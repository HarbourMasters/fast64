"""HM64 material hooks: MM presets, enhanced light preview, cosmetic entry UI."""

import bpy
from mathutils import Color, Vector
from bpy.types import Material, Panel


def _prim_cosmetic_entry(panel: Panel, f3dMat, layout):
    """Extension hook for ui_prim: adds dynamic cosmetic entry controls."""
    layout.prop(f3dMat, "prim_dynamic_entry", text="Dynamic Cosmetic Entry")
    if getattr(f3dMat, "prim_dynamic_entry"):
        dynamicEntry = layout.column()
        dynamicEntry.prop(f3dMat, "prim_dynamic_entry_name", text="Name")
        dynamicEntry.prop(f3dMat, "prim_dynamic_entry_category", text="Category")


def _env_cosmetic_entry(panel: Panel, f3dMat, layout):
    """Extension hook for ui_env: adds dynamic cosmetic entry controls."""
    layout.prop(f3dMat, "env_dynamic_entry", text="Dynamic Cosmetic Entry")
    if getattr(f3dMat, "env_dynamic_entry"):
        dynamicEntry = layout.column()
        dynamicEntry.prop(f3dMat, "env_dynamic_entry_name", text="Name")
        dynamicEntry.prop(f3dMat, "env_dynamic_entry_category", text="Category")


# --- Enhanced light preview (7-light compression to 2 preview lights) ---


def _get_named_node_input(node, socket_name: str):
    return next((socket for socket in node.inputs if socket.name == socket_name), None)


def _relink_preview_light_socket(material: Material, input_name: str, from_node_name: str):
    from ...f3d.f3d_material import link_if_none_exist

    nodes = material.node_tree.nodes
    shade_node = nodes.get("Shade Color")
    from_node = nodes.get(from_node_name)
    if shade_node is None or from_node is None or not from_node.outputs:
        return

    shade_input = _get_named_node_input(shade_node, input_name)
    if shade_input is not None:
        link_if_none_exist(material, from_node.outputs[0], shade_input)


def _relink_preview_reroute_socket(material: Material, socket_name: str):
    from ...f3d.f3d_material import link_if_none_exist

    nodes = material.node_tree.nodes
    target_node = nodes.get(socket_name)
    scene_props = nodes.get("SceneProperties")
    if target_node is None or scene_props is None or not target_node.inputs:
        return

    link_if_none_exist(material, scene_props.outputs[socket_name], target_node.inputs[0])


def _override_preview_reroute_socket(material: Material, socket_name: str, value):
    from ...f3d.f3d_material import remove_first_link_if_exists

    target_node = material.node_tree.nodes.get(socket_name)
    if target_node is None or not target_node.inputs:
        return

    remove_first_link_if_exists(material, target_node.inputs[0].links)
    target_node.inputs[0].default_value = value


def _get_preview_light_weight(light_data: dict) -> float:
    color = light_data["color"]
    return color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114


def _get_preview_light_entries(f3dMat, renderSettings) -> list[dict]:
    from ...utility import getObjDirectionVec

    default_dirs = [Vector(renderSettings.light0Direction), Vector(renderSettings.light1Direction)]
    default_sizes = [float(renderSettings.light0SpecSize), float(renderSettings.light1SpecSize)]
    entries: list[dict] = []

    for light_index in range(7):
        light = getattr(f3dMat, f"f3d_light{light_index + 1}")
        if light is None:
            continue

        color = [float(light.color[0]), float(light.color[1]), float(light.color[2]), 1.0]
        light_objects = [
            obj for obj in bpy.context.scene.objects if obj.type == "LIGHT" and obj.data == getattr(light, "original", light)
        ]
        if not light_objects:
            light_objects = [None]

        for obj in light_objects:
            direction = default_dirs[light_index % 2]
            if obj is not None:
                direction = Vector(getObjDirectionVec(obj, True))
            entries.append(
                {
                    "color": color.copy(),
                    "direction": direction.normalized() if direction.length_squared != 0 else default_dirs[0],
                    "size": default_sizes[light_index % 2],
                }
            )

    return entries


def _compress_preview_lights(light_entries: list[dict]) -> list[dict]:
    if len(light_entries) <= 2:
        return light_entries

    sorted_entries = sorted(light_entries, key=_get_preview_light_weight, reverse=True)
    buckets = []
    for entry in sorted_entries[:2]:
        weight = max(_get_preview_light_weight(entry), 0.001)
        buckets.append(
            {
                "color": entry["color"].copy(),
                "direction": entry["direction"].copy(),
                "direction_accum": entry["direction"] * weight,
                "size_total": entry["size"] * weight,
                "weight_total": weight,
            }
        )

    for entry in sorted_entries[2:]:
        weight = max(_get_preview_light_weight(entry), 0.001)
        bucket_index = (
            0
            if entry["direction"].dot(buckets[0]["direction"]) >= entry["direction"].dot(buckets[1]["direction"])
            else 1
        )
        bucket = buckets[bucket_index]
        for i in range(3):
            bucket["color"][i] = min(1.0, bucket["color"][i] + entry["color"][i])
        bucket["direction_accum"] += entry["direction"] * weight
        bucket["size_total"] += entry["size"] * weight
        bucket["weight_total"] += weight

    compressed = []
    for bucket in buckets:
        direction = bucket["direction_accum"]
        compressed.append(
            {
                "color": bucket["color"],
                "direction": direction.normalized() if direction.length_squared != 0 else bucket["direction"],
                "size": bucket["size_total"] / bucket["weight_total"],
            }
        )
    return compressed


