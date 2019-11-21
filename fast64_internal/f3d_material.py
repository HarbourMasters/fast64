import bpy
from bpy.app.handlers import persistent
import math
import mathutils
import sys
from bpy.types import Node, NodeSocket, NodeSocketInterface, ShaderNode, ShaderNodeGroup, Panel
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem
from .f3d_gbi import F3D
from .f3d_enums import *
from .f3d_material_nodes import *
from .sm64_constants import *
from .utility import prop_split
from bpy.utils import register_class, unregister_class

def F3DOrganizeLights(self, context):
	# Flag to prevent infinite recursion on update callback
	if self.f3d_update_flag:
		return
	self.f3d_update_flag = True
	lightList = []
	if self.f3d_light1 is not None: lightList.append(self.f3d_light1)
	if self.f3d_light2 is not None: lightList.append(self.f3d_light2)
	if self.f3d_light3 is not None: lightList.append(self.f3d_light3)
	if self.f3d_light4 is not None: lightList.append(self.f3d_light4)
	if self.f3d_light5 is not None: lightList.append(self.f3d_light5)
	if self.f3d_light5 is not None: lightList.append(self.f3d_light6)
	if self.f3d_light6 is not None: lightList.append(self.f3d_light7)

	self.f3d_light1 = lightList[0] if len(lightList) > 0 else None
	self.f3d_light2 = lightList[1] if len(lightList) > 1 else None
	self.f3d_light3 = lightList[2] if len(lightList) > 2 else None
	self.f3d_light4 = lightList[3] if len(lightList) > 3 else None
	self.f3d_light5 = lightList[4] if len(lightList) > 4 else None
	self.f3d_light6 = lightList[5] if len(lightList) > 5 else None
	self.f3d_light7 = lightList[6] if len(lightList) > 6 else None
	self.f3d_update_flag = False

def combiner_uses(material, checkList, is2Cycle):
	display = False
	nodes = material.node_tree.nodes
	for value in checkList:
		display |= nodes['Case A 1'].inA == value
		if is2Cycle:
			display |= nodes['Case A 2'].inA == value

		display |= nodes['Case B 1'].inB == value
		if is2Cycle:
			display |= nodes['Case B 2'].inB == value

		display |= nodes['Case C 1'].inC == value
		if is2Cycle:
			display |= nodes['Case C 2'].inC == value

		display |= nodes['Case D 1'].inD == value
		if is2Cycle:
			display |= nodes['Case D 2'].inD == value
	

		display |= nodes['Case A Alpha 1'].inA_alpha == value
		if is2Cycle:
			display |= nodes['Case A Alpha 2'].inA_alpha == value

		display |= nodes['Case B Alpha 1'].inB_alpha == value
		if is2Cycle:
			display |= nodes['Case B Alpha 2'].inB_alpha == value

		display |= nodes['Case C Alpha 1'].inC_alpha == value
		if is2Cycle:
			display |= nodes['Case C Alpha 2'].inC_alpha == value

		display |= nodes['Case D Alpha 1'].inD_alpha == value
		if is2Cycle:
			display |= nodes['Case D Alpha 2'].inD_alpha == value

	return display

