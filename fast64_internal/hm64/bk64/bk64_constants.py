import struct

# Torch ResourceType fourccs, little endian
RT_BK_MODEL = 0x424B4D4F
RT_BK_ANIM = 0x424B414E
RT_VERTEX = 0x4F565458
RT_BLOB = 0x4F424C42
RT_TEXTURE = 0x4F544558

BKMODEL_MAGIC = 0x0B
BKMODEL_HEADER_SIZE = 0x38

OTR_HEADER_SIZE = 0x40
OTR_ID = 0xDEADBEEFDEADBEEF

OTR_TEXTURE_V0 = 0
OTR_TEXTURE_V1 = 1
TEX_FLAG_LOAD_AS_RAW = 1 << 0

# libultraship TextureType
OTEX_TYPE = {
    "RGBA32": 1,
    "RGBA16": 2,
    "CI4": 3,
    "CI8": 4,
    "I4": 5,
    "I8": 6,
    "IA4": 7,
    "IA8": 8,
    "IA16": 9,
}

F3D_FMT_TO_OTEX = {
    ("G_IM_FMT_RGBA", "G_IM_SIZ_16b"): "RGBA16",
    ("G_IM_FMT_RGBA", "G_IM_SIZ_32b"): "RGBA32",
    ("G_IM_FMT_CI", "G_IM_SIZ_4b"): "CI4",
    ("G_IM_FMT_CI", "G_IM_SIZ_8b"): "CI8",
    ("G_IM_FMT_I", "G_IM_SIZ_4b"): "I4",
    ("G_IM_FMT_I", "G_IM_SIZ_8b"): "I8",
    ("G_IM_FMT_IA", "G_IM_SIZ_4b"): "IA4",
    ("G_IM_FMT_IA", "G_IM_SIZ_8b"): "IA8",
    ("G_IM_FMT_IA", "G_IM_SIZ_16b"): "IA16",
}

PALETTED_FORMATS = frozenset(("CI4", "CI8"))

# BKTextureInfo.type. model.h names the first four, but 0x10 is vanilla too,
# on the MMM skyboxes and the lightning among others
BK_TEX_TYPE = {"CI4": 1, "CI8": 2, "RGBA16": 4, "RGBA32": 8, "IA8": 16}

# every type the game has a bit for
BIN_TEX_FORMATS = frozenset(("CI4", "CI8", "RGBA16", "RGBA32", "IA8"))

# a baked shade color needs RGB to sit in. IA8 carries intensity and alpha, so
# a fold has nowhere to go and the texture keeps the SHADE that tints it.
SHADE_FOLD_FORMATS = frozenset(("CI4", "CI8", "RGBA16", "RGBA32"))

# the game reads a fixed size per format. A short palette needs padding.
BK_PALETTE_SIZE = {"CI4": 0x20, "CI8": 0x200}

# for stepping over an image in the model's own texture blob
BK_TEX_BITS = {"CI4": 4, "CI8": 8, "RGBA16": 16, "RGBA32": 32, "IA8": 8}

# slot i of the animated texture list drives this segment, counting down. Each
# frame the game slides that segment's base on by frame_size bytes.
SEG_ANIM_BASE = 15
ANIM_TEX_SLOT_COUNT = 4
ANIM_FRAME_FORMATS = frozenset(("RGBA16", "RGBA32", "IA8", "CI4", "CI8"))  # a CI frame carries its palette with it

MAX_TEXTURE_DIM = 255  # BKTextureInfo stores width/height as u8

GEO_CMD_UNK0 = 0x00
GEO_CMD_SORT = 0x01
GEO_CMD_BONE = 0x02
GEO_CMD_LOADDL = 0x03
GEO_CMD_NOP = 0x04
GEO_CMD_SKINNING = 0x05
GEO_CMD_CALL = 0x06
GEO_CMD_LOADDL2 = 0x07
GEO_CMD_LOD = 0x08
GEO_CMD_REFPOINT = 0x0A
GEO_CMD_SELECTOR = 0x0C
GEO_CMD_DRAWDIST = 0x0D
GEO_CMD_CULL = 0x0E  # a sphere the game tests before drawing what hangs off it
GEO_CMD_CAMERA = 0x0F  # the areas what hangs off it draws inside, or outside with flag 2
GEO_CMD_TEXWRAP = 0x10  # 1 clamps the mipmap tiles that follow, 2 wraps them

