from __future__ import annotations

import bpy
from dataclasses import dataclass, field
from typing import Optional, Union

from ...f3d import f3d_texture_writer as base
from ...f3d.f3d_gbi import (
    DPLoadSync,
    DPLoadTLUTCmd,
    DPPipeSync,
    DPSetTextureImage,
    DPSetTextureLUT,
    DPSetTile,
    DPTileSync,
    FImage,
    FImageKey,
    FMaterial,
    FModel,
    FPaletteKey,
    FTexRect,
    GfxList,
)
from ...f3d.f3d_material import (
    F3DMaterialProperty,
    TextureProperty,
    getTmemMax,
    getTmemWordUsage,
    texBitSizeF3D,
    texFormatOf,
)
from ...utility import PluginError, toAlnum
from ..utility import is_hm64, sanitize_internal_asset_path


_ORIGINALS = {}
_REGISTERED = False


def computeAutoNativeSize(tex_size: tuple[int, int], texFormat: str) -> tuple[int, int]:
    """Divide an image's size by powers of two until it fits texFormat's TMEM budget."""
    width, height = tex_size
    tmemWordBudget = getTmemMax(texFormat) // 8  # bytes -> words, same unit as getTmemWordUsage
    divisor = 1
    while True:
        w, h = max(1, width // divisor), max(1, height // divisor)
        if getTmemWordUsage(texFormat, w, h) <= tmemWordBudget or (w == 1 and h == 1):
            return (w, h)
        divisor *= 2


def writeRawTextureData(image: bpy.types.Image, fImage: FImage):
    """Write plain 4-bytes-per-texel RGBA8 pixel data (TEX_FLAG_LOAD_AS_RAW), not N64 bit-packed."""
    width, height = image.size[0], image.size[1]
    pixels = image.pixels[:]
    channels = image.channels
    data = bytearray(width * height * 4)
    i = 0
    for y in reversed(range(height)):
        row = y * width
        for x in range(width):
            idx = (row + x) * channels
            data[i] = int(round(pixels[idx + 0] * 0xFF)) & 0xFF
            data[i + 1] = int(round(pixels[idx + 1] * 0xFF)) & 0xFF if channels > 1 else data[i]
            data[i + 2] = int(round(pixels[idx + 2] * 0xFF)) & 0xFF if channels > 2 else data[i]
            data[i + 3] = int(round(pixels[idx + 3] * 0xFF)) & 0xFF if channels > 3 else 0xFF
            i += 4
    fImage.data = bytes(data)


class HM64PaletteKey(FPaletteKey):
    def __init__(self, palFormat: str, paletteName: str | None = None):
        self.palFormat = palFormat
        self.paletteName = toAlnum(paletteName) if paletteName else ""

    def __hash__(self) -> int:
        return hash((self.palFormat, self.paletteName))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, HM64PaletteKey)
            and self.palFormat == other.palFormat
            and self.paletteName == other.paletteName
        )


@dataclass
class SharedTLUTState:
    palette_name: str
    tex_format: str
    pal_format: str
    palette: list[int] = field(default_factory=list)
    texture_uses: dict[object, tuple[bpy.types.Image, FImage, str, str]] = field(default_factory=dict)
    palette_image: Optional[FImage] = None
    load_commands: list[tuple[DPLoadTLUTCmd, Optional[int]]] = field(default_factory=list)


def getTextureNamesFromBasename(
    baseName: str, texOrPalFormat: str, parent: Union[FModel, FTexRect], isPalette: bool, skip_pal_suffix: bool = False
):
    if not is_hm64():
        return _ORIGINALS["getTextureNamesFromBasename"](baseName, texOrPalFormat, parent, isPalette)
    sanitizedName = toAlnum(baseName)
    imageName = sanitizedName
    if isPalette and not skip_pal_suffix:
        imageName += "_pal"
    imageName = base.checkDuplicateTextureName(parent, imageName)
    filename = baseName + (".pal" if isPalette else ".inc.c")
    return imageName, filename


