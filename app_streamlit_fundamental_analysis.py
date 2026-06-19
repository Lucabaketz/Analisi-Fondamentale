import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================
#  VALUTATORE AZIENDE + CORSO DI FINANZA
#  - Valutazione: DCF (FCFF) - Reverse DCF - Sensitivity - DDM - Multipli
#    con multipli di default calcolati dallo storico del titolo (mediana),
#    sempre modificabili a mano.
#  - Corso: lezioni dalle basi, pensato per crescere 1 lezione/settimana
#  Dati letti dai prospetti finanziari (non solo da .info).
# =============================================================

st.set_page_config(page_title="Valutatore Aziende", layout="wide", page_icon=":chart_with_upwards_trend:")

# ---------- STILE ----------
st.markdown("""
<style>
:root{ --ink:#0b1f3a; --accent:#2563eb; --soft:#eef4ff; --line:#dbe4f0; --muted:#5b6b82; --warn:#b45309; }
.stApp{ background:#f7f9fc; }
h1,h2,h3,h4{ color:var(--ink); }
.card{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
.lesson{ background:#fff; border:1px solid var(--line); border-left:4px solid var(--accent);
         border-radius:10px; padding:18px 22px; margin-bottom:14px; }
.kpi{ background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
.kpi .v{ font-size:1.35rem; font-weight:700; color:var(--ink); }
.kpi .l{ font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }
.pill{ display:inline-block; background:var(--soft); color:var(--accent); border:1px solid #c7d8f5;
       padding:.15rem .6rem; border-radius:999px; font-size:.8rem; margin-right:.35rem; }
.muted{ color:var(--muted); font-size:.9rem; }
.fv-up{ color:#15803d; font-weight:700; }
.fv-dn{ color:#b91c1c; font-weight:700; }
.formula{ background:#0b1f3a; color:#e8f0ff; padding:10px 14px; border-radius:8px;
          font-family:ui-monospace,monospace; font-size:.95rem; display:inline-block; }
</style>
""", unsafe_allow_html=True)

# =============================================================
#  HELPERS
# =============================================================
def f(x, default=None):
    try:
        v = float(x)
        return default if (v != v) else v
    except Exception:
        return default

def fmt(v, dec=2, suffix=""):
    return f"{v:,.{dec}f}{suffix}" if v is not None else "N/D"

def fmt_big(v):
    if v is None: return "N/D"
    a = abs(v)
    if a >= 1e12: return f"{v/1e12:,.2f} T"
    if a >= 1e9:  return f"{v/1e9:,.2f} B"
    if a >= 1e6:  return f"{v/1e6:,.2f} M"
    return f"{v:,.0f}"

def row(df, *names):
    if df is None or df.empty: return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if not s.empty:
                return f(s.iloc[0])
    return None

def full_row(df, *names):
    """Riga completa (tutti gli anni) come Series indicizzata per data."""
    if df is None or df.empty: return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if not s.empty:
                return s.astype(float)
    return None

# =============================================================
#  MULTIPLI STORICI (mediana sul titolo)
# =============================================================
def _naive(ts):
    """Timestamp senza timezone, per confronti uniformi."""
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tz is not None else ts

def price_at(date, price_hist_naive):
    """Ultimo prezzo di chiusura alla data del bilancio (o subito prima)."""
    if price_hist_naive is None or price_hist_naive.empty:
        return None
    d = _naive(date)
    window = price_hist_naive[price_hist_naive.index <= d]
    return float(window.iloc[-1]) if not window.empty else None

def hist_multiple(price_hist_naive, per_share_by_date):
    """Mediana del rapporto prezzo/metrica anno per anno. Ritorna (mediana, n_anni)."""
    ratios = []
    for d, ps in per_share_by_date.items():
        px = price_at(d, price_hist_naive)
        if px and ps and ps > 0:
            r = px / ps
            if 0 < r < 1000:  # scarta outlier assurdi
                ratios.append(r)
    if len(ratios) >= 2:
        return float(np.median(ratios)), len(ratios)
    return None, len(ratios)

