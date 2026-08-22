import os
import re
import bpy

from typing import Optional

from ...utility import CData, getGroupIndexFromname, getGroupNameFromIndex, readFile, writeFile
from ...f3d.flipbook import flipbook_to_c, flipbook_2d_to_c, flipbook_data_to_c
from ...f3d.f3d_gbi import MTX_SIZE
from ...f3d.f3d_material import createF3DMat, F3DMaterial_UpdateLock, update_preset_manual
from ...z64.utility import replaceMatchContent, getOOTScale
from ...z64.texture_array import TextureFlipbook

from ..f3d.hm64_f3d_writer import (
    checkForF3dMaterialInFaces,
    saveOrGetF3DMaterial,
    saveMeshWithLargeTexturesByFaces,
    saveMeshByFaces,
)

from ...z64.model_classes import (
    OOTTriangleConverter,
    OOTTriangleConverterInfo,
    OOTModel,
    ootGetActorData,
    ootGetLinkData,
)


_HM64_LINK_SKELETONS = {
    "gLinkChildSkel",
    "gLinkAdultSkel",
    "gDarkLinkSkel",
    "gLinkHumanSkel",
    "gLinkDekuSkel",
    "gLinkGoronSkel",
    "gLinkZoraSkel",
    "gLinkFierceDeitySkel",
    "gLinkChildKokiriTunicSkel",
    "gLinkChildGoronTunicSkel",
    "gLinkChildZoraTunicSkel",
    "gLinkAdultKokiriTunicSkel",
    "gLinkAdultGoronTunicSkel",
    "gLinkAdultZoraTunicSkel",
}
_HM64_LINK_PRIORITY_LIMBS = {10, 13, 16}
_HM64_LINK_TORSO_LIMB = 20
_HM64_LINK_TORSO_MATRIX_INDEX = 17


def _is_hm64_link_torso_exception(
    namePrefix: str, currentGroupIndex: int, vertGroupIndex: int, meshObj, armatureObj, meshInfo
):
    if namePrefix not in _HM64_LINK_SKELETONS:
        return False

    current_bone_name = getGroupNameFromIndex(meshObj, currentGroupIndex)
    other_bone_name = getGroupNameFromIndex(meshObj, vertGroupIndex)
    if current_bone_name is None or other_bone_name is None:
        return False

    current_bone_index = armatureObj.data.bones.find(current_bone_name)
    other_bone_index = armatureObj.data.bones.find(other_bone_name)
    if current_bone_index < 0 or other_bone_index < 0:
        return False

    current_limb_index = meshInfo.vertexGroupInfo.boneIndexToLimbIndex.get(current_bone_index)
    other_limb_index = meshInfo.vertexGroupInfo.boneIndexToLimbIndex.get(other_bone_index)
    return current_limb_index in _HM64_LINK_PRIORITY_LIMBS and other_limb_index == _HM64_LINK_TORSO_LIMB


class HM64OOTTriangleConverterInfo(OOTTriangleConverterInfo):
    def __init__(self, obj, armature, f3d, transformMatrix, infoDict, allowed_missing_matrix_groups):
        super().__init__(obj, armature, f3d, transformMatrix, infoDict)
        self.hm64_allowed_missing_matrix_groups = allowed_missing_matrix_groups

    def getMatrixAddrFromGroup(self, groupIndex):
        if (
            groupIndex not in self.vertexGroupInfo.vertexGroupToMatrixIndex
            and groupIndex in self.hm64_allowed_missing_matrix_groups
        ):
            return format((0x0D << 24) + MTX_SIZE * _HM64_LINK_TORSO_MATRIX_INDEX, "#010x")
        return super().getMatrixAddrFromGroup(groupIndex)


