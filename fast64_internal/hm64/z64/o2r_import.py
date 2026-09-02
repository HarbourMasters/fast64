from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import bpy
import mathutils
from bpy.props import BoolProperty, StringProperty
from bpy.types import Scene

from ...utility import PluginError, applyRotation, deselectAllObjects, prop_split, selectSingleObject
from ...f3d.f3d_gbi import get_F3D_GBI
from ...f3d.f3d_parser import importMeshC, parseF3D
from ...z64.model_classes import OOTF3DContext
from ...z64.skeleton.importer.functions import OOTDLEntry, ootAddBone
from ...z64.skeleton.constants import ootSkeletonImportDict
from ...z64.skeleton.utility import applySkeletonRestPose
from ...z64.utility import getOOTScale
from ...f3d.flipbook import TextureFlipbook
from ...data.z64.data import mm_skeleton_dict
from ..utility import crc64, is_hm64
from .o2r_flipbooks import O2R_MM_SKELETON_FLIPBOOKS, O2R_SKELETON_FLIPBOOKS


def normalize_o2r_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip("/")


class HM64O2RArchive:
    def __init__(self, archive_path: str, fallbacks: tuple[HM64O2RArchive, ...] = ()):
        self.archive_path = Path(archive_path)
        self.fallbacks = fallbacks
        self._entries: list[str] | None = None
        self._entry_set: set[str] | None = None
        self._crc_index: dict[int, str] | None = None

    def _zip_error(self, exc: Exception):
        raise PluginError(f"Could not read O2R archive '{self.archive_path}': {exc}") from exc

    @property
    def entries(self) -> list[str]:
        if self._entries is None:
            try:
                with ZipFile(self.archive_path, "r") as archive:
                    self._entries = archive.namelist()
            except (BadZipFile, OSError) as exc:
                self._zip_error(exc)
        return self._entries

    @property
    def entry_set(self) -> set[str]:
        if self._entry_set is None:
            self._entry_set = set(self.entries)
        return self._entry_set

    @property
    def crc_index(self) -> dict[int, str]:
        if self._crc_index is None:
            self._crc_index = {int(crc64(entry), 16): entry for entry in self.entries}
        return self._crc_index

    def has(self, path: str) -> bool:
        return self.resolve_path(path) is not None

    def resolve_path(self, path: str) -> str | None:
        normalized = normalize_o2r_path(path)
        if normalized in self.entry_set:
            return normalized
        alternate = f"alt/{normalized}"
        if alternate in self.entry_set:
            return alternate
        return next(
            (fallback.resolve_path(normalized) for fallback in self.fallbacks if fallback.has(normalized)), None
        )

    def file(self, path: str) -> bytes | None:
        normalized = normalize_o2r_path(path)
        resolved = normalized if normalized in self.entry_set else f"alt/{normalized}"
        if resolved not in self.entry_set:
            return next((data for fallback in self.fallbacks if (data := fallback.file(normalized)) is not None), None)
        try:
            with ZipFile(self.archive_path, "r") as archive:
                return archive.read(resolved)
        except (BadZipFile, OSError, KeyError) as exc:
            self._zip_error(exc)

    def files_by_prefix(self, prefix: str) -> dict[str, bytes]:
        normalized_prefix = normalize_o2r_path(prefix)
        if normalized_prefix:
            normalized_prefix += "/"
        try:
            with ZipFile(self.archive_path, "r") as archive:
                return {entry: archive.read(entry) for entry in self.entries if entry.startswith(normalized_prefix)}
        except (BadZipFile, OSError, KeyError) as exc:
            self._zip_error(exc)

    def find_path_by_crc64(self, hash_value: int | str) -> str | None:
        if isinstance(hash_value, str):
            hash_value = int(hash_value, 16)
        return self.crc_index.get(hash_value) or next(
            (path for fallback in self.fallbacks if (path := fallback.find_path_by_crc64(hash_value)) is not None), None
        )

    def find_path_by_name(self, name: str, preferred_prefix: str = "") -> str | None:
        matches = [entry for entry in self.entries if Path(entry).name == name]
        if preferred_prefix:
            preferred = next((entry for entry in matches if entry.startswith(preferred_prefix + "/")), None)
            if preferred:
                return preferred
        return (
            matches[0]
            if matches
            else next(
                (
                    path
                    for fallback in self.fallbacks
                    if (path := fallback.find_path_by_name(name, preferred_prefix)) is not None
                ),
                None,
            )
        )


@dataclass(frozen=True)
class HM64ImportSource:
    kind: str
    path: str
    archive: HM64O2RArchive | None = None

    @property
    def is_o2r(self) -> bool:
        return self.kind == "o2r"


@dataclass(frozen=True)
class HM64O2RVertex:
    position: tuple[int, int, int]
    uv: tuple[int, int]
    color: tuple[int, int, int, int]

    @property
    def normal(self) -> tuple[float, float, float]:
        return tuple((value if value < 128 else value - 256) / 127 for value in self.color[:3])


def _resolve_path(path_value: str) -> Path:
    return Path(bpy.path.abspath(path_value)).expanduser().resolve()


def get_hm64_o2r_source(scene=None) -> HM64ImportSource:
    scene = scene or bpy.context.scene
    archive_path_value = (scene.hm64_o2r_path or "").strip()
    if not archive_path_value:
        raise PluginError("Select an O2R archive before importing.")

    archive_path = _resolve_path(archive_path_value)
    if not archive_path.is_file():
        raise PluginError(f"O2R archive does not exist: '{archive_path}'.")
    if archive_path.suffix.lower() != ".o2r":
        raise PluginError("Not an O2R archive!")
    fallback_path = next(
        (parent / "oot.o2r" for parent in archive_path.parents if (parent / "oot.o2r").is_file()), None
    )
    fallbacks = (HM64O2RArchive(str(fallback_path)),) if fallback_path and fallback_path != archive_path else ()
    return HM64ImportSource("o2r", str(archive_path), HM64O2RArchive(str(archive_path), fallbacks))


def _resource_type(data: bytes) -> str:
    byte_order = "little" if data[0] == 0 else "big"
    return int.from_bytes(data[4:8], byte_order).to_bytes(4, "big").decode("ascii", "replace")


def _xml_resource(data: bytes, tag: str | None = None) -> ElementTree.Element | None:
    if not data.lstrip().startswith(b"<"):
        return None
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise PluginError(f"Invalid O2R XML resource: {exc}") from exc
    if tag is not None and root.tag != tag:
        return None
    return root


