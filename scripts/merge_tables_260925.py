#!/usr/bin/env python3
"""260925 README restructure (operator mandate):
merge Podium + Champion-vs-cloud + Inference-stacks tables into one
'What we measured' table (leftmost qualifier column: Local LLM / Cloud /
Engine), follow with 'Analysis' (sub-chapter per row) then 'Footnotes'.
Source: README.md is backed up as README-premerge-260925.md first.
"""
import re, sys, shutil

SRC = "README.md"
shutil.copy(SRC, "README-premerge-260925.md")
md = open(SRC).read()
lines = md.split("\n")

def find(needle, start=0):
    for i in range(start, len(lines)):
        if lines[i].startswith(needle):
            return i
    raise SystemExit(f"boundary not found: {needle}")

# ---- boundaries ----------------------------------------------------------
i_podium  = find("## Podium")                      # table 1 chapter start
i_cloud   = find("## Champion vs cloud models")    # table 2 start
i_engine  = find("## Inference stacks")            # table 3 start
i_arch    = find("## Arch Linux minimal server")   # end of the three
i_details = find("## Podium — the details")
i_foot    = find("## Footnotes")
i_ital    = find("## Italian (iten12)")            # end of footnotes block

podium_ch  = lines[i_podium:i_cloud]
cloud_ch   = lines[i_cloud:i_engine]
engine_ch  = lines[i_engine:i_arch]
details_ch = lines[i_details:i_foot]
foot_ch    = lines[i_foot:i_ital]

# ---- parse the three tables ---------------------------------------------
def table_rows(ch):
    """return (header_cols, [row_cells...]) for the first md table in ch"""
    hdr = sep = None
    for i, l in enumerate(ch):
        if l.startswith("|") and "---" in ch[i+1] if i+1 < len(ch) else False:
            hdr, rows, j = [c.strip() for c in l.strip("|").split("|")], [], i+2
            while j < len(ch) and ch[j].startswith("|"):
                rows.append([c.strip() for c in ch[j].strip("|").split("|")]); j += 1
            return hdr, rows
    raise SystemExit("no table found in chapter")

phdr, prows = table_rows(podium_ch)
chdr, crows = table_rows(cloud_ch)
ehdr, erows = table_rows(engine_ch)
assert phdr[0] == "model" and chdr[0].startswith("metric") and ehdr[0] == "engine", (phdr[0], chdr[0], ehdr[0])

# podium row cells: model|pp4k|pp32k|pp128k|tg128|tg2048|iten|aime|fcb15|ladder|sli|zebra|ram|draft
COLS = ["class","solution","pp4k","pp32k","pp128k","tg128","tg2048","iten12","aime12","aime60","zebra","fcb15","ladder","sli","ram"]
merged = []
for r in prows:  # locals
    model, pp4k, pp32k, pp128k, tg128, tg2048, iten, aime, fcb, lad, sli, zeb, ram, draft = r
    aime60 = "—"
    if "UD-Q4_K_XL" in model: aime60 = "**0.533** [0.41–0.65] [³⁴](#fn34)"
    elif "Q5_K_XL" in model:  aime60 = "0.533 [³⁴](#fn34)"
    merged.append(["Local LLM", model, pp4k, pp32k, pp128k, tg128, tg2048, iten, aime, aime60, zeb, fcb, lad, sli, f"{ram} · draft {draft}"])

# cloud table is metric-per-row: transpose into per-solution cells
cm = {row[0]: row[1:] for row in crows}  # metric -> [champ, dsv4f, glm53, glm53f]
def cget(metric, idx): return cm[metric][idx]
for name, idx in (("DeepSeek V4.1 Flash (cloud API)", 1), ("GLM-5.3 (cloud API)", 2), ("GLM-5.3-flash (cloud API)", 3)):
    merged.append(["Cloud", name, "—", "—", "—", "—", "—",
                   cget("Italian gate (iten12)", idx), cget("AIME yearsplit-12", idx),
                   cget("AIME-60 census", idx), cget("Zebra CSP ladder", idx),
                   cget("fcb15 coding", idx), cget("fcb15 ladder (all rungs, greedy)", idx),
                   cget("sli structured-list", idx), "n/a (API)"])

