package main

import (
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

func automaticInterfacesChecks() []AutoCheck {
	checks := []AutoCheck{
		{ID: "cell.prerequisites", Title: "Cellular IPA/WWAN data-path prerequisites", Area: "Cellular", Kind: "inventory", Boxes: []string{"N03"}, Run: interfacesCellPrerequisites},
		{ID: "cell.control", Title: "ModemManager and QRTR control metadata", Area: "Cellular", Kind: "inventory", Boxes: []string{"N03", "B04"}, Run: interfacesCellControl},
		{ID: "cell.data", Title: "HTTPS HEAD reachability on an existing cellular bearer", Area: "Cellular", Kind: "functional", Boxes: []string{"N03"}, Run: interfacesCellData},
		{ID: "gnss.path", Title: "GNSS class and modem location capability", Area: "GNSS", Kind: "inventory", Boxes: []string{"N04"}, Run: interfacesGNSSPath},
		{ID: "gnss.fix", Title: "Real GNSS fix and reacquisition", Area: "GNSS", Kind: "functional", Boxes: []string{"N04"}, Run: interfacesGNSSFix},
		{ID: "usb.controllers", Title: "USB controller root hubs and advertised speeds", Area: "USB", Kind: "inventory", Boxes: []string{"U01"}, Run: interfacesUSBControllers},
		{ID: "usb.attached", Title: "Attached USB device negotiated speeds", Area: "USB", Kind: "inventory", Boxes: []string{"U01", "U04"}, Run: interfacesUSBAttached},
		{ID: "usb.transfer", Title: "Checksum-verified disposable USB storage transfer", Area: "USB", Kind: "functional", Boxes: []string{"U01"}, Run: func(c *AutoContext) AutoResult {
			return interfacesResult("usb.transfer", "blocked", "USB-backed disposable transfer probe is not implemented: needs an explicit mounted fixture and verified USB block-device ancestry before bounded checksum I/O. Ordinary root-storage I/O or speed enumeration cannot prove USB transfer; no block device opened or file written")
		}},
		{ID: "usb.roles", Title: "Read-only Type-C attachment and role metadata", Area: "USB-C", Kind: "inventory", Boxes: []string{"U02"}, Run: interfacesUSBRoles},
		{ID: "usb.pd", Title: "Reported USB-C power-delivery metadata", Area: "USB-C", Kind: "inventory", Boxes: []string{"U02", "P01"}, Run: interfacesUSBPD},
		{ID: "usb.typec-routing", Title: "Data delivery over an attributable Type-C route", Area: "USB-C", Kind: "functional", Boxes: []string{"U02"}, Run: func(c *AutoContext) AutoResult {
			return interfacesResult("usb.typec-routing", "blocked", "Full firmware Type-C/PD and lane-routing support remains unresolved; functional route/transfer probe and already-attached attributable fixture are unavailable. Port-zero HPD metadata does not prove data delivery; no role, cable, PHY or display changes attempted")
		}},
		{ID: "dock.paths", Title: "Dock and Surface Connect attached path attribution", Area: "Dock and Surface Connect", Kind: "inventory", Boxes: []string{"U04"}, Run: interfacesDockPaths},
		{ID: "dock.concurrent", Title: "Attributable dock concurrent data and display operation", Area: "Dock and Surface Connect", Kind: "functional", Boxes: []string{"U04"}, Run: func(c *AutoContext) AutoResult {
			return interfacesResult("dock.concurrent", "blocked", "Concurrent dock probe is not implemented; needs an already-attached identifiable dock, supported connector topology, safe data fixture and active external scanout. Generic USB/display counts are inventory; no attachment, playback or charging actions attempted")
		}},
		{ID: "input.startup", Title: "IPTSD service and virtual-device startup health", Area: "Input", Kind: "inventory", Boxes: []string{"I01"}, Run: interfacesInputStartup},
		{ID: "input.accessory", Title: "Pen and keyboard accessory battery metadata", Area: "Input", Kind: "inventory", Boxes: []string{"I07"}, Run: interfacesInputAccessory},
		{ID: "sensors.channels", Title: "Light and motion channel capabilities", Area: "Sensors", Kind: "inventory", Boxes: []string{"S01", "S02"}, Run: interfacesSensorChannels},
		{ID: "sensors.backend", Title: "SDSP sensor backend and startup services", Area: "Sensors", Kind: "inventory", Boxes: []string{"S02", "B07"}, Run: interfacesSensorBackend},
		{ID: "sensors.desktop", Title: "Already-running SensorProxy cached properties", Area: "Sensors", Kind: "inventory", Boxes: []string{"S01", "S02"}, Run: interfacesSensorDesktop},
		{ID: "sensors.light-lux", Title: "Calibrated ambient-light report delivery", Area: "Sensors", Kind: "functional", Boxes: []string{"S01"}, Run: func(c *AutoContext) AutoResult {
			return interfacesResult("sensors.light-lux", "blocked", "No verified TCS3430 lux conversion or desktop ambient-light source is implemented; raw XYZ/IR reads do not establish calibrated light delivery. No stimulus or brightness change requested")
		}},
		{ID: "sensors.desktop-motion", Title: "Fresh desktop accelerometer delivery", Area: "Sensors", Kind: "functional", Boxes: []string{"S02"}, Run: interfacesSensorDesktopDelivery},
		{ID: "sensors.desktop-compass", Title: "Fresh desktop compass delivery", Area: "Sensors", Kind: "functional", Boxes: []string{"S02"}, Run: interfacesSensorDesktopCompass},
	}
	for _, feature := range []struct{ id, title, box string }{
		{"touch", "Touchscreen direct multi-touch capabilities", "I02"},
		{"pen", "Pen position, pressure and tilt capabilities", "I03"},
		{"keyboard", "Keyboard key and indicator capabilities", "I04"},
		{"touchpad", "Touchpad pointer multi-touch capabilities", "I05"},
		{"buttons", "Power/volume and posture switch capabilities", "I06"},
	} {
		feature := feature
		checks = append(checks, AutoCheck{ID: "input." + feature.id, Title: feature.title, Area: "Input", Kind: "inventory", Boxes: []string{feature.box}, Run: func(c *AutoContext) AutoResult { return interfacesInputCapability(c, feature.id) }})
	}
	for _, group := range []struct{ id, title, box string }{
		{"light", "One-shot light-channel numeric read", "S01"},
		{"motion", "Bounded SSC accelerometer/gyro/magnetometer delivery", "S02"},
	} {
		group := group
		checks = append(checks, AutoCheck{ID: "sensors." + group.id + "-read", Title: group.title, Area: "Sensors", Kind: "functional", Boxes: []string{group.box}, Run: func(c *AutoContext) AutoResult { return interfacesSensorRead(c, group.id) }})
	}
	return checks
}

func interfacesResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}

