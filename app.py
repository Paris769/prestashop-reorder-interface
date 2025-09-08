import io
import math
from typing import Tuple, List

import numpy as np
import pandas as pd
import requests
import streamlit as st
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# PrestaShop integration helpers
# ---------------------------------------------------------------------------

def _build_cart_xml(customer_id: str, items: List[dict]) -> str:
    """Costruisce l'XML necessario per creare un carrello PrestaShop.

    Ogni elemento in ``items`` deve essere un dizionario con chiavi ``product_id``
    e ``quantity``. Vengono creati i nodi <cart_row> per ogni prodotto.

    Args:
        customer_id: ID numerico del cliente in PrestaShop.
        items: elenco di dizionari con chiavi ``product_id`` e ``quantity``.

    Returns:
        XML (stringa Unicode) per la richiesta di creazione del carrello.
    """
    cart = ET.Element("cart")
    # ID cliente
    id_customer = ET.SubElement(cart, "id_customer")
    id_customer.text = str(customer_id)
    # Valori di default (lingua, valuta, indirizzi) – possono essere personalizzati
    id_lang = ET.SubElement(cart, "id_lang")
    id_lang.text = "1"  # Italiano di default
    id_currency = ET.SubElement(cart, "id_currency")
    id_currency.text = "1"
    id_address_delivery = ET.SubElement(cart, "id_address_delivery")
    id_address_delivery.text = "0"
    id_address_invoice = ET.SubElement(cart, "id_address_invoice")
    id_address_invoice.text = "0"
    id_carrier = ET.SubElement(cart, "id_carrier")
    id_carrier.text = "0"
    associations = ET.SubElement(cart, "associations")
    cart_rows = ET.SubElement(associations, "cart_rows")
    for item in items:
        row = ET.SubElement(cart_rows, "cart_row")
        id_product = ET.SubElement(row, "id_product")
        id_product.text = str(item["product_id"])
        id_product_attribute = ET.SubElement(row, "id_product_attribute")
        id_product_attribute.text = "0"
        id_address_delivery_r = ET.SubElement(row, "id_address_delivery")
        id_address_delivery_r.text = "0"
        quantity = ET.SubElement(row, "quantity")
        quantity.text = str(item["quantity"])
    return ET.tostring(cart, encoding="unicode")


def _build_order_xml(customer_id: str, cart_id: int, items: List[dict]) -> str:
    """Costruisce l'XML necessario per creare un ordine PrestaShop.

    Args:
        customer_id: ID del cliente (numerico) in PrestaShop.
        cart_id: ID del carrello appena creato.
        items: elenco di dizionari con chiavi ``product_id`` e ``quantity``.

    Returns:
        XML (stringa) per la richiesta di creazione ordine.
    """
    order = ET.Element("order")
    # Collegamenti al carrello e al cliente
    id_cart = ET.SubElement(order, "id_cart")
    id_cart.text = str(cart_id)
    id_customer = ET.SubElement(order, "id_customer")
    id_customer.text = str(customer_id)
    # Valori di default (lingua, valuta, indirizzi, carrier, metodo di pagamento)
    id_address_delivery = ET.SubElement(order, "id_address_delivery")
    id_address_delivery.text = "0"
    id_address_invoice = ET.SubElement(order, "id_address_invoice")
    id_address_invoice.text = "0"
    id_currency = ET.SubElement(order, "id_currency")
    id_currency.text = "1"
    id_lang = ET.SubElement(order, "id_lang")
    id_lang.text = "1"
    id_carrier = ET.SubElement(order, "id_carrier")
    id_carrier.text = "0"
    module = ET.SubElement(order, "module")
    module.text = "ps_checkpayment"
    payment = ET.SubElement(order, "payment")
    payment.text = "Contanti"
    # Totali inizializzati a zero; PrestaShop li sovrascriverà in base ai prezzi correnti
    total_paid = ET.SubElement(order, "total_paid")
    total_paid.text = "0"
    total_paid_real = ET.SubElement(order, "total_paid_real")
    total_paid_real.text = "0"
    # Righe d’ordine (associazioni)
    associations = ET.SubElement(order, "associations")
    order_rows = ET.SubElement(associations, "order_rows")
    for item in items:
        row = ET.SubElement(order_rows, "order_row")
        id_product = ET.SubElement(row, "product_id")
        id_product.text = str(item["product_id"])
        id_product_attribute = ET.SubElement(row, "product_attribute_id")
        id_product_attribute.text = "0"
        quantity = ET.SubElement(row, "product_quantity")
        quantity.text = str(item["quantity"])
    return ET.tostring(order, encoding="unicode")


