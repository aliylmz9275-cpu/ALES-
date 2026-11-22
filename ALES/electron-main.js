const { app, BrowserWindow, Tray, Menu, globalShortcut, ipcMain, screen, dialog, session } = require('electron')
const path = require('path')
const { spawn, execSync } = require('child_process')
const fs = require('fs')

app.commandLine.appendSwitch('force-device-scale-factor', '1')

let mainWindow = null
let tray = null
let backendProcess = null
let isFloating = false

// ─── LOG ─────────────────────────────────────────────────────────
// Daha once bir sorun cikinca "hicbir sey olmadi" hissi veriyordu,
// cunku hata sadece konsola yaziliyordu ve normal (cift tik) baslatmada
// konsol gorunmuyor. Artik her seyi ayrica bir log dosyasina da yaziyoruz
// ve kritik hatalarda gorunur bir dialog gosteriyoruz.
function getLogPath() {
  try { return path.join(app.getPath('userData'), 'ales-electron.log') }
  catch (e) { return path.join(require('os').tmpdir(), 'ales-electron.log') }
}
function log(...args) {
  const line = `[${new Date().toISOString()}] ${args.join(' ')}`
  console.log(line)
  try {
    const p = getLogPath()
    fs.mkdirSync(path.dirname(p), { recursive: true })
    fs.appendFileSync(p, line + '\n')
  } catch (e) {}
}

// Herhangi bir yerde yakalanmamis hata olursa artik sessizce kapanmak
// yerine gorunur bir hata penceresi gosteriyoruz. showErrorBox app hazir
// olmadan da cagrilabilir, bu yuzden en erken asamadaki hatalari da yakalar.
process.on('uncaughtException', (err) => {
  log('[FATAL] Yakalanmamis hata:', err?.stack || String(err))
  try {
    dialog.showErrorBox(
      'ALES baslatilamadi',
      `Beklenmeyen bir hata olustu:\n\n${err?.message || err}\n\n` +
      `Detay log: ${getLogPath()}`
    )
  } catch (e) {}
})
process.on('unhandledRejection', (reason) => {
  log('[FATAL] Yakalanmamis promise reddi:', reason?.stack || String(reason))
})

function getBackendPath() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'ales-backend.exe')
  return null
}

function getConfigPath() {
  return path.join(app.getPath('userData'), 'config.json')
}

