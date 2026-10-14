package main

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const platformStorageBytes = 4 << 20
const platformStorageFreeBytes = 8 << 20
const platformRTCSlack = 5 * time.Second
const platformCPUBufferBytes = 1 << 20
const platformCPUWorkerLimit = 8
const platformCPURoundLimit = 64
const platformCPUTimeLimit = time.Second

func automaticPlatformChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "cpu.cores", Title: "CPU online/present inventory", Area: "Platform", Kind: "inventory", Boxes: []string{"B03"}, Run: platformCPUCores},
		{ID: "cpu.memory", Title: "Memory capacity inventory", Area: "Platform", Kind: "inventory", Boxes: []string{"B03"}, Run: platformMemory},
		{ID: "cpu.cpufreq", Title: "CPU frequency policy inventory", Area: "Platform", Kind: "inventory", Boxes: []string{"B03", "P02"}, Run: platformCPUFreq},
		{ID: "cpu.workload", Title: "AC-only bounded CPU/memory consistency", Area: "Platform", Kind: "functional", Boxes: []string{"B03"}, Run: platformCPUWorkload},
		{ID: "cpu.frequency-transitions", Title: "Loaded frequency transitions and idle recovery", Area: "Platform", Kind: "functional", Boxes: []string{"B03", "P02"}, Run: platformCPUTransitions},
		{ID: "storage.nvme", Title: "NVMe controller inventory", Area: "Storage", Kind: "inventory", Boxes: []string{"B02"}, Run: platformNVMe},
		{ID: "storage.fsync-checksum", Title: "Disposable filesystem write/fsync/checksum (4 MiB)", Area: "Storage", Kind: "functional", Boxes: []string{"B02"}, Run: platformStorage},
		{ID: "fw.remoteproc", Title: "Remote processor states (no startup)", Area: "Firmware", Kind: "inventory", Boxes: []string{"B04"}, Run: platformRemoteproc},
		{ID: "fw.services", Title: "Firmware service states", Area: "Firmware", Kind: "inventory", Boxes: []string{"B04"}, Run: platformFirmwareServices},
		{ID: "fw.stability", Title: "Combined-use/resume firmware stability", Area: "Firmware", Kind: "functional", Boxes: []string{"B04"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("fw.stability", "Combined firmware-use/resume fixture is not supplied; this safe boot suite does not start parked DSPs or suspend the device")
		}},
		{ID: "accel.cdsp-fastrpc", Title: "CDSP/FastRPC interface inventory (no startup)", Area: "Firmware", Kind: "inventory", Boxes: []string{"B07"}, Run: platformFastRPC},
		{ID: "accel.cdsp-workload", Title: "Supported CDSP workload", Area: "Firmware", Kind: "functional", Boxes: []string{"B07"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("accel.cdsp-workload", "CDSP startup/workload remains parked; no supported workload fixture or authorization to start the disabled path")
		}},
		{ID: "rtc.read-time", Title: "RTC accessible time agrees with system clock", Area: "Platform", Kind: "functional", Boxes: []string{"B05"}, Run: func(c *AutoContext) AutoResult { return platformRTC(c, time.Now()) }},
		{ID: "security.tpm", Title: "TPM interface inventory", Area: "Security", Kind: "inventory", Boxes: []string{"B06"}, Run: platformTPM},
		{ID: "security.tpm-capability", Title: "Read-only TPM2 fixed-capability response", Area: "Security", Kind: "functional", Boxes: []string{"B06"}, Run: platformTPMCapability},
		{ID: "security.tpm-signing", Title: "TPM signing workflow", Area: "Security", Kind: "functional", Boxes: []string{"B06"}, Run: platformTPMSigning},
		{ID: "security.secureboot", Title: "EFI Secure Boot state inventory", Area: "Security", Kind: "inventory", Boxes: []string{"B06"}, Run: platformSecureBoot},
		{ID: "thermal.metadata", Title: "Thermal temperatures, trips and cooling states (no load)", Area: "Thermal", Kind: "inventory", Boxes: []string{"P05"}, Run: platformThermal},
		{ID: "thermal.response", Title: "Automatic thermal response under load", Area: "Thermal", Kind: "functional", Boxes: []string{"P05"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("thermal.response", "Thermal-response workload is parked; this suite does not heat the device or change thermal policy")
		}},
		{ID: "pwr.supplies", Title: "Battery and external-power metadata (no discharge/load)", Area: "Power", Kind: "inventory", Boxes: []string{"P01", "P02"}, Run: platformPowerSupplies},
		{ID: "pwr.support", Title: "Sleep interfaces and masked service states (no suspend)", Area: "Power", Kind: "inventory", Boxes: []string{"P03", "P04"}, Run: platformPowerSupport},
		{ID: "pwr.suspend-recovery", Title: "Device suspend/resume recovery", Area: "Power", Kind: "functional", Boxes: []string{"P03"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("pwr.suspend-recovery", "Suspend/resume is excluded from the safe boot suite; no sleep masks or driver states are changed")
		}},
		{ID: "pwr.hibernate-recovery", Title: "Device hibernate/resume recovery", Area: "Power", Kind: "functional", Boxes: []string{"P04"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("pwr.hibernate-recovery", "Hibernation/reboot recovery is excluded from the safe boot suite; no sleep masks or boot state are changed")
		}},
		{ID: "diag.watchdog", Title: "Watchdog interface inventory (no device open)", Area: "Diagnostics", Kind: "inventory", Boxes: []string{"R02"}, Run: platformWatchdog},
		{ID: "diag.watchdog-recovery", Title: "Watchdog reset/recovery", Area: "Diagnostics", Kind: "functional", Boxes: []string{"R02"}, Run: func(c *AutoContext) AutoResult {
			return platformBlocked("diag.watchdog-recovery", "No reset/recovery fixture or authorization in this boot suite; watchdog devices are never opened or armed")
		}},
		{ID: "diag.boot", Title: "Boot identity and retained fault-record inventory", Area: "Diagnostics", Kind: "inventory", Boxes: []string{"B01", "R01"}, Run: platformBoot},
		{ID: "diag.kernel-faults", Title: "Current boot warning-priority kernel fault scan", Area: "Diagnostics", Kind: "functional", Boxes: []string{"R01", "B02", "B03", "B04", "P05"}, Run: platformKernelFaults},
		{ID: "diag.taint", Title: "Kernel taint inventory", Area: "Diagnostics", Kind: "inventory", Boxes: []string{"R01", "F02"}, Run: platformTaint},
		{ID: "diag.failed-units", Title: "Current systemd failed-unit scan", Area: "Diagnostics", Kind: "functional", Boxes: []string{"F03"}, Run: platformFailedUnits},
	}
}

func platformResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}
func platformBlocked(id, detail string) AutoResult { return platformResult(id, "blocked", detail) }
func platformInt(c *AutoContext, path string) (int64, error) {
	text, err := c.Read(path)
	if err != nil {
		return 0, err
	}
	return strconv.ParseInt(strings.TrimSpace(text), 10, 64)
}
func platformCPUCount(text string) (int, error) {
	cores := map[int]bool{}
	for _, part := range strings.Split(strings.TrimSpace(text), ",") {
		limits := strings.Split(part, "-")
		if len(limits) > 2 {
			return 0, errors.New("invalid CPU list")
		}
		low, err := strconv.Atoi(limits[0])
		if err != nil || low < 0 || low > 65535 {
			return 0, errors.New("invalid CPU list")
		}
		high := low
		if len(limits) == 2 {
			high, err = strconv.Atoi(limits[1])
		}
		if err != nil || high < low || high > 65535 {
			return 0, errors.New("invalid CPU list")
		}
		for n := low; n <= high; n++ {
			cores[n] = true
		}
	}
	return len(cores), nil
}
func platformCPUCores(c *AutoContext) AutoResult {
	const id = "cpu.cores"
	var parts []string
	for _, name := range []string{"online", "present"} {
		text, err := c.Read("/sys/devices/system/cpu/" + name)
		if err != nil {
			return platformBlocked(id, "CPU "+name+" list is not readable")
		}
		count, err := platformCPUCount(text)
		if err != nil {
			return platformResult(id, "error", "Malformed CPU "+name+" list")
		}
		parts = append(parts, fmt.Sprintf("%s=%d", name, count))
	}
	return platformResult(id, "observed", strings.Join(parts, "; ")+"; enumeration only; no CPU load or frequency-transition test")
}
func platformMemory(c *AutoContext) AutoResult {
	const id = "cpu.memory"
	text, err := c.Read("/proc/meminfo")
	if err != nil {
		return platformBlocked(id, "/proc/meminfo is not readable")
	}
	values := map[string]int64{}
	for _, line := range strings.Split(text, "\n") {
		fields := strings.Fields(line)
		if len(fields) != 3 || (fields[0] != "MemTotal:" && fields[0] != "MemAvailable:") {
			continue
		}
		value, err := strconv.ParseInt(fields[1], 10, 64)
		if err != nil || value < 0 || fields[2] != "kB" {
			return platformResult(id, "error", "Malformed memory capacity data")
		}
		values[fields[0]] = value
	}
	total, totalOK := values["MemTotal:"]
	available, availableOK := values["MemAvailable:"]
	if !totalOK || total == 0 || !availableOK {
		return platformBlocked(id, "MemTotal/MemAvailable capacity fields are unavailable")
	}
	return platformResult(id, "observed", fmt.Sprintf("total=%d MiB; available=%d MiB; no memory load test", total/1024, available/1024))
}
func platformCPUFreq(c *AutoContext) AutoResult {
	const id = "cpu.cpufreq"
	paths, err := c.Glob("/sys/devices/system/cpu/cpufreq/policy*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "CPU frequency policy interface is not exposed/readable")
	}
	var parts []string
	for _, p := range paths {
		governor, e1 := c.Read(p + "/scaling_governor")
		driver, e2 := c.Read(p + "/scaling_driver")
		low, e3 := platformInt(c, p+"/scaling_min_freq")
		current, e4 := platformInt(c, p+"/scaling_cur_freq")
		high, e5 := platformInt(c, p+"/scaling_max_freq")
		if errors.Join(e1, e2, e3, e4, e5) != nil {
			return platformBlocked(id, filepath.Base(p)+" frequency policy attributes are unavailable/readable numbers are required")
		}
		parts = append(parts, fmt.Sprintf("%s driver=%s governor=%s min/current/max=%d/%d/%d kHz", filepath.Base(p), driver, governor, low, current, high))
	}
	return platformResult(id, "observed", strings.Join(parts, "; ")+"; no transitions or idle recovery exercised")
}