// Only controlled values are emitted. Device names, SIM identifiers, addresses,
// operator names, bearer configuration and command stdout never enter reports.
func interfacesEnum(value string, allowed ...string) string {
	value = strings.TrimSpace(value)
	for _, word := range strings.Fields(value) {
		if strings.HasPrefix(word, "[") && strings.HasSuffix(word, "]") {
			value = strings.Trim(word, "[]")
			break
		}
	}
	for _, option := range allowed {
		if value == option {
			return value
		}
	}
	return "unreported"
}

func interfacesService(c *AutoContext, unit string) (map[string]string, error) {
	out, err := c.Command("systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,NRestarts", "--no-pager")
	if err != nil {
		return nil, err
	}
	values := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		p := strings.SplitN(line, "=", 2)
		if len(p) == 2 {
			values[p[0]] = p[1]
		}
	}
	if values["ActiveState"] == "" {
		return nil, errors.New("service status unavailable")
	}
	return values, nil
}

func interfacesConfig(c *AutoContext) map[string]string {
	values := map[string]string{}
	data, err := c.ReadBytes("/proc/config.gz")
	if err == nil {
		gz, e := gzip.NewReader(strings.NewReader(string(data)))
		if e == nil {
			defer gz.Close()
			b, e := io.ReadAll(io.LimitReader(gz, 4<<20))
			if e == nil {
				interfacesConfigValues(string(b), values)
			}
		}
	}
	if len(values) == 0 {
		if release, e := c.Read("/proc/sys/kernel/osrelease"); e == nil && !strings.ContainsAny(release, "/\\") {
			if text, e := c.Read("/boot/config-" + release); e == nil {
				interfacesConfigValues(text, values)
			}
		}
	}
	return values
}

func interfacesConfigValues(text string, values map[string]string) {
	for _, line := range strings.Split(text, "\n") {
		for _, key := range []string{"QCOM_IPA", "WWAN", "RMNET", "QCOM_FASTRPC"} {
			name := "CONFIG_" + key
			if strings.HasPrefix(line, name+"=") {
				values[key] = strings.TrimPrefix(line, name+"=")
			}
			if line == "# "+name+" is not set" {
				values[key] = "disabled"
			}
		}
	}
}

func interfacesCellNetPaths(c *AutoContext) []string {
	paths, _ := c.Glob("/sys/class/net/*")
	var cellular []string
	for _, p := range paths {
		n := filepath.Base(p)
		if strings.HasPrefix(n, "wwan") || strings.HasPrefix(n, "rmnet") {
			cellular = append(cellular, p)
		}
	}
	return cellular
}

func interfacesSourceIPAGap(c *AutoContext) string {
	if c.Repo == "" {
		return ""
	}
	ipa, e1 := os.ReadFile(filepath.Join(c.Repo, "drivers/net/ipa/ipa_main.c"))
	dts, e2 := os.ReadFile(filepath.Join(c.Repo, "arch/arm64/boot/dts/qcom/sc8180x.dtsi"))
	if e1 == nil && e2 == nil && !strings.Contains(string(ipa), "qcom,sc8180x-ipa") && !strings.Contains(string(dts), "qcom,sc8180x-ipa") {
		return "; repository lacks SC8180X IPA match/device resources (source finding, not deployed config)"
	}
	return ""
}

func interfacesCellPrerequisites(c *AutoContext) AutoResult {
	cfg := interfacesConfig(c)
	var parts []string
	missing := false
	for _, key := range []string{"QCOM_IPA", "WWAN", "RMNET"} {
		v := interfacesEnum(cfg[key], "y", "m", "n", "disabled")
		parts = append(parts, key+"="+v)
		missing = missing || v == "n" || v == "disabled"
	}
	wwan, _ := c.Glob("/sys/class/wwan/*")
	net := interfacesCellNetPaths(c)
	parts = append(parts, fmt.Sprintf("WWAN control nodes=%d, cellular-style net paths=%d", len(wwan), len(net)))
	detail := strings.Join(parts, "; ") + interfacesSourceIPAGap(c)
	if missing || len(net) == 0 {
		return interfacesResult("cell.prerequisites", "blocked", detail+"; missing kernel/data-path integration or exposed path; SIM/service and genuine same-device modem provisioning are separate prerequisites, not hardware absence")
	}
	return interfacesResult("cell.prerequisites", "observed", detail+"; interface enumeration does not prove connectivity")
}

func interfacesJSON(c *AutoContext, args ...string) (map[string]any, error) {
	out, err := c.Command(args...)
	if err != nil {
		return nil, err
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(out), &obj); err != nil {
		return nil, err
	}
	return obj, nil
}

func interfacesJSONValue(obj map[string]any, keys ...string) any {
	var value any = obj
	for _, key := range keys {
		m, ok := value.(map[string]any)
		if !ok {
			return nil
		}
		value = m[key]
	}
	return value
}

func interfacesJSONString(obj map[string]any, keys ...string) string {
	value := interfacesJSONValue(obj, keys...)
	if s, ok := value.(string); ok {
		return s
	}
	if b, ok := value.(bool); ok {
		return strconv.FormatBool(b)
	}
	return ""
}

func interfacesJSONStrings(obj map[string]any, keys ...string) []string {
	var result []string
	if a, ok := interfacesJSONValue(obj, keys...).([]any); ok {
		for _, v := range a {
			if s, ok := v.(string); ok {
				result = append(result, s)
			}
		}
	}
	return result
}

var interfacesModemPath = regexp.MustCompile(`^/org/freedesktop/ModemManager1/Modem/[0-9]+$`)
var interfacesBearerPath = regexp.MustCompile(`^/org/freedesktop/ModemManager1/Bearer/[0-9]+$`)
var interfacesNetName = regexp.MustCompile(`^[a-zA-Z0-9_.-]{1,15}$`)

func interfacesModems(c *AutoContext) ([]map[string]any, string) {
	state, err := interfacesService(c, "ModemManager.service")
	if err != nil {
		return nil, "ModemManager service query unavailable (tool, bus or permission)"
	}
	if state["LoadState"] == "not-found" {
		return nil, "ModemManager service not installed"
	}
	if state["ActiveState"] != "active" {
		return nil, "ModemManager not active; it will not be started automatically"
	}
	list, err := interfacesJSON(c, "mmcli", "--list-modems", "--output-json")
	if err != nil {
		return nil, "ModemManager discovery query unavailable (mmcli, bus or permission)"
	}
	var modems []map[string]any
	for _, path := range interfacesJSONStrings(list, "modem-list") {
		if !interfacesModemPath.MatchString(path) {
			continue
		}
		modem, err := interfacesJSON(c, "mmcli", "--modem="+path, "--output-json")
		if err != nil {
			return nil, "Discovered modem metadata query unavailable"
		}
		modems = append(modems, modem)
	}
	if len(modems) == 0 {
		return nil, "No modem discovered by ModemManager; control integration/provisioning unresolved, not hardware absence"
	}
	return modems, ""
}

