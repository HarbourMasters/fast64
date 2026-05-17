# HM64 module - HarbourMasters XML export and MM/MK64 extensions
# This module contains all HM64-specific code isolated from upstream Fast64.


def hm64_register():
    # --- Sub-module registrations ---
    from .f3d.xml_exporter import register as register_xml
    from .f3d.material_hooks import register as register_material_hooks
    from .f3d.material_presets import register as register_material_presets
    from .z64.properties import register as register_z64_props
    from .z64.operators import register as register_z64_ops
    from .z64.panels import register as register_z64_panels
    from .mm.skeleton import mm_skeleton_register
    from .o2r.exporter import register as register_o2r

    register_o2r()
    register_xml()
    register_material_hooks()
    register_material_presets()
    register_z64_props()
    register_z64_ops()
    register_z64_panels()
    mm_skeleton_register()

    # --- Game mode registrations ---
    from ... import register_base_game
    from ..panels import register_oot_compatible_mode, register_sm64_compatible_mode, register_mk64_compatible_mode
    from ..f3d.flipbook import register_flipbook_game
    from ..f3d.f3d_material import register_z64_compatible_mode as register_mat_z64_mode
    from ..f3d.f3d_gbi import register_gbi_z64_compat
    from ..z64.f3d.panels import register_z64_compatible_mode

    # SOH (Ship of Harkinian) = OOT PC port
    register_base_game("SOH", "OOT")
    register_oot_compatible_mode("SOH")
    register_mat_z64_mode("SOH")
    register_gbi_z64_compat("SOH")
    register_z64_compatible_mode("SOH")
    register_flipbook_game("SOH")

    # 2SHIP (2 Ship) = MM PC port
    register_base_game("2SHIP", "MM")
    register_oot_compatible_mode("2SHIP")
    register_mat_z64_mode("2SHIP")
    register_gbi_z64_compat("2SHIP")
    register_z64_compatible_mode("2SHIP")
    register_flipbook_game("2SHIP")
    register_flipbook_game("MM")

    # SPK (Spaghetti Kart) = MK64 PC port
    register_base_game("SPK", "MK64")
    register_mk64_compatible_mode("SPK")


def hm64_unregister():
    # --- Game mode unregistrations ---
    from ... import unregister_base_game
    from ..panels import unregister_oot_compatible_mode, unregister_sm64_compatible_mode, unregister_mk64_compatible_mode
    from ..f3d.flipbook import unregister_flipbook_game
    from ..f3d.f3d_material import unregister_z64_compatible_mode as unregister_mat_z64_mode
    from ..f3d.f3d_gbi import unregister_gbi_z64_compat
    from ..z64.f3d.panels import unregister_z64_compatible_mode

    unregister_flipbook_game("MM")
    unregister_flipbook_game("2SHIP")
    unregister_flipbook_game("SOH")
    unregister_z64_compatible_mode("2SHIP")
    unregister_z64_compatible_mode("SOH")
    unregister_gbi_z64_compat("2SHIP")
    unregister_gbi_z64_compat("SOH")
    unregister_mat_z64_mode("2SHIP")
    unregister_mat_z64_mode("SOH")
    unregister_oot_compatible_mode("2SHIP")
    unregister_oot_compatible_mode("SOH")
    unregister_base_game("2SHIP")
    unregister_mk64_compatible_mode("SPK")
    unregister_base_game("SPK")
    unregister_base_game("SOH")

    # --- Sub-module unregistrations ---
    from .f3d.xml_exporter import unregister as unregister_xml
    from .f3d.material_hooks import unregister as unregister_material_hooks
    from .f3d.material_presets import unregister as unregister_material_presets
    from .z64.panels import unregister as unregister_z64_panels
    from .z64.operators import unregister as unregister_z64_ops
    from .z64.properties import unregister as unregister_z64_props
    from .mm.skeleton import mm_skeleton_unregister
    from .o2r.exporter import unregister as unregister_o2r

    mm_skeleton_unregister()
    unregister_z64_panels()
    unregister_z64_ops()
    unregister_z64_props()
    unregister_material_presets()
    unregister_material_hooks()
    unregister_xml()
    unregister_o2r()
