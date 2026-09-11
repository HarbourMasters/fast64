from __future__ import annotations

import os
import re
import struct
from contextlib import contextmanager
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UILayout
from bpy.utils import register_class, unregister_class

from ...utility import PluginError, hexOrDecInt, prop_split, toAlnum
from ...game_data import game_data
from ...data.z64.actor_data import Z64_ActorData
from ...data.z64.object_data import Z64_ObjectData
from ...data.z64.data import (
    mm_enum_camera_setting_type,
    mm_enum_environment_type,
    mm_enum_room_type,
    mm_enum_skybox,
    mm_enum_skybox_config,
    oot_enum_camera_setting_type,
    oot_enum_environment_type,
    oot_enum_nature_id,
    oot_enum_room_type,
    oot_enum_skybox,
    oot_enum_skybox_config,
    enum_ambiance_id,
)
from ...z64.exporter import SceneExport
from ...z64.exporter.room import shape as room_shape_exporter
from ...z64.exporter.utility import Utility
from ...z64.scene.operators import OOT_ExportScene
from ...z64.scene import operators as scene_operators
from ...z64.scene import panels as scene_panels
from ...z64 import props_panel_main
from ...z64.scene.properties import (
    OOTAlternateSceneHeaderProperty,
    OOTExportSceneSettingsProperty,
    OOTSceneHeaderProperty,
)
from ...z64.actor.properties import OOTActorHeaderProperty, OOTActorProperty
from ...z64.room.properties import OOTAlternateRoomHeaderProperty, OOTObjectProperty, OOTRoomHeaderProperty
from ...z64.utility import getEvalParamsInt, getObjectList, ootSceneDungeons, sceneNameFromID
from ..f3d.soh_xml_exporter import register as ensure_hm64_soh_xml
from ..f3d.f3d_texture_writer_hm64 import register as ensure_hm64_texture_writer
from ..f3d.hm64_f3d_writer import TriangleConverterInfo, getInfoDict, saveStaticModel
from ..utility import hm64_mm_features_enabled, is_hm64, writeXMLData
from .mm_scenes import mm_enum_scene_id, mm_scene_id_to_name
from .o2r_import import get_hm64_o2r_source, normalize_o2r_path
from .o2r_object_ids import O2R_OBJECT_IDS


_RESOURCE_HEADER_SIZE = 0x40
_RESOURCE_MAGIC = 0xDEADBEEFDEADBEEF
_OOT_ACTORS = None
_MM_ACTORS = None
_MM_OBJECT_ENUM = None
_oot_actor_ids = None
_HM64_SCENE_IS_OOT = True
_HM64_ACTOR_REF = "_hm64_o2r_actor_ref"
_MM_ACTOR_ENUM = {}
_HM64_MM_ACTOR_MENU = (("General", "General", "General"), ("Actor Cutscene", "Actor Cutscene", "Actor Cutscene"))
_HM64_MM_HALF_DAY = (
    ("Custom", "Custom", "Custom"),
    ("0-Dawn", "Day 0 (Intro) - Dawn", "Day 0 - Dawn"),
    ("0-Night", "Day 0 (Intro) - Night", "Day 0 - Night"),
    ("1-Dawn", "Day 1 - Dawn", "Day 1 - Dawn"),
    ("1-Night", "Day 1 - Night", "Day 1 - Night"),
    ("2-Dawn", "Day 2 - Dawn", "Day 2 - Dawn"),
    ("2-Night", "Day 2 - Night", "Day 2 - Night"),
    ("3-Dawn", "Day 3 - Dawn", "Day 3 - Dawn"),
    ("3-Night", "Day 3 - Night", "Day 3 - Night"),
    ("4-Dawn", "Day 4 (Credits) - Dawn", "Day 4 - Dawn"),
    ("4-Night", "Day 4 (Credits) - Night", "Day 4 - Night"),
)
_HM64_MM_HALFDAY_BITS = {
    "0-Dawn": 1 << 9,
    "0-Night": 1 << 8,
    "1-Dawn": 1 << 7,
    "1-Night": 1 << 6,
    "2-Dawn": 1 << 5,
    "2-Night": 1 << 4,
    "3-Dawn": 1 << 3,
    "3-Night": 1 << 2,
    "4-Dawn": 1 << 1,
    "4-Night": 1 << 0,
}
_HM64_MM_HALFDAY_ALL_DAWNS = (
    _HM64_MM_HALFDAY_BITS["0-Dawn"]
    | _HM64_MM_HALFDAY_BITS["1-Dawn"]
    | _HM64_MM_HALFDAY_BITS["2-Dawn"]
    | _HM64_MM_HALFDAY_BITS["3-Dawn"]
    | _HM64_MM_HALFDAY_BITS["4-Dawn"]
)
_HM64_MM_HALFDAY_ALL_NIGHTS = (
    _HM64_MM_HALFDAY_BITS["0-Night"]
    | _HM64_MM_HALFDAY_BITS["1-Night"]
    | _HM64_MM_HALFDAY_BITS["2-Night"]
    | _HM64_MM_HALFDAY_BITS["3-Night"]
    | _HM64_MM_HALFDAY_BITS["4-Night"]
)
_HM64_MM_HALFDAY_ALL = _HM64_MM_HALFDAY_ALL_DAWNS | _HM64_MM_HALFDAY_ALL_NIGHTS


def _build_mm_actor_items(actor_user: str = "Actor"):
    actors = Z64_ActorData("MM")
    items = [("Custom", "Custom Actor", "Custom")]
    if actor_user == "Entrance":
        player = actors.actorsByKey["player"]
        items.append((player.id, player.name, player.id))
    else:
        actor_list = sorted(actors.actorList, key=lambda actor: actor.index)
        if actor_user == "Transition Actor":
            actor_list = [actor for actor in actor_list if actor.category == "ACTORCAT_DOOR"]
        items.extend((actor.id, actor.name, actor.id) for actor in actor_list)
    return items


def _build_mm_object_items():
    objects = Z64_ObjectData("MM")
    return [("Custom", "Custom Object", "Custom")] + [
        (obj.key, obj.name, obj.id) for obj in sorted(objects.objectList, key=lambda obj: obj.index)
    ]


_HM64_MM_ACTOR_ITEMS = _build_mm_actor_items("Actor")
_HM64_MM_TRANSITION_ACTOR_ITEMS = _build_mm_actor_items("Transition Actor")
_HM64_MM_ENTRANCE_ACTOR_ITEMS = _build_mm_actor_items("Entrance")
_HM64_MM_OBJECT_ITEMS = _build_mm_object_items()
_SCENE_ENUMS = (
    oot_enum_skybox,
    oot_enum_skybox_config,
    oot_enum_environment_type,
    oot_enum_nature_id,
    oot_enum_room_type,
    oot_enum_camera_setting_type,
    mm_enum_skybox,
    mm_enum_skybox_config,
    mm_enum_environment_type,
    mm_enum_room_type,
    mm_enum_camera_setting_type,
    enum_ambiance_id,
)
_ENTRANCE_INDEX_RE = re.compile(r"/\*\s*0x([0-9A-Fa-f]+)\s*\*/\s*DEFINE_ENTRANCE\((ENTR_[A-Z0-9_]+)")
_ACTOR_ID_RE = re.compile(r"/\*\s*0x([0-9A-Fa-f]+)\s*\*/\s*DEFINE_ACTOR(?:_INTERNAL)?\([^,]+,\s*(ACTOR_[A-Z0-9_]+)")
_entrance_indices = None
_MM_ROOM_TYPES = {
    "ROOM_TYPE_NORMAL": 0,
    "ROOM_TYPE_DUNGEON": 1,
    "ROOM_TYPE_INDOORS": 2,
    "ROOM_TYPE_3": 3,
    "ROOM_TYPE_4": 4,
    "ROOM_TYPE_BOSS": 5,
    "ROOM_ENV_DEFAULT": 0,
    "ROOM_ENV_COLD": 1,
    "ROOM_ENV_WARM": 2,
    "ROOM_ENV_HOT": 3,
    "ROOM_ENV_UNK_STRETCH_1": 4,
    "ROOM_ENV_UNK_STRETCH_2": 5,
    "ROOM_ENV_UNK_STRETCH_3": 6,
    "LIGHT_MODE_TIME": 0,
    "LIGHT_MODE_SETTINGS": 1,
}
_OOT_SCENE_CAMERA_TYPES = {
    "SCENE_CAM_TYPE_DEFAULT": 0x00,
    "SCENE_CAM_TYPE_FIXED_SHOP_VIEWPOINT": 0x10,
    "SCENE_CAM_TYPE_FIXED_TOGGLE_VIEWPOINT": 0x20,
    "SCENE_CAM_TYPE_FIXED": 0x30,
    "SCENE_CAM_TYPE_FIXED_MARKET": 0x40,
    "SCENE_CAM_TYPE_SHOOTING_GALLERY": 0x50,
}
_CMD = {
    "START_POSITIONS": 0x00,
    "ACTORS": 0x01,
    "COLLISION": 0x03,
    "ROOMS": 0x04,
    "WIND": 0x05,
    "ENTRANCES": 0x06,
    "SPECIAL_OBJECTS": 0x07,
    "ROOM_BEHAVIOR": 0x08,
    "MESH": 0x0A,
    "OBJECTS": 0x0B,
    "PATHWAYS": 0x0D,
    "TRANSITIONS": 0x0E,
    "LIGHTING": 0x0F,
    "TIME": 0x10,
    "SKYBOX": 0x11,
    "SKYBOX_MODIFIER": 0x12,
    "EXITS": 0x13,
    "END": 0x14,
    "SOUND": 0x15,
    "ECHO": 0x16,
    "CUTSCENES": 0x17,
    "ALTERNATE_HEADERS": 0x18,
    "CAMERA_SETTINGS": 0x19,
}
_MM_CMD = {
    **_CMD,
    "WORLD_MAP_VISITED": 0x19,
    "ANIMATED_MATERIALS": 0x1A,
    "ACTOR_CUTSCENES": 0x1B,
    "MINIMAP": 0x1C,
    "MINIMAP_CHESTS": 0x1E,
    "CUTSCENES": 0x1F,
}


class _Writer:
    def __init__(self, resource_type: bytes):
        self.data = bytearray(_RESOURCE_HEADER_SIZE)
        struct.pack_into("<I", self.data, 4, int.from_bytes(resource_type, "little"))
        struct.pack_into("<Q", self.data, 12, _RESOURCE_MAGIC)

    def u8(self, value):
        self.data.extend(struct.pack("<B", int(value) & 0xFF))

    def s8(self, value):
        self.data.extend(struct.pack("<b", max(-128, min(127, int(value)))))

    def u16(self, value):
        self.data.extend(struct.pack("<H", int(value) & 0xFFFF))

    def s16(self, value):
        self.data.extend(struct.pack("<h", max(-32768, min(32767, round(value)))))

    def u32(self, value):
        self.data.extend(struct.pack("<I", int(value) & 0xFFFFFFFF))

    def s32(self, value):
        self.data.extend(struct.pack("<i", int(value)))

    def string(self, value: str):
        encoded = value.encode("utf-8")
        self.u32(len(encoded))
        self.data.extend(encoded)

    def command(self, command_id: int):
        self.u32(command_id)

    def finish(self) -> bytes:
        return bytes(self.data)


class HM64MMHalfdayItem(PropertyGroup):
    value: EnumProperty(items=_HM64_MM_HALF_DAY, default="0-Dawn")
    value_custom: StringProperty(name="Custom", default="0x0000")

    def draw_props(self, layout: UILayout, owner_name: str, index: int):
        row = layout.row(align=True)
        row.prop(self, "value", text="")
        if self.value == "Custom":
            row.prop(self, "value_custom", text="")
        ops = row.row(align=True)
        add_op = ops.operator(HM64MMActorHalfdayAdd.bl_idname, text="", icon="ADD")
        add_op.obj_name = owner_name
        add_op.index = index + 1
        remove_op = ops.operator(HM64MMActorHalfdayRemove.bl_idname, text="", icon="REMOVE")
        remove_op.obj_name = owner_name
        remove_op.index = index
        move_up = ops.operator(HM64MMActorHalfdayMove.bl_idname, text="", icon="TRIA_UP")
        move_up.obj_name = owner_name
        move_up.index = index
        move_up.offset = -1
        move_down = ops.operator(HM64MMActorHalfdayMove.bl_idname, text="", icon="TRIA_DOWN")
        move_down.obj_name = owner_name
        move_down.index = index
        move_down.offset = 1


class HM64MMActorHalfdayAdd(Operator):
    bl_idname = "object.hm64_mm_actor_halfday_add"
    bl_label = "Add Spawn Schedule Entry"
    bl_options = {"REGISTER", "UNDO"}

    obj_name: StringProperty()
    index: IntProperty()

    def execute(self, context):
        collection = bpy.data.objects[self.obj_name].ootActorProperty.hm64_mm_halfday_bits
        item = collection.add()
        collection.move(len(collection) - 1, min(self.index, len(collection) - 1))
        if len(collection) == 1:
            item.value = "0-Dawn"
        context.region.tag_redraw()
        return {"FINISHED"}


class HM64MMActorHalfdayRemove(Operator):
    bl_idname = "object.hm64_mm_actor_halfday_remove"
    bl_label = "Remove Spawn Schedule Entry"
    bl_options = {"REGISTER", "UNDO"}

    obj_name: StringProperty()
    index: IntProperty()

    def execute(self, context):
        collection = bpy.data.objects[self.obj_name].ootActorProperty.hm64_mm_halfday_bits
        if 0 <= self.index < len(collection):
            collection.remove(self.index)
        context.region.tag_redraw()
        return {"FINISHED"}


class HM64MMActorHalfdayMove(Operator):
    bl_idname = "object.hm64_mm_actor_halfday_move"
    bl_label = "Move Spawn Schedule Entry"
    bl_options = {"REGISTER", "UNDO"}

    obj_name: StringProperty()
    index: IntProperty()
    offset: IntProperty()

    def execute(self, context):
        collection = bpy.data.objects[self.obj_name].ootActorProperty.hm64_mm_halfday_bits
        new_index = self.index + self.offset
        if 0 <= self.index < len(collection) and 0 <= new_index < len(collection):
            collection.move(self.index, new_index)
        context.region.tag_redraw()
        return {"FINISHED"}


