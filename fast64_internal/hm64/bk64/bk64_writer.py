from __future__ import annotations

import bpy

from ...f3d.f3d_writer import (
    BufferVertex,
    F3DVert,
    LoopConvertInfo,
    MeshInfo,
    TriangleConverter,
    TriangleConverterInfo,
    addCullCommand,
    checkForF3dMaterialInFaces,
    check_face_materials,
    getF3DVert,
    getLoopFromVert,
    get_original_name,
    revertMatAndEndDraw,
    saveMeshByFaces,
    saveMeshWithLargeTexturesByFaces,
    saveOrGetF3DMaterial,
)
from ...utility import PluginError
from .bk64_uv import fixLargeUVs


class BKVert(F3DVert):
    # two BK meshes can hold the same point, and each needs its own Vtx to move
    meshTag = None

    def __eq__(self, other):
        return super().__eq__(other) and self.meshTag == other.meshTag

    def toVtx(self, mesh, texDimensions, transformMatrix, isPointSampled: bool, tex_scale=(1, 1)):
        vtx = super().toVtx(mesh, texDimensions, transformMatrix, isPointSampled, tex_scale)
        vtx.meshTag = self.meshTag  # which BK meshes claim it, never written to the binary
        return vtx


class BKTriangleConverterInfo(TriangleConverterInfo):
    def __init__(self, obj, armature, f3d, transformMatrix, infoDict, meshTags=None):
        super().__init__(obj, armature, f3d, transformMatrix, infoDict)
        self.meshTags = meshTags  # one per source vertex, BK only


class BKTriangleConverter(TriangleConverter):
    def getBufferVert(self, loop, face, groupIndex) -> BufferVertex:
        f3dVert = getF3DVert(loop, face, self.convertInfo, self.triConverterInfo.mesh, BKVert)
        meshTags = self.triConverterInfo.meshTags
        f3dVert.meshTag = meshTags[loop.vertex_index] if meshTags else None
        return BufferVertex(f3dVert, groupIndex, face.material_index)


def getInfoDict(obj: bpy.types.Object, groupInfo: VG = None) -> MeshInfo[VG]:
    try:
        return getInfoDict_impl(obj, groupInfo)
    except:
        print(f"Error in getInfoDict_impl(obj name = {get_original_name(obj)!r})")
        raise


def getInfoDict_impl(obj: bpy.types.Object, groupInfo: VG) -> MeshInfo[VG]:
    mesh: bpy.types.Mesh = obj.data
    material_slots = obj.material_slots
    if len(mesh.materials) == 0 or len(material_slots) == 0:
        raise PluginError(f"Mesh object {get_original_name(obj)} does not have any Fast3D materials.")

    # check mesh.polygons, used by fixLargeUVs
    check_face_materials(get_original_name(obj), material_slots, mesh.polygons)
    unfit = fixLargeUVs(obj)

    mesh.calc_loop_triangles()
    # check mesh.loop_triangles (now that we computed them), used below
    check_face_materials(get_original_name(obj), material_slots, mesh.loop_triangles)

    # in blender version 4.1 func was removed, in 4.1+ normals are always calculated
    if bpy.app.version < (4, 1, 0):
        mesh.calc_normals_split()

    infoDict = MeshInfo(groupInfo)
    infoDict.unfit = unfit

    vertDict = infoDict.vert
    edgeDict = infoDict.edge
    f3dVertDict = infoDict.f3dVert
    edgeValidDict = infoDict.edgeValid
    validNeighborDict = infoDict.validNeighbors

    uv_data: bpy.types.bpy_prop_collection | list[bpy.types.MeshUVLoop] = None
    if len(obj.data.uv_layers) == 0:
        uv_data = obj.data.uv_layers.new().data
    else:
        uv_data = None
        for uv_layer in obj.data.uv_layers:
            if uv_layer.name == "UVMap":
                uv_data = uv_layer.data
        if uv_data is None:
            raise PluginError("Object '" + get_original_name(obj) + "' does not have a UV layer named 'UVMap.'")
    for face in mesh.loop_triangles:
        validNeighborDict[face] = []
        material = obj.material_slots[face.material_index].material
        if material is None:
            raise PluginError(
                f"There are some faces on your mesh object {get_original_name(obj)}"
                " that are assigned to an empty material slot."
            )
        for vertIndex in face.vertices:
            if vertIndex not in vertDict:
                vertDict[vertIndex] = []
            if face not in vertDict[vertIndex]:
                vertDict[vertIndex].append(face)
        for edgeKey in face.edge_keys:
            if edgeKey not in edgeDict:
                edgeDict[edgeKey] = []
            if face not in edgeDict[edgeKey]:
                edgeDict[edgeKey].append(face)

        for loopIndex in face.loops:
            convertInfo = LoopConvertInfo(uv_data, obj, obj.material_slots[face.material_index].material)
            f3dVertDict[loopIndex] = getF3DVert(mesh.loops[loopIndex], face, convertInfo, mesh)
    for face in mesh.loop_triangles:
        for edgeKey in face.edge_keys:
            for otherFace in edgeDict[edgeKey]:
                if otherFace == face:
                    continue
                if (otherFace, face) not in edgeValidDict and (face, otherFace) not in edgeValidDict:
                    edgeValid = (
                        f3dVertDict[getLoopFromVert(edgeKey[0], face)]
                        == f3dVertDict[getLoopFromVert(edgeKey[0], otherFace)]
                        and f3dVertDict[getLoopFromVert(edgeKey[1], face)]
                        == f3dVertDict[getLoopFromVert(edgeKey[1], otherFace)]
                    )
                    edgeValidDict[(otherFace, face)] = edgeValid
                    if edgeValid:
                        validNeighborDict[face].append(otherFace)
                        validNeighborDict[otherFace].append(face)
    return infoDict


