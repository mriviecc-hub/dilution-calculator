import zipfile
from pathlib import Path

import pytest

from app.mission_builder import MissionBuildError, build_mission, save_mission
from app.mission_spec import ENEMY_AIR_UNITS_BY_ERA, PLAYER_AIRCRAFT, THEATER_INFO, MissionSpec

EXPECTED_MIZ_MEMBERS = {"options", "warehouses", "l10n/DEFAULT/dictionary", "l10n/DEFAULT/mapResource", "mission"}


def cap_spec(**overrides) -> MissionSpec:
    kwargs = dict(
        title="Test CAP",
        briefing="Intercept red fighters near Sochi-Adler.",
        mission_type="CAP",
        player_aircraft="F_16C_50",
        player_aircraft_count=2,
        home_airport="Kobuleti",
        target_airport="Sochi-Adler",
        enemy_air_unit="MiG_29S",
        enemy_air_count=2,
    )
    kwargs.update(overrides)
    return MissionSpec(**kwargs)


def strike_spec(**overrides) -> MissionSpec:
    kwargs = dict(
        title="Test Strike",
        briefing="Destroy the convoy near Krasnodar-Center.",
        mission_type="STRIKE",
        player_aircraft="A_10C_2",
        home_airport="Senaki-Kolkhi",
        target_airport="Krasnodar-Center",
        strike_target_profile="convoy",
    )
    kwargs.update(overrides)
    return MissionSpec(**kwargs)


def test_build_cap_mission_produces_valid_mission_object():
    m = build_mission(cap_spec())
    assert m.sortie_text == "Test CAP"
    groups = [g.name for g in m.country("USA").plane_group]
    assert "Player Flight" in groups
    red_groups = [g.name for g in m.country("Russia").plane_group]
    assert "RED CAP-1" in red_groups


def test_build_strike_mission_places_target_and_qrf():
    m = build_mission(strike_spec())
    red_vehicle_groups = [g.name for g in m.country("Russia").vehicle_group]
    assert "STRIKE TARGET-1" in red_vehicle_groups
    assert "STRIKE QRF-1" in red_vehicle_groups


def test_save_mission_writes_valid_miz(tmp_path):
    out = tmp_path / "test.miz"
    save_mission(cap_spec(), str(out))
    assert out.is_file()

    with zipfile.ZipFile(out) as z:
        assert EXPECTED_MIZ_MEMBERS.issubset(set(z.namelist()))
        mission_text = z.read("mission").decode("utf-8")
        assert "Player Flight" in mission_text
        assert "RED CAP-1" in mission_text


def test_save_mission_embeds_moose_lua_when_path_given(tmp_path):
    moose = tmp_path / "Moose.lua"
    moose.write_text("-- fake moose for test\n")
    out = tmp_path / "test_moose.miz"

    save_mission(cap_spec(), str(out), moose_lua_path=str(moose))

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "l10n/DEFAULT/Moose.lua" in names
        mission_text = z.read("mission").decode("utf-8")
        assert "a_do_script_file" in mission_text


def test_save_mission_embeds_mist_before_moose(tmp_path):
    """MIST must load before MOOSE - the order of the DoScriptFile actions
    in the mission-start trigger is what DCS actually executes."""
    mist = tmp_path / "mist.lua"
    mist.write_text("-- fake mist for test\n")
    moose = tmp_path / "Moose.lua"
    moose.write_text("-- fake moose for test\n")

    m = build_mission(cap_spec(), moose_lua_path=str(moose), mist_lua_path=str(mist))
    trigger = m.triggerrules.triggers[0]
    script_file_keys = [a.dict()["file"] for a in trigger.actions if type(a).__name__ == "DoScriptFile"]
    resources = m.map_resource.files["DEFAULT"]
    loaded_in_order = [Path(resources[k]).name for k in script_file_keys]
    assert loaded_in_order == ["mist.lua", "Moose.lua"]


def test_save_mission_embeds_mist_independently_of_moose(tmp_path):
    mist = tmp_path / "mist.lua"
    mist.write_text("-- fake mist for test\n")
    out = tmp_path / "mist_only.miz"
    save_mission(cap_spec(), str(out), mist_lua_path=str(mist))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "l10n/DEFAULT/mist.lua" in names
        assert "l10n/DEFAULT/Moose.lua" not in names


def test_f14b_u_builds_with_expected_dcs_unit_id(tmp_path):
    """The F-14B(U) is newer than pydcs 0.15.0 and comes from
    extra_aircraft.py - check it resolves and writes a real unit type."""
    from app.extra_aircraft import F_14B_U

    out = tmp_path / "f14bu.miz"
    save_mission(cap_spec(player_aircraft="F_14B_U"), str(out))
    with zipfile.ZipFile(out) as z:
        mission_text = z.read("mission").decode("utf-8")
    assert f'"{F_14B_U.id}"' in mission_text
    assert F_14B_U.flyable is True


def test_save_mission_without_moose_lua_has_no_embedded_file(tmp_path):
    out = tmp_path / "test_no_moose.miz"
    save_mission(cap_spec(), str(out))
    with zipfile.ZipFile(out) as z:
        assert "l10n/DEFAULT/Moose.lua" not in z.namelist()


def test_strike_dynamic_lua_references_all_target_groups(tmp_path):
    out = tmp_path / "strike.miz"
    save_mission(strike_spec(), str(out))
    with zipfile.ZipFile(out) as z:
        dictionary = z.read("l10n/DEFAULT/dictionary").decode("utf-8")
        assert "STRIKE TARGET-1" in dictionary
        assert "STRIKE QRF-1" in dictionary
        assert "MISSION_OBJECTIVE_COMPLETE" in dictionary


