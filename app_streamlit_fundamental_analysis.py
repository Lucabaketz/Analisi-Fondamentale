import math
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =========================
# STILE (tema blu minimal)
# =========================
st.set_page_config(page_title="Analisi Fondamentale", layout="wide")
st.markdown(
    """
    <style>
    :root{
      --primary: #1e3a8a;      /* blu scuro */
      --primary-600:#1d4ed8;   /* blu */
      --bg:#f8fafc;            /* grigio chiarissimo */
      --bg-soft:#eef2ff;       /* azzurrino tenue */
      --text:#0f172a;
      --muted:#64748b;
      --ring:#93c5fd;
    }
    .stApp {background: var(--bg);}
    h1,h2,h3,h4 { color: var(--primary); }
    .blue-card{
      background: white; border:1px solid #e5e7eb; border-radius:14px; padding:16px;
      box-shadow:0 1px 2px rgba(2,6,23,.06);
    }
    .soft { background: var(--bg-soft) !important; }
    .muted { color: var(--muted); font-size:0.95rem; }
    .metric > div { border-radius:12px; }
    .stButton>button, .stDownloadButton>button {
      background: var(--primary-600) !important; color:white !important; border-radius:10px;
      border:0 !important; padding:.5rem .9rem; box-shadow:none;
    }
    .stSelectbox [data-baseweb="select"] { border-radius:10px; }
    .stTabs [data-baseweb="tab-list"] { gap:.5rem; }
    .stTabs [data-baseweb="tab"] { background:#e2e8f0; border-radius:999px; padding:.35rem .9rem; color:#0f172a; }
    .stTabs [aria-selected="true"] { background:var(--primary-600); color:white; }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# LISTE TICKER (menu)
# =========================
FTSE_MIB = {
    "ENEL": "ENEL.MI",
    "ENI": "ENI.MI",
    "Intesa Sanpaolo": "ISP.MI",
    "UniCredit": "UCG.MI",
    "Stellantis": "STLAM.MI",
    "Ferrari": "RACE.MI",
    "Prysmian": "PRY.MI",
    "Poste Italiane": "PST.MI",
    "Moncler": "MONC.MI",
    "Amplifon": "AMP.MI",
}
USA_MEGA = {
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Amazon": "AMZN",
    "Alphabet": "GOOGL",
    "Meta": "META",
    "NVIDIA": "NVDA",
    "Tesla": "TSLA",
    "JPMorgan": "JPM",
    "Visa": "V",
    "ExxonMobil": "XOM",
}
UNIVERSES = {"FTSE MIB": FTSE_MIB, "USA Mega-cap": USA_MEGA}

# =========================
# HELPERS
# =========================
def _as_float(x, default=None):
    try: return float(x)
    except Exception: return default

def fmt2(v):  # per stampare "N/D" con 2 decimali quando serve
    return f"{v:.2f}" if v is not None else "N/D"

@st.cache_data(ttl=300)
def fetch_yf_info(symbol: str):
    t = yf.Ticker(symbol)
    try:
        info = t.get_info() if hasattr(t, "get_info") else (t.info or {})
    except Exception:
        info = {}
    price = info.get("currentPrice")
    if not price:
        try:
            h = t.history(period="1d")
            if isinstance(h, pd.DataFrame) and not h.empty:
                price = float(h["Close"].iloc[-1])
        except Exception:
            price = None

    eps = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
    pe = info.get("trailingPE")
    if (not pe or pe == 0) and price and eps:
        try:
            if eps and eps != 0: pe = float(price)/float(eps)
        except Exception: pass

    dy = info.get("dividendYield")
    if dy is not None:
        try: dy = dy*100 if dy < 1 else dy
        except Exception: dy = None
    dps = info.get("dividendRate")  # dividendo annuo/azione

    return {
        "price": _as_float(price),
        "currency": info.get("currency", ""),
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector"),
        "beta": _as_float(info.get("beta")),
        "eps": _as_float(eps),
        "pe": _as_float(pe),
        "payout": _as_float(info.get("payoutRatio")),  # frazione (0.35 = 35%)
        "div_yield": _as_float(dy),
        "dividend_rate": _as_float(dps),
        "shares_out": info.get("sharesOutstanding"),
    }

@st.cache_data(ttl=600)
def fetch_eps_history(symbol: str):
    t = yf.Ticker(symbol)
    try:
        earn = t.earnings  # DF con Earnings/Revenue per anno
        if isinstance(earn, pd.DataFrame) and not earn.empty:
            info = fetch_yf_info(symbol)
            shares = info.get("shares_out") or 0
            if shares:
                return (earn["Earnings"]/shares).dropna()
    except Exception:
        pass
    return pd.Series(dtype=float)

def cagr(series: pd.Series, years: int = 5):
    if series is None or series.empty or len(series)<2: return None
    s = series.sort_index()
    first = float(s.iloc[max(0, len(s)-years-1)])
    last  = float(s.iloc[-1])
    n = min(years, len(s)-1)
    if first<=0 or last<=0 or n<=0: return None
    try: return (last/first)**(1/n) - 1
    except Exception: return None

SECTOR_PE = {
    "Technology": 22.0, "Communication Services": 19.0, "Consumer Discretionary": 18.0,
    "Health Care": 18.0, "Industrials": 16.0, "Materials": 15.0, "Consumer Staples": 18.0,
    "Energy": 10.0, "Financial Services": 11.0, "Utilities": 14.0, "Real Estate": 14.0,
}

def required_return(beta, rf, mrp, default_beta=1.0):
    b = beta if beta is not None and not math.isnan(beta) else default_beta
    return rf + b*mrp

def dcf_lite_fair_value(eps, payout, r, g1, g2):
    if eps is None: return None
    if payout is None or payout<0 or payout>1: payout = 0.4
    fcf0 = eps*(1-payout)
    years=5; pv=0.0
    for t in range(1, years+1):
        fcf_t = fcf0*((1+g1)**t); pv += fcf_t/((1+r)**t)
    fcf_T = fcf0*((1+g1)**years)
    if r<=g2: g2 = max(g2-0.01,0.0)
    terminal = fcf_T*(1+g2)/(r-g2); pv_term = terminal/((1+r)**years)
    return pv+pv_term

def relative_pe_fair_value(eps, sector):
    if eps is None: return None
    return eps*SECTOR_PE.get(sector, 15.0)

def gordon_fair_value(dps, r, g):
    if dps is None or dps<=0: return None
    if r<=g: g = max(g-0.01, 0.0)
    return dps*(1+g)/(r-g)

def combine_values(values, has_ddm):
    w = {"DCF":0.6, "PE":0.4, "DDM":0.0} if not has_ddm else {"DCF":0.6,"PE":0.3,"DDM":0.1}
    tot=0.0; ww=0.0
    for k,v in values.items():
        if v is not None and w.get(k,0)>0: tot+=v*w[k]; ww+=w[k]
    return (tot/ww) if ww>0 else None

def show_or_input(label, key, default, step=0.01, fmt="{:.2f}",
                  allow_edit=False, allow_negative=False, currency=""):
    val = default if isinstance(default,(int,float)) else _as_float(default, None)
    if allow_edit:
        minv = None if allow_negative else 0.0
        return st.number_input(label, min_value=minv, value=float(val or 0.0), step=step, key=key)
    else:
        if val is None: st.markdown(f"- **{label}:** N/D")
        else:           st.markdown(f"- **{label}:** {fmt.format(val)} {currency}")
        return val

# =========================
# UI: TABS (Analisi / Tutorial)
# =========================
tab_analisi, tab_tutorial = st.tabs(["📊 Analisi", "📘 Tutorial"])

with tab_analisi:
    st.markdown("### Selezione titoli")
    sel1, sel2 = st.columns([1,2])
    with sel1:
        choice = st.selectbox("Scegli l'universo", ["FTSE MIB","USA Mega-cap","Altro"])
    with sel2:
        if choice=="Altro":
            tickers_input = st.text_input("Ticker personalizzati (max 2, separati da virgola)", "")
            tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
        else:
            mapping = UNIVERSES[choice]; labels = list(mapping.keys())
            selected_labels = st.multiselect(f"Seleziona fino a 2 titoli ({choice})", labels, max_selections=2)
            tickers = [mapping[l] for l in selected_labels]
    tickers = tickers[:2]
    allow_manual = st.toggle("Modifica manualmente i dati quantitativi", value=False)

    # Parametri modello
    with st.expander("⚙️ Assunzioni del modello (opzionali)"):
        c1,c2,c3,c4 = st.columns(4)
        with c1: rf  = st.number_input("Tasso risk-free r_f (%)", value=3.0, step=0.1)/100.0
        with c2: mrp = st.number_input("Market Risk Premium MRP (%)", value=5.5, step=0.1)/100.0
        with c3: cap_g1 = st.number_input("Cap crescita 5y g₁ max (%)", value=15.0, step=0.5)/100.0
        with c4: g2  = st.number_input("Crescita terminale g₂ (%)", value=2.0, step=0.1)/100.0

    for tkr in tickers:
        st.markdown(f"## {tkr}")
        col1, col2 = st.columns(2, gap="large")

        with col1:
            st.markdown('<div class="blue-card soft">**Valutazione Qualitativa**</div>', unsafe_allow_html=True)
            q1 = st.radio("Vantaggio competitivo duraturo?", ["Sì","No"], index=1, key=f"{tkr}_q1")
            q2 = st.radio("Situazione finanziaria solida?", ["Sì","No"], index=1, key=f"{tkr}_q2")
            q3 = st.radio("Utili in crescita?", ["Sì","No"], index=1, key=f"{tkr}_q3")
            q4 = st.radio("Management competente?", ["Sì","No"], index=1, key=f"{tkr}_q4")

        with col2:
            st.markdown('<div class="blue-card">**Dati Quantitativi (Yahoo Finance)**</div>', unsafe_allow_html=True)
            info = fetch_yf_info(tkr)
            currency = info.get("currency") or ""

            price_val = show_or_input(f"Prezzo attuale ({tkr})", f"{tkr}_price", info.get("price"),
                                      step=0.01, allow_edit=allow_manual, currency=currency)
            pe_val = show_or_input(f"P/E ({tkr})", f"{tkr}_pe", info.get("pe"),
                                   step=0.1, allow_edit=allow_manual, allow_negative=True)
            eps_val = show_or_input(f"EPS ({tkr})", f"{tkr}_eps", info.get("eps"),
                                    step=0.01, allow_edit=allow_manual, allow_negative=True)
            payout_val = show_or_input(f"Payout ratio (0–1) ({tkr})", f"{tkr}_payout", info.get("payout"),
                                       step=0.05, fmt="{:.2f}", allow_edit=allow_manual)
            dy = info.get("div_yield")
            if allow_manual:
                dy = st.number_input(f"Dividend Yield (%) ({tkr})", min_value=0.0,
                                     value=float(dy or 0.0), step=0.1, key=f"{tkr}_divy")
            else:
                st.markdown(f"- **Dividend Yield:** {dy:.1f}%" if dy is not None else "- **Dividend Yield:** N/D")

            # grafico 1Y
            try:
                h = yf.Ticker(tkr).history(period="1y")
                if not h.empty:
                    st.line_chart(h["Close"], height=180)
            except Exception:
                pass

        # crescita & r
        eps_hist = fetch_eps_history(tkr)
        g1_raw = cagr(eps_hist, years=5) or cagr(eps_hist, years=3) or 0.05
        g1 = min(max(g1_raw, -0.10), cap_g1)
        r_req = required_return(info.get("beta"), rf, mrp)

        # fair values
        fv_dcf = dcf_lite_fair_value(eps_val, payout_val, r_req, g1, g2)
        fv_pe  = relative_pe_fair_value(eps_val, info.get("sector"))
        fv_ddm = gordon_fair_value(info.get("dividend_rate"), r_req, min(g1, 0.08))

        st.markdown("**Fair Value – {}**".format(tkr))
        vals = {"DCF": fv_dcf, "PE": fv_pe, "DDM": fv_ddm}
        fv_comb = combine_values(vals, fv_ddm is not None)

        band = [v for v in vals.values() if v is not None]
        if band:
            st.write(
                f"Banda modelli: **{min(band):.2f} – {max(band):.2f} {currency}**  "
                f"(DCF: {fmt2(fv_dcf)}, PE: {fmt2(fv_pe)}, DDM: {fmt2(fv_ddm)})"
            )

        if fv_comb is not None:
            if price_val and price_val>0:
                delta = (fv_comb - price_val)/price_val*100
                st.metric("Fair Value combinato", f"{fv_comb:.2f} {currency}", f"{delta:.1f}%")
            else:
                st.metric("Fair Value combinato", f"{fv_comb:.2f} {currency}")
        else:
            st.info("Impossibile calcolare un fair value combinato con i dati disponibili.")

        with st.expander("Dettaglio assunzioni e diagnosi"):
            sector = info.get("sector") or "N/D"
            beta   = info.get("beta")
            st.write(
              f"- **Settore**: {sector} | **β**: {beta if beta is not None else 'N/D'} "
              f"| **r** = {r_req*100:.1f}% | **g₁** = {g1*100:.1f}% | **g₂** = {g2*100:.1f}%"
            )

        st.subheader(f"Commento finale su {tkr}")
        score = sum(1 for q in [q1,q2,q3,q4] if q=="Sì")
        qual_map = {0:"Debole",1:"Debole",2:"Misto",3:"Buono",4:"Ottimo"}
        comment = f"Profilo qualitativo: **{qual_map[score]}**. "
        if fv_comb and price_val:
            d = (fv_comb - price_val)/price_val*100
            if d>=10: comment += f"Valutazione: **sottovalutato** (~{d:.0f}%). "
            elif d<=-10: comment += f"Valutazione: **sopravvalutato** (~{abs(d):.0f}%). "
            else: comment += "Valutazione: **in linea**. "
        comment += "Modelli: DCF-Lite (FCF/ps), multipli di settore, Gordon (se dividend payer)."
        st.write(comment)
        st.warning("⚠️ Analisi informativa; non costituisce consulenza finanziaria.", icon="⚠️")

with tab_tutorial:
    st.markdown("## Come calcoliamo il fair value (tutorial)")
    st.markdown(
        """
        Questo strumento combina **tre** metodi per stimare un valore ragionevole per azione:

        **1) DCF-Lite (flusso di cassa scontato semplificato)**  
        - Stimiamo il **FCF per azione** come `EPS × (1 − payout)`.  
        - Proiettiamo 5 anni con una crescita **g₁** basata sulla **CAGR dell’EPS** (con un tetto massimo).  
        - Applichiamo una **crescita terminale g₂** (di default 2%).  
        - Scontiamo i flussi con il tasso **r = r_f + β × MRP (CAPM)**.  
        - Somma dei flussi scontati + **valore terminale** ⇒ fair value DCF.

        **2) Multipli relativi (P/E di settore)**  
        - Selezioniamo un **P/E tipico** per il settore (es.: Utilities 14, Tech 22…).  
        - `FV_PE = EPS × P/E_settore`.

        **3) Modello di Gordon (dividendi)**  
        - Se c’è dividendo, usiamo `FV_DDM = DPS × (1+g) / (r−g)` con `g = min(g₁, 8%)`.  

        **Combinazione**  
        - Se DDM non è applicabile: **DCF 60% + PE 40%**.  
        - Se DDM è applicabile: **DCF 60% + PE 30% + DDM 10%**.  

        **Interpretazione**  
        - Mostriamo una **banda** (min–max dei modelli calcolati) e un **Fair Value combinato**.  
        - Il **Δ%** indica la differenza rispetto al prezzo corrente (sottovalutato / in linea / sopravvalutato).

        **Parametri modificabili (opzionali)**  
        - `r_f` (risk-free), `MRP` (premio di mercato), `g₁ cap`, `g₂`.  
        - Se lasci tutto com’è, usiamo valori **prudenziali**.

        **Limiti da tenere a mente**  
        - Dati Yahoo possono essere incompleti su alcuni titoli.  
        - Le ipotesi (crescita, payout, P/E di settore) sono **semplificate**.  
        - Il risultato è **informativo**: non è una raccomandazione d’investimento.
        """,
        unsafe_allow_html=True,
    )



