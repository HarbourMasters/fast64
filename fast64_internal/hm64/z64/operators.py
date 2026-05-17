"""HM64 XML export helpers and operators."""

import bpy
import os

from bpy.types import Operator
from bpy.ops import object
from bpy.utils import register_class, unregister_class
from mathutils import Matrix

from ...utility import PluginError, ExportUtils, raisePluginError, toAlnum
from ..utility import writeXMLData
from ...f3d.f3d_gbi import DLFormat
from ...f3d.f3d_writer import TriangleConverterInfo, saveStaticModel, getInfoDict
from ...z64.utility import getOOTScale, checkEmptyName
from ...z64.model_classes import OOTModel
from ...z64.f3d_writer import writeTextureArraysExisting
from .properties import LIMB_MATRIX_PATHS

from ...z64.utility import (
    OOTObjectCategorizer,
    ootDuplicateHierarchy,
    ootCleanupScene,
    get_internal_asset_path,
)


def build_extra_xml_entries(entries) -> str:
    xml_lines: list[str] = []
    for entry in entries:
        matrix_path = LIMB_MATRIX_PATHS.get(entry.limb, "")
        if matrix_path:
            xml_lines.append(f'\t<Matrix Path="{matrix_path}" Param="G_MTX_LOAD"/>')
        call = entry.call_dl.strip()
        if call:
            internal_path = entry.internal_path.strip()
            if internal_path:
                prefix = internal_path.rstrip("/")
                if prefix:
                    if not (call.startswith(prefix + "/") or call == prefix):
                        call = call.lstrip("/")
                        call = f"{prefix}/{call}" if call else prefix
            xml_lines.append(f'\t<CallDisplayList Path="{call}"/>')
    if not xml_lines:
        return ""
    return "\n".join(xml_lines) + "\n"


def get_active_matrix_entries(obj: bpy.types.Object, settings: "OOTDLExportSettings"):
    if obj is not None and hasattr(obj, "oot_matrix_calls") and len(obj.oot_matrix_calls) > 0:
        return obj.oot_matrix_calls
    return []


def resolve_custom_export_base(settings: "OOTDLExportSettings") -> str:
    custom_path = (settings.customPath or "").strip()
    if not custom_path:
        raise PluginError("Export path is empty.")
    base_path = bpy.path.abspath(custom_path)
    if not os.path.exists(base_path):
        os.makedirs(base_path, exist_ok=True)
    return base_path


def resolve_custom_export_folder(base_path: str, folder_name: str) -> str:
    folder_path = os.path.join(base_path, folder_name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
    return folder_path


def resolve_dl_export_name(originalObj: bpy.types.Object, settings: "OOTDLExportSettings") -> str:
    if settings.useCustomDLName:
        custom_name = (settings.customDLName or "").strip()
        checkEmptyName(custom_name)
        name = toAlnum(custom_name)
        checkEmptyName(name)
        return name

    return toAlnum(originalObj.name)


def ootConvertMeshToXML(
    originalObj: bpy.types.Object,
    finalTransform,
    DLFormat: DLFormat,
    savePNG: bool,
    settings: "OOTDLExportSettings",
):
    folderName = settings.folder
    exportPath = resolve_custom_export_base(settings)
    isCustomExport = settings.isCustom
    name = resolve_dl_export_name(originalObj, settings)
    overlayName = settings.actorOverlayName
    flipbookUses2DArray = settings.flipbookUses2DArray
    flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None
    matrix_entries = list(get_active_matrix_entries(originalObj, settings))

    try:
        obj, allObjs = ootDuplicateHierarchy(originalObj, None, False, OOTObjectCategorizer())

        fModel = OOTModel(name, DLFormat, None)
        triConverterInfo = TriangleConverterInfo(obj, None, fModel.f3d, finalTransform, getInfoDict(obj))
        fMeshes = saveStaticModel(
            triConverterInfo, fModel, obj, finalTransform, fModel.name, not savePNG, False, "oot"
        )

        for fMesh in fMeshes.values():
            fMesh.draw.name = name

        ootCleanupScene(originalObj, allObjs)

    except Exception as e:
        ootCleanupScene(originalObj, allObjs)
        raise Exception(str(e))

    path = resolve_custom_export_folder(exportPath, folderName)
    includeDir = get_internal_asset_path(settings, folderName)
    exportData = fModel.to_xml(path, includeDir, include_cull_vertices=False, combine_root_meshes=True)
    extra_entries = matrix_entries
    extra_xml = build_extra_xml_entries(extra_entries)
    if extra_xml:
        display_start = exportData.find("\n")
        if display_start != -1:
            insert_point = display_start + 1
            exportData = exportData[:insert_point] + extra_xml + exportData[insert_point:]
        else:
            exportData = extra_xml + exportData

    writeXMLData(exportData, os.path.join(path, name))

    if not isCustomExport:
        writeTextureArraysExisting(bpy.context.scene.ootDecompPath, overlayName, False, flipbookArrayIndex2D, fModel)


class HM64_ExportDLOperator(Operator):
    bl_idname = "object.hm64_export_dl_xml"
    bl_label = "Export DL (XML)"
    bl_options = {"REGISTER", "UNDO", "PRESET"}

    def execute(self, context):
        with ExportUtils() as export_utils:
            if context.mode != "OBJECT":
                object.mode_set(mode="OBJECT")
            if len(context.selected_objects) == 0:
                raise PluginError("Mesh not selected.")
            obj = context.active_object
            if obj.type != "MESH":
                raise PluginError("Mesh not selected.")

            finalTransform = Matrix.Scale(getOOTScale(obj.ootActorScale), 4)

            try:
                saveTextures = context.scene.saveTextures
                exportSettings = context.scene.fast64.oot.DLExportSettings

                ootConvertMeshToXML(
                    obj,
                    finalTransform,
                    DLFormat.Static,
                    saveTextures,
                    exportSettings,
                )

                self.report({"INFO"}, "XML export success!")
                return {"FINISHED"}

            except Exception as e:
                if context.mode != "OBJECT":
                    object.mode_set(mode="OBJECT")
                raisePluginError(self, e)
                return {"CANCELLED"}


hm64_z64_operator_classes = (
    HM64_ExportDLOperator,
)


def register():
    for cls in hm64_z64_operator_classes:
        register_class(cls)


def unregister():
    for cls in reversed(hm64_z64_operator_classes):
        unregister_class(cls)
