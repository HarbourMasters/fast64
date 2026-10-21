from __future__ import annotations

import functools
import math
from fractions import Fraction
from typing import Optional

import numpy

from ...f3d.f3d_material import all_combiner_uses, isTexturePointSampled
from ...f3d.f3d_writer import applyOffset, findUVBounds, get_original_name
from ...utility import PluginError
from .bk64_texture_writer import resolveAddressingSize


def getTexDimensions(material):
    """The size the export converts the material's UVs against, an HD image's native one"""
    f3dMat = material.f3d_mat
    basis = f3dMat.uv_basis_index
    if basis is None:
        return (0, 0)
    return resolveAddressingSize(getattr(f3dMat, f"tex{basis}")) or (0, 0)


def getSTUVRepeats(tex_prop: "TextureProperty", texDimensions) -> tuple[Optional[Fraction], Optional[Fraction]]:
    """Texels per repeat on each axis, ahead of the texture scale, or None where it clamps"""
    repeats = []
    for field, size in zip((tex_prop.S, tex_prop.T), texDimensions):
        if field.clamp:
            repeats.append(None)
            continue
        wrap = 2**field.mask if field.mask else size  # a mask of 0 doesn't wrap
        repeats.append(Fraction(wrap) * Fraction(2) ** field.shift * (2 if field.mirror else 1))
    return tuple(repeats)


def getSampledTextures(f3dMat):
    # tex gen makes its own UVs
    if f3dMat.rdp_settings.g_lighting and f3dMat.rdp_settings.g_tex_gen:
        return []
    useDict = all_combiner_uses(f3dMat)
    return [
        texProp
        for used, texProp in ((useDict["Texture 0"], f3dMat.tex0), (useDict["Texture 1"], f3dMat.tex1))
        if used and texProp.tex_set
    ]


def getUVInterval(f3dMat, texDimensions):
    repeats = [getSTUVRepeats(texProp, texDimensions) for texProp in getSampledTextures(f3dMat)]
    if not repeats:
        return (1.0, 1.0)

    # a move has to be whole repeats of both textures, and the RSP multiplies UVs by the texture scale
    interval = []
    for axis in range(2):
        wraps = [repeat[axis] for repeat in repeats if repeat[axis] is not None]
        if not wraps:
            interval.append(None)
            continue
        texels = functools.reduce(
            lambda a, b: Fraction(math.lcm(a.numerator, b.numerator), math.gcd(a.denominator, b.denominator)),
            wraps,
        )
        scale = f3dMat.tex_scale[axis] if f3dMat.tex_scale[axis] > 0 else 1.0
        interval.append(float(texels) / (texDimensions[axis] * scale))
    return tuple(interval)


def getClampedTileUVs(material, texDimensions):
    """The UVs each clamped tile spans, per axis, or None when the material samples no texture"""
    f3dMat = material.f3d_mat
    texProps = getSampledTextures(f3dMat)
    if not texProps:
        return None
    # bilinear UVs are pulled back half a texel to sample texel centers
    offset = 0 if isTexturePointSampled(material) else 0.5
    tiles = ([], [])
    for texProp in texProps:
        for axis, field in enumerate((texProp.S, texProp.T)):
            if not field.clamp:
                continue
            scale = f3dMat.tex_scale[axis] if f3dMat.tex_scale[axis] > 0 else 1.0
            low, high = (
                (edge * 2**field.shift + offset) / (texDimensions[axis] * scale) for edge in (field.low, field.high)
            )
            # T runs against V, which the export flips
            tiles[axis].append((low, high) if axis == 0 else (1 - high, 1 - low))
    return tiles


def getHeldUV(value, inward):
    # Blender stores UVs as 32-bit floats, and a face moved onto a bound they can't hold is stored just past it
    held = numpy.float32(value)
    if (float(held) - value) * inward < 0:
        held = numpy.nextafter(held, numpy.float32(math.copysign(math.inf, inward)))
    return float(held)


def fixLargeUVs(obj):
    """The faces no move fits without changing what they show"""
    mesh = obj.data
    if len(obj.data.uv_layers) == 0:
        uv_data = obj.data.uv_layers.new().data
    else:
        uv_data = None
        for uv_layer in obj.data.uv_layers:
            if uv_layer.name == "UVMap":
                uv_data = uv_layer.data
        if uv_data is None:
            raise PluginError("Object '" + get_original_name(obj) + "' does not have a UV layer named 'UVMap.'")

    texSizeDict = {}
    tileDict = {}
    unfit = []
    if len(obj.data.materials) == 0:
        raise PluginError(f"{get_original_name(obj)}: This object needs an f3d material on it.")

        # Don't get tex dimensions here, as it also processes unused materials.
        # texSizeDict[material] = getTexDimensions(material)

    for polygon in mesh.polygons:
        material = obj.material_slots[polygon.material_index].material
        if material is None:
            raise PluginError(
                f"There are some faces on your mesh object {get_original_name(obj)}"
                " that are assigned to an empty material slot."
            )

        if material not in texSizeDict:
            texSizeDict[material] = getTexDimensions(material)
        if material.f3d_mat.use_large_textures:
            continue

        size = texSizeDict[material]
        if size[0] == 0 or size[1] == 0:
            continue
        if material not in tileDict:
            tileDict[material] = getClampedTileUVs(material, size)
        # To prevent wrong UVs when wrapping UVs into valid bounds,
        # we need to move them by whole repeats of every texture the material samples.
        UVinterval = getUVInterval(material.f3d_mat, size)
        cellSize = [1024 / size[0], 1024 / size[1]]
        low = [getHeldUV(-cell + 2, 1) for cell in cellSize]
        high = [getHeldUV(cell - 1, -1) for cell in cellSize]
        minUV, maxUV = findUVBounds(polygon, uv_data)
        startMin, startMax = list(minUV), list(maxUV)
        uvOffset = [0, 0]

        for i in range(2):
            # Move any UVs close to or straddling edge
            # with no repeat to keep to, move only as far as needed, so a face past a clamped tile keeps its edge texel
            step = UVinterval[i]
            minDiff = low[i] - minUV[i]
            if minDiff > 0:
                applyOffset(minUV, maxUV, uvOffset, math.ceil(minDiff / step) * step if step else minDiff, i)

            maxDiff = maxUV[i] - high[i]
            if maxDiff > 0:
                applyOffset(minUV, maxUV, uvOffset, -(math.ceil(maxDiff / step) * step if step else maxDiff), i)

        for loopIndex in polygon.loop_indices:
            newUV = (uv_data[loopIndex].uv[0] + uvOffset[0], uv_data[loopIndex].uv[1] + uvOffset[1])
            uv_data[loopIndex].uv = newUV

        # a face too wide for the range, or one a clamped tile shows on, can't move without changing its look
        tiles = tileDict[material]
        if tiles is not None and any(uvOffset):
            heldMin, heldMax = findUVBounds(polygon, uv_data)
            if any(
                heldMin[i] < low[i]
                or heldMax[i] > high[i]
                or uvOffset[i]
                and not all(
                    startMax[i] <= a and heldMax[i] <= a or startMin[i] >= b and heldMin[i] >= b for a, b in tiles[i]
                )
                for i in range(2)
            ):
                unfit.append(polygon.index)
    return unfit
