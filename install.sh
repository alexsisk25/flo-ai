#!/usr/bin/env bash
#
# Walnut installer.  curl-free path:  git clone … && cd walnut && ./install.sh
#
#   ./install.sh              install deps, run a self-test
#   ./install.sh --login      …and start Walnut automatically at login
#   ./install.sh --uninstall  remove the login item (keeps your data)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.walnut.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
die()  { printf "\033[31merror:\033[0m %s\n" "$1" >&2; exit 1; }

RETIRED=0

# Retire any older Walnut login item (e.g. a hand-written com.brandon.walnut)
# so we never end up with two instances fighting over port 8765 and the hotkeys.
retire_legacy() {
  local p
  for p in "$HOME"/Library/LaunchAgents/*walnut*.plist; do
    [ -e "$p" ] || continue                 # no match: glob stayed literal
    [ "$p" = "$PLIST" ] && continue         # ours, not legacy
    launchctl unload "$p" 2>/dev/null || true
    mv "$p" "$p.disabled"
    bold "Retired older login item: $(basename "$p") → $(basename "$p").disabled"
    RETIRED=1
  done
}

uninstall() {
  local removed=0
  if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    bold "Removed login item."
    removed=1
  fi
  retire_legacy
  if [ "$removed" = 1 ] || [ "$RETIRED" = 1 ]; then
    bold "Your walnut.db and recordings are untouched."
  else
    echo "No login item installed."
  fi
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

[ "$(uname -s)" = "Darwin" ] || die "Walnut is macOS-only (it uses \`say\` and \`afplay\`)."

# ---------------------------------------------------------------- uv
if ! command -v uv >/dev/null 2>&1; then
  bold "Installing uv (the Python package manager Walnut uses)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv lands in one of these depending on the installer version
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv install failed; see https://docs.astral.sh/uv/"
fi

# ---------------------------------------------------------------- deps
bold "Installing dependencies…"
cd "$REPO"
uv sync

# Apple Silicon gets mlx-whisper (GPU) as well as faster-whisper; Intel Macs
# get faster-whisper alone. pyproject.toml decides via a platform marker, so
# there is nothing to choose here.
bold "Checking what Walnut found on this Mac…"
uv run walnut.py --doctor

# ---------------------------------------------------------------- self-test
bold "Running the self-test (first run downloads the speech model)…"
if uv run walnut.py --test; then
  bold "Self-test passed."
else
  die "Self-test failed. Run \`uv run walnut.py --doctor\` and check the output above."
fi

# ---------------------------------------------------------------- login item
if [ "${1:-}" = "--login" ]; then
  bold "Installing login item…"
  retire_legacy
  mkdir -p "$HOME/Library/LaunchAgents"
  # Launch through `uv run` rather than .venv/bin/python: macOS binds
  # Accessibility permission to the launching binary, and uv keeps the
  # environment correct even after a dependency change.
  UV_BIN="$(command -v uv)"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV_BIN</string>
    <string>run</string>
    <string>--project</string><string>$REPO</string>
    <string>$REPO/walnut.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/walnut.log</string>
  <key>StandardErrorPath</key><string>/tmp/walnut.log</string>
</dict>
</plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  bold "Walnut will start at login. Logs: /tmp/walnut.log"
fi

cat <<'DONE'

──────────────────────────────────────────────────────────────
Walnut is installed.  Start it with:

    uv run walnut.py

Then grant macOS permissions ONCE (Walnut cannot do this for you):

  1. Accessibility     System Settings → Privacy & Security →
                       Accessibility → add your Terminal
                       (needed for global hotkeys + typing into apps)
  2. Microphone        macOS asks the first time you dictate → Allow
  3. Input Monitoring  only if hotkeys still don't fire

Restart Walnut after granting Accessibility.

  ⌃⌥S      narrate the selected text in any app
  ⌃⌥Space  toggle dictation into the frontmost app
  Dashboard → http://127.0.0.1:8765
──────────────────────────────────────────────────────────────
DONE
