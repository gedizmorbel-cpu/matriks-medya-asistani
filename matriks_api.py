import os
import time
import subprocess
import logging
import asyncio
import re
import requests
import threading
from datetime import datetime
import redis
from celery import Celery
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from faster_whisper import WhisperModel
from playwright.async_api import async_playwright
from fastapi.staticfiles import StaticFiles

# --- LOGLAMA SİSTEMİ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MatriksCore")

# --- DİNAMİK AYARLAR VE YOLLAR ---
HOME_DIR = os.path.expanduser("~")
KAYITLAR_DIR = os.path.join(HOME_DIR, "Desktop", "bant_kayıtlar")
KLIPLER_DIR = os.path.join(HOME_DIR, "Desktop", "bant_klipler")
FFMPEG_PATH = '/opt/homebrew/bin/ffmpeg'

# Klasörleri güvence altına al
os.makedirs(KAYITLAR_DIR, exist_ok=True)
os.makedirs(KLIPLER_DIR, exist_ok=True)

# Kilit mekanizması
klip_kilit = threading.Lock()

# Kullanıcının tanımladığı kanallar
OTOMATIK_KANALLAR = {
    "Habertürk TV": "https://www.haberturk.com/canliyayin",
    "TRT Haber": "https://www.trthaber.com/canli-yayin-izle.html"
}

STATIK_KANALLAR = {
    "CNBC-e": "https://hnpsechtsc.turknet.ercdn.net/xpnvudnlsv/cnbc-e/cnbc-e.m3u8",
    "NTV": "https://dogus.daioncdn.net/ntv/ntv.m3u8?app=ntv_web",
    "Ekotürk TV": "https://cdn.ekoturk.net/hls/master.m3u8",
    "TGRT Haber": "https://canli.tgrthaber.com/tgrt.m3u8"
}

# --- REDIS VE CELERY KURULUMU ---
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

