"""
Statcast pitch-level extraction and aggregation.

Everything here operates on either:
  (a) raw MLB Stats API ``game/{pk}/feed/live`` JSON, or
  (b) a list of pitch dicts previously extracted via ``extract_pitch_logs``
      and cached in ``game_logs.pitches_json``.
"""

from __future__ import annotations

import math
from typing import Optional

# ── Pitch result-code classifications ──────────────────────────────────────
# Source: MLB Stats API ``details.code`` values.

SWING_CODES = {"S", "W", "F", "T", "M", "X", "D", "E", "Z", "L", "Q"}
# S=swinging strike, W=swinging strike blocked, F=foul, T=foul tip,
# M=missed bunt, L=foul bunt, X=in play out, D=in play no-out, E=in play run(s),
# Z=swinging pitchout, Q=swinging pitchout missed

WHIFF_CODES = {"S", "W", "T", "M", "Q"}
# T=foul tip (counts as swinging strike per Statcast), Q=swinging pitchout missed

CALLED_STRIKE_CODES = {"C"}

# ── wOBA weights by year (FanGraphs MLB guts table) ──────────────────────
# Columns: walk, hbp, single, double, triple, home_run
# Source: https://www.fangraphs.com/guts.aspx?type=cn
_W = {
    2026: {"walk": 0.711, "hbp": 0.743, "single": 0.909, "double": 1.292, "triple": 1.636, "home_run": 2.105},
    2025: {"walk": 0.691, "hbp": 0.722, "single": 0.882, "double": 1.252, "triple": 1.584, "home_run": 2.037},
    2024: {"walk": 0.689, "hbp": 0.720, "single": 0.882, "double": 1.254, "triple": 1.590, "home_run": 2.050},
    2023: {"walk": 0.696, "hbp": 0.726, "single": 0.883, "double": 1.244, "triple": 1.569, "home_run": 2.004},
    2022: {"walk": 0.689, "hbp": 0.720, "single": 0.884, "double": 1.261, "triple": 1.601, "home_run": 2.072},
    2021: {"walk": 0.692, "hbp": 0.722, "single": 0.879, "double": 1.242, "triple": 1.568, "home_run": 2.007},
    2020: {"walk": 0.699, "hbp": 0.728, "single": 0.883, "double": 1.238, "triple": 1.558, "home_run": 1.979},
    2019: {"walk": 0.690, "hbp": 0.719, "single": 0.870, "double": 1.217, "triple": 1.529, "home_run": 1.940},
}
# Fallback for years not in the table (use the oldest available year)
_WOBA_FALLBACK = _W[2019]


def get_woba_weights(year: Optional[int] = None) -> dict:
    """Return the FanGraphs wOBA weights for *year*, falling back gracefully."""
    if year is None:
        return _W.get(max(_W), _WOBA_FALLBACK)
    return _W.get(year, _WOBA_FALLBACK)


# PA event strings from MLB Stats API ``result.eventType`` that count as wOBA outcomes.
WOBA_EVENT_MAP = {
    "walk": "walk",
    "hit_by_pitch": "hbp",
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "home_run",
}

# ── Known FIP constants per (sport_level, year). 2024 values precomputed ──
FIP_CONSTANTS = {
    ("MLB", 2024): 3.247,
    ("AAA", 2024): 3.896,
    ("AA", 2024): 3.613,
    ("A+", 2024): 3.586,
    ("A", 2024): 3.733,
}

# League RA/9 used in xWPCT formula (approximate)
LEAGUE_RA9 = {
    "MLB": 4.40,
    "AAA": 5.10,
    "AA": 4.80,
    "A+": 4.60,
    "A": 4.70,
}

# Baserunning play events that occur during a batter's PA but do NOT
# constitute a plate appearance outcome for the batter (e.g. caught stealing,
# pickoff outs).  Pitches ending in these events must be excluded from batter
# wOBA / AB / PA calculations.
_NON_PA_EVENTS: frozenset[str] = frozenset({
    "caught_stealing_2b",
    "caught_stealing_3b",
    "caught_stealing_home",
    "pickoff_caught_stealing_2b",
    "pickoff_caught_stealing_3b",
    "pickoff_caught_stealing_home",
    "pickoff_1b",
    "pickoff_2b",
    "pickoff_3b",
    "game_advisory",
    "other_advance",
})

_BAT_SIDE_SPLITS = (
    ("all", "全部"),
    ("L", "左打"),
    ("R", "右打"),
)

_COUNT_USAGE_BUCKETS = (
    {
        "key": "early",
        "label": "前段球數",
        "counts_label": "0-0, 0-1, 1-0",
        "counts": {(0, 0), (0, 1), (1, 0)},
    },
    {
        "key": "pitcher_ahead",
        "label": "球數領先",
        "counts_label": "0-1, 0-2, 1-2, 2-2",
        "counts": {(0, 1), (0, 2), (1, 2), (2, 2)},
    },
    {
        "key": "pitcher_behind",
        "label": "球數落後",
        "counts_label": "1-0, 2-0, 3-0, 2-1, 3-1",
        "counts": {(1, 0), (2, 0), (3, 0), (2, 1), (3, 1)},
    },
    {
        "key": "pre_two_strikes",
        "label": "兩好球前",
        "counts_label": "0-0, 0-1, 1-0, 1-1, 2-1, 3-1",
        "counts": {(0, 0), (0, 1), (1, 0), (1, 1), (2, 1), (3, 1)},
    },
    {
        "key": "two_strikes",
        "label": "兩好球後",
        "counts_label": "0-2, 1-2, 2-2, 3-2",
        "counts": {(0, 2), (1, 2), (2, 2), (3, 2)},
    },
)

_PLINKO_COUNTS = (
    (0, 0), (0, 1), (1, 0), (0, 2), (1, 1), (2, 0),
    (1, 2), (2, 1), (3, 0), (2, 2), (3, 1), (3, 2),
)

_PLINKO_EDGES = (
    ("0-0", "0-1"), ("0-0", "1-0"),
    ("0-1", "0-2"), ("0-1", "1-1"),
    ("1-0", "1-1"), ("1-0", "2-0"),
    ("0-2", "1-2"),
    ("1-1", "1-2"), ("1-1", "2-1"),
    ("2-0", "2-1"), ("2-0", "3-0"),
    ("1-2", "2-2"),
    ("2-1", "2-2"), ("2-1", "3-1"),
    ("3-0", "3-1"),
    ("2-2", "3-2"), ("3-1", "3-2"),
)

_BATTER_PLINKO_SPLITS = (
    ("L", "vs LHP"),
    ("R", "vs RHP"),
)

_PITCHER_PLINKO_SPLITS = (
    ("L", "vs LHB"),
    ("R", "vs RHB"),
)

