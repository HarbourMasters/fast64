from __future__ import annotations

import math
import os
import struct

import bpy
import mathutils

from ...utility import PluginError
from .bk64_constants import (
    ANIM_CHANNEL_COUNT,
    ANIM_CHANNEL_DEFAULTS,
    ANIM_FIXED_POINT,
    ANIM_MAX_ELEMENTS,
    ANIM_MAX_KEY_FRAME,
    ANIM_MAX_VALUE,
    ANIM_SCALE,
    ANIM_TRANSLATION,
    NO_PARENT,
    RT_BK_ANIM,
)
from .bk64_model import otr_header
from .bk64_skeleton import build_bone_table

CHANNEL_NAMES = ("rotation X", "rotation Y", "rotation Z", "scale X", "scale Y", "scale Z", "X", "Y", "Z")


def _action_fcurves(action):
    # 4.4 moved the curves into layers and left action.fcurves empty, 5.0 dropped
    # it. Take it only when it's there and has something in it.
    curves = getattr(action, "fcurves", None)
    if curves:
        return list(curves)
    return [
        curve
        for layer in getattr(action, "layers", ())
        for strip in layer.strips
        for bag in strip.channelbags
        for curve in bag.fcurves
    ]


def actions_for(armature_obj):
    # one from another rig would export as a model standing still
    bones = {bone.name for bone in armature_obj.data.bones}
    found = []
    for action in bpy.data.actions:
        for curve in _action_fcurves(action):
            if not curve.data_path.startswith('pose.bones["'):
                continue
            if curve.data_path.split('"')[1] in bones:
                found.append(action)
                break
    return found


def _to_bk(scale: float):
    """Blender's Z up and units into BK's Y up, at the model's scale"""
    return (
        mathutils.Matrix.Rotation(math.radians(-90), 4, "X")
        @ mathutils.Matrix.Diagonal(mathutils.Vector((scale, scale, scale))).to_4x4()
    )


def _quantize(value: float, channel: int, bone_name: str):
    if not -ANIM_MAX_VALUE <= value <= ANIM_MAX_VALUE:
        unit = "degrees" if channel < ANIM_SCALE else "animation units"
        raise PluginError(
            f"Bone '{bone_name}' reaches {value:.1f} {unit} on {CHANNEL_NAMES[channel]}, past the "
            f"{ANIM_MAX_VALUE:.0f} BK can store. Split it over more bones, or raise Animation Scale."
        )
    return int(round(value * ANIM_FIXED_POINT))


def _bone_channels(armature_obj, bones, to_bk, anim_scale: float, previous):
    # each is a delta from rest in its parent's space, the game composes them
    # down the table
    frame = []
    deltas = {}
    for index, bone in enumerate(bones):
        pose_bone = armature_obj.pose.bones[bone.name]
        rest = armature_obj.data.bones[bone.name].matrix_local
        # the game wants the difference from rest, not the pose, in BK's axes
        delta = to_bk @ (pose_bone.matrix @ rest.inverted()) @ to_bk.inverted()
        deltas[index] = delta
        if bone.parent_index != NO_PARENT:
            delta = deltas[bone.parent_index].inverted() @ delta

        _translation, rotation, bone_scale = delta.decompose()
        # to_euler can jump a full turn. Keep each one near the last.
        euler = rotation.to_euler("XYZ", previous[index])
        previous[index] = euler

        pivot = mathutils.Vector(bone.position)
        # rotation is about the joint, and this leaves what the game adds
        offset = (delta @ pivot - pivot) / anim_scale

        frame.append(
            (
                math.degrees(euler.x),
                math.degrees(euler.y),
                math.degrees(euler.z),
                bone_scale.x,
                bone_scale.y,
                bone_scale.z,
                offset.x,
                offset.y,
                offset.z,
            )
        )
    return frame


