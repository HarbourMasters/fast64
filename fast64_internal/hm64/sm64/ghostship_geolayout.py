from __future__ import annotations

import os
import struct

import bpy

from ...f3d.f3d_gbi import (
    DPSetTextureImage,
    FModel,
    GfxList,
    SPBranchList,
    SPDisplayList,
    SPSetLights,
    SPVertex,
    get_F3D_GBI,
)
from ...sm64 import sm64_geolayout_classes as geo
from ...sm64.sm64_geolayout_constants import (
    GEO_BILLBOARD,
    GEO_BRANCH,
    GEO_CALL_ASM,
    GEO_CAMERA,
    GEO_END,
    GEO_HELD_OBJECT,
    GEO_LOAD_DL,
    GEO_LOAD_DL_W_OFFSET,
    GEO_NODE_CLOSE,
    GEO_NODE_OPEN,
    GEO_RETURN,
    GEO_ROTATE,
    GEO_SCALE,
    GEO_SET_BG,
    GEO_SET_CAMERA_FRUSTRUM,
    GEO_SET_ORTHO,
    GEO_SET_RENDER_AREA,
    GEO_SET_RENDER_RANGE,
    GEO_SET_Z_BUF,
    GEO_SETUP_OBJ_RENDER,
    GEO_START,
    GEO_START_W_RENDERAREA,
    GEO_START_W_SHADOW,
    GEO_SWITCH,
    GEO_TRANSLATE,
    GEO_TRANSLATE_ROTATE,
)
from ...utility import (
    PluginError,
    convertEulerFloatToShort,
    convertFloatToShort,
    crc64,
    geoNodeRotateOrder,
    prop_split,
    toAlnum,
)

GHOSTSHIP_RESOURCE_TYPE_BLOB = 0x4F424C42


def _ghostship_asset_hash(folder_path: str, name: str | None):
    if name in {None, "", "NULL"}:
        return 0
    asset_path = f"{folder_path}/{name}".replace("\\", "/")
    return int(crc64(asset_path), 16)


def _ghostship_resource_header(resource_type: int, version: int = 0):
    data = bytearray()
    data.extend(struct.pack("<bbbbIIQIQI", 0, 0, 0, 0, resource_type, version, 0xDEADBEEFDEADBEEF, 0, 0, 0))
    while len(data) < 0x40:
        data.extend(struct.pack("<I", 0))
    return data


def _ghostship_blob_resource(payload: bytes):
    data = _ghostship_resource_header(GHOSTSHIP_RESOURCE_TYPE_BLOB, 0)
    data.extend(struct.pack("<I", len(payload)))
    data.extend(payload)
    return data


def _write_u8(data, value):
    data.extend(struct.pack("<B", value & 0xFF))


def _write_s16(data, value):
    data.extend(struct.pack("<h", int(value)))


def _write_u32(data, value):
    data.extend(struct.pack("<I", int(value) & 0xFFFFFFFF))


def _write_u64(data, value):
    data.extend(struct.pack("<Q", int(value) & 0xFFFFFFFFFFFFFFFF))


def _write_f32(data, value):
    data.extend(struct.pack("<f", float(value)))


def _write_vec3s(data, values):
    for value in values:
        _write_s16(data, value)


def _write_vec3f(data, values):
    for value in values:
        _write_f32(data, value)


def _func_u32(func):
    try:
        return int(str(func), 16)
    except ValueError:
        raise PluginError(f'In geolayout node, could not convert function "{func}" to hexadecimal.')


def _is_mario_stand_run_switch(node):
    return isinstance(node, geo.SwitchNode) and _func_u32(node.switchFunc) == 0x80277150


def _dl_asset_hash(node, folder_path: str):
    if not getattr(node, "hasDL", False):
        return 0
    return _ghostship_asset_hash(folder_path, node.get_dl_name())


def _geo_asset_hash(geolayout: geo.Geolayout | None, geo_ref: str | None, folder_path: str):
    name = geo_ref or (geolayout.name if geolayout is not None else None)
    return _ghostship_asset_hash(folder_path, name)


