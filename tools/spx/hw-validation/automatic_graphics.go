package main

import (
	"encoding/binary"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"image/png"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

func automaticGraphicsChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "graphics.display.internal", Title: "Internal connector modes and preferred timing", Area: "Graphics", Kind: "inventory", Boxes: []string{"D01"}, Run: func(c *AutoContext) AutoResult { return graphicsDisplays(c, true) }},
		{ID: "graphics.display.external", Title: "Connected external display modes and preferred timing", Area: "Graphics", Kind: "inventory", Boxes: []string{"U03"}, Run: func(c *AutoContext) AutoResult { return graphicsDisplays(c, false) }},
		{ID: "graphics.display.internal.scanout", Title: "Current internal native scanout and advancing vblank", Area: "Graphics", Kind: "functional", Boxes: []string{"D01"}, Run: func(c *AutoContext) AutoResult { return graphicsScanout(c, true) }},
		{ID: "graphics.display.external.scanout", Title: "Current external scanout and advancing vblank", Area: "Graphics", Kind: "functional", Boxes: []string{"U03"}, Run: func(c *AutoContext) AutoResult { return graphicsScanout(c, false) }},
		{ID: "graphics.backlight", Title: "Backlight metadata without changing brightness", Area: "Graphics", Kind: "inventory", Boxes: []string{"D01"}, Run: graphicsBacklight},
		{ID: "graphics.egl", Title: "Surfaceless EGL hardware GL/GLES contexts", Area: "Graphics", Kind: "inventory", Boxes: []string{"D02"}, Run: graphicsEGL},
		{ID: "graphics.vulkan.devices", Title: "Vulkan hardware device and API inventory", Area: "Graphics", Kind: "inventory", Boxes: []string{"D02"}, Run: graphicsVulkanDevices},
		{ID: "graphics.gl.render", Title: "Offscreen GL expected-image smoke", Area: "Graphics", Kind: "functional", Boxes: []string{"D02"}, Run: func(c *AutoContext) AutoResult { return graphicsGLRender(c, false) }},
		{ID: "graphics.gles.render", Title: "Offscreen GLES expected-image smoke", Area: "Graphics", Kind: "functional", Boxes: []string{"D02"}, Run: func(c *AutoContext) AutoResult { return graphicsGLRender(c, true) }},
		{ID: "graphics.vulkan.render", Title: "Windowless Vulkan static render and pixel readback", Area: "Graphics", Kind: "functional", Boxes: []string{"D02"}, Run: graphicsVulkanRender},
		{ID: "graphics.vulkan.dynamic-damage", Title: "Vulkan scrolling and partial-damage corruption regression", Area: "Graphics", Kind: "functional", Boxes: []string{"D02"}, Run: func(*AutoContext) AutoResult {
			return graphicsResult("graphics.vulkan.dynamic-damage", "blocked", "Recorded Vulkan GMEM scrolling corruption is unresolved; TU_DEBUG=sysmem is a workaround, not a fix. No safe windowless reproducer for that workload is available; a static render does not cover it")
		}},
	}
}

func graphicsResult(id, status, detail string) AutoResult {
	return AutoResult{ID: id, Status: status, Detail: detail}
}

var graphicsMode = regexp.MustCompile(`^[0-9]{2,5}x[0-9]{2,5}$`)

