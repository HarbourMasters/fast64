from __future__ import annotations

from bpy.utils import register_class, unregister_class

from ...f3d.flipbook import drawTextureArray
from ...panels import BK64_Panel
from ...utility import prop_split
from .bk64_constants import BK_COLLISION_FLAG_BITS
from .bk64_operators import (
    BK64_ExportAllAnimations,
    BK64_ImportAnimation,
    BK64_ExportAnimation,
    BK64_ExportModel,
    BK64_ImportModel,
    BK64_ImportSkeleton,
    BK64_PromoteMaterials,
    BK64_MarkCollisionOnly,
    BK64_SelectLooseVertices,
    BK64_SplitMeshAtBones,
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
        prop_split(col, scene, "hm64_bk64_draw_layer", "Draw Layer")

        col.prop(scene, "hm64_bk64_force_unlit")
        col.prop(scene, "hm64_bk64_env_map")
        col.prop(scene, "hm64_bk64_mipmap")

        col.operator(BK64_PromoteMaterials.bl_idname)
        col.operator(BK64_SplitMeshAtBones.bl_idname)
        col.operator(BK64_SelectLooseVertices.bl_idname)
        col.operator(BK64_MarkCollisionOnly.bl_idname)
        col.operator(BK64_ExportModel.bl_idname)

        box = col.box().column()
        box.label(text="Select the armature, or the mesh for a static model.")
        box.label(text="Split At Bones needs the mesh cut first, Bind Vertices doesn't.")
        box.label(text="Collision Only makes a mesh an invisible floor or wall.")
        box.label(text="Pack the folder with: torch pack <folder> <name>.o2r o2r")


class BK64_ExportAnimationPanel(BK64_Panel):
    bl_idname = "BK64_PT_export_animation"
    bl_label = "Animation Exporter"
    bl_order = 1

    def draw(self, context):
        col = self.layout.column()
        scene = context.scene

        prop_split(col, scene, "hm64_bk64_anim_path", "Animation Path")
        col.prop(scene, "hm64_bk64_anim_include_rest")
        col.operator(BK64_ExportAnimation.bl_idname)
        col.operator(BK64_ExportAllAnimations.bl_idname)

        prop_split(col, scene, "hm64_bk64_anim_import_path", "Animation File")
        col.operator(BK64_ImportAnimation.bl_idname)

        box = col.box().column()
        box.label(text="Exports the armature's active action, over its own frame range.")
        box.label(text="Export All Actions writes every action on this rig, named after it.")
        box.label(text="Format, folder, scale and Animation Scale come from the panel above.")
        box.label(text="Animation Scale must match the model this plays on.")
        box.label(text="Import puts one on the selected armature, by bone id.")


class BK64_ImportModelPanel(BK64_Panel):
    bl_idname = "BK64_PT_import_model"
    bl_label = "Model Importer"
    bl_order = 2

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
        box.label(text="replacement can answer the original's animations id for id.")
        box.label(text="Both need the _GEO, _VTX and _tex siblings in the same folder.")


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
    BK64_BonePanel,
    BK64_MaterialPanel,
)


def bk64_panels_register():
    for cls in bk64_panel_classes:
        register_class(cls)


def bk64_panels_unregister():
    for cls in reversed(bk64_panel_classes):
        unregister_class(cls)
