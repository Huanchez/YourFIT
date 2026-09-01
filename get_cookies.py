"""
get_cookies.py - вход на data.ozon.ru, сохранение cookies.
Данные о товарах не собираем
 
Запуск:
    python get_cookies.py            # автоматический вход
    python get_cookies.py --manual   # войти руками, скрипт только сохранит cookies
"""
 
import argparse
import base64
import json
import logging
import os
import re
import sys
import time
 
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright
 
PHONE = os.getenv("OZON_PHONE", "79001234567")
LOGIN_URL = "https://data.ozon.ru/app"  # редиректит на форму логина
COOKIES_FILE = "cookies.json"
PROFILE_DIR = ".chrome-profile" 
 
CREDENTIALS_FILE = "credentials.json"   # OAuth-ключ из Google Cloud Console
TOKEN_FILE = "token.json"               # создаётся автоматически при первом входе
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MAIL_QUERY = "from:ozon.ru newer_than:1h"
CODE_TIMEOUT = 180                      # сколько секунд ждём письмо

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
 
 
def get_gmail_service():
    # Авторизация в Gmail API. Первый раз откроется браузер, потом берём token.json
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
 
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
 
    return build("gmail", "v1", credentials=creds)
 
 
def get_message_text(message):
    # Собирает текст письма из всех его частей 
    parts = [message["payload"]] + message["payload"].get("parts", [])
    text = ""
    for part in parts:
        data = part.get("body", {}).get("data")
        if data:
            text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return text or message.get("snippet", "")
 
 
def wait_for_code(service, since_ts):
    # Ждём письмо, пришедшее позже since_ts, и достаём из него код
 
    logging.info("Жду письмо с кодом...")
    deadline = time.time() + CODE_TIMEOUT
 
    while time.time() < deadline:
        messages = service.users().messages().list(
            userId="me", q=MAIL_QUERY, maxResults=5
        ).execute().get("messages", [])
 
        for item in messages:
            message = service.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
 
            if int(message["internalDate"]) < since_ts * 1000:
                continue  # старое письмо
 
            match = re.search(r"\b(\d{6})\b", get_message_text(message))
            if match:
                logging.info("Код получен")
                return match.group(1)
 
        time.sleep(5)
 
    raise RuntimeError("Письмо с кодом не пришло за отведённое время")
 
 
def open_browser(pw):
    options = dict(
        headless=False,  # в headless антибот срабатывает почти всегда
        args=["--disable-blink-features=AutomationControlled"],
        locale="ru-RU",
        timezone_id="Europe/Moscow",
        viewport={"width": 1440, "height": 900},
    )

    try:
        context = pw.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", **options)
    except Exception:
        logging.warning("Chrome не найден, запускаю Chromium")
        context = pw.chromium.launch_persistent_context(PROFILE_DIR, **options)

    page = context.pages[0] if context.pages else context.new_page()
    return context, page
 
 
def is_blocked(page):
    html = page.content()
    return "Инцидент" in html or "fab_chlg" in html
 
 
def save_screenshot(page):
    try:
        page.screenshot(path="error.png")
        logging.info("Скриншот сохранён в error.png")
    except Exception:
        pass
 
 
def login(page):
    # Автоматический вход
    # Код страны (+7) в форме выбран отдельным селектором, поле принимает
    # только 10 цифр номера — без ведущей 7/8 из PHONE
    page.fill("input[type='tel']", PHONE[-10:])
    logging.info("Телефон введён")
 
    # Время запроса запоминаем до отправки формы 
    requested_at = time.time()
    page.click("button[type='submit']")
 
    code = wait_for_code(get_gmail_service(), requested_at)
    page.fill("input[type='text']", code)
    page.wait_for_load_state("networkidle", timeout=60000)
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", action="store_true", help="войти вручную в окне браузера")
    args = parser.parse_args()
 
    with sync_playwright() as pw:
        context, page = open_browser(pw)
 
        try:
            logging.info("Открываю %s", LOGIN_URL)
            page.goto(LOGIN_URL, timeout=60000)
            page.wait_for_timeout(3000)
 
            if args.manual:
                input("Войдите в аккаунт в окне браузера и нажмите Enter здесь... ")
            else:
                if is_blocked(page):
                    logging.warning("Ozon показал страницу проверки — пройдите её в окне браузера")
                    input("Когда увидите форму входа, нажмите Enter здесь... ")
                login(page)
 
            # Заходим на www.ozon.ru: парсим его, и cookies нужны именно этого домена
            page.goto("https://www.ozon.ru/", timeout=60000)
            page.wait_for_timeout(3000)
 
            cookies = context.cookies()
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            logging.info("Сохранено %s cookies в %s", len(cookies), COOKIES_FILE)
 
        except Exception as e:
            logging.error("Вход не выполнен: %s", e)
            save_screenshot(page)
            return 1
        finally:
            context.close()
 
    return 0
 
 
if __name__ == "__main__":
    sys.exit(main())
 