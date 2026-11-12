"""Structured mission specification.

This is the contract between the natural-language parser (llm_parser.py) and
the pydcs mission builder (mission_builder.py). Every field that maps to a
concrete DCS asset (aircraft, vehicle, airport) is restricted to a whitelist
so the builder never has to guess at, or fail on, a hallucinated unit name.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Whitelists -------------------------------------------------------------
# Kept intentionally small for v1 (Caucasus / Blue / CAP & Strike). Extend as
# more theaters and mission types come online.

# Every currently player-flyable DCS module pydcs 0.15.0 knows about (its own
# `flyable` flag on each unit type - the authoritative source of truth this
# app can act on, since attempting to place a non-flyable type as a Client
# slot raises a hard error in pydcs). This means a handful of real, released
# DCS modules pydcs hasn't been updated to mark flyable yet (e.g. F-15E,
# F-4E, F-117A, AH-64D (non-Block II), Tornado, Tu-22M3, B-52H, MiG-23MLD)
# aren't selectable here - see README's Troubleshooting section if you hit
# a "not human flyable" error for a module you believe should work.
PLAYER_AIRCRAFT = [
    # --- Jets: modern / Cold War -----------------------------------------
    "F_16C_50", "FA_18C_hornet", "A_10C_2", "A_10C", "A_10A", "AV8BNA",
    "F_14B", "F_14A_135_GR", "F_15C", "M_2000C", "JF_17",
    "Su_27", "Su_33", "Su_25T", "Su_25",
    "MiG_29S", "MiG_29A", "MiG_29G", "MiG_21Bis", "MiG_19P", "MiG_15bis",
    "Mirage_F1CE", "Mirage_F1EE",
    "F_5E_3", "F_86F_Sabre",
    # --- Jet trainers / light attack -------------------------------------
    "L_39C", "L_39ZA", "C_101EB", "C_101CC", "MB_339A", "MB_339APAN", "Hawk", "AJS37",
    # --- Helicopters -------------------------------------------------------
    "Ka_50", "Ka_50_3", "Mi_8MT", "Mi_24P", "UH_1H", "AH_64D_BLK_II",
    "SA342M", "SA342L", "SA342Mistral", "SA342Minigun",
    # --- WWII / warbirds ----------------------------------------------------
    "P_51D", "P_51D_30_NA", "TF_51D", "P_47D_30", "P_47D_30bl1", "P_47D_40",
    "Bf_109K_4", "FW_190D9", "FW_190A8",
    "SpitfireLFMkIX", "SpitfireLFMkIXCW", "MosquitoFBMkVI", "I_16",
    # --- General aviation ---------------------------------------------------
    "Yak_52", "Christen_Eagle_II",
    # --- Modules newer than pydcs 0.15.0 (see extra_aircraft.py) ------------
    "F_14B_U",
]

# Air-to-air adversary pools, split by era so a CAP mission on a WWII map
# (Channel/Normandy) gets a period-correct fighter instead of a modern jet.
# Every entry is a real pydcs aircraft class (same ground-truth rule as
# PLAYER_AIRCRAFT above) - MiG-29/Su-27/etc. aren't flyable-only, they're
# perfectly valid AI-only types too.
MODERN_ENEMY_AIR_UNITS = ["MiG_29S", "MiG_29A", "Su_27", "Su_33", "MiG_31", "J_11A", "F_5E_3"]
WWII_ENEMY_AIR_UNITS = ["Bf_109K_4", "FW_190D9", "FW_190A8"]
ENEMY_AIR_UNITS_BY_ERA = {"modern": MODERN_ENEMY_AIR_UNITS, "wwii": WWII_ENEMY_AIR_UNITS}
# Combined whitelist backing the EnemyAirUnit Literal below - covers both
# eras so the schema itself doesn't need to vary per theater; validate_whitelists()
# checks that the chosen unit actually matches the chosen theater's era.
ENEMY_AIR_UNITS = MODERN_ENEMY_AIR_UNITS + WWII_ENEMY_AIR_UNITS

# Named ground-target compositions for STRIKE missions, one set per era.
# Each profile is a list of "groups" to place around the target point; each
# group's exact vehicle type and unit count is randomized at build time
# (mission_builder's _random_strike_groups) from the given pool/range, so no
# two generations of the same profile look identical. All pool entries are
# real pydcs vehicle class names (dcs.vehicles.Armor / .AirDefence / .Unarmed).
# Both eras define the same profile *names* (convoy/sam_site/depot) so
# strike_target_profile stays theater-independent - only the pools differ.
MODERN_STRIKE_TARGET_PROFILES: dict[str, list[dict]] = {
    "convoy": [
        {"pool": ["Ural_375", "KAMAZ_Truck", "GAZ_3307", "GAZ_66"], "count_range": (3, 5)},
        {"pool": ["ZSU_23_4_Shilka", "Strela_10M3", "ZU_23_Emplacement"], "count_range": (1, 2)},
    ],
    "sam_site": [
        {"pool": ["Osa_9A33_ln", "Tor_9A331", "Strela_10M3"], "count_range": (1, 1)},
        {"pool": ["ZSU_23_4_Shilka", "Vulcan", "ZU_23_Emplacement"], "count_range": (1, 2)},
        {"pool": ["Ural_375"], "count_range": (1, 1)},
    ],
    "depot": [
        {"pool": ["Ural_375", "KAMAZ_Truck", "GAZ_3307", "ATZ_10"], "count_range": (5, 8)},
        {"pool": ["ZSU_23_4_Shilka", "ZU_23_Emplacement"], "count_range": (0, 1)},
    ],
}
WWII_STRIKE_TARGET_PROFILES: dict[str, list[dict]] = {
    "convoy": [
        {"pool": ["Blitz_36_6700A", "Kubelwagen_82", "Horch_901_typ_40_kfz_21"], "count_range": (3, 5)},
        {"pool": ["Flak38", "Flak36"], "count_range": (1, 2)},
    ],
    "sam_site": [  # no SAMs existed in WWII - reuses this profile name for a flak/AAA site
        {"pool": ["Flak36", "Flak37", "Flak41"], "count_range": (1, 2)},
        {"pool": ["Flakscheinwerfer_37"], "count_range": (0, 1)},
        {"pool": ["Kubelwagen_82"], "count_range": (1, 1)},
    ],
    "depot": [
        {"pool": ["Blitz_36_6700A", "Horch_901_typ_40_kfz_21", "Kubelwagen_82"], "count_range": (5, 8)},
        {"pool": ["Flak38"], "count_range": (0, 1)},
    ],
}
STRIKE_TARGET_PROFILES_BY_ERA = {"modern": MODERN_STRIKE_TARGET_PROFILES, "wwii": WWII_STRIKE_TARGET_PROFILES}
assert MODERN_STRIKE_TARGET_PROFILES.keys() == WWII_STRIKE_TARGET_PROFILES.keys()
# Kept as the canonical name (existing callers just want the profile *names*,
# identical across eras) - use STRIKE_TARGET_PROFILES_BY_ERA for the pools.
STRIKE_TARGET_PROFILES = MODERN_STRIKE_TARGET_PROFILES

# Reinforcement-group pools STRIKE missions spawn once the target takes
# losses (see mission_builder._spawn_qrf / strike_dynamic.lua.tmpl), by era.
MODERN_STRIKE_QRF_POOL = ["BTR_80", "BMP_2", "ZSU_23_4_Shilka", "Strela_10M3"]
WWII_STRIKE_QRF_POOL = ["Elefant_SdKfz_184", "JagdPz_IV", "Jagdpanther_G1"]
STRIKE_QRF_POOL_BY_ERA = {"modern": MODERN_STRIKE_QRF_POOL, "wwii": WWII_STRIKE_QRF_POOL}
STRIKE_QRF_POOL = MODERN_STRIKE_QRF_POOL

# Caucasus airfields, split roughly by traditional faction friendliness for
# sane defaults. The builder validates against pydcs's own terrain object too.
CAUCASUS_BLUE_AIRPORTS = [
    "Kobuleti", "Senaki-Kolkhi", "Batumi", "Kutaisi", "Tbilisi-Lochini",
]
CAUCASUS_RED_AIRPORTS = [
    "Anapa-Vityazevo", "Krasnodar-Center", "Krasnodar-Pashkovsky", "Sochi-Adler",
    "Maykop-Khanskaya", "Gelendzhik", "Novorossiysk", "Krymsk", "Gudauta", "Sukhumi-Babushara",
]
ALL_CAUCASUS_AIRPORTS = CAUCASUS_BLUE_AIRPORTS + CAUCASUS_RED_AIRPORTS

# --- Theaters -----------------------------------------------------------
# All 8 terrains pydcs 0.15.0 knows how to build (dcs.terrain.<key>()). Each
# entry's airport lists are real airfield names pulled directly from pydcs's
# own terrain data (same ground-truth approach as PLAYER_AIRCRAFT) - a
# reasonably-sized, recognizable subset per side rather than the map's full
# airport list, matching how Caucasus was originally scoped. "era" picks
# which ENEMY_AIR_UNITS/STRIKE_TARGET_PROFILES/STRIKE_QRF_POOL pool
# mission_builder reaches for, so WWII maps get period-correct opposition
# instead of modern jets and trucks.
THEATERS = ["Caucasus", "TheChannel", "Nevada", "Normandy", "PersianGulf", "Syria", "MarianaIslands", "Falklands"]

THEATER_INFO: dict[str, dict] = {
    "Caucasus": {
        "era": "modern",
        "blue_airports": CAUCASUS_BLUE_AIRPORTS,
        "red_airports": CAUCASUS_RED_AIRPORTS,
        "blue_countries": ["USA", "UK", "Germany", "France", "Israel", "Georgia"],
        "red_countries": ["Russia", "USAFAggressors"],
        "default_blue_country": "USA",
        "default_red_country": "Russia",
    },
    "TheChannel": {
        "era": "wwii",
        "blue_airports": ["Biggin Hill", "Detling", "Eastchurch", "Hawkinge", "Headcorn", "High Halden", "Lympne", "Manston"],
        "red_airports": ["Abbeville Drucat", "Dunkirk Mardyck", "Merville Calonne", "Saint Omer Longuenesse"],
        "blue_countries": ["UK", "USA", "France"],
        "red_countries": ["ThirdReich"],
        "default_blue_country": "UK",
        "default_red_country": "ThirdReich",
    },
    "Normandy": {
        "era": "wwii",
        "blue_airports": ["Chailey", "Ford_AF", "Funtington", "Needs Oar Point", "Tangmere"],
        "red_airports": [
            "Carpiquet", "Maupertus", "Lessay", "Cricqueville-en-Bessin",
            "Sainte-Croix-sur-Mer", "Longues-sur-Mer", "Picauville", "Beuzeville",
        ],
        "blue_countries": ["UK", "USA", "France"],
        "red_countries": ["ThirdReich"],
        "default_blue_country": "UK",
        "default_red_country": "ThirdReich",
    },
    "Nevada": {
        "era": "modern",
        "blue_airports": ["Nellis", "McCarran International", "North Las Vegas", "Creech", "Boulder City", "Henderson Executive"],
        "red_airports": [
            "Groom Lake", "Tonopah", "Tonopah Test Range", "Pahute Mesa",
            "Beatty", "Mina", "Echo Bay", "Mesquite", "Lincoln County", "Laughlin", "Jean",
        ],
        "blue_countries": ["USA"],
        "red_countries": ["USAFAggressors"],
        "default_blue_country": "USA",
        "default_red_country": "USAFAggressors",
    },
    "PersianGulf": {
        "era": "modern",
        "blue_airports": [
            "Abu Dhabi Intl", "Al Dhafra AFB", "Dubai Intl", "Sharjah Intl",
            "Al Minhad AFB", "Fujairah Intl", "Al Maktoum Intl", "Ras Al Khaimah Intl",
        ],
        "red_airports": [
            "Bandar Abbas Intl", "Bandar Lengeh", "Bandar-e-Jask", "Havadarya",
            "Jiroft", "Kerman", "Kish Intl", "Lar", "Shiraz Intl", "Qeshm Island",
        ],
        "blue_countries": ["USA", "UK"],
        "red_countries": ["Iran"],
        "default_blue_country": "USA",
        "default_red_country": "Iran",
    },
    "Syria": {
        "era": "modern",
        "blue_airports": ["Ramat David", "Haifa", "Megiddo", "Rosh Pina", "Kiryat Shmona", "Incirlik", "Akrotiri"],
        "red_airports": [
            "Damascus", "Mezzeh", "Aleppo", "Hama", "Shayrat", "Tiyas",
            "Bassel Al-Assad", "Palmyra", "Taftanaz", "Deir ez-Zor",
        ],
        "blue_countries": ["USA", "Israel"],
        "red_countries": ["Syria"],
        "default_blue_country": "Israel",
        "default_red_country": "Syria",
    },
    "MarianaIslands": {
        "era": "modern",
        "blue_airports": ["Andersen AFB", "Antonio B. Won Pat Intl", "North West Field", "Olf Orote"],
        "red_airports": ["Saipan Intl", "Tinian Intl", "Rota Intl", "Pagan Airstrip"],
        "blue_countries": ["USA"],
        "red_countries": ["Japan"],
        "default_blue_country": "USA",
        "default_red_country": "Japan",
    },
    "Falklands": {
        "era": "modern",
        "blue_airports": ["Port Stanley", "Mount Pleasant", "San Carlos FOB", "Goose Green", "Gull Point"],
        "red_airports": ["Rio Grande", "Rio Gallegos", "San Julian", "Comandante Luis Piedrabuena", "El Calafate"],
        "blue_countries": ["UK"],
        "red_countries": ["Argentina"],
        "default_blue_country": "UK",
        "default_red_country": "Argentina",
    },
}
assert set(THEATER_INFO.keys()) == set(THEATERS)

ALL_BLUE_COUNTRIES = sorted({c for info in THEATER_INFO.values() for c in info["blue_countries"]})
ALL_RED_COUNTRIES = sorted({c for info in THEATER_INFO.values() for c in info["red_countries"]})
ALL_BLUE_AIRPORTS = [ap for info in THEATER_INFO.values() for ap in info["blue_airports"]]
ALL_AIRPORTS = [ap for info in THEATER_INFO.values() for ap in info["blue_airports"] + info["red_airports"]]

TIME_OF_DAY = Literal["dawn", "day", "dusk", "night"]
WEATHER = Literal["clear", "cloudy", "rainy", "snowy", "windy"]
MISSION_TYPE = Literal["CAP", "STRIKE"]

# Every field below that maps to a concrete DCS asset is a real Literal enum
# (not a free string) so the LLM's structured-output schema enforces validity
# at generation time - the model literally cannot emit a value outside the
# whitelist. Airport/country Literals span ALL theaters (which ones are
# actually valid depends on the chosen `theater`); validate_whitelists()
# below is the runtime check - both for callers that build a MissionSpec by
# hand, and to catch a theater/airport/country mismatch the LLM might emit.
Theater = Literal[*THEATERS]
PlayerAircraft = Literal[*PLAYER_AIRCRAFT]
EnemyAirUnit = Literal[*ENEMY_AIR_UNITS]
StrikeTargetProfile = Literal[*STRIKE_TARGET_PROFILES.keys()]
BlueCountry = Literal[*ALL_BLUE_COUNTRIES]
RedCountry = Literal[*ALL_RED_COUNTRIES]
HomeAirport = Literal[*ALL_BLUE_AIRPORTS]
TargetAirport = Literal[*ALL_AIRPORTS]


class MissionSpec(BaseModel):
    title: str = Field(..., description="Short mission title")
    briefing: str = Field(..., description="1-3 sentence pilot briefing")

    theater: Theater = Field("Caucasus", description="Which DCS map/terrain to build the mission on")
    mission_type: MISSION_TYPE

    player_country: BlueCountry = "USA"
    player_aircraft: PlayerAircraft
    player_aircraft_count: int = Field(1, ge=1, le=4)
    home_airport: HomeAirport = Field(..., description="Blue-friendly airport name, on the chosen theater, for the player flight")

    enemy_country: RedCountry = "Russia"
    target_airport: TargetAirport = Field(
        ..., description="Nearest airport (on the chosen theater) to the objective area; anchors where threats/targets spawn"
    )

    # CAP-specific
    enemy_air_unit: EnemyAirUnit | None = Field(None, description="Red CAP aircraft type")
    enemy_air_count: int = Field(2, ge=1, le=4)

    # STRIKE-specific
    strike_target_profile: StrikeTargetProfile | None = Field(
        None, description="Named ground target composition"
    )

    time_of_day: TIME_OF_DAY = "day"
    weather: WEATHER = "clear"

    random_seed: int | None = Field(
        None,
        description=(
            "Optional seed controlling the randomized flight route, ground-threat "
            "composition, and enemy air presence. Omit for a fresh random layout "
            "on every generation; set it to reproduce the exact same layout again."
        ),
    )

    def validate_whitelists(self) -> None:
        errors = []
        info = THEATER_INFO[self.theater]
        theater_airports = info["blue_airports"] + info["red_airports"]

        if self.home_airport not in info["blue_airports"]:
            errors.append(f"home_airport '{self.home_airport}' is not a Blue airport on {self.theater}")
        if self.target_airport not in theater_airports:
            errors.append(f"target_airport '{self.target_airport}' is not on the {self.theater} map")
        if self.player_country not in info["blue_countries"]:
            errors.append(f"player_country '{self.player_country}' is not available on {self.theater} (expected one of {info['blue_countries']})")
        if self.enemy_country not in info["red_countries"]:
            errors.append(f"enemy_country '{self.enemy_country}' is not available on {self.theater} (expected one of {info['red_countries']})")

        if self.mission_type == "CAP":
            if self.enemy_air_unit is None:
                errors.append("mission_type is CAP but enemy_air_unit was not set")
            elif self.enemy_air_unit not in ENEMY_AIR_UNITS_BY_ERA[info["era"]]:
                errors.append(
                    f"enemy_air_unit '{self.enemy_air_unit}' doesn't match the {info['era']} era of {self.theater}"
                )
        if self.mission_type == "STRIKE" and self.strike_target_profile is None:
            errors.append("mission_type is STRIKE but strike_target_profile was not set")

        if errors:
            raise ValueError("MissionSpec validation failed:\n" + "\n".join(errors))


def reconcile_spec(spec: MissionSpec) -> MissionSpec:
    """Return a copy of `spec` made internally consistent with its `theater`.

    Used after the UI applies hard field overrides (map / aircraft / time /
    weather) on top of a parsed spec: forcing the map, in particular,
    cascades - the parsed airports/countries/enemy-air-era may no longer be
    valid for the new theater. This repairs only the *dependent* fields
    (airports, coalition countries, enemy air era) that a forced field
    invalidated, leaving everything the caller explicitly chose intact. The
    result is guaranteed to pass validate_whitelists() for any theater.
    """
    info = THEATER_INFO[spec.theater]
    theater_airports = info["blue_airports"] + info["red_airports"]
    updates: dict = {}

    if spec.home_airport not in info["blue_airports"]:
        updates["home_airport"] = info["blue_airports"][0]
    home_airport = updates.get("home_airport", spec.home_airport)
    if spec.target_airport not in theater_airports or spec.target_airport == home_airport:
        updates["target_airport"] = next(
            (ap for ap in info["red_airports"] if ap != home_airport), info["red_airports"][0]
        )
    if spec.player_country not in info["blue_countries"]:
        updates["player_country"] = info["default_blue_country"]
    if spec.enemy_country not in info["red_countries"]:
        updates["enemy_country"] = info["default_red_country"]

    if spec.mission_type == "CAP":
        era_units = ENEMY_AIR_UNITS_BY_ERA[info["era"]]
        if spec.enemy_air_unit not in era_units:
            updates["enemy_air_unit"] = era_units[0]
    elif spec.mission_type == "STRIKE" and spec.strike_target_profile is None:
        updates["strike_target_profile"] = "convoy"

    return spec.model_copy(update=updates) if updates else spec
