package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestDesktopMotionFixtureDoesNotExecuteHelper(t *testing.T) {
	for _, c := range []*AutoContext{interfacesFixture(t, nil), {Root: "/", Fixture: true}} {
		c.Run = func(args ...string) (string, error) {
			t.Fatalf("fixture must not run helper: %v", args)
			return "", nil
		}
		if got := interfacesSensorDesktopDelivery(c); got.Status != "blocked" {
			t.Fatal(got)
		}
	}
}

func TestDesktopMotionAndCompassCatalog(t *testing.T) {
	found := map[string]bool{}
	for _, check := range automaticInterfacesChecks() {
		if check.ID == "sensors.desktop-delivery" {
			t.Fatal("combined row would overclaim compass delivery")
		}
		if check.ID != "sensors.desktop-motion" && check.ID != "sensors.desktop-compass" {
			continue
		}
		found[check.ID] = true
		if check.Kind != "functional" {
			t.Fatal(check)
		}
		c := interfacesFixture(t, nil)
		c.Run = func(args ...string) (string, error) { t.Fatalf("unexpected command %v", args); return "", nil }
		got := check.Run(c)
		if got.ID != check.ID || got.Status != "blocked" {
			t.Fatal(got)
		}
		if check.ID == "sensors.desktop-compass" && !strings.Contains(got.Detail, "restricted to geoclue") {
			t.Fatal(got)
		}
	}
	if len(found) != 2 {
		t.Fatal(found)
	}
}

func TestDesktopMotionHelperOutcomes(t *testing.T) {
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		name, output, status, detail string
		err                          error
	}{
		{"signal", `{"status":"pass","reason":"signal","has_compass":true,"orientation_before":"normal","orientation_after":"normal","signal":true,"claimed":true,"released":true}`, "pass", "Fresh PropertiesChanged", nil},
		{"transition", `{"status":"pass","reason":"transition","has_compass":false,"orientation_before":"undefined","orientation_after":"normal","claimed":true,"released":true}`, "pass", "transitioned from undefined/empty", nil},
		{"empty transition", `{"status":"pass","reason":"transition","orientation_before":"","orientation_after":"normal","claimed":true,"released":true}`, "pass", "transitioned from undefined/empty", nil},
		{"stationary", `{"status":"blocked","reason":"stationary","has_compass":true,"orientation_before":"normal","orientation_after":"normal","claimed":true,"released":true,"window_complete":true}`, "blocked", "Device is stationary and the property was already defined before the claim so freshness cannot be distinguished", nil},
		{"no service", `{"status":"blocked","reason":"no_service"}`, "blocked", "NameHasOwner false", nil},
		{"no accelerometer", `{"status":"blocked","reason":"no_accelerometer","has_compass":false}`, "blocked", "HasAccelerometer false", nil},
		{"refused", `{"status":"blocked","reason":"claim_refused"}`, "blocked", "ClaimAccelerometer refused", nil},
		{"undefined", `{"status":"fail","reason":"undefined","orientation_before":"undefined","orientation_after":"undefined","claimed":true,"released":true,"window_complete":true}`, "fail", "never obtained a reading", nil},
		{"cached then undefined", `{"status":"fail","reason":"undefined","orientation_before":"normal","orientation_after":"undefined","claimed":true,"released":true,"window_complete":true}`, "fail", "never obtained a reading", nil},
		{"missing PyGObject", `{"status":"blocked","reason":"unavailable"}`, "blocked", "PyGObject", nil},
		{"helper error", `{"status":"error","reason":"helper_error"}`, "error", "helper error", nil},
		{"timeout", `{"status":"error","reason":"timeout","claimed":true,"released":true}`, "error", "timeout", nil},
		{"release error", `{"status":"error","reason":"release_error","claimed":true,"signal":true}`, "error", "release_error", nil},
		{"missing release", `{"status":"pass","reason":"signal","claimed":true,"signal":true}`, "error", "Invalid", nil},
		{"cached cannot pass", `{"status":"pass","reason":"transition","orientation_before":"normal","orientation_after":"normal","claimed":true,"released":true}`, "error", "Invalid", nil},
		{"short window cannot fail", `{"status":"fail","reason":"undefined","orientation_before":"undefined","orientation_after":"undefined","claimed":true,"released":true}`, "error", "Invalid", nil},
		{"malformed", `PRIVATE`, "error", "Invalid", nil},
		{"command error", `PRIVATE`, "error", "command failed", errors.New("exit status 1")},
		{"missing Python", `PRIVATE`, "blocked", "unavailable", os.ErrNotExist},
	} {
		t.Run(test.name, func(t *testing.T) {
			calls := 0
			c := &AutoContext{Root: "/", Repo: repo}
			c.Run = func(args ...string) (string, error) {
				calls++
				want := []string{"python3", "-B", filepath.Join(repo, "tools/spx/hw-validation/sensorproxy_probe.py")}
				if strings.Join(args, "\n") != strings.Join(want, "\n") {
					t.Fatalf("helper invocation: %v", args)
				}
				return test.output, test.err
			}
			got := interfacesSensorDesktopDelivery(c)
			if calls != 1 || got.ID != "sensors.desktop-motion" || got.Status != test.status || !strings.Contains(got.Detail, test.detail) || strings.Contains(got.Detail, "PRIVATE") || !strings.Contains(got.Detail, "compass not covered") {
				t.Fatalf("%+v calls=%d", got, calls)
			}
			if strings.Contains(test.output, `"has_compass":true`) && !strings.Contains(got.Detail, "HasCompass=true") {
				t.Fatal(got)
			}
			if strings.Contains(test.output, `"has_compass":false`) && !strings.Contains(got.Detail, "HasCompass=false") {
				t.Fatal(got)
			}
		})
	}
}

