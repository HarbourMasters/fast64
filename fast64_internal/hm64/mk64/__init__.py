import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.utils import register_class, unregister_class

from .mk64_operators import MK64_ExportCourse
from .mk64_panels import MK64_CurvePanel, MK64_ExportCoursePanel, MK64_ObjectPanel
from .mk64_constants import enum_clip_types, enum_draw_layer_types, enum_path_type, enum_surface_types
from .mk64_properties import featureSetEnum, featureSetUpdate

_REGISTERED = False
_REGISTERED_CLASSES = []
_HM64_MK64_FEATURE_SET_PROP = "hm64_mk64_feature_set"
_HM64_MK64_EXPORT_NAME_PROP = "hm64_mk64_export_name"
_HM64_MK64_EXPORT_PATH_PROP = "hm64_mk64_export_path"
_HM64_MK64_RENDER_MODE_PROP = "hm64_mk64_enable_render_mode_default"
_HM64_MK64_OBJECT_TYPE_PROP = "hm64_mk64_obj_type"
_HM64_MK64_SURFACE_TYPE_PROP = "hm64_mk64_surface_type"
_HM64_MK64_SECTION_ID_PROP = "hm64_mk64_section_id"
_HM64_MK64_CLIP_TYPE_PROP = "hm64_mk64_clip_type"
_HM64_MK64_DRAW_LAYER_PROP = "hm64_mk64_draw_layer"
_HM64_MK64_PATH_TYPE_PROP = "hm64_mk64_path_type"

_HM64_MK64_CLASSES = (
    MK64_ExportCourse,
    MK64_ExportCoursePanel,
    MK64_ObjectPanel,
    MK64_CurvePanel,
)


def register():
    global _REGISTERED, _REGISTERED_CLASSES
    if _REGISTERED:
        return

    _REGISTERED_CLASSES = []
    for cls in _HM64_MK64_CLASSES:
        try:
            register_class(cls)
            _REGISTERED_CLASSES.append(cls)
        except RuntimeError:
            pass

    bpy.types.Scene.hm64_mk64_feature_set = EnumProperty(
        name="Feature Set",
        default="HM64",
        items=featureSetEnum,
        update=featureSetUpdate,
    )
    bpy.types.Scene.hm64_mk64_export_name = StringProperty(name="Name")
    bpy.types.Scene.hm64_mk64_export_path = StringProperty(name="Directory", subtype="FILE_PATH")
    bpy.types.Scene.hm64_mk64_enable_render_mode_default = BoolProperty(
        name="Set Render Mode by Default",
        default=True,
    )

    bpy.types.Object.hm64_mk64_obj_type = EnumProperty(
        name="Object Type",
        items=(("Track Root", "Track Root", "Track Root"), ("Actor", "Actor", "Actor")),
    )
    bpy.types.Object.hm64_mk64_surface_type = EnumProperty(
        name="Collision Type",
        items=enum_surface_types,
        default="SURFACE_DEFAULT",
    )
    bpy.types.Object.hm64_mk64_section_id = IntProperty(name="section_id", default=255, min=0, max=255)
    bpy.types.Object.hm64_mk64_clip_type = EnumProperty(
        name="clip_type",
        items=enum_clip_types,
        default="CLIP_DEFAULT",
    )
    bpy.types.Object.hm64_mk64_draw_layer = EnumProperty(
        name="draw_layer",
        items=enum_draw_layer_types,
        default="DRAW_OPAQUE",
    )
    bpy.types.Object.hm64_mk64_path_type = EnumProperty(
        name="Path Type",
        items=enum_path_type,
        default="TRACK_PATH_1",
    )
    _REGISTERED = True


def unregister():
    global _REGISTERED, _REGISTERED_CLASSES
    if not _REGISTERED:
        return

    for owner, attr in (
        (bpy.types.Object, _HM64_MK64_PATH_TYPE_PROP),
        (bpy.types.Object, _HM64_MK64_DRAW_LAYER_PROP),
        (bpy.types.Object, _HM64_MK64_CLIP_TYPE_PROP),
        (bpy.types.Object, _HM64_MK64_SECTION_ID_PROP),
        (bpy.types.Object, _HM64_MK64_SURFACE_TYPE_PROP),
        (bpy.types.Object, _HM64_MK64_OBJECT_TYPE_PROP),
        (bpy.types.Scene, _HM64_MK64_RENDER_MODE_PROP),
        (bpy.types.Scene, _HM64_MK64_EXPORT_PATH_PROP),
        (bpy.types.Scene, _HM64_MK64_EXPORT_NAME_PROP),
        (bpy.types.Scene, _HM64_MK64_FEATURE_SET_PROP),
    ):
        if hasattr(owner, attr):
            delattr(owner, attr)

    for cls in reversed(_REGISTERED_CLASSES):
        try:
            unregister_class(cls)
        except RuntimeError:
            pass

    _REGISTERED_CLASSES = []
    _REGISTERED = False
