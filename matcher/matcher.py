from __future__ import annotations
import io, re, string, json
from typing import Tuple
import pandas as pd

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None


def _norm_txt(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.translate(str.maketrans("", "", string.punctuation))
    s = re.sub(r"\b(cm|mm|ml|lt|pz|conf|cf|kg|gr|ø|diam|x)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_order_excel(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    cols_lc = {c: c.lower() for c in df.columns}
    df = df.rename(columns=cols_lc)

    def pick(cands):
        for c in cands:
            for col in df.columns:
                if col.lower() == c:
                    return col
        return None

    c_code = pick([
        "itemcode",
        "codice",
        "codice articolo",
        "sku",
        "reference",
        "prodotto",
        "articolo",
    ])
    c_desc = pick([
        "description",
        "descrizione",
        "itemname",
        "name",
        "product",
        "prodotto",
        "articolo",
    ])
    c_qty = pick([
        "qty",
        "quantita",
        "quantity",
        "qta",
        "qta ordinata",
        "pezzi",
    ])

    out = pd.DataFrame()
    if c_code is not None:
        out["order_itemcode"] = df[c_code].astype(str).str.strip()
    if c_desc is not None:
        out["order_desc"] = df[c_desc].astype(str).str.strip()
    if c_qty is not None:
        out["order_qty"] = pd.to_numeric(
            df[c_qty].astype(str).str.replace(",", "."), errors="coerce"
        ).fillna(1).astype(int)
    else:
        out["order_qty"] = 1
    if "order_desc" in out:
        out["order_desc_norm"] = out["order_desc"].map(_norm_txt)
    else:
        out["order_desc_norm"] = ""
    return out


def load_order_pdf(file) -> pd.DataFrame:
    """
    Load an order from a PDF. First attempts to extract tables with pdfplumber.
    If no tables are found, fall back to parsing uppercase text lines to
    approximate item descriptions and quantities.
    """
    if pdfplumber is None:
        raise RuntimeError("pdfplumber non disponibile: aggiungi 'pdfplumber' a requirements.txt.")
    rows: list[list[str]] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            for t in tables or []:
                for r in t:
                    if not r or all((x is None or str(x).strip() == "" for x in r)):
                        continue
                    cells = [str(x).strip() if x is not None else "" for x in r]
                    rows.append(cells)

    # if the first extracted row contains no meaningful text (all cells blank),
    # treat as if no table was found to trigger the fallback parsing logic below.
    if rows:
        first_row = rows[0]
        # check if every cell in the first row is None or empty/whitespace
        if all(not (cell and str(cell).strip()) for cell in first_row):
            rows = []

    # standard table-based extraction
    if rows:
        header = max(rows[:5], key=lambda r: sum(len(c) for c in r))
        n = len(header)
        # build a DataFrame from the extracted rows
        df = pd.DataFrame(
            [r if len(r) == n else (r + [""] * (n - len(r))) for r in rows],
            columns=[f"col{i}" for i in range(n)],
        )
        # initialise output columns
        df["order_itemcode"] = ""
        df["order_desc"] = ""
        df["order_qty"] = 1
        # heuristics to pick which column contains codes, quantities and descriptions
        for c in df.columns:
            if c.startswith("col"):
                sample = df[c].head(50).astype(str).tolist()
                alnum = sum(1 for v in sample if re.match(r"^[A-Za-z0-9\-\._]{3,}$", v))
                numeric = sum(
                    1 for v in sample if re.match(r"^\d+([,\.]\d+)?$", v)
                )
                longtxt = sum(1 for v in sample if len(v) > 15)
                # if many alphanumeric codes, assume this column contains item codes
                if alnum > 20:
                    df["order_itemcode"] = df["order_itemcode"].mask(
                        df["order_itemcode"] == "", df[c]
                    )
                # if many numeric values, assume quantities
                if numeric > 20:
                    q = pd.to_numeric(
                        df[c].str.replace(",", ".", regex=False), errors="coerce"
                    )
                    df["order_qty"] = df["order_qty"].mask(
                        df["order_qty"] == 1, q.fillna(1).astype(int)
                    )
                # if many long text entries, assume descriptions
                if longtxt > 20:
                    df["order_desc"] = df["order_desc"].mask(
                        df["order_desc"] == "", df[c]
                    )
        df["order_desc_norm"] = df["order_desc"].map(_norm_txt)
        # if after table parsing the itemcode and description columns are still blank,
        # treat as if no valid table was found and trigger text-based fallback
        if (
            df["order_itemcode"].astype(str).str.strip().eq("").all()
            and df["order_desc"].astype(str).str.strip().eq("").all()
        ):
            rows = []
        else:
            return df[["order_itemcode", "order_desc", "order_desc_norm", "order_qty"]]

    # fallback: use text extraction to approximate items
        # Begin improved fallback logic: parse uppercase item descriptions with quantities
        # If the initial table-based parsing did not yield any valid items, we parse
        # the PDF as plain text. Many vendor PDFs list items in uppercase lines
        # followed by a quantity line. We activate scanning only after an
        # item-table header that contains both 'Item' and 'Qty'. Scanning stops
        # when encountering net or grand total lines or a new delivery date. We
        # accumulate consecutive uppercase lines as a single description and
        # extract the quantity from the next numeric line. This ensures the
        # number of returned rows matches the number of product lines in the
        # order.
        improved_items: list[dict[str, object]] = []
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = [ln.strip() for ln in text.split("\n")]
                in_table = False
                current_desc: list[str] = []
                for idx, line in enumerate(lines):
                    # start scanning once both 'Item' and 'Qty' appear in the same line
                    if not in_table:
                        if (("Item" in line) or ("ITEM" in line)) and (("Qty" in line) or ("QTY" in line)):
                            in_table = True
                        continue
                    # stop scanning at totals or new section headers
                    if any(term in line for term in ["Net Total", "Grand", "Grand Total", "Net", "Delivery Date"]):
                        if current_desc:
                            desc = " ".join(current_desc).strip()
                            improved_items.append({"order_itemcode": "", "order_desc": desc, "order_qty": 1})
                            current_desc = []
                        break
                    # uppercase lines with letters are part of a description (exclude HSN lines)
                    if (
                        len(line) > 3
                        and any(ch.isalpha() for ch in line)
                        and line.upper() == line
                        and not line.startswith("HSN")
                    ):
                        current_desc.append(line)
                        continue
                    # if we have accumulated description lines and encounter a line with numeric quantity
                    if current_desc:
                        m = re.search(r"(\d+[\.,]\d+)|(\d+)", line)
                        if m:
                            # determine quantity from the first number in the line
                            try:
                                q_val = float(m.group().replace(",", "."))
                                qty = int(round(q_val)) if q_val > 0 else 1
                            except Exception:
                                qty = 1
                            # attempt to extract a product code: look for long numeric sequences (>=5 digits)
                            code_candidates = re.findall(r"\d{5,}", line)
                            code = code_candidates[-1] if code_candidates else ""
                            desc = " ".join(current_desc).strip()
                            improved_items.append({"order_itemcode": code, "order_desc": desc, "order_qty": qty})
                            current_desc = []
                        else:
                            # continue accumulating uppercase fragments if no quantity yet
                            if (
                                len(line) > 0
                                and any(ch.isalpha() for ch in line)
                                and line.upper() == line
                                and not line.startswith("HSN")
                            ):
                                current_desc.append(line)
                # flush leftover description at end of page
                if current_desc:
                    desc = " ".join(current_desc).strip()
                    # no quantity line encountered, so default qty = 1 and no code
                    improved_items.append({"order_itemcode": "", "order_desc": desc, "order_qty": 1})
                    current_desc = []
        if improved_items:
            fallback_df = pd.DataFrame(improved_items)
            fallback_df["order_desc_norm"] = fallback_df["order_desc"].map(_norm_txt)
            return fallback_df[["order_itemcode", "order_desc", "order_desc_norm", "order_qty"]]
        # End improved fallback logic
    items: list[dict[str, object]] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.split("\n")]
            for i, line in enumerate(lines):
                # line candidate: uppercase, contains letters, not too short, not starting with HSN
                if (
                    len(line) > 3
                    and any(ch.isalpha() for ch in line)
                    and line.upper() == line
                    and not line.startswith("HSN")
                ):
                    qty = 1
                    # search nearby lines for numeric quantity (preceding or following)
                    for j in range(max(0, i - 2), min(len(lines), i + 3)):
                        candidate = lines[j]
                        m = re.search(r"(\d+[\.,]\d+)|(\d+)", candidate)
                        if m:
                            try:
                                q = float(m.group().replace(",", "."))
                                qty = int(round(q))
                                break
                            except Exception:
                                pass
                    items.append(
                        {
                            "order_itemcode": "",
                            "order_desc": line,
                            "order_qty": qty,
                        }
                    )
    df = pd.DataFrame(items)
    if not df.empty:
        df["order_desc_norm"] = df["order_desc"].map(_norm_txt)
        return df[["order_itemcode", "order_desc", "order_desc_norm", "order_qty"]]
    # still nothing: return empty structured df
    return pd.DataFrame(
        columns=["order_itemcode", "order_desc", "order_desc_norm", "order_qty"]
    )


def _build_customer_stats(
    df_sales: pd.DataFrame, customer_id: str | None
) -> Tuple[dict, dict]:
    df = df_sales.copy()
    ren: dict[str, str] = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ["cardcode", "cliente", "codice cliente/fornitore"]:
            ren[c] = "customer_id"
        if cl in ["itemcode", "codice articolo", "articolo", "sku", "prodotto"]:
            ren[c] = "product_id"
        if cl in ["itemname", "descrizione articolo", "descrizione", "name", "product"]:
            ren[c] = "name"
        if cl in [
            "quantity",
            "qta",
            "qtasped",
            "quantità",
            "qty",
            "pezzi",
        ]:
            ren[c] = "qty"
        if cl in ["docdate", "data", "date"]:
            ren[c] = "order_date"
        if cl in ["ddt", "docnum", "numero ddt", "order_id"]:
            ren[c] = "order_id"
    df = df.rename(columns=ren)
    if customer_id:
        df = df[df["customer_id"].astype(str) == str(customer_id)]
    if df.empty:
        return {}, {}
    freq = df.groupby("product_id")["qty"].sum()
    freq_norm = ((freq - freq.min()) / (freq.max() - freq.min() + 1e-9)).to_dict()
    if "order_date" in df.columns and pd.api.types.is_datetime64_any_dtype(
        pd.to_datetime(df["order_date"], errors="coerce")
    ):
        df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
        last = df.groupby("product_id")["order_date"].max()
        span = (df["order_date"].max() - df["order_date"].min()).days + 1e-9
        rec = 1.0 - ((df["order_date"].max() - last).dt.days / span)
        rec = rec.clip(0, 1).to_dict()
    else:
        rec = {pid: 0.5 for pid in freq.index}
    return freq_norm, rec


def match_order_to_catalog(
    order_df: pd.DataFrame,
    catalog_df: pd.DataFrame,
    customer_stats: Tuple[dict, dict],
    accept_thresh: float = 0.70,
    review_thresh: float = 0.50,
    topk: int = 5,
) -> pd.DataFrame:
    """
    Match each order line to the catalog based on product_id (exact),
    normalized name (exact), or fuzzy similarity combined with purchase history.
    """
    if fuzz is None:
        raise RuntimeError(
            "rapidfuzz non disponibile: aggiungi 'rapidfuzz' a requirements.txt."
        )
    freq_norm, rec_norm = customer_stats
    cat = catalog_df.copy()
    ren: dict[str, str] = {}
    for c in cat.columns:
        cl = str(c).lower()
        if cl in ["itemcode", "codice articolo", "articolo", "sku", "prodotto"]:
            ren[c] = "product_id"
        if cl in ["itemname", "descrizione articolo", "descrizione", "name", "product"]:
            ren[c] = "name"
    cat = cat.rename(columns=ren)
    cat["product_id"] = cat["product_id"].astype(str)
    cat["name_norm"] = cat["name"].map(_norm_txt)
    results: list[dict[str, object]] = []
    codes = set(cat["product_id"])
    for _, r in order_df.iterrows():
        ocode = str(r.get("order_itemcode", "")).strip()
        oname = r.get("order_desc", "")
        oname_norm = r.get("order_desc_norm", "")
        qty = int(r.get("order_qty", 1))
        # exact match on product code
        if ocode and ocode in codes:
            row = cat[cat["product_id"] == ocode].iloc[0]
            results.append(
                {
                    "order_itemcode": ocode,
                    "order_desc": oname,
                    "order_qty": qty,
                    "matched_itemcode": ocode,
                    "matched_name": row["name"],
                    "probability": 1.0,
                    "method": "code",
                    "status": "OK",
                    "candidates": None,
                }
            )
            continue
        # exact match on normalized description
        if oname_norm:
            exact = cat[cat["name_norm"] == oname_norm]
            if len(exact) > 0:
                row = exact.iloc[0]
                results.append(
                    {
                        "order_itemcode": ocode,
                        "order_desc": oname,
                        "order_qty": qty,
                        "matched_itemcode": row["product_id"],
                        "matched_name": row["name"],
                        "probability": 0.90,
                        "method": "desc_exact",
                        "status": "OK",
                        "candidates": None,
                    }
                )
                continue
        # no description to match
        if not oname_norm:
            results.append(
                {
                    "order_itemcode": ocode,
                    "order_desc": oname,
                    "order_qty": qty,
                    "matched_itemcode": None,
                    "matched_name": None,
                    "probability": 0.0,
                    "method": "no_name",
                    "status": "NON TROVATO",
                    "candidates": None,
                }
            )
            continue
        # fuzzy match
        sims: list[tuple[str, str, float, float, float]] = []
        for _, row in cat.iterrows():
            sim = max(
                fuzz.token_set_ratio(oname_norm, row["name_norm"]),
                fuzz.token_sort_ratio(oname_norm, row["name_norm"]),
                fuzz.partial_ratio(oname_norm, row["name_norm"]),
            ) / 100.0
            pid = str(row["product_id"])
            # combine recency/frequency stats into a purchase bias
            pb = 0.4 * rec_norm.get(pid, 0.0) + 0.6 * freq_norm.get(pid, 0.0)
            # weight fuzzy similarity lower and purchase history higher to prioritise frequently bought items
            p = 0.35 * sim + 0.65 * pb
            sims.append((pid, row["name"], p, sim, pb))
        sims.sort(key=lambda x: x[2], reverse=True)
        pid_best, name_best, p_best, *_ = sims[0]
        status = (
            "OK"
            if p_best >= accept_thresh
            else ("DA RIVEDERE" if p_best >= review_thresh else "NON TROVATO")
        )
        candidates = [
            {"product_id": pid, "name": nm, "prob": round(float(p), 3)}
            for (pid, nm, p, _, _) in sims[:topk]
        ]
        results.append(
            {
                "order_itemcode": ocode,
                "order_desc": oname,
                "order_qty": qty,
                "matched_itemcode": pid_best if p_best >= review_thresh else None,
                "matched_name": name_best if p_best >= review_thresh else None,
                "probability": round(float(p_best), 3),
                "method": "desc_fuzzy",
                "status": status,
                "candidates": json.dumps(candidates, ensure_ascii=False),
            }
        )
    return pd.DataFrame(results)

# -----------------------------------------------------------------------------
# SAP export
# -----------------------------------------------------------------------------
def export_sap_excel(header: dict, df: pd.DataFrame) -> bytes:
    """Export matched order to SAP Excel with ORDR and RDR1 sheets.

    Parameters
    ----------
    header : dict
        Dictionary with order header fields like DocDate, CardCode, Comments.
    df : pandas.DataFrame
        Matched order lines. Should contain columns for item code and quantity.

    Returns
    -------
    bytes
        The bytes of the Excel file with two sheets: ORDR (header) and RDR1 (lines).
    """
    # Create header DataFrame
    ordr_df = pd.DataFrame([header])
    # Determine columns for item code and quantity
    item_col = None
    qty_col = None
    for c in ['matched_itemcode', 'order_itemcode', 'match_itemcode', 'itemcode', 'item_code', 'code']:
        if c in df.columns:
            item_col = c
            break
    for c in ['order_qty', 'qty', 'quantity', 'qta']:
        if c in df.columns:
            qty_col = c
            break
    # Build RDR1 DataFrame
    if item_col is not None and qty_col is not None:
        rdr1_df = df[[item_col, qty_col]].copy()
        rdr1_df.columns = ['ItemCode', 'Quantity']
    else:
        # Fallback: use entire dataframe if structure unknown
        rdr1_df = df.copy()
    # Write Excel to bytes buffer
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        ordr_df.to_excel(writer, sheet_name='ORDR', index=False)
        rdr1_df.to_excel(writer, sheet_name='RDR1', index=False)
    return buf.getvalue()