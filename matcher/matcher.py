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

    c_code = pick(["itemcode", "codice", "codice articolo", "sku", "reference", "prodotto", "articolo"])
    c_desc = pick(["description", "descrizione", "itemname", "name", "product", "prodotto", "articolo"])
    c_qty = pick(["qty", "quantita", "quantity", "qta", "qta ordinata", "pezzi"])

    out = pd.DataFrame()
    if c_code is not None:
        out["order_itemcode"] = df[c_code].astype(str).str.strip()
    if c_desc is not None:
        out["order_desc"] = df[c_desc].astype(str).str.strip()
    if c_qty is not None:
        out["order_qty"] = pd.to_numeric(df[c_qty].astype(str).str.replace(",", "."), errors="coerce").fillna(1).astype(int)
    else:
        out["order_qty"] = 1
    out["order_desc_norm"] = out.get("order_desc", "").map(_norm_txt) if "order_desc" in out else ""
    return out


def load_order_pdf(file) -> pd.DataFrame:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber non disponibile: aggiungi 'pdfplumber' a requirements.txt.")
    rows = []
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

    if not rows:
        return pd.DataFrame(columns=["order_itemcode", "order_desc", "order_desc_norm", "order_qty"])

    header = max(rows[:5], key=lambda r: sum(len(c) for c in r))
    n = len(header)
    df = pd.DataFrame([r if len(r) == n else (r + [""] * (n - len(r))) for r in rows], columns=[f"col{i}" for i in range(n)])

    df["order_itemcode"] = ""
    df["order_desc"] = ""
    df["order_qty"] = 1
    for c in df.columns:
        if c.startswith("col"):
            sample = df[c].head(50).astype(str).tolist()
            alnum = sum(1 for v in sample if re.match(r"^[A-Za-z0-9\-\._]{3,}$", v))
            numeric = sum(1 for v in sample if re.match(r"^\d+([,\.]\d+)?$", v))
            longtxt = sum(1 for v in sample if len(v) > 15)
            if alnum > 20:
                df["order_itemcode"] = df["order_itemcode"].mask(df["order_itemcode"] == "", df[c])
            if numeric > 20:
                q = pd.to_numeric(df[c].str.replace(",", ".", regex=False), errors="coerce")
                df["order_qty"] = df["order_qty"].mask(df["order_qty"] == 1, q.fillna(1).astype(int))
            if longtxt > 20:
                df["order_desc"] = df["order_desc"].mask(df["order_desc"] == "", df[c])

    df["order_desc_norm"] = df["order_desc"].map(_norm_txt)
    return df[["order_itemcode", "order_desc", "order_desc_norm", "order_qty"]]


