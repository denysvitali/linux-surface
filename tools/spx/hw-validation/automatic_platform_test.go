package main

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func platformFixture(t *testing.T, files map[string]string) *AutoContext {
	t.Helper()
	root := t.TempDir()
	for path, text := range files {
		full := filepath.Join(root, strings.TrimPrefix(path, "/"))
		if err := os.MkdirAll(filepath.Dir(full), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return &AutoContext{Root: root, Options: AutoOptions{StorageDir: t.TempDir()}, Run: func(...string) (string, error) {
		t.Fatal("Unexpected external command")
		return "", errors.New("unexpected")
	}}
}
func platformCheck(t *testing.T, c *AutoContext, id string) AutoResult {
	t.Helper()
	for _, check := range automaticPlatformChecks() {
		if check.ID == id {
			return check.Run(c)
		}
	}
	t.Fatal("Missing check " + id)
	return AutoResult{}
}

func platformWatchdogFixture(t *testing.T, attrs bool, driver bool) *AutoContext {
	t.Helper()
	c := platformFixture(t, nil)
	device := filepath.Join(c.Root, "sys/devices/platform/soc/17c10000.watchdog/watchdog/watchdog0")
	if err := os.MkdirAll(device, 0700); err != nil {
		t.Fatal(err)
	}
	classParent := filepath.Join(c.Root, "sys/class/watchdog")
	if err := os.MkdirAll(classParent, 0700); err != nil {
		t.Fatal(err)
	}
	class := filepath.Join(classParent, "watchdog0")
	if err := os.Symlink("../../devices/platform/soc/17c10000.watchdog/watchdog/watchdog0", class); err != nil {
		t.Fatal(err)
	}
	if attrs {
		if err := os.WriteFile(filepath.Join(device, "identity"), []byte("qcom_wdt"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	parent := filepath.Join(c.Root, "sys/devices/platform/soc/17c10000.watchdog")
	if err := os.MkdirAll(filepath.Join(parent, "of_node"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(parent, "of_node/compatible"), []byte("qcom,sc8180x-wdt\x00qcom,kpss-wdt"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../..", filepath.Join(device, "device")); err != nil {
		t.Fatal(err)
	}
	if driver {
		driverPath := filepath.Join(c.Root, "sys/bus/platform/drivers/qcom_wdt")
		if err := os.MkdirAll(driverPath, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink("../../../../bus/platform/drivers/qcom_wdt", filepath.Join(device, "device/driver")); err != nil {
			t.Fatal(err)
		}
	}
	return c
}

func TestPlatformWatchdogIdentityAttributes(t *testing.T) {
	result := platformCheck(t, platformWatchdogFixture(t, true, false), "diag.watchdog")
	if result.Status != "observed" || !strings.Contains(result.Detail, "watchdog0 identity=qcom_wdt") || strings.Contains(result.Detail, "attributes unavailable") {
		t.Fatalf("got %+v", result)
	}
}

func TestPlatformWatchdogDriverFallback(t *testing.T) {
	result := platformCheck(t, platformWatchdogFixture(t, false, true), "diag.watchdog")
	for _, fact := range []string{"driver=qcom_wdt", "parent=17c10000.watchdog", "compatible=qcom,sc8180x-wdt,qcom,kpss-wdt", "identity/state/timeout attributes unavailable", "capability inventory only", "no device open"} {
		if result.Status != "observed" || !strings.Contains(result.Detail, fact) {
			t.Fatalf("missing %q in %+v", fact, result)
		}
	}
}

func TestPlatformWatchdogWithoutAttributesOrDriverBlocked(t *testing.T) {
	result := platformCheck(t, platformWatchdogFixture(t, false, false), "diag.watchdog")
	if result.Status != "blocked" || !strings.Contains(result.Detail, "no bound parent driver") {
		t.Fatalf("got %+v", result)
	}
}

func TestPlatformMissingSupportBlocked(t *testing.T) {
	c := platformFixture(t, nil)
	for _, id := range []string{"cpu.cores", "cpu.memory", "cpu.cpufreq", "storage.nvme", "fw.remoteproc", "accel.cdsp-fastrpc", "rtc.read-time", "security.tpm", "security.tpm-capability", "security.secureboot", "thermal.metadata", "diag.boot", "diag.taint", "cpu.workload", "cpu.frequency-transitions", "fw.stability", "security.tpm-signing", "accel.cdsp-workload", "thermal.response", "pwr.supplies", "pwr.support", "diag.watchdog", "pwr.suspend-recovery", "pwr.hibernate-recovery", "diag.watchdog-recovery"} {
		t.Run(id, func(t *testing.T) {
			if result := platformCheck(t, c, id); result.Status != "blocked" {
				t.Fatalf("got %+v", result)
			}
		})
	}
}
func TestPlatformInventoriesNeverPass(t *testing.T) {
	c := platformFixture(t, map[string]string{
		"/sys/devices/system/cpu/online": "0-7", "/sys/devices/system/cpu/present": "0-7",
		"/proc/meminfo": "MemTotal: 7888896 kB\nMemAvailable: 6111104 kB\n",
		"/sys/devices/system/cpu/cpufreq/policy0/scaling_driver":   "qcom-cpufreq-hw",
		"/sys/devices/system/cpu/cpufreq/policy0/scaling_governor": "schedutil",
		"/sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq": "300000",
		"/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq": "710000",
		"/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq": "1804800",
		"/sys/class/nvme/nvme0/model":                              "Fixture NVMe",
		"/sys/class/remoteproc/remoteproc0/name":                   "cdsp", "/sys/class/remoteproc/remoteproc0/state": "offline",
		"/dev/fastrpc-cdsp-secure": "", "/sys/class/tpm/tpm0/tpm_version_major": "2",
		"/sys/firmware/efi/efivars/SecureBoot-fixture": string([]byte{7, 0, 0, 0, 1}),
		"/sys/class/thermal/thermal_zone0/type":        "cpu-cluster0", "/sys/class/thermal/thermal_zone0/temp": "42000",
		"/sys/class/thermal/thermal_zone0/trip_point_0_type": "critical", "/sys/class/thermal/thermal_zone0/trip_point_0_temp": "110000",
		"/sys/class/thermal/cooling_device0/cur_state": "0", "/sys/class/thermal/cooling_device0/max_state": "10",
		"/proc/sys/kernel/random/boot_id": "fixture-boot", "/proc/sys/kernel/osrelease": "7-fixture", "/sys/fs/pstore/previous-crash": "not read",
		"/proc/sys/kernel/tainted":        "4096",
		"/sys/class/power_supply/AC/type": "Mains", "/sys/class/power_supply/AC/online": "1",
		"/sys/class/power_supply/BAT/type": "Battery", "/sys/class/power_supply/BAT/status": "Charging", "/sys/class/power_supply/BAT/capacity": "80",
		"/sys/power/state": "freeze mem disk", "/sys/power/mem_sleep": "s2idle [deep]", "/sys/power/disk": "[platform] shutdown reboot suspend test_resume",
		"/sys/class/watchdog/watchdog0/identity": "fixture watchdog",
	})
	c.Run = func(args ...string) (string, error) {
		if args[0] != "systemctl" {
			t.Fatal(args)
		}
		return "LoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\n", nil
	}
	for _, check := range automaticPlatformChecks() {
		if check.Kind != "inventory" {
			continue
		}
		result := check.Run(c)
		if result.Status != "observed" {
			t.Errorf("%s: %+v", check.ID, result)
		}
		if strings.Contains(result.Detail, "previous-crash") {
			t.Error("pstore record filename disclosed")
		}
	}
}
func TestPlatformCPULists(t *testing.T) {
	for _, tc := range []struct {
		text  string
		count int
		valid bool
	}{{"0-7", 8, true}, {"0-3,6,8-9", 7, true}, {"0,0", 1, true}, {"2-1", 0, false}, {"", 0, false}, {"0-9999999", 0, false}, {"0-1-2", 0, false}} {
		count, err := platformCPUCount(tc.text)
		if (err == nil) != tc.valid || count != tc.count {
			t.Errorf("%q: %d %v", tc.text, count, err)
		}
	}
}
func TestPlatformCPUConsistencyACGateAndVectors(t *testing.T) {
	c := platformFixture(t, map[string]string{
		"/sys/class/power_supply/AC/type": "Mains", "/sys/class/power_supply/AC/online": "0",
		"/sys/devices/system/cpu/online": "0-7",
	})
	if result := platformCPUWorkload(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	// Exercise one consistency vector per worker, not a live device load.
	result := platformCPUConsistency(2, 1, time.Now().Add(time.Second))
	if result.Status != "pass" || !strings.Contains(result.Detail, "2 concurrent workers") {
		t.Fatal(result)
	}
	result = platformCPUConsistency(2, 1, time.Now().Add(-time.Second))
	if result.Status != "blocked" {
		t.Fatal(result)
	}
}
func TestPlatformFixtureCLINativeWorkloadsBlocked(t *testing.T) {
	c := platformFixture(t, map[string]string{
		"/sys/class/power_supply/AC/type": "Mains", "/sys/class/power_supply/AC/online": "1",
		"/sys/devices/system/cpu/online": "0-7",
	})
	c.Fixture = true
	c.Options.StorageDir = ""
	if result := platformStorage(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	if result := platformCPUWorkload(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c.Root = "/"
	if result := platformStorage(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	if result := platformCPUWorkload(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}
func TestPlatformStorageAndCleanup(t *testing.T) {
	c := platformFixture(t, nil)
	result := platformStorage(c)
	if result.Status != "pass" {
		t.Fatalf("%+v", result)
	}
	entries, err := os.ReadDir(c.Options.StorageDir)
	if err != nil || len(entries) != 0 {
		t.Fatalf("cleanup: %v %v", entries, err)
	}
	result = platformStorageFile(c.Options.StorageDir, platformStorageFreeBytes-1, 0)
	if result.Status != "blocked" {
		t.Fatal(result)
	}
	entries, err = os.ReadDir(c.Options.StorageDir)
	if err != nil || len(entries) != 0 {
		t.Fatalf("low-space created a file: %v %v", entries, err)
	}
	result = platformStorage(&AutoContext{Options: AutoOptions{StorageDir: filepath.Join(c.Options.StorageDir, "missing")}})
	if result.Status != "blocked" || strings.Contains(result.Detail, c.Options.StorageDir) {
		t.Fatal(result)
	}
	for _, tc := range []struct {
		err    error
		status string
	}{{syscall.ENOSPC, "blocked"}, {syscall.EACCES, "blocked"}, {syscall.EIO, "fail"}} {
		got := platformStorageError("write", &os.PathError{Op: "write", Path: "/private/user", Err: tc.err})
		if got.Status != tc.status || strings.Contains(got.Detail, "/private/user") {
			t.Fatal(got)
		}
	}
}
func TestPlatformStorageDetectsCorruption(t *testing.T) {
	path := filepath.Join(t.TempDir(), "payload")
	original := make([]byte, platformStorageBytes)
	expected := sha256.Sum256(original)
	original[len(original)-1] = 1
	if err := os.WriteFile(path, original, 0600); err != nil {
		t.Fatal(err)
	}
	if err := platformStorageReadback(path, expected[:]); err == nil {
		t.Fatal("corruption accepted")
	}
	if err := os.WriteFile(path, original[:100], 0600); err != nil {
		t.Fatal(err)
	}
	if err := platformStorageReadback(path, expected[:]); err == nil {
		t.Fatal("short file accepted")
	}
}
func TestPlatformRTCSystemOnlyAndMismatch(t *testing.T) {
	c := platformFixture(t, map[string]string{"/sys/class/rtc/rtc0/since_epoch": "1700000000", "/sys/class/rtc/rtc1/since_epoch": "0"})
	result := platformRTC(c, time.Unix(1700000005, 0))
	if result.Status != "pass" || !strings.Contains(result.Detail, "1 other RTC(s) not compared") {
		t.Fatal(result)
	}
	result = platformRTC(c, time.Unix(1700000006, 0))
	if result.Status != "fail" {
		t.Fatal(result)
	}
	if err := os.Remove(filepath.Join(c.Root, "sys/class/rtc/rtc0/since_epoch")); err != nil {
		t.Fatal(err)
	}
	result = platformRTC(c, time.Unix(1700000000, 0))
	if result.Status != "blocked" {
		t.Fatal(result)
	}
}
func TestPlatformSecureBootBinaryState(t *testing.T) {
	for _, tc := range []struct {
		data           []byte
		status, detail string
	}{{[]byte{7, 0, 0, 0, 0}, "observed", "disabled"}, {[]byte{7, 0, 0, 0, 1}, "observed", "enabled"}, {[]byte{7, 0, 0, 0, 2}, "error", "Malformed"}, {[]byte{0}, "error", "Malformed"}} {
		c := platformFixture(t, map[string]string{"/sys/firmware/efi/efivars/SecureBoot-fixture": string(tc.data)})
		result := platformSecureBoot(c)
		if result.Status != tc.status || !strings.Contains(result.Detail, tc.detail) {
			t.Fatal(result)
		}
	}
}
func TestPlatformFirmwareFailureAndMissingService(t *testing.T) {
	c := platformFixture(t, map[string]string{"/sys/class/remoteproc/remoteproc0/name": "adsp", "/sys/class/remoteproc/remoteproc0/state": "crashed"})
	if result := platformRemoteproc(c); result.Status != "fail" {
		t.Fatal(result)
	}
	for _, tc := range []struct{ text, status string }{{"LoadState=loaded\nActiveState=active\n", "observed"}, {"LoadState=not-found\nActiveState=inactive\n", "blocked"}, {"LoadState=loaded\nActiveState=failed\n", "fail"}} {
		c.Run = func(args ...string) (string, error) {
			if args[0] != "systemctl" {
				t.Fatal(args)
			}
			return tc.text, nil
		}
		if result := platformFirmwareServices(c); result.Status != tc.status {
			t.Fatal(result)
		}
	}
}
func TestPlatformTPMCapability(t *testing.T) {
	c := platformFixture(t, map[string]string{"/dev/tpmrm0": ""})
	for _, tc := range []struct {
		text   string
		err    error
		status string
	}{{"TPM2_PT_FAMILY_INDICATOR:\n raw: 0x322E3000", nil, "pass"}, {"", errors.New("missing tool"), "blocked"}, {"TPM_RC_FAILURE", errors.New("TPM failure"), "fail"}, {"unrecognized response", nil, "error"}} {
		c.Run = func(args ...string) (string, error) {
			if len(args) != 3 || args[0] != "tpm2_getcap" || args[1] != "--tcti=device:/dev/tpmrm0" || args[2] != "properties-fixed" {
				t.Fatal(args)
			}
			return tc.text, tc.err
		}
		result := platformTPMCapability(c)
		if result.Status != tc.status {
			t.Fatal(result)
		}
	}
}

func TestPlatformProvenFaultsSurviveUnavailableMetadata(t *testing.T) {
	c := platformFixture(t, map[string]string{
		"/sys/class/remoteproc/remoteproc0/name":             "adsp",
		"/sys/class/remoteproc/remoteproc0/state":            "crashed",
		"/sys/class/remoteproc/remoteproc1/name":             "unreadable-state",
		"/sys/class/thermal/thermal_zone0/type":              "cpu",
		"/sys/class/thermal/thermal_zone0/temp":              "110000",
		"/sys/class/thermal/thermal_zone0/trip_point_0_type": "critical",
		"/sys/class/thermal/thermal_zone0/trip_point_0_temp": "110000",
		"/sys/class/thermal/thermal_zone1/type":              "unreadable-temp",
	})
	if result := platformRemoteproc(c); result.Status != "fail" || !strings.Contains(result.Detail, "crashed") || !strings.Contains(result.Detail, "unreadable") {
		t.Fatalf("firmware crash hidden by incomplete metadata: %+v", result)
	}
	if result := platformThermal(c); result.Status != "fail" || !strings.Contains(result.Detail, "critical-temperature") || !strings.Contains(result.Detail, "unavailable") {
		t.Fatalf("critical thermal fault hidden by incomplete metadata: %+v", result)
	}
	c.Run = func(args ...string) (string, error) {
		if args[2] == "pd-mapper.service" {
			return "LoadState=loaded\nActiveState=failed\nSubState=failed\nUnitFileState=enabled", nil
		}
		return "", errors.New("query unavailable")
	}
	if result := platformFirmwareServices(c); result.Status != "fail" || !strings.Contains(result.Detail, "failed") || !strings.Contains(result.Detail, "unavailable") {
		t.Fatalf("service failure hidden by inaccessible next service: %+v", result)
	}
}
func TestPlatformThermalFaultEvidence(t *testing.T) {
	c := platformFixture(t, map[string]string{"/sys/class/thermal/thermal_zone0/type": "cpu", "/sys/class/thermal/thermal_zone0/temp": "110000", "/sys/class/thermal/thermal_zone0/trip_point_0_type": "critical", "/sys/class/thermal/thermal_zone0/trip_point_0_temp": "110000"})
	if result := platformThermal(c); result.Status != "fail" {
		t.Fatal(result)
	}
}
func TestPlatformFailedUnitsSummary(t *testing.T) {
	c := platformFixture(t, nil)
	for _, tc := range []struct {
		text   string
		err    error
		status string
	}{
		{"", nil, "pass"},
		{"private-unit.service loaded failed failed private description\n", nil, "fail"},
		{"spx-hw-validation.service loaded failed failed validator\n", nil, "pass"},
		{"spx-hw-validation.service loaded failed failed validator\nprivate-unit.service loaded failed failed private description\n", nil, "fail"},
		{"unexpected response", nil, "blocked"},
		{"", errors.New("manager unavailable"), "blocked"},
	} {
		c.Run = func(args ...string) (string, error) {
			if strings.Join(args, " ") != "systemctl list-units --state=failed --no-legend --no-pager --plain" {
				t.Fatal(args)
			}
			return tc.text, tc.err
		}
		result := platformFailedUnits(c)
		if result.Status != tc.status || strings.Contains(result.Detail, "private-unit") || strings.Contains(result.Detail, "private description") {
			t.Fatal(result)
		}
	}
}
func TestPlatformKernelFaultsPrivacyAndAccess(t *testing.T) {
	c := platformFixture(t, nil)
	for _, tc := range []struct {
		text   string
		err    error
		status string
	}{{strings.Repeat("x", 1<<20), nil, "blocked"}, {"Linux version fixture\nremoteproc remoteproc0: powering up adsp\n", nil, "pass"}, {"BUG: bad access from privateuser /home/private\narm-smmu: Unhandled context fault mac=aa:bb:cc:dd:ee:ff\n", nil, "fail"}, {"-- No entries --", nil, "pass"}, {"", nil, "pass"}, {"", errors.New("permission denied"), "blocked"}, {"kernel: Buffer I/O error on dev nvme0\n", nil, "fail"}, {"kernel: WARNING: CPU: 0 PID: 1 at fixture.c\n", nil, "fail"}} {
		c.Run = func(args ...string) (string, error) {
			if strings.Join(args, " ") != "journalctl --boot=0 -k -p warning --no-pager --output=cat --quiet" {
				t.Fatal(args)
			}
			return tc.text, tc.err
		}
		result := platformKernelFaults(c)
		if result.Status != tc.status {
			t.Fatal(result)
		}
		for _, private := range []string{"privateuser", "/home/private", "aa:bb:cc:dd:ee:ff"} {
			if strings.Contains(result.Detail, private) {
				t.Fatalf("private kernel log exposed: %+v", result)
			}
		}
	}
}

func platformFrequencyFixture(t *testing.T, count int) *AutoContext {
	t.Helper()
	files := map[string]string{}
	for i := 0; i < count; i++ {
		base := fmt.Sprintf("/sys/devices/system/cpu/cpufreq/policy%d", i)
		for key, value := range map[string]string{"scaling_min_freq": "300000", "scaling_max_freq": "1800000", "scaling_cur_freq": "300000", "scaling_governor": "schedutil", "related_cpus": fmt.Sprintf("%d %d", i, i+2), "stats/total_trans": "10", "stats/time_in_state": "300000 100"} {
			files[base+"/"+key] = value
		}
	}
	return platformFixture(t, files)
}

func TestPlatformFrequencyTransitions(t *testing.T) {
	for _, tc := range []struct {
		name, status                   string
		idle, peak, after, transitions int
	}{
		{"rise-recover", "pass", 300000, 1800000, 300000, 10},
		{"rise-no-stats", "pass", 300000, 1800000, 300000, 10},
		{"stats-evidence", "pass", 300000, 300000, 300000, 12},
		{"stuck", "fail", 300000, 300000, 300000, 10},
		{"no-recovery", "fail", 300000, 1800000, 1800000, 10},
		{"ceiling", "blocked", 1800000, 1800000, 1800000, 10},
		{"ceiling-no-stats", "blocked", 1800000, 1800000, 1800000, 10},
		{"ceiling-drop-only", "blocked", 1800000, 1800000, 300000, 10},
		{"ceiling-stats", "pass", 1800000, 1800000, 1800000, 12},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := platformFrequencyFixture(t, 2)
			noStats := strings.HasSuffix(tc.name, "no-stats")
			for i := 0; i < 2; i++ {
				base := filepath.Join(c.Root, fmt.Sprintf("sys/devices/system/cpu/cpufreq/policy%d", i))
				if err := os.WriteFile(filepath.Join(base, "scaling_cur_freq"), []byte(strconv.Itoa(tc.idle)), 0600); err != nil {
					t.Fatal(err)
				}
				if noStats {
					if err := os.RemoveAll(filepath.Join(base, "stats")); err != nil {
						t.Fatal(err)
					}
				}
			}
			started := make(chan string, 2)
			release := make(chan struct{})
			c.Run = func(args ...string) (string, error) {
				if args[0] == "sh" {
					if strings.Join(args, " ") != "sh -c command -v taskset >/dev/null && command -v timeout >/dev/null && command -v sh >/dev/null" {
						return "", errors.New("unexpected tool probe")
					}
					return "", nil
				}
				if strings.Join(args, " ") != "taskset -c "+args[2]+" timeout -k 0.2 1.5 sh -c while :; do :; done" {
					return "", errors.New("unexpected workload")
				}
				started <- args[2]
				<-release
				return "", platformTimeoutExit{}
			}
			calls := 0
			var elapsed time.Duration
			result := platformCPUTransitionsWithSleep(c, func(d time.Duration) {
				elapsed += d
				calls++
				if calls == 1 {
					cpus := map[string]bool{<-started: true, <-started: true}
					if !cpus["0"] || !cpus["1"] {
						t.Fatal(cpus)
					}
				}
				freq := tc.peak
				if calls > 6 {
					freq = tc.after
				}
				for i := 0; i < 2; i++ {
					base := filepath.Join(c.Root, fmt.Sprintf("sys/devices/system/cpu/cpufreq/policy%d", i))
					if err := os.WriteFile(filepath.Join(base, "scaling_cur_freq"), []byte(strconv.Itoa(freq)), 0600); err != nil {
						t.Fatal(err)
					}
					if !noStats {
						if err := os.WriteFile(filepath.Join(base, "stats/total_trans"), []byte(strconv.Itoa(tc.transitions)), 0600); err != nil {
							t.Fatal(err)
						}
					}
				}
				if calls == 6 {
					close(release)
				}
			})
			if result.Status != tc.status || elapsed != 4500*time.Millisecond || !strings.Contains(result.Detail, "policy0 min/idle/peak/after=") || !strings.Contains(result.Detail, "policy1 min/idle/peak/after=") {
				t.Fatalf("%+v; delay=%v", result, elapsed)
			}
			if tc.status == "blocked" && !strings.Contains(result.Detail, "started at policy maximum") {
				t.Fatalf("missing measurement prerequisite: %+v", result)
			}
		})
	}
}

func TestPlatformFrequencyMixedPolicies(t *testing.T) {
	for _, tc := range []struct {
		name, status              string
		blockedCPU                int
		unreadable, siblingPassed bool
	}{
		{"ceiling-first", "fail", 0, false, false},
		{"ceiling-last", "fail", 1, false, false},
		{"unreadable-first", "fail", 0, true, false},
		{"unreadable-last", "fail", 1, true, false},
		{"stats-before-ceiling", "blocked", 1, false, true},
		{"stats-after-ceiling", "blocked", 0, false, true},
		{"stats-before-unreadable", "blocked", 1, true, true},
		{"stats-after-unreadable", "blocked", 0, true, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := platformFrequencyFixture(t, 2)
			base := filepath.Join(c.Root, fmt.Sprintf("sys/devices/system/cpu/cpufreq/policy%d", tc.blockedCPU))
			if !tc.unreadable {
				if err := os.WriteFile(filepath.Join(base, "scaling_cur_freq"), []byte("1800000"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if tc.siblingPassed {
				sibling := filepath.Join(c.Root, fmt.Sprintf("sys/devices/system/cpu/cpufreq/policy%d/scaling_cur_freq", 1-tc.blockedCPU))
				if err := os.WriteFile(sibling, []byte("1800000"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			c.Run = func(args ...string) (string, error) {
				if args[0] == "sh" {
					return "", nil
				}
				if args[0] != "taskset" {
					return "", errors.New("unexpected command")
				}
				return "", platformTimeoutExit{}
			}
			calls := 0
			result := platformCPUTransitionsWithSleep(c, func(time.Duration) {
				calls++
				if calls == 1 && tc.unreadable {
					if err := os.Remove(filepath.Join(base, "scaling_cur_freq")); err != nil {
						t.Fatal(err)
					}
				}
				if calls == 1 && tc.siblingPassed {
					sibling := filepath.Join(c.Root, fmt.Sprintf("sys/devices/system/cpu/cpufreq/policy%d/stats/total_trans", 1-tc.blockedCPU))
					if err := os.WriteFile(sibling, []byte("12"), 0600); err != nil {
						t.Fatal(err)
					}
				}
			})
			if result.Status != tc.status || calls != 12 {
				t.Fatalf("wrong mixed-policy outcome: %+v; samples=%d", result, calls)
			}
		})
	}
}

type platformTimeoutExit struct{}

func (platformTimeoutExit) Error() string { return "exit status 124" }
func (platformTimeoutExit) ExitCode() int { return 124 }

func TestPlatformFrequencyBlocked(t *testing.T) {
	for _, reason := range []string{"no-policies", "fixture", "fixed-governor", "fixed-limits", "unreadable", "tools", "affinity"} {
		t.Run(reason, func(t *testing.T) {
			c := platformFrequencyFixture(t, 1)
			base := filepath.Join(c.Root, "sys/devices/system/cpu/cpufreq/policy0")
			switch reason {
			case "no-policies":
				os.RemoveAll(base)
			case "fixture":
				c.Fixture = true
			case "fixed-governor":
				os.WriteFile(filepath.Join(base, "scaling_governor"), []byte("performance"), 0600)
			case "fixed-limits":
				os.WriteFile(filepath.Join(base, "scaling_max_freq"), []byte("300000"), 0600)
			case "unreadable":
				os.Remove(filepath.Join(base, "related_cpus"))
			case "tools", "affinity":
				c.Run = func(args ...string) (string, error) {
					if reason == "affinity" && args[0] == "sh" {
						return "", nil
					}
					return "", errors.New("unavailable")
				}
			}
			if result := platformCPUTransitionsWithSleep(c, func(time.Duration) {}); result.Status != "blocked" {
				t.Fatal(result)
			}
		})
	}
}

func TestPlatformTPMSigning(t *testing.T) {
	for _, tc := range []struct{ name, failure, algorithms, status string }{
		{"ecc-pass", "", "ecc:\n  value: 0x23\nrsa:\n", "pass"},
		{"rsa-pass", "", "rsa:\n", "pass"},
		{"tools", "sh", "ecc:\n", "blocked"},
		{"transport", "tpm2_getcap", "ecc:\n", "blocked"},
		{"algorithms", "", "sha256:\n", "blocked"},
		{"creation", "tpm2_createprimary", "ecc:\n", "blocked"},
		{"sign", "tpm2_sign", "ecc:\n", "fail"},
		{"verify", "tpm2_verifysignature", "ecc:\n", "fail"},
		{"cleanup", "tpm2_flushcontext", "ecc:\n", "error"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := platformFixture(t, map[string]string{"/dev/tpmrm0": ""})
			var calls []string
			var dir, context, digestFile, signature string
			c.Run = func(args ...string) (string, error) {
				calls = append(calls, args[0])
				if args[0] != "sh" && args[1] != "--tcti=device:/dev/tpmrm0" {
					t.Fatal(args)
				}
				switch args[0] {
				case "sh":
					if len(args) != 3 || !strings.Contains(args[2], "command -v tpm2_flushcontext >/dev/null") {
						t.Fatal(args)
					}
				case "tpm2_getcap":
					if args[2] != "algorithms" {
						t.Fatal(args)
					}
				case "tpm2_createprimary":
					context = args[len(args)-1]
					dir = filepath.Dir(context)
					digestFile, signature = filepath.Join(dir, "digest"), filepath.Join(dir, "signature")
					algorithm := "ecc"
					if tc.name == "rsa-pass" {
						algorithm = "rsa"
					}
					want := []string{"tpm2_createprimary", "--tcti=device:/dev/tpmrm0", "-C", "n", "-G", algorithm, "-g", "sha256", "-a", "sign|fixedtpm|fixedparent|sensitivedataorigin|userwithauth", "-c", context}
					if !reflect.DeepEqual(args, want) {
						t.Fatal(args)
					}
					info, err := os.Stat(dir)
					if err != nil || info.Mode().Perm() != 0700 {
						t.Fatal(info, err)
					}
					data, err := os.ReadFile(digestFile)
					expected := sha256.Sum256([]byte("Surface Pro X automatic TPM signing smoke v1"))
					if err != nil || string(data) != string(expected[:]) {
						t.Fatal("wrong digest", err)
					}
					if err := os.WriteFile(context, []byte("fake transient"), 0600); err != nil {
						t.Fatal(err)
					}
				case "tpm2_sign":
					want := []string{"tpm2_sign", "--tcti=device:/dev/tpmrm0", "-c", context, "-g", "sha256", "-d", "-f", "tss", "-o", signature, digestFile}
					if !reflect.DeepEqual(args, want) {
						t.Fatal(args)
					}
				case "tpm2_verifysignature":
					want := []string{"tpm2_verifysignature", "--tcti=device:/dev/tpmrm0", "-c", context, "-d", digestFile, "-s", signature}
					if !reflect.DeepEqual(args, want) {
						t.Fatal(args)
					}
				case "tpm2_flushcontext":
					if strings.Join(args, " ") != "tpm2_flushcontext --tcti=device:/dev/tpmrm0 -t" {
						t.Fatal(args)
					}
				default:
					t.Fatal(args)
				}
				if args[0] == tc.failure {
					return "private TPM error", errors.New("failed")
				}
				return tc.algorithms, nil
			}
			result := platformCheck(t, c, "security.tpm-signing")
			if result.Status != tc.status || strings.Contains(result.Detail, "private TPM error") {
				t.Fatal(result)
			}
			if dir != "" {
				if _, err := os.Stat(dir); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("files retained", err)
				}
				if calls[len(calls)-1] != "tpm2_flushcontext" {
					t.Fatal("flush omitted", calls)
				}
			}
			if tc.failure == "tpm2_sign" && strings.Contains(strings.Join(calls, " "), "tpm2_verifysignature") {
				t.Fatal(calls)
			}
		})
	}
}

func TestPlatformTPMSigningFixtureAndMissingDevice(t *testing.T) {
	c := platformFixture(t, nil)
	if result := platformTPMSigning(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c = platformFixture(t, map[string]string{"/dev/tpmrm0": ""})
	c.Fixture = true
	if result := platformTPMSigning(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c.Root = "/"
	if result := platformTPMSigning(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}