function startBackend() {
  if (process.platform === 'win32') {
    try {
      const out = execSync('netstat -ano | findstr :8000').toString()
      for (const line of out.trim().split('\n')) {
        if (line.includes('LISTENING')) {
          const parts = line.trim().split(/\s+/)
          const pid = parts[parts.length - 1]
          if (pid && pid !== '0' && pid !== String(process.pid)) {
            log('[ALES] Port 8000 zombi süreç temizleniyor, PID:', pid)
            try { execSync('taskkill /pid ' + pid + ' /T /F') } catch (e) {}
          }
        }
      }
    } catch (e) {}
  }

  const exePath = getBackendPath()
  const backendDir = app.isPackaged ? process.resourcesPath : path.join(__dirname, 'backend')
  const configPath = getConfigPath()

  if (fs.existsSync(configPath)) {
    try { fs.copyFileSync(configPath, path.join(backendDir, 'config.json')) } catch(e) {}
  }

  if (exePath && app.isPackaged && !fs.existsSync(exePath)) {
    // En sik gorulen sebep: Windows Defender/antivirus PyInstaller ile
    // yapilmis exe'leri yanlislikla virus sanip sessizce silmis/karantinaya
    // almis olabilir. Once bunu acikca bildir, sonra da denemeye devam et.
    log('[HATA] ales-backend.exe bulunamadi:', exePath)
    dialog.showErrorBox(
      'ALES Backend Bulunamadi',
      `Beklenen konumda backend dosyasi yok:\n${exePath}\n\n` +
      `Bu genellikle Windows Defender/antivirus'un PyInstaller ile ` +
      `derlenmis exe'yi yanlislikla virus sanip silmesinden/karantinaya ` +
      `almasindan kaynaklanir.\n\nWindows Guvenligi > Virus ve tehdit ` +
      `korumasi > Koruma gecmisi'ni kontrol et, gerekirse ALES kurulum ` +
      `klasorunu antivirus istisna listesine ekleyip yeniden kur.`
    )
  }

  // ─── TARAYICI ACILMASINI ENGELLE ────────────────────────────────
  // main.py acilista _open_browser_when_ready() cagiriyor ve VARSAYILAN
  // olarak sistem tarayicisini http://localhost:8000 adresinde aciyor.
  // Bu env degiskeni verilmezse cift tiklamada Electron penceresinin
  // YANINDA bir de tarayici sekmesi aciliyor -- "tarayici YOK" sartinin
  // ihlali. spawn'a env GECMEDIGIMIZ surece cocuk sureç Electron'un
  // env'ini aynen devralir, yani bayrak buradan verilmek ZORUNDA.
  const backendEnv = Object.assign({}, process.env, {
    ALES_NO_BROWSER: '1',
    PYTHONIOENCODING: 'utf-8',
  })

  try {
    if (exePath && fs.existsSync(exePath)) {
      backendProcess = spawn(exePath, [], {
        cwd: backendDir, stdio: 'pipe', windowsHide: true, env: backendEnv
      })
    } else {
      const pythonCmd = process.platform === 'win32' ? 'python' : 'python3'
      backendProcess = spawn(pythonCmd, [path.join(__dirname, 'backend', 'main.py')], {
        cwd: path.join(__dirname, 'backend'), stdio: 'pipe',
        windowsHide: true, env: backendEnv
      })
    }
  } catch (e) {
    log('[HATA] Backend spawn edilemedi (senkron):', e?.stack || String(e))
    return
  }

  // KRITIK DUZELTME: spawn() ENOENT gibi hatalarda senkron degil,
  // ASENKRON 'error' event'i ile bildirir. Bu event dinlenmezse
  // Node.js unhandled 'error' event'i icin surecin tamamini SESSIZCE
  // sonlandirir - pencere hic acilmadan, hicbir mesaj gostermeden.
  // "kuruluyor ama acilmiyor" sikayetinin en olasi sebebi buydu.
  backendProcess.on('error', (err) => {
    log('[HATA] Backend process baslatilamadi:', err?.stack || String(err))
    dialog.showErrorBox(
      'ALES Backend Baslatilamadi',
      `Backend surecini baslatirken hata olustu:\n${err?.message || err}\n\n` +
      `Antivirus/Defender engelliyor olabilir. Kurulum klasorunu ` +
      `istisna listesine eklemeyi dene.`
    )
  })

  backendProcess.stdout?.on('data', d => log('[ALES BACKEND]', d.toString().trim()))
  let portConflictShown = false
  backendProcess.stderr?.on('data', d => {
    const text = d.toString().trim()
    log('[ALES BACKEND ERR]', text)
    // "10048" = Windows'ta "adres zaten kullaniliyor" hata kodu (locale'e
    // gore mesaj Turkce de olabilir, o yuzden metne degil koda bakiyoruz).
    // En sik sebebi: onceki bir ALES denemesinden kalma "zombi" backend
    // sureci hala 8000 portunu tutuyor.
    if (!portConflictShown && (text.includes('10048') || text.includes('Address already in use'))) {
      portConflictShown = true
      dialog.showErrorBox(
        'ALES Portu Meşgul',
        'Backend 8000 portuna baglanamadi. Muhtemelen onceki bir ALES ' +
        'denemesinden kalan bir surec hala calisiyor ve portu tutuyor.\n\n' +
        'Gorev Yoneticisi > Detaylar sekmesinden "ales-backend.exe" ve ' +
        '"ALES.exe" olarak gorunen tum surecleri sonlandirip tekrar dene.'
      )
    }
  })
  backendProcess.on('close', code => log('[ALES BACKEND] kapandi:', code))
}

function createMainWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  mainWindow = new BrowserWindow({
    width, height,
    frame: false,
    transparent: false,
    backgroundColor: '#000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      zoomFactor: 1.0,
      // URUNDE DevTools KAPALI. Gelistirmede acik kaliyor, yoksa
      // "beyaz pencere" gibi bir arizayi tesbit etmenin yolu kalmaz.
      devTools: !app.isPackaged,
    },
    show: false,
    icon: path.join(__dirname, 'assets', 'icon.png'),
  })

  // Mikrofon ve Medya İzinleri (STT / MediaRecorder için kesin izin)
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(true)
  })
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    return true
  })

  // devTools:false tek basina YETMEZ: Ctrl+Shift+I / F12 kisayollari
  // Electron'un varsayilan menusunden gelir ve menu bu pencerede
  // frame:false olsa bile etkin kalir. Urunde menuyu tamamen
  // kaldiriyoruz; ALES'in kendi baslik cubugu React tarafinda.
  if (app.isPackaged) {
    Menu.setApplicationMenu(null)
    mainWindow.webContents.on('before-input-event', (event, input) => {
      const k = (input.key || '').toLowerCase()
      const devCombo =
        k === 'f12' ||
        (input.control && input.shift && (k === 'i' || k === 'j' || k === 'c')) ||
        (input.control && k === 'r') ||        // yeniden yukleme: durumu siler
        (input.control && k === 'u')           // kaynak goruntuleme
      if (devCombo) event.preventDefault()
    })
    // Bir eklenti/uzanti yine de acmayi denerse aninda kapat.
    mainWindow.webContents.on('devtools-opened', () => {
      mainWindow.webContents.closeDevTools()
    })
  }

  // ─── ARAYUZ NEREDEN YUKLENIR ──────────────────────────────────────
  // ESKIDEN: app.isPackaged icin loadFile(dist/index.html), yani sayfa
  // file:// kaynagindan aciliyordu. Puter.js TAM BURADA patliyor:
  // "Unsupported Protocol - file://". Sebep teknik ve kalici: puter.js
  // kimlik dogrulamasi puter.com'a acilan bir pencere + postMessage
  // uzerine kurulu ve jetonu KAYNAGA BAGLI bir depoda tutuyor. file://
  // ise "opaque origin"dir -- kaynak "null" gorunur ve jetonun
  // yasayacagi bir depo yoktur. Yani file:// ile Big ALES hicbir zaman
  // calisamaz; bu bir ayar sorunu degil, protokol sorunudur.
  //
  // SIMDI: arayuz backend'in KENDI http kaynagindan yukleniyor
  // (http://localhost:8000) -- gercek bir origin, gercek bir depo.
  //
  // BUNUN CALISMASI ICIN GEREKEN IKINCI PARCA: backend'in derlenmis
  // arayuzu BULABILMESI. Paketlenmis halde dist/ app.asar icinde durur,
  // ales-backend.exe ise resources/ icinde -- yani main.py'nin
  // _find_webui_dir() adaylari HICBIRINI tutmuyordu ve backend yalnizca
  // API servis ederdi (pencere JSON hata metni gosterirdi). Bu yuzden
  // dist/ artik extraResources ile exe'nin YANINA da kopyalaniyor
  // (package.json), boylece <resources>/dist adayi tutuyor.
  const UI_URL = 'http://localhost:8000'
  const targetURL = 'http://localhost:8000'

  const indexPath = path.join(__dirname, 'dist', 'index.html')
  // Backend'in servis edecegi kopya. YOKSA pencere bos degil ama
  // KULLANILAMAZ olur (main.py: WEBUI_DIR None -> 503 JSON). Sessiz
  // gecmiyoruz, cunku electron-builder eksik bir extraResources
  // kaynagini SESSIZCE atlar ve 0 ile ciker.
  const resIndex = app.isPackaged
    ? path.join(process.resourcesPath, 'dist', 'index.html')
    : null

  log('[ALES] arayuz adresi:', targetURL)
  log('[ALES] asar dist:', indexPath, '- Var mi:', fs.existsSync(indexPath))
  if (resIndex) {
    log('[ALES] resources dist:', resIndex, '- Var mi:', fs.existsSync(resIndex))
  }

  if (resIndex && !fs.existsSync(resIndex)) {
    dialog.showErrorBox(
      'ALES Arayuz Dosyalari Eksik',
      `Backend'in servis edecegi arayuz kopyasi yok:\n${resIndex}\n\n` +
      `Bu, paketlemede extraResources icindeki "dist" girdisinin ` +
      `atlandigi anlamina gelir (electron-builder eksik kaynagi sessizce ` +
      `atlar). Once "npm run build:frontend", sonra paketlemeyi tekrar ` +
      `calistirin.\n\nDetay log: ${getLogPath()}`
    )
  }

  mainWindow.loadURL(targetURL)

  // ─── ACILAN COCUK PENCERELER (PUTER GIRISI) ───────────────────────
  // Big ALES girisi window.open ile puter.com'a bir pencere aciyor ve
  // jetonu opener'a postMessage ile geri veriyor. Bu yuzden pencereyi
  // ENGELLEMIYORUZ (engellersek giris hic tamamlanmaz) ama acarken
  // ayarlarini SIKILASTIRIYORUZ:
  //   * webSecurity: true  -> ana pencerede kapali (Puter API'sine CORS
  //     olmadan ulasabilmek icin); UZAK bir sayfada kapali kalmasi icin
  //     hicbir sebep yok, geri aciyoruz.
  //   * devTools: false    -> uzak sayfada konsol acilmasin.
  //   * nodeIntegration kapali / contextIsolation acik -> zaten oyle,
  //     acikca yaziyoruz ki ileride ana pencere degisirse burasi kaymasin.
  // JETON/ANAHTAR SIZMASI: cocuk pencere ust pencerenin PRELOAD'unu da
  // devralir; asil koruma preload.js icindeki kaynak kapisi (window.ales
  // yalnizca localhost/file kaynaginda tanimlanir). Burasi ikinci katman.
  //
  // Yalnizca https ve YEREL http'ye izin veriliyor: /puter-bridge yedek
  // sayfasi http://localhost:8000 uzerinde, saglayici "Key Al" baglantilari
  // https. Geri kalan her sey (file:, ozel uygulama semalari) reddedilir --
  // bir sayfanin harici bir program tetiklemesinin yolu budur.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    let u = null
    try { u = new URL(url) } catch (e) { u = null }
    const localHost = u && (u.hostname === 'localhost' ||
                            u.hostname === '127.0.0.1' || u.hostname === '::1')
    const allowed = !!u && (u.protocol === 'https:' ||
                            (u.protocol === 'http:' && localHost))
    if (!allowed) {
      log('[ALES] pencere acma REDDEDILDI:', url)
      return { action: 'deny' }
    }
    log('[ALES] pencere aciliyor:', u.origin)
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        width: 580, height: 620,
        autoHideMenuBar: true,
        backgroundColor: '#000000',
        webPreferences: {
          webSecurity: true,
          contextIsolation: true,
          nodeIntegration: false,
          devTools: false,
        },
      },
    }
  })

  // ─── YENIDEN DENEME ───────────────────────────────────────────────
  // ESKI SURUM BURADA file:// KAYNAGINA DUSUYORDU (loadFile(indexPath)).
  // Yani backend bir saniye gec kalktiginda uygulama sessizce file://'a
  // donuyor ve Puter hatasi geri geliyordu; bu satir arizanin ikinci
  // yarisiydi. Artik AYNI http adresini artan gecikmeyle deniyoruz ve
  // file://'a HICBIR KOSULDA dusmuyoruz.
  let loadTries = 0
  mainWindow.webContents.on('did-fail-load',
    (e, code, desc, url, isMainFrame) => {
      if (isMainFrame === false) return   // alt cerceve hatasi sayfayi bozmaz
      if (code === -3) return             // ERR_ABORTED: yonlendirme kaynakli
      log('[ALES HATA] Sayfa yuklenemedi:', code, desc, url || '')
      if (!mainWindow) return
      loadTries += 1
      if (loadTries > 40) {
        log('[ALES] arayuz 40 denemede yuklenemedi, vazgecildi')
        dialog.showErrorBox(
          'ALES Arayuzu Yuklenemedi',
          `Arayuz ${targetURL} adresinden yuklenemedi (${desc}).\n\n` +
          `Backend ayaga kalkmamis olabilir.\n\nDetay log: ${getLogPath()}`
        )
        return
      }
      setTimeout(() => {
        if (mainWindow) mainWindow.loadURL(targetURL)
      }, Math.min(500 * loadTries, 3000))
    })

  mainWindow.webContents.on('did-finish-load', () => {
    loadTries = 0
    log('[ALES] arayuz yuklendi:', mainWindow?.webContents?.getURL() || '?')
  })

  // Renderer (arayuz) surecinin cokmesi de eskiden sessiz kaliyordu -
  // pencere acik ama tamamen boş/beyaz kalabiliyordu. Artik loglaniyor.
  mainWindow.webContents.on('render-process-gone', (e, details) => {
    log('[ALES HATA] Arayuz sureci coktu:', JSON.stringify(details))
  })

  mainWindow.once('ready-to-show', () => {
    // ─── DPI / KESKINLIK ─────────────────────────────────────────
    // Chromium yakinlastirma seviyesini KAYNAK BASINA kalici tutar.
    // Kullanici bir kez Ctrl+= / Ctrl+fare tekeri yaptiysa, arayuz
    // bir daha ACILDIGINDA da o kesirli olcekle (orn. 1.1x) cizilir:
    // metin 1x rasterize edilip 1.1 kat buyutuldugu icin belirgin
    // sekilde BULANIK gorunur ve kullanici bunun sebebini bilemez.
    // Windows %125 olceklemesinde etki iki kat belli olur (1.25 x 1.1).
    // Burada 1:1'e sabitliyoruz -- index.html'deki user-scalable=no
    // yalnizca dokunmatik/mobil icin gecerli, masaustunde ise
    // gecmiyor; asil kilit bu.
    try {
      mainWindow.webContents.setZoomFactor(1)
      mainWindow.webContents.setZoomLevel(0)
      mainWindow.webContents.setVisualZoomLevelLimits(1, 1)
    } catch (e) { log('[ALES] zoom sabitlenemedi:', e?.message || String(e)) }

    mainWindow.show()
    log('[ALES] Pencere acildi, olcek:', screen.getPrimaryDisplay().scaleFactor)
  })

  // GUVENLIK AGI: pencere show:false ile yaratiliyor ve yalnizca
  // ready-to-show ile gorunur oluyor. Arayuz artik YEREL BIR DOSYADAN
  // degil AGDAN (http://localhost:8000) geliyor; ilk yukleme basarisiz
  // olursa ready-to-show hic tetiklenmeyebilir ve kullanici hicbir
  // pencere goremez -- "cift tikladim, bir sey olmadi" arizasi. Bu
  // yuzden 15 saniye sonra pencereyi her halukarda gosteriyoruz:
  // yeniden deneme dongusu arkada calismaya devam eder, ama kullanici
  // en azindan bir pencere ve hata metnini gorur.
  setTimeout(() => {
    if (mainWindow && !mainWindow.isVisible()) {
      log('[ALES] ready-to-show gelmedi, pencere zorla gosteriliyor')
      try { mainWindow.show() } catch (e) {}
    }
  }, 15000)

  mainWindow.on('closed', () => { mainWindow = null })
}

