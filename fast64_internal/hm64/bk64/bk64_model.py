from __future__ import annotations

import math
import struct
import zlib

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
from ...f3d.f3d_material import get_output_method
from ...f3d.f3d_writer import TriangleConverterInfo, getInfoDict, saveStaticModel
from ...utility import (
    PluginError,
    exportColor,
    getObjDirectionVec,
    lightDataToObj,
    normToSigned8Vector,
)
from .bk64_constants import (
    ANIM_TEX_SLOT_COUNT,
    bk64_world_defaults,
    COLLISION_COLOR_ATTR,
    COLLISION_GRID_PROP,
    COLLISION_ONLY_PROP,
    COLLISION_UV_ATTR,
    CAMERA_AREA_KIND,
    SOURCE_CHUNK_ATTR,
    CYCLE_TYPE_2CYCLE,
    DEFAULT_LIGHT_DIR,
    GEO_TYPE_MIPMAP_TRILINEAR,
    MAX_DRAWABLE_BONE_INDEX,
    MAX_VERTEX_COUNT,
    MESH_GROUP_PREFIX,
    MESH_TAG_ATTRIBUTE,
    MIP_SPTEXTURE_LEVEL,
    MIP_SPTEXTURE_TILE,
    MIP_TEXTURE_DIM,
    NO_PARENT,
    otr_header,
    RT_BK_MODEL,
    RT_BLOB,
    RT_VERTEX,
    s16,
    SEG_ANIM_BASE,
    SEG_TEX,
    SEG_TEX_BLOB,
    SEG_VTX,
    SHAPE_KIND,
    SHAPE_PIVOT,
    written_key,
)
from .bk64_texture import (
    animated_slots,
    draw_layer_of,
    collect_textures,
    f3d_materials,
    f3d_settings,
    image_folds,
    image_opacity,
    reads_texel1,
)
from .bk64_geo import (
    count_triangles,
    fixup_chunk,
    flatten_gfx_list,
    geo_records,
    layout_refpoints,
    relink_layout,
    split_skinning,
    stored_layout,
)
from .bk64_collision import (
    check_camera_water_reads,
    collision_from_display_list,
    material_surfaces,
    surface_of_material,
    unpack_collision_grid,
    write_collision_list,
)
from .bk64_rom import (
    collision_shapes,
    geo_body,
    layout_records,
    camera_area_list,
    mesh_list,
    vertex_bone_map,
    vertex_bounds,
    vertex_records,
    write_bkmodelbin,
)
from .bk64_skeleton import BK64Bone, BLENDER_TO_BK, build_bone_table


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
    camera_areas,
    bound_vertices,
    meshes,
    animated_slots,
    vertices,
    collision_grid_stored=None,
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
            1 if camera_areas else 0,
            1 if meshes else 0,
            1 if bound_vertices else 0,
            1 if any(slot[0] for slot in animated_slots) else 0,
        )
    )

    data.extend(vertex_bounds(bounds))

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
        data.extend(write_collision_list(collision, vertices, collision_grid_stored, "<"))
    if shapes:
        data.extend(collision_shapes(shapes))
    if camera_areas:
        data.extend(camera_area_list(camera_areas))
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


def promote_materials_to_2_cycle(mesh_obj):
    # the second cycle is the identity and there's nothing to decide
    changed = 0
    for _material, f3d_mat in f3d_materials([mesh_obj]):
        if f3d_mat.rdp_settings.g_mdsft_cycletype == CYCLE_TYPE_2CYCLE:
            continue
        f3d_mat.rdp_settings.g_mdsft_cycletype = CYCLE_TYPE_2CYCLE
        second = f3d_mat.combiner2
        second.A, second.B, second.C, second.D = "0", "0", "0", "COMBINED"
        second.A_alpha, second.B_alpha, second.C_alpha, second.D_alpha = "0", "0", "0", "COMBINED"
        changed += 1
    return changed


def armature_of(mesh_obj):
    """The armature a mesh exports under, or None"""
    # an ancestor wins over a modifier: the export gathers a model from the root's
    # children, and a static model parented to an empty carries no modifier at all
    current = mesh_obj.parent
    while current is not None:
        if current.type == "ARMATURE":
            return current
        current = current.parent
    return next((m.object for m in mesh_obj.modifiers if m.type == "ARMATURE" and m.object), None)


