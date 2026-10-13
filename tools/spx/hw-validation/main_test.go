package main

import "testing"

func TestReportPaths(t *testing.T) {
	for _, input := range []string{"report", "report.json", "report.md"} {
		md, js := automaticReportPaths(input)
		if md != "report.md" || js != "report.json" {
			t.Fatalf("report paths: %q, %q", md, js)
		}
	}
}
