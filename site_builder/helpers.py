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


def annotate_computed_stats(all_stats):
    """Add derived fields (np, p_per_pa, iso) to each stat row."""
    for stat in all_stats:
        stat.np = stat.pitches
        if stat.p_per_pa is None:
            stat.p_per_pa = stat.pitches_per_pa
        if stat.get("slg") is not None and stat.get("avg") is not None:
            stat.iso = stat.slg - stat.avg
        else:
            stat.iso = None
    return all_stats
