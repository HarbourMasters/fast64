from __future__ import annotations

import bpy
from bpy.types import Material, UILayout
from bpy.utils import register_class, unregister_class

from ...f3d import f3d_material as base
from ...f3d.f3d_material import F3DMaterialProperty, F3DPanel, TextureProperty, setAutoProp

from ..utility import is_hm64
from .f3d_texture_writer_hm64 import getNativeSizeOverride, resolveNativeSize


_ORIGINALS = {}

_HD_NATIVE_SIZES = (4, 8, 16, 32, 64, 128, 256)
_HD_NATIVE_SIZE_ITEMS = [("0", "Auto (TMEM-fit)", "Divide down to fit the TMEM budget; may not match the original asset's true resolution")] + [
    (str(v), str(v), f"{v} texels") for v in _HD_NATIVE_SIZES
]


def is_hm64_feature_set() -> bool:
    return True


def _update_tex_values_field(self: Material, texProperty: TextureProperty, tex_size: list[int], tex_index: int):
    if not is_hm64():
        return _ORIGINALS["update_tex_values_field"](self, texProperty, tex_size, tex_index)

    nodes = self.node_tree.nodes
    textureSettings = nodes["TextureSettings"]
    inputs = textureSettings.inputs

    base.set_texture_size(self, tex_size, tex_index)

    if texProperty.autoprop:
        tex_size = tuple(tex_size)
        native_size = resolveNativeSize(texProperty, tex_size)
        setAutoProp(texProperty.S, native_size[0])
        setAutoProp(texProperty.T, native_size[1])

    str_index = str(tex_index)

    inputs[str_index + " S Low"].default_value = base.trunc_10_2(texProperty.S.low)
    inputs[str_index + " T Low"].default_value = base.trunc_10_2(texProperty.T.low)

    inputs[str_index + " S High"].default_value = base.trunc_10_2(texProperty.S.high)
    inputs[str_index + " T High"].default_value = base.trunc_10_2(texProperty.T.high)

    inputs[str_index + " ClampX"].default_value = 1 if texProperty.S.clamp else 0
    inputs[str_index + " ClampY"].default_value = 1 if texProperty.T.clamp else 0

    inputs[str_index + " S Mask"].default_value = texProperty.S.mask
    inputs[str_index + " T Mask"].default_value = texProperty.T.mask


class HM64_OT_ApplyReferenceSize(bpy.types.Operator):
    bl_idname = "material.hm64_apply_reference_size"
    bl_label = "Apply Native Size to Reference"
    bl_description = (
        "Fill Texture Size and S/T tile bounds (mask/shift/low/high) from the Native Width/Height selection, "
        "since Auto Set Other Properties doesn't track reference-mode textures"
    )
    bl_options = {"REGISTER", "UNDO"}

    combinerTexIndex: bpy.props.IntProperty()

    def execute(self, context):
        material = context.material
        texProp = getattr(material.f3d_mat, "tex" + str(self.combinerTexIndex))
        native_size = getNativeSizeOverride(texProp)
        if native_size is None:
            self.report({"ERROR"}, "Set Native Width and Native Height first.")
            return {"CANCELLED"}
        texProp.tex_reference_size = native_size
        setAutoProp(texProp.S, native_size[0])
        setAutoProp(texProp.T, native_size[1])
        self.report({"INFO"}, f"Set Texture Size and S/T bounds to {native_size}.")
        return {"FINISHED"}


def _ui_dynamic_cosmetic_entry(self, f3dMat, layout, enabledProp, nameProp, categoryProp):
    layout.prop(f3dMat, enabledProp, text="Dynamic Cosmetic Entry")
    if getattr(f3dMat, enabledProp):
        dynamicEntry = layout.column()
        dynamicEntry.prop(f3dMat, nameProp, text="Name")
        dynamicEntry.prop(f3dMat, categoryProp, text="Category")


def _ui_prim(self, material, layout, setName, setProp, showCheckBox):
    f3dMat = material.f3d_mat
    inputGroup = layout.row()
    prop_input_name = inputGroup.column()
    prop_input = inputGroup.column()
    if showCheckBox:
        prop_input_name.prop(f3dMat, setName, text="Primitive Color")
    else:
        prop_input_name.label(text="Primitive Color")

    prop_input.prop(f3dMat, "prim_color", text="")
    prop_input.prop(f3dMat, "prim_lod_frac", text="Prim LOD Fraction")
    prop_input.prop(f3dMat, "prim_lod_min", text="Min LOD Ratio")
    self.ui_dynamic_cosmetic_entry(
        f3dMat,
        prop_input,
        "prim_dynamic_entry",
        "prim_dynamic_entry_name",
        "prim_dynamic_entry_category",
    )
    prop_input.enabled = setProp
    return inputGroup


