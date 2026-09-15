#!/usr/bin/env bash
# dircomp installer — idempotent: safe to re-run for updates.
#
#   curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.1.2/install.sh | bash
#
# Pin to a tag (vX.Y.Z), never to a branch — curl|bash has no verification
# step of its own, and a branch can change under you between the curl and the
# bash. This script fetches the library from the SAME ref it was published
# under (DIRCOMP_RELEASE below), so a pinned installer installs a pinned
# library. It only writes under ~/.local/share/dircomp and adds one guarded
# block to ~/.bashrc.
set -euo pipefail

# Bumped as part of the release process; must match the tag this file is
# published under, or a pinned install silently pulls an unpinned library.
DIRCOMP_RELEASE="v0.1.2"

REPO_RAW="${DIRCOMP_REPO_RAW:-https://raw.githubusercontent.com/tebello-thejane/dircomp/$DIRCOMP_RELEASE}"
INSTALL_DIR="$HOME/.local/share/dircomp"
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

die() { echo "dircomp: $*" >&2; exit 1; }

mkdir -p "$INSTALL_DIR"

# --- fetch to a temp file, validate, then replace atomically ---------------
# A download that fails midway must not leave a working install truncated.
tmp=$(mktemp "$INSTALL_DIR/.dircomp.bash.XXXXXX")
trap 'rm -f "$tmp"' EXIT

if [[ -n "${DIRCOMP_LOCAL_SOURCE:-}" ]]; then
    cp "$(dirname "$0")/lib/dircomp.bash" "$tmp"
else
    curl -fsSL "$REPO_RAW/lib/dircomp.bash" -o "$tmp"
fi

bash -n "$tmp" || die "downloaded library failed syntax check — install aborted, existing install untouched"
grep -q 'DIRCOMP_VERSION=' "$tmp" || die "downloaded file does not look like dircomp — install aborted"

chmod 0644 "$tmp"
mv "$tmp" "$INSTALL_DIR/dircomp.bash"
trap - EXIT

# --- bashrc block ----------------------------------------------------------
BLOCK=$(cat <<BLK
$MARK_BEGIN
# Managed by dircomp's installer — do not hand-edit; re-run install.sh to update.
[ -f "$INSTALL_DIR/dircomp.bash" ] && source "$INSTALL_DIR/dircomp.bash"
$MARK_END
BLK
)

touch "$BASHRC"

# Refuse to touch a file whose markers are missing, duplicated, or inverted.
# Rewriting on a half-present block silently deletes whatever follows it.
n_begin=$(grep -cF -- "$MARK_BEGIN" "$BASHRC" || true)
n_end=$(grep -cF -- "$MARK_END" "$BASHRC" || true)

if (( n_begin == 0 && n_end == 0 )); then
    state=absent
elif (( n_begin == 1 && n_end == 1 )); then
    line_begin=$(grep -nF -- "$MARK_BEGIN" "$BASHRC" | head -1 | cut -d: -f1)
    line_end=$(grep -nF -- "$MARK_END" "$BASHRC" | head -1 | cut -d: -f1)
    (( line_begin < line_end )) && state=present || state=malformed
else
    state=malformed
fi

[[ $state == malformed ]] && die "$BASHRC has a malformed dircomp block ($n_begin begin / $n_end end marker(s)) — fix it by hand, refusing to rewrite"

if [[ $state == present ]]; then
    tmp_rc=$(mktemp)
    trap 'rm -f "$tmp_rc"' EXIT
    awk -v begin="$MARK_BEGIN" -v end="$MARK_END" -v block="$BLOCK" '
        $0 == begin { print block; skip = 1; next }
        $0 == end   { skip = 0; next }
        !skip       { print }
    ' "$BASHRC" > "$tmp_rc"
    # Write THROUGH the existing path, not over it: `mv` would clobber the
    # file's mode (mktemp is 0600) and replace a dotfiles symlink with a
    # regular file, orphaning the real target.
    cat "$tmp_rc" > "$BASHRC"
    rm -f "$tmp_rc"
    trap - EXIT
    echo "dircomp $DIRCOMP_RELEASE: updated existing install in $BASHRC"
else
    { echo; echo "$BLOCK"; } >> "$BASHRC"
    echo "dircomp $DIRCOMP_RELEASE: installed. Restart your shell, or: source $BASHRC"
fi
