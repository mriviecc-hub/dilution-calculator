"""Offline, keyword/regex-based mission parser - no LLM, no API key, no network.

Used automatically by the server when no Anthropic API key is configured.
Far less flexible than llm_parser.parse_prompt (it matches known phrases
rather than genuinely understanding the request), but it always produces a
valid MissionSpec by falling back to sensible defaults for anything it can't
confidently extract from the prompt text.

Not every entry in mission_spec.PLAYER_AIRCRAFT has a dedicated alias here -
every distinct aircraft *family* does (so no family is unreachable offline),
but picking out an exact sub-variant (e.g. "MB-339APAN" vs "MB-339A", or a
specific SA342 loadout variant) is left to the Claude parser. That's an
intentional scope boundary, not an oversight.
"""
from __future__ import annotations

import re

from .mission_spec import (
    ENEMY_AIR_UNITS,
    PLAYER_AIRCRAFT,
    THEATER_INFO,
    MissionSpec,
)

# --- Theater detection ---------------------------------------------------
THEATER_ALIASES: dict[str, list[str]] = {
    "TheChannel": ["english channel", "channel map", "the channel", "channel"],
    "Normandy": ["normandy", "d-day", "d day"],
    "Nevada": ["nevada", "las vegas", "nttr", "test and training range", "vegas"],
    "PersianGulf": ["persian gulf", "the gulf", "strait of hormuz", "hormuz", "uae", "dubai"],
    "Syria": ["syria"],
    "MarianaIslands": ["marianas", "mariana islands", "guam", "saipan", "tinian"],
    "Falklands": ["falklands", "falkland islands"],
    "Caucasus": ["caucasus"],
}
assert set(THEATER_ALIASES) == set(THEATER_INFO)

# Player-aircraft families that only make sense on a "wwii" era theater
# (Channel/Normandy) - everything else in PLAYER_AIRCRAFT_ALIASES is treated
# as "modern", except general aviation (Yak-52, Christen Eagle), which fits
# either era and is left searchable regardless of theater.
WWII_AIRCRAFT_KEYS = {
    "P_51D", "P_51D_30_NA", "TF_51D", "P_47D_30", "P_47D_30bl1", "P_47D_40",
    "Bf_109K_4", "FW_190D9", "FW_190A8",
    "SpitfireLFMkIX", "SpitfireLFMkIXCW", "MosquitoFBMkVI", "I_16",
}
ERA_AGNOSTIC_AIRCRAFT_KEYS = {"Yak_52", "Christen_Eagle_II"}

# --- Alias tables ------------------------------------------------------------
# Matching prefers the EARLIEST position in the text across ALL entries, and
# only breaks ties on the LONGEST pattern at that same position (see
# _find_alias). Earliest-position-wins means the first aircraft mentioned in
# a prompt is treated as the player's, even if a later mention is a longer
# string (e.g. "F-16s against a pair of MiG-29s" picks F-16 for the player,
# not MiG-29, even though "mig-29" is a longer pattern than "f-16"). The
# length tiebreak still means "a-10a" beats the shorter "a-10" it contains
# when both start at the same position.

