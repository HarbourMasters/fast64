"""HM64 skeleton XML export extracted from z64/exporter/skeleton/functions.py."""

import mathutils
import bpy
import os

from ...f3d.f3d_gbi import DLFormat
from ...z64.model_classes import OOTModel
from ...z64.skeleton.constants import ootSkeletonImportDict
from ...z64.skeleton.properties import OOTSkeletonExportSettings

from ...utility import (
    PluginError,
    toAlnum,
    get_internal_asset_path,
    sanitize_internal_asset_path,
    writeXMLData,
)

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

    exportPath = bpy.path.abspath(settings.customPath)
    isCustomExport = settings.isCustom

    from ...z64.exporter.skeleton.functions import ootConvertArmatureToSkeletonWithMesh

    fModel = OOTModel(skeletonName, DLFormat, drawLayer)
    skeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
        originalArmatureObj, convertTransformMatrix, fModel, skeletonName, not savePNG, drawLayer, False
    )

    if originalArmatureObj.ootSkeleton.LOD is not None:
        lodSkeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
            originalArmatureObj.ootSkeleton.LOD,
            convertTransformMatrix,
            fModel,
            skeletonName + "_lod",
            not savePNG,
            drawLayer,
            False,
        )
    else:
        lodSkeleton = None

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
            writeTextureArraysExisting(bpy.context.scene.ootDecompPath, overlayName, isLink, flipbookArrayIndex2D, fModel)
        addIncludeFiles(folderName, path, skeletonName)