def _transform_node_to_ghostship_binary(node: geo.TransformNode, folder_path: str):
    node.do_export_checks()
    data = bytearray()
    skip_node = node.node is not None and _is_mario_stand_run_switch(node.node)
    if node.node is not None and not skip_node:
        data.extend(_node_to_ghostship_binary(node.node, folder_path))

    if len(node.children) > 0:
        if isinstance(node.node, geo.FunctionNode):
            raise PluginError("An FunctionNode cannot have children.")
        if node.groups and not skip_node:
            _write_u8(data, GEO_NODE_OPEN)
        for child in node.children:
            data.extend(_transform_node_to_ghostship_binary(child, folder_path))
        if node.groups and not skip_node:
            _write_u8(data, GEO_NODE_CLOSE)
    elif isinstance(node.node, geo.SwitchNode):
        raise PluginError("A switch bone must have at least one child bone.")
    return data


def _node_to_ghostship_binary(node, folder_path: str):
    data = bytearray()

    if isinstance(node, geo.JumpNode):
        _write_u8(data, GEO_BRANCH)
        _write_u8(data, 1 if node.storeReturn else 0)
        _write_u64(data, _geo_asset_hash(node.geolayout, node.geoRef, folder_path))
    elif isinstance(node, geo.FunctionNode):
        _write_u8(data, GEO_CALL_ASM)
        _write_s16(data, int(node.func_param))
        _write_u32(data, _func_u32(node.geo_func))
    elif isinstance(node, geo.HeldObjectNode):
        _write_u8(data, GEO_HELD_OBJECT)
        _write_u32(data, _func_u32(node.geo_func))
        _write_u8(data, 0)
        _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
    elif isinstance(node, geo.StartNode):
        _write_u8(data, GEO_START)
    elif isinstance(node, geo.EndNode):
        _write_u8(data, GEO_END)
    elif isinstance(node, geo.SwitchNode):
        _write_u8(data, GEO_SWITCH)
        _write_s16(data, int(node.defaultCase))
        _write_u32(data, _func_u32(node.switchFunc))
    elif isinstance(node, geo.TranslateRotateNode):
        params = ((1 if node.hasDL else 0) << 7) | (node.fieldLayout << 4) | int(node.drawLayer)
        rotation = node.rotate.to_euler(geoNodeRotateOrder)
        _write_u8(data, GEO_TRANSLATE_ROTATE)
        _write_u8(data, params)
        if node.fieldLayout == 0:
            _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
            _write_vec3s(data, [convertEulerFloatToShort(value) for value in rotation])
        elif node.fieldLayout == 1:
            _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
        elif node.fieldLayout == 2:
            _write_vec3s(data, [convertEulerFloatToShort(value) for value in rotation])
        elif node.fieldLayout == 3:
            _write_s16(data, convertEulerFloatToShort(rotation.y))
        if node.hasDL:
            _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.TranslateNode):
        _write_u8(data, GEO_TRANSLATE)
        _write_u8(data, ((1 if node.hasDL else 0) << 7) | int(node.drawLayer))
        _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
        if node.hasDL:
            _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.RotateNode):
        _write_u8(data, GEO_ROTATE)
        _write_u8(data, ((1 if node.hasDL else 0) << 7) | int(node.drawLayer))
        _write_vec3s(data, [convertEulerFloatToShort(value) for value in node.rotate.to_euler(geoNodeRotateOrder)])
        if node.hasDL:
            _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.BillboardNode):
        _write_u8(data, GEO_BILLBOARD)
        _write_u8(data, ((1 if node.hasDL else 0) << 7) | int(node.drawLayer))
        _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
        if node.hasDL:
            _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.DisplayListNode):
        _write_u8(data, GEO_LOAD_DL)
        _write_u8(data, int(node.drawLayer))
        _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.ShadowNode):
        _write_u8(data, GEO_START_W_SHADOW)
        _write_s16(data, node.shadowType)
        _write_s16(data, node.shadowSolidity)
        _write_s16(data, node.shadowScale)
    elif isinstance(node, geo.ScaleNode):
        _write_u8(data, GEO_SCALE)
        _write_u8(data, ((1 if node.hasDL else 0) << 7) | int(node.drawLayer))
        _write_u32(data, int(node.scaleValue * 0x10000))
        if node.hasDL:
            _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.StartRenderAreaNode):
        _write_u8(data, GEO_START_W_RENDERAREA)
        _write_s16(data, convertFloatToShort(node.cullingRadius))
    elif isinstance(node, geo.RenderRangeNode):
        _write_u8(data, GEO_SET_RENDER_RANGE)
        _write_s16(data, convertFloatToShort(node.minDist))
        _write_s16(data, convertFloatToShort(node.maxDist))
    elif isinstance(node, geo.DisplayListWithOffsetNode):
        _write_u8(data, GEO_LOAD_DL_W_OFFSET)
        _write_u8(data, int(node.drawLayer))
        _write_vec3s(data, [convertFloatToShort(value) for value in node.translate])
        _write_u64(data, _dl_asset_hash(node, folder_path))
    elif isinstance(node, geo.ScreenAreaNode):
        position = [160, 120] if node.useDefaults else node.position
        dimensions = [160, 120] if node.useDefaults else node.dimensions
        entry_count = 0xA if node.useDefaults else node.entryMinus2Count
        _write_u8(data, GEO_SET_RENDER_AREA)
        _write_s16(data, entry_count)
        _write_s16(data, position[0])
        _write_s16(data, position[1])
        _write_s16(data, dimensions[0])
        _write_s16(data, dimensions[1])
    elif isinstance(node, geo.OrthoNode):
        _write_u8(data, GEO_SET_ORTHO)
        _write_s16(data, int(node.scale))
    elif isinstance(node, geo.FrustumNode):
        _write_u8(data, GEO_SET_CAMERA_FRUSTRUM)
        _write_u8(data, 1 if node.useFunc else 0)
        _write_s16(data, int(node.fov))
        _write_s16(data, node.near)
        _write_s16(data, node.far)
        if node.useFunc:
            _write_u32(data, 0x8029AA3C)
    elif isinstance(node, geo.ZBufferNode):
        _write_u8(data, GEO_SET_Z_BUF)
        _write_u8(data, 1 if node.enable else 0)
    elif isinstance(node, geo.CameraNode):
        _write_u8(data, GEO_CAMERA)
        _write_s16(data, node.camType)
        _write_vec3f(data, node.position)
        _write_vec3f(data, node.lookAt)
        _write_u32(data, _func_u32(node.geo_func))
    elif isinstance(node, geo.RenderObjNode):
        _write_u8(data, GEO_SETUP_OBJ_RENDER)
    elif isinstance(node, geo.BackgroundNode):
        _write_u8(data, GEO_SET_BG)
        _write_s16(data, node.backgroundValue)
        _write_u32(data, 0 if node.isColor else _func_u32(node.geo_func))
    else:
        raise PluginError(f"Ghostship export does not support {type(node).__name__}.")

    return data