def saveStaticModel(
    triConverterInfo,
    fModel: FModel,
    obj,
    transformMatrix,
    ownerName: str,
    convertTextureData,
    revertMatAtEnd: bool,
    drawLayerField,
):
    if len(obj.data.polygons) == 0:
        return None

    # checkForF3DMaterial(obj)

    faces_by_mat = {}
    for face in obj.data.loop_triangles:
        if face.material_index not in faces_by_mat:
            faces_by_mat[face.material_index] = []
        faces_by_mat[face.material_index].append(face)

    # sort by material slot
    faces_by_mat = {
        mat_index: faces_by_mat[mat_index]
        for mat_index, _ in enumerate(obj.material_slots)
        if mat_index in faces_by_mat
    }

    fMeshes: dict[str, FMesh] = {}
    for material_index, faces in faces_by_mat.items():
        material = obj.material_slots[material_index].material

        if drawLayerField is not None and material.mat_ver > 3:
            drawLayer = getattr(material.f3d_mat.draw_layer, drawLayerField)
            drawLayerName = drawLayer
        else:
            drawLayer = fModel.getDrawLayerV3(obj)
            drawLayerName = None

        if drawLayer not in fMeshes:
            fMesh = fModel.addMesh(obj.original_name, ownerName, drawLayerName, False, obj)
            fMeshes[drawLayer] = fMesh

            if obj.use_f3d_culling and not fModel.f3d.F3D_OLD_GBI:
                addCullCommand(obj, fMesh, transformMatrix, fModel.matWriteMethod)
        else:
            fMesh = fMeshes[drawLayer]

        checkForF3dMaterialInFaces(obj, material)
        fMaterial, texDimensions = saveOrGetF3DMaterial(material, fModel, obj, drawLayer, convertTextureData)

        if fMaterial.isTexLarge[0] or fMaterial.isTexLarge[1]:
            saveMeshWithLargeTexturesByFaces(
                material,
                faces,
                fModel,
                fMesh,
                obj,
                drawLayer,
                convertTextureData,
                None,
                triConverterInfo,
                None,
                None,
                None,
            )
        else:
            saveMeshByFaces(
                material,
                faces,
                fModel,
                fMesh,
                obj,
                drawLayer,
                convertTextureData,
                None,
                triConverterInfo,
                None,
                None,
                None,
                BKTriangleConverter,
            )

    for drawLayer, fMesh in fMeshes.items():
        if revertMatAtEnd:
            revertMatAndEndDraw(fMesh.draw, [])
        else:
            fModel.endDraw(fMesh, obj)
    return fMeshes
