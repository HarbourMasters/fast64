from __future__ import annotations

from bpy.utils import register_class, unregister_class

from ...f3d.flipbook import drawTextureArray
from ...panels import BK64_Panel
from ...utility import prop_split
from .bk64_constants import BK_COLLISION_FLAG_BITS, SORT_SIDES
from .bk64_geo import geo_node_of_group, layout_detail_levels, layout_selectors, stored_layout
from .bk64_model import in_level_half, level_half_faces, read_vertex_bounds
from .bk64_operators import (
    BK64_AddMeshEffect,
    BK64_ExportAllAnimations,
    BK64_ImportAnimation,
    BK64_ExportAnimation,
    BK64_ExportModel,
    BK64_ExportLevelHalves,
    BK64_ImportLevel,
    BK64_ImportModel,
    BK64_ImportSkeleton,
    BK64_PromoteMaterials,
    BK64_MarkCollisionOnly,
    BK64_PutInDetailLevel,
    BK64_PutInSelectorState,
    BK64_PutInSort,
    BK64_SelectLooseVertices,
    BK64_SplitNodes,
    BK64_ShowHitSphere,
    BK64_SplitMeshAtBones,
    resolve_root,
)


class BK64_ExportModelPanel(BK64_Panel):
    bl_idname = "BK64_PT_export_model"
    bl_label = "Model Exporter"
    bl_order = 0

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene

        prop_split(col, scene, "hm64_bk64_file_format", "Format")
        prop_split(col, scene, "hm64_bk64_export_path", "Export Folder")
        prop_split(col, scene, "hm64_bk64_resource_name", "Resource Path")
        prop_split(col, scene, "hm64_bk64_scale", "Blender To BK Scale")
        prop_split(col, scene, "hm64_bk64_anim_scale", "Animation Scale")
        prop_split(col, scene, "hm64_bk64_rigging", "Rigging")
        prop_split(col, scene, "hm64_bk64_draw_layer", "Default Draw Layer")

        col.prop(scene, "hm64_bk64_force_unlit")

        # an imported model writes its own geo type, and these two lose to it
        try:
            root = resolve_root(context)
        except Exception:  # a draw callback must never raise
            root = None
        stored = root.hm64_bk64_geo_type_raw if root is not None else 0
        sub = col.column()
        sub.enabled = not stored
        sub.prop(scene, "hm64_bk64_env_map")
        sub.prop(scene, "hm64_bk64_mipmap")
        if stored:
            prop_split(col, root, "hm64_bk64_geo_type_raw", "Imported Geo Type")
            box = col.box().column()
            box.label(text="This model came in with its own geo type, so the two")
            box.label(text="boxes above do nothing. Set it to 0 to use them instead.")

        col.operator(BK64_ExportModel.bl_idname)

        # its own box, or the settings above it read as its settings
        col.separator()
        halves = col.box().column()
        obj = context.object
        if obj is not None and obj.type == "MESH":
            prop_split(halves, obj, "hm64_bk64_level_half", "Level Half")
            if obj.hm64_bk64_level_half == "AUTO":
                if level_half_faces(obj, "OPAQUE") and level_half_faces(obj, "TRANSLUCENT"):
                    halves.label(text="Its materials read as both, so it goes out cut in two.")
                else:
                    which = "translucent" if in_level_half(obj, "TRANSLUCENT") else "opaque"
                    halves.label(text=f"Its materials read as {which}.")
        # the root is usually not a mesh, so the row above is often missing
        meshes = [] if root is None else ([root] if root.type == "MESH" else root.children_recursive)
        drawn = [child for child in meshes if child.type == "MESH" and not child.ignore_render]
        if len(drawn) > 1:  # one mesh already says what it reads as, just above
            counts = {"OPAQUE": 0, "TRANSLUCENT": 0}
            for child in drawn:
                for half in counts:
                    if in_level_half(child, half):
                        counts[half] += 1
            halves.label(text=f"{counts['OPAQUE']} opaque, {counts['TRANSLUCENT']} translucent")
        halves.operator(BK64_ExportLevelHalves.bl_idname)

        box = col.box().column()
        box.label(text="Select the armature, or the mesh for a static model.")
        box.label(text="Split At Bones needs the mesh cut first, Bind Vertices doesn't.")
        box.label(text="Level Half picks which model, Export Level Halves writes both.")
        box.label(text="Geo Type per bone and collision per material are in Properties.")
        if scene.hm64_bk64_file_format == "O2R":
            box.label(text="Pack the folder with: torch pack <folder> <name>.o2r o2r")


