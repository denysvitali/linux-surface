package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

func automaticNetworkChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "net.wifi.interfaces", Title: "Wi-Fi interfaces and current carrier", Area: "Network", Kind: "inventory", Boxes: []string{"N01"}, Run: automaticNetworkInterfaces},
		{ID: "net.wifi.link", Title: "Current Wi-Fi association evidence", Area: "Network", Kind: "inventory", Boxes: []string{"N01"}, Run: automaticNetworkLink},
		{ID: "net.wifi.scan", Title: "Bounded Wi-Fi scan completes", Area: "Network", Kind: "functional", Boxes: []string{"N01"}, Run: automaticNetworkScan},
		{ID: "net.ip.families", Title: "Wi-Fi address and default-route families", Area: "Network", Kind: "inventory", Boxes: []string{"N01"}, Run: automaticNetworkIP},
		{ID: "net.dns.config", Title: "Configured DNS resolver families", Area: "Network", Kind: "inventory", Boxes: []string{"N01"}, Run: automaticNetworkDNS},
		{ID: "net.dns.lookup", Title: "Bounded DNS lookup of a deliberate public fixture", Area: "Network", Kind: "functional", Boxes: []string{"N01"}, Run: automaticNetworkDNSLookup},
		{ID: "net.wifi.gateway4", Title: "Local IPv4 gateway replies over Wi-Fi", Area: "Network", Kind: "functional", Boxes: []string{"N01"}, Run: func(c *AutoContext) AutoResult { return automaticNetworkGateway(c, 4) }},
		{ID: "net.wifi.gateway6", Title: "Local IPv6 gateway replies over Wi-Fi", Area: "Network", Kind: "functional", Boxes: []string{"N01"}, Run: func(c *AutoContext) AutoResult { return automaticNetworkGateway(c, 6) }},
	}
}

func automaticNetworkResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}

// Command diagnostics can contain addresses and SSIDs, including on failure.
func automaticNetworkCommandProblem(id, operation, output string, err error) AutoResult {
	text := strings.ToLower(output)
	if err != nil {
		text += " " + strings.ToLower(err.Error())
	}
	status, reason := "error", "command failed without a recognized cause"
	switch {
	case strings.Contains(text, "executable file not found"), strings.Contains(text, "command not found"), strings.Contains(text, "no such file or directory"), strings.Contains(text, "no such device"):
		status, reason = "blocked", "required tool or interface is unavailable"
	case strings.Contains(text, "permission"), strings.Contains(text, "not permitted"), strings.Contains(text, "access denied"), strings.Contains(text, "accessdenied"), strings.Contains(text, "not authorized"), strings.Contains(text, "not authorised"):
		status, reason = "blocked", "permission or authorization is unavailable"
	case strings.Contains(text, "serviceunknown"), strings.Contains(text, "namehasnoowner"), strings.Contains(text, "not running"), strings.Contains(text, "failed to connect to bus"):
		status, reason = "blocked", "required service or system bus is unavailable"
	case strings.Contains(text, "rfkill"), strings.Contains(text, "disabled"), strings.Contains(text, "radio is off"):
		status, reason = "blocked", "radio is disabled or blocked; it was not toggled"
	case strings.Contains(text, "not supported"), strings.Contains(text, "unknownproperty"), strings.Contains(text, "unknownmethod"), strings.Contains(text, "unknowninterface"), strings.Contains(text, "unknown property"), strings.Contains(text, "unknown method"), strings.Contains(text, "unknown interface"):
		status, reason = "blocked", "required operation or completion evidence is unsupported"
	case strings.Contains(text, "busy"), strings.Contains(text, "in progress"), strings.Contains(text, "temporarily unavailable"), strings.Contains(text, "not allowed immediately"):
		status, reason = "blocked", "owner is busy or scan rate-limited; no retry or link change"
	case strings.Contains(text, "timed out"), strings.Contains(text, "timeout"), strings.Contains(text, "deadline exceeded"), strings.Contains(text, "command limit"), strings.Contains(text, "exit status 124"):
		status, reason = "blocked", "bounded command did not return completion evidence"
	case strings.Contains(text, "network is unreachable"), strings.Contains(text, "no route to host"):
		status, reason = "blocked", "configured route is not currently usable"
	case strings.Contains(text, "input/output error"), strings.Contains(text, "firmware crash"):
		status, reason = "fail", "driver reported an I/O or firmware malfunction"
	}
	return automaticNetworkResult(id, status, operation+": "+reason)
}

