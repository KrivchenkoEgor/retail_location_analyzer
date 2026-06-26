"""
core/demographics.py — демографическая модель пересчёта квартир в жителей.

Воспроизводит логику из bf_house_and_apartments_analysis.xlsx (Омск):
  - base_residents    = квартиры × 2,3                 (столбец «≈ Жителей ср.2,3 чел/кв»)
  - corrected_residents = квартиры × 2,44              (столбец «≈ Жителей скорр.»)
  - детализация по составу домохозяйств: {1: 23,5%, 2: 30%, 3: 23%, 4: 15%, 5+: 8,5%}

Поправочный коэффициент 2,44/2,30 = 1,061 отражает «долю одиноких 28,5%»
и зашит как DEFAULT_CORRECTION_FACTOR. Если пользователь меняет avg или
single_share в UI, final_avg пересчитывается пропорционально.

Параметры приходят из UI (редактируемые), дефолты — из config.py.
"""
from __future__ import annotations

from typing import Dict

import config

# Фиксированный поправочный коэффициент для дефолтных значений Омска.
# 2,44 / 2,30 ≈ 1,0609. Привязан к доле одиноких 28,5%.
DEFAULT_CORRECTION_FACTOR = 1.061


def _compute_correction_factor(single_share: float) -> float:
    """
    Поправочный коэффициент по доле одиноких.
    Линейная интерполяция: при single_share=0.285 коэффициент = 1.061.
    Меньше одиноких → коэффициент ближе к 1,0 (меньше поправка).
    """
    return 1.0 + (single_share / config.DEFAULT_SINGLE_SHARE) * (DEFAULT_CORRECTION_FACTOR - 1.0)


def compute_population(
    flats: int,
    avg_persons_per_flat: float = config.DEFAULT_AVG_PERSONS_PER_FLAT,
    single_share: float = config.DEFAULT_SINGLE_SHARE,
    household_dist: Dict[int, float] = None,
) -> dict:
    """
    Рассчитать население по числу квартир и демографическим параметрам.

    Возвращает dict:
        {
          flats, base_residents, corrected_residents, final_avg_per_flat,
          households: {1..5: int},          — число домохозяйств каждой группы
          residents_by_hh: {1..5: int},     — жителей в каждой группе
        }
    """
    if household_dist is None:
        household_dist = config.DEFAULT_HOUSEHOLD_DISTRIBUTION

    flats = max(0, int(flats))

    # 1) Базовая оценка (столбец «≈ Жителей ср.2,3 чел/кв» в Excel)
    base_residents = flats * avg_persons_per_flat

    # 2) Скорректированная оценка с поправкой на одиноких
    correction = _compute_correction_factor(single_share)
    final_avg_per_flat = avg_persons_per_flat * correction
    corrected_residents = round(flats * final_avg_per_flat)

    # 3) Детализация по составу домохозяйств (для листа «Демография» в отчёте)
    households = {k: round(flats * share) for k, share in household_dist.items()}
    residents_by_hh = {k: households[k] * k for k in household_dist}

    return {
        "flats": flats,
        "base_residents": int(round(base_residents)),
        "corrected_residents": corrected_residents,
        "final_avg_per_flat": round(final_avg_per_flat, 2),
        "households": households,
        "residents_by_hh": residents_by_hh,
    }


def residents_per_competitor(corrected_residents: int, competitors: int) -> float:
    """Соотношение жителей на одного конкурента (насыщенность рынка)."""
    if competitors <= 0:
        return float("inf")
    return round(corrected_residents / competitors, 1)
