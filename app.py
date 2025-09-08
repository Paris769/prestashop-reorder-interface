import io
from datetime import datetime
import pandas as pd
import streamlit as st
import requests
import xml.etree.ElementTree as ET

# Configurazione della pagina
st.set_page_config(page_title="Gestione Riordini PrestaShop", layout="wide")

# Barra laterale per la chiave API e l'URL del negozio PrestaShop
with st.sidebar:
    # La chiave API è necessaria per autenticare le chiamate al Webservice
    api_key_input = st.text_input("Chiave API PrestaShop", type="password")
      # Test connessione al Webservice PrestaShop
        if st.button("Test connessione"):
            if api_key_input and base_url_input:
                test_url = base_url_input.rstrip("/") + "/api/products?limit=1"
                try:
                    resp = requests.get(test_url, auth=(api_key_input, ""), timeout=10)
                    if resp.status_code == 200:
                    st.success("Connessione al Webservice PrestaShop OK!")
                else:
                    st.error(f"Errore {resp.status_code}: {resp.text}")
            except Exception as e:
                st.error(f"Errore di connessione: {e}")
        else:
            st.warning("Inserisci prima la chiave API e l'URL base.")
  # URL base del negozio (es. https://mioshop.it). Serve per costruire gli endpoint
    base_url_input = st.text_input(
        "URL base PrestaShop", placeholder="https://example.com"
   
  
  

# Funzioni di utilità per l'importazione di Excel/CSV
def _load_excel_or_csv(uploaded_file: io.BytesIO) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, sep=None, engine="python")
    return pd.read_excel(uploaded_file)

