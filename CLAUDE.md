# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Local development
```bash
# Install dependencies (Python 3.13, use venv)
pip install -r requirements.txt

# Build static site from existing database (no API calls)
python build.py build

# Serve the built site locally
python -m http.server 8000 --directory dist
open http://localhost:8000

# First-time / backfill (all historical years, takes minutes)
python build.py all

# Daily update (fast: current-year logs only + Statcast + build)
python build.py refresh
```

### Single-player operations
```bash
python build.py sync     --player 678906
python build.py statcast --player 678906
python build.py refresh  --player 678906
```

### Custom paths / season
```bash
python build.py build   --base-url /twbexpats/  # GitHub Pages sub-path
python build.py refresh --db data/tracker.sqlite3 --year 2026
```

### Environment variable
`DEFAULT_SEASON_YEAR` (default `2026`) controls which season is treated as current. Set it in the shell or the GitHub Actions env block.

## Architecture

This is a **pure Python + Jinja2 static site generator** — no framework, no build tool, no JavaScript bundler. The entire pipeline reads from a local SQLite database and writes HTML to `dist/`.

### Data flow

```
roster.json  →  sync.py  →  SQLite (tracker.sqlite3)
                              ↓
                          builder.py  →  dist/ (HTML + static files)
                              ↑
                          statcast.py (pitch-level aggregations stored in season_stats.stat_json)
```

1. **`sync.py`** — fetches from `statsapi.mlb.com/api/v1`. Two entry points: `sync_database` (full history) and `update_database` (current year only). Both fetch in parallel via `ThreadPoolExecutor(max_workers=8)`, then write to SQLite sequentially. `sync_statcast` fetches `game/{pk}/feed/live`, extracts pitch events, and writes them into `game_logs.pitches_json`.

2. **`api.py`** — thin MLB Stats API client. All endpoints are at `https://statsapi.mlb.com/api/v1`. Sport IDs map to level abbreviations via `_SPORT_ID_MAP`.

3. **`statcast.py`** — all Statcast math lives here: wOBA weights by year (hardcoded from FanGraphs guts table), pitch-type classification, FIP constants, xwPCT, pitch movement chart data, and per-game pitch extraction (`extract_pitch_logs`).

4. **`helpers.py`** — shared utilities. Key types:
   - `Obj(dict)` — attribute-access dict used throughout templates (`stat.era`, `player.team`).
   - `ip_to_outs` / `outs_to_ip` — baseball innings-pitched notation converter (critical: IP `7.2` means 7⅔ innings, not 7.2 real innings; always use these when computing ERA/WHIP).
   - `annotate_computed_stats` / `compute_year_groups` — derive advanced stats and group season rows by year for template rendering.
   - `SPORT_LEVEL_ORDER` — canonical sort order for levels (MLB=0, AAA=1, … ROK=6).

5. **`builder.py`** — renders all HTML. Entry point is `build_static_site`. Key decisions made here:
   - `_pick_display_stat` — chooses which row to show in the player card hero strip (priority: exact team match → current level match → highest level).
   - `_combine_statcast_dicts` — count-weighted average of per-level Statcast when a player appeared at multiple levels; produces the `_combined` summary row.
   - Pitch data for game log expansion is written as external JSON to `dist/data/pitchlogs/{mlb_id}/{game_id}.json` and lazy-loaded by the browser.
   - Headshots are cached in `data/headshots/` and copied to `dist/img/players/`.

6. **`jinja_env.py`** — Jinja2 environment setup. All templates use `player_url(mlb_id)`, `static_url(path)`, and `absolute_url(path)` globals. Custom filters: `floatformat`, `pct_fmt` (decimal → percentage), `tojson_safe`, `jsonld`, `num_dash`.

### SQLite schema

Four tables, all in `data/tracker.sqlite3`:
- `players` — profile, team, level, transactions, next-game snapshot.
- `season_stats` — one row per `(player_mlb_id, year, team_name)`. `stat_json` holds a flat dict of every stat field plus nested keys `statcast`, `saber`, `expected`. `fielding_json` is a list of per-position fielding rows.
- `game_logs` — one row per `(player_mlb_id, game_id)`. `pitches_json` is a list of pitch event dicts extracted from the live feed.
- `playbyplay_processed` — cache of fetched `game_pk`s to avoid re-fetching.

`stat_json` stores both API-provided values and locally-computed values (advanced stats computed in `helpers._compute_advanced_stats`). API values are never overwritten (the `if s.get("x") is None` pattern).

### Templates

`src/templates/` uses `.j2` extension. Layout:
- `base.j2` — HTML shell, head tags, common scripts.
- `index.j2` — player card grid.
- `player_detail.j2` — player detail shell with tab navigation.
- `tabs/tab_*.j2` — desktop tab content (stats, gamelogs, advanced, bio, fielding, plot).
- `mobile/m_player_detail.j2` + `mobile/sections/m_*.j2` — separate mobile layout.

### CI / GitHub Pages

`.github/workflows/pages.yml` runs `python build.py refresh` twice daily (11:17 AM and 2:17 PM UTC+8). The SQLite database is persisted between runs via Google Drive (OAuth credentials in GitHub Secrets: `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`, `GDRIVE_FILE_ID`).

### Roster management

To add a player: add `{"mlb_id": <int>, "name_tw": "<zh-name>"}` to `src/data/roster.json`, then run `python build.py sync --player <mlb_id>` to backfill, then `python build.py build`.

### Stat field conventions

- Pitcher counting fields are prefixed `p_` when they conflict with batter fields (e.g. `p_hits`, `p_hr`, `p_hbp`).
- Batter K/BB use `h_so` and `hit_bb`; pitcher K/BB use `so` and `bb`.
- `np` is an alias for `pitches` (number of pitches) set in `annotate_computed_stats` for template compatibility.
- Statcast percentages are stored as decimals (0.0–1.0) and formatted by the `pct_fmt` Jinja filter.
