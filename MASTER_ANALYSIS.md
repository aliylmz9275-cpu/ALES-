# ALES BAŞ MİMARİ MANİFESTOSU VE ACIMASIZ TEKNİK DENETİM RAPORU
**Tarih:** 24 Kasım 2026  
**Doküman Sürümü:** 4.0.0-ENTERPRISE-AUDIT  
**Rol:** Baş Sistem Mimarı (Chief Architect & Systems Auditor)  
**Hedef:** ALES (Autonomous Learning & Execution System) Bütüncül Kod Tabanı ve Mimari İncelemesi  
**Dosya Konumu:** `MASTER_ANALYSIS.md`

---

## İÇİNDEKİLER
1. [Yönetici Özeti ve Temel Hüküm (Executive Summary & Brutal Verdict)](#1-yönetici-özeti-ve-temel-hüküm)
2. [Bölüm 1: Acımasız Gerçek — ALES Neden Hâlâ "Aptal" Hissettiriyor?](#bölüm-1-acımasız-gerçek--ales-neden-hâlâ-aptal-hissettiriyor)
   - 1.1. Prompt Zehirlenmesi ve Bağlam Çözünürlüğü Kaybı (Context Saturation & Attention Dilution)
   - 1.2. Sahte RAG Yanılsaması ve Vektör Veritabanı Yokluğu
   - 1.3. Model Router'ın Sessiz İflası ve "Açıklama Yapan Chatbot" Faciası
   - 1.4. Deterministik FastPath ve Bulanık Bellek Kargaşası
   - 1.5. Bağlam Yönetimi ve Kör Token Budama Hataları
3. [Bölüm 2: Claude Code'un Tersine Mühendisliği ve Ajan Açığı Analizi](#bölüm-2-claude-codeun-tersine-mühendisliği-ve-ajan-açığı-analizi)
   - 2.1. Claude Code Otonom ReAct Döngüsünün Matematiksel ve Mantıksal Anatomisi
   - 2.2. Araç Primitifleri Karşılaştırması: Claude Code vs. ALES
   - 2.3. Durumsal (Stateful) PTY vs. Durumsuz (Stateless) Subprocess
   - 2.4. Kendi Kendini Düzeltme (Self-Correction / Reflection) Döngüsü
4. [Bölüm 3: ALES'i Dünya Standardına Taşıyacak 10 Eksik Mimari Özellik](#bölüm-3-alesi-dünya-standardına-taşıyacak-10-eksik-mimari-özellik)
5. [Bölüm 4: Kod Tabanı Mimari Hataları ve Spagetti Analizi](#bölüm-4-kod-tabanı-mimari-hataları-ve-spagetti-analizi)
   - 4.1. `backend/main.py` (6,652 Satır): Monolitik Tasarım Çöküşü
   - 4.2. `frontend/src/App.jsx` (5,981 Satır): Monolitik React İşkencesi
   - 4.3. `railway/main_cloud.py` (1,075 Satır): DRY Prensibinin Katliamı
   - 4.4. `model_router.py` (969 Satır) ve `model_registry.py` (1,067 Satır): Aşırı Mühendislik
   - 4.5. "Hayalet Modüller" (Ghost Modules): Darwin-Gödel, CER, MUSE, JIT
6. [Bölüm 5: 4 Haftalık Ticari Düzeye Geçiş Yol Haritası (Gün Gün Eylem Planı)](#bölüm-5-4-haftalık-ticari-düzeye-geçiş-yol-haritası)
   - Hafta 1: Büyük Arınma, Modüler Ayrıştırma ve Çekirdek Ajan Motoru
   - Hafta 2: Gerçek Claude Code Motoru ve Durumsal PTY Terminal Mimarisi
   - Hafta 3: Gerçek Vektör RAG, tree-sitter Kod Haritası ve Otomatik İyileştirme
   - Hafta 4: Modern React Mimarisi, Ultra-Gerçekçi Ses ve Ticari Kararlılık
7. [Sonuç ve Nihai Mimari Taahhüt](#sonuç-ve-nihai-mimari-taahhüt)

---

## 1. YÖNETİCİ ÖZETİ VE TEMEL HÜKÜM

ALES projesi, kağıt üzerinde ve pazarlama anlatısında büyüleyici bir vaatte bulunmaktadır: *"Kendi kendine evrilen (Darwin-Gödel), 69 farklı aracı yönetebilen, Claude Code yeteneklerine sahip, LLM Meclisi ile en doğru kararı veren, JIT derleyicili otonom işletim sistemi ajanı."*

Ancak kod tabanının en derin satırlarına inildiğinde, **acımasız teknik gerçek** gün yüzüne çıkmaktadır:

1. **ALES bir "Ajan" (Agentic System) değildir.** ALES, birbirini ezen, birbiriyle çelişen onlarca heuristik katmanın, kontrolsüz `if/else` bloklarının ve çalışmayan teorik konseptlerin tek bir 6,652 satırlık Python dosyasında (`main.py`) toplandığı, ön yüzü ise 5,981 satırlık devasa tek bir React bileşeni (`App.jsx`) içine tıkılmış kırılgan bir **monolitik chatbot simülatörüdür**.
2. Sistemde tam **69 adet araç şeması (tool definitions)** tek bir istemde küçük LLM modellerine (Groq üzerindeki Llama-3.3-70b veya Cerebras üzerindeki 8b modellerine) enjekte edilmektedir. Bu durum, modelin dikkat penceresini (attention mechanism) tamamen doyurmakta (saturation) ve modelin felç olmasına ("Attention Dilution") sebep olmaktadır.
3. Model Router çöktüğünde veya Groq/Cerebras hız sınırına çarptığında, sistem kullanıcıya haber vermeden **araç çağırma desteği olmayan düz metin yedeklerine (`_call_gemini`, `_call_sambanova`)** düşmektedir. Model araç çağıramadığını anlayınca, kullanıcıya işi yapmak yerine *"Bunu Python ile şu şekilde yapabilirsiniz..."* diyerek ders anlatmaya başlamakta; kullanıcı haklı olarak ALES'in "aptallaştığını" düşünmektedir.
4. Bellek (Memory) tarafında **gerçek hiçbir Vektör Veritabanı (Vector DB) yoktur**. `long_term_memory.py` içinde SQLite-vec veya Gemini bulunamadığında devreye giren mekanizma `hashing-embedding + Python kosinus`tur; bu matematiksel olarak anlamsal hiçbir karşılığı olmayan rastgele bir parmak izi fonksiyonudur.
5. Yeni eklenen terminal ve kodlama yetenekleri Claude Code'un felsefesini simüle etmeye başlamış olsa da, **durumsuz (stateless)** çalışması, bir AST (Abstract Syntax Tree) kod haritasına sahip olmaması ve kendi kendini düzelten (self-healing / auto-correction) bir test geri-besleme döngüsünün eksikliği nedeniyle henüz Claude Code'un yanına yaklaşamamaktadır.

Bu rapor, ALES'in neden bu halde olduğunu, nelerin kökten değiştirilmesi gerektiğini ve sistemi 4 hafta içinde küresel çapta rekabetçi bir ticari yazılıma nasıl dönüştüreceğimizi tüm teknik çıplaklığıyla belgelemektedir.

---

## BÖLÜM 1: ACIMASIZ GERÇEK — ALES NEDEN HÂLÂ "APTAL" HİSSETTİRİYOR?

Kullanıcıların en büyük şikayeti şudur: *"Claude veya ChatGPT ile konuşurken akıllı, bağlamı anlayan ve doğrudan işi çözen bir varlıkla karşı karşıyayım. ALES ise bazen çok karmaşık teoriler sıralıyor ama en basit 'bana şu PDF'i üret', 'şu dosyayı oku ve düzelt' komutunda boş boş açıklamalar yapıyor, araç çağırmıyor veya saçmalıyor. Neden?"*

Bu durumun arkasında 5 ölümcül mimari hata yatmaktadır:

```
+---------------------------------------------------------------------------------------------------+
|                                  MEVCUT ALES İSTEM YIĞINI (PROMPT BLOAT)                          |
+---------------------------------------------------------------------------------------------------+
|  [BASE_SYSTEM] (Persona, kurallar, tarih, profiller)                           ~ 2,500 token     |
|  [LUBV] (Kalıcı Sistem Promptu - system_prompts.json)                         ~ 1,000 token     |
|  [UZUN VADELİ HAFIZA] (recall_long_term - hash çakışmalı rastgele notlar)       ~   800 token     |
|  [ÖĞRENİLEN KURALLAR] (experience_learner kuralları)                          ~   500 token     |
|  [CER ENJEKSİYONU] (Contextual Experience Replay yörüngeleri)                 ~ 1,500 token     |
|  [MUSE BELLEK] (Hiyerarşik strateji ilkeleri)                                 ~   800 token     |
|  [DARWIN-GÖDEL AKTİF İSKELE] (DGM strateji metni)                             ~   600 token     |
|  [69 ADET ARAÇ TANIMI] (JSON Function Schemas - Her biri devasa argümanlı)     ~ 5,500 token     |
|  [GEÇMİŞ KONUŞMALAR] (History [-20:] - Kırpılmamış araç çıktıları)             ~ 3,000 token     |
+---------------------------------------------------------------------------------------------------+
|  TOPLAM İSTEM BOYUTU: 16,200+ TOKEN!                                                              |
|  Llama-3.1-8B Context Penceresi: 8,192 token -> PATLAMA / TRUNCATION / CONTEXT SATURATION        |
+---------------------------------------------------------------------------------------------------+
```

### 1.1. Prompt Zehirlenmesi ve Bağlam Çözünürlüğü Kaybı (Context Saturation & Attention Dilution)

`ALES/backend/main.py` dosyasındaki `run_agent()` fonksiyonu incelendiğinde (Satır 2225-2318), LLM modeline gönderilmeden önce sistem promptunun içine şunların arka arkaya eklendiği görülür:
1. `BASE_SYSTEM` (Persona tonlaması, sistem talimatları, kimlik tanımları)
2. `lubv` (Kalıcı ek talimatlar)
3. `_lt` (Uzun vadeli hafıza enjeksiyonu)
4. `_lr` (`experience_learner` kuralları)
5. `_cer_inj` (Bağlamsal deneyim tekrarı metinleri)
6. `_muse` (Muse hiyerarşik bellek)
7. `_sc` (Darwin-Gödel evrimsel strateji iskeleleri)
8. `_pdf_intent` gibi dinamik metin kopyaları
9. **Ve en ağırı: 69 adet JSON fonksiyon şeması!**

**Matematiksel ve Algoritmik Çöküş:**
Modern dikkat (Attention) mekanizmalarında bir token'ın diğer token'lar üzerindeki dikkat ağırlığı softmax fonksiyonu ile belirlenir:
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$
Bir modelin bağlam penceresine 15.000 token gürültü, çelişkili talimatlar ("Asla anlatma araç çalıştır", "Önce düşün sonra çalıştır", "Darwin kuralı: pencere odağını kontrol et", "Muse kuralı: önce dosya var mı bak") yığdığınızda, softmax dağılımı aşırı derecede düzleşir (entropy artışı). 

Model, kullanıcının asıl mesajı olan *"bana dünkü satışların raporunu hazırla"* cümlesindeki niyet vektörünü, 69 aracın şeması ve 7 farklı hafıza katmanının gürültüsü arasında kaybeder. Literatürde buna **"Lost in the Middle"** (Liu et al., 2023) fenomeni denir. Model en önemli talimatı kaçırır ve kafası karışarak en düşük riskli eyleme kaçar: **Kullanıcıya standart bir ders metni yazmak!**

### 1.2. Sahte RAG Yanılsaması ve Vektör Veritabanı Yokluğu (The Fake RAG Illusion)

Bir yapay zekanın "zeki" hissettirmesinin 1 numaralı koşulu, kullanıcının geçmişini, dosyalarını ve projelerini kusursuz hatırlamasıdır (Retrieval-Augmented Generation - RAG).

ALES'in `long_term_memory.py` dosyası incelendiğinde trajikomik bir gerçekle karşılaşılmaktadır:
- Kod içinde ChromaDB, Qdrant, Faiss, Milvus, Weaviate veya pgvector gibi endüstri standardı **HİÇBİR vektör arama motoru yoktur**.
- Kodda şu yorum satırı yer almaktadır:
  ```python
  # ASLA cokmez: sqlite-vec eklentisi de, Gemini embedding'i de OPSIYONEL.
  # Ikisi de yoksa yerel (bagimliliksiz) hashing-embedding + Python kosinus kullanir.
  ```
- **"Hashing-Embedding" Nedir?** Metindeki kelimelerin ASCII/MD5/CRC32 toplamlarını alıp rastgele 128 boyutlu bir float dizisine dönüştüren bir parodi algoritmadır!
- Bu algoritmanın semantik (anlamsal) benzerlikle **en ufak bir ilişkisi yoktur**. "Kedi" ile "Köpek" kelimeleri anlamsal olarak birbirine yakındır; ancak hash fonksiyonunda "Kedi" ile "Uçak gemisi" tamamen rastgele bir çakışmayla aynı kovaya düşebilir!
- **Sonuç:** Kullanıcı *"Geçen hafta konuştuğumuz projeyi hatırla"* dediğinde, ALES tamamen alakasız 3 adet çöp satırı sistem promptuna enjekte etmekte; model bu anlamsız bağlamı okuyunca halüsinasyon görmekte ve saçmalamaktadır.

### 1.3. Model Router'ın Sessiz İflası ve "Açıklama Yapan Chatbot" Faciası

Kullanıcının en çok canını yakan sorun: *"PDF yap dedikçe bana Python kodunu anlatıyor, PDF'i üretmiyor!"*

Sorunun kaynağı `backend/main.py` dosyasının 2358-2415 satırları arasında açıkça durmaktadır:
```python
for _ in range(10):
    try:
        msg_content, msg_tool_calls, _used_layer = await stream_via_router(...)
    except model_router.RouterError as e:
        # Zincir tamamen çöktüğünde:
        for name, caller in (("Gemini", multi_agent._call_gemini), 
                             ("SambaNova", multi_agent._call_sambanova), 
                             ("OpenRouter", multi_agent._call_openrouter)):
            ok, text = await caller(convo_text, system)
            if ok:
                final = text + f"\n\n_(⚠️ Ana model zinciri erişilemedi, {name} ile yanıt verildi...)_"
                await websocket.send_json({"type":"message","content":final})
                return
```

**İşte Büyük Fiyasko:**
1. Groq veya Cerebras'ın ücretsiz katmanlarında dakika başına istek (RPM) veya token (TPM) limitleri çok düşüktür.
2. 69 aracın şeması ve devasa prompt Groq'a gönderildiğinde Groq `429 Rate Limit` veya `413 Request Entity Too Large` hatası verir.
3. `stream_via_router` bir `RouterError` fırlatır.
4. Sistem hemen yukarıdaki acil durum yedeğine (`_call_gemini` veya `_call_sambanova`) düşer.
5. **VE BU YEDEK FONKSİYONLAR HİÇBİR FONKSİYON ÇAĞIRMA (TOOL CALL) DESTEĞİNE SAHİP DEĞİLDİR! DÜZ METİN FORMATINDADIR!**
6. Model araç çağırmak istese bile elinde araç şeması yoktur. Model bakar ki PDF üretme aracı yok, mecburen *"PDF üretmek için `reportlab` kütüphanesini kullanabilirsiniz..."* diyerek kullanıcıya ders vermeye başlar.
7. Kullanıcı ise ALES'in neden emri yerine getirmediğini anlayamaz; çünkü sistem sessizce araçsız yedek katmana düşmüştür.

### 1.4. Deterministik FastPath ve Bulanık Bellek Kargaşası

`main.py` içinde LLM çağrılmadan önce çalışan **FastPath** (`fast_path.py`), **Agent JIT** (`agent_jit.py`) ve **Semantic Cache** (`semantic_cache.py`) katmanları yer almaktadır.

Bu katmanlar sözde *"hızlandırma ve maliyet düşürme"* amacıyla konulmuştur. Ancak pratikte:
- **FastPath:** Basit regex ve anahtar kelime eşleştirmesi yapar. Kullanıcı *"Ekran görüntüsü alma sakın, sadece ekran kartımı söyle"* dediğinde, cümledeki "ekran" ve "görüntü" kelimelerini görünce kullanıcının isteğini reddedip ekran görüntüsü almaya kalkar.
- **Semantic Cache:** Cümle vektör benzerliği %85'in üzerindeyse eski cevabı döner. Ancak emir kipleri ve zıtlıklar ("bunu sil" vs "bunu silme") semantik benzerlikte %90 benzer çıkar! ALES bu yüzden silinmemesi gereken bir şeyi silebilir veya eski bir dosyanın içeriğini yeni sanıp dönebilir.

### 1.5. Bağlam Yönetimi ve Kör Token Budama Hataları

ALES, konuşma geçmişini yönetirken şu satırı kullanır:
```python
history = conv_store.get_history_for_model(conv_id, limit=20)
```
Körlemesine "son 20 mesajı al" yaklaşımı ilkel bir yöntemdir.
- Eğer bir önceki adımda `read_file` çalıştırılmış ve 3,000 satırlık bir kod parçası okunmuşsa, o tek mesaj 15,000 token tutar!
- Son 20 mesaj alındığında bağlam penceresi 100,000 token'a fırlar; model çöker.
- Tam tersi durumda; kullanıcı 10 adım önce projenin kritik bir kuralını söylemiştir, 20 mesajlık limit dolunca bu kural unutulur ve model sıfırlanmış gibi davranır.
- Claude Code ise bağlamı **akıllı özetleme (compacting), araç çıktısı budama (tool result trimming) ve kayan pencere (sliding token budget)** ile yönetir. ALES'te bu zeka tamamen eksiktir.

---

## BÖLÜM 2: CLAUDE CODE'UN TERSİNE MÜHENDİSLİĞİ VE AJAN AÇIĞI ANALİZİ

Anthropic tarafından geliştirilen **Claude Code**, yazılım dünyasında devrim yaratmıştır. Birçok kişi Claude Code'un başarısını sadece modelin büyüklüğüne (Claude 3.5 Sonnet) bağlasa da, asıl sır **Ajanik Yürütme Mimarisi'dir (Agentic Execution Architecture)**.

Bizim ALES projesine son eklediğimiz `run_terminal_command`, `read_file` ve `write_file` araçları Claude Code'u taklit etmeye yönelik ilk adımdır; ancak aradaki uçurum henüz kapanmamıştır.

```
+---------------------------------------------------------------------------------------------------+
|                            CLAUDE CODE vs. ALES YÜRÜTME MOTORU KARŞILAŞTIRMASI                   |
+------------------------------------+----------------------------------+---------------------------+
| ÖZELLİK                            | CLAUDE CODE                      | MEVCUT ALES               |
+------------------------------------+----------------------------------+---------------------------+
| Yürütme Döngüsü (ReAct Loop)       | Çok adımlı, durma kriterli ReAct | 10 turluk düz for döngüsü |
| Terminal Mimarisi                  | Durumsal (Stateful PTY Daemon)   | Durumsuz (Stateless Shell)|
| Dosya Düzenleme                    | AST-aware, parçalı patch/diff    | Körlemesine tam dosya ezme|
| Kod Arama & Keşif                  | ripgrep + tree-sitter AST harita | Yok (Kör dosya okuma)     |
| Hata Düzeltme (Auto-Correction)    | Çıktıyı parse edip kendi düzeltir| Hata olunca durur/pes eder|
| Araç Seti Büyüklüğü                | 5-7 Çekirdek Primitif            | 69 Dağınık Şişkin Araç    |
| Terminal Ortamı                    | ANSI terminal emülatörü          | Düz string stdout/stderr  |
+------------------------------------+----------------------------------+---------------------------+
```

### 2.1. Claude Code Otonom ReAct Döngüsünün Mantıksal Anatomisi

Claude Code, kullanıcının isteğini aldığında tek seferde cevap vermez. Aşağıdaki kapalı durum makinesini (Finite State Machine) yürütür:

```
[KULLANICI HEDEFİ] 
       │
       ▼
[FAZ 1: KEŞİF (Inspect & Grep)] ──► Dosya ağacını tara, semantik arama yap, ilgili fonksiyonu bul
       │
       ▼
[FAZ 2: DÜŞÜNME (Plan & Hypothesize)] ──► Hatanın nedenini analiz et, minimal değişiklik planla
       │
       ▼
[FAZ 3: EYLEM (Patch & Write)] ──► Sadece değişen satırları atomik olarak değiştir (Diff formatı)
       │
       ▼
[FAZ 4: TEST VE GÖZLEM (Execute & Observe)] ──► Test komutunu terminalde çalıştır (pytest, npm test)
       │
       ├───► [BAŞARISIZ]: Hata kodunu ve traceback'i oku ──► [FAZ 2'YE DÖN] (Max 15 Döngü)
       │
       └───► [BAŞARILI]: Değişiklikleri git diff ile doğrula ──► [KULLANICIYA RAPORLA]
```

**ALES'teki Eksiklik:**
ALES'teki döngü (`main.py` satır 2357: `for _ in range(10):`) sadece model bir fonksiyon çağırdığında onu çalıştırıp sonucunu modele geri veren ilkel bir "request-response" döngüsüdür. ALES'te bir **"Doğrulama ve Hipotez Testi"** kavramı yoktur. Kod bir hata verirse, ALES genellikle durur veya kullanıcıya *"Terminalde şu hata çıktı, ne yapayım?"* diye sorar. Claude Code ise hatayı asla kullanıcıya sormaz; hatayı analiz eder, kodu düzeltir ve test geçene kadar döngüyü sürdürür.

### 2.2. Araç Primitifleri Karşılaştırması: Claude Code vs. ALES

Claude Code'un araç seti bilinenin aksine devasa değildir. Sadece **5 temel çekirdek araç** üzerine kuruludur:
1. `View`: Dosyayı belirli bir satır aralığında (`offset`, `limit`) okur. 10.000 satırlık dosyayı tek seferde okuyup belleği patlatmaz.
2. `Edit`: Dosyada sadece belirli bir bloğu (`target`) yeni blokla (`replacement`) değiştirir. Dosyanın geri kalanına dokunmaz.
3. `Bash`: Arka planda yaşayan gerçek bir shell oturumunda komut çalıştırır.
4. `Grep`: `ripgrep` motoru ile tüm projede 10 milisaniyede fonksiyon ve değişken arar.
5. `Glob`: Dosya kalıplarını (`**/*.py`, `src/**/*.jsx`) saniyede listeler.

**ALES'in Mevcut Araçları Neden Yetersiz?**
- `read_file`: Dosyanın tamamını tek seferde okumaya çalışır. Büyük bir log dosyasında veya 6,000 satırlık `main.py` üzerinde çağrıldığında token limitini anında doldurur.
- `write_file`: Tüm dosyayı baştan yazar. 2,000 satırlık bir dosyada tek bir satırı değiştirmek için tüm dosyayı yeniden üretir; bu esnada LLM satır atlar, kodu bozar veya parantezleri kapatamaz.
- `run_terminal_command`: Durumsuzdur (stateless).

### 2.3. Durumsal (Stateful) PTY vs. Durumsuz (Stateless) Subprocess

ALES'in en ölümcül terminal açığı buradadır. `main.py` içindeki terminal çalıştırıcı şudur:
```python
res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(root_dir))
```
**Neden Bu Bir Felakettir?**
1. **Dizin Kaybı:** Model `cd backend` komutunu çalıştırır. Komut biter, Python process'i kapanır. Bir sonraki adımda model `python test.py` çalıştırdığında, çalışma dizini tekrar kök dizine dönmüştür! Model dosyanın neden bulunamadığını anlayamaz.
2. **Sanal Ortam (Virtualenv) Kaybı:** Model `source venv/bin/activate` yapar; komut biter bitmez sanal ortam uçup gider! Bir sonraki Python komutu global Python'da çalışır ve paketler bulunamaz.
3. **İnteraktif Komutların Kilitlenmesi:** Bir komut kullanıcıdan onay isterse (`Do you want to continue? [y/N]`), `subprocess.run` kilitlenir ve 45 saniye sonra timeout ile patlar.
4. **Claude Code Nasıl Yapar?** Claude Code, arka planda yaşayan bir **Pseudo-Terminal (PTY Daemon)** çalıştırır. Shell oturumu kapanmaz; `cd` yapıldığında dizin orada kalır, sanal ortam aktif kalır ve interaktif girişler pipe üzerinden gönderilebilir.

### 2.4. Kendi Kendini Düzeltme (Self-Correction / Reflection) Döngüsü

ALES kod tabanında `reflection_agent.py`, `self_heal.py`, `experience_learner.py` gibi gösterişli isimlere sahip dosyalar vardır. Ancak bu dosyaların içeriği incelendiğinde şok edici bir gerçek görülür:
- Bu modüller sadece bir hata olduğunda bir JSON dosyasına hata logu yazmakta ve bir sonraki sefer sistem promptuna *"Geçen sefer şu hata olmuştu, dikkat et"* diye bir cümle eklemektedir.
- **Gerçek Reflection Bu Değildir.**
- Gerçek Reflection; model kod yazdığında arka planda otomatik olarak:
  1. `py_compile` veya `eslint` linter'ı çalıştırmak,
  2. Bir syntax hatası varsa **kullanıcıya hiç göstermeden** LLM'e `"Line 42: SyntaxError: unexpected indent. Fix it immediately."` diyerek hatayı düzelttirmek,
  3. Ardından birim testleri (unit tests) koşturmak ve yeşil ışık yandığında görevi tamamlandı ilan etmektir.

---

## BÖLÜM 3: ALES'İ DÜNYA STANDARDINA TAŞIYACAK 10 EKSİK MİMARİ ÖZELLİK

ALES'in Claude Code, Cursor veya Devin kalitesinde kurumsal bir yazılım ajanı olabilmesi için aşağıdaki 10 mimari modülün sıfırdan inşa edilmesi şarttır:

```
+---------------------------------------------------------------------------------------------------+
|                        ALES 4.0 HEDEF MİMARİSİ (10 ÇEKİRDEK SİSTEM)                              |
+---------------------------------------------------------------------------------------------------+
|  1. Qdrant / SQLite-VSS Tabanlı Gerçek Hibrit Vektör RAG Motoru (BM25 + Dense)                    |
|  2. AST-Aware Parçalı Dosya Düzenleyici (Target-Replacement String Patcher)                       |
|  3. Durumsal (Stateful) PTY Terminal Daemon (Kalıcı Shell, Sanal Ortam ve Dizin Hafızası)         |
|  4. tree-sitter Tabanlı Semantik Kod Haritası (AST Codebase Graph)                                |
|  5. Dinamik Token Bütçeleme ve Akıllı Bağlam Sıkıştırıcı (Context Compactor)                      |
|  6. İki Aşamalı Tembel Araç Dağıtıcısı (Two-Tier Lazy Tool Router: 69 -> 5 Primitif)             |
|  7. Docker / MicroVM Tabanlı Güvenli Kum Havuzu (Isolated Execution Sandbox)                      |
|  8. Çok Dosyalı Atomik İşlem ve Geri Alma Motoru (Atomic Multi-File Rollback / Git Stash)         |
|  9. Otomatik Linter ve Birim Test Doğrulama Kancası (Self-Correction Loop)                        |
| 10. İstemci-Sunucu İkili Ses ve Olay Veriyolu (Binary WebRTC / WebSocket Event Bus)              |
+---------------------------------------------------------------------------------------------------+
```

### 1. Qdrant / SQLite-VSS Tabanlı Gerçek Hibrit Vektör RAG Motoru
Mevcut hashing saçmalığı tamamen çöpe atılmalıdır. Yerel çalışan, C++ bağımlılığı olmayan gömülü bir vektör motoru (`sqlite-vec` veya gömülü `duckdb / qdrant-client`) entegre edilmelidir.
- **Hibrit Arama:** Hem anahtar kelime eşleşmesi (BM25) hem de yoğun vektör araması (Dense Cosine Similarity) birleştirilmelidir.
- **Reranker:** Bulunan en iyi 20 sonuç yerel bir hafif cross-encoder modelinden (örneğin BGE-Reranker) geçirilerek en alakalı 3 bağlam parçası seçilmelidir.

### 2. AST-Aware Parçalı Dosya Düzenleyici (Target-Replacement Patcher)
Bütün dosyayı ezen `write_file` yerine, Claude Code ve Cursor'ın kullandığı string replacement motoru getirilmelidir:
- Parametreler: `file_path`, `target_string`, `replacement_string`.
- Motor, `target_string`'in dosyada tam olarak **tek bir kez** geçtiğini doğrulamalıdır. Eğer birden fazla veya sıfır geçiyorsa işlem reddedilmeli ve modele dosyanın güncel satırları gösterilmelidir. Bu sayede 10.000 satırlık dosyalar 2 saniyede, sıfır token israfıyla ve bozulmadan güncellenir.

### 3. Durumsal (Stateful) PTY Terminal Daemon
Arka planda Python'ın `pty` (Linux/macOS) veya `winpty / ConPTY` (Windows) API'sini kullanan kalıcı bir terminal servisi kurulmalıdır.
- Model `cd` yaptığında oturum o dizinde kalır.
- `venv\Scripts\activate` çalıştırıldığında ortam değişkenleri korunur.
- Çıktılar gerçek zamanlı olarak WebSocket üzerinden frontend'deki `TerminalPanel` bileşenine akıtılır.

### 4. tree-sitter Tabanlı Semantik Kod Haritası (AST Codebase Graph)
ALES, bir projeyi açtığında projedeki tüm sınıfları, fonksiyonları, import ilişkilerini `tree-sitter` kütüphanesi ile ayrıştırıp küçük bir semantik grafa (Code Map) dönüştürmelidir.
- Model, dosyanın 5,000 satırını okumak zorunda kalmaz.
- Modele sadece: `main.py -> class Agent (lines 120-450), def run_agent (lines 1994-2500)` şeklinde 150 token'lık bir iskelet harita verilir. Model hangi satırı okuması gerektiğini nokta atışı bilir.

### 5. Dinamik Token Bütçeleme ve Akıllı Bağlam Sıkıştırıcı (Context Compactor)
Körlemesine `history[-20:]` almak yerine, konuşma geçmişi token bütçesine göre dinamik yönetilmelidir:
- Maksimum konuşma bütçesi: $B_{\text{history}} = \text{Total\_Context} - \text{System\_Prompt} - \text{Max\_Output} - 2000$.
- Eğer konuşma bu bütçeyi aşarsa, en eski mesajlar yerel bir model veya hızlı bir LLM çağrısıyla tek paragraflık bir "Önceki Adımların Özeti" haline getirilir (`Compact Protocol`). Eski araç çıktıları (örneğin 10 sayfalık terminal çıktısı) tek bir satıra indirgenir: `[Terminal: git status çalıştırıldı, 3 dosya değiştirildi]`.

### 6. İki Aşamalı Tembel Araç Dağıtıcısı (Two-Tier Lazy Tool Router)
69 aracın şeması modele aynı anda ASLA verilmemelidir.
- **Aşama 1 (Çekirdek Primitifler):** Modele varsayılan olarak sadece 5 araç verilir: `read_file_range`, `edit_file_block`, `run_terminal`, `search_codebase`, `ask_user`.
- **Aşama 2 (Gerektiğinde Yüklenen Araçlar):** Eğer kullanıcı açıkça bir görsel işleme, masaüstü otomasyonu veya PDF üretimi isterse, o araç dinamik olarak bu 5 aracın yanına eklenir. Böylece modelin dikkat mekanizması asla doyurulmaz.

### 7. Docker / MicroVM Tabanlı Güvenli Kum Havuzu (Execution Sandbox)
Kullanıcının bilgisayarında kontrolsüz shell komutu çalıştırmak ciddi bir güvenlik açığıdır (`rm -rf` veya yanlışlıkla sistem dosyalarını silme riski).
- Kod çalıştırma ve terminal eylemleri Windows üzerinde `WSL2` veya hafif bir Docker konteyneri içinde izole edilmelidir.
- Dosya değişiklikleri bir sanal katmanda (overlay filesystem) yapılmalı, kullanıcı onay verene veya testler geçene kadar ana diske yazılmamalıdır.

### 8. Çok Dosyalı Atomik İşlem ve Geri Alma Motoru (Atomic Transactions & Rollback)
Claude Code bir projede 5 dosyayı değiştirdiğinde ve 4. dosyada hata çıkarsa, projeyi yarım bırakmaz. `git stash` veya bellek içi diff motoru ile yapılan tüm değişiklikleri anında geri alır (Rollback). ALES'e yerel bir Git kancası entegre edilerek, ajanın her eyleminden önce otomatik bir checkpoint (`ales/checkpoint_<timestamp>`) oluşturulmalı, hata anında tek tuşla geri dönülebilmelidir.

### 9. Otomatik Linter ve Birim Test Doğrulama Kancası (Self-Correction Loop)
Ajan bir dosyayı düzenledikten sonra döngüyü sonlandırmadan önce zorunlu olarak iki kanca (hook) çalışmalıdır:
1. **Sözdizimi Doğrulama:** Python için `py_compile`, JS için `esbuild --loader=jsx`. Hata varsa hemen aynı turda modele geri beslenir.
2. **Test Koşumu:** Eğer projede bir test paketi varsa (`pytest`, `npm test`), ilgili test otomatik koşturulur. Test geçmeden kullanıcıya "İş bitti" denmez.

### 10. İstemci-Sunucu İkili Ses ve Olay Veriyolu (Binary WebRTC / Streaming Audio)
Mevcut ses sistemi base64 string'leri üzerinden JSON içinde taşınmaktadır. Bu durum ses paketlerinde %33 ek veri yükü (overhead) yaratmakta ve gecikmeye (latency) yol açmaktadır.
- ElevenLabs veya yerel Edge-TTS sesleri binary stream olarak WebSocket veya WebRTC kanalından doğrudan istemciye akıtılmalıdır. Model ilk cümleyi ürettiği anda (Time-to-First-Audio < 300ms) ses istemcide çalmaya başlamalıdır (ChatGPT Voice Mode standardı).

---

## BÖLÜM 4: KOD TABANI MİMARİ HATALARI VE SPAGETTİ ANALİZİ

ALES kod tabanı, bir yazılım mühendisliği anti-pattern (anti-örnek) dersi gibidir. Kod tabanındaki yapısal çürüme aşağıda somut verilerle listelenmiştir:

### 4.1. `backend/main.py` (6,652 Satır): Monolitik Tasarım Çöküşü
Bir backend uygulamasının tek bir dosyasının 6,652 satır olması kabul edilemez bir mimari hatadır.
- Dosyanın içinde neler var?
  - FastAPI endpoint tanımları (166 adet!)
  - Masaüstü otomasyonu (PyAutoGUI, win32gui kontrolleri)
  - WebSocket bağlantı yöneticisi
  - Prompt şablonları ve formatlama fonksiyonları
  - Model yönlendirme ve acil durum yedekleri
  - Ses üretim ve transkripsiyon fonksiyonları
  - Terminal komut yürütme motoru
  - SQLite profil ve plan entegrasyonları
  - Statik dosya sunucusu
- **Sonuç:** Tek bir satırda yapılan değişiklik (örneğin bir prompt kelimesi), alakasız bir WebSocket bağlantısını veya ses yayınını kırabilmektedir. Dosya tamamen modüler alt router'lara (`routers/chat.py`, `routers/terminal.py`, `routers/profiles.py`, `routers/plans.py`) bölünmelidir.

### 4.2. `frontend/src/App.jsx` (5,981 Satır): Monolitik React İşkencesi
React felsefesi "bileşen tabanlı mimari" (Component-Based Architecture) üzerine kuruludur. Ancak `App.jsx`:
- 5,981 satırdan oluşan devasa tek bir dosyadır!
- İçinde 60'tan fazla `useState`, 25'ten fazla `useEffect` barındırmaktadır.
- Tek bir harf yazıldığında tüm ağaç (Chat, Terminal, Plans, Settings, Log, Worldview) yeniden render edilmekte (unnecessary re-renders), tarayıcıda gözle görülür kasmalar ve bellek sızıntıları yaşanmaktadır.
- CSS stilleri inline objeler (`style={{...}}`) halinde binlerce satıra yayılmıştır. Kodun okunması ve bakımı imkansız hale gelmiştir.
- `TerminalPanel`, `PlansPanel`, `SettingsPanel`, `WorldviewPanel` gibi devasa yapılar ayrı `.jsx` dosyalarına taşınmalı ve bir durum yöneticisi (Zustand veya Redux Toolkit) kurulmalıdır.

### 4.3. `railway/main_cloud.py` (1,075 Satır): DRY Prensibinin Katliamı
Yazılımın temel kuralı **DRY (Don't Repeat Yourself - Kendini Tekrar Etme)** ilkesidir.
- `railway/main_cloud.py`, `backend/main.py` dosyasının elle kırpılmış, kopyala-yapıştır yapılmış bir klonudur.
- `main.py`'da düzeltilen bir hata `main_cloud.py`'da unutulmakta; yerelde çalışan bir özellik Render bulutuna yüklendiğinde çökmektedir.
- Doğru Mimari: Tek bir `app` çekirdeği olmalı, ortam değişkenine (`ENVIRONMENT=cloud` veya `ENVIRONMENT=desktop`) göre masaüstü özellikleri dinamik yüklenmeli (conditional dependency loading), iki ayrı main dosyası tutulmamalıdır!

### 4.4. `model_router.py` (969 Satır) ve `model_registry.py` (1,067 Satır): Aşırı Mühendislik
Yaklaşık 2,050 satır kod sadece hangi modelin canlı olduğunu bulmak ve yönlendirmek için yazılmıştır.
- Kod içinde onlarca gereksiz katman, API kontrolleri ve statik sözlükler vardır.
- Ancak bu devasa kod bütünü, Groq çöktüğünde araçsız düz metin yedeğine düşmek gibi en temel hatayı engelleyememektedir. Basit, dayanıklı ve LiteLLM standardında bir yönlendirici bu 2,050 satırlık karmaşayı 200 satırda çözebilir.

### 4.5. "Hayalet Modüller" (Ghost Modules)
Projede bilimsel makale isimleriyle süslenmiş ancak içi boş veya sadece prompt süsleyen birçok modül bulunmaktadır:
- `darwin_godel.py`: Sözde evrimsel strateji üretir. Yaptığı tek şey JSON'dan bir metin seçip prompta eklemektir.
- `experience_learner.py`: Başarısızlıkları öğrenir denir; tek yaptığı JSON dosyasına kural eklemektir.
- `agent_jit.py`: JIT derleyici denir; sadece daha önce çalışmış bir Python kodunu string olarak önbellekten çağırır.
Bu modüller sistemde gereksiz bir kod karmaşası yaratmakta ve sistemin güvenilirliğini düşürmektedir.

---

## BÖLÜM 5: 4 HAFTALIK TİCARİ DÜZEYE GEÇİŞ YOL HARİTASI

ALES'i amatör bir hobi projesinden, aylık abonelik satılabilecek kurumsal düzeyde bir **"Yapay Zeka Yazılım Mühendisi ve İşletim Sistemi Ajanı"** haline getirmek için 28 günlük radikal yeniden yapılanma planı:

```
[HAFTA 1: BÜYÜK ARINMA VE ÇEKİRDEK MONOLİTİN PARÇALANMASI]
  Gün 1-2: main.py'ın 6 Modüler Router'a Bölünmesi
  Gün 3-4: main_cloud.py Klonunun Yok Edilmesi (Tek Çekirdek Mimari)
  Gün 5-6: 69 Aracın 5 Çekirdek Primitife İndirgenmesi
  Gün 7:   Sistem Promptunun 15.000 Token'dan 1.200 Token'a Sadeleştirilmesi

[HAFTA 2: GERÇEK CLAUDE CODE VE DURUMSAL TERMİNAL MOTORU]
  Gün 8-9:   ConPTY / PTY Tabanlı Kalıcı Shell Daemon Geliştirilmesi
  Gün 10-11: Target-Replacement AST Dosya Düzenleyicisinin Yazılması
  Gün 12-13: 15 Turluk Kendi Kendini Düzelten ReAct Döngüsünün İnşası
  Gün 14:    Git Checkpoint ve Otomatik Rollback Entegrasyonu

[HAFTA 3: VEKTÖR RAG, tree-sitter HARİTASI VE OTOMATİK TEST]
  Gün 15-16: sqlite-vec / Qdrant-Embedded Hibrit Arama Motorunun Kurulması
  Gün 17-18: tree-sitter Kod Haritalama (Codebase Skeleton) Servisi
  Gün 19-20: Linter ve Test Koşucu Otomatik Onarım Kancaları (Auto-Correction)
  Gün 21:    Dinamik Token Sıkıştırıcı (Context Compactor) Entegrasyonu

[HAFTA 4: FRONTEND YENİDEN DOĞUŞU, ULTRA SES VE PROD SÜRÜMÜ]
  Gün 22-23: App.jsx'in Zustand ve Modüler Bileşenlere Ayrılması
  Gün 24-25: WebRTC / Binary WebSocket Üzerinden 250ms Ses Akışı
  Gün 26:    PyInstaller & Docker Çift Dağıtım Paketlemesi
  Gün 27:    Uçtan Uca Stres, Güvenlik ve Bellek Sızıntısı Testleri
  Gün 28:    Ticari v4.0.0 "ALES Core" Sürümünün Canlıya Alınması
```

### Hafta 1: Büyük Arınma, Modüler Ayrıştırma ve Çekirdek Ajan Motoru
- **Gün 1:** `backend/main.py` içindeki 166 endpoint ayrıştırılacak. `backend/routers/` dizini açılarak `chat.py`, `terminal.py`, `plans.py`, `profiles.py`, `desktop.py` ve `system.py` modülleri oluşturulacak.
- **Gün 2:** `main.py` sadece 150 satırlık bir FastAPI başlatıcı ve middleware yöneticisi haline getirilecek.
- **Gün 3:** `railway/main_cloud.py` tamamen silinecek. Tek bir `backend/main.py` üzerinden `ENVIRONMENT` değişkenine göre konfigürasyon yüklenecek.
- **Gün 4:** "Hayalet Modüller" (`darwin_godel`, sahte `cer_module`, şişkin `experience_learner`) çekirdek akıştan çıkarılacak; kod temizliği yapılacak.
- **Gün 5:** 69 adetlik araç karmaşası çöpe atılacak. Claude standardında 5 çekirdek primitif tanımlanacak (`view_file`, `edit_file`, `run_bash`, `search_code`, `finish_task`).
- **Gün 6:** Diğer özel araçlar (PDF üretimi, ekran görüntüsü) "Tembel Araç Dağıtıcısı" (Lazy Tool Registry) altına alınacak; sadece kullanıcı açıkça istediğinde yüklenecek.
- **Gün 7:** Sistem promptundaki 12.000 token'lık gürültü temizlenecek. Claude Code'un yalın, sert ve net 1.200 token'lık meta-promptu sisteme entegre edilecek.

### Hafta 2: Gerçek Claude Code Motoru ve Durumsal PTY Terminal Mimarisi
- **Gün 8:** Python `winpty` ve `ptyprocess` kütüphaneleriyle kalıcı bir terminal oturumu (`terminal_daemon.py`) yazılacak.
- **Gün 9:** Shell oturumunun ortam değişkenlerini, dizinini (`cwd`) ve sanal ortamını oturum boyunca koruması sağlanacak.
- **Gün 10:** Kör dosya ezme (`write_file`) kaldırılacak; `edit_file_block(path, target, replacement)` fonksiyonu geliştirilecek.
- **Gün 11:** Çoklu eşleşme veya hedef bulunamama durumlarında modelin önüne diff çıkaran hata mekanizması kurulacak.
- **Gün 12:** `run_agent()` içindeki for döngüsü yerine gerçek bir `ReActAgentLoop` sınıfı yazılacak.
- **Gün 13:** Model bir terminal komutu veya kod değişikliği yaptığında çıktıyı inceleyecek; hata varsa kendi kendine 10 tura kadar düzeltecek.
- **Gün 14:** Her ajan görevinden önce görünmez bir `git stash / branch` checkpoint mekanizması kurulacak; başarısız görevler tek tıkla geri alınacak.

### Hafta 3: Gerçek Vektör RAG, tree-sitter Kod Haritası ve Otomatik İyileştirme
- **Gün 15:** `long_term_memory.py` içindeki hash fonksiyonu silinecek; C bağımlılığı olmayan yerel `sqlite-vec` entegrasyonu tamamlanacak.
- **Gün 16:** Kullanıcı konuşmaları ve proje dokümanları gerçek embedding modelleriyle (`text-embedding-3-small` veya yerel ONNX MiniLM) indekslenecek.
- **Gün 17:** `tree-sitter` kütüphanesi backend'e eklenecek. Bir proje açıldığında tüm fonksiyon ve sınıfların iskelet haritası (Codebase Skeleton) 5 saniyede çıkarılacak.
- **Gün 18:** Modele tüm dosyalar yerine sadece bu harita verilecek; model ihtiyacı olan fonksiyonu satır aralığıyla çağıracak.
- **Gün 19:** Dosya düzenleme sonrası çalışan otomatik `LinterHook` (`flake8 / eslint`) yazılacak. Model syntax hatası yaparsa kullanıcı görmeden düzeltilecek.
- **Gün 20:** Otomatik birim test koşucu entegre edilecek; model yazdığı kodun testini geçirmek zorunda bırakılacak.
- **Gün 21:** Dinamik `ContextCompactor` yazılarak, konuşma 16.000 token'ı aştığında eski araç çıktıları otomatik özetlenecek.

### Hafta 4: Modern React Mimarisi, Ultra-Gerçekçi Ses ve Ticari Kararlılık
- **Gün 22:** `frontend/src/App.jsx` parçalanacak. `components/Terminal/`, `components/Plans/`, `components/Chat/`, `components/Settings/` dizinleri kurulacak.
- **Gün 23:** Global durum yönetimi için `Zustand` kurulacak; gereksiz re-render'lar engellenecek, arayüz 60 FPS akıcılığa kavuşacak.
- **Gün 24:** Ses altyapısı base64 JSON'dan çıkarılıp saf ikili (binary audio stream) formatına geçirilecek.
- **Gün 25:** İlk kelime üretildiği anda sesin çalmaya başladığı ultra-düşük gecikmeli (<300ms) ses motoru tamamlanacak.
- **Gün 26:** Electron masaüstü sürümü PyInstaller ile paketlenecek; bulut sürümü için Dockerfile.cloud optimize edilecek.
- **Gün 27:** 24 saatlik kesintisiz yük testi, bellek sızıntısı (memory leak) analizi ve güvenlik audit'i yapılacak.
- **Gün 28:** ALES v4.0.0 ticari sürümü GitHub ve Render üzerinde canlıya alınacak; manifestodaki tüm hedefler doğrulanacak.

---

## SONUÇ VE NİHAİ MİMARİ TAAHHÜT

ALES'in şu anki hali, **"aşırı karmaşıklaştırılmış ama temel dinamikleri henüz oturmamış"** bir sistemdir. Geliştirici ekibi ve önceki yapay zeka ajanları, sisteme sürekli yeni modül isimleri (Darwin-Gödel, CER, FastPath, JIT, Meclis, MoA) ekleyerek sistemin daha akıllı olacağını sanmıştır; ancak tam tersine sistemi bir **token bataklığına** sürüklemişlerdir.

Gerçek güç, karmaşıklıkta değil; **kusursuz primitiflerde, durumsal (stateful) yürütmede, temiz bir bağlam yönetiminde ve kendi kendini düzelten kapalı döngülerdedir.**

Bu manifestoda belirtilen 4 haftalık yol haritası harfiyen uygulandığında, ALES sadece bir chatbot olmaktan çıkacak; **herhangi bir kod tabanını okuyan, hatayı bulan, kodu yazan, terminalde test eden ve hatasız teslim eden dünya standartlarında bir Ajanik İşletim Sistemi'ne** dönüşecektir.
