#!/usr/bin/env bash
# ============================================================================
# install_midi_deps.sh — Provision Ubuntu 22.04 for MIDI dependencies only.
#
# What this does:
#   1. apt install every MIDI-related package listed in deps/apt_packages.txt.
#
# Safe to re-run.
#
# Run once as a user with sudo:
#     bash deps/install_midi_deps.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_LIST="${SCRIPT_DIR}/apt_packages.txt"

if [[ ! -f "${PKG_LIST}" ]]; then
    echo "ERROR: package list not found: ${PKG_LIST}" >&2
    exit 1
fi

echo "==> Installing MIDI-related packages from ${PKG_LIST}"
sudo apt-get update

# shellcheck disable=SC2046
sudo apt-get install -y $(grep -vE '^\s*(#|$)' "${PKG_LIST}")

echo
echo "Done. MIDI dependencies installed."