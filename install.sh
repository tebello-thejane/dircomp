#!/usr/bin/env bash
# dircomp installer — idempotent: safe to re-run for updates.
#
#   curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/vX.Y.Z/install.sh | bash
#
# Pin to a tag (vX.Y.Z), never to a branch — curl|bash has no verification
# step of its own, and a branch can change under you between the curl and
# the bash. Read this file before piping it to a shell, same as any other
# curl|bash install; it only writes under ~/.local/share/dircomp and adds
# one guarded block to ~/.bashrc.
set -euo pipefail

REPO_RAW="${DIRCOMP_REPO_RAW:-https://raw.githubusercontent.com/tebello-thejane/dircomp/main}"
INSTALL_DIR="$HOME/.local/share/dircomp"
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

mkdir -p "$INSTALL_DIR"

if [[ -n "${DIRCOMP_LOCAL_SOURCE:-}" ]]; then
    # Local dev/test path: install.sh sits next to lib/dircomp.bash.
    cp "$(dirname "$0")/lib/dircomp.bash" "$INSTALL_DIR/dircomp.bash"
else
    curl -fsSL "$REPO_RAW/lib/dircomp.bash" -o "$INSTALL_DIR/dircomp.bash"
fi
chmod 0644 "$INSTALL_DIR/dircomp.bash"

BLOCK=$(cat <<BLK
$MARK_BEGIN
# Managed by dircomp's installer — do not hand-edit; re-run install.sh to update.
[ -f "$INSTALL_DIR/dircomp.bash" ] && source "$INSTALL_DIR/dircomp.bash"
$MARK_END
BLK
)

touch "$BASHRC"
if grep -qF "$MARK_BEGIN" "$BASHRC"; then
    # Replace the existing block in place (portable awk, no sed -i -z).
    tmp=$(mktemp)
    awk -v begin="$MARK_BEGIN" -v end="$MARK_END" -v block="$BLOCK" '
        $0 == begin { print block; skip = 1; next }
        $0 == end   { skip = 0; next }
        !skip       { print }
    ' "$BASHRC" > "$tmp"
    mv "$tmp" "$BASHRC"
    echo "dircomp: updated existing install in $BASHRC"
else
    { echo; echo "$BLOCK"; } >> "$BASHRC"
    echo "dircomp: installed. Restart your shell, or: source $BASHRC"
fi
