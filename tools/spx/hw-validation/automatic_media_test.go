package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func autoMediaTestContext(t *testing.T, files map[string]string, run func(...string) (string, error)) *AutoContext {
	t.Helper()
	root := t.TempDir()
	for _, dir := range []string{"sys/module", "sys/class/video4linux", "dev"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0700); err != nil {
			t.Fatal(err)
		}
	}
	for path, data := range files {
		target := filepath.Join(root, strings.TrimPrefix(path, "/"))
		if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(target, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return &AutoContext{Root: root, Run: run}
}

const autoMediaTestDecodeLog = `[h264_v4l2m2m @ 0x1] Using device /dev/video32
[h264_v4l2m2m @ 0x1] driver 'qcom-venus' on card 'Qualcomm Venus video decoder' in mplane mode
Stream mapping:
  Stream #0:0 -> #0:0 (h264 (h264_v4l2m2m) -> wrapped_avframe (native))
frame=30
progress=end
[out#0/null @ 0x1] Output stream #0:0 (video): 30 frames encoded; 30 packets muxed (100 bytes);
[in#0/mp4 @ 0x1] Input stream #0:0 (video): 33 packets read (1000 bytes); 32 frames decoded; 0 decode errors;
`

func TestAutomaticMediaDecodeEvidence(t *testing.T) {
	cases := []struct{ name, text, want string }{
		{"hardware", autoMediaTestDecodeLog, "pass"},
		{"software mapping", strings.ReplaceAll(autoMediaTestDecodeLog, "(h264_v4l2m2m) ->", "(native) ->"), "fail"},
		{"wrong device", strings.ReplaceAll(autoMediaTestDecodeLog, "/dev/video32", "/dev/video9"), "fail"},
		{"missing completion", strings.ReplaceAll(autoMediaTestDecodeLog, "progress=end", "progress=continue"), "fail"},
		{"missing decoded count", strings.ReplaceAll(autoMediaTestDecodeLog, "32 frames decoded;", "no summary;"), "fail"},
		{"mismatched counts", strings.ReplaceAll(autoMediaTestDecodeLog, "frame=30", "frame=29"), "fail"},
		{"decode errors", strings.ReplaceAll(autoMediaTestDecodeLog, "0 decode errors", "1 decode errors"), "fail"},
		{"short fixture", strings.NewReplacer("30", "3", "32 frames decoded", "3 frames decoded").Replace(autoMediaTestDecodeLog), "blocked"},
		{"short output", strings.NewReplacer("frame=30", "frame=3", "30 frames encoded", "3 frames encoded").Replace(autoMediaTestDecodeLog), "fail"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			result := autoMediaDecodeEvidence(tc.text, "h264_v4l2m2m", []string{"/dev/video32"}, 1920, 1080)
			if result.Status != tc.want {
				t.Fatalf("got %+v want %s", result, tc.want)
			}
		})
	}
}

func TestAutomaticMediaDecodeUsesExplicitHardwareAndDiscard(t *testing.T) {
	var calls [][]string
	c := autoMediaTestContext(t, map[string]string{
		"/fixtures/real.mp4":                  "fixture placeholder; fake runner never reads media",
		"/sys/class/video4linux/video32/name": "qcom-venus-decoder",
	}, func(args ...string) (string, error) {
		calls = append(calls, append([]string{}, args...))
		switch args[0] {
		case "ffprobe":
			return `{"streams":[{"codec_name":"h264","width":1920,"height":1080}]}`, nil
		case "ffmpeg":
			if strings.Contains(strings.Join(args, " "), "-decoders") {
				return " V..... h264_v4l2m2m V4L2 mem2mem H.264 decoder wrapper (codec h264)\n", nil
			}
			return autoMediaTestDecodeLog, nil
		}
		t.Fatalf("unexpected command %q", args)
		return "", nil
	})
	c.Options.Media = "/fixtures/real.mp4"
	result := autoMediaDecode(c)
	if result.Status != "pass" {
		t.Fatalf("decode: %+v", result)
	}
	if len(calls) != 3 {
		t.Fatalf("calls: %q", calls)
	}
	args := strings.Join(calls[2], " ")
	for _, required := range []string{"-c:v h264_v4l2m2m -i", "-xerror", "-t 2", "-frames:v 30", "-an -sn -dn", "-f null -", "-progress pipe:1", "-fps_mode passthrough"} {
		if !strings.Contains(args, required) {
			t.Errorf("missing %s in %s", required, args)
		}
	}
	if strings.Contains(args, "lavfi") || strings.Contains(args, "-hwaccel auto") {
		t.Fatal("synthetic fixture or fallback")
	}
}

