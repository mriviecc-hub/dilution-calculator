"""Turns a validated MissionSpec into a real DCS .miz file using pydcs.

Static placement (units, waypoints, loadouts, weather) is done directly
through pydcs. Runtime dynamism (regenerating threats, reinforcement,
objective tracking) is layered on top via a generated MOOSE Lua script that
gets embedded into the mission's "MISSION START" trigger.

Neither MOOSE nor MIST is bundled by this app (both are large third-party
community projects - MOOSE is GPLv3 from FlightControl-Master, MIST is from
mrSkortch) - the caller supplies paths to locally-downloaded Moose.lua /
mist.lua and they get embedded per-mission. See README for one-time setup.
"""
from __future__ import annotations

import math
import random
import string
from pathlib import Path

import dcs
import dcs.countries as countries
import dcs.helicopters as helicopters
import dcs.planes as planes
import dcs.vehicles as vehicles
from dcs.action import DoScript, DoScriptFile
from dcs.mapping import Point
from dcs.mission import Mission, StartType
from dcs.task import CAP, OrbitAction, PinpointStrike
from dcs.triggers import TriggerStart
from dcs.unit import Skill
from dcs.weather import Weather as _Weather

WeatherPreceptions = _Weather.Preceptions

from .extra_aircraft import EXTRA_PLAYER_AIRCRAFT
from .mission_spec import (
    ENEMY_AIR_UNITS_BY_ERA,
    STRIKE_QRF_POOL_BY_ERA,
    STRIKE_TARGET_PROFILES_BY_ERA,
    THEATER_INFO,
    MissionSpec,
)

MOOSE_TEMPLATES_DIR = Path(__file__).parent / "moose_templates"


class MissionBuildError(Exception):
    pass


def _aircraft_type(name: str):
    """Look up a player/enemy aircraft class - a plane, a helicopter, or one
    of the newer-than-pydcs modules defined in extra_aircraft.py."""
    ac_type = (
        getattr(planes, name, None)
        or getattr(helicopters, name, None)
        or EXTRA_PLAYER_AIRCRAFT.get(name)
    )
    if ac_type is None:
        raise MissionBuildError(f"Unknown aircraft type '{name}'")
    return ac_type


def _get_country(m: Mission, coalition: str, name: str):
    """A Mission only pre-populates a fixed default coalition roster (see
    Mission.__init__) - most of pydcs's ~90 Country classes, including ones
    this app whitelists per-theater (USAFAggressors, ThirdReich, Japan,
    Argentina, ...), aren't in it and m.country(name) would silently return
    None for them. Register on first use instead."""
    existing = m.country(name)
    if existing is not None:
        return existing
    country_cls = getattr(countries, name, None)
    if country_cls is None:
        raise MissionBuildError(f"Unknown country '{name}'")
    return m.coalition[coalition].add_country(country_cls())


def _vehicle_type(name: str):
    for cat in ("Armor", "AirDefence", "Unarmed", "Artillery"):
        cat_obj = getattr(vehicles, cat, None)
        if cat_obj is not None and hasattr(cat_obj, name):
            return getattr(cat_obj, name)
    raise MissionBuildError(f"Unknown vehicle type '{name}'")


def _apply_weather(m: Mission, weather: str) -> None:
    # precip: pydcs's Preceptions enum only has None_/Rain/Thunderstorm - DCS
    # itself renders that precipitation as SNOW when the temperature is below
    # freezing, so "snowy" is just rain + a sub-zero season_temperature.
    none_ = WeatherPreceptions.None_
    rain = WeatherPreceptions.Rain
    presets = {
        "clear": dict(clouds_density=0, clouds_thickness=200, clouds_base=1500,
                      visibility_distance=80000, wind_ground=(2, 0), precip=none_, temp=21),
        "cloudy": dict(clouds_density=6, clouds_thickness=1400, clouds_base=1800,
                       visibility_distance=45000, wind_ground=(5, 50), precip=none_, temp=17),
        "rainy": dict(clouds_density=9, clouds_thickness=2200, clouds_base=900,
                      visibility_distance=11000, wind_ground=(8, 90), precip=rain, temp=12),
        "snowy": dict(clouds_density=9, clouds_thickness=2200, clouds_base=900,
                      visibility_distance=9000, wind_ground=(6, 70), precip=rain, temp=-6),
        "windy": dict(clouds_density=4, clouds_thickness=1000, clouds_base=2000,
                      visibility_distance=55000, wind_ground=(16, 120), precip=none_, temp=15),
    }
    p = presets[weather]
    m.weather.clouds_density = p["clouds_density"]
    m.weather.clouds_thickness = p["clouds_thickness"]
    m.weather.clouds_base = p["clouds_base"]
    m.weather.clouds_iprecptns = p["precip"]
    m.weather.visibility_distance = p["visibility_distance"]
    m.weather.season_temperature = p["temp"]

    speed, direction = p["wind_ground"]
    # Wind stores its heading on `.direction`; a prior version set `.dir`,
    # which is a no-op the serializer ignores - so keep this on `.direction`.
    m.weather.wind_at_ground.speed = speed
    m.weather.wind_at_ground.direction = direction
    # Winds aloft scale up with the surface wind so "windy" is felt at
    # altitude too (and turbulence for the gusty presets).
    m.weather.wind_at_2000.speed = round(speed * 1.6)
    m.weather.wind_at_2000.direction = direction
    m.weather.wind_at_8000.speed = round(speed * 2.2)
    m.weather.wind_at_8000.direction = direction
    m.weather.turbulence_at_ground = 12 if weather == "windy" else 0


