from __future__ import annotations

import json
import struct

from ...f3d.f3d_gbi import VTX_SIZE, SPDisplayList, SPEndDisplayList
from ...utility import PluginError
from .bk64_constants import (
    ANIM_TEX_SLOT_COUNT,
    G_LIGHTING,
    G_TEXTURE_GEN,
    GEO_LAYOUT_PROP,
    MAX_APPENDAGE_ID,
    MIP_LOAD_BLOCK,
    MIP_LOAD_TILE,
    NO_PARENT,
    OP_CLEARGEOMETRYMODE,
    OP_CULLDL,
    OP_DL,
    OP_ENDDL,
    OP_LOADBLOCK,
    OP_MOVEMEM,
    OP_MOVEWORD,
    OP_POPMTX,
    OP_SETCOMBINE,
    OP_SETGEOMETRYMODE,
    OP_SETTILE,
    OP_SETTILESIZE,
    OP_SETTIMG,
    OP_TRI1,
    OP_TRI2,
    OP_VTX,
    RENDERMODE_ENTRY_STRIDE,
    s16,
    SEG_ANIM_BASE,
    SEG_RENDERMODE,
    SEG_TEX,
    SEG_TEX_BLOB,
    SEG_VTX,
    WHITE_TEXTURE_DIM,
)
from .bk64_rom import layout_records


def _subtree_points(index, children, chunk_points):
    """Every vertex the bone and everything under it draws, in BK units"""
    points = list(chunk_points.get(index, []))
    for child in children.get(index, []):
        points += _subtree_points(child, children, chunk_points)
    return points


def stored_layout(root_obj):
    """The layout an imported model came with, or None"""
    # JSON, a Blender custom property can't hold a nested tuple tree
    raw = root_obj.get(GEO_LAYOUT_PROP)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def relink_layout(records, from_source):
    """The stored layout with every original chunk index swapped for the new ones, or None"""
    kept = 0

    def relink(nodes):
        nonlocal kept
        out = []
        for record in nodes:
            kind = record[0]
            if kind == "loaddl":
                # a chunk that drew nothing has no faces to carry a source, and
                # vanilla writes plenty of those to set state for the next one
                indices = from_source.get(record[1])
                if not indices:
                    continue
                kept += 1
                out += [("loaddl", index) for index in indices]
            elif kind == "skinning":
                indices = [i for source in record[1] for i in from_source.get(source, [])]
                if not indices:
                    continue
                kept += 1
                out.append(("skinning", indices))
            elif kind == "bonebranch":
                out.append(("bonebranch", record[1], relink(record[2])))
            elif kind == "selector":
                out.append(("selector", record[1], [relink(option) for option in record[2]]))
            elif kind == "sort":
                out.append(
                    ("sort", tuple(record[1]), tuple(record[2]), relink(record[3]), relink(record[4]), record[5])
                )
            elif kind == "lod":
                out.append(("lod", record[1], record[2], tuple(record[3]), relink(record[4])))
            elif kind == "drawdist":
                out.append(("drawdist", tuple(record[1]), tuple(record[2]), relink(record[3])))
            elif kind == "camera":
                out.append(("camera", list(record[1]), record[2], relink(record[3])))
            elif kind == "refpoint":
                out.append(("refpoint", record[1], record[2], tuple(record[3])))
            else:
                out.append(tuple(record))
        return out

    relinked = relink(records)
    return relinked if kept else None


def layout_refpoints(records):
    """Every REFPOINT in a stored layout, whatever it sits under"""
    return [
        ("refpoint", record[1], record[2], tuple(record[3]))
        for kind, _indices, _matrix, _parent, record in layout_records(records)
        if kind == "refpoint"
    ]


def _bound_refpoints(bones, armature_obj):
    """Every REFPOINT bone of a model that draws under no bone of its own"""
    # a selector has nothing to choose without per bone geometry, a refpoint only reports a joint
    if armature_obj is None:
        return []
    records = []
    for index, entry in enumerate(bones):
        bone = armature_obj.data.bones[entry.name]
        if getattr(bone, "hm64_bk64_geo_type", "NONE") == "REFPOINT":
            records.append(("refpoint", getattr(bone, "hm64_bk64_geo_index", 0), index, tuple(entry.position)))
    return records


