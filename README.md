# Парсер товаров Ozon

- `get_cookies.py` - автоматический вход на `data.ozon.ru` по телефону, код подтверждения берётся из почты через Gmail API, cookies сохраняются в `cookies.json`.
- `parse_ozon.py` - читает `cookies.json` и собирает карточки товаров по списку SKU в `products.csv`.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate         
pip install -r requirements.txt
```

Для входа через `channel="chrome"` нужен установленный обычный Google Chrome - Playwright использует его напрямую. Если Chrome не найден, скрипт сам откатится на Chromium от Playwright, но тогда нужно один раз выполнить:

```bash
playwright install chromium
```

## Gmail API

1. В [Google Cloud Console](https://console.cloud.google.com/) включить Gmail API.
2. Создать OAuth client ID типа Desktop app, скачать JSON и положить рядом со скриптами как `credentials.json`.
3. При первом запуске `get_cookies.py` откроется браузер для входа в Google и подтверждения доступа на чтение почты - после этого рядом появится `token.json`, и дальше он переиспользуется без повторного входа.

`credentials.json`, `token.json` и `cookies.json` - не для git (уже в `.gitignore`): в них секреты и сессия конкретного пользователя.

## Запуск

```bash
export OZON_PHONE=79001234567    # Windows PowerShell: $env:OZON_PHONE = "79001234567"
python get_cookies.py
python parse_ozon.py
```

Номер должен быть от аккаунта Ozon, на который приходит код подтверждения именно на почту (не SMS) - иначе `get_cookies.py` не найдёт письмо и упадёт по таймауту. Формат номера не важен - скрипт сам берёт последние 10 цифр.

Если антибот Ozon покажет страницу проверки, скрипт остановится и попросит пройти её вручную в открывшемся окне браузера. Есть и полностью ручной режим:

```bash
python get_cookies.py --manual   # вход руками, скрипт только сохранит cookies
```

## Результат

`parse_ozon.py` пишет `products.csv` с колонками:

`sku, title, price, rating, reviews_total, cover_image, photos_seller, videos_seller, color, material, art_set, has_rich_content, error`

Если по конкретному SKU что-то пошло не так, строка всё равно попадёт в CSV - с заполненным `sku` и текстом ошибки в `error`, остальные поля пустые. Это ожидаемое поведение: ошибка по одному товару не должна останавливать весь список.

## Как достаются данные

Ozon кладёт состояние страницы в JSON внутри HTML:

```html
<div id="state-webPrice-3121879-default-1" data-state="{&quot;price&quot;:&quot;1 299 ₽&quot;}"></div>
```

Тот же JSON отдаёт внутренний эндпоинт `/api/entrypoint-api.bx/page/json/v2?url=/product/{sku}/` - парсер идёт туда, а разбор HTML оставлен как запасной путь на случай, если эндпоинт не ответит. Имена виджетов ищутся по подстроке, потому что у них случайный хвост (`-3121879-default-1`).

Поля: `title` - `webProductHeading`, `price` - `webPrice`, рейтинг и отзывы - `webReviewProductScore`, фото и видео - `webGallery`, цвет/материал/артикул - `webShortCharacteristics`, `has_rich_content` - картинки, таблицы или списки в `webDescription`.
