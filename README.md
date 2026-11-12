# DCS Mission Companion

A desktop app that turns a plain-English request ("dawn CAP over Sochi with
two F-16s against a pair of MiG-29s") into a ready-to-fly DCS World mission
file (`.miz`) — no interaction with the DCS Mission Editor required.

Claude parses your prompt into a structured mission spec (or, with no API key
configured, a built-in offline keyword parser does — see
[Prompt parsing](#prompt-parsing-claude-vs-offline) below), then
[pydcs](https://github.com/pydcs/dcs) builds a real DCS mission from it
(units, waypoints, loadouts, weather, triggers), and generated Lua backed by
[MOOSE](https://github.com/FlightControl-Master/MOOSE) gives the mission
runtime dynamism (regenerating threats, reinforcement, objective tracking)
instead of static one-shot unit placement.

**v1 scope:** all 8 maps pydcs can build a mission for (Caucasus, The
Channel, Nevada, Normandy, Persian Gulf, Syria, Mariana Islands, Falklands —
see [Maps](#maps)), Blue coalition player, CAP (intercept) and STRIKE
missions. See [Roadmap](#roadmap) for what's next.

## How it works

There is no live API into the DCS Mission Editor — missions are just Lua
tables inside a zipped `.miz` file, and that's the real integration point
every serious DCS tool (this one included) uses.

```
 plain-English prompt
        |
        v
 Claude (structured outputs)  ->  MissionSpec (validated JSON)
        |
        v
 pydcs mission builder        ->  units, waypoints, loadouts, weather, triggers
        |
        v
 generated MOOSE Lua          ->  dynamic threats / reinforcement / objectives
        |
        v
      mission.miz  ->  drop into your DCS Missions folder and fly
```

- `backend/` — Python engine: FastAPI server, the Claude-based prompt parser,
  and the pydcs mission builder. This does all the actual work.
- `desktop/` — Electron shell around the backend: a prompt box, a settings
  panel (API key, MOOSE path, DCS folder), and a "generate" button.

## Setup

### 1. Backend

```sh
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python patch_pydcs.py
```

That last step patches a couple of known `pydcs` bugs (see [Troubleshooting](#troubleshooting)) that otherwise crash mission generation on some real DCS installations - it's safe to re-run any time, including after recreating the venv.

An [Anthropic API key](https://console.anthropic.com/) is optional — enter it
in the app's Settings panel once the desktop app is running (or set
`ANTHROPIC_API_KEY` as an environment variable before launching) for flexible,
free-form prompt parsing. Without one, the app automatically falls back to a
built-in offline parser — see [Prompt parsing](#prompt-parsing-claude-vs-offline).

Run the test suite (no API key required — the LLM call is mocked):

```sh
pytest
```

### 2. MOOSE (optional, enables dynamic mission logic)

Missions still work without this — you just lose the dynamic-threat layer
(regenerating CAP flights, QRF reinforcement, objective tracking) and fall
back to static unit placement.

1. Download the latest static `Moose.lua` from the
   [MOOSE releases page](https://github.com/FlightControl-Master/MOOSE/releases)
   (look for `Moose_Include_Static/Moose.lua` in the release assets).
2. Save it anywhere on disk, e.g.
   `%USERPROFILE%\Saved Games\DCS.openbeta\Scripts\MOOSE\Moose.lua`.
3. Point the app's Settings panel at that file. The generator embeds a copy
   of it into every mission it builds (exactly what the Mission Editor does
   when you manually add a "DO SCRIPT FILE" trigger action) - it never
   references the file by path at mission runtime.

### 2b. MIST (optional, extra scripting library)

[MIST](https://github.com/mrSkortch/MissionScriptingTools) is a widely-used
DCS scripting utility library. It's independent of MOOSE — set either, both,
or neither.

1. Download the latest `mist.lua` from the
   [MIST releases page](https://github.com/mrSkortch/MissionScriptingTools/releases).
2. Save it anywhere on disk, e.g.
   `%USERPROFILE%\Saved Games\DCS.openbeta\Scripts\MIST\mist.lua`.
3. Point the app's Settings panel at it. It's embedded the same way MOOSE is,
   and **loaded before MOOSE** so any MIST helpers are available to
   everything that runs afterward.

Nothing this app generates *requires* MIST — the built-in dynamic logic is
MOOSE-based. Set it when you want MIST's helpers available for your own
scripting on top of the generated mission.

### 3. Desktop app

```sh
cd desktop
npm install
npm start
```

`npm install` downloads the Electron binary from GitHub releases — if your
network blocks that, install on a machine that doesn't (this is unrelated to
the Python/pydcs/Claude parts, which have no such restriction).

On launch, the app spawns the Python backend from `backend/venv` and opens
its own window. In Settings you can:

- enter your Anthropic API key
- point at your local `Moose.lua` (optional, see above)
- point at (or auto-detect) your DCS Saved Games `Missions` folder, so
  generated missions save straight there instead of a temp folder

### 4. Fly it

Type a prompt, hit **Generate mission**, then open the `.miz` from your DCS
Missions folder (or use **Show file in folder**) in DCS World.

## Prompt parsing: Claude vs. offline

The app has two interchangeable ways to turn your prompt into a mission spec,
and picks automatically based on whether an API key is configured:

- **Claude (API key set):** genuinely understands free-form, creative
  phrasing ("something moody and dangerous over the coast at dusk"), infers
  intent, and writes a custom briefing.
- **Offline keyword parser (no API key):** zero cost, zero setup, no network
  calls - pure Python string/keyword matching (`backend/app/rule_parser.py`).
  It recognizes a nickname for every player-aircraft *family* in the roster
  below (F-16/Viper, Hornet, Warthog, Mirage, Flanker, Fulcrum, Apache,
  Huey, Mustang, Spitfire, etc. - see `PLAYER_AIRCRAFT_ALIASES` for the full
  list), mission-type words (CAP/intercept/patrol vs. strike/bomb/destroy),
  target-profile words (convoy/SAM site/depot), airport names, numbers
  ("two", "a pair of", "4x"), and time-of-day/weather words. When a prompt
  mentions more than one aircraft (player and enemy), the first one
  mentioned is treated as the player's. It always produces a valid mission
  by falling back to sensible defaults for anything it can't confidently
  extract, but it won't pick out an exact sub-variant (e.g. "MB-339APAN" vs
  plain "MB-339A") or understand indirect/unusually-phrased requests the way
  Claude does, so prompts work best when they mention things somewhat
  literally, e.g. *"CAP over Sochi with two F-16s against a pair of
  MiG-29s"* rather than *"give me something fun near the water."*

The app tells you which one was used after each generation (shown next to
the saved file path).

### Locking in fundamentals

Under the prompt box are four dropdowns — **Map**, **Player aircraft**,
**Time of day**, **Weather** — each defaulting to *Auto (from prompt)*. Leave
one on Auto and it's inferred from your prompt as usual; set it and that value
is pinned exactly, whichever parser runs. Locking the **Map** cascades
correctly: everything else (airfields, coalition countries, and — on a WWII
map — the enemy fighters and ground threats) is reconciled to that theater, so
forcing Normandy with no aircraft named still gives you a Spitfire vs a Bf 109,
not an F-16. **Weather** options are `clear`, `cloudy`, `rainy`, `snowy`,
`windy` (snowy = precipitation with a sub-zero temperature, which is how DCS
renders falling snow; windy drives real wind at altitude plus turbulence). The
**New mission** button clears the prompt and resets every dropdown to Auto.

## Maps

Name a map in your prompt and the mission builds on it - e.g. *"CAP over the
Channel map with a Spitfire against a 109"* or *"strike a convoy in Syria"*.
Say nothing and it defaults to Caucasus. The result panel always shows which
map a generation actually used (**Map** field) so a map mismatch is obvious
at a glance instead of silently building on the wrong terrain.

| Map (say...) | Era | Blue | Red |
|---|---|---|---|
| Caucasus *(default)* | modern | USA, UK, Germany, France, Israel, Georgia | Russia, USAF Aggressors |
| "Channel"/"English Channel" (`TheChannel`) | WWII | UK, USA, France | Third Reich |
| "Normandy"/"D-Day" | WWII | UK, USA, France | Third Reich |
| "Nevada"/"Vegas"/"NTTR" | modern | USA | USAF Aggressors |
| "Persian Gulf"/"the Gulf"/"UAE"/"Dubai" | modern | USA, UK | Iran |
| "Syria" | modern | USA, Israel | Syria |
| "Marianas"/"Guam"/"Saipan" | modern | USA | Japan *(flag only - no period Japanese aircraft exist in `pydcs`)* |
| "Falklands" | modern | UK | Argentina *(flag only, same caveat)* |

**Era matters for CAP/STRIKE composition, not just scenery.** On a WWII map
(Channel/Normandy), `enemy_air_unit` is restricted to period fighters
(Bf 109 K-4, Fw 190 D-9/A-8) instead of modern jets, and STRIKE ground
threats/QRF pull from WWII-appropriate vehicles (flak guns, period trucks,
Jagdpanther/Elefant tank destroyers) instead of modern IFVs and SAMs - see
`mission_spec.py`'s `*_BY_ERA` dicts. Every other map uses the same modern
pools as Caucasus.

Airport and country lists per map are a curated subset (not every airfield
pydcs knows about), same scoping choice as the original Caucasus list - see
`mission_spec.THEATER_INFO` for the exact whitelist, or ask me to add more.

## Aircraft roster

`player_aircraft` (what you fly) is **player-flyable modules only** — every
aircraft `pydcs` 0.15.0 marks as flyable, plus newer modules added by hand
(see below). 59 aircraft as of this writing, and a test asserts none of them
is an AI-only type:

- **Modern / Cold War jets:** F-16C, F/A-18C, A-10C II, A-10C, A-10A, AV-8B,
  F-14B(U), F-14B, F-14A, F-15C, Mirage 2000C, JF-17, Su-27, Su-33, Su-25T,
  Su-25, MiG-29S/A/G, MiG-21bis, MiG-19P, MiG-15bis, Mirage F1CE/EE, F-5E,
  F-86F
- **Jet trainers / light attack:** L-39C, L-39ZA, C-101EB, C-101CC,
  MB-339A, MB-339APAN, BAE Hawk, AJS37 Viggen
- **Helicopters:** Ka-50, Ka-50 III, Mi-8MTV2, Mi-24P, UH-1H, AH-64D,
  SA342 Gazelle (M/L/Mistral/Minigun)
- **WWII warbirds:** P-51D, P-51D-30, TF-51D, P-47D-30/40, Bf 109 K-4,
  Fw 190 D-9/A-8, Spitfire LF Mk IX (+ clipped wing), Mosquito FB Mk VI, I-16
- **General aviation:** Yak-52, Christen Eagle II

**Modules newer than pydcs** (like the 2026 Heatblur **F-14B(U)**) aren't in
`pydcs` 0.15.0's table at all, so they're defined by hand in
`backend/app/extra_aircraft.py`. Each subclasses the closest real pydcs type
— the F-14B(U) subclasses the F-14B, inheriting its pylons, tasks and
dimensions — so only the DCS unit-type id differs. That id has to match what
DCS itself uses byte-for-byte, so instead of hard-coding a guess, the app
scans your local DCS installation's `UnitPayloads` files at startup and
adopts the id that actually matches. If DCS isn't installed (CI, a build
machine), it falls back to the documented default. Add further new modules
by following the same pattern.

A handful of real, released DCS modules `pydcs` hasn't marked flyable yet
(F-15E, F-4E, F-117A, non-Block-II AH-64D, Tornado, Tu-22M3, B-52H,
MiG-23MLD) aren't selectable - see [Troubleshooting](#troubleshooting) if a
module you expect to see is missing.

`enemy_air_unit` (CAP missions) is a smaller, deliberately curated list of
plausible Red adversaries: MiG-29S/A, Su-27, Su-33, MiG-31, J-11A, F-5E.

## Troubleshooting

`pydcs` (0.15.0, the latest release) has a couple of known bugs that surface
when it scans a real, up-to-date DCS World installation - it predates some
recent DCS content and crashes instead of gracefully skipping what it can't
parse. **Run `python patch_pydcs.py` from `backend/` (with the venv active)
to fix both** - it's idempotent, so safe to re-run any time, including after
recreating the venv. Manual fixes below if you'd rather not run the script,
or if a *different* aircraft/livery trips a similar bug it doesn't cover yet
(if so, paste me the traceback and I'll add it to the patch script).

**`KeyError: 'country_list'` crash on startup (Python 3.13+):** the livery
scanner uses an old `exec()`/`locals()` trick that breaks on Python 3.13 and
newer. Manual fix: in `backend/venv/Lib/site-packages/dcs/liveries_scanner.py`,
replace
```python
exec(f"country_list = {countries}")
countries = set(filter(lambda x: x != "", locals()['country_list']))
```
with
```python
country_list = eval(countries)
countries = set(filter(lambda x: x != "", country_list))
```
(Alternatively, install Python 3.11 or 3.12 alongside your current version
and rebuild the venv with it - `py -3.11 -m venv venv` - which avoids this
bug entirely, though the payload-cache bug below is unrelated to Python
version and needs the patch either way.)

**`KeyError: WindowsPath(...UnitPayloads\<Aircraft>.lua)` crash when
generating a mission:** the payload scanner assumes every payload file it
finds was successfully parsed into its cache, but skips files whose
`unitType` line it couldn't match (e.g. newer aircraft like the F-100D) -
then crashes looking that skipped entry back up. Manual fix: in
`backend/venv/Lib/site-packages/dcs/unittype.py`, replace
```python
if FlyingType._payload_cache[payload_path] == cls.id and payload_path.exists():
```
with
```python
if FlyingType._payload_cache.get(payload_path) == cls.id and payload_path.exists():
```

## What "dynamic" means in v1

- **Flight routing**: the player flight is never a single straight waypoint
  into the objective. Every mission gets a dogleg transit leg off the direct
  line, then a mission-specific pattern - a two-point CAP race-track station
  (with a proper MOOSE `OrbitAction`) offset from the target airport for CAP,
  or a distinct IP -> target -> egress run (each leg on a different heading,
  so you don't fly back out over the same ground track) for STRIKE.
- **CAP missions**: the red flight is placed airborne near the same patrol
  area the player is routed to (not sitting at the target airbase), and is
  late-activated so a generated MOOSE `SPAWN` script keeps regenerating it for
  the mission duration instead of a single scripted patrol you can kill once
  and be done with. Each regeneration randomly picks between the requested
  bandit type and a second "wildcard" type/count, so red air composition
  varies across playthroughs.
- **STRIKE missions**: the ground target's exact vehicle types, counts, and
  placement around the objective are randomized per generation from a
  profile-appropriate pool (see `mission_spec.STRIKE_TARGET_PROFILES`), not a
  fixed list. The target is placed live; a MOOSE scheduler polls it, launches
  a randomized QRF reinforcement group (type/count/position vary too) once it
  takes losses, and announces mission-objective completion (sets a DCS flag)
  once it's wiped out.
- **Reproducibility**: all of the above randomization is driven by
  `MissionSpec.random_seed` (optional). Leave it unset for a fresh layout on
  every generation, or set it to get the exact same route/threat layout back
  again.

Both layers sit on top of a fully valid static mission — if the dynamic Lua
were ever to no-op for any reason, the mission still loads and flies fine.

## Roadmap

- Red-side player missions
- More mission types (SEAD, escort, CSAR, transport)
- MOOSE `AI_A2A_DISPATCHER` / `AI_A2G_DISPATCHER` for genuinely emergent AI
  behavior instead of the current SPAWN/scheduler-based dynamism
- Richer ground-target compositions (proper SAM sites, IADS)
- Packaged desktop builds (no manual `venv`/`npm install` setup)
