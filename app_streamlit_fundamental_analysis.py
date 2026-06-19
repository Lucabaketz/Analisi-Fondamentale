     import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# =============================================================
#  VALUTATORE AZIENDE  ·  DCF (FCFF/FCFE) · DDM · Multipli
#  Logica robusta: i dati vengono letti dai prospetti finanziari
#  (income statement, balance sheet, cashflow) e NON dal solo
#  dizionario .info, che è spesso incompleto o incoerente.
# =============================================================

st.set_page_config(page_title="Valutatore Aziende", layout="wide", page_icon="📈")

# ---------- STILE ----------
st.markdown("""
<style>
:root{ --ink:#0b1f3a; --accent:#2563eb; --soft:#eef4ff; --line:#dbe4f0; --muted:#5b6b82; }
.stApp{ background:#f7f9fc; }
h1,h2,h3,h4{ color:var(--ink); }
.card{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
.kpi{ background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
.kpi .v{ font-size:1.35rem; font-weight:700; color:var(--ink); }
.kpi .l{ font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.4px; }
.pill{ display:inline-block; background:var(--soft); color:var(--accent); border:1px solid #c7d8f5;
       padding:.15rem .6rem; border-radius:999px; font-size:.8rem; margin-right:.35rem; }
.muted{ color:var(--muted); font-size:.9rem; }
.fv-up{ color:#15803d; font-weight:700; }
.fv-dn{ color:#b91c1c; font-weight:700; }
</style>
""", unsafe_allow_html=True)

# =============================================================
#  HELPERS
# =============================================================
def f(x, default=None):
    """to float, NaN-safe"""
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
    """Estrae l'ultima colonna (anno più recente) di una riga dai prospetti yfinance,
    provando più nomi alternativi. df ha le voci come indice."""
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if not s.empty:
                return f(s.iloc[0])
    return None

# =============================================================
#  DATA LAYER  ·  legge prospetti + info, normalizza tutto
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

    # ---- prezzo ----
    price = f(info.get("currentPrice"))
    if price is None:
        try:
            h = t.history(period="5d")
            if not h.empty:
                price = f(h["Close"].dropna().iloc[-1])
        except Exception:
            pass

    shares = f(info.get("sharesOutstanding")) or row(bs, "Share Issued", "Ordinary Shares Number")

    # ---- conto economico ----
    revenue   = row(inc, "Total Revenue", "Operating Revenue")
    ebit      = row(inc, "EBIT", "Operating Income")
    ebitda    = row(inc, "EBITDA", "Normalized EBITDA") or info.get("ebitda")
    ebitda    = f(ebitda)
    net_inc   = row(inc, "Net Income", "Net Income Common Stockholders")
    pretax    = row(inc, "Pretax Income")
    tax_prov  = row(inc, "Tax Provision")
    interest  = row(inc, "Interest Expense", "Interest Expense Non Operating")

    # aliquota fiscale effettiva (clamp 0–40%)
    tax_rate = 0.25
    if pretax and tax_prov is not None and pretax != 0:
        tr = tax_prov / pretax
        if 0 <= tr <= 0.40:
            tax_rate = tr

    # ---- stato patrimoniale ----
    total_debt = row(bs, "Total Debt") \
                 or ((row(bs, "Long Term Debt") or 0) + (row(bs, "Current Debt", "Short Term Debt") or 0)) or None
    cash       = row(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    equity_bv  = row(bs, "Stockholders Equity", "Total Equity Gross Minority Interest")

    # ---- rendiconto finanziario ----
    cfo   = row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = row(cf, "Capital Expenditure", "Purchase Of PPE")  # negativo
    fcf   = row(cf, "Free Cash Flow")
    if fcf is None and cfo is not None and capex is not None:
        fcf = cfo + capex  # capex è già negativo

    # ---- dividendi (DPS da serie, più affidabile) ----
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
        "price": price,
        "shares": shares,
        "mktcap": f(info.get("marketCap")) or ((price * shares) if (price and shares) else None),
        "beta": f(info.get("beta")) or 1.0,
        # CE
        "revenue": revenue, "ebit": ebit, "ebitda": ebitda, "net_income": net_inc,
        "interest": abs(interest) if interest else None, "tax_rate": tax_rate,
        # SP
        "total_debt": total_debt, "cash": cash, "equity_bv": equity_bv,
        # CF
        "cfo": cfo, "capex": capex, "fcf": fcf,
        # dividendi
        "dps": dps if (dps and dps > 0) else None,
        # multipli da info (validazione)
        "eps_t": f(info.get("trailingEps")), "eps_f": f(info.get("forwardEps")),
        "bvps": f(info.get("bookValue")),
    }

