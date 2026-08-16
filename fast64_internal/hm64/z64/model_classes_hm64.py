from __future__ import annotations

import bpy
from typing import Union

from ...utility import PluginError
from ...f3d.f3d_material import texFormatOf, texBitSizeF3D
from ...f3d.flipbook import TextureFlipbook, usesFlipbook, ootFlipbookReferenceIsValid
from ...f3d.f3d_texture_writer import getTextureNamesFromImage, writeNonCITextureData
from ...f3d.f3d_gbi import FModel, FMaterial, FImage, FImageKey
from ...z64.model_classes import OOTModel

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
            imageName, filename = getTextureNamesFromImage(flipbookTexture.image, texProp.tex_format, model)
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


def register():
    _ORIGINALS["OOTModel.validateImages"] = OOTModel.validateImages
    _ORIGINALS["OOTModel.processTexRefNonCITextures"] = OOTModel.processTexRefNonCITextures
    _ORIGINALS["OOTModel.writeTexRefNonCITextures"] = OOTModel.writeTexRefNonCITextures
    OOTModel.validateImages = validateImages
    OOTModel.processTexRefNonCITextures = processTexRefNonCITextures
    OOTModel.writeTexRefNonCITextures = writeTexRefNonCITextures


def unregister():
    OOTModel.validateImages = _ORIGINALS["OOTModel.validateImages"]
    OOTModel.processTexRefNonCITextures = _ORIGINALS["OOTModel.processTexRefNonCITextures"]
    OOTModel.writeTexRefNonCITextures = _ORIGINALS["OOTModel.writeTexRefNonCITextures"]