def _load_template(name: str, **kwargs) -> str:
    text = (MOOSE_TEMPLATES_DIR / name).read_text()
    return string.Template(text).substitute(**kwargs)


def _dogleg_point(
    rng: random.Random,
    start: Point,
    end: Point,
    frac_range: tuple[float, float] = (0.35, 0.55),
    offset_deg_range: tuple[float, float] = (25, 45),
) -> Point:
    """A point partway along start->end, offset laterally off the direct
    line, so a transit leg isn't a razor-straight line into the objective."""
    heading = start.heading_between_point(end)
    distance = start.distance_to_point(end)
    side = rng.choice((-1, 1))
    jogged_heading = (heading + side * rng.uniform(*offset_deg_range)) % 360
    jogged_distance = distance * rng.uniform(*frac_range)
    return start.point_from_heading(jogged_heading, jogged_distance)


def _build_player_route(rng: random.Random, player_group, home_pt: Point, target_pt: Point, mission_type: str) -> None:
    """Lays a multi-leg route (dogleg transit, then a mission-specific
    ingress/objective/egress pattern) instead of a single straight waypoint
    at the objective, so the flight plan reads as deliberate routing rather
    than a beeline over the same ground track every time."""
    transit_point = _dogleg_point(rng, home_pt, target_pt)
    player_group.add_waypoint(transit_point, altitude=rng.randint(2500, 4000), speed=rng.randint(500, 620), name="Transit")

    ingress_heading = transit_point.heading_between_point(target_pt)

    if mission_type == "CAP":
        patrol_heading = (ingress_heading + rng.choice((-1, 1)) * rng.uniform(15, 40)) % 360
        patrol_distance = rng.uniform(9000, 20000)
        patrol_a = target_pt.point_from_heading(patrol_heading, patrol_distance)
        racetrack_heading = (patrol_heading + 90) % 360
        patrol_b = patrol_a.point_from_heading(racetrack_heading, rng.uniform(12000, 20000))
        cap_alt = rng.randint(5500, 7000)
        wp = player_group.add_waypoint(patrol_a, altitude=cap_alt, speed=rng.randint(450, 550), name="CAP Station")
        wp.add_task(OrbitAction(altitude=cap_alt, speed=470, pattern=OrbitAction.OrbitPattern.RaceTrack))
        player_group.add_waypoint(patrol_b, altitude=cap_alt, speed=rng.randint(450, 550), name="CAP Station (leg 2)")
    else:  # STRIKE
        ip_heading = (ingress_heading + rng.choice((-1, 1)) * rng.uniform(10, 25)) % 360
        ip_point = target_pt.point_from_heading((ip_heading + 180) % 360, rng.uniform(14000, 22000))
        player_group.add_waypoint(ip_point, altitude=rng.randint(3500, 4500), speed=rng.randint(480, 560), name="IP")
        player_group.add_waypoint(target_pt, altitude=rng.randint(1500, 2500), speed=rng.randint(480, 560), name="Target")
        egress_heading = (ip_heading + 180 + rng.choice((-1, 1)) * rng.uniform(60, 110)) % 360
        egress_point = target_pt.point_from_heading(egress_heading, rng.uniform(12000, 18000))
        player_group.add_waypoint(egress_point, altitude=rng.randint(3000, 4500), speed=rng.randint(480, 560), name="Egress")


