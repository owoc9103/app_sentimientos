"""Panel de Streamlit: sentimiento de noticias financieras frente a movimientos de precios.

Ejecución local:  streamlit run app.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.analysis import (
    assign_trading_day,
    bucket_table,
    build_panel,
    compute_returns,
    correlation_table,
    daily_sentiment,
    describe_correlation,
)
from src.config import WATCHLIST
from src.storage import load_headlines, load_prices

st.set_page_config(page_title="Panel de sentimiento financiero", page_icon="📰", layout="wide")

POS, NEG, NEU, INK = "#1a9e77", "#d6543c", "#8a8f98", "#2b59c3"
DISCLAIMER = "Solo con fines educativos. No constituye una recomendación de inversión."

# Etiquetas visibles. Las claves en inglés se conservan porque FinBERT y los CSV las usan.
LABEL_ES = {"positive": "Positivo", "neutral": "Neutral", "negative": "Negativo"}
HORIZON_ES = {
    "Previous day (t-1)": "Día anterior (t−1)",
    "Same day (t)": "Mismo día (t)",
    "Next day (t+1)": "Día siguiente (t+1)",
}
BUCKET_ES = {
    "Most negative third": "Más negativo",
    "Middle third": "Intermedio",
    "Most positive third": "Más positivo",
}


def fmt_num(value: float, decimals: int = 2, signed: bool = False) -> str:
    """Formato es-CO: miles con punto y decimales con coma."""
    if pd.isna(value):
        return "n. d."
    number = float(value)
    sign = ""
    if signed:
        sign = "+" if number >= 0 else "-"
        number = abs(number)
    text = f"{number:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}{text}"


def fmt_pct(value: float) -> str:
    if pd.isna(value):
        return "n. d."
    return f"{fmt_num(value * 100, 0)} %"


# ------------------------------------------------------------------ data
@st.cache_data(ttl=3600)
def load_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load stored data and build the analysis panel (cached for an hour)."""
    headlines = load_headlines()
    prices = load_prices()
    trading_days = pd.DatetimeIndex(prices["date"].unique())
    headlines["trading_day"] = assign_trading_day(headlines["published_utc"], trading_days)
    panel = build_panel(daily_sentiment(headlines), compute_returns(prices))
    return headlines, prices, panel


@st.cache_resource(show_spinner="Cargando FinBERT (la primera vez puede tardar cerca de un minuto)...")
def get_model():
    from src.sentiment import load_finbert

    return load_finbert()


headlines, prices, panel = load_all()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Configuración")
    ticker = st.selectbox(
        "Acción", list(WATCHLIST), format_func=lambda t: f"{WATCHLIST[t][0]} ({t})"
    )
    first, last = panel["date"].min().date(), panel["date"].max().date()
    start, end = st.slider("Periodo", min_value=first, max_value=last, value=(first, last), format="MM/YYYY")
    min_n = st.slider(
        "Mínimo de titulares por día", 1, 5, 2,
        help="Los días con menos titulares quedan fuera de las estadísticas. Con más titulares, el índice diario es menos ruidoso.",
    )
    pooled = st.toggle(
        "Agrupar las 10 acciones para las estadísticas",
        value=False,
        help="Usa en conjunto los días de todas las acciones: hay más datos y las estimaciones son más estables.",
    )
    st.divider()
    st.caption(f"Titulares: Google News RSS · Precios: Yahoo Finance · Modelo: FinBERT\n\n{DISCLAIMER}")

in_period = lambda df, col: df[(df[col].dt.date >= start) & (df[col].dt.date <= end)]  # noqa: E731
stock_panel = in_period(panel[panel["ticker"] == ticker], "date")
stock_news = headlines[(headlines["ticker"] == ticker)].dropna(subset=["trading_day"])
stock_news = in_period(stock_news, "trading_day")
stock_prices = in_period(prices[prices["ticker"] == ticker], "date")
stats_panel = in_period(panel, "date") if pooled else stock_panel

