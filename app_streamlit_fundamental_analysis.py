import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import base64
from pathlib import Path

# =========================
# STILE (tema blu minimal)
# =========================
st.set_page_config(page_title="Analisi Fondamentale", layout="wide")
st.markdown(
    """
    <style>
    :root{
      --primary:#1e3a8a; --primary-600:#1d4ed8; --bg:#f8fafc; --bg-soft:#eef2ff; --text:#0f172a; --muted:#64748b;
    }
    .stApp{background:var(--bg);} h1,h2,h3,h4{color:var(--primary);} 
    .blue-card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(2,6,23,.06)}
    .soft{background:var(--bg-soft)!important}
    .badge{background:#e2e8f0;color:#0f172a;padding:.25rem .6rem;border-radius:999px;font-size:.85rem;margin-right:.35rem}
    .note{font-size:.9rem;color:#475569}
    .tag{display:inline-block;background:#eef2ff;color:#1e3a8a;border:1px solid #c7d2fe;padding:.15rem .5rem;border-radius:8px;margin-right:.35rem}
    ul.tight li{margin:.25rem 0;}
    code.kbd{background:#f1f5f9;border:1px solid #e2e8f0;padding:.05rem .35rem;border-radius:6px}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# LISTA UNICA TICKER (menu)
# =========================
STOCKS = {
    "Apple":"AAPL","Microsoft":"MSFT","NVIDIA":"NVDA","Amazon":"AMZN","Alphabet":"GOOGL","Meta":"META",
    "Tesla":"TSLA","Berkshire Hathaway B":"BRK-B","JPMorgan":"JPM","Visa":"V","ExxonMobil":"XOM",
    "Broadcom":"AVGO","Johnson & Johnson":"JNJ","UnitedHealth":"UNH","Coca-Cola":"KO","PepsiCo":"PEP",
    "Procter & Gamble":"PG","Walmart":"WMT",
    # Italia
    "ENEL":"ENEL.MI","ENI":"ENI.MI","Intesa Sanpaolo":"ISP.MI","UniCredit":"UCG.MI","Stellantis":"STLAM.MI",
    "Ferrari":"RACE.MI","Prysmian":"PRY.MI","Poste Italiane":"PST.MI","Moncler":"MONC.MI","Amplifon":"AMP.MI",
    # Europa/altre
    "ASML":"ASML","TSMC":"TSM","Novo Nordisk":"NOVO-B.CO","LVMH":"MC.PA","Nestlé":"NESN.SW","SAP":"SAP",
    "Shell":"SHEL","Toyota":"TM",
}

# =========================
# HELPERS
# =========================
def _as_float(x, default=None):
    try:
        v = float(x)
        if np.isnan(v):
            return default
        return v
    except Exception:
        return default

def fmt2(v):
    return f"{v:.2f}" if (v is not None) else "N/D"

@st.cache_data(ttl=300)
def fetch_yf_info(symbol: str):
    t = yf.Ticker(symbol)
    try:
        info = t.get_info() if hasattr(t, "get_info") else (t.info or {})
    except Exception:
        info = {}
    # prezzo fallback
    price = info.get("currentPrice")
    if not price:
        try:
            h = t.history(period="1d")
            if isinstance(h, pd.DataFrame) and not h.empty:
                price = float(h["Close"].iloc[-1])
        except Exception:
            price = None
    return {
        "price": _as_float(price),
        "currency": info.get("currency", ""),
        "financialCurrency": info.get("financialCurrency", info.get("currency", "")),
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector"),
        "shares_out": info.get("sharesOutstanding"),
        # utili
        "eps_trailing": _as_float(info.get("trailingEps") or info.get("epsTrailingTwelveMonths")),
        "eps_forward": _as_float(info.get("forwardEps")),
        "pe_trailing": _as_float(info.get("trailingPE")),
        "pe_forward": _as_float(info.get("forwardPE")),
        # patrimonio / ricavi / ebitda
        "book_value_ps": _as_float(info.get("bookValue")),
        "price_to_book": _as_float(info.get("priceToBook")),
        "revenue": _as_float(info.get("totalRevenue")),
        "ebitda": _as_float(info.get("ebitda")),
        # FCF
        "free_cashflow": info.get("freeCashflow"),
        "levered_free_cashflow": info.get("leveredFreeCashflow"),
        # dividendi
        "forward_dividend_rate": _as_float(info.get("forwardAnnualDividendRate") or info.get("dividendRate")),
        "trailing_dividend_rate": _as_float(info.get("trailingAnnualDividendRate")),
        "payout": _as_float(info.get("payoutRatio")),
        # P/S corrente
        "price_to_sales_ttm": _as_float(info.get("priceToSalesTrailing12Months")),
    }

@st.cache_data(ttl=900)
def get_dps_ttm(symbol: str):
    try:
        s = yf.Ticker(symbol).dividends
        if s is not None and not s.empty:
            cut = pd.Timestamp.today(tz=s.index.tz) - pd.DateOffset(years=1)
            last12 = s[s.index >= cut]
            dps = float(last12.sum()) if not last12.empty else None
            return dps if dps and dps > 0 else None
    except Exception:
        pass
    return None

def select_dividend(price, forward_div, trailing_div, dps_ttm, payout, eps_for_div):
    def _ok(d):
        return (d is not None) and (d>0) and (price and price>0) and (0 < d/price <= 0.15)
    if _ok(forward_div):
        return forward_div, "FORWARD"
    if _ok(dps_ttm):
        return dps_ttm, "TTM"
    if _ok(trailing_div):
        return trailing_div, "TRAILING"
    if (payout is not None) and (0 <= payout <= 1) and (eps_for_div is not None) and (eps_for_div > 0):
        dps_est = eps_for_div * payout
        if _ok(dps_est):
            return dps_est, "PAYOUT"
    return None, None

def gordon_fair_value(dps, r, g):
    if dps is None or dps <= 0: return None
    g = float(min(0.08, max(0.0, g)))
    r = float(min(0.14, max(0.06, r)))
    if r <= g: g = max(g-0.01, 0.0)
    return dps*(1+g)/(r-g)

def ddm_gate(dps, price):
    try:
        if dps is None or price is None or price<=0: return False
        return (dps/price) >= 0.005
    except Exception:
        return False

# ================
# Logo / Header
# ================
def img_to_base64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()

b64 = img_to_base64("logo.png")

st.markdown(
    f"""
    <link href="https://fonts.googleapis.com/css2?family=Montserrat+Alternates:wght@700&display=swap" rel="stylesheet">
    <div style="
        display:flex;
        justify-content:center;
        align-items:center;
        gap:12px;
        margin:12px 0 24px;
    ">
      <img src="data:image/png;base64,{b64}" width="100" style="border-radius:10px;">
      <span style="
          font-family:'Montserrat Alternates', sans-serif;
          font-weight:700;
          color:#1e3a8a;
          font-size:2.2em;
          letter-spacing:0.4px;
      ">
        Valutatore Azioni
      </span>
    </div>
    """,
    unsafe_allow_html=True
)

tab_analisi, tab_tutorial = st.tabs(["📊 Analisi", "📘 Tutorial"])

with tab_analisi:
    st.markdown("### Selezione titoli")
    labels_ordered = list(STOCKS.keys())
    selected_labels = st.multiselect("Seleziona fino a 2 titoli (menu unico)", labels_ordered, max_selections=2)
    custom = st.text_input("Oppure inserisci fino a 2 ticker separati da virgola (es. AAPL, ENEL.MI)", "")

    tickers_from_menu = [STOCKS[l] for l in selected_labels]
    tickers_from_custom = [t.strip().upper() for t in custom.split(",") if t.strip()]
    tickers = (tickers_from_custom or tickers_from_menu)[:2]

    # Buffer per il debug (lo mostreremo in fondo)
    _debug_rows = []

    for tkr in tickers:
        st.markdown(f"## {tkr}")
        col1, col2 = st.columns(2, gap="large")

        info = fetch_yf_info(tkr)
        price = info.get("price"); price_ccy = info.get("currency") or ""; fin_ccy = info.get("financialCurrency") or price_ccy or ""
        shares = info.get("shares_out") or 0

        with col1:
            st.markdown('<div class="blue-card soft">**Valutazione Qualitativa (rapida)**</div>', unsafe_allow_html=True)
            q1 = st.radio("Vantaggio competitivo duraturo?", ["Sì","No"], index=1, key=f"{tkr}_q1")
            q2 = st.radio("Situazione finanziaria solida?", ["Sì","No"], index=1, key=f"{tkr}_q2")
            q3 = st.radio("Utili in crescita?", ["Sì","No"], index=1, key=f"{tkr}_q3")
            q4 = st.radio("Management competente?", ["Sì","No"], index=1, key=f"{tkr}_q4")

        with col2:
            st.markdown('<div class="blue-card">**Dati Quantitativi (Yahoo)**</div>', unsafe_allow_html=True)
            st.markdown(f"- **Prezzo attuale ({tkr})**: {fmt2(price)} {price_ccy}")
            eps_t = info.get("eps_trailing"); eps_f = info.get("eps_forward")
            st.markdown(f"- **EPS trailing [{fin_ccy}]**: {fmt2(eps_t)}  |  **EPS forward**: {fmt2(eps_f)}")

            # per-share metrics
            bvps = info.get("book_value_ps")
            ebitda_ps = (info.get("ebitda")/shares) if (info.get("ebitda") and shares) else None
            sales_ps  = (info.get("revenue")/shares) if (info.get("revenue") and shares) else None
            fcf_ps = None
            if info.get("free_cashflow") and shares:
                try: fcf_ps = float(info.get("free_cashflow"))/float(shares)
                except Exception: pass
            if (fcf_ps is None) and info.get("levered_free_cashflow") and shares:
                try: fcf_ps = float(info.get("levered_free_cashflow"))/float(shares)
                except Exception: pass

            st.markdown(f"- **BV/az**: {fmt2(bvps)} | **EBITDA/az**: {fmt2(ebitda_ps)} | **Sales/az**: {fmt2(sales_ps)} | **FCF/az**: {fmt2(fcf_ps)}")

            try:
                h = yf.Ticker(tkr).history(period="1y")
                if isinstance(h, pd.DataFrame) and not h.empty:
                    st.line_chart(h["Close"], height=180)
            except Exception:
                pass

        # ------------------ MULTIPLI ------------------
        st.markdown("### 🔹 Campi per modello dei multipli")
        curr_pe_t = (price/eps_t) if (price and eps_t and eps_t>0) else None
        curr_pe_f = (price/eps_f) if (price and eps_f and eps_f>0) else None
        curr_pe = ( (curr_pe_t + curr_pe_f)/2 if (curr_pe_t and curr_pe_f) else (curr_pe_f or curr_pe_t) )
        curr_pb = (price/bvps) if (price and bvps) else info.get("price_to_book")
        curr_ps = (price/sales_ps) if (price and sales_ps) else info.get("price_to_sales_ttm")
        curr_pebitda = ((price*shares)/(info.get("ebitda") or np.nan)) if (price and shares and info.get("ebitda")) else None
        curr_pfcf = (price/fcf_ps) if (price and fcf_ps) else None

        cpe1,cpe2,cpe3,cpe4,cpe5 = st.columns(5)
        with cpe1: pe_star = st.number_input(f"P/E atteso ({tkr})", value=float(curr_pe or 15.0), step=0.5)
        with cpe2: pb_star = st.number_input(f"P/BV atteso ({tkr})", value=float(curr_pb or 1.5), step=0.1)
        with cpe3: pebitda_star = st.number_input(f"P/EBITDA atteso ({tkr})", value=float(curr_pebitda or 10.0), step=0.5)
        with cpe4: ps_star = st.number_input(f"P/Sales atteso ({tkr})", value=float(curr_ps or 2.0), step=0.1)
        with cpe5: pfcf_star = st.number_input(f"P/FCF atteso ({tkr})", value=float(curr_pfcf or 15.0), step=0.5)

        # Avvisi per i 3 multipli dove spesso mancano dati
        if ebitda_ps is None:
            st.warning("P/EBITDA: dato EBITDA per azione non disponibile. Inserisci manualmente l'EBITDA per azione per abilitare il calcolo.")
            ebitda_ps = st.number_input(f"EBITDA per azione ({tkr}) – inserisci", min_value=0.0, value=0.0, step=0.01, key=f"{tkr}_ebitda_ps_manual") or None
        if sales_ps is None:
            st.warning("P/Sales: dato Sales per azione non disponibile. Inserisci manualmente le Vendite per azione per abilitare il calcolo.")
            sales_ps = st.number_input(f"Sales per azione ({tkr}) – inserisci", min_value=0.0, value=0.0, step=0.01, key=f"{tkr}_sales_ps_manual") or None
        if fcf_ps is None:
            st.warning("P/FCF: dato FCF per azione non disponibile. Inserisci manualmente il FCF per azione per abilitare il calcolo.")
            fcf_ps = st.number_input(f"FCF per azione ({tkr}) – inserisci", min_value=0.0, value=0.0, step=0.01, key=f"{tkr}_fcf_ps_manual") or None

        # fair values multipli
        fv_pe = (eps_f or eps_t) * pe_star if ((eps_f or eps_t) and pe_star>0) else None
        fv_pb = bvps * pb_star if (bvps and pb_star>0) else None
        fv_pebitda = (ebitda_ps * pebitda_star) if (ebitda_ps and pebitda_star>0) else None
        fv_ps = (sales_ps * ps_star) if (sales_ps and ps_star>0) else None
        fv_pfcf = (fcf_ps * pfcf_star) if (fcf_ps and pfcf_star>0) else None

        # ------------------ DDM + RISULTATI ------------------
        st.markdown("### 🔹 Campi per modello DDM ")

        # candidati DPS
        dps_ttm = get_dps_ttm(tkr)
        forward_div = info.get("forward_dividend_rate")
        trailing_div = info.get("trailing_dividend_rate")
        payout_ratio = info.get("payout")
        eps_for_div = (eps_f or eps_t)

        # selezione automatica iniziale
        dps_auto, dps_src = select_dividend(price, forward_div, trailing_div, dps_ttm, payout_ratio, eps_for_div)

        with st.expander("🔎 Dividendo & Assunzioni DDM"):
            # blocco fonti DPS
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Forward DPS", fmt2(forward_div), help="forwardAnnualDividendRate")
                if price: st.caption(f"Yield: {fmt2((forward_div or 0)/price*100)}%")
            with c2:
                st.metric("TTM DPS (12m)", fmt2(dps_ttm))
                if price: st.caption(f"Yield: {fmt2((dps_ttm or 0)/price*100)}%")
            with c3:
                st.metric("Trailing DPS", fmt2(trailing_div))
                if price: st.caption(f"Yield: {fmt2((trailing_div or 0)/price*100)}%")
            with c4:
                est = (eps_for_div or 0)*(payout_ratio or 0) if (eps_for_div and payout_ratio and 0<=payout_ratio<=1) else None
                st.metric("Stima payout (EPS×payout)", fmt2(est))
                if price: st.caption(f"Yield: {fmt2((est or 0)/price*100)}%")

            st.markdown(f"**Selezione automatica DPS:** `{dps_src or 'N/D'}` → **{fmt2(dps_auto)} {price_ccy}**")

            # selettore fonte opzionale
            src_choice = st.selectbox(
                "Fonte DPS (opzionale)",
                ["AUTO","FORWARD","TTM","TRAILING","PAYOUT","MANUAL"],
                index=0, key=f"{tkr}_dps_src_choice"
            )

            # valore iniziale del campo numerico
            default_dps = dps_auto or 0.0
            if src_choice == "FORWARD" and forward_div is not None: default_dps = forward_div
            elif src_choice == "TTM" and dps_ttm is not None:       default_dps = dps_ttm
            elif src_choice == "TRAILING" and trailing_div is not None: default_dps = trailing_div
            elif src_choice == "PAYOUT" and (eps_for_div and payout_ratio and 0<=payout_ratio<=1):
                default_dps = eps_for_div * payout_ratio

            dps_manual = st.number_input(
                "DPS usato per DDM", min_value=0.0, value=float(default_dps), step=0.01, key=f"{tkr}_dps_used"
            )

            # assunzioni DDM (r, g) qui dentro come richiesto
            a1, a2 = st.columns(2)
            with a1:
                r_req = st.number_input("Tasso di sconto r (%)", value=9.0, step=0.5, key=f"{tkr}_r")/100.0
            with a2:
                g_term = st.number_input("Crescita g (%)", value=2.0, step=0.25, key=f"{tkr}_g")/100.0

            # definisci la "fonte" visualizzata
            use_src = (
                "MANUAL" if src_choice=="MANUAL"
                else (src_choice if src_choice!="AUTO" else (dps_src or "N/D"))
            )

        # calcolo FV DDM
        dps_used = dps_manual
        fv_ddm = gordon_fair_value(dps_used, r_req, g_term)
        if not ddm_gate(dps_used, price):
            fv_ddm = None

        # util per stampa FV
        def line_fv(label, fv):
            if fv is None:
                st.write(f"- **{label}:** N/D")
            else:
                delta = f" (Δ {((fv-price)/price*100):.1f}%)" if (price and price>0) else ""
                st.write(f"- **{label}:** {fv:.2f} {price_ccy}{delta}")

        st.markdown("#### 📌 Risultati PREZZO TEORICO per modello")
        line_fv("P/E", fv_pe)
        st.caption("↳ Basato sugli utili (EPS); utile per aziende con utili stabili/crescenti.")
        line_fv("P/BV", fv_pb)
        st.caption("↳ Rilevante per banche/assicurazioni. - Per calcolo inserire dati manualmente ")
        line_fv("P/EBITDA", fv_pebitda)
        st.caption("↳ Utile per business capital-intensive.  - Per calcolo inserire dati manualmente ")
        line_fv("P/Sales", fv_ps)
        st.caption("↳ Adatto a società growth/early-stage.  - Per calcolo inserire dati manualmente ")
        ddm_label = f"DDM (Gordon) — DPS fonte: {use_src}"
        line_fv(ddm_label, fv_ddm)
        st.caption("↳ Basato sul dividendo; escluso se yield troppo basso (<0,5%) o DPS non valido.")

        # ======================
        # COMMENTO FINALE (semplificato)
        # ======================
        st.subheader(f"Commento finale su {tkr}")

        def classify_diff(upside):
            if upside is None:
                return None, "N/D"
            if upside <= -0.30:
                return "Molto caro", "⚠️ Sopravvalutazione elevata (>+30% vs prezzo)"
            if -0.30 < upside <= -0.15:
                return "Caro", "⚠️ Sopravvalutazione moderata (+15–30%)"
            if -0.15 < upside <= 0.10:
                return "In linea", "≈ Valutazione in linea (−15% a +10%)"
            if 0.10 < upside <= 0.30:
                return "Sottovalutata", "✅ Sottovalutazione potenziale (+10–30%)"
            return "Molto sottovalutata", "✅✅ Sottovalutazione elevata (>+30%)"

        def fmt_pct(v):
            return f"{v*100:.1f}%" if v is not None else "N/D"

        up_pe  = (fv_pe/price - 1.0) if (fv_pe and price) else None
        up_ddm = (fv_ddm/price - 1.0) if (fv_ddm and price) else None

        label_pe, note_pe   = classify_diff(up_pe)
        label_ddm, note_ddm = classify_diff(up_ddm) if fv_ddm is not None else (None, None)

        score = sum(1 for q in [q1,q2,q3,q4] if q=="Sì")
        qual_map = {0:"Debole",1:"Debole",2:"Misto",3:"Buono",4:"Ottimo"}
        qual_label = qual_map[score]

        div_flag = None
        if payout_ratio is not None:
            if payout_ratio > 1.0:
                div_flag = "Payout >100%: sostenibilità del dividendo a rischio."
            elif payout_ratio < 0.2 and fv_ddm is not None:
                div_flag = "Payout contenuto: spazio per crescita dividendi, se utili in aumento."

        ddm_reason = (
            "DDM non applicato (yield <0,5% o DPS non utilizzabile)."
            if fv_ddm is None else f"DDM applicato (DPS fonte: {use_src})."
        )

        st.markdown(
            f"""
            <div class="blue-card">
              <div>
                <span class="tag">Profilo qualitativo: {qual_label}</span>
                <span class="tag">Payout: {fmt2(payout_ratio) if payout_ratio is not None else 'N/D'}</span>
              </div>
              <p class="note" style="margin-top:.5rem">Commento basato <b>solo</b> su differenziali vs <b>P/E</b> e <b>DDM</b> (se applicabile).</p>
              <ul class="tight">
                <li><b>Vista P/E</b>: upside {fmt_pct(up_pe)} → <b>{label_pe or 'N/D'}</b>. {note_pe or ''}</li>
                <li><b>Vista DDM</b>: {('upside '+fmt_pct(up_ddm)+' → <b>'+label_ddm+'</b>. '+(note_ddm or '')) if fv_ddm is not None else ddm_reason}</li>
                {('<li>'+div_flag+'</li>' if div_flag else '')}
              </ul>
              <p class="note">Nota: stime e dati automatici possono contenere errori; verifica sempre le fonti.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.warning("⚠️ Analisi informativa; non costituisce consulenza finanziaria. ATTENZIONE: i dati inseriti in automatico potrebbero essere errati", icon="⚠️")

        # ====== DEBUG: accumula riga per ticker ======
        _debug_rows.append(
            f"- [{tkr}] Valuta prezzo: {price_ccy} | Valuta contabile: {fin_ccy} | "
            f"EPS T: {fmt2(eps_t)} | EPS F: {fmt2(eps_f)} | "
            f"BV/az: {fmt2(bvps)} | EBITDA/az: {fmt2(ebitda_ps)} | Sales/az: {fmt2(sales_ps)} | FCF/az: {fmt2(fcf_ps)} | "
            f"DDM → DPS_auto: {fmt2(dps_auto)} (src={dps_src}), DPS_used: {fmt2(dps_used)} (src={use_src}), r={r_req:.3f}, g={g_term:.3f}"
        )

    # ====== DEBUG in fondo alla pagina ======
    st.markdown("---")
    show_debug = st.toggle("Mostra pannello debug", value=True, key="show_debug_bottom")
    if show_debug and _debug_rows:
        with st.expander("🛠️ Debug & diagnostica (tutti i ticker)"):
            for row in _debug_rows:
                st.write(row)

with tab_tutorial:
    st.markdown("## 📘 Tutorial – Istruzioni pratiche per usare l’app")
    st.markdown(
        """
        <div class="blue-card">
          <h4>1) Scegli i titoli</h4>
          <ul class="tight">
            <li>Dal menu seleziona fino a <b>2 titoli</b> oppure inserisci i ticker manualmente (es. <code class="kbd">AAPL</code>, <code class="kbd">ENEL.MI</code>).</li>
            <li>Attiva <b>Debug</b> per vedere rapidamente EPS, BV/az, EBITDA/az, Sales/az, FCF/az.</li>
          </ul>

          <h4>2) Imposta (se vuoi) il DDM</h4>
          <ul class="tight">
            <li>Nel pannello “Assunzioni DDM” imposta <b>r</b> (tasso di sconto) e <b>g</b> (crescita di lungo periodo).</li>
            <li>Il DDM viene usato solo se il <b>dividend yield</b> è abbastanza significativo (≥0,5%) e i dati sono coerenti.</li>
          </ul>

          <h4>3) Imposta i multipli attesi</h4>
          <ul class="tight">
            <li>Per il commento finale conta <b>solo</b> il fair value da <b>P/E</b> e da <b>DDM</b> (se applicabile).</li>
            <li>Puoi comunque impostare anche P/BV, P/EBITDA, P/Sales, P/FCF (visibili nei risultati ma non usati nel commento finale).</li>
          </ul>

          <h4>4) Dati mancanti? Come recuperarli</h4>
          <p class="note">Alcuni valori “per azione” possono mancare: inseriscili tu. Ecco dove trovarli e come calcolarli:</p>
          <ul class="tight">
            <li><b>Fonti rapide (gratuite)</b>: Yahoo Finance, Investing.com, Morningstar (versione free), siti IR aziendali, Borsa Italiana/LSE, EDGAR (SEC 10-K/20-F per società USA).</li>
            <li><b>Sales per azione</b> = Ricavi totali (TTM o ultimo anno) ÷ <i>numero azioni</i> (meglio le <i>diluted average</i> dall’Annual Report).</li>
            <li><b>EBITDA per azione</b> = EBITDA totale ÷ numero azioni.</li>
            <li><b>FCF per azione</b> = Free Cash Flow (operativo – capex) ÷ numero azioni. Se non trovi il FCF pronto, calcolalo dai prospetti di cassa.</li>
            <li><b>EPS</b>: l’app usa automaticamente <i>forward</i> se disponibile, altrimenti <i>trailing</i>. Puoi validarlo con il consenso analisti su Yahoo/IR.</li>
            <li><b>Dividendo (DPS)</b>: usa <i>forward</i> dal prospetto dividendi; in alternativa somma gli ultimi 4 pagamenti (TTM) o prendi il <i>trailing</i>. Se mancano, stima con <code>DPS ≈ EPS × Payout</code> (solo se payout è plausibile).</li>
          </ul>

          <h4>5) Come leggere i risultati</h4>
          <ul class="tight">
            <li>Per ciascun modello vedi il <b>fair value</b> e la <b>Δ%</b> vs prezzo.</li>
            <li>Il <b>Commento finale</b> mostra due viste:
              <ul class="tight">
                <li><b>P/E</b>: usa EPS (forward o trailing) × P/E atteso.</li>
                <li><b>DDM</b>: se applicabile, usa DPS con formula di Gordon.</li>
              </ul>
            </li>
            <li>La classificazione è: <i>Molto sottovalutata</i> (&gt;+30%), <i>Sottovalutata</i> (+10÷30%), <i>In linea</i> (−15÷+10%), <i>Cara</i> (+15÷+30% in senso negativo), <i>Molto cara</i> (&gt;+30% in senso negativo).</li>
          </ul>

          <h4>6) Consigli operativi (generali)</h4>
          <ul class="tight">
            <li>Verifica sempre le <b>ipotesi</b> (P/E atteso, r e g del DDM) e i <b>dati</b> inseriti manualmente.</li>
            <li>Per aziende <i>growth</i> con dividendi bassi, il DDM spesso non è informativo; per business maturi può esserlo.</li>
            <li>Ricorda: questa è un’analisi informativa, non costituisce consulenza finanziaria.</li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
