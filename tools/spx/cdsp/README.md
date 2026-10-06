# Offline CDSP workload preparation

This freestanding Hexagon v66 shared library provides a small deterministic
compute test. It has **not been deployed or invoked on CDSP**. A successful
build or host check does not close B07.

The two-argument dispatcher follows Qualcomm's public
[FastRPC argument/scalar ABI](https://github.com/qualcomm/fastrpc/blob/main/inc/remote.h)
and [skeleton entry convention](https://github.com/qualcomm/fastrpc/blob/main/src/apps_std_skel.c).
It exports `spx_workload_skel_invoke` and has no external runtime dependencies.

| Scalar | Inputs | Output |
|---|---|---|
| `0x00010100` | One buffer containing two little-endian uint32 values | Four-byte sum modulo 2^32 |
| `0x01020100` | Two buffers, each containing 64 little-endian int32 values | Eight-byte dot product modulo 2^64 |

Buffer lengths must match exactly. Null pointers and all other scalar values
return 1 without writing output; valid requests return 0. The transport must
supply the argument array described by the scalar and valid non-overlapping
buffer storage. This is an arithmetic dispatcher, not a validation boundary
for arbitrary untrusted memory addresses. Loader compatibility, process
creation, and a host FastRPC invocation client remain to be established.

## Reproduce without changing system packages

Use a clang/lld build with Hexagon v66 support. The local toolchain was
extracted privately from official Arch Linux ARM packages after verifying
each detached package signature with the installed trusted keyring.

```sh
cd tools/spx/cdsp
env LD_LIBRARY_PATH=/var/tmp/spx-hexagon-toolchain/usr/lib \
  make HEXAGON_CC=/var/tmp/spx-hexagon-toolchain/usr/bin/clang \
       HEXAGON_LD=/var/tmp/spx-hexagon-toolchain/usr/bin/ld.lld all check inspect
```

`OUT` defaults to `/var/tmp/spx-cdsp-workload`. `check` compares native C output
with independent Python arithmetic, including overflow, unaligned input,
rejection and output canaries. `inspect` shows the DSP ELF header, dynamic
symbols/dependencies and relocations. The initial result is ELF32 little
endian, DSP6, flags `0x66`, with the exported entry and no undefined symbols,
`DT_NEEDED` entries or relocations.

## Hardware prerequisite

The retained Surface INF/IORT establish CDSP stream IDs `0x1441..0x1448` and
hardware context-bank indices `0x21..0x28`. These are not Linux FastRPC `reg`
values. The Windows driver has a platform-specific flat-IOVA branch, whereas
Linux's default session encoding shifts `reg` by 32 bits. Resolve that
address contract and the firmware's process authorization before adding a
live session or attempting compute. See
[the bounded preparation result](../boot-diagnostics/RESULT-20261006cdsp.md).