def test_cap_route_has_multiple_waypoints_not_a_straight_line():
    m = build_mission(cap_spec(random_seed=1))
    points = m.country("USA").plane_group[0].points
    assert len(points) >= 3  # transit + patrol station(s), not a single objective waypoint


def test_strike_route_has_ip_target_and_egress():
    m = build_mission(strike_spec(random_seed=1))
    points = m.country("USA").plane_group[0].points
    names = [p.name for p in points]
    assert "IP" in names
    assert "Target" in names
    assert "Egress" in names


def test_same_random_seed_reproduces_identical_route():
    m1 = build_mission(cap_spec(random_seed=42))
    m2 = build_mission(cap_spec(random_seed=42))
    coords1 = [(round(p.position.x), round(p.position.y)) for p in m1.country("USA").plane_group[0].points]
    coords2 = [(round(p.position.x), round(p.position.y)) for p in m2.country("USA").plane_group[0].points]
    assert coords1 == coords2


def test_different_random_seeds_produce_different_routes():
    m1 = build_mission(cap_spec(random_seed=1))
    m2 = build_mission(cap_spec(random_seed=2))
    coords1 = [(round(p.position.x), round(p.position.y)) for p in m1.country("USA").plane_group[0].points]
    coords2 = [(round(p.position.x), round(p.position.y)) for p in m2.country("USA").plane_group[0].points]
    assert coords1 != coords2


def test_cap_mission_spawns_primary_and_wildcard_red_groups():
    m = build_mission(cap_spec(random_seed=1))
    red_group_names = [g.name for g in m.country("Russia").plane_group]
    assert "RED CAP-1" in red_group_names
    assert "RED CAP-2 (Wildcard)" in red_group_names


def test_strike_ground_threat_composition_varies_with_seed():
    m1 = build_mission(strike_spec(random_seed=1))
    m2 = build_mission(strike_spec(random_seed=2))
    types1 = sorted(u.type for g in m1.country("Russia").vehicle_group for u in g.units)
    types2 = sorted(u.type for g in m2.country("Russia").vehicle_group for u in g.units)
    assert types1 != types2


@pytest.mark.parametrize("weather", ["clear", "cloudy", "rainy", "snowy", "windy"])
def test_every_weather_builds_and_sets_expected_precip(weather):
    m = build_mission(cap_spec(weather=weather))
    clouds = m.weather.dict()["clouds"]
    season = m.weather.dict()["season"]["temperature"]
    if weather in ("rainy", "snowy"):
        assert clouds["iprecptns"] == 1  # rain precip type
    else:
        assert clouds["iprecptns"] == 0
    if weather == "snowy":
        assert season < 0  # DCS renders sub-zero precip as snow
    if weather == "windy":
        assert m.weather.dict()["wind"]["atGround"]["speed"] >= 12


def test_unknown_vehicle_type_raises_mission_build_error():
    from app import mission_builder

    with pytest.raises(MissionBuildError):
        mission_builder._vehicle_type("NotARealVehicle")


def test_unknown_aircraft_type_raises_mission_build_error():
    from app import mission_builder

    with pytest.raises(MissionBuildError):
        mission_builder._aircraft_type("NotARealPlane")


@pytest.mark.parametrize("aircraft", PLAYER_AIRCRAFT)
def test_every_whitelisted_player_aircraft_builds(aircraft):
    """Regression guard: every PLAYER_AIRCRAFT entry (plane or helicopter)
    must resolve to a real pydcs class and build into a valid player slot."""
    m = build_mission(cap_spec(player_aircraft=aircraft))
    groups = [g.name for g in m.country("USA").plane_group] + [
        g.name for g in m.country("USA").helicopter_group
    ]
    assert "Player Flight" in groups


@pytest.mark.parametrize("theater", list(THEATER_INFO.keys()))
def test_every_theater_builds_cap_and_strike(theater):
    """Regression guard: every THEATER_INFO entry's terrain class, airports,
    countries, and era-appropriate enemy pools must actually build - this is
    the direct fix for missions silently building on Caucasus regardless of
    which map the user asked for."""
    info = THEATER_INFO[theater]
    era = info["era"]
    player_aircraft = "SpitfireLFMkIX" if era == "wwii" else "F_16C_50"

    cap = MissionSpec(
        title="t", briefing="b", theater=theater, mission_type="CAP",
        player_country=info["default_blue_country"], player_aircraft=player_aircraft,
        home_airport=info["blue_airports"][0],
        enemy_country=info["default_red_country"], target_airport=info["red_airports"][0],
        enemy_air_unit=ENEMY_AIR_UNITS_BY_ERA[era][0], enemy_air_count=2,
        random_seed=1,
    )
    m = build_mission(cap)
    assert m.terrain.__class__.__name__ == theater
    assert "Player Flight" in [g.name for g in m.country(info["default_blue_country"]).plane_group]

    strike = MissionSpec(
        title="t", briefing="b", theater=theater, mission_type="STRIKE",
        player_country=info["default_blue_country"], player_aircraft=player_aircraft,
        home_airport=info["blue_airports"][0],
        enemy_country=info["default_red_country"], target_airport=info["red_airports"][0],
        strike_target_profile="convoy",
        random_seed=1,
    )
    build_mission(strike)