def checked_armature_of(mesh_obj):
    """The armature a mesh exports under, refusing one that has none"""
    armature_obj = armature_of(mesh_obj)
    if armature_obj is None:
        raise PluginError(f"'{mesh_obj.name}' is not attached to an armature. Parent it to one.")
    return armature_obj


def bone_groups_of(mesh_obj, armature_obj):
    """{vertex group index: bone name} for the groups named after a bone"""
    bone_names = {bone.name for bone in armature_obj.data.bones}
    return {group.index: group.name for group in mesh_obj.vertex_groups if group.name in bone_names}


def checked_bone_groups(mesh_obj, armature_obj):
    """The bone groups a mesh has, refusing one weighted to no bone"""
    groups = bone_groups_of(mesh_obj, armature_obj)
    if not groups:
        raise PluginError(
            f"'{mesh_obj.name}' has no vertex groups named after a bone in '{armature_obj.name}'. "
            "Weight it to the bones you want it to follow."
        )
    return groups


def select_loose_vertices(mesh_obj):
    """Selects the vertices no bone weights, returning how many"""
    # Select All by Trait finds only the vertices in no group at all, and a
    # weight of 0 or a group no bone is named after reads as loose here too
    groups = set(bone_groups_of(mesh_obj, checked_armature_of(mesh_obj)))

    # bmesh, since writing .select straight onto a from_pydata mesh crashes Blender
    # 5.0, and every imported model is built that way
    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    try:
        deform = bm.verts.layers.deform.active
        # Edit mode flushes from these, and a selected face would bring its corners with it
        for edge in bm.edges:
            edge.select = False
        for face in bm.faces:
            face.select = False

        found = 0
        for vertex in bm.verts:
            weights = vertex[deform].items() if deform is not None else ()
            vertex.select = not any(index in groups and weight > 0.0 for index, weight in weights)
            found += vertex.select
        bm.to_mesh(mesh_obj.data)
    finally:
        bm.free()
    mesh_obj.data.update()
    return found


def source_bones_of(mesh_obj, armature_obj):
    """{chunk index: bone name} for a model imported with a layout, or None"""
    stored = stored_layout(armature_obj)
    if stored is None:
        stored = stored_layout(mesh_obj)
    if stored is None:
        return None
    # only the names and their order are read back out, so the matrix is free
    bones = build_bone_table(armature_obj, mathutils.Matrix.Identity(4))[0]
    return _layout_bone_of_source(stored, bones)[0] or None


def bone_of_faces(bm, mesh_obj, group_index_to_bone, fallback_bone_name=None, source_bones=None):
    """({face: bone name}, how many faces had nothing to vote on)"""
    source_of_face = _face_sources(mesh_obj.data) if source_bones else []
    deform_layer = bm.verts.layers.deform.active

    bone_of_face, unweighted = {}, 0
    for face in bm.faces:
        bone_name = None
        if source_bones and face.index < len(source_of_face):
            bone_name = source_bones.get(source_of_face[face.index])
        if bone_name is None:
            group_index = _face_bone_group(face, deform_layer, group_index_to_bone)
            if group_index is None:
                unweighted += 1
            bone_name = group_index_to_bone[group_index] if group_index is not None else fallback_bone_name
        bone_of_face[face] = bone_name
    return bone_of_face, unweighted


def bone_seam_edges(bm, bone_of_face, armature_obj, source_bones):
    """Edges whose two faces sit on bones a single chunk cannot span"""
    parent_of = {bone.name: bone.parent.name if bone.parent else None for bone in armature_obj.data.bones}

    # a chunk carries one bone. A weld across a joint gets torn, except at
    # a bone and its parent, the one seam skinning blends.
    def family(name_a, name_b):
        if name_a is None or name_b is None:
            return False
        return parent_of[name_a] == name_b or parent_of[name_b] == name_a

    seams = []
    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        name_a, name_b = (bone_of_face[face] for face in edge.link_faces)
        if name_a != name_b and not (source_bones and family(name_a, name_b)):
            seams.append(edge)
    return seams


