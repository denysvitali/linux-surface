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

# Install ccache if not present
echo ""
echo "Installing ccache..."
if ! command -v ccache &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y ccache
fi
echo "✓ ccache installed: $(ccache --version)"

# Configure ccache
echo ""
echo "Configuring ccache with 50GB cache..."
ccache -M 50G

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

# Install gh CLI if not present
echo ""
echo "Checking for gh CLI..."
if command -v gh &> /dev/null; then
    echo "✓ gh CLI already installed: $(gh --version)"
else
    echo "Installing gh CLI..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y gh
    echo "✓ gh CLI installed: $(gh --version)"
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
