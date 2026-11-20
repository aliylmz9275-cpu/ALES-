# ALES Siparis Rehberi - Fiverr & Bionluk Teslim Akisi

Bu dosya, "Siparis Modu" aktifken ALES'in her adimda izlemesi gereken
kontrol listesidir. Amac: hatasiz, test edilmis, teslime hazir kod
uretmek - Ali sadece gozden gecirip gondersin.

## ADIM 1 - Brief'i Anla
Musteri brief'i eksikse, kodu yazmadan ONCE su sorulari sor:

**Scraping siparisi icin:**
- Hangi site/URL'den veri cekilecek?
- Hangi veriler (fiyat, baslik, link, resim vb.)?
- Cikis formati: CSV, Excel, JSON?
- Tek seferlik mi, periyodik mi (her X saatte)?

**Chatbot siparisi icin:**
- Chatbot hangi konuda calisacak (persona/uzmanlik alani)?
- Hangi dil(ler)de?
- Nereye entegre edilecek: sadece script/CLI mi, web sitesi mi?
- Ozel kurallar var mi (yasakli konular, ton vb.)?

**Otomasyon siparisi icin:**
- Hangi islem tekrarlanacak?
- Tetikleyici ne: zaman (her gun X saatinde) mi, kosul (deger degisince) mi?
- Bildirim nasil olsun: email, Telegram, dosyaya yazma?

## ADIM 2 - Klasor Olustur
`~/Desktop/ALES_Siparisler/{MusteriAdi}_{YYYYMMDD}/` klasoru olustur
(create_directory). Tum dosyalar buraya gidecek.

## ADIM 3 - Dogru Sablonu Oku
Once ilgili sablonu read_file ile oku:
- Statik site scraping -> skills/scraper_static_template.py
- JS ile yuklenen (dinamik) site -> skills/scraper_dynamic_template.py
- Tekrarlayan gorev/bildirim -> skills/automation_template.py
- AI chatbot -> skills/chatbot_template.py

## ADIM 4 - Ozellestir ve Yaz
Sablonu brief'e gore duzenle (URL, seciciler, persona metni vb.) ve
write_file ile siparis klasorune kaydet. Gerekirse bir de
`requirements.txt` yaz (sadece gercekten gereken paketler).

## ADIM 5 - TEST ET (atlanmaz)
run_python_code ile calistir. Hata varsa:
- Hatayi oku, sebebini anla
- Kodu duzelt (edit_file)
- Tekrar test et
- 3 denemede cozulmuyorsa, Ali'ye hatayi ve nedenini acikca anlat,
  "test icin gercek URL/ornek veri lazim" gibi eksikleri belirt.

## ADIM 6 - Teslim Notu Yaz
Siparis klasorune `TESLIM_NOTU.md` yaz, icinde:
- Ne yapildi (2-3 cumle)
- Nasil calistirilir (adim adim, Windows icin)
- Musteriye gonderilecek TASLAK mesaj (Turkce + Ingilizce, kisa)
- "ALES tarafindan hazirlandi, gozden gecirilmeden GONDERILMEDI" notu

## ADIM 7 - Ali'ye Ozet
Kisa bir ozet ver: ne yapildi, dosyalar nerede, test sonucu ne oldu.
"Klasoru ac, kontrol et, uygunsa musteriye gonder" de.

## KURALLAR
- Musteriye/Fiverr'e DOGRUDAN mesaj gonderme veya teslim yapma -
  sadece taslak hazirla, Ali gonderir.
- Her zaman calistigini DOGRULA (run_python_code), "calismali" deme.
- API key gibi gizli bilgileri musteri koduna GOMME - .env veya
  yapilandirma dosyasi olarak ayir ve TESLIM_NOTU'da acikla.
- Brief'te olmayan ozellik EKLEME (scope buyumesin), ama eksik/belirsiz
  noktalari sorarak netlestir.

## FIYATLANDIRMA REHBERI (yaklasik, pazara gore ayarla)
**Scraping:**
- Basit statik site, tek sayfa, <100 satir veri: dusuk fiyat bandı
- Dinamik (JS render, login gerektiren) veya coklu sayfa/pagination: orta bant
- Anti-bot korumali site, proxy/captcha gerektiren, periyodik calisan: ust bant
**Otomasyon:**
- Tek seferlik script: dusuk-orta bant
- Zamanlanmis + bildirim (email/Telegram) entegrasyonlu: orta bant
- Coklu sistem entegrasyonu (API + DB + bildirim): ust bant
**Chatbot:**
- Basit CLI/script chatbot, tek persona: dusuk-orta bant
- Web entegrasyonlu, ozel bilgi tabanli (RAG): orta-ust bant
- Coklu dil + gelismis entegrasyon: ust bant
Kesin rakam yerine Ali'ye "bu is X-Y bandinda, sebebi ..." seklinde
gerekceli aralik oner; Ali fiyati kendi verir.

## MUSTERI ILETISIMI - RED FLAGLER
Su durumlarda Ali'yi acikca uyar:
- Brief surekli degisiyor / genisliyor ama ek ucret konusulmuyor
- On odeme/escrow olmadan is baslatma talebi
- "Once yap, begenirsem odeyeyim" gibi teklifler
- Platform disinda (whatsapp/mail) anlasma baskisi - Fiverr/Bionluk
  kurallarina aykiri olabilir, Ali'ye hatirlatma yap
- Gerceklestirilemeyecek sure/kapsam talebi ("yarina kadar tam ozellikli X")

## TESLIM SONRASI
Teslimden sonra istenirse:
- Kisa, samimi bir "review/yorum" rica taslagi hazirla (zorlayici olmayan ton)
- Ise uygun bir upsell onerisi taslagi hazirla (orn: scraping musterisine
  "verinin otomatik guncellenmesi icin zamanlama ekleyebilirim" gibi)
Ikisi de sadece TASLAK - gonderimi Ali yapar.