func interfacesQRTR(c *AutoContext) (int, int, bool) {
	out, err := c.Command("qrtr-lookup")
	if err != nil {
		return 0, 0, false
	}
	count, loc := 0, 0
	// qrtr-lookup's table columns are Service, Version, Instance, Node, Port.
	for _, line := range strings.Split(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 5 {
			continue
		}
		valid := true
		for _, field := range fields[:5] {
			if _, err := strconv.ParseUint(field, 10, 32); err != nil {
				valid = false
			}
		}
		if valid {
			count++
			if fields[0] == "16" {
				loc++
			}
		}
	}
	return count, loc, true
}

func interfacesCellControl(c *AutoContext) AutoResult {
	services, _, qrtr := interfacesQRTR(c)
	modems, reason := interfacesModems(c)
	detail := fmt.Sprintf("QRTR table available=%t, advertised services=%d; discovered modems=%d", qrtr, services, len(modems))
	if reason != "" {
		return interfacesResult("cell.control", "blocked", detail+"; "+reason)
	}
	registered, connected, sims := 0, 0, 0
	var states []string
	for _, modem := range modems {
		state := interfacesEnum(interfacesJSONString(modem, "modem", "generic", "state"), "failed", "unknown", "initializing", "locked", "disabled", "disabling", "enabling", "enabled", "searching", "registered", "disconnecting", "connecting", "connected")
		states = append(states, state)
		reg := interfacesJSONString(modem, "modem", "3gpp", "registration-state")
		if reg == "home" || reg == "roaming" {
			registered++
		}
		if state == "connected" {
			connected++
		}
		if sim := interfacesJSONString(modem, "modem", "generic", "sim"); strings.HasPrefix(sim, "/org/freedesktop/ModemManager1/SIM/") {
			sims++
		}
	}
	sort.Strings(states)
	detail += fmt.Sprintf("; states=%s, registered=%d, connected=%d, SIM objects=%d; no SIM identity/operator/location read; online-mode and genuine backing storage remain prerequisites unless resolved on this boot", strings.Join(states, ","), registered, connected, sims)
	return interfacesResult("cell.control", "observed", detail)
}

func interfacesCellData(c *AutoContext) AutoResult {
	modems, reason := interfacesModems(c)
	if reason != "" {
		return interfacesResult("cell.data", "blocked", reason+"; no connection or radio/provisioning change attempted")
	}
	var iface string
	for _, modem := range modems {
		if interfacesJSONString(modem, "modem", "generic", "state") != "connected" {
			continue
		}
		for _, path := range interfacesJSONStrings(modem, "modem", "generic", "bearers") {
			if !interfacesBearerPath.MatchString(path) {
				continue
			}
			bearer, err := interfacesJSON(c, "mmcli", "--bearer="+path, "--output-json")
			if err != nil {
				continue
			}
			connected := interfacesJSONString(bearer, "bearer", "status", "connected")
			candidate := interfacesJSONString(bearer, "bearer", "status", "interface")
			if (connected == "yes" || connected == "true") && interfacesNetName.MatchString(candidate) {
				if state, e := c.Read("/sys/class/net/" + candidate + "/operstate"); e == nil && state == "up" {
					iface = candidate
					break
				}
			}
		}
		if iface != "" {
			break
		}
	}
	if iface == "" {
		return interfacesResult("cell.data", "blocked", "No existing connected modem bearer with an up host data interface; IPA/RMNET/WWAN, provisioning, registration and SIM/service must be resolved; no connection fabricated")
	}
	// if! forces a real interface binding; proxies are disabled to prevent Wi-Fi
	// fallback. HEAD avoids a response body and is reachability, not throughput.
	out, err := c.Command("curl", "--disable", "--silent", "--show-error", "--head", "--proxy", "", "--noproxy", "*", "--interface", "if!"+iface, "--connect-timeout", "4", "--max-time", "8", "--max-filesize", "4096", "--output", "/dev/null", "--write-out", "%{http_code} %{size_header} %{size_request}", "https://example.com/")
	if err != nil {
		var execErr *exec.Error
		if errors.As(err, &execErr) || errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission) || strings.Contains(out, "not permitted") || strings.Contains(out, "Could not resolve") {
			return interfacesResult("cell.data", "blocked", "Bound HTTPS test unavailable: curl, binding permission or DNS prerequisite; no private command output retained")
		}
		return interfacesResult("cell.data", "blocked", "Existing bearer could not complete the bounded public HTTPS transaction; endpoint/routing/service availability is unresolved, not a specific hardware-failure verdict")
	}
	fields := strings.Fields(out)
	if len(fields) != 3 {
		return interfacesResult("cell.data", "error", "HTTPS transaction summary could not be parsed; raw output discarded")
	}
	code, e1 := strconv.Atoi(fields[0])
	received, e2 := strconv.ParseFloat(fields[1], 64)
	sent, e3 := strconv.ParseFloat(fields[2], 64)
	if e1 != nil || e2 != nil || e3 != nil || math.IsNaN(received) || math.IsInf(received, 0) || math.IsNaN(sent) || math.IsInf(sent, 0) {
		return interfacesResult("cell.data", "error", "HTTPS transaction counters invalid; raw output discarded")
	}
	if code < 200 || code >= 300 {
		return interfacesResult("cell.data", "blocked", fmt.Sprintf("Public HTTPS endpoint returned HTTP %d; data-transfer fixture unavailable", code))
	}
	if received <= 0 || sent <= 0 {
		return interfacesResult("cell.data", "fail", "Connected-bearer HEAD transaction returned no request/response-header byte evidence")
	}
	return interfacesResult("cell.data", "pass", fmt.Sprintf("Existing cellular bearer, forced host-interface binding; HEAD https://example.com/, max-time=8s, max-filesize=4096 bytes, no response body; request bytes=%.0f, response-header bytes=%.0f; reachability only, not bidirectional data throughput, radio changes, reconnect or resume; identifiers discarded", sent, received))
}