def submit_order_to_prestashop(api_key: str, base_url: str, customer_id: str, items: List[dict]) -> str:
    """Invia un ordine a PrestaShop utilizzando il Webservice.

    Esegue due chiamate: prima crea un carrello con gli articoli, poi crea un ordine a partire
    dal carrello appena creato. Restituisce una stringa con l’esito dell’operazione.

    Args:
        api_key: chiave API del webservice PrestaShop.
        base_url: URL base del negozio (senza /api).
        customer_id: ID cliente in PrestaShop.
        items: elenco di dizionari {product_id, quantity}.

    Returns:
        Messaggio di successo o di errore.
    """
    if not api_key or not base_url:
        return "Chiave API o URL mancanti."
    # Crea carrello
    cart_xml = _build_cart_xml(customer_id, items)
    headers = {"Content-Type": "application/xml"}
    try:
        cart_resp = requests.post(
            f"{base_url}/api/carts",
            data=cart_xml.encode("utf-8"),
            headers=headers,
            auth=(api_key, ""),
            timeout=30,
        )
    except Exception as exc:
        return f"Errore connessione (carrello): {exc}"
    if not cart_resp.ok:
        return f"Errore creazione carrello: {cart_resp.status_code} - {cart_resp.text}"
    # Recupera id carrello
    try:
        root = ET.fromstring(cart_resp.text)
        cart_id = int(root.find("./cart/id").text)
    except Exception:
        return "Carrello creato ma impossibile leggere l'ID dalla risposta."
    # Crea ordine
    order_xml = _build_order_xml(customer_id, cart_id, items)
    try:
        order_resp = requests.post(
            f"{base_url}/api/orders",
            data=order_xml.encode("utf-8"),
            headers=headers,
            auth=(api_key, ""),
            timeout=30,
        )
    except Exception as exc:
        return f"Errore connessione (ordine): {exc}"
    if not order_resp.ok:
        return f"Errore creazione ordine: {order_resp.status_code} - {order_resp.text}"
    # Recupera id ordine
    try:
        root_o = ET.fromstring(order_resp.text)
        order_id = root_o.find("./order/id").text
    except Exception:
        order_id = "(id non disponibile)"
    return f"Ordine creato con successo. ID ordine: {order_id}"


def test_connection_to_prestashop(api_key: str, base_url: str) -> str:
    """Esegue una chiamata GET per verificare la connessione al webservice PrestaShop.

    Ritorna una stringa con l’esito (OK o messaggio di errore).
    """
    if not api_key or not base_url:
        return "Chiave API o URL mancanti."
    try:
        resp = requests.get(
            f"{base_url}/api/products?limit=1",
            auth=(api_key, ""),
            timeout=15,
        )
    except Exception as exc:
        return f"Errore connessione: {exc}"
    if resp.ok:
        return "Connessione OK!"
    return f"Connessione fallita: {resp.status_code} - {resp.text}"


# ---------------------------------------------------------------------------
# Funzioni di importazione ed elaborazione storico vendite per il riordino
# ---------------------------------------------------------------------------

def _load_excel_or_csv(uploaded_file: io.BytesIO) -> pd.DataFrame:
    """Carica un file Excel o CSV e restituisce un DataFrame.

    Usa la prima riga come intestazione. Il separatore CSV viene rilevato
    automaticamente da pandas.
    """
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, sep=None, engine="python")
    # default: Excel
    return pd.read_excel(uploaded_file)


def _safe_str(series: pd.Series) -> pd.Series:
    """Normalizza una serie in stringhe, rimuovendo spazi e valori NaN."""
    return series.astype(str).str.strip()


