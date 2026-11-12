"""One-time compatibility patches for known pydcs 0.15.0 bugs that surface
when scanning a real, current DCS World installation (pydcs predates some
recent DCS content and has a couple of crash-on-KeyError bugs as a result).

Run once after `pip install -r requirements.txt`:
    python patch_pydcs.py

Safe to run multiple times - each patch checks whether it's already applied
before touching the file.
"""
from __future__ import annotations

from pathlib import Path

import dcs

DCS_DIR = Path(dcs.__file__).parent

PATCHES = [
    {
        "file": "liveries_scanner.py",
        "description": "livery country-list parsing crashes on Python 3.13+ (exec()/locals() no longer reliable)",
        "find": (
            'exec(f"country_list = {countries}")\n'
            "            countries = set(filter(lambda x: x != \"\", locals()['country_list']))"
        ),
        "replace": (
            "country_list = eval(countries)\n"
            "            countries = set(filter(lambda x: x != \"\", country_list))"
        ),
    },
    {
        "file": "unittype.py",
        "description": "aircraft payload scan crashes (KeyError) on payload files it couldn't parse a unitType from",
        "find": "if FlyingType._payload_cache[payload_path] == cls.id and payload_path.exists():",
        "replace": "if FlyingType._payload_cache.get(payload_path) == cls.id and payload_path.exists():",
    },
]


def main() -> None:
    for patch in PATCHES:
        path = DCS_DIR / patch["file"]
        if not path.is_file():
            print(f"SKIP  {patch['file']}: file not found (unexpected pydcs layout)")
            continue
        text = path.read_text(encoding="utf-8")
        if patch["replace"] in text:
            print(f"OK    {patch['file']}: already patched")
            continue
        if patch["find"] not in text:
            print(f"SKIP  {patch['file']}: expected code not found (pydcs version differs?) - {patch['description']}")
            continue
        path.write_text(text.replace(patch["find"], patch["replace"], 1), encoding="utf-8")
        print(f"PATCHED {patch['file']}: {patch['description']}")


if __name__ == "__main__":
    main()
