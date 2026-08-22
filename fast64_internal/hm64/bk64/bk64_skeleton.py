from __future__ import annotations

import math
import struct

import bpy
import mathutils

from ...utility import PluginError
from .bk64_constants import MAX_BONE_ID, NO_PARENT, RT_BK_MODEL
from .bk64_rom import is_bkmodelbin, read_bkmodelbin_header

# BK is Y up where Blender is Z up
BLENDER_TO_BK = mathutils.Matrix.Rotation(math.radians(-90), 4, "X")


def bone_space_matrix(scale: float):
    """Blender armature space to BK bone space, Y up and in BK units"""
    return mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4() @ BLENDER_TO_BK


class BK64Bone:
    """One BKAnimationList entry"""

    # bone_id is what animations address, parent_index points into this same
    # table (parents first), position is the joint pivot
    __slots__ = ("name", "position", "bone_id", "parent_index")

    def __init__(self, name: str, position, bone_id: int, parent_index: int):
        self.name = name
        self.position = position
        self.bone_id = bone_id
        self.parent_index = parent_index

    def __repr__(self):
        parent = "root" if self.parent_index == NO_PARENT else self.parent_index
        return f"BK64Bone({self.name}, id={self.bone_id}, parent={parent}, pos={self.position})"


def _sorted_children(bone: bpy.types.Bone):
    # set by the importer, keeps round trips stable
    children = list(bone.children)
    if children and all(child.hm64_bk64_bone_order >= 0 for child in children):
        return sorted(children, key=lambda child: child.hm64_bk64_bone_order)
    return sorted(children, key=lambda child: child.name)


def build_bone_table(armature_obj: bpy.types.Object, transform_matrix: mathutils.Matrix):
    """Depth first walk of the armature, parents before children"""
    if armature_obj is None or armature_obj.type != "ARMATURE":
        raise PluginError("BK64 skeleton export needs an armature object.")

    armature = armature_obj.data
    roots = [bone for bone in armature.bones if bone.parent is None]
    if not roots:
        raise PluginError(f"Armature '{armature_obj.name}' has no bones.")
    if all(root.hm64_bk64_bone_order >= 0 for root in roots):
        roots.sort(key=lambda root: root.hm64_bk64_bone_order)
    else:
        roots.sort(key=lambda root: root.name)

    bones: list[BK64Bone] = []
    index_of_name: dict[str, int] = {}

    def visit(bone: bpy.types.Bone, parent_index: int):
        position = transform_matrix @ bone.head_local
        index = len(bones)
        bone_id = bone.hm64_bk64_bone_id if bone.hm64_bk64_bone_id > 0 else index + 1
        bones.append(BK64Bone(bone.name, (position.x, position.y, position.z), bone_id, parent_index))
        index_of_name[bone.name] = index
        for child in _sorted_children(bone):
            visit(child, index)

    for root in roots:
        visit(root, NO_PARENT)

    seen: dict[int, str] = {}
    for bone in bones:
        if bone.bone_id > MAX_BONE_ID:
            raise PluginError(
                f"Bone '{bone.name}' uses BK bone id {bone.bone_id}, past the {MAX_BONE_ID} the "
                "game's unchecked table holds."
            )
        if bone.bone_id in seen:
            raise PluginError(
                f"Bones '{seen[bone.bone_id]}' and '{bone.name}' both use BK bone id {bone.bone_id}. "
                "Animations address bones by id, so ids must be unique."
            )
        seen[bone.bone_id] = bone.name

    return bones, index_of_name


def _read_bones(data: bytes, offset: int, endian: str, header_size: int):
    """(animation scale, bones) from the BKAnimationList at offset.

    The resource packs the list header into 6 bytes; the ROM's own pads it to 8.
    """
    if not offset:
        return 0.0, []
    anim_scale = struct.unpack_from(endian + "f", data, offset)[0]
    bone_count = struct.unpack_from(endian + "H", data, offset + 4)[0]
    offset += header_size

    bones = []
    for i in range(bone_count):
        x, y, z, bone_id, parent = struct.unpack_from(endian + "fffHH", data, offset + i * 16)
        bones.append(BK64Bone(f"bone_{bone_id}", (x, y, z), bone_id, parent))
    return anim_scale, bones


def read_bone_table(data: bytes):
    """(animation scale, bones) from a model resource or a .bin"""
    if is_bkmodelbin(data):
        return _read_bones(data, read_bkmodelbin_header(data)["anim"], ">", 8)

    # same field order as the model resource, earlier sections get skipped
    if len(data) < 0x40:
        raise PluginError("Not a libultraship resource, it's shorter than the 64 byte header.")

    resource_type = struct.unpack_from("<I", data, 4)[0]
    if resource_type != RT_BK_MODEL:
        raise PluginError(
            f"Not a BK model resource (type 0x{resource_type:08X}, expected 0x{RT_BK_MODEL:08X}). "
            "Point this at the model itself, not its _GEO/_VTX/_tex sibling."
        )

    offset = 0x40 + 6  # geoType, triCount, vertCount
    has_geo, has_vtx, has_dl = struct.unpack_from("<BBB", data, offset)
    offset += 3
    tex_count = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    has_anim = struct.unpack_from("<BBBBBBB", data, offset)[0]
    offset += 7

    if has_vtx:
        offset += 24
    if has_dl:
        dl_count = struct.unpack_from("<I", data, offset)[0]
        offset += 12 + dl_count * 8
    offset += tex_count * 10  # type u16, w u8, h u8, tlutColors u16, romOffset u32
    offset += 4 + struct.unpack_from("<I", data, offset)[0]  # raw texture blob

    return _read_bones(data, offset if has_anim else 0, "<", 6)


def create_armature_from_bones(
    name: str, bones: list[BK64Bone], transform_matrix: mathutils.Matrix, bone_length: float
):
    # Blender refuses zero length bones. Aim each at its first differing child.
    to_blender = transform_matrix.inverted()

    armature = bpy.data.armatures.new(name)
    armature_obj = bpy.data.objects.new(name, armature)
    bpy.context.scene.collection.objects.link(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")

    heads = [to_blender @ mathutils.Vector(bone.position) for bone in bones]
    children_of = {i: [] for i in range(len(bones))}
    for i, bone in enumerate(bones):
        if bone.parent_index != NO_PARENT and bone.parent_index < len(bones):
            children_of[bone.parent_index].append(i)

    edit_bones = []
    for i, bone in enumerate(bones):
        edit_bone = armature.edit_bones.new(f"bk_{i:02}_id{bone.bone_id}")
        edit_bone.head = heads[i]
        tail = next((heads[child] for child in children_of[i] if (heads[child] - heads[i]).length > 1e-5), None)
        edit_bone.tail = tail if tail is not None else heads[i] + mathutils.Vector((0.0, 0.0, bone_length))
        edit_bone.use_connect = False
        edit_bones.append(edit_bone)

    for i, bone in enumerate(bones):
        if bone.parent_index != NO_PARENT and bone.parent_index < len(bones):
            edit_bones[i].parent = edit_bones[bone.parent_index]

    # EditBones die on mode_set, read the names first
    names = [edit_bone.name for edit_bone in edit_bones]
    bpy.ops.object.mode_set(mode="OBJECT")

    for i, bone in enumerate(bones):
        data_bone = armature.bones[names[i]]
        data_bone.hm64_bk64_bone_id = bone.bone_id
        data_bone.hm64_bk64_bone_order = i

    return armature_obj
