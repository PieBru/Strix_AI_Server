#!/usr/bin/env python3
"""footnote_links — turn every footnote reference into a link to its definition.

The README marks footnotes with unicode superscripts (¹ ² ¹⁰ ...) and defines
them as plain paragraphs under "### Footnotes". Plain paragraphs get no anchor
on GitHub, so this does two things:

  1. inserts an explicit target before each definition:  <a id="fn10"></a>¹⁰ ...
  2. rewrites every other superscript run into a link:   [¹⁰](#fn10)

Idempotent by construction: it first strips its own anchors and links, then
regenerates them, so running it twice changes nothing. Only runs whose number
has a definition are linked — an unknown number is reported and left alone.

Usage:
  python3 scripts/footnote_links.py          # rewrite README.md in place
  python3 scripts/footnote_links.py --check  # exit 1 if it would change
Self-check: python3 scripts/footnote_links.py --selfcheck
"""

import re
import sys

SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹"
TO_DIGIT = str.maketrans(SUP, "0123456789")
RUN = f"[{SUP}]+"

ANCHOR = re.compile(r'<a id="fn\d+"></a>')
LINK = re.compile(rf"\[({RUN})\]\(#fn\d+\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def sup_to_int(run: str) -> int:
    return int(run.translate(TO_DIGIT))


def build(md: str):
    """-> (new_md, linked_count, unknown_numbers)

    Definitions are detected anywhere in the document (the README carries two
    blocks: the main `### Footnotes` and a later pair that belongs to the
    coding chapter), so a definition is any line that starts with a superscript
    run followed by a space or end of line.
    """
    md = ANCHOR.sub("", md)
    md = LINK.sub(r"\1", md)

    lines = md.split("\n")
    defined, unknown = set(), set()
    in_fence = False
    for n, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(rf"^({RUN})(?: |$)", line)
        if m:
            num = sup_to_int(m.group(1))
            defined.add(num)
            lines[n] = f'<a id="fn{num}"></a>' + line

    def link_run(m):
        num = sup_to_int(m.group(0))
        if num not in defined:
            unknown.add(num)
            return m.group(0)
        return f"[{m.group(0)}](#fn{num})"

    linked = 0
    in_fence = False
    for n, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # a definition's leading marker is the anchor target itself — its
        # space-separated tail must not be linked either
        head = ""
        m = re.match(rf'^(<a id="fn\d+"></a>)({RUN})(?: |$)', line)
        if m:
            head, line = m.group(0), line[m.end():]
        new = re.sub(RUN, link_run, line)
        linked += len(re.findall(rf"\[{RUN}\]\(#fn\d+\)", new))
        lines[n] = head + new
    return "\n".join(lines), linked, unknown


def verify(md: str):
    """Every #fnN target must exist, and no unlinked reference may remain."""
    targets = {int(x) for x in re.findall(r'<a id="fn(\d+)"></a>', md)}
    refs = {int(x) for x in re.findall(r"\(#fn(\d+)\)", md)}
    assert refs <= targets, f"links with no target: {sorted(refs - targets)}"
    body = LINK.sub("", md)                       # drop the links just made
    body = re.sub(rf'^<a id="fn\d+"></a>{RUN}(?: |$)', "", body, flags=re.M)
    bare = [r for r in re.findall(RUN, body) if sup_to_int(r) in targets]
    assert not bare, f"unlinked references remain: {bare[:5]}"
    return len(targets), len(re.findall(r"\(#fn\d+\)", md))


def selfcheck():
    doc = "# T\n\nFact ¹ and pair ⁷ ⁸ here.\n\n### Footnotes\n\n¹ one\n\n⁷ seven\n\n⁸ eight\n"
    out, linked, unknown = build(doc)
    assert '<a id="fn1"></a>¹ one' in out and '<a id="fn7"></a>⁷ seven' in out, out
    assert "[¹](#fn1)" in out.split("### Footnotes")[0], out
    assert "[⁷](#fn7) [⁸](#fn8)" in out, out
    assert not unknown, unknown
    again, linked2, _ = build(out)
    assert again == out, "not idempotent"
    verify(out)
    # an unknown number stays plain text and is reported
    out2, _, unk = build("# T\n\nsee ⁹ nothing\n\n### Footnotes\n\n¹ one\n")
    assert 9 in unk and "[⁹]" not in out2, (unk, out2)
    print("footnote_links selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
        raise SystemExit(0)
    md = open("README.md", encoding="utf-8").read()
    new, linked, unknown = build(md)
    targets, refs = verify(new) if new != md else (0, 0)
    if "--check" in sys.argv:
        if new != md:
            print("footnote links are stale — run scripts/footnote_links.py")
            raise SystemExit(1)
        print("footnote links up to date")
        raise SystemExit(0)
    if new != md:
        open("README.md", "w", encoding="utf-8").write(new)
        print(f"footnote links written: {targets} targets, {refs} references")
    else:
        print("footnote links unchanged")
    if unknown:
        print(f"WARNING: {len(unknown)} number(s) have no definition, left as text: "
              f"{sorted(unknown)}")