func interfacesGNSSPath(c *AutoContext) AutoResult {
	class, _ := c.Glob("/sys/class/gnss/*")
	_, loc, qrtr := interfacesQRTR(c)
	modems, reason := interfacesModems(c)
	capable := 0
	for _, modem := range modems {
		for _, capability := range interfacesJSONStrings(modem, "modem", "location", "capabilities") {
			if capability == "gps-raw" || capability == "gps-nmea" || capability == "agps-msb" || capability == "agps-msa" {
				capable++
				break
			}
		}
	}
	detail := fmt.Sprintf("GNSS class paths=%d; QRTR table available=%t, LOC service16 entries=%d; modems advertising GNSS=%d; no position/session query", len(class), qrtr, loc, capable)
	if len(class)+loc+capable == 0 {
		return interfacesResult("gnss.path", "blocked", detail+"; location interface/control integration unresolved; missing GNSS class does not establish hardware absence; "+reason)
	}
	return interfacesResult("gnss.path", "observed", detail+"; capability alone is not a fix; prior factory-test/DeviceNotReady and genuine provisioning must be resolved rather than repeating reception trials")
}

func interfacesGNSSFix(c *AutoContext) AutoResult {
	modems, reason := interfacesModems(c)
	connected := 0
	for _, modem := range modems {
		if interfacesJSONString(modem, "modem", "generic", "state") == "connected" {
			connected++
		}
	}
	if reason == "" {
		reason = fmt.Sprintf("Modem control discovered=%d, connected=%d", len(modems), connected)
	}
	return interfacesResult("gnss.fix", "blocked", reason+"; real fix/reacquisition requires a separately authorized positioning session and suitable reception; automatic scans do not start GNSS or collect position; previous online-mode/provisioning gap is not cured by LOC enumeration")
}

var interfacesUSBDeviceName = regexp.MustCompile(`^[0-9]+-[0-9]+(?:\.[0-9]+)*$`)
var interfacesUSBRootName = regexp.MustCompile(`^usb[0-9]+$`)

func interfacesUSBDevices(c *AutoContext, roots bool) (int, []string, error) {
	paths, err := c.Glob("/sys/bus/usb/devices/*")
	count := 0
	var speeds []string
	for _, p := range paths {
		name := filepath.Base(p)
		if (roots && !interfacesUSBRootName.MatchString(name)) || (!roots && !interfacesUSBDeviceName.MatchString(name)) {
			continue
		}
		count++
		if text, e := c.Read(p + "/speed"); e == nil {
			if speed, e := strconv.ParseFloat(text, 64); e == nil && speed > 0 && speed <= 80000 {
				speeds = append(speeds, strconv.FormatFloat(speed, 'f', -1, 64))
			}
		}
	}
	sort.Strings(speeds)
	return count, speeds, err
}

func interfacesUSBControllers(c *AutoContext) AutoResult {
	count, speeds, err := interfacesUSBDevices(c, true)
	if err != nil || count == 0 {
		return interfacesResult("usb.controllers", "blocked", "USB root-hub metadata not exposed/readable; controller support/permissions unresolved, not hardware absence")
	}
	return interfacesResult("usb.controllers", "observed", fmt.Sprintf("USB root hubs=%d, advertised rates(Mbit/s)=%s; root hubs are not a physical-port count or data-transfer proof", count, strings.Join(speeds, ",")))
}

func interfacesUSBAttached(c *AutoContext) AutoResult {
	count, speeds, err := interfacesUSBDevices(c, false)
	if err != nil || count == 0 {
		return interfacesResult("usb.attached", "blocked", "No readable attached non-root USB device fixture; both ports/orientations and checksum transfer remain untested, not hardware absent")
	}
	return interfacesResult("usb.attached", "observed", fmt.Sprintf("Attached USB device descriptors=%d, negotiated rates(Mbit/s)=%s; no product/serial retained; rates/enumeration are not checksum transfers or physical-port/orientation coverage", count, strings.Join(speeds, ",")))
}

var interfacesTypeCPort = regexp.MustCompile(`^port[0-9]+$`)

func interfacesUSBRoles(c *AutoContext) AutoResult {
	ports, _ := c.Glob("/sys/class/typec/port*")
	roles, _ := c.Glob("/sys/class/usb_role/*")
	count, partners := 0, 0
	var values []string
	for _, p := range ports {
		if strings.HasSuffix(filepath.Base(p), "-partner") {
			partners++
		}
		if !interfacesTypeCPort.MatchString(filepath.Base(p)) {
			continue
		}
		count++
		for _, attr := range []string{"data_role", "power_role", "orientation"} {
			if text, e := c.Read(p + "/" + attr); e == nil {
				values = append(values, attr+"="+interfacesEnum(text, "host", "device", "source", "sink", "normal", "reverse", "none"))
			}
		}
	}
	for _, p := range roles {
		if text, e := c.Read(p + "/role"); e == nil {
			values = append(values, "usb_role="+interfacesEnum(text, "host", "device", "none"))
		}
	}
	detail := fmt.Sprintf("Type-C class ports=%d, partner paths=%d, USB role interfaces=%d; %s", count, partners, len(roles), strings.Join(values, ", "))
	if len(values) == 0 {
		return interfacesResult("usb.roles", "blocked", detail+"; role/orientation reporting interface missing; the SPX port-zero HPD bridge is not full two-port Type-C/PD integration")
	}
	return interfacesResult("usb.roles", "observed", detail+"; current role metadata only; no role/orientation changes or physical port attribution tested")
}

func interfacesUSBPD(c *AutoContext) AutoResult {
	ports, _ := c.Glob("/sys/class/typec/port*")
	supplies, _ := c.Glob("/sys/class/power_supply/*")
	pdModes, usbSupplies, online, pdSupplies := 0, 0, 0, 0
	for _, p := range ports {
		if !interfacesTypeCPort.MatchString(filepath.Base(p)) {
			continue
		}
		if mode, e := c.Read(p + "/power_operation_mode"); e == nil && mode == "usb_power_delivery" {
			pdModes++
		}
	}
	for _, p := range supplies {
		t, e := c.Read(p + "/type")
		if e != nil || !strings.HasPrefix(t, "USB") {
			continue
		}
		usbSupplies++
		if value, e := c.Read(p + "/online"); e == nil && value == "1" {
			online++
		}
		if value, e := c.Read(p + "/usb_type"); e == nil && interfacesEnum(value, "PD", "PD_PPS", "PD_DRP") != "unreported" {
			pdSupplies++
		}
	}
	detail := fmt.Sprintf("Type-C ports reporting PD mode=%d; USB power interfaces=%d, online=%d, reporting PD type=%d", pdModes, usbSupplies, online, pdSupplies)
	if pdModes+usbSupplies == 0 {
		return interfacesResult("usb.pd", "blocked", detail+"; no supported PD contract/charger reporting path; firmware PD/second-port contract unresolved, not absence of charging hardware")
	}
	return interfacesResult("usb.pd", "observed", detail+"; advertised/instantaneous power state only, not negotiation, attach/detach or charger coverage; no battery load/test")
}

