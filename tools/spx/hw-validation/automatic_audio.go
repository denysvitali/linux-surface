package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

func automaticAudioChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "audio.alsa", Title: "ALSA cards and PCM interfaces", Area: "Audio", Kind: "inventory", Boxes: []string{"A01", "A02", "A03", "A04"}, Run: autoAudioALSA},
		{ID: "audio.controls", Title: "Native audio routing control capabilities", Area: "Audio", Kind: "inventory", Boxes: []string{"A01", "A02", "A03"}, Run: autoAudioControls},
		{ID: "audio.soundwire", Title: "SoundWire core enumeration", Area: "Audio", Kind: "inventory", Boxes: []string{"A01", "A03"}, Run: autoAudioSoundWire},
		{ID: "audio.services", Title: "Desktop audio service availability", Area: "Audio", Kind: "inventory", Boxes: []string{"A03", "A04"}, Run: autoAudioServices},
		{ID: "audio.graph", Title: "Desktop audio graph and default routing", Area: "Audio", Kind: "inventory", Boxes: []string{"A01", "A02", "A03", "A04"}, Run: autoAudioGraph},
		{ID: "audio.feeder", Title: "Native desktop feeder readiness", Area: "Audio", Kind: "inventory", Boxes: []string{"A01", "A03"}, Run: autoAudioFeeder},
		{ID: "audio.speakers", Title: "Physical speaker output", Area: "Audio", Kind: "functional", Boxes: []string{"A01"}, Run: func(c *AutoContext) AutoResult { return trialAudioRow(c, "audio.speakers") }},
		{ID: "audio.acoustic", Title: "Speaker acoustic feedback", Area: "Audio", Kind: "functional", Boxes: []string{"A01", "A02"}, Run: func(c *AutoContext) AutoResult { return trialAudioRow(c, "audio.acoustic") }},
		{ID: "audio.microphones", Title: "Internal microphone stimulus capture", Area: "Audio", Kind: "functional", Boxes: []string{"A02"}, Run: autoAudioMicrophones},
		{ID: "audio.lifecycle", Title: "Native audio stream lifecycle", Area: "Audio", Kind: "functional", Boxes: []string{"A03"}, Run: func(c *AutoContext) AutoResult { return trialAudioRow(c, "audio.lifecycle") }},
		{ID: "audio.external", Title: "External USB and Bluetooth audio data paths", Area: "Audio", Kind: "functional", Boxes: []string{"A04"}, Run: autoAudioExternal},
	}
}

func autoAudioResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}

var autoAudioCardLine = regexp.MustCompile(`^\s*(\d+)\s+\[[^\]]+\]\s*:`)

func autoAudioCards(text string) (int, []string) {
	count := 0
	var internal []string
	current, spx := "", false
	flush := func() {
		if current != "" && spx {
			internal = append(internal, current)
		}
	}
	for _, line := range strings.Split(text, "\n") {
		if match := autoAudioCardLine.FindStringSubmatch(line); match != nil {
			flush()
			current, spx = match[1], false
			count++
		}
		if strings.Contains(line, "Surface Pro X") {
			spx = true
		}
	}
	flush()
	return count, internal
}

func autoAudioALSA(c *AutoContext) AutoResult {
	const id = "audio.alsa"
	cards, err := c.Read("/proc/asound/cards")
	if err != nil {
		return autoAudioResult(id, "blocked", "Cannot read ALSA card metadata; kernel audio support and procfs read permission required.")
	}
	count, internal := autoAudioCards(cards)
	if count == 0 {
		return autoAudioResult(id, "blocked", "No ALSA card interface exposed; kernel/firmware audio support is a prerequisite, not proof of hardware absence.")
	}
	pcm, err := c.Read("/proc/asound/pcm")
	if err != nil {
		return autoAudioResult(id, "blocked", "ALSA cards exposed but PCM metadata unreadable; procfs permission and PCM driver support required.")
	}
	playback, capture := 0, 0
	for _, line := range strings.Split(pcm, "\n") {
		if strings.Contains(line, ": playback ") {
			playback++
		}
		if strings.Contains(line, ": capture ") {
			capture++
		}
	}
	if playback+capture == 0 {
		return autoAudioResult(id, "blocked", "ALSA cards exposed but no playback/capture PCM interface listed; machine routing and PCM support required.")
	}
	return autoAudioResult(id, "observed", fmt.Sprintf("ALSA cards=%d, identified SPX cards=%d, playback interfaces=%d, capture interfaces=%d; nodes do not establish acoustic output or microphone quality.", count, len(internal), playback, capture))
}

