package main

import (
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fixture(t *testing.T, root, path, text string) {
	t.Helper()
	p := filepath.Join(root, path)
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(text), 0644); err != nil {
		t.Fatal(err)
	}
}
func TestFrozenChecklist(t *testing.T) {
	text, err := os.ReadFile("../../../PORT-CHECKLIST.md")
	if err != nil {
		t.Fatal(err)
	}
	boxes, err := checklist(string(text))
	if err != nil {
		t.Fatal(err)
	}
	if len(boxes) != 47 || boxes[0].ID != "B01" || boxes[46].ID != "F04" {
		t.Fatal("wrong frozen checklist")
	}
	if !strings.Contains(boxes[0].Acceptance, "regression.") || !strings.Contains(boxes[46].Acceptance, "failing.") {
		t.Fatal("truncated acceptance")
	}
	for _, b := range boxes {
		if strings.Contains(b.Acceptance, "Notes, not acceptance") || strings.Contains(b.Acceptance, "Milestones") {
			t.Fatalf("notes leaked into %s", b.ID)
		}
	}
	for _, bad := range []string{strings.Replace(string(text), "B01 —", "B99 —", 1), strings.Replace(string(text), "B02 —", "B01 —", 1), strings.Replace(string(text), "- [ ] **B01", "- [ ] **B01a", 1)} {
		if _, err := checklist(bad); err == nil {
			t.Fatal("accepted altered frozen IDs")
		}
	}
}
func TestCachedNamesAndUnknown(t *testing.T) {
	root := t.TempDir()
	fixture(t, root, "sys/class/remoteproc/remoteproc0/name", "adsp\n")
	fixture(t, root, "sys/class/remoteproc/remoteproc0/state", "running\n")
	fixture(t, root, "proc/bus/input/devices", "N: Name=\"Surface Keyboard\"\nU: Uniq=aa:bb:cc:dd:ee:ff\n")
	v := newInventory(root, func(...string) (string, error) { return "", os.ErrNotExist })
	p := v.names("fw.remoteproc", "B04", "/sys/class/remoteproc/remoteproc*", "name", "state")
	if p.State != "observed" || !strings.Contains(p.Detail, "adsp") {
		t.Fatal(p)
	}
	fixture(t, root, "sys/class/remoteproc/remoteproc0/state", "offline")
	if v.read("/sys/class/remoteproc/remoteproc0/state").text != "running" {
		t.Fatal("metadata not cached")
	}
	p = v.names("missing", "N03", "/sys/class/wwan/*")
	if p.State != "unknown" || !strings.Contains(p.Detail, "does not establish hardware absence") {
		t.Fatal(p)
	}
	p = v.inputNames()
	if strings.Contains(p.Detail, "Uniq") || strings.Contains(p.Detail, "aa:bb") {
		t.Fatal("input identifiers leaked")
	}
	p = v.services("services", "B04", false, "pd-mapper.service")
	if p.State != "unknown" {
		t.Fatal(p)
	}
}
func TestIIONeverReadsChannels(t *testing.T) {
	root := t.TempDir()
	fixture(t, root, "sys/bus/iio/devices/iio:device0/name", "tcs3430")
	fixture(t, root, "sys/bus/iio/devices/iio:device0/in_intensity_raw", "PRIVATE_SENSOR_VALUE")
	v := newInventory(root, nil)
	p := v.iio()
	if p.State != "observed" || !strings.Contains(p.Detail, "in_intensity_raw") || strings.Contains(p.Detail, "PRIVATE_SENSOR_VALUE") {
		t.Fatal(p)
	}
	if _, ok := v.cache["/sys/bus/iio/devices/iio:device0/in_intensity_raw"]; ok {
		t.Fatal("read raw sensor")
	}
}
func TestRunningConfig(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "proc"), 0755); err != nil {
		t.Fatal(err)
	}
	f, err := os.Create(filepath.Join(root, "proc/config.gz"))
	if err != nil {
		t.Fatal(err)
	}
	gz := gzip.NewWriter(f)
	_, err = gz.Write([]byte("# CONFIG_QCOM_IPA is not set\n# CONFIG_WWAN is not set\nCONFIG_QCOM_FASTRPC=m\nCONFIG_TYPEC_DP_ALTMODE=y\nCONFIG_SURFACE_AGGREGATOR_USBC=m\nCONFIG_VIDEO_QCOM_VENUS=m\nCONFIG_VIDEO_QCOM_CAMSS=m\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err = gz.Close(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	p := newInventory(root, nil).config()
	if p.State != "needs investigation" || !strings.Contains(p.Detail, "CONFIG_QCOM_IPA=not set") || !strings.Contains(p.Detail, "CONFIG_QCOM_FASTRPC=m") {
		t.Fatal(p)
	}
}
func TestReportDoesNotGrantAcceptance(t *testing.T) {
	text, err := os.ReadFile("../../../PORT-CHECKLIST.md")
	if err != nil {
		t.Fatal(err)
	}
	boxes, err := checklist(string(text))
	if err != nil {
		t.Fatal(err)
	}
	closed := 0
	for _, b := range boxes {
		if b.Closed {
			closed++
		}
	}
	r, err := assemble(boxes, []Probe{{ID: "foo", Boxes: []string{"B01"}, State: "observed", Detail: "present"}}, Meta{Kernel: "fixture-kernel", BootID: "fixture-boot"})
	if err != nil {
		t.Fatal(err)
	}
	if r.Closed != closed || r.Boxes[0].Closed {
		t.Fatal("presence granted acceptance")
	}
	md := markdown(r)
	if !strings.Contains(md, "fixture-boot") || !strings.Contains(md, boxes[0].Acceptance) || !strings.Contains(md, "not functional acceptance") {
		t.Fatal("incomplete report")
	}
	if _, err = assemble(boxes, []Probe{{Boxes: []string{"B99"}}}, Meta{}); err == nil {
		t.Fatal("unknown box allowed")
	}
}