func automaticNetworkWiFi(c *AutoContext) ([]string, error) {
	paths, err := c.Glob("/sys/class/net/*")
	if err != nil {
		return nil, err
	}
	var result []string
	for _, path := range paths {
		wireless, _ := c.Glob(path + "/wireless")
		phy, _ := c.Glob(path + "/phy80211")
		if len(wireless)+len(phy) > 0 {
			result = append(result, filepath.Base(path))
		}
	}
	return result, nil
}

func automaticNetworkFirstWiFi(c *AutoContext, id string) (string, *AutoResult) {
	interfaces, err := automaticNetworkWiFi(c)
	if err != nil || len(interfaces) == 0 {
		r := automaticNetworkResult(id, "blocked", "Wi-Fi sysfs interface unavailable; missing support or access is not hardware absence")
		return "", &r
	}
	// Prefer the existing carrier without creating or replacing a connection.
	for _, name := range interfaces {
		carrier, e := c.Read("/sys/class/net/" + name + "/carrier")
		if e == nil && carrier == "1" {
			return name, nil
		}
	}
	return interfaces[0], nil
}

func automaticNetworkInterfaces(c *AutoContext) AutoResult {
	const id = "net.wifi.interfaces"
	interfaces, err := automaticNetworkWiFi(c)
	if err != nil || len(interfaces) == 0 {
		return automaticNetworkResult(id, "blocked", "Wi-Fi sysfs interface unavailable; missing support or access is not hardware absence")
	}
	up, carrier, unknown := 0, 0, 0
	for _, name := range interfaces {
		state, e1 := c.Read("/sys/class/net/" + name + "/operstate")
		value, e2 := c.Read("/sys/class/net/" + name + "/carrier")
		if e1 != nil || e2 != nil {
			unknown++
		}
		if state == "up" {
			up++
		}
		if value == "1" {
			carrier++
		}
	}
	status := "observed"
	if unknown > 0 {
		status = "blocked"
	}
	return automaticNetworkResult(id, status, fmt.Sprintf("wireless interfaces=%d; up=%d; carrier=%d; unreadable state=%d; enumeration is not working data", len(interfaces), up, carrier, unknown))
}

var automaticNetworkFrequency = regexp.MustCompile(`(?m)^\s*freq:\s*([0-9]+)\s*$`)

func automaticNetworkLink(c *AutoContext) AutoResult {
	const id = "net.wifi.link"
	name, blocked := automaticNetworkFirstWiFi(c, id)
	if blocked != nil {
		return *blocked
	}
	output, err := c.Command("iw", "dev", name, "link")
	if err != nil {
		return automaticNetworkCommandProblem(id, "Wi-Fi link query", output, err)
	}
	if strings.Contains(output, "Not connected.") {
		return automaticNetworkResult(id, "observed", "primary wireless interface is not associated; no connection was attempted")
	}
	if !strings.HasPrefix(strings.TrimSpace(output), "Connected to ") {
		return automaticNetworkResult(id, "error", "Wi-Fi link query returned no recognized association state")
	}
	detail := "primary wireless interface associated"
	if m := automaticNetworkFrequency.FindStringSubmatch(output); m != nil {
		frequency, _ := strconv.Atoi(m[1])
		if frequency >= 2000 && frequency <= 7200 {
			detail += fmt.Sprintf("; frequency=%d MHz", frequency)
		}
	}
	return automaticNetworkResult(id, "observed", detail+"; association alone does not verify DNS or data")
}

func automaticNetworkBus(c *AutoContext, args ...string) (string, error) {
	return c.Command(append([]string{"busctl", "--system", "--timeout=1s"}, args...)...)
}

