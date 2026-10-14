package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func trialFixtureContext(t *testing.T) *AutoContext {
	t.Helper()
	c := &AutoContext{Root: t.TempDir(), Fixture: true, Run: func(...string) (string, error) { t.Fatal("evidence reader attempted a command"); return "", nil }}
	autoAudioFixture(t, c.Root, "/proc/sys/kernel/random/boot_id", "current")
	autoAudioFixture(t, c.Root, "/proc/sys/kernel/osrelease", "kernel")
	return c
}
func trialFixture(t *testing.T, c *AutoContext, relative string, r trialRecord) {
	t.Helper()
	text, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	autoAudioFixture(t, c.Root, "/var/lib/spx-boot-diagnostics/functional/20261014test/"+relative, string(text))
}
func trialAudioFixtureRecord() trialRecord {
	phases := []any{}
	cycles := []any{}
	for n := 1; n <= 2; n++ {
		for _, name := range []string{"left", "right", "both"} {
			phases = append(phases, trialRecord{"name": fmt.Sprintf("cycle-%d-%s", n, name), "start_frame": 100, "end_frame": 1000, "score": trialRecord{"passed": true, "metrics": trialRecord{"clipped": 0}}})
		}
		cycles = append(cycles, trialRecord{"passed": true, "capture_start_frame": 100, "capture_end_frame": 1000, "closed_status": "closed", "teardown": trialRecord{"passed": true}, "capture_status_after_close": "state: RUNNING\nowner_pid: 42", "pcm": trialRecord{"pid": n, "dsp_consumed": true, "running_status": "state: RUNNING\nhw_ptr: 2400", "consumed_status": "state: RUNNING\nhw_ptr: 480000", "format": "S16_LE/48000/stereo", "log": ""}})
	}
	return trialRecord{"boot_id": "current", "release": "kernel", "action": "reopen", "success": true, "parked": true, "acoustic_passed": true, "microphone_capture": true, "capture": trialRecord{"phases": phases, "frames": 200000, "recording": nil, "baseline": trialRecord{"peak": 100, "rms": 20}}, "reopen": trialRecord{"passed": true, "asm_kept": true, "capture_pid": 42, "cycles": cycles}}
}
func addAmpsOff(r trialRecord) {
	// Fixtures are serialized before parsing, just as actual helper JSON is.
	capture := r["capture"].(trialRecord)
	capture["amps_off_control"] = trialRecord{"start_frame": 10, "end_frame": 100, "scores": []any{
		trialRecord{"targets": trialRecord{"440": trialRecord{"rms": 0.1, "baseline_rise_db": 0, "neighbor_rise_db": 0}}},
		trialRecord{"targets": trialRecord{"660": trialRecord{"rms": 0.1, "baseline_rise_db": 0, "neighbor_rise_db": 0}}},
	}}
	r["control_parked_state"] = trialRecord{"GPIO_VAL": 24}
}
func TestTrialAudioRowsPassFailBlocked(t *testing.T) {
	for _, id := range []string{"audio.speakers", "audio.acoustic", "audio.microphones", "audio.lifecycle"} {
		t.Run(id, func(t *testing.T) {
			c := trialFixtureContext(t)
			if result := trialAudioRow(c, id); result.Status != "blocked" || !strings.Contains(result.Detail, "arm-audio") {
				t.Fatal(result)
			}
			r := trialAudioFixtureRecord()
			addAmpsOff(r)
			trialFixture(t, c, "audio/reopen-result.json", r)
			if result := trialAudioRow(c, id); result.Status != "pass" {
				t.Fatal(result)
			} else if id == "audio.lifecycle" && !strings.Contains(result.Detail, "UNMAP/AFE STOP) is NOT covered") {
				t.Fatal(result)
			}
			r["success"] = false
			trialFixture(t, c, "audio/reopen-result.json", r)
			if result := trialAudioRow(c, id); result.Status != "fail" {
				t.Fatal(result)
			}
			r["boot_id"] = "earlier"
			trialFixture(t, c, "audio/reopen-result.json", r)
			if result := trialAudioRow(c, id); result.Status != "blocked" {
				t.Fatal(result)
			}
			r["boot_id"] = "current"
			r["release"] = "old-kernel"
			trialFixture(t, c, "audio/reopen-result.json", r)
			if result := trialAudioRow(c, id); result.Status != "blocked" {
				t.Fatal(result)
			}
		})
	}
}
func TestTrialAudioRejectsMissingOrFailedOracle(t *testing.T) {
	for _, test := range []struct {
		id     string
		mutate func(trialRecord)
	}{
		{"audio.speakers", func(r trialRecord) {
			r["reopen"].(trialRecord)["cycles"].([]any)[1].(trialRecord)["pcm"].(trialRecord)["dsp_consumed"] = false
		}},
		{"audio.lifecycle", func(r trialRecord) {
			r["reopen"].(trialRecord)["cycles"].([]any)[1].(trialRecord)["pcm"].(trialRecord)["pid"] = 1
		}},
		{"audio.lifecycle", func(r trialRecord) {
			r["reopen"].(trialRecord)["cycles"].([]any)[0].(trialRecord)["closed_status"] = "RUNNING"
		}},
		{"audio.microphones", func(r trialRecord) { r["capture"].(trialRecord)["baseline"].(trialRecord)["peak"] = 32767 }},
		{"audio.microphones", func(r trialRecord) {
			r["capture"].(trialRecord)["phases"].([]any)[0].(trialRecord)["score"].(trialRecord)["metrics"].(trialRecord)["clipped"] = 1
		}},
		{"audio.acoustic", func(r trialRecord) { r["control_parked_state"] = trialRecord{"GPIO_VAL": 30} }},
	} {
		c := trialFixtureContext(t)
		r := trialAudioFixtureRecord()
		addAmpsOff(r)
		test.mutate(r)
		trialFixture(t, c, "audio/reopen-result.json", r)
		if result := trialAudioRow(c, test.id); result.Status != "fail" {
			t.Fatalf("%s: %+v", test.id, result)
		}
	}
	c := trialFixtureContext(t)
	r := trialAudioFixtureRecord()
	trialFixture(t, c, "audio/reopen-result.json", r)
	if result := trialAudioRow(c, "audio.acoustic"); result.Status != "blocked" || !strings.Contains(result.Detail, "feedback") {
		t.Fatal(result)
	}
	feedback := trialAudioFixtureRecord()
	feedback["action"] = "feedback"
	phases := []any{}
	for _, name := range []string{"left", "right", "both"} {
		phases = append(phases, trialRecord{"name": name, "start_frame": 10, "end_frame": 100, "score": trialRecord{"passed": true}})
	}
	feedback["capture"].(trialRecord)["phases"] = phases
	addAmpsOff(feedback)
	trialFixture(t, c, "audio/feedback-result.json", feedback)
	if result := trialAudioRow(c, "audio.acoustic"); result.Status != "pass" {
		t.Fatal(result)
	}
	feedback["success"] = false
	trialFixture(t, c, "audio/feedback-result.json", feedback)
	if result := trialAudioRow(c, "audio.acoustic"); result.Status != "fail" {
		t.Fatal(result)
	}
}
func trialThermalFixtureRecord() trialRecord {
	clusters := trialRecord{}
	evidence := trialRecord{}
	for _, key := range []string{"0", "1"} {
		clusters[key] = trialRecord{"temperature": 44000, "state": 0, "limit": 2000}
		evidence[key] = trialRecord{"trip_mc": 50000, "recovery_below_mc": 45000, "crossing": trialRecord{"seconds": 5, "temperature": 50001}, "response": trialRecord{"seconds": 6, "state": 1, "limit": 1800}, "recovery": trialRecord{"seconds": 8, "temperature": 44999, "state": 0, "limit": 2000}}
	}
	return trialRecord{"boot_id": "current", "release": "kernel", "cpu_passive_trip_mc": 50000, "before": trialRecord{"clusters": clusters}, "response_evidence": evidence, "recovered": true, "workers_stopped": true, "gpu_stopped": true, "gpu_group_stopped": true, "native_arithmetic_passed": true, "response_load_witnessed": true, "gpu_completed_rows": []any{trialRecord{"renderer": "FD680"}}}
}
func TestTrialThermalPassFailBlocked(t *testing.T) {
	c := trialFixtureContext(t)
	if result := trialThermalResponse(c); result.Status != "blocked" || !strings.Contains(result.Detail, "trial.py thermal") {
		t.Fatal(result)
	}
	r := trialThermalFixtureRecord()
	trialFixture(t, c, "combined-thermal/result.json", r)
	if result := trialThermalResponse(c); result.Status != "pass" {
		t.Fatal(result)
	}
	r["complete"] = true
	r["response_evidence"].(trialRecord)["1"].(trialRecord)["recovery"] = nil
	trialFixture(t, c, "combined-thermal/result.json", r)
	if result := trialThermalResponse(c); result.Status != "fail" {
		t.Fatal(result)
	}
	r["boot_id"] = "old"
	trialFixture(t, c, "combined-thermal/result.json", r)
	if result := trialThermalResponse(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}
func trialSleepFixtureRecord() trialRecord {
	streams := trialRecord{}
	for _, name := range []string{"accelerometer", "gyroscope", "magnetometer"} {
		streams[name] = trialRecord{"finite_stream_and_disable": true}
	}
	services := trialRecord{"sensor": trialRecord{"MainPID": "42", "NRestarts": "0"}}
	return trialRecord{"boot_id": "current", "release": "kernel", "complete": true, "functional_pass": true, "audio_mode": "parked-retention", "direct_prerequisite": trialRecord{"complete": true, "audio_retention": trialRecord{"complete": true}}, "sleep": trialRecord{"boot_unchanged": true, "sleep_seconds": 30, "kernel_entered": true, "kernel_exited": true, "service_completed": true, "irq_before": 1, "irq_after": 2, "event": 160, "alarm_disabled": true, "user_thawed": true, "audio_retention": trialRecord{"complete": true}}, "before": trialRecord{"services": services, "streams": streams}, "after": trialRecord{"services": services, "streams": streams, "download_bytes": 1000000, "fsync_readback_bytes": 65536}, "cleanup": trialRecord{"masks_restored": true, "owned_files_removed": true, "idle_inhibitor_reaped": true, "parked_audio": trialRecord{"restored": true}}, "pre_playback": trialRecord{"acoustic_passed": true}, "post_playback": trialRecord{"acoustic_passed": true}}
}
func addCombined(r trialRecord) {
	tests := trialRecord{}
	for _, name := range []string{"audio", "sensors", "wifi", "bluetooth", "gl", "vulkan", "decoder", "tpm", "cdsp"} {
		tests[name] = trialRecord{"status": "pass"}
	}
	r["combined_firmware"] = trialRecord{"seconds": 30, "before": tests, "after": tests, "owners_preserved": true, "clean_teardown": true, "faults": []any{}}
}
func TestTrialSuspendAndFirmwarePassFailBlocked(t *testing.T) {
	for _, test := range []struct {
		id, relative string
		run          func(*AutoContext) AutoResult
	}{
		{"pwr.suspend-recovery", "systemd-suspend/result.json", trialSuspendRecovery},
		{"fw.stability", "audio-resume/result.json", trialFirmwareStability},
	} {
		c := trialFixtureContext(t)
		if result := test.run(c); result.Status != "blocked" || !strings.Contains(result.Detail, "systemd-suspend") {
			t.Fatal(result)
		}
		r := trialSleepFixtureRecord()
		addCombined(r)
		trialFixture(t, c, test.relative, r)
		if result := test.run(c); result.Status != "pass" {
			t.Fatal(result)
		}
		r["sleep"].(trialRecord)["service_completed"] = false
		trialFixture(t, c, test.relative, r)
		if result := test.run(c); result.Status != "fail" {
			t.Fatal(result)
		}
		r["boot_id"] = "old"
		trialFixture(t, c, test.relative, r)
		if result := test.run(c); result.Status != "blocked" {
			t.Fatal(result)
		}
	}
}
func TestTrialFirmwareMissingCoverageAndFaults(t *testing.T) {
	c := trialFixtureContext(t)
	r := trialSleepFixtureRecord()
	trialFixture(t, c, "audio-resume/result.json", r)
	if result := trialFirmwareStability(c); result.Status != "blocked" || !strings.Contains(result.Detail, "CDSP") {
		t.Fatal(result)
	}
	addCombined(r)
	r["combined_firmware"].(trialRecord)["before"].(trialRecord)["cdsp"] = trialRecord{"status": "blocked"}
	trialFixture(t, c, "audio-resume/result.json", r)
	if result := trialFirmwareStability(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	addCombined(r)
	r["combined_firmware"].(trialRecord)["faults"] = []any{"SSR"}
	trialFixture(t, c, "audio-resume/result.json", r)
	if result := trialFirmwareStability(c); result.Status != "fail" {
		t.Fatal(result)
	}
}
func TestTrialWatchdogPassFailBlocked(t *testing.T) {
	c := trialFixtureContext(t)
	if result := trialWatchdogRecovery(c); result.Status != "blocked" || !strings.Contains(result.Detail, "watchdog-reset") {
		t.Fatal(result)
	}
	path := "/var/lib/spx-boot-diagnostics/boots/current/watchdog-reset/result.json"
	r := trialRecord{"boot_id": "current", "release": "kernel", "previous_boot_id": "prior", "runtime_watchdog_restored": true, "consumed": true, "complete": true, "status": "pass", "bootstatus": 32, "marker": trialRecord{"boot_id": "prior", "nonce": "nonce", "armed": true, "timeout_seconds": 10, "pretimeout_seconds": 0, "pre_bootstatus": 0}}
	write := func() { text, _ := json.Marshal(r); autoAudioFixture(t, c.Root, path, string(text)) }
	write()
	if result := trialWatchdogRecovery(c); result.Status != "pass" {
		t.Fatal(result)
	}
	r["status"] = "fail"
	write()
	if result := trialWatchdogRecovery(c); result.Status != "fail" {
		t.Fatal(result)
	}
	r["status"] = "pass"
	r["previous_boot_id"] = "older"
	write()
	if result := trialWatchdogRecovery(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	r["previous_boot_id"] = "prior"
	r["bootstatus"] = 0
	write()
	if result := trialWatchdogRecovery(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	r["bootstatus"] = 32
	r["marker"].(trialRecord)["pre_bootstatus"] = 32
	write()
	if result := trialWatchdogRecovery(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	r["boot_id"] = "prior"
	write()
	if result := trialWatchdogRecovery(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}
