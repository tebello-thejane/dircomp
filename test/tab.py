#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Real-TAB test harness for lib/dircomp.bash.

Drives an actual interactive bash under a pty, types a partial command line,
presses a real TAB, and reads back what readline printed or inserted. Nothing
is stubbed: bash-completion, the dircomp default handler, compgen and readline
all run for real.

Run it as ./test/tab.py (never `python3 test/tab.py` — the shebang is a uv
inline-script header). Nothing outside the temporary fixture directory is
written, so the repository may be mounted read-only.
"""

from __future__ import annotations

import argparse
import errno
import os
import pty
import pwd
import re
import select
import shlex
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time
import fcntl
from pathlib import Path

DEFAULT_BASH_COMPLETION = "/usr/share/bash-completion/bash_completion"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LIB = SCRIPT_DIR.parent / "lib" / "dircomp.bash"
EXAMPLES = SCRIPT_DIR.parent / "examples"

PROMPT = "$ "

ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


# --------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------

SPEC_TALLY = """\
add
list
clear
--help

[add]
--count
--from
--into

[add --from]
@file

[add --into]
@dir

[list]
--json
--sort
--host

[list --sort]
label
count

[list --host]
@host

[clear]
--yes
--owner
$(touch {pwned})
*
@bogus

[clear --owner]
@user
"""

# Leading whitespace is tolerated on every line, section headers included.
# An author who indents a spec for readability must not silently get a
# different grammar: before 0.2.2 an indented header was offered as a literal
# candidate and its section was unreachable. The trailing space after @dir is
# deliberate.
SPEC_INDENT = """\
alpha
beta

  [beta]
    --deep
  @dir
"""

# v3 fixtures. SPEC_NEST is the nesting / slot / global-section example from
# SPEC.md; SPEC_DOCK is the docker-shaped one (clusters, @endopts, #*). Empty
# headers such as [add --count] are deliberate: they declare "takes a value".
SPEC_NEST = """\
add
list
remote
--help

[*]
--verbose
--config

[* --config]
@file

[add]
--count
--from

[add --count]

[add --from]
@file