def build_recommendations_from_sales(
    df_raw: pd.DataFrame,
    col_customer: str,
    col_product: str,
    col_desc: str,
    col_qty: str,
    date_start: pd.Timestamp | None = None,
    date_end: pd.Timestamp | None = None,
    col_date: str | None = None,
    topn_per_client: int = 0,
    min_qty: int = 0,
    score_floor: float = 0.0,
) -> pd.DataFrame:
    """Genera proposte di riordino raggruppando le vendite per cliente e prodotto.

    Filtra le righe per date se ``col_date`` è fornito assieme a ``date_start`` e ``date_end``.
    Calcola la quantità complessiva acquistata da ciascun cliente per ciascun prodotto e
    normalizza le quantità rispetto al massimo acquistato dal cliente. Opzionalmente
    applica filtri su quantità minima, punteggio minimo e limita il numero di
    suggerimenti per cliente.

    Args:
        df_raw: DataFrame originale con lo storico vendite.
        col_customer: nome colonna cliente.
        col_product: nome colonna codice articolo.
        col_desc: nome colonna descrizione articolo.
        col_qty: nome colonna quantità venduta.
        date_start: data di inizio periodo (inclusa).
        date_end: data di fine periodo (inclusa).
        col_date: nome colonna della data; se None non filtra per data.
        topn_per_client: numero massimo di righe da mantenere per cliente (0 = nessun limite).
        min_qty: filtra via prodotti con quantità proposta inferiore a questo valore.
        score_floor: filtra via prodotti con punteggio normalizzato inferiore a questa soglia.

    Returns:
        DataFrame con colonne [customer_id, product_id, name, predicted_qty, normalized_score, reason].
    """
    df = df_raw.copy()
    # filtra per periodo se disponibile
    if col_date and date_start is not None and date_end is not None and col_date in df.columns:
        try:
            df[col_date] = pd.to_datetime(df[col_date])
            mask = (df[col_date] >= pd.to_datetime(date_start)) & (df[col_date] <= pd.to_datetime(date_end))
            df = df.loc[mask]
        except Exception:
            # se la conversione fallisce, ignora il filtro
            pass
    # normalizza stringhe
    df[col_customer] = _safe_str(df[col_customer])
    df[col_product] = _safe_str(df[col_product])
    df[col_desc] = df[col_desc].astype(str)
    # quantità numerica
    df[col_qty] = pd.to_numeric(df[col_qty], errors="coerce").fillna(0)
    # aggregazione: somma quantità per cliente/prodotto
    g = (df.groupby([col_customer, col_product, col_desc])[col_qty]
            .sum()
            .reset_index()
            .rename(columns={
                col_customer: "customer_id",
                col_product: "product_id",
                col_desc: "name",
                col_qty: "predicted_qty",
            }))
    # normalizza per cliente
    g["normalized_score"] = (
        g.groupby("customer_id")["predicted_qty"].transform(lambda s: (s / s.max()).fillna(0))
    ).round(3)
    g["reason"] = "Storico vendite"
    # filtri opzionali
    if min_qty > 0:
        g = g[g["predicted_qty"] >= min_qty]
    if score_floor > 0:
        g = g[g["normalized_score"] >= score_floor]
    # limitazione top-N
    if topn_per_client > 0:
        g = (g.sort_values(["customer_id", "normalized_score", "predicted_qty"], ascending=[True, False, False])
                .groupby("customer_id")
                .head(topn_per_client)
                .reset_index(drop=True))
    # ordina per cliente e punteggio decrescente
    g = g.sort_values(["customer_id", "normalized_score", "predicted_qty"], ascending=[True, False, False])
    g["predicted_qty"] = g["predicted_qty"].astype(int)
    return g[["customer_id", "product_id", "name", "predicted_qty", "normalized_score", "reason"]]


# ---------------------------------------------------------------------------
# Cross-sell: regole d'associazione e suggerimenti
# ---------------------------------------------------------------------------

