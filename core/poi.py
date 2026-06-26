"""
core/poi.py — поиск объектов (POI) в радиусе через Overpass API (OpenStreetMap).

Единый запрос на точку возвращает сразу три категории:
  - shops      — продуктовые конкуренты (R=500м по умолчанию)
  - offices    — офисы (R=100м)
  - education  — ВУЗы, колледжи, ПТУ/техникумы/училища (R=150м)

Особенности:
  * Перебор зеркал Overpass + retry при 429/504 с экспоненциальной задержкой.
  * nwr (node|way|relation) в одном Overpass QL union — один запрос вместо трёх.
  * Классификация по тегам в Python; дедупликация по (type, id).
  * ПТУ ловятся через name~"(колледж|техникум|училище|пту)" (в OSM нет спецтега).
"""
from __future__ import annotations

import logging
import time
from math import radians, sin, cos, sqrt, atan2
from typing import Dict, List, Optional

import requests

import config

log = logging.getLogger("poi")


# ---------------------------------------------------------------------------
# Вспомогательное: расстояние между двумя точками (метры)
# ---------------------------------------------------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по дуге большого круга в метрах."""
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


# ---------------------------------------------------------------------------
# Низкоуровневый запрос к Overpass с перебором зеркал и retry
# ---------------------------------------------------------------------------
def _query_overpass(query: str) -> Optional[dict]:
    """
    Выполнить Overpass QL запрос.

    Перебирает зеркала из config.OVERPASS_MIRRORS; на каждом делает до
    OVERPASS_RETRIES попыток с экспоненциальной задержкой при 429/504/ошибках.
    Возвращает распарсенный JSON {elements:[...]} или None при полной неудаче.
    """
    payload = {"data": query}
    query_preview = query[:120].replace("\n", " ")

    log.info("OVERPAST query start (first 120 chars): %s", query_preview)

    for mirror in config.OVERPASS_MIRRORS:
        for attempt in range(1, config.OVERPASS_RETRIES + 1):
            start = time.monotonic()
            log.info("OVERPAST request: mirror=%s, attempt=%d/%d", mirror, attempt, config.OVERPASS_RETRIES)
            try:
                resp = requests.post(
                    mirror,
                    data=payload,
                    timeout=config.OVERPASS_TIMEOUT,
                    headers={"User-Agent": config.USER_AGENT},
                )
                elapsed = time.monotonic() - start
                log.info("OVERPAST response: mirror=%s, status=%s, elapsed=%.2fs, body_len=%s",
                         mirror, resp.status_code, elapsed, len(resp.content))

                # 429/504 — перегрузка сервера: ждём и повторяем
                if resp.status_code in (429, 504):
                    wait = 8 * attempt  # 8с, 16с — экспоненциальная задержка
                    log.warning("OVERPAST %s on %s, retrying in %ds", resp.status_code, mirror, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])
                log.info("OVERPAST success: mirror=%s, %d elements (%.2fs)", mirror, len(elements), elapsed)
                return data
            except (requests.RequestException, ValueError) as e:
                elapsed = time.monotonic() - start
                log.warning("OVERPAST error on %s (attempt %d): %s (elapsed=%.2fs)",
                            mirror, attempt, e, elapsed)
                # Сетевая ошибка / таймаут / невалидный JSON — пробуем снова
                if attempt < config.OVERPASS_RETRIES:
                    time.sleep(5 * attempt)
                continue
        # зеркало не ответило — переходим к следующему
    log.error("OVERPAST: все зеркала недоступны")
    return None


# ---------------------------------------------------------------------------
# Построение единого Overpass QL запроса для точки
# ---------------------------------------------------------------------------
def _build_unified_query(
    lat: float,
    lon: float,
    r_shops: int,
    r_offices: int,
    r_edu: int,
) -> str:
    """
    Сконструировать Overpass QL с одним union: магазины + офисы + образование.
    """
    shop_types = config.SHOP_TYPES
    edu_amenity = config.EDUCATION_AMENITY
    edu_name = config.EDUCATION_NAME_REGEX
    qt = config.OVERPASS_QUERY_TIMEOUT

    # nwr = node|way|relation — компактная запись вместо трёх блоков.
    # Каждый подзапрос — отдельная ветка union; все результаты сливаются.
    return f"""[out:json][timeout:{qt}];
(
  nwr["shop"~"^({shop_types})$"](around:{r_shops},{lat},{lon});
  nwr["office"](around:{r_offices},{lat},{lon});
  nwr["amenity"~"^({edu_amenity})$"](around:{r_edu},{lat},{lon});
  nwr["name"~"{edu_name}",i](around:{r_edu},{lat},{lon});
);
out center tags;"""