// All policies share one load/idle window, rather than multiplying the runtime.
func platformCPUTransitions(c *AutoContext) AutoResult {
	return platformCPUTransitionsWithSleep(c, time.Sleep)
}
func platformCPUTransitionsWithSleep(c *AutoContext, sleep func(time.Duration)) AutoResult {
	const id = "cpu.frequency-transitions"
	if c.Fixture || (c.Run == nil && c.Root != "" && filepath.Clean(c.Root) != "/") {
		return platformBlocked(id, "Frequency workload disabled for fixture root")
	}
	paths, err := c.Glob("/sys/devices/system/cpu/cpufreq/policy*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "No readable cpufreq policies")
	}
	type policy struct {
		path, cpu                           string
		min, idle, peak, after, transitions int64
		hasTransitions                      bool
	}
	policies := make([]policy, 0, len(paths))
	for _, path := range paths {
		low, e1 := platformInt(c, path+"/scaling_min_freq")
		high, e2 := platformInt(c, path+"/scaling_max_freq")
		idle, e3 := platformInt(c, path+"/scaling_cur_freq")
		cpus, e4 := c.Read(path + "/related_cpus")
		governor, e5 := c.Read(path + "/scaling_governor")
		if errors.Join(e1, e2, e3, e4, e5) != nil || low <= 0 || high < low || idle <= 0 || len(strings.Fields(cpus)) == 0 {
			return platformBlocked(id, filepath.Base(path)+" frequency/CPU/governor attributes unreadable or invalid")
		}
		if governor == "performance" || governor == "powersave" || low == high {
			return platformBlocked(id, filepath.Base(path)+" governor or frequency limits fixed; no policy changed")
		}
		cpu := strings.Fields(cpus)[0]
		n, err := strconv.Atoi(cpu)
		if err != nil || n < 0 || n > 65535 {
			return platformBlocked(id, filepath.Base(path)+" related_cpus does not identify a valid CPU")
		}
		transitions, err := platformInt(c, path+"/stats/total_trans")
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return platformBlocked(id, filepath.Base(path)+" transition statistics unreadable")
		}
		if _, err := c.Read(path + "/stats/time_in_state"); err != nil && !errors.Is(err, os.ErrNotExist) {
			return platformBlocked(id, filepath.Base(path)+" time-in-state statistics unreadable")
		}
		policies = append(policies, policy{path: path, cpu: cpu, min: low, idle: idle, peak: idle, after: idle, transitions: transitions, hasTransitions: err == nil})
	}
	if _, err := c.Command("sh", "-c", "command -v taskset >/dev/null && command -v timeout >/dev/null && command -v sh >/dev/null"); err != nil {
		return platformBlocked(id, "taskset/timeout/sh tools unavailable; no load started")
	}
	finished := make(chan error, len(policies))
	for _, p := range policies {
		go func(cpu string) {
			_, err := c.Command("taskset", "-c", cpu, "timeout", "-k", "0.2", "1.5", "sh", "-c", "while :; do :; done")
			// GNU timeout normally ends this deliberately infinite workload with 124.
			var exit interface{ ExitCode() int }
			if errors.As(err, &exit) && exit.ExitCode() == 124 {
				err = nil
			}
			finished <- err
		}(p.cpu)
	}
	unreadable := false
	for sample := 0; sample < 6; sample++ {
		sleep(250 * time.Millisecond)
		for i := range policies {
			freq, err := platformInt(c, policies[i].path+"/scaling_cur_freq")
			if err != nil || freq <= 0 {
				unreadable = true
			} else if freq > policies[i].peak {
				policies[i].peak = freq
			}
		}
	}
	// Drain all workers even when one fails; no load is left behind on return.
	loadFailed := false
	for range policies {
		loadFailed = (<-finished != nil) || loadFailed
	}
	if loadFailed {
		return platformBlocked(id, "Bounded pinned workload could not run for every policy (tool/affinity prerequisite); all workers exited")
	}
	for sample := 0; sample < 6; sample++ {
		sleep(500 * time.Millisecond)
		for i := range policies {
			freq, err := platformInt(c, policies[i].path+"/scaling_cur_freq")
			if err != nil || freq <= 0 {
				unreadable = true
			} else if sample == 0 || freq < policies[i].after {
				policies[i].after = freq
			}
		}
	}
	status := "pass"
	var details []string
	for _, p := range policies {
		transitions, err := platformInt(c, p.path+"/stats/total_trans")
		increased := p.hasTransitions && err == nil && transitions > p.transitions
		if p.hasTransitions && err != nil {
			unreadable = true
		}
		if !increased && !(p.peak > p.idle && p.after < p.peak) {
			status = "fail"
		}
		details = append(details, fmt.Sprintf("%s min/idle/peak/after=%d/%d/%d/%d kHz; total_trans increased=%t", filepath.Base(p.path), p.min, p.idle, p.peak, p.after, increased))
	}
	if unreadable {
		status = "blocked"
		details = append(details, "frequency sample or previously available transition statistics became unreadable/invalid")
	}
	return platformResult(id, status, strings.Join(details, "; ")+"; 1.5s pinned load per policy in parallel, 3s idle sampling; no sysfs writes, governor/limit changes, thermal or battery test")
}

func platformCPUWorkload(c *AutoContext) AutoResult {
	const id = "cpu.workload"
	if c.Fixture {
		return platformBlocked(id, "CPU/memory workload disabled for fixture CLI; mocked unit helpers only")
	}
	supplies, err := c.Glob("/sys/class/power_supply/*")
	if err != nil {
		return platformBlocked(id, "External-power metadata is unreadable; no battery CPU/memory load allowed")
	}
	onAC := false
	for _, p := range supplies {
		kind, err := c.Read(p + "/type")
		if err != nil || (kind != "Mains" && kind != "USB" && kind != "USB_C" && kind != "USB_PD") {
			continue
		}
		online, err := platformInt(c, p+"/online")
		if err == nil && online == 1 {
			onAC = true
		}
	}
	if !onAC {
		return platformBlocked(id, "No readable online external-power supply; no battery CPU/memory load allowed")
	}
	online, err := c.Read("/sys/devices/system/cpu/online")
	if err != nil {
		return platformBlocked(id, "Online CPU count unavailable for bounded consistency check")
	}
	workers, err := platformCPUCount(online)
	if err != nil || workers < 1 {
		return platformBlocked(id, "Valid online CPU count required for bounded consistency check")
	}
	if workers > platformCPUWorkerLimit {
		workers = platformCPUWorkerLimit
	}
	return platformCPUConsistency(workers, platformCPURoundLimit, time.Now().Add(platformCPUTimeLimit))
}
func platformCPUConsistency(workers, roundLimit int, deadline time.Time) AutoResult {
	const id = "cpu.workload"
	type outcome struct {
		rounds int
		valid  bool
	}
	outcomes := make(chan outcome, workers)
	start := make(chan struct{})
	for worker := 0; worker < workers; worker++ {
		go func() {
			buffer := make([]byte, platformCPUBufferBytes)
			for i := range buffer {
				buffer[i] = byte(i*31 + i/251)
			}
			<-start
			result := outcome{valid: true}
			// Fixed-size vectors plus a wall-clock deadline bound work; no timers or I/O.
			expected := [32]byte{0xdc, 0x6e, 0x5c, 0x46, 0x32, 0x9e, 0x70, 0x19, 0xfc, 0xa9, 0x8b, 0x07, 0xfa, 0x2d, 0xdc, 0x98, 0xde, 0x06, 0x45, 0x44, 0x48, 0xc4, 0x57, 0xa4, 0x7c, 0xf0, 0x09, 0x22, 0xc9, 0x00, 0x6d, 0xeb}
			for result.rounds < roundLimit && time.Now().Before(deadline) {
				var sum uint64
				for i := uint64(1); i <= 16384; i++ {
					sum += i * i
				}
				if sum != 1466149724160 || sha256.Sum256(buffer) != expected {
					result.valid = false
					break
				}
				result.rounds++
			}
			outcomes <- result
		}()
	}
	close(start)
	rounds := 0
	empty := false
	valid := true
	for worker := 0; worker < workers; worker++ {
		result := <-outcomes
		rounds += result.rounds
		valid = valid && result.valid
		empty = empty || result.rounds == 0
	}
	if !valid {
		return platformResult(id, "fail", "Bounded CPU arithmetic/memory SHA-256 vector mismatch")
	}
	if empty {
		return platformBlocked(id, "Worker scheduling exhausted the one-second bound before every worker completed a consistency round")
	}
	return platformResult(id, "pass", fmt.Sprintf("External power online; %d concurrent workers, 1 MiB private buffer each, %d total consistency rounds; <=64 rounds/worker and one-second work deadline; no affinity/clock changes; not frequency, thermal, sustained or all-core placement validation", workers, rounds))
}
func platformNVMe(c *AutoContext) AutoResult {
	const id = "storage.nvme"
	paths, err := c.Glob("/sys/class/nvme/nvme*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "NVMe controller interface is not exposed/readable; hardware absence is not established")
	}
	var parts []string
	for _, p := range paths {
		model, err := c.Read(p + "/model")
		if err != nil {
			return platformBlocked(id, "NVMe model metadata is not readable")
		}
		parts = append(parts, filepath.Base(p)+" model="+model)
	}
	return platformResult(id, "observed", strings.Join(parts, "; ")+"; controller enumeration only")
}