def get_shared_tlut_state(parent: Union[FModel, FTexRect], tex_info: "base.TexInfo") -> Optional[SharedTLUTState]:
    if (
        not tex_info.useTex
        or not tex_info.isTexCI
        or tex_info.isTexRef
        or tex_info.isPalRef
        or tex_info.flipbook is not None
        or tex_info.pal is None
        or tex_info.texProp is None
        or tex_info.texProp.tex is None
        or not getattr(tex_info, "custom_palette_requested", False)
    ):
        return None

    groups = getattr(parent, "shared_tlut_states", None)
    if groups is None:
        groups = {}
        setattr(parent, "shared_tlut_states", groups)

    palette_name = toAlnum(tex_info.palBaseName)
    shared_key = (palette_name, tex_info.texFormat, tex_info.palFormat)
    state = groups.get(shared_key)
    if state is None:
        state = SharedTLUTState(palette_name, tex_info.texFormat, tex_info.palFormat)
        groups[shared_key] = state

    merged_palette = base.mergePalettes(state.palette, tex_info.pal)
    palette_limit = 16 if tex_info.texFormat == "CI4" else 256
    if len(merged_palette) > palette_limit:
        raise PluginError(
            f"Textures sharing TLUT '{tex_info.palBaseName}' contain {len(merged_palette)} colors, which cannot fit in format {tex_info.texFormat}."
        )

    state.palette = merged_palette
    tex_info.pal = state.palette
    tex_info.palLen = len(state.palette)
    return state


def apply_shared_tlut_state(state: SharedTLUTState):
    if state.palette_image is not None:
        state.palette_image.data = bytearray()
        state.palette_image.height = len(state.palette)
        state.palette_image.converted = False
        base.writePaletteData(state.palette_image, state.palette)

    for image, fImage, tex_format, pal_format in state.texture_uses.values():
        fImage.data = bytearray()
        fImage.converted = False
        base.writeCITextureData(image, fImage, state.palette, pal_format, tex_format)

    for load_cmd, count_override in state.load_commands:
        load_count = len(state.palette) - 1
        if count_override is not None:
            load_count = count_override
        load_cmd.count = max(0, min(load_count, 255))


def saveOrGetPaletteDefinition(
    fMaterial: FMaterial,
    parent: Union[FModel, FTexRect],
    texProp: TextureProperty,
    isPalRef: bool,
    images: list[bpy.types.Image],
    palBaseName: str,
    palLen: int,
) -> tuple[FPaletteKey, FImage]:
    if not is_hm64():
        return _ORIGINALS["saveOrGetPaletteDefinition"](
            fMaterial, parent, texProp, isPalRef, images, palBaseName, palLen
        )
    palFmt = texProp.ci_format
    palFormat = texFormatOf[palFmt]
    custom_name = getattr(texProp, "custom_palette_name", "").strip()
    custom_requested = bool(custom_name)
    paletteKey = HM64PaletteKey(palFmt, palBaseName) if custom_requested else FPaletteKey(palFmt, images)

    if isPalRef:
        fPalette = FImage(texProp.pal_reference, None, None, 1, palLen, None)
        return paletteKey, fPalette

    fPalette = parent.getTextureAndHandleShared(paletteKey)
    if fPalette is not None:
        if texProp.texture_internal_path:
            fPalette.internal_path = sanitize_internal_asset_path(texProp.texture_internal_path)
        fPalette.skip_export = texProp.is_vanilla_texture
        return paletteKey, fPalette

    paletteName, filename = getTextureNamesFromBasename(palBaseName, palFmt, parent, True, custom_requested)
    fPalette = FImage(paletteName, palFormat, "G_IM_SIZ_16b", 1, palLen, filename)
    fPalette.internal_path = (
        sanitize_internal_asset_path(texProp.texture_internal_path) if texProp.texture_internal_path else ""
    )
    fPalette.skip_export = texProp.is_vanilla_texture
    parent.addTexture(paletteKey, fPalette, fMaterial)
    return paletteKey, fPalette