PLAYER_AIRCRAFT_ALIASES: dict[str, list[str]] = {
    # Jets: modern / Cold War
    "F_16C_50": ["f-16c", "f16c", "f-16", "f16", "viper", "fighting falcon"],
    "FA_18C_hornet": ["f/a-18c", "fa-18c", "f/a-18", "fa-18", "f-18", "f18", "hornet"],
    "A_10C_2": ["a-10c ii", "a-10cii", "a-10c", "a10c", "a-10", "a10", "warthog", "thunderbolt ii", "hog"],
    "A_10A": ["a-10a", "a10a"],
    "AV8BNA": ["av-8b", "av8b", "harrier"],
    "F_14B_U": ["f-14b(u)", "f-14bu", "f14bu", "f-14b u", "tomcat upgrade", "upgraded tomcat"],
    "F_14B": ["f-14b", "f14b", "tomcat", "f-14", "f14"],
    "F_14A_135_GR": ["f-14a", "f14a"],
    "F_15C": ["f-15c", "f15c", "eagle", "f-15", "f15"],
    "M_2000C": ["mirage 2000", "mirage2000", "m-2000c", "m2000c", "mirage"],
    "JF_17": ["jf-17", "jf17", "thunder"],
    "Su_27": ["su-27", "su27", "flanker"],
    "Su_33": ["su-33", "su33", "flanker-d", "sea flanker"],
    "Su_25T": ["su-25t", "su25t", "frogfoot"],
    "Su_25": ["su-25", "su25"],
    "MiG_29S": ["mig-29s", "mig29s", "mig-29", "mig29", "fulcrum"],
    "MiG_29A": ["mig-29a", "mig29a"],
    "MiG_29G": ["mig-29g", "mig29g"],
    "MiG_21Bis": ["mig-21", "mig21", "fishbed"],
    "MiG_19P": ["mig-19", "mig19", "farmer"],
    "MiG_15bis": ["mig-15", "mig15"],
    "Mirage_F1CE": ["mirage f1", "mirage-f1", "mirage f-1", "f1ce"],
    "Mirage_F1EE": ["mirage f1ee", "f1ee"],
    "F_5E_3": ["f-5e", "f5e", "f-5", "f5", "tiger ii", "tiger 2"],
    "F_86F_Sabre": ["f-86", "f86", "sabre"],
    # Jet trainers / light attack
    "L_39C": ["l-39c", "l39c", "albatros", "l-39", "l39"],
    "L_39ZA": ["l-39za", "l39za"],
    "C_101EB": ["c-101eb", "c101eb", "aviojet"],
    "C_101CC": ["c-101cc", "c101cc"],
    "MB_339A": ["mb-339", "mb339", "macchi"],
    "MB_339APAN": ["mb-339apan", "frecce tricolori"],
    "Hawk": ["bae hawk", "hawk t", "hawk trainer", "hawk"],
    "AJS37": ["viggen", "ajs37", "ajs-37", "aj37", "aj-37"],
    # Helicopters
    "Ka_50": ["ka-50", "ka50", "black shark", "blackshark", "werewolf"],
    "Ka_50_3": ["ka-50 iii", "ka-50iii", "black shark 3"],
    "Mi_8MT": ["mi-8", "mi8", "hip"],
    "Mi_24P": ["mi-24", "mi24", "hind"],
    "UH_1H": ["uh-1", "uh1", "huey"],
    "AH_64D_BLK_II": ["ah-64", "ah64", "apache"],
    "SA342M": ["gazelle", "sa342m", "sa-342", "sa342"],
    "SA342L": ["sa342l"],
    "SA342Mistral": ["gazelle mistral", "sa342 mistral", "sa342mistral"],
    "SA342Minigun": ["gazelle minigun", "sa342 minigun", "sa342minigun"],
    # WWII / warbirds
    "P_51D": ["p-51d", "p51d", "mustang", "p-51", "p51"],
    "P_51D_30_NA": ["p-51d-30", "p51d30"],
    "TF_51D": ["tf-51", "tf51", "mustang trainer"],
    "P_47D_30": ["p-47d-30", "p-47", "p47", "thunderbolt", "jug"],
    "P_47D_30bl1": ["p-47d-30 bl", "p47d30bl1"],
    "P_47D_40": ["p-47d-40", "p47d40"],
    "Bf_109K_4": ["bf-109", "bf109", "bf 109", "messerschmitt"],
    "FW_190D9": ["fw-190d", "fw190d", "dora"],
    "FW_190A8": ["fw-190a", "fw190a", "fw-190", "fw190", "focke-wulf"],
    "SpitfireLFMkIX": ["spitfire", "spit mk ix", "spitfire mk ix", "spitfire ix"],
    "SpitfireLFMkIXCW": ["spitfire cw", "spitfire clipped wing"],
    "MosquitoFBMkVI": ["mosquito", "mossie"],
    "I_16": ["i-16", "i16", "rata"],
    # General aviation
    "Yak_52": ["yak-52", "yak52"],
    "Christen_Eagle_II": ["christen eagle", "aerobatic biplane"],
}