def _element_point(el: dict) -> tuple:
    """Получить (lat, lon) элемента OSM (node или center способа/отношения)."""
    if el["type"] == "node":
        return float(el["lat"]), float(el["lon"])
    center = el.get("center", {})
    return float(center.get("lat", 0)), float(center.get("lon", 0))


def _classify_element(el: dict, lat: float, lon: float) -> List[str]:
    """
    Определить, к каким категориям относится элемент.
    Один объект может относиться к нескольким (например, офис в учебном заведении).
    Возвращает список категорий: 'shops' | 'offices' | 'education'.
    """
    tags = el.get("tags", {})
    cats = []

    if "shop" in tags:
        cats.append("shops")
    if "office" in tags:
        cats.append("offices")

    name_lower = tags.get("name", "").lower()
    amenity = tags.get("amenity", "")
    is_edu_by_amenity = amenity in ("university", "college")
    is_edu_by_name = any(w in name_lower for w in ("колледж", "техникум", "училище", "пту", "политехникум"))
    if is_edu_by_amenity or is_edu_by_name:
        cats.append("education")

    return cats


# ---------------------------------------------------------------------------
# Публичный API модуля
# ---------------------------------------------------------------------------
def find_poi_near(
    lat: float,
    lon: float,
    r_shops: int = config.DEFAULT_RADIUS_SHOPS,
    r_offices: int = config.DEFAULT_RADIUS_OFFICES,
    r_edu: int = config.DEFAULT_RADIUS_EDUCATION,
) -> Dict[str, List[dict]]:
    """
    Найти конкурентов, офисы и учебные заведения рядом с точкой.

    Выполняет один запрос к Overpass и классифицирует результат.
    Возвращает dict с ключами 'shops', 'offices', 'education' — списки объектов.
    Каждый объект: {name, brand, category, shop_type, distance_m, tags}.

    При недоступности всех зеркал возвращает пустые списки (не падает).
    """
    query = _build_unified_query(lat, lon, r_shops, r_offices, r_edu)
    data = _query_overpass(query)

    result: Dict[str, List[dict]] = {"shops": [], "offices": [], "education": []}
    if not data:
        return result

    seen = set()  # дедупликация по (type, id)
    for el in data.get("elements", []):
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)

        elat, elon = _element_point(el)
        tags = el.get("tags", {})
        distance = haversine(lat, lon, elat, elon) if elat and elon else None

        record = {
            "name": tags.get("name", "(без названия)"),
            "brand": tags.get("brand") or tags.get("name", "(без названия)"),
            "shop_type": tags.get("shop", ""),
            "office_type": tags.get("office", ""),
            "amenity": tags.get("amenity", ""),
            "distance_m": round(distance) if distance is not None else None,
            "tags": tags,
        }

        for cat in _classify_element(el, lat, lon):
            result[cat].append(record)

    # Сортируем каждую категорию по удалённости
    for cat in result:
        result[cat].sort(key=lambda x: x["distance_m"] if x["distance_m"] is not None else 99999)

    return result


def categorize_shops(shops: List[dict]) -> Dict[str, List[dict]]:
    """
    Разнести магазины по человекочитаемым категориям (config.SHOP_CATEGORIES).
    Возвращает {категория: [записи]}.
    """
    # Обратное отображение: shop-тег -> категория
    tag_to_cat = {}
    for cat, tags in config.SHOP_CATEGORIES.items():
        for t in tags:
            tag_to_cat[t] = cat

    by_cat: Dict[str, List[dict]] = {cat: [] for cat in config.SHOP_CATEGORIES}
    for shop in shops:
        cat = tag_to_cat.get(shop["shop_type"], "Прочее")
        by_cat.setdefault(cat, []).append(shop)
    return {k: v for k, v in by_cat.items() if v}
