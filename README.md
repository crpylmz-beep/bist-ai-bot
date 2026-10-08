# BIST Asistanı

Yerelde bağımlılıklar: `python -m pip install -r requirements.txt` (Python 3.13).

Web: `python web_server.py`; bağımsız worker: `python ana_motor.py`.

Railway kalıcı volume ve HTTPS/PWA kurulumu: [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md).
Railway tek volume'u iki servise paylaşmaz; hazırlanmış kurulum bir serviste iki ayrı process kullanır. İki ayrı servis için ortak veri deposuna geçiş gerekir.

Veri yolu/migration: [DATA_PERSISTENCE.md](DATA_PERSISTENCE.md). Worker: [ANA_MOTOR_SETUP.md](ANA_MOTOR_SETUP.md). Push: [PUSH_SETUP.md](PUSH_SETUP.md).

Testler: `python -m unittest discover -s tests`; JavaScript smoke testleri `tests/*.cjs`.

Pozitif kapanış havuzu, Yarın TOP10/30/50 ve 1/3/5 günlük ölçüm: [POZITIF_KAPANIS.md](POZITIF_KAPANIS.md).

V6 PostgreSQL/R2 hazırlığı ve kaynakları silmeyen DRY_RUN taşıma: [docs/STORAGE_V6.md](docs/STORAGE_V6.md). Varsayılan `STORAGE_BACKEND=legacy`; gerçek bağlantı ve production geçişi otomatik yapılmaz. Kapasite/maliyet sınırları: [docs/STORAGE_V6_COSTS.md](docs/STORAGE_V6_COSTS.md).