def _safe_str(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()

def build_recommendations_from_sales(
    df_raw: pd.DataFrame,
    col_customer: str,
    col_product: str,
    col_desc: str,
    col_qty: str,
    col_date=None,
    date_start=None,
    
    date_end=None,
) -> pd.DataFrame:
    df = df_raw.copy()
    df[col_customer] = _safe_str(df[col_customer])
    df[col_product] = _safe_str(df[col_product])
    df[col_desc] = _safe_str(df[col_desc])
    df[col_qty] = pd.to_numeric(df[col_qty], errors="coerce").fillna(0)
    if col_date:
        df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
    if col_date and date_start is not None and date_end is not None:
        df = df[(df[col_date] >= date_start) & (df[col_date] <= date_end)]
    g = (
        df.groupby([col_customer, col_product, col_desc])[col_qty]
        .sum()
        .reset_index()
        .rename(
            columns={
                col_customer: "customer_id",
                col_product: "product_id",
                col_desc: "name",
                col_qty: "predicted_qty",
            }
        )
    )
    # Normalizza per cliente
    g["normalized_score"] = (
        g.groupby("customer_id")["predicted_qty"]
        .transform(lambda s: (s / s.max()).fillna(0))
        .round(3)
    )
    g["reason"] = "Storico vendite"
    g["predicted_qty"] = g["predicted_qty"].astype(int)
    g = g.sort_values(
        ["customer_id", "normalized_score", "predicted_qty"],
        ascending=[True, False, False],
    )
    return g[
        [
            "customer_id",
            "product_id",
            "name",
            "predicted_qty",
            "normalized_score",
            "reason",
        ]
    ]

# Funzione per generare le raccomandazioni applicando i filtri di business
def generate_recommendations(
    df_raw: pd.DataFrame,
    col_customer: str,
    col_product: str,
    col_desc: str,
    col_qty: str,
    col_date: str = None,
    date_start: datetime = None,
    date_end: datetime = None,
    top_n: int = 0,
    min_qty: int = 0,
    score_floor: float = 0.0,
) -> pd.DataFrame:
    """
    Genera un DataFrame di raccomandazioni a partire dai dati di vendita grezzi.

    Filtra il dataset per l'intervallo di date se fornito, raggruppa per cliente e prodotto,
    normalizza le quantità e applica eventuali filtri (quantità minima, soglia di punteggio,
    top-N per cliente).

    Parameters
    ----------
    df_raw : DataFrame
        Il dataset originale delle vendite.
    col_customer, col_product, col_desc, col_qty : str
        Nomi delle colonne per cliente, articolo, descrizione e quantità.
    col_date : str, opzionale
        Nome della colonna data da utilizzare per il filtro temporale.
    date_start, date_end : datetime, opzionale
        Limiti inferiori e superiori del periodo di riferimento.
    top_n : int
        Numero massimo di prodotti per cliente (0 = nessun limite).
    min_qty : int
        Quantità minima proposta per includere un prodotto nelle raccomandazioni.
    score_floor : float
        Soglia minima del punteggio normalizzato per includere un prodotto.

    Returns
    -------
    DataFrame
        Il DataFrame delle raccomandazioni filtrato e ordinato.
    """
    # Calcola raccomandazioni di base
    df_recs = build_recommendations_from_sales(
        df_raw,
        col_customer=col_customer,
        col_product=col_product,
        col_desc=col_desc,
        col_qty=col_qty,
        col_date=col_date,
        date_start=date_start,
        date_end=date_end,
    )
    # Applica filtri business
    if min_qty > 0:
        df_recs = df_recs[df_recs["predicted_qty"] >= min_qty]
    if score_floor > 0:
        df_recs = df_recs[df_recs["normalized_score"] >= score_floor]
    if top_n > 0:
        df_recs = (
            df_recs.sort_values(
                ["customer_id", "normalized_score", "predicted_qty"],
                ascending=[True, False, False],
            )
            .groupby("customer_id")
            .head(top_n)
            .reset_index(drop=True)
        )
    return df_recs.copy()

# ---------- Funzioni di integrazione con PrestaShop ----------
def _build_cart_xml(customer_id: str, items: list, id_currency: int = 1, id_lang: int = 1) -> str:
    """
    Costruisce una stringa XML per la creazione di un carrello su PrestaShop.

    Parameters
    ----------
    customer_id : str
        ID del cliente in PrestaShop.
    items : list of dict
        Lista di articoli da inserire nel carrello; ciascun dizionario deve contenere
        'product_id' e 'quantity'.
    id_currency : int
        ID della valuta (default: 1 per Euro).
    id_lang : int
        ID della lingua (default: 1 per Italiano).

    Returns
    -------
    str
        XML formattato come richiesto dal Webservice PrestaShop.
    """
    rows_xml = ""
    for item in items:
        rows_xml += (
            f"        <cart_row>\n"
            f"          <id_product><![CDATA[{item['product_id']}]]></id_product>\n"
            f"          <quantity><![CDATA[{item['quantity']}]]></quantity>\n"
            f"        </cart_row>\n"
        )
    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<prestashop>\n"
        "  <cart>\n"
        f"    <id_currency><![CDATA[{id_currency}]]></id_currency>\n"
        f"    <id_lang><![CDATA[{id_lang}]]></id_lang>\n"
        f"    <id_customer><![CDATA[{customer_id}]]></id_customer>\n"
        "    <associations>\n"
        "      <cart_rows nodeType=\"cart_row\" virtualEntity=\"true\">\n"
        f"{rows_xml}"
        "      </cart_rows>\n"
        "    </associations>\n"
        "  </cart>\n"
        "</prestashop>"
    )
    return xml


