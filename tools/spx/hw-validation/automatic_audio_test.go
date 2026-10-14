package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func autoAudioFixture(t *testing.T, root, path, text string) {
	t.Helper()
	file := filepath.Join(root, strings.TrimPrefix(path, "/"))
	if err := os.MkdirAll(filepath.Dir(file), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(file, []byte(text), 0644); err != nil {
		t.Fatal(err)
	}
}

func autoAudioContext(t *testing.T) *AutoContext {
	t.Helper()
	return &AutoContext{Root: t.TempDir(), Run: func(...string) (string, error) {
		return "", errors.New("fixture command unavailable")
	}}
}

const autoAudioFixtureCards = ` 0 [Dock           ]: USB-Audio - PRIVATE_DOCK_SERIAL
                      USB dock PRIVATE_LOCATION
 1 [SurfaceProX    ]: surface-pro-x - Surface Pro X
                      Surface Pro X
`

const autoAudioFixtureSinks = `[
 {"name":"spx_speakers","properties":{"device.class":"abstract"}},
 {"name":"alsa_output.usb_PRIVATE_SERIAL","properties":{"device.bus":"usb","device.serial":"PRIVATE_SERIAL"}},
 {"name":"bluez_output.aa_bb_cc_dd_ee_ff.1","properties":{"device.bus":"bluetooth","api.bluez5.address":"aa:bb:cc:dd:ee:ff"}}
]`
const autoAudioFixtureSources = `[
 {"name":"spx_speakers.monitor","monitor_of_sink":0,"properties":{"device.class":"monitor"}},
 {"name":"spx_microphone","monitor_of_sink":null,"properties":{}},
 {"name":"alsa_input.usb_PRIVATE_SERIAL","monitor_of_sink":null,"properties":{"device.bus":"usb"}},
 {"name":"bluez_input.aa_bb_cc_dd_ee_ff.0","monitor_of_sink":null,"properties":{"device.api":"bluez5"}}
]`

func TestAutomaticAudioInventoryAndScope(t *testing.T) {
	c := autoAudioContext(t)
	c.Options.CaptureMicrophone = true
	autoAudioFixture(t, c.Root, "/proc/asound/cards", autoAudioFixtureCards)
	autoAudioFixture(t, c.Root, "/proc/asound/pcm", "00-00: USB Audio : playback 1 : capture 1\n01-00: MultiMedia1 : playback 1 : capture 1\n01-01: MultiMedia2 : playback 1 : capture 1\n")
	autoAudioFixture(t, c.Root, "/sys/bus/soundwire/devices/sdw:0:1:0217:2110:00:3/status", "Unattached")
	autoAudioFixture(t, c.Root, "/sys/bus/soundwire/devices/sdw:0:1:0217:2110:00:4/status", "Unattached")
	autoAudioFixture(t, c.Root, "/proc/sys/kernel/random/boot_id", "fixture-boot")
	autoAudioFixture(t, c.Root, "/var/lib/spx-desktop-playback/serve-ready.json", `{"boot_id":"fixture-boot","pa_gain":6,"peak_limit":32768,"recording":"PRIVATE_RECORDING","owner_pid":17}`)
	autoAudioFixture(t, c.Root, "/sys/module/q6asm_dai/parameters/spx_keep_asm", "Y")
	controls := []string{"SpkrLeft PA Volume", "SpkrRight PA Volume", "MultiMedia2 Mixer SLIMBUS_0_TX", "AIF1_CAP Mixer SLIM TX0", "CDC_IF TX0 MUX", "ADC MUX0", "DMIC MUX0"}
	var controlLines []string
	for _, name := range controls {
		controlLines = append(controlLines, "numid=1,iface=MIXER,name='"+name+"'")
	}
	var commands []string
	c.Run = func(args ...string) (string, error) {
		command := strings.Join(args, " ")
		commands = append(commands, command)
		switch {
		case strings.HasPrefix(command, "systemctl "):
			if !strings.Contains(command, " show ") {
				t.Fatalf("service mutation attempted: %s", command)
			}
			return "LoadState=loaded\nActiveState=active\n", nil
		case command == "amixer -c 1 controls":
			return strings.Join(controlLines, "\n"), nil
		case command == "pactl --format=json list sinks":
			return autoAudioFixtureSinks, nil
		case command == "pactl --format=json list sources":
			return autoAudioFixtureSources, nil
		case command == "pactl get-default-sink":
			return "spx_speakers\n", nil
		case command == "pactl get-default-source":
			return "spx_microphone\n", nil
		default:
			t.Fatalf("non-allowlisted audio command: %s", command)
			return "", errors.New("unexpected command")
		}
	}
	seen := map[string]bool{}
	for _, check := range automaticAudioChecks() {
		if seen[check.ID] || check.Run == nil || len(check.Boxes) == 0 || check.Area == "" {
			t.Fatalf("invalid check: %+v", check)
		}
		seen[check.ID] = true
		result := check.Run(c)
		if result.ID != check.ID {
			t.Fatalf("result id mismatch: %+v", result)
		}
		switch check.Kind {
		case "inventory":
			if result.Status != "observed" {
				t.Fatalf("fixture inventory: %+v", result)
			}
		case "functional":
			if result.Status != "blocked" {
				t.Fatalf("capture flag gave an unauthorized audio result: %+v", result)
			}
		default:
			t.Fatalf("invalid kind %q", check.Kind)
		}
		for _, private := range []string{"PRIVATE", "aa:bb", "aa_bb", "fixture-boot", "owner_pid"} {
			if strings.Contains(result.Detail, private) {
				t.Fatalf("private metadata leaked: %+v", result)
			}
		}
	}
	if len(commands) == 0 {
		t.Fatal("read-only graph/control queries not exercised")
	}
}

func TestAutomaticAudioMissingSupportAndPermissions(t *testing.T) {
	c := autoAudioContext(t)
	for _, check := range automaticAudioChecks() {
		result := check.Run(c)
		if result.Status != "blocked" || result.Detail == "" {
			t.Fatalf("missing prerequisite result: %+v", result)
		}
	}
	autoAudioFixture(t, c.Root, "/proc/asound/cards", autoAudioFixtureCards)
	if result := autoAudioControls(c); result.Status != "blocked" {
		t.Fatalf("missing amixer/permission result: %+v", result)
	}
	c.Run = func(...string) (string, error) { return "numid=1,iface=MIXER,name='PRIVATE_UNRELATED'", nil }
	if result := autoAudioControls(c); result.Status != "blocked" || strings.Contains(result.Detail, "PRIVATE") {
		t.Fatalf("missing native routing controls: %+v", result)
	}
	c.Run = func(...string) (string, error) {
		return "LoadState=loaded\nActiveState=inactive\nPRIVATE_REASON", nil
	}
	if result := autoAudioServices(c); result.Status != "blocked" || strings.Contains(result.Detail, "PRIVATE") {
		t.Fatalf("inactive service: %+v", result)
	}
	c.Run = func(args ...string) (string, error) {
		if args[0] != "systemctl" {
			t.Fatalf("audio client attempted server activation: %v", args)
		}
		return "LoadState=loaded\nActiveState=inactive\n", nil
	}
	if result := autoAudioGraph(c); result.Status != "blocked" {
		t.Fatalf("inactive graph service: %+v", result)
	}
	if result := autoAudioExternal(c); result.Status != "blocked" {
		t.Fatalf("inactive external service: %+v", result)
	}
}

func TestAutomaticAudioMonitorsAndExternalFixtures(t *testing.T) {
	for _, sentinel := range []string{"null", "4294967295", `"4294967295"`, `"n/a"`, "-1"} {
		var endpoint autoAudioEndpoint
		if err := json.Unmarshal([]byte(`{"name":"spx_microphone","monitor_of_sink":`+sentinel+`}`), &endpoint); err != nil {
			t.Fatal(err)
		}
		if endpoint.monitor() {
			t.Fatalf("non-monitor sentinel inferred as loopback: %s", sentinel)
		}
	}
	c := autoAudioContext(t)
	c.Run = func(args ...string) (string, error) {
		if args[0] == "systemctl" {
			return "LoadState=loaded\nActiveState=active\n", nil
		}
		switch strings.Join(args, " ") {
		case "pactl --format=json list sinks":
			return `[{"name":"spx_speakers","properties":{}}]`, nil
		case "pactl --format=json list sources":
			return `[{"name":"spx_speakers.monitor","properties":{"device.class":"monitor"},"monitor_of_sink":0}]`, nil
		case "pactl get-default-sink":
			return "spx_speakers", nil
		case "pactl get-default-source":
			return "spx_speakers.monitor", nil
		}
		return "", errors.New("unavailable")
	}
	graph := autoAudioGraph(c)
	if graph.Status != "observed" || !strings.Contains(graph.Detail, "SPX microphone nodes=0") || !strings.Contains(graph.Detail, "not a microphone") {
		t.Fatalf("monitor inferred as microphone: %+v", graph)
	}
	external := autoAudioExternal(c)
	if external.Status != "blocked" || !strings.Contains(external.Detail, "nodes=0/0") {
		t.Fatalf("missing external fixture: %+v", external)
	}
	c.Run = func(args ...string) (string, error) {
		if args[0] == "systemctl" {
			return "LoadState=loaded\nActiveState=active\n", nil
		}
		return "[]", nil
	}
	if result := autoAudioGraph(c); result.Status != "blocked" {
		t.Fatalf("empty graph: %+v", result)
	}
	c.Run = func(args ...string) (string, error) {
		if args[0] == "systemctl" {
			return "LoadState=loaded\nActiveState=active\n", nil
		}
		return "PRIVATE_BROKEN_JSON", nil
	}
	if result := autoAudioGraph(c); result.Status != "blocked" || strings.Contains(result.Detail, "PRIVATE") {
		t.Fatalf("unsupported graph JSON: %+v", result)
	}
}

func TestAutomaticAudioFeederReadinessNotPlayback(t *testing.T) {
	c := autoAudioContext(t)
	c.Run = func(...string) (string, error) { return "LoadState=loaded\nActiveState=active\n", nil }
	autoAudioFixture(t, c.Root, "/proc/sys/kernel/random/boot_id", "fixture-boot")
	path := "/var/lib/spx-desktop-playback/serve-ready.json"
	for _, test := range []struct {
		text, status string
	}{
		{`{"boot_id":"old-boot","pa_gain":6}`, "blocked"},
		{`{"boot_id":"fixture-boot","stopped":true}`, "blocked"},
		{`PRIVATE_MALFORMED`, "error"},
		{`{"boot_id":"fixture-boot","pa_gain":6,"peak_limit":32768,"acoustic_passed":true}`, "observed"},
	} {
		autoAudioFixture(t, c.Root, path, test.text)
		result := autoAudioFeeder(c)
		if result.Status != test.status || strings.Contains(result.Detail, "PRIVATE") {
			t.Fatalf("readiness %s: %+v", test.text, result)
		}
	}
}

func TestAutomaticAudioFailedServicesAreFailures(t *testing.T) {
	c := autoAudioContext(t)
	c.Run = func(args ...string) (string, error) {
		if args[0] != "systemctl" || !strings.Contains(strings.Join(args, " "), " show ") {
			t.Fatalf("failed audio services must only be queried: %v", args)
		}
		// A failed unit must remain a failure even when other prerequisites are missing.
		if strings.Contains(strings.Join(args, " "), "pipewire-pulse.service") {
			return "LoadState=not-found\nActiveState=inactive\n", nil
		}
		return "LoadState=loaded\nActiveState=failed\nPRIVATE_FAILURE", nil
	}
	for _, check := range []func(*AutoContext) AutoResult{autoAudioServices, autoAudioFeeder} {
		result := check(c)
		if result.Status != "fail" || strings.Contains(result.Detail, "PRIVATE") {
			t.Fatalf("known service failure mislabeled or private output retained: %+v", result)
		}
	}
}

func TestAutomaticAudioCameraOptInDoesNotAllowMicrophones(t *testing.T) {
	c := &AutoContext{Options: AutoOptions{CaptureCamera: true}, Run: func(args ...string) (string, error) {
		t.Fatalf("unauthorized microphone command %q", args)
		return "", nil
	}}
	result := autoAudioMicrophones(c)
	if result.Status != "blocked" || !strings.Contains(result.Detail, "arm-audio") {
		t.Fatal(result)
	}
	c.Options.CaptureMicrophone = true
	result = autoAudioMicrophones(c)
	if result.Status != "blocked" || !strings.Contains(result.Detail, "arm-audio") {
		t.Fatal(result)
	}
}
