"""Command line entry point."""
import argparse
import logging
import sys
from pathlib import Path

from . import build, collect, extract, hardware, lifecycle, report


def main() -> None:
    parser = argparse.ArgumentParser(prog="palobugs")
    parser.add_argument("--pages", type=Path, default=Path("sources/pages.json"))
    parser.add_argument("--lifecycle", type=Path, default=Path("sources/lifecycle.json"))
    parser.add_argument("--hardware", type=Path, default=Path("sources/hardware.json"))
    parser.add_argument("--schedule", type=Path, default=Path("sources/schedule.yml"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/html"))
    parser.add_argument("--output", type=Path, default=Path("data/extracted"))
    parser.add_argument("--changes", type=Path, default=Path("data/changes.json"))
    parser.add_argument("--report", type=Path, default=Path("data/report.json"))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--base-url", default="https://frc-fr.github.io/palo-bug-tracker/")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="update the page list and fetch the new or changed pages")
    commands.add_parser("extract", help="parse the cached pages and write the processing report; fails only when too few pages are read")
    commands.add_parser("build", help="generate the static site from the extracted data")
    commands.add_parser("check", help="fail when the processing report lists something to fix")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "collect":
        client = collect.Client()
        with report.source(args.report, "sitemap", collect.SITEMAP_URL):
            pages = collect.update_pages(args.pages, client)
        with report.source(args.report, "pages"):
            fetched = collect.fetch_pages(pages, args.cache, client, extract.today(),
                                          save=lambda: collect.save_pages(args.pages, pages))
            collect.save_pages(args.pages, pages)
        with report.source(args.report, "lifecycle", lifecycle.PAGE_URL):
            lifecycle.update_lifecycle(args.lifecycle, client)
        with report.source(args.report, "hardware", hardware.PAGE_URL):
            hardware.update_hardware(args.hardware, client)
        logging.info("%d pages, %d fetched", len(pages), len(fetched))
    elif args.command == "extract":
        stops = extract.extract_all(args.cache, args.output, args.changes, args.pages, args.report)
        for reason in stops:
            logging.error("%s", reason)
        sys.exit(1 if stops else 0)
    elif args.command == "check":
        left = report.check(report.load(args.report))
        for line in left:
            print(line)
        sys.exit(1 if left else 0)
    elif args.command == "build":
        summary = build.build_site(args.output, args.pages, args.changes, args.lifecycle, args.schedule,
                                   args.site, args.dist, args.base_url, args.hardware, args.report)
        logging.info("%s", summary)
