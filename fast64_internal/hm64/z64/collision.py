from pathlib import Path
from random import random
import struct

import bpy
import mathutils
from bpy.props import StringProperty
from bpy.types import Operator
from bpy.utils import register_class, unregister_class
from mathutils import Matrix

from ...utility import PluginError, ExportUtils, prop_split, raisePluginError, toAlnum, yUpToZUp
from ...z64.collision.operators import OOT_ExportCollision
from ...z64.collision.panels import OOT_ExportCollisionPanel
from ...z64.collision.properties import OOTCollisionExportSettings
from ...z64.exporter.collision import CollisionHeader
from ...z64.exporter.collision.polygons import CollisionPoly
from ...z64.exporter.collision.surface import SurfaceType
from ...z64.importer.scene_collision import parseSurfaceParams
from ...z64.f3d_writer import getColliderMat
from ...z64.constants import ootEnumSceneID
from ...z64.scene.operators import OOT_SearchSceneEnumOperator
from ...z64.utility import getEnumName
from ...z64.utility import getOOTScale
from ..utility import is_hm64
from .o2r_import import get_hm64_o2r_source
from .o2r_collision_paths import O2R_COLLISION_PATHS, O2R_MQ_COLLISION_PATHS
from .scene import _write_collision


_original_execute = None
_original_draw_props = None
_original_panel_draw = None
_HM64_COLLISION_SCALE = "_hm64_collision_scale"
_HM64_COLLISION_SOURCE_PATH = "_hm64_collision_source_path"


def _scene_collision_path(option):
    path = O2R_COLLISION_PATHS.get(option)
    if path is None:
        raise PluginError("Cannot find scene.")
    return path


def _collision_resource_path(obj, settings) -> Path:
    if not settings.exportPath.strip():
        raise PluginError("Set a collision export path.")
    name = settings.filename.strip() if settings.isCustomFilename else toAlnum(obj.name)
    if not name:
        raise PluginError("Set a collision export name.")
    internal_path = bpy.context.scene.hm64_collision_internal_path.strip().replace("\\", "/").strip("/")
    return Path(bpy.path.abspath(settings.exportPath)) / internal_path / name


def _collision_tail_offset(data: bytes) -> int:
    cursor = 0x40 + 12
    vertex_count = struct.unpack_from("<i", data, cursor)[0]
    cursor += 4 + vertex_count * 6
    polygon_count = struct.unpack_from("<I", data, cursor)[0]
    cursor += 4 + polygon_count * 16
    surface_count = struct.unpack_from("<I", data, cursor)[0]
    return cursor + 4 + surface_count * 8


def _collision_source_tail(obj, settings) -> bytes:
    source_path = obj.get(_HM64_COLLISION_SOURCE_PATH)
    if not source_path:
        internal_path = bpy.context.scene.hm64_collision_internal_path.strip().replace("\\", "/").strip("/")
        name = settings.filename.strip() if settings.isCustomFilename else toAlnum(obj.name)
        source_path = f"{internal_path}/{name}".strip("/")
    data = get_hm64_o2r_source(bpy.context.scene).archive.file(source_path)
    if data is None or len(data) < 0x40 or data[4:8] != b"LOCO":
        raise PluginError("The base O2R does not contain the collision resource used for camera preservation.")
    return data[_collision_tail_offset(data) :]


