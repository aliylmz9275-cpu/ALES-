---
id: panoya_erisim
name: Panoya Erişim
description: Panoya (clipboard) kopyalanan metni okur ve panoya yeni metin yazar.
keywords: [pano, clipboard, kopyala, kopyaladığım, yapıştır, kopyalanan]
enabled: true
---
# Panoya Erişim

"Az önce kopyaladığım şeyi not al", "panoya şunu kopyala", "kopyaladığım
linki aç" gibi isteklerde kullanılır.

## Araçlar
- `read_clipboard()` — panodaki güncel metni okur
- `write_clipboard(text)` — panoya yeni bir metin yazar

## Nasıl çalışır
Önce `pyperclip` kütüphanesi denenir (requirements.txt'te var), o
başarısız olursa (nadir durumlarda) `tkinter` üzerinden yedek bir yol
denenir - ekstra kurulum gerekmez.
