"use client";
import { useState, useEffect } from "react";
import axios from "axios";
import { Play, Square, Activity, Tv, Loader2, Video, RefreshCw } from "lucide-react";

export default function Dashboard() {
  const [keywords, setKeywords] = useState("");
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [status, setStatus] = useState("Bekliyor");
  
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [isLoadingChannels, setIsLoadingChannels] = useState(true);
  
  // YENİ: Klipleri tutacağımız state
  const [clips, setClips] = useState<{isim: string, url: string}[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Python'dan kanal listesini çek
  useEffect(() => {
    const fetchChannels = async () => {
      try {
        const response = await axios.get("http://127.0.0.1:8000/api/channels");
        if (response.data.status === "success") {
          setAvailableChannels(response.data.channels);
        }
      } catch (error) {
        console.error("Kanal listesi çekilemedi.");
      } finally {
        setIsLoadingChannels(false);
      }
    };
    fetchChannels();
  }, []);

  // YENİ: Python'dan üretilen klipleri çek
  const fetchClips = async () => {
    setIsRefreshing(true);
    try {
      const response = await axios.get("http://127.0.0.1:8000/api/klipler");
      if (response.data.status === "success") {
        setClips(response.data.klipler);
      }
    } catch (error) {
      console.error("Klipler çekilemedi.");
    } finally {
      setTimeout(() => setIsRefreshing(false), 500); // Buton animasyonu için ufak gecikme
    }
  };

  // YENİ: Sistem çalışırken her 10 saniyede bir klipleri otomatik güncelle
  useEffect(() => {
    fetchClips(); // Sayfa ilk açıldığında bir kere çek
    
    let interval: NodeJS.Timeout;
    if (status.includes("Aktif")) {
      interval = setInterval(() => {
        fetchClips();
      }, 10000);
    }
    return () => clearInterval(interval);
  }, [status]);

  const handleChannelToggle = (kanal: string) => {
    setSelectedChannels(prev => 
      prev.includes(kanal) 
        ? prev.filter(k => k !== kanal) 
        : [...prev, kanal]
    );
  };

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedChannels.length === 0) {
      alert("Lütfen en az bir kanal seçin!");
      return;
    }
    setStatus("Başlatılıyor...");
    const keywordList = keywords.split(",").map((k) => k.trim()).filter((k) => k);

    try {
      const response = await axios.post("http://127.0.0.1:8000/api/start", {
        keywords: keywordList,
        channels: selectedChannels, 
      });
      if (response.data.status === "success") {
        setStatus("Aktif - Dinleniyor 🟢");
      } else {
        setStatus(`Hata: ${response.data.message}`);
      }
    } catch (error) {
      setStatus("Bağlantı Hatası! Python API kapalı olabilir.");
    }
  };

  const handleStop = async () => {
    setStatus("Durduruluyor...");
    try {
      await axios.post("http://127.0.0.1:8000/api/stop");
      setStatus("Durduruldu 🔴");
    } catch (error) {
      setStatus("Bağlantı Hatası!");
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8 font-sans">
      <div className="max-w-5xl mx-auto space-y-8">
        
        {/* ÜST BİLGİ */}
        <header className="flex items-center justify-between border-b border-slate-700 pb-6">
          <div>
            <h1 className="text-3xl font-bold text-blue-400">Matriks Medya Asistanı</h1>
            <p className="text-slate-400 mt-2">Canlı Yayın Gözlem ve Klip Motoru</p>
          </div>
          <div className={`px-4 py-2 rounded-full font-semibold flex items-center gap-2 ${status.includes("Aktif") ? "bg-green-500/20 text-green-400" : "bg-slate-800 text-slate-300"}`}>
            <Activity size={18} />
            {status}
          </div>
        </header>

        {/* KONTROL PANELİ */}
        <div className="bg-slate-800 rounded-xl p-6 shadow-xl border border-slate-700">
          <form onSubmit={handleStart} className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">Hedef Kelimeler (Virgülle ayırın)</label>
              <input 
                type="text" 
                required
                placeholder="Örn: matriks, borsa, dolar, faiz"
                className="w-full bg-slate-900 border border-slate-600 rounded-lg p-3 text-white focus:outline-none focus:border-blue-500"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-3">Takip Edilecek Kanallar</label>
              
              {isLoadingChannels ? (
                <div className="flex items-center gap-2 text-slate-400 p-4">
                  <Loader2 className="animate-spin" size={20} />
                  <span>Kanallar Python'dan çekiliyor, Playwright çalışıyor...</span>
                </div>
              ) : availableChannels.length === 0 ? (
                <div className="text-red-400 p-4 border border-red-900 bg-red-900/20 rounded-lg">
                  Kanal listesi alınamadı. Python sunucusunun çalıştığından emin olun.
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {availableChannels.map((kanal) => (
                    <div 
                      key={kanal}
                      onClick={() => handleChannelToggle(kanal)}
                      className={`cursor-pointer flex items-center justify-center gap-2 p-3 rounded-lg border transition-all ${
                        selectedChannels.includes(kanal) 
                          ? "bg-blue-600/20 border-blue-500 text-blue-400" 
                          : "bg-slate-900 border-slate-600 text-slate-400 hover:border-slate-500"
                      }`}
                    >
                      <Tv size={16} />
                      <span className="font-medium text-sm">{kanal}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex gap-4 pt-4 border-t border-slate-700">
              <button type="submit" disabled={isLoadingChannels} className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 px-6 rounded-lg flex items-center justify-center gap-2 transition-colors">
                <Play size={20} /> Asistanı Başlat
              </button>
              <button type="button" onClick={handleStop} className="flex-1 bg-red-600 hover:bg-red-500 text-white font-bold py-3 px-6 rounded-lg flex items-center justify-center gap-2 transition-colors">
                <Square size={20} /> Sistemi Durdur
              </button>
            </div>
          </form>
        </div>

        {/* YENİ: KLİP GALERİSİ */}
        <div className="bg-slate-800 rounded-xl p-6 shadow-xl border border-slate-700">
          <div className="flex items-center justify-between mb-6 border-b border-slate-700 pb-4">
            <h2 className="text-xl font-bold flex items-center gap-2 text-slate-200">
              <Video className="text-blue-400" /> Yakalanan Klipler
            </h2>
            <button 
              onClick={fetchClips} 
              className="flex items-center gap-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors text-sm text-slate-300"
            >
              <RefreshCw size={16} className={isRefreshing ? "animate-spin" : ""} />
              Yenile
            </button>
          </div>

          {clips.length === 0 ? (
            <div className="text-center py-12 text-slate-500 border-2 border-dashed border-slate-700 rounded-lg bg-slate-900/50">
              Henüz yakalanan bir klip yok. Gözlemci devrede...
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {clips.map((klip, idx) => (
                <div key={idx} className="bg-slate-900 rounded-xl overflow-hidden border border-slate-700 shadow-lg group">
                  {/* Video Oynatıcı */}
                  <video 
                    controls 
                    preload="metadata"
                    className="w-full aspect-video bg-black object-contain"
                  >
                    <source src={klip.url} type="video/mp4" />
                    Tarayıcınız video etiketini desteklemiyor.
                  </video>
                  
                  {/* Klip Bilgisi (Dosya isminden okunabilir hale getiriliyor) */}
                  <div className="p-4 bg-slate-800/50">
                    <p className="text-sm font-semibold text-slate-300 truncate">
                      {klip.isim.replace(".mp4", "").replace(/_/g, " ")}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}