func TestAutomaticMediaCodecRequirementsShareOnlyMatchingEvidence(t *testing.T) {
	commands := 0
	c := autoMediaTestContext(t, map[string]string{
		"/fixtures/real.mp4":                  "fixture placeholder",
		"/sys/class/video4linux/video32/name": "qcom-venus-decoder",
	}, func(args ...string) (string, error) {
		commands++
		if args[0] == "ffprobe" {
			return `{"streams":[{"codec_name":"h264","width":1920,"height":1080}]}`, nil
		}
		if strings.Contains(strings.Join(args, " "), "-decoders") {
			return " V..... h264_v4l2m2m wrapper (codec h264)\n", nil
		}
		return autoMediaTestDecodeLog, nil
	})
	c.Options.Media = "/fixtures/real.mp4"
	checked := 0
	for _, check := range automaticMediaChecks() {
		if check.Kind != "functional" || !strings.HasPrefix(check.ID, "media.decode.") {
			continue
		}
		checked++
		result := automaticResult(check, c)
		want := "blocked"
		if check.ID == "media.decode.h264" {
			want = "pass"
		}
		if result.Status != want {
			t.Fatalf("another codec inherited the fixture result: %+v", result)
		}
	}
	if checked != 5 || commands != 3 {
		t.Fatalf("codec coverage=%d commands=%d; need five requirements and one decode attempt", checked, commands)
	}
}

