"""
Data synchronization: fetch from MLB/FanGraphs APIs and store in SQLite.

Uses concurrent.futures to fetch player data in parallel for faster syncs.
"""

import datetime
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from site_builder.api import (
    get_fangraphs_stats,
    get_game_logs,
    get_next_game,
    get_player_advanced_stats,
    get_player_profile,
    get_player_stats,
    parse_roster_from_file,
)
from site_builder.helpers import (
    SPORT_LEVEL_ORDER,
    dumps_json,
    loads_json,
    loads_json_dict,
    loads_json_list,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

MAX_WORKERS = 8  # parallel API fetch threads


# ── Database schema ──


def _init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mlb_id INTEGER NOT NULL UNIQUE,
            name_en TEXT NOT NULL,
            name_tw TEXT NOT NULL DEFAULT '',
            team TEXT NOT NULL DEFAULT 'N/A',
            level TEXT NOT NULL DEFAULT 'Minors',
            position TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'milb',
            height TEXT NOT NULL DEFAULT '',
            weight INTEGER,
            birth_date TEXT,
            birth_city TEXT NOT NULL DEFAULT '',
            birth_country TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            bat_side TEXT NOT NULL DEFAULT '',
            pitch_hand TEXT NOT NULL DEFAULT '',
            latest_transaction TEXT NOT NULL DEFAULT '',
            roster_status TEXT NOT NULL DEFAULT '',
            team_id INTEGER,
            transactions_json TEXT NOT NULL DEFAULT '[]',
            next_game_json TEXT NOT NULL DEFAULT '{}',
            next_game_updated_at TEXT,
            next_game_for_season INTEGER
        );

        CREATE TABLE IF NOT EXISTS season_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_mlb_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            league_name TEXT NOT NULL DEFAULT '',
            sport_level TEXT NOT NULL DEFAULT '',
            stat_json TEXT NOT NULL DEFAULT '{}',
            fielding_json TEXT NOT NULL DEFAULT '[]',
            advanced_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(player_mlb_id, year, team_name)
        );

        CREATE TABLE IF NOT EXISTS game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_mlb_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            game_id INTEGER NOT NULL,
            opponent TEXT NOT NULL,
            is_home INTEGER,
            stats_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(player_mlb_id, game_id)
        );

        CREATE INDEX IF NOT EXISTS idx_season_stats_player_year
            ON season_stats(player_mlb_id, year);
        CREATE INDEX IF NOT EXISTS idx_game_logs_player_date
            ON game_logs(player_mlb_id, date);
    """)
    conn.commit()


# ── Season row load/save ──


def _load_season_row(cur, mlb_id: int, year: int, team_name: str) -> dict:
    cur.execute(
        "SELECT league_name, sport_level, stat_json, fielding_json, advanced_json "
        "FROM season_stats WHERE player_mlb_id = ? AND year = ? AND team_name = ?",
        (mlb_id, year, team_name),
    )
    row = cur.fetchone()
    if not row:
        return {
            "league_name": "",
            "sport_level": "",
            "stat_json": {},
            "fielding_json": [],
            "advanced_json": {},
        }
    return {
        "league_name": row[0] or "",
        "sport_level": row[1] or "",
        "stat_json": loads_json(row[2], {}),
        "fielding_json": loads_json(row[3], []),
        "advanced_json": loads_json(row[4], {}),
    }


def _save_season_row(
    cur,
    mlb_id,
    year,
    team_name,
    league_name,
    sport_level,
    stat_json,
    fielding_json,
    advanced_json,
):
    cur.execute(
        "INSERT INTO season_stats "
        "(player_mlb_id, year, team_name, league_name, sport_level, "
        " stat_json, fielding_json, advanced_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(player_mlb_id, year, team_name) DO UPDATE SET "
        " league_name=excluded.league_name, sport_level=excluded.sport_level, "
        " stat_json=excluded.stat_json, fielding_json=excluded.fielding_json, "
        " advanced_json=excluded.advanced_json",
        (
            mlb_id,
            year,
            team_name,
            league_name or "",
            sport_level or "",
            dumps_json(stat_json),
            dumps_json(fielding_json),
            dumps_json(advanced_json),
        ),
    )


# ── Field mapping ──


def _apply_yearbyyear_fields(stat_doc: dict, group_name: str, stat: dict):
    if group_name == "pitching":
        stat_doc.update(
            {
                "era": safe_float(stat.get("era")),
                "whip": safe_float(stat.get("whip")),
                "ip": safe_float(stat.get("inningsPitched")),
                "so": safe_int(stat.get("strikeOuts")),
                "wins": safe_int(stat.get("wins")),
                "losses": safe_int(stat.get("losses")),
                "bb": safe_int(stat.get("baseOnBalls")),
                "sv": safe_int(stat.get("saves")),
                "hld": safe_int(stat.get("holds")),
                "gs": safe_int(stat.get("gamesStarted")),
                "earned_runs": safe_int(stat.get("earnedRuns")),
                "pitches": safe_int(stat.get("numberOfPitches")),
                "bf": safe_int(stat.get("battersFaced")),
                "k_per_9": safe_float(stat.get("strikeoutsPer9Inn")),
                "bb_per_9": safe_float(stat.get("walksPer9Inn")),
                "h_per_9": safe_float(stat.get("hitsPer9Inn")),
                "k_bb_ratio": safe_float(stat.get("strikeoutWalkRatio")),
                "hr_per_9": safe_float(stat.get("homeRunsPer9")),
                "p_per_ip": safe_float(stat.get("pitchesPerInning")),
                "r_per_9": safe_float(stat.get("runsScoredPer9")),
                "win_pct": str(stat.get("winPercentage", "")),
                "strike_pct": str(stat.get("strikePercentage", "")),
                "p_ground_outs": safe_int(stat.get("groundOuts")),
                "p_air_outs": safe_int(stat.get("airOuts")),
                "runs_allowed": safe_int(stat.get("runs")),
                "p_hits": safe_int(stat.get("hits")),
                "p_hr": safe_int(stat.get("homeRuns")),
                "p_hbp": safe_int(stat.get("hitByPitch")),
                "p_ibb": safe_int(stat.get("intentionalWalks")),
                "p_sb": safe_int(stat.get("stolenBases")),
                "p_cs": safe_int(stat.get("caughtStealing")),
                "p_gdp": safe_int(stat.get("groundIntoDoublePlay")),
                "p_doubles": safe_int(stat.get("doubles")),
                "p_triples": safe_int(stat.get("triples")),
                "p_tb": safe_int(stat.get("totalBases")),
                "p_ab": safe_int(stat.get("atBats")),
                "svo": safe_int(stat.get("saveOpportunities")),
                "bs": safe_int(stat.get("blownSaves")),
                "outs": safe_int(stat.get("outs")),
                "cg": safe_int(stat.get("completeGames")),
                "sho": safe_int(stat.get("shutouts")),
                "strikes": safe_int(stat.get("strikes")),
                "balks": safe_int(stat.get("balks")),
                "wp": safe_int(stat.get("wildPitches")),
                "pickoffs": safe_int(stat.get("pickoffs")),
                "gf": safe_int(stat.get("gamesFinished")),
                "ir": safe_int(stat.get("inheritedRunners")),
                "irs": safe_int(stat.get("inheritedRunnersScored")),
                "p_sac_bunts": safe_int(stat.get("sacBunts")),
                "p_sac_flies": safe_int(stat.get("sacFlies")),
                "p_avg": str(stat.get("avg", "")),
                "p_obp": str(stat.get("obp", "")),
                "p_slg": str(stat.get("slg", "")),
                "p_ops": str(stat.get("ops", "")),
                "p_sb_pct": str(stat.get("stolenBasePercentage", "")),
                "p_babip": safe_float(stat.get("babip")),
                "p_go_ao": safe_float(stat.get("groundOutsToAirouts")),
                "qs": safe_int(stat.get("qualityStarts")),
            }
        )
    elif group_name == "hitting":
        stat_doc.update(
            {
                "avg": safe_float(stat.get("avg")),
                "obp": safe_float(stat.get("obp")),
                "slg": safe_float(stat.get("slg")),
                "ops": safe_float(stat.get("ops")),
                "hr": safe_int(stat.get("homeRuns")),
                "rbi": safe_int(stat.get("rbi")),
                "sb": safe_int(stat.get("stolenBases")),
                "cs": safe_int(stat.get("caughtStealing")),
                "ab": safe_int(stat.get("atBats")),
                "hits": safe_int(stat.get("hits")),
                "hit_bb": safe_int(stat.get("baseOnBalls")),
                "pa": safe_int(stat.get("plateAppearances")),
                "doubles": safe_int(stat.get("doubles")),
                "triples": safe_int(stat.get("triples")),
                "tb": safe_int(stat.get("totalBases")),
                "hbp": safe_int(stat.get("hitByPitch")),
                "gdp": safe_int(stat.get("groundIntoDoublePlay")),
                "runs": safe_int(stat.get("runs")),
                "h_so": safe_int(stat.get("strikeOuts")),
                "ibb": safe_int(stat.get("intentionalWalks")),
                "h_ground_outs": safe_int(stat.get("groundOuts")),
                "h_air_outs": safe_int(stat.get("airOuts")),
                "pitches_seen": safe_int(stat.get("numberOfPitches")),
                "lob": safe_int(stat.get("leftOnBase")),
                "sac_bunts": safe_int(stat.get("sacBunts")),
                "sac_flies": safe_int(stat.get("sacFlies")),
                "ci": safe_int(stat.get("catchersInterference")),
                "babip": safe_float(stat.get("babip")),
                "go_ao": safe_float(stat.get("groundOutsToAirouts")),
                "sb_pct": str(stat.get("stolenBasePercentage", "")),
                "cs_pct": str(stat.get("caughtStealingPercentage", "")),
                "ab_per_hr": safe_float(stat.get("atBatsPerHomeRun")),
            }
        )


def _apply_advanced_fields(stat_doc: dict, group_name: str, stat: dict):
    if group_name == "hitting":
        for api_key, local_key in [
            ("reachedOnError", "roe"),
            ("walkOffs", "wo"),
            ("gidpOpp", "gidpo"),
            ("extraBaseHits", "xbh"),
        ]:
            val = safe_int(stat.get(api_key))
            if val is not None:
                stat_doc[local_key] = val
        for api_key, local_key in [
            ("babip", "babip"),
            ("pitchesPerPlateAppearance", "pitches_per_pa"),
        ]:
            val = safe_float(stat.get(api_key))
            if val is not None:
                stat_doc[local_key] = val
    elif group_name == "pitching":
        for api_key, local_key in [
            ("qualityStarts", "qs"),
            ("bequeathedRunners", "bqr"),
            ("bequeathedRunnersScored", "bqr_s"),
            ("gidpOpp", "p_gidpo"),
            ("runSupport", "run_support"),
        ]:
            val = safe_int(stat.get(api_key))
            if val is not None:
                stat_doc[local_key] = val
        for api_key, local_key in [
            ("runsScoredPer9", "rs_per_9"),
            ("babip", "p_babip"),
            ("pitchesPerPlateAppearance", "pitches_per_pa"),
        ]:
            val = safe_float(stat.get(api_key))
            if val is not None:
                stat_doc[local_key] = val


# ── Parallel data fetching ──


def _fetch_player_data(pconf: dict, year: int) -> Optional[dict]:
    """Fetch all API data for one player (no DB writes). Thread-safe."""
    mlb_id = pconf["mlb_id"]
    source = pconf.get("source", "milb")
    name_tw = pconf.get("name_tw", "")

    profile = get_player_profile(mlb_id)
    if not profile:
        logger.warning("No profile for %s (%s)", mlb_id, name_tw)
        return None

    # yearByYear stats
    stats_groups = []
    try:
        stats_groups = get_player_stats(mlb_id, source=source)
    except Exception as e:
        logger.warning("yearByYear failed for %s: %s", mlb_id, e)

    # Determine years with data for advanced/gamelog fetches
    years_with_data = set()
    for sg in stats_groups:
        if sg.get("type", {}).get("displayName", "") != "yearByYear":
            continue
        for split in sg.get("splits", []):
            yr = safe_int(split.get("season"))
            if yr:
                years_with_data.add(yr)

    # seasonAdvanced stats
    adv_groups = []
    try:
        years_to_fetch = sorted(years_with_data) if years_with_data else [year]
        adv_groups = get_player_advanced_stats(
            mlb_id, years=years_to_fetch, source=source
        )
    except Exception as e:
        logger.warning("seasonAdvanced failed for %s: %s", mlb_id, e)

    # Game logs
    if years_with_data:
        fetch_years = sorted(y for y in years_with_data if y == year) or sorted(
            years_with_data
        )
    else:
        fetch_years = [year]

    log_groups = {}
    for y in fetch_years:
        try:
            log_groups[y] = get_game_logs(mlb_id, y, source=source)
        except Exception as e:
            logger.warning("gameLog failed for %s/%s: %s", mlb_id, y, e)

    # Next game
    next_game = None
    try:
        team_id = profile.get("team_id")
        if team_id:
            next_game = get_next_game(team_id)
    except Exception as e:
        logger.warning("next-game failed for %s: %s", mlb_id, e)

    # FanGraphs
    fg_data = {}
    fg_id = pconf.get("fg_id")
    if fg_id:
        try:
            fg_position = pconf.get("fg_position", "OF")
            fg_data = get_fangraphs_stats(fg_id, position=fg_position)
        except Exception as e:
            logger.warning("fangraphs failed for %s: %s", mlb_id, e)

    return {
        "pconf": pconf,
        "profile": profile,
        "stats_groups": stats_groups,
        "adv_groups": adv_groups,
        "log_groups": log_groups,
        "next_game": next_game,
        "fg_data": fg_data,
        "years_with_data": years_with_data,
    }


def _write_player_to_db(conn: sqlite3.Connection, bundle: dict, year: int):
    """Write one player's fetched data into SQLite."""
    cur = conn.cursor()
    pconf = bundle["pconf"]
    profile = bundle["profile"]
    mlb_id = pconf["mlb_id"]
    source = pconf.get("source", "milb")
    name_tw = pconf.get("name_tw", "")
    years_with_data = bundle["years_with_data"]

    # Upsert player profile
    cur.execute(
        "INSERT INTO players "
        "(mlb_id, name_en, name_tw, team, level, position, source, "
        " height, weight, birth_date, birth_city, birth_country, is_active, "
        " bat_side, pitch_hand, latest_transaction, roster_status, team_id, "
        " transactions_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(mlb_id) DO UPDATE SET "
        " name_en=excluded.name_en, name_tw=excluded.name_tw, "
        " position=excluded.position, source=excluded.source, "
        " height=excluded.height, weight=excluded.weight, "
        " birth_date=excluded.birth_date, birth_city=excluded.birth_city, "
        " birth_country=excluded.birth_country, is_active=excluded.is_active, "
        " bat_side=excluded.bat_side, pitch_hand=excluded.pitch_hand, "
        " latest_transaction=excluded.latest_transaction, "
        " roster_status=excluded.roster_status, team_id=excluded.team_id, "
        " transactions_json=excluded.transactions_json",
        (
            profile.get("mlb_id"),
            profile.get("full_name", ""),
            name_tw,
            profile.get("current_team_name") or "N/A",
            profile.get("current_team_level")
            or ("MLB" if source == "mlb" else "Minors"),
            profile.get("position", ""),
            source,
            profile.get("height", ""),
            profile.get("weight"),
            profile.get("birth_date"),
            profile.get("birth_city", ""),
            profile.get("birth_country", ""),
            1 if profile.get("is_active", True) else 0,
            profile.get("bat_side", ""),
            profile.get("pitch_hand", ""),
            profile.get("latest_transaction", ""),
            profile.get("roster_status", ""),
            profile.get("team_id"),
            dumps_json(profile.get("transactions_json", [])),
        ),
    )

    # yearByYear stats
    for stat_group in bundle["stats_groups"]:
        group_name = stat_group.get("group", {}).get("displayName", "").lower()
        stat_type = stat_group.get("type", {}).get("displayName", "")
        if stat_type != "yearByYear":
            continue

        for split in stat_group.get("splits", []):
            yr = safe_int(split.get("season"))
            stat = split.get("stat", {})
            team_name = split.get("team", {}).get("name", "")
            if not yr or not team_name:
                continue

            row = _load_season_row(cur, mlb_id, yr, team_name)
            stat_doc = row["stat_json"]
            fielding_doc = row["fielding_json"]

            stat_doc["gp"] = safe_int(stat.get("gamesPlayed"))
            _apply_yearbyyear_fields(stat_doc, group_name, stat)

            if group_name == "fielding":
                pos_abbr = split.get("position", {}).get("abbreviation", "")
                if pos_abbr:
                    entry = {
                        "position": pos_abbr,
                        "gp": safe_int(stat.get("gamesPlayed")),
                        "gs": safe_int(stat.get("gamesStarted")),
                        "innings": safe_float(stat.get("innings")),
                        "assists": safe_int(stat.get("assists")),
                        "putouts": safe_int(stat.get("putOuts")),
                        "errors": safe_int(stat.get("errors")),
                        "chances": safe_int(stat.get("chances")),
                        "fielding_pct": str(stat.get("fielding", "")),
                        "dp": safe_int(stat.get("doublePlays")),
                        "tp": safe_int(stat.get("triplePlays")),
                        "throwing_errors": safe_int(stat.get("throwingErrors")),
                        "range_factor_game": safe_float(stat.get("rangeFactorPerGame")),
                        "range_factor_9": safe_float(stat.get("rangeFactorPer9Inn")),
                    }
                    fielding_doc = [
                        f for f in fielding_doc if f.get("position") != pos_abbr
                    ]
                    fielding_doc.append(entry)

            _save_season_row(
                cur,
                mlb_id,
                yr,
                team_name,
                split.get("league", {}).get("name", ""),
                split.get("sport", {}).get("abbreviation", ""),
                stat_doc,
                fielding_doc,
                row["advanced_json"],
            )

    # seasonAdvanced stats
    for stat_group in bundle["adv_groups"]:
        group_name = stat_group.get("group", {}).get("displayName", "").lower()
        for split in stat_group.get("splits", []):
            yr = safe_int(split.get("season"))
            team_name = split.get("team", {}).get("name", "")
            if not yr or not team_name:
                continue

            row = _load_season_row(cur, mlb_id, yr, team_name)
            stat_doc = row["stat_json"]
            _apply_advanced_fields(stat_doc, group_name, split.get("stat", {}))

            _save_season_row(
                cur,
                mlb_id,
                yr,
                team_name,
                row["league_name"],
                row["sport_level"],
                stat_doc,
                row["fielding_json"],
                row["advanced_json"],
            )

    # Update level/team
    if not profile.get("current_team_level") or not profile.get("current_team_name"):
        level_order_sql = " ".join(
            f"WHEN '{k}' THEN {v}" for k, v in SPORT_LEVEL_ORDER.items()
        )
        cur.execute(
            f"SELECT sport_level, team_name FROM season_stats "
            f"WHERE player_mlb_id = ? "
            f"ORDER BY year DESC, CASE sport_level {level_order_sql} ELSE 50 END ASC "
            f"LIMIT 1",
            (mlb_id,),
        )
        latest = cur.fetchone()
        if latest:
            cur.execute(
                "UPDATE players SET level=?, team=? WHERE mlb_id=?",
                (latest[0] or "Minors", latest[1] or "N/A", mlb_id),
            )
    else:
        cur.execute(
            "UPDATE players SET level=?, team=? WHERE mlb_id=?",
            (
                profile.get("current_team_level") or "Minors",
                profile.get("current_team_name") or "N/A",
                mlb_id,
            ),
        )

    # Game logs
    for y, log_groups in bundle["log_groups"].items():
        for log_group in log_groups:
            if log_group.get("type", {}).get("displayName", "") != "gameLog":
                continue
            for split in log_group.get("splits", []):
                game_date = split.get("date")
                game_pk = split.get("game", {}).get("gamePk")
                if not game_date or not game_pk:
                    continue
                cur.execute(
                    "INSERT INTO game_logs "
                    "(player_mlb_id, date, game_id, opponent, is_home, stats_json) "
                    "VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(player_mlb_id, game_id) DO UPDATE SET "
                    " date=excluded.date, opponent=excluded.opponent, "
                    " is_home=excluded.is_home, stats_json=excluded.stats_json",
                    (
                        mlb_id,
                        game_date,
                        game_pk,
                        split.get("opponent", {}).get("name", "Unknown"),
                        1 if split.get("isHome") else 0,
                        dumps_json(split.get("stat", {})),
                    ),
                )

    # Next game snapshot
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur.execute(
        "UPDATE players SET next_game_json=?, next_game_updated_at=?, "
        "next_game_for_season=? WHERE mlb_id=?",
        (dumps_json(bundle["next_game"] or {}), now, year, mlb_id),
    )

    # FanGraphs merge
    fg_data = bundle["fg_data"]
    for _key, stats_dict in fg_data.items():
        season = stats_dict.get("season")
        if not season:
            continue
        cur.execute(
            "SELECT team_name, league_name, sport_level, stat_json, fielding_json, advanced_json "
            "FROM season_stats WHERE player_mlb_id = ? AND year = ?",
            (mlb_id, season),
        )
        rows = cur.fetchall()
        for row in rows:
            advanced_doc = loads_json_dict(row[5])
            advanced_doc["fangraphs"] = stats_dict
            _save_season_row(
                cur,
                mlb_id,
                season,
                row[0],
                row[1],
                row[2],
                loads_json_dict(row[3]),
                loads_json_list(row[4]),
                advanced_doc,
            )

    conn.commit()


