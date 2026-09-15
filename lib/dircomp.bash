#!/usr/bin/env bash
# dircomp — directory-scoped bash completions.
#
# https://github.com/tebello-thejane/dircomp
#
# Reads <project>/.completions/<command> — a plain-text word list, never
# executed — resolved by walking up from $PWD on every TAB press. No load or
# unload step: nothing to go stale when you cd away.
#
# Spec format (see SPEC.md): lines before the first [section] complete the
# first word. [subcommand] lists that subcommand's flags. [subcommand --flag]
# lists that flag's values. '#' comments and blank lines are ignored.
#
# This file is installed verbatim by install.sh to
# ~/.local/share/dircomp/dircomp.bash and sourced from ~/.bashrc via one
# guarded line — see that file for the install/update/uninstall story.

DIRCOMP_VERSION="0.1.1"
DIRCOMP_SPEC_VERSION="1"   # bump only if the [section] grammar changes incompatibly

_dircomp_find() {
    local d=$PWD
    while [[ -n $d ]]; do
        [[ -f $d/.completions/$1 ]] && { printf '%s\n' "$d/.completions/$1"; return 0; }
        [[ $d == / ]] && break
        d=${d%/*}
    done
    return 1
}

_dircomp_section() {
    awk -v want="$2" '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
        /^\[.*\]$/ { cur = substr($0, 2, length($0) - 2); next }
        cur == want { print }
    ' "$1"
}

_dircomp() {
    local spec cur=${COMP_WORDS[COMP_CWORD]} sub prev section flagsec candidate
    spec=$(_dircomp_find "${COMP_WORDS[0]}") || { _minimal "$@"; return; }
    if (( COMP_CWORD == 1 )); then
        section=""
    else
        sub=${COMP_WORDS[1]}
        prev=${COMP_WORDS[COMP_CWORD - 1]}
        section=$sub
        if [[ $prev == -* ]]; then
            flagsec=$(_dircomp_section "$spec" "$sub $prev")
            [[ -n $flagsec ]] && section="$sub $prev"
        fi
    fi
    # Literal prefix match, never `compgen -W`. Bash performs command
    # substitution, parameter and arithmetic expansion on a -W word list, so
    # feeding it spec-file text would let a committed .completions file run
    # arbitrary commands on TAB. Quoting $cur and the array append also stops
    # a literal `*` candidate being glob-expanded against the directory.
    COMPREPLY=()
    while IFS= read -r candidate; do
        [[ $candidate == "$cur"* ]] && COMPREPLY+=("$candidate")
    done < <(_dircomp_section "$spec" "$section")
}

_dircomp_load() {
    local cmd=${1:-_EmptycmD_}
    _dircomp_find "$cmd" >/dev/null && { complete -F _dircomp "$cmd"; return 124; }
    _completion_loader "$cmd"
    [[ $(complete -p "$cmd" 2>/dev/null) == *"-F _minimal"* ]] && complete -F _dircomp "$cmd"
    return 124
}

# Requires bash-completion's _minimal/_completion_loader — bail out loudly
# rather than silently no-op if it isn't loaded yet.
if ! declare -F _completion_loader >/dev/null; then
    echo "dircomp: bash-completion not loaded — source it before this file" >&2
    return 1 2>/dev/null || exit 1
fi

complete -D -F _dircomp_load
