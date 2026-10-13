package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func autoFixture(t *testing.T, root, path, text string) {
	t.Helper()
	p := filepath.Join(root, path)
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(text), 0644); err != nil {
		t.Fatal(err)
	}
}

func autoTestChecks() []AutoCheck {
	return []AutoCheck{
		{ID: "test.workload", Title: "Bounded workload", Area: "Test", Kind: "functional", Run: func(*AutoContext) AutoResult { return AutoResult{Status: "pass", Detail: "workload completed"} }},
		{ID: "test.inventory", Title: "Interface inventory", Area: "Test", Kind: "inventory", Run: func(*AutoContext) AutoResult { return AutoResult{Status: "observed", Detail: "one exposed interface"} }},
		{ID: "test.blocked", Title: "Missing fixture", Area: "Test", Kind: "functional", Run: func(*AutoContext) AutoResult {
			return AutoResult{Status: "blocked", Detail: "required fixture unavailable"}
		}},
	}
}

func TestAutomaticCatalogValidation(t *testing.T) {
	checks := autoTestChecks()
	if err := automaticValidateCatalog(checks); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name   string
		mutate func([]AutoCheck) []AutoCheck
	}{
		{"empty", func([]AutoCheck) []AutoCheck { return nil }},
		{"duplicate", func(c []AutoCheck) []AutoCheck { c[1].ID = c[0].ID; return c }},
		{"area", func(c []AutoCheck) []AutoCheck { c[0].Area = " "; return c }},
		{"title", func(c []AutoCheck) []AutoCheck { c[0].Title = ""; return c }},
		{"kind", func(c []AutoCheck) []AutoCheck { c[0].Kind = "manual"; return c }},
		{"run", func(c []AutoCheck) []AutoCheck { c[0].Run = nil; return c }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := automaticValidateCatalog(tc.mutate(autoTestChecks())); err == nil {
				t.Fatal("invalid catalog accepted")
			}
		})
	}
}

func TestAutomaticContextFixtureIsolation(t *testing.T) {
	root := t.TempDir()
	autoFixture(t, root, "sys/test/node1/value", " value\x00one\n")
	c := &AutoContext{Root: root}
	value, err := c.Read("/sys/test/node1/value")
	if err != nil || value != "value one" {
		t.Fatalf("Read: %q, %v", value, err)
	}
	paths, err := c.Glob("/sys/test/node*/value")
	if err != nil || len(paths) != 1 || paths[0] != "/sys/test/node1/value" {
		t.Fatalf("Glob: %v, %v", paths, err)
	}
	if _, err := c.Read("../../outside"); err == nil {
		t.Fatal("fixture escape accepted")
	}
	outside := t.TempDir()
	autoFixture(t, outside, "private", "not fixture data")
	if err := os.Symlink(outside, filepath.Join(root, "escape")); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Read("/escape/private"); err == nil {
		t.Fatal("symlink escape accepted")
	}
	if _, err := c.Glob("/escape/*"); err == nil {
		t.Fatal("symlink enumeration escape accepted")
	}
	if _, err := c.Command("must-not-execute"); err == nil || !strings.Contains(err.Error(), "fixture") {
		t.Fatalf("fixture command: %v", err)
	}
	called := false
	c.Run = func(args ...string) (string, error) { called = true; return "fixture-output", nil }
	if out, err := c.Command("unit-test-command"); err != nil || out != "fixture-output" || !called {
		t.Fatalf("Run injection: %q %v", out, err)
	}
	c.Fixture = true
	called = false
	c.Options.User = "account-that-must-not-be-looked-up"
	if _, err := c.Command("unit-test-command"); err == nil || called {
		t.Fatal("CLI fixture ran injected command")
	}
	if _, err := c.UserCommand("session-command"); err == nil || called {
		t.Fatal("CLI fixture looked up or ran user session")
	}
}

