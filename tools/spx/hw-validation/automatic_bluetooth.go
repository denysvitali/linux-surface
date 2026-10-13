package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

const bluetoothScanSeconds = "5"

func automaticBluetoothChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "bluetooth.inventory", Title: "Bluetooth paired, connected and service capability counts", Area: "Bluetooth", Kind: "inventory", Boxes: []string{"N02", "A04"}, Run: automaticBluetoothInventory},
		{ID: "bluetooth.discovery", Title: "Bounded Bluetooth discovery starts and releases its own session", Area: "Bluetooth", Kind: "functional", Boxes: []string{"N02"}, Run: automaticBluetoothDiscovery},
	}
}

type bluetoothAdapter struct {
	powered, discovering bool
}

type bluetoothDevice struct {
	address           string
	paired, connected bool
	hid, audio        bool
}

type bluetoothSnapshot struct {
	adapters map[string]bluetoothAdapter
	devices  map[string]bluetoothDevice
}

func bluetoothObjects(c *AutoContext) (bluetoothSnapshot, error) {
	output, err := c.Command("busctl", "--system", "--timeout=3", "--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
	if err != nil {
		status, detail := bluetoothCommandProblem(output, err, false)
		return bluetoothSnapshot{}, &bluetoothProblem{status, detail}
	}
	return bluetoothParseObjects(output)
}

type bluetoothProblem struct {
	status, detail string
}

func (e *bluetoothProblem) Error() string { return e.detail }

func bluetoothResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}

func bluetoothProblemResult(id string, err error) AutoResult {
	var problem *bluetoothProblem
	if errors.As(err, &problem) {
		return bluetoothResult(id, problem.status, problem.detail)
	}
	return bluetoothResult(id, "error", "BlueZ returned an unsupported or malformed object reply; no private reply retained")
}

// busctl represents each D-Bus variant with {"type": ..., "data": ...}.
func bluetoothUnwrap(value any) any {
	switch v := value.(type) {
	case map[string]any:
		if _, typed := v["type"].(string); typed && len(v) == 2 {
			if data, ok := v["data"]; ok {
				return bluetoothUnwrap(data)
			}
		}
		result := make(map[string]any, len(v))
		for key, child := range v {
			result[key] = bluetoothUnwrap(child)
		}
		return result
	case []any:
		result := make([]any, len(v))
		for i, child := range v {
			result[i] = bluetoothUnwrap(child)
		}
		return result
	default:
		return value
	}
}

func bluetoothParseObjects(output string) (bluetoothSnapshot, error) {
	var value any
	if err := json.Unmarshal([]byte(output), &value); err != nil {
		return bluetoothSnapshot{}, errors.New("invalid BlueZ JSON")
	}
	args, ok := bluetoothUnwrap(value).([]any)
	if !ok || len(args) != 1 {
		return bluetoothSnapshot{}, errors.New("invalid BlueZ arguments")
	}
	objects, ok := args[0].(map[string]any)
	if !ok {
		return bluetoothSnapshot{}, errors.New("invalid BlueZ objects")
	}
	snapshot := bluetoothSnapshot{adapters: map[string]bluetoothAdapter{}, devices: map[string]bluetoothDevice{}}
	for path, value := range objects {
		interfaces, ok := value.(map[string]any)
		if !ok {
			return bluetoothSnapshot{}, errors.New("invalid BlueZ interfaces")
		}
		if value, exists := interfaces["org.bluez.Adapter1"]; exists {
			props, ok := value.(map[string]any)
			if !ok {
				return bluetoothSnapshot{}, errors.New("invalid BlueZ adapter")
			}
			powered, powerOK := props["Powered"].(bool)
			discovering, discoveryOK := props["Discovering"].(bool)
			if !powerOK || !discoveryOK {
				return bluetoothSnapshot{}, errors.New("missing BlueZ adapter state")
			}
			snapshot.adapters[path] = bluetoothAdapter{powered: powered, discovering: discovering}
		}
		if value, exists := interfaces["org.bluez.Device1"]; exists {
			props, ok := value.(map[string]any)
			if !ok {
				return bluetoothSnapshot{}, errors.New("invalid BlueZ device")
			}
			address, _ := props["Address"].(string)
			paired, pairedOK := props["Paired"].(bool)
			connected, connectedOK := props["Connected"].(bool)
			if !bluetoothAddress.MatchString(address) || !pairedOK || !connectedOK {
				return bluetoothSnapshot{}, errors.New("missing BlueZ device state")
			}
			device := bluetoothDevice{address: strings.ToUpper(address), paired: paired, connected: connected}
			if uuids, exists := props["UUIDs"]; exists {
				services, ok := uuids.([]any)
				if !ok {
					return bluetoothSnapshot{}, errors.New("invalid BlueZ service list")
				}
				for _, service := range services {
					uuid, ok := service.(string)
					if !ok {
						return bluetoothSnapshot{}, errors.New("invalid BlueZ service UUID")
					}
					hid, audio := bluetoothServiceCapabilities(uuid)
					device.hid = device.hid || hid
					device.audio = device.audio || audio
				}
			}
			snapshot.devices[path] = device
		}
	}
	return snapshot, nil
}