class BK64_ExportAnimationPanel(BK64_Panel):
    bl_idname = "BK64_PT_export_animation"
    bl_label = "Animations"
    bl_order = 2

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene

        prop_split(col, scene, "hm64_bk64_anim_scale", "Animation Scale")
        prop_split(col, scene, "hm64_bk64_anim_path", "Animation Path")
        col.prop(scene, "hm64_bk64_anim_include_rest")
        col.operator(BK64_ExportAnimation.bl_idname)
        col.operator(BK64_ExportAllAnimations.bl_idname)

        prop_split(col, scene, "hm64_bk64_anim_import_path", "Animation File")
        col.operator(BK64_ImportAnimation.bl_idname)

        box = col.box().column()
        box.label(text="Exports the armature's active action, over its own frame range.")
        box.label(text="Export All Actions writes every action on this rig, named after it.")
        box.label(text="Format, folder and scale come from the Model Exporter.")
        box.label(text="Animation Scale must match the model this plays on.")
        box.label(text="Import puts one on the selected armature, by bone id.")


class BK64_ImportModelPanel(BK64_Panel):
    bl_idname = "BK64_PT_import_model"
    bl_label = "Model Importer"
    bl_order = 1

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene

        prop_split(col, scene, "hm64_bk64_import_path", "Model File")
        prop_split(col, scene, "hm64_bk64_import_bone_length", "Bone Length")
        col.operator(BK64_ImportModel.bl_idname)
        col.operator(BK64_ImportSkeleton.bl_idname)

        box = col.box().column()
        box.label(text="Import BK Model brings in the mesh, textures and armature.")
        box.label(text="Import BK Skeleton takes only the bones, ids included, so a")
        box.label(text="replacement accepts the original's animations.")
        box.label(text="An o2r model needs its _GEO, _VTX and _tex siblings beside it.")
        box.label(text="For a level use Import BK Level below, a level is two models.")

        col.separator()
        prop_split(col, scene, "hm64_bk64_level_folder", "Level Folder")
        prop_split(col, scene, "hm64_bk64_level", "Level")
        prop_split(col, scene, "hm64_bk64_level_layer", "Halves")
        col.operator(BK64_ImportLevel.bl_idname)

        box = col.box().column()
        box.label(text="Import BK Level finds a level by name, so you don't have to")
        box.label(text="hunt for its ASSET_ file. Unpack bk.o2r and point at the")
        box.label(text="assets/level folder inside. Each half comes in as its own")
        box.label(text="object, so the translucent one can be hidden while you work.")


class BK64_MeshToolsPanel(BK64_Panel):
    bl_idname = "BK64_PT_mesh_tools"
    bl_label = "Mesh Tools"
    bl_order = 3

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene

        col.operator(BK64_PromoteMaterials.bl_idname)
        col.operator(BK64_SplitMeshAtBones.bl_idname)
        col.operator(BK64_SelectLooseVertices.bl_idname)
        col.operator(BK64_MarkCollisionOnly.bl_idname)

        col.separator()
        prop_split(col, scene, "hm64_bk64_mesh_effect", "Effect")
        prop_split(col, scene, "hm64_bk64_scroll_speed", "Speed")
        col.operator(BK64_AddMeshEffect.bl_idname)

        box = col.box().column()
        box.label(text="These change the mesh you have selected, not the export.")
        box.label(text="Collision Only makes a mesh an invisible floor or wall.")
        box.label(text="Pick the faces in edit mode before Add Mesh Effect.")
        box.label(text="Scroll only moves vertically, and effects only run on a level.")

        col.separator()
        radii = col.box().column()
        try:
            root = resolve_root(context)
        except Exception:  # a draw callback must never raise
            root = None
        kept = root.hm64_bk64_cull_radius_raw if root is not None else 0
        try:
            bounds = (
                read_vertex_bounds(context.evaluated_depsgraph_get(), root, scene.hm64_bk64_scale)
                if root is not None
                else None
            )
        except Exception:
            bounds = None
        if bounds is not None and bounds["count"]:
            radii.label(text=f"Hit Radius: {bounds['local_norm']}")
            radii.label(text=f"Cull Radius: {max(bounds['global_norm'], kept)}")
        if root is not None and root.type == "ARMATURE":
            # the export measures in the armature's space, so its own transform cancels
            _at, turn, size = root.matrix_world.decompose()
            if any(abs(value - 1.0) > 1e-4 for value in size) or abs(turn.angle) > 1e-4:
                radii.label(text="The armature's own scale and rotation stay out of the")
                radii.label(text="file, so they don't move these. Scale the mesh instead.")
        radii.operator(BK64_ShowHitSphere.bl_idname)
        if kept:
            prop_split(radii, root, "hm64_bk64_cull_radius_raw", "Imported Cull Radius")
        radii.label(text="An actor is hit anywhere inside its hit radius, out from the")
        radii.label(text="center of the model's box, so one far vertex widens it.")
        radii.label(text="Cull radius runs from the origin and decides when it leaves")
        radii.label(text="the screen. Collision only meshes count toward both.")


