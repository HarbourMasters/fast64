from __future__ import annotations

import bpy
from typing import Any, Union

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
    DPSetTextureImage,
    DPTileSync,
    DPLoadTLUTCmd,
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


def _freeze_material_value(value: Any):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, set):
        return tuple(sorted((_freeze_material_value(item) for item in value), key=repr))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_material_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze_material_value(item)) for key, item in value.items()))
    if hasattr(value, "name") and isinstance(getattr(value, "name"), str):
        return (type(value).__name__, value.name)
    if hasattr(value, "__dict__"):
        skipped = {"fMaterial", "tag", "tags"}
        return (
            type(value).__name__,
            tuple(
                sorted((key, _freeze_material_value(item)) for key, item in vars(value).items() if key not in skipped)
            ),
        )
    return repr(value)


def _command_signature(command: Any):
    return _freeze_material_value(command)


def _command_state_key(command: Any):
    if isinstance(command, SPDisplayList):
        return (type(command).__name__, getattr(command.displayList, "name", None))
    if hasattr(command, "cmd") and hasattr(command, "sft") and hasattr(command, "length"):
        return (type(command).__name__, command.cmd, command.sft, command.length)
    if hasattr(command, "n"):
        return (type(command).__name__, command.n)
    return (type(command).__name__,)


def _split_texture_and_tlut_blocks(tex_commands: list[Any]):
    prim_cmds = [cmd for cmd in tex_commands if isinstance(cmd, DPSetPrimColor)]
    working = [cmd for cmd in tex_commands if not isinstance(cmd, DPSetPrimColor)]

    tex_block_cmds: list[Any] = []
    tlut_block_cmds: list[Any] = []

    idx = 0
    while idx < len(working):
        cmd = working[idx]
        next_cmd = working[idx + 1] if idx + 1 < len(working) else None

        if isinstance(cmd, DPSetTextureImage) and isinstance(next_cmd, DPTileSync):
            while idx < len(working):
                tlut_block_cmds.append(working[idx])
                last_cmd = working[idx]
                idx += 1
                if isinstance(last_cmd, DPPipeSync):
                    break
            continue

        tex_block_cmds.append(cmd)
        idx += 1

    return tex_block_cmds, tlut_block_cmds, prim_cmds


def _emit_diffed_commands(cache: dict[tuple[Any, ...], Any], commands: list[Any]):
    emitted = []
    for command in commands:
        key = _command_state_key(command)
        signature = _command_signature(command)
        if cache.get(key) != signature:
            emitted.append(command)
        cache[key] = signature
    return emitted


def _normalize_cull_flags(flags: set[str]) -> set[str]:
    normalized = set(flags)
    if "G_CULL_FRONT" in normalized and "G_CULL_BACK" in normalized:
        normalized.discard("G_CULL_FRONT")
        normalized.discard("G_CULL_BACK")
        normalized.add("G_CULL_BOTH")
    return normalized