func platformStorage(c *AutoContext) AutoResult {
	if c.Fixture {
		return platformBlocked("storage.fsync-checksum", "Native disposable-file workload disabled for fixture CLI; mocked unit helpers only")
	}
	dir := c.Options.StorageDir
	if dir == "" {
		dir = os.TempDir()
	}
	var info syscall.Statfs_t
	if err := syscall.Statfs(dir, &info); err != nil {
		return platformStorageError("inspect filesystem", err)
	}
	return platformStorageFile(dir, uint64(info.Bavail)*uint64(info.Bsize), int64(info.Type))
}
func platformStorageError(operation string, err error) AutoResult {
	var pathErr *os.PathError
	if errors.As(err, &pathErr) {
		err = pathErr.Err
	}
	status := "fail"
	if errors.Is(err, syscall.ENOSPC) || errors.Is(err, syscall.EDQUOT) || errors.Is(err, syscall.EROFS) || errors.Is(err, syscall.EACCES) || errors.Is(err, syscall.EPERM) || errors.Is(err, syscall.ENOENT) || errors.Is(err, syscall.ENOTDIR) {
		status = "blocked"
	}
	return platformResult("storage.fsync-checksum", status, fmt.Sprintf("Disposable file %s: %v", operation, err))
}
func platformStorageFile(dir string, available uint64, fsType int64) (result AutoResult) {
	const id = "storage.fsync-checksum"
	if available < platformStorageFreeBytes {
		return platformBlocked(id, "Less than 8 MiB available; no disposable file created (4 MiB payload plus 4 MiB reserve)")
	}
	file, err := os.CreateTemp(dir, ".spx-hwv-*")
	if err != nil {
		return platformStorageError("create", err)
	}
	defer func() {
		file.Close()
		if err := os.Remove(file.Name()); err != nil {
			result = platformStorageError("cleanup", err)
		}
	}()
	block := make([]byte, 64<<10)
	for i := range block {
		block[i] = byte(i*31 + i/251)
	}
	expected := sha256.New()
	for n := 0; n < platformStorageBytes/len(block); n++ {
		if _, err := io.MultiWriter(file, expected).Write(block); err != nil {
			return platformStorageError("write", err)
		}
	}
	if err := file.Sync(); err != nil {
		return platformStorageError("fsync", err)
	}
	if err := file.Close(); err != nil {
		return platformStorageError("close after fsync", err)
	}
	if err := platformStorageReadback(file.Name(), expected.Sum(nil)); err != nil {
		return platformStorageError("readback/checksum", err)
	}
	storageScope := "filesystem test only"
	if fsType == 0x01021994 || fsType == 0x858458f6 {
		storageScope = "volatile RAM-backed filesystem; not persistent storage validation"
	}
	return platformResult(id, "pass", fmt.Sprintf("4 MiB disposable file written, fsynced, reopened and SHA-256 matched; file removed; filesystem type=0x%x; %s; not sustained/post-resume or raw NVMe validation", fsType, storageScope))
}
func platformStorageReadback(path string, expected []byte) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	actual := sha256.New()
	size, err := io.Copy(actual, io.LimitReader(file, platformStorageBytes+1))
	if err != nil {
		return err
	}
	if size != platformStorageBytes || string(actual.Sum(nil)) != string(expected) {
		return errors.New("length or SHA-256 mismatch")
	}
	return nil
}

