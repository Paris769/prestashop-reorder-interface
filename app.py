import traceback
from io import BytesIO
from typing import Optional

import streamlit as st
import pandas as pd

# -------------------------------
# Import intelligente del matcher
# -------------------------------
MATCHER_OK = True
IMPORT_ERROR: Optional[str] = None

try:
    from matcher.matcher import (
        load_order_pdf, load_order_excel,
        _build_customer_stats, match_order_to_catalog,
        export_sap_excel
    )
except Exception as e:
    MATCHER_OK = False
    IMPORT_ERROR = f"{e.__class__.__name__}: {e}\n" + traceback.format_exc()

# Capabilities opzionali
try:
    import pdfplumber  # noqa
    HAS_PDF = True
except Exception:
    HAS_PDF = False

try:
    from rapidfuzz import fuzz  # noqa
    HAS_FUZZ = True
except Exception:
    HAS_FUZZ = False

st.set_page_config(page_title="PrestaShop Reorder Interface", layout="wide")
st.title("PrestaShop Reorder Interface")

tab_import, tab_manage, tab_order, tab_xsell = st.tabs(
    ["Import SAP", "Gestione riordini", "Import Ordine Cliente", "Cross-sell"]
)

with tab_import:
    st.info("Scheda Import SAP (placeholder)")

with tab_manage:
    st.info("Scheda Gestione Riordini (placeholder)")

# --------------------------------------
# SCHEDA: Import Ordine Cliente (Attiva)
# --------------------------------------
with tab_order:
    st.subheader("Import Ordine Cliente (PDF/Excel) • Matching • Export SAP")

    # Diagnostica se il matcher non è importabile
    if not MATCHER_OK:
        with st.expander("Diagnostica import matcher (clicca per dettagli)", expanded=True):
            st.warning("Il modulo di matching non è stato importato. "
                       "Procedo con **funzionalità ridotte** (Excel→Excel).")
            st.code(IMPORT_ERROR or "Nessun dettaglio disponibile", language="text")

    # Stato dipendenze
    colA, colB, colC = st.columns(3)
    colA.metric("Supporto PDF (pdfplumber)", "OK" if HAS_PDF else "NON DISPONIBILE")
    colB.metric("Fuzzy match (rapidfuzz)", "OK" if HAS_FUZZ else "NON DISPONIBILE")
    colC.metric("Modulo matcher", "OK" if MATCHER_OK else "IMPORT FALLITO")

    # Uploaders SEMPRE disponibili
    up_order = st.file_uploader(
        "Carica ordine (PDF o Excel)",
        type=(["pdf"] if HAS_PDF else []) + ["xlsx", "xls", "csv"],
        help="Se il supporto PDF non è disponibile, usa Excel/CSV."
    )
    up_sales = st.file_uploader("Carica storico vendite (Excel/CSV)", type=["xlsx", "xls", "csv"], key="sales_hist")
    up_catalog = st.file_uploader("Carica catalogo prodotti (Excel/CSV)", type=["xlsx", "xls", "csv"], key="catalog")
    sel_customer = st.text_input("CardCode Cliente (opzionale)", value="")

    # Helpers lettura
    def read_table(file):
        name = file.name.lower()
        if name.endswith(".csv"):
            return pd.read_csv(file)
        return pd.read_excel(file)

    # Caricamento dati
    order_df = None
    if up_order is not None and MATCHER_OK:
        if up_order.name.lower().endswith(".pdf") and HAS_PDF:
            order_df = load_order_pdf(up_order)
        else:
            if up_order.name.lower().endswith((".xlsx", ".xls", ".csv")):
                order_df = load_order_excel(up_order)
            else:
                st.error("Formato non supportato senza pdfplumber. Usa Excel/CSV.")
    elif up_order is not None and not MATCHER_OK:
        # Fallback duro: prova a leggere Excel/CSV anche senza matcher
        if up_order.name.lower().endswith((".xlsx", ".xls", ".csv")):
            try:
                order_df = read_table(up_order)
                # Normalizzazione minima
                lc = {c: c.lower() for c in order_df.columns}
                order_df.rename(columns=lc, inplace=True)
            except Exception as e:
                st.error(f"Impossibile leggere l'ordine: {e}")

    sales_df = None
    if up_sales is not None:
        try:
            sales_df = read_table(up_sales)
        except Exception as e:
            st.error(f"Storico non leggibile: {e}")

    catalog_df = None
    if up_catalog is not None:
        try:
            catalog_df = read_table(up_catalog)
        except Exception as e:
            st.error(f"Catalogo non leggibile: {e}")

    # Matching
    if order_df is not None and catalog_df is not None and MATCHER_OK:
        st.caption("Anteprima ordine")
        st.dataframe(order_df.head(30), use_container_width=True)

        stats = _build_customer_stats(sales_df if sales_df is not None else pd.DataFrame(), sel_customer or None)

        try:
            matched = match_order_to_catalog(order_df, catalog_df, stats)
        except Exception as e:
            st.error(f"Errore nel matching: {e}")
            matched = None

        if matched is not None:
            st.success("Matching completato.")
            st.dataframe(matched, use_container_width=True)

            # Export SAP
            with st.form("export_form"):
                st.caption("Parametri export SAP (minimali)")
                header = {
                    "DocDate": pd.Timestamp.utcnow().strftime("%Y-%m-%d"),
                    "CardCode": sel_customer or "",
                    "Comments": "Ordine generato da PrestaShop Reorder Interface",
                }
                submitted = st.form_submit_button("Esporta Excel ORDR/RDR1")
                if submitted:
                    try:
                        data = export_sap_excel(header, matched)
                        st.download_button(
                            "Scarica file Excel",
                            data=BytesIO(data),
                            file_name="SAP_ORDR_RDR1.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    except Exception as e:
                        st.error(f"Errore export: {e}")
    elif order_df is None:
        st.info("Carica **ordine** (PDF se disponibile o Excel/CSV) e **catalogo** per procedere.")

with tab_xsell:
    st.info("Scheda Cross-sell (placeholder)")
