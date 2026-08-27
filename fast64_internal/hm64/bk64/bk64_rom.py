from __future__ import annotations

import struct

from ...utility import PluginError
from .bk64_collision import write_collision_list
from .bk64_constants import (
    GEO_CMD_SKINNING,
    s16,
    BKMODEL_HEADER_SIZE,
    BKMODEL_MAGIC,
    GEO_BONE_BRANCH_OFFSET,
    GEO_BONE_PAIR_SIZE,
    GEO_CMD_BONE,
    GEO_CMD_CAMERA,
    GEO_CMD_LOADDL,
    GEO_CMD_NOP,
    GEO_CMD_REFPOINT,
    GEO_CMD_DRAWDIST,
    GEO_CMD_LOD,
    GEO_CMD_SELECTOR,
    GEO_CMD_SIZE,
    GEO_CMD_SORT,
    GEO_CMD_TEXWRAP,
    GEO_DRAWDIST_SIZE,
    GEO_LOD_SIZE,
    GEO_REFPOINT_SIZE,
    GEO_SORT_SIZE,
    MAX_LAYOUT_BONE,
)


def vertex_records(vertices, endian: str = "<"):
    """N64 Vtx records, 16 bytes each. Little endian for a resource, big endian for a ROM"""
    data = bytearray()
    for position, flag, uv, color in vertices:
        # wrap like Fast64, tiled UVs run past s10.5
        sign_u = 1 if uv[0] >= 0 else -1
        sign_v = 1 if uv[1] >= 0 else -1
        data.extend(
            struct.pack(
                endian + "hhhhhh",
                s16(position[0]),
                s16(position[1]),
                s16(position[2]),
                flag,
                uv[0] % (sign_u * 2**15),
                uv[1] % (sign_v * 2**15),
            )
        )
        data.extend(bytes(channel & 0xFF for channel in color))
    return bytes(data)


def _loaddl(gfx_index: int, next_offset: int, endian: str = "<"):
    return struct.pack(endian + "Iihxx", GEO_CMD_LOADDL, next_offset, gfx_index)


def _record_size(record):
    """Bytes a fixed size record takes, for finding the next one"""
    # anything carrying branches works its own size out and never gets here
    if record[0] == "bone":
        return GEO_BONE_PAIR_SIZE
    if record[0] == "refpoint":
        return GEO_REFPOINT_SIZE
    if record[0] == "skinning":
        return _skinning_size(record[1])
    return GEO_CMD_SIZE


def _skinning_size(indices):
    """cmd, next, then the gfx indices and a zero to stop on, padded to 4"""
    return GEO_CMD_SIZE - 4 + (len(indices) + 1) * 2 + (len(indices) + 1) % 2 * 2


