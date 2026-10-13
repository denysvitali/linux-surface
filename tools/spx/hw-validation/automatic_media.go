package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// The sensor/DT-address mapping and CPU software-ISP path are the verified
// recipes in camera.py and tools/spx/libcamera/README.md, not format claims.
var autoMediaSensors = []struct{ role, model, address, box string }{
	{"front", "ov5693", "36", "C02"},
	{"rear", "ov13858", "10", "C03"},
	{"ir", "ov7251", "60", "C04"},
}

const autoMediaPrivateCam = "/var/tmp/spx-libcamera-0.7.2/build/src/apps/cam/cam"
const autoMediaDecodeFrameLimit = 30
const autoMediaDecodeSeconds = 2

type autoMediaDecodeRun struct {
	codec  string
	result AutoResult
}

func automaticMediaChecks() []AutoCheck {
	checks := []AutoCheck{
		{ID: "media.decode.formats", Title: "Exposed Venus decoder formats", Area: "Video", Kind: "inventory", Boxes: []string{"D03"}, Run: autoMediaDecodeFormats},
		{ID: "media.encode", Title: "Hardware encoder workload", Area: "Video", Kind: "functional", Boxes: []string{"D03"}, Run: func(c *AutoContext) AutoResult {
			return AutoResult{Status: "blocked", Detail: "Encoder trials parked: known CVP fault/reset/hang and unresolved protected-buffer/recovery contract; no encoder open, autoload or workload attempted"}
		}},
		{ID: "camera.graph", Title: "CAMSS media graph integration", Area: "Cameras", Kind: "inventory", Boxes: []string{"C01", "C02", "C03", "C04", "C05"}, Run: autoMediaCameraGraph},
		{ID: "camera.libcamera", Title: "Libcamera fitted-sensor metadata", Area: "Cameras", Kind: "inventory", Boxes: []string{"C01", "C02", "C03", "C04", "C05"}, Run: autoMediaCameraMetadata},
	}
	for _, codec := range []struct{ name, title string }{
		{"h264", "H.264"}, {"hevc", "HEVC"}, {"mpeg2video", "MPEG-2"}, {"vp8", "VP8"}, {"vp9", "VP9"},
	} {
		codec := codec
		checks = append(checks, AutoCheck{ID: "media.decode." + codec.name, Title: codec.title + " hardware decode of supplied real media", Area: "Video", Kind: "functional", Boxes: []string{"D03"}, Run: func(c *AutoContext) AutoResult {
			result := autoMediaDecode(c)
			if actual := c.mediaDecode.codec; actual != "" && actual != codec.name {
				return AutoResult{Status: "blocked", Detail: "Supplied fixture codec=" + actual + "; a verified " + codec.title + " fixture and supported hardware decoder are required. Another codec's result cannot establish this workload; no extra decode attempted"}
			}
			return result
		}})
	}
	for _, sensor := range autoMediaSensors {
		role, box := sensor.role, sensor.box
		checks = append(checks, AutoCheck{ID: "camera." + role + ".frames", Title: strings.ToUpper(role[:1]) + role[1:] + " processed frame delivery", Area: "Cameras", Kind: "functional", Boxes: []string{box, "C05"}, Run: func(c *AutoContext) AutoResult {
			return autoMediaCameraFrames(c, role)
		}})
	}
	return checks
}

func autoMediaNodes(c *AutoContext, name string) ([]string, error) {
	paths, err := c.Glob("/sys/class/video4linux/video*")
	if err != nil {
		return nil, err
	}
	var nodes []string
	for _, path := range paths {
		value, e := c.Read(path + "/name")
		if e != nil {
			return nil, e
		}
		if strings.TrimSpace(value) == name {
			nodes = append(nodes, "/dev/"+filepath.Base(path))
		}
	}
	return nodes, nil
}

var autoMediaFourCC = regexp.MustCompile(`(?m)^\s*\[\d+\]:\s*'([A-Za-z0-9 ]{4})'`)