func TestExposedSensorFailuresAreNotMissingPrerequisites(t *testing.T) {
	for _, test := range []struct {
		output string
		err    error
		status string
	}{
		{"private channel: Input/output error", errors.New("exit status 1"), "fail"},
		{"", errors.New("exit status 124"), "fail"},
		{"private channel: Permission denied", os.ErrPermission, "blocked"},
		{"", os.ErrNotExist, "blocked"},
		{"PRIVATE_UNEXPECTED_OUTPUT", errors.New("unexpected runner fault"), "error"},
	} {
		result := interfacesSensorReadProblem("sensors.light-read", test.output, test.err)
		if result.Status != test.status || strings.Contains(result.Detail, "private") || strings.Contains(result.Detail, "PRIVATE") {
			t.Fatalf("light failure mislabeled or raw output retained: %+v", result)
		}
	}
}

func interfacesFixture(t *testing.T, files map[string]string) *AutoContext {
	t.Helper()
	root := t.TempDir()
	for path, text := range files {
		name := filepath.Join(root, strings.TrimPrefix(path, "/"))
		if err := os.MkdirAll(filepath.Dir(name), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(name, []byte(text), 0644); err != nil {
			t.Fatal(err)
		}
	}
	return &AutoContext{Root: root, Run: func(args ...string) (string, error) { return "", errors.New("fixture command unavailable") }}
}

func interfacesFixtureConfig(t *testing.T, c *AutoContext, text string) {
	t.Helper()
	var data bytes.Buffer
	gz := gzip.NewWriter(&data)
	if _, err := gz.Write([]byte(text)); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(c.Root, "proc/config.gz")
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data.Bytes(), 0644); err != nil {
		t.Fatal(err)
	}
}

