from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from ...render_settings import on_update_render_settings
from .bk64_constants import (
    ANIM_TEX_SLOT_COUNT,
    BK64_DRAW_LAYER_ENTRY,
    GEO_TYPE_ENV_MAP,
    GEO_TYPE_MIPMAP_TRILINEAR,
    MAX_BONE_ID,
    RENDERMODE_AA_OPAQUE,
)
from .bk64_level_models import bk64_level_layers, bk64_level_names

bk64_collision_type_enum = (
    ("NONE", "No Collision", "Not written into the collision list"),
    ("GROUND", "Ground", "Solid, walked on from above"),
    ("WATER", "Water", "Swimmable"),
    ("WATER2", "Water (alt)", "Swimmable. The game tests it exactly like Water"),
)

bk64_level_enum = tuple(
    (
        name,
        name,
        "Opaque and translucent halves" if len(bk64_level_layers(name)) > 1 else "Opaque half only",
    )
    for name in bk64_level_names()
)

bk64_level_layer_enum = (
    ("BOTH", "Both", "Each half as its own object, so either can be hidden"),
    ("OPA", "Opaque", "The solid half on its own"),
    ("XLU", "Translucent", "The blended half on its own, water and glass"),
)

bk64_sound_type_enum = (
    ("NONE", "None", "No sound tag. Vanilla water and ceilings carry none"),
    ("MAP_DEFAULT", "Map Default", "The map's default footstep, sand on TTC and snow on FP"),
    ("MAP_1", "Map Sound 1", "One of the map's own footsteps, wood on TTC"),
    ("MAP_2", "Map Sound 2", "One of the map's own footsteps, stone on TTC"),
    ("MAP_3", "Map Sound 3", "One of the map's own footsteps"),
    ("MAP_4", "Map Sound 4", "One of the map's own footsteps"),
    ("NORMAL", "Normal", "Default footstep"),
    ("METAL", "Metal", "Metal footstep"),
    ("HARD_GROUND", "Hard Ground", "Hard ground footstep"),
    ("STONE", "Stone", "Stone footstep"),
    ("WOOD", "Wood", "Wood footstep"),
    ("SNOW", "Snow", "Snow footstep"),
    ("LEAVES", "Leaves", "Leaves footstep"),
    ("SWAMP", "Swamp", "Swamp footstep"),
    ("SAND", "Sand", "Sand footstep"),
    ("SLUSH", "Slush", "Slush footstep"),
)

bk64_anim_tex_enum = (
    ("NONE", "Not Animated", "The texture holds still"),
    ("TEX0", "Texture 0", "The first texture cycles through the frames below"),
    ("TEX1", "Texture 1", "The second texture cycles through the frames below"),
)

bk64_geo_type_enum = (
    ("NONE", "None", "Just a bone, carrying its own geometry"),
    ("SELECTOR", "Selector", "Draws one of its child bones at a time, whichever the game asks for"),
    ("REFPOINT", "Reference Point", "Reports where this joint is, for effects to hang off"),
    ("LOD", "Level Of Detail", "Draws what is under it only while the camera is in range"),
    ("SORT", "Sort", "Orders its two child bones by which one is nearer the camera"),
    ("DRAWDIST", "Draw Distance", "Skips what is under it when its box is off screen"),
)

bk64_rigging_enum = (
    ("SPLIT", "Split At Bones", "Every triangle belongs to one bone. The mesh is cut where two of them meet"),
    ("BIND", "Bind Vertices", "The mesh stays whole and each vertex follows its own bone"),
)

bk64_file_format_enum = (
    ("O2R", "O2R", "Resource family for the HarbourMasters ports, packed with torch"),
    ("BIN", "BK Model Binary", "One .bin in the game's own format, for the ROM hacking tools"),
)

bk64_draw_layer_enum = (
    ("OPAQUE", "Opaque", "Solid geometry"),
    ("OPAQUE_NO_AA", "Opaque, No AA", "Solid, without the antialiased edge"),
    ("TRANSLUCENT", "Translucent", "Blended geometry, drawn against what is already there"),
    ("TRANSLUCENT_NO_AA", "Translucent, No AA", "Blended, without the antialiased edge"),
)

bk64_material_draw_layer_enum = (
    ("SCENE", "From Scene", "Whatever the export panel's Draw Layer says"),
    ("INHERIT", "Inherit", "Sets no render mode and draws with whatever the chunk before it left"),
) + bk64_draw_layer_enum


