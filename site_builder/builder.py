"""
Static site builder: reads SQLite data and renders Jinja2 templates to HTML.
"""

import datetime
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
    compute_year_groups,
    has_appearance,
    height_to_cm,
    dumps_json,
    lbs_to_kg,
    loads_json_dict,
    loads_json_list,
    parse_date,
    safe_float,
)
from site_builder.jinja_env import create_jinja_env
from site_builder.statcast import summarize_pitch_for_display

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _combine_pitch_type_data(
    entries: list[dict],
    sc_key: str,
    rate_fields: list[str],
    include_pct: bool = False,
) -> list[dict]:
    """Shared helper: combine per-level pitch-type data via count-weighted averages.

    Args:
        entries: list of {sport_level, team_name, sc} dicts.
        sc_key: key inside ``sc`` to read (``"vs_pitch_types"`` or ``"pitch_arsenal"``).
        rate_fields: field names to weight-average by pitch count.
        include_pct: if True, compute ``pct`` (type count / grand total) in output.

    Returns:
        Combined list sorted by pitch count descending.
        ``put_away_pct`` is always weighted by ``two_strike_count`` for accuracy.
    """
    total_count = 0
    by_type: dict[str, dict] = {}

    for e in entries:
        if e.get("sport_level") == "_combined":
            continue
        items = (e.get("sc") or {}).get(sc_key) or []
        for pt in items:
            t = pt.get("type", "UN")
            n = pt.get("count", 0)
            total_count += n
            if t not in by_type:
                by_type[t] = {
                    "name": pt.get("name", t),
                    "count": 0,
                    "two_strike_count": 0,
                    "wsums": {f: 0.0 for f in rate_fields},
                    "wcounts": {f: 0.0 for f in rate_fields},
                    "pa_wsum": 0.0,
                    "pa_wcount": 0.0,
                }
            bucket = by_type[t]
            bucket["count"] += n
            two_k_n = pt.get("two_strike_count", 0)
            bucket["two_strike_count"] += two_k_n
            pa_pct = pt.get("put_away_pct")
            if pa_pct is not None and two_k_n:
                bucket["pa_wsum"] += pa_pct * two_k_n
                bucket["pa_wcount"] += two_k_n
            for f in rate_fields:
                v = pt.get(f)
                if v is not None:
                    bucket["wsums"][f] += v * n
                    bucket["wcounts"][f] += n

    out = []
    for t, bucket in by_type.items():
        n = bucket["count"]
        row: dict = {"type": t, "name": bucket["name"], "count": n}
        if include_pct:
            row["pct"] = round(n / total_count, 4) if total_count else None
        for f in rate_fields:
            wc = bucket["wcounts"][f]
            row[f] = round(bucket["wsums"][f] / wc, 4) if wc else None
        pa_wc = bucket["pa_wcount"]
        row["put_away_pct"] = round(bucket["pa_wsum"] / pa_wc, 4) if pa_wc else None
        out.append(row)
    out.sort(key=lambda r: r.get("count", 0), reverse=True)
    return out


def _combine_vs_pitch_types(entries: list[dict]) -> list[dict]:
    """Combine per-level vs_pitch_types into a single count-weighted list."""
    return _combine_pitch_type_data(
        entries,
        sc_key="vs_pitch_types",
        rate_fields=[
            "strike_pct", "zone_pct", "z_swing_pct", "o_swing_pct",
            "whiff_pct", "swstr_pct", "csw_pct",
            "avg", "woba", "barrel_pct", "hard_hit_pct",
        ],
    )


def _combine_pitch_arsenal(entries: list[dict]) -> list[dict]:
    """Combine per-level pitch_arsenal into a single count-weighted list."""
    return _combine_pitch_type_data(
        entries,
        sc_key="pitch_arsenal",
        rate_fields=[
            "velo", "ivb", "hb", "spin", "extension", "v_rel", "h_rel",
            "zone_pct", "chase_pct", "whiff_pct", "woba",
        ],
        include_pct=True,
    )