def _random_strike_groups(rng: random.Random, profile: list[dict]) -> list[tuple[str, int]]:
    """Rolls a concrete (vehicle_type, count) list from a STRIKE_TARGET_PROFILES
    entry's pools/ranges - a different, but still profile-appropriate,
    composition on every call."""
    groups = []
    for slot in profile:
        count = rng.randint(*slot["count_range"])
        if count <= 0:
            continue
        groups.append((rng.choice(slot["pool"]), count))
    return groups


def _spawn_red_cap_group(m: Mission, red, rng: random.Random, name: str, aircraft: str, count: int, anchor: Point) -> None:
    """An airborne, late-activated red flight orbiting near `anchor` (with its
    own small position jitter so multiple such groups don't stack exactly on
    top of each other). Used as a MOOSE SPAWN template - see cap_dynamic.lua.tmpl."""
    spawn_point = anchor.point_from_heading(rng.uniform(0, 360), rng.uniform(0, 3000))
    altitude = rng.randint(5500, 7000)
    group = m.flight_group(
        country=red,
        name=name,
        aircraft_type=_aircraft_type(aircraft),
        airport=None,
        position=spawn_point,
        altitude=altitude,
        speed=rng.randint(420, 500),
        maintask=CAP,
        group_size=count,
    )
    group.points[0].add_task(OrbitAction(altitude=altitude, speed=400, pattern=OrbitAction.OrbitPattern.Circle))
    group.late_activation = True


