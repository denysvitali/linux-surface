package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
)

// Evidence readers never run a trial, open a device, or grant capture permission.
// Boot and kernel identity are required even when the helper reports failure.
type trialRecord map[string]any

func trObject(r trialRecord, key string) trialRecord { v, _ := r[key].(map[string]any); return v }
func trList(r trialRecord, key string) []any         { v, _ := r[key].([]any); return v }
func trString(r trialRecord, key string) string      { v, _ := r[key].(string); return v }
func trBool(r trialRecord, key string) bool          { return r[key] == true }
func trNumber(r trialRecord, key string) float64     { v, _ := r[key].(float64); return v }
func trNonempty(r trialRecord, key string) bool {
	v := r[key]
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case []any:
		for _, item := range x {
			if trNonempty(trialRecord{"v": item}, "v") {
				return true
			}
		}
		return false
	case map[string]any:
		for _, item := range x {
			if trNonempty(trialRecord{"v": item}, "v") {
				return true
			}
		}
		return false
	default:
		return true
	}
}
func trFailed(r trialRecord) bool {
	for _, key := range []string{"error", "cleanup_error", "cleanup_errors", "background_errors", "kernel_faults", "kernel_window_error", "capture_error", "recovery_error", "gpu_output_error"} {
		if trNonempty(r, key) {
			return true
		}
	}
	return false
}
func trialIdentity(c *AutoContext) (string, string) {
	boot, _ := c.Read("/proc/sys/kernel/random/boot_id")
	release, _ := c.Read("/proc/sys/kernel/osrelease")
	return boot, release
}
func trialEvidence(c *AutoContext, id, command string, relatives ...string) (trialRecord, *AutoResult) {
	boot, release := trialIdentity(c)
	missing := AutoResult{ID: id, Status: "blocked", Detail: "No current-boot/kernel evidence; run " + command + " in its authorized trial. Evidence is read only; no workload started."}
	if boot == "" || release == "" {
		missing.Detail = "Current boot/kernel identity unavailable; cannot admit evidence from " + command
		return nil, &missing
	}
	pattern := "/var/lib/spx-boot-diagnostics/functional/*/"
	if words, err := c.Read("/proc/cmdline"); err == nil {
		for _, word := range strings.Fields(words) {
			if strings.HasPrefix(word, "spx_attempt=") {
				attempt := strings.TrimPrefix(word, "spx_attempt=")
				if regexp.MustCompile(`^[0-9]{8}[a-z0-9]+$`).MatchString(attempt) {
					pattern = "/var/lib/spx-boot-diagnostics/functional/" + attempt + "/"
				}
			}
		}
	}
	for _, relative := range relatives {
		paths, _ := c.Glob(pattern + relative)
		var matched trialRecord
		for _, path := range paths {
			text, err := c.Read(path)
			if err != nil {
				continue
			}
			var record trialRecord
			if json.Unmarshal([]byte(text), &record) != nil || record == nil {
				if strings.Contains(pattern, "*") {
					continue
				}
				return nil, &AutoResult{ID: id, Status: "error", Detail: "Invalid trial JSON at " + path}
			}
			identity := record
			if trString(identity, "boot_id") == "" {
				identity = trObject(record, "before")
			}
			if trString(identity, "boot_id") != boot || trString(identity, "release") != release {
				continue
			}
			if matched != nil {
				return nil, &AutoResult{ID: id, Status: "error", Detail: "Multiple current-boot trial results; evidence selection is ambiguous"}
			}
			matched = record
		}
		if matched != nil {
			return matched, nil
		}
	}
	return nil, &missing
}
func trialVerdict(id string, good bool, scope string) AutoResult {
	status := "fail"
	if !good {
		scope = "Required proof failed or incomplete: " + scope
	}
	if good {
		status = "pass"
	}
	return AutoResult{ID: id, Status: status, Detail: scope}
}

var trialPCMError = regexp.MustCompile(`(?i)underrun|overrun|error`)

