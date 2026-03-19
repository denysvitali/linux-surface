#!/bin/bash
# One-time setup script for self-hosted GitHub Actions runner
# Run this on the runner machine as the runner user

set -e

echo "Setting up persistent directories for kernel builds..."

# Create persistent directories
mkdir -p ~/kernel-builds
mkdir -p ~/.cache/ccache

echo "✓ Created directories:"
echo "  - ~/kernel-builds (for source and build artifacts)"
echo "  - ~/.cache/ccache (for compiler cache)"

# Configure ccache
echo ""
echo "Configuring ccache with 50GB cache..."
ccache -M 50G
ccache -s

echo ""
echo "✓ Ccache configured with 50GB max cache size"

# Add to .bashrc if not already present
BASHRC="$HOME/.bashrc"

if ! grep -q "CCACHE_DIR" "$BASHRC" 2>/dev/null; then
    echo ""
    echo "Adding ccache environment variables to .bashrc..."
    cat >> "$BASHRC" << 'EOF'

# Ccache configuration for kernel builds
export CCACHE_DIR="$HOME/.cache/ccache"
export CCACHE_MAXSIZE=50G
EOF
    echo "✓ Added to .bashrc"
else
    echo "✓ Ccache already configured in .bashrc"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Persistent storage locations:"
echo "  Source:     ~/kernel-builds/linux-surface-src"
echo "  Build:      ~/kernel-builds/linux-surface-build"
echo "  Ccache:     $CCACHE_DIR"
echo ""
echo "Next steps:"
echo "  1. Ensure this machine is registered as a self-hosted runner with label 'arm64'"
echo "  2. Push to an 'spx/*' branch to trigger the workflow"
echo "  3. Monitor the first build (may take 30-60 minutes)"
echo ""
echo "To check ccache stats later: ccache -s"
echo "To clear caches: rm -rf ~/kernel-builds ~/.cache/ccache"
