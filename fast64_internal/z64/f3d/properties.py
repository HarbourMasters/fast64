from bpy.types import PropertyGroup, Object, World, Material, UILayout
from bpy.props import PointerProperty, StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty, CollectionProperty
from bpy.utils import register_class, unregister_class

from ...f3d.f3d_material import update_world_default_rendermode
from ...f3d.f3d_parser import ootEnumDrawLayers
from ...utility import prop_split
from ..utility import is_hackeroot

LIMB_MATRIX_OPTIONS = (
    ("none", "None", ""),
    ("head", "Head (0x0D0001C0)", ">0x0D0001C0"),
    ("hat", "Hat (0x0D000200)", ">0x0D000200"),
    ("left_shoulder", "Left Shoulder (0x0D000280)", ">0x0D000280"),
    ("left_arm", "Left Arm (0x0D0002C0)", ">0x0D0002C0"),
    ("left_hand", "Left Hand (0x0D000300)", ">0x0D000300"),
    ("right_shoulder", "Right Shoulder (0x0D000340)", ">0x0D000340"),
    ("right_arm", "Right Arm (0x0D000380)", ">0x0D000380"),
    ("right_hand", "Right Hand (0x0D0003C0)", ">0x0D0003C0"),
    ("chest", "Chest (0x0D000440)", ">0x0D000440"),
    ("collar", "Collar (0x0D000240)", ">0x0D000240"),
    ("waist", "Waist (0x0D000000)", ">0x0D000000"),
    ("right_thigh", "Right Thigh (0x0D000040)", ">0x0D000040"),
    ("right_leg", "Right Leg (0x0D000080)", ">0x0D000080"),
    ("right_foot", "Right Foot (0x0D0000C0)", ">0x0D0000C0"),
    ("left_thigh", "Left Thigh (0x0D000100)", ">0x0D000100"),
    ("left_leg", "Left Leg (0x0D000140)", ">0x0D000140"),
    ("left_foot", "Left Foot (0x0D000180)", ">0x0D000180"),
)
LIMB_MATRIX_PATHS = {key: path for key, _label, path in LIMB_MATRIX_OPTIONS}


class OOTDLMatrixCallPair(PropertyGroup):
    limb: EnumProperty(
        name="Limb",
        items=LIMB_MATRIX_OPTIONS,
        default="none",
    )
    call_dl: StringProperty(
        name="Call DL",
        default="",
        description="Display list path to emit after the matrix entry",
    )
    internal_path: StringProperty(
        name="Internal Path",
        default="",
        description="Optional internal path prefix used when writing the call display list",
    )

    @property
    def matrix_path(self) -> str:
        return LIMB_MATRIX_PATHS.get(self.limb, "")


class OOTDLExportSettings(PropertyGroup):
    isCustomFilename: BoolProperty(
        name="Use Custom Filename", description="Override filename instead of basing it off of the Blender name"
    )
    filename: StringProperty(name="Filename")
    folder: StringProperty(name="DL Folder", default="gameplay_keep")
    customPath: StringProperty(name="Custom DL Path", subtype="FILE_PATH")
    isCustom: BoolProperty(
        name="Use Custom Path",
        description="Determines whether or not to export to an explicitly specified folder",
        default=True,
    )
    removeVanillaData: BoolProperty(name="Replace Vanilla DLs")
    actorOverlayName: StringProperty(name="Overlay", default="")
    flipbookUses2DArray: BoolProperty(name="Has 2D Flipbook Array", default=False)
    flipbookArrayIndex2D: IntProperty(name="Index if 2D Array", default=0, min=0)
    customAssetIncludeDir: StringProperty(
        name="Asset Include Directory",
        default="assets/objects/gameplay_keep",
        description="Used in #include for including image files",
    )
    extra_matrix_calls: CollectionProperty(type=OOTDLMatrixCallPair)
    extra_matrix_calls_index: IntProperty(default=0)

    def draw_props(self, layout: UILayout):
        prop_split(layout, self, "folder", "Internal Path")
        prop_split(layout, self, "customPath", "Path")
        prop_split(layout, self, "actorOverlayName", "Overlay (Optional)")
        box = layout.box()
        box.label(text="Matrix Path + CallDisplayList", icon="PLUS")
        row = box.row()
        row.template_list(
            "OOT_UL_matrix_call_pairs",
            "",
            self,
            "extra_matrix_calls",
            self,
            "extra_matrix_calls_index",
            rows=3,
        )
        ops = row.column(align=True)
        ops.operator("fast64.oot_add_matrix_call", icon="ADD", text="")
        ops.operator("fast64.oot_remove_matrix_call", icon="REMOVE", text="")
        if self.extra_matrix_calls:
            active = self.extra_matrix_calls[self.extra_matrix_calls_index]
            box.prop(active, "limb")
            box.prop(active, "internal_path", text="Internal Path")
            box.prop(active, "call_dl", text="Call Display List")