GEO_CMD_SIZE = 12  # every geo command is padded to 12 bytes
GEO_BONE_BRANCH_OFFSET = 12  # BONE to its own LOADDL
GEO_BONE_PAIR_SIZE = 24  # BONE to the next BONE
GEO_REFPOINT_SIZE = 24  # index, matrix id and a f32 point
GEO_LOD_SIZE = 32  # two distances, a f32 point and the branch
GEO_DRAWDIST_SIZE = 24  # a s16 box and the branch, padded from 22
GEO_SORT_SIZE = 40  # two f32 points, flags and two branches

MAX_APPENDAGE_ID = 0x29  # the visibility table is 0x2A entries, and SELECTOR treats 0 as unset

MAX_DRAWABLE_BONE_INDEX = 127  # geo_cmd_bone_s.anim_matrix_id is an s8
MAX_BONE_ID = 0x6C  # the bone transform table is 0x6D entries, indexed by id unchecked
MAX_LAYOUT_BONE = 127  # the geo layout's BONE command holds its bone index in an s8

MESH_GROUP_PREFIX = "bk64_mesh_"  # the uid rides in the name, it's what the game looks a mesh up by

GEO_TYPE_MIPMAP_TRILINEAR = 0x02

# A mipmapped chunk renders from the game's own tile pyramid, texture level 2
# tile 2, and its load brings base plus pyramid. The pyramid is 32x32 RGBA16.
MIP_TEXTURE_DIM = 32
MIP_SPTEXTURE_LEVEL = 2
MIP_SPTEXTURE_TILE = 2
MIP_LOAD_TILE_INDEX = 7
MIP_LOAD_TILE = (0xF5100000, 0x07014050)  # load tile 7
MIP_LOAD_BLOCK = (0xF3000000, 0x075FF100)  # 0x600 texels
MIP_ROW_BYTES = MIP_TEXTURE_DIM * 2
MIP_PYRAMID_SIZE = (0x600 - MIP_TEXTURE_DIM * MIP_TEXTURE_DIM) * 2
GEO_TYPE_ENV_MAP = 0x04

# BK is F3DEX 1
OP_MOVEMEM = 0x03
OP_MOVEWORD = 0xBC
OP_DL = 0x06
OP_VTX = 0x04
OP_TRI2 = 0xB1
OP_CLEARGEOMETRYMODE = 0xB6
OP_SETGEOMETRYMODE = 0xB7
OP_ENDDL = 0xB8
OP_CULLDL = 0xBE
OP_TRI1 = 0xBF
OP_SETTILE = 0xF5
OP_SETTILESIZE = 0xF2
OP_LOADBLOCK = 0xF3
OP_SETPRIMCOLOR = 0xFA
OP_SETENVCOLOR = 0xFB
OP_SETCOMBINE = 0xFC
OP_SETTIMG = 0xFD
OP_TEXTURE = 0xBB
OP_POPMTX = 0xBD

# texture gen reads the normal only the lighting pipeline transforms. All 72
# vanilla models that set one set the other.
G_LIGHTING = 0x00020000
G_TEXTURE_GEN = 0x00040000

# geometry mode bit -> the rdp_settings flag that writes it again
GEO_MODE_FLAGS = {
    0x00000001: "g_zbuffer",
    0x00000004: "g_shade",
    0x00000200: "g_shade_smooth",
    0x00001000: "g_cull_front",
    0x00002000: "g_cull_back",
    0x00010000: "g_fog",
    0x00020000: "g_lighting",
    0x00040000: "g_tex_gen",
    0x00080000: "g_tex_gen_linear",
}

# what modelRender_draw leaves set. Clearing a bit that was never set still
# leaves the right mode.
GEO_MODE_START = 0x00000001 | 0x00000004 | 0x00000200  # zbuffer, shade, shade smooth

# getLightDefinitions' default direction, as the signed bytes the RSP would get
DEFAULT_LIGHT_DIR = (0x49, 0x49, 0x49)

SEG_RENDERMODE = 3
RENDERMODE_ENTRY_STRIDE = 16  # 2 Gfx, as a byte offset into the table
RENDERMODE_OPAQUE = 0  # G_RM_OPA_SURF2
RENDERMODE_AA_OPAQUE = 1  # G_RM_AA_OPA_SURF2, what vanilla actors use
RENDERMODE_TRANSLUCENT = 2  # G_RM_XLU_SURF2
RENDERMODE_AA_TRANSLUCENT = 3  # G_RM_AA_XLU_SURF2

