from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import PropertyGroup, UILayout
from bpy.utils import register_class, unregister_class
from ...utility import prop_split
from ...f3d.f3d_material import ootEnumDrawLayers


class MK64CourseDLImportSettings(PropertyGroup):
    name: StringProperty(name="Name")
    path: StringProperty(name="Directory", subtype="FILE_PATH")
    base_path: StringProperty(name="Directory", subtype="FILE_PATH")
    remove_doubles: BoolProperty(name="Remove Doubles", default=True)
    import_normals: BoolProperty(name="Import Normals", default=True)
    enable_render_Mode_Default: BoolProperty(name="Set Render Mode by Default", default=True)

    def draw_props(self, layout: UILayout):
        prop_split(layout, self, "name", "Name")
        prop_split(layout, self, "path", "File")
        prop_split(layout, self, "base_path", "Base Path")
        layout.prop(self, "remove_doubles")
        layout.prop(self, "import_normals")

        layout.prop(self, "enable_render_Mode_Default")

class MK64DLExportSettings(PropertyGroup):
    isCustomFilename: BoolProperty(
        name="Use Custom Filename", description="Override filename instead of basing it off of the Blender name"
    )
    filename: StringProperty(name="Filename")
    folder: StringProperty(name="DL Folder", default="gameplay_keep")
    customPath: StringProperty(name="Custom DL Path", subtype="FILE_PATH")
    isCustom: BoolProperty(
        name="Use Custom Path", description="Determines whether or not to export to an explicitly specified folder"
    )
    removeVanillaData: BoolProperty(name="Replace Vanilla DLs")
    drawLayer: EnumProperty(name="Draw Layer", items=ootEnumDrawLayers)
    actorOverlayName: StringProperty(name="Overlay", default="")
    flipbookUses2DArray: BoolProperty(name="Has 2D Flipbook Array", default=False)
    flipbookArrayIndex2D: IntProperty(name="Index if 2D Array", default=0, min=0)
    customAssetIncludeDir: StringProperty(
        name="Asset Include Directory",
        default="assets/objects/gameplay_keep",
        description="Used in #include for including image files",
    )

    def draw_props(self, layout: UILayout):
        layout.label(text="Object name used for export.", icon="INFO")
        layout.prop(self, "isCustomFilename")
        if self.isCustomFilename:
            prop_split(layout, self, "filename", "Filename")
        prop_split(layout, self, "folder", "Object" if not self.isCustom else "Folder")
        if self.isCustom:
            prop_split(layout, self, "customAssetIncludeDir", "Asset Include Path")
            prop_split(layout, self, "customPath", "Path")
        else:
            prop_split(layout, self, "actorOverlayName", "Overlay (Optional)")
            layout.prop(self, "flipbookUses2DArray")
            if self.flipbookUses2DArray:
                box = layout.box().column()
                prop_split(box, self, "flipbookArrayIndex2D", "Flipbook Index")

        prop_split(layout, self, "drawLayer", "Export Draw Layer")
        layout.prop(self, "isCustom")
        layout.prop(self, "removeVanillaData")

mk64_dl_writer_classes = [
    MK64CourseDLImportSettings,
]


def f3d_props_register():
    for cls in mk64_dl_writer_classes:
        register_class(cls)


def f3d_props_unregister():
    for cls in reversed(mk64_dl_writer_classes):
        unregister_class(cls)
