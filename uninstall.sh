#!/usr/bin/env bash
# dircomp uninstaller — removes the installed library and the bashrc block.
# Project .completions/ files are untouched; they're inert without this.
set -euo pipefail
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

if grep -qF "$MARK_BEGIN" "$BASHRC" 2>/dev/null; then
    tmp=$(mktemp)
    awk -v begin="$MARK_BEGIN" -v end="$MARK_END" '
        $0 == begin { skip = 1; next }
        $0 == end   { skip = 0; next }
        !skip       { print }
    ' "$BASHRC" > "$tmp"
    mv "$tmp" "$BASHRC"
    echo "dircomp: removed block from $BASHRC"
else
    echo "dircomp: no managed block found in $BASHRC"
fi
rm -rf "$HOME/.local/share/dircomp"
echo "dircomp: removed $HOME/.local/share/dircomp"
