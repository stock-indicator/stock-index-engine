from __future__ import annotations

import argparse

from common.logger import get_logger
from services.output import LATEST_JSON_PATH, LOG_CSV_PATH
from services.refresh import full_refresh, manual_refresh


logger = get_logger("runner")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run market indicator evaluation")
    parser.add_argument(
        "--mode",
        choices=["manual", "full"],
        default="manual",
        help="manual uses incremental refresh; full purges cached data before evaluating",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Number of days of history to regenerate when exporting series",
    )
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Skip regenerating per-indicator history outputs",
    )
    parser.add_argument(
        "--keep-resource-cache",
        action="store_true",
        help="When running in full mode, keep shared resource cache on disk",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info(
        "Running indicator refresh (mode=%s, lookback_days=%s, skip_history=%s)",
        args.mode,
        args.lookback_days,
        args.skip_history,
    )
    if args.mode == "full":
        run = full_refresh(
            lookback_days=args.lookback_days,
            regenerate_history=not args.skip_history,
            purge_resource_cache=not args.keep_resource_cache,
        )
    else:
        run = manual_refresh(
            lookback_days=args.lookback_days,
            regenerate_history=not args.skip_history,
        )

    logger.info("Latest run persisted to %s", LATEST_JSON_PATH)
    logger.info("History log updated at %s", LOG_CSV_PATH)

    print(f"Mode: {run.mode}")
    print(f"Generated at: {run.generated_at.isoformat(timespec='seconds')}")
    print(
        "Triggered indicators (available only): "
        f"{run.summary.get('ratio_available')}"
    )
    print(
        "Triggered indicators (all tracked): "
        f"{run.summary.get('ratio_total')}"
    )
    print(f"Summary saved to {LATEST_JSON_PATH}")
    print(f"History log saved to {LOG_CSV_PATH}")


if __name__ == "__main__":
    main()
