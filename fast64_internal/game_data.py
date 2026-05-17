import bpy

from typing import Optional


def _get_base_game(mode: str) -> str:
    """Resolve HM64 modes to their decomp base game (e.g. SOH→OOT, 2SHIP→MM)."""
    try:
        from .. import get_base_game
        return get_base_game(mode)
    except ImportError:
        return mode


class GameData:
    def __init__(self, game_editor_mode: Optional[str] = None):
        from .data import Z64_Data

        self.z64 = Z64_Data("OOT")

        if game_editor_mode is not None:
            self.update(game_editor_mode)

    def update(self, game_editor_mode: str):
        from .z64.utility import getObjectList

        base_game = _get_base_game(game_editor_mode)

        if base_game is not None and base_game in {"OOT", "MM"}:
            self.z64.update(None, base_game, True)

            # ensure `currentCutsceneIndex` is set to a correct value
            if base_game in {"OOT", "MM"}:
                for scene_obj in bpy.data.objects:
                    scene_obj.ootAlternateSceneHeaders.currentCutsceneIndex = game_data.z64.cs_index_start

                    if scene_obj.type == "EMPTY" and scene_obj.ootEmptyType == "Scene":
                        room_obj_list = getObjectList(scene_obj.children_recursive, "EMPTY", "Room")

                        for room_obj in room_obj_list:
                            room_obj.ootAlternateRoomHeaders.currentCutsceneIndex = game_data.z64.cs_index_start

            if base_game in {"OOT", "MM"} and base_game != self.z64.game:
                raise ValueError(f"ERROR: Z64 game mismatch: {base_game}, {game_data.z64.game}")


game_data = GameData()
