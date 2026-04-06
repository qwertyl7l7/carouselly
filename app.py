from __future__ import annotations

import os
import time
from pathlib import Path
import asyncio

import streamlit as st
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


def default_headless() -> bool:
    value = os.getenv("HEADLESS")
    if value is not None:
        return value.lower() in {"1", "true", "yes"}
    return os.name != "nt"


def default_config() -> SearchConfig:
    return SearchConfig(
        product_name=os.getenv("SEARCH_QUERY", "vario 150"),
        min_price=env_int("MIN_PRICE", 2000),
        max_price=env_int("MAX_PRICE", 4000),
        max_results=env_int("MAX_RESULTS", 10),
        headless=default_headless(),
        check_interval=env_int("CHECK_INTERVAL", 300),
        proxy_server=os.getenv("PROXY_SERVER") or None,
    )


def ensure_session_state() -> None:
    defaults = {
        "running": False,
        "logs": [],
        "found_items": [],
        "seen_ids": load_seen_items(SEEN_ITEMS_FILE),
        "current_config": default_config(),
        "last_check": 0.0,
        "last_error": "",
        "search_signature": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def add_log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")
    st.session_state.logs = st.session_state.logs[-60:]


def config_signature(config: SearchConfig) -> tuple:
    return (config.product_name, config.min_price, config.max_price, config.max_results, config.headless)


def reset_results(config: SearchConfig) -> None:
    st.session_state.found_items = []
    st.session_state.seen_ids = set()
    st.session_state.last_check = 0.0
    st.session_state.last_error = ""
    st.session_state.latest_scan = []
    st.session_state.latest_scan_summary = ""
    save_seen_items(SEEN_ITEMS_FILE, set())


def run_scan(config: SearchConfig) -> None:
    try:
        listings = scrape_carousell(config)
        new_items = filter_new_listings(listings, st.session_state.seen_ids)
        st.session_state.latest_scan = new_items

        if new_items:
            st.session_state.found_items.extend(new_items)
            save_seen_items(SEEN_ITEMS_FILE, st.session_state.seen_ids)
            add_log(f"Captured {len(new_items)} new listing(s).")
            st.session_state.latest_scan_summary = f"{len(new_items)} new listing(s) found."
            st.toast(st.session_state.latest_scan_summary)
            for listing in new_items[:3]:
                st.toast(f"{listing.title} - {listing.price}")
        else:
            add_log("No new listings in this scan.")
            st.session_state.latest_scan_summary = "No new listings found in the latest scan."
            st.toast(st.session_state.latest_scan_summary)

        st.session_state.last_error = ""
        st.session_state.last_check = time.time()
    except CarousellyError as exc:
        st.session_state.last_error = str(exc)
        st.session_state.running = False
        add_log(f"Error: {exc}")


def set_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f4efe7;
            --card: #ffffff;
            --ink: #0f172a;
            --muted: #5b6475;
            --accent: #e85d04;
            --accent-soft: rgba(232, 93, 4, 0.12);
            --border: #dde3eb;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(232, 93, 4, 0.12), transparent 28%),
                radial-gradient(circle at bottom right, rgba(34, 197, 94, 0.10), transparent 22%),
                var(--bg);
        }

        .hero {
            padding: 2rem 2rem 1.5rem 2rem;
            border: 1px solid var(--border);
            border-radius: 24px;
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.98), rgba(30, 41, 59, 0.96));
            color: #f8fafc;
            box-shadow: 0 20px 60px rgba(15, 23, 42, 0.12);
            margin-bottom: 1.25rem;
        }

        .hero-kicker {
            font-size: 0.82rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #fbbf24;
            margin-bottom: 0.5rem;
        }

        .hero-title {
            font-size: 2.25rem;
            line-height: 1.05;
            font-weight: 800;
            margin: 0;
        }

        .hero-copy {
            margin-top: 0.75rem;
            max-width: 60rem;
            color: #cbd5e1;
            font-size: 1rem;
        }

        .metric-card, .panel-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 20px;
            box-shadow: 0 14px 40px rgba(15, 23, 42, 0.06);
        }

        .metric-card {
            padding: 1rem 1.1rem;
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.84rem;
            margin-bottom: 0.35rem;
        }

        .metric-value {
            color: var(--ink);
            font-size: 1.6rem;
            font-weight: 800;
        }

        .sidebar-note {
            padding: 0.75rem 0.9rem;
            border-radius: 14px;
            background: var(--accent-soft);
            color: var(--ink);
            font-size: 0.92rem;
        }

        .scan-chip {
            display: inline-block;
            padding: 0.28rem 0.7rem;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_controls() -> SearchConfig:
    with st.sidebar:
        st.markdown("## Search Controls")
        st.markdown(
            "<div class='sidebar-note'>Set the product name and price band you want to monitor. New matches appear as popups and in the latest scan panel.</div>",
            unsafe_allow_html=True,
        )

        current = st.session_state.current_config
        product_name = st.text_input("Product name", value=current.product_name, placeholder="e.g. iPhone 15, monitor, PS5")

        col_left, col_right = st.columns(2)
        with col_left:
            min_price = st.number_input("Min price", min_value=0, value=int(current.min_price), step=50)
        with col_right:
            max_price = st.number_input("Max price", min_value=0, value=int(current.max_price), step=50)

        max_results = st.number_input("Max results per scan", min_value=1, value=int(current.max_results), step=1)
        check_interval = st.number_input("Check interval (seconds)", min_value=10, value=int(current.check_interval), step=10)
        headless = st.checkbox("Headless browser", value=bool(current.headless), help="Disable this when you want to see the browser while the scan runs.")

        config = SearchConfig(
            product_name=product_name,
            min_price=int(min_price),
            max_price=int(max_price),
            max_results=int(max_results),
            headless=headless,
            check_interval=int(check_interval),
            proxy_server=current.proxy_server,
        )

        st.session_state.current_config = config

        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Start", use_container_width=True):
                try:
                    config.validate()
                    signature = config_signature(config)
                    if st.session_state.search_signature != signature:
                        reset_results(config)
                        st.session_state.search_signature = signature
                    st.session_state.running = True
                    st.session_state.current_config = config
                    add_log("Monitoring started.")
                    st.rerun()
                except CarousellyError as exc:
                    st.error(str(exc))
        with col_b:
            if st.button("Stop", use_container_width=True, disabled=not st.session_state.running):
                st.session_state.running = False
                add_log("Monitoring stopped.")
                st.rerun()

        if st.button("Run one scan", use_container_width=True):
            try:
                config.validate()
                if st.session_state.search_signature != config_signature(config):
                    reset_results(config)
                    st.session_state.search_signature = config_signature(config)
                run_scan(config)
                st.rerun()
            except CarousellyError as exc:
                st.error(str(exc))

        if st.button("Reset saved data", use_container_width=True):
            reset_results(config)
            st.session_state.seen_ids = set()
            st.session_state.found_items = []
            st.session_state.logs = []
            st.session_state.last_error = ""
            add_log("Saved data cleared.")
            st.rerun()

    return config


def render_header(config: SearchConfig) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-kicker">Portfolio build</div>
            <h1 class="hero-title">Carouselly</h1>
            <div class="hero-copy">
                A focused Carousell monitor for spotting listings that match a product name and price range.
                It is built to be easy to demo, easy to read, and easy to extend.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Tracked item count</div><div class="metric-value">{len(st.session_state.found_items)}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Monitoring state</div><div class="metric-value">{"Active" if st.session_state.running else "Stopped"}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Seen listing ids</div><div class="metric-value">{len(st.session_state.seen_ids)}</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        last_check = "Never" if not st.session_state.last_check else time.strftime("%H:%M:%S", time.localtime(st.session_state.last_check))
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Last check</div><div class="metric-value">{last_check}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 0.35rem'></div>", unsafe_allow_html=True)
    st.markdown(f"<span class='scan-chip'>Watching: {config.product_name}</span>", unsafe_allow_html=True)


def render_main_panel(config: SearchConfig) -> None:
    st.subheader("Latest findings")
    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    if st.session_state.get("latest_scan_summary"):
        st.info(st.session_state.latest_scan_summary)

    if st.session_state.found_items:
        display_rows = [
            {
                "Title": item.title,
                "Price": item.price,
                "Found at": item.found_at,
                "Link": item.link,
            }
            for item in reversed(st.session_state.found_items)
        ]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No matched listings yet. Start monitoring or run a one-off scan from the sidebar.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("Activity log")
        if st.session_state.logs:
            for entry in reversed(st.session_state.logs[-12:]):
                st.write(entry)
        else:
            st.caption("Logs will appear here when a scan runs.")
    with col_right:
        st.subheader("Current scan URL")
        st.code(build_search_url(config), language="text")
        st.caption("This is the exact Carousell search URL used by the scraper.")

    st.divider()
    st.subheader("Latest scan popup feed")
    if st.session_state.get("latest_scan"):
        for item in st.session_state.latest_scan:
            st.markdown(f"- **{item.title}** - {item.price}  \n  {item.link}")
    else:
        st.caption("Run a scan to see popup notifications and the latest matched listings here.")


def main() -> None:
    st.set_page_config(page_title="Carouselly", page_icon="🛒", layout="wide")
    ensure_session_state()
    set_dashboard_styles()

    config = sidebar_controls()
    render_header(config)

    if st.session_state.running:
        now = time.time()
        if now - st.session_state.last_check >= config.check_interval:
            run_scan(config)
        time.sleep(1)
        st.rerun()

    render_main_panel(config)


if __name__ == "__main__":
    main()
