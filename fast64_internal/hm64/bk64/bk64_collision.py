from __future__ import annotations

import base64
import struct
import zlib

from ...f3d.f3d_gbi import VTX_SIZE, FModel
from ...utility import PluginError
from .bk64_constants import (
    BK_COLLISION_CELL_TRIANGLES,
    BK_COLLISION_FLAG_BITS,
    BK_COLLISION_MAX_CELLS,
    BK_COLLISION_MAX_ENTRIES,
    BK_COLLISION_MEDIUM_MASK,
    BK_COLLISION_SCALE_MAX,
    BK_COLLISION_SCALE_MIN,
    BK_COLLISION_SCALE_STEP,
    BK_MEDIUM_TYPE,
    BK_SOUND_TYPE,
    bk64_surface_decode,
    bk64_surface_encode,
    OP_TRI1,
    OP_TRI2,
    OP_VTX,
    s16,
    tri_indices,
)

MEDIUM_NAMES = {value: key for key, value in BK_MEDIUM_TYPE.items()}
SOUND_NAMES = {value: key for key, value in BK_SOUND_TYPE.items()}


def pack_collision_grid(grid, vertices) -> str:
    """The imported grid as a property value, corners resolved to positions"""
    data = bytearray(struct.pack("<7h", grid["scale"], *grid["low"], *grid["high"]))
    data.extend(struct.pack("<I", len(grid["counts"])))
    data.extend(struct.pack(f"<{len(grid['counts'])}H", *grid["counts"]))
    data.extend(struct.pack("<I", len(grid["records"])))
    for a, b, c, unk6, flags in grid["records"]:
        for index in (a, b, c):
            data.extend(struct.pack("<3h", *(s16(value) for value in vertices[index][0])))
        data.extend(struct.pack("<HI", unk6, flags & 0xFFFFFFFF))
    return base64.b64encode(zlib.compress(bytes(data))).decode()


def unpack_collision_grid(text: str):
    """The stored grid back as (scale, low, high, counts, records), or None"""
    try:
        data = zlib.decompress(base64.b64decode(text))
    except Exception:
        return None
    scale, *bounds = struct.unpack_from("<7h", data, 0)
    count = struct.unpack_from("<I", data, 14)[0]
    counts = struct.unpack_from(f"<{count}H", data, 18)
    at = 18 + count * 2
    total = struct.unpack_from("<I", data, at)[0]
    at += 4
    records = []
    for _ in range(total):
        corners = tuple(struct.unpack_from("<3h", data, at + step * 6) for step in range(3))
        unk6, flags = struct.unpack_from("<HI", data, at + 18)
        records.append((corners, unk6, flags))
        at += 24
    return dict(scale=scale, low=tuple(bounds[:3]), high=tuple(bounds[3:]), counts=counts, records=records)


def preserved_grid(stored, triangles, vertices):
    """The imported grid rebuilt over this export's vertex order, or None"""
    if stored is None:
        return None
    position = {}
    for index, vertex in enumerate(vertices):
        position.setdefault(tuple(s16(value) for value in vertex[0]), index)
    ours = {
        (tuple(sorted(tuple(s16(v) for v in vertices[i][0]) for i in tri)), flags & 0xFFFFFFFF, unk6)
        for tri, flags, unk6 in triangles
    }
    theirs = {(tuple(sorted(corners)), flags & 0xFFFFFFFF, unk6) for corners, unk6, flags in stored["records"]}
    if ours != theirs:
        return None
    records = []
    for corners, unk6, flags in stored["records"]:
        indices = tuple(position.get(corner) for corner in corners)
        if None in indices:
            return None
        records.append((indices, unk6, flags))
    low, high = stored["low"], stored["high"]
    size = [high[k] - low[k] + 1 for k in range(3)]
    runs, cursor = [], 0
    for count in stored["counts"]:
        runs.append((cursor, count))
        cursor += count
    return low, size, stored["scale"], runs, records


