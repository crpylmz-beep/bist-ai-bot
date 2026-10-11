import json
import streamlit as st
import pandas as pd

st.set_page_config(page_title='BIST V6 Mobil', page_icon='📈', layout='centered')

st.title('📈 BIST V6 Mobil Veri Paneli')
st.markdown('Cepten 7/24 erişim için **Railway & Streamlit** bulut altyapısı.')

@st.cache_data
def veri_yukle():
    with open('bist_records_yedek.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return pd.DataFrame(data)

with st.spinner('90,800 kayıt yükleniyor...'):
    df = veri_yukle()

st.success(f'Toplam {len(df):,} kayıt yüklendi!')

sorgu = st.text_input('🔍 Kayıtlarda Ara (Hisse, Sembol vb.):')
if sorgu:
    mask = df.astype(str).apply(lambda x: x.str.contains(sorgu, case=False, na=False)).any(axis=1)
    df_filtrelenmis = df[mask]
    st.write(f'Eşleşen kayıt sayısı: {len(df_filtrelenmis):,}')
    st.dataframe(df_filtrelenmis.head(100), use_container_width=True)
else:
    st.info('Performans için ilk 100 kayıt listeleniyor. Arama kutusunu kullanabilirsiniz.')
    st.dataframe(df.head(100), use_container_width=True)
