from __future__ import annotations

import os
import re
import struct

import bpy

from ...f3d.f3d_gbi import (
    DPSetEnvColor,
    DPSetPrimColor,
    DPSetTextureImage,
    FImage,
    FScrollData,
    GfxList,
    MTX_SIZE,
    SPBranchList,
    SPDisplayList,
    SPMatrix,
    SPVertex,
    VTX_SIZE,
    VtxList,
    _SHIFTL,
    get_F3D_GBI,
    gsDma1p,
    gsDma2p,
    gsSetImage,
)
from ...utility import PluginError
from ..utility import crc64


_REGISTERED = False

bitSizeDict = {
    "G_IM_SIZ_4b": 4,
    "G_IM_SIZ_8b": 8,
    "G_IM_SIZ_16b": 16,
    "G_IM_SIZ_32b": 32,
}


def normalize_hex_pointer(name: str) -> str:
    stripped = name.strip()
    if stripped.lower().startswith("0x"):
        digits = stripped[2:]
        if len(digits) >= 2 and digits[0] == "0" and digits[1].upper() in "ABCDEF":
            digits = digits[1:]
        return "0x" + digits
    return stripped


def format_asset_path(objectPath: str | None, name: str | None) -> str:
    sanitized_path = (objectPath or "").replace("\\", "/").strip("/")
    sanitized_name = (name or "").replace("\\", "/").strip("/")
    if sanitized_name:
        if sanitized_name.lower().startswith("0x"):
            digits = sanitized_name[2:]
            digits = digits if digits.startswith("0") else "0" + digits
            return f">0x{digits.upper()}"
        if sanitized_path:
            return f"{sanitized_path}/{sanitized_name}"
        return sanitized_name
    return sanitized_path


def canonical_image_identity(image: bpy.types.Image | None) -> tuple[str, str, str]:
    if image is None:
        return "", "", ""
    lib_path = ""
    try:
        lib_obj = getattr(image, "library", None)
        if lib_obj is not None:
            lib_path = lib_obj.filepath or ""
    except Exception:
        lib_path = ""
    return (lib_path, image.filepath or "", image.name or "")


def find_image_by_identity(image_id: tuple[str, str, str]) -> bpy.types.Image | None:
    if not any(image_id):
        return None
    for image in bpy.data.images:
        if canonical_image_identity(image) == image_id:
            return image
    return None


def get_image_from_image_key(imageKey) -> bpy.types.Image:
    image = getattr(imageKey, "image", None)
    if image is None:
        image = find_image_by_identity(getattr(imageKey, "image_id", ("", "", "")))
    if image is None:
        raise PluginError(f"Image for texture key {getattr(imageKey, 'image_id', None)} not found.")
    return image


def has_scroll_data(self) -> bool:
    return (
        self.tile_scroll_tex0.s != 0
        or self.tile_scroll_tex0.t != 0
        or self.tile_scroll_tex1.s != 0
        or self.tile_scroll_tex1.t != 0
    )


def _texture_type_o2r(image: FImage) -> int:
    bitSize = bitSizeDict[image.bitSize]
    if image.fmt == "G_IM_FMT_RGBA":
        if bitSize == 32:
            return 1
        if bitSize == 16:
            return 2
    if image.fmt == "G_IM_FMT_CI":
        if bitSize == 4:
            return 3
        if bitSize == 8:
            return 4
    if image.fmt == "G_IM_FMT_I":
        if bitSize == 4:
            return 5
        if bitSize == 8:
            return 6
    if image.fmt == "G_IM_FMT_IA":
        if bitSize == 4:
            return 7
        if bitSize == 8:
            return 8
        if bitSize == 16:
            return 9
    return 0


def _vtx_list_to_o2r(self, folderPath: str, segments: dict | None = None):
    data = bytearray()
    data.extend(struct.pack("<IIIQIQIQQQI", 0, 0x4F415252, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack("<II", 25, len(self.vertices)))
    for vert in self.vertices:
        data.extend(
            struct.pack(
                "<hhhhhhBBBB",
                vert.position[0],
                vert.position[1],
                vert.position[2],
                vert.packedNormal,
                vert.uv[0],
                vert.uv[1],
                *vert.colorOrNormal,
            )
        )
    return data


def _gfx_list_to_o2r(self, folderPath: str, segments: dict | None = None):
    data = bytearray()
    data.extend(struct.pack("<I", 1))
    data.extend(struct.pack(">IIQIQIQQQI", 0x4F444C54, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack(">bBHI", 4, 0xFF, 0xFFFF, 0xFFFFFFFF))
    data.extend(struct.pack(">II", 0x33 << 24, 0xBEEFBEEF))
    dlPath = os.path.join(folderPath, self.name).replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))

    f3d = get_F3D_GBI()
    segments = {} if segments is None else segments
    for command in self.commands:
        if hasattr(command, "toO2R"):
            data.extend(command.toO2R(folderPath))
        else:
            data.extend(command.to_binary(f3d, segments))
    return data