func TestAutomaticResultsNeverPassInventory(t *testing.T) {
	checks := autoTestChecks()
	c := &AutoContext{Root: t.TempDir()}
	checks[1].Run = func(*AutoContext) AutoResult { return AutoResult{Status: "pass", Detail: "enumerated"} }
	if result := automaticResult(checks[1], c); result.Status != "error" {
		t.Fatalf("inventory passed: %#v", result)
	}
	cases := []func(*AutoContext) AutoResult{
		func(*AutoContext) AutoResult { return AutoResult{ID: "wrong", Status: "pass", Detail: "wrong check"} },
		func(*AutoContext) AutoResult { return AutoResult{Status: "unknown", Detail: "invalid status"} },
		func(*AutoContext) AutoResult { return AutoResult{Status: "pass"} },
		func(*AutoContext) AutoResult { panic("private panic output") },
	}
	for _, run := range cases {
		check := checks[0]
		check.Run = run
		if result := automaticResult(check, c); result.Status != "error" || strings.Contains(result.Detail, "private panic") {
			t.Fatalf("invalid result accepted: %#v", result)
		}
	}
}

func TestAutomaticCollectIdentityAndAllOutcomes(t *testing.T) {
	root := t.TempDir()
	autoFixture(t, root, "proc/sys/kernel/random/boot_id", "fixture-boot")
	autoFixture(t, root, "proc/sys/kernel/osrelease", "fixture-kernel")
	checks := autoTestChecks()
	checks[0].Run = func(*AutoContext) AutoResult {
		return AutoResult{Status: "fail", Detail: "recognized workload mismatch"}
	}
	c := &AutoContext{Root: root}
	report := automaticCollect(c, checks, AutoMetadata{Date: "saved-date", Fixture: true, Mode: "run"})
	if len(report.Results) != len(checks) || report.Counts.Failed != 1 || report.Counts.Observed != 1 || report.Counts.Blocked != 1 || automaticFailure(report) == nil {
		t.Fatalf("lost outcomes or failure: %#v", report)
	}
	if report.Meta.BootIDAfter != report.Meta.BootID || report.Meta.KernelAfter != report.Meta.Kernel {
		t.Fatal("identity recheck missing")
	}
	checks[0].Run = func(*AutoContext) AutoResult {
		autoFixture(t, root, "proc/sys/kernel/osrelease", "different-kernel")
		return AutoResult{Status: "pass", Detail: "workload completed"}
	}
	report = automaticCollect(c, checks, AutoMetadata{})
	if report.Counts.Passed != 0 || report.Counts.Errors != len(checks) || len(report.Errors) != 1 {
		t.Fatalf("mixed identity accepted: %#v", report)
	}
	missing := automaticCollect(&AutoContext{Root: t.TempDir()}, autoTestChecks(), AutoMetadata{Fixture: true})
	if missing.Counts.Blocked != len(checks) || automaticFailure(missing) == nil {
		t.Fatal("unbound report accepted")
	}
}

func TestAutomaticReportAndGeneratedChecklist(t *testing.T) {
	report := automaticNewReport(autoTestChecks(), AutoMetadata{Date: "2026-10-13T12:00:00Z", BootID: "fixture-boot", Kernel: "fixture-kernel", Mode: "run", Fixture: true})
	for _, check := range autoTestChecks() {
		report.Results = append(report.Results, automaticResult(check, &AutoContext{}))
	}
	automaticCount(&report)
	dir := t.TempDir()
	base := filepath.Join(dir, "saved")
	checklist := filepath.Join(dir, "AUTO-HW-CHECKLIST.md")
	if err := automaticWriteReports(report, base, checklist); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(base + ".json")
	if err != nil {
		t.Fatal(err)
	}
	var saved AutoReport
	if err = json.Unmarshal(data, &saved); err != nil {
		t.Fatal(err)
	}
	if saved.Meta.Date != report.Meta.Date || len(saved.Catalog) != 3 || saved.Counts.Passed != 1 {
		t.Fatal("report metadata lost")
	}
	md, err := os.ReadFile(checklist)
	if err != nil {
		t.Fatal(err)
	}
	text := string(md)
	if strings.Count(text, "- [x]") != 1 || strings.Count(text, "- [ ]") != 1 || !strings.Contains(text, "inventory; observed") || strings.Contains(text, "[ ] **test.inventory") {
		t.Fatal("checkbox semantics changed:\n" + text)
	}
	if !strings.Contains(text, "Missing fixture") || !strings.Contains(text, report.Meta.Date) || strings.Contains(text, "of 47") {
		t.Fatal("incomplete automatic report")
	}
	regenerated := filepath.Join(dir, "regenerated.md")
	regeneratedReport, err := automaticRegenerate(saved, autoTestChecks(), base+".json")
	if err != nil {
		t.Fatal(err)
	}
	if err = automaticWrite(regenerated, []byte(automaticMarkdown(regeneratedReport, true))); err != nil {
		t.Fatal(err)
	}
	regeneratedData, err := os.ReadFile(regenerated)
	if err != nil || string(regeneratedData) != text {
		t.Fatalf("regeneration changed stored date/outcomes: %v", err)
	}
}