def _fit_keys(frames, values, checks, channel: int, start: int):
    """Key indices the game's own reader reproduces the whole channel from"""
    # checked at half frames too, since that spline normalizes each span on its
    # own and can bulge between two whole ones
    if len(values) < 3:
        return list(range(len(values)))

    # a key can only sit on a whole frame. Each check blames the nearer one.
    nearest = [
        (time, wanted, min(range(len(frames)), key=lambda step: abs(frames[step] - time))) for time, wanted in checks
    ]

    chosen = {0, len(values) - 1}
    while len(chosen) < len(values):
        keys = [(1, 1, frames[index], values[index]) for index in sorted(chosen)]
        worst, at = 0.5, None
        for time, wanted, index in nearest:
            if index in chosen:
                continue
            error = abs(_value_at(start, channel, keys, time) * ANIM_FIXED_POINT - wanted)
            if error > worst:
                worst, at = error, index
        if at is None:
            break
        chosen.add(at)
    return sorted(chosen)


def _elements(bones, samples, frames, fine, include_rest: bool):
    """One element per animated channel, grouped by bone id"""
    # the game flushes a bone when the id changes. Its elements have to be
    # adjacent.
    elements = []
    for index, bone in enumerate(bones):
        for channel in range(ANIM_CHANNEL_COUNT):
            values = [_quantize(sample[index][channel], channel, bone.name) for sample in samples]
            default = _quantize(ANIM_CHANNEL_DEFAULTS[channel], channel, bone.name)
            if all(value == default for value in values):
                if not include_rest:
                    continue
                # a bone left out keeps whatever the last animation put there
                elements.append((bone.bone_id, channel, [(frames[0], default)]))
                continue
            checks = [(time, sample[index][channel] * ANIM_FIXED_POINT) for time, sample in fine]
            keys = _fit_keys(frames, values, checks, channel, frames[0])
            elements.append((bone.bone_id, channel, [(frames[key], values[key]) for key in keys]))

    elements.sort(key=lambda element: (element[0], element[1]))
    if len(elements) > ANIM_MAX_ELEMENTS:
        raise PluginError(f"This animation needs {len(elements)} elements, past the {ANIM_MAX_ELEMENTS} an s16 counts.")
    return elements


def _write_resource(start: int, end: int, elements):
    # not the runtime struct, the factory packs the bitfields on load
    data = otr_header(RT_BK_ANIM)
    data.extend(struct.pack("<hhI", start, end, len(elements)))
    for bone_id, channel, keys in elements:
        data.extend(struct.pack("<hhI", bone_id, channel, len(keys)))
        for frame, value in keys:
            # smooth at both ends like vanilla, or the game draws chords
            data.extend(struct.pack("<BBHh", 1, 1, frame, value))
    return bytes(data)


def _write_bin(start: int, end: int, elements):
    """The animation as the ROM holds it, the runtime struct big endian"""
    data = bytearray(struct.pack(">hhhh", start, end, len(elements), 0))
    for bone_id, channel, keys in elements:
        data.extend(struct.pack(">Hh", ((bone_id & 0xFFF) << 4) | (channel & 0xF), len(keys)))
        for frame, value in keys:
            data.extend(struct.pack(">Hh", (3 << 14) | (frame & ANIM_MAX_KEY_FRAME), value))
    return bytes(data)


def _read_animation(data: bytes):
    """(start, end, elements) out of a BKAN resource or a ROM .bin"""
    # an element is (bone id, channel, [(smooth next, smooth previous, frame, value)])
    if len(data) >= 0x40 and struct.unpack_from("<I", data, 4)[0] == RT_BK_ANIM:
        offset = 0x40
        start, end, count = struct.unpack_from("<hhI", data, offset)
        offset += 8
        elements = []
        for _element in range(count):
            bone_id, channel, key_count = struct.unpack_from("<hhI", data, offset)
            offset += 8
            keys = []
            for _key in range(key_count):
                smooth_next, smooth_previous, frame, value = struct.unpack_from("<BBHh", data, offset)
                offset += 6
                keys.append((smooth_next, smooth_previous, frame, value))
            elements.append((bone_id, channel, keys))
        return start, end, elements

    start, end, count, _pad = struct.unpack_from(">hhhh", data, 0)
    offset = 8
    elements = []
    for _element in range(count):
        packed, key_count = struct.unpack_from(">Hh", data, offset)
        offset += 4
        keys = []
        for _key in range(key_count):
            bits, value = struct.unpack_from(">Hh", data, offset)
            offset += 4
            keys.append(((bits >> 15) & 1, (bits >> 14) & 1, bits & ANIM_MAX_KEY_FRAME, value))
        elements.append((packed >> 4, packed & 0xF, keys))
    return start, end, elements


