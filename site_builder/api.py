"""
MLB Stats API client helpers.
"""

import datetime
import json
import logging
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
    17: "ROK",
}


# 對 people/mlb_id?hydrate=transactions,rosterEntries,currentTeam 取得基本資料，transactions status 
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


def get_player_stats(mlb_id: int) -> list:
    """Fetch yearByYear stats (hitting, pitching, fielding) from both MLB and MiLB endpoints.

    Always fetches both endpoints so shuttle players (MLB ↔ MiLB) get complete data
    regardless of current assignment. The MLB endpoint returns empty for pure MiLB players.
    """
    all_stats = []
    groups = "hitting,pitching,fielding"

    # MLB endpoint — returns MLB-level seasons only; empty for players without MLB time
    try:
        url = f"{BASE_URL}/people/{mlb_id}/stats?stats=yearByYear&group={groups}"
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        all_stats.extend(resp.json().get("stats", []))
    except Exception as e:
        logger.warning("MLB yearByYear failed for %s: %s", mlb_id, e)

    # MiLB endpoint — always needed for minor-league history
    url = (
        f"{BASE_URL}/people/{mlb_id}/stats"
        f"?stats=yearByYear&leagueListId=milb_all&group={groups}"
    )
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    all_stats.extend(resp.json().get("stats", []))

    return all_stats


def get_player_advanced_stats(
    mlb_id: int, years: Optional[list[int]] = None
) -> list:
    """Fetch seasonAdvanced stats (hitting + pitching) for specified years.

    Always fetches both MLB and MiLB endpoints so shuttle players get complete data.
    """
    all_stats = []
    groups = "hitting,pitching"
    fetch_years = years if years else [None]

    for yr in fetch_years:
        year_param = f"&season={yr}" if yr else ""

        # MLB endpoint — returns empty for players without MLB time
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


def get_game_logs(mlb_id: int, season: int) -> list:
    """Fetch game logs for a specific season from both MLB and MiLB endpoints.

    Always fetches both endpoints so shuttle players (MLB ↔ MiLB) get all
    game logs regardless of current assignment.
    """
    all_logs = []

    # MLB endpoint — returns MLB game logs; empty for players without MLB time
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
                if status == "Preview":
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


def get_game_play_by_play(game_pk: int) -> dict:
    """Fetch the full live-feed JSON for a single game.

    Returns the raw dict from MLB Stats API. Caller is responsible for
    walking ``liveData.plays.allPlays`` and extracting pitches.
    """
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("playByPlay failed for game_pk=%s: %s", game_pk, e)
        return {}


_SPORT_NAME_TO_ABBR: dict[str, str] = {
    "Major League Baseball": "MLB",
    "Triple-A": "AAA",
    "Double-A": "AA",
    "High-A": "A+",
    "Single-A": "A",
    "Low-A": "A",
    "Rookie": "ROK",
    "Rookie Advanced": "ROK",
}


def sport_obj_to_abbr(sport: dict) -> str:
    """Convert an MLB Stats API sport object to an abbreviation string."""
    if not sport:
        return ""
    abbr = _SPORT_ID_MAP.get(sport.get("id", 0))
    if abbr:
        return abbr
    return _SPORT_NAME_TO_ABBR.get(sport.get("name", ""), "")


def get_game_sport_level(game_pk: int) -> str:
    """Fetch only the sport abbreviation (e.g. 'MLB', 'AAA') for a single game.

    The live-feed ``gameData.game`` node does not expose a sport field; the
    authoritative sport info is at ``gameData.teams.home.sport``.
    Uses a fields-filtered request so the payload is small.

    Returns an empty string on failure.
    """
    url = (
        f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        "?fields=gameData,teams,home,sport,id,name"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        sport = (
            data.get("gameData", {})
            .get("teams", {})
            .get("home", {})
            .get("sport", {})
        )
        return sport_obj_to_abbr(sport)
    except Exception as e:
        logger.warning("get_game_sport_level failed for game_pk=%s: %s", game_pk, e)
        return ""


def get_player_sabermetrics(mlb_id: int, years: Optional[list[int]] = None) -> list:
    """Fetch sabermetrics stats (FIP/xFIP/WAR) — MLB only.

    Returns the raw ``stats`` list from the API; caller walks splits.
    """
    all_stats = []
    fetch_years = years if years else [None]
    for yr in fetch_years:
        year_param = f"&season={yr}" if yr else ""
        url = (
            f"{BASE_URL}/people/{mlb_id}/stats"
            f"?stats=sabermetrics&group=pitching,hitting{year_param}"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            all_stats.extend(resp.json().get("stats", []))
        except Exception as e:
            logger.warning("sabermetrics failed for %s year=%s: %s", mlb_id, yr, e)
    return all_stats


def get_player_expected_stats(
    mlb_id: int,
    years: Optional[list[int]] = None,
    group: str = "pitching",
) -> list:
    """Fetch expectedStatistics (xwOBA, xBA, xSLG) — MLB only.

    Only fetches the MLB endpoint. The MiLB endpoint (leagueListId=milb_all)
    always returns 0.0 for all expected stats fields — the MLB Stats API does
    not publish Statcast-derived expected stats for minor-league play — so
    calling it wastes bandwidth and latency.

    Note: API fields are named ``avg``/``slg``/``woba``/``wobaCon`` (no x prefix).
    """
    all_stats = []
    fetch_years = years if years else [None]
    for yr in fetch_years:
        year_param = f"&season={yr}" if yr else ""

        # MLB endpoint — returns valid xBA/xSLG/xwOBA for MLB seasons only
        url = (
            f"{BASE_URL}/people/{mlb_id}/stats"
            f"?stats=expectedStatistics&group={group}{year_param}"
        )
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            all_stats.extend(resp.json().get("stats", []))
        except Exception as e:
            logger.warning(
                "MLB expectedStatistics failed for %s year=%s: %s", mlb_id, yr, e
            )

    return all_stats


def parse_roster_from_file(filepath: str) -> list:
    """Parse player roster entries from a JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("players", [])
    except Exception as e:
        logger.error("Error reading %s: %s", filepath, e)
        return []

