#!/usr/bin/env python3
"""toc — regenerate the README's table of contents between the toc markers.

Why a script and not a markdown extension: GitHub has no in-file ToC
directive (GitLab's [[_TOC_]] has no GitHub equivalent). GitHub *does*
anchor every heading, so a generated list of links is all that is needed —
this regenerates that list from the headings themselves, and the workflow in
.github/workflows/toc.yml runs it on every README change, so the list cannot
go stale.

Slugs follow GitHub's own slugger: lowercase, drop anything that is not a
letter/digit/space/hyphen/underscore (so backticks, emoji and punctuation
vanish), spaces -> hyphens, and repeated slugs get -1, -2 suffixes.

Usage:
  python3 scripts/toc.py            # rewrite README.md's toc block in place
  python3 scripts/toc.py --check    # exit 1 if the block is stale (CI use)
Self-check: python3 scripts/toc.py --selfcheck
"""

import re
import sys
import unicodedata

START = "<!-- toc -->"
END = "<!-- /toc -->"
HEADING = re.compile(r"^(#{2,3})\s+(.*?)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(text: str) -> str:
    """GitHub's heading -> anchor slug."""
    s = text.strip().lower()
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)   # links -> their text
    s = s.replace("`", "").replace("*", "").replace("_", "_")
    out = []
    for ch in s:
        if ch.isalnum() or ch in " -_":
            out.append(ch)
        elif unicodedata.category(ch).startswith("L") or unicodedata.category(ch).startswith("N"):
            out.append(ch)                            # keep non-ascii letters/digits
    return re.sub(r"\s", "-", "".join(out)).strip("-")


def headings(md: str):
    """-> [(level, text, slug)] for h2/h3 outside code fences; unique slugs."""
    seen, res, in_fence = {}, [], False
    for line in md.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2).strip()
        text = re.sub(r"\s*#+\s*$", "", text)         # trailing hashes
        sl = slug(text)
        n = seen.get(sl, 0)
        seen[sl] = n + 1
        res.append((level, text, sl if n == 0 else f"{sl}-{n}"))
    return res


def build(md: str) -> str:
    hs = headings(md)
    lines = [START, ""]
    for level, text, sl in hs:
        indent = "" if level == 2 else "  "
        lines.append(f"{indent}- [{text}](#{sl})")
    lines += ["", END]
    return "\n".join(lines)


def rewrite(md: str) -> str:
    block = build(md)
    if START in md and END in md:
        i = md.index(START)
        j = md.index(END) + len(END)
        return md[:i] + block + md[j:]
    # first insertion: right after the first heading (or at the top)
    lines = md.splitlines(keepends=True)
    ins = 0
    for k, l in enumerate(lines):
        if l.startswith("# "):
            ins = k + 1
            break
    return "".join(lines[:ins]) + "\n" + block + "\n" + "".join(lines[ins:])


def selfcheck():
    assert slug("Why not IQ4_NL? (also 12/12, faster decode, less RAM)") == \
        "why-not-iq4_nl-also-1212-faster-decode-less-ram", slug("x")
    assert slug("Speed at depth — how much wall-time you actually wait") == \
        "speed-at-depth--how-much-wall-time-you-actually-wait", slug("y")
    assert slug("`code` and *star*") == "code-and-star"
    md = "# T\n\n## A\n\n### B\n\n## A\n\n```\n## not-a-heading\n```\n"
    hs = headings(md)
    assert [h[2] for h in hs] == ["a", "b", "a-1"], hs
    out = rewrite(md)
    assert "## not-a-heading" in out and "- [A](#a)" in out and "- [A](#a-1)" in out
    print("toc selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
        raise SystemExit(0)
    path = "README.md"
    md = open(path, encoding="utf-8").read()
    new = rewrite(md)
    if "--check" in sys.argv:
        if new != md:
            print("README toc block is stale — run scripts/toc.py")
            raise SystemExit(1)
        print("toc up to date")
        raise SystemExit(0)
    if new != md:
        open(path, "w", encoding="utf-8").write(new)
        print(f"toc rewritten ({len(headings(md))} headings)")
    else:
        print("toc unchanged")