[add #1]

[list]
--json
--sort

[list --sort]
label
count

[remote]
add
rm
--prune

[remote add]
--track

[remote add --track]
@host

[remote add #1]

[remote add #2]
@host

[remote rm #1]
origin
upstream
"""

SPEC_DOCK = """\
run
rm
ps
--help

[*]
--context
--debug
--host
-D
-H

[* --context]
[* --host]
[* -H]

[run]
@endopts
--name
--restart
--rm
-d
-i
-p
-t

[run --name]
[run --restart]
no
always
on-failure
unless-stopped
[run -p]
[run #1]
[run #*]

[rm]
-f

[rm #*]
"""

# A root slot, then a variadic one: `var` offers `first`, then `rest` for
# every further positional.
SPEC_VAR = """\
[#1]
first

[#*]
rest
"""

# Candidates containing a colon: readline replaces only what follows the last
# one the user typed, so the reader must trim the typed prefix.
SPEC_IMG = """\
[#1]
ubuntu:22.04
ubuntu:24.04
alpine:3.20
"""

NATIVE_FOO = """\
_foo() { COMPREPLY=(native1); }
complete -F _foo foo
"""


def build_fixture(root: Path) -> None:
    """Create the tree the cases complete against. Only writes under root."""
    home = root / "home"
    compl = home / "compl"
    (compl / "bin").mkdir(parents=True)
    (compl / ".completions").mkdir()
    (home / "bin").mkdir()
    work = home / "work"
    work.mkdir()
    (root / "bc" / "completions").mkdir(parents=True)

    tally = compl / "bin" / "tally"
    tally.write_text("#!/bin/sh\necho yeah\n")
    tally.chmod(0o755)

    (compl / ".completions" / "tally").write_text(
        SPEC_TALLY.format(pwned=root / "PWNED")
    )

    os.symlink("../compl/bin/tally", home / "bin" / "t")

    foo = compl / "bin" / "foo"
    foo.write_text("#!/bin/sh\n")
    foo.chmod(0o755)
    (compl / ".completions" / "foo").write_text("spec1\n")

    (root / "bc" / "completions" / "foo").write_text(NATIVE_FOO)

    indent = compl / "bin" / "indent"
    indent.write_text("#!/bin/sh\n")
    indent.chmod(0o755)
    (compl / ".completions" / "indent").write_text(SPEC_INDENT)

    for name, spec in (
        ("nest", SPEC_NEST),
        ("dock", SPEC_DOCK),
        ("var", SPEC_VAR),
        ("img", SPEC_IMG),
    ):
        script = compl / "bin" / name
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        (compl / ".completions" / name).write_text(spec)

    noread = compl / "bin" / "noread"
    noread.write_text("#!/bin/sh\n")
    noread.chmod(0o755)
    unreadable = compl / ".completions" / "noread"
    unreadable.write_text("neverseen\n")
    unreadable.chmod(0o000)

    build_docs_fixture(root)

    (root / "hosts").write_text("alpha.example\nbeta.example\n")

    (work / "alpha.txt").write_text("a\n")
    (work / "beta.txt").write_text("b\n")
    (work / "sub").mkdir()


def build_docs_fixture(root: Path) -> None:
    """The manual's tools under home/examples, and one project per tutorial
    stage under home/tut/NN. The stage projects hold a stub `notes`: only the
    spec next to it is under test."""
    home = root / "home"
    for tool in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        shutil.copytree(tool, home / "examples" / tool.name,
                        ignore=shutil.ignore_patterns("stages"))
    manual = (SCRIPT_DIR.parent / "docs" / "MANUAL.md").read_text()
    for spec in sorted(EXAMPLES.glob("*/.completions/*")):
        if spec.read_text().rstrip("\n") not in manual:
            raise SystemExit(f"docs/MANUAL.md does not quote {spec} verbatim")
    stages = sorted((EXAMPLES / "notes" / "stages").glob("*.spec"))
    shipped = EXAMPLES / "notes" / ".completions" / "notes"
    if stages[-1].read_text() != shipped.read_text():
        raise SystemExit(f"{stages[-1]} differs from {shipped}")
    for spec in stages:
        proj = home / "tut" / spec.name[:2]
        (proj / "bin").mkdir(parents=True)
        (proj / ".completions").mkdir()
        stub = proj / "bin" / "notes"
        stub.write_text("#!/bin/sh\n")
        stub.chmod(0o755)
        shutil.copy(spec, proj / ".completions" / "notes")


# --------------------------------------------------------------------------
# pty-driven bash
# --------------------------------------------------------------------------


class ShellTimeout(RuntimeError):
    pass


class Shell:
    """An interactive bash on the other end of a pty."""

    def __init__(self, env: dict, timeout: float, verbose: bool):
        self.timeout = timeout
        self.verbose = verbose
        self.marker_n = 0
        self.log: list[str] = []
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child
            try:
                os.execvpe("bash", ["bash", "--norc", "--noprofile", "-i"], env)
            except Exception:
                os._exit(127)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        self.wait_quiet(0.3, 2.0)

    # -- raw io ----------------------------------------------------------

    def send(self, data: str) -> None:
        os.write(self.fd, data.encode())

    def _read_some(self, timeout: float) -> str:
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return ""
        if not r:
            return ""
        try:
            chunk = os.read(self.fd, 65536)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                return ""
            raise
        return chunk.decode("utf-8", "replace")

    def wait_quiet(self, quiet: float = 0.25, total: float = 2.0) -> str:
        """Read until nothing arrives for `quiet` seconds (or `total` elapses)."""
        deadline = time.monotonic() + total
        buf = []
        while time.monotonic() < deadline:
            chunk = self._read_some(quiet)
            if not chunk:
                break
            buf.append(chunk)
        return "".join(buf)

    def read_until(self, needle: str, timeout: float | None = None) -> str:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        buf = ""
        while True:
            buf += self._read_some(max(0.05, deadline - time.monotonic()))
            if needle in buf:
                return buf
            if time.monotonic() > deadline:
                raise ShellTimeout(
                    f"timed out waiting for {needle!r}; got: {buf!r}"
                )

    # -- synchronisation -------------------------------------------------

    def run(self, command: str) -> str:
        """Send a command line, wait for it to finish, return its output."""
        self.send(command + "\r")
        return self.mark()

    def mark(self) -> str:
        """Echo a unique marker and read up to it.

        The marker is typed with an empty quoted pair inside it, so the
        terminal's echo of the typed line never matches the marker text we
        search for — only bash's own output of it does.
        """
        self.marker_n += 1
        token = f"__MARK_{self.marker_n}__"
        typed = f'echo "__MARK""_{self.marker_n}__"'
        self.send(typed + "\r")
        out = self.read_until(token)
        if self.verbose:
            self.log.append(f"  [run {typed!r}] -> {out!r}")
        return out

    # -- the TAB probe ---------------------------------------------------

    def probe(self, line: str, tab_wait: float) -> tuple[str, str]:
        """Type `line`, press TAB, return (raw listing region, line buffer).

        The line buffer is read back by jumping to the start of the line,
        typing `echo B""UFBEG'`, jumping to the end, typing `'E""NDBUF` and
        pressing Enter. bash then prints the buffer verbatim between the two
        markers. Single-quoting it means nothing in the buffer is expanded —
        a `$(...)` candidate that readline inserted is printed, not run — and
        executing the line disposes of it, so the next probe starts clean.
        """
        self.send(line)
        time.sleep(0.15)
        self.wait_quiet(0.15, 1.0)  # discard the echo of what we typed

        self.send("\t")
        time.sleep(tab_wait)
        listing = self.wait_quiet(0.25, 5.0)

        self.send("\x01" + 'echo B""UFBEG\'' + "\x05" + "'E\"\"NDBUF" + "\r")
        out = self.read_until("ENDBUF")
        out += self.wait_quiet(0.2, 2.0)
        cleaned = clean(out)
        m = re.search(r"BUFBEG(.*?)ENDBUF", cleaned, re.S)
        buffer_text = m.group(1) if m else ""
        self.mark()
        return listing, buffer_text

    def close(self) -> None:
        try:
            self.send("\x03")
            self.send("exit\r")
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


# --------------------------------------------------------------------------
# parsing what readline printed
# --------------------------------------------------------------------------


def clean(raw: str) -> str:
    text = ANSI_OSC.sub("", ANSI_CSI.sub("", raw))
    text = text.replace("\x07", "").replace("\x00", "")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_listing(raw: str) -> list[str]:
    """Candidates readline printed as a match list.

    `set completion-display-width 0` puts one match per line, which is the
    only unambiguous form: a match may itself contain a space (the literal
    `$(touch /tmp/.../PWNED)` candidate is printed unescaped) and column
    padding can be a single space, so column layout cannot be split reliably.
    Multi-column output is still handled — split on runs of two or more
    spaces — in case the readline in use ignores that variable. Lines that
    are the prompt being redrawn are dropped.
    """
    out = []
    for line in clean(raw).split("\n"):
        if not line.strip():
            continue
        if line.startswith(PROMPT):
            continue
        stripped = line.strip()
        pieces = re.split(r"\s{2,}|\t+", stripped) if re.search(r"\s{2,}|\t", stripped) else [stripped]
        out.extend(p for p in pieces if p)
    return out


def normalise(word: str) -> str:
    word = word.replace("\\", "")
    return word[:-1] if word.endswith("/") and len(word) > 1 else word


def candidates(listing_raw: str, buffer_text: str, typed: str) -> tuple[set[str], str]:
    """Return (normalised candidate set, mode) for one probe."""
    cleaned = clean(listing_raw)
    if "\n" in cleaned:
        # readline broke the line: it printed a match list, then redrew the
        # prompt. Anything that is not the redrawn prompt line is a candidate.
        words = parse_listing(listing_raw)
        if words:
            return {normalise(w) for w in words}, "listing"
    # nothing listed: readline inserted a unique completion inline (or nothing)
    buf = buffer_text
    if buf == typed:
        return set(), "none"
    if buf.endswith(" "):
        buf = buf[:-1]
    word = buf.rsplit(" ", 1)[-1]
    if not word:
        return set(), "none"
    return {normalise(word)}, "inline"


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------


def login_name() -> str:
    try:
        return os.getlogin()
    except OSError:
        return pwd.getpwuid(os.getuid()).pw_name


def build_cases(root: Path) -> list[dict]:
    home = root / "home"
    work = home / "work"
    compl = home / "compl"
    pwned = root / "PWNED"
    user = login_name()

    base = {"add", "list", "clear", "--help"}
    return [
        # 12 first: it must be the first probe of `foo` in the session.
        dict(
            name="12 native completion wins over .completions/foo",
            cwd=work,
            line="foo ",
            expect=({"native1"}, "=="),
        ),
        dict(name="1 ./bin/tally from project root", cwd=compl,
             line="./bin/tally ", expect=(base, "==")),
        dict(name="2 ./compl/bin/tally from parent", cwd=home,
             line="./compl/bin/tally ", expect=(base, "==")),
        dict(name="3 ~/compl/bin/tally from outside HOME", cwd=root,
             line="~/compl/bin/tally ", expect=(base, "==")),
        dict(name="4 ../bin/t symlink", cwd=work,
             line="../bin/t ", expect=(base, "==")),
        dict(name="pre-5 put compl/bin on PATH", pre=f"export PATH={shlex.quote(str(compl / 'bin'))}:$PATH"),
        dict(name="5 bare tally li -> unique completion", cwd=work,
             line="tally li", expect=({"list"}, "==")),
        dict(name="6 tally list --sort", cwd=work,
             line="tally list --sort ", expect=({"label", "count"}, "==")),
        dict(name="7 tally add --from (@file)", cwd=work,
             line="tally add --from ", expect=({"alpha.txt", "beta.txt", "sub"}, "==")),
        dict(name="8 tally add --into (@dir)", cwd=work,
             line="tally add --into ", expect=({"sub"}, "==")),
        dict(name="9 tally list --host (@host)", cwd=work,
             line="tally list --host ", expect=({"alpha.example", "beta.example"}, "==")),
        dict(name="10 tally clear --owner (@user)", cwd=work,
             line="tally clear --owner ", expect=({user}, "contains")),
        dict(name="11 tally clear literals, never executed or globbed", cwd=work,
             line="tally clear ",
             expect=({"--yes", "--owner", f"$(touch {pwned})", "*"}, "=="),
             not_in={"@bogus"}, must_not_exist=pwned),
        dict(name="15 redirect target still completes", cwd=work,
             line="tally list > alp", expect=({"alpha.txt"}, "==")),
        dict(name="16 no section match falls back to filenames", cwd=work,
             line="tally add --count al", expect=({"alpha.txt"}, "==")),
        dict(name="17 indented spec, top-level section", cwd=work,
             line="../compl/bin/indent ", expect=({"alpha", "beta"}, "==")),
        dict(name="18 indented spec, indented header and @kind", cwd=work,
             line="../compl/bin/indent beta ", expect=({"--deep", "sub"}, "==")),
        dict(name="19 unreadable spec falls back with no awk error", cwd=work,
             line="../compl/bin/noread ",
             expect=({"alpha.txt", "beta.txt", "sub"}, "=="),
             skip_if_root=True),
        dict(name="pre-13 restore PATH", pre="export PATH=$DIRCOMP_TEST_PATH"),
        dict(name="13 unknown command falls back to filenames", cwd=home,
             line="tally ", expect=({"bin", "compl", "examples", "tut", "work"}, "==")),
        dict(name="14 ./bin/tally again after a miss (not sticky)", cwd=compl,
             line="./bin/tally ", expect=(base, "==")),
    ] + build_v3_cases(work) + build_docs_cases(work)


def build_v3_cases(work: Path) -> list[dict]:
    """Format v3: depth, slots, `=`, `[*]`, clusters, @endopts, `#*`, `:`."""
    nest = "../compl/bin/nest "
    dock = "../compl/bin/dock "
    var = "../compl/bin/var "
    img = "../compl/bin/img "
    files = {"alpha.txt", "beta.txt", "sub"}
    g_dock = {"--context", "--debug", "--host", "-D", "-H"}
    return [
        dict(name="v3-1 nest root: names, root flags, [*]", cwd=work,
             line=nest,
             expect=({"add", "list", "remote", "--help", "--verbose", "--config"}, "==")),
        dict(name="v3-2 [* --config] global flag values", cwd=work,
             line=nest + "--config ", expect=(files, "==")),
        dict(name="v3-3 an empty header still consumes the value", cwd=work,
             # --count has a header, so 3 is its value and this is slot #1, which
             # is empty: filenames. Were 3 a positional, k=1 and flags would show.
             line=nest + "add --count 3 ", expect=(files, "==")),
        dict(name="v3-4 node flags plus [*] after `-`", cwd=work,
             line=nest + "add -",
             expect=({"--count", "--from", "--verbose", "--config"}, "==")),
        dict(name="v3-5 --flag= completes the value", cwd=work,
             line=nest + "list --sort=", expect=({"label", "count"}, "==")),
        dict(name="v3-6 --flag=la replaces only the value", cwd=work,
             line=nest + "list --sort=la", buffer=nest + "list --sort=label "),
        dict(name="v3-7 depth 2: remote", cwd=work,
             line=nest + "remote ",
             expect=({"add", "rm", "--prune", "--verbose", "--config"}, "==")),
        dict(name="v3-8 depth 2 flag values", cwd=work,
             line=nest + "remote add --track ",
             expect=({"alpha.example", "beta.example"}, "==")),
        dict(name="v3-9 positional counting: second slot", cwd=work,
             line=nest + "remote add origin ",
             expect=({"alpha.example", "beta.example"}, "==")),
        dict(name="v3-10 positional slot literals", cwd=work,
             line=nest + "remote rm ", expect=({"origin", "upstream"}, "==")),
        dict(name="v3-11 unknown word is a positional; flags only after it", cwd=work,
             line=nest + "frob ",
             expect=({"--help", "--verbose", "--config"}, "==")),
        dict(name="v3-12 dock root with globals", cwd=work,
             line=dock, expect=({"run", "rm", "ps", "--help"} | g_dock, "==")),
        dict(name="v3-13 global value flag takes a colon word", cwd=work,
             # Raw COMP_WORDS split tcp://h:2375 into five words; rejoined it
             # is -H's one value and the root is back to k=0.
             line=dock + "-H tcp://h:2375 ",
             expect=({"run", "rm", "ps", "--help"} | g_dock, "==")),
        dict(name="v3-14 run flags after `-`", cwd=work,
             line=dock + "run -",
             expect=({"--name", "--restart", "--rm", "-d", "-i", "-p", "-t"} | g_dock, "==")),
        dict(name="v3-15 cluster ending in a value flag takes the next word", cwd=work,
             # -itp leaves -p pending, 80:80 is its value, so k=0 and `-` still
             # offers flags. Were 80:80 a positional, @endopts would end flags.
             line=dock + "run -itp 80:80 -",
             expect=({"--name", "--restart", "--rm", "-d", "-i", "-p", "-t"} | g_dock, "==")),
        dict(name="v3-16 --restart= enumerates values", cwd=work,
             line=dock + "run --restart=",
             expect=({"no", "always", "on-failure", "unless-stopped"}, "==")),
        dict(name="v3-17 --restart=al replaces only the value", cwd=work,
             line=dock + "run --restart=al", buffer=dock + "run --restart=always "),
        dict(name="v3-18 @endopts: no flags after the image", cwd=work,
             line=dock + "run -it ubuntu --", expect=(set(), "==")),
        dict(name="v3-19 without @endopts flags still follow positionals", cwd=work,
             line=dock + "rm a b -", expect=({"-f"} | g_dock, "==")),
        dict(name="v3-20 root slot, then #* for every further positional", cwd=work,
             line=var, expect=({"first"}, "==")),
        dict(name="v3-21 #* after the numbered slot", cwd=work,
             line=var + "x ", expect=({"rest"}, "==")),
        dict(name="v3-22 #* keeps applying", cwd=work,
             line=var + "x y z ", expect=({"rest"}, "==")),
        dict(name="v3-23 colon candidates trimmed to what follows the typed colon", cwd=work,
             line=img + "ubuntu:2", expect=({"22.04", "24.04"}, "==")),
        dict(name="v3-24 colon candidate unique", cwd=work,
             line=img + "ubuntu:22", buffer=img + "ubuntu:22.04 "),
        dict(name="v3-25 no colon typed: whole candidates", cwd=work,
             line=img + "ub", buffer=img + "ubuntu:2"),
    ]


def build_docs_cases(work: Path) -> list[dict]:
    """The manual: tutorial stages of `notes`, then the four finished tools.

    Every table in docs/MANUAL.md is one of these cases, so the manual cannot
    drift from the reader.
    """
    files = {"alpha.txt", "beta.txt", "sub"}
    hosts = {"alpha.example", "beta.example"}
    user = login_name()
    names = {"add", "list", "show", "rm", "import", "export", "remote", "with"}
    g_notes = {"--dir", "-v"}

    def tut(stage: str, rest: str) -> str:
        return f"../tut/{stage}/bin/notes " + rest

    def c(name, line, expect=None, how="==", buffer=None):
        d = dict(name=name, cwd=work, line=line)
        if buffer is not None:
            d["buffer"] = buffer
        else:
            d["expect"] = (expect, how)
        return d

    out = [
        # -- tutorial ------------------------------------------------------
        c("t01 names", tut("01", ""), names),
        c("t01 unique name completes", tut("01", "li"), buffer=tut("01", "list ")),
        c("t01 no section yet: filenames", tut("01", "list "), files),
        c("t02 names and root flag", tut("02", ""), names | {"--help"}),
        c("t03 node flags", tut("03", "list "), {"--tag", "--sort", "--json"}),
        c("t03 undeclared value flag: flags again", tut("03", "list --tag "),
          {"--tag", "--sort", "--json"}),
        c("t04 values", tut("04", "list --sort "), {"date", "title"}),
        c("t04 declared but empty: filenames", tut("04", "list --tag "), files),
        c("t04 enumerated", tut("04", "add --priority "), {"low", "normal", "high"}),
        c("t05 @file", tut("05", "export --to "), files),
        c("t05 = form", tut("05", "export --format="), {"md", "txt", "json"}),
        c("t05 = form replaces the value only", tut("05", "export --format=m"),
          buffer=tut("05", "export --format=md ")),
        c("t06 nested names", tut("06", "remote "), {"add", "rm", "list"}),
        c("t06 no header yet: filenames", tut("06", "remote add "), files),
        c("t07 slot 1 is free text", tut("07", "remote add "), files),
        c("t07 slot 2 is @host", tut("07", "remote add web "), hosts),
        c("t07 no slot 3: nothing to offer, bash's filenames", tut("07", "remote add web alpha.example "), files),
        c("t07 #* repeats", tut("07", "import alpha.txt "), files),
        c("t08 globals at the root", tut("08", ""), names | {"--help"} | g_notes),
        c("t08 globals at a node", tut("08", "list "), {"--tag", "--sort", "--json"} | g_notes),
        c("t08 global value kind", tut("08", "--dir "), {"sub"}),
        c("t09 short flag joins the node", tut("09", "add -"), {"--priority", "-t"} | g_notes),
        c("t09 short flag values", tut("09", "add -t "), {"idea", "todo", "bug"}),
        c("t09 cluster ending in a value flag", tut("09", "add -vt "), {"idea", "todo", "bug"}),
        c("t09 a slot hides flags until a dash is typed", tut("09", "add "), files),
        c("t09 attached value, then back to the node", tut("09", "add -tidea -"),
          {"--priority", "-t"} | g_notes),
        c("t09 after a positional: dash lines only", tut("09", "rm 1 -"), {"-f"} | g_notes),
        c("t10 slot before flags", tut("10", "with "), files),
        c("t10 flags before the id", tut("10", "with -"), {"-q"} | g_notes),
        c("t10 second slot", tut("10", "with 3 "), {"grep", "wc", "less"}),
        c("t10 flags ended: no flags offered", tut("10", "with 3 grep --"), set(), "=="),
        c("t10 #* after the command", tut("10", "with 3 grep -i "), files),
        c("t11 colon values, typed up to the colon", tut("11", "add -t team:"), {"alpha", "beta"}),
        c("t11 colon value unique", tut("11", "add -t team:a"), buffer=tut("11", "add -t team:alpha ")),
        c("t11 no colon typed: whole values", tut("11", "add -t t"), {"todo", "team:alpha", "team:beta"}),
        c("t11 colon after =", tut("11", "list --tag=team:"), {"alpha", "beta"}),
        c("t11 is the shipped spec", tut("11", "add -t b"), buffer=tut("11", "add -t bug ")),
    ]

    ship = "../examples/ship/bin/ship "
    g_ship = {"--config", "--profile", "-n"}
    out += [
        c("ship root", ship, {"env", "release", "host", "--help"} | g_ship),
        c("ship global value set", ship + "--profile ", {"dev", "staging", "prod"}),
        c("ship global value set at depth", ship + "release promote --profile=", {"dev", "staging", "prod"}),
        c("ship node override replaces the global set", ship + "release rollback --profile=", {"dev", "staging"}),
        c("ship enumerated", ship + "release create --channel ", {"stable", "beta", "nightly"}),
        c("ship flags still allowed after a positional", ship + "release create 1.0 ",
          {"--channel", "--notes"} | g_ship),
        c("ship slot 2 is @host", ship + "host add web ", hosts),
        c("ship @user", ship + "host add --user ", {user}, "contains"),
        c("ship port values", ship + "host add --port=", {"22", "2222"}),
        c("ship region values", ship + "env create dev --region ", {"eu-west-1", "eu-central-1", "af-south-1"}),
        c("ship free text slot", ship + "env show ", files),
        c("ship global @file", ship + "--config ", files),
    ]

    box = "../examples/box/bin/box "
    g_box = {"--host", "-H"}
    out += [
        c("box root", box, {"run", "ps", "rm", "images", "--help"} | g_box),
        c("box run flags", box + "run -",
          {"--name", "--restart", "--network", "--pull", "-d", "-i", "-t", "-p", "-e", "-v"} | g_box),
        c("box = value", box + "run --restart=", {"no", "always", "on-failure", "unless-stopped"}),
        c("box image slot after a cluster ending in -p", box + "run -itp 8080:80 ",
          {"alpine:3.20", "busybox:latest", "ubuntu:22.04", "ubuntu:24.04"}),
        c("box image with a colon typed", box + "run -itp 8080:80 ubuntu:", {"22.04", "24.04"}),
        c("box -v takes @dir", box + "run -it -v ", {"sub"}),
        c("box command slot", box + "run ubuntu:24.04 ", {"sh", "bash", "env"}),
        c("box flags end at the image", box + "run ubuntu:24.04 sh -", set(), "=="),
        c("box command args", box + "run ubuntu:24.04 sh ", files),
        c("box global value with a colon", box + "-H tcp://h:2375 run --pull ", {"always", "missing", "never"}),
        c("box ps --format", box + "ps --format=", {"table", "json"}),
        c("box rm is not @endopts", box + "rm a b -", {"-f", "-v"} | g_box),
    ]

    mig = "../examples/mig/bin/mig "
    g_mig = {"--env", "--dir", "-v", "-n"}
    out += [
        c("mig root", mig, {"new", "up", "migrate", "down", "apply", "status", "--help"} | g_mig),
        c("mig global values", mig + "--env=", {"dev", "staging", "prod"}),
        c("mig bare cluster changes nothing", mig + "-vn ",
          {"new", "up", "migrate", "down", "apply", "status", "--help"} | g_mig),
        c("mig value flag", mig + "up --steps ", {"1", "2", "5"}),
        c("mig alias written twice", mig + "migrate --steps ", {"1", "2", "5"}),
        c("mig declared but empty", mig + "up --to ", files),
        c("mig apply files", mig + "apply ", files),
        c("mig apply files, repeated", mig + "apply alpha.txt ", files),
        c("mig value consumed, back at the node", mig + "down -vn --steps 2 ",
          {"--steps", "--force"} | g_mig),
        c("mig new --kind", mig + "new --kind=", {"sql", "py"}),
    ]

    bk = "../examples/backup/bin/backup "
    g_bk = {"-v", "-n"}
    out += [
        c("backup root", bk, {"run", "restore", "verify", "hosts", "--help"} | g_bk),
        c("backup run slot 1 is @dir", bk + "run ", {"sub"}),
        c("backup run slot 2 is @host", bk + "run sub ", hosts),
        c("backup run no slot 3: dash lines", bk + "run sub alpha.example ",
          {"--exclude", "--compress", "--as"} | g_bk),
        c("backup run --compress=", bk + "run --compress=", {"none", "gzip", "zstd"}),
        c("backup run --as", bk + "run --as ", {user}, "contains"),
        c("backup restore slot 1 is @host", bk + "restore ", hosts),
        c("backup restore slot 2 is @dir", bk + "restore alpha.example ", {"sub"}),
        c("backup restore --at=", bk + "restore --at=", {"latest", "yesterday", "last-week"}),
        c("backup verify", bk + "verify ", hosts),
    ]
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def run_suite(root: Path, args) -> int:
    build_fixture(root)
    home = root / "home"

    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TERM": "dumb",
        "INPUTRC": "/dev/null",
        "BASH_COMPLETION_USER_DIR": str(root / "bc"),
        "HOSTFILE": str(root / "hosts"),
        "PS1": PROMPT,
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "DIRCOMP_TEST_PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }

    sh = Shell(env, args.timeout, args.verbose)
    passed = failed = 0
    try:
        for cmd in (
            "unset PROMPT_COMMAND",
            "bind 'set bell-style none'",
            "bind 'set show-all-if-ambiguous on'",
            "bind 'set page-completions off'",
            "bind 'set completion-query-items -1'",
            "bind 'set completion-display-width 0'",
            f"source {shlex.quote(args.bash_completion)}",
            f"source {shlex.quote(args.lib)}",
        ):
            sh.run(cmd)

        for case in build_cases(root):
            if "pre" in case:
                sh.run(case["pre"])
                continue
            if case.get("skip_if_root") and os.geteuid() == 0:
                # root reads a mode-000 file regardless, so the case cannot
                # assert anything here.
                print(f"SKIP {case['name']} (root bypasses file permissions)")
                continue
            sh.run(f"cd {shlex.quote(str(case['cwd']))}")
            listing, buf = sh.probe(case["line"], args.tab_wait)
            got, mode = candidates(listing, buf, case["line"])
            problems = []
            if "buffer" in case:
                # What readline left on the line: the replacement, not the
                # candidate set. Needed where the two differ (after `=`/`:`).
                if buf != case["buffer"]:
                    problems.append(f"expected line {case['buffer']!r} got {buf!r}")
            else:
                expect, how = case["expect"]
                expect_n = {normalise(w) for w in expect}
                if how == "==":
                    if got != expect_n:
                        problems.append(f"expected {sorted(expect_n)} got {sorted(got)}")
                else:
                    missing = expect_n - got
                    if missing:
                        problems.append(f"expected to contain {sorted(missing)}; got {sorted(got)}")
            for bad in case.get("not_in", ()):  # e.g. an unknown @kind leaking
                if bad in got:
                    problems.append(f"unexpected candidate {bad!r}")
            mne = case.get("must_not_exist")
            if mne is not None and Path(mne).exists():
                problems.append(f"{mne} was created — a spec line was executed")

            if args.verbose:
                print(f"    typed={case['line']!r} mode={mode}")
                print(f"    raw listing={listing!r}")
                print(f"    line buffer={buf!r}")
            if problems:
                failed += 1
                print(f"FAIL {case['name']}")
                for p in problems:
                    print(f"     {p}")
                if not args.verbose:
                    print(f"     raw listing: {listing!r}")
                    print(f"     line buffer: {buf!r}")
            else:
                passed += 1
                print(f"PASS {case['name']}")
    finally:
        sh.close()

    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="real-TAB tests for dircomp.bash")
    ap.add_argument("--lib", default=str(DEFAULT_LIB))
    ap.add_argument("--bash-completion", default=DEFAULT_BASH_COMPLETION)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--tab-wait", type=float, default=0.3)
    ap.add_argument("--verbose", action="store_true", help="dump raw bytes per case")
    ap.add_argument("--keep", action="store_true", help="keep the fixture and print its path")
    args = ap.parse_args()

    for path in (args.lib, args.bash_completion):
        if not Path(path).is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 2

    if args.keep:
        root = Path(tempfile.mkdtemp(prefix="dircomp-tab-"))
        print(f"fixture: {root}")
        return run_suite(root, args)
    with tempfile.TemporaryDirectory(prefix="dircomp-tab-") as tmp:
        return run_suite(Path(tmp), args)


if __name__ == "__main__":
    sys.exit(main())
