// Automatic checks report bounded functional tests separately from inventory.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

type AutoCheck struct {
	ID, Title, Area, Kind string
	Boxes                 []string
	Run                   func(*AutoContext) AutoResult
}

type AutoResult struct {
	ID     string `json:"id"`
	Status string `json:"status"`
	Detail string `json:"detail"`
}

type AutoOptions struct {
	Capture    bool
	Media      string
	StorageDir string
	User       string
}

type AutoContext struct {
	Fixture    bool
	Root, Repo string
	Options    AutoOptions
	Run        func(...string) (string, error)
}

func (c *AutoContext) path(path string) (string, error) {
	root := c.Root
	if root == "" {
		root = "/"
	}
	root, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	p := filepath.Join(root, strings.TrimPrefix(path, "/"))
	rel, err := filepath.Rel(root, p)
	if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return "", errors.New("path escapes fixture root")
	}
	return p, nil
}

func (c *AutoContext) withinRoot(path string) error {
	if c.Root == "" || filepath.Clean(c.Root) == "/" {
		return nil
	}
	root, err := filepath.Abs(c.Root)
	if err != nil {
		return err
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(root, resolved)
	if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return errors.New("symlink escapes fixture root")
	}
	return nil
}

func (c *AutoContext) ReadBytes(path string) ([]byte, error) {
	p, err := c.path(path)
	if err != nil {
		return nil, err
	}
	if err = c.withinRoot(p); err != nil {
		return nil, err
	}
	return os.ReadFile(p)
}

func (c *AutoContext) Read(path string) (string, error) {
	data, err := c.ReadBytes(path)
	return strings.TrimSpace(strings.ReplaceAll(string(data), "\x00", " ")), err
}

