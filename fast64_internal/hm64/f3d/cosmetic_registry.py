"""WeakKeyDictionary-based cosmetic metadata for DPSetPrimColor/DPSetEnvColor.

This avoids adding fields to upstream dataclasses (Option B).
hm64's material writer calls set_cosmetic() after constructing color commands.
The XML exporter calls get_cosmetic() to retrieve metadata.
"""

import weakref

_cosmetic_data: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def set_cosmetic(obj, entry: str = "", category: str = ""):
    _cosmetic_data[obj] = {"entry": entry, "category": category}


def get_cosmetic(obj) -> dict:
    return _cosmetic_data.get(obj, {"entry": "", "category": ""})


def clear():
    _cosmetic_data.clear()
