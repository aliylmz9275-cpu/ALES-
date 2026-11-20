// ALES PWA service worker
// Amac: telefonda "ana ekrana ekle" ile gercek bir uygulama gibi
// acilabilmek icin gereken minimum sart (fetch handler + manifest).
// Sohbet/WS trafigi CANLI kalmali, o yuzden sadece STATIK dosyalari
// (html/js/css/icon) onbellekliyoruz - API/WS istekleri her zaman
// direkt aga gidiyor.

const CACHE_NAME = 'ales-shell-v3'
const SHELL_FILES = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)).catch(() => {})
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)

  // GET olmayan her sey (POST /big-ales, POST /puter-bridge/result ...)
  // dogrudan aga gider.
  if (event.request.method !== 'GET') return

  // GIRIS BELGESI (index.html): once AG, onbellek yalnizca yedek.
  //
  // NEDEN: index.html icinde hash'li paket adi var
  // (./assets/index-<hash>.js). Onbellekten donerse arayuz yeniden
  // derlendikten sonra bile ESKI hash istenir ve kullanici ne yaparsa
  // yapsin eski arayuzu gorur. ALES.exe arayuzu http://localhost uzerinden
  // servis ettigi icin bu service worker artik MASAUSTUNDE de calisiyor
  // (Electron file:// ile hic kaydolmuyordu) -- yani bu tuzak once yoktu.
  // Cevrimdisi PWA davranisi korunuyor: ag yoksa onbellege dusuyoruz.
  const isDoc = event.request.mode === 'navigate' ||
                url.pathname === '/' ||
                url.pathname.endsWith('/index.html')
  if (isDoc) {
    event.respondWith(
      fetch(event.request).then((res) => {
        if (res && res.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, res.clone()))
        }
        return res
      }).catch(() => caches.match(event.request).then((c) => c || caches.match('./index.html')))
    )
    return
  }

  // ─── NE ONBELLEKLENIR: BEYAZ LISTE, KARA LISTE DEGIL ──────────────
  // ESKIDEN burada "su API yollari haric hepsini onbellekle" yazan bir
  // KARA LISTE vardi (/status, /config, /conversations, ...). Iki sebeple
  // yanlisti:
  //   1. Liste eksikti. /modes, /big-ales, /system/status, /jit/graphs,
  //      /puter-bridge/job/<id> ... hepsi GET ve hicbiri listede yoktu ->
  //      "statik dosya" sayilip ONBELLEKTEN ONCE donuyorlardi. Yani
  //      Ayarlar paneli donmus bir Puter oturumu/devre kesici durumu
  //      gosterirdi ve kullanici bunu asla anlayamazdi.
  //   2. Her yeni API ucu bu listeye eklenmeyi bekliyordu -- unutmasi
  //      kolay, farketmesi cok zor bir bakim borcu.
  // Artik yalnizca GERCEKTEN STATIK gorunen yollar onbelleklenir: /assets/
  // altindakiler ve bilinen dosya uzantilari. API uclarinin uzantisi yok,
  // bu yuzden hicbiri buraya giremez.
  const isStatic = url.pathname.startsWith('/assets/') ||
    /\.(js|mjs|css|png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|eot|map|json|txt|webmanifest)$/i
      .test(url.pathname)
  if (!isStatic) return          // API/dinamik: her zaman ag, onbellek YOK

  // Statik dosyalar: onbellek varsa hizlica onu don, arka planda tazele.
  // Paket dosyalarinin adi hash'li oldugu icin icerik degisince ad da
  // degisir -- yani burada onbellek once gelmesi guvenli.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request).then((res) => {
        if (res && res.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, res.clone()))
        }
        return res
      }).catch(() => cached)
      return cached || network
    })
  )
})
