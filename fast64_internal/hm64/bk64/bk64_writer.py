from __future__ import annotations

from ...f3d.f3d_writer import (
    BufferVertex,
    F3DVert,
    TriangleConverter,
    TriangleConverterInfo,
    addCullCommand,
    checkForF3dMaterialInFaces,
    getF3DVert,
    revertMatAndEndDraw,
    saveMeshByFaces,
    saveMeshWithLargeTexturesByFaces,
    saveOrGetF3DMaterial,
)


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