def _build_order_xml(
    customer_id: str,
    cart_id: int,
    items: list,
    id_address_delivery: int = 1,
    id_address_invoice: int = 1,
    id_currency: int = 1,
    id_lang: int = 1,
    module: str = "bankwire",
    payment: str = "Pagamento su conto bancario",
) -> str:
    """
    Costruisce una stringa XML per la creazione di un ordine su PrestaShop.

    Parameters
    ----------
    customer_id : str
        ID del cliente.
    cart_id : int
        ID del carrello appena creato.
    items : list of dict
        Lista di articoli con 'product_id' e 'quantity'.
    id_address_delivery : int
        ID indirizzo di consegna (default 1).
    id_address_invoice : int
        ID indirizzo di fatturazione (default 1).
    id_currency : int
        ID della valuta (default 1).
    id_lang : int
        ID della lingua (default 1).
    module : str
        Nome del modulo di pagamento (default 'bankwire').
    payment : str
        Descrizione del pagamento (default 'Pagamento su conto bancario').

    Returns
    -------
    str
        XML formattato per la creazione di un ordine.
    """
    rows_xml = ""
    for item in items:
        rows_xml += (
            f"        <order_row>\n"
            f"          <product_id><![CDATA[{item['product_id']}]]></product_id>\n"
            f"          <product_quantity><![CDATA[{item['quantity']}]]></product_quantity>\n"
            f"        </order_row>\n"
        )
    xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<prestashop>\n"
        "  <order>\n"
        f"    <id_customer><![CDATA[{customer_id}]]></id_customer>\n"
        f"    <id_address_delivery><![CDATA[{id_address_delivery}]]></id_address_delivery>\n"
        f"    <id_address_invoice><![CDATA[{id_address_invoice}]]></id_address_invoice>\n"
        f"    <id_cart><![CDATA[{cart_id}]]></id_cart>\n"
        f"    <id_currency><![CDATA[{id_currency}]]></id_currency>\n"
        f"    <id_lang><![CDATA[{id_lang}]]></id_lang>\n"
        "    <current_state><![CDATA[2]]></current_state>\n"
        f"    <module><![CDATA[{module}]]></module>\n"
        f"    <payment><![CDATA[{payment}]]></payment>\n"
        "    <total_paid><![CDATA[0]]></total_paid>\n"
        "    <total_paid_real><![CDATA[0]]></total_paid_real>\n"
        "    <total_products><![CDATA[0]]></total_products>\n"
        "    <total_products_wt><![CDATA[0]]></total_products_wt>\n"
        "    <conversion_rate><![CDATA[1]]></conversion_rate>\n"
        "    <associations>\n"
        "      <order_rows nodeType=\"order_row\" virtualEntity=\"true\">\n"
        f"{rows_xml}"
        "      </order_rows>\n"
        "    </associations>\n"
        "  </order>\n"
        "</prestashop>"
    )
    return xml


def submit_order_to_prestashop(api_key: str, base_url: str, customer_id: str, items: list) -> str:
    """
    Invoca il Webservice PrestaShop per creare un carrello e un ordine.

    Parameters
    ----------
    api_key : str
        Chiave API del Webservice PrestaShop.
    base_url : str
        URL base del negozio (es. https://mioshop.it). Non deve terminare con slash.
    customer_id : str
        ID del cliente.
    items : list of dict
        Lista di prodotti da ordinare, ciascuno con 'product_id' e 'quantity'.

    Returns
    -------
    str
        Messaggio di stato dell'operazione.
    """
    # Normalizza l'URL
    base_url = base_url.rstrip("/")
    try:
        # Costruisci XML del carrello
        cart_xml = _build_cart_xml(customer_id, items)
        cart_endpoint = f"{base_url}/api/carts"
        headers = {"Content-Type": "application/xml"}
        # Effettua richiesta per creare il carrello
        cart_resp = requests.post(
            cart_endpoint,
            data=cart_xml.encode("utf-8"),
            headers=headers,
            auth=(api_key, ""),
            timeout=30,
        )
        if not cart_resp.ok:
            return f"Errore creazione carrello: {cart_resp.status_code} {cart_resp.text}"
        # Parsea la risposta per ottenere l'ID del carrello
        try:
            root = ET.fromstring(cart_resp.content)
            cart_id = int(root.find('.//cart/id').text)
        except Exception:
            return "Cart creato ma impossibile leggere ID carrello dalla risposta."
        # Costruisci XML dell'ordine
        order_xml = _build_order_xml(customer_id, cart_id, items)
        order_endpoint = f"{base_url}/api/orders"
        order_resp = requests.post(
            order_endpoint,
            data=order_xml.encode("utf-8"),
            headers=headers,
            auth=(api_key, ""),
            timeout=30,
        )
        if not order_resp.ok:
            return f"Errore creazione ordine: {order_resp.status_code} {order_resp.text}"
        # Parsea la risposta per ottenere l'ID ordine
        try:
            root_o = ET.fromstring(order_resp.content)
            order_id = root_o.find('.//order/id').text
        except Exception:
            order_id = "(id non disponibile)"
        return f"Ordine creato con successo su PrestaShop (ID carrello {cart_id}, ID ordine {order_id})."
    except Exception as e:
        return f"Errore invio a PrestaShop: {e}"

