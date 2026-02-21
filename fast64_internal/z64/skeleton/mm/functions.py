import mathutils
import bpy
import os

from pathlib import Path
from ....f3d.mm_f3d_gbi import DLFormat, FMesh, TextureExportSettings, ScrollMethod, get_F3D_GBI
from ....f3d.mm_f3d_writer import getInfoDict
from ... import mm_f3d_writer
from ...model_classes import OOTModel, OOTGfxFormatter
from ....game_data import game_data
from ..properties import OOTSkeletonExportSettings
from ..utility import ootDuplicateArmatureAndRemoveRotations, getGroupIndices, ootRemoveSkeleton
from .classes import OOTLimb, OOTSkeleton
from ...constants import o2rLimbNames

from ....utility import (
    PluginError,
    CData,
    getGroupIndexFromname,
    writeCData,
    toAlnum,
    cleanupDuplicatedObjects,
    crc64,
    get_internal_asset_path,
)

from ...utility import (
    checkEmptyName,
    checkForStartBone,
    getStartBone,
    getSortedChildren,
    ootGetPath,
    addIncludeFiles,
)


def ootProcessBone(
    fModel,
    boneName,
    parentLimb,
    nextIndex,
    meshObj,
    armatureObj,
    convertTransformMatrix,
    meshInfo,
    convertTextureData,
    namePrefix,
    skeletonOnly,
    drawLayer,
    lastMaterialName,
    optimize: bool,
):
    bone = armatureObj.data.bones[boneName]
    if bone.parent is not None:
        transform = convertTransformMatrix @ bone.parent.matrix_local.inverted() @ bone.matrix_local
    else:
        transform = convertTransformMatrix @ bone.matrix_local

    translate, rotate, scale = transform.decompose()

    groupIndex = getGroupIndexFromname(meshObj, boneName)

    meshInfo.vertexGroupInfo.vertexGroupToLimb[groupIndex] = nextIndex

    if skeletonOnly:
        mesh = None
        hasSkinnedFaces = None
    else:
        mesh, hasSkinnedFaces, lastMaterialName = mm_f3d_writer.ootProcessVertexGroup(
            fModel,
            meshObj,
            boneName,
            convertTransformMatrix,
            armatureObj,
            namePrefix,
            meshInfo,
            drawLayer,
            convertTextureData,
            lastMaterialName,
            optimize,
        )

    if bone.ootBone.boneType == "Custom DL":
        if mesh is not None:
            raise PluginError(
                bone.name
                + " is set to use a custom DL but still has geometry assigned to it. Remove this geometry from this bone."
            )
        else:
            # Dummy data, only used so that name is set correctly
            mesh = FMesh(bone.ootBone.customDLName, DLFormat.Static)

    DL = None
    if mesh is not None:
        if not bone.use_deform:
            raise PluginError(
                bone.name
                + " has vertices in its vertex group but is not set to deformable. Make sure to enable deform on this bone."
            )
        DL = mesh.draw

    if isinstance(parentLimb, OOTSkeleton):
        skeleton = parentLimb
        limb = OOTLimb(skeleton.name, boneName, nextIndex, translate, DL, None)
        skeleton.limbRoot = limb
    else:
        limb = OOTLimb(parentLimb.skeletonName, boneName, nextIndex, translate, DL, None)
        parentLimb.children.append(limb)

    limb.isFlex = hasSkinnedFaces
    nextIndex += 1

    # This must be in depth-first order to match the OoT SkelAnime draw code, so
    # the bones are listed in the file in the same order as they are drawn. This
    # is needed to enable the programmer to get the limb indices and to enable
    # optimization between limbs.
    childrenNames = getSortedChildren(armatureObj, bone)
    for childName in childrenNames:
        nextIndex, lastMaterialName = ootProcessBone(
            fModel,
            childName,
            limb,
            nextIndex,
            meshObj,
            armatureObj,
            convertTransformMatrix,
            meshInfo,
            convertTextureData,
            namePrefix,
            skeletonOnly,
            drawLayer,
            lastMaterialName,
            optimize,
        )

    return nextIndex, lastMaterialName