class HM64SearchMMActorOperator(Operator):
    bl_idname = "object.hm64_search_mm_actor"
    bl_label = "Select MM Actor ID"
    bl_property = "actor_id"
    bl_options = {"REGISTER", "UNDO"}

    actor_id: EnumProperty(items=_HM64_MM_ACTOR_ITEMS)
    actor_user: StringProperty(default="Actor")
    obj_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects[self.obj_name]
        if self.actor_user == "Actor":
            _set_hm64_mm_actor_id(obj.ootActorProperty, self.actor_id)
        elif self.actor_user == "Transition Actor":
            _set_hm64_mm_actor_id(obj.ootTransitionActorProperty.actor, self.actor_id)
        elif self.actor_user == "Entrance":
            _set_hm64_mm_actor_id(obj.ootEntranceProperty.actor, self.actor_id)
        else:
            raise PluginError("Invalid actor user for MM search: " + str(self.actor_user))
        context.region.tag_redraw()
        self.report({"INFO"}, f"Selected: {self.actor_id}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}


class HM64SearchMMObjectOperator(Operator):
    bl_idname = "object.hm64_search_mm_object"
    bl_label = "Select MM Object ID"
    bl_property = "object_key"
    bl_options = {"REGISTER", "UNDO"}

    object_key: EnumProperty(items=_HM64_MM_OBJECT_ITEMS)
    header_index: IntProperty(default=0, min=0)
    index: IntProperty(default=0, min=0)
    obj_name: StringProperty()

    def execute(self, context):
        from ...utility import ootGetSceneOrRoomHeader

        room_header = ootGetSceneOrRoomHeader(bpy.data.objects[self.obj_name], self.header_index, True)
        _set_hm64_mm_object_key(room_header.objectList[self.index], self.object_key)
        context.region.tag_redraw()
        self.report({"INFO"}, f"Selected: {self.object_key}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}


def _number(value, field: str) -> int:
    global _OOT_ACTORS
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    text = str(value).strip()
    if text in _MM_ROOM_TYPES:
        return _MM_ROOM_TYPES[text]
    if text in _OOT_SCENE_CAMERA_TYPES:
        return _OOT_SCENE_CAMERA_TYPES[text]
    try:
        return hexOrDecInt(text)
    except Exception:
        pass
    if re.fullmatch(r"[0-9a-fA-FxX()<>|&~+\-*/\s]+", text):
        result = getEvalParamsInt(text)
        if result is not None:
            return result
    for enum in game_data.z64.enums.enumByKey.values():
        for item in enum.item_by_key.values():
            if text == item.id or text == getattr(item, "key", None):
                return item.index
    for item in game_data.z64.objects.objects_by_key.values():
        if text == item.id:
            return item.index
    if text.startswith("ACTOR_"):
        if _OOT_ACTORS is None:
            _OOT_ACTORS = Z64_ActorData("OOT").actorsByID
        actor = _OOT_ACTORS.get(text)
        if actor is not None:
            return actor.index
    for enum in (*game_data.z64.enum_map.values(), *_SCENE_ENUMS):
        for index, entry in enumerate(enum):
            if len(entry) >= 3 and text in entry:
                try:
                    return hexOrDecInt(entry[0])
                except Exception:
                    try:
                        return hexOrDecInt(entry[2])
                    except Exception:
                        return max(0, index - 1)
    raise PluginError(f"HM64 scene export requires numeric {field}, got '{text}'.")


def _mm_actor_items(actor_user: str = "Actor"):
    if actor_user == "Transition Actor":
        return _HM64_MM_TRANSITION_ACTOR_ITEMS
    if actor_user == "Entrance":
        return _HM64_MM_ENTRANCE_ACTOR_ITEMS
    return _HM64_MM_ACTOR_ITEMS


def _set_hm64_mm_actor_id(props, actor_id: str):
    props.actor_id = "Custom"
    props.actor_id_custom = actor_id


def _mm_actor_get(props):
    actor_id = props.actor_id_custom if props.actor_id == "Custom" else props.actor_id
    return next((index for index, item in enumerate(_mm_actor_items()) if item[0] == actor_id), 0)


def _mm_actor_set(props, index):
    _set_hm64_mm_actor_id(props, _mm_actor_items()[index][0])


def _mm_object_items():
    return _HM64_MM_OBJECT_ITEMS


def _mm_object_key_from_id(value: str):
    objects = Z64_ObjectData("MM")
    object_data = objects.objects_by_id.get(value) or objects.objects_by_key.get(value)
    return object_data.key if object_data is not None else None


def _set_hm64_mm_object_key(props, object_key: str):
    key = _mm_object_key_from_id(object_key) or object_key
    props.objectKey = "Custom"
    props.objectIDCustom = key


def _mm_object_get(props):
    key = props.objectIDCustom if props.objectKey == "Custom" else props.objectKey
    key = _mm_object_key_from_id(key) or key
    return next((index for index, item in enumerate(_mm_object_items()) if item[0] == key), 0)


def _mm_object_set(props, index):
    _set_hm64_mm_object_key(props, _mm_object_items()[index][0])


def _binary_angle(value) -> int:
    text = str(value).strip()
    match = re.fullmatch(r"DEG_TO_BINANG\(([-+0-9.]+)\)", text)
    if match is not None:
        return round(float(match.group(1)) * 0x8000 / 180.0)
    return _number(text, "actor rotation")


def _exit_index(value) -> int:
    global _entrance_indices
    text = str(value).strip()
    try:
        return _number(text, "exit index")
    except PluginError:
        if not text.startswith("ENTR_"):
            raise
    if _entrance_indices is None:
        decomp_path = bpy.path.abspath(bpy.context.scene.ootDecompPath)
        table_path = Path(decomp_path) / "include" / "tables" / "entrance_table.h"
        if not table_path.is_file():
            raise PluginError(
                "Set an OoT decomp path containing include/tables/entrance_table.h to export named scene exits."
            )
        _entrance_indices = {
            symbol: int(index, 16)
            for index, symbol in _ENTRANCE_INDEX_RE.findall(table_path.read_text(encoding="utf-8"))
        }
    if text not in _entrance_indices:
        raise PluginError(f"Entrance symbol '{text}' was not found in entrance_table.h.")
    return _entrance_indices[text]


def _hm64_mm_halfday_bits(actor_props) -> int:
    if getattr(actor_props, "hm64_mm_halfday_all", True):
        return _HM64_MM_HALFDAY_ALL
    bits = 0
    if getattr(actor_props, "hm64_mm_halfday_all_dawns", False):
        bits |= _HM64_MM_HALFDAY_ALL_DAWNS
    if getattr(actor_props, "hm64_mm_halfday_all_nights", False):
        bits |= _HM64_MM_HALFDAY_ALL_NIGHTS
    if bits:
        return bits
    for item in getattr(actor_props, "hm64_mm_halfday_bits", []):
        if item.value == "Custom":
            bits |= _number(item.value_custom, "spawn schedule")
        else:
            bits |= _HM64_MM_HALFDAY_BITS.get(item.value, 0)
    return bits


def _set_hm64_mm_halfday_bits(actor_props, bits: int):
    actor_props.hm64_mm_halfday_bits.clear()
    bits &= _HM64_MM_HALFDAY_ALL
    actor_props.hm64_mm_halfday_all = bits == _HM64_MM_HALFDAY_ALL
    actor_props.hm64_mm_halfday_all_dawns = not actor_props.hm64_mm_halfday_all and bits == _HM64_MM_HALFDAY_ALL_DAWNS
    actor_props.hm64_mm_halfday_all_nights = not actor_props.hm64_mm_halfday_all and bits == _HM64_MM_HALFDAY_ALL_NIGHTS
    if (
        actor_props.hm64_mm_halfday_all
        or actor_props.hm64_mm_halfday_all_dawns
        or actor_props.hm64_mm_halfday_all_nights
    ):
        return
    actor_props.hm64_mm_halfday_show_entries = True
    for value, flag in _HM64_MM_HALFDAY_BITS.items():
        if bits & flag:
            item = actor_props.hm64_mm_halfday_bits.add()
            item.value = value


def _hm64_mm_pack_actor_rotation(rotation: list[int], actor_obj):
    if actor_obj is None or actor_obj.type != "EMPTY" or actor_obj.ootEmptyType != "Actor":
        return rotation
    actor_props = actor_obj.ootActorProperty
    halfday_bits = _hm64_mm_halfday_bits(actor_props)
    cs_index = getattr(actor_props, "hm64_mm_actor_cs_index", 0x7F) & 0x7F
    flags = ((halfday_bits >> 7) & 0x07, cs_index, halfday_bits & 0x7F)
    masks = (~0x07, ~0x7F, ~0x7F)
    return [(value & mask) | flag for value, mask, flag in zip(rotation, masks, flags)]


def _actor_entry(writer: _Writer, actor, actor_obj=None):
    writer.u16(_actor_id(actor.id))
    for value in actor.pos:
        writer.s16(value)
    rotation = [_binary_angle(value) for value in str(actor.rot).split(",")]
    if hm64_mm_features_enabled():
        rotation = _hm64_mm_pack_actor_rotation(rotation, actor_obj)
    for value in rotation:
        writer.s16(value)
    params = str(actor.params).strip()
    writer.u16(0 if not params else _number(params, "actor parameters"))


def _mm_start_position_entry(writer: _Writer, actor, source_entry: bytes | None):
    if source_entry is not None and len(source_entry) == 16:
        source = struct.unpack("<H3h3hH", source_entry)
        writer.u16(_actor_id(actor.id))
        for value in actor.pos:
            writer.s16(value)
        for value in source[4:7]:
            writer.s16(value)
        writer.u16(source[7])
    else:
        _actor_entry(writer, actor)


def _actor_id(value) -> int:
    global _OOT_ACTORS, _MM_ACTORS, _oot_actor_ids
    text = str(value).strip()
    if hm64_mm_features_enabled():
        if _MM_ACTORS is None:
            _MM_ACTORS = Z64_ActorData("MM").actorsByID
        actor_id = 0
        for term in (part.strip() for part in text.split("|")):
            actor = _MM_ACTORS.get(term)
            if actor is not None:
                actor_id |= actor.index
            else:
                try:
                    actor_id |= hexOrDecInt(term)
                except Exception as exc:
                    raise PluginError(f"HM64 scene export requires a known MM actor, got '{text}'.") from exc
        return actor_id
    if _oot_actor_ids is None:
        decomp_path = Path(bpy.path.abspath(bpy.context.scene.ootDecompPath))
        table_path = decomp_path / "include" / "tables" / "actor_table.h"
        if not table_path.is_file():
            raise PluginError("Set an OoT decomp path containing include/tables/actor_table.h to export scene actors.")
        _oot_actor_ids = {
            symbol: int(index, 16) for index, symbol in _ACTOR_ID_RE.findall(table_path.read_text(encoding="utf-8"))
        }
    if text in _oot_actor_ids:
        return _oot_actor_ids[text]
    try:
        ui_index = hexOrDecInt(text)
    except Exception:
        raise PluginError(f"HM64 scene export requires a known OoT actor, got '{text}'.")
    if _OOT_ACTORS is None:
        _OOT_ACTORS = Z64_ActorData("OOT").actorsByID
    actor = next((actor for actor in _OOT_ACTORS.values() if actor.index == ui_index), None)
    if actor is not None and actor.id in _oot_actor_ids:
        return _oot_actor_ids[actor.id]
    return ui_index


def _light_entry(writer: _Writer, light):
    for value in light.ambientColor:
        writer.u8(value)
    for value in light.light1Dir:
        writer.u8(value)
    for value in light.light1Color:
        writer.u8(value)
    for value in light.light2Dir:
        writer.u8(value)
    for value in light.light2Color:
        writer.u8(value)
    for value in light.fogColor:
        writer.u8(value)
    writer.u16(((light.blendRate // 4) << 10) | light.fogNear)
    writer.u16(light.zFar)


def _light_settings(header, source_commands) -> list:
    settings = header.lighting.settings
    source_settings = _source_entries(source_commands.get(_CMD["LIGHTING"]), 22)
    if (
        header.lighting.envLightMode == "LIGHT_MODE_TIME"
        and source_settings
        and len(settings) == len(source_settings) * 4
    ):
        return source_settings
    return settings


def _surface_words(surface) -> tuple[int, int]:
    data0 = (
        (_number(surface.bgCamIndex, "camera ID") & 0xFF)
        | ((_number(surface.exitIndex, "exit ID") & 0x1F) << 8)
        | ((_number(surface.floorType, "floor type") & 0x1F) << 13)
        | ((_number(surface.unk18, "surface unknown") & 7) << 18)
        | ((_number(surface.wallType, "wall type") & 0x1F) << 21)
        | ((_number(surface.floorProperty, "floor property") & 0xF) << 26)
        | ((int(bool(surface.isSoft)) & 1) << 30)
        | ((int(bool(surface.isHorseBlocked)) & 1) << 31)
    )
    data1 = (
        (_number(surface.material, "surface material") & 0xF)
        | ((_number(surface.floorEffect, "floor effect") & 3) << 4)
        | ((_number(surface.lightSetting, "light setting") & 0x1F) << 6)
        | ((_number(surface.echo, "surface echo") & 0x3F) << 11)
        | ((int(bool(surface.canHookshot)) & 1) << 17)
        | ((_number(surface.conveyorSpeed, "conveyor speed") & 7) << 18)
        | ((_number(surface.conveyorDirection, "conveyor direction") & 0x3F) << 21)
        | ((int(bool(surface.isWallDamage)) & 1) << 27)
    )
    return data0, data1


def _write_collision(collision) -> bytes:
    writer = _Writer(b"LOCO")
    for bounds in (collision.minBounds, collision.maxBounds):
        for value in bounds:
            writer.s16(value)
    writer.s32(len(collision.vertices.vertexList))
    for vertex in collision.vertices.vertexList:
        for value in vertex.pos:
            writer.s16(value)
    writer.u32(len(collision.collisionPoly.polyList))
    for poly in collision.collisionPoly.polyList:
        writer.u16(poly.type)
        writer.u16(
            (poly.indices[0] & 0x1FFF)
            | ((int(poly.ignoreCamera) | (int(poly.ignoreEntity) << 1) | (int(poly.ignoreProjectile) << 2)) << 13)
        )
        writer.u16((poly.indices[1] & 0x1FFF) | (int(poly.isLandConveyor) << 13))
        writer.u16(poly.indices[2] & 0x1FFF)
        for value in poly.normal:
            writer.s16(round(value * 0x7FFF))
        writer.s16(poly.dist)
    writer.u32(len(collision.surfaceType.surfaceTypeList))
    for surface in collision.surfaceType.surfaceTypeList:
        data0, data1 = _surface_words(surface)
        writer.u32(data1)
        writer.u32(data0)

    camera_table = collision.bgCamInfo.camFromIndex
    if camera_table:
        writer.s32(len(camera_table))
        for camera in camera_table.values():
            writer.u16(_number(camera.setting, "camera setting"))
            writer.s16(camera.count)
            writer.s32(camera.arrayIndex)
    else:
        writer.s32(1)
        writer.u16(0)
        writer.s16(0)
        writer.s32(0)

    camera_positions = []
    for camera in camera_table.values():
        if hasattr(camera, "points"):
            camera_positions.extend(camera.points)
        elif camera.hasPosData:
            camera_positions.extend(
                (camera.data.pos, camera.data.rot, (camera.data.fov, camera.data.roomImageOverrideBgCamIndex, -1))
            )
    writer.s32(len(camera_positions))
    for position in camera_positions:
        for value in position:
            writer.s16(value)
    writer.s32(len(collision.waterbox.waterboxList))
    for water in collision.waterbox.waterboxList:
        for value in (water.xMin, water.ySurface, water.zMin, water.xLength, water.zLength):
            writer.s16(value)
        properties = (
            (_number(water.bgCamIndex, "water box camera") & 0xFF)
            | ((_number(water.lightIndex, "water box light") & 0x1F) << 8)
            | ((_number(water.roomIndexC, "water box room") & 0x3F) << 13)
            | ((int(_number(water.setFlag19C, "water box flag")) & 1) << 19)
        )
        writer.u32(properties)
    return writer.finish()


def _write_pathways(pathways, is_mm: bool = False) -> bytes:
    writer = _Writer(b"HTPO")
    writer.u32(len(pathways.pathList))
    for path in pathways.pathList:
        writer.u32(len(path.points))
        if is_mm:
            writer.u8(getattr(path, "hm64_mm_additional_path_index", 0))
            writer.s16(getattr(path, "hm64_mm_custom_value", 0))
        for point in path.points:
            for value in point:
                writer.s16(value)
    return writer.finish()


def _room_mesh_groups(room, directory: str, internal_directory: str):
    shape = room.roomShape
    shape_type = shape.get_type()
    if shape_type not in {"ROOM_SHAPE_TYPE_NORMAL", "ROOM_SHAPE_TYPE_CULLABLE"}:
        raise PluginError("HM64 scene export does not yet support background-image room shapes.")
    model = shape.model
    model.to_soh_xml(directory, internal_directory, include_cull_vertices=False)
    groups = []
    for entry in shape.dl_entries:
        paths = []
        for display_list in (entry.opaque, entry.transparent):
            if display_list is None:
                paths.append("")
                continue
            xml = display_list.to_soh_xml(directory, internal_directory)
            writeXMLData(xml, os.path.join(directory, display_list.name))
            paths.append(f"{internal_directory}/{display_list.name}")
        groups.append((*paths, entry))
    return shape_type, groups


def _write_alternate_headers(writer: _Writer, paths: list[str | None]):
    writer.command(_CMD["ALTERNATE_HEADERS"])
    writer.u32(len(paths))
    for path in paths:
        writer.string(path or "")


def _write_room_header(
    header,
    shape_type,
    groups,
    alternate_paths: list[str | None] | None = None,
    source_header: bytes | None = None,
    actor_objects=None,
    source_indices: set[int] | None = None,
) -> bytes:
    infos = header.infos
    actor_objects = actor_objects or []
    writer = _Writer(b"MORO")
    source_commands = _header_commands(source_header)
    source_wind = source_commands.get(_CMD["WIND"])
    source_objects = source_commands.get(_CMD["OBJECTS"])
    source_actors = _source_entries(source_commands.get(_CMD["ACTORS"]), 16)
    actors = _merge_room_actors(source_actors, header.actors.actorList, actor_objects or [], source_indices or set())
    writer.u32(8 + int(alternate_paths is not None) + int(source_wind is not None and len(source_wind) == 4))
    if alternate_paths is not None:
        _write_alternate_headers(writer, alternate_paths)
    writer.command(_CMD["ROOM_BEHAVIOR"])
    writer.s8(_number(infos.roomBehavior, "room behavior"))
    if _HM64_SCENE_IS_OOT:
        writer.s32(_number(infos.playerIdleType, "player idle type"))
    else:
        for _ in range(5):
            writer.s8(0)
    writer.command(_CMD["ECHO"])
    writer.s8(_number(infos.echo, "room echo"))
    writer.command(_CMD["TIME"])
    writer.u8(infos.hour)
    writer.u8(infos.minute)
    writer.u8(infos.timeSpeed)
    writer.command(_CMD["SKYBOX_MODIFIER"])
    writer.u8(infos.disableSky)
    writer.u8(infos.disableSunMoon)
    if source_wind is not None and len(source_wind) == 4:
        writer.command(_CMD["WIND"])
        writer.data.extend(source_wind)
    writer.command(_CMD["OBJECTS"])
    object_ids = _merge_room_objects(source_objects, header.objects.objectList)
    writer.u32(len(object_ids))
    for object_id in object_ids:
        writer.u16(object_id)
    writer.command(_CMD["ACTORS"])
    writer.u32(len(actors))
    for actor_index, actor in enumerate(actors):
        if isinstance(actor, bytes):
            writer.data.extend(actor)
        else:
            _actor_entry(writer, actor, actor_objects[actor_index] if actor_index < len(actor_objects) else None)
    writer.command(_CMD["MESH"])
    writer.s8(0)
    writer.s8(2 if shape_type == "ROOM_SHAPE_TYPE_CULLABLE" else 0)
    writer.u8(len(groups))
    for opaque, transparent, entry in groups:
        writer.s8(0)
        if shape_type == "ROOM_SHAPE_TYPE_CULLABLE":
            for value in entry.bounds_sphere_center:
                writer.s16(value)
            writer.s16(entry.bounds_sphere_radius)
        writer.string(opaque)
        writer.string(transparent)
    writer.command(_CMD["END"])
    return writer.finish()


def _room_header_variants(room):
    headers = [room.mainHeader]
    if room.altHeader is None:
        return headers
    headers.extend([room.altHeader.childNight, room.altHeader.adultDay, room.altHeader.adultNight])
    headers.extend(room.altHeader.cutscenes)
    return headers


def _mm_room_header_variants(room):
    return _room_header_variants(room)


def _write_room(
    room,
    directory: str,
    internal_directory: str,
    source_headers: list[bytes | None] | None = None,
    actor_objects_by_header: dict[int, list] | None = None,
    source_indices_by_header: dict[int, set[int]] | None = None,
) -> dict[str, bytes]:
    shape_type, groups = _room_mesh_groups(room, directory, internal_directory)
    headers = _room_header_variants(room)
    paths = [
        f"{internal_directory}/{room.name}Header_{index:02}" if header is not None else None
        for index, header in enumerate(headers[1:], 1)
    ]
    source_headers = source_headers or []
    actor_objects_by_header = actor_objects_by_header or {}
    source_indices_by_header = source_indices_by_header or {}
    files = {
        room.name: _write_room_header(
            room.mainHeader,
            shape_type,
            groups,
            paths if len(headers) > 1 else None,
            source_headers[0] if source_headers else None,
            actor_objects_by_header.get(0),
            source_indices_by_header.get(0),
        )
    }
    for index, header in enumerate(headers[1:], 1):
        if header is not None:
            files[f"{room.name}Header_{index:02}"] = _write_room_header(
                header,
                shape_type,
                groups,
                source_header=source_headers[index] if index < len(source_headers) else None,
                actor_objects=actor_objects_by_header.get(index),
                source_indices=source_indices_by_header.get(index),
            )
    return files


def _header_commands(data: bytes) -> dict[int, bytes]:
    if data is None or len(data) < _RESOURCE_HEADER_SIZE + 4:
        return {}
    try:
        count = struct.unpack_from("<I", data, _RESOURCE_HEADER_SIZE)[0]
        cursor = _RESOURCE_HEADER_SIZE + 4
        commands = {}
        for _ in range(count):
            command = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
            start = cursor
            if command in (_CMD["START_POSITIONS"], _CMD["ACTORS"]):
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 16
            elif command == _CMD["COLLISION"]:
                cursor = _read_resource_string(data, cursor)[1]
            elif command == _CMD["ROOMS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1] + 8
            elif command == _CMD["ENTRANCES"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command in (_CMD["WIND"], _CMD["SKYBOX"]):
                cursor += 4
            elif command == _CMD["SPECIAL_OBJECTS"]:
                cursor += 3
            elif command in (_CMD["ROOM_BEHAVIOR"], _CMD["CAMERA_SETTINGS"]):
                cursor += 5
            elif command == _CMD["MESH"]:
                shape_type = data[cursor + 1]
                entries = data[cursor + 2]
                cursor += 3
                for _ in range(entries):
                    cursor += 1 + (8 if shape_type == 2 else 0)
                    cursor = _read_resource_string(data, cursor)[1]
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _CMD["OBJECTS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command == _CMD["PATHWAYS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _CMD["TRANSITIONS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 16
            elif command == _CMD["LIGHTING"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 22
            elif command == _CMD["TIME"]:
                cursor += 3
            elif command == _CMD["SKYBOX_MODIFIER"]:
                cursor += 2
            elif command == _CMD["EXITS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command in (_CMD["SOUND"],):
                cursor += 3
            elif command == _CMD["ECHO"]:
                cursor += 1
            elif command == _CMD["CUTSCENES"]:
                cursor = _read_resource_string(data, cursor)[1]
            elif command == _CMD["ALTERNATE_HEADERS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _CMD["END"]:
                commands[command] = data[start:cursor]
                break
            else:
                return {}
            if cursor > len(data):
                return {}
            commands[command] = data[start:cursor]
        return commands
    except (IndexError, struct.error, TypeError):
        return {}


def _source_entries(payload: bytes | None, entry_size: int) -> list[bytes]:
    if payload is None or len(payload) < 4:
        return []
    count = struct.unpack_from("<I", payload)[0]
    if len(payload) != 4 + count * entry_size:
        return []
    return [payload[4 + index * entry_size : 4 + (index + 1) * entry_size] for index in range(count)]


def _merge_room_objects(source_objects: bytes | None, object_names) -> list[int]:
    object_ids = [struct.unpack("<H", entry)[0] for entry in _source_entries(source_objects, 2)]
    for object_name in object_names:
        object_id = O2R_OBJECT_IDS.get(str(object_name))
        if object_id is None:
            try:
                object_id = hexOrDecInt(str(object_name))
            except ValueError:
                continue
        if object_id not in object_ids:
            object_ids.append(object_id)
    return object_ids


def _merge_room_objects_mm(source_objects: bytes | None, object_names) -> list[int]:
    object_ids = [struct.unpack("<H", entry)[0] for entry in _source_entries(source_objects, 2)]
    objects = Z64_ObjectData("MM")
    for object_name in object_names:
        object_data = objects.objects_by_id.get(str(object_name)) or objects.objects_by_key.get(str(object_name))
        if object_data is not None and object_data.index not in object_ids:
            object_ids.append(object_data.index)
    return object_ids


def _room_actor_objects(scene_obj, room_obj, header_index: int):
    actors = getObjectList(
        scene_obj.children,
        "EMPTY",
        "Actor",
        parentObj=room_obj,
        room_index=room_obj.ootRoomHeader.roomIndex,
    )
    return [
        actor
        for actor in actors
        if actor.ootActorProperty.actor_id != "None"
        and _hm64_is_current_header_valid(actor.ootActorProperty.headerSettings, header_index)
    ]


def _hm64_is_current_header_valid(header_settings, header_index: int):
    if not hm64_mm_features_enabled():
        return Utility.isCurrentHeaderValid(header_settings, header_index)
    if getattr(header_settings, "hm64_mm_include_in_all_setups", True):
        return True
    if header_index == 0:
        return bool(header_settings.childDayHeader)
    return any(header.headerIndex == header_index for header in header_settings.cutsceneHeaders)


@contextmanager
def _use_hm64_mm_header_visibility():
    original = Utility.isCurrentHeaderValid
    Utility.isCurrentHeaderValid = staticmethod(_hm64_is_current_header_valid)
    try:
        yield
    finally:
        Utility.isCurrentHeaderValid = original


def _exported_source_actor_indices(actors, actor_objects) -> set[int]:
    indices = set()
    for actor_obj in actor_objects[: len(actors)]:
        ref = actor_obj.get(_HM64_ACTOR_REF)
        if not isinstance(ref, str):
            continue
        try:
            indices.add(int(ref.rsplit(":", 1)[1]))
        except ValueError:
            continue
    return indices


def _merge_room_actors(source_actors: list[bytes], actors, actor_objects, source_indices: set[int]):
    if not any(actor_obj.get(_HM64_ACTOR_REF) for actor_obj in actor_objects):
        actors = list(actors)
        if len(actors) < len(source_actors):
            actors.extend(source_actors[len(actors) :])
        return actors
    ordered = [None] * len(source_actors)
    appended = []
    for actor, actor_obj in zip(actors, actor_objects):
        ref = actor_obj.get(_HM64_ACTOR_REF)
        if isinstance(ref, str):
            try:
                room_index, header_index, source_index = (int(value) for value in ref.split(":"))
            except ValueError:
                source_index = -1
        else:
            source_index = -1
        if 0 <= source_index < len(ordered) and ordered[source_index] is None:
            ordered[source_index] = actor
        else:
            appended.append(actor)
    for index, source_actor in enumerate(source_actors):
        if ordered[index] is None and index not in source_indices:
            ordered[index] = source_actor
    return [actor for actor in ordered if actor is not None] + appended


def _write_scene_header(
    header,
    room_paths: list[str],
    collision_path: str,
    cutscene_path: str | None,
    pathway_path: str | None,
    alternate_paths: list[str | None] | None = None,
    has_camera_settings: bool | None = None,
    source_header: bytes | None = None,
) -> bytes:
    infos = header.infos
    transitions = header.transitionActors.entries
    writer = _Writer(b"MORO")
    if has_camera_settings is None:
        has_camera_settings = _HM64_SCENE_IS_OOT
    source_commands = _header_commands(source_header)
    source_entrances = _source_entries(source_commands.get(_CMD["ENTRANCES"]), 2)
    source_spawns = _source_entries(source_commands.get(_CMD["START_POSITIONS"]), 16)
    entrances = [(entry.spawnIndex, entry.roomIndex) for entry in header.spawns.entries]
    spawns = list(header.entranceActors.entries)
    if len(entrances) < len(source_entrances):
        entrances.extend(struct.unpack("<BB", entry) for entry in source_entrances[len(entrances) :])
    if len(spawns) < len(source_spawns):
        spawns.extend(source_spawns[len(spawns) :])
    writer.u32(
        10
        + int(cutscene_path is not None)
        + int(pathway_path is not None)
        + int(has_camera_settings)
        + (1 if transitions else 0)
        + int(alternate_paths is not None)
    )
    if alternate_paths is not None:
        _write_alternate_headers(writer, alternate_paths)
    writer.command(_CMD["SPECIAL_OBJECTS"])
    source_special_objects = source_commands.get(_CMD["SPECIAL_OBJECTS"])
    if source_special_objects is not None and len(source_special_objects) == 3:
        writer.data.extend(source_special_objects)
    else:
        writer.s8(_number(infos.naviHintType, "Navi hint"))
        writer.u16(_number(infos.keepObjectID, "global object"))
    writer.command(_CMD["COLLISION"])
    writer.string(collision_path)
    writer.command(_CMD["ROOMS"])
    writer.u32(len(room_paths))
    for room_path in room_paths:
        writer.string(room_path)
        writer.s32(0)
        writer.s32(0)
    writer.command(_CMD["ENTRANCES"])
    writer.u32(len(entrances))
    for spawn_index, room_index in entrances:
        writer.u8(spawn_index)
        writer.u8(room_index)
    writer.command(_CMD["START_POSITIONS"])
    writer.u32(len(spawns))
    for actor in spawns:
        if isinstance(actor, bytes):
            writer.data.extend(actor)
        else:
            _actor_entry(writer, actor)
    if pathway_path is not None:
        writer.command(_CMD["PATHWAYS"])
        writer.u32(1)
        writer.string(pathway_path)
    if transitions:
        writer.command(_CMD["TRANSITIONS"])
        writer.u32(len(transitions))
        for actor in transitions:
            writer.s8(actor.roomFrom)
            writer.u8(_number(actor.cameraFront, "transition camera"))
            writer.s8(actor.roomTo)
            writer.u8(_number(actor.cameraBack, "transition camera"))
            writer.u16(_actor_id(actor.id))
            for value in actor.pos:
                writer.s16(value)
            writer.s16(_binary_angle(actor.rot))
            writer.u16(_number(actor.params, "transition actor parameters"))
    writer.command(_CMD["SKYBOX"])
    writer.s8(0)
    writer.s8(_number(infos.skyboxID, "skybox ID"))
    writer.s8(_number(infos.skyboxConfig, "skybox config"))
    writer.s8(_number(header.lighting.envLightMode, "skybox lighting mode"))
    writer.command(_CMD["LIGHTING"])
    light_settings = _light_settings(header, source_commands)
    writer.u32(len(light_settings))
    for light in light_settings:
        if isinstance(light, bytes):
            writer.data.extend(light)
        else:
            _light_entry(writer, light)
    writer.command(_CMD["EXITS"])
    writer.u32(len(header.exits.exitList))
    for _, exit_index in header.exits.exitList:
        writer.u16(_exit_index(exit_index))
    writer.command(_CMD["SOUND"])
    writer.s8(_number(infos.specID, "audio session preset"))
    writer.s8(_number(infos.ambienceID, "night ambience"))
    writer.s8(_number(infos.sequenceID, "music sequence"))
    if cutscene_path is not None:
        writer.command(_CMD["CUTSCENES"])
        writer.string(cutscene_path)
    if has_camera_settings:
        writer.command(_CMD["CAMERA_SETTINGS"])
        writer.s8(_number(infos.sceneCamType, "scene camera mode"))
        writer.s32(_number(infos.worldMapLocation, "world map location"))
    writer.command(_CMD["END"])
    return writer.finish()


def _mm_header_commands(data: bytes) -> dict[int, bytes]:
    if data is None or len(data) < _RESOURCE_HEADER_SIZE + 4:
        return {}
    try:
        count = struct.unpack_from("<I", data, _RESOURCE_HEADER_SIZE)[0]
        cursor = _RESOURCE_HEADER_SIZE + 4
        commands = {}
        for _ in range(count):
            command = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
            start = cursor
            if command in (_MM_CMD["START_POSITIONS"], _MM_CMD["ACTORS"]):
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 16
            elif command == _MM_CMD["COLLISION"]:
                cursor = _read_resource_string(data, cursor)[1]
            elif command == _MM_CMD["ROOMS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1] + 8
            elif command == _MM_CMD["ENTRANCES"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command in (_MM_CMD["WIND"], _MM_CMD["SKYBOX"]):
                cursor += 4
            elif command == _MM_CMD["SPECIAL_OBJECTS"]:
                cursor += 3
            elif command == _MM_CMD["ROOM_BEHAVIOR"]:
                cursor += 6
            elif command == _MM_CMD["WORLD_MAP_VISITED"]:
                pass
            elif command == 0x02:  # CsCamera: settings plus a Vec3s array per entry.
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor += 4 + struct.unpack_from("<H", data, cursor + 2)[0] * 6
            elif command == _MM_CMD["MESH"]:
                shape_type = data[cursor + 1]
                entries = data[cursor + 2]
                cursor += 3
                for _ in range(entries):
                    cursor += 1 + (8 if shape_type == 2 else 0)
                    cursor = _read_resource_string(data, cursor)[1]
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _MM_CMD["OBJECTS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command == _MM_CMD["PATHWAYS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _MM_CMD["TRANSITIONS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 16
            elif command == _MM_CMD["LIGHTING"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 22
            elif command == _MM_CMD["TIME"]:
                cursor += 3
            elif command == _MM_CMD["SKYBOX_MODIFIER"]:
                cursor += 2
            elif command == _MM_CMD["EXITS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 2
            elif command == _MM_CMD["SOUND"]:
                cursor += 3
            elif command == _MM_CMD["ECHO"]:
                cursor += 1
            elif command == _MM_CMD["ALTERNATE_HEADERS"]:
                entries = struct.unpack_from("<I", data, cursor)[0]
                cursor += 4
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1]
            elif command == _MM_CMD["ANIMATED_MATERIALS"]:
                cursor = _read_resource_string(data, cursor)[1]
            elif command == _MM_CMD["ACTOR_CUTSCENES"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 16
            elif command == _MM_CMD["MINIMAP"]:
                cursor += 6 + struct.unpack_from("<I", data, cursor)[0] * 10
            elif command == _MM_CMD["MINIMAP_CHESTS"]:
                cursor += 4 + struct.unpack_from("<I", data, cursor)[0] * 10
            elif command == _MM_CMD["CUTSCENES"]:
                entries = data[cursor]
                cursor += 1
                for _ in range(entries):
                    cursor = _read_resource_string(data, cursor)[1] + 4
            elif command == _MM_CMD["END"]:
                commands[command] = data[start:cursor]
                break
            else:
                return {}
            if cursor > len(data):
                return {}
            commands[command] = data[start:cursor]
        return commands
    except (IndexError, struct.error, TypeError):
        return {}


def _write_room_header_mm(
    header,
    shape_type,
    groups,
    alternate_paths: list[str | None] | None = None,
    source_header: bytes | None = None,
    actor_objects=None,
    source_indices: set[int] | None = None,
) -> bytes:
    infos = header.infos
    actor_objects = actor_objects or []
    writer = _Writer(b"MORO")
    source_commands = _mm_header_commands(source_header)
    source_wind = source_commands.get(_MM_CMD["WIND"])
    source_behavior = bytearray(source_commands.get(_MM_CMD["ROOM_BEHAVIOR"], b"\0" * 6))
    if len(source_behavior) != 6:
        source_behavior = bytearray(6)
    source_objects = source_commands.get(_MM_CMD["OBJECTS"])
    source_actors = _source_entries(source_commands.get(_MM_CMD["ACTORS"]), 16)
    actors = _merge_room_actors(source_actors, header.actors.actorList, actor_objects or [], source_indices or set())
    writer.u32(8 + int(alternate_paths is not None) + int(source_wind is not None and len(source_wind) == 4))
    if alternate_paths is not None:
        _write_alternate_headers(writer, alternate_paths)
    source_behavior[0] = _number(infos.roomBehavior, "room behavior") & 0xFF
    source_behavior[1] = _number(infos.playerIdleType, "player idle type") & 0xFF
    source_behavior[2] = int(infos.showInvisActors)
    source_behavior[3] = int(infos.disableWarpSongs)
    source_behavior[4] = int(getattr(infos, "hm64_mm_enable_pos_lights", False))
    source_behavior[5] = int(getattr(infos, "hm64_mm_enable_storm", False))
    writer.command(_MM_CMD["ROOM_BEHAVIOR"])
    writer.data.extend(source_behavior)
    writer.command(_MM_CMD["ECHO"])
    writer.s8(_number(infos.echo, "room echo"))
    writer.command(_MM_CMD["TIME"])
    writer.u8(infos.hour)
    writer.u8(infos.minute)
    writer.u8(infos.timeSpeed)
    writer.command(_MM_CMD["SKYBOX_MODIFIER"])
    writer.u8(infos.disableSky)
    writer.u8(infos.disableSunMoon)
    if source_wind is not None and len(source_wind) == 4:
        writer.command(_MM_CMD["WIND"])
        writer.data.extend(source_wind)
    writer.command(_MM_CMD["OBJECTS"])
    object_ids = _merge_room_objects_mm(source_objects, header.objects.objectList)
    writer.u32(len(object_ids))
    for object_id in object_ids:
        writer.u16(object_id)
    writer.command(_MM_CMD["ACTORS"])
    writer.u32(len(actors))
    for actor_index, actor in enumerate(actors):
        if isinstance(actor, bytes):
            writer.data.extend(actor)
        else:
            _actor_entry(writer, actor, actor_objects[actor_index] if actor_index < len(actor_objects) else None)
    writer.command(_MM_CMD["MESH"])
    writer.s8(0)
    writer.s8(2 if shape_type == "ROOM_SHAPE_TYPE_CULLABLE" else 0)
    writer.u8(len(groups))
    for opaque, transparent, entry in groups:
        writer.s8(0)
        if shape_type == "ROOM_SHAPE_TYPE_CULLABLE":
            for value in entry.bounds_sphere_center:
                writer.s16(value)
            writer.s16(entry.bounds_sphere_radius)
        writer.string(opaque)
        writer.string(transparent)
    writer.command(_MM_CMD["END"])
    return writer.finish()


def _write_room_mm(
    room,
    directory,
    internal_directory,
    source_headers=None,
    actor_objects_by_header=None,
    source_indices_by_header=None,
):
    shape_type, groups = _room_mesh_groups(room, directory, internal_directory)
    headers = _mm_room_header_variants(room)
    paths = [
        f"{internal_directory}/{room.name}Header_{index:02}" if header is not None else None
        for index, header in enumerate(headers[1:], 1)
    ]
    source_headers = source_headers or []
    actor_objects_by_header = actor_objects_by_header or {}
    source_indices_by_header = source_indices_by_header or {}
    files = {
        room.name: _write_room_header_mm(
            room.mainHeader,
            shape_type,
            groups,
            paths if len(headers) > 1 else None,
            source_headers[0] if source_headers else None,
            actor_objects_by_header.get(0),
            source_indices_by_header.get(0),
        )
    }
    for index, header in enumerate(headers[1:], 1):
        if header is not None:
            files[f"{room.name}Header_{index:02}"] = _write_room_header_mm(
                header,
                shape_type,
                groups,
                source_header=source_headers[index] if index < len(source_headers) else None,
                actor_objects=actor_objects_by_header.get(index),
                source_indices=source_indices_by_header.get(index),
            )
    return files


def _mm_tex_anim_path(payload: bytes | None) -> str | None:
    result = None if payload is None else _read_resource_string(payload, 0)
    return None if result is None or not result[0] else result[0]


def _mm_skybox_indoors(value) -> int:
    text = str(value).strip().lower()
    if text in {"false", "outdoor", "light_mode_time"}:
        return 0
    if text in {"true", "indoor", "light_mode_settings"}:
        return 1
    return _number(value, "skybox indoors")


def _write_scene_header_mm(
    header, room_paths, collision_path, pathway_path, source_header=None, alternate_paths=None
) -> bytes:
    infos = header.infos
    transitions = header.transitionActors.entries
    source_commands = _mm_header_commands(source_header)
    source_entrances = _source_entries(source_commands.get(_MM_CMD["ENTRANCES"]), 2)
    source_spawns = _source_entries(source_commands.get(_MM_CMD["START_POSITIONS"]), 16)
    tex_anim_path = _mm_tex_anim_path(source_commands.get(_MM_CMD["ANIMATED_MATERIALS"]))
    has_world_map_visited = getattr(
        infos, "hm64_mm_set_region_visited", _MM_CMD["WORLD_MAP_VISITED"] in source_commands
    )
    entrances = [(entry.spawnIndex, entry.roomIndex) for entry in header.spawns.entries]
    spawns = list(header.entranceActors.entries)
    if len(entrances) < len(source_entrances):
        entrances.extend(struct.unpack("<BB", entry) for entry in source_entrances[len(entrances) :])
    if len(spawns) < len(source_spawns):
        spawns.extend(source_spawns[len(spawns) :])
    preserved = (0x02, _MM_CMD["ACTOR_CUTSCENES"], _MM_CMD["MINIMAP"], _MM_CMD["MINIMAP_CHESTS"], _MM_CMD["CUTSCENES"])
    writer = _Writer(b"MORO")
    writer.u32(
        10
        + int(alternate_paths is not None)
        + int(pathway_path is not None)
        + int(has_world_map_visited)
        + int(bool(transitions))
        + int(tex_anim_path is not None)
        + sum(command in source_commands for command in preserved)
    )
    if alternate_paths is not None:
        _write_alternate_headers(writer, alternate_paths)
    writer.command(_MM_CMD["SPECIAL_OBJECTS"])
    source_special = source_commands.get(_MM_CMD["SPECIAL_OBJECTS"])
    if source_special is not None and len(source_special) == 3:
        writer.data.extend(source_special)
    else:
        writer.s8(_number(infos.naviHintType, "Navi hint"))
        writer.u16(_number(infos.keepObjectID, "global object"))
    writer.command(_MM_CMD["COLLISION"])
    writer.string(collision_path)
    writer.command(_MM_CMD["ROOMS"])
    writer.u32(len(room_paths))
    for room_path in room_paths:
        writer.string(room_path)
        writer.s32(0)
        writer.s32(0)
    writer.command(_MM_CMD["ENTRANCES"])
    writer.u32(len(entrances))
    for spawn_index, room_index in entrances:
        writer.u8(spawn_index)
        writer.u8(room_index)
    writer.command(_MM_CMD["START_POSITIONS"])
    writer.u32(len(spawns))
    for spawn_index, actor in enumerate(spawns):
        if isinstance(actor, bytes):
            writer.data.extend(actor)
        else:
            _mm_start_position_entry(
                writer,
                actor,
                source_spawns[spawn_index] if spawn_index < len(source_spawns) else None,
            )
    if pathway_path is not None:
        writer.command(_MM_CMD["PATHWAYS"])
        writer.u32(1)
        writer.string(pathway_path)
    if transitions:
        writer.command(_MM_CMD["TRANSITIONS"])
        writer.u32(len(transitions))
        for actor in transitions:
            writer.s8(actor.roomFrom)
            writer.u8(_number(actor.cameraFront, "transition camera"))
            writer.s8(actor.roomTo)
            writer.u8(_number(actor.cameraBack, "transition camera"))
            writer.u16(_actor_id(actor.id))
            for value in actor.pos:
                writer.s16(value)
            writer.s16(_binary_angle(actor.rot))
            writer.u16(_number(actor.params, "transition actor parameters"))
    writer.command(_MM_CMD["SKYBOX"])
    source_skybox = source_commands.get(_MM_CMD["SKYBOX"])
    writer.s8(source_skybox[0] if source_skybox is not None and len(source_skybox) == 4 else 0)
    writer.s8(_number(infos.skyboxID, "skybox ID"))
    writer.s8(_number(infos.skyboxConfig, "skybox config"))
    writer.s8(_mm_skybox_indoors(header.lighting.envLightMode))
    writer.command(_MM_CMD["LIGHTING"])
    light_settings = _light_settings(header, source_commands)
    writer.u32(len(light_settings))
    for light in light_settings:
        if isinstance(light, bytes):
            writer.data.extend(light)
        else:
            _light_entry(writer, light)
    writer.command(_MM_CMD["EXITS"])
    writer.u32(len(header.exits.exitList))
    for _, exit_index in header.exits.exitList:
        writer.u16(_exit_index(exit_index))
    writer.command(_MM_CMD["SOUND"])
    writer.s8(_number(infos.specID, "audio session preset"))
    writer.s8(_number(infos.ambienceID, "night ambience"))
    writer.s8(_number(infos.sequenceID, "music sequence"))
    if has_world_map_visited:
        writer.command(_MM_CMD["WORLD_MAP_VISITED"])
    if tex_anim_path is not None:
        writer.command(_MM_CMD["ANIMATED_MATERIALS"])
        writer.string(tex_anim_path)
    for command in preserved:
        payload = source_commands.get(command)
        if payload is not None:
            writer.command(command)
            writer.data.extend(payload)
    writer.command(_MM_CMD["END"])
    return writer.finish()


def _scene_header_variants(scene):
    headers = [scene.mainHeader]
    if scene.altHeader is None:
        return headers
    headers.extend([scene.altHeader.childNight, scene.altHeader.adultDay, scene.altHeader.adultNight])
    headers.extend(scene.altHeader.cutscenes)
    return headers


def _mm_scene_header_variants(scene):
    headers = [scene.mainHeader]
    if scene.altHeader is not None:
        headers.extend(scene.altHeader.cutscenes)
    return headers


def _read_resource_string(data: bytes, offset: int) -> tuple[str, int] | None:
    if offset + 4 > len(data):
        return None
    length = struct.unpack_from("<I", data, offset)[0]
    end = offset + 4 + length
    if end > len(data):
        return None
    try:
        return data[offset + 4 : end].decode("utf-8"), end
    except UnicodeDecodeError:
        return None


def _header_command_paths(data: bytes, command_id: int) -> list[str]:
    command = struct.pack("<I", command_id)
    paths = []
    start = _RESOURCE_HEADER_SIZE
    while True:
        offset = data.find(command, start)
        if offset < 0:
            return paths
        start = offset + 1
        if command_id == _CMD["CUTSCENES"]:
            result = _read_resource_string(data, offset + 4)
            if result is not None:
                paths.append(result[0])
        elif command_id == _CMD["ALTERNATE_HEADERS"] and offset + 8 <= len(data):
            count = struct.unpack_from("<I", data, offset + 4)[0]
            cursor = offset + 8
            entries = []
            for _ in range(count):
                result = _read_resource_string(data, cursor)
                if result is None:
                    break
                path, cursor = result
                entries.append(path)
            if len(entries) == count:
                paths.extend(entries)


def _base_header_cutscene_paths(internal_directory: str, scene_name: str, archive) -> list[str | None]:
    main_path = f"{internal_directory}/{scene_name}"
    main_data = archive.file(main_path)
    if main_data is None:
        return [None]
    header_paths = [main_path]
    header_paths.extend(_header_command_paths(main_data, _CMD["ALTERNATE_HEADERS"]))
    cutscene_paths = []
    for path in header_paths:
        data = archive.file(path) if path else None
        paths = [] if data is None else _header_command_paths(data, _CMD["CUTSCENES"])
        cutscene_paths.append(paths[0] if paths else None)
    return cutscene_paths


def _base_header_command_presence(internal_directory: str, scene_name: str, archive, command_id: int) -> list[bool]:
    main_path = f"{internal_directory}/{scene_name}"
    main_data = archive.file(main_path)
    if main_data is None:
        return []
    header_paths = [main_path]
    header_paths.extend(_header_command_paths(main_data, _CMD["ALTERNATE_HEADERS"]))
    command = struct.pack("<I", command_id)
    return [
        bool(path and (data := archive.file(path)) and data.find(command, _RESOURCE_HEADER_SIZE) >= 0)
        for path in header_paths
    ]


def _base_header_resources(internal_directory: str, scene_name: str, archive) -> list[bytes | None]:
    main_path = f"{internal_directory}/{scene_name}"
    main_data = archive.file(main_path)
    if main_data is None:
        return []
    paths = [main_path]
    paths.extend(_header_command_paths(main_data, _CMD["ALTERNATE_HEADERS"]))
    return [archive.file(path) if path else None for path in paths]


def _base_room_header_resources(internal_directory: str, room_name: str, archive) -> list[bytes | None]:
    path = f"{internal_directory}/{room_name}"
    return _base_room_header_resources_by_path(path, archive)


def _base_room_header_resources_by_path(path: str, archive) -> list[bytes | None]:
    data = archive.file(path)
    if data is None:
        return []
    paths = [path]
    paths.extend(_header_command_paths(data, _CMD["ALTERNATE_HEADERS"]))
    return [archive.file(header_path) if header_path else None for header_path in paths]


def _tag_imported_room_actors(scene_obj, internal_directory: str, archive, is_mm: bool = False):
    read_commands = _mm_header_commands if is_mm else _header_commands
    for room_obj in (obj for obj in scene_obj.children if obj.type == "EMPTY" and obj.ootEmptyType == "Room"):
        source_headers = _base_room_header_resources(internal_directory, room_obj.name, archive)
        for header_index, source_header in enumerate(source_headers):
            source_actors = _source_entries(read_commands(source_header).get(_CMD["ACTORS"]), 16)
            actor_objects = _room_actor_objects(scene_obj, room_obj, header_index)
            indices = list(range(min(len(actor_objects), len(source_actors))))
            for actor_obj, source_index in zip(actor_objects, indices):
                actor_obj[_HM64_ACTOR_REF] = f"{room_obj.ootRoomHeader.roomIndex}:{header_index}:{source_index}"
                if is_mm:
                    _apply_hm64_mm_actor_flags(actor_obj.ootActorProperty, source_actors[source_index])


def _apply_hm64_mm_actor_flags(actor_props, actor_entry: bytes):
    if len(actor_entry) < 14:
        return
    rot_x, rot_y, rot_z = struct.unpack_from("<hhh", actor_entry, 8)
    _set_hm64_mm_halfday_bits(actor_props, ((rot_x & 0x07) << 7) | (rot_z & 0x7F))
    actor_props.hm64_mm_actor_cs_index = rot_y & 0x7F


def _assign_missing_scene_materials(scene_obj):
    material = next(iter(bpy.data.materials), None)
    if material is None:
        from ...f3d.f3d_material import createF3DMat

        material = createF3DMat(None, preset="oot_shaded_solid")
    for obj in scene_obj.children_recursive:
        if obj.type == "MESH" and not obj.data.materials:
            obj.data.materials.append(material)


def _reference_archive(archive):
    while archive.fallbacks:
        archive = archive.fallbacks[0]
    return archive


@contextmanager
def _use_hm64_scene_mesh_writer():
    original = (
        room_shape_exporter.TriangleConverterInfo,
        room_shape_exporter.getInfoDict,
        room_shape_exporter.saveStaticModel,
    )
    room_shape_exporter.TriangleConverterInfo = TriangleConverterInfo
    room_shape_exporter.getInfoDict = getInfoDict
    room_shape_exporter.saveStaticModel = saveStaticModel
    try:
        yield
    finally:
        (
            room_shape_exporter.TriangleConverterInfo,
            room_shape_exporter.getInfoDict,
            room_shape_exporter.saveStaticModel,
        ) = original


def _normalize_mm_global_objects(scene_obj):
    headers = [scene_obj.ootSceneHeader]
    alternate = getattr(scene_obj, "ootAlternateSceneHeaders", None)
    if alternate is not None:
        headers.extend(alternate.cutsceneHeaders)
    for header in headers:
        if header is not None and header.globalObject != "Custom":
            header.globalObjectCustom = header.globalObject
            header.globalObject = "Custom"


def _preserve_mm_empty_header_slots(exported_scene, scene_obj):
    alternate = getattr(scene_obj, "ootAlternateSceneHeaders", None)
    if alternate is not None and exported_scene.altHeader is not None:
        for index, header_props in enumerate(alternate.cutsceneHeaders):
            if header_props.usePreviousHeader and index < len(exported_scene.altHeader.cutscenes):
                exported_scene.altHeader.cutscenes[index] = None

    room_props_by_index = {
        room.ootRoomHeader.roomIndex: room
        for room in scene_obj.children_recursive
        if room.type == "EMPTY" and room.ootEmptyType == "Room"
    }
    for room in exported_scene.rooms.entries:
        source_room = room_props_by_index.get(room.roomIndex)
        if source_room is None or room.altHeader is None:
            continue
        for index, header_props in enumerate(source_room.ootAlternateRoomHeaders.cutsceneHeaders):
            if header_props.usePreviousHeader and index < len(room.altHeader.cutscenes):
                room.altHeader.cutscenes[index] = None


def _apply_mm_header_properties(exported_scene, scene_obj):
    scene_props = [scene_obj.ootSceneHeader, *scene_obj.ootAlternateSceneHeaders.cutsceneHeaders]
    for header, props in zip(_mm_scene_header_variants(exported_scene), scene_props):
        if header is not None:
            header.infos.hm64_mm_set_region_visited = props.hm64_mm_set_region_visited

    rooms_by_index = {
        room.ootRoomHeader.roomIndex: room
        for room in scene_obj.children_recursive
        if room.type == "EMPTY" and room.ootEmptyType == "Room"
    }
    for room in exported_scene.rooms.entries:
        source_room = rooms_by_index.get(room.roomIndex)
        if source_room is None:
            continue
        for header, props in zip(_mm_room_header_variants(room), _mm_room_headers(source_room)):
            if header is not None:
                header.infos.hm64_mm_enable_pos_lights = props.hm64_mm_enable_pos_lights
                header.infos.hm64_mm_enable_storm = props.hm64_mm_enable_storm


def _normalize_mm_room_objects(scene_obj):
    oot_objects = Z64_ObjectData("OOT").objects_by_key
    for room_obj in (obj for obj in scene_obj.children_recursive if obj.type == "EMPTY" and obj.ootEmptyType == "Room"):
        headers = [room_obj.ootRoomHeader]
        alternate = room_obj.ootAlternateRoomHeaders
        headers.extend((alternate.childNightHeader, alternate.adultDayHeader, alternate.adultNightHeader))
        headers.extend(alternate.cutsceneHeaders)
        for header in headers:
            for object_props in header.objectList:
                if object_props.objectKey != "Custom":
                    source_object = oot_objects.get(object_props.objectKey)
                    object_props.objectIDCustom = (
                        source_object.id if source_object is not None else object_props.objectKey
                    )
                    object_props.objectKey = "Custom"


def _mm_room_headers(room_obj):
    headers = [room_obj.ootRoomHeader]
    alternate = room_obj.ootAlternateRoomHeaders
    headers.extend((alternate.childNightHeader, alternate.adultDayHeader, alternate.adultNightHeader))
    headers.extend(alternate.cutsceneHeaders)
    return headers


def _add_missing_mm_room_objects(scene_obj):
    objects = Z64_ObjectData("MM")
    ignored = {"player", "gameplay_keep", "gameplay_field_keep", "gameplay_dangeon_keep"}
    for room_obj in (obj for obj in scene_obj.children_recursive if obj.type == "EMPTY" and obj.ootEmptyType == "Room"):
        for header_index, header in enumerate(_mm_room_headers(room_obj)):
            existing = {
                entry.objectIDCustom if entry.objectKey == "Custom" else entry.objectKey for entry in header.objectList
            }
            for actor_obj in _room_actor_objects(scene_obj, room_obj, header_index):
                actor_props = actor_obj.ootActorProperty
                actor_id = actor_props.actor_id_custom if actor_props.actor_id == "Custom" else actor_props.actor_id
                actor = Z64_ActorData("MM").actorsByID.get(actor_id)
                if actor is None or actor.key in ignored:
                    continue
                for object_key in actor.tiedObjects:
                    if object_key in ignored:
                        continue
                    object_data = objects.objects_by_key.get(object_key)
                    if object_data is None or object_data.id in existing:
                        continue
                    object_props = header.objectList.add()
                    object_props.objectKey = "Custom"
                    object_props.objectIDCustom = object_data.id
                    existing.add(object_data.id)


def _export_hm64_mm_scene(scene_obj, transform, settings):
    if not settings.exportPath.strip():
        raise PluginError("Set a scene export directory.")
    _normalize_mm_global_objects(scene_obj)
    _normalize_mm_room_objects(scene_obj)
    _add_missing_mm_room_objects(scene_obj)
    export_root = bpy.path.abspath(settings.exportPath)
    level_name = _mm_scene_name_from_id(bpy.context.scene.hm64_mm_scene_export_option)
    scene_name = level_name
    internal_directory = f"scenes/nonmq/{scene_name}"
    directory = Path(export_root) / internal_directory
    directory.mkdir(parents=True, exist_ok=True)

    ensure_hm64_soh_xml()
    ensure_hm64_texture_writer()
    export_info = type(
        "HM64MMSceneExportInfo",
        (),
        {
            "name": level_name,
            "saveTexturesAsPNG": False,
            "useMacros": False,
            "auto_add_room_objects": False,
        },
    )()
    with _use_hm64_scene_mesh_writer(), _use_hm64_mm_header_visibility():
        exported_scene = SceneExport.create_scene(scene_obj, transform, export_info)
    _apply_mm_header_properties(exported_scene, scene_obj)
    _preserve_mm_empty_header_slots(exported_scene, scene_obj)
    room_paths = [f"{internal_directory}/{room.name}" for room in exported_scene.rooms.entries]
    collision_path = f"{internal_directory}/{scene_name}CollisionHeader"
    headers = _mm_scene_header_variants(exported_scene)
    paths = [
        f"{internal_directory}/{scene_name}Header_{index:02}" if header is not None else None
        for index, header in enumerate(headers[1:], 1)
    ]
    reference_archive = None
    base_headers = []
    if (bpy.context.scene.hm64_o2r_path or "").strip():
        reference_archive = _reference_archive(get_hm64_o2r_source(bpy.context.scene).archive)
        base_headers = _base_header_resources(internal_directory, scene_name, reference_archive)
    for room in exported_scene.rooms.entries:
        source_room_headers = (
            []
            if reference_archive is None
            else _base_room_header_resources(internal_directory, room.name, reference_archive)
        )
        room_obj = next(
            (
                obj
                for obj in scene_obj.children
                if obj.type == "EMPTY" and obj.ootEmptyType == "Room" and obj.ootRoomHeader.roomIndex == room.roomIndex
            ),
            None,
        )
        actor_objects_by_header = {}
        source_indices_by_header = {}
        if room_obj is not None:
            for header_index, header in enumerate(_mm_room_header_variants(room)):
                if header is not None:
                    actor_objects_by_header[header_index] = _room_actor_objects(scene_obj, room_obj, header_index)
                    source_indices_by_header[header_index] = _exported_source_actor_indices(
                        header.actors.actorList, actor_objects_by_header[header_index]
                    )
        for name, data in _write_room_mm(
            room,
            str(directory),
            internal_directory,
            source_room_headers,
            actor_objects_by_header,
            source_indices_by_header,
        ).items():
            (directory / name).write_bytes(data)
    (directory / f"{scene_name}CollisionHeader").write_bytes(_write_collision(exported_scene.colHeader))
    pathway_paths = []
    for index, header in enumerate(headers):
        if header is None or not header.path.pathList:
            pathway_paths.append(None)
            continue
        suffix = "" if index == 0 else f"Header_{index:02}"
        pathway_name = f"{scene_name}Pathway{suffix}"
        (directory / pathway_name).write_bytes(_write_pathways(header.path, True))
        pathway_paths.append(f"{internal_directory}/{pathway_name}")
    for index, header in enumerate(headers):
        if header is None:
            continue
        name = scene_name if index == 0 else f"{scene_name}Header_{index:02}"
        (directory / name).write_bytes(
            _write_scene_header_mm(
                header,
                room_paths,
                collision_path,
                pathway_paths[index],
                base_headers[index] if index < len(base_headers) else None,
                paths if index == 0 and len(headers) > 1 else None,
            )
        )


def export_hm64_scene(scene_obj, transform, settings):
    if hm64_mm_features_enabled():
        with _using_mm_scene_import_context():
            return _export_hm64_mm_scene(scene_obj, transform, settings)
    if settings.option == "Custom":
        raise PluginError("HM64 scene export replaces a selected scene; choose a Scene ID.")
    if not settings.exportPath.strip():
        raise PluginError("Set a scene export directory.")
    export_root = bpy.path.abspath(settings.exportPath)
    level_name = sceneNameFromID(settings.option)
    scene_name = f"{toAlnum(level_name)}_scene"
    category = "nonmq" if level_name in ootSceneDungeons else "shared"
    internal_directory = f"scenes/{category}/{scene_name}"
    directory = Path(export_root) / internal_directory
    directory.mkdir(parents=True, exist_ok=True)

    ensure_hm64_soh_xml()
    ensure_hm64_texture_writer()
    export_info = type(
        "HM64SceneExportInfo",
        (),
        {
            "name": level_name,
            "saveTexturesAsPNG": False,
            "useMacros": False,
            "auto_add_room_objects": settings.auto_add_room_objects,
        },
    )()
    with _use_hm64_scene_mesh_writer():
        exported_scene = SceneExport.create_scene(scene_obj, transform, export_info)
    room_paths = [f"{internal_directory}/{room.name}" for room in exported_scene.rooms.entries]
    collision_path = f"{internal_directory}/{scene_name}CollisionHeader"
    headers = _scene_header_variants(exported_scene)
    paths = [
        f"{internal_directory}/{scene_name}Header_{index:02}" if header is not None else None
        for index, header in enumerate(headers[1:], 1)
    ]
    archive = None
    base_cutscene_paths = []
    base_camera_settings = []
    base_headers = []
    reference_archive = None
    if (bpy.context.scene.hm64_o2r_path or "").strip():
        archive = get_hm64_o2r_source(bpy.context.scene).archive
        reference_archive = _reference_archive(archive)
        base_cutscene_paths = _base_header_cutscene_paths(internal_directory, scene_name, reference_archive)
        base_camera_settings = _base_header_command_presence(
            internal_directory, scene_name, reference_archive, _CMD["CAMERA_SETTINGS"]
        )
        base_headers = _base_header_resources(internal_directory, scene_name, reference_archive)
    for room in exported_scene.rooms.entries:
        source_room_headers = (
            []
            if reference_archive is None
            else _base_room_header_resources(internal_directory, room.name, reference_archive)
        )
        room_obj = next(
            (
                obj
                for obj in scene_obj.children
                if obj.type == "EMPTY" and obj.ootEmptyType == "Room" and obj.ootRoomHeader.roomIndex == room.roomIndex
            ),
            None,
        )
        actor_objects_by_header = {}
        source_indices_by_header = {}
        if room_obj is not None:
            for header_index, header in enumerate(_room_header_variants(room)):
                if header is not None:
                    actor_objects_by_header[header_index] = _room_actor_objects(scene_obj, room_obj, header_index)
                    source_indices_by_header[header_index] = _exported_source_actor_indices(
                        header.actors.actorList, actor_objects_by_header[header_index]
                    )
        for name, data in _write_room(
            room,
            str(directory),
            internal_directory,
            source_room_headers,
            actor_objects_by_header,
            source_indices_by_header,
        ).items():
            (directory / name).write_bytes(data)
    (directory / f"{scene_name}CollisionHeader").write_bytes(_write_collision(exported_scene.colHeader))
    pathway_paths = []
    for index, header in enumerate(headers):
        if header is None or not header.path.pathList:
            pathway_paths.append(None)
            continue
        suffix = "" if index == 0 else f"Header_{index:02}"
        pathway_name = f"{scene_name}Pathway{suffix}"
        (directory / pathway_name).write_bytes(_write_pathways(header.path))
        pathway_paths.append(f"{internal_directory}/{pathway_name}")

    def cutscene_path_for(index):
        return base_cutscene_paths[index] if index < len(base_cutscene_paths) else None

    def camera_settings_for(index):
        if index < len(base_camera_settings):
            return base_camera_settings[index]
        return None

    def pathway_path_for(index):
        return pathway_paths[index] if index < len(pathway_paths) else None

    cutscene_path = cutscene_path_for(0)
    (directory / scene_name).write_bytes(
        _write_scene_header(
            headers[0],
            room_paths,
            collision_path,
            cutscene_path,
            pathway_path_for(0),
            paths if len(headers) > 1 else None,
            camera_settings_for(0),
            base_headers[0] if base_headers else None,
        )
    )
    for index, header in enumerate(headers[1:], 1):
        if header is not None:
            cutscene_path = cutscene_path_for(index)
            (directory / f"{scene_name}Header_{index:02}").write_bytes(
                _write_scene_header(
                    header,
                    room_paths,
                    collision_path,
                    cutscene_path,
                    pathway_path_for(index),
                    has_camera_settings=camera_settings_for(index),
                    source_header=base_headers[index] if index < len(base_headers) else None,
                )
            )


_original_export_execute = None
_original_draw_props = None
_original_import_scene = None
_original_draw_scene_search = None
_original_actor_draw_props = None
_original_object_draw_props = None
_original_object_panel_draw = None
_original_scene_alt_draw_props = None
_original_room_alt_draw_props = None
_original_scene_header_draw_props = None
_original_room_header_draw_props = None


@contextmanager
def _using_mm_game_data():
    previous_game = game_data.z64.game
    if previous_game == "MM":
        yield
        return
    game_data.z64.update(None, "MM", True)
    try:
        yield
    finally:
        game_data.z64.update(None, previous_game, True)


class HM64_SearchMMSceneOperator(Operator):
    bl_idname = "object.hm64_search_mm_scene"
    bl_label = "Choose MM Scene"
    bl_property = "scene_id"
    bl_options = {"REGISTER", "UNDO"}

    scene_id: EnumProperty(items=mm_enum_scene_id, default="SCENE_20SICHITAI2")
    op_name: StringProperty(default="Import")

    def execute(self, context):
        if self.op_name == "Export":
            context.scene.hm64_mm_scene_export_option = self.scene_id
        else:
            context.scene.hm64_mm_scene_import_option = self.scene_id
        context.region.tag_redraw()
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}


def _mm_scene_name_from_id(scene_id: str) -> str:
    try:
        return mm_scene_id_to_name[scene_id]
    except KeyError:
        raise PluginError(f"Cannot find MM scene ID {scene_id}")


def _mm_scene_directory(scene_name: str, include_extracted: bool = False) -> str:
    extracted = bpy.context.scene.fast64.oot.get_extracted_path() if include_extracted else "."
    return f"{extracted}/assets/scenes/{scene_name}"


@contextmanager
def _using_mm_scene_import_context():
    from ...z64.importer import scene as scene_importer
    from ...z64.importer import actor as actor_importer
    from ...z64.importer import scene_header
    from ...z64.importer import room_header
    from ...z64.exporter.decomp_edit.scene_table import SceneTableUtility
    from ...z64.exporter.collision.surface import SurfaceType
    from ...z64.importer.scene_pathways import parsePath
    from ...z64.importer.utility import getDataMatch
    from ...f3d import f3d_parser
    from ...z64 import OOT_Properties

    original_scene_name = scene_importer.sceneNameFromID
    original_scene_directory = scene_importer.getSceneDirFromLevelName
    original_parse_scene_commands = scene_importer.parseSceneCommands
    original_header_parse_scene_commands = scene_header.parseSceneCommands
    original_parse_room_commands = scene_header.parseRoomCommands
    original_set_header_property = scene_header.setCustomProperty
    original_parse_actor_info = actor_importer.parseActorInfo
    original_set_actor_property = actor_importer.setCustomProperty
    original_surface_from_hex = SurfaceType.__dict__["from_hex"]
    original_parse_path_list = scene_header.parsePathList
    original_parse_object_list = room_header.parseObjectList
    original_draw_config = SceneTableUtility.__dict__["get_draw_config"]
    original_parse_texture_data = f3d_parser.parseTextureData
    original_game_data_update = game_data.z64.update
    original_get_extracted_path = OOT_Properties.get_extracted_path
    previous_game = game_data.z64.game
    shared_texture_sources: dict[Path, str] = {}

    def _mm_draw_config(scene_name: str):
        path = os.path.join(bpy.path.abspath(bpy.context.scene.ootDecompPath), "include/tables/scene_table.h")
        scene_table = Path(path).read_text(encoding="utf-8")
        match = re.search(
            rf"DEFINE_SCENE\(\s*{re.escape(scene_name)}\s*,\s*[^,]+,\s*[^,]+,\s*([^,\s)]+)",
            scene_table,
        )
        if match is None:
            raise PluginError(f"Scene name {scene_name} not found in scene table.")
        return match.group(1)

    def _mm_game_data_update(context, game, force=False):
        if game is None:
            return original_game_data_update(context, "MM", True)
        return original_game_data_update(context, game, force)

    def _mm_get_extracted_path(self):
        version = self.mm_version
        if version == "legacy":
            return "."
        return f"extracted/{version if version != 'Custom' else self.oot_version_custom}"

    def _mm_parse_texture_data(dl_data, texture_name, f3d_context, image_format, image_size, width, is_lut, f3d):
        image, loaded_from_image_file = original_parse_texture_data(
            dl_data, texture_name, f3d_context, image_format, image_size, width, is_lut, f3d
        )
        if loaded_from_image_file and isinstance(image, bpy.types.Image):
            existing_image = bpy.data.images.get(texture_name)
            if existing_image is not None and existing_image != image:
                bpy.data.images.remove(image)
                image = existing_image
            else:
                image.name = texture_name
        return image, loaded_from_image_file

    def _mm_parse_path_list(scene_obj, scene_data, path_list_name, header_index, shared_scene_data):
        path_data = getDataMatch(scene_data, path_list_name, "Path", "path list", strip=True)
        path_list = [value.replace("{", "").strip() for value in path_data.split("},") if value.strip()]
        for index, path_entry in enumerate(path_list):
            values = [value.strip() for value in path_entry.split(",")]
            if len(values) != 4:
                raise PluginError(f"MM path entry '{path_entry}' is malformed.")
            parsePath(scene_obj, scene_data, values[3], header_index, shared_scene_data, index)

    def _mm_parse_object_list(room_header_props, scene_data, object_list_name):
        object_data = getDataMatch(scene_data, object_list_name, "s16", "object list", strip=True)
        for object_id in (value.strip() for value in object_data.split(",") if value.strip()):
            object_props = room_header_props.objectList.add()
            _set_hm64_mm_object_key(object_props, object_id)

    def _mm_parse_actor_info(actor_match, nested_brackets):
        if not nested_brackets or "SPAWN_ROT_FLAGS" not in actor_match.group(3):
            return original_parse_actor_info(actor_match, nested_brackets)

        actor_id = actor_match.group(1).strip().split(" | ", 1)[0]
        position = tuple(hexOrDecInt(value.strip()) for value in actor_match.group(2).split(",") if value.strip())
        rotation = tuple(
            hexOrDecInt(getEvalParamsInt(match.group(1)))
            for match in re.finditer(r"SPAWN_ROT_FLAGS\s*\(\s*([^,]+)", actor_match.group(3))
        )
        return actor_id, position, rotation, actor_match.group(4).strip().removesuffix(",")

    def _mm_parse_scene_commands(*args, **kwargs):
        args = list(args)
        args[4] = re.sub(r"\bSCENE_CMD_SPAWN_LIST\s*\(", "SCENE_CMD_PLAYER_ENTRY_LIST(", args[4])
        result = original_parse_scene_commands(*args, **kwargs)
        header_index = args[6]
        scene_obj = args[1] or result
        if header_index > 0:
            headers = scene_obj.ootAlternateSceneHeaders.cutsceneHeaders
            while len(headers) < header_index:
                headers.add()
            headers[header_index - 1].usePreviousHeader = False
            header = headers[header_index - 1]
        else:
            header = scene_obj.ootSceneHeader
        header.hm64_mm_set_region_visited = "SCENE_CMD_SET_REGION_VISITED" in args[4]
        return result

    def _mm_parse_room_commands(*args, **kwargs):
        args = list(args)
        root = Path(bpy.context.scene.ootDecompPath) / bpy.context.scene.fast64.oot.get_extracted_path()
        included_data = []
        for include_path in re.findall(r'#include\s+"(assets/[^"\n]+\.h)"', args[2]):
            if not include_path.startswith("assets/misc/scene_texture_"):
                continue
            include_file = root / include_path
            source_file = include_file.with_suffix(".c")
            if source_file not in shared_texture_sources:
                shared_texture_sources[source_file] = (
                    source_file.read_text(encoding="utf-8") if source_file.is_file() else ""
                )
            if shared_texture_sources[source_file]:
                included_data.append(shared_texture_sources[source_file])
        args[2] += "\n" + "\n".join(included_data)
        result = original_parse_room_commands(*args, **kwargs)
        header_index = args[7]
        room_obj = args[1] or result
        if header_index >= 4:
            headers = room_obj.ootAlternateRoomHeaders.cutsceneHeaders
            while len(headers) < header_index - 3:
                headers.add()
            headers[header_index - 4].usePreviousHeader = False
            header = headers[header_index - 4]
        elif header_index > 0:
            header = getattr(
                room_obj.ootAlternateRoomHeaders,
                ("childNightHeader", "adultDayHeader", "adultNightHeader")[header_index - 1],
            )
        else:
            header = room_obj.ootRoomHeader
        match = re.search(r"SCENE_CMD_ROOM_BEHAVIOR\s*\(([^)]*)\)", args[2])
        if match is not None:
            values = [value.strip().lower() for value in match.group(1).split(",")]
            header.hm64_mm_enable_pos_lights = len(values) > 4 and values[4] in {"true", "1"}
            header.hm64_mm_enable_storm = len(values) > 5 and values[5] in {"true", "1"}
        return result

    def _mm_set_actor_property(data, prop, value, enum_list, custom_name=None):
        if prop == "actor_id":
            _set_hm64_mm_actor_id(data, value)
            return
        return original_set_actor_property(data, prop, value, enum_list, custom_name)

    def _mm_set_header_property(data, prop, value, enum_list, custom_name=None):
        if prop == "globalObject":
            data.globalObject = "Custom"
            data.globalObjectCustom = value
            return
        return original_set_header_property(data, prop, value, enum_list, custom_name)

    def _mm_surface_from_hex(surface0, surface1):
        return SurfaceType(
            surface0 & 0xFF,
            (surface0 >> 8) & 0x1F,
            f"0x{(surface0 >> 13) & 0x1F:02X}",
            (surface0 >> 18) & 0x07,
            f"0x{(surface0 >> 21) & 0x1F:02X}",
            f"0x{(surface0 >> 26) & 0x0F:02X}",
            bool((surface0 >> 30) & 1),
            bool((surface0 >> 31) & 1),
            f"0x{surface1 & 0x0F:02X}",
            f"0x{(surface1 >> 4) & 0x03:02X}",
            (surface1 >> 6) & 0x1F,
            (surface1 >> 11) & 0x3F,
            bool((surface1 >> 17) & 1),
            (surface1 >> 18) & 0x07,
            (surface1 >> 21) & 0x3F,
            bool((surface1 >> 27) & 1),
            bpy.context.scene.fast64.oot.useDecompFeatures,
        )

    scene_importer.sceneNameFromID = _mm_scene_name_from_id
    scene_importer.getSceneDirFromLevelName = _mm_scene_directory
    scene_importer.parseSceneCommands = _mm_parse_scene_commands
    scene_header.parseSceneCommands = _mm_parse_scene_commands
    scene_header.parseRoomCommands = _mm_parse_room_commands
    scene_header.setCustomProperty = _mm_set_header_property
    actor_importer.parseActorInfo = _mm_parse_actor_info
    actor_importer.setCustomProperty = _mm_set_actor_property
    SurfaceType.from_hex = staticmethod(_mm_surface_from_hex)
    scene_header.parsePathList = _mm_parse_path_list
    room_header.parseObjectList = _mm_parse_object_list
    SceneTableUtility.get_draw_config = staticmethod(_mm_draw_config)
    f3d_parser.parseTextureData = _mm_parse_texture_data
    game_data.z64.update = _mm_game_data_update
    OOT_Properties.get_extracted_path = _mm_get_extracted_path
    try:
        original_game_data_update(None, "MM", True)
        yield
    finally:
        game_data.z64.update = original_game_data_update
        OOT_Properties.get_extracted_path = original_get_extracted_path
        original_game_data_update(None, previous_game, True)
        scene_importer.sceneNameFromID = original_scene_name
        scene_importer.getSceneDirFromLevelName = original_scene_directory
        scene_importer.parseSceneCommands = original_parse_scene_commands
        scene_header.parseSceneCommands = original_header_parse_scene_commands
        scene_header.parseRoomCommands = original_parse_room_commands
        scene_header.setCustomProperty = original_set_header_property
        actor_importer.parseActorInfo = original_parse_actor_info
        actor_importer.setCustomProperty = original_set_actor_property
        SurfaceType.from_hex = original_surface_from_hex
        scene_header.parsePathList = original_parse_path_list
        room_header.parseObjectList = original_parse_object_list
        SceneTableUtility.get_draw_config = original_draw_config
        f3d_parser.parseTextureData = original_parse_texture_data


def _hm64_import_scene(settings, option):
    if hm64_mm_features_enabled():
        if not settings.isCustomDest:
            option = bpy.context.scene.hm64_mm_scene_import_option
            bpy.context.scene.hm64_mm_scene_export_option = option
        with _using_mm_scene_import_context():
            result = _original_import_scene(settings, option)
        if is_hm64() and (bpy.context.scene.hm64_o2r_path or "").strip() and not settings.isCustomDest:
            scene_obj = bpy.context.scene.ootSceneExportObj
            if scene_obj is not None:
                source = get_hm64_o2r_source(bpy.context.scene).archive
                _tag_imported_room_actors(
                    scene_obj,
                    f"scenes/nonmq/{_mm_scene_name_from_id(option)}",
                    _reference_archive(source),
                    is_mm=True,
                )
        scene_obj = bpy.context.scene.ootSceneExportObj
        if scene_obj is not None:
            _assign_missing_scene_materials(scene_obj)
        return result
    result = _original_import_scene(settings, option)
    if not is_hm64():
        return result
    scene_obj = bpy.context.scene.ootSceneExportObj
    if scene_obj is None:
        return result
    if (bpy.context.scene.hm64_o2r_path or "").strip() and option != "Custom":
        level_name = sceneNameFromID(option)
        scene_name = f"{toAlnum(level_name)}_scene"
        category = "nonmq" if level_name in ootSceneDungeons else "shared"
        source = get_hm64_o2r_source(bpy.context.scene).archive
        _tag_imported_room_actors(scene_obj, f"scenes/{category}/{scene_name}", _reference_archive(source))
    _assign_missing_scene_materials(scene_obj)
    return result


def _hm64_draw_scene_search(self, layout, enum_value, op_name):
    if hm64_mm_features_enabled() and op_name in {"Import", "Export"}:
        search_box = layout.box().row()
        search_box.operator(HM64_SearchMMSceneOperator.bl_idname, icon="VIEWZOOM", text="").op_name = op_name
        selected = bpy.context.scene.hm64_mm_scene_import_option
        if op_name == "Export":
            selected = bpy.context.scene.hm64_mm_scene_export_option
        search_box.label(text=next(item[1] for item in mm_enum_scene_id if item[0] == selected))
        return
    return _original_draw_scene_search(self, layout, enum_value, op_name)


def _hm64_export_execute(self, context):
    if not is_hm64():
        return _original_export_execute(self, context)
    from mathutils import Matrix, Vector
    from bpy.ops import object
    from ...utility import ExportUtils, raisePluginError

    with ExportUtils():
        try:
            if context.mode != "OBJECT":
                object.mode_set(mode="OBJECT")
            scene_obj = context.scene.ootSceneExportObj
            if scene_obj is None or scene_obj.type != "EMPTY" or scene_obj.ootEmptyType != "Scene":
                raise PluginError("Set Scene Object to an empty with the Scene type.")
            scale = context.scene.ootBlenderScale
            transform = Matrix.Diagonal(Vector((scale, scale, scale))).to_4x4()
            export_hm64_scene(scene_obj, transform, context.scene.ootSceneExportSettings)
            self.report({"INFO"}, "HM64 scene export complete.")
            return {"FINISHED"}
        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


def _hm64_draw_props(self, layout):
    if not is_hm64():
        return _original_draw_props(self, layout)
    if not hm64_mm_features_enabled():
        prop_split(layout, self, "option", "Scene ID")
    prop_split(layout, self, "exportPath", "Directory")
    prop_split(layout, bpy.context.scene, "ootSceneExportObj", "Scene Object")
    prop_split(layout, bpy.context.scene, "hm64_o2r_path", "Base O2R")
    layout.prop(self, "auto_add_room_objects")


def _hm64_actor_draw_props(self, layout, alt_room_prop, obj):
    if not hm64_mm_features_enabled():
        return _original_actor_draw_props(self, layout, alt_room_prop, obj)
    actor_box = layout.column()
    actor_box.row().prop(self, "hm64_mm_menu_tab", expand=True)
    if self.hm64_mm_menu_tab == "General":
        search_row = actor_box.row()
        search_op = search_row.operator(HM64SearchMMActorOperator.bl_idname, icon="VIEWZOOM", text="Actor ID")
        search_op.actor_user = "Actor"
        search_op.obj_name = obj.name
        search_row.label(text=_hm64_mm_actor_label(self))
        if self.actor_id_custom == "None":
            actor_box.box().label(text="This Actor was deleted from the XML file.")
            return
        if self.actor_id_custom == "Custom" or self.hm64_mm_actor_id == "Custom":
            prop_split(actor_box, self, "actor_id_custom", "Actor ID Custom")

        param_box = actor_box.box()
        param_box.label(text="Actor Parameter")
        param_box.prop(self, "params_custom", text="")
        param_box.prop(self, "rot_override", text="Override Rotation (ignore Blender rot)")
        if self.rot_override:
            prop_split(param_box, self, "rot_x_custom", "Rot X")
            prop_split(param_box, self, "rot_y_custom", "Rot Y")
            prop_split(param_box, self, "rot_z_custom", "Rot Z")

        _draw_hm64_mm_spawn_schedule(actor_box, self, obj.name)
    elif self.hm64_mm_menu_tab == "Actor Cutscene":
        actor_box.prop(self, "hm64_mm_use_global_actor_cs", text="Use Global Actor Cutscene")
        prop_split(actor_box, self, "hm64_mm_actor_cs_index", "Actor CS Index")
        if 119 < self.hm64_mm_actor_cs_index < 127:
            actor_box.label(text="The index can't be between 120 and 126.", icon="ERROR")
        if self.hm64_mm_use_global_actor_cs:
            info_box = actor_box.box()
            info_box.label(text="Use the matching global actor cutscene index.", icon="INFO")
        else:
            actor_box.label(text="Local actor cutscene authoring is not wired for HM64 binary export yet.", icon="INFO")

    _draw_hm64_mm_actor_header_props(actor_box, self.headerSettings, "Actor", alt_room_prop, obj.name)


def _hm64_mm_actor_label(actor_props):
    actor_id = actor_props.actor_id_custom if actor_props.actor_id == "Custom" else actor_props.actor_id
    for item in _mm_actor_items():
        if item[0] == actor_id:
            return item[1]
    return actor_id


def _draw_hm64_mm_spawn_schedule(layout, actor_props, owner_name: str):
    schedule = layout.box().column()
    schedule.label(text="Spawn Schedule")
    row = schedule.row(align=True)
    row.prop(actor_props, "hm64_mm_halfday_all", text="Always Spawn")
    if actor_props.hm64_mm_halfday_all:
        return
    row.prop(actor_props, "hm64_mm_halfday_all_dawns", text="All Dawns")
    row.prop(actor_props, "hm64_mm_halfday_all_nights", text="All Nights")
    if actor_props.hm64_mm_halfday_all_dawns or actor_props.hm64_mm_halfday_all_nights:
        return
    count = len(actor_props.hm64_mm_halfday_bits)
    label = "Entries (Empty)" if count == 0 else f"Entries ({count} Item{'s' if count != 1 else ''})"
    schedule.prop(
        actor_props,
        "hm64_mm_halfday_show_entries",
        text=label,
        icon="TRIA_DOWN" if actor_props.hm64_mm_halfday_show_entries else "TRIA_RIGHT",
    )
    if not actor_props.hm64_mm_halfday_show_entries:
        return
    for index, item in enumerate(actor_props.hm64_mm_halfday_bits):
        item.draw_props(schedule, owner_name, index)
    add_op = schedule.operator(HM64MMActorHalfdayAdd.bl_idname)
    add_op.obj_name = owner_name
    add_op.index = count


def _draw_hm64_mm_actor_header_props(layout, header_props, prop_user: str, alt_prop, obj_name: str):
    header_box = layout.box().column()
    header_box.label(text="Header Settings")
    header_box.prop(header_props, "hm64_mm_include_in_all_setups")
    if header_props.hm64_mm_include_in_all_setups:
        return
    header_box.prop(header_props, "childDayHeader", text="Default Header")
    count = len(header_props.cutsceneHeaders)
    label = "Cutscene Headers (Empty)" if count == 0 else f"Cutscene Headers ({count} Item{'s' if count != 1 else ''})"
    header_box.prop(
        header_props,
        "hm64_mm_expand_tab",
        text=label,
        icon="TRIA_DOWN" if header_props.hm64_mm_expand_tab else "TRIA_RIGHT",
    )
    if not header_props.hm64_mm_expand_tab:
        return
    for index, header_item in enumerate(header_props.cutsceneHeaders):
        header_item.draw_props(header_box, prop_user, index, alt_prop, obj_name)
    from ...z64.collection_utility import drawAddButton

    drawAddButton(header_box, count, prop_user, None, obj_name)


def _hm64_mm_object_label(object_props):
    key = object_props.objectIDCustom if object_props.objectKey == "Custom" else object_props.objectKey
    key = _mm_object_key_from_id(key) or key
    objects = Z64_ObjectData("MM")
    object_data = objects.objects_by_key.get(key)
    return object_data.name if object_data is not None else key


def _hm64_object_draw_props(self, layout, header_index: int, index: int, obj_name: str):
    if not hm64_mm_features_enabled():
        return _original_object_draw_props(self, layout, header_index, index, obj_name)
    obj_item_box = layout.column()
    row = obj_item_box.row()
    row.label(text=_hm64_mm_object_label(self))
    buttons = row.row(align=True)
    search = buttons.operator(HM64SearchMMObjectOperator.bl_idname, icon="VIEWZOOM", text="Select")
    search.obj_name = obj_name
    search.header_index = header_index if header_index is not None else 0
    search.index = index
    from ...z64.collection_utility import drawCollectionOps

    drawCollectionOps(buttons, index, "Object", header_index, obj_name, compact=True)
    if self.hm64_mm_object_key == "Custom":
        prop_split(obj_item_box, self, "objectIDCustom", "Object ID Custom")


def _hm64_object_panel_draw(self, context):
    if not hm64_mm_features_enabled(context.scene):
        return _original_object_panel_draw(self, context)
    box = self.layout.box()
    box.box().label(text="MM Object Inspector")
    obj = context.object
    obj_name = obj.name
    prop_split(box, obj, "ootEmptyType", "Object Type")

    scene_obj = props_panel_main.getSceneObj(obj)
    room_obj = props_panel_main.getRoomObj(obj)
    alt_scene_prop = scene_obj.ootAlternateSceneHeaders if scene_obj is not None else None
    alt_room_prop = room_obj.ootAlternateRoomHeaders if room_obj is not None else None

    with _using_mm_game_data():
        if obj.ootEmptyType == "Actor":
            obj.ootActorProperty.draw_props(box, alt_room_prop, obj)
        elif obj.ootEmptyType == "Transition Actor":
            obj.ootTransitionActorProperty.draw_props(box, alt_scene_prop, room_obj, obj_name)
        elif obj.ootEmptyType == "Water Box":
            obj.ootWaterBoxProperty.draw_props(box)
        elif obj.ootEmptyType == "Scene":
            props_panel_main.drawSceneHeader(box, obj)
        elif obj.ootEmptyType == "Room":
            obj.ootRoomHeader.draw_props(box, None, None, obj_name)
            if obj.ootRoomHeader.menuTab == "Alternate":
                obj.ootAlternateRoomHeaders.draw_props(box, obj_name)
        elif obj.ootEmptyType == "Entrance":
            obj.ootEntranceProperty.draw_props(box, obj, alt_scene_prop, obj_name)
        elif obj.ootEmptyType == "Cull Group":
            obj.ootCullGroupProperty.draw_props(box)
        elif obj.ootEmptyType == "LOD":
            props_panel_main.drawLODProperty(box, obj)
        elif obj.ootEmptyType == "Cutscene":
            obj.ootCutsceneProperty.draw_props(box, obj)
        elif obj.ootEmptyType == "Animated Materials":
            obj.fast64.oot.animated_materials.draw_props(box, obj)
        elif obj.ootEmptyType in [
            "CS Actor Cue List",
            "CS Player Cue List",
            "CS Actor Cue Preview",
            "CS Player Cue Preview",
        ]:
            label_prefix = "Player" if "Player" in obj.ootEmptyType else "Actor"
            obj.ootCSMotionProperty.actorCueListProp.draw_props(
                box, obj.ootEmptyType == f"CS {label_prefix} Cue Preview", label_prefix, obj.name
            )
        elif obj.ootEmptyType in ["CS Actor Cue", "CS Player Cue", "CS Dummy Cue"]:
            label_prefix = "Player" if obj.parent.ootEmptyType == "CS Player Cue List" else "Actor"
            obj.ootCSMotionProperty.actorCueProp.draw_props(
                box, label_prefix, obj.ootEmptyType == "CS Dummy Cue", obj.name
            )
        elif obj.ootEmptyType == "None":
            box.label(text="Geometry can be parented to this.")


def _hm64_scene_header_draw_props(self, layout, dropdown_label, header_index, obj):
    if not hm64_mm_features_enabled():
        return _original_scene_header_draw_props(self, layout, dropdown_label, header_index, obj)
    from ...z64.collection_utility import drawAddButton, drawCollectionOps
    from ...z64.scene.operators import OOT_SearchMusicSeqEnumOperator
    from ...z64.utility import drawEnumWithCustom

    if dropdown_label is not None:
        layout.prop(self, "expandTab", text=dropdown_label, icon="TRIA_DOWN" if self.expandTab else "TRIA_RIGHT")
        if not self.expandTab:
            return
    if header_index is not None and header_index > 3:
        drawCollectionOps(layout, header_index - game_data.z64.cs_index_start, "Scene", None, obj.name)

    menu_box = layout.grid_flow(row_major=True, align=True, columns=3)
    if header_index is None or header_index == 0:
        menu_box.prop(self, "menuTab", expand=True)
        menu_tab = self.menuTab
    else:
        menu_box.prop(self, "altMenuTab", expand=True)
        menu_tab = self.altMenuTab

    with _using_mm_game_data():
        if menu_tab == "General":
            general = layout.column()
            general.box().label(text="General")
            drawEnumWithCustom(general, self, "globalObject", "Global Object", "")
            if header_index is None or header_index == 0:
                self.sceneTableEntry.draw_props(general)
                prop_split(general, self, "title_card_name", "Title Card")
            general.prop(self, "hm64_mm_set_region_visited", text="Set Region Visited")
            general.prop(self, "appendNullEntrance")

            skybox_sound = layout.column()
            skybox_sound.box().label(text="Skybox And Sound")
            prop_split(skybox_sound, self, "skybox_texture_id", "Skybox Texture ID")
            drawEnumWithCustom(skybox_sound, self, "skyboxID", "Skybox", "")
            drawEnumWithCustom(skybox_sound, self, "skyboxCloudiness", "Skybox Config", "")
            drawEnumWithCustom(skybox_sound, self, "musicSeq", "Music Sequence", "")
            music_search = skybox_sound.operator(OOT_SearchMusicSeqEnumOperator.bl_idname, icon="VIEWZOOM")
            music_search.objName = obj.name
            music_search.headerIndex = header_index if header_index is not None else 0
            drawEnumWithCustom(skybox_sound, self, "nightSeq", "Nighttime SFX", "")
            drawEnumWithCustom(skybox_sound, self, "audioSessionPreset", "Audio Session Preset", "")
        elif menu_tab == "Lighting":
            lighting = layout.column()
            lighting.box().label(text="Lighting List")
            drawEnumWithCustom(lighting, self, "skyboxLighting", "Lighting Mode", "")
            if self.skyboxLighting == "LIGHT_MODE_TIME":
                self.timeOfDayLights.draw_props(lighting.box(), None, header_index, obj.name)
                for index, tod_light in enumerate(self.tod_lights):
                    tod_light.draw_props(lighting.box(), index, header_index, obj.name)
                drawAddButton(lighting, len(self.tod_lights), "ToD Light", header_index, obj.name)
            else:
                for index in range(len(self.lightList)):
                    self.lightList[index].draw_props(
                        lighting, f"Lighting {index}", True, index, header_index, obj.name, "Light"
                    )
                drawAddButton(lighting, len(self.lightList), "Light", header_index, obj.name)
        elif menu_tab == "Cutscene":
            cutscene = layout.column()
            row = cutscene.row()
            row.prop(self, "writeCutscene", text="Write Cutscene")
            if self.writeCutscene:
                row.prop(self, "csWriteType", text="Data")
                if self.csWriteType == "Custom":
                    cutscene.prop(self, "csWriteCustom")
                else:
                    cutscene.prop(self, "csWriteObject")
            if header_index is None or header_index == 0:
                cutscene.label(text="Extra cutscenes (not in any header):")
                for index in range(len(self.extraCutscenes)):
                    box = cutscene.box().column()
                    drawCollectionOps(box, index, "extraCutscenes", None, obj.name, True)
                    box.prop(self.extraCutscenes[index], "csObject", text="CS obj")
                if len(self.extraCutscenes) == 0:
                    drawAddButton(cutscene, 0, "extraCutscenes", 0, obj.name)
        elif menu_tab == "Exits":
            exit_box = layout.column()
            exit_box.box().label(text="Exit List")
            for index in range(len(self.exitList)):
                self.exitList[index].draw_props(exit_box, index, header_index, obj.name)
            drawAddButton(exit_box, len(self.exitList), "Exit", header_index, obj.name)
        elif menu_tab == "AnimMats":
            if header_index is not None:
                layout.prop(self, "reuse_anim_mat", text="Use Existing Material Anim.")
            self.animated_material.draw_props(layout, obj, None, header_index)


def _hm64_room_header_draw_props(self, layout, dropdown_label, header_index, obj_name):
    if not hm64_mm_features_enabled():
        return _original_room_header_draw_props(self, layout, dropdown_label, header_index, obj_name)
    with _using_mm_game_data():
        _original_room_header_draw_props(self, layout, dropdown_label, header_index, obj_name)
    mm_box = layout.column()
    mm_box.box().label(text="MM Room Behavior")
    mm_box.prop(self, "hm64_mm_enable_pos_lights", text="Enable Pos Lights")
    mm_box.prop(self, "hm64_mm_enable_storm", text="Enable Storm")


def _mm_story_headers(alternate_headers, room=False):
    if room:
        return [
            alternate_headers.childNightHeader,
            alternate_headers.adultDayHeader,
            alternate_headers.adultNightHeader,
            *alternate_headers.cutsceneHeaders,
        ]
    return list(alternate_headers.cutsceneHeaders)


def _mm_story_header_index(alternate_headers, room=False):
    return min(max(1, alternate_headers.hm64_mm_story_index), len(_mm_story_headers(alternate_headers, room)))


def _hm64_scene_alt_draw_props(self, layout, obj):
    if not hm64_mm_features_enabled():
        return _original_scene_alt_draw_props(self, layout, obj)
    headers = _mm_story_headers(self)
    if not headers:
        layout.label(text="No alternate story configurations were imported.", icon="INFO")
        return
    header_setup = layout.column()
    prop_split(header_setup, self, "hm64_mm_story_index", "Story Configuration")
    index = _mm_story_header_index(self)
    header_setup.label(text=f"Story Configuration {index} of {len(headers)}")
    header = headers[index - 1]
    header_setup.prop(header, "usePreviousHeader", text="Use Base Configuration")
    if header.usePreviousHeader:
        return
    with _using_mm_game_data():
        header.draw_props(header_setup, None, min(index, 3), obj)


def _hm64_room_alt_draw_props(self, layout, obj_name):
    if not hm64_mm_features_enabled():
        return _original_room_alt_draw_props(self, layout, obj_name)
    headers = _mm_story_headers(self, room=True)
    if not headers:
        layout.label(text="No alternate story configurations were imported.", icon="INFO")
        return
    header_setup = layout.column()
    prop_split(header_setup, self, "hm64_mm_story_index", "Story Configuration")
    index = _mm_story_header_index(self, room=True)
    header_setup.label(text=f"Story Configuration {index} of {len(headers)}")
    header = headers[index - 1]
    header_setup.prop(header, "usePreviousHeader", text="Use Base Configuration")
    if header.usePreviousHeader:
        return
    with _using_mm_game_data():
        header.draw_props(header_setup, None, min(index, 3), obj_name)


def register():
    global _original_export_execute, _original_draw_props, _original_import_scene, _original_draw_scene_search
    global _original_actor_draw_props, _original_object_draw_props, _original_object_panel_draw
    global _original_scene_alt_draw_props, _original_room_alt_draw_props
    global _original_scene_header_draw_props, _original_room_header_draw_props
    if _original_export_execute is not None:
        return
    register_class(HM64MMHalfdayItem)
    register_class(HM64MMActorHalfdayAdd)
    register_class(HM64MMActorHalfdayRemove)
    register_class(HM64MMActorHalfdayMove)
    register_class(HM64SearchMMActorOperator)
    register_class(HM64SearchMMObjectOperator)
    register_class(HM64_SearchMMSceneOperator)
    bpy.types.Scene.hm64_mm_scene_import_option = EnumProperty(items=mm_enum_scene_id, default="SCENE_20SICHITAI2")
    bpy.types.Scene.hm64_mm_scene_export_option = EnumProperty(items=mm_enum_scene_id, default="SCENE_20SICHITAI2")
    OOTActorProperty.hm64_mm_actor_id = EnumProperty(
        name="Actor ID", items=_HM64_MM_ACTOR_ITEMS, get=_mm_actor_get, set=_mm_actor_set
    )
    OOTObjectProperty.hm64_mm_object_key = EnumProperty(
        name="Object ID", items=_HM64_MM_OBJECT_ITEMS, get=_mm_object_get, set=_mm_object_set
    )
    OOTActorProperty.hm64_mm_menu_tab = EnumProperty(items=_HM64_MM_ACTOR_MENU, default="General")
    OOTActorProperty.hm64_mm_halfday_show_entries = BoolProperty(default=True)
    OOTActorProperty.hm64_mm_halfday_all = BoolProperty(default=True)
    OOTActorProperty.hm64_mm_halfday_all_dawns = BoolProperty(default=False)
    OOTActorProperty.hm64_mm_halfday_all_nights = BoolProperty(default=False)
    OOTActorProperty.hm64_mm_halfday_bits = CollectionProperty(type=HM64MMHalfdayItem)
    OOTActorProperty.hm64_mm_use_global_actor_cs = BoolProperty(name="Use Global Actor Cutscene", default=False)
    OOTActorProperty.hm64_mm_actor_cs_index = IntProperty(min=0, max=127, default=127)
    OOTActorHeaderProperty.hm64_mm_include_in_all_setups = BoolProperty(
        name="Include in all scene setups", default=True
    )
    OOTActorHeaderProperty.hm64_mm_expand_tab = BoolProperty(name="Expand Tab", default=False)
    OOTSceneHeaderProperty.skybox_texture_id = StringProperty(name="Skybox Texture ID", default="0x00")
    OOTSceneHeaderProperty.hm64_mm_set_region_visited = BoolProperty(name="Set Region Visited")
    OOTRoomHeaderProperty.hm64_mm_enable_pos_lights = BoolProperty(name="Enable Pos Lights")
    OOTRoomHeaderProperty.hm64_mm_enable_storm = BoolProperty(name="Enable Storm")
    OOTAlternateSceneHeaderProperty.hm64_mm_story_index = IntProperty(name="Story Configuration", default=1, min=1)
    OOTAlternateRoomHeaderProperty.hm64_mm_story_index = IntProperty(name="Story Configuration", default=1, min=1)
    _original_export_execute = OOT_ExportScene.execute
    _original_draw_props = OOTExportSceneSettingsProperty.draw_props
    _original_import_scene = scene_operators.parseScene
    _original_draw_scene_search = scene_panels.OOT_ExportScenePanel.drawSceneSearchOp
    _original_actor_draw_props = OOTActorProperty.draw_props
    _original_object_draw_props = OOTObjectProperty.draw_props
    _original_object_panel_draw = props_panel_main.OOTObjectPanel.draw
    _original_scene_alt_draw_props = OOTAlternateSceneHeaderProperty.draw_props
    _original_room_alt_draw_props = OOTAlternateRoomHeaderProperty.draw_props
    _original_scene_header_draw_props = OOTSceneHeaderProperty.draw_props
    _original_room_header_draw_props = OOTRoomHeaderProperty.draw_props
    OOT_ExportScene.execute = _hm64_export_execute
    OOTExportSceneSettingsProperty.draw_props = _hm64_draw_props
    scene_operators.parseScene = _hm64_import_scene
    scene_panels.OOT_ExportScenePanel.drawSceneSearchOp = _hm64_draw_scene_search
    OOTActorProperty.draw_props = _hm64_actor_draw_props
    OOTObjectProperty.draw_props = _hm64_object_draw_props
    props_panel_main.OOTObjectPanel.draw = _hm64_object_panel_draw
    OOTAlternateSceneHeaderProperty.draw_props = _hm64_scene_alt_draw_props
    OOTAlternateRoomHeaderProperty.draw_props = _hm64_room_alt_draw_props
    OOTSceneHeaderProperty.draw_props = _hm64_scene_header_draw_props
    OOTRoomHeaderProperty.draw_props = _hm64_room_header_draw_props


def unregister():
    global _original_export_execute, _original_draw_props, _original_import_scene, _original_draw_scene_search
    global _original_actor_draw_props, _original_object_draw_props, _original_object_panel_draw
    global _original_scene_alt_draw_props, _original_room_alt_draw_props
    global _original_scene_header_draw_props, _original_room_header_draw_props
    if _original_export_execute is None:
        return
    OOT_ExportScene.execute = _original_export_execute
    OOTExportSceneSettingsProperty.draw_props = _original_draw_props
    scene_operators.parseScene = _original_import_scene
    scene_panels.OOT_ExportScenePanel.drawSceneSearchOp = _original_draw_scene_search
    OOTActorProperty.draw_props = _original_actor_draw_props
    OOTObjectProperty.draw_props = _original_object_draw_props
    props_panel_main.OOTObjectPanel.draw = _original_object_panel_draw
    OOTAlternateSceneHeaderProperty.draw_props = _original_scene_alt_draw_props
    OOTAlternateRoomHeaderProperty.draw_props = _original_room_alt_draw_props
    OOTSceneHeaderProperty.draw_props = _original_scene_header_draw_props
    OOTRoomHeaderProperty.draw_props = _original_room_header_draw_props
    del bpy.types.Scene.hm64_mm_scene_import_option
    del bpy.types.Scene.hm64_mm_scene_export_option
    del OOTActorProperty.hm64_mm_actor_id
    del OOTObjectProperty.hm64_mm_object_key
    del OOTActorProperty.hm64_mm_menu_tab
    del OOTActorProperty.hm64_mm_halfday_show_entries
    del OOTActorProperty.hm64_mm_halfday_all
    del OOTActorProperty.hm64_mm_halfday_all_dawns
    del OOTActorProperty.hm64_mm_halfday_all_nights
    del OOTActorProperty.hm64_mm_halfday_bits
    del OOTActorProperty.hm64_mm_use_global_actor_cs
    del OOTActorProperty.hm64_mm_actor_cs_index
    del OOTActorHeaderProperty.hm64_mm_include_in_all_setups
    del OOTActorHeaderProperty.hm64_mm_expand_tab
    del OOTSceneHeaderProperty.skybox_texture_id
    del OOTSceneHeaderProperty.hm64_mm_set_region_visited
    del OOTRoomHeaderProperty.hm64_mm_enable_pos_lights
    del OOTRoomHeaderProperty.hm64_mm_enable_storm
    del OOTAlternateSceneHeaderProperty.hm64_mm_story_index
    del OOTAlternateRoomHeaderProperty.hm64_mm_story_index
    unregister_class(HM64_SearchMMSceneOperator)
    unregister_class(HM64SearchMMObjectOperator)
    unregister_class(HM64SearchMMActorOperator)
    unregister_class(HM64MMActorHalfdayMove)
    unregister_class(HM64MMActorHalfdayRemove)
    unregister_class(HM64MMActorHalfdayAdd)
    unregister_class(HM64MMHalfdayItem)
    _original_export_execute = None
    _original_draw_props = None
    _original_import_scene = None
    _original_draw_scene_search = None
    _original_actor_draw_props = None
    _original_object_draw_props = None
    _original_object_panel_draw = None
    _original_scene_alt_draw_props = None
    _original_room_alt_draw_props = None
    _original_scene_header_draw_props = None
    _original_room_header_draw_props = None