# =============================================================
#  MODELLI DI VALUTAZIONE
# =============================================================
def wacc(beta, rf, erp, kd_pretax, tax, e, d):
    """Costo medio ponderato del capitale."""
    ke = rf + beta * erp
    kd = kd_pretax * (1 - tax)
    v = e + d
    if v <= 0:
        return ke
    return ke * (e / v) + kd * (d / v)

def dcf_fcff(fcf0, g, years, term_g, discount, net_debt, shares):
    """DCF a 2 stadi su FCFF → Enterprise Value → Equity → per azione."""
    if not all(v is not None for v in [fcf0, discount, shares]) or shares <= 0:
        return None
    if discount <= term_g:
        return None
    pv = 0.0
    cf = fcf0
    for yr in range(1, years + 1):
        cf = cf * (1 + g)
        pv += cf / (1 + discount) ** yr
    # valore terminale (Gordon sul FCFF dell'ultimo anno)
    tv = cf * (1 + term_g) / (discount - term_g)
    pv += tv / (1 + discount) ** years
    equity_value = pv - (net_debt or 0)
    return equity_value / shares

def ddm_gordon(dps, ke, g):
    """Gordon Growth a stadio singolo."""
    if dps is None or dps <= 0 or ke <= g:
        return None
    return dps * (1 + g) / (ke - g)

def multiple_fv(per_share_metric, multiple):
    if per_share_metric is None or multiple is None or multiple <= 0:
        return None
    return per_share_metric * multiple

# =============================================================
#  HEADER
# =============================================================
st.markdown("# 📈 Valutatore Aziende")
st.markdown('<p class="muted">DCF (FCFF) · Dividend Discount Model · Multipli — dati letti dai prospetti finanziari, '
            'con parametri di valutazione modificabili. Strumento informativo, non consulenza finanziaria.</p>',
            unsafe_allow_html=True)

PRESET = {
    "Apple":"AAPL","Microsoft":"MSFT","NVIDIA":"NVDA","Alphabet":"GOOGL","Amazon":"AMZN",
    "Coca-Cola":"KO","Johnson & Johnson":"JNJ","ENEL":"ENEL.MI","ENI":"ENI.MI",
    "Intesa Sanpaolo":"ISP.MI","Ferrari":"RACE.MI","LVMH":"MC.PA","Nestlé":"NESN.SW","ASML":"ASML",
}

c1, c2 = st.columns([2, 3])
with c1:
    choice = st.selectbox("Titolo dall'elenco", ["—"] + list(PRESET.keys()))
with c2:
    manual = st.text_input("Oppure inserisci un ticker (es. AAPL, ENEL.MI, MC.PA)", "")

ticker = manual.strip().upper() or (PRESET.get(choice) if choice != "—" else None)

if not ticker:
    st.info("Seleziona un titolo o inserisci un ticker per iniziare.")
    st.stop()

with st.spinner(f"Carico i dati di {ticker}…"):
    D = load_company(ticker)

price = D["price"]
ccy = D["currency"]

if price is None:
    st.error(f"Non riesco a recuperare il prezzo di **{ticker}**. Verifica il ticker (per Borsa Italiana usa il suffisso `.MI`).")
    st.stop()

# attenzione valuta mista
if D["fin_currency"] and ccy and D["fin_currency"] != ccy:
    st.warning(f"⚠️ Attenzione valute: prezzo in **{ccy}**, bilanci in **{D['fin_currency']}**. "
               f"I valori per-azione derivati dai bilanci potrebbero non essere allineati al prezzo.")

# ---------- KPI HEADER ----------
st.markdown(f"## {D['name']}  ·  `{ticker}`")
k = st.columns(5)
kpis = [
    ("Prezzo", f"{fmt(price)} {ccy}"),
    ("Capitalizzazione", fmt_big(D["mktcap"])),
    ("Settore", D["sector"] or "N/D"),
    ("Beta", fmt(D["beta"])),
    ("Aliquota fiscale", fmt(D["tax_rate"]*100, 1, "%")),
]
for col, (l, v) in zip(k, kpis):
    col.markdown(f'<div class="kpi"><div class="l">{l}</div><div class="v">{v}</div></div>', unsafe_allow_html=True)

