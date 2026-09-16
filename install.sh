#!/usr/bin/env bash
# dircomp installer — idempotent: safe to re-run for updates.
#
#   curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.2.2/install.sh | bash
#
# Pin to a tag (vX.Y.Z), never to a branch — curl|bash has no verification
# step of its own, and a branch can change under you between the curl and the
# bash. This script fetches the library from the SAME ref it was published
# under (DIRCOMP_RELEASE below), so a pinned installer installs a pinned
# library. It only writes under ~/.local/share/dircomp and adds one guarded
# block to ~/.bashrc.
#
# Order matters: every check that can refuse runs BEFORE anything is created
# or written. A refusal leaves the filesystem as it found it — no ~/.bashrc
# where there was none, no empty ~/.local/share/dircomp, and an existing
# install untouched.
set -euo pipefail

# Bumped as part of the release process; must match the tag this file is
# published under, or a pinned install silently pulls an unpinned library.
DIRCOMP_RELEASE="v0.2.2"

REPO_RAW="${DIRCOMP_REPO_RAW:-https://raw.githubusercontent.com/tebello-thejane/dircomp/$DIRCOMP_RELEASE}"
INSTALL_DIR="$HOME/.local/share/dircomp"
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> dircomp >>>"
MARK_END="# <<< dircomp <<<"

die() { echo "dircomp: $*" >&2; exit 1; }

# --- 1. validate ~/.bashrc marker state (reads only, creates nothing) -------
# Markers must match as WHOLE LINES (-x), because the awk rewrite below
# compares $0 == marker. A substring match here with an exact match there
# would report success while installing nothing. Refuse on missing,
# duplicated, or inverted markers: rewriting a half-present block silently
# deletes everything after it.
#
# A ~/.bashrc that does not exist is treated as logically empty rather than
# created here. Creating it would be a write during the phase whose whole
# point is that it can still refuse.
if [[ -f $BASHRC ]]; then
    n_begin=$(grep -cxF -- "$MARK_BEGIN" "$BASHRC" || true)
    n_end=$(grep -cxF -- "$MARK_END" "$BASHRC" || true)
else
    n_begin=0
    n_end=0
fi

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
# The temp file is staged INSIDE the install directory so the commit below is
# a same-filesystem rename. That means the directory has to exist now, before
# the download can fail, so record which levels of it we create and take them
# back down on any failure. rmdir only removes an empty directory, so a
# directory that already held something is never touched.
missing_dirs=()
probe=$INSTALL_DIR
while [[ -n $probe && ! -d $probe ]]; do
    missing_dirs+=("$probe")
    probe=${probe%/*}
done

cleanup() {
    [[ -n ${tmp:-} ]] && rm -f "$tmp"
    local d
    for d in ${missing_dirs[@]+"${missing_dirs[@]}"}; do
        rmdir "$d" 2>/dev/null || break
    done
}
trap cleanup EXIT

mkdir -p "$INSTALL_DIR"
tmp=$(mktemp "$INSTALL_DIR/.dircomp.bash.XXXXXX")

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
tmp=""
missing_dirs=()
trap - EXIT

if [[ $state == present ]]; then
    # Write THROUGH the existing path, not over it: `mv` would clobber the
    # file's mode (mktemp is 0600) and replace a dotfiles symlink with a
    # regular file, orphaning the real target.
    printf '%s\n' "$new_rc" > "$BASHRC"
    echo "dircomp $DIRCOMP_RELEASE: updated existing install in $BASHRC"
else
    # Separate the block from whatever came before, but don't open a brand
    # new ~/.bashrc with a blank first line.
    if [[ -s $BASHRC ]]; then
        { echo; echo "$BLOCK"; } >> "$BASHRC"
    else
        echo "$BLOCK" >> "$BASHRC"
    fi
    echo "dircomp $DIRCOMP_RELEASE: installed. Restart your shell, or: source $BASHRC"
fi
