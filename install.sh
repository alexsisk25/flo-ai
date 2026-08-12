#!/usr/bin/env bash
#
# Flo installer.  curl-free path:  git clone … && cd flo && ./install.sh
#
#   ./install.sh              install deps, run a self-test
#   ./install.sh --app        …and build Flo.app (double-click / Spotlight)
#   ./install.sh --login      …and start Flo automatically at login
#   ./install.sh --uninstall  remove the app + login item (keeps your data)
#
# Flags combine:  ./install.sh --app --login
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.flo.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT=8765

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
die()  { printf "\033[31merror:\033[0m %s\n" "$1" >&2; exit 1; }

WANT_APP=0
WANT_LOGIN=0
WANT_UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --app)       WANT_APP=1 ;;
    --login)     WANT_LOGIN=1 ;;
    --uninstall) WANT_UNINSTALL=1 ;;
    -h|--help)   sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           die "unknown flag: $arg (try --help)" ;;
  esac
done

# Prefer /Applications, fall back to ~/Applications if it isn't writable.
app_dir() {
  if [ -w /Applications ]; then echo "/Applications"; else echo "$HOME/Applications"; fi
}
APP="$(app_dir)/Flo.app"

RETIRED=0

# Retire any older Flo login item (e.g. a hand-written com.brandon.flo)
# so we never end up with two instances fighting over port 8765 and the hotkeys.
retire_legacy() {
  local p
  for p in "$HOME"/Library/LaunchAgents/*flo*.plist; do
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
  for candidate in /Applications/Flo.app "$HOME/Applications/Flo.app"; do
    if [ -d "$candidate" ]; then
      rm -rf "$candidate"
      bold "Removed $candidate"
      removed=1
    fi
  done
  retire_legacy
  if [ "$removed" = 1 ] || [ "$RETIRED" = 1 ]; then
    bold "Your flo.db and recordings are untouched."
  else
    echo "Nothing installed."
  fi
  exit 0
}

# ---------------------------------------------------------------- Flo.app
# A thin bundle: the executable is a shell script that runs the repo through
# uv. No frozen Python, no code signing, nothing to rebuild when the code
# changes — the app is a launcher, the repo stays the source of truth.
build_app() {
  local uv_bin="$1" icons work
  bold "Building ${APP}…"   # braces: bash folds a bare … into the var name
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

  # Icon: source art is 180px, so stop at 256 rather than upscale to a mushy
  # 1024. macOS scales down from 256 cleanly for Dock/Finder/Spotlight.
  work="$(mktemp -d)"
  icons="$work/flo.iconset"
  mkdir -p "$icons"
  for sz in 16 32 128 256; do
    sips -z $sz $sz "$REPO/static/apple-touch-icon.png" \
         --out "$icons/icon_${sz}x${sz}.png" >/dev/null 2>&1
  done
  # @2x variants, capped at the same 256px ceiling
  sips -z 32  32  "$REPO/static/apple-touch-icon.png" --out "$icons/icon_16x16@2x.png"  >/dev/null 2>&1
  sips -z 64  64  "$REPO/static/apple-touch-icon.png" --out "$icons/icon_32x32@2x.png"  >/dev/null 2>&1
  sips -z 256 256 "$REPO/static/apple-touch-icon.png" --out "$icons/icon_128x128@2x.png" >/dev/null 2>&1
  iconutil -c icns "$icons" -o "$APP/Contents/Resources/flo.icns" 2>/dev/null \
    || bold "  (icon build skipped; app will use the default icon)"
  rm -rf "$work"

  cat > "$APP/Contents/Info.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Flo</string>
  <key>CFBundleDisplayName</key><string>Flo</string>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleExecutable</key><string>flo</string>
  <key>CFBundleIconFile</key><string>flo</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.1.3</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- menu bar utility: live in the status bar, not the Dock -->
  <key>LSUIElement</key><true/>
  <!-- shown in the macOS prompt when Flo first records -->
  <key>NSMicrophoneUsageDescription</key>
  <string>Flo transcribes your speech on this Mac. Audio never leaves it.</string>
</dict>
</plist>
PLIST_EOF

  cat > "$APP/Contents/MacOS/flo" <<LAUNCH_EOF
#!/bin/bash
# Thin launcher — the real code lives in the repo below.
REPO="$REPO"
UV="$uv_bin"
PORT=$PORT

# Already running (e.g. started at login)? Don't start a second instance
# fighting over the port and the hotkeys — just show the dashboard.
if /usr/bin/nc -z 127.0.0.1 "\$PORT" 2>/dev/null; then
  exec /usr/bin/open "http://127.0.0.1:\$PORT"
fi

[ -x "\$UV" ] || UV="\$(command -v uv 2>/dev/null)"
[ -x "\$UV" ] || { /usr/bin/osascript -e 'display alert "Flo" message "uv not found. Run ./install.sh in the flo repo."'; exit 1; }

# The bundle stores an absolute path. If the repo moved, say so rather than
# failing with a silent `cd` error.
if [ ! -f "\$REPO/flo.py" ]; then
  /usr/bin/osascript -e 'display alert "Flo" message "The Flo folder moved or was deleted. Re-run ./install.sh --app from its new location."'
  exit 1
fi

cd "\$REPO" || exit 1
exec "\$UV" run --project "\$REPO" "\$REPO/flo.py"
LAUNCH_EOF
  chmod +x "$APP/Contents/MacOS/flo"

  # Ad-hoc sign so macOS gives the bundle a stable identity for TCC
  # (Accessibility/Microphone). Without this the grant can reset on edits.
  codesign --force --deep --sign - "$APP" 2>/dev/null \
    || bold "  (ad-hoc signing unavailable; you may need to re-grant permissions after updates)"

  # Let Finder/Spotlight/Launchpad notice it immediately.
  touch "$APP"
  bold "Built $APP"
}

[ "$WANT_UNINSTALL" = 1 ] && uninstall

[ "$(uname -s)" = "Darwin" ] || die "Flo is macOS-only (it uses \`say\` and \`afplay\`)."

# ---------------------------------------------------------------- uv
if ! command -v uv >/dev/null 2>&1; then
  bold "Installing uv (the Python package manager Flo uses)…"
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
bold "Checking what Flo found on this Mac…"
# --doctor exits 1 when Accessibility isn't granted yet, which is the normal
# state during a first install. Report it, don't abort on it.
uv run flo.py --doctor || true

# ---------------------------------------------------------------- self-test
bold "Running the self-test."
bold "The first run downloads the speech model — about 1.6 GB on Apple Silicon,"
bold "460 MB on Intel. It happens once, and it is cached for good."
if uv run flo.py --test; then
  bold "Self-test passed."
else
  die "Self-test failed. Run \`uv run flo.py --doctor\` and check the output above."
fi

UV_BIN="$(command -v uv)"

# ---------------------------------------------------------------- Flo.app
[ "$WANT_APP" = 1 ] && build_app "$UV_BIN"

# ---------------------------------------------------------------- login item
if [ "$WANT_LOGIN" = 1 ]; then
  bold "Installing login item…"
  retire_legacy
  mkdir -p "$HOME/Library/LaunchAgents"
  # Launch through `uv run` rather than .venv/bin/python: macOS binds
  # Accessibility permission to the launching binary, and uv keeps the
  # environment correct even after a dependency change.
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
    <string>$REPO/flo.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/flo.log</string>
  <key>StandardErrorPath</key><string>/tmp/flo.log</string>
</dict>
</plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  bold "Flo will start at login. Logs: /tmp/flo.log"
fi

cat <<'DONE'

──────────────────────────────────────────────────────────────
Flo is installed.  Start it with:

    uv run flo.py

Then grant macOS permissions ONCE (Flo cannot do this for you).

ACCESSIBILITY — needed for global hotkeys and for typing into other apps.
macOS grants this to the program that RUNS the code, not to "Flo", so you
need TWO entries in System Settings -> Privacy & Security -> Accessibility:

  a) Terminal.app        for running \`uv run flo.py\` by hand.
                         Quit Terminal with Cmd+Q and reopen it afterwards —
                         the permission is only read when a process starts.
  b) the \`uv\` binary     for the login agent, which runs Flo at startup.
                         Run \`which uv\` (usually /opt/homebrew/bin/uv), then
                         click +, press Cmd+Shift+G, and paste that path.

  Heads up: \`brew upgrade uv\` replaces that binary and can silently void the
  grant. If the hotkey ever stops firing for no reason, re-add it here.

MICROPHONE — macOS asks the first time the menu-bar app starts. Click Allow.
  If you are never asked, check that pyobjc-framework-avfoundation is
  installed; without it Flo cannot ask, and it will record pure silence while
  looking like it is working.

INPUT MONITORING — only if hotkeys still do not fire.

Check both at any time with:  uv run flo.py --doctor
It reports Accessibility and Microphone, and exits non-zero if either is wrong.

  Hold Right Option   push-to-talk: hold, speak, release — types into any app
  Option + S          narrate the selected text in any app
  Dashboard → http://127.0.0.1:8765
──────────────────────────────────────────────────────────────
DONE