_BATTER_PLINKO_SKIP_TYPES = {"EP", "FA"}

_GB_TRAJECTORIES = {"ground_ball", "bunt_grounder"}
_LD_TRAJECTORIES = {"line_drive", "bunt_line_drive"}
_FB_TRAJECTORIES = {"fly_ball"}
_PU_TRAJECTORIES = {"popup", "bunt_popup"}
_AIR_TRAJECTORIES = _LD_TRAJECTORIES | _FB_TRAJECTORIES
_PULL_AIR_TRAJECTORIES = _AIR_TRAJECTORIES

_BATTED_BALL_RATE_DIGITS = 6
# MLB Gameday hit coordinate origin and spray-angle formula.
# Source: Jeff & Darrell Zimmerman / Bill Petti, The Hardball Times (2017)
# https://tht.fangraphs.com/research-notebook-new-format-for-statcast-data-export-at-baseball-savant/
# Formula: atan((hc_x - 125.42) / (198.27 - hc_y)) * 180/pi * 0.75
# The 0.75 factor corrects for the perspective distortion of the Gameday spray chart image.
_GAMEDAY_HOME_X = 125.42
_GAMEDAY_HOME_Y = 198.27
_GAMEDAY_SPRAY_CORRECTION = 0.75
_GAMEDAY_LEFT_FIELD_THRESHOLD_DEG = 15.0
_GAMEDAY_RIGHT_FIELD_THRESHOLD_DEG = 15.0

# MLB Stats API hitData.location → broad field zone (LF / CF / RF).
# Used as fallback when hit coordinates are unavailable.
# '1'=Pitcher, '2'=Catcher, '3'=1B, '4'=2B, '5'=3B, '6'=SS,
# '7'=LF, '78'=LC, '8'=CF, '89'=RC, '9'=RF
_HIT_LOCATION_ZONE: dict[str, str] = {
    "1":  "CF",  # pitcher (e.g. comebacker)
    "2":  "CF",  # catcher (bunt)
    "3":  "RF",  # first baseman
    "4":  "CF",  # second baseman (up the middle)
    "5":  "LF",  # third baseman
    "6":  "LF",  # shortstop
    "7":  "LF",  # left fielder
    "78": "LF",  # left-center
    "8":  "CF",  # center fielder
    "89": "RF",  # right-center
    "9":  "RF",  # right fielder
}


# ══════════════════════════════════════════════════════════════════════════
# EXTRACTION
# ══════════════════════════════════════════════════════════════════════════


def extract_pitch_logs(
    game_data: dict, player_id: int, role: str
) -> list[dict]:
    """Walk a live-feed JSON and return every pitch involving ``player_id``.

    Args:
        game_data: raw JSON from ``game/{pk}/feed/live``.
        player_id: MLB ID to filter for.
        role: ``"pitcher"`` or ``"batter"`` — which side of the matchup to
              match on.

    Returns a list of pitch dicts in chronological order.
    """
    if not game_data:
        return []
    plays = (
        game_data.get("liveData", {})
        .get("plays", {})
        .get("allPlays", [])
    )
    if not plays:
        return []

    out: list[dict] = []
    for play in plays:
        matchup = play.get("matchup", {})
        pitcher_id = matchup.get("pitcher", {}).get("id")
        batter_id = matchup.get("batter", {}).get("id")

        if role == "pitcher" and pitcher_id != player_id:
            continue
        if role == "batter" and batter_id != player_id:
            continue

        events = play.get("playEvents", [])
        # Find the index of the LAST pitch in the PA (for wOBA attribution)
        pitch_indices = [i for i, e in enumerate(events) if e.get("isPitch")]
        if not pitch_indices:
            continue
        last_pitch_idx = pitch_indices[-1]

        result = play.get("result", {}) or {}
        event_type = result.get("eventType", "")
        event_desc = result.get("event", "")
        about = play.get("about", {}) or {}

        # Track pre-pitch strike count within this PA.
        # First pitch of every PA starts at 0-0.  For subsequent pitches the
        # pre-pitch count equals the previous pitch's post-pitch count.
        pa_pre_balls = 0
        pa_pre_strikes = 0

        for i, ev in enumerate(events):
            if not ev.get("isPitch"):
                continue
            details = ev.get("details", {}) or {}
            pdata = ev.get("pitchData", {}) or {}
            hdata = ev.get("hitData", {}) or {}
            coords = pdata.get("coordinates", {}) or {}
            hit_coords = hdata.get("coordinates", {}) or {}
            breaks = pdata.get("breaks", {}) or {}
            count = ev.get("count", {}) or {}

            pitch_type_obj = details.get("type") or {}
            is_final = i == last_pitch_idx

            post_balls = count.get("balls", 0)
            post_strikes = count.get("strikes", 0)

            out.append({
                "game_pk": game_data.get("gamePk"),
                "inning": about.get("inning"),
                "pitch_type": pitch_type_obj.get("code", ""),
                "pitch_name": pitch_type_obj.get("description", ""),
                "result_code": details.get("code", ""),
                "result_desc": details.get("description", ""),
                "is_strike": bool(details.get("isStrike")),
                "is_ball": bool(details.get("isBall")),
                "is_in_play": bool(details.get("isInPlay")),
                "zone": pdata.get("zone"),
                "start_speed": pdata.get("startSpeed"),
                "end_speed": pdata.get("endSpeed"),
                "extension": pdata.get("extension"),
                "pfx_x": coords.get("pfxX"),
                "pfx_z": coords.get("pfxZ"),
                "px": coords.get("pX"),
                "pz": coords.get("pZ"),
                "x0": coords.get("x0"),
                "z0": coords.get("z0"),
                "ivb": breaks.get("breakVerticalInduced"),
                "hb": breaks.get("breakHorizontal"),
                "spin_rate": breaks.get("spinRate"),
                "spin_dir": breaks.get("spinDirection"),
                "ev": hdata.get("launchSpeed"),
                "la": hdata.get("launchAngle"),
                "hit_distance": hdata.get("totalDistance"),
                "trajectory": hdata.get("trajectory", ""),
                "hit_location": hdata.get("location"),
                "hit_coord_x": hit_coords.get("coordX"),
                "hit_coord_y": hit_coords.get("coordY"),
                "hardness": hdata.get("hardness", ""),
                "balls": count.get("balls"),
                "strikes": post_strikes,
                "pre_balls": pa_pre_balls,
                "pre_strikes": pa_pre_strikes,
                "outs": count.get("outs"),
                "batter_id": batter_id,
                "pitcher_id": pitcher_id,
                "bat_side": matchup.get("batSide", {}).get("code", ""),
                "pitch_hand": matchup.get("pitchHand", {}).get("code", ""),
                "is_pa_final": is_final,
                "pa_event": event_type if is_final else "",
                "pa_event_desc": event_desc if is_final else "",
            })

            # Advance pre-pitch tracker: next pitch's pre-count =
            # this pitch's post-count.
            pa_pre_balls = post_balls
            pa_pre_strikes = post_strikes

    return out