# engine rows: engine|status|measured-on|pp4k|tg128|tg2048|fcb15|read
ENG = {
 "llama.cpp fork": dict(pp4k="**865**", pp32k="**909**", pp128k="**761** [³⁷](#fn37)", tg128="33.5", tg2048="**31.7**", fcb="**14/15**"),
 "vanilla, `b11168`": dict(pp4k="476", pp32k="395", pp128k="dies [³⁸](#fn38)", tg128="20.7", tg2048="21.7", fcb="none"),
 "vanilla, **Vulkan**": dict(pp4k="468", pp32k="407", pp128k="—", tg128="**26.0**", tg2048="**25.1**", fcb="none"),
 "halogen-flash-server": dict(pp4k="**980**", pp32k="—", pp128k="262k-capable", tg128="26.9", tg2048="22.8", fcb="12/15"),
 "Gufo": dict(pp4k="**1200**", pp32k="**1100**", pp128k="n/a [³⁰](#fn30)", tg128="**44.3**", tg2048="**35.3**", fcb="**13/15**"),
 "ROCmFPX": dict(pp4k="336", pp32k="—", pp128k="—", tg128="23.4", tg2048="19.7", fcb="13/15"),
}
for r in erows:
    eng, status, measured, pp4k, tg128, tg2048, fcb, _read = r
    spec = next((v for k, v in ENG.items() if k in eng), None)
    if spec is None:  # fall back to parsed cells
        spec = dict(pp4k=pp4k, pp32k="—", pp128k="—", tg128=tg128, tg2048=tg2048, fcb=fcb)
    label = eng + f" — {measured}"
    merged.append(["Engine", label, spec["pp4k"], spec["pp32k"], spec["pp128k"], spec["tg128"], spec["tg2048"],
                   "—", "—", "—", "—", spec["fcb"], "—", "—", "—"])

