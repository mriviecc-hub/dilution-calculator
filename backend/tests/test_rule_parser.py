import pytest

from app.rule_parser import THEATER_ALIASES, parse_prompt_rule_based


def test_cap_prompt_extracts_aircraft_and_counts():
    spec = parse_prompt_rule_based(
        "Dawn CAP over Sochi-Adler with two F-16s against a pair of MiG-29s"
    )
    assert spec.mission_type == "CAP"
    assert spec.player_aircraft == "F_16C_50"
    assert spec.player_aircraft_count == 2
    assert spec.target_airport == "Sochi-Adler"
    assert spec.enemy_air_unit == "MiG_29S"
    assert spec.enemy_air_count == 2
    assert spec.time_of_day == "dawn"


def test_strike_prompt_extracts_target_profile():
    spec = parse_prompt_rule_based("Strike a convoy near Krasnodar with an A-10")
    assert spec.mission_type == "STRIKE"
    assert spec.player_aircraft == "A_10C_2"
    assert spec.target_airport == "Krasnodar-Center"
    assert spec.strike_target_profile == "convoy"


def test_sam_site_keyword_maps_to_sam_site_profile():
    spec = parse_prompt_rule_based("destroy a SAM site near Gelendzhik using a warthog")
    assert spec.mission_type == "STRIKE"
    assert spec.player_aircraft == "A_10C_2"
    assert spec.strike_target_profile == "sam_site"


def test_weather_and_time_keywords_detected():
    spec = parse_prompt_rule_based("intercept enemy fighters near Anapa at night in stormy weather")
    assert spec.time_of_day == "night"
    assert spec.weather == "rainy"  # "stormy" maps to the rainy preset


def test_snow_and_wind_keywords_detected():
    assert parse_prompt_rule_based("CAP over Batumi in heavy snow").weather == "snowy"
    assert parse_prompt_rule_based("CAP over Batumi, very windy and gusty").weather == "windy"


def test_ui_overrides_pin_fields_regardless_of_prompt():
    # Prompt says clear-sky F-16 CAP on Caucasus; UI forces everything else.
    spec = parse_prompt_rule_based(
        "CAP over Sochi with two F-16s in clear skies",
        forced_theater="Normandy",
        forced_player_aircraft="MosquitoFBMkVI",
        forced_time_of_day="dusk",
        forced_weather="snowy",
    )
    assert spec.theater == "Normandy"
    assert spec.player_aircraft == "MosquitoFBMkVI"
    assert spec.player_aircraft_count == 2  # count still read from the prompt
    assert spec.time_of_day == "dusk"
    assert spec.weather == "snowy"
    assert spec.enemy_air_unit in ("Bf_109K_4", "FW_190D9", "FW_190A8")  # era-correct
    spec.validate_whitelists()


def test_forced_theater_alone_cascades_to_era_correct_defaults():
    spec = parse_prompt_rule_based("a quick patrol", forced_theater="TheChannel")
    assert spec.theater == "TheChannel"
    assert spec.player_aircraft == "SpitfireLFMkIX"  # wwii default, not F-16
    spec.validate_whitelists()


def test_completely_vague_prompt_still_produces_valid_spec():
    spec = parse_prompt_rule_based("give me something to fly")
    spec.validate_whitelists()
    assert spec.player_aircraft == "F_16C_50"
    assert spec.mission_type == "CAP"


def test_never_raises_on_arbitrary_text():
    # Should always produce a valid spec, never throw, regardless of input.
    for prompt in ["asdf jkl;", "🚀🚀🚀", "a" * 500, "STRIKE STRIKE STRIKE"]:
        spec = parse_prompt_rule_based(prompt)
        spec.validate_whitelists()


def test_channel_map_keyword_selects_channel_theater():
    # Regression test for the exact bug report: prompts naming a non-Caucasus
    # map used to be silently ignored and always built on Caucasus.
    spec = parse_prompt_rule_based("CAP over the channel map with a spitfire against a 109")
    assert spec.theater == "TheChannel"
    assert spec.player_aircraft == "SpitfireLFMkIX"
    assert spec.enemy_air_unit == "Bf_109K_4"
    assert spec.home_airport in ("Biggin Hill", "Detling", "Eastchurch", "Hawkinge", "Headcorn", "High Halden", "Lympne", "Manston")
    spec.validate_whitelists()


def test_normandy_keyword_selects_wwii_era_defaults():
    spec = parse_prompt_rule_based("dogfight over normandy")
    assert spec.theater == "Normandy"
    assert spec.player_aircraft == "SpitfireLFMkIX"  # wwii default, not F_16C_50
    assert spec.player_country == "UK"
    assert spec.enemy_country == "ThirdReich"
    spec.validate_whitelists()


def test_no_map_keyword_still_defaults_to_caucasus():
    spec = parse_prompt_rule_based("Dawn CAP over Sochi-Adler with two F-16s against a pair of MiG-29s")
    assert spec.theater == "Caucasus"


@pytest.mark.parametrize("theater", list(THEATER_ALIASES.keys()))
def test_every_theater_keyword_produces_valid_spec(theater):
    prompt = f"CAP mission over the {THEATER_ALIASES[theater][0]}"
    spec = parse_prompt_rule_based(prompt)
    assert spec.theater == theater
    spec.validate_whitelists()
