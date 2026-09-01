"""
parse_ozon.py - парсинг карточек товаров Ozon по списку SKU

Данные страницы лежат в JSON внутри HTML
Результат пишем в CSV

Запуск: python parse_ozon.py
"""

import csv
import json
import logging
import random
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

SKUS = ["2359066702", "2829800382"]
COOKIES_FILE = "cookies.json"
OUTPUT_FILE = "products.csv"

API_URL = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2"
PRODUCT_URL = "https://www.ozon.ru/product/{}/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}

FIELDS = ["sku", "title", "price", "rating", "reviews_total", "cover_image",
          "photos_seller", "videos_seller", "color", "material", "art_set",
          "has_rich_content", "error"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def make_session():
    # Создаёт сессию с cookies из файла
    with open(COOKIES_FILE, encoding="utf-8") as f:
        cookies = json.load(f)

    session = requests.Session()
    session.headers.update(HEADERS)
    for cookie in cookies:
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ".ozon.ru"))

    logging.info("Загружено %s cookies", len(cookies))
    return session


def get_widgets(session, sku):
    # Возвращает словарь виджетов страницы {имя: данные}
    # Основной вариант: внутренний JSON-эндпоинт
    response = session.get(API_URL, params={"url": f"/product/{sku}/"}, timeout=30)
    if response.status_code == 200 and "widgetStates" in response.text:
        raw = response.json()["widgetStates"]
    else:
        # Запасной вариант: тот же JSON, но вытащенный из HTML
        logging.warning("SKU %s: эндпоинт не ответил (%s), читаю HTML", sku, response.status_code)
        html = session.get(PRODUCT_URL.format(sku), timeout=30).text
        soup = BeautifulSoup(html, "html.parser")
        raw = {div["id"]: div["data-state"] for div in soup.select("div[data-state]")}

    if not raw:
        raise RuntimeError("данные виджетов не найдены")

    widgets = {}
    for name, value in raw.items():
        try:
            widgets[name] = json.loads(value)
        except json.JSONDecodeError:
            pass
    return widgets


def find(widgets, prefix):
    # Ищет виджет по началу имени
    for name, value in widgets.items():
        if prefix in name:
            return value
    return {}


def to_number(value, integer=False):
    # '1 299 ₽' -> 1299, '4,8' -> 4.8. None если числа нет
    if isinstance(value, (int, float)):
        return int(value) if integer else value

    match = re.search(r"\d+(?:[.,]\d+)?", re.sub(r"\s", "", str(value)))
    if not match:
        return None

    number = float(match.group().replace(",", "."))
    return int(number) if integer else number


def get_characteristics(widgets):
    # Собирает характеристики в словарь {'цвет': 'чёрный', ...}
    widget = find(widgets, "webShortCharacteristics") or find(widgets, "webCharacteristics")
    result = {}

    for group in widget.get("characteristics", []):
        # Характеристики бывают плоским списком или сгруппированными
        for item in group.get("short", [group]):
            name = item.get("name") or item.get("key", "")
            if isinstance(item.get("title"), dict):
                name = item["title"].get("textRs", [{}])[0].get("content", name)
            # У Ozon в values иногда встречаются пустые элементы и текст с запятой на конце
            texts = [v.get("text", "").strip(", ") for v in item.get("values", [])]
            values = ", ".join(t for t in texts if t)
            if name and values:
                result[name.lower()] = values

    return result


def get_characteristic(characteristics, *keywords):
    # Ищет характеристику по вхождению слова в название
    for keyword in keywords:
        for name, value in characteristics.items():
            if keyword in name:
                return value
    return None


def has_rich_content(widgets):
    # Есть ли в описании картинки, таблицы или списки
    description = find(widgets, "webDescription")
    if description.get("richAnnotationJson"):
        return True

    html = description.get("richAnnotation", "")
    return bool(BeautifulSoup(html, "html.parser").find(["img", "table", "ul", "ol"]))


def parse_sku(session, sku):
    # Собирает все нужные поля по одному товару
    widgets = get_widgets(session, sku)
    characteristics = get_characteristics(widgets)

    gallery = find(widgets, "webGallery")
    images = [img["src"] if isinstance(img, dict) else img for img in gallery.get("images", [])]
    score = find(widgets, "webReviewProductScore") or find(widgets, "webSingleProductScore")

    return {
        "sku": sku,
        "title": find(widgets, "webProductHeading").get("title"),
        "price": to_number(find(widgets, "webPrice").get("price"), integer=True),
        "rating": to_number(score.get("totalScore")),
        "reviews_total": to_number(score.get("reviewsCount"), integer=True),
        "cover_image": images[0] if images else None,
        "photos_seller": len(images),
        "videos_seller": len(gallery.get("videos", [])),
        "color": get_characteristic(characteristics, "цвет"),
        "material": get_characteristic(characteristics, "материал"),
        "art_set": get_characteristic(characteristics, "артикул", "комплектация"),
        "has_rich_content": has_rich_content(widgets),
        "error": None,
    }


def main():
    try:
        session = make_session()
    except FileNotFoundError:
        logging.error("Нет %s — сначала запустите get_cookies.py", COOKIES_FILE)
        return 1

    rows = []
    for sku in SKUS:
        logging.info("Парсю SKU %s", sku)
        try:
            row = parse_sku(session, sku)
            logging.info("SKU %s: %s, цена %s", sku, row["title"], row["price"])
        except Exception as e:
            # Ошибка по одному товару не должна останавливать весь список
            logging.error("SKU %s: ошибка — %s", sku, e)
            row = dict.fromkeys(FIELDS)
            row["sku"], row["error"] = sku, str(e)

        rows.append(row)
        time.sleep(random.uniform(2, 5))  # пауза чтобы не поймать капчу

    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    logging.info("Готово, результат в %s", OUTPUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