def _geolayout_to_ghostship_otr(geolayout: geo.Geolayout, folder_path: str):
    payload = bytearray()
    for node in geolayout.nodes:
        payload.extend(_transform_node_to_ghostship_binary(node, folder_path))
    _write_u8(payload, GEO_END if geolayout.isStartGeo else GEO_RETURN)
    return _ghostship_blob_resource(payload)


def _geolayout_graph_to_ghostship_otr(geolayout_graph: geo.GeolayoutGraph, folder_path: str):
    geolayout_graph.checkListSorted()
    return {geolayout.name: _geolayout_to_ghostship_otr(geolayout, folder_path) for geolayout in geolayout_graph.sortedList}


def _write_ghostship_resource(export_folder_path: str, name: str, data: bytes):
    with open(os.path.join(export_folder_path, name), "wb") as resource_file:
        resource_file.write(data)


def _ghostship_hash_bytes(asset_path: str):
    hash_val = int(crc64(asset_path.replace("\\", "/")), 16)
    return struct.pack("<II", hash_val >> 32, hash_val & 0xFFFFFFFF)


def _ghostship_native_words_from_big_endian(data: bytes):
    fixed = bytearray()
    for offset in range(0, len(data), 4):
        fixed.extend(data[offset : offset + 4][::-1])
    return fixed


def _ghostship_pointer_command(command, folder_path: str):
    return _ghostship_native_words_from_big_endian(command.toO2R(folder_path))


def _ghostship_gbi_command(command, folder_path: str, f3d):
    if isinstance(command, (SPVertex, SPDisplayList, SPBranchList, DPSetTextureImage)):
        return _ghostship_pointer_command(command, folder_path)

    data = command.to_binary(f3d, {})
    if len(data) >= 8 and data[0] >= 0xE4:
        data = _ghostship_native_words_from_big_endian(data)
    return data


def _ghostship_vtx_list(folder_path: str, vtx_list):
    data = _ghostship_resource_header(0x4F565458, 0)
    data.extend(struct.pack("<I", len(vtx_list.vertices)))
    for vert in vtx_list.vertices:
        data.extend(
            struct.pack(
                "<hhhhhhBBBB",
                vert.position[0],
                vert.position[1],
                vert.position[2],
                vert.packedNormal,
                vert.uv[0],
                vert.uv[1],
                *vert.colorOrNormal,
            )
        )
    return data


