from __future__ import annotations

import bpy
from typing import Union

from ...utility import PluginError
from ...f3d.f3d_material import texFormatOf, texBitSizeF3D
from ...f3d.flipbook import TextureFlipbook, usesFlipbook, ootFlipbookReferenceIsValid
from ...f3d.f3d_texture_writer import getTextureNamesFromImage, writeNonCITextureData
from ...f3d.f3d_gbi import (
    FModel,
    FMaterial,
    FImage,
    FImageKey,
    DPPipeSync,
    DPSetTextureLUT,
    SPTexture,
    DPSetCombineMode,
    SPSetOtherMode,
    DPSetRenderMode,
    SPClearGeometryMode,
    SPSetGeometryMode,
    SPGeometryMode,
    DPSetEnvColor,
    DPSetPrimColor,
    GfxList,
    GfxListTag,
    DLFormat,
    SPDisplayList,
)
from ...z64.model_classes import OOTModel, DynamicMaterialDL

from ..utility import is_hm64
from ..f3d.f3d_texture_writer_hm64 import (
    isHdFImage,
    resolveHdScale,
    resolveNativeSize,
    syncMaterialReferenceSizes,
    writeRawTextureData,
)


_ORIGINALS = {}


def validateImages(self: OOTModel, material: bpy.types.Material, index: int):
    if not is_hm64():
        return _ORIGINALS["OOTModel.validateImages"](self, material, index)

    syncMaterialReferenceSizes(material)
    flipbookProp = getattr(material.flipbookGroup, f"flipbook{index}")
    texProp = getattr(material.f3d_mat, f"tex{index}")
    allImages = []
    refSize = tuple(texProp.tex_reference_size)
    for flipbookTexture in flipbookProp.textures:
        if flipbookTexture.image is None:
            raise PluginError(f"Flipbook for {material.name} has a texture array item that has not been set.")
        imSize = tuple(flipbookTexture.image.size)
        if imSize != refSize and resolveNativeSize(texProp, imSize) != refSize:
            raise PluginError(
                f"In {material.name}: texture reference size is {refSize}, but flipbook image "
                f"{flipbookTexture.image.filepath} size is {imSize}, which doesn't match and doesn't divide "
                f"down to {refSize} for TMEM either."
            )
        if flipbookTexture.image not in allImages:
            allImages.append(flipbookTexture.image)
    return allImages


def processTexRefNonCITextures(self: OOTModel, fMaterial: FMaterial, material: bpy.types.Material, index: int):
    if not is_hm64():
        return _ORIGINALS["OOTModel.processTexRefNonCITextures"](self, fMaterial, material, index)

    model = self.getFlipbookOwner()
    flipbookProp = getattr(material.flipbookGroup, f"flipbook{index}")
    texProp = getattr(material.f3d_mat, f"tex{index}")
    if not usesFlipbook(material, flipbookProp, index, True, ootFlipbookReferenceIsValid):
        return FModel.processTexRefNonCITextures(self, fMaterial, material, index)
    if len(flipbookProp.textures) == 0:
        raise PluginError(f"{str(material)} cannot have a flipbook material with no flipbook textures.")

    flipbook = TextureFlipbook(flipbookProp.name, flipbookProp.exportMode, [], [])
    allImages = self.validateImages(material, index)
    for flipbookTexture in flipbookProp.textures:
        imageKey = FImageKey(flipbookTexture.image, texProp.tex_format, texProp.ci_format, [flipbookTexture.image])
        fImage = model.getTextureAndHandleShared(imageKey)
        if fImage is None:
            imageName, filename = getTextureNamesFromImage(
                flipbookTexture.image, texProp.tex_format, texProp.ci_format if texProp.is_ci else None, model
            )
            if flipbookProp.exportMode == "Individual":
                imageName = flipbookTexture.name

            # Spoof this FImage's own size down to native/TMEM-legal.
            image_size = tuple(flipbookTexture.image.size)
            native_size = resolveNativeSize(texProp, image_size)
            isHd = native_size != image_size
            fImage = FImage(
                imageName,
                texFormatOf[texProp.tex_format],
                texBitSizeF3D[texProp.tex_format],
                native_size[0],
                native_size[1],
                filename,
            )
            if isHd:
                fImage.hd_width, fImage.hd_height = image_size
                fImage.hd_byte_scale, fImage.hd_pixel_scale = resolveHdScale(
                    image_size, native_size, texProp.tex_format
                )
            model.addTexture(imageKey, fImage, fMaterial)

        flipbook.textureNames.append(fImage.name)
        flipbook.images.append((flipbookTexture.image, fImage))

    self.addFlipbookWithRepeatCheck(flipbook)
    return allImages, flipbook


