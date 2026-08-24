from __future__ import annotations

import json
import math
import struct

import bmesh
import bpy
import mathutils

from ...f3d.f3d_gbi import (
    FImage,
    FPaletteKey,
    VTX_SIZE,
    DLFormat,
    FModel,
    GfxMatWriteMethod,
    SPDisplayList,
    SPEndDisplayList,
    SPTexture,
)
from ...f3d.f3d_writer import TriangleConverterInfo, getInfoDict, saveStaticModel
from ...utility import (
    PluginError,
    exportColor,
    getObjDirectionVec,
    lightDataToObj,
    normToSigned8Vector,
)
from .bk64_constants import (
    ANIM_FRAME_FORMATS,
    ANIM_TEX_SLOT_COUNT,
    BIN_TEX_FORMATS,
    BK_PALETTE_SIZE,
    BK_TEX_TYPE,
    bk64_world_defaults,
    BK_COLLISION_FLAG_BASE,
    BK_COLLISION_SINGLE_CELL_SCALE,
    BK_COLLISION_TYPE,
    BK_GROUND_TYPE,
    COLLISION_COLOR_ATTR,
    COLLISION_ONLY_PROP,
    COLLISION_UV_ATTR,
    BK_SOUND_TYPE,
    CYCLE_TYPE_2CYCLE,
    DEFAULT_LIGHT_DIR,
    F3D_FMT_TO_OTEX,
    G_LIGHTING,
    G_TEXTURE_GEN,
    GEO_LAYOUT_PROP,
    MAX_APPENDAGE_ID,
    MAX_DRAWABLE_BONE_INDEX,
    MAX_TEXTURE_DIM,
    MAX_VERTEX_COUNT,
    MESH_GROUP_PREFIX,
    MIP_LOAD_BLOCK,
    MIP_LOAD_TILE,
    MIP_SPTEXTURE_LEVEL,
    MIP_SPTEXTURE_TILE,
    MIP_TEXTURE_DIM,
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
    OTEX_TYPE,
    OTR_HEADER_SIZE,
    OTR_ID,
    OTR_TEXTURE_V0,
    OTR_TEXTURE_V1,
    PALETTED_FORMATS,
    RENDERMODE_ENTRY_STRIDE,
    SHADE_FOLD_FORMATS,
    TEX_FLAG_LOAD_AS_RAW,
    RT_BK_MODEL,
    RT_BLOB,
    RT_TEXTURE,
    RT_VERTEX,
    SEG_RENDERMODE,
    SEG_TEX,
    SEG_ANIM_BASE,
    SEG_TEX_BLOB,
    SEG_VTX,
    SHAPE_KIND,
    SHAPE_PIVOT,
    WHITE_TEXTURE_DIM,
)
from .bk64_rom import (
    collision_shapes,
    geo_body,
    layout_records,
    mesh_list,
    s16,
    tri_indices,
    vertex_bone_map,
    vertex_records,
    write_bkmodelbin,
)
from .bk64_skeleton import BK64Bone, BLENDER_TO_BK, build_bone_table


def otr_header(resource_type: int, version: int = 0):
    # byte order, is custom, 2 unused, type, version, id
    data = bytearray(struct.pack("<BBBBIIQ", 0, 1, 0, 0, resource_type, version, OTR_ID))
    data.extend(b"\x00" * (OTR_HEADER_SIZE - len(data)))
    return data


def _write_vertex_resource(vertices):
    """u32 count, then the Vtx records, as the _VTX sibling"""
    data = otr_header(RT_VERTEX)
    data.extend(struct.pack("<I", len(vertices)))
    data.extend(vertex_records(vertices))
    return data


def _vertex_bounds(vertices):
    """The BKVertexList header"""
    # BK culls off center + local_norm, global_norm is from the model origin
    if not vertices:
        return dict(min=(0, 0, 0), max=(0, 0, 0), center=(0, 0, 0), local_norm=0, count=0, global_norm=0)

    positions = [vertex[0] for vertex in vertices]
    low = tuple(min(position[axis] for position in positions) for axis in range(3))
    high = tuple(max(position[axis] for position in positions) for axis in range(3))
    center = tuple((low[axis] + high[axis]) / 2.0 for axis in range(3))

    def distance(point, origin):
        return math.sqrt(sum((point[axis] - origin[axis]) ** 2 for axis in range(3)))

    return dict(
        min=low,
        max=high,
        center=center,
        local_norm=math.ceil(max(distance(position, center) for position in positions)),
        count=len(vertices),
        global_norm=math.ceil(max(distance(position, (0, 0, 0)) for position in positions)),
    )


def _write_geo_layout(records):
    body = geo_body(records)
    data = otr_header(RT_BLOB)
    data.extend(struct.pack("<I", len(body)))
    data.extend(body)
    return data


def _write_texture_resource(otex_format: str, width: int, height: int, pixels: bytes, hd_scale=None):
    """u32 type, u32 width, u32 height, u32 byte count, then native N64 pixels.

    An HD texture goes out as V1, which fits the raw flag and the two scales in
    ahead of the count. Width and height stay the sizes the display list tiles,
    and the pixels behind them are RGBA8 at the real size.
    """
    if hd_scale is None:
        data = otr_header(RT_TEXTURE, OTR_TEXTURE_V0)
        data.extend(struct.pack("<IIII", OTEX_TYPE[otex_format], width, height, len(pixels)))
    else:
        h_scale, v_scale = hd_scale
        data = otr_header(RT_TEXTURE, OTR_TEXTURE_V1)
        data.extend(
            struct.pack(
                "<IIIIffI",
                OTEX_TYPE[otex_format],
                width,
                height,
                TEX_FLAG_LOAD_AS_RAW,
                h_scale,
                v_scale,
                len(pixels),
            )
        )
    data.extend(pixels)
    return data


def _hd_scale_of(fImage):
    """(h byte scale, v pixel scale) when an image was spoofed down, else None"""
    h_scale = getattr(fImage, "hd_byte_scale", 1.0)
    v_scale = getattr(fImage, "hd_pixel_scale", 1.0)
    return None if h_scale == 1.0 and v_scale == 1.0 else (h_scale, v_scale)


def _write_model_resource(
    geo_type,
    tri_count,
    bounds,
    dl_words,
    gfx_sub_count,
    bones,
    anim_scale,
    tex_infos,
    tex_blob,
    collision,
    shapes,
    bound_vertices,
    meshes,
    animated_slots,
):
    """The main BKMO resource, field for field"""
    has_anim = len(bones) > 0

    data = otr_header(RT_BK_MODEL)
    data.extend(struct.pack("<HHH", geo_type, tri_count, bounds["count"]))
    data.extend(struct.pack("<BBB", 1, 1, 1))  # geo, vtx and display list present
    data.extend(struct.pack("<H", len(tex_infos)))  # one entry per paletted texture
    data.extend(
        struct.pack(
            "<BBBBBBB",
            1 if has_anim else 0,
            1 if collision else 0,
            1 if shapes else 0,
            0,  # camera areas
            1 if meshes else 0,
            1 if bound_vertices else 0,
            1 if any(slot[0] for slot in animated_slots) else 0,
        )
    )

    data.extend(
        struct.pack(
            "<hhhhhhhhhhHh",
            *(s16(value) for value in bounds["min"]),
            *(s16(value) for value in bounds["max"]),
            *(s16(value) for value in bounds["center"]),
            s16(bounds["local_norm"]),
            bounds["count"],
            s16(bounds["global_norm"]),
        )
    )

    data.extend(struct.pack("<III", len(dl_words), 0, gfx_sub_count))
    for w0, w1 in dl_words:
        data.extend(struct.pack("<II", w0 & 0xFFFFFFFF, w1 & 0xFFFFFFFF))
    for info in tex_infos:
        data.extend(struct.pack("<HBBHI", info["type"], info["width"], info["height"], info["colors"], info["offset"]))
    data.extend(struct.pack("<I", len(tex_blob)))
    data.extend(tex_blob)

    # these follow the flag order above, the reader finds each by stepping over the last
    if has_anim:
        data.extend(struct.pack("<fH", anim_scale, len(bones)))
        for bone in bones:
            data.extend(struct.pack("<fffHH", *bone.position, bone.bone_id & 0xFFFF, bone.parent_index & 0xFFFF))
    if collision:
        data.extend(_write_collision(collision))
    if shapes:
        data.extend(collision_shapes(shapes))
    if meshes:
        data.extend(mesh_list(meshes))
    if bound_vertices:
        data.extend(vertex_bone_map(bound_vertices))
    if any(slot[0] for slot in animated_slots):
        for frame_size, frame_count, rate in animated_slots:
            data.extend(struct.pack("<hhf", frame_size, frame_count, rate))
    return data


