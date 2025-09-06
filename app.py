import streamlit as st
import pandas as pd

st.title("Gestione Riordini PrestaShop")

# Carica i dati e memorizzali in cache
@st.cache_data
def load_data():
    return pd.read_json('recommendations_demo.json')

# Carica tutto il DataFrame
all_df = load_data()

# Assicurati che il campo quantità prevista sia intero se presente
if 'predicted_qty' in all_df.columns:
    all_df['predicted_qty'] = all_df['predicted_qty'].astype(int)

# Lista clienti disponibili
client_ids = sorted(all_df['customer_id'].unique())
cliente = st.selectbox("Seleziona cliente", client_ids)

# Filtra i dati per il cliente selezionato
df_client = all_df[all_df['customer_id'] == cliente].copy()

# Prepara il DataFrame da visualizzare
rename_map = {
    'product_id': 'ID prodotto',
    'name': 'Prodotto',
    'predicted_qty': 'Quantità suggerita',
    'normalized_score': 'Punteggio',
    'reason': 'Motivazione'
}
df_display = df_client.rename(columns=rename_map)[list(rename_map.values())]

st.subheader("Prodotti consigliati")
edited_df = st.data_editor(df_display, num_rows="dynamic")

st.subheader("Aggiungi immagini")
images = st.file_uploader("Carica una o più immagini", accept_multiple_files=True)

metodo = st.selectbox("Metodo di invio", ["Email", "WhatsApp"])
testo = st.text_area("Testo del messaggio")

st.sidebar.header("Impostazioni PrestaShop")
api_key = st.sidebar.text_input("Chiave API PrestaShop", type="password")

if st.button("Invia proposta"):
    st.write(f"Proposta pronta per cliente: {cliente}")
    st.dataframe(edited_df)
    st.write("Numero immagini allegate:", len(images) if images else 0)
    st.write("Metodo di invio:", metodo)
    st.write("Testo del messaggio:")
    st.write(testo)