func bluetoothServiceCapabilities(uuid string) (hid, audio bool) {
	uuid = strings.ToLower(uuid)
	if len(uuid) != 36 || !strings.HasPrefix(uuid, "0000") || !strings.HasSuffix(uuid, "-0000-1000-8000-00805f9b34fb") {
		return false, false
	}
	switch uuid[4:8] {
	case "1124", "1812": // Classic HID and HID over GATT.
		return true, false
	case "1108", "110a", "110b", "110c", "110d", "110e", "1112", "111e", "111f", "184e", "1850":
		return false, true
	}
	return false, false
}

func bluetoothCounts(snapshot bluetoothSnapshot) string {
	powered, discovering, paired, connected, hid, audio := 0, 0, 0, 0, 0, 0
	for _, adapter := range snapshot.adapters {
		if adapter.powered {
			powered++
		}
		if adapter.discovering {
			discovering++
		}
	}
	for _, device := range snapshot.devices {
		if device.paired {
			paired++
		}
		if device.connected {
			connected++
		}
		if device.hid {
			hid++
		}
		if device.audio {
			audio++
		}
	}
	return fmt.Sprintf("adapters=%d; powered=%d; discovering=%d; cached peers=%d; paired=%d; connected=%d; cached HID-capable=%d; cached audio-capable=%d", len(snapshot.adapters), powered, discovering, len(snapshot.devices), paired, connected, hid, audio)
}

func automaticBluetoothInventory(c *AutoContext) AutoResult {
	const id = "bluetooth.inventory"
	snapshot, err := bluetoothObjects(c)
	if err != nil {
		return bluetoothProblemResult(id, err)
	}
	if len(snapshot.adapters) == 0 {
		return bluetoothResult(id, "blocked", "BlueZ exposes no adapter interface; fitted-radio kernel/firmware/service support is not established, not hardware absence")
	}
	return bluetoothResult(id, "observed", bluetoothCounts(snapshot)+"; cached service metadata only; pairing, reconnect and peripheral use are not tested")
}

func automaticBluetoothDiscovery(c *AutoContext) AutoResult {
	const id = "bluetooth.discovery"
	before, err := bluetoothObjects(c)
	if err != nil {
		return bluetoothProblemResult(id, err)
	}
	if len(before.adapters) == 0 {
		return bluetoothResult(id, "blocked", "BlueZ exposes no adapter interface; fitted-radio kernel/firmware/service support is not established, not hardware absence")
	}
	if len(before.adapters) != 1 {
		return bluetoothResult(id, "blocked", "Multiple BlueZ adapters are exposed; a single unambiguous scan adapter is required")
	}
	var adapterPath string
	for path, adapter := range before.adapters {
		adapterPath = path
		if !adapter.powered {
			return bluetoothResult(id, "blocked", "Bluetooth radio is powered off or rfkill-blocked; power preference is unchanged")
		}
		if adapter.discovering {
			return bluetoothResult(id, "blocked", "Pre-existing Bluetooth discovery is active; its session and filters are left untouched")
		}
	}

	// BlueZ owns discovery per D-Bus sender. The timed CLI exit releases only
	// its own session (adapter.c discovery_disconnect). A separate 'scan off'
	// command would use another sender and must not be used for cleanup.
	output, scanErr := c.Command("env", "LC_ALL=C", "TERM=dumb", "bluetoothctl", "--timeout", bluetoothScanSeconds, "scan", "on")
	started, reports, peers := bluetoothFreshReports(output, before)
	var after bluetoothSnapshot
	for attempt := 0; attempt < 5; attempt++ {
		after, err = bluetoothObjects(c)
		if err != nil {
			return bluetoothProblemResult(id, err)
		}
		adapter, exists := after.adapters[adapterPath]
		if !exists || !adapter.powered {
			return bluetoothResult(id, "blocked", "Bluetooth adapter is unavailable or powered off after the scan; no power or module changes were requested")
		}
		if !adapter.discovering {
			break
		}
		if attempt == 4 {
			return bluetoothResult(id, "blocked", "Discovery remains active after the owned scanner exited: another client or delayed cleanup prevents confirmation; no stop command sent")
		}
		time.Sleep(100 * time.Millisecond)
	}
	for path, device := range before.devices {
		if device.connected && !after.devices[path].connected {
			return bluetoothResult(id, "fail", "A previously connected Bluetooth peripheral lost its connection during discovery; no disconnect was requested")
		}
	}
	if scanErr != nil || bluetoothScanProblem(output) {
		status, detail := bluetoothCommandProblem(output, scanErr, true)
		return bluetoothResult(id, status, detail+"; owned scanner exited; no global stop or radio change requested")
	}
	if !started {
		return bluetoothResult(id, "blocked", "bluetoothctl did not confirm discovery start; usable BlueZ scan support or permission was not established")
	}
	detail := fmt.Sprintf("Bounded 5-second discovery started; owned scanner exited and discovery is inactive; fresh reports=%d from peers=%d; prior connections retained; no power, pairing or disconnect changes", reports, peers)
	if peers == 0 {
		detail += "; no fresh peer report received, so radio reception is unproven"
	}
	return bluetoothResult(id, "pass", detail)
}