class BK64_Settings:
    """Snapshot of the scene's BK64 properties, for the exporters and importers"""

    def __init__(self, scene: bpy.types.Scene):
        self.warnings: list[str] = []
        self.name = scene.hm64_bk64_resource_name
        self.scale = scene.hm64_bk64_scale
        self.anim_scale = scene.hm64_bk64_anim_scale
        self.force_unlit = scene.hm64_bk64_force_unlit
        self.env_map = scene.hm64_bk64_env_map
        self.mipmap = scene.hm64_bk64_mipmap
        self.draw_layer = scene.hm64_bk64_draw_layer
        self.file_format = scene.hm64_bk64_file_format
        self.rigging = scene.hm64_bk64_rigging
        self.anim_path = scene.hm64_bk64_anim_path
        self.anim_include_rest = scene.hm64_bk64_anim_include_rest
        self.bone_length = scene.hm64_bk64_import_bone_length

    def rendermode_entry(self, draw_layer: str):
        # None for the layer that sets no render mode at all
        return BK64_DRAW_LAYER_ENTRY.get(draw_layer, RENDERMODE_AA_OPAQUE)

    def geo_type_bits(self) -> int:
        bits = 0
        if self.env_map:
            bits |= GEO_TYPE_ENV_MAP
        if self.mipmap:
            # only the resource path builds the tile pyramid, and the bit alone
            # has the game sample tiles TMEM never got
            if self.file_format == "BIN":
                self.warnings.append(
                    "Trilinear Mipmap needs an o2r export, so the .bin went out without it and its "
                    "textures draw from level 0."
                )
            else:
                bits |= GEO_TYPE_MIPMAP_TRILINEAR
        return bits


_BK64_SCENE_PROPS = (
    "hm64_bk64_export_path",
    "hm64_bk64_resource_name",
    "hm64_bk64_scale",
    "hm64_bk64_anim_scale",
    "hm64_bk64_force_unlit",
    "hm64_bk64_env_map",
    "hm64_bk64_mipmap",
    "hm64_bk64_draw_layer",
    "hm64_bk64_file_format",
    "hm64_bk64_rigging",
    "hm64_bk64_import_path",
    "hm64_bk64_import_bone_length",
    "hm64_bk64_level_folder",
    "hm64_bk64_level",
    "hm64_bk64_level_layer",
    "hm64_bk64_anim_path",
    "hm64_bk64_anim_include_rest",
    "hm64_bk64_anim_import_path",
)

_BK64_OBJECT_PROPS = ("hm64_bk64_geo_type_raw",)

_BK64_BONE_PROPS = (
    "hm64_bk64_bone_id",
    "hm64_bk64_bone_order",
    "hm64_bk64_geo_type",
    "hm64_bk64_geo_index",
    "hm64_bk64_lod_near",
    "hm64_bk64_lod_far",
)

_BK64_MATERIAL_PROPS = (
    "hm64_bk64_collision_type",
    "hm64_bk64_sound_type",
    "hm64_bk64_trottable_slope",
    "hm64_bk64_untrottable_slope",
    "hm64_bk64_hazard_1",
    "hm64_bk64_hazard_2",
    "hm64_bk64_hazard_3",
    "hm64_bk64_double_sided",
    "hm64_bk64_non_impeding",
    "hm64_bk64_script_target",
    "hm64_bk64_collision_extra",
    "hm64_bk64_draw_layer",
    "hm64_bk64_collision_raw",
    "hm64_bk64_collision_unk6",
    "hm64_bk64_source_chunk",
    "hm64_bk64_anim_tex",
    "hm64_bk64_anim_slot",
    "hm64_bk64_anim_rate",
)


