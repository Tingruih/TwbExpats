"""
Shared utilities, data containers, and stat computation helpers.
"""

import datetime
import json
import os
import re
from typing import Any, Optional

SPORT_LEVEL_ORDER = {
    "MLB": 0,
    "AAA": 1,
    "AA": 2,
    "A+": 3,
    "A": 4,
    "A-": 5,
    "ROK": 6,
    "Minors": 99,
}

DEFAULT_SEASON_YEAR = int(os.environ.get("DEFAULT_SEASON_YEAR", "2026"))


class Obj(dict):
    """Simple attribute-access dict used by Jinja templates."""

    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value


# ── Counting stat fields summed in career / season-combined aggregations ──

_COUNTING_FIELDS = [
    "gp",
    "wins",
    "losses",
    "sv",
    "hld",
    "so",
    "bb",
    "hr",
    "rbi",
    "sb",
    "cs",
    "hits",
    "ab",
    "hit_bb",
    "earned_runs",
    "pitches",
    "bf",
    "gs",
    "pa",
    "doubles",
    "triples",
    "tb",
    "hbp",
    "gdp",
    "runs",
    "h_so",
    "ibb",
    "lob",
    "sac_bunts",
    "sac_flies",
    "p_ground_outs",
    "p_air_outs",
    "runs_allowed",
    "p_hits",
    "p_hr",
    "p_hbp",
    "p_ibb",
    "p_sb",
    "p_cs",
    "p_gdp",
    "p_doubles",
    "p_triples",
    "p_tb",
    "p_ab",
    "svo",
    "outs",
    "cg",
    "sho",
    "strikes",
    "balks",
    "wp",
    "pickoffs",
    "gf",
    "ir",
    "irs",
    "p_sac_bunts",
    "p_sac_flies",
    "h_ground_outs",
    "h_air_outs",
    "pitches_seen",
    "gidpo",
    "roe",
    "wo",
    "qs",
    "bqr",
    "bqr_s",
    "run_support",
    "p_gidpo",
    "xbh",
]


# ── Safe type conversions ──


def safe_float(value: Any, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default=None):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ── JSON helpers ──


def loads_json(text: Any, default: Any):
    if text is None:
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


def loads_json_dict(text: Any) -> dict:
    value = loads_json(text, {})
    return value if isinstance(value, dict) else {}


def loads_json_list(text: Any) -> list:
    value = loads_json(text, [])
    return value if isinstance(value, list) else []


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# ── Date / unit helpers ──


def parse_date(text: Optional[str]):
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def ip_to_outs(ip_value) -> int:
    if ip_value is None:
        return 0
    whole = int(ip_value)
    thirds = round((ip_value - whole) * 10)
    return whole * 3 + thirds


def outs_to_ip(outs: int):
    if outs == 0:
        return None
    whole = outs // 3
    remainder = outs % 3
    return round(whole + remainder / 10, 1)


_HEIGHT_RE = re.compile(r"(\d+)['\u2032]\s*(\d+)[\"\u201c\u201d\u2033]?")


def height_to_cm(height_str):
    if not height_str:
        return None
    m = _HEIGHT_RE.match(str(height_str))
    if m:
        feet, inches = int(m.group(1)), int(m.group(2))
        return round((feet * 12 + inches) * 2.54, 1)
    return None


def lbs_to_kg(weight_lbs):
    if weight_lbs is None:
        return None
    return round(weight_lbs * 0.453592, 1)


def calc_obp(hits, bb, hbp, ab, sac_flies):
    h = hits or 0
    b = bb or 0
    hp = hbp or 0
    a = ab or 0
    sf = sac_flies or 0
    denom = a + b + hp + sf
    if denom == 0:
        return None
    return round((h + b + hp) / denom, 3)


def has_appearance(stat) -> bool:
    if not stat:
        return False
    if (stat.gp or 0) > 0:
        return True
    if (stat.pa or 0) > 0:
        return True
    if (stat.ab or 0) > 0:
        return True
    if (stat.bf or 0) > 0:
        return True
    return ip_to_outs(stat.ip) > 0


# ── Stat aggregation ──


