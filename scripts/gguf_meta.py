#!/usr/bin/env python3
"""gguf_meta.py — read a GGUF file's header + metadata without llama.cpp or internet.

The rule before a systemd unit points at a rsynced weight file (AGENTS 260928,
.150 relay): read the metadata of the COPY. Size alone does not prove the copy is
the model you think it is. Stdlib only.

    python3 scripts/gguf_meta.py FILE.gguf [KEY_FILTER ...]
    python3 scripts/gguf_meta.py FILE.gguf --expect-arch spark2_5

Exit 0 = header parsed (and every --expect-* matched). Non-zero = bad copy.
"""
import struct, sys

# GGUF spec type ids (0-based, gguf-spec.md): a wrong table parses real files into
# garbage, so the --selftest fixture hardcodes the spec numbers, not these names.
T = dict(U8=0, I8=1, U16=2, I16=3, U32=4, I32=5, F32=6, BOOL=7, STRING=8, ARRAY=9, U64=10, I64=11, F64=12)
FMT = {T["U8"]: "B", T["I8"]: "b", T["U16"]: "<H", T["I16"]: "<h", T["U32"]: "<I",
       T["I32"]: "<i", T["F32"]: "<f", T["U64"]: "<Q", T["I64"]: "<q", T["F64"]: "<d"}


def _str(f):
    n = struct.unpack("<Q", f.read(8))[0]
    if n > 1 << 24:  # a torn/wrong-offset file asks for gigabytes; fail as BAD COPY
        raise ValueError(f"implausible string length {n}")
    return f.read(n).decode("utf-8", "replace")


def _val(f, t):
    if t == T["STRING"]:
        return _str(f)
    if t == T["BOOL"]:
        return struct.unpack("<B", f.read(1))[0] != 0
    if t == T["ARRAY"]:
        et, n = struct.unpack("<I", f.read(4))[0], struct.unpack("<Q", f.read(8))[0]
        return [_val(f, et) for _ in range(n)]
    fmt = FMT[t]
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def read(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        ver = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        meta = {}
        for _ in range(n_kv):
            key = _str(f)
            t = struct.unpack("<I", f.read(4))[0]
            meta[key] = _val(f, t)
    return ver, n_tensors, meta


def main():
    args, expects = [], {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i].startswith("--expect-"):
            expects[argv[i][len("--expect-"):].replace("-", ".")] = argv[i + 1]; i += 2
        else:
            args.append(argv[i]); i += 1
    if not args:
        print(__doc__); return 2
    path = args[0]
    filt = args[1:]
    try:
        ver, n_tensors, meta = read(path)
    except Exception as e:
        print(f"BAD COPY: {path}: {e}"); return 1
    arch = meta.get("general.architecture")
    print(f"{path}\n  gguf v{ver}  tensors={n_tensors}  kv={len(meta)}  arch={arch!r} "
          f"quant={meta.get(f'{arch}.quantization_version') or meta.get('general.quantization_version')}")
    for k, v in meta.items():
        if not filt or any(x in k for x in filt):
            s = str(v).replace("\n", "\\n")
            print(f"  {k} = {s[:200]}{'…' if len(s) > 200 else ''}")
    bad = [f"{k}={meta.get(k)!r} != {v!r}" for k, v in expects.items() if str(meta.get(k)) != v]
    for b in bad:
        print(f"MISMATCH {b}")
    print("META_OK" if not bad else "META_MISMATCH")
    return 1 if bad else 0


def _selftest():
    import tempfile, os
    kv = lambda k, t, v: (struct.pack("<Q", len(k)) + k.encode() + struct.pack("<I", t)
                          + (struct.pack("<Q", len(v)) + v.encode() if t == 8
                             else struct.pack("<I", v)))
    blob = (b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 42) + struct.pack("<Q", 2)
            + kv("general.architecture", 8, "spark2_5")   # 8 = STRING, 4 = U32 (spec)
            + kv("spark2_5.block_count", 4, 40))
    with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
        f.write(blob); p = f.name
    ver, nt, meta = read(p)
    assert (ver, nt) == (3, 42) and meta["general.architecture"] == "spark2_5", meta
    assert meta["spark2_5.block_count"] == 40
    open(p, "wb").write(b"NOPE")
    try:
        read(p); raise AssertionError("bad magic accepted")
    except ValueError:
        pass
    os.unlink(p)
    print("SELFTEST OK")
    return 0


if "--selftest" in sys.argv:
    sys.exit(_selftest())
if __name__ == "__main__":
    sys.exit(main())