def saveOrGetTextureDefinition(
    fMaterial: FMaterial,
    parent: Union[FModel, FTexRect],
    texProp: TextureProperty,
    images: list[bpy.types.Image],
    isLarge: bool,
) -> tuple[FImageKey, FImage]:
    imageKey, fImage = _ORIGINALS["saveOrGetTextureDefinition"](fMaterial, parent, texProp, images, isLarge)
    if not is_hm64():
        return imageKey, fImage
    if texProp and getattr(texProp, "texture_internal_path", ""):
        fImage.internal_path = sanitize_internal_asset_path(texProp.texture_internal_path)
    if texProp:
        fImage.skip_export = getattr(texProp, "is_vanilla_texture", False)
    if texProp and not texProp.use_tex_reference and texProp.tex is not None and texProp.tex_format[:2] != "CI":
        tex_size = tuple(texProp.tex.size)
        native_size = computeAutoNativeSize(tex_size, texProp.tex_format)
        if native_size != tex_size:
            fImage.hd_width, fImage.hd_height = tex_size
            fImage.hd_byte_scale = tex_size[0] / native_size[0]
            fImage.hd_pixel_scale = tex_size[1] / native_size[1]
            fImage.width, fImage.height = native_size
    return imageKey, fImage


def fromProp(self, texProp: TextureProperty, index: int, ignore_tex_set=False) -> bool:
    if not is_hm64():
        return _ORIGINALS["TexInfo.fromProp"](self, texProp, index, ignore_tex_set)

    self.indexInMat = index
    self.texProp = texProp
    if not texProp.tex_set and not ignore_tex_set:
        return True

    self.useTex = True
    tex = texProp.tex
    self.isTexRef = texProp.use_tex_reference
    self.texFormat = texProp.tex_format
    self.isTexCI = self.texFormat[:2] == "CI"
    self.palFormat = texProp.ci_format if self.isTexCI else ""

    if tex is not None and (tex.size[0] == 0 or tex.size[1] == 0):
        self.errorMsg = f"Image {tex.name} has 0 size; may have been deleted/moved."
        return False

    if not self.isTexRef:
        if tex is None:
            self.errorMsg = "No texture is selected."
            return False
        elif len(tex.pixels) == 0:
            self.errorMsg = f"Image {tex.name} is missing on disk."
            return False

    if self.isTexRef:
        width, height = texProp.tex_reference_size
    elif self.isTexCI:
        width, height = tex.size
    else:
        width, height = computeAutoNativeSize(tuple(tex.size), self.texFormat)
    self.imageDims = (width, height)

    self.tmemSize = base.getTmemWordUsage(self.texFormat, width, height)

    if width > 1024 or height > 1024:
        self.errorMsg = "Image size (even large textures) limited to 1024 in each dimension."
        return False

    if base.texBitSizeInt[self.texFormat] == 4 and (width & 1) != 0:
        self.errorMsg = "A 4-bit image must have a width which is even."
        return False

    return True


def getPaletteName(self):
    if not is_hm64():
        return _ORIGINALS["TexInfo.getPaletteName"](self)
    if not self.useTex or self.isPalRef:
        return None
    self.custom_palette_requested = False
    if self.texProp is not None:
        custom_name = getattr(self.texProp, "custom_palette_name", "")
        if custom_name:
            stripped = custom_name.strip()
            if stripped:
                self.custom_palette_requested = True
                return stripped
    if self.flipbook is not None:
        self.custom_palette_requested = False
        return self.flipbook.name
    self.custom_palette_requested = False
    return base.getImageName(self.texProp.tex)