def _read_oarr_vertices(data: bytes) -> list[HM64O2RVertex]:
    xml_root = _xml_resource(data, "Vertex")
    if xml_root is not None:
        return [
            HM64O2RVertex(
                tuple(int(vertex.attrib[axis]) for axis in ("X", "Y", "Z")),
                tuple(int(vertex.attrib[axis]) for axis in ("S", "T")),
                tuple(int(vertex.attrib[axis]) for axis in ("R", "G", "B", "A")),
            )
            for vertex in xml_root.findall("Vtx")
        ]
    if _resource_type(data) != "OARR":
        raise PluginError("Referenced O2R resource is not an OARR vertex array.")
    byte_order = "little" if data[0] == 0 else "big"
    array_type = int.from_bytes(data[0x40:0x44], byte_order)
    count = int.from_bytes(data[0x44:0x48], byte_order)
    if array_type != 25:
        raise PluginError(f"OARR array type {array_type} is not a vertex array.")
    payload_end = 0x48 + count * 16
    if payload_end > len(data):
        raise PluginError(f"OARR vertex array is truncated: expected {payload_end} bytes, got {len(data)}.")

    vertices: list[HM64O2RVertex] = []
    for offset in range(0x48, payload_end, 16):
        vertices.append(
            HM64O2RVertex(
                tuple(int.from_bytes(data[offset + n : offset + n + 2], byte_order, signed=True) for n in (0, 2, 4)),
                tuple(int.from_bytes(data[offset + n : offset + n + 2], byte_order, signed=True) for n in (8, 10)),
                tuple(data[offset + n] for n in (12, 13, 14, 15)),
            )
        )
    return vertices


