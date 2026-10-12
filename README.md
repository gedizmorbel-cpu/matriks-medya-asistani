# Matriks Medya Takip Asistanı

Matriks Medya Takip Asistanı, canlı TV yayınlarını (M3U8) eşzamanlı olarak arka planda kaydeden, Faster-Whisper ile anlık deşifre eden ve hedef kelimeler yakalandığında o anın klibini otomatik oluşturan entegre bir sistemdir.

**Geliştirici:** Gediz Bora Morbel

## Sistem Mimarisi
* **Frontend:** Next.js (React)
* **Backend API:** FastAPI (Python)
* **Görev Kuyruğu (Task Queue):** Celery & Redis
* **Medya İşleme:** FFmpeg
* **Web Scraping / Şifre Çözücü:** Playwright (Chromium)
* **Yapay Zeka (STT):** Faster-Whisper (CTranslate2)

## 1. Sistem Gereksinimleri
Sunucuda (Tavsiye edilen: Ubuntu 22.04+) aşağıdaki bağımlılıkların global olarak kurulu olması gerekmektedir:
* `python3` (v3.10 veya üzeri) ve `python3-pip`
* `nodejs` (v18+) ve `npm`
* `redis-server` (Aktif ve arka planda çalışıyor olmalı: `sudo systemctl start redis`)
* `ffmpeg` (Görüntü ve ses segmentasyonu için zorunlu: `sudo apt install ffmpeg`)

## 2. Kurulum Adımları

### A. Python Backend Kurulumu
1. Proje dizinine gidin.
2. Sanal ortam (virtual environment) oluşturun ve aktif edin:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Gerekli kütüphaneleri yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
4. **Kritik Adım:** Zorlu kanalların linklerini parse edebilmek için Playwright tarayıcılarını sisteme kurun:
   ```bash
   playwright install chromium
   ```

### B. Next.js Frontend Kurulumu
1. `matriks-frontend` (veya ilgili arayüz) klasörüne gidin.
2. Bağımlılıkları yükleyin:
   ```bash
   npm install
   ```
3. Üretime (Production) hazırlayın:
   ```bash
   npm run build
   ```

## 3. Sistemi Canlıda (Production) Ayağa Kaldırma
Sistemin kapanmaması için `PM2`, `Supervisor` veya `Systemd` gibi bir process manager kullanılması tavsiye edilir. Aşağıdaki 3 servisin aynı anda çalışması gerekir:

**1. FastAPI Sunucusu (Port: 8000)**
```bash
uvicorn matriks_api:app --host 0.0.0.0 --port 8000
```

**2. Celery İşçileri**
*(Not: `concurrency` değeri sunucunun CPU çekirdek sayısına ve takip edilecek kanal sayısına göre artırılmalıdır).*
```bash
celery -A matriks_api.celery_app worker --pool=threads --concurrency=20 --loglevel=info
```

**3. Next.js Arayüzü (Port: 3000)**
```bash
npm run start
```

## 4. İzinler ve Dizin Yapısı
Sunucuda projeyi çalıştıran kullanıcının, projenin kök dizininde otomatik oluşturulacak olan `bant_kayıtlar` ve `bant_klipler` dizinlerine okuma/yazma (r/w) izinlerine sahip olduğundan emin olun. FFmpeg ve Celery bu dizinlere anlık olarak veri yazıp silecektir.