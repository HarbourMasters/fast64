"""SOH XML export extensions for F3D GBI classes.
Monkey-patches to_soh_xml() and related methods onto F3D classes at registration time.
All methods are removed at unregistration time.
"""

import os
import bpy
from html import escape
from struct import pack

from ...f3d.f3d_gbi import (
    DPFullSync,
    DPLoadBlock,
    DPLoadSync,
    DPLoadTLUTCmd,
    DPLoadTile,
    DPPipeSync,
    DPSetCombineMode,
    DPSetEnvColor,
    DPSetPrimColor,
    DPSetTextureImage,
    DPSetTextureLUT,
    DPSetTile,
    DPSetTileSize,
    DPTileSync,
    FImageKey,
    FLODGroup,
    FMaterial,
    FMesh,
    FModel,
    FPaletteKey,
    FScrollData,
    FSetTileSizeScrollField,
    FTriGroup,
    GfxList,
    SP1Triangle,
    SP2Triangles,
    SPBranchList,
    SPClearGeometryMode,
    SPCullDisplayList,
    SPDisplayList,
    SPEndDisplayList,
    SPLoadGeometryMode,
    SPMatrix,
    SPSetGeometryMode,
    SPSetLights,
    SPSetOtherMode,
    SPTexture,
    SPVertex,
    Vtx,
    VtxList,
    format_asset_path,
    get_image_from_image_key,
)
from ...utility import (
    PluginError,
    writeXMLData,
    resolve_internal_export_path,
)
from ...z64.exporter.skeleton.classes import OOTSkeleton, OOTLimb

# --- Helper functions ---

def getDynamicCosmeticXmlAttrs(cosmeticEntry: str, cosmeticCategory: str):
    entry = escape(cosmeticEntry.strip(), quote=True) if cosmeticEntry else ""
    if not entry:
        return ""

    attrs = f' CosmeticEntry="{entry}"'
    category = escape(cosmeticCategory.strip(), quote=True) if cosmeticCategory else ""
    if category:
        attrs += f' CosmeticCategory="{category}"'
    return attrs


# --- Extracted methods ---

# FSetTileSizeScrollField.to_soh_xml
def _FSetTileSizeScrollField_to_soh_xml(self, tex_index, dimensions):
    """Export scroll data for a single texture as XML for SOH.

    Args:
        tex_index: Texture index (0 for TEXEL0, 1 for TEXEL1)
        dimensions: Tuple of (width, height) in texels

    Returns:
        XML string with TexScroll element, or empty string if no scrolling
    """
    width, height = dimensions
    if self.s == 0 and self.t == 0:
        return ""  # No scrolling, don't export

    return f'<TexScroll TexIndex="{tex_index}" S="{self.s}" T="{self.t}" Width="{width}" Height="{height}" Interval="{self.interval}"/>\n'


# Vtx.to_soh_xml
def _Vtx_to_soh_xml(self):
    baseStr = "<Vtx X=\"{pX}\" Y=\"{pY}\" Z=\"{pZ}\" S=\"{s}\" T=\"{t}\" R=\"{r}\" G=\"{g}\" B=\"{b}\" A=\"{a}\"/>"
    return baseStr.format(
        pX=self.position[0],
        pY=self.position[1],
        pZ=self.position[2],
        s=self.uv[0],
        t=self.uv[1],
        r=self.colorOrNormal[0],
        g=self.colorOrNormal[1],
        b=self.colorOrNormal[2],
        a=self.colorOrNormal[3],
    )


# VtxList.to_soh_xml
def _VtxList_to_soh_xml(self):
    data = "<Vertex Version=\"0\">\n"
    for vert in self.vertices:
        data += "\t" + vert.to_soh_xml() + "\n"
    data += "</Vertex>\n"
    return data


# GfxList.to_soh_xml
def _GfxList_to_soh_xml(self, modelDirPath, objectPath):
    data = "<DisplayList Version=\"0\">\n"
    for command in self.commands:
        if isinstance(command, (SPDisplayList, SPBranchList, SPVertex, DPSetTextureImage)):
            data += "\t" + command.to_soh_xml(objectPath) + "\n"
        else:
            data += "\t" + command.to_soh_xml() + "\n"

    data += "</DisplayList>\n\n"

    return data


