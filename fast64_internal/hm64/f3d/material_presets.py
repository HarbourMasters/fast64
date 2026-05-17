"""HM64 material presets: tunic color variants and shaded texture decal for MM."""

shaded_tunic_color_environment_mapped = """
import bpy
f3d_mat = bpy.context.material.f3d_mat

bpy.context.material.f3d_update_flag = True
f3d_mat.combiner1.name = ''
f3d_mat.combiner1.A = 'TEXEL0'
f3d_mat.combiner1.B = '0'
f3d_mat.combiner1.C = 'SHADE'
f3d_mat.combiner1.D = '0'
f3d_mat.combiner1.A_alpha = '0'
f3d_mat.combiner1.B_alpha = '0'
f3d_mat.combiner1.C_alpha = '0'
f3d_mat.combiner1.D_alpha = '1'
f3d_mat.combiner2.name = ''
f3d_mat.combiner2.A = 'ENVIRONMENT'
f3d_mat.combiner2.B = '0'
f3d_mat.combiner2.C = 'COMBINED'
f3d_mat.combiner2.D = '0'
f3d_mat.combiner2.A_alpha = '0'
f3d_mat.combiner2.B_alpha = '0'
f3d_mat.combiner2.C_alpha = '0'
f3d_mat.combiner2.D_alpha = 'COMBINED'
f3d_mat.tex0.name = ''
f3d_mat.tex0.tex_set = True
f3d_mat.tex1.name = ''
f3d_mat.tex1.tex_set = True
f3d_mat.set_prim = True
f3d_mat.set_lights = False
f3d_mat.set_env = False
f3d_mat.set_blend = False
f3d_mat.set_key = True
f3d_mat.set_k0_5 = True
f3d_mat.set_combiner = True
f3d_mat.use_default_lighting = True
f3d_mat.blend_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.prim_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.env_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.key_center = (0.5, 0.5, 0.5, 1.0)
f3d_mat.key_scale = (0.0, 0.0, 0.0)
f3d_mat.key_width = (0.0, 0.0, 0.0)
f3d_mat.k0 = 0.686274528503418
f3d_mat.k1 = -0.16862745583057404
f3d_mat.k2 = -0.3490196168422699
f3d_mat.k3 = 0.8705882430076599
f3d_mat.k4 = 0.4470588266849518
f3d_mat.k5 = 0.16470588743686676
f3d_mat.prim_lod_frac = 0.0
f3d_mat.prim_lod_min = 0.0
f3d_mat.default_light_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.ambient_light_color = (0.5, 0.5, 0.5, 1.0)
f3d_mat.f3d_light1 = None
f3d_mat.f3d_light2 = None
f3d_mat.f3d_light3 = None
f3d_mat.f3d_light4 = None
f3d_mat.f3d_light5 = None
f3d_mat.f3d_light6 = None
f3d_mat.f3d_light7 = None
f3d_mat.set_ao = False
f3d_mat.set_fresnel = False
f3d_mat.set_attroffs_st = False
f3d_mat.set_attroffs_z = False
f3d_mat.fog_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.fog_position = (985, 1000)
f3d_mat.set_fog = False
f3d_mat.use_global_fog = True
f3d_mat.rdp_settings.name = ''
f3d_mat.rdp_settings.g_zbuffer = True
f3d_mat.rdp_settings.g_shade = True
f3d_mat.rdp_settings.g_ambocclusion = False
f3d_mat.rdp_settings.g_attroffset_z_enable = False
f3d_mat.rdp_settings.g_attroffset_st_enable = False
f3d_mat.rdp_settings.g_cull_front = False
f3d_mat.rdp_settings.g_cull_back = True
f3d_mat.rdp_settings.g_packed_normals = False
f3d_mat.rdp_settings.g_lighttoalpha = False
f3d_mat.rdp_settings.g_lighting_specular = False
f3d_mat.rdp_settings.g_fresnel_color = False
f3d_mat.rdp_settings.g_fresnel_alpha = False
f3d_mat.rdp_settings.g_fog = True
f3d_mat.rdp_settings.g_lighting = True
f3d_mat.rdp_settings.g_tex_gen = True
f3d_mat.rdp_settings.g_tex_gen_linear = False
f3d_mat.rdp_settings.g_lod = False
f3d_mat.rdp_settings.g_shade_smooth = True
f3d_mat.rdp_settings.g_clipping = False
f3d_mat.rdp_settings.g_mdsft_alpha_dither = 'G_AD_NOISE'
f3d_mat.rdp_settings.g_mdsft_rgb_dither = 'G_CD_MAGICSQ'
f3d_mat.rdp_settings.g_mdsft_combkey = 'G_CK_NONE'
f3d_mat.rdp_settings.g_mdsft_textconv = 'G_TC_FILT'
f3d_mat.rdp_settings.g_mdsft_text_filt = 'G_TF_BILERP'
f3d_mat.rdp_settings.g_mdsft_textlut = 'G_TT_NONE'
f3d_mat.rdp_settings.g_mdsft_textlod = 'G_TL_TILE'
f3d_mat.rdp_settings.g_mdsft_textdetail = 'G_TD_CLAMP'
f3d_mat.rdp_settings.g_mdsft_textpersp = 'G_TP_PERSP'
f3d_mat.rdp_settings.g_mdsft_cycletype = 'G_CYC_2CYCLE'
f3d_mat.rdp_settings.g_mdsft_color_dither = 'G_CD_ENABLE'
f3d_mat.rdp_settings.g_mdsft_pipeline = 'G_PM_NPRIMITIVE'
f3d_mat.rdp_settings.g_mdsft_alpha_compare = 'G_AC_NONE'
f3d_mat.rdp_settings.g_mdsft_zsrcsel = 'G_ZS_PIXEL'
f3d_mat.rdp_settings.clip_ratio = 1
f3d_mat.rdp_settings.set_rendermode = True
f3d_mat.rdp_settings.rendermode_advanced_enabled = False
f3d_mat.rdp_settings.rendermode_preset_cycle_1 = 'G_RM_FOG_SHADE_A'
f3d_mat.rdp_settings.rendermode_preset_cycle_2 = 'G_RM_AA_ZB_OPA_SURF2'
f3d_mat.draw_layer.name = ''
f3d_mat.draw_layer.sm64 = '1'
f3d_mat.draw_layer.oot = 'Opaque'
bpy.context.material.f3d_update_flag = False
f3d_mat.use_default_lighting = f3d_mat.use_default_lighting # Force nodes update
f3d_mat.presetName = 'Shaded Tunic Color Environment Mapped'
"""