// Glob returns logical paths, so callers can pass them straight to Read.
func (c *AutoContext) Glob(pattern string) ([]string, error) {
	p, err := c.path(pattern)
	if err != nil {
		return nil, err
	}
	// Check the non-wildcard parent before any fixture enumeration.
	parent := filepath.Dir(p)
	for strings.ContainsAny(parent, "*?[") {
		parent = filepath.Dir(parent)
	}
	if err = c.withinRoot(parent); err != nil {
		return nil, err
	}
	matches, err := filepath.Glob(p)
	if err != nil {
		return nil, err
	}
	root := c.Root
	if root == "" {
		root = "/"
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	paths := make([]string, 0, len(matches))
	for _, match := range matches {
		if err := c.withinRoot(match); err != nil {
			return nil, err
		}
		rel, err := filepath.Rel(root, match)
		if err != nil {
			return nil, err
		}
		paths = append(paths, "/"+filepath.ToSlash(rel))
	}
	return paths, nil
}

func (c *AutoContext) Command(args ...string) (string, error) {
	if len(args) == 0 || args[0] == "" {
		return "", errors.New("no command supplied")
	}
	if c.Fixture {
		return "", errors.New("external commands disabled for fixture root")
	}
	if c.Run != nil {
		return c.Run(args...)
	}
	if c.Root != "" && filepath.Clean(c.Root) != "/" {
		return "", errors.New("external commands disabled for fixture root")
	}
	return automaticCommand(args...)
}

// UserCommand selects an existing user's session without starting services.
func automaticDisplayEnvironment(output string) []string {
	values := make(map[string]string)
	for _, line := range strings.Split(output, "\n") {
		pair := strings.SplitN(line, "=", 2)
		if len(pair) != 2 || pair[1] == "" {
			continue
		}
		switch pair[0] {
		case "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY":
			if !strings.ContainsAny(pair[1], "\x00\r") {
				values[pair[0]] = pair[1]
			}
		}
	}
	var env []string
	for _, key := range []string{"WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"} {
		if value := values[key]; value != "" {
			env = append(env, key+"="+value)
		}
	}
	return env
}

func automaticNeedsDisplay(args []string) bool {
	for _, arg := range args {
		if filepath.Base(arg) == "gtk4-rendernode-tool" {
			return true
		}
	}
	return false
}

func (c *AutoContext) UserCommand(args ...string) (string, error) {
	if c.Options.User == "" {
		return c.Command(args...)
	}
	if c.Fixture || (c.Root != "" && filepath.Clean(c.Root) != "/") {
		return c.Command(args...)
	}
	account, err := user.Lookup(c.Options.User)
	if err != nil {
		return "", errors.New("requested desktop user cannot be resolved")
	}
	runtime := "/run/user/" + account.Uid
	env := []string{"env", "XDG_RUNTIME_DIR=" + runtime, "DBUS_SESSION_BUS_ADDRESS=unix:path=" + runtime + "/bus", "PULSE_SERVER=unix:" + runtime + "/pulse/native"}
	wrap := func(command []string) []string {
		if os.Geteuid() == 0 && account.Uid != "0" {
			return append([]string{"runuser", "-u", account.Username, "--"}, command...)
		}
		return command
	}
	if automaticNeedsDisplay(args) {
		query := append(append([]string{}, env...), "systemctl", "--user", "show-environment")
		output, queryErr := c.Command(wrap(query)...)
		if queryErr != nil {
			return "", errors.New("existing desktop user manager display environment unavailable")
		}
		env = append(env, automaticDisplayEnvironment(output)...)
	}
	return c.Command(wrap(append(env, args...))...)
}

// Keep diagnostics in memory only and cap output from noisy or broken tools.
type autoOutput struct {
	bytes.Buffer
	Truncated bool
}

func (b *autoOutput) Write(p []byte) (int, error) {
	const limit = 1024 * 1024
	n := len(p)
	if n > limit-b.Len() {
		b.Truncated = true
	}
	if b.Len() < limit {
		keep := limit - b.Len()
		if keep > n {
			keep = n
		}
		_, _ = b.Buffer.Write(p[:keep])
	}
	return n, nil
}

func automaticCommandTimeout(program string) time.Duration {
	switch filepath.Base(program) {
	case "ffmpeg", "ffprobe", "cam", "libcamera-vid", "libcamera-still", "vulkaninfo", "eglinfo", "glmark2", "glmark2-es2", "glmark2-gbm", "glmark2-es2-gbm", "gtk4-rendernode-tool", "env":
		return 60 * time.Second
	case "spx-lock":
		return 10 * time.Second
	default:
		return 20 * time.Second
	}
}

func automaticArgsTimeout(args []string) time.Duration {
	if len(args) == 0 {
		return 20 * time.Second
	}
	switch filepath.Base(args[0]) {
	case "runuser":
		for i, arg := range args {
			if arg == "--" {
				return automaticArgsTimeout(args[i+1:])
			}
		}
	case "env":
		i := 1
		for i < len(args) && strings.Contains(args[i], "=") {
			i++
		}
		return automaticArgsTimeout(args[i:])
	}
	return automaticCommandTimeout(args[0])
}

func automaticCommand(args ...string) (string, error) {
	if len(args) == 0 {
		return "", errors.New("no command supplied")
	}
	timeout := automaticArgsTimeout(args)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.WaitDelay = 2 * time.Second
	cmd.Env = append(os.Environ(), "LC_ALL=C")
	var output autoOutput
	cmd.Stdout, cmd.Stderr = &output, &output
	err := cmd.Run()
	if output.Truncated {
		err = errors.Join(err, errors.New("command output exceeded in-memory limit; incomplete output cannot establish success"))
	}
	if ctx.Err() != nil {
		return output.String(), fmt.Errorf("%s exceeded %s command limit", filepath.Base(args[0]), timeout)
	}
	return output.String(), err
}

func automaticCatalog() ([]AutoCheck, error) {
	var checks []AutoCheck
	for _, group := range [][]AutoCheck{
		automaticPlatformChecks(), automaticNetworkChecks(), automaticBluetoothChecks(),
		automaticGraphicsChecks(), automaticMediaChecks(), automaticAudioChecks(), automaticInterfacesChecks(),
	} {
		checks = append(checks, group...)
	}
	return checks, automaticValidateCatalog(checks)
}

func automaticValidateCatalog(checks []AutoCheck) error {
	if len(checks) == 0 {
		return errors.New("automatic catalog is empty")
	}
	ids := make(map[string]bool)
	for _, check := range checks {
		if strings.TrimSpace(check.ID) == "" || strings.TrimSpace(check.Title) == "" || strings.TrimSpace(check.Area) == "" {
			return errors.New("automatic check needs an ID, title and area")
		}
		if ids[check.ID] {
			return fmt.Errorf("duplicate automatic check ID: %s", check.ID)
		}
		ids[check.ID] = true
		if check.Kind != "functional" && check.Kind != "inventory" {
			return fmt.Errorf("%s: invalid kind %q", check.ID, check.Kind)
		}
		if check.Run == nil {
			return fmt.Errorf("%s: no runnable check", check.ID)
		}
	}
	return nil
}

type AutoCheckMetadata struct {
	ID             string   `json:"id"`
	Title          string   `json:"title"`
	Area           string   `json:"area"`
	Kind           string   `json:"kind"`
	Boxes          []string `json:"historical_boxes"`
	Implementation string   `json:"implementation"`
}

type AutoMetadata struct {
	ReportJSON  string `json:"report_json,omitempty"`
	Date        string `json:"date"`
	BootID      string `json:"boot_id"`
	Kernel      string `json:"kernel"`
	BootIDAfter string `json:"boot_id_after"`
	KernelAfter string `json:"kernel_after"`
	Fixture     bool   `json:"fixture"`
	Mode        string `json:"mode"`
}

type AutoCounts struct {
	Functional int `json:"functional"`
	Passed     int `json:"functional_passed"`
	Inventory  int `json:"inventory"`
	Observed   int `json:"inventory_observed"`
	Failed     int `json:"failed"`
	Blocked    int `json:"blocked"`
	Errors     int `json:"errors"`
}

type AutoReport struct {
	Meta     AutoMetadata        `json:"meta"`
	Coverage string              `json:"coverage"`
	Catalog  []AutoCheckMetadata `json:"catalog"`
	Results  []AutoResult        `json:"results"`
	Counts   AutoCounts          `json:"counts"`
	Errors   []string            `json:"errors,omitempty"`
}

const automaticCoverage = "Implemented checks are validator coverage, not proof that hardware drivers are implemented. Only a functional pass from this boot completes a check. Inventory is never a functional pass."

func automaticNewReport(checks []AutoCheck, meta AutoMetadata) AutoReport {
	report := AutoReport{Meta: meta, Coverage: automaticCoverage, Catalog: []AutoCheckMetadata{}, Results: []AutoResult{}}
	for _, check := range checks {
		boxes := append([]string{}, check.Boxes...)
		report.Catalog = append(report.Catalog, AutoCheckMetadata{check.ID, check.Title, check.Area, check.Kind, boxes, "validator entry available; hardware workload may be blocked"})
	}
	return report
}

var automaticMAC = regexp.MustCompile(`(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b`)
var automaticIPv4 = regexp.MustCompile(`\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b`)
var automaticIPv6 = regexp.MustCompile(`(?i)[0-9a-f]*:[0-9a-f:]+(?:%[a-z0-9_.-]+)?`)
var automaticIdentifiers = regexp.MustCompile(`(?i)\b(?:ssid|bssid|(?:device[_ -]?)?serial(?:number)?)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s;]+)`)

func automaticDetail(detail string) string {
	detail = automaticIdentifiers.ReplaceAllString(detail, "[private identifier omitted]")
	detail = automaticMAC.ReplaceAllString(detail, "[address omitted]")
	detail = automaticIPv4.ReplaceAllStringFunc(detail, func(s string) string {
		if net.ParseIP(s) != nil {
			return "[address omitted]"
		}
		return s
	})
	detail = automaticIPv6.ReplaceAllStringFunc(detail, func(s string) string {
		ip := strings.SplitN(s, "%", 2)[0]
		if net.ParseIP(ip) != nil {
			return "[address omitted]"
		}
		return s
	})
	detail = strings.Join(strings.Fields(detail), " ")
	if len(detail) > 4096 {
		detail = detail[:4096] + " [summary truncated]"
	}
	return detail
}

func automaticResult(check AutoCheck, c *AutoContext) (result AutoResult) {
	defer func() {
		if recover() != nil {
			result = AutoResult{check.ID, "error", "validator check panicked; no outcome accepted"}
		}
	}()
	result = check.Run(c)
	if result.ID != "" && result.ID != check.ID {
		return AutoResult{check.ID, "error", "validator returned a different check ID"}
	}
	result.ID = check.ID
	switch result.Status {
	case "pass", "fail", "observed", "blocked", "error":
	default:
		return AutoResult{check.ID, "error", "validator returned an invalid status"}
	}
	if check.Kind == "inventory" && result.Status == "pass" {
		return AutoResult{check.ID, "error", "inventory cannot establish a functional pass"}
	}
	result.Detail = automaticDetail(result.Detail)
	if result.Detail == "" {
		return AutoResult{check.ID, "error", "validator returned no result detail"}
	}
	return result
}

func automaticCount(report *AutoReport) {
	report.Counts = AutoCounts{}
	for i, check := range report.Catalog {
		if check.Kind == "functional" {
			report.Counts.Functional++
		} else {
			report.Counts.Inventory++
		}
		result := report.Results[i]
		switch result.Status {
		case "pass":
			if check.Kind == "functional" {
				report.Counts.Passed++
			}
		case "observed":
			if check.Kind == "inventory" {
				report.Counts.Observed++
			}
		case "fail":
			report.Counts.Failed++
		case "blocked":
			report.Counts.Blocked++
		case "error":
			report.Counts.Errors++
		}
	}
}

func automaticCollect(c *AutoContext, checks []AutoCheck, meta AutoMetadata) AutoReport {
	report := automaticNewReport(checks, meta)
	boot, bootErr := c.Read("/proc/sys/kernel/random/boot_id")
	kernel, kernelErr := c.Read("/proc/sys/kernel/osrelease")
	report.Meta.BootID, report.Meta.Kernel = boot, kernel
	if bootErr != nil || kernelErr != nil || boot == "" || kernel == "" {
		report.Errors = append(report.Errors, "boot/kernel identity unavailable; no checks run")
		for _, check := range checks {
			report.Results = append(report.Results, AutoResult{check.ID, "blocked", "boot/kernel identity unavailable; no checks run"})
		}
		automaticCount(&report)
		return report
	}
	for _, check := range checks {
		report.Results = append(report.Results, automaticResult(check, c))
	}
	report.Meta.BootIDAfter, bootErr = c.Read("/proc/sys/kernel/random/boot_id")
	report.Meta.KernelAfter, kernelErr = c.Read("/proc/sys/kernel/osrelease")
	if bootErr != nil || kernelErr != nil || report.Meta.BootIDAfter != boot || report.Meta.KernelAfter != kernel {
		report.Errors = append(report.Errors, "boot/kernel identity changed or could not be rechecked; outcomes invalidated")
		for i := range report.Results {
			report.Results[i] = AutoResult{report.Results[i].ID, "error", "boot/kernel identity changed or could not be rechecked; outcome invalidated"}
		}
	}
	automaticCount(&report)
	return report
}

func automaticCatalogReport(checks []AutoCheck) AutoReport {
	report := automaticNewReport(checks, AutoMetadata{Date: time.Now().Format(time.RFC3339), Mode: "catalog"})
	for _, check := range checks {
		report.Results = append(report.Results, AutoResult{check.ID, "blocked", "not run; generation-only catalog; validator availability does not establish workload implementation or driver support"})
	}
	automaticCount(&report)
	return report
}

func automaticValidateReport(report AutoReport) error {
	if len(report.Catalog) == 0 || len(report.Results) != len(report.Catalog) {
		return errors.New("report has incomplete catalog outcomes")
	}
	ids := make(map[string]bool)
	for i, check := range report.Catalog {
		if check.ID == "" || check.Title == "" || check.Area == "" || ids[check.ID] {
			return errors.New("report has invalid or duplicate catalog metadata")
		}
		ids[check.ID] = true
		if check.Kind != "functional" && check.Kind != "inventory" {
			return errors.New("report has invalid check kind")
		}
		result := report.Results[i]
		if result.ID != check.ID || result.Detail == "" {
			return errors.New("report outcome does not match catalog")
		}
		switch result.Status {
		case "pass", "fail", "observed", "blocked", "error":
		default:
			return errors.New("report has invalid outcome status")
		}
		if check.Kind == "inventory" && result.Status == "pass" {
			return errors.New("report incorrectly passes inventory")
		}
	}
	return nil
}

// Saved evidence describes exactly one catalog; changes require a new run.
func automaticRegenerate(saved AutoReport, checks []AutoCheck, path string) (AutoReport, error) {
	if err := automaticValidateReport(saved); err != nil {
		return AutoReport{}, err
	}
	if len(saved.Catalog) != len(checks) {
		return AutoReport{}, errors.New("saved report catalog differs from current catalog; rerun checks")
	}
	current := make(map[string]AutoCheck)
	for _, check := range checks {
		current[check.ID] = check
	}
	outcomes := make(map[string]AutoResult)
	for i, metadata := range saved.Catalog {
		check, ok := current[metadata.ID]
		if !ok || check.Kind != metadata.Kind || check.Title != metadata.Title || check.Area != metadata.Area {
			return AutoReport{}, errors.New("saved report metadata differs from current catalog; rerun checks")
		}
		outcome := saved.Results[i]
		outcome.Detail = automaticDetail(outcome.Detail)
		outcomes[check.ID] = outcome
	}
	report := automaticNewReport(checks, saved.Meta)
	absolute, err := filepath.Abs(path)
	if err != nil {
		return AutoReport{}, err
	}
	report.Meta.ReportJSON = absolute
	report.Errors = append([]string{}, saved.Errors...)
	for _, check := range checks {
		report.Results = append(report.Results, outcomes[check.ID])
	}
	automaticCount(&report)
	return report, nil
}

func automaticMarkdown(report AutoReport, checklistOnly bool) string {
	var b strings.Builder
	title := "Automatic hardware report"
	if checklistOnly {
		title = "Automatic hardware checklist"
	}
	fmt.Fprintf(&b, "# %s\n\n", title)
	fmt.Fprintf(&b, "Date: %s\nBoot: `%s`\nKernel: `%s`\nMode: %s; fixture: %t\n\n", report.Meta.Date, report.Meta.BootID, report.Meta.Kernel, report.Meta.Mode, report.Meta.Fixture)
	if report.Meta.ReportJSON != "" {
		fmt.Fprintf(&b, "Report JSON: [JSON](%s)\n\n", report.Meta.ReportJSON)
	}
	fmt.Fprintf(&b, "Functional checks passed: **%d of %d**. Inventory observations: %d of %d. Blocked: %d. Failed: %d. Errors: %d.\n\n", report.Counts.Passed, report.Counts.Functional, report.Counts.Observed, report.Counts.Inventory, report.Counts.Blocked, report.Counts.Failed, report.Counts.Errors)
	if report.Meta.Fixture {
		b.WriteString("**FIXTURE ONLY: these are not live hardware results.**\n\n")
	}
	b.WriteString(automaticCoverage + "\n\nAll catalog rows remain visible, including unsupported or blocked checks. This automatic list has no human conditions and does not certify the historical full acceptance checklist. Each run replaces the active list with that boot's outcomes.\n\n")
	for _, err := range report.Errors {
		fmt.Fprintf(&b, "Report error: %s\n\n", automaticMarkdownText(err))
	}
	areas := []string{}
	for _, check := range report.Catalog {
		known := false
		for _, area := range areas {
			if area == check.Area {
				known = true
				break
			}
		}
		if !known {
			areas = append(areas, check.Area)
		}
	}
	for _, area := range areas {
		fmt.Fprintf(&b, "## %s\n\n", automaticMarkdownText(area))
		for i, check := range report.Catalog {
			if check.Area != area {
				continue
			}
			result := report.Results[i]
			prefix := "- "
			if check.Kind == "functional" {
				tick := " "
				if result.Status == "pass" {
					tick = "x"
				}
				prefix += "[" + tick + "] "
			}
			fmt.Fprintf(&b, "%s**%s — %s** (%s; %s): %s\n", prefix, automaticMarkdownText(check.ID), automaticMarkdownText(check.Title), check.Kind, result.Status, automaticMarkdownText(result.Detail))
		}
		b.WriteString("\n")
	}
	return strings.TrimRight(b.String(), "\n") + "\n"
}

func automaticMarkdownText(s string) string {
	r := strings.NewReplacer("\n", " ", "\r", " ", "\\", "\\\\", "*", "\\*", "[", "\\[", "]", "\\]", "`", "\\`", "<", "&lt;", ">", "&gt;")
	return r.Replace(s)
}

func automaticWrite(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".auto-hw-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(0644); err == nil {
		_, err = f.Write(data)
	}
	err = errors.Join(err, f.Close())
	if err != nil {
		return err
	}
	return os.Rename(name, path)
}