def geo_records(bones, chunks, armature_obj, rigged: bool, chunk_bounds=None):
    # depth first matches the order the chunks were built in. A selector pulls
    # its child bones' subtrees out of that run.
    if not rigged:
        records = [("loaddl", gfx_index) for _bone_index, gfx_index in chunks]
        return records + _bound_refpoints(bones, armature_obj)

    chunks_by_bone = {}
    for bone_index, gfx_index in chunks:
        chunks_by_bone.setdefault(bone_index, []).append(gfx_index)

    children = {}
    for index, bone in enumerate(bones):
        if bone.parent_index != NO_PARENT:
            children.setdefault(bone.parent_index, []).append(index)

    chunk_points = {}
    for position, (bone_index, _gfx_index) in enumerate(chunks):
        chunk_points.setdefault(bone_index, []).extend(chunk_bounds[position] if chunk_bounds else [])

    def node_of(index):
        if armature_obj is None:
            return "NONE", 0
        bone = armature_obj.data.bones[bones[index].name]
        return getattr(bone, "hm64_bk64_geo_type", "NONE"), getattr(bone, "hm64_bk64_geo_index", 0)

    def guarded(index, records):
        bone = armature_obj.data.bones[bones[index].name]
        geo_type = getattr(bone, "hm64_bk64_geo_type", "NONE")
        points = _subtree_points(index, children, chunk_points)

        if geo_type == "LOD":
            far = getattr(bone, "hm64_bk64_lod_far", 0.0)
            if far <= 0.0:
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Level Of Detail with no Far Distance, and would "
                    "never draw. Set one."
                )
            return [("lod", far, getattr(bone, "hm64_bk64_lod_near", 0.0), tuple(bones[index].position), records)]

        if geo_type == "DRAWDIST":
            if not points:
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Draw Distance with no geometry under it to make "
                    "a box from. Parent geometry to it, or to a bone beneath it."
                )
            low = tuple(min(point[axis] for point in points) for axis in range(3))
            high = tuple(max(point[axis] for point in points) for axis in range(3))
            return [("drawdist", low, high, records)]

        return records

    def subtree(index):
        records = [("bone", index, gfx_index) for gfx_index in chunks_by_bone.get(index, [])]
        geo_type, geo_index = node_of(index)

        if geo_type == "SORT":
            branches = [subtree(child) for child in children.get(index, [])]
            if len(branches) != 2:
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Sort with {len(branches)} child bones. Parent "
                    "two to it, one per half."
                )
            middles = []
            for child in children[index]:
                points = _subtree_points(child, children, chunk_points)
                middles.append(
                    tuple(sum(point[axis] for point in points) / len(points) for axis in range(3))
                    if points
                    else tuple(bones[child].position)
                )
            # bit 0 set draws only the half the camera faces. Leave it clear and
            # both halves draw back to front, the ordering a Sort is for.
            records.append(("sort", middles[0], middles[1], branches[0], branches[1], 0))
            return guarded(index, records)

        if geo_type == "SELECTOR":
            if not 1 <= geo_index <= MAX_APPENDAGE_ID:
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Selector with appendage id {geo_index}. The "
                    f"game treats 0 as unset and its table holds {MAX_APPENDAGE_ID}. Use 1 to "
                    f"{MAX_APPENDAGE_ID}."
                )
            if not children.get(index):
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Selector with no child bones. Parent one bone "
                    "per option to it."
                )
            records.append(("selector", geo_index, [subtree(child) for child in children[index]]))
        else:
            for child in children.get(index, []):
                records += subtree(child)

        if geo_type == "REFPOINT":
            # the game puts it through this bone's matrix and it rides the joint
            records.append(("refpoint", geo_index, index, tuple(bones[index].position)))
        return guarded(index, records)

    records = []
    for index, bone in enumerate(bones):
        if bone.parent_index == NO_PARENT:
            records += subtree(index)
    return records


