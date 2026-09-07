from __future__ import annotations

import os
import re
import struct
from contextlib import contextmanager
from pathlib import Path

import bpy

from ...utility import PluginError, hexOrDecInt, prop_split, toAlnum
from ...game_data import game_data
from ...data.z64.actor_data import Z64_ActorData
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
from ...z64.scene.properties import OOTExportSceneSettingsProperty
from ...z64.utility import getEvalParamsInt, getObjectList, ootSceneDungeons, sceneNameFromID
from ..f3d.soh_xml_exporter import register as ensure_hm64_soh_xml
from ..f3d.f3d_texture_writer_hm64 import register as ensure_hm64_texture_writer
from ..f3d.hm64_f3d_writer import TriangleConverterInfo, getInfoDict, saveStaticModel
from ..utility import is_hm64, writeXMLData
from .o2r_import import get_hm64_o2r_source, normalize_o2r_path
from .o2r_object_ids import O2R_OBJECT_IDS


_RESOURCE_HEADER_SIZE = 0x40
_RESOURCE_MAGIC = 0xDEADBEEFDEADBEEF
_OOT_ACTORS = None
_oot_actor_ids = None
_HM64_SCENE_IS_OOT = True
_HM64_ACTOR_REF = "_hm64_o2r_actor_ref"
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


def _actor_entry(writer: _Writer, actor):
    writer.u16(_actor_id(actor.id))
    for value in actor.pos:
        writer.s16(value)
    for value in str(actor.rot).split(","):
        writer.s16(_binary_angle(value))
    writer.u16(_number(actor.params, "actor parameters"))


def _actor_id(value) -> int:
    global _OOT_ACTORS, _oot_actor_ids
    text = str(value).strip()
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


def _write_pathways(pathways) -> bytes:
    writer = _Writer(b"HTPO")
    writer.u32(len(pathways.pathList))
    for path in pathways.pathList:
        writer.u32(len(path.points))
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
    for actor in actors:
        if isinstance(actor, bytes):
            writer.data.extend(actor)
        else:
            _actor_entry(writer, actor)
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
        and Utility.isCurrentHeaderValid(actor.ootActorProperty.headerSettings, header_index)
    ]


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


def _scene_header_variants(scene):
    headers = [scene.mainHeader]
    if scene.altHeader is None:
        return headers
    headers.extend([scene.altHeader.childNight, scene.altHeader.adultDay, scene.altHeader.adultNight])
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
    data = archive.file(path)
    if data is None:
        return []
    paths = [path]
    paths.extend(_header_command_paths(data, _CMD["ALTERNATE_HEADERS"]))
    return [archive.file(header_path) if header_path else None for header_path in paths]


def _tag_imported_room_actors(scene_obj, internal_directory: str, archive):
    for room_obj in (obj for obj in scene_obj.children if obj.type == "EMPTY" and obj.ootEmptyType == "Room"):
        source_headers = _base_room_header_resources(internal_directory, room_obj.name, archive)
        for header_index, source_header in enumerate(source_headers):
            source_actors = _source_entries(_header_commands(source_header).get(_CMD["ACTORS"]), 16)
            actor_objects = _room_actor_objects(scene_obj, room_obj, header_index)
            indices = list(range(min(len(actor_objects), len(source_actors))))
            for actor_obj, source_index in zip(actor_objects, indices):
                actor_obj[_HM64_ACTOR_REF] = f"{room_obj.ootRoomHeader.roomIndex}:{header_index}:{source_index}"


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


def export_hm64_scene(scene_obj, transform, settings):
    if settings.option == "Custom":
        raise PluginError("HM64 scene export currently replaces a selected scene; choose a Scene ID.")
    if not settings.exportPath.strip():
        raise PluginError("Set an HM64 scene export directory.")
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


def _hm64_import_scene(settings, option):
    result = _original_import_scene(settings, option)
    if not is_hm64() or not (bpy.context.scene.hm64_o2r_path or "").strip() or option == "Custom":
        return result
    scene_obj = bpy.context.scene.ootSceneExportObj
    if scene_obj is None:
        return result
    level_name = sceneNameFromID(option)
    scene_name = f"{toAlnum(level_name)}_scene"
    category = "nonmq" if level_name in ootSceneDungeons else "shared"
    source = get_hm64_o2r_source(bpy.context.scene).archive
    _tag_imported_room_actors(scene_obj, f"scenes/{category}/{scene_name}", _reference_archive(source))
    return result


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
    prop_split(layout, self, "option", "Scene ID")
    prop_split(layout, self, "exportPath", "Directory")
    prop_split(layout, bpy.context.scene, "ootSceneExportObj", "Scene Object")
    prop_split(layout, bpy.context.scene, "hm64_o2r_path", "Base O2R")
    layout.prop(self, "auto_add_room_objects")


def register():
    global _original_export_execute, _original_draw_props, _original_import_scene
    if _original_export_execute is not None:
        return
    _original_export_execute = OOT_ExportScene.execute
    _original_draw_props = OOTExportSceneSettingsProperty.draw_props
    _original_import_scene = scene_operators.parseScene
    OOT_ExportScene.execute = _hm64_export_execute
    OOTExportSceneSettingsProperty.draw_props = _hm64_draw_props
    scene_operators.parseScene = _hm64_import_scene


def unregister():
    global _original_export_execute, _original_draw_props, _original_import_scene
    if _original_export_execute is None:
        return
    OOT_ExportScene.execute = _original_export_execute
    OOTExportSceneSettingsProperty.draw_props = _original_draw_props
    scene_operators.parseScene = _original_import_scene
    _original_export_execute = None
    _original_draw_props = None
    _original_import_scene = None
