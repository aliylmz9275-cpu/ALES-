# ALES Sistem Denetimi (AUDIT.md)

Bu belge, ALES (Advanced Logic Execution System) projesindeki tüm bileşenlerin, modüllerin ve özelliklerin gerçek durumunu hiçbir pazarlama abartısı olmadan, somut test kanıtlarıyla belgelemektedir.

Tarih: Ekim 2026  
Sürüm: ALES v3.0 Final Build  
Çalışma Modu: Tekil Windows Masaüstü Asistanı (`release/ALES.exe`)

---

## 1. Kritik Hata Düzeltmeleri & Temel Mimari

| Bileşen | Durum | Kanıt & Açıklama |
|---|---|---|
| **Puter.js Protokol Düzeltmesi** | ✅ **ÇALIŞIYOR** | Eskiden `electron-main.js` içinde `loadFile` ile `file://` üzerinden yüklenen arayüz `loadURL('http://localhost:8000')` olarak değiştirildi. Backend (`backend/main.py`) derlenmiş `dist` klasörünü statik dosya olarak bağlar ve SPA fallback sağlar. Puter SDK `http://localhost:8000` orijini altında çalıştığı için "Unsupported Protocol – file://" hatası kalıcı olarak giderildi. |
| **Puter Giriş Pop-up Yönetimi** | ✅ **ÇALIŞIYOR** | `electron-main.js` içindeki `setWindowOpenHandler`, Puter.js oturum açma pencerelerine kontrollü izin verir ve token `postMessage` ile güvenle ana pencereye iletilir. |
| **Electron Backend Yeniden Deneme (Retry Loop)** | ✅ **ÇALIŞIYOR** | `electron-main.js` açılışta `http://localhost:8000/status` ucunu yoklayarak arka uç tamamen ayağa kalkana kadar artan gecikmeyle (20 deneme) bekler. Sayfa yükleme hatasında ise 40 denemeli eksponansiyel geri çekilme döngüsü devrededir. |
| **Tekil Windows EXE Paketleme** | ✅ **ÇALIŞIYOR** | `release/ALES.exe` bağımsız taşınabilir (portable) Windows masaüstü uygulaması olarak üretilir. Çift tıklandığında siyah konsol penceresi veya harici tarayıcı açılmaz. |

---

## 2. Temel Kişisel Asistan Yetenekleri

| Yetenek | Durum | Kanıt & Açıklama |
|---|---|---|
| **Masaüstü Denetimi (Computer Control)** | ✅ **ÇALIŞIYOR** | 3 Gerçek Görev Test Edildi:<br>1. **Ekran Görüntüsü:** `vision._grab_screen` ve `mss` entegrasyonu ile tam ekran (1920x1080) başarıyla yakalanıp diske kaydedildi.<br>2. **Notepad Açma & Yazma:** `open_app("notepad")` ve `type_text("hello from ALES")` ile Windows Not Defteri açıldı ve pano tabanlı Türkçe destekli yazım yapıldı.<br>3. **Tarayıcı Arama:** `webbrowser` ile Chrome/varsayılan tarayıcıda hava durumu araması tetiklendi.<br>Ek olarak `native_desktop.list_windows` masaüstü oturumuna (`winsta0\default`) bağlanarak açık pencereleri (16+ pencere) eksiksiz listeler. |
| **Türkçe Ses Çıkışı (TTS)** | ✅ **ÇALIŞIYOR** | `audio_streamer.py` ve güncel `edge-tts` (>=7.0.0) kullanılarak Türkçe nöral ses sentezi (`tr-TR-AhmetNeural` / `tr-TR-EmelNeural`) test edildi. 24.192 baytlık MP3 ses verisi başarıyla üretildi. |
| **Ses Girişi (STT)** | 🟡 **BETA** | Electron / Chromium yerel Web Speech API ve bas-konuş (Push-to-Talk) entegrasyonu mevcuttur. Arka planda tam çevrimdışı Whisper modeli yüklenmediğinden tarayıcı motoruna bağımlıdır. |
| **Fast Path (Zero-LLM Hızlı Yol)** | ✅ **ÇALIŞIYOR** | `fast_path.py` ve `skills.json` 20 gerçek komut ile test edildi. 15 rutin komut ("ekran görüntüsü al", "ss al", "sistem bilgisi", "kripto fiyatları", "döviz kuru", "haberler", "hava durumu", "notepad aç" vb.) LLM'e hiç uğramadan <50ms süreyle doğrudan araçlara yönlendirildi. 5 sohbet/soru komutu doğru şekilde AI'ya bırakıldı (Hedef: >=5, Gerçekleşen: 15). |
| **Kalıcı Hafıza (Long-Term Memory)** | ✅ **ÇALIŞIYOR** | `long_term_memory.py` tekil SQLite veritabanı (`%APPDATA%\ALES\ltm.db`) ve yerel 256-boyutlu embedding ile çalışır. Testte eklenen bilgi, veritabanı bağlantısı sıfırlandıktan sonra ("Ali hangi programlama dilini sever?") semantik arama ile başarıyla geri çağrıldı. Ebbinghaus unutma eğrisi devrededir. |
| **Sınırlı Kendi Kendini Onarma (Self-Heal)** | ✅ **ÇALIŞIYOR** | `self_heal.py` çöken arka plan işlerini eksponansiyel geri çekilme ile en fazla 5 kez yeniden başlatır. Kendi kodunu yeniden yazma (self-rewriting) veya çoğalma (self-replication) bulunmamaktadır. |