def all_combiner_uses(material, is2Cycle):
	useDict = {
		'Texture' : combiner_uses(material, 
			['TEXEL0', 'TEXEL0_ALPHA', 'TEXEL1', 'TEXEL1_ALPHA', 
			'COMBINED', 'COMBINED_ALPHA'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Texture 0' : combiner_uses(material, 
			['TEXEL0', 'TEXEL0_ALPHA'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Texture 1' : combiner_uses(material, 
			['TEXEL1', 'TEXEL1_ALPHA'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Primitive' : combiner_uses(material, 
			['PRIMITIVE', 'PRIMITIVE_ALPHA', 'PRIM_LOD_FRAC'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Environment' : combiner_uses(material, 
			['ENVIRONMENT', 'ENV_ALPHA'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Shade' : combiner_uses(material, 
			['SHADE', 'SHADE_ALPHA'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Key' : combiner_uses(material, ['CENTER', 'SCALE'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'LOD Fraction' : combiner_uses(material, ['LOD_FRACTION'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),

		'Convert' : combiner_uses(material, ['K4', 'K5'], 
			material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE'),
	}
	return useDict

def ui_geo_mode(settings, dataHolder, layout):
	inputGroup = layout.column()
	inputGroup.prop(dataHolder, 'menu_geo', 
		text = 'Geometry Mode Settings',
		icon = 'TRIA_DOWN' if dataHolder.menu_geo else 'TRIA_RIGHT')
	if dataHolder.menu_geo:
		inputGroup.prop(settings, 'g_zbuffer', text = 'Z Buffer')
		inputGroup.prop(settings, 'g_shade', text = 'Shading')
		inputGroup.prop(settings, 'g_cull_front', text = 'Cull Front')
		inputGroup.prop(settings, 'g_cull_back', text = 'Cull Back')
		inputGroup.prop(settings, 'g_fog', text = 'Fog')
		if isinstance(dataHolder, bpy.types.Material) and \
			settings.g_fog:
			material = dataHolder
			layout.prop(material, 'set_fog', text = 'Set Fog')
			fogGroup = layout.column()
			fogColorGroup = fogGroup.row().split(factor = 0.5)
			fogColorGroup.label(text = 'Fog Color')
			fogColorGroup.prop(material, 'fog_color', text = '')
			fogPositionGroup = fogGroup.row().split(factor = 0.5)
			fogPositionGroup.label(text = 'Fog Range')
			fogPositionGroup.prop(material, 'fog_position', text = '')
			fogGroup.enabled = material.set_fog
		inputGroup.prop(settings, 'g_lighting', text = 'Lighting')
		inputGroup.prop(settings, 'g_tex_gen', text = 'Texture UV Generate')
		inputGroup.prop(settings, 'g_tex_gen_linear', 
			text = 'Texture UV Generate Linear')
		inputGroup.prop(settings, 'g_shade_smooth', text = 'Smooth Shading')
		if bpy.context.scene.f3d_type == 'F3DEX_GBI_2' or \
			bpy.context.scene.f3d_type == 'F3DEX_GBI':
			inputGroup.prop(settings, 'g_clipping', text = 'Clipping')
	
def ui_upper_mode(settings, dataHolder, layout):
	inputGroup = layout.column()
	inputGroup.prop(dataHolder, 'menu_upper', 
		text = 'Other Mode Upper Settings', 
		icon = 'TRIA_DOWN' if dataHolder.menu_upper else 'TRIA_RIGHT')
	if dataHolder.menu_upper:
		if not bpy.context.scene.isHWv1:
			prop_split(inputGroup, settings, 'g_mdsft_alpha_dither',
				'Alpha Dither')
			prop_split(inputGroup, settings, 'g_mdsft_rgb_dither', 
				'RGB Dither')
		else:
			prop_split(inputGroup, settings, 'g_mdsft_color_dither',
				'Color Dither')
		prop_split(inputGroup, settings, 'g_mdsft_combkey', 'Chroma Key')
		prop_split(inputGroup, settings, 'g_mdsft_textconv', 'Texture Convert')
		prop_split(inputGroup, settings, 'g_mdsft_text_filt', 'Texture Filter')
		#prop_split(inputGroup, settings, 'g_mdsft_textlut', 'Texture LUT')
		prop_split(inputGroup, settings, 'g_mdsft_textlod', 'Texture LOD')
		prop_split(inputGroup, settings, 'g_mdsft_textdetail', 'Texture Detail')
		prop_split(inputGroup, settings, 'g_mdsft_textpersp', 'Texture Perspective Correction')
		prop_split(inputGroup, settings, 'g_mdsft_cycletype', 'Cycle Type')
		
		prop_split(inputGroup, settings, 'g_mdsft_pipeline', 'Pipeline Span Buffer Coherency')

def ui_lower_mode(settings, dataHolder, layout):
	inputGroup = layout.column()
	inputGroup.prop(dataHolder, 'menu_lower', 
		text = 'Other Mode Lower Settings', 
		icon = 'TRIA_DOWN' if dataHolder.menu_lower else 'TRIA_RIGHT')
	if dataHolder.menu_lower:
		prop_split(inputGroup, settings, 'g_mdsft_alpha_compare', 'Alpha Compare')
		prop_split(inputGroup, settings, 'g_mdsft_zsrcsel', 'Z Source Selection')

# UI Assumptions:
# shading = 1
# lighting = 1
# cycle type = 1 cycle
class F3DPanel(bpy.types.Panel):
	bl_label = "F3D Material"
	bl_idname = "F3D_Inspector"
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "material"
	bl_options = {'HIDE_HEADER'} 

	#def hasNecessaryNodes(self, nodes):
	#	result = True
	#	for name, nodeType in caseTemplateDict.items():
	#		result &= (name in nodes)
	#	return result

	def ui_image(self, material, layout, textureProp, name):
		nodes = material.node_tree.nodes
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(textureProp, 'tex_set', text = name)

		prop_input.prop(textureProp, 'menu', text = 'Texture Properties',
			icon = 'TRIA_DOWN' if textureProp.menu else 'TRIA_RIGHT')
		if textureProp.menu:
			prop_input.template_image(textureProp, 'tex', 
				nodes[name].image_user)
			prop_input.enabled = textureProp.tex_set

			#prop_input.box().label(text = "YUV and CI not yet supported.")
			prop_input.prop(textureProp, 'tex_format', text = 'Format')
			if textureProp.tex_format[:2] == 'CI':
				prop_input.prop(textureProp, 'ci_format', text = 'CI Format')
			prop_input.prop(textureProp.S, "clamp", text = 'Clamp S')
			prop_input.prop(textureProp.T, "clamp", text = 'Clamp T')
			prop_input.prop(textureProp.S, "mirror", text = 'Mirror S')
			prop_input.prop(textureProp.T, "mirror", text = 'Mirror T')

			prop_input.prop(textureProp, 'autoprop', 
				text = 'Auto Set Other Properties')

			if not textureProp.autoprop:
				prop_input.prop(textureProp.S, "mask", text = 'Mask S')
				prop_input.prop(textureProp.T, "mask", text = 'Mask T')
				prop_input.prop(textureProp.S, "shift", text = 'Shift S')
				prop_input.prop(textureProp.T, "shift", text = 'Shift T')
				prop_input.prop(textureProp.S, "low", text = 'S Low')
				prop_input.prop(textureProp.T, "low", text = 'T Low')
				prop_input.prop(textureProp.S, "high", text = 'S High')
				prop_input.prop(textureProp.T, "high", text = 'T High')

			tex = textureProp.tex
			if tex is not None and tex.size[0] > 0 and tex.size[1] > 0 and \
				(math.log(tex.size[0], 2) % 1 > 0.000001 or \
				math.log(tex.size[1], 2) % 1 > 0.000001):
				warnBox = layout.box()
				warnBox.label(
					text = 'Warning: Texture dimensions are not power of 2.')
				warnBox.label(text = 'Wrapping only occurs on power of 2 bounds.')	
	
	def ui_prop(self, material, layout, name, setName, setProp):
		nodes = material.node_tree.nodes
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, setName, text = name)
		prop_input.prop(nodes[name].outputs[0], 'default_value', text='')
		prop_input.enabled = setProp
		return inputGroup

	def ui_prop_non_node(self, material, layout, label, name, setName, setProp):
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, setName, text = name)
		prop_input.prop(material, name, text='')
		prop_input.enabled = setProp
		return inputGroup

	def ui_scale(self, material, layout):
		inputGroup = layout.row().split(factor = 0.5)
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.label(text = 'Texture Scale')
		prop_input.prop(material, 'scale_autoprop', text='Auto Set')
		if not material.scale_autoprop:
			prop_input_group = prop_input.row()
			prop_input_group.prop(material, 'tex_scale', text='')
		return inputGroup

	def ui_prim(self, material, layout, setName, setProp):
		nodes = material.node_tree.nodes
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, setName, text = 'Primitive Color')
		prop_input.prop(nodes['Primitive Color'].outputs[0], 'default_value',
			text='')
		prop_input.prop(material, 'prim_lod_frac', 
			text='Prim LOD Fraction')
		prop_input.prop(material, 'prim_lod_min', 
			text='Min LOD Ratio')
		prop_input.enabled = setProp
		return inputGroup

	def ui_chroma(self, material, layout, name, setName, setProp):
		nodes = material.node_tree.nodes
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, setName, text = 'Chroma Key')
		prop_input.prop(nodes['Chroma Key Center'].outputs[0], 
			'default_value', text='Center')
		prop_input.prop(material, 'key_scale', text = 'Scale')
		prop_input.prop(material, 'key_width', text = 'Width')
		if material.key_width[0] > 1 or material.key_width[1] > 1 or \
			material.key_width[2] > 1:
			layout.box().label(text = \
				"NOTE: Keying is disabled for channels with width > 1.") 
		prop_input.enabled = setProp
		return inputGroup
	
	def ui_lights(self, material, layout, name):
		nodes = material.node_tree.nodes
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, 'set_lights', text = name)
		prop_input_name.enabled = material.rdp_settings.g_lighting and \
			material.rdp_settings.g_shade
		if material.rdp_settings.g_lighting:
			prop_input.prop(nodes['Ambient Color'].outputs[0],'default_value', 
				text='Ambient Color')

			prop_input.prop_search(material, 'f3d_light1', 
				bpy.data, 'lights', text = '')
			if material.f3d_light1 is not None:
				prop_input.prop_search(material, 'f3d_light2', 
					bpy.data, 'lights', text = '')
			if material.f3d_light2 is not None:
				prop_input.prop_search(material, 'f3d_light3', 
					bpy.data, 'lights', text = '')
			if material.f3d_light3 is not None:
				prop_input.prop_search(material, 'f3d_light4', 
					bpy.data, 'lights', text = '')
			if material.f3d_light4 is not None:
				prop_input.prop_search(material, 'f3d_light5', 
					bpy.data, 'lights', text = '')
			if material.f3d_light5 is not None:
				prop_input.prop_search(material, 'f3d_light6', 
					bpy.data, 'lights', text = '')
			if material.f3d_light6 is not None:
				prop_input.prop_search(material, 'f3d_light7', 
					bpy.data, 'lights', text = '')
			layout.box().label(text = "Note: Lighting preview is not 100% accurate.")
			layout.box().label(text = "For vertex colors, clear 'Lighting'.")
			prop_input.enabled = material.set_lights and \
				material.rdp_settings.g_lighting and \
				material.rdp_settings.g_shade

		return inputGroup

	def ui_convert(self, material, layout):
		inputGroup = layout.row()
		prop_input_name = inputGroup.column()
		prop_input = inputGroup.column()
		prop_input_name.prop(material, 'set_k0_5', text = 'YUV Convert')
		
		prop_k0 = prop_input.row()
		prop_k0.prop(material, 'k0', text='K0')
		prop_k0.label(text = str(int(material.k0 * 255)))

		prop_k1 = prop_input.row()
		prop_k1.prop(material, 'k1', text='K1')
		prop_k1.label(text = str(int(material.k1 * 255)))

		prop_k2 = prop_input.row()
		prop_k2.prop(material, 'k2', text='K2')
		prop_k2.label(text = str(int(material.k2 * 255)))

		prop_k3 = prop_input.row()
		prop_k3.prop(material, 'k3', text='K3')
		prop_k3.label(text = str(int(material.k3 * 255)))

		prop_k4 = prop_input.row()
		prop_k4.prop(material, 'k4', text='K4')
		prop_k4.label(text = str(int(material.k4 * 255)))

		prop_k5 = prop_input.row()
		prop_k5.prop(material, 'k5', text='K5')
		prop_k5.label(text = str(int(material.k5 * 255)))

		prop_input.enabled = material.set_k0_5
		return inputGroup

	def ui_lower_render_mode(self, material, layout):
		# cycle independent
		inputGroup = layout.column()
		inputGroup.prop(material, 'menu_lower_render', 
			text = 'Other Mode Lower Render Settings', 
			icon = 'TRIA_DOWN' if material.menu_lower_render else 'TRIA_RIGHT')
		if material.menu_lower_render:
			inputGroup.prop(material, 'set_rendermode', 
				text ='Set Render Mode?')

			renderGroup = inputGroup.column()
			prop_split(renderGroup, material.rdp_settings, 'aa_en', 'Antialiasing')
			prop_split(renderGroup, material.rdp_settings, 'z_cmp', 'Z Testing')
			prop_split(renderGroup, material.rdp_settings, 'z_upd', 'Z Writing')
			prop_split(renderGroup, material.rdp_settings, 'im_rd', 'IM_RD (?)')
			prop_split(renderGroup, material.rdp_settings, 'clr_on_cvg', 
				'Clear On Coverage')
			prop_split(renderGroup, material.rdp_settings, 'cvg_dst', 
				'Coverage Destination')
			prop_split(renderGroup, material.rdp_settings, 'zmode', 'Z Mode')
			prop_split(renderGroup, material.rdp_settings, 'cvg_x_alpha', 
				'Multiply Coverage And Alpha')
			prop_split(renderGroup, material.rdp_settings, 'alpha_cvg_sel',
				'Use Coverage For Alpha')
			prop_split(renderGroup, material.rdp_settings, 'force_bl', 'Force Blending')

			# cycle dependent - (P * A + M - B) / (A + B) 
			combinerBox = renderGroup.box()
			combinerBox.label(text='Blender (Color = (P * A + M - B) / (A + B)')
			combinerCol = combinerBox.row()
			rowColor = combinerCol.column()
			rowAlpha = combinerCol.column()
			rowColor.prop(material.rdp_settings, 'blend_p1', text = 'P')
			rowColor.prop(material.rdp_settings, 'blend_m1', text = 'M')
			rowAlpha.prop(material.rdp_settings, 'blend_a1', text = 'A')
			rowAlpha.prop(material.rdp_settings, 'blend_b1', text = 'B')

			if material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE':
				combinerBox2 = renderGroup.box()
				combinerBox2.label(text='Blender Cycle 2')
				combinerCol2 = combinerBox2.row()
				rowColor2 = combinerCol2.column()
				rowAlpha2 = combinerCol2.column()
				rowColor2.prop(material.rdp_settings, 'blend_p2', text = 'P')
				rowColor2.prop(material.rdp_settings, 'blend_m2', text = 'M')
				rowAlpha2.prop(material.rdp_settings, 'blend_a2', text = 'A')
				rowAlpha2.prop(material.rdp_settings, 'blend_b2', text = 'B')

			renderGroup.enabled = material.set_rendermode
		
	def ui_procAnimVec(self, procAnimVec, layout, name, vecType):
		layout.prop(procAnimVec, 'menu', text = name, 
			icon = 'TRIA_DOWN' if procAnimVec.menu else 'TRIA_RIGHT')
		if procAnimVec.menu:
			box = layout.box()
			self.ui_procAnimField(procAnimVec.x, box, vecType[0])
			self.ui_procAnimField(procAnimVec.y, box, vecType[1])
			if len(vecType) > 2:
				self.ui_procAnimField(procAnimVec.z, box, vecType[2])

	def ui_procAnimField(self, procAnimField, layout, name):
		box = layout
		box.prop(procAnimField, 'animate', text = name)
		if procAnimField.animate:
			if name not in 'XYZ':
				split0 = box.row().split(factor = 0.5)
				split0.prop(procAnimField, 'speed')
				split0.prop(procAnimField, 'scrollOffset')
			split1 = box.row().split(factor = 0.5)
			split1.prop(procAnimField, 'amplitude')
			split1.prop(procAnimField, 'frequency')

			layout.row().prop(procAnimField, 'spaceFrequency')

			split2 = box.row().split(factor = 0.5)
			split2.prop(procAnimField, 'offset')
			split2.prop(procAnimField, 'noiseAmplitude')
	
	def ui_procAnim(self, material, layout, useTex0, useTex1):
		layout.prop(material, 'menu_procAnim', 
			text = 'Procedural Animation', 
			icon = 'TRIA_DOWN' if material.menu_procAnim else 'TRIA_RIGHT')
		if material.menu_procAnim:
			procAnimBox = layout.box()
			if useTex0:
				self.ui_procAnimVec(material.UVanim_tex0, procAnimBox, 
				"UV Texture 0", 'UV')
			if useTex1:
				self.ui_procAnimVec(material.UVanim_tex1, procAnimBox, 
				"UV Texture 1", 'UV')
			self.ui_procAnimVec(material.positionAnim, procAnimBox,
				"Position", 'XYZ')
			self.ui_procAnimVec(material.colorAnim, procAnimBox, "Color",
			 	'RGB')

	# texture convert/LUT controlled by texture settings
	# add node support for geo mode settings
	def draw(self, context):
		layout = self.layout

		layout.operator(CreateFast3DMaterial.bl_idname)
		material = context.material
		if material is None:
			pass
		elif not(material.use_nodes and material.is_f3d):
			layout.label(text="This is not a Fast3D material.")
		else:
			layout.box().label(text = 'Note: Do not copy paste materials.')
			layout = layout.box()
			titleCol = layout.column()
			titleCol.label(text = "F3D Material Inspector")

			prop_split(layout, material, 'f3d_preset', 'Preset Material')

			if not material.rdp_settings.g_lighting:
				noticeBox = layout.box()
				noticeBox.label(
					text = 'Note: There must be two vertex color layers.')
				noticeBox.label(
					text = 'They should be called "Col" and "Alpha".')

			combinerBox = layout.box()
			combinerBox.prop(material, 'set_combiner', 
				text = 'Color Combiner (Color = (A - B) * C + D)')
			combinerCol = combinerBox.row()
			combinerCol.enabled = material.set_combiner
			rowColor = combinerCol.column()
			rowAlpha = combinerCol.column()

			rowColor.prop(material.combiner1, 'A')
			rowColor.prop(material.combiner1, 'B')
			rowColor.prop(material.combiner1, 'C')
			rowColor.prop(material.combiner1, 'D')
			rowAlpha.prop(material.combiner1, 'A_alpha')
			rowAlpha.prop(material.combiner1, 'B_alpha')
			rowAlpha.prop(material.combiner1, 'C_alpha')
			rowAlpha.prop(material.combiner1, 'D_alpha')

			if material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE':
				combinerBox2 = layout.box()
				combinerBox2.label(text = 'Color Combiner Cycle 2')
				combinerBox2.enabled = material.set_combiner
				combinerCol2 = combinerBox2.row()
				rowColor2 = combinerCol2.column()
				rowAlpha2 = combinerCol2.column()

				rowColor2.prop(material.combiner2, 'A')
				rowColor2.prop(material.combiner2, 'B')
				rowColor2.prop(material.combiner2, 'C')
				rowColor2.prop(material.combiner2, 'D')
				rowAlpha2.prop(material.combiner2, 'A_alpha')
				rowAlpha2.prop(material.combiner2, 'B_alpha')
				rowAlpha2.prop(material.combiner2, 'C_alpha')
				rowAlpha2.prop(material.combiner2, 'D_alpha')

			layout.box().label(
				text = 'Note: Alpha preview is not 100% accurate.')

			inputCol = layout.column()
			useDict = all_combiner_uses(material, 
				material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE')
			
			if useDict['Texture']:
				self.ui_scale(material, inputCol)

			if useDict['Texture 0']:
				self.ui_image(material, inputCol, material.tex0, 'Texture 0')

			if useDict['Texture 1']:
				self.ui_image(material, inputCol, material.tex1, 'Texture 1')

			if useDict['Texture 0'] and useDict['Texture 1']:
				inputCol.prop(material, 'uv_basis', text = 'UV Basis')
			
			if useDict['Primitive']:
				self.ui_prim(material, inputCol, 'set_prim', material.set_prim)

			if useDict['Environment']:	
				self.ui_prop(material, inputCol, 'Environment Color', 'set_env',
				material.set_env)

			if useDict['Shade']:
				self.ui_lights(material, inputCol, 'Shade Color')

			if useDict['Key']:
				self.ui_chroma(material, inputCol, 'Chroma Key Center',
					'set_key', material.set_key)
			
			if useDict['Convert']:
				self.ui_convert(material, inputCol)
			
			#self.ui_procAnim(material, inputCol, 
			#	useDict['Texture 0'], useDict['Texture 1'])
			
			ui_geo_mode(material.rdp_settings, material, layout)
			ui_upper_mode(material.rdp_settings, material, layout)
			ui_lower_mode(material.rdp_settings, material, layout)
			layout.box().label(text = \
				'WARNING: Render mode settings not reset after drawing.')
			self.ui_lower_render_mode(material, layout)

def update_node_values(self, context):
	if hasattr(context.scene, 'world') and \
		self == context.scene.world.rdp_defaults:
		pass
	elif hasattr(context, 'material') and context.material is not None:
		material = context.material # Handles case of texture property groups
		if not material.is_f3d or material.f3d_update_flag:
			return
		material.f3d_update_flag = True
		update_node_values_of_material(material, context)
		material.f3d_preset = 'Custom'
		material.f3d_update_flag = False
	else:
		pass
		#print('No material in context.')

def update_node_values_directly(material, context):
	if not material.is_f3d or material.f3d_update_flag:
		return
	material.f3d_update_flag = True
	update_node_values_of_material(material, context)
	material.f3d_preset = 'Custom'
	material.f3d_update_flag = False

def update_node_values_of_material(material, context):
	nodes = material.node_tree.nodes

	nodes['Case A 1'].inA = material.combiner1.A
	nodes['Case B 1'].inB = material.combiner1.B
	nodes['Case C 1'].inC = material.combiner1.C
	nodes['Case D 1'].inD = material.combiner1.D
	nodes['Case A Alpha 1'].inA_alpha = material.combiner1.A_alpha
	nodes['Case B Alpha 1'].inB_alpha = material.combiner1.B_alpha
	nodes['Case C Alpha 1'].inC_alpha = material.combiner1.C_alpha
	nodes['Case D Alpha 1'].inD_alpha = material.combiner1.D_alpha
	nodes['Case A 2'].inA = material.combiner2.A
	nodes['Case B 2'].inB = material.combiner2.B
	nodes['Case C 2'].inC = material.combiner2.C
	nodes['Case D 2'].inD = material.combiner2.D
	nodes['Case A Alpha 2'].inA_alpha = material.combiner2.A_alpha
	nodes['Case B Alpha 2'].inB_alpha = material.combiner2.B_alpha
	nodes['Case C Alpha 2'].inC_alpha = material.combiner2.C_alpha
	nodes['Case D Alpha 2'].inD_alpha = material.combiner2.D_alpha

	nodes['Cycle Type'].outputs[0].default_value = 1 if \
		material.rdp_settings.g_mdsft_cycletype == 'G_CYC_2CYCLE' else 0
	nodes['Texture Gen'].outputs[0].default_value = 1 if \
		material.rdp_settings.g_tex_gen else 0
	nodes['Texture Gen Linear'].outputs[0].default_value = 1 if \
		material.rdp_settings.g_tex_gen_linear else 0
	nodes['Shading'].outputs[0].default_value = 0 if \
		not material.rdp_settings.g_shade else 1
	nodes['Lighting'].outputs[0].default_value = 0 if \
		not material.rdp_settings.g_lighting else 1

	nodes['Chroma Key Scale'].outputs[0].default_value = \
		[value for value in material.key_scale] + [1]
	nodes['Primitive LOD Fraction'].outputs[0].default_value = \
		material.prim_lod_frac

	# nodes['YUV Convert K0'].outputs[0].default_value = material.k0
	# nodes['YUV Convert K1'].outputs[0].default_value = material.k1
	# nodes['YUV Convert K2'].outputs[0].default_value = material.k2
	# nodes['YUV Convert K3'].outputs[0].default_value = material.k3
	nodes['YUV Convert K4'].outputs[0].default_value = material.k4
	nodes['YUV Convert K5'].outputs[0].default_value = material.k5

	nodes['Cull Front'].outputs[0].default_value = \
		0 if material.rdp_settings.g_cull_front else 1
	material.show_transparent_back = material.rdp_settings.g_cull_front
	nodes['Cull Back'].outputs[0].default_value = \
		0 if material.rdp_settings.g_cull_back else 1

	
	#nodes['Texture 0'].interpolation = 'Closest' if \
	#	material.rdp_settings.g_mdsft_text_filt == '0' else 'Cubic'
	#nodes['Texture 1'].interpolation = 'Closest' if \
	#	material.rdp_settings.g_mdsft_text_filt == '0' else 'Cubic'
	update_tex_values_manual(material, context)

def update_tex_values_field(self, fieldProperty, texCoordNode, pixelLength,
	isTexGen, uvBasisScale, scale, autoprop):
	clamp = fieldProperty.clamp
	mirror = fieldProperty.mirror

	texCoordNode['Clamp'].outputs[0].default_value = 1 if clamp else 0
	texCoordNode['Mirror'].outputs[0].default_value = 1 if mirror else 0
	texCoordNode['Normalized Half Pixel'].outputs[0].default_value = \
			1 / (2 * pixelLength)

	if autoprop:
		fieldProperty.low = 0
		fieldProperty.high = pixelLength - 1
		fieldProperty.mask =  math.ceil(math.log(pixelLength, 2) - 0.001)
		fieldProperty.shift = 0
	
	L = fieldProperty.low
	H = fieldProperty.high
	mask = fieldProperty.mask
	shift = fieldProperty.shift

	texCoordNode['Normalized L'].outputs[0].default_value = L / pixelLength
	texCoordNode['Normalized H'].outputs[0].default_value = (H + 1)/pixelLength
	texCoordNode['Normalized Mask'].outputs[0].default_value = \
		(2 ** mask) / pixelLength if mask > 0 else 0
	
	texCoordNode['Shift'].outputs[0].default_value = shift
	texCoordNode['Scale'].outputs[0].default_value = scale * uvBasisScale

def update_tex_values_index(self, context, texProperty, texNodeName, 
	uvNodeName, isTexGen, uvBasisScale, scale):
	nodes = self.node_tree.nodes

	tex_x = nodes[uvNodeName].node_tree.nodes[\
		'Create Tex Coord'].node_tree.nodes
	tex_y = nodes[uvNodeName].node_tree.nodes[\
		'Create Tex Coord.001'].node_tree.nodes

	nodes[texNodeName].image = texProperty.tex
	if nodes[texNodeName].image is not None:
		tex_size = nodes[texNodeName].image.size
		if tex_size[0] > 0 and tex_size[1] > 0:
			
			# 1024 == 2^16 / 2^6 (converting 0.16 to 10.5 fixed point)
			nodes[uvNodeName].node_tree.nodes['Image Width Factor'].outputs[0\
				].default_value = 1024 / tex_size[0]
			nodes[uvNodeName].node_tree.nodes['Image Height Factor'].outputs[0\
				].default_value = 1024 / tex_size[1]
			update_tex_values_field(self, texProperty.S, tex_x, tex_size[0],
				self.rdp_settings.g_tex_gen or self.rdp_settings.g_tex_gen_linear,
				uvBasisScale[0], scale[0], texProperty.autoprop)
			update_tex_values_field(self, texProperty.T, tex_y, tex_size[1],
				self.rdp_settings.g_tex_gen or self.rdp_settings.g_tex_gen_linear,
				uvBasisScale[1], scale[1], texProperty.autoprop)

			texFormat = texProperty.tex_format
			ciFormat = texProperty.ci_format
			nodes[texNodeName + ' Is Greyscale'].outputs[0].default_value = \
     		    1 if (texFormat[0] == 'I' or \
				(texFormat[:2] == 'CI' and ciFormat[0] == 'I')) else 0
			nodes[texNodeName + ' Has Alpha'].outputs[0].default_value = \
     		    1 if ('A' in texFormat or \
				(texFormat[:2] == 'CI' and 'A' in ciFormat))else 0

def update_tex_values(self, context):
	if hasattr(context, 'material') and context.material is not None:
		material = context.material # Handles case of texture property groups
		if material.f3d_update_flag:
			return
		material.f3d_update_flag = True
		update_tex_values_manual(material, context)
		material.f3d_update_flag = False

def update_tex_values_manual(self, context):
	isTexGen = self.rdp_settings.g_tex_gen or self.rdp_settings.g_tex_gen_linear

	if self.scale_autoprop:
		tex_size = None
		if self.tex0.tex is not None and self.tex1.tex is not None:
			tex_size = self.tex0.tex.size if self.uv_basis == 'TEXEL0' else \
				self.tex1.tex.size
		elif self.tex0.tex is not None:
			tex_size = self.tex0.tex.size
		elif self.tex1.tex is not None:
			tex_size = self.tex1.tex.size

		if isTexGen and tex_size is not None:
			self.tex_scale = ((tex_size[0] - 1) / 1024, 
				(tex_size[1] - 1) / 1024)
		else:
			self.tex_scale = (1,1)
	
	if self.tex0.tex is not None and self.tex1.tex is not None and\
		self.tex0.tex.size[0] > 0 and self.tex0.tex.size[1] > 0 and\
		self.tex1.tex.size[0] > 0 and self.tex1.tex.size[1] > 0:
		if self.uv_basis == 'TEXEL0':
			uvBasisScale0 = (1,1)
			uvBasisScale1 = (self.tex0.tex.size[0] / self.tex1.tex.size[0],
				self.tex0.tex.size[1] / self.tex1.tex.size[1])
		else:
			uvBasisScale1 = (1,1)
			uvBasisScale0 = (self.tex1.tex.size[0] / self.tex0.tex.size[0],
				self.tex1.tex.size[1] / self.tex0.tex.size[1])
	else:
		uvBasisScale0 = (1,1)
		uvBasisScale1 = (1,1)
			
	update_tex_values_index(self, context, self.tex0, 'Texture 0', 
		'Get UV', isTexGen, uvBasisScale0, self.tex_scale)
	update_tex_values_index(self, context, self.tex1, 'Texture 1', 
		'Get UV.001', isTexGen, uvBasisScale1, self.tex_scale)

def update_preset(self, context):
	if hasattr(context, 'material') and context.material is not None:
		if context.material.f3d_preset != 'Custom':
			materialSettings = materialPresetDict[context.material.f3d_preset]
			materialSettings.applyToMaterial(context.material)

def update_preset_manual(material, context):
	if material.f3d_preset != 'Custom':
		materialSettings = materialPresetDict[material.f3d_preset]
		materialSettings.applyToMaterial(material)

def createF3DMat(obj):
	material = bpy.data.materials.new('sm64_material')
	obj.data.materials.append(material)

	material.is_f3d = True

	material.use_nodes = True
	material.blend_method = 'BLEND'
	material.show_transparent_back = False

	# Remove default shader 
	node_tree = material.node_tree
	nodes = material.node_tree.nodes
	links = material.node_tree.links
	nodes.remove(nodes.get('Principled BSDF'))
	material_output = nodes.get('Material Output')

	nodePos = [600, 0]
	caseNodeDict1 = addNodeListAtWithZeroAddNode(node_tree, 
		caseTemplateDict, *nodePos, 1)
	
	nodePos = [600, -1600]
	caseNodeDict2 = addNodeListAtWithZeroAddNode(node_tree, 
		caseTemplateDict, *nodePos, 2)

	nodePos = [0, 0]
	nodeDict = addNodeListAt(node_tree, {
		'Combined Color': 'ShaderNodeTexImage',
		'Texture 0': 'ShaderNodeTexImage',
		'Texture 1': 'ShaderNodeTexImage',
		'Primitive Color': 'ShaderNodeRGB',
		#'Shade Color': 'ShaderNodeBsdfDiffuse',
		'Environment Color': 'ShaderNodeRGB',
		'Chroma Key Center': 'ShaderNodeRGB',
		'Chroma Key Scale': 'ShaderNodeRGB',
		#'Primitive Alpha': 'ShaderNodeValue',
		#'Shade Alpha': 'ShaderNodeValue',
		#'Environment Alpha' : 'ShaderNodeValue', 
		'LOD Fraction' : 'ShaderNodeValue', 
		'Primitive LOD Fraction' : 'ShaderNodeValue', 
		'Noise' : 'ShaderNodeTexNoise', 
		'YUV Convert K4' : 'ShaderNodeValue', 
		'YUV Convert K5' : 'ShaderNodeValue', 
		'1' : 'ShaderNodeValue', 
		'0' : 'ShaderNodeValue', 
		}, *nodePos)

	# create uv nodes
	# Must be done before texture format mixes, which overwrite nodeDict

	# Note: Because of modulo operations on UVs, aliasing occurs
	# due to mipmapping when 'Linear' filtering is used. 
	# When using 'Cubic', clamping doesn't work correctly either.
	# Thus 'Closest' is used instead.
	nodes['Texture 0'].interpolation = 'Closest'
	nodes['Texture 1'].interpolation = 'Closest'
	
	texGenNode, x, y = addNodeAt(node_tree, 'ShaderNodeValue', 
		'Texture Gen', -500, -200)
	texGenLinearNode, x, y = addNodeAt(node_tree, 'ShaderNodeValue', 
		'Texture Gen Linear', -500, -300)
	uvNode0 = createUVNode(node_tree, [-300, -200], 
		texGenNode, texGenLinearNode)
	uvNode1 = createUVNode(node_tree, [-300,-400], 
		texGenNode, texGenLinearNode)
	links.new(nodeDict['Texture 0'].inputs[0], uvNode0.outputs[0])
	links.new(nodeDict['Texture 1'].inputs[0], uvNode1.outputs[0])
	
	# Add texture format mixes
	y = createTexFormatNodes(node_tree, [300, 0], 0, nodeDict)
	createTexFormatNodes(node_tree, [300, y], 1, nodeDict)
	
	# create shade node
	lightingNode, x, y = addNodeAt(node_tree, 'ShaderNodeValue', 
		'Lighting', -900, 0)
	shadingNode, x, y = addNodeAt(node_tree, 'ShaderNodeValue', 
		'Shading', -900, y)
	ambientNode, x, y = addNodeAt(node_tree, 'ShaderNodeRGB', 
		'Ambient Color', -900, y)
	nodeDict['Shade Color'] = createShadeNode(node_tree, [-900, y], 
		shadingNode, lightingNode, ambientNode)

	# Create combiner nodes
	groupNode = createNodeFinal(node_tree, caseNodeDict1, nodeDict, 
		['Combined Color', 'Shade Color'], ['Environment Color', 'Primitive Color'], 1)
	groupNode.location = [1200,0]

	groupNode2 = createNodeFinal(node_tree, caseNodeDict2, nodeDict, 
		['Combined Color', 'Shade Color'], ['Environment Color', 'Primitive Color'], 2)
	groupNode2.location = [1200, -800]

	links.new(groupNode2.inputs[8], groupNode.outputs[0])
	links.new(groupNode2.inputs[9], groupNode.outputs[1])

	mixCycleNodeRGB, x, y = \
		addNodeAt(node_tree, 'ShaderNodeMixRGB', 'Cycle Mix RGB', 1500, -600)
	mixCycleNodeAlpha, x, y = \
		addNodeAt(node_tree, 'ShaderNodeMixRGB', 'Cycle Mix Alpha', 1500, -900)
	cycleTypeNode, x, y = \
		addNodeAt(node_tree, 'ShaderNodeValue', 'Cycle Type', 1500, -1200)
	
	links.new(mixCycleNodeRGB.inputs[1], groupNode.outputs[0])
	links.new(mixCycleNodeRGB.inputs[2], groupNode2.outputs[0])
	links.new(mixCycleNodeAlpha.inputs[1], groupNode.outputs[1])
	links.new(mixCycleNodeAlpha.inputs[2], groupNode2.outputs[1])
	links.new(mixCycleNodeRGB.inputs[0], cycleTypeNode.outputs[0])
	links.new(mixCycleNodeAlpha.inputs[0], cycleTypeNode.outputs[0])

	cullFront, x, y = \
		addNodeAt(node_tree, 'ShaderNodeValue', 'Cull Front', 1800, -600)
	cullBack, x, y = \
		addNodeAt(node_tree, 'ShaderNodeValue', 'Cull Back', 1800, -800)
	backFacing, x, y = \
		addNodeAt(node_tree, 'ShaderNodeNewGeometry', 'Is Backfacing', 
		1800, -1000)
	
	multCullFront,x,y = \
		addNodeAt(node_tree, 'ShaderNodeMath','Multiply Cull Front', 2100, -600)
	multCullFront.operation = 'MULTIPLY'
	multCullBack,x,y = \
		addNodeAt(node_tree, 'ShaderNodeMath','Multiply Cull Back', 2100, -800)
	multCullBack.operation = 'MULTIPLY'

	finalCullAlpha,x,y = \
		addNodeAt(node_tree, 'ShaderNodeMixRGB','Cull Alpha', 2400, -600)

	links.new(multCullFront.inputs[0], cullFront.outputs[0])
	links.new(multCullBack.inputs[0], cullBack.outputs[0])
	links.new(multCullFront.inputs[1], mixCycleNodeAlpha.outputs[0])
	links.new(multCullBack.inputs[1], mixCycleNodeAlpha.outputs[0])
	links.new(finalCullAlpha.inputs[0], backFacing.outputs[6])
	links.new(finalCullAlpha.inputs[1], multCullFront.outputs[0])
	links.new(finalCullAlpha.inputs[2], multCullBack.outputs[0])	

	# Create mix shader to allow for alpha blending
	# we cannot input alpha directly to material output, but we can mix between
	# our final color and a completely transparent material based on alpha

	material_output.location = [2100,0]
	mixShaderNode = nodes.new('ShaderNodeMixShader')
	mixShaderNode.location = [1800, 0]
	clearNode = nodes.new('ShaderNodeEeveeSpecular')
	clearNode.location = [1500, 0]
	clearNode.inputs[4].default_value = 1 # transparency
	links.new(mixShaderNode.inputs[2], mixCycleNodeRGB.outputs[0])
	links.new(mixShaderNode.inputs[0], finalCullAlpha.outputs[0])
	links.new(mixShaderNode.inputs[1], clearNode.outputs[0])

	# link new node output to material_output input
	links.new(material_output.inputs[0], mixShaderNode.outputs[0])

	#update_node_values_directly(material, bpy.context)
	#update_tex_values(material, bpy.context)

	# This won't update because material is not in context
	material.f3d_preset = 'Shaded Texture'
	# That's why we force update
	update_preset_manual(material, bpy.context)
	#materialPresetDict['Shaded Texture'].applyToMaterial(material)

	return material

class CreateFast3DMaterial(bpy.types.Operator):
	# set bl_ properties
	bl_idname = 'object.create_f3d_mat'
	bl_label = "Create Fast3D Material"
	bl_options = {'REGISTER', 'UNDO', 'PRESET'}

	# Called on demand (i.e. button press, menu item)
	# Can also be called from operator search menu (Spacebar)
	def execute(self, context):
		obj = bpy.context.view_layer.objects.active
		if obj is None:
			self.report({'ERROR'}, 'No active object selected.')
		else:
			createF3DMat(obj)
			self.report({'INFO'}, 'Created new Fast3D material.')
		return {'FINISHED'} # must return a set

class F3DMaterialSettings:
	def __init__(self):
		self.color_combiner = tuple(S_SHADED_TEX + S_SHADED_TEX)
		self.set_texture0 = True
		self.set_texture1 = True
		self.set_prim = True
		self.set_lights = True
		self.set_env = True
		self.set_key = True
		self.set_k0_5 = True
		self.set_combiner = True
		self.set_rendermode = False
		self.scale_autoprop = True

		# geometry mode
		self.g_zbuffer = True
		self.g_shade = True
		self.g_cull_front = False
		self.g_cull_back = True
		self.g_fog = False
		self.g_lighting = True
		self.g_tex_gen = False
		self.g_tex_gen_linear = False
		self.g_shade_smooth = True
		# f3dlx2 only
		self.g_clipping = False

		# upper half mode
		self.g_mdsft_alpha_dither = 'G_AD_NOISE'
		self.g_mdsft_rgb_dither = 'G_CD_MAGICSQ'
		self.g_mdsft_combkey = 'G_CK_NONE'
		self.g_mdsft_textconv = 'G_TC_FILT'
		self.g_mdsft_text_filt = 'G_TF_BILERP'
		self.g_mdsft_textlut = 'G_TT_NONE'
		self.g_mdsft_textlod = 'G_TL_TILE'
		self.g_mdsft_textdetail = 'G_TD_CLAMP'
		self.g_mdsft_textpersp = 'G_TP_PERSP'
		self.g_mdsft_cycletype = 'G_CYC_1CYCLE'
		# v1 only
		self.g_mdsft_color_dither = 'G_CD_ENABLE'
		self.g_mdsft_pipeline = 'G_PM_1PRIMITIVE'

		# lower half mode
		self.g_mdsft_alpha_compare = 'G_AC_NONE'
		self.g_mdsft_zsrcsel = 'G_ZS_PIXEL'

		# cycle independent
		self.aa_en = False
		self.z_cmp = False
		self.z_upd = False
		self.im_rd = False
		self.clr_on_cvg = False
		self.aa_en = False
		self.cvg_dst = 'CVG_DST_CLAMP'
		self.zmode = 'ZMODE_OPA'
		self.cvg_x_alpha = False
		self.alpha_cvg_sel = False
		self.force_bl = False

		# cycle dependent - (P * A + M - B) / (A + B)
		self.blend_p1 = None
		self.blend_p2 = None
		self.blend_m1 = None
		self.blend_m2 = None
		self.blend_a1 = None
		self.blend_a2 = None
		self.blend_b1 = None
		self.blend_b2 = None

	def loadFromMaterial(self, material):
		if not material.is_f3d:
			print(material.name + ' is not an f3d material.')
			return

		self.color_combiner = (
			material.combiner1.A,
			material.combiner1.B,
			material.combiner1.C,
			material.combiner1.D,
			material.combiner1.A_alpha,
			material.combiner1.B_alpha,
			material.combiner1.C_alpha,
			material.combiner1.D_alpha,
			material.combiner2.A,
			material.combiner2.B,
			material.combiner2.C,
			material.combiner2.D,
			material.combiner1.A_alpha,
			material.combiner1.B_alpha,
			material.combiner1.C_alpha,
			material.combiner1.D_alpha,
		)
		self.set_texture0 = material.tex0.tex_set
		self.set_texture1 = material.tex1.tex_set
		self.set_prim = material.set_prim
		self.set_lights = material.set_lights
		self.set_env = material.set_env
		self.set_key = material.set_key
		self.set_k0_5 = material.set_k0_5
		self.set_combiner = material.set_combiner
		self.set_rendermode = material.set_rendermode
		self.scale_autoprop = material.scale_autoprop

		# geometry mode
		self.g_zbuffer = material.rdp_settings.g_zbuffer
		self.g_shade = material.rdp_settings.g_shade
		self.g_cull_front = material.rdp_settings.g_cull_front
		self.g_cull_back = material.rdp_settings.g_cull_back
		self.g_fog = material.rdp_settings.g_fog
		self.g_lighting = material.rdp_settings.g_lighting
		self.g_tex_gen = material.rdp_settings.g_tex_gen
		self.g_tex_gen_linear = material.rdp_settings.g_tex_gen_linear
		self.g_shade_smooth = material.rdp_settings.g_shade_smooth
		# f3dlx2 only
		self.g_clipping = material.rdp_settings.g_clipping

		# upper half mode
		self.g_mdsft_alpha_dither = material.rdp_settings.g_mdsft_alpha_dither
		self.g_mdsft_rgb_dither = material.rdp_settings.g_mdsft_rgb_dither
		self.g_mdsft_combkey = material.rdp_settings.g_mdsft_combkey
		self.g_mdsft_textconv = material.rdp_settings.g_mdsft_textconv
		self.g_mdsft_text_filt = material.rdp_settings.g_mdsft_text_filt
		self.g_mdsft_textlut = material.rdp_settings.g_mdsft_textlut
		self.g_mdsft_textlod = material.rdp_settings.g_mdsft_textlod
		self.g_mdsft_textdetail = material.rdp_settings.g_mdsft_textdetail
		self.g_mdsft_textpersp = material.rdp_settings.g_mdsft_textpersp
		self.g_mdsft_cycletype = material.rdp_settings.g_mdsft_cycletype
		# v1 only
		self.g_mdsft_color_dither = material.rdp_settings.g_mdsft_color_dither
		self.g_mdsft_pipeline = material.rdp_settings.g_mdsft_pipeline

		# lower half mode
		self.g_mdsft_alpha_compare = material.rdp_settings.g_mdsft_alpha_compare
		self.g_mdsft_zsrcsel = material.rdp_settings.g_mdsft_zsrcsel

		# cycle independent
		self.aa_en = material.rdp_settings.aa_en
		self.z_cmp = material.rdp_settings.z_cmp
		self.z_upd = material.rdp_settings.z_upd
		self.im_rd = material.rdp_settings.im_rd
		self.clr_on_cvg = material.rdp_settings.clr_on_cvg
		self.aa_en = material.rdp_settings.aa_en
		self.cvg_dst = material.rdp_settings.cvg_dst
		self.zmode = material.rdp_settings.zmode
		self.cvg_x_alpha = material.rdp_settings.cvg_x_alpha
		self.alpha_cvg_sel = material.rdp_settings.alpha_cvg_sel
		self.force_bl = material.rdp_settings.force_bl

		# cycle dependent - (P * A + M - B) / (A + B)
		self.blend_p1 = material.rdp_settings.blend_p1
		self.blend_p2 = material.rdp_settings.blend_p2
		self.blend_m1 = material.rdp_settings.blend_m1
		self.blend_m2 = material.rdp_settings.blend_m2
		self.blend_a1 = material.rdp_settings.blend_a1
		self.blend_a2 = material.rdp_settings.blend_a2
		self.blend_b1 = material.rdp_settings.blend_b1
		self.blend_b2 = material.rdp_settings.blend_b2
	
	def applyToMaterial(self, material):
		if not material.is_f3d:
			print(material.name + ' is not an f3d material.')
			return
		
		material.f3d_update_flag = True
		material.combiner1.A = self.color_combiner[0]
		material.combiner1.B = self.color_combiner[1]
		material.combiner1.C = self.color_combiner[2]
		material.combiner1.D = self.color_combiner[3]
		material.combiner1.A_alpha = self.color_combiner[4]
		material.combiner1.B_alpha = self.color_combiner[5]
		material.combiner1.C_alpha = self.color_combiner[6]
		material.combiner1.D_alpha = self.color_combiner[7]
		material.combiner2.A = self.color_combiner[8]
		material.combiner2.B = self.color_combiner[9]
		material.combiner2.C = self.color_combiner[10]
		material.combiner2.D = self.color_combiner[11]
		material.combiner1.A_alpha = self.color_combiner[12]
		material.combiner1.B_alpha = self.color_combiner[13]
		material.combiner1.C_alpha = self.color_combiner[14]
		material.combiner1.D_alpha = self.color_combiner[15]

		material.tex0.tex_set = self.set_texture0
		material.tex1.tex_set = self.set_texture1
		material.set_prim = self.set_prim
		material.set_lights = self.set_lights
		material.set_env = self.set_env
		material.set_key = self.set_key
		material.set_k0_5 = self.set_k0_5
		material.set_combiner = self.set_combiner
		material.set_rendermode = self.set_rendermode
		material.scale_autoprop = self.scale_autoprop

		# geometry mode
		material.rdp_settings.g_zbuffer = self.g_zbuffer
		material.rdp_settings.g_shade = self.g_shade
		material.rdp_settings.g_cull_front = self.g_cull_front
		material.rdp_settings.g_cull_back = self.g_cull_back
		material.rdp_settings.g_fog = self.g_fog
		material.rdp_settings.g_lighting = self.g_lighting
		material.rdp_settings.g_tex_gen = self.g_tex_gen
		material.rdp_settings.g_tex_gen_linear = self.g_tex_gen_linear
		material.rdp_settings.g_shade_smooth = self.g_shade_smooth
		# f3dlx2 only
		material.rdp_settings.g_clipping = self.g_clipping

		# upper half mode
		material.rdp_settings.g_mdsft_alpha_dither = self.g_mdsft_alpha_dither
		material.rdp_settings.g_mdsft_rgb_dither = self.g_mdsft_rgb_dither
		material.rdp_settings.g_mdsft_combkey = self.g_mdsft_combkey
		material.rdp_settings.g_mdsft_textconv = self.g_mdsft_textconv
		material.rdp_settings.g_mdsft_text_filt = self.g_mdsft_text_filt
		material.rdp_settings.g_mdsft_textlut = self.g_mdsft_textlut
		material.rdp_settings.g_mdsft_textlod = self.g_mdsft_textlod
		material.rdp_settings.g_mdsft_textdetail = self.g_mdsft_textdetail
		material.rdp_settings.g_mdsft_textpersp = self.g_mdsft_textpersp
		material.rdp_settings.g_mdsft_cycletype = self.g_mdsft_cycletype
		# v1 only
		material.rdp_settings.g_mdsft_color_dither = self.g_mdsft_color_dither
		material.rdp_settings.g_mdsft_pipeline = self.g_mdsft_pipeline

		# lower half mode
		material.rdp_settings.g_mdsft_alpha_compare = self.g_mdsft_alpha_compare
		material.rdp_settings.g_mdsft_zsrcsel = self.g_mdsft_zsrcsel

		# cycle independent
		if self.set_rendermode:
			material.rdp_settings.aa_en = self.aa_en
			material.rdp_settings.z_cmp = self.z_cmp
			material.rdp_settings.z_upd = self.z_upd
			material.rdp_settings.im_rd = self.im_rd
			material.rdp_settings.clr_on_cvg = self.clr_on_cvg
			material.rdp_settings.aa_en = self.aa_en
			material.rdp_settings.cvg_dst = self.cvg_dst
			material.rdp_settings.zmode = self.zmode
			material.rdp_settings.cvg_x_alpha = self.cvg_x_alpha
			material.rdp_settings.alpha_cvg_sel = self.alpha_cvg_sel
			material.rdp_settings.force_bl = self.force_bl

			# cycle dependent - (P * A + M - B) / (A + B)
			material.rdp_settings.blend_p1 = self.blend_p1
			material.rdp_settings.blend_p2 = self.blend_p2
			material.rdp_settings.blend_m1 = self.blend_m1
			material.rdp_settings.blend_m2 = self.blend_m2
			material.rdp_settings.blend_a1 = self.blend_a1
			material.rdp_settings.blend_a2 = self.blend_a2
			material.rdp_settings.blend_b1 = self.blend_b1
			material.rdp_settings.blend_b2 = self.blend_b2

		update_node_values_of_material(material, bpy.context)
		material.f3d_update_flag = False
		
class TextureFieldProperty(bpy.types.PropertyGroup):
	clamp : bpy.props.BoolProperty(name = 'Clamp', 
		update = update_tex_values)
	mirror : bpy.props.BoolProperty(name = 'Mirror', 
		update = update_tex_values)
	low : bpy.props.FloatProperty(name = 'Low', min = 0, max = 1023.75,
		update = update_tex_values)
	high : bpy.props.FloatProperty(name = 'High', min = 0, max = 1023.75,
		update = update_tex_values)
	mask : bpy.props.IntProperty(min = 0, max = 15,
		update = update_tex_values, default = 5)
	shift : bpy.props.IntProperty(min = -5, max = 10,
		update = update_tex_values)

class TextureProperty(bpy.types.PropertyGroup):
	tex : bpy.props.PointerProperty(
		type = bpy.types.Image, name = 'Texture',
		update = update_tex_values)

	# this is done in material so that greyscale/nonalpha formats will
	# be reflected in preview
	tex_format : bpy.props.EnumProperty(
		name = 'Format', items = enumTexFormat, default = 'RGBA16',
		update = update_tex_values)
	ci_format : bpy.props.EnumProperty(name = 'CI Format', items = enumCIFormat,
		default = 'RGBA16', update = update_tex_values)
	S : bpy.props.PointerProperty(type = TextureFieldProperty)
	T : bpy.props.PointerProperty(type = TextureFieldProperty)

	menu : bpy.props.BoolProperty()
	tex_set : bpy.props.BoolProperty(default = True, update = update_node_values)
	autoprop : bpy.props.BoolProperty(name = 'Autoprop',
		update = update_tex_values, default = True)

class CombinerProperty(bpy.types.PropertyGroup):
	A : bpy.props.EnumProperty(
		name = "A", description = "A", items = combiner_enums['Case A'], 
		default = 'TEXEL0', update = update_node_values)

	B : bpy.props.EnumProperty(
		name = "B", description = "B", items = combiner_enums['Case B'], 
		default = '0', update = update_node_values)

	C : bpy.props.EnumProperty(
		name = "C", description = "C", items = combiner_enums['Case C'], 
		default = 'SHADE', update = update_node_values)

	D : bpy.props.EnumProperty(
		name = "D", description = "D", items = combiner_enums['Case D'], 
		default = '0', update = update_node_values)

	A_alpha : bpy.props.EnumProperty(
		name = "A Alpha", description = "A Alpha", 
		items = combiner_enums['Case A Alpha'], 
		default = '0', update = update_node_values)

	B_alpha : bpy.props.EnumProperty(
		name = "B Alpha", description = "B Alpha", 
		items = combiner_enums['Case B Alpha'], 
		default = '0', update = update_node_values)

	C_alpha : bpy.props.EnumProperty(
		name = "C Alpha", description = "C Alpha", 
		items = combiner_enums['Case C Alpha'], 
		default = '0', update = update_node_values)

	D_alpha : bpy.props.EnumProperty(
		name = "D Alpha", description = "D Alpha", 
		items = combiner_enums['Case D Alpha'], 
		default = 'ENVIRONMENT', update = update_node_values)

class ProceduralAnimProperty(bpy.types.PropertyGroup):
	speed : bpy.props.FloatProperty(name = 'Scroll Speed', default = 1)
	amplitude : bpy.props.FloatProperty(name = 'Amplitude', default = 0)
	frequency : bpy.props.FloatProperty(name = 'Time Frequency', default = 1)
	#spaceFrequency : bpy.props.FloatVectorProperty(name = 'Space Frequency',
	#	size = 3, default = (0,0,0))
	spaceFrequency : bpy.props.FloatProperty(name = 'Space Frequency',
		default = 0)
	offset : bpy.props.FloatProperty(name = 'Sin Offset', default = 0)
	scrollOffset : bpy.props.FloatProperty(name = 'Scroll Offset', default = 0)
	noiseAmplitude : bpy.props.FloatProperty(name = 'Noise', default = 0)
	animate : bpy.props.BoolProperty()

class ProcAnimVectorProperty(bpy.types.PropertyGroup):
	x : bpy.props.PointerProperty(type = ProceduralAnimProperty)
	y : bpy.props.PointerProperty(type = ProceduralAnimProperty)
	z : bpy.props.PointerProperty(type = ProceduralAnimProperty)
	menu : bpy.props.BoolProperty()

class RDPSettings(bpy.types.PropertyGroup):
	g_zbuffer : bpy.props.BoolProperty(name = 'Z Buffer', default = True,
		update = update_node_values)
	g_shade : bpy.props.BoolProperty(name = 'Shading', default = True,
		update = update_node_values)
	#v1/2 difference
	g_cull_front : bpy.props.BoolProperty(name = 'Cull Front',
		update = update_node_values)
	#v1/2 difference
	g_cull_back : bpy.props.BoolProperty(name = 'Cull Back', default = True,
		update = update_node_values)
	g_fog : bpy.props.BoolProperty(name = 'Fog',
		update = update_node_values)
	g_lighting : bpy.props.BoolProperty(name = 'Lighting', default = True,
		update = update_node_values)
	g_tex_gen : bpy.props.BoolProperty(name = 'Texture UV Generate',
		update = update_node_values)
	g_tex_gen_linear : bpy.props.BoolProperty(
		name = 'Texture UV Generate Linear',
		update = update_node_values)
	#v1/2 difference
	g_shade_smooth : bpy.props.BoolProperty(name = 'Smooth Shading', 
		default = True,	update = update_node_values)
	# f3dlx2 only
	g_clipping : bpy.props.BoolProperty(name = 'Clipping',
		update = update_node_values)
	
	# upper half mode
	# v2 only
	g_mdsft_alpha_dither : bpy.props.EnumProperty(
		name = 'Alpha Dither', items = enumAlphaDither, default = 'G_AD_NOISE')
	# v2 only
	g_mdsft_rgb_dither : bpy.props.EnumProperty(
		name = 'RGB Dither', items = enumRGBDither, default = 'G_CD_MAGICSQ')
	g_mdsft_combkey : bpy.props.EnumProperty(
		name = 'Chroma Key', items = enumCombKey, default = 'G_CK_NONE')
	g_mdsft_textconv : bpy.props.EnumProperty(
		name = 'Texture Convert', items = enumTextConv, default = 'G_TC_FILT')
	g_mdsft_text_filt : bpy.props.EnumProperty(
		name = 'Texture Filter', items = enumTextFilt, default = 'G_TF_BILERP',
		update = update_node_values)
	g_mdsft_textlut : bpy.props.EnumProperty(
		name = 'Texture LUT', items = enumTextLUT, default = 'G_TT_NONE')
	g_mdsft_textlod : bpy.props.EnumProperty(
		name = 'Texture LOD', items = enumTextLOD, default = 'G_TL_TILE')
	g_mdsft_textdetail : bpy.props.EnumProperty(
		name = 'Texture Detail', items = enumTextDetail, default = 'G_TD_CLAMP')
	g_mdsft_textpersp : bpy.props.EnumProperty(
		name = 'Texture Perspective Correction', items = enumTextPersp, 
		default = 'G_TP_PERSP')
	g_mdsft_cycletype : bpy.props.EnumProperty(
		name = 'Cycle Type', items = enumCycleType, default = 'G_CYC_1CYCLE',
		update = update_node_values)
	# v1 only
	g_mdsft_color_dither : bpy.props.EnumProperty(
		name = 'Color Dither', items = enumColorDither, default = 'G_CD_ENABLE')
	g_mdsft_pipeline : bpy.props.EnumProperty(
		name = 'Pipeline Span Buffer Coherency', items = enumPipelineMode,
		default = 'G_PM_1PRIMITIVE')
	
	# lower half mode
	g_mdsft_alpha_compare : bpy.props.EnumProperty(
		name = 'Alpha Compare', items = enumAlphaCompare, 
		default = 'G_AC_NONE')
	g_mdsft_zsrcsel : bpy.props.EnumProperty(
		name = 'Z Source Selection', items = enumDepthSource, 
		default = 'G_ZS_PIXEL')

	# cycle independent
	set_rendermode : bpy.props.BoolProperty(default = False)
	aa_en : bpy.props.BoolProperty()
	z_cmp : bpy.props.BoolProperty()
	z_upd : bpy.props.BoolProperty()
	im_rd : bpy.props.BoolProperty()
	clr_on_cvg : bpy.props.BoolProperty()
	cvg_dst : bpy.props.EnumProperty(
		name = 'Coverage Destination', items = enumCoverage)
	zmode : bpy.props.EnumProperty(
		name = 'Z Mode', items = enumZMode)
	cvg_x_alpha : bpy.props.BoolProperty()
	alpha_cvg_sel : bpy.props.BoolProperty()
	force_bl : bpy.props.BoolProperty()

	# cycle dependent - (P * A + M - B) / (A + B) 
	blend_p1 : bpy.props.EnumProperty(
		name = 'Color Source 1', items = enumBlendColor)
	blend_p2 : bpy.props.EnumProperty(
		name = 'Color Source 1', items = enumBlendColor)
	blend_m1 : bpy.props.EnumProperty(
		name = 'Color Source 2', items = enumBlendColor)
	blend_m2 : bpy.props.EnumProperty(
		name = 'Color Source 2', items = enumBlendColor)
	blend_a1 : bpy.props.EnumProperty(
		name = 'Alpha Source', items = enumBlendAlpha)
	blend_a2 : bpy.props.EnumProperty(
		name = 'Alpha Source', items = enumBlendAlpha)
	blend_b1 : bpy.props.EnumProperty(
		name = 'Alpha Mix', items = enumBlendMix)
	blend_b2 : bpy.props.EnumProperty(
		name = 'Alpha Mix', items = enumBlendMix)

class DefaultRDPSettingsPanel(bpy.types.Panel):
	bl_label = "RDP Default Settings"
	bl_idname = "RDP_Default_Inspector"
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_context = "world"
	bl_options = {'HIDE_HEADER'} 

	def draw(self, context):
		world = context.scene.world
		layout = self.layout
		layout.box().label(text = 'RDP Default Settings')
		layout.label(text = "If a material setting is a same as a default " +\
			"setting, then it won't be set.")
		ui_geo_mode(world.rdp_defaults, world, layout)
		ui_upper_mode(world.rdp_defaults, world, layout)
		ui_lower_mode(world.rdp_defaults, world, layout)

### Node Categories ###
# Node categories are a python system for automatically
# extending the Add menu, toolbar panels and search operator.
# For more examples see release/scripts/startup/nodeitems_builtins.py

# all categories in a list
node_categories = [
	# identifier, label, items list
	NodeCategory('CUSTOM', 'Custom', items = [
		NodeItem("GetAlphaFromColor",label="Get Alpha From Color", settings={}),
	]),
	NodeCategory('FAST3D', "Fast3D", items=[
		# the node item can have additional settings,
		# which are applied to new nodes
		# NB: settings values are stored as string expressions,
		# for this reason they should be converted to strings using repr()
		NodeItem("Fast3D_A", label="A", settings={}),
		NodeItem("Fast3D_B", label="B", settings={}),
		NodeItem("Fast3D_C", label="C", settings={}),
		NodeItem("Fast3D_D", label="D", settings={}),
		NodeItem("Fast3D_A_alpha", label="A Alpha", settings={}),
		NodeItem("Fast3D_B_alpha", label="B Alpha", settings={}),
		NodeItem("Fast3D_C_alpha", label="C Alpha", settings={}),
		NodeItem("Fast3D_D_alpha", label="D Alpha", settings={}),
		'''
		NodeItem("Test_NodeType", label="Full", settings={
			"my_string_prop": repr("consectetur adipisicing elit"),
			"my_float_prop": repr(2.0),
		}),
		NodeItem("Fast3D_NodeType", label="Shaded Texture", settings={
			"inA": repr('1'), "inB": repr('8'), "inC": repr('4'), 
			"inD": repr('7'), "inA_alpha": repr('7'), "inB_alpha": repr('7'), 
			"inC_alpha": repr('7'), "inD_alpha": repr('5'), 
		}),
		NodeItem("Fast3DSplitter_NodeType", label="Splitter", settings={
		}),
		'''	
	]),
]

classes = (
	#MyCustomSocket,
	#MyCustomNode,
	#F3DNode,
	#F3DOptionSplitterNode,
	F3DNodeA,
	F3DNodeB,
	F3DNodeC,
	F3DNodeD,
	F3DNodeA_alpha,
	F3DNodeB_alpha,
	F3DNodeC_alpha,
	F3DNodeD_alpha,
	F3DPanel,
	CreateFast3DMaterial,
	GetAlphaFromColor,
	TextureFieldProperty,
	TextureProperty,
	CombinerProperty,
	ProceduralAnimProperty,
	ProcAnimVectorProperty,
	RDPSettings,
	DefaultRDPSettingsPanel
	#F3DLightCollectionProperty,
)

global_time = 0
def set_global_time():
	global global_time
	timestep = 0.033333
	global_time = (global_time + timestep) % sys.maxsize
	for material in bpy.data.materials:
		if material.is_f3d:
			nodes = material.node_tree.nodes
			if 'Global Time' in nodes:
				nodes['Global Time'].outputs[0].default_value =  \
					global_time 
	return timestep

@persistent
def loadTimer(param):
	bpy.app.timers.register(set_global_time)

def register():
	#bpy.app.handlers.load_post.append(loadTimer)
	for cls in classes:
		register_class(cls)

	nodeitems_utils.register_node_categories('CUSTOM_NODES', node_categories)

	bpy.types.Material.f3d_preset = bpy.props.EnumProperty(name = 'F3D Preset',
		items = enumMaterialPresets, default = 'Custom', 
		update = update_preset)

	bpy.types.Scene.update_flag = bpy.props.BoolProperty()
	bpy.types.Scene.f3d_type = bpy.props.EnumProperty(
		name = 'F3D Microcode', items = enumF3D, default = 'F3D')
	bpy.types.Scene.isHWv1 = bpy.props.BoolProperty(name = 'Is Hardware v1?')
	
	# RDP Defaults
	bpy.types.World.rdp_defaults = bpy.props.PointerProperty(
		type = RDPSettings)
	bpy.types.World.menu_geo = bpy.props.BoolProperty()
	bpy.types.World.menu_upper = bpy.props.BoolProperty()
	bpy.types.World.menu_lower = bpy.props.BoolProperty()

	bpy.types.Material.scale_autoprop = bpy.props.BoolProperty(
		name = 'Auto Set Scale', default = True,
		update = update_node_values)
	bpy.types.Material.uv_basis = bpy.props.EnumProperty(
		name = 'UV Basis', default = 'TEXEL0',
		update = update_tex_values, items = enumTexUV)

	# Combiners
	bpy.types.Material.combiner1 = bpy.props.PointerProperty(type = \
		CombinerProperty)
	bpy.types.Material.combiner2 = bpy.props.PointerProperty(type = \
		CombinerProperty)

	# Texture animation
	bpy.types.Material.menu_procAnim = bpy.props.BoolProperty()
	bpy.types.Material.positionAnim = bpy.props.PointerProperty(
		type = ProcAnimVectorProperty)
	bpy.types.Material.UVanim_tex0 = bpy.props.PointerProperty(
		type = ProcAnimVectorProperty)
	bpy.types.Material.UVanim_tex1 = bpy.props.PointerProperty(
		type = ProcAnimVectorProperty)
	bpy.types.Material.colorAnim = bpy.props.PointerProperty(
		type = ProcAnimVectorProperty)

	# material textures
	bpy.types.Material.tex_scale = bpy.props.FloatVectorProperty(
		min = 0, max = 1, size = 2, default = (1,1), step = 1, 
		update = update_tex_values)
	bpy.types.Material.tex0 = bpy.props.PointerProperty(type = TextureProperty)
	bpy.types.Material.tex1 = bpy.props.PointerProperty(type = TextureProperty)

	# Should Set?
	bpy.types.Material.is_f3d = bpy.props.BoolProperty()
	bpy.types.Material.f3d_update_flag = bpy.props.BoolProperty()
	bpy.types.Material.set_prim = bpy.props.BoolProperty(default = True,
		update = update_node_values)
	bpy.types.Material.set_lights = bpy.props.BoolProperty(default = True,
		update = update_node_values)
	bpy.types.Material.set_env = bpy.props.BoolProperty(default = False,
		update = update_node_values)
	bpy.types.Material.set_key = bpy.props.BoolProperty(default = True,
		update = update_node_values)
	bpy.types.Material.set_k0_5 = bpy.props.BoolProperty(default = True,
		update = update_node_values)
	bpy.types.Material.set_combiner = bpy.props.BoolProperty(default = True,
		update = update_node_values)

	# Chroma
	bpy.types.Material.key_scale = bpy.props.FloatVectorProperty(
		name = 'Key Scale', min = 0, max = 1, step = 1,
		update = update_node_values)
	bpy.types.Material.key_width = bpy.props.FloatVectorProperty(
		name = 'Key Width', min = 0, max = 16,
		update = update_node_values)
	
	# Convert
	bpy.types.Material.k0 = bpy.props.FloatProperty(min = -1, max = 1,
		default = 175/255, step = 1, update = update_node_values)
	bpy.types.Material.k1 = bpy.props.FloatProperty(min = -1, max = 1,
		default = -43/255, step = 1, update = update_node_values)
	bpy.types.Material.k2 = bpy.props.FloatProperty(min = -1, max = 1,
		default = -89/255, step = 1, update = update_node_values)	
	bpy.types.Material.k3 = bpy.props.FloatProperty(min = -1, max = 1,
		default = 222/255, step = 1, update = update_node_values)
	bpy.types.Material.k4 = bpy.props.FloatProperty(min = -1, max = 1,
		default = 114/255, step = 1, update = update_node_values)
	bpy.types.Material.k5 = bpy.props.FloatProperty(min = -1, max = 1,
		default = 42/255, step = 1, update = update_node_values)
	
	# Prim
	bpy.types.Material.prim_lod_frac = bpy.props.FloatProperty(
		name = 'Prim LOD Frac', min = 0, max = 1, step = 1,
		update = update_node_values)
	bpy.types.Material.prim_lod_min = bpy.props.FloatProperty(
		name = 'Min LOD Ratio', min = 0, max = 1, step = 1,
		update = update_node_values)

	# lights
	bpy.types.Material.f3d_light1 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light2 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light3 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light4 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light5 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light6 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)
	bpy.types.Material.f3d_light7 = bpy.props.PointerProperty(
		type = bpy.types.Light, update = F3DOrganizeLights)

	# Fog Properties
	bpy.types.Material.fog_color = bpy.props.FloatVectorProperty(
		name = 'Fog Color', subtype='COLOR', size = 4, min = 0, max = 1, default = (0,0,0,1))
	bpy.types.Material.fog_position = bpy.props.IntVectorProperty(
		name = 'Fog Range', size = 2, min = 0, max = 1000, default = (500,1000))
	bpy.types.Material.set_fog = bpy.props.BoolProperty()

	# geometry mode
	bpy.types.Material.menu_geo = bpy.props.BoolProperty()
	bpy.types.Material.menu_upper = bpy.props.BoolProperty()
	bpy.types.Material.menu_lower = bpy.props.BoolProperty()
	bpy.types.Material.menu_lower_render = bpy.props.BoolProperty()
	bpy.types.Material.set_rendermode = bpy.props.BoolProperty(default = False)
	bpy.types.Material.rdp_settings = bpy.props.PointerProperty(
		type = RDPSettings)

def unregister():
	nodeitems_utils.unregister_node_categories('CUSTOM_NODES')
	for cls in reversed(classes):
		unregister_class(cls)

if __name__ == "__main__":
	register()

#from .f3d_material import *

# Presets
sm64_unlit_texture = F3DMaterialSettings()
sm64_unlit_texture.color_combiner = tuple(S_UNLIT_TEX + S_UNLIT_TEX)
sm64_unlit_texture.set_env = False

sm64_shaded_texture = F3DMaterialSettings()
sm64_shaded_texture.color_combiner = tuple(S_SHADED_TEX + S_SHADED_TEX)
sm64_shaded_texture.set_env = False

sm64_shaded_solid = F3DMaterialSettings()
sm64_shaded_solid.color_combiner = tuple(S_SHADED_SOLID + S_SHADED_SOLID)
sm64_shaded_solid.set_env = False

sm64_shaded_texture_cutout = F3DMaterialSettings()
sm64_shaded_texture_cutout.color_combiner = \
	tuple(S_SHADED_TEX_CUTOUT + S_SHADED_TEX_CUTOUT)
sm64_shaded_texture_cutout.set_env = False
sm64_shaded_texture_cutout.g_cull_back = False

sm64_unlit_env_map = F3DMaterialSettings()
sm64_unlit_env_map.color_combiner = tuple(S_UNLIT_TEX + S_UNLIT_TEX)
sm64_unlit_env_map.g_tex_gen = True
sm64_unlit_env_map.set_env = False

sm64_decal = F3DMaterialSettings()
sm64_decal.color_combiner = tuple(S_UNLIT_DECAL_ON_SHADED_SOLID + \
	S_UNLIT_DECAL_ON_SHADED_SOLID)
sm64_decal.set_env = False

sm64_vert_colored_tex = F3DMaterialSettings()
sm64_vert_colored_tex.color_combiner = tuple(S_VERTEX_COLORED_TEX + \
	S_VERTEX_COLORED_TEX)
sm64_vert_colored_tex.g_lighting = False
sm64_vert_colored_tex.set_env = False

sm64_prim_transparent_shade = F3DMaterialSettings()
sm64_prim_transparent_shade.color_combiner = tuple(S_PRIM_TRANSPARENT_SHADE + \
	S_PRIM_TRANSPARENT_SHADE)
sm64_prim_transparent_shade.set_env = False
sm64_prim_transparent_shade.g_cull_back = False

enumMaterialPresets = [
    ('Custom', 'Custom', 'Custom'),
    ('Unlit Texture', 'Unlit Texture', 'Unlit Texture'),
	('Shaded Solid', 'Shaded Solid', 'Shaded Solid'),
	('Decal On Shaded Solid', 'Decal On Shaded Solid', 'Decal On Shaded Solid'),
    ('Shaded Texture', 'Shaded Texture', 'Shaded Texture'),
    ('Shaded Texture Cutout', 'Shaded Texture Cutout', 'Shaded Texture Cutout'),
	('Shaded Texture Transparent', 'Shaded Texture Transparent', 'Shaded Texture Transparent'),
	('Vertex Colored Texture', 'Vertex Colored Texture', 'Vertex Colored Texture'),
    ('Environment Mapped', 'Environment Mapped', 'Environment Mapped'),
]

materialPresetDict = {
    'Unlit Texture' : sm64_unlit_texture,
	'Shaded Solid' : sm64_shaded_solid,
    'Shaded Texture' : sm64_shaded_texture,
    'Shaded Texture Cutout' : sm64_shaded_texture_cutout,
	'Shaded Texture Transparent' : sm64_prim_transparent_shade,
    'Environment Mapped' : sm64_unlit_env_map,
    'Decal On Shaded Solid' : sm64_decal,
    'Vertex Colored Texture' : sm64_vert_colored_tex,
	
}