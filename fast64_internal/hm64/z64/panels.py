"""HM64 MM panels and matrix-call support classes extracted from z64/f3d/panels.py."""

import bpy
from bpy.types import Panel, Mesh, Operator, UIList

from ...panels import MM_Panel
from ...z64.f3d.properties import OOTDLExportSettings


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


class MM_DisplayListPanel(MM_Panel):
    bl_label = "Display List Inspector"
    bl_idname = "OBJECT_PT_OOT_DL_Inspector_mm"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode == "MM" and (
            context.object is not None and isinstance(context.object.data, Mesh)
        )

    def draw(self, context):
        from ...z64.f3d.panels import OOT_DisplayListPanel
        OOT_DisplayListPanel.draw(self, context)


class MM_MaterialPanel(MM_Panel):
    bl_label = "OOT Material"
    bl_idname = "MATERIAL_PT_OOT_Material_Inspector_mm"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.material is not None and context.scene.gameEditorMode == "MM"

    def draw(self, context):
        from ...z64.f3d.panels import OOT_MaterialPanel
        OOT_MaterialPanel.draw(self, context)


class MM_DrawLayersPanel(MM_Panel):
    bl_label = "OOT Draw Layers"
    bl_idname = "WORLD_PT_OOT_Draw_Layers_Panel_mm"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode == "MM"

    def draw(self, context):
        from ...z64.f3d.panels import OOT_DrawLayersPanel
        OOT_DrawLayersPanel.draw(self, context)


class MM_ExportDLPanel(MM_Panel):
    bl_idname = "Z64_PT_export_dl_mm"
    bl_label = "DL Exporter"

    def draw(self, context):
        from ...z64.f3d.panels import OOT_ExportDLPanel
        OOT_ExportDLPanel.draw(self, context)


hm64_panel_classes = (
    MM_DisplayListPanel,
    MM_MaterialPanel,
    MM_DrawLayersPanel,
    MM_ExportDLPanel,
)

hm64_support_classes = (
    OOT_UL_MatrixCallPairs,
    FAST64_OT_AddObjectMatrixCall,
    FAST64_OT_RemoveObjectMatrixCall,
)


def register():
    from bpy.utils import register_class
    for cls in (*hm64_panel_classes, *hm64_support_classes):
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed((*hm64_panel_classes, *hm64_support_classes)):
        unregister_class(cls)
