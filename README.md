# Taiwan MLB Tracker

Pure Python + Jinja2 static site generator that tracks Taiwanese baseball
players in the American professional baseball system (MLB/MiLB).

## Project Layout

```
├── src/
│   ├── templates/          # Jinja2 templates (.j2)
│   ├── static/css/         # Stylesheets
│   └── data/roster.json    # Tracked player roster
├── site_builder/           # Python package
│   ├── api.py              # MLB Stats API + FanGraphs client
│   ├── sync.py             # Data sync (parallel fetch)
│   ├── builder.py          # Static site renderer
│   ├── helpers.py          # Shared utilities & stat computation
│   └── jinja_env.py        # Jinja2 environment config
├── build.py                # CLI entry point
├── requirements.txt
└── .github/workflows/pages.yml
```

## Commands

```bash
# Sync latest data from MLB/FanGraphs APIs
python build.py sync

# Build static site to dist/
python build.py build

# Full pipeline (sync + build)
python build.py all

# Override defaults
python build.py sync --player 678906
python build.py build --base-url /twbexpats/ --output dist
```

## Quick Smoke Test

```bash
python build.py build --output dist-smoke --base-url /
test -f dist-smoke/index.html && test -f dist-smoke/404.html && echo "OK"
rm -rf dist-smoke
```
