#!/bin/bash
# Installs the /extract slash command into Claude Code

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMANDS_DIR="$HOME/.claude/commands"
TEMPLATE="$REPO_DIR/commands/extract.md"
DEST="$COMMANDS_DIR/extract.md"

if ! command -v ffmpeg &>/dev/null; then
  echo "Error: ffmpeg is required but not installed."
  echo "  macOS:  brew install ffmpeg"
  echo "  Linux:  sudo apt install ffmpeg"
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "Error: python3 is required but not installed."
  exit 1
fi

mkdir -p "$COMMANDS_DIR"
sed "s|REPO_PATH|$REPO_DIR|g" "$TEMPLATE" > "$DEST"

echo "Installed /extract command → $DEST"
echo "Repo path: $REPO_DIR"
echo ""
echo "Usage in Claude Code:"
echo "  /extract /path/to/recording.mov"
