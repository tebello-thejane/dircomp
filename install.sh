#!/usr/bin/env bash
# dircomp installer — idempotent: safe to re-run for updates.
#
#   curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.1.3/install.sh | bash
#
# Pin to a tag (vX.Y.Z), never to a branch — curl|bash has no verification
# step of its own, and a branch can change under you between the curl and the
# bash. This script fetches the library from the SAME ref it was published
# under (DIRCOMP_RELEASE below), so a pinned installer installs a pinned
# library. It only writes under ~/.local/share/dircomp and adds one guarded
# block to ~/.bashrc.
#
# Order matters: every check that can refuse runs BEFORE anything is written,
# so a refusal leaves both the library and ~/.bashrc exactly as they were.
set -euo pipefail

# Bumped as part of the release process; must match the tag this file is
# published under, or a pinned install silently pulls an unpinned library.
DIRCOMP_RELEASE="v0.1.3"

REPO_RAW="${DIRCOMP_REPO_RAW:-https://raw.githubusercontent.com/tebello-thejane/dircomp/$DIRCOMP_RELEASE}"
INSTALL_DIR="$HOME/.local/share/dircomp"
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

die() { echo "dircomp: $*" >&2; exit 1; }

# --- 1. validate ~/.bashrc marker state (read-only) ------------------------
# Markers must match as WHOLE LINES (-x), because the awk rewrite below
# compares $0 == marker. A substring match here with an exact match there
# would report success while installing nothing. Refuse on missing,
# duplicated, or inverted markers: rewriting a half-present block silently
# deletes everything after it.
touch "$BASHRC"
n_begin=$(grep -cxF -- "$MARK_BEGIN" "$BASHRC" || true)
n_end=$(grep -cxF -- "$MARK_END" "$BASHRC" || true)

if (( n_begin == 0 && n_end == 0 )); then
    state=absent
elif (( n_begin == 1 && n_end == 1 )); then
    line_begin=$(grep -nxF -- "$MARK_BEGIN" "$BASHRC" | head -1 | cut -d: -f1)
    line_end=$(grep -nxF -- "$MARK_END" "$BASHRC" | head -1 | cut -d: -f1)
    (( line_begin < line_end )) && state=present || state=malformed
else
    state=malformed
fi
[[ $state == malformed ]] && die "$BASHRC has a malformed dircomp block ($n_begin begin / $n_end end marker(s)) — fix it by hand, refusing to rewrite"

# --- 2. fetch the library to a temp file and validate it (nothing replaced yet)
mkdir -p "$INSTALL_DIR"
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

# --- 3. build the new bashrc content in memory (still nothing written) -----
BLOCK=$(cat <<BLK
$MARK_BEGIN
# Managed by dircomp's installer — do not hand-edit; re-run install.sh to update.
[ -f "$INSTALL_DIR/dircomp.bash" ] && source "$INSTALL_DIR/dircomp.bash"
$MARK_END
BLK
)
if [[ $state == present ]]; then
    new_rc=$(awk -v begin="$MARK_BEGIN" -v end="$MARK_END" -v block="$BLOCK" '
        $0 == begin { print block; skip = 1; next }
        $0 == end   { skip = 0; next }
        !skip       { print }
    ' "$BASHRC")
fi

# --- 4. commit: all checks passed, now write both files -------------------
mv "$tmp" "$INSTALL_DIR/dircomp.bash"
trap - EXIT

if [[ $state == present ]]; then
    # Write THROUGH the existing path, not over it: `mv` would clobber the
    # file's mode (mktemp is 0600) and replace a dotfiles symlink with a
    # regular file, orphaning the real target.
    printf '%s\n' "$new_rc" > "$BASHRC"
    echo "dircomp $DIRCOMP_RELEASE: updated existing install in $BASHRC"
else
    { echo; echo "$BLOCK"; } >> "$BASHRC"
    echo "dircomp $DIRCOMP_RELEASE: installed. Restart your shell, or: source $BASHRC"
fi