func autoAudioControls(c *AutoContext) AutoResult {
	const id = "audio.controls"
	cards, err := c.Read("/proc/asound/cards")
	if err != nil {
		return autoAudioResult(id, "blocked", "ALSA card metadata unreadable; cannot select the native control interface safely.")
	}
	_, internal := autoAudioCards(cards)
	if len(internal) != 1 {
		return autoAudioResult(id, "blocked", "Need one identified Surface Pro X ALSA card for read-only control enumeration; native card support/identification unavailable or ambiguous.")
	}
	output, err := c.Command("amixer", "-c", internal[0], "controls")
	if err != nil {
		return autoAudioResult(id, "blocked", "Cannot enumerate native ALSA controls; amixer, control-device permission and the native card are required. No mixer values written.")
	}
	// Enumerating control names does not read codec registers or change DAPM.
	controls := map[string]bool{}
	re := regexp.MustCompile(`name='([^']+)'`)
	for _, match := range re.FindAllStringSubmatch(output, -1) {
		controls[match[1]] = true
	}
	if len(controls) == 0 {
		return autoAudioResult(id, "blocked", "Native ALSA control list is empty or unsupported; routing/control capability not exposed.")
	}
	has := func(names ...string) bool {
		for _, name := range names {
			if controls[name] {
				return true
			}
		}
		return false
	}
	stereo := has("SpkrLeft PA Volume") && has("SpkrRight PA Volume")
	mic := has("MultiMedia2 Mixer SLIMBUS_0_TX") && has("AIF1_CAP Mixer SLIM TX0") && has("CDC_IF TX0 MUX") && has("ADC MUX0") && has("DMIC MUX0")
	status := "observed"
	detail := fmt.Sprintf("Native ALSA controls=%d, stereo PA control names=%t, MM2 internal microphone route control names=%t; capability only, no values read/written or stream started.", len(controls), stereo, mic)
	if !stereo || !mic {
		status = "blocked"
		detail += " Native stereo/microphone routing control support is incomplete; card/codec routing support required."
	}
	return autoAudioResult(id, status, detail)
}

func autoAudioSoundWire(c *AutoContext) AutoResult {
	const id = "audio.soundwire"
	paths, err := c.Glob("/sys/bus/soundwire/devices/sdw:*")
	if err != nil || len(paths) == 0 {
		return autoAudioResult(id, "blocked", "SoundWire core device interfaces not accessible; bus/codec support or sysfs permission required. This does not establish amplifier absence.")
	}
	attached, unattached, other, unreadable := 0, 0, 0, 0
	for _, path := range paths {
		status, err := c.Read(filepath.Join(path, "status"))
		if err != nil {
			unreadable++
			continue
		}
		switch strings.ToLower(strings.TrimSpace(status)) {
		case "attached":
			attached++
		case "unattached":
			unattached++
		default:
			other++
		}
	}
	if unreadable != 0 {
		return autoAudioResult(id, "blocked", fmt.Sprintf("SoundWire core nodes=%d, unreadable status attributes=%d; sysfs permission/status support required. No hardware register probe.", len(paths), unreadable))
	}
	return autoAudioResult(id, "observed", fmt.Sprintf("SoundWire core nodes=%d, attached=%d, unattached=%d, other states=%d; parked amps may be unattached. Core enumeration is not verified physical output; no bridge/register reads.", len(paths), attached, unattached, other))
}

func autoAudioService(c *AutoContext, user bool, unit string) (string, bool) {
	args := []string{"systemctl"}
	if user {
		args = append(args, "--user")
	}
	args = append(args, "show", unit, "--property=LoadState,ActiveState", "--no-pager")
	query := c.Command
	if user {
		query = c.UserCommand
	}
	output, err := query(args...)
	if err != nil {
		return "query unavailable", false
	}
	values := map[string]string{}
	for _, line := range strings.Split(output, "\n") {
		if pair := strings.SplitN(line, "=", 2); len(pair) == 2 {
			values[pair[0]] = pair[1]
		}
	}
	if values["LoadState"] != "loaded" {
		return "not loaded or masked", false
	}
	switch values["ActiveState"] {
	case "active":
		return "active", true
	case "inactive", "failed", "activating", "deactivating":
		return values["ActiveState"], false
	default:
		return "unsupported status reply", false
	}
}