def writeAll(self, fMaterial: FMaterial, fModel: Union[FModel, FTexRect], convertTextureData: bool):
    if not is_hm64():
        return _ORIGINALS["TexInfo.writeAll"](self, fMaterial, fModel, convertTextureData)
    if not self.useTex:
        return
    assert self.imDependencies is not None

    shared_tlut_state = get_shared_tlut_state(fModel, self)
    imageKey, fImage = saveOrGetTextureDefinition(
        fMaterial, fModel, self.texProp, self.imDependencies, fMaterial.isTexLarge[self.indexInMat]
    )
    fMaterial.imageKey[self.indexInMat] = imageKey
    fPalette = None
    if self.loadPal:
        _, fPalette = saveOrGetPaletteDefinition(
            fMaterial, fModel, self.texProp, self.isPalRef, self.palDependencies, self.palBaseName, self.palLen
        )

    loadGfx = fMaterial.texture_DL
    f3d = fModel.f3d
    if self.loadPal:
        load_tlut_cmd = base.savePaletteLoad(
            loadGfx, fPalette, self.palFormat, self.palAddr, self.palLen, 5 - self.indexInMat, f3d
        )
        override = getattr(self.texProp, "palette_color_count", None) if self.texProp is not None else None
        if load_tlut_cmd is not None:
            load_tlut_cmd.count = max(0, min((override if override is not None else self.palLen - 1), 255))
            if shared_tlut_state is not None and fPalette is not None:
                shared_tlut_state.palette_image = fPalette
                shared_pair = (load_tlut_cmd, override)
                if shared_pair not in shared_tlut_state.load_commands:
                    shared_tlut_state.load_commands.append(shared_pair)
    if self.doTexLoad:
        base.saveTextureLoadOnly(fImage, loadGfx, self.texProp, None, 7 - self.indexInMat, self.texAddr, f3d)
    if self.doTexTile:
        base.saveTextureTile(
            fImage, fMaterial, loadGfx, self.texProp, None, self.indexInMat, self.texAddr, self.palIndex, f3d
        )

    texProp = self.texProp
    should_write_data = convertTextureData and not (texProp and getattr(texProp, "is_vanilla_texture", False))
    if should_write_data:
        if self.isTexRef:
            if self.loadPal and not self.isPalRef:
                base.writePaletteData(fPalette, self.pal)
            if self.isTexCI:
                fModel.writeTexRefCITextures(
                    self.flipbook, fMaterial, self.imDependencies, self.pal, self.texFormat, self.palFormat
                )
            else:
                fModel.writeTexRefNonCITextures(self.flipbook, self.texFormat)
        else:
            if self.isTexCI:
                assert self.pal is not None
                if shared_tlut_state is not None:
                    shared_tlut_state.texture_uses[self.texProp.tex] = (
                        self.texProp.tex,
                        fImage,
                        self.texFormat,
                        self.palFormat,
                    )
                    apply_shared_tlut_state(shared_tlut_state)
                else:
                    if self.loadPal and not self.isPalRef:
                        base.writePaletteData(fPalette, self.pal)
                    base.writeCITextureData(self.texProp.tex, fImage, self.pal, self.palFormat, self.texFormat)
            else:
                isHd = (
                    getattr(fImage, "hd_byte_scale", 1.0) != 1.0 or getattr(fImage, "hd_pixel_scale", 1.0) != 1.0
                )
                if isHd:
                    writeRawTextureData(self.texProp.tex, fImage)
                else:
                    base.writeNonCITextureData(self.texProp.tex, fImage, self.texFormat)


