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
# Spec format (see SPEC.md): lines before the first [section] are the root
# node's subcommand names and flags. [path] lists a node's names and flags,
# [path --flag] and [path -f] a flag's values, [path #N] and [path #*] the
# candidates for a positional; [*] is merged into every node. A line @file,
# @dir, @user or @host names a kind of candidate resolved by a fixed bash
# builtin instead of a literal word; @endopts in a [path] ends that node's
# flags at its first positional. '#' comments and blank lines are ignored.
#
# This file is installed verbatim by install.sh to
# ~/.local/share/dircomp/dircomp.bash and sourced from ~/.bashrc via one
# guarded line — see that file for the install/update/uninstall story.

DIRCOMP_VERSION="0.2.2"
DIRCOMP_SPEC_VERSION="3"   # bump only if the file grammar changes incompatibly

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

_DIRCOMP_US=$'\x1f'   # joins a section key to one of its lines in _DC_LINES

_dircomp_parse() {
    # Read the spec at $1 into variables the caller (_dircomp) declared local,
    # so they die with the TAB:
    #   _DC_LINES  "<key><US><line>" for every candidate line
    #   _DC_DECL   newline-delimited keys of every valid header, empty or not
    #   _DC_NODES  newline-delimited node paths: every prefix of every path
    #   _DC_ENDS   newline-delimited node paths whose section holds @endopts
    # A key is "n <path>" (a node), "f <path> <flag>" (a flag's values) or
    # "s <path> #N" / "s <path> #*" (a positional slot). <path> is the node's
    # names joined by single spaces: "" for the root, "*" for the global
    # section. A name never starts with "-", is never "*" and is never a
    # slot, so no two headers can build the same key.
    #
    # Everything downstream looks these strings up by quoted pattern match,
    # never by associative-array subscript: a typed word such as @ or a]
    # is a subscript hazard in bash, a pattern match on a quoted string is not.
    #
    # Every line is trimmed before it is classified, so indenting a spec for
    # readability cannot change its meaning. Without this, a comment or blank
    # line tolerated leading whitespace while a section header did not: an
    # indented header was emitted as a literal candidate and its own section
    # became unreachable, with nothing to say so. Inside a header, runs of
    # whitespace collapse to one space (read -a splits on them), so
    # [list  --sort] and [list --sort] are the same key.
    local IFS=$' \t\n' line tok last acc kind key path valid n fd
    local cur_key="n " cur_kind=n cur_path=""
    local -a toks ptoks
    _DC_LINES=()
    _DC_DECL=$'\n' _DC_NODES=$'\n' _DC_ENDS=$'\n'
    { exec {fd}<"$1"; } 2>/dev/null || return 1
    while IFS= read -r -u "$fd" line || [[ -n $line ]]; do
        line=${line#"${line%%[![:space:]]*}"}
        line=${line%"${line##*[![:space:]]}"}
        [[ -z $line || $line == "#"* ]] && continue
        if [[ $line == "["*"]" ]]; then
            read -ra toks <<<"${line:1:${#line}-2}"
            n=${#toks[@]} kind=n last=""
            ptoks=("${toks[@]}")
            if (( n > 0 )); then
                last=${toks[n - 1]}
                if [[ $last =~ ^#([0-9]+|\*)$ ]]; then
                    kind=s
                elif [[ $last == --?* || ( $last == -? && $last != -- ) ]]; then
                    kind=f
                fi
                [[ $kind == n ]] || ptoks=("${toks[@]:0:n-1}")
            fi
            # An invalid header (a name that starts with "-", a stray slot,
            # "*" anywhere but alone, a global slot) matches nothing and its
            # lines are dropped.
            valid=1
            for tok in "${ptoks[@]}"; do
                if [[ $tok == -* || $tok =~ ^#([0-9]+|\*)$ ]]; then
                    valid=0
                elif [[ $tok == "*" ]] && { [[ $kind == s ]] || (( ${#ptoks[@]} != 1 )); }; then
                    valid=0
                fi
            done
            if (( valid )); then
                path="${ptoks[*]}"
                if [[ $kind == n ]]; then key="n $path"; else key="$kind $path $last"; fi
                cur_key=$key cur_kind=$kind cur_path=$path
                _DC_DECL+="$key"$'\n'
                acc=""
                for tok in "${ptoks[@]}"; do
                    acc=${acc:+$acc }$tok
                    [[ ${ptoks[0]} == "*" ]] || _DC_NODES+="$acc"$'\n'
                done
            else
                cur_key=""
            fi
            continue
        fi
        [[ -n $cur_key ]] || continue
        # @endopts is a directive, not a candidate: read in a [path] node
        # only, and ignored (it is an unknown @kind, so skipped) elsewhere.
        if [[ $line == "@endopts" && $cur_kind == n && $cur_path != "*" ]]; then
            _DC_ENDS+="$cur_path"$'\n'
            continue
        fi
        _DC_LINES+=("$cur_key$_DIRCOMP_US$line")
    done
    exec {fd}<&-
}

_dircomp_has() {
    # Was a header with key $1 declared? Presence decides, not content: an
    # empty [add --count] still says "--count takes a value".
    [[ $_DC_DECL == *$'\n'"$1"$'\n'* ]]
}

_dircomp_takes_value() {
    # Does flag $2 take a value at node $1? Node-specific or global.
    _dircomp_has "f $1 $2" || _dircomp_has "f * $2"
}

_dircomp_words() {
    # Fill _DC_W with COMP_WORDS[0..COMP_CWORD], rejoined across = and :.
    # bash splits the line at every COMP_WORDBREAKS character, so --from=fo
    # arrives as [--from][=][fo], ubuntu:2 as [ubuntu][:][2], and the cursor
    # right after --from= is the word "=". Two raw words are one typed word
    # when nothing separates them in COMP_LINE and one of them is made only
    # of = and :. Other break characters, such as > | ; and (, are real
    # boundaries: `list >out` must stay two words. This is bash-completion's
    # _get_comp_words_by_ref -n =: done by hand, because that name was
    # replaced in bash-completion 2.12 and survives only as a deprecation
    # wrapper that a shadowing startup file can remove. If COMP_LINE does not
    # line up with COMP_WORDS (unusual quoting), use the raw words.
    local line=$COMP_LINE w stripped ws i last=0 lastraw="" ok=1
    _DC_W=()
    for (( i = 0; i <= COMP_CWORD; i++ )); do
        w=${COMP_WORDS[i]}
        stripped=${line#"${line%%[![:space:]]*}"}
        ws=$(( ${#line} - ${#stripped} ))
        if [[ ${stripped:0:${#w}} != "$w" ]]; then ok=0; break; fi
        line=${stripped:${#w}}
        if (( i > 0 && ws == 0 )) && [[ $w =~ ^[=:]+$ || $lastraw =~ ^[=:]+$ ]]; then
            _DC_W[last]+=$w
        else
            _DC_W+=("$w")
            last=$(( ${#_DC_W[@]} - 1 ))
        fi
        lastraw=$w
    done
    (( ok )) || _DC_W=("${COMP_WORDS[@]:0:COMP_CWORD + 1}")
}

_dircomp_offer() {
    # Append section $1's candidates that match $typed to COMPREPLY. With $2
    # = 1, offer only literal lines starting with "-": a node that already
    # has a positional offers its flags, not its subcommand names or kinds.
    #
    # Literal prefix match, never `compgen -W`. Bash performs command
    # substitution, parameter and arithmetic expansion on a -W word list, so
    # feeding it spec-file text would let a committed .completions file run
    # arbitrary commands on TAB. Quoting $typed and the array append also
    # stops a literal `*` candidate being glob-expanded against the directory.
    #
    # An @kind line selects one fixed, argument-free builtin; the spec cannot
    # parameterise it, so no spec text reaches compgen here either. $typed is
    # what the user typed, not file content. Unknown kinds (and @endopts
    # outside a node) are skipped so a file written for a newer reader
    # degrades to fewer candidates, not to a stray literal.
    local e line
    for e in "${_DC_LINES[@]}"; do
        [[ $e == "$1$_DIRCOMP_US"* ]] || continue
        line=${e#*"$_DIRCOMP_US"}
        [[ $2 == 1 && $line != -* ]] && continue
        case $line in
            @file) compopt -o filenames; mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -f -- "$typed") ;;
            @dir)  compopt -o filenames; mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -d -- "$typed") ;;
            @user) mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -u -- "$typed") ;;
            @host) mapfile -t -O "${#COMPREPLY[@]}" COMPREPLY < <(compgen -A hostname -- "$typed") ;;
            @*)    ;;
            *)     [[ $line == "$typed"* ]] && COMPREPLY+=("$line") ;;
        esac
    done
}

_dircomp() {
    local spec _DC_DECL _DC_NODES _DC_ENDS
    local -a _DC_LINES _DC_W
    spec=$(_dircomp_find "${COMP_WORDS[0]}") || { "$_DIRCOMP_MINIMAL" "$@"; return; }
    _dircomp_parse "$spec" || { "$_DIRCOMP_MINIMAL" "$@"; return; }
    _dircomp_words

    # Walk the words before the cursor, tracking the node path P, the count
    # k of positionals seen at P, and a flag still waiting for its value.
    local last cur
    last=$(( ${#_DC_W[@]} - 1 ))
    cur=${_DC_W[last]}
    local P="" k=0 pending="" i j w rest flag nxt ended=0
    for (( i = 1; i < last; i++ )); do
        w=${_DC_W[i]}
        # A pending flag takes the next word whatever it looks like.
        if [[ -n $pending ]]; then pending=""; continue; fi
        # @endopts: from the node's first positional on, even -x is a positional.
        if (( k >= 1 )) && [[ $_DC_ENDS == *$'\n'"$P"$'\n'* ]]; then (( k++ )); continue; fi
        case $w in
            --?*)
                # --flag=value carries its value; nothing more is consumed
                # whether or not a section declares the flag.
                [[ $w == *=* ]] && continue
                _dircomp_takes_value "$P" "$w" && pending=$w ;;
            -?*)
                # A single-dash word is a cluster of one-character flags. The
                # first one that takes a value ends the scan: the rest of the
                # word is its value, or the next word is if it came last.
                rest=${w:1}
                for (( j = 0; j < ${#rest}; j++ )); do
                    flag=-${rest:j:1}
                    if _dircomp_takes_value "$P" "$flag"; then
                        (( j == ${#rest} - 1 )) && pending=$flag
                        break
                    fi
                done ;;
            *)
                # Descent only before the node's first positional.
                nxt=${P:+$P }$w
                if (( k == 0 )) && [[ $_DC_NODES == *$'\n'"$nxt"$'\n'* ]]; then
                    P=$nxt
                else
                    (( k++ ))
                fi ;;
        esac
    done
    (( k >= 1 )) && [[ $_DC_ENDS == *$'\n'"$P"$'\n'* ]] && ended=1

    # Classify the word under the cursor: a flag's value, a positional slot,
    # or a node's own names and flags.
    local ctx=node key="" typed=$cur
    if [[ -n $pending ]]; then
        ctx=value
        key="f $P $pending"; _dircomp_has "$key" || key="f * $pending"
    elif (( ! ended )) && [[ $cur == --?*=* ]]; then
        ctx=value
        flag=${cur%%=*} typed=${cur#*=}
        key="f $P $flag"; _dircomp_has "$key" || key="f * $flag"
    elif (( ended )) || [[ $cur != -* ]]; then
        key="s $P #$(( k + 1 ))"
        if ! _dircomp_has "$key"; then
            key="s $P #*"
            _dircomp_has "$key" || key=""
        fi
        if [[ -n $key ]]; then ctx=slot; elif (( ended )); then ctx=none; fi
    fi

    COMPREPLY=()
    case $ctx in
        value|slot) _dircomp_offer "$key" 0 ;;
        node)       _dircomp_offer "n $P" $(( k >= 1 )); _dircomp_offer "n *" $(( k >= 1 )) ;;
    esac

    # readline replaces only what follows the last word-break character, so
    # a candidate that spans an = or : the user already typed must lose that
    # prefix, as bash-completion's __ltrim_colon_completions does for colons.
    local brk="" pre
    [[ $COMP_WORDBREAKS == *=* ]] && brk+="="
    [[ $COMP_WORDBREAKS == *:* ]] && brk+=":"
    if [[ -n $brk ]]; then
        pre=${typed%"${typed##*[$brk]}"}
        if [[ -n $pre ]]; then
            for i in "${!COMPREPLY[@]}"; do
                [[ ${COMPREPLY[i]} == "$pre"* ]] && COMPREPLY[i]=${COMPREPLY[i]#"$pre"}
            done
        fi
    fi
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