func autoMediaDecodeFormats(c *AutoContext) AutoResult {
	nodes, err := autoMediaNodes(c, "qcom-venus-decoder")
	if err != nil || len(nodes) == 0 {
		return AutoResult{Status: "blocked", Detail: "No exposed qcom-venus-decoder node; running Venus decoder support/permissions are needed (hardware absence is not established)"}
	}
	formats := map[string]bool{}
	for _, node := range nodes {
		output, e := c.Command("v4l2-ctl", "--device", node, "--list-formats-out")
		if e != nil {
			return autoMediaCommandProblem("V4L2 decoder format enumeration", output, e)
		}
		for _, match := range autoMediaFourCC.FindAllStringSubmatch(output, -1) {
			formats[match[1]] = true
		}
	}
	if len(formats) == 0 {
		return AutoResult{Status: "blocked", Detail: "Decoder format enumeration returned no parseable compressed-input FourCCs; needs v4l2-ctl output support/permissions"}
	}
	var names []string
	for name := range formats {
		names = append(names, name)
	}
	sort.Strings(names)
	return AutoResult{Status: "observed", Detail: fmt.Sprintf("%d exposed Venus decoder node(s); advertised compressed-input formats: %s; enumeration does not prove any codec workload; encoder is parked", len(nodes), strings.Join(names, ", "))}
}

func autoMediaDecode(c *AutoContext) AutoResult {
	// Per-codec requirements share one attempt: don't replay a successful fixture
	// or mistake that codec's evidence for any other advertised decoder format.
	if c.mediaDecode == nil {
		c.mediaDecode = &autoMediaDecodeRun{}
		c.mediaDecode.result = autoMediaDecodeFixture(c, &c.mediaDecode.codec)
	}
	return c.mediaDecode.result
}

func autoMediaDecodeFixture(c *AutoContext, codec *string) AutoResult {
	if c.Options.Media == "" {
		return AutoResult{Status: "blocked", Detail: "Supply --media=/path/to/real-video fixture; needs exposed Venus decoder, ffprobe and FFmpeg V4L2 decoder; no synthetic or software-decode substitute"}
	}
	if !filepath.IsAbs(c.Options.Media) {
		return AutoResult{Status: "blocked", Detail: "--media must name an absolute local regular-file real-video fixture, not a URL or pipe"}
	}
	root := c.Root
	if root == "" {
		root = "/"
	}
	fixture := filepath.Join(root, strings.TrimPrefix(filepath.Clean(c.Options.Media), "/"))
	info, err := os.Stat(fixture)
	if err != nil || !info.Mode().IsRegular() {
		return AutoResult{Status: "blocked", Detail: "Supplied real-video fixture is not an accessible regular file"}
	}
	nodes, err := autoMediaNodes(c, "qcom-venus-decoder")
	if err != nil || len(nodes) == 0 {
		return AutoResult{Status: "blocked", Detail: "Real fixture supplied, but no exposed qcom-venus-decoder node; install/enable coherent running decoder support separately; no modules loaded by this test"}
	}
	// FFmpeg's V4L2 discovery scans exposed video nodes. Never let that scan
	// open the parked encoder; module policy belongs to the coordinator.
	encoders, encoderErr := autoMediaNodes(c, "qcom-venus-encoder")
	loadedEncoder, moduleErr := c.Glob("/sys/module/venus_enc")
	if encoderErr != nil || moduleErr != nil || len(encoders) != 0 || len(loadedEncoder) != 0 {
		return AutoResult{Status: "blocked", Detail: "Cannot safely scan V4L2 devices while encoder is exposed/loaded or its state is unreadable; parked encoder must remain unexposed, no module policy changes attempted"}
	}
	output, err := c.Command("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height", "-of", "json", "-i", c.Options.Media)
	if err != nil {
		return autoMediaCommandProblem("Real-video fixture probe", output, err)
	}
	var probe struct {
		Streams []struct {
			Codec  string `json:"codec_name"`
			Width  int    `json:"width"`
			Height int    `json:"height"`
		} `json:"streams"`
	}
	if json.Unmarshal([]byte(output), &probe) != nil || len(probe.Streams) != 1 || probe.Streams[0].Width <= 0 || probe.Streams[0].Height <= 0 {
		return AutoResult{Status: "blocked", Detail: "ffprobe did not identify one valid video stream in the supplied real fixture"}
	}
	stream := probe.Streams[0]
	*codec = stream.Codec
	output, err = c.Command("ffmpeg", "-hide_banner", "-decoders")
	if err != nil {
		return autoMediaCommandProblem("FFmpeg decoder inventory", output, err)
	}
	decoder := autoMediaV4L2Decoder(output, stream.Codec)
	if decoder == "" {
		return AutoResult{Status: "blocked", Detail: "Installed FFmpeg has no explicit V4L2 mem2mem decoder for the supplied fixture codec; no software fallback attempted"}
	}
	output, err = c.Command("ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "verbose", "-nostats", "-xerror", "-c:v", decoder, "-i", c.Options.Media,
		"-map", "0:v:0", "-an", "-sn", "-dn", "-t", strconv.Itoa(autoMediaDecodeSeconds), "-frames:v", strconv.Itoa(autoMediaDecodeFrameLimit), "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-")
	if err != nil {
		return autoMediaCommandProblem("Explicit hardware fixture decode", output, err)
	}
	return autoMediaDecodeEvidence(output, decoder, nodes, stream.Width, stream.Height)
}