shaded_tunic_color_texture = """
import bpy
f3d_mat = bpy.context.material.f3d_mat

bpy.context.material.f3d_update_flag = True
f3d_mat.combiner1.name = ''
f3d_mat.combiner1.A = 'TEXEL0'
f3d_mat.combiner1.B = '0'
f3d_mat.combiner1.C = 'SHADE'
f3d_mat.combiner1.D = '0'
f3d_mat.combiner1.A_alpha = '0'
f3d_mat.combiner1.B_alpha = '0'
f3d_mat.combiner1.C_alpha = '0'
f3d_mat.combiner1.D_alpha = '1'
f3d_mat.combiner2.name = ''
f3d_mat.combiner2.A = 'ENVIRONMENT'
f3d_mat.combiner2.B = '0'
f3d_mat.combiner2.C = 'COMBINED'
f3d_mat.combiner2.D = '0'
f3d_mat.combiner2.A_alpha = '0'
f3d_mat.combiner2.B_alpha = '0'
f3d_mat.combiner2.C_alpha = '0'
f3d_mat.combiner2.D_alpha = 'COMBINED'
f3d_mat.tex0.name = ''
f3d_mat.tex0.tex_set = True
f3d_mat.tex1.name = ''
f3d_mat.tex1.tex_set = True
f3d_mat.set_prim = True
f3d_mat.set_lights = False
f3d_mat.set_env = False
f3d_mat.set_blend = False
f3d_mat.set_key = True
f3d_mat.set_k0_5 = True
f3d_mat.set_combiner = True
f3d_mat.use_default_lighting = True
f3d_mat.blend_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.prim_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.env_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.key_center = (0.5, 0.5, 0.5, 1.0)
f3d_mat.key_scale = (0.0, 0.0, 0.0)
f3d_mat.key_width = (0.0, 0.0, 0.0)
f3d_mat.k0 = 0.686274528503418
f3d_mat.k1 = -0.16862745583057404
f3d_mat.k2 = -0.3490196168422699
f3d_mat.k3 = 0.8705882430076599
f3d_mat.k4 = 0.4470588266849518
f3d_mat.k5 = 0.16470588743686676
f3d_mat.prim_lod_frac = 0.0
f3d_mat.prim_lod_min = 0.0
f3d_mat.default_light_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.ambient_light_color = (0.5, 0.5, 0.5, 1.0)
f3d_mat.f3d_light1 = None
f3d_mat.f3d_light2 = None
f3d_mat.f3d_light3 = None
f3d_mat.f3d_light4 = None
f3d_mat.f3d_light5 = None
f3d_mat.f3d_light6 = None
f3d_mat.f3d_light7 = None
f3d_mat.set_ao = False
f3d_mat.set_fresnel = False
f3d_mat.set_attroffs_st = False
f3d_mat.set_attroffs_z = False
f3d_mat.fog_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.fog_position = (985, 1000)
f3d_mat.set_fog = False
f3d_mat.use_global_fog = True
f3d_mat.rdp_settings.name = ''
f3d_mat.rdp_settings.g_zbuffer = True
f3d_mat.rdp_settings.g_shade = True
f3d_mat.rdp_settings.g_ambocclusion = False
f3d_mat.rdp_settings.g_attroffset_z_enable = False
f3d_mat.rdp_settings.g_attroffset_st_enable = False
f3d_mat.rdp_settings.g_cull_front = False
f3d_mat.rdp_settings.g_cull_back = True
f3d_mat.rdp_settings.g_packed_normals = False
f3d_mat.rdp_settings.g_lighttoalpha = False
f3d_mat.rdp_settings.g_lighting_specular = False
f3d_mat.rdp_settings.g_fresnel_color = False
f3d_mat.rdp_settings.g_fresnel_alpha = False
f3d_mat.rdp_settings.g_fog = True
f3d_mat.rdp_settings.g_lighting = True
f3d_mat.rdp_settings.g_tex_gen = False
f3d_mat.rdp_settings.g_tex_gen_linear = False
f3d_mat.rdp_settings.g_lod = False
f3d_mat.rdp_settings.g_shade_smooth = True
f3d_mat.rdp_settings.g_clipping = False
f3d_mat.rdp_settings.g_mdsft_alpha_dither = 'G_AD_NOISE'
f3d_mat.rdp_settings.g_mdsft_rgb_dither = 'G_CD_MAGICSQ'
f3d_mat.rdp_settings.g_mdsft_combkey = 'G_CK_NONE'
f3d_mat.rdp_settings.g_mdsft_textconv = 'G_TC_FILT'
f3d_mat.rdp_settings.g_mdsft_text_filt = 'G_TF_BILERP'
f3d_mat.rdp_settings.g_mdsft_textlut = 'G_TT_NONE'
f3d_mat.rdp_settings.g_mdsft_textlod = 'G_TL_TILE'
f3d_mat.rdp_settings.g_mdsft_textdetail = 'G_TD_CLAMP'
f3d_mat.rdp_settings.g_mdsft_textpersp = 'G_TP_PERSP'
f3d_mat.rdp_settings.g_mdsft_cycletype = 'G_CYC_2CYCLE'
f3d_mat.rdp_settings.g_mdsft_color_dither = 'G_CD_ENABLE'
f3d_mat.rdp_settings.g_mdsft_pipeline = 'G_PM_NPRIMITIVE'
f3d_mat.rdp_settings.g_mdsft_alpha_compare = 'G_AC_NONE'
f3d_mat.rdp_settings.g_mdsft_zsrcsel = 'G_ZS_PIXEL'
f3d_mat.rdp_settings.clip_ratio = 1
f3d_mat.rdp_settings.set_rendermode = True
f3d_mat.rdp_settings.rendermode_advanced_enabled = False
f3d_mat.rdp_settings.rendermode_preset_cycle_1 = 'G_RM_FOG_SHADE_A'
f3d_mat.rdp_settings.rendermode_preset_cycle_2 = 'G_RM_AA_ZB_OPA_SURF2'
f3d_mat.draw_layer.name = ''
f3d_mat.draw_layer.sm64 = '1'
f3d_mat.draw_layer.oot = 'Opaque'
bpy.context.material.f3d_update_flag = False
f3d_mat.use_default_lighting = f3d_mat.use_default_lighting # Force nodes update
f3d_mat.presetName = 'Shaded Tunic Color Texture'
"""

