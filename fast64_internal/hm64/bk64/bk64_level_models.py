import os
import re

BK64_LEVEL_MODELS = {
    0x146B: ("TTC_TREASURE_TROVE_COVE", "OPA"),
    0x146C: ("TTC_TREASURE_TROVE_COVE", "XLU"),
    0x146D: ("TTC_NIPPERS_SHELL", "OPA"),
    0x146E: ("TTC_NIPPERS_SHELL", "XLU"),
    0x146F: ("TTC_BLUBBERS_SHIP", "OPA"),
    0x1470: ("TTC_BLUBBERS_SHIP", "XLU"),
    0x1471: ("TTC_SANDCASTLE", "OPA"),
    0x1472: ("TTC_SANDCASTLE", "XLU"),
    0x1473: ("TTC_SHARKFOOD_ISLAND", "OPA"),
    0x1474: ("GV_GOBIS_VALLEY", "OPA"),
    0x1475: ("GV_GOBIS_VALLEY", "XLU"),
    0x1476: ("GV_MEMORY_GAME", "OPA"),
    0x1478: ("GV_SANDYBUTTS_MAZE", "OPA"),
    0x1479: ("GV_SANDYBUTTS_MAZE", "XLU"),
    0x147A: ("GV_WATER_PYRAMIDS", "OPA"),
    0x147B: ("GV_WATER_PYRAMIDS", "XLU"),
    0x147C: ("GV_RUBEES_CHAMBER", "OPA"),
    0x147D: ("GV_INSIDE_JINXY", "OPA"),
    0x147E: ("GV_SNS_CHAMBER", "OPA"),
    0x147F: ("MMM_MAD_MONSTER_MANSION", "OPA"),
    0x1480: ("MMM_MAD_MONSTER_MANSION", "XLU"),
    0x1481: ("MMM_RAINBARREL", "OPA"),
    0x1482: ("MMM_CELLAR", "OPA"),
    0x1483: ("MMM_SECRET_CHURCH_ROOM", "OPA"),
    0x1484: ("MMM_SECRET_CHURCH_ROOM", "XLU"),
    0x1485: ("MMM_NAPPERS_ROOM", "OPA"),
    0x1486: ("MMM_CHURCH", "OPA"),
    0x1487: ("MMM_CHURCH", "XLU"),
    0x1488: ("MMM_TUMBLARS_SHED", "OPA"),
    0x1489: ("MMM_EGG_ROOM", "OPA"),
    0x148A: ("MMM_EGG_ROOM", "XLU"),
    0x148B: ("MMM_NOTE_ROOM", "OPA"),
    0x148C: ("MMM_NOTE_ROOM", "XLU"),
    0x148D: ("MMM_FEATHER_ROOM", "OPA"),
    0x148E: ("MMM_FEATHER_ROOM", "XLU"),
    0x148F: ("MMM_BATHROOM", "OPA"),
    0x1490: ("MMM_BATHROOM", "XLU"),
    0x1491: ("MMM_BEDROOM", "OPA"),
    0x1492: ("MMM_BEDROOM", "XLU"),
    0x1493: ("MMM_HONEYCOMB_ROOM", "OPA"),
    0x1494: ("MMM_HONEYCOMB_ROOM", "XLU"),
    0x1495: ("MMM_WELL", "OPA"),
    0x1496: ("MMM_WELL", "XLU"),
    0x1497: ("MMM_RAINBARREL", "XLU"),
    0x1498: ("MMM_INSIDE_LOGGO", "OPA"),
    0x1499: ("MMM_INSIDE_LOGGO", "XLU"),
    0x149A: ("MMM_NAPPERS_ROOM", "XLU"),
    0x149B: ("MMM_CELLAR", "XLU"),
    0x149D: ("CS_START_NINTENDO", "OPA"),
    0x149E: ("CS_START_RAREWARE", "OPA"),
    0x149F: ("CS_END_SPIRAL_MOUNTAIN", "OPA"),
    0x14A0: ("CS_START_RAREWARE", "XLU"),
    0x14A1: ("CS_START_NINTENDO", "XLU"),
    0x14A2: ("CS_BANJOS_HOUSE", "OPA"),
    0x14A3: ("CS_END_SPIRAL_MOUNTAIN", "XLU"),
    0x14A4: ("CS_BANJOS_HOUSE", "XLU"),
    0x14A5: ("CS_BEACH", "XLU"),
    0x14A6: ("CS_INTRO_SPIRAL_MOUNTAIN", "OPA"),
    0x14A8: ("GL_GV_LOBBY", "XLU"),
    0x14A9: ("CS_BEACH", "OPA"),
    0x14AA: ("MM_MUMBOS_MOUNTAIN", "OPA"),
    0x14AB: ("MM_MUMBOS_MOUNTAIN", "XLU"),
    0x14AC: ("MM_TICKERS_TOWER", "OPA"),
    0x14AD: ("MM_TICKERS_TOWER", "XLU"),
    0x14AE: ("MUMBOS_SKULL", "OPA"),
    0x14B0: ("RBB_RUSTY_BUCKET_BAY", "OPA"),
    0x14B1: ("RBB_RUSTY_BUCKET_BAY", "XLU"),
    0x14B2: ("RBB_ENGINE_ROOM", "OPA"),
    0x14B3: ("RBB_ENGINE_ROOM", "XLU"),
    0x14B4: ("RBB_WAREHOUSE", "OPA"),
    0x14B5: ("RBB_WAREHOUSE", "XLU"),
    0x14B6: ("RBB_BOATHOUSE", "OPA"),
    0x14B7: ("RBB_BOATHOUSE", "XLU"),
    0x14B8: ("RBB_CONTAINER_1", "OPA"),
    0x14B9: ("RBB_CONTAINER_2", "OPA"),
    0x14BA: ("RBB_CONTAINER_3", "OPA"),
    0x14BB: ("RBB_CAPTIANS_CABIN", "OPA"),
    0x14BC: ("RBB_CAPTIANS_CABIN", "XLU"),
    0x14BD: ("RBB_CREW_CABIN", "OPA"),
    0x14BE: ("RBB_BOSS_BOOM_BOX", "OPA"),
    0x14BF: ("RBB_BOSS_BOOM_BOX", "XLU"),
    0x14C0: ("RBB_NAVIGATION_ROOM", "OPA"),
    0x14C1: ("RBB_STORAGE_ROOM", "OPA"),
    0x14C2: ("RBB_STORAGE_ROOM", "XLU"),
    0x14C3: ("RBB_KITCHEN", "OPA"),
    0x14C4: ("RBB_KITCHEN", "XLU"),
    0x14C5: ("RBB_ANCHOR_ROOM", "OPA"),
    0x14C6: ("RBB_ANCHOR_ROOM", "XLU"),
    0x14C7: ("RBB_NAVIGATION_ROOM", "XLU"),
    0x14C8: ("FP_FREEZEEZY_PEAK", "OPA"),
    0x14C9: ("FP_FREEZEEZY_PEAK", "XLU"),
    0x14CA: ("FP_BOGGYS_IGLOO", "OPA"),
    0x14CB: ("FP_XMAS_TREE", "OPA"),
    0x14CC: ("FP_WOZZAS_CAVE", "OPA"),
    0x14CD: ("FP_WOZZAS_CAVE", "XLU"),
    0x14CE: ("FP_BOGGYS_IGLOO", "XLU"),
    0x14CF: ("SM_SPIRAL_MOUNTAIN", "OPA"),
    0x14D0: ("SM_SPIRAL_MOUNTAIN", "XLU"),
    0x14D1: ("BGS_BUBBLEGLOOP_SWAMP", "OPA"),
    0x14D2: ("BGS_BUBBLEGLOOP_SWAMP", "XLU"),
    0x14D3: ("BGS_MR_VILE", "OPA"),
    0x14D4: ("BGS_TIPTUP", "OPA"),
    0x14D5: ("BGS_TIPTUP", "XLU"),
    0x14D6: ("TEST_MAP", "OPA"),
    0x14D7: ("TEST_MAP", "XLU"),
    0x14D8: ("CCW_HUB", "OPA"),
    0x14D9: ("CCW_SPRING", "OPA"),
    0x14DA: ("CCW_SUMMER", "OPA"),
    0x14DB: ("CCW_AUTUMN", "OPA"),
    0x14DC: ("CCW_WINTER", "OPA"),
    0x14DD: ("CCW_ZUBBA_HIVE", "OPA"),
    0x14DE: ("CCW_NABNUTS_HOUSE", "OPA"),
    0x14DF: ("CCW_WHIPCRACK_ROOM", "OPA"),
    0x14E0: ("CCW_HONEYCOMB_ROOM", "OPA"),
    0x14E1: ("CCW_NABBUTS_STASH", "OPA"),
    0x14E2: ("CCW_NABBUTS_STASH", "XLU"),
    0x14E3: ("CCW_HUB", "XLU"),
    0x14E4: ("CCW_SPRING", "XLU"),
    0x14E5: ("CCW_SUMMER", "XLU"),
    0x14E6: ("CCW_AUTUMN", "XLU"),
    0x14E7: ("CCW_WINTER", "XLU"),
    0x14E8: ("GL_FURNACE_FUN", "OPA"),
    0x14ED: ("CC_CLANKERS_CAVERN", "OPA"),
    0x14EE: ("CC_CLANKERS_CAVERN", "XLU"),
    0x14EF: ("CC_WITCH_SWITCH_ROOM", "OPA"),
    0x14F0: ("CC_INSIDE_CLANKER", "OPA"),
    0x14F1: ("CC_INSIDE_CLANKER", "XLU"),
    0x14F2: ("CC_GOLD_FEATHER_ROOM", "OPA"),
    0x14F3: ("GL_MM_LOBBY", "OPA"),
    0x14F4: ("GL_TTC_AND_CC_PUZZLE", "OPA"),
    0x14F5: ("GL_180_NOTE_DOOR", "OPA"),
    0x14F6: ("GL_RED_CAULDRON_ROOM", "OPA"),
    0x14F7: ("GL_TTC_LOBBY", "OPA"),
    0x14F8: ("GL_GV_LOBBY", "OPA"),
    0x14F9: ("GL_FP_LOBBY", "OPA"),
    0x14FA: ("GL_FP_LOBBY", "XLU"),
    0x14FB: ("GL_CC_LOBBY", "OPA"),
    0x14FC: ("GL_BATTLEMENTS", "OPA"),
    0x14FD: ("GL_GV_PUZZLE", "OPA"),
    0x14FE: ("GL_MMM_LOBBY", "OPA"),
    0x14FF: ("GL_CRYPT", "OPA"),
    0x1500: ("GL_STATUE_ROOM", "OPA"),
    0x1501: ("GL_BGS_LOBBY", "OPA"),
    0x1502: ("GL_640_NOTE_DOOR", "OPA"),
    0x1503: ("GL_RBB_LOBBY", "OPA"),
    0x1504: ("RBB_AND_MMM_PUZZLE", "OPA"),
    0x1505: ("GL_CCW_LOBBY", "OPA"),
    0x1506: ("GL_FF_ENTRANCE", "OPA"),
    0x1507: ("GL_CC_LOBBY", "XLU"),
    0x1508: ("GL_640_NOTE_DOOR", "XLU"),
    0x1509: ("GL_RBB_LOBBY", "XLU"),
    0x150A: ("RBB_AND_MMM_PUZZLE", "XLU"),
    0x150B: ("GL_MM_LOBBY", "XLU"),
    0x150C: ("GL_TTC_AND_CC_PUZZLE", "XLU"),
    0x150D: ("GL_RED_CAULDRON_ROOM", "XLU"),
    0x150E: ("GL_STATUE_ROOM", "XLU"),
    0x150F: ("CS_KLUNGOS_LAB", "OPA"),
    0x1510: ("GL_180_NOTE_DOOR", "XLU"),
    0x1511: ("GL_BGS_LOBBY", "XLU"),
    0x1512: ("GL_TTC_LOBBY", "XLU"),
    0x1513: ("CS_KLUNGOS_LAB", "XLU"),
    0x1514: ("GL_FF_ENTRANCE", "XLU"),
    0x1515: ("GL_BATTLEMENTS", "XLU"),
}


