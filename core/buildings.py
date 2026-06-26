"""
core/buildings.py — дома и квартиры в радиусе от точки.

Источник: открытый API Почты России (geo.pochta.ru)
    GET /api/address-search/in-circle?centerLat=&centerLon=&radius=
Возвращает список зданий; у каждого есть поле flats (количество квартир).

Важная деталь: flats == 1 трактуется как «нет данных по жилому фонду»
(так сделано в самом фронтенде сервиса — findAddressesWithOneFlat),
поэтому такие здания исключаются из жилого фонда при подсчёте.
"""
from __future__ import annotations

import logging
import time
from typing import List

import requests

import config

log = logging.getLogger("buildings")


def get_buildings_in_circle(lat: float, lon: float, radius: int = 500) -> List[dict]:
    """
    Получить здания в радиусе `radius` метров от точки (lat, lon).

    Возвращает список объектов здания в исходном виде API Почты России:
        {
          address: {...},
          geoLocation: {lat, lon},
          geoLocationPrecision: "exact" | "number" | "near",
          verifydata: {...},
          flats: int,
        }
    """
    start = time.monotonic()
    log.info("POCHTA in-circle request: lat=%.5f, lon=%.5f, radius=%d", lat, lon, radius)
    resp = requests.get(
        config.POCHTA_IN_CIRCLE,
        params={"centerLat": lat, "centerLon": lon, "radius": radius},
        timeout=config.POCHTA_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
    )
    elapsed = time.monotonic() - start
    log.info("POCHTA in-circle response: status=%s, elapsed=%.2fs, body_len=%s",
             resp.status_code, elapsed, len(resp.content))
    resp.raise_for_status()
    data = resp.json()
    count = len(data) if isinstance(data, list) else 0
    log.info("POCHTA in-circle result: %d buildings in radius %d (%.2fs)", count, radius, elapsed)
    return data if isinstance(data, list) else []


def is_residential(building: dict) -> bool:
    """
    Жилое ли здание (т.е. по нему есть данные о квартирах).
    flats == 1 — заглушка «нет данных», такие здания не считаем жилыми.
    """
    flats = building.get("flats", 0)
    return flats is not None and flats > 1


def summarize_buildings(buildings: List[dict]) -> dict:
    """
    Свести список зданий в сводку по жилому фонду.

    Возвращает dict:
        {
          total_buildings: int,    — всего зданий в радиусе
          residential: int,        — жилых (с известным числом квартир)
          total_flats: int,        — суммарно квартир (по жилым)
          no_data: int,            — зданий без данных (flats=1)
        }
    """
    total = len(buildings)
    residential = [b for b in buildings if is_residential(b)]
    total_flats = sum(b.get("flats", 0) for b in residential)
    no_data = total - len(residential)
    return {
        "total_buildings": total,
        "residential": len(residential),
        "total_flats": total_flats,
        "no_data": no_data,
    }