def build_product_pairs(
    df_sales: pd.DataFrame,
    col_order: str,
    col_product: str,
    col_customer: str | None = None,
    exclude_patterns: Tuple[str, ...] = ("spese trasporto", "trasporto", "costo", "fee"),
    col_product_name: str | None = None,
) -> pd.DataFrame:
    """Calcola le coppie di prodotti acquistati insieme nello stesso ordine.

    Restituisce un DataFrame con colonne: [a, b, co_count, support, conf_ab, conf_ba, lift].
    Le coppie sono filtrate in modo da avere a < b per evitare duplicati.

    Args:
        df_sales: dataframe delle vendite nel periodo selezionato.
        col_order: nome colonna ordine/DDT.
        col_product: nome colonna codice articolo.
        col_customer: ignorato (presente per compatibilità).
        exclude_patterns: tuple di stringhe; se il nome prodotto contiene uno di questi
            pattern (minuscolo), viene escluso.
        col_product_name: nome colonna descrizione articolo (usata per escludere pattern).

    Returns:
        DataFrame con metrica di supporto, confidenza e lift.
    """
    df = df_sales.copy()
    # normalizza id ordine e id prodotto
    df[col_order] = _safe_str(df[col_order])
    df[col_product] = _safe_str(df[col_product])
    if col_product_name and col_product_name in df.columns:
        df[col_product_name] = df[col_product_name].astype(str)
        patt = "|".join([p for p in exclude_patterns if p])
        if patt:
            df = df[~df[col_product_name].str.lower().str.contains(patt, na=False)]
    # deduplica righe per ordine-prodotto
    base = df[[col_order, col_product]].drop_duplicates()
    # genera coppie A<B
    p1 = base.rename(columns={col_product: "a"})
    p2 = base.rename(columns={col_product: "b"})
    pairs = p1.merge(p2, on=col_order)
    pairs = pairs[pairs["a"] < pairs["b"]][["a", "b"]]
    product_pairs = (
        pairs.groupby(["a", "b"]).size().reset_index(name="co_count")
    )
    # conteggio ordini totali
    orders_tot = base[col_order].nunique()
    # conteggio ordini con ciascun prodotto
    ord_with_a = base.groupby(col_product).size().reset_index(name="ord_with")
    ord_with_a = ord_with_a.rename(columns={col_product: "prod"})
    # supporto e confidence
    result = product_pairs.copy()
    result["support"] = result["co_count"] / float(orders_tot)
    # merge conteggi per A e B
    result = result.merge(ord_with_a.rename(columns={"prod": "a", "ord_with": "ord_with_a"}), on="a", how="left")
    result = result.merge(ord_with_a.rename(columns={"prod": "b", "ord_with": "ord_with_b"}), on="b", how="left")
    result["conf_ab"] = result["co_count"] / result["ord_with_a"].replace(0, np.nan)
    result["conf_ba"] = result["co_count"] / result["ord_with_b"].replace(0, np.nan)
    # calcolo lift
    pA = result["ord_with_a"] / float(orders_tot)
    pB = result["ord_with_b"] / float(orders_tot)
    pAB = result["co_count"] / float(orders_tot)
    result["lift"] = pAB / (pA * pB).replace(0, np.nan)
    result = result.replace([np.inf, -np.inf], np.nan).dropna(subset=["lift"])
    return result[["a", "b", "co_count", "support", "conf_ab", "conf_ba", "lift"]].sort_values("lift", ascending=False)


def suggest_cross_sell_for_customer(
    df_sales: pd.DataFrame,
    rules: pd.DataFrame,
    customer_id: str,
    col_customer: str,
    col_product: str,
    topn: int = 8,
    min_support: float = 0.002,
    min_conf: float = 0.05,
    min_lift: float = 1.10,
    weight_lift: float = 0.6,
    weight_conf: float = 0.4,
) -> pd.DataFrame:
    """Propone prodotti in cross-sell per un cliente dato, utilizzando le regole d'associazione.

    Args:
        df_sales: DataFrame delle vendite nel periodo selezionato.
        rules: DataFrame con le regole d’associazione (a, b, support, conf_ab, conf_ba, lift).
        customer_id: id cliente di cui calcolare i cross-sell.
        col_customer: nome colonna cliente.
        col_product: nome colonna codice articolo.
        topn: numero massimo di suggerimenti da restituire.
        min_support, min_conf, min_lift: soglie minime per filtrare le regole.
        weight_lift, weight_conf: pesi per la costruzione dello score finale.

    Returns:
        DataFrame con colonne [product_id, source_product, score, why].
    """
    # prodotti acquistati dal cliente
    df = df_sales.copy()
    df[col_customer] = _safe_str(df[col_customer])
    df[col_product] = _safe_str(df[col_product])
    bought = df.loc[df[col_customer] == str(customer_id), [col_product]].drop_duplicates()[col_product].tolist()
    if not bought:
        return pd.DataFrame(columns=["product_id", "source_product", "score", "why"])
    # filtra regole forti dove A (a) è uno dei prodotti acquistati
    r = rules[
        (rules["a"].isin(bought))
        & (rules["support"] >= min_support)
        & (rules["conf_ab"] >= min_conf)
        & (rules["lift"] >= min_lift)
    ].copy()
    if r.empty:
        return pd.DataFrame(columns=["product_id", "source_product", "score", "why"])
    # calcolo score combinato
    r["score"] = (weight_lift * r["lift"]) + (weight_conf * r["conf_ab"])
    r["product_id"] = r["b"]
    r["source_product"] = r["a"]
    # motivo: descrizione breve con lift/conf
    r["why"] = r.apply(
        lambda x: f"Spesso acquistato con {x['a']} (lift {x['lift']:.2f}, conf {x['conf_ab']:.2%})",
        axis=1,
    )
    # deduplica per prodotto consigliato, tenendo il punteggio più alto
    r = (
        r.sort_values("score", ascending=False)
        .drop_duplicates(subset=["product_id"], keep="first")
        .reset_index(drop=True)
    )
    return r[["product_id", "source_product", "score", "why"]].head(topn)