class OOTDLImportSettings(PropertyGroup):
    name: StringProperty(name="DL Name", default="gBoulderFragmentsDL")
    folder: StringProperty(name="DL Folder", default="gameplay_keep")
    customPath: StringProperty(name="Custom DL Path", subtype="FILE_PATH")
    isCustom: BoolProperty(name="Use Custom Path")
    removeDoubles: BoolProperty(name="Remove Doubles", default=True)
    importNormals: BoolProperty(name="Import Normals", default=True)
    drawLayer: EnumProperty(name="Draw Layer", items=ootEnumDrawLayers)
    actorOverlayName: StringProperty(name="Overlay", default="")
    flipbookUses2DArray: BoolProperty(name="Has 2D Flipbook Array", default=False)
    flipbookArrayIndex2D: IntProperty(name="Index if 2D Array", default=0, min=0)
    autoDetectActorScale: BoolProperty(name="Auto Detect Actor Scale", default=True)
    actorScale: FloatProperty(name="Actor Scale", min=0, default=10)

    def draw_props(self, layout: UILayout):
        prop_split(layout, self, "name", "DL")
        if self.isCustom:
            prop_split(layout, self, "customPath", "File")
            prop_split(layout, self, "actorScale", "Actor Scale")
        else:
            prop_split(layout, self, "folder", "Object")
            prop_split(layout, self, "actorOverlayName", "Overlay (Optional)")
            layout.prop(self, "autoDetectActorScale")
            if not self.autoDetectActorScale:
                prop_split(layout, self, "actorScale", "Actor Scale")
            layout.prop(self, "flipbookUses2DArray")
            if self.flipbookUses2DArray:
                box = layout.box().column()
                prop_split(box, self, "flipbookArrayIndex2D", "Flipbook Index")
        prop_split(layout, self, "drawLayer", "Import Draw Layer")

        layout.prop(self, "isCustom")
        layout.prop(self, "removeDoubles")
        layout.prop(self, "importNormals")


class OOTDynamicMaterialDrawLayerProperty(PropertyGroup):
    segment8: BoolProperty()
    segment9: BoolProperty()
    segmentA: BoolProperty()
    segmentB: BoolProperty()
    segmentC: BoolProperty()
    segmentD: BoolProperty()
    customCall0: BoolProperty()
    customCall0_seg: StringProperty(description="Segment address of a display list to call, e.g. 0x08000010")
    customCall1: BoolProperty()
    customCall1_seg: StringProperty(description="Segment address of a display list to call, e.g. 0x08000010")

    def key(self):
        return (
            self.segment8,
            self.segment9,
            self.segmentA,
            self.segmentB,
            self.segmentC,
            self.segmentD,
            self.customCall0_seg if self.customCall0 else None,
            self.customCall1_seg if self.customCall1 else None,
        )

    def draw_props(self, layout: UILayout, suffix: str):
        row = layout.row()
        for colIndex in range(2):
            col = row.column()
            for rowIndex in range(3):
                i = 8 + colIndex * 3 + rowIndex
                name = "Segment " + format(i, "X") + " " + suffix
                col.prop(self, "segment" + format(i, "X"), text=name)
            name = "Custom call (" + str(colIndex + 1) + ") " + suffix
            p = "customCall" + str(colIndex)
            col.prop(self, p, text=name)
            if getattr(self, p):
                col.prop(self, p + "_seg", text="")