# Inizializza session_state se necessario
if "all_df" not in st.session_state:
    st.session_state["all_df"] = None

# Tabs per l'applicazione
tab_import, tab_manage = st.tabs(["Import SAP", "Gestione riordini"])

with tab_import:
    st.subheader("Import vendite SAP (Excel/CSV)")
    uploaded_file = st.file_uploader(
        "Carica il file vendite (xlsx/xls/csv)", type=["xlsx", "xls", "csv"]
    )
    if uploaded_file:
        try:
            df_raw = _load_excel_or_csv(uploaded_file)
            st.caption("Anteprima dati caricati")
            st.dataframe(df_raw.head(10), use_container_width=True)
            cols = df_raw.columns.tolist()

            # funzione per preselezionare le colonne
            def preselect(candidates):
                for c in candidates:
                    if c in cols:
                        return cols.index(c)
                return 0

            col_customer = st.selectbox(
                "Colonna cliente",
                cols,
                index=preselect(
                    [
                        "cardcode",
                        "CardCode",
                        "Codice cliente/fornitore",
                        "Cliente",
                        "CodCliente",
                    ]
                ),
            )
            col_product = st.selectbox(
                "Colonna articolo",
                cols,
                index=preselect(
                    [
                        "ItemCode",
                        "Codice articolo",
                        "Articolo",
                        "CodArticolo",
                    ]
                ),
            )
            col_desc = st.selectbox(
                "Colonna descrizione",
                cols,
                index=preselect(
                    [
                        "ItemName",
                        "Descrizione articolo",
                        "Descrizione",
                        "DescArticolo",
                    ]
                ),
            )
            col_qty = st.selectbox(
                "Colonna quantità (venduto/spedito)",
                cols,
                index=preselect(
                    [
                        "Quantity",
                        "QtaSped",
                        "Qta",
                        "Quantità",
                        "QtaVenduta",
                    ]
                ),
            )

            # Colonna data opzionale
            col_date_options = ["(nessuna)"] + cols
            # Preseleziona la colonna data usando nomi comuni
            date_candidates = ["DocDate", "Doc Date", "Data", "Date", "DataOrdine"]
            date_index = 0
            for i, c in enumerate(cols):
                if c in date_candidates:
                    date_index = i + 1  # +1 perché "(nessuna)" è all'indice 0
                    break
            col_date_sel = st.selectbox(
                "Colonna data (opzionale)", col_date_options, index=date_index
            )

            date_start = None
            date_end = None
            if col_date_sel != "(nessuna)":
                dates_series = pd.to_datetime(
                    df_raw[col_date_sel], errors="coerce"
                )
                min_date = dates_series.min()
                max_date = dates_series.max()
                if pd.notnull(min_date) and pd.notnull(max_date):
                    date_range = st.date_input(
                        "Intervallo date",
                        value=(min_date.date(), max_date.date()),
                    )
                    if (
                        isinstance(date_range, tuple)
                        and len(date_range) == 2
                    ):
                        date_start = pd.to_datetime(date_range[0])
                        date_end = pd.to_datetime(date_range[1])

            with st.expander("Opzioni di generazione"):
                top_n = st.number_input(
                    "Top-N prodotti per cliente (0 = nessun limite)",
                    0,
                    1000,
                    0,
                    step=1,
                )
                min_qty = st.number_input(
                    "Quantità minima proposta", 0, 99999, 0, step=1
                )
                score_floor = st.slider(
                    "Soglia minima di punteggio normalizzato",
                    0.0,
                    1.0,
                    0.0,
                    0.01,
                )

            if st.button("Genera proposte da Excel"):
                # Verifica che tutte le colonne selezionate siano diverse
                if len({col_customer, col_product, col_desc, col_qty}) < 4:
                    st.error(
                        "Ogni colonna selezionata deve essere diversa. Per favore, seleziona colonne distinte per cliente, articolo, descrizione e quantità."
                    )
                else:
                    # Determina la colonna data da utilizzare
                    selected_col_date = None if col_date_sel == "(nessuna)" else col_date_sel
                    # Genera le raccomandazioni con i parametri selezionati
                    df_recs = generate_recommendations(
                        df_raw,
                        col_customer=col_customer,
                        col_product=col_product,
                        col_desc=col_desc,
                        col_qty=col_qty,
                        col_date=selected_col_date,
                        date_start=date_start,
                        date_end=date_end,
                        top_n=top_n,
                        min_qty=min_qty,
                        score_floor=score_floor,
                    )
                    # salva dati e parametri in sessione per poter rigenerare le proposte
                    st.session_state["df_raw"] = df_raw
                    st.session_state["col_customer"] = col_customer
                    st.session_state["col_product"] = col_product
                    st.session_state["col_desc"] = col_desc
                    st.session_state["col_qty"] = col_qty
                    st.session_state["col_date"] = selected_col_date
                    st.session_state["top_n"] = top_n
                    st.session_state["min_qty"] = min_qty
                    st.session_state["score_floor"] = score_floor
                    # salva intervallo date e DataFrame raccomandazioni
                    st.session_state["date_start"] = date_start
                    st.session_state["date_end"] = date_end
                    st.session_state["all_df"] = df_recs.copy()

                    st.success(
                        f"Proposte generate: {len(df_recs)}. Vai alla scheda 'Gestione riordini' per continuare."
                    )
                    st.dataframe(
                        df_recs.head(50), use_container_width=True
                    )

                    # Download file delle proposte
                    csv_bytes = df_recs.to_csv(index=False).encode("utf-8")
                    json_bytes = df_recs.to_json(
                        orient="records", force_ascii=False
                    ).encode("utf-8")
                    st.download_button(
                        "Scarica proposte (CSV)",
                        data=csv_bytes,
                        file_name="proposte_riordino.csv",
                        mime="text/csv",
                    )
                    st.download_button(
                        "Scarica proposte (JSON)",
                        data=json_bytes,
                        file_name="proposte_riordino.json",
                        mime="application/json",
                    )
        except Exception as e:
            st.error(f"Errore durante l'elaborazione del file: {e}")