def build_mission(
    spec: MissionSpec,
    moose_lua_path: str | None = None,
    mist_lua_path: str | None = None,
) -> Mission:
    """Build a Mission object. Caller is responsible for m.save(path).

    moose_lua_path / mist_lua_path are optional local paths to the MOOSE and
    MIST scripting libraries; each is embedded into the mission when given.
    """
    spec.validate_whitelists()
    rng = random.Random(spec.random_seed)
    era = THEATER_INFO[spec.theater]["era"]

    terrain_cls = getattr(dcs.terrain, spec.theater, None)
    if terrain_cls is None:
        raise MissionBuildError(f"Unknown theater '{spec.theater}'")
    m = Mission(terrain=terrain_cls())
    m.random_date()
    m.random_daytime(spec.time_of_day)
    _apply_weather(m, spec.weather)
    m.set_description_text(spec.briefing)
    m.sortie_text = spec.title

    terrain = m.terrain
    if spec.home_airport not in terrain.airports:
        raise MissionBuildError(f"Unknown home_airport '{spec.home_airport}' for {spec.theater}")
    if spec.target_airport not in terrain.airports:
        raise MissionBuildError(f"Unknown target_airport '{spec.target_airport}' for {spec.theater}")
    home_ap = terrain.airports[spec.home_airport]
    target_ap = terrain.airports[spec.target_airport]

    blue = _get_country(m, "blue", spec.player_country)
    red = _get_country(m, "red", spec.enemy_country)

    # --- Player flight -------------------------------------------------
    maintask = CAP if spec.mission_type == "CAP" else PinpointStrike
    player_group = m.flight_group_from_airport(
        country=blue,
        name="Player Flight",
        aircraft_type=_aircraft_type(spec.player_aircraft),
        airport=home_ap,
        maintask=maintask,
        start_type=StartType.Cold,
        group_size=spec.player_aircraft_count,
    )
    player_group.set_client()
    for unit in player_group.units:
        unit.skill = Skill.Client
    # Lay a multi-leg route (dogleg transit + mission-specific ingress/
    # objective/egress pattern) instead of a single straight waypoint.
    home_pt, target_pt = home_ap.position, target_ap.position
    _build_player_route(rng, player_group, home_pt, target_pt, spec.mission_type)

    dynamic_lua_parts: list[str] = []

    if spec.mission_type == "CAP":
        # Same patrol-area heading/distance logic _build_player_route used
        # for the player's CAP station, so red air actually shows up near
        # where the player is patrolling instead of a disconnected area.
        ingress_heading = home_pt.heading_between_point(target_pt)
        patrol_heading = (ingress_heading + rng.choice((-1, 1)) * rng.uniform(15, 40)) % 360
        patrol_anchor = target_pt.point_from_heading(patrol_heading, rng.uniform(9000, 20000))

        cap_group_name = "RED CAP-1"
        _spawn_red_cap_group(m, red, rng, cap_group_name, spec.enemy_air_unit, spec.enemy_air_count, patrol_anchor)

        era_enemy_air_units = ENEMY_AIR_UNITS_BY_ERA[era]
        wildcard_pool = [ac for ac in era_enemy_air_units if ac != spec.enemy_air_unit] or era_enemy_air_units
        wildcard_aircraft = rng.choice(wildcard_pool)
        wildcard_count = rng.randint(1, 2)
        cap_wildcard_group_name = "RED CAP-2 (Wildcard)"
        _spawn_red_cap_group(m, red, rng, cap_wildcard_group_name, wildcard_aircraft, wildcard_count, patrol_anchor)

        dynamic_lua_parts.append(_load_template(
            "cap_dynamic.lua.tmpl",
            cap_template_name=cap_group_name,
            cap_wildcard_template_name=cap_wildcard_group_name,
            wildcard_chance=0.35,
            max_alive_units=max(spec.enemy_air_count, wildcard_count) * 2,
            max_groups=3,
            respawn_interval_seconds=600,
            target_area_name=spec.target_airport,
        ))

    else:  # STRIKE
        profile = STRIKE_TARGET_PROFILES_BY_ERA[era][spec.strike_target_profile]
        target_point = target_ap.position.random_point_within(3000, 1000)
        rolled_groups = _random_strike_groups(rng, profile)
        target_group_names: list[str] = []
        total_units = 0
        num_groups = max(len(rolled_groups), 1)
        for idx, (veh_name, count) in enumerate(rolled_groups):
            gname = f"STRIKE TARGET-{idx + 1}"
            spread_heading = (idx * (360 / num_groups) + rng.uniform(-20, 20)) % 360
            spread_distance = rng.uniform(100, 300)
            vg = m.vehicle_group(
                country=red,
                name=gname,
                _type=_vehicle_type(veh_name),
                position=target_point.point_from_heading(spread_heading, spread_distance),
                group_size=count,
            )
            target_group_names.append(vg.name)
            total_units += count

        qrf_group_name = "STRIKE QRF-1"
        qrf_heading = rng.uniform(0, 360)
        qrf_distance = rng.uniform(3000, 6000)
        qrf_group = m.vehicle_group(
            country=red,
            name=qrf_group_name,
            _type=_vehicle_type(rng.choice(STRIKE_QRF_POOL_BY_ERA[era])),
            position=target_point.point_from_heading(qrf_heading, qrf_distance),
            group_size=rng.randint(1, 3),
        )
        qrf_group.late_activation = True

        lua_names = ", ".join(f'"{n}"' for n in target_group_names)
        dynamic_lua_parts.append(_load_template(
            "strike_dynamic.lua.tmpl",
            target_group_names_lua=lua_names,
            qrf_template_name=qrf_group_name,
            qrf_trigger_threshold=math.ceil(total_units / 2),
            target_area_name=spec.target_airport,
        ))

    # --- Mission-start trigger: load scripting libs + generated logic ---
    # MIST is loaded before MOOSE: MIST is a standalone utility library that
    # some MOOSE-era community scripts expect to already exist, and loading
    # it first matches the conventional Mission Editor ordering. Either can
    # be omitted independently - the generated logic below only *requires*
    # MOOSE, and the mission still loads and flies with neither.
    trigger = TriggerStart(comment="Mission setup / scripting init")
    for lib_path in (mist_lua_path, moose_lua_path):
        if lib_path:
            key = m.map_resource.add_resource_file(lib_path)
            trigger.add_action(DoScriptFile(key))
    trigger.add_action(DoScript(m.string(_moose_wrap("\n\n".join(dynamic_lua_parts)))))
    m.triggerrules.triggers.append(trigger)

    return m


def _moose_wrap(body: str) -> str:
    # Delay slightly so MOOSE (loaded by the preceding DoScriptFile action in
    # the same trigger) has finished initializing before our script runs.
    return (
        "local function __DcsCompanionInit()\n"
        f"{body}\n"
        "end\n"
        "if timer then\n"
        "  timer.scheduleFunction(function() __DcsCompanionInit() end, nil, timer.getTime() + 2)\n"
        "else\n"
        "  __DcsCompanionInit()\n"
        "end\n"
    )


def save_mission(
    spec: MissionSpec,
    out_path: str,
    moose_lua_path: str | None = None,
    mist_lua_path: str | None = None,
) -> str:
    m = build_mission(spec, moose_lua_path=moose_lua_path, mist_lua_path=mist_lua_path)
    m.save(out_path)
    return out_path