# FModel.to_soh_xml
def _FModel_to_soh_xml(self, modelDirPath, objectPath, include_cull_vertices=True, combine_root_meshes=False):
    data = ""

    if combine_root_meshes:
        combined_call_lines = []
        combined_other_lines = []
        for mesh in self.meshes.values():
            data += mesh.to_soh_xml(modelDirPath, objectPath, include_cull_vertices, write_root_draw=False)
            call_lines, other_lines = mesh.get_soh_root_draw_lines(objectPath)
            combined_call_lines.extend(call_lines)
            if call_lines or other_lines:
                combined_other_lines = other_lines

        if combined_call_lines or combined_other_lines:
            data += (
                "<DisplayList Version=\"0\">\n"
                + "".join(combined_call_lines + combined_other_lines)
                + "</DisplayList>\n\n"
            )
    else:
        for mesh in self.meshes.values():
            data += mesh.to_soh_xml(modelDirPath, objectPath, include_cull_vertices)

    for lod in self.LODGroups.values():
        data += lod.to_soh_xml(modelDirPath)

    for fMaterial, _ in self.materials.values():
        data += fMaterial.to_soh_xml(modelDirPath, objectPath)

    self.texturesSavedLastExport = self.save_soh_textures(modelDirPath)
    self.save_soh_palettes(modelDirPath)
    self.freePalettes()

    return data


# FModel.save_soh_textures
def _FModel_save_soh_textures(self, exportPath):
    texturesSaved = 0

    for key, texture in self.textures.items():
        if isinstance(key, FPaletteKey):
            continue
        if not isinstance(key, FImageKey):
            continue

        if getattr(texture, "skip_export", False):
            continue

        image = get_image_from_image_key(key)
        imageFileName = texture.name
        fmt_code = -1

        if texture.fmt == "G_IM_FMT_RGBA":
            if texture.bitSize == "G_IM_SIZ_16b":
                fmt_code = 2
            elif texture.bitSize == "G_IM_SIZ_32b":
                fmt_code = 1
        elif texture.fmt == "G_IM_FMT_CI":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 3
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 4
        elif texture.fmt == "G_IM_FMT_I":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 5
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 6
        elif texture.fmt == "G_IM_FMT_IA":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 7
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 8
            elif texture.bitSize == "G_IM_SIZ_16b":
                fmt_code = 9

        if fmt_code == -1:
            raise PluginError(
                f"Unsupported texture format {texture.fmt}/{texture.bitSize} when exporting SOH XML textures."
            )

        bpy.path.abspath(image.filepath)
        internal_path = getattr(texture, "internal_path", "")
        targetPath = bpy.path.abspath(resolve_internal_export_path(exportPath, internal_path, imageFileName))
        targetDir = os.path.dirname(targetPath)
        if targetDir and not os.path.exists(targetDir):
            os.makedirs(targetDir, exist_ok=True)

        isPacked = image.packed_file is not None
        if not isPacked:
            image.pack()
        oldpath = image.filepath
        try:
            image.filepath = targetPath
            with open(targetPath, "wb") as file:
                file.write(
                    pack(
                        "<IIIQIQIQQQIIIIIffI",
                        0,
                        0x4F544558,
                        1,
                        0xDEADBEEFDEADBEEF,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        fmt_code,
                        texture.width,
                        texture.height,
                        0,
                        1.0,
                        1.0,
                        len(texture.data),
                    )
                    + texture.data
                )
            texturesSaved += 1
            if not isPacked:
                old_dir = ""
                unpack_path = oldpath or targetPath
                if oldpath:
                    old_dir = os.path.dirname(bpy.path.abspath(oldpath))
                else:
                    old_dir = os.path.dirname(bpy.path.abspath(targetPath))
                if old_dir and not os.path.exists(old_dir):
                    os.makedirs(old_dir, exist_ok=True)
                image.filepath = unpack_path
                try:
                    image.unpack()
                except RuntimeError:
                    pass
        except Exception as exc:
            image.filepath = oldpath
            raise Exception(str(exc))
        image.filepath = oldpath
    return texturesSaved