def _sum_counting(stats, result):
    for field in _COUNTING_FIELDS:
        values = [getattr(s, field) for s in stats]
        if all(v is None for v in values):
            result[field] = None
        else:
            result[field] = sum(v or 0 for v in values)


def _compute_rate_stats(agg):
    """Compute batting / pitching rate stats on an aggregated Obj."""
    if agg.get("ab") and agg["ab"] > 0:
        agg["avg"] = round((agg.get("hits") or 0) / agg["ab"], 3)
        agg["obp"] = calc_obp(
            agg.get("hits"),
            agg.get("hit_bb"),
            agg.get("hbp"),
            agg["ab"],
            agg.get("sac_flies"),
        )
        agg["slg"] = (
            round((agg.get("tb") or 0) / agg["ab"], 3)
            if agg.get("tb") is not None
            else None
        )
        if agg.get("obp") is not None and agg.get("slg") is not None:
            agg["ops"] = round(agg["obp"] + agg["slg"], 3)
        else:
            agg["ops"] = None
    else:
        agg["avg"] = agg["obp"] = agg["slg"] = agg["ops"] = None

    # agg["ip"] is baseball decimal notation (e.g. 7.2 = 7⅔ innings = 7.333... real innings).
    # Must convert via ip_to_outs → divide by 3 to get true fractional innings before
    # computing rate stats, otherwise ERA/WHIP will be slightly wrong.
    _ip_outs = ip_to_outs(agg.get("ip"))
    _ip_actual = _ip_outs / 3.0  # real innings pitched as a fraction
    if _ip_actual > 0:
        er = agg.get("earned_runs") or 0
        agg["era"] = round(er / _ip_actual * 9, 2)
        agg["whip"] = (
            round(((agg.get("p_hits") or 0) + (agg.get("bb") or 0)) / _ip_actual, 2)
            if agg.get("p_hits") is not None
            else None
        )
    else:
        agg["era"] = agg["whip"] = None


def compute_career(stats, level_filter=None):
    """Aggregate counting stats across multiple seasons and compute rates."""
    if level_filter == "mlb":
        stats = [s for s in stats if s.sport_level == "MLB"]
    elif level_filter == "milb":
        stats = [s for s in stats if s.sport_level != "MLB"]

    if not stats:
        return None

    career = Obj()
    _sum_counting(stats, career)

    total_outs = sum(ip_to_outs(s.ip) for s in stats)
    career["ip"] = outs_to_ip(total_outs)
    _compute_rate_stats(career)

    teams = [f"{s.sport_level} {s.team_name}" for s in stats]
    career["teams_display"] = " / ".join(teams)

    years_set = sorted(set(s.year for s in stats))
    if len(years_set) > 1:
        career["years_range"] = f"{years_set[0]}–{years_set[-1]}"
    elif years_set:
        career["years_range"] = str(years_set[0])
    else:
        career["years_range"] = ""

    return career


def compute_season_combined(stats, year):
    """Aggregate counting stats for a single year across teams."""
    stats = [s for s in stats if s.year == year]
    if not stats:
        return None

    combined = Obj()
    _sum_counting(stats, combined)

    total_outs = sum(ip_to_outs(s.ip) for s in stats)
    combined["ip"] = outs_to_ip(total_outs)
    _compute_rate_stats(combined)

    teams = [f"{s.sport_level} {s.team_name}" for s in stats]
    combined["teams_display"] = " / ".join(teams)
    combined["year"] = year

    return combined


def _fmt_avg(value):
    """Format a float as a baseball average string with no leading zero.

    Examples:
        0.333  -> ".333"
        1.000  -> "1.000"
        None   -> None
    """
    if value is None:
        return None
    s = f"{value:.3f}"
    return s[1:] if s.startswith("0.") else s