def _combine_statcast_dicts(entries: list[dict]) -> dict:
    """Compute a weighted-average combined statcast dict from multiple level entries.

    Args:
        entries: list of {sport_level, team_name, sc} dicts (the per-level entries).

    Returns:
        A combined sc dict suitable for display in a summary row.
        pitch_arsenal and vs_pitch_types are computed as count-weighted averages.
    """
    scs = [e["sc"] for e in entries if e.get("sc")]
    if not scs:
        return {}
    if len(scs) == 1:
        return dict(scs[0])

    def _wsum(field, weight_field):
        """Weighted sum of (value * weight) and sum of weights."""
        total_w = 0.0
        total_wv = 0.0
        for sc in scs:
            v = sc.get(field)
            w = sc.get(weight_field) or 0
            if v is not None and w:
                total_w += w
                total_wv += v * w
        return total_wv, total_w

    def _wpct(field, weight_field, digits=3):
        wv, w = _wsum(field, weight_field)
        if not w:
            return None
        return round(wv / w, digits)

    total_p = sum((sc.get("total_pitches") or 0) for sc in scs)
    total_bbe = sum((sc.get("bbe") or 0) for sc in scs)
    total_pa = sum((sc.get("pa_count") or 0) for sc in scs)

    # Pitch-discipline fields — weight by total_pitches
    pitch_pct_fields = [
        "swing_pct", "swstr_pct", "csw_pct", "zone_pct", "strike_pct",
        "z_swing_pct", "o_swing_pct", "z_contact_pct", "whiff_pct",
        "avg_extension",
    ]
    # BBE-based fields — weight by bbe
    bbe_fields = [
        "barrel_pct", "hard_hit_pct", "avg_ev", "avg_la", "swsp_pct",
        "gb_pct", "ld_pct", "fb_pct", "pu_pct", "pull_pct",
        "straight_pct", "oppo_pct", "hr_fb_pct", "ev90",
    ]
    # PA-based fields — weight by pa_count
    pa_fields = ["woba", "woba_against"]

    combined: dict = {
        "total_pitches": total_p,
        "bbe": total_bbe,
        "pa_count": total_pa,
    }
    for f in pitch_pct_fields:
        combined[f] = _wpct(f, "total_pitches")
    for f in bbe_fields:
        combined[f] = _wpct(f, "bbe")
    for f in pa_fields:
        combined[f] = _wpct(f, "pa_count")

    # max_ev — take the maximum across levels
    max_evs = [sc.get("max_ev") for sc in scs if sc.get("max_ev") is not None]
    combined["max_ev"] = round(max(max_evs), 1) if max_evs else None

    # pitch_arsenal / vs_pitch_types: combine using count-weighted averages
    combined["pitch_arsenal"] = _combine_pitch_arsenal(entries)
    combined["vs_pitch_types"] = _combine_vs_pitch_types(entries)

    return combined


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
        "       fielding_json "
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
        data.level_order = SPORT_LEVEL_ORDER.get(data.sport_level, 50)
        slg = safe_float(data.get("slg"))
        avg = safe_float(data.get("avg"))
        data.iso = (slg - avg) if (slg is not None and avg is not None) else None
        stats.append(data)

    stats.sort(key=lambda s: (-s.year, s.level_order))
    player.latest_stat = stats[0] if stats else None
    player.available_years = sorted({s.year for s in stats}, reverse=True)

    # Game logs — pitches_json may not exist on older DBs (before Statcast support)
    has_pitches_col = False
    try:
        cur.execute("SELECT pitches_json FROM game_logs LIMIT 0")
        has_pitches_col = True
    except Exception:
        pass

    if has_pitches_col:
        log_sql = (
            "SELECT date, game_id, opponent, is_home, stats_json, pitches_json, sport_level "
            "FROM game_logs WHERE player_mlb_id = ? ORDER BY date DESC"
        )
    else:
        log_sql = (
            "SELECT date, game_id, opponent, is_home, stats_json, sport_level "
            "FROM game_logs WHERE player_mlb_id = ? ORDER BY date DESC"
        )

    cur.execute(log_sql, (player.mlb_id,))
    logs = []
    for row in cur.fetchall():
        log = Obj()
        log.date = parse_date(row[0])
        log.game_id = row[1]
        log.opponent = row[2]
        log.is_home = None if row[3] is None else bool(row[3])
        log.stats_json = loads_json_dict(row[4])
        if has_pitches_col:
            log.pitches_json = loads_json_list(row[5])
            log.sport_level = row[6] or ""
        else:
            log.pitches_json = []
            log.sport_level = row[5] or ""
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
    normalized_base_url = env.globals["base_url"]

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

        logs_by_year = {}
        for log in all_logs:
            if not log.date: continue
            y = log.date.year
            logs_by_year.setdefault(y, []).append(log)

        for y in logs_by_year:
            logs_by_year[y].sort(key=lambda g: g.date, reverse=True)

        available_log_years = sorted(logs_by_year.keys(), reverse=True)
        game_logs = logs_by_year.get(selected_year, [])

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
        stats_year_groups = compute_year_groups(all_stats)

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

        # ── Statcast context ──
        # Summarised pitch logs are written as external JSON and lazy-loaded by
        # the browser when a game row is expanded. This keeps player HTML small.
        pitchlog_dir = out_dir / "data" / "pitchlogs" / str(player.mlb_id)
        pitchlog_url_base = f"{normalized_base_url}data/pitchlogs/{player.mlb_id}"
        for y_key in logs_by_year:
            for log in logs_by_year[y_key]:
                if log.pitches_json:
                    pitch_display = [
                        summarize_pitch_for_display(p) for p in log.pitches_json
                    ]
                    if pitch_display:
                        pitchlog_dir.mkdir(parents=True, exist_ok=True)
                        pitchlog_filename = f"{log.game_id}.json"
                        (pitchlog_dir / pitchlog_filename).write_text(
                            dumps_json(pitch_display), encoding="utf-8"
                        )
                        log.pitch_data_url = f"{pitchlog_url_base}/{pitchlog_filename}"
                        log.pitch_count = len(pitch_display)
                    else:
                        log.pitch_data_url = ""
                        log.pitch_count = 0
                else:
                    log.pitch_data_url = ""
                    log.pitch_count = 0

        # Season-level Statcast data keyed by year → list of {sport_level, team_name, sc}
        statcast_by_year: dict[int, list] = {}
        for s in all_stats:
            sc = s.get("statcast")
            if sc:
                statcast_by_year.setdefault(s.year, []).append({
                    "sport_level": s.sport_level,
                    "team_name": s.team_name,
                    "sc": sc,
                    "stat": s,
                })
        # For years with multiple levels, prepend a combined summary entry so the
        # summary row in the template can display real weighted-average values.
        for yr_key, yr_entries in statcast_by_year.items():
            if len(yr_entries) > 1:
                combined_sc = _combine_statcast_dicts(yr_entries)
                yr_entries.insert(0, {
                    "sport_level": "_combined",
                    "team_name": "合計",
                    "sc": combined_sc,
                    "stat": None,
                })

        statcast_available = bool(statcast_by_year)

        # Determine available Statcast years (sorted desc)
        available_statcast_years = sorted(statcast_by_year.keys(), reverse=True)

        context = {
            "player": player,
            "all_stats": all_stats,
            "stats_year_groups": stats_year_groups,
            "years": player.available_years,
            "selected_year": selected_year,
            "game_logs": game_logs,
            "logs_by_year": logs_by_year,
            "available_log_years": available_log_years,
            "chart_labels": chart_labels,
            "chart_data": chart_data,
            "is_pitcher": player.is_pitcher,
            "milb_career": milb_career,
            "mlb_career": mlb_career,
            "total_career": total_career,
            "next_game": next_game,
            "next_game_updated_at": next_game_updated_at,
            "transactions": player.transactions_json or [],
            "all_fielding": all_fielding,
            "height_cm": height_to_cm(player.height),
            "weight_kg": lbs_to_kg(player.weight),
            "latest_team_stat": latest_team_stat,
            "season_combined": season_combined,
            "statcast_by_year": statcast_by_year,
            "statcast_available": statcast_available,
            "available_statcast_years": available_statcast_years,
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
