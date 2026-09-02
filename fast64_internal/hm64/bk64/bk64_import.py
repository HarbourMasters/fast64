from __future__ import annotations

import json
import math
import os
import struct
import zlib

import bmesh
import bpy
import mathutils

from ...f3d.f3d_enums import combiner_enums
from ...f3d.f3d_gbi import VTX_SIZE
from ...f3d.f3d_material import (
    createF3DMat,
    update_node_values_of_material,
    update_tex_values_manual,
)
from ...utility import PluginError, gammaInverse, gammaInverseValue
from .bk64_constants import (
    BK_PALETTE_SIZE,
    BK_TEX_BITS,
    BK_TEX_TYPE,
    GEO_CMD_BONE,
    GEO_CMD_CALL,
    GEO_CMD_CAMERA,
    GEO_CMD_CULL,
    GEO_CMD_DRAWDIST,
    GEO_CMD_LOADDL,
    GEO_CMD_LOADDL2,
    GEO_CMD_LOD,
    GEO_CMD_REFPOINT,
    GEO_CMD_SELECTOR,
    GEO_CMD_SKINNING,
    GEO_CMD_SORT,
    GEO_CMD_TEXWRAP,
    GEO_CMD_UNK0,
    CAMERA_AREA_KIND,
    GEO_LAYOUT_PROP,
    SOURCE_CHUNK_ATTR,
    MIP_BASE_PROP,
    MIP_LOAD_TILE_INDEX,
    MIP_PYRAMID_PROP,
    MIP_PYRAMID_SIZE,
    BK64_DRAW_LAYER_ENTRY,
    COLLISION_GRID_PROP,
    OP_DL,
    OP_CLEARGEOMETRYMODE,
    OP_ENDDL,
    OP_SETCOMBINE,
    OP_SETENVCOLOR,
    OP_SETGEOMETRYMODE,
    OP_SETPRIMCOLOR,
    OP_SETTILE,
    OP_POPMTX,
    OP_SETTIMG,
    OP_TEXTURE,
    OP_TRI1,
    OP_TRI2,
    OP_VTX,
    ANIM_TEX_SLOT_COUNT,
    COLLISION_COLOR_ATTR,
    COLLISION_ONLY_PROP,
    COLLISION_UV_ATTR,
    GEO_MODE_FLAGS,
    GEO_MODE_START,
    MESH_GROUP_PREFIX,
    NATIVE_SIZE_PROP,
    OTEX_TYPE,
    OTR_TEXTURE_V1,
    PALETTED_FORMATS,
    TEX_FLAG_LOAD_AS_RAW,
    RENDERMODE_ENTRY_STRIDE,
    RT_BK_MODEL,
    SEG_RENDERMODE,
    SEG_TEX,
    SEG_ANIM_BASE,
    SEG_TEX_BLOB,
    SHAPE_KIND,
    SHAPE_PIVOT,
    TILE_BITS,
    tri_indices,
)
from .bk64_collision import (
    apply_surface,
    pack_collision_grid,
    read_bin_collision,
    read_collision,
    read_collision_shapes_data,
)
from .bk64_rom import is_bkmodelbin, layout_records, read_bkmodelbin_header, read_camera_area_list
from .bk64_skeleton import bone_space_matrix, create_armature_from_bones, read_bone_table

OTEX_FORMAT = {value: key for key, value in OTEX_TYPE.items()}
BK_TEX_FORMAT = {value: key for key, value in BK_TEX_TYPE.items()}

# the entry a chunk jumps into, back to the draw layer that writes it again
DRAW_LAYER_OF_ENTRY = {entry: layer for layer, entry in BK64_DRAW_LAYER_ENTRY.items() if entry is not None}

SHAPE_CODE = "hm64_bk64_hit_code"  # the hit code the export reads back off a volume


def _read_model(data: bytes):
    if len(data) < 0x40 or struct.unpack_from("<I", data, 4)[0] != RT_BK_MODEL:
        raise PluginError(
            "Not a BK model resource. Point this at the model itself, not a _GEO, _VTX or " "_tex sibling."
        )

    offset = 0x40
    geo_type, tri_count, _vert_count = struct.unpack_from("<HHH", data, offset)
    offset += 6
    _has_geo, has_vtx, has_dl = struct.unpack_from("<BBB", data, offset)
    offset += 3
    tex_count = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    flags = struct.unpack_from("<7B", data, offset)
    _has_anim, has_collision, has_shapes = flags[:3]
    offset += 7
    if has_vtx:
        offset += 24
    words = []
    if has_dl:
        dl_count = struct.unpack_from("<I", data, offset)[0]
        offset += 12
        words = [struct.unpack_from("<II", data, offset + index * 8) for index in range(dl_count)]
        offset += dl_count * 8
    tex_infos = []
    for index in range(tex_count):
        kind, width, height, _colors, tex_offset = struct.unpack_from("<HBBHI", data, offset + index * 10)
        tex_infos.append(dict(offset=tex_offset, type=kind, width=width, height=height))
    offset += tex_count * 10
    blob_size = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    blob = data[offset : offset + blob_size]

    offset += blob_size
    anim_scale, bones = read_bone_table(data)
    if bones:
        offset += 6 + len(bones) * 16

    collision, collision_grid, shapes = {}, None, None
    if has_collision:
        collision, collision_grid, offset = read_collision(data, offset)
    if has_shapes:
        shapes, offset = read_collision_shapes_data(data, offset)

    extra, offset = _read_rest(data, offset, flags[3:])
    if offset != len(data):
        raise PluginError(
            f"Read {offset} bytes of a {len(data)} byte model. Each section is found by stepping "
            "over the one before, so not landing on the end means something was misread."
        )

    return dict(
        geo_type=geo_type,
        tri_count=tri_count,
        has_mesh_list=bool(flags[4]),
        camera_areas=extra["camera_areas"],
        mesh_list=extra["mesh_list"],
        bound_vertices=extra["bound_vertices"],
        animated_textures=extra["animated_textures"],
        words=words,
        blob=blob,
        tex_infos=tex_infos,
        anim_scale=anim_scale,
        bones=bones,
        collision=collision,
        collision_grid=collision_grid,
        shapes=shapes,
    )


