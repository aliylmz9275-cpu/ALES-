const { contextBridge, ipcRenderer } = require('electron')

// ─── KOPRU YALNIZCA ALES'IN KENDI SAYFASINA KURULUR ────────────────────
// NEDEN BU KAPI VAR: Electron'da window.open ile acilan COCUK PENCERE,
// ust pencerenin webPreferences'ini -- PRELOAD DAHIL -- devralir. Big ALES
// icin Puter girisi tam olarak boyle bir pencere aciyor ve o pencerede
// puter.com yukleniyor. Kapi olmadan asagidaki koprü UZAK BIR SITEDE de
// tanimli olurdu, yani puter.com sayfasi window.ales.loadConfig() cagirip
// config.json'daki CANLI API ANAHTARLARINI okuyabilir, saveConfig ile
// uzerine yazabilir, quit ile uygulamayi kapatabilirdi.
//
// BU ACIK ONCE DE VARDI AMA ULASILAMAZDI: arayuz file:// kaynagindan
// aciliyordu, orada puter.js kimlik dogrulamasi hic baslamiyordu
// ("Unsupported Protocol - file://") ve giris penceresi hic acilmiyordu.
// Arayuz artik http://localhost:8000 uzerinden yuklendigi icin (bkz.
// electron-main.js) o pencere GERCEKTEN aciliyor -- yani kapi artik
// zorunlu.
//
// Ikinci savunma katmani electron-main.js icindeki setWindowOpenHandler:
// cocuk pencerede webSecurity'yi geri aciyor ve devTools'u kapatiyor.
// Ikisi birlikte duruyor cunku bu kapi Electron'un webPreferences birlestirme
// davranisina HIC guvenmiyor: preload yine devralinsa bile burada duruyoruz.
const TRUSTED_ORIGIN = (() => {
  try {
    const u = new URL(window.location.href)
    // Arayuzu backend servis ediyor: 127.0.0.1/localhost. Port'a
    // bakmiyoruz -- gelistirmede vite 5173, urunde backend 8000.
    if (u.protocol === 'http:' || u.protocol === 'https:') {
      return u.hostname === 'localhost' || u.hostname === '127.0.0.1' ||
             u.hostname === '[::1]' || u.hostname === '::1'
    }
    // Eski/yedek yerlesim: index.html dogrudan dosyadan acilirsa arayuzun
    // pencere dugmeleri yine calissin. Uzak bir site file:// olamaz.
    return u.protocol === 'file:'
  } catch (e) {
    return false
  }
})()

if (TRUSTED_ORIGIN) {
  contextBridge.exposeInMainWorld('ales', {
    close: () => ipcRenderer.send('window-close'),
    minimize: () => ipcRenderer.send('window-minimize'),
    toggleFloat: () => ipcRenderer.send('window-toggle-float'),
    quit: () => ipcRenderer.send('window-quit'),
    onModeChange: (cb) => ipcRenderer.on('mode-change', (_, mode) => cb(mode)),
    saveConfig: (data) => ipcRenderer.invoke('save-config', data),
    loadConfig: () => ipcRenderer.invoke('load-config'),
    isElectron: true,
  })
}
