# dircomp completion spec — format v2

A spec file lives at `<project>/.completions/<command>` and is plain text,
never executed. On every TAB press the reader resolves the command word to
its file on disk and walks up from that file's directory until it finds
`.completions/<name>`, where `<name>` is the resolved file's basename. The
spec therefore follows the script, not your shell's location: `bin/tally`,
`./compl/bin/tally` from the parent directory, `~/compl/bin/tally` from
anywhere, a symlink to it, or bare `tally` when `bin/` is on PATH all read
`compl/.completions/tally`. There is no load or unload step.

## Grammar

```
# comment                     — ignored, as are blank lines
word                          — a candidate for the first word (before any subcommand)

[subcommand]
--flag                        — a candidate when completing subcommand's flags

[subcommand --flag]
value                         — a candidate for that flag's value

@file                         — in any section: filenames in the current directory
@dir                          — directories only
@user                         — login names
@host                         — hostnames (from HOSTFILE or /etc/hosts)
```

Leading and trailing whitespace is stripped from every line before it is
read, headers included, so a spec may be indented for readability. Inside a
header, runs of whitespace collapse to one space, so `[list  --sort]` and
`[list --sort]` name the same section. A candidate cannot therefore begin or
end with a space.

A literal line is offered when it starts with what has been typed so far.
It is compared as a string and nothing else: `$(rm -rf ~)` or `*` in a spec
is a candidate spelt exactly that way, not a command or a glob.

When no candidate in the relevant section matches, completion falls back to
bash's own, which is normally filenames. A command does not lose ordinary
completion by gaining a spec: a redirect target, or a flag value the spec
says nothing about, still completes as it would for any other command.

An `@kind` line selects one fixed bash builtin (`compgen -f`, `-d`, `-u`,
`-A hostname`) run against the word being typed. The spec can choose the
kind but cannot pass it anything, so no spec text reaches the shell there
either. Kinds and literals may be mixed in one section. An `@` line naming a
kind this reader does not know is skipped, so a file written for a newer
reader offers fewer candidates rather than a stray literal. A literal
candidate beginning with `@` cannot be expressed in v2.

## Example

```
add
list
clear
--help

[add]
--count
--from

[add --from]
@file

[list]
--json
--sort

[list --sort]
label
count

[clear]
--yes
--owner

[clear --owner]
@user
```

`tally <TAB>` offers `add list clear --help`. `tally list --sort <TAB>`
offers `label count`. `tally add --from <TAB>` offers files in the current
directory. `tally clear --owner <TAB>` offers login names.

## Changes from v1

- Spec lookup starts from the command's file, not from the current
  directory. Under v1, `./compl/bin/tally <TAB>` from the parent directory
  completed filenames because no `.completions/` existed above `$PWD`.
- `@file`, `@dir`, `@user`, `@host` kinds added. Under v1 these were four
  literal candidates; that is the incompatibility that moves the version.
- A project spec never overrides a completion bash-completion knows for the
  same command name. That was the documented intent under v1 and now holds
  on bash-completion 2.12+ as well as 2.11.

## Known limits (v2)

- No positional-argument awareness: a spec can't say "the first argument to
  `add` is a free-text label, don't offer flags there." It only distinguishes
  the first word, a subcommand's flags, and one flag's values.
- No dynamic candidates beyond the four kinds. No `@lines <path>`, no
  `$(...)`, by design.
- `@file` and `@dir` do not expand `~` or unquote the word being typed;
  they see it as bash's `compgen` does. Sections containing them are
  completed with readline's filename rules for the whole section, so a
  literal candidate that happens to match a directory name gets a trailing
  slash.
- Nesting is one level: `[subcommand --flag]`, not `[subcommand subsubcommand]`.
- `--flag=value` is not recognised; only `--flag value`.
- A spec file that cannot be read is skipped silently and the walk continues
  upward. There is no warning, because a completion handler has nowhere to
  put one without corrupting the line being edited.

Report a v3 need against the version in `lib/dircomp.bash`
(`DIRCOMP_SPEC_VERSION`) rather than hand-extending the grammar informally —
that field exists so a future reader can tell which grammar a file assumes.
