"""
MLB Stats API and FanGraphs API client helpers.
"""

import datetime
import json
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 15

_SPORT_ID_MAP = {
    1: "MLB",
    11: "AAA",
    12: "AA",
    13: "A+",
    14: "A",
    15: "A-",
    16: "ROK",
}


def get_player_profile(mlb_id: int) -> dict:
    """Fetch player bio, transactions, and current roster status."""
    url = f"{BASE_URL}/people/{mlb_id}?hydrate=transactions,rosterEntries,currentTeam"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    people = resp.json().get("people", [])
    if not people:
        return {}

    p = people[0]

    # Transactions (most recent first)
    transactions = p.get("transactions", [])
    latest_tx = ""
    tx_list = []
    if transactions:
        sorted_tx = sorted(transactions, key=lambda t: t.get("date", ""), reverse=True)
        latest_tx = sorted_tx[0].get("description", "") if sorted_tx else ""
        for tx in sorted_tx:
            tx_list.append(
                {
                    "date": tx.get("effectiveDate") or tx.get("date", ""),
                    "type": tx.get("typeDesc", ""),
                    "description": tx.get("description", ""),
                }
            )

    # Active roster status
    roster_status = ""
    for entry in p.get("rosterEntries", []):
        if entry.get("isActive", False):
            roster_status = entry.get("status", {}).get("description", "")
            break

    # Team info and level
    current_team = p.get("currentTeam", {})
    team_id = current_team.get("id")
    current_team_name = current_team.get("name", "")
    current_team_level = ""

    if team_id:
        try:
            t_resp = requests.get(f"{BASE_URL}/teams/{team_id}", timeout=TIMEOUT)
            if t_resp.status_code == 200:
                t_data = t_resp.json().get("teams", [])
                if t_data:
                    sport_id = t_data[0].get("sport", {}).get("id")
                    current_team_level = _SPORT_ID_MAP.get(sport_id, "")
        except Exception as e:
            logger.warning("Failed to fetch team level for team_id=%s: %s", team_id, e)

    return {
        "mlb_id": p.get("id"),
        "full_name": p.get("fullName", ""),
        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
        "height": p.get("height", ""),
        "weight": p.get("weight"),
        "birth_date": p.get("birthDate"),
        "birth_city": p.get("birthCity", ""),
        "birth_country": p.get("birthCountry", ""),
        "is_active": p.get("active", True),
        "bat_side": p.get("batSide", {}).get("description", ""),
        "pitch_hand": p.get("pitchHand", {}).get("description", ""),
        "latest_transaction": latest_tx,
        "transactions_json": tx_list,
        "roster_status": roster_status,
        "team_id": team_id,
        "current_team_name": current_team_name,
        "current_team_level": current_team_level,
    }


def get_player_stats(mlb_id: int, source: str = "milb") -> list:
    """Fetch yearByYear stats (hitting, pitching, fielding)."""
    all_stats = []
    groups = "hitting,pitching,fielding"

    if source == "mlb":
        url = f"{BASE_URL}/people/{mlb_id}/stats?stats=yearByYear&group={groups}"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        all_stats.extend(resp.json().get("stats", []))

    # Always include MiLB history
    url = (
        f"{BASE_URL}/people/{mlb_id}/stats"
        f"?stats=yearByYear&leagueListId=milb_all&group={groups}"
    )
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    all_stats.extend(resp.json().get("stats", []))

    return all_stats


