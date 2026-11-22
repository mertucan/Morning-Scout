"""Command-line entry point: ``python -m morning_scout [options]``."""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from morning_scout.app import RunOptions, run
from morning_scout.privacy import configure_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="morning-scout",
        description="Research your topics and send only what's new as a short morning digest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the digest to the terminal; send nothing and do not save state (local only)",
    )
    parser.add_argument(
        "--now", action="store_true", help="send immediately instead of waiting for send_time"
    )
    parser.add_argument(
        "--force", action="store_true", help="run even if today's digest was already sent"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="read/write config.yaml and state.json in ./data (or $DATA_DIR) instead of the Gist",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="detailed, unredacted logs for local debugging (refused on GitHub Actions)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if os.environ.get("GITHUB_ACTIONS") == "true" and (args.verbose or args.dry_run):
        # Both flags print personal data; CI logs must stay clean.
        print("--verbose and --dry-run are disabled on GitHub Actions.", file=sys.stderr)
        return 2

    load_dotenv()
    configure_logging(verbose=args.verbose)
    options = RunOptions(
        dry_run=args.dry_run,
        now=args.now,
        force=args.force,
        local=args.local,
        verbose=args.verbose,
    )
    return run(options)


if __name__ == "__main__":
    sys.exit(main())