@st.cache_data(ttl=600, show_spinner=False)
def historical_multiples(symbol: str, shares_now: float):
    """Calcola P/E, P/BV, P/Sales, P/EBITDA, P/FCF storici (mediana) dal titolo.
    Usa prospetti annuali + prezzo storico allineato alla data di ciascun bilancio."""
    t = yf.Ticker(symbol)
    inc = getattr(t, "income_stmt", None)
    bs  = getattr(t, "balance_sheet", None)
    cf  = getattr(t, "cashflow", None)
    try:
        ph = t.history(period="6y")["Close"].dropna()
        if ph is not None and not ph.empty and ph.index.tz is not None:
            ph.index = ph.index.tz_localize(None)  # uniforma a tz-naive
    except Exception:
        ph = None

    # serie per-azione per data (n. azioni: usa quello attuale come proxy stabile)
    eps_s    = full_row(inc, "Diluted EPS", "Basic EPS")
    if eps_s is None:
        ni = full_row(inc, "Net Income", "Net Income Common Stockholders")
        eps_s = (ni / shares_now) if (ni is not None and shares_now) else None
    equity_s = full_row(bs, "Stockholders Equity", "Total Equity Gross Minority Interest")
    rev_s    = full_row(inc, "Total Revenue", "Operating Revenue")
    ebitda_s = full_row(inc, "EBITDA", "Normalized EBITDA")
    cfo_s    = full_row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex_s  = full_row(cf, "Capital Expenditure", "Purchase Of PPE")
    fcf_s = None
    if cfo_s is not None and capex_s is not None:
        fcf_s = (cfo_s + capex_s).dropna()

    def per_share(series):
        if series is None or shares_now in (None, 0):
            return {}
        return {_naive(d): (float(v) / shares_now) for d, v in series.items() if v == v}

    def per_share_direct(series):
        if series is None:
            return {}
        return {_naive(d): float(v) for d, v in series.items() if v == v}

    out = {}
    # EPS gia' per-azione (non dividere per le azioni)
    out["P/E"]      = hist_multiple(ph, per_share_direct(eps_s))
    out["P/BV"]     = hist_multiple(ph, per_share(equity_s))
    out["P/Sales"]  = hist_multiple(ph, per_share(rev_s))
    out["P/EBITDA"] = hist_multiple(ph, per_share(ebitda_s))
    out["P/FCF"]    = hist_multiple(ph, per_share(fcf_s))
    return out

