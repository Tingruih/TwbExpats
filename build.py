#!/usr/bin/env python3
"""
Taiwan MLB Tracker — build pipeline.

Usage:
    python build.py sync                # full sync: fetch ALL years of data for ALL players
    python build.py statcast            # fetch playByPlay + compute Statcast aggregates
    python build.py refresh             # update stats & Statcast, then build site
    python build.py build               # generate static site from existing database
    python build.py all                 # full sync + statcast + build (first-time / backfill)

Commands:
    sync     Fetches yearByYear stats AND game logs for every historical season.
             Use this the first time or to backfill complete game log history.
    statcast Fetches playByPlay for every un-processed game, extracts pitch-level
             data, and computes Statcast aggregates (FIP, Whiff%, arsenal, etc.).
             Run after sync; uses a cache table to avoid re-fetching games.
    refresh  Three-step daily update pipeline:
               1. update_database  — yearByYear stats (all seasons) + current-year
                                     game logs only (fast path).
               2. sync_statcast    — fetch playByPlay for any new unprocessed games
                                     and recompute Statcast / FIP / expected stats.
               3. build_static_site — render HTML to the dist/ directory.
             Use this for daily/CI updates — requires an existing database.
    build    Reads the SQLite database and renders HTML to the dist/ directory.
    all      Runs full sync → statcast → build in one step.

Options:
    python build.py sync     --player 678906   # single player only
    python build.py statcast --player 678906   # single player only
    python build.py refresh  --player 678906   # single player only
    python build.py build    --base-url /twbexpats/
"""

import argparse
import sys

from site_builder.helpers import DEFAULT_SEASON_YEAR


def cmd_sync(args):
    from site_builder.sync import sync_database

    sync_database(
        db_path=args.db,
        roster_file=args.roster,
        year=args.year,
        only_player=args.player,
    )


def cmd_build(args):
    from site_builder.builder import build_static_site

    build_static_site(
        db_path=args.db,
        year=args.year,
        output_dir=args.output,
        base_url=args.base_url,
        roster_file=args.roster,
    )


def cmd_statcast(args):
    """Fetch playByPlay for all un-processed games and compute Statcast aggregates."""
    from site_builder.sync import sync_statcast

    sync_statcast(
        db_path=args.db,
        roster_file=args.roster,
        year=args.year,
        only_player=args.player,
    )


def cmd_refresh(args):
    """Three-step daily update: basic stats → Statcast → build."""
    from site_builder.sync import update_database, sync_statcast
    from site_builder.builder import build_static_site

    update_database(
        db_path=args.db,
        roster_file=args.roster,
        year=args.year,
        only_player=args.player,
    )
    sync_statcast(
        db_path=args.db,
        roster_file=args.roster,
        year=args.year,
        only_player=args.player,
    )
    build_static_site(
        db_path=args.db,
        year=args.year,
        output_dir=args.output,
        base_url=args.base_url,
        roster_file=args.roster,
    )


def cmd_all(args):
    if args.player is not None:
        print(
            f"Warning: 'all --player {args.player}' only syncs one player.\n"
            "  sync and statcast will be restricted to that player, but build\n"
            "  renders all roster players. On a fresh database this means all\n"
            "  other player pages will be empty.\n"
            "  For a full first-time setup run: python build.py all (no --player).\n"
            "  For a single-player backfill run: python build.py sync --player <id>\n"
            "    then: python build.py statcast --player <id>\n"
            "    then: python build.py build"
        )
    cmd_sync(args)
    cmd_statcast(args)
    cmd_build(args)


def main():
    parser = argparse.ArgumentParser(
        description="Taiwan MLB Tracker — sync data & build static site",
    )
    sub = parser.add_subparsers(dest="command")

    # Shared defaults
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default="data/tracker.sqlite3", help="SQLite path")
    common.add_argument(
        "--year", type=int, default=DEFAULT_SEASON_YEAR, help="Season year"
    )

    # sync — full historical sync (all years, all game logs)
    sp_sync = sub.add_parser(
        "sync",
        parents=[common],
        help="Full sync: fetch ALL years of stats + game logs for every player",
    )
    sp_sync.add_argument(
        "--roster", default="src/data/roster.json", help="Roster JSON path"
    )
    sp_sync.add_argument(
        "--player", type=int, default=None, help="Sync single MLB ID only"
    )
    sp_sync.set_defaults(func=cmd_sync)

    # statcast — fetch playByPlay and compute Statcast aggregates
    sp_statcast = sub.add_parser(
        "statcast",
        parents=[common],
        help="Fetch playByPlay for un-processed games and compute Statcast aggregates",
    )
    sp_statcast.add_argument(
        "--roster", default="src/data/roster.json", help="Roster JSON path"
    )
    sp_statcast.add_argument(
        "--player", type=int, default=None, help="Single MLB ID only"
    )
    sp_statcast.set_defaults(func=cmd_statcast)

    # refresh — fast update + statcast + build (the standard daily/CI command)
    sp_refresh = sub.add_parser(
        "refresh",
        parents=[common],
        help="Update stats + Statcast, then build the static site (daily pipeline)",
    )
    sp_refresh.add_argument(
        "--roster", default="src/data/roster.json", help="Roster JSON path"
    )
    sp_refresh.add_argument(
        "--player", type=int, default=None, help="Refresh single MLB ID only"
    )
    sp_refresh.add_argument("--output", default="dist", help="Output directory")
    sp_refresh.add_argument(
        "--base-url", default="/", help="Site base URL (e.g. /repo/)"
    )
    sp_refresh.set_defaults(func=cmd_refresh)

    # build — render HTML from existing database
    sp_build = sub.add_parser(
        "build",
        parents=[common],
        help="Generate static HTML site from existing database",
    )
    sp_build.add_argument(
        "--roster", default="src/data/roster.json", help="Roster JSON path"
    )
    sp_build.add_argument("--output", default="dist", help="Output directory")
    sp_build.add_argument("--base-url", default="/", help="Site base URL (e.g. /repo/)")
    sp_build.set_defaults(func=cmd_build)

    # all — full sync then build
    sp_all = sub.add_parser(
        "all",
        parents=[common],
        help="Full sync then build (first-time / backfill pipeline)",
    )
    sp_all.add_argument(
        "--roster", default="src/data/roster.json", help="Roster JSON path"
    )
    sp_all.add_argument(
        "--player", type=int, default=None, help="Sync single MLB ID only"
    )
    sp_all.add_argument("--output", default="dist", help="Output directory")
    sp_all.add_argument("--base-url", default="/", help="Site base URL")
    sp_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
