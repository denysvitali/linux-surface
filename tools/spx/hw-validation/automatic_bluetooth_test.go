package main

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
)

func bluetoothFixtureVariant(kind string, data any) any {
	return map[string]any{"type": kind, "data": data}
}

func bluetoothFixtureObjects(t *testing.T, powered, discovering bool, connected bool) string {
	t.Helper()
	objects := map[string]any{
		"/org/bluez/hci0": map[string]any{
			"org.bluez.Adapter1": map[string]any{
				"Address":     bluetoothFixtureVariant("s", "A0:B0:C0:D0:E0:F0"),
				"Alias":       bluetoothFixtureVariant("s", "PRIVATE-ADAPTER"),
				"Powered":     bluetoothFixtureVariant("b", powered),
				"Discovering": bluetoothFixtureVariant("b", discovering),
			},
		},
		"/org/bluez/hci0/dev_10_20_30_40_50_60": map[string]any{
			"org.bluez.Device1": map[string]any{
				"Address":   bluetoothFixtureVariant("s", "10:20:30:40:50:60"),
				"Name":      bluetoothFixtureVariant("s", "PRIVATE-PERIPHERAL"),
				"Paired":    bluetoothFixtureVariant("b", true),
				"Connected": bluetoothFixtureVariant("b", connected),
				"UUIDs": bluetoothFixtureVariant("as", []any{
					"00001812-0000-1000-8000-00805f9b34fb",
					"0000110b-0000-1000-8000-00805f9b34fb",
				}),
			},
		},
	}
	data, err := json.Marshal(map[string]any{"type": "a{oa{sa{sv}}}", "data": []any{objects}})
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

type bluetoothFixtureStep struct {
	args   []string
	output string
	err    error
}

func bluetoothFixtureContext(t *testing.T, steps []bluetoothFixtureStep) *AutoContext {
	t.Helper()
	pos := 0
	t.Cleanup(func() {
		if pos != len(steps) {
			t.Errorf("consumed %d commands, expected %d", pos, len(steps))
		}
	})
	return &AutoContext{Root: t.TempDir(), Run: func(args ...string) (string, error) {
		t.Helper()
		if pos >= len(steps) {
			t.Fatalf("unexpected command: %q", args)
		}
		step := steps[pos]
		pos++
		if !reflect.DeepEqual(args, step.args) {
			t.Fatalf("command %d: got %q, want %q", pos, args, step.args)
		}
		return step.output, step.err
	}}
}

func bluetoothFixtureQuery(output string) bluetoothFixtureStep {
	return bluetoothFixtureStep{args: []string{"busctl", "--system", "--timeout=3", "--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"}, output: output}
}

func bluetoothFixtureScan(output string, err error) bluetoothFixtureStep {
	return bluetoothFixtureStep{args: []string{"env", "LC_ALL=C", "TERM=dumb", "bluetoothctl", "--timeout", "5", "scan", "on"}, output: output, err: err}
}

func bluetoothFixturePrivacy(t *testing.T, result AutoResult) {
	t.Helper()
	text, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	for _, private := range []string{"A0:B0:C0:D0:E0:F0", "10:20:30:40:50:60", "20:30:40:50:60:70", "PRIVATE-ADAPTER", "PRIVATE-PERIPHERAL", "PRIVATE-NEW-PEER", "dev_10_20_30_40_50_60"} {
		if strings.Contains(string(text), private) {
			t.Errorf("private value %q in report", private)
		}
	}
}

func TestBluetoothInventoryIsNotFunctional(t *testing.T) {
	checks := automaticBluetoothChecks()
	if len(checks) != 2 || checks[0].Kind != "inventory" || checks[1].Kind != "functional" {
		t.Fatal("expected separate inventory and functional scan checks")
	}
	context := bluetoothFixtureContext(t, []bluetoothFixtureStep{bluetoothFixtureQuery(bluetoothFixtureObjects(t, true, false, true))})
	result := checks[0].Run(context)
	if result.Status != "observed" {
		t.Fatalf("enumeration gave %s", result.Status)
	}
	for _, count := range []string{"adapters=1", "powered=1", "paired=1", "connected=1", "HID-capable=1", "audio-capable=1"} {
		if !strings.Contains(result.Detail, count) {
			t.Errorf("missing count %s", count)
		}
	}
	bluetoothFixturePrivacy(t, result)
}

func TestBluetoothDiscoveryUsesTimedOwnedClientAndFreshReports(t *testing.T) {
	before := bluetoothFixtureObjects(t, true, false, true)
	output := "[NEW] Device 20:30:40:50:60:70 PRIVATE-NEW-PEER\n" +
		"Discovery started\n" +
		"\x1b[0;93m[NEW]\x1b[0m Device 20:30:40:50:60:70 PRIVATE-NEW-PEER\r\n" +
		"[CHG] Device 10:20:30:40:50:60 RSSI: 0xffffffc0 (-64)\n"
	context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
		bluetoothFixtureQuery(before), bluetoothFixtureScan(output, nil), bluetoothFixtureQuery(before),
	})
	result := automaticBluetoothDiscovery(context)
	if result.Status != "pass" || !strings.Contains(result.Detail, "reports=2 from peers=2") {
		t.Fatalf("expected fresh radio report proof, got %#v", result)
	}
	bluetoothFixturePrivacy(t, result)
}

