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

    (root / "hosts").write_text("alpha.example\nbeta.example\n")

    (work / "alpha.txt").write_text("a\n")
    (work / "beta.txt").write_text("b\n")
    (work / "sub").mkdir()


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
        dict(name="pre-13 restore PATH", pre="export PATH=$DIRCOMP_TEST_PATH"),
        dict(name="13 unknown command falls back to filenames", cwd=home,
             line="tally ", expect=({"bin", "compl", "work"}, "==")),
        dict(name="14 ./bin/tally again after a miss (not sticky)", cwd=compl,
             line="./bin/tally ", expect=(base, "==")),
    ]


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
            sh.run(f"cd {shlex.quote(str(case['cwd']))}")
            listing, buf = sh.probe(case["line"], args.tab_wait)
            got, mode = candidates(listing, buf, case["line"])
            expect, how = case["expect"]
            expect_n = {normalise(w) for w in expect}

            problems = []
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
