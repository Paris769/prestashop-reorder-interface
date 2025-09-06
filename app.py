import streamlit as st
import pandas as pd
import json

st.title("Gestione Riordini PrestaShop")

# Carica dati da file JSON
def load_data():
    with open('recommendations_demo.json', 'r') as f:
        return json.load(f)

# Carica i dati solo una volta con caching
if 'data' not in st.session_state:
    st.session_state['data'] = load_data()

# Lista clienti basata sui dati
clienti = list(st.session_state['data'].keys())
cliente = st.selectbox("Seleziona cliente", clienti)

# DataFrame dei prodotti per il cliente selezionato
df = pd.DataFrame(st.session_state['data'][cliente])

st.subheader("Prodotti consigliati")
# Editor interattivo per modificare quantità o rimuovere prodotti
edited_df = st.data_editor(df, num_rows="dynamic")

st.subheader("Aggiungi immagini")
images = st.file_uploader("Carica una o più immagini", accept_multiple_files=True)

metodo = st.selectbox("Metodo di invio", ["Email", "WhatsApp"])
testo = st.text_area("Testo del messaggio")

# Impostazioni PrestaShop in sidebar
st.sidebar.header("Impostazioni PrestaShop")
api_key = st.sidebar.text_input("Chiave API PrestaShop", type='password')

if st.button("Invia proposta"):
    st.write("Proposta pronta per: ", cliente)
    st.write("Prodotti selezionati:")
    st.dataframe(edited_df)
    if images:
        st.write("Numero immagini allegate: ", len(images))
    else:
        st.write("Nessuna immagine allegata")
    st.write("Metodo di invio: ", metodo)
    st.write("Testo del messaggio: ")
    st.write(testo)