def _compute_advanced_stats(s):
    """Fill in derived advanced stats on an Obj (or any dict-like).

    Only sets a field when its current value is None so that API-supplied
    values are never overwritten.  Works for both per-row and summary rows,
    and for both batters and pitchers (all fields guarded by None-checks).
    """
    # ── IP as real fractional innings (needed for pitcher /9 rates) ──
    ip_actual = None
    if s.get("ip") is not None:
        ip_actual = ip_to_outs(s["ip"]) / 3.0
    elif s.get("outs"):
        ip_actual = s["outs"] / 3.0

    # ─────────────────────────── BATTER fields ───────────────────────────

    # P/PA: prefer pitches_per_pa alias, then compute from pitches_seen / PA
    if s.get("p_per_pa") is None and s.get("pitches_per_pa") is not None:
        s["p_per_pa"] = s.get("pitches_per_pa")
    if s.get("p_per_pa") is None:
        ps = s.get("pitches_seen")
        pa = s.get("pa")
        if ps is not None and pa and pa > 0:
            s["p_per_pa"] = round(ps / pa, 2)

    # XBH fallback from components
    if s.get("xbh") is None:
        d = s.get("doubles") or 0
        t = s.get("triples") or 0
        h = s.get("hr") or 0
        if d or t or h:
            s["xbh"] = d + t + h

    # ISO = SLG - AVG
    if s.get("iso") is None:
        slg = s.get("slg")
        avg = s.get("avg")
        if slg is not None and avg is not None:
            s["iso"] = round(slg - avg, 3)

    # BABIP = (H - HR) / (AB - SO - HR + SF)
    if s.get("babip") is None:
        hits = s.get("hits")
        hr   = s.get("hr")
        ab   = s.get("ab")
        so   = s.get("h_so")
        sf   = s.get("sac_flies") or 0
        if all(v is not None for v in [hits, hr, ab, so]):
            denom = ab - so - hr + sf
            if denom > 0:
                s["babip"] = round((hits - hr) / denom, 3)

    # AB/HR
    if s.get("ab_per_hr") is None:
        ab = s.get("ab")
        hr = s.get("hr")
        if ab is not None and hr and hr > 0:
            s["ab_per_hr"] = round(ab / hr, 1)

    # Batter GO/AO
    if s.get("go_ao") is None:
        go = s.get("h_ground_outs")
        ao = s.get("h_air_outs")
        if go is not None and ao is not None and ao > 0:
            s["go_ao"] = round(go / ao, 2)

    # SB% = SB / (SB + CS)
    if s.get("sb_pct") is None:
        sb = s.get("sb")
        cs = s.get("cs")
        if sb is not None and cs is not None:
            total = sb + cs
            if total > 0:
                s["sb_pct"] = _fmt_avg(sb / total)

    # ─────────────────────────── PITCHER fields ──────────────────────────

    # Pitcher P/PA alias: pitches_per_pa = pitches / BF
    if s.get("pitches_per_pa") is None:
        pitches = s.get("pitches")
        bf = s.get("bf")
        if pitches is not None and bf and bf > 0:
            s["pitches_per_pa"] = round(pitches / bf, 2)

    # /9 rate stats require IP
    if ip_actual and ip_actual > 0:
        so     = s.get("so")
        bb     = s.get("bb")
        p_hits = s.get("p_hits")
        p_hr   = s.get("p_hr")

        if s.get("k_per_9") is None and so is not None:
            s["k_per_9"] = round(so * 9 / ip_actual, 1)

        if s.get("bb_per_9") is None and bb is not None:
            s["bb_per_9"] = round(bb * 9 / ip_actual, 1)

        if s.get("h_per_9") is None and p_hits is not None:
            s["h_per_9"] = round(p_hits * 9 / ip_actual, 1)

        if s.get("hr_per_9") is None and p_hr is not None:
            s["hr_per_9"] = round(p_hr * 9 / ip_actual, 2)

        if s.get("p_per_ip") is None:
            pitches = s.get("pitches")
            if pitches is not None:
                s["p_per_ip"] = round(pitches / ip_actual, 1)

        if s.get("rs_per_9") is None:
            rs = s.get("run_support")
            if rs is not None:
                s["rs_per_9"] = round(rs * 9 / ip_actual, 2)

    # K/BB
    if s.get("k_bb_ratio") is None:
        so = s.get("so")
        bb = s.get("bb")
        if so is not None and bb is not None and bb > 0:
            s["k_bb_ratio"] = round(so / bb, 2)

    # Strike% = strikes / pitches
    if s.get("strike_pct") is None:
        strikes = s.get("strikes")
        pitches = s.get("pitches")
        if strikes is not None and pitches and pitches > 0:
            s["strike_pct"] = _fmt_avg(strikes / pitches)

    # Pitcher BABIP = (H - HR) / (BF - SO - HR - BB)
    if s.get("p_babip") is None:
        p_hits = s.get("p_hits")
        p_hr   = s.get("p_hr")
        bf     = s.get("bf")
        so     = s.get("so")
        bb     = s.get("bb")
        if all(v is not None for v in [p_hits, p_hr, bf, so, bb]):
            denom = bf - so - p_hr - bb
            if denom > 0:
                s["p_babip"] = round((p_hits - p_hr) / denom, 3)

    # Pitcher GO/AO
    if s.get("p_go_ao") is None:
        go = s.get("p_ground_outs")
        ao = s.get("p_air_outs")
        if go is not None and ao is not None and ao > 0:
            s["p_go_ao"] = round(go / ao, 2)

    # Win% = W / (W + L)
    if s.get("win_pct") is None:
        w = s.get("wins")
        l = s.get("losses")
        if w is not None and l is not None:
            total = w + l
            if total > 0:
                s["win_pct"] = _fmt_avg(w / total)

    # Pitcher batting line (opponents): p_avg, p_obp, p_slg, p_ops
    p_ab = s.get("p_ab")
    if p_ab and p_ab > 0:
        p_hits = s.get("p_hits")
        p_tb   = s.get("p_tb")
        bb     = s.get("bb")
        p_hbp  = s.get("p_hbp")
        p_sf   = s.get("p_sac_flies") or 0

        if s.get("p_avg") is None and p_hits is not None:
            s["p_avg"] = _fmt_avg(p_hits / p_ab)

        p_obp_f = None
        if p_hits is not None and bb is not None and p_hbp is not None:
            obp_denom = p_ab + bb + p_hbp + p_sf
            if obp_denom > 0:
                p_obp_f = (p_hits + bb + p_hbp) / obp_denom
        if s.get("p_obp") is None and p_obp_f is not None:
            s["p_obp"] = _fmt_avg(p_obp_f)

        p_slg_f = None
        if p_tb is not None:
            p_slg_f = p_tb / p_ab
        if s.get("p_slg") is None and p_slg_f is not None:
            s["p_slg"] = _fmt_avg(p_slg_f)

        if s.get("p_ops") is None:
            # Use already-computed floats if available, else parse strings
            obp_f = p_obp_f if p_obp_f is not None else safe_float(s.get("p_obp"))
            slg_f = p_slg_f if p_slg_f is not None else safe_float(s.get("p_slg"))
            if obp_f is not None and slg_f is not None:
                s["p_ops"] = _fmt_avg(obp_f + slg_f)