def ootConvertArmatureToSkeleton(
    originalArmatureObj,
    convertTransformMatrix,
    fModel: OOTModel,
    name,
    convertTextureData,
    skeletonOnly,
    drawLayer,
    optimize: bool,
):
    checkEmptyName(name)

    armatureObj, meshObjs = ootDuplicateArmatureAndRemoveRotations(originalArmatureObj)

    try:
        skeleton = OOTSkeleton(name)

        if len(armatureObj.children) == 0:
            raise PluginError("No mesh parented to armature.")

        # startBoneNames = sorted([bone.name for bone in armatureObj.data.bones if bone.parent is None])
        # startBoneName = startBoneNames[0]
        checkForStartBone(armatureObj)
        startBoneName = getStartBone(armatureObj)
        meshObj = meshObjs[0]

        meshInfo = getInfoDict(meshObj)
        getGroupIndices(meshInfo, armatureObj, meshObj, getGroupIndexFromname(meshObj, startBoneName))

        convertTransformMatrix = convertTransformMatrix @ mathutils.Matrix.Diagonal(armatureObj.scale).to_4x4()

        # for i in range(len(startBoneNames)):
        # 	startBoneName = startBoneNames[i]
        ootProcessBone(
            fModel,
            startBoneName,
            skeleton,
            0,
            meshObj,
            armatureObj,
            convertTransformMatrix,
            meshInfo,
            convertTextureData,
            name,
            skeletonOnly,
            drawLayer,
            None,
            optimize,
        )

        cleanupDuplicatedObjects(meshObjs + [armatureObj])
        originalArmatureObj.select_set(True)
        bpy.context.view_layer.objects.active = originalArmatureObj

        return skeleton, fModel
    except Exception as e:
        cleanupDuplicatedObjects(meshObjs + [armatureObj])
        originalArmatureObj.select_set(True)
        bpy.context.view_layer.objects.active = originalArmatureObj
        raise Exception(str(e))


def ootConvertArmatureToSkeletonWithoutMesh(originalArmatureObj, convertTransformMatrix, name):
    # note: only used to export non-Link animation
    skeleton, fModel = ootConvertArmatureToSkeleton(
        originalArmatureObj, convertTransformMatrix, None, name, False, True, "Opaque", False
    )
    return skeleton


def ootConvertArmatureToSkeletonWithMesh(
    originalArmatureObj, convertTransformMatrix, fModel, name, convertTextureData, drawLayer, optimize
):
    return ootConvertArmatureToSkeleton(
        originalArmatureObj, convertTransformMatrix, fModel, name, convertTextureData, False, drawLayer, optimize
    )


def ootConvertArmatureToC(
    originalArmatureObj: bpy.types.Object,
    convertTransformMatrix: mathutils.Matrix,
    DLFormat: DLFormat,
    savePNG: bool,
    drawLayer: str,
    settings: OOTSkeletonExportSettings,
):
    if settings.mode != "Generic" and not settings.isCustom:
        importInfo = game_data.z64.skeleton_dict[settings.mode]
        skeletonName = importInfo.skeletonName
        filename = skeletonName
        folderName = importInfo.folderName
        overlayName = importInfo.actorOverlayName
        flipbookUses2DArray = importInfo.flipbookArrayIndex2D is not None
        flipbookArrayIndex2D = importInfo.flipbookArrayIndex2D
        isLink = importInfo.isLink
    else:
        skeletonName = toAlnum(originalArmatureObj.name)
        filename = settings.filename if settings.isCustomFilename else skeletonName
        folderName = settings.folder
        overlayName = settings.actorOverlayName if not settings.isCustom else None
        flipbookUses2DArray = settings.flipbookUses2DArray
        flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None
        isLink = False

    exportPath = bpy.path.abspath(settings.customPath)
    isCustomExport = settings.isCustom
    removeVanillaData = settings.removeVanillaData
    optimize = settings.optimize

    fModel = OOTModel(skeletonName, DLFormat, drawLayer)
    skeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
        originalArmatureObj, convertTransformMatrix, fModel, skeletonName, not savePNG, drawLayer, optimize
    )

    if originalArmatureObj.ootSkeleton.LOD is not None:
        lodSkeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
            originalArmatureObj.ootSkeleton.LOD,
            convertTransformMatrix,
            fModel,
            skeletonName + "_lod",
            not savePNG,
            drawLayer,
            optimize,
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

    header_filename = Path(filename).parts[-1]
    data = CData()

    data.header = f"#ifndef {header_filename.upper()}_H\n" + f"#define {header_filename.upper()}_H\n\n"

    if bpy.context.scene.fast64.oot.is_globalh_present():
        data.header += '#include "ultra64.h"\n' + '#include "global.h"\n'
    else:
        data.header += '#include "ultra64.h"\n' + '#include "array_count.h"\n' + '#include "z64animation.h"\n'

    data.source = f'#include "{header_filename}.h"\n\n'
    if not isCustomExport:
        data.header += f'#include "{folderName}.h"\n\n'
    else:
        data.header += "\n"

    path = ootGetPath(exportPath, isCustomExport, "assets/objects/", folderName, True, True)
    includeDir = settings.customAssetIncludeDir if settings.isCustom else f"assets/objects/{folderName}"
    exportData = fModel.to_c(
        TextureExportSettings(False, savePNG, includeDir, path), OOTGfxFormatter(ScrollMethod.Vertex)
    )
    skeletonC = skeleton.toC()

    data.append(exportData.all())
    data.append(skeletonC)

    if isCustomExport:
        textureArrayData = mm_f3d_writer.writeTextureArraysNew(fModel, flipbookArrayIndex2D)
        data.append(textureArrayData)

    data.header += "\n#endif\n"
    writeCData(data, os.path.join(path, filename + ".h"), os.path.join(path, filename + ".c"))

    if not isCustomExport:
        mm_f3d_writer.writeTextureArraysExisting(bpy.context.scene.ootDecompPath, overlayName, isLink, flipbookArrayIndex2D, fModel)
        addIncludeFiles(folderName, path, filename)
        if removeVanillaData:
            ootRemoveSkeleton(path, folderName, skeletonName)