def _build_customer_stats(df_sales: pd.DataFrame, customer_id: str | None) -> Tuple[dict, dict]:
    df = df_sales.copy()
    ren = {}
    for c in df.columns:
        cl = str(c).lower()
        if cl in ["cardcode", "cliente", "codice cliente/fornitore"]:
            ren[c] = "customer_id"
        if cl in ["itemcode", "codice articolo", "articolo", "sku", "prodotto"]:
            ren[c] = "product_id"
        if cl in ["itemname", "descrizione articolo", "descrizione", "name", "product"]:
            ren[c] = "name"
        if cl in ["quantity", "qta", "qtasped", "quantità", "qty", "pezzi"]:
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

    if "order_date" in df.columns and pd.api.types.is_datetime64_any_dtype(pd.to_datetime(df["order_date"], errors="coerce")):
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
    topk: int = 5
) -> pd.DataFrame:
    if fuzz is None:
        raise RuntimeError("rapidfuzz non disponibile: aggiungi 'rapidfuzz' a requirements.txt.")

    freq_norm, rec_norm = customer_stats
    cat = catalog_df.copy()
    ren = {}
    for c in cat.columns:
        cl = str(c).lower()
        if cl in ["itemcode", "codice articolo", "articolo", "sku", "prodotto"]:
            ren[c] = "product_id"
        if cl in ["itemname", "descrizione articolo", "descrizione", "name", "product"]:
            ren[c] = "name"
    cat = cat.rename(columns=ren)

    cat["product_id"] = cat["product_id"].astype(str)
    cat["name_norm"] = cat["name"].map(_norm_txt)

    results = []
    codes = set(cat["product_id"])

    for _, r in order_df.iterrows():
        ocode = str(r.get("order_itemcode", "")).strip()
        oname = r.get("order_desc", "")
        oname_norm = r.get("order_desc_norm", "")
        qty = int(r.get("order_qty", 1))

        if ocode and ocode in codes:
            row = cat[cat["product_id"] == ocode].iloc[0]
            results.append({
                "order_itemcode": ocode,
                "order_desc": oname,
                "order_qty": qty,
                "matched_itemcode": ocode,
                "matched_name": row["name"],
                "probability": 1.0,
                "method": "code",
                "status": "OK",
                "candidates": None
            })
            continue

        if oname_norm:
            exact = cat[cat["name_norm"] == oname_norm]
            if len(exact) > 0:
                row = exact.iloc[0]
                results.append({
                    "order_itemcode": ocode,
                    "order_desc": oname,
                    "order_qty": qty,
                    "matched_itemcode": row["product_id"],
                    "matched_name": row["name"],
                    "probability": 0.90,
                    "method": "desc_exact",
                    "status": "OK",
                    "candidates": None
                })
                continue

        if not oname_norm:
            results.append({
                "order_itemcode": ocode,
                "order_desc": oname,
                "order_qty": qty,
                "matched_itemcode": None,
                "matched_name": None,
                "probability": 0.0,
                "method": "no_name",
                "status": "NON TROVATO",
                "candidates": None
            })
            continue

        sims = []
        for _, row in cat.iterrows():
            sim = max(
                fuzz.token_set_ratio(oname_norm, row["name_norm"]),
                fuzz.token_sort_ratio(oname_norm, row["name_norm"]),
                fuzz.partial_ratio(oname_norm, row["name_norm"])
            ) / 100.0
            pid = str(row["product_id"])
            pb = 0.4 * rec_norm.get(pid, 0.0) + 0.6 * freq_norm.get(pid, 0.0)
            p = 0.65 * sim + 0.35 * pb
            sims.append((pid, row["name"], p, sim, pb))
        sims.sort(key=lambda x: x[2], reverse=True)
        pid_best, name_best, p_best, *_ = sims[0]
        status = "OK" if p_best >= accept_thresh else ("DA RIVEDERE" if p_best >= review_thresh else "NON TROVATO")
        candidates = [
            {"product_id": pid, "name": nm, "prob": round(float(p), 3)}
            for (pid, nm, p, _, _) in sims[:topk]
        ]
        results.append({
            "order_itemcode": ocode,
            "order_desc": oname,
            "order_qty": qty,
            "matched_itemcode": pid_best if p_best >= review_thresh else None,
            "matched_name": name_best if p_best >= review_thresh else None,
            "probability": round(float(p_best), 3),
            "method": "desc_fuzzy",
            "status": status,
            "candidates": json.dumps(candidates, ensure_ascii=False)
        })

    return pd.DataFrame(results)


def export_sap_excel(header: dict, lines: pd.DataFrame) -> bytes:
    with pd.ExcelWriter(io.BytesIO(), engine="openpyxl") as writer:
        pd.DataFrame([header]).to_excel(writer, sheet_name="ORDR", index=False)
        cols = ["ItemCode", "Dscription", "Quantity", "Price", "WhsCode"]
        lines = lines.copy()
        for c in cols:
            if c not in lines.columns:
                lines[c] = "" if c not in ["Quantity", "Price"] else 0
        lines[cols].to_excel(writer, sheet_name="RDR1", index=False)
        writer.book.save(writer.path)
        data = writer.path.getvalue()
    return data
