"""
LinkedIn Auto Connection Request Script
========================================
Automates sending personalized connection requests on LinkedIn using Selenium.

⚠️  IMPORTANT WARNINGS:
    - This script uses browser automation which violates LinkedIn's Terms of Service.
    - Use at your own risk — misuse can result in account restriction or permanent ban.
    - Designed to RESPECT free account limits: max 20–25 requests/day.
    - Always add a personalized note to improve acceptance rates.
    - Never run this script aggressively or overnight.

Requirements:
    pip install selenium webdriver-manager pandas colorama

Usage:
    1. Fill in your credentials in the CONFIG section below.
    2. Add target profile URLs to 'profiles.csv' (see sample format).
    3. Run: python linkedin_connector.py
"""

import time
import random
import csv
import logging
import os
import urllib.parse
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import streamlit as st
import sys
from colorama import Fore, Style, init
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION — Edit this section before running
# ─────────────────────────────────────────────────────────────────────────────

CONFIG = {
    # ── LinkedIn Credentials ──────────────────────────────────────────────────
    "email": "ashowry1999@gmail.com",        # Your LinkedIn email
    "password": "HD<'325P'_Q6r:)",       # Your LinkedIn password

    # ── Input File ────────────────────────────────────────────────────────────
    "profiles_csv": "LinkedIn - Sheet1.csv",         # CSV with LinkedIn profile URLs

    # ── Output / Logging ─────────────────────────────────────────────────────
    "log_file": "linkedin_log.csv",         # Log of sent/failed requests
    "progress_file": "progress.txt",        # Tracks daily count across runs

    # ── Safety Limits (FREE ACCOUNT) ─────────────────────────────────────────
    "daily_limit": 20,                      # Max requests per day (keep ≤ 25)
    "min_delay_sec": 20,                     # Min seconds between actions
    "max_delay_sec": 60,                    # Max seconds between actions

    # ── Connection Note ───────────────────────────────────────────────────────
    # Set to True  → clicks "Add a note", types your message, then clicks "Send"
    # Set to False → clicks "Send without a note" directly
    "add_note": False,
 
    # Use {first_name} as a placeholder — it will be replaced automatically.
    # Keep it under 200 characters (free account limit).
    # Only used when add_note is True.
    "connection_note": (
        "Hi {first_name}, I came across your profile and would love to connect "
        "and exchange ideas. Looking forward to connecting!"
    ),
 
    # ── Browser Settings ─────────────────────────────────────────────────────
    "headless": False,   # False = show browser window (safer, recommended)
    "slow_mode": True,   # Adds extra delays to mimic human typing speed
}
 
# ─────────────────────────────────────────────────────────────────────────────
#  SETUP — Logging & Console Colors
# ─────────────────────────────────────────────────────────────────────────────
 
init(autoreset=True)  # Initialize colorama
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
 
 
def log_info(msg):
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL}  {msg}")
 
def log_success(msg):
    print(f"{Fore.GREEN}[OK]{Style.RESET_ALL}    {msg}")
 
def log_warning(msg):
    print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}  {msg}")
 
def log_error(msg):
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {msg}")
 
def log_skip(msg):
    print(f"{Fore.MAGENTA}[SKIP]{Style.RESET_ALL}  {msg}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  DAILY LIMIT TRACKER
# ─────────────────────────────────────────────────────────────────────────────
 
def get_today_count(progress_file: str) -> int:
    """Read how many requests have been sent today from the progress file."""
    today = str(date.today())
    if not os.path.exists(progress_file):
        return 0
    with open(progress_file, "r") as f:
        lines = f.read().strip().split("\n")
    for line in lines:
        if line.startswith(today):
            return int(line.split(",")[1])
    return 0
 
 
def update_today_count(progress_file: str, count: int):
    """Update the daily count in the progress file."""
    today = str(date.today())
    lines = []
    found = False
    if os.path.exists(progress_file):
        with open(progress_file, "r") as f:
            lines = f.read().strip().split("\n")
    new_lines = []
    for line in lines:
        if line.startswith(today):
            new_lines.append(f"{today},{count}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{today},{count}")
    with open(progress_file, "w") as f:
        f.write("\n".join(new_lines))
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  CSV LOG WRITER
# ─────────────────────────────────────────────────────────────────────────────
 
def append_log(log_file: str, profile_url: str, name: str, status: str, note: str = ""):
    """Append a result row to the CSV log file."""
    file_exists = os.path.exists(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "profile_url", "name", "status", "note"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            profile_url,
            name,
            status,
            note,
        ])
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  BROWSER SETUP
# ─────────────────────────────────────────────────────────────────────────────
 
