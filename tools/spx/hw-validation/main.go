// Surface Pro X automatic hardware validation CLI.
package main

import (
	"fmt"
	"os"
)

func main() {
	if err := automaticMain(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(automaticExitCode(err))
	}
}