func autoMediaV4L2Decoder(output, codec string) string {
	if !regexp.MustCompile(`^[a-z0-9_]+$`).MatchString(codec) {
		return ""
	}
	for _, line := range strings.Split(output, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 || !strings.HasPrefix(fields[0], "V") || !strings.HasSuffix(fields[1], "_v4l2m2m") {
			continue
		}
		if fields[1] == codec+"_v4l2m2m" || strings.Contains(line, "(codec "+codec+")") {
			return fields[1]
		}
	}
	return ""
}

var autoMediaDecodeInput = regexp.MustCompile(`Input stream #0:\d+ \(video\):[^\n]*?([0-9]+) frames decoded; ([0-9]+) decode errors`)
var autoMediaDecodeOutput = regexp.MustCompile(`Output stream #0:\d+ \(video\): ([0-9]+) frames encoded;`)
var autoMediaProgressFrames = regexp.MustCompile(`(?m)^frame=\s*([0-9]+)\s*$`)

func autoMediaDecodeEvidence(output, decoder string, nodes []string, width, height int) AutoResult {
	driver := regexp.MustCompile(`driver 'qcom-venus' on card '[^'\n]*[Dd]ecoder'`)
	mapping := regexp.MustCompile(`Stream #0:\d+ -> #0:\d+ \([^\n]*\(` + regexp.QuoteMeta(decoder) + `\) ->`)
	selected := false
	for _, node := range nodes {
		if strings.Contains(output, "Using device "+node+"\n") || strings.HasSuffix(output, "Using device "+node) {
			selected = true
		}
	}
	if !selected || !driver.MatchString(output) || !mapping.MatchString(output) {
		return AutoResult{Status: "fail", Detail: "Decode lacked selected Venus decoder device/driver and explicit V4L2 input-stream mapping; hardware acceleration was not proved"}
	}
	input, emitted := autoMediaDecodeInput.FindStringSubmatch(output), autoMediaDecodeOutput.FindStringSubmatch(output)
	progress := autoMediaProgressFrames.FindAllStringSubmatch(output, -1)
	if len(input) == 0 || len(emitted) == 0 || len(progress) == 0 || !strings.Contains(output, "progress=end") {
		return AutoResult{Status: "fail", Detail: "Hardware decode exited without complete decoded/output/progress frame-count evidence"}
	}
	decoded, _ := strconv.Atoi(input[1])
	errors, _ := strconv.Atoi(input[2])
	frames, _ := strconv.Atoi(emitted[1])
	final, _ := strconv.Atoi(progress[len(progress)-1][1])
	if errors != 0 || frames <= 0 || frames > autoMediaDecodeFrameLimit || final != frames || decoded < frames {
		return AutoResult{Status: "fail", Detail: fmt.Sprintf("Venus frame-count/error predicate failed: decoded=%d output=%d progress=%d decode_errors=%d", decoded, frames, final, errors)}
	}
	if frames < autoMediaDecodeFrameLimit {
		if decoded >= autoMediaDecodeFrameLimit {
			return AutoResult{Status: "fail", Detail: "Hardware decoded enough frames but did not deliver the requested complete 30-frame output"}
		}
		return AutoResult{Status: "blocked", Detail: "Fixture did not supply the required 30 decoded frames within the 2s media limit; supply a longer/higher-rate real fixture; no complete startup baseline pass"}
	}
	return AutoResult{Status: "pass", Detail: fmt.Sprintf("Supplied %dx%d fixture: %s on Venus; decoded=%d output=%d, zero decode errors, complete progress; capped at %ds/%d frames, output discarded. Only this fixture codec/path tested; not encoder, all formats, pixels or sustained playback", width, height, decoder, decoded, frames, autoMediaDecodeSeconds, autoMediaDecodeFrameLimit)}
}