func platformRemoteproc(c *AutoContext) AutoResult {
	const id = "fw.remoteproc"
	paths, err := c.Glob("/sys/class/remoteproc/remoteproc*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "Remote processor state interfaces are not exposed/readable")
	}
	var parts []string
	status := "observed"
	for _, p := range paths {
		name, e1 := c.Read(p + "/name")
		state, e2 := c.Read(p + "/state")
		if e1 != nil || e2 != nil {
			parts = append(parts, "remote processor name/state metadata unreadable")
			if status != "fail" {
				status = "blocked"
			}
			continue
		}
		if state == "crashed" {
			status = "fail"
		}
		parts = append(parts, name+"="+state)
	}
	return platformResult(id, status, strings.Join(parts, "; ")+"; no remote processor started; offline CDSP is not a malfunction; combined-use/resume stability is untested")
}
func platformFirmwareServices(c *AutoContext) AutoResult {
	const id = "fw.services"
	status := "observed"
	var parts []string
	for _, unit := range []string{"pd-mapper.service", "rmtfs.service", "tqftpserv.service"} {
		text, err := c.Command("systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,UnitFileState", "--no-pager")
		if err != nil {
			parts = append(parts, "systemctl status query unavailable for "+unit+" (tool/service access required)")
			if status != "fail" {
				status = "blocked"
			}
			continue
		}
		props := map[string]string{}
		for _, line := range strings.Split(text, "\n") {
			pair := strings.SplitN(line, "=", 2)
			if len(pair) == 2 {
				props[pair[0]] = pair[1]
			}
		}
		load, active := props["LoadState"], props["ActiveState"]
		if active == "failed" {
			status = "fail"
		} else if (load != "loaded" || active != "active" || props["UnitFileState"] == "masked") && status != "fail" {
			status = "blocked"
		}
		parts = append(parts, fmt.Sprintf("%s load=%s active=%s sub=%s enabled=%s", unit, load, active, props["SubState"], props["UnitFileState"]))
	}
	return platformResult(id, status, strings.Join(parts, "; ")+"; status only; missing/inactive/masked required service blocks operation")
}
func platformFastRPC(c *AutoContext) AutoResult {
	const id = "accel.cdsp-fastrpc"
	paths, err := c.Glob("/dev/fastrpc-*")
	if err != nil {
		return platformBlocked(id, "FastRPC device interface inventory is not readable; CDSP startup remains parked")
	}
	cdsp := 0
	for _, p := range paths {
		if strings.Contains(filepath.Base(p), "cdsp") {
			cdsp++
		}
	}
	if cdsp == 0 {
		return platformBlocked(id, fmt.Sprintf("%d FastRPC interface(s), no CDSP interface exposed; known CDSP support/startup is parked, not evidence of absent compute hardware", len(paths)))
	}
	return platformResult(id, "observed", fmt.Sprintf("%d FastRPC interface(s), %d CDSP interface(s); no device open, DSP query, startup or compute workload", len(paths), cdsp))
}
func platformRTC(c *AutoContext, now time.Time) AutoResult {
	const id = "rtc.read-time"
	paths, err := c.Glob("/sys/class/rtc/rtc*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "RTC time interface is not exposed/readable; power-retention is not tested")
	}
	// rtc0 is the Surface system RTC. A PMIC rtc1 may intentionally be unset.
	system := ""
	for _, p := range paths {
		if filepath.Base(p) == "rtc0" {
			system = p
		}
	}
	if system == "" {
		return platformBlocked(id, "Surface system rtc0 is not exposed; other RTCs do not substitute for its timekeeping")
	}
	epoch, err := platformInt(c, system+"/since_epoch")
	if err != nil {
		return platformBlocked(id, "rtc0 since_epoch is not accessible as a timestamp")
	}
	if epoch < 0 {
		return platformResult(id, "fail", "rtc0 returned a negative RTC epoch")
	}
	delta := now.Sub(time.Unix(epoch, 0))
	if delta < 0 {
		delta = -delta
	}
	status := "pass"
	if delta > platformRTCSlack {
		status = "fail"
	}
	return platformResult(id, status, fmt.Sprintf("Surface rtc0 time read; wall-clock difference=%.0f s (limit 5 s); %d other RTC(s) not compared; no power-off/suspend retention or independence from network time established", delta.Seconds(), len(paths)-1))
}
func platformTPM(c *AutoContext) AutoResult {
	const id = "security.tpm"
	paths, err := c.Glob("/sys/class/tpm/tpm*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "TPM sysfs interface is not exposed/readable; this does not establish hardware absence")
	}
	var versions []string
	for _, p := range paths {
		version, err := c.Read(p + "/tpm_version_major")
		if err != nil {
			return platformBlocked(id, "TPM major-version metadata is not readable")
		}
		versions = append(versions, filepath.Base(p)+" version="+version)
	}
	return platformResult(id, "observed", strings.Join(versions, "; ")+"; metadata only; no keys changed")
}
func platformTPMCapability(c *AutoContext) AutoResult {
	const id = "security.tpm-capability"
	devices, err := c.Glob("/dev/tpm*")
	if err != nil || len(devices) == 0 {
		return platformBlocked(id, "TPM device transport is not exposed/readable; no key changes requested")
	}
	device := ""
	for _, p := range devices {
		if filepath.Base(p) == "tpmrm0" {
			device = p
		}
	}
	if device == "" {
		for _, p := range devices {
			if filepath.Base(p) == "tpm0" {
				device = p
			}
		}
	}
	if device == "" {
		return platformBlocked(id, "No standard TPM0/TPM resource-manager transport exposed")
	}
	text, err := c.Command("tpm2_getcap", "--tcti=device:"+device, "properties-fixed")
	if err != nil {
		if strings.Contains(text, "TPM_RC") || strings.Contains(text, "tpm:parameter") || strings.Contains(text, "tpm:error") {
			return platformResult(id, "fail", "TPM returned an error to the read-only fixed-capability request; no keys changed")
		}
		return platformBlocked(id, "Read-only tpm2_getcap unavailable: tool, device permission or TPM transport required")
	}
	if !regexp.MustCompile(`(?m)^TPM2_PT_FAMILY_INDICATOR:[ \t]*\r?\n[ \t]+raw:[ \t]+0x322[eE]3000[ \t]*\r?$`).MatchString(text) {
		return platformResult(id, "error", "Read-only TPM capability output did not match the expected TPM2 response format; no hardware malfunction inferred or keys changed")
	}
	return platformResult(id, "pass", "TPM2 GetCapability returned fixed properties with family 2.0; no keys, PCRs or firmware settings changed")
}
func platformTPMSigning(c *AutoContext) (result AutoResult) {
	const id = "security.tpm-signing"
	const tcti = "--tcti=device:/dev/tpmrm0"
	const scope = "; only a transient unrestricted signing primary under NULL, public fixed SHA-256 digest and disposable private files; no persistent handles, NV writes, hierarchy/auth changes, PCR extends or owner/endorsement use"
	if c.Fixture || (c.Run == nil && c.Root != "" && filepath.Clean(c.Root) != "/") {
		return platformBlocked(id, "TPM signing disabled for fixture root; no TPM state changed")
	}
	path, err := c.path("/dev/tpmrm0")
	if err != nil || c.withinRoot(path) != nil {
		return platformBlocked(id, "TPM resource-manager device unavailable; no TPM state changed")
	}
	device, err := os.OpenFile(path, os.O_RDWR, 0)
	if err != nil {
		return platformBlocked(id, "/dev/tpmrm0 inaccessible; no TPM state changed")
	}
	device.Close()
	if _, err := c.Command("sh", "-c", "command -v tpm2_getcap >/dev/null && command -v tpm2_createprimary >/dev/null && command -v tpm2_sign >/dev/null && command -v tpm2_verifysignature >/dev/null && command -v tpm2_flushcontext >/dev/null"); err != nil {
		return platformBlocked(id, "Required tpm2-tools unavailable; no TPM state changed")
	}
	algorithms, err := c.Command("tpm2_getcap", tcti, "algorithms")
	if err != nil {
		return platformBlocked(id, "TPM algorithm capability query unavailable; no TPM state changed")
	}
	algorithm := "ecc"
	if !regexp.MustCompile(`(?m)^ecc:[ \t]*\r?$`).MatchString(algorithms) {
		if !regexp.MustCompile(`(?m)^rsa:[ \t]*\r?$`).MatchString(algorithms) {
			return platformBlocked(id, "No ECC/RSA signing algorithm advertised; no TPM state changed")
		}
		algorithm = "rsa"
	}
	dir, err := os.MkdirTemp("", "spx-tpm-sign-*")
	if err != nil {
		return platformResult(id, "error", "Cannot create private TPM signing directory; no TPM state changed")
	}
	defer func() {
		if err := os.RemoveAll(dir); err != nil {
			result.Status = "error"
			result.Detail += "; disposable file cleanup failed"
		}
	}()
	context := filepath.Join(dir, "primary.ctx")
	digestFile := filepath.Join(dir, "digest")
	signature := filepath.Join(dir, "signature")
	digest := sha256.Sum256([]byte("Surface Pro X automatic TPM signing smoke v1"))
	if err := os.WriteFile(digestFile, digest[:], 0600); err != nil {
		return platformResult(id, "error", "Cannot write fixed public digest; no TPM state changed")
	}
	// Linux tpmrm releases each connection's transient objects on close.
	// 5.8 flushcontext accepts handles/session files, not saved object contexts.
	// -t through tpmrm is scoped to this connection, never other clients or tpm0.
	defer func() {
		if _, err := c.Command("tpm2_flushcontext", tcti, "-t"); err != nil {
			result.Status = "error"
			result.Detail += "; resource-manager transient flush failed (device-close cleanup still applies)"
		} else {
			result.Detail += "; resource-manager transient flush succeeded; command connections closed, private files removed"
		}
	}()
	if _, err := c.Command("tpm2_createprimary", tcti, "-C", "n", "-G", algorithm, "-g", "sha256", "-a", "sign|fixedtpm|fixedparent|sensitivedataorigin|userwithauth", "-c", context); err != nil {
		return platformBlocked(id, "NULL-hierarchy signing primary creation refused/unavailable"+scope)
	}
	if _, err := c.Command("tpm2_sign", tcti, "-c", context, "-g", "sha256", "-d", "-f", "tss", "-o", signature, digestFile); err != nil {
		return platformResult(id, "fail", "TPM "+algorithm+" primary created but fixed-digest signing failed"+scope)
	}
	if _, err := c.Command("tpm2_verifysignature", tcti, "-c", context, "-d", digestFile, "-s", signature); err != nil {
		return platformResult(id, "fail", "TPM "+algorithm+" signature created but verification with the same context failed"+scope)
	}
	return platformResult(id, "pass", "TPM "+algorithm+" signed fixed SHA-256 digest and verified signature with the same context"+scope)
}