MODERN_ENEMY_AIRCRAFT_ALIASES: dict[str, list[str]] = {
    "MiG_31": ["mig-31", "mig31", "foxhound"],
    "Su_33": ["su-33", "su33", "flanker-d", "flanker d"],
    "J_11A": ["j-11", "j11"],
    "F_5E_3": ["f-5", "f5", "tiger ii", "tiger 2", "aggressor"],
    "Su_27": ["su-27", "su27", "flanker"],
    "MiG_29S": ["mig-29", "mig29", "fulcrum"],
}
WWII_ENEMY_AIRCRAFT_ALIASES: dict[str, list[str]] = {
    "Bf_109K_4": PLAYER_AIRCRAFT_ALIASES["Bf_109K_4"],
    "FW_190D9": PLAYER_AIRCRAFT_ALIASES["FW_190D9"],
    "FW_190A8": PLAYER_AIRCRAFT_ALIASES["FW_190A8"],
}
assert set(MODERN_ENEMY_AIRCRAFT_ALIASES) | set(WWII_ENEMY_AIRCRAFT_ALIASES) <= set(ENEMY_AIR_UNITS)
assert set(PLAYER_AIRCRAFT_ALIASES) <= set(PLAYER_AIRCRAFT)

STRIKE_PROFILE_KEYWORDS: dict[str, list[str]] = {
    "sam_site": ["sam site", "sam", "air defense", "air defence", "missile site"],
    "depot": ["depot", "supply", "warehouse", "logistics"],
    "convoy": ["convoy", "trucks", "truck column", "column"],
}

CAP_KEYWORDS = ["cap", "intercept", "patrol", "dogfight", "air-to-air", "air to air", "fighter sweep"]
STRIKE_KEYWORDS = [
    "strike", "bomb", "bombing", "destroy", "attack", "cas",
    "close air support", "ground attack", "convoy", "depot", "sam site",
]

NUMBER_WORDS = {
    "one": 1, "single": 1, "solo": 1,
    "two": 2, "pair": 2, "couple": 2,
    "three": 3, "trio": 3,
    "four": 4, "flight of four": 4,
}

TIME_KEYWORDS: dict[str, list[str]] = {
    "dawn": ["dawn", "sunrise", "early morning"],
    "dusk": ["dusk", "sunset", "evening"],
    "night": ["night", "midnight", "nighttime"],
    "day": ["day", "daytime", "noon", "morning", "afternoon"],
}

WEATHER_KEYWORDS: dict[str, list[str]] = {
    "snowy": ["snow", "snowy", "snowing", "blizzard", "wintry"],
    "rainy": ["rain", "rainy", "raining", "storm", "stormy", "thunderstorm", "downpour", "wet"],
    "windy": ["windy", "gusty", "strong wind", "high wind", "gale", "blustery"],
    "cloudy": ["cloudy", "overcast", "partly cloudy", "cloud", "foggy", "fog"],
    "clear": ["clear", "sunny", "clear skies", "fair", "fine"],
}

STRIKE_PROFILE_DISPLAY = {
    "convoy": "vehicle convoy",
    "sam_site": "SAM site",
    "depot": "supply depot",
}

