"""
Statcast pitch-level extraction and aggregation.

Everything here operates on either:
  (a) raw MLB Stats API ``game/{pk}/feed/live`` JSON, or
  (b) a list of pitch dicts previously extracted via ``extract_pitch_logs``
      and cached in ``game_logs.pitches_json``.
"""

from __future__ import annotations

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
        pa_pre_strikes = 0

        for i, ev in enumerate(events):
            if not ev.get("isPitch"):
                continue
            details = ev.get("details", {}) or {}
            pdata = ev.get("pitchData", {}) or {}
            hdata = ev.get("hitData", {}) or {}
            coords = pdata.get("coordinates", {}) or {}
            breaks = pdata.get("breaks", {}) or {}
            count = ev.get("count", {}) or {}

            pitch_type_obj = details.get("type") or {}
            is_final = i == last_pitch_idx

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
                "hardness": hdata.get("hardness", ""),
                "balls": count.get("balls"),
                "strikes": post_strikes,
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
            pa_pre_strikes = post_strikes

    return out


def _ensure_pre_strikes(pitches: list[dict]) -> None:
    """Annotate ``pre_strikes`` on pitches that lack it (backward compat).

    Walks the list in order, grouped by ``game_pk``.  Within each game the
    pitches are assumed to be in chronological PA order (as produced by
    ``extract_pitch_logs``).  The first pitch of each PA starts at 0 strikes;
    subsequent pitches inherit the previous pitch's post-pitch strike count.

    Always recomputes for pitches missing the field, even when other pitches
    in the same list already have it (handles mixed old/new cached data).
    """
    if not pitches:
        return
    # Fast path: if ALL pitches already have the field, nothing to do.
    if all("pre_strikes" in p for p in pitches):
        return

    pre_strikes = 0
    last_game_pk = None
    for p in pitches:
        gpk = p.get("game_pk")
        if gpk != last_game_pk:
            # New game boundary — reset to start of a fresh PA.
            pre_strikes = 0
            last_game_pk = gpk

        p["pre_strikes"] = pre_strikes

        if p.get("is_pa_final"):
            pre_strikes = 0  # next pitch starts a new PA
        else:
            pre_strikes = p.get("strikes", 0)


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


# ══════════════════════════════════════════════════════════════════════════
# SHARED AGGREGATION HELPERS
# ══════════════════════════════════════════════════════════════════════════


def _aggregate_pitches(pitches: list[dict]) -> dict:
    """Classify a list of pitches into common categories.

    Returns a dict with pre-filtered lists and counts shared by both
    pitcher and batter aggregation paths.
    """
    swings = [p for p in pitches if _is_swing(p)]
    whiffs = [p for p in pitches if _is_whiff(p)]
    called = [p for p in pitches if _is_called_strike(p)]
    in_zone = [p for p in pitches if _is_in_zone(p)]
    out_zone = [p for p in pitches if _is_out_of_zone(p)]
    in_zone_swings = [p for p in in_zone if _is_swing(p)]
    out_zone_swings = [p for p in out_zone if _is_swing(p)]
    in_zone_contact = [p for p in in_zone_swings if not _is_whiff(p)]
    in_play = [p for p in pitches if p.get("is_in_play")]
    bbe_ev = [p for p in in_play if p.get("ev") is not None]
    pa_final = [p for p in pitches if p.get("is_pa_final")]

    trajectories = [p.get("trajectory", "") for p in in_play]

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
        "gb": sum(1 for t in trajectories if t == "ground_ball"),
        "fb": sum(1 for t in trajectories if t == "fly_ball"),
        "ld": sum(1 for t in trajectories if t == "line_drive"),
        "pu": sum(1 for t in trajectories if t == "popup"),
        "barrels": sum(1 for p in in_play if _is_barrel(p.get("ev"), p.get("la"))),
        "hard_hits": sum(1 for p in bbe_ev if p["ev"] >= 95),
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
        "zone_pct": _ratio(len(agg["in_zone"]), total),
    }