# The reason these are separate is for the case when the user changes the material draw layer, but not the
# dynamic material calls. This could cause crashes which would be hard to detect.
class OOTDynamicMaterialProperty(PropertyGroup):
    opaque: PointerProperty(type=OOTDynamicMaterialDrawLayerProperty)
    transparent: PointerProperty(type=OOTDynamicMaterialDrawLayerProperty)

    def key(self):
        return (self.opaque.key(), self.transparent.key())

    def draw_props(self, layout: UILayout, mat: Object, drawLayer: str):
        drawLayerSuffix = {"Opaque": "OPA", "Transparent": "XLU", "Overlay": "OVL"}

        if drawLayer == "Overlay":
            return

        suffix = "(" + drawLayerSuffix[drawLayer] + ")"
        layout.box().column().label(text="OOT Dynamic Material Properties " + suffix)
        layout.label(text="See gSPSegment calls in z_scene_table.c.")
        layout.label(text="Based off draw config index in gSceneTable.")
        dynMatLayerProp: OOTDynamicMaterialDrawLayerProperty = getattr(self, drawLayer.lower())
        dynMatLayerProp.draw_props(layout.column(), suffix)
        if not mat.is_f3d:
            return
        f3d_mat = mat.f3d_mat


class OOTDefaultRenderModesProperty(PropertyGroup):
    expandTab: BoolProperty()
    opaqueCycle1: StringProperty(default="G_RM_AA_ZB_OPA_SURF", update=update_world_default_rendermode)
    opaqueCycle2: StringProperty(default="G_RM_AA_ZB_OPA_SURF2", update=update_world_default_rendermode)
    transparentCycle1: StringProperty(default="G_RM_AA_ZB_XLU_SURF", update=update_world_default_rendermode)
    transparentCycle2: StringProperty(default="G_RM_AA_ZB_XLU_SURF2", update=update_world_default_rendermode)
    overlayCycle1: StringProperty(default="G_RM_AA_ZB_OPA_SURF", update=update_world_default_rendermode)
    overlayCycle2: StringProperty(default="G_RM_AA_ZB_OPA_SURF2", update=update_world_default_rendermode)

    def draw_props(self, layout: UILayout):
        inputGroup = layout.column()
        inputGroup.prop(
            self,
            "expandTab",
            text="Default Render Modes",
            icon="TRIA_DOWN" if self.expandTab else "TRIA_RIGHT",
        )
        if self.expandTab:
            prop_split(inputGroup, self, "opaqueCycle1", "Opaque Cycle 1")
            prop_split(inputGroup, self, "opaqueCycle2", "Opaque Cycle 2")
            prop_split(inputGroup, self, "transparentCycle1", "Transparent Cycle 1")
            prop_split(inputGroup, self, "transparentCycle2", "Transparent Cycle 2")
            prop_split(inputGroup, self, "overlayCycle1", "Overlay Cycle 1")
            prop_split(inputGroup, self, "overlayCycle2", "Overlay Cycle 2")


oot_dl_writer_classes = (
    OOTDLMatrixCallPair,
    OOTDLExportSettings,
    OOTDLImportSettings,
    OOTDynamicMaterialDrawLayerProperty,
    OOTDynamicMaterialProperty,
    OOTDefaultRenderModesProperty,
)


def f3d_props_register():
    ootEnumObjectMenu = [
        ("Scene", "Parent Scene Settings", "Scene"),
        ("Room", "Parent Room Settings", "Room"),
    ]

    for cls in oot_dl_writer_classes:
        register_class(cls)

    Object.ootDrawLayer = EnumProperty(items=ootEnumDrawLayers, default="Opaque")

    # Doesn't work since all static meshes are pre-transformed
    # Object.ootDynamicTransform = PointerProperty(type = OOTDynamicTransformProperty)
    World.ootDefaultRenderModes = PointerProperty(type=OOTDefaultRenderModesProperty)
    Material.ootMaterial = PointerProperty(type=OOTDynamicMaterialProperty)
    Object.ootObjectMenu = EnumProperty(items=ootEnumObjectMenu)


def f3d_props_unregister():
    for cls in reversed(oot_dl_writer_classes):
        unregister_class(cls)

    del Material.ootMaterial
    del Object.ootObjectMenu
