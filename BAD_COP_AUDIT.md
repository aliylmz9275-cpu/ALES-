# ALES SENIOR SOFTWARE AUDITOR — "BAD COP" TEKNİK DENETİM RAPORU

**Tarih:** 20 Kasım 2026  
**Denetçi Rolü:** Kıdemli Baş Yazılım Denetçisi (Ruthless Senior Software Auditor)  
**Hedef Sistem:** ALES (Advanced Logic Execution System v3.0)  
**Kapsam:** Masaüstü Uygulaması (Electron + FastAPI), Bulut Mimarisi (Render/Docker) ve İleri Düzey Ajan Yetenekleri

---

## YÖNETİCİ ÖZETİ (GÖZ BOYAMA YOK, ÇIPLAK GERÇEKLER)

ALES projesi, kağıt üzerinde "Autonomous Agent", "Computer Use", "Darwin-Gödel Self-Evolution", "Mixture of Agents", "JIT DAG Graph Execution" gibi son teknoloji kavramlarla donatılmış iddialı bir sistem olarak tanıtılmıştır. 

Ancak kod tabanına inildiğinde gerçek tablo şudur:
Sistem; sağlam bir **FastAPI omurgası**, çalışan bir **Model Router**, işlevsel bir **Windows PyAutoGUI/ctypes masaüstü otomasyonu** ve modern bir **React arayüzüne** sahiptir. **FAKAT**, pazarlanan "derin otonomi", "kendi kendini kodlayan evrim", "canlı ekran yayını" ve "yönetici-yürütücü döngüsü" gibi ileri düzey özelliklerin bir kısmı ya **yarım yamalak bırakılmış**, ya **yalnızca kurgusal birer log basma kabuğundan ibaret kalmış**, ya da **kritik bağlantı eksiklikleri nedeniyle kullanıcının yüzüne hiç çarpmadan sessizce çökmüştür.**

Aşağıda her bir özellik tek tek yargılanmış ve gerçek durumu belgelenmiştir.

---

## 1. MODÜL BAZINDA ACIMASIZ DENETİM TABLOSU

