from ...f3d.f3d_gbi import GfxMatWriteMethod, SPGeometryMode, SPLoadGeometryMode, SPSetGeometryMode, SPClearGeometryMode


def get_geo_cmds(clear_modes: set[str], set_modes: set[str], is_ex2: bool, matWriteMethod: GfxMatWriteMethod):
    set_modes, clear_modes = set(set_modes), set(clear_modes)
    if len(clear_modes) == 0 and len(set_modes) == 0:
        return ([], [])

    material = []
    revert = []
    if len(set_modes) > 0:
        material.append(SPSetGeometryMode(set_modes))
        revert.append(SPClearGeometryMode(set_modes))
    if len(clear_modes) > 0:
        material.append(SPClearGeometryMode(clear_modes))
        revert.append(SPSetGeometryMode(clear_modes))
    return (material, revert)
