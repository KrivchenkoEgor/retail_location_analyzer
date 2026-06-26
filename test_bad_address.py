"""
Тест: что происходит при вводе несуществующего адреса.
Запуск: python test_bad_address.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import analyzer

# Тест 1: Несуществующий номер дома на существующей улице
# Тест 2: Полностью несуществующий адрес
# Тест 3: Обычный рабочий адрес для сравнения

test_cases = [
    ("Несущ. дом на существующей улице", "Новосибирск, улица Бориса Богаткова, 1"),
    ("Полностью несущ. адрес", "Новосибирск, вымышленная улица Космическая, 999"),
    ("Обычный рабочий адрес", "Омск, проспект Мира, 46"),
]

for label, addr in test_cases:
    print("=" * 70)
    print(f"ТЕСТ: {label}")
    print(f"Адрес: {addr!r}")
    print("=" * 70)

    t_start = time.monotonic()
    results = analyzer.analyze_many([addr], sleep_between=0)
    t_total = time.monotonic() - t_start

    for r in results:
        print(f"  OK: {r.get('ok')}")
        if r.get("error"):
            print(f"  Ошибка: {r['error']}")
        if r.get("ok"):
            print(f"  Координаты: {r.get('lat')}, {r.get('lon')} ({r.get('geo_source')})")
            print(f"  Точность: {r.get('precision')}")
            print(f"  Нормализованный: {r.get('normalized_address')}")
            print(f"  Зданий всего: {r.get('buildings_summary', {}).get('total_buildings', 0)}")
            print(f"  Квартир: {r.get('buildings_summary', {}).get('total_flats', 0)}")
            print(f"  Конкурентов: {r.get('competitors_count', 0)}")
    print(f"  Время: {t_total:.1f}s")
    print()
