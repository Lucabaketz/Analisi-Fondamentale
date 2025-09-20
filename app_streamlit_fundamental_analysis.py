import streamlit as st
import requests

st.set_page_config(page_title="Analisi Fondamentale", layout="wide")

# =========================
# CONFIG
# =========================
# API key FMP integrata per evitare errori con st.secrets
API_KEY = "DgWXeCFwuJ94JzTQr4hOS6TJ9sMp2fR7"

# =========================
# HEADER
# =========================
st.title("Analisi Fondamentale dei Titoli Azionari")
st.write(
    "Inserisci fino a 2 ticker separati da virgola per confrontarli. "
    "I dati quantitativi sono forniti da Financial Modeling Prep e possono richiedere l'inserimento manuale in caso di indisponibilità."
)
st.caption("⚠️ I risultati sono a scopo informativo e possono contenere errori o essere incompleti.")

# =========================
# INPUT TICKERS
# =========================
tickers_input = st.text_input("Ticker (es: AAPL, ENI.MI)", value="")
tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
if len(tickers) > 2:
    st.warning(f"Saranno considerati solo i primi 2 ticker: **{tickers[0]}**, **{tickers[1]}**.")
    tickers = tickers[:2]

# =========================
# FMP HELPER
# =========================
def fetch_fmp_data(symbol: str, api_key: str):
    """
    Prende da FMP: profile, quote, ratios-ttm.
    Ritorna dict con: price, currency, company_name, last_div, eps, pe, roe, de
    """
    base_url = "https://financialmodelingprep.com/api/v3"
    data = {}

    # PROFILE
    try:
        prof_res = requests.get(f"{base_url}/profile/{symbol}?apikey={api_key}", timeout=20)
        prof = prof_res.json()[0] if prof_res.status_code == 200 and prof_res.json() else None
    except Exception:
        prof = None
    if prof:
        data["price"] = prof.get("price")
        data["currency"] = prof.get("currency")
        data["company_name"] = prof.get("companyName")
        data["last_div"] = prof.get("lastDiv")

    # QUOTE (può dare eps, pe)
    try:
        q_res = requests.get(f"{base_url}/quote/{symbol}?apikey={api_key}", timeout=20)
        q = q_res.json()[0] if q_res.status_code == 200 and q_res.json() else None
    except Exception:
        q = None
    if q:
        data["price"] = q.get("price", data.get("price"))
        data["eps"] = q.get("eps")
        data["pe"] = q.get("pe")
        data["currency"] = q.get("currency", data.get("currency"))
        data["company_name"] = q.get("name", data.get("company_name"))

    # RATIOS TTM (roe, de, eventuali conferme)
    try:
        r_res = requests.get(f"{base_url}/ratios-ttm/{symbol}?apikey={api_key}", timeout=20)
        r = r_res.json()[0] if r_res.status_code == 200 and r_res.json() else None
    except Exception:
        r = None
    if r:
        data["eps"] = r.get("epsTTM", data.get("eps"))
        data["pe"] = r.get("peRatioTTM", data.get("pe"))
        roe = r.get("returnOnEquityTTM")
        data["roe"] = roe
        de = r.get("debtEquityRatioTTM") or r.get("debtToEquityTTM") or r.get("debtEquityRatioTTM")
        data["de"] = de

    return data