# draw layer -> table entry, None to set no render mode at all
BK64_DRAW_LAYER_ENTRY = {
    "OPAQUE": RENDERMODE_AA_OPAQUE,
    "OPAQUE_NO_AA": RENDERMODE_OPAQUE,
    "TRANSLUCENT": RENDERMODE_AA_TRANSLUCENT,
    "TRANSLUCENT_NO_AA": RENDERMODE_TRANSLUCENT,
    "INHERIT": None,
}

CYCLE_TYPE_2CYCLE = "G_CYC_2CYCLE"

# Segments the resource family binds
SEG_VTX = 1  # byte offset into the _VTX sibling
SEG_TEX = 0xFF  # index of a _tex_<i> sibling
SEG_TEX_BLOB = 2  # offset into the model's own texture blob

# An untextured run leaves the last G_SETTIMG standing. A ROM binds a white
# texture instead. The game never looks, its combiner takes SHADE.
WHITE_TEXTURE_DIM = 8

# the grid a collision query walks. Vanilla's scales are multiples of 100, at
# around five triangles a cell
BK_COLLISION_SCALE_STEP = 100
BK_COLLISION_SCALE_MIN = 300
BK_COLLISION_SCALE_MAX = 8000
BK_COLLISION_CELL_TRIANGLES = 5
BK_COLLISION_MAX_CELLS = 16384  # vanilla tops out at 12441
BK_COLLISION_MAX_ENTRIES = 32000  # tri_cnt and start_tri_index are both s16

# The sound field holds a map sound slot, or with bit 31 one of the shared
# sounds. core2/map/audioconfig.c resolves the slots through a per-map table.
BK_COLLISION_SOUND_MASK = 0x80001F00
BK_SOUND_TYPE = {
    "NONE": 0x00000000,
    "MAP_DEFAULT": 0x00000100,
    "MAP_1": 0x00000200,
    "MAP_2": 0x00000400,
    "MAP_3": 0x00000800,
    "MAP_4": 0x00001000,
    "NORMAL": 0x80000000,
    "METAL": 0x80000100,
    "HARD_GROUND": 0x80000200,
    "STONE": 0x80000300,
    "WOOD": 0x80000400,
    "SNOW": 0x80000500,
    "LEAVES": 0x80000600,
    "SWAMP": 0x80000700,
    "SAND": 0x80000800,
    "SLUSH": 0x80000900,
}

# BKCollisionTriangle.flags is a bit field
BK_COLLISION_MEDIUM_SHIFT = 17
BK_COLLISION_MEDIUM_MASK = 0x001E0000  # core2/vtx/listutils.c func_802E7408 tests all four together
BK_MEDIUM_TYPE = {"GROUND": 0, "WATER": 1, "WATER2": 2}

BK_COLLISION_FLAG_BITS = {
    "trottable_slope": 0x00000010,
    "untrottable_slope": 0x00000040,
    "hazard_1": 0x00002000,  # ba/hazards.c reads 0xE000 as a group, gated per map
    "hazard_2": 0x00004000,  # GV's sand tests this one alone
    "hazard_3": 0x00008000,
    "double_sided": 0x00010000,  # core2/collision/raycast.c, and listutils.c inverts the normal
    "non_impeding": 0x00400000,
    "script_target": 0x08000000,
}

# unidentified bits vanilla sets
BK_COLLISION_EXTRA_MASK = 0x47A00086

BK_COLLISION_KNOWN_MASK = BK_COLLISION_SOUND_MASK | BK_COLLISION_MEDIUM_MASK | BK_COLLISION_EXTRA_MASK
for _mask in BK_COLLISION_FLAG_BITS.values():
    BK_COLLISION_KNOWN_MASK |= _mask
del _mask


def bk64_surface_decode(flags: int) -> dict | None:
    """The flag word as named fields, or None if it sets a bit we don't recognize"""
    flags &= 0xFFFFFFFF
    if flags & ~BK_COLLISION_KNOWN_MASK:
        return None
    sound = flags & BK_COLLISION_SOUND_MASK
    medium = (flags & BK_COLLISION_MEDIUM_MASK) >> BK_COLLISION_MEDIUM_SHIFT
    if sound not in BK_SOUND_TYPE.values() or medium not in BK_MEDIUM_TYPE.values():
        return None
    if medium and sound == BK_SOUND_TYPE["MAP_DEFAULT"]:
        return None

    fields = {name: bool(flags & mask) for name, mask in BK_COLLISION_FLAG_BITS.items()}
    fields["sound"] = sound
    fields["medium"] = medium
    fields["extra"] = flags & BK_COLLISION_EXTRA_MASK
    return fields