func platformSecureBoot(c *AutoContext) AutoResult {
	const id = "security.secureboot"
	paths, err := c.Glob("/sys/firmware/efi/efivars/SecureBoot-*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "EFI SecureBoot variable is not exposed/readable; Linux node absence does not establish firmware capability")
	}
	if len(paths) != 1 {
		return platformResult(id, "error", "Ambiguous EFI SecureBoot variables")
	}
	data, err := c.ReadBytes(paths[0])
	if err != nil {
		return platformBlocked(id, "EFI SecureBoot variable read requires access to efivarfs")
	}
	if len(data) != 5 || data[4] > 1 {
		return platformResult(id, "error", "Malformed EFI SecureBoot state variable")
	}
	state := "disabled"
	if data[4] == 1 {
		state = "enabled"
	}
	return platformResult(id, "observed", "EFI SecureBoot="+state+"; state only, not verification of a trusted boot/signing path; no firmware settings changed")
}

func platformThermal(c *AutoContext) AutoResult {
	const id = "thermal.metadata"
	zones, err := c.Glob("/sys/class/thermal/thermal_zone*")
	if err != nil || len(zones) == 0 {
		return platformBlocked(id, "Thermal-zone metadata is not exposed/readable")
	}
	var parts []string
	trips := 0
	status := "observed"
	unavailable := func(detail string) {
		parts = append(parts, detail)
		if status != "fail" {
			status = "blocked"
		}
	}
	for _, p := range zones {
		name, e1 := c.Read(p + "/type")
		temp, e2 := platformInt(c, p+"/temp")
		if e1 != nil || e2 != nil {
			unavailable("thermal type/temperature metadata unavailable")
			continue
		}
		points, err := c.Glob(p + "/trip_point_*_type")
		if err != nil {
			unavailable("thermal trip metadata unreadable")
			continue
		}
		for _, point := range points {
			kind, err := c.Read(point)
			if err != nil {
				unavailable("thermal trip type unreadable")
				continue
			}
			threshold, err := platformInt(c, strings.TrimSuffix(point, "_type")+"_temp")
			if err != nil {
				unavailable("thermal trip temperature unreadable")
				continue
			}
			trips++
			if kind == "critical" && temp >= threshold {
				status = "fail"
			}
		}
		parts = append(parts, fmt.Sprintf("%s=%d mC", name, temp))
	}
	cooling, err := c.Glob("/sys/class/thermal/cooling_device*")
	if err != nil {
		unavailable("cooling-device metadata directory unreadable")
	}
	for _, p := range cooling {
		current, e1 := platformInt(c, p+"/cur_state")
		maximum, e2 := platformInt(c, p+"/max_state")
		if e1 != nil || e2 != nil {
			unavailable("cooling state metadata unreadable")
			continue
		}
		if current < 0 || current > maximum {
			status = "fail"
		}
	}
	evidence := "instantaneous metadata only"
	if status == "fail" {
		evidence = "critical-temperature or invalid cooling-state evidence"
	}
	return platformResult(id, status, fmt.Sprintf("%s; %d trip(s), %d cooling device(s); %s; no load or policy changes; thermal names do not establish compute capability", strings.Join(parts, ", "), trips, len(cooling), evidence))
}
func platformPowerSupplies(c *AutoContext) AutoResult {
	const id = "pwr.supplies"
	paths, err := c.Glob("/sys/class/power_supply/*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "Power-supply class is not exposed/readable; no battery test performed")
	}
	var parts []string
	for _, p := range paths {
		kind, err := c.Read(p + "/type")
		if err != nil {
			return platformBlocked(id, "Power-supply type metadata is not readable")
		}
		if kind == "Battery" {
			status, e1 := c.Read(p + "/status")
			capacity, e2 := platformInt(c, p+"/capacity")
			if e1 != nil || e2 != nil {
				return platformBlocked(id, "Battery status/capacity metadata is not readable")
			}
			parts = append(parts, fmt.Sprintf("Battery status=%s capacity=%d%%", status, capacity))
		} else {
			online, err := platformInt(c, p+"/online")
			if err != nil {
				parts = append(parts, kind+" online attribute unavailable")
				continue
			}
			parts = append(parts, fmt.Sprintf("%s online=%d", kind, online))
		}
	}
	return platformResult(id, "observed", strings.Join(parts, "; ")+"; metadata only; battery/discharge/endurance/charger transitions deferred; no load")
}
func platformPowerSupport(c *AutoContext) AutoResult {
	const id = "pwr.support"
	var parts []string
	for _, name := range []string{"state", "mem_sleep", "disk"} {
		text, err := c.Read("/sys/power/" + name)
		if err != nil {
			return platformBlocked(id, "Power "+name+" interface is not exposed/readable; no suspend/hibernate attempted")
		}
		parts = append(parts, name+"="+text)
	}
	for _, unit := range []string{"sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target", "suspend-then-hibernate.target"} {
		text, err := c.Command("systemctl", "show", unit, "--property=LoadState,UnitFileState", "--no-pager")
		if err != nil {
			return platformBlocked(id, "Sleep unit state query unavailable (systemctl/service-manager access required); no suspend attempted")
		}
		props := map[string]string{}
		for _, line := range strings.Split(text, "\n") {
			pair := strings.SplitN(line, "=", 2)
			if len(pair) == 2 {
				props[pair[0]] = pair[1]
			}
		}
		if props["LoadState"] == "" {
			return platformBlocked(id, "Sleep unit LoadState metadata not available")
		}
		parts = append(parts, fmt.Sprintf("%s load=%s enabled=%s", unit, props["LoadState"], props["UnitFileState"]))
	}
	return platformResult(id, "observed", strings.Join(parts, "; ")+"; masks respected; exposed sleep states do not validate suspend/hibernate; no state changed")
}
func platformWatchdog(c *AutoContext) AutoResult {
	const id = "diag.watchdog"
	paths, err := c.Glob("/sys/class/watchdog/watchdog*")
	if err != nil || len(paths) == 0 {
		return platformBlocked(id, "Watchdog sysfs interface is not exposed/readable; no watchdog device opened")
	}
	var parts []string
	usedFallback := false
	for _, p := range paths {
		identity, err := c.Read(p + "/identity")
		if err == nil && identity != "" {
			parts = append(parts, filepath.Base(p)+" identity="+identity)
			continue
		}
		usedFallback = true
		driver, err := platformReadlink(c, p+"/device/driver")
		if err != nil || filepath.Base(driver) == "." || filepath.Base(driver) == string(filepath.Separator) {
			return platformBlocked(id, "Watchdog identity metadata is not readable and no bound parent driver can be established; no watchdog device opened")
		}
		device, _ := platformReadlink(c, p+"/device")
		deviceName := filepath.Base(device)
		if device == "" {
			deviceName = "unknown"
		}
		compatible, _ := c.Read(p + "/device/of_node/compatible")
		fact := filepath.Base(p) + " driver=" + filepath.Base(driver) + " parent=" + deviceName
		if compatible != "" {
			fact += " compatible=" + strings.ReplaceAll(compatible, " ", ",")
		}
		parts = append(parts, fact)
	}
	detail := strings.Join(parts, "; ")
	if usedFallback {
		detail += "; identity/state/timeout attributes unavailable because the kernel lacks watchdog sysfs attributes; capability inventory only; no device open, arm, reset or recovery test"
	} else {
		detail += "; capability only; no device open, watchdog arm, reset or recovery test"
	}
	return platformResult(id, "observed", detail)
}