shaded_texture_decal = """
import bpy
f3d_mat = bpy.context.material.f3d_mat

bpy.context.material.f3d_update_flag = True
f3d_mat.combiner1.name = ''
f3d_mat.combiner1.A = 'TEXEL0'
f3d_mat.combiner1.B = '0'
f3d_mat.combiner1.C = 'SHADE'
f3d_mat.combiner1.D = '0'
f3d_mat.combiner1.A_alpha = '0'
f3d_mat.combiner1.B_alpha = '0'
f3d_mat.combiner1.C_alpha = '0'
f3d_mat.combiner1.D_alpha = 'TEXEL0'
f3d_mat.combiner2.name = ''
f3d_mat.combiner2.A = 'COMBINED'
f3d_mat.combiner2.B = '0'
f3d_mat.combiner2.C = 'PRIMITIVE'
f3d_mat.combiner2.D = '0'
f3d_mat.combiner2.A_alpha = '0'
f3d_mat.combiner2.B_alpha = '0'
f3d_mat.combiner2.C_alpha = '0'
f3d_mat.combiner2.D_alpha = 'COMBINED'
f3d_mat.tex0.name = ''
f3d_mat.tex0.tex_set = True
f3d_mat.tex1.name = ''
f3d_mat.tex1.tex_set = True
f3d_mat.set_prim = True
f3d_mat.set_lights = False
f3d_mat.set_env = False
f3d_mat.set_blend = False
f3d_mat.set_key = True
f3d_mat.set_k0_5 = True
f3d_mat.set_combiner = True
f3d_mat.use_default_lighting = True
f3d_mat.blend_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.prim_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.env_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.key_center = (0.5, 0.5, 0.5, 1.0)
f3d_mat.key_scale = (0.0, 0.0, 0.0)
f3d_mat.key_width = (0.0, 0.0, 0.0)
f3d_mat.k0 = 0.686274528503418
f3d_mat.k1 = -0.16862745583057404
f3d_mat.k2 = -0.3490196168422699
f3d_mat.k3 = 0.8705882430076599
f3d_mat.k4 = 0.4470588266849518
f3d_mat.k5 = 0.16470588743686676
f3d_mat.prim_lod_frac = 0.0
f3d_mat.prim_lod_min = 0.0
f3d_mat.default_light_color = (1.0, 1.0, 1.0, 1.0)
f3d_mat.ambient_light_color = (0.5, 0.5, 0.5, 1.0)
f3d_mat.f3d_light1 = None
f3d_mat.f3d_light2 = None
f3d_mat.f3d_light3 = None
f3d_mat.f3d_light4 = None
f3d_mat.f3d_light5 = None
f3d_mat.f3d_light6 = None
f3d_mat.f3d_light7 = None
f3d_mat.set_ao = False
f3d_mat.set_fresnel = False
f3d_mat.set_attroffs_st = False
f3d_mat.set_attroffs_z = False
f3d_mat.fog_color = (0.0, 0.0, 0.0, 1.0)
f3d_mat.fog_position = (985, 1000)
f3d_mat.set_fog = False
f3d_mat.use_global_fog = True
f3d_mat.rdp_settings.name = ''
f3d_mat.rdp_settings.g_zbuffer = True
f3d_mat.rdp_settings.g_shade = True
f3d_mat.rdp_settings.g_ambocclusion = False
f3d_mat.rdp_settings.g_attroffset_z_enable = False
f3d_mat.rdp_settings.g_attroffset_st_enable = False
f3d_mat.rdp_settings.g_cull_front = False
f3d_mat.rdp_settings.g_cull_back = True
f3d_mat.rdp_settings.g_packed_normals = False
f3d_mat.rdp_settings.g_lighttoalpha = False
f3d_mat.rdp_settings.g_lighting_specular = False
f3d_mat.rdp_settings.g_fresnel_color = False
f3d_mat.rdp_settings.g_fresnel_alpha = False
f3d_mat.rdp_settings.g_fog = True
f3d_mat.rdp_settings.g_lighting = True
f3d_mat.rdp_settings.g_tex_gen = False
f3d_mat.rdp_settings.g_tex_gen_linear = False
f3d_mat.rdp_settings.g_lod = False
f3d_mat.rdp_settings.g_shade_smooth = True
f3d_mat.rdp_settings.g_clipping = False
f3d_mat.rdp_settings.g_mdsft_alpha_dither = 'G_AD_NOISE'
f3d_mat.rdp_settings.g_mdsft_rgb_dither = 'G_CD_MAGICSQ'
f3d_mat.rdp_settings.g_mdsft_combkey = 'G_CK_NONE'
f3d_mat.rdp_settings.g_mdsft_textconv = 'G_TC_FILT'
f3d_mat.rdp_settings.g_mdsft_text_filt = 'G_TF_BILERP'
f3d_mat.rdp_settings.g_mdsft_textlut = 'G_TT_NONE'
f3d_mat.rdp_settings.g_mdsft_textlod = 'G_TL_TILE'
f3d_mat.rdp_settings.g_mdsft_textdetail = 'G_TD_CLAMP'
f3d_mat.rdp_settings.g_mdsft_textpersp = 'G_TP_PERSP'
f3d_mat.rdp_settings.g_mdsft_cycletype = 'G_CYC_2CYCLE'
f3d_mat.rdp_settings.g_mdsft_color_dither = 'G_CD_ENABLE'
f3d_mat.rdp_settings.g_mdsft_pipeline = 'G_PM_NPRIMITIVE'
f3d_mat.rdp_settings.g_mdsft_alpha_compare = 'G_AC_NONE'
f3d_mat.rdp_settings.g_mdsft_zsrcsel = 'G_ZS_PIXEL'
f3d_mat.rdp_settings.clip_ratio = 1
f3d_mat.rdp_settings.set_rendermode = True
f3d_mat.rdp_settings.rendermode_advanced_enabled = False
f3d_mat.rdp_settings.rendermode_preset_cycle_1 = 'G_RM_FOG_SHADE_A'
f3d_mat.rdp_settings.rendermode_preset_cycle_2 = 'G_RM_AA_ZB_XLU_DECAL2'
f3d_mat.draw_layer.name = ''
f3d_mat.draw_layer.sm64 = '1'
f3d_mat.draw_layer.oot = 'Opaque'
bpy.context.material.f3d_update_flag = False
f3d_mat.use_default_lighting = f3d_mat.use_default_lighting # Force nodes update
f3d_mat.presetName = 'Shaded Texture Decal'
"""



def get_mm_presets(homebrew_and_oot):
    """Build the MM presets dict from homebrew_and_oot, excluding tunic-only variants."""
    return {
        f"mm_{key}": value + 'f3d_mat.presetName = "MM " +  f3d_mat.presetName'
        for key, value in homebrew_and_oot.items()
        if key not in ("shaded_tunic_color_environment_mapped", "shaded_tunic_color_texture")
    }


# Extra presets to add to homebrew_and_oot (available for homebrew and oot)
_hm64_homebrew_extras = {
    "shaded_tunic_color_environment_mapped": shaded_tunic_color_environment_mapped,
    "shaded_tunic_color_texture": shaded_tunic_color_texture,
    "shaded_texture_decal": shaded_texture_decal,
}


def register():
    from ...f3d.f3d_material_presets import register_game_presets, homebrew_and_oot

    homebrew_and_oot.update(_hm64_homebrew_extras)
    mm_presets = get_mm_presets(homebrew_and_oot)
    register_game_presets("mm", mm_presets)


def unregister():
    from ...f3d.f3d_material_presets import unregister_game_presets, homebrew_and_oot

    unregister_game_presets("mm")
    for key in _hm64_homebrew_extras:
        homebrew_and_oot.pop(key, None)