def _read_model_bin(data: bytes):
    """(model, vertices, layout, textures) from one BKModelBin.

    The header holds an offset to every section. Each is read where it points
    rather than by stepping over the one before it.
    """
    header = read_bkmodelbin_header(data)

    words = []
    if header["gfx"]:
        count = struct.unpack_from(">I", data, header["gfx"])[0]
        words = [struct.unpack_from(">II", data, header["gfx"] + 8 + index * 8) for index in range(count)]

    vertices = []
    if header["vtx"]:
        # a BKVertexList opens with the model's bounds, then the records
        vertices = _vertex_records(data, header["vtx"] + 24, header["vertex_count"], ">")

    tex_infos, blob = [], b""
    if header["texture"]:
        blob_size, count = struct.unpack_from(">iH", data, header["texture"])
        for index in range(count):
            offset, kind, width, height = struct.unpack_from(">ihxxBB", data, header["texture"] + 8 + index * 16)
            tex_infos.append(dict(offset=offset, type=kind, width=width, height=height))
        blob_at = header["texture"] + 8 + count * 16
        blob = data[blob_at : blob_at + blob_size]

    anim_scale, bones = read_bone_table(data)
    bin_collision = read_bin_collision(data, header["collision"]) if header["collision"] else ({}, None)
    model = dict(
        geo_type=header["geo_type"],
        tri_count=header["tri_count"],
        has_mesh_list=bool(header["mesh_list"]),
        camera_areas=read_camera_area_list(data, header["camera"], ">", True) if header["camera"] else [],
        mesh_list=_read_mesh_list(data, header["mesh_list"], ">")[0] if header["mesh_list"] else [],
        bound_vertices=(
            _read_bound_vertices(data, header["anim_vertices"], ">", True)[0] if header["anim_vertices"] else []
        ),
        animated_textures=(
            _read_animated_textures(data, header["animated_texture"], ">") if header["animated_texture"] else []
        ),
        words=words,
        blob=blob,
        tex_infos=tex_infos,
        anim_scale=anim_scale,
        bones=bones,
        collision=bin_collision[0],
        collision_grid=bin_collision[1],
        shapes=read_collision_shapes_data(data, header["unk14"], ">")[0] if header["unk14"] else None,
    )
    # the layout is written last and runs to the end of the file
    return (
        model,
        vertices,
        read_geo_body(data[header["geo"] :], ">"),
        _blob_textures(_retype_ci_from_tiles(words, tex_infos)),
    )


def _read_mesh_list(data: bytes, offset: int, endian: str = "<"):
    """([{uid, vertices}], where the section ends).

    meshList_getMesh matches on the uid, so a mesh's place in the list means nothing.
    """
    count = struct.unpack_from(endian + "H", data, offset)[0]
    offset += 2
    meshes = []
    for _mesh in range(count):
        uid, vertex_count = struct.unpack_from(endian + "hH", data, offset)
        offset += 4
        meshes.append(dict(uid=uid, vertices=list(struct.unpack_from(endian + f"{vertex_count}h", data, offset))))
        offset += vertex_count * 2
    return meshes, offset


def _read_bound_vertices(data: bytes, offset: int, endian: str = "<", pad_header: bool = False):
    """([{coord, bone, vertices}], where the section ends).

    Each coordinate goes through its matrix once, into every vertex it lists.
    """
    count = struct.unpack_from(endian + "h", data, offset)[0]
    offset += 4 if pad_header else 2  # BKAnimVerticesList pads, the resource stream doesn't
    entries = []
    for _entry in range(count):
        # the count is a u8. Read signed and a run over 127 walks the stream backwards.
        x, y, z, bone, vertex_count = struct.unpack_from(endian + "3hbB", data, offset)
        offset += 8
        entries.append(
            dict(
                coord=(x, y, z),
                bone=bone,
                vertices=list(struct.unpack_from(endian + f"{vertex_count}h", data, offset)),
            )
        )
        offset += vertex_count * 2
    return entries, offset


def _read_animated_textures(data: bytes, offset: int, endian: str):
    """One (frame_size, frame_count, rate) per slot, s16 s16 f32 each"""
    return [struct.unpack_from(endian + "hhf", data, offset + slot * 8) for slot in range(ANIM_TEX_SLOT_COUNT)]


def _read_rest(data: bytes, offset: int, flags):
    """(the sections that follow the shapes, where the stream ends)"""
    # landing on the exact end is the only check that the earlier sections were
    # found right. Every one is stepped whether or not it's kept.
    has_camera_areas, has_mesh_list, has_bound_vertices, has_animated_textures = flags
    extra = dict(mesh_list=[], bound_vertices=[], animated_textures=[], camera_areas=[])
    if has_camera_areas:
        extra["camera_areas"] = read_camera_area_list(data, offset)
        offset += 1 + struct.unpack_from("<B", data, offset)[0] * 14
    if has_mesh_list:
        extra["mesh_list"], offset = _read_mesh_list(data, offset)
    if has_bound_vertices:
        extra["bound_vertices"], offset = _read_bound_vertices(data, offset)
    if has_animated_textures:
        extra["animated_textures"] = _read_animated_textures(data, offset, "<")
        offset += ANIM_TEX_SLOT_COUNT * 8  # four slots, always written
    return extra, offset


def _shape_matrix(position, rotation):
    # the game inverts this to push a query into the shape's space, and the shape
    # itself turns roll, pitch, yaw. Each byte is worth two degrees.
    angles = mathutils.Euler([math.radians(value * 2) for value in (rotation[0], rotation[1], rotation[2])], "YXZ")
    pivot = mathutils.Vector(position)
    return mathutils.Matrix.Translation(pivot) @ angles.to_matrix().to_4x4() @ mathutils.Matrix.Translation(-pivot)


def _mux(case: str, value: int):
    """The name a combiner slot's value stands for"""
    # every slot's list ends in 0, and a value past the end means the same
    names = [item[0] for item in combiner_enums[case]]
    return names[min(value, len(names) - 1)]


def _apply_combiner(f3d_mat, words):
    w0, w1 = words

    cycle = f3d_mat.combiner1
    cycle.A, cycle.B = _mux("Case A", (w0 >> 20) & 0xF), _mux("Case B", (w1 >> 28) & 0xF)
    cycle.C, cycle.D = _mux("Case C", (w0 >> 15) & 0x1F), _mux("Case D", (w1 >> 15) & 7)
    cycle.A_alpha = _mux("Case A Alpha", (w0 >> 12) & 7)
    cycle.B_alpha = _mux("Case B Alpha", (w1 >> 12) & 7)
    cycle.C_alpha = _mux("Case C Alpha", (w0 >> 9) & 7)
    cycle.D_alpha = _mux("Case D Alpha", (w1 >> 9) & 7)

    cycle = f3d_mat.combiner2
    cycle.A, cycle.B = _mux("Case A", (w0 >> 5) & 0xF), _mux("Case B", (w1 >> 24) & 0xF)
    cycle.C, cycle.D = _mux("Case C", w0 & 0x1F), _mux("Case D", (w1 >> 6) & 7)
    cycle.A_alpha = _mux("Case A Alpha", (w1 >> 21) & 7)
    cycle.B_alpha = _mux("Case B Alpha", (w1 >> 3) & 7)
    cycle.C_alpha = _mux("Case C Alpha", (w1 >> 18) & 7)
    cycle.D_alpha = _mux("Case D Alpha", w1 & 7)


def _apply_tile(f3d_mat, w1):
    # a third of vanilla's tiles clamp, and importing them as wrap shows up as
    # smears across a surface
    for field, clamp_shift, mask_shift, shift_shift in (
        (f3d_mat.tex0.S, 8, 4, 0),
        (f3d_mat.tex0.T, 18, 14, 10),
    ):
        mode = (w1 >> clamp_shift) & 3
        field.clamp = bool(mode & 2)
        field.mirror = bool(mode & 1)
        field.mask = (w1 >> mask_shift) & 0xF
        field.shift = (w1 >> shift_shift) & 0xF


def _vertex_records(data: bytes, offset: int, count: int, endian: str):
    vertices = []
    for index in range(count):
        at = offset + index * VTX_SIZE
        x, y, z, _flag, u, v = struct.unpack_from(endian + "hhhhhh", data, at)
        color = struct.unpack_from(endian + "BBBB", data, at + 12)
        vertices.append(((x, y, z), (u, v), color))
    return vertices


def _read_vertices(data: bytes):
    return _vertex_records(data, 0x44, struct.unpack_from("<I", data, 0x40)[0], "<")


