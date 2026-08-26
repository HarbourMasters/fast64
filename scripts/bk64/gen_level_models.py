"""Regenerate fast64_internal/hm64/bk64/bk64_level_models.py.

Usage:
    python scripts/bk64/gen_level_models.py <lighthouse-dir> <rom>
"""

import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ASSET_TABLE_OFF = 0x5E90
ASSET_DATA_OFF = 0x10CD0
BKMODEL_MAGIC = 0xB

OUT = Path(__file__).resolve().parents[2] / "fast64_internal" / "hm64" / "bk64" / "bk64_level_models.py"


def be32(data, offset):
    return struct.unpack_from(">I", data, offset)[0]


def parse_asset_enum(header: Path) -> dict:
    """asset_e as {value: name}. Members without an `= 0x...` continue from the last one."""
    body = re.search(r"enum\s+asset_e\s*\{(.*?)\n\}", header.read_text(encoding="utf-8", errors="replace"), re.S)
    if body is None:
        sys.exit("asset_e enum not found")

    values, nxt = {}, 0
    for line in body.group(1).splitlines():
        member = re.match(r"^(ASSET_[A-Za-z0-9_]+)\s*(?:=\s*(0x[0-9A-Fa-f]+|\d+))?\s*,?$", line.split("//")[0].strip())
        if member is None:
            continue
        value = int(member.group(2), 0) if member.group(2) else nxt
        values[value] = member.group(1)
        nxt = value + 1
    return values


def level_resources(o2r: Path) -> dict:
    """{asset index: name} for everything under assets/level/ in the o2r"""
    names = {}
    entry_re = re.compile(r"^assets/level/ASSET_([0-9A-Fa-f]+)_(.+)$")
    for entry in zipfile.ZipFile(o2r).namelist():
        found = entry_re.match(entry)
        if found:
            stem = re.sub(r"_(GEO|tex_\d+(_TLUT)?|ANIM|COLLISION)$", "", found.group(2))
            names[int(found.group(1), 16)] = stem
    return names


def decodes_as_model(rom: bytes, index: int) -> bool:
    """Asset `index` lives at table entry index + 1 - see the note in the generated file."""
    entry = ASSET_TABLE_OFF + (index + 1) * 8
    if entry + 12 > len(rom):
        return False
    start, end = ASSET_DATA_OFF + be32(rom, entry), ASSET_DATA_OFF + be32(rom, entry + 8)
    if not (0 < start <= end <= len(rom)) or end - start < 6:
        return False

    blob = rom[start:end]
    if blob[:2] == b"\x11\x72":
        size = be32(blob, 2)
        try:
            blob = zlib.decompressobj(-15).decompress(blob[6:], size)
        except zlib.error:
            return False
        if len(blob) != size:
            return False
    return len(blob) >= 4 and be32(blob, 0) == BKMODEL_MAGIC


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    lighthouse, rom_path = Path(sys.argv[1]), Path(sys.argv[2])

    rom = rom_path.read_bytes()
    enum_names = {
        value: name.split("_MODEL_", 1)[1]
        for value, name in parse_asset_enum(lighthouse / "include" / "enums.h").items()
        if "_MODEL_" in name
    }
    o2r_names = level_resources(lighthouse / "build" / "bk.o2r")

    rows, dropped = [], []
    for index in sorted(set(enum_names) & set(o2r_names)):
        if enum_names[index] != o2r_names[index]:
            dropped.append((index, "name disagrees with the o2r"))
            continue
        if not decodes_as_model(rom, index):
            dropped.append((index, "no BKModelBin in the ROM"))
            continue
        name = enum_names[index]
        layer = "OPA" if name.endswith("_OPA") else "XLU" if name.endswith("_XLU") else ""
        rows.append((index, name[:-4] if layer else name, layer))

    unnamed = sorted(set(o2r_names) - set(enum_names))
    table = "\n".join(f'    0x{index:04X}: ("{stem}", "{layer}"),' for index, stem, layer in rows)
    OUT.write_text(TEMPLATE.format(table=table), encoding="utf-8", newline="\n")

    print(f"wrote {OUT}")
    print(f"  {len(rows)} entries over {len({r[1] for r in rows})} levels")
    for index, why in dropped:
        print(f"  dropped 0x{index:04X}: {why}")
    for index in unnamed:
        print(f"  unnamed in enums.h, left out: 0x{index:04X} ({o2r_names[index]})")


TEMPLATE = '''BK64_LEVEL_MODELS = {{
{table}
}}


def bk64_level_layers(level: str) -> dict:
    """The asset index per draw layer, e.g. {{"OPA": 0x146B, "XLU": 0x146C}}"""
    return {{layer: index for index, (name, layer) in BK64_LEVEL_MODELS.items() if name == level}}


def bk64_level_names() -> list:
    """Every level name once, in asset order"""
    seen = {{}}
    for _, (name, _layer) in sorted(BK64_LEVEL_MODELS.items()):
        seen[name] = None
    return list(seen)
'''

if __name__ == "__main__":
    main()