def create_driver(headless: bool = False) -> webdriver.Chrome:
    """Initialize and return a configured Chrome WebDriver.

    Uses selenium-stealth to mask automation fingerprints and prevent
    LinkedIn from detecting the browser as a bot (root cause of CAPTCHAs).

    Handles two environments automatically:
      - Windows (local): uses webdriver-manager to download the correct win64 chromedriver.
      - Linux (Streamlit Cloud): uses system Chromium installed via packages.txt.
    """
    import platform
    import glob
    import subprocess as sp

    options = Options()

    system = platform.system()

    if system != "Windows":
        # ── Streamlit Cloud / Linux ───────────────────────────────────────────
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")

        # Locate system chromium binary
        for binary in ("chromium-browser", "chromium"):
            result = sp.run(["which", binary], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                options.binary_location = result.stdout.strip()
                log_info(f"Using system Chromium: {options.binary_location}")
                break

        # Locate system chromedriver
        driver_path = None
        for candidate in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver",
                          "/usr/lib/chromium-browser/chromedriver"):
            if os.path.isfile(candidate):
                driver_path = candidate
                log_info(f"Using system chromedriver: {driver_path}")
                break

        if driver_path is None:
            log_warning("System chromedriver not found, falling back to webdriver-manager.")
            from webdriver_manager.chrome import ChromeDriverManager as CDM
            driver_path = CDM().install()

        service = Service(driver_path)

    else:
        # ── Windows (local) ───────────────────────────────────────────────────
        if headless:
            options.add_argument("--headless=new")

        from webdriver_manager.core.os_manager import OperationSystemManager
        os_manager = OperationSystemManager(os_type="win64")
        manager = ChromeDriverManager(os_system_manager=os_manager)
        driver_path = manager.install()

        # webdriver-manager bug: returns path to THIRD_PARTY_NOTICES instead of exe
        if not driver_path.endswith(".exe") or not os.path.isfile(driver_path):
            search_root = os.path.dirname(driver_path)
            candidates = glob.glob(os.path.join(search_root, "**", "chromedriver.exe"), recursive=True)
            if not candidates:
                candidates = glob.glob(os.path.join(os.path.dirname(search_root), "**", "chromedriver.exe"), recursive=True)
            if candidates:
                driver_path = candidates[0]
                log_info(f"Resolved chromedriver.exe → {driver_path}")
            else:
                log_error("Could not locate chromedriver.exe — automation may fail.")

        service = Service(driver_path)

    # ── Anti-detection options ───────────────────────────────────────────────
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--lang=en-US")
    options.add_argument("--window-size=1920,1080")

    if system == "Windows":
        options.add_argument("--start-maximized")

    driver = webdriver.Chrome(service=service, options=options)

    # ── Apply selenium-stealth (masks ALL automation fingerprints) ────────
    try:
        from selenium_stealth import stealth
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        log_info("selenium-stealth applied — browser fingerprint masked.")
    except ImportError:
        log_warning("selenium-stealth not installed. Falling back to basic anti-detection.")
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    return driver
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  HUMAN-LIKE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
 
