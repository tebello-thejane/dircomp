#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build docs/spec-diagrams.html and three standalone SVGs for dircomp SPEC.md.

Usage: ./docs/build-diagrams.py [out-dir]    (default: the directory of this script)

Tokens come from the diagram-design style guide (Trafman skin). Every
coordinate is authored on the 4px grid; connectors are rounded right-angle
paths drawn before the nodes.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE

PAPER = "#f4f4f4"
INK = "#2d2d3b"
MUTED = "#616161"
SOFT = "#878787"
ACCENT = "#da6a07"
ACCENT_TINT = "rgba(218,106,7,0.08)"
RULE = "rgba(45,45,59,0.12)"
SANS = "'Roboto', system-ui, sans-serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,500;0,700;1,400"
    "&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------


def text(x, y, s, size=12, weight=400, fill=INK, family=SANS, anchor="middle", spacing=None):
    sp = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
        f'font-family="{family}" text-anchor="{anchor}"{sp}>{esc(s)}</text>'
    )


def box(x, y, w, h, kind, name, subs=(), mono_name=True):
    """Node box: opaque paper mask, styled rect, name, sublabels."""
    fill, stroke, sw, dash = {
        "step": ("#ffffff", INK, 1, None),
        "leaf": ("#ffffff", INK, 0.8, None),
        "focal": (ACCENT_TINT, ACCENT, 1, None),
        "optional": ("rgba(45,45,59,0.02)", "rgba(45,45,59,0.20)", 1, "4,3"),
    }[kind]
    d = f' stroke-dasharray="{dash}"' if dash else ""
    cy = y + h / 2
    n = len(subs)
    name_y = cy - n * 6 + 4
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw}"{d}/>',
        text(x + w / 2, name_y, name, 12, 500, INK, MONO if mono_name else SANS),
    ]
    for i, s in enumerate(subs):
        out.append(text(x + w / 2, name_y + 16 + i * 12, s, 9, 400, MUTED, MONO))
    return "\n".join(out)


def oval(x, y, w, h, name):
    return "\n".join(
        [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h // 2}" fill="{PAPER}"/>',
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h // 2}" fill="#ffffff" '
            f'stroke="{INK}" stroke-width="1"/>',
            text(x + w / 2, y + h / 2 + 4, name, 12, 500, INK, SANS),
        ]
    )


def diamond(cx, cy, w, h, lines, focal=False):
    hw, hh = w // 2, h // 2
    pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
    fill, stroke = (ACCENT_TINT, ACCENT) if focal else ("#ffffff", INK)
    out = [
        f'<polygon points="{pts}" fill="{PAPER}"/>',
        f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>',
    ]
    n = len(lines)
    for i, s in enumerate(lines):
        out.append(text(cx, cy + 4 - (n - 1) * 8 + i * 16, s, 12, 600, INK, SANS))
    return "\n".join(out)


def path(d, marker=None, color=MUTED, dashed=False):
    m = f' marker-end="url(#{marker})"' if marker else ""
    da = ' stroke-dasharray="5,4"' if dashed else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1"{da}{m}/>'


