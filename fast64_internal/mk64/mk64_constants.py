MODEL_HEADER = """#include <ultra64.h>
#include <macros.h>
#include <PR/gbi.h>

"""

enum_surface_types = [
    ("SURFACE_DEFAULT", "SURFACE_DEFAULT", "SURFACE_DEFAULT"),
    ("AIRBORNE", "AIRBORNE", "AIRBORNE"),
    ("ASPHALT", "ASPHALT", "ASPHALT"),
    ("DIRT", "DIRT", "DIRT"),
    ("SAND", "SAND", "SAND"),
    ("STONE", "STONE", "STONE"),
    ("SNOW", "SNOW", "SNOW"),
    ("BRIDGE", "BRIDGE", "BRIDGE"),
    ("SAND_OFFROAD", "SAND_OFFROAD", "SAND_OFFROAD"),
    ("GRASS", "GRASS", "GRASS"),
    ("ICE", "ICE", "ICE"),
    ("WET_SAND", "WET_SAND", "WET_SAND"),
    ("SNOW_OFFROAD", "SNOW_OFFROAD", "SNOW_OFFROAD"),
    ("CLIFF", "CLIFF", "CLIFF"),
    ("DIRT_OFFROAD", "DIRT_OFFROAD", "DIRT_OFFROAD"),
    ("TRAIN_TRACK", "TRAIN_TRACK", "TRAIN_TRACK"),
    ("CAVE", "CAVE", "CAVE"),
    ("ROPE_BRIDGE", "ROPE_BRIDGE", "ROPE_BRIDGE"),
    ("WOOD_BRIDGE", "WOOD_BRIDGE", "WOOD_BRIDGE"),
    ("WATER_SURFACE", "WATER_SURFACE", "WATER_SURFACE"),
    ("BOOST_RAMP_WOOD", "BOOST_RAMP_WOOD", "BOOST_RAMP_WOOD"),
    ("OUT_OF_BOUNDS", "OUT_OF_BOUNDS", "OUT_OF_BOUNDS"),
    ("BOOST_RAMP_ASPHALT", "BOOST_RAMP_ASPHALT", "BOOST_RAMP_ASPHALT"),
    ("RAMP", "RAMP", "RAMP"),
]

SURFACE_TYPE_ENUM = {
    "SURFACE_DEFAULT": -1,
    "AIRBORNE": 0,
    "ASPHALT": 1,
    "DIRT": 2,
    "SAND": 3,
    "STONE": 4,
    "SNOW": 5,
    "BRIDGE": 6,
    "SAND_OFFROAD": 7,
    "GRASS": 8,
    "ICE": 9,
    "WET_SAND": 10,
    "SNOW_OFFROAD": 11,
    "CLIFF": 12,
    "DIRT_OFFROAD": 13,
    "TRAIN_TRACK": 14,
    "CAVE": 15,
    "ROPE_BRIDGE": 16,
    "WOOD_BRIDGE": 17,
    "WATER_SURFACE": 251,
    "BOOST_RAMP_WOOD": 252,
    "OUT_OF_BOUNDS": 253,
    "BOOST_RAMP_ASPHALT": 254,
    "RAMP": 255,
}

enum_clip_types = [
    ("CLIP_NONE", "CLIP_NONE", "CLIP_NONE"),
    ("CLIP_DEFAULT", "CLIP_DEFAULT", "CLIP_DEFAULT"),
    ("CLIP_SINGLE_SIDED_WALL", "CLIP_SINGLE_SIDED_WALL", "CLIP_SINGLE_SIDED_WALL"),
    ("CLIP_SURFACE", "CLIP_SURFACE", "CLIP_SURFACE"),
    ("CLIP_DOUBLE_SIDED_WALL", "CLIP_DOUBLE_SIDED_WALL", "CLIP_DOUBLE_SIDED_WALL"),
]

CLIP_TYPE_ENUM = {
    "CLIP_NONE": 0,
    "CLIP_DEFAULT": 1,
    "CLIP_SINGLE_SIDED_WALL": 2,
    "CLIP_SURFACE": 3,
    "CLIP_DOUBLE_SIDED_WALL": 4,
}

enum_draw_layer_types = [
    ("DRAW_INVISIBLE", "DRAW_INVISIBLE", "DRAW_INVISIBLE"),
    ("DRAW_OPAQUE", "DRAW_OPAQUE", "DRAW_OPAQUE"),
    ("DRAW_TRANSLUCENT", "DRAW_TRANSLUCENT", "DRAW_TRANSLUCENT"),
    ("DRAW_TRANSLUCENT_NO_ZBUFFER", "DRAW_TRANSLUCENT_NO_ZBUFFER", "DRAW_TRANSLUCENT_NO_ZBUFFER"),
]

DRAW_LAYER_ENUM = {
    "DRAW_INVISIBLE": 0,
    "DRAW_OPAQUE": 1,
    "DRAW_TRANSLUCENT": 2,
    "DRAW_TRANSLUCENT_NO_ZBUFFER": 3,
}

enum_actor_types = [
    ("Piranha_Plant", "Piranha Plant", "Piranha Plant"),
    ("Other", "Other", "Other"),
]

mk64_world_defaults = {
    "geometryMode": {
        "zBuffer": True,
        "shade": True,
        "cullBack": True,
        "lighting": True,
        "shadeSmooth": True,
    },
    "otherModeH": {
        "alphaDither": "G_AD_NOISE",
        "textureFilter": "G_TF_BILERP",
        "perspectiveCorrection": "G_TP_PERSP",
        "textureConvert": "G_TC_FILT",
        "cycleType": "G_CYC_2CYCLE",
    },
}