func graphicsDisplays(c *AutoContext, internal bool) AutoResult {
	id, scope := "graphics.display.external", "external"
	if internal {
		id, scope = "graphics.display.internal", "internal"
	}
	paths, err := c.Glob("/sys/class/drm/card*-*")
	if err != nil {
		return graphicsResult(id, "blocked", "DRM connector metadata unavailable: "+err.Error())
	}
	var parts []string
	connected, disconnected, matched := 0, 0, 0
	for _, path := range paths {
		name := filepath.Base(path)
		connector := strings.SplitN(name, "-", 2)
		if len(connector) != 2 {
			continue
		}
		isInternal := strings.HasPrefix(connector[1], "eDP-") || strings.HasPrefix(connector[1], "LVDS-") || strings.HasPrefix(connector[1], "DSI-")
		if isInternal != internal {
			continue
		}
		matched++
		status, readErr := c.Read(path + "/status")
		if readErr != nil {
			return graphicsResult(id, "blocked", name+" status unavailable: "+readErr.Error())
		}
		if status != "connected" {
			disconnected++
			continue
		}
		connected++
		modesText, readErr := c.Read(path + "/modes")
		if readErr != nil {
			return graphicsResult(id, "blocked", name+" mode metadata unavailable: "+readErr.Error())
		}
		var modes []string
		for _, mode := range strings.Fields(modesText) {
			if graphicsMode.MatchString(mode) {
				modes = append(modes, mode)
			}
		}
		if len(modes) == 0 {
			return graphicsResult(id, "blocked", name+" is connected but exposes no usable mode metadata; driver/EDID support is needed")
		}
		edid, readErr := c.ReadBytes(path + "/edid")
		if readErr != nil {
			return graphicsResult(id, "blocked", name+" modes="+strings.Join(modes, ",")+"; preferred timing unavailable: "+readErr.Error())
		}
		timing, timingErr := graphicsPreferredTiming(edid)
		if timingErr != nil {
			return graphicsResult(id, "blocked", name+" modes="+strings.Join(modes, ",")+"; "+timingErr.Error())
		}
		enabled, readErr := c.Read(path + "/enabled")
		if readErr != nil {
			return graphicsResult(id, "blocked", name+" enabled metadata unavailable: "+readErr.Error())
		}
		if enabled != "enabled" && enabled != "disabled" {
			return graphicsResult(id, "blocked", name+" has unrecognized enabled metadata")
		}
		parts = append(parts, name+" connected, "+enabled+", modes="+strings.Join(modes, ",")+", EDID preferred="+timing)
	}
	if connected == 0 {
		return graphicsResult(id, "blocked", fmt.Sprintf("No connected %s display fixture exposed (%d connectors, %d disconnected/unknown); this does not establish hardware absence", scope, matched, disconnected))
	}
	return graphicsResult(id, "observed", strings.Join(parts, "; ")+"; advertised timing only, not active scanout, image quality, hotplug or resume")
}

// EDID binary identifiers never leave this function: only its preferred timing does.
func graphicsPreferredTiming(edid []byte) (string, error) {
	if len(edid) < 128 || string(edid[:8]) != "\x00\xff\xff\xff\xff\xff\xff\x00" {
		return "", errors.New("valid EDID base block needed for native/preferred timing")
	}
	var sum byte
	for _, b := range edid[:128] {
		sum += b
	}
	if sum != 0 {
		return "", errors.New("EDID base checksum is invalid; native/preferred timing not established")
	}
	if edid[24]&2 == 0 {
		return "", errors.New("EDID does not mark a preferred detailed timing; native mode not established")
	}
	d := edid[54:72]
	clock := int(binary.LittleEndian.Uint16(d[:2])) * 10000
	hActive, hBlank := int(d[2])+(int(d[4]&0xf0)<<4), int(d[3])+(int(d[4]&0x0f)<<8)
	vActive, vBlank := int(d[5])+(int(d[7]&0xf0)<<4), int(d[6])+(int(d[7]&0x0f)<<8)
	if clock == 0 || hActive == 0 || vActive == 0 || hBlank == 0 || vBlank == 0 || d[17]&0x80 != 0 {
		return "", errors.New("unsupported/missing preferred detailed timing; no native refresh inferred")
	}
	hz := float64(clock) / float64((hActive+hBlank)*(vActive+vBlank))
	return fmt.Sprintf("%dx%d@%.2fHz", hActive, vActive, hz), nil
}

// This is the existing trial.py read-only WAIT_VBLANK observer, not its
// display-power test. The kernel bounds each relative wait; Command also has
// a process deadline. No DRM master, modeset or framebuffer changes occur.
const graphicsVblankObserver = `import errno, fcntl, json, os, struct, sys
try:
    fd = os.open(sys.argv[1], os.O_RDWR | os.O_CLOEXEC)
    rows = []
    try:
        for _ in range(2):
            buf = bytearray(struct.pack('=IIQQ', 1 | (int(sys.argv[2]) << 1), 1, 0, 0))
            fcntl.ioctl(fd, 0xc018643a, buf, True)
            _, seq, sec, usec = struct.unpack('=IIqq', buf)
            rows.append((seq, sec * 1000000 + usec))
    finally:
        os.close(fd)
    print(json.dumps({'sequences': [r[0] for r in rows], 'timestamps_us': [r[1] for r in rows]}))
except OSError as e:
    status = 'blocked' if e.errno in (errno.ENOENT, errno.EACCES, errno.EPERM, errno.ENOTTY, errno.EINVAL) else 'fail'
    print(json.dumps({'status': status, 'errno': e.errno}))
`

