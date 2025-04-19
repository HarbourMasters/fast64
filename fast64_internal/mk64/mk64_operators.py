import bpy, mathutils, math
from bpy.types import Operator
from bpy.utils import register_class, unregister_class

from .mk64_model_classes import MK64F3DContext, parse_course_vtx
from .mk64_course import export_course_c
from .mk64_properties import MK64_ImportProperties

from ..f3d.f3d_material import createF3DMat
from ..f3d.f3d_gbi import get_F3D_GBI, DLFormat
from ..f3d.f3d_parser import getImportData, importMeshC
from ..f3d.f3d_writer import getWriteMethodFromEnum, exportF3DtoC
from .f3d.properties import MK64DLExportSettings

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
    bl_label = "Export Course"

    def execute(self, context):
        mk64_props: MK64_Properties = context.scene.fast64.mk64
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            all_objs = context.selected_objects
            if len(all_objs) == 0:
                raise PluginError("No objects selected.")
            obj = context.selected_objects[0]
            root = obj
            if not root.fast64.mk64.obj_type == "Course Root":
                while root.parent:
                    root = root.parent
                    if root.fast64.mk64.obj_type == "Course Root":
                        break
            assert root.fast64.mk64.obj_type == "Course Root", PluginError("Object must be a course root")

            scale = mk64_props.scale
            final_transform = mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4()

        except Exception as e:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            raisePluginError(self, e)
            return {"CANCELLED"}  # must return a set

        finalTransform = 1

        try:
            applyRotation([root], math.radians(90), "X")

            export_path = bpy.path.abspath(mk64_props.course_export_settings.export_path)

            saveTextures = context.scene.saveTextures
            exportSettings = context.scene.fast64.oot.DLExportSettings

            if context.scene.fast64.mk64.featureSet == "HM64":
                mk64ConvertMeshToXML(obj, finalTransform, DLFormat.Static, saveTextures, exportSettings, self.report)
            else:
                export_course_c(root, context, export_path)

            self.report({"INFO"}, "Success!")
            applyRotation([root], math.radians(-90), "X")
            return {"FINISHED"}  # must return a set

        except Exception as e:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            applyRotation([root], math.radians(-90), "X")

            raisePluginError(self, e)
            return {"CANCELLED"}  # must return a set


def mk64ConvertMeshToXML(
    originalObj: bpy.types.Object,
    finalTransform: mathutils.Matrix,
    DLFormat: DLFormat,
    saveTextures: bool,
    settings: MK64DLExportSettings,
    logging_func,
):
    logging_func({"INFO"}, "mk64ConvertMeshToXML 1")

    folderName = settings.folder
    exportPath = bpy.path.abspath(settings.customPath)
    isCustomExport = settings.isCustom
    drawLayer = settings.drawLayer
    removeVanillaData = settings.removeVanillaData
    name = toAlnum(originalObj.name)
    overlayName = settings.actorOverlayName
    flipbookUses2DArray = settings.flipbookUses2DArray
    flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None

    logging_func({"INFO"}, "mk64ConvertMeshToXML 2")

    try:
        obj, allObjs = ootDuplicateHierarchy(originalObj, None, False, OOTObjectCategorizer())

        logging_func({"INFO"}, "mk64ConvertMeshToXML 3")

        fModel = OOTModel(name, DLFormat, drawLayer)

        logging_func({"INFO"}, "mk64ConvertMeshToXML 4")

        triConverterInfo = TriangleConverterInfo(obj, None, fModel.f3d, finalTransform, getInfoDict(obj))

        logging_func({"INFO"}, "mk64ConvertMeshToXML 5")

        fMeshes = saveStaticModel(
            triConverterInfo,
            fModel,
            obj,
            finalTransform,
            fModel.name,
            not saveTextures,
            False,
            "mk64",
            logging_func=logging_func,
        )

        logging_func({"INFO"}, "mk64ConvertMeshToXML 6")

        # Since we provide a draw layer override, there should only be one fMesh.
        for drawLayer, fMesh in fMeshes.items():
            fMesh.draw.name = name

        logging_func({"INFO"}, "mk64ConvertMeshToXML 7")

        ootCleanupScene(originalObj, allObjs)

        logging_func({"INFO"}, "mk64ConvertMeshToXML 8")

    except Exception as e:
        ootCleanupScene(originalObj, allObjs)
        raise Exception(str(e))

    logging_func(
        {"INFO"}, "mk64ConvertMeshToXML 9.1 exportPath=" + (str(exportPath) if exportPath is not None else "None")
    )
    logging_func(
        {"INFO"},
        "mk64ConvertMeshToXML 9.2 settings.customAssetIncludeDir="
        + (str(settings.customAssetIncludeDir) if settings.customAssetIncludeDir is not None else "None"),
    )

    path = ootGetPath(exportPath, isCustomExport, "assets/objects/", folderName, False, True)

    logging_func({"INFO"}, "mk64ConvertMeshToXML 10.1 path=" + (str(path) if path is not None else "None"))
    logging_func(
        {"INFO"}, "mk64ConvertMeshToXML 10.2 folderName=" + (str(folderName) if folderName is not None else "None")
    )

    data = fModel.to_xml(exportPath, folderName, logging_func)

    logging_func({"INFO"}, "mk64ConvertMeshToXML 11")

    if isCustomExport:
        textureArrayData = writeTextureArraysNewXML(fModel, flipbookArrayIndex2D)
        data += textureArrayData

    logging_func({"INFO"}, "mk64ConvertMeshToXML 12")


mk64_operator_classes = (MK64_ImportCourseDL, MK64_ExportCourse)


def mk64_operator_register():
    for cls in mk64_operator_classes:
        register_class(cls)


def mk64_operator_unregister():
    for cls in mk64_operator_classes:
        unregister_class(cls)