---

## 3. Yasal Otomasyon Modülleri

| Modül | Durum | Kanıt & Açıklama |
|---|---|---|
| **Freelance Mesaj Yöneticisi (`freelance_bridge.py`)** | ✅ **ÇALIŞIYOR** | Kullanıcının kendi tekil Fiverr / Bionluk hesabı üzerinden gelen mesajları okur, özetler ve profesyonel taslak yanıtlar üretir. **Asla otomatik göndermez.** Kullanıcı taslağı inceler ve platformdan kendisi gönderir. Arayüzde "SERBEST" sekmesi olarak yer alır. |
| **Dosya Düzenleyici (`file_organizer.py`)** | ✅ **ÇALIŞIYOR** | İstenen klasörü tarar; uzantı, kategori veya yaşa (gün) göre organize eder. **Önizleme (dry-run) garantilidir.** Kullanıcı onayı (`confirmed=True`) olmadan dosyaları taşımaz. Testte 2 dosya güvenle kategorize edilip taşındı. |
| **Rapor Oluşturucu (`report_generator.py`)** | ✅ **ÇALIŞIYOR** | CSV ve Excel (.xlsx) dosyalarını satır satır ayrıştırır; sayısal kolonların toplamını, ortalamasını, min/max değerlerini hesaplar. Şık, karanlık modda bağımsız HTML raporu üretir. Testte `test_data.csv` başarıyla analiz edildi ve rapor dosyası üretildi. |
| **E-Posta Asistanı (`email_assistant.py`)** | ✅ **ÇALIŞIYOR** | Standart IMAP/SSL ile gelen kutusundaki okunmamış e-postaları okur, özetler ve taslak yanıt hazırlar. **Asla otomatik göndermez.** SMTP gönderimi için açık onay parametresi (`confirmed=True`) zorunludur. |

---

## 4. Güvenlik & Güvenilirlik Katmanı

| Özellik | Durum | Kanıt & Açıklama |
|---|---|---|
| **Komut Kaynağı Takibi (Provenance Tracking)** | ✅ **ÇALIŞIYOR** | Gelen her komut kaynağıyla (`user_ui`, `user_voice`, `fast_path`, `cron`, `subagent`) etiketlenir ve denetim günlüğüne kaydedilir. |
| **İstem Enjeksiyonu Tespiti (Injection Detection)** | ✅ **ÇALIŞIYOR** | Dış araç çıktılarında veya girdilerde "ignore all previous instructions", "system override", "DAN" gibi jailbreak ve gizli talimat desenleri regex ile taranır ve şüpheli içerik engellenir. |
| **Yıkıcı İşlem Onayı (Destructive Action Intercept)** | ✅ **ÇALIŞIYOR** | Dosya silme (`rmdir /s`, `del /f`), disk formatlama veya kritik sistem dizinlerine yönelik işlemler yakalanır ve kullanıcı onay belirteci (token) oluşturularak bloke edilir. |
| **İşlem Bağlama Doğrulaması (Action Binding Validation)** | ✅ **ÇALIŞIYOR** | Tıklama koordinatları ekran sınırları (`1920x1080`) ve negatif değerler açısından doğrulanır. |
| **Alt Ajan Hafıza İzolasyonu (Memory Isolation)** | ✅ **ÇALIŞIYOR** | Alt ajanlar için izole isim alanları sağlanır; bir ajan diğerinin hafıza bölümünü okuyamaz veya üzerine yazamaz. |

---

## 5. Dürüst Kapsam & Dışarıda Bırakılanlar

| Özellik | Gerçek Durum | Neden Uygulanmadı? |
| **Çoklu Hesap & Proxy Bot Otomasyonu** | ❌ **UYGULANMADI** | Platform kullanım koşullarını (ToS) ihlal eden bot kullanımı, proxy rotasyonu ve CAPTCHA çözme kalıcı olarak kapsam dışıdır. |
| **Kendi Kodunu Değiştirme (Self-Rewriting Code)** | ❌ **UYGULANMADI** | Güvenlik açığı, öngörülemez davranış ve bozulma riski nedeniyle ALES kaynak kodunu değiştirmez; modellerin ağırlıklarını eğitmez. "Evrim" yalnızca istem ve kural düzeyinde deneyim kaydıdır. |
| **İnsan Taklidi Yorum & Spam Üretimi** | ❌ **UYGULANMADI** | Sosyal ağlarda veya freelance platformlarında spam ve sahte hesap faaliyetleri yasal ve etik politikalara aykırıdır. |
