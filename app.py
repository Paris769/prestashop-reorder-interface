import io
import pandas as pd
import streamlit as st

# Configurazione della pagina
st.set_page_config(page_title="Gestione Riordini PrestaShop", layout="wide")

# Funzioni di utilità per l'importazione di Excel/CSV
def _load_excel_or_csv(uploaded_file: io.BytesIO) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file, sep=None, engine="python")
    return pd.read_excel(uploaded_file)

def _safe_str(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()

def build_recommendations_from_sales(df_raw: pd.DataFrame, col_customer: str, col_product: str, col_desc: str, col_qty: str) -> pd.DataFrame:
    df = df_raw.copy()
    df[col_customer] = _safe_str(df[col_customer])
    df[col_product] = _safe_str(df[col_product])
    df[col_desc] = _safe_str(df[col_desc])
    df[col_qty] = pd.to_numeric(df[col_qty], errors="coerce").fillna(0)
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
    g["normalized_score"] = (
        g.groupby("customer_id")["predicted_qty"].transform(lambda s: (s / s.max()).fillna(0)).round(3)
    )
    g["reason"] = "Storico vendite"
    g = g.sort_values(["customer_id", "normalized_score", "predicted_qty"], ascending=[True, False, False])
    g["predicted_qty"] = g["predicted_qty"].astype(int)
    return g[["customer_id", "product_id", "name", "predicted_qty", "normalized_score", "reason"]]

def load_data_json(path: str) -> pd.DataFrame:
    return pd.read_json(path)

# Inizializza lo stato di sessione per le proposte
if "all_df" not in st.session_state:
    try:
        st.session_state["all_df"] = load_data_json("recommendations_demo.json")
    except Exception:
        st.session_state["all_df"] = pd.DataFrame(
            columns=["customer_id", "product_id", "name", "predicted_qty", "normalized_score", "reason"]
        )

# UI principale con due tab
tabs = st.tabs(["Import SAP", "Gestione riordini"])

# Tab 0: Import SAP
with tabs[0]:
    st.header("Import vendite SAP (Excel/CSV)")
    uploaded = st.file_uploader(
        "Carica il file vendite (xlsx/xls/csv)", type=["xlsx", "xls", "csv"]
    )

    if uploaded is not None:
        try:
            df_raw = _load_excel_or_csv(uploaded)
            st.caption("Anteprima dati caricati")
            st.dataframe(df_raw.head(10), use_container_width=True)

            cols = df_raw.columns.tolist()

            def preselect(name_candidates):
                for c in name_candidates:
                    if c in cols:
                        return cols.index(c)
                return 0

            col_customer = st.selectbox(
                "Colonna cliente",
                cols,
                index=preselect([
                    "Codice cliente/fornitore",
                    "Cliente",
                    "CodCliente",
                ]),
            )
            col_product = st.selectbox(
                "Colonna articolo",
                cols,
                index=preselect([
                    "Codice articolo",
                    "Articolo",
                    "CodArticolo",
                ]),
            )
            col_desc = st.selectbox(
                "Colonna descrizione",
                cols,
                index=preselect([
                    "Descrizione articolo",
                    "Descrizione",
                    "DescArticolo",
                ]),
            )
            col_qty = st.selectbox(
                "Colonna quantità (venduto/spedito)",
                cols,
                index=preselect([
                    "QtaSped",
                    "Qta",
                    "Quantità",
                    "QtaVenduta",
                ]),
            )

            with st.expander("Opzioni di generazione"):
                topn_per_client = st.number_input(
                    "Top-N prodotti per cliente (0 = nessun limite)", 0, 100, 0, step=1
                )
                min_qty = st.number_input(
                    "Quantità minima proposta", 0, 99999, 0, step=1
                )
                score_floor = st.slider(
                    "Soglia minima di punteggio normalizzato", 0.0, 1.0, 0.0, 0.01
                )

            if st.button("Genera proposte da file"):
                all_df = build_recommendations_from_sales(
                    df_raw, col_customer, col_product, col_desc, col_qty
                )
                if min_qty > 0:
                    all_df = all_df[all_df["predicted_qty"] >= min_qty]
                if score_floor > 0:
                    all_df = all_df[all_df["normalized_score"] >= score_floor]
                if topn_per_client > 0:
                    all_df = (
                        all_df.sort_values(
                            ["customer_id", "normalized_score", "predicted_qty"],
                            ascending=[True, False, False],
                        )
                        .groupby("customer_id")
                        .head(topn_per_client)
                        .reset_index(drop=True)
                    )
                st.session_state["all_df"] = all_df.copy()
                st.success(f"Proposte generate: {len(all_df):,}")
                st.dataframe(all_df.head(50), use_container_width=True)

                csv_bytes = all_df.to_csv(index=False).encode("utf-8")
                json_bytes = all_df.to_json(
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

# Tab 1: Gestione riordini
with tabs[1]:
    st.header("Gestione riordini")
    all_df = st.session_state.get("all_df", pd.DataFrame())

    if all_df.empty:
        st.warning(
            "Nessuna proposta disponibile. Importa un file oppure utilizza il file demo."
        )
    else:
        if "predicted_qty" in all_df.columns:
            all_df["predicted_qty"] = all_df["predicted_qty"].astype(int)

        client_ids = sorted(all_df["customer_id"].unique())
        cliente = st.selectbox("Seleziona cliente", client_ids)

        df_client = all_df[all_df["customer_id"] == cliente].copy()
        rename_map = {
            "product_id": "ID prodotto",
            "name": "Prodotto",
            "predicted_qty": "Quantità suggerita",
            "normalized_score": "Punteggio",
            "reason": "Motivazione",
        }
        df_display = df_client.rename(columns=rename_map)[list(rename_map.values())]
        edited = st.data_editor(
            df_display, num_rows="dynamic", use_container_width=True
        )

        reverse_map = {v: k for k, v in rename_map.items()}
        updated_client_df = edited.rename(columns=reverse_map)

        for idx, row in updated_client_df.iterrows():
            mask = (all_df["customer_id"] == cliente) & (
                all_df["product_id"] == row["product_id"]
            )
            all_df.loc[mask, "predicted_qty"] = int(row["predicted_qty"])

        st.subheader("Opzioni messaggio")
        invio_metodo = st.radio(
            "Metodo di invio", ["Email", "WhatsApp"], horizontal=True
        )
        testo_msg = st.text_area(
            "Testo del messaggio",
            "Gentile cliente, ecco la nostra proposta di riordino...",
        )

        immagini = st.file_uploader(
            "Allega immagini (facoltative)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )

        prestashop_api_key = st.sidebar.text_input(
            "Chiave API PrestaShop", type="password"
        )

        if st.button("Invia"):
            st.success(
                "Ordine pronto per l'invio (funzionalità non attiva in questa demo)."
            )
            # Qui integreresti le API di email/WhatsApp e l'API di PrestaShop
