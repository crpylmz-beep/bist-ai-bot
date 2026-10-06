FROM python:3.13.9-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Istanbul
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY webapp/data/sektor_haritasi.json webapp/data/sirket_site_haritasi.json ./seed-public/
CMD ["python", "cloud_baslat.py"]