func automaticNetworkOwner(c *AutoContext, service string) (bool, error) {
	output, err := automaticNetworkBus(c, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", service)
	if err != nil {
		// Keep private diagnostics internal; callers emit only fixed summaries.
		return false, fmt.Errorf("%s: %w", output, err)
	}
	switch strings.TrimSpace(output) {
	case "b true":
		return true, nil
	case "b false":
		return false, nil
	default:
		return false, fmt.Errorf("unrecognized system bus ownership response")
	}
}

func automaticNetworkInt(output, signature string) (int64, error) {
	fields := strings.Fields(output)
	if len(fields) != 2 || fields[0] != signature {
		return 0, fmt.Errorf("unrecognized numeric property")
	}
	return strconv.ParseInt(fields[1], 10, 64)
}

func automaticNetworkCount(output, signature string) (int, error) {
	fields := strings.Fields(output)
	if len(fields) < 2 || fields[0] != signature {
		return 0, fmt.Errorf("unrecognized array response")
	}
	count, err := strconv.Atoi(fields[1])
	if err != nil || count < 0 {
		return 0, fmt.Errorf("unrecognized array size")
	}
	width := 1
	if signature == "a(on)" {
		width = 2
	}
	if len(fields) != 2+count*width {
		return 0, fmt.Errorf("incomplete array response")
	}
	return count, nil
}

// LastScan means a finished scan, not a rescan request or cached AP list.
func automaticNetworkNMScan(c *AutoContext, name, path string) AutoResult {
	const id = "net.wifi.scan"
	property := func() (string, error) {
		return automaticNetworkBus(c, "get-property", "org.freedesktop.NetworkManager", path, "org.freedesktop.NetworkManager.Device.Wireless", "LastScan")
	}
	output, err := property()
	if err != nil {
		return automaticNetworkCommandProblem(id, "NetworkManager scan-completion query", output, err)
	}
	before, err := automaticNetworkInt(output, "x")
	if err != nil {
		return automaticNetworkResult(id, "error", "NetworkManager LastScan response was not recognized")
	}
	output, err = c.Command("nmcli", "--wait", "5", "device", "wifi", "rescan", "ifname", name)
	if err != nil {
		return automaticNetworkCommandProblem(id, "NetworkManager rescan", output, err)
	}
	deadline := time.Now().Add(8 * time.Second)
	for time.Now().Before(deadline) {
		output, err = property()
		if err != nil {
			return automaticNetworkCommandProblem(id, "NetworkManager scan-completion query", output, err)
		}
		after, e := automaticNetworkInt(output, "x")
		if e != nil {
			return automaticNetworkResult(id, "error", "NetworkManager LastScan response was not recognized")
		}
		if after >= 0 && after > before {
			output, err = automaticNetworkBus(c, "get-property", "org.freedesktop.NetworkManager", path, "org.freedesktop.NetworkManager.Device.Wireless", "AccessPoints")
			if err != nil {
				return automaticNetworkCommandProblem(id, "NetworkManager scan count", output, err)
			}
			count, e := automaticNetworkCount(output, "ao")
			if e != nil {
				return automaticNetworkResult(id, "error", "NetworkManager scan completed but AP count response was not recognized")
			}
			return automaticNetworkResult(id, "pass", fmt.Sprintf("NetworkManager completed a scan (LastScan advanced); available AP entries=%d; current connection was not changed", count))
		}
		time.Sleep(100 * time.Millisecond)
	}
	return automaticNetworkResult(id, "blocked", "NetworkManager accepted rescan but no finished scan was observed within 8s; cached AP entries are not a pass")
}

var automaticNetworkIWDStation = regexp.MustCompile(`^/net/connman/iwd/(?:phy)?[0-9]+/[0-9]+$`)

func automaticNetworkIWDScan(c *AutoContext, name string) AutoResult {
	const id = "net.wifi.scan"
	output, err := automaticNetworkBus(c, "tree", "--list", "net.connman.iwd")
	if err != nil {
		return automaticNetworkCommandProblem(id, "iwd station query", output, err)
	}
	path := ""
	stations := 0
	for _, candidate := range strings.Fields(output) {
		if !automaticNetworkIWDStation.MatchString(candidate) {
			continue
		}
		stations++
		if stations > 16 {
			return automaticNetworkResult(id, "blocked", "iwd exposes more than 16 station candidates; bounded owner query stopped")
		}
		value, e := automaticNetworkBus(c, "get-property", "net.connman.iwd", candidate, "net.connman.iwd.Device", "Name")
		if e == nil && strings.TrimSpace(value) == "s "+strconv.Quote(name) {
			path = candidate
			break
		}
	}
	if path == "" {
		return automaticNetworkResult(id, "blocked", "iwd is active but a matching station interface was not exposed")
	}
	property := func() (string, error) {
		return automaticNetworkBus(c, "get-property", "net.connman.iwd", path, "net.connman.iwd.Station", "Scanning")
	}
	output, err = property()
	if err != nil {
		return automaticNetworkCommandProblem(id, "iwd scan-completion query", output, err)
	}
	if strings.TrimSpace(output) != "b false" {
		return automaticNetworkResult(id, "blocked", "iwd has an existing scan or unrecognized scanning state; no competing scan was requested")
	}
	output, err = automaticNetworkBus(c, "call", "net.connman.iwd", path, "net.connman.iwd.Station", "Scan")
	if err != nil {
		return automaticNetworkCommandProblem(id, "iwd scan", output, err)
	}
	started := false
	deadline := time.Now().Add(8 * time.Second)
	for time.Now().Before(deadline) {
		output, err = property()
		if err != nil {
			return automaticNetworkCommandProblem(id, "iwd scan-completion query", output, err)
		}
		switch strings.TrimSpace(output) {
		case "b true":
			started = true
		case "b false":
			if started {
				output, err = automaticNetworkBus(c, "call", "net.connman.iwd", path, "net.connman.iwd.Station", "GetOrderedNetworks")
				if err != nil {
					return automaticNetworkCommandProblem(id, "iwd scan count", output, err)
				}
				count, e := automaticNetworkCount(output, "a(on)")
				if e != nil {
					return automaticNetworkResult(id, "error", "iwd scan completed but network count response was not recognized")
				}
				return automaticNetworkResult(id, "pass", fmt.Sprintf("iwd scan completed (Scanning true to false); available network entries=%d; current connection was not changed", count))
			}
		default:
			return automaticNetworkResult(id, "error", "iwd scanning state was not recognized")
		}
		time.Sleep(100 * time.Millisecond)
	}
	return automaticNetworkResult(id, "blocked", "iwd accepted scan but no Scanning true-to-false completion was observed within 8s; cached entries are not a pass")
}

func automaticNetworkScan(c *AutoContext) AutoResult {
	const id = "net.wifi.scan"
	name, blocked := automaticNetworkFirstWiFi(c, id)
	if blocked != nil {
		return *blocked
	}
	nm, err := automaticNetworkOwner(c, "org.freedesktop.NetworkManager")
	if err != nil {
		return automaticNetworkCommandProblem(id, "Wi-Fi owner query", "", err)
	}
	if nm {
		output, e := automaticNetworkBus(c, "call", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "GetDeviceByIpIface", "s", name)
		if e == nil {
			fields := strings.Fields(output)
			if len(fields) != 2 || fields[0] != "o" {
				return automaticNetworkResult(id, "error", "NetworkManager device path response was not recognized")
			}
			path, e := strconv.Unquote(fields[1])
			if e != nil || !strings.HasPrefix(path, "/org/freedesktop/NetworkManager/Devices/") {
				return automaticNetworkResult(id, "error", "NetworkManager device path was not recognized")
			}
			output, e = automaticNetworkBus(c, "get-property", "org.freedesktop.NetworkManager", path, "org.freedesktop.NetworkManager.Device", "Managed")
			if e != nil {
				return automaticNetworkCommandProblem(id, "Wi-Fi owner query", output, e)
			}
			if strings.TrimSpace(output) == "b true" {
				return automaticNetworkNMScan(c, name, path)
			}
			if strings.TrimSpace(output) != "b false" {
				return automaticNetworkResult(id, "error", "NetworkManager managed state was not recognized")
			}
		} else {
			return automaticNetworkCommandProblem(id, "NetworkManager device query", output, e)
		}
	}
	iwd, err := automaticNetworkOwner(c, "net.connman.iwd")
	if err != nil {
		return automaticNetworkCommandProblem(id, "Wi-Fi owner query", "", err)
	}
	if iwd {
		return automaticNetworkIWDScan(c, name)
	}
	wpa, err := automaticNetworkOwner(c, "fi.w1.wpa_supplicant1")
	if err != nil {
		return automaticNetworkCommandProblem(id, "Wi-Fi owner query", "", err)
	}
	if wpa {
		return automaticNetworkResult(id, "blocked", "standalone wpa_supplicant owns Wi-Fi; a supported owner-mediated scan completion path is unavailable")
	}
	// Supplicants may run without owning a D-Bus name. Do not scan around them.
	processes, err := c.Glob("/proc/[0-9]*")
	if err != nil || len(processes) == 0 {
		return automaticNetworkResult(id, "blocked", "process ownership cannot be checked; no direct driver scan was requested")
	}
	for _, process := range processes {
		comm, e := c.Read(process + "/comm")
		if e != nil {
			return automaticNetworkResult(id, "blocked", "process ownership is unreadable; no direct driver scan was requested")
		}
		if comm == "wpa_supplicant" || comm == "iwd" || comm == "NetworkManager" {
			return automaticNetworkResult(id, "blocked", "a Wi-Fi manager is running without an applicable owner-mediated scan path")
		}
	}
	output, err := c.Command("timeout", "12s", "iw", "dev", name, "scan")
	if err != nil {
		return automaticNetworkCommandProblem(id, "unmanaged driver scan", output, err)
	}
	count := 0
	for _, line := range strings.Split(output, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "BSS ") {
			count++
		}
	}
	if strings.TrimSpace(output) != "" && count == 0 {
		return automaticNetworkResult(id, "error", "driver scan returned unrecognized output; no completed empty scan can be established")
	}
	return automaticNetworkResult(id, "pass", fmt.Sprintf("unmanaged iw scan completed; BSS entries=%d; no radio or connection changes", count))
}

