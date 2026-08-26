from __future__ import annotations

import struct
import zlib

from ...f3d.f3d_gbi import FImage, FModel, FPaletteKey
from ...utility import PluginError
from .bk64_constants import (
    ANIM_FRAME_FORMATS,
    BIN_TEX_FORMATS,
    BK_PALETTE_SIZE,
    BK_TEX_TYPE,
    F3D_FMT_TO_OTEX,
    MAX_TEXTURE_DIM,
    MIP_BASE_PROP,
    MIP_PYRAMID_PROP,
    MIP_PYRAMID_SIZE,
    MIP_ROW_BYTES,
    MIP_TEXTURE_DIM,
    OTEX_TYPE,
    otr_header,
    OTR_TEXTURE_V0,
    OTR_TEXTURE_V1,
    PALETTED_FORMATS,
    RT_TEXTURE,
    SEG_ANIM_BASE,
    SEG_TEX,
    SEG_TEX_BLOB,
    SHADE_FOLD_FORMATS,
    TEX_FLAG_LOAD_AS_RAW,
    WHITE_TEXTURE_DIM,
)


def _write_texture_resource(otex_format: str, width: int, height: int, pixels: bytes, hd_scale=None):
    """u32 type, u32 width, u32 height, u32 byte count, then native N64 pixels"""
    if hd_scale is None:
        data = otr_header(RT_TEXTURE, OTR_TEXTURE_V0)
        data.extend(struct.pack("<IIII", OTEX_TYPE[otex_format], width, height, len(pixels)))
    else:
        h_scale, v_scale = hd_scale
        # V1 fits the raw flag and both scales in ahead of the count. Width and
        # height stay the sizes the display list tiles, the pixels RGBA8 real size
        data = otr_header(RT_TEXTURE, OTR_TEXTURE_V1)
        data.extend(
            struct.pack(
                "<IIIIffI",
                OTEX_TYPE[otex_format],
                width,
                height,
                TEX_FLAG_LOAD_AS_RAW,
                h_scale,
                v_scale,
                len(pixels),
            )
        )
    data.extend(pixels)
    return data


def _hd_scale_of(fImage):
    """(h byte scale, v pixel scale) when an image was spoofed down, else None"""
    h_scale = getattr(fImage, "hd_byte_scale", 1.0)
    v_scale = getattr(fImage, "hd_pixel_scale", 1.0)
    return None if h_scale == 1.0 and v_scale == 1.0 else (h_scale, v_scale)


def f3d_settings(material):
    """The f3d_mat a material keeps its settings on, or the material before Fast64 4"""
    return material.f3d_mat if material.mat_ver > 3 else material


def f3d_materials(mesh_objects):
    """(material, its f3d settings) for every F3D material on these objects"""
    for mesh_obj in mesh_objects:
        for slot in mesh_obj.material_slots:
            material = slot.material
            if material is None or not getattr(material, "is_f3d", False):
                continue
            yield material, f3d_settings(material)


def reads_texel1(f3d_mat):
    for cycle in (f3d_mat.combiner1, f3d_mat.combiner2):
        for name in ("A", "B", "C", "D", "A_alpha", "B_alpha", "C_alpha", "D_alpha"):
            if "TEXEL1" in getattr(cycle, name):
                return True
    return False


def _kept_pyramid(image, base: bytes):
    """The mip levels the image was imported with, or None once its base moves"""
    stored = image.get(MIP_PYRAMID_PROP) if image is not None else None
    if not stored or image.get(MIP_BASE_PROP) != f"{zlib.crc32(base):08x}":
        return None
    kept = bytes.fromhex(stored)
    return kept if len(kept) == MIP_PYRAMID_SIZE else None