# ---------- DATI DI BILANCIO ----------
with st.expander("📑 Dati di bilancio letti (ultimo esercizio)", expanded=False):
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("**Conto economico**")
        st.write(f"Ricavi: {fmt_big(D['revenue'])}")
        st.write(f"EBIT: {fmt_big(D['ebit'])}")
        st.write(f"EBITDA: {fmt_big(D['ebitda'])}")
        st.write(f"Utile netto: {fmt_big(D['net_income'])}")
    with g2:
        st.markdown("**Stato patrimoniale**")
        st.write(f"Debito totale: {fmt_big(D['total_debt'])}")
        st.write(f"Cassa: {fmt_big(D['cash'])}")
        st.write(f"Patrimonio netto: {fmt_big(D['equity_bv'])}")
        st.write(f"N. azioni: {fmt_big(D['shares'])}")
    with g3:
        st.markdown("**Flussi di cassa**")
        st.write(f"Cash flow operativo: {fmt_big(D['cfo'])}")
        st.write(f"Capex: {fmt_big(D['capex'])}")
        st.write(f"Free Cash Flow: {fmt_big(D['fcf'])}")
        st.write(f"DPS (12m): {fmt(D['dps'])}")

# grafico prezzo
try:
    h = yf.Ticker(ticker).history(period="1y")
    if not h.empty:
        st.line_chart(h["Close"], height=200)
except Exception:
    pass

net_debt = (D["total_debt"] or 0) - (D["cash"] or 0)

# =============================================================
#  PARAMETRI (sidebar)
# =============================================================
st.sidebar.markdown("## ⚙️ Parametri di valutazione")

st.sidebar.markdown("### Costo del capitale")
rf  = st.sidebar.slider("Risk-free rate (%)", 0.0, 8.0, 3.5, 0.1) / 100
erp = st.sidebar.slider("Equity risk premium (%)", 3.0, 10.0, 5.5, 0.1) / 100
beta_in = st.sidebar.number_input("Beta", value=float(round(D["beta"], 2)), step=0.05)

# costo del debito stimato (interessi / debito)
kd_auto = (D["interest"] / D["total_debt"]) if (D["interest"] and D["total_debt"]) else 0.05
kd = st.sidebar.slider("Costo del debito ante imposte (%)", 0.0, 15.0,
                       float(round(min(max(kd_auto*100, 1.0), 12.0), 1)), 0.1) / 100

ke = rf + beta_in * erp
e_val = D["mktcap"] or 0
d_val = D["total_debt"] or 0
wacc_val = wacc(beta_in, rf, erp, kd, D["tax_rate"], e_val, d_val)

st.sidebar.markdown(f"**Ke (cost of equity):** {ke*100:.2f}%")
st.sidebar.markdown(f"**WACC:** {wacc_val*100:.2f}%")

st.sidebar.markdown("### Crescita DCF (FCFF)")
g_fcf  = st.sidebar.slider("Crescita FCF esplicita (%/anno)", -5.0, 25.0, 6.0, 0.5) / 100
years  = st.sidebar.slider("Anni di previsione esplicita", 3, 15, 7, 1)
term_g = st.sidebar.slider("Crescita terminale (%)", 0.0, 4.0, 2.0, 0.25) / 100

st.sidebar.markdown("### Crescita DDM")
g_ddm = st.sidebar.slider("Crescita dividendi (%)", 0.0, 8.0, 2.5, 0.25) / 100

# =============================================================
#  CALCOLO FAIR VALUE
# =============================================================
st.markdown("## 🎯 Fair Value per modello")

# --- DCF FCFF ---
fv_dcf = dcf_fcff(D["fcf"], g_fcf, years, term_g, wacc_val, net_debt, D["shares"])

# --- DDM ---
fv_ddm = ddm_gordon(D["dps"], ke, g_ddm)
ddm_yield_ok = (D["dps"] and price and (D["dps"]/price) >= 0.005)
if not ddm_yield_ok:
    fv_ddm = None

# --- Multipli (metriche per azione) ---
sh = D["shares"]
eps   = D["eps_f"] or D["eps_t"] or ((D["net_income"]/sh) if (D["net_income"] and sh) else None)
bvps  = D["bvps"] or ((D["equity_bv"]/sh) if (D["equity_bv"] and sh) else None)
salesps  = (D["revenue"]/sh) if (D["revenue"] and sh) else None
ebitdaps = (D["ebitda"]/sh) if (D["ebitda"] and sh) else None
fcfps    = (D["fcf"]/sh) if (D["fcf"] and sh) else None

st.markdown("#### Multipli attesi (modificabili)")
m = st.columns(5)
with m[0]: pe_x   = st.number_input("P/E", value=18.0, step=0.5)
with m[1]: pb_x   = st.number_input("P/BV", value=2.5, step=0.1)
with m[2]: ps_x   = st.number_input("P/Sales", value=3.0, step=0.1)
with m[3]: pebd_x = st.number_input("P/EBITDA", value=12.0, step=0.5)
with m[4]: pfcf_x = st.number_input("P/FCF", value=18.0, step=0.5)