with tab_manage:
    st.subheader("Gestione riordini")
    df = st.session_state.get("all_df")
    if df is None or df is False:
        # fallback a dati demo
        try:
            df = pd.read_json("recommendations_demo.json")
            st.info(
                "Nessun file importato. Stai visualizzando dati di esempio."
            )
        except Exception:
            df = pd.DataFrame()

    if df is not None and not df.empty:
        # Visualizza il periodo selezionato se disponibile
        if (
            "date_start" in st.session_state
            and st.session_state["date_start"] is not None
        ):
            st.info(
                f"Periodo selezionato: {st.session_state['date_start'].date()} – {st.session_state['date_end'].date()}"
            )

        # Se disponibile il dataframe originale e la colonna data, consenti di aggiornare il periodo
        if "df_raw" in st.session_state and st.session_state.get("col_date"):
            col_date_name = st.session_state.get("col_date")
            if col_date_name:
                df_raw_cached = st.session_state["df_raw"]
                # Calcola l'intervallo minimo e massimo dal dataset grezzo
                dates_series_out = pd.to_datetime(
                    df_raw_cached[col_date_name], errors="coerce"
                )
                min_date_out = dates_series_out.min()
                max_date_out = dates_series_out.max()
                # Imposta valori di default
                current_start = st.session_state.get("date_start")
                current_end = st.session_state.get("date_end")
                default_start = (
                    current_start.date()
                    if current_start is not None
                    else min_date_out.date() if pd.notnull(min_date_out) else None
                )
                default_end = (
                    current_end.date()
                    if current_end is not None
                    else max_date_out.date() if pd.notnull(max_date_out) else None
                )
                if default_start and default_end:
                    new_range = st.date_input(
                        "Seleziona periodo di riferimento per la proposta",
                        value=(default_start, default_end),
                    )
                    # Se l'utente cambia le date, aggiorna all'azione del bottone
                    if (
                        isinstance(new_range, tuple)
                        and len(new_range) == 2
                        and st.button("Aggiorna proposte")
                    ):
                        new_start = pd.to_datetime(new_range[0])
                        new_end = pd.to_datetime(new_range[1])
                        # Ricrea le raccomandazioni con i parametri salvati
                        df_recs_new = generate_recommendations(
                            st.session_state["df_raw"],
                            col_customer=st.session_state["col_customer"],
                            col_product=st.session_state["col_product"],
                            col_desc=st.session_state["col_desc"],
                            col_qty=st.session_state["col_qty"],
                            col_date=st.session_state.get("col_date"),
                            date_start=new_start,
                            date_end=new_end,
                            top_n=st.session_state.get("top_n", 0),
                            min_qty=st.session_state.get("min_qty", 0),
                            score_floor=st.session_state.get("score_floor", 0.0),
                        )
                                # removed st.experimental_rerun to avoid AttributeError

                        # aggiorna sessione
                        st.session_state["date_start"] = new_start
                        st.session_state["date_end"] = new_end
                        st.session_state["all_df"] = df_recs_new.copy()
                        df = df_recs_new
                        

        

        client_ids = sorted(df["customer_id"].unique())
        selected_client = st.selectbox("Seleziona cliente", client_ids)
        df_client = df[df["customer_id"] == selected_client].copy()

        # mappa colonne per editor
        rename_map = {
            "customer_id": "Cliente",
            "product_id": "Articolo",
            "name": "Descrizione",
            "predicted_qty": "Q.tà proposta",
            "normalized_score": "Punteggio",
            "reason": "Motivo",
        }
        display_df = df_client.rename(columns=rename_map)
        edited = st.data_editor(
            display_df, num_rows="dynamic", use_container_width=True
        )

        # ridenomina a colonne originali
        reverse_map = {v: k for k, v in rename_map.items()}
        edited = edited.rename(columns=reverse_map)

        st.subheader("Allega immagini (facoltativo)")
        uploaded_images = st.file_uploader(
            "Seleziona immagini (jpg/png)",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
        )

        st.subheader("Metodo di invio e messaggio")
        method = st.selectbox("Metodo di invio", ["Email", "WhatsApp"])
        message_text = st.text_area(
            "Testo del messaggio",
            placeholder="Scrivi qui il messaggio da inviare...",
            height=150,
        )

        if st.button("Finalizza e Invia"):
            # Verifica presenza di API key e base URL
            if api_key_input and base_url_input:
                # Converte il DataFrame editato in un elenco di prodotti per l'ordine
                items_to_order = []
                for _, row in edited.iterrows():
                    # Usa i campi originali product_id e predicted_qty
                    try:
                        prod_id = str(row["product_id"])
                        qty = int(row["predicted_qty"])
                        if qty > 0:
                            items_to_order.append({"product_id": prod_id, "quantity": qty})
                    except Exception:
                        continue
                if not items_to_order:
                    st.error("Nessun prodotto selezionato per l'ordine.")
                else:
                    # Invia ordine a PrestaShop
                    status_msg = submit_order_to_prestashop(
                        api_key_input,
                        base_url_input,
                        str(selected_client),
                        items_to_order,
                    )
                    # Mostra risultato
                    if status_msg.startswith("Ordine creato"):
                        st.success(status_msg)
                    else:
                        st.error(status_msg)
         
                    # Mostra riepilogo dell'ordine
                    st.write("Cliente:", selected_client)
                    st.write("Prodotti selezionati:")
                    st.dataframe(
                        edited, use_container_width=True
                    )
                    if uploaded_images:
                        st.write(f"Immagini allegate: {len(uploaded_images)}")
                    st.write("Metodo di invio:", method)
                    st.write("Testo del messaggio:")
                    st.write(message_text)
            else:
                st.error(
                    "Per inviare l'ordine a PrestaShop devi inserire la chiave API e l'URL del negozio nella barra laterale."
                )
    else:
        st.info(
            "Nessun dato disponibile. Carica un file nella scheda 'Import SAP' per iniziare."
        )
