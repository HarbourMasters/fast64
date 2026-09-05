"""HM64 skeleton XML export extracted from z64/exporter/skeleton/functions.py."""

import mathutils
import bpy
import os
from contextlib import contextmanager

from ...f3d.f3d_gbi import DLFormat, FModel
from ...z64.model_classes import OOTModel
from ...z64.skeleton.constants import ootSkeletonImportDict
from ...z64.skeleton.properties import OOTSkeletonExportSettings
from ..f3d.hm64_f3d_writer import getInfoDict as hm64_getInfoDict
from . import hm64_z64_f3d_writer
from ..f3d.soh_xml_exporter import register as ensure_hm64_soh_xml
from ..f3d.f3d_texture_writer_hm64 import register as ensure_hm64_texture_writer
from .model_classes_hm64 import clear_hm64_material_state_cache
from .zelda2_hair import get_zelda2_hair_matrix_bones

from ...utility import PluginError, toAlnum
from ..utility import get_internal_asset_path, sanitize_internal_asset_path, writeXMLData

from ...z64.utility import (
    addIncludeFiles,
    ootGetPath,
)

from ...z64.f3d_writer import writeTextureArraysExisting


def _normalize_folder_for_path(
    folderName: str, keep_objects_prefix: bool = False, ensure_objects_prefix: bool = False
) -> str:
    folder_path = sanitize_internal_asset_path(folderName)
    if folder_path.startswith("objects/") and not keep_objects_prefix:
        folder_path = folder_path[len("objects/") :]
    if ensure_objects_prefix and folder_path and not folder_path.startswith("objects/"):
        folder_path = "objects/" + folder_path
    return folder_path


@contextmanager
def _use_hm64_skeleton_material_writer():
    from ...z64.exporter.skeleton import functions as shared_skeleton_functions

    old_get_info_dict = shared_skeleton_functions.getInfoDict
    old_process_vertex_group = shared_skeleton_functions.ootProcessVertexGroup
    shared_skeleton_functions.getInfoDict = hm64_getInfoDict
    shared_skeleton_functions.ootProcessVertexGroup = hm64_z64_f3d_writer.ootProcessVertexGroup
    try:
        yield shared_skeleton_functions
    finally:
        shared_skeleton_functions.getInfoDict = old_get_info_dict
        shared_skeleton_functions.ootProcessVertexGroup = old_process_vertex_group


def ootConvertArmatureToXML(
    originalArmatureObj: bpy.types.Object,
    convertTransformMatrix: mathutils.Matrix,
    DLFormat: DLFormat,
    savePNG: bool,
    drawLayer: str,
    settings: OOTSkeletonExportSettings,
):
    if settings.mode != "Generic":
        importInfo = ootSkeletonImportDict[settings.mode]
        skeletonName = importInfo.skeletonName
        folderName = importInfo.folderName
        overlayName = importInfo.actorOverlayName
        flipbookUses2DArray = importInfo.flipbookArrayIndex2D is not None
        flipbookArrayIndex2D = importInfo.flipbookArrayIndex2D
        isLink = importInfo.isLink
    else:
        skeletonName = toAlnum(originalArmatureObj.name)
        folderName = settings.folder
        overlayName = settings.actorOverlayName
        flipbookUses2DArray = settings.flipbookUses2DArray
        flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None
        isLink = False

    customPath = (settings.customPath or "").strip()
    if not customPath:
        raise PluginError("Export path is empty.")
    exportPath = bpy.path.abspath(customPath)
    if not os.path.exists(exportPath):
        os.makedirs(exportPath, exist_ok=True)
    isCustomExport = True

    fModel = None
    with _use_hm64_skeleton_material_writer() as shared_skeleton_functions:
        ootConvertArmatureToSkeletonWithMesh = shared_skeleton_functions.ootConvertArmatureToSkeletonWithMesh

        ensure_hm64_soh_xml()
        ensure_hm64_texture_writer()

        fModel = OOTModel(skeletonName, DLFormat, drawLayer)
        fModel.skip_skeleton_bones = get_zelda2_hair_matrix_bones(skeletonName)
        hm64_optimize = bool(getattr(settings, "hm64_optimize_skeleton_material_writes", False))
        fModel.hm64_optimize_skeleton_material_writes = hm64_optimize
        fModel.hm64_optimize_material_writes = hm64_optimize
        try:
            skeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
                originalArmatureObj,
                convertTransformMatrix,
                fModel,
                skeletonName,
                not savePNG,
                drawLayer,
                hm64_optimize,
            )

            if originalArmatureObj.ootSkeleton.LOD is not None:
                lodSkeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
                    originalArmatureObj.ootSkeleton.LOD,
                    convertTransformMatrix,
                    fModel,
                    skeletonName + "_lod",
                    not savePNG,
                    drawLayer,
                    hm64_optimize,
                )
            else:
                lodSkeleton = None
        finally:
            if fModel is not None:
                clear_hm64_material_state_cache(fModel)

    if lodSkeleton is not None:
        skeleton.hasLOD = True
        limbList = skeleton.createLimbList()
        lodLimbList = lodSkeleton.createLimbList()

        if len(limbList) != len(lodLimbList):
            raise PluginError(
                originalArmatureObj.name
                + " cannot use "
                + originalArmatureObj.ootSkeleton.LOD.name
                + "as LOD because they do not have the same bone structure."
            )

        for i in range(len(limbList)):
            limbList[i].lodDL = lodLimbList[i].DL
            limbList[i].isFlex |= lodLimbList[i].isFlex

    folder_path_for_export = _normalize_folder_for_path(
        folderName, keep_objects_prefix=isCustomExport, ensure_objects_prefix=isCustomExport
    )
    if not folder_path_for_export:
        folder_path_for_export = sanitize_internal_asset_path(folderName)
    path = ootGetPath(exportPath, isCustomExport, "assets/objects/", folder_path_for_export, False, True)
    includeDir = get_internal_asset_path(settings, folderName)
    fModel.to_soh_xml(path, includeDir)
    skeletonXML = skeleton.toSohXML(path, includeDir)
    writeXMLData(skeletonXML, os.path.join(path, skeletonName))

    if not isCustomExport:
        if not isLink:
            writeTextureArraysExisting(
                bpy.context.scene.ootDecompPath, overlayName, isLink, flipbookArrayIndex2D, fModel
            )
        addIncludeFiles(folderName, path, skeletonName)
