import bpy
from bpy.types import Panel, Mesh, Armature, Operator, UIList
from bpy.utils import register_class, unregister_class
from ...panels import MM_Panel, OOT_Panel
from ...utility import prop_split
from .operators import OOT_ImportDL, OOT_ExportDL
from .properties import (
    OOTDLExportSettings,
    OOTDLImportSettings,
    OOTDynamicMaterialProperty,
    OOTDefaultRenderModesProperty,
)


class OOT_UL_MatrixCallPairs(UIList):
    bl_idname = "OOT_UL_matrix_call_pairs"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        label = item.matrix_path if item.matrix_path else "No matrix"
        row = layout.row(align=True)
        row.label(text=label, icon="MESH_TORUS")


class FAST64_OT_AddMatrixCall(Operator):
    bl_idname = "fast64.oot_add_matrix_call"
    bl_label = "Add Matrix Call"
    bl_description = "Add a new matrix-call pair to the list"

    def execute(self, context):
        settings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        entry = settings.extra_matrix_calls.add()
        settings.extra_matrix_calls_index = len(settings.extra_matrix_calls) - 1
        entry.limb = "none"
        entry.call_dl = ""
        entry.internal_path = settings.folder
        return {"FINISHED"}


class FAST64_OT_RemoveMatrixCall(Operator):
    bl_idname = "fast64.oot_remove_matrix_call"
    bl_label = "Remove Matrix Call"
    bl_description = "Remove the selected matrix-call pair"

    @classmethod
    def poll(cls, context):
        settings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        return len(settings.extra_matrix_calls) > 0

    def execute(self, context):
        settings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        index = settings.extra_matrix_calls_index
        settings.extra_matrix_calls.remove(index)
        settings.extra_matrix_calls_index = max(0, min(index, len(settings.extra_matrix_calls) - 1))
        return {"FINISHED"}


class OOT_DisplayListPanel(Panel):
    bl_label = "Display List Inspector"
    bl_idname = "OBJECT_PT_OOT_DL_Inspector"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode == "OOT" and (
            context.object is not None and isinstance(context.object.data, Mesh)
        )

    def draw(self, context):
        box = self.layout.box().column()
        box.box().label(text="OOT DL Inspector")
        obj = context.object

        # prop_split(box, obj, "ootDrawLayer", "Draw Layer")
        box.prop(obj, "ignore_render")
        box.prop(obj, "ignore_collision")
        if bpy.context.scene.f3d_type == "F3DEX3":
            box.prop(obj, "is_occlusion_planes")
            if obj.is_occlusion_planes and (not obj.ignore_render or not obj.ignore_collision):
                box.label(icon="INFO", text="Suggest Ignore Render & Ignore Collision.")

        if not (obj.parent is not None and isinstance(obj.parent.data, Armature)):
            actorScaleBox = box.box().column()
            prop_split(actorScaleBox, obj, "ootActorScale", "Actor Scale")
            actorScaleBox.label(text="This applies to actor exports only.", icon="INFO")

        # Doesn't work since all static meshes are pre-transformed
        # box.prop(obj.ootDynamicTransform, "billboard")


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
        OOT_DisplayListPanel.draw(self, context)


class OOT_MaterialPanel(Panel):
    bl_label = "OOT Material"
    bl_idname = "MATERIAL_PT_OOT_Material_Inspector"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.material is not None and context.scene.gameEditorMode == "OOT"

    def draw(self, context):
        layout = self.layout
        mat = context.material
        col = layout.column()

        if (
            hasattr(context, "object")
            and context.object is not None
            and context.object.parent is not None
            and isinstance(context.object.parent.data, Armature)
        ):
            drawLayer = context.object.parent.ootDrawLayer
            if drawLayer != mat.f3d_mat.draw_layer.oot:
                col.label(text="Draw layer is being overriden by skeleton.", icon="OUTLINER_DATA_ARMATURE")
        else:
            drawLayer = mat.f3d_mat.draw_layer.oot

        dynMatProps: OOTDynamicMaterialProperty = mat.ootMaterial
        dynMatProps.draw_props(col.box().column(), mat, drawLayer)


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
        OOT_MaterialPanel.draw(self, context)


class OOT_DrawLayersPanel(Panel):
    bl_label = "OOT Draw Layers"
    bl_idname = "WORLD_PT_OOT_Draw_Layers_Panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "world"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode == "OOT"

    def draw(self, context):
        world = context.scene.world
        if not world:
            return
        ootDefaultRenderModeProp: OOTDefaultRenderModesProperty = world.ootDefaultRenderModes
        ootDefaultRenderModeProp.draw_props(self.layout)


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
        OOT_DrawLayersPanel.draw(self, context)


class OOT_ExportDLPanel(OOT_Panel):
    bl_idname = "Z64_PT_export_dl"
    bl_label = "DL Exporter"

    # called every frame
    def draw(self, context):
        col = self.layout.column()

        col.operator(OOT_ExportDL.bl_idname)
        exportSettings: OOTDLExportSettings = context.scene.fast64.oot.DLExportSettings
        exportSettings.draw_props(col)

        col.operator(OOT_ImportDL.bl_idname)
        importSettings: OOTDLImportSettings = context.scene.fast64.oot.DLImportSettings
        importSettings.draw_props(col)


class MM_ExportDLPanel(MM_Panel):
    bl_idname = "Z64_PT_export_dl_mm"
    bl_label = "DL Exporter"

    def draw(self, context):
        OOT_ExportDLPanel.draw(self, context)


oot_dl_writer_panel_classes = (
    OOT_DisplayListPanel,
    OOT_MaterialPanel,
    OOT_DrawLayersPanel,
    OOT_ExportDLPanel,
    MM_DisplayListPanel,
    MM_MaterialPanel,
    MM_DrawLayersPanel,
    MM_ExportDLPanel,
)

oot_dl_writer_support_classes = (
    OOT_UL_MatrixCallPairs,
    FAST64_OT_AddMatrixCall,
    FAST64_OT_RemoveMatrixCall,
)


def f3d_panels_register():
    for cls in (*oot_dl_writer_panel_classes, *oot_dl_writer_support_classes):
        register_class(cls)


def f3d_panels_unregister():
    for cls in reversed((*oot_dl_writer_panel_classes, *oot_dl_writer_support_classes)):
        unregister_class(cls)