type automaticNetworkRoute struct {
	Gateway string `json:"gateway"`
	Type    string `json:"type"`
}

func automaticNetworkRoutes(c *AutoContext, name string, family int) ([]automaticNetworkRoute, string, error) {
	output, err := c.Command("ip", "-j", fmt.Sprintf("-%d", family), "route", "show", "default", "dev", name)
	if err != nil {
		return nil, output, err
	}
	var routes []automaticNetworkRoute
	err = json.Unmarshal([]byte(output), &routes)
	if err == nil && strings.TrimSpace(output) == "null" {
		err = fmt.Errorf("route query returned no array")
	}
	return routes, "", err
}

func automaticNetworkIP(c *AutoContext) AutoResult {
	const id = "net.ip.families"
	name, blocked := automaticNetworkFirstWiFi(c, id)
	if blocked != nil {
		return *blocked
	}
	output, err := c.Command("ip", "-j", "address", "show", "dev", name)
	if err != nil {
		return automaticNetworkCommandProblem(id, "Wi-Fi address query", output, err)
	}
	var devices []struct {
		Addresses []struct {
			Family    string `json:"family"`
			Local     string `json:"local"`
			Scope     string `json:"scope"`
			Tentative bool   `json:"tentative"`
			DADFailed bool   `json:"dadfailed"`
		} `json:"addr_info"`
	}
	if json.Unmarshal([]byte(output), &devices) != nil || strings.TrimSpace(output) == "null" {
		return automaticNetworkResult(id, "error", "IP address query returned unrecognized JSON")
	}
	if len(devices) == 0 {
		return automaticNetworkResult(id, "blocked", "Wi-Fi interface no longer appears in the IP address query")
	}
	ipv4, ipv6, link6, unusable := 0, 0, 0, 0
	for _, device := range devices {
		for _, address := range device.Addresses {
			ip := net.ParseIP(address.Local)
			if ip == nil {
				return automaticNetworkResult(id, "error", "IP address query contained an invalid address")
			}
			if address.Tentative || address.DADFailed {
				unusable++
			} else if address.Family == "inet" && address.Scope == "global" {
				ipv4++
			} else if address.Family == "inet6" && address.Scope == "global" {
				ipv6++
			} else if address.Family == "inet6" && ip.IsLinkLocalUnicast() {
				link6++
			}
		}
	}
	counts := [2]int{}
	for i, family := range []int{4, 6} {
		routes, out, e := automaticNetworkRoutes(c, name, family)
		if e != nil {
			return automaticNetworkCommandProblem(id, "Wi-Fi route-family query", out, e)
		}
		for _, route := range routes {
			if route.Type == "" || route.Type == "unicast" {
				counts[i]++
			}
		}
	}
	return automaticNetworkResult(id, "observed", fmt.Sprintf("primary Wi-Fi addresses: IPv4 global=%d, IPv6 global=%d, IPv6 link-local=%d, tentative/DAD-failed=%d; default routes: IPv4=%d, IPv6=%d; configured families are not working WAN data", ipv4, ipv6, link6, unusable, counts[0], counts[1]))
}

