# HM64 module - HarbourMasters XML export and MM/MK64 extensions
# This module contains all HM64-specific code isolated from upstream Fast64.


def hm64_register():
    from .f3d.f3d_gbi_hm64 import register as register_f3d_gbi_hm64
    from .f3d.f3d_material_hm64 import register as register_f3d_material_hm64
    from .f3d.f3d_texture_writer_hm64 import register as register_f3d_texture_writer_hm64
    from .f3d.soh_xml_exporter import register as register_soh_xml
    from .mk64 import register as register_mk64
    from .z64.panels import register as register_z64_panels
    from .z64.skeleton import register as register_z64_skeleton
    from .mm.skeleton.operators import mm_skeleton_ops_register

    register_f3d_gbi_hm64()
    register_f3d_material_hm64()
    register_f3d_texture_writer_hm64()
    register_soh_xml()
    register_mk64()
    register_z64_skeleton()
    register_z64_panels()
    mm_skeleton_ops_register()


def hm64_unregister():
    from .f3d.f3d_gbi_hm64 import unregister as unregister_f3d_gbi_hm64
    from .f3d.f3d_material_hm64 import unregister as unregister_f3d_material_hm64
    from .f3d.f3d_texture_writer_hm64 import unregister as unregister_f3d_texture_writer_hm64
    from .f3d.soh_xml_exporter import unregister as unregister_soh_xml
    from .mk64 import unregister as unregister_mk64
    from .z64.panels import unregister as unregister_z64_panels
    from .z64.skeleton import unregister as unregister_z64_skeleton
    from .mm.skeleton.operators import mm_skeleton_ops_unregister

    mm_skeleton_ops_unregister()
    unregister_z64_panels()
    unregister_z64_skeleton()
    unregister_mk64()
    unregister_soh_xml()
    unregister_f3d_texture_writer_hm64()
    unregister_f3d_material_hm64()
    unregister_f3d_gbi_hm64()
