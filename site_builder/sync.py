"""
Data synchronization: fetch from MLB APIs and store in SQLite.

Uses concurrent.futures to fetch player data in parallel for faster syncs.
"""

import datetime
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from site_builder.api import (
    get_game_logs,
    get_game_play_by_play,
    get_game_sport_level,
    get_next_game,
    get_player_advanced_stats,
    get_player_expected_stats,
    get_player_profile,
    get_player_sabermetrics,
    get_player_stats,
    parse_roster_from_file,
    sport_obj_to_abbr,
)
from site_builder.levels import TIERS
from site_builder.helpers import (
    categorize_roster_status,
    dumps_json,
    loads_json,
    loads_json_dict,
    loads_json_list,
    safe_float,
    safe_int,
)
from site_builder.statcast import (
    compute_batter_statcast,
    compute_fip,
    compute_pitcher_statcast,
    compute_xwpct,
    extract_pitch_logs,
)

logger = logging.getLogger(__name__)

MAX_WORKERS = 10  # parallel threads for all API fetch and statcast compute phases


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
            roster_status_code TEXT NOT NULL DEFAULT '',
            roster_is_active INTEGER NOT NULL DEFAULT 0,
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
            pitches_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(player_mlb_id, game_id)
        );

        CREATE TABLE IF NOT EXISTS playbyplay_processed (
            game_pk INTEGER PRIMARY KEY,
            processed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_season_stats_player_year
            ON season_stats(player_mlb_id, year);
        CREATE INDEX IF NOT EXISTS idx_game_logs_player_date
            ON game_logs(player_mlb_id, date);
    """)
    # Forward-migration: add pitches_json column if it does not yet exist
    # (needed for databases created before Statcast support).
    try:
        conn.execute("ALTER TABLE game_logs ADD COLUMN pitches_json TEXT NOT NULL DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Forward-migration: add sport_level column to game_logs if it does not yet exist.
    try:
        conn.execute("ALTER TABLE game_logs ADD COLUMN sport_level TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Forward-migration: add roster_status_code/roster_is_active columns to players
    # if they do not yet exist (needed for richer status-pill classification).
    try:
        conn.execute("ALTER TABLE players ADD COLUMN roster_status_code TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE players ADD COLUMN roster_is_active INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Forward-migration: track whether hit_coord backfill has been attempted for this
    # player-game row. Prevents re-fetching games where the API genuinely has no
    # hit coordinates (pre-2019 MLB, low-level MiLB).
    try:
        conn.execute(
            "ALTER TABLE game_logs ADD COLUMN hit_coord_checked INTEGER NOT NULL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()


# ── Season row load/save ──


def _load_season_row(cur, mlb_id: int, year: int, team_name: str) -> dict:
    cur.execute(
        "SELECT league_name, sport_level, stat_json, fielding_json "
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
        }
    return {
        "league_name": row[0] or "",
        "sport_level": row[1] or "",
        "stat_json": loads_json(row[2], {}),
        "fielding_json": loads_json(row[3], []),
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
):
    cur.execute(
        "INSERT INTO season_stats "
        "(player_mlb_id, year, team_name, league_name, sport_level, stat_json, fielding_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(player_mlb_id, year, team_name) DO UPDATE SET "
        " league_name=excluded.league_name, sport_level=excluded.sport_level, "
        " stat_json=excluded.stat_json, fielding_json=excluded.fielding_json",
        (
            mlb_id,
            year,
            team_name,
            league_name or "",
            sport_level or "",
            dumps_json(stat_json),
            dumps_json(fielding_json),
        ),
    )


def _players_with_existing_stats(conn: sqlite3.Connection) -> set[int]:
    """Return mlb_ids that already have season_stats rows.

    Used to detect players being synced for the first time, so their
    history can be fully backfilled even during a fetch_all_years=False
    (update/refresh) run.
    """
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT player_mlb_id FROM season_stats")
    return {row[0] for row in cur.fetchall()}


def _warn_orphaned_players(conn: sqlite3.Connection, roster_ids: set[int]):
    """Print a warning for any players in the DB that are not in the current roster.

    These orphans accumulate when a player's MLB ID is corrected in roster.json
    or when a player is removed from the roster without cleaning the database.
    They won't appear on the built site (the builder filters by roster) but they
    do occupy space in the database and can cause confusion.
    """
    cur = conn.cursor()
    cur.execute("SELECT mlb_id, name_en, name_tw FROM players ORDER BY mlb_id")
    orphans = [
        (mlb_id, name_en, name_tw)
        for mlb_id, name_en, name_tw in cur.fetchall()
        if mlb_id not in roster_ids
    ]
    if not orphans:
        return
    print(f"  WARNING: {len(orphans)} DB player(s) not in current roster (won't appear on site):")
    for mlb_id, name_en, name_tw in orphans:
        label = f"{name_tw} / {name_en}" if name_tw else name_en
        print(f"    {mlb_id}  {label}")
    print(
        "  To remove orphans, run:\n"
        "    sqlite3 data/tracker.sqlite3 "
        "\"DELETE FROM game_logs WHERE player_mlb_id NOT IN "
        f"({','.join(str(i) for i in roster_ids)}); "
        "DELETE FROM season_stats WHERE player_mlb_id NOT IN "
        f"({','.join(str(i) for i in roster_ids)}); "
        "DELETE FROM players WHERE mlb_id NOT IN "
        f"({','.join(str(i) for i in roster_ids)});\""
    )


def _is_first_sync(mlb_id: int, synced_ids: set[int]) -> bool:
    """A player with no season_stats rows yet is being synced for the first time."""
    return mlb_id not in synced_ids


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


def _fetch_player_data(
    pconf: dict, year: int, fetch_all_years: bool = True
) -> Optional[dict]:
    """Fetch all API data for one player (no DB writes). Thread-safe.

    Args:
        pconf: Player configuration dict from roster.
        year: The target/current season year.
        fetch_all_years: If True (sync mode), fetch game logs for ALL historical
            years. If False (update mode), only fetch the current year's logs
            for a faster update.
    """
    mlb_id = pconf["mlb_id"]
    name_tw = pconf.get("name_tw", "")

    profile = get_player_profile(mlb_id)
    if not profile:
        logger.warning("No profile for %s (%s)", mlb_id, name_tw)
        return None

    status_category = categorize_roster_status(
        profile.get("roster_status_code", ""),
        bool(profile.get("roster_is_active", False)),
        bool(profile.get("is_active", True)),
    )
    if status_category == "inactive" and not fetch_all_years:
        # Player has left the organization (Released/Retired/Voluntarily
        # Retired) and has already been synced before (fetch_all_years=False
        # means the caller already has season_stats for this player) --
        # their historical stats won't change further. Refresh just the
        # profile (so status/team info stays current) and skip the heavier
        # stats/advanced-stats/game-log/next-game fetches. A first-time sync
        # (fetch_all_years=True) always runs the full fetch below so newly
        # added retired players get their history backfilled once.
        return {
            "pconf": pconf,
            "profile": profile,
            "status_category": status_category,
            "stats_groups": [],
            "adv_groups": [],
            "log_groups": {},
            "next_game": None,
            "years_with_data": set(),
        }

    # yearByYear stats
    stats_groups = []
    try:
        stats_groups = get_player_stats(mlb_id)
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
        if not fetch_all_years:
            # update mode: only fetch advanced stats for the current year
            years_to_fetch = [year]
        adv_groups = get_player_advanced_stats(
            mlb_id, years=years_to_fetch
        )
    except Exception as e:
        logger.warning("seasonAdvanced failed for %s: %s", mlb_id, e)

    # Game logs — in sync mode fetch ALL historical years so the game log
    # tab shows data for every season, not just the current one.
    if fetch_all_years:
        fetch_years = sorted(years_with_data) if years_with_data else [year]
    else:
        # update mode: only refresh the current year's logs (fast)
        fetch_years = [year]

    log_groups = {}
    for y in fetch_years:
        try:
            log_groups[y] = get_game_logs(mlb_id, y)
        except Exception as e:
            logger.warning("gameLog failed for %s/%s: %s", mlb_id, y, e)

    # Next game -- skip for inactive (retired/released) players even during
    # a first-time backfill, since profile.team_id reflects their *last*
    # team and would otherwise show that team's schedule as "next game".
    next_game = None
    try:
        team_id = profile.get("team_id")
        if team_id and status_category != "inactive":
            next_game = get_next_game(team_id)
    except Exception as e:
        logger.warning("next-game failed for %s: %s", mlb_id, e)

    return {
        "pconf": pconf,
        "profile": profile,
        "status_category": status_category,
        "stats_groups": stats_groups,
        "adv_groups": adv_groups,
        "log_groups": log_groups,
        "next_game": next_game,
        "years_with_data": years_with_data,
    }


def _write_player_to_db(conn: sqlite3.Connection, bundle: dict, year: int):
    """Write one player's fetched data into SQLite."""
    cur = conn.cursor()
    pconf = bundle["pconf"]
    profile = bundle["profile"]
    mlb_id = pconf["mlb_id"]
    name_tw = pconf.get("name_tw", "")
    years_with_data = bundle["years_with_data"]

    # Upsert player profile
    cur.execute(
        "INSERT INTO players "
        "(mlb_id, name_en, name_tw, team, level, position, "
        " height, weight, birth_date, birth_city, birth_country, is_active, "
        " bat_side, pitch_hand, latest_transaction, roster_status, "
        " roster_status_code, roster_is_active, team_id, "
        " transactions_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(mlb_id) DO UPDATE SET "
        " name_en=excluded.name_en, name_tw=excluded.name_tw, "
        " position=excluded.position, "
        " height=excluded.height, weight=excluded.weight, "
        " birth_date=excluded.birth_date, birth_city=excluded.birth_city, "
        " birth_country=excluded.birth_country, is_active=excluded.is_active, "
        " bat_side=excluded.bat_side, pitch_hand=excluded.pitch_hand, "
        " latest_transaction=excluded.latest_transaction, "
        " roster_status=excluded.roster_status, "
        " roster_status_code=excluded.roster_status_code, "
        " roster_is_active=excluded.roster_is_active, team_id=excluded.team_id, "
        " transactions_json=excluded.transactions_json",
        (
            profile.get("mlb_id"),
            profile.get("full_name", ""),
            name_tw,
            profile.get("current_team_name") or "N/A",
            profile.get("current_team_level") or "Minors",
            profile.get("position", ""),
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
            profile.get("roster_status_code", ""),
            1 if profile.get("roster_is_active", False) else 0,
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

            # Only overwrite gp from hitting/pitching; fielding splits have per-position
            # gamesPlayed which would otherwise clobber the correct total.
            if group_name != "fielding":
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
            )

    # Update level/team
    if not profile.get("current_team_level") or not profile.get("current_team_name"):
        # Rank every raw sport_level spelling (incl. historical ones like
        # "A(Adv)" / "A(Short)") via the single level registry, so the "latest
        # level" pick orders pre-2021 rows correctly too.
        level_order_sql = " ".join(
            f"WHEN '{alias}' THEN {t.rank}"
            for t in TIERS
            for alias in t.aliases
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
            group_sport_level = log_group.get("sport", {}).get("abbreviation", "")
            for split in log_group.get("splits", []):
                game_date = split.get("date")
                game_pk = split.get("game", {}).get("gamePk")
                if not game_date or not game_pk:
                    continue
                # Prefer split-level sport, fall back to group-level
                split_sport_level = (
                    split.get("sport", {}).get("abbreviation", "")
                    or group_sport_level
                )
                cur.execute(
                    "INSERT INTO game_logs "
                    "(player_mlb_id, date, game_id, opponent, is_home, stats_json, sport_level) "
                    "VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(player_mlb_id, game_id) DO UPDATE SET "
                    " date=excluded.date, opponent=excluded.opponent, "
                    " is_home=excluded.is_home, stats_json=excluded.stats_json, "
                    " sport_level = CASE WHEN excluded.sport_level != '' "
                    "   THEN excluded.sport_level ELSE game_logs.sport_level END",
                    (
                        mlb_id,
                        game_date,
                        game_pk,
                        split.get("opponent", {}).get("name", "Unknown"),
                        1 if split.get("isHome") else 0,
                        dumps_json(split.get("stat", {})),
                        split_sport_level,
                    ),
                )

    # Next game snapshot
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur.execute(
        "UPDATE players SET next_game_json=?, next_game_updated_at=?, "
        "next_game_for_season=? WHERE mlb_id=?",
        (dumps_json(bundle["next_game"] or {}), now, year, mlb_id),
    )

    conn.commit()


# ── Public entry point ──


def _run_pipeline(
    db_path: str,
    roster_file: str,
    year: int,
    only_player: Optional[int] = None,
    fetch_all_years: bool = True,
    mode_label: str = "Sync",
):
    """Shared fetch-and-write pipeline used by both sync and update."""
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file)
    _init_db(conn)

    players_config = parse_roster_from_file(roster_file)
    if only_player is not None:
        players_config = [p for p in players_config if p.get("mlb_id") == only_player]

    # Players with no season_stats rows yet have never been synced. Force a
    # full historical fetch for them even on an update/refresh run, so
    # newly added players (e.g. retired players added straight to the
    # roster) get backfilled automatically on the next pipeline run.
    synced_ids = _players_with_existing_stats(conn)
    cur = conn.cursor()
    cur.execute("SELECT mlb_id, is_active FROM players")
    cached_is_active = {row[0]: bool(row[1]) for row in cur.fetchall()}

    # Players cached as is_active=False (the API's "active" flag, set the
    # last time their profile was fetched) have permanently left affiliated
    # ball and won't come back, so skip them entirely on subsequent runs --
    # no profile/status re-fetch, no further steps. Players cached as
    # is_active=True keep going through _fetch_player_data, which refreshes
    # the profile and -- based on the *new* status -- either continues with
    # the full fetch (still active) or skips the heavier stats/log fetches
    # (e.g. just released, possibly RET/RL/VL). A first-time sync (no
    # season_stats yet) always runs the full fetch so newly added retired
    # players get backfilled once, and --player always forces a fetch
    # regardless of cached status.
    players_to_fetch = []
    for pconf in players_config:
        mlb_id = pconf["mlb_id"]
        if (
            only_player is None
            and cached_is_active.get(mlb_id) is False
            and not _is_first_sync(mlb_id, synced_ids)
        ):
            print(f"  skipped {pconf.get('name_tw', mlb_id)} (inactive, status cached)")
            continue
        players_to_fetch.append(pconf)

    total = len(players_to_fetch)
    print(
        f"{mode_label}: {total} players into {db_file} "
        f"(max {MAX_WORKERS} parallel, all_years={fetch_all_years})"
    )

    # Phase 1: Fetch all data in parallel
    bundles = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_pconf = {
            executor.submit(
                _fetch_player_data,
                pconf,
                year,
                fetch_all_years or _is_first_sync(pconf["mlb_id"], synced_ids),
            ): pconf
            for pconf in players_to_fetch
        }
        for i, future in enumerate(as_completed(future_to_pconf), 1):
            pconf = future_to_pconf[future]
            name = pconf.get("name_tw", pconf["mlb_id"])
            try:
                result = future.result()
                if result:
                    bundles.append(result)
                    if result.get("status_category") == "inactive":
                        if _is_first_sync(pconf["mlb_id"], synced_ids):
                            print(f"  [{i}/{total}] fetched {name} (inactive: first-time backfill)")
                        elif fetch_all_years:
                            print(f"  [{i}/{total}] fetched {name} (inactive: full re-sync)")
                        else:
                            print(f"  [{i}/{total}] fetched {name} (inactive: profile only)")
                    else:
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

    # After a full sync (not a single-player run), check for orphaned DB entries
    # that are no longer referenced by the current roster.
    if only_player is None:
        roster_ids = {p["mlb_id"] for p in parse_roster_from_file(roster_file)}
        _warn_orphaned_players(conn, roster_ids)

    conn.close()
    print(f"{mode_label} complete")


def sync_database(
    db_path: str,
    roster_file: str,
    year: int,
    only_player: Optional[int] = None,
):
    """Full sync: fetch ALL historical years of stats + game logs for every player.

    Use this to build the database from scratch or ensure complete historical data.
    Slower than update_database because it fetches game logs for every season.
    """
    _run_pipeline(
        db_path=db_path,
        roster_file=roster_file,
        year=year,
        only_player=only_player,
        fetch_all_years=True,
        mode_label="Sync",
    )


def update_database(
    db_path: str,
    roster_file: str,
    year: int,
    only_player: Optional[int] = None,
):
    """Fast update: refresh player profiles and current-year stats/logs only.

    Use this for daily/regular updates during the season. It fetches yearByYear
    stats (all years) for the season-stats table, but only downloads game logs
    for the current year, making it significantly faster than a full sync.
    """
    _run_pipeline(
        db_path=db_path,
        roster_file=roster_file,
        year=year,
        only_player=only_player,
        fetch_all_years=False,
        mode_label="Update",
    )


# ══════════════════════════════════════════════════════════════════════════
# STATCAST SYNC
# ══════════════════════════════════════════════════════════════════════════


def _build_roster_map(roster_file: str) -> dict:
    """Return {mlb_id: pconf} for quick lookup during statcast sync."""
    return {p["mlb_id"]: p for p in parse_roster_from_file(roster_file)}


def _fetch_and_extract_game(
    game_pk: int, players_in_game: list[tuple[int, str]]
) -> tuple[dict[int, list[dict]], str]:
    """Fetch one game's live feed and extract pitches for every relevant player.

    Args:
        game_pk: the game primary key.
        players_in_game: list of (mlb_id, position) tuples — players we
                         care about that appeared in this game.

    Returns:
        A 2-tuple of:
          - {mlb_id: [pitch_dict, ...]}  (may be empty per player)
          - sport_level string (e.g. "MLB", "AAA") extracted from the live feed,
            or "" if unavailable.
    """
    game_data = get_game_play_by_play(game_pk)
    out: dict[int, list[dict]] = {}
    if not game_data:
        return out, ""
    sport_obj = (
        game_data.get("gameData", {})
        .get("teams", {})
        .get("home", {})
        .get("sport", {})
    )
    sport_level: str = sport_obj_to_abbr(sport_obj)
    for mlb_id, position in players_in_game:
        role = "pitcher" if position == "P" else "batter"
        pitches = extract_pitch_logs(game_data, mlb_id, role)
        if not pitches:
            # try the opposite role as fallback (two-way / misconfigured roster)
            alt = "batter" if role == "pitcher" else "pitcher"
            pitches = extract_pitch_logs(game_data, mlb_id, alt)
        out[mlb_id] = pitches
    return out, sport_level


def _pitches_need_hit_coord_backfill(pitches: list[dict]) -> bool:
    in_play = [p for p in pitches if p.get("is_in_play")]
    if not in_play:
        return False
    return all(
        p.get("hit_coord_x") is None or p.get("hit_coord_y") is None
        for p in in_play
    )


def _load_all_pitches_for_player(cur, mlb_id: int) -> dict[tuple, list[dict]]:
    """Return {(year, sport_level): [pitch_dict, ...]} merged across all cached games.

    When a game_logs row has an empty sport_level, we attempt to resolve it
    from season_stats.  If the player only appeared at one level in that year,
    the resolution is unambiguous; otherwise the pitches are grouped under
    ``(year, "")`` and the caller must handle the ambiguity.
    """
    cur.execute(
        "SELECT date, sport_level, pitches_json FROM game_logs "
        "WHERE player_mlb_id = ? AND pitches_json != '[]' AND pitches_json IS NOT NULL",
        (mlb_id,),
    )
    by_year_level: dict[tuple, list[dict]] = {}
    # Buffer games with empty sport_level for resolution
    unresolved: list[tuple[int, list[dict]]] = []  # (year, pitches)

    for row in cur.fetchall():
        date_str = row[0] or ""
        sport_level = row[1] or ""
        if len(date_str) < 4:
            continue
        try:
            yr = int(date_str[:4])
        except ValueError:
            continue
        pitches = loads_json_list(row[2])
        if not pitches:
            continue
        if sport_level:
            by_year_level.setdefault((yr, sport_level), []).extend(pitches)
        else:
            unresolved.append((yr, pitches))

    if not unresolved:
        return by_year_level

    # Build {year: [sport_level, ...]} from season_stats for resolution
    cur.execute(
        "SELECT year, sport_level FROM season_stats "
        "WHERE player_mlb_id = ? AND sport_level != ''",
        (mlb_id,),
    )
    levels_by_year: dict[int, set[str]] = {}
    for row in cur.fetchall():
        levels_by_year.setdefault(row[0], set()).add(row[1])

    for yr, pitches in unresolved:
        known_levels = levels_by_year.get(yr, set())
        if len(known_levels) == 1:
            # Unambiguous: assign to the single known level
            lvl = next(iter(known_levels))
            by_year_level.setdefault((yr, lvl), []).extend(pitches)
        else:
            # Ambiguous or unknown: keep under empty key for caller to handle
            by_year_level.setdefault((yr, ""), []).extend(pitches)

    return by_year_level


def _merge_statcast_into_season(
    cur,
    mlb_id: int,
    year: int,
    position: str,
    statcast_data: dict,
    sport_level: str = "",
    sabermetrics: Optional[dict] = None,
    expected_stats: Optional[dict] = None,
):
    """Merge computed Statcast + sabermetrics + expected-stats into season_stats.

    ``statcast_data`` is written only to rows whose sport_level matches
    ``sport_level`` (when provided and non-empty). This ensures that players
    who played at multiple levels in the same year get per-level Statcast data
    rather than the same season-aggregate written to every row.

    When ``sport_level`` is empty (legacy data with unresolved levels):
      - If there is exactly ONE season_stats row for the year, write to it.
      - If there are MULTIPLE rows, skip writing statcast to prevent the bug
        where identical combined data appears for every level.

    ``sabermetrics`` (MLB-only) and ``expected_stats`` are also written only
    to the row whose sport_level matches ``sport_level`` (not broadcast to all
    rows). This prevents shuttle-player rows at MiLB levels from receiving
    MLB-derived aggregate stats.
    """
    cur.execute(
        "SELECT team_name, league_name, sport_level, stat_json, fielding_json "
        "FROM season_stats WHERE player_mlb_id = ? AND year = ?",
        (mlb_id, year),
    )
    rows = cur.fetchall()
    if not rows:
        return

    is_pitcher = position == "P"

    for row in rows:
        team_name = row[0]
        league_name = row[1]
        row_sport_level = row[2]
        stat_doc = loads_json_dict(row[3])
        fielding_doc = loads_json_list(row[4])

        # Write statcast only to the matching level row.
        # If sport_level is empty (unresolved legacy data), only write when
        # there is a single row for the year (unambiguous).
        if sport_level:
            if row_sport_level == sport_level:
                stat_doc["statcast"] = statcast_data
        elif len(rows) == 1:
            stat_doc["statcast"] = statcast_data
        # else: multiple rows + unknown level → skip to avoid duplicates

        # Attach sabermetrics (MLB only) — only write to the matching sport_level row.
        # Sabermetrics are always fetched from the MLB endpoint; broadcasting them
        # to MiLB rows of the same year would be misleading.
        if sabermetrics and row_sport_level == "MLB":
            if not sport_level or row_sport_level == sport_level:
                stat_doc["saber"] = sabermetrics

        # Attach expected stats — only write to the matching sport_level row.
        # MiLB expected stats are all 0.0 (API limitation), so valid data only
        # arrives for MLB rows; still guard by sport_level match for correctness.
        if expected_stats:
            if sport_level and row_sport_level == sport_level:
                stat_doc["expected"] = expected_stats
            elif not sport_level and len(rows) == 1:
                stat_doc["expected"] = expected_stats

        # Compute FIP (MiLB path) if we have enough inputs
        if is_pitcher and row_sport_level and row_sport_level != "MLB":
            ip = stat_doc.get("ip")
            fip_val = compute_fip(
                hr=stat_doc.get("p_hr"),
                bb=stat_doc.get("bb"),
                hbp=stat_doc.get("p_hbp"),
                k=stat_doc.get("so"),
                ip=safe_float(ip),
                sport_level=row_sport_level,
                year=year,
            )
            if fip_val is not None:
                stat_doc["fip"] = fip_val
                stat_doc["xwpct"] = compute_xwpct(fip_val, row_sport_level)
        elif is_pitcher and row_sport_level == "MLB" and sabermetrics:
            fip_val = safe_float(sabermetrics.get("fip"))
            if fip_val is not None:
                stat_doc["fip"] = round(fip_val, 2)
                stat_doc["xfip"] = safe_float(sabermetrics.get("xfip"))
                stat_doc["war"] = safe_float(sabermetrics.get("war"))
                stat_doc["xwpct"] = compute_xwpct(fip_val, "MLB")
        elif not is_pitcher and row_sport_level == "MLB" and sabermetrics:
            # Batter sabermetrics — extract WAR and wRC+ to top-level fields
            stat_doc["war"] = safe_float(sabermetrics.get("war"))
            wrc_plus_val = safe_int(sabermetrics.get("wRcPlus"))
            if wrc_plus_val is not None:
                stat_doc["wrc_plus"] = wrc_plus_val

        _save_season_row(
            cur, mlb_id, year, team_name,
            league_name, row_sport_level, stat_doc, fielding_doc,
        )


def _compute_player_statcast_bundle(
    mlb_id: int,
    db_path: str,
    position: str,
) -> tuple[int, Optional[dict]]:
    """Parallel worker: load pitches + fetch API stats + compute statcast.

    Opens its own SQLite connection for reads; performs no DB writes.
    Returns (mlb_id, {(year, sport_level): {statcast, sabermetrics, expected_stats}})
    or (mlb_id, None) when the player has no pitch data.
    """
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    try:
        pitches_by_year_level = _load_all_pitches_for_player(cur, mlb_id)
        if not pitches_by_year_level:
            return mlb_id, None

        years = sorted({k[0] for k in pitches_by_year_level.keys()})

        cur.execute(
            "SELECT COUNT(*) FROM season_stats WHERE player_mlb_id = ? AND sport_level = 'MLB'",
            (mlb_id,),
        )
        has_mlb_stats = (cur.fetchone() or [0])[0] > 0
    finally:
        conn.close()

    is_pitcher = position == "P"
    saber_by_year: dict[int, dict] = {}
    expected_by_year: dict[tuple, dict] = {}

    if has_mlb_stats:
        try:
            target_group = "pitching" if is_pitcher else "hitting"
            saber_groups = get_player_sabermetrics(mlb_id, years=years)
            for grp in saber_groups:
                if grp.get("group", {}).get("displayName", "").lower() != target_group:
                    continue
                for sp in grp.get("splits", []):
                    yr = safe_int(sp.get("season"))
                    if yr:
                        saber_by_year[yr] = sp.get("stat", {})
        except Exception as e:
            logger.warning("sabermetrics fetch failed for %s: %s", mlb_id, e)

    try:
        group = "pitching" if is_pitcher else "hitting"
        exp_groups = get_player_expected_stats(mlb_id, years=years, group=group)
        for grp in exp_groups:
            for sp in grp.get("splits", []):
                yr = safe_int(sp.get("season"))
                if yr:
                    stat = sp.get("stat", {})
                    xba = safe_float(stat.get("avg"))
                    xslg = safe_float(stat.get("slg"))
                    xwoba = safe_float(stat.get("woba"))
                    xwobacon = safe_float(stat.get("wobaCon"))
                    if not any([xba, xslg, xwoba, xwobacon]):
                        continue
                    split_sport_level = (
                        sp.get("sport", {}).get("abbreviation", "") or "MLB"
                    )
                    expected_by_year[(yr, split_sport_level)] = {
                        "xba": xba,
                        "xslg": xslg,
                        "xwoba": xwoba,
                        "xwobacon": xwobacon,
                    }
    except Exception as e:
        logger.warning("expectedStats fetch failed for %s: %s", mlb_id, e)

    results: dict[tuple, dict] = {}
    for (yr, lvl), pitches in pitches_by_year_level.items():
        if is_pitcher:
            statcast_data = compute_pitcher_statcast(pitches, year=yr, sport_level=lvl)
        else:
            statcast_data = compute_batter_statcast(pitches, year=yr, sport_level=lvl)
        results[(yr, lvl)] = {
            "statcast": statcast_data,
            "sabermetrics": saber_by_year.get(yr),
            "expected_stats": expected_by_year.get((yr, lvl)),
        }

    return mlb_id, results


def sync_statcast(
    db_path: str,
    roster_file: str,
    year: int,
    only_player: Optional[int] = None,
):
    """Fetch playByPlay for every un-processed game and compute Statcast.

    Pipeline:
      1. Load roster map (mlb_id -> player config from roster.json).
      2. For each player: collect all (game_pk, date) from game_logs where
         pitches_json is empty AND game_pk is not in playbyplay_processed.
      3. Group by game_pk (one fetch per unique game, parallelised).
      4. Extract pitches for every roster player in that game.
      5. Write pitches_json back to game_logs (per-player row), mark game_pk
         as processed.
      6. For each affected player-year, recompute Statcast aggregates and
         merge into season_stats.stat_json. Also fetch sabermetrics (MLB)
         and expectedStatistics (all levels).
    """
    db_file = Path(db_path)
    conn = sqlite3.connect(db_file)
    _init_db(conn)
    cur = conn.cursor()

    roster_map = _build_roster_map(roster_file)
    if only_player is not None:
        roster_map = {k: v for k, v in roster_map.items() if k == only_player}

    if not roster_map:
        print("Statcast: no matching players in roster")
        conn.close()
        return

    # Pull position for each roster player from the DB (fallback to empty)
    positions: dict[int, str] = {}
    for mlb_id in roster_map:
        cur.execute("SELECT position FROM players WHERE mlb_id = ?", (mlb_id,))
        row = cur.fetchone()
        positions[mlb_id] = (row[0] if row else "") or ""

    # ── Phase 0: backfill sport_level for historical game_logs ──
    # Historical rows written before sport_level tracking was added will have
    # sport_level=''. Find them (scoped to the current roster selection), fetch
    # the level from a lightweight live-feed call, and fill it in.  Once
    # filled, subsequent runs skip this entirely.
    placeholders = ",".join("?" * len(roster_map))
    cur.execute(
        f"SELECT DISTINCT game_id FROM game_logs "
        f"WHERE player_mlb_id IN ({placeholders}) AND sport_level = '' "
        f"AND pitches_json != '[]' AND pitches_json != 'null' AND pitches_json IS NOT NULL",
        list(roster_map.keys()),
    )
    backfill_game_ids = [row[0] for row in cur.fetchall() if row[0] is not None]

    if backfill_game_ids:
        print(
            f"Statcast: backfilling sport_level for {len(backfill_game_ids)} "
            f"historical game(s) ..."
        )
        backfill_levels: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_gpk = {
                executor.submit(get_game_sport_level, gpk): gpk
                for gpk in backfill_game_ids
            }
            for future in as_completed(future_to_gpk):
                gpk = future_to_gpk[future]
                try:
                    lvl = future.result()
                    backfill_levels[gpk] = lvl
                except Exception as e:
                    logger.warning(
                        "backfill sport_level failed for game_pk=%s: %s", gpk, e
                    )
        for gpk, lvl in backfill_levels.items():
            if lvl:
                cur.execute(
                    "UPDATE game_logs SET sport_level = ? "
                    "WHERE game_id = ? AND sport_level = ''",
                    (lvl, gpk),
                )
        conn.commit()
        filled = sum(1 for v in backfill_levels.values() if v)
        print(f"  backfilled sport_level for {filled}/{len(backfill_game_ids)} games")

    # ── Phase 1: build list of (game_pk, [players in game]) to fetch ──
    game_to_players: dict[int, list[tuple[int, str]]] = {}
    target_count = 0  # count of player-game rows needing pitch data

    for mlb_id in roster_map:
        cur.execute(
            "SELECT game_id, pitches_json, hit_coord_checked FROM game_logs "
            "WHERE player_mlb_id = ?",
            (mlb_id,),
        )
        for gpk, pitches_json, hit_coord_checked in cur.fetchall():
            if gpk is None:
                continue
            needs_fetch = pitches_json in (None, "[]")
            if not needs_fetch and not hit_coord_checked:
                needs_fetch = _pitches_need_hit_coord_backfill(
                    loads_json_list(pitches_json)
                )
            if not needs_fetch:
                continue
            target_count += 1
            game_to_players.setdefault(gpk, []).append((mlb_id, positions.get(mlb_id, "")))

    total_games = len(game_to_players)
    print(
        f"Statcast: {len(roster_map)} players, {total_games} unique games to fetch "
        f"({target_count} player-game rows to update)"
    )
    if total_games == 0:
        print("  no new games to fetch; recomputing statcast from existing pitch data ...")

    # ── Phase 2: parallel fetch + extract ──
    extracted: dict[tuple[int, int], list[dict]] = {}  # (player_id, game_pk) -> pitches
    game_sport_levels: dict[int, str] = {}  # game_pk -> sport_level
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_gpk = {
            executor.submit(_fetch_and_extract_game, gpk, players): gpk
            for gpk, players in game_to_players.items()
        }
        for i, future in enumerate(as_completed(future_to_gpk), 1):
            gpk = future_to_gpk[future]
            try:
                result, sport_level = future.result()
                game_sport_levels[gpk] = sport_level
                for mlb_id, pitches in result.items():
                    extracted[(mlb_id, gpk)] = pitches
                if i % 25 == 0 or i == total_games:
                    print(f"  [{i}/{total_games}] games fetched")
            except Exception as e:
                print(f"  game {gpk} failed: {e}")
                logger.exception("Statcast fetch failed for game_pk=%s", gpk)

    # ── Phase 3: write pitch logs back to DB ──
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    affected_years_by_player: dict[int, set[int]] = {}

    for (mlb_id, gpk), pitches in extracted.items():
        # Look up the game's date so we know which year is affected
        cur.execute(
            "SELECT date FROM game_logs WHERE player_mlb_id = ? AND game_id = ?",
            (mlb_id, gpk),
        )
        row = cur.fetchone()
        if not row:
            continue
        date_str = row[0] or ""
        yr = None
        if len(date_str) >= 4:
            try:
                yr = int(date_str[:4])
            except ValueError:
                pass

        lvl = game_sport_levels.get(gpk, "")
        # Empty pitch list means the player didn't appear at the plate in this
        # game (AB=0, PA=0: defensive sub, pinch runner, DNP).  Write JSON null
        # instead of '[]' so Phase 1's needs_fetch check won't mistake it for
        # "not yet fetched" and trigger an infinite re-fetch loop.
        stored_pitches = dumps_json(pitches) if pitches else "null"
        # Only overwrite sport_level when we got a valid one from the live
        # feed; otherwise preserve whatever the main sync already stored.
        if lvl:
            cur.execute(
                "UPDATE game_logs SET pitches_json = ?, sport_level = ?, hit_coord_checked = 1 "
                "WHERE player_mlb_id = ? AND game_id = ?",
                (stored_pitches, lvl, mlb_id, gpk),
            )
        else:
            cur.execute(
                "UPDATE game_logs SET pitches_json = ?, hit_coord_checked = 1 "
                "WHERE player_mlb_id = ? AND game_id = ?",
                (stored_pitches, mlb_id, gpk),
            )
        if yr is not None:
            affected_years_by_player.setdefault(mlb_id, set()).add(yr)

    # Mark games as processed
    for gpk in game_to_players:
        cur.execute(
            "INSERT OR REPLACE INTO playbyplay_processed (game_pk, processed_at) "
            "VALUES (?, ?)",
            (gpk, now),
        )
    conn.commit()
    print(f"  wrote pitch logs for {len(extracted)} player-games")

    # ── Phase 4: parallel compute + API fetch, then sequential DB write ──
    print(f"  aggregating statcast per player-year-level ({MAX_WORKERS} workers) ...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_mlb_id = {
            executor.submit(
                _compute_player_statcast_bundle,
                mlb_id,
                str(db_file),
                positions.get(mlb_id, ""),
            ): mlb_id
            for mlb_id in roster_map
        }
        for future in as_completed(future_to_mlb_id):
            mlb_id = future_to_mlb_id[future]
            name = roster_map[mlb_id].get("name_tw", str(mlb_id))
            try:
                _, results = future.result()
                if not results:
                    continue
                position = positions.get(mlb_id, "")
                for (yr, lvl), data in results.items():
                    _merge_statcast_into_season(
                        cur,
                        mlb_id=mlb_id,
                        year=yr,
                        position=position,
                        statcast_data=data["statcast"],
                        sport_level=lvl,
                        sabermetrics=data["sabermetrics"],
                        expected_stats=data["expected_stats"],
                    )
                conn.commit()
                print(f"    {name}: aggregated {len(results)} season-level(s)")
            except Exception as e:
                print(f"  error for {name}: {e}")
                logger.exception("Statcast aggregation failed for %s", name)

    conn.close()
    print("Statcast sync complete")