def flatten_gfx_list(gfx_list, f3d, segments, seen=None):
    # BK walks from a start index until G_ENDDL. A sub list call has no target
    seen = seen if seen is not None else set()
    if id(gfx_list) in seen:
        raise PluginError(f"Recursive display list '{gfx_list.name}' cannot be flattened.")
    seen = seen | {id(gfx_list)}

    words = []
    for command in gfx_list.commands:
        if isinstance(command, SPDisplayList):
            words += flatten_gfx_list(command.displayList, f3d, segments, seen)
        elif not isinstance(command, SPEndDisplayList):
            # big endian, and a macro can expand to several commands
            raw = command.to_binary(f3d, segments)
            words += [struct.unpack_from(">II", raw, offset) for offset in range(0, len(raw), 8)]
    return words


def _vtx_loads(pairs):
    """gSPVertex words for (record, slot) pairs, split where either run breaks"""
    words = []
    index = 0
    while index < len(pairs):
        end = index + 1
        while end < len(pairs) and pairs[end][0] == pairs[end - 1][0] + 1 and pairs[end][1] == pairs[end - 1][1] + 1:
            end += 1
        count = end - index
        record, slot = pairs[index]
        words.append(
            (
                (OP_VTX << 24) | ((slot * 2) << 16) | (count << 10) | (VTX_SIZE * count - 1),
                (SEG_VTX << 24) | (record * VTX_SIZE),
            )
        )
        index = end
    return words