func autoMediaCommandProblem(label, output string, err error) AutoResult {
	text := strings.ToLower(output + " " + err.Error())
	reasons := []struct{ match, reason string }{
		{"permission denied", "permission denied; device/file access is required"},
		{"operation not permitted", "operation not permitted; device/file access is required"},
		{"executable file not found", "required userspace executable is not installed"},
		{"no such file or directory", "required executable, library, fixture or device is unavailable"},
		{"error while loading shared libraries", "required userspace shared library is unavailable"},
		{"fixture root", "external execution is disabled for fixture-root runs"},
		{"device or resource busy", "camera/decoder is busy; release the competing client"},
		{"failed to acquire camera", "camera is not available for exclusive acquisition"},
		{"could not find a valid device", "no compatible exposed V4L2 decoder supports this fixture codec"},
		{"unknown decoder", "installed FFmpeg lacks the requested hardware decoder"},
		{"invalid data found when processing input", "supplied fixture is not valid supported media"},
	}
	for _, reason := range reasons {
		if strings.Contains(text, reason.match) {
			return AutoResult{Status: "blocked", Detail: label + ": " + reason.reason}
		}
	}
	for _, match := range []string{"timed out", "deadline exceeded", "command limit", "failed to start capture", "failed to configure camera", "can't queue request", "vidioc", "decode error", "failed to initialise", "failed to initialize"} {
		if strings.Contains(text, match) {
			return AutoResult{Status: "fail", Detail: label + ": stream configuration/delivery failed or timed out; no raw log retained in report"}
		}
	}
	return AutoResult{Status: "error", Detail: label + ": userspace command failed without a recognized prerequisite or hardware-fault reason; no raw log retained in report"}
}

func autoMediaCameraGraph(c *AutoContext) AutoResult {
	paths, err := c.Glob("/dev/media*")
	if err != nil || len(paths) == 0 {
		return AutoResult{Status: "blocked", Detail: "No accessible media-controller nodes; running CAMSS/sensor graph support is needed (hardware absence is not established)"}
	}
	found := map[string]bool{}
	graphs, links := 0, 0
	for _, path := range paths {
		output, e := c.Command("media-ctl", "--device", path, "--print-topology")
		if e != nil {
			return autoMediaCommandProblem("CAMSS media graph enumeration", output, e)
		}
		if !strings.Contains(strings.ToLower(output), "camss") {
			continue
		}
		graphs++
		links += strings.Count(output, "[ENABLED")
		for _, sensor := range autoMediaSensors {
			if regexp.MustCompile(`(?m)^- entity \d+: ` + sensor.model + `(?:\s|\()`).MatchString(output) {
				found[sensor.role] = true
			}
		}
	}
	var roles, missing []string
	for _, sensor := range autoMediaSensors {
		if found[sensor.role] {
			roles = append(roles, sensor.role)
		} else {
			missing = append(missing, sensor.role)
		}
	}
	detail := fmt.Sprintf("CAMSS graphs=%d, enabled links=%d, fitted sensor entities=%s", graphs, links, strings.Join(roles, ","))
	if len(missing) > 0 {
		return AutoResult{Status: "blocked", Detail: detail + "; missing registered sensor graph support for " + strings.Join(missing, ",") + "; no overlays, modules or link changes attempted"}
	}
	return AutoResult{Status: "observed", Detail: detail + "; enumeration is not regulator ownership, frame delivery or full graph acceptance"}
}

type autoMediaCamera struct{ id, model string }

var autoMediaCameraRow = regexp.MustCompile(`(?m)^\d+: .*\(([^()]+)\)\s*$`)
var autoMediaProperty = regexp.MustCompile(`(?m)^Property: ([A-Za-z]+) = ([^\n]+)$`)