GEO_KIND_NAMES = {
    "sort": "Sort",
    "skinning": "Skinning",
    "lod": "Level Of Detail",
    "selector": "Selector",
    "drawdist": "Draw Distance",
    "camera": "Camera Area",
}


def read_geo_body(body: bytes, endian: str = "<"):
    """The layout as records geo_body can write again, holding the original gfx indices.

    Keeping the tree itself, rather than deriving one from the bone table, is
    what lets selectors, sorts and skinning survive a round trip.
    """
    visited = set()

    def branch(pos, offset):
        if offset and 0 <= pos + offset < len(body) and (pos + offset) not in visited:
            return walk(pos + offset)
        return []

    def walk(pos):
        records = []
        guard = 0
        while 0 <= pos < len(body) and guard < 4096:
            if pos in visited:
                break
            visited.add(pos)
            guard += 1
            cmd, next_offset = struct.unpack_from(endian + "Ii", body, pos)

            if cmd == GEO_CMD_BONE:
                offset, own = struct.unpack_from(endian + "Bb", body, pos + 8)
                records.append(("bonebranch", own, branch(pos, offset)))
            elif cmd == GEO_CMD_LOADDL:
                records.append(("loaddl", struct.unpack_from(endian + "h", body, pos + 8)[0]))
            elif cmd == GEO_CMD_LOADDL2:
                records.append(("loaddl", struct.unpack_from(endian + "h", body, pos + 10)[0]))
            elif cmd == GEO_CMD_SKINNING:
                at, first, indices = pos + 8, True, []
                limit = min(pos + next_offset if next_offset else len(body), len(body))
                while at + 2 <= limit:
                    gfx_index = struct.unpack_from(endian + "h", body, at)[0]
                    if gfx_index == 0 and not first:
                        break
                    indices.append(gfx_index)
                    at, first = at + 2, False
                records.append(("skinning", indices))
            elif cmd == GEO_CMD_SELECTOR:
                count, index = struct.unpack_from(endian + "hh", body, pos + 8)
                options = [
                    branch(pos, struct.unpack_from(endian + "i", body, pos + 12 + 4 * i)[0]) for i in range(count)
                ]
                records.append(("selector", index, options))
            elif cmd == GEO_CMD_SORT:
                first_half = branch(pos, struct.unpack_from(endian + "h", body, pos + 0x22)[0])
                second_half = branch(pos, struct.unpack_from(endian + "i", body, pos + 0x24)[0])
                point_a = struct.unpack_from(endian + "3f", body, pos + 8)
                point_b = struct.unpack_from(endian + "3f", body, pos + 20)
                flags = struct.unpack_from(endian + "h", body, pos + 0x20)[0]
                records.append(("sort", point_a, point_b, first_half, second_half, flags))
            elif cmd == GEO_CMD_LOD:
                far, near = struct.unpack_from(endian + "ff", body, pos + 8)
                point = struct.unpack_from(endian + "3f", body, pos + 16)
                records.append(
                    ("lod", far, near, point, branch(pos, struct.unpack_from(endian + "i", body, pos + 0x1C)[0]))
                )
            elif cmd == GEO_CMD_DRAWDIST:
                low = struct.unpack_from(endian + "3h", body, pos + 8)
                high = struct.unpack_from(endian + "3h", body, pos + 14)
                records.append(
                    ("drawdist", low, high, branch(pos, struct.unpack_from(endian + "h", body, pos + 0x14)[0]))
                )
            elif cmd == GEO_CMD_REFPOINT:
                index, matrix = struct.unpack_from(endian + "hh", body, pos + 8)
                point = struct.unpack_from(endian + "3f", body, pos + 12)
                records.append(("refpoint", index, matrix, point))
            elif cmd == GEO_CMD_CAMERA:
                # a level hangs most of its geometry off these. Missing the
                # branch costs nearly the whole model, not just the culling.
                offset, count, flags = struct.unpack_from(endian + "hBB", body, pos + 8)
                ids = list(struct.unpack_from(endian + f"{count}B", body, pos + 12)) if count else []
                records.append(("camera", ids, flags, branch(pos, offset)))
            elif cmd == GEO_CMD_TEXWRAP:
                records.append(("texwrap", struct.unpack_from(endian + "i", body, pos + 8)[0]))
            elif cmd in (GEO_CMD_UNK0, GEO_CMD_CALL):
                offset_field = endian + ("h" if cmd == GEO_CMD_UNK0 else "i")
                records += branch(pos, struct.unpack_from(offset_field, body, pos + 8)[0])
            elif cmd == GEO_CMD_CULL:
                # only a visibility test around what it holds. Keeping the
                # branch and dropping the sphere costs culling, not geometry.
                records += branch(pos, struct.unpack_from(endian + "h", body, pos + 0x10)[0])

            if next_offset == 0:
                break
            pos += next_offset
        return records

    return walk(0)


def read_geo_tree(data: bytes):
    size = struct.unpack_from("<I", data, 0x40)[0]
    return read_geo_body(data[0x44 : 0x44 + size])


def layout_chunks(records, used=None):
    """(matrix, parent, gfx index) per chunk, in the order the layout draws them"""
    chunks = []
    for kind, indices, matrix, parent, _record in layout_records(records):
        if used is not None and kind in GEO_KIND_NAMES:
            used.add(GEO_KIND_NAMES[kind])
        for index in indices:
            chunks.append((matrix, parent, index))
    return chunks