def human_delay(min_s: float = None, max_s: float = None):
    """Sleep for a random duration to mimic human behavior."""
    min_s = min_s or CONFIG["min_delay_sec"]
    max_s = max_s or CONFIG["max_delay_sec"]
    duration = random.uniform(min_s, max_s)
    time.sleep(duration)
 
 
def human_type(element, text: str):
    """Type text character by character with random delays."""
    for char in text:
        element.send_keys(char)
        if CONFIG["slow_mode"]:
            time.sleep(random.uniform(0.04, 0.12))
 
 
def scroll_page(driver, amount: int = None):
    """Scroll the page by a random or specified amount."""
    amount = amount or random.randint(200, 600)
    driver.execute_script(f"window.scrollBy(0, {amount});")
    time.sleep(random.uniform(0.5, 1.5))
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  LINKEDIN ACTIONS
# ─────────────────────────────────────────────────────────────────────────────
 
def _handle_challenge(driver) -> str:
    """Detect and handle LinkedIn verification challenges.

    Returns:
        'solved'    — challenge was auto-handled (verify button clicked)
        'pin_needed' — email PIN verification detected, user must enter PIN
        'unknown'   — unknown challenge type (screenshot saved for user)
        'none'      — no challenge detected
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return "none"

    # ── Type 0: reCAPTCHA "I'm not a robot" checkbox (inside iframe) ─────
    if "security check" in body_text or "captcha" in body_text or "robot" in body_text:
        try:
            # Find all iframes — reCAPTCHA lives in one
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            captcha_found = False
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "recaptcha" in src or "captcha" in src or "challenge" in src:
                    log_info(f"Checking iframe for checkbox (src: {src[:50]})...")
                    driver.switch_to.frame(iframe)
                    try:
                        # Click the "I'm not a robot" checkbox
                        checkbox = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".recaptcha-checkbox-border, #recaptcha-anchor, .recaptcha-checkbox"))
                        )
                        log_info("Checkbox found! Attempting to click...")
                        try:
                            # Try ActionChains first (more human-like, avoids some interception)
                            ActionChains(driver).move_to_element(checkbox).pause(0.5).click().perform()
                        except Exception:
                            try:
                                checkbox.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", checkbox)
                                
                        log_info("Clicked reCAPTCHA checkbox.")
                        human_delay(3, 6)
                        captcha_found = True

                        # Check if the checkbox turned green (solved)
                        try:
                            checked = driver.find_element(By.CSS_SELECTOR, ".recaptcha-checkbox-checked, [aria-checked='true']")
                            if checked:
                                log_success("reCAPTCHA checkbox passed!")
                                driver.switch_to.default_content()
                                # Click any submit/verify button on the main page
                                try:
                                    submit = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
                                    driver.execute_script("arguments[0].click();", submit)
                                    human_delay(3, 5)
                                except NoSuchElementException:
                                    pass
                                return "solved"
                        except NoSuchElementException:
                            log_warning("reCAPTCHA checkbox clicked but may need image puzzle.")
                    except TimeoutException:
                        log_info("Not the correct iframe (no checkbox). Trying next...")
                    except Exception as e:
                        log_warning(f"Error while interacting with reCAPTCHA iframe: {e}")
                    finally:
                        driver.switch_to.default_content()
                    
                    if captcha_found:
                        break # We found the anchor iframe and clicked it, no need to check others

            # If we got here, reCAPTCHA wasn't solved
            log_warning("reCAPTCHA detected but could not be auto-solved (image puzzle likely required).")
            st.warning(
                "🔒 **reCAPTCHA detected** — LinkedIn is showing 'Let's do a quick security check'.\n\n"
                "This happens because Streamlit Cloud uses a **data center IP** which LinkedIn flags as suspicious. "
                "No free tool can solve image/puzzle CAPTCHAs automatically.\n\n"
                "**Solutions:**\n"
                "1. **Run locally** on your computer (works perfectly — no CAPTCHA)\n"
                "2. **Use a residential proxy** to mask the cloud IP\n"
            )
            return "unknown"
        except Exception as e:
            log_error(f"reCAPTCHA handling error: {e}")
            driver.switch_to.default_content()

    # ── Type 1: Simple "Verify" / "Submit" / "Continue" button ───────────
    verify_xpaths = [
        "//button[contains(text(),'Verify')]",
        "//button[contains(text(),'verify')]",
        "//button[contains(text(),'Submit')]",
        "//button[contains(text(),'Continue')]",
        "//button[@id='home_children_button']",
        "//input[@type='submit']",
    ]
    for xpath in verify_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            if btn.is_displayed():
                log_info(f"Found verify button — clicking it...")
                try:
                    btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btn)
                human_delay(3, 5)
                return "solved"
        except NoSuchElementException:
            continue

    # ── Type 2: Email / SMS PIN verification ─────────────────────────
    pin_keywords = ["enter the code", "verification code", "pin", "we sent", "check your email"]
    if any(kw in body_text for kw in pin_keywords):
        pin_selectors = ["input[name='pin']", "input#input__email_verification_pin",
                         "input[name='verification_code']", "input[type='text']"]
        for sel in pin_selectors:
            try:
                pin_input = driver.find_element(By.CSS_SELECTOR, sel)
                if pin_input.is_displayed():
                    log_info("Email/SMS PIN verification detected.")
                    return "pin_needed"
            except NoSuchElementException:
                continue

    # ── Type 3: Unknown challenge ─────────────────────────────────
    if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
        return "unknown"

    return "none"


def _enter_pin(driver, pin: str) -> bool:
    """Enter a verification PIN code into LinkedIn's challenge page."""
    pin_selectors = ["input[name='pin']", "input#input__email_verification_pin",
                     "input[name='verification_code']", "input[type='text']"]
    for sel in pin_selectors:
        try:
            pin_input = driver.find_element(By.CSS_SELECTOR, sel)
            if pin_input.is_displayed():
                pin_input.clear()
                human_type(pin_input, pin)
                human_delay(0.5, 1)

                # Click submit
                submit_xpaths = [
                    "//button[contains(text(),'Submit')]",
                    "//button[contains(text(),'Verify')]",
                    "//button[@type='submit']",
                    "//input[@type='submit']",
                ]
                for xpath in submit_xpaths:
                    try:
                        btn = driver.find_element(By.XPATH, xpath)
                        try:
                            btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", btn)
                        human_delay(3, 5)
                        return True
                    except NoSuchElementException:
                        continue

                # Fallback: press Enter
                pin_input.send_keys(Keys.RETURN)
                human_delay(3, 5)
                return True
        except NoSuchElementException:
            continue
    return False