func autoMediaCamArgs(c *AutoContext) ([]string, string) {
	app, origin := "cam", "installed libcamera"
	paths, err := c.Glob(autoMediaPrivateCam)
	if err == nil && len(paths) == 1 {
		app, origin = autoMediaPrivateCam, "verified private libcamera/CPU ISP (not distro integration)"
	}
	return []string{"env", "LIBCAMERA_SOFTISP_MODE=cpu", "LIBCAMERA_LOG_LEVELS=*:ERROR", app}, origin
}

func autoMediaCameras(c *AutoContext) ([]string, string, map[string]autoMediaCamera, AutoResult) {
	args, origin := autoMediaCamArgs(c)
	output, err := c.Command(append(append([]string{}, args...), "--list")...)
	if err != nil {
		return args, origin, nil, autoMediaCommandProblem("Libcamera sensor enumeration", output, err)
	}
	cameras := map[string]autoMediaCamera{}
	for _, row := range autoMediaCameraRow.FindAllStringSubmatch(output, -1) {
		id := row[1]
		for _, sensor := range autoMediaSensors {
			// Camera IDs encode the DT sensor address in the tested simple pipeline.
			if strings.Contains(strings.ToLower(id), sensor.model) || strings.HasSuffix(strings.ToLower(id), "/camera@"+sensor.address) {
				if _, duplicate := cameras[sensor.role]; duplicate {
					return args, origin, nil, AutoResult{Status: "blocked", Detail: "Libcamera sensor selection is ambiguous; multiple cameras match one fitted sensor"}
				}
				cameras[sensor.role] = autoMediaCamera{id: id, model: sensor.model}
			}
		}
	}
	return args, origin, cameras, AutoResult{}
}

func autoMediaCameraMetadata(c *AutoContext) AutoResult {
	args, origin, cameras, problem := autoMediaCameras(c)
	if problem.Status != "" {
		return problem
	}
	var parts, missing []string
	for _, sensor := range autoMediaSensors {
		camera, ok := cameras[sensor.role]
		if !ok {
			missing = append(missing, sensor.role+" not exposed by libcamera")
			continue
		}
		output, err := c.Command(append(append([]string{}, args...), "--camera", camera.id, "--list-properties", "--list-controls")...)
		if err != nil {
			return autoMediaCommandProblem("Libcamera "+sensor.role+" metadata", output, err)
		}
		properties := map[string]string{}
		for _, row := range autoMediaProperty.FindAllStringSubmatch(output, -1) {
			properties[row[1]] = strings.TrimSpace(row[2])
		}
		model := strings.ToLower(strings.Trim(properties["Model"], "\"'"))
		size := regexp.MustCompile(`^\d+x\d+$`).FindString(properties["PixelArraySize"])
		if model != sensor.model || size == "" {
			missing = append(missing, sensor.role+" Model/PixelArraySize metadata missing or mismatched")
			continue
		}
		part := sensor.role + " model=" + sensor.model + " pixel_array=" + size
		for _, key := range []string{"Location", "Rotation"} {
			value := regexp.MustCompile(`^-?\d+`).FindString(properties[key])
			if value != "" {
				part += " " + strings.ToLower(key) + "=" + value
			}
		}
		part += fmt.Sprintf(" controls=%d", strings.Count(output, "Control: "))
		parts = append(parts, part)
	}
	detail := origin + "; " + strings.Join(parts, "; ")
	if len(missing) > 0 {
		return AutoResult{Status: "blocked", Detail: detail + "; " + strings.Join(missing, "; ") + "; needs running sensor graph/userspace support, not evidence of hardware absence"}
	}
	return AutoResult{Status: "observed", Detail: detail + "; metadata enumeration only, no capture or normal-app integration claim"}
}