# =============================================================
#  DATA LAYER
# =============================================================
@st.cache_data(ttl=600, show_spinner=False)
def load_company(symbol: str):
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}

    inc = getattr(t, "income_stmt", None)
    bs  = getattr(t, "balance_sheet", None)
    cf  = getattr(t, "cashflow", None)

    price = f(info.get("currentPrice"))
    if price is None:
        try:
            h = t.history(period="5d")
            if not h.empty:
                price = f(h["Close"].dropna().iloc[-1])
        except Exception:
            pass

    shares = f(info.get("sharesOutstanding")) or row(bs, "Share Issued", "Ordinary Shares Number")

    revenue   = row(inc, "Total Revenue", "Operating Revenue")
    ebit      = row(inc, "EBIT", "Operating Income")
    ebitda    = row(inc, "EBITDA", "Normalized EBITDA") or f(info.get("ebitda"))
    net_inc   = row(inc, "Net Income", "Net Income Common Stockholders")
    pretax    = row(inc, "Pretax Income")
    tax_prov  = row(inc, "Tax Provision")
    interest  = row(inc, "Interest Expense", "Interest Expense Non Operating")

    tax_rate = 0.25
    if pretax and tax_prov is not None and pretax != 0:
        tr = tax_prov / pretax
        if 0 <= tr <= 0.40:
            tax_rate = tr

    total_debt = row(bs, "Total Debt") \
                 or ((row(bs, "Long Term Debt") or 0) + (row(bs, "Current Debt", "Short Term Debt") or 0)) or None
    cash       = row(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    equity_bv  = row(bs, "Stockholders Equity", "Total Equity Gross Minority Interest")

    cfo   = row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = row(cf, "Capital Expenditure", "Purchase Of PPE")
    fcf   = row(cf, "Free Cash Flow")
    if fcf is None and cfo is not None and capex is not None:
        fcf = cfo + capex

    cfo_s   = full_row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex_s = full_row(cf, "Capital Expenditure", "Purchase Of PPE")
    fcf_norm = None
    if cfo_s is not None and capex_s is not None:
        merged = (cfo_s + capex_s).dropna()
        if not merged.empty:
            fcf_norm = f(merged.mean())

    dps = None
    try:
        d = t.dividends
        if d is not None and not d.empty:
            cut = pd.Timestamp.now(tz=d.index.tz) - pd.DateOffset(years=1)
            last = d[d.index >= cut]
            if not last.empty:
                dps = f(last.sum())
    except Exception:
        pass
    if dps is None:
        dps = f(info.get("dividendRate"))

    return {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector"),
        "currency": info.get("currency") or "",
        "fin_currency": info.get("financialCurrency") or info.get("currency") or "",
        "price": price, "shares": shares,
        "mktcap": f(info.get("marketCap")) or ((price*shares) if (price and shares) else None),
        "beta": f(info.get("beta")) or 1.0,
        "revenue": revenue, "ebit": ebit, "ebitda": ebitda, "net_income": net_inc,
        "interest": abs(interest) if interest else None, "tax_rate": tax_rate,
        "total_debt": total_debt, "cash": cash, "equity_bv": equity_bv,
        "cfo": cfo, "capex": capex, "fcf": fcf, "fcf_norm": fcf_norm,
        "dps": dps if (dps and dps > 0) else None,
        "eps_t": f(info.get("trailingEps")), "eps_f": f(info.get("forwardEps")),
        "bvps": f(info.get("bookValue")),
    }

# =============================================================
#  MODELLI
# =============================================================
def wacc(beta, rf, erp, kd_pretax, tax, e, d):
    ke = rf + beta * erp
    kd = kd_pretax * (1 - tax)
    v = e + d
    return ke if v <= 0 else ke*(e/v) + kd*(d/v)

def dcf_fcff(fcf0, g, years, term_g, discount, net_debt, shares):
    if not all(v is not None for v in [fcf0, discount, shares]) or shares <= 0 or discount <= term_g:
        return None
    pv = 0.0; cf = fcf0
    for yr in range(1, years+1):
        cf *= (1 + g)
        pv += cf / (1 + discount)**yr
    tv = cf * (1 + term_g) / (discount - term_g)
    pv += tv / (1 + discount)**years
    return (pv - (net_debt or 0)) / shares

def dcf_diagnose(fcf0, g, years, term_g, discount, net_debt, shares):
    """Restituisce (enterprise_value, equity_value, fair_value, lista_avvisi).
    Spiega in modo leggibile perche' il DCF e' negativo o inaffidabile."""
    warns = []
    if discount is None or shares in (None, 0):
        return None, None, None, ["Dati insufficienti (WACC o numero azioni mancante)."]
    if discount <= term_g:
        warns.append(f"WACC ({discount*100:.1f}%) <= crescita terminale ({term_g*100:.1f}%): "
                     f"il valore terminale diventa infinito/negativo. Abbassa la crescita terminale.")
        return None, None, None, warns

    # Enterprise value (senza togliere il debito)
    pv = 0.0; cf = fcf0 if fcf0 is not None else 0.0
    for yr in range(1, years+1):
        cf *= (1 + g)
        pv += cf / (1 + discount)**yr
    tv = cf * (1 + term_g) / (discount - term_g)
    pv += tv / (1 + discount)**years
    ev = pv
    nd = net_debt or 0
    equity = ev - nd
    fv = equity / shares

    # diagnosi
    if fcf0 is None:
        warns.append("FCF di partenza non disponibile: impossibile calcolare un DCF affidabile.")
    elif fcf0 < 0:
        warns.append(f"FCF di partenza NEGATIVO ({fmt_big(fcf0)}): l'azienda sta bruciando cassa. "
                     f"Su questo profilo il DCF non e' lo strumento adatto - usa i multipli (P/Sales) o scenari.")
    if ev > 0 and nd > ev:
        warns.append(f"Debito netto ({fmt_big(nd)}) SUPERA l'enterprise value ({fmt_big(ev)}): "
                     f"cio' che resta agli azionisti e' negativo. Titolo molto indebitato, "
                     f"il FCFF qui e' fragile (basta un EV stimato poco diverso per ribaltare il segno).")
    # term_g vicino al WACC -> TV dominante
    if 0 < (discount - term_g) < 0.02:
        peso_tv = (tv / (1 + discount)**years) / ev if ev else 0
        warns.append(f"WACC e crescita terminale molto vicini (spread {(discount-term_g)*100:.1f} punti): "
                     f"il valore terminale pesa per il {peso_tv*100:.0f}% del totale e rende il risultato instabile.")
    return ev, equity, fv, warns

def reverse_dcf_growth(price, fcf0, years, term_g, discount, net_debt, shares):
    if not all(v is not None for v in [price, fcf0, discount, shares]) or shares <= 0:
        return None
    if fcf0 <= 0 or discount <= term_g:
        return None
    target_equity = price * shares + (net_debt or 0)
    def pv_for(g):
        pv = 0.0; cf = fcf0
        for yr in range(1, years+1):
            cf *= (1 + g)
            pv += cf / (1 + discount)**yr
        tv = cf * (1 + term_g) / (discount - term_g)
        pv += tv / (1 + discount)**years
        return pv
    lo, hi = -0.50, 0.60
    if (pv_for(lo) - target_equity) * (pv_for(hi) - target_equity) > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if (pv_for(lo) - target_equity) * (pv_for(mid) - target_equity) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

def ddm_gordon(dps, ke, g):
    if dps is None or dps <= 0 or ke <= g:
        return None
    return dps * (1 + g) / (ke - g)

def multiple_fv(metric, mult):
    return metric*mult if (metric is not None and mult and mult > 0) else None

# =============================================================
#  NAVIGAZIONE
# =============================================================
section = st.sidebar.radio("Sezione", [":chart_with_upwards_trend: Valutazione", ":books: Corso di finanza"], index=0)

# #############################################################
#  SEZIONE 1 - VALUTAZIONE
# #############################################################
if section.endswith("Valutazione"):
    st.markdown("# :chart_with_upwards_trend: Valutatore Aziende")
    st.markdown('<p class="muted">DCF - Reverse DCF - Sensitivity - DDM - Multipli. '
                'Dati dai prospetti finanziari. Strumento informativo, non consulenza.</p>', unsafe_allow_html=True)

    PRESET = {
        "Apple":"AAPL","Microsoft":"MSFT","NVIDIA":"NVDA","Alphabet":"GOOGL","Amazon":"AMZN",
        "Coca-Cola":"KO","Johnson & Johnson":"JNJ","ENEL":"ENEL.MI","ENI":"ENI.MI",
        "Intesa Sanpaolo":"ISP.MI","Ferrari":"RACE.MI","LVMH":"MC.PA","Nestle":"NESN.SW","ASML":"ASML",
    }
    c1, c2 = st.columns([2, 3])
    with c1: choice = st.selectbox("Titolo dall'elenco", ["-"] + list(PRESET.keys()))
    with c2: manual = st.text_input("Oppure un ticker (es. AAPL, ENEL.MI)", "")
    ticker = manual.strip().upper() or (PRESET.get(choice) if choice != "-" else None)

    if not ticker:
        st.info("Seleziona un titolo o inserisci un ticker per iniziare.")
        st.stop()

    with st.spinner(f"Carico i dati di {ticker}..."):
        D = load_company(ticker)
        HM = historical_multiples(ticker, D["shares"]) if D["shares"] else {}

    price = D["price"]; ccy = D["currency"]
    if price is None:
        st.error(f"Prezzo non disponibile per **{ticker}**. Per Borsa Italiana usa il suffisso `.MI`.")
        st.stop()

    if D["fin_currency"] and ccy and D["fin_currency"] != ccy:
        st.warning(f":warning: Valute diverse: prezzo in **{ccy}**, bilanci in **{D['fin_currency']}**. "
                   f"I per-azione dai bilanci potrebbero non allinearsi al prezzo.")

    st.markdown(f"## {D['name']}  -  `{ticker}`")
    k = st.columns(5)
    for col, (l, v) in zip(k, [
        ("Prezzo", f"{fmt(price)} {ccy}"), ("Cap.", fmt_big(D["mktcap"])),
        ("Settore", D["sector"] or "N/D"), ("Beta", fmt(D["beta"])),
        ("Aliquota", fmt(D["tax_rate"]*100, 1, "%"))]):
        col.markdown(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)

    with st.expander(":page_facing_up: Dati di bilancio letti"):
        g1, g2, g3 = st.columns(3)
        with g1:
            st.markdown("**Conto economico**")
            st.write(f"Ricavi: {fmt_big(D['revenue'])}"); st.write(f"EBIT: {fmt_big(D['ebit'])}")
            st.write(f"EBITDA: {fmt_big(D['ebitda'])}"); st.write(f"Utile netto: {fmt_big(D['net_income'])}")
        with g2:
            st.markdown("**Stato patrimoniale**")
            st.write(f"Debito: {fmt_big(D['total_debt'])}"); st.write(f"Cassa: {fmt_big(D['cash'])}")
            st.write(f"Patrim. netto: {fmt_big(D['equity_bv'])}"); st.write(f"Azioni: {fmt_big(D['shares'])}")
        with g3:
            st.markdown("**Flussi di cassa**")
            st.write(f"CFO: {fmt_big(D['cfo'])}"); st.write(f"Capex: {fmt_big(D['capex'])}")
            st.write(f"FCF ultimo: {fmt_big(D['fcf'])}"); st.write(f"FCF medio: {fmt_big(D['fcf_norm'])}")

    try:
        h = yf.Ticker(ticker).history(period="1y")
        if not h.empty: st.line_chart(h["Close"], height=200)
    except Exception:
        pass

    net_debt = (D["total_debt"] or 0) - (D["cash"] or 0)

    # ---------- PARAMETRI ----------
    st.sidebar.markdown("## :gear: Parametri")
    st.sidebar.markdown("### Costo del capitale")
    rf  = st.sidebar.slider("Risk-free (%)", 0.0, 8.0, 3.5, 0.1)/100
    erp = st.sidebar.slider("Equity risk premium (%)", 3.0, 10.0, 5.5, 0.1)/100
    beta_in = st.sidebar.number_input("Beta", value=float(round(D["beta"],2)), step=0.05)
    kd_auto = (D["interest"]/D["total_debt"]) if (D["interest"] and D["total_debt"]) else 0.05
    kd = st.sidebar.slider("Costo debito ante imposte (%)", 0.0, 15.0,
                           float(round(min(max(kd_auto*100,1.0),12.0),1)), 0.1)/100
    ke = rf + beta_in*erp
    wacc_val = wacc(beta_in, rf, erp, kd, D["tax_rate"], D["mktcap"] or 0, D["total_debt"] or 0)
    st.sidebar.markdown(f"**Ke:** {ke*100:.2f}%  -  **WACC:** {wacc_val*100:.2f}%")

    st.sidebar.markdown("### Crescita DCF")
    use_norm = st.sidebar.checkbox("Usa FCF medio (normalizzato)", value=True,
                                   help="Parte dalla media pluriennale invece che dall'ultimo anno.")
    g_fcf  = st.sidebar.slider("Crescita FCF (%/anno)", -5.0, 25.0, 6.0, 0.5)/100
    years  = st.sidebar.slider("Anni espliciti", 3, 15, 7, 1)
    term_g = st.sidebar.slider("Crescita terminale (%)", 0.0, 4.0, 2.0, 0.25)/100
    st.sidebar.markdown("### Crescita DDM")
    g_ddm = st.sidebar.slider("Crescita dividendi (%)", 0.0, 8.0, 2.5, 0.25)/100

    fcf_base = D["fcf_norm"] if (use_norm and D["fcf_norm"]) else D["fcf"]

    # ---------- FAIR VALUE ----------
    st.markdown("## :dart: Fair Value per modello")
    fv_ddm = ddm_gordon(D["dps"], ke, g_ddm)
    if not (D["dps"] and price and D["dps"]/price >= 0.005):
        fv_ddm = None

    sh = D["shares"]
    eps   = D["eps_f"] or D["eps_t"] or ((D["net_income"]/sh) if (D["net_income"] and sh) else None)
    bvps  = D["bvps"] or ((D["equity_bv"]/sh) if (D["equity_bv"] and sh) else None)
    salesps  = (D["revenue"]/sh) if (D["revenue"] and sh) else None
    ebitdaps = (D["ebitda"]/sh) if (D["ebitda"] and sh) else None
    fcfps    = (fcf_base/sh) if (fcf_base and sh) else None

    # default multipli = mediana storica del titolo (con fallback prudente)
    def hist_default(key, fallback):
        v = HM.get(key, (None, 0))
        return (round(v[0], 1) if v[0] else fallback), (v[1] if v else 0)

    pe_def,   pe_n   = hist_default("P/E", 18.0)
    pb_def,   pb_n   = hist_default("P/BV", 2.5)
    ps_def,   ps_n   = hist_default("P/Sales", 3.0)
    pebd_def, pebd_n = hist_default("P/EBITDA", 12.0)
    pfcf_def, pfcf_n = hist_default("P/FCF", 18.0)

    st.markdown("#### Multipli attesi")
    st.caption("Valori di default = **mediana storica del titolo** (ultimi anni disponibili su Yahoo). "
               "Modificabili: cambia il numero se ritieni che il multiplo storico non sia piu appropriato. "
               "Il numerino sotto indica su quanti anni e calcolata la mediana (piu anni = piu affidabile).")
    m = st.columns(5)
    with m[0]:
        pe_x = st.number_input("P/E", value=float(pe_def), step=0.5)
        st.caption(f"storico: {fmt(HM.get('P/E',(None,0))[0],1)} ({pe_n} anni)")
    with m[1]:
        pb_x = st.number_input("P/BV", value=float(pb_def), step=0.1)
        st.caption(f"storico: {fmt(HM.get('P/BV',(None,0))[0],1)} ({pb_n} anni)")
    with m[2]:
        ps_x = st.number_input("P/Sales", value=float(ps_def), step=0.1)
        st.caption(f"storico: {fmt(HM.get('P/Sales',(None,0))[0],1)} ({ps_n} anni)")
    with m[3]:
        pebd_x = st.number_input("P/EBITDA", value=float(pebd_def), step=0.5)
        st.caption(f"storico: {fmt(HM.get('P/EBITDA',(None,0))[0],1)} ({pebd_n} anni)")
    with m[4]:
        pfcf_x = st.number_input("P/FCF", value=float(pfcf_def), step=0.5)
        st.caption(f"storico: {fmt(HM.get('P/FCF',(None,0))[0],1)} ({pfcf_n} anni)")

    if max(pe_n, pb_n, ps_n, pebd_n, pfcf_n) < 2:
        st.info("Storico insufficiente per calcolare multipli affidabili: sono stati usati valori di default generici. "
                "Frequente per titoli con pochi anni di bilanci su Yahoo.")

    models = [
        ("DCF - FCFF", dcf_fcff(fcf_base, g_fcf, years, term_g, wacc_val, net_debt, sh),
         "Sconta i flussi di cassa liberi al WACC. Cardine per societa mature con FCF positivo."),
        ("DDM - Gordon", fv_ddm, "Sconta i dividendi al costo dell'equity. Solo se yield >=0,5%."),
        ("P/E", multiple_fv(eps, pe_x), "EPS x P/E (default = mediana storica)."),
        ("P/BV", multiple_fv(bvps, pb_x), "Book value/azione x P/BV. Rilevante per banche/assicurazioni."),
        ("P/Sales", multiple_fv(salesps, ps_x), "Ricavi/azione x P/Sales. Per growth o societa in perdita."),
        ("P/EBITDA", multiple_fv(ebitdaps, pebd_x), "EBITDA/azione x multiplo. Per business capital-intensive."),
        ("P/FCF", multiple_fv(fcfps, pfcf_x), "FCF/azione x multiplo."),
    ]

    def delta_html(fv):
        if fv is None or not price: return '<span class="muted">N/D</span>'
        up = (fv/price-1)*100; cls = "fv-up" if up >= 0 else "fv-dn"
        return f'<b>{fmt(fv)} {ccy}</b> &nbsp;<span class="{cls}">({up:+.1f}%)</span>'

    st.markdown('<div class="card">', unsafe_allow_html=True)
    for name, fv, desc in models:
        st.markdown(f"**{name}** - {delta_html(fv)}", unsafe_allow_html=True)
        st.markdown(f'<span class="muted">{desc}</span>', unsafe_allow_html=True)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ---------- DIAGNOSTICA DCF ----------
    ev, eq, fv_check, warns = dcf_diagnose(fcf_base, g_fcf, years, term_g, wacc_val, net_debt, sh)
    dcf_value = models[0][1]
    show_diag = (dcf_value is None) or (dcf_value is not None and dcf_value < 0) or bool(warns)
    if show_diag:
        with st.expander(":mag: Perche' il DCF ha questo risultato? (diagnostica)", expanded=(dcf_value is None or (dcf_value is not None and dcf_value < 0))):
            if ev is not None:
                d1, d2, d3 = st.columns(3)
                d1.markdown(f'<div class="kpi"><div class="l">Enterprise Value</div><div class="v">{fmt_big(ev)}</div></div>', unsafe_allow_html=True)
                d2.markdown(f'<div class="kpi"><div class="l">- Debito netto</div><div class="v">{fmt_big(net_debt)}</div></div>', unsafe_allow_html=True)
                d3.markdown(f'<div class="kpi"><div class="l">= Equity / azioni</div><div class="v">{fmt(fv_check)} {ccy}</div></div>', unsafe_allow_html=True)
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                st.caption(f"Catena del calcolo: FCF base **{fmt_big(fcf_base)}**, cresce al **{g_fcf*100:.1f}%**/anno per "
                           f"**{years} anni**, scontato al WACC **{wacc_val*100:.1f}%**, + valore terminale "
                           f"(crescita perpetua **{term_g*100:.1f}%**) = Enterprise Value. Tolto il debito netto e "
                           f"diviso per **{fmt_big(sh)}** azioni.")
            if warns:
                for w in warns:
                    st.warning(w)
            else:
                st.success("Nessuna anomalia rilevata: il DCF e' calcolabile e i parametri sono coerenti.")

    # ---------- REVERSE DCF ----------
    st.markdown("## :arrows_counterclockwise: Reverse DCF - cosa sta scontando il mercato")
    st.markdown('<p class="muted">Invece di chiedere "quanto vale?", calcola la crescita del FCF che il prezzo attuale '
                'implica. Poi ti chiedi: e plausibile?</p>', unsafe_allow_html=True)
    g_impl = reverse_dcf_growth(price, fcf_base, years, term_g, wacc_val, net_debt, sh)
    if g_impl is not None:
        cc = st.columns(3)
        cc[0].markdown(f'<div class="kpi"><div class="l">Crescita FCF implicita</div>'
                       f'<div class="v">{g_impl*100:+.1f}%/anno</div></div>', unsafe_allow_html=True)
        cc[1].markdown(f'<div class="kpi"><div class="l">Per {years} anni, poi</div>'
                       f'<div class="v">{term_g*100:.1f}% perpetua</div></div>', unsafe_allow_html=True)
        plaus = "molto aggressiva" if g_impl > 0.15 else ("ambiziosa" if g_impl > 0.08 else
                ("moderata" if g_impl > 0.02 else "conservativa/pessimista"))
        cc[2].markdown(f'<div class="kpi"><div class="l">Lettura</div>'
                       f'<div class="v">{plaus}</div></div>', unsafe_allow_html=True)
        st.caption(f"Al WACC del {wacc_val*100:.1f}%, il prezzo di {fmt(price)} {ccy} e coerente con una crescita "
                   f"del FCF del {g_impl*100:.1f}% annuo per {years} anni. Confrontala con la crescita storica e "
                   f"con le attese di settore: se ti sembra irrealistica, il titolo e caro (o a sconto).")
    else:
        st.info("Reverse DCF non calcolabile con i dati/parametri attuali (es. FCF non positivo).")

    # ---------- SENSITIVITY ----------
    st.markdown("## :thermometer: Sensitivity - fragilita del DCF")
    st.markdown('<p class="muted">Il fair value del DCF al variare di WACC (righe) e crescita terminale (colonne).</p>',
                unsafe_allow_html=True)
    if fcf_base and sh:
        wacc_range = [wacc_val + d for d in (-0.015, -0.0075, 0, 0.0075, 0.015)]
        tg_range   = [max(0.0, term_g + d) for d in (-0.01, -0.005, 0, 0.005, 0.01)]
        grid = []
        for w in wacc_range:
            r = []
            for tg in tg_range:
                r.append(dcf_fcff(fcf_base, g_fcf, years, tg, w, net_debt, sh))
            grid.append(r)
        sens = pd.DataFrame(grid,
                            index=[f"WACC {w*100:.1f}%" for w in wacc_range],
                            columns=[f"g {tg*100:.1f}%" for tg in tg_range])
        st.dataframe(sens.style.format(lambda x: fmt(x) if x is not None else "N/D")
                     .background_gradient(cmap="RdYlGn", axis=None), use_container_width=True)
        st.caption(f"Prezzo attuale di confronto: **{fmt(price)} {ccy}**. "
                   f"Celle verdi = fair value sopra prezzo, rosse = sotto.")
    else:
        st.info("Sensitivity non disponibile (FCF non utilizzabile).")

    # ---------- SINTESI ----------
    st.markdown("## :compass: Sintesi")
    valid = [(n, fv) for n, fv, _ in models if fv is not None]
    if valid:
        fvs = [v for _, v in valid]
        fv_median = float(np.median(fvs)); upside = (fv_median/price-1)*100
        if upside <= -20:   verdict, cls = "Sopravvalutata", "fv-dn"
        elif upside <= -8:  verdict, cls = "Leggermente cara", "fv-dn"
        elif upside < 10:   verdict, cls = "In linea col prezzo", "muted"
        elif upside < 25:   verdict, cls = "Potenzialmente sottovalutata", "fv-up"
        else:               verdict, cls = "Marcatamente sottovalutata", "fv-up"
        sc = st.columns(4)
        sc[0].markdown(f'<div class="kpi"><div class="l">Prezzo</div><div class="v">{fmt(price)} {ccy}</div></div>', unsafe_allow_html=True)
        sc[1].markdown(f'<div class="kpi"><div class="l">FV mediano</div><div class="v">{fmt(fv_median)} {ccy}</div></div>', unsafe_allow_html=True)
        sc[2].markdown(f'<div class="kpi"><div class="l">Range</div><div class="v">{fmt(min(fvs))}-{fmt(max(fvs))}</div></div>', unsafe_allow_html=True)
        sc[3].markdown(f'<div class="kpi"><div class="l">Upside</div><div class="v {cls}">{upside:+.1f}%</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card" style="margin-top:12px"><span class="pill">{verdict}</span> '
                    f'<span class="muted">Mediana di {len(valid)} modelli. Range ampio = i metodi non concordano = '
                    f'maggiore incertezza.</span></div>', unsafe_allow_html=True)
        chart_df = pd.DataFrame({"Fair Value": fvs}, index=[n for n, _ in valid])
        chart_df.loc["> PREZZO"] = price
        st.bar_chart(chart_df, height=280)
    else:
        st.info("Nessun modello applicabile con i dati disponibili.")

    st.markdown("---")
    st.caption(":warning: Strumento informativo. Dati da Yahoo Finance, possibili errori/ritardi. "
               "Le valutazioni dipendono dalle assunzioni. Non e consulenza finanziaria.")

# #############################################################
#  SEZIONE 2 - CORSO DI FINANZA
# #############################################################
else:
    st.markdown("# :books: Corso di finanza - dalle basi")
    st.markdown('<p class="muted">Un percorso che parte da zero e arriva ai modelli usati nella sezione Valutazione. '
                'Si aggiunge una lezione alla volta.</p>', unsafe_allow_html=True)

    LESSONS = [
        {
            "n": 1,
            "title": "Cos'e un'azione",
            "subtitle": "La quota di proprieta di un'azienda",
            "body": """
**Un'azione e una frazione di proprieta di una societa.** Se una societa ha emesso 1.000 azioni
e tu ne possiedi 10, possiedi l'1% dell'azienda: l'1% degli utili, dei beni e del diritto di voto.

**Perche esistono?** Un'azienda che vuole crescere ha bisogno di capitale. Puo indebitarsi (chiedere
prestiti) oppure vendere quote di se stessa a investitori. Vendendo azioni raccoglie denaro senza
obbligo di restituirlo: in cambio cede una parte della proprieta e degli utili futuri.

**Da cosa guadagni come azionista?** Da due fonti:
- **Capital gain**: l'azione aumenta di valore e la rivendi a un prezzo piu alto.
- **Dividendi**: l'azienda distribuisce parte dei suoi utili agli azionisti, di solito ogni anno.

**Il prezzo di un'azione** non e il valore "vero" dell'azienda diviso per le azioni. E il punto in cui
si incontrano chi vuole comprare e chi vuole vendere, in ogni istante. Riflette le *aspettative* del
mercato sugli utili futuri. Tutto il mestiere della valutazione consiste nel chiedersi: questo prezzo
e giustificato dai fondamentali, o no?
""",
            "key": "Possedere un'azione = possedere una frazione dell'azienda e dei suoi utili futuri. Il prezzo riflette le aspettative, non un valore oggettivo.",
        },
        {
            "n": 2,
            "title": "Il bilancio: le tre tabelle che raccontano un'azienda",
            "subtitle": "Stato patrimoniale, conto economico, rendiconto finanziario",
            "body": """
Per valutare un'azienda devi saper leggere il suo **bilancio**, composto da tre prospetti che
rispondono a tre domande diverse.

**1. Stato patrimoniale (balance sheet) - "Cosa possiede e cosa deve?"**
E una fotografia in un istante. Si divide in:
- **Attivita**: tutto cio che l'azienda possiede (cassa, magazzino, immobili, macchinari, crediti).
- **Passivita**: tutto cio che deve (debiti verso banche, fornitori, dipendenti).
- **Patrimonio netto**: la differenza. E cio che resta agli azionisti se si vendesse tutto e si
pagassero i debiti. Vale sempre: *Attivita = Passivita + Patrimonio netto*.

**2. Conto economico (income statement) - "Quanto ha guadagnato in un periodo?"**
E un film che copre un anno (o un trimestre). Parte dai **ricavi** e sottrae i costi a strati:
- Ricavi - costi di produzione = **margine lordo**
- - costi operativi = **EBIT** (utile operativo)
- - interessi e tasse = **utile netto** (la "bottom line", cio che resta agli azionisti).

**3. Rendiconto finanziario (cash flow statement) - "Quanta cassa e entrata e uscita davvero?"**
L'utile contabile non e cassa: si puo avere utile e non avere liquidita (e viceversa). Questo prospetto
segue i soldi veri, divisi in flussi da attivita operativa, di investimento e di finanziamento.

**Perche tre tabelle?** Perche un'azienda sana deve esserlo su tutti e tre i fronti: solida nel
patrimonio, redditizia nel conto economico, capace di generare cassa nel rendiconto. Un'azienda puo
sembrare profittevole e fallire lo stesso, se non genera liquidita.
""",
            "key": "Stato patrimoniale = cosa possiede/deve (foto). Conto economico = quanto guadagna (film). Rendiconto = la cassa reale. Servono tutti e tre.",
        },
        {
            "n": 3,
            "title": "Utile vs cassa: perche EBITDA e Free Cash Flow",
            "subtitle": "La differenza che manda in errore i principianti",
            "body": """
Il concetto piu importante e meno intuitivo: **l'utile contabile non e denaro in banca.**

Esempio: vendi merce per 100 a un cliente che paghera fra 6 mesi. In conto economico registri subito
100 di ricavo e magari 30 di utile. Ma in cassa, oggi, non e entrato nulla. Sei "profittevole" e
contemporaneamente a corto di liquidita.

Per questo gli analisti guardano misure diverse a seconda di cosa vogliono sapere:

**EBITDA** = utile prima di interessi, tasse, svalutazioni e ammortamenti. Serve ad avvicinarsi alla
redditivita *operativa* pulita, togliendo voci non monetarie (ammortamenti) e scelte finanziarie/fiscali.
Utile per confrontare aziende diverse, ma **non e cassa**: ignora gli investimenti necessari a far girare
l'azienda.

**Free Cash Flow (FCF)** = la cassa che l'azienda genera *dopo* aver pagato gli investimenti necessari
(capex). E il numero piu vicino a "quanti soldi liberi produce davvero". Formula base:

<span class="formula">FCF = Flusso di cassa operativo - Capex</span>

Il FCF e il cuore della valutazione DCF: il valore di un'azienda e la somma dei flussi di cassa liberi
che generera in futuro, scontati a oggi. Se capisci il FCF, capisci il 70% della valutazione.

**Attenzione**: un singolo anno di FCF puo essere distorto (un grande investimento una-tantum, una
vendita straordinaria). Per questo nella sezione Valutazione puoi usare il **FCF medio** su piu anni:
riduce il rumore.
""",
            "key": "Utile != cassa. EBITDA = redditivita operativa (ma non e cassa). FCF = cassa libera dopo gli investimenti, ed e la base del DCF.",
        },
    ]
    # ---- FINE ELENCO LEZIONI ----

    titles = [f"Lezione {l['n']} - {l['title']}" for l in LESSONS]
    sel = st.selectbox("Scegli la lezione", titles, index=len(titles)-1)
    lesson = LESSONS[titles.index(sel)]

    st.markdown(f"### Lezione {lesson['n']} - {lesson['title']}")
    st.markdown(f'<p class="muted">{lesson["subtitle"]}</p>', unsafe_allow_html=True)
    st.markdown(f'<div class="lesson">{lesson["body"]}</div>', unsafe_allow_html=True)
    st.success(f":bulb: **In una frase:** {lesson['key']}")

    st.markdown("---")
    st.markdown(f"**Lezioni pubblicate:** {len(LESSONS)} - "
                f"Prossima in arrivo: Lezione {len(LESSONS)+1}")
    st.caption("Il corso cresce una lezione alla volta. Prossime tappe: i multipli (P/E, P/BV), "
               "il valore temporale del denaro, il costo del capitale (WACC), il DCF passo passo, "
               "e infine la valutazione di banche e assicurazioni.")
