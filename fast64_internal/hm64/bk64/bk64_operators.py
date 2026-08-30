from __future__ import annotations

import os
from contextlib import contextmanager

import bpy
from bpy.types import Operator
from bpy.utils import register_class, unregister_class

from ...utility import PluginError, raisePluginError
from .bk64_anim import actions_for, export_bk64_animation, import_bk64_animation
from .bk64_constants import COLLISION_ONLY_PROP, GEO_TYPE_ENV_MAP, GEO_TYPE_MIPMAP_TRILINEAR
from .bk64_import import import_bk64_model
from .bk64_level_models import bk64_level_layers
from .bk64_model import (
    export_bk64_model,
    promote_materials_to_2_cycle,
    read_collision_only,
    read_collision_shapes,
    select_loose_vertices,
    split_mesh_at_bones,
)
from .bk64_properties import BK64_Settings
from .bk64_skeleton import bone_space_matrix, create_armature_from_bones, read_bone_table


@contextmanager
def object_mode(context):
    # an animation exported from Pose mode shouldn't leave you in Object mode
    previous = context.mode
    if context.object is not None and previous != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        yield
    finally:
        if context.object is not None and context.mode != previous:
            if previous.startswith("EDIT") and context.object.type in {"MESH", "CURVE", "ARMATURE"}:
                bpy.ops.object.mode_set(mode="EDIT")
            elif previous in {"POSE", "SCULPT"}:
                bpy.ops.object.mode_set(mode=previous)


def resolve_root(context):
    """The object to export, an armature if rigged and a mesh otherwise"""
    # walks up to the root like MK64 does, letting any part of a rig work
    selected = context.selected_objects
    if not selected:
        raise PluginError("Nothing selected. Pick the armature, or the mesh for a static model.")

    for obj in selected:
        if obj.type == "ARMATURE":
            return obj
    for obj in selected:
        current = obj
        while current is not None:
            if current.type == "ARMATURE":
                return current
            current = current.parent

    for obj in selected:  # the empty the error below asks for
        if obj.type == "EMPTY" and any(child.type == "MESH" for child in obj.children_recursive):
            return obj

    meshes = [obj for obj in selected if obj.type == "MESH"]
    if not meshes:
        raise PluginError("Select an armature or a mesh object.")
    if len(meshes) > 1:
        raise PluginError("Multiple meshes selected with no armature. Parent them to one empty and select that.")
    return meshes[0]