# Canonical human-readable names for aircraft ids. Used for the generated
# briefing text here, and served by /options so the desktop app's aircraft
# dropdown shows real module names instead of raw pydcs class ids.
DISPLAY_NAMES = {
    "F_16C_50": "F-16C", "FA_18C_hornet": "F/A-18C", "A_10C_2": "A-10C II",
    "A_10C": "A-10C", "A_10A": "A-10A", "AV8BNA": "AV-8B Harrier",
    "F_14B": "F-14B Tomcat", "F_14A_135_GR": "F-14A Tomcat",
    "F_14B_U": "F-14B(U) Tomcat",
    "F_15C": "F-15C", "M_2000C": "Mirage 2000C", "JF_17": "JF-17",
    "Su_27": "Su-27", "Su_33": "Su-33", "Su_25T": "Su-25T", "Su_25": "Su-25",
    "MiG_29S": "MiG-29S", "MiG_29A": "MiG-29A", "MiG_29G": "MiG-29G",
    "MiG_21Bis": "MiG-21bis", "MiG_19P": "MiG-19P", "MiG_15bis": "MiG-15bis",
    "Mirage_F1CE": "Mirage F1CE", "Mirage_F1EE": "Mirage F1EE",
    "F_5E_3": "F-5E", "F_86F_Sabre": "F-86F Sabre",
    "L_39C": "L-39C Albatros", "L_39ZA": "L-39ZA Albatros",
    "C_101EB": "C-101EB Aviojet", "C_101CC": "C-101CC Aviojet",
    "MB_339A": "MB-339A", "MB_339APAN": "MB-339APAN",
    "Hawk": "BAE Hawk T.1", "AJS37": "AJS 37 Viggen",
    "Ka_50": "Ka-50 Black Shark", "Ka_50_3": "Ka-50 III",
    "Mi_8MT": "Mi-8MTV2 Hip", "Mi_24P": "Mi-24P Hind",
    "UH_1H": "UH-1H Huey", "AH_64D_BLK_II": "AH-64D Apache",
    "SA342M": "SA342M Gazelle", "SA342L": "SA342L Gazelle",
    "SA342Mistral": "SA342 Gazelle (Mistral)", "SA342Minigun": "SA342 Gazelle (Minigun)",
    "P_51D": "P-51D Mustang", "P_51D_30_NA": "P-51D-30 Mustang",
    "TF_51D": "TF-51D Mustang", "P_47D_30": "P-47D-30 Thunderbolt",
    "P_47D_30bl1": "P-47D-30 Thunderbolt", "P_47D_40": "P-47D-40 Thunderbolt",
    "Bf_109K_4": "Bf 109 K-4", "FW_190D9": "Fw 190 D-9", "FW_190A8": "Fw 190 A-8",
    "SpitfireLFMkIX": "Spitfire LF Mk IX", "SpitfireLFMkIXCW": "Spitfire LF Mk IX (CW)",
    "MosquitoFBMkVI": "Mosquito FB Mk VI", "I_16": "I-16",
    "Yak_52": "Yak-52", "Christen_Eagle_II": "Christen Eagle II",
    "MiG_31": "MiG-31", "J_11A": "J-11A",
}

class RuleParseError(Exception):
    pass


def _find_alias(text: str, aliases: dict[str, list[str]]) -> tuple[str, str] | None:
    """Returns (canonical, matched_pattern) for the best matching pattern
    across ALL entries, preferring (in order): the EARLIEST position in the
    text, then the LONGEST pattern at that position.

    Position-first matters because prompts routinely mention more than one
    aircraft family ("F-16s against a pair of MiG-29s") - the first one
    mentioned is overwhelmingly the player's aircraft, the rest are
    someone/something else. Length-as-tiebreak still makes a same-position
    match like "a-10a" beat the shorter "a-10" it contains.
    """
    matches = []
    for canonical, patterns in aliases.items():
        for pattern in patterns:
            idx = text.find(pattern)
            if idx != -1:
                matches.append((idx, -len(pattern), canonical, pattern))
    if not matches:
        return None
    matches.sort()
    _, _, canonical, pattern = matches[0]
    return canonical, pattern


def _find_count_near(text: str, alias: str) -> int | None:
    idx = text.find(alias)
    if idx == -1:
        return None
    window = text[max(0, idx - 25):idx]
    for word, value in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in window:
            return value
    m = re.search(r"([1-4])\s*x?\s*$", window)
    return int(m.group(1)) if m else None


def _find_airport(text: str, candidates: list[str]) -> str | None:
    for airport in candidates:
        key = airport.split("-")[0].lower()
        if key in text or airport.lower() in text:
            return airport
    return None


def _find_first_keyword(text: str, keyword_map: dict[str, list[str]]) -> str | None:
    for value, keywords in keyword_map.items():
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in text:
                return value
    return None


def _find_theater(text: str) -> str:
    for theater, aliases in THEATER_ALIASES.items():
        if theater == "Caucasus":
            continue  # fallback default; checked last so it can't shadow a real match
        if any(a in text for a in aliases):
            return theater
    return "Caucasus"