function toggleFloating() {
  if (!mainWindow) return
  const { width: sw, height: sh } = screen.getPrimaryDisplay().workAreaSize
  if (!isFloating) {
    isFloating = true
    mainWindow.setSize(380, 660)
    mainWindow.setPosition(sw - 400, sh - 700)
    mainWindow.setAlwaysOnTop(true)
    mainWindow.setResizable(false)
    mainWindow.webContents.send('mode-change', 'floating')
  } else {
    isFloating = false
    mainWindow.setSize(sw, sh)
    mainWindow.setPosition(0, 0)
    mainWindow.setAlwaysOnTop(false)
    mainWindow.setResizable(true)
    mainWindow.webContents.send('mode-change', 'fullscreen')
  }
}

function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'icon.png')
  if (!fs.existsSync(iconPath)) return
  tray = new Tray(iconPath)
  tray.setToolTip('ALES v3.0')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Ac', click: () => mainWindow ? mainWindow.show() : createMainWindow() },
    { label: 'Floating / Tam Ekran', click: toggleFloating },
    { type: 'separator' },
    { label: 'Kapat', click: () => app.quit() }
  ]))
  tray.on('click', () => {
    if (mainWindow) mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show()
    else createMainWindow()
  })
}

// IPC
ipcMain.on('window-close', () => mainWindow?.hide())
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-toggle-float', () => toggleFloating())
ipcMain.on('window-quit', () => app.quit())