class BK64_ExportModel(Operator):
    bl_idname = "scene.hm64_bk64_export_model"
    bl_label = "Export BK Model"
    bl_description = "Write the selected model as an o2r resource family or a .bin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene

        try:
            with object_mode(context):
                root_obj = resolve_root(context)
                settings = BK64_Settings(scene)

                export_dir = bpy.path.abspath(scene.hm64_bk64_export_path)
                if not export_dir:
                    raise PluginError("Set an export folder first.")
                if not settings.name:
                    raise PluginError("Set a resource path first, e.g. models/mymodel.")

                shapes = read_collision_shapes(root_obj, settings.scale)
                collision_only = read_collision_only(context, root_obj, settings.scale)
                resources = export_bk64_model(context, root_obj, settings, shapes, collision_only)

                extension = ".bin" if settings.file_format == "BIN" else ""
                for suffix, data in resources.items():
                    path = os.path.join(export_dir, settings.name + suffix + extension)
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                    with open(path, "wb") as file:
                        file.write(data)

                for warning in settings.warnings:
                    self.report({"WARNING"}, warning)
                self.report(
                    {"INFO"},
                    (
                        f"Exported {settings.name} and {len(resources) - 1} sibling resources to {export_dir}"
                        if len(resources) > 1
                        else f"Exported {settings.name}{extension} to {export_dir}"
                    ),
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_ExportAnimation(Operator):
    bl_idname = "scene.hm64_bk64_export_animation"
    bl_label = "Export BK Animation"
    bl_description = "Write the armature's active action as a BK animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene

        try:
            with object_mode(context):
                root_obj = resolve_root(context)
                if root_obj.type != "ARMATURE":
                    raise PluginError("Select the armature the animation is on, only rigged models animate.")
                settings = BK64_Settings(scene)

                export_dir = bpy.path.abspath(scene.hm64_bk64_export_path)
                if not export_dir:
                    raise PluginError("Set an export folder first.")
                if not settings.anim_path:
                    raise PluginError("Set an animation path first, e.g. assets/anim/myanim.")

                data = export_bk64_animation(context, root_obj, settings)
                extension = ".bin" if settings.file_format == "BIN" else ""
                path = os.path.join(export_dir, settings.anim_path + extension)
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "wb") as file:
                    file.write(data)

                self.report({"INFO"}, f"Exported {settings.anim_path}{extension} to {export_dir}")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_ExportAllAnimations(Operator):
    bl_idname = "scene.hm64_bk64_export_all_animations"
    bl_label = "Export All Actions"
    bl_description = "Write every action with a curve on this armature, one asset each"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene

        try:
            with object_mode(context):
                armature_obj = resolve_root(context)
                if armature_obj.type != "ARMATURE":
                    raise PluginError("Select the armature the actions are on, only rigged models animate.")
                settings = BK64_Settings(scene)

                export_dir = bpy.path.abspath(scene.hm64_bk64_export_path)
                if not export_dir:
                    raise PluginError("Set an export folder first.")

                actions = actions_for(armature_obj)
                if not actions:
                    raise PluginError(f"No action in this file has a curve on a bone of '{armature_obj.name}'.")

                # each animation is its own asset, landing beside the one named above
                folder = os.path.dirname(settings.anim_path)
                extension = ".bin" if settings.file_format == "BIN" else ""
                armature_obj.animation_data_create()
                restore = armature_obj.animation_data.action

                written = []
                try:
                    for action in actions:
                        armature_obj.animation_data.action = action
                        data = export_bk64_animation(context, armature_obj, settings)
                        path = os.path.join(export_dir, folder, action.name + extension)
                        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                        with open(path, "wb") as file:
                            file.write(data)
                        written.append(action.name)
                finally:
                    armature_obj.animation_data.action = restore

                self.report({"INFO"}, f"Exported {len(written)} actions to {os.path.join(export_dir, folder)}")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_PromoteMaterials(Operator):
    bl_idname = "object.hm64_bk64_promote_materials"
    bl_label = "Promote Materials To 2 Cycle"
    bl_description = "Give every material on the selected meshes a second cycle. BK renders a 1 cycle material black"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            with object_mode(context):
                meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
                if not meshes:
                    raise PluginError("Select the mesh whose materials to promote.")

                moved = sum(promote_materials_to_2_cycle(mesh_obj) for mesh_obj in meshes)
                self.report(
                    {"INFO"},
                    f"Moved {moved} materials to 2 cycle." if moved else "Every material was already 2 cycle.",
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_SplitMeshAtBones(Operator):
    bl_idname = "object.hm64_bk64_split_mesh_at_bones"
    bl_label = "Split Mesh At Bones"
    bl_description = (
        "Cut the selected mesh wherever a face spans two bones, which Split At Bones rigging cannot represent"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            with object_mode(context):
                meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
                if not meshes:
                    raise PluginError("Select the mesh to split.")

                cuts = sum(split_mesh_at_bones(mesh_obj) for mesh_obj in meshes)
                self.report(
                    {"INFO"},
                    (
                        f"Cut {cuts} edges. Every triangle belongs to one bone now, so what you see is what exports."
                        if cuts
                        else "Nothing to cut, every triangle already belongs to one bone."
                    ),
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_SelectLooseVertices(Operator):
    bl_idname = "object.hm64_bk64_select_loose_vertices"
    bl_label = "Select Loose Vertices"
    bl_description = (
        "Select the vertices no bone weights, which hold their rest pose while the rest of the model animates"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            with object_mode(context):
                meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
                if not meshes:
                    raise PluginError("Select the mesh to check.")
                found = sum(select_loose_vertices(mesh_obj) for mesh_obj in meshes)

            if found:
                context.tool_settings.mesh_select_mode = (True, False, False)
                bpy.ops.object.mode_set(mode="EDIT")
            self.report(
                {"INFO"},
                (
                    f"Selected {found} vertices. Weight them to a bone, or they stay behind when the model moves."
                    if found
                    else "Every vertex is weighted. If the export still warned, a modifier is making the loose ones."
                ),
            )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_MarkCollisionOnly(Operator):
    bl_idname = "object.hm64_bk64_mark_collision_only"
    bl_label = "Toggle Collision Only"
    bl_description = (
        "Make the selected meshes collide without drawing, for an invisible floor or wall. "
        "Give every face a collision material"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            with object_mode(context):
                meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
                if not meshes:
                    raise PluginError("Select the mesh to use as collision.")

                marking = not all(obj.get(COLLISION_ONLY_PROP) for obj in meshes)
                for obj in meshes:
                    if marking:
                        obj[COLLISION_ONLY_PROP] = 1
                        obj.ignore_render = True
                        obj.display_type = "WIRE"
                    else:
                        del obj[COLLISION_ONLY_PROP]
                        obj.ignore_render = False
                        obj.display_type = "TEXTURED"

                counted = "1 mesh" if len(meshes) == 1 else f"{len(meshes)} meshes"
                self.report(
                    {"INFO"},
                    (
                        f"{counted} collide but don't draw. Give every face a collision material."
                        if marking
                        else f"{counted} draw again."
                    ),
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_ImportAnimation(Operator):
    bl_idname = "scene.hm64_bk64_import_animation"
    bl_label = "Import BK Animation"
    bl_description = "Read a BK animation onto an armature carrying the right bone ids"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        try:
            with object_mode(context):
                armature_obj = resolve_root(context)
                if armature_obj.type != "ARMATURE":
                    raise PluginError("Select the armature to put the animation on.")

                path = bpy.path.abspath(scene.hm64_bk64_anim_import_path)
                if not path or not os.path.isfile(path):
                    raise PluginError("Pick an animation resource to import.")

                action, frames = import_bk64_animation(context, armature_obj, path, BK64_Settings(scene))
                self.report({"INFO"}, f"Imported '{action.name}' over {frames} frames.")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


def _level_resource(folder: str, index: int, stem: str, layer: str):
    """Where a level's half was extracted to, or None if it isn't there"""
    name = f"ASSET_{index:04X}_{stem}_{layer}"
    for candidate in (os.path.join(folder, name), os.path.join(folder, "assets", "level", name)):
        if os.path.isfile(candidate):
            return candidate
    return None


class BK64_ImportLevel(Operator):
    bl_idname = "scene.hm64_bk64_import_level"
    bl_label = "Import BK Level"
    bl_description = "Read a level by name from a folder of extracted resources"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        try:
            with object_mode(context):
                folder = bpy.path.abspath(scene.hm64_bk64_level_folder)
                if not folder or not os.path.isdir(folder):
                    raise PluginError("Pick the folder holding the extracted level resources.")

                level, choice = scene.hm64_bk64_level, scene.hm64_bk64_level_layer
                layers = bk64_level_layers(level)
                wanted = [half for half in ("OPA", "XLU") if half in layers]
                if choice != "BOTH":
                    wanted = [half for half in wanted if half == choice]
                if not wanted:
                    raise PluginError(f"{level} has no {choice} half. It is opaque only.")

                triangles, brought = 0, []
                for half in wanted:
                    path = _level_resource(folder, layers[half], level, half)
                    if path is None:
                        raise PluginError(
                            f"{level} {half} isn't in that folder. It should hold "
                            f"ASSET_{layers[half]:04X}_{level}_{half} and its _GEO, _VTX and _tex siblings."
                        )
                    _armature_obj, mesh_obj, _model = import_bk64_model(context, path, BK64_Settings(scene))
                    triangles += len(mesh_obj.data.polygons)
                    brought.append(half)

                note = " Each half is its own object." if len(brought) > 1 else ""
                self.report({"INFO"}, f"Imported {level} {' and '.join(brought)}, {triangles} triangles.{note}")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_ImportModel(Operator):
    bl_idname = "scene.hm64_bk64_import_model"
    bl_label = "Import BK Model"
    bl_description = "Read a BK model, from either an o2r resource family or a .bin"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        try:
            with object_mode(context):
                path = bpy.path.abspath(scene.hm64_bk64_import_path)
                if not path or not os.path.isfile(path):
                    raise PluginError("Pick a BK model resource or .bin file to import.")

                _armature_obj, mesh_obj, model = import_bk64_model(context, path, BK64_Settings(scene))
                if model["bones"]:
                    scene.hm64_bk64_anim_scale = model["anim_scale"]
                scene.hm64_bk64_env_map = bool(model["geo_type"] & GEO_TYPE_ENV_MAP)
                scene.hm64_bk64_mipmap = bool(model["geo_type"] & GEO_TYPE_MIPMAP_TRILINEAR)

                notes = []
                kept = model.get("geo_commands", ())
                if kept:
                    notes.append(f"Its geo layout uses {', '.join(kept)}, kept for re-export.")
                if model["mesh_list"]:
                    notes.append(f"Its mesh list came in as {len(model['mesh_list'])} vertex groups.")
                    if not model["mesh_list_exact"]:
                        notes.append(
                            "Some of its meshes share a coordinate with geometry outside them, so a "
                            "re-export puts more vertices in a mesh than vanilla did."
                        )
                if model["shapes"]:
                    notes.append(f"{len(model['shape_objects'])} collision shapes are in their own collection.")
                if model["dropped"]:
                    notes.append(
                        f"{model['dropped']} triangles reference vertices no G_VTX loads, and came "
                        "in without them. The display list is malformed, likely a romhack tool's."
                    )
                if model["unbound_textures"]:
                    notes.append(
                        f"{model['unbound_textures']} of its textures aren't bound by the display list, "
                        "so they won't be there on the way out."
                    )
                if model["collision_only_object"] is not None:
                    faces = len(model["collision_only_object"].data.polygons)
                    notes.append(f"{faces} collision triangles sit on geometry nothing draws, in their own mesh.")
                if model["bones"]:
                    notes.append("Animation Scale came in with it.")
                    if model["bound_vertices"]:
                        notes.append("Its rigging is bound vertices, weighted from the binding table.")
                    elif not mesh_obj.vertex_groups:
                        notes.append("Nothing was weighted, the layout draws under no bone. Weight the mesh yourself.")
                else:
                    notes.append("Static model, no bone table.")
                self.report(
                    {"INFO"},
                    f"Imported {len(mesh_obj.data.polygons)} triangles over {len(model['bones'])} bones. "
                    + " ".join(notes),
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_ImportSkeleton(Operator):
    bl_idname = "scene.hm64_bk64_import_skeleton"
    bl_label = "Import BK Skeleton"
    bl_description = "Read only the bones of a BK model, keeping their ids so animations bind"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        try:
            with object_mode(context):
                path = bpy.path.abspath(scene.hm64_bk64_import_path)
                if not path or not os.path.isfile(path):
                    raise PluginError("Pick a BK model resource or .bin file to read the skeleton from.")

                with open(path, "rb") as file:
                    data = file.read()

                anim_scale, bones = read_bone_table(data)
                if not bones:
                    raise PluginError(f"'{os.path.basename(path)}' has no bone table, it's a static model.")

                create_armature_from_bones(
                    os.path.basename(path) + "_skel",
                    bones,
                    bone_space_matrix(scene.hm64_bk64_scale),
                    scene.hm64_bk64_import_bone_length,
                )

                scene.hm64_bk64_anim_scale = anim_scale  # or vanilla animations move the wrong distance

                self.report(
                    {"INFO"},
                    f"Imported {len(bones)} bones (animation scale {anim_scale:g}). Bone ids are on the bone tab.",
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


bk64_operator_classes = (
    BK64_ExportModel,
    BK64_ExportAnimation,
    BK64_ExportAllAnimations,
    BK64_PromoteMaterials,
    BK64_SplitMeshAtBones,
    BK64_SelectLooseVertices,
    BK64_MarkCollisionOnly,
    BK64_ImportSkeleton,
    BK64_ImportModel,
    BK64_ImportLevel,
    BK64_ImportAnimation,
)


def bk64_operators_register():
    for cls in bk64_operator_classes:
        register_class(cls)


def bk64_operators_unregister():
    for cls in reversed(bk64_operator_classes):
        unregister_class(cls)
