from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Iterable
from urllib.parse import quote_plus
import json
import re


DEFAULT_BASE_URL = "https://www.carousell.com.my"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
const originalQuery = navigator.permissions.query;
navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
"""


def ensure_windows_event_loop_policy() -> None:
    if hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


class CarousellyError(Exception):
    """Base error for application-level failures."""


class ValidationError(CarousellyError):
    """Raised when a search configuration is invalid."""


class StorageError(CarousellyError):
    """Raised when local storage cannot be read or written."""


class ScrapeError(CarousellyError):
    """Raised when Carousell cannot be scraped successfully."""


@dataclass(frozen=True)
class SearchConfig:
    product_name: str
    min_price: int
    max_price: int
    max_results: int = 10
    headless: bool = False
    check_interval: int = 300
    proxy_server: str | None = None

    def validate(self) -> None:
        if not self.product_name.strip():
            raise ValidationError("Product name cannot be empty.")
        if self.min_price < 0:
            raise ValidationError("Minimum price cannot be negative.")
        if self.max_price < 0:
            raise ValidationError("Maximum price cannot be negative.")
        if self.min_price > self.max_price:
            raise ValidationError("Minimum price must be less than or equal to maximum price.")
        if self.max_results < 1:
            raise ValidationError("Max results must be at least 1.")
        if self.check_interval < 1:
            raise ValidationError("Check interval must be at least 1 second.")


@dataclass(frozen=True)
class Listing:
    item_id: str
    title: str
    price: str
    link: str
    found_at: str
    raw_text: str = ""


def build_search_url(config: SearchConfig, base_url: str = DEFAULT_BASE_URL) -> str:
    config.validate()
    encoded_query = quote_plus(config.product_name.strip())
    return (
        f"{base_url}/search/{encoded_query}"
        f"?sort_by=3&price_start={config.min_price}&price_end={config.max_price}"
    )


PRICE_LINE_PATTERN = re.compile(
    r"(?i)(?:^|\b)(?:rm|myr|s\$|us\$|\$|₱|฿|€|£|¥)\s*\d|\d+\s*(?:rm|myr|s\$|us\$|\$|₱|฿|€|£|¥)|free\b"
)
DATE_LINE_PATTERN = re.compile(r"(?i)\b(?:ago|day|days|hour|hours|hr|hrs|min|mins|minute|minutes|view|views|sold)\b")


def looks_like_price_line(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if DATE_LINE_PATTERN.search(normalized):
        return False
    return bool(PRICE_LINE_PATTERN.search(normalized))


def load_seen_items(path: str | Path) -> set[str]:
    file_path = Path(path)
    if not file_path.exists():
        return set()

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"Seen items file is corrupted: {file_path}") from exc
    except OSError as exc:
        raise StorageError(f"Could not read seen items file: {file_path}") from exc

    if not isinstance(payload, list):
        raise StorageError("Seen items file must contain a JSON array.")

    return {str(item) for item in payload if str(item).strip()}


def save_seen_items(path: str | Path, seen_ids: Iterable[str]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_path.write_text(json.dumps(sorted({str(item) for item in seen_ids})), encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not write seen items file: {file_path}") from exc


def filter_new_listings(listings: Iterable[Listing], seen_ids: set[str]) -> list[Listing]:
    new_items = [listing for listing in listings if listing.item_id not in seen_ids]
    for listing in new_items:
        seen_ids.add(listing.item_id)
    return new_items


def parse_listing_card(raw_text: str, item_id: str, base_url: str = DEFAULT_BASE_URL) -> Listing:
    cleaned_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not item_id.strip():
        raise ScrapeError("Listing card is missing an item id.")
    if not cleaned_lines:
        raise ScrapeError(f"Listing card {item_id} has no readable text.")

    title = cleaned_lines[0]
    price = next((line for line in cleaned_lines[1:] if looks_like_price_line(line)), "Price hidden")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return Listing(
        item_id=item_id.strip(),
        title=title,
        price=price,
        link=f"{base_url}/p/{item_id.strip()}",
        found_at=now,
        raw_text=raw_text.strip(),
    )


def apply_human_like_behavior(page: object) -> None:
    page.wait_for_timeout(random.randint(600, 1300))
    page.mouse.move(random.randint(60, 320), random.randint(40, 180), steps=random.randint(8, 18))
    page.mouse.wheel(0, random.randint(280, 620))
    page.wait_for_timeout(random.randint(500, 1100))
    page.mouse.wheel(0, -random.randint(120, 300))


def scrape_carousell(config: SearchConfig, base_url: str = DEFAULT_BASE_URL) -> list[Listing]:
    config.validate()
    ensure_windows_event_loop_policy()

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised in runtime, not tests
        raise ScrapeError(
            "Playwright is not installed. Run 'pip install -r requirements.txt' first."
        ) from exc

    search_url = build_search_url(config, base_url=base_url)
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    selector_candidates = [
        'div[data-testid^="listing-card-"]',
        'a[data-testid^="listing-card-"]',
        '[data-testid*="listing-card"]',
    ]
    last_error: Exception | None = None

    try:
        with sync_playwright() as playwright:
            for attempt in range(2):
                browser = None
                context = None
                try:
                    launch_kwargs: dict[str, object] = {
                        "headless": config.headless,
                        "args": launch_args,
                        "ignore_default_args": ["--enable-automation"],
                    }
                    if config.proxy_server:
                        launch_kwargs["proxy"] = {"server": config.proxy_server}

                    try:
                        browser = playwright.chromium.launch(
                            **launch_kwargs,
                        )
                    except Exception as exc:
                        if "Executable doesn't exist" in str(exc):
                            ensure_playwright_chromium_installed()
                            browser = playwright.chromium.launch(
                                **launch_kwargs,
                            )
                        else:
                            raise

                    context = browser.new_context(
                        user_agent=random.choice(USER_AGENT_POOL) if config.headless else DEFAULT_USER_AGENT,
                        viewport={"width": random.choice([1280, 1366, 1440]), "height": random.choice([720, 768, 900])},
                        locale="en-US",
                        timezone_id="Asia/Kuala_Lumpur",
                    )
                    context.set_extra_http_headers(
                        {
                            "Accept-Language": "en-US,en;q=0.9",
                            "Upgrade-Insecure-Requests": "1",
                            "DNT": "1",
                        }
                    )

                    page = context.new_page()
                    page.add_init_script(STEALTH_INIT_SCRIPT)
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                    apply_human_like_behavior(page)

                    active_selector = None
                    for selector in selector_candidates:
                        try:
                            page.wait_for_selector(selector, timeout=12000)
                            active_selector = selector
                            break
                        except PlaywrightTimeoutError:
                            continue

                    if not active_selector:
                        page_text = page.content().lower()
                        if "verify you are human" in page_text or "captcha" in page_text or "cloudflare" in page_text:
                            raise ScrapeError(
                                "Bot protection challenge detected while loading Carousell. "
                                "Try a residential proxy via PROXY_SERVER or a remote browser endpoint."
                            )
                        raise PlaywrightTimeoutError("No listing card selector matched.")

                    cards = page.locator(active_selector)
                    total_cards = min(cards.count(), config.max_results)
                    listings: list[Listing] = []

                    for index in range(total_cards):
                        card = cards.nth(index)
                        item_id = (card.get_attribute("data-testid") or "").replace("listing-card-", "", 1)
                        raw_text = card.inner_text()
                        try:
                            listings.append(parse_listing_card(raw_text, item_id, base_url=base_url))
                        except ScrapeError:
                            continue

                    if listings:
                        return listings
                    last_error = ScrapeError("No parseable listings were found in matched listing cards.")
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                except ScrapeError as exc:
                    last_error = exc
                finally:
                    if context:
                        context.close()
                    if browser:
                        browser.close()

                if attempt == 0:
                    continue

            if isinstance(last_error, ScrapeError):
                raise last_error
            raise ScrapeError("Timed out waiting for Carousell listings. The site may be blocking automation.")
    except ScrapeError:
        raise
    except NotImplementedError as exc:
        raise ScrapeError(
            "Your current Python event loop cannot launch Playwright subprocesses on Windows. "
            "Run the app from a normal Windows PowerShell session and avoid embedded or constrained shells."
        ) from exc
    except Exception as exc:
        raise ScrapeError(f"Unexpected scraping failure: {exc}") from exc


def ensure_playwright_chromium_installed() -> None:
    install_cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache" / "ms-playwright"))

    result = subprocess.run(install_cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        error_output = "\n".join(part for part in [result.stdout, result.stderr] if part.strip())
        raise ScrapeError(
            "Playwright Chromium install failed during runtime. "
            "On Streamlit Cloud, verify Linux libs in packages.txt and try redeploy. "
            f"Installer output: {error_output[-1200:]}"
        )


def build_results_markdown(config: SearchConfig, listings: Iterable[Listing], source_url: str) -> str:
    rows = list(listings)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Carouselly Results",
        "",
        f"Generated at: {generated_at}",
        f"Search: {config.product_name} | RM {config.min_price:,} to RM {config.max_price:,}",
        f"Source: {source_url}",
        "",
    ]

    if not rows:
        lines.extend([
            "## Latest Scan",
            "",
            "No new listings were found in the latest scan.",
            "",
        ])
        return "\n".join(lines)

    lines.extend([
        f"## New Listings ({len(rows)})",
        "",
        "| Title | Price | Link | Found At |",
        "| --- | --- | --- | --- |",
    ])

    for listing in rows:
        safe_title = listing.title.replace("|", "\\|")
        safe_price = listing.price.replace("|", "\\|")
        safe_link = listing.link.replace("|", "%7C")
        lines.append(f"| {safe_title} | {safe_price} | {safe_link} | {listing.found_at} |")

    lines.append("")
    return "\n".join(lines)


def write_results_markdown(path: str | Path, config: SearchConfig, listings: Iterable[Listing], source_url: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_path.write_text(build_results_markdown(config, listings, source_url), encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not write results file: {file_path}") from exc
