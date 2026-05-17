"""HM64 base panel class for the HM64 UI tab."""

import bpy

_HM64_MODES = {"SOH", "2SHIP", "SPK"}


def register_hm64_mode(mode: str):
    _HM64_MODES.add(mode)


def unregister_hm64_mode(mode: str):
    _HM64_MODES.discard(mode)


class HM64_Panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HM64"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode in _HM64_MODES
