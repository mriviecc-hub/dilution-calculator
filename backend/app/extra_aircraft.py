"""Player-flyable DCS modules that are newer than the pinned pydcs release.

pydcs 0.15.0 ships a fixed table of aircraft classes. Modules released after
it (currently: Heatblur's F-14B(U), released 2026) simply aren't in that
table, so they can't be placed as a player slot no matter what we whitelist.

This module defines them as ordinary pydcs types so the rest of the app can
treat them like any other aircraft. Each one subclasses the closest existing
pydcs type, which is what makes this safe rather than guesswork: pylons,
tasks, dimensions and payload plumbing are inherited from a real, tested
class, and only the DCS unit-type `id` differs.

The `id` is the one thing that MUST match the string DCS itself uses, since
it's written verbatim into the .miz. Rather than hard-coding a guess, we
scan the local DCS installation's UnitPayloads files at import time (the
same files pydcs's own payload scanner reads) and adopt whatever id actually
matches - falling back to the documented default only when no install is
present (e.g. on a build machine or in CI, where it's never used to fly).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import dcs.planes as planes
from dcs.installation import get_dcs_install_directory

logger = logging.getLogger(__name__)

# unitType lines look like:  unitType = "F-14B(U)",
_UNIT_TYPE_RE = re.compile(r'unitType\s*=\s*"([^"]+)"')


def _scan_installed_unit_types() -> set[str]:
    """Every unit-type id declared by payload files in the local DCS install.

    Returns an empty set when DCS isn't installed or can't be located, which
    is the normal case off the player's machine.
    """
    try:
        install_dir = get_dcs_install_directory()
    except Exception:  # pragma: no cover - depends on a real Windows install
        return set()
    if not install_dir:
        return set()

    root = Path(install_dir)
    found: set[str] = set()
    # Third-party/ED modules live under Mods/aircraft/<Module>/UnitPayloads,
    # stock ones under CoreMods/aircraft/<Module>/UnitPayloads.
    for mods_dir in (root / "Mods" / "aircraft", root / "CoreMods" / "aircraft"):
        if not mods_dir.is_dir():
            continue
        for payload_file in mods_dir.glob("*/UnitPayloads/*.lua"):
            try:
                text = payload_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found.update(_UNIT_TYPE_RE.findall(text))
    return found


_INSTALLED_UNIT_TYPES = _scan_installed_unit_types()


def _resolve_unit_id(default_id: str, pattern: str) -> str:
    """Pick the real DCS unit id for a module, preferring what's installed.

    `default_id` is used as-is if we can't see a DCS install (nothing to
    check against) or if it's already present. Otherwise the first installed
    unit type matching `pattern` wins - this is what lets the app stay
    correct if ED/Heatblur ship a slightly different id string than expected.
    """
    if not _INSTALLED_UNIT_TYPES or default_id in _INSTALLED_UNIT_TYPES:
        return default_id
    rx = re.compile(pattern)
    for unit_type in sorted(_INSTALLED_UNIT_TYPES):
        if rx.match(unit_type):
            logger.info("Resolved %s -> installed DCS unit type %r", default_id, unit_type)
            return unit_type
    logger.warning(
        "No installed DCS unit type matched %r (pattern %r); using it as-is. "
        "If this module fails to load in DCS, its unit id differs from what this app expects.",
        default_id, pattern,
    )
    return default_id


class F_14B_U(planes.F_14B):
    """Heatblur F-14B(U) - the late-service 'Upgrade' Tomcat (2026).

    An expansion of the F-14A/B module rather than a separate airframe, so
    inheriting F_14B's pylons/tasks/dimensions is accurate. Note the added
    JDAM/GBU-31 capability isn't reflected in the inherited pylon options;
    that only affects preset loadouts, not whether the jet spawns correctly.
    """

    id = _resolve_unit_id("F-14B(U)", r"^F-14B[\s_(-]*U\)?$")
    flyable = True


# name -> class, for mission_builder's aircraft lookup and the whitelist.
EXTRA_PLAYER_AIRCRAFT: dict[str, type] = {
    "F_14B_U": F_14B_U,
}