# FModel.save_soh_palettes
def _FModel_save_soh_palettes(self, exportPath):
    palettesSaved = 0
    for key, texture in self.textures.items():
        if not isinstance(key, FPaletteKey):
            continue
        if getattr(texture, "skip_export", False):
            continue

        palette_name = texture.filename or texture.name
        if not palette_name:
            continue
        if palette_name.endswith(".inc.c"):
            palette_filename = palette_name[:-6]
        else:
            palette_filename = os.path.splitext(palette_name)[0]

        fmt_code = -1
        if texture.fmt == "G_IM_FMT_RGBA":
            if texture.bitSize == "G_IM_SIZ_16b":
                fmt_code = 2
            elif texture.bitSize == "G_IM_SIZ_32b":
                fmt_code = 1
        elif texture.fmt == "G_IM_FMT_CI":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 3
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 4
        elif texture.fmt == "G_IM_FMT_I":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 5
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 6
        elif texture.fmt == "G_IM_FMT_IA":
            if texture.bitSize == "G_IM_SIZ_4b":
                fmt_code = 7
            elif texture.bitSize == "G_IM_SIZ_8b":
                fmt_code = 8
            elif texture.bitSize == "G_IM_SIZ_16b":
                fmt_code = 9

        if fmt_code == -1:
            raise PluginError(
                f"Unsupported palette format {texture.fmt}/{texture.bitSize} when exporting SOH XML textures."
            )

        internal_path = getattr(texture, "internal_path", "")
        targetPath = bpy.path.abspath(resolve_internal_export_path(exportPath, internal_path, palette_filename))
        targetDir = os.path.dirname(targetPath)
        if targetDir and not os.path.exists(targetDir):
            os.makedirs(targetDir, exist_ok=True)

        try:
            with open(targetPath, "wb") as file:
                file.write(
                    pack(
                        "<IIIQIQIQQQIIIIIffI",
                        0,
                        0x4F544558,
                        1,
                        0xDEADBEEFDEADBEEF,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        fmt_code,
                        texture.width,
                        texture.height,
                        0,
                        1.0,
                        1.0,
                        len(texture.data),
                    )
                    + texture.data
                )
            palettesSaved += 1
        except Exception as exc:
            raise Exception(str(exc))

    return palettesSaved


# FMesh.get_soh_root_draw_lines
def _FMesh_get_soh_root_draw_lines(self, objectPath):
    def command_xml(command):
        if isinstance(command, (SPDisplayList, SPBranchList, DPSetTextureImage)):
            return "\t" + command.to_soh_xml(objectPath) + "\n"
        return "\t" + command.to_soh_xml() + "\n"

    call_lines = []
    other_lines = []
    for command in self.draw.commands:
        if isinstance(command, (SPVertex, SPCullDisplayList)):
            continue
        line = command_xml(command)
        if isinstance(command, (SPDisplayList, SPBranchList)):
            call_lines.append(line)
        else:
            other_lines.append(line)

    return call_lines, other_lines


# FMesh.to_soh_xml
def _FMesh_to_soh_xml(self, modelDirPath, objectPath, include_cull_vertices=True, write_root_draw=True):
    if include_cull_vertices and self.cullVertexList is not None:
        cullData = self.cullVertexList.to_soh_xml()
        writeXMLData(cullData, os.path.join(modelDirPath, self.cullVertexList.name))

    for triGroup in self.triangleGroups:
        triGroup.to_soh_xml(modelDirPath, objectPath)

    for drawOverride in self.draw_overrides:
        overrideData = drawOverride.to_soh_xml(modelDirPath)
        writeXMLData(overrideData, os.path.join(modelDirPath, drawOverride.name))

    if not write_root_draw:
        return ""

    call_lines, other_lines = self.get_soh_root_draw_lines(objectPath)
    drawData = "<DisplayList Version=\"0\">\n" + "".join(call_lines + other_lines) + "</DisplayList>\n\n"
    writeXMLData(drawData, os.path.join(modelDirPath, self.draw.name))
    return drawData


# FTriGroup.to_soh_xml
def _FTriGroup_to_soh_xml(self, modelDirPath, objectPath):
    vtxData = self.vertexList.to_soh_xml()
    writeXMLData(vtxData, os.path.join(modelDirPath, self.vertexList.name))

    triListData = self.triList.to_soh_xml(modelDirPath, objectPath)
    writeXMLData(triListData, os.path.join(modelDirPath, self.triList.name))
    return ""