def _model_meshes(root):
    """Every mesh of the model, the root included when it is one"""
    if root is None:
        return []
    return [obj for obj in ([root] + list(root.children_recursive)) if obj.type == "MESH"]


class BK64_GeoNodesPanel(BK64_Panel):
    bl_idname = "BK64_PT_geo_nodes"
    bl_label = "Geo Nodes"
    bl_order = 4

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene
        try:
            root = resolve_root(context)
        except Exception:  # a draw callback must never raise
            root = None
        if root is None:
            col.box().label(text="Select the model to see the nodes it has.")

        levels = layout_detail_levels(stored_layout(root) or []) if root is not None else []
        if levels:
            detail = col.box().column()
            detail.label(text="Detail Levels")
            for near, far in levels:
                button = detail.operator(BK64_PutInDetailLevel.bl_idname, text=f"Put In {near}-{far}")
                button.near, button.far = near, far
            detail.operator(BK64_PutInDetailLevel.bl_idname, text="Take Out Of Every Level").far = 0
            detail.separator()
            detail.operator(BK64_SplitNodes.bl_idname, text="Split Detail Levels").kind = "lod"
            detail.prop(root, "hm64_bk64_spread_levels")
            aside = [obj for obj in _model_meshes(root) if any(obj.hm64_bk64_view_offset)]
            if aside:
                step = max(max(abs(value) for value in obj.hm64_bk64_view_offset) for obj in aside)
                detail.label(text=f"Standing aside up to {step:.2f} for viewing. The export puts them back.")
            detail.label(text="The model draws one level at a time, by how far away the")
            detail.label(text="camera is. Geometry in no level draws at every distance.")

        sorts = col.box().column()
        sorts.label(text="Sorts")
        prop_split(sorts, scene, "hm64_bk64_sort_index", "Sort")
        row = sorts.row(align=True)
        for side, name in enumerate(SORT_SIDES):
            button = row.operator(BK64_PutInSort.bl_idname, text=f"Put In Half {name.upper()}")
            button.index, button.side = scene.hm64_bk64_sort_index, side
        sorts.operator(BK64_PutInSort.bl_idname, text="Take Out Of Every Sort").side = -1

        held = {}
        for mesh_obj in _model_meshes(root):
            for group in mesh_obj.vertex_groups:
                node = geo_node_of_group(group.name)
                if node is not None and node[0] == "sort":
                    held.setdefault(node[1], set()).add(SORT_SIDES[node[2]])
        for index in sorted(held):
            sides = ", ".join(sorted(held[index]))
            sorts.label(text=f"Sort {index} holds half {sides}")

        sorts.label(text="Fixes translucent faces that draw over each other in the")
        sorts.label(text="wrong order. Put each side in one half and the game keeps")
        sorts.label(text="the nearer half in front. Opaque geometry doesn't need it.")
        sorts.label(text="Fill both halves.")

        selectors = layout_selectors(stored_layout(root) or []) if root is not None else []
        if selectors:
            states = col.box().column()
            states.label(text="Selector States")
            prop_split(states, scene, "hm64_bk64_appendage", "Appendage")
            # the stored pick can outlive the model it came from
            chosen = int(scene.hm64_bk64_appendage) if scene.hm64_bk64_appendage.isdigit() else 0
            row = states.row(align=True)
            for state in range(1, dict(selectors).get(chosen, 0) + 1):
                button = row.operator(BK64_PutInSelectorState.bl_idname, text=f"State {state}")
                button.appendage, button.state = chosen, state
            states.operator(BK64_PutInSelectorState.bl_idname, text="Take Out Of Every State").state = 0
            states.operator(BK64_SplitNodes.bl_idname, text="Split Selector States").kind = "selector"

            kept = {}
            for mesh_obj in _model_meshes(root):
                for group in mesh_obj.vertex_groups:
                    node = geo_node_of_group(group.name)
                    if node is not None and node[0] == "selector":
                        kept.setdefault(node[1], set()).add(node[2])
            if chosen in kept:
                shown = ", ".join(str(state) for state in sorted(kept[chosen]))
                states.label(text=f"Appendage {chosen} holds state {shown}")
            elsewhere = sorted(appendage for appendage in kept if appendage != chosen)
            if elsewhere:
                states.label(text="Also filled: " + ", ".join(str(appendage) for appendage in elsewhere))

            states.label(text="Game code picks which state draws, so a hand can hold")
            states.label(text="something or a face can swap. Geometry in no state draws")
            states.label(text="whatever it picks.")


