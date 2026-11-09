"""Command line entry point."""
import argparse
import logging
import sys
from pathlib import Path

from . import build, collect, extract, lifecycle


def main() -> None:
    parser = argparse.ArgumentParser(prog="palobugs")
    parser.add_argument("--pages", type=Path, default=Path("sources/pages.json"))
    parser.add_argument("--lifecycle", type=Path, default=Path("sources/lifecycle.json"))
    parser.add_argument("--schedule", type=Path, default=Path("sources/schedule.yml"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/html"))
    parser.add_argument("--output", type=Path, default=Path("data/extracted"))
    parser.add_argument("--changes", type=Path, default=Path("data/changes.json"))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--base-url", default="https://frc-fr.github.io/palo-bug-tracker/")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="update the page list and fetch the new or changed pages")
    commands.add_parser("extract", help="parse the cached pages; fails on any warning")
    commands.add_parser("build", help="generate the static site from the extracted data")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "collect":
        client = collect.Client()
        pages = collect.update_pages(args.pages, client)
        fetched = collect.fetch_pages(pages, args.cache, client, extract.today(),
                                      save=lambda: collect.save_pages(args.pages, pages))
        collect.save_pages(args.pages, pages)
        lifecycle.update_lifecycle(args.lifecycle, client)
        logging.info("%d pages, %d fetched", len(pages), len(fetched))
    elif args.command == "extract":
        problems = extract.extract_all(args.cache, args.output, args.changes, args.pages)
        for key, warnings in problems.items():
            for warning in warnings:
                logging.error("%s: %s", key, warning)
        sys.exit(1 if problems else 0)
    elif args.command == "build":
        summary = build.build_site(args.output, args.pages, args.changes, args.lifecycle, args.schedule,
                                   args.site, args.dist, args.base_url)
        logging.info("%s", summary)