func interfacesDockPaths(c *AutoContext) AutoResult {
	usb, _, _ := interfacesUSBDevices(c, false)
	thunderbolt, _ := c.Glob("/sys/bus/thunderbolt/devices/*")
	aggregator, _ := c.Glob("/sys/bus/surface_aggregator/devices/*")
	net, _ := c.Glob("/sys/class/net/*")
	wired := 0
	for _, p := range net {
		if filepath.Base(p) == "lo" {
			continue
		}
		if t, e := c.Read(p + "/type"); e == nil && t == "1" {
			if _, e := c.Read(p + "/wireless/uevent"); e != nil {
				if _, e := c.Read(p + "/phy80211/name"); e != nil {
					wired++
				}
			}
		}
	}
	drm, _ := c.Glob("/sys/class/drm/card*-*")
	display := 0
	for _, p := range drm {
		n := filepath.Base(p)
		if !strings.Contains(n, "-DP-") && !strings.Contains(n, "-HDMI-") {
			continue
		}
		if status, e := c.Read(p + "/status"); e == nil && status == "connected" {
			display++
		}
	}
	return interfacesResult("dock.paths", "blocked", fmt.Sprintf("Current paths: non-root USB=%d, non-wireless Ethernet-style=%d, connected external DRM=%d, Thunderbolt bus entries=%d, Surface Aggregator clients=%d; supported Surface Connect attachment/capability attribution unavailable. These counts do not identify connector/dock, Thunderbolt mode, audio/charging or concurrent operation; accessory topology fixture/firmware contract needed", usb, wired, display, len(thunderbolt), len(aggregator)))
}

type interfacesInput struct {
	key, abs, sw, led, props string
	fitted, virtual          bool
}

func interfacesInputs(c *AutoContext) []interfacesInput {
	paths, _ := c.Glob("/sys/class/input/event*")
	var inputs []interfacesInput
	for _, p := range paths {
		name, err := c.Read(p + "/device/name")
		if err != nil {
			continue
		}
		lower := strings.ToLower(name)
		in := interfacesInput{fitted: strings.Contains(lower, "surface") || strings.Contains(lower, "iptsd") || strings.Contains(lower, "045e:0c21"), virtual: strings.Contains(lower, "iptsd virtual")}
		in.key, _ = c.Read(p + "/device/capabilities/key")
		in.abs, _ = c.Read(p + "/device/capabilities/abs")
		in.sw, _ = c.Read(p + "/device/capabilities/sw")
		in.led, _ = c.Read(p + "/device/capabilities/led")
		in.props, _ = c.Read(p + "/device/properties")
		inputs = append(inputs, in)
	}
	sort.SliceStable(inputs, func(i, j int) bool { return inputs[i].fitted && !inputs[j].fitted })
	return inputs
}

func interfacesBit(bitmap string, bit int) bool {
	words := strings.Fields(bitmap)
	index := len(words) - 1 - bit/strconv.IntSize
	if index < 0 {
		return false
	}
	for _, word := range words {
		if _, err := strconv.ParseUint(word, 16, strconv.IntSize); err != nil {
			return false
		}
	}
	word, err := strconv.ParseUint(words[index], 16, strconv.IntSize)
	return err == nil && word&(uint64(1)<<uint(bit%strconv.IntSize)) != 0
}

func interfacesInputMatches(in interfacesInput, feature string) bool {
	switch feature {
	case "touch":
		return interfacesBit(in.props, 1) && interfacesBit(in.abs, 0x35) && interfacesBit(in.abs, 0x36) && !interfacesBit(in.key, 0x140)
	case "pen":
		return interfacesBit(in.key, 0x140) && interfacesBit(in.abs, 0) && interfacesBit(in.abs, 1)
	case "keyboard":
		return interfacesBit(in.key, 30) && interfacesBit(in.key, 28)
	case "touchpad":
		return interfacesBit(in.props, 0) && interfacesBit(in.abs, 0x35) && interfacesBit(in.abs, 0x36) && !interfacesBit(in.key, 0x140)
	case "buttons":
		return interfacesBit(in.key, 116) || interfacesBit(in.key, 114) || interfacesBit(in.key, 115) || interfacesBit(in.sw, 0) || interfacesBit(in.sw, 1)
	}
	return false
}

func interfacesInputCapability(c *AutoContext, feature string) AutoResult {
	for _, in := range interfacesInputs(c) {
		if !interfacesInputMatches(in, feature) {
			continue
		}
		detail := fmt.Sprintf("Matching input capability interface exposed; Surface/IPTSD identified=%t", in.fitted)
		if feature == "pen" {
			detail += fmt.Sprintf("; pressure=%t, tilt X=%t, tilt Y=%t, eraser=%t, barrel buttons=%t", interfacesBit(in.abs, 0x18), interfacesBit(in.abs, 0x1a), interfacesBit(in.abs, 0x1b), interfacesBit(in.key, 0x141), interfacesBit(in.key, 0x14b))
		}
		if feature == "keyboard" {
			detail += fmt.Sprintf("; CapsLock indicator=%t", interfacesBit(in.led, 1))
		}
		if feature == "buttons" {
			detail += fmt.Sprintf("; power=%t, volume up/down=%t/%t, lid/tablet switches=%t/%t", interfacesBit(in.key, 116), interfacesBit(in.key, 115), interfacesBit(in.key, 114), interfacesBit(in.sw, 0), interfacesBit(in.sw, 1))
		}
		return interfacesResult("input."+feature, "observed", detail+"; advertised capabilities only; no input events, physical actions or lifecycle tested")
	}
	return interfacesResult("input."+feature, "blocked", "Matching input capability metadata not exposed/readable; driver/accessory applicability unresolved, not hardware absence; no synthetic input generated")
}

