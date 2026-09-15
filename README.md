# dircomp

Directory-scoped bash completions. A project drops a plain-text spec at
`.completions/<command>`; typing that command and pressing TAB inside the
project (or any subdirectory of it) completes from that spec.

Spec files are read as literal text. They are never sourced, and never passed
through `compgen -W` or any other shell expansion, so a line like
`$(rm -rf ~)` in a checked-out `.completions/` file is offered as a
candidate string and nothing more. See *Scope and limits* below for what
happens outside the project.

No load step, no unload step, no environment variable, no direnv dependency.
The completion machinery resolves the spec fresh from `$PWD` on every TAB.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.1.2/install.sh | bash
```

Pin to a release tag, not `main` — a curl|bash install has no verification
step beyond you reading the script first, and a tag can't move under you
mid-pipe the way a branch can. Re-running install.sh (same tag or a newer
one) is safe: it replaces the previously-installed block rather than
duplicating it.

Installs to `~/.local/share/dircomp/dircomp.bash` and adds one guarded block
to `~/.bashrc`, between `# >>> dircomp >>>` / `# <<< dircomp <<<` markers.
Nothing else on the machine is touched.

## Update

Re-run the install command with a newer tag.

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.1.2/uninstall.sh | bash
```

Removes the bashrc block and `~/.local/share/dircomp`. Projects' own
`.completions/` files are untouched — they're just inert text without this
installed.

## Use

In any project:

```
mkdir -p .completions
$EDITOR .completions/mycommand
```

See [SPEC.md](SPEC.md) for the file format.

## Scope and limits

dircomp hooks bash's *default* completion, the one consulted only for
commands that have no completion of their own registered yet. Two
consequences follow, and both are current behaviour, not plans:

- **A command that already has a completion registered in your shell cannot
  be overridden by a project spec.** `git`, `ssh`, and anything your fzf or
  other integration wraps at startup fall in this group. A
  `.completions/git` file is silently ignored.
- **A project spec for a command whose native completion has not loaded yet
  displaces that native completion for the rest of the shell session.**
  Enter a project with `.completions/7z`, press TAB on `7z`, and `7z` will
  complete from the spec inside the project and from plain filenames
  outside it, instead of from bash-completion's own `7z` rules, until you
  open a new shell.

In practice dircomp fits commands that are *specific to the project*, such
as a script under the project's own `bin/`. Using it to add per-project
targets to a global tool is not yet supported.

## Requirements

The system `bash-completion` package (2.x), already loaded by most distro
default `.bashrc`s. The library checks for this at source time and refuses
to load with a clear error instead of silently doing nothing.

## Local development

```sh
git clone https://github.com/tebello-thejane/dircomp
cd dircomp
DIRCOMP_LOCAL_SOURCE=1 ./install.sh     # installs from the local checkout, no curl
```

## Versioning

`lib/dircomp.bash` carries two version numbers: `DIRCOMP_VERSION`, the
library release, and `DIRCOMP_SPEC_VERSION`, the `.completions` file
grammar. The spec version only moves on a breaking grammar change.