class HM64O2RF3DSerializer:
    def __init__(self, archive: HM64O2RArchive):
        self.archive = archive
        self._vertex_symbols: dict[int, str] = {}
        self._display_symbols: dict[str, str] = {}
        self._vertex_declarations: list[str] = []
        self._display_declarations: list[str] = []
        self._texture_symbols: dict[int, str] = {}
        self._texture_metadata: dict[int, tuple[str, str, int]] = {}
        self.texture_paths: dict[str, str] = {}
        self._texture_declarations: list[str] = []
        self._matrix_symbols: dict[int, str] = {}
        self._matrix_declarations: list[str] = []

    @staticmethod
    def _symbol(prefix: str, value: str) -> str:
        return prefix + "_" + "".join(char if char.isalnum() else "_" for char in value)

    @staticmethod
    def _combiner(word0: int, word1: int) -> str:
        color_a = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "1", "NOISE"]
        color_b = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "CENTER", "K4"]
        color_c = [
            "COMBINED",
            "TEXEL0",
            "TEXEL1",
            "PRIMITIVE",
            "SHADE",
            "ENVIRONMENT",
            "SCALE",
            "COMBINED_ALPHA",
            "TEXEL0_ALPHA",
            "TEXEL1_ALPHA",
            "PRIMITIVE_ALPHA",
            "SHADE_ALPHA",
            "ENV_ALPHA",
            "LOD_FRACTION",
            "PRIM_LOD_FRAC",
            "K5",
        ]
        color_d = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "1", "0"]
        alpha = ["COMBINED", "TEXEL0", "TEXEL1", "PRIMITIVE", "SHADE", "ENVIRONMENT", "1", "0"]

        def pick(values, index):
            return values[index] if index < len(values) else "0"

        values = [
            pick(color_a, (word0 >> 20) & 0xF),
            pick(color_b, (word1 >> 28) & 0xF),
            pick(color_c, (word0 >> 15) & 0x1F),
            pick(color_d, (word1 >> 15) & 7),
            pick(alpha, (word0 >> 12) & 7),
            pick(alpha, (word1 >> 12) & 7),
            pick(alpha, (word0 >> 9) & 7),
            pick(alpha, (word1 >> 9) & 7),
            pick(color_a, (word0 >> 5) & 0xF),
            pick(color_b, (word1 >> 24) & 0xF),
            pick(color_c, word0 & 0x1F),
            pick(color_d, (word1 >> 6) & 7),
            pick(alpha, (word1 >> 21) & 7),
            pick(alpha, (word1 >> 3) & 7),
            pick(alpha, (word1 >> 18) & 7),
            pick(alpha, word1 & 7),
        ]
        return "gsDPSetCombineLERP(" + ", ".join(values) + ")"

    def _vertices(self, hash_value: int) -> str:
        if hash_value in self._vertex_symbols:
            return self._vertex_symbols[hash_value]
        path = self.archive.find_path_by_crc64(hash_value)
        if path is None:
            raise PluginError(f"O2R vertex resource hash {hash_value:016x} could not be resolved.")
        data = self.archive.file(path)
        if data is None:
            raise PluginError(f"O2R vertex resource '{path}' could not be read.")
        name = self._symbol("o2r_vtx", f"{hash_value:016x}")
        records = _read_oarr_vertices(data)
        values = []
        for vertex in records:
            x, y, z = vertex.position
            s, t = vertex.uv
            r, g, b, a = vertex.color
            values.append(f"{{{{ {{ {x}, {y}, {z} }}, 0, {{ {s}, {t} }}, {{ {r}, {g}, {b}, {a} }} }}}}")
        self._vertex_declarations.append(f"Vtx {name}[{len(records)}] = {{ {', '.join(values)} }};")
        self._vertex_symbols[hash_value] = name
        return name

    def _resource_hash(self, path: str) -> int:
        normalized = normalize_o2r_path(path)
        if not self.archive.has(normalized):
            raise PluginError(f"O2R resource '{path}' could not be resolved.")
        key = normalized if normalized not in self.archive.entry_set else normalized
        if normalized not in self.archive.entry_set and f"alt/{normalized}" in self.archive.entry_set:
            key = f"alt/{normalized}"
        return int(crc64(key), 16)

    def _vertices_path(self, path: str) -> str:
        return self._vertices(self._resource_hash(path))

    @staticmethod
    def _image_format(texture_type: int) -> tuple[str, str]:
        formats = {
            1: ("G_IM_FMT_RGBA", "G_IM_SIZ_32b"),
            2: ("G_IM_FMT_RGBA", "G_IM_SIZ_16b"),
            3: ("G_IM_FMT_CI", "G_IM_SIZ_4b"),
            4: ("G_IM_FMT_CI", "G_IM_SIZ_8b"),
            5: ("G_IM_FMT_I", "G_IM_SIZ_4b"),
            6: ("G_IM_FMT_I", "G_IM_SIZ_8b"),
            7: ("G_IM_FMT_IA", "G_IM_SIZ_4b"),
            8: ("G_IM_FMT_IA", "G_IM_SIZ_8b"),
            9: ("G_IM_FMT_IA", "G_IM_SIZ_16b"),
        }
        try:
            return formats[texture_type]
        except KeyError as exc:
            raise PluginError(f"OTEX texture type {texture_type} is not supported.") from exc

    def _texture(self, hash_value: int) -> tuple[str, str, str, int]:
        if hash_value in self._texture_symbols:
            texture = self._texture_symbols[hash_value]
            return texture, *self._texture_metadata[hash_value]
        path = self.archive.find_path_by_crc64(hash_value)
        if path is None:
            raise PluginError(f"O2R texture resource hash {hash_value:016x} could not be resolved.")
        data = self.archive.file(path)
        if data is None:
            raise PluginError(f"O2R texture resource '{path}' could not be read.")
        texture_type, width, _height, pixels = _read_otex_raw(data)
        image_format, image_size = self._image_format(texture_type)
        name = Path(path).name
        if not name.isidentifier():
            raise PluginError(f"O2R texture resource '{path}' does not have a C-compatible name.")
        existing_hash = next((value for value, symbol in self._texture_symbols.items() if symbol == name), None)
        if existing_hash is not None and existing_hash != hash_value:
            raise PluginError(f"O2R texture name '{name}' is shared by multiple resources.")
        self._texture_symbols[hash_value] = name
        self._texture_metadata[hash_value] = (image_format, image_size, width)
        logical_path = path[4:] if path.startswith("alt/") else path
        self.texture_paths[name] = str(Path(logical_path).parent).replace("\\", "/")
        self._texture_declarations.append(f"u8 {name}[] = {{ {', '.join(str(value) for value in pixels)} }};")
        return name, image_format, image_size, width

    def _texture_path(self, path: str) -> tuple[str, str, str, int]:
        return self._texture(self._resource_hash(path))

    def _matrix(self, hash_value: int) -> str:
        if hash_value in self._matrix_symbols:
            return self._matrix_symbols[hash_value]
        path = self.archive.find_path_by_crc64(hash_value)
        data = self.archive.file(path) if path else None
        if data is None or _resource_type(data) != "OMTX" or len(data) < 0x80:
            raise PluginError(f"O2R matrix resource hash {hash_value:016x} could not be read.")
        name = self._symbol("o2r_mtx", f"{hash_value:016x}")
        values = [int.from_bytes(data[0x40 + index * 4 : 0x44 + index * 4], "little") for index in range(16)]
        self._matrix_symbols[hash_value] = name
        self._matrix_declarations.append(f"Mtx {name} = {{ {', '.join(f'0x{value:08X}' for value in values)} }};")
        return name

    def _matrix_path(self, path: str) -> str:
        return self._matrix(self._resource_hash(path))

    @staticmethod
    def _tile_mode(value: int) -> str:
        modes = ("G_TX_WRAP", "G_TX_MIRROR", "G_TX_CLAMP", "G_TX_MIRROR | G_TX_CLAMP")
        return modes[value & 3]

    @staticmethod
    def _xml_pointer(path: str) -> str:
        return path[1:] if path.startswith(">") else path

    @staticmethod
    def _xml_other_mode_commands(attr: dict[str, str]) -> list[str]:
        commands = []
        field_macros = (
            ("G_AD_", "gsDPSetAlphaDither"),
            ("G_CD_", "gsDPSetColorDither"),
            ("G_CK_", "gsDPSetCombineKey"),
            ("G_CYC_", "gsDPSetCycleType"),
            ("G_TC_", "gsDPSetTextureConvert"),
            ("G_TD_", "gsDPSetTextureDetail"),
            ("G_TF_", "gsDPSetTextureFilter"),
            ("G_TL_", "gsDPSetTextureLOD"),
            ("G_TP_", "gsDPSetTexturePersp"),
            ("G_TT_", "gsDPSetTextureLUT"),
            ("G_AC_", "gsDPSetAlphaCompare"),
            ("G_ZS_", "gsDPSetDepthSource"),
        )
        for prefix, macro in field_macros:
            value = next((key for key, enabled in attr.items() if enabled == "1" and key.startswith(prefix)), None)
            if value is not None:
                commands.append(f"{macro}({value})")
        render_modes = [key for key, enabled in attr.items() if enabled == "1" and key.startswith("G_RM_")]
        if render_modes:
            commands.append(f"gsDPSetRenderMode({', '.join(render_modes)})")
        return commands

    def _xml_display_list(self, path: str, root: ElementTree.Element) -> str:
        name = self._symbol("o2r_dl", path)
        self._display_symbols[path] = name
        commands: list[str] = []
        for element in root:
            attr = element.attrib
            tag = element.tag
            if tag == "PipeSync":
                commands.append("gsDPPipeSync()")
            elif tag == "LoadSync":
                commands.append("gsDPLoadSync()")
            elif tag == "TileSync":
                commands.append("gsDPTileSync()")
            elif tag == "EndDisplayList":
                commands.append("gsSPEndDisplayList()")
            elif tag == "SetTextureLUT":
                commands.append(f"gsDPSetTextureLUT({attr['Mode']})")
            elif tag == "Texture":
                commands.append(f"gsSPTexture({attr['S']}, {attr['T']}, {attr['Level']}, {attr['Tile']}, {attr['On']})")
            elif tag == "SetTextureImage":
                texture_path = attr["Path"]
                image = (
                    self._xml_pointer(texture_path)
                    if texture_path.startswith(">")
                    else self._texture_path(texture_path)[0]
                )
                commands.append(f"gsDPSetTextureImage({attr['Format']}, {attr['Size']}, {attr['Width']}, {image})")
            elif tag == "SetTile":
                cmt = " | ".join((attr["Cmt0"], attr["Cmt1"]))
                cms = " | ".join((attr["Cms0"], attr["Cms1"]))
                commands.append(
                    f"gsDPSetTile({attr['Format']}, {attr['Size']}, {attr['Line']}, {attr['TMem']}, {attr['Tile']}, "
                    f"{attr['Palette']}, {cmt}, {attr['MaskT']}, {attr['ShiftT']}, "
                    f"{cms}, {attr['MaskS']}, {attr['ShiftS']})"
                )
            elif tag == "LoadBlock":
                commands.append(
                    f"gsDPLoadBlock({attr['Tile']}, {attr['Uls']}, {attr['Ult']}, {attr['Lrs']}, {attr['Dxt']})"
                )
            elif tag == "SetTileSize":
                commands.append(
                    f"gsDPSetTileSize({attr['T']}, {attr['Uls']}, {attr['Ult']}, {attr['Lrs']}, {attr['Lrt']})"
                )
            elif tag == "LoadTLUTCmd":
                commands.append(f"gsDPLoadTLUTCmd({attr['Tile']}, {attr['Count']})")
            elif tag == "SetCombineLERP":
                values = []
                for cycle in (0, 1):
                    for prefix in ("A", "B", "C", "D", "Aa", "Ab", "Ac", "Ad"):
                        value = attr[f"{prefix}{cycle}"]
                        values.append(
                            value.removeprefix("G_ACMUX_")
                            if prefix.startswith("A") and len(prefix) > 1
                            else value.removeprefix("G_CCMUX_")
                        )
                commands.append("gsDPSetCombineLERP(" + ", ".join(values) + ")")
            elif tag == "SetRenderMode":
                commands.append(f"gsDPSetRenderMode({attr['Mode1']}, {attr['Mode2']})")
            elif tag == "SetOtherMode":
                commands.extend(self._xml_other_mode_commands(attr))
            elif tag in {"ClearGeometryMode", "SetGeometryMode"}:
                flags = " | ".join(key for key, value in attr.items() if value == "1")
                if flags:
                    commands.append(f"gsSP{'Clear' if tag == 'ClearGeometryMode' else 'Set'}GeometryMode({flags})")
            elif tag in {"CallDisplayList", "JumpToDisplayList"}:
                target = attr["Path"]
                target = self._xml_pointer(target) if target.startswith(">") else self._display_list(target)
                macro = "gsSPDisplayList" if tag == "CallDisplayList" else "gsSPBranchList"
                commands.append(f"{macro}({target})")
            elif tag == "SetPrimColor":
                commands.append(
                    f"gsDPSetPrimColor({attr['M']}, {attr['L']}, {attr['R']}, {attr['G']}, {attr['B']}, {attr['A']})"
                )
            elif tag == "SetEnvColor":
                commands.append(f"gsDPSetEnvColor({attr['R']}, {attr['G']}, {attr['B']}, {attr['A']})")
            elif tag == "SetFogColor":
                commands.append(f"gsDPSetFogColor({attr['R']}, {attr['G']}, {attr['B']}, {attr['A']})")
            elif tag == "SetBlendColor":
                commands.append(f"gsDPSetBlendColor({attr['R']}, {attr['G']}, {attr['B']}, {attr['A']})")
            elif tag == "LoadVertices":
                commands.append(
                    f"gsSPVertex({self._vertices_path(attr['Path'])} + {attr['VertexOffset']}, {attr['Count']}, {attr['VertexBufferIndex']})"
                )
            elif tag == "Triangle1":
                commands.append(f"gsSP1Triangle({attr['V00']}, {attr['V01']}, {attr['V02']}, {attr.get('Flag0', '0')})")
            elif tag == "Triangles2":
                commands.append(
                    f"gsSP2Triangles({attr['V00']}, {attr['V01']}, {attr['V02']}, {attr.get('Flag0', '0')}, "
                    f"{attr['V10']}, {attr['V11']}, {attr['V12']}, {attr.get('Flag1', '0')})"
                )
            elif tag == "Matrix":
                matrix = (
                    self._xml_pointer(attr["Path"])
                    if attr["Path"].startswith(">")
                    else f"&{self._matrix_path(attr['Path'])}"
                )
                commands.append(
                    f"gsSPMatrix({matrix}, {attr.get('Param', 'G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_MODELVIEW')})"
                )
            else:
                raise PluginError(f"Unsupported O2R XML display-list command '{tag}'.")
        self._display_declarations.append(f"Gfx {name}[] = {{ {', '.join(commands)} }};")
        return name

    def _display_list(self, path: str) -> str:
        path = normalize_o2r_path(path)
        if path in self._display_symbols:
            return self._display_symbols[path]
        data = self.archive.file(path)
        if data is None:
            raise PluginError(f"O2R resource '{path}' is not a readable ODLT display list.")
        xml_root = _xml_resource(data, "DisplayList")
        if xml_root is not None:
            return self._xml_display_list(path, xml_root)
        if _resource_type(data) != "ODLT":
            raise PluginError(f"O2R resource '{path}' is not a readable ODLT display list.")
        name = self._symbol("o2r_dl", path)
        self._display_symbols[path] = name
        commands: list[str] = []
        offset = 0x48
        expanded = HM64O2RDisplayListReader._EXPANDED_OPCODES
        while offset + 8 <= len(data):
            word0 = int.from_bytes(data[offset : offset + 4], "little")
            word1 = int.from_bytes(data[offset + 4 : offset + 8], "little")
            opcode = word0 >> 24
            hash_value = (
                int.from_bytes(data[offset + 8 : offset + 12], "little") << 32
                | int.from_bytes(data[offset + 12 : offset + 16], "little")
                if opcode in expanded
                else 0
            )
            if opcode == 0xDF:
                commands.append("gsSPEndDisplayList()")
                break
            if opcode == 0x32:
                count = (word0 >> 12) & 0xFF
                start = ((word0 >> 1) & 0x7F) - count
                commands.append(f"gsSPVertex({self._vertices(hash_value)} + {word1 // 16}, {count}, {start})")
            elif opcode == 0x31:
                sub_path = self.archive.find_path_by_crc64(hash_value)
                if sub_path:
                    commands.append(f"gsSPDisplayList({self._display_list(sub_path)})")
            elif opcode == 0xDE:
                commands.append(f"gsSPDisplayList(0x{word1:08X})")
            elif opcode == 0x20:
                texture, image_format, image_size, width = self._texture(hash_value)
                commands.append(f"gsDPSetTextureImage({image_format}, {image_size}, {width}, {texture})")
            elif opcode == 0xFD:
                format_index = (word0 >> 21) & 7
                size_index = (word0 >> 19) & 3
                image_format = ("RGBA", "YUV", "CI", "IA", "I")[format_index] if format_index < 5 else "RGBA"
                image_size = (4, 8, 16, 32)[size_index]
                width = (word0 & 0xFFF) + 1
                commands.append(
                    f"gsDPSetTextureImage(G_IM_FMT_{image_format}, G_IM_SIZ_{image_size}b, {width}, 0x{word1:08X})"
                )
            elif opcode == 0x36:
                commands.append(f"gsSPMatrix(&{self._matrix(hash_value)}, 0x{word0 & 0xFF:02X})")
            elif opcode == 0xDA:
                commands.append(f"gsSPMatrix(0x{word1:08X}, 0x{word0 & 0xFF:02X})")
            elif opcode == 0x05:
                commands.append(
                    f"gsSP1Triangle({(word0 >> 16 & 0xFF) // 2}, {(word0 >> 8 & 0xFF) // 2}, {(word0 & 0xFF) // 2}, 0)"
                )
            elif opcode == 0x06:
                commands.append(
                    f"gsSP2Triangles({(word0 >> 16 & 0xFF) // 2}, {(word0 >> 8 & 0xFF) // 2}, {(word0 & 0xFF) // 2}, 0, {(word1 >> 16 & 0xFF) // 2}, {(word1 >> 8 & 0xFF) // 2}, {(word1 & 0xFF) // 2}, 0)"
                )
            elif opcode == 0xD9:
                clear_mask = (~word0) & 0x00FFFFFF
                if clear_mask:
                    commands.append(f"gsSPClearGeometryMode(0x{clear_mask:08X})")
                if word1:
                    commands.append(f"gsSPSetGeometryMode(0x{word1:08X})")
            elif opcode == 0xE2:
                length = (word0 & 0xFF) + 1
                shift = 32 - ((word0 >> 8) & 0xFF) - length
                commands.append(f"gsSPSetOtherMode(G_SETOTHERMODE_L, {shift}, {length}, 0x{word1:08X})")
            elif opcode == 0xE3:
                length = (word0 & 0xFF) + 1
                shift = 32 - ((word0 >> 8) & 0xFF) - length
                commands.append(f"gsSPSetOtherMode(G_SETOTHERMODE_H, {shift}, {length}, 0x{word1:08X})")
            elif opcode == 0xFA:
                commands.append(
                    f"gsDPSetPrimColor(0, 0, {(word1 >> 24) & 0xFF}, {(word1 >> 16) & 0xFF}, {(word1 >> 8) & 0xFF}, {word1 & 0xFF})"
                )
            elif opcode == 0xFB:
                commands.append(
                    f"gsDPSetEnvColor({(word1 >> 24) & 0xFF}, {(word1 >> 16) & 0xFF}, {(word1 >> 8) & 0xFF}, {word1 & 0xFF})"
                )
            elif opcode == 0xD7:
                commands.append(
                    f"gsSPTexture({word1 >> 16}, {word1 & 0xFFFF}, {(word0 >> 11) & 7}, {(word0 >> 8) & 7}, {word0 & 0xFF})"
                )
            elif opcode == 0xF5:
                commands.append(
                    "gsDPSetTile("
                    f"G_IM_FMT_{('RGBA', 'YUV', 'CI', 'IA', 'I')[((word0 >> 21) & 7) if ((word0 >> 21) & 7) < 5 else 0]}, "
                    f"G_IM_SIZ_{(4, 8, 16, 32)[(word0 >> 19) & 3]}b, {(word0 >> 9) & 0x1FF}, {word0 & 0x1FF}, "
                    f"{(word1 >> 24) & 7}, {(word1 >> 20) & 0xF}, {self._tile_mode((word1 >> 18) & 3)}, {(word1 >> 14) & 0xF}, {(word1 >> 10) & 0xF}, "
                    f"{self._tile_mode((word1 >> 8) & 3)}, {(word1 >> 4) & 0xF}, {word1 & 0xF})"
                )
            elif opcode == 0xF3:
                commands.append(
                    f"gsDPLoadBlock({(word1 >> 24) & 7}, {(word0 >> 12) & 0xFFF}, {word0 & 0xFFF}, {(word1 >> 12) & 0xFFF}, {word1 & 0xFFF})"
                )
            elif opcode == 0xF2:
                commands.append(
                    f"gsDPSetTileSize({(word1 >> 24) & 7}, {(word0 >> 12) & 0xFFF}, {word0 & 0xFFF}, {(word1 >> 12) & 0xFFF}, {word1 & 0xFFF})"
                )
            elif opcode == 0xF0:
                commands.append(f"gsDPLoadTLUTCmd({(word1 >> 24) & 7}, {(word1 >> 14) & 0x3FF})")
            elif opcode == 0xFC:
                commands.append(self._combiner(word0, word1))
            offset += 16 if opcode in expanded else 8
        self._display_declarations.append(f"Gfx {name}[] = {{ {', '.join(commands)} }};")
        return name

    def serialize(self, path: str) -> tuple[str, str]:
        root = self._display_list(path)
        return (
            "\n".join(
                [
                    *self._texture_declarations,
                    *self._matrix_declarations,
                    *self._vertex_declarations,
                    *self._display_declarations,
                ]
            ),
            root,
        )


