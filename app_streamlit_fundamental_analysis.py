import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================
#  VALUTATORE AZIENDE + CORSO DI FINANZA
#  - Valutazione: DCF (FCFF) · Reverse DCF · Sensitivity · DDM · Multipli
#  - Corso: lezioni dalle basi, pensato per crescere 1 lezione/settimana
#  Dati letti dai prospetti finanziari (non solo da .info).
# =============================================================

st.set_page_config(page_title="Valutatore Aziende", layout="wide", page_icon="📈")

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

def row_series(df, *names):
    """Restituisce l'intera riga (più anni) per medie/normalizzazione."""
    if df is None or df.empty: return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if not s.empty:
                return s.astype(float)
    return None

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

    # FCF normalizzato (media degli anni disponibili)
    cfo_s   = row_series(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex_s = row_series(cf, "Capital Expenditure", "Purchase Of PPE")
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

def reverse_dcf_growth(price, fcf0, years, term_g, discount, net_debt, shares):
    """Trova la crescita g (anni espliciti) che rende fair value == prezzo.
    Restituisce g implicita, oppure None se non trovata nel range."""
    if not all(v is not None for v in [price, fcf0, discount, shares]) or shares <= 0:
        return None
    target_equity = price * shares + (net_debt or 0)
    lo, hi = -0.50, 0.60
    def pv_for(g):
        pv = 0.0; cf = fcf0
        for yr in range(1, years+1):
            cf *= (1 + g)
            pv += cf / (1 + discount)**yr
        tv = cf * (1 + term_g) / (discount - term_g)
        pv += tv / (1 + discount)**years
        return pv
    # bisezione
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
section = st.sidebar.radio("Sezione", ["📈 Valutazione", "📚 Corso di finanza"], index=0)

# #############################################################
#  SEZIONE 1 — VALUTAZIONE
# #############################################################
if section == "📈 Valutazione":
    st.markdown("# 📈 Valutatore Aziende")
    st.markdown('<p class="muted">DCF · Reverse DCF · Sensitivity · DDM · Multipli. '
                'Dati dai prospetti finanziari. Strumento informativo, non consulenza.</p>', unsafe_allow_html=True)

    PRESET = {
        "Apple":"AAPL","Microsoft":"MSFT","NVIDIA":"NVDA","Alphabet":"GOOGL","Amazon":"AMZN",
        "Coca-Cola":"KO","Johnson & Johnson":"JNJ","ENEL":"ENEL.MI","ENI":"ENI.MI",
        "Intesa Sanpaolo":"ISP.MI","Ferrari":"RACE.MI","LVMH":"MC.PA","Nestlé":"NESN.SW","ASML":"ASML",
    }
    c1, c2 = st.columns([2, 3])
    with c1: choice = st.selectbox("Titolo dall'elenco", ["—"] + list(PRESET.keys()))
    with c2: manual = st.text_input("Oppure un ticker (es. AAPL, ENEL.MI)", "")
    ticker = manual.strip().upper() or (PRESET.get(choice) if choice != "—" else None)

    if not ticker:
        st.info("Seleziona un titolo o inserisci un ticker per iniziare.")
        st.stop()

    with st.spinner(f"Carico i dati di {ticker}…"):
        D = load_company(ticker)

    price = D["price"]; ccy = D["currency"]
    if price is None:
        st.error(f"Prezzo non disponibile per **{ticker}**. Per Borsa Italiana usa il suffisso `.MI`.")
        st.stop()

    if D["fin_currency"] and ccy and D["fin_currency"] != ccy:
        st.warning(f"⚠️ Valute diverse: prezzo in **{ccy}**, bilanci in **{D['fin_currency']}**. "
                   f"I per-azione dai bilanci potrebbero non allinearsi al prezzo.")

    st.markdown(f"## {D['name']}  ·  `{ticker}`")
    k = st.columns(5)
    for col, (l, v) in zip(k, [
        ("Prezzo", f"{fmt(price)} {ccy}"), ("Cap.", fmt_big(D["mktcap"])),
        ("Settore", D["sector"] or "N/D"), ("Beta", fmt(D["beta"])),
        ("Aliquota", fmt(D["tax_rate"]*100, 1, "%"))]):
        col.markdown(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)

    with st.expander("📑 Dati di bilancio letti"):
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
    st.sidebar.markdown("## ⚙️ Parametri")
    st.sidebar.markdown("### Costo del capitale")
    rf  = st.sidebar.slider("Risk-free (%)", 0.0, 8.0, 3.5, 0.1)/100
    erp = st.sidebar.slider("Equity risk premium (%)", 3.0, 10.0, 5.5, 0.1)/100
    beta_in = st.sidebar.number_input("Beta", value=float(round(D["beta"],2)), step=0.05)
    kd_auto = (D["interest"]/D["total_debt"]) if (D["interest"] and D["total_debt"]) else 0.05
    kd = st.sidebar.slider("Costo debito ante imposte (%)", 0.0, 15.0,
                           float(round(min(max(kd_auto*100,1.0),12.0),1)), 0.1)/100
    ke = rf + beta_in*erp
    wacc_val = wacc(beta_in, rf, erp, kd, D["tax_rate"], D["mktcap"] or 0, D["total_debt"] or 0)
    st.sidebar.markdown(f"**Ke:** {ke*100:.2f}% &nbsp;·&nbsp; **WACC:** {wacc_val*100:.2f}%")

    st.sidebar.markdown("### Crescita DCF")
    use_norm = st.sidebar.checkbox("Usa FCF medio (normalizzato)", value=True,
                                   help="Parte dalla media pluriennale invece che dall'ultimo anno (meno sensibile ad anni anomali).")
    g_fcf  = st.sidebar.slider("Crescita FCF (%/anno)", -5.0, 25.0, 6.0, 0.5)/100
    years  = st.sidebar.slider("Anni espliciti", 3, 15, 7, 1)
    term_g = st.sidebar.slider("Crescita terminale (%)", 0.0, 4.0, 2.0, 0.25)/100
    st.sidebar.markdown("### Crescita DDM")
    g_ddm = st.sidebar.slider("Crescita dividendi (%)", 0.0, 8.0, 2.5, 0.25)/100

    fcf_base = D["fcf_norm"] if (use_norm and D["fcf_norm"]) else D["fcf"]

    # ---------- FAIR VALUE ----------
    st.markdown("## 🎯 Fair Value per modello")
    fv_dcf = dcf_fcff(fcf_base, g_fcf, years, term_g, wacc_val, net_debt, D["shares"])
    fv_ddm = ddm_gordon(D["dps"], ke, g_ddm)
    if not (D["dps"] and price and D["dps"]/price >= 0.005):
        fv_ddm = None

    sh = D["shares"]
    eps   = D["eps_f"] or D["eps_t"] or ((D["net_income"]/sh) if (D["net_income"] and sh) else None)
    bvps  = D["bvps"] or ((D["equity_bv"]/sh) if (D["equity_bv"] and sh) else None)
    salesps  = (D["revenue"]/sh) if (D["revenue"] and sh) else None
    ebitdaps = (D["ebitda"]/sh) if (D["ebitda"] and sh) else None
    fcfps    = (fcf_base/sh) if (fcf_base and sh) else None

    st.markdown("#### Multipli attesi (modificabili)")
    m = st.columns(5)
    with m[0]: pe_x   = st.number_input("P/E", value=18.0, step=0.5)
    with m[1]: pb_x   = st.number_input("P/BV", value=2.5, step=0.1)
    with m[2]: ps_x   = st.number_input("P/Sales", value=3.0, step=0.1)
    with m[3]: pebd_x = st.number_input("P/EBITDA", value=12.0, step=0.5)
    with m[4]: pfcf_x = st.number_input("P/FCF", value=18.0, step=0.5)

    models = [
        ("DCF — FCFF", dcf_fcff(fcf_base, g_fcf, years, term_g, wacc_val, net_debt, sh),
         "Sconta i flussi di cassa liberi al WACC. Cardine per società mature con FCF positivo."),
        ("DDM — Gordon", fv_ddm, "Sconta i dividendi al costo dell'equity. Solo se yield ≥0,5%."),
        ("P/E", multiple_fv(eps, pe_x), "EPS × P/E atteso."),
        ("P/BV", multiple_fv(bvps, pb_x), "Book value/azione × P/BV. Rilevante per banche/assicurazioni."),
        ("P/Sales", multiple_fv(salesps, ps_x), "Ricavi/azione × P/Sales. Per growth o società in perdita."),
        ("P/EBITDA", multiple_fv(ebitdaps, pebd_x), "EBITDA/azione × multiplo. Per business capital-intensive."),
        ("P/FCF", multiple_fv(fcfps, pfcf_x), "FCF/azione × multiplo."),
    ]

    def delta_html(fv):
        if fv is None or not price: return '<span class="muted">N/D</span>'
        up = (fv/price-1)*100; cls = "fv-up" if up >= 0 else "fv-dn"
        return f'<b>{fmt(fv)} {ccy}</b> &nbsp;<span class="{cls}">({up:+.1f}%)</span>'

    st.markdown('<div class="card">', unsafe_allow_html=True)
    for name, fv, desc in models:
        st.markdown(f"**{name}** — {delta_html(fv)}", unsafe_allow_html=True)
        st.markdown(f'<span class="muted">{desc}</span>', unsafe_allow_html=True)
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # ---------- REVERSE DCF ----------
    st.markdown("## 🔄 Reverse DCF — cosa sta scontando il mercato")
    st.markdown('<p class="muted">Invece di chiedere "quanto vale?", calcola la crescita del FCF che il prezzo attuale '
                'implica. Poi ti chiedi: è plausibile?</p>', unsafe_allow_html=True)
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
        st.caption(f"Al WACC del {wacc_val*100:.1f}%, il prezzo di {fmt(price)} {ccy} è coerente con una crescita "
                   f"del FCF del {g_impl*100:.1f}% annuo per {years} anni. Confrontala con la crescita storica e "
                   f"con le attese di settore: se ti sembra irrealistica, il titolo è caro (o a sconto).")
    else:
        st.info("Reverse DCF non calcolabile con i dati/parametri attuali (es. FCF non positivo).")

    # ---------- SENSITIVITY ----------
    st.markdown("## 🌡️ Sensitivity — fragilità del DCF")
    st.markdown('<p class="muted">Il fair value del DCF al variare di WACC (righe) e crescita terminale (colonne). '
                'Mostra quanto il numero dipende dalle ipotesi.</p>', unsafe_allow_html=True)
    if fcf_base and sh:
        wacc_range = [wacc_val + d for d in (-0.015, -0.0075, 0, 0.0075, 0.015)]
        tg_range   = [max(0.0, term_g + d) for d in (-0.01, -0.005, 0, 0.005, 0.01)]
        grid = []
        for w in wacc_range:
            r = []
            for tg in tg_range:
                v = dcf_fcff(fcf_base, g_fcf, years, tg, w, net_debt, sh)
                r.append(v)
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
    st.markdown("## 🧭 Sintesi")
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
        sc[2].markdown(f'<div class="kpi"><div class="l">Range</div><div class="v">{fmt(min(fvs))}–{fmt(max(fvs))}</div></div>', unsafe_allow_html=True)
        sc[3].markdown(f'<div class="kpi"><div class="l">Upside</div><div class="v {cls}">{upside:+.1f}%</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card" style="margin-top:12px"><span class="pill">{verdict}</span> '
                    f'<span class="muted">Mediana di {len(valid)} modelli. Range ampio = i metodi non concordano = '
                    f'maggiore incertezza.</span></div>', unsafe_allow_html=True)
        chart_df = pd.DataFrame({"Fair Value": fvs}, index=[n for n, _ in valid])
        chart_df.loc["▶ PREZZO"] = price
        st.bar_chart(chart_df, height=280)
    else:
        st.info("Nessun modello applicabile con i dati disponibili.")

    st.markdown("---")
    st.caption("⚠️ Strumento informativo. Dati da Yahoo Finance, possibili errori/ritardi. "
               "Le valutazioni dipendono dalle assunzioni. Non è consulenza finanziaria.")

# #############################################################
#  SEZIONE 2 — CORSO DI FINANZA
#  Per aggiungere una lezione: copia un blocco {...} dentro LESSONS.
#  Le lezioni appaiono automaticamente nel menu.
# #############################################################
else:
    st.markdown("# 📚 Corso di finanza — dalle basi")
    st.markdown('<p class="muted">Un percorso che parte da zero e arriva ai modelli usati nella sezione Valutazione. '
                'Si aggiunge una lezione alla volta.</p>', unsafe_allow_html=True)

    # =========================================================
    #  ELENCO LEZIONI
    #  Ogni lezione = un dizionario. "body" accetta Markdown.
    #  Aggiungere la lezione N+1 = aggiungere un dizionario in fondo.
    # =========================================================
    LESSONS = [
        {
            "n": 1,
            "title": "Cos'è un'azione",
            "subtitle": "La quota di proprietà di un'azienda",
            "body": """
**Un'azione è una frazione di proprietà di una società.** Se una società ha emesso 1.000 azioni
e tu ne possiedi 10, possiedi l'1% dell'azienda: l'1% degli utili, dei beni e del diritto di voto.

**Perché esistono?** Un'azienda che vuole crescere ha bisogno di capitale. Può indebitarsi (chiedere
prestiti) oppure vendere quote di sé stessa a investitori. Vendendo azioni raccoglie denaro senza
obbligo di restituirlo: in cambio cede una parte della proprietà e degli utili futuri.

**Da cosa guadagni come azionista?** Da due fonti:
- **Capital gain**: l'azione aumenta di valore e la rivendi a un prezzo più alto.
- **Dividendi**: l'azienda distribuisce parte dei suoi utili agli azionisti, di solito ogni anno.

**Il prezzo di un'azione** non è il valore "vero" dell'azienda diviso per le azioni. È il punto in cui
si incontrano chi vuole comprare e chi vuole vendere, in ogni istante. Riflette le *aspettative* del
mercato sugli utili futuri. Tutto il mestiere della valutazione consiste nel chiedersi: questo prezzo
è giustificato dai fondamentali, o no?
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

**1. Stato patrimoniale (balance sheet) — "Cosa possiede e cosa deve?"**
È una fotografia in un istante. Si divide in:
- **Attività**: tutto ciò che l'azienda possiede (cassa, magazzino, immobili, macchinari, crediti).
- **Passività**: tutto ciò che deve (debiti verso banche, fornitori, dipendenti).
- **Patrimonio netto**: la differenza. È ciò che resta agli azionisti se si vendesse tutto e si
pagassero i debiti. Vale sempre: *Attività = Passività + Patrimonio netto*.

**2. Conto economico (income statement) — "Quanto ha guadagnato in un periodo?"**
È un film che copre un anno (o un trimestre). Parte dai **ricavi** e sottrae i costi a strati:
- Ricavi − costi di produzione = **margine lordo**
- − costi operativi = **EBIT** (utile operativo)
- − interessi e tasse = **utile netto** (la "bottom line", ciò che resta agli azionisti).

**3. Rendiconto finanziario (cash flow statement) — "Quanta cassa è entrata e uscita davvero?"**
L'utile contabile non è cassa: si può avere utile e non avere liquidità (e viceversa). Questo prospetto
segue i soldi veri, divisi in flussi da attività operativa, di investimento e di finanziamento.

**Perché tre tabelle?** Perché un'azienda sana deve esserlo su tutti e tre i fronti: solida nel
patrimonio, redditizia nel conto economico, capace di generare cassa nel rendiconto. Un'azienda può
sembrare profittevole e fallire lo stesso, se non genera liquidità.
""",
            "key": "Stato patrimoniale = cosa possiede/deve (foto). Conto economico = quanto guadagna (film). Rendiconto = la cassa reale. Servono tutti e tre.",
        },
        {
            "n": 3,
            "title": "Utile vs cassa: perché EBITDA e Free Cash Flow",
            "subtitle": "La differenza che manda in errore i principianti",
            "body": """
Il concetto più importante e meno intuitivo: **l'utile contabile non è denaro in banca.**

Esempio: vendi merce per 100 a un cliente che pagherà fra 6 mesi. In conto economico registri subito
100 di ricavo e magari 30 di utile. Ma in cassa, oggi, non è entrato nulla. Sei "profittevole" e
contemporaneamente a corto di liquidità.

Per questo gli analisti guardano misure diverse a seconda di cosa vogliono sapere:

**EBITDA** = utile prima di interessi, tasse, svalutazioni e ammortamenti. Serve ad avvicinarsi alla
redditività *operativa* pulita, togliendo voci non monetarie (ammortamenti) e scelte finanziarie/fiscali.
Utile per confrontare aziende diverse, ma **non è cassa**: ignora gli investimenti necessari a far girare
l'azienda.

**Free Cash Flow (FCF)** = la cassa che l'azienda genera *dopo* aver pagato gli investimenti necessari
(capex). È il numero più vicino a "quanti soldi liberi produce davvero". Formula base:

<span class="formula">FCF = Flusso di cassa operativo − Capex</span>

Il FCF è il cuore della valutazione DCF: il valore di un'azienda è la somma dei flussi di cassa liberi
che genererà in futuro, scontati a oggi. Se capisci il FCF, capisci il 70% della valutazione.

**Attenzione**: un singolo anno di FCF può essere distorto (un grande investimento una-tantum, una
vendita straordinaria). Per questo nella sezione Valutazione puoi usare il **FCF medio** su più anni:
riduce il rumore.
""",
            "key": "Utile ≠ cassa. EBITDA = redditività operativa (ma non è cassa). FCF = cassa libera dopo gli investimenti, ed è la base del DCF.",
        },
    ]
    # ---- FINE ELENCO LEZIONI ----

    titles = [f"Lezione {l['n']} — {l['title']}" for l in LESSONS]
    sel = st.selectbox("Scegli la lezione", titles, index=len(titles)-1)
    lesson = LESSONS[titles.index(sel)]

    st.markdown(f"### Lezione {lesson['n']} · {lesson['title']}")
    st.markdown(f'<p class="muted">{lesson["subtitle"]}</p>', unsafe_allow_html=True)
    st.markdown(f'<div class="lesson">{lesson["body"]}</div>', unsafe_allow_html=True)
    st.success(f"💡 **In una frase:** {lesson['key']}")

    # progress
    st.markdown("---")
    st.markdown(f"**Lezioni pubblicate:** {len(LESSONS)} · "
                f"Prossima in arrivo: Lezione {len(LESSONS)+1}")
    st.caption("Il corso cresce una lezione alla volta. Le prossime tappe previste: i multipli (P/E, P/BV), "
               "il valore temporale del denaro, il costo del capitale (WACC), il DCF passo passo, "
               "e infine la valutazione di banche e assicurazioni.")