def _fimage_to_o2r(self, folderPath: str):
    data = bytearray()
    data.extend(struct.pack("<IIIQIQIQQQI", 0, 0x4F544558, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack("<IIII", _texture_type_o2r(self), self.width, self.height, len(self.data)))
    data.extend(self.data)
    return data


def _spmatrix_to_o2r(self, folderPath: str):
    data = bytearray()
    matPtr = self.matrix
    if isinstance(matPtr, str):
        matPtr = matPtr.lstrip(">")
        matPtr = int(matPtr, 0)
    if isinstance(matPtr, int):
        matPtr = (matPtr & 0x0FFFFFFF) + 1
    f3d = get_F3D_GBI()
    data.extend(gsDma2p(f3d.G_MTX, matPtr, MTX_SIZE, 0x02 ^ f3d.G_MTX_PUSH, 0))
    return data


def _spvertex_to_o2r(self, folderPath: str):
    data = bytearray()
    words = (
        _SHIFTL(0x32, 24, 8) | _SHIFTL(self.count, 12, 8) | _SHIFTL(self.index + self.count, 1, 7),
        self.offset * VTX_SIZE,
    )
    data.extend(words[0].to_bytes(4, "big") + words[1].to_bytes(4, "big"))
    vertPath = os.path.join(folderPath, self.vertList.name).replace("\\", "/")
    hash_val = int(crc64(vertPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def _spdisplaylist_to_o2r(self, folderPath: str):
    data = bytearray()
    data.extend(gsDma1p(0x31, 0, 0, 0x00))
    dlPath = os.path.join(folderPath, self.displayList.name).replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def _spbranchlist_to_o2r(self, folderPath: str):
    data = bytearray()
    data.extend(gsDma1p(0x31, 0, 0, 0x01))
    dlPath = os.path.join(folderPath, self.displayList.name).replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def _dpsettextureimage_to_o2r(self, folderPath: str):
    data = bytearray()
    f3d = get_F3D_GBI()
    fmt = f3d.G_IM_FMT_VARS[self.fmt]
    siz = f3d.G_IM_SIZ_VARS[self.siz]

    if re.match(r"^0x0(\d)000000$", self.image.name):
        imagePtr = int(self.image.name, 16) + 1
        data.extend(gsSetImage(f3d.G_SETTIMG, fmt, siz, self.width, imagePtr))
    else:
        data.extend(gsSetImage(0x20, fmt, siz, self.width, 0))
        imagePath = os.path.join(folderPath, self.image.name).replace("\\", "/")
        hash_val = int(crc64(imagePath), 16)
        data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def make_prim_color(
    m: int, l: int, r: int, g: int, b: int, a: int, cosmeticEntry: str = "", cosmeticCategory: str = ""
):
    cmd = DPSetPrimColor(m, l, r, g, b, a)
    cmd.cosmeticEntry = cosmeticEntry
    cmd.cosmeticCategory = cosmeticCategory
    return cmd


def make_env_color(r: int, g: int, b: int, a: int, cosmeticEntry: str = "", cosmeticCategory: str = ""):
    cmd = DPSetEnvColor(r, g, b, a)
    cmd.cosmeticEntry = cosmeticEntry
    cmd.cosmeticCategory = cosmeticCategory
    return cmd


_PATCHED_METHODS = {
    VtxList: {"toO2R": _vtx_list_to_o2r},
    GfxList: {"toO2R": _gfx_list_to_o2r},
    FScrollData: {"has_scroll_data": has_scroll_data},
    FImage: {"toO2R": _fimage_to_o2r},
    SPMatrix: {"toO2R": _spmatrix_to_o2r},
    SPVertex: {"toO2R": _spvertex_to_o2r},
    SPDisplayList: {"toO2R": _spdisplaylist_to_o2r},
    SPBranchList: {"toO2R": _spbranchlist_to_o2r},
    DPSetTextureImage: {"toO2R": _dpsettextureimage_to_o2r},
}


def register():
    global _REGISTERED
    if _REGISTERED:
        return

    FImage.skip_export = False
    FImage.internal_path = ""
    DPSetEnvColor.cosmeticEntry = ""
    DPSetEnvColor.cosmeticCategory = ""
    DPSetPrimColor.cosmeticEntry = ""
    DPSetPrimColor.cosmeticCategory = ""
    for cls, methods in _PATCHED_METHODS.items():
        for name, func in methods.items():
            setattr(cls, name, func)
    _REGISTERED = True


def unregister():
    global _REGISTERED
    if not _REGISTERED:
        return

    for cls, methods in _PATCHED_METHODS.items():
        for name in methods:
            if hasattr(cls, name):
                delattr(cls, name)
    for cls, attrs in {
        FImage: ("skip_export", "internal_path"),
        DPSetEnvColor: ("cosmeticEntry", "cosmeticCategory"),
        DPSetPrimColor: ("cosmeticEntry", "cosmeticCategory"),
    }.items():
        for attr in attrs:
            if hasattr(cls, attr):
                delattr(cls, attr)
    _REGISTERED = False
