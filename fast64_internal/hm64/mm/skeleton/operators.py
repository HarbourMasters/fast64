import bpy
from bpy.ops import object
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from bpy.path import abspath
from mathutils import Matrix

from ....f3d.f3d_gbi import DLFormat
from ....z64.skeleton.properties import OOTSkeletonExportSettings, OOTSkeletonImportSettings
from ....z64.utility import getOOTScale
from ....utility import ExportUtils, PluginError, raisePluginError
from .functions import ootConvertArmatureToO2R


class MM_ExportSkeleton(Operator):
    bl_idname = "object.mm_export_skeleton"
    bl_label = "Export MM Skeleton"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    def execute(self, context):
        with ExportUtils() as export_utils:
            armatureObj = None
            if context.mode != "OBJECT":
                object.mode_set(mode="OBJECT")
            if len(context.selected_objects) == 0:
                raise PluginError("Armature not selected.")
            armatureObj = context.active_object
            if armatureObj.type != "ARMATURE":
                raise PluginError("Armature not selected.")

            if len(armatureObj.children) == 0 or not hasattr(armatureObj.children[0], "data"):
                raise PluginError("Armature does not have any mesh children.")

            finalTransform = Matrix.Scale(getOOTScale(armatureObj.ootActorScale), 4)

            object.select_all(action="DESELECT")
            armatureObj.select_set(True)
            object.transform_apply(location=False, rotation=True, scale=True, properties=False)
            object.select_all(action="DESELECT")

            try:
                exportSettings: OOTSkeletonExportSettings = context.scene.fast64.oot.skeletonExportSettings
                saveTextures = context.scene.saveTextures
                drawLayer = armatureObj.ootDrawLayer

                ootConvertArmatureToO2R(
                    armatureObj, finalTransform, DLFormat.Static, saveTextures, drawLayer, exportSettings
                )

                self.report({"INFO"}, "Success!")
                return {"FINISHED"}

            except Exception as e:
                if context.mode != "OBJECT":
                    object.mode_set(mode="OBJECT")
                raisePluginError(self, e)
                return {"CANCELLED"}


class MM_ImportSkeleton(Operator):
    bl_idname = "object.mm_import_skeleton"
    bl_label = "Import MM Skeleton"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    def execute(self, context):
        if context.mode != "OBJECT":
            object.mode_set(mode="OBJECT")

        try:
            from .mm_importer import ootImportSkeletonC

            importSettings: OOTSkeletonImportSettings = context.scene.fast64.oot.skeletonImportSettings
            decompPath = abspath(context.scene.ootDecompPath)

            ootImportSkeletonC(decompPath, importSettings)

            self.report({"INFO"}, "Success!")
            return {"FINISHED"}

        except Exception as e:
            if context.mode != "OBJECT":
                object.mode_set(mode="OBJECT")
            raisePluginError(self, e)
            return {"CANCELLED"}


mm_skeleton_classes = (MM_ExportSkeleton, MM_ImportSkeleton)


def mm_skeleton_ops_register():
    for cls in mm_skeleton_classes:
        register_class(cls)


def mm_skeleton_ops_unregister():
    for cls in reversed(mm_skeleton_classes):
        unregister_class(cls)
