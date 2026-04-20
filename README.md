# Taiwan MLB Tracker

Pure Python + Jinja2 static site generator that tracks Taiwanese baseball
players in the American professional baseball system (MLB/MiLB).

## Live Website

https://tingruih.github.io/twbexpats/

## Project Layout

```
├── src/
│   ├── templates/          # Jinja2 templates (.j2)
│   ├── static/css/         # Stylesheets
│   └── data/roster.json    # Tracked player roster
├── site_builder/           # Python package
│   ├── api.py              # MLB Stats API client
│   ├── sync.py             # Data sync (parallel fetch + Statcast pipeline)
│   ├── statcast.py         # Pitch-level analytics (Statcast / FIP / wOBA)
│   ├── builder.py          # Static site renderer
│   ├── helpers.py          # Shared utilities & stat computation
│   └── jinja_env.py        # Jinja2 environment config
├── build.py                # CLI entry point
├── requirements.txt
└── .github/workflows/pages.yml
```

## Commands

### Daily update (standard)

```bash
# Update stats + Statcast data, then build the site
python build.py refresh
```

`refresh` runs three steps in sequence:
1. **update_database** — fetches yearByYear stats (all seasons) and game logs for
   the current year only (fast path).
2. **sync_statcast** — fetches playByPlay for any new unprocessed games, extracts
   pitch-level data, and recomputes Statcast / FIP / expected stats.
3. **build_static_site** — renders HTML to `dist/`.

### First-time setup / full backfill

```bash
# 1. Full historical sync (all years, all game logs)
python build.py sync

# 2. Fetch playByPlay + compute Statcast for every game
python build.py statcast

# 3. Build the static site
python build.py build

# Or run all three in one command
python build.py all

# 4. Start a local static server (default: http://localhost:8000)
python -m http.server 8000 --directory dist

# 5. Open site in browser
open http://localhost:8000
```

### Individual commands

| Command | What it does |
|---------|-------------|
| `python build.py sync` | Fetches yearByYear stats **and** game logs for every historical season. Use this the first time or to backfill. |
| `python build.py statcast` | Fetches playByPlay for every un-processed game, extracts pitch data, and computes Statcast aggregates. Uses a cache table to avoid re-fetching. |
| `python build.py refresh` | Three-step daily pipeline: `update_database` → `sync_statcast` → `build_static_site`. |
| `python build.py build` | Renders the static site from the existing database without touching the data. |
| `python build.py all` | Runs `sync` → `statcast` → `build` in sequence. |

### Options

```bash
# Target a single player (all commands that fetch data)
python build.py sync     --player 678906
python build.py statcast --player 678906
python build.py refresh  --player 678906

# Custom output directory and base URL
python build.py build  --output dist --base-url /twbexpats/
python build.py refresh --output dist --base-url /twbexpats/

# Custom database path or season year
python build.py refresh --db data/tracker.sqlite3 --year 2025
```

