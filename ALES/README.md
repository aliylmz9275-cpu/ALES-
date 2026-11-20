# ALES v2.0 — Kurulum Rehberi

## 🚨 KRİTİK DÜZELTME (bu paket) — Groq modelleri değişti

Groq, Haziran 2026'da `llama-3.3-70b-versatile` (sohbet) ve
`meta-llama/llama-4-scout-17b-16e-instruct` (vision) modellerini emekliye
ayırdı — bu yüzden her mesajda Groq/Cerebras'a erişilemiyor gibi görünüp
SambaNova gibi daha zayıf/yavaş yedeklere düşülüyordu (yavaşlığın sebebi de
buydu: her mesajda önce başarısız Groq denemesi, sonra sırayla diğer
sağlayıcılar deneniyordu).

Düzeltildi:
- Sohbet modeli → `openai/gpt-oss-120b` (Groq'un resmi önerdiği geçiş modeli)
- Vision modeli → `qwen/qwen3.6-27b` (Groq'un vision için önerdiği model)
- Streaming bir sorun yaşarsa artık önce AYNI sağlayıcıda tekrar denendikten
  sonra bir üst yedeğe düşülüyor (gereksiz yere daha zayıf sağlayıcılara
  düşmeyi önlüyor)

## 🔊 Ses kalitesi ve anında oynatma (bu paket)

- Ses artık backend'in açtığı bir mp3 dosyası/medya oynatıcı penceresi
  değil, doğrudan tarayıcıda **anında** çalıyor (ChatGPT'deki gibi) - hem
  PC'de hem telefonda doğru cihazdan ses çıkıyor.
- **Ücretsiz sesin kalitesi hakkında:** Edge-TTS (ElevenLabs key'in yoksa
  kullanılan ücretsiz ses) Türkçe'de ElevenLabs kadar doğal değil - bu
  motorun kendi sınırı. İki seçenek:
  1. Ayarlar'dan ücretsiz ses için Ahmet/Emel arasında dene, biri daha
     doğal gelebilir
  2. Gerçekten doğal bir ses istiyorsan [elevenlabs.io](https://elevenlabs.io)'dan
     ücretsiz bir hesap açıp key'i Ayarlar'a ekle — çok daha kaliteli
     Türkçe okuyor

---

## 🧩 Yeni skill'ler + kalite özellikleri (bu paket)

**Yeni skill'ler**
- **Panoya Erişim** (`panoya_erisim`) — panodaki metni oku/yaz. "Az önce
  kopyaladığım şeyi not al" gibi isteklerde kullanılır.
- **Medya/Spotify Kontrolü** (`medya_kontrolu`) — oynat/duraklat,
  sonraki/önceki parça, ses seviyesi. OS medya tuşlarını simüle eder,
  Spotify/YouTube/her neyse odaktaki uygulamayı kontrol eder, OAuth
  gerekmez.
- **Ekran Çevirisi** (`ekran_cevirisi`) — ekrandaki yabancı dil yazıyı
  anında hedef dile çevirir (önce yerel OCR + Groq, yoksa vision zincirine
  düşer).

**Proaktif bildirimler**
- `crypto_drop` ve `fiverr_message` tetikleyicileri artık GERÇEKTEN
  çalışıyor (eskiden sadece dokümanda vaad edilmiş, kod eksikti).
- `schedules.json`/`notifications.json` artık kalıcı AppData klasöründe
  tutuluyor (eskiden proje klasörüne bağımlıydı - paketlenmiş exe'de
  güncellemede kaybolabilirdi).
- Yeni bir bildirim geldiğinde artık işletim sistemi bildirimi olarak da
  gösteriliyor (Web Notification API), sadece sohbet geçmişine değil.

**Semantic/uzun süreli hafıza**
- `search_memory` artık sadece kayıtlı "facts" listesinde değil,
  **geçmişteki TÜM sohbetlerde** arıyor. "Geçen ay X hakkında ne
  konuşmuştuk" gibi sorulara cevap verebiliyor.
- Gemini key varsa sonuçlar embedding tabanlı **anlamsal** benzerlikle de
  yeniden sıralanıyor (eş anlamlı ifadelerde de doğru sonucu buluyor);
  yoksa anahtar kelime eşleşmesine düşüyor (yine çalışıyor).

**Onay akışı iyileştirmesi**
- Yeni bir onay isteği geldiğinde artık 4 saniyelik anketi beklemeden
  ANINDA banner'da görünüyor.
- Onay banner'ında artık "detay" ile tam olarak hangi işlem + hangi
  parametrelerle çalıştırılacağı görülebiliyor (şeffaflık/güvenlik).
- 24 saatten eski unutulmuş onay istekleri artık otomatik temizleniyor.

**Kullanım panosu (yeni "PANO" sekmesi)**
- Toplam sohbet/mesaj/işlem sayısı, son 14 günün aktivite grafiği, en
  çok kullanılan araçlar - var olan log verisinden türetiliyor, ekstra
  bir izleme sistemi eklenmedi.

---

## ⚡ Hız güncellemesi (bu paket)

- **Streaming yanıtlar**: Model artık kelime kelime cevap veriyor ve her
  parça ANINDA ekrana düşüyor (Groq `stream=True`). Eskiden cevabın
  TAMAMI üretilene kadar ekran boş kalıyordu; artık ilk kelime hemen
  görünüyor — algılanan hız çok büyük fark yaratıyor. WS'e yeni bir
  `token` mesaj tipi eklendi, frontend'de canlı bir "yazıyor" balonu
  olarak gösteriliyor.
- **`get_worldview` 3-4x hızlandı**: hava/deprem/döviz/kripto/haber
  eskiden SIRAYLA çekiliyordu (toplam süre = hepsinin toplamı). Artık
  paralel çekiliyor (toplam süre = en yavaş kaynağın süresi).
- **Kalıcı tarayıcı (Playwright)**: `browse_web`/`web_search_deep` artık
  her seferinde sıfırdan Chromium başlatmıyor — arka planda tek bir
  tarayıcı örneği açık tutuluyor, her istek sadece yeni bir sekme açıp
  kapatıyor. Art arda birkaç web isteğinde 5-10x hızlanma.
- **Daha fazla paralel iş parçacığı**: arka plan thread havuzu 4'ten
  8'e çıkarıldı — aynı anda birden fazla bloklayıcı işlem (ekran
  görüntüsü, ses üretimi, HTTP istekleri) artık birbirini beklemiyor.
- Var olan optimizasyonlar da yerinde: tool-router (her turda 40+
  aracın tamamı yerine sadece ilgili olanlar gönderiliyor) ve salt-okunur
  araçların paralel çalıştırılması.
- **OpenRouter yedek zincirine NVIDIA Nemotron 3 eklendi**: Groq VE
  Cerebras ikisi de başarısız olursa devreye giren ücretsiz OpenRouter
  yedeğinde artık önce `nemotron-3-super-120b-a12b:free` ve
  `nemotron-3-ultra-550b-a55b:free` deneniyor (120B/550B MoE, güçlü ve
  ücretsiz), sonra eski yedekler (Llama 3.3 70B, DeepSeek R1, Qwen3).

---

## 👁️ Vision (ekran görme) hız güncellemesi

Ekran analizi artık şu sırayla çalışıyor (her adım bir öncekinden hızlı,
sonrakiler ücretsiz/dayanıklılık yedekleri):

1. **OCR fast-path** — "ekranda ne yazıyor" türü isteklerde, hiçbir AI
   modeline gitmeden yerel Tesseract OCR ile ~100-300ms'de anında cevap.
   Kurulum: `pip install pytesseract` (zaten requirements.txt'te) +
   sistemine [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
   kur (Windows installer). Kurulu değilse otomatik atlanır, sıradaki
   adıma geçilir — hiçbir şey bozulmaz.
2. **Yerel Ollama + Ministral 3 (Mistral)** — bilgisayarında
   `ollama run ministral-3` ile bu vision modelini çalıştırıyorsan, ALES
   onu ağ gecikmesi SIFIR şekilde önce dener (Ollama kapalıysa ~0.4sn'de
   vazgeçip sıradaki adıma düşer, 60sn boyunca tekrar denemez).
3. **Groq (Qwen3.6-27B)** — bulut seçenekleri arasında en düşük gecikmeli
   olan (Groq'un LPU donanımı).
4. **OpenRouter / NVIDIA Nemotron 3 Nano Omni (ücretsiz)** — Groq/Ollama
   yoksa veya başarısız olursa, NVIDIA'nın ücretsiz multimodal modeli
   devreye giriyor (OpenRouter üzerinden `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`).
   "Reasoning" varyantı olduğu için diğerlerinden biraz daha yavaş
   olabilir — bu yüzden birincil hız seçeneği değil, ücretsiz bir yedek.
5. **Gemini 2.5 Flash** — yedek/doğruluk odaklı son seçenek.

Ayrıca ekran görüntüsü artık varsayılan olarak **sadece aktif pencereyi**
yakalıyor (region="auto") — tüm ekranı yakalamaktan çok daha küçük/hızlı.
Kullanıcı "tüm ekranı göster" derse ALES otomatik olarak
region="full_screen" kullanır.

**"Ministral 3" ile "Nemotron 3" karışmasın:**
- **Ministral 3** → Mistral AI'nin edge model ailesi (3B/8B/14B, vision
  destekli, Apache 2.0). Groq'ta yok; ana sohbet modelinden (Groq Llama
  3.3 70B) daha güçlü değil. Değeri: küçük olması ve tamamen **yerelde**
  (Ollama ile, internetsiz) çalışabilmesi — bu yüzden sadece 2. adımda
  kullanılıyor.
- **Nemotron 3** → NVIDIA'nın model ailesi (Nano/Super/Ultra + vision
  destekli Nano Omni). Groq'ta henüz yok (toplulukta talep var ama canlı
  değil), ama **OpenRouter'da ücretsiz** — hem metin (Super/Ultra, artık
  `_call_openrouter` yedek zincirinde) hem görüntü (Nano Omni, vision
  zincirinde 4. adım) için eklendi.

---

## 🆕 v3.0 FIX güncellemesi

**Yeni: Skills sistemi (Claude'daki skill mantığı)**
- `backend/skills/` altında her klasör bir "skill" — `SKILL.md` (açıklama)
  + `skill.py` (SKILL_TOOLS + run() fonksiyonu) yeterli, ALES otomatik keşfeder.
- Örnek: `skills/youtube_oynatici/` — "youtube'da X'i aç/izlet/oynat" dendiğinde
  gerçekten ilk sonucu bulup tarayıcıda oynatan bir skill.
- Ayarlar > **Skills** panelinden: mevcut skilleri aç/kapat, sil, ya da
  SKILL.md + skill.py yapıştırarak yeni bir skill yükle — restart gerekmez.
- Backend uçları: `GET /skills`, `POST /skills/{id}/toggle`,
  `POST /skills/install`, `DELETE /skills/{id}`, `POST /skills/reload`.

**Yeni: Connectors sistemi (Claude'daki connector/MCP mantığı)**
- Hazır şablonlar: Notion, Slack, Spotify, Google Calendar — API key/token
  girip açana kadar hiçbir dış servise istek atılmaz.
- Kendi connector'ını da ekleyebilirsin: id + base URL + auth stili.
- ALES ajanı `list_connectors` ile hangilerinin aktif olduğunu görür,
  `call_connector(connector_id, path, method, body)` ile genel bir HTTP
  isteği yapar — her yeni connector için ayrı kod yazmaya gerek yok.
- Ayarlar > **Connectors** panelinden yönetilir. Backend uçları:
  `GET /connectors`, `POST /connectors/{id}/configure`,
  `POST /connectors/install`, `DELETE /connectors/{id}`.

**Düzeltmeler**
- `tool_router.py`: skill/connector kategorileri artık dinamik olarak
  arac yönlendirmeye dahil ediliyor (yeni bir skill eklenince kod
  değiştirmeden anahtar kelimeleriyle otomatik devreye giriyor).
- `main.py`: araç listesi (`TOOLS`) artık sabit değil, her mesajda
  `get_all_tools()` ile taze hesaplanıyor — panelden bir skill açılıp
  kapatıldığında hemen (restart'sız) yansıyor.
- `skills_engine.py`: PyInstaller ile paketlenmiş exe'de de doğru
  `skills/` klasörünü bulan, `filesystem.py`'deki mantıkla tutarlı bir
  yol çözümleme eklendi (yoksa paketli sürümde yeni skiller görünmezdi).
- `build.bat`: yeni modüller (`skills_engine`, `connectors`) pyinstaller
  hidden-imports listesine eklendi.

---

## 📁 Klasör Yapısı

```
ALES/
├── start.bat          ← Çift tıkla, her şey başlar
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   └── .env.example   ← Bunu .env yap, key gir
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        └── App.jsx
```

---

## ⚡ KURULUM (İlk kez)

### 1. Groq API Key al
- groq.com'a git
- Google ile giriş yap
- API Keys → Create Key
- Kopyala

### 2. .env dosyasını oluştur
- `backend/.env.example` dosyasını kopyala
- Adını `.env` yap
- `GROQ_API_KEY=` satırına key'ini yaz

### 3. Node.js kurulu değilse
- nodejs.org → LTS versiyonu indir, kur

### 4. start.bat'ı çalıştır
- `start.bat`'a çift tıkla
- İlk açılışta paketleri yükler (1-2 dk)
- Tarayıcı otomatik açılır

---

## 📱 Telefondan Bağlanmak

1. PC ve telefon **aynı Wi-Fi**'de olmalı
2. PC'nin IP adresini öğren:
   - Windows tuşu → `cmd` → `ipconfig`
   - `IPv4 Address` satırındaki IP (örn: 192.168.1.5)
3. Telefon tarayıcısında: `http://192.168.1.5:5173`
4. Kullan — tam PC arayüzü telefonda açılır

---

## 💬 ALES'e Ne Söyleyebilirsin

```
"Fiverr'ı kontrol et"
"Sistemi kontrol et"
"Chrome aç"
"Ekrana bak ne var"
"Not al: yarın müşteriye logo gönder"
"Notlarımı göster"
"Google'da React öğren ara"
"YouTube'da lo-fi müzik çal"
"Hangi skillerin/connector'ların var?"
"Az önce kopyaladığım şeyi göster"
"Müziği duraklat / sonraki şarkıya geç"
"Ekrandaki yazıyı Türkçe'ye çevir"
"Geçen ay tatil hakkında ne konuşmuştuk?"
```

---

## ⚠️ Sorun Giderme

**Backend başlamıyor:**
- `backend/` klasöründe `pip install -r requirements.txt` çalıştır

**Frontend açılmıyor:**
- `frontend/` klasöründe `npm install` çalıştır

**Bağlanamıyor:**
- `backend/.env` dosyasında key doğru mu?
- Antivirüs engelliyor olabilir, izin ver

**Telefon bağlanamıyor:**
- Aynı Wi-Fi'de misin?
- Windows Firewall → 5173 ve 8000 portlarına izin ver