def _ensure_pre_strikes(pitches: list[dict]) -> None:
    """Annotate pre-pitch count fields on pitches that lack them.

    Walks the list in order, grouped by ``game_pk``. Within each game the
    pitches are assumed to be in chronological PA order (as produced by
    ``extract_pitch_logs``). The first pitch of each PA starts at 0-0;
    subsequent pitches inherit the previous pitch's post-pitch count.

    Always recomputes for pitches missing the field, even when other pitches
    in the same list already have it (handles mixed old/new cached data).
    """
    if not pitches:
        return
    # Fast path: if ALL pitches already have the fields, nothing to do.
    if all("pre_balls" in p and "pre_strikes" in p for p in pitches):
        return

    pre_balls = 0
    pre_strikes = 0
    last_game_pk = None
    for p in pitches:
        gpk = p.get("game_pk")
        if gpk != last_game_pk:
            # New game boundary — reset to start of a fresh PA.
            pre_balls = 0
            pre_strikes = 0
            last_game_pk = gpk

        p["pre_balls"] = pre_balls
        p["pre_strikes"] = pre_strikes

        if p.get("is_pa_final"):
            pre_balls = 0
            pre_strikes = 0  # next pitch starts a new PA
        else:
            pre_balls = p.get("balls", 0) or 0
            pre_strikes = p.get("strikes", 0) or 0


# ══════════════════════════════════════════════════════════════════════════
# CLASSIFICATION HELPERS
# ══════════════════════════════════════════════════════════════════════════


def _is_swing(p: dict) -> bool:
    return p.get("result_code", "") in SWING_CODES


def _is_whiff(p: dict) -> bool:
    return p.get("result_code", "") in WHIFF_CODES


def _is_called_strike(p: dict) -> bool:
    return p.get("result_code", "") in CALLED_STRIKE_CODES


def _is_in_zone(p: dict) -> bool:
    z = p.get("zone")
    return z is not None and 1 <= z <= 9


def _is_out_of_zone(p: dict) -> bool:
    z = p.get("zone")
    return z is not None and 11 <= z <= 14


def _is_barrel(ev: Optional[float], la: Optional[float]) -> bool:
    """Statcast barrel definition.

    Minimum EV is 98 mph.  At exactly 98 mph the launch-angle window is
    26°–30°.  For every additional mph above 98:
      - lower bound drops 1°/mph  (floor 8°)
      - upper bound rises 1.5°/mph (ceiling 50°)

    Anchor points:
      98 mph → [26, 30]
     100 mph → [24, 33]
     116 mph → [8,  50]  (both bounds saturated)
    """
    if ev is None or la is None:
        return False
    if ev < 98:
        return False
    delta = ev - 98.0
    la_min = max(8.0,  26.0 - delta)
    la_max = min(50.0, 30.0 + delta * 1.5)
    return la_min <= la <= la_max


def _is_sweet_spot(la: Optional[float]) -> bool:
    """Sweet spot: launch angle between 8° and 32° (inclusive)."""
    if la is None:
        return False
    return 8 <= la <= 32


# ── Math utilities ─────────────────────────────────────────────────────────


def _ratio(num, den, digits=3):
    """Safe division returning a rounded decimal or None when denominator is 0."""
    if not den:
        return None
    return round(num / den, digits)


def _mean(values):
    """Mean of non-None values, or None if empty."""
    vs = [v for v in values if v is not None]
    if not vs:
        return None
    return sum(vs) / len(vs)


def _mean_round(values, digits=1):
    """Mean of non-None values, rounded. Returns None if no valid values."""
    v = _mean(values)
    return round(v, digits) if v is not None else None


