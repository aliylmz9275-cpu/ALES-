---
id: youtube_oynatici
name: YouTube Oynatici
description: Istenen video/sarkiyi YouTube'da bulur ve dogrudan oynatmaya baslar (arama sayfasinda birakmaz, ilk sonucun watch linkini acar).
keywords: [youtube, video, izlet, izle, oynat, çal, muzik, müzik, şarkı, sarki, clip, klip]
enabled: true
---
# YouTube Oynatici

Bu skill ALES'e "youtube'da X videosunu ac/izlet/oynat" gibi isteklerde
gercekten bir video oynatma yetenegi kazandirir.

## Nasil calisir
1. `play_youtube_video(query)` cagrildiginda, YouTube arama sonuc sayfasi
   hafifce cekilir (httpx ile), ilk video sonucunun `watch?v=...` linki
   regex ile bulunur.
2. Bulunan link `webbrowser.open()` ile kullanicinin varsayilan
   tarayicisinda acilir → video otomatik oynamaya baslar (YouTube'un
   kendi autoplay davranisi).
3. Ilk sonuc bulunamazsa (YouTube sayfa yapisini degistirmis olabilir)
   arama sonuc sayfasi acilir, kullanici kendisi secer.

## Araclar
- `play_youtube_video(query)` — video ara ve oynat
- `search_youtube(query)` — sadece sonuc basliklarini/linklerini dondur (oynatmadan)

## Genisletme fikri
Ayni sablonu kopyalayip baska bir "medya oynatici" skill'i yapabilirsin
(orn. Spotify web player, bir podcast sitesi, kurum-ici bir video portali).
Sadece yeni bir klasor + SKILL.md + skill.py yeterli, ALES otomatik kesfeder.
