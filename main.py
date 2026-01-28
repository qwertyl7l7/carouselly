import time
import json
import requests
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
SEARCH_QUERY = "rtx 4070"
MAX_PRICE = 2500
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"       # <--- Paste your ID here
SEEN_ITEMS_FILE = "seen_items.json"
CHECK_INTERVAL = 300 

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def load_seen_items():
    try:
        with open(SEEN_ITEMS_FILE, "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_seen_items(seen_ids):
    with open(SEEN_ITEMS_FILE, "w") as f:
        json.dump(list(seen_ids), f)

def check_carousell():
    seen_ids = load_seen_items()
    
    with sync_playwright() as p:
        # 1. Launch Visible Browser (headless=False)
        # This helps bypass Cloudflare significantly better than headless
        browser = p.chromium.launch(headless=False)
        
        # 2. Configure Context with a Real User Agent
        # (This is the most important part of "Stealth")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        
        page = context.new_page()

        # 3. Manual Stealth Injection
        # We inject JS to hide the "navigator.webdriver" flag that bots usually have
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        search_url = f"https://www.carousell.com.my/search/{SEARCH_QUERY}?sort_by=3&price_end={MAX_PRICE}"
        
        print(f"Checking: {search_url}")
        
        try:
            page.goto(search_url, timeout=60000) # Increased timeout to 60s
            
            # Wait for listings. 
            # If you see a Cloudflare "Verify you are human" box, 
            # you can now manually click it because headless=False!
            page.wait_for_selector('div[data-testid^="listing-card-"]', timeout=30000)
        
            listings = page.locator('div[data-testid^="listing-card-"]')
            count = listings.count()
            print(f"Found {count} listings.")
            
            new_items_found = False
            
            for i in range(min(count, 5)):
                item = listings.nth(i)
                item_id = item.get_attribute("data-testid").replace("listing-card-", "")
                
                if item_id not in seen_ids:
                    # Try to get data, skip if it fails (ads/promos sometimes break structure)
                    try:
                        text_content = item.inner_text().split('\n')
                        title = text_content[0]
                        price = text_content[1]
                        
                        link_element = item.locator("a").first
                        href = link_element.get_attribute("href")
                        full_link = f"https://www.carousell.com.my{href}"

                        msg = f"🚨 **New Deal Found!**\n\n**Item:** {title}\n**Price:** {price}\n**Link:** {full_link}"
                        send_telegram(msg)
                        print(f"Alert sent for {item_id}")
                        
                        seen_ids.add(item_id)
                        new_items_found = True
                    except Exception as e:
                        print(f"Skipping item {item_id}: {e}")

            if new_items_found:
                save_seen_items(seen_ids)

        except Exception as e:
            print(f"Error during check: {e}")
            # Optional: Take a screenshot to see what happened
            # page.screenshot(path="error_screenshot.png")
            
        finally:
            browser.close()

if __name__ == "__main__":
    while True:
        check_carousell()
        print(f"Sleeping for {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)