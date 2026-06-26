# Sonzai X API — Python/Flask Edition

Migrasi dari Cloudflare Worker (JavaScript) ke Python/Flask untuk deployment di VPS.

## 📁 Struktur Project

```
project-api/
├── app.py              # Entry point utama Flask
├── config.py           # Konfigurasi (API keys, headers, dll)
├── utils.py            # Utility functions (json_response, dll)
├── requirements.txt    # Dependencies Python
├── .env.example        # Template environment variables
├── Procfile            # Untuk deployment (gunicorn)
├── static/
│   └── index.html      # Frontend API Explorer  
└── routes/
    ├── __init__.py
    ├── auth.py          # API Key Management (Upstash Redis)
    ├── cors_proxy.py    # CORS Proxy
    ├── sosmed.py        # Social Media Downloader (TikTok, IG, FB)
    ├── terabox.py       # TeraBox Downloader
    ├── shinigami.py     # Shinigami Manga + PDF Generator
    ├── melolo.py        # Melolo Short Drama
    ├── dramabox.py      # DramaBox Short Drama (RSA signing)
    ├── dramawave.py     # DramaWave Short Drama
    ├── drama.py         # Drama Drakor
    ├── goodshort.py     # GoodShort Short Drama (RSA signing)
    ├── anime.py         # Anime Lover V3
    └── supabase_proxy.py # Proxy: ReelShort, FreeReels, NetShort, MeloShort, FlickReels, YouTube
```

## 🚀 Cara Deploy di VPS

### 1. Setup Environment

```bash
# Clone / upload project ke VPS
cd /path/to/project-api

# Buat virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Konfigurasi

```bash
# Copy .env.example ke .env
cp .env.example .env

# Edit sesuai kebutuhan
nano .env
```

### 3. Jalankan (Development)

```bash
python app.py
```

### 3a. Jalankan TeraBox Standalone

```bash
python standalone_terabox_api.py
```

Endpoint utama:

```bash
GET /terabox?url=https://1024terabox.com/s/1HcZ4bbKShOS8o69NX7MXFg
GET /terabox?url=https://1024terabox.com/s/xxxxx&pwd=1234
```

Mode standalone ini tidak membutuhkan `api_key`.

### 4. Jalankan (Production dengan Gunicorn)

```bash
gunicorn app:app -b 0.0.0.0:5000 -w 4 --timeout 120
```

### 5. Systemd Service (Optional)

Buat file `/etc/systemd/system/sonzaix-api.service`:

```ini
[Unit]
Description=Sonzai X API Flask
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/project-api
Environment=PATH=/path/to/project-api/venv/bin
ExecStart=/path/to/project-api/venv/bin/gunicorn app:app -b 0.0.0.0:5000 -w 4 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable sonzaix-api
sudo systemctl start sonzaix-api
```

## 📝 Perbedaan dari Versi Cloudflare Worker

| Fitur | Cloudflare Worker (JS) | Flask/VPS (Python) |
|---|---|---|
| Runtime | Cloudflare Edge | VPS (Python 3) |
| HTTP Client | `fetch()` | `requests` library |
| HTML Parser | `HTMLRewriter` | `BeautifulSoup` |
| PDF Generator | `pdf-lib.js` | `reportlab + Pillow` |
| RSA Signing | Web Crypto API | `cryptography` library |
| CORS | Manual headers | `flask-cors` |
| Config | Hardcoded | `.env` file support |
