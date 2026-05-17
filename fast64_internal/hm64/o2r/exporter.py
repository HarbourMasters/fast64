"""O2R export functions extracted from f3d_gbi.py.

Each function takes the upstream class instance as the first argument,
matching the dispatch pattern in f3d_gbi.py.
"""

import os
import struct
import re

from ...f3d.f3d_gbi import (
    get_F3D_GBI,
    gsDma1p,
    gsDma2p,
    gsSetImage,
    _SHIFTL,
    MTX_SIZE,
    VTX_SIZE,
    encodeSegmentedAddr,
)
from .crc import crc64


# --- Utility functions (moved from f3d_gbi.py) ---

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


# --- Texture type mapping (shared by VtxList and FImage) ---

def _texture_type_o2r(fmt: str, bitSize: str) -> int:
    size = bitSizeDict[bitSize]
    if fmt == "G_IM_FMT_RGBA":
        if size == 32:
            return 1
        if size == 16:
            return 2
    if fmt == "G_IM_FMT_CI":
        if size == 4:
            return 3
        if size == 8:
            return 4
    if fmt == "G_IM_FMT_I":
        if size == 4:
            return 5
        if size == 8:
            return 6
    if fmt == "G_IM_FMT_IA":
        if size == 4:
            return 7
        if size == 8:
            return 8
        if size == 16:
            return 9
    return 0


# --- O2R export functions ---

def VtxList_textureTypeO2R(vtx_list) -> int:
    return _texture_type_o2r(vtx_list.fmt, vtx_list.bitSize)


def VtxList_to_o2r(vtx_list, folderPath: str, segments: dict | None = None):
    data = bytearray(0)
    print(f"VtxList.to_o2r {vtx_list.name} ({len(vtx_list.vertices)} vertices).")
    data.extend(struct.pack("<IIIQIQIQQQI", 0, 0x4F415252, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack("<II", 25, len(vtx_list.vertices)))
    for vert in vtx_list.vertices:
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


def GfxList_to_o2r(gfx_list, folderPath: str, segments: dict | None = None):
    data = bytearray(0)
    print(f"GfxList.to_o2r {gfx_list.name} ({len(gfx_list.commands)} commands).")
    data.extend(struct.pack("<I", 1))
    data.extend(struct.pack(">IIQIQIQQQI", 0x4F444C54, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack(">bBHI", 4, 0xFF, 0xFFFF, 0xFFFFFFFF))
    data.extend(struct.pack(">II", 0x33 << 24, 0xBEEFBEEF))

    dlPath = os.path.join(folderPath, gfx_list.name)
    dlPath = dlPath.replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))

    f3d = get_F3D_GBI()
    segments = {} if segments is None else segments
    for command in gfx_list.commands:
        if hasattr(command, "to_o2r"):
            data.extend(command.to_o2r(folderPath))
        else:
            data.extend(command.to_binary(f3d, segments))
    return data


def FImage_textureTypeO2R(fimage) -> int:
    return _texture_type_o2r(fimage.fmt, fimage.bitSize)


def FImage_to_o2r(fimage, folderPath: str):
    data = bytearray(0)
    print(f"FImage.to_o2r {fimage.name} {fimage.fmt} {fimage.bitSize} {fimage.width}x{fimage.height} {len(fimage.data)} bytes")
    data.extend(struct.pack("<IIIQIQIQQQI", 0, 0x4F544558, 0, 0xDEADBEEFDEADBEEF, 0, 0, 0, 0, 0, 0, 0))
    data.extend(struct.pack("<IIII", FImage_textureTypeO2R(fimage), fimage.width, fimage.height, len(fimage.data)))
    data.extend(fimage.data)
    return data


def SPMatrix_to_o2r(sp_matrix, folderPath: str):
    data = bytearray(0)
    print(f"SPMatrix.to_o2r {sp_matrix.matrix}")
    matPtr = sp_matrix._resolve_matrix_address()
    if isinstance(matPtr, int):
        matPtr = (matPtr & 0x0FFFFFFF) + 1
    f3d = get_F3D_GBI()
    data.extend(gsDma2p(f3d.G_MTX, matPtr, MTX_SIZE, 0x02 ^ f3d.G_MTX_PUSH, 0))
    return data


def SPVertex_to_o2r(sp_vertex, folderPath: str):
    data = bytearray(0)
    print(f"SPVertex.to_o2r {sp_vertex.vertList.name} {sp_vertex.offset} {sp_vertex.count} {sp_vertex.index}")
    words = (
        _SHIFTL(0x32, 24, 8) | _SHIFTL(sp_vertex.count, 12, 8) | _SHIFTL(sp_vertex.index + sp_vertex.count, 1, 7),
        sp_vertex.offset * VTX_SIZE,
    )
    data.extend(words[0].to_bytes(4, "big") + words[1].to_bytes(4, "big"))

    vertPath = os.path.join(folderPath, sp_vertex.vertList.name)
    vertPath = vertPath.replace("\\", "/")
    hash_val = int(crc64(vertPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def SPDisplayList_to_o2r(sp_dl, folderPath: str):
    data = bytearray(0)
    print(f"SPDisplayList.to_o2r {sp_dl.displayList.name}")
    data.extend(gsDma1p(0x31, 0, 0, 0x00))

    dlPath = os.path.join(folderPath, sp_dl.displayList.name)
    dlPath = dlPath.replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def SPBranchList_to_o2r(sp_branch, folderPath: str):
    data = bytearray(0)
    print(f"SPBranchList.to_o2r {sp_branch.displayList.name}")
    data.extend(gsDma1p(0x31, 0, 0, 0x01))

    dlPath = os.path.join(folderPath, sp_branch.displayList.name)
    dlPath = dlPath.replace("\\", "/")
    hash_val = int(crc64(dlPath), 16)
    data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


def DPSetTextureImage_to_o2r(dp_tex, folderPath: str):
    print(f"DPSetTextureImage.to_o2r {dp_tex.image.name}")
    data = bytearray(0)
    f3d = get_F3D_GBI()
    fmt = f3d.G_IM_FMT_VARS[dp_tex.fmt]
    siz = f3d.G_IM_SIZ_VARS[dp_tex.siz]

    if re.match(r"^0x0(\d)000000$", dp_tex.image.name):
        imagePtr = int(dp_tex.image.name, 16) + 1
        data.extend(gsSetImage(f3d.G_SETTIMG, fmt, siz, dp_tex.width, imagePtr))
    else:
        data.extend(gsSetImage(0x20, fmt, siz, dp_tex.width, 0))
        imagePath = os.path.join(folderPath, dp_tex.image.name)
        imagePath = imagePath.replace("\\", "/")
        hash_val = int(crc64(imagePath), 16)
        data.extend(struct.pack(">II", hash_val >> 32, hash_val & 0xFFFFFFFF))
    return data


# --- Registration ---

def register():
    from ...f3d.f3d_gbi import register_o2r_exporter
    import sys
    register_o2r_exporter(sys.modules[__name__])


def unregister():
    from ...f3d.f3d_gbi import unregister_o2r_exporter
    unregister_o2r_exporter()