# FScrollData.to_soh_xml
def _FScrollData_to_soh_xml(self):
    """Export all tile scroll data as XML for SOH.

    Returns:
        XML string with TexScroll elements for each texture that has scrolling,
        or empty string if no scrolling is present
    """
    data = ""

    # Export tex0 scroll if present
    if self.tile_scroll_tex0.s != 0 or self.tile_scroll_tex0.t != 0:
        data += "\t\t" + self.tile_scroll_tex0.to_soh_xml(0, self.dimensions)

    # Export tex1 scroll if present
    if self.tile_scroll_tex1.s != 0 or self.tile_scroll_tex1.t != 0:
        data += "\t\t" + self.tile_scroll_tex1.to_soh_xml(1, self.dimensions)

    return data


# FMaterial.to_soh_xml
def _FMaterial_to_soh_xml(self, modelDirPath, objectPath):
    data = ""

    if self.material.tag.Export:
        matData = self.material.to_soh_xml(modelDirPath, objectPath)
        # Insert scroll data before closing DisplayList tag if present
        if self.scrollData.has_scroll_data():
            scrollData = self.scrollData.to_soh_xml()
            matData = matData.replace("</DisplayList>", scrollData + "</DisplayList>")
        writeXMLData(matData, os.path.join(modelDirPath, self.material.name))

    if self.revert is not None and self.revert.tag.Export:
        revData = self.revert.to_soh_xml(modelDirPath, objectPath)
        writeXMLData(revData, os.path.join(modelDirPath, self.revert.name))

    return data


# SPMatrix.to_soh_xml
def _SPMatrix_to_soh_xml(self, objectPath=""):
    name = self.matrix
    path = f"{objectPath}/{name}" if objectPath else f">{name}"
    return f'<Matrix Path="{path}" Param="{self.param}"/>'


# SPVertex.to_soh_xml
def _SPVertex_to_soh_xml(self, objectPath=""):
    baseStr = "<LoadVertices Path=\"{parent}/{vertexPath}\" VertexBufferIndex=\"{bufferIndex}\" VertexOffset=\"{vertexOffset}\" Count=\"{count}\"/>"
    return baseStr.format(
        parent=objectPath,
        vertexPath=self.vertList.name,
        bufferIndex=self.index,
        vertexOffset=self.offset,
        count=self.count,
    )


# SPDisplayList.to_soh_xml
def _SPDisplayList_to_soh_xml(self, objectPath=""):
    name = self.displayList.name
    path = format_asset_path(objectPath, name)
    return f'<CallDisplayList Path="{path}"/>'


# SPEndDisplayList.to_soh_xml
def _SPEndDisplayList_to_soh_xml(self):
    return "<EndDisplayList/>"


# SP1Triangle.to_soh_xml
def _SP1Triangle_to_soh_xml(self, objectPath=""):
    return f'<Triangle1 V00="{self.v0}" V01="{self.v1}" V02="{self.v2}"/>'


# SP2Triangles.to_soh_xml
def _SP2Triangles_to_soh_xml(self, objectPath=""):
    first = f'<Triangle1 V00="{self.v00}" V01="{self.v01}" V02="{self.v02}"/>'
    second = f'<Triangle1 V00="{self.v10}" V01="{self.v11}" V02="{self.v12}"/>'
    return first + "\n\t" + second


# SPCullDisplayList.to_soh_xml
def _SPCullDisplayList_to_soh_xml(self, objectPath=""):
    return f'<CullDisplayList Start="{self.vstart}" End="{self.vend}"/>'


# SPSetLights.to_soh_xml
def _SPSetLights_to_soh_xml(self, objectPath=""):
    return ""


# SPTexture.to_soh_xml
def _SPTexture_to_soh_xml(self, objectPath=""):
    return f'<Texture S="{self.s}" T="{self.t}" Level="{self.level}" Tile="{self.tile}" On="{self.on}"/>'


# SPSetGeometryMode.to_soh_xml
def _SPSetGeometryMode_to_soh_xml(self, objectPath=""):
    if not self.flagList:
        return "<SetGeometryMode/>"
    flags = " ".join(f'{flag}="1"' for flag in sorted(self.flagList, key=str))
    return f"<SetGeometryMode {flags}/>"


