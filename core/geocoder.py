"""
core/geocoder.py — преобразование адреса в географические координаты.

Первичный источник: открытый API Почты России (geo.pochta.ru) —
работает по любому адресу РФ без авторизации, отдаёт precision (exact/number/near).
Резерв: Nominatim (OpenStreetMap) — на случай если Почта РФ не нашла адрес.

Использование:
    from core.geocoder import geocode
    lat, lon, precision = geocode("Омск, проспект Мира, 46")
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests

import config

log = logging.getLogger("geocoder")

# Эндпоинт списка доступных городов (регионов рассылки) Почты России.
POCHTA_DELIVERY_AREAS = config.POCHTA_BASE + "/api/delivery-area/find-active"

# Кэш списка городов, чтобы не запрашивать API при каждом рендере UI.
_cities_cache: Optional[List[str]] = None


class GeocodeError(Exception):
    """Адрес не удалось геокодировать ни одним из провайдеров."""


def _geocode_pochta(address: str) -> Optional[dict]:
    """Геокодирование через Почту России. Возвращает dict или None."""
    start = time.monotonic()
    log.info("POCHTA geocode request: address=%r", address)
    try:
        resp = requests.get(
            config.POCHTA_GEOCODE,
            params={"addressString": address},
            timeout=config.POCHTA_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        elapsed = time.monotonic() - start
        log.info("POCHTA geocode response: status=%s, elapsed=%.2fs, body_len=%s",
                 resp.status_code, elapsed, len(resp.content))
        resp.raise_for_status()
        data = resp.json()
        if not data:
            log.warning("POCHTA geocode: empty result for %r (%.2fs)", address, elapsed)
            return None
        hit = data[0]
        geo = hit.get("geoLocation", {})
        if "lat" not in geo or "lon" not in geo:
            log.warning("POCHTA geocode: no coords in first hit for %r (%.2fs)", address, elapsed)
            return None
        result = {
            "lat": float(geo["lat"]),
            "lon": float(geo["lon"]),
            "precision": hit.get("precision", "unknown"),
            "normalized": hit.get("addressByGeoProvider", ""),
            "source": "pochta",
        }
        log.info("POCHTA geocode success: lat=%.5f, lon=%.5f, precision=%s, elapsed=%.2fs",
                 result["lat"], result["lon"], result["precision"], elapsed)
        return result
    except (requests.RequestException, ValueError, KeyError) as e:
        elapsed = time.monotonic() - start
        log.warning("POCHTA geocode error for %r: %s (elapsed=%.2fs)", address, e, elapsed)
        return None


def _geocode_nominatim(address: str) -> Optional[dict]:
    """Резервный геокодер: Nominatim (OpenStreetMap)."""
    start = time.monotonic()
    log.info("NOMINATIM geocode request: address=%r", address)
    try:
        resp = requests.get(
            config.NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "ru"},
            timeout=config.NOMINATIM_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        elapsed = time.monotonic() - start
        log.info("NOMINATIM geocode response: status=%s, elapsed=%.2fs, body_len=%s",
                 resp.status_code, elapsed, len(resp.content))
        resp.raise_for_status()
        data = resp.json()
        if not data:
            log.warning("NOMINATIM geocode: empty result for %r (%.2fs)", address, elapsed)
            return None
        hit = data[0]
        result = {
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "precision": "exact" if hit.get("class") == "highway" or "house" in str(hit.get("type", "")) else "near",
            "normalized": hit.get("display_name", ""),
            "source": "nominatim",
        }
        log.info("NOMINATIM geocode success: lat=%.5f, lon=%.5f, precision=%s, elapsed=%.2fs",
                 result["lat"], result["lon"], result["precision"], elapsed)
        return result
    except (requests.RequestException, ValueError, KeyError) as e:
        elapsed = time.monotonic() - start
        log.warning("NOMINATIM geocode error for %r: %s (elapsed=%.2fs)", address, e, elapsed)
        return None


def geocode(address: str) -> dict:
    """
    Преобразовать адрес в координаты.

    Сначала пробует Почту России, при неудаче — Nominatim.
    Поднимает GeocodeError, если ни один провайдер не сработал.

    Возвращает dict:
        {lat, lon, precision, normalized, source, imprecise}
        imprecise=True — адрес найден приблизительно (может не существовать)
    """
    address = address.strip()
    if not address:
        raise GeocodeError("Пустой адрес")

    log.info("GEOCODE start: address=%r", address)

    # 1) Почта России — основной провайдер (лучше по РФ)
    result = _geocode_pochta(address)
    if result is not None:
        is_imprecise = result["precision"] not in ("exact",)
        result["imprecise"] = is_imprecise
        if is_imprecise:
            log.warning("GEOCODE imprecise via pochta: %r, precision=%s", address, result["precision"])
        else:
            log.info("GEOCODE done via pochta: %r → (%.5f, %.5f)", address, result["lat"], result["lon"])
        return result

    # 2) Nominatim — резерв
    result = _geocode_nominatim(address)
    if result is not None:
        # Nominatim часто находит улицу, даже если дома нет; считаем imprecise
        is_imprecise = result["precision"] != "exact"
        result["imprecise"] = is_imprecise
        if is_imprecise:
            log.warning("GEOCODE imprecise via nominatim: %r, precision=%s — адрес может не существовать",
                        address, result["precision"])
        else:
            log.info("GEOCODE done via nominatim: %r → (%.5f, %.5f)", address, result["lat"], result["lon"])
        return result

    log.error("GEOCODE failed: %r — ни один провайдер не вернул координаты", address)
    raise GeocodeError(f"Адрес не найден ни одним геокодером: {address!r}")


def geocode_safe(address: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Безопасная обёртка: возвращает (result, error).
    result — dict геокодинга или None; error — текст ошибки или None.
    """
    try:
        return geocode(address), None
    except GeocodeError as e:
        return None, str(e)


def get_available_cities(use_cache: bool = True) -> List[str]:
    """
    Получить список городов, доступных в сервисе geo.pochta.ru.

    Источник: GET /api/delivery-area/find-active — возвращает ~103 региона
    рассылки с полями id, name, lat, lon. Дубликатов по name нет.

    Результат кэшируется в модуле (use_cache=True), чтобы не дёргать API
    при каждом рендере Streamlit. Возвращает список имён городов,
    отсортированный по алфавиту.

    При ошибке сети возвращает запасной список ключевых городов,
    чтобы UI продолжал работать.
    """
    global _cities_cache
    if use_cache and _cities_cache is not None:
        return _cities_cache

    try:
        resp = requests.get(
            POCHTA_DELIVERY_AREAS,
            timeout=config.POCHTA_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
        # Берём только активные регионы с непустым именем, убираем дубли.
        seen = set()
        cities = []
        for area in data:
            if not area.get("active", True):
                continue
            name = area.get("name", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cities.append(name)
        cities.sort()
    except (requests.RequestException, ValueError):
        # Запасной список — чтобы UI не падал при отсутствии сети.
        cities = ["Москва", "Санкт-Петербург", "Омск", "Новосибирск",
                  "Екатеринбург", "Казань", "Новосибирск", "Краснодар"]

    _cities_cache = cities
    return cities
