# Local patchset — pwilkin/llama.cpp (strixy fork base)

`pwilkin/llama.cpp` (branch `strix-halo`) is **third-party and read-only** for
us; the fork lives at `~/.local/share/qwen3.8-strix-halo/src/llama.cpp`
(detached HEAD at the fork's tip) and carries these commits **locally only**.
The patch files here are the durable copy — re-apply after a fresh clone:

```bash
git am patches/0001-*.patch patches/0002-*.patch
```

| patch | what | why |
|---|---|---|
| 0001 | `server: fix router eviction races with the existing queue` (#29217 cherry-pick, upstream `991991118571`) | arm-switch/unload-first race class (doctor 260923 F4); applies clean on the fork tip |
| 0002 | `qwen4exp: let a quantized cache fall back to the masked QSA path` | removes the `GGML_ASSERT(q 256 / K,V F16)` abort on the HIP fast path; enables the KV-quant headroom route (256k). F16 caches keep the fast path untouched |

Patches authored here (260923). Regenerate after edits with
`git format-patch <fork-tip>..HEAD -o patches/`.

## Local patchset — gufo (`~/Downloads/Git/gufo`)

Plain `git apply` patches (working-tree delta, not `git am` commits) — the gufo
clone stays at upstream HEAD and carries this only while building.

```bash
cd ~/Downloads/Git/gufo && git apply ../../Strix_AI_Server/patches/gufo-0001-*.patch
GUFO_SKIP_DS4=1 cmake --build build/release
```

| patch | what | why |
|---|---|---|
| gufo-0001 | `GUFO_SKIP_DS4=1` env guard around the ds4 subdirectory/targets + `src/models/deepseek_v4_flash/stub.cpp` (fatal stubs) | nightly `ld.lld` 24 SIGSEGVs in the LTO CallGraph pass linking the ds4 HIP device kernels (3× Sep 27 12:23/12:25/12:26, doctor 260928 F4). Serving a ds4 model then aborts loudly instead of shipping a half-linked binary. Drop when the toolchain stops crashing |

Verified 260928: `git apply -R --check` against the live tree at `b722a61`
(the build that shipped to strixy2 and passed the F3 gate) → clean, so the
patch is byte-equivalent to the delta the champion was built from.
