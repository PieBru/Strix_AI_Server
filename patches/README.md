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