func automaticNetworkDNS(c *AutoContext) AutoResult {
	const id = "net.dns.config"
	text, err := c.Read("/etc/resolv.conf")
	if err != nil {
		return automaticNetworkResult(id, "blocked", "resolver configuration is unreadable; no DNS request was sent")
	}
	ipv4, ipv6, stub := 0, 0, 0
	for _, line := range strings.Split(text, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 || fields[0] != "nameserver" {
			continue
		}
		ip := net.ParseIP(strings.SplitN(fields[1], "%", 2)[0])
		if ip == nil {
			return automaticNetworkResult(id, "error", "resolver configuration contains an unrecognized nameserver address")
		}
		if ip.To4() != nil {
			ipv4++
		} else {
			ipv6++
		}
		if ip.IsLoopback() {
			stub++
		}
	}
	if ipv4+ipv6 == 0 {
		return automaticNetworkResult(id, "blocked", "no nameserver is configured in resolv.conf; NSS or per-link resolver support is not established")
	}
	return automaticNetworkResult(id, "observed", fmt.Sprintf("configured resolver entries: IPv4=%d, IPv6=%d, loopback stubs=%d; configuration inventory only; see net.dns.lookup for functional evidence; this inventory sends no query", ipv4, ipv6, stub))
}

// Read both kernel route tables without invoking a potentially slow command.
func automaticNetworkDefaultRoute(c *AutoContext) bool {
	v4, _ := c.Read("/proc/net/route")
	for _, line := range strings.Split(v4, "\n") {
		f := strings.Fields(line)
		if len(f) < 8 || f[1] != "00000000" || f[7] != "00000000" {
			continue
		}
		flags, err := strconv.ParseUint(f[3], 16, 32)
		if err == nil && flags&1 != 0 && flags&0x200 == 0 {
			return true
		}
	}
	v6, _ := c.Read("/proc/net/ipv6_route")
	for _, line := range strings.Split(v6, "\n") {
		f := strings.Fields(line)
		if len(f) != 10 || f[0] != strings.Repeat("0", 32) || f[1] != "00" {
			continue
		}
		flags, err := strconv.ParseUint(f[8], 16, 32)
		if err == nil && flags&1 != 0 && flags&0x200 == 0 {
			return true
		}
	}
	return false
}