def _mip_pyramid(pixels: bytes) -> bytes:
    """The 16 down to 1 texel levels of a 32x32 RGBA16 base"""

    def decode(data, size):
        out = []
        for index in range(size * size):
            value = (data[index * 2] << 8) | data[index * 2 + 1]
            out.append(((value >> 11) & 31, (value >> 6) & 31, (value >> 1) & 31, value & 1))
        return out

    def shrink(texels, size):
        half = size // 2
        out = []
        for y in range(half):
            for x in range(half):
                cells = [texels[(y * 2 + dy) * size + x * 2 + dx] for dy in (0, 1) for dx in (0, 1)]
                color = tuple(sum(cell[channel] for cell in cells) // 4 for channel in range(3))
                out.append(color + (1 if sum(cell[3] for cell in cells) >= 2 else 0,))
        return out

    rows = [bytearray(MIP_ROW_BYTES) for _ in range(MIP_PYRAMID_SIZE // MIP_ROW_BYTES)]
    level = decode(pixels, MIP_TEXTURE_DIM)
    size = MIP_TEXTURE_DIM
    while size > 1:
        level = shrink(level, size)
        size //= 2
        data = bytearray()
        for red, green, blue, alpha in level:
            value = (red << 11) | (green << 6) | (blue << 1) | alpha
            data += bytes((value >> 8, value & 0xFF))
        stride = size * 2
        at = MIP_ROW_BYTES - stride * 2
        for row in range(size):
            rows[row][at : at + stride] = data[row * stride : (row + 1) * stride]
    return b"".join(bytes(row) for row in rows)


def collect_textures(
    fModel: FModel, embed_images: bool, image_folds=None, opaque_images=None, mip_images=None, animated=None
):
    # a resource puts images in _tex_<i> siblings behind segment 0xFF, a ROM
    # puts everything in the blob behind segment 2
    resources, infos, blob = [], [], bytearray()
    animated_offsets = {}

    palette_size = {}
    for key, fImage in fModel.textures.items():
        otex_format = F3D_FMT_TO_OTEX.get((fImage.fmt, fImage.bitSize))
        if otex_format is None:
            raise PluginError(
                f"Texture '{fImage.name}' uses {fImage.fmt}/{fImage.bitSize}, which has no BK equivalent."
            )
        if isinstance(key, FPaletteKey):
            continue
        if embed_images and otex_format not in BIN_TEX_FORMATS:
            raise PluginError(
                f"Texture '{fImage.name}' is {otex_format}, which BKTextureInfo has no type bit "
                "for. Use RGBA16, RGBA32, IA8, CI4 or CI8."
            )
        if embed_images and _hd_scale_of(fImage) is not None:
            raise PluginError(
                f"Texture '{fImage.name}' is HD. A .bin holds its images as bare bytes in the "
                "model's own blob, with no resource header to carry the scales. Export o2r."
            )
        if otex_format in PALETTED_FORMATS:
            shared = key.imagesSharingPalette or (key.image,)
            palette_size[shared] = max(palette_size.get(shared, 0), BK_PALETTE_SIZE[otex_format])

    palette_offset, palette_colors, palette_data, palette_address, anim_palettes = {}, {}, {}, {}, {}
    for key, fImage in fModel.textures.items():
        if not isinstance(key, FPaletteKey):
            continue
        if not fImage.converted:
            raise PluginError(f"Palette '{fImage.name}' was not converted to N64 format.")
        shared_key = key.imagesSharingPalette
        padded = bytes(fImage.data) + bytes(palette_size.get(shared_key, 0) - len(fImage.data))
        if embed_images:
            opaque = all((opaque_images or {}).get(image, True) for image in shared_key or ())
            padded = _flatten_shade(
                padded, "RGBA16", (image_folds or {}).get(shared_key[0] if shared_key else None), opaque
            )
        palette_colors[shared_key] = fImage.height
        palette_data[shared_key] = padded
        animated_shared = any(image in (animated or {}) for image in shared_key or ())
        if not embed_images and not animated_shared:
            palette_offset[shared_key] = len(blob)
            blob.extend(padded)

    for key, fImage in fModel.textures.items():
        if isinstance(key, FPaletteKey):
            continue
        otex_format = F3D_FMT_TO_OTEX[(fImage.fmt, fImage.bitSize)]
        if fImage.width > MAX_TEXTURE_DIM or fImage.height > MAX_TEXTURE_DIM:
            raise PluginError(
                f"Texture '{fImage.name}' is {fImage.width}x{fImage.height}, and BK stores each "
                f"side in one byte. Scale it under {MAX_TEXTURE_DIM}."
            )
        if not fImage.converted:
            raise PluginError(f"Texture '{fImage.name}' was not converted to N64 format.")

        paletted = otex_format in PALETTED_FORMATS
        shared = key.imagesSharingPalette or (key.image,)
        if paletted and shared not in palette_data:
            raise PluginError(f"Texture '{fImage.name}' is {otex_format} but exported without a palette.")

        animation = (animated or {}).get(key.image)
        if animation is not None:
            slot, frames, _rate = animation
            if otex_format not in ANIM_FRAME_FORMATS:
                raise PluginError(
                    f"Animated texture '{fImage.name}' is {otex_format}. Use RGBA16, RGBA32, IA8, CI4 or CI8 frames."
                )
            if _hd_scale_of(fImage) is not None:
                raise PluginError(
                    f"Animated texture '{fImage.name}' is HD. The game slides the segment on by a "
                    "frame of N64 sized bytes and a raw strip no longer matches. Scale it to fit TMEM."
                )
            strip_offset = len(blob)
            if strip_offset > 0xFFFFFF:
                raise PluginError(f"'{fImage.name}' lands past the 16MB a segment can address. Use fewer textures.")
            segment_base = (SEG_ANIM_BASE - slot) << 24
            if paletted:
                pixels = _strip_ci_pixels(fImage, frames, otex_format, palette_data[shared])
                # the palette rides ahead of each frame and both slide together
                anim_palettes[shared] = segment_base | strip_offset
                fImage.startAddress = segment_base | (strip_offset + BK_PALETTE_SIZE[otex_format])
            else:
                pixels = _strip_pixels(fImage, frames, otex_format)
                fImage.startAddress = segment_base | strip_offset
            blob.extend(pixels)
            frame_bytes = len(pixels) // len(frames)
            animated_offsets[slot] = (strip_offset, frame_bytes, len(frames))
            # BKTextureInfo holds height as a u8. GV's 21 frame strip declares
            # one frame, the short vanilla strips their total
            strip_height = fImage.height * len(frames)
            if strip_height > MAX_TEXTURE_DIM:
                strip_height = fImage.height
            if not embed_images:
                resources.append(_write_texture_resource(otex_format, fImage.width, strip_height, pixels))
            infos.append(
                dict(
                    type=BK_TEX_TYPE.get(otex_format, 0),
                    width=fImage.width,
                    height=strip_height,
                    colors=0,
                    offset=strip_offset,
                )
            )
            continue

        if embed_images:
            # the game's layout puts a palette right ahead of its image, even
            # if a shared one gets written twice
            entry_offset = len(blob)
            if paletted:
                palette = palette_data[shared]
                blob.extend(palette)
                palette_address.setdefault(shared, entry_offset)
            image_offset = len(blob)
            pixels = bytes(fImage.data)
            if not paletted:  # a paletted image is recolored through its palette
                opaque = (opaque_images or {}).get(key.image, True)
                pixels = _flatten_shade(pixels, otex_format, (image_folds or {}).get(key.image), opaque)
            blob.extend(pixels)
            fImage.startAddress = (SEG_TEX_BLOB << 24) | image_offset
        else:
            image_offset = None
            fImage.startAddress = (SEG_TEX << 24) | len(resources)
            pixels = bytes(fImage.data)
            hd_scale = _hd_scale_of(fImage)
            if mip_images and key.image in mip_images:
                if hd_scale is not None:
                    raise PluginError(
                        f"Texture '{fImage.name}' is HD and mipmapped. The pyramid needs N64 sized "
                        "pixels an HD image no longer carries. Drop TEXEL0 or scale it to fit TMEM."
                    )
                pixels += _kept_pyramid(key.image, pixels) or _mip_pyramid(pixels)
            resources.append(_write_texture_resource(otex_format, fImage.width, fImage.height, pixels, hd_scale))

        # one entry per texture, in display list order. Fewer would slide the
        # indices and send a CI texture to the wrong palette.
        infos.append(
            dict(
                type=BK_TEX_TYPE.get(otex_format, 0),
                width=fImage.width,
                height=fImage.height,
                colors=palette_colors[shared] if paletted else 0,
                offset=entry_offset if embed_images else (palette_offset[shared] if paletted else 0),
            )
        )

    white_offset = None
    if embed_images:
        white_offset = len(blob)
        blob.extend(bytes([0xFF]) * (WHITE_TEXTURE_DIM * WHITE_TEXTURE_DIM * 2))
        infos.append(
            dict(
                type=BK_TEX_TYPE["RGBA16"],
                width=WHITE_TEXTURE_DIM,
                height=WHITE_TEXTURE_DIM,
                colors=0,
                offset=white_offset,
            )
        )

    # segment 2 is bound to the blob itself, making an offset into it the address
    if embed_images:
        palette_offset = palette_address
    for key, fImage in fModel.textures.items():
        if isinstance(key, FPaletteKey):
            if key.imagesSharingPalette in anim_palettes:
                fImage.startAddress = anim_palettes[key.imagesSharingPalette]
            else:
                fImage.startAddress = (SEG_TEX_BLOB << 24) | palette_offset[key.imagesSharingPalette]

    return resources, infos, bytes(blob), white_offset, animated_offsets


def draw_layer_of(material, scene_layer: str):
    layer = getattr(material, "hm64_bk64_draw_layer", "SCENE") if material is not None else "SCENE"
    return scene_layer if layer == "SCENE" else layer


def _combiner_fold(f3d_mat):
    # LERP is Fast64's decal idiom, where the texture's alpha picks a flat base
    # color or the detail on top
    cycle = f3d_mat.combiner1
    signature = (cycle.A, cycle.B, cycle.C, cycle.D)
    if signature == ("TEXEL0", "SHADE", "TEXEL0_ALPHA", "SHADE"):
        return "LERP"
    if signature == ("TEXEL0", "0", "SHADE", "0"):
        return "MULTIPLY"
    return None


def image_folds(mesh_objects, shade_by_material):
    """The (shade, fold) each image is drawn with, keyed by the image"""
    # an image drawn two ways can't be baked either way. It keeps its colors.
    folds = {}
    for material, f3d_mat in f3d_materials(mesh_objects):
        fold = _combiner_fold(f3d_mat)
        shade = shade_by_material.get(material.name, (255, 255, 255, 255))[:3]
        for tex_slot in (f3d_mat.tex0, f3d_mat.tex1):
            if tex_slot.tex is None or not tex_slot.tex_set:
                continue
            if tex_slot.tex_format not in SHADE_FOLD_FORMATS:
                # nothing to bake into
                continue
            folds.setdefault(tex_slot.tex, set()).add((shade, fold))
    return {image: next(iter(ways)) for image, ways in folds.items() if len(ways) == 1}


def image_opacity(mesh_objects, scene_layer: str):
    """Whether each image is only ever drawn on the opaque layer, keyed by the image"""
    opaque = {}
    for material, f3d_mat in f3d_materials(mesh_objects):
        layer = draw_layer_of(material, scene_layer)
        for tex_slot in (f3d_mat.tex0, f3d_mat.tex1):
            if tex_slot.tex is None or not tex_slot.tex_set:
                continue
            opaque[tex_slot.tex] = opaque.get(tex_slot.tex, True) and layer == "OPAQUE"
    return opaque


def _flatten_shade(data: bytes, otex_format: str, fold, opaque: bool):
    # the game does this with the combiner, a plain texture viewer doesn't
    if fold is None:
        return data
    shade, mode = fold
    if mode is None or (shade == (255, 255, 255) and not opaque):
        return data

    out = bytearray(data)
    if otex_format == "RGBA32":
        for i in range(0, len(out), 4):
            for channel in range(3):
                if mode == "LERP":
                    out[i + channel] = out[i + channel] if out[i + 3] > 127 else shade[channel]
                else:
                    out[i + channel] = out[i + channel] * shade[channel] // 255
            if opaque:
                out[i + 3] = 255
        return bytes(out)

    # RGBA16, either the image itself or a palette entry
    for i in range(0, len(out) - 1, 2):
        value = (out[i] << 8) | out[i + 1]
        channels = [(value >> 11) & 31, (value >> 6) & 31, (value >> 1) & 31]
        if mode == "LERP" and not value & 1:
            channels = [shade[c] * 31 // 255 for c in range(3)]
        elif mode == "MULTIPLY":
            channels = [channels[c] * shade[c] // 255 for c in range(3)]
        alpha = 1 if opaque else value & 1
        value = (channels[0] << 11) | (channels[1] << 6) | (channels[2] << 1) | alpha
        out[i] = value >> 8
        out[i + 1] = value & 0xFF
    return bytes(out)


def _strip_pixels(fImage, frames, otex_format: str):
    """Every frame's N64 bytes end to end, frame 0 first"""
    from ...f3d.f3d_texture_writer import writeNonCITextureData

    first = bytes(fImage.data)  # frame 0 is already converted, keep it exactly
    encoded = bytearray(first)
    for frame in frames[1:]:
        spare = FImage(frame.name, fImage.fmt, fImage.bitSize, frame.size[0], frame.size[1], None)
        writeNonCITextureData(frame, spare, otex_format)
        if len(spare.data) != len(first):
            raise PluginError(
                f"Frame '{frame.name}' encodes to {len(spare.data)} bytes and frame 0 to {len(first)}. "
                "Every frame has to be the same size and format."
            )
        encoded += spare.data
    return bytes(encoded)


def _strip_ci_pixels(fImage, frames, otex_format: str, palette0: bytes):
    """Every frame as its own palette then image, frame 0 first"""
    from ...f3d.f3d_texture_writer import getColorsUsedInImage, writeCITextureData

    pal_size = BK_PALETTE_SIZE[otex_format]
    first = bytes(fImage.data)
    encoded = bytearray(palette0 + first)
    for frame in frames[1:]:
        colors = getColorsUsedInImage(frame, "RGBA16")
        if len(colors) > pal_size // 2:
            raise PluginError(
                f"Frame '{frame.name}' uses {len(colors)} colors and {otex_format} palettes hold "
                f"{pal_size // 2}. Reduce its colors, or use RGBA16 frames."
            )
        spare = FImage(frame.name, fImage.fmt, fImage.bitSize, frame.size[0], frame.size[1], None)
        writeCITextureData(frame, spare, colors, "RGBA16", otex_format)
        if len(spare.data) != len(first):
            raise PluginError(
                f"Frame '{frame.name}' encodes to {len(spare.data)} bytes and frame 0 to {len(first)}. "
                "Every frame has to be the same size and format."
            )
        palette = bytearray(pal_size)
        for index, color in enumerate(colors):
            palette[index * 2] = color >> 8
            palette[index * 2 + 1] = color & 0xFF
        encoded += palette + spare.data
    return bytes(encoded)


def animated_slots(fModel: FModel):
    """{frame 0's image: (slot, [frames], rate)} for every animated material"""
    animated, claimed = {}, {}
    for key, value in fModel.materials.items():
        material = key[0]
        if getattr(material, "hm64_bk64_anim_tex", "NONE") == "NONE":
            continue

        which = material.hm64_bk64_anim_tex
        source = getattr(material.f3d_mat, which.lower()).tex
        frames = [entry.image for entry in material.flipbookGroup.flipbook0.textures if entry.image]
        slot = material.hm64_bk64_anim_slot

        if source is None:
            raise PluginError(f"'{material.name}' animates {which} but has no texture there.")
        if len(frames) < 2:
            raise PluginError(
                f"'{material.name}' is animated but lists {len(frames)} of the two frames it needs "
                "at least. Add them under Animated Texture, starting with the one the material uses."
            )
        if frames[0] != source:
            raise PluginError(
                f"'{material.name}' lists '{frames[0].name}' first but samples '{source.name}'. The "
                "first frame has to be the texture the material uses."
            )
        sizes = {tuple(frame.size) for frame in frames}
        if len(sizes) > 1:
            raise PluginError(f"'{material.name}' has frames of {len(sizes)} different sizes. Every frame is one tile.")
        if slot in claimed and claimed[slot] != frames:
            raise PluginError(
                f"'{material.name}' and '{claimed[slot][0].name}'s material both drive slot {slot} "
                "with different frames. Give one of them another slot."
            )
        claimed[slot] = frames
        animated[frames[0]] = (slot, frames, material.hm64_bk64_anim_rate)
    return animated