func TestAutomaticCLIListingAndCatalogGeneration(t *testing.T) {
	dir := t.TempDir()
	// A nonexistent repo/root ensures no lock or hardware read can succeed.
	if err := automaticMain([]string{"--repo", filepath.Join(dir, "missing"), "--root", filepath.Join(dir, "missing-root"), "--list"}); err != nil {
		t.Fatal(err)
	}
	if err := automaticMain([]string{"--repo", dir, "--root", filepath.Join(dir, "missing-root"), "--checklist"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "AUTO-HW-CHECKLIST.md"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "- [x]") || !strings.Contains(string(data), "generation-only catalog") {
		t.Fatal("generation fabricated pass")
	}
	if err := automaticMain([]string{"--unexpected"}); err == nil {
		t.Fatal("unknown flag accepted")
	}
}

func TestAutomaticPrivacyAndBounds(t *testing.T) {
	input := "interfaces=2; peer=aa:bb:cc:dd:ee:ff; target=192.0.2.1; target6=2001:db8::5; SSID=private-name; serial=private-serial"
	detail := automaticDetail(input)
	for _, secret := range []string{"aa:bb", "192.0.2.1", "2001:db8", "private-name", "private-serial"} {
		if strings.Contains(detail, secret) {
			t.Fatalf("private value leaked: %s", detail)
		}
	}
	if !strings.Contains(detail, "interfaces=2") {
		t.Fatal("safe count redacted")
	}
	wrappedTimeout := automaticArgsTimeout([]string{"runuser", "-u", "fixture-user", "--", "env", "XDG_RUNTIME_DIR=/fixture", "env", "GDK_DEBUG=vulkan", "gtk4-rendernode-tool", "render"})
	if wrappedTimeout != automaticCommandTimeout("gtk4-rendernode-tool") {
		t.Fatal("user wrapper lost media command budget")
	}
	if automaticCommandTimeout("ffmpeg") <= automaticCommandTimeout("systemctl") {
		t.Fatal("media command budget not bounded separately")
	}
	var out autoOutput
	inputBytes := make([]byte, 2*1024*1024)
	n, err := out.Write(inputBytes)
	if err != nil || n != len(inputBytes) || out.Len() > 1024*1024 || !out.Truncated {
		t.Fatal("output cap failed")
	}
	report := automaticCatalogReport(autoTestChecks())
	report.Results[1].Status = "pass"
	if err := automaticValidateReport(report); err == nil {
		t.Fatal("saved inventory pass accepted")
	}
	if automaticFailure(automaticCatalogReport(autoTestChecks())) != nil {
		t.Fatal("blocked checks treated as real failure")
	}
}

func TestAutomaticSavedReportMatchesCurrentCatalog(t *testing.T) {
	checks, err := automaticCatalog()
	if err != nil {
		t.Fatal(err)
	}
	report := automaticCatalogReport(checks)
	report.Meta.Date = "saved-date"
	dir := t.TempDir()
	source := filepath.Join(dir, "saved.json")
	data, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(source, data, 0644); err != nil {
		t.Fatal(err)
	}
	// Regeneration uses only saved evidence; it cannot take a device lock or
	// access the intentionally nonexistent fixture root.
	target := filepath.Join(dir, "checklist.md")
	if err := automaticMain([]string{"--repo", dir, "--root", filepath.Join(dir, "missing"), "--from-report", source, "--checklist-path", target}); err != nil {
		t.Fatal(err)
	}
	md, err := os.ReadFile(target)
	if err != nil || !strings.Contains(string(md), "saved-date") || !strings.Contains(string(md), source) {
		t.Fatalf("saved metadata missing: %v", err)
	}
	report.Catalog[0].ID = "not.in.current.catalog"
	report.Results[0].ID = report.Catalog[0].ID
	if _, err := automaticRegenerate(report, checks, source); err == nil {
		t.Fatal("unknown saved catalog ID accepted")
	}
	short := automaticCatalogReport(checks[1:])
	if _, err := automaticRegenerate(short, checks, source); err == nil {
		t.Fatal("incomplete saved catalog accepted")
	}
	changed := automaticCatalogReport(checks)
	changed.Catalog[0].Title = "stale title"
	if _, err := automaticRegenerate(changed, checks, source); err == nil {
		t.Fatal("stale title accepted")
	}
}

func TestAutomaticExitCodes(t *testing.T) {
	if automaticExitCode(nil) != 0 || automaticExitCode(&AutoExitError{75, errors.New("busy")}) != 75 || automaticExitCode(errors.New("infrastructure")) != 2 {
		t.Fatal("exit codes changed")
	}
	report := automaticCatalogReport(autoTestChecks())
	report.Counts.Failed = 1
	if automaticExitCode(automaticFailure(report)) != 1 {
		t.Fatal("real failure exit missing")
	}
}

func TestAutomaticFixtureDoesNotReplaceActiveChecklist(t *testing.T) {
	dir, root := t.TempDir(), t.TempDir()
	autoFixture(t, root, "proc/sys/kernel/random/boot_id", "fixture-boot")
	autoFixture(t, root, "proc/sys/kernel/osrelease", "fixture-kernel")
	active := filepath.Join(dir, "AUTO-HW-CHECKLIST.md")
	if err := os.WriteFile(active, []byte("keep real evidence"), 0644); err != nil {
		t.Fatal(err)
	}
	base := filepath.Join(dir, "fixture")
	// No external commands are possible; unavailable fixtures remain blocked.
	_ = automaticMain([]string{"--repo", dir, "--root", root, "--output", base})
	current, err := os.ReadFile(active)
	if err != nil || string(current) != "keep real evidence" {
		t.Fatal("fixture replaced active checklist")
	}
	fixtureData, err := os.ReadFile(base + "-CHECKLIST.md")
	if err != nil || !strings.Contains(string(fixtureData), "FIXTURE ONLY") {
		t.Fatalf("fixture checklist not labeled: %v", err)
	}
	if err := automaticMain([]string{"--repo", dir, "--from-report", base + ".json"}); err != nil {
		t.Fatal(err)
	}
	current, err = os.ReadFile(active)
	if err != nil || string(current) != "keep real evidence" {
		t.Fatal("fixture regeneration replaced active checklist")
	}
}

func TestAutomaticDisplayEnvironmentOnlyImportsSessionFields(t *testing.T) {
	output := "WAYLAND_DISPLAY=wayland-existing\nDISPLAY=:7\nXAUTHORITY=/existing/user/auth\nPRIVATE_TOKEN=never-import\nSSID=private-network\n"
	env := automaticDisplayEnvironment(output)
	if len(env) != 3 || strings.Contains(strings.Join(env, " "), "private") || strings.Contains(strings.Join(env, " "), "TOKEN") {
		t.Fatalf("unrelated user environment imported: %v", env)
	}
	if !automaticNeedsDisplay([]string{"env", "GDK_DEBUG=vulkan", "gtk4-rendernode-tool", "render"}) || automaticNeedsDisplay([]string{"pactl", "list", "sinks"}) {
		t.Fatal("display import applied to wrong command")
	}
}