def export_hm64_collision(obj, settings):
    if obj.ignore_collision:
        raise PluginError("Cannot export an object with Ignore Collision enabled.")
    transform = (
        Matrix.Scale(float(obj.get(_HM64_COLLISION_SCALE, getOOTScale(obj.ootActorScale))), 4) @ yUpToZUp.inverted()
    )
    collision = CollisionHeader.new(
        f"{toAlnum(obj.name)}_collisionHeader",
        toAlnum(obj.name),
        obj,
        transform,
        False,
        False,
    )
    path = _collision_resource_path(obj, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _write_collision(collision)
    path.write_bytes(data[: _collision_tail_offset(data)] + _collision_source_tail(obj, settings))


def _hm64_execute(self, context):
    if not is_hm64():
        return _original_execute(self, context)
    with ExportUtils():
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            obj = context.active_object
            if obj is None or obj.type != "MESH":
                raise PluginError("Select a mesh object to export collision.")
            export_hm64_collision(obj, context.scene.fast64.oot.collisionExportSettings)
            self.report({"INFO"}, "Success!")
            return {"FINISHED"}
        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


def _hm64_draw_props(self, layout):
    if not is_hm64():
        return _original_draw_props(self, layout)
    layout.prop(self, "isCustomFilename", text="Use Custom Name")
    if self.isCustomFilename:
        prop_split(layout, self, "filename", "Name")
    prop_split(layout, bpy.context.scene, "hm64_collision_internal_path", "Internal Path")
    prop_split(layout, self, "exportPath", "Path")


def _o2r_collision_data(settings):
    option = bpy.context.scene.ootSceneImportSettings.option
    archive = get_hm64_o2r_source(bpy.context.scene).archive
    paths = [_scene_collision_path(option)]
    mq_path = O2R_MQ_COLLISION_PATHS.get(option)
    if mq_path is not None:
        paths.append(mq_path)
    path = next((candidate for candidate in paths if archive.has(candidate)), None)
    if path is None:
        path = next((candidate for candidate in paths if archive.file(candidate) is not None), paths[0])
    data = archive.file(path)
    if data is None or len(data) < 0x40 or data[4:8] != b"LOCO":
        raise PluginError("Select an OCLO collision resource in the O2R archive.")
    return data, path


def _import_o2r_collision(settings):
    data, path = _o2r_collision_data(settings)
    cursor = 0x40

    def take(format_string):
        nonlocal cursor
        size = struct.calcsize(format_string)
        values = struct.unpack_from(format_string, data, cursor)
        cursor += size
        return values

    take("<6h")
    vertex_count = take("<i")[0]
    vertices = [take("<3h") for _ in range(vertex_count)]
    poly_count = take("<I")[0]
    polygons = [take("<4H4h") for _ in range(poly_count)]
    surface_count = take("<I")[0]
    surfaces = []
    for data1, data0 in (take("<2I") for _ in range(surface_count)):
        surface = SurfaceType.from_hex(data0, data1)
        surface.floorType = f"0x{(data0 >> 13) & 0x1F:02X}"
        surface.wallType = f"0x{(data0 >> 21) & 0x1F:02X}"
        surface.floorProperty = f"0x{(data0 >> 26) & 0x0F:02X}"
        surface.material = f"0x{data1 & 0x0F:02X}"
        surface.floorEffect = f"0x{(data1 >> 4) & 0x03:02X}"
        surface.conveyorSpeed = f"0x{(data1 >> 18) & 0x07:02X}"
        surfaces.append(surface)
    name = toAlnum(path.rsplit("/", 1)[-1])
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    import_scale = bpy.context.scene.ootBlenderScale * 10
    obj[_HM64_COLLISION_SCALE] = import_scale
    obj[_HM64_COLLISION_SOURCE_PATH] = path
    mesh.from_pydata(
        [yUpToZUp @ (mathutils.Vector(vertex) / import_scale) for vertex in vertices],
        [],
        [[poly[1] & 0x1FFF, poly[2] & 0x1FFF, poly[3] & 0x1FFF] for poly in polygons],
    )
    material_map = {}
    for index, surface in enumerate(surfaces):
        color = mathutils.Color((1, 1, 1))
        color.hsv = (random(), 0.5, 0.5)
        material = getColliderMat(f"oot_collision_mat_{index}", color[:] + (0.5,))
        material.f3d_mat.prim_color = color[:] + (0.5,)
        mesh.materials.append(material)
        material_map[index] = material
    for index, poly in enumerate(polygons):
        surface_index, v0, v1, v2, nx, ny, nz, dist = poly
        collision_poly = CollisionPoly(
            [v0 & 0x1FFF, v1 & 0x1FFF, v2 & 0x1FFF],
            bool(v0 & 0x2000),
            bool(v0 & 0x4000),
            bool(v0 & 0x8000),
            bool(v1 & 0x2000),
            mathutils.Vector((nx / 0x7FFF, ny / 0x7FFF, nz / 0x7FFF)),
            dist,
            False,
        )
        collision_poly.type = surface_index
        parseSurfaceParams(surfaces[surface_index], collision_poly, material_map[surface_index].ootCollisionProperty)
        mesh.polygons[index].material_index = surface_index
    obj.ignore_render = True


class HM64_ImportCollision(Operator):
    bl_idname = "object.hm64_import_collision"
    bl_label = "Import Collision"

    def execute(self, context):
        try:
            settings = context.scene.fast64.oot.collisionExportSettings
            if not context.scene.hm64_use_o2r_import:
                raise PluginError("Collision imports require O2R importing.")
            _import_o2r_collision(settings)
            self.report({"INFO"}, "Success!")
            return {"FINISHED"}
        except Exception as exc:
            raisePluginError(self, exc)
            return {"CANCELLED"}


def _hm64_panel_draw(self, context):
    if not is_hm64():
        return _original_panel_draw(self, context)
    col = self.layout.column()
    col.operator(OOT_ExportCollision.bl_idname)
    settings = context.scene.fast64.oot.collisionExportSettings
    settings.draw_props(col)
    col.separator()
    col.label(text="Collision Import")
    if not context.scene.hm64_use_o2r_import:
        col.box().label(text="Collision imports require O2R importing.", icon="INFO")
        return
    col.operator(HM64_ImportCollision.bl_idname)
    search_box = col.box().row()
    search_box.operator(OOT_SearchSceneEnumOperator.bl_idname, icon="VIEWZOOM", text="").opName = "Import"
    search_box.label(text=getEnumName(ootEnumSceneID, context.scene.ootSceneImportSettings.option))


def register():
    global _original_execute, _original_draw_props, _original_panel_draw
    if _original_execute is not None:
        return
    _original_execute = OOT_ExportCollision.execute
    _original_draw_props = OOTCollisionExportSettings.draw_props
    _original_panel_draw = OOT_ExportCollisionPanel.draw
    OOT_ExportCollision.execute = _hm64_execute
    OOTCollisionExportSettings.draw_props = _hm64_draw_props
    OOT_ExportCollisionPanel.draw = _hm64_panel_draw
    bpy.types.Scene.hm64_collision_internal_path = StringProperty(name="Internal Path", default="scenes/shared/")
    register_class(HM64_ImportCollision)


def unregister():
    global _original_execute, _original_draw_props, _original_panel_draw
    if _original_execute is None:
        return
    OOT_ExportCollision.execute = _original_execute
    OOTCollisionExportSettings.draw_props = _original_draw_props
    OOT_ExportCollisionPanel.draw = _original_panel_draw
    del bpy.types.Scene.hm64_collision_internal_path
    unregister_class(HM64_ImportCollision)
    _original_execute = None
    _original_draw_props = None
    _original_panel_draw = None
