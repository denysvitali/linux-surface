package main

import (
	"encoding/binary"
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
				if args[0] != tool || graphicsTestArgument(args, "--size") != "800x600" || graphicsTestArgument(args, "--benchmark") != "build:use-vbo=true:duration=1" || !strings.Contains(strings.Join(args, " "), "--off-screen --winsys-options=drm-device=/dev/dri/renderD128") {
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

func graphicsTestPNG(path string, corrupt bool) error {
	im := image.NewRGBA(image.Rect(0, 0, 64, 64))
	for y := 0; y < 64; y++ {
		for x := 0; x < 64; x++ {
			pixel := color.RGBA{R: 255, A: 255}
			if x >= 32 {
				pixel = color.RGBA{G: 255, A: 255}
			}
			if corrupt && x == 48 && y == 32 {
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
		corrupt   bool
		want      string
	}{
		{"Using Vulkan device 0, queue 0\n", false, "pass"},
		{"Using Vulkan device 1, queue 0\n", false, "fail"},
		{"", false, "blocked"},
		{"Using Vulkan device 0, queue 0\n", true, "fail"},
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
		if got.Status == "pass" && !strings.Contains(got.Detail, "remains unresolved") {
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