# =========================
# MAIN LOOP PER OGNI TICKER
# =========================
for tkr in tickers:
    st.markdown(f"## {tkr}")
    col1, col2 = st.columns(2, gap="large")

    # ---------- COLONNA SINISTRA: QUALITATIVI ----------
    with col1:
        st.markdown("**Valutazione Qualitativa**")
        q1 = st.radio("1. L'azienda ha un forte vantaggio competitivo duraturo?", ["Sì", "No"], index=1, key=f"{tkr}_q1")
        q2 = st.radio("2. La situazione finanziaria è solida (basso indebitamento)?", ["Sì", "No"], index=1, key=f"{tkr}_q2")
        q3 = st.radio("3. Gli utili sono in crescita negli ultimi anni?", ["Sì", "No"], index=1, key=f"{tkr}_q3")
        q4 = st.radio("4. Il management è trasparente e competente?", ["Sì", "No"], index=1, key=f"{tkr}_q4")
        # (RIMOSSA) q5: “Il titolo è sottovalutato rispetto al suo fair value?”

    # ---------- COLONNA DESTRA: QUANTITATIVI ----------
    with col2:
        st.markdown("**Dati Quantitativi**")
        fmp = fetch_fmp_data(tkr, API_KEY)

        # Preparazione valori di default da FMP (poi sempre editabili)
        def _as_float(x, default=0.0):
            try:
                return float(x)
            except Exception:
                return default

        currency = fmp.get("currency", "")

        # Prezzo (sempre modificabile)
        price_default = _as_float(fmp.get("price"), 0.0)
        price_val = st.number_input(
            f"Inserisci/Correggi Prezzo attuale per {tkr}",
            min_value=0.0, value=price_default, step=0.01, key=f"{tkr}_price"
        )
        st.markdown(f"- **Prezzo Attuale:** {price_val:.2f} {currency}")
        with st.expander("❓ Cos'è il Prezzo Attuale?"):
            st.write(
                "È la quotazione più recente dell'azione sul mercato. "
                "Riflette domanda/offerta e incorpora le informazioni disponibili. "
                "Varia continuamente durante le sessioni di borsa."
            )

        # P/E (sempre modificabile)
        pe_default = _as_float(fmp.get("pe"), 0.0)
        pe_val = st.number_input(
            f"Inserisci/Correggi P/E (Prezzo/Utile) per {tkr}",
            min_value=0.0, value=pe_default, step=0.1, key=f"{tkr}_pe"
        )
        st.markdown(f"- **P/E (Prezzo/Utile):** {pe_val:.2f}")
        with st.expander("❓ Cos'è il P/E?"):
            st.write(
                "Il rapporto Prezzo/Utile (P/E) confronta il prezzo dell’azione con l’utile per azione (EPS). "
                "Un P/E alto può riflettere attese di crescita elevate; un P/E basso può suggerire valutazione contenuta "
                "o utili depressi. Confrontalo con la media del settore/mercato."
            )

        # EPS (sempre modificabile)
        eps_default = _as_float(fmp.get("eps"), 0.0)
        eps_val = st.number_input(
            f"Inserisci/Correggi EPS (utile per azione) per {tkr}",
            min_value=0.0, value=eps_default, step=0.01, key=f"{tkr}_eps"
        )
        st.markdown(f"- **EPS (Utile/Azione):** {eps_val:.2f}")
        with st.expander("❓ Cos'è l'EPS?"):
            st.write(
                "L'EPS è l'utile netto attribuito a ciascuna azione. "
                "Si calcola come utile netto diviso numero di azioni in circolazione. "
                "Utile per stimare il fair value moltiplicandolo per un P/E target."
            )

        # ROE % (sempre modificabile)
        roe_raw = fmp.get("roe")
        if roe_raw is not None and roe_raw < 1.0:
            roe_raw = roe_raw * 100.0
        roe_default = _as_float(roe_raw, 0.0)
        roe_val = st.number_input(
            f"Inserisci/Correggi ROE (%) per {tkr}",
            min_value=0.0, value=roe_default, step=0.5, key=f"{tkr}_roe"
        )
        st.markdown(f"- **ROE (Return on Equity):** {roe_val:.1f}%")
        with st.expander("❓ Cos'è il ROE?"):
            st.write(
                "Misura la redditività del capitale proprio: utile netto / patrimonio netto. "
                "Indicativamente 10–15% è nella media; >20% è elevato; <8% è debole (dipende dal settore)."
            )

        # D/E (sempre modificabile)
        de_default = _as_float(fmp.get("de"), 0.0)
        de_val = st.number_input(
            f"Inserisci/Correggi Debt/Equity (rapporto) per {tkr}",
            min_value=0.0, value=de_default, step=0.1, key=f"{tkr}_de"
        )
        st.markdown(f"- **Debt/Equity (D/E):** {de_val:.2f}")
        with st.expander("❓ Cos'è il Debt/Equity?"):
            st.write(
                "Indica la leva finanziaria: debito totale rispetto al patrimonio netto. "
                "Più è alto, più l’azienda finanzia le attività con debito. "
                "Indicativamente D/E < 0,5 è prudente; tra 0,5 e 1 moderato; >1 elevato (da valutare col settore)."
            )

        # Dividend Yield (calcolabile da lastDiv/price, ma sempre modificabile)
        computed_div_yield = None
        last_div = fmp.get("last_div")
        if last_div and price_val:
            try:
                if float(last_div) > 0 and float(price_val) > 0:
                    computed_div_yield = (float(last_div) / float(price_val)) * 100.0
            except Exception:
                computed_div_yield = None
        divy_default = _as_float(computed_div_yield, 0.0)
        div_yield = st.number_input(
            f"Inserisci/Correggi Dividend Yield (%) per {tkr}",
            min_value=0.0, value=divy_default, step=0.1, key=f"{tkr}_divy"
        )
        if div_yield > 0:
            st.markdown(f"- **Dividend Yield:** {div_yield:.1f}%")
        else:
            st.markdown("- **Dividend Yield:** N/D")
        with st.expander("❓ Cos'è il Dividend Yield?"):
            st.write(
                "Percentuale del prezzo restituita come dividendo annuale. "
                "Alto rendimento può essere interessante per reddito, ma verifica sostenibilità e payout."
            )

    # ---------- FAIR VALUE ----------
    st.markdown(f"**Fair Value (Prezzo Teorico) – {tkr}**")
    fv_cols = st.columns([1, 1])
    with fv_cols[0]:
        st.write("**EPS (Utile per Azione)**")
        eps_input = st.number_input(
            f"EPS di {tkr}",
            value=float(eps_val) if eps_val is not None else 0.0,
            step=0.01,
            key=f"fv_eps_{tkr}"
        )
        with st.expander("❓ EPS: che cos'è e dove trovarlo"):
            st.write(
                "L'EPS è l’utile per azione (TTM o annuale). "
                "Puoi trovarlo su siti come FMP o Yahoo Finance (sezione Financials/Statistics) "
                "o nei bilanci dell’azienda."
            )

    with fv_cols[1]:
        st.write("**P/E target (moltiplicatore atteso)**")
        default_pe_target = 15.0
        try:
            if pe_val is not None and float(pe_val) > 0:
                default_pe_target = float(round(pe_val))
        except Exception:
            pass
        pe_target = st.number_input(
            f"P/E target per {tkr}",
            min_value=0.0, value=default_pe_target, step=1.0, key=f"fv_pe_{tkr}"
        )
        with st.expander("❓ P/E target: come sceglierlo e dove trovarlo"):
            st.write(
                "Il P/E target è il multiplo che ritieni appropriato per il titolo, in base a media storica dell’azienda, "
                "media di settore o crescita attesa. Se non hai un riferimento, inizia da 15–20x e adatta."
            )

    if pe_target is None or eps_input is None:
        st.write("⚠️ Inserire EPS e P/E target per calcolare il fair value.")
        fair_value = None
    else:
        fair_value = eps_input * pe_target
        if price_val and price_val > 0:
            delta_pct = (fair_value - price_val) / price_val * 100.0
            st.metric(label="Fair Value stimato", value=f"{fair_value:.2f} {currency}", delta=f"{delta_pct:.1f}%")
        else:
            st.metric(label="Fair Value stimato", value=f"{fair_value:.2f} {currency}")

        if price_val and price_val > 0:
            if fair_value > price_val * 1.1:
                st.write(
                    f"💡 **Interpretazione:** il fair value (**{fair_value:.2f} {currency}**) "
                    f"è ben sopra il prezzo di mercato ⇒ possibile **sottovalutazione**."
                )
            elif fair_value < price_val * 0.9:
                st.write(
                    f"💡 **Interpretazione:** il fair value (**{fair_value:.2f} {currency}**) "
                    f"è sotto il prezzo di mercato ⇒ possibile **sopravvalutazione**."
                )
            else:
                st.write(
                    f"💡 **Interpretazione:** il fair value (**{fair_value:.2f} {currency}**) "
                    "è in linea con la quotazione corrente."
                )
        else:
            st.write("💡 Confronta il fair value con il prezzo per valutare sotto/sopravvalutazione.")

    # ---------- COMMENTO FINALE (più elaborato/tecnico) ----------
    st.subheader(f"Commento finale su {tkr}")

    # punteggio qualitativo su 4 domande
    responses = [q1, q2, q3, q4]
    score = sum(1 for ans in responses if ans == "Sì")
    issues = []
    if q1 == "No": issues.append("vantaggio competitivo")
    if q2 == "No": issues.append("solidità finanziaria")
    if q3 == "No": issues.append("crescita degli utili")
    if q4 == "No": issues.append("gestione/management")

    # sintesi qualitativa (testo invariato ma arricchito leggermente)
    if score == 4:
        qual_comment = "Tutti i principali criteri qualitativi considerati risultano positivi (profilo competitivo/gestionale solido)."
    elif score == 3:
        qual_comment = "La valutazione qualitativa è complessivamente buona (3/4 positivi), con alcuni fattori da monitorare."
    elif score == 2:
        qual_comment = "Valutazione qualitativa mista (2/4 positivi): serve approfondire le aree critiche individuate."
    elif score == 1:
        qual_comment = "Prevalgono criticità a livello qualitativo (solo 1/4 positivo), il profilo di rischio aumenta."
    else:
        qual_comment = "I criteri qualitativi risultano deboli (0/4 positivi), segnalando un profilo rischio/rendimento sfavorevole."
    if issues:
        qual_comment += " Debolezze osservate: " + ", ".join(issues) + "."

    # sintesi quantitativa + fair value (più tecnica)
    quant_comment = ""
    if price_val:
        quant_comment += f"Prezzo ~{price_val:.2f} {currency}. "
    quant_comment += f"P/E ~{pe_val:.1f}"
    if pe_val > 0:
        if pe_val < 12:
            quant_comment += " (multiplo basso). "
        elif pe_val > 25:
            quant_comment += " (multiplo elevato). "
        else:
            quant_comment += " (in linea con medie storiche). "
    else:
        quant_comment += ". "

    quant_comment += f"EPS ~{eps_val:.2f}. "

    if fair_value is not None:
        quant_comment += f"Fair value stimato ~{fair_value:.2f} {currency}. "
        if price_val:
            delta_pct = (fair_value - price_val) / price_val * 100.0
            if delta_pct >= 10:
                quant_comment += f"Scostamento positivo ~{delta_pct:.0f}% ⇒ potenziale **sottovalutazione** (margine di sicurezza). "
            elif delta_pct <= -10:
                quant_comment += f"Scostamento negativo ~{abs(delta_pct):.0f}% ⇒ **sopravvalutazione** rispetto ai fondamentali assunti. "
            else:
                quant_comment += "Scostamento contenuto ⇒ titolo grosso modo **in linea** con il fair value. "

    # ROE e D/E con lettura tecnica + dividend yield
    fin_comment = ""
    if roe_val is not None:
        fin_comment += f"ROE ~{roe_val:.0f}%"
        if roe_val >= 20:
            fin_comment += " (redditività molto elevata, superiore al costo del capitale). "
        elif roe_val >= 12:
            fin_comment += " (redditività buona/soddisfacente). "
        elif roe_val >= 8:
            fin_comment += " (redditività nella media). "
        else:
            fin_comment += " (redditività contenuta). "
    if de_val is not None:
        fin_comment += f"D/E ~{de_val:.2f}"
        if de_val <= 0.5:
            fin_comment += " (leva contenuta, resilienza finanziaria). "
        elif de_val <= 1.0:
            fin_comment += " (leva moderata, profilo equilibrato). "
        else:
            fin_comment += " (leva elevata: sensibilità più alta a tassi e ciclo). "
    if div_yield is not None and div_yield > 0:
        fin_comment += f"Dividend yield ~{div_yield:.1f}%. "
        if div_yield >= 5:
            fin_comment += "Rendimento elevato: verificare sostenibilità e payout. "
        elif div_yield <= 1:
            fin_comment += "Rendimento contenuto: strategia più orientata a reinvestimento/buyback. "

    # Unione dei commenti e output
    final_comment = qual_comment + "\n\n" + quant_comment + "\n\n" + fin_comment
    st.write(final_comment)

    # Disclaimer
    st.warning(
        "*Disclaimer:* questa analisi è fornita a scopo informativo e non costituisce consulenza finanziaria "
        "né raccomandazione di investimento."
    )

