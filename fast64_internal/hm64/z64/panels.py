"""HM64 panels for the HM64 UI tab.

Export panels for SOH (Ship of Harkinian) and 2SHIP (2 Ship) XML workflows.
Inspector panels (DL, Material, Draw Layers) are handled by the upstream OOT
panels via compatibility hooks, so they don't need to be mirrored here.
"""

import bpy
from bpy.types import Mesh, Operator, UIList
from bpy.utils import register_class, unregister_class

from ..panels import HM64_Panel
from ...z64.f3d.properties import OOTDLExportSettings


# --- Matrix Call Pair support (used by DL export settings) ---

class OOT_UL_MatrixCallPairs(UIList):
    bl_idname = "OOT_UL_matrix_call_pairs"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        label = item.matrix_path if item.matrix_path else "No matrix"
        row = layout.row(align=True)
        row.label(text=label, icon="MESH_TORUS")


class FAST64_OT_AddObjectMatrixCall(Operator):
    bl_idname = "fast64.oot_add_object_matrix_call"
    bl_label = "Add Matrix Call (Object)"
    bl_description = "Add a new matrix-call pair to this object"

    @classmethod
    def poll(cls, context):
        return context.object is not None and isinstance(context.object.data, Mesh)

    def execute(self, context):
        obj = context.object
        settings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        entry = obj.oot_matrix_calls.add()
        obj.oot_matrix_calls_index = len(obj.oot_matrix_calls) - 1
        entry.limb = "none"
        entry.call_dl = ""
        entry.internal_path = settings.folder
        return {"FINISHED"}


class FAST64_OT_RemoveObjectMatrixCall(Operator):
    bl_idname = "fast64.oot_remove_object_matrix_call"
    bl_label = "Remove Matrix Call (Object)"
    bl_description = "Remove the selected matrix-call pair from this object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and isinstance(obj.data, Mesh) and len(obj.oot_matrix_calls) > 0

    def execute(self, context):
        obj = context.object
        index = obj.oot_matrix_calls_index
        obj.oot_matrix_calls.remove(index)
        obj.oot_matrix_calls_index = max(0, min(index, len(obj.oot_matrix_calls) - 1))
        return {"FINISHED"}


# --- HM64 Export Panels ---

class HM64_ExportDLPanel(HM64_Panel):
    bl_idname = "HM64_PT_export_dl"
    bl_label = "DL Exporter"

    def draw(self, context):
        from .operators import HM64_ExportDLOperator
        from ...utility import prop_split

        col = self.layout.column()
        col.operator(HM64_ExportDLOperator.bl_idname)
        settings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        col.label(text="Object name used for export.", icon="INFO")
        prop_split(col, settings, "folder", "Internal Path")
        prop_split(col, settings, "customPath", "Path")
        prop_split(col, settings, "actorOverlayName", "Overlay (Optional)")

        obj = context.object
        if obj is not None and isinstance(obj.data, Mesh):
            self._draw_matrix_section(col, obj)

    def _draw_matrix_section(self, layout, obj):
        matrix_box = layout.box()
        matrix_box.label(text=f"Matrix Path + CallDisplayList ({obj.name})", icon="PLUS")
        row = matrix_box.row()
        row.template_list(
            "OOT_UL_matrix_call_pairs",
            "",
            obj,
            "oot_matrix_calls",
            obj,
            "oot_matrix_calls_index",
            rows=3,
        )
        ops = row.column(align=True)
        ops.operator("fast64.oot_add_object_matrix_call", icon="ADD", text="")
        ops.operator("fast64.oot_remove_object_matrix_call", icon="REMOVE", text="")
        collection = obj.oot_matrix_calls
        if collection:
            index = max(0, min(obj.oot_matrix_calls_index, len(collection) - 1))
            active = collection[index]
            matrix_box.prop(active, "limb")
            matrix_box.prop(active, "internal_path", text="Internal Path")
            matrix_box.prop(active, "call_dl", text="Call Display List")


class HM64_AnimatedMaterialsPanel(HM64_Panel):
    bl_idname = "HM64_PT_animated_materials"
    bl_label = "Animated Materials Exporter"

    def draw(self, context):
        from ...z64.animated_mats.panels import Z64_AnimatedMaterialsPanel
        Z64_AnimatedMaterialsPanel.draw(self, context)


class HM64_ExportAnimPanel(HM64_Panel):
    bl_idname = "HM64_PT_export_anim"
    bl_label = "Animation Exporter"

    def draw(self, context):
        from ...z64.animation.panels import OOT_ExportAnimPanel
        OOT_ExportAnimPanel.draw(self, context)


