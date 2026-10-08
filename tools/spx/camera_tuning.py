# SPDX-License-Identifier: GPL-2.0-only
"""Read Surface QTI V1.3.2 colour coefficient candidates; never access hardware.

The format here is inferred from the fitted sensors' Windows blobs. Output
retains stage, profile, trigger and symbol provenance. It does not establish
RGB ordering, the active profile or the meaning of the trailing region bytes,
and is deliberately not a libcamera tuning file.
"""
import argparse
import json
import math
import struct
from pathlib import Path


class Tuning:
    def __init__(self, data):
        self.data = data
        if not data.startswith(b'QTI Chromatix Header\0') or len(data) < 0xe8:
            raise ValueError('not a Surface Chromatix blob')
        if b'Parameter Parser V1.3.2 ' not in data[0x28:0x98]:
            raise ValueError('unsupported parameter parser version')
        table, count = struct.unpack_from('<II', data, 0x98)
        if table != 0xa0 or count != 3:
            raise ValueError('unsupported section table')
        sections = {}
        for index in range(count):
            kind, offset, size = struct.unpack_from('<QQQ', data, table + index * 24)
            if kind in sections or offset < 0xe8 or offset + size > len(data):
                raise ValueError('invalid section bounds')
            sections[kind] = (offset, size)
        if set(sections) != {0, 1, 2}:
            raise ValueError('unsupported sections')
        intervals = sorted((off, off + size) for off, size in sections.values())
        if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
            raise ValueError('overlapping sections')
        self.base, payload_size = sections[1]
        table, size = sections[2]
        if size % 24:
            raise ValueError('invalid selector table size')
        self.selectors = {}
        for offset in range(table, table + size, 24):
            ident, word0, word1, parent = struct.unpack_from('<QIIQ', data, offset)
            if ident in self.selectors:
                raise ValueError('duplicate selector ID')
            self.selectors[ident] = dict(id=ident, word0=word0, word1=word1, parent=parent)
        table, size = sections[0]
        if size % 72:
            raise ValueError('invalid symbol table size')
        self.symbols = {}
        for offset in range(table, table + size, 72):
            ident, name, kind, profile, relative, length = struct.unpack_from(
                '<Q32sQQQQ', data, offset)
            name = name.split(b'\0', 1)[0].decode('ascii')
            if ident in self.symbols or relative + length > payload_size:
                raise ValueError('invalid symbol bounds or duplicate ID')
            self.symbols[ident] = dict(id=ident, name=name, kind=kind,
                                       profile=profile, offset=self.base + relative,
                                       length=length)

    def payload(self, ident, expected):
        symbol = self.symbols.get(ident)
        if symbol is None or symbol['name'] != expected:
            raise ValueError('unexpected colour-table reference: %s' % ident)
        offset = symbol['offset']
        return symbol, self.data[offset:offset + symbol['length']]

    def regions(self, ident, prefix, level, path):
        sizes = {'drc_gain': 32, 'hdr_aec': 64, 'led_idx': 24, 'aec': 48, 'cct': 72}
        levels = list(sizes)
        name = 'mod_%s_%s_data' % (prefix, level)
        symbol, data = self.payload(ident, name)
        record_size = sizes[level]
        if len(data) % record_size:
            raise ValueError('invalid %s region size' % level)
        result = []
        for index in range(len(data) // record_size):
            record = data[index * record_size:(index + 1) * record_size]
            if level == 'cct':
                triggers = [struct.unpack_from('<f', record, off)[0] for off in (0, 8)]
                coefficients = list(struct.unpack_from('<9f', record, 16))
                if not all(math.isfinite(v) for v in triggers + coefficients):
                    raise ValueError('non-finite colour coefficient or trigger')
                if triggers[0] > triggers[1]:
                    raise ValueError('reversed colour-temperature trigger')
                result.append(dict(path=path, symbol_id=ident, region=index,
                                   offset=symbol['offset'] + index * record_size,
                                   temperature_trigger=triggers,
                                   coefficients=coefficients,
                                   row_sums=[sum(coefficients[i:i + 3]) for i in (0, 3, 6)],
                                   region_tail_hex=record[52:].hex()))
            else:
                count, child = struct.unpack_from('<QQ', record, record_size - 16)
                next_level = levels[levels.index(level) + 1]
                _, child_data = self.payload(child, 'mod_%s_%s_data' % (prefix, next_level))
                if len(child_data) != count * sizes[next_level]:
                    raise ValueError('colour region count does not match referenced data')
                trigger_size = record_size - 16
                triggers = list(struct.unpack('<' + 'Q' * (trigger_size // 8), record[:trigger_size]))
                branch = dict(level=level, symbol_id=ident, region=index,
                              trigger_words=triggers)
                result.extend(self.regions(child, prefix, next_level, path + [branch]))
        return result

    def colour_modules(self):
        result = []
        for ident, symbol in self.symbols.items():
            if symbol['name'] not in {'cc12_ife', 'cc13_ipe', 'cc13_bps'}:
                continue
            _, data = self.payload(ident, symbol['name'])
            if len(data) != 144:
                raise ValueError('unsupported colour module layout')
            count, child = struct.unpack_from('<QQ', data, 128)
            prefix = symbol['name'].split('_')[0]
            _, child_data = self.payload(child, 'mod_%s_drc_gain_data' % prefix)
            if len(child_data) != count * 32:
                raise ValueError('invalid root region count')
            selector = symbol['profile']
            chain = []
            seen = set()
            while selector:
                if selector in seen or selector not in self.selectors:
                    raise ValueError('invalid selector reference chain')
                seen.add(selector)
                entry = self.selectors[selector]
                chain.append(entry)
                selector = entry['parent']
            result.append(dict(module=symbol['name'], symbol_id=ident,
                               profile=symbol['profile'],
                               selector_chain=chain,
                               header_words=list(struct.unpack('<18Q', data)),
                               regions=self.regions(child, prefix, 'drc_gain', [])))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('blob', type=Path)
    args = parser.parse_args()
    try:
        tuning = Tuning(args.blob.read_bytes())
        modules = tuning.colour_modules()
        if not modules:
            raise ValueError('no supported colour module found')
    except (OSError, UnicodeError, ValueError, struct.error) as error:
        parser.exit(1, 'camera tuning: %s\n' % error)
    print(json.dumps(dict(source=str(args.blob), schema='Surface Parameter Parser V1.3.2',
                          validated_for_processing=False, modules=modules), indent=2))


if __name__ == '__main__':
    main()
