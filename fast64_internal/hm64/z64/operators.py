"""HM64 XML export helpers extracted from z64/f3d/operators.py."""

import bpy
import os

from ...utility import PluginError, toAlnum
from ..utility import writeXMLData
from ...f3d import f3d_gbi
from ...f3d.f3d_gbi import DLFormat, SPClearGeometryMode, SPSetGeometryMode
from ..f3d.hm64_f3d_writer import TriangleConverterInfo, saveStaticModel, getInfoDict
from ..f3d.soh_xml_exporter import register as ensure_hm64_soh_xml
from ..f3d.f3d_texture_writer_hm64 import register as ensure_hm64_texture_writer
from ...z64.utility import getOOTScale, checkEmptyName
from ...z64.model_classes import OOTModel
from ...z64.f3d_writer import writeTextureArraysExisting
from .properties import LIMB_MATRIX_PATHS

from ...z64.utility import (
    OOTObjectCategorizer,
    ootDuplicateHierarchy,
    ootCleanupScene,
)
from ..utility import get_internal_asset_path


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


def strip_hm64_xml_cull_preamble(fMesh):
    commands = fMesh.draw.commands
    if len(commands) < 4:
        return

    if (
        isinstance(commands[0], SPClearGeometryMode)
        and set(commands[0].flagList) == {"G_LIGHTING"}
        and isinstance(commands[2], SPSetGeometryMode)
        and set(commands[2].flagList) == {"G_LIGHTING"}
    ):
        del commands[:4]


def ootConvertMeshToXML(
    originalObj: bpy.types.Object,
    finalTransform,
    DLFormat: DLFormat,
    savePNG: bool,
    settings: "OOTDLExportSettings",
):
    folderName = settings.folder
    exportPath = resolve_custom_export_base(settings)
    isCustomExport = True
    name = resolve_dl_export_name(originalObj, settings)
    overlayName = settings.actorOverlayName
    flipbookUses2DArray = settings.flipbookUses2DArray
    flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None
    matrix_entries = list(get_active_matrix_entries(originalObj, settings))

    try:
        obj, allObjs = ootDuplicateHierarchy(originalObj, None, False, OOTObjectCategorizer())

        fModel = OOTModel(name, DLFormat, None)
        triConverterInfo = TriangleConverterInfo(obj, None, fModel.f3d, finalTransform, getInfoDict(obj))
        original_get_fmesh_name = f3d_gbi.getFMeshName
        f3d_gbi.getFMeshName = lambda vertexGroup, namePrefix, drawLayer, isSkinned: (
            toAlnum(namePrefix + ("_" if namePrefix != "" else "") + vertexGroup)
            + ("_skinned" if isSkinned else "")
            + (f"_layer_{drawLayer}" if drawLayer is not None else "")
        )
        try:
            fMeshes = saveStaticModel(triConverterInfo, fModel, obj, finalTransform, "", not savePNG, False, None)
        finally:
            f3d_gbi.getFMeshName = original_get_fmesh_name

        for fMesh in fMeshes.values():
            strip_hm64_xml_cull_preamble(fMesh)
            fMesh.draw.name = name

        ootCleanupScene(originalObj, allObjs)

    except Exception as e:
        ootCleanupScene(originalObj, allObjs)
        raise Exception(str(e))

    path = resolve_custom_export_folder(exportPath, folderName)
    includeDir = get_internal_asset_path(settings, folderName)
    ensure_hm64_soh_xml()
    ensure_hm64_texture_writer()
    exportData = fModel.to_soh_xml(path, includeDir, include_cull_vertices=False, combine_root_meshes=True)
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