# ------------------------------------------------------------------ header
name = WATCHLIST[ticker][0]
st.title("📰 Panel de análisis de sentimiento financiero")
st.markdown(
    "¿El tono de las noticias financieras coincide con el movimiento de una acción? Cada titular se evalúa con "
    "**FinBERT**, un modelo de inteligencia artificial entrenado con textos financieros, y se compara con el "
    "**rendimiento ajustado por mercado** de la acción."
)
updated = pd.to_datetime(headlines["published_utc"].max())
st.caption(f"Datos hasta el {updated:%d/%m/%Y} · actualización diaria · {DISCLAIMER}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Titulares", fmt_num(len(stock_news), 0))
c2.metric(
    "Sentimiento promedio",
    fmt_num(stock_news["score"].mean(), 2, signed=True),
    help="−1 = totalmente negativo, +1 = totalmente positivo",
)
c3.metric(
    "Positivo / negativo",
    f"{fmt_pct((stock_news['label'] == 'positive').mean())} / {fmt_pct((stock_news['label'] == 'negative').mean())}",
)
c4.metric("Días con noticias", fmt_num(len(stock_panel), 0))

# ------------------------------------------------------------------ price vs sentiment chart
st.subheader(f"{name}: precio e índice de sentimiento diario")
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.6, 0.4], vertical_spacing=0.06)
fig.add_trace(go.Scatter(x=stock_prices["date"], y=stock_prices["close"], name="Precio (USD)",
                         line=dict(color=INK, width=2)), row=1, col=1)
colors = np.where(stock_panel["sentiment"] >= 0, POS, NEG)
fig.add_trace(go.Bar(x=stock_panel["date"], y=stock_panel["sentiment"], name="Sentimiento diario",
                     marker_color=colors, opacity=0.55,
                     customdata=stock_panel["n_headlines"],
                     hovertemplate="%{x|%d/%m/%Y}<br>Sentimiento %{y:+.2f}<br>%{customdata} titulares<extra></extra>"),
              row=2, col=1)
smooth = stock_panel.set_index("date")["sentiment"].rolling("14D").mean()
fig.add_trace(go.Scatter(x=smooth.index, y=smooth.values, name="Promedio de 14 días",
                         line=dict(color="#222", width=1.5)), row=2, col=1)
fig.update_yaxes(title_text="Precio (USD)", row=1, col=1)
fig.update_yaxes(title_text="Sentimiento", range=[-1, 1], row=2, col=1)
fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                  legend=dict(orientation="h", y=1.08, x=0), separators=",.")
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ statistics
scope = "las 10 acciones agrupadas" if pooled else name
st.subheader(f"¿El sentimiento coincide con los rendimientos? ({scope})")
st.markdown(
    "Correlación entre el sentimiento promedio de un día y el **rendimiento anormal** de la acción "
    "(rendimiento de la acción menos el rendimiento del ETF SPY, que replica el S&P 500) "
    "el día anterior, el mismo día y el día siguiente."
)
corr = correlation_table(stats_panel, min_headlines=min_n)
left, right = st.columns([3, 2])
with left:
    for _, row in corr.iterrows():
        r = row["pearson_r"]
        value = "n. d." if np.isnan(r) else f"r = {fmt_num(r, 2, signed=True)}, p = {fmt_num(row['p_value'], 3)}"
        horizon = HORIZON_ES.get(row["horizon"], row["horizon"])
        st.markdown(f"**{horizon}** — {value} · {fmt_num(row['n_days'], 0)} días  \n"
                    f"{describe_correlation(r, row['p_value'])}")
    with st.expander("Cómo interpretar estos resultados"):
        st.markdown(
            "- **Mismo día:** es esperable que la noticia y el precio se muevan juntos: muchas veces la noticia *informa* el movimiento.\n"
            "- **Día anterior:** una relación aquí sugiere que la noticia *sigue* a los precios (la prensa explica el movimiento de ayer).\n"
            "- **Día siguiente:** una relación aquí indicaría que la noticia *anticipa* el rendimiento. En un mercado eficiente este valor debería "
            "estar cerca de cero, porque la noticia pública se incorpora rápido al precio.\n"
            "- **Valor p:** por debajo de 0,05, una relación de esta magnitud sería poco probable si en realidad no existiera. "
            "La correlación no implica causalidad ni garantiza una predicción de precios. Varias pruebas sobre los mismos datos pueden producir falsos positivos."
        )
with right:
    buckets = bucket_table(stats_panel, min_headlines=min_n)
    if not buckets.empty:
        buckets = buckets.copy()
        buckets["bucket"] = buckets["bucket"].astype(str).map(BUCKET_ES).fillna(buckets["bucket"].astype(str))
        bfig = go.Figure()
        bfig.add_trace(go.Bar(x=buckets["bucket"], y=buckets["same_day"] * 100, name="Mismo día", marker_color=INK))
        bfig.add_trace(go.Bar(x=buckets["bucket"], y=buckets["next_day"] * 100, name="Día siguiente", marker_color=NEU))
        bfig.update_layout(
            title="Rendimiento anormal promedio<br>por tercio de sentimiento",
            barmode="group",
            height=380,
            yaxis_title="Rendimiento anormal (%)",
            margin=dict(l=10, r=10, t=72, b=10),
            legend=dict(orientation="h", y=-0.28),
            separators=",.",
        )
        bfig.update_xaxes(tickangle=-15)
        st.plotly_chart(bfig, use_container_width=True)