# ---------------------------------------------------------------------------
# Interfaccia Streamlit
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Gestione riordini PrestaShop", layout="wide")
st.title("Gestione riordini PrestaShop")

tab_import, tab_manage, tab_xsell = st.tabs(["Import SAP", "Gestione riordini", "Cross-sell"])


with tab_import:
    st.subheader("Import vendite SAP (Excel/CSV)")
    uploaded = st.file_uploader("Carica il file vendite", type=["xls", "xlsx", "csv"])
    if uploaded is not None:
        try:
            df_raw = _load_excel_or_csv(uploaded)
        except Exception as exc:
            st.error(f"Errore nella lettura del file: {exc}")
            df_raw = None
        if df_raw is not None:
            st.caption("Anteprima dei dati (prime 10 righe)")
            st.dataframe(df_raw.head(10), use_container_width=True)
            cols = df_raw.columns.tolist()
            # definizione liste candidati per mappatura automatica
            candidate_customer = ["cardcode", "card code", "customer", "cliente", "codice cliente/fornitore", "codice cliente", "cliente"]
            candidate_product = ["itemcode", "item code", "codice articolo", "articolo", "codice", "sku"]
            candidate_name = ["itemname", "item name", "descrizione articolo", "descrizione", "descarticolo", "product name", "name"]
            candidate_qty = ["quantity", "qty", "qta", "qtasped", "quantita", "qta venduta"]
            candidate_order = ["docnum", "ddtnumber", "numero ddt", "ordernum", "numdocumento", "doc"]
            candidate_date = ["docdate", "data", "doc date", "date"]
            def preselect(candidates):
                # trova la prima colonna che matcha uno dei candidati (case insensitive)
                for c in candidates:
                    for i, col in enumerate(cols):
                        if col.lower() == c.lower():
                            return i
                return 0
            col_customer = st.selectbox("Colonna cliente", cols, index=preselect(candidate_customer))
            col_product = st.selectbox("Colonna articolo", cols, index=preselect(candidate_product))
            col_desc = st.selectbox("Colonna descrizione", cols, index=preselect(candidate_name))
            col_qty = st.selectbox("Colonna quantità", cols, index=preselect(candidate_qty))
            # colonna ordine/DDT
            col_order = st.selectbox("Colonna ordine/DDT", cols, index=preselect(candidate_order))
            # colonna data (opzionale) con opzione nessuna
            date_options = ["(nessuna)"] + cols
            date_idx = 0
            # se esiste un match in candidate_date, seleziona
            for candidate in candidate_date:
                for i, col in enumerate(cols):
                    if col.lower() == candidate.lower():
                        date_idx = i + 1  # +1 perché c'è l'opzione '(nessuna)' in testa
                        break
                if date_idx:
                    break
            col_date_sel = st.selectbox("Colonna data (opzionale)", date_options, index=date_idx)
            # periodo di riferimento
            date_start = None
            date_end = None
            if col_date_sel != "(nessuna)":
                try:
                    # prova a convertire per ricavare min e max
                    temp_dates = pd.to_datetime(df_raw[col_date_sel])
                    min_date = temp_dates.min().date()
                    max_date = temp_dates.max().date()
                    # selettore intervallo
                    date_start, date_end = st.date_input(
                        "Seleziona intervallo da analizzare",
                        value=(min_date, max_date),
                        min_value=min_date,
                        max_value=max_date,
                        format="DD/MM/YYYY",
                    )
                except Exception:
                    st.warning("La colonna data selezionata non contiene valori interpretabili come date.")
                    col_date_sel = "(nessuna)"
            # opzioni avanzate
            with st.expander("Opzioni di generazione proposte"):
                topn_per_client = st.number_input(
                    "Top-N prodotti per cliente (0 = nessun limite)", 0, 100, 0, step=1
                )
                min_qty = st.number_input(
                    "Quantità minima proposta", 0, 99999, 0, step=1
                )
                score_floor = st.slider(
                    "Soglia minima punteggio normalizzato", 0.0, 1.0, 0.0, step=0.01
                )
            if st.button("Genera proposte"):
                # verifica che le colonne siano tutte diverse
                selected_cols = [col_customer, col_product, col_desc, col_qty]
                if len(selected_cols) != len(set(selected_cols)):
                    st.error("Le colonne selezionate devono essere tutte diverse.")
                else:
                    # filtra periodo e genera proposte
                    recs = build_recommendations_from_sales(
                        df_raw=df_raw,
                        col_customer=col_customer,
                        col_product=col_product,
                        col_desc=col_desc,
                        col_qty=col_qty,
                        date_start=date_start,
                        date_end=date_end,
                        col_date=(None if col_date_sel == "(nessuna)" else col_date_sel),
                        topn_per_client=int(topn_per_client),
                        min_qty=int(min_qty),
                        score_floor=float(score_floor),
                    )
                    # salva in sessione
                    st.session_state["all_df"] = recs.copy()
                    # salva raw sales e colonne per cross-sell
                    # filtra raw per periodo
                    df_period = df_raw.copy()
                    if col_date_sel != "(nessuna)" and date_start is not None and date_end is not None:
                        try:
                            df_period[col_date_sel] = pd.to_datetime(df_period[col_date_sel])
                            mask = (df_period[col_date_sel] >= pd.to_datetime(date_start)) & (df_period[col_date_sel] <= pd.to_datetime(date_end))
                            df_period = df_period.loc[mask]
                        except Exception:
                            pass
                    st.session_state["sales_df_period"] = df_period.copy()
                    st.session_state["col_customer"] = col_customer
                    st.session_state["col_product"] = col_product
                    st.session_state["col_name"] = col_desc
                    st.session_state["col_qty"] = col_qty
                    st.session_state["col_order"] = col_order
                    st.session_state["col_date"] = None if col_date_sel == "(nessuna)" else col_date_sel
                    st.session_state["date_start"] = date_start
                    st.session_state["date_end"] = date_end
                    # reset cross-sell rules
                    if "xsell_rules" in st.session_state:
                        del st.session_state["xsell_rules"]
                    st.success(f"Proposte generate: {len(recs):,}. Vai alla scheda 'Gestione riordini' per continuare.")
                    st.dataframe(recs, use_container_width=True)


