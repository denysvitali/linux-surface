package main

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func automaticNetworkFixture(t *testing.T) *AutoContext {
	t.Helper()
	root := t.TempDir()
	for _, dir := range []string{"sys/class/net/wlan0/wireless", "proc/1", "etc"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
			t.Fatal(err)
		}
	}
	for path, value := range map[string]string{
		"sys/class/net/wlan0/operstate": "up\n",
		"sys/class/net/wlan0/carrier":   "1\n",
		"proc/1/comm":                   "init\n",
		"etc/resolv.conf":               "nameserver 127.0.0.53\nnameserver fd00::53\nsearch private.example\n",
	} {
		if err := os.WriteFile(filepath.Join(root, path), []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return &AutoContext{Root: root, Run: func(args ...string) (string, error) {
		t.Fatalf("unexpected command: %v", args)
		return "", errors.New("unexpected command")
	}}
}

func automaticNetworkAssertPrivate(t *testing.T, result AutoResult) {
	t.Helper()
	for _, private := range []string{"00:11:22:33:44:55", "my-private-ssid", "192.168.7.1", "192.168.7.22", "fd00::1", "private.example"} {
		if strings.Contains(result.Detail, private) {
			t.Fatalf("private output escaped: %+v", result)
		}
	}
}

func automaticNetworkScanOwnerFixture(t *testing.T, c *AutoContext, owner string, body func([]string) (string, error)) {
	t.Helper()
	c.Run = func(args ...string) (string, error) {
		if args[0] == "busctl" && len(args) > 7 && args[7] == "NameHasOwner" {
			if args[9] == owner {
				return "b true", nil
			}
			return "b false", nil
		}
		return body(args)
	}
}

func TestAutomaticNetworkInventoryNeverPasses(t *testing.T) {
	c := automaticNetworkFixture(t)
	result := automaticNetworkInterfaces(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "wireless interfaces=1") {
		t.Fatalf("inventory: %+v", result)
	}
	for _, check := range automaticNetworkChecks() {
		if check.ID == "net.dns.lookup" {
			lookup := check.Run(c)
			if lookup.Status != "blocked" || check.Kind != "functional" || !strings.Contains(lookup.Detail, "fixture") {
				t.Fatalf("unconfigured DNS workload: %+v", lookup)
			}
		}
	}
	result = automaticNetworkDNS(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "IPv4=1, IPv6=1, loopback stubs=1") {
		t.Fatalf("DNS configuration: %+v", result)
	}
	automaticNetworkAssertPrivate(t, result)
	c.Run = func(args ...string) (string, error) {
		return "Connected to 00:11:22:33:44:55 (on wlan0)\n\tSSID: my-private-ssid\n\tfreq: 5180\n", nil
	}
	result = automaticNetworkLink(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "5180 MHz") {
		t.Fatalf("link: %+v", result)
	}
	automaticNetworkAssertPrivate(t, result)
}

func TestAutomaticNetworkMissingInterfaceBlocked(t *testing.T) {
	c := &AutoContext{Root: t.TempDir()}
	for _, check := range automaticNetworkChecks() {
		result := check.Run(c)
		if result.Status != "blocked" {
			t.Fatalf("missing support: %+v", result)
		}
	}
}

func TestAutomaticNetworkNMEmptyCompletedScanPasses(t *testing.T) {
	c := automaticNetworkFixture(t)
	lastScan, rescans := 0, 0
	automaticNetworkScanOwnerFixture(t, c, "org.freedesktop.NetworkManager", func(args []string) (string, error) {
		if args[0] == "nmcli" {
			if !reflect.DeepEqual(args, []string{"nmcli", "--wait", "5", "device", "wifi", "rescan", "ifname", "wlan0"}) {
				t.Fatalf("unexpected mutation: %v", args)
			}
			rescans++
			return "", nil
		}
		switch args[len(args)-1] {
		case "wlan0":
			return `o "/org/freedesktop/NetworkManager/Devices/2"`, nil
		case "Managed":
			return "b true", nil
		case "LastScan":
			lastScan++
			if lastScan == 1 {
				return "x 100", nil
			}
			return "x 101", nil
		case "AccessPoints":
			return "ao 0", nil
		default:
			t.Fatalf("unexpected command: %v", args)
			return "", nil
		}
	})
	result := automaticNetworkScan(c)
	if result.Status != "pass" || !strings.Contains(result.Detail, "entries=0") || rescans != 1 || lastScan != 2 {
		t.Fatalf("empty completed scan: %+v scans=%d completion reads=%d", result, rescans, lastScan)
	}
}

func TestAutomaticNetworkNMNoCompletionCannotPassCachedList(t *testing.T) {
	c := automaticNetworkFixture(t)
	lastScan := 0
	automaticNetworkScanOwnerFixture(t, c, "org.freedesktop.NetworkManager", func(args []string) (string, error) {
		if args[0] == "nmcli" {
			return "", nil
		}
		switch args[len(args)-1] {
		case "wlan0":
			return `o "/org/freedesktop/NetworkManager/Devices/2"`, nil
		case "Managed":
			return "b true", nil
		case "LastScan":
			lastScan++
			if lastScan == 1 {
				return "x 100", nil
			}
			return "my-private-ssid 00:11:22:33:44:55", errors.New("permission denied")
		default:
			t.Fatalf("cached count queried without completion: %v", args)
			return "", nil
		}
	})
	result := automaticNetworkScan(c)
	if result.Status != "blocked" {
		t.Fatalf("no completion: %+v", result)
	}
	automaticNetworkAssertPrivate(t, result)
}

func TestAutomaticNetworkIWDEmptyCompletedScanPasses(t *testing.T) {
	c := automaticNetworkFixture(t)
	properties, scans := 0, 0
	automaticNetworkScanOwnerFixture(t, c, "net.connman.iwd", func(args []string) (string, error) {
		if args[3] == "tree" {
			return "/net/connman/iwd/0/1", nil
		}
		switch args[len(args)-1] {
		case "Name":
			return `s "wlan0"`, nil
		case "Scanning":
			properties++
			if properties == 2 {
				return "b true", nil
			}
			return "b false", nil
		case "Scan":
			scans++
			return "", nil
		case "GetOrderedNetworks":
			return "a(on) 0", nil
		default:
			t.Fatalf("unexpected command: %v", args)
			return "", nil
		}
	})
	result := automaticNetworkScan(c)
	if result.Status != "pass" || !strings.Contains(result.Detail, "entries=0") || properties != 3 || scans != 1 {
		t.Fatalf("empty iwd scan: %+v", result)
	}
}

func TestAutomaticNetworkDirectScanRequiresNoOwner(t *testing.T) {
	for _, tc := range []struct {
		owner, output, status string
		err                   error
	}{
		{output: "", status: "pass"},
		{output: "BSS 00:11:22:33:44:55(on wlan0)\n\tSSID: my-private-ssid", status: "pass"},
		{output: "command failed: Operation not permitted (-1)", err: errors.New("exit status 1"), status: "blocked"},
		{output: "scan failed: Input/output error", err: errors.New("exit status 1"), status: "fail"},
		{owner: "fi.w1.wpa_supplicant1", status: "blocked"},
	} {
		c := automaticNetworkFixture(t)
		commands := 0
		automaticNetworkScanOwnerFixture(t, c, tc.owner, func(args []string) (string, error) {
			if !reflect.DeepEqual(args, []string{"timeout", "12s", "iw", "dev", "wlan0", "scan"}) {
				t.Fatalf("unexpected command: %v", args)
			}
			commands++
			return tc.output, tc.err
		})
		result := automaticNetworkScan(c)
		if result.Status != tc.status || (tc.owner != "" && commands != 0) {
			t.Fatalf("driver scan: %+v commands=%d", result, commands)
		}
		automaticNetworkAssertPrivate(t, result)
	}
}

func TestAutomaticNetworkManagerWithoutBusBlocksDriverScan(t *testing.T) {
	c := automaticNetworkFixture(t)
	if err := os.WriteFile(filepath.Join(c.Root, "proc/1/comm"), []byte("wpa_supplicant\n"), 0600); err != nil {
		t.Fatal(err)
	}
	automaticNetworkScanOwnerFixture(t, c, "", func(args []string) (string, error) {
		t.Fatalf("driver scan despite manager process: %v", args)
		return "", nil
	})
	if result := automaticNetworkScan(c); result.Status != "blocked" {
		t.Fatalf("process owner: %+v", result)
	}
}

func TestAutomaticNetworkIPSummaryPrivate(t *testing.T) {
	c := automaticNetworkFixture(t)
	c.Run = func(args ...string) (string, error) {
		if args[2] == "address" {
			return `[{"address":"00:11:22:33:44:55","addr_info":[{"family":"inet","scope":"global","local":"192.168.7.22"},{"family":"inet6","scope":"global","local":"fd00::1"},{"family":"inet6","scope":"link","local":"fe80::1"},{"family":"inet6","scope":"global","local":"fd00::2","tentative":true}]}]`, nil
		}
		return `[{"gateway":"192.168.7.1"}]`, nil
	}
	result := automaticNetworkIP(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "IPv4 global=1, IPv6 global=1, IPv6 link-local=1, tentative/DAD-failed=1") {
		t.Fatalf("IP configuration: %+v", result)
	}
	automaticNetworkAssertPrivate(t, result)
}

func TestAutomaticNetworkGatewayBoundedAndPrivate(t *testing.T) {
	for _, tc := range []struct {
		output, status string
		err            error
	}{
		{"3 packets transmitted, 3 received, 0% packet loss", "pass", nil},
		{"3 packets transmitted, 2 received, 33% packet loss", "fail", errors.New("exit status 1")},
		{"3 packets transmitted, 0 received, 100% packet loss", "blocked", errors.New("exit status 1")},
		{"ping: 192.168.7.1: Operation not permitted", "blocked", errors.New("exit status 2")},
	} {
		c := automaticNetworkFixture(t)
		c.Run = func(args ...string) (string, error) {
			if args[0] == "ip" {
				return `[{"gateway":"192.168.7.1"}]`, nil
			}
			if !reflect.DeepEqual(args, []string{"ping", "-n", "-4", "-c", "3", "-W", "1", "-w", "5", "-s", "8", "-I", "wlan0", "192.168.7.1"}) {
				t.Fatalf("unbounded or unexpected traffic: %v", args)
			}
			return "PING 192.168.7.1\n" + tc.output, tc.err
		}
		result := automaticNetworkGateway(c, 4)
		if result.Status != tc.status {
			t.Fatalf("gateway: %+v", result)
		}
		automaticNetworkAssertPrivate(t, result)
	}
}

func TestAutomaticNetworkGatewayNeverUsesPublicDestination(t *testing.T) {
	c := automaticNetworkFixture(t)
	c.Run = func(args ...string) (string, error) {
		if args[0] != "ip" {
			t.Fatalf("public traffic: %v", args)
		}
		return `[{"gateway":"8.8.8.8"}]`, nil
	}
	if result := automaticNetworkGateway(c, 4); result.Status != "blocked" {
		t.Fatalf("public fixture: %+v", result)
	}
}

func TestAutomaticNetworkIPv6GatewayBoundToWiFi(t *testing.T) {
	c := automaticNetworkFixture(t)
	c.Run = func(args ...string) (string, error) {
		if args[0] == "ip" {
			return `[{"gateway":"fe80::1"}]`, nil
		}
		if !reflect.DeepEqual(args, []string{"ping", "-n", "-6", "-c", "3", "-W", "1", "-w", "5", "-s", "8", "-I", "wlan0", "fe80::1"}) {
			t.Fatalf("IPv6 gateway not bound to Wi-Fi: %v", args)
		}
		return "PING fe80::1\n3 packets transmitted, 3 received, 0% packet loss", nil
	}
	result := automaticNetworkGateway(c, 6)
	if result.Status != "pass" || strings.Contains(result.Detail, "fe80::1") {
		t.Fatalf("IPv6 gateway: %+v", result)
	}
}

func TestAutomaticNetworkArrayCounts(t *testing.T) {
	for _, tc := range []struct {
		output, signature string
		count             int
		valid             bool
	}{
		{"ao 0", "ao", 0, true},
		{`ao 2 "/org/freedesktop/NetworkManager/AccessPoint/1" "/org/freedesktop/NetworkManager/AccessPoint/2"`, "ao", 2, true},
		{`a(on) 1 "/net/connman/iwd/0/1/001122334455" -6000`, "a(on)", 1, true},
		{"ao 2", "ao", 0, false},
		{"ao -1", "ao", 0, false},
	} {
		count, err := automaticNetworkCount(tc.output, tc.signature)
		if (err == nil) != tc.valid || count != tc.count {
			t.Fatalf("array count %q => %d %v", tc.output, count, err)
		}
	}
}

func TestAutomaticNetworkDNSLookup(t *testing.T) {
	for _, tc := range []struct {
		name, status string
		ips          []net.IP
		err          error
	}{
		{"IPv4", "pass", []net.IP{net.ParseIP("192.0.2.1")}, nil},
		{"IPv6", "pass", []net.IP{net.ParseIP("2001:db8::1")}, nil},
		{"dual", "pass", []net.IP{net.ParseIP("192.0.2.1"), net.ParseIP("2001:db8::1")}, nil},
		{"empty", "fail", nil, nil},
		{"NXDOMAIN", "fail", nil, &net.DNSError{IsNotFound: true, Name: "private.example"}},
		{"timeout", "fail", nil, context.DeadlineExceeded},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := automaticNetworkFixture(t)
			if err := os.MkdirAll(filepath.Join(c.Root, "proc/net"), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(c.Root, "proc/net/route"), []byte("wlan0 00000000 010200C0 0003 0 0 100 00000000\n"), 0600); err != nil {
				t.Fatal(err)
			}
			c.Options.DNSName = "example.org"
			calls := 0
			c.LookupIP = func(ctx context.Context, network, name string) ([]net.IP, error) {
				calls++
				deadline, ok := ctx.Deadline()
				if !ok || time.Until(deadline) > 3*time.Second || time.Until(deadline) <= 0 || network != "ip" || name != "example.org." {
					t.Fatal("missing bounded public fixture lookup")
				}
				return tc.ips, tc.err
			}
			r := automaticNetworkDNSLookup(c)
			if r.Status != tc.status || calls != 1 || !strings.Contains(r.Detail, "example.org") {
				t.Fatal(r)
			}
			for _, private := range []string{"192.0.2.1", "2001:db8::1", "private.example"} {
				if strings.Contains(r.Detail, private) {
					t.Fatal(r)
				}
			}
			if tc.name == "dual" && !strings.Contains(r.Detail, "A=1 AAAA=1") {
				t.Fatal(r)
			}
		})
	}
}