class HM64_ExportCollisionPanel(HM64_Panel):
    bl_idname = "HM64_PT_export_collision"
    bl_label = "Collision Exporter"

    def draw(self, context):
        from ...z64.collision.panels import OOT_ExportCollisionPanel
        OOT_ExportCollisionPanel.draw(self, context)


class HM64_PreviewSettingsPanel(HM64_Panel):
    bl_idname = "HM64_PT_preview_settings"
    bl_label = "CS Preview Settings"

    def draw(self, context):
        from ...z64.cutscene.panels import OoT_PreviewSettingsPanel
        OoT_PreviewSettingsPanel.draw(self, context)


class HM64_CutscenePanel(HM64_Panel):
    bl_idname = "HM64_PT_export_cutscene"
    bl_label = "Cutscene Exporter"

    def draw(self, context):
        from ...z64.cutscene.panels import OOT_CutscenePanel
        OOT_CutscenePanel.draw(self, context)


class HM64_HackerOoTSettingsPanel(HM64_Panel):
    bl_idname = "HM64_PT_hackeroot_settings"
    bl_label = "HackerOoT Settings"

    def draw(self, context):
        from ...z64.hackeroot.panels import HackerOoTSettingsPanel
        HackerOoTSettingsPanel.draw(self, context)


class HM64_ExportScenePanel(HM64_Panel):
    bl_idname = "HM64_PT_export_scene"
    bl_label = "Scene Exporter"

    def drawSceneSearchOp(self, layout, enumValue, opName):
        from ...z64.scene.panels import OOT_ExportScenePanel
        OOT_ExportScenePanel.drawSceneSearchOp(self, layout, enumValue, opName)

    def draw(self, context):
        from ...z64.scene.panels import OOT_ExportScenePanel
        OOT_ExportScenePanel.draw(self, context)


class HM64_ToolsPanel(HM64_Panel):
    bl_idname = "HM64_PT_tools"
    bl_label = "Tools"

    def draw(self, context):
        from ...z64.tools.panel import OoT_ToolsPanel
        OoT_ToolsPanel.draw(self, context)


class HM64_FileSettingsPanel(HM64_Panel):
    bl_idname = "HM64_PT_file_settings"
    bl_label = "Workspace Settings"
    bl_options = set()

    def draw(self, context):
        from ...z64.file_settings import OOT_FileSettingsPanel
        OOT_FileSettingsPanel.draw(self, context)


class HM64_CSMotionCameraShotPanel(HM64_Panel):
    bl_label = "Cutscene Motion Camera Shot Controls"
    bl_idname = "HM64_PT_camera_shot_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        from ...z64.cutscene.motion.panels import OOT_CSMotionCameraShotPanel
        OOT_CSMotionCameraShotPanel.draw(self, context)


# 2SHIP-specific: MM skeleton exporter
class HM64_ExportSkeleton2SHIPPanel(HM64_Panel):
    bl_idname = "HM64_PT_export_skeleton_2ship"
    bl_label = "Skeleton Exporter (2SHIP)"

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode == "2SHIP"

    def draw(self, context):
        from ...hm64.mm.skeleton.operators import MM_ExportSkeleton, MM_ImportSkeleton
        from ...z64.skeleton.properties import OOTSkeletonImportSettings, OOTSkeletonExportSettings

        col = self.layout.column()
        col.operator(MM_ExportSkeleton.bl_idname)
        exportSettings: OOTSkeletonExportSettings = context.scene.fast64.oot.skeletonExportSettings
        exportSettings.draw_props(col)

        col.operator(MM_ImportSkeleton.bl_idname)
        importSettings: OOTSkeletonImportSettings = context.scene.fast64.oot.skeletonImportSettings
        importSettings.draw_props(col)


# --- Registration ---

hm64_panel_classes = (
    HM64_ExportDLPanel,
    HM64_AnimatedMaterialsPanel,
    HM64_ExportAnimPanel,
    HM64_ExportCollisionPanel,
    HM64_PreviewSettingsPanel,
    HM64_CutscenePanel,
    HM64_HackerOoTSettingsPanel,
    HM64_ExportScenePanel,
    HM64_ToolsPanel,
    HM64_FileSettingsPanel,
    HM64_ExportSkeleton2SHIPPanel,
    HM64_CSMotionCameraShotPanel,
)

hm64_support_classes = (
    OOT_UL_MatrixCallPairs,
    FAST64_OT_AddObjectMatrixCall,
    FAST64_OT_RemoveObjectMatrixCall,
)


def register():
    for cls in (*hm64_panel_classes, *hm64_support_classes):
        register_class(cls)


def unregister():
    for cls in reversed((*hm64_panel_classes, *hm64_support_classes)):
        unregister_class(cls)
