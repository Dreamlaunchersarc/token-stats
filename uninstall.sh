#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${CYAN}"
echo "  ╭────────────────────────────────────────╮"
echo "  │   Claude Token Stats - Uninstall      │"
echo "  ╰────────────────────────────────────────╯"
echo -e "${NC}"

CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
STATS_DIR="$CLAUDE_DIR/stats"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

# Remove hook scripts
echo -e "${CYAN}Removing hook scripts...${NC}"
rm -f "$HOOKS_DIR/log-token-stats.py"
rm -f "$HOOKS_DIR/claude-stats"

# Remove hooks from settings.json
if [ -f "$SETTINGS_FILE" ]; then
    echo -e "${CYAN}Removing hooks from settings...${NC}"
    python3 << 'EOF'
import json

settings_file = "$HOME/.claude/settings.json".replace("$HOME", __import__("os").environ["HOME"])

try:
    with open(settings_file, 'r') as f:
        settings = json.load(f)

    if 'hooks' in settings and 'PostToolUse' in settings['hooks']:
        del settings['hooks']['PostToolUse']
        if not settings['hooks']:
            del settings['hooks']

    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=2)

    print("Settings updated")
except Exception as e:
    print(f"Could not update settings: {e}")
EOF
fi

# Remove shell alias
for rc_file in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [ -f "$rc_file" ]; then
        if grep -q 'claude-stats' "$rc_file" 2>/dev/null; then
            # Remove the alias lines
            sed -i.bak '/# Claude Token Stats/d' "$rc_file"
            sed -i.bak '/alias claude-stats/d' "$rc_file"
            rm -f "${rc_file}.bak"
            echo -e "${GREEN}Removed alias from $rc_file${NC}"
        fi
    fi
done

echo ""
echo -e "${BOLD}${GREEN}Uninstall complete!${NC}"
echo ""

# Ask about stats data
echo -e "${YELLOW}Your stats data is still saved at:${NC}"
echo -e "  $STATS_DIR"
echo ""
read -p "Do you want to delete your stats data? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$STATS_DIR"
    echo -e "${GREEN}Stats data deleted${NC}"
else
    echo -e "${CYAN}Stats data preserved${NC}"
fi

echo ""
echo -e "${YELLOW}Note:${NC} Restart your shell to complete the uninstall"
echo ""
