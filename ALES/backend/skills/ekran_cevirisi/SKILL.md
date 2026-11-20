---
id: ekran_cevirisi
name: Ekran Çevirisi
description: Ekrandaki (aktif pencere) yabancı dildeki yazıyı anında hedef dile çevirir.
keywords: [çevir, çeviri, translate, ne demek, ekrandaki yazıyı çevir, ingilizce çevir]
enabled: true
---
# Ekran Çevirisi

"Ekrandaki yazıyı çevir", "bu ne demek", "İngilizce'den çevir" gibi
isteklerde kullanılır.

## Nasıl çalışır
1. Aktif pencerenin görüntüsü alınır (varsayılan - hızlı).
2. Önce yerel OCR (Tesseract) ile metin çıkarılmaya çalışılır (hızlı,
   ağ gerektirmez).
3. OCR metin bulursa, o metin Groq ile (hızlı) hedef dile çevrilir.
4. OCR kurulu değilse/metin bulamazsa, doğrudan vision modeline
   "ekrandaki yazıyı oku ve çevir" diye sorulur (tek adımda hem okuma
   hem çeviri) - `vision.py`'deki hızlı-önce-yerel-sonra-bulut zincirini
   kullanır.

## Araçlar
- `translate_screen(target_language)` — varsayılan hedef dil Türkçe
