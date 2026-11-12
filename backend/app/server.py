"""Local FastAPI backend for the DCS Mission Companion desktop app.

Runs on localhost only - the Electron main process spawns this and talks to
it over HTTP. Not designed to be exposed to the network.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from typing import get_args

from .llm_parser import ParseError, parse_prompt
from .mission_builder import MissionBuildError, save_mission
from .mission_spec import (
    ENEMY_AIR_UNITS_BY_ERA,
    PLAYER_AIRCRAFT,
    STRIKE_TARGET_PROFILES,
    THEATER_INFO,
    TIME_OF_DAY,
    WEATHER,
    MissionSpec,
    PlayerAircraft,
    Theater,
    reconcile_spec,
)
from .rule_parser import DISPLAY_NAMES, parse_prompt_rule_based

app = FastAPI(title="DCS Mission Companion")


class GenerateRequest(BaseModel):
    prompt: str
    moose_lua_path: str | None = None
    mist_lua_path: str | None = None
    save_path: str | None = None  # absolute path to write the .miz; temp file if omitted
    anthropic_api_key: str | None = None  # overrides ANTHROPIC_API_KEY env var for this call

    # Optional hard overrides from the UI dropdowns. Each None = "Auto"
    # (let the parser decide from the prompt). A set value is pinned exactly,
    # and any dependent fields it invalidates are reconciled server-side.
    theater: Theater | None = None
    player_aircraft: PlayerAircraft | None = None
    time_of_day: TIME_OF_DAY | None = None
    weather: WEATHER | None = None


class GenerateResponse(BaseModel):
    spec: MissionSpec
    saved_path: str
    parser_used: str  # "claude" or "rule_based"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/options")
def options() -> dict:
    return {
        "player_aircraft": PLAYER_AIRCRAFT,
        # id -> real module name, so the UI dropdown reads "F-14B(U) Tomcat"
        # rather than "F_14B_U". Falls back to the id for anything unnamed.
        "aircraft_display_names": {ac: DISPLAY_NAMES.get(ac, ac) for ac in PLAYER_AIRCRAFT},
        "enemy_air_units_by_era": ENEMY_AIR_UNITS_BY_ERA,
        "strike_target_profiles": list(STRIKE_TARGET_PROFILES.keys()),
        "theaters": THEATER_INFO,
        "theater_names": list(THEATER_INFO.keys()),
        "times_of_day": list(get_args(TIME_OF_DAY)),
        "weathers": list(get_args(WEATHER)),
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    if not req.prompt.strip():
        raise HTTPException(400, "prompt must not be empty")

    forced = dict(
        forced_theater=req.theater,
        forced_player_aircraft=req.player_aircraft,
        forced_time_of_day=req.time_of_day,
        forced_weather=req.weather,
    )

    api_key = req.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            spec = parse_prompt(req.prompt, client=anthropic.Anthropic(api_key=api_key), **forced)
            parser_used = "claude"
        except ParseError as e:
            raise HTTPException(422, str(e)) from e
    else:
        # No API key configured - fall back to the offline keyword-based
        # parser instead of failing outright. Less flexible with vague or
        # creative phrasing, but works with zero setup and no network calls.
        spec = parse_prompt_rule_based(req.prompt, **forced)
        parser_used = "rule_based"

    # Re-pin the UI overrides as hard anchors and reconcile any dependent
    # fields they invalidate (belt-and-suspenders: the parsers already honor
    # forced values, but this also fixes a Claude spec that ignored them).
    override_updates = {k: v for k, v in {
        "theater": req.theater,
        "player_aircraft": req.player_aircraft,
        "time_of_day": req.time_of_day,
        "weather": req.weather,
    }.items() if v is not None}
    if override_updates:
        spec = reconcile_spec(spec.model_copy(update=override_updates))
        try:
            spec.validate_whitelists()
        except ValueError as e:
            raise HTTPException(422, f"Could not reconcile overrides: {e}") from e

    if req.save_path:
        out_path = req.save_path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = str(Path(tempfile.gettempdir()) / f"{_safe_filename(spec.title)}.miz")

    try:
        save_mission(
            spec, out_path,
            moose_lua_path=req.moose_lua_path,
            mist_lua_path=req.mist_lua_path,
        )
    except MissionBuildError as e:
        raise HTTPException(422, str(e)) from e

    return GenerateResponse(spec=spec, saved_path=out_path, parser_used=parser_used)


@app.get("/download")
def download(path: str) -> FileResponse:
    p = Path(path)
    if not p.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(str(p), filename=p.name, media_type="application/octet-stream")


def _safe_filename(title: str) -> str:
    keep = [c if c.isalnum() or c in (" ", "-", "_") else "_" for c in title]
    return "".join(keep).strip().replace(" ", "_")[:60] or "mission"
