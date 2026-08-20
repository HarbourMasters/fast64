import bpy

from bpy.types import Mesh, UILayout

from ...utility import prop_split


def draw_hm64_dl_export_props(settings, layout: UILayout):
    layout.prop(settings, "useCustomDLName")
    if settings.useCustomDLName:
        prop_split(layout, settings, "customDLName", "DL Name")

    prop_split(layout, settings, "folder", "Internal Path")
    prop_split(layout, settings, "customPath", "Path")
    prop_split(layout, settings, "actorOverlayName", "Overlay (Optional)")
    layout.prop(settings, "hm64_optimize_material_writes")

    obj = getattr(bpy.context, "object", None)
    if obj is None or not isinstance(obj.data, Mesh) or not hasattr(obj, "oot_matrix_calls"):
        return

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

    if len(obj.oot_matrix_calls) == 0:
        return

    index = max(0, min(obj.oot_matrix_calls_index, len(obj.oot_matrix_calls) - 1))
    active = obj.oot_matrix_calls[index]
    matrix_box.prop(active, "limb")
    matrix_box.prop(active, "internal_path", text="Internal Path")
    matrix_box.prop(active, "call_dl", text="Call Display List")
