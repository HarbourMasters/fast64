import mathutils

from ...z64.skeleton.importer.functions import ootAddBone


ZELDA2_HAIR_SKELETON_NAME = "gZelda2Skel"
ZELDA2_HAIR_HEAD_LIMB_INDEX = 13
_ZELDA2_HAIR_MATRICES = (
    ((174, -317, 0), None),
    ((-236, -501, 0), 0),
    ((-1255, -527, 0), 1),
    ((40, 264, 386), None),
    ((-406, 212, 470), 3),
    ((40, 264, -386), None),
    ((-406, 212, -470), 5),
)
ZELDA2_HAIR_MATRIX_NAMES = tuple(f"0x0C{index * 0x40:06X}" for index in range(len(_ZELDA2_HAIR_MATRICES)))
ZELDA2_HAIR_MATRIX_BONES = frozenset(ZELDA2_HAIR_MATRIX_NAMES)
_ZELDA2_HAIR_HEAD_VERTEX_OFFSETS = {
    ZELDA2_HAIR_MATRIX_NAMES[2]: {332, 333, 334},
    ZELDA2_HAIR_MATRIX_NAMES[4]: {346, 347, 348},
}


def get_zelda2_hair_matrix_bones(skeleton_name: str) -> frozenset[str]:
    return ZELDA2_HAIR_MATRIX_BONES if skeleton_name == ZELDA2_HAIR_SKELETON_NAME else frozenset()


def add_zelda2_hair_matrices(skeleton_name, armature_obj, f3d_context):
    if skeleton_name != ZELDA2_HAIR_SKELETON_NAME or len(f3d_context.limbList) <= ZELDA2_HAIR_HEAD_LIMB_INDEX:
        return

    head_transform = f3d_context.matrixData.get(f3d_context.getLimbName(ZELDA2_HAIR_HEAD_LIMB_INDEX))
    if head_transform is None:
        return

    head_bone_name = f3d_context.getBoneName(ZELDA2_HAIR_HEAD_LIMB_INDEX)
    for index, (translation, parent_index) in enumerate(_ZELDA2_HAIR_MATRICES):
        matrix_name = ZELDA2_HAIR_MATRIX_NAMES[index]
        matrix = head_transform @ mathutils.Matrix.Translation(translation)
        parent_bone_name = head_bone_name if parent_index is None else ZELDA2_HAIR_MATRIX_NAMES[parent_index]
        ootAddBone(armature_obj, matrix_name, parent_bone_name, matrix, True, None)
        f3d_context.addRuntimeMatrix(matrix_name, matrix, matrix_name)

    head_limb_name = f3d_context.getLimbName(ZELDA2_HAIR_HEAD_LIMB_INDEX)
    for matrix_name, vertex_offsets in _ZELDA2_HAIR_HEAD_VERTEX_OFFSETS.items():
        f3d_context.addRuntimeHeadVertices(matrix_name, head_limb_name, vertex_offsets)
