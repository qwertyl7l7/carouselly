from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from carouselly_core import (
    CarousellyError,
    SearchConfig,
    build_search_url,
    filter_new_listings,
    load_seen_items,
    save_seen_items,
    scrape_carousell,
)


if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


load_dotenv()

APP_ROOT = Path(__file__).resolve().parent
SEEN_ITEMS_FILE = APP_ROOT / "seen_items.json"


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single Carouselly scan from the terminal.")
    parser.add_argument("--product-name", default=os.getenv("SEARCH_QUERY", "vario 150"))
    parser.add_argument("--min-price", type=int, default=env_int("MIN_PRICE", 2000))
    parser.add_argument("--max-price", type=int, default=env_int("MAX_PRICE", 4000))
    parser.add_argument("--max-results", type=int, default=env_int("MAX_RESULTS", 10))
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes"})
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = SearchConfig(
        product_name=args.product_name,
        min_price=args.min_price,
        max_price=args.max_price,
        max_results=args.max_results,
        headless=args.headless,
    )

    try:
        config.validate()
        seen_ids = load_seen_items(SEEN_ITEMS_FILE)
        listings = scrape_carousell(config)
        new_items = filter_new_listings(listings, seen_ids)

        if new_items:
            save_seen_items(SEEN_ITEMS_FILE, seen_ids)

        print(f"Scan URL: {build_search_url(config)}")
        if new_items:
            print(f"Found {len(new_items)} new listing(s):")
            for listing in new_items:
                print(f"- {listing.title} | {listing.price} | {listing.link}")
        else:
            print("No new listings found.")
        return 0
    except CarousellyError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