func interfacesInputStartup(c *AutoContext) AutoResult {
	out, err := c.Command("systemctl", "show", "iptsd@*.service", "--property=LoadState,ActiveState,SubState,NRestarts", "--no-pager")
	if err != nil {
		return interfacesResult("input.startup", "blocked", "IPTSD startup service query unavailable (systemctl, bus or permission)")
	}
	active, failed, restarts := 0, 0, uint64(0)
	for _, line := range strings.Split(out, "\n") {
		if line == "ActiveState=active" {
			active++
		}
		if line == "ActiveState=failed" {
			failed++
		}
		if strings.HasPrefix(line, "NRestarts=") {
			if n, e := strconv.ParseUint(strings.TrimPrefix(line, "NRestarts="), 10, 64); e == nil {
				restarts += n
			}
		}
	}
	touch, pen := false, false
	for _, in := range interfacesInputs(c) {
		if in.virtual {
			touch = touch || interfacesInputMatches(in, "touch")
			pen = pen || interfacesInputMatches(in, "pen")
		}
	}
	detail := fmt.Sprintf("IPTSD active=%d, failed=%d, restarts=%d; virtual touch=%t, virtual pen=%t", active, failed, restarts, touch, pen)
	if failed > 0 {
		return interfacesResult("input.startup", "fail", detail+"; startup service reports failure")
	}
	if active == 0 || !touch || !pen {
		return interfacesResult("input.startup", "blocked", detail+"; active startup/virtual-device prerequisites missing; no service restarted")
	}
	return interfacesResult("input.startup", "observed", detail+"; readiness metadata only, not physical touch or repeat-boot reliability; restarts are reported, not concealed")
}

func interfacesInputAccessory(c *AutoContext) AutoResult {
	paths, _ := c.Glob("/sys/class/power_supply/*")
	count := 0
	for _, p := range paths {
		n := strings.ToLower(filepath.Base(p))
		if !strings.Contains(n, "pen") && !strings.Contains(n, "keyboard") {
			continue
		}
		if t, e := c.Read(p + "/type"); e == nil && t == "Battery" {
			count++
		}
	}
	if count == 0 {
		return interfacesResult("input.accessory", "blocked", "No attributable pen/keyboard battery-reporting path; identified accessory model/applicability and supported charging/wireless-button interface needed; no hardware absence inferred")
	}
	return interfacesResult("input.accessory", "observed", fmt.Sprintf("Attributable pen/keyboard battery interfaces=%d; reporting metadata only, not charging or wireless-button function; no battery test", count))
}

var interfacesLightChannel = regexp.MustCompile(`^in_(illuminance_(raw|input)|intensity_((x|y|z|ir)_)?(raw|input))$`)
var interfacesMotionChannel = regexp.MustCompile(`^in_(accel|anglvel|magn)_[xyz]_(raw|input)$`)

type interfacesSensor struct {
	path          string
	light, motion []string
	tcs           bool
}

func interfacesSensors(c *AutoContext) []interfacesSensor {
	paths, _ := c.Glob("/sys/bus/iio/devices/iio:device*")
	var sensors []interfacesSensor
	for _, p := range paths {
		name, e := c.Read(p + "/name")
		if e != nil {
			continue
		}
		lower := strings.ToLower(name)
		// PMIC ADCs are voltage/temperature channels, not motion/light sensors.
		if strings.Contains(lower, "adc") || strings.Contains(lower, "pmic") {
			continue
		}
		sensor := interfacesSensor{path: p, tcs: lower == "tcs3430"}
		channels, _ := c.Glob(p + "/in_*")
		for _, channel := range channels {
			base := filepath.Base(channel)
			if interfacesLightChannel.MatchString(base) {
				sensor.light = append(sensor.light, channel)
			}
			if interfacesMotionChannel.MatchString(base) {
				sensor.motion = append(sensor.motion, channel)
			}
		}
		if len(sensor.light)+len(sensor.motion) > 0 {
			sensors = append(sensors, sensor)
		}
	}
	return sensors
}

func interfacesSensorChannels(c *AutoContext) AutoResult {
	light, motion, tcs := 0, 0, 0
	for _, sensor := range interfacesSensors(c) {
		light += len(sensor.light)
		motion += len(sensor.motion)
		if sensor.tcs {
			tcs++
		}
	}
	detail := fmt.Sprintf("Allowlisted light channels=%d, motion channels=%d, TCS3430 interfaces=%d; PMIC ADCs excluded; TCS3430 XYZ/IR is not proximity or a verified lux conversion; SDSP motion may be outside IIO", light, motion, tcs)
	if light+motion == 0 {
		return interfacesResult("sensors.channels", "blocked", detail+"; channel/backend support unresolved, not fitted sensor absence")
	}
	return interfacesResult("sensors.channels", "observed", detail+"; advertised capability only, not stimulus, axes or calibration")
}

func interfacesSensorBackend(c *AutoContext) AutoResult {
	paths, _ := c.Glob("/dev/fastrpc-*")
	sdsp, cdsp := 0, 0
	for _, p := range paths {
		n := filepath.Base(p)
		if strings.Contains(n, "sdsp") {
			sdsp++
		}
		if strings.Contains(n, "cdsp") {
			cdsp++
		}
	}
	provider, e1 := interfacesService(c, "spx-sensors.service")
	proxy, e2 := interfacesService(c, "iio-sensor-proxy.service")
	providerState := interfacesEnum(provider["ActiveState"], "active", "inactive", "failed", "activating")
	proxyState := interfacesEnum(proxy["ActiveState"], "active", "inactive", "failed", "activating")
	cdspStatus, _ := c.Read("/sys/firmware/devicetree/base/soc@0/remoteproc@8300000/glink-edge/fastrpc/status")
	detail := fmt.Sprintf("SDSP FastRPC endpoints=%d, CDSP endpoints=%d; sensor provider=%s, proxy=%s", sdsp, cdsp, providerState, proxyState)
	if cdspStatus == "disabled" {
		detail += "; running DT disables CDSP FastRPC: compute transport intentionally parked, not missing silicon and not the SDSP sensor path"
	}
	if providerState == "failed" || proxyState == "failed" {
		return interfacesResult("sensors.backend", "fail", detail+"; service reports startup/backend failure; no automatic repair")
	}
	if e1 != nil || e2 != nil || sdsp == 0 || providerState != "active" || proxyState != "active" {
		return interfacesResult("sensors.backend", "blocked", detail+"; SDSP/service startup prerequisites unavailable; no DSP activation, reload or restart")
	}
	return interfacesResult("sensors.backend", "observed", detail+"; endpoint/service metadata only, not sensor delivery or CDSP workload")
}

