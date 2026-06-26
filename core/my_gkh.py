"""
core/my_gkh.py — обогащение данных о торговой точке через портал my-gkh.ru.

Для произвольного адреса в РФ находит:
  — характеристики дома: год постройки, этажность, материал стен, площадь
  — управляющую компанию (телефон, email)
  — поставщиков коммунальных ресурсов
  — план капитального ремонта
  — координаты с карты Яндекса

Поток:
  1. POST /housejsonsearchregioncity/novosibirск с bounds вокруг точки
  2. Матчинг дома по адресу
  3. GET /gethouse/{id} → полная информация
  4. Парсинг HTML → структурированный dict

При ошибках любого шага возвращается пустой dict — анализ продолжается.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from typing import Dict, List, Optional

import requests

import config

log = logging.getLogger("my_gkh")

# Сессия с общими заголовками — единая для POST и GET, чтобы капча не срабатывала
_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        _SESSION = s
    return _SESSION


def _clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&quot;', '"').replace('&#x2B;', '+').replace('&amp;', '&')
    s = s.replace('&#xA0;', ' ').replace('\u00a0', ' ').replace('&nbsp;', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _has_captcha(html: str) -> bool:
    """Проверить, вернул ли сервер страницу с капчей."""
    return len(html) < 10000 and "captcha" in html.lower()


def _extract_city_slug(address: str) -> str:
    """Извлечь город из адреса и вернуть slug для API my-gkh.ru."""
    a = address.lower()
    # "г Город" or "город Город" or "г.Город"
    m = re.search(r'(?:^|,\s*)(?:город\s+|г\.?\s*)([а-яё\-]+(?:-[а-яё]+)*)', a)
    if m:
        city = m.group(1).strip('.').strip()
        slug = config.MYGKH_CITY_SLUGS.get(city)
        if slug:
            return slug
        # transliteration fallback
        table = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
            'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i',
            'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
            'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
            'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
            'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '',
            'э': 'e', 'ю': 'yu', 'я': 'ya', '-': '-',
        }
        slug = ''.join(table.get(ch, ch) for ch in city)
        slug = re.sub(r'_+', '-', slug).strip('-')
        if slug:
            log.info("MYGKH city slug: %s → %s (transliterated)", city, slug)
            return slug
    log.info("MYGKH city slug: not found in %r, fallback to novosibirsk", address)
    return "novosibirsk"


def _find_houses(lat: float, lng: float, address: str = "") -> List[dict]:
    """Ищет дома рядом с координатами через API my-gkh.ru (GeoJSON)."""
    city_slug = _extract_city_slug(address)
    houses_api = config.MYGKH_HOUSES_API_TPL.format(city=city_slug)
    r = config.MYGKH_BOUNDS_RADIUS
    bounds = [[lat - r, lng - r], [lat + r, lng + r]]
    log.info("MYGKH houses: city=%s lat=%.5f lng=%.5f bounds=%s", city_slug, lat, lng, bounds)
    try:
        s = _get_session()
        s.get(config.MYGKH_BASE, timeout=config.MYGKH_TIMEOUT)
        resp = s.post(
            houses_api,
            data={
                "bounds": str(bounds).replace("'", '"'),
                "isMobileBrowser": "False",
                "roleId": "0",
            },
            timeout=config.MYGKH_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        resp.raise_for_status()
        if _has_captcha(resp.text):
            log.warning("MYGKH houses: captcha blocked")
            return []
        features = resp.json().get("features", [])
        log.info("MYGKH houses: %d features", len(features))
        return features
    except Exception as e:
        log.warning("MYGKH houses: %s", e)
        return []


def _normalize_address(a: str) -> str:
    """Привести адрес к единому формату для сравнения."""
    a = a.lower()
    # remove postal code prefix like "630009, Россия,"
    a = re.sub(r'^\d{6}\s*,?\s*россия\s*,?\s*', '', a)
    a = re.sub(r'[^а-яёa-z0-9\s/]', '', a)
    a = re.sub(r'\s+', ' ', a).strip()
    # "д111" or "д 111" → "111" (remove prefix letter before house num)
    a = re.sub(r'\bд\s*(\d)', r'\1', a)
    return a


def _match_house(features: List[dict], address: str) -> Optional[dict]:
    """Матчит дом по адресу среди features (нормализованное сравнение)."""
    addr_norm = _normalize_address(address)

    best = None
    best_score = 0

    for f in features:
        p = f.get("properties", {})
        ha_norm = _normalize_address(p.get("address", ""))

        if ha_norm in addr_norm or addr_norm in ha_norm:
            score = min(len(ha_norm), len(addr_norm))
            if score > best_score:
                best_score = score
                best = f
    return best


def _parse_house_html(html: str) -> dict:
    """Парсит /gethouse/{id} → структурированный dict."""
    r: dict = {}

    m = re.search(r'<h1[^>]*>\s*([^<]+?)\s*</h1>', html)
    if m:
        r["address"] = _clean(m.group(1))

    m = re.search(r'Дом находится под управлением\s*<a[^>]*>\s*([^<]+?)\s*</a>', html)
    if m:
        r["management_company"] = _clean(m.group(1))

    m = re.search(r'c\s+(\d+\s+\S+\s+\S+)', html)
    if m:
        r["management_since"] = _clean(m.group(1))

    m = re.search(r'Здание построено в (\d+) году', html)
    if m:
        r["year_built"] = int(m.group(1))

    m = re.search(r'имеет\s+([\d-]+)\s+этаж', html)
    if m:
        r["floors"] = m.group(1)  # может быть "18" или "4-11-19"

    m = re.search(r'(\d+)\s+жил[ыо]х?\s*помещени', html)
    if m:
        r["living_spaces"] = int(m.group(1))

    m = re.search(r'общая площадь всех помещений МКД составляет\s*([\d\s,.]+)\s*кв\.м', html)
    if m:
        r["total_area_sqm"] = _clean(m.group(1))

    chars: Dict[str, str] = {}
    # Секция характеристик — первый <ul class="list-texts"> до "Информация об управлении"
    chars_section = re.search(
        r'Общая характеристика(.*?)(?:Информация об управлении|$)',
        html, re.DOTALL
    )
    if chars_section:
        for ul in re.finditer(r'<ul class="list-texts[^"]*">(.*?)</ul>', chars_section.group(1), re.DOTALL):
            for m in re.finditer(
                r'<li[^>]*>.*?<b[^>]*>(.*?)</b>\s*<span[^>]*>(.*?)</span>',
                ul.group(1), re.DOTALL
            ):
                label = _clean(m.group(1)).rstrip(':')
                val = _clean(m.group(2))
                if val and val != '-' and 'сведения отсутствуют' not in val.lower():
                    chars[label] = val
        # Конструктивные элементы под характеристиками (не в ul, но в том же блоке)
        for m in re.finditer(
            r'<b[^>]*>(Тип[^<]+)</b>\s*<span[^>]*>(.*?)</span>',
            chars_section.group(1), re.DOTALL
        ):
            label = _clean(m.group(1)).rstrip(':')
            val = _clean(m.group(2))
            if val and val != '-' and 'сведения отсутствуют' not in val.lower():
                chars[label] = val
    if chars:
        r["characteristics"] = chars
        for k, v in chars.items():
            if 'серия' in k.lower() or 'тип постройки' in k.lower():
                parts = [x.strip() for x in v.split(',', 1)]
                r["building_series"] = parts[0]
                if len(parts) > 1:
                    r["building_material"] = parts[1]
        # Fallback: достаём из таблицы то, что не спарсилось из описания
        chars_lower = {k.lower(): v for k, v in chars.items()}
        if 'floors' not in r and 'количество этажей' in chars_lower:
            r['floors'] = chars_lower['количество этажей']
        if 'total_area_sqm' not in r:
            for k, v in chars_lower.items():
                if 'общая площадь дома' in k:
                    r['total_area_sqm'] = v
                    break

    mgmt: Dict[str, str] = {}
    mgmt_sec = re.search(r'Информация об управлении(.*?)(?:Отчеты|Поставщики)', html, re.DOTALL)
    if mgmt_sec:
        for m in re.finditer(
            r'<li[^>]*>\s*<b[^>]*>(.*?)</b>\s*<span[^>]*>(.*?)</span>\s*</li>',
            mgmt_sec.group(1), re.DOTALL
        ):
            label = _clean(m.group(1)).rstrip(':')
            val = _clean(m.group(2))
            if val:
                mgmt[label] = val
    if mgmt:
        r["management"] = mgmt

    utils_sec = re.search(r'Поставщики коммунальных ресурсов(.*?)(?:Региональная программа|Выполняемые работы|$)', html, re.DOTALL)
    if utils_sec:
        utils = re.findall(
            r'<a[^>]*href="/getorganization/[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
            utils_sec.group()
        )
        if utils:
            r["utility_providers"] = [_clean(u) for u in utils]

    m = re.search(r'center:\s*\[([\d.]+),\s*([\d.]+)\]', html)
    if m:
        r["coordinates"] = {"lat": float(m.group(1)), "lng": float(m.group(2))}

    return r


# ---------------------------------------------------------------------------
# Kimi WebBridge — обход капчи через браузер
# ---------------------------------------------------------------------------
_WEBBRIDGE_URL = "http://127.0.0.1:10086/command"


def _webbridge_request(action: str, args: dict, timeout: int = 15) -> Optional[dict]:
    """Выполнить команду к kimi-webbridge."""
    try:
        resp = requests.post(
            _WEBBRIDGE_URL,
            json={"session": "mygkh", "action": action, "args": args},
            timeout=timeout,
        )
        return resp.json()
    except Exception as e:
        log.warning("MYGKH webbridge %s: %s", action, e)
        return None


def _solve_captcha_via_browser(house_id: str) -> Optional[str]:
    """Решить капчу слайдер через kimi-webbridge и вернуть HTML страницы."""
    url = f"{config.MYGKH_HOUSE_INFO}/{house_id}"
    log.info("MYGKH browser: navigate to %s", url)

    r = _webbridge_request("navigate", {"url": url, "newTab": True}, timeout=25)
    if not r or not r.get("data", {}).get("success"):
        log.warning("MYGKH browser: navigate failed")
        return None

    time.sleep(2)

    # Проверяем, есть ли капча
    r = _webbridge_request("evaluate", {
        "code": "document.getElementById('sliderThumb') ? true : false"
    })
    has_captcha = r and r.get("data", {}).get("value") == True

    if has_captcha:
        log.info("MYGKH browser: solving slider captcha")
        js_solve = (
            "(function(){"
            "var t=document.getElementById('sliderThumb');"
            "var r=document.getElementById('sliderTrack');"
            "if(!t||!r)return'fail';"
            "var a=r.getBoundingClientRect(),e=t.getBoundingClientRect();"
            "var s=e.left+e.width/2,o=e.top+e.height/2;"
            "var i=a.left+a.width-e.width/2,c=o;"
            "t.dispatchEvent(new MouseEvent('mousedown',{clientX:s,clientY:o,bubbles:true,cancelable:true}));"
            "for(var n=1;n<=15;n++){"
            "var l=s+(i-s)*(n/15);"
            "document.dispatchEvent(new MouseEvent('mousemove',{clientX:l,clientY:c,bubbles:true,cancelable:true}))"
            "}"
            "document.dispatchEvent(new MouseEvent('mouseup',{clientX:i,clientY:c,bubbles:true,cancelable:true}));"
            "return'done'"
            "})()"
        )
        r = _webbridge_request("evaluate", {"code": js_solve})
        r_val = r.get("data", {}).get("value") if r else None
        log.info("MYGKH browser: solve result=%s", r_val)
        time.sleep(2)
    else:
        log.info("MYGKH browser: no captcha detected")

    # Получаем HTML
    r = _webbridge_request("evaluate", {
        "code": "document.documentElement.outerHTML"
    }, timeout=20)
    html = r.get("data", {}).get("value") if r else None
    if html:
        log.info("MYGKH browser: got HTML (%d chars)", len(html))
    else:
        log.warning("MYGKH browser: failed to get HTML")
    return html


def enrich(address: str, normalized_address: str, lat: float, lng: float) -> dict:
    """
    Обогатить данные адреса информацией с my-gkh.ru.

    Возвращает dict с полями:
      house_id, address, year_built, floors, living_spaces, total_area_sqm,
      building_series, building_material, management_company, management_since,
      management (dict), utility_providers, characteristics (dict), coordinates, organization_name
    или пустой dict при ошибке.
    """
    start = time.monotonic()
    log.info("MYGKH enrich: %r (%.5f, %.5f)", address, lat, lng)

    features = _find_houses(lat, lng, normalized_address or address)
    if not features:
        log.info("MYGKH enrich: no houses near (%.5f, %.5f)", lat, lng)
        return {}

    matched = _match_house(features, (normalized_address or address))
    if not matched:
        log.info("MYGKH enrich: no match for %r among %d houses", address, len(features))
        return {}

    props = matched.get("properties", {})
    house_id = props.get("id")
    if not house_id:
        log.warning("MYGKH enrich: matched feature has no id")
        return {}

    log.info("MYGKH enrich: matched house_id=%s, addr=%s, org=%s",
             house_id, props.get("address"), props.get("organizationName"))

    # Пробуем получить детальную информацию
    details_ok = False
    html = None

    # 3a) Быстрый HTTP-запрос (работает, если нет капчи)
    try:
        s = _get_session()
        resp = s.get(
            f"{config.MYGKH_HOUSE_INFO}/{house_id}",
            timeout=config.MYGKH_TIMEOUT,
        )
        resp.raise_for_status()
        if not _has_captcha(resp.text):
            html = resp.text
        else:
            log.warning("MYGKH enrich: captcha on /gethouse/%s", house_id)
    except Exception as e:
        log.warning("MYGKH enrich: fetch /gethouse/%s: %s", house_id, e)

    # 3b) Если капча — пробуем через kimi-webbridge (решаем слайдер)
    if html is None:
        log.info("MYGKH enrich: trying browser captcha bypass for %s", house_id)
        html = _solve_captcha_via_browser(house_id)

    if html:
        result = _parse_house_html(html)
        details_ok = True

    if not details_ok:
        # Минимальные данные из houses API
        result = {}

    result["house_id"] = house_id
    result["organization_url"] = props.get("organizationUrl", "")
    result["organization_name"] = props.get("organizationName", "")

    elapsed = time.monotonic() - start
    log.info("MYGKH enrich: done (%.2fs) fields=%s", elapsed, list(result.keys()))
    return result