func TestAutomaticMediaDecodeBlockedPrerequisites(t *testing.T) {
	c := autoMediaTestContext(t, nil, func(args ...string) (string, error) { t.Fatalf("unexpected command %q", args); return "", nil })
	if result := autoMediaDecode(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c.Options.Media = "https://private.invalid/clip.mp4"
	if result := autoMediaDecode(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c.Options.Media = "/fixtures/missing.mp4"
	if result := autoMediaDecode(c); result.Status != "blocked" {
		t.Fatal(result)
	}
	c = autoMediaTestContext(t, map[string]string{
		"/fixtures/real.mp4": "placeholder", "/sys/class/video4linux/video32/name": "qcom-venus-decoder",
		"/sys/class/video4linux/video33/name": "qcom-venus-encoder",
	}, func(args ...string) (string, error) {
		t.Fatalf("encoder exposed: no command allowed %q", args)
		return "", nil
	})
	c.Options.Media = "/fixtures/real.mp4"
	if result := autoMediaDecode(c); result.Status != "blocked" || !strings.Contains(result.Detail, "encoder") {
		t.Fatal(result)
	}
	c = autoMediaTestContext(t, map[string]string{
		"/fixtures/real.mp4": "placeholder", "/sys/class/video4linux/video32/name": "qcom-venus-decoder",
		"/sys/module/venus_enc/refcnt": "0",
	}, func(args ...string) (string, error) {
		t.Fatalf("encoder loaded: no command allowed %q", args)
		return "", nil
	})
	c.Options.Media = "/fixtures/real.mp4"
	if result := autoMediaDecode(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}

func TestAutomaticMediaFormatsAreOnlyInventory(t *testing.T) {
	c := autoMediaTestContext(t, map[string]string{
		"/sys/class/video4linux/video32/name": "qcom-venus-decoder",
		"/sys/class/video4linux/video33/name": "qcom-venus-encoder",
	}, func(args ...string) (string, error) {
		if strings.Join(args, " ") != "v4l2-ctl --device /dev/video32 --list-formats-out" {
			t.Fatalf("unsafe/unexpected %q", args)
		}
		return "Type: Video Output Multiplanar\n [0]: 'H264' (H.264)\n [1]: 'HEVC' (HEVC)\n [2]: 'ZZZZ' (driver-advertised future codec)\n", nil
	})
	result := autoMediaDecodeFormats(c)
	if result.Status != "observed" || !strings.Contains(result.Detail, "H264, HEVC, ZZZZ") {
		t.Fatal(result)
	}
	if got := autoMediaV4L2Decoder(" V..... mpeg2_v4l2m2m wrapper (codec mpeg2video)\n", "mpeg2video"); got != "mpeg2_v4l2m2m" {
		t.Fatal(got)
	}
	if got := autoMediaV4L2Decoder(" V..... h264 native software\n", "h264"); got != "" {
		t.Fatal(got)
	}
}

func TestAutomaticMediaProblemsArePrivateAndClassified(t *testing.T) {
	cases := []struct{ output, want string }{
		{"/home/private/secret.mp4: Permission denied", "blocked"},
		{"Could not find a valid device", "blocked"},
		{"exit status 127; error while loading shared libraries", "blocked"},
		{"FFmpeg exceeded 60s command limit", "fail"},
		{"VIDIOC_STREAMON failed", "fail"},
		{"unrecognized failure secret-serial SSID=private", "error"},
	}
	for _, tc := range cases {
		result := autoMediaCommandProblem("Media", tc.output, errors.New("command failed"))
		if result.Status != tc.want {
			t.Fatal(result)
		}
		if strings.Contains(result.Detail, "secret") || strings.Contains(result.Detail, "SSID=") || strings.Contains(result.Detail, "/home/private") {
			t.Fatal("private output leaked", result)
		}
	}
}

func autoMediaTestCameraFiles() map[string]string {
	files := map[string]string{"/dev/media0": "", autoMediaPrivateCam: "fake app"}
	for index, sensor := range autoMediaSensors {
		files[fmt.Sprintf("/sys/class/video4linux/v4l-subdev%d/name", index)] = sensor.model + " 0-00" + sensor.address
	}
	return files
}

const autoMediaTestCameraListing = `Available cameras:
1: Internal front camera (/base/soc/cci@ac4b000/i2c-bus@0/camera@36)
2: Internal back camera (/base/soc/cci@ac4a000/i2c-bus@0/camera@10)
3: Internal front camera (/base/soc/cci@ac4a000/i2c-bus@1/camera@60)
`

const autoMediaTestCameraFrames = `Using camera private-id as cam0
0: 632x480-BGR888/sRGB
cam0: Capture 3 frames
10.000001 (0.00 fps) cam0-stream0 seq: 000005 bytesused: 921600
 ExposureTime = 1000
10.033334 (30.00 fps) cam0-stream0 seq: 000006 bytesused: 921600
 ExposureTime = 1000
10.066667 (30.00 fps) cam0-stream0 seq: 000007 bytesused: 921600
 ExposureTime = 1000
`

func TestAutomaticMediaCaptureGatesAndRealFrames(t *testing.T) {
	c := autoMediaTestContext(t, nil, func(args ...string) (string, error) { t.Fatalf("capture without opt-in %q", args); return "", nil })
	for _, sensor := range autoMediaSensors {
		if result := autoMediaCameraFrames(c, sensor.role); result.Status != "blocked" {
			t.Fatal(result)
		}
	}
	var captured []string
	c = autoMediaTestContext(t, autoMediaTestCameraFiles(), func(args ...string) (string, error) {
		joined := strings.Join(args, " ")
		if strings.Contains(joined, "--list") {
			return autoMediaTestCameraListing, nil
		}
		if args[0] == "v4l2-ctl" {
			if !strings.Contains(joined, "--get-ctrl=test_pattern") || strings.Contains(joined, "--set") {
				t.Fatalf("unsafe sensor command %q", args)
			}
			return "test_pattern: 0\n", nil
		}
		if strings.Contains(joined, "--capture=3") {
			for _, banned := range []string{"--file", "--display", "--sdl", "--script", "modprobe", "--set", "led"} {
				if strings.Contains(joined, banned) {
					t.Fatalf("unsafe capture command %q", args)
				}
			}
			if !strings.Contains(joined, "LIBCAMERA_SOFTISP_MODE=cpu") || !strings.Contains(joined, autoMediaPrivateCam) {
				t.Fatalf("wrong ISP path %q", args)
			}
			captured = append(captured, joined)
			return autoMediaTestCameraFrames, nil
		}
		t.Fatalf("unexpected %q", args)
		return "", nil
	})
	c.Options.Capture = true
	for _, sensor := range autoMediaSensors {
		result := autoMediaCameraFrames(c, sensor.role)
		if result.Status != "pass" {
			t.Fatalf("%s: %+v", sensor.role, result)
		}
	}
	if len(captured) != 3 {
		t.Fatal(captured)
	}
	for index, sensor := range autoMediaSensors {
		if !strings.Contains(captured[index], "/camera@"+sensor.address) {
			t.Fatalf("wrong sensor %s", captured[index])
		}
	}
}

func TestAutomaticMediaCameraFrameEvidence(t *testing.T) {
	cases := []struct{ name, text string }{
		{"no frames", "camera started and exited zero"},
		{"partial frames", strings.ReplaceAll(autoMediaTestCameraFrames, "bytesused: 921600", "bytesused: 20")},
		{"repeated sequence", strings.ReplaceAll(autoMediaTestCameraFrames, "seq: 000006", "seq: 000005")},
		{"repeated timestamps", strings.ReplaceAll(autoMediaTestCameraFrames, "10.033334", "10.000001")},
		{"raw not processed", strings.ReplaceAll(autoMediaTestCameraFrames, "-BGR888", "-Y10")},
		{"stop failed", autoMediaTestCameraFrames + "Failed to stop capture\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if result := autoMediaCameraFrameEvidence(tc.text); result.Status != "fail" {
				t.Fatal(result)
			}
		})
	}
	c := autoMediaTestContext(t, autoMediaTestCameraFiles(), func(args ...string) (string, error) {
		if args[0] == "v4l2-ctl" {
			return "test_pattern: 1", nil
		}
		if strings.Contains(strings.Join(args, " "), "--capture") {
			t.Fatal("synthetic capture attempted")
		}
		return autoMediaTestCameraListing, nil
	})
	c.Options.Capture = true
	if result := autoMediaCameraFrames(c, "ir"); result.Status != "blocked" {
		t.Fatal(result)
	}
}

func TestAutomaticMediaCameraInventoryNotCapture(t *testing.T) {
	c := autoMediaTestContext(t, autoMediaTestCameraFiles(), func(args ...string) (string, error) {
		joined := strings.Join(args, " ")
		if strings.Contains(joined, "--capture") {
			t.Fatal("inventory captured")
		}
		if args[0] == "media-ctl" {
			return "Media controller\ndriver qcom-camss\n- entity 1: ov5693 1-0036 (1 pad, 1 link)\n- entity 2: ov13858 2-0010 (1 pad, 1 link)\n- entity 3: ov7251 3-0060 (1 pad, 1 link)\n [ENABLED,IMMUTABLE]\n", nil
		}
		if strings.Contains(joined, "--list-properties") {
			model := ""
			for _, sensor := range autoMediaSensors {
				if strings.Contains(joined, "/camera@"+sensor.address) {
					model = sensor.model
				}
			}
			return "Property: Model = " + model + "\nProperty: PixelArraySize = 640x480\nProperty: Location = 0 (CameraLocationFront)\nProperty: Rotation = 180\nProperty: SerialNumber = private-never-report\nControl: ExposureTime: [1..10000]\n", nil
		}
		return autoMediaTestCameraListing, nil
	})
	for _, result := range []AutoResult{autoMediaCameraGraph(c), autoMediaCameraMetadata(c)} {
		if result.Status != "observed" {
			t.Fatal(result)
		}
		if strings.Contains(result.Detail, "private-never-report") || strings.Contains(result.Detail, "/base/") {
			t.Fatal("private metadata leaked", result)
		}
	}
	c.Run = func(args ...string) (string, error) {
		return strings.ReplaceAll(autoMediaTestCameraListing, "camera@36", "camera@55"), nil
	}
	if result := autoMediaCameraMetadata(c); result.Status != "blocked" {
		t.Fatal(result)
	}
}

func TestAutomaticMediaCatalogNeverAttemptsEncoder(t *testing.T) {
	c := autoMediaTestContext(t, nil, func(args ...string) (string, error) { t.Fatalf("parked encoder command %q", args); return "", nil })
	checks := automaticMediaChecks()
	if len(checks) != 12 {
		t.Fatalf("catalog rows=%d", len(checks))
	}
	for _, check := range checks {
		if check.ID == "media.encode" {
			if result := check.Run(c); result.Status != "blocked" {
				t.Fatal(result)
			}
		}
		if check.Kind != "inventory" && check.Kind != "functional" {
			t.Fatal(check)
		}
	}
}