ipcMain.handle('save-config', async (_, data) => {
  const configPath = getConfigPath()
  let cfg = {}
  if (fs.existsSync(configPath)) {
    try { cfg = JSON.parse(fs.readFileSync(configPath, 'utf-8')) } catch(e) {}
  }
  for (const [k, v] of Object.entries(data || {})) {
    if (v !== null && v !== undefined && String(v).trim() !== '') {
      cfg[k] = String(v).trim()
    } else if (data[`clear_${k}`] === true || v === '__CLEAR__') {
      cfg[k] = ''
    }
  }
  fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2))
  try {
    await fetch('http://localhost:8000/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
  } catch(e) {}
  return { success: true }
})

ipcMain.handle('load-config', () => {
  const configPath = getConfigPath()
  if (fs.existsSync(configPath)) {
    try { return JSON.parse(fs.readFileSync(configPath, 'utf-8')) } catch(e) {}
  }
  return {}
})

app.whenReady().then(() => {
  log('[ALES] Uygulama basliyor...')
  log('[ALES] __dirname:', __dirname)
  log('[ALES] isPackaged:', app.isPackaged)

  startBackend()

  // Backend'in hazır olmasını bekle - sabit 2.5s yerine
  // gerçekten /status endpoint'i yanıt verene kadar dene
  let windowCreated = false
  const tryCreateWindow = (attempt) => {
    if (windowCreated) return
    const http = require('http')

    const retryOrForceOpen = (reason) => {
      if (windowCreated) return
      const delay = Math.min(500 * (attempt + 1), 3000)
      if (attempt < 20) {
        setTimeout(() => tryCreateWindow(attempt + 1), delay)
      } else {
        // 20 denemeden sonra yine de ac - ama artik SEBEBINI de logluyoruz
        log('[ALES] Backend zaman asimi/hata, pencere yine de aciliyor. Sebep:', reason)
        windowCreated = true
        createMainWindow()
        createTray()
      }
    }

    const req = http.get('http://localhost:8000/status', (res) => {
      if (res.statusCode === 200) {
        windowCreated = true
        log('[ALES] Backend hazir, pencere aciliyor...')
        createMainWindow()
        createTray()
        res.resume()
        return
      }
      // KRITIK DUZELTME: eskiden 200 disi bir yanit (orn. backend
      // /status icinde hata alip 500 donduruyorsa) burada HICBIR SEY
      // yapilmiyordu - ne yeniden deneme, ne zorla acma, ne log.
      // Backend'in ic hatasi = "hicbir sey olmadi" hissi bu yuzdendi.
      let body = ''
      res.on('data', (c) => { body += c })
      res.on('end', () => {
        retryOrForceOpen(`/status HTTP ${res.statusCode} dondurdu: ${body.slice(0, 200)}`)
      })
    })
    req.on('error', (err) => {
      retryOrForceOpen(`istek hatasi: ${err.message}`)
    })
    req.setTimeout(1000, () => req.destroy())
  }

  // İlk denemeyi 1 saniye sonra başlat (backend process başlasın diye)
  setTimeout(() => tryCreateWindow(0), 1000)


  globalShortcut.register('Alt+Space', () => {
    if (!mainWindow) return
    mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show()
  })
  globalShortcut.register('Alt+F', toggleFloating)
})

function killBackend() {
  if (backendProcess && backendProcess.pid) {
    log('[ALES] Backend süreci sonlandırılıyor (taskkill /T /F)... PID:', backendProcess.pid)
    try {
      execSync('taskkill /pid ' + backendProcess.pid + ' /T /F')
    } catch (e) {
      log('[ALES] taskkill hatası / zaten kapalı:', e?.message || e)
    }
    try { backendProcess.kill('SIGKILL') } catch (e) {}
    backendProcess = null
  }
}

app.on('window-all-closed', e => e.preventDefault())
app.on('before-quit', () => {
  globalShortcut.unregisterAll()
  killBackend()
})
app.on('will-quit', () => {
  killBackend()
})