# SPClearGeometryMode.to_soh_xml
def _SPClearGeometryMode_to_soh_xml(self, objectPath=""):
    if not self.flagList:
        return "<ClearGeometryMode/>"
    flags = " ".join(f'{flag}="1"' for flag in sorted(self.flagList, key=str))
    return f"<ClearGeometryMode {flags}/>"


# SPLoadGeometryMode.to_soh_xml
def _SPLoadGeometryMode_to_soh_xml(self, objectPath=""):
    flags = ",".join(sorted(self.flagList))
    return f'<GeometryFlags Mode="Load" Flags="{flags}"/>'


# SPSetOtherMode.to_soh_xml
def _SPSetOtherMode_to_soh_xml(self, objectPath=""):
    if not self.flagList:
        return f'<SetOtherMode Cmd="{self.cmd}" Sft="{self.sft}" Length="{self.length}"/>'
    flags = " ".join(f'{flag}="1"' for flag in sorted(self.flagList, key=str))
    return f'<SetOtherMode Cmd="{self.cmd}" Sft="{self.sft}" Length="{self.length}" {flags}/>'


# DPSetTextureLUT.to_soh_xml
def _DPSetTextureLUT_to_soh_xml(self, objectPath=""):
    return f'<SetTextureLUT Mode="{self.mode}"/>'


# DPSetTextureImage.to_soh_xml
def _DPSetTextureImage_to_soh_xml(self, objectPath=""):
    prefix = self.image.internal_path if self.image.internal_path else (objectPath if self.image.filename is not None else "")
    imagePath = format_asset_path(prefix, self.image.name if self.image.name else "")
    return (
        f'<SetTextureImage Path="{imagePath}" Format="{self.fmt}" Size="{self.siz}" Width="{self.width}"/>'
    )


# DPSetCombineMode.to_soh_xml
def _DPSetCombineMode_to_soh_xml(self, objectPath=""):
    def _cc(name: str) -> str:
        return name if name.startswith("G_CCMUX_") else f"G_CCMUX_{name}"

    def _ac(name: str) -> str:
        return name if name.startswith("G_ACMUX_") else f"G_ACMUX_{name}"

    return (
        '<SetCombineLERP '
        f'A0="{_cc(self.a0)}" B0="{_cc(self.b0)}" C0="{_cc(self.c0)}" D0="{_cc(self.d0)}" '
        f'Aa0="{_ac(self.Aa0)}" Ab0="{_ac(self.Ab0)}" Ac0="{_ac(self.Ac0)}" Ad0="{_ac(self.Ad0)}" '
        f'A1="{_cc(self.a1)}" B1="{_cc(self.b1)}" C1="{_cc(self.c1)}" D1="{_cc(self.d1)}" '
        f'Aa1="{_ac(self.Aa1)}" Ab1="{_ac(self.Ab1)}" Ac1="{_ac(self.Ac1)}" Ad1="{_ac(self.Ad1)}"/>'
    )


# DPSetEnvColor.to_soh_xml
def _DPSetEnvColor_to_soh_xml(self, objectPath=""):
    return (
        f'<SetEnvColor R="{self.r}" G="{self.g}" B="{self.b}" A="{self.a}"'
        f'{getDynamicCosmeticXmlAttrs(self.cosmeticEntry, self.cosmeticCategory)}/>'
    )


# DPSetPrimColor.to_soh_xml
def _DPSetPrimColor_to_soh_xml(self, objectPath=""):
    return (
        f'<SetPrimColor M="{self.m}" L="{self.l}" R="{self.r}" G="{self.g}" B="{self.b}" A="{self.a}"'
        f'{getDynamicCosmeticXmlAttrs(self.cosmeticEntry, self.cosmeticCategory)}/>'
    )


# DPSetTileSize.to_soh_xml
def _DPSetTileSize_to_soh_xml(self, objectPath=""):
    return (
        f'<SetTileSize T="{self.tile}" Uls="{self.uls}" Ult="{self.ult}" '
        f'Lrs="{self.lrs}" Lrt="{self.lrt}"/>'
    )


# DPLoadTile.to_soh_xml
def _DPLoadTile_to_soh_xml(self, objectPath=""):
    return (
        f'<LoadTile Tile="{self.tile}" Uls="{self.uls}" Ult="{self.ult}" '
        f'Lrs="{self.lrs}" Lrt="{self.lrt}"/>'
    )


