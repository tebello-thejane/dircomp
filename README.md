# dircomp

Directory-scoped bash completions. A project drops a plain-text spec at
`.completions/<command>`; typing that command and pressing TAB inside the
project (or any subdirectory of it) completes from that spec. Outside the
project, the command completes however it normally would — or not at all,
if it isn't a real command out there.

No load step, no unload step, no environment variable, no direnv dependency.
The completion machinery resolves the spec fresh from `$PWD` on every TAB.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v1.0.0/install.sh | bash
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
curl -fsSL https://raw.githubusercontent.com/tebello-thejane/dircomp/v1.0.0/uninstall.sh | bash
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
