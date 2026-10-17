#!/bin/bash
# Installs Auto-Delete Posts on a Mac and starts it.
#
#   curl -fsSL https://raw.githubusercontent.com/Zutrak00/Auto-Delete-Post-/main/install-mac.sh | bash
#
# Why a Terminal command: macOS blocks apps downloaded in a web browser unless the developer pays Apple to
# notarize them ("Apple could not verify ... is free of malware"). Files downloaded with curl aren't marked as
# downloaded, so the app runs without that block.
#
# Already downloaded the Mac zip in a browser? It contains this script. In Terminal type "bash " and drag
# install-mac.sh from the unzipped folder into the window, then press Enter. A zip or folder path also works:
#   bash install-mac.sh ~/Downloads/AutoDeletePosts-Mac.zip
set -euo pipefail

URL="https://github.com/Zutrak00/Auto-Delete-Post-/releases/latest/download/AutoDeletePosts-Mac.zip"
DEST="$HOME/Applications/AutoDeletePosts"
LAUNCHER="$HOME/Desktop/Auto-Delete Posts.command"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is for Macs. Windows and Linux downloads are on the Releases page."
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "This download needs an Apple Silicon Mac (M1 or newer)."
  echo "On an Intel Mac, follow 'Run from source' in the README instead."
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

here=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ $# -ge 1 ] && [ -d "$1" ]; then
  (cd "$1" && zip -qr "$tmp/app.zip" AutoDeletePosts)
elif [ $# -ge 1 ]; then
  cp "$1" "$tmp/app.zip"
elif [ -n "$here" ] && [ -f "$here/AutoDeletePosts" ]; then
  # Run from the unzipped download folder.
  (cd "$here" && zip -qr "$tmp/app.zip" AutoDeletePosts)
else
  echo "Downloading Auto-Delete Posts..."
  if ! curl -fL --progress-bar "$URL" -o "$tmp/app.zip"; then
    echo
    echo "The download failed. If the project's GitHub page is private, ask its owner to make it public."
    echo "Or download AutoDeletePosts-Mac.zip in your browser, open its folder, type 'bash ' here,"
    echo "drag install-mac.sh from that folder into this window, and press Enter."
    exit 1
  fi
fi

mkdir -p "$DEST"
unzip -oq "$tmp/app.zip" -d "$DEST"
chmod +x "$DEST/AutoDeletePosts"
# Clear the "downloaded from the internet" mark in case the zip came from a browser.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

cat > "$LAUNCHER" <<EOF
#!/bin/bash
# Starts Auto-Delete Posts. Keep the window open while you use it.
exec "$DEST/AutoDeletePosts"
EOF
chmod +x "$LAUNCHER"

echo
echo "Installed. From now on, double-click 'Auto-Delete Posts' on your Desktop to start it."
echo "Starting it now..."
rm -rf "$tmp"  # exec below replaces this shell, so the cleanup trap wouldn't run
exec "$DEST/AutoDeletePosts"