func TestBluetoothDiscoveryDoesNotChangeOffOrPreexistingDiscovery(t *testing.T) {
	cases := []struct{ powered, discovering bool }{{false, false}, {true, true}}
	for _, test := range cases {
		context := bluetoothFixtureContext(t, []bluetoothFixtureStep{bluetoothFixtureQuery(bluetoothFixtureObjects(t, test.powered, test.discovering, true))})
		result := automaticBluetoothDiscovery(context)
		if result.Status != "blocked" {
			t.Fatalf("expected no-command prerequisite block, got %#v", result)
		}
		bluetoothFixturePrivacy(t, result)
	}
}

func TestBluetoothDiscoveryCompletionWithoutReportsDoesNotClaimReception(t *testing.T) {
	before := bluetoothFixtureObjects(t, true, false, true)
	for _, output := range []string{
		"Discovery started\n",
		"[NEW] Device 20:30:40:50:60:70 PRIVATE-NEW-PEER\nDiscovery started\n",
		"Discovery started\n[NEW] Device 10:20:30:40:50:60 PRIVATE-PERIPHERAL\n",
		"Discovery started\n[CHG] Device 10:20:30:40:50:60 Connected: yes\n",
		"Discovery started\n[CHG] Device 10:20:30:40:50:60 RSSI: PRIVATE-PERIPHERAL\n",
		"Discovery started\nDiscovery stopped\n[CHG] Device 10:20:30:40:50:60 RSSI: -64\n",
	} {
		context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
			bluetoothFixtureQuery(before), bluetoothFixtureScan(output, nil), bluetoothFixtureQuery(before),
		})
		result := automaticBluetoothDiscovery(context)
		if result.Status != "pass" || !strings.Contains(result.Detail, "radio reception is unproven") {
			t.Fatalf("completed discovery is not evidence of radio reception, got %#v", result)
		}
		bluetoothFixturePrivacy(t, result)
	}
	context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
		bluetoothFixtureQuery(before),
		bluetoothFixtureScan("[NEW] Device 20:30:40:50:60:70 PRIVATE-NEW-PEER\n", nil),
		bluetoothFixtureQuery(before),
	})
	if result := automaticBluetoothDiscovery(context); result.Status != "blocked" {
		t.Fatalf("mere enumeration without starting discovery cannot pass: %#v", result)
	}
}

func TestBluetoothScanFailureClassificationDiscardsPrivateReplies(t *testing.T) {
	before := bluetoothFixtureObjects(t, true, false, true)
	cases := []struct {
		output, status string
		err            error
	}{
		{"Failed to start discovery: org.bluez.Error.NotAuthorized\nPRIVATE-PERIPHERAL", "blocked", nil},
		{"Failed to start discovery: org.bluez.Error.NotReady\n10:20:30:40:50:60", "blocked", nil},
		{"Failed to start discovery: org.bluez.Error.InProgress", "blocked", nil},
		{"Failed to start discovery: org.bluez.Error.Failed\n[NEW] Device 20:30:40:50:60:70 PRIVATE-NEW-PEER busy notready", "fail", nil},
		{"env: bluetoothctl: No such file or directory", "blocked", errors.New("PRIVATE-PERIPHERAL")},
		{"", "error", errors.New("PRIVATE-PERIPHERAL 10:20:30:40:50:60")},
	}
	for _, test := range cases {
		context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
			bluetoothFixtureQuery(before), bluetoothFixtureScan(test.output, test.err), bluetoothFixtureQuery(before),
		})
		result := automaticBluetoothDiscovery(context)
		if result.Status != test.status {
			t.Errorf("got %s, want %s", result.Status, test.status)
		}
		bluetoothFixturePrivacy(t, result)
	}
}