// The helper owns a private system-bus connection through claim and release.
func interfacesSensorDesktopDelivery(c *AutoContext) AutoResult {
	const id = "sensors.desktop-motion"
	if c.Fixture || (c.Root != "" && filepath.Clean(c.Root) != "/") {
		return interfacesResult(id, "blocked", "Fixture root: SensorProxy helper disabled; compass not covered")
	}
	if c.Repo == "" {
		return interfacesResult(id, "blocked", "Repository helper path unavailable; compass not covered")
	}
	helper := filepath.Join(c.Repo, "tools/spx/hw-validation/sensorproxy_probe.py")
	if info, err := os.Stat(helper); err != nil || !info.Mode().IsRegular() {
		return interfacesResult(id, "blocked", "SensorProxy repository helper unavailable; compass not covered")
	}
	out, err := c.Command("python3", "-B", helper)
	if err != nil {
		var execErr *exec.Error
		if errors.As(err, &execErr) || errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission) {
			return interfacesResult(id, "blocked", "Python/helper unavailable or inaccessible; compass not covered")
		}
		return interfacesResult(id, "error", "SensorProxy helper command failed; raw output discarded; compass not covered")
	}
	var probe struct {
		Status         string  `json:"status"`
		Reason         string  `json:"reason"`
		HasCompass     *bool   `json:"has_compass"`
		Before         *string `json:"orientation_before"`
		After          *string `json:"orientation_after"`
		Signal         bool    `json:"signal"`
		Claimed        bool    `json:"claimed"`
		Released       bool    `json:"released"`
		WindowComplete bool    `json:"window_complete"`
	}
	if json.Unmarshal([]byte(out), &probe) != nil {
		return interfacesResult(id, "error", "Invalid SensorProxy helper JSON; raw output discarded; compass not covered")
	}
	compass := "unknown (not readable)"
	if probe.HasCompass != nil {
		compass = strconv.FormatBool(*probe.HasCompass)
	}
	suffix := "; HasCompass=" + compass + "; compass not covered: delivery not exercised (ClaimCompass normally restricted to geoclue)"
	undefined := func(value *string) bool { return value != nil && (*value == "" || *value == "undefined") }
	transition := undefined(probe.Before) && probe.After != nil && !undefined(probe.After)
	status, detail := "error", "Invalid SensorProxy helper outcome; raw output discarded"
	switch probe.Reason {
	case "signal":
		if probe.Status == "pass" && probe.Claimed && probe.Released && probe.Signal {
			status, detail = "pass", "Fresh PropertiesChanged carrying AccelerometerOrientation or AccelerometerTilt after ClaimAccelerometer; claim released on the same connection"
		}
	case "transition":
		if probe.Status == "pass" && probe.Claimed && probe.Released && transition {
			status, detail = "pass", "AccelerometerOrientation transitioned from undefined/empty before claim to defined after claim: fresh reading; claim released on the same connection"
		}
	case "stationary":
		if probe.Status == "blocked" && probe.Claimed && probe.Released && probe.WindowComplete && !probe.Signal && probe.Before != nil && !undefined(probe.Before) && !transition {
			status, detail = "blocked", "Device is stationary and the property was already defined before the claim so freshness cannot be distinguished; no accelerometer PropertiesChanged in 6 s; claim released"
		}
	case "undefined":
		if probe.Status == "fail" && probe.Claimed && probe.Released && probe.WindowComplete && !probe.Signal && undefined(probe.After) {
			status, detail = "fail", "Claim accepted, AccelerometerOrientation stayed undefined/empty for the whole 6 s window: proxy never obtained a reading from the driver; claim released"
		}
	case "no_service", "no_accelerometer", "claim_refused", "unavailable", "bus_unavailable":
		if probe.Status == "blocked" {
			status = "blocked"
			detail = map[string]string{
				"no_service":       "SensorProxy service not running; NameHasOwner false; no activation",
				"no_accelerometer": "SensorProxy HasAccelerometer false",
				"claim_refused":    "SensorProxy ClaimAccelerometer refused; release attempted on the same connection",
				"unavailable":      "SensorProxy helper or Python PyGObject (Gio/GLib) unavailable",
				"bus_unavailable":  "System bus connection unavailable; no activation",
			}[probe.Reason]
		}
	case "helper_error", "timeout", "release_error", "close_error":
		if probe.Status == "error" {
			detail = "SensorProxy helper error (" + probe.Reason + "); fresh delivery not established; raw output discarded"
		}
	}
	return interfacesResult(id, status, detail+suffix)
}

func interfacesSensorDesktopCompass(c *AutoContext) AutoResult {
	const id = "sensors.desktop-compass"
	if c.Fixture || (c.Root != "" && filepath.Clean(c.Root) != "/") {
		return interfacesResult(id, "blocked", "Fixture root: SensorProxy helper disabled")
	}
	if c.Repo == "" {
		return interfacesResult(id, "blocked", "Repository helper path unavailable")
	}
	helper := filepath.Join(c.Repo, "tools/spx/hw-validation/sensorproxy_probe.py")
	if info, err := os.Stat(helper); err != nil || !info.Mode().IsRegular() {
		return interfacesResult(id, "blocked", "SensorProxy repository helper unavailable")
	}
	out, err := c.Command("python3", "-B", helper, "--compass")
	if err != nil {
		var execErr *exec.Error
		if errors.As(err, &execErr) || errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission) {
			return interfacesResult(id, "blocked", "Python/helper unavailable or inaccessible")
		}
		return interfacesResult(id, "error", "SensorProxy compass helper command failed; raw output discarded")
	}
	var probe struct {
		Status         string   `json:"status"`
		Reason         string   `json:"reason"`
		HasCompass     *bool    `json:"has_compass"`
		Before         *float64 `json:"compass_before"`
		After          *float64 `json:"compass_after"`
		Signal         bool     `json:"signal"`
		SignalCount    int      `json:"compass_signal_count"`
		Min            *float64 `json:"compass_min"`
		Max            *float64 `json:"compass_max"`
		Claimed        bool     `json:"claimed"`
		Released       bool     `json:"released"`
		WindowComplete bool     `json:"window_complete"`
	}
	if json.Unmarshal([]byte(out), &probe) != nil {
		return interfacesResult(id, "error", "Invalid SensorProxy compass helper JSON; raw output discarded")
	}
	status, detail := "error", "Invalid SensorProxy compass helper outcome; raw output discarded"
	switch probe.Reason {
	case "signal":
		if probe.Status == "pass" && probe.Claimed && probe.Released && probe.Signal && probe.SignalCount > 0 && compassHeading(probe.Min) && compassHeading(probe.Max) && *probe.Min <= *probe.Max {
			status = "pass"
			detail = fmt.Sprintf("Fresh desktop compass delivery: PropertiesChanged headings=%d, min/max=%.1f/%.1f degrees; before=%s after=%s; proves fresh desktop compass delivery only, not calibration, true-north accuracy or tilt compensation; claim released", probe.SignalCount, *probe.Min, *probe.Max, compassValue(probe.Before), compassValue(probe.After))
		}
	case "no_service", "no_compass", "access_denied", "claim_refused", "unavailable", "bus_unavailable":
		if probe.Status == "blocked" {
			status = "blocked"
			detail = map[string]string{
				"no_service":      "SensorProxy service not running; NameHasOwner false; no activation",
				"no_compass":      "SensorProxy HasCompass false",
				"access_denied":   "SensorProxy ClaimCompass refused by access policy (AccessDenied); release attempted on the same connection",
				"claim_refused":   "SensorProxy ClaimCompass refused; release attempted on the same connection",
				"unavailable":     "SensorProxy helper or Python PyGObject (Gio/GLib) unavailable",
				"bus_unavailable": "System bus connection unavailable; no activation",
			}[probe.Reason]
		}
	case "no_heading":
		if probe.Status == "fail" && probe.Claimed && probe.Released && probe.WindowComplete && !probe.Signal && (probe.Before == nil || probe.After == nil || !compassFinite(probe.Before) || !compassFinite(probe.After) || *probe.Before == *probe.After) {
			status = "fail"
			detail = fmt.Sprintf("Claim accepted, no finite CompassHeading PropertiesChanged and heading stayed at its pre-claim value or non-finite for the full 6 s window; before=%s after=%s; claim released", compassValue(probe.Before), compassValue(probe.After))
		}
	case "helper_error", "timeout", "release_error", "close_error":
		if probe.Status == "error" {
			detail = "SensorProxy compass helper error (" + probe.Reason + "); fresh delivery not established; raw output discarded"
		}
	}
	return interfacesResult(id, status, detail)
}

