"""HM64 MM panels and matrix-call support classes extracted from z64/f3d/panels.py."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Object, Mesh, Operator, UIList

from ..utility import is_hm64
from ...z64.f3d.properties import OOTDLExportSettings
from .properties import OOTDLMatrixCallPair


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
        return is_hm64() and context.object is not None and isinstance(context.object.data, Mesh)

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
        return is_hm64() and obj is not None and isinstance(obj.data, Mesh) and len(obj.oot_matrix_calls) > 0

    def execute(self, context):
        obj = context.object
        index = obj.oot_matrix_calls_index
        obj.oot_matrix_calls.remove(index)
        obj.oot_matrix_calls_index = max(0, min(index, len(obj.oot_matrix_calls) - 1))
        return {"FINISHED"}


hm64_panel_classes = ()

hm64_support_classes = (
    OOTDLMatrixCallPair,
    OOT_UL_MatrixCallPairs,
    FAST64_OT_AddObjectMatrixCall,
    FAST64_OT_RemoveObjectMatrixCall,
)


def register():
    from bpy.utils import register_class

    for cls in (*hm64_panel_classes, *hm64_support_classes):
        register_class(cls)
    Object.oot_matrix_calls = CollectionProperty(type=OOTDLMatrixCallPair)
    Object.oot_matrix_calls_index = IntProperty(default=0)
    Object.hm64_dl_jumper_enabled = BoolProperty(
        name="DL Jumper",
        description="Replaces EndDisplayList with JumpToDisplayList branching off to another displaylist of your choice",
        default=False,
    )
    Object.hm64_dl_jumper_internal_path = StringProperty(
        name="Internal Path",
        default="",
        description="Location of the target displaylist",
    )
    Object.hm64_dl_jumper_dl_name = StringProperty(
        name="DL Name",
        default="",
        description="Name of the target displaylist",
    )


def unregister():
    from bpy.utils import unregister_class

    del Object.oot_matrix_calls
    del Object.oot_matrix_calls_index
    del Object.hm64_dl_jumper_enabled
    del Object.hm64_dl_jumper_internal_path
    del Object.hm64_dl_jumper_dl_name
    for cls in reversed((*hm64_panel_classes, *hm64_support_classes)):
        unregister_class(cls)