def _ghostship_gfx_list_xml(folder_path: str, gfx_list: GfxList):
    data = '<DisplayList Version="0">\n'
    f3d = get_F3D_GBI()
    for command in gfx_list.commands:
        if isinstance(command, SPSetLights):
            continue
        if isinstance(command, (SPVertex, SPDisplayList, SPBranchList, DPSetTextureImage)):
            data += "\t" + command.to_soh_xml(folder_path) + "\n"
        elif hasattr(command, "to_soh_xml"):
            data += "\t" + command.to_soh_xml() + "\n"
        elif hasattr(command, "mode") and hasattr(command, "is_othermodeh"):
            raw = command.to_binary(f3d, {})
            w0 = int.from_bytes(raw[:4], "big")
            cmd = "G_SETOTHERMODE_H" if command.is_othermodeh else "G_SETOTHERMODE_L"
            sft = (w0 >> 8) & 0xFF
            length = (w0 & 0xFF) + 1
            data += f'\t<SetOtherMode Cmd="{cmd}" Sft="{sft}" Length="{length}" {command.mode}="1"/>\n'
        else:
            raise PluginError(f"Ghostship XML export does not support command {command.__class__.__name__}.")
    data += "</DisplayList>\n\n"
    return data.encode("utf-8")


def _ghostship_mario_root_geo(folder_path: str, body_geo_name: str):
    body_hash = _ghostship_asset_hash(folder_path, body_geo_name)
    data = bytearray()
    data.extend(struct.pack("<Bhhh", GEO_START_W_SHADOW, 0x63, 0xB4, 100))
    data.extend(struct.pack("<B", GEO_NODE_OPEN))
    data.extend(struct.pack("<BBI", GEO_SCALE, 0, 0x4000))
    data.extend(struct.pack("<B", GEO_NODE_OPEN))
    data.extend(struct.pack("<BhI", GEO_CALL_ASM, 0, 0x80277D6C))
    data.extend(struct.pack("<BhI", GEO_CALL_ASM, 0, 0x802770A4))
    data.extend(struct.pack("<BhI", GEO_SWITCH, 0, 0x80277150))
    data.extend(struct.pack("<B", GEO_NODE_OPEN))
    data.extend(struct.pack("<BBQ", GEO_BRANCH, 1, body_hash))
    data.extend(struct.pack("<BBQ", GEO_BRANCH, 1, body_hash))
    data.extend(struct.pack("<B", GEO_NODE_CLOSE))
    data.extend(struct.pack("<BhI", GEO_CALL_ASM, 1, 0x80277D6C))
    data.extend(struct.pack("<B", GEO_NODE_CLOSE))
    data.extend(struct.pack("<B", GEO_NODE_CLOSE))
    data.extend(struct.pack("<B", GEO_END))
    return _ghostship_blob_resource(data)


def _save_ghostship_gfx_list(export_folder_path: str, folder_path: str, gfx_list: GfxList):
    if gfx_list is not None and gfx_list.tag.Export:
        _write_ghostship_resource(export_folder_path, gfx_list.name, _ghostship_gfx_list_xml(folder_path, gfx_list))


def _save_ghostship_fmodel_resources(f_model: FModel, export_folder_path: str, folder_path: str):
    for _, f_image in f_model.textures.items():
        if getattr(f_image, "skip_export", False):
            continue
        _write_ghostship_resource(export_folder_path, f_image.name, f_image.toO2R(folder_path))

    for _, (f_material, _) in f_model.materials.items():
        _save_ghostship_gfx_list(export_folder_path, folder_path, f_material.material)
        if f_material.revert is not None:
            _save_ghostship_gfx_list(export_folder_path, folder_path, f_material.revert)

    for _, mesh in f_model.meshes.items():
        _save_ghostship_gfx_list(export_folder_path, folder_path, mesh.draw)
        if mesh.cullVertexList is not None:
            _write_ghostship_resource(
                export_folder_path, mesh.cullVertexList.name, _ghostship_vtx_list(folder_path, mesh.cullVertexList)
            )
        for tri_group in mesh.triangleGroups:
            _write_ghostship_resource(
                export_folder_path, tri_group.vertexList.name, _ghostship_vtx_list(folder_path, tri_group.vertexList)
            )
            for cel_tri_list in tri_group.celTriLists:
                _save_ghostship_gfx_list(export_folder_path, folder_path, cel_tri_list)
            _save_ghostship_gfx_list(export_folder_path, folder_path, tri_group.triList)
        for draw_override in mesh.draw_overrides:
            _save_ghostship_gfx_list(export_folder_path, folder_path, draw_override)