class HM64O2RDisplayListReader:
    _EXPANDED_OPCODES = {0x20, 0x31, 0x32, 0x33, 0x35, 0x36, 0x42}

    def __init__(self, archive: HM64O2RArchive):
        self.archive = archive
        self._oarr_cache: dict[int, list[HM64O2RVertex]] = {}
        self._vertex_cache: list[tuple[int, int, bool] | None] = [None] * 64
        self._vertices: list[HM64O2RVertex] = []
        self._vertex_normals: list[tuple[float, float, float] | None] = []
        self._vertex_indices: dict[tuple[int, int, bool], int] = {}
        self.faces: list[tuple[int, int, int]] = []
        self.face_textures: list[int | None] = []
        self._current_texture_hash: int | None = None
        self._geometry_mode = 0

    def _oarr(self, hash_value: int) -> list[HM64O2RVertex]:
        cached = self._oarr_cache.get(hash_value)
        if cached is not None:
            return cached
        path = self.archive.find_path_by_crc64(hash_value)
        if path is None:
            raise PluginError(f"O2R vertex resource hash {hash_value:016x} could not be resolved.")
        data = self.archive.file(path)
        if data is None:
            raise PluginError(f"O2R vertex resource '{path}' could not be read.")
        vertices = _read_oarr_vertices(data)
        self._oarr_cache[hash_value] = vertices
        return vertices

    def _load_vertices(self, hash_value: int, byte_offset: int, count: int, cache_start: int):
        vertices = self._oarr(hash_value)
        source_start = byte_offset // 16
        for index in range(count):
            target = cache_start + index
            source = source_start + index
            if target >= len(self._vertex_cache) or source >= len(vertices):
                continue
            self._vertex_cache[target] = (hash_value, source, bool(self._geometry_mode & 0x00020000))

    def _mesh_vertex(self, cache_index: int) -> int | None:
        if not 0 <= cache_index < len(self._vertex_cache):
            return None
        source = self._vertex_cache[cache_index]
        if source is None:
            return None
        result = self._vertex_indices.get(source)
        if result is None:
            result = len(self._vertices)
            self._vertex_indices[source] = result
            self._vertices.append(self._oarr(source[0])[source[1]])
            self._vertex_normals.append(self._vertices[-1].normal if source[2] else None)
        return result

    def _triangle(self, a: int, b: int, c: int):
        face = tuple(self._mesh_vertex(index) for index in (a, b, c))
        if None not in face and len(set(face)) == 3:
            self.faces.append(face)
            self.face_textures.append(self._current_texture_hash)

    def read(self, path: str):
        data = self.archive.file(path)
        if data is None:
            raise PluginError(f"O2R display list '{path}' could not be read.")
        if _resource_type(data) != "ODLT":
            raise PluginError(f"O2R resource '{path}' is not a displaylist.")

        offset = 0x48
        while offset + 8 <= len(data):
            word0 = int.from_bytes(data[offset : offset + 4], "little")
            word1 = int.from_bytes(data[offset + 4 : offset + 8], "little")
            opcode = word0 >> 24
            hash_value = (
                int.from_bytes(data[offset + 8 : offset + 12], "little") << 32
                | int.from_bytes(data[offset + 12 : offset + 16], "little")
                if opcode in self._EXPANDED_OPCODES
                else 0
            )

            if opcode == 0xDF:  # G_ENDDL
                return
            if opcode == 0x32:  # G_VTX_OTR_HASH
                count = (word0 >> 12) & 0xFF
                cache_start = ((word0 >> 1) & 0x7F) - count
                self._load_vertices(hash_value, word1, count, cache_start)
            elif opcode == 0x31:  # G_DL_OTR_HASH
                sub_path = self.archive.find_path_by_crc64(hash_value)
                if sub_path is not None:
                    self.read(sub_path)
            elif opcode == 0x20:  # G_SETTIMG_OTR_HASH
                self._current_texture_hash = hash_value
            elif opcode == 0xD9:  # G_GEOMETRYMODE
                self._geometry_mode = (self._geometry_mode & (word0 & 0x00FFFFFF)) | word1
            elif opcode == 0x05:  # G_TRI1
                self._triangle((word0 >> 16 & 0xFF) // 2, (word0 >> 8 & 0xFF) // 2, (word0 & 0xFF) // 2)
            elif opcode == 0x06:  # G_TRI2
                self._triangle((word0 >> 16 & 0xFF) // 2, (word0 >> 8 & 0xFF) // 2, (word0 & 0xFF) // 2)
                self._triangle((word1 >> 16 & 0xFF) // 2, (word1 >> 8 & 0xFF) // 2, (word1 & 0xFF) // 2)
            elif opcode == 0x26:  # G_TRI1_OTR, whose indices are not doubled.
                self._triangle(word0 & 0xFF, word1 >> 16 & 0xFF, word1 & 0xFF)

            offset += 16 if opcode in self._EXPANDED_OPCODES else 8

    @property
    def vertices(self) -> list[tuple[int, int, int]]:
        return [vertex.position for vertex in self._vertices]

    @property
    def source_vertices(self) -> list[HM64O2RVertex]:
        return self._vertices

    @property
    def vertex_normals(self) -> list[tuple[float, float, float] | None]:
        return self._vertex_normals


class HM64O2RF3DContext(OOTF3DContext):
    def __init__(self, f3d, limb_list, base_path, texture_paths: dict[str, str]):
        self.o2r_texture_paths = texture_paths
        super().__init__(f3d, limb_list, base_path)

    def handleTextureValue(self, material, image, index):
        super().handleTextureValue(material, image, index)
        texture_name = self.getImageName(image)
        if texture_name is not None and texture_name in self.o2r_texture_paths:
            getattr(material.f3d_mat, f"tex{index}").texture_internal_path = self.o2r_texture_paths[texture_name]

    def setCurrentTransform(self, name, flagList="G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_MODELVIEW"):
        if name.startswith("&o2r_mtx_"):
            return
        super().setCurrentTransform(name, flagList)

    def handleTextureReference(self, name, image, material, index, tileSettings, data):
        try:
            pointer = int(name, 0)
        except ValueError:
            pointer = None
        if pointer is not None:
            segment = pointer >> 24
            key = (segment, material.f3d_mat.draw_layer.oot)
            if key in self.flipbooks:
                name = f"0x{segment:02X}000000"
        super().handleTextureReference(name, image, material, index, tileSettings, data)

    def applyTileToMaterial(self, index, tileSettings, tileSizeSettings, dlData):
        super().applyTileToMaterial(index, tileSettings, tileSizeSettings, dlData)

        texture_name = self.tmemDict.get(tileSettings.tmem)
        draw_layer = self.materialContext.f3d_mat.draw_layer.oot
        for (segment, layer), flipbook in self.flipbooks.items():
            if layer == draw_layer and flipbook.textureNames and flipbook.textureNames[0] == texture_name:
                self.handleTextureReference(
                    f"0x{segment:02X}000000", None, self.materialContext, index, tileSettings, dlData
                )
                break

    def applyTLUTToIndex(self, index):
        tex_prop = getattr(self.mat(), f"tex{index}")
        palette_tmem = 256 if 256 in self.tmemDict else 496 if 496 in self.tmemDict else None
        if tex_prop.tex_format.startswith("CI") and palette_tmem is None:
            return

        previous_tlut = self.tmemDict.get(256)
        if palette_tmem == 496:
            self.tmemDict[256] = self.tmemDict[496]
        try:
            super().applyTLUTToIndex(index)
        finally:
            if palette_tmem == 496:
                if previous_tlut is None:
                    del self.tmemDict[256]
                else:
                    self.tmemDict[256] = previous_tlut

        tlut_name = self.tmemDict.get(palette_tmem)
        if not tex_prop.tex_format.startswith("CI") or not tlut_name:
            return
        tlut = self.textureData.get(tlut_name)
        if tlut is None:
            return

        tex_prop.custom_palette_name = tlut_name
        if hasattr(tlut, "size"):
            tex_prop.palette_color_count = min(tlut.size[0] * tlut.size[1], 255)


def _read_otex_raw(data: bytes) -> tuple[int, int, int, bytes]:
    if _resource_type(data) != "OTEX":
        raise PluginError("Referenced O2R resource is not an OTEX texture.")
    byte_order = "little" if data[0] == 0 else "big"
    version = int.from_bytes(data[8:12], byte_order)
    texture_type = int.from_bytes(data[0x40:0x44], byte_order)
    width = int.from_bytes(data[0x44:0x48], byte_order)
    height = int.from_bytes(data[0x48:0x4C], byte_order)
    if version == 0:
        data_size = int.from_bytes(data[0x4C:0x50], byte_order)
        pixels_start = 0x50
    elif version == 1:
        data_size = int.from_bytes(data[0x58:0x5C], byte_order)
        pixels_start = 0x5C
    else:
        raise PluginError(f"OTEX version {version} is not supported.")
    if width <= 0 or height <= 0 or pixels_start + data_size > len(data):
        raise PluginError("OTEX resource has invalid dimensions or truncated pixel data.")
    return texture_type, width, height, data[pixels_start : pixels_start + data_size]


def import_hm64_o2r_display_list(
    scene,
    path: str,
    actor_scale: float = 10,
    remove_doubles: bool = True,
    import_normals: bool = True,
    draw_layer: str = "Opaque",
):
    source = get_hm64_o2r_source(scene)
    serializer = HM64O2RF3DSerializer(source.archive)
    data, root_name = serializer.serialize(normalize_o2r_path(path))
    name = normalize_o2r_path(path).rsplit("/", 1)[-1]
    import_scale = getattr(scene, "ootBlenderScale", 10) * actor_scale / 0.1
    obj = importMeshC(
        data,
        root_name,
        import_scale,
        remove_doubles,
        import_normals,
        draw_layer,
        HM64O2RF3DContext(
            get_F3D_GBI(),
            [root_name],
            str(Path(source.path).parent),
            serializer.texture_paths,
        ),
    )
    obj.name = name
    obj.data.name = name
    _pack_o2r_images(obj)
    return obj


def _pack_o2r_images(obj: bpy.types.Object):
    images: set[bpy.types.Image] = set()
    for material in obj.data.materials:
        if not material or not material.is_f3d:
            continue
        for index in range(2):
            image = getattr(material.f3d_mat, f"tex{index}").tex
            if image is not None:
                images.add(image)
    for image in images:
        if image.packed_file is None:
            image.pack()


def _display_list_path(settings) -> str:
    if settings.isCustom:
        raise PluginError("Custom file paths are not used with O2R import. Set Object and DL instead.")
    name = normalize_o2r_path(settings.name)
    if "/" in name:
        return name
    return f"objects/{normalize_o2r_path(settings.folder)}/{name}"


def import_hm64_o2r_display_list_from_settings(scene, settings):
    return import_hm64_o2r_display_list(
        scene,
        _display_list_path(settings),
        settings.actorScale,
        settings.removeDoubles,
        settings.importNormals,
        settings.drawLayer,
    )


@dataclass(frozen=True)
class HM64O2RLimb:
    joint_pos: tuple[int, int, int]
    child: int
    sibling: int
    display_list: str | None


def _read_o2r_string(data: bytes, offset: int, byte_order: str) -> tuple[str, int]:
    if offset + 4 > len(data):
        raise PluginError("O2R resource has a truncated string.")
    length = int.from_bytes(data[offset : offset + 4], byte_order)
    offset += 4
    if offset + length > len(data):
        raise PluginError("O2R resource has a truncated string payload.")
    return data[offset : offset + length].decode("utf-8"), offset + length


def _read_oskl_limb_paths(data: bytes) -> list[str]:
    xml_root = _xml_resource(data, "Skeleton")
    if xml_root is not None:
        return [limb.attrib["Path"] for limb in xml_root.findall("SkeletonLimb")]
    if _resource_type(data) != "OSKL":
        raise PluginError("Selected O2R resource is not an OSKL skeleton.")
    byte_order = "little" if data[0] == 0 else "big"
    if len(data) < 0x4F:
        raise PluginError("OSKL resource is truncated.")
    limb_count = int.from_bytes(data[0x4B:0x4F], byte_order)
    offset = 0x4F
    paths = []
    for _ in range(limb_count):
        path, offset = _read_o2r_string(data, offset, byte_order)
        paths.append(path)
    return paths


def _read_oslb(data: bytes) -> HM64O2RLimb:
    xml_root = _xml_resource(data, "SkeletonLimb")
    if xml_root is not None:
        return HM64O2RLimb(
            tuple(int(xml_root.attrib.get(axis, "0")) for axis in ("LegTransX", "LegTransY", "LegTransZ")),
            int(xml_root.attrib.get("ChildIndex", "255")),
            int(xml_root.attrib.get("SiblingIndex", "255")),
            xml_root.attrib.get("DisplayList1") or None,
        )
    if _resource_type(data) != "OSLB":
        raise PluginError("Referenced skeleton limb is not an OSLB resource.")
    byte_order = "little" if data[0] == 0 else "big"
    offset = 0x42
    _value, offset = _read_o2r_string(data, offset, byte_order)
    offset += 2
    if offset + 4 > len(data):
        raise PluginError("OSLB resource is truncated.")
    if int.from_bytes(data[offset : offset + 4], byte_order):
        raise PluginError("O2R skin-modifier limbs are not supported yet.")
    offset += 4
    _value, offset = _read_o2r_string(data, offset, byte_order)
    offset += 18
    _child_ptr, offset = _read_o2r_string(data, offset, byte_order)
    _sibling_ptr, offset = _read_o2r_string(data, offset, byte_order)
    display_list, offset = _read_o2r_string(data, offset, byte_order)
    _dl2, offset = _read_o2r_string(data, offset, byte_order)
    if offset + 8 > len(data):
        raise PluginError("OSLB limb position is truncated.")
    return HM64O2RLimb(
        tuple(int.from_bytes(data[offset + i : offset + i + 2], byte_order, signed=True) for i in (0, 2, 4)),
        data[offset + 6],
        data[offset + 7],
        display_list or None,
    )


def import_hm64_o2r_skeleton(scene, settings):
    is_mm = is_hm64() and scene.fast64.oot.mm_features
    import_dict = mm_skeleton_dict if is_mm else ootSkeletonImportDict
    flipbook_map = O2R_MM_SKELETON_FLIPBOOKS if is_mm else O2R_SKELETON_FLIPBOOKS
    import_info = None
    if settings.mode != "Generic":
        import_info = import_dict[settings.mode]
        skeleton_name = import_info.skeletonName
        folder_name = import_info.folderName
    else:
        skeleton_name = normalize_o2r_path(settings.name).rsplit("/", 1)[-1]
        folder_name = normalize_o2r_path(settings.folder)
    skeleton_path = f"objects/{folder_name}/{skeleton_name}"
    source = get_hm64_o2r_source(scene)
    data = source.archive.file(skeleton_path)
    if data is None:
        raise PluginError(f"O2R skeleton resource '{skeleton_path}' could not be read.")
    limb_paths = _read_oskl_limb_paths(data)
    if not limb_paths:
        raise PluginError("O2R skeleton contains no limbs.")
    limbs = []
    for path in limb_paths:
        limb_data = source.archive.file(path)
        if limb_data is None:
            raise PluginError(f"O2R skeleton limb '{path}' could not be read.")
        limbs.append(_read_oslb(limb_data))

    serializer = HM64O2RF3DSerializer(source.archive)
    limb_roots = [
        serializer._display_list(limb.display_list) if limb.display_list and limb.display_list != "gEmptyDL" else None
        for limb in limbs
    ]
    flipbook_textures: dict[int, list[str]] = {}
    texture_prefix = f"objects/{folder_name}"
    for segment, texture_names in flipbook_map.get(skeleton_name, {}).items():
        resolved_names = []
        for texture_name in texture_names:
            texture_path = source.archive.find_path_by_name(texture_name, texture_prefix)
            if texture_path is None:
                raise PluginError(
                    f"O2R flipbook texture '{texture_name}' for skeleton '{skeleton_name}' could not be resolved."
                )
            resolved_names.append(serializer._texture(int(crc64(texture_path), 16))[0])
        flipbook_textures[segment] = resolved_names
    f3d_data = "\n".join(
        [
            *serializer._texture_declarations,
            *serializer._matrix_declarations,
            *serializer._vertex_declarations,
            *serializer._display_declarations,
        ]
    )
    actor_scale = getOOTScale(settings.actorScale) / 0.1
    mesh = bpy.data.meshes.new(skeleton_name + "_mesh")
    obj = bpy.data.objects.new(skeleton_name + "_mesh", mesh)
    bpy.context.collection.objects.link(obj)
    armature = bpy.data.armatures.new(skeleton_name)
    armature_obj = bpy.data.objects.new(skeleton_name, armature)
    armature_obj.show_in_front = True
    armature_obj.ootDrawLayer = settings.drawLayer
    bpy.context.collection.objects.link(armature_obj)
    f3d_context = HM64O2RF3DContext(
        get_F3D_GBI(), [Path(path).name for path in limb_paths], str(Path(source.path).parent), serializer.texture_paths
    )
    f3d_context.mat().draw_layer.oot = settings.drawLayer
    for segment, texture_names in flipbook_textures.items():
        flipbook = TextureFlipbook("", "Individual", texture_names)
        for draw_layer in ("Opaque", "Transparent", "Overlay"):
            f3d_context.flipbooks[(segment, draw_layer)] = flipbook
    pending: list[tuple[int, mathutils.Matrix, str | None]] = [(0, mathutils.Matrix.Scale(1 / actor_scale, 4), None)]
    seen: set[int] = set()
    draw_entries: list[tuple[int, str]] = []
    while pending:
        index, parent_transform, parent_bone = pending.pop()
        if index == 0xFF or not 0 <= index < len(limbs) or index in seen:
            continue
        seen.add(index)
        limb = limbs[index]
        transform = parent_transform @ mathutils.Matrix.Translation((0, 0, 0) if index == 0 else limb.joint_pos)
        limb_name = f3d_context.getLimbName(index)
        bone_name = f3d_context.getBoneName(index)
        f3d_context.limbToBoneName[limb_name] = bone_name
        f3d_context.matrixData[limb_name] = transform
        ootAddBone(armature_obj, bone_name, parent_bone, transform, limb_roots[index] is not None, None)
        if limb_roots[index]:
            draw_entries.append((index, limb_roots[index]))
            f3d_context.dlList.append(OOTDLEntry(limb_roots[index], index))
        pending.append((limb.sibling, parent_transform, parent_bone))
        pending.append((limb.child, transform, bone_name))
    for index, display_list in draw_entries:
        limb_name = f3d_context.getLimbName(index)
        parseF3D(
            f3d_data,
            display_list,
            f3d_context.matrixData[limb_name],
            limb_name,
            f3d_context.getBoneName(index),
            settings.drawLayer,
            f3d_context,
            True,
        )
    f3d_context.createMesh(obj, settings.removeDoubles, settings.importNormals, False)
    _pack_o2r_images(obj)
    armature_obj.location = scene.cursor.location
    deselectAllObjects()
    obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.parent_set(type="ARMATURE")
    applyRotation([armature_obj], math.radians(-90), "X")
    armature_obj.ootActorScale = actor_scale / scene.ootBlenderScale
    f3d_context.deleteMaterialContext()
    if import_info is not None and settings.applyRestPose:
        rest_pose = import_info.restPoseData
        if rest_pose is not None:
            applySkeletonRestPose(rest_pose, armature_obj)
    return armature_obj


def _draw_file_settings(panel, context):
    from ...game_data import game_data

    col = panel.layout.column()
    col.scale_y = 1.1
    prop_split(col, context.scene, "ootBlenderScale", "OOT Scene Scale")
    oot_settings = context.scene.fast64.oot
    is_oot = game_data.z64.is_oot()
    feature_set = oot_settings.feature_set
    is_decomp = feature_set == "default"
    show_hm64_mm_toggle = is_oot and feature_set == "hm64"
    use_mm_version = (not is_oot) or (show_hm64_mm_toggle and oot_settings.mm_features)

    col.prop(context.scene, "hm64_use_o2r_import")
    if context.scene.hm64_use_o2r_import:
        prop_split(col, context.scene, "hm64_o2r_path", "O2R Path")
    else:
        prop_split(col, context.scene, "ootDecompPath", "Decomp Path")

    version = "mm_version" if use_mm_version else "oot_version"
    prop_split(col, oot_settings, version, "Game Version")
    if getattr(oot_settings, version) == "Custom":
        prop_split(col, oot_settings, "oot_version_custom", "Custom Version")
    if is_oot:
        prop_split(col, oot_settings, "feature_set", "Feature Set")
    col.prop(oot_settings, "headerTabAffectsVisibility")
    if is_oot and (is_decomp or show_hm64_mm_toggle):
        col.prop(oot_settings, "mm_features")
    if game_data.z64.is_mm() or is_decomp:
        col.prop(oot_settings, "useDecompFeatures")
    col.prop(oot_settings, "exportMotionOnly")
    if is_oot:
        col.prop(oot_settings, "use_new_actor_panel")


_original_file_settings_draw = None
_original_dl_import_execute = None


def _hm64_file_settings_draw(panel, context):
    if is_hm64():
        return _draw_file_settings(panel, context)
    return _original_file_settings_draw(panel, context)


def _hm64_dl_import_execute(operator, context):
    if not (is_hm64() and context.scene.hm64_use_o2r_import):
        return _original_dl_import_execute(operator, context)
    try:
        settings = context.scene.fast64.oot.DLImportSettings
        obj = import_hm64_o2r_display_list_from_settings(context.scene, settings)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        operator.report({"INFO"}, f"Imported {len(obj.data.polygons)} O2R triangles.")
        return {"FINISHED"}
    except Exception as exc:
        operator.report({"ERROR"}, str(exc))
        return {"CANCELLED"}


def register():
    global _original_dl_import_execute, _original_file_settings_draw
    from ...z64.f3d.operators import OOT_ImportDL
    from ...z64.file_settings import OOT_FileSettingsPanel

    _original_dl_import_execute = OOT_ImportDL.execute
    _original_file_settings_draw = OOT_FileSettingsPanel.draw
    OOT_ImportDL.execute = _hm64_dl_import_execute
    OOT_FileSettingsPanel.draw = _hm64_file_settings_draw
    Scene.hm64_use_o2r_import = BoolProperty(
        name="Use O2R Import",
        description="Use the selected Ship of Harkinian O2R archive for HM64 imports",
        default=False,
    )
    Scene.hm64_o2r_path = StringProperty(
        name="O2R File",
        subtype="FILE_PATH",
        description="Path to a Ship of Harkinian O2R archive, for example oot.o2r",
    )


def unregister():
    from ...z64.f3d.operators import OOT_ImportDL
    from ...z64.file_settings import OOT_FileSettingsPanel

    OOT_ImportDL.execute = _original_dl_import_execute
    OOT_FileSettingsPanel.draw = _original_file_settings_draw
    del Scene.hm64_use_o2r_import
    del Scene.hm64_o2r_path
