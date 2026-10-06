#!/usr/bin/env python3
"""Independent host arithmetic/bounds checks; not a DSP functional pass."""
import ctypes as C
from pathlib import Path
import random
import struct
import sys


class Buffer(C.Structure):
    _fields_ = [('pv', C.c_void_p), ('length', C.c_size_t)]


class Arg(C.Union):
    _fields_ = [('buffer', Buffer), ('handle64', C.c_uint64)]


entry = C.CDLL(str(Path(sys.argv[1]).resolve())).spx_workload_skel_invoke
entry.argtypes = [C.c_uint32, C.POINTER(Arg)]
entry.restype = C.c_int


def invoke(scalar, payloads, output_size, bad_length=None, null_input=False):
    # Deliberately unaligned payloads with canaries around the output.
    inputs = [C.create_string_buffer(b'!' + b + b'!') for b in payloads]
    output = C.create_string_buffer(b'!' + bytes([0xA5]) * output_size + b'!')
    args = (Arg * (len(inputs) + 1))()
    for i, (buf, data) in enumerate(zip(inputs, payloads)):
        args[i].buffer = Buffer(C.addressof(buf) + 1, len(data))
    args[-1].buffer = Buffer(C.addressof(output) + 1, output_size)
    if bad_length is not None:
        args[0].buffer.length = bad_length
    if null_input:
        args[0].buffer.pv = None
    status = entry(scalar, args)
    assert output.raw[0] == ord('!') and output.raw[output_size + 1] == ord('!')
    return status, output.raw[1:output_size + 1]


assert entry(0x10100, None) != 0
for a, b in ((0, 0), (1, 2), (0xFFFFFFFF, 1), (0x80000000, 0x80000000)):
    status, output = invoke(0x10100, [struct.pack('<II', a, b)], 4)
    assert status == 0 and struct.unpack('<I', output)[0] == (a + b) & 0xFFFFFFFF
vectors = [(list(range(64)), list(range(-32, 32))),
           ([-0x80000000] * 64, [-0x80000000] * 64),
           ([0x7FFFFFFF] * 64, [-0x80000000] * 64)]
rng = random.Random(0)
vectors += [([rng.randrange(-2**31, 2**31) for _ in range(64)],
             [rng.randrange(-2**31, 2**31) for _ in range(64)]) for _ in range(8)]
for a, b in vectors:
    status, output = invoke(0x1020100, [struct.pack('<64i', *a), struct.pack('<64i', *b)], 8)
    assert status == 0 and struct.unpack('<Q', output)[0] == sum(x*y for x, y in zip(a, b)) % 2**64
for scalar, bad, null in ((0x2010100, None, False), (0x10101, None, False),
                          (0x10100, 7, False), (0x10100, None, True)):
    status, output = invoke(scalar, [struct.pack('<II', 1, 2)], 4, bad, null)
    assert status != 0 and output == bytes([0xA5]) * 4
print('Host checks pass: wraparound arithmetic, 64-element vectors, unaligned buffers, rejection and canaries')