# ------------------------------------------------------------------ headlines table
st.subheader(f"Titulares recientes de {name}")
label_filter = st.multiselect(
    "Mostrar",
    list(LABEL_ES),
    default=list(LABEL_ES),
    format_func=lambda label: LABEL_ES[label],
)
table = stock_news[stock_news["label"].isin(label_filter)].sort_values("published_utc", ascending=False)
view = table[["published_utc", "headline", "source", "label", "score", "link"]].head(300).copy()
view["label"] = view["label"].map(LABEL_ES).fillna(view["label"])
st.dataframe(
    view,
    hide_index=True, use_container_width=True,
    column_config={
        "published_utc": st.column_config.DatetimeColumn("Publicado (UTC)", format="DD/MM/YYYY, HH:mm"),
        "headline": st.column_config.TextColumn("Titular", width="large"),
        "source": st.column_config.TextColumn("Fuente"),
        "label": st.column_config.TextColumn("Etiqueta"),
        "score": st.column_config.ProgressColumn("Índice", min_value=-1, max_value=1, format="%+.2f"),
        "link": st.column_config.LinkColumn("Enlace", display_text="abrir"),
    },
)

# ------------------------------------------------------------------ try it yourself
with st.expander("🧪 Pruébalo: evalúa cualquier titular con FinBERT"):
    st.caption(
        "FinBERT se entrenó con textos financieros en inglés. Un titular en inglés se evalúa con mayor fiabilidad."
    )
    text = st.text_input("Titular", "Company beats earnings expectations and raises full-year guidance")
    if st.button("Evaluar titular"):
        from src.sentiment import score_texts

        result = score_texts([text], classifier=get_model()).iloc[0]
        a, b, c, d = st.columns(4)
        a.metric("Etiqueta", LABEL_ES.get(result["label"], str(result["label"]).capitalize()))
        b.metric("Positivo", fmt_pct(result["p_positive"]))
        c.metric("Negativo", fmt_pct(result["p_negative"]))
        d.metric("Índice", fmt_num(result["score"], 2, signed=True))

# ------------------------------------------------------------------ method
with st.expander("Metodología y limitaciones"):
    st.markdown(
        """
**Método**
1. Los titulares de cada acción se recogen a diario desde Google News RSS y se filtran para conservar los que mencionan a la empresa.
   Se eliminan los duplicados (la misma noticia reproducida por varios medios).
2. FinBERT asigna a cada titular P(positivo), P(negativo) y P(neutral). **Índice = P(positivo) − P(negativo)**, entre −1 y +1.
   En los datos y en el modelo, esas clases conservan las etiquetas `positive`, `negative` y `neutral`.
3. Cada titular se asigna al primer día bursátil en el que podría influir: la noticia posterior al cierre de las 16:00 en Nueva York,
   o publicada en fin de semana o festivo, cuenta para el día bursátil siguiente.
4. El sentimiento diario es el promedio del índice de los titulares de ese día.
5. El rendimiento anormal es el rendimiento de la acción menos el rendimiento de SPY, para retirar los movimientos de todo el mercado.

**Limitaciones**
- Solo se usan titulares, no los artículos completos. La cobertura de Google News varía según la acción y el momento.
- El historial reconstruido solo tiene marcas de tiempo a nivel de fecha, así que alguna noticia posterior al cierre puede quedar asignada al día equivocado.
- FinBERT puede malinterpretar el sarcasmo, las preguntas ("Should you buy...?") y las menciones que no son relevantes para la empresa.
- La lista de seguimiento incluye diez empresas grandes y muy cubiertas por la prensa, de modo que los resultados no se generalizan a empresas de baja capitalización.
- La correlación no implica causalidad ni es una señal para operar. Esta herramienta es exploratoria: no predice ni garantiza precios.
"""
    )
st.caption(
    "Desarrollado por Mehedi Hasan Khan · "
    "[GitHub](https://github.com/KhanFT787/news-sentiment-dashboard) · "
    f"{DISCLAIMER}"
)