fv_pe   = multiple_fv(eps, pe_x)
fv_pb   = multiple_fv(bvps, pb_x)
fv_ps   = multiple_fv(salesps, ps_x)
fv_pebd = multiple_fv(ebitdaps, pebd_x)
fv_pfcf = multiple_fv(fcfps, pfcf_x)

# --- tabella risultati ---
def delta_html(fv):
    if fv is None or not price:
        return '<span class="muted">N/D</span>'
    up = (fv/price - 1) * 100
    cls = "fv-up" if up >= 0 else "fv-dn"
    return f'<b>{fmt(fv)} {ccy}</b> &nbsp;<span class="{cls}">({up:+.1f}%)</span>'

models = [
    ("DCF — FCFF (2 stadi)", fv_dcf, "Sconta i flussi di cassa liberi al WACC. Cardine per società mature con FCF positivo."),
    ("DDM — Gordon", fv_ddm, "Sconta i dividendi al costo dell'equity. Solo se il dividend yield è ≥0,5%."),
    ("Multiplo P/E", fv_pe, "EPS × P/E atteso."),
    ("Multiplo P/BV", fv_pb, "Book value/azione × P/BV. Rilevante per banche e assicurazioni."),
    ("Multiplo P/Sales", fv_ps, "Ricavi/azione × P/Sales. Utile per società growth o in perdita."),
    ("Multiplo P/EBITDA", fv_pebd, "EBITDA/azione × multiplo. Per business capital-intensive."),
    ("Multiplo P/FCF", fv_pfcf, "FCF/azione × multiplo."),
]

st.markdown('<div class="card">', unsafe_allow_html=True)
for name, fv, desc in models:
    st.markdown(f"**{name}** — {delta_html(fv)}", unsafe_allow_html=True)
    st.markdown(f'<span class="muted">{desc}</span>', unsafe_allow_html=True)
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# =============================================================
#  SINTESI
# =============================================================
st.markdown("## 🧭 Sintesi")

valid = [(n, fv) for n, fv, _ in models if fv is not None]
if valid:
    fvs = [v for _, v in valid]
    fv_median = float(np.median(fvs))
    fv_min, fv_max = min(fvs), max(fvs)
    upside = (fv_median/price - 1) * 100

    if upside <= -20:      verdict, cls = "Sopravvalutata", "fv-dn"
    elif upside <= -8:     verdict, cls = "Leggermente cara", "fv-dn"
    elif upside < 10:      verdict, cls = "In linea col prezzo", "muted"
    elif upside < 25:      verdict, cls = "Potenzialmente sottovalutata", "fv-up"
    else:                  verdict, cls = "Marcatamente sottovalutata", "fv-up"

    sc = st.columns(4)
    sc[0].markdown(f'<div class="kpi"><div class="l">Prezzo</div><div class="v">{fmt(price)} {ccy}</div></div>', unsafe_allow_html=True)
    sc[1].markdown(f'<div class="kpi"><div class="l">Fair value mediano</div><div class="v">{fmt(fv_median)} {ccy}</div></div>', unsafe_allow_html=True)
    sc[2].markdown(f'<div class="kpi"><div class="l">Range modelli</div><div class="v">{fmt(fv_min)}–{fmt(fv_max)}</div></div>', unsafe_allow_html=True)
    sc[3].markdown(f'<div class="kpi"><div class="l">Upside vs prezzo</div><div class="v {cls}">{upside:+.1f}%</div></div>', unsafe_allow_html=True)

    st.markdown(f'<div class="card" style="margin-top:12px"><span class="pill">{verdict}</span> '
                f'<span class="muted">Mediana di {len(valid)} modelli applicabili. '
                f'La dispersione del range indica quanto i metodi concordano: range ampio = maggiore incertezza.</span></div>',
                unsafe_allow_html=True)

    # grafico a barre dei fair value
    chart_df = pd.DataFrame({"Fair Value": fvs}, index=[n for n, _ in valid])
    chart_df.loc["▶ PREZZO ATTUALE"] = price
    st.bar_chart(chart_df, height=280)
else:
    st.info("Nessun modello applicabile con i dati disponibili. Prova a modificare i parametri o verifica i dati di bilancio.")

st.markdown("---")
st.caption("⚠️ Strumento puramente informativo. I dati provengono da Yahoo Finance e possono contenere errori o ritardi. "
           "Le valutazioni dipendono fortemente dalle assunzioni inserite. Non costituisce consulenza finanziaria o sollecitazione all'investimento.")