class BK64_BonePanel(BK64_Panel):
    bl_idname = "BK64_PT_bone_inspector"
    bl_label = "BK64 Bone Inspector"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and context.bone is not None

    def draw(self, context):
        col = self.layout.column()
        prop_split(col, context.bone, "hm64_bk64_bone_id", "BK Bone ID")
        prop_split(col, context.bone, "hm64_bk64_bone_order", "Table Order")
        prop_split(col, context.bone, "hm64_bk64_geo_type", "Geo Type")
        if context.bone.hm64_bk64_geo_type == "SELECTOR":
            prop_split(col, context.bone, "hm64_bk64_geo_index", "Appendage ID")
            col.box().label(text="Each child bone is one option, in table order.")
        elif context.bone.hm64_bk64_geo_type == "REFPOINT":
            prop_split(col, context.bone, "hm64_bk64_geo_index", "Point Slot")
        elif context.bone.hm64_bk64_geo_type == "LOD":
            prop_split(col, context.bone, "hm64_bk64_lod_near", "Near Distance")
            prop_split(col, context.bone, "hm64_bk64_lod_far", "Far Distance")
        elif context.bone.hm64_bk64_geo_type == "SORT":
            col.box().label(text="Its two child bones, drawn nearest last.")
        elif context.bone.hm64_bk64_geo_type == "DRAWDIST":
            col.box().label(text="The box comes from the geometry under it.")


class BK64_MaterialPanel(BK64_Panel):
    bl_idname = "BK64_PT_material_collision"
    bl_label = "BK64 Material"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and context.material is not None

    def draw(self, context):
        col = self.layout.column()
        material = context.material
        prop_split(col, material, "hm64_bk64_draw_layer", "Draw Layer")
        prop_split(col, material, "hm64_bk64_level_half", "Level Half")
        prop_split(col, material.f3d_mat.rdp_settings, "g_mdsft_alpha_compare", "Alpha Compare")
        if material.f3d_mat.rdp_settings.g_mdsft_alpha_compare == "G_AC_NONE" and material.f3d_mat.presetName.endswith(
            "Cutout"
        ):
            col.box().label(text="A cutout blends its edges without Threshold here.")

        prop_split(col, material, "hm64_bk64_anim_tex", "Animated Texture")
        if material.hm64_bk64_anim_tex != "NONE":
            prop_split(col, material, "hm64_bk64_anim_slot", "Slot")
            prop_split(col, material, "hm64_bk64_anim_rate", "Frames Per Second")
            # anything but Individual, which adds a name field only OoT reads
            drawTextureArray(col.box().column(), material.flipbookGroup.flipbook0.textures, 0, "Array")
            box = col.box().column()
            box.label(text="List every frame, starting with the one the material samples.")
            box.label(text="Frames share one size and format, and can't be CI4 or CI8.")

        if material.hm64_bk64_collision_raw:
            prop_split(col, material, "hm64_bk64_collision_raw", "Raw Flags")
            prop_split(col, material, "hm64_bk64_collision_unk6", "Raw Unk6")
            col.box().label(text="Imported surface, written back as it came in.")
            return
        prop_split(col, material, "hm64_bk64_collision_type", "Collision")
        if material.hm64_bk64_collision_type != "NONE":
            prop_split(col, material, "hm64_bk64_sound_type", "Sound Type")
            box = col.box().column()
            box.label(text="Surface Flags")
            for name in BK_COLLISION_FLAG_BITS:
                box.prop(material, f"hm64_bk64_{name}")
            if material.hm64_bk64_collision_extra:
                prop_split(box, material, "hm64_bk64_collision_extra", "Other Flags")


bk64_panel_classes = (
    BK64_ExportModelPanel,
    BK64_ExportAnimationPanel,
    BK64_ImportModelPanel,
    BK64_MeshToolsPanel,
    BK64_GeoNodesPanel,
    BK64_BonePanel,
    BK64_MaterialPanel,
)


def bk64_panels_register():
    for cls in bk64_panel_classes:
        register_class(cls)


def bk64_panels_unregister():
    for cls in reversed(bk64_panel_classes):
        unregister_class(cls)