def save_geolayout_ghostship(geo_name, dir_name, geolayout_graph: geo.GeolayoutGraph, f_model: FModel, export_path):
    dir_name = toAlnum(dir_name)
    folder_path = f"actors/{dir_name}/geo"
    export_folder_path = os.path.join(export_path, folder_path)
    os.makedirs(export_folder_path, exist_ok=True)

    is_mario_root = dir_name == "mario" and geo_name == "mario_geo"
    geolayout_graph.startGeolayout.name = "mario_geo_render_body" if is_mario_root else geo_name
    if is_mario_root:
        geolayout_graph.startGeolayout.isStartGeo = False
    _save_ghostship_fmodel_resources(f_model, export_folder_path, folder_path)
    for name, resource_data in _geolayout_graph_to_ghostship_otr(geolayout_graph, folder_path).items():
        _write_ghostship_resource(export_folder_path, name, resource_data)
    if is_mario_root:
        _write_ghostship_resource(export_folder_path, "mario_geo", _ghostship_mario_root_geo(folder_path, "mario_geo_render_body"))

    return export_folder_path


def export_geolayout_armature_ghostship(armature_obj, obj, convert_transform_matrix, export_path, dir_name, geo_name, dl_format):
    from ...sm64.sm64_geolayout_writer import convertArmatureToGeolayout

    geolayout_graph, f_model = convertArmatureToGeolayout(
        armature_obj, obj, convert_transform_matrix, None, dir_name, dl_format, True
    )
    return save_geolayout_ghostship(geo_name, dir_name, geolayout_graph, f_model, export_path)


def export_geolayout_object_ghostship(obj, convert_transform_matrix, export_path, dir_name, geo_name, dl_format):
    from ...sm64.sm64_geolayout_writer import convertObjectToGeolayout

    geolayout_graph, f_model = convertObjectToGeolayout(
        obj, convert_transform_matrix, True, dir_name, None, None, dl_format, True
    )
    return save_geolayout_ghostship(geo_name, dir_name, geolayout_graph, f_model, export_path)


def export_object_from_context(obj, final_transform, props, context, dl_format):
    export_path = bpy.path.abspath(context.scene.geoGhostshipPath)
    asset_folder = context.scene.geoGhostshipAssetFolder or props.obj_name_gfx
    geolayout_name = context.scene.geoGhostshipGeoName or f"{toAlnum(asset_folder)}_geo"
    return export_geolayout_object_ghostship(
        obj,
        final_transform,
        export_path,
        asset_folder,
        geolayout_name,
        dl_format,
    )


def export_armature_from_context(armature_obj, obj, final_transform, props, context, dl_format):
    export_path = bpy.path.abspath(context.scene.geoGhostshipPath)
    asset_folder = context.scene.geoGhostshipAssetFolder or props.obj_name_gfx
    geolayout_name = context.scene.geoGhostshipGeoName or f"{toAlnum(asset_folder)}_geo"
    return export_geolayout_armature_ghostship(
        armature_obj,
        obj,
        final_transform,
        export_path,
        asset_folder,
        geolayout_name,
        dl_format,
    )


def draw_panel(layout, context):
    layout.prop(context.scene, "geoGhostshipPath")
    prop_split(layout, context.scene, "geoGhostshipAssetFolder", "Asset Folder")
    prop_split(layout, context.scene, "geoGhostshipGeoName", "Geolayout Name")


def register_scene_props():
    bpy.types.Scene.geoGhostshipPath = bpy.props.StringProperty(
        name="Ghostship Export Path", default="//ghostship_export", subtype="DIR_PATH"
    )
    bpy.types.Scene.geoGhostshipAssetFolder = bpy.props.StringProperty(name="Asset Folder", default="mario")
    bpy.types.Scene.geoGhostshipGeoName = bpy.props.StringProperty(name="Geolayout Name", default="mario_geo")


def unregister_scene_props():
    del bpy.types.Scene.geoGhostshipPath
    del bpy.types.Scene.geoGhostshipAssetFolder
    del bpy.types.Scene.geoGhostshipGeoName