def split_mesh_at_bones(mesh_obj):
    """Cuts a mesh so every triangle belongs to one bone, returning the cut count"""
    # the export needs the mesh this way, but cutting it there would leave the
    # viewport showing something other than what ships
    armature_obj = checked_armature_of(mesh_obj)
    groups = checked_bone_groups(mesh_obj, armature_obj)

    bm = bmesh.new()
    bm.from_mesh(mesh_obj.data)
    deform = bm.verts.layers.deform.verify()

    # every weight boundary. The export reads which bone a vertex follows off the
    # weights, and only one bone per vertex lets it find the parent's vertices.
    owners = {face: _face_bone_group(face, deform, groups) for face in bm.faces}
    seams = [edge for edge in bm.edges if len({owners[f] for f in edge.link_faces}) > 1]

    # then the boundaries only the layout knows about. The weights alone can
    # disagree with it, and the export counts a weld they called clean.
    source_bones = source_bones_of(mesh_obj, armature_obj)
    if source_bones:
        by_layout = bone_of_faces(bm, mesh_obj, groups, None, source_bones)[0]
        already = {edge.index for edge in seams}
        layout_seams = bone_seam_edges(bm, by_layout, armature_obj, source_bones)
        seams += [edge for edge in layout_seams if edge.index not in already]

    # use_verts splits the vertices along these edges as well
    bmesh.ops.split_edges(bm, edges=seams, use_verts=True)

    # a vertex the seams did not separate can still hold faces from two bones. The
    # rewrite below would give it to whichever comes last, so cut those apart first.
    conflicted = set()
    for vert in bm.verts:
        holding = {owners.get(face) for face in vert.link_faces}
        if len(holding) > 1:
            conflicted |= holding
    # in face order: reordering these splits cost one vanilla model its skinning,
    # so which copy of a shared vertex each chunk keeps is load bearing
    faces_by_owner = {}
    for face, owner in owners.items():
        if owner in conflicted:
            faces_by_owner.setdefault(owner, []).append(face)
    for faces in faces_by_owner.values():
        bmesh.ops.split(bm, geom=faces, use_only_faces=False)

    for face in bm.faces:
        owner = owners.get(face)
        if owner is None:
            continue
        for vert in face.verts:
            # only the bone groups. Clearing the lot takes the mesh groups with it.
            for index in [i for i in vert[deform].keys() if i in groups]:
                del vert[deform][index]
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
    group_index_to_bone = checked_bone_groups(mesh_obj, armature_obj)

    bone_of_face, unweighted = bone_of_faces(bm, mesh_obj, group_index_to_bone, fallback_bone_name, source_bones)
    faces_by_bone = {}
    for face, bone_name in bone_of_face.items():
        faces_by_bone.setdefault(bone_name, []).append(face.index)

    # a face with nothing to vote on lands on the root, right for scenery and wrong for a limb
    if unweighted and warnings is not None:
        warnings.append(
            f"{unweighted} faces on '{mesh_obj.name}' carry no weight to a bone's vertex group "
            f"and went onto '{fallback_bone_name}'."
        )

    seams = bone_seam_edges(bm, bone_of_face, armature_obj, source_bones)
    if seams:
        bones = sorted({bone_of_face[face] or "no bone" for edge in seams for face in edge.link_faces})
        where = ", ".join(bones[:4]) + (f" and {len(bones) - 4} more" if len(bones) > 4 else "")
        # Split Mesh At Bones cuts the mesh itself, and this reads it with its modifiers
        # applied. Telling someone to run a cut they already ran helps nobody.
        if len(bm.verts) != len(mesh_obj.data.vertices):
            fix = "Apply its modifiers first, they make geometry Split Mesh At Bones never saw."
        else:
            fix = "Run Split Mesh At Bones."
        raise PluginError(f"'{mesh_obj.name}' is welded across {len(seams)} bone boundaries, at {where}. {fix}")

    parts = {}
    for bone_name, face_indices in faces_by_bone.items():
        part_obj = _bmesh_to_object(context, bm, f"bk64_{mesh_obj.name}_{bone_name}", mesh_obj, face_indices)
        if part_obj is not None:
            parts[bone_name] = [part_obj]
    return parts