def parse_prompt_rule_based(
    user_prompt: str,
    *,
    forced_theater: str | None = None,
    forced_player_aircraft: str | None = None,
    forced_time_of_day: str | None = None,
    forced_weather: str | None = None,
) -> MissionSpec:
    """Parse a prompt into a MissionSpec offline.

    The optional forced_* arguments come from the UI's dropdowns (each left
    on "Auto" is None) and pin a field regardless of the prompt text. Passing
    forced_theater in particular is what lets the theater's era cascade into
    the right defaults (e.g. forcing Normandy with no aircraft named still
    yields a Spitfire vs Bf-109, not an F-16 vs MiG-29).
    """
    text = user_prompt.lower()

    theater = forced_theater or _find_theater(text)
    info = THEATER_INFO[theater]
    era = info["era"]

    is_strike = any(kw in text for kw in STRIKE_KEYWORDS)
    is_cap = any(kw in text for kw in CAP_KEYWORDS)
    mission_type = "STRIKE" if is_strike and not is_cap else "CAP"

    if era == "wwii":
        player_aliases = {
            k: v for k, v in PLAYER_AIRCRAFT_ALIASES.items()
            if k in WWII_AIRCRAFT_KEYS or k in ERA_AGNOSTIC_AIRCRAFT_KEYS
        }
        default_player_aircraft = "SpitfireLFMkIX"
    else:
        player_aliases = {k: v for k, v in PLAYER_AIRCRAFT_ALIASES.items() if k not in WWII_AIRCRAFT_KEYS}
        default_player_aircraft = "F_16C_50"

    player_hit = _find_alias(text, player_aliases)
    player_aircraft = forced_player_aircraft or (player_hit[0] if player_hit else default_player_aircraft)
    # Count is read from whatever aircraft the prompt names, across BOTH eras -
    # so "two F-16s" still yields 2 even when the UI forces a different (e.g.
    # WWII) aircraft that the era-filtered alias set above wouldn't have matched.
    count_hit = _find_alias(text, PLAYER_AIRCRAFT_ALIASES)
    player_aircraft_count = (
        _find_count_near(text, count_hit[1]) if count_hit else None
    ) or 1

    home_airport = _find_airport(text, info["blue_airports"]) or info["blue_airports"][0]
    target_airport = _find_airport(text, info["blue_airports"] + info["red_airports"])
    if target_airport is None or target_airport == home_airport:
        target_airport = next((ap for ap in info["red_airports"] if ap != home_airport), info["red_airports"][0])

    time_of_day = forced_time_of_day or _find_first_keyword(text, TIME_KEYWORDS) or "day"
    weather = forced_weather or _find_first_keyword(text, WEATHER_KEYWORDS) or "clear"

    enemy_air_unit = None
    enemy_air_count = 2
    strike_target_profile = None

    enemy_aliases = MODERN_ENEMY_AIRCRAFT_ALIASES if era == "modern" else WWII_ENEMY_AIRCRAFT_ALIASES
    default_enemy_air_unit = "MiG_29S" if era == "modern" else "Bf_109K_4"

    if mission_type == "CAP":
        enemy_hit = _find_alias(text, enemy_aliases)
        if enemy_hit is None:
            enemy_air_unit = default_enemy_air_unit
        else:
            enemy_air_unit, enemy_pattern = enemy_hit
            enemy_air_count = _find_count_near(text, enemy_pattern) or 2
    else:
        strike_target_profile = _find_first_keyword(text, STRIKE_PROFILE_KEYWORDS) or "convoy"

    player_display = DISPLAY_NAMES.get(player_aircraft, player_aircraft)
    if mission_type == "CAP":
        enemy_display = DISPLAY_NAMES.get(enemy_air_unit, enemy_air_unit)
        title = f"CAP near {target_airport}"
        briefing = (
            f"{player_aircraft_count}x {player_display} flying CAP out of {home_airport} "
            f"against {enemy_air_count}x {enemy_display} operating near {target_airport}."
        )
    else:
        profile_display = STRIKE_PROFILE_DISPLAY.get(strike_target_profile, strike_target_profile)
        title = f"Strike on {target_airport}"
        briefing = (
            f"{player_aircraft_count}x {player_display} tasked to destroy a {profile_display} "
            f"near {target_airport}, launching from {home_airport}."
        )

    spec = MissionSpec(
        title=title,
        briefing=briefing,
        theater=theater,
        player_country=info["default_blue_country"],
        enemy_country=info["default_red_country"],
        mission_type=mission_type,
        player_aircraft=player_aircraft,
        player_aircraft_count=min(max(player_aircraft_count, 1), 4),
        home_airport=home_airport,
        target_airport=target_airport,
        enemy_air_unit=enemy_air_unit,
        enemy_air_count=min(max(enemy_air_count, 1), 4),
        strike_target_profile=strike_target_profile,
        time_of_day=time_of_day,
        weather=weather,
    )
    spec.validate_whitelists()
    return spec