func autoAudioServices(c *AutoContext) AutoResult {
	parts, available := []string{}, true
	failed := false
	for _, unit := range []string{"pipewire.service", "pipewire-pulse.service", "wireplumber.service"} {
		state, ok := autoAudioService(c, true, unit)
		parts = append(parts, unit+"="+state)
		available = available && ok
		failed = failed || state == "failed"
	}
	status := "observed"
	if !available {
		status = "blocked"
		parts = append(parts, "active desktop services, systemctl and access to the selected desktop session bus required; no service started or restarted")
	}
	if failed {
		status = "fail"
		parts = append(parts, "systemd reports a failed desktop audio service; no start or restart attempted")
	}
	return autoAudioResult("audio.services", status, strings.Join(parts, "; "))
}

type autoAudioEndpoint struct {
	Name          string            `json:"name"`
	Properties    map[string]string `json:"properties"`
	MonitorOfSink json.RawMessage   `json:"monitor_of_sink"`
}

func (e autoAudioEndpoint) monitor() bool {
	if e.Properties["device.class"] == "monitor" || strings.HasSuffix(e.Name, ".monitor") {
		return true
	}
	value := strings.Trim(string(e.MonitorOfSink), "\"")
	index, err := strconv.ParseUint(value, 10, 32)
	return err == nil && index < 4294967295
}

func (e autoAudioEndpoint) route() string {
	if e.Name == "spx_speakers" || e.Name == "spx_microphone" {
		return "SPX"
	}
	bus := e.Properties["device.bus"]
	if bus == "usb" {
		return "USB"
	}
	if bus == "bluetooth" || e.Properties["device.api"] == "bluez5" || e.Properties["api.bluez5.address"] != "" || strings.HasPrefix(e.Name, "bluez_") {
		return "Bluetooth"
	}
	return "other/virtual"
}

func autoAudioEndpoints(c *AutoContext, kind string) ([]autoAudioEndpoint, error) {
	// A Pulse client can autospawn/socket-activate an absent server. Query only
	// an already-active PipeWire pair; do not repair or activate the session.
	for _, unit := range []string{"pipewire.service", "pipewire-pulse.service"} {
		if _, active := autoAudioService(c, true, unit); !active {
			return nil, fmt.Errorf("active %s required before connecting", unit)
		}
	}
	output, err := c.UserCommand("pactl", "--format=json", "list", kind)
	if err != nil {
		return nil, err
	}
	var endpoints []autoAudioEndpoint
	if err := json.Unmarshal([]byte(output), &endpoints); err != nil {
		return nil, err
	}
	return endpoints, nil
}

func autoAudioGraph(c *AutoContext) AutoResult {
	const id = "audio.graph"
	sinks, err := autoAudioEndpoints(c, "sinks")
	if err != nil {
		return autoAudioResult(id, "blocked", "Cannot query desktop sinks; pactl JSON support, the Pulse-compatible audio service and selected desktop session permission required.")
	}
	sources, err := autoAudioEndpoints(c, "sources")
	if err != nil {
		return autoAudioResult(id, "blocked", "Cannot query desktop sources; pactl JSON support, audio service and selected desktop session permission required.")
	}
	counts := map[string]int{}
	for _, sink := range sinks {
		counts[sink.route()+" output"]++
	}
	for _, source := range sources {
		if source.monitor() {
			counts["monitor"]++
		} else {
			counts[source.route()+" input"]++
		}
	}
	defaultRoute := func(kind string, entries []autoAudioEndpoint) (string, bool) {
		name, err := c.UserCommand("pactl", "get-default-"+kind)
		if err != nil {
			return "unavailable", false
		}
		for _, endpoint := range entries {
			if endpoint.Name == strings.TrimSpace(name) {
				if kind == "source" && endpoint.monitor() {
					return "monitor (not a microphone)", true
				}
				return endpoint.route(), true
			}
		}
		return "not exposed in graph", false
	}
	sinkRoute, sinkOK := defaultRoute("sink", sinks)
	sourceRoute, sourceOK := defaultRoute("source", sources)
	status := "observed"
	if len(sinks) == 0 || !sinkOK || !sourceOK {
		status = "blocked"
	}
	detail := fmt.Sprintf("Graph outputs=%d, sources=%d (monitors=%d), SPX speaker nodes=%d, SPX microphone nodes=%d, USB output/input=%d/%d, Bluetooth output/input=%d/%d; default output=%s, input=%s. Read-only API/routing inventory, not signal delivery.", len(sinks), len(sources), counts["monitor"], counts["SPX output"], counts["SPX input"], counts["USB output"], counts["USB input"], counts["Bluetooth output"], counts["Bluetooth input"], sinkRoute, sourceRoute)
	if status == "blocked" {
		detail += " Usable endpoint/default-route support is required; no route changed."
	}
	return autoAudioResult(id, status, detail)
}