def saveTextureLoadOnly(
    fImage: FImage,
    gfxOut: GfxList,
    texProp: TextureProperty,
    tileSettings: Optional[base.TileLoad],
    loadtile: int,
    tmem: int,
    f3d,
    omitSetTextureImage=False,
    omitSetTile=False,
):
    if not is_hm64():
        return _ORIGINALS["saveTextureLoadOnly"](
            fImage, gfxOut, texProp, tileSettings, loadtile, tmem, f3d, omitSetTextureImage, omitSetTile
        )

    fmt = texFormatOf[texProp.tex_format]
    siz = texBitSizeF3D[texProp.tex_format]
    nocm = ("G_TX_WRAP", "G_TX_NOMIRROR")
    SL, TL, SH, TH, sl, tl, sh, th = base.getTileSizeSettings(texProp, tileSettings, f3d)

    useLoadBlock = base.canUseLoadBlock(fImage, texProp.tex_format, f3d)
    line = 0 if useLoadBlock else base.getTileLine(fImage, SL, SH, siz, f3d)
    wid = 1 if useLoadBlock else fImage.width

    if siz == "G_IM_SIZ_4b":
        if useLoadBlock:
            dxs = (((fImage.width) * (fImage.height) + 3) >> 2) - 1
            dxt = f3d.CALC_DXT_4b(fImage.width)
            siz = "G_IM_SIZ_16b"
            loadCommand = base.DPLoadBlock(loadtile, 0, 0, dxs, dxt)
        else:
            sl2 = int(SL * (2 ** (f3d.G_TEXTURE_IMAGE_FRAC - 1)))
            sh2 = int(SH * (2 ** (f3d.G_TEXTURE_IMAGE_FRAC - 1)))
            siz = "G_IM_SIZ_8b"
            wid >>= 1
            loadCommand = base.DPLoadTile(loadtile, sl2, tl, sh2, th)
    else:
        if useLoadBlock:
            dxs = (
                ((fImage.width) * (fImage.height) + f3d.G_IM_SIZ_VARS[siz + "_INCR"])
                >> f3d.G_IM_SIZ_VARS[siz + "_SHIFT"]
            ) - 1
            dxt = f3d.CALC_DXT(fImage.width, f3d.G_IM_SIZ_VARS[siz + "_BYTES"])
            siz += "_LOAD_BLOCK"
            loadCommand = base.DPLoadBlock(loadtile, 0, 0, dxs, dxt)
        else:
            loadCommand = base.DPLoadTile(loadtile, sl, tl, sh, th)

    if not omitSetTextureImage:
        gfxOut.commands.append(DPTileSync())
        gfxOut.commands.append(DPSetTextureImage(fmt, siz, wid, fImage))
    elif not omitSetTile:
        gfxOut.commands.append(DPTileSync())
    if not omitSetTile:
        gfxOut.commands.append(DPSetTile(fmt, siz, line, tmem, loadtile, 0, nocm, 0, 0, nocm, 0, 0))
    gfxOut.commands.append(DPLoadSync())
    gfxOut.commands.append(loadCommand)


def saveTextureTile(
    fImage: FImage,
    fMaterial: FMaterial,
    gfxOut: GfxList,
    texProp: TextureProperty,
    tileSettings,
    rendertile: int,
    tmem: int,
    pal: int,
    f3d,
    omitSetTile=False,
):
    if not is_hm64():
        return _ORIGINALS["saveTextureTile"](
            fImage, fMaterial, gfxOut, texProp, tileSettings, rendertile, tmem, pal, f3d, omitSetTile
        )

    if tileSettings is not None:
        clamp_S = True
        clamp_T = True
        mirror_S = False
        mirror_T = False
        mask_S = 0
        mask_T = 0
        shift_S = 0
        shift_T = 0
    else:
        clamp_S = texProp.S.clamp
        clamp_T = texProp.T.clamp
        mirror_S = texProp.S.mirror
        mirror_T = texProp.T.mirror
        mask_S = texProp.S.mask
        mask_T = texProp.T.mask
        shift_S = texProp.S.shift
        shift_T = texProp.T.shift
    cms = (("G_TX_CLAMP" if clamp_S else "G_TX_WRAP"), ("G_TX_MIRROR" if mirror_S else "G_TX_NOMIRROR"))
    cmt = (("G_TX_CLAMP" if clamp_T else "G_TX_WRAP"), ("G_TX_MIRROR" if mirror_T else "G_TX_NOMIRROR"))
    masks = mask_S
    maskt = mask_T
    shifts = shift_S if shift_S >= 0 else (shift_S + 16)
    shiftt = shift_T if shift_T >= 0 else (shift_T + 16)
    fmt = texFormatOf[texProp.tex_format]
    siz = texBitSizeF3D[texProp.tex_format]
    SL, _, SH, _, sl, tl, sh, th = base.getTileSizeSettings(texProp, tileSettings, f3d)
    line = base.getTileLine(fImage, SL, SH, siz, f3d)

    tileCommand = DPSetTile(fmt, siz, line, tmem, rendertile, pal, cmt, maskt, shiftt, cms, masks, shifts)
    tileSizeCommand = base.DPSetTileSize(rendertile, sl, tl, sh, th)

    scrollInfo = getattr(fMaterial.scrollData, f"tile_scroll_tex{rendertile}")
    if scrollInfo.s or scrollInfo.t:
        tileSizeCommand.tags |= base.GfxTag.TileScroll0 if rendertile == 0 else base.GfxTag.TileScroll1

    tileSizeCommand.fMaterial = fMaterial
    if not omitSetTile:
        gfxOut.commands.append(DPPipeSync())
        gfxOut.commands.append(tileCommand)
    gfxOut.commands.append(tileSizeCommand)

    if hasattr(fMaterial, "tileSizeCommands"):
        fMaterial.tileSizeCommands[rendertile] = tileSizeCommand


