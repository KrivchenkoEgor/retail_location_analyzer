"""
app.py — Retail Location Analyzer. Streamlit веб-приложение.

Запуск:
    cd retail_location_analyzer
    streamlit run app.py

Поток:
    1. Сidebar: ввод города, адресов, радиусов, демографических параметров.
    2. Главная: кнопка «Запустить анализ» → прогресс-бар → результаты во вкладках.
    3. Экспорт: скачивание Excel-отчёта (6 листов).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Добавляем корень проекта в sys.path, чтобы импортировать config и core
sys.path.insert(0, str(Path(__file__).parent))

import config
from core import analyzer, geocoder
from exporters import excel_report


# ---------------------------------------------------------------------------
# Настройка страницы
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Retail Location Analyzer",
    page_icon="🏪",
    layout="wide",
)


def _build_summary_df(results):
    """DataFrame сводки по точкам для таблицы."""
    rows = []
    for i, r in enumerate(results, 1):
        if not r.get("ok"):
            rows.append({"№": i, "Адрес": r.get("address", ""), "Статус": f"Ошибка: {r.get('error', '')}"})
            continue
        bld = r.get("buildings_summary", {})
        demo = r.get("demographics", {})
        g = r.get("mygkh", {})
        addr_display = r["address"]
        if r.get("geo_imprecise"):
            addr_display += " ⚠️"
        rows.append({
            "№": i,
            "Адрес": addr_display,
            "Домов": bld.get("total_buildings", 0),
            "Жилых": bld.get("residential", 0),
            "Квартир": bld.get("total_flats", 0),
            "Конкурентов": r.get("competitors_count", 0),
            "Офисов": len(r.get("poi", {}).get("offices", [])),
            "Уч.заведений": len(r.get("poi", {}).get("education", [])),
            "Жителей": demo.get("corrected_residents", 0),
            "Жит./конк.": r.get("residents_per_competitor", 0),
            "Год постройки": g.get("year_built", ""),
            "Этажей": g.get("floors", ""),
            "Материал": g.get("building_material", ""),
            "УК": g.get("management_company", ""),
        })
    return pd.DataFrame(rows)


def _build_chain_matrix_df(results):
    """Матрица присутствия сетей по точкам для тепловой карты."""
    ok_results = [r for r in results if r.get("ok")]
    all_brands = {}
    for r in ok_results:
        for brand in r.get("shop_brands", {}):
            all_brands[brand] = all_brands.get(brand, 0) + 1
    brands = [b for b, _ in sorted(all_brands.items(), key=lambda kv: -kv[1])]

    data = []
    for brand in brands:
        row = {"Сеть / Бренд": brand}
        for i, r in enumerate(ok_results, 1):
            cnt = r.get("shop_brands", {}).get(brand, 0)
            row[f"Т{i}"] = cnt
        data.append(row)
    return pd.DataFrame(data), brands, ok_results


# ---------------------------------------------------------------------------
# Sidebar: ввод данных
# ---------------------------------------------------------------------------
st.sidebar.title("🏪 Retail Location Analyzer")
st.sidebar.caption("Анализ торговых точек: дома, квартиры, конкуренты, демография")

st.sidebar.markdown("### 1. Входные данные")
# Список городов подгружается с geo.pochta.ru (103 региона рассылки).
# Кэшируется через st.cache_data, чтобы не запрашивать при каждом рендере.
@st.cache_data(show_spinner=False)
def _load_cities():
    return geocoder.get_available_cities()

_cities = _load_cities()
_default_idx = _cities.index("Омск") if "Омск" in _cities else 0
city = st.sidebar.selectbox(
    "Город",
    options=_cities,
    index=_default_idx,
    help="Город из списка geo.pochta.ru. Подставляется к каждому адресу при геокодинге.",
)

addresses_text = st.sidebar.text_area(
    "Адреса (по одному в строке)",
    value="проспект Мира, 46\nпроспект Комарова, 8Б\nбульвар Архитекторов, 5/1г",
    height=150,
    help="Улица и дом. Город добавится автоматически.",
)
uploaded = st.sidebar.file_uploader("Или загрузите .txt с адресами", type=["txt"])
if uploaded is not None:
    addresses_text = uploaded.read().decode("utf-8")

# Радиусы
st.sidebar.markdown("### 2. Радиусы поиска (м)")
col1, col2, col3 = st.sidebar.columns(3)
r_shops = col1.number_input("Конкуренты", 50, 2000, config.DEFAULT_RADIUS_SHOPS, step=50)
r_offices = col2.number_input("Офисы", 50, 1000, config.DEFAULT_RADIUS_OFFICES, step=50)
r_edu = col3.number_input("Образование", 50, 1000, config.DEFAULT_RADIUS_EDUCATION, step=50)

# Демография
st.sidebar.markdown("### 3. Демографическая модель")
avg_ppf = st.sidebar.number_input("Среднее чел/квартиру", 1.0, 6.0, config.DEFAULT_AVG_PERSONS_PER_FLAT, 0.1)
single_share = st.sidebar.slider(
    "Доля одиноких, %", 0, 100, int(config.DEFAULT_SINGLE_SHARE * 100), step=5
) / 100

with st.sidebar.expander("Распределение домохозяйств (доли)"):
    hh = {}
    hh[1] = st.slider("1 чел", 0.0, 1.0, config.DEFAULT_HOUSEHOLD_DISTRIBUTION[1], 0.01)
    hh[2] = st.slider("2 чел", 0.0, 1.0, config.DEFAULT_HOUSEHOLD_DISTRIBUTION[2], 0.01)
    hh[3] = st.slider("3 чел", 0.0, 1.0, config.DEFAULT_HOUSEHOLD_DISTRIBUTION[3], 0.01)
    hh[4] = st.slider("4 чел", 0.0, 1.0, config.DEFAULT_HOUSEHOLD_DISTRIBUTION[4], 0.01)
    hh[5] = st.slider("5+ чел", 0.0, 1.0, config.DEFAULT_HOUSEHOLD_DISTRIBUTION[5], 0.01)
    total_hh = sum(hh.values())
    if abs(total_hh - 1.0) > 0.01:
        st.warning(f"Сумма долей = {total_hh:.2f}, нормализуем к 1.0")
        hh = {k: v / total_hh for k, v in hh.items()}


# ---------------------------------------------------------------------------
# Главная область
# ---------------------------------------------------------------------------
st.title("🏪 Анализ торговых точек")
st.markdown("Дома и квартиры — **Почта России** • Конкуренты/офисы/образование — **OpenStreetMap**")

# Разбор адресов
raw_addresses = [a.strip() for a in addresses_text.strip().splitlines() if a.strip()]
addresses = [f"{city}, {a}" if not a.lower().startswith(city.lower()) else a for a in raw_addresses]

if not addresses:
    st.info("Введите адреса в боковой панели слева.")
    st.stop()

st.caption(f"Подготовлено адресов: **{len(addresses)}**")

# Кнопка запуска
if st.button("🚀 Запустить анализ", type="primary", use_container_width=True):
    results = []
    progress = st.progress(0.0, text="Подготовка...")
    status = st.empty()

    def on_progress(i, total, res):
        pct = i / total
        addr = res.get("address", "")
        if res.get("ok"):
            if res.get("geo_imprecise"):
                status.warning(f"⚠️ [{i}/{total}] {addr} — адрес найден приблизительно, данные могут быть неточными")
            else:
                status.success(f"✅ [{i}/{total}] {addr} — конкурентов: {res.get('competitors_count', 0)}")
        else:
            status.error(f"❌ [{i}/{total}] {addr} — {res.get('error', 'ошибка')}")
        progress.progress(pct, text=f"Обработано {i} из {total}")

    with st.spinner("Идёт анализ точек (Overpass ~10с на точку)..."):
        results = analyzer.analyze_many(
            addresses,
            progress_cb=on_progress,
            r_shops=r_shops,
            r_offices=r_offices,
            r_edu=r_edu,
            avg_persons_per_flat=avg_ppf,
            single_share=single_share,
            household_dist=hh,
        )

    progress.progress(1.0, text="Готово!")
    st.session_state["results"] = results
    st.success("Анализ завершён!")

# Результаты
results = st.session_state.get("results")
if results:
    st.divider()
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["📊 Сводка", "🏢 Детально по точкам", "👥 Демография", "🔌 Матрица сетей", "🏠 Данные МКД", "💾 Экспорт"]
    )

    with tab1:
        st.subheader("Сводка по точкам")
        df = _build_summary_df(results)
        st.dataframe(df, use_container_width=True, hide_index=True)

        ok_results = [r for r in results if r.get("ok")]
        if ok_results:
            # График: жители vs конкуренты
            chart_df = pd.DataFrame([
                {"Адрес": r["address"].split(",")[-1].strip()[:30],
                 "Жителей": r["demographics"]["corrected_residents"],
                 "Конкурентов": r["competitors_count"]}
                for r in ok_results
            ])
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(px.bar(chart_df, x="Адрес", y="Жителей", title="Жители в зоне охвата"),
                                use_container_width=True)
            with c2:
                st.plotly_chart(px.bar(chart_df, x="Адрес", y="Конкурентов", title="Конкуренты в радиусе"),
                                use_container_width=True)

    with tab2:
        st.subheader("Конкуренты по категориям")
        sel = st.selectbox("Выберите точку", [r["address"] for r in results if r.get("ok")])
        sel_r = next(r for r in results if r.get("ok") and r["address"] == sel)
        by_cat = sel_r.get("shops_by_category", {})
        for cat, items in by_cat.items():
            with st.expander(f"{cat} — {len(items)}"):
                st.dataframe(pd.DataFrame(items)[["brand", "shop_type", "distance_m"]]
                             .rename(columns={"brand": "Бренд", "shop_type": "Тип", "distance_m": "Расстояние, м"}),
                             hide_index=True)

    with tab3:
        st.subheader("Демографический расчёт")
        demo_rows = []
        for r in results:
            if not r.get("ok"):
                continue
            d = r["demographics"]
            hhd = d["households"]
            demo_rows.append({
                "Адрес": r["address"],
                "Квартир": d["flats"],
                "1 чел": hhd.get(1, 0), "2 чел": hhd.get(2, 0), "3 чел": hhd.get(3, 0),
                "4 чел": hhd.get(4, 0), "5+ чел": hhd.get(5, 0),
                "Жителей (скорр.)": d["corrected_residents"],
                "Чел/кв": d["final_avg_per_flat"],
            })
        st.dataframe(pd.DataFrame(demo_rows), use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Матрица присутствия сетей")
        mat_df, brands, ok_r = _build_chain_matrix_df(results)
        if not mat_df.empty:
            st.dataframe(mat_df, use_container_width=True, hide_index=True)
            # Тепловая карта
            heat = mat_df.set_index("Сеть / Бренд").drop(columns=[])
            st.plotly_chart(px.imshow(heat, title="Присутствие сетей по точкам",
                                      color_continuous_scale="Blues"),
                            use_container_width=True)
        else:
            st.info("Нет данных о сетях-конкурентах.")

    with tab5:
        st.subheader("Данные МКД (my-gkh.ru)")
        mygkh_points = [r for r in results if r.get("ok") and r.get("mygkh")]
        if not mygkh_points:
            st.info("Данные МКД найдены не для всех точек (my-gkh.ru доступен для Новосибирска).")
        else:
            sel_m = st.selectbox("Выберите точку", [r["address"] for r in mygkh_points], key="mygkh_sel")
            sel_r = next(r for r in mygkh_points if r["address"] == sel_m)
            g = sel_r["mygkh"]

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Год постройки", g.get("year_built", "—"))
                st.metric("Этажей", g.get("floors", "—"))
                st.metric("Жилых помещений", g.get("living_spaces", "—"))
            with c2:
                st.metric("Общая площадь, м²", g.get("total_area_sqm", "—"))
                st.metric("Серия", g.get("building_series", "—"))
                st.metric("Материал", g.get("building_material", "—"))
            with c3:
                st.metric("Управляющая компания", g.get("management_company", "—"))
                st.metric("Организация", g.get("organization_name", "—"))

            if g.get("characteristics"):
                with st.expander("Характеристики дома", expanded=True):
                    for k, v in g["characteristics"].items():
                        st.markdown(f"**{k}:** {v}")

            if g.get("management"):
                with st.expander("Управляющая компания"):
                    for k, v in g["management"].items():
                        st.markdown(f"**{k}:** {v}")

            if g.get("utility_providers"):
                with st.expander("Поставщики коммунальных ресурсов"):
                    for u in g["utility_providers"]:
                        st.markdown(f"- {u}")

            if g.get("coordinates"):
                with st.expander("Координаты (Яндекс)"):
                    st.write(f"{g['coordinates']['lat']:.5f}, {g['coordinates']['lng']:.5f}")

    with tab6:
        st.subheader("Экспорт в Excel")
        out_path = str(Path.cwd() / "retail_analysis_report.xlsx")
        if st.button("📄 Сгенерировать Excel-отчёт", type="primary"):
            excel_report.build_report(results, out_path)
            with open(out_path, "rb") as f:
                st.download_button(
                    "⬇️ Скачать отчёт (.xlsx)", f, file_name="retail_analysis_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success(f"Отчёт сохранён: {out_path}")
else:
    st.info("Нажмите «Запустить анализ», чтобы получить результаты.")