def _save_challenge_screenshot(driver) -> str:
    """Save a screenshot of the challenge page and return the file path."""
    screenshot_path = os.path.join(os.path.dirname(__file__), "challenge_screenshot.png")
    try:
        driver.save_screenshot(screenshot_path)
        log_info(f"Challenge screenshot saved to: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        log_error(f"Failed to save screenshot: {e}")
        return ""


def login(driver: webdriver.Chrome, email: str, password: str) -> bool:
    """Log into LinkedIn with free challenge handling.

    Flow:
      1. Warm up browser session by visiting linkedin.com first
      2. Navigate to login page (selenium-stealth already masks automation)
      3. Enter credentials and submit
      4. If challenge detected:
         a. Auto-click verify buttons (free)
         b. Email PIN — prompt user in Streamlit UI to enter the code (free)
         c. Unknown — screenshot + show error
    """
    # ── Warm up session (helps avoid instant blocks) ──────────────────────
    log_info("Warming up browser session...")
    driver.get("https://www.linkedin.com")
    human_delay(3, 5)

    log_info("Navigating to LinkedIn login page...")
    driver.get("https://www.linkedin.com/login")
    human_delay(3, 5)

    try:
        # Try multiple possible login form selectors
        email_field = None
        selectors = [
            (By.ID, "username"),
            (By.CSS_SELECTOR, "input[name='session_key']"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[autocomplete='username']"),
        ]

        for by, selector in selectors:
            try:
                email_field = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((by, selector))
                )
                log_info(f"Login form found via: {selector}")
                break
            except TimeoutException:
                continue

        if email_field is None:
            # Page loaded but no login form — take screenshot for diagnostics
            log_error("Could not find login form on the page.")
            screenshot_path = _save_challenge_screenshot(driver)
            page_title = driver.title
            current_url = driver.current_url
            log_error(f"Page title: {page_title}")
            log_error(f"Current URL: {current_url}")

            st.error(f"⚠️ LinkedIn login page did not load properly.\n\n"
                     f"**Page title:** {page_title}\n\n"
                     f"**URL:** {current_url}")
            if screenshot_path and os.path.exists(screenshot_path):
                st.image(screenshot_path, caption="What the browser is showing")
            st.info("**Tip:** This usually means LinkedIn is blocking this server's IP. "
                    "Try running the automation locally on your computer instead.")
            return False

        human_type(email_field, email)
        human_delay(0.5, 1.5)

        pass_field = driver.find_element(By.ID, "password")
        human_type(pass_field, password)
        human_delay(0.5, 1.5)

        pass_field.send_keys(Keys.RETURN)
        human_delay(4, 7)

        # ── Check outcome ──────────────────────────────────────────────────
        current_url = driver.current_url

        if "feed" in current_url or "mynetwork" in current_url:
            log_success("Logged in successfully!")
            return True

        elif "checkpoint" in current_url or "challenge" in current_url:
            log_warning("LinkedIn verification challenge detected.")

            challenge_type = _handle_challenge(driver)

            if challenge_type == "solved":
                # Verify button was clicked — check if we're in
                human_delay(2, 4)
                if "feed" in driver.current_url or "mynetwork" in driver.current_url:
                    log_success("Challenge auto-solved — logged in!")
                    return True
                # May need PIN after verify click
                challenge_type = _handle_challenge(driver)

            if challenge_type == "pin_needed":
                log_info("PIN verification required — check your email for the code.")
                st.warning("📧 LinkedIn sent a verification code to your email. Enter it below.")

                # Use session state to handle the PIN input outside the form
                if "linkedin_driver" not in st.session_state:
                    st.session_state["linkedin_driver"] = driver
                    st.session_state["pin_stage"] = True
                    st.session_state["login_success"] = False

                pin_code = st.text_input("Enter verification PIN from your email:", key="pin_input")
                submit_pin = st.button("✅ Submit PIN", key="submit_pin")

                if submit_pin and pin_code:
                    log_info(f"Entering PIN: {'*' * len(pin_code)}")
                    if _enter_pin(driver, pin_code.strip()):
                        human_delay(3, 5)
                        if "feed" in driver.current_url or "mynetwork" in driver.current_url:
                            log_success("PIN verified — logged in!")
                            st.success("✅ PIN verified! Login successful.")
                            return True
                        else:
                            st.error("PIN was entered but login still failed. The PIN may be incorrect.")
                            return False
                    else:
                        st.error("Could not find the PIN input field on the page.")
                        return False

                # Stop execution here and wait for user to enter PIN
                st.stop()

            # Unknown challenge — take screenshot and show user
            import platform
            if platform.system() == "Windows":
                log_warning("Please complete the verification in the browser window.")
                input("Press ENTER here once you've completed the verification...")
                return True
            else:
                screenshot_path = _save_challenge_screenshot(driver)
                st.error("⚠️ LinkedIn triggered a verification challenge that couldn't be auto-solved.")
                if screenshot_path and os.path.exists(screenshot_path):
                    st.image(screenshot_path, caption="Challenge screenshot — this is what LinkedIn is showing")
                st.info("**Tip:** Log in to LinkedIn from your phone/laptop first to clear the challenge, then try again.")
                return False
        else:
            # Unknown page — screenshot for diagnostics
            log_error("Login may have failed. Check your credentials.")
            screenshot_path = _save_challenge_screenshot(driver)
            if screenshot_path and os.path.exists(screenshot_path):
                st.image(screenshot_path, caption="Post-login page — this is what LinkedIn redirected to")
            return False

    except TimeoutException:
        log_error("Timed out waiting for the login page to load.")
        screenshot_path = _save_challenge_screenshot(driver)
        st.error("⚠️ LinkedIn login page timed out.")
        if screenshot_path and os.path.exists(screenshot_path):
            st.image(screenshot_path, caption="Timeout screenshot — this is what the browser was showing")
        st.info("**Possible causes:** LinkedIn may be blocking this server's IP, or the page didn't load due to network issues.")
        return False
 
 
def get_first_name(driver: webdriver.Chrome) -> str:
    """Try to extract the first name from the profile page."""
    try:
        name_element = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h1.text-heading-xlarge"))
        )
        full_name = name_element.text.strip()
        return full_name.split()[0] if full_name else "there"
    except Exception:
        return "there"
 
 