var graphicsDRMBlock = regexp.MustCompile(`(?m)^(?:plane|crtc|connector)\[[0-9]+\]:`)
var graphicsCRTCHead = regexp.MustCompile(`^crtc\[[0-9]+\]: crtc-([0-9]+)\n`)
var graphicsConnectorHead = regexp.MustCompile(`^connector\[[0-9]+\]: ([^\n]+)\n\s*crtc=crtc-([0-9]+)`)
var graphicsPlaneRoute = regexp.MustCompile(`^plane\[[0-9]+\]: [^\n]+\n\s*crtc=crtc-([0-9]+)\n\s*fb=([0-9]+)`)
var graphicsCurrentMode = regexp.MustCompile(`(?m)^\s*mode: "([0-9]+x[0-9]+)": ([0-9]+)\b`)

func graphicsScanout(c *AutoContext, internal bool) AutoResult {
	id, scope := "graphics.display.external.scanout", "external"
	if internal {
		id, scope = "graphics.display.internal.scanout", "internal"
	}
	paths, err := c.Glob("/sys/class/drm/card*-*")
	if err != nil {
		return graphicsResult(id, "blocked", "DRM connector metadata/permissions needed for current "+scope+" scanout")
	}
	var witnessed []string
	for _, path := range paths {
		pair := strings.SplitN(filepath.Base(path), "-", 2)
		if len(pair) != 2 {
			continue
		}
		isInternal := strings.HasPrefix(pair[1], "eDP-") || strings.HasPrefix(pair[1], "LVDS-") || strings.HasPrefix(pair[1], "DSI-")
		if isInternal != internal {
			continue
		}
		status, err := c.Read(path + "/status")
		if err != nil {
			return graphicsResult(id, "blocked", "Connector status unavailable for "+scope+" scanout")
		}
		if status != "connected" {
			continue
		}
		enabled, err := c.Read(path + "/enabled")
		if err != nil || enabled != "enabled" {
			return graphicsResult(id, "blocked", "Connected "+scope+" display is not currently enabled; no power/mode changes requested")
		}
		state, err := c.Read("/sys/kernel/debug/dri/" + strings.TrimPrefix(pair[0], "card") + "/state")
		if err != nil {
			return graphicsResult(id, "blocked", "Read-only DRM atomic state/debugfs permissions needed for scanout witness")
		}
		starts := graphicsDRMBlock.FindAllStringIndex(state, -1)
		var blocks []string
		for i, start := range starts {
			end := len(state)
			if i+1 < len(starts) {
				end = starts[i+1][0]
			}
			blocks = append(blocks, state[start[0]:end])
		}
		crtcs, routes, framebuffers := map[string]string{}, map[string]string{}, map[string]bool{}
		for _, block := range blocks {
			if m := graphicsCRTCHead.FindStringSubmatch(block); m != nil {
				crtcs[m[1]] = block
			}
			if m := graphicsConnectorHead.FindStringSubmatch(block); m != nil {
				routes[m[1]] = m[2]
			}
			if m := graphicsPlaneRoute.FindStringSubmatch(block); m != nil && m[2] != "0" {
				framebuffers[m[1]] = true
			}
		}
		crtc, ok := routes[pair[1]]
		if !ok {
			return graphicsResult(id, "blocked", "Connected display lacks a recognized CRTC route; active scanout not established")
		}
		block := crtcs[crtc]
		if !regexp.MustCompile(`(?m)^\s*enable=1$`).MatchString(block) || !regexp.MustCompile(`(?m)^\s*active=1$`).MatchString(block) || !framebuffers[crtc] {
			return graphicsResult(id, "fail", "Enabled "+scope+" display has no active CRTC framebuffer")
		}
		mode := graphicsCurrentMode.FindStringSubmatch(block)
		if mode == nil {
			return graphicsResult(id, "blocked", "Current scanout mode format is not recognized")
		}
		if internal && (mode[1] != "2880x1920" || mode[2] != "60") {
			return graphicsResult(id, "blocked", "Internal scanout is not currently using the recorded native 2880x1920@60Hz mode; no modeset requested")
		}
		out, err := c.Command("python3", "-c", graphicsVblankObserver, "/dev/dri/"+pair[0], crtc)
		if err != nil {
			return graphicsCommandIssue(id, "Current "+scope+" vblank observer", out, err)
		}
		var sample struct {
			Sequences  []uint32 `json:"sequences"`
			Timestamps []int64  `json:"timestamps_us"`
			Status     string   `json:"status"`
			Errno      int      `json:"errno"`
		}
		if err := json.Unmarshal([]byte(out), &sample); err != nil {
			return graphicsResult(id, "blocked", "Vblank observer returned no recognized sample")
		}
		if sample.Status == "blocked" {
			return graphicsResult(id, "blocked", fmt.Sprintf("DRM vblank support/device permissions unavailable (errno %d)", sample.Errno))
		}
		if sample.Status == "fail" {
			return graphicsResult(id, "fail", fmt.Sprintf("Active DRM vblank wait failed (errno %d)", sample.Errno))
		}
		if len(sample.Sequences) != 2 || len(sample.Timestamps) != 2 {
			return graphicsResult(id, "blocked", "Vblank observer did not return two real samples")
		}
		if sample.Sequences[1]-sample.Sequences[0] == 0 || sample.Timestamps[1] <= sample.Timestamps[0] {
			return graphicsResult(id, "fail", "Active scanout vblank sequence/timestamp did not advance")
		}
		witnessed = append(witnessed, fmt.Sprintf("%s current=%s@%sHz, active framebuffer, vblank advanced %d", pair[1], mode[1], mode[2], sample.Sequences[1]-sample.Sequences[0]))
	}
	if len(witnessed) == 0 {
		return graphicsResult(id, "blocked", "No connected "+scope+" display fixture currently exposed; no hotplug/power/mode action requested")
	}
	return graphicsResult(id, "pass", strings.Join(witnessed, "; ")+"; current scanout only, not image quality, hotplug, blank/unblank or resume")
}