# DPSetTile.to_soh_xml
def _DPSetTile_to_soh_xml(self, objectPath=""):
    return (
        f'<SetTile Format="{self.fmt}" Size="{self.siz}" Line="{self.line}" TMem="{self.tmem}" '
        f'Tile="{self.tile}" Palette="{self.palette}" Cms0="{self.cms[0]}" Cms1="{self.cms[1]}" '
        f'Cmt0="{self.cmt[0]}" Cmt1="{self.cmt[1]}" MaskS="{self.masks}" ShiftS="{self.shifts}" '
        f'MaskT="{self.maskt}" ShiftT="{self.shiftt}"/>'
    )


# DPLoadBlock.to_soh_xml
def _DPLoadBlock_to_soh_xml(self, objectPath=""):
    return (
        f'<LoadBlock Tile="{self.tile}" Uls="{self.uls}" Ult="{self.ult}" '
        f'Lrs="{self.lrs}" Dxt="{self.dxt}" />'
    )


# DPLoadTLUTCmd.to_soh_xml
def _DPLoadTLUTCmd_to_soh_xml(self, objectPath=""):
    return f'<LoadTLUTCmd Tile="{self.tile}" Count="{self.count}"/>'


# DPFullSync.to_soh_xml
def _DPFullSync_to_soh_xml(self):
    return "<FullSync/>"


# DPTileSync.to_soh_xml
def _DPTileSync_to_soh_xml(self):
    return "<TileSync/>"


# DPPipeSync.to_soh_xml
def _DPPipeSync_to_soh_xml(self):
    return "<PipeSync/>"


# DPLoadSync.to_soh_xml
def _DPLoadSync_to_soh_xml(self):
    return "<LoadSync/>"


# --- Patch registry ---

# OOTSkeleton.toSohXML
def _OOTSkeleton_toSohXML(self, modelDirPath, objectPath):
    limbData = ""
    data = ""

    if self.limbRoot is None:
        return data

    limbList = self.createLimbList()
    isFlex = self.isFlexSkeleton()

    limbData += "<Skeleton Version=\"0\" Type=\""

    if isFlex:
        limbData += "Flex\" LimbCount=\"{lc}\" DisplayListCount=\"{dlC}\">\n".format(
            lc=self.getNumLimbs(), dlC=self.getNumDLs()
        )
    else:
        limbData += "Normal\" LimbCount=\"{lc}\">\n".format(lc=self.getNumLimbs())

    for limb in limbList:
        indLimbData = limb.toSohXML(self.hasLOD, objectPath)

        writeXMLData(indLimbData, os.path.join(modelDirPath, limb.name()))

        limbData += "\t<SkeletonLimb Path=\"{path}/{name}\"/>\n".format(
            path=objectPath if len(objectPath) > 0 else ">", name=limb.name()
        )

    limbData += "</Skeleton>"
    return limbData


# OOTLimb.toSohXML
def _OOTLimb_toSohXML(self, isLOD, objectPath):
    data = "<SkeletonLimb Version=\"0\" Type=\""

    if not isLOD:
        data += "Standard\" "
    else:
        data += "Lod\" "

    DLName = self.DL.name if self.DL is not None else "gEmptyDL"

    if DLName != "gEmptyDL":
        DLName = (objectPath + "/" if len(objectPath) > 0 else ">") + DLName

    data += (
        "LegTransX=\"{legTransX}\" LegTransY=\"{legTransY}\" LegTransZ=\"{legTransZ}\" "
        "ChildIndex=\"{firstChildIndex}\" SiblingIndex=\"{siblingIndex}\" DisplayList1=\"{displayList1}\"/>\n"
    ).format(
        legTransX=int(round(self.translation[0])),
        legTransY=int(round(self.translation[1])),
        legTransZ=int(round(self.translation[2])),
        firstChildIndex=self.firstChildIndex,
        siblingIndex=self.nextSiblingIndex,
        displayList1=DLName,
    )

    return data