func autoAudioFeeder(c *AutoContext) AutoResult {
	const id = "audio.feeder"
	service, active := autoAudioService(c, false, "spx-desktop-playback.service")
	if service == "failed" {
		return autoAudioResult(id, "fail", "Systemd reports the native desktop feeder failed; playback readiness is lost. No PCM, amplifier, start or restart attempted.")
	}
	if !active {
		return autoAudioResult(id, "blocked", "Native desktop feeder="+service+"; installed/running feeder service and system service-query access required. No start or restart attempted.")
	}
	text, err := c.Read("/var/lib/spx-desktop-playback/serve-ready.json")
	if err != nil {
		return autoAudioResult(id, "blocked", "Feeder service active but readiness metadata unreadable; readiness file and read permission required.")
	}
	var ready struct {
		BootID    string `json:"boot_id"`
		Stopped   bool   `json:"stopped"`
		PAGain    *int   `json:"pa_gain"`
		PeakLimit *int   `json:"peak_limit"`
	}
	if json.Unmarshal([]byte(text), &ready) != nil {
		return autoAudioResult(id, "error", "Feeder readiness metadata is not valid JSON; no raw contents retained.")
	}
	boot, err := c.Read("/proc/sys/kernel/random/boot_id")
	if err != nil || ready.BootID == "" || ready.BootID != boot {
		return autoAudioResult(id, "blocked", "Cannot bind feeder readiness to this boot; current-boot readiness metadata required.")
	}
	if ready.Stopped {
		return autoAudioResult(id, "blocked", "Feeder readiness record marks serving stopped; live readiness required, no restart attempted.")
	}
	gain, peak := "unreported", "unreported"
	if ready.PAGain != nil && *ready.PAGain >= 0 && *ready.PAGain <= 12 {
		gain = strconv.Itoa(*ready.PAGain)
	}
	if ready.PeakLimit != nil && *ready.PeakLimit >= 0 && *ready.PeakLimit <= 32768 {
		peak = strconv.Itoa(*ready.PeakLimit)
	}
	parked, err := c.Read("/sys/module/q6asm_dai/parameters/spx_keep_asm")
	lifetime := "parameter unreadable"
	if err == nil {
		if parked == "Y" || parked == "1" {
			lifetime = "retained ASM enabled; full DSP destruction unvalidated"
		} else if parked == "N" || parked == "0" {
			lifetime = "retained ASM disabled; parked-session safety prerequisite not met"
		}
	}
	return autoAudioResult(id, "observed", fmt.Sprintf("Feeder active with current-boot readiness, recorded PA step=%s, digital peak limit=%s; %s. Readiness is not measured sound, latency or stream-lifecycle validation; no gain/PCM/graph changed.", gain, peak, lifetime))
}

func autoAudioMicrophones(c *AutoContext) AutoResult {
	return trialAudioRow(c, "audio.microphones")
}

func autoAudioExternal(c *AutoContext) AutoResult {
	const id = "audio.external"
	sinks, err := autoAudioEndpoints(c, "sinks")
	if err != nil {
		return autoAudioResult(id, "blocked", "External audio fixtures cannot be identified through the desktop graph; pactl JSON support, audio service and user-session access required.")
	}
	sources, err := autoAudioEndpoints(c, "sources")
	if err != nil {
		return autoAudioResult(id, "blocked", "External input fixtures cannot be identified through the desktop graph; source API/service access required.")
	}
	outputs, inputs := 0, 0
	for _, sink := range sinks {
		if sink.route() == "USB" || sink.route() == "Bluetooth" {
			outputs++
		}
	}
	for _, source := range sources {
		if !source.monitor() && (source.route() == "USB" || source.route() == "Bluetooth") {
			inputs++
		}
	}
	return autoAudioResult(id, "blocked", fmt.Sprintf("External USB/Bluetooth graph output/input nodes=%d/%d; real audio fixtures, a controlled signal/recording path and separate sound authorization required for data-path validation. No playback, capture, radio/route change or hotplug performed.", outputs, inputs))
}