def _evaluated_bmesh(context, mesh_obj, space_matrix, ignore_armature: bool):
    # the triangle converter applies the export transform but not the object's
    # world matrix. Bake that in here.
    disabled = []
    if ignore_armature:  # we want the rest pose, the bone table has the pivots
        for modifier in mesh_obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.show_viewport:
                modifier.show_viewport = False
                disabled.append(modifier)
    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = mesh_obj.evaluated_get(depsgraph)
        source = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)

        bm = bmesh.new()
        bm.from_mesh(source)
        evaluated.to_mesh_clear()
    finally:
        for modifier in disabled:
            modifier.show_viewport = True

    bm.transform(space_matrix @ mesh_obj.matrix_world)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    return bm


def _bmesh_to_object(context, bm, name: str, material_source, face_indices=None):
    part = bm.copy()
    if face_indices is not None:
        keep = set(face_indices)
        part.faces.ensure_lookup_table()
        bmesh.ops.delete(part, geom=[face for face in part.faces if face.index not in keep], context="FACES")
    if not part.faces:
        part.free()
        return None

    mesh = bpy.data.meshes.new(name)
    part.to_mesh(mesh)
    part.free()
    for slot in material_source.material_slots:
        mesh.materials.append(slot.material)

    part_obj = bpy.data.objects.new(name, mesh)
    part_obj.original_name = name  # saveStaticModel names its FMesh after this, and they must not collide
    part_obj.use_f3d_culling = False  # a cull list would drag a junk vertex load into the chunk
    context.scene.collection.objects.link(part_obj)
    mesh.calc_loop_triangles()
    return part_obj


def _f3d_settings(material):
    """The f3d_mat a material keeps its settings on, or the material before Fast64 4"""
    return material.f3d_mat if material.mat_ver > 3 else material


def _f3d_materials(mesh_objects):
    """(material, its f3d settings) for every F3D material on these objects"""
    for mesh_obj in mesh_objects:
        for slot in mesh_obj.material_slots:
            material = slot.material
            if material is None or not getattr(material, "is_f3d", False):
                continue
            yield material, _f3d_settings(material)


def promote_materials_to_2_cycle(mesh_obj):
    # the second cycle is the identity and there's nothing to decide
    changed = 0
    for _material, f3d_mat in _f3d_materials([mesh_obj]):
        if f3d_mat.rdp_settings.g_mdsft_cycletype == CYCLE_TYPE_2CYCLE:
            continue
        f3d_mat.rdp_settings.g_mdsft_cycletype = CYCLE_TYPE_2CYCLE
        second = f3d_mat.combiner2
        second.A, second.B, second.C, second.D = "0", "0", "0", "COMBINED"
        second.A_alpha, second.B_alpha, second.C_alpha, second.D_alpha = "0", "0", "0", "COMBINED"
        changed += 1
    return changed


def select_loose_vertices(mesh_obj):
    """Selects the vertices no bone weights, returning how many"""
    # Select All by Trait finds only the vertices in no group at all, and a
    # weight of 0 or a group no bone is named after reads as loose here too
    armature_obj = mesh_obj.find_armature()
    if armature_obj is None:
        raise PluginError(f"'{mesh_obj.name}' is not attached to an armature.")

    bone_names = {bone.name for bone in armature_obj.data.bones}
    groups = {group.index for group in mesh_obj.vertex_groups if group.name in bone_names}
    mesh = mesh_obj.data

    # Edit mode flushes from these, and a selected face would bring its corners with it
    for edge in mesh.edges:
        edge.select = False
    for polygon in mesh.polygons:
        polygon.select = False

    found = 0
    for vertex in mesh.vertices:
        vertex.select = not any(entry.group in groups and entry.weight > 0.0 for entry in vertex.groups)
        found += vertex.select
    return found


def split_mesh_at_bones(mesh_obj):
    """Cuts a mesh so every triangle belongs to one bone, returning the cut count"""
    # the export needs the mesh this way, but cutting it there would leave the
    # viewport showing something other than what ships
    armature_obj = next((m.object for m in mesh_obj.modifiers if m.type == "ARMATURE" and m.object), None)
    if armature_obj is None and mesh_obj.parent is not None and mesh_obj.parent.type == "ARMATURE":
        armature_obj = mesh_obj.parent
    if armature_obj is None:
        raise PluginError(f"'{mesh_obj.name}' is not attached to an armature.")

    bone_names = {bone.name for bone in armature_obj.data.bones}
    groups = {group.index: group.name for group in mesh_obj.vertex_groups if group.name in bone_names}
    if not groups:
        raise PluginError(f"'{mesh_obj.name}' has no vertex groups named after a bone in '{armature_obj.name}'.")

    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    deform = bm.verts.layers.deform.verify()

    # the same rule the export uses, or a mesh cut here still reads as welded there
    owners = {face: _face_bone_group(face, deform, groups) for face in bm.faces}

    seams = [edge for edge in bm.edges if len({owners[f] for f in edge.link_faces}) > 1]
    # use_verts also separates where two bones meet at a single vertex
    bmesh.ops.split_edges(bm, edges=seams, use_verts=True)
    for face in bm.faces:
        owner = owners.get(face)
        if owner is None:
            continue
        for vert in face.verts:
            vert[deform].clear()
            vert[deform][owner] = 1.0

    bm.to_mesh(mesh_obj.data)
    bm.free()
    mesh_obj.data.update()
    return len(seams)


def _face_bone_group(face, deform_layer, group_index_to_bone):
    # sum weights, don't vote per vert
    totals = {}
    for vert in face.verts:
        weights = vert[deform_layer] if deform_layer is not None else {}
        for group_index, weight in weights.items():
            if group_index in group_index_to_bone and weight > 0.0:
                totals[group_index] = totals.get(group_index, 0.0) + weight
    if not totals:
        return None
    return max(totals.items(), key=lambda item: (item[1], -item[0]))[0]


def _split_mesh_by_bone(context, bm, mesh_obj, armature_obj, fallback_bone_name: str, source_bones=None, warnings=None):
    bone_names = {bone.name for bone in armature_obj.data.bones}
    group_index_to_bone = {group.index: group.name for group in mesh_obj.vertex_groups if group.name in bone_names}
    if not group_index_to_bone:
        raise PluginError(f"'{mesh_obj.name}' has no vertex groups matching a bone in '{armature_obj.name}'.")

    # an imported face keeps its chunk's bone from the layout, not a weight
    # vote that could land it across the seam
    bone_of_slot = {}
    if source_bones:
        for slot_index, slot in enumerate(mesh_obj.material_slots):
            source = getattr(slot.material, "hm64_bk64_source_chunk", -1) if slot.material else -1
            if source in source_bones:
                bone_of_slot[slot_index] = source_bones[source]

    deform_layer = bm.verts.layers.deform.active
    bone_of_face, faces_by_bone = {}, {}
    unweighted = 0
    for face in bm.faces:
        bone_name = bone_of_slot.get(face.material_index)
        if bone_name is None:
            group_index = _face_bone_group(face, deform_layer, group_index_to_bone)
            if group_index is None:
                unweighted += 1
            bone_name = group_index_to_bone[group_index] if group_index is not None else fallback_bone_name
        bone_of_face[face] = bone_name
        faces_by_bone.setdefault(bone_name, []).append(face.index)

    # a face with nothing to vote on lands on the root, right for scenery and wrong for a limb
    if unweighted and warnings is not None:
        warnings.append(
            f"{unweighted} faces on '{mesh_obj.name}' carry no weight to a bone's vertex group "
            f"and went onto '{fallback_bone_name}'."
        )

    # a chunk carries one bone. A weld across a joint gets torn, except at
    # a bone and its parent, the one seam skinning blends.
    def family(name_a, name_b):
        bone_a, bone_b = armature_obj.data.bones[name_a], armature_obj.data.bones[name_b]
        return bone_a.parent == bone_b or bone_b.parent == bone_a

    seams = sum(
        1
        for edge in bm.edges
        if len(edge.link_faces) == 2
        and bone_of_face[edge.link_faces[0]] != bone_of_face[edge.link_faces[1]]
        and not (source_bones and family(bone_of_face[edge.link_faces[0]], bone_of_face[edge.link_faces[1]]))
    )
    if seams:
        raise PluginError(f"'{mesh_obj.name}' is welded across {seams} bone boundaries. Run Split Mesh At Bones.")

    parts = {}
    for bone_name, face_indices in faces_by_bone.items():
        part_obj = _bmesh_to_object(context, bm, f"bk64_{mesh_obj.name}_{bone_name}", mesh_obj, face_indices)
        if part_obj is not None:
            parts[bone_name] = [part_obj]
    return parts


def _subtree_points(index, children, chunk_points):
    """Every vertex the bone and everything under it draws, in BK units"""
    points = list(chunk_points.get(index, []))
    for child in children.get(index, []):
        points += _subtree_points(child, children, chunk_points)
    return points