def bk64_surface_encode(fields: dict) -> int:
    """The flag word for those fields"""
    flags = fields.get("sound", 0) & BK_COLLISION_SOUND_MASK
    if fields.get("medium") and flags == BK_SOUND_TYPE["MAP_DEFAULT"]:
        flags = 0
    flags |= (fields.get("medium", 0) << BK_COLLISION_MEDIUM_SHIFT) & BK_COLLISION_MEDIUM_MASK
    flags |= fields.get("extra", 0) & BK_COLLISION_EXTRA_MASK
    for name, mask in BK_COLLISION_FLAG_BITS.items():
        if fields.get(name):
            flags |= mask
    return flags


NO_PARENT = 0xFFFF


def otr_header(resource_type: int, version: int = 0):
    # byte order, is custom, 2 unused, type, version, id
    data = bytearray(struct.pack("<BBBBIIQ", 0, 1, 0, 0, resource_type, version, OTR_ID))
    data.extend(b"\x00" * (OTR_HEADER_SIZE - len(data)))
    return data


def s16(value):
    """Rounded and clamped, a coordinate past the range would wrap"""
    return max(-32768, min(32767, int(round(value))))


def tri_indices(word, cache):
    """The three vertices a G_TRI word names, or None when a slot holds nothing yet"""
    try:
        return [cache[((word >> shift) & 0xFF) // 2] for shift in (16, 8, 0)]
    except KeyError:
        return None


MAX_VERTEX_COUNT = 32767  # the header count is an s16, the port drops indices past it

# where an imported model's geo layout rides, as JSON on the armature
GEO_LAYOUT_PROP = "hm64_bk64_geo_layout"

# an HD image carries the N64 size its tiles address, for the slot to read back
NATIVE_SIZE_PROP = "hm64_bk64_native_size"

# the mip levels a texture arrived with, and
# a fingerprint of the base they were drawn from.
MIP_PYRAMID_PROP = "hm64_bk64_mip_pyramid"
MIP_BASE_PROP = "hm64_bk64_mip_base"

# the display list chunk each imported face was drawn in, on the mesh rather
# than the material so identical materials can share one slot
SOURCE_CHUNK_ATTR = "hm64_bk64_source"

# the cell grid a model's collision came with, written back while the surface
# set still matches
COLLISION_GRID_PROP = "hm64_bk64_collision_grid"

# markers on helper objects, found by walking the root's children on export
SHAPE_KIND = "hm64_bk64_shape"
SHAPE_PIVOT = "hm64_bk64_shape_pivot"  # the point a box turns about, kept to export it back in place
COLLISION_ONLY_PROP = "hm64_bk64_collision_only"

# what an undrawn collision vertex carried. Nothing reads them, a round trip does.
COLLISION_COLOR_ATTR = "hm64_bk64_vtx_color"
COLLISION_UV_ATTR = "hm64_bk64_vtx_uv"

# a f32[9] per bone: rotation, scale, then translation
ANIM_SCALE = 3  # where the scale channels start, so anything below is a rotation
ANIM_TRANSLATION = 6
ANIM_CHANNEL_COUNT = 9
ANIM_CHANNEL_DEFAULTS = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)

ANIM_FIXED_POINT = 64  # every value is read back as (f32)unk2 / 64
ANIM_MAX_KEY_FRAME = 0x3FFF  # AnimationFileData.unk0_13 is 14 bits
ANIM_MAX_ELEMENTS = 0x7FFF  # elem_cnt is an s16

# Rotation is degrees, composed roll then yaw then pitch
ANIM_MAX_VALUE = 32767 / ANIM_FIXED_POINT

# What the game leaves the RDP set to before a model draws, not preferences.
# Match it and nothing gets written.
bk64_world_defaults = {
    "geometryMode": {
        "zBuffer": True,
        "shade": True,
        "cullBack": False,  # the per frame clear drops it and nothing puts it back
        "lighting": False,  # the model path loads no lights
        "shadeSmooth": True,
        "clipping": False,  # nothing in the game ever sets it
    },
    "otherModeH": {
        # the setup lists never touch dithering and no vanilla model writes it,
        # so match the presets and nothing gets written either way
        "alphaDither": "G_AD_NOISE",
        "textureFilter": "G_TF_BILERP",
        "perspectiveCorrection": "G_TP_PERSP",
        "textureConvert": "G_TC_FILT",
        "pipelineMode": "G_PM_1PRIMITIVE",
        "cycleType": "G_CYC_2CYCLE",  # every model setup display list sets it
    },
}