func trialAudioPhases(r trialRecord, reopen bool) bool {
	capture := trObject(r, "capture")
	phases := trList(capture, "phases")
	expected := []string{"left", "right", "both"}
	if reopen {
		expected = []string{"cycle-1-left", "cycle-1-right", "cycle-1-both", "cycle-2-left", "cycle-2-right", "cycle-2-both"}
	}
	if len(phases) != len(expected) {
		return false
	}
	seen := map[string]bool{}
	for _, raw := range phases {
		phase, _ := raw.(map[string]any)
		name := trString(phase, "name")
		if seen[name] || !trBool(trObject(phase, "score"), "passed") || trNumber(phase, "end_frame") <= trNumber(phase, "start_frame") {
			return false
		}
		score := trObject(phase, "score")
		if trNumber(trObject(score, "metrics"), "clipped") > 0 {
			return false
		}
		seen[name] = true
	}
	for _, name := range expected {
		if !seen[name] {
			return false
		}
	}
	return true
}
func trialAudioClean(r trialRecord) bool {
	return trBool(r, "success") && trBool(r, "parked") && !trFailed(r) && !trialPCMError.MatchString(trString(trObject(r, "capture"), "log")) && !trNonempty(trObject(r, "capture"), "error")
}
func trialPCMAdvanced(pcm trialRecord) bool {
	statusPtr := regexp.MustCompile(`(?m)^hw_ptr\s*:\s*(\d+)$`)
	first := statusPtr.FindStringSubmatch(trString(pcm, "running_status"))
	last := statusPtr.FindStringSubmatch(trString(pcm, "consumed_status"))
	if len(first) != 2 || len(last) != 2 {
		return false
	}
	var a, b uint64
	if _, err := fmt.Sscan(first[1], &a); err != nil {
		return false
	}
	if _, err := fmt.Sscan(last[1], &b); err != nil {
		return false
	}
	return b > a
}

func trialAudioConsumed(r trialRecord) bool {
	cycles := trList(trObject(r, "reopen"), "cycles")
	if len(cycles) != 2 {
		return false
	}
	for _, raw := range cycles {
		cycle, _ := raw.(map[string]any)
		pcm := trObject(cycle, "pcm")
		if !trBool(pcm, "dsp_consumed") || !trialPCMAdvanced(pcm) || trString(pcm, "format") != "S16_LE/48000/stereo" || trialPCMError.MatchString(trString(pcm, "log")) {
			return false
		}
	}
	return true
}
func trialAudioAmpsOff(r trialRecord) bool {
	control := trObject(trObject(r, "capture"), "amps_off_control")
	scores := trList(control, "scores")
	if len(scores) < 2 || trNumber(control, "end_frame") <= trNumber(control, "start_frame") || int(trNumber(trObject(r, "control_parked_state"), "GPIO_VAL"))&0x1e != 0x18 {
		return false
	}
	for _, raw := range scores {
		score, _ := raw.(map[string]any)
		targets := trObject(score, "targets")
		if len(targets) == 0 {
			return false
		}
		for _, raw := range targets {
			target, _ := raw.(map[string]any)
			if target == nil {
				return false
			}
			rms, rmsOK := target["rms"].(float64)
			baseline, bOK := target["baseline_rise_db"].(float64)
			neighbor, nOK := target["neighbor_rise_db"].(float64)
			if !rmsOK || !bOK || !nOK || !(rms < 1 || baseline < 10 || neighbor < 10) {
				return false
			}
		}
	}
	return true
}
func trialAudioRow(c *AutoContext, id string) AutoResult {
	command := "trial.py arm-audio ATTEMPT --audio-action reopen --allow-amp-power --allow-playback --allow-capture before trial.py boot ATTEMPT"
	relatives := []string{"audio/reopen-result.json"}
	if id == "audio.acoustic" {
		relatives = append(relatives, "audio/feedback-result.json")
		command += "; trial.py audio ATTEMPT --audio-action feedback --microphone-array --allow-amp-power --allow-playback --allow-capture supplies amps-off control"
	}
	r, issue := trialEvidence(c, id, command, relatives...)
	if issue != nil {
		return *issue
	}
	reopen := trString(r, "action") == "reopen"
	if !trialAudioClean(r) {
		return trialVerdict(id, false, "Current-boot audio helper failed or did not verify clean amplifier parking/capture cleanup")
	}
	if !trialAudioPhases(r, reopen) {
		return trialVerdict(id, false, "Current-boot audio tone phases failed, are incomplete, or capture did not advance without clipping")
	}
	switch id {
	case "audio.speakers":
		return trialVerdict(id, trialAudioConsumed(r), "Quiet stereo native DSP consumption and left/right/both microphone tone detection across two playback owners; no SPL, physical placement or listening-quality claim")
	case "audio.acoustic":
		if !trNonempty(trObject(r, "capture"), "amps_off_control") {
			// Reopen has quiet references but does not perform the feedback-only control.
			feedback, issue := trialEvidence(c, id, command, "audio/feedback-result.json")
			if issue != nil {
				return AutoResult{ID: id, Status: "blocked", Detail: "Reopen tones passed, but amps-off rejection is not covered; run trial.py audio ATTEMPT --audio-action feedback --microphone-array --allow-amp-power --allow-playback --allow-capture"}
			}
			r = feedback
		}
		return trialVerdict(id, trialAudioClean(r) && trialAudioPhases(r, trString(r, "action") == "reopen") && trBool(r, "acoustic_passed") && trialAudioAmpsOff(r), "All quiet/noise-relative acoustic phases and physical amps-off crosstalk rejection; uncalibrated short tone test")
	case "audio.microphones":
		capture := trObject(r, "capture")
		return trialVerdict(id, trBool(r, "microphone_capture") && trNumber(capture, "frames") > 144000 && trNumber(trObject(capture, "baseline"), "peak") < 32000 && trNumber(trObject(capture, "baseline"), "rms") > 0 && capture["recording"] == nil, "Advancing unclipped DMIC1 native capture with known channel tones; raw recording discarded. DMIC0/array independence and full capture teardown are NOT covered by reopen")
	default:
		evidence := trObject(r, "reopen")
		cycles := trList(evidence, "cycles")
		pids := map[float64]bool{}
		good := len(cycles) == 2 && trBool(evidence, "passed") && trBool(evidence, "asm_kept") && trNumber(evidence, "capture_pid") > 0
		for _, raw := range cycles {
			cycle, _ := raw.(map[string]any)
			pcm := trObject(cycle, "pcm")
			pid := trNumber(pcm, "pid")
			pids[pid] = true
			status := trString(cycle, "capture_status_after_close")
			owner := regexp.MustCompile(fmt.Sprintf(`(?m)^owner_pid\s*:\s*%.0f$`, trNumber(evidence, "capture_pid")))
			good = good && pid > 0 && trBool(cycle, "passed") && trString(cycle, "closed_status") == "closed" && !trialPCMError.MatchString(trString(pcm, "log")) && trBool(trObject(cycle, "teardown"), "passed") && trNumber(cycle, "capture_end_frame") > trNumber(cycle, "capture_start_frame") && regexp.MustCompile(`(?m)^state:\s+RUNNING$`).MatchString(status) && owner.MatchString(status)
		}
		return trialVerdict(id, good && len(pids) == 2, "Two distinct retained Linux playback PCM owners, intermediate close, continuous capture and clean amplifier parking. Full DSP teardown (UNMAP/AFE STOP) is NOT covered")
	}
}