def _bucket(points, low, scale, size):
    """{cell index: [triangle]}, a triangle landing in every cell its box covers"""
    cells = {}
    for index, tri in enumerate(points):
        span = [(min(point[k] for point in tri) // scale, max(point[k] for point in tri) // scale) for k in range(3)]
        for z in range(span[2][0], span[2][1] + 1):
            for y in range(span[1][0], span[1][1] + 1):
                for x in range(span[0][0], span[0][1] + 1):
                    cell = (x - low[0]) + (y - low[1]) * size[0] + (z - low[2]) * size[0] * size[1]
                    cells.setdefault(cell, []).append(index)
    return cells


def collision_grid(triangles, vertices):
    """(low cell, size, scale, runs, entries) for a BKCollisionList"""
    points = [tuple(tuple(s16(value) for value in vertices[i][0]) for i in tri[0]) for tri in triangles]
    low_world = [min(point[k] for tri in points for point in tri) for k in range(3)]
    high_world = [max(point[k] for tri in points for point in tri) for k in range(3)]

    span = [max(1, high_world[k] - low_world[k]) for k in range(3)]
    wanted = max(1, len(points) // BK_COLLISION_CELL_TRIANGLES)
    scale = round((span[0] * span[1] * span[2] / wanted) ** (1.0 / 3.0) / BK_COLLISION_SCALE_STEP)
    scale = max(BK_COLLISION_SCALE_MIN, min(BK_COLLISION_SCALE_MAX, scale * BK_COLLISION_SCALE_STEP))

    while True:
        low = [low_world[k] // scale for k in range(3)]
        high = [high_world[k] // scale for k in range(3)]
        size = [high[k] - low[k] + 1 for k in range(3)]
        count = size[0] * size[1] * size[2]
        if count <= BK_COLLISION_MAX_CELLS:
            cells = _bucket(points, low, scale, size)
            if sum(len(members) for members in cells.values()) <= BK_COLLISION_MAX_ENTRIES:
                break
        if scale >= BK_COLLISION_SCALE_MAX:
            raise PluginError(
                f"{len(points)} collision triangles are more than the game can index. Split the mesh, "
                "or take collision off the parts that don't need it."
            )
        scale = min(BK_COLLISION_SCALE_MAX, scale + BK_COLLISION_SCALE_STEP)

    runs, entries = [], []
    for cell in range(count):
        members = cells.get(cell, ())
        runs.append((len(entries), len(members)))
        entries.extend(members)
    return low, size, scale, runs, entries


def read_collision_triangles(data: bytes, offset: int, count: int, endian: str):
    # keyed by vertices, not list position, the display list reorders the faces
    surfaces = {}
    for index in range(count):
        first, second, third, unk6, flags = struct.unpack_from(endian + "HHHHI", data, offset + index * 12)
        surfaces[tuple(sorted((first, second, third)))] = (flags, unk6)
    return surfaces


def read_collision(data: bytes, offset: int):
    """({sorted vertex triple: (flags, unk6)}, the grid, where the section ends)"""
    low = struct.unpack_from("<3h", data, offset)
    high = struct.unpack_from("<3h", data, offset + 6)
    offset += 12
    # the resource puts the scale ahead of the cell count and drops the pad
    _y_stride, _z_stride, scale, cube_count, tri_count = struct.unpack_from("<5H", data, offset)
    offset += 10
    grid = read_grid(data, offset, low, high, scale, cube_count, tri_count, "<")
    offset += cube_count * 4
    return read_collision_triangles(data, offset, tri_count, "<"), grid, offset + tri_count * 12


def read_bin_collision(data: bytes, offset: int):
    """({sorted vertex triple: (flags, unk6)}, the grid) from a BKCollisionList"""
    low = struct.unpack_from(">3h", data, offset)
    high = struct.unpack_from(">3h", data, offset + 6)
    _y_stride, _z_stride, cell_count, scale, tri_count = struct.unpack_from(">5h", data, offset + 0xC)
    grid = read_grid(data, offset + 0x18, low, high, scale, cell_count, tri_count, ">")
    return read_collision_triangles(data, offset + 0x18 + cell_count * 4, tri_count, ">"), grid


def read_grid(data: bytes, runs_at: int, low, high, scale: int, cube_count: int, tri_count: int, endian: str):
    """The cell structure as it came, or None for a layout not worth keeping"""
    if scale <= 0 or cube_count <= 0:
        return None
    counts, cursor = [], 0
    for index in range(cube_count):
        start, count = struct.unpack_from(endian + "hh", data, runs_at + index * 4)
        if count and start != cursor:
            return None  # runs the game's layout never produces, keep nothing
        counts.append(count)
        cursor += count
    if cursor != tri_count:
        return None
    records_at = runs_at + cube_count * 4
    # order kept as is, corner order included, a raycast takes its normal from the winding
    records = [struct.unpack_from(endian + "HHHHI", data, records_at + index * 12) for index in range(tri_count)]
    return dict(low=low, high=high, scale=scale, counts=counts, records=records)


def read_collision_shapes_data(data: bytes, offset: int, endian: str = "<"):
    """The header 0x14 shapes and their cull radius"""
    # a shape's code is a label rather than a setting, and shapes can share one
    box_count, cylinder_count, sphere_count, cull = struct.unpack_from(endian + "4h", data, offset)
    offset += 8
    shapes = {"cull": cull, "boxes": [], "cylinders": [], "spheres": []}

    for _box in range(box_count):
        values = struct.unpack_from(endian + "3h3h3h3BBbx", data, offset)
        shapes["boxes"].append(
            dict(
                low=values[0:3],
                high=values[3:6],
                position=values[6:9],
                rotation=values[9:12],
                code=values[12],
                bone=values[13],
            )
        )
        offset += 24
    for _cylinder in range(cylinder_count):
        values = struct.unpack_from(endian + "hh3h3BBbx", data, offset)
        shapes["cylinders"].append(
            dict(
                radius=values[0],
                height=values[1],
                position=values[2:5],
                rotation=values[5:8],
                code=values[8],
                bone=values[9],
            )
        )
        offset += 16
    for _sphere in range(sphere_count):
        values = struct.unpack_from(endian + "h3hBbxx", data, offset)
        shapes["spheres"].append(dict(radius=values[0], center=values[1:4], code=values[4], bone=values[5]))
        offset += 12
    return shapes, offset


def apply_surface(material, flags: int, unk6: int):
    fields = bk64_surface_decode(flags)
    if fields is not None:
        material.hm64_bk64_collision_type = MEDIUM_NAMES[fields["medium"]]
        material.hm64_bk64_sound_type = SOUND_NAMES[fields["sound"]]
        for name in BK_COLLISION_FLAG_BITS:
            setattr(material, f"hm64_bk64_{name}", fields[name])
        material.hm64_bk64_collision_extra = fields["extra"]
        material.hm64_bk64_collision_unk6 = unk6
        return
    material.hm64_bk64_collision_raw = flags - 0x100000000 if flags > 0x7FFFFFFF else flags
    material.hm64_bk64_collision_unk6 = unk6


def surface_of_material(material):
    """(flags, unk6) for a material that asks for collision, None for one that doesn't"""
    raw = getattr(material, "hm64_bk64_collision_raw", 0)
    if raw:
        # an imported surface kept exactly, for the flag words only a romhack sets
        return (raw & 0xFFFFFFFF, getattr(material, "hm64_bk64_collision_unk6", 0))
    collision = getattr(material, "hm64_bk64_collision_type", "NONE")
    if collision == "NONE":
        return None
    fields = {name: getattr(material, f"hm64_bk64_{name}", False) for name in BK_COLLISION_FLAG_BITS}
    fields["medium"] = BK_MEDIUM_TYPE[collision]
    fields["sound"] = BK_SOUND_TYPE[getattr(material, "hm64_bk64_sound_type", "MAP_DEFAULT")]
    fields["extra"] = getattr(material, "hm64_bk64_collision_extra", 0)
    return (bk64_surface_encode(fields), getattr(material, "hm64_bk64_collision_unk6", 0))


def material_surfaces(fModel: FModel):
    """The collision a material asks for, keyed by FMaterial id"""
    surfaces = {}
    for key, value in fModel.materials.items():
        surface = surface_of_material(key[0])
        if surface is not None:
            surfaces[id(value[0])] = surface
    return surfaces


def check_camera_water_reads(mesh_objects, warnings):
    """Warn for a surface the camera's water ray can't tell from water"""
    # core2/nc/camera_fog.c rays up with filter 0xF800FF0F, and ordinary
    # floors only stay out of it through their sound bits
    for mesh_obj in mesh_objects:
        for slot in mesh_obj.material_slots:
            surface = surface_of_material(slot.material) if slot.material else None
            if surface is None:
                continue
            flags = surface[0]
            if flags & (0xF800FF0F | BK_COLLISION_MEDIUM_MASK):
                continue
            warnings.append(
                f"'{slot.material.name}' collides with no sound tag, so the camera reads it as "
                "water and shows the underwater overlay beneath it. Give it a Sound Type."
            )


def collision_from_display_list(dl_words, owners, surfaces):
    # a collision triangle indexes the model's own vertex buffer, so walking the
    # display list beats building the faces twice
    if not surfaces:
        return []

    material_of = {}
    for first, last, fmaterial in owners:
        for index in range(first, last):
            material_of[index] = fmaterial

    triangles, cache = [], {}

    def emit(word):
        indices = tri_indices(word, cache)
        if indices is None:
            return
        surface = surfaces.get(material_of.get(indices[0]))
        if surface is not None:
            triangles.append((indices, surface[0], surface[1]))

    for w0, w1 in dl_words:
        opcode = (w0 >> 24) & 0xFF
        if opcode == OP_VTX:
            start = ((w0 >> 16) & 0xFF) // 2
            count = (w0 & 0xFFFF) >> 10
            base = (w1 & 0xFFFFFF) // VTX_SIZE
            for step in range(count):
                cache[start + step] = base + step
        elif opcode == OP_TRI1:
            emit(w1)
        elif opcode == OP_TRI2:
            emit(w0 & 0xFFFFFF)
            emit(w1)
    return triangles


def write_collision_list(triangles, vertices, stored=None, endian: str = "<"):
    """A BKCollisionList, bucketed into the grid a query walks"""
    kept = preserved_grid(stored, triangles, vertices)
    if kept is not None:
        low, size, scale, runs, records = kept
    else:
        low, size, scale, runs, entries = collision_grid(triangles, vertices)
        # (indices, flags, unk6) into the record's (indices, unk6, flags)
        records = [(triangles[index][0], triangles[index][2], triangles[index][1]) for index in entries]

    data = bytearray()
    data.extend(struct.pack(endian + "hhhhhh", *low, *(low[k] + size[k] - 1 for k in range(3))))
    counts = (scale, len(runs)) if endian == "<" else (len(runs), scale)
    data.extend(struct.pack(endian + "HHHHH", size[0], size[0] * size[1], *counts, len(records)))
    if endian != "<":
        data.extend(bytes(2))
    for start, count in runs:
        data.extend(struct.pack(endian + "HH", start, count))
    for indices, unk6, flags in records:
        data.extend(struct.pack(endian + "HHHHI", indices[0], indices[1], indices[2], unk6, flags & 0xFFFFFFFF))
    return bytes(data)