var automaticNetworkDNSLabel = regexp.MustCompile(`^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$`)

func automaticNetworkDNSLookup(c *AutoContext) AutoResult {
	const id = "net.dns.lookup"
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	name := c.Options.DNSName
	if name == "" {
		name = "example.com"
	}
	// Require a hostname, never an IP literal, URL, or single-label search name.
	valid := len(name) <= 253 && strings.Contains(strings.TrimSuffix(name, "."), ".") && net.ParseIP(strings.TrimSuffix(name, ".")) == nil
	for _, label := range strings.Split(strings.TrimSuffix(name, "."), ".") {
		if len(label) == 0 || len(label) > 63 || !automaticNetworkDNSLabel.MatchString(label) {
			valid = false
		}
	}
	if !valid {
		return automaticNetworkResult(id, "blocked", "DNS fixture must be a public multi-label hostname")
	}
	detail := "DNS fixture=" + name + "; "
	if c.Options.NoDNSLookup {
		return automaticNetworkResult(id, "blocked", detail+"lookups disabled by --no-dns-lookup")
	}
	if c.Fixture || (c.LookupIP == nil && c.Root != "" && filepath.Clean(c.Root) != "/") {
		return automaticNetworkResult(id, "blocked", detail+"external lookups disabled for fixture-root runs")
	}
	if config := automaticNetworkDNS(c); config.Status != "observed" {
		return automaticNetworkResult(id, "blocked", detail+"no usable resolver configured; "+config.Detail)
	}
	if !automaticNetworkDefaultRoute(c) {
		return automaticNetworkResult(id, "blocked", detail+"no usable default route exposed; no lookup attempted")
	}
	lookup := c.LookupIP
	if lookup == nil {
		lookup = net.DefaultResolver.LookupIP
	}
	// A trailing dot prevents private search domains from changing the fixture.
	addresses, err := lookup(ctx, "ip", strings.TrimSuffix(name, ".")+".")
	v4, v6 := 0, 0
	for _, ip := range addresses {
		if ip.To4() != nil {
			v4++
		} else if ip.To16() != nil {
			v6++
		}
	}
	if v4+v6 > 0 {
		return automaticNetworkResult(id, "pass", detail+fmt.Sprintf("system resolver answers: A=%d AAAA=%d; total deadline 3s; no network state changed", v4, v6))
	}
	reason := "no A or AAAA answers"
	if ctx.Err() != nil {
		reason = "lookup timed out"
	} else if err != nil {
		reason = "system resolver lookup failed (including NXDOMAIN or timeout)"
	}
	return automaticNetworkResult(id, "fail", detail+reason+" with resolver configured and default route present; addresses and raw errors omitted")
}

