package main

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func graphicsFixture(t *testing.T, root, path string, data []byte) {
	t.Helper()
	p := filepath.Join(root, strings.TrimPrefix(path, "/"))
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, data, 0644); err != nil {
		t.Fatal(err)
	}
}

func graphicsFixtureEDID() []byte {
	b := make([]byte, 128)
	copy(b, []byte{0, 255, 255, 255, 255, 255, 255, 0})
	copy(b[12:16], "SECR") // A serial field must never reach the report.
	b[24] = 2
	d := b[54:72]
	binary.LittleEndian.PutUint16(d, 35550)
	// 2880 + 80 pixels, 1920 + 82 lines, 355.5 MHz.
	d[2], d[3], d[4] = 64, 80, 0xb0
	d[5], d[6], d[7] = 128, 82, 0x70
	var sum byte
	for _, n := range b {
		sum += n
	}
	b[127] -= sum
	return b
}

func TestGraphicsDisplayAndBacklightInventory(t *testing.T) {
	root := t.TempDir()
	for _, connector := range []string{"card0-eDP-1", "card0-DP-1"} {
		base := "/sys/class/drm/" + connector
		graphicsFixture(t, root, base+"/status", []byte("connected\n"))
		graphicsFixture(t, root, base+"/enabled", []byte("enabled\n"))
		graphicsFixture(t, root, base+"/modes", []byte("2880x1920\n"))
		graphicsFixture(t, root, base+"/edid", graphicsFixtureEDID())
	}
	for k, v := range map[string]string{"brightness": "80", "actual_brightness": "78", "max_brightness": "255", "type": "raw"} {
		graphicsFixture(t, root, "/sys/class/backlight/panel/"+k, []byte(v))
	}
	c := &AutoContext{Root: root, Run: func(...string) (string, error) { t.Fatal("inventory ran a command"); return "", nil }}
	for _, got := range []AutoResult{graphicsDisplays(c, true), graphicsDisplays(c, false), graphicsBacklight(c)} {
		if got.Status != "observed" {
			t.Fatal(got)
		}
		if strings.Contains(got.Detail, "SECR") {
			t.Fatal("EDID serial leaked", got)
		}
	}
	got := graphicsDisplays(c, true)
	if !strings.Contains(got.Detail, "2880x1920@59.99Hz") {
		t.Fatal(got)
	}
	graphicsFixture(t, root, "/sys/class/drm/card0-DP-1/status", []byte("disconnected"))
	if got := graphicsDisplays(c, false); got.Status != "blocked" {
		t.Fatal(got)
	}
	graphicsFixture(t, root, "/sys/class/drm/card0-eDP-1/edid", []byte("bad EDID"))
	if got := graphicsDisplays(c, true); got.Status != "blocked" {
		t.Fatal(got)
	}
	if got := graphicsBacklight(&AutoContext{Root: t.TempDir()}); got.Status != "blocked" {
		t.Fatal(got)
	}
}

func TestGraphicsEGLRejectsSoftwareContext(t *testing.T) {
	for _, tc := range []struct{ output, status string }{
		{"Surfaceless platform:\nOpenGL core profile renderer: FD680\nOpenGL ES renderer: FD680\n", "observed"},
		{"OpenGL core profile renderer: FD680\nOpenGL ES renderer: llvmpipe (LLVM 22)\n", "fail"},
		{"Device lists Adreno 680\nOpenGL renderer: llvmpipe\n", "fail"},
		{"EGL driver name: freedreno\n", "blocked"},
	} {
		c := &AutoContext{Run: func(args ...string) (string, error) {
			if strings.Join(args, " ") != "eglinfo -B -p surfaceless" {
				t.Fatal("unexpected context command", args)
			}
			return tc.output, nil
		}}
		if got := graphicsEGL(c); got.Status != tc.status {
			t.Fatal(got, tc)
		}
	}
}

