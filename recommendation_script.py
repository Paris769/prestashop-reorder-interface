"""
Script per generare raccomandazioni di riordino e cross-sell a partire da file Excel esportati da SAP/PrestaShop.

Utilizzo:
    python recommendation_script.py clienti.xlsx prodotti.xlsx ordini.xlsx righe_ordini.xlsx output.csv

I file Excel devono avere le seguenti colonne (senza header extra):
    - clienti.xlsx: customer_id, email, phone
    - prodotti.xlsx: product_id, name, price
    - ordini.xlsx: order_id, customer_id, date (formato AAAA-MM-GG)
    - righe_ordini.xlsx: order_id, product_id, quantity, price

Il programma calcola:
    • Un punteggio di riordino per ciascuna combinazione cliente-prodotto basato sulla ricorrenza degli acquisti e il tempo trascorso dall'ultimo acquisto.
    • Associazioni tra prodotti acquistati insieme per suggerimenti di cross-sell.
    • Una classifica finale di prodotti raccomandati per ciascun cliente con punteggi normalizzati e motivazioni.

Il risultato viene salvato in formato CSV con le colonne: customer_id, product_id, score, reason, normalized_score, name.
"""

import sys
import pandas as pd
import numpy as np
from collections import defaultdict
from itertools import combinations


def load_data(clienti_file: str, prodotti_file: str, ordini_file: str, righe_file: str):
    """Carica i dati dai file Excel forniti."""
    clienti = pd.read_excel(clienti_file)
    prodotti = pd.read_excel(prodotti_file)
    ordini = pd.read_excel(ordini_file)
    righe = pd.read_excel(righe_file)
    # Converti la colonna date in formato datetime
    ordini['date'] = pd.to_datetime(ordini['date'])
    return clienti, prodotti, ordini, righe


def compute_reorder_scores(ordini: pd.DataFrame, righe: pd.DataFrame, reference_date: pd.Timestamp):
    """Calcola il punteggio di riordino per ciascun cliente e prodotto."""
    order_data = ordini.merge(righe, on='order_id')
    order_data_sorted = order_data.sort_values(['customer_id', 'product_id', 'date'])
    reorder_records = []
    for (cust, prod), group in order_data_sorted.groupby(['customer_id', 'product_id']):
        dates = group['date'].sort_values()
        if len(dates) > 1:
            intervals = dates.diff().dropna().dt.days
            median_interval = intervals.median()
            days_since_last = (reference_date - dates.max()).days
            reorder_score = 1 / (1 + np.exp((days_since_last - median_interval) / (median_interval if median_interval else 1)))
        else:
            # Se ha acquistato una sola volta, usa una cadenza di 180 giorni come riferimento
            days_since_last = (reference_date - dates.max()).days
            reorder_score = 1 / (1 + np.exp((days_since_last - 180) / 180))
        reorder_records.append({'customer_id': cust, 'product_id': prod, 'reorder_score': reorder_score})
    reorder_df = pd.DataFrame(reorder_records)
    # Normalizza i punteggi globalmente (si può fare anche per cliente, ma questo è sufficiente)
    max_reorder = reorder_df['reorder_score'].max()
    reorder_df['normalized_reorder'] = reorder_df['reorder_score'] / (max_reorder if max_reorder else 1)
    return reorder_df


def compute_cross_sell(ordini: pd.DataFrame, righe: pd.DataFrame):
    """Calcola le associazioni tra prodotti utilizzando supporto e lift."""
    order_data = ordini.merge(righe, on='order_id')
    pair_counts = defaultdict(int)
    product_counts = defaultdict(int)
    total_orders = 0
    for order_id, items in order_data.groupby('order_id'):
        prods = set(items['product_id'].tolist())
        total_orders += 1
        for prod in prods:
            product_counts[prod] += 1
        for a, b in combinations(prods, 2):
            pair = (min(a, b), max(a, b))
            pair_counts[pair] += 1
    cross = defaultdict(list)
    for (a, b), count in pair_counts.items():
        support = count / total_orders
        lift = support / ((product_counts[a] / total_orders) * (product_counts[b] / total_orders))
        score = support * lift
        cross[a].append((b, score))
        cross[b].append((a, score))
    return cross


def generate_recommendations(clienti: pd.DataFrame, prodotti: pd.DataFrame, reorder_df: pd.DataFrame, cross_sell: dict):
    """Combina il punteggio di riordino e il cross-sell per generare raccomandazioni per ciascun cliente."""
    recommendations = []
    for cust in clienti['customer_id']:
        history = reorder_df[reorder_df['customer_id'] == cust]
        bought = history['product_id'].tolist()
        for _, row in history.iterrows():
            prod = row['product_id']
            score = 0.7 * row['normalized_reorder']
            recommendations.append({
                'customer_id': cust,
                'product_id': prod,
                'score': score,
                'reason': 'Riordino'
            })
            for cross_prod, cross_score in cross_sell.get(prod, []):
                if cross_prod not in bought:
                    recommendations.append({
                        'customer_id': cust,
                        'product_id': cross_prod,
                        'score': 0.3 * cross_score,
                        'reason': f'Associato a {prod}'
                    })
    rec_df = pd.DataFrame(recommendations)
    rec_df = rec_df.groupby(['customer_id', 'product_id']).agg({
        'score': 'sum',
        'reason': lambda reasons: '; '.join(set(reasons))
    }).reset_index()
    max_score_per_cust = rec_df.groupby('customer_id')['score'].transform('max')
    rec_df['normalized_score'] = rec_df['score'] / max_score_per_cust.replace(0, 1)
    rec_df = rec_df.merge(prodotti[['product_id', 'name']], on='product_id')
    rec_df = rec_df.sort_values(['customer_id', 'normalized_score'], ascending=[True, False])
    return rec_df


def main():
    if len(sys.argv) != 6:
        print("Uso: python recommendation_script.py clienti.xlsx prodotti.xlsx ordini.xlsx righe_ordini.xlsx output.csv")
        sys.exit(1)
    clienti_file, prodotti_file, ordini_file, righe_file, output_file = sys.argv[1:]
    reference_date = pd.Timestamp('2025-09-06')
    clienti, prodotti, ordini, righe = load_data(clienti_file, prodotti_file, ordini_file, righe_file)
    reorder_df = compute_reorder_scores(ordini, righe, reference_date)
    cross_sell = compute_cross_sell(ordini, righe)
    rec_df = generate_recommendations(clienti, prodotti, reorder_df, cross_sell)
    rec_df.to_csv(output_file, index=False)
    print(f"Raccomandazioni salvate in {output_file}")


if __name__ == '__main__':
    main()