def _ui_env(self, material, layout, showCheckBox):
    inputGroup = layout.row()
    prop_input_name = inputGroup.column()
    prop_input = inputGroup.column()
    f3dMat = material.f3d_mat

    if showCheckBox:
        prop_input_name.prop(f3dMat, "set_env", text="Environment Color")
    else:
        prop_input_name.label(text="Environment Color")
    prop_input.prop(f3dMat, "env_color", text="")
    self.ui_dynamic_cosmetic_entry(
        f3dMat,
        prop_input,
        "env_dynamic_entry",
        "env_dynamic_entry_name",
        "env_dynamic_entry_category",
    )
    prop_input.enabled = f3dMat.set_env
    return inputGroup


def _ui_image(
    canUseLargeTextures: bool,
    layout: UILayout,
    material: Material,
    textureProp: TextureProperty,
    name: str,
    showCheckBox: bool,
    hide_lowhigh=False,
):
    _ORIGINALS["ui_image"](canUseLargeTextures, layout, material, textureProp, name, showCheckBox, hide_lowhigh)
    if not textureProp.menu:
        return

    box = layout.box().column()
    if is_hm64_feature_set() and not textureProp.use_tex_reference and textureProp.tex_format[:2] == "CI":
        row = box.row(align=True)
        row.prop(textureProp, "custom_palette_name", text="TLUT Name")
        row = box.row(align=True)
        row.prop(textureProp, "palette_color_count", text="Color Count")
    if not textureProp.use_tex_reference:
        row = box.row(align=True)
        row.prop(textureProp, "is_vanilla_texture", text="Is Vanilla Texture?")
        row = box.row(align=True)
        row.prop(textureProp, "texture_internal_path", text="Internal Path")
        if is_hm64_feature_set():
            row = box.row(align=True)
            row.prop(textureProp, "hd_native_width", text="Native Width")
            row.prop(textureProp, "hd_native_height", text="Native Height")
    elif is_hm64_feature_set():
        row = box.row(align=True)
        row.prop(textureProp, "hd_native_width", text="Native Width")
        row.prop(textureProp, "hd_native_height", text="Native Height")
        row = box.row(align=True)
        applyOp = row.operator(HM64_OT_ApplyReferenceSize.bl_idname, text="Apply to Texture Size")
        applyOp.combinerTexIndex = int(name[-1]) if name and name[-1].isdigit() else 0


def _texture_to_dict(self):
    data = _ORIGINALS["TextureProperty.to_dict"](self)
    if self.custom_palette_name:
        data["customTLUTName"] = self.custom_palette_name
    data["paletteColorCount"] = self.palette_color_count
    data["isVanillaTexture"] = self.is_vanilla_texture
    if self.texture_internal_path:
        data["internalPath"] = self.texture_internal_path
    return data


def _texture_from_dict(self, data: dict):
    _ORIGINALS["TextureProperty.from_dict"](self, data)
    self.custom_palette_name = data.get("customTLUTName", self.custom_palette_name)
    self.palette_color_count = data.get("paletteColorCount", self.palette_color_count)
    self.is_vanilla_texture = data.get("isVanillaTexture", self.is_vanilla_texture)
    self.texture_internal_path = data.get("internalPath", self.texture_internal_path)


def _n64_colors_to_dict(self, use_dict: dict[str]):
    data = _ORIGINALS["F3DMaterialProperty.n64_colors_to_dict"](self, use_dict)
    if use_dict["Environment"] and "environment" in data:
        data["environment"].update(
            {
                "dynamicEntry": self.env_dynamic_entry,
                "dynamicEntryName": self.env_dynamic_entry_name,
                "dynamicEntryCategory": self.env_dynamic_entry_category,
            }
        )
    if use_dict["Primitive"] and "primitive" in data:
        data["primitive"].update(
            {
                "dynamicEntry": self.prim_dynamic_entry,
                "dynamicEntryName": self.prim_dynamic_entry_name,
                "dynamicEntryCategory": self.prim_dynamic_entry_category,
            }
        )
    return data


def _n64_colors_from_dict(self, data: dict):
    _ORIGINALS["F3DMaterialProperty.n64_colors_from_dict"](self, data)
    env = data.get("environment", {})
    self.env_dynamic_entry = env.get("dynamicEntry", self.env_dynamic_entry)
    self.env_dynamic_entry_name = env.get("dynamicEntryName", self.env_dynamic_entry_name)
    self.env_dynamic_entry_category = env.get("dynamicEntryCategory", self.env_dynamic_entry_category)
    prim = data.get("primitive", {})
    self.prim_dynamic_entry = prim.get("dynamicEntry", self.prim_dynamic_entry)
    self.prim_dynamic_entry_name = prim.get("dynamicEntryName", self.prim_dynamic_entry_name)
    self.prim_dynamic_entry_category = prim.get("dynamicEntryCategory", self.prim_dynamic_entry_category)