def bk64_properties_register():
    bpy.types.Scene.hm64_bk64_export_path = StringProperty(
        name="Export Folder",
        subtype="FILE_PATH",
        description="Folder the resource files are written into. Pack it with torch to get an "
        "o2r for the port's mods folder",
    )
    bpy.types.Scene.hm64_bk64_resource_name = StringProperty(
        name="Resource Path",
        default="models/mymodel",
        description="Path the model is stored at inside the archive. Use a vanilla model's own "
        "path to replace it, e.g. assets/model/ASSET_3C0_JINJO_BLUE",
    )
    bpy.types.Scene.hm64_bk64_scale = FloatProperty(
        name="Blender To BK Scale",
        default=100,
        min=0.0001,
        update=on_update_render_settings,
        description="Blender units to BK units. Banjo is about 138 units tall, a Jinjo about 104",
    )
    bpy.types.Scene.hm64_bk64_anim_scale = FloatProperty(
        name="Animation Scale",
        default=10.0,
        min=0.0,
        description="Scales the translation of animations played on this model. Copy it from the "
        "model you are replacing, or the animation moves the wrong distance",
    )
    bpy.types.Scene.hm64_bk64_force_unlit = BoolProperty(
        name="Force Unlit Shade",
        default=True,
        description="Bakes each lit material's lighting into the vertices, since BK's model path "
        "loads no lights and a lit material would otherwise render black",
    )
    bpy.types.Scene.hm64_bk64_env_map = BoolProperty(
        name="Reflective (Env Map)",
        default=False,
        description="Sets up the reflection matrix that environment mapping needs",
    )
    bpy.types.Scene.hm64_bk64_mipmap = BoolProperty(
        name="Trilinear Mipmap",
        default=False,
        description="Trilinear mipmap filtering",
    )
    bpy.types.Scene.hm64_bk64_file_format = EnumProperty(
        name="Format",
        items=bk64_file_format_enum,
        default="O2R",
        description="An o2r resource family, or a single .bin for the ROM hacking tools",
    )
    bpy.types.Scene.hm64_bk64_rigging = EnumProperty(
        name="Rigging",
        items=bk64_rigging_enum,
        default="SPLIT",
        description="How the mesh follows the bones. Split At Bones cuts it into rigid pieces, Bind "
        "Vertices keeps it whole and weights each vertex to one bone",
    )
    bpy.types.Scene.hm64_bk64_draw_layer = EnumProperty(
        name="Draw Layer",
        items=bk64_draw_layer_enum,
        default="OPAQUE",
        description="Opaque for solid geometry, Translucent for blended. Whether the model reads "
        "or writes depth stays with the game",
    )
    bpy.types.Object.hm64_bk64_geo_type_raw = IntProperty(
        name="Imported Geo Type",
        default=0,
        min=0,
        description="The geo type word an imported model came in with, written back as it is. It sits "
        "on the object because a level's two halves differ. Set it to 0 to use Env Map and Mipmap",
    )
    bpy.types.Scene.hm64_bk64_import_path = StringProperty(
        name="Model File",
        subtype="FILE_PATH",
        description="A BK model resource extracted from bk.o2r. Pick the model itself, not a "
        "_GEO, _VTX or _tex sibling",
    )
    bpy.types.Scene.hm64_bk64_level_folder = StringProperty(
        name="Level Folder",
        subtype="DIR_PATH",
        description="Folder holding extracted level resources. Unpack bk.o2r and pick its "
        "assets/level folder, or the folder you unpacked it into",
    )
    bpy.types.Scene.hm64_bk64_level = EnumProperty(
        name="Level",
        items=bk64_level_enum,
        description="Which level to read",
    )
    bpy.types.Scene.hm64_bk64_level_layer = EnumProperty(
        name="Halves",
        items=bk64_level_layer_enum,
        default="BOTH",
        description="Which of the level's two models to bring in",
    )
    bpy.types.Scene.hm64_bk64_import_bone_length = FloatProperty(
        name="Bone Length",
        default=0.1,
        min=0.001,
        description="Viewport length for bones with no child to point at. Cosmetic only, BK joints are points",
    )

    bpy.types.Scene.hm64_bk64_anim_path = StringProperty(
        name="Animation Path",
        default="assets/anim/myanim",
        description="Path the animation is stored at inside the archive. Use a vanilla animation's "
        "own path to replace it, e.g. assets/anim/ASSET_64_GRUBLIN_ALERT",
    )
    bpy.types.Scene.hm64_bk64_anim_import_path = StringProperty(
        name="Animation File",
        subtype="FILE_PATH",
        description="A BK animation extracted from bk.o2r, or a .bin, to read onto the selected "
        "armature. Applied by bone id, so import that model's skeleton first",
    )
    bpy.types.Scene.hm64_bk64_anim_include_rest = BoolProperty(
        name="Hold Unanimated Bones",
        default=True,
        description="Writes one key holding every bone the action never moves. Without it those "
        "bones keep the pose left by the previous animation",
    )

    bpy.types.Material.hm64_bk64_draw_layer = EnumProperty(
        name="Draw Layer",
        items=bk64_material_draw_layer_enum,
        default="SCENE",
        description="Draws faces using this material on their own render mode, so one model can mix "
        "solid and translucent geometry",
    )
    bpy.types.Material.hm64_bk64_collision_type = EnumProperty(
        name="Collision",
        items=bk64_collision_type_enum,
        default="NONE",
        description="Whether faces using this material go into the model's collision list, and what "
        "kind of surface they are. Characters carry no collision, scenery does",
    )
    bpy.types.Material.hm64_bk64_trottable_slope = BoolProperty(
        name="Trottable Slope",
        description="Slippery unless the player is in Talon Trot",
    )
    bpy.types.Material.hm64_bk64_untrottable_slope = BoolProperty(
        name="Untrottable Slope",
        description="Slippery in any move except a transformation",
    )
    bpy.types.Material.hm64_bk64_hazard_1 = BoolProperty(
        name="Hazard 1",
        description="Damages the player where the map has a matching hazard. Piranha water and thorns",
    )
    bpy.types.Material.hm64_bk64_hazard_2 = BoolProperty(
        name="Hazard 2",
        description="Damages the player where the map has a matching hazard. GV's sand",
    )
    bpy.types.Material.hm64_bk64_hazard_3 = BoolProperty(
        name="Hazard 3",
        description="The third hazard bit. Vanilla never sets it, the game reads all three",
    )
    bpy.types.Material.hm64_bk64_double_sided = BoolProperty(
        name="Double Sided",
        description="Solid from either face",
    )
    bpy.types.Material.hm64_bk64_non_impeding = BoolProperty(
        name="Non-Impeding",
        description="Detected but does not block movement",
    )
    bpy.types.Material.hm64_bk64_script_target = BoolProperty(
        name="Script Target",
        description="Targeted by the map's event scripts",
    )
    bpy.types.Material.hm64_bk64_collision_extra = IntProperty(
        name="Other Flags",
        default=0,
        description="Unidentified flag bits, kept so an imported surface exports unchanged",
    )
    bpy.types.Material.hm64_bk64_sound_type = EnumProperty(
        name="Sound Type",
        items=bk64_sound_type_enum,
        default="MAP_DEFAULT",
        description="Which footstep sound the surface makes",
    )
    bpy.types.Material.hm64_bk64_source_chunk = IntProperty(
        name="Source Chunk",
        default=-1,
        min=-1,
        description="Display list an imported face was drawn in. The export needs it to write the "
        "layout the model came with. -1 for geometry that was not imported",
    )
    bpy.types.Material.hm64_bk64_collision_raw = IntProperty(
        name="Raw Flags",
        default=0,
        description="The flag word an imported surface came in with, written back as it is. Only set "
        "when the word holds a bit the choices above can't describe. Set it to 0 to author with them",
    )
    bpy.types.Material.hm64_bk64_collision_unk6 = IntProperty(
        name="Raw Unk6",
        default=0,
        min=0,
        max=0xFFFF,
        description="The unidentified halfword an imported collision triangle came in with, written back untouched",
    )
    bpy.types.Material.hm64_bk64_anim_tex = EnumProperty(
        name="Animated Texture",
        items=bk64_anim_tex_enum,
        default="NONE",
        description="Cycle this material's texture through the frames listed below",
    )
    bpy.types.Material.hm64_bk64_anim_slot = IntProperty(
        name="Slot",
        default=0,
        min=0,
        max=ANIM_TEX_SLOT_COUNT - 1,
        description="Which of the model's four animation slots drives this texture. Leave it at 0 "
        "unless the model animates more than one texture at once",
    )
    bpy.types.Material.hm64_bk64_anim_rate = FloatProperty(
        name="Frames Per Second",
        default=5.0,
        min=0.01,
        max=60.0,
        description="How fast the frames cycle. Vanilla runs between 4 and 15",
    )

    bpy.types.Bone.hm64_bk64_bone_id = IntProperty(
        name="BK Bone ID",
        default=0,
        min=0,
        max=MAX_BONE_ID,
        description="The id animations use to address this bone. Replacing a vanilla model means "
        "matching its ids exactly. 0 assigns ids automatically on export",
    )
    bpy.types.Bone.hm64_bk64_geo_type = EnumProperty(
        name="Geo Type",
        items=bk64_geo_type_enum,
        default="NONE",
        description="What this bone does in the geo layout, beyond carrying geometry",
    )
    bpy.types.Bone.hm64_bk64_geo_index = IntProperty(
        name="Geo Index",
        default=0,
        min=0,
        max=0x7FFF,
        description="Appendage id for a Selector, the number the game sets to pick a child. "
        "Slot number for a Reference Point, where the actor reads the joint back",
    )
    bpy.types.Bone.hm64_bk64_lod_near = FloatProperty(
        name="Near Distance",
        default=0.0,
        min=0.0,
        description="Closest the camera can be and still draw this, in BK units. 0 for no near limit",
    )
    bpy.types.Bone.hm64_bk64_lod_far = FloatProperty(
        name="Far Distance",
        default=0.0,
        min=0.0,
        description="Furthest the camera can be and still draw this, in BK units",
    )
    bpy.types.Bone.hm64_bk64_bone_order = IntProperty(
        name="BK Bone Order",
        default=-1,
        description="Position in the exported bone table. The skeleton importer sets this so a "
        "round trip keeps the original order. -1 sorts by name",
    )


def bk64_properties_unregister():
    for prop in _BK64_SCENE_PROPS:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    for prop in _BK64_OBJECT_PROPS:
        if hasattr(bpy.types.Object, prop):
            delattr(bpy.types.Object, prop)
    for prop in _BK64_BONE_PROPS:
        if hasattr(bpy.types.Bone, prop):
            delattr(bpy.types.Bone, prop)
    for prop in _BK64_MATERIAL_PROPS:
        if hasattr(bpy.types.Material, prop):
            delattr(bpy.types.Material, prop)
