from __future__ import annotations

import json
import os
from contextlib import contextmanager

import bpy
import mathutils
from bpy.app.handlers import persistent
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator
from bpy.utils import register_class, unregister_class

from ...utility import PluginError, raisePluginError
from .bk64_anim import actions_for, export_bk64_animation, import_bk64_animation
from .bk64_constants import (
    CAMERA_AREA_KIND,
    COLLISION_ONLY_PROP,
    HIT_SPHERE_PROP,
    GEO_LAYOUT_PROP,
    GEO_TYPE_ENV_MAP,
    GEO_TYPE_MIPMAP_TRILINEAR,
    MAX_APPENDAGE_ID,
    SCENE_CONTRACT,
    MESH_EFFECT_UID_BASE,
    MESH_GROUP_PREFIX,
    MODEL_STASH_PROPS,
    SHAPE_KIND,
    SORT_SIDES,
)
from .bk64_import import import_bk64_model
from .bk64_geo import (
    geo_node_group,
    geo_node_of_group,
    layout_detail_levels,
    layout_level_gaps,
    set_detail_level,
    stored_layout,
)
from .bk64_level_models import bk64_level_half_paths, bk64_level_layers, bk64_level_of_asset
from .bk64_properties import spread_detail_levels
from .bk64_model import (
    armature_of,
    blank_half_object,
    export_bk64_model,
    LEVEL_HALVES,
    level_half_objects,
    whole_level_half,
    promote_materials_to_2_cycle,
    from_bk_space,
    read_collision_only,
    read_collision_shapes,
    read_vertex_bounds,
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

    for obj in selected:  # an explicit pick wins
        if obj.type == "ARMATURE":
            return obj

    # the same rule the tools use, so what they split is what this exports
    for obj in selected:
        if obj.type == "MESH":
            rig = armature_of(obj)
            if rig is not None:
                return rig

    for obj in selected:
        current = obj.parent
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
                png_folder = export_dir if scene.saveTextures else None
                resources = export_bk64_model(context, root_obj, settings, shapes, collision_only, png_folder)

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


def _half_holder(context, name, objects, temp_objects):
    """An empty standing in for one half's model, holding what the export reads off a root"""
    holder = bpy.data.objects.new(name, None)
    context.scene.collection.objects.link(holder)
    temp_objects.append(holder)
    for prop in MODEL_STASH_PROPS:
        stashed = next((obj[prop] for obj in objects if prop in obj), None)
        if stashed is not None:
            holder[prop] = stashed
    # a real property rather than a custom one, so MODEL_STASH_PROPS can't carry it
    holder.hm64_bk64_geo_type_raw = next(
        (obj.hm64_bk64_geo_type_raw for obj in objects if obj.hm64_bk64_geo_type_raw), 0
    )
    return holder


class BK64_ExportLevelHalves(Operator):
    bl_idname = "scene.hm64_bk64_export_level_halves"
    bl_label = "Export Level Halves"
    bl_description = (
        "Write the selected level as its opaque and translucent models. A vanilla level's halves go "
        "out under their own asset names, which differ from each other"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        temp_objects = []
        try:
            with object_mode(context):
                root_obj = resolve_root(context)
                if root_obj.type == "ARMATURE":
                    raise PluginError("A level is a static model. Select the level geometry, not an armature.")

                settings = BK64_Settings(scene)
                export_dir = bpy.path.abspath(scene.hm64_bk64_export_path)
                if not export_dir:
                    raise PluginError("Set an export folder first.")
                if not settings.name:
                    raise PluginError("Set a resource path first, e.g. levels/mylevel.")

                sources = (
                    [root_obj]
                    if root_obj.type == "MESH"
                    else [child for child in root_obj.children_recursive if child.type == "MESH"]
                )
                hidden = [obj for obj in sources if obj.get(COLLISION_ONLY_PROP)]
                # a collision only mesh draws nothing, so no draw layer can place it
                hidden_of = {half: [obj for obj in hidden if whole_level_half(obj) == half] for half, _ in LEVEL_HALVES}
                sources = [obj for obj in sources if not obj.ignore_render and not obj.get(COLLISION_ONLY_PROP)]
                if not sources:
                    raise PluginError(f"Nothing to export, '{root_obj.name}' has no mesh geometry.")

                base_name, written, blanked = settings.name, [], []
                extension = ".bin" if settings.file_format == "BIN" else ""
                paths = bk64_level_half_paths(base_name)

                for half, suffix in LEVEL_HALVES:
                    layer = suffix.lstrip("_")
                    halves = level_half_objects(context, sources, half, temp_objects)
                    if not halves:
                        halves = [blank_half_object(context, sources, half, temp_objects)]
                        blanked.append(layer)

                    holder = _half_holder(context, f"bk64_half_{half.lower()}", halves + hidden_of[half], temp_objects)

                    def stand_in_for(obj, parent):
                        # a copy shares the mesh data, so parenting one under the
                        # holder leaves the user's own objects where they were
                        copy = obj.copy()
                        context.scene.collection.objects.link(copy)
                        temp_objects.append(copy)
                        copy.parent = parent
                        copy.matrix_world = obj.matrix_world
                        return copy

                    for obj in halves + hidden_of[half]:
                        stand_in = stand_in_for(obj, holder)
                        # the collision volumes and camera gates hang off the model, not the
                        # holder the export is handed, and both readers only walk children
                        for child in obj.children_recursive:
                            if child.get(SHAPE_KIND) is not None or child.get(CAMERA_AREA_KIND) is not None:
                                stand_in_for(child, stand_in)

                    settings.name = paths[layer]
                    shapes = read_collision_shapes(holder, settings.scale)
                    collision_only = read_collision_only(context, holder, settings.scale)
                    png_folder = export_dir if scene.saveTextures else None
                    resources = export_bk64_model(context, holder, settings, shapes, collision_only, png_folder)
                    for res_suffix, data in resources.items():
                        path = os.path.join(export_dir, settings.name + res_suffix + extension)
                        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                        with open(path, "wb") as file:
                            file.write(data)
                    written.append(settings.name)

                settings.name = base_name
                # both halves raise the same ones, and one settings collects them all
                for warning in dict.fromkeys(settings.warnings):
                    self.report({"WARNING"}, warning)
                note = f" {' and '.join(blanked)} had no geometry and went out blank." if blanked else ""
                self.report({"INFO"}, f"Exported {' and '.join(written)} to {export_dir}.{note}")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}

        finally:
            for obj in temp_objects:
                if obj.name in bpy.data.objects:
                    bpy.data.objects.remove(obj, do_unlink=True)


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

                for warning in dict.fromkeys(settings.warnings):
                    self.report({"WARNING"}, warning)
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
    bl_description = (
        "Give every material on the selected meshes the second cycle BK needs. Materials made in BK64 "
        "mode already have it, so this is for a mesh brought in from elsewhere"
    )
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


class BK64_AddMeshEffect(Operator):
    bl_idname = "object.hm64_bk64_add_mesh_effect"
    bl_label = "Add Mesh Effect"
    bl_description = (
        "Have the game animate the selected faces. Select them in edit mode first, and pick the effect "
        "and speed above"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            mesh_obj = context.object
            if mesh_obj is None or mesh_obj.type != "MESH":
                raise PluginError("Select the mesh holding the faces to animate.")

            effect = context.scene.hm64_bk64_mesh_effect
            speed = context.scene.hm64_bk64_scroll_speed
            # edit mode keeps the selection in a bmesh of its own, object mode is where it lands
            with object_mode(context):
                chosen = [vertex.index for vertex in mesh_obj.data.vertices if vertex.select]
                if not chosen:
                    raise PluginError("No vertices selected. Pick the faces to animate in edit mode.")

                name = f"{MESH_GROUP_PREFIX}{MESH_EFFECT_UID_BASE[effect] + speed}"
                group = mesh_obj.vertex_groups.get(name) or mesh_obj.vertex_groups.new(name=name)
                group.add(chosen, 1.0, "REPLACE")

            self.report(
                {"INFO"},
                f"{len(chosen)} vertices in '{name}'. The number in the name is the effect's hundred plus the speed.",
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


def _place_hit_sphere(empty, root_obj, scale: float, bounds):
    """Move and size one hit sphere empty"""
    # a write here tags another depsgraph update, so only write a change
    size = bounds["local_norm"] / scale
    at = from_bk_space(root_obj, scale) @ mathutils.Vector(bounds["center"])
    # location reads through the parent, so take the world point back through it
    local = (root_obj.matrix_world @ empty.matrix_parent_inverse).inverted() @ at
    if abs(empty.empty_display_size - size) > 1e-6:
        empty.empty_display_size = size
    if (empty.location - local).length > 1e-6:
        empty.location = local
    if max(abs(value - 1.0) for value in empty.scale) > 1e-6:
        empty.scale = (1.0, 1.0, 1.0)


@persistent
def _follow_hit_spheres(scene, depsgraph):
    """Keep every hit sphere on the model it was made from"""
    for empty in bpy.data.objects:
        root_obj = empty.parent
        if not empty.get(HIT_SPHERE_PROP) or root_obj is None:
            continue
        try:
            bounds = read_vertex_bounds(depsgraph, root_obj, scene.hm64_bk64_scale)
            if bounds["count"]:
                _place_hit_sphere(empty, root_obj, scene.hm64_bk64_scale, bounds)
        except Exception:  # a handler that raises does so on every update
            continue


class BK64_ShowHitSphere(Operator):
    bl_idname = "object.hm64_bk64_show_hit_sphere"
    bl_label = "Show Hit Sphere"
    bl_description = "Put an empty around the model at the radius an actor gets hit inside"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            with object_mode(context):
                root_obj = resolve_root(context)
                scale = context.scene.hm64_bk64_scale
                bounds = read_vertex_bounds(context.evaluated_depsgraph_get(), root_obj, scale)
                if not bounds["count"]:
                    raise PluginError(f"'{root_obj.name}' has no mesh geometry to measure.")

                name = f"{root_obj.name}_hit_sphere"
                empty = bpy.data.objects.get(name)
                if empty is None or empty.type != "EMPTY":
                    empty = bpy.data.objects.new(name, None)
                    context.scene.collection.objects.link(empty)
                empty[HIT_SPHERE_PROP] = 1
                empty.empty_display_type = "SPHERE"
                empty.show_in_front = True  # or the mesh hides the far side of it
                empty.parent = root_obj
                empty.matrix_parent_inverse = root_obj.matrix_world.inverted()
                _place_hit_sphere(empty, root_obj, scale, bounds)

            cull = max(bounds["global_norm"], root_obj.hm64_bk64_cull_radius_raw)
            spot = "({:.3f}, {:.3f}, {:.3f})".format(
                *(from_bk_space(root_obj, scale) @ mathutils.Vector(bounds["furthest"]))
            )
            self.report(
                {"INFO"},
                f"Hit radius {bounds['local_norm']}, cull radius {cull}. The vertex setting the hit "
                f"radius is at {spot} in world space, furthest from the center of the model's box.",
            )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_WeldBoneSeams(Operator):
    bl_idname = "object.hm64_bk64_weld_bone_seams"
    bl_label = "Weld Bone Seams"
    bl_description = (
        "Put every vertex sitting on one spot onto the same bone, the heaviest weighted one. "
        "For an older model whose seams pull apart in game"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            root_obj = resolve_root(context)
            meshes = [root_obj] if root_obj.type == "MESH" else root_obj.children_recursive
            welded = 0
            with object_mode(context):
                for mesh_obj in [obj for obj in meshes if obj.type == "MESH"]:
                    bones = {group.index: group for group in mesh_obj.vertex_groups if group.name.startswith("bk_")}
                    at_spot = {}
                    for vertex in mesh_obj.data.vertices:
                        held = {entry.group: entry.weight for entry in vertex.groups if entry.group in bones}
                        if held:
                            at_spot.setdefault(tuple(round(value, 4) for value in vertex.co), []).append(
                                (vertex.index, held)
                            )

                    for spot, sitting in at_spot.items():
                        groups = {index for _vertex, held in sitting for index in held}
                        if len(groups) < 2:
                            continue
                        weights = {}
                        for _vertex, held in sitting:
                            for index, weight in held.items():
                                weights[index] = weights.get(index, 0.0) + weight
                        # the heaviest weight wins, the same tie break the export uses
                        winner = max(weights.items(), key=lambda item: (item[1], -item[0]))[0]
                        indices = [vertex for vertex, _held in sitting]
                        for index in groups - {winner}:
                            bones[index].remove(indices)
                        bones[winner].add(indices, 1.0, "REPLACE")
                        welded += 1

                    # a group left holding nothing is noise in the list
                    for group in list(mesh_obj.vertex_groups):
                        if group.name.startswith("bk_") and not any(
                            entry.group == group.index for vert in mesh_obj.data.vertices for entry in vert.groups
                        ):
                            mesh_obj.vertex_groups.remove(group)

            root_obj.hm64_bk64_contract = SCENE_CONTRACT
            counted = "1 spot" if welded == 1 else f"{welded} spots"
            self.report(
                {"INFO"},
                f"{counted} put back on one bone."
                if welded
                else "Every spot already followed one bone, so nothing moved.",
            )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_SetDetailLevelRange(Operator):
    bl_idname = "object.hm64_bk64_set_detail_level_range"
    bl_label = "Edit Range"
    bl_description = "Change the distances this detail level covers. Its vertex group is renamed to match"
    bl_options = {"REGISTER", "UNDO"}

    near: IntProperty(default=0)
    far: IntProperty(default=0)
    new_near: IntProperty(name="Near Distance", default=0, min=0, max=0x3FFF)
    new_far: IntProperty(name="Far Distance", default=0, min=0, max=0x3FFF)

    def invoke(self, context, event):
        self.new_near, self.new_far = self.near, self.far
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "new_near")
        col.prop(self, "new_far")
        col.label(text="In BK units, from the joint this level hangs off.")

    def execute(self, context):
        try:
            root_obj = resolve_root(context)
            records = stored_layout(root_obj)
            if records is None:
                raise PluginError("This model came with no geo layout, so it has no levels to move.")
            if self.new_far <= self.new_near:
                raise PluginError("Far Distance has to be past Near Distance, or the level never draws.")
            was, now = (self.near, self.far), (self.new_near, self.new_far)
            if now != was and now in layout_detail_levels(records):
                raise PluginError(
                    f"A level between {now[0]} and {now[1]} is already here, and both would want "
                    f"the group {geo_node_group(('lod',) + now)}."
                )
            if not set_detail_level(records, was, now):
                raise PluginError(f"This model has no level between {was[0]} and {was[1]} any more.")
            root_obj[GEO_LAYOUT_PROP] = json.dumps(records)

            # the name carries the distances, so it moves with them or the export stops finding it
            old_name, new_name = geo_node_group(("lod",) + was), geo_node_group(("lod",) + now)
            meshes = [root_obj] if root_obj.type == "MESH" else root_obj.children_recursive
            for mesh_obj in [obj for obj in meshes if obj.type == "MESH"]:
                group = mesh_obj.vertex_groups.get(old_name)
                if group is not None:
                    group.name = new_name
            self.report({"INFO"}, f"That level now draws between {now[0]} and {now[1]}.")
            for low, high in layout_level_gaps(records):
                self.report(
                    {"WARNING"},
                    f"Nothing draws between {low} and {high} now. Move the next level's "
                    f"Near Distance to {low} to close it.",
                )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_PutInDetailLevel(Operator):
    bl_idname = "object.hm64_bk64_put_in_detail_level"
    bl_label = "Put In Detail Level"
    bl_description = "Draw the selected meshes only at this distance, or the selected vertices in edit mode"
    bl_options = {"REGISTER", "UNDO"}

    near: IntProperty(default=0)
    far: IntProperty(default=0)

    def execute(self, context):
        try:
            wanted = geo_node_group(("lod", self.near, self.far)) if self.far else None
            moved = _put_in_node(context, wanted, "lod")
            counted = "1 vertex" if moved == 1 else f"{moved} vertices"
            self.report(
                {"INFO"},
                f"{counted} now draw between {self.near} and {self.far}."
                if wanted is not None
                else f"{counted} left their detail level, so they draw at every distance.",
            )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


def _put_in_node(context, wanted, kind: str):
    """Move the selection into that node's group, out of whatever node of the same kind held it"""
    editing = context.mode == "EDIT_MESH"
    meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if not meshes:
        raise PluginError("Select the mesh to move.")

    moved = 0
    # a vertex group can't be touched from edit mode, and leaving it writes the
    # selection back to the mesh, where this reads it
    with object_mode(context):
        for mesh_obj in meshes:
            indices = [vertex.index for vertex in mesh_obj.data.vertices if vertex.select or not editing]
            if not indices:
                continue
            # vanilla puts hand states inside a detail level, so a face can be in one
            # of each and only this kind is left behind
            left = [
                group
                for group in mesh_obj.vertex_groups
                if (geo_node_of_group(group.name) or (None,))[0] == kind and group.name != wanted
            ]
            for group in left:
                group.remove(indices)
            for group in left:
                if not any(entry.group == group.index for vert in mesh_obj.data.vertices for entry in vert.groups):
                    mesh_obj.vertex_groups.remove(group)
            if wanted is not None:
                group = mesh_obj.vertex_groups.get(wanted) or mesh_obj.vertex_groups.new(name=wanted)
                group.add(indices, 1.0, "REPLACE")
            moved += len(indices)
    return moved


class BK64_SplitNodes(Operator):
    bl_idname = "object.hm64_bk64_split_nodes"
    bl_label = "Split Layout Nodes"
    bl_description = "Give each level or state its own object, so one can be hidden or moved without the rest"
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty(default="lod")

    def execute(self, context):
        try:
            root_obj = resolve_root(context)
            meshes = [root_obj] if root_obj.type == "MESH" else root_obj.children_recursive
            made = 0
            for mesh_obj in [obj for obj in meshes if obj.type == "MESH"]:
                levels = [
                    group.name
                    for group in mesh_obj.vertex_groups
                    if (geo_node_of_group(group.name) or (None,))[0] == self.kind and len(mesh_obj.vertex_groups) > 1
                ]
                # the first level stays in the object it is in, the rest move out
                for name in levels[1:]:
                    with object_mode(context):
                        for obj in context.view_layer.objects:
                            obj.select_set(obj is mesh_obj)
                        context.view_layer.objects.active = mesh_obj
                        # an earlier split can leave a group behind with nothing in it,
                        # and edit mode holds its own selection, so count members here
                        index = mesh_obj.vertex_groups[name].index
                        empty = not any(
                            entry.group == index for vert in mesh_obj.data.vertices for entry in vert.groups
                        )
                    if empty:
                        continue
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_all(action="DESELECT")
                    mesh_obj.vertex_groups.active_index = mesh_obj.vertex_groups[name].index
                    bpy.ops.object.vertex_group_select()
                    bpy.ops.mesh.separate(type="SELECTED")
                    bpy.ops.object.mode_set(mode="OBJECT")
                    made += 1

            # the box was ticked while this was one object, so the update had nothing to move
            if root_obj.hm64_bk64_spread_levels:
                spread_detail_levels(root_obj, context)

            named = "level" if self.kind == "lod" else "state" if self.kind == "selector" else "half"
            counted = f"1 {named}" if made == 1 else f"{made} {named}s"
            self.report({"INFO"}, f"{counted} left as their own object. The export draws them the same.")
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_PutInSort(Operator):
    bl_idname = "object.hm64_bk64_put_in_sort"
    bl_label = "Put In Sort"
    bl_description = "Draw the selected meshes as this half of a sort, or the selected vertices in edit mode"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=1, min=1)
    side: IntProperty(default=0, min=-1, max=1)

    def execute(self, context):
        try:
            wanted = geo_node_group(("sort", self.index, self.side)) if self.side >= 0 else None
            moved = _put_in_node(context, wanted, "sort")
            counted = "1 vertex" if moved == 1 else f"{moved} vertices"
            self.report(
                {"INFO"},
                (
                    f"{counted} now draw as half {SORT_SIDES[self.side]} of sort {self.index}."
                    if wanted is not None
                    else f"{counted} left their sort, so they draw in the order they were built."
                ),
            )
            return {"FINISHED"}

        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


class BK64_PutInSelectorState(Operator):
    bl_idname = "object.hm64_bk64_put_in_selector_state"
    bl_label = "Put In Selector State"
    bl_description = (
        "Draw the selected meshes only in this state of an appendage, or the selected vertices in "
        "edit mode. Game code picks the state"
    )
    bl_options = {"REGISTER", "UNDO"}

    appendage: IntProperty(default=1, min=1, max=MAX_APPENDAGE_ID)
    state: IntProperty(default=1, min=0)

    def execute(self, context):
        try:
            wanted = geo_node_group(("selector", self.appendage, self.state)) if self.state else None
            moved = _put_in_node(context, wanted, "selector")
            counted = "1 vertex" if moved == 1 else f"{moved} vertices"
            self.report(
                {"INFO"},
                (
                    f"{counted} now draw in state {self.state} of appendage {self.appendage}."
                    if wanted is not None
                    else f"{counted} left their state, so they draw whatever the game picks."
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
                    raise PluginError(f"{level} is opaque only. Set Halves to Opaque or Both.")

                triangles, brought, caveats = 0, [], []
                for half in wanted:
                    path = _level_resource(folder, layers[half], level, half)
                    if path is None:
                        raise PluginError(
                            f"{level} {half} isn't in that folder. It should hold "
                            f"ASSET_{layers[half]:04X}_{level}_{half} and its _GEO, _VTX and _tex siblings."
                        )
                    _armature_obj, mesh_obj, model = import_bk64_model(context, path, BK64_Settings(scene))
                    # so Export Level Halves puts it back where it came from
                    mesh_obj.hm64_bk64_level_half = "TRANSLUCENT" if half == "XLU" else "OPAQUE"
                    triangles += len(mesh_obj.data.polygons)
                    brought.append(half)
                    # the same things the model importer says, or a level round trips quietly wrong
                    if model["dropped"]:
                        caveats.append(f"{half}: {model['dropped']} triangles came in without their vertices.")
                    if model["unbound_textures"]:
                        caveats.append(
                            f"{half}: {model['unbound_textures']} textures aren't bound by the display "
                            "list and won't be there on the way out."
                        )
                    if model["mesh_list_dropped"]:
                        caveats.append(
                            f"{half}: {model['mesh_list_dropped']} mesh list vertices aren't drawn by the "
                            "display list and won't be there on the way out."
                        )

                note = " Each half is its own object." if len(brought) > 1 else ""
                for caveat in caveats:
                    self.report({"WARNING"}, caveat)
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
                    # no bound model draws under a BONE command, so the table decides it
                    scene.hm64_bk64_rigging = "BIND" if model["bound_vertices"] else "SPLIT"
                scene.hm64_bk64_env_map = bool(model["geo_type"] & GEO_TYPE_ENV_MAP)
                scene.hm64_bk64_mipmap = bool(model["geo_type"] & GEO_TYPE_MIPMAP_TRILINEAR)

                # a level is two models and this reads one, so say which it was
                level = bk64_level_of_asset(path)
                if level is not None:
                    level_name, layer = level
                    mesh_obj.hm64_bk64_level_half = "TRANSLUCENT" if layer == "XLU" else "OPAQUE"

                notes = []
                if level is not None:
                    notes.append(
                        f"It is the {layer} half of {level_name}, and Level Half is set to match. "
                        "Import BK Level brings in both at once if you want them together."
                    )
                kept = model.get("geo_commands", ())
                if kept:
                    notes.append(f"Its geo layout uses {', '.join(kept)}, kept for re-export.")
                if model.get("lod_levels"):
                    notes.append(
                        f"Its {model['lod_levels']} detail levels came in as vertex groups, named "
                        "for the distances they cover."
                    )
                if model.get("selector_states"):
                    notes.append(
                        f"Its {model['selector_states']} appendage states came in as vertex groups, "
                        "for game code to pick between."
                    )
                if model["mesh_list"]:
                    notes.append(f"Its mesh list came in as {len(model['mesh_list'])} vertex groups.")
                    if model["mesh_list_dropped"]:
                        notes.append(
                            f"{model['mesh_list_dropped']} of those vertices aren't drawn by the display "
                            "list, so they won't come back on a re-export."
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
                if model["external_textures"]:
                    notes.append(
                        f"Its {model['external_textures']} textures are in Tooie's shared texture bank, "
                        "not the model, so it came in untextured."
                    )
                if model["collision_only_object"] is not None:
                    faces = len(model["collision_only_object"].data.polygons)
                    notes.append(f"{faces} collision triangles sit on geometry nothing draws, in their own mesh.")
                if model["bones"]:
                    bound = bool(model["bound_vertices"])
                    scheme = "Bind Vertices" if bound else "Split At Bones"
                    notes.append(f"Animation Scale came in with it, and Rigging is set to {scheme}.")
                    if not bound and not mesh_obj.vertex_groups:
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
    BK64_ExportLevelHalves,
    BK64_ExportAnimation,
    BK64_ExportAllAnimations,
    BK64_PromoteMaterials,
    BK64_SplitMeshAtBones,
    BK64_AddMeshEffect,
    BK64_SelectLooseVertices,
    BK64_MarkCollisionOnly,
    BK64_WeldBoneSeams,
    BK64_PutInDetailLevel,
    BK64_SetDetailLevelRange,
    BK64_PutInSelectorState,
    BK64_PutInSort,
    BK64_SplitNodes,
    BK64_ShowHitSphere,
    BK64_ImportSkeleton,
    BK64_ImportModel,
    BK64_ImportLevel,
    BK64_ImportAnimation,
)


def bk64_operators_register():
    for cls in bk64_operator_classes:
        register_class(cls)
    bpy.app.handlers.depsgraph_update_post.append(_follow_hit_spheres)


def bk64_operators_unregister():
    for cls in reversed(bk64_operator_classes):
        unregister_class(cls)
    if _follow_hit_spheres in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_follow_hit_spheres)
