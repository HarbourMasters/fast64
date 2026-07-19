"""HM64-specific z64 skeleton integration hooks."""

import bpy

from contextlib import contextmanager
from types import SimpleNamespace
from bpy.props import EnumProperty
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from ..utility import hm64_mm_features_enabled, is_hm64
from ...data.z64.data import mm_skeleton_dict
from ...game_data import game_data
from ...z64 import OOT_Properties
from ...z64.skeleton import operators as shared_skeleton_operators
from ...z64.skeleton.properties import OOTSkeletonExportSettings
from ...z64.skeleton.importer import functions as shared_skeleton_importer
from ...z64.skeleton.importer.functions import ootImportSkeletonC as shared_import_skeleton
from ...z64.exporter.skeleton.functions import ootConvertArmatureToC as shared_export_skeleton
from ..mm.skeleton import mm_importer as hm64_mm_importer
from ..mm.skeleton.mm_importer import ootImportSkeletonC as mm_import_skeleton
from ..mm.skeleton.functions import ootConvertArmatureToO2R as mm_export_skeleton
from .skeleton_xml import ootConvertArmatureToXML as oot_xml_export_skeleton
from ..f3d.f3d_gbi_hm64 import register as ensure_hm64_f3d_gbi
from ..f3d.f3d_texture_writer_hm64 import register as ensure_hm64_texture_writer


MM_SKELETON_MODE_ITEMS = [("Generic", "Generic", "Generic")] + [(name, name, name) for name in mm_skeleton_dict.keys()]

_original_export_draw_props = OOTSkeletonExportSettings.draw_props


DEFAULT_MM_SKELETON_MODE = "Generic"


HM64_MM_SKELETON_MODE_KEY = "hm64_mm_skeleton_export_mode"


def get_hm64_mm_skeleton_mode_items(_self=None, _context=None):
    return MM_SKELETON_MODE_ITEMS


class FAST64_OT_SetHM64MMSkeletonExportMode(Operator):
    bl_idname = "fast64.hm64_set_mm_skeleton_export_mode"
    bl_label = "Set HM64 MM Skeleton Export Mode"
    bl_options = {"INTERNAL"}

    mode: EnumProperty(items=get_hm64_mm_skeleton_mode_items, default=DEFAULT_MM_SKELETON_MODE)

    def execute(self, context):
        context.scene[HM64_MM_SKELETON_MODE_KEY] = self.mode
        return {"FINISHED"}


def get_hm64_mm_export_mode(scene=None) -> str:
    scene = scene or bpy.context.scene
    return scene.get(HM64_MM_SKELETON_MODE_KEY, DEFAULT_MM_SKELETON_MODE)


def clear_hm64_mm_export_mode(scene=None):
    scene = scene or bpy.context.scene
    if HM64_MM_SKELETON_MODE_KEY in scene:
        del scene[HM64_MM_SKELETON_MODE_KEY]


def _override_mode(settings, mode_value: str):
    data = {key: getattr(settings, key) for key in settings.__class__.__annotations__.keys()}
    data["mode"] = mode_value
    return SimpleNamespace(**data)


@contextmanager
def _using_mm_game_data():
    previous_game = game_data.z64.game
    original_get_extracted_path = OOT_Properties.get_extracted_path

    def _hm64_mm_get_extracted_path(self):
        version = self.mm_version
        if version == "legacy":
            return "."
        return f"extracted/{version if version != 'Custom' else self.oot_version_custom}"

    OOT_Properties.get_extracted_path = _hm64_mm_get_extracted_path
    game_data.z64.update(None, "MM", True)
    try:
        yield
    finally:
        OOT_Properties.get_extracted_path = original_get_extracted_path
        game_data.z64.update(None, previous_game, True)


@contextmanager
def _disable_lod_imports(importer_module):
    original_build_skeleton = importer_module.ootBuildSkeleton

    def _hm64_build_skeleton_without_lod(*args, **kwargs):
        _is_lod, armature_obj = original_build_skeleton(*args, **kwargs)
        return False, armature_obj

    importer_module.ootBuildSkeleton = _hm64_build_skeleton_without_lod
    try:
        yield
    finally:
        importer_module.ootBuildSkeleton = original_build_skeleton


def _hm64_export_draw_props(self, layout):
    if is_hm64():
        from .skeleton_properties_ui import draw_hm64_skeleton_export_props

        draw_hm64_skeleton_export_props(self, layout)
        return

    return _original_export_draw_props(self, layout)


def hm64_import_skeleton(base_path: str, import_settings):
    ensure_hm64_f3d_gbi()
    ensure_hm64_texture_writer()
    if hm64_mm_features_enabled():
        with _using_mm_game_data():
            with _disable_lod_imports(hm64_mm_importer):
                return mm_import_skeleton(base_path, import_settings)
    with _disable_lod_imports(shared_skeleton_importer):
        return shared_import_skeleton(base_path, import_settings)


def hm64_export_skeleton(armature_obj, final_transform, dl_format, save_textures, draw_layer, export_settings):
    ensure_hm64_f3d_gbi()
    ensure_hm64_texture_writer()
    if is_hm64():
        if hm64_mm_features_enabled():
            mode_value = get_hm64_mm_export_mode()
            with _using_mm_game_data():
                return mm_export_skeleton(
                    armature_obj,
                    final_transform,
                    dl_format,
                    save_textures,
                    draw_layer,
                    _override_mode(export_settings, mode_value),
                )
        return oot_xml_export_skeleton(
            armature_obj, final_transform, dl_format, save_textures, draw_layer, export_settings
        )
    return shared_export_skeleton(armature_obj, final_transform, dl_format, save_textures, draw_layer, export_settings)


def register():
    register_class(FAST64_OT_SetHM64MMSkeletonExportMode)
    OOTSkeletonExportSettings.draw_props = _hm64_export_draw_props
    shared_skeleton_operators.ootImportSkeletonC = hm64_import_skeleton
    shared_skeleton_operators.ootConvertArmatureToC = hm64_export_skeleton


def unregister():
    shared_skeleton_operators.ootImportSkeletonC = shared_import_skeleton
    shared_skeleton_operators.ootConvertArmatureToC = shared_export_skeleton
    OOTSkeletonExportSettings.draw_props = _original_export_draw_props
    clear_hm64_mm_export_mode()
    unregister_class(FAST64_OT_SetHM64MMSkeletonExportMode)