func TestAutomaticNetworkDNSBlockedWithoutLookup(t *testing.T) {
	for _, mode := range []string{"disabled", "fixture", "root", "no route", "no resolver", "invalid name"} {
		t.Run(mode, func(t *testing.T) {
			c := automaticNetworkFixture(t)
			c.LookupIP = func(context.Context, string, string) ([]net.IP, error) { t.Fatal("unexpected lookup"); return nil, nil }
			switch mode {
			case "disabled":
				c.Options.NoDNSLookup = true
			case "fixture":
				c.Fixture = true
				c.Root = "/"
			case "root":
				c.LookupIP = nil
			case "no resolver":
				if err := os.WriteFile(filepath.Join(c.Root, "etc/resolv.conf"), nil, 0600); err != nil {
					t.Fatal(err)
				}
			case "invalid name":
				c.Options.DNSName = "192.0.2.1"
			}
			if r := automaticNetworkDNSLookup(c); r.Status != "blocked" {
				t.Fatal(r)
			}
		})
	}
}

func TestAutomaticNetworkIPv6DefaultRoute(t *testing.T) {
	c := automaticNetworkFixture(t)
	if err := os.MkdirAll(filepath.Join(c.Root, "proc/net"), 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(c.Root, "proc/net/ipv6_route")
	for _, flags := range []string{"00000001", "00200200", "00000000"} {
		row := strings.Repeat("0", 32) + " 00 " + strings.Repeat("0", 32) + " 00 " + strings.Repeat("0", 32) + " 00000064 00000000 00000000 " + flags + " wlan0\n"
		if err := os.WriteFile(path, []byte(row), 0600); err != nil {
			t.Fatal(err)
		}
		if automaticNetworkDefaultRoute(c) != (flags == "00000001") {
			t.Fatalf("flags %s", flags)
		}
	}
}
