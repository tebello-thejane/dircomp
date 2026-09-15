#!/usr/bin/env bash
# dircomp uninstaller — removes the installed library and the bashrc block.
# Project .completions/ files are untouched; they're inert without this.
set -euo pipefail
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

die() { echo "dircomp: $*" >&2; exit 1; }

if [[ -f $BASHRC ]]; then
    n_begin=$(grep -cF -- "$MARK_BEGIN" "$BASHRC" || true)
    n_end=$(grep -cF -- "$MARK_END" "$BASHRC" || true)

    if (( n_begin == 0 && n_end == 0 )); then
        echo "dircomp: no managed block found in $BASHRC"
    elif (( n_begin == 1 && n_end == 1 )); then
        line_begin=$(grep -nF -- "$MARK_BEGIN" "$BASHRC" | head -1 | cut -d: -f1)
        line_end=$(grep -nF -- "$MARK_END" "$BASHRC" | head -1 | cut -d: -f1)
        (( line_begin < line_end )) || die "$BASHRC has inverted dircomp markers — fix by hand, refusing to rewrite"
        tmp=$(mktemp)
        trap 'rm -f "$tmp"' EXIT
        awk -v begin="$MARK_BEGIN" -v end="$MARK_END" '
            $0 == begin { skip = 1; next }
            $0 == end   { skip = 0; next }
            !skip       { print }
        ' "$BASHRC" > "$tmp"
        # Write through the path so mode and any dotfiles symlink survive.
        cat "$tmp" > "$BASHRC"
        rm -f "$tmp"
        trap - EXIT
        echo "dircomp: removed block from $BASHRC"
    else
        die "$BASHRC has a malformed dircomp block ($n_begin begin / $n_end end marker(s)) — fix it by hand, refusing to rewrite"
    fi
fi

rm -rf "$HOME/.local/share/dircomp"
echo "dircomp: removed $HOME/.local/share/dircomp"
