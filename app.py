import io
from datetime import datetime
import pandas as pd
import streamlit as st

# Configurazione della pagina
st.set_page_config(page_title="Gestione Riordini PrestaShop", layout="wide")

# Barra laterale per la chiave API
with st.sidebar:
    st.text_input("Chiave API PrestaShop", type="password")

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
                        # aggiorna sessione
                        st.session_state["date_start"] = new_start
                        st.session_state["date_end"] = new_end
                        st.session_state["all_df"] = df_recs_new.copy()
                        df = df_recs_new
                        # forza il rerun della app per aggiornare i dati
                        st.experimental_rerun()

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
            st.success("Ordine pronto per essere inviato (simulazione).")
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
        st.info(
            "Nessun dato disponibile. Carica un file nella scheda 'Import SAP' per iniziare."
        )
