import bpy, os, mathutils, math
from bpy.types import Operator
from bpy.utils import register_class, unregister_class

from pathlib import Path
from .mk64_model_classes import MK64F3DContext, parse_course_vtx
from .mk64_course import export_course_c, export_course_xml
from .mk64_properties import MK64_ImportProperties
from .f3d.properties import MK64DLExportSettings

from ..f3d.f3d_material import createF3DMat
from ..f3d.f3d_gbi import get_F3D_GBI, DLFormat
from ..f3d.f3d_parser import getImportData, importMeshC
from ..f3d.f3d_writer import getWriteMethodFromEnum, exportF3DtoC

from ..utility import raisePluginError, applyRotation, toAlnum, PluginError

class MK64_ImportCourseDL(Operator):
    # set bl_ properties
    bl_idname = "scene.fast64_mk64_course_import_dl"
    bl_label = "Import Course DL"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    # Called on demand (i.e. button press, menu item)
    # Can also be called from operator search menu (Spacebar)
    def execute(self, context):
        obj = None
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        try:
            import_settings: MK64_ImportProperties = context.scene.fast64.mk64.course_DL_import_settings
            name = import_settings.name
            import_path = bpy.path.abspath(import_settings.path)
            base_path = bpy.path.abspath(import_settings.base_path)
            scale_value = context.scene.fast64.mk64.scale

            remove_doubles = import_settings.remove_doubles
            import_normals = import_settings.import_normals
            draw_layer = "Opaque"

            paths = [import_path]

            if "course_data" in import_path:
                paths += [import_path.replace("course_data", "course_displaylists.inc")]

            paths += [
                import_path.replace("course_data", "course_textures.linkonly").replace(
                    "course_displaylists.inc", "course_textures.linkonly"
                )
            ]

            data = getImportData(paths)

            material = createF3DMat(None)
            f3d_mat = material.f3d_mat
            f3d_mat.rdp_settings.set_rendermode = import_settings.enable_render_Mode_Default
            f3d_mat.combiner1.A = "TEXEL0"
            f3d_mat.combiner1.B = "0"
            f3d_mat.combiner1.C = "SHADE"
            f3d_mat.combiner1.D = "0"
            f3d_mat.combiner1.A_alpha = "TEXEL0"
            f3d_mat.combiner1.B_alpha = "0"
            f3d_mat.combiner1.C_alpha = "SHADE"
            f3d_mat.combiner1.D_alpha = "0"
            f3d_mat.combiner2.name = ""
            f3d_mat.combiner2.A = "TEXEL0"
            f3d_mat.combiner2.B = "0"
            f3d_mat.combiner2.C = "SHADE"
            f3d_mat.combiner2.D = "0"
            f3d_mat.combiner2.A_alpha = "TEXEL0"
            f3d_mat.combiner2.B_alpha = "0"
            f3d_mat.combiner2.C_alpha = "SHADE"
            f3d_mat.combiner2.D_alpha = "0"

            f3d_context = MK64F3DContext(get_F3D_GBI(), base_path, material)
            if "course_displaylists" in import_path or "course_data" in import_path:
                vertex_path = import_path.replace("course_displaylists.inc", "course_vertices.inc").replace(
                    "course_data", "course_vertices.inc"
                )
                print(vertex_path)
                f3d_context.vertexData["0x4000000"] = parse_course_vtx(vertex_path, f3d_context.f3d)

            importMeshC(
                data,
                name,
                scale_value,
                remove_doubles,
                import_normals,
                draw_layer,
                f3d_context,
            )

            self.report({"INFO"}, "Success!")
            return {"FINISHED"}

        except Exception as e:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            raisePluginError(self, e)
            return {"CANCELLED"}  # must return a set


class MK64_ExportCourse(Operator):
    bl_idname = "scene.mk64_export_course"
    bl_label = "Export Track"

    def execute(self, context):
        mk64_props: MK64_Properties = context.scene.fast64.mk64

        prev_mode = context.mode
        root = None
        rotation_applied = False

        try:
            # -----------------------------
            # Ensure object mode
            # -----------------------------
            if context.object and context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            # -----------------------------
            # Root resolution (can error)
            # -----------------------------
            selected = context.selected_objects
            if not selected:
                raise PluginError("No objects selected.")

            selected_roots = [
                obj for obj in selected
                if obj.type == "EMPTY"
                and obj.fast64.mk64.obj_type == "Course Root"
            ]

            if len(selected_roots) > 1:
                raise PluginError("Multiple Course Roots selected.")

            if selected_roots:
                root = selected_roots[0]
            else:
                course_roots = set()
                for obj in selected:
                    current = obj
                    visited = set()
                    while current and current not in visited:
                        visited.add(current)
                        if (
                            current.type == "EMPTY"
                            and current.fast64.mk64.obj_type == "Course Root"
                        ):
                            course_roots.add(current)
                            break
                        current = current.parent

                if not course_roots:
                    raise PluginError("No Course Root found.")

                if len(course_roots) > 1:
                    raise PluginError(
                        "Multiple Course Roots found. Select one explicitly."
                    )

                root = course_roots.pop()

            # -----------------------------
            # Export work
            # -----------------------------
            applyRotation([root], math.radians(90), "X")
            rotation_applied = True

            name = mk64_props.course_export_settings.name
            export_path = Path(bpy.path.abspath(
                mk64_props.course_export_settings.export_path
            ))

            internal_path = Path("tracks") / name
            (export_path / internal_path).mkdir(parents=True, exist_ok=True)

            if context.scene.fast64.mk64.featureSet == "HM64":
                export_course_xml(root, context, export_path, internal_path.as_posix(), self.report)
            else:
                export_course_c(root, context, export_path)

            self.report({"INFO"}, "Success!")
            return {"FINISHED"}

        except Exception as e:
            raisePluginError(self, e)
            return {"CANCELLED"}

        finally:
            # -----------------------------
            # Guaranteed cleanup
            # -----------------------------
            if rotation_applied and root:
                applyRotation([root], math.radians(-90), "X")

            if context.object and context.mode != prev_mode:
                if not context.object:
                    return

                if prev_mode.startswith("EDIT"):
                    bpy.ops.object.mode_set(mode="EDIT")
                elif prev_mode in {"OBJECT", "POSE", "SCULPT"}:
                    bpy.ops.object.mode_set(mode=prev_mode)



mk64_operator_classes = (MK64_ImportCourseDL, MK64_ExportCourse)


def mk64_operator_register():
    for cls in mk64_operator_classes:
        register_class(cls)


def mk64_operator_unregister():
    for cls in mk64_operator_classes:
        unregister_class(cls)