celery_app = Celery(
    "matriks_tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

# --- FASTAPI KURULUMU ---
app = FastAPI(title="Matriks Medya Takip Asistanı API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_whisper_model = None

def get_model():
    global _whisper_model
    if _whisper_model is None:
        logger.info("🤖 Yapay zeka modeli (Faster-Whisper) Celery işçisine yükleniyor...")
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model

def klip_al(kaynak_dosya, kelime_saniyesi, kanal_ismi):
    with klip_kilit:
        guvenli_isim = "".join([c if c.isalnum() else "_" for c in kanal_ismi])
        zaman_damgasi = datetime.now().strftime('%Y%m%d_%H%M%S')
        hedef_dosya = os.path.join(KLIPLER_DIR, f"{guvenli_isim}_{zaman_damgasi}.mp4")
        
        baslangic = max(0, kelime_saniyesi - 15)
        
        ffmpeg_cmd = [
            FFMPEG_PATH, '-y', '-i', kaynak_dosya,
            '-ss', str(baslangic), '-t', '30',
            '-c:v', 'copy', '-c:a', 'aac',
            hedef_dosya
        ]
        
        subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"🎬 KLİP OLUŞTURULDU: {hedef_dosya}")

# --- PLAYWRIGHT DİNAMİK LİNK BULUCU (ZORLU KANALLAR İÇİN) ---
async def zorlu_kanallari_avla():
    sonuclar = {}
    print("\n🕵️ Zırhlı Kanallar (CNN & A Para) için Ninja Tarayıcı başlatılıyor...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=['--autoplay-policy=no-user-gesture-required', '--mute-audio']
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        
        # --- 1. CNN TÜRK OPERASYONU ---
        page_cnn = await context.new_page()
        yakalanan_cnn = None
        
        async def cnn_yakala(req):
            nonlocal yakalanan_cnn
            if yakalanan_cnn: return
            if ".m3u8" in req.url and "duhnet" in req.url:
                yakalanan_cnn = req.url
                
        page_cnn.on("request", cnn_yakala)
        try:
            print("🌐 CNN Türk adresine giriliyor...")
            await page_cnn.goto("https://www.cnnturk.com/canli-yayin", wait_until="domcontentloaded")
            for _ in range(8):
                await page_cnn.wait_for_timeout(1000)
                if yakalanan_cnn:
                    sonuclar["CNN Türk"] = yakalanan_cnn
                    print("✅ CNN Türk şifresi havada kapıldı!")
                    break
        except Exception as e:
            print(f"❌ CNN Türk Hatası: {e}")
        finally:
            await page_cnn.close()

        # --- 2. A PARA OPERASYONU ---
        page_apara = await context.new_page()
        yakalanan_apara = None
        
        async def apara_istek_yakala(req):
            nonlocal yakalanan_apara
            if yakalanan_apara: return
            url = req.url.lower()
            if ".m3u8" in url and "ad" not in url and "secure" not in url and "token" not in url:
                if "ercdn" in url or "trkvz" in url:
                    yakalanan_apara = req.url

        async def apara_cevap_yakala(res):
            nonlocal yakalanan_apara
            if yakalanan_apara: return
            try:
                if "secure" in res.url.lower() or "token" in res.url.lower():
                    text = await res.text()
                    if ".m3u8" in text:
                        eslesmeler = re.findall(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', text)
                        for link in eslesmeler:
                            if "ad" not in link.lower() and ("ercdn" in link or "trkvz" in link):
                                yakalanan_apara = link.replace('\\/', '/')
                                break
            except: pass

        page_apara.on("request", apara_istek_yakala)
        page_apara.on("response", apara_cevap_yakala)
        
        try:
            print("🌐 A Para adresine giriliyor...")
            await page_apara.goto("https://www.apara.com.tr/canli-yayin", wait_until="domcontentloaded", timeout=20000)
            await page_apara.wait_for_timeout(3000)
            
            print("📜 A Para: Sayfa kaydırılıp player uyanmaya zorlanıyor...")
            await page_apara.evaluate("window.scrollTo(0, document.body.scrollHeight/2);")
            await page_apara.wait_for_timeout(1000)
            
            print("🖱️ A Para: Tüm başlatıcı butonlar tetikleniyor...")
            await page_apara.evaluate('''
                document.querySelectorAll('button, .vjs-big-play-button, [class*="play"]').forEach(b => { try { b.click(); } catch(e) {} });
                document.querySelectorAll('video').forEach(v => { try { v.play(); } catch(e) {} });
            ''')
            
            for _ in range(12):
                await page_apara.wait_for_timeout(1000)
                if yakalanan_apara:
                    sonuclar["A Para"] = yakalanan_apara
                    print("✅ A Para şifresi güvenli dosyadan söküldü!")
                    break
        except Exception as e:
            print(f"❌ A Para Hatası: {e}")
        finally:
            await page_apara.close()

        # --- 3. BLOOMBERG HT OPERASYONU ---
        page_bht = await context.new_page()
        yakalanan_bht = None
        
        async def bht_yakala(req):
            nonlocal yakalanan_bht
            if yakalanan_bht: return
            url = req.url.lower()
            if ".m3u8" in url and "ad" not in url:
                yakalanan_bht = req.url
                
        page_bht.on("request", bht_yakala)
        try:
            print("🌐 Bloomberg HT adresine giriliyor...")
            await page_bht.goto("https://www.bloomberght.com/tv", wait_until="domcontentloaded")
            for _ in range(8):
                await page_bht.wait_for_timeout(1000)
                if yakalanan_bht:
                    sonuclar["Bloomberg HT"] = yakalanan_bht
                    print("✅ Bloomberg HT şifresi havada kapıldı!")
                    break
        except Exception as e:
            print(f"❌ Bloomberg HT Hatası: {e}")
        finally:
            await page_bht.close()

        await browser.close()
    return sonuclar

async def baslangic_linklerini_hazirla():
    print("🚀 Matriks Media Assistant başlatılıyor... Canlı linkler avlanıyor, lütfen bekleyin...")
    harita = {}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for kanal, sayfa_url in OTOMATIK_KANALLAR.items():
        try:
            response = requests.get(sayfa_url, headers=headers, timeout=8)
            bulunanlar = re.findall(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', response.text)
            if bulunanlar:
                harita[kanal] = list(set(bulunanlar))[0]
                print(f"✅ {kanal} güncel linki çekildi.")
            else:
                print(f"⚠ {kanal} linki bulunamadı.")
        except Exception as e:
            print(f"❌ {kanal} avlama hatası: {e}")

    try:
        zorlu_kanallar = await zorlu_kanallari_avla()
        harita.update(zorlu_kanallar)
    except Exception as e:
        print(f"⚠️ Zırhlı kanal avında hata: {e}")

    for kanal, url in STATIK_KANALLAR.items():
        harita[kanal] = url
        
    print("🎯 Tüm linkler hazır! API dinlemeye geçiyor...\n")
    return harita

KANAL_ISIM_URL_HARITASI = {}

@app.on_event("startup")
async def startup_event():
    global KANAL_ISIM_URL_HARITASI
    KANAL_ISIM_URL_HARITASI = await baslangic_linklerini_hazirla()


# --- CELERY GÖREVLERİ (ARKA PLAN İŞÇİLERİ) ---
@celery_app.task(name="matriks.indirici")
def indirici_ve_takip_yoneticisi(stream_url, kanal_ismi):
    logger.info(f"✅ {kanal_ismi} yayınına Celery üzerinden kilitlenildi. Segmentasyon başlıyor...")
    while redis_client.get("is_running") == "1":
        try:
            guvenli_isim = "".join([c if c.isalnum() else "_" for c in kanal_ismi])
            oturum_id = f"{guvenli_isim}_{datetime.now().strftime('%H%M%S')}"
            
            # SADECE Bloomberg için zaman damgası kalkanı
            if "bloomberg" in kanal_ismi.lower():
                ekstra_parametreler = ['-segment_time', '300', '-break_non_keyframes', '1']
            else:
                ekstra_parametreler = ['-segment_time', '300'] 
            
            ffmpeg_cmd = [
                FFMPEG_PATH, '-y', '-rw_timeout', '15000000',
                '-i', stream_url, '-c', 'copy', 
                '-f', 'segment'
            ] + ekstra_parametreler + [
                '-reset_timestamps', '1',
                f'{KAYITLAR_DIR}/{oturum_id}_parca_%03d.ts'
            ]
            
            # Ana indirme işlemi sessize alındı
            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            while process.poll() is None:
                if redis_client.get("is_running") != "1":
                    process.terminate()   
                    break
                time.sleep(2)
        except Exception as e:
            logger.error(f"❌ {kanal_ismi} Hata: {e}")
            time.sleep(5)

@celery_app.task(name="matriks.gozlemci")
def gozlemci_motor(hedef_kelimeler, baslatilan_kanallar):
    islenen_dosyalar = set()
    model = get_model()
    logger.info("👀 Gözlemci Zeka Motoru Celery üzerinde devrede...")
    
    while redis_client.get("is_running") == "1":
        mevcut_dosyalar = [f for f in os.listdir(KAYITLAR_DIR) if f.endswith('.ts')]
        mevcut_dosyalar.sort()
        su_an = time.time()
        
        en_yeni_dosyalar = {}
        for f in mevcut_dosyalar:
            oturum = f.split('_parca_')[0]
            en_yeni_dosyalar[oturum] = f 
        
        for dosya_adi in mevcut_dosyalar:
            if redis_client.get("is_running") != "1": break 
            tam_yol = os.path.join(KAYITLAR_DIR, dosya_adi)
            oturum_id = dosya_adi.split('_parca_')[0]
            
            if dosya_adi == en_yeni_dosyalar.get(oturum_id) and (su_an - os.path.getmtime(tam_yol) < 60):
                continue
            
            if tam_yol not in islenen_dosyalar and os.path.getsize(tam_yol) > 1000:
                islenen_dosyalar.add(tam_yol) 
                logger.info(f"🧠 Analiz ediliyor -> {dosya_adi}")
                
                try:
                    kanal_ismi = "Bilinmeyen"
                    for k in baslatilan_kanallar:
                        if "".join([c if c.isalnum() else "_" for c in k]) in dosya_adi:
                            kanal_ismi = k
                            break

                    wav_yol = tam_yol.replace('.ts', '.wav')
                    
                    # Ses analiz (WAV çıkarma) logları şeffaf bırakıldı (Özel İsteğin Üzerine)
                    subprocess.run(
                        [FFMPEG_PATH, '-y', '-i', tam_yol, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', wav_yol]
                    )

                    # ZIRH: Eğer bozuk videodan ses çıkarılamadıysa atla
                    if not os.path.exists(wav_yol):
                        logger.warning(f"⚠️ {dosya_adi} dosyasından ses çıkarılamadı (Bozuk yayın). Atlanıyor...")
                        try: os.remove(tam_yol)
                        except: pass
                        continue

                    segments, info = model.transcribe(wav_yol, beam_size=5, language="tr")
                    bulundu_mu = False
                    
                    for segment in segments:
                        if redis_client.get("is_running") != "1": break
                        metin = segment.text.lower()
                        
                        for kelime in hedef_kelimeler:
                            if kelime in metin:
                                bulundu_mu = True
                                logger.warning(f"🚨 HEDEF {kanal_ismi.upper()} KANALINDA YAKALANDI: '{kelime.upper()}' -> {segment.text.strip()}")
                                klip_al(tam_yol, segment.start, kanal_ismi)
                                break 
                                
                    try: os.remove(wav_yol)
                    except: pass
                    
                    if not bulundu_mu:
                        try: os.remove(tam_yol)
                        except: pass
                except Exception as e:
                    logger.error(f"❌ Analiz Hatası ({dosya_adi}): {e}")
        time.sleep(3)


# --- API UÇ NOKTALARI (SEKRETER) ---
@app.get("/api/channels")
def get_channels():
    global KANAL_ISIM_URL_HARITASI
    return {"status": "success", "channels": list(KANAL_ISIM_URL_HARITASI.keys())}

class StartRequest(BaseModel):
    keywords: List[str]
    channels: List[str] 

@app.post("/api/start")
def start_system(request: StartRequest):
    global KANAL_ISIM_URL_HARITASI

    if redis_client.get("is_running") == "1":
        return {"status": "error", "message": "Sistem zaten çalışıyor."}

    redis_client.set("is_running", "1")
    redis_client.set("start_time", str(time.time()))
    
    for f in os.listdir(KAYITLAR_DIR):
        if f.endswith('.ts'): 
            try: os.remove(os.path.join(KAYITLAR_DIR, f))
            except: pass

    hedef_kelimeler = [k.lower() for k in request.keywords]
    logger.info(f"🚀 SİSTEM BAŞLATILDI. İş emirleri Celery'e gönderiliyor...")

    baslatilan_kanallar = []

    for kanal_ismi in request.channels:
        stream_url = KANAL_ISIM_URL_HARITASI.get(kanal_ismi)
        
        if stream_url:
            logger.info(f"✅ {kanal_ismi} linki alındı, indirme başlatılıyor...")
            baslatilan_kanallar.append(kanal_ismi)
            indirici_ve_takip_yoneticisi.delay(stream_url, kanal_ismi)
        else:
            logger.error(f"⚠️ {kanal_ismi} atlandı çünkü m3u8 linki kütüphanede bulunamadı.")

    gozlemci_motor.delay(hedef_kelimeler, baslatilan_kanallar)

    return {"status": "success", "message": "Canlı takip ve analiz görevleri Celery'e iletildi."}

@app.post("/api/stop")
def stop_system():
    redis_client.set("is_running", "0")
    try:
        os.system("pkill -9 -f ffmpeg")
    except:
        pass
    logger.info("⏹️ Operasyon durdurma emri verildi.")
    return {"status": "success", "message": "Sistem güvenli bir şekilde durduruldu."}
# Tarayıcının klipleri oynatabilmesi için klasörü güvenli bir şekilde dışa açıyoruz
app.mount("/medya", StaticFiles(directory=KLIPLER_DIR), name="medya")

@app.get("/api/klipler")
def get_klipler():
    # Klasördeki mp4 dosyalarını yeniden eskiye doğru sıralayıp arayüze listeler
    klipler = []
    if os.path.exists(KLIPLER_DIR):
        for dosya in sorted(os.listdir(KLIPLER_DIR), reverse=True):
            if dosya.endswith('.mp4'):
                klipler.append({
                    "isim": dosya,
                    "url": f"http://127.0.0.1:8000/medya/{dosya}"
                })
    return {"status": "success", "klipler": klipler}