def _decode(pixels: bytes, otex_format: str, width: int, height: int, palette: bytes):
    """N64 pixels as Blender wants them: RGBA floats, bottom row first"""

    def rgba16(value):
        return (
            ((value >> 11) & 31) / 31.0,
            ((value >> 6) & 31) / 31.0,
            ((value >> 1) & 31) / 31.0,
            float(value & 1),
        )

    colors = []
    if otex_format in PALETTED_FORMATS:
        entries = [rgba16(struct.unpack_from(">H", palette, index * 2)[0]) for index in range(len(palette) // 2)]
        for index in range(width * height):
            if otex_format == "CI4":
                byte = pixels[index // 2] if index // 2 < len(pixels) else 0
                entry = (byte >> 4) if index % 2 == 0 else (byte & 0xF)
            else:
                entry = pixels[index] if index < len(pixels) else 0
            colors.append(entries[entry] if entry < len(entries) else (1.0, 0.0, 1.0, 1.0))
    elif otex_format == "RGBA16":
        for index in range(width * height):
            colors.append(rgba16(struct.unpack_from(">H", pixels, index * 2)[0]))
    elif otex_format == "RGBA32":
        for index in range(width * height):
            r, g, b, a = struct.unpack_from(">BBBB", pixels, index * 4)
            colors.append((r / 255.0, g / 255.0, b / 255.0, a / 255.0))
    elif otex_format in ("I4", "I8", "IA4", "IA8", "IA16"):
        for index in range(width * height):
            if otex_format == "I4":
                nibble = (pixels[index // 2] >> 4) if index % 2 == 0 else (pixels[index // 2] & 0xF)
                gray, alpha = nibble / 15.0, 1.0
            elif otex_format == "I8":
                gray, alpha = pixels[index] / 255.0, 1.0
            elif otex_format == "IA4":
                nibble = (pixels[index // 2] >> 4) if index % 2 == 0 else (pixels[index // 2] & 0xF)
                gray, alpha = (nibble >> 1) / 7.0, float(nibble & 1)
            elif otex_format == "IA8":
                byte = pixels[index]
                gray, alpha = (byte >> 4) / 15.0, (byte & 0xF) / 15.0
            else:
                value = struct.unpack_from(">H", pixels, index * 2)[0]
                gray, alpha = (value >> 8) / 255.0, (value & 0xFF) / 255.0
            colors.append((gray, gray, gray, alpha))
    else:
        raise PluginError(f"Texture format {otex_format} can't be read back.")

    flat = []
    for row in range(height - 1, -1, -1):  # Blender starts at the bottom row
        for column in range(width):
            flat.extend(colors[row * width + column])
    return flat


def _decode_raw(pixels: bytes, width: int, height: int):
    """RGBA8 as Blender wants it, bottom row first"""
    flat = []
    for row in range(height - 1, -1, -1):
        start = row * width * 4
        for value in pixels[start : start + width * 4]:
            flat.append(value / 255.0)
    return flat


def _keep_pyramid(image, data: bytes, at: int, size: int):
    """Stash the mip levels a texture arrived with, for export to write back"""
    pyramid = data[at + size : at + size + MIP_PYRAMID_SIZE]
    if len(pyramid) < MIP_PYRAMID_SIZE:
        return
    image[MIP_PYRAMID_PROP] = pyramid.hex()
    image[MIP_BASE_PROP] = f"{zlib.crc32(data[at : at + size]):08x}"


def _load_textures(folder: str, base: str, blob: bytes, palettes, used, mip_used=()):
    images = {}
    index = 0
    while True:
        path = os.path.join(folder, f"{base}_tex_{index}")
        if not os.path.exists(path):
            break
        with open(path, "rb") as file:
            data = file.read()
        version = struct.unpack_from("<I", data, 8)[0]
        if version == OTR_TEXTURE_V1:
            kind, width, height, flags, h_scale, v_scale, size = struct.unpack_from("<IIIIffI", data, 0x40)
            pixels_at = 0x40 + 28
        else:
            kind, width, height, size = struct.unpack_from("<IIII", data, 0x40)
            flags, h_scale, v_scale, pixels_at = 0, 1.0, 1.0, 0x50
        otex_format = OTEX_FORMAT.get(kind)
        if otex_format is None:
            raise PluginError(f"'{os.path.basename(path)}' has texture type {kind}, which BK doesn't use.")

        palette = b""
        if otex_format in PALETTED_FORMATS:
            offset = palettes.get(index)
            if offset is None:
                if index not in used:
                    # a sibling no face samples, with no palette to find
                    # and nothing to miss it
                    index += 1
                    continue
                raise PluginError(
                    f"'{os.path.basename(path)}' is {otex_format} but nothing in the display list "
                    "loads a palette for it."
                )
            palette = blob[offset : offset + BK_PALETTE_SIZE[otex_format]]

        if flags & TEX_FLAG_LOAD_AS_RAW:
            # width and height are the sizes the display list tiles, not the
            # sizes of the RGBA8 behind them
            real_height = max(1, round(height * v_scale))
            real_width = max(1, (size // 4) // real_height)
            image = bpy.data.images.new(f"{base}_tex_{index}", real_width, real_height, alpha=True)
            image.pixels = _decode_raw(data[pixels_at : pixels_at + size], real_width, real_height)
            # the slot carries it, and no material exists yet to put it on
            image[NATIVE_SIZE_PROP] = (width, height)
        else:
            image = bpy.data.images.new(f"{base}_tex_{index}", width, height, alpha=True)
            base_size = width * height * BK_TEX_BITS[otex_format] // 8
            image.pixels = _decode(data[pixels_at : pixels_at + base_size], otex_format, width, height, palette)
            if index in mip_used:
                _keep_pyramid(image, data, pixels_at, base_size)
        image.pack()
        images[index] = (image, otex_format)
        index += 1
    return images


def _retype_ci_from_tiles(words, tex_infos):
    """tex_infos, with each CI entry's type taken from the tile its image draws from"""
    drawn_bits, bound = {}, None
    for w0, w1 in words:
        if (w0 >> 24) == OP_SETTIMG and (w1 >> 24) == SEG_TEX_BLOB:
            bound = w1 & 0xFFFFFF
        elif (w0 >> 24) == OP_SETTILE and (w1 >> 24) == 0 and bound is not None:
            drawn_bits[bound] = TILE_BITS[(w0 >> 19) & 3]
            bound = None

    for info in tex_infos:
        if BK_TEX_FORMAT.get(info["type"]) not in PALETTED_FORMATS:
            continue
        for otex_format in ("CI4", "CI8"):
            # the offset and the depth both have to land, so one alone can't retype
            image = info["offset"] + BK_PALETTE_SIZE[otex_format]
            if drawn_bits.get(image) == BK_TEX_BITS[otex_format]:
                info["type"] = BK_TEX_TYPE[otex_format]
                break
    return tex_infos


def _blob_textures(tex_infos):
    """Each texture's format, size, and where its palette and image start.

    A paletted texture's info points at its palette and the image follows it.
    The display list binds that second offset.
    """
    textures = []
    for index, info in enumerate(tex_infos):
        otex_format = BK_TEX_FORMAT.get(info["type"])
        if otex_format is None:
            raise PluginError(
                f"Texture {index} is type 0x{info['type']:X}, which is none of BK's. Tooie models land "
                "here, since their texture entries are 8 bytes and lead with the offset, not the type."
            )
        palette = BK_PALETTE_SIZE[otex_format] if otex_format in PALETTED_FORMATS else 0
        textures.append(
            dict(
                format=otex_format,
                width=info["width"],
                height=info["height"],
                palette=info["offset"],
                image=info["offset"] + palette,
                size=info["width"] * info["height"] * BK_TEX_BITS[otex_format] // 8,
            )
        )
    return textures


def _load_blob_textures(base: str, blob: bytes, textures, mip_used=()):
    images = {}
    for index, texture in enumerate(textures):
        otex_format, width, height = texture["format"], texture["width"], texture["height"]
        at = texture["image"]
        palette = blob[texture["palette"] : at]  # empty unless one sits ahead of the image

        image = bpy.data.images.new(f"{base}_tex_{index}", width, height, alpha=True)
        image.pixels = _decode(blob[at : at + texture["size"]], otex_format, width, height, palette)
        if index in mip_used:
            _keep_pyramid(image, blob, at, texture["size"])
        image.pack()
        images[index] = (image, otex_format)
    return images


def _load_animated_frames(base: str, model, binds, images):
    """{slot: (frames, rate)}, and each slot's frame 0 goes into images too.

    A slot's frames sit end to end inside one texture list entry declared tall
    enough for all of them. The display list tiles the first and the game slides
    the segment on by frame_size for each one after it.
    """
    frames, blob = {}, model["blob"]
    for slot, offset in sorted(binds.items()):
        if slot >= len(model["animated_textures"]):
            continue
        frame_size, frame_count, rate = model["animated_textures"][slot]
        if frame_size <= 0 or frame_count <= 0:
            continue  # the segment is bound with no slot driving it. It holds still

        info = next((entry for entry in model["tex_infos"] if entry["offset"] == offset), None)
        if info is None or not info["width"]:
            raise PluginError(
                f"Slot {slot} binds offset {offset:#x}, which no texture in '{base}' starts at. The "
                "model's texture list and its animated textures disagree."
            )
        otex_format = BK_TEX_FORMAT.get(info["type"])
        if otex_format is None:
            raise PluginError(f"Animated texture in '{base}' is type {info['type']}, which has no BK format.")

        # a CI frame's palette rides ahead of its image, sliding along with it
        pal_size = BK_PALETTE_SIZE.get(otex_format, 0)
        expected = pal_size + info["width"] * info["height"] * BK_TEX_BITS[otex_format] // 8
        if pal_size and expected != frame_size:
            # Don't trust the header, test the stride
            for candidate in ("CI4", "CI8"):
                c_pal = BK_PALETTE_SIZE[candidate]
                c_bytes = info["width"] * info["height"] * BK_TEX_BITS[candidate] // 8
                if c_pal + c_bytes == frame_size:
                    otex_format, pal_size = candidate, c_pal
                    break
        rows = (frame_size - pal_size) * 8 // (info["width"] * BK_TEX_BITS[otex_format])
        built = []
        for index in range(frame_count):
            at = offset + index * frame_size
            image = bpy.data.images.new(f"{base}_anim{slot}_{index}", info["width"], rows, alpha=True)
            image.pixels = _decode(
                blob[at + pal_size : at + frame_size], otex_format, info["width"], rows, blob[at : at + pal_size]
            )
            image.pack()
            built.append(image)

        images[("anim", slot)] = (built[0], otex_format)
        frames[slot] = (built, rate)
    return frames


def new_walk_state():
    return {
        "cache": {},
        "palettes": {},
        "blob_images": {},
        "anim_binds": {},
        "texture": None,
        "palette": None,
        "tile": None,
        "combine": None,
        "rendermode": None,
        "prim": None,
        "env": None,
        "geomode": GEO_MODE_START,
        "texlevel": None,
        "mip_tile": None,
        "mip_textures": set(),
        "vertex_owner": {},
        "chunk_owner": None,
        "chunk_parent": None,
        "texscale": None,
        "dropped": 0,
    }


def _walk_display_list(words, start: int, state):
    """Triangles of one chunk as (vertex indices, texture index)"""
    # state carries between chunks like on the RSP, and a SKINNING chunk indexes
    # vertices it never loaded
    faces = []
    cache, palettes = state["cache"], state["palettes"]
    position = start
    # a vertex belongs to the matrix it was loaded under, and a POPMTX mid
    # chunk exposes the parent's, which is how a seam vertex follows the parent
    current_owner = state["chunk_owner"]

    def emit(word):
        indices = tri_indices(word, cache)
        if indices is None:
            state["dropped"] += 1  # a slot nothing has loaded yet
            return
        mipmapped = state["texlevel"] is not None and state["texlevel"][0] > 0
        if mipmapped and isinstance(state["texture"], int):
            state["mip_textures"].add(state["texture"])
        faces.append(
            (
                indices,
                (
                    state["texture"],
                    state["mip_tile"] if mipmapped and state["mip_tile"] else state["tile"],
                    state["combine"],
                    state["rendermode"],
                    state["prim"],
                    state["env"],
                    state["geomode"],
                    state["texscale"],
                    state["texlevel"],
                ),
            )
        )

    while position < len(words):
        w0, w1 = words[position]
        opcode = (w0 >> 24) & 0xFF
        if opcode == OP_ENDDL:
            break
        if opcode == OP_VTX:
            first = ((w0 >> 16) & 0xFF) // 2
            count = (w0 & 0xFFFF) >> 10
            base = (w1 & 0xFFFFFF) // VTX_SIZE
            for step in range(count):
                cache[first + step] = base + step
                state["vertex_owner"][base + step] = current_owner
        elif opcode == OP_SETTIMG:
            segment, value = w1 >> 24, w1 & 0x00FFFFFF
            state["mip_tile"] = None
            if segment == SEG_TEX:
                state["texture"] = value
                if state["palette"] is not None:
                    palettes.setdefault(value, state["palette"])
            elif SEG_ANIM_BASE - ANIM_TEX_SLOT_COUNT < segment <= SEG_ANIM_BASE:
                # an animated texture is bound by segment, and the game slides
                # that segment along the blob a frame at a time
                slot = SEG_ANIM_BASE - segment
                state["texture"] = ("anim", slot)
                state["anim_binds"].setdefault(slot, value)
            elif segment == SEG_TEX_BLOB:
                # a .bin keeps its images in the blob too. An offset a
                # texture starts at is a bind and anything else a palette.
                index = state["blob_images"].get(value)
                if index is None:
                    state["palette"] = value
                    # vanilla sends a palette before the image it belongs to and
                    # Fast64 sends it after, and a tool nobody has seen may do
                    # either. Pair them up whichever way round they arrive.
                    if state["texture"] is not None:
                        palettes.setdefault(state["texture"], value)
                else:
                    state["texture"] = index
        elif opcode == OP_SETTILE:
            if (w1 >> 24) == 0:
                state["tile"] = w1
            elif (w1 >> 24) == MIP_LOAD_TILE_INDEX:
                state["mip_tile"] = w1
        elif opcode == OP_SETCOMBINE:
            state["combine"] = (w0 & 0xFFFFFF, w1)
        elif opcode == OP_SETGEOMETRYMODE:
            state["geomode"] |= w1
        elif opcode == OP_CLEARGEOMETRYMODE:
            state["geomode"] &= ~w1 & 0xFFFFFFFF
        elif opcode == OP_TEXTURE:
            # the scale the RSP multiplies UVs by, which vanilla often halves,
            # and the mip level and tile a mipmapped chunk renders from
            state["texscale"] = (w1 >> 16 & 0xFFFF, w1 & 0xFFFF)
            state["texlevel"] = ((w0 >> 11) & 7, (w0 >> 8) & 7, w0 & 0xFF)
        elif opcode == OP_SETPRIMCOLOR:
            # a flat color combiner takes its color from here, not a texture
            state["prim"] = (w1 >> 24 & 0xFF, w1 >> 16 & 0xFF, w1 >> 8 & 0xFF, w1 & 0xFF, w0 >> 8 & 0xFF, w0 & 0xFF)
        elif opcode == OP_SETENVCOLOR:
            state["env"] = (w1 >> 24 & 0xFF, w1 >> 16 & 0xFF, w1 >> 8 & 0xFF, w1 & 0xFF)
        elif opcode == OP_DL and (w1 >> 24) == SEG_RENDERMODE:
            # a chunk picks its render mode by jumping into the game's table, and
            # one that never jumps keeps whatever the chunk before it left
            state["rendermode"] = (w1 & 0xFFFFFF) // RENDERMODE_ENTRY_STRIDE
        elif opcode == OP_POPMTX:
            current_owner = state["chunk_parent"]
        elif opcode == OP_TRI1:
            emit(w1)
        elif opcode == OP_TRI2:
            emit(w0 & 0xFFFFFF)
            emit(w1)
        position += 1
    return faces


def _material_from_preset(mesh_obj, preset: str, prototypes: dict):
    """A material on the preset, copied from the first one built on it"""
    # createF3DMat reopens the node library and re-runs the preset script every
    # call, and a model can carry hundreds of draw states
    proto = prototypes.get(preset)
    if proto is None:
        material = createF3DMat(mesh_obj, preset=preset)
        keeper = material.copy()  # before the caller writes a draw state onto it
        keeper.use_fake_user = True
        prototypes[preset] = keeper
        return material

    material = proto.copy()
    # the first material through brought the color attributes with it
    mesh_obj.data.materials.append(material)
    return material


def _report_progress(window, status, base: str):
    """A callable that moves the cursor progress and names what it is on"""

    def report(fraction, label):
        window.progress_update(fraction)
        if status is not None:
            status(f"Importing {base}: {label}")

    return report


def _build_materials(mesh_obj, base: str, geometry, surfaces, images, animated=None, progress=None):
    """One material per distinct draw state, and the image each slot samples"""
    # texture, tile, combiner and collision, all four read back off materials
    keys = {
        (draw, surfaces.get(tuple(sorted(indices)))) for _matrix, _source, faces in geometry for indices, draw in faces
    }
    materials, slot_image, slot_scale = {}, {}, {}
    prototypes = {}
    ordered = sorted(keys, key=repr)
    for index, key in enumerate(ordered):
        if progress is not None:
            progress(index / len(ordered), f"material {index + 1} of {len(ordered)}")
        (texture, tile, combine, rendermode, prim, env, geomode, texscale, _texlevel), surface = key
        preset = "bk64_shaded_texture" if texture is not None else "bk64_shaded_solid"
        material = _material_from_preset(mesh_obj, preset, prototypes)
        if isinstance(texture, tuple):
            material.name = f"{base}_anim{texture[1]}"
        else:
            material.name = f"{base}_tex_{texture}" if texture is not None else f"{base}_untextured"
        # every set_* flag writes a command the model may never have had, and
        # vanilla leaves the flat colors to the game
        material.f3d_mat.tex0.tex_set = False
        material.f3d_mat.tex1.tex_set = False
        material.f3d_mat.set_prim = False
        material.f3d_mat.set_env = False
        material.f3d_mat.set_key = False
        material.f3d_mat.set_k0_5 = False
        material.f3d_mat.set_blend = False
        material.f3d_mat.set_fog = False
        material.f3d_mat.prim_color = (0.0, 0.0, 0.0, 0.0)
        material.f3d_mat.env_color = (1.0, 1.0, 1.0, 1.0)
        if texture is not None and texture in images:
            image, otex_format = images[texture]
            material.f3d_mat.tex0.tex = image
            material.f3d_mat.tex0.tex_format = otex_format
            material.f3d_mat.tex0.tex_set = True
            native = image.get(NATIVE_SIZE_PROP)
            if native is not None:
                # an HD image tiles at the size it came in at, not its own
                material.f3d_mat.tex0.hd_native_width = str(int(native[0]))
                material.f3d_mat.tex0.hd_native_height = str(int(native[1]))
            if otex_format in PALETTED_FORMATS:
                # the fork's own override defaults to 255, which loads a CI4's
                # 16 entry palette as 256 and reads past the end of the blob
                material.f3d_mat.tex0.palette_color_count = BK_PALETTE_SIZE[otex_format] // 2 - 1
            slot_image[len(materials)] = image
        if isinstance(texture, tuple) and animated and texture[1] in animated:
            frames, rate = animated[texture[1]]
            material.hm64_bk64_anim_tex = "TEX0"
            material.hm64_bk64_anim_slot = texture[1]
            material.hm64_bk64_anim_rate = rate
            for frame in frames:
                material.flipbookGroup.flipbook0.textures.add().image = frame
        if tile is not None:
            _apply_tile(material.f3d_mat, tile)
        if combine is not None:
            _apply_combiner(material.f3d_mat, combine)
        if prim is not None:
            red, green, blue, alpha, lod_min, lod_frac = prim
            material.f3d_mat.prim_color = tuple(gammaInverse([c / 255.0 for c in (red, green, blue)])) + (
                alpha / 255.0,
            )
            material.f3d_mat.prim_lod_min = lod_min / 255.0
            material.f3d_mat.prim_lod_frac = lod_frac / 255.0
            material.f3d_mat.set_prim = True
        if env is not None:
            red, green, blue, alpha = env
            material.f3d_mat.env_color = tuple(gammaInverse([c / 255.0 for c in (red, green, blue)])) + (alpha / 255.0,)
            material.f3d_mat.set_env = True
        # INHERIT for a chunk that ran before any jump. It exports without one.
        layer = DRAW_LAYER_OF_ENTRY.get(rendermode, "INHERIT")
        material.hm64_bk64_draw_layer = layer
        if layer.startswith("TRANSLUCENT"):
            material.f3d_mat.rdp_settings.rendermode_preset_cycle_2 = "G_RM_AA_ZB_XLU_SURF2"
        for bit, flag in GEO_MODE_FLAGS.items():
            setattr(material.f3d_mat.rdp_settings, flag, bool(geomode & bit))
        # BK keeps its shading in vertex colors. A lit material has the export
        # throw that away and rebuild from the normals, which is wrong for
        # everything except reflection, where texture gen needs the normal.
        if not material.f3d_mat.rdp_settings.g_tex_gen:
            material.f3d_mat.rdp_settings.g_lighting = False
        if texscale is not None:
            # vanilla usually halves this, and convertUV divides the half texel
            # offset by it. _fill_mesh has to use the same number
            material.f3d_mat.scale_autoprop = False
            material.f3d_mat.tex_scale = (texscale[0] / 0xFFFF, texscale[1] / 0xFFFF)
            slot_scale[len(materials)] = (texscale[0] / 0xFFFF, texscale[1] / 0xFFFF)
        if surface is not None:
            material.name += "_collision"
            apply_surface(material, *surface)
        # the property update callback resolves its material from the UI context
        # and gives up during an import, leaving tile sizes at 1x1 and the nodes
        # on the preset's combiner. A flat run drops TEXEL0, so the preset's
        # TEXEL0 * SHADE draws it black wherever no texture was left bound.
        update_node_values_of_material(material, bpy.context)
        update_tex_values_manual(material, bpy.context)
        materials[key] = len(materials)

    for proto in prototypes.values():
        proto.use_fake_user = False
        bpy.data.materials.remove(proto)
    return materials, slot_image, slot_scale


def _build_faces(geometry, surfaces, vertices, materials, to_blender):
    """(corners, material slot, bone index, source vertices) per face, and the positions"""
    positions, face_data, remap = [], [], {}
    for matrix_id, source, faces in geometry:
        for indices, draw in faces:
            corners = []
            for index in indices:
                if index not in remap:
                    remap[index] = len(positions)
                    positions.append(to_blender @ mathutils.Vector(vertices[index][0]))
                corners.append(remap[index])
            if len(set(corners)) < 3:
                continue  # a degenerate triangle carries no surface
            key = (draw, surfaces.get(tuple(sorted(indices))))
            face_data.append(
                (corners, materials[key], matrix_id, [vertices[i] for i in indices], list(indices), source)
            )
    return face_data, positions, remap


def _build_collision_only(context, base: str, leftover, vertices, armature_obj, mesh_obj, to_blender):
    """The collision triangles no drawn face covers, as their own wire mesh"""
    collection = bpy.data.collections.new(f"{base}_collision_only")
    context.scene.collection.children.link(collection)

    positions, remap, faces, face_surfaces = [], {}, [], []
    for triple, (flags, unk6) in sorted(leftover.items()):
        if len(set(triple)) < 3 or any(index >= len(vertices) for index in triple):
            continue
        corners = []
        for index in triple:
            if index not in remap:
                remap[index] = len(positions)
                positions.append(to_blender @ mathutils.Vector(vertices[index][0]))
            corners.append(remap[index])
        faces.append(corners)
        face_surfaces.append((flags, unk6))

    if not faces:
        return None

    mesh = bpy.data.meshes.new(f"{base}_collision_only")
    mesh.from_pydata(positions, [], faces)
    mesh.validate()

    # nothing samples these, but they're in the Vtx record and a round trip that
    # rewrites them stops matching the model it came from
    colors = mesh.attributes.new(COLLISION_COLOR_ATTR, "FLOAT_COLOR", "POINT")
    uvs = mesh.attributes.new(COLLISION_UV_ATTR, "FLOAT2", "POINT")
    for index, slot in remap.items():
        _position, uv, color = vertices[index]
        colors.data[slot].color = [channel / 255.0 for channel in color]
        uvs.data[slot].vector = uv

    slot_of = {}
    for surface in face_surfaces:
        if surface not in slot_of:
            material = bpy.data.materials.new(f"{base}_collision_{len(slot_of)}")
            apply_surface(material, *surface)
            mesh.materials.append(material)
            slot_of[surface] = len(slot_of)
    for polygon, surface in zip(mesh.polygons, face_surfaces):
        polygon.material_index = slot_of[surface]

    obj = bpy.data.objects.new(f"{base}_collision_only", mesh)
    obj.ignore_render = True  # it's collision, nothing draws it
    obj.display_type = "WIRE"
    obj[COLLISION_ONLY_PROP] = 1
    collection.objects.link(obj)
    obj.parent = armature_obj or mesh_obj
    return obj


def _build_camera_areas(context, base: str, areas, parent, to_blender):
    """The boxes a geo CAMERA command gates on, as objects you can move"""
    collection = bpy.data.collections.new(f"{base}_camera_areas")
    context.scene.collection.children.link(collection)
    for index, area in enumerate(areas):
        low, high = area["min"], area["max"]
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        # a flat gate would be invisible and unpickable, so give it a unit of thickness
        bmesh.ops.scale(bm, vec=[max(abs(high[axis] - low[axis]), 1) for axis in range(3)], verts=bm.verts)
        mesh = bpy.data.meshes.new(f"{base}_camera_{index:02d}")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.ignore_render = True  # a gate isn't geometry, it must not export as any
        obj.display_type = "WIRE"
        obj[CAMERA_AREA_KIND] = index
        collection.objects.link(obj)
        obj.parent = parent
        context.view_layer.update()
        centre = mathutils.Vector([(high[axis] + low[axis]) / 2.0 for axis in range(3)])
        obj.matrix_world = to_blender @ mathutils.Matrix.Translation(centre)
    return collection


def _build_collision_shapes(context, base: str, shapes, armature_obj, mesh_obj, bone_names, to_blender):
    # built around its own origin and placed by its transform, which the export
    # reads it straight back off that
    collection = bpy.data.collections.new(f"{base}_collision_shapes")
    context.scene.collection.children.link(collection)
    # the export works this out again from the shapes, it's here to read
    collection["hm64_bk64_cull_radius"] = shapes["cull"]
    built = []

    def place(name, bm, kind, placement, bone, code, pivot=None):
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.ignore_render = True  # a collision volume isn't geometry, don't export it as any
        obj.display_type = "WIRE"
        collection.objects.link(obj)
        obj[SHAPE_KIND] = kind
        obj[SHAPE_CODE] = code
        if pivot is not None:
            # a rotated box sits where its own point puts it, not its middle.
            # Losing that moved Blubber's hatch 55 units off.
            obj[SHAPE_PIVOT] = list(pivot)

        # under whatever the export is handed, or read_collision_shapes walks
        # the children of a root these never hung off and finds nothing
        obj.parent = armature_obj or mesh_obj
        if armature_obj is not None and bone in bone_names:
            obj.parent_type = "BONE"
            obj.parent_bone = bone_names[bone]
        context.view_layer.update()
        obj.matrix_world = to_blender @ placement
        built.append(obj)

    for index, box in enumerate(shapes["boxes"]):
        low, high, position = box["low"], box["high"], box["position"]
        center = mathutils.Vector([(high[axis] + low[axis]) / 2.0 for axis in range(3)])
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=[abs(high[axis] - low[axis]) for axis in range(3)], verts=bm.verts)
        # the box turns about its own point and its center lands somewhere else
        turned = _shape_matrix(position, box["rotation"])
        place(
            f"{base}_box_{index:02d}",
            bm,
            "BOX",
            mathutils.Matrix.Translation(turned @ center) @ turned.to_3x3().to_4x4(),
            box["bone"],
            box["code"],
            position,
        )

    for index, cylinder in enumerate(shapes["cylinders"]):
        bm = bmesh.new()
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=12,
            radius1=cylinder["radius"],
            radius2=cylinder["radius"],
            depth=cylinder["height"],
        )
        # a cylinder is centered on its own point, and turning about that leaves
        # it there. Placing it by the turn itself would land it at p - R@p.
        turned = _shape_matrix(cylinder["position"], cylinder["rotation"])
        place(
            f"{base}_cylinder_{index:02d}",
            bm,
            "CYLINDER",
            mathutils.Matrix.Translation(mathutils.Vector(cylinder["position"])) @ turned.to_3x3().to_4x4(),
            cylinder["bone"],
            cylinder["code"],
        )

    for index, sphere in enumerate(shapes["spheres"]):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=sphere["radius"])
        place(
            f"{base}_sphere_{index:02d}",
            bm,
            "SPHERE",
            mathutils.Matrix.Translation(mathutils.Vector(sphere["center"])),
            sphere["bone"],
            sphere["code"],
        )

    return built


def _fill_mesh(mesh, positions, face_data, slot_image, slot_scale):
    mesh.from_pydata(positions, [], [face[0] for face in face_data])
    uv_layer = mesh.uv_layers.new(name="UVMap")
    # createF3DMat already made this, and the export reads it by name
    color_layer = mesh.color_attributes.get("Col") or mesh.color_attributes.new(
        name="Col", type="BYTE_COLOR", domain="CORNER"
    )
    alpha_layer = mesh.color_attributes.get("Alpha")

    # the chunk each face was drawn in, for the export to rebuild the layout
    chunk_layer = mesh.attributes.new(name=SOURCE_CHUNK_ATTR, type="INT", domain="FACE")
    for face_index, (_corners, material_index, _matrix_id, source, _orig_indices, chunk) in enumerate(face_data):
        polygon = mesh.polygons[face_index]
        polygon.material_index = material_index
        chunk_layer.data[face_index].value = chunk
        image = slot_image.get(material_index)
        width, height = (image.size[0], image.size[1]) if image else (32, 32)
        scale_s, scale_t = slot_scale.get(material_index, (1.0, 1.0))
        # convertUV takes off half a texel for bilinear sampling, divided by the
        # texture scale. Add back the same amount.
        offset_s = 0.5 / scale_s if scale_s else 0.0
        offset_t = 0.5 / scale_t if scale_t else 0.0
        for corner, (_position, uv, color) in zip(polygon.loop_indices, source):
            uv_layer.data[corner].uv = (
                (uv[0] / 32.0 + offset_s) / width,
                1.0 - (uv[1] / 32.0 + offset_t) / height,
            )
            # the export gamma corrects on the way out. Store what it wants back.
            color_layer.data[corner].color = gammaInverse([channel / 255.0 for channel in color]) + [1.0]
            if alpha_layer is not None:
                # the export gamma corrects this layer the same as Col. Store
                # it the same way or an alpha of 102 comes back out as 170.
                alpha_layer.data[corner].color = [gammaInverseValue(color[3] / 255.0)] * 3 + [1.0]
    # after the attributes, not before: validate drops faces, and the loop above
    # pairs face_data with mesh.polygons by position
    mesh.validate()
    mesh.update()


def import_bk64_model(context, path: str, settings):
    """Reads a model resource family or a .bin, returning (armature, mesh, model)"""
    folder, base = os.path.dirname(path), os.path.basename(path)
    with open(path, "rb") as file:
        data = file.read()

    textures = None
    if is_bkmodelbin(data):
        model, vertices, layout, textures = _read_model_bin(data)
    else:
        model = _read_model(data)
        siblings = {}
        for suffix in ("_VTX", "_GEO"):
            sibling = os.path.join(folder, base + suffix)
            if not os.path.exists(sibling):
                raise PluginError(
                    f"'{base}{suffix}' isn't next to the model. A BK model is a family of files. "
                    "Extract the whole set, not just the one."
                )
            with open(sibling, "rb") as file:
                siblings[suffix] = file.read()
        vertices = _read_vertices(siblings["_VTX"])
        layout = read_geo_tree(siblings["_GEO"])
    model["geo_layout"] = layout
    geo_used = set()
    chunks = layout_chunks(layout, geo_used)
    model["geo_commands"] = sorted(geo_used)

    # geometry first, to know the palettes before the images load
    state = new_walk_state()
    if textures is not None:
        state["blob_images"] = {texture["image"]: index for index, texture in enumerate(textures)}
    geometry = []
    for matrix_id, parent_id, gfx_index in chunks:
        state["chunk_owner"], state["chunk_parent"] = matrix_id, parent_id
        geometry.append((matrix_id, gfx_index, _walk_display_list(model["words"], gfx_index, state)))

    if textures is None:
        drawn = {draw[0] for _matrix, _source, faces in geometry for _indices, draw in faces}
        images = _load_textures(folder, base, model["blob"], state["palettes"], drawn, state["mip_textures"])
    else:
        images = _load_blob_textures(base, model["blob"], textures, state["mip_textures"])

    model["animated_frames"] = _load_animated_frames(base, model, state["anim_binds"], images)

    # six models list textures their display list never binds, up to 81 of them.
    # Nothing here samples one, and nothing writes one back.
    bound = {draw[0] for _matrix, _source, faces in geometry for _indices, draw in faces}
    model["unbound_textures"] = max(0, len(model["tex_infos"]) - len({t for t in bound if isinstance(t, int)}))
    model["dropped"] = state["dropped"]

    armature_obj = None
    bone_names = {}
    if model["bones"]:
        armature_obj = create_armature_from_bones(
            base + "_skel", model["bones"], bone_space_matrix(settings.scale), settings.bone_length
        )
        # Blender lists bones by tree, and two Kazooie tables aren't in tree order
        bone_names = {bone.hm64_bk64_bone_order: bone.name for bone in armature_obj.data.bones}

    # BK is Y up and in its own units
    to_blender = (
        mathutils.Matrix.Rotation(math.radians(90), 4, "X")
        @ mathutils.Matrix.Diagonal(mathutils.Vector((1.0 / settings.scale,) * 3)).to_4x4()
    )

    mesh = bpy.data.meshes.new(base)
    mesh_obj = bpy.data.objects.new(base, mesh)
    mesh_obj.use_f3d_culling = False  # BK culls off the model's own center and radius
    context.scene.collection.objects.link(mesh_obj)
    # on whichever object the export is handed, the armature when there's one
    (armature_obj or mesh_obj)[GEO_LAYOUT_PROP] = json.dumps(model["geo_layout"])
    (armature_obj or mesh_obj).hm64_bk64_geo_type_raw = model["geo_type"]
    if model.get("camera_areas"):
        _build_camera_areas(context, base, model["camera_areas"], armature_obj or mesh_obj, to_blender)
    if model.get("collision_grid"):
        mesh_obj[COLLISION_GRID_PROP] = pack_collision_grid(model["collision_grid"], vertices)

    if model["shapes"]:
        model["shape_objects"] = _build_collision_shapes(
            context, base, model["shapes"], armature_obj, mesh_obj, bone_names, to_blender
        )

    surfaces = model["collision"]
    window = context.window_manager
    workspace = getattr(context, "workspace", None)
    status = getattr(workspace, "status_text_set", None) or getattr(window, "status_text_set", None)
    window.progress_begin(0, 1)
    try:
        materials, slot_image, slot_scale = _build_materials(
            mesh_obj,
            base,
            geometry,
            surfaces,
            images,
            model["animated_frames"],
            progress=_report_progress(window, status, base),
        )
    finally:
        window.progress_end()
        if status is not None:
            status(None)
    face_data, positions, remap = _build_faces(geometry, surfaces, vertices, materials, to_blender)
    _fill_mesh(mesh, positions, face_data, slot_image, slot_scale)

    # vanilla puts collision on geometry it never draws, cheap floors and walls
    # the mesh has no face for
    drawn = {tuple(sorted(indices)) for _matrix, _source, faces in geometry for indices, _draw in faces}
    leftover = {triple: surface for triple, surface in surfaces.items() if triple not in drawn}
    model["collision_only_object"] = (
        _build_collision_only(context, base, leftover, vertices, armature_obj, mesh_obj, to_blender)
        if leftover
        else None
    )

    # the export reads these back by name. A renamed group stops being a mesh.
    dropped = 0
    for entry in model["mesh_list"]:
        # vanilla lists vertices no triangle draws, and there is no geometry to put those on
        drawn = [remap[orig] for orig in entry["vertices"] if orig in remap]
        dropped += len(entry["vertices"]) - len(drawn)
        if drawn:
            group = mesh_obj.vertex_groups.new(name=f"{MESH_GROUP_PREFIX}{entry['uid']}")
            group.add(sorted(set(drawn)), 1.0, "REPLACE")
    model["mesh_list_dropped"] = dropped

    if armature_obj is not None:
        # a bound model draws under no bone of its own. Its binding table names
        # the bone each vertex follows.
        bound_owner = {}
        for entry in model["bound_vertices"]:
            for orig in entry["vertices"]:
                bound_owner[orig] = entry["bone"]
        # a seam vertex follows the parent bone. Grouping by face would hand it
        # to the child and tear the joint open the moment it bends.
        owner_of = state["vertex_owner"]
        fallback = {}
        for corners, _material, matrix_id, _source, orig_indices, _chunk in face_data:
            for orig in orig_indices:
                fallback.setdefault(orig, matrix_id)
        groups = {}
        for orig, blender_index in remap.items():
            # bone -1 is the identity matrix, a bound vertex that follows nothing
            owner = bound_owner[orig] if orig in bound_owner else owner_of.get(orig, fallback.get(orig))
            name = bone_names.get(owner)
            if name is not None:
                groups.setdefault(name, set()).add(blender_index)
        for name, indices in groups.items():
            mesh_obj.vertex_groups.new(name=name).add(sorted(indices), 1.0, "REPLACE")
        mesh_obj.parent = armature_obj
        modifier = mesh_obj.modifiers.new("Armature", "ARMATURE")
        modifier.object = armature_obj

    return armature_obj, mesh_obj, model