func TestBluetoothMissingBlueZInterfacesAndToolsAreBlocked(t *testing.T) {
	for _, run := range []func(*AutoContext) AutoResult{automaticBluetoothInventory, automaticBluetoothDiscovery} {
		for _, step := range []bluetoothFixtureStep{
			bluetoothFixtureQuery(`{"type":"a{oa{sa{sv}}}","data":[{}]}`),
			{args: bluetoothFixtureQuery("").args, output: "Call failed: org.freedesktop.DBus.Error.ServiceUnknown PRIVATE-ADAPTER", err: errors.New("10:20:30:40:50:60")},
			{args: bluetoothFixtureQuery("").args, err: errors.New("exec: busctl: executable file not found")},
		} {
			result := run(bluetoothFixtureContext(t, []bluetoothFixtureStep{step}))
			if result.Status != "blocked" || strings.Contains(result.Detail, "hardware absent") {
				t.Fatalf("expected specific support block, got %#v", result)
			}
			bluetoothFixturePrivacy(t, result)
		}
	}
}

func TestBluetoothMalformedReplyDoesNotExposePrivateContents(t *testing.T) {
	for _, reply := range []string{"PRIVATE-PERIPHERAL 10:20:30:40:50:60", `{"type":"a{oa{sa{sv}}}","data":[{"/org/bluez/hci0":{"org.bluez.Adapter1":{"Powered":true}}}]}`} {
		result := automaticBluetoothInventory(bluetoothFixtureContext(t, []bluetoothFixtureStep{bluetoothFixtureQuery(reply)}))
		if result.Status != "error" {
			t.Fatalf("malformed reply must be an error: %#v", result)
		}
		bluetoothFixturePrivacy(t, result)
	}
}

func TestBluetoothConnectionLossFailsInsteadOfPassingScan(t *testing.T) {
	context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
		bluetoothFixtureQuery(bluetoothFixtureObjects(t, true, false, true)),
		bluetoothFixtureScan("Discovery started\n[CHG] Device 10:20:30:40:50:60 RSSI: -60\n", nil),
		bluetoothFixtureQuery(bluetoothFixtureObjects(t, true, false, false)),
	})
	result := automaticBluetoothDiscovery(context)
	if result.Status != "fail" {
		t.Fatalf("connection loss must not pass: %#v", result)
	}
	bluetoothFixturePrivacy(t, result)
}

func TestBluetoothOwnedCleanupAllowsBoundedNativeDelay(t *testing.T) {
	before := bluetoothFixtureObjects(t, true, false, true)
	context := bluetoothFixtureContext(t, []bluetoothFixtureStep{
		bluetoothFixtureQuery(before),
		bluetoothFixtureScan("Discovery started\n[CHG] Device 10:20:30:40:50:60 RSSI: -60\n", nil),
		bluetoothFixtureQuery(bluetoothFixtureObjects(t, true, true, true)),
		bluetoothFixtureQuery(before),
	})
	result := automaticBluetoothDiscovery(context)
	if result.Status != "pass" {
		t.Fatalf("native owned cleanup delay: %#v", result)
	}
}

func TestBluetoothUnownedDiscoveryIsNeverStopped(t *testing.T) {
	before := bluetoothFixtureObjects(t, true, false, true)
	steps := []bluetoothFixtureStep{
		bluetoothFixtureQuery(before),
		bluetoothFixtureScan("Discovery started\n[CHG] Device 10:20:30:40:50:60 RSSI: -60\n", nil),
	}
	for attempt := 0; attempt < 5; attempt++ {
		steps = append(steps, bluetoothFixtureQuery(bluetoothFixtureObjects(t, true, true, true)))
	}
	result := automaticBluetoothDiscovery(bluetoothFixtureContext(t, steps))
	if result.Status != "blocked" {
		t.Fatalf("ambiguous ongoing discovery must block without stopping: %#v", result)
	}
	bluetoothFixturePrivacy(t, result)
}