def ootConvertArmatureToO2R(
    originalArmatureObj: bpy.types.Object,
    convertTransformMatrix: mathutils.Matrix,
    DLFormat: DLFormat,
    savePNG: bool,
    drawLayer: str,
    settings: OOTSkeletonExportSettings,
):
    if settings.mode != "Generic" and not settings.isCustom:
        importInfo = game_data.z64.skeleton_dict[settings.mode]
        skeletonName = importInfo.skeletonName
        filename = skeletonName
        folderName = importInfo.folderName
        overlayName = importInfo.actorOverlayName
        flipbookUses2DArray = importInfo.flipbookArrayIndex2D is not None
        flipbookArrayIndex2D = importInfo.flipbookArrayIndex2D
        isLink = importInfo.isLink
    else:
        skeletonName = toAlnum(originalArmatureObj.name)
        filename = settings.filename if settings.isCustomFilename else skeletonName
        folderName = settings.folder
        overlayName = settings.actorOverlayName if not settings.isCustom else None
        flipbookUses2DArray = settings.flipbookUses2DArray
        flipbookArrayIndex2D = settings.flipbookArrayIndex2D if flipbookUses2DArray else None
        isLink = False

    exportPath = bpy.path.abspath(settings.customPath)
    isCustomExport = settings.isCustom
    removeVanillaData = settings.removeVanillaData
    optimize = settings.optimize

    fModel = OOTModel(skeletonName, DLFormat, drawLayer)
    skeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
        originalArmatureObj, convertTransformMatrix, fModel, skeletonName, not savePNG, drawLayer, optimize
    )

    if originalArmatureObj.ootSkeleton.LOD is not None:
        lodSkeleton, fModel = ootConvertArmatureToSkeletonWithMesh(
            originalArmatureObj.ootSkeleton.LOD,
            convertTransformMatrix,
            fModel,
            skeletonName + "_lod",
            not savePNG,
            drawLayer,
            optimize,
        )
    else:
        lodSkeleton = None

    limbList = skeleton.createLimbList()

    if lodSkeleton is not None:
        skeleton.hasLOD = True
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

    folderPath = os.path.join("objects", folderName)
    exportFolderPath = os.path.join(exportPath, folderPath)
    if not os.path.exists(exportFolderPath):
        os.makedirs(exportFolderPath)
    objectPath = get_internal_asset_path(settings, folderName)

    # dict[Union[FImageKey, FPaletteKey], FImage]
    for _, fImage in fModel.textures.items():
        if getattr(fImage, "skip_export", False):
            continue
        with open(os.path.join(exportFolderPath, fImage.name), "wb") as f:
            f.write(fImage.toO2R(folderPath))

    # dict[Tuple[bpy.types.Material, str, FAreaData], Tuple[FMaterial, Tuple[int, int]]]
    for _, (fMaterial, _) in fModel.materials.items():
        if fMaterial.material is not None:
            with open(os.path.join(exportFolderPath, fMaterial.material.name), "wb") as f:
                f.write(fMaterial.material.toO2R(folderPath))

        if fMaterial.revert is not None:
            with open(os.path.join(exportFolderPath, fMaterial.revert.name), "wb") as f:
                f.write(fMaterial.revert.toO2R(folderPath))

    for _, (fMaterial, _) in fModel.materials.items():
        if fMaterial is not None:
            fMaterial.to_soh_xml(exportFolderPath, objectPath)

    # dict[str, FMesh]
    for name, mesh in fModel.meshes.items():
        if mesh.draw is not None:
            meshName = mesh.name
            with open(os.path.join(exportFolderPath, meshName), "wb") as f:
                f.write(mesh.draw.toO2R(folderPath))

            for triGroup in mesh.triangleGroups:
                if triGroup.triList is not None:
                    with open(os.path.join(exportFolderPath, triGroup.triList.name), "wb") as f:
                        f.write(triGroup.triList.toO2R(folderPath))

                if triGroup.vertexList is not None:
                    vertexListName = triGroup.vertexList.name
                    with open(os.path.join(exportFolderPath, vertexListName), "wb") as f:
                        f.write(triGroup.vertexList.toO2R(folderPath))

    with open(os.path.join(exportFolderPath, filename), "wb") as f:
        f.write(skeleton.toO2R(folderPath))

    for limb in limbList:
        with open(os.path.join(exportFolderPath, limb.o2rName()), "wb") as f:
            f.write(limb.toO2R(folderPath))

        if limb.DL is not None:
            with open(os.path.join(exportFolderPath, limb.DL.name), "wb") as f:
                f.write(limb.DL.toO2R(folderPath))