tbl = ["| " + " | ".join(["class","solution","pp @4k","pp @32k","pp @128k","tg128","tg2048","iten12","AIME-12","AIME-60","zebra","fcb15","ladder","sli","RAM / draft"]) + " |",
       "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
for m in merged:
    tbl.append("| " + " | ".join(m) + " |")

# ---- new chapters ---------------------------------------------------------
new_main = f"""## What we measured

One table, every solution this fleet has put a number on — local LLMs, cloud
APIs, and the engines that serve them. The champion slot is open to any class:
today it is a local LLM on our fork, but an engine (see gufo) can win it too.
Empty cells are **doable but not yet measured** — they are not zeros, and the
[Analysis](#analysis--every-measured-solution) sub-chapters name each row's
missing cells. Cells keep their footnote markers: bases, CIs and protocols
live in [Footnotes](#footnotes).

{chr(10).join(tbl)}

Reading it honestly:

- **Bases are heterogeneous by design** — engines were measured on the
  weights noted in their row (the fork, halogen, gufo and both vanilla builds
  on UD-Q4_K_XL; ROCmFPX on its own fp4 format), clouds at vendor defaults,
  locals at the fleet basis. Only cells that share weights and day compare
  head-to-head; footnote markers say which.
- **The cloud columns carry the format caveat** ([⁷](#fn7)): a cloud API that
  ignores the one-code-block answer contract scores a *format* failure —
  compatibility first, capability second.
- **What is still missing and doable**: iten12/AIME/zebra/sli for the engine
  rows (gufo first — it is the only engine that could take the champion slot),
  AIME-60 for Q6/Muse, and the fork's own census cells beyond fcb15/AIME-12.
"""

analysis_head = "## Analysis — every measured solution"
new_subs = """
### The fork (llama.cpp strix-halo) — why it still serves
The load-bearing baseline: the only engine that hosts the family's MTP draft
(`--spec-type draft-mtp`), the deep-prefill patches (pp128k 761 t/s where
vanilla dies), months of resident-serving robustness, and the models.ini
router + systemd fleet around it. Cons: closed-ish pace (fork maintenance),
decode behind gufo (33.5 vs 44.3 tg128), no modality beyond text+vision.
Missing cells: its own iten/AIME/zebra census rows (they are the champion's —
same arm, same weights).

### Gufo — the open challenger
The only engine beating the fork on both axes at the fleet basis (pp +39%,
tg +11–32%), quality holding (13/15), one MIT binary covering text +
Qwen-Image-2.1 + TTS + ASR, maintained by the Italian Strix-Halo community.
Cons: fleet robustness unproven (every cell <1 h fresh-load), concurrency
unmeasured, operational surface (router/slots/eviction) unmapped, loader is
UD-Q4-strict. Path: one-week probation as strixy2's resident default, Doctor
watching, fork one systemd unit away. Missing cells: iten12, AIME, zebra, sli
— all doable in one bench window.

### DeepSeek V4.1 Flash (cloud)
The cheapest strong cloud: AIME-12 parity with the champion (0.667), iten
12/12. Cons: fcb15 7/15 greedy (9/15 with retry — below every local), zebra
0.42, format-contract failures; API cost and data egress vs any local row.
Missing cells: pp128k-class deep context (meaningless for an API), sli tied
0.8.

### GLM-5.3 (cloud)
The strongest cloud on the ladder (11/15 greedy, 14/15 with retry) and
AIME-60 0.433; sli 10/10. Cons: fcb15 census 0.60, zebra 0.50, the same
format caveat; per-token cost scales with thinking. Missing cells: none
blocking — it is a complete cloud row.

### GLM-5.3-flash (cloud)
The value pick: ladder 9/15 greedy but **15/15 with retry** (its greedy
misses are format, not capability), AIME-60 0.367. Cons: AIME-12 0.333 —
the reasoning floor of the cloud set; iten 11/12. Missing cells: none
blocking.
"""

# ---- relocate + retitle ----------------------------------------------------
details = list(details_ch)
assert details[0].startswith("## Podium — the details")
details[0] = analysis_head + "  <!-- was: Podium — the details -->"
# strip the now-redundant intro line of old details chapter if it duplicates
gufo_note = None
for i, l in enumerate(details):
    if "**Gufo as the overall engine (operator question, 2026-09-25):**" in l:
        gufo_note = i
# engine adoption paragraph lives in the OLD engine chapter; move it here
engine_reading = [l for l in engine_ch if l.strip()]

out = lines[:i_podium]                      # up to old Podium
out += new_main.split("\n")                 # new merged chapter
out += [""] + details                       # Analysis (retitled, with old subs)
out += [""]
out += new_subs.split("\n")                 # new Analysis sub-chapters
out += [""] + foot_ch                       # Footnotes chapter right after
out += [""] + lines[i_arch:i_details]      # Arch..Reproduce chapters
out += [""] + lines[i_ital:]               # battery deep-dive chapters (tail)
out += [""]
md2 = "\n".join(out)

# ---- repoint anchors -------------------------------------------------------
for old, new in (("(#podium)", "(#what-we-measured)"),
                 ("(#champion-vs-cloud-models--deepseek-v41-flash-and-glm-53)", "(#what-we-measured)"),
                 ("(#inference-stacks--the-engine-axis)", "(#what-we-measured)"),
                 ("(#podium--the-details)", "(#analysis--every-measured-solution)")):
    md2 = md2.replace(old, new)
# drop the three old ToC lines, add the new ones
md2 = md2.replace("- [Podium](#what-we-measured)\n- [Champion vs cloud models — DeepSeek V4.1 Flash and GLM-5.3](#what-we-measured)\n- [Inference stacks — the engine axis](#what-we-measured)",
                  "- [What we measured](#what-we-measured)\n- [Analysis — every measured solution](#analysis--every-measured-solution)")
md2 = md2.replace("## In a hurry? Look at these 2 tables", "## In a hurry? Look at this table")
md2 = md2.replace("[**the podium**](#what-we-measured) — which local model this fleet serves and why",
                  "[**What we measured**](#what-we-measured) — every solution with a number on it")
md2 = md2.replace("[**the champion vs the cloud**](#what-we-measured) — the same batteries run",
                  "[**Analysis**](#analysis--every-measured-solution) — the same batteries run")
# fn38: note upstream moved
md2 = md2.replace("(iii) the Vulkan decode win over\nvanilla HIP (+26% tg128) replicates on Q4, same direction as fn35's Q5 finding.",
                  "(iii) the Vulkan decode win over\nvanilla HIP (+26% tg128) replicates on Q4, same direction as fn35's Q5 finding.\n(Upstream moved on to b11181 `d028c697b` the same morning; the cells above\nremain b11168 — re-pin on the next engine pass.)")

open(SRC, "w").write(md2)
print(f"merged: {len(merged)} rows ({len(prows)} local + 3 cloud + {len(erows)} engine); "
      f"details {len(details_ch)} lines moved; footnotes {len(foot_ch)} lines moved")