def send_connection_request(
    driver: webdriver.Chrome,
    profile_url: str,
    add_note: bool,
    note_template: str,
    log_file: str,
) -> str:
    """
    Visit a LinkedIn profile and send a connection request.
 
    Flow:
        1. Navigate directly to the custom-invite page:
             https://www.linkedin.com/preload/custom-invite/?vanityName=<handle>
           → A popup appears with two buttons:
               • "Add a note"          (shown when add_note=True)
               • "Send without a note" (shown when add_note=False)
        3a. add_note=True  → click "Add a note" → type message → click "Send"
        3b. add_note=False → click "Send without a note" directly
 
    Returns:
        'sent'    — request was sent successfully
        'skipped' — already connected or request already pending
        'failed'  — something went wrong
        'limit'   — LinkedIn's own weekly limit was hit
    """
    log_info(f"Visiting: {profile_url}")
    driver.get(profile_url)
    human_delay(3, 6)
    scroll_page(driver)
 
    first_name = get_first_name(driver)
    log_info(f"  Profile name detected: {first_name}")
 
    # ── Step 1: Navigate directly to the custom-invite page ──────
    try:
        parsed_url = urllib.parse.urlparse(profile_url)
        path_parts = [p for p in parsed_url.path.split('/') if p]
        
        handle = ""
        if 'in' in path_parts:
            handle = path_parts[path_parts.index('in') + 1]
        elif len(path_parts) > 0:
            handle = path_parts[-1]
            
        if not handle:
            log_error(f"Could not extract handle from {profile_url}")
            append_log(log_file, profile_url, first_name, "failed", "invalid profile format")
            return "failed"
            
        invite_url = f"https://www.linkedin.com/preload/custom-invite/?vanityName={handle}"
        log_info(f"  Navigating to custom invite URL: {invite_url}")
        driver.get(invite_url)
        
        # Wait for the page / popup to settle
        human_delay(2, 4)
        
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
            if "Pending" in page_text or "already sent" in page_text.lower() or "Message" in page_text:
                log_skip(f"Already connected or request pending — {profile_url}")
                append_log(log_file, profile_url, first_name, "skipped", "already connected/pending")
                return "skipped"
        except Exception:
            pass

    except Exception as e:
        log_error(f"Failed to navigate to invite URL for {profile_url}: {str(e)}")
        append_log(log_file, profile_url, first_name, "failed", "invite url navigation error")
        return "failed"
 
    # ── Step 2: Check for LinkedIn's weekly limit notice ─────────────────────
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text
        if "weekly invitation limit" in page_text.lower():
            log_error("LinkedIn weekly invitation limit reached! Stopping.")
            append_log(log_file, profile_url, first_name, "limit", "LinkedIn weekly limit hit")
            return "limit"
    except Exception:
        pass
 
    # ── Step 3a: add_note=True → "Add a note" → type → "Send" ───────────────
    if add_note:
        try:
            add_note_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(@aria-label,'Add a note')]"
                    "|//span[normalize-space()='Add a note']"
                ))
            )
            try:
                add_note_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", add_note_btn)
            human_delay(1, 2)
 
            note_box = WebDriverWait(driver, 6).until(
                EC.presence_of_element_located((By.ID, "custom-message"))
            )
 
            personalized_note = note_template.replace("{first_name}", first_name)[:200]
            human_type(note_box, personalized_note)
            human_delay(1, 2)
 
            send_btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(@aria-label,'Send now')]"
                    "|//span[normalize-space()='Send']"
                ))
            )
            try:
                send_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", send_btn)
            human_delay(2, 4)
 
            log_success(f"  ✓ Request sent to {first_name} (with note).")
            append_log(log_file, profile_url, first_name, "sent", personalized_note)
            return "sent"
 
        except TimeoutException:
            log_error(f"  Timed out during 'Add a note' flow for {profile_url}")
            append_log(log_file, profile_url, first_name, "failed", "add-note flow timed out")
            return "failed"
 
    # ── Step 3b: add_note=False → "Send without a note" directly ────────────
    else:
        try:
            send_without_note_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(@aria-label,'Send without a note')]"
                    "|//span[normalize-space()='Send without a note']"
                ))
            )
            try:
                send_without_note_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", send_without_note_btn)
            human_delay(2, 4)
 
            log_success(f"  ✓ Request sent to {first_name} (without note).")
            append_log(log_file, profile_url, first_name, "sent", "")
            return "sent"
 
        except TimeoutException:
            log_error(f"  Timed out waiting for 'Send without a note' for {profile_url}")
            append_log(log_file, profile_url, first_name, "failed", "send-without-note timed out")
            return "failed"
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  LOAD PROFILES FROM CSV
# ─────────────────────────────────────────────────────────────────────────────
 
