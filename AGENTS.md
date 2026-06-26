# Retail Location Analyzer — LLM Context

## Project Overview

Streamlit-приложение для анализа торговых точек: геокодинг (Почта РФ / Nominatim),
поиск зданий и квартир (in-circle API Почты РФ), поиск конкурентов/офисов/образования
(Overpass API), демографическая модель (квартиры → жители), экспорт в Excel (openpyxl).

## Stack

| Компонент | Технология |
|---|---|
| UI | Streamlit |
| Геокодинг | geo.pochta.ru + nominatim.openstreetmap.org |
| Здания/квартиры | geo.pochta.ru (in-circle) |
| POI (магазины/офисы/школы) | Overpass API (OSM) |
| Демография | Собственная модель (распределение домохозяйств) |
| Обогащение | my-gkh.ru |
| Экспорт | openpyxl (6 листов + данные МКД) |

## Key Files

- `app.py` — Streamlit UI (ввод адресов, прогресс-бар, вкладки)
- `config.py` — все константы, таймауты, OSM-теги, дефолты демографии
- `core/geocoder.py` — геокодинг (Почта РФ → Nominatim fallback)
- `core/buildings.py` — здания и квартиры в радиусе
- `core/poi.py` — Overpass-запросы с retry по зеркалам
- `core/analyzer.py` — оркестратор (адрес → полный анализ)
- `core/demographics.py` — flats → residents
- `core/my_gkh.py` — обогащение через my-gkh.ru (см. CAPTCHA ниже)
- `exporters/excel_report.py` — генерация 7-листного Excel

## Overpass API

- Используются 4 зеркала с перебором при 429/504/таймауте
- Таймаут: 20с сетевой, 15с query timeout
- 1 retry на зеркало
- Пауза 10с между точками

## my-gkh.ru Enrichment & CAPTCHA Problem

### Что делает модуль

`core/my_gkh.py` обогащает данные о доме:
- POST `/housejsonsearchregioncity/novosibirsk` — GeoJSON всех домов в bounds (до 100)
- Match по адресу → получаем house_id, название УК, url организации
- GET `/gethouse/{house_id}` — парсим характеристики дома (год, этажи, материал, площадь, УК, поставщики)

### CAPTCHA

Сервер my-gkh.ru (IIS 10.0 / ASP.NET) имеет антибот-защиту:

| Эндпоинт | Статус |
|---|---|
| `POST /housejsonsearchregioncity/novosibirsk` | ✅ Всегда работает (JSON API) |
| `GET /gethouse/{id}` | ❌ Блокируется капчей при HTTP-запросах |
| `GET / (homepage)` | ❌ Блокируется капчей |

**Признак капчи**: response length < 10000 байт, в HTML есть слово "captcha".

**Тип капчи**: Слайдер ("Перетащите ползунок"), собственная реализация на JS.

### Неудачные попытки обхода

- `requests.Session()` с постоянными куками ❌
- Заголовки User-Agent браузера + Referer ❌
- Задержка 1.5–3с между запросами ❌
- Двойной GET с паузой при первой капче ❌
- `kimi-webbridge` (Chrome extension) — navigate к gethouse таймаутится (30с) ❌
- `kimi-webbridge evaluate` fetch — то же ❌

### Что нужно для обхода

Капча срабатывает на уровне IIS/ASP.NET до отдачи контента.
Вероятно, используется модуль:
- проверка `User-Agent` на browser-like
- проверка `Accept-Language`
- проверка TLS handshake (JA3 fingerprint)
- проверка наличия/отсутствия определённых JS-кук

**Слайдерная капча решается вручную** (пользователь проходит в браузере один раз,
после чего куки сессии работают ~некоторое время).

### Рекомендации для обхода

1. **Использовать реальный браузер** (Playwright/undetected-chromedriver) с:
   - --disable-blink-features=AutomationControlled
   - stealth.js
   - Реальные user-data-dir с решённой капчей (один раз решить, сохранить профиль)
2. **curl_cffi** — библиотека Python, имитирующая TLS-отпечатки реальных браузеров
3. **cloudscraper** — если сайт переедет на Cloudflare
4. **Скачать профиль Chrome** с solved CAPTCHA и переиспользовать
