from bpy.types import UILayout

from ...utility import prop_split


def _draw_mode_prop(layout: UILayout, mode_prop_owner, mode_prop_name: str, fallback_settings):
    split = layout.split(factor=0.5)
    split.label(text="Mode")
    if hasattr(mode_prop_owner, mode_prop_name):
        split.prop(mode_prop_owner, mode_prop_name, text="")
        return getattr(mode_prop_owner, mode_prop_name, "Generic")
    split.prop(fallback_settings, "mode", text="")
    return getattr(fallback_settings, "mode", "Generic")


def draw_hm64_skeleton_export_props(settings, layout: UILayout):
    prop_split(layout, settings, "folder", "Internal Path")
    prop_split(layout, settings, "customPath", "Path")
    layout.prop(settings, "hm64_optimize_skeleton_material_writes")


def _draw_mode_menu(layout: UILayout, current_mode: str):
    split = layout.split(factor=0.5)
    split.label(text="Mode")
    split.operator_menu_enum("fast64.hm64_set_mm_skeleton_export_mode", "mode", text=current_mode)
    return current_mode


def draw_hm64_mm_skeleton_export_props(settings, layout: UILayout, current_mode: str):
    layout.prop(settings, "removeVanillaData")
    layout.prop(settings, "hm64_optimize_skeleton_material_writes", text="Optimize + Inline Skeleton Materials")
    if settings.hm64_optimize_skeleton_material_writes:
        box = layout.box().column()
        box.label(icon="LIBRARY_DATA_BROKEN", text="Do not draw anything in SkelAnime")
        box.label(text="callbacks or cull limbs, will be corrupted.")
    layout.prop(settings, "isCustom")
    layout.label(text="Object name used for export.", icon="INFO")
    layout.prop(settings, "isCustomFilename")
    if settings.isCustomFilename:
        prop_split(layout, settings, "filename", "Filename")
    if settings.isCustom:
        prop_split(layout, settings, "folder", "Folder")
        prop_split(layout, settings, "customAssetIncludeDir", "Asset Include Path")
        prop_split(layout, settings, "customPath", "Path")
    else:
        mode_value = _draw_mode_menu(layout, current_mode)
        if mode_value == "Generic":
            prop_split(layout, settings, "folder", "Object")
            prop_split(layout, settings, "actorOverlayName", "Overlay")
            layout.prop(settings, "flipbookUses2DArray")
            if settings.flipbookUses2DArray:
                box = layout.box().column()
                prop_split(box, settings, "flipbookArrayIndex2D", "Flipbook Index")


def draw_hm64_mm_skeleton_import_props(settings, layout: UILayout, mode_prop_owner, mode_prop_name: str):
    prop_split(layout, settings, "drawLayer", "Import Draw Layer")
    layout.prop(settings, "removeDoubles")
    layout.prop(settings, "importNormals")
    layout.prop(settings, "import_animations")
    layout.prop(settings, "isCustom")
    if settings.isCustom:
        prop_split(layout, settings, "name", "Skeleton")
        prop_split(layout, settings, "customPath", "File")
        prop_split(layout, settings, "actorScale", "Actor Scale")
    else:
        mode_value = _draw_mode_prop(layout, mode_prop_owner, mode_prop_name, settings)
        if mode_value == "Generic":
            prop_split(layout, settings, "name", "Skeleton")
            prop_split(layout, settings, "folder", "Object")
            prop_split(layout, settings, "actorOverlayName", "Overlay")
            layout.prop(settings, "autoDetectActorScale")
            if not settings.autoDetectActorScale:
                prop_split(layout, settings, "actorScale", "Actor Scale")
            layout.prop(settings, "flipbookUses2DArray")
            if settings.flipbookUses2DArray:
                box = layout.box().column()
                prop_split(box, settings, "flipbookArrayIndex2D", "Flipbook Index")
        else:
            layout.prop(settings, "applyRestPose")