def clear_hm64_material_state_cache(model: OOTModel):
    if hasattr(model, "_hm64_material_state_cache_by_layer"):
        delattr(model, "_hm64_material_state_cache_by_layer")


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
    render_state_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetRenderMode)]
    other_mode_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPSetOtherMode)]
    clear_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPClearGeometryMode)]
    set_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPSetGeometryMode)]
    combined_geo_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, SPGeometryMode)]
    env_cmds = [cmd for cmd in remaining_mat if isinstance(cmd, DPSetEnvColor)]
    tex_block_cmds, tlut_block_cmds, prim_cmds = _split_texture_and_tlut_blocks(tex_commands)

    if not render_state_cmds and getattr(f3dMat.rdp_settings, "set_rendermode", False):
        from ..f3d.hm64_f3d_writer import getRenderModeFlagList

        flagList, blender = getRenderModeFlagList(f3dMat.rdp_settings, fMaterial)
        render_state_cmds = [DPSetRenderMode(flagList, blender)]

    extracted_ids = {
        id(cmd)
        for cmd in (
            tlut_mode_cmds
            + texture_cmds
            + combiner_cmds
            + render_state_cmds
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

    if not getattr(self, "hm64_optimize_material_writes", False):
        emitted_commands = []
        emitted_commands.extend(head_pipe)
        emitted_commands.extend(tlut_mode_cmds)
        emitted_commands.extend(texture_cmds)
        emitted_commands.extend(tex_block_cmds)
        emitted_commands.extend(tlut_block_cmds)
        emitted_commands.extend(combiner_cmds)
        emitted_commands.extend(render_state_cmds)
        emitted_commands.extend(other_mat_cmds)
        emitted_commands.extend(clear_geo_cmds)
        emitted_commands.extend(set_geo_cmds)
        emitted_commands.extend(combined_geo_cmds)
        emitted_commands.extend(segment_cmds)
        emitted_commands.extend(env_cmds)
        emitted_commands.extend(prim_cmds)
        fMaterial.material.commands = emitted_commands
        return

    cache_by_layer = getattr(self, "_hm64_material_state_cache_by_layer", None)
    if cache_by_layer is None:
        cache_by_layer = {}
        self._hm64_material_state_cache_by_layer = cache_by_layer
    optimize_scope = getattr(fMaterial, "hm64_optimize_scope", None)
    cache_key = (drawLayer, optimize_scope)
    layer_cache = cache_by_layer.setdefault(
        cache_key, {"commands": {}, "tex_block": None, "tlut_block": None, "geo_flags": set()}
    )
    first_material_for_layer = (
        not layer_cache["geo_flags"]
        and layer_cache["tex_block"] is None
        and layer_cache["tlut_block"] is None
        and not layer_cache["commands"]
    )

    emitted_commands = []
    emitted_commands.extend(head_pipe)
    emitted_commands.extend(_emit_diffed_commands(layer_cache["commands"], tlut_mode_cmds + texture_cmds))

    tex_block_signature = tuple(_command_signature(cmd) for cmd in tex_block_cmds) if tex_block_cmds else None
    tlut_block_signature = tuple(_command_signature(cmd) for cmd in tlut_block_cmds) if tlut_block_cmds else None

    if tex_block_signature is not None and layer_cache["tex_block"] != tex_block_signature:
        emitted_commands.extend(tex_block_cmds)
    if tlut_block_signature is not None and layer_cache["tlut_block"] != tlut_block_signature:
        emitted_commands.extend(tlut_block_cmds)

    emitted_commands.extend(
        _emit_diffed_commands(layer_cache["commands"], combiner_cmds + render_state_cmds + other_mat_cmds)
    )

    current_geo_flags = set()
    for cmd in set_geo_cmds:
        current_geo_flags.update(cmd.flagList)
    for cmd in combined_geo_cmds:
        current_geo_flags.update(cmd.setFlagList)
        current_geo_flags.difference_update(cmd.clearFlagList)

    previous_geo_flags = set(layer_cache["geo_flags"])

    if first_material_for_layer:
        for cmd in clear_geo_cmds:
            flags = _normalize_cull_flags(set(cmd.flagList))
            if flags:
                emitted_commands.append(SPClearGeometryMode(flags))
        for cmd in set_geo_cmds:
            flags = _normalize_cull_flags(set(cmd.flagList))
            if flags:
                emitted_commands.append(SPSetGeometryMode(flags))
        for cmd in combined_geo_cmds:
            set_flags = _normalize_cull_flags(set(cmd.setFlagList))
            clear_flags = _normalize_cull_flags(set(cmd.clearFlagList))
            if set_flags or clear_flags:
                emitted_commands.append(SPGeometryMode(clear_flags, set_flags))
    else:
        set_geo_diff = _normalize_cull_flags(current_geo_flags - previous_geo_flags)
        clear_geo_diff = _normalize_cull_flags(previous_geo_flags - current_geo_flags)

        if clear_geo_diff:
            emitted_commands.append(SPClearGeometryMode(set(clear_geo_diff)))
        if set_geo_diff:
            emitted_commands.append(SPSetGeometryMode(set(set_geo_diff)))

    emitted_commands.extend(segment_cmds)
    emitted_commands.extend(_emit_diffed_commands(layer_cache["commands"], env_cmds + prim_cmds))

    layer_cache["tex_block"] = tex_block_signature
    layer_cache["tlut_block"] = tlut_block_signature
    layer_cache["geo_flags"] = set(current_geo_flags)

    fMaterial.material.commands = emitted_commands


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