func TestGraphicsVulkanInventoryIsNotSelection(t *testing.T) {
	out := "GPU0:\n deviceName = Turnip Adreno (TM) 680\n deviceType = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n apiVersion = 1.3.354\n deviceUUID = PRIVATE_UUID\nGPU1:\n deviceName = llvmpipe\n deviceType = PHYSICAL_DEVICE_TYPE_CPU\n"
	c := &AutoContext{Run: func(args ...string) (string, error) {
		if strings.Join(args, " ") != "vulkaninfo --summary" {
			t.Fatal(args)
		}
		return out, nil
	}}
	got := graphicsVulkanDevices(c)
	if got.Status != "observed" || strings.Contains(got.Detail, "PRIVATE_UUID") || !strings.Contains(got.Detail, "software devices=1") {
		t.Fatal(got)
	}
	out = "GPU0:\n deviceName = llvmpipe\n deviceType = PHYSICAL_DEVICE_TYPE_CPU\n"
	if got := graphicsVulkanDevices(c); got.Status != "blocked" {
		t.Fatal(got)
	}
}

func TestGraphicsCommandFailuresDistinguishPrerequisitesAndWorkloads(t *testing.T) {
	failed := errors.New("exit status 1")
	for _, tc := range []struct {
		name, output string
		err          error
		want         string
	}{
		{"missing executable", "", exec.ErrNotFound, "blocked"},
		{"missing file", "/home/private/fixture: No such file or directory", failed, "blocked"},
		{"missing library", "error while loading shared libraries: private.so", failed, "blocked"},
		{"permission error", "", os.ErrPermission, "blocked"},
		{"permission output", "Operation not permitted", failed, "blocked"},
		{"no display", "Cannot open display", failed, "blocked"},
		{"no driver", "VK_ERROR_INCOMPATIBLE_DRIVER", failed, "blocked"},
		{"no desktop session", "", errors.New("existing desktop user manager display environment unavailable"), "blocked"},
		{"fixture execution", "", errors.New("external commands disabled for fixture root"), "blocked"},
		{"device loss", "VK_ERROR_DEVICE_LOST", failed, "fail"},
		{"context loss", "Context lost", failed, "fail"},
		{"wrapped deadline", "", fmt.Errorf("render: %w", context.DeadlineExceeded), "fail"},
		{"bounded command", "", errors.New("gtk4-rendernode-tool exceeded 1m0s command limit"), "fail"},
		{"timeout output", "GPU fence wait timed out", failed, "fail"},
		{"render failure", "Failed to render public fixture", failed, "fail"},
		{"submission failure", "Failed to submit command buffer", failed, "fail"},
		{"workload beats prerequisite warning", "Cannot open display warning; VK_ERROR_DEVICE_LOST", failed, "fail"},
		{"unrecognized not-found text", "private atlas entry not found", failed, "error"},
		{"output limit", "", errors.New("command output exceeded in-memory limit"), "error"},
		{"unexpected exit", "private serial secret-123", failed, "error"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got := graphicsCommandIssue("graphics.vulkan.render", "Vulkan render", tc.output, tc.err)
			if got.Status != tc.want {
				t.Fatalf("got %+v, want %s", got, tc.want)
			}
			if strings.Contains(got.Detail, "private") || strings.Contains(got.Detail, "secret-123") {
				t.Fatal("raw private command output leaked", got)
			}
		})
	}
}