func automaticReportPaths(base string) (string, string) {
	ext := filepath.Ext(base)
	if ext == ".md" || ext == ".json" {
		base = strings.TrimSuffix(base, ext)
	}
	return base + ".md", base + ".json"
}

func automaticWriteReports(report AutoReport, base, checklistPath string) error {
	if err := automaticValidateReport(report); err != nil {
		return err
	}
	mdPath, jsonPath := automaticReportPaths(base)
	jsonPath, err := filepath.Abs(jsonPath)
	if err != nil {
		return err
	}
	report.Meta.ReportJSON = jsonPath
	automaticCount(&report)
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return err
	}
	if err = automaticWrite(jsonPath, append(data, '\n')); err != nil {
		return err
	}
	if err = automaticWrite(mdPath, []byte(automaticMarkdown(report, false))); err != nil {
		return err
	}
	return automaticWrite(checklistPath, []byte(automaticMarkdown(report, true)))
}

type AutoExitError struct {
	Code int
	Err  error
}

func (e *AutoExitError) Error() string { return e.Err.Error() }
func (e *AutoExitError) Unwrap() error { return e.Err }

func automaticExitCode(err error) int {
	if err == nil {
		return 0
	}
	var exit *AutoExitError
	if errors.As(err, &exit) {
		return exit.Code
	}
	return 2
}