var automaticNetworkPingCounts = regexp.MustCompile(`([0-9]+) packets transmitted,\s*([0-9]+)(?: packets)? received`)

func automaticNetworkGateway(c *AutoContext, family int) AutoResult {
	id := fmt.Sprintf("net.wifi.gateway%d", family)
	name, blocked := automaticNetworkFirstWiFi(c, id)
	if blocked != nil {
		return *blocked
	}
	routes, output, err := automaticNetworkRoutes(c, name, family)
	if err != nil {
		return automaticNetworkCommandProblem(id, "local gateway route query", output, err)
	}
	gateway := ""
	for _, route := range routes {
		ip := net.ParseIP(route.Gateway)
		if ip == nil || (family == 4) != (ip.To4() != nil) || !(route.Type == "" || route.Type == "unicast") {
			continue
		}
		if (ip.IsPrivate() || ip.IsLinkLocalUnicast()) && !ip.IsLoopback() && !ip.IsMulticast() && !ip.IsUnspecified() {
			gateway = route.Gateway
			break
		}
	}
	if gateway == "" {
		return automaticNetworkResult(id, "blocked", fmt.Sprintf("no configured private/link-local IPv%d gateway fixture; no external destination was contacted", family))
	}
	output, err = c.Command("ping", "-n", fmt.Sprintf("-%d", family), "-c", "3", "-W", "1", "-w", "5", "-s", "8", "-I", name, gateway)
	match := automaticNetworkPingCounts.FindStringSubmatch(output)
	if match == nil {
		if err != nil {
			return automaticNetworkCommandProblem(id, "local gateway echo", output, err)
		}
		return automaticNetworkResult(id, "error", "local gateway echo returned no recognized packet summary")
	}
	sent, _ := strconv.Atoi(match[1])
	received, _ := strconv.Atoi(match[2])
	if received == 0 {
		return automaticNetworkResult(id, "blocked", fmt.Sprintf("local IPv%d gateway echo replies=0/%d; gateway availability or ICMP policy prevents a data-path conclusion", family, sent))
	}
	if err == nil && sent == 3 && received == 3 {
		return automaticNetworkResult(id, "pass", fmt.Sprintf("local IPv%d gateway echo replies=3/3 over primary Wi-Fi; 8-byte payloads; not WAN, DNS or sustained transfer acceptance", family))
	}
	return automaticNetworkResult(id, "fail", fmt.Sprintf("local IPv%d gateway echo replies=%d/%d, expected 3/3; bounded local path lost responses, not isolated to Wi-Fi hardware", family, received, sent))
}
