#!/usr/bin/env bash
# install_su2.sh — Download and set up SU2 for use with su2-mcp
#
# Usage:
#   bash scripts/install_su2.sh
#
# This script attempts to install SU2 via the best available method:
#   1. conda/mamba (preferred)
#   2. Pre-built binary download from su2code.github.io
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================"
echo "  SU2 MCP — Dependency Installer"
echo "============================================"
echo

if command -v mamba &>/dev/null; then
    echo -e "${GREEN}Found mamba. Installing SU2 + Gmsh via conda-forge...${NC}"
    mamba install -y -c conda-forge su2 gmsh python-gmsh
    echo -e "${GREEN}Done! Verify with: SU2_CFD --version${NC}"
    exit 0
elif command -v conda &>/dev/null; then
    echo -e "${GREEN}Found conda. Installing SU2 + Gmsh via conda-forge...${NC}"
    conda install -y -c conda-forge su2 gmsh python-gmsh
    echo -e "${GREEN}Done! Verify with: SU2_CFD --version${NC}"
    exit 0
fi

echo -e "${YELLOW}No conda/mamba found. Attempting binary download...${NC}"
echo

OS="$(uname -s)"
ARCH="$(uname -m)"
SU2_VERSION="8.1.0"

case "$OS" in
    Linux)
        ARCHIVE="SU2-v${SU2_VERSION}-linux64.zip"
        ;;
    Darwin)
        if [ "$ARCH" = "arm64" ]; then
            echo -e "${YELLOW}Note: SU2 pre-built binaries may not be available for Apple Silicon.${NC}"
            echo -e "${YELLOW}Consider using Docker or conda instead.${NC}"
        fi
        ARCHIVE="SU2-v${SU2_VERSION}-macosX.zip"
        ;;
    *)
        echo -e "${RED}Unsupported OS: $OS${NC}"
        echo "Please install SU2 manually: https://su2code.github.io/download.html"
        exit 1
        ;;
esac

DOWNLOAD_URL="https://github.com/su2code/SU2/releases/download/v${SU2_VERSION}/${ARCHIVE}"
INSTALL_DIR="${HOME}/.local/su2"

echo "Downloading SU2 v${SU2_VERSION}..."
echo "  URL: ${DOWNLOAD_URL}"
echo "  Target: ${INSTALL_DIR}"
echo

mkdir -p "$INSTALL_DIR"

if command -v curl &>/dev/null; then
    curl -fSL "$DOWNLOAD_URL" -o "/tmp/${ARCHIVE}" || {
        echo -e "${RED}Download failed. The version or platform may not be available.${NC}"
        echo "Please download manually from: https://su2code.github.io/download.html"
        exit 1
    }
elif command -v wget &>/dev/null; then
    wget -q "$DOWNLOAD_URL" -O "/tmp/${ARCHIVE}" || {
        echo -e "${RED}Download failed.${NC}"
        exit 1
    }
else
    echo -e "${RED}Neither curl nor wget found. Cannot download.${NC}"
    exit 1
fi

echo "Extracting..."
unzip -qo "/tmp/${ARCHIVE}" -d "$INSTALL_DIR"
rm -f "/tmp/${ARCHIVE}"

SU2_BIN=$(find "$INSTALL_DIR" -name "SU2_CFD" -type f 2>/dev/null | head -1)
if [ -z "$SU2_BIN" ]; then
    echo -e "${RED}Could not find SU2_CFD after extraction.${NC}"
    ls -la "$INSTALL_DIR"
    exit 1
fi

SU2_BIN_DIR=$(dirname "$SU2_BIN")

echo
echo -e "${GREEN}SU2 installed to: ${SU2_BIN_DIR}${NC}"
echo
echo "Add to your PATH by running:"
echo "  export PATH=\"${SU2_BIN_DIR}:\$PATH\""
echo "  export SU2_RUN=\"${SU2_BIN_DIR}\""
echo
echo -e "${GREEN}Verify with: SU2_CFD --version${NC}"
