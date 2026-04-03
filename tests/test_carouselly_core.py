from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carouselly_core import (
    Listing,
    SearchConfig,
    build_results_markdown,
    build_search_url,
    filter_new_listings,
    load_seen_items,
    looks_like_price_line,
    parse_listing_card,
    save_seen_items,
)


def test_build_search_url_encodes_product_name() -> None:
    config = SearchConfig(product_name="iPhone 15", min_price=2000, max_price=4000)

    url = build_search_url(config)

    assert url == "https://www.carousell.com.my/search/iPhone+15?sort_by=3&price_start=2000&price_end=4000"


def test_parse_listing_card_handles_missing_price() -> None:
    listing = parse_listing_card("Refurbished monitor", "abc123")

    assert listing.item_id == "abc123"
    assert listing.title == "Refurbished monitor"
    assert listing.price == "Price hidden"
    assert listing.link.endswith("/p/abc123")


def test_parse_listing_card_ignores_date_lines() -> None:
    listing = parse_listing_card("imotorbike\n9 days ago\nRM 850", "abc123")

    assert listing.title == "imotorbike"
    assert listing.price == "RM 850"


def test_looks_like_price_line_filters_date_text() -> None:
    assert looks_like_price_line("RM 1,250")
    assert looks_like_price_line("Free")
    assert not looks_like_price_line("9 days ago")
    assert not looks_like_price_line("123 views")


def test_filter_new_listings_updates_seen_ids() -> None:
    seen_ids = {"existing"}
    listings = [
        Listing("existing", "Old item", "RM 10", "https://example.com/1", "2026-04-04 12:00:00"),
        Listing("fresh", "New item", "RM 20", "https://example.com/2", "2026-04-04 12:01:00"),
    ]

    fresh_items = filter_new_listings(listings, seen_ids)

    assert [item.item_id for item in fresh_items] == ["fresh"]
    assert seen_ids == {"existing", "fresh"}


def test_seen_items_round_trip(tmp_path: Path) -> None:
    file_path = tmp_path / "seen_items.json"

    save_seen_items(file_path, {"b", "a"})

    assert load_seen_items(file_path) == {"a", "b"}


def test_results_markdown_includes_listings() -> None:
    config = SearchConfig(product_name="MacBook", min_price=3000, max_price=5000)
    markdown = build_results_markdown(
        config,
        [Listing("1", "MacBook Air", "RM 3200", "https://example.com/1", "2026-04-04 12:30:00")],
        "https://www.carousell.com.my/search/MacBook",
    )

    assert "# Carouselly Results" in markdown
    assert "MacBook Air" in markdown
    assert "RM 3,000 to RM 5,000" in markdown