var bluetoothAddress = regexp.MustCompile(`(?i)^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$`)
var bluetoothANSI = regexp.MustCompile(`\x1b\[[0-?]*[ -/]*[@-~]`)
var bluetoothEvent = regexp.MustCompile(`(?i)^\[(NEW|CHG)\] Device ((?:[0-9a-f]{2}:){5}[0-9a-f]{2})(?:\s+(.*))?$`)
var bluetoothRSSI = regexp.MustCompile(`^RSSI: (?:-?[0-9]+|0x[0-9a-fA-F]+(?: \(-?[0-9]+\))?)$`)

func bluetoothLines(output string) []string {
	return strings.Split(strings.ReplaceAll(bluetoothANSI.ReplaceAllString(output, ""), "\r", "\n"), "\n")
}

func bluetoothFreshReports(output string, before bluetoothSnapshot) (started bool, reports, peers int) {
	cached := map[string]bool{}
	for _, device := range before.devices {
		cached[device.address] = true
	}
	fresh := map[string]bool{}
	active := false
	for _, raw := range bluetoothLines(output) {
		line := strings.TrimSpace(raw)
		if line == "Discovery started" {
			started, active = true, true
			continue
		}
		if line == "Discovery stopped" {
			active = false
		}
		if !active {
			continue
		}
		match := bluetoothEvent.FindStringSubmatch(line)
		if match == nil {
			continue
		}
		address := strings.ToUpper(match[2])
		newPeer := strings.EqualFold(match[1], "NEW") && !cached[address]
		rssi := strings.EqualFold(match[1], "CHG") && bluetoothRSSI.MatchString(match[3])
		if newPeer || rssi {
			reports++
			fresh[address] = true
		}
	}
	return started, reports, len(fresh)
}

func bluetoothScanProblem(output string) bool {
	for _, raw := range bluetoothLines(output) {
		line := strings.TrimSpace(raw)
		if strings.HasPrefix(line, "Failed to ") || line == "No default controller available" || strings.HasPrefix(line, "Invalid command") {
			return true
		}
	}
	return false
}

// Classification is fixed text: neither command output nor errors (which may
// include Bluetooth addresses or aliases) are copied into the report.
func bluetoothCommandProblem(output string, err error, scan bool) (string, string) {
	text := strings.ToLower(bluetoothANSI.ReplaceAllString(output, ""))
	if scan {
		// Nearby peer aliases are not command diagnostics.
		var diagnostics []string
		for _, raw := range bluetoothLines(output) {
			line := strings.TrimSpace(raw)
			if strings.HasPrefix(line, "Failed to ") || strings.HasPrefix(line, "env:") || line == "No default controller available" || strings.HasPrefix(line, "Invalid command") {
				diagnostics = append(diagnostics, line)
			}
		}
		text = strings.ToLower(strings.Join(diagnostics, " "))
	}
	if err != nil {
		text += " " + strings.ToLower(err.Error())
	}
	groups := []struct {
		matches []string
		detail  string
	}{
		{[]string{"notauthorized", "not authorized", "permission denied", "access denied", "accessdenied"}, "Bluetooth command permission is denied by the system bus or BlueZ policy"},
		{[]string{"notready", "not ready", "powered off", "rfkill"}, "Bluetooth radio is not ready or is blocked; no power preference changed"},
		{[]string{"inprogress", "in progress", "busy"}, "BlueZ discovery is busy with another operation; no other session stopped"},
		{[]string{"serviceunknown", "namehasnoowner", "not provided by any .service", "failed to connect to bus", "connection refused"}, "BlueZ service or system bus is unavailable"},
		{[]string{"executable file not found", "no such file or directory", "command not found"}, "Required busctl, env or bluetoothctl command tool is unavailable"},
		{[]string{"external commands disabled for fixture root"}, "Bluetooth commands are disabled for this fixture-only run"},
		{[]string{"notsupported", "not supported", "unrecognized option", "unknown option", "invalid command", "no default controller available"}, "Bluetooth scan CLI or fitted-radio support is unavailable"},
	}
	for _, group := range groups {
		for _, match := range group.matches {
			if strings.Contains(text, match) {
				return "blocked", group.detail
			}
		}
	}
	if scan && (strings.Contains(text, "org.bluez.error.failed") || strings.Contains(text, "input/output error")) {
		return "fail", "BlueZ reported a discovery operation failure on the powered adapter"
	}
	return "error", "Bluetooth command did not complete successfully; private command replies were discarded"
}
