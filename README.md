<div align="center">

# 🏪 Retail Location Analyzer

**Интерактивный анализ торговых точек** — геокодинг, поиск зданий и квартир в зоне охвата, конкуренты и инфраструктура через OpenStreetMap, демографический расчёт, обогащение из my-gkh.ru, экспорт в Excel.

[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![GitHub last commit](https://img.shields.io/github/last-commit/KrivchenkoEgor/retail_location_analyzer?style=for-the-badge&color=blue)](https://github.com/KrivchenkoEgor/retail_location_analyzer/commits/main)
[![GitHub stars](https://img.shields.io/github/stars/KrivchenkoEgor/retail_location_analyzer?style=for-the-badge&color=yellow)](https://github.com/KrivchenkoEgor/retail_location_analyzer/stargazers)

</div>

---

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| 🌐 **Геокодинг** | Почта России + Nominatim (резерв) |
| 🏘️ **Дома и квартиры** | In-circle API Почты России, квартиры → жители |
| 🏪 **Конкуренты** | Магазины, супермаркеты, гипермаркеты, алко, мясные, молочные (OSM) |
| 🏢 **Офисы и образование** | Бизнес-центры, ВУЗы, колледжи, ПТУ (OSM) |
| 📊 **Демография** | Модель домохозяйств с редактируемыми параметрами |
| 🏗️ **Обогащение МКД** | Год постройки, этажность, материал, УК, поставщики (my-gkh.ru) |
| 📑 **Экспорт** | Excel-отчёт (7 листов) |

---

## 🚀 Быстрый старт

```bash
git clone https://github.com/KrivchenkoEgor/retail_location_analyzer.git
cd retail_location_analyzer
pip install -r requirements.txt
streamlit run app.py
```

Откроется в браузере по адресу `http://localhost:8501`.

---

## 🎮 Использование

<table>
<tr>
<td width="60%">

1. **Боковая панель**
   - Укажите **город** (подставляется к каждому адресу)
   - Введите **адреса** (по одному в строке или .txt)
   - Настройте **радиусы** поиска
   - Отредактируйте **демографическую модель**

2. **Запустите анализ** — прогресс-бар покажет статус

3. **Изучите результаты** по вкладкам:
   - 📋 Сводка · 🏪 Детально · 👨‍👩‍👧‍👦 Демография
   - 🏢 Матрица сетей · 🏗️ Данные МКД · 📥 Экспорт

4. **Скачайте Excel** на вкладке «Экспорт»

</td>
</tr>
</table>

---

## 🏛️ Источники данных

| Данные | Источник | Авторизация |
|--------|----------|:-----------:|
| Геокодинг | [geo.pochta.ru](https://geo.pochta.ru/) + [Nominatim](https://nominatim.openstreetmap.org/) | ❌ не требуется |
| Дома и квартиры | [geo.pochta.ru](https://geo.pochta.ru/) (in-circle) | ❌ не требуется |
| Конкуренты / офисы / образование | [OpenStreetMap](https://www.openstreetmap.org/) (Overpass API) | ❌ не требуется |
| Характеристики МКД | [my-gkh.ru](https://my-gkh.ru/) | ⚠️ возможна CAPTCHA |

---

## 📁 Структура проекта

```
retail_location_analyzer/
├── 🚀 app.py                  # Streamlit UI
├── ⚙️ config.py               # Константы, таймауты, OSM-теги
├── 📦 requirements.txt
├── core/
│   ├── 🌐 geocoder.py         # Адрес → координаты
│   ├── 🏘️ buildings.py        # Здания и квартиры в радиусе
│   ├── 🏪 poi.py              # Overpass: магазины, офисы, образование
│   ├── 👨‍👩‍👧‍👦 demographics.py  # Квартиры → жители
│   ├── 🏗️ my_gkh.py           # Обогащение из my-gkh.ru
│   └── 🔄 analyzer.py         # Оркестратор
└── exporters/
    └── 📑 excel_report.py     # Excel-отчёт (openpyxl, 7 листов)
```

---

## 👨‍👩‍👧‍👦 Демографическая модель

| Параметр | Значение |
|----------|:--------:|
| Базовая оценка | квартиры × **2,3** |
| Скорректированная | квартиры × **2,44** |
| 👤 1 чел | **23,5%** |
| 👫 2 чел | **30%** |
| 👨‍👩‍👧 3 чел | **23%** |
| 👨‍👩‍👧‍👦 4 чел | **15%** |
| 👨‍👩‍👧‍👧‍👦 5+ чел | **8,5%** |

> Все параметры редактируются в UI боковой панели

---

## ⚠️ Замечания

- **Overpass API** — медленный (~10 с на точку). Между точками автоматическая пауза для защиты от блокировки (429).
- **`flats = 1`** трактуется как «нет данных по жилому фонду» (аналогично фронтенду Почты России).
- **my-gkh.ru** — сервер может возвращать CAPTCHA при запросах к `/gethouse/`. Модуль пытается получить данные напрямую; если не удаётся — детали пропускаются, базовая информация (адрес, УК) доступна всегда.

---

<div align="center">

**Made with ❤️ for retail analytics**

[Report Bug](https://github.com/KrivchenkoEgor/retail_location_analyzer/issues) · [Request Feature](https://github.com/KrivchenkoEgor/retail_location_analyzer/issues)

</div>