func platformReadlink(c *AutoContext, path string) (string, error) {
	p, err := c.path(path)
	if err != nil {
		return "", err
	}
	if err = c.withinRoot(p); err != nil {
		return "", err
	}
	target, err := os.Readlink(p)
	if err != nil {
		return "", err
	}
	linkParent, err := filepath.EvalSymlinks(filepath.Dir(p))
	if err != nil {
		return "", err
	}
	if filepath.IsAbs(target) {
		target = filepath.Join(c.Root, strings.TrimPrefix(target, string(filepath.Separator)))
	} else {
		target = filepath.Join(linkParent, target)
	}
	if err = c.withinRoot(target); err != nil {
		return "", err
	}
	return target, nil
}
func platformBoot(c *AutoContext) AutoResult {
	const id = "diag.boot"
	boot, e1 := c.Read("/proc/sys/kernel/random/boot_id")
	kernel, e2 := c.Read("/proc/sys/kernel/osrelease")
	if e1 != nil || e2 != nil || boot == "" || kernel == "" {
		return platformBlocked(id, "Current boot identity/kernel release is not readable")
	}
	records, err := c.Glob("/sys/fs/pstore/*")
	evidence := fmt.Sprintf("%d retained pstore record(s); prior-boot records are not a current-boot fault verdict", len(records))
	if err != nil {
		evidence = "pstore diagnostic storage is not readable/exposed"
	}
	return platformResult(id, "observed", "Current boot identity available; kernel="+kernel+"; "+evidence+"; no startup/shutdown repeatability test")
}

