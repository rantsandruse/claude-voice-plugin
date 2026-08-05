#!/usr/bin/env bash
set -euo pipefail

echo ">> Checking Python 3.11+"
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'

echo ">> Installing package (editable)"
python3 -m pip install -e ".[dev]"

CFG_DIR="$HOME/.config/claude-voice"
mkdir -p "$CFG_DIR"

if [ ! -f "$CFG_DIR/config.yaml" ]; then
    cp config.yaml.example "$CFG_DIR/config.yaml"
    echo ">> Wrote $CFG_DIR/config.yaml"
fi
if [ ! -f "$CFG_DIR/.env" ]; then
    cp env.example "$CFG_DIR/.env"
    echo ">> Wrote $CFG_DIR/.env — add your API keys here"
fi

echo ">> Merging Stop hook into ~/.claude/settings.json"
python3 -m claude_voice._install merge-settings

cat <<'EOF'

============================================================
Install complete. Next steps:

1. Add your API keys in ~/.config/claude-voice/.env
2. Start the daemon:  claude-voice start
3. Grant Microphone and Accessibility permissions when prompted
4. To auto-start on login: System Settings → General → Login Items
   → add "claude-voice" (or run `claude-voice start` at login)
============================================================
EOF