func graphicsBacklight(c *AutoContext) AutoResult {
	id := "graphics.backlight"
	paths, err := c.Glob("/sys/class/backlight/*")
	if err != nil || len(paths) == 0 {
		return graphicsResult(id, "blocked", "Backlight interface unavailable; PWM/backlight driver support or permissions are needed")
	}
	var parts []string
	for _, path := range paths {
		values := map[string]int{}
		for _, attr := range []string{"brightness", "actual_brightness", "max_brightness"} {
			text, readErr := c.Read(path + "/" + attr)
			if readErr != nil {
				return graphicsResult(id, "blocked", filepath.Base(path)+"/"+attr+" unavailable: "+readErr.Error())
			}
			value, parseErr := strconv.Atoi(text)
			if parseErr != nil || value < 0 {
				return graphicsResult(id, "blocked", "Backlight numeric metadata is unavailable/unrecognized")
			}
			values[attr] = value
		}
		kind, readErr := c.Read(path + "/type")
		if readErr != nil {
			return graphicsResult(id, "blocked", "Backlight type metadata unavailable: "+readErr.Error())
		}
		if kind != "raw" && kind != "platform" && kind != "firmware" {
			return graphicsResult(id, "blocked", "Backlight type metadata is unrecognized")
		}
		parts = append(parts, fmt.Sprintf("%s type=%s requested=%d actual=%d maximum=%d", filepath.Base(path), kind, values["brightness"], values["actual_brightness"], values["max_brightness"]))
	}
	return graphicsResult(id, "observed", strings.Join(parts, "; ")+"; no writes or brightness-range/visual claim")
}

func graphicsSoftware(name string) bool {
	name = strings.ToLower(name)
	for _, marker := range []string{"llvmpipe", "softpipe", "lavapipe", "swrast", "software", "swiftshader", "cpu"} {
		if strings.Contains(name, marker) {
			return true
		}
	}
	return false
}

var graphicsA680 = regexp.MustCompile(`(?i)\b(?:FD680|Adreno(?:\s*\(TM\))?\s*680)\b`)
var graphicsEGLRenderer = regexp.MustCompile(`(?m)^\s*(OpenGL(?: ES| core profile| compatibility profile)?)(?: renderer(?: string)?):\s*([^\r\n]+)`)

