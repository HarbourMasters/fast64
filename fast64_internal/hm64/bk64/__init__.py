_REGISTERED = False


def register():
    global _REGISTERED
    if _REGISTERED:
        return

    from .bk64_operators import bk64_operators_register
    from .bk64_panels import bk64_panels_register
    from .bk64_presets import bk64_presets_register
    from .bk64_properties import bk64_properties_register

    bk64_presets_register()
    bk64_properties_register()
    bk64_operators_register()
    bk64_panels_register()
    _REGISTERED = True


def unregister():
    global _REGISTERED
    if not _REGISTERED:
        return

    from .bk64_operators import bk64_operators_unregister
    from .bk64_panels import bk64_panels_unregister
    from .bk64_presets import bk64_presets_unregister
    from .bk64_properties import bk64_properties_unregister

    bk64_panels_unregister()
    bk64_operators_unregister()
    bk64_properties_unregister()
    bk64_presets_unregister()
    _REGISTERED = False