def load_profiles(csv_file) -> list[str]:
    """Load LinkedIn profile URLs from a CSV file or file-like object. Expects a 'url' column."""
    if isinstance(csv_file, str) and not os.path.exists(csv_file):
        log_error(f"CSV file not found: {csv_file}")
        log_info("Creating a sample 'profiles.csv' for you...")
        create_sample_csv(csv_file)
        return []
 
    df = pd.read_csv(csv_file)
    if "url" not in df.columns:
        log_error("CSV must have a column named 'url'")
        return []
 
    urls = df["url"].dropna().str.strip().tolist()
    log_info(f"Loaded {len(urls)} profile URLs from {csv_file}")
    return urls
 
 
def create_sample_csv(filename: str):
    """Create a sample profiles.csv so users know the format."""
    sample = pd.DataFrame({
        "url": [
            "https://www.linkedin.com/in/example-profile-1/",
            "https://www.linkedin.com/in/example-profile-2/",
            "https://www.linkedin.com/in/example-profile-3/",
        ]
    })
    sample.to_csv(filename, index=False)
    log_success(f"Sample '{filename}' created. Add your target profile URLs there.")
 
 
# ─────────────────────────────────────────────────────────────────────────────
#  MAIN RUNNER / STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────
 
def run_automation(email, password, uploaded_file, add_note, note_text, start_row, end_row):
    # Set config overrides
    CONFIG["email"] = email
    CONFIG["password"] = password
    CONFIG["add_note"] = add_note
    if add_note:
        CONFIG["connection_note"] = note_text

    today_count = get_today_count(CONFIG["progress_file"])
    remaining = CONFIG["daily_limit"] - today_count
 
    if remaining <= 0:
        st.warning(f"Daily limit of {CONFIG['daily_limit']} already reached for today. Try again tomorrow!")
        return
 
    st.info(f"Daily limit: {CONFIG['daily_limit']} | Sent today: {today_count} | Remaining: {remaining}")
 
    # Load profiles using the uploaded file directly
    all_profiles = load_profiles(uploaded_file)
    if not all_profiles:
        st.error("Could not load profiles from the provided CSV. Ensure it has a 'url' column.")
        return
        
    start_idx = max(0, start_row - 1)
    end_idx = end_row if end_row > 0 else len(all_profiles)
    all_profiles = all_profiles[start_idx:end_idx]
 
    profiles_to_process = all_profiles[:remaining]
    st.info(f"Will process {len(profiles_to_process)} profiles this session.")
 
    # Launch browser & login
    driver = create_driver(headless=CONFIG["headless"])
 
    try:
        if not login(driver, CONFIG["email"], CONFIG["password"]):
            st.error("Login failed. Check your console and credentials.")
            return
 
        human_delay(3, 6)  # Wait a bit after login before starting
 
        # ── Process each profile ─────────────────────────────────────────────
        sent_count = 0
        failed_count = 0
        skipped_count = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
 
        for i, url in enumerate(profiles_to_process, start=1):
            status_text.text(f"Processing Profile {i}/{len(profiles_to_process)}: {url}")
            print(f"\n{'─' * 50}")
            print(f"  Profile {i}/{len(profiles_to_process)}")
 
            result = send_connection_request(
                driver=driver,
                profile_url=url,
                add_note=CONFIG["add_note"],
                note_template=CONFIG["connection_note"],
                log_file=CONFIG["log_file"],
            )
 
            if result == "sent":
                sent_count += 1
                update_today_count(CONFIG["progress_file"], today_count + sent_count)
            elif result == "skipped":
                skipped_count += 1
            elif result == "failed":
                failed_count += 1
            elif result == "limit":
                st.error("LinkedIn limit hit — stopping early to protect your account.")
                break
                
            progress_bar.progress(i / len(profiles_to_process))
 
            # ── Wait between profiles (human-like) ──────────────────────────
            if i < len(profiles_to_process):
                wait_time = random.uniform(CONFIG["min_delay_sec"], CONFIG["max_delay_sec"])
                st.caption(f"Waiting {wait_time:.1f}s before next profile...")
                time.sleep(wait_time)
                st.caption("") # Clear text
 
    finally:
        driver.quit()
 
    # ── Final Summary ────────────────────────────────────────────────────────
    st.success(f"Session Complete! Sent: {sent_count}, Skipped: {skipped_count}, Failed: {failed_count}")
    st.info(f"Total sent today: {today_count + sent_count}/{CONFIG['daily_limit']}")


