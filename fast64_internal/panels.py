import bpy


# --- SM64 Panel ---

_sm64_compatible_modes = {"SM64"}


def register_sm64_compatible_mode(mode: str):
    _sm64_compatible_modes.add(mode)


def unregister_sm64_compatible_mode(mode: str):
    _sm64_compatible_modes.discard(mode)


class SM64_Panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SM64"
    bl_options = {"DEFAULT_CLOSED"}

    # If bl_context is 'object' and object_type is defined, only show if the object is in the types
    bl_context = ""
    object_type: list | None = None

    # goal refers to the selected enum_sm64_goal_type in SM64_Properties,
    # a different selection than this goal will filter this panel out
    goal = "All"
    # if this is True, the panel is hidden whenever the scene's export_type is not 'C'
    decomp_only = False
    # if this is True, the panel is hidden whenever the scene's export_type is 'C'
    binary_only = False
    import_panel = False

    @classmethod
    def poll(cls, context):
        if cls.bl_context == "object":
            if cls.object_type and context.object.type not in cls.object_type:
                return False
        sm64_props = context.scene.fast64.sm64
        if context.scene.gameEditorMode not in _sm64_compatible_modes:
            return False
        elif cls.import_panel and not sm64_props.show_importing_menus:
            return False
        elif cls.decomp_only and sm64_props.export_type != "C":
            return False
        elif cls.binary_only and sm64_props.export_type == "C":
            return False
        scene_goal = sm64_props.goal
        return scene_goal == "All" or sm64_props.goal == cls.goal or cls.goal == "All"


# --- OOT Panel ---

_oot_compatible_modes = {"OOT"}


def register_oot_compatible_mode(mode: str):
    _oot_compatible_modes.add(mode)


def unregister_oot_compatible_mode(mode: str):
    _oot_compatible_modes.discard(mode)


class OOT_Panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OOT"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode in _oot_compatible_modes


# --- MK64 Panel ---

_mk64_compatible_modes = {"MK64"}


def register_mk64_compatible_mode(mode: str):
    _mk64_compatible_modes.add(mode)


def unregister_mk64_compatible_mode(mode: str):
    _mk64_compatible_modes.discard(mode)


class MK64_Panel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MK64"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.gameEditorMode in _mk64_compatible_modes
