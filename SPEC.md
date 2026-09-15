# dircomp completion spec — format v1

A spec file lives at `<project>/.completions/<command>` and is plain text,
never executed. It is read fresh on every TAB press by walking up from the
current directory, so it applies inside the project (and its subdirectories)
only, with no load/unload step and nothing to go stale.

## Grammar

```
# comment                     — ignored, as are blank lines
word                          — a candidate for the first word (before any subcommand)

[subcommand]
--flag                        — a candidate when completing subcommand's flags

[subcommand --flag]
value                         — a candidate for that flag's value
```

## Example

```
add
list
clear
--help

[add]
--count

[list]
--json
--sort

[list --sort]
label
count

[clear]
--yes
```

`tally <TAB>` offers `add list clear --help`. `tally list --sort <TAB>`
offers `label count`.

## Known limits (v1)

- No positional-argument awareness: a spec can't say "the first argument to
  `add` is a free-text label, don't offer flags there." It only distinguishes
  the first word, a subcommand's flags, and one flag's values.
- No dynamic candidates (reading a file list, hitting an API). Static text
  only, by design. The reader matches each line as a literal prefix and
  never hands spec text to `compgen -W`, `eval`, `source`, or any other
  expansion, so a committed spec cannot run commands on TAB.
- Nesting is one level: `[subcommand --flag]`, not `[subcommand subsubcommand]`.

Report a v2 need against the version in `lib/dircomp.bash`
(`DIRCOMP_SPEC_VERSION`) rather than hand-extending v1's grammar informally —
that field exists so a future reader can tell which grammar a file assumes.