def _to_bk_space(root_obj, scale: float):
    """Blender space to BK model space, Y up and in BK units, with the root at the origin"""
    # a rig cancels whole on top of that, its bone table sits in armature space
    origin = (
        mathutils.Matrix.Translation(-root_obj.matrix_world.translation)
        if root_obj.type == "MESH"
        else root_obj.matrix_world.inverted()
    )
    return BLENDER_TO_BK @ mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4() @ origin


def read_camera_areas(root_obj, scale: float):
    """The camera gate boxes under the root, as the unk20 section wants them"""
    to_bk = _to_bk_space(root_obj, scale)
    areas = []
    for obj in root_obj.children_recursive:
        index = obj.get(CAMERA_AREA_KIND)
        if index is None or obj.type != "MESH":
            continue
        corners = [to_bk @ obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
        low = [s16(min(corner[axis] for corner in corners)) for axis in range(3)]
        high = [s16(max(corner[axis] for corner in corners)) for axis in range(3)]
        areas.append((index, dict(min=low, max=high)))
    # the geo CAMERA commands address these by index, so the order is not cosmetic
    return [area for _index, area in sorted(areas, key=lambda pair: pair[0])]


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
                surface = surface_of_material(material) if material else None
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


def _check_cycle_type(mesh_objects):
    """BK draws models in 2 cycle, and a 1 cycle material never reaches the blending"""
    offenders = []
    for material, f3d_mat in f3d_materials(mesh_objects):
        if f3d_mat.rdp_settings.g_mdsft_cycletype != CYCLE_TYPE_2CYCLE and material.name not in offenders:
            offenders.append(material.name)
    if offenders:
        listed = "\n  ".join(offenders)
        raise PluginError(
            "BK draws models in 2 cycle, and these would lose the blending the second cycle does. "
            f"Set Cycle Type:\n  {listed}"
        )


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


def _face_sources(mesh):
    """The chunk each face was drawn in, off the mesh or an older blend's materials"""
    layer = mesh.attributes.get(SOURCE_CHUNK_ATTR)
    if layer is not None and layer.domain == "FACE":
        return [item.value for item in layer.data]
    of_slot = [getattr(material, "hm64_bk64_source_chunk", -1) if material else -1 for material in mesh.materials] or [
        -1
    ]
    return [
        of_slot[polygon.material_index] if polygon.material_index < len(of_slot) else -1 for polygon in mesh.polygons
    ]


def _split_by_draw_key(context, part_obj, scene_layer: str, temp_objects):
    """The part as (key, object) pairs, cut where its faces disagree"""
    # a chunk jumps into one render mode entry. Other faces need their own.
    layer_of_slot = {
        index: draw_layer_of(slot.material, scene_layer) for index, slot in enumerate(part_obj.material_slots)
    }
    sources = _face_sources(part_obj.data)
    part_obj.data.calc_loop_triangles()
    key_of_face = [
        (layer_of_slot.get(polygon.material_index, scene_layer), sources[index])
        for index, polygon in enumerate(part_obj.data.polygons)
    ]
    default = (scene_layer, -1)
    wanted = set(key_of_face) or {default}
    if len(wanted) <= 1:
        return [(wanted.pop(), part_obj)]

    pieces = []
    for key in sorted(wanted):
        bm = bmesh.new()
        bm.from_mesh(part_obj.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(
            bm,
            geom=[face for face in bm.faces if key_of_face[face.index] != key],
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


def _material_lights(fModel: FModel):
    """The lighting each lit FMaterial was authored with, keyed by id"""
    # BK loads no lights. The shading gets worked out here instead.
    lights = {}
    for key, value in fModel.materials.items():
        material = key[0]
        f3d_mat = f3d_settings(material)
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
        f3d_mat = f3d_settings(material)
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
                    yield written_key(vertex.co, scale_matrix), held
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
        key = written_key(vertex[0])
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
        raise PluginError(
            f"Vertex group '{group.name}' names mesh {uid}, which is out of range. "
            "Rename it to a number from -32768 to 32767."
        )
    return uid


def _tag_mesh_groups(bm, mesh_obj, index_of):
    """Write each vertex's mesh membership into the bmesh, as an index into index_of"""
    uid_of_group = {}
    for group in mesh_obj.vertex_groups:
        uid = _checked_mesh_uid(group)
        if uid is not None:
            uid_of_group[group.index] = uid
    if not uid_of_group:
        return

    deform = bm.verts.layers.deform.active
    if deform is None:
        return
    layer = bm.verts.layers.int.get(MESH_TAG_ATTRIBUTE) or bm.verts.layers.int.new(MESH_TAG_ATTRIBUTE)
    for vertex in bm.verts:
        held = frozenset(
            uid_of_group[index] for index, weight in vertex[deform].items() if index in uid_of_group and weight > 0.0
        )
        # every vertex, since index 0 is the empty set and a stale layer would show through
        vertex[layer] = index_of.setdefault(held, len(index_of))


def _piece_mesh_tags(piece):
    """One tag per source vertex, or None when the piece has none"""
    attribute = piece.data.attributes.get(MESH_TAG_ATTRIBUTE)
    return [item.value for item in attribute.data] if attribute else None


def _mesh_list_entries(tags, uid_sets):
    """One mesh per uid, listing every vertex the export wrote for it"""
    holding = {}
    for index, tag in enumerate(tags):
        for uid in uid_sets[tag]:
            holding.setdefault(uid, []).append(index)
    # every vanilla mesh list runs in ascending uid
    return [dict(uid=uid, vertices=holding[uid]) for uid in sorted(holding)]


def _collect_vertices(fMeshes, shade_colors, force_unlit: bool, reflective=frozenset()):
    # startAddress is a byte offset, so SPVertex.to_binary emits the segment 1
    # address directly and nothing needs patching after
    vertices, tags, owners, spans = [], [], [], {}
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
                tags.append(vtx.meshTag or 0)  # 0 is the empty set, which a model with no meshes writes
            owners.append((first, len(vertices), id(triGroup.fMaterial)))
        spans[id(fMesh)] = (spans[id(fMesh)], len(vertices))
    return vertices, tags, owners, spans


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
    """(bone table, parts by bone name, the uid sets the vertex tags index into)"""
    mesh_uids = {frozenset(): 0}
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
                _tag_mesh_groups(bm, mesh_obj, mesh_uids)
                part = _bmesh_to_object(context, bm, f"bk64_{mesh_obj.name}", mesh_obj)
            finally:
                bm.free()
            if part is not None:
                temp_objects.append(part)
                meshes_by_bone[holder].append(part)
        return bones, meshes_by_bone, mesh_uids

    bones, _index_of_name = build_bone_table(armature_obj, bone_matrix)
    root_bone_name = bones[0].name
    meshes_by_bone = {}
    for mesh_obj in mesh_objects:
        bm = _evaluated_bmesh(context, mesh_obj, to_bk_space, True)
        try:
            _tag_mesh_groups(bm, mesh_obj, mesh_uids)
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
    return bones, meshes_by_bone, mesh_uids


# a level's two models in draw order, the opaque one writing depth and the
# translucent one only testing against it
LEVEL_HALVES = (("OPAQUE", "_OPA"), ("TRANSLUCENT", "_XLU"))


def level_half_objects(mesh_objects, half: str):
    """The meshes marked for this half"""
    return [obj for obj in mesh_objects if obj.hm64_bk64_level_half == half]


def blank_half_object(context, mesh_objects, half: str, temp_objects):
    """A model that draws nothing, for the half with no geometry of its own"""
    material = next(
        (slot.material for obj in mesh_objects for slot in obj.material_slots if slot.material is not None),
        None,
    )
    if material is None:
        raise PluginError("Nothing to build a blank half from. Give the level's geometry a material.")

    name = f"bk64_blank_{half.lower()}"
    mesh = bpy.data.meshes.new(name)
    # the export refuses an empty mesh, so this is one triangle with no area
    mesh.from_pydata([(0.0, 0.0, 0.0)] * 3, [], [(0, 1, 2)])
    mesh.update()
    mesh.uv_layers.new(name="UVMap")
    mesh.materials.append(material)

    blank = bpy.data.objects.new(name, mesh)
    blank.use_f3d_culling = False
    context.scene.collection.objects.link(blank)
    temp_objects.append(blank)
    mesh.calc_loop_triangles()
    return blank


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
    check_camera_water_reads(mesh_objects, settings.warnings)
    _check_large_textures(mesh_objects)
    # nothing in BK reads a cull list, and the import and the splitter already clear it
    culling = [obj for obj in mesh_objects if obj.use_f3d_culling]
    for obj in culling:
        obj.use_f3d_culling = False
    if culling:
        counted = "1 object" if len(culling) == 1 else f"{len(culling)} objects"
        settings.warnings.append(f"Turned Use F3D Culling off on {counted}. BK culls off its own center and radius.")

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
        stored = stored_layout(root_obj)
        source_bones, source_parents = None, {}
        if stored is not None and rigged:  # only a split mesh gets cut along these
            table = build_bone_table(armature_obj, bone_matrix)[0]
            source_bones, source_parents = _layout_bone_of_source(stored, table)
        bones, meshes_by_bone, mesh_uids = _gather_parts(
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
                    triConverterInfo = TriangleConverterInfo(
                        piece, None, fModel.f3d, transform_matrix, infoDict, _piece_mesh_tags(piece)
                    )
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
        folds = image_folds(mesh_objects, shade_by_material) if rom_format else None
        opaque_images = image_opacity(mesh_objects, settings.draw_layer) if rom_format else None

        # a TEXEL1 combiner blends between the wrap DL's tiles, so it renders
        # from tile 2 at level 2 and its sibling carries the pyramid
        mip_images = set()
        for key, value in fModel.materials.items():
            material = key[0]
            f3d_mat = f3d_settings(material)
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
        # an import stores geo type on the object, since a level's halves disagree
        geo_type = root_obj.hm64_bk64_geo_type_raw or settings.geo_type_bits()
        # the bits shipped, not the scene setting: a level's second half clears that
        if (geo_type & GEO_TYPE_MIPMAP_TRILINEAR) and not rom_format:
            for key, value in fModel.materials.items():
                material = key[0]
                f3d_mat = f3d_settings(material)
                image = f3d_mat.tex0.tex
                if image is None or not reads_texel1(f3d_mat):
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

        animated = animated_slots(fModel)
        texture_resources, tex_infos, tex_blob, white_offset, animated_offsets = collect_textures(
            fModel, rom_format, folds, opaque_images, mip_images, animated
        )
        slot_table = [(0, 0, 0.0)] * ANIM_TEX_SLOT_COUNT
        for image, (slot, frames, rate) in animated.items():
            offset, frame_bytes, count = animated_offsets[slot]
            if offset + frame_bytes * count > len(tex_blob):
                raise PluginError(f"'{image.name}' runs {frame_bytes * count} bytes past the end of the texture data.")
            slot_table[slot] = (frame_bytes, count, rate)
        mip_textures = set()
        for key, fImage in fModel.textures.items():
            if not isinstance(key, FPaletteKey) and getattr(key, "image", None) in mip_images:
                if (fImage.startAddress >> 24) == SEG_TEX:
                    mip_textures.add(fImage.startAddress & 0xFFFFFF)
        if rom_format:
            # the texture carries the tint now. Neutralize its SHADE.
            for key, value in fModel.materials.items():
                material = key[0]
                f3d_mat = f3d_settings(material)
                if not getattr(f3d_mat.rdp_settings, "g_lighting", False):
                    # only a lit material had a tint to fold. An unlit one folded
                    # against white and keeps its shading in the vertex colors
                    continue
                used = [slot.tex for slot in (f3d_mat.tex0, f3d_mat.tex1) if slot.tex is not None and slot.tex_set]
                if used and all((folds.get(image) or (None, None))[1] for image in used):
                    shade_colors[id(value[0])] = ((255, 255, 255), [])
        reflective = {
            id(value[0])
            for key, value in fModel.materials.items()
            if getattr(f3d_settings(key[0]).rdp_settings, "g_tex_gen", False)
        }
        # the geo CAMERA commands come back with the layout, and cull everything
        # they gate when the boxes they test against are missing
        camera_areas = read_camera_areas(root_obj, settings.scale)

        vertices, mesh_tags, vertex_owners, spans = _collect_vertices(
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
        rigid_seams = set()
        from_source = {}  # original chunk -> the indices its faces went out as
        for bone_index, (layer, source), bone_fMeshes in chunk_fMeshes:
            raw = []
            for fMesh in bone_fMeshes:
                raw += flatten_gfx_list(fMesh.draw, fModel.f3d, segments)
            chunk_words = fixup_chunk(
                raw, len(texture_resources), settings.rendermode_entry(layer), white_offset, mip_textures
            )
            first = min(spans[id(fMesh)][0] for fMesh in bone_fMeshes)
            last = max(spans[id(fMesh)][1] for fMesh in bone_fMeshes)
            points = [vertex[0] for vertex in vertices[first:last]]
            pair = None
            if source in skinning_sources:
                if source_counts.get(source) == 1 and source in source_parents:
                    pair = split_skinning(chunk_words, vertices, owner_of_pos, source_parents[source])
                if pair is None:
                    rigid_seams.add((source_bones or {}).get(source, f"chunk {source}"))
            for part in pair if pair is not None else (chunk_words,):
                chunks.append((bone_index, len(dl_words)))
                chunk_bounds.append(points if part is not (pair[0] if pair else None) else [])
                if source >= 0:
                    from_source.setdefault(source, []).append(len(dl_words))
                dl_words += part

        for name in sorted(rigid_seams):
            settings.warnings.append(
                f"The seam at bone '{name}' lost its skinning and can tear in game. It needs its "
                "faces on one material and draw layer, with up to 24 vertices weighted to the parent bone."
            )
        collision = collision_from_display_list(dl_words, vertex_owners, material_surfaces(fModel))
        if shapes:
            index_of_bone = {bone.name: index for index, bone in enumerate(bones)}
            for group in ("boxes", "cylinders", "spheres"):
                for shape in shapes[group]:
                    shape["bone"] = index_of_bone.get(shape.pop("bone_name"), -1)

        # binding matches on position. Take it before the collision only vertices
        # land, or one sitting on a drawn vertex joins its entry.
        bound_vertices = (
            _vertex_bone_entries(vertices, owner_of_pos, settings.warnings, transform_matrix @ to_bk_space)
            if bind
            else []
        )
        if bind and not bound_vertices:
            raise PluginError(f"Bind Vertices found nothing to bind. Weight the mesh to '{root_obj.name}'.")

        meshes = _mesh_list_entries(mesh_tags, sorted(mesh_uids, key=mesh_uids.get))
        lost = sorted({uid for held in mesh_uids for uid in held} - {entry["uid"] for entry in meshes})
        if lost:
            settings.warnings.append(
                f"Mesh {', '.join(str(uid) for uid in lost)} has no drawn faces and was left out of the "
                "mesh list. Give the group faces, or delete it."
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
            records = relink_layout(stored, from_source)
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
            records = geo_records(bones, chunks, armature_obj, rigged, chunk_bounds)
            # a refpoint names no display list and outlives a relink that gave up
            emitted = {record[1] for record in records if record[0] == "refpoint"}
            for point in layout_refpoints(stored_layout(root_obj) or []):
                if point[1] not in emitted:
                    records.append(point)
        stored_grid = next(
            (
                unpack_collision_grid(obj[COLLISION_GRID_PROP])
                for obj in [root_obj] + mesh_objects
                if COLLISION_GRID_PROP in obj.keys()
            ),
            None,
        )
        if rom_format:
            return {
                "": write_bkmodelbin(
                    geo_type,
                    count_triangles(dl_words),
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
                    camera_areas,
                    bound_vertices,
                    meshes,
                    slot_table,
                    stored_grid,
                )
            }

        resources = {
            "": _write_model_resource(
                geo_type,
                count_triangles(dl_words),
                bounds,
                dl_words,
                len(chunks),
                bone_table,
                settings.anim_scale,
                tex_infos,
                tex_blob,
                collision,
                shapes,
                camera_areas,
                bound_vertices,
                meshes,
                slot_table,
                vertices,
                stored_grid,
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