func trialThermalResponse(c *AutoContext) AutoResult {
	const id = "thermal.response"
	r, issue := trialEvidence(c, id, "trial.py thermal ATTEMPT --thermal-combined --thermal-cpu-stress-ng PATH", "combined-thermal/result.json", "cpu-thermal/result.json")
	if issue != nil {
		return *issue
	}
	trip := trNumber(r, "cpu_passive_trip_mc")
	good := !trFailed(r) && trBool(r, "recovered") && (trip == 50000 || trip == 55000 || trip == 75000) && trBool(r, "workers_stopped")
	before := trObject(trObject(r, "before"), "clusters")
	responses := trObject(r, "response_evidence")
	for _, key := range []string{"0", "1"} {
		base := trObject(before, key)
		evidence := trObject(responses, key)
		crossing, response, recovery := trObject(evidence, "crossing"), trObject(evidence, "response"), trObject(evidence, "recovery")
		good = good && base != nil && crossing != nil && response != nil && recovery != nil && trNumber(base, "temperature") < trip-5000 && trNumber(base, "state") == 0 && trNumber(base, "limit") > 0 && trNumber(evidence, "trip_mc") == trip && trNumber(evidence, "recovery_below_mc") == trip-5000 && trNumber(crossing, "temperature") >= trip && trNumber(response, "seconds") >= trNumber(crossing, "seconds") && trNumber(response, "state") > 0 && trNumber(response, "limit") < trNumber(base, "limit") && trNumber(recovery, "seconds") > trNumber(response, "seconds") && trNumber(recovery, "temperature") < trip-5000 && trNumber(recovery, "state") == 0 && trNumber(recovery, "limit") == trNumber(base, "limit")
	}
	if trip == 50000 {
		// The arithmetic self-check exists only for the native workload; the
		// Python fallback is proven by the recorded crossing under load instead.
		native := !strings.HasPrefix(trString(r, "cpu_workload"), "Python")
		good = good && (!native || trBool(r, "native_arithmetic_passed")) && trBool(r, "gpu_stopped") && trBool(r, "gpu_group_stopped") && trBool(r, "response_load_witnessed")
	}
	return trialVerdict(id, good, fmt.Sprintf("Real CPU crossing, automatic cooling/maximum reduction and natural hysteresis recovery for both clusters at %.0f mC; temporary-policy scope only, normal 75C/GPU/OEM envelope remains open", trip))
}

