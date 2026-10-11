// hw-validation inventories read-only interfaces; it never grants acceptance.
package main

import (
	"compress/gzip"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

type Box struct {
	ID         string   `json:"id"`
	Closed     bool     `json:"closed"`
	Acceptance string   `json:"acceptance"`
	Probes     []string `json:"probes"`
}
type Probe struct {
	ID     string   `json:"id"`
	Boxes  []string `json:"boxes"`
	State  string   `json:"state"`
	Detail string   `json:"detail"`
}
type Meta struct {
	Kernel    string `json:"kernel"`
	BootID    string `json:"boot_id"`
	Date      string `json:"date"`
	Repo      string `json:"repo"`
	Checklist string `json:"checklist"`
}
type Report struct {
	Meta   Meta    `json:"meta"`
	Closed int     `json:"closed"`
	Total  int     `json:"total"`
	Boxes  []Box   `json:"boxes"`
	Probes []Probe `json:"probes"`
}

var frozenIDs = strings.Fields("B01 B02 B03 B04 B05 B06 B07 D01 D02 D03 I01 I02 I03 I04 I05 I06 I07 A01 A02 A03 A04 N01 N02 N03 N04 U01 U02 U03 U04 C01 C02 C03 C04 C05 S01 S02 P01 P02 P03 P04 P05 R01 R02 F01 F02 F03 F04")
var boxStart = regexp.MustCompile(`^- \[([ x])\] \*\*([A-Z][0-9]{2}) — (.*?)\*\*(.*)$`)

func checklist(text string) ([]Box, error) {
	var boxes []Box
	var body []string
	notes := false
	flush := func() {
		if len(boxes) > 0 && body != nil {
			boxes[len(boxes)-1].Acceptance = strings.Join(strings.Fields(strings.Join(body, " ")), " ")
		}
		body = nil
		notes = false
	}
	for _, line := range strings.Split(text, "\n") {
		m := boxStart.FindStringSubmatch(line)
		if m != nil {
			flush()
			boxes = append(boxes, Box{ID: m[2], Closed: m[1] == "x", Probes: []string{}})
			body = []string{m[3], m[4]}
		} else if strings.HasPrefix(line, "## ") {
			flush()
		} else if strings.HasPrefix(line, "- [") {
			return nil, fmt.Errorf("invalid checklist row: %s", line)
		} else if body != nil {
			if strings.Contains(line, "*Notes, not acceptance:") {
				notes = true
			}
			if !notes {
				body = append(body, line)
			}
		}
	}
	flush()
	if len(boxes) != len(frozenIDs) {
		return nil, fmt.Errorf("expected frozen 47 boxes, got %d", len(boxes))
	}
	for i, b := range boxes {
		if b.ID != frozenIDs[i] || b.Acceptance == "" {
			return nil, fmt.Errorf("invalid frozen checklist at row %d: %s", i+1, b.ID)
		}
	}
	return boxes, nil
}

type node struct {
	text string
	err  error
}
type Inventory struct {
	root  string
	cache map[string]node
	run   func(...string) (string, error)
}

func newInventory(root string, run func(...string) (string, error)) *Inventory {
	return &Inventory{root: root, cache: map[string]node{}, run: run}
}
func (v *Inventory) path(p string) string { return filepath.Join(v.root, strings.TrimPrefix(p, "/")) }
func (v *Inventory) read(p string) node {
	if n, ok := v.cache[p]; ok {
		return n
	}
	b, err := os.ReadFile(v.path(p))
	n := node{strings.TrimSpace(strings.ReplaceAll(string(b), "\x00", " ")), err}
	v.cache[p] = n
	return n
}

// Directory enumeration is restricted to interface names. Device files are never opened.
func (v *Inventory) glob(pattern string) ([]string, error) {
	parent := filepath.Dir(pattern)
	if strings.ContainsAny(parent, "*?[") {
		return nil, errors.New("wildcards allowed only in basename")
	}
	entries, err := os.ReadDir(v.path(parent))
	if err != nil {
		return nil, err
	}
	var paths []string
	for _, e := range entries {
		ok, err := filepath.Match(filepath.Base(pattern), e.Name())
		if err != nil {
			return nil, err
		}
		if ok {
			paths = append(paths, filepath.Join(parent, e.Name()))
		}
	}
	sort.Strings(paths)
	return paths, nil
}

var mac = regexp.MustCompile(`(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b`)

func redact(s string) string { return mac.ReplaceAllString(s, "[address omitted]") }
func observation(id, boxes string, parts []string, err error) Probe {
	p := Probe{ID: id, Boxes: strings.Split(boxes, ","), State: "observed", Detail: redact(strings.Join(parts, "; "))}
	if err != nil {
		p.State = "unknown"
		p.Detail += "; " + err.Error()
	}
	if len(parts) == 0 {
		p.State = "unknown"
		p.Detail = "No matching exposed interface; this does not establish hardware absence"
		if err != nil {
			p.Detail += "; " + err.Error()
		}
	}
	return p
}
func (v *Inventory) files(id, boxes string, paths ...string) Probe {
	var parts []string
	var errs []error
	for _, p := range paths {
		n := v.read(p)
		if n.err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", p, n.err))
			continue
		}
		parts = append(parts, p+"="+n.text)
	}
	return observation(id, boxes, parts, errors.Join(errs...))
}
func (v *Inventory) names(id, boxes, pattern string, attrs ...string) Probe {
	paths, err := v.glob(pattern)
	var parts []string
	errs := []error{err}
	for _, p := range paths {
		if strings.HasPrefix(p, "/sys/bus/usb/devices/") && strings.Contains(filepath.Base(p), ":") {
			continue
		}
		parts = append(parts, p)
		for _, a := range attrs {
			n := v.read(filepath.Join(p, a))
			if n.err != nil {
				errs = append(errs, fmt.Errorf("%s/%s: %w", p, a, n.err))
			} else {
				parts = append(parts, filepath.Base(p)+"/"+a+"="+n.text)
			}
		}
	}
	return observation(id, boxes, parts, errors.Join(errs...))
}
func (v *Inventory) services(id, boxes string, user bool, units ...string) Probe {
	var parts []string
	var errs []error
	for _, unit := range units {
		args := []string{"systemctl"}
		if user {
			args = append(args, "--user")
		}
		args = append(args, "show", unit, "--property=LoadState,ActiveState,SubState,UnitFileState", "--no-pager")
		output, err := v.run(args...)
		if err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", unit, err))
			continue
		}
		if !strings.Contains(output, "ActiveState=") {
			errs = append(errs, fmt.Errorf("%s: no service status", unit))
			continue
		}
		parts = append(parts, unit+": "+strings.TrimSpace(output))
	}
	p := observation(id, boxes, parts, errors.Join(errs...))
	if p.State == "observed" && (strings.Contains(p.Detail, "ActiveState=inactive") || strings.Contains(p.Detail, "ActiveState=failed") || strings.Contains(p.Detail, "LoadState=not-found") || strings.Contains(p.Detail, "UnitFileState=masked")) {
		p.State = "needs investigation"
	}
	return p
}
func (v *Inventory) config() Probe {
	flags := strings.Fields("QCOM_IPA WWAN QCOM_FASTRPC TYPEC_DP_ALTMODE SURFACE_AGGREGATOR_USBC VIDEO_QCOM_VENUS VIDEO_QCOM_CAMSS")
	f, err := os.Open(v.path("/proc/config.gz"))
	if err != nil {
		return observation("kernel.config", "N03,B07,U03,D03,C01,F02", nil, err)
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return observation("kernel.config", "N03,B07,U03,D03,C01,F02", nil, err)
	}
	defer gz.Close()
	b, err := io.ReadAll(gz)
	if err != nil {
		return observation("kernel.config", "N03,B07,U03,D03,C01,F02", nil, err)
	}
	values := map[string]string{}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "CONFIG_") {
			pair := strings.SplitN(line, "=", 2)
			if len(pair) == 2 {
				values[pair[0]] = pair[1]
			}
		}
		if strings.HasPrefix(line, "# CONFIG_") && strings.HasSuffix(line, " is not set") {
			values[strings.TrimSuffix(strings.TrimPrefix(line, "# "), " is not set")] = "not set"
		}
	}
	var parts []string
	var errs []error
	for _, flag := range flags {
		key := "CONFIG_" + flag
		if value, ok := values[key]; ok {
			parts = append(parts, key+"="+value)
		} else {
			errs = append(errs, fmt.Errorf("%s not recorded in running config", key))
		}
	}
	p := observation("kernel.config", "N03,B07,U03,D03,C01,F02", parts, errors.Join(errs...))
	if p.State == "observed" && strings.Contains(p.Detail, "=not set") {
		p.State = "needs investigation"
	}
	p.Detail += "; Disabled config is evidence of missing kernel support, not hardware absence; y/m does not verify operation"
	return p
}
func (v *Inventory) iio() Probe {
	paths, err := v.glob("/sys/bus/iio/devices/iio:device*")
	var parts []string
	errs := []error{err}
	for _, p := range paths {
		n := v.read(p + "/name")
		if n.err != nil {
			errs = append(errs, n.err)
		} else {
			parts = append(parts, filepath.Base(p)+" name="+n.text)
		}
		// List channel filenames only: never read *_raw, *_input or other sensor values.
		entries, e := os.ReadDir(v.path(p))
		if e != nil {
			errs = append(errs, e)
			continue
		}
		var channels []string
		for _, entry := range entries {
			if strings.HasPrefix(entry.Name(), "in_") {
				channels = append(channels, entry.Name())
			}
		}
		parts = append(parts, filepath.Base(p)+" channel filenames="+strings.Join(channels, ","))
	}
	return observation("sens.iio", "S01,S02", parts, errors.Join(errs...))
}
func (v *Inventory) inputNames() Probe {
	n := v.read("/proc/bus/input/devices")
	var parts []string
	re := regexp.MustCompile(`(?m)^N: Name="(.*)"$`)
	for _, m := range re.FindAllStringSubmatch(n.text, -1) {
		parts = append(parts, m[1])
	}
	return observation("in.names", "I01,I02,I03,I04,I05,I06,I07", parts, n.err)
}
func (v *Inventory) memTotal() Probe {
	n := v.read("/proc/meminfo")
	var parts []string
	for _, line := range strings.Split(n.text, "\n") {
		if strings.HasPrefix(line, "MemTotal:") {
			parts = append(parts, line)
		}
	}
	return observation("mem.total", "B03", parts, n.err)
}
func (v *Inventory) cmdline() Probe {
	n := v.read("/proc/cmdline")
	var parts []string
	for _, arg := range strings.Fields(n.text) {
		key := strings.SplitN(arg, "=", 2)[0]
		if strings.HasPrefix(key, "rd.luks") || key == "root" || strings.Contains(strings.ToLower(key), "uuid") || strings.Contains(strings.ToLower(key), "password") {
			parts = append(parts, key+"=[identifier omitted]")
		} else {
			parts = append(parts, arg)
		}
	}
	return observation("diag.cmdline", "B04,P02,F02", parts, n.err)
}
func (v *Inventory) matching(id, boxes, pattern, attr, match string) Probe {
	paths, err := v.glob(pattern)
	var parts []string
	errs := []error{err}
	for _, p := range paths {
		name := filepath.Base(p)
		if attr != "" {
			n := v.read(p + "/" + attr)
			if n.err != nil {
				errs = append(errs, n.err)
				continue
			}
			name = n.text
		}
		if strings.Contains(strings.ToLower(name), match) {
			parts = append(parts, p+"="+name)
		}
	}
	return observation(id, boxes, parts, errors.Join(errs...))
}
func (v *Inventory) collect() []Probe {
	return []Probe{
		v.files("plat.model", "F01", "/sys/firmware/devicetree/base/model"),
		v.files("cpu.cores", "B03", "/sys/devices/system/cpu/online", "/sys/devices/system/cpu/present"),
		v.names("cpu.freq", "B03,P02", "/sys/devices/system/cpu/cpufreq/policy*", "scaling_governor", "scaling_min_freq", "scaling_max_freq", "cpuinfo_max_freq"),
		v.memTotal(),
		v.names("storage.nvme", "B02", "/sys/class/nvme/nvme*", "model"),
		v.names("fw.remoteproc", "B04", "/sys/class/remoteproc/remoteproc*", "name", "state"),
		v.services("fw.services", "B04", false, "pd-mapper.service", "rmtfs.service", "tqftpserv.service"),
		v.names("rtc.names", "B05", "/sys/class/rtc/rtc*", "name"),
		v.names("tpm.present", "B06", "/sys/class/tpm/tpm*", "tpm_version_major"),
		v.names("tpm.secureboot", "B06", "/sys/firmware/efi/efivars/SecureBoot-*"),
		v.matching("accel.cdsp", "B07", "/dev/fastrpc-*", "", "cdsp"),
		v.names("disp.drm", "D01,D02,U03", "/sys/class/drm/card*-*", "status", "enabled", "modes"),
		v.names("disp.backlight", "D01", "/sys/class/backlight/*", "brightness", "max_brightness"),
		v.names("gpu.devfreq", "D02,P02", "/sys/class/devfreq/*", "governor"),
		v.names("video.names", "D03,C01,C02,C03,C04,C05", "/sys/class/video4linux/video*", "name"),
		v.names("camera.subdevices", "C01,C02,C03,C04,C05", "/sys/class/video4linux/v4l-subdev*", "name"),
		v.names("media.nodes", "C01,C02,C03,C04,C05", "/dev/media*"),
		v.inputNames(),
		v.names("led.names", "I04,C05", "/sys/class/leds/*"),
		v.files("aud.card", "A01,A02,A03,A04", "/proc/asound/cards", "/proc/asound/pcm"),
		v.names("aud.amps", "A01,A03", "/sys/bus/soundwire/devices/*"),
		v.services("aud.desktop", "A03,A04", true, "pipewire.service", "wireplumber.service"),
		v.services("aud.feeder", "A01,A03", false, "spx-desktop-playback.service"),
		v.names("net.interfaces", "N01,N03,U04", "/sys/class/net/*", "operstate"),
		v.names("net.bt", "N02,A04", "/sys/class/bluetooth/*"),
		v.names("net.wwan", "N03", "/sys/class/wwan/*"),
		v.names("net.gnss", "N04", "/sys/class/gnss/*"),
		v.names("usb.devices", "U01,U04,A04", "/sys/bus/usb/devices/*", "speed"),
		v.names("usb.typec", "U02,U03", "/sys/class/typec/port*"),
		v.names("usb.roles", "U02", "/sys/class/usb_role/*", "role"),
		v.iio(),
		v.matching("sens.als", "S01", "/sys/bus/iio/devices/iio:device*", "name", "tcs3430"),
		v.matching("video.decoder", "D03", "/sys/class/video4linux/video*", "name", "decoder"),
		v.matching("video.encoder", "D03", "/sys/class/video4linux/video*", "name", "encoder"),
		v.services("sens.desktop", "S01,S02", false, "iio-sensor-proxy.service"),
		v.files("pwr.states", "P03,P04", "/sys/power/state", "/sys/power/mem_sleep", "/sys/power/disk"),
		v.services("pwr.sleep_units", "P03,P04", false, "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target", "suspend-then-hibernate.target"),
		v.names("pwr.idle", "P02", "/sys/devices/system/cpu/cpu0/cpuidle/state*", "name", "disable"),
		v.names("diag.pstore", "R01", "/sys/fs/pstore/*"),
		v.names("diag.watchdog", "R02", "/sys/class/watchdog/watchdog*", "identity"),
		v.files("diag.taint", "R01,F02", "/proc/sys/kernel/tainted"),
		v.cmdline(),
		v.config(),
	}
}
func assemble(boxes []Box, probes []Probe, meta Meta) (Report, error) {
	r := Report{Meta: meta, Total: len(boxes), Boxes: boxes, Probes: probes}
	valid := map[string]int{}
	for i, b := range boxes {
		valid[b.ID] = i
		if b.Closed {
			r.Closed++
		}
	}
	for _, p := range probes {
		for _, id := range p.Boxes {
			i, ok := valid[id]
			if !ok {
				return r, fmt.Errorf("unknown box %s", id)
			}
			r.Boxes[i].Probes = append(r.Boxes[i].Probes, p.ID)
		}
	}
	return r, nil
}
func cell(s string) string { return strings.ReplaceAll(strings.ReplaceAll(s, "|", "/"), "\n", " ") }
func markdown(r Report) string {
	var b strings.Builder
	fmt.Fprintf(&b, "boxes closed: %d of %d; newly closed: none.\n\n# Surface Pro X hardware gaps\n\nKernel: `%s`; boot: `%s`; date: %s\n\n", r.Closed, r.Total, r.Meta.Kernel, r.Meta.BootID, r.Meta.Date)
	b.WriteString("Interface observations are not functional acceptance. Checklist closures are historical and are not revalidated by this inventory. Missing nodes, tools or permissions mean unknown, not hardware absence. Disabled running-kernel config can identify missing kernel support; enabled config does not prove functionality.\n\nNo sound, capture, media ioctls, EGL, raw sensors, thermal load, battery tests, sleep, module changes or boot changes are performed. Battery testing remains deferred. Follow TODO.md for blocker order.\n\n## Findings needing investigation\n\n| Probe | Boxes | State | Detail |\n|---|---|---|---|\n")
	for _, p := range r.Probes {
		if p.State != "observed" {
			fmt.Fprintf(&b, "| %s | %s | %s | %s |\n", p.ID, strings.Join(p.Boxes, ", "), p.State, cell(p.Detail))
		}
	}
	b.WriteString("\n## Remaining acceptance (full frozen checklist requirements)\n\nThese requirements remain unmet or unverified even when an interface is observed. Physical actions, fixtures and lifecycle evidence cannot be replaced by inventory.\n\n")
	for _, box := range r.Boxes {
		if !box.Closed {
			coverage := strings.Join(box.Probes, ", ")
			if coverage == "" {
				coverage = "none; not automatically checked"
			}
			fmt.Fprintf(&b, "### %s\n%s\n\nInventory probes: %s\n\n", box.ID, box.Acceptance, coverage)
		}
	}
	b.WriteString("## All interface observations\n\n| Probe | State | Detail |\n|---|---|---|\n")
	for _, p := range r.Probes {
		fmt.Fprintf(&b, "| %s | %s | %s |\n", p.ID, p.State, cell(p.Detail))
	}
	return b.String()
}
func command(args ...string) (string, error) {
	cmd := exec.Command(args[0], args[1:]...)
	// systemctl is only used for status queries, never state changes.
	output, err := cmd.CombinedOutput()
	return string(output), err
}
func reportPaths(base string) (string, string) {
	ext := filepath.Ext(base)
	if ext == ".md" || ext == ".json" {
		base = strings.TrimSuffix(base, ext)
	}
	return base + ".md", base + ".json"
}
func live(repo, checkpath, output string) (err error) {
	text, err := os.ReadFile(checkpath)
	if err != nil {
		return err
	}
	boxes, err := checklist(string(text))
	if err != nil {
		return err
	}
	lock := filepath.Join(repo, "tools/spx/spx-lock")
	owner := fmt.Sprintf("hw-validation-go-%d", os.Getpid())
	if out, e := command(lock, "acquire", "device", owner); e != nil {
		return fmt.Errorf("device lock: %w: %s", e, out)
	}
	defer func() {
		out, e := command(lock, "release", "device", owner)
		if e != nil {
			err = errors.Join(err, fmt.Errorf("release device lock: %w: %s", e, out))
		}
	}()
	v := newInventory("/", command)
	boot := v.read("/proc/sys/kernel/random/boot_id")
	kernel := v.read("/proc/sys/kernel/osrelease")
	if boot.err != nil || kernel.err != nil || boot.text == "" || kernel.text == "" {
		return fmt.Errorf("cannot bind report to boot/kernel: %w", errors.Join(boot.err, kernel.err))
	}
	probes := v.collect()
	// Do not reuse the cache for the final identity check.
	after, e := os.ReadFile("/proc/sys/kernel/random/boot_id")
	if e != nil {
		return e
	}
	if strings.TrimSpace(string(after)) != boot.text {
		return errors.New("boot changed during inventory; discard mixed evidence")
	}
	r, e := assemble(boxes, probes, Meta{kernel.text, boot.text, time.Now().Format(time.RFC3339), repo, checkpath})
	if e != nil {
		return e
	}
	data, e := json.MarshalIndent(r, "", "  ")
	if e != nil {
		return e
	}
	md, j := reportPaths(output)
	if e = os.MkdirAll(filepath.Dir(md), 0755); e != nil {
		return e
	}
	if e = os.WriteFile(md, []byte(markdown(r)), 0644); e != nil {
		return e
	}
	if e = os.WriteFile(j, append(data, '\n'), 0644); e != nil {
		return e
	}
	fmt.Printf("boxes closed: %d of %d; newly closed: none.\nreport: %s\nreport: %s\n", r.Closed, r.Total, md, j)
	return nil
}
func main() {
	repo := flag.String("repo", ".", "repository root (default current working directory)")
	check := flag.String("checklist", "", "checklist path (default <repo>/PORT-CHECKLIST.md)")
	output := flag.String("output", "", "required report basename; writes .md and .json")
	flag.Parse()
	if flag.NArg() != 0 || *output == "" {
		fmt.Fprintln(os.Stderr, "usage: hw-validation --repo PATH [--checklist PATH] --output BASENAME")
		os.Exit(2)
	}
	abs, e := filepath.Abs(*repo)
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	checkpath := *check
	if checkpath == "" {
		checkpath = filepath.Join(abs, "PORT-CHECKLIST.md")
	}
	checkpath, e = filepath.Abs(checkpath)
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	if e = live(abs, checkpath, *output); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