def register():
    register_class(HM64_OT_ApplyReferenceSize)

    _ORIGINALS["ui_image"] = base.ui_image
    _ORIGINALS["update_tex_values_field"] = base.update_tex_values_field
    _ORIGINALS["TextureProperty.to_dict"] = TextureProperty.to_dict
    _ORIGINALS["TextureProperty.from_dict"] = TextureProperty.from_dict
    _ORIGINALS["F3DMaterialProperty.n64_colors_to_dict"] = F3DMaterialProperty.n64_colors_to_dict
    _ORIGINALS["F3DMaterialProperty.n64_colors_from_dict"] = F3DMaterialProperty.n64_colors_from_dict

    F3DPanel.ui_dynamic_cosmetic_entry = _ui_dynamic_cosmetic_entry
    F3DPanel.ui_prim = _ui_prim
    F3DPanel.ui_env = _ui_env
    base.ui_image = _ui_image
    base.update_tex_values_field = _update_tex_values_field
    TextureProperty.to_dict = _texture_to_dict
    TextureProperty.from_dict = _texture_from_dict
    F3DMaterialProperty.n64_colors_to_dict = _n64_colors_to_dict
    F3DMaterialProperty.n64_colors_from_dict = _n64_colors_from_dict

    TextureProperty.palette_color_count = bpy.props.IntProperty(
        name="Color Count",
        description="Total color count used by the image texture, for vanilla TLUTs this can usually be left at 255.",
        default=255,
        min=1,
        max=255,
    )
    TextureProperty.is_vanilla_texture = bpy.props.BoolProperty(
        name="Is Vanilla Texture?",
        description="Check this if you are using a vanilla texture, this simply does not export a texture image.",
        default=False,
    )
    TextureProperty.texture_internal_path = bpy.props.StringProperty(
        name="Internal Path",
        description="Points the texture to a separate internal path. Leave this blank to use the normal export path.",
        default="",
    )
    TextureProperty.custom_palette_name = bpy.props.StringProperty(
        name="TLUT Name",
        description="Override the TLUT name used when exporting CI textures",
        default="",
    )
    TextureProperty.hd_native_width = bpy.props.EnumProperty(
        items=_HD_NATIVE_SIZE_ITEMS,
        name="Native Width",
        description="N64-native/TMEM width to spoof for this texture's addressing. Overrides TMEM-fit auto-divide.",
        default="0",
    )
    TextureProperty.hd_native_height = bpy.props.EnumProperty(
        items=_HD_NATIVE_SIZE_ITEMS,
        name="Native Height",
        description="N64-native/TMEM height to spoof for this texture's addressing. Overrides TMEM-fit auto-divide.",
        default="0",
    )

    F3DMaterialProperty.prim_dynamic_entry = bpy.props.BoolProperty(name="Dynamic Cosmetic Entry", default=False)
    F3DMaterialProperty.prim_dynamic_entry_name = bpy.props.StringProperty(name="Dynamic Cosmetic Entry Name")
    F3DMaterialProperty.prim_dynamic_entry_category = bpy.props.StringProperty(name="Dynamic Cosmetic Entry Category")
    F3DMaterialProperty.env_dynamic_entry = bpy.props.BoolProperty(name="Dynamic Cosmetic Entry", default=False)
    F3DMaterialProperty.env_dynamic_entry_name = bpy.props.StringProperty(name="Dynamic Cosmetic Entry Name")
    F3DMaterialProperty.env_dynamic_entry_category = bpy.props.StringProperty(name="Dynamic Cosmetic Entry Category")


def unregister():
    unregister_class(HM64_OT_ApplyReferenceSize)

    base.ui_image = _ORIGINALS["ui_image"]
    base.update_tex_values_field = _ORIGINALS["update_tex_values_field"]
    TextureProperty.to_dict = _ORIGINALS["TextureProperty.to_dict"]
    TextureProperty.from_dict = _ORIGINALS["TextureProperty.from_dict"]
    F3DMaterialProperty.n64_colors_to_dict = _ORIGINALS["F3DMaterialProperty.n64_colors_to_dict"]
    F3DMaterialProperty.n64_colors_from_dict = _ORIGINALS["F3DMaterialProperty.n64_colors_from_dict"]

    for cls, names in {
        TextureProperty: (
            "palette_color_count",
            "is_vanilla_texture",
            "texture_internal_path",
            "custom_palette_name",
            "hd_native_width",
            "hd_native_height",
        ),
        F3DMaterialProperty: (
            "prim_dynamic_entry",
            "prim_dynamic_entry_name",
            "prim_dynamic_entry_category",
            "env_dynamic_entry",
            "env_dynamic_entry_name",
            "env_dynamic_entry_category",
        ),
        F3DPanel: ("ui_dynamic_cosmetic_entry",),
    }.items():
        for name in names:
            if hasattr(cls, name):
                delattr(cls, name)
