# ------------------------------------------------------------------------
#    Header
# ------------------------------------------------------------------------
from __future__ import annotations

from bpy.utils import register_class, unregister_class

from ...utility import prop_split
from ...panels import MK64_Panel

from .mk64_properties import MK64_ImportProperties
from .mk64_operators import MK64_ImportCourseDL, MK64_ExportCourse


class MK64_ImportCourseDLPanel(MK64_Panel):
    bl_idname = "MK64_PT_import_course_DL"
    bl_label = "MK64 Import Course DL"
    bl_order = 0  # force to front

    # called every frame
    def draw(self, context):
        col = self.layout.column()

        col.operator(MK64_ImportCourseDL.bl_idname)
        course_DL_import_settings: MK64_ImportProperties = context.scene.fast64.mk64.course_DL_import_settings
        course_DL_import_settings.draw_props(col)
        prop_split(col, context.scene.fast64.mk64, "scale", "Scale")

        box = col.box().column()
        box.label(text="All data must be contained within file.")
        box.label(text="The only exception are pngs converted to inc.c.")


class MK64_ExportCoursePanel(MK64_Panel):
    bl_label = "SpaghettiKart Track Export"
    bl_idname = "MK64_PT_export_course"

    def draw(self, context):
        col = self.layout.column()
        col.prop(context.scene, "hm64_mk64_feature_set", text="Feature Set")
        col.scale_y = 1.1  # extra padding

        prop_split(col, context.scene, "hm64_mk64_export_name", "Name")
        prop_split(col, context.scene, "hm64_mk64_export_path", "Mods Path")
        prop_split(col, context.scene.fast64.mk64, "scale", "Scale")

        col.operator(MK64_ExportCourse.bl_idname)


class MK64_ObjectPanel(MK64_Panel):
    bl_label = "MK64 Object Inspector"
    bl_idname = "MK64_PT_object_inspector"
    bl_context = "object"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        box = self.layout.box()
        box.label(text="MK64 Object Properties")
        obj = context.object
        if obj.type == "EMPTY":
            prop_split(box, obj, "hm64_mk64_obj_type", "object type")
        elif obj.type == "MESH":
            self.draw_mesh_props(box, obj)
        elif obj.type == "CURVE":
            self.draw_curve_props(box, obj)

    def draw_mesh_props(self, layout: UILayout, obj):
        prop_split(layout, obj, "hm64_mk64_section_id", "Section ID")
        prop_split(layout, obj, "hm64_mk64_surface_type", "Surface")
        prop_split(layout, obj, "hm64_mk64_clip_type", "Clip")
        prop_split(layout, obj, "hm64_mk64_draw_layer", "Draw Layer")

    def draw_curve_props(self, layout: UILayout, obj):
        prop_split(layout, obj, "hm64_mk64_path_type", "Path Type")


class MK64_CurvePanel(MK64_Panel):
    bl_label = "MK64 Curve Inspector"
    bl_idname = "MK64_PT_curve_inspector"
    bl_context = "object"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        if context.object.type != "CURVE":
            return None
        return context.object.data is not None

    def draw(self, context):
        pass


mk64_panel_classes = (MK64_ImportCourseDLPanel, MK64_ExportCoursePanel, MK64_ObjectPanel, MK64_CurvePanel)


def mk64_panel_register():
    for cls in mk64_panel_classes:
        register_class(cls)


def mk64_panel_unregister():
    for cls in mk64_panel_classes:
        unregister_class(cls)
