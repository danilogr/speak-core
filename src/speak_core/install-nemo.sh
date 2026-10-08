#!/usr/bin/env bash
# Install NeMo-Speech.cpp and the models every speak-core plugin uses.
# Idempotent: safe to run again. Downloads about 1.4 GB the first time.
set -euo pipefail

BIN="${NEMO_BIN:-nemo-speech}"
# speak-core-setup sets this to where the speech server reads its grammars.
TN_DIR="${NEMO_TN_DIR:?run this through speak-core-setup, which sets NEMO_TN_DIR}"
INSTALLER="${NEMO_INSTALLER:-https://github.com/NVIDIA/NeMo-Speech.cpp/raw/main/scripts/install.sh}"
# The supervisor runs the server on --device auto. Below 0.2.0, MagpieTTS on Metal
# returns DC saturation instead of speech on M5-class Macs, so older builds are upgraded.
MIN_VERSION=0.2.0

installed_version() {
  "$BIN" --version 2>/dev/null | awk '{print $2; exit}'
}

at_least_min() {
  [ "$(printf '%s\n%s\n' "$MIN_VERSION" "$1" | sort -V | head -n 1)" = "$MIN_VERSION" ]
}

if command -v "$BIN" >/dev/null 2>&1; then
  have="$(installed_version || true)"
  if at_least_min "$have"; then
    echo "nemo-speech $have already installed at $(command -v "$BIN")"
  else
    echo "nemo-speech ${have:-of unknown version} is older than $MIN_VERSION; upgrading from $INSTALLER"
    curl -fsSL "$INSTALLER" | sh
  fi
else
  echo "installing NeMo-Speech.cpp from $INSTALLER"
  curl -fsSL "$INSTALLER" | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# The upstream installer writes to its own prefix, so an older copy earlier on PATH
# (or an absolute NEMO_BIN) survives an upgrade and is what the plugin would run.
have="$(installed_version || true)"
if ! at_least_min "$have"; then
  echo "nemo-speech at $(command -v "$BIN" || echo "$BIN") is ${have:-of unknown version}," \
    "still older than $MIN_VERSION." >&2
  echo "Remove that copy or put ~/.local/bin first on PATH, then run this again." >&2
  exit 1
fi

echo "pulling the MagpieTTS model (640 MB with its codec, skipped if present)"
"$BIN" pull magpie

echo "pulling the transcription model (710 MB, skipped if present)"
"$BIN" pull nemotron-3.5

# MagpieTTS speaks numbers, prices, times and some abbreviations only after the server
# normalizes them into words, which takes these grammars. NVIDIA publishes them with each
# release, and they are matched to it, so a different version replaces them. Speech
# works without them, so a failed download warns rather than failing the setup.
install_grammars() {
  local marker="$TN_DIR/.nemo-speech-version" parent staging
  if [ -f "$TN_DIR/en/verbalize.far" ] && [ "$(cat "$marker" 2>/dev/null)" = "$have" ]; then
    echo "text-normalization grammars for $have already installed in $TN_DIR"
    return 0
  fi
  echo "downloading the text-normalization grammars for $have (9 MB, 137 MB unpacked)"
  parent="$(dirname "$TN_DIR")"
  mkdir -p "$parent" || return 1
  staging="$(mktemp -d "$parent/tn.XXXXXX")" || return 1
  if curl -fsSL "https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v$have/tn_configs.tar.bz2" |
    tar -xjf - -C "$staging" &&
    [ -f "$staging/tn_configs/en/tokenize_and_classify.far" ] &&
    [ -f "$staging/tn_configs/en/verbalize.far" ]; then
    echo "$have" >"$staging/tn_configs/.nemo-speech-version"
    rm -rf "$TN_DIR" && mv "$staging/tn_configs" "$TN_DIR" && rm -rf "$staging"
  else
    rm -rf "$staging"
    return 1
  fi
}

if ! install_grammars; then
  echo "could not install the text-normalization grammars for nemo-speech $have." >&2
  echo "Speech still works, but numbers and some abbreviations are read badly." >&2
  echo "Run this again to retry." >&2
fi

echo
"$BIN" doctor
echo
echo "Done. NeMo-Speech.cpp and both models are installed; the plugins start and stop"
echo "the speech server on their own. A server already running picks up new grammars"
echo "when it next starts."