func interfacesFixtureJSON(t *testing.T, value any) string {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestInterfacesCatalogSafeFixture(t *testing.T) {
	checks := automaticInterfacesChecks()
	if err := automaticValidateCatalog(checks); err != nil {
		t.Fatal(err)
	}
	c := interfacesFixture(t, nil)
	calls := 0
	c.Run = func(args ...string) (string, error) {
		calls++
		if len(args) == 0 {
			t.Fatal("empty command")
		}
		switch args[0] {
		case "systemctl":
			if len(args) < 2 || args[1] != "show" {
				t.Fatalf("not read-only: %v", args)
			}
		case "qrtr-lookup", "mmcli", "busctl":
		default:
			t.Fatalf("unexpected command on empty fixture: %v", args)
		}
		return "", errors.New("fixture tools unavailable")
	}
	seen := map[string]bool{}
	for _, check := range checks {
		seen[check.ID] = true
		result := check.Run(c)
		if result.ID != check.ID || result.Status != "blocked" {
			t.Fatalf("empty fixture %s: %+v", check.ID, result)
		}
		if strings.Contains(result.Detail, "hardware absent") && !strings.Contains(result.Detail, "not hardware absent") {
			t.Fatalf("absence verdict: %+v", result)
		}
	}
	for _, id := range []string{"cell.control", "cell.data", "gnss.path", "gnss.fix", "usb.controllers", "usb.attached", "usb.transfer", "usb.roles", "usb.pd", "dock.paths", "input.touch", "input.pen", "input.keyboard", "input.touchpad", "input.buttons", "input.accessory", "input.startup", "sensors.channels", "sensors.backend", "sensors.desktop", "sensors.light-read", "sensors.motion-read"} {
		if !seen[id] {
			t.Errorf("missing feature %s", id)
		}
	}
	if calls == 0 {
		t.Fatal("queries not exercised")
	}
}

func TestInterfacesRunningConfigPrerequisites(t *testing.T) {
	c := interfacesFixture(t, map[string]string{"/sys/class/net/rmnet0/operstate": "up", "/sys/class/wwan/wwan0/uevent": ""})
	interfacesFixtureConfig(t, c, "# CONFIG_QCOM_IPA is not set\n# CONFIG_WWAN is not set\nCONFIG_RMNET=m\n")
	result := interfacesCellPrerequisites(c)
	if result.Status != "blocked" || !strings.Contains(result.Detail, "QCOM_IPA=disabled") {
		t.Fatalf("%+v", result)
	}
	interfacesFixtureConfig(t, c, "CONFIG_QCOM_IPA=m\nCONFIG_WWAN=y\nCONFIG_RMNET=y\n")
	if result = interfacesCellPrerequisites(c); result.Status != "observed" {
		t.Fatalf("enumeration must be observed: %+v", result)
	}
}

func TestInterfacesUSBMetadataNoEnumerationPass(t *testing.T) {
	c := interfacesFixture(t, map[string]string{
		"/sys/bus/usb/devices/usb1/speed": "480", "/sys/bus/usb/devices/usb2/speed": "5000",
		"/sys/bus/usb/devices/1-2/speed": "480", "/sys/bus/usb/devices/2-1/speed": "5000",
		"/sys/bus/usb/devices/2-1:1.0/speed": "5000", "/sys/bus/usb/devices/2-1/serial": "PRIVATE-SERIAL",
		"/sys/class/typec/port0/data_role": "[host] device", "/sys/class/typec/port0/power_role": "source [sink]",
		"/sys/class/typec/port0/orientation": "reverse", "/sys/class/typec/port0/power_operation_mode": "usb_power_delivery",
		"/sys/class/typec/port0-partner/uevent": "", "/sys/class/usb_role/role0/role": "host",
		"/sys/class/power_supply/usb0/type": "USB", "/sys/class/power_supply/usb0/online": "1", "/sys/class/power_supply/usb0/usb_type": "[PD] SDP",
	})
	for _, run := range []func(*AutoContext) AutoResult{interfacesUSBControllers, interfacesUSBAttached, interfacesUSBRoles, interfacesUSBPD} {
		result := run(c)
		if result.Status != "observed" || strings.Contains(result.Detail, "PRIVATE") {
			t.Fatalf("%+v", result)
		}
	}
	if result := interfacesUSBAttached(c); !strings.Contains(result.Detail, "descriptors=2") {
		t.Fatalf("interface counted as device: %+v", result)
	}
	if result := interfacesUSBRoles(c); !strings.Contains(result.Detail, "data_role=host") || !strings.Contains(result.Detail, "power_role=sink") {
		t.Fatalf("active bracket role lost: %+v", result)
	}
	if result := interfacesDockPaths(c); result.Status != "blocked" {
		t.Fatalf("unattributed dock must block: %+v", result)
	}
}

func interfacesBitmap(bits ...int) string {
	max := 0
	for _, bit := range bits {
		if bit > max {
			max = bit
		}
	}
	words := make([]uint64, max/strconv.IntSize+1)
	for _, bit := range bits {
		words[bit/strconv.IntSize] |= uint64(1) << uint(bit%strconv.IntSize)
	}
	var text []string
	for i := len(words) - 1; i >= 0; i-- {
		text = append(text, strconv.FormatUint(words[i], 16))
	}
	return strings.Join(text, " ")
}

func TestInterfacesInputCapabilityPrivacyAndStartup(t *testing.T) {
	files := map[string]string{}
	add := func(event, name, key, abs, prop string) {
		base := "/sys/class/input/" + event + "/device/"
		files[base+"name"] = name
		files[base+"capabilities/key"] = key
		files[base+"capabilities/abs"] = abs
		files[base+"properties"] = prop
		files[base+"uniq"] = "PRIVATE-SERIAL"
	}
	add("event0", "IPTSD Virtual Touchscreen", "0", interfacesBitmap(0x35, 0x36), interfacesBitmap(1))
	add("event1", "IPTSD Virtual Stylus", interfacesBitmap(0x140, 0x141, 0x14b), interfacesBitmap(0, 1, 0x18, 0x1a, 0x1b), "0")
	add("event2", "Microsoft Surface Keyboard", interfacesBitmap(30, 28), "0", "0")
	add("event3", "Microsoft Surface Touchpad", "0", interfacesBitmap(0x35, 0x36), interfacesBitmap(0))
	add("event4", "Surface Buttons", interfacesBitmap(114, 115, 116), "0", "0")
	files["/sys/class/input/event4/device/capabilities/sw"] = interfacesBitmap(0, 1)
	c := interfacesFixture(t, files)
	for _, feature := range []string{"touch", "pen", "keyboard", "touchpad", "buttons"} {
		result := interfacesInputCapability(c, feature)
		if result.Status != "observed" || strings.Contains(result.Detail, "PRIVATE") {
			t.Fatalf("%s %+v", feature, result)
		}
	}
	pen := interfacesInputCapability(c, "pen")
	if !strings.Contains(pen.Detail, "pressure=true") || !strings.Contains(pen.Detail, "tilt X=true") {
		t.Fatalf("capabilities lost: %+v", pen)
	}
	c.Run = func(args ...string) (string, error) {
		return "LoadState=loaded\nActiveState=active\nSubState=running\nNRestarts=1\n", nil
	}
	result := interfacesInputStartup(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "restarts=1") {
		t.Fatalf("restart concealed: %+v", result)
	}
	c.Run = func(args ...string) (string, error) {
		return "LoadState=loaded\nActiveState=failed\nSubState=failed\nNRestarts=0\n", nil
	}
	if result = interfacesInputStartup(c); result.Status != "fail" {
		t.Fatalf("known startup failure: %+v", result)
	}
	if interfacesBit("malformed", 0) {
		t.Fatal("malformed capability bitmap accepted")
	}
}

func TestInterfacesSensorsExcludeADCAndBoundedReads(t *testing.T) {
	c := interfacesFixture(t, map[string]string{
		"/sys/bus/iio/devices/iio:device0/name": "qcom-spmi-adc", "/sys/bus/iio/devices/iio:device0/in_voltage0_raw": "999",
		"/sys/bus/iio/devices/iio:device1/name": "tcs3430", "/sys/bus/iio/devices/iio:device1/in_intensity_x_raw": "0", "/sys/bus/iio/devices/iio:device1/in_intensity_ir_raw": "23",
		"/sys/bus/iio/devices/iio:device1/in_proximity_raw": "NaN",
	})
	result := interfacesSensorChannels(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "light channels=2") || !strings.Contains(result.Detail, "motion channels=0") {
		t.Fatalf("%+v", result)
	}
	if result = interfacesSensorRead(c, "light"); result.Status != "pass" || !strings.Contains(result.Detail, "zero-valued=1") {
		t.Fatalf("zero not functional light failure: %+v", result)
	}
	if result = interfacesSensorRead(c, "motion"); result.Status != "blocked" {
		t.Fatalf("ADC not motion substitute: %+v", result)
	}
	path := filepath.Join(c.Root, "sys/bus/iio/devices/iio:device1/in_intensity_x_raw")
	if err := os.WriteFile(path, []byte("NaN"), 0644); err != nil {
		t.Fatal(err)
	}
	if result = interfacesSensorRead(c, "light"); result.Status != "fail" {
		t.Fatalf("nonfinite data must fail: %+v", result)
	}
}

func TestInterfacesLiveSensorReadCommandIsBounded(t *testing.T) {
	c := &AutoContext{Run: func(args ...string) (string, error) {
		if strings.Join(args, " ") != "timeout --signal=TERM --kill-after=1s 3s cat /fixture/tcs/in_intensity_x_raw" {
			t.Fatalf("unexpected read command: %v", args)
		}
		return "0\n", nil
	}}
	out, err := interfacesBoundedSensorRead(c, "/fixture/tcs/in_intensity_x_raw")
	if err != nil || strings.TrimSpace(out) != "0" {
		t.Fatalf("%q %v", out, err)
	}
}

func TestInterfacesSensorServicesNoStartOrClaim(t *testing.T) {
	c := interfacesFixture(t, map[string]string{
		"/dev/fastrpc-sdsp-secure": "", "/sys/firmware/devicetree/base/soc@0/remoteproc@8300000/glink-edge/fastrpc/status": "disabled\x00",
	})
	c.Run = func(args ...string) (string, error) {
		if args[0] == "systemctl" && args[1] == "show" {
			return "LoadState=loaded\nActiveState=active\nSubState=running", nil
		}
		if args[0] != "busctl" || !strings.Contains(strings.Join(args, " "), "--auto-start=no") || args[len(args)-2] == "Claim" {
			t.Fatalf("unsafe query: %v", args)
		}
		switch args[len(args)-1] {
		case "HasAmbientLight", "HasCompass", "HasAccelerometer":
			return "b true", nil
		case "LightLevel", "CompassHeading":
			return "d 123", nil
		}
		t.Fatalf("unexpected query: %v", args)
		return "", nil
	}
	result := interfacesSensorBackend(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "running DT disables CDSP") {
		t.Fatalf("%+v", result)
	}
	result = interfacesSensorDesktop(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "may be stale") {
		t.Fatalf("cached value pass prohibited: %+v", result)
	}
}

func TestInterfacesCellularExistingBearerAndPrivacy(t *testing.T) {
	c := interfacesFixture(t, map[string]string{"/sys/class/net/wwan0/operstate": "up"})
	modemPath := "/org/freedesktop/ModemManager1/Modem/0"
	bearerPath := "/org/freedesktop/ModemManager1/Bearer/1"
	modem := map[string]any{"modem": map[string]any{
		"generic":  map[string]any{"state": "connected", "sim": "/org/freedesktop/ModemManager1/SIM/0", "bearers": []string{bearerPath}, "equipment-identifier": "PRIVATE-IMEI"},
		"3gpp":     map[string]any{"registration-state": "home", "operator-name": "PRIVATE-OPERATOR"},
		"location": map[string]any{"capabilities": []string{"gps-raw", "gps-nmea"}},
	}}
	bearer := map[string]any{"bearer": map[string]any{"status": map[string]any{"connected": "yes", "interface": "wwan0"}, "ipv4-config": map[string]any{"address": "192.0.2.23"}}}
	curlCalls := 0
	c.Run = func(args ...string) (string, error) {
		switch args[0] {
		case "systemctl":
			return "LoadState=loaded\nActiveState=active", nil
		case "qrtr-lookup":
			return "Service Version Instance Node Port\n16 2 0 0 70 Location service\n3 1 0 0 71 Device service", nil
		case "mmcli":
			switch args[1] {
			case "--list-modems":
				return interfacesFixtureJSON(t, map[string]any{"modem-list": []string{modemPath}}), nil
			case "--modem=" + modemPath:
				return interfacesFixtureJSON(t, modem), nil
			case "--bearer=" + bearerPath:
				return interfacesFixtureJSON(t, bearer), nil
			}
		case "curl":
			curlCalls++
			joined := strings.Join(args, " ")
			for _, guard := range []string{"--disable", "--head", "--interface if!wwan0", "--max-time 8", "--max-filesize 4096", "https://example.com/"} {
				if !strings.Contains(joined, guard) {
					t.Fatalf("curl guard missing %s: %v", guard, args)
				}
			}
			return "200 700 91", nil
		}
		t.Fatalf("unexpected command %v", args)
		return "", nil
	}
	for _, run := range []func(*AutoContext) AutoResult{interfacesCellControl, interfacesGNSSPath} {
		result := run(c)
		if result.Status != "observed" || strings.Contains(result.Detail, "PRIVATE") || strings.Contains(result.Detail, "192.0.2.23") {
			t.Fatalf("%+v", result)
		}
	}
	result := interfacesCellData(c)
	if result.Status != "pass" || !strings.Contains(result.Detail, "reachability only") || strings.Contains(result.Detail, "PRIVATE") {
		t.Fatalf("%+v", result)
	}
	if result = interfacesGNSSFix(c); result.Status != "blocked" {
		t.Fatalf("no GNSS session: %+v", result)
	}
	modem["modem"].(map[string]any)["generic"].(map[string]any)["state"] = "registered"
	if result = interfacesCellData(c); result.Status != "blocked" || curlCalls != 1 {
		t.Fatalf("no fabricated connection: %+v calls=%d", result, curlCalls)
	}
}

func TestInterfacesNoCellularFallbackOnUnboundBearer(t *testing.T) {
	c := interfacesFixture(t, nil)
	c.Run = func(args ...string) (string, error) {
		if args[0] == "curl" {
			t.Fatalf("unbound bearer must not run curl: %v", args)
		}
		if args[0] == "systemctl" {
			return "LoadState=loaded\nActiveState=active", nil
		}
		if args[1] == "--list-modems" {
			return `{"modem-list":["/org/freedesktop/ModemManager1/Modem/0"]}`, nil
		}
		if strings.HasPrefix(args[1], "--modem=") {
			return `{"modem":{"generic":{"state":"connected","bearers":["/org/freedesktop/ModemManager1/Bearer/0"]}}}`, nil
		}
		if strings.HasPrefix(args[1], "--bearer=") {
			return `{"bearer":{"status":{"connected":"yes","interface":"../../wlan0"}}}`, nil
		}
		return "", fmt.Errorf("unhandled query")
	}
	if result := interfacesCellData(c); result.Status != "blocked" {
		t.Fatalf("%+v", result)
	}
}