def main():
    st.title("LinkedIn Auto Connector")
    st.markdown("Automates sending personalized connection requests on LinkedIn.")
    
    with st.form("config_form"):
        email = st.text_input("LinkedIn Email", value=CONFIG["email"])
        password = st.text_input("LinkedIn Password", value="", type="password")
        
        uploaded_file = st.file_uploader("Upload Profiles CSV (Must contain a 'url' column)", type=['csv'])
        
        col1, col2 = st.columns(2)
        with col1:
            start_row = st.number_input("Start Row", min_value=1, value=1)
        with col2:
            end_row = st.number_input("End Row (0 for all)", min_value=0, value=0)
        
        add_note = st.checkbox("Add a connection note", value=CONFIG["add_note"])
        note_text = st.text_area("Connection Note (use {first_name} for name)", value=CONFIG["connection_note"], max_chars=200)
        
        submitted = st.form_submit_button("Start Automation")
        
    if submitted:
        if not email or not password:
            st.error("Please provide both Email and Password.")
        elif not uploaded_file:
            st.error("Please upload a CSV file with target profiles.")
        else:
            run_automation(email, password, uploaded_file, add_note, note_text, start_row, end_row)

if __name__ == "__main__":
    import os
    if os.environ.get("STREAMLIT_RUNNING") == "true":
        main()
    else:
        import subprocess
        os.environ["STREAMLIT_RUNNING"] = "true"
        sys.exit(subprocess.run([sys.executable, "-m", "streamlit", "run", sys.argv[0]]).returncode)