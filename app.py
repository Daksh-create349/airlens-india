from base64 import b64encode
from calendar import monthrange
from datetime import date
from html import escape
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
SAMPLE_CITY = "Mumbai"
SAMPLE_DATE = date(2020, 1, 15)
POLLUTANTS = {
    "PM2.5": ("Fine particles", "µg/m³", 75.0),
    "PM10": ("Coarse particles", "µg/m³", 120.0),
    "NO2": ("Nitrogen dioxide", "µg/m³", 35.0),
    "SO2": ("Sulfur dioxide", "µg/m³", 12.0),
    "CO": ("Carbon monoxide", "mg/m³", 1.2),
}
MAX_MODEL_INPUT = float(np.finfo(np.float32).max)
AQI_BANDS = (
    (0, 50, "Good", "#74bb91"),
    (51, 100, "Satisfactory", "#b5cb70"),
    (101, 200, "Moderate", "#f1c46e"),
    (201, 300, "Poor", "#eb9a70"),
    (301, 400, "Very Poor", "#e68286"),
    (401, 500, "Severe", "#bd8aa9"),
)


@st.cache_resource
def load_model():
    return joblib.load(ROOT / "aqi_model.pkl")


@st.cache_data
def local_font_styles():
    fonts = {"Geist": "Geist-Variable.woff2", "Geist Mono": "GeistMono-Variable.woff2"}
    rules = []
    for family, filename in fonts.items():
        data = b64encode((ASSETS / "fonts" / filename).read_bytes()).decode("ascii")
        rules.append(
            f'@font-face {{ font-family:"{family}"; '
            f'src:url(data:font/woff2;base64,{data}) format("woff2"); '
            'font-weight:100 900; font-display:swap; }'
        )
    return "<style>" + "".join(rules) + "</style>"


def predict_aqi(bundle, city, observed_on, readings):
    row = {
        "City": city,
        "Year": observed_on.year,
        "Month": observed_on.month,
        "Day": observed_on.day,
        "DayOfWeek": observed_on.weekday(),
        **{name: float("nan") if value is None else value for name, value in readings.items()},
    }
    frame = pd.DataFrame([row], columns=bundle["features"])
    prediction = float(bundle["model"].predict(frame)[0])
    return round(max(0, min(500, prediction)))


SCENARIOS = {
    "Bengaluru": (date(2019, 7, 15), [14, 32, 11, 4, 0.4]),
    "Chennai": (date(2019, 12, 10), [58, 106, 26, 9, 0.8]),
    "Delhi": (date(2019, 11, 2), [250, 390, 58, 21, 2.6]),
}


def use_example():
    city = st.session_state.get("example")
    if not city:
        return
    day, concentrations = SCENARIOS[city]
    readings = dict(zip(POLLUTANTS, concentrations))
    st.session_state.update({name: str(value) for name, value in readings.items()})
    st.session_state.update(city=city, reading_date=day,
                            last_prediction=(city, day, predict_aqi(load_model(), city, day, readings)))


@st.cache_data
def historical_readings():
    data = pd.read_csv(ROOT / "city_day.csv", usecols=["City", "Date", "AQI"], parse_dates=["Date"])
    return data.dropna(subset=["AQI"]).set_index(["City", "Date"])["AQI"].sort_index()


def render_calendar(city, observed_on):
    history = historical_readings().loc[city]
    end = min(pd.Timestamp(observed_on), history.index.max()).to_period("M")
    months = pd.period_range(end=end, periods=12, freq="M")
    rows = []
    for month in months:
        cells = []
        for day in range(1, monthrange(month.year, month.month)[1] + 1):
            stamp = pd.Timestamp(month.year, month.month, day)
            value = history.get(stamp)
            color = "#e0ded4"
            detail = "No reading"
            if value is not None:
                color = next(b[3] for b in AQI_BANDS if min(value, 500) <= b[1])
                detail = f"AQI {value:.0f}"
            cells.append(f'<i style="background:{color}" title="{stamp:%d %b %Y} · {detail}"></i>')
        rows.append(f'<div class="calendar-row"><span>{month.start_time:%b}</span>{"".join(cells)}</div>')
    return f"""
        <figure class="calendar">
        <figcaption><strong>Daily air quality</strong><small>{months[0].start_time:%b %Y} – {end.start_time:%b %Y}</small></figcaption>
        {"".join(rows)}
        <div class="calendar-key"><span>One square per day</span><span>□ &nbsp; No reading</span></div>
        </figure>
    """


@st.cache_data
def skyline_background():
    return b64encode((ASSETS / "skyline.webp").read_bytes()).decode("ascii")


def render_result(city, observed_on, score, example):
    low, high, category, color = next(b for b in AQI_BANDS if b[0] <= score <= b[1])
    context = "Example result" if example else "Prediction"
    st.html(f"<style>:root {{ --skyline:url(data:image/webp;base64,{skyline_background()}); }}</style>")
    st.html(f"""
        <section class="answer" data-atmosphere="{category.lower().replace(' ', '-')}"
                 aria-label="{context}: AQI {score}, {category}">
            <span class="answer-label">{context} for {escape(city)} · {observed_on:%d %b %Y}</span>
            <div class="answer-score"><strong>{score}</strong><span>/ 500 AQI</span></div>
            <h2><i style="background:{color}"></i>{category}</h2>
            <p>This score falls in the {low}–{high} range. Higher AQI means more polluted air.</p>
        </section>
    """)
    return category