def enhanced_update_light_colors(material, context):
    """Enhanced update_light_colors with 7-light compression and direction/size handling."""
    from ...f3d.f3d_material import inherit_light_and_fog, remove_first_link_if_exists, link_if_none_exist
    from ...utility import s_rgb_alpha_1_tuple

    f3dMat = material.f3d_mat
    nodes = material.node_tree.nodes
    renderSettings = context.scene.fast64.renderSettings

    if f3dMat.use_default_lighting and f3dMat.set_ambient_from_light:
        amb = Color(f3dMat.default_light_color[:3])
        amb.v /= 4.672

        new_amb = [c for c in amb]
        new_amb.append(1.0)

        f3dMat.ambient_light_color = new_amb

    if f3dMat.set_lights or inherit_light_and_fog():
        remove_first_link_if_exists(material, nodes["Shade Color"].inputs["AmbientColor"].links)
        remove_first_link_if_exists(material, nodes["Shade Color"].inputs["Light0Color"].links)
        remove_first_link_if_exists(material, nodes["Shade Color"].inputs["Light1Color"].links)

        light0 = f3dMat.default_light_color
        light1 = [0.0, 0.0, 0.0, 1.0]
        light0_direction = Vector(renderSettings.light0Direction)
        light1_direction = Vector(renderSettings.light1Direction)
        light0_size = float(renderSettings.light0SpecSize)
        light1_size = float(renderSettings.light1SpecSize)
        if not f3dMat.use_default_lighting:
            preview_lights = _compress_preview_lights(_get_preview_light_entries(f3dMat, renderSettings))
            if preview_lights:
                light0 = preview_lights[0]["color"]
                light0_direction = preview_lights[0]["direction"]
                light0_size = preview_lights[0]["size"]
            else:
                light0 = [1.0, 1.0, 1.0, 1.0]

            if len(preview_lights) > 1:
                light1 = preview_lights[1]["color"]
                light1_direction = preview_lights[1]["direction"]
                light1_size = preview_lights[1]["size"]

        nodes["Shade Color"].inputs["AmbientColor"].default_value = s_rgb_alpha_1_tuple(f3dMat.ambient_light_color)
        nodes["Shade Color"].inputs["Light0Color"].default_value = s_rgb_alpha_1_tuple(light0)
        nodes["Shade Color"].inputs["Light1Color"].default_value = s_rgb_alpha_1_tuple(light1)
        if f3dMat.set_lights and not f3dMat.use_default_lighting:
            _override_preview_reroute_socket(material, "Light0Dir", tuple(light0_direction))
            _override_preview_reroute_socket(material, "Light0Size", light0_size)
            _override_preview_reroute_socket(material, "Light1Dir", tuple(light1_direction))
            _override_preview_reroute_socket(material, "Light1Size", light1_size)
        else:
            _relink_preview_reroute_socket(material, "Light0Dir")
            _relink_preview_reroute_socket(material, "Light0Size")
            _relink_preview_reroute_socket(material, "Light1Dir")
            _relink_preview_reroute_socket(material, "Light1Size")
    else:
        nodes["Shade Color"].inputs["AmbientColor"].default_value = (0.5, 0.5, 0.5, 1.0)
        nodes["Shade Color"].inputs["Light0Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        nodes["Shade Color"].inputs["Light1Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        link_if_none_exist(material, nodes["AmbientColorOut"].outputs[0], nodes["Shade Color"].inputs["AmbientColor"])
        link_if_none_exist(material, nodes["Light0ColorOut"].outputs[0], nodes["Shade Color"].inputs["Light0Color"])
        link_if_none_exist(material, nodes["Light1ColorOut"].outputs[0], nodes["Shade Color"].inputs["Light1Color"])
        _relink_preview_reroute_socket(material, "Light0Dir")
        _relink_preview_reroute_socket(material, "Light0Size")
        _relink_preview_reroute_socket(material, "Light1Dir")
        _relink_preview_reroute_socket(material, "Light1Size")


# --- Registration ---


def register():
    from ...f3d.f3d_material import (
        register_default_presets,
        register_prim_ui_extension,
        register_env_ui_extension,
        register_light_update_override,
    )

    register_default_presets("MM", {
        "Shaded Solid": "mm_shaded_solid",
        "Shaded Texture": "mm_shaded_texture",
    })
    register_prim_ui_extension(_prim_cosmetic_entry)
    register_env_ui_extension(_env_cosmetic_entry)
    register_light_update_override(enhanced_update_light_colors)


def unregister():
    from ...f3d.f3d_material import (
        unregister_default_presets,
        unregister_prim_ui_extension,
        unregister_env_ui_extension,
        unregister_light_update_override,
    )

    unregister_light_update_override()
    unregister_env_ui_extension(_env_cosmetic_entry)
    unregister_prim_ui_extension(_prim_cosmetic_entry)
    unregister_default_presets("MM")