func automaticFailure(report AutoReport) error {
	if len(report.Errors) > 0 {
		return &AutoExitError{2, errors.New("automatic report cannot establish consistent boot/kernel identity")}
	}
	if report.Counts.Failed > 0 || report.Counts.Errors > 0 {
		return &AutoExitError{1, fmt.Errorf("automatic checks recorded %d failed and %d error outcomes", report.Counts.Failed, report.Counts.Errors)}
	}
	return nil
}

// automaticMain is independent of the historical acceptance parser.
func automaticMain(args []string) (err error) {
	flags := flag.NewFlagSet("hw-validation", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	repo := flags.String("repo", ".", "repository root")
	root := flags.String("root", "", "fixture filesystem root; disables all external commands and locks")
	output := flags.String("output", "", "report basename (.json and .md); with --checklist, read saved JSON")
	list := flags.Bool("list", false, "list catalog only; no commands, locks or hardware reads")
	listJSON := flags.Bool("list-json", false, "print catalog metadata as JSON; no tests or hardware reads")
	fromReport := flags.String("from-report", "", "saved JSON report for checklist generation only")
	generate := flags.Bool("checklist", false, "generate checklist only; no tests, locks or hardware reads")
	checklistPath := flags.String("checklist-path", "", "active checklist path (default <repo>/AUTO-HW-CHECKLIST.md)")
	capture := flags.Bool("capture", false, "allow minimal bounded camera/microphone capture; samples discarded")
	media := flags.String("media", "", "existing media fixture for bounded decoder-only checks")
	storageDir := flags.String("storage-dir", "", "directory for disposable bounded storage checks")
	desktopUser := flags.String("user", "", "existing desktop session user for selected user-session commands")
	if err := flags.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	checks, err := automaticCatalog()
	if err != nil {
		return err
	}
	absRepo, err := filepath.Abs(*repo)
	if err != nil {
		return err
	}
	path := *checklistPath
	if path == "" {
		path = filepath.Join(absRepo, "AUTO-HW-CHECKLIST.md")
	}
	if *list || *listJSON {
		if *listJSON {
			report := automaticNewReport(checks, AutoMetadata{Mode: "catalog"})
			encoder := json.NewEncoder(os.Stdout)
			encoder.SetIndent("", "  ")
			return encoder.Encode(report.Catalog)
		}
		for _, check := range checks {
			fmt.Printf("%s\t%s\t%s\t%s\n", check.ID, check.Area, check.Kind, check.Title)
		}
		return nil
	}
	if *generate || *fromReport != "" {
		report := automaticCatalogReport(checks)
		jsonPath := *fromReport
		if jsonPath == "" && *output != "" {
			_, jsonPath = automaticReportPaths(*output)
		}
		if jsonPath != "" {
			data, err := os.ReadFile(jsonPath)
			if err != nil {
				return fmt.Errorf("read saved automatic report: %w", err)
			}
			var saved AutoReport
			if err = json.Unmarshal(data, &saved); err != nil {
				return err
			}
			report, err = automaticRegenerate(saved, checks, jsonPath)
			if err != nil {
				return err
			}
		}
		if report.Meta.Fixture && *checklistPath == "" {
			path = strings.TrimSuffix(jsonPath, ".json") + "-CHECKLIST.md"
		}
		if err = automaticWrite(path, []byte(automaticMarkdown(report, true))); err != nil {
			return err
		}
		fmt.Printf("checklist: %s\n", path)
		return nil
	}
	c := &AutoContext{Root: "/", Repo: absRepo, Options: AutoOptions{Capture: *capture, Media: *media, StorageDir: *storageDir, User: *desktopUser}, Run: automaticCommand}
	fixture := *root != ""
	if fixture {
		c.Root, err = filepath.Abs(*root)
		if err != nil {
			return err
		}
		c.Fixture = true
		c.Run = nil
	} else {
		lock := filepath.Join(absRepo, "tools/spx/spx-lock")
		owner := fmt.Sprintf("automatic-hw-%d", os.Getpid())
		lockOutput, lockErr := c.Command(lock, "acquire", "device", owner)
		if lockErr != nil {
			reason := fmt.Errorf("device lock unavailable; no automatic checks run: %w", lockErr)
			if strings.Contains(lockOutput, "BUSY") {
				return &AutoExitError{75, reason}
			}
			return reason
		}
		defer func() {
			_, releaseErr := c.Command(lock, "release", "device", owner)
			if releaseErr != nil {
				err = errors.Join(err, fmt.Errorf("release device lock: %w", releaseErr))
			}
		}()
	}
	if *capture {
		fmt.Fprintln(os.Stderr, "Capture enabled: bounded camera/microphone checks may capture data; samples are discarded. No speaker playback is authorized by this flag.")
	}
	meta := AutoMetadata{Date: time.Now().Format(time.RFC3339), Fixture: fixture, Mode: "run"}
	report := automaticCollect(c, checks, meta)
	base := *output
	if base == "" {
		boot := report.Meta.BootID
		if len(boot) > 8 {
			boot = boot[:8]
		}
		if boot == "" {
			boot = "identity-unavailable"
		}
		base = filepath.Join(absRepo, "tools/spx/boot-diagnostics", "auto-hw-"+time.Now().Format("20060102-150405")+"-"+boot)
	}
	if fixture && *checklistPath == "" {
		mdPath, _ := automaticReportPaths(base)
		path = strings.TrimSuffix(mdPath, ".md") + "-CHECKLIST.md"
	}
	if err = automaticWriteReports(report, base, path); err != nil {
		return err
	}
	mdPath, jsonPath := automaticReportPaths(base)
	fmt.Printf("functional checks passed: %d of %d; inventory observed: %d of %d; blocked: %d; failed: %d; errors: %d\nreport: %s\nreport: %s\nchecklist: %s\n", report.Counts.Passed, report.Counts.Functional, report.Counts.Observed, report.Counts.Inventory, report.Counts.Blocked, report.Counts.Failed, report.Counts.Errors, mdPath, jsonPath, path)
	return automaticFailure(report)
}