# ── Public entry point ──


def sync_database(
    db_path: str,
    roster_file: str,
    year: int,
    only_player: Optional[int] = None,
):
    """Sync all player data from APIs into SQLite, using parallel fetches."""
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    _init_db(conn)

    players_config = parse_roster_from_file(roster_file)
    if only_player is not None:
        players_config = [p for p in players_config if p.get("mlb_id") == only_player]

    total = len(players_config)
    print(f"Syncing {total} players into {db_file} (max {MAX_WORKERS} parallel)")

    # Phase 1: Fetch all data in parallel
    bundles = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_name = {
            executor.submit(_fetch_player_data, pconf, year): pconf.get(
                "name_tw", pconf["mlb_id"]
            )
            for pconf in players_config
        }
        for i, future in enumerate(as_completed(future_to_name), 1):
            name = future_to_name[future]
            try:
                result = future.result()
                if result:
                    bundles.append(result)
                    print(f"  [{i}/{total}] fetched {name}")
                else:
                    print(f"  [{i}/{total}] skipped {name} (no profile)")
            except Exception as e:
                print(f"  [{i}/{total}] error {name}: {e}")
                logger.exception("Fetch failed for %s", name)

    # Phase 2: Write to DB sequentially
    for bundle in bundles:
        name = bundle["pconf"].get("name_tw", bundle["profile"].get("full_name"))
        try:
            _write_player_to_db(conn, bundle, year)
            print(f"  saved {name}")
        except Exception as e:
            print(f"  DB write error for {name}: {e}")
            logger.exception("DB write failed for %s", name)

    conn.close()
    print("Sync complete")