def bk64_level_layers(level: str) -> dict:
    """The asset index per draw layer, e.g. {"OPA": 0x146B, "XLU": 0x146C}"""
    return {layer: index for index, (name, layer) in BK64_LEVEL_MODELS.items() if name == level}


def bk64_level_names() -> list:
    """Every level name once, in asset order"""
    seen = {}
    for _, (name, _layer) in sorted(BK64_LEVEL_MODELS.items()):
        seen[name] = None
    return list(seen)


def bk64_level_of_asset(path: str):
    """(level, half) when a file names a level model, else None"""
    stem = os.path.basename(path).split(".")[0]
    named = re.fullmatch(r"ASSET_([0-9A-Fa-f]{4})_.+", stem)  # an o2r resource
    if named is None and not re.fullmatch(r"[0-9A-Fa-f]{4}", stem):  # a decomp asset
        return None
    return BK64_LEVEL_MODELS.get(int(named.group(1) if named else stem, 16))


def bk64_level_half_paths(resource: str) -> dict:
    """{layer: resource path} for both halves, under vanilla's own names where it has them"""
    head, _, stem = resource.rpartition("/")
    stem = re.sub(r"_(OPA|XLU)$", "", stem)
    prefix = f"{head}/" if head else ""
    # a vanilla level's halves are separate assets, so the ids differ between them
    named = re.fullmatch(r"ASSET_[0-9A-Fa-f]{4}_(.+)", stem)
    vanilla = bk64_level_layers(named.group(1)) if named else {}
    paths = {}
    for layer in ("OPA", "XLU"):
        if layer in vanilla:
            paths[layer] = f"{prefix}ASSET_{vanilla[layer]:04X}_{named.group(1)}_{layer}"
        else:
            paths[layer] = f"{prefix}{stem}_{layer}"
    return paths