def writeTexRefNonCITextures(self: OOTModel, flipbook: Union[TextureFlipbook, None], texFmt: str):
    if not is_hm64():
        return _ORIGINALS["OOTModel.writeTexRefNonCITextures"](self, flipbook, texFmt)

    if flipbook is None:
        return FModel.writeTexRefNonCITextures(self, flipbook, texFmt)
    for image, fImage in flipbook.images:
        if isHdFImage(fImage):
            writeRawTextureData(image, fImage)
        else:
            writeNonCITextureData(image, fImage, texFmt)


def onMaterialCommandsBuilt(self: OOTModel, fMaterial: FMaterial, material: bpy.types.Material, drawLayer):
    if not is_hm64():
        return _ORIGINALS["OOTModel.onMaterialCommandsBuilt"](self, fMaterial, material, drawLayer)

    mat_commands = list(fMaterial.mat_only_DL.commands)
    tex_commands = list(fMaterial.texture_DL.commands)
    f3dMat = material.f3d_mat if material.mat_ver > 3 else material

    head_pipe = [cmd for cmd in mat_commands[:1] if isinstance(cmd, DPPipeSync)]
    remaining_mat = mat_commands[1:] if head_pipe else mat_commands[:]

    tlut_mode_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetTextureLUT)]
    texture_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPTexture)]
    combiner_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetCombineMode)]
    render_mode_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetRenderMode)]
    other_mode_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPSetOtherMode)]
    clear_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPClearGeometryMode)]
    set_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPSetGeometryMode)]
    combined_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPGeometryMode)]
    env_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetEnvColor)]
    prim_cmds = [cmd for cmd in tex_commands if isinstance(cmd, DPSetPrimColor)]
    tex_block_cmds = [cmd for cmd in tex_commands if not isinstance(cmd, DPSetPrimColor)]

    if not render_mode_cmds and getattr(f3dMat.rdp_settings, "set_rendermode", False):
        from ..f3d.hm64_f3d_writer import getRenderModeFlagList

        flagList, blender = getRenderModeFlagList(f3dMat.rdp_settings, fMaterial)
        render_mode_cmds = [DPSetRenderMode(flagList, blender)]

    extracted_ids = {
        id(cmd)
        for cmd in (
            tlut_mode_cmds
            + texture_cmds
            + combiner_cmds
            + render_mode_cmds
            + other_mode_cmds
            + clear_geo_cmds
            + set_geo_cmds
            + combined_geo_cmds
            + env_cmds
        )
    }
    other_mat_cmds = [cmd for cmd in remaining_mat if id(cmd) not in extracted_ids]

    segment_cmds = []
    matDrawLayer = getattr(material.ootMaterial, drawLayer.lower())

    for i in range(8, 14):
        if getattr(matDrawLayer, f"segment{i:X}"):
            is_animated_material = False
            if self.draw_config is not None and "mat_anim" in self.draw_config:
                is_animated_material = True
            segment_cmds.append(
                DynamicMaterialDL(
                    GfxList(f"0x0{i:X}000000", GfxListTag.Material, DLFormat.Static), is_animated_material
                )
            )

    for i in range(0, 2):
        p = f"customCall{i}"
        if getattr(matDrawLayer, p):
            segment_cmds.append(
                SPDisplayList(GfxList(getattr(matDrawLayer, f"{p}_seg"), GfxListTag.Material, DLFormat.Static))
            )

    fMaterial.material.commands = (
        head_pipe
        + tlut_mode_cmds
        + texture_cmds
        + tex_block_cmds
        + combiner_cmds
        + render_mode_cmds
        + set_geo_cmds
        + clear_geo_cmds
        + combined_geo_cmds
        + other_mat_cmds
        + segment_cmds
        + env_cmds
        + prim_cmds
    )


def register():
    _ORIGINALS["OOTModel.validateImages"] = OOTModel.validateImages
    _ORIGINALS["OOTModel.processTexRefNonCITextures"] = OOTModel.processTexRefNonCITextures
    _ORIGINALS["OOTModel.writeTexRefNonCITextures"] = OOTModel.writeTexRefNonCITextures
    _ORIGINALS["OOTModel.onMaterialCommandsBuilt"] = OOTModel.onMaterialCommandsBuilt
    OOTModel.validateImages = validateImages
    OOTModel.processTexRefNonCITextures = processTexRefNonCITextures
    OOTModel.writeTexRefNonCITextures = writeTexRefNonCITextures
    OOTModel.onMaterialCommandsBuilt = onMaterialCommandsBuilt


def unregister():
    OOTModel.validateImages = _ORIGINALS["OOTModel.validateImages"]
    OOTModel.processTexRefNonCITextures = _ORIGINALS["OOTModel.processTexRefNonCITextures"]
    OOTModel.writeTexRefNonCITextures = _ORIGINALS["OOTModel.writeTexRefNonCITextures"]
    OOTModel.onMaterialCommandsBuilt = _ORIGINALS["OOTModel.onMaterialCommandsBuilt"]