func graphicsEGL(c *AutoContext) AutoResult {
	id := "graphics.egl"
	out, err := c.Command("eglinfo", "-B", "-p", "surfaceless")
	if err != nil {
		return graphicsCommandIssue(id, "surfaceless EGL context inventory", out, err)
	}
	matches := graphicsEGLRenderer.FindAllStringSubmatch(out, -1)
	if len(matches) == 0 {
		return graphicsResult(id, "blocked", "eglinfo did not expose GL/GLES renderer fields; context support/tool output is insufficient")
	}
	var apis []string
	for _, m := range matches {
		if graphicsSoftware(m[2]) {
			return graphicsResult(id, "fail", "Surfaceless EGL selected a software GL/GLES renderer; hardware fallback rejected")
		}
		if !graphicsA680.MatchString(m[2]) {
			return graphicsResult(id, "blocked", "Surfaceless EGL renderer is not identified as the fitted Adreno 680; hardware path not established")
		}
		apis = append(apis, m[1])
	}
	return graphicsResult(id, "observed", "Surfaceless EGL exposes Adreno 680 contexts: "+strings.Join(apis, ", ")+"; context creation is not draw/readback or desktop acceleration evidence")
}

func graphicsVulkanDevices(c *AutoContext) AutoResult {
	id := "graphics.vulkan.devices"
	out, err := c.Command("vulkaninfo", "--summary")
	if err != nil {
		return graphicsCommandIssue(id, "Vulkan device inventory", out, err)
	}
	hardware, software := 0, 0
	var versions []string
	for _, block := range regexp.MustCompile(`(?m)^GPU[0-9]+:`).Split(out, -1)[1:] {
		name := graphicsValue(block, "deviceName")
		kind := graphicsValue(block, "deviceType")
		if graphicsSoftware(name) || strings.Contains(kind, "CPU") {
			software++
			continue
		}
		if graphicsA680.MatchString(name) && (strings.Contains(kind, "INTEGRATED_GPU") || strings.Contains(kind, "DISCRETE_GPU")) {
			hardware++
			version := graphicsValue(block, "apiVersion")
			if regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+$`).MatchString(version) {
				versions = append(versions, version)
			}
		}
	}
	if hardware == 0 {
		return graphicsResult(id, "blocked", fmt.Sprintf("No identified Adreno 680 Vulkan hardware device exposed (%d software devices); hardware ICD/driver support or permissions are needed", software))
	}
	return graphicsResult(id, "observed", fmt.Sprintf("Adreno 680 Vulkan hardware devices=%d, software devices=%d, API=%s; enumeration does not establish renderer selection or fix recorded GMEM scrolling corruption", hardware, software, strings.Join(versions, ",")))
}

func graphicsValue(text, key string) string {
	for _, line := range strings.Split(text, "\n") {
		pair := strings.SplitN(strings.TrimSpace(line), "=", 2)
		if len(pair) == 2 && strings.TrimSpace(pair[0]) == key {
			return strings.TrimSpace(pair[1])
		}
	}
	return ""
}

func graphicsCommandIssue(id, action, output string, err error) AutoResult {
	low := strings.ToLower(output)
	if strings.Contains(low, "vk_error_device_lost") || strings.Contains(low, "gpu hang") || strings.Contains(low, "context lost") {
		return graphicsResult(id, "fail", action+" reported device/context loss")
	}
	if errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) || strings.Contains(strings.ToLower(err.Error()), "executable file not found") || strings.Contains(low, "no such file or directory") || strings.Contains(low, "not found") {
		return graphicsResult(id, "blocked", action+" requires an installed tool/fixture")
	}
	if strings.Contains(low, "permission denied") || errors.Is(err, os.ErrPermission) {
		return graphicsResult(id, "blocked", action+" requires graphics device/session permissions")
	}
	if strings.Contains(low, "could not initialize windowing") || strings.Contains(low, "cannot open display") || strings.Contains(low, "failed to create renderer") || strings.Contains(low, "eglinitialize failed") || strings.Contains(low, "failed to create gbm") || strings.Contains(low, "failed to open drm") || strings.Contains(low, "vk_error_incompatible_driver") {
		return graphicsResult(id, "blocked", action+" needs a usable graphics driver/context and, for GTK, an existing display session")
	}
	return graphicsResult(id, "blocked", action+" did not complete; usable tool/context support is needed (no functional verdict)")
}

type graphicsGLXML struct {
	XMLName xml.Name `xml:"glmark2"`
	Info    struct {
		Renderer string `xml:"gl_renderer"`
		Version  string `xml:"gl_version"`
	} `xml:"info"`
	Rows []struct {
		Name   string `xml:"name"`
		Status string `xml:"status"`
	} `xml:"benchmark"`
}

// Only the GBM backend is used: unlike the DRM backend it never requests a modeset.
func graphicsGLRender(c *AutoContext, es bool) AutoResult {
	id, tool, api := "graphics.gl.render", "glmark2-gbm", "OpenGL"
	if es {
		id, tool, api = "graphics.gles.render", "glmark2-es2-gbm", "OpenGL ES"
	}
	nodes, err := c.Glob("/dev/dri/renderD*")
	if err != nil || len(nodes) == 0 {
		return graphicsResult(id, "blocked", "DRM render-node support/permissions are needed for windowless "+api+" validation")
	}
	if len(nodes) != 1 {
		return graphicsResult(id, "blocked", "Multiple DRM render nodes need an explicit fitted-GPU mapping before running the fixture")
	}
	dir, err := os.MkdirTemp("", "spx-graphics-gl-")
	if err != nil {
		return graphicsResult(id, "blocked", "A writable temporary directory is needed for the expected-image result")
	}
	defer os.RemoveAll(dir)
	resultFile := filepath.Join(dir, "result.xml")
	out, err := c.Command(tool, "--off-screen", "--winsys-options=drm-device="+nodes[0], "--size", "800x600", "--frame-end=finish", "--validate", "--benchmark", "build:use-vbo=true:duration=1", "--results-file", resultFile)
	if err != nil {
		return graphicsCommandIssue(id, api+" offscreen expected-image test", out, err)
	}
	data, err := os.ReadFile(resultFile)
	if err != nil {
		return graphicsResult(id, "blocked", "glmark2 did not expose its expected-image result; installed tool/assets are needed")
	}
	var result graphicsGLXML
	if err := xml.Unmarshal(data, &result); err != nil {
		return graphicsResult(id, "blocked", "glmark2 expected-image result format is unusable")
	}
	if graphicsSoftware(result.Info.Renderer) {
		return graphicsResult(id, "fail", api+" offscreen test used software rendering; fallback rejected")
	}
	if !graphicsA680.MatchString(result.Info.Renderer) {
		return graphicsResult(id, "blocked", "Offscreen renderer is not identified as the fitted Adreno 680")
	}
	if result.Info.Version == "" || strings.Contains(result.Info.Version, "OpenGL ES") != es {
		return graphicsResult(id, "blocked", "Offscreen result does not establish the requested "+api+" API")
	}
	if len(result.Rows) != 1 || !graphicsGLScene(result.Rows[0].Name) {
		return graphicsResult(id, "blocked", "Offscreen expected-image fixture scene was not identified")
	}
	switch result.Rows[0].Status {
	case "Failure":
		return graphicsResult(id, "fail", api+" Adreno 680 offscreen VBO scene failed glmark2 pixel validation")
	case "Success":
		return graphicsResult(id, "pass", api+" Adreno 680 GBM VBO scene rendered offscreen at 800x600 and passed pixel readback; one-scene smoke only, not sustained/desktop/idle coverage")
	default:
		return graphicsResult(id, "blocked", "Offscreen scene lacks a recognized pixel validation oracle/result")
	}
}

func graphicsGLScene(name string) bool {
	parts := strings.SplitN(name, "] ", 2)
	if len(parts) != 2 || parts[0] != "[build" {
		return false
	}
	options := strings.Split(parts[1], ":")
	if len(options) != 2 {
		return false
	}
	return (options[0] == "duration=1" && options[1] == "use-vbo=true") ||
		(options[0] == "use-vbo=true" && options[1] == "duration=1")
}

func graphicsUserTempDir(c *AutoContext, pattern string) (string, error) {
	dir, err := os.MkdirTemp("", pattern)
	if err != nil {
		return "", err
	}
	if c.Options.User == "" || os.Geteuid() != 0 || (c.Root != "" && filepath.Clean(c.Root) != "/") {
		return dir, nil
	}
	account, err := user.Lookup(c.Options.User)
	if err == nil {
		uid, uidErr := strconv.Atoi(account.Uid)
		gid, gidErr := strconv.Atoi(account.Gid)
		err = errors.Join(uidErr, gidErr)
		if err == nil {
			err = os.Chown(dir, uid, gid)
		}
	}
	if err != nil {
		os.RemoveAll(dir)
		return "", err
	}
	return dir, nil
}

func graphicsVulkanRender(c *AutoContext) AutoResult {
	id := "graphics.vulkan.render"
	dir, err := graphicsUserTempDir(c, "spx-graphics-vulkan-")
	if err != nil {
		return graphicsResult(id, "blocked", "A writable temporary directory is needed for the public render fixture")
	}
	defer os.RemoveAll(dir)
	node, output := filepath.Join(dir, "public.node"), filepath.Join(dir, "output.png")
	// Public color geometry only. The render subcommand realizes for the existing
	// display without constructing/presenting a window when --renderer is explicit.
	fixture := "color { bounds: 0 0 32 64; color: rgb(255,0,0); }\ncolor { bounds: 32 0 32 64; color: rgb(0,255,0); }\n"
	if err := os.WriteFile(node, []byte(fixture), 0644); err != nil {
		return graphicsResult(id, "blocked", "Unable to create the disposable public render fixture")
	}
	// The boot service has a private umask; the selected user must read this public fixture.
	if err := os.Chmod(node, 0644); err != nil {
		return graphicsResult(id, "blocked", "Unable to make the public fixture readable to the selected desktop user")
	}
	out, err := c.UserCommand("env", "GDK_DEBUG=vulkan", "gtk4-rendernode-tool", "render", "--renderer=vulkan", "--bounds=0,0,64,64", node, output)
	if err != nil {
		return graphicsCommandIssue(id, "GTK Vulkan windowless render", out, err)
	}
	selected, ok := graphicsSelectedVulkan(out)
	if !ok {
		return graphicsResult(id, "blocked", "GTK Vulkan selected-device witness unavailable; a PNG alone cannot exclude software fallback")
	}
	if graphicsSoftware(selected) || strings.HasSuffix(selected, "(CPU)") {
		return graphicsResult(id, "fail", "GTK Vulkan windowless render selected a software/CPU device; fallback rejected")
	}
	if !graphicsA680.MatchString(selected) || !(strings.HasSuffix(selected, "(Integrated GPU)") || strings.HasSuffix(selected, "(Discrete GPU)")) {
		return graphicsResult(id, "blocked", "GTK Vulkan selected device is not established as the fitted Adreno 680 hardware")
	}
	f, err := os.Open(output)
	if err != nil {
		return graphicsResult(id, "blocked", "GTK Vulkan did not provide its offscreen readback PNG")
	}
	defer f.Close()
	im, err := png.Decode(f)
	if err != nil {
		return graphicsResult(id, "fail", "GTK Vulkan readback was not a valid PNG")
	}
	if im.Bounds().Dx() != 64 || im.Bounds().Dy() != 64 {
		return graphicsResult(id, "fail", "GTK Vulkan readback dimensions differ from the 64x64 fixture")
	}
	for _, sample := range []struct {
		x, y    int
		r, g, b uint32
	}{{16, 32, 65535, 0, 0}, {48, 32, 0, 65535, 0}} {
		r, g, b, a := im.At(sample.x, sample.y).RGBA()
		if r != sample.r || g != sample.g || b != sample.b || a != 65535 {
			return graphicsResult(id, "fail", "GTK Vulkan public static-color pixel readback differs from the fixture")
		}
	}
	return graphicsResult(id, "pass", "Adreno 680 Vulkan rendered a public 64x64 color fixture windowlessly and matched pixel readback; output discarded. Static path only: recorded GMEM scrolling/partial-damage corruption remains unresolved")
}

var graphicsVulkanDevice = regexp.MustCompile(`(?m)^Vulkan Device ([0-9]+):\s*\n\s*([^\r\n]+)`)
var graphicsVulkanSelection = regexp.MustCompile(`Using Vulkan device ([0-9]+), queue [0-9]+`)

func graphicsSelectedVulkan(output string) (string, bool) {
	selected := graphicsVulkanSelection.FindAllStringSubmatch(output, -1)
	if len(selected) != 1 {
		return "", false
	}
	for _, device := range graphicsVulkanDevice.FindAllStringSubmatch(output, -1) {
		if device[1] == selected[0][1] {
			return strings.TrimSpace(device[2]), true
		}
	}
	return "", false
}