def savePaletteLoad(
    gfxOut: GfxList,
    fPalette: FImage,
    palFormat: str,
    palAddr: int,
    palLen: int,
    loadtile: int,
    f3d,
):
    if not is_hm64():
        return _ORIGINALS["savePaletteLoad"](gfxOut, fPalette, palFormat, palAddr, palLen, loadtile, f3d)

    assert 0 <= palAddr < 256 and (palAddr & 0xF) == 0
    palFmt = texFormatOf[palFormat]
    loadTileIndex = f3d.G_TX_LOADTILE
    nocm = ("G_TX_WRAP", "G_TX_NOMIRROR")
    lutMode = "G_TT_RGBA16" if palFmt == "G_IM_FMT_RGBA" else "G_TT_IA16"
    load_tlut_cmd = DPLoadTLUTCmd(loadTileIndex, max(0, min(palLen - 1, 255)))
    gfxOut.commands.extend(
        [
            DPSetTextureLUT(lutMode),
            DPSetTextureImage(palFmt, "G_IM_SIZ_16b", 1, fPalette),
            DPTileSync(),
            DPSetTile("0", "0", 0, 256 + palAddr, loadTileIndex, 0, nocm, 0, 0, nocm, 0, 0),
            DPLoadSync(),
            load_tlut_cmd,
            DPPipeSync(),
        ]
    )
    return load_tlut_cmd


def register():
    global _REGISTERED
    if _REGISTERED:
        return

    _ORIGINALS["getTextureNamesFromBasename"] = base.getTextureNamesFromBasename
    _ORIGINALS["saveOrGetPaletteDefinition"] = base.saveOrGetPaletteDefinition
    _ORIGINALS["saveOrGetTextureDefinition"] = base.saveOrGetTextureDefinition
    _ORIGINALS["savePaletteLoad"] = base.savePaletteLoad
    _ORIGINALS["saveTextureLoadOnly"] = base.saveTextureLoadOnly
    _ORIGINALS["saveTextureTile"] = base.saveTextureTile
    _ORIGINALS["TexInfo.getPaletteName"] = base.TexInfo.getPaletteName
    _ORIGINALS["TexInfo.writeAll"] = base.TexInfo.writeAll
    _ORIGINALS["TexInfo.fromProp"] = base.TexInfo.fromProp
    base.getTextureNamesFromBasename = getTextureNamesFromBasename
    base.saveOrGetPaletteDefinition = saveOrGetPaletteDefinition
    base.saveOrGetTextureDefinition = saveOrGetTextureDefinition
    base.savePaletteLoad = savePaletteLoad
    base.saveTextureLoadOnly = saveTextureLoadOnly
    base.saveTextureTile = saveTextureTile
    base.TexInfo.getPaletteName = getPaletteName
    base.TexInfo.writeAll = writeAll
    base.TexInfo.fromProp = fromProp
    base.TexInfo.custom_palette_requested = False
    _REGISTERED = True


def unregister():
    global _REGISTERED
    if not _REGISTERED:
        return

    base.getTextureNamesFromBasename = _ORIGINALS["getTextureNamesFromBasename"]
    base.saveOrGetPaletteDefinition = _ORIGINALS["saveOrGetPaletteDefinition"]
    base.saveOrGetTextureDefinition = _ORIGINALS["saveOrGetTextureDefinition"]
    base.savePaletteLoad = _ORIGINALS["savePaletteLoad"]
    base.saveTextureLoadOnly = _ORIGINALS["saveTextureLoadOnly"]
    base.saveTextureTile = _ORIGINALS["saveTextureTile"]
    base.TexInfo.getPaletteName = _ORIGINALS["TexInfo.getPaletteName"]
    base.TexInfo.writeAll = _ORIGINALS["TexInfo.writeAll"]
    base.TexInfo.fromProp = _ORIGINALS["TexInfo.fromProp"]
    _REGISTERED = False