func compassValue(value *float64) string {
	if !compassFinite(value) {
		return "non-finite/unavailable"
	}
	return fmt.Sprintf("%.1f°", *value)
}

func compassFinite(value *float64) bool {
	return value != nil && !math.IsNaN(*value) && !math.IsInf(*value, 0)
}

func compassHeading(value *float64) bool {
	return compassFinite(value) && *value >= 0 && *value < 360
}

func interfacesSensorDesktop(c *AutoContext) AutoResult {
	state, err := interfacesService(c, "iio-sensor-proxy.service")
	if err != nil || state["ActiveState"] != "active" {
		return interfacesResult("sensors.desktop", "blocked", "SensorProxy is not already active/readable; no D-Bus auto-start or policy bypass")
	}
	properties := []struct{ iface, capability, value string }{
		{"net.hadess.SensorProxy", "HasAmbientLight", "LightLevel"},
		{"net.hadess.SensorProxy", "HasAccelerometer", ""},
		{"net.hadess.SensorProxy.Compass", "HasCompass", "CompassHeading"},
	}
	advertised, numeric := 0, 0
	for _, property := range properties {
		out, err := c.Command("busctl", "--system", "--auto-start=no", "--timeout=3s", "get-property", "net.hadess.SensorProxy", "/net/hadess/SensorProxy", property.iface, property.capability)
		if err != nil {
			continue
		}
		if strings.TrimSpace(out) != "b true" {
			continue
		}
		advertised++
		if property.value == "" {
			continue
		}
		out, err = c.Command("busctl", "--system", "--auto-start=no", "--timeout=3s", "get-property", "net.hadess.SensorProxy", "/net/hadess/SensorProxy", property.iface, property.value)
		if err != nil {
			continue
		}
		fields := strings.Fields(out)
		if len(fields) == 2 && fields[0] == "d" {
			if v, e := strconv.ParseFloat(fields[1], 64); e == nil && !math.IsNaN(v) && !math.IsInf(v, 0) {
				numeric++
			}
		}
	}
	if advertised == 0 {
		return interfacesResult("sensors.desktop", "blocked", "Already-running SensorProxy exposes no readable advertised sensor capabilities; tool/bus/backend prerequisites unresolved")
	}
	return interfacesResult("sensors.desktop", "observed", fmt.Sprintf("Already-running SensorProxy advertised capability groups=%d, finite cached numeric properties=%d; read-only, no Claim/stream/start; cached values may be stale, not fresh delivery, axes/calibration or brightness response", advertised, numeric))
}

func interfacesBoundedSensorRead(c *AutoContext, path string) (string, error) {
	if c.Root != "" && filepath.Clean(c.Root) != "/" {
		return c.Read(path)
	}
	// The known driver's live raw read runs in a process so a stuck backend
	// cannot block the validator's own sysfs reader indefinitely.
	return c.Command("timeout", "--signal=TERM", "--kill-after=1s", "3s", "cat", path)
}

func interfacesSensorRead(c *AutoContext, group string) AutoResult {
	if group == "motion" {
		return automaticSSCMotion(c)
	}
	id := "sensors." + group + "-read"
	count, zero := 0, 0
	for _, sensor := range interfacesSensors(c) {
		if !sensor.tcs {
			continue
		}
		channels := sensor.light
		for _, path := range channels {
			text, err := interfacesBoundedSensorRead(c, path)
			if err != nil {
				return interfacesSensorReadProblem(id, text, err)
			}
			value, err := strconv.ParseFloat(strings.TrimSpace(text), 64)
			if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || math.Abs(value) > 1e12 {
				return interfacesResult(id, "fail", "Exposed sensor channel returned non-finite/invalid numeric data; no axes/stimulus verdict")
			}
			count++
			if value == 0 {
				zero++
			}
		}
	}
	if count == 0 {
		return interfacesResult(id, "blocked", "No permitted "+group+" sample path: safe raw reads are restricted to known TCS3430 light channels; SDSP motion needs a supported fresh service-delivery sample, not arbitrary IIO or PMIC ADC substitutes; cached properties are not delivery")
	}
	return interfacesResult(id, "pass", fmt.Sprintf("One-shot finite %s-channel reads=%d, zero-valued=%d; raw values discarded; zero is not a light/stimulus failure; no scale/lux, physical axes, calibration, rotation, proximity or lifecycle claim", group, count, zero))
}

func interfacesSensorReadProblem(id, output string, err error) AutoResult {
	text := strings.ToLower(output + " " + err.Error())
	if errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission) || errors.Is(err, exec.ErrNotFound) ||
		strings.Contains(text, "no such file") || strings.Contains(text, "permission denied") || strings.Contains(text, "not permitted") || strings.Contains(text, "fixture root") {
		return interfacesResult(id, "blocked", "Allowlisted light read lacks tool, channel or permission; no stream enabled")
	}
	for _, signature := range []string{"input/output error", "timed out", "deadline exceeded", "exit status 124", "command limit"} {
		if strings.Contains(text, signature) {
			return interfacesResult(id, "fail", "Exposed allowlisted light channel reported I/O failure or timed out; no raw values/logs retained")
		}
	}
	return interfacesResult(id, "error", "Allowlisted light-channel runner failed unexpectedly; no raw values/logs retained")
}
