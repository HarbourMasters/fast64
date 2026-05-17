from .functions import ootConvertArmatureToSkeletonWithoutMesh, ootConvertArmatureToC, ootConvertArmatureToO2R
from .operators import mm_skeleton_ops_register, mm_skeleton_ops_unregister


def mm_skeleton_register():
    from .constants import find_skeleton_import_info, get_skeleton_mode_items
    from ....z64.skeleton.constants import register_skeleton_extensions

    register_skeleton_extensions(get_skeleton_mode_items, find_skeleton_import_info)
    mm_skeleton_ops_register()


def mm_skeleton_unregister():
    from ....z64.skeleton.constants import unregister_skeleton_extensions

    unregister_skeleton_extensions()
    mm_skeleton_ops_unregister()