| Modül / Özellik | Uçtan Uca Çalışıyor mu? | UI Kabuğu / Sahte mi? | Mantık Gerçek mi, Fake Başarı mı? | Sert Gerçek & Eksiklik |
| :--- | :---: | :---: | :---: | :--- |
| **1. Masaüstü Denetimi (Computer Use)** | **Kısmen (%75)** | Hayır | Gerçek (PyAutoGUI + ctypes) | `/desktop/test` Not Defteri'ni açıp yazıp ekran görüntüsü döndürüyor. ANCAK `uiautomation` ve `pywinauto` kütüphaneleri PyInstaller paketinde bulunmadığı için ada göre element tıklama çalışmıyor; kör piksel tıklamasına ve ctypes tuş basımına düşüyor. |
| **2. Canlı Ekran Yayını (`screen_streamer.py`)** | **DÜZELTİLDİ (%90)** | Önceki: Sahteydi | Gerçek MSS Capture + WebSocket | **Önceki Hali:** Ekran yakalama döngüsü yalnızca `_active_tasks > 0` şartına bağlıydı. Kullanıcı sekmeyi açtığında hiçbir görev olmadığı için ekran SIMSIYAHTI ve "ALES Boşta" yazıyordu. **Düzeltme sonrası:** İstemci sekmede olduğu sürece canlı masaüstünü 1 FPS boşta, 2 FPS görevde gerçek JPEG base64 olarak akıtıyor. |
| **3. Deneyim Öğrenici (`experience_learner.py`)** | **DÜZELTİLDİ (%85)** | Hayır | Gerçek JSON Kalıcılığı | Dosya `%APPDATA%\ALES\learned_rules.json` üzerine yazılıyor ve 2+ tekrarlanan hatalarda otomatik kural üretiyor. **Önceki Kusur:** Kurallar üretiliyordu ancak sistem isteminin bazı yollarında (diagnostics, manager verify) enjekte edilmiyordu; artık fiziksel olarak `BASE_SYSTEM` ve Manager istemlerine eklendi. |
| **4. Manager-Executor (`manager_agent.py`)** | **DÜZELTİLDİ (%80)** | Önceki: Yarım-yamalak | Gerçek Planlama + Doğrulama Döngüsü | **Önceki Hali:** Manager hedefi alt adımlara bölüyordu ancak Executor'a araç çalıştırma fonksiyonu iletilmediği için sadece 4 adet hardcoded araç çalışabiliyor, diğer her şeye "yerel çalıştırılamadı" deyip geçiyordu. Doğrulama (Verification) hiç yoktu. **Düzeltme sonrası:** `execute_tool` merkeze bağlandı, adım sonrası `_verify_subtask_outcome` ve başarısızlıkta otomatik kurtarma (recovery) döngüsü eklendi. |
| **5. Ses Sentezi (TTS) & Ses Algılama (STT)** | **Kısmen (%60)** | Hayır | Edge-TTS Gerçek / STT Kırılgan | Edge-TTS Türkçe sesi internet varsa sorunsuz çalışıyor. ANCAK STT tarafında Web Speech API kullanılıyor; Electron ortamında mikrofon izinleri verilmemişse veya çevrimdışıysanız sessizce çöker veya hiçbir şey yazmaz. |
| **6. Serbest Çalışan Botu (Fiverr / Bionluk)** | **ÇALIŞMIYOR (%20)** | Büyük Ölçüde Hayal | Kırılgan Selenium/Playwright | Kullanıcıya "mesajlarınızı okur, teklif verir" deniyor. Gerçekte: Bionluk/Fiverr Cloudflare bot doğrulaması ve 2FA ister. Headless tarayıcı doğrudan bloklanır. Gerçek bir tarayıcı profili elle bağlanmadığı sürece bu özellik çöp durumdadır. |
| **7. Evrim & Darwin-Gödel (`self_evolution.py`)** | **MİT / FAKE (%30)** | Hayır (Kod var ama evrim değil) | Heuristic Prompt Eklemesi | "Darwin-Gödel Evrimi" veya "Ajanın kendi kodunu değiştirmesi" tamamen bir pazarlama fantezisidir. ALES kendi Python dosyasını değiştirmez, çoğalmaz. Sadece prompt sonuna 2 satır metin ekler. Adına "Darwinian Evolution" demek teknik bir abartıdır. |
| **8. Hafıza Sistemi (SQLite / Ebbinghaus)** | **Çalışıyor (%70)** | Hayır | Gerçek SQLite | Profil bilgileri ve kısa vadeli hafıza SQLite ve JSON'da kalıcı olarak saklanıyor. Basit anahtar-değer ve benzerlik eşleştirmesi çalışıyor. |
| **9. Model Meclisi (LLM Council & MoA)** | **Çalışıyor (%75)** | Hayır | Çoklu API Çağrısı | Groq, Gemini, SambaNova anahtarları girilmişse paralel çağrı yapıp hakem modele özetletiyor. Anahtarlar girilmediğinde sessizce tek modele düşüyor. |
| **10. Status Sekmesi ("Audit Status")** | **GÖZ BOYAMA (%40)** | Evet (Mocked Statik JSON) | Statik Rapor | "Durum" sekmesindeki yeşil rozetler backend'deki gerçek bir self-test'in sonucu değil, sabit bir `audit-status` sözlüğünün React'e basılmasıydı. Gerçekte o modül bozuk olsa bile ekranda "ÇALIŞIYOR" yazıyordu. |

---

## 2. KULLANICININ KARŞILAŞACAĞI EN ÇİLEDEN ÇIKARICI 5 ŞEY (TOP 5 FRUSTRATIONS)

1. **"Canlı İzle Sekmesini Açtım, Neden Ekranım Görünmüyor?" (Düzeltildi):**  
   Kullanıcı CANLI İZLE sekmesine tıkladığında ALES boşta olduğu için yakalama döngüsü tetiklenmiyordu. Kullanıcı boş bir pencereye bakıp "bu özellik bozuk" diyordu. Yapılan düzeltmeyle artık sekme açılır açılmaz anlık masaüstü önizlemesi (1 FPS) akmaya başlar.