with tab_manage:
    st.subheader("Gestione riordini e invio ordine")
    # pannello laterale con impostazioni PrestaShop
    with st.sidebar:
        st.markdown("### Configurazione PrestaShop")
        api_key = st.text_input("Chiave API PrestaShop", type="password")
        base_url = st.text_input("URL base negozio", value="https://")
        if st.button("Test connessione"):
            if not api_key or not base_url or base_url == "https://":
                st.sidebar.warning("Inserisci sia chiave che URL per testare.")
            else:
                result = test_connection_to_prestashop(api_key.strip(), base_url.strip().rstrip("/"))
                if result == "Connessione OK!":
                    st.sidebar.success(result)
                else:
                    st.sidebar.error(result)
    if "all_df" not in st.session_state or st.session_state["all_df"] is None:
        st.info("Devi prima importare e generare le proposte nella scheda Import SAP.")
    else:
        df_all = st.session_state["all_df"].copy()
        # selezione cliente
        clients = sorted(df_all["customer_id"].unique().tolist())
        # Usa una chiave esplicita per evitare conflitti con altri selectbox con la stessa etichetta
        selected_client = st.selectbox("Seleziona cliente", clients, key="manage_client_select")
        # visualizza data periodo
        if st.session_state.get("date_start") is not None and st.session_state.get("date_end") is not None:
            st.caption(
                f"Periodo proposte: {st.session_state['date_start']} – {st.session_state['date_end']}"
            )
        if selected_client:
            df_client = df_all[df_all["customer_id"] == selected_client].copy().reset_index(drop=True)
            # editor quantità
            st.markdown("### Proposte di riordino")
            # usa data editor per consentire modifica delle quantità
            edited = st.data_editor(
                df_client,
                column_config={
                    "predicted_qty": st.column_config.NumberColumn("Quantità proposta", min_value=0, step=1),
                    "normalized_score": st.column_config.NumberColumn("Score", disabled=True),
                    "reason": st.column_config.TextColumn("Motivo", disabled=True),
                    "product_id": st.column_config.TextColumn("Codice articolo", disabled=True),
                    "name": st.column_config.TextColumn("Descrizione", disabled=True),
                },
                num_rows="dynamic",
                use_container_width=True,
                key="editor_client",
            )
            # salva le modifiche di quantità su all_df
            if st.button("Salva modifiche proposte"):
                # aggiorna session state all_df con le nuove quantità
                updated = df_all.copy()
                # per ogni riga modificata, aggiorna predicted_qty
                for idx, row in edited.iterrows():
                    mask = (
                        (updated["customer_id"] == selected_client)
                        & (updated["product_id"] == row["product_id"])
                    )
                    updated.loc[mask, "predicted_qty"] = int(row["predicted_qty"])
                st.session_state["all_df"] = updated.copy()
                st.success("Modifiche salvate. Puoi procedere all'invio.")
            # Azione invio ordine
            st.markdown("### Invia ordine a PrestaShop")
            # costruisci elenco items da inviare
            items_to_send = []
            for _, row in edited.iterrows():
                qty = int(row["predicted_qty"])
                if qty > 0:
                    items_to_send.append({"product_id": row["product_id"], "quantity": qty})
            if st.button("Finalizza e invia ordine"):
                if not items_to_send:
                    st.warning("Non ci sono articoli con quantità > 0 da inviare.")
                elif not api_key or not base_url or base_url == "https://":
                    st.error("Configura la chiave API e l'URL del negozio nella barra laterale.")
                else:
                    msg = submit_order_to_prestashop(api_key.strip(), base_url.strip().rstrip("/"), selected_client, items_to_send)
                    if msg.startswith("Ordine creato"):
                        st.success(msg)
                    else:
                        st.error(msg)