def _batted_ball_metrics(agg: dict) -> dict:
    """Build batted-ball metrics dict from _aggregate_pitches output."""
    n_ip = len(agg["in_play"])
    n_ev = len(agg["bbe_ev"])
    return {
        "bbe": n_ip,
        "gb_pct": _ratio(agg["gb"], n_ip),
        "ld_pct": _ratio(agg["ld"], n_ip),
        "fb_pct": _ratio(agg["fb"], n_ip),
        "pu_pct": _ratio(agg["pu"], n_ip),
        "barrel_pct": _ratio(agg["barrels"], n_ip),
        "hard_hit_pct": _ratio(agg["hard_hits"], n_ev),
        "avg_ev": _mean_round([p["ev"] for p in agg["bbe_ev"]], 1),
    }


# ══════════════════════════════════════════════════════════════════════════
# PITCHER AGGREGATION
# ══════════════════════════════════════════════════════════════════════════


def compute_pitcher_statcast(pitches: list[dict], year: Optional[int] = None) -> dict:
    """Season-level pitcher aggregates from pitch list."""
    if not pitches:
        return {}

    _ensure_pre_strikes(pitches)

    woba_w = get_woba_weights(year)
    agg = _aggregate_pitches(pitches)
    woba_num, woba_den = _compute_woba(agg["pa_final"], woba_w)

    hr = sum(1 for p in agg["pa_final"] if p.get("pa_event") == "home_run")

    result = {
        "total_pitches": agg["total"],
        "pa_count": woba_den,
        "woba_against": _ratio(woba_num, woba_den),
        "hr_fb_pct": _ratio(hr, agg["fb"]),
        "avg_extension": _mean_round([p.get("extension") for p in pitches], 2),
        "pitch_arsenal": _compute_pitch_arsenal_pitcher(pitches, year=year),
    }
    result.update(_discipline_metrics(agg))
    result.update(_batted_ball_metrics(agg))
    return result


def _compute_pitch_arsenal_pitcher(pitches: list[dict], year: Optional[int] = None) -> list[dict]:
    """Per-pitch-type breakdown for a pitcher."""
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
            "zone_pct": _ratio(len(agg["in_zone"]), n),
            "chase_pct": _ratio(len(agg["out_zone_swings"]), len(agg["out_zone"])),
            "whiff_pct": _ratio(len(agg["whiffs"]), len(agg["swings"])),
            "put_away_pct": _ratio(two_strike_strikeouts, len(two_strike)),
            "two_strike_count": len(two_strike),
            "woba": _ratio(woba_num, woba_den),
        })
    out.sort(key=lambda r: r.get("count", 0), reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════
# BATTER AGGREGATION
# ══════════════════════════════════════════════════════════════════════════


def compute_batter_statcast(pitches: list[dict], year: Optional[int] = None) -> dict:
    """Season-level batter aggregates from pitch list."""
    if not pitches:
        return {}

    # Ensure every pitch has a pre_strikes field (backfills cached data
    # that predates the field being added to extract_pitch_logs).
    _ensure_pre_strikes(pitches)

    woba_w = get_woba_weights(year)
    agg = _aggregate_pitches(pitches)
    woba_num, woba_den = _compute_woba(agg["pa_final"], woba_w)

    # Spray (location depends on bat side)
    pull = straight = oppo = 0
    for p in agg["in_play"]:
        loc = p.get("hit_location")
        bat = p.get("bat_side", "R")
        if loc is None:
            continue
        try:
            loc = int(loc)
        except (ValueError, TypeError):
            continue
        # location: 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
        if loc in (1, 2, 4, 8):
            straight += 1
        elif loc in (5, 6, 7):
            pull += 1 if bat == "R" else 0
            oppo += 1 if bat != "R" else 0
        elif loc in (3, 9):
            oppo += 1 if bat == "R" else 0
            pull += 1 if bat != "R" else 0

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
        "pull_pct": _ratio(pull, n_ip),
        "straight_pct": _ratio(straight, n_ip),
        "oppo_pct": _ratio(oppo, n_ip),
        "max_ev": round(max(p["ev"] for p in agg["bbe_ev"]), 1) if agg["bbe_ev"] else None,
        "ev90": ev90,
        "avg_la": _mean_round(la_values, 1),
        "swsp_pct": _ratio(sweet_spots, len(la_values)),
        "vs_pitch_types": _compute_vs_pitch_types_batter(pitches, year=year),
    }
    result.update(_discipline_metrics(agg))
    result.update(_batted_ball_metrics(agg))
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
            "zone_pct": _ratio(len(agg["in_zone"]), n),
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