def _camera_size(id_count):
    """cmd, next, the branch, a count and flags, then a byte an area id, padded to 8"""
    return -(-(15 + id_count) // 8) * 8


def _layout_bone(index: int) -> int:
    """The bone index a BONE command carries, read back by the game as an s8"""
    if index > MAX_LAYOUT_BONE:
        raise PluginError(
            f"Bone {index} in the table carries geometry, past the {MAX_LAYOUT_BONE} the geo "
            "layout can address. Set BK Bone Order so the bones that draw come first, or move "
            "its geometry onto an earlier bone."
        )
    return index


def geo_body(records, endian: str = "<"):
    # a selector keeps its branches right behind itself like vanilla, and its
    # next_offset steps over the whole subtree
    entries = records or [("nop",)]  # a branch that draws nothing is still a list
    body = bytearray()
    for index, record in enumerate(entries):
        last = index == len(entries) - 1
        kind = record[0]

        if kind == "selector":
            branches = [geo_body(branch, endian) for branch in record[2]]
            offsets, running = [], GEO_CMD_SIZE + 4 * len(branches)
            for branch in branches:
                offsets.append(running)
                running += len(branch)
            body.extend(
                struct.pack(endian + "Iihh", GEO_CMD_SELECTOR, 0 if last else running, len(branches), record[1])
            )
            for offset in offsets:
                body.extend(struct.pack(endian + "i", offset))
            for branch in branches:
                body.extend(branch)
            continue

        if kind == "lod":
            branch = geo_body(record[4], endian)
            body.extend(
                struct.pack(
                    endian + "Iifffffi",
                    GEO_CMD_LOD,
                    0 if last else GEO_LOD_SIZE + len(branch),
                    record[1],  # the far cutoff first, as geo_cmd_lod_s has it
                    record[2],
                    *record[3],
                    GEO_LOD_SIZE,
                )
            )
            body.extend(branch)
            continue

        if kind == "drawdist":
            branch = geo_body(record[3], endian)
            body.extend(
                struct.pack(
                    endian + "Iihhhhhhhxx",
                    GEO_CMD_DRAWDIST,
                    0 if last else GEO_DRAWDIST_SIZE + len(branch),
                    *(s16(value) for value in record[1]),
                    *(s16(value) for value in record[2]),
                    GEO_DRAWDIST_SIZE,
                )
            )
            body.extend(branch)
            continue

        if kind == "camera":
            branch = geo_body(record[3], endian)
            ids = bytes(record[1])
            header = _camera_size(len(ids))
            body.extend(
                struct.pack(
                    endian + "IihBB", GEO_CMD_CAMERA, 0 if last else header + len(branch), header, len(ids), record[2]
                )
            )
            body.extend(ids)
            body.extend(bytes(header - GEO_CMD_SIZE - len(ids)))
            body.extend(branch)
            continue

        if kind == "sort":
            first_branch = geo_body(record[3], endian)
            second_branch = geo_body(record[4], endian)
            body.extend(
                struct.pack(
                    endian + "Iiffffffhhi",
                    GEO_CMD_SORT,
                    0 if last else GEO_SORT_SIZE + len(first_branch) + len(second_branch),
                    *record[1],
                    *record[2],
                    record[5],
                    GEO_SORT_SIZE,
                    GEO_SORT_SIZE + len(first_branch),
                )
            )
            body.extend(first_branch)
            body.extend(second_branch)
            continue

        if kind == "bonebranch":
            branch = geo_body(record[2], endian)
            body.extend(
                struct.pack(
                    endian + "IiBbxx",
                    GEO_CMD_BONE,
                    0 if last else GEO_CMD_SIZE + len(branch),
                    GEO_CMD_SIZE,
                    _layout_bone(record[1]),
                )
            )
            body.extend(branch)
            continue

        next_offset = 0 if last else _record_size(record)
        if kind == "skinning":
            body.extend(struct.pack(endian + "Ii", GEO_CMD_SKINNING, next_offset))
            for gfx_index in list(record[1]) + [0]:
                body.extend(struct.pack(endian + "h", gfx_index))
            body.extend(bytes(_skinning_size(record[1]) - GEO_CMD_SIZE + 4 - (len(record[1]) + 1) * 2))
        elif kind == "bone":
            body.extend(
                struct.pack(
                    endian + "IiBbxx", GEO_CMD_BONE, next_offset, GEO_BONE_BRANCH_OFFSET, _layout_bone(record[1])
                )
            )
            body.extend(_loaddl(record[2], 0, endian))
        elif kind == "loaddl":
            body.extend(_loaddl(record[1], next_offset, endian))
        elif kind == "texwrap":
            body.extend(struct.pack(endian + "Iii", GEO_CMD_TEXWRAP, next_offset, record[1]))
        elif kind == "refpoint":
            body.extend(
                struct.pack(endian + "Iihhfff", GEO_CMD_REFPOINT, next_offset, record[1], record[2], *record[3])
            )
        else:
            body.extend(struct.pack(endian + "Iixxxx", GEO_CMD_NOP, next_offset))
    return bytes(body)


def collision_shapes(shapes, endian: str = "<"):
    """Counts, a cull radius, then the boxes, cylinders and spheres"""
    # rotations are bytes worth two degrees, and a sphere pads two where the
    # others pad one
    data = bytearray(
        struct.pack(
            endian + "4h", len(shapes["boxes"]), len(shapes["cylinders"]), len(shapes["spheres"]), shapes["cull"]
        )
    )
    for box in shapes["boxes"]:
        data.extend(
            struct.pack(
                endian + "3h3h3h3BBbx",
                *(s16(value) for value in box["low"]),
                *(s16(value) for value in box["high"]),
                *(s16(value) for value in box["position"]),
                *box["rotation"],
                box["code"] & 0xFF,
                box["bone"],
            )
        )
    for cylinder in shapes["cylinders"]:
        data.extend(
            struct.pack(
                endian + "hh3h3BBbx",
                s16(cylinder["radius"]),
                s16(cylinder["height"]),
                *(s16(value) for value in cylinder["position"]),
                *cylinder["rotation"],
                cylinder["code"] & 0xFF,
                cylinder["bone"],
            )
        )
    for sphere in shapes["spheres"]:
        data.extend(
            struct.pack(
                endian + "h3hBbxx",
                s16(sphere["radius"]),
                *(s16(value) for value in sphere["center"]),
                sphere["code"] & 0xFF,
                sphere["bone"],
            )
        )
    return bytes(data)


def mesh_list(meshes, endian: str = "<"):
    """A count, then each mesh's uid and the vertices it holds"""
    data = bytearray(struct.pack(endian + "h", len(meshes)))
    for mesh in meshes:
        data.extend(struct.pack(endian + "hH", mesh["uid"], len(mesh["vertices"])))
        for index in mesh["vertices"]:
            data.extend(struct.pack(endian + "h", index))
    return bytes(data)


def vertex_bone_map(entries, endian: str = "<", pad_header: bool = False):
    """A count, then each bound coordinate with its matrix and the vertices at it"""
    # the game runs the coordinate through the matrix once and writes the result
    # into every vertex listed
    data = bytearray(struct.pack(endian + "h", len(entries)))
    if pad_header:  # BKAnimVerticesList pads here, the resource stream doesn't
        data.extend(bytes(2))
    for entry in entries:
        data.extend(
            struct.pack(
                endian + "3hbB",
                *(s16(value) for value in entry["coord"]),
                entry["bone"],
                len(entry["vertices"]),
            )
        )
        for index in entry["vertices"]:
            data.extend(struct.pack(endian + "h", index))
    return bytes(data)


# the 0x38 BKModelBin header: a magic, then offsets into the file itself
BKMODEL_BIN_HEADER = ">IihhiiiiiiiiiHHf"
BKMODEL_BIN_FIELDS = (
    "magic",
    "geo",
    "texture",
    "geo_type",
    "gfx",
    "vtx",
    "unk14",
    "anim",
    "collision",
    "camera",
    "mesh_list",
    "anim_vertices",
    "animated_texture",
    "tri_count",
    "vertex_count",
    "unk34",
)


# the header fields that are values rather than offsets to a section
BKMODEL_BIN_VALUES = frozenset(("magic", "geo_type", "tri_count", "vertex_count", "unk34"))


def is_bkmodelbin(data: bytes) -> bool:
    return len(data) >= BKMODEL_HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == BKMODEL_MAGIC


def read_bkmodelbin_header(data: bytes) -> dict:
    """The header by name, its section offsets absolute within the file"""
    header = dict(zip(BKMODEL_BIN_FIELDS, struct.unpack_from(BKMODEL_BIN_HEADER, data, 0)))
    for name, offset in header.items():
        if name not in BKMODEL_BIN_VALUES and offset and not BKMODEL_HEADER_SIZE <= offset < len(data):
            raise PluginError(
                f"The {name} section starts at 0x{offset:X}, past the end of a {len(data)} byte file. "
                "This isn't a whole model binary."
            )
    return header


def layout_records(records, matrix_id=None, parent_id=None):
    """Every record of a layout tree, flattened in draw order.

    Yields (kind, chunk indices, matrix, parent, record). The parent is the
    enclosing bone's own enclosure, the matrix a POPMTX inside the chunk exposes.
    """
    for record in records:
        kind = record[0]
        if kind == "loaddl":
            yield kind, [record[1]], matrix_id, parent_id, record
        elif kind == "skinning":
            yield kind, list(record[1]), matrix_id, parent_id, record
        elif kind == "bonebranch":
            yield kind, [], record[1], matrix_id, record
            yield from layout_records(record[2], record[1], matrix_id)
        elif kind == "selector":
            yield kind, [], matrix_id, parent_id, record
            for option in record[2]:
                yield from layout_records(option, matrix_id, parent_id)
        elif kind == "sort":
            yield kind, [], matrix_id, parent_id, record
            yield from layout_records(record[3], matrix_id, parent_id)
            yield from layout_records(record[4], matrix_id, parent_id)
        elif kind in ("lod", "drawdist", "camera"):
            yield kind, [], matrix_id, parent_id, record
            yield from layout_records(record[-1], matrix_id, parent_id)
        else:
            yield kind, [], matrix_id, parent_id, record


def _pad8(data: bytearray):
    data.extend(bytes(-len(data) % 8))


def write_bkmodelbin(
    geo_type,
    tri_count,
    bounds,
    dl_words,
    records,
    bones,
    anim_scale,
    tex_infos,
    tex_blob,
    vertices,
    collision,
    shapes,
    bound_vertices,
    meshes,
    animated_slots,
    collision_grid_stored=None,
):
    """One BKModelBin, the ROM's own layout.

    Big endian, a 0x38 header of offsets into itself, then each section padded to 8.
    """
    out = bytearray(BKMODEL_HEADER_SIZE)

    # section order follows the ROM's own, geo layout last
    offsets = {}
    if tex_infos or tex_blob:
        _pad8(out)
        offsets["texture"] = len(out)
        out.extend(struct.pack(">iHH", len(tex_blob), len(tex_infos), 0))
        for info in tex_infos:
            out.extend(struct.pack(">ihxxBB", info["offset"], info["type"], info["width"], info["height"]))
            out.extend(bytes(6))
        out.extend(tex_blob)

    _pad8(out)
    offsets["gfx"] = len(out)
    out.extend(struct.pack(">II", len(dl_words), 0))
    for w0, w1 in dl_words:
        out.extend(struct.pack(">II", w0 & 0xFFFFFFFF, w1 & 0xFFFFFFFF))

    _pad8(out)
    offsets["vtx"] = len(out)
    out.extend(
        struct.pack(
            ">hhhhhhhhhhHh",
            *(s16(value) for value in bounds["min"]),
            *(s16(value) for value in bounds["max"]),
            *(s16(value) for value in bounds["center"]),
            s16(bounds["local_norm"]),
            bounds["count"],
            s16(bounds["global_norm"]),
        )
    )
    out.extend(vertex_records(vertices, ">"))

    if shapes:
        _pad8(out)
        offsets["unk14"] = len(out)
        out.extend(collision_shapes(shapes, ">"))

    if collision:
        _pad8(out)
        offsets["collision"] = len(out)
        # BKCollisionList counts its cells before the scale, the other way
        # round from _write_collision's stream
        out.extend(write_collision_list(collision, vertices, collision_grid_stored, ">"))

    if bones:
        _pad8(out)
        offsets["anim"] = len(out)
        out.extend(struct.pack(">fh", anim_scale, len(bones)))
        out.extend(bytes(2))
        for bone in bones:
            out.extend(struct.pack(">fffHH", *bone.position, bone.bone_id & 0xFFFF, bone.parent_index & 0xFFFF))

    if bound_vertices:
        _pad8(out)
        offsets["anim_vertices"] = len(out)
        out.extend(vertex_bone_map(bound_vertices, ">", pad_header=True))

    if meshes:
        _pad8(out)
        offsets["mesh_list"] = len(out)
        out.extend(mesh_list(meshes, ">"))

    if any(slot[0] for slot in animated_slots):
        _pad8(out)
        offsets["animated_texture"] = len(out)
        for frame_size, frame_count, rate in animated_slots:
            out.extend(struct.pack(">hhf", frame_size, frame_count, rate))

    _pad8(out)
    offsets["geo"] = len(out)
    out.extend(geo_body(records, ">"))

    if offsets.get("texture", 0) > 0x7FFF:
        raise PluginError("The texture section starts past 0x7FFF, as far as the header's s16 can point.")

    struct.pack_into(
        BKMODEL_BIN_HEADER,
        out,
        0,
        BKMODEL_MAGIC,
        offsets["geo"],
        offsets.get("texture", 0),
        geo_type,
        offsets["gfx"],
        offsets["vtx"],
        offsets.get("unk14", 0),
        offsets.get("anim", 0),
        offsets.get("collision", 0),
        0,  # camera areas
        offsets.get("mesh_list", 0),
        offsets.get("anim_vertices", 0),
        offsets.get("animated_texture", 0),
        tri_count,
        bounds["count"],
        0.0,  # unk34
    )
    return bytes(out)