with tab_xsell:
    st.subheader("Suggerimenti Cross-sell (per cliente)")
    # verifica prerequisiti
    if "sales_df_period" not in st.session_state or st.session_state["sales_df_period"] is None:
        st.info("Carica i dati nella scheda Import SAP e genera le proposte per abilitare i suggerimenti cross-sell.")
    else:
        df_sales = st.session_state["sales_df_period"].copy()
        col_customer = st.session_state.get("col_customer")
        col_product = st.session_state.get("col_product")
        col_name = st.session_state.get("col_name")
        col_order = st.session_state.get("col_order")
        if not (col_customer and col_product and col_order):
            st.warning("Mappatura colonne incompleta. Re-importa il file.")
        else:
            # selezione cliente unico
            clients = sorted(df_sales[col_customer].astype(str).unique().tolist())
            # Usa una chiave distinta per evitare StreamlitDuplicateElementID quando esistono più selectbox con lo stesso label
            sel_client = st.selectbox("Seleziona cliente", clients, key="xsell_client_select")
            # intervallo periodo
            ds = st.session_state.get("date_start")
            de = st.session_state.get("date_end")
            if ds and de:
                st.caption(f"Storico analizzato: {ds} – {de}")
            # soglie e parametri
            col1, col2, col3 = st.columns(3)
            with col1:
                min_support = st.number_input("Supporto minimo", min_value=0.0, max_value=1.0, value=0.002, step=0.001, format="%.3f")
            with col2:
                min_conf = st.number_input("Confidenza minima", min_value=0.0, max_value=1.0, value=0.05, step=0.01, format="%.2f")
            with col3:
                min_lift = st.number_input("Lift minimo", min_value=0.0, max_value=10.0, value=1.10, step=0.05, format="%.2f")
            c1, c2, c3 = st.columns(3)
            with c1:
                weight_lift = st.slider("Peso lift", 0.0, 1.0, 0.6, step=0.05)
            with c2:
                weight_conf = st.slider("Peso confidenza", 0.0, 1.0, 0.4, step=0.05)
            with c3:
                topn = st.number_input("Num. suggerimenti", 1, 50, 8, step=1)
            # esclusioni basate sul nome prodotto
            with st.expander("Escludi prodotti (nome contiene)"):
                excl_input = st.text_input("Parole chiave da escludere (separate da punto e virgola)", "spese trasporto;trasporto;costo;fee")
                exclude_patterns = tuple([w.strip().lower() for w in excl_input.split(";") if w.strip()])
            # costruisci regole solo una volta per periodo
            if "xsell_rules" not in st.session_state:
                rules = build_product_pairs(
                    df_sales=df_sales,
                    col_order=col_order,
                    col_product=col_product,
                    exclude_patterns=exclude_patterns,
                    col_product_name=col_name,
                )
                st.session_state["xsell_rules"] = rules
            else:
                rules = st.session_state["xsell_rules"]
            # suggerisci per cliente
            recs = suggest_cross_sell_for_customer(
                df_sales=df_sales,
                rules=rules,
                customer_id=sel_client,
                col_customer=col_customer,
                col_product=col_product,
                topn=int(topn),
                min_support=float(min_support),
                min_conf=float(min_conf),
                min_lift=float(min_lift),
                weight_lift=float(weight_lift),
                weight_conf=float(weight_conf),
            )
            if recs.empty:
                st.warning("Nessun suggerimento cross-sell con le soglie selezionate. Riduci le soglie o amplia il periodo.")
            else:
                # aggiungi descrizione prodotto se disponibile
                if col_name and col_name in df_sales.columns:
                    names = df_sales[[col_product, col_name]].drop_duplicates().rename(columns={col_product: "product_id", col_name: "name"})
                    recs = recs.merge(names, on="product_id", how="left")
                st.dataframe(recs, use_container_width=True)
                st.markdown("### Aggiungi suggerimenti alle proposte")
                # selezione quantità per aggiunta
                items_to_add = []
                for _, row in recs.iterrows():
                    col_left, col_mid, col_right = st.columns([4, 2, 2])
                    with col_left:
                        label = row.get("name", row["product_id"])
                        st.write(f"**{label}**")
                        st.caption(row["why"])
                    with col_mid:
                        qty = st.number_input(f"Qtà {row['product_id']}", min_value=0, max_value=9999, value=0, step=1, key=f"xsell_qty_{row['product_id']}")
                    with col_right:
                        st.write("")
                    if qty and qty > 0:
                        items_to_add.append({
                            "customer_id": sel_client,
                            "product_id": row["product_id"],
                            "name": row.get("name", row["product_id"]),
                            "predicted_qty": int(qty),
                            "normalized_score": round(float(row["score"]), 3),
                            "reason": row["why"],
                        })
                if items_to_add:
                    if st.button("Aggiungi alle proposte"):
                        # aggiunge gli items alle proposte esistenti
                        if "all_df" in st.session_state and st.session_state["all_df"] is not None:
                            current = st.session_state["all_df"].copy()
                            new_df = pd.DataFrame(items_to_add)
                            combined = pd.concat([current, new_df], ignore_index=True)
                            # deduplica (cliente, prodotto) mantenendo la riga con quantità maggiore
                            combined = combined.sort_values(["customer_id", "product_id", "predicted_qty"], ascending=[True, True, False])
                            combined = combined.drop_duplicates(subset=["customer_id", "product_id"], keep="first").reset_index(drop=True)
                            st.session_state["all_df"] = combined
                            st.success("Suggerimenti aggiunti alle proposte. Verifica nella scheda Gestione riordini.")
                        else:
                            st.error("Nessuna proposta esistente a cui aggiungere i suggerimenti.")