def _spline(between: float, knots):
    """Catmull-rom, clamping the interpolant first the way the game does"""
    between = min(1.0, max(0.0, between))
    third = -0.5 * knots[0] + 1.5 * knots[1] - 1.5 * knots[2] + 0.5 * knots[3]
    second = 1.0 * knots[0] - 2.5 * knots[1] + 2.0 * knots[2] - 0.5 * knots[3]
    first = -0.5 * knots[0] + 0.5 * knots[2]
    return ((third * between + second) * between + first) * between + knots[1]


def _value_at(start: int, channel: int, keys, time: float):
    """Linear between two plain keys, catmull-rom around a flagged one, as the game reads them"""
    first = keys[0]
    if int(time) < first[2]:
        knots = [ANIM_CHANNEL_DEFAULTS[channel]] * 2
        knots.append(first[3] / ANIM_FIXED_POINT)
        knots.append(keys[1][3] / ANIM_FIXED_POINT if first[0] == 1 and len(keys) >= 2 else knots[2])
        return _spline((time - start) / (first[2] - start), knots)

    last = keys[-1]
    if int(time) >= last[2]:
        value = last[3] / ANIM_FIXED_POINT
        previous = keys[-2][3] / ANIM_FIXED_POINT if last[1] == 1 and len(keys) >= 2 else value
        return _spline(time - last[2], [previous, value, value, value])

    low, high = 0, len(keys) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if keys[middle][2] <= int(time):
            low = middle
        else:
            high = middle

    before, after = keys[low], keys[high]
    between = (time - before[2]) / (after[2] - before[2])
    if before[1] == 0 and after[0] == 0:
        return before[3] / ANIM_FIXED_POINT + (after[3] - before[3]) / ANIM_FIXED_POINT * between

    knots = [0.0, before[3] / ANIM_FIXED_POINT, after[3] / ANIM_FIXED_POINT, 0.0]
    knots[0] = keys[low - 1][3] / ANIM_FIXED_POINT if before[1] == 1 and low >= 1 else knots[1]
    knots[3] = keys[high + 1][3] / ANIM_FIXED_POINT if after[0] == 1 and high + 1 < len(keys) else knots[2]
    return _spline(between, knots)


