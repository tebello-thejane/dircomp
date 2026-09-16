#!/usr/bin/env bash
# dircomp — directory-scoped bash completions.
#
# https://github.com/tebello-thejane/dircomp
#
# Reads <project>/.completions/<command> — a plain-text word list, never
# executed — found by resolving the command to its file on disk and walking
# up from that file's directory. The spec therefore travels with the script:
# `./compl/bin/tally`, `~/compl/bin/tally`, a symlink to it, or bare `tally`
# via PATH all complete from compl/.completions/tally, from any cwd. No load
# or unload step: nothing to go stale when you cd away.
#
# Spec format (see SPEC.md): lines before the first [section] complete the
# first word. [subcommand] lists that subcommand's flags. [subcommand --flag]
# lists that flag's values. A line @file, @dir, @user or @host names a kind of
# candidate resolved by a fixed bash builtin instead of a literal word.
# '#' comments and blank lines are ignored.
#
# This file is installed verbatim by install.sh to
# ~/.local/share/dircomp/dircomp.bash and sourced from ~/.bashrc via one
# guarded line — see that file for the install/update/uninstall story.

DIRCOMP_VERSION="0.2.2"
DIRCOMP_SPEC_VERSION="2"   # bump only if the file grammar changes incompatibly

# bash-completion reworked its internals in 2.12. _comp_load is the loading
# primitive; _comp_complete_load is the `complete -D` callback that wraps
# `_comp_load -D` and returns 124. The 2.11 names _completion_loader and
# _minimal survive only as deprecation wrappers in the compat startup file
# (startup-core/000_bash_completion_compat.bash), which loads by default but
# can be shadowed by a file of the same name earlier in the startup search
# path. So detect whichever generation is actually present and refuse only
# when neither is: gating on the deprecated name alone would turn a perfectly
# good 2.12+ setup into a load error.
if declare -F _comp_complete_load >/dev/null; then
    _DIRCOMP_LOADER=_comp_complete_load
elif declare -F _completion_loader >/dev/null; then
    _DIRCOMP_LOADER=_completion_loader
else
    echo "dircomp: bash-completion not loaded — source it before this file" >&2
    return 1 2>/dev/null || exit 1
fi

