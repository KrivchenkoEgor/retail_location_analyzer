"""
core/analyzer.py — оркестратор: один адрес → полный анализ одной точки.

Связывает геокодер → здания → POI → демографию в единый результат.
Также содержит пакетную обработку списка адресов с прогресс-колбэком
для UI (Streamlit прогресс-бар) и паузами между точками для Overpass.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Callable, Dict, List, Optional

import config
from core import buildings, demographics, geocoder, my_gkh, poi

log = logging.getLogger("analyzer")


def analyze_point(
    address: str,
    r_shops: int = config.DEFAULT_RADIUS_SHOPS,
    r_offices: int = config.DEFAULT_RADIUS_OFFICES,
    r_edu: int = config.DEFAULT_RADIUS_EDUCATION,
    avg_persons_per_flat: float = config.DEFAULT_AVG_PERSONS_PER_FLAT,
    single_share: float = config.DEFAULT_SINGLE_SHARE,
    household_dist: Optional[Dict[int, float]] = None,
) -> dict:
    """
    Полный анализ одной торговой точки по адресу.

    Шаги:
      1. Геокодинг адреса → (lat, lon).
      2. Здания/квартиры в радиусе r_shops (in-circle Почты РФ).
      3. Конкуренты/офисы/образование одним Overpass-запросом.
      4. Демография: квартиры → жители.

    Возвращает dict:
        {
          address, lat, lon, precision, geo_source,
          ok: bool, error: str|None,
          buildings_summary: {...},
          poi: {shops:[...], offices:[...], education:[...]},
          shops_by_category: {...},
          shop_brands: {бренд: кол-во},
          demographics: {...},
          residents_per_competitor: float,
        }
    """
    result = {
        "address": address,
        "ok": False,
        "error": None,
    }

    overall_start = time.monotonic()
    log.info("=" * 60)
    log.info("ANALYZE start: address=%r, r_shops=%d, r_offices=%d, r_edu=%d",
             address, r_shops, r_offices, r_edu)

    # 1) Геокодинг
    t0 = time.monotonic()
    try:
        geo = geocoder.geocode(address)
    except geocoder.GeocodeError as e:
        elapsed = time.monotonic() - t0
        log.error("ANALYZE failed at geocoding: %r — %s (%.2fs)", address, e, elapsed)
        result["error"] = f"Геокодинг: {e}"
        return result

    log.info("ANALYZE step1 geocode: %.2fs → (%.5f, %.5f) via %s",
             time.monotonic() - t0, geo["lat"], geo["lon"], geo["source"])

    result.update({
        "lat": geo["lat"],
        "lon": geo["lon"],
        "precision": geo["precision"],
        "geo_source": geo["source"],
        "normalized_address": geo["normalized"],
        "geo_imprecise": geo.get("imprecise", False),
    })
    if geo.get("imprecise"):
        log.warning("ANALYZE imprecise geocode: %r — precision=%s, source=%s",
                     address, geo["precision"], geo["source"])

    # 1.5) Обогащение через my-gkh.ru (характеристики дома, УК, стройматериалы)
    t0 = time.monotonic()
    try:
        mygkh_data = my_gkh.enrich(address, geo.get("normalized", ""), geo["lat"], geo["lon"])
    except Exception as e:
        log.warning("ANALYZE my-gkh enrich error: %r — %s", address, e)
        mygkh_data = {}
    if mygkh_data:
        log.info("ANALYZE step1.5 my-gkh: %.2fs → year=%s, floors=%s, mgmt=%s",
                 time.monotonic() - t0,
                 mygkh_data.get("year_built"), mygkh_data.get("floors"),
                 mygkh_data.get("management_company"))
    else:
        log.info("ANALYZE step1.5 my-gkh: %.2fs → no data", time.monotonic() - t0)
    result["mygkh"] = mygkh_data

    # 2) Здания и квартиры в радиусе (используем r_shops как охват жилой зоны)
    t0 = time.monotonic()
    try:
        bld = buildings.get_buildings_in_circle(geo["lat"], geo["lon"], radius=r_shops)
        bld_summary = buildings.summarize_buildings(bld)
    except Exception as e:
        elapsed = time.monotonic() - t0
        log.warning("ANALYZE buildings error: %r — %s (%.2fs), continuing", address, e, elapsed)
        # продолжаем — POI могут быть доступны даже если Почта РФ упала
        bld = []
        bld_summary = {"total_buildings": 0, "residential": 0, "total_flats": 0, "no_data": 0}

    log.info("ANALYZE step2 buildings: %.2fs → %d buildings, %d flats",
             time.monotonic() - t0, bld_summary["total_buildings"], bld_summary["total_flats"])

    result["buildings_summary"] = bld_summary
    result["buildings_raw"] = bld

    # 3) POI (конкуренты / офисы / образование) одним запросом
    t0 = time.monotonic()
    poi_data = poi.find_poi_near(geo["lat"], geo["lon"], r_shops, r_offices, r_edu)
    shops_by_cat = poi.categorize_shops(poi_data["shops"])

    log.info("ANALYZE step3 poi: %.2fs → %d shops, %d offices, %d education",
             time.monotonic() - t0,
             len(poi_data["shops"]), len(poi_data["offices"]), len(poi_data["education"]))

    # Группировка конкурентов по бренду
    brand_counts: Dict[str, int] = {}
    for s in poi_data["shops"]:
        brand = s["brand"]
        brand_counts[brand] = brand_counts.get(brand, 0) + 1
    # Сортировка по убыванию числа точек
    brand_counts = dict(sorted(brand_counts.items(), key=lambda kv: -kv[1]))

    result["poi"] = poi_data
    result["shops_by_category"] = shops_by_cat
    result["shop_brands"] = brand_counts
    result["competitors_count"] = len(poi_data["shops"])

    # 4) Демография
    t0 = time.monotonic()
    demo = demographics.compute_population(
        flats=bld_summary["total_flats"],
        avg_persons_per_flat=avg_persons_per_flat,
        single_share=single_share,
        household_dist=household_dist,
    )
    result["demographics"] = demo
    result["residents_per_competitor"] = demographics.residents_per_competitor(
        demo["corrected_residents"], result["competitors_count"]
    )
    log.info("ANALYZE step4 demographics: %.2fs → %d corrected residents",
             time.monotonic() - t0, demo["corrected_residents"])

    overall_elapsed = time.monotonic() - overall_start
    log.info("ANALYZE done: %r — OK, %.2fs total", address, overall_elapsed)

    result["ok"] = True
    return result


def analyze_many(
    addresses: List[str],
    progress_cb: Optional[Callable[[int, int, dict], None]] = None,
    r_shops: int = config.DEFAULT_RADIUS_SHOPS,
    r_offices: int = config.DEFAULT_RADIUS_OFFICES,
    r_edu: int = config.DEFAULT_RADIUS_EDUCATION,
    avg_persons_per_flat: float = config.DEFAULT_AVG_PERSONS_PER_FLAT,
    single_share: float = config.DEFAULT_SINGLE_SHARE,
    household_dist: Optional[Dict[int, float]] = None,
    sleep_between: float = config.OVERPASS_SLEEP_BETWEEN_POINTS,
) -> List[dict]:
    """
    Пакетный анализ списка адресов.

    progress_cb(index, total, result) — колбэк для обновления UI
    (например, Streamlit progress bar). Вызывается после каждой точки.

    Между точками делается пауза sleep_between секунд, чтобы не словить
    429 от Overpass (внутри analyze_point уже есть retry, но пауза снижает риск).
    """
    total = len(addresses)
    log.info("=== ANALYZE_MANY: %d addresses, r_shops=%d, r_offices=%d, r_edu=%d, sleep=%.1fs ===",
             total, r_shops, r_offices, r_edu, sleep_between)
    results: List[dict] = []
    pool = ThreadPoolExecutor(max_workers=1)
    for i, address in enumerate(addresses):
        log.info("--- Point %d/%d: %r ---", i + 1, total, address)
        future = pool.submit(analyze_point, address,
                             r_shops=r_shops, r_offices=r_offices, r_edu=r_edu,
                             avg_persons_per_flat=avg_persons_per_flat,
                             single_share=single_share, household_dist=household_dist)
        try:
            res = future.result(timeout=config.POINT_TIMEOUT)
        except FuturesTimeout:
            log.error("Point %d/%d TIMEOUT (%ds): %r", i + 1, total, config.POINT_TIMEOUT, address)
            res = {
                "address": address, "ok": False,
                "error": f"Таймаут {config.POINT_TIMEOUT}с — сервера не ответили вовремя",
            }
        results.append(res)
        if progress_cb:
            progress_cb(i + 1, total, res)
        if not res.get("ok"):
            log.warning("Point %d/%d FAILED: %r — %s", i + 1, total, address, res.get("error", "unknown"))
        # Пауза между точками, кроме последней
        if i < total - 1 and sleep_between > 0:
            log.info("Sleeping %.1fs between points...", sleep_between)
            time.sleep(sleep_between)
    pool.shutdown(wait=False)
    log.info("=== ANALYZE_MANY done: %d/%d OK ===",
             sum(1 for r in results if r.get("ok")), total)
    return results
