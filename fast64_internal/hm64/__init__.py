# HM64 module - HarbourMasters XML export and MM/MK64 extensions
# This module contains all HM64-specific code isolated from upstream Fast64.


def hm64_register():
    from .f3d.soh_xml_exporter import register as register_soh_xml
    from .z64.panels import register as register_z64_panels

    register_soh_xml()
    register_z64_panels()


def hm64_unregister():
    from .f3d.soh_xml_exporter import unregister as unregister_soh_xml
    from .z64.panels import unregister as unregister_z64_panels

    unregister_z64_panels()
    unregister_soh_xml()
