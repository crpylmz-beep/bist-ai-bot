FROM python:3.13.9-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Istanbul
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY webapp/data/sektor_haritasi.json webapp/data/sirket_site_haritasi.json ./seed-public/
COPY webapp/data/bist_data.json webapp/data/gun_ici_top10.json webapp/data/gun_ici_tum.json webapp/data/yarin_top10.json ./seed-public/
# Optional archives already present in the filtered COPY context.
RUN if [ -d webapp/data/yarin_top10_arsiv ]; then cp -r webapp/data/yarin_top10_arsiv seed-public/; fi
CMD ["python", "cloud_baslat.py"]