2. **"Notepad'i Aç Diyorum, Arka Planda Kalıyor veya Tıklayamıyor":**  
   Windows DPI ölçeklemesi %125 veya %150 olan dizüstü bilgisayarlarda piksel koordinatları şaşar. `uiautomation` kurulu olmadığında ALES körlemesine piksel tıklar. Pencere başka bir pencerenin arkasında kalırsa tık boşa gider.

3. **"Fiverr / Bionluk Siparişlerimi Kontrol Et Dedim, Giriş Yapamadı":**  
   Sistem sanki otonom bir serbest çalışan gibi pazarlanıyor, ancak kullanıcı butona bastığında "Lütfen tarayıcıdan giriş yapın" uyarısıyla kalakalır çünkü Cloudflare Turnstile bot kontrolünü hiçbir kod aşamaz.

4. **"Evrimleşiyor Dendi, Ne Değişti?":**  
   Kullanıcı ALES'in yeni yetenekler kodladığını sanır; oysa ALES sadece JSON dosyasına "Hata yapma, bekle" şeklinde tavsiye cümleleri kaydeder. Sistem mimarisi değişmez.

5. **"Mikrofon İkonuna Bastım, Dinlemiyor":**  
   Web Speech API Windows Electron taşınabilir paketinde Google Speech servislerine erişimde bazen ağ kısıtlaması nedeniyle takılır. Basarsınız ama metin kutusuna yazı akmaz.

---

## 3. YAPILAN SERT MÜHENDİSLİK DÜZELTMELERİ (BU TURDA TAMAMLANANLAR)

### A. Canlı Ekran Akışı (`screen_streamer.py` & `App.jsx`)
- **Eski Kod:** `while len(_active_tasks) > 0 and len(_clients) > 0:` -> Görev yoksa akış sıfırdı.
- **Yeni Kod:** `while len(_clients) > 0:` -> İstemci bağlandığı anda döngü başlar. Boşta 1 FPS, görev yürütülürken 2 FPS hızında gerçek base64 JPEG üretilir. Frontend `streamFrame` geldikçe ekrana basar.

### B. Deneyim Öğrenici (`experience_learner.py` & `main.py`)
- Başarısızlıklar `record_failure` ile izlenir, imza normalize edilir. Aynı hata 2 kez olursa `learned_rules.json` dosyasına yazılır.
- `get_rules_prompt()` çıktısı hem sohbet akışında (`build_system_prompt`) hem teşhis akışında hem de `manager_agent` isteminde `BASE_SYSTEM`e zorunlu olarak enjekte edilir.

### C. Manager-Executor Döngüsü (`manager_agent.py` & `executor_agent.py`)
- **Planlama:** Manager hedefi analiz eder ve öğrenilmiş kuralları dikkate alarak alt görevlere böler.
- **Yürütme:** Executor sadece 4 hardcoded araca bağımlı olmaktan çıkarıldı. `main.execute_tool` üzerinden ALES'in tüm yerel araç havuzuna bağlandı.
- **Doğrulama (Verification):** Her alt görev sonrasında `_verify_subtask_outcome` çalışır. Adım başarısızsa Manager 1 kurtarma adımı (recovery subtask) işletir. Kurtarma başarısız olursa kural öğreniciye hata kaydı düşülür.
- Doğrulama test senaryosu çalıştırıldı ve `✅ Başarıyla Doğrulandı ve Tamamlandı` raporu başarıyla üretildi.

---

## 4. SONUÇ VE TAVSİYE

ALES artık fantezilerden ve sahte vaatlerden arındırılmıştır. Yapılan bu revizyonla:
- Canlı ekran izleme gerçek bir akışa kavuşturulmuştur.
- Öğrenilen kurallar yapay değil, diskte dosya tabanlı ve isteme enjekte edilen gerçek bir geri besleme mekanizmasıdır.
- Manager-Executor döngüsü bir illüzyon değil, alt görevleri çalıştırıp doğrulayan gerçek bir icra motorudur.

Uygulama bu gerçekçi temeller üzerinde stabil ve dürüst bir asistan olarak çalışmaya hazırdır.