def import_bk64_animation(context, armature_obj, path: str, settings):
    # bones are addressed by id. The rig has to carry the ones it names.
    with open(path, "rb") as file:
        start, end, elements = _read_animation(file.read())
    if not elements:
        raise PluginError(f"'{os.path.basename(path)}' holds no animation channels.")

    to_bk = _to_bk(settings.scale)
    bones, _index_of_name = build_bone_table(armature_obj, to_bk)

    channels = {}
    for bone_id, channel, keys in elements:
        channels.setdefault(bone_id, {})[channel] = keys
    missing = sorted(set(channels) - {bone.bone_id for bone in bones})
    if missing:
        raise PluginError(
            f"'{os.path.basename(path)}' animates bone ids {missing}, which '{armature_obj.name}' "
            "doesn't have. Import that model's skeleton first."
        )

    armature_obj.animation_data_create()
    action = bpy.data.actions.new(os.path.basename(path))
    armature_obj.animation_data.action = action
    for pose_bone in armature_obj.pose.bones:
        pose_bone.rotation_mode = "XYZ"

    original_frame = context.scene.frame_current
    for offset in range(end - start + 1):
        time = float(start + offset)
        frame = 1 + offset
        context.scene.frame_set(frame)
        for bone in bones:
            keys = channels.get(bone.bone_id)
            if keys is None:
                continue
            values = [
                _value_at(start, channel, keys[channel], time) if channel in keys else ANIM_CHANNEL_DEFAULTS[channel]
                for channel in range(ANIM_CHANNEL_COUNT)
            ]

            pivot = mathutils.Vector(bone.position)
            translation = mathutils.Vector(values[ANIM_TRANSLATION : ANIM_TRANSLATION + 3]) * settings.anim_scale
            rotation = mathutils.Euler([math.radians(angle) for angle in values[:ANIM_SCALE]], "XYZ").to_matrix()
            delta = (
                mathutils.Matrix.Translation(pivot + translation)
                @ rotation.to_4x4()
                @ mathutils.Matrix.Diagonal(mathutils.Vector(values[ANIM_SCALE : ANIM_SCALE + 3])).to_4x4()
                @ mathutils.Matrix.Translation(-pivot)
            )

            rest = armature_obj.data.bones[bone.name].matrix_local
            pose_bone = armature_obj.pose.bones[bone.name]
            pose_bone.matrix_basis = rest.inverted() @ (to_bk.inverted() @ delta @ to_bk) @ rest
            pose_bone.keyframe_insert("location", frame=frame)
            pose_bone.keyframe_insert("rotation_euler", frame=frame)
            pose_bone.keyframe_insert("scale", frame=frame)
    context.scene.frame_set(original_frame)

    # every frame is keyed, and Blender's easing would invent a shape
    for curve in _action_fcurves(action):
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"

    return action, end - start + 1


def export_bk64_animation(context, armature_obj, settings):
    action = armature_obj.animation_data.action if armature_obj.animation_data else None
    if action is None:
        raise PluginError(
            f"'{armature_obj.name}' has no action. Make one in the Dope Sheet, or pick one in " "the Action Editor."
        )

    first, last = (round(value) for value in action.frame_range)
    if last <= first:
        raise PluginError(f"Action '{action.name}' covers a single frame, so there's nothing to play.")
    if last - first > ANIM_MAX_KEY_FRAME - 1:
        raise PluginError(
            f"Action '{action.name}' is {last - first} frames long. A key frame number is 14 bits, "
            f"so nothing can run past frame {ANIM_MAX_KEY_FRAME}."
        )

    # rotating the rig here would leave the pose matrices on the old rest, so
    # turn the delta instead
    to_bk = _to_bk(settings.scale)
    bones, _index_of_name = build_bone_table(armature_obj, to_bk)

    # frame numbers are the animation's own, and the game divides by end - start
    frames = list(range(1, last - first + 2))
    previous = [mathutils.Euler((0.0, 0.0, 0.0), "XYZ") for _bone in bones]

    original_frame = context.scene.frame_current
    samples, fine = [], []
    try:
        for offset in range(last - first + 1):
            # half frames too, the game reads between them
            for step in (0.0, 0.5) if offset < last - first else (0.0,):
                context.scene.frame_set(first + offset, subframe=step)
                evaluated = armature_obj.evaluated_get(context.evaluated_depsgraph_get())
                channels = _bone_channels(evaluated, bones, to_bk, settings.anim_scale, previous)
                fine.append((frames[offset] + step, channels))
                if step == 0.0:
                    samples.append(channels)
    finally:
        context.scene.frame_set(original_frame)

    elements = _elements(bones, samples, frames, fine, settings.anim_include_rest)
    if not elements:
        raise PluginError(f"Action '{action.name}' never moves a bone, it would export empty.")

    if settings.file_format == "BIN":
        return _write_bin(frames[0], frames[-1], elements)
    return _write_resource(frames[0], frames[-1], elements)