# Creates a semi-transparent solid color material (cached)
def getColliderMat(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    if "oot_collision_mat_base" not in bpy.data.materials:
        baseMat = createF3DMat(None, preset="oot_shaded_texture_transparent", index=0)
        with F3DMaterial_UpdateLock(baseMat) as lockedMat:
            lockedMat.name = name
            lockedMat.f3d_mat.combiner1.A = "0"
            lockedMat.f3d_mat.combiner1.C = "0"
            lockedMat.f3d_mat.combiner1.D = "SHADE"
            lockedMat.f3d_mat.combiner1.D_alpha = "1"
            lockedMat.f3d_mat.prim_color = color
            update_preset_manual(lockedMat, bpy.context)

    if name not in bpy.data.materials:
        baseMat = bpy.data.materials["oot_collision_mat_base"]
        baseMat.f3d_update_flag = True
        newMat = baseMat.copy()
        baseMat.f3d_update_flag = False
        newMat.f3d_mat.prim_color = color
        return newMat
    else:
        return bpy.data.materials[name]


# returns:
# 	mesh,
# 	anySkinnedFaces (to determine if skeleton should be flex)
def ootProcessVertexGroup(
    fModel,
    meshObj,
    vertexGroup,
    convertTransformMatrix,
    armatureObj,
    namePrefix,
    meshInfo,
    drawLayerOverride,
    convertTextureData,
    lastMaterialName,
    optimize: bool,
):
    lastMaterialName = None
    claimed_exception_faces = getattr(meshInfo, "hm64_claimed_exception_faces", None)
    if claimed_exception_faces is None:
        claimed_exception_faces = set()
        meshInfo.hm64_claimed_exception_faces = claimed_exception_faces

    mesh = meshObj.data
    currentGroupIndex = getGroupIndexFromname(meshObj, vertexGroup)
    nextDLIndex = len(meshInfo.vertexGroupInfo.vertexGroupToMatrixIndex)
    vertIndices = [
        vert.index
        for vert in meshObj.data.vertices
        if meshInfo.vertexGroupInfo.vertexGroups[vert.index] == currentGroupIndex
    ]

    if len(vertIndices) == 0:
        print("No vert indices in " + vertexGroup)
        return None, False, lastMaterialName

    bone = armatureObj.data.bones[vertexGroup]

    # dict of material_index keys to face array values
    groupFaces = {}

    hasSkinnedFaces = False

    handledFaces = []
    anyConnectedToUnhandledBone = False
    exceptionMatrixGroups = set()
    for vertIndex in vertIndices:
        if vertIndex not in meshInfo.vert:
            continue
        for face in meshInfo.vert[vertIndex]:
            # Ignore repeat faces
            if face in handledFaces or face in claimed_exception_faces:
                continue

            connectedToUnhandledBone = False
            uses_exception_face = False

            # A Blender loop is interpreted as face + loop index
            for i in range(3):
                faceVertIndex = face.vertices[i]
                vertGroupIndex = meshInfo.vertexGroupInfo.vertexGroups[faceVertIndex]
                if vertGroupIndex != currentGroupIndex:
                    hasSkinnedFaces = True
                if vertGroupIndex not in meshInfo.vertexGroupInfo.vertexGroupToLimb:
                    if _is_hm64_link_torso_exception(
                        namePrefix,
                        currentGroupIndex,
                        vertGroupIndex,
                        meshObj,
                        armatureObj,
                        meshInfo,
                    ):
                        exceptionMatrixGroups.add(vertGroupIndex)
                        uses_exception_face = True
                        continue
                    # Connected to a bone not processed yet
                    # These skinned faces will be handled by that limb
                    connectedToUnhandledBone = True
                    anyConnectedToUnhandledBone = True
                    break

            if connectedToUnhandledBone:
                continue

            if face.material_index not in groupFaces:
                groupFaces[face.material_index] = []
            groupFaces[face.material_index].append(face)

            handledFaces.append(face)
            if uses_exception_face:
                claimed_exception_faces.add(face)

    if len(groupFaces) == 0:
        print("No faces in " + vertexGroup)

        # OOT will only allocate matrix if DL exists.
        # This doesn't handle case where vertices belong to a limb, but not triangles.
        # Therefore we create a dummy DL
        if anyConnectedToUnhandledBone:
            fMesh = fModel.addMesh(
                vertexGroup,
                namePrefix,
                drawLayerOverride,
                False,
                bone,
            )
            fModel.endDraw(fMesh, bone)
            meshInfo.vertexGroupInfo.vertexGroupToMatrixIndex[currentGroupIndex] = nextDLIndex
            return fMesh, False, lastMaterialName
        else:
            return None, False, lastMaterialName

    meshInfo.vertexGroupInfo.vertexGroupToMatrixIndex[currentGroupIndex] = nextDLIndex
    triConverterInfo = HM64OOTTriangleConverterInfo(
        meshObj,
        armatureObj.data,
        fModel.f3d,
        convertTransformMatrix,
        meshInfo,
        exceptionMatrixGroups,
    )

    if optimize:
        # If one of the materials we need to draw is the currently loaded material,
        # do this one first.
        newGroupFaces = {
            material_index: faces
            for material_index, faces in groupFaces.items()
            if meshObj.material_slots[material_index].material.name == lastMaterialName
        }
        newGroupFaces.update(groupFaces)
        groupFaces = newGroupFaces

    # Usually we would separate DLs into different draw layers.
    # however it seems like OOT skeletons don't have this ability.
    # Therefore we always use the drawLayerOverride as the draw layer key.
    # This means everything will be saved to one mesh.
    fMesh = fModel.addMesh(
        vertexGroup,
        namePrefix,
        drawLayerOverride,
        False,
        bone,
    )

    previous_scope_key = getattr(fModel, "hm64_material_scope_key", None)
    previous_manifest_owner = getattr(fModel, "hm64_material_manifest_owner_name", None)
    fModel.hm64_material_scope_key = f"{namePrefix}:{vertexGroup}"
    fModel.hm64_material_manifest_owner_name = fMesh.draw.name
    try:
        for material_index, faces in groupFaces.items():
            material = meshObj.material_slots[material_index].material
            checkForF3dMaterialInFaces(meshObj, material)
            fMaterial, texDimensions = saveOrGetF3DMaterial(
                material, fModel, meshObj, drawLayerOverride, convertTextureData
            )

            if fMaterial.isTexLarge[0] or fMaterial.isTexLarge[1]:
                currentGroupIndex = saveMeshWithLargeTexturesByFaces(
                    material,
                    faces,
                    fModel,
                    fMesh,
                    meshObj,
                    drawLayerOverride,
                    convertTextureData,
                    currentGroupIndex,
                    triConverterInfo,
                    None,
                    None,
                    lastMaterialName,
                    OOTTriangleConverter,
                )
            else:
                currentGroupIndex = saveMeshByFaces(
                    material,
                    faces,
                    fModel,
                    fMesh,
                    meshObj,
                    drawLayerOverride,
                    convertTextureData,
                    currentGroupIndex,
                    triConverterInfo,
                    None,
                    None,
                    lastMaterialName,
                    OOTTriangleConverter,
                )

            lastMaterialName = material.name if optimize else None
    finally:
        if previous_scope_key is None:
            if hasattr(fModel, "hm64_material_scope_key"):
                delattr(fModel, "hm64_material_scope_key")
        else:
            fModel.hm64_material_scope_key = previous_scope_key

        if previous_manifest_owner is None:
            if hasattr(fModel, "hm64_material_manifest_owner_name"):
                delattr(fModel, "hm64_material_manifest_owner_name")
        else:
            fModel.hm64_material_manifest_owner_name = previous_manifest_owner

    fModel.endDraw(fMesh, bone)

    return fMesh, hasSkinnedFaces, lastMaterialName


def writeTextureArraysNew(fModel: OOTModel, arrayIndex: int):
    textureArrayData = CData()
    for flipbook in fModel.flipbooks:
        if flipbook.exportMode == "Array":
            if arrayIndex is not None:
                textureArrayData.source += flipbook_2d_to_c(flipbook, True, arrayIndex + 1) + "\n"
            else:
                textureArrayData.source += flipbook_to_c(flipbook, True) + "\n"
    return textureArrayData


def getActorFilepath(basePath: str, overlayName: str | None, isLink: bool, checkDataPath: bool = False):
    if isLink:
        actorFilePath = os.path.join(basePath, f"src/code/z_player_lib.c")
    else:
        actorFilePath = os.path.join(basePath, f"src/overlays/actors/{overlayName}/z_{overlayName[4:].lower()}.c")
        actorFileDataPath = f"{actorFilePath[:-2]}_data.c"  # some bosses store texture arrays here

        if checkDataPath and os.path.exists(actorFileDataPath):
            actorFilePath = actorFileDataPath

    return actorFilePath


def writeTextureArraysExisting(
    exportPath: str, overlayName: str, isLink: bool, flipbookArrayIndex2D: int, fModel: OOTModel
):
    actorFilePath = getActorFilepath(exportPath, overlayName, isLink, True)

    if not os.path.exists(actorFilePath):
        print(f"{actorFilePath} not found, ignoring texture array writing.")
        return

    actorData = readFile(actorFilePath)
    newData = actorData

    for flipbook in fModel.flipbooks:
        if flipbook.exportMode == "Array":
            if flipbookArrayIndex2D is None:
                newData = writeTextureArraysExisting1D(newData, flipbook, "")
            else:
                newData = writeTextureArraysExisting2D(newData, flipbook, flipbookArrayIndex2D)

    if newData != actorData:
        writeFile(actorFilePath, newData)


def writeTextureArraysExisting1D(data: str, flipbook: TextureFlipbook, additionalIncludes: str) -> str:
    newData = data
    arrayMatch = re.search(
        r"(static\s*)?void\s*\*\s*" + re.escape(flipbook.name) + r"\s*\[\s*\]\s*=\s*\{(((?!\}).)*)\}\s*;",
        newData,
        flags=re.DOTALL,
    )

    # replace array if found
    if arrayMatch:
        newArrayData = flipbook_to_c(flipbook, arrayMatch.group(1))
        newData = newData[: arrayMatch.start(0)] + newArrayData + newData[arrayMatch.end(0) :]

        # otherwise, add to end of asset includes
    else:
        newArrayData = flipbook_to_c(flipbook, True)

    # get last asset include
    includeMatch = None
    for includeMatchItem in re.finditer(r"\#include\s*\"assets/.*?\"\s*?\n", newData, flags=re.DOTALL):
        includeMatch = includeMatchItem
    if includeMatch:
        newData = (
            newData[: includeMatch.end(0)]
            + additionalIncludes
            + ((newArrayData + "\n") if not arrayMatch else "")
            + newData[includeMatch.end(0) :]
        )
    else:
        newData = (additionalIncludes + newData + newArrayData + "\n") if not arrayMatch else newData

    return newData


# for flipbook textures, we only replace one element of the 2D array.
def writeTextureArraysExisting2D(data: str, flipbook: TextureFlipbook, flipbookArrayIndex2D: int) -> str:
    newData = data

    # for !AVOID_UB, Link has textures in 2D Arrays
    array2DMatch = re.search(
        r"(static\s*)?void\s*\*\s*"
        + re.escape(flipbook.name)
        + r"\s*\[\s*\]\s*\[\s*[0-9a-zA-Z_]*\s*\]\s*=\s*\{(.*?)\}\s*;",
        newData,
        flags=re.DOTALL,
    )

    newArrayData = "{\n" + flipbook_data_to_c(flipbook) + " }"

    # build a list of arrays here
    # replace existing element if list is large enough
    # otherwise, pad list with repeated arrays
    if array2DMatch:
        arrayMatchData = [
            arrayMatch.group(0) for arrayMatch in re.finditer(r"\{(.*?)\}", array2DMatch.group(2), flags=re.DOTALL)
        ]

        if flipbookArrayIndex2D >= len(arrayMatchData):
            while len(arrayMatchData) <= flipbookArrayIndex2D:
                arrayMatchData.append(newArrayData)
        else:
            arrayMatchData[flipbookArrayIndex2D] = newArrayData

        newArray2DData = ",\n".join([item for item in arrayMatchData])
        newData = replaceMatchContent(newData, newArray2DData, array2DMatch, 2)

        # otherwise, add to end of asset includes
    else:
        arrayMatchData = [newArrayData] * (flipbookArrayIndex2D + 1)
        newArray2DData = ",\n".join([item for item in arrayMatchData])

        # get last asset include
        includeMatch = None
        for includeMatchItem in re.finditer(r"\#include\s*\"assets/.*?\"\s*?\n", newData, flags=re.DOTALL):
            includeMatch = includeMatchItem
        if includeMatch:
            newData = newData[: includeMatch.end(0)] + newArray2DData + "\n" + newData[includeMatch.end(0) :]
        else:
            newData += newArray2DData + "\n"

    return newData


# Note this does not work well with actors containing multiple "parts". (z_en_honotrap)
def ootReadActorScale(basePath: str, overlayName: str, isLink: bool) -> Optional[float]:
    if not isLink:
        actorData = ootGetActorData(basePath, overlayName)
    else:
        actorData = ootGetLinkData(basePath)

    chainInitMatch = re.search(r"CHAIN_VEC3F_DIV1000\s*\(\s*scale\s*,\s*(.*?)\s*,", actorData, re.DOTALL)
    if chainInitMatch is not None:
        scale = chainInitMatch.group(1).strip()
        if scale[-1] == "f":
            scale = scale[:-1]
        return getOOTScale(1 / (float(scale) / 1000))

    actorScaleMatch = re.search(r"Actor\_SetScale\s*\(.*?,\s*(.*?)\s*\)", actorData, re.DOTALL)
    if actorScaleMatch is not None:
        scale = actorScaleMatch.group(1).strip()
        if scale[-1] == "f":
            scale = scale[:-1]
        try:
            return getOOTScale(1 / float(scale))
        except:
            print(f"WARNING: the scale value read is not a float ({repr(scale)})")

    print("WARNING: auto-detection failed, defaulting to this panel's actor scale property value")
    return None