func graphicsTestArgument(args []string, key string) string {
	for i, a := range args {
		if a == key && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

func TestGraphicsGLRenderRequiresHardwareAndPixelOracle(t *testing.T) {
	root := t.TempDir()
	graphicsFixture(t, root, "/dev/dri/renderD128", nil)
	for _, tc := range []struct{ renderer, status, want string }{
		{"FD680", "Success", "pass"},
		{"llvmpipe", "Success", "fail"},
		{"FD680", "Failure", "fail"},
		{"FD680", "Unknown", "blocked"},
	} {
		for _, es := range []bool{false, true} {
			resultPath := ""
			c := &AutoContext{Root: root, Run: func(args ...string) (string, error) {
				tool, version := "glmark2-gbm", "4.6 (Compatibility Profile) Mesa"
				if es {
					tool, version = "glmark2-es2-gbm", "OpenGL ES 3.2 Mesa"
				}
				if args[0] != tool || graphicsTestArgument(args, "--size") != "800x600" || graphicsTestArgument(args, "--benchmark") != "build:use-vbo=true:duration=1" || !strings.Contains(strings.Join(args, " "), "--winsys-options=drm-device=/dev/dri/renderD128") || strings.Contains(strings.Join(args, " "), "--off-screen") {
					t.Fatal("unsafe/different fixture command", args)
				}
				resultPath = graphicsTestArgument(args, "--results-file")
				xml := fmt.Sprintf("<glmark2><info><gl_renderer>%s</gl_renderer><gl_version>%s</gl_version></info><benchmark><name>[build] duration=1:use-vbo=true</name><status>%s</status></benchmark></glmark2>", tc.renderer, version, tc.status)
				return "", os.WriteFile(resultPath, []byte(xml), 0600)
			}}
			if got := graphicsGLRender(c, es); got.Status != tc.want {
				t.Fatal(got, tc)
			}
			if _, err := os.Stat(filepath.Dir(resultPath)); !os.IsNotExist(err) {
				t.Fatal("temporary benchmark result retained")
			}
		}
	}
	c := &AutoContext{Root: root, Run: func(...string) (string, error) { return "", exec.ErrNotFound }}
	if got := graphicsGLRender(c, false); got.Status != "blocked" {
		t.Fatal(got)
	}
}

func TestGraphicsGLMissingGBMFlavours(t *testing.T) {
	root := t.TempDir()
	graphicsFixture(t, root, "/dev/dri/renderD128", nil)
	for _, es := range []bool{false, true} {
		for _, flavour := range strings.Fields("glmark2 glmark2-drm glmark2-egl glmark2-es2 glmark2-es2-drm glmark2-wayland glmark2-es2-wayland") {
			t.Run(fmt.Sprintf("es=%t/%s", es, flavour), func(t *testing.T) {
				calls := 0
				tool := "glmark2-gbm"
				if es {
					tool = "glmark2-es2-gbm"
				}
				c := &AutoContext{Root: root, Run: func(args ...string) (string, error) {
					calls++
					if calls == 1 && args[0] == tool {
						return "", fmt.Errorf("missing: %w", exec.ErrNotFound)
					}
					if calls == 2 && len(args) == 3 && args[0] == "sh" && args[1] == "-c" && args[2] == graphicsGLInstalledLookup {
						return "/usr/bin/" + flavour, nil
					}
					t.Fatalf("unexpected/fallback command: %v", args)
					return "", nil
				}}
				got := graphicsGLRender(c, es)
				if got.Status != "blocked" || calls != 2 || !strings.Contains(got.Detail, "installed glmark2 has no GBM offscreen flavour; DRM flavour is excluded because it requests a modeset") || strings.Contains(got.Detail, "/usr/bin/") {
					t.Fatal(got, calls)
				}
			})
		}
		for _, tc := range []struct {
			name, output, want string
			err                error
		}{
			{"not installed", "", "glmark2 tool not installed", errors.New("exit status 1")},
			{"lookup unavailable", "", "package presence is unknown", os.ErrPermission},
			{"empty successful lookup", "", "package presence is unknown", nil},
		} {
			t.Run(fmt.Sprintf("es=%t/%s", es, tc.name), func(t *testing.T) {
				lookupErr := tc.err
				c := &AutoContext{Root: root, Run: func(args ...string) (string, error) {
					if args[0] == "glmark2-gbm" || args[0] == "glmark2-es2-gbm" {
						return "", exec.ErrNotFound
					}
					if args[0] != "sh" || len(args) != 3 || args[2] != graphicsGLInstalledLookup {
						t.Fatalf("unexpected/fallback command: %v", args)
					}
					return tc.output, lookupErr
				}}
				if got := graphicsGLRender(c, es); got.Status != "blocked" || !strings.Contains(got.Detail, tc.want) {
					t.Fatal(got)
				}
			})
		}
	}
}

func graphicsTestPNG(path string, corrupt *image.Point) error {
	im := image.NewRGBA(image.Rect(0, 0, 64, 64))
	for y := 0; y < 64; y++ {
		for x := 0; x < 64; x++ {
			pixel := color.RGBA{R: 255, A: 255}
			if x >= 32 {
				pixel = color.RGBA{G: 255, A: 255}
			}
			if corrupt != nil && x == corrupt.X && y == corrupt.Y {
				pixel = color.RGBA{B: 255, A: 255}
			}
			im.SetRGBA(x, y, pixel)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	err = png.Encode(f, im)
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func TestGraphicsWindowlessVulkanRejectsSelectedCPUAndBadPixels(t *testing.T) {
	hardware := "Vulkan Device 0:\n    Turnip Adreno (TM) 680 (Integrated GPU)\nVulkan Device 1:\n    llvmpipe (CPU)\n"
	for _, tc := range []struct {
		selection string
		corrupt   *image.Point
		want      string
	}{
		{"Using Vulkan device 0, queue 0\n", nil, "pass"},
		{"Using Vulkan device 1, queue 0\n", nil, "fail"},
		{"", nil, "blocked"},
		{"Using Vulkan device 0, queue 0\n", &image.Point{X: 48, Y: 32}, "fail"},
		// Corruption away from the former two samples must also reject a pass.
		{"Using Vulkan device 0, queue 0\n", &image.Point{X: 1, Y: 1}, "fail"},
		{"Using Vulkan device 0, queue 0\n", &image.Point{X: 63, Y: 63}, "fail"},
		{"Using Vulkan device 0, queue 0\n", &image.Point{X: 31, Y: 0}, "fail"},
		{"Using Vulkan device 0, queue 0\n", &image.Point{X: 32, Y: 63}, "fail"},
	} {
		resultDir := ""
		c := &AutoContext{Run: func(args ...string) (string, error) {
			if len(args) != 8 || strings.Join(args[:6], " ") != "env GDK_DEBUG=vulkan gtk4-rendernode-tool render --renderer=vulkan --bounds=0,0,64,64" {
				t.Fatal("unsafe/different GTK command", args)
			}
			resultDir = filepath.Dir(args[6])
			contents, err := os.ReadFile(args[6])
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(contents), "color {") || strings.Contains(string(contents), "texture") {
				t.Fatal("fixture must be public geometry")
			}
			return hardware + tc.selection, graphicsTestPNG(args[7], tc.corrupt)
		}}
		got := graphicsVulkanRender(c)
		if got.Status != tc.want {
			t.Fatal(got, tc)
		}
		if got.Status == "pass" && !strings.Contains(got.Detail, "covered separately by graphics.vulkan.dynamic-damage") {
			t.Fatal("static render masked dynamic corruption", got)
		}
		if _, err := os.Stat(resultDir); !os.IsNotExist(err) {
			t.Fatal("static fixture/readback retained")
		}
	}
}

func TestGraphicsCurrentScanoutUsesOnlyReadOnlyStateAndVblank(t *testing.T) {
	root := t.TempDir()
	for _, connector := range []string{"card0-eDP-1", "card0-DP-1"} {
		graphicsFixture(t, root, "/sys/class/drm/"+connector+"/status", []byte("connected"))
		graphicsFixture(t, root, "/sys/class/drm/"+connector+"/enabled", []byte("enabled"))
	}
	state := "plane[46]: plane-0\n\tcrtc=crtc-0\n\tfb=102\n" +
		"plane[47]: plane-1\n\tcrtc=crtc-1\n\tfb=103\n" +
		"crtc[94]: crtc-0\n\tenable=1\n\tactive=1\n\tmode: \"2880x1920\": 60 355500\n" +
		"crtc[95]: crtc-1\n\tenable=1\n\tactive=1\n\tmode: \"3440x1440\": 50 265250\n" +
		"connector[39]: eDP-1\n\tcrtc=crtc-0\nconnector[40]: DP-1\n\tcrtc=crtc-1\n"
	graphicsFixture(t, root, "/sys/kernel/debug/dri/0/state", []byte(state))
	for _, tc := range []struct{ output, want string }{
		{`{"sequences":[9,10],"timestamps_us":[1000000,1016667]}`, "pass"},
		{`{"sequences":[9,9],"timestamps_us":[1000000,1016667]}`, "fail"},
		{`{"sequences":[9,10],"timestamps_us":[1000000,1000000]}`, "fail"},
		{`{"status":"blocked","errno":13}`, "blocked"},
		{`{"status":"fail","errno":16}`, "fail"},
	} {
		for _, internal := range []bool{true, false} {
			calls := 0
			c := &AutoContext{Root: root, Run: func(args ...string) (string, error) {
				calls++
				crtc := "1"
				if internal {
					crtc = "0"
				}
				if len(args) != 5 || args[0] != "python3" || args[1] != "-c" || args[2] != graphicsVblankObserver || args[3] != "/dev/dri/card0" || args[4] != crtc {
					t.Fatal("unexpected scanout command", args)
				}
				return tc.output, nil
			}}
			if got := graphicsScanout(c, internal); got.Status != tc.want {
				t.Fatal(got, tc)
			}
			if calls != 1 {
				t.Fatal("missing real vblank observer")
			}
		}
	}
	graphicsFixture(t, root, "/sys/kernel/debug/dri/0/state", []byte(strings.Replace(state, `"2880x1920": 60`, `"2880x1920": 30`, 1)))
	if got := graphicsScanout(&AutoContext{Root: root}, true); got.Status != "blocked" {
		t.Fatal(got)
	}
	graphicsFixture(t, root, "/sys/kernel/debug/dri/0/state", []byte(strings.Replace(state, "\tfb=102", "\tfb=0", 1)))
	if got := graphicsScanout(&AutoContext{Root: root}, true); got.Status != "fail" {
		t.Fatal(got)
	}
	graphicsFixture(t, root, "/sys/class/drm/card0-DP-1/status", []byte("disconnected"))
	if got := graphicsScanout(&AutoContext{Root: root}, false); got.Status != "blocked" {
		t.Fatal(got)
	}
}

func TestGraphicsCatalogKeepsKnownDynamicDefectVisible(t *testing.T) {
	checks := automaticGraphicsChecks()
	if len(checks) != 11 {
		t.Fatal("incomplete graphics catalog", len(checks))
	}
	for _, check := range checks {
		if check.ID == "graphics.vulkan.dynamic-damage" {
			got := check.Run(&AutoContext{})
			if check.Kind != "functional" || got.Status != "blocked" {
				t.Fatal(got)
			}
			return
		}
	}
	t.Fatal("dynamic damage regression missing")
}

type graphicsDamageExit int

func (e graphicsDamageExit) Error() string { return fmt.Sprintf("exit status %d", e) }
func (e graphicsDamageExit) ExitCode() int { return int(e) }

func TestGraphicsVulkanDamageResults(t *testing.T) {
	hardware := "Device: Turnip Adreno (TM) 680; driver: turnip Mesa driver (Mesa 26.2.1)\n"
	for _, tc := range []struct {
		name, output, status, detail string
		err                          error
	}{
		{"pass", hardware + "PASS; elapsed 1.2 s\n", "pass", "every frame", nil},
		{"mismatch", hardware + "2880x1920 frame=-1: 0/5529600 pixels differ; FNV64=PRIVATE\n2880x1920 frame=0: 890000/5529600 pixels differ; FNV64=PRIVATE\nraw pixel=PRIVATE\nFAIL; elapsed 1 s\n", "fail", "890000/5529600 pixels differ", graphicsDamageExit(1)},
		{"fail marker", hardware + "FAIL; elapsed 1 s\n", "fail", "comparison failed", nil},
		{"missing binary", "", "blocked", "unavailable", exec.ErrNotFound},
		{"missing through timeout", "timeout: No such file or directory", "blocked", "unavailable", graphicsDamageExit(127)},
		{"unsupported", "No hardware Turnip device", "blocked", "exit 77", graphicsDamageExit(77)},
		{"software", "Device: llvmpipe (LLVM 22); driver: lavapipe\nPASS; elapsed 1 s\n", "fail", "fallback rejected", nil},
		{"software masquerading", "Device: Turnip software\nPASS; elapsed 1 s\n", "fail", "fallback rejected", nil},
		{"error", hardware, "error", "exit 2", graphicsDamageExit(2)},
		{"missing device", "PASS; elapsed 1 s\n", "blocked", "Device line missing", nil},
		{"unparseable", hardware + "PRIVATE", "error", "no parseable", nil},
		{"runner error", hardware, "error", "did not complete", errors.New("output cap exceeded PRIVATE")},
		{"timeout", hardware, "error", "did not complete", graphicsDamageExit(124)},
		{"desktop unavailable", "", "blocked", "desktop session", errors.New("requested desktop user cannot be resolved")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := &AutoContext{Root: t.TempDir(), Options: AutoOptions{User: "desktop"}, Run: func(args ...string) (string, error) {
				want := "env TU_DEBUG=gmem timeout --kill-after=2s 15s /usr/local/lib/spx-turnip/spx-vk-partial-load-store"
				if strings.Join(args, " ") != want {
					t.Fatal("unexpected regression command", args)
				}
				return tc.output, tc.err
			}}
			got := graphicsVulkanDamage(c)
			if got.Status != tc.status || !strings.Contains(got.Detail, tc.detail) || strings.Contains(got.Detail, "PRIVATE") {
				t.Fatal(got)
			}
			for _, scope := range []string{"ICD=system default", "Partial load/store in GMEM mode", "not general Vulkan conformance", "msm A680 GMEM-base fix", "sysmem-workaround driver"} {
				if !strings.Contains(got.Detail, scope) {
					t.Fatal("missing regression scope", got)
				}
			}
		})
	}
}

func TestGraphicsVulkanEnvironment(t *testing.T) {
	for _, tc := range []struct{ text, want string }{
		{"", ""},
		{"# VK_DRIVER_FILES=/ignored.json\nGSK_RENDERER=opengl\nnot an assignment", ""},
		{" VK_DRIVER_FILES = \"/custom/a.json:/custom/b.json\" \nVK_ICD_FILENAMES='/legacy.json'\n", "VK_DRIVER_FILES=/custom/a.json:/custom/b.json VK_ICD_FILENAMES=/legacy.json"},
		{"VK_ICD_FILENAMES=/legacy.json\n", "VK_ICD_FILENAMES=/legacy.json"},
		{"VK_DRIVER_FILES=/old.json\nVK_DRIVER_FILES='/new.json'\n", "VK_DRIVER_FILES=/new.json"},
		{"VK_DRIVER_FILES=/old.json\nVK_DRIVER_FILES=\"\"\n", ""},
	} {
		if got := strings.Join(graphicsVulkanEnvironment(tc.text), " "); got != tc.want {
			t.Fatalf("environment %q: got %q, want %q", tc.text, got, tc.want)
		}
	}
	root := t.TempDir()
	graphicsFixture(t, root, "/etc/environment", []byte("VK_DRIVER_FILES=\"/patched.json\"\nVK_ICD_FILENAMES='/legacy.json'\nTU_DEBUG=sysmem\n"))
	c := &AutoContext{Root: root, Options: AutoOptions{User: "desktop"}, Run: func(args ...string) (string, error) {
		want := "env TU_DEBUG=gmem VK_DRIVER_FILES=/patched.json VK_ICD_FILENAMES=/legacy.json timeout --kill-after=2s 15s /usr/local/lib/spx-turnip/spx-vk-partial-load-store"
		if strings.Join(args, " ") != want {
			t.Fatal("system ICD selection not propagated", args)
		}
		return "Device: Turnip Adreno (TM) 680; driver: turnip Mesa driver\nPASS; elapsed 1 s\n", nil
	}}
	if got := graphicsVulkanDamage(c); got.Status != "pass" || !strings.Contains(got.Detail, "ICD=VK_DRIVER_FILES=/patched.json") {
		t.Fatal(got)
	}
}

func TestGraphicsVulkanDamageBlocksFixtureAndMissingUser(t *testing.T) {
	for _, c := range []*AutoContext{
		{Fixture: true, Root: t.TempDir(), Run: func(...string) (string, error) { t.Fatal("fixture executed a command"); return "", nil }},
		{Root: t.TempDir()},
		{},
	} {
		if got := graphicsVulkanDamage(c); got.Status != "blocked" {
			t.Fatal(got)
		}
	}
}
