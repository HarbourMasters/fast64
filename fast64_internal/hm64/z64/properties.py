"""HM64 matrix-call properties."""

import bpy
from bpy.types import PropertyGroup, Object
from bpy.props import StringProperty, EnumProperty, CollectionProperty, IntProperty
from bpy.utils import register_class, unregister_class


LIMB_MATRIX_OPTIONS = (
    ("none", "None", ""),
    ("head", "Head (0x0D0001C0)", ">0x0D0001C0"),
    ("hat", "Hat (0x0D000200)", ">0x0D000200"),
    ("left_shoulder", "Left Shoulder (0x0D000280)", ">0x0D000280"),
    ("left_arm", "Left Arm (0x0D0002C0)", ">0x0D0002C0"),
    ("left_hand", "Left Hand (0x0D000300)", ">0x0D000300"),
    ("right_shoulder", "Right Shoulder (0x0D000340)", ">0x0D000340"),
    ("right_arm", "Right Arm (0x0D000380)", ">0x0D000380"),
    ("right_hand", "Right Hand (0x0D0003C0)", ">0x0D0003C0"),
    ("chest", "Chest (0x0D000440)", ">0x0D000440"),
    ("collar", "Collar (0x0D000240)", ">0x0D000240"),
    ("waist", "Waist (0x0D000000)", ">0x0D000000"),
    ("right_thigh", "Right Thigh (0x0D000040)", ">0x0D000040"),
    ("right_leg", "Right Leg (0x0D000080)", ">0x0D000080"),
    ("right_foot", "Right Foot (0x0D0000C0)", ">0x0D0000C0"),
    ("left_thigh", "Left Thigh (0x0D000100)", ">0x0D000100"),
    ("left_leg", "Left Leg (0x0D000140)", ">0x0D000140"),
    ("left_foot", "Left Foot (0x0D000180)", ">0x0D000180"),
)
LIMB_MATRIX_PATHS = {key: path for key, _label, path in LIMB_MATRIX_OPTIONS}


class OOTDLMatrixCallPair(PropertyGroup):
    limb: EnumProperty(
        name="Limb",
        items=LIMB_MATRIX_OPTIONS,
        default="none",
    )
    call_dl: StringProperty(
        name="Call DL",
        default="",
        description="Display list path to emit after the matrix entry",
    )
    internal_path: StringProperty(
        name="Internal Path",
        default="",
        description="Optional internal path prefix used when writing the call display list",
    )

    @property
    def matrix_path(self) -> str:
        return LIMB_MATRIX_PATHS.get(self.limb, "")


hm64_property_classes = (OOTDLMatrixCallPair,)


def register():
    for cls in hm64_property_classes:
        register_class(cls)
    Object.oot_matrix_calls = CollectionProperty(type=OOTDLMatrixCallPair)
    Object.oot_matrix_calls_index = IntProperty(default=0)


def unregister():
    del Object.oot_matrix_calls
    del Object.oot_matrix_calls_index
    for cls in reversed(hm64_property_classes):
        unregister_class(cls)
