#!/usr/bin/env bash
# install_su2.sh — Download and set up SU2 for use with su2-mcp
#
# Usage:
#   bash scripts/install_su2.sh            # the pinned SU2 release binary
#   bash scripts/install_su2.sh --conda    # conda-forge instead (version not pinned)
#
# Installs the pinned SU2 release (the version every published number in this
# project was produced with) from the official GitHub release into
# ~/.local/su2, and refuses to report success unless the installed SU2_CFD
# actually runs. Solver versions matter: on the same mesh SU2 8.1.0 and 8.4.0
# differ by about 7 % in drag (su2-mcp/docs/PARALLEL_SU2.md), so this script
# does not take whatever version a package manager happens to have.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SU2_VERSION="8.4.0"
# SU2_INSTALL_DIR overrides the install location (used by the install tests).
INSTALL_DIR="${SU2_INSTALL_DIR:-${HOME}/.local/su2}"
USE_CONDA=0
for arg in "$@"; do
    case "$arg" in
        --conda) USE_CONDA=1 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo -e "${RED}Unknown option: $arg${NC}"; exit 2 ;;
    esac
done

echo "============================================"
echo "  SU2 MCP — Dependency Installer (SU2 v${SU2_VERSION})"
echo "============================================"
echo

if [ "$USE_CONDA" -eq 1 ]; then
    if command -v mamba &>/dev/null; then
        CONDA_CMD=mamba
    elif command -v conda &>/dev/null; then
        CONDA_CMD=conda
    else
        echo -e "${RED}--conda given but neither mamba nor conda is on PATH.${NC}"
        exit 1
    fi
    echo -e "${YELLOW}Installing SU2 from conda-forge with ${CONDA_CMD}. conda-forge does not"
    echo -e "carry v${SU2_VERSION}; the version you get will differ from the one this"
    echo -e "project's numbers were made with, and results will differ with it.${NC}"
    "$CONDA_CMD" install -y -c conda-forge su2
    SU2_CFD -h 2>&1 | head -1
    echo -e "${GREEN}Done. Verify with: SU2_CFD -h${NC}"
    exit 0
fi

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        ARCHIVE="SU2-v${SU2_VERSION}-linux64.zip"
        ;;
    Darwin)
        ARCHIVE="SU2-v${SU2_VERSION}-macos64.zip"
        if [ "$ARCH" = "arm64" ]; then
            # The release binary is built for Intel Macs. Apple's Rosetta runs
            # it on Apple silicon; without Rosetta it fails with "Bad CPU type".
            if ! arch -x86_64 /usr/bin/true 2>/dev/null; then
                echo -e "${RED}This Mac has an Apple-silicon chip and Rosetta is not installed.${NC}"
                echo "The SU2 release binary is built for Intel chips and needs Rosetta. Install it once with:"
                echo "  softwareupdate --install-rosetta --agree-to-license"
                echo "then run this script again."
                exit 1
            fi
        fi
        ;;
    *)
        echo -e "${RED}Unsupported OS: $OS${NC}"
        echo "On Windows, install WSL2 and run this script inside Ubuntu (RUN_THE_PIPELINE.md)."
        echo "Otherwise install SU2 manually: https://su2code.github.io/download.html"
        exit 1
        ;;
esac

for cmd in unzip; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}'$cmd' is not installed; the SU2 archive cannot be unpacked.${NC}"
        [ "$OS" = "Linux" ] && echo "  sudo apt-get install -y unzip"
        [ "$OS" = "Darwin" ] && echo "  brew install unzip"
        exit 1
    fi
done

DOWNLOAD_URL="https://github.com/su2code/SU2/releases/download/v${SU2_VERSION}/${ARCHIVE}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading SU2 v${SU2_VERSION}..."
echo "  URL: ${DOWNLOAD_URL}"
echo "  Target: ${INSTALL_DIR}"
echo

if command -v curl &>/dev/null; then
    curl -fSL "$DOWNLOAD_URL" -o "$TMP/${ARCHIVE}" || {
        echo -e "${RED}Download failed. Check the network, or download manually from${NC}"
        echo "  https://github.com/su2code/SU2/releases/tag/v${SU2_VERSION}"
        exit 1
    }
elif command -v wget &>/dev/null; then
    wget -q "$DOWNLOAD_URL" -O "$TMP/${ARCHIVE}" || {
        echo -e "${RED}Download failed.${NC}"
        exit 1
    }
else
    echo -e "${RED}Neither curl nor wget found. Cannot download.${NC}"
    exit 1
fi

echo "Extracting..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# unzip exits 1 for warnings (odd path separators, extra bytes) after a
# complete extraction; only 2 and above mean failure.
unzip_ok() { local rc=0; unzip -qo "$1" -d "$2" || rc=$?; [ "$rc" -le 1 ]; }
unzip_ok "$TMP/${ARCHIVE}" "$INSTALL_DIR"
# The v8.x release archives hold a second zip (linux64.zip / macos64.zip)
# with the actual files; unpack any inner archive too.
for inner in "$INSTALL_DIR"/*.zip; do
    [ -f "$inner" ] || continue
    unzip_ok "$inner" "$INSTALL_DIR"
    rm -f "$inner"
done

# No pipe here: with pipefail, `find | head -1` can end the script when find
# is cut off after the first match.
SU2_BIN=$(find "$INSTALL_DIR" -name "SU2_CFD" -type f 2>/dev/null)
SU2_BIN="${SU2_BIN%%$'\n'*}"
if [ -z "$SU2_BIN" ]; then
    echo -e "${RED}Could not find SU2_CFD after extraction.${NC}"
    ls -la "$INSTALL_DIR"
    exit 1
fi
chmod +x "$SU2_BIN"
SU2_BIN_DIR=$(dirname "$SU2_BIN")

# Shared libraries the Linux binary needs but a minimal system may lack. The
# release binary is statically linked (ldd then exits 1 with "not a dynamic
# executable", which is fine); a locally built one may not be.
if [ "$OS" = "Linux" ] && command -v ldd &>/dev/null; then
    MISSING=$( (ldd "$SU2_BIN" 2>/dev/null || true) | awk '/not found/ {print $1}' | sort -u | tr '\n' ' ')
    if [ -n "$MISSING" ]; then
        echo -e "${RED}SU2_CFD needs shared libraries this system does not have: ${MISSING}${NC}"
        echo "On Ubuntu/Debian the full set the pipeline needs is:"
        echo "  sudo apt-get install -y unzip zstd libglu1-mesa libgl1 libxrender1 libxcursor1 libxfixes3 libxft2 libfontconfig1 libxinerama1 libgomp1 libegl1 libosmesa6"
        exit 1
    fi
fi

# The installed binary must run and report the pinned version. On an
# Apple-silicon Mac without Rosetta this is where "Bad CPU type" would show.
BANNER=$("$SU2_BIN" -h 2>&1 | head -1 || true)
case "$BANNER" in
    *"v${SU2_VERSION}"*) ;;
    *)
        echo -e "${RED}SU2_CFD was installed but does not run as v${SU2_VERSION}. Output:${NC}"
        echo "  ${BANNER:-<no output>}"
        exit 1
        ;;
esac

echo
echo -e "${GREEN}SU2 v${SU2_VERSION} installed to: ${SU2_BIN_DIR}${NC}"
echo "  ${BANNER}"
echo
echo "Add to your PATH by running (and put it in your shell profile):"
echo "  export PATH=\"${SU2_BIN_DIR}:\$PATH\""
echo
echo -e "${GREEN}Verify with: SU2_CFD -h${NC}"
