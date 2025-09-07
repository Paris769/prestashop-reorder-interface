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
    df[col_product]  = _safe_str(df[col_product])
    df[col_desc]     = _safe_str(df[col_desc])
    df[col_qty] = pd.to_numeric(df[col_qty], errors="coerce").fillna(0)
    if col_date:
        df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
    if col_date and date_start is not None and date_end is not None:
        df = df[(df[col_date] >= date_start) & (df[col_date] <= date_end)]

    g = (
        df.groupby([col_customer, col_product, col_desc])[col_qty]
          .sum()
          .reset_index()
          .rename(columns={
              col_customer: "customer_id",
              col_product:  "product_id",
              col_desc:     "name",
              col_qty:      "predicted_qty",
          })
    )
    # Normalizza per cliente
    g["normalized_score"] = (
        g.groupby("customer_id")["predicted_qty"]
         .transform(lambda s: (s / s.max()).fillna(0))
         .round(3)
    )
    g["reason"] = "Storico vendite"
    g["predicted_qty"] = g["predicted_qty"].astype(int)
    g = g.sort_values(["customer_id","normalized_score","predicted_qty"], ascending=[True,False,False])
    return g[["customer_id","product_id","name","predicted_qty","normalized_score","reason"]]

# Inizializza session_state se necessario
if "all_df" not in st.session_state:
    st.session_state["all_df"] = None

# Tabs per l'applicazione
tab_import, tab_manage = st.tabs(["Import SAP", "Gestione riordini"])

with tab_import:
    st.subheader("Import vendite SAP (Excel/CSV)")
    uploaded_file = st.file_uploader("Carica il file vendite (xlsx/xls/csv)", type=["xlsx","xls","csv"])
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

            col_customer = st.selectbox("Colonna cliente", cols, index=preselect(["Codice cliente/fornitore","Cliente","CodCliente"]))
            col_product  = st.selectbox("Colonna articolo", cols, index=preselect(["Codice articolo","Articolo","CodArticolo"]))
            col_desc     = st.selectbox("Colonna descrizione", cols, index=preselect(["Descrizione articolo","Descrizione","DescArticolo"]))
            col_qty      = st.selectbox("Colonna quantità (venduto/spedito)", cols, index=preselect(["QtaSped","Qta","Quantità","QtaVenduta"]))

            # Colonna data opzionale
            col_date_options = ["(nessuna)"] + cols
            col_date_sel = st.selectbox("Colonna data (opzionale)", col_date_options, index=0)

            date_start = None
            date_end   = None
            if col_date_sel != "(nessuna)":
                dates_series = pd.to_datetime(df_raw[col_date_sel], errors="coerce")
                min_date = dates_series.min()
                max_date = dates_series.max()
                if pd.notnull(min_date) and pd.notnull(max_date):
                    date_range = st.date_input("Intervallo date", value=(min_date.date(), max_date.date()))
                    if isinstance(date_range, tuple) and len(date_range) == 2:
                        date_start = pd.to_datetime(date_range[0])
                        date_end   = pd.to_datetime(date_range[1])

            with st.expander("Opzioni di generazione"):
                top_n = st.number_input("Top-N prodotti per cliente (0 = nessun limite)", 0, 1000, 0, step=1)
                min_qty = st.number_input("Quantità minima proposta", 0, 99999, 0, step=1)
                score_floor = st.slider("Soglia minima di punteggio normalizzato", 0.0, 1.0, 0.0, 0.01)

            if st.button("Genera proposte da Excel"):
                df_recs = build_recommendations_from_sales(
                    df_raw,
                    col_customer=col_customer,
                    col_product=col_product,
                    col_desc=col_desc,
                    col_qty=col_qty,
                    col_date=None if col_date_sel == "(nessuna)" else col_date_sel,
                    date_start=date_start,
                    date_end=date_end,
                )
                # applica filtri
                if min_qty > 0:
                    df_recs = df_recs[df_recs["predicted_qty"] >= min_qty]
                if score_floor > 0:
                    df_recs = df_recs[df_recs["normalized_score"] >= score_floor]
                if top_n > 0:
                    df_recs = (
                        df_recs
                        .sort_values(["customer_id","normalized_score","predicted_qty"], ascending=[True,False,False])
                        .groupby("customer_id")
                        .head(top_n)
                        .reset_index(drop=True)
                    )
                st.session_state["all_df"] = df_recs.copy()
                st.success(f"Proposte generate: {len(df_recs):,}")
                st.dataframe(df_recs.head(50), use_container_width=True)

                # Download
                csv_bytes = df_recs.to_csv(index=False).encode("utf-8")
                json_bytes = df_recs.to_json(orient="records", force_ascii=False).encode("utf-8")
                st.download_button("Scarica proposte (CSV)", data=csv_bytes, file_name="proposte_riordino.csv", mime="text/csv")
                st.download_button("Scarica proposte (JSON)", data=json_bytes, file_name="proposte_riordino.json", mime="application/json")
        except Exception as e:
            st.error(f"Errore durante l'elaborazione del file: {e}")

with tab_manage:
    st.subheader("Gestione riordini")
    df = st.session_state.get("all_df")
    if df is None or df is False:
        # fallback a dati demo
        try:
            df = pd.read_json("recommendations_demo.json")
            st.info("Nessun file importato. Stai visualizzando dati di esempio.")
        except Exception:
            df = pd.DataFrame()

    if df is not None and not df.empty:
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
        edited = st.data_editor(display_df, num_rows="dynamic", use_container_width=True)

        # ridenomina a colonne originali
        reverse_map = {v: k for k, v in rename_map.items()}
        edited = edited.rename(columns=reverse_map)

        st.subheader("Allega immagini (facoltativo)")
        uploaded_images = st.file_uploader("Seleziona immagini (jpg/png)", type=["jpg","jpeg","png"], accept_multiple_files=True)

        st.subheader("Metodo di invio e messaggio")
        method = st.selectbox("Metodo di invio", ["Email","WhatsApp"])
        message_text = st.text_area("Testo del messaggio", placeholder="Scrivi qui il messaggio da inviare...", height=150)

        if st.button("Finalizza e Invia"):
            st.success("Ordine pronto per essere inviato (simulazione).")
            st.write("Cliente:", selected_client)
            st.write("Prodotti selezionati:")
            st.dataframe(edited, use_container_width=True)
            if uploaded_images:
                st.write(f"Immagini allegate: {len(uploaded_images)}")
            st.write("Metodo di invio:", method)
            st.write("Testo del messaggio:")
            st.write(message_text)
    else:
        st.info("Nessun dato disponibile. Carica un file nella scheda 'Import SAP' per iniziare.")
