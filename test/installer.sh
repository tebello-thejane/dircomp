#!/usr/bin/env bash
# Installer regression tests. Each case runs install.sh against a throwaway
# HOME and asserts on what it left behind.
#
#   test/installer.sh
#
# No case writes outside its own temp HOME, and none removes a directory tree.
set -uo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(dirname -- "$script_dir")

pass=0
fail=0
report() {
    if [[ $1 == ok ]]; then
        pass=$((pass + 1)); printf 'PASS %s\n' "$2"
    else
        fail=$((fail + 1)); printf 'FAIL %s\n     %s\n' "$2" "$3"
    fi
}

# --- 1. a refusal must not create or even touch ~/.bashrc ------------------
# Malformed markers: a begin with no end. The installer must refuse, and the
# file's mtime must be what we set, proving nothing wrote to it.
home=$(mktemp -d)
printf '# user config\n%s\n' "# >>> dircomp >>>" > "$home/.bashrc"
touch -t 200101010000 "$home/.bashrc"
before=$(stat -c %Y "$home/.bashrc")
out=$(HOME="$home" DIRCOMP_LOCAL_SOURCE=1 "$repo_root/install.sh" 2>&1)
rc=$?
after=$(stat -c %Y "$home/.bashrc")
if (( rc != 0 )) && [[ $before == "$after" ]]; then
    report ok "1 malformed block refused without touching ~/.bashrc"
else
    report fail "1 malformed block refused without touching ~/.bashrc" \
        "rc=$rc before=$before after=$after out=$out"
fi

# --- 2. a refusal must not create ~/.bashrc at all -------------------------
home=$(mktemp -d)
out=$(HOME="$home" DIRCOMP_REPO_RAW="https://127.0.0.1:1/nope" "$repo_root/install.sh" 2>&1)
rc=$?
leftovers=""
[[ -e $home/.bashrc ]] && leftovers+=" .bashrc"
[[ -e $home/.local/share/dircomp ]] && leftovers+=" .local/share/dircomp"
[[ -e $home/.local/share ]] && leftovers+=" .local/share"
[[ -e $home/.local ]] && leftovers+=" .local"
if (( rc != 0 )) && [[ -z $leftovers ]]; then
    report ok "2 failed download leaves no ~/.bashrc and no install dir"
else
    report fail "2 failed download leaves no ~/.bashrc and no install dir" \
        "rc=$rc leftovers:${leftovers:- none} out=$out"
fi

# --- 3. a failed download must not disturb an existing install -------------
home=$(mktemp -d)
mkdir -p "$home/.local/share/dircomp"
printf 'PREEXISTING\n' > "$home/.local/share/dircomp/dircomp.bash"
printf '# user config\n' > "$home/.bashrc"
out=$(HOME="$home" DIRCOMP_REPO_RAW="https://127.0.0.1:1/nope" "$repo_root/install.sh" 2>&1)
rc=$?
body=$(cat "$home/.local/share/dircomp/dircomp.bash")
strays=$(find "$home/.local/share/dircomp" -name '.dircomp.bash.*' | wc -l)
if (( rc != 0 )) && [[ $body == PREEXISTING ]] && (( strays == 0 )); then
    report ok "3 failed download leaves an existing install and no temp file"
else
    report fail "3 failed download leaves an existing install and no temp file" \
        "rc=$rc body=$body strays=$strays out=$out"
fi

# --- 4. clean install into a HOME with no ~/.bashrc ------------------------
home=$(mktemp -d)
out=$(HOME="$home" DIRCOMP_LOCAL_SOURCE=1 "$repo_root/install.sh" 2>&1)
rc=$?
first=$(head -1 "$home/.bashrc" 2>/dev/null)
blocks=$(grep -cxF -- "# >>> dircomp >>>" "$home/.bashrc" 2>/dev/null)
if (( rc == 0 )) && [[ $first == "# >>> dircomp >>>" ]] && (( blocks == 1 )); then
    report ok "4 clean install creates ~/.bashrc with no leading blank line"
else
    report fail "4 clean install creates ~/.bashrc with no leading blank line" \
        "rc=$rc first='$first' blocks=$blocks out=$out"
fi

# --- 5. re-running is idempotent and preserves mode and symlink ------------
home=$(mktemp -d)
mkdir -p "$home/dotfiles"
printf '# real file\n' > "$home/dotfiles/bashrc"
chmod 0640 "$home/dotfiles/bashrc"
ln -s "$home/dotfiles/bashrc" "$home/.bashrc"
HOME="$home" DIRCOMP_LOCAL_SOURCE=1 "$repo_root/install.sh" >/dev/null 2>&1
HOME="$home" DIRCOMP_LOCAL_SOURCE=1 "$repo_root/install.sh" >/dev/null 2>&1
rc=$?
blocks=$(grep -cxF -- "# >>> dircomp >>>" "$home/dotfiles/bashrc" 2>/dev/null)
mode=$(stat -c %a "$home/dotfiles/bashrc")
islink=no; [[ -L $home/.bashrc ]] && islink=yes
if (( rc == 0 )) && (( blocks == 1 )) && [[ $mode == 640 ]] && [[ $islink == yes ]]; then
    report ok "5 re-install is idempotent, keeps 0640 and the symlink"
else
    report fail "5 re-install is idempotent, keeps 0640 and the symlink" \
        "rc=$rc blocks=$blocks mode=$mode symlink=$islink"
fi

printf '%d passed, %d failed\n' "$pass" "$fail"
(( fail == 0 ))