def render_category_guide(active_category):
    cells = []
    for lower, upper, label, color in AQI_BANDS:
        active = ' class="active-band" aria-current="true"' if label == active_category else ""
        cells.append(
            f'<li{active} style="--band:{color}"><b>{label}</b><span>{lower}–{upper}</span></li>'
        )
    st.html(f"""
        <section class="category-guide">
            <h2>India’s AQI scale</h2>
            <ul>{"".join(cells)}</ul>
        </section>
    """)


def main():
    st.set_page_config(page_title="AirLens India | AQI Predictor", page_icon=":material/air:", layout="wide")
    st.html(local_font_styles())
    st.html(ASSETS / "styles.css")
    try:
        bundle = load_model()
    except (OSError, ImportError, ValueError):
        st.error("Could not load the AQI model. Check that aqi_model.pkl is beside app.py and that the project requirements are installed.")
        st.stop()

    st.html(f"""
        <header class="masthead">
            <div class="brand">
                
                <span>AirLens <em>India</em></span>
            </div>
            <span class="masthead-meta">AQI PREDICTOR &nbsp; / &nbsp; GROUP 6</span>
        </header>
    """)
    st.session_state.setdefault("city", SAMPLE_CITY)
    st.session_state.setdefault("reading_date", SAMPLE_DATE)
    for name, (_, _, initial) in POLLUTANTS.items():
        st.session_state.setdefault(name, f"{initial:g}")
    st.html("""<div class="welcome"><h1>How polluted is the air?</h1>
        <p>Pick an example to see an instant result, or enter your own pollutant readings below.</p></div>""")
    form_column, result_slot = st.columns([1.25, 1], gap="medium")
    with form_column:
        st.pills("Try an example", list(SCENARIOS), key="example", on_change=use_example)
        with st.form("prediction", border=False, enter_to_submit=True):
            st.html('<h2 class="form-heading">Enter your readings</h2>')
            location, day = st.columns(2, gap="small")
            city = location.selectbox("City", bundle["cities"], key="city")
            observed_on = day.date_input("Date", min_value=date(2015, 1, 1),
                                         max_value=date(2100, 12, 31), format="DD/MM/YYYY", key="reading_date")
            readings = {}
            for index, (name, (description, unit, initial)) in enumerate(POLLUTANTS.items()):
                if index % 2 == 0:
                    pollutant_columns = st.columns(2, gap="small")
                label = {"PM2.5": "PM₂.₅", "PM10": "PM₁₀", "NO2": "NO₂", "SO2": "SO₂"}.get(name, name)
                readings[name] = pollutant_columns[index % 2].text_input(
                    f"{description} · {label} ({unit})", key=name,
                )
            st.caption("Missing a reading? Leave it blank. Enter at least one value.")
            submitted = st.form_submit_button("Predict AQI", type="primary",
                                              use_container_width=True, icon=":material/arrow_forward:")
            if submitted:
                values = {}
                invalid = []
                for name, entry in readings.items():
                    try:
                        value = float(entry) if entry.strip() else None
                        if value is not None and not 0 <= value <= MAX_MODEL_INPUT:
                            raise ValueError
                        values[name] = value
                    except ValueError:
                        invalid.append(name)
                if invalid:
                    st.error(f"Enter nonnegative numbers for {', '.join(invalid)}, or leave them blank.")
                elif all(value is None for value in values.values()):
                    st.error("Enter at least one pollutant reading to make a prediction.")
                else:
                    st.session_state["last_prediction"] = (
                        city, observed_on, predict_aqi(bundle, city, observed_on, values)
                    )

    with result_slot:
        last_prediction = st.session_state.get("last_prediction")
        if last_prediction is None:
            sample_readings = {name: config[2] for name, config in POLLUTANTS.items()}
            score = predict_aqi(bundle, SAMPLE_CITY, SAMPLE_DATE, sample_readings)
            current_category = render_result(SAMPLE_CITY, SAMPLE_DATE, score, example=True)
        else:
            current_category = render_result(*last_prediction, example=False)

        with st.expander("See all AQI categories"):
            render_category_guide(current_category)
    with st.expander("Explore historical readings"):
        history_city, history_date = (last_prediction[:2] if last_prediction else (SAMPLE_CITY, SAMPLE_DATE))
        st.caption(f"Recorded daily AQI in {history_city}. Hover over a square for the date and reading.")
        st.html(render_calendar(history_city, history_date))

    st.html(f"""
        <footer class="app-foot">
            <span>MODEL &nbsp; <strong>{escape(bundle["model_name"])}</strong></span>
            <span>TRAINING DATA &nbsp; <strong>2015–2020</strong></span>
        </footer>
    """)


if __name__ == "__main__":
    main()
