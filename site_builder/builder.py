"""
Static site builder: reads SQLite data and renders Jinja2 templates to HTML.
"""

import datetime
import os
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests as _requests

from site_builder.helpers import (
    SPORT_LEVEL_ORDER,
    Obj,
    annotate_computed_stats,
    compute_career,
    compute_season_combined,
    has_appearance,
    height_to_cm,
    lbs_to_kg,
    loads_json_dict,
    loads_json_list,
    parse_date,
    safe_float,
)
from site_builder.jinja_env import create_jinja_env

_PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _prefetch_headshots(mlb_ids: list, cache_dir: Path, dest_dir: Path):
    """Download player headshots to a local cache and copy to the dist directory.

    Uses a persistent cache under ``data/headshots/`` so images are only
    re-downloaded when the cached file is missing.  All HTTP errors are
    silently ignored — the template falls back to the MLB CDN via JS.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    to_fetch = [mid for mid in mlb_ids if not (cache_dir / f"{mid}.jpg").exists()]

    def _fetch_one(mlb_id):
        url = (
            f"https://img.mlbstatic.com/mlb-photos/image/upload/"
            f"w_180,q_auto:best/v1/people/{mlb_id}/headshot/milb/current"
        )
        try:
            r = _requests.get(url, timeout=10)
            if r.status_code == 200 and r.content:
                (cache_dir / f"{mlb_id}.jpg").write_bytes(r.content)
        except Exception:
            pass

    if to_fetch:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_fetch_one, to_fetch))

    # Copy every cached headshot to dist regardless of whether it was just fetched
    for mlb_id in mlb_ids:
        src = cache_dir / f"{mlb_id}.jpg"
        if src.exists():
            shutil.copy2(src, dest_dir / f"{mlb_id}.jpg")


def _pick_display_stat(stats_current, player):
    """Pick the stat row to show on the player card / detail hero strip.

    Priority:
    1. Exact team match — handles players who've been at multiple teams at
       the same level (e.g. demoted back to a different AA club).
    2. Current level match — handles demotions where player.level has changed.
    3. Highest level with appearances — fallback / original behaviour for
       promotions where the player hasn't appeared at the new level yet.

    ``stats_current`` must already be filtered to the target year + has_appearance,
    and sorted by level_order ascending (highest level first).
    """
    if not stats_current:
        return None
    # 1. Exact current-team match
    for s in stats_current:
        if s.team_name == player.team:
            return s
    # 2. Current level match (takes the highest-level team at that level)
    for s in stats_current:
        if s.sport_level == player.level:
            return s
    # 3. Fallback: highest level played with appearances
    return stats_current[0]


def _load_player_bundle(cur, player_row: sqlite3.Row):
    """Load a complete player data bundle from SQLite."""
    player = Obj(dict(player_row))
    player.transactions_json = loads_json_list(player.transactions_json)
    player.next_game_json = loads_json_dict(player.next_game_json)
    player.is_pitcher = player.position == "P"
    player.birth_date = parse_date(player.birth_date)

    today = datetime.date.today()
    if player.birth_date:
        player.age = (
            today.year
            - player.birth_date.year
            - (
                (today.month, today.day)
                < (player.birth_date.month, player.birth_date.day)
            )
        )
    else:
        player.age = None

    # Season stats
    cur.execute(
        "SELECT year, team_name, league_name, sport_level, stat_json, "
        "       fielding_json, advanced_json "
        "FROM season_stats WHERE player_mlb_id = ? ORDER BY year DESC",
        (player.mlb_id,),
    )
    stats = []
    for row in cur.fetchall():
        data = Obj()
        data.year = row[0]
        data.team_name = row[1]
        data.league_name = row[2]
        data.sport_level = row[3]
        stat_json = loads_json_dict(row[4])
        data.update(stat_json)
        data.fielding_json = loads_json_list(row[5])
        data.advanced_json = loads_json_dict(row[6])
        data.level_order = SPORT_LEVEL_ORDER.get(data.sport_level, 50)
        slg = safe_float(data.get("slg"))
        avg = safe_float(data.get("avg"))
        data.iso = (slg - avg) if (slg is not None and avg is not None) else None
        stats.append(data)

    stats.sort(key=lambda s: (-s.year, s.level_order))
    player.latest_stat = stats[0] if stats else None
    player.available_years = sorted({s.year for s in stats}, reverse=True)

    # Game logs
    cur.execute(
        "SELECT date, game_id, opponent, is_home, stats_json "
        "FROM game_logs WHERE player_mlb_id = ? ORDER BY date DESC",
        (player.mlb_id,),
    )
    logs = []
    for row in cur.fetchall():
        log = Obj()
        log.date = parse_date(row[0])
        log.game_id = row[1]
        log.opponent = row[2]
        log.is_home = None if row[3] is None else bool(row[3])
        log.stats_json = loads_json_dict(row[4])
        logs.append(log)

    return player, stats, logs


def build_static_site(db_path: str, year: int, output_dir: str, base_url: str = "/"):
    """Build the complete static site from SQLite data."""
    out_dir = Path(output_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy static files from src/static
    static_src = _PROJECT_ROOT / "src" / "static"
    if static_src.is_dir():
        shutil.copytree(static_src, out_dir / "static")

    env = create_jinja_env(base_url=base_url)

    # Build timestamp in UTC+8
    now_utc8 = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    env.globals["build_time"] = now_utc8.strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Verify the database has been populated by a prior sync
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
    if not cur.fetchone():
        conn.close()
        raise SystemExit(
            f"Error: database '{db_path}' has no 'players' table. "
            "Run 'python build.py sync' first."
        )

    cur.execute("SELECT * FROM players ORDER BY name_en")
    rows = cur.fetchall()

    bundles = [_load_player_bundle(cur, row) for row in rows]

    # ── Prefetch / cache player headshots for local serving ──
    headshot_cache = _PROJECT_ROOT / "data" / "headshots"
    headshot_dest = out_dir / "img" / "players"
    _prefetch_headshots(
        [player.mlb_id for player, _, _ in bundles],
        headshot_cache,
        headshot_dest,
    )

    # ── Index page ──
    index_template = env.get_template("index.j2")
    player_data = []
    for player, stats, logs in bundles:
        stats_current = [s for s in stats if s.year == year and has_appearance(s)]
        stats_current.sort(key=lambda x: x.level_order)
        # Find the most recent game date for sorting
        last_game_date = None
        for log in logs:
            if log.date:
                last_game_date = log.date
                break  # logs are already sorted descending
        player_data.append(
            {
                "player": player,
                "stat": _pick_display_stat(stats_current, player),
                "last_game_date": last_game_date,
            }
        )
    player_data.sort(key=lambda x: SPORT_LEVEL_ORDER.get(x["player"].level, 50))

    index_html = index_template.render(
        player_data=player_data,
        current_sort="level",
        default_season_year=year,
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    # ── Player detail pages ──
    player_template = env.get_template("player_detail.j2")
    for player, all_stats, all_logs in bundles:
        selected_year = year
        game_logs = [g for g in all_logs if g.date and g.date.year == selected_year]
        game_logs.sort(key=lambda g: g.date, reverse=True)

        # Chart data
        chart_labels = []
        chart_data = []
        for log in sorted(game_logs, key=lambda x: x.date):
            chart_labels.append(log.date.strftime("%m/%d"))
            s = log.stats_json
            val = (
                safe_float(s.get("era", 0))
                if player.is_pitcher
                else safe_float(s.get("avg", 0))
            )
            chart_data.append(val)

        all_stats = annotate_computed_stats(all_stats)

        # Career aggregations
        milb_career = compute_career(all_stats, level_filter="milb")
        mlb_career = compute_career(all_stats, level_filter="mlb")
        total_career = compute_career(all_stats, level_filter=None)

        # Next game validity
        snapshot_valid = (
            isinstance(player.next_game_json, dict)
            and bool(player.next_game_json)
            and (
                player.next_game_for_season in (None, year)
                or (player.next_game_for_season or 0) >= datetime.date.today().year
            )
        )
        next_game = player.next_game_json if snapshot_valid else None

        next_game_updated_at = None
        if player.next_game_updated_at:
            try:
                dt = datetime.datetime.fromisoformat(player.next_game_updated_at)
                next_game_updated_at = dt.strftime("%Y-%m-%d %H:%M UTC")
            except ValueError:
                next_game_updated_at = player.next_game_updated_at

        # Current season stats
        stats_current = [s for s in all_stats if s.year == year and has_appearance(s)]
        stats_current.sort(key=lambda x: x.level_order)
        latest_team_stat = _pick_display_stat(stats_current, player)
        season_combined = (
            compute_season_combined(all_stats, year) if stats_current else None
        )

        # Fielding data
        all_fielding = []
        for s in all_stats:
            if s.fielding_json:
                for f in s.fielding_json:
                    entry = dict(f)
                    entry["year"] = s.year
                    entry["team_name"] = s.team_name
                    entry["sport_level"] = s.sport_level
                    all_fielding.append(entry)

        # FanGraphs data
        fg_stats = []
        for s in all_stats:
            if s.advanced_json and isinstance(s.advanced_json, dict):
                fg = s.advanced_json.get("fangraphs")
                if fg:
                    entry = dict(fg)
                    entry["year"] = s.year
                    entry["team_name"] = s.team_name
                    entry["sport_level"] = s.sport_level
                    fg_stats.append(entry)

        context = {
            "player": player,
            "all_stats": all_stats,
            "years": player.available_years,
            "selected_year": selected_year,
            "game_logs": game_logs,
            "chart_labels": chart_labels,
            "chart_data": chart_data,
            "is_pitcher": player.is_pitcher,
            "milb_career": milb_career,
            "mlb_career": mlb_career,
            "total_career": total_career,
            "next_game": next_game,
            "next_game_updated_at": next_game_updated_at,
            "transactions": player.transactions_json or [],
            "fielding_data": [],  # kept for template compatibility
            "all_fielding": all_fielding,
            "height_cm": height_to_cm(player.height),
            "weight_kg": lbs_to_kg(player.weight),
            "fg_stats": fg_stats,
            "latest_team_stat": latest_team_stat,
            "season_combined": season_combined,
            "default_season_year": year,
        }

        html = player_template.render(**context)
        player_dir = out_dir / "player" / str(player.mlb_id)
        player_dir.mkdir(parents=True, exist_ok=True)
        (player_dir / "index.html").write_text(html, encoding="utf-8")

    # ── 404 page ──
    template_404 = env.get_template("404.j2")
    (out_dir / "404.html").write_text(template_404.render(), encoding="utf-8")

    # ── GitHub Pages marker ──
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    conn.close()
    print(f"Built {len(bundles)} player pages + index to {out_dir}")
