import streamlit as st
import pandas as pd
from datetime import datetime

try:
    from matcher.matcher import (
        load_order_pdf, load_order_excel,
        _build_customer_stats, match_order_to_catalog,
        export_sap_excel
    )
    _ORDER_MATCH_OK = True
except Exception:
    _ORDER_MATCH_OK = False

def main():
    st.set_page_config(page_title="PrestaShop Reorder Interface", layout="wide")
    st.title("PrestaShop Reorder Interface")

    tab_import, tab_manage, tab_order, tab_xsell = st.tabs(
        ["Import SAP", "Gestione riordini", "Import Ordine Cliente", "Cross-sell"]
    )

    with tab_import:
        st.info("Scheda Import SAP (placeholder)")

    with tab_manage:
        st.info("Scheda Gestione Riordini (placeholder)")

    # -----------------------------
    # SCHEDA: Import Ordine Cliente
    # -----------------------------
    with tab_order:
        st.subheader("Import Ordine Cliente (PDF/Excel) • Matching • Export SAP")

        if not _ORDER_MATCH_OK:
            st.warning("Per questa scheda servono le librerie: **pdfplumber** e **rapidfuzz**.")
        else:
            up_order = st.file_uploader("Carica ordine (PDF o Excel)", type=["pdf","xlsx","xls"])
            up_sales = st.file_uploader("Carica storico vendite (Excel/CSV)", type=["xlsx","xls","csv"], key="sales_hist")
            up_catalog = st.file_uploader("Carica catalogo prodotti", type=["xlsx","xls","csv"], key="catalog")
            sel_customer = st.text_input("CardCode Cliente", value="")

            order_df = None
            if up_order is not None:
                if up_order.name.lower().endswith(".pdf"):
                    order_df = load_order_pdf(up_order)
                else:
                    order_df = load_order_excel(up_order)

            sales_df = None
            if up_sales is not None:
                sales_df = pd.read_excel(up_sales) if up_sales.name.endswith(".xls") else pd.read_csv(up_sales)

            catalog_df = None
            if up_catalog is not None:
                catalog_df = pd.read_excel(up_catalog) if up_catalog.name.endswith(".xls") else pd.read_csv(up_catalog)

            if order_df is not None and catalog_df is not None:
                st.caption("Anteprima ordine")
                st.dataframe(order_df.head(30), use_container_width=True)
                stats = _build_customer_stats(sales_df if sales_df is not None else pd.DataFrame(), sel_customer or None)
                matched = match_order_to_catalog(order_df, catalog_df, stats)
                st.dataframe(matched, use_container_width=True)
            else:
                st.info("Carica ordine e catalogo per procedere al matching.")

    with tab_xsell:
        st.info("Scheda Cross-sell (placeholder)")

if __name__ == "__main__":
    main()