def label_h(cx, stroke_y, s):
    """Label above a horizontal segment: mask bottom sits 8px above the stroke."""
    w = max(28, (round(len(s) * 5.4 + 12) + 3) // 4 * 4)
    return (
        f'<rect x="{cx - w // 2}" y="{stroke_y - 20}" width="{w}" height="12" rx="2" fill="{PAPER}"/>\n'
        + text(cx, stroke_y - 11, s, 8, 400, SOFT, MONO, spacing="0.06em")
    )


def label_v(stroke_x, cy, s):
    """Label beside a vertical segment: mask left edge sits 8px right of the stroke."""
    w = max(28, (round(len(s) * 5.4 + 12) + 3) // 4 * 4)
    return (
        f'<rect x="{stroke_x + 8}" y="{cy - 6}" width="{w}" height="12" rx="2" fill="{PAPER}"/>\n'
        + text(stroke_x + 8 + w // 2, cy + 3, s, 8, 400, SOFT, MONO, spacing="0.06em")
    )


def legend(y, width, items):
    """Horizontal bottom strip: hairline, LEGEND eyebrow, swatch + text items."""
    out = [
        f'<line x1="32" y1="{y - 8}" x2="{width - 32}" y2="{y - 8}" stroke="{RULE}" stroke-width="0.8"/>',
        text(32, y + 12, "LEGEND", 8, 500, MUTED, MONO, "start", "0.14em"),
    ]
    x = 120
    for kind, label, adv in items:
        sy = y + 4
        if kind == "decision":
            out.append(
                f'<polygon points="{x + 8},{sy} {x + 16},{sy + 8} {x + 8},{sy + 16} {x},{sy + 8}" '
                f'fill="#ffffff" stroke="{INK}" stroke-width="1"/>'
            )
        elif kind == "focal-decision":
            out.append(
                f'<polygon points="{x + 8},{sy} {x + 16},{sy + 8} {x + 8},{sy + 16} {x},{sy + 8}" '
                f'fill="{ACCENT_TINT}" stroke="{ACCENT}" stroke-width="1"/>'
            )
        elif kind == "step":
            out.append(f'<rect x="{x}" y="{sy + 2}" width="16" height="12" rx="3" fill="#ffffff" stroke="{INK}" stroke-width="1"/>')
        elif kind == "focal":
            out.append(f'<rect x="{x}" y="{sy + 2}" width="16" height="12" rx="3" fill="{ACCENT_TINT}" stroke="{ACCENT}" stroke-width="1"/>')
        elif kind == "optional":
            out.append(f'<rect x="{x}" y="{sy + 2}" width="16" height="12" rx="3" fill="rgba(45,45,59,0.02)" stroke="rgba(45,45,59,0.20)" stroke-width="1" stroke-dasharray="4,3"/>')
        elif kind == "leaf":
            out.append(f'<rect x="{x}" y="{sy + 2}" width="16" height="12" rx="3" fill="#ffffff" stroke="{INK}" stroke-width="0.8"/>')
        out.append(text(x + 24, sy + 12, label, 9, 400, MUTED, SANS, "start"))
        x += adv
    return "\n".join(out)


def svg(slug, title, desc, width, height, body, markers=False):
    m = ""
    if markers:
        m = (
            f'<marker id="{slug}-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            f'<polygon points="0 0, 8 3, 0 6" fill="{MUTED}"/></marker>\n'
            f'<marker id="{slug}-arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            f'<polygon points="0 0, 8 3, 0 6" fill="{ACCENT}"/></marker>'
        )
    defs = f"<defs>\n{m}\n</defs>\n" if m else ""
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-labelledby="{slug}-title {slug}-desc">\n'
        f'<title id="{slug}-title">{esc(title)}</title>\n'
        f'<desc id="{slug}-desc">{esc(desc)}</desc>\n'
        f"{defs}"
        f'<rect width="100%" height="100%" fill="{PAPER}"/>\n'
        f"{body}\n</svg>"
    )


# --------------------------------------------------------------------------
# figure 1: the node tree
# --------------------------------------------------------------------------


def fig_tree():
    W, H = 1000, 396
    cx_root, cx_glob, cx_run, cx_rm = 460, 120, 460, 860
    run_kids = (280, 460, 640)
    y0, y1, y2 = 40, 140, 240  # node tops, h=52
    h = 52
    wires = [
        # root -> [*], [run], [rm]
        path(f"M{cx_root} {y0 + h} V{y1}"),
        path(f"M{cx_root} 120 H{cx_glob + 8} A8 8 0 0 0 {cx_glob} 128 V{y1}"),
        path(f"M{cx_root} 120 H{cx_rm - 8} A8 8 0 0 1 {cx_rm} 128 V{y1}"),
        # [run] -> its three leaves
        path(f"M{cx_run} {y1 + h} V{y2}"),
        path(f"M{cx_run} 216 H{run_kids[0] + 8} A8 8 0 0 0 {run_kids[0]} 224 V{y2}"),
        path(f"M{cx_run} 216 H{run_kids[2] - 8} A8 8 0 0 1 {run_kids[2]} 224 V{y2}"),
        # [rm] -> its leaf
        path(f"M{cx_rm} {y1 + h} V{y2}"),
    ]
    nodes = [
        box(cx_root - 90, y0, 180, h, "step", "root", ["run rm ps --help"]),
        box(cx_glob - 80, y1, 160, h, "optional", "[*]", ["merged into every node"]),
        box(cx_run - 80, y1, 160, h, "focal", "[run]", ["@endopts  --name -p -t"]),
        box(cx_rm - 80, y1, 160, h, "step", "[rm]", ["-f"]),
        box(run_kids[0] - 80, y2, 160, h, "leaf", "[run --restart]", ["no always on-failure"]),
        box(run_kids[1] - 80, y2, 160, h, "leaf", "[run #1]", ["image: free text"]),
        box(run_kids[2] - 80, y2, 160, h, "leaf", "[run #*]", ["command, args"]),
        box(cx_rm - 80, y2, 160, h, "leaf", "[rm #*]", ["containers"]),
    ]
    leg = legend(
        332,
        W,
        [
            ("focal", "directive: flags end at the first positional", 304),
            ("optional", "merged into every node", 200),
            ("leaf", "leaf: flag values or a positional slot", 280),
        ],
    )
    body = "\n".join(wires + nodes + [leg])
    return svg(
        "spec-tree",
        "dircomp spec v3: the node tree",
        "Tree of a docker-shaped command spec: a root node, a global section merged into every node, and run and rm nodes with flag-value and positional-slot leaves.",
        W,
        H,
        body,
    )


# --------------------------------------------------------------------------
# figure 2: walking the words before the cursor
# --------------------------------------------------------------------------


def fig_walk():
    W, H = 1000, 744
    DW, DH = 240, 88
    cx = 500
    d1, d2, d3, d4 = 80, 224, 368, 520
    body = []
    # connectors first
    body += [
        path(f"M{cx} {d1 + 44} V{d2 - 44}", "spec-walk-arrow"),
        path(f"M{cx} {d2 + 44} V{d3 - 44}", "spec-walk-arrow"),
        path(f"M{cx} {d3 + 44} V{d4 - 44}", "spec-walk-arrow"),
        path(f"M{cx} {d4 + 44} V622", "spec-walk-arrow"),
        path(f"M{cx + 120} {d1} H700", "spec-walk-arrow"),
        path(f"M{cx - 120} {d3} H320", "spec-walk-arrow"),
        path(f"M{cx + 120} {d3} H700", "spec-walk-arrow"),
        path(f"M{cx + 120} {d4} H700", "spec-walk-arrow"),
        path(
            f"M{cx + 120} {d2} H940 A8 8 0 0 1 948 {d2 + 8} V638 A8 8 0 0 1 940 646 H600",
            "spec-walk-arrow-accent",
            ACCENT,
        ),
    ]
    # labels
    body += [
        label_h(660, d1, "YES"),
        label_v(cx, 152, "NO"),
        label_h(680, d2, "YES"),
        label_v(cx, 296, "NO"),
        label_h(350, d3, "LONG"),
        label_h(660, d3, "SHORT"),
        label_v(cx, 444, "BARE"),
        label_h(660, d4, "YES"),
        label_v(cx, 592, "NO"),
    ]
    # nodes
    body += [
        diamond(cx, d1, DW, DH, ["flag pending?"]),
        diamond(cx, d2, DW, DH, ["endopts and", "k ≥ 1?"], focal=True),
        diamond(cx, d3, DW, DH, ["word starts with?"]),
        diamond(cx, d4, DW, DH, ["k = 0 and", "node exists?"]),
        box(700, 56, 200, 48, "step", "word is its value", ["pending clears"], mono_name=False),
        box(120, 328, 200, 80, "step", "long flag  --x", ["--x=v : value attached", "declared flag : pending", "undeclared : bare flag"]),
        box(700, 328, 200, 80, "step", "short flag, cluster", ["scan chars left to right", "declared char takes value:", "attached, or next word"], mono_name=False),
        box(700, 496, 200, 48, "step", "descend", ["path += word, k = 0"], mono_name=False),
        box(400, 622, 200, 48, "step", "positional", ["k = k + 1"], mono_name=False),
    ]
    body.append(
        legend(
            700,
            W,
            [
                ("decision", "decision", 120),
                ("step", "step", 100),
                ("focal-decision", "the @endopts check", 200),
            ],
        )
    )
    return svg(
        "spec-walk",
        "dircomp spec v3: walking one typed word",
        "Flowchart of how the reader consumes each word before the cursor: pending flag, endopts, long or short flag, descent into a node, or positional.",
        W,
        H,
        "\n".join(body),
        markers=True,
    )


# --------------------------------------------------------------------------
# figure 3: classifying the word under the cursor
# --------------------------------------------------------------------------


def fig_classify():
    W, H = 1000, 616
    DW, DH = 280, 96
    cx = 400
    d1, d2 = 200, 360
    body = [
        path(f"M{cx} 88 V{d1 - 48}", "spec-classify-arrow"),
        path(f"M{cx} {d1 + 48} V{d2 - 48}", "spec-classify-arrow"),
        path(f"M{cx} {d2 + 48} V472", "spec-classify-arrow"),
        path(f"M{cx + 140} {d1} H640", "spec-classify-arrow"),
        path(f"M{cx + 140} {d2} H640", "spec-classify-arrow-accent", ACCENT),
        label_h(590, d1, "YES"),
        label_h(590, d2, "YES"),
        label_v(cx, 280, "NO"),
        label_v(cx, 440, "NO"),
        oval(300, 48, 200, 40, "word at cursor"),
        diamond(cx, d1, DW, DH, ["flag pending,", "or --flag=… ?"]),
        diamond(cx, d2, DW, DH, ["flags ended, or no dash", "and a slot exists?"], focal=True),
        box(640, 168, 260, 64, "step", "value", ["candidates: [P flag]", "else [* flag]"], mono_name=False),
        box(640, 328, 260, 64, "step", "positional slot", ["[P #k+1], else [P #*]", "none if flags ended, no slot"], mono_name=False),
        box(270, 472, 260, 64, "step", "node", ["[P] plus [*]", "dash lines only if k ≥ 1"], mono_name=False),
        legend(
            576,
            W,
            [
                ("decision", "decision", 120),
                ("step", "outcome", 120),
                ("focal-decision", "the slot test", 160),
            ],
        ),
    ]
    return svg(
        "spec-classify",
        "dircomp spec v3: classifying the cursor word",
        "Flowchart of how the word under the cursor is classified as a flag value, a positional slot, or a node's own names and flags.",
        W,
        H,
        "\n".join(body),
        markers=True,
    )


# --------------------------------------------------------------------------
# figure 4: what happens on one TAB (docs/MANUAL.md, "How it works")
# --------------------------------------------------------------------------


def fig_howitworks():
    W, H = 1000, 384
    body = [
        path("M160 72 V128", "spec-howitworks-arrow"),
        path("M280 170 H380", "spec-howitworks-arrow"),
        path("M620 170 H720", "spec-howitworks-arrow"),
        path("M840 212 V268", "spec-howitworks-arrow-accent", ACCENT),
        oval(40, 32, 240, 40, "notes remote add web <TAB>"),
        box(40, 128, 240, 84, "step", "1  Find the spec",
            ["notes is a file on disk;", "read .completions/notes", "next to it, or above"], mono_name=False),
        box(380, 128, 240, 84, "step", "2  Walk the typed words",
            ["remote : node [remote]", "add    : node [remote add]", "web    : positional 1"], mono_name=False),
        box(720, 128, 240, 84, "step", "3  Look at the cursor",
            ["a non-flag word, and", "a slot exists for it:", "positional 2"], mono_name=False),
        box(720, 268, 240, 52, "focal", "[remote add #2]", ["offers @host: hostnames"]),
        legend(344, W, [("focal", "the section TAB reads", 220), ("step", "step", 100)]),
    ]
    return svg(
        "spec-howitworks",
        "dircomp: what happens on one TAB",
        "Three steps on pressing TAB after notes remote add web: find the spec file, walk the typed words through the nodes, then pick the section for the word under the cursor.",
        W, H, "\n".join(body), markers=True,
    )


# --------------------------------------------------------------------------
# figure 5: counting positionals (docs/MANUAL.md, tutorial step 7)
# --------------------------------------------------------------------------


def fig_slots():
    W, H = 1000, 316
    xs = [130, 370, 610, 850]
    words = ["remote", "add", "web", "<TAB>"]
    classes = [
        ("descend", ["P = [remote]", "k = 0"], "step"),
        ("descend", ["P = [remote add]", "k = 0"], "step"),
        ("positional 1", ["P = [remote add]", "k = 1"], "step"),
        ("cursor: slot #2", ["[remote add #2]", "k + 1 = 2"], "focal"),
    ]
    body = []
    for i in range(3):
        body.append(path(f"M{xs[i] + 100} 76 H{xs[i + 1] - 100}", "spec-slots-arrow"))
    for x in xs:
        body.append(path(f"M{x} 104 V176", "spec-slots-arrow"))
    for x, w in zip(xs, words):
        body.append(box(x - 100, 48, 200, 56, "step", w, ["typed word" if w != "<TAB>" else "word at cursor"]))
    for x, (name, subs, kind) in zip(xs, classes):
        body.append(box(x - 100, 176, 200, 76, kind, name, subs, mono_name=False))
    body.append(legend(276, W, [("focal", "the section TAB reads", 220), ("step", "step", 100)]))
    return svg(
        "spec-slots",
        "dircomp: counting positional arguments",
        "Reading notes remote add web TAB left to right: remote and add descend into nodes, web is positional 1, so the cursor is on slot 2 of the remote add node.",
        W, H, "\n".join(body), markers=True,
    )


# --------------------------------------------------------------------------
# a visual for every spec: the node tree of a .completions file
# --------------------------------------------------------------------------

NW, NH, PITCH, GAP = 200, 52, 68, 80  # node width/height, row pitch, column gap


def parse_spec(text: str) -> dict:
    """Section dict: key (path tuple, kind, last) -> body lines.

    kind is "n" (node), "f" (flag values) or "s" (slot). Mirrors SPEC.md's
    grammar closely enough to draw it; it is not the reader.
    """
    secs: dict = {(): {}}
    secs = {((), "n", ""): []}
    cur = ((), "n", "")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            toks = line[1:-1].split()
            last = ""
            if toks and (toks[-1].startswith("-") or re.fullmatch(r"#(\d+|\*)", toks[-1])):
                last = toks.pop()
            kind = "n" if not last else ("s" if last.startswith("#") else "f")
            cur = (tuple(toks), kind, last)
            secs.setdefault(cur, [])
            continue
        secs[cur].append(line)
    return secs


def spec_tree(secs: dict):
    """Nodes (path tuple -> info) for every [path] and every name in a parent."""
    nodes: dict = {}

    def touch(path):
        for i in range(len(path) + 1):
            nodes.setdefault(path[:i], dict(flags=[], slots=[], endopts=False, names=[], section=False))

    for (path, kind, last), body in secs.items():
        if path and path[0] == "*":
            continue
        touch(path)
        n = nodes[path]
        if kind == "f":
            n["section"] = True
        if kind == "n":
            n["section"] = True
            n["endopts"] = n["endopts"] or "@endopts" in body
            for line in body:
                if line.startswith("-"):
                    n["flags"].append(line)
                elif not line.startswith("@"):
                    n["names"].append(line)
        elif kind == "s":
            n["section"] = True
            if not body:
                what = "free"
            elif body[0].startswith("@"):
                what = body[0]
            else:
                what = "|".join(body[:2]) + ("|…" if len(body) > 2 else "")
            n["slots"].append(f"{last} {what}")
    for path in list(nodes):
        for name in nodes[path]["names"]:
            touch(path + (name,))
    return nodes


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def fig_spec(slug: str, cmd: str, text: str) -> str:
    secs = parse_spec(text)
    nodes = spec_tree(secs)
    gbody = secs.get((("*",), "n", ""), [])
    has_global = ("*",) in {k[0] for k in secs}
    kids: dict = {}
    for path in nodes:
        if path:
            kids.setdefault(path[:-1], []).append(path)
    # one row per leaf, parents centred on their children
    rows: dict = {}
    nxt = [0.0]

    def place(path):
        ch = sorted(kids.get(path, []), key=lambda p: list(nodes[path]["names"]).index(p[-1]) if p[-1] in nodes[path]["names"] else 99)
        if not ch:
            rows[path] = nxt[0]
            nxt[0] += 1
        else:
            for c in ch:
                place(c)
            rows[path] = (rows[ch[0]] + rows[ch[-1]]) / 2
        return rows[path]

    glob_row = None
    if has_global:  # the global node is the first child of the root, drawn dashed
        glob_row = nxt[0]
        nxt[0] += 1
    place(())
    depth = max(len(p) for p in nodes)
    cols = depth + 1
    W = 40 + cols * NW + depth * GAP + 40
    top = 32
    H = top + int(nxt[0] * PITCH) + 72
    pos = lambda path: (40 + len(path) * (NW + GAP), top + int(rows[path] * PITCH))
    focal = [p for p, n in nodes.items() if n["endopts"]]
    focal = focal[:1] or [()]

    wires, boxes = [], []

    def bus(parent_xy, child_cys, child_x):
        px, py = parent_xy[0] + NW, parent_xy[1] + NH // 2
        bx = px + GAP // 2
        wires.append(path_(f"M{px} {py} H{bx}"))
        lo, hi = min(child_cys + [py]), max(child_cys + [py])
        if hi > lo:
            wires.append(path_(f"M{bx} {lo + (8 if lo < py else 0)} V{hi - (8 if hi > py else 0)}"))
        for cy in child_cys:
            if cy == py:
                wires.append(path_(f"M{bx} {cy} H{child_x}"))
            elif cy < py:
                wires.append(path_(f"M{bx} {py} V{cy + 8} A8 8 0 0 1 {bx + 8} {cy} H{child_x}"))
            else:
                wires.append(path_(f"M{bx} {py} V{cy - 8} A8 8 0 0 0 {bx + 8} {cy} H{child_x}"))

    path_ = lambda d: f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1"/>'
    kid_list = list(kids.get((), []))
    root_xy = pos(())
    child_cys, cx = [], root_xy[0] + NW + GAP
    if has_global:
        child_cys.append(top + int(glob_row * PITCH) + NH // 2)
    for c in kids.get((), []):
        child_cys.append(pos(c)[1] + NH // 2)
    if child_cys:
        bus(root_xy, child_cys, cx)
    for path, ch in kids.items():
        if path == () or not ch:
            continue
        bus(pos(path), [pos(c)[1] + NH // 2 for c in ch], pos(ch[0])[0])

    def subs_for(n, global_node=False):
        out = []
        if n["flags"]:
            out.append(clip(" ".join(n["flags"]), 31))
        if n["slots"]:
            out.append(clip(" · ".join(n["slots"]), 31))
        if n.get("endopts"):
            out.insert(0, "@endopts: flags end at #1")
        return out[:2]

    for path, n in nodes.items():
        x, y = pos(path)
        name = cmd if not path else "[" + " ".join(path) + "]"
        kind = "focal" if path in focal else ("leaf" if not kids.get(path) else "step")
        subs = subs_for(n)
        if path and not n["section"]:
            subs = ["no section: nothing to offer"]
        boxes.append(box(x, y, NW, NH, kind, name, subs))
    if has_global:
        gx, gy = pos(()) [0] + NW + GAP, top + int(glob_row * PITCH)
        gflags = [l for l in gbody if l.startswith("-")]
        boxes.append(box(gx, gy, NW, NH, "optional", "[*]", [clip(" ".join(gflags), 31), "merged into every node"]))
    items = [("focal", "@endopts directive" if focal != [()] else "the command", 200),
             ("step", "node with children", 180), ("leaf", "leaf", 80)]
    if has_global:
        items.append(("optional", "[*] global, merged into every node", 280))
    body = wires + boxes + [legend(H - 52, W, items)]
    return svg(
        f"spec-{slug}",
        f"{cmd}: the shape of its completion spec",
        f"Node tree of the {cmd} completion spec: each box is a [path] section with its flags and positional slots.",
        W, H, "\n".join(body),
    )


def spec_sources() -> dict:
    """name -> spec text, for every example spec and the two specs in SPEC.md."""
    out = {}
    for f in sorted((ROOT / "examples").glob("*/.completions/*")):
        out[f.name] = f.read_text()
    blocks, cur, fence = [], [], None
    for line in (ROOT / "SPEC.md").read_text().splitlines():
        if line.startswith("```"):
            if fence is None:
                fence, cur = line[3:].strip(), []
            else:
                blocks.append((fence, "\n".join(cur) + "\n"))
                fence = None
        elif fence is not None:
            cur.append(line)
    for lang, block in blocks:
        if lang:
            continue
        if block.startswith("add\nlist\nremote"):
            out["tally"] = block
        elif block.startswith("run\nrm\nps"):
            out["dock"] = block
    return out


# --------------------------------------------------------------------------
# outputs
# --------------------------------------------------------------------------

STANDALONE_FONTS = (
    "<style>@import url('https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,500;0,700;1,400"
    "&amp;family=IBM+Plex+Mono:wght@400;500;600&amp;display=swap');</style>"
)


def standalone(s: str) -> str:
    # strict-SVG consumers read rgba()/transparent as opaque black: normalise
    s = re.sub(
        r'(fill|stroke)="rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d*\.?\d+)\s*\)"',
        lambda m: '{0}="#{1:02x}{2:02x}{3:02x}" {0}-opacity="{4}"'.format(
            m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        ),
        s,
    )
    s = re.sub(r'(fill|stroke)="transparent"', r'\1="none"', s)
    if "<defs>" in s:
        s = s.replace("<defs>", "<defs>\n" + STANDALONE_FONTS, 1)
    else:
        s = re.sub(r"(</desc>\n)", r"\1<defs>\n" + STANDALONE_FONTS + "\n</defs>\n", s, count=1)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + s + "\n"


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>dircomp diagrams</title>
  <link href="{fonts}" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --color-paper:  {paper};
      --color-ink:    {ink};
      --color-muted:  {muted};
      --color-soft:   {soft};
      --color-rule:   {rule};
      --color-accent: {accent};
      --font-sans:    'Roboto', system-ui, sans-serif;
      --font-mono:    'IBM Plex Mono', ui-monospace, monospace;
    }}
    body {{
      font-family: var(--font-sans);
      background: var(--color-paper);
      color: var(--color-ink);
      padding: 3rem 2rem 2rem;
    }}
    .frame {{ max-width: 1040px; margin: 0 auto; }}
    .eyebrow {{
      font-family: var(--font-mono);
      font-size: 0.66rem;
      font-weight: 500;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--color-muted);
      margin-bottom: 0.5rem;
    }}
    h1 {{
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.01em;
      line-height: 1.15;
      margin-bottom: 0.75rem;
    }}
    .lede {{ color: var(--color-muted); font-size: 0.95rem; line-height: 1.5; max-width: 64ch; margin-bottom: 3rem; }}
    .lede code, figcaption code {{ font-family: var(--font-mono); font-size: 0.85em; color: var(--color-ink); }}
    section {{ margin-bottom: 3.5rem; }}
    h2 {{ font-size: 1.1rem; font-weight: 500; margin-bottom: 1rem; }}
    figure svg {{ width: 100%; display: block; }}
    figcaption {{ margin-top: 0.75rem; color: var(--color-muted); font-size: 0.85rem; line-height: 1.5; max-width: 72ch; }}
    footer {{
      border-top: 1px solid var(--color-rule);
      padding-top: 1rem;
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--color-soft);
    }}
    a {{ color: inherit; }}
  </style>
</head>
<body>
  <div class="frame">
    <p class="eyebrow">dircomp &middot; completion spec v3</p>
    <h1>dircomp in five diagrams</h1>
    <p class="lede">What happens on a TAB, the shape a <code>.completions</code> file describes, how the reader counts positional arguments, how it consumes the words before the cursor, and how it classifies the word under it. Guide: <a href="MANUAL.md">MANUAL.md</a>. Rules: <a href="../SPEC.md">SPEC.md</a>.</p>

    <section>
      <p class="eyebrow">Flow &middot; one TAB</p>
      <h2>What happens when you press TAB</h2>
      <figure>
{howitworks}
        <figcaption>Find the spec from the command's own file, walk the words already typed, then pick one section for the word under the cursor. Here the cursor is on the second positional of <code>remote add</code>.</figcaption>
      </figure>
    </section>

    <section>
      <p class="eyebrow">Tree &middot; shape</p>
      <h2>What a spec describes</h2>
      <figure>
{tree}
        <figcaption>Each box is a <code>[path]</code> section of a docker-shaped spec. <code>[*]</code> is merged into every node. Leaves are flag-value sections and positional slots; <code>@endopts</code> on <code>[run]</code> hands everything after the image to the container.</figcaption>
      </figure>
    </section>

    <section>
      <p class="eyebrow">Walk &middot; counting</p>
      <h2>Counting positional arguments</h2>
      <figure>
{slots}
        <figcaption>Words that name a node move <code>P</code> and reset <code>k</code>. Any other word is a positional and raises <code>k</code>. The cursor then reads slot <code>k + 1</code>.</figcaption>
      </figure>
    </section>

    <section>
      <p class="eyebrow">Flowchart &middot; walk</p>
      <h2>Consuming one typed word</h2>
      <figure>
{walk}
        <figcaption>Run for every word before the cursor, left to right. <code>k</code> counts positionals at the current node. Descent into a subcommand is only possible while <code>k</code> is 0.</figcaption>
      </figure>
    </section>

    <section>
      <p class="eyebrow">Flowchart &middot; classify</p>
      <h2>The word under the cursor</h2>
      <figure>
{classify}
        <figcaption><code>P</code> is the node path the walk ended on. A slot hides flags and subcommand names until <code>-</code> is typed.</figcaption>
      </figure>
    </section>

    <footer>Drawn with the diagram-design skill. Standalone files: spec-howitworks.svg, spec-tree.svg, spec-slots.svg, spec-walk.svg, spec-classify.svg.</footer>
  </div>
</body>
</html>
"""


GALLERY_CAPTIONS = {
    "tally": "The v3 spec from SPEC.md's examples: nesting, a global section, slots.",
    "dock": "SPEC.md's docker-shaped spec: @endopts on run, a variadic rm.",
    "notes": "The tutorial's finished spec (examples/notes/.completions/notes).",
    "ship": "examples/ship: three levels of subcommand, globals, an override.",
    "box": "examples/box: the shape of docker run, with @endopts on run.",
    "backup": "examples/backup: positional slots with different meanings.",
    "mig": "examples/mig: clusters, an alias, a variadic file slot.",
}


def gallery(specs: dict) -> str:
    head = PAGE.split("<body>")[0].replace("<title>dircomp diagrams</title>", "<title>dircomp spec visuals</title>")
    head = head.format(
        fonts=FONTS_HREF.replace("&", "&amp;"),
        paper=PAPER, ink=INK, muted=MUTED, soft=SOFT, rule=RULE, accent=ACCENT,
    ) if "{fonts}" in head else head
    secs = []
    for name in specs:
        src = {"tally": "../SPEC.md", "dock": "../SPEC.md"}.get(name, f"../examples/{name}/.completions/{name}")
        secs.append(f"""    <section>
      <p class="eyebrow">Spec &middot; {name}</p>
      <h2>{name}</h2>
      <figure>
{specs[name]}
        <figcaption>{esc(GALLERY_CAPTIONS.get(name, ""))} Source: <a href="{src}">{src.lstrip("./")}</a>.</figcaption>
      </figure>
    </section>
""")
    return head + """<body>
  <div class="frame">
    <p class="eyebrow">dircomp &middot; completion specs</p>
    <h1>Every spec, drawn</h1>
    <p class="lede">Each box is a <code>[path]</code> section with its flags and positional slots. The command is the root; <code>[*]</code> is merged into every node. Guide: <a href="MANUAL.md">MANUAL.md</a>.</p>
""" + "\n".join(secs) + """
    <footer>Generated by docs/build-diagrams.py from the spec files. Standalone files are in docs/specs/.</footer>
  </div>
</body>
</html>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    figs = {"tree": fig_tree(), "walk": fig_walk(), "classify": fig_classify(),
            "howitworks": fig_howitworks(), "slots": fig_slots()}
    for name, s in figs.items():
        (OUT / f"spec-{name}.svg").write_text(standalone(s))
    page = PAGE.format(
        fonts=FONTS_HREF.replace("&", "&amp;"),
        paper=PAPER, ink=INK, muted=MUTED, soft=SOFT, rule=RULE, accent=ACCENT,
        **figs,
    )
    (OUT / "spec-diagrams.html").write_text(page)

    (OUT / "specs").mkdir(exist_ok=True)
    order = ["tally", "dock", "notes", "ship", "box", "backup", "mig"]
    sources = spec_sources()
    drawn = {}
    for name in order:
        drawn[name] = fig_spec(name, name, sources[name])
        (OUT / "specs" / f"{name}.svg").write_text(standalone(drawn[name]))
    (OUT / "spec-visuals.html").write_text(gallery(drawn))
    print("wrote", sorted(p.name for p in OUT.iterdir()), sorted(p.name for p in (OUT / "specs").iterdir()))


main()
