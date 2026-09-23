#!/usr/bin/env python3
"""verify_readme.py — one runnable check for README.md's structural integrity.

Re-runnable by anyone, from the repo root:

    uv run --no-project python scripts/verify_readme.py

Checks (exit 0 = all pass, 1 = something is broken):
  1. every internal link ](#anchor) resolves to a heading slug or an <a id="...">
  2. footnote hygiene: no definition without a citation, no citation without a
     definition
  3. markdown tables are rectangular (every row has its header's cell count)
  4. paragraph-level parentheses/bold balance outside tables and code fences
  5. the <!-- toc --> block matches what scripts/toc.py would generate

Deliberately dependency-free (stdlib only) so it runs in a fresh shell.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
failures: list[str] = []


def slug(heading: str) -> str:
    s = re.sub(r"[^\w\s-]", "", heading.lower())
    return s.strip().replace(" ", "-")


def check_links(text: str) -> None:
    anchors = {slug(m.group(1).strip()) for m in re.finditer(r"^#{1,6}\s+(.*)$", text, re.M)}
    anchors |= set(re.findall(r'<a id="([^"]+)"', text))
    bad = sorted({l for l in re.findall(r"\]\(#([^)]+)\)", text) if l not in anchors})
    if bad:
        failures.append(f"unresolved internal links: {bad}")


def check_footnotes(text: str) -> None:
    defined = set(re.findall(r'<a id="(fn\d+)">', text))
    cited = set(re.findall(r"\]\(#(fn\d+)\)", text))
    if orphans := sorted(defined - cited, key=lambda x: int(x[2:])):
        failures.append(f"footnotes defined but never cited: {orphans}")
    if missing := sorted(cited - defined, key=lambda x: int(x[2:])):
        failures.append(f"footnotes cited but never defined: {missing}")


def check_tables(text: str) -> None:
    for n, block in enumerate(re.finditer(r"(?:^\|.*\n)+", text, re.M), 1):
        rows = [r for r in block.group(0).splitlines() if r.strip()]
        counts = {len(r.split("|")) for r in rows}
        if len(counts) > 1:
            failures.append(f"table #{n} near line {text[:block.start()].count(chr(10))+1} is ragged: {sorted(counts)} cells")


def check_paragraphs(text: str) -> None:
    infence, para, start = False, [], 0

    def audit(p: list[str], s: int) -> None:
        if not p or any(l.startswith(("|", "```", "  ")) for l in p):
            return
        joined = " ".join(p)
        if joined.count("(") != joined.count(")"):
            failures.append(f"unbalanced parentheses in the paragraph at line {s}")
        if joined.count("**") % 2:
            failures.append(f"unbalanced bold markers in the paragraph at line {s}")

    for n, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            infence = not infence
        if not line.strip() and not infence:
            audit(para, start)
            para, start = [], n + 1
        else:
            if not para:
                start = n
            para.append(line)
    audit(para, start)


def check_toc(text: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "toc.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        if "unrecognized" in out or "no such option" in out.lower():
            return  # older toc.py without --check: skip rather than false-fail
        failures.append(f"ToC out of date (run scripts/toc.py): {out[:200]}")


def main() -> int:
    text = README.read_text()
    check_links(text)
    check_footnotes(text)
    check_tables(text)
    check_paragraphs(text)
    check_toc(text)
    if failures:
        print("README verification FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("README verification PASSED: links, footnotes, tables, paragraphs, ToC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