# Read the "nothing found" stub's name from what bash-completion registered
# for the empty command rather than hard-coding either spelling, then fall
# back to the known names if that compspec is missing or names a function
# that does not exist.
_DIRCOMP_MINIMAL=$(complete -p '' 2>/dev/null)
_DIRCOMP_MINIMAL=${_DIRCOMP_MINIMAL#*-F }
_DIRCOMP_MINIMAL=${_DIRCOMP_MINIMAL%% *}
if [[ -z $_DIRCOMP_MINIMAL ]] || ! declare -F "$_DIRCOMP_MINIMAL" >/dev/null; then
    if declare -F _comp_complete_minimal >/dev/null; then
        _DIRCOMP_MINIMAL=_comp_complete_minimal
    elif declare -F _minimal >/dev/null; then
        _DIRCOMP_MINIMAL=_minimal
    else
        echo "dircomp: bash-completion's fallback completion not found" >&2
        return 1 2>/dev/null || exit 1
    fi
fi

_dircomp_resolve() {
    # Print the real path of the executable the command word names, or fail.
    # A word with a slash is a path as typed; a bare word goes through PATH.
    # Functions and aliases have no file and so resolve to nothing.
    local word=$1 path
    [[ $word == "~/"* ]] && word=$HOME/${word#"~/"}
    if [[ $word == */* ]]; then
        path=$word
    else
        path=$(type -P -- "$word") || return 1
    fi
    path=$(realpath -e -- "$path" 2>/dev/null || readlink -f -- "$path" 2>/dev/null) || return 1
    [[ -f $path ]] || return 1
    printf '%s\n' "$path"
}

_dircomp_find() {
    # Walk up from the executable's own directory looking for
    # .completions/<basename>. The basename is the resolved file's, so a
    # symlink ~/bin/t -> ~/compl/bin/tally still reads .completions/tally.
    local path d cmd
    path=$(_dircomp_resolve "$1") || return 1
    cmd=${path##*/}
    d=${path%/*}; d=${d:-/}
    while :; do
        # -r as well as -f: an unreadable spec must fall through to the
        # normal fallback, not make awk print a permission error into the
        # middle of the completion display on every TAB.
        [[ -f $d/.completions/$cmd && -r $d/.completions/$cmd ]] && { printf '%s\n' "$d/.completions/$cmd"; return 0; }
        [[ $d == / ]] && break
        d=${d%/*}; d=${d:-/}     # stripping /tmp yields ""; visit / last, not never
    done
    return 1
}

_dircomp_section() {
    # Every line is trimmed before it is classified, so indenting a spec for
    # readability cannot change its meaning. Without this, a comment or blank
    # line tolerated leading whitespace while a section header did not: an
    # indented header was emitted as a literal candidate and its own section
    # became unreachable, with nothing to say so. Inside a header, runs of
    # whitespace collapse to one space so that [list  --sort] still matches
    # the "<subcommand> <flag>" key the caller builds.
    awk -v want="$2" '
        {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            sub(/[[:space:]]+$/, "", line)
        }
        line ~ /^#/ || line == "" { next }
        line ~ /^\[.*\]$/ {
            cur = substr(line, 2, length(line) - 2)
            gsub(/[[:space:]]+/, " ", cur)
            sub(/^ /, "", cur)
            sub(/ $/, "", cur)
            next
        }
        cur == want { print line }
    ' "$1" 2>/dev/null
}

_dircomp() {
    local spec cur=${COMP_WORDS[COMP_CWORD]} sub prev section flagsec line
    spec=$(_dircomp_find "${COMP_WORDS[0]}") || { "$_DIRCOMP_MINIMAL" "$@"; return; }
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
    #
    # An @kind line selects one fixed, argument-free builtin; the spec cannot
    # parameterise it, so no spec text reaches compgen here either. $cur is
    # what the user typed, not file content. Unknown kinds are skipped so a
    # file written for a newer reader degrades to fewer candidates, not to a
    # stray literal.
    COMPREPLY=()
    while IFS= read -r line; do
        case $line in
            @file) compopt -o filenames; mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -f -- "$cur") ;;
            @dir)  compopt -o filenames; mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -d -- "$cur") ;;
            @user) mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -u -- "$cur") ;;
            @host) mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -A hostname -- "$cur") ;;
            @*)    ;;
            *)     [[ $line == "$cur"* ]] && COMPREPLY+=("$line") ;;
        esac
    done < <(_dircomp_section "$spec" "$section")
}

_dircomp_load() {
    # Default handler: runs only for a command with no completion registered
    # yet. bash-completion gets first go; if it found a native completion,
    # that is now registered and wins — a project spec never overrides it.
    # Only when it left its "nothing found" stub behind is the command handed
    # to _dircomp, which re-resolves the spec on every TAB and itself falls
    # back to the stub when there is none. Registering _dircomp even when no
    # spec exists right now is what stops a first miss from being sticky for
    # the rest of the session.
    local cmd=${1:-_EmptycmD_}
    "$_DIRCOMP_LOADER" "$cmd"
    # -o bashdefault -o default so that an empty COMPREPLY falls back to
    # bash's own completion instead of to nothing. The stub being replaced
    # here completes filenames, and a command must not lose that just because
    # it gained a spec: a redirect target, or a flag value the spec says
    # nothing about, still completes as it would anywhere else. Both options
    # apply only when the reply is empty, so a matching section is unaffected.
    [[ $(complete -p -- "$cmd" 2>/dev/null) == *"-F $_DIRCOMP_MINIMAL "* ]] &&
        complete -o bashdefault -o default -F _dircomp -- "$cmd"
    return 124
}

complete -D -F _dircomp_load
