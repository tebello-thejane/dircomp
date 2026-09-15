# dircomp

Directory-scoped bash completions. A project drops a plain-text spec at
`.completions/<command>`; typing a command that lives in that project and
pressing TAB completes from the spec, from whatever directory you happen to
be in.

Spec files are read as literal text. They are never sourced, and never passed
through `compgen -W` or any other shell expansion, so a line like
`$(rm -rf ~)` in a checked-out `.completions/` file is offered as a
candidate string and nothing more. Four `@kind` lines (`@file`, `@dir`,
`@user`, `@host`) select fixed builtins the spec cannot parameterise.

No load step, no unload step, no environment variable, no direnv dependency.
On every TAB the machinery resolves the command word to its file (a typed
path, a symlink, or a bare name through PATH), then walks up from that
file's directory to find `.completions/<name>`. The spec travels with the
script.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.2.0/install.sh | bash
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
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v0.2.0/uninstall.sh | bash
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

See [SPEC.md](SPEC.md) for the file format. Then, from anywhere:

```
$ ~/proj/bin/mycommand <TAB>
$ cd ~/proj && bin/mycommand <TAB>
$ mycommand <TAB>          # if ~/proj/bin is on PATH, e.g. via direnv
```

## Scope and limits

dircomp hooks bash's *default* completion, the one consulted only for
commands that have no completion registered yet. When it fires, it first
lets bash-completion look for a native completion for the command. If one
exists, that is registered and used; the project spec is not consulted.
Only a command bash-completion has nothing for is completed from its spec.

So a project spec **cannot override or extend** completion for `git`,
`ssh`, `7z`, anything your fzf or other integration wraps at startup, or
anything bash-completion ships a completion file for. A `.completions/git`
file is silently ignored. This is a deliberate contract, not a gap: dircomp
is for commands that are *specific to the project*, such as a script under
the project's own `bin/`.

Shell functions and aliases have no file on disk and so never match a spec.

## Requirements

- The system `bash-completion` package, 2.11 or later. Most distro default
  `.bashrc`s load it. The library checks for it at source time and refuses
  to load with a clear error instead of silently doing nothing.
- `realpath` from coreutils (or GNU `readlink -f`), used to resolve the
  command word to its file.

## Local development

```sh
git clone https://github.com/tebello-thejane/dircomp
cd dircomp
DIRCOMP_LOCAL_SOURCE=1 ./install.sh     # installs from the local checkout, no curl
./test/tab.py                           # drives a real bash through a pty and presses TAB
./test/docker.sh                        # same, on debian:bookworm-slim (2.11) and debian:trixie-slim (2.16)
```

## Versioning

`lib/dircomp.bash` carries two version numbers: `DIRCOMP_VERSION`, the
library release, and `DIRCOMP_SPEC_VERSION`, the `.completions` file
grammar. The spec version only moves on a breaking grammar change.