def _float_or_none(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_unknown_pitch_type(
    pitch_type: Optional[str], pitch_name: Optional[str] = None
) -> bool:
    """Return True when a pitch type is an unknown placeholder."""
    type_token = str(pitch_type or "").strip().upper()
    name_token = str(pitch_name or "").strip().upper()
    return type_token in {"", "UN", "UNKNOWN"} or name_token in {"UN", "UNKNOWN"}


def _filter_known_pitch_events(pitches: list[dict]) -> list[dict]:
    """Drop unknown pitch-type events from pitch-type breakdowns."""
    return [
        p for p in pitches
        if not _is_unknown_pitch_type(p.get("pitch_type"), p.get("pitch_name"))
    ]


def _pre_count_tuple(p: dict) -> Optional[tuple[int, int]]:
    """Return the pre-pitch (balls, strikes) tuple when available."""
    try:
        balls = p.get("pre_balls")
        strikes = p.get("pre_strikes")
        if balls is None or strikes is None:
            return None
        return int(balls), int(strikes)
    except (TypeError, ValueError):
        return None


def _post_count_tuple(p: dict) -> Optional[tuple[int, int]]:
    try:
        balls = p.get("balls")
        strikes = p.get("strikes")
        if balls is None or strikes is None:
            return None
        return int(balls), int(strikes)
    except (TypeError, ValueError):
        return None


def _count_label(count: tuple[int, int]) -> str:
    return f"{count[0]}-{count[1]}"


def _empty_plinko_nodes() -> list[dict]:
    return [
        {"count": _count_label(count), "pitches": 0, "pct": None, "pitch_types": []}
        for count in _PLINKO_COUNTS
    ]


def _empty_plinko_edges() -> list[dict]:
    return [
        {"from": from_count, "to": to_count, "pitches": 0}
        for from_count, to_count in _PLINKO_EDGES
    ]


def _compute_pitch_plinko(
    pitches: list[dict],
    *,
    split_field: str,
    split_specs: tuple[tuple[str, str], ...],
    skip_types: Optional[set[str]] = None,
) -> dict:
    """Build Pitch Plinko data split by pitcher/batter handedness."""
    valid_counts = set(_PLINKO_COUNTS)
    split_keys = {key for key, _ in split_specs}

    candidates = []
    for p in pitches:
        if p.get(split_field) not in split_keys:
            continue
        ptype = p.get("pitch_type") or "UN"
        if _is_unknown_pitch_type(ptype, p.get("pitch_name")):
            continue
        if skip_types and ptype in skip_types:
            continue
        if _pre_count_tuple(p) not in valid_counts:
            continue
        candidates.append(p)

    type_names: dict[str, str] = {}
    total_type_counts: dict[str, int] = {}
    for p in candidates:
        ptype = p.get("pitch_type") or "UN"
        if p.get("pitch_name") and type_names.get(ptype, ptype) == ptype:
            type_names[ptype] = p.get("pitch_name") or ptype
        else:
            type_names.setdefault(ptype, ptype)
        total_type_counts[ptype] = total_type_counts.get(ptype, 0) + 1

    ordered_types = sorted(total_type_counts, key=lambda t: total_type_counts[t], reverse=True)
    total = len(candidates)
    pitch_types = [
        {
            "type": t,
            "name": type_names.get(t, t),
            "count": total_type_counts[t],
            "pct": _ratio(total_type_counts[t], total, digits=4),
        }
        for t in ordered_types
    ]

    splits = []
    edge_keys = set(_PLINKO_EDGES)
    for split_key, split_label in split_specs:
        split_pitches = [p for p in candidates if p.get(split_field) == split_key]
        split_total = len(split_pitches)
        node_data = {
            _count_label(count): {"pitches": 0, "type_counts": {}}
            for count in _PLINKO_COUNTS
        }
        edge_counts = {edge: 0 for edge in _PLINKO_EDGES}

        for p in split_pitches:
            pre_count = _pre_count_tuple(p)
            if pre_count not in valid_counts:
                continue
            pre_label = _count_label(pre_count)
            ptype = p.get("pitch_type") or "UN"
            bucket = node_data[pre_label]
            bucket["pitches"] += 1
            bucket["type_counts"][ptype] = bucket["type_counts"].get(ptype, 0) + 1

            post_count = _post_count_tuple(p)
            if p.get("is_pa_final") or post_count not in valid_counts:
                continue
            edge = (pre_label, _count_label(post_count))
            if edge in edge_keys:
                edge_counts[edge] += 1

        nodes = []
        for count in _PLINKO_COUNTS:
            label = _count_label(count)
            bucket = node_data[label]
            node_total = bucket["pitches"]
            node_pitch_types = [
                {
                    "type": t,
                    "name": type_names.get(t, t),
                    "count": bucket["type_counts"].get(t, 0),
                    "pct": _ratio(bucket["type_counts"].get(t, 0), node_total, digits=4),
                }
                for t in ordered_types
                if bucket["type_counts"].get(t, 0)
            ]
            node_pitch_types.sort(key=lambda pt: pt.get("count", 0), reverse=True)
            nodes.append({
                "count": label,
                "pitches": node_total,
                "pct": _ratio(node_total, split_total, digits=4),
                "pitch_types": node_pitch_types,
            })

        splits.append({
            "key": split_key,
            "label": split_label,
            "pitches": split_total,
            "pct": _ratio(split_total, total, digits=4),
            "nodes": nodes if split_total else _empty_plinko_nodes(),
            "edges": [
                {"from": from_count, "to": to_count, "pitches": edge_counts[(from_count, to_count)]}
                for from_count, to_count in _PLINKO_EDGES
            ] if split_total else _empty_plinko_edges(),
        })

    return {"total_pitches": total, "pitch_types": pitch_types, "splits": splits}


def compute_pitch_movement_chart(
    pitches: list[dict], max_points: Optional[int] = 700
) -> dict:
    """Return lightweight per-pitch movement points for pitcher charts."""
    points = []
    type_names: dict[str, str] = {}
    type_counts: dict[str, int] = {}

    for p in _filter_known_pitch_events(pitches):
        hb = _float_or_none(p.get("hb"))
        ivb = _float_or_none(p.get("ivb"))
        if hb is None or ivb is None:
            continue

        ptype = p.get("pitch_type") or "UN"
        name = p.get("pitch_name") or ptype
        type_names.setdefault(ptype, name)
        if p.get("pitch_name") and type_names.get(ptype, ptype) == ptype:
            type_names[ptype] = p.get("pitch_name") or ptype
        type_counts[ptype] = type_counts.get(ptype, 0) + 1

        point = {
            "type": ptype,
            "name": type_names.get(ptype, name),
            "hb": round(hb, 1),
            "ivb": round(ivb, 1),
        }
        velo = _float_or_none(p.get("start_speed"))
        spin = _float_or_none(p.get("spin_rate"))
        if velo is not None:
            point["velo"] = round(velo, 1)
        if spin is not None:
            point["spin"] = int(round(spin))
        points.append(point)

    total = len(points)
    if max_points and total > max_points:
        step = total / max_points
        points = [points[min(total - 1, int(i * step))] for i in range(max_points)]

    ordered_types = sorted(type_counts, key=lambda t: type_counts[t], reverse=True)
    pitch_types = [
        {
            "type": t,
            "name": type_names.get(t, t),
            "count": type_counts[t],
            "pct": _ratio(type_counts[t], total, digits=4),
        }
        for t in ordered_types
    ]

    return {
        "total_pitches": total,
        "shown_pitches": len(points),
        "pitch_types": pitch_types,
        "points": points,
    }


# ══════════════════════════════════════════════════════════════════════════
# SHARED AGGREGATION HELPERS
# ══════════════════════════════════════════════════════════════════════════


def _spray_direction_from_location(p: dict) -> Optional[str]:
    """Fallback: classify spray direction using hitData.location fielder code.

    Used when hit coordinates are unavailable.  The location code is mapped
    to a broad field zone (LF / CF / RF) via ``_HIT_LOCATION_ZONE``, then
    combined with the batter's handedness to produce pull / straight / oppo.
    """
    zone = _HIT_LOCATION_ZONE.get(str(p.get("hit_location", "") or ""))
    if zone is None:
        return None
    if zone == "CF":
        return "straight"
    bat = p.get("bat_side", "R")
    if bat == "L":
        return "pull" if zone == "RF" else "oppo"
    return "pull" if zone == "LF" else "oppo"


def _spray_direction_from_coordinates(p: dict) -> Optional[str]:
    """Classify batted-ball direction from MLB Gameday hit coordinates.

    座標系統說明（MLB Gameday 250×250 像素噴射圖）：
      - 原點 (0, 0) 在圖片左上角
      - X 軸向右遞增（從打者視角：朝右外野方向）
      - Y 軸向下遞增（朝本壘板 / 捕手方向）
      - 本壘板位於圖片下方中央 (HOME_X ≈ 125, HOME_Y ≈ 198)

    角度計算公式：
      angle = atan2(hc_x − HOME_X,  HOME_Y − hc_y) × 0.75

      atan2 的兩個引數（dx, dy）：
        dx = hc_x − HOME_X  正值 → 球落在本壘板右側（RF 方向）
                             負值 → 球落在本壘板左側（LF 方向）
        dy = HOME_Y − hc_y  正值 → 球落在本壘板前方（往外野方向，正常擊球）
                             負值 → 球落在本壘板後方（捕手後方的高飛球）

      atan2(dx, dy) 而非 atan2(dy, dx)：
        標準 atan2(y, x) 以「正 X 軸」為 0°。這裡將引數對調，
        改以「正 dy 軸（直線方向 / CF）」為 0°，左負右正，
        使得 0° = 中外野正中, +45° ≈ 一壘線, −45° ≈ 三壘線。

      × 0.75 修正係數：
        Gameday 噴射圖是從斜上方的俯瞰視角，圖像在橫向（左右）比
        縱深（本壘→外野）更「壓縮」，導致同樣真實角度在圖上橫向偏移
        看起來比實際大。乘以 0.75 補正此透視變形，修正後的角度尺度中
        −45° = 三壘界外線, +45° = 一壘界外線。

    閾值說明：
      修正後 ±15° 作為 Pull / Straight / Oppo 的分界，
      對應修正前原始角度的約 ±20°（±15° / 0.75 = ±20°）。

    參考來源：
      Jeff & Darrell Zimmerman / Bill Petti, The Hardball Times (2017)
      https://tht.fangraphs.com/research-notebook-new-format-for-statcast-data-export-at-baseball-savant/
    """
    x = p.get("hit_coord_x")
    y = p.get("hit_coord_y")
    if x is None or y is None:
        return None
    try:
        # dx > 0 → RF 側；dy > 0 → 外野方向（正常擊球）
        # atan2(dx, dy) 使 0° 指向 CF，正角往 RF，負角往 LF
        # × 0.75 補正噴射圖的透視壓縮變形
        angle = math.degrees(
            math.atan2(float(x) - _GAMEDAY_HOME_X, _GAMEDAY_HOME_Y - float(y))
        ) * _GAMEDAY_SPRAY_CORRECTION
    except (TypeError, ValueError):
        return None

    if angle < -_GAMEDAY_LEFT_FIELD_THRESHOLD_DEG:
        field = "LF"
    elif angle > _GAMEDAY_RIGHT_FIELD_THRESHOLD_DEG:
        field = "RF"
    else:
        field = "CF"

    if field == "CF":
        return "straight"
    bat = p.get("bat_side", "R")
    if bat == "L":
        return "pull" if field == "RF" else "oppo"
    return "pull" if field == "LF" else "oppo"


def _compute_spray(in_play: list[dict]) -> dict:
    """Return batted-ball direction counts from in-play pitch dicts.

    For each batted ball, tries coordinate-based classification first;
    falls back to hitData.location + bat_side when coordinates are absent.
    """
    pull = straight = oppo = pull_air = spray_total = 0
    for p in in_play:
        direction = _spray_direction_from_coordinates(p)
        if direction is None:
            direction = _spray_direction_from_location(p)
        if direction is None:
            continue
        spray_total += 1
        if direction == "straight":
            straight += 1
        elif direction == "pull":
            pull += 1
            if p.get("trajectory", "") in _PULL_AIR_TRAJECTORIES:
                pull_air += 1
        elif direction == "oppo":
            oppo += 1
    return {
        "pull": pull,
        "straight": straight,
        "oppo": oppo,
        "pull_air": pull_air,
        "spray_total": spray_total,
    }


def _aggregate_pitches(pitches: list[dict]) -> dict:
    """Classify a list of pitches into common categories.

    Returns a dict with pre-filtered lists and counts shared by both
    pitcher and batter aggregation paths.
    """
    swings: list[dict] = []
    whiffs: list[dict] = []
    called: list[dict] = []
    in_zone: list[dict] = []
    out_zone: list[dict] = []
    in_zone_swings: list[dict] = []
    out_zone_swings: list[dict] = []
    in_zone_contact: list[dict] = []
    in_play: list[dict] = []
    bbe_ev: list[dict] = []
    pa_final: list[dict] = []
    gb = fb = ld = pu = barrels = hard_hits = 0

    for p in pitches:
        is_sw = _is_swing(p)
        is_wh = _is_whiff(p)
        in_z  = _is_in_zone(p)
        out_z = _is_out_of_zone(p)

        if is_sw:
            swings.append(p)
        if is_wh:
            whiffs.append(p)
        if _is_called_strike(p):
            called.append(p)
        if in_z:
            in_zone.append(p)
            if is_sw:
                in_zone_swings.append(p)
                if not is_wh:
                    in_zone_contact.append(p)
        if out_z:
            out_zone.append(p)
            if is_sw:
                out_zone_swings.append(p)
        if p.get("is_in_play"):
            in_play.append(p)
            ev = p.get("ev")
            if ev is not None:
                bbe_ev.append(p)
                if ev >= 95:
                    hard_hits += 1
            if _is_barrel(ev, p.get("la")):
                barrels += 1
            traj = p.get("trajectory", "")
            if traj in _GB_TRAJECTORIES:
                gb += 1
            elif traj in _LD_TRAJECTORIES:
                ld += 1
            elif traj in _FB_TRAJECTORIES:
                fb += 1
            elif traj in _PU_TRAJECTORIES:
                pu += 1
        if p.get("is_pa_final"):
            pa_final.append(p)

    spray = _compute_spray(in_play)
    return {
        "total": len(pitches),
        "swings": swings,
        "whiffs": whiffs,
        "called": called,
        "in_zone": in_zone,
        "out_zone": out_zone,
        "in_zone_swings": in_zone_swings,
        "out_zone_swings": out_zone_swings,
        "in_zone_contact": in_zone_contact,
        "in_play": in_play,
        "bbe_ev": bbe_ev,
        "pa_final": pa_final,
        "gb": gb,
        "fb": fb,
        "ld": ld,
        "pu": pu,
        "pull": spray["pull"],
        "straight": spray["straight"],
        "oppo": spray["oppo"],
        "pull_air": spray["pull_air"],
        "spray_total": spray["spray_total"],
        "barrels": barrels,
        "hard_hits": hard_hits,
    }


def _compute_woba(pa_final: list[dict], woba_w: dict) -> tuple[float, int]:
    """Compute wOBA numerator and denominator from PA-final pitches.

    Excludes intentional walks, sacrifice bunts, and non-PA baserunning
    events (caught stealing, pickoffs) from the denominator.
    """
    woba_num = 0.0
    woba_den = 0
    for p in pa_final:
        ev = p.get("pa_event", "")
        if ev in ("intent_walk", "sac_bunt") or ev in _NON_PA_EVENTS:
            continue
        woba_den += 1
        key = WOBA_EVENT_MAP.get(ev)
        if key:
            woba_num += woba_w[key]
    return woba_num, woba_den


def _discipline_metrics(agg: dict) -> dict:
    """Build plate-discipline metrics dict from _aggregate_pitches output."""
    total = agg["total"]
    return {
        "swing_pct": _ratio(len(agg["swings"]), total),
        "whiff_pct": _ratio(len(agg["whiffs"]), len(agg["swings"])),
        "swstr_pct": _ratio(len(agg["whiffs"]), total),
        "csw_pct": _ratio(len(agg["called"]) + len(agg["whiffs"]), total),
        "z_swing_pct": _ratio(len(agg["in_zone_swings"]), len(agg["in_zone"])),
        "o_swing_pct": _ratio(len(agg["out_zone_swings"]), len(agg["out_zone"])),
        "z_contact_pct": _ratio(len(agg["in_zone_contact"]), len(agg["in_zone_swings"])),
        "zone_pct": _ratio(len(agg["in_zone"]), len(agg["in_zone"]) + len(agg["out_zone"])),
    }


def _batted_ball_metrics(agg: dict, sport_level: str = "") -> dict:
    """Build batted-ball metrics dict from _aggregate_pitches output."""
    n_ip = len(agg["in_play"])
    n_ev = len(agg["bbe_ev"])
    spray_available = (agg.get("spray_total") or 0) > 0
    metrics = {
        "bbe": n_ip,
        "gb_pct": _ratio(agg["gb"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
        "ld_pct": _ratio(agg["ld"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
        "fb_pct": _ratio(agg["fb"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
        "pu_pct": _ratio(agg["pu"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
        "air_pct": _ratio(
            agg["ld"] + agg["fb"], n_ip, digits=_BATTED_BALL_RATE_DIGITS
        ),
        "pull_pct": None,
        "straight_pct": None,
        "oppo_pct": None,
        "pull_air_pct": None,
        "barrel_pct": _ratio(agg["barrels"], n_ip),
        "hard_hit_pct": _ratio(agg["hard_hits"], n_ev),
        "avg_ev": _mean_round([p["ev"] for p in agg["bbe_ev"]], 1),
    }
    if spray_available:
        metrics.update({
            "pull_pct": _ratio(agg["pull"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
            "straight_pct": _ratio(agg["straight"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
            "oppo_pct": _ratio(agg["oppo"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
            "pull_air_pct": _ratio(agg["pull_air"], n_ip, digits=_BATTED_BALL_RATE_DIGITS),
        })
    return metrics


# ══════════════════════════════════════════════════════════════════════════
# PITCHER AGGREGATION
# ══════════════════════════════════════════════════════════════════════════


def compute_pitcher_statcast(
    pitches: list[dict], year: Optional[int] = None, sport_level: str = ""
) -> dict:
    """Season-level pitcher aggregates from pitch list."""
    if not pitches:
        return {}

    _ensure_pre_strikes(pitches)

    woba_w = get_woba_weights(year)
    agg = _aggregate_pitches(pitches)
    woba_num, woba_den = _compute_woba(agg["pa_final"], woba_w)
    bat_side_splits = _compute_pitcher_bat_side_splits(pitches, year=year)

    hr = sum(1 for p in agg["pa_final"] if p.get("pa_event") == "home_run")

    result = {
        "total_pitches": agg["total"],
        "pa_count": woba_den,
        "woba_against": _ratio(woba_num, woba_den),
        "hr_fb_pct": _ratio(hr, agg["fb"]),
        "avg_extension": _mean_round([p.get("extension") for p in pitches], 2),
        "pitch_arsenal": bat_side_splits["all"]["pitch_arsenal"],
        "pitch_outcomes": bat_side_splits["all"]["pitch_outcomes"],
        "pitch_usage_by_count": bat_side_splits["all"]["pitch_usage_by_count"],
        "pitcher_bat_side_splits": bat_side_splits,
        "pitch_plinko": _compute_pitch_plinko(
            pitches,
            split_field="bat_side",
            split_specs=_PITCHER_PLINKO_SPLITS,
        ),
        "pitch_movement": compute_pitch_movement_chart(pitches),
    }
    result.update(_discipline_metrics(agg))
    result.update(_batted_ball_metrics(agg, sport_level=sport_level))
    return result


def _compute_pitch_arsenal_pitcher(pitches: list[dict], year: Optional[int] = None) -> list[dict]:
    """Per-pitch-type breakdown for a pitcher."""
    pitches = _filter_known_pitch_events(pitches)
    if not pitches:
        return []

    total = len(pitches)
    woba_w = get_woba_weights(year)

    by_type: dict[str, list[dict]] = {}
    for p in pitches:
        t = p.get("pitch_type") or "UN"
        by_type.setdefault(t, []).append(p)

    out = []
    for ptype, ps in by_type.items():
        n = len(ps)
        agg = _aggregate_pitches(ps)
        woba_num, woba_den = _compute_woba(agg["pa_final"], woba_w)
        name = next((p.get("pitch_name") for p in ps if p.get("pitch_name")), ptype)

        # Put Away%: strikeouts on two-strike pitches / total two-strike pitches
        two_strike = [p for p in ps if p.get("pre_strikes") == 2]
        two_strike_strikeouts = sum(
            1 for p in two_strike
            if p.get("is_pa_final")
            and p.get("pa_event") in ("strikeout", "strikeout_double_play")
        )

        out.append({
            "type": ptype,
            "name": name,
            "count": n,
            "pct": _ratio(n, total),
            "velo": _mean_round([p.get("start_speed") for p in ps], 1),
            "ivb": _mean_round([p.get("ivb") for p in ps], 1),
            "hb": _mean_round([p.get("hb") for p in ps], 1),
            "spin": _mean_round([p.get("spin_rate") for p in ps], 0),
            "extension": _mean_round([p.get("extension") for p in ps], 2),
            "v_rel": _mean_round([p.get("z0") for p in ps], 2),
            "h_rel": _mean_round([p.get("x0") for p in ps], 2),
            "zone_pct": _ratio(len(agg["in_zone"]), len(agg["in_zone"]) + len(agg["out_zone"])),
            "chase_pct": _ratio(len(agg["out_zone_swings"]), len(agg["out_zone"])),
            "whiff_pct": _ratio(len(agg["whiffs"]), len(agg["swings"])),
            "put_away_pct": _ratio(two_strike_strikeouts, len(two_strike)),
            "two_strike_count": len(two_strike),
            "woba": _ratio(woba_num, woba_den),
        })
    out.sort(key=lambda r: r.get("count", 0), reverse=True)
    return out


def _compute_pitch_outcomes_pitcher(pitches: list[dict], year: Optional[int] = None) -> list[dict]:
    """Per-pitch-type outcome breakdown for a pitcher."""
    pitches = _filter_known_pitch_events(pitches)
    if not pitches:
        return []

    total = len(pitches)
    woba_w = get_woba_weights(year)

    by_type: dict[str, list[dict]] = {}
    for p in pitches:
        t = p.get("pitch_type") or "UN"
        by_type.setdefault(t, []).append(p)

    out = []
    for ptype, ps in by_type.items():
        n = len(ps)
        agg = _aggregate_pitches(ps)
        two_strike = [p for p in ps if p.get("pre_strikes") == 2]
        strikes = sum(1 for p in ps if p.get("is_strike") or p.get("is_in_play"))

        hits = 0
        ab = 0
        woba_num = 0.0
        woba_den = 0
        for p in agg["pa_final"]:
            ev = p.get("pa_event", "")
            if ev in _NON_PA_EVENTS:
                continue
            if ev in ("intent_walk", "sac_bunt"):
                continue
            woba_den += 1
            key = WOBA_EVENT_MAP.get(ev)
            if key:
                woba_num += woba_w[key]
            if ev not in ("walk", "hit_by_pitch", "sac_fly", "sac_bunt", "intent_walk"):
                ab += 1
                if ev in ("single", "double", "triple", "home_run"):
                    hits += 1

        two_strike_strikeouts = sum(
            1 for p in two_strike
            if p.get("is_pa_final")
            and p.get("pa_event") in ("strikeout", "strikeout_double_play")
        )
        zone_whiffs = sum(1 for p in agg["in_zone"] if _is_whiff(p))
        name = next((p.get("pitch_name") for p in ps if p.get("pitch_name")), ptype)

        out.append({
            "type": ptype,
            "name": name,
            "count": n,
            "pct": _ratio(n, total),
            "strike_pct": _ratio(strikes, n),
            "z_whiff_pct": _ratio(zone_whiffs, len(agg["in_zone_swings"])),
            "o_swing_pct": _ratio(len(agg["out_zone_swings"]), len(agg["out_zone"])),
            "swstr_pct": _ratio(len(agg["whiffs"]), n),
            "csw_pct": _ratio(len(agg["called"]) + len(agg["whiffs"]), n),
            "put_away_pct": _ratio(two_strike_strikeouts, len(two_strike)),
            "two_strike_count": len(two_strike),
            "avg": _ratio(hits, ab),
            "woba": _ratio(woba_num, woba_den),
            "barrel_pct": _ratio(agg["barrels"], len(agg["in_play"])),
            "hard_hit_pct": _ratio(agg["hard_hits"], len(agg["bbe_ev"])),
        })
    out.sort(key=lambda r: r.get("count", 0), reverse=True)
    return out


def _compute_pitch_usage_by_count_pitcher(pitches: list[dict]) -> dict:
    """Pitch-type usage percentages for common ball-strike count buckets."""
    pitches = _filter_known_pitch_events(pitches)
    if not pitches:
        return {"pitch_types": [], "rows": []}

    type_counts: dict[str, int] = {}
    type_names: dict[str, str] = {}
    for p in pitches:
        ptype = p.get("pitch_type") or "UN"
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        if p.get("pitch_name") and type_names.get(ptype, ptype) == ptype:
            type_names[ptype] = p.get("pitch_name") or ptype
        else:
            type_names.setdefault(ptype, ptype)

    ordered_types = sorted(type_counts, key=lambda t: type_counts[t], reverse=True)
    pitch_types = [
        {"type": t, "name": type_names.get(t, t), "count": type_counts[t]}
        for t in ordered_types
    ]

    rows = []
    for bucket in _COUNT_USAGE_BUCKETS:
        count_set = bucket["counts"]
        if count_set is None:
            bucket_pitches = pitches
        else:
            bucket_pitches = [p for p in pitches if _pre_count_tuple(p) in count_set]

        bucket_total = len(bucket_pitches)
        bucket_type_counts = {t: 0 for t in ordered_types}
        for p in bucket_pitches:
            ptype = p.get("pitch_type") or "UN"
            if ptype in bucket_type_counts:
                bucket_type_counts[ptype] += 1

        rows.append({
            "key": bucket["key"],
            "label": bucket["label"],
            "counts_label": bucket["counts_label"],
            "pitches": bucket_total,
            "pitch_types": [
                {
                    "type": t,
                    "name": type_names.get(t, t),
                    "count": bucket_type_counts[t],
                    "pct": _ratio(bucket_type_counts[t], bucket_total),
                }
                for t in ordered_types
            ],
        })

    return {"pitch_types": pitch_types, "rows": rows}


def _compute_pitcher_bat_side_splits(
    pitches: list[dict], year: Optional[int] = None
) -> dict[str, dict]:
    """Build all/L/R batter-side pitch-type tables for pitchers."""
    splits: dict[str, dict] = {}
    for key, label in _BAT_SIDE_SPLITS:
        if key == "all":
            split_pitches = pitches
        else:
            split_pitches = [p for p in pitches if p.get("bat_side") == key]

        splits[key] = {
            "key": key,
            "label": label,
            "pitch_arsenal": _compute_pitch_arsenal_pitcher(split_pitches, year=year),
            "pitch_outcomes": _compute_pitch_outcomes_pitcher(split_pitches, year=year),
            "pitch_usage_by_count": _compute_pitch_usage_by_count_pitcher(split_pitches),
        }
    return splits


# ══════════════════════════════════════════════════════════════════════════
# BATTER AGGREGATION
# ══════════════════════════════════════════════════════════════════════════


def compute_batter_statcast(
    pitches: list[dict], year: Optional[int] = None, sport_level: str = ""
) -> dict:
    """Season-level batter aggregates from pitch list."""
    if not pitches:
        return {}

    # Ensure every pitch has a pre_strikes field (backfills cached data
    # that predates the field being added to extract_pitch_logs).
    _ensure_pre_strikes(pitches)

    woba_w = get_woba_weights(year)
    agg = _aggregate_pitches(pitches)
    woba_num, woba_den = _compute_woba(agg["pa_final"], woba_w)

    # 此部分若ev_values數據量小於10 則算出數據與tjstats不符
    ev_values = sorted([p["ev"] for p in agg["bbe_ev"]])  # ascending for percentile
    ev90 = None
    if ev_values:
        # 90th percentile: the single value below which 90% of BBEs fall
        idx = min(int(len(ev_values) * 0.9), len(ev_values) - 1)
        ev90 = round(ev_values[idx], 1)

    la_values = [p["la"] for p in agg["bbe_ev"] if p.get("la") is not None]
    sweet_spots = sum(1 for p in agg["in_play"] if _is_sweet_spot(p.get("la")))
    strikes = sum(1 for p in pitches if p.get("is_strike") or p.get("is_in_play"))
    n_ip = len(agg["in_play"])

    result = {
        "total_pitches": agg["total"],
        "pa_count": woba_den,
        "strike_pct": _ratio(strikes, agg["total"]),
        "woba": _ratio(woba_num, woba_den),
        "max_ev": round(max(p["ev"] for p in agg["bbe_ev"]), 1) if agg["bbe_ev"] else None,
        "ev90": ev90,
        "avg_la": _mean_round(la_values, 1),
        "swsp_pct": _ratio(sweet_spots, len(la_values)),
        "vs_pitch_types": _compute_vs_pitch_types_batter(pitches, year=year),
        "pitch_plinko": _compute_pitch_plinko(
            pitches,
            split_field="pitch_hand",
            split_specs=_BATTER_PLINKO_SPLITS,
            skip_types=_BATTER_PLINKO_SKIP_TYPES,
        ),
    }
    result.update(_discipline_metrics(agg))
    result.update(_batted_ball_metrics(agg, sport_level=sport_level))
    return result


def _compute_vs_pitch_types_batter(pitches: list[dict], year: Optional[int] = None) -> list[dict]:
    """Per-pitch-type breakdown for a batter."""
    # EP (Eephus) and FA (generic Fastball) almost exclusively appear in
    # position-player-pitching situations (e.g. catcher or shortstop mops up
    # in a blowout).  Exclude them so they don't pollute the breakdown or
    # show as spurious pitch types (matching TJStats / Baseball Savant behaviour).
    _SKIP_TYPES = {"EP", "FA"}

    woba_w = get_woba_weights(year)
    by_type: dict[str, list[dict]] = {}
    for p in pitches:
        t = p.get("pitch_type") or "UN"
        if t in _SKIP_TYPES:
            continue
        by_type.setdefault(t, []).append(p)

    # Drop the UN (unknown) bucket when there are real named pitch types,
    # so unknown pitches don't pollute the per-type breakdown.
    if any(t != "UN" for t in by_type):
        by_type = {t: v for t, v in by_type.items() if t != "UN"}

    out = []
    for ptype, ps in by_type.items():
        n = len(ps)
        agg = _aggregate_pitches(ps)
        # Two-strike pitches: those thrown when the pre-pitch count had 2 strikes.
        # pre_strikes is computed during extraction (or backfilled by
        # _ensure_pre_strikes for legacy cached data).
        two_strike = [p for p in ps if p.get("pre_strikes") == 2]
        strikes = sum(1 for p in ps if p.get("is_strike") or p.get("is_in_play"))

        # AVG / wOBA
        hits = 0
        ab = 0
        woba_num = 0.0
        woba_den = 0
        for p in agg["pa_final"]:
            ev = p.get("pa_event", "")
            # Skip non-PA baserunning events (caught stealing, pickoffs, etc.)
            if ev in _NON_PA_EVENTS:
                continue
            if ev in ("intent_walk", "sac_bunt"):
                continue
            woba_den += 1
            key = WOBA_EVENT_MAP.get(ev)
            if key:
                woba_num += woba_w[key]
            # AB = PA - BB - HBP - SF - SH
            if ev not in ("walk", "hit_by_pitch", "sac_fly", "sac_bunt", "intent_walk"):
                ab += 1
                if ev in ("single", "double", "triple", "home_run"):
                    hits += 1

        name = next((p.get("pitch_name") for p in ps if p.get("pitch_name")), ptype)

        # Put Away%: strikeouts on two-strike pitches / total two-strike pitches
        two_strike_strikeouts = sum(
            1 for p in two_strike
            if p.get("is_pa_final")
            and p.get("pa_event") in ("strikeout", "strikeout_double_play")
        )

        out.append({
            "type": ptype,
            "name": name,
            "count": n,
            "strike_pct": _ratio(strikes, n),
            "zone_pct": _ratio(len(agg["in_zone"]), len(agg["in_zone"]) + len(agg["out_zone"])),
            "z_swing_pct": _ratio(len(agg["in_zone_swings"]), len(agg["in_zone"])),
            "o_swing_pct": _ratio(len(agg["out_zone_swings"]), len(agg["out_zone"])),
            "whiff_pct": _ratio(len(agg["whiffs"]), len(agg["swings"])),
            "swstr_pct": _ratio(len(agg["whiffs"]), n),
            "csw_pct": _ratio(len(agg["called"]) + len(agg["whiffs"]), n),
            "put_away_pct": _ratio(two_strike_strikeouts, len(two_strike)),
            "two_strike_count": len(two_strike),
            "avg": _ratio(hits, ab),
            "woba": _ratio(woba_num, woba_den),
            "barrel_pct": _ratio(agg["barrels"], len(agg["in_play"])),
            "hard_hit_pct": _ratio(agg["hard_hits"], len(agg["bbe_ev"])),
        })
    out.sort(key=lambda r: r.get("count", 0), reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════
# FIP / xWPCT
# ══════════════════════════════════════════════════════════════════════════


def compute_fip(hr, bb, hbp, k, ip, sport_level: str, year: int,
                c_fip: Optional[float] = None) -> Optional[float]:
    """MiLB FIP using known or supplied constant."""
    if ip is None or ip <= 0:
        return None
    if c_fip is None:
        c_fip = FIP_CONSTANTS.get((sport_level, year))
    if c_fip is None:
        # Fallback: use 2024 constant at the same level, or MLB 2024
        for (lvl, _), v in FIP_CONSTANTS.items():
            if lvl == sport_level:
                c_fip = v
                break
    if c_fip is None:
        c_fip = 3.2  # final fallback

    hr = hr or 0
    bb = bb or 0
    hbp = hbp or 0
    k = k or 0
    try:
        fip = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip + c_fip
        return round(fip, 2)
    except (TypeError, ZeroDivisionError):
        return None


def compute_xwpct(fip: Optional[float], sport_level: str) -> Optional[float]:
    """Expected winning percentage from FIP (Pythagenpat 1.83)."""
    if fip is None or fip <= 0:
        return None
    lg_ra = LEAGUE_RA9.get(sport_level, 4.5)
    try:
        xwpct = 1 / (1 + (fip / lg_ra) ** 1.83)
        return round(xwpct, 3)
    except (ValueError, ZeroDivisionError):
        return None


# ══════════════════════════════════════════════════════════════════════════
# PITCH-LOG DISPLAY HELPERS (for gamelog expansion)
# ══════════════════════════════════════════════════════════════════════════


def summarize_pitch_for_display(p: dict) -> dict:
    """Thin projection of a pitch dict for use in the per-game expandable row."""
    return {
        "inning": p.get("inning"),
        "pitch_type": p.get("pitch_type", ""),
        "pitch_name": p.get("pitch_name", ""),
        "speed": p.get("start_speed"),
        "zone": p.get("zone"),
        "result": p.get("result_desc") or p.get("result_code", ""),
        "ev": p.get("ev"),
        "la": p.get("la"),
        "ivb": p.get("ivb"),
        "hb": p.get("hb"),
        "spin": p.get("spin_rate"),
        "extension": p.get("extension"),
        "pa_event": p.get("pa_event_desc") if p.get("is_pa_final") else "",
        "balls": p.get("balls"),
        "strikes": p.get("strikes"),
    }
