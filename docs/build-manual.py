#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build docs/MANUAL.md from docs/MANUAL.md.in.

Usage: ./docs/build-manual.py

Markers in the template:
  {{file:PATH}}    the file, verbatim (PATH relative to the repository root)
  {{stage:N}}      tutorial step N: step 1 is the whole stage file, later
                   steps are the diff from the previous stage file
  {{lines:PATH}}   "N lines (M of spec, K comments)" for a spec file

The examples are the source of truth. test/tab.py fails if MANUAL.md does not
quote every examples/*/.completions/* file verbatim, so rebuild after editing
a spec.
"""
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = sorted((ROOT / "examples" / "notes" / "stages").glob("*.spec"))


def stage(n: int) -> str:
    cur = STAGES[n - 1].read_text().splitlines()
    if n == 1:
        return "```text\n" + "\n".join(cur) + "\n```"
    prev = STAGES[n - 2].read_text().splitlines()
    out = []
    for line in difflib.unified_diff(prev, cur, lineterm="", n=1):
        if line.startswith(("---", "+++")):
            continue
        out.append(" ..." if line.startswith("@@") else line)
    return "```diff\n" + "\n".join(out) + "\n```"


def lines(path: str) -> str:
    rows = (ROOT / path).read_text().splitlines()
    com = sum(1 for r in rows if r.strip().startswith("#"))
    blank = sum(1 for r in rows if not r.strip())
    return f"{len(rows)} lines ({len(rows) - com - blank} of spec, {com} of comments)"


text = (ROOT / "docs" / "MANUAL.md.in").read_text()
text = re.sub(r"\{\{file:(.*?)\}\}", lambda m: (ROOT / m.group(1)).read_text().rstrip("\n"), text)
text = re.sub(r"\{\{stage:(\d+)\}\}", lambda m: stage(int(m.group(1))), text)
text = re.sub(r"\{\{lines:(.*?)\}\}", lambda m: lines(m.group(1)), text)
header = "<!-- Generated from docs/MANUAL.md.in by docs/build-manual.py. Edit the .in file. -->\n\n"
(ROOT / "docs" / "MANUAL.md").write_text(header + text)
print("wrote docs/MANUAL.md,", len((header + text).splitlines()), "lines")