func trialSleepGood(r trialRecord) bool {
	sleep := trObject(r, "sleep")
	if sleep == nil {
		sleep = trObject(r, "verified_sleep")
	}
	after := trObject(r, "after")
	cleanup := trObject(r, "cleanup")
	good := !trNonempty(sleep, "new_kernel_faults") && trBool(r, "complete") && trBool(r, "functional_pass") && !trFailed(r) && trBool(trObject(r, "direct_prerequisite"), "complete") && trBool(sleep, "boot_unchanged") && trNumber(sleep, "sleep_seconds") >= 15 && trNumber(sleep, "sleep_seconds") <= 45 && trNumber(sleep, "irq_after") > trNumber(sleep, "irq_before") && int(trNumber(sleep, "event"))&0xa0 == 0xa0 && trNumber(after, "download_bytes") == 1000000 && trNumber(after, "fsync_readback_bytes") == 65536
	for _, key := range []string{"kernel_entered", "kernel_exited", "service_completed", "alarm_disabled", "user_thawed"} {
		good = good && trBool(sleep, key)
	}
	for _, key := range []string{"masks_restored", "owned_files_removed", "idle_inhibitor_reaped"} {
		good = good && trBool(cleanup, key)
	}
	beforeServices := trObject(trObject(r, "before"), "services")
	afterServices := trObject(after, "services")
	a, _ := json.Marshal(beforeServices)
	b, _ := json.Marshal(afterServices)
	good = good && len(beforeServices) > 0 && string(a) == string(b)
	for _, phase := range []string{"before", "after"} {
		streams := trObject(trObject(r, phase), "streams")
		for _, name := range []string{"accelerometer", "gyroscope", "magnetometer"} {
			good = good && trBool(trObject(streams, name), "finite_stream_and_disable")
		}
	}
	if trString(r, "audio_mode") == "parked-retention" || trString(r, "audio_mode") == "live-retention" || trNonempty(r, "live_audio") {
		good = good && trBool(trObject(sleep, "audio_retention"), "complete") && trBool(trObject(trObject(r, "direct_prerequisite"), "audio_retention"), "complete") && trBool(trObject(cleanup, "parked_audio"), "restored")
	}
	return good
}
func trialSuspendRecovery(c *AutoContext) AutoResult {
	const id = "pwr.suspend-recovery"
	r, issue := trialEvidence(c, id, "trial.py systemd-suspend ATTEMPT --parked-audio (inside systemd-run --unit=spx-systemd-suspend)", "systemd-suspend-recovery/result.json", "systemd-suspend/result.json", "audio-resume/result.json")
	if issue != nil {
		return *issue
	}
	return trialVerdict(id, trialSleepGood(r), "Normal 15–45s AC s2idle, ordered kernel/service freeze/thaw, PMIC RTC IRQ/alarm cleanup, same fresh sensor owners, WLAN 1 MB and storage 64 KiB recovery, restored masks; powered retention only, no energy-saving or full display/BT/camera/decoder resume claim")
}
func trialFirmwareStability(c *AutoContext) AutoResult {
	const id = "fw.stability"
	r, issue := trialEvidence(c, id, "trial.py systemd-suspend ATTEMPT --live-audio-resume --allow-amp-power --allow-playback --allow-capture (inside spx-systemd-suspend)", "audio-resume/result.json")
	if issue != nil {
		return *issue
	}
	if !trialSleepGood(r) || !trBool(trObject(r, "pre_playback"), "acoustic_passed") || !trBool(trObject(r, "post_playback"), "acoustic_passed") {
		return trialVerdict(id, false, "Current-boot live audio/firmware suspend helper failed a pre/post functional oracle or cleanup")
	}
	// Existing audio_resume proves the retained ADSP/SDSP subset. A future
	// combined result must supply each functional oracle; complete alone cannot
	// close combined firmware stability. Missing CDSP transport stays visible.
	combined := trObject(r, "combined_firmware")
	if combined == nil {
		return AutoResult{ID: id, Status: "blocked", Detail: "Current-boot retained audio/sensor/network/storage resume passed; full combined firmware workload is missing: 30s simultaneous use, pre/post Wi-Fi/BT/GL/Vulkan/decoder/TPM and CDSP workload. trial.py systemd-suspend --live-audio-resume supplies only the retained subset; CDSP FastRPC/loader prerequisite remains parked"}
	}
	if trNumber(combined, "seconds") < 30 || !trBool(combined, "owners_preserved") || !trBool(combined, "clean_teardown") || combined["faults"] == nil || trNonempty(combined, "faults") {
		return trialVerdict(id, false, "Combined firmware duration, owner preservation, fresh-fault scan or teardown failed")
	}
	for _, phase := range []string{"before", "after"} {
		tests := trObject(combined, phase)
		for _, name := range []string{"audio", "sensors", "wifi", "bluetooth", "gl", "vulkan", "decoder", "tpm", "cdsp"} {
			oracle := trObject(tests, name)
			if oracle == nil || trString(oracle, "status") == "blocked" {
				return AutoResult{ID: id, Status: "blocked", Detail: "Combined firmware functional workload missing/blocked: " + phase + " " + name}
			}
			if trString(oracle, "status") != "pass" {
				return trialVerdict(id, false, "Combined firmware functional oracle failed: "+phase+" "+name)
			}
		}
	}
	return trialVerdict(id, true, "30s combined firmware use, all named pre/post functional oracles, unchanged owners, no fresh SSR/watchdog/SMMU faults and clean teardown")
}
func trialWatchdogRecovery(c *AutoContext) AutoResult {
	const id = "diag.watchdog-recovery"
	boot, release := trialIdentity(c)
	missing := AutoResult{ID: id, Status: "blocked", Detail: "No current-boot watchdog reset collection; run trial.py watchdog-reset ATTEMPT separately, then trial.py watchdog-collect ATTEMPT on the next boot (automatic boot hook collects it). No watchdog opened by validator"}
	if boot == "" || release == "" {
		return missing
	}
	text, err := c.Read(filepath.Join("/var/lib/spx-boot-diagnostics/boots", boot, "watchdog-reset/result.json"))
	if err != nil {
		return missing
	}
	var r trialRecord
	if json.Unmarshal([]byte(text), &r) != nil || r == nil {
		return AutoResult{ID: id, Status: "error", Detail: "Invalid watchdog collector JSON"}
	}
	if trString(r, "boot_id") != boot || trString(r, "release") != release {
		return missing
	}
	if trString(r, "status") == "fail" {
		return trialVerdict(id, false, "Explicit watchdog reset/collector failed; inspect the retained result")
	}
	marker := trObject(r, "marker")
	if !trBool(r, "runtime_watchdog_restored") || !trBool(r, "consumed") || trString(marker, "nonce") == "" || trString(marker, "boot_id") == boot || trString(marker, "boot_id") == "" || trString(r, "previous_boot_id") != trString(marker, "boot_id") || !trBool(marker, "armed") || trNumber(marker, "timeout_seconds") != 10 || trNumber(marker, "pretimeout_seconds") != 0 || marker["pre_bootstatus"] == nil || int(trNumber(marker, "pre_bootstatus"))&0x20 != 0 || r["bootstatus"] == nil || int(trNumber(r, "bootstatus"))&0x20 == 0 || !trBool(r, "complete") || trString(r, "status") != "pass" {
		return AutoResult{ID: id, Status: "blocked", Detail: "Watchdog marker consumed without verified immediately previous boot and new WDIOF_CARDRESET; reset cause unavailable/ambiguous. Inspect trial.py watchdog-collect result; changed boot alone is insufficient"}
	}
	return trialVerdict(id, true, "Consumed nonce links the immediately previous armed 10s boot to this boot; WDIOC_GETBOOTSTATUS newly reports WDIOF_CARDRESET; PID1 watchdog restored. This proves reset and boot recovery only")
}