def split_skinning(words, vertices, owner_of_pos, parent_bone):
    """The chunk as SKINNING's two lists, or None when there's nothing to blend"""
    slot_record = {}
    items = []
    try:
        for w0, w1 in words:
            opcode = (w0 >> 24) & 0xFF
            if opcode == OP_ENDDL:
                break
            if opcode == OP_VTX:
                first = ((w0 >> 16) & 0xFF) // 2
                count = (w0 & 0xFFFF) >> 10
                base = (w1 & 0xFFFFFF) // VTX_SIZE
                for step in range(count):
                    slot_record[first + step] = base + step
            elif opcode == OP_TRI1:
                items.append(("tri", tuple(slot_record[((w1 >> shift) & 0xFF) // 2] for shift in (16, 8, 0))))
            elif opcode == OP_TRI2:
                for packed in (w0 & 0xFFFFFF, w1):
                    items.append(("tri", tuple(slot_record[((packed >> shift) & 0xFF) // 2] for shift in (16, 8, 0))))
            else:
                items.append(("word", w0, w1))
    except KeyError:
        return None  # indexes a slot loaded outside the chunk

    def owner(record):
        return owner_of_pos.get(tuple(s16(value) for value in vertices[record][0]))

    parent_records = []
    for kind, *rest in items:
        if kind == "tri":
            for record in rest[0]:
                if record not in parent_records and owner(record) == parent_bone:
                    parent_records.append(record)
    if not parent_records or len(parent_records) > 24:
        return None

    reserved = {record: slot for slot, record in enumerate(parent_records)}
    window = 32 - len(parent_records)
    # POPMTX puts the first list's loads under the parent's matrix, the handler
    # pushes the bone's own back for the second, and triangles there mix both
    list_a = [(OP_POPMTX << 24, 0)]
    list_a += _vtx_loads(sorted(((record, slot) for record, slot in reserved.items()), key=lambda pair: pair[1]))
    list_a.append((OP_ENDDL << 24, 0))

    list_b = []
    loaded = {}
    fresh = []
    pending = []

    def flush():
        nonlocal fresh, pending
        list_b.extend(_vtx_loads(sorted(fresh, key=lambda pair: pair[1])))
        for triangle in pending:
            slots = [reserved.get(record, loaded.get(record)) for record in triangle]
            list_b.append((OP_TRI1 << 24, ((slots[0] * 2) << 16) | ((slots[1] * 2) << 8) | (slots[2] * 2)))
        fresh, pending = [], []

    for kind, *rest in items:
        if kind == "word":
            flush()
            list_b.append((rest[0], rest[1]))
            continue
        triangle = rest[0]
        needed = list(dict.fromkeys(r for r in triangle if r not in reserved and r not in loaded))
        if len(loaded) + len(needed) > window:
            flush()
            loaded.clear()
            needed = list(dict.fromkeys(r for r in triangle if r not in reserved))
        for record in needed:
            slot = len(parent_records) + len(loaded)
            loaded[record] = slot
            fresh.append((record, slot))
        pending.append(triangle)
    flush()
    list_b.append((OP_ENDDL << 24, 0))
    return list_a, list_b


def fixup_chunk(words, texture_count: int, rendermode_entry, white_offset=None, mip_textures=frozenset()):
    # a reflective chunk keeps its lighting bit. That bit transforms the normal
    # texture gen reads, and modelRender hands it a LookAt and no lights, the
    # same as vanilla.
    reflective = any(((w0 >> 24) & 0xFF) == OP_SETGEOMETRYMODE and (w1 & G_TEXTURE_GEN) for w0, w1 in words)
    out = [] if reflective else [(OP_CLEARGEOMETRYMODE << 24, G_LIGHTING)]  # the model path loads no lights
    if rendermode_entry is not None:
        # jump into the table instead of setting a mode, leaving the actor's depth mode to hold
        out.append((OP_DL << 24, (SEG_RENDERMODE << 24) | (rendermode_entry * RENDERMODE_ENTRY_STRIDE)))
    mip_active = False
    for w0, w1 in words:
        opcode = (w0 >> 24) & 0xFF
        if opcode in {OP_ENDDL, OP_CULLDL}:  # BK culls off the vertex header
            continue
        if opcode in {OP_MOVEMEM, OP_MOVEWORD}:
            # SPSetLights and its count. The structs never got addresses, so
            # the RSP would read vertices as lights.
            continue
        if opcode == OP_SETGEOMETRYMODE and (w1 & G_LIGHTING) and not reflective:
            w1 &= ~G_LIGHTING
            if w1 == 0:
                continue
        if opcode == OP_SETTIMG:  # seg 0xFF indexes _tex_<i>, seg 2 offsets into the blob
            segment, index = w1 >> 24, w1 & 0x00FFFFFF
            animated_segment = SEG_ANIM_BASE - ANIM_TEX_SLOT_COUNT < segment <= SEG_ANIM_BASE
            if not animated_segment and segment != SEG_TEX_BLOB and (segment != SEG_TEX or index >= texture_count):
                raise PluginError(
                    f"A G_SETTIMG points at 0x{w1:08X}, which is not one of the {texture_count} "
                    "textures or a palette in the blob."
                )
            mip_active = segment == SEG_TEX and index in mip_textures
        elif mip_active:
            # a mipmapped chunk renders from the wrap DL's tile pyramid, so its
            # own setup is one load of base plus pyramid and no render tile
            if opcode == OP_SETTILE:
                if (w1 >> 24) & 7 == 7:
                    out.append(MIP_LOAD_TILE)
                continue
            if opcode == OP_LOADBLOCK:
                out.append(MIP_LOAD_BLOCK)
                continue
            if opcode == OP_SETTILESIZE:
                mip_active = False
                continue
        out.append((w0, w1))
    if white_offset is not None:
        out = _bind_untextured(out, white_offset)
    out.append((OP_ENDDL << 24, 0))
    return out


def _bind_untextured(words, white_offset: int):
    # a reader picks the texture up at the vertex load. Bind ahead of that.
    runs, current = [], []
    for word in words:
        if (word[0] >> 24) & 0xFF == OP_SETCOMBINE and current:
            runs.append(current)
            current = []
        current.append(word)
    runs.append(current)

    # G_SETTILE carries the format. Send it too or the white texture reads
    # as whatever the last material used.
    setimg = (OP_SETTIMG << 24) | (2 << 19) | (WHITE_TEXTURE_DIM - 1)
    line = WHITE_TEXTURE_DIM * 2 // 8
    settile = ((OP_SETTILE << 24) | (2 << 19) | (line << 9), (2 << 18) | (2 << 8))
    out = []
    for run in runs:
        opcodes = [(w0 >> 24) & 0xFF for w0, _w1 in run]
        if any(opcode in {OP_TRI1, OP_TRI2} for opcode in opcodes) and OP_SETTIMG not in opcodes:
            at = opcodes.index(OP_VTX) if OP_VTX in opcodes else len(run)
            bind = [(setimg, (SEG_TEX_BLOB << 24) | white_offset), settile]
            run = run[:at] + bind + run[at:]
        out += run
    return out


def count_triangles(words):
    total = 0
    for w0, _w1 in words:
        opcode = (w0 >> 24) & 0xFF
        if opcode == OP_TRI1:
            total += 1
        elif opcode == OP_TRI2:
            total += 2
    return total
