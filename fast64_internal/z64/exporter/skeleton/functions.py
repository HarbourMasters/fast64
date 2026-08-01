import mathutils
import bpy
import os

from pathlib import Path
from ....f3d.f3d_gbi import DLFormat, FMesh, TextureExportSettings, ScrollMethod
from ....f3d.f3d_writer import getInfoDict, MeshInfo
from ...f3d_writer import ootProcessVertexGroup, writeTextureArraysNew, writeTextureArraysExisting
from ...model_classes import LimbSkinType, OOTModel, OOTGfxFormatter, OOTVertexGroupInfo, OOTVert
from ...skeleton.constants import ootSkeletonImportDict
from ...skeleton.properties import OOTSkeletonExportSettings
from ...skeleton.utility import (
    ootDuplicateArmatureAndRemoveRotations,
    getGroupIndices,
    ootRemoveSkeleton,
    getRecursiveSortedChildren,
    ootConstructSkeleton,
)

from .classes import OOTBaseLimb, SkinLimb, OOTBaseSkeleton


from ....utility import (
    PluginError,
    CData,
    getGroupIndexFromname,
    writeCData,
    toAlnum,
    cleanupDuplicatedObjects,
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
    fModel: OOTModel,
    boneName: str,
    parentLimb: OOTBaseSkeleton | OOTBaseLimb,  # OOTSkeleton | OOTLimb,
    limbOverride: type[OOTBaseLimb],
    nextIndex: int,
    meshObj: bpy.types.Object,
    armatureObj: bpy.types.Object,
    convertTransformMatrix: mathutils.Matrix,
    meshInfo: MeshInfo,
    convertTextureData: bool,
    namePrefix: str,
    skeletonOnly: bool,
    drawLayer: str,
    lastMaterialName: str | None,
    optimize: bool,
) -> tuple[int, str | None]:
    bone = armatureObj.data.bones[boneName]
    if bone.parent is not None:
        transform = convertTransformMatrix @ bone.parent.matrix_local.inverted() @ bone.matrix_local
    else:
        transform = convertTransformMatrix @ bone.matrix_local

    segmentType = meshInfo.vertexGroupInfo.skinnedVertexGroups[boneName].type
    match segmentType:
        case LimbSkinType.SKIN_LIMB_TYPE_NORMAL | LimbSkinType.EMPTY:
            ...
        case LimbSkinType.SKINNED:
            ...
        case LimbSkinType.SKIN_LIMB_TYPE_ANIMATED:
            # We just need a group index that won't overwrite any other vertex group
            groupIndex = -1

    translate, rotate, scale = transform.decompose()

    groupIndex = getGroupIndexFromname(meshObj, boneName)

    meshInfo.vertexGroupInfo.vertexGroupToLimb[groupIndex] = nextIndex

    if skeletonOnly:
        mesh = None
        hasSkinnedFaces = False
    else:
        mesh, hasSkinnedFaces, lastMaterialName = ootProcessVertexGroup(
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
        if not bone.use_deform and segmentType != LimbSkinType.SKIN_LIMB_TYPE_ANIMATED:
            raise PluginError(
                bone.name
                + " has vertices in its vertex group but is not set to deformable. Make sure to enable deform on this bone."
            )
        DL = mesh.draw

    # if isinstance(parentLimb, OOTSkeleton):
    #     skeleton = parentLimb
    #     limb = OOTLimb(skeleton.name, boneName, nextIndex, translate, DL, None)
    #     skeleton.limbRoot = limb
    # else:
    #     limb = OOTLimb(parentLimb.skeletonName, boneName, nextIndex, translate, DL, None)
    #     parentLimb.children.append(limb)

    # limb.isFlex = hasSkinnedFaces

    if isinstance(parentLimb, OOTBaseSkeleton):
        skeletonName = parentLimb.name
    else:
        skeletonName = parentLimb.skeletonName
    limb = limbOverride(skeletonName, boneName, nextIndex, translate, DL)
    if isinstance(limb, SkinLimb):
        assert isinstance(meshInfo.vertexGroupInfo, OOTVertexGroupInfo)
        segmentType = meshInfo.vertexGroupInfo.skinnedVertexGroups[boneName].type
        if segmentType == LimbSkinType.SKINNED:
            limb.segment = segmentType
        elif segmentType == LimbSkinType.SKIN_LIMB_TYPE_ANIMATED:
            limb.segment = mesh
        else:
            limb.segmentType = segmentType

    parentLimb.addChild(limb)

    # limb.isFlex = hasSkinnedFaces

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
            limbOverride,
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

    armatureObj, meshObjs = ootDuplicateArmatureAndRemoveRotations(originalArmatureObj, False)

    try:
        # skeleton = OOTSkeleton(name)

        if len(armatureObj.children) == 0:
            raise PluginError("No mesh parented to armature.")

        # startBoneNames = sorted([bone.name for bone in armatureObj.data.bones if bone.parent is None])
        # startBoneName = startBoneNames[0]
        checkForStartBone(armatureObj)
        startBoneName = getStartBone(armatureObj)
        meshObj = meshObjs[0]

        meshInfo = getInfoDict(meshObj, OOTVert)
        getGroupIndices(meshInfo, armatureObj.data, meshObj, getGroupIndexFromname(meshObj, startBoneName))
        skeleton = ootConstructSkeleton(
            name, originalArmatureObj, meshObj.data.loop_triangles, meshInfo.vertexGroupInfo
        )

        convertTransformMatrix = convertTransformMatrix @ mathutils.Matrix.Diagonal(armatureObj.scale).to_4x4()

        # for i in range(len(startBoneNames)):
        # 	startBoneName = startBoneNames[i]
        assert isinstance(meshInfo.vertexGroupInfo, OOTVertexGroupInfo)
        limbIndex = 0
        meshInfo.vertexGroupInfo.boneIndexToLimbIndex[armatureObj.data.bones.find(startBoneName)] = limbIndex
        startBone = armatureObj.data.bones[startBoneName]

        for child in getRecursiveSortedChildren(startBone):
            limbIndex += 1
            childName = child.name
            boneIndex = armatureObj.data.bones.find(childName)
            meshInfo.vertexGroupInfo.boneIndexToLimbIndex[boneIndex] = limbIndex

        ootProcessBone(
            fModel,
            startBoneName,
            skeleton,
            skeleton.limbType,
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
        importInfo = ootSkeletonImportDict[settings.mode]
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
            # limbList[i].isFlex |= lodLimbList[i].isFlex

    header_filename = Path(filename).parts[-1]
    data = CData()

    data.header = f"#ifndef {header_filename.upper()}_H\n" + f"#define {header_filename.upper()}_H\n\n"

    if bpy.context.scene.fast64.oot.is_globalh_present():
        data.header += '#include "ultra64.h"\n' + '#include "global.h"\n'
    elif bpy.context.scene.fast64.oot.is_z64sceneh_present():
        data.header += '#include "ultra64.h"\n' + '#include "array_count.h"\n' + '#include "z64animation.h"\n'
    else:
        data.header += '#include "ultra64.h"\n' + '#include "array_count.h"\n' + '#include "animation.h"\n'

    if skeleton.limbType.typeName == "SkinLimb":
        data.header += '#include "skin.h"\n'

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
        textureArrayData = writeTextureArraysNew(fModel, flipbookArrayIndex2D)
        data.append(textureArrayData)

    data.header += "\n#endif\n"
    writeCData(data, os.path.join(path, filename + ".h"), os.path.join(path, filename + ".c"))

    if not isCustomExport:
        writeTextureArraysExisting(bpy.context.scene.ootDecompPath, overlayName, isLink, flipbookArrayIndex2D, fModel)
        addIncludeFiles(folderName, path, filename)
        if removeVanillaData:
            ootRemoveSkeleton(path, folderName, skeletonName)