func autoMediaCameraFrames(c *AutoContext, role string) AutoResult {
	if !c.Options.Capture {
		return AutoResult{Status: "blocked", Detail: role + " camera capture requires explicit --capture opt-in; three processed frames would be discarded in memory, no IR emitter or retained images"}
	}
	args, origin, cameras, problem := autoMediaCameras(c)
	if problem.Status != "" {
		return problem
	}
	camera, ok := cameras[role]
	if !ok {
		return AutoResult{Status: "blocked", Detail: role + " fitted sensor is not exposed by libcamera; needs running enabled sensor graph and matching libcamera support; no module/overlay changes attempted"}
	}
	subdevs, err := c.Glob("/sys/class/video4linux/v4l-subdev*")
	if err != nil {
		return AutoResult{Status: "blocked", Detail: role + " sensor subdevice enumeration is inaccessible; cannot verify native test pattern is off"}
	}
	var subdev string
	for _, path := range subdevs {
		name, e := c.Read(path + "/name")
		if e == nil && strings.HasPrefix(name, camera.model+" ") {
			if subdev != "" {
				return AutoResult{Status: "blocked", Detail: role + " native sensor subdevice selection is ambiguous"}
			}
			subdev = "/dev/" + filepath.Base(path)
		}
	}
	if subdev == "" {
		return AutoResult{Status: "blocked", Detail: role + " native sensor subdevice is not exposed; cannot verify real-scene mode"}
	}
	output, err := c.Command("v4l2-ctl", "--device", subdev, "--get-ctrl=test_pattern")
	if err != nil {
		return autoMediaCommandProblem(role+" sensor test-pattern state", output, err)
	}
	if !regexp.MustCompile(`(?m)^\s*test_pattern:\s*0\s*$`).MatchString(output) {
		return AutoResult{Status: "blocked", Detail: role + " native test pattern is active or its state is unreadable; no synthetic camera frames or control writes attempted"}
	}
	output, err = c.Command(append(append([]string{}, args...), "--camera", camera.id, "--info", "--stream", "role=viewfinder,width=1280,height=960,pixelformat=BGR888", "--capture=3", "--metadata")...)
	if err != nil {
		return autoMediaCommandProblem(role+" processed capture", output, err)
	}
	result := autoMediaCameraFrameEvidence(output)
	result.Detail = role + ": " + origin + "; " + result.Detail
	return result
}

var autoMediaFrameRow = regexp.MustCompile(`(?m)^([0-9]+)\.([0-9]{6}) \([0-9.]+ fps\) cam0-stream0 seq:\s*([0-9]+) bytesused:\s*([0-9]+)\s*$`)
var autoMediaStreamSize = regexp.MustCompile(`(?m)^0: ([0-9]+)x([0-9]+)-BGR888(?:/[^\r\n]+)?\s*$`)

func autoMediaCameraFrameEvidence(output string) AutoResult {
	size := autoMediaStreamSize.FindStringSubmatch(output)
	rows := autoMediaFrameRow.FindAllStringSubmatch(output, -1)
	if len(size) == 0 || len(rows) != 3 {
		return AutoResult{Status: "fail", Detail: fmt.Sprintf("Expected three actual completed BGR888 frames with stream dimensions; observed frame records=%d", len(rows))}
	}
	width, _ := strconv.ParseInt(size[1], 10, 64)
	height, _ := strconv.ParseInt(size[2], 10, 64)
	var lastTS, lastSeq int64
	for index, row := range rows {
		sec, _ := strconv.ParseInt(row[1], 10, 64)
		us, _ := strconv.ParseInt(row[2], 10, 64)
		seq, _ := strconv.ParseInt(row[3], 10, 64)
		bytes, _ := strconv.ParseInt(row[4], 10, 64)
		ts := sec*1000000 + us
		if width <= 0 || height <= 0 || bytes < width*height*3 || ts <= lastTS || (index > 0 && seq != lastSeq+1) {
			return AutoResult{Status: "fail", Detail: "Completed camera frames have incomplete payload, repeated/out-of-order timestamps or nonconsecutive sequence numbers"}
		}
		lastTS, lastSeq = ts, seq
	}
	for _, failure := range []string{"Failed to stop capture", "Failed to start capture", "Failed to configure camera"} {
		if strings.Contains(output, failure) {
			return AutoResult{Status: "fail", Detail: "Camera start/configure/stop reported failure despite completed frame records"}
		}
	}
	return AutoResult{Status: "pass", Detail: fmt.Sprintf("Three consecutive complete %dx%d BGR888 frames with increasing timestamps; native test pattern off; memory-only discard, no emitter activation. Proves short processed delivery only, not image quality, illumination, app packaging or resume", width, height)}
}