def get_player_advanced_stats(
    mlb_id: int, years: Optional[list[int]] = None, source: str = "milb"
) -> list:
    """Fetch seasonAdvanced stats (hitting + pitching) for specified years."""
    all_stats = []
    groups = "hitting,pitching"
    fetch_years = years if years else [None]

    for yr in fetch_years:
        year_param = f"&season={yr}" if yr else ""

        if source == "mlb":
            url = f"{BASE_URL}/people/{mlb_id}/stats?stats=seasonAdvanced&group={groups}{year_param}"
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                resp.raise_for_status()
                all_stats.extend(resp.json().get("stats", []))
            except Exception as e:
                logger.warning(
                    "MLB seasonAdvanced failed for %s year=%s: %s", mlb_id, yr, e
                )

        url = (
            f"{BASE_URL}/people/{mlb_id}/stats"
            f"?stats=seasonAdvanced&leagueListId=milb_all&group={groups}{year_param}"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            all_stats.extend(resp.json().get("stats", []))
        except Exception as e:
            logger.warning(
                "MiLB seasonAdvanced failed for %s year=%s: %s", mlb_id, yr, e
            )

    return all_stats


def get_game_logs(mlb_id: int, season: int, source: str = "milb") -> list:
    """Fetch game logs for a specific season."""
    all_logs = []

    if source == "mlb":
        url = (
            f"{BASE_URL}/people/{mlb_id}/stats"
            f"?stats=gameLog&season={season}&group=hitting,pitching"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            all_logs.extend(resp.json().get("stats", []))
        except Exception as e:
            logger.warning("MLB game logs failed for %s/%s: %s", mlb_id, season, e)

    url = (
        f"{BASE_URL}/people/{mlb_id}/stats"
        f"?stats=gameLog&season={season}&leagueListId=milb_all&group=hitting,pitching"
    )
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        all_logs.extend(resp.json().get("stats", []))
    except Exception as e:
        logger.warning("MiLB game logs failed for %s/%s: %s", mlb_id, season, e)

    return all_logs


def get_next_game(team_id: int) -> Optional[dict]:
    """Fetch the next upcoming game for a team (7-day window)."""
    if not team_id:
        return None

    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=7)
    url = (
        f"{BASE_URL}/schedule"
        f"?teamId={team_id}"
        f"&startDate={today.isoformat()}"
        f"&endDate={end_date.isoformat()}"
        f"&sportId=1,11,12,13,14,15,16"
    )

    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        dates = resp.json().get("dates", [])

        for date_entry in dates:
            for game in date_entry.get("games", []):
                status = game.get("status", {}).get("abstractGameState", "")
                if status in ("Preview", "Pre-Game", "Warmup"):
                    away_team = game.get("teams", {}).get("away", {}).get("team", {})
                    home_team = game.get("teams", {}).get("home", {}).get("team", {})
                    is_home = home_team.get("id") == team_id

                    game_time = ""
                    game_date_str = game.get("gameDate", "")
                    if game_date_str:
                        try:
                            dt = datetime.datetime.fromisoformat(
                                game_date_str.replace("Z", "+00:00")
                            )
                            utc8 = datetime.timezone(datetime.timedelta(hours=8))
                            game_time = dt.astimezone(utc8).strftime(
                                "%m/%d %H:%M (UTC+8)"
                            )
                        except Exception:
                            game_time = game_date_str[:16]
                        except Exception:
                            game_time = game_date_str[:16]

                    return {
                        "date": date_entry.get("date", ""),
                        "opponent": (
                            away_team.get("name", "")
                            if is_home
                            else home_team.get("name", "")
                        ),
                        "is_home": is_home,
                        "venue": game.get("venue", {}).get("name", ""),
                        "game_time": game_time,
                        "status": game.get("status", {}).get("detailedState", ""),
                    }
    except Exception as e:
        logger.warning("Failed to fetch next game for team_id=%s: %s", team_id, e)
        return None

    return None


def parse_roster_from_file(filepath: str) -> list:
    """Parse player roster entries from a JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("players", [])
    except Exception as e:
        logger.error("Error reading %s: %s", filepath, e)
        return []


# ── FanGraphs API ──

FANGRAPHS_API = "https://www.fangraphs.com/api/players/stats"

_FG_PITCHER_FIELDS = {
    "FIP": "fip",
    "xFIP": "xfip",
    "SIERA": "siera",
    "LOB%": "lob_pct",
    "K%": "k_pct",
    "BB%": "bb_pct",
    "ERA-": "era_minus",
    "FIP-": "fip_minus",
    "GB%": "gb_pct",
    "FB%": "fb_pct",
    "LD%": "ld_pct",
    "IFFB%": "iffb_pct",
    "HR/FB": "hr_fb",
    "SwStr%": "swstr_pct",
    "F-Strike%": "fstrike_pct",
    "CStr%": "cstr_pct",
    "Hard%": "hard_pct",
    "Med%": "med_pct",
    "Soft%": "soft_pct",
    "Pull%": "pull_pct",
    "Cent%": "cent_pct",
    "Oppo%": "oppo_pct",
    "WAR": "war",
    "RAR": "rar",
    "WPA": "wpa",
    "RE24": "re24",
    "Clutch": "clutch",
    "EV": "ev",
    "LA": "la",
    "Barrel%": "barrel_pct",
    "HardHit%": "hardhit_pct",
    "xERA": "xera",
    "xFIP_SC": "xfip_statcast",
}

_FG_BATTER_FIELDS = {
    "wOBA": "woba",
    "wRC+": "wrc_plus",
    "wRC": "wrc",
    "wRAA": "wraa",
    "WAR": "war",
    "RAR": "rar",
    "ISO": "iso",
    "Spd": "spd",
    "K%": "k_pct",
    "BB%": "bb_pct",
    "GB%": "gb_pct",
    "FB%": "fb_pct",
    "LD%": "ld_pct",
    "IFFB%": "iffb_pct",
    "HR/FB": "hr_fb",
    "BABIP": "babip",
    "BsR": "bsr",
    "Off": "off",
    "Def": "def",
    "RE24": "re24",
    "WPA": "wpa",
    "Clutch": "clutch",
    "EV": "ev",
    "LA": "la",
    "Barrel%": "barrel_pct",
    "HardHit%": "hardhit_pct",
    "Hard%": "hard_pct",
    "Med%": "med_pct",
    "Soft%": "soft_pct",
    "Pull%": "pull_pct",
    "Cent%": "cent_pct",
    "Oppo%": "oppo_pct",
    "SwStr%": "swstr_pct",
    "F-Strike%": "fstrike_pct",
    "xwOBA": "xwoba",
    "xBA": "xba",
    "xSLG": "xslg",
}


def get_fangraphs_stats(fg_playerid: str, position: str = "OF") -> dict:
    """Fetch advanced stats from FanGraphs API. Returns dict keyed by '{season}_{team}'."""
    url = f"{FANGRAPHS_API}?playerid={fg_playerid}&position={position}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("FanGraphs API error for %s: %s", fg_playerid, e)
        return {}

    result = {}
    rows = data if isinstance(data, list) else data.get("data", [])
    field_map = _FG_PITCHER_FIELDS if position == "P" else _FG_BATTER_FIELDS

    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_season = row.get("Season")
        if not raw_season:
            continue

        # FanGraphs sometimes returns Season as HTML link: <a href="...">2021</a>
        if isinstance(raw_season, str):
            m = re.search(r"(\d{4})", raw_season)
            season = int(m.group(1)) if m else None
        else:
            season = int(raw_season) if raw_season else None
        if not season:
            continue

        team = row.get("Team", "")
        key = f"{season}_{team}"

        fg_data = {"season": season, "team": team}
        for fg_key, local_key in field_map.items():
            val = row.get(fg_key)
            if val is not None:
                fg_data[local_key] = val

        if len(fg_data) > 2:  # has actual stat fields beyond season/team
            result[key] = fg_data

    return result