def annotate_computed_stats(all_stats):
    """Add derived fields to each stat row (np alias + all advanced stats)."""
    for stat in all_stats:
        stat.np = stat.pitches
        _compute_advanced_stats(stat)
    return all_stats


def compute_year_groups(all_stats):
    """Group stats by year, producing a summary row + per-team detail rows.

    Returns a list of dicts (ordered most-recent year first)::

        [
          {
            "year": 2024,
            "summary": <Obj with summed counts + recalculated rates>,
            "rows": [<Obj per team/level row for that year>],
            "multi": True/False,   # True when player was on 2+ teams that year
          },
          ...
        ]

    ERA and WHIP on the summary row are computed from total outs (IP via
    ip_to_outs) so cross-team ERA is always accurate.
    """
    years = sorted({s.year for s in all_stats}, reverse=True)
    groups = []
    for yr in years:
        yr_stats = [s for s in all_stats if s.year == yr]
        # Sort rows: MLB first, then by level order
        yr_stats.sort(key=lambda s: s.level_order)

        summary = Obj()
        _sum_counting(yr_stats, summary)
        total_outs = sum(ip_to_outs(s.ip) for s in yr_stats)
        summary["ip"] = outs_to_ip(total_outs)
        _compute_rate_stats(summary)
        summary["year"] = yr

        # np alias for template compatibility
        summary["np"] = summary.get("pitches")

        # Fill in all advanced / derived stats
        _compute_advanced_stats(summary)

        groups.append({
            "year": yr,
            "summary": summary,
            "rows": yr_stats,
            "multi": len(yr_stats) > 1,
        })
    return groups
