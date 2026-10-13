package main

import (
	"errors"
	"fmt"
	"os/exec"
	"reflect"
	"strings"
	"testing"
)

func sscTestContext(t *testing.T, service string, stream func(string) (string, error)) (*AutoContext, *[]string) {
	t.Helper()
	c := interfacesFixture(t, map[string]string{
		"/sys/class/remoteproc/remoteproc0/name":     "slpi",
		"/sys/class/remoteproc/remoteproc0/firmware": "qcom/microsoft/spx/qcslpi8180.mbn",
		"/sys/class/remoteproc/remoteproc0/state":    "running",
		automaticSSCPrivate + "/libssc.so.2":         "mock library",
	})
	calls := []string{}
	c.Run = func(args ...string) (string, error) {
		if args[0] == "systemctl" {
			want := []string{"systemctl", "show", "spx-sensors.service", "--property=LoadState,ActiveState,SubState,MainPID,Environment", "--no-pager"}
			if !reflect.DeepEqual(args, want) {
				t.Fatalf("unexpected provider action: %v", args)
			}
			return service, nil
		}
		if len(args) != 14 {
			t.Fatalf("unexpected stream action: %v", args)
		}
		sensor := args[11]
		want := []string{"timeout", "--signal=TERM", "--kill-after=2s", "12s", "env", "-u", "LD_LIBRARY_PATH", "LD_LIBRARY_PATH=" + automaticSSCPrivate, "ssccli", "--debug", "--sensor", sensor, "--timeout", "3"}
		if !reflect.DeepEqual(args, want) {
			t.Fatalf("unbounded or mismatched CLI: %v", args)
		}
		calls = append(calls, sensor)
		return stream(sensor)
	}
	return c, &calls
}

const sscTestReady = "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=120\nEnvironment=LD_LIBRARY_PATH=" + automaticSSCPrivate

func sscTestStream(sensor string) string {
	var out strings.Builder
	out.WriteString("Sensor enable request sent successfully\n")
	for i := 0; i < 20; i++ {
		fmt.Fprintf(&out, "%s sensor measurement: X=1.25 Y=-2.5 Z=0.000000 units\n", strings.ToUpper(sensor[:1])+sensor[1:])
	}
	out.WriteString("Sensor disable request sent successfully\n")
	return out.String()
}

func TestSSCMotionFreshDelivery(t *testing.T) {
	c, calls := sscTestContext(t, sscTestReady, func(sensor string) (string, error) { return sscTestStream(sensor), nil })
	result := automaticSSCMotion(c)
	if result.ID != "sensors.motion-read" || result.Status != "pass" || !reflect.DeepEqual(*calls, []string{"accelerometer", "gyroscope", "magnetometer"}) {
		t.Fatalf("%+v calls=%v", result, *calls)
	}
	if !strings.Contains(result.Detail, "accelerometer=20, gyroscope=20, magnetometer=20") || strings.Contains(result.Detail, "X=1.25") {
		t.Fatalf("counts missing or samples retained: %+v", result)
	}
}

func TestSSCMotionPrerequisites(t *testing.T) {
	c, calls := sscTestContext(t, "LoadState=loaded\nActiveState=failed\nSubState=failed", func(string) (string, error) { t.Fatal("stream without READY provider"); return "", nil })
	if result := automaticSSCMotion(c); result.Status != "blocked" || len(*calls) != 0 {
		t.Fatalf("%+v calls=%v", result, *calls)
	}
	c.Fixture = true
	c.Run = func(...string) (string, error) { t.Fatal("command in fixture mode"); return "", nil }
	if result := automaticSSCMotion(c); result.Status != "blocked" {
		t.Fatalf("fixture: %+v", result)
	}
	c, _ = sscTestContext(t, sscTestReady, func(string) (string, error) { return "", &exec.Error{Name: "ssccli", Err: exec.ErrNotFound} })
	if result := automaticSSCMotion(c); result.Status != "blocked" {
		t.Fatalf("missing tool: %+v", result)
	}
}

func TestSSCMotionFailedDelivery(t *testing.T) {
	for _, test := range []struct {
		name, output string
		err          error
	}{
		{"nonfinite", strings.Replace(sscTestStream("accelerometer"), "X=1.25", "X=NaN", 1), nil},
		{"no delivery", "Sensor enable request sent successfully\nSensor disable request sent successfully\n", nil},
		{"operation", sscTestStream("accelerometer"), errors.New("nonzero exit")},
	} {
		t.Run(test.name, func(t *testing.T) {
			c, calls := sscTestContext(t, sscTestReady, func(string) (string, error) { return test.output, test.err })
			if result := automaticSSCMotion(c); result.Status != "fail" || len(*calls) != 1 {
				t.Fatalf("%+v calls=%v", result, *calls)
			}
		})
	}
}

func TestSSCMotionRequiresCleanClose(t *testing.T) {
	for _, output := range []string{
		strings.ReplaceAll(sscTestStream("accelerometer"), "Sensor disable request sent successfully\n", ""),
		sscTestStream("accelerometer") + "Unable to close accelerometer sensor: UNKNOWN\n",
	} {
		c, calls := sscTestContext(t, sscTestReady, func(string) (string, error) { return output, nil })
		if result := automaticSSCMotion(c); result.Status != "fail" || len(*calls) != 1 {
			t.Fatalf("CLI close error must fail despite exit0: %+v calls=%v", result, *calls)
		}
	}
}
