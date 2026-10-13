// Bounded fresh SSC delivery through the already-running SensorsPD provider.
package main

import (
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

const automaticSSCPrivate = "/usr/local/libexec/spx-sensors/libssc"

// READY is supplied by the existing notify service; never create an attachment.
func automaticSSCProvider(c *AutoContext) (pid, library, reason string) {
	out, err := c.Command("systemctl", "show", "spx-sensors.service", "--property=LoadState,ActiveState,SubState,MainPID,Environment", "--no-pager")
	if err != nil {
		return "", "", "Provider query unavailable (systemctl, bus or permission)"
	}
	values := map[string]string{}
	for _, line := range strings.Split(out, "\n") {
		if pair := strings.SplitN(line, "=", 2); len(pair) == 2 {
			values[pair[0]] = pair[1]
		}
	}
	if values["LoadState"] != "loaded" || values["ActiveState"] != "active" || values["SubState"] != "running" {
		return "", "", "spx-sensors.service is not already loaded/READY/running; no service or DSP started"
	}
	n, err := strconv.ParseUint(values["MainPID"], 10, 32)
	if err != nil || n == 0 {
		return "", "", "Running provider PID unavailable"
	}
	pid = strconv.FormatUint(n, 10)
	for _, word := range strings.Fields(values["Environment"]) {
		word = strings.Trim(word, `"`)
		if strings.HasPrefix(word, "LD_LIBRARY_PATH=") {
			if word != "LD_LIBRARY_PATH="+automaticSSCPrivate {
				return "", "", "Provider selects an unsupported libssc path; no guessed library fallback"
			}
			library = automaticSSCPrivate
		}
	}
	return pid, library, ""
}

func automaticSSCSamples(output, sensor string) (count int, finite bool) {
	finite = true
	prefix := strings.ToUpper(sensor[:1]) + sensor[1:] + " sensor measurement: "
	for _, line := range strings.Split(output, "\n") {
		if !strings.HasPrefix(line, prefix) {
			continue
		}
		fields := strings.Fields(strings.TrimPrefix(line, prefix))
		valid := len(fields) >= 3
		if valid {
			for i, axis := range []string{"X=", "Y=", "Z="} {
				if !strings.HasPrefix(fields[i], axis) {
					valid = false
					break
				}
				v, err := strconv.ParseFloat(strings.TrimPrefix(fields[i], axis), 64)
				if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
					valid = false
				}
			}
		}
		finite = finite && valid
		if valid {
			count++
		}
	}
	return count, finite
}

func automaticSSCMotion(c *AutoContext) AutoResult {
	const id = "sensors.motion-read"
	if c.Fixture {
		return interfacesResult(id, "blocked", "SSC fresh delivery disabled for fixture root; no external commands")
	}
	if c.Run == nil && os.Geteuid() != 0 {
		return interfacesResult(id, "blocked", "SSC delivery requires the existing root validator; no guessed user or capability grant")
	}
	pid, library, reason := automaticSSCProvider(c)
	if reason != "" {
		return interfacesResult(id, "blocked", reason)
	}
	paths, _ := c.Glob("/sys/class/remoteproc/remoteproc*")
	firmware := 0
	for _, path := range paths {
		name, _ := c.Read(path + "/name")
		image, _ := c.Read(path + "/firmware")
		state, _ := c.Read(path + "/state")
		if name == "slpi" && image == "qcom/microsoft/spx/qcslpi8180.mbn" && state == "running" {
			firmware++
		}
	}
	if firmware != 1 {
		return interfacesResult(id, "blocked", "Exact SPX SLPI firmware is not uniquely already running/readable; no firmware or DSP started")
	}
	if library != "" {
		paths, err := c.Glob(library + "/libssc.so.2")
		if err != nil || len(paths) != 1 {
			return interfacesResult(id, "blocked", "Provider-selected private libssc.so.2 unavailable; no library fallback")
		}
	}
	var counts []string
	for _, sensor := range []string{"accelerometer", "gyroscope", "magnetometer"} {
		args := []string{"timeout", "--signal=TERM", "--kill-after=2s", "12s", "env", "-u", "LD_LIBRARY_PATH"}
		if library != "" {
			args = append(args, "LD_LIBRARY_PATH="+library)
		}
		args = append(args, "ssccli", "--debug", "--sensor", sensor, "--timeout", "3")
		out, err := c.Command(args...)
		count, finite := automaticSSCSamples(out, sensor)
		enable := strings.Contains(out, "Sensor enable request sent successfully")
		disable := strings.Contains(out, "Sensor disable request sent successfully")
		failed := false
		for _, message := range []string{"Unable to open ", "Unable to close ", "Sensor enable request failed:", "Sensor disable request failed:", "QMI request failed:", "Sensor attribute request failed:", "Could not release SSC QMI client:", "Could not close SSC QMI client:", "Failed to unpack", "Cannot extract Protobuf data"} {
			failed = failed || strings.Contains(out, message)
		}
		if !failed && count == 0 && !enable {
			var execErr *exec.Error
			missing := errors.As(err, &execErr) || errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission)
			for _, message := range []string{"No such file or directory", "Permission denied", "error while loading shared libraries:", "symbol lookup error:", "SSC QMI Service not found", "Sensor service unavailable", "'registry' sensor unavailable", "QRTR bus unavailable", "Only QRTR QMI devices are supported"} {
				missing = missing || strings.Contains(out, message)
			}
			if missing {
				return interfacesResult(id, "blocked", sensor+": installed CLI/library, QRTR permission/service or sensor firmware prerequisite unavailable; raw output discarded")
			}
		}
		if err != nil || failed || !finite || count < 20 || !enable || !disable {
			return interfacesResult(id, "fail", fmt.Sprintf("%s: finite XYZ rows=%d (minimum 20), all rows finite/valid=%t, enable ACK=%t, disable ACK=%t, CLI exit0=%t, operation failure=%t; bounded fresh delivery/clean close not established; raw output discarded", sensor, count, finite, enable, disable, err == nil, failed))
		}
		counts = append(counts, fmt.Sprintf("%s=%d", sensor, count))
	}
	currentPID, currentLibrary, reason := automaticSSCProvider(c)
	if reason != "" || currentPID != pid || currentLibrary != library {
		return interfacesResult(id, "fail", "Provider or selected library changed or became unavailable during delivery; no startup, reset, reload or reattachment attempted; raw output discarded")
	}
	return interfacesResult(id, "pass", "Fresh finite XYZ rows: "+strings.Join(counts, ", ")+"; each CLI exit0 with enable/disable ACKs, requested stream=3s, outer TERM=12s/KILL-after=2s; same already-running provider; raw samples/logs discarded; no physical axes, mounting, calibration, rotation or resume claim")
}
