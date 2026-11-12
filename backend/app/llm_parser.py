"""Turns a plain-English mission request into a validated MissionSpec.

Uses Claude's structured-outputs support (client.messages.parse) so the
response is guaranteed to match the MissionSpec JSON schema - including every
Literal-typed field, which the LLM literally cannot fill with a value outside
the DCS-asset whitelist.
"""
from __future__ import annotations

import anthropic

from .mission_spec import (
    ENEMY_AIR_UNITS_BY_ERA,
    PLAYER_AIRCRAFT,
    STRIKE_TARGET_PROFILES,
    THEATER_INFO,
    MissionSpec,
)

MODEL = "claude-opus-4-8"


def _theater_table() -> str:
    lines = []
    for theater, info in THEATER_INFO.items():
        lines.append(
            f"  - {theater} ({info['era']} era): player_country one of "
            f"[{', '.join(info['blue_countries'])}] (default {info['default_blue_country']}), "
            f"enemy_country one of [{', '.join(info['red_countries'])}] (default {info['default_red_country']}), "
            f"home_airport one of [{', '.join(info['blue_airports'])}], "
            f"target_airport one of [{', '.join(info['blue_airports'] + info['red_airports'])}]"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are a DCS World (Digital Combat Simulator) mission designer. \
Convert the user's plain-English request into a structured mission, Blue \
coalition player, with a CAP (combat air patrol / intercept) or STRIKE \
(ground attack) mission type.

Guidance for filling fields:
- theater must be one of: {", ".join(THEATER_INFO.keys())}. Pick whichever \
map the user asked for (e.g. "Channel"/"English Channel" -> TheChannel, \
"Normandy"/"D-Day" -> Normandy, "Nevada"/"Vegas"/"NTTR" -> Nevada, "Persian \
Gulf"/"Gulf"/"UAE"/"Hormuz" -> PersianGulf, "Syria" -> Syria, "Marianas"/ \
"Guam"/"Pacific" -> MarianaIslands, "Falklands" -> Falklands). Default to \
Caucasus if the user doesn't name a map.
- player_country, enemy_country, home_airport, and target_airport ALL \
depend on the chosen theater and MUST come from that theater's own lists \
below - never mix airports/countries from a different theater than the one \
you picked:
{_theater_table()}
  home_airport should be geographically reasonable within its list, or the \
given default. target_airport anchors where the enemy threat/target spawns \
- pick the one nearest to wherever the user describes the objective, or a \
Red-side airport by default.
- player_aircraft must be one of: {", ".join(PLAYER_AIRCRAFT)}. Pick the one \
that best matches what the user asked for (e.g. "F-16" -> F_16C_50, "Hornet" \
or "F/A-18" -> FA_18C_hornet, "Warthog" or "A-10" -> A_10C_2, "Apache" -> \
AH_64D_BLK_II, "Hind" -> Mi_24P, "Hip" -> Mi_8MT, "Huey" -> UH_1H, "Black \
Shark" -> Ka_50, "Spitfire" -> SpitfireLFMkIX, "Mustang" -> P_51D, "109" or \
"Messerschmitt" -> Bf_109K_4, "Fw 190" -> FW_190D9). Only pick a helicopter \
if the user explicitly asked for one. On a "wwii" era theater, only pick a \
WWII-appropriate aircraft (P-51/P-47/Spitfire/Mosquito/Bf 109/Fw 190/I-16/ \
Yak-52), never a modern jet or helicopter. Default to F_16C_50 on modern \
theaters, SpitfireLFMkIX on wwii theaters, if unspecified.
- For CAP missions, enemy_air_unit must match the chosen theater's era: \
{", ".join(ENEMY_AIR_UNITS_BY_ERA["modern"])} on a modern theater, or \
{", ".join(ENEMY_AIR_UNITS_BY_ERA["wwii"])} on a wwii theater (Channel/Normandy).
- For STRIKE missions, strike_target_profile must be one of: \
{", ".join(STRIKE_TARGET_PROFILES.keys())} (convoy = trucks + AAA/flak \
escort, sam_site = command vehicle + AAA/flak + SAM if the era has one, \
depot = static supply trucks, no escort). The actual vehicles used are \
picked automatically based on the theater's era - you only choose the \
profile name.
- Write a punchy 1-3 sentence pilot briefing in the briefing field.
- Infer time_of_day (dawn/day/dusk/night) and weather from mood/atmosphere \
words in the request. weather is one of clear, cloudy, rainy, snowy, windy \
("stormy"/"rain" -> rainy, "snow"/"blizzard" -> snowy, "gusty"/"gale" -> \
windy, "overcast" -> cloudy). Default to day/clear if unstated.
- If a CONSTRAINTS line is present in the user message, treat those values as \
already decided: use them exactly, and choose every other field to be \
consistent with them (e.g. a forced wwii theater means wwii aircraft and \
period adversaries, a forced snowy map still needs valid airports for that \
theater).
"""


class ParseError(Exception):
    pass


def _constraints_line(
    forced_theater: str | None,
    forced_player_aircraft: str | None,
    forced_time_of_day: str | None,
    forced_weather: str | None,
) -> str:
    parts = []
    if forced_theater:
        parts.append(f"theater={forced_theater}")
    if forced_player_aircraft:
        parts.append(f"player_aircraft={forced_player_aircraft}")
    if forced_time_of_day:
        parts.append(f"time_of_day={forced_time_of_day}")
    if forced_weather:
        parts.append(f"weather={forced_weather}")
    return ("CONSTRAINTS (use these exact values): " + "; ".join(parts)) if parts else ""


def parse_prompt(
    user_prompt: str,
    client: anthropic.Anthropic | None = None,
    *,
    forced_theater: str | None = None,
    forced_player_aircraft: str | None = None,
    forced_time_of_day: str | None = None,
    forced_weather: str | None = None,
) -> MissionSpec:
    client = client or anthropic.Anthropic()

    constraints = _constraints_line(
        forced_theater, forced_player_aircraft, forced_time_of_day, forced_weather
    )
    content = f"{user_prompt}\n\n{constraints}" if constraints else user_prompt

    response = client.messages.parse(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=MissionSpec,
    )

    if response.stop_reason == "refusal":
        raise ParseError("Claude declined to generate this mission (safety refusal).")
    if response.parsed_output is None:
        raise ParseError(f"Claude did not return a parseable mission spec (stop_reason={response.stop_reason}).")

    spec = response.parsed_output
    try:
        spec.validate_whitelists()
    except ValueError as e:
        raise ParseError(
            f"Claude produced an inconsistent mission spec (mismatched theater/airport/country/aircraft): {e}"
        ) from e
    return spec
