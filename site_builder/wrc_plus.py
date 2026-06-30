"""
TJBat+ (wRC+) computation aligned with the TJStats glossary formulas.

Fetches park factors and league constants from tjstats.ca at build time
(never persisted to SQLite — recomputed fresh on every build, same as every
other derived stat in this codebase) and computes wRC+ for batters from
season_stats counting stats.
"""

from typing import Optional

import requests
from bs4 import BeautifulSoup

from .statcast import WOBA_WEIGHTS

TIMEOUT = 15
WOBA_SCALE = 1.24
MIN_WRC_YEAR = 2021

# site_builder.levels Tier key -> TJStats park-factors `pf_level` query value.
PF_LEVEL_PARAM = {
    "MLB": "mlb",
    "AAA": "aaa",
    "AA": "aa",
    "A+": "hi_a",
    "A": "lo_a",
}

# site_builder.levels Tier key -> TJStats league-constants table "Level" code.
# Note this uses hyphens (hi-a/lo-a) while PF_LEVEL_PARAM uses underscores —
# the two TJStats pages spell the same levels differently.
LC_LEVEL_CODE = {
    "MLB": "mlb",
    "AAA": "aaa",
    "AA": "aa",
    "A+": "hi-a",
    "A": "lo-a",
}

WRC_LEVELS = tuple(PF_LEVEL_PARAM.keys())


def compute_woba(stat: dict) -> Optional[float]:
    """Compute wOBA from a season_stats row's counting stats.

    Mirrors statcast.py's PA-based wOBA convention: intentional walks are
    excluded from both numerator and denominator (only the unintentional
    portion of walks counts, matching TJStats' own wOBA definition).
    Returns None when there are no usable plate appearances.
    """
    ab = stat.get("ab") or 0
    hits = stat.get("hits") or 0
    doubles = stat.get("doubles") or 0
    triples = stat.get("triples") or 0
    hr = stat.get("hr") or 0
    bb = stat.get("hit_bb") or 0
    ibb = stat.get("ibb") or 0
    hbp = stat.get("hbp") or 0
    sac_flies = stat.get("sac_flies") or 0

    singles = hits - doubles - triples - hr
    unintentional_bb = bb - ibb

    den = ab + unintentional_bb + sac_flies + hbp
    if den <= 0:
        return None

    num = (
        WOBA_WEIGHTS["walk"] * unintentional_bb
        + WOBA_WEIGHTS["hbp"] * hbp
        + WOBA_WEIGHTS["single"] * singles
        + WOBA_WEIGHTS["double"] * doubles
        + WOBA_WEIGHTS["triple"] * triples
        + WOBA_WEIGHTS["home_run"] * hr
    )
    return num / den


def compute_wrc_plus(
    woba: float, pf_final: float, lg_woba: float, lg_r_pa: float
) -> Optional[int]:
    """TJStats wRC+ formula: 100 x (wRC/PA / PFm) / lg_R/PA, rounded to an int."""
    if not lg_r_pa:
        return None
    wrc_pa = (woba - lg_woba) / WOBA_SCALE + lg_r_pa
    pfm = 1 + (pf_final - 1) * 0.5
    if not pfm:
        return None
    return round(100 * (wrc_pa / pfm) / lg_r_pa)


def fetch_park_factors(level: str, year: int) -> dict[str, dict]:
    """Fetch TJStats park factors for one tier/year.

    Returns {team_name: {"pf_final": float, "league": str}}. Returns {} on
    an unknown level or any fetch/parse failure -- this is a best-effort
    enhancement, not core data, so failures must not raise.
    """
    param = PF_LEVEL_PARAM.get(level)
    if not param:
        return {}

    url = f"https://tjstats.ca/park-factors/?pf_level={param}&pf_season={year}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch TJStats park factors for {level} {year}: {exc}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.select("table.tjs-guts")
    if not tables:
        return {}

    result = {}
    for tr in tables[0].select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 9:
            continue
        team_name, league = cells[0], cells[1]
        try:
            pf_final = float(cells[8])
        except ValueError:
            continue
        result[team_name] = {"pf_final": pf_final, "league": league}
    return result


def fetch_league_constants(year: int) -> dict[tuple[str, str], dict]:
    """Fetch TJStats league constants for every level/league in one year.

    Returns {(level_code, league_name): {"lg_woba": float, "lg_r_pa": float}}.
    level_code matches LC_LEVEL_CODE's values (mlb/aaa/aa/hi-a/lo-a).
    Returns {} on any fetch/parse failure.
    """
    url = f"https://tjstats.ca/park-factors/?lc_season={year}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  WARNING: failed to fetch TJStats league constants for {year}: {exc}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.select("table.tjs-guts")
    if len(tables) < 2:
        return {}

    result = {}
    for tr in tables[1].select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 7:
            continue
        level_code, league = cells[0], cells[1]
        try:
            lg_woba = float(cells[3])
            lg_r_pa = float(cells[5])
        except ValueError:
            continue
        result[(level_code, league)] = {"lg_woba": lg_woba, "lg_r_pa": lg_r_pa}
    return result


def annotate_wrc_plus(bundles) -> None:
    """Compute and inject wRC+ into season_stats rows for qualifying batters.

    bundles is [(player, stats, logs), ...] as produced by
    builder._load_player_bundle. Mutates the per-season Obj rows in `stats`
    in place; never written back to SQLite (recomputed every build).

    For each batter's rows, grouped by (year, sport_level):
      - The row with the most PA in the group determines which team's park
        factor and league (and therefore league constants) are used for
        every row in the group -- mirrors how TJStats itself treats players
        traded between two teams at the same level.
      - MLB rows: the computed value is stored as `wrc_plus_calc`; the
        API-sourced `wrc_plus` value itself is never overwritten.
      - Non-MLB rows: the computed value is written directly into
        `wrc_plus`, the field the templates already render.
    """
    pf_cache: dict[tuple[str, int], dict] = {}
    lc_cache: dict[int, dict] = {}

    def _park_factors(level, year):
        key = (level, year)
        if key not in pf_cache:
            pf_cache[key] = fetch_park_factors(level, year)
        return pf_cache[key]

    def _league_constants(year):
        if year not in lc_cache:
            lc_cache[year] = fetch_league_constants(year)
        return lc_cache[year]

    for player, stats, _logs in bundles:
        if player.position == "P":
            continue

        by_year_level: dict[tuple[int, str], list] = {}
        for s in stats:
            if s.year < MIN_WRC_YEAR or s.sport_level not in WRC_LEVELS:
                continue
            by_year_level.setdefault((s.year, s.sport_level), []).append(s)

        for (yr, level), rows in by_year_level.items():
            primary = max(rows, key=lambda r: r.get("pa") or 0)
            pf_entry = _park_factors(level, yr).get(primary.team_name)
            if pf_entry is None:
                continue
            lc_key = (LC_LEVEL_CODE[level], pf_entry["league"])
            lc_entry = _league_constants(yr).get(lc_key)
            if lc_entry is None:
                continue

            for row in rows:
                woba = compute_woba(row)
                if woba is None:
                    continue
                calc = compute_wrc_plus(
                    woba, pf_entry["pf_final"], lc_entry["lg_woba"], lc_entry["lg_r_pa"]
                )
                if calc is None:
                    continue
                if level == "MLB":
                    row["wrc_plus_calc"] = calc
                else:
                    row["wrc_plus"] = calc