_PATCHES = {
    FSetTileSizeScrollField: {
        "to_soh_xml": _FSetTileSizeScrollField_to_soh_xml,
    },
    Vtx: {
        "to_soh_xml": _Vtx_to_soh_xml,
    },
    VtxList: {
        "to_soh_xml": _VtxList_to_soh_xml,
    },
    GfxList: {
        "to_soh_xml": _GfxList_to_soh_xml,
    },
    FModel: {
        "to_soh_xml": _FModel_to_soh_xml,
        "save_soh_textures": _FModel_save_soh_textures,
        "save_soh_palettes": _FModel_save_soh_palettes,
    },
    FMesh: {
        "get_soh_root_draw_lines": _FMesh_get_soh_root_draw_lines,
        "to_soh_xml": _FMesh_to_soh_xml,
    },
    FTriGroup: {
        "to_soh_xml": _FTriGroup_to_soh_xml,
    },
    FScrollData: {
        "to_soh_xml": _FScrollData_to_soh_xml,
    },
    FMaterial: {
        "to_soh_xml": _FMaterial_to_soh_xml,
    },
    SPMatrix: {
        "to_soh_xml": _SPMatrix_to_soh_xml,
    },
    SPVertex: {
        "to_soh_xml": _SPVertex_to_soh_xml,
    },
    SPDisplayList: {
        "to_soh_xml": _SPDisplayList_to_soh_xml,
    },
    SPEndDisplayList: {
        "to_soh_xml": _SPEndDisplayList_to_soh_xml,
    },
    SP1Triangle: {
        "to_soh_xml": _SP1Triangle_to_soh_xml,
    },
    SP2Triangles: {
        "to_soh_xml": _SP2Triangles_to_soh_xml,
    },
    SPCullDisplayList: {
        "to_soh_xml": _SPCullDisplayList_to_soh_xml,
    },
    SPSetLights: {
        "to_soh_xml": _SPSetLights_to_soh_xml,
    },
    SPTexture: {
        "to_soh_xml": _SPTexture_to_soh_xml,
    },
    SPSetGeometryMode: {
        "to_soh_xml": _SPSetGeometryMode_to_soh_xml,
    },
    SPClearGeometryMode: {
        "to_soh_xml": _SPClearGeometryMode_to_soh_xml,
    },
    SPLoadGeometryMode: {
        "to_soh_xml": _SPLoadGeometryMode_to_soh_xml,
    },
    SPSetOtherMode: {
        "to_soh_xml": _SPSetOtherMode_to_soh_xml,
    },
    DPSetTextureLUT: {
        "to_soh_xml": _DPSetTextureLUT_to_soh_xml,
    },
    DPSetTextureImage: {
        "to_soh_xml": _DPSetTextureImage_to_soh_xml,
    },
    DPSetCombineMode: {
        "to_soh_xml": _DPSetCombineMode_to_soh_xml,
    },
    DPSetEnvColor: {
        "to_soh_xml": _DPSetEnvColor_to_soh_xml,
    },
    DPSetPrimColor: {
        "to_soh_xml": _DPSetPrimColor_to_soh_xml,
    },
    DPSetTileSize: {
        "to_soh_xml": _DPSetTileSize_to_soh_xml,
    },
    DPLoadTile: {
        "to_soh_xml": _DPLoadTile_to_soh_xml,
    },
    DPSetTile: {
        "to_soh_xml": _DPSetTile_to_soh_xml,
    },
    DPLoadBlock: {
        "to_soh_xml": _DPLoadBlock_to_soh_xml,
    },
    DPLoadTLUTCmd: {
        "to_soh_xml": _DPLoadTLUTCmd_to_soh_xml,
    },
    DPFullSync: {
        "to_soh_xml": _DPFullSync_to_soh_xml,
    },
    DPTileSync: {
        "to_soh_xml": _DPTileSync_to_soh_xml,
    },
    DPPipeSync: {
        "to_soh_xml": _DPPipeSync_to_soh_xml,
    },
    DPLoadSync: {
        "to_soh_xml": _DPLoadSync_to_soh_xml,
    },
    OOTSkeleton: {
        "toSohXML": _OOTSkeleton_toSohXML,
    },
    OOTLimb: {
        "toSohXML": _OOTLimb_toSohXML,
    },
}

def register():
    for cls, methods in _PATCHES.items():
        for name, func in methods.items():
            setattr(cls, name, func)

def unregister():
    for cls, methods in _PATCHES.items():
        for name in methods:
            if hasattr(cls, name):
                delattr(cls, name)
