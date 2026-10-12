import streamlit as st
import pandas as pd
import psycopg2
import os

st.set_page_config(page_title='BIST V6 Mobil', page_icon='📈', layout='centered')

st.title('📈 BIST V6 Mobil Canlı Veri Paneli')
st.markdown('Cepten 7/24 erişim için **Railway PostgreSQL & Streamlit** bulut altyapısı.')

@st.cache_data(ttl=600)
def veri_cek():
    # Railway veritabanı bağlantı adresini buraya veya Streamlit Secrets'a ekleyeceğiz
    # Şimdilik Railway bağlantı cümleni (DATABASE_URL) kullanıyoruz
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        # Alternatif olarak direkt bağlantı adresini buraya yazabiliriz
        db_url = 'postgresql://postgres:sifren@host:port/veritabani' 
    
    conn = psycopg2.connect(db_url)
    query = 'SELECT * FROM bist_v6.records LIMIT 1000'
    df = pd.read_sql(query, conn)
    conn.close()
    return df

try:
    with st.spinner('Railway veritabanından canlı veriler yükleniyor...'):
        df = veri_cek()
    st.success(f'Bağlantı başarılı! Toplam {len(df):,} kayıt listeleniyor.')
    
    sorgu = st.text_input('🔍 Kayıtlarda Ara (Hisse, Sembol vb.):')
    if sorgu:
        mask = df.astype(str).apply(lambda x: x.str.contains(sorgu, case=False, na=False)).any(axis=1)
        df_filtrelenmis = df[mask]
        st.dataframe(df_filtrelenmis, use_container_width=True)
    else:
        st.dataframe(df.head(100), use_container_width=True)
except Exception as e:
    st.error(f'Bağlantı hatası: {e}')
