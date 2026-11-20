---
id: medya_kontrolu
name: Medya/Spotify Kontrolü
description: Oynatma/durdurma, sonraki/önceki parça, ses seviyesi - Spotify, YouTube veya odaktaki HERHANGİ bir medya uygulamasında çalışır.
keywords: [spotify, müzik, sarki, şarkı, çal, durdur, duraklat, sonraki parça, önceki parça, ses aç, ses kıs, oynat, pause]
enabled: true
---
# Medya/Spotify Kontrolü

İşletim sisteminin medya tuşlarını (Play/Pause, Next, Previous, Volume)
simüle eder - bu yüzden Spotify masaüstü uygulaması, YouTube (tarayıcıda),
ya da başka herhangi bir medya oynatıcısı neyse ODAKTA/etkin olan onu
kontrol eder. Spotify hesabına özel OAuth gerektirmez, anında çalışır.

## Araçlar
- `media_play_pause()` — oynat/duraklat
- `media_next()` — sonraki parça
- `media_previous()` — önceki parça
- `media_volume_up()` / `media_volume_down()` — ses seviyesi

## Not
Belirli bir şarkıyı ARAYIP çalmak istersen (örn. "Spotify'da X şarkısını
çal") bu skill değil, `youtube_oynatici` skill'i ya da Connectors
panelinden açacağın gerçek Spotify Web API bağlantısı (`call_connector`)
daha uygun - bu skill sadece oynatma/duraklatma/geçiş kontrolü yapar.