var platformFaultPatterns = []struct {
	name    string
	pattern *regexp.Regexp
}{
	{"kernel BUG/oops/panic", regexp.MustCompile(`(?i)\b(?:BUG:|Oops:|Kernel panic)`)},
	{"kernel warning", regexp.MustCompile(`(?i)\bWARNING:.*(?: at |CPU:)`)},
	{"I/O error", regexp.MustCompile(`(?i)\b(?:I/O error|Buffer I/O error|blk_update_request:.*error|critical medium error)`)},
	{"NVMe timeout/reset", regexp.MustCompile(`(?i)\bnvme.*(?:I/O.*timeout|controller is down|reset(?:ting)? controller|CSTS=0xffffffff)`)},
	{"filesystem corruption", regexp.MustCompile(`(?i)\b(?:EXT4-fs error|BTRFS.*(?:corrupt|error \(device)|XFS.*(?:corruption|metadata I/O error))`)},
	{"IOMMU fault", regexp.MustCompile(`(?i)\b(?:Unhandled context fault|IOMMU.*(?:fault|translation error)|arm-smmu.*(?:Unhandled|fault))`)},
	{"firmware crash", regexp.MustCompile(`(?i)\b(?:remoteproc.*(?:crash detected|fatal error)|qcom.*(?:fatal error|watchdog bite)|firmware.*(?:crashed|fatal error))`)},
	{"thermal critical event", regexp.MustCompile(`(?i)\b(?:critical temperature reached|thermal.*(?:critical trip|emergency shutdown))`)},
	{"CPU lockup", regexp.MustCompile(`(?i)\b(?:soft lockup|hard LOCKUP|rcu.*(?:stall|stalled))`)},
}

func platformKernelFaults(c *AutoContext) AutoResult {
	const id = "diag.kernel-faults"
	text, err := c.Command("journalctl", "--boot=0", "-k", "-p", "warning", "--no-pager", "--output=cat", "--quiet")
	if err != nil {
		return platformBlocked(id, "Current-boot kernel journal unavailable; journalctl and kernel-log read permission required")
	}
	if len(text) >= 1<<20 {
		return platformBlocked(id, "Current-boot kernel journal reached the command output limit; complete fault evidence is unavailable")
	}
	if strings.Contains(text, "No journal files were found") || strings.Contains(text, "Permission denied") || strings.Contains(text, "not seeing messages from other users") {
		return platformBlocked(id, "Current-boot warning-priority kernel journal unavailable; log visibility is required")
	}
	if strings.TrimSpace(text) == "" || strings.TrimSpace(text) == "-- No entries --" {
		return platformResult(id, "pass", "Current-boot warning-priority kernel journal query completed with no matching entries; lower-priority messages were not scanned; not a load/lifecycle test")
	}
	var parts []string
	for _, category := range platformFaultPatterns {
		count := 0
		for _, line := range strings.Split(text, "\n") {
			if category.pattern.MatchString(line) {
				count++
			}
		}
		if count > 0 {
			parts = append(parts, fmt.Sprintf("%s=%d", category.name, count))
		}
	}
	if len(parts) > 0 {
		return platformResult(id, "fail", "Recognized current-boot warning-priority fault evidence: "+strings.Join(parts, "; ")+"; private log lines omitted")
	}
	return platformResult(id, "pass", "Accessible current-boot warning-priority kernel journal scanned; no recognized BUG/oops/panic, warning, storage, IOMMU, firmware, critical thermal or lockup signatures; lower-priority messages not scanned; not a load/lifecycle test")
}
func platformFailedUnits(c *AutoContext) AutoResult {
	const id = "diag.failed-units"
	text, err := c.Command("systemctl", "list-units", "--state=failed", "--no-legend", "--no-pager", "--plain")
	if err != nil {
		return platformBlocked(id, "systemd failed-unit query unavailable; systemctl/service-manager access required")
	}
	count, excluded := 0, 0
	for _, line := range strings.Split(text, "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		if len(fields) < 4 || fields[2] != "failed" {
			return platformBlocked(id, "systemd failed-unit response was not a recognized unit row")
		}
		if fields[0] == "spx-hw-validation.service" {
			excluded++
			continue
		}
		count++
	}
	status := "pass"
	if count > 0 {
		status = "fail"
	}
	return platformResult(id, status, fmt.Sprintf("%d failed system unit(s), excluding %d prior validator unit(s); private unit names/logs omitted; not user-service or repeat-startup validation", count, excluded))
}
func platformTaint(c *AutoContext) AutoResult {
	const id = "diag.taint"
	value, err := platformInt(c, "/proc/sys/kernel/tainted")
	if err != nil || value < 0 {
		return platformBlocked(id, "Kernel taint bitmask is not readable as a nonnegative integer")
	}
	return platformResult(id, "observed", fmt.Sprintf("kernel taint bitmask=%d (0x%x); taint is context, not a functional pass/fault verdict", value, value))
}