def _stored_layout(root_obj):
    """The layout an imported model came with, or None.

    JSON, because a Blender custom property can't hold a nested tuple tree.
    """
    raw = root_obj.get(GEO_LAYOUT_PROP)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _relink_layout(records, from_source):
    """The stored layout with every original chunk index swapped for the new ones.

    None when nothing it draws survived, since a layout with no geometry left in
    it is worse than the flat one the bone tree gives.
    """
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
            elif kind == "refpoint":
                out.append(("refpoint", record[1], record[2], tuple(record[3])))
            else:
                out.append(tuple(record))
        return out

    relinked = relink(records)
    return relinked if kept else None


def _layout_refpoints(records):
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


def _geo_records(bones, chunks, armature_obj, rigged: bool, chunk_bounds=None):
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
                    f"Bone '{bones[index].name}' is a Level Of Detail with no Far Distance, and would never draw."
                )
            return [("lod", far, getattr(bone, "hm64_bk64_lod_near", 0.0), tuple(bones[index].position), records)]

        if geo_type == "DRAWDIST":
            if not points:
                raise PluginError(
                    f"Bone '{bones[index].name}' is a Draw Distance with no geometry under it to " "make a box from."
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
                    f"Bone '{bones[index].name}' is a Sort with {len(branches)} child bones, and it "
                    "orders exactly two."
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


def _to_bk_space(root_obj, scale: float):
    """Root local Blender space to BK model space, Y up and in BK units"""
    return (
        BLENDER_TO_BK
        @ mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4()
        @ root_obj.matrix_world.inverted()
    )


def read_collision_shapes(root_obj, scale: float):
    """The collision volumes under the root, as the unk14 section wants them"""
    to_bk = _to_bk_space(root_obj, scale)
    shapes = {"boxes": [], "cylinders": [], "spheres": []}

    for obj in root_obj.children_recursive:
        kind = obj.get(SHAPE_KIND)
        if kind is None or obj.type != "MESH":
            continue

        placement = to_bk @ obj.matrix_world
        center, rotation, obj_scale = placement.decompose()
        angles = rotation.to_euler("YXZ")
        # two degrees a step makes a full turn 180 of them. No vanilla shape
        # stores more, and wrapping at 256 sends a negative angle past one.
        turn = tuple(round(math.degrees(angle) / 2.0) % 180 for angle in (angles.x, angles.y, angles.z))
        bone = obj.parent_bone if obj.parent_type == "BONE" else ""
        code = obj.get("hm64_bk64_hit_code", 0xFF)

        local = [mathutils.Vector(corner) for corner in obj.bound_box]
        size = [
            (max(corner[axis] for corner in local) - min(corner[axis] for corner in local)) * abs(obj_scale[axis])
            for axis in range(3)
        ]

        if kind == "BOX":
            half = [size[axis] / 2.0 for axis in range(3)]
            # the corners are stored unturned and the box turns about its
            # point. Undo the turn to find where they sit before it.
            pivot = obj.get(SHAPE_PIVOT)
            pivot = mathutils.Vector(pivot) if pivot is not None else center
            resting = pivot + rotation.to_matrix().inverted() @ (center - pivot)
            shapes["boxes"].append(
                dict(
                    low=[resting[axis] - half[axis] for axis in range(3)],
                    high=[resting[axis] + half[axis] for axis in range(3)],
                    position=list(pivot),
                    rotation=turn,
                    code=code,
                    bone_name=bone,
                )
            )
        elif kind == "CYLINDER":
            shapes["cylinders"].append(
                dict(
                    radius=max(size[0], size[1]) / 2.0,
                    height=size[2],
                    position=list(center),
                    rotation=turn,
                    code=code,
                    bone_name=bone,
                )
            )
        elif kind == "SPHERE":
            shapes["spheres"].append(dict(radius=max(size) / 2.0, center=list(center), code=code, bone_name=bone))
        else:
            raise PluginError(
                f"'{obj.name}' is marked as a {kind} collision shape, which BK doesn't have. Use "
                "BOX, CYLINDER or SPHERE, or clear the marker."
            )

    if not any(shapes.values()):
        return None
    shapes["cull"] = 0  # the export fills this in once it knows the model's own radius
    return shapes


def read_collision_only(context, root_obj, scale: float):
    """(vertices, triangles) for the meshes marked collision only.

    Vertices are (s16 position, uv, color) like the drawn ones, triangles are
    (i0, i1, i2, flags, unk6). The export appends both to what the mesh drew.
    """
    to_bk = _to_bk_space(root_obj, scale)

    vertices, index_of, triangles = [], {}, []
    for obj in [root_obj] + list(root_obj.children_recursive):
        if obj.type != "MESH" or not obj.get(COLLISION_ONLY_PROP):
            continue

        # what the vertex carried before the import, white when it's new
        colors = obj.data.attributes.get(COLLISION_COLOR_ATTR)
        uvs = obj.data.attributes.get(COLLISION_UV_ATTR)

        bm = _evaluated_bmesh(context, obj, to_bk, True)
        try:
            for face in bm.faces:
                material = obj.material_slots[face.material_index].material if obj.material_slots else None
                surface = _surface_of_material(material) if material else None
                if surface is None:
                    raise PluginError(
                        f"'{obj.name}' is marked collision only but face {face.index} has no collision material. "
                        "Give every face a material with a Collision Type set, or unmark the object."
                    )
                corners = []
                for vert in face.verts:
                    key = tuple(s16(value) for value in vert.co)
                    if key not in index_of:
                        index_of[key] = len(vertices)
                        readable = colors is not None and vert.index < len(colors.data)
                        color = (
                            tuple(max(0, min(255, round(channel * 255))) for channel in colors.data[vert.index].color)
                            if readable
                            else (255, 255, 255, 255)
                        )
                        uv = (
                            tuple(s16(value) for value in uvs.data[vert.index].vector)
                            if uvs is not None and vert.index < len(uvs.data)
                            else (0, 0)
                        )
                        vertices.append((key, uv, color))
                    corners.append(index_of[key])
                triangles.append((corners[0], corners[1], corners[2], surface[0], surface[1]))
        finally:
            bm.free()

    return vertices, triangles


def _flatten_gfx_list(gfx_list, f3d, segments, seen=None):
    # BK walks from a start index until G_ENDDL. A sub list call has no target
    seen = seen if seen is not None else set()
    if id(gfx_list) in seen:
        raise PluginError(f"Recursive display list '{gfx_list.name}' cannot be flattened.")
    seen = seen | {id(gfx_list)}

    words = []
    for command in gfx_list.commands:
        if isinstance(command, SPDisplayList):
            words += _flatten_gfx_list(command.displayList, f3d, segments, seen)
        elif not isinstance(command, SPEndDisplayList):
            # big endian, and a macro can expand to several commands
            raw = command.to_binary(f3d, segments)
            words += [struct.unpack_from(">II", raw, offset) for offset in range(0, len(raw), 8)]
    return words


def _reads_texel1(f3d_mat):
    for cycle in (f3d_mat.combiner1, f3d_mat.combiner2):
        for name in ("A", "B", "C", "D", "A_alpha", "B_alpha", "C_alpha", "D_alpha"):
            if "TEXEL1" in getattr(cycle, name):
                return True
    return False


def _mip_pyramid(pixels: bytes) -> bytes:
    """The 16, 8, 4 and 2 pixel levels of a 32x32 RGBA16 base, padded out to the
    0x600 texels the mip load brings in"""

    def decode(data, size):
        out = []
        for index in range(size * size):
            value = (data[index * 2] << 8) | data[index * 2 + 1]
            out.append(((value >> 11) & 31, (value >> 6) & 31, (value >> 1) & 31, value & 1))
        return out

    def shrink(texels, size):
        half = size // 2
        out = []
        for y in range(half):
            for x in range(half):
                cells = [texels[(y * 2 + dy) * size + x * 2 + dx] for dy in (0, 1) for dx in (0, 1)]
                color = tuple(sum(cell[channel] for cell in cells) // 4 for channel in range(3))
                out.append(color + (1 if sum(cell[3] for cell in cells) >= 2 else 0,))
        return out

    level = decode(pixels, MIP_TEXTURE_DIM)
    size = MIP_TEXTURE_DIM
    data = bytearray()
    while size > 2:
        level = shrink(level, size)
        size //= 2
        for red, green, blue, alpha in level:
            value = (red << 11) | (green << 6) | (blue << 1) | alpha
            data += bytes((value >> 8, value & 0xFF))
    data += bytes((0x600 - MIP_TEXTURE_DIM * MIP_TEXTURE_DIM) * 2 - len(data))
    return bytes(data)


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


def _split_skinning(words, vertices, owner_of_pos, parent_bone):
    """The chunk as SKINNING's two lists, or None when there's nothing to blend.

    The first list's POPMTX puts its loads under the parent's matrix, the
    handler pushes the bone's own back for the second, and triangles there mix
    both. That's BK's joint blend, and one rigid list tears the shoulder open.
    """
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


def _fixup_chunk(words, texture_count: int, rendermode_entry, white_offset=None, mip_textures=frozenset()):
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


def _count_triangles(words):
    total = 0
    for w0, _w1 in words:
        opcode = (w0 >> 24) & 0xFF
        if opcode == OP_TRI1:
            total += 1
        elif opcode == OP_TRI2:
            total += 2
    return total


def _collect_textures(
    fModel: FModel, embed_images: bool, image_folds=None, opaque_images=None, mip_images=None, animated=None
):
    # a resource puts images in _tex_<i> siblings behind segment 0xFF, a ROM
    # puts everything in the blob behind segment 2
    resources, infos, blob = [], [], bytearray()
    animated_offsets = {}

    palette_size = {}
    for key, fImage in fModel.textures.items():
        otex_format = F3D_FMT_TO_OTEX.get((fImage.fmt, fImage.bitSize))
        if otex_format is None:
            raise PluginError(
                f"Texture '{fImage.name}' uses {fImage.fmt}/{fImage.bitSize}, which has no BK equivalent."
            )
        if isinstance(key, FPaletteKey):
            continue
        if embed_images and otex_format not in BIN_TEX_FORMATS:
            raise PluginError(
                f"Texture '{fImage.name}' is {otex_format}, which BKTextureInfo has no type bit "
                "for. Use RGBA16, RGBA32, IA8, CI4 or CI8."
            )
        if embed_images and _hd_scale_of(fImage) is not None:
            raise PluginError(
                f"Texture '{fImage.name}' is HD. A .bin holds its images as bare bytes in the "
                "model's own blob, with no resource header to carry the scales. Export o2r."
            )
        if otex_format in PALETTED_FORMATS:
            shared = key.imagesSharingPalette or (key.image,)
            palette_size[shared] = max(palette_size.get(shared, 0), BK_PALETTE_SIZE[otex_format])

    palette_offset, palette_colors, palette_data, palette_address = {}, {}, {}, {}
    for key, fImage in fModel.textures.items():
        if not isinstance(key, FPaletteKey):
            continue
        if not fImage.converted:
            raise PluginError(f"Palette '{fImage.name}' was not converted to N64 format.")
        shared_key = key.imagesSharingPalette
        padded = bytes(fImage.data) + bytes(palette_size.get(shared_key, 0) - len(fImage.data))
        if embed_images:
            opaque = all((opaque_images or {}).get(image, True) for image in shared_key or ())
            padded = _flatten_shade(
                padded, "RGBA16", (image_folds or {}).get(shared_key[0] if shared_key else None), opaque
            )
        palette_colors[shared_key] = fImage.height
        palette_data[shared_key] = padded
        if not embed_images:
            palette_offset[shared_key] = len(blob)
            blob.extend(padded)

    for key, fImage in fModel.textures.items():
        if isinstance(key, FPaletteKey):
            continue
        otex_format = F3D_FMT_TO_OTEX[(fImage.fmt, fImage.bitSize)]
        if fImage.width > MAX_TEXTURE_DIM or fImage.height > MAX_TEXTURE_DIM:
            raise PluginError(
                f"Texture '{fImage.name}' is {fImage.width}x{fImage.height}, and BK stores each "
                f"side in one byte. Scale it under {MAX_TEXTURE_DIM}."
            )
        if not fImage.converted:
            raise PluginError(f"Texture '{fImage.name}' was not converted to N64 format.")

        paletted = otex_format in PALETTED_FORMATS
        shared = key.imagesSharingPalette or (key.image,)
        if paletted and shared not in palette_data:
            raise PluginError(f"Texture '{fImage.name}' is {otex_format} but exported without a palette.")

        animation = (animated or {}).get(key.image)
        if animation is not None:
            slot, frames, _rate = animation
            if otex_format not in ANIM_FRAME_FORMATS:
                raise PluginError(
                    f"Animated texture '{fImage.name}' is {otex_format}. A CI frame would have to "
                    "animate its palette alongside it. Use RGBA16, RGBA32 or IA8."
                )
            if _hd_scale_of(fImage) is not None:
                raise PluginError(
                    f"Animated texture '{fImage.name}' is HD. The game slides the segment on by a "
                    "frame of N64 sized bytes and a raw strip no longer matches. Scale it to fit TMEM."
                )
            pixels = _strip_pixels(fImage, frames, otex_format)
            strip_offset = len(blob)
            if strip_offset > 0xFFFFFF:
                raise PluginError(f"'{fImage.name}' lands past the 16MB a segment can address. Use fewer textures.")
            blob.extend(pixels)
            # the game binds the strip by segment and slides it a frame at a time
            fImage.startAddress = ((SEG_ANIM_BASE - slot) << 24) | strip_offset
            frame_bytes = len(pixels) // len(frames)
            animated_offsets[slot] = (strip_offset, frame_bytes, len(frames))
            if not embed_images:
                resources.append(
                    _write_texture_resource(otex_format, fImage.width, fImage.height * len(frames), pixels)
                )
            infos.append(
                dict(
                    type=BK_TEX_TYPE.get(otex_format, 0),
                    width=fImage.width,
                    height=fImage.height * len(frames),
                    colors=0,
                    offset=strip_offset,
                )
            )
            continue

        if embed_images:
            # the game's layout puts a palette right ahead of its image, even
            # if a shared one gets written twice
            entry_offset = len(blob)
            if paletted:
                palette = palette_data[shared]
                blob.extend(palette)
                palette_address.setdefault(shared, entry_offset)
            image_offset = len(blob)
            pixels = bytes(fImage.data)
            if not paletted:  # a paletted image is recolored through its palette
                opaque = (opaque_images or {}).get(key.image, True)
                pixels = _flatten_shade(pixels, otex_format, (image_folds or {}).get(key.image), opaque)
            blob.extend(pixels)
            fImage.startAddress = (SEG_TEX_BLOB << 24) | image_offset
        else:
            image_offset = None
            fImage.startAddress = (SEG_TEX << 24) | len(resources)
            pixels = bytes(fImage.data)
            hd_scale = _hd_scale_of(fImage)
            if mip_images and key.image in mip_images:
                if hd_scale is not None:
                    raise PluginError(
                        f"Texture '{fImage.name}' is HD and mipmapped. The pyramid needs N64 sized "
                        "pixels an HD image no longer carries. Drop TEXEL0 or scale it to fit TMEM."
                    )
                pixels += _mip_pyramid(pixels)
            resources.append(_write_texture_resource(otex_format, fImage.width, fImage.height, pixels, hd_scale))

        # one entry per texture, in display list order. Fewer would slide the
        # indices and send a CI texture to the wrong palette.
        infos.append(
            dict(
                type=BK_TEX_TYPE.get(otex_format, 0),
                width=fImage.width,
                height=fImage.height,
                colors=palette_colors[shared] if paletted else 0,
                offset=entry_offset if embed_images else (palette_offset[shared] if paletted else 0),
            )
        )

    white_offset = None
    if embed_images:
        white_offset = len(blob)
        blob.extend(bytes([0xFF]) * (WHITE_TEXTURE_DIM * WHITE_TEXTURE_DIM * 2))
        infos.append(
            dict(
                type=BK_TEX_TYPE["RGBA16"],
                width=WHITE_TEXTURE_DIM,
                height=WHITE_TEXTURE_DIM,
                colors=0,
                offset=white_offset,
            )
        )

    # segment 2 is bound to the blob itself, making an offset into it the address
    if embed_images:
        palette_offset = palette_address
    for key, fImage in fModel.textures.items():
        if isinstance(key, FPaletteKey):
            fImage.startAddress = (SEG_TEX_BLOB << 24) | palette_offset[key.imagesSharingPalette]

    return resources, infos, bytes(blob), white_offset, animated_offsets


def _check_cycle_type(mesh_objects):
    """BK draws models in 2 cycle and a 1 cycle material renders black"""
    offenders = []
    for material, f3d_mat in _f3d_materials(mesh_objects):
        if f3d_mat.rdp_settings.g_mdsft_cycletype != CYCLE_TYPE_2CYCLE and material.name not in offenders:
            offenders.append(material.name)
    if offenders:
        listed = "\n  ".join(offenders)
        raise PluginError(f"BK draws models in 2 cycle and these would render black. Set Cycle Type:\n  {listed}")


def _check_large_textures(mesh_objects):
    """BK binds a texture whole and a mesh tiled across one can't say which tile"""
    offenders = []
    for mesh_obj in mesh_objects:
        for slot in mesh_obj.material_slots:
            material = slot.material
            if material is None or not getattr(material, "is_f3d", False) or material.mat_ver <= 3:
                continue
            if material.f3d_mat.use_large_textures and material.name not in offenders:
                offenders.append(material.name)
    if offenders:
        listed = "\n  ".join(offenders)
        raise PluginError(
            "BK binds a texture whole. Turn off Large Texture Mode and scale the image to fit " f"TMEM:\n  {listed}"
        )


def _draw_layer_of(material, scene_layer: str):
    layer = getattr(material, "hm64_bk64_draw_layer", "SCENE") if material is not None else "SCENE"
    return scene_layer if layer == "SCENE" else layer


def _draw_key_of(material, scene_layer: str):
    """(draw layer, source chunk) a material asks for, and chunks split where it differs.

    The source chunk is the display list an imported face was drawn in. Keeping
    those faces together lets the layout a model came with be written again with
    the new indices.
    """
    source = getattr(material, "hm64_bk64_source_chunk", -1) if material is not None else -1
    return (_draw_layer_of(material, scene_layer), source)


def _split_by_draw_key(context, part_obj, scene_layer: str, temp_objects):
    """The part as (key, object) pairs, cut where its materials disagree"""
    # a chunk jumps into one render mode entry. Other faces need their own.
    key_of_slot = {
        index: _draw_key_of(slot.material, scene_layer) for index, slot in enumerate(part_obj.material_slots)
    }
    default = (scene_layer, -1)
    part_obj.data.calc_loop_triangles()
    wanted = {key_of_slot.get(tri.material_index, default) for tri in part_obj.data.loop_triangles}
    if len(wanted) <= 1:
        return [(wanted.pop() if wanted else default, part_obj)]

    pieces = []
    for key in sorted(wanted):
        bm = bmesh.new()
        bm.from_mesh(part_obj.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(
            bm,
            geom=[face for face in bm.faces if key_of_slot.get(face.material_index, default) != key],
            context="FACES",
        )
        piece = _bmesh_to_object(context, bm, f"{part_obj.name}_{key[0].lower()}_{key[1]}", part_obj)
        bm.free()
        if piece is not None:
            temp_objects.append(piece)
            pieces.append((key, piece))
    return pieces


def _check_world_defaults(scene):
    """The defaults a material is compared against, which have to be BK's own state"""
    # picking BK64 fills them in, but a scene with no world has nowhere to keep them
    if scene.world is None:
        raise PluginError("This scene has no world to keep the RDP defaults in. Add one, then pick BK64 again.")

    defaults = scene.world.rdp_defaults.to_dict()
    wrong = [
        key
        for key, expected in bk64_world_defaults["geometryMode"].items()
        if bool(defaults["geometryMode"].get(key, False)) != expected
    ]
    wrong += [
        key
        for key, expected in bk64_world_defaults["otherModeH"].items()
        if defaults["otherModeH"].get(key) != expected
    ]
    wrong += [
        key
        for key, expected in bk64_world_defaults.get("otherModeL", {}).items()
        if defaults["otherModeL"].get(key) != expected
    ]
    if wrong:
        listed = ", ".join(wrong)
        raise PluginError(f"This world's RDP defaults aren't BK's state. Wrong: {listed}. Pick BK64 again to reset.")


def _combiner_fold(f3d_mat):
    # LERP is Fast64's decal idiom, where the texture's alpha picks a flat base
    # color or the detail on top
    cycle = f3d_mat.combiner1
    signature = (cycle.A, cycle.B, cycle.C, cycle.D)
    if signature == ("TEXEL0", "SHADE", "TEXEL0_ALPHA", "SHADE"):
        return "LERP"
    if signature == ("TEXEL0", "0", "SHADE", "0"):
        return "MULTIPLY"
    return None


def _image_folds(mesh_objects, shade_by_material):
    """The (shade, fold) each image is drawn with, keyed by the image"""
    # an image drawn two ways can't be baked either way. It keeps its colors.
    folds = {}
    for material, f3d_mat in _f3d_materials(mesh_objects):
        fold = _combiner_fold(f3d_mat)
        shade = shade_by_material.get(material.name, (255, 255, 255, 255))[:3]
        for tex_slot in (f3d_mat.tex0, f3d_mat.tex1):
            if tex_slot.tex is None or not tex_slot.tex_set:
                continue
            if tex_slot.tex_format not in SHADE_FOLD_FORMATS:
                # nothing to bake into
                continue
            folds.setdefault(tex_slot.tex, set()).add((shade, fold))
    return {image: next(iter(ways)) for image, ways in folds.items() if len(ways) == 1}


def _image_opacity(mesh_objects, scene_layer: str):
    """Whether each image is only ever drawn on the opaque layer, keyed by the image"""
    opaque = {}
    for material, f3d_mat in _f3d_materials(mesh_objects):
        layer = _draw_layer_of(material, scene_layer)
        for tex_slot in (f3d_mat.tex0, f3d_mat.tex1):
            if tex_slot.tex is None or not tex_slot.tex_set:
                continue
            opaque[tex_slot.tex] = opaque.get(tex_slot.tex, True) and layer == "OPAQUE"
    return opaque


def _flatten_shade(data: bytes, otex_format: str, fold, opaque: bool):
    # the game does this with the combiner, a plain texture viewer doesn't
    if fold is None:
        return data
    shade, mode = fold
    if mode is None or (shade == (255, 255, 255) and not opaque):
        return data

    out = bytearray(data)
    if otex_format == "RGBA32":
        for i in range(0, len(out), 4):
            for channel in range(3):
                if mode == "LERP":
                    out[i + channel] = out[i + channel] if out[i + 3] > 127 else shade[channel]
                else:
                    out[i + channel] = out[i + channel] * shade[channel] // 255
            if opaque:
                out[i + 3] = 255
        return bytes(out)

    # RGBA16, either the image itself or a palette entry
    for i in range(0, len(out) - 1, 2):
        value = (out[i] << 8) | out[i + 1]
        channels = [(value >> 11) & 31, (value >> 6) & 31, (value >> 1) & 31]
        if mode == "LERP" and not value & 1:
            channels = [shade[c] * 31 // 255 for c in range(3)]
        elif mode == "MULTIPLY":
            channels = [channels[c] * shade[c] // 255 for c in range(3)]
        alpha = 1 if opaque else value & 1
        value = (channels[0] << 11) | (channels[1] << 6) | (channels[2] << 1) | alpha
        out[i] = value >> 8
        out[i + 1] = value & 0xFF
    return bytes(out)


def _strip_pixels(fImage, frames, otex_format: str):
    """Every frame's N64 bytes end to end, frame 0 first"""
    from ...f3d.f3d_texture_writer import writeNonCITextureData

    first = bytes(fImage.data)  # frame 0 is already converted, keep it exactly
    encoded = bytearray(first)
    for frame in frames[1:]:
        spare = FImage(frame.name, fImage.fmt, fImage.bitSize, frame.size[0], frame.size[1], None)
        writeNonCITextureData(frame, spare, otex_format)
        if len(spare.data) != len(first):
            raise PluginError(
                f"Frame '{frame.name}' encodes to {len(spare.data)} bytes and frame 0 to {len(first)}. "
                "Every frame has to be the same size and format."
            )
        encoded += spare.data
    return bytes(encoded)


def _animated_slots(fModel: FModel):
    """{frame 0's image: (slot, [frames], rate)} for every animated material.

    Keyed by the Blender image so the texture pass can recognize the one it's
    converting. The rest of the frames follow frame 0 into the strip.
    """
    animated, claimed = {}, {}
    for key, value in fModel.materials.items():
        material = key[0]
        if getattr(material, "hm64_bk64_anim_tex", "NONE") == "NONE":
            continue

        which = material.hm64_bk64_anim_tex
        source = getattr(material.f3d_mat, which.lower()).tex
        frames = [entry.image for entry in material.flipbookGroup.flipbook0.textures if entry.image]
        slot = material.hm64_bk64_anim_slot

        if source is None:
            raise PluginError(f"'{material.name}' animates {which} but has no texture there.")
        if len(frames) < 2:
            raise PluginError(
                f"'{material.name}' is animated but lists {len(frames)} of the two frames it needs "
                "at least. Add them under Animated Texture, starting with the one the material uses."
            )
        if frames[0] != source:
            raise PluginError(
                f"'{material.name}' lists '{frames[0].name}' first but samples '{source.name}'. The "
                "first frame has to be the texture the material uses."
            )
        sizes = {tuple(frame.size) for frame in frames}
        if len(sizes) > 1:
            raise PluginError(f"'{material.name}' has frames of {len(sizes)} different sizes. Every frame is one tile.")
        if slot in claimed and claimed[slot] != frames:
            raise PluginError(
                f"'{material.name}' and '{claimed[slot][0].name}'s material both drive slot {slot} "
                "with different frames. Give one of them another slot."
            )
        claimed[slot] = frames
        animated[frames[0]] = (slot, frames, material.hm64_bk64_anim_rate)
    return animated


def _surface_of_material(material):
    """(flags, unk6) for a material that asks for collision, None for one that doesn't"""
    raw = getattr(material, "hm64_bk64_collision_raw", 0)
    if raw:
        # an imported surface, kept exactly. Vanilla uses flag words the three
        # choices can't describe.
        return (raw & 0xFFFFFFFF, getattr(material, "hm64_bk64_collision_unk6", 0))
    collision = getattr(material, "hm64_bk64_collision_type", "NONE")
    if collision == "NONE":
        return None
    flags = (
        (BK_COLLISION_FLAG_BASE << 24)
        | (BK_COLLISION_TYPE[collision] << 16)
        | (BK_SOUND_TYPE[getattr(material, "hm64_bk64_sound_type", "NORMAL")] << 8)
        | BK_GROUND_TYPE[getattr(material, "hm64_bk64_ground_type", "NORMAL")]
    )
    return (flags, 0)


def _material_surfaces(fModel: FModel):
    """The collision a material asks for, keyed by FMaterial id"""
    surfaces = {}
    for key, value in fModel.materials.items():
        surface = _surface_of_material(key[0])
        if surface is not None:
            surfaces[id(value[0])] = surface
    return surfaces


def _collision_triangles(dl_words, owners, surfaces):
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


def _write_collision(triangles):
    """BKCollisionList, one cell holding every triangle"""
    data = bytearray()
    data.extend(struct.pack("<hhhhhh", 0, 0, 0, 0, 0, 0))  # cell bounds, unused at scale 0
    data.extend(struct.pack("<HHHHH", 0, 0, BK_COLLISION_SINGLE_CELL_SCALE, 1, len(triangles)))
    data.extend(struct.pack("<HH", 0, len(triangles)))  # the one cell, holding all of them
    for indices, flags, unk6 in triangles:
        data.extend(struct.pack("<HHHHI", indices[0], indices[1], indices[2], unk6, flags & 0xFFFFFFFF))
    return bytes(data)


def _material_lights(fModel: FModel):
    """The lighting each lit FMaterial was authored with, keyed by id"""
    # BK loads no lights. The shading gets worked out here instead.
    lights = {}
    for key, value in fModel.materials.items():
        material = key[0]
        f3d_mat = _f3d_settings(material)
        if not getattr(f3d_mat.rdp_settings, "g_lighting", False):
            continue

        sources = []
        if getattr(f3d_mat, "use_default_lighting", False):
            sources.append((exportColor(f3d_mat.default_light_color), DEFAULT_LIGHT_DIR))
        else:
            for index in range(1, 8):
                light = getattr(f3d_mat, f"f3d_light{index}", None)
                if light is None:
                    continue
                direction = normToSigned8Vector(getObjDirectionVec(lightDataToObj(light), True))
                sources.append((exportColor(light.color), direction))
        lights[id(value[0])] = (exportColor(f3d_mat.ambient_light_color), sources)
    return lights


def _material_base_colors(fModel: FModel):
    """Fully lit color per material name, what a ROM texture fold tints against"""
    # per vertex shading can't fold in. The fold takes the surface's color.
    colors = {}
    for key, _value in fModel.materials.items():
        material = key[0]
        f3d_mat = _f3d_settings(material)
        if not getattr(f3d_mat.rdp_settings, "g_lighting", False):
            continue
        if not getattr(f3d_mat, "use_default_lighting", False):
            continue
        light = f3d_mat.default_light_color
        ambient = f3d_mat.ambient_light_color
        colors[material.name] = tuple(exportColor([min(1.0, light[i] + ambient[i]) for i in range(3)])) + (255,)
    return colors


def _shade_from_normal(packed, ambient, sources):
    """Ambient plus every light that faces the vertex, the N64 lighting sum"""
    # a lit Vtx keeps its normal where the shade is about to go
    normal = [((channel - 0x100 if channel > 0x7F else channel) / 127.0) for channel in packed[:3]]
    shade = list(ambient)
    for color, direction in sources:
        length = math.sqrt(sum(axis * axis for axis in direction))
        if length == 0.0:
            continue
        facing = sum(normal[axis] * direction[axis] / length for axis in range(3))
        if facing <= 0.0:
            continue
        for channel in range(3):
            shade[channel] += color[channel] * facing
    return tuple(min(255, int(round(channel))) for channel in shade) + (255,)


def _written_key(position, scale_matrix=None):
    """The Vtx coordinate a point is written at, which binding and mesh lists key by"""
    # scale then round, the order F3DVert.convertPosition uses. Rounding first
    # keys a point on a half unit to a coordinate no vertex was written at.
    if scale_matrix is not None:
        position = scale_matrix @ position
    return tuple(s16(value) for value in position)


def _grouped_vertices(context, mesh_objects, space_matrix, scale_matrix, value_of):
    """(written position, [(value, weight)]) for every vertex in a group value_of names.

    Keyed by coordinate, since that's what both sections using it bind by. Read
    the evaluated mesh or a mirrored half comes back empty.
    """
    for mesh_obj in mesh_objects:
        groups = {}
        for group in mesh_obj.vertex_groups:
            value = value_of(group)
            if value is not None:
                groups[group.index] = value
        if not groups:
            continue
        bm = _evaluated_bmesh(context, mesh_obj, space_matrix, True)
        try:
            deform = bm.verts.layers.deform.active
            if deform is None:
                continue
            for vertex in bm.verts:
                held = [
                    (groups[index], weight)
                    for index, weight in vertex[deform].items()
                    if index in groups and weight > 0.0
                ]
                if held:
                    yield _written_key(vertex.co, scale_matrix), held
        finally:
            bm.free()


def _vertex_bones(context, mesh_objects, bones, space_matrix, scale_matrix):
    """{written position: bone table index} from the meshes' own vertex groups"""
    index_of_bone = {bone.name: index for index, bone in enumerate(bones)}
    bound = {}
    for key, held in _grouped_vertices(
        context, mesh_objects, space_matrix, scale_matrix, lambda g: index_of_bone.get(g.name)
    ):
        weights = {}
        for bone_index, weight in held:
            weights[bone_index] = weights.get(bone_index, 0.0) + weight
        bound[key] = max(weights.items(), key=lambda item: (item[1], -item[0]))[0]
    return bound


def _vertex_bone_entries(vertices, bound, warnings, space_matrix):
    """One entry per bound coordinate, listing every vertex written at it"""
    at_position = {}
    loose = set()
    for index, vertex in enumerate(vertices):
        key = _written_key(vertex[0])
        if key in bound:
            at_position.setdefault(key, []).append(index)
        else:
            loose.add(key)

    # the game only moves vertices an entry lists, so one left out tears its triangle.
    # Three vanilla models do that on parts that never move, so warn, don't refuse.
    if loose:
        # in world space, since BK units mean nothing in the N panel
        to_blender = space_matrix.inverted()
        listed = "; ".join(
            "({:.3f}, {:.3f}, {:.3f})".format(*(to_blender @ mathutils.Vector(position)))
            for position in sorted(loose)[:3]
        )
        warnings.append(
            f"{len(loose)} vertex positions carry no weight to a bone's vertex group, at {listed} "
            "in world space. Bind Vertices leaves those at rest while the rest of the model animates."
        )

    entries = []
    for position, indices in at_position.items():
        # the count is one byte. A busier coordinate needs several entries.
        for start in range(0, len(indices), 0x7F):
            entries.append(dict(coord=position, bone=bound[position], vertices=indices[start : start + 0x7F]))
    return entries


def _mesh_group_uid(name: str):
    if not name.startswith(MESH_GROUP_PREFIX):
        return None
    digits = name[len(MESH_GROUP_PREFIX) :].split(".")[0]  # Blender appends .001 to a name already taken
    return int(digits) if digits.lstrip("-").isdigit() else None


def _checked_mesh_uid(group):
    """The mesh uid a group names, refusing one the section can't store"""
    uid = _mesh_group_uid(group.name)
    if uid is not None and not -0x8000 <= uid <= 0x7FFF:
        raise PluginError(f"Vertex group '{group.name}' names mesh {uid}, past the s16 BKMesh.uid holds.")
    return uid


def _mesh_list_positions(context, mesh_objects, space_matrix, scale_matrix):
    """{written position: {mesh uid}} from the meshes' own mesh list groups"""
    at_position = {}
    for key, held in _grouped_vertices(context, mesh_objects, space_matrix, scale_matrix, _checked_mesh_uid):
        at_position.setdefault(key, set()).update(uid for uid, _weight in held)
    return at_position


def _mesh_list_entries(vertices, uids_at_position):
    """One mesh per uid, listing every vertex written at its coordinates"""
    order, holding = [], {}
    for index, vertex in enumerate(vertices):
        key = _written_key(vertex[0])
        for uid in sorted(uids_at_position.get(key, ())):
            if uid not in holding:
                order.append(uid)
                holding[uid] = []
            holding[uid].append(index)
    return [dict(uid=uid, vertices=holding[uid]) for uid in order]


def _collect_vertices(fMeshes, shade_colors, force_unlit: bool, reflective=frozenset()):
    # startAddress is a byte offset, so SPVertex.to_binary emits the segment 1
    # address directly and nothing needs patching after
    vertices, owners, spans = [], [], {}
    for fMesh in fMeshes:
        spans[id(fMesh)] = len(vertices)
        for triGroup in fMesh.triangleGroups:
            triGroup.vertexList.startAddress = len(vertices) * VTX_SIZE
            first = len(vertices)
            # unlit SHADE is vertex color, where a lit Vtx holds a normal.
            # a reflective material keeps its normals. Texture gen turns them
            # into the reflection, and a baked color has nothing to reflect.
            bake = force_unlit and id(triGroup.fMaterial) not in reflective
            lighting = shade_colors.get(id(triGroup.fMaterial)) if bake else None
            for vtx in triGroup.vertexList.vertices:
                color = (
                    _shade_from_normal(vtx.colorOrNormal, *lighting)
                    if lighting is not None
                    else tuple(vtx.colorOrNormal)
                )
                vertices.append((tuple(vtx.position), vtx.packedNormal, tuple(vtx.uv), color))
            owners.append((first, len(vertices), id(triGroup.fMaterial)))
        spans[id(fMesh)] = (spans[id(fMesh)], len(vertices))
    return vertices, owners, spans


def _layout_bone_of_source(records, bones):
    """({chunk index: bone name}, {chunk index: parent matrix}) from the layout.

    The parent comes from the layout's own nesting, not the bone table: BK's
    paired bones mean a bone's table parent often has no BONE command of its
    own, and the matrix a POPMTX exposes is the enclosing one.
    """
    index_of_matrix = {bone_index: bone.name for bone_index, bone in enumerate(bones)}
    bone_of, parent_of = {}, {}
    for _kind, indices, matrix, parent, _record in layout_records(records):
        for index in indices:
            if matrix in index_of_matrix:
                bone_of[index] = index_of_matrix[matrix]
            if parent is not None:
                parent_of[index] = parent
    return bone_of, parent_of


def _gather_parts(
    context,
    root_obj,
    mesh_objects,
    armature_obj,
    bone_matrix,
    to_bk_space,
    temp_objects,
    bind: bool = False,
    source_bones=None,
    warnings=None,
):
    """Groups the geometry by bone name, building the temporary meshes"""
    # bind rigging skips the grouping, its vertices carry the rig instead
    if armature_obj is None or bind:
        # one implicit bone, same code path builds the chunks
        if bind:  # the real table, since the vertices name its entries
            bones = build_bone_table(armature_obj, bone_matrix)[0]
        else:
            bones = [BK64Bone(root_obj.name, (0.0, 0.0, 0.0), 1, NO_PARENT)]
        holder = bones[0].name
        meshes_by_bone = {holder: []}
        for mesh_obj in mesh_objects:
            bm = _evaluated_bmesh(context, mesh_obj, to_bk_space, bind)
            try:
                part = _bmesh_to_object(context, bm, f"bk64_{mesh_obj.name}", mesh_obj)
            finally:
                bm.free()
            if part is not None:
                temp_objects.append(part)
                meshes_by_bone[holder].append(part)
        return bones, meshes_by_bone

    bones, _index_of_name = build_bone_table(armature_obj, bone_matrix)
    root_bone_name = bones[0].name
    meshes_by_bone = {}
    for mesh_obj in mesh_objects:
        bm = _evaluated_bmesh(context, mesh_obj, to_bk_space, True)
        try:
            if mesh_obj.parent_type == "BONE" and mesh_obj.parent_bone:
                part = _bmesh_to_object(context, bm, f"bk64_{mesh_obj.name}", mesh_obj)
                if part is not None:
                    temp_objects.append(part)
                    meshes_by_bone.setdefault(mesh_obj.parent_bone, []).append(part)
                continue
            split = _split_mesh_by_bone(context, bm, mesh_obj, armature_obj, root_bone_name, source_bones, warnings)
            for bone_name, parts in split.items():
                temp_objects += parts
                meshes_by_bone.setdefault(bone_name, []).extend(parts)
        finally:
            bm.free()
    return bones, meshes_by_bone


def export_bk64_model(context, root_obj, settings, shapes=None, collision_only=None):
    """Builds the whole resource family as {suffix: bytes}.

    Keys are "" for the model, then "_VTX", "_GEO" and "_tex_<i>".
    """
    scale = settings.scale
    transform_matrix = mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4()

    armature_obj = root_obj if root_obj.type == "ARMATURE" else None
    mesh_objects = (
        [root_obj]
        if root_obj.type == "MESH"
        else [child for child in root_obj.children_recursive if child.type == "MESH"]
    )
    mesh_objects = [
        mesh_obj for mesh_obj in mesh_objects if not mesh_obj.ignore_render and not mesh_obj.get(COLLISION_ONLY_PROP)
    ]
    if not mesh_objects:
        raise PluginError(f"Nothing to export, '{root_obj.name}' has no mesh geometry.")

    _check_world_defaults(context.scene)
    _check_cycle_type(mesh_objects)
    _check_large_textures(mesh_objects)
    culling = [obj.name for obj in mesh_objects if obj.use_f3d_culling]
    if culling:
        listed = "\n  ".join(culling)
        raise PluginError(f"Turn off Use F3D Culling on these, BK culls off its own center and radius:\n  {listed}")

    # WriteAll emits a blanket othermode-H and leaks it, differing-and-revert
    # writes only what the world defaults don't cover
    fModel = FModel(settings.name, DLFormat.Static, GfxMatWriteMethod.WriteDifferingAndRevert)
    # BK's own space, worked out from the scene rather than by turning it
    to_bk_space = _to_bk_space(root_obj, 1.0)
    # head_local already sits in armature space and needs only the turn and the scale
    bone_matrix = transform_matrix @ BLENDER_TO_BK

    temp_objects = []
    try:
        bind = armature_obj is not None and settings.rigging == "BIND"
        rigged = armature_obj is not None and not bind
        # every model keeps its layout. No bound or static one draws under a
        # BONE, and what is left addresses chunks and relinks the same way.
        stored = _stored_layout(root_obj)
        source_bones, source_parents = None, {}
        if stored is not None and rigged:  # only a split mesh gets cut along these
            table = build_bone_table(armature_obj, bone_matrix)[0]
            source_bones, source_parents = _layout_bone_of_source(stored, table)
        bones, meshes_by_bone = _gather_parts(
            context,
            root_obj,
            mesh_objects,
            armature_obj,
            bone_matrix,
            to_bk_space,
            temp_objects,
            bind,
            source_bones,
            settings.warnings,
        )

        # bone table order, keeping chunk order and bone order in step
        chunk_fMeshes = []
        ordered_fMeshes = []
        for bone_index, bone in enumerate(bones):
            parts = meshes_by_bone.get(bone.name)
            if not parts:
                continue
            if bone_index > MAX_DRAWABLE_BONE_INDEX:
                raise PluginError(
                    f"Bone '{bone.name}' is entry {bone_index} in the bone table, and only the first "
                    f"{MAX_DRAWABLE_BONE_INDEX + 1} can own geometry."
                )
            by_layer = {}
            for part in parts:
                for layer, piece in _split_by_draw_key(context, part, settings.draw_layer, temp_objects):
                    infoDict = getInfoDict(piece)
                    triConverterInfo = TriangleConverterInfo(piece, None, fModel.f3d, transform_matrix, infoDict)
                    fMeshes = saveStaticModel(
                        triConverterInfo,
                        fModel,
                        piece,
                        transform_matrix,
                        f"{settings.name}_{bone.name}",
                        True,  # convertTextureData, we need N64 bytes not a png
                        False,  # revertMatAtEnd
                        None,
                    )
                    if fMeshes:
                        by_layer.setdefault(layer, []).extend(fMeshes.values())
            for layer in sorted(by_layer):
                chunk_fMeshes.append((bone_index, layer, by_layer[layer]))
                ordered_fMeshes += by_layer[layer]

        if not ordered_fMeshes:
            raise PluginError("Nothing was exported. Check that the mesh has faces and F3D materials.")

        rom_format = settings.file_format == "BIN"
        shade_colors = _material_lights(fModel)
        shade_by_material = _material_base_colors(fModel)
        image_folds = _image_folds(mesh_objects, shade_by_material) if rom_format else None
        opaque_images = _image_opacity(mesh_objects, settings.draw_layer) if rom_format else None

        # a TEXEL1 combiner blends between the wrap DL's tiles, so it renders
        # from tile 2 at level 2 and its sibling carries the pyramid
        mip_images = set()
        for key, value in fModel.materials.items():
            material = key[0]
            f3d_mat = _f3d_settings(material)
            if not any(
                "TEXEL" in getattr(cycle, name)
                for cycle in (f3d_mat.combiner1, f3d_mat.combiner2)
                for name in ("A", "B", "C", "D", "A_alpha", "B_alpha", "C_alpha", "D_alpha")
            ):
                # the combiner never samples, and vanilla draws these with the
                # texture unit off rather than merely unused
                for dl_name in ("material", "mat_only_DL", "texture_DL"):
                    gfx_list = getattr(value[0], dl_name, None)
                    if gfx_list is None:
                        continue
                    for command in gfx_list.commands:
                        if isinstance(command, SPTexture):
                            command.on = 0
        if settings.mipmap and not rom_format:
            for key, value in fModel.materials.items():
                material = key[0]
                f3d_mat = _f3d_settings(material)
                image = f3d_mat.tex0.tex
                if image is None or not _reads_texel1(f3d_mat):
                    continue
                if tuple(image.size) != (MIP_TEXTURE_DIM, MIP_TEXTURE_DIM) or f3d_mat.tex0.tex_format != "RGBA16":
                    continue
                mip_images.add(image)
                for dl_name in ("material", "mat_only_DL", "texture_DL", "revert"):
                    gfx_list = getattr(value[0], dl_name, None)
                    if gfx_list is None:
                        continue
                    for command in gfx_list.commands:
                        if isinstance(command, SPTexture):
                            command.level, command.tile = MIP_SPTEXTURE_LEVEL, MIP_SPTEXTURE_TILE

        animated = _animated_slots(fModel)
        texture_resources, tex_infos, tex_blob, white_offset, animated_offsets = _collect_textures(
            fModel, rom_format, image_folds, opaque_images, mip_images, animated
        )
        animated_slots = [(0, 0, 0.0)] * ANIM_TEX_SLOT_COUNT
        for image, (slot, frames, rate) in animated.items():
            offset, frame_bytes, count = animated_offsets[slot]
            if offset + frame_bytes * count > len(tex_blob):
                raise PluginError(f"'{image.name}' runs {frame_bytes * count} bytes past the end of the texture data.")
            animated_slots[slot] = (frame_bytes, count, rate)
        mip_textures = set()
        for key, fImage in fModel.textures.items():
            if not isinstance(key, FPaletteKey) and getattr(key, "image", None) in mip_images:
                if (fImage.startAddress >> 24) == SEG_TEX:
                    mip_textures.add(fImage.startAddress & 0xFFFFFF)
        if rom_format:
            # the texture carries the tint now. Neutralize its SHADE.
            for key, value in fModel.materials.items():
                material = key[0]
                f3d_mat = _f3d_settings(material)
                used = [slot.tex for slot in (f3d_mat.tex0, f3d_mat.tex1) if slot.tex is not None and slot.tex_set]
                if used and all((image_folds.get(image) or (None, None))[1] for image in used):
                    shade_colors[id(value[0])] = ((255, 255, 255), [])
        reflective = {
            id(value[0])
            for key, value in fModel.materials.items()
            if getattr(_f3d_settings(key[0]).rdp_settings, "g_tex_gen", False)
        }
        vertices, vertex_owners, spans = _collect_vertices(
            ordered_fMeshes, shade_colors, settings.force_unlit, reflective
        )
        if not vertices:
            raise PluginError("Nothing was exported, no vertices were produced.")

        segments = {
            SEG_VTX: (0, len(vertices) * VTX_SIZE),
            SEG_TEX: (SEG_TEX << 24, (SEG_TEX << 24) + max(len(texture_resources), 1)),
            SEG_TEX_BLOB: (SEG_TEX_BLOB << 24, (SEG_TEX_BLOB << 24) + max(len(tex_blob), 1)),
        }
        # an animated texture is bound through the segment its slot drives
        for slot in animated_offsets:
            segment = SEG_ANIM_BASE - slot
            segments[segment] = (segment << 24, (segment << 24) + max(len(tex_blob), 1))

        skinning_sources = set()
        if stored is not None:
            for kind, indices, _matrix, _parent, _record in layout_records(stored):
                if kind == "skinning":
                    skinning_sources.update(indices)
        source_counts = {}
        for _bone_index, (_layer, chunk_source), _fMeshes in chunk_fMeshes:
            source_counts[chunk_source] = source_counts.get(chunk_source, 0) + 1
        owner_of_pos = (
            _vertex_bones(context, mesh_objects, bones, to_bk_space, transform_matrix)
            if armature_obj is not None
            else {}
        )

        dl_words = []
        chunks = []
        chunk_bounds = []
        from_source = {}  # original chunk -> the indices its faces went out as
        for bone_index, (layer, source), bone_fMeshes in chunk_fMeshes:
            raw = []
            for fMesh in bone_fMeshes:
                raw += _flatten_gfx_list(fMesh.draw, fModel.f3d, segments)
            chunk_words = _fixup_chunk(
                raw, len(texture_resources), settings.rendermode_entry(layer), white_offset, mip_textures
            )
            first = min(spans[id(fMesh)][0] for fMesh in bone_fMeshes)
            last = max(spans[id(fMesh)][1] for fMesh in bone_fMeshes)
            points = [vertex[0] for vertex in vertices[first:last]]
            pair = None
            if source in skinning_sources and source_counts.get(source) == 1 and source in source_parents:
                pair = _split_skinning(chunk_words, vertices, owner_of_pos, source_parents[source])
            for part in pair if pair is not None else (chunk_words,):
                chunks.append((bone_index, len(dl_words)))
                chunk_bounds.append(points if part is not (pair[0] if pair else None) else [])
                if source >= 0:
                    from_source.setdefault(source, []).append(len(dl_words))
                dl_words += part

        collision = _collision_triangles(dl_words, vertex_owners, _material_surfaces(fModel))
        if shapes:
            index_of_bone = {bone.name: index for index, bone in enumerate(bones)}
            for group in ("boxes", "cylinders", "spheres"):
                for shape in shapes[group]:
                    shape["bone"] = index_of_bone.get(shape.pop("bone_name"), -1)

        # both of these match on position. Take them before the collision only
        # vertices land, or one sitting on a drawn vertex joins its binding
        # entry and its mesh.
        bound_vertices = (
            _vertex_bone_entries(vertices, owner_of_pos, settings.warnings, transform_matrix @ to_bk_space)
            if bind
            else []
        )
        if bind and not bound_vertices:
            raise PluginError(f"Bind Vertices found nothing to bind. Weight the mesh to '{root_obj.name}'.")

        meshes = _mesh_list_entries(
            vertices, _mesh_list_positions(context, mesh_objects, to_bk_space, transform_matrix)
        )

        if collision_only is not None:
            hidden_vertices, hidden_surfaces = collision_only
            base = len(vertices)
            if base + len(hidden_vertices) > MAX_VERTEX_COUNT:
                raise PluginError(
                    f"{base + len(hidden_vertices)} vertices is past the {MAX_VERTEX_COUNT} the game can "
                    "index. Simplify the mesh or the collision only geometry."
                )
            vertices += [(position, 0, uv, color) for position, uv, color in hidden_vertices]
            collision += [((base + a, base + b, base + c), flags, unk6) for a, b, c, flags, unk6 in hidden_surfaces]

        # after the append, the way vanilla does it. global_norm is the radius
        # collision gets tested against at all
        bounds = _vertex_bounds(vertices)
        if shapes:
            # bkmodelunk14list_func_802EBAE0 answers no without testing a shape
            # once a query is past this. Every vanilla model sets it to its own
            # cull radius, not to how far the shapes happen to reach.
            shapes["cull"] = bounds["global_norm"]

        # only split rigging draws under BONE commands, but both need the table:
        # the game builds no matrix list without one
        bone_table = bones if armature_obj is not None else []
        if stored is not None:
            records = _relink_layout(stored, from_source)
            if records is not None:
                # anything the modeller added is outside the layout, hung off its
                # bone at the end. Anything else draws plainly, off no matrix.
                drawn = {index for _k, indices, _m, _p, _r in layout_records(records) for index in indices}
                for chunk_bone, gfx_index in chunks:
                    if gfx_index not in drawn:
                        records.append(("bone", chunk_bone, gfx_index) if rigged else ("loaddl", gfx_index))
            if records is None:
                stored = None
        if stored is None:
            records = _geo_records(bones, chunks, armature_obj, rigged, chunk_bounds)
            # a refpoint names no display list and outlives a relink that gave up
            emitted = {record[1] for record in records if record[0] == "refpoint"}
            for point in _layout_refpoints(_stored_layout(root_obj) or []):
                if point[1] not in emitted:
                    records.append(point)
        if rom_format:
            return {
                "": write_bkmodelbin(
                    settings.geo_type_bits(),
                    _count_triangles(dl_words),
                    bounds,
                    dl_words,
                    records,
                    bone_table,
                    settings.anim_scale,
                    tex_infos,
                    tex_blob,
                    vertices,
                    collision,
                    shapes,
                    bound_vertices,
                    meshes,
                    animated_slots,
                )
            }

        resources = {
            "": _write_model_resource(
                settings.geo_type_bits(),
                _count_triangles(dl_words),
                bounds,
                dl_words,
                len(chunks),
                bone_table,
                settings.anim_scale,
                tex_infos,
                tex_blob,
                collision,
                shapes,
                bound_vertices,
                meshes,
                animated_slots,
            ),
            "_VTX": _write_vertex_resource(vertices),
            "_GEO": _write_geo_layout(records),
        }
        for index, texture in enumerate(texture_resources):
            resources[f"_tex_{index}"] = texture
        return resources

    finally:
        for temp_obj in temp_objects:
            mesh = temp_obj.data
            bpy.data.objects.remove(temp_obj, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
