import pytest
from pydantic import ValidationError

from app.mission_spec import MissionSpec, reconcile_spec


def _base_kwargs(**overrides):
    kwargs = dict(
        title="Test",
        briefing="Test briefing.",
        mission_type="CAP",
        player_aircraft="F_16C_50",
        home_airport="Kobuleti",
        target_airport="Sochi-Adler",
        enemy_air_unit="MiG_29S",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_cap_spec_builds():
    spec = MissionSpec(**_base_kwargs())
    spec.validate_whitelists()
    assert spec.mission_type == "CAP"


def test_valid_strike_spec_builds():
    spec = MissionSpec(**_base_kwargs(
        mission_type="STRIKE", enemy_air_unit=None, strike_target_profile="convoy",
    ))
    spec.validate_whitelists()


def test_rejects_unknown_aircraft():
    with pytest.raises(ValidationError):
        MissionSpec(**_base_kwargs(player_aircraft="F_22A_Raptor"))


def test_rejects_unknown_airport():
    with pytest.raises(ValidationError):
        MissionSpec(**_base_kwargs(home_airport="Nellis AFB"))


def test_rejects_home_airport_on_red_side():
    # home_airport is restricted to the blue-friendly whitelist even though
    # it's a valid Caucasus airport in general (it's red-friendly).
    with pytest.raises(ValidationError):
        MissionSpec(**_base_kwargs(home_airport="Anapa-Vityazevo"))


def test_cap_without_enemy_air_unit_fails_whitelist_check():
    spec = MissionSpec(**_base_kwargs(enemy_air_unit=None))
    with pytest.raises(ValueError):
        spec.validate_whitelists()


def test_strike_without_target_profile_fails_whitelist_check():
    spec = MissionSpec(**_base_kwargs(mission_type="STRIKE", enemy_air_unit=None))
    with pytest.raises(ValueError):
        spec.validate_whitelists()


def _channel_kwargs(**overrides):
    kwargs = dict(
        title="Test", briefing="Test briefing.", theater="TheChannel", mission_type="CAP",
        player_country="UK", player_aircraft="SpitfireLFMkIX",
        home_airport="Biggin Hill", enemy_country="ThirdReich",
        target_airport="Abbeville Drucat", enemy_air_unit="Bf_109K_4",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_non_caucasus_theater_spec_builds():
    spec = MissionSpec(**_channel_kwargs())
    spec.validate_whitelists()
    assert spec.theater == "TheChannel"


def test_rejects_airport_from_wrong_theater():
    # Kobuleti/Sochi-Adler are real Caucasus airports, not on TheChannel.
    spec = MissionSpec(**_channel_kwargs(home_airport="Kobuleti", target_airport="Sochi-Adler"))
    with pytest.raises(ValueError):
        spec.validate_whitelists()


def test_rejects_enemy_air_unit_from_wrong_era():
    # MiG-29 is a modern jet; TheChannel is a wwii-era theater.
    spec = MissionSpec(**_channel_kwargs(enemy_air_unit="MiG_29S"))
    with pytest.raises(ValueError):
        spec.validate_whitelists()


def test_rejects_country_not_available_on_theater():
    # Russia isn't a red_country option on TheChannel (ThirdReich is).
    spec = MissionSpec(**_channel_kwargs(enemy_country="Russia"))
    with pytest.raises(ValueError):
        spec.validate_whitelists()


@pytest.mark.parametrize("theater", ["Caucasus", "TheChannel", "Nevada", "Normandy", "PersianGulf", "Syria", "MarianaIslands", "Falklands"])
def test_every_theater_default_combo_is_internally_consistent(theater):
    """Regression guard: THEATER_INFO's own default_blue_country/default_red_country
    and first blue/red airport must always pass validate_whitelists() together."""
    from app.mission_spec import ENEMY_AIR_UNITS_BY_ERA, THEATER_INFO

    info = THEATER_INFO[theater]
    era = info["era"]
    player_aircraft = "SpitfireLFMkIX" if era == "wwii" else "F_16C_50"
    spec = MissionSpec(
        title="t", briefing="b", theater=theater, mission_type="CAP",
        player_country=info["default_blue_country"], player_aircraft=player_aircraft,
        home_airport=info["blue_airports"][0],
        enemy_country=info["default_red_country"],
        target_airport=info["red_airports"][0],
        enemy_air_unit=ENEMY_AIR_UNITS_BY_ERA[era][0],
    )
    spec.validate_whitelists()


def test_reconcile_repairs_cross_theater_override():
    # A valid Caucasus spec whose theater is then forced to a WWII map: the
    # now-invalid airports/countries/enemy-era must all get repaired.
    caucasus = MissionSpec(**_base_kwargs())
    forced = reconcile_spec(caucasus.model_copy(update={"theater": "Normandy"}))
    assert forced.theater == "Normandy"
    forced.validate_whitelists()  # must not raise
    assert forced.home_airport != "Kobuleti"
    assert forced.enemy_air_unit != "MiG_29S"  # swapped to a period fighter


def test_player_aircraft_whitelist_is_flyable_only():
    """The aircraft dropdown is populated straight from PLAYER_AIRCRAFT, so
    every entry must be a genuinely player-flyable module - otherwise DCS
    rejects the client slot at mission load."""
    import dcs.helicopters as helicopters
    import dcs.planes as planes

    from app.extra_aircraft import EXTRA_PLAYER_AIRCRAFT
    from app.mission_spec import PLAYER_AIRCRAFT

    not_flyable = []
    for name in PLAYER_AIRCRAFT:
        cls = (
            getattr(planes, name, None)
            or getattr(helicopters, name, None)
            or EXTRA_PLAYER_AIRCRAFT.get(name)
        )
        assert cls is not None, f"{name} does not resolve to any aircraft class"
        if not getattr(cls, "flyable", False):
            not_flyable.append(name)
    assert not_flyable == []


def test_reconcile_leaves_a_consistent_spec_untouched():
    spec = MissionSpec(**_base_kwargs())
    assert reconcile_spec(spec) is spec  # no changes needed -> same object
