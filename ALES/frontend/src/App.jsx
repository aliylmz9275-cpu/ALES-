import { useState, useEffect, useRef, useCallback } from 'react'
import Worldview3D from './Worldview3D.jsx'

const isElectron = typeof window !== 'undefined' && window.ales?.isElectron
// AYIRT ETME MANTIĞI (bu satırlar telefon/PC baglanti sorununun kaynagiydi):
// - Electron (masaustu .exe): her zaman ayni makine -> localhost:8000
// - Yerel gelistirme/start.bat (Vite :5173 portunda calisiyor): ister PC'den
//   (localhost:5173) ister telefondan (LAN IP:5173) acilsin backend HER
//   ZAMAN 8000 portunda - sadece HOSTNAME degisir. Eskiden bu durumda da
//   "cloud" moduna dusup ya sabit 'localhost' (telefonda kendi kendini
//   arar, PC'yi degil) ya da yanlis port (5173) kullaniliyordu - telefonda
//   sonsuza kadar "Backend baslatiliyor..." gorunmesinin sebebi buydu.
// - Gercek bulut dagitimi (Railway vb.): frontend+backend AYNI origin/portta
//   servis edilir (5173 degil) -> bu GERCEKTEN cloud modu, erisim anahtari
//   ekrani burada dogru.
const isLocalDev = typeof window !== 'undefined' && window.location.port === '5173'
const isCloud = typeof window !== 'undefined' && window.location.protocol !== 'file:' && !isElectron && !isLocalDev
const backendHost = (typeof window !== 'undefined' && window.location.hostname) || 'localhost'
const API_URL = isCloud ? window.location.origin : `http://${backendHost}:8000`
const WS_URL = isCloud ? window.location.origin.replace(/^http/, 'ws') + '/ws' : `ws://${backendHost}:8000/ws`
const STREAM_WS_URL = isCloud ? window.location.origin.replace(/^http/, 'ws') + '/ws/stream' : `ws://${backendHost}:8000/ws/stream`

// Cloud modunda (telefon/tarayici) backend'e girerken erisim anahtari
// gerekir - masaustunde (yerel ag, sadece Ali erisebiliyor) gerekmez.
function getCloudKey() {
  try { return isCloud ? (localStorage.getItem('ales_cloud_key') || '') : '' } catch { return '' }
}
function setCloudKey(key) {
  try { if (isCloud) localStorage.setItem('ales_cloud_key', key) } catch {}
}
// fetch() cagrilarina otomatik olarak erisim anahtari header'ini ekler
function authFetch(url, opts = {}) {
  const key = getCloudKey()
  const headers = { ...(opts.headers || {}), ...(key ? { 'X-ALES-Key': key } : {}) }
  return fetch(url, { ...opts, headers })
}

// Mesaj içeriğindeki PDF ve bağlantıları şık indirme kartlarına dönüştürür
function renderMessageContent(text) {
  if (!text || typeof text !== 'string') return text
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)|(https?:\/\/[^\s)]+|\/api\/download\/pdf\/[^\s)]+)/g
  if (!linkRegex.test(text)) return text

  const parts = []
  let lastIndex = 0
  let match
  linkRegex.lastIndex = 0

  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index))
    }
    const label = match[1] || match[3]
    let url = match[2] || match[3]
    const fullUrl = url.startsWith('/') && !url.startsWith('//') ? `${API_URL}${url}` : url
    const isPdf = url.toLowerCase().includes('.pdf') || url.includes('/api/download/pdf/')

    if (isPdf) {
      parts.push(
        <a
          key={match.index}
          href={fullUrl}
          target="_blank"
          rel="noopener noreferrer"
          download
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            color: '#fca5a5',
            padding: '4px 10px',
            borderRadius: 6,
            textDecoration: 'none',
            fontWeight: 600,
            fontSize: 13,
            margin: '4px 2px',
            verticalAlign: 'middle',
            transition: 'all 0.15s'
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.25)'
            e.currentTarget.style.color = '#ffffff'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)'
            e.currentTarget.style.color = '#fca5a5'
          }}
        >
          <span>📄</span>
          <span>{label}</span>
          <span style={{ fontSize: 11, opacity: 0.8 }}>⬇ İndir</span>
        </a>
      )
    } else {
      parts.push(
        <a
          key={match.index}
          href={fullUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            color: '#60a5fa',
            textDecoration: 'underline',
            wordBreak: 'break-all'
          }}
        >
          {label}
        </a>
      )
    }
    lastIndex = linkRegex.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex))
  }
  return parts
}

// ElevenLabs cok-dilli (Turkce dahil) dogal sesler - voice.py ile ayni liste
const VOICE_OPTIONS = [
  { id: 'pNInz6obpgDQGcFmaJgB', name: 'Adam - Derin Erkek (JARVIS tarzi)' },
  { id: 'VR6AewLTigWG4xSOukaG', name: 'Arnold - Sert/Otoriter Erkek' },
  { id: 'ErXwobaYiN019PkySvjV', name: 'Antoni - Sicak/Yumusak Erkek' },
  { id: 'TxGEqnHWrfWFTfGW9XjX', name: 'Josh - Genc Erkek' },
  { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel - Dogal Kadin' },
  { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella - Sicak Kadin' },
]
// Ucretsiz Edge-TTS sesleri (ElevenLabs key'i yoksa/basarisiz olursa
// kullanilir) - voice.py'deki EDGE_VOICES ile ayni liste
const EDGE_VOICE_OPTIONS = [
  { id: 'tr-TR-AhmetNeural', name: 'Ahmet - Erkek (ücretsiz)' },
  { id: 'tr-TR-EmelNeural', name: 'Emel - Kadın (ücretsiz)' },
]
const selectStyle = {background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.1)',borderRadius:8,padding:'9px 11px',color:'#fff',fontSize:12,fontFamily:'monospace',outline:'none',width:'100%'}

// ─── CLOUD GIRIS EKRANI ──────────────────────────────────────────
// Sadece telefon/tarayicidan acildiginda gorunur. Masaustunde hic devreye
// girmez (isCloud=false oldugu icin App bu bileseni hic render etmez).
function CloudGate({ onOk }) {
  const [val, setVal] = useState('')
  const [err, setErr] = useState('')
  const [checking, setChecking] = useState(false)
  const submit = async () => {
    if (!val.trim()) return
    setChecking(true); setErr('')
    try {
      const r = await fetch(API_URL + '/status', { headers: { 'X-ALES-Key': val.trim() } })
      if (r.status === 401) { setErr('Kod yanlış.'); setChecking(false); return }
      setCloudKey(val.trim())
      onOk()
    } catch { setErr('Sunucuya ulaşılamadı.'); }
    setChecking(false)
  }
  return (
    <div style={{width:'100vw',height:'100vh',background:'#121212',display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:16,padding:20}}>
      <div style={{fontFamily:"'Share Tech Mono',monospace",fontSize:28,color:'#ffffff',letterSpacing:3}}>ALES</div>
      <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',textAlign:'center'}}>Bu cihaz için erişim kodunu girin</div>
      <input autoFocus type="password" value={val} onChange={e=>setVal(e.target.value)} onKeyDown={e=>e.key==='Enter'&&submit()}
        style={{...selectStyle, width:240, textAlign:'center', letterSpacing:2, background:'#1E1E24', color:'#ffffff', fontSize:14}} placeholder="ERİŞİM KODU" />
      {err && <div style={{fontSize:12,color:'#f87171'}}>{err}</div>}
      <button onClick={submit} disabled={checking} style={{padding:'10px 24px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.14)',color:'#ffffff',borderRadius:8,cursor:'pointer',fontFamily:'monospace',fontSize:13,fontWeight:600}}>
        {checking?'KONTROL EDİLİYOR...':'GİRİŞ'}
      </button>
    </div>
  )
}

// ─── SPLASH ──────────────────────────────────────────────────────
function Splash({ onDone }) {
  const [phase, setPhase] = useState(0)
  useEffect(() => {
    const t = [300,1200,2400,4200,5000].map((ms,i) => setTimeout(() => {
      if (i < 4) setPhase(i+1); else onDone()
    }, ms))
    return () => t.forEach(clearTimeout)
  }, [])
  return (
    <div style={{position:'fixed',inset:0,zIndex:9999,display:'flex',alignItems:'center',justifyContent:'center',overflow:'hidden',background:phase===4?'#fff':'#000',transition:phase===4?'background 0.5s':'none'}}>
      <div style={{position:'absolute',inset:0,backgroundImage:'repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(255,255,255,0.01) 2px,rgba(255,255,255,0.01) 4px)',pointerEvents:'none'}} />
      {phase>=1 && ['tl','tr','bl','br'].map(p=>(
        <div key={p} style={{position:'absolute',width:24,height:24,...{tl:{top:32,left:32,borderTop:'2px solid #ffffff',borderLeft:'2px solid #ffffff'},tr:{top:32,right:32,borderTop:'2px solid #ffffff',borderRight:'2px solid #ffffff'},bl:{bottom:32,left:32,borderBottom:'2px solid #ffffff',borderLeft:'2px solid #ffffff'},br:{bottom:32,right:32,borderBottom:'2px solid #ffffff',borderRight:'2px solid #ffffff'}}[p]}} />
      ))}
      <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:24,zIndex:2}}>
        {phase>=3 && <div style={{position:'relative',width:80,height:80,display:'flex',alignItems:'center',justifyContent:'center'}}>
          <div style={{width:50,height:50,borderRadius:'50%',background:'radial-gradient(circle,#dddddd,#ffffff,#1a1a1a)',boxShadow:'0 0 40px #ffffff',animation:'orbp 2s ease-in-out infinite'}} />
          <div style={{position:'absolute',inset:0,borderRadius:'50%',border:'1px solid #ffffff55',borderTopColor:'#ffffff',animation:'ring 2s linear infinite'}} />
        </div>}
        {phase>=2 && <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:8}}>
          <div style={{display:'flex',gap:4}}>
            {'ALES'.split('').map((l,i)=>(
              <span key={i} style={{fontSize:64,fontWeight:900,color:'#fff',fontFamily:"'Share Tech Mono',monospace",letterSpacing:8,animation:'letin .5s ease forwards',opacity:0,textShadow:'0 0 30px #ffffff',animationDelay:`${i*.15}s`}}>{l}</span>
            ))}
          </div>
          {phase>=3 && <div style={{fontSize:9,color:'#ffffff',letterSpacing:5,fontFamily:'monospace',animation:'subin .8s ease forwards',opacity:0}}>ADVANCED LOGIC EXECUTION SYSTEM</div>}
        </div>}
        {phase>=3 && <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:7,marginTop:8}}>
          <div style={{fontSize:9,color:'#ffffff44',fontFamily:'monospace',letterSpacing:3}}>BASLATILIYOR...</div>
          <div style={{width:180,height:1,background:'#ffffff11',overflow:'hidden'}}>
            <div style={{height:'100%',background:'linear-gradient(90deg,#ffffff,#dddddd)',animation:'bfill 2s ease forwards'}} />
          </div>
        </div>}
      </div>
      <style>{`
        @keyframes letin{from{opacity:0;transform:translateY(14px);filter:blur(5px)}to{opacity:1;transform:none;filter:none}}
        @keyframes orbp{0%,100%{transform:scale(1)}50%{transform:scale(1.08)}}
        @keyframes ring{to{transform:rotate(360deg)}}
        @keyframes bfill{from{width:0}to{width:100%}}
        @keyframes subin{from{opacity:0;letter-spacing:10px}to{opacity:.8;letter-spacing:5px}}
      `}</style>
    </div>
  )
}

// ─── ONBOARDING (API KEYS) MODAL (TASK 4) ────────────────────────────
function OnboardingModal({ isOpen = true, onDone }) {
  const [groqKey, setGroqKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testStatus, setTestStatus] = useState('idle') // 'idle' | 'success' | 'error'
  const [testMsg, setTestMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  if (!isOpen) return null

  const testConnection = async () => {
    setTesting(true)
    setTestStatus('idle')
    setTestMsg('')
    setErr('')
    const gKey = groqKey.trim()
    const gmKey = geminiKey.trim()
    if (!gKey && !gmKey) {
      setTesting(false)
      setTestStatus('error')
      setTestMsg('Lütfen en az bir API anahtarı girin (Groq veya Gemini).')
      return
    }

    const errors = []
    const successes = []

    if (gKey) {
      try {
        const res = await authFetch(API_URL + '/test-key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'groq', key: gKey })
        })
        const data = await res.json()
        if (data.ok) {
          successes.push(`Groq ✓ (${data.model || 'aktif'})`)
        } else {
          errors.push(data.error || 'Groq: Invalid API Key')
        }
      } catch (e) {
        errors.push(`Groq Bağlantı Hatası: ${e?.message || e}`)
      }
    }

    if (gmKey) {
      try {
        const res = await authFetch(API_URL + '/test-key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'gemini', key: gmKey })
        })
        const data = await res.json()
        if (data.ok) {
          successes.push(`Gemini ✓ (${data.model || 'aktif'})`)
        } else {
          errors.push(data.error || 'Gemini: Invalid API Key')
        }
      } catch (e) {
        errors.push(`Gemini Bağlantı Hatası: ${e?.message || e}`)
      }
    }

    setTesting(false)
    if (successes.length > 0) {
      setTestStatus('success')
      const msg = `${successes.join(' & ')} Bağlantı Başarılı!`
      setTestMsg(errors.length > 0 ? `${msg} — Dikkat: ${errors.join('; ')}` : msg)
    } else {
      setTestStatus('error')
      setTestMsg(errors.join(' | '))
    }
  }

  const save = async () => {
    if (testStatus !== 'success') {
      setErr('Lütfen önce "Test Connection" ile anahtarınızı doğrulayın.')
      return
    }
    setSaving(true)
    setErr('')
    const data = {}
    if (groqKey.trim()) data.groq_key = groqKey.trim()
    if (geminiKey.trim()) data.gemini_key = geminiKey.trim()

    if (isElectron) { try { await window.ales.saveConfig(data) } catch(e) {} }
    for (let i = 0; i < 6; i++) {
      try {
        const r = await authFetch(API_URL + '/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        })
        if (r.ok) break
      } catch(e) { await new Promise(res => setTimeout(res, 1000)) }
    }
    setSaving(false)
    onDone && onDone(data)
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.85)',
      backdropFilter: 'blur(12px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 10000,
      fontFamily: "'Inter', sans-serif"
    }}>
      <div style={{
        width: 460,
        maxWidth: '92vw',
        padding: '32px 28px',
        background: '#1E1E24',
        border: '1px solid rgba(255,255,255,0.22)',
        borderRadius: 16,
        boxShadow: '0 24px 64px rgba(0,0,0,0.9)',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        animation: 'fadeUp .25s ease'
      }}>
        {/* Logo & Header */}
        <div style={{display:'flex',alignItems:'center',gap:12}}>
          <div style={{
            width: 44,
            height: 44,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #444, #fff)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 18,
            fontWeight: 800,
            color: '#000',
            fontFamily: "'Share Tech Mono', monospace"
          }}>
            A
          </div>
          <div>
            <div style={{fontSize: 18, fontWeight: 700, color: '#ffffff', letterSpacing: 0.5}}>ALES'e Hoş Geldiniz</div>
            <div style={{fontSize: 12, color: '#A1A1AA', fontFamily: 'monospace', letterSpacing: 1.5, marginTop: 2}}>HIZLI KURULUM & DOĞRULAMA</div>
          </div>
        </div>

        {/* Core Message */}
        <div style={{
          padding: '12px 14px',
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.15)',
          borderRadius: 8,
          fontSize: 13,
          lineHeight: 1.5,
          color: '#E4E4E7'
        }}>
          <b style={{color:'#ffffff'}}>ALES needs at least one API key to function.</b>
          <div style={{fontSize: 12, color: '#A1A1AA', marginTop: 4}}>
            ALES'in yanıt verebilmesi ve modelleri çalıştırabilmesi için en az bir API anahtarı (Groq veya Gemini) gereklidir. Anahtarınızı girip bağlantıyı test edin.
          </div>
        </div>

        {/* Input Fields */}
        <div style={{display:'flex',flexDirection:'column',gap:14}}>
          <div>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
              <label style={{fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace'}}>Groq API Key (Önerilen)</label>
              <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" style={{fontSize:12,color:'#38bdf8',textDecoration:'none',fontFamily:'monospace'}}>Key Al ↗</a>
            </div>
            <input
              type="password"
              placeholder="gsk_..."
              value={groqKey}
              onChange={e => { setGroqKey(e.target.value); setTestStatus('idle'); setTestMsg(''); }}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: '#121212',
                border: '1px solid rgba(255,255,255,0.22)',
                borderRadius: 8,
                color: '#ffffff',
                fontSize: 14,
                fontFamily: 'monospace',
                outline: 'none'
              }}
            />
            <div style={{fontSize:12,color:'#A1A1AA',marginTop:4}}>Ücretsiz, anlık ultra-hızlı Llama-3.3-70B modeli.</div>
          </div>

          <div>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
              <label style={{fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace'}}>Gemini API Key</label>
              <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" style={{fontSize:12,color:'#38bdf8',textDecoration:'none',fontFamily:'monospace'}}>Key Al ↗</a>
            </div>
            <input
              type="password"
              placeholder="AIza..."
              value={geminiKey}
              onChange={e => { setGeminiKey(e.target.value); setTestStatus('idle'); setTestMsg(''); }}
              style={{
                width: '100%',
                padding: '10px 12px',
                background: '#121212',
                border: '1px solid rgba(255,255,255,0.22)',
                borderRadius: 8,
                color: '#ffffff',
                fontSize: 14,
                fontFamily: 'monospace',
                outline: 'none'
              }}
            />
            <div style={{fontSize:12,color:'#A1A1AA',marginTop:4}}>Google AI Studio - Görme (Vision) ve genel zeka modeli.</div>
          </div>
        </div>

        {/* Validation Status Display */}
        {testStatus === 'error' && (
          <div style={{
            fontSize: 13,
            color: '#f87171',
            background: 'rgba(239,68,68,0.12)',
            border: '1px solid rgba(239,68,68,0.3)',
            padding: '10px 12px',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 8
          }}>
            ❌ {testMsg}
          </div>
        )}

        {testStatus === 'success' && (
          <div style={{
            fontSize: 13,
            color: '#4ade80',
            background: 'rgba(74,222,128,0.12)',
            border: '1px solid rgba(74,222,128,0.3)',
            padding: '10px 12px',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 8
          }}>
            ✓ {testMsg}
          </div>
        )}

        {err && <div style={{fontSize:12,color:'#f87171',background:'rgba(248,113,113,0.12)',padding:'8px 12px',borderRadius:6}}>{err}</div>}

        {/* Action Buttons */}
        <div style={{display:'flex',gap:10,marginTop:8}}>
          <button
            onClick={testConnection}
            disabled={testing || (!groqKey.trim() && !geminiKey.trim())}
            style={{
              flex: 1,
              padding: '12px',
              background: 'rgba(255,255,255,0.12)',
              color: '#ffffff',
              fontWeight: 600,
              border: '1px solid rgba(255,255,255,0.3)',
              borderRadius: 8,
              fontSize: 13,
              fontFamily: 'monospace',
              cursor: (testing || (!groqKey.trim() && !geminiKey.trim())) ? 'not-allowed' : 'pointer',
              opacity: (testing || (!groqKey.trim() && !geminiKey.trim())) ? 0.4 : 1,
              transition: 'all .2s'
            }}
          >
            {testing ? 'TEST EDİLİYOR...' : 'Test Connection'}
          </button>

          <button
            onClick={save}
            disabled={testStatus !== 'success' || saving}
            style={{
              flex: 1,
              padding: '12px',
              background: testStatus === 'success' ? '#ffffff' : 'rgba(255,255,255,0.15)',
              color: testStatus === 'success' ? '#000000' : '#888888',
              fontWeight: 700,
              border: 'none',
              borderRadius: 8,
              fontSize: 13,
              fontFamily: 'monospace',
              letterSpacing: 1,
              cursor: (testStatus !== 'success' || saving) ? 'not-allowed' : 'pointer',
              opacity: (testStatus !== 'success' || saving) ? 0.5 : 1,
              boxShadow: testStatus === 'success' ? '0 0 16px rgba(255,255,255,0.3)' : 'none',
              transition: 'all .2s'
            }}
          >
            {saving ? 'KAYDEDİLİYOR...' : 'Save & Start'}
          </button>
        </div>
      </div>
    </div>
  )
}
const Setup = OnboardingModal;

// ─── TOOL LABELS ─────────────────────────────────────────────────
const TL = {
  take_screenshot:'Ekrana bakiyor',open_app:'Uygulama aciyor',type_text:'Yazıyor',
  press_key:'Tus basiyor',click_at:'Tıklıyor',get_system_info:'Sistem kontrolu',
  remember_fact:'Ogreniyor',update_user_profile:'Profil guncellıyor',
  search_memory:'Hafizada ariyor',fetch_url:'Siteye giriyor',
  google_search:'Arıyor',get_worldview:'Dunyaya bakiyor',
  get_news_tr:'Haberler alıyor',get_weather:'Hava durumu',
  get_crypto_prices:'Kripto fiyatları',get_exchange_rates:'Doviz',
  run_python_code:'Kod calıstırıyor',set_persona:'Mod degistiriyor',
  switch_model:'Model degistiriyor',add_schedule:'Zamanlama kuruyor',
  // Masaustu kontrolu (native_desktop.py)
  list_windows:'Pencereleri listeliyor',focus_window:'Pencereyi one getiriyor',
  window_state:'Pencere boyutunu degistiriyor',close_window:'Pencereyi kapatiyor',
  wait_for_window:'Pencere bekliyor',list_controls:'Arayuzu inceliyor',
  click_control:'Butona basiyor',set_control_text:'Kutuya yaziyor',
  get_control_text:'Metni okuyor',
}

// ─── YEREL HUD (OpenDex yerine) ──────────────────────────────────
// NEDEN AYRI BIR PENCERE/PAKET DEGIL: OpenDex tarzi bir HUD ayri bir
// surec + ayri bir pencere yonetimi demek. Ayni gorsel geri bildirimi
// ZATEN acik olan React arayuzunun icine gomuyoruz: sifir ek surec,
// sifir ek bagimlilik, ayni koyu/gri tema.
//
// ERISILEBILIRLIK: ikisi de prefers-reduced-motion'a uyar. Surekli
// nabiz atan bir nokta, hareket duyarliligi olan kullanicilar icin
// rahatsizlik kaynagidir; o durumda nokta sabit kalir (kaybolmaz —
// bilgi kaybolmadan sadece hareket durur).
function useReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    let mq
    try {
      mq = window.matchMedia('(prefers-reduced-motion: reduce)')
      setReduced(mq.matches)
      const on = e => setReduced(e.matches)
      mq.addEventListener ? mq.addEventListener('change', on) : mq.addListener(on)
      return () => { mq.removeEventListener ? mq.removeEventListener('change', on) : mq.removeListener(on) }
    } catch { setReduced(false) }
  }, [])
  return reduced
}

// Konusan nokta: ALES ses cikardigi SURECE nabiz atar. Kaynak
// backend'in {"type":"speaking","on":bool} olayidir — tahmini bir
// zamanlayici degil, gercek ses akisinin baslangici/bitisi.
function TalkingDot({ on, hidden }) {
  const reduced = useReducedMotion()
  if (hidden) return null
  return (
    <div style={{position:'fixed',bottom:18,right:18,zIndex:998,pointerEvents:'none',
                 display:'flex',alignItems:'center',gap:9,
                 opacity:on?1:0,transform:on?'translateY(0)':'translateY(6px)',
                 transition:'opacity .25s ease, transform .25s ease'}}>
      <div style={{position:'relative',width:34,height:34,display:'flex',
                   alignItems:'center',justifyContent:'center'}}>
        {/* Dalga halkalari: sadece hareket izni varken */}
        {on && !reduced && [0,1,2].map(i=>(
          <div key={i} style={{position:'absolute',width:34,height:34,borderRadius:'50%',
                               border:'1px solid rgba(255,255,255,0.28)',
                               animation:`waveRipple 1.9s ease-out ${i*0.55}s infinite`}} />
        ))}
        <div style={{width:13,height:13,borderRadius:'50%',
                     background:'radial-gradient(circle,#ffffff,#bbbbbb)',
                     boxShadow:on?'0 0 14px #ffffff,0 0 28px rgba(255,255,255,0.35)':'none',
                     animation:(on&&!reduced)?'hudBreathe 1.15s ease-in-out infinite':'none'}} />
      </div>
      <span style={{fontSize:8,fontFamily:'monospace',letterSpacing:2,color:'#ffffff77',
                    background:'rgba(0,0,0,0.82)',border:'1px solid rgba(255,255,255,0.12)',
                    borderRadius:6,padding:'3px 8px'}}>
        KONUSUYOR
      </span>
    </div>
  )
}

// Yazan imlec: metin uretildikce ilerleyen blok imlec. Kendi bilesenine
// ayirdik cunku hem akis onizlemesinde hem HUD seridinde kullaniliyor ve
// hareket-azaltma kurali tek yerde kalmali.
function TypingCursor({ active = true, char = '▍' }) {
  const reduced = useReducedMotion()
  return (
    <span style={{opacity:active?0.75:0.3,marginLeft:1,
                  animation:(active&&!reduced)?'d1 1s infinite':'none'}}>{char}</span>
  )
}

// Ust serit HUD: yazma/arac/ses durumunu tek satirda gosterir.
// SOHBET BALONUNUN YERINI ALMAZ — sadece durum ozeti; sekme degistirilse
// bile ALES'in ne yaptigi gorunur kalir.
function HudStrip({ typing, speaking, toolLabel, chars, hidden }) {
  const reduced = useReducedMotion()
  if (hidden) return null
  const show = typing || speaking || !!toolLabel
  if (!show) return null
  const label = toolLabel || (typing ? 'YAZIYOR' : 'KONUSUYOR')
  return (
    <div style={{position:'fixed',top:56,left:'50%',transform:'translateX(-50%)',zIndex:997,
                 pointerEvents:'none',display:'flex',alignItems:'center',gap:8,
                 background:'rgba(10,10,10,0.94)',border:'1px solid rgba(255,255,255,0.14)',
                 borderRadius:8,padding:'4px 11px',
                 animation:reduced?'none':'fadeUp .2s ease'}}>
      <div style={{width:6,height:6,borderRadius:'50%',
                   background:speaking?'#ffffff':'#cccccc',
                   boxShadow:speaking?'0 0 8px #ffffff':'none',
                   animation:(!reduced&&(speaking||typing))?'scanPulse 1.2s infinite':'none'}} />
      <span style={{fontSize:8,fontFamily:'monospace',letterSpacing:2,color:'#dddddd'}}>{label}</span>
      {typing && <TypingCursor active />}
      {typing && chars>0 && <span style={{fontSize:7,fontFamily:'monospace',color:'#ffffff44'}}>{chars} krk</span>}
    </div>
  )
}

// ─── ANA APP ─────────────────────────────────────────────────────
export default function App() {
  const [screen, setScreen] = useState('splash')
  const [cloudUnlocked, setCloudUnlocked] = useState(!isCloud || !!getCloudKey())
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [streamPreview, setStreamPreview] = useState('')
  const [expandedApproval, setExpandedApproval] = useState(null)
  const [stats, setStats] = useState(null)
  const [earnAmount, setEarnAmount] = useState('')
  const [earnNote, setEarnNote] = useState('')
  const [activeTools, setActiveTools] = useState([])
  const [approvals, setApprovals] = useState([])
  const [speaking, setSpeaking] = useState(false)
  const [mode, setMode] = useState('fullscreen')
  const [tab, setTab] = useState('chat')
  const [time, setTime] = useState(new Date())
  const [showSettings, setShowSettings] = useState(false)
  const [worldviewText, setWorldviewText] = useState(null)
  const [listening, setListening] = useState(false)
  const [conversations, setConversations] = useState([])
  const [activeConvId, setActiveConvId] = useState(null)
  const [logs, setLogs] = useState([])
  // GOREV sekmesi (Faz 3): gercek sistem kontrolu. Eskiden bu sekme sadece
  // hazir sohbet komutlari yolluyordu; artik /system/* endpointlerini kullanir.
  const [sysStatus, setSysStatus] = useState(null)
  const [sysLogs, setSysLogs] = useState([])
  const [profiles, setProfiles] = useState([])
  const [selProfiles, setSelProfiles] = useState([])
  const [sysBusy, setSysBusy] = useState(false)
  const [councilInfo, setCouncilInfo] = useState(null)
  // Ekrana bakma animasyonu - analyze_screen/take_screenshot aracı
  // calısırken mavi tarama dalgası gösterilir ve ALES otomatik
  // floating (sag alt kose) moduna geçer ki ekranı kapatmasın
  const [scanning, setScanning] = useState(false)
  // Beceri onerileri (skills_autogrowth): onay bekleyen sayisi. Ayarlar
  // panelinde rozet olarak gosterilir; kullanici acmadan da haberi olur.
  const [skillProposals, setSkillProposals] = useState(0)
  const [autoSpeak, setAutoSpeak] = useState(() => {
    try { return localStorage.getItem('ales_autospeak') === 'true' } catch { return false }
  })
  const autoSpeakRef = useRef(autoSpeak)
  useEffect(() => { autoSpeakRef.current = autoSpeak }, [autoSpeak])
  useEffect(() => {
    if (isCloud && tab === 'live') {
      setTab('chat')
    }
  }, [tab])
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [streamFrame, setStreamFrame] = useState(null)
  const [streamActive, setStreamActive] = useState(false)
  const [streamTasks, setStreamTasks] = useState([])
  const [streamActivities, setStreamActivities] = useState([])

  useEffect(() => {
    if (tab !== 'live') return
    let ws = null
    try {
      const url = isCloud ? `${STREAM_WS_URL}?key=${encodeURIComponent(getCloudKey())}` : STREAM_WS_URL
      ws = new WebSocket(url)
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'init') {
            setStreamActive(msg.status === 'active')
            setStreamTasks(msg.active_tasks || [])
            if (msg.activities) setStreamActivities(msg.activities)
          } else if (msg.type === 'frame') {
            setStreamFrame(msg.image)
            setStreamActive(msg.status === 'active' || (msg.active_tasks && msg.active_tasks.length > 0))
            if (msg.active_tasks) setStreamTasks(msg.active_tasks)
          } else if (msg.type === 'idle') {
            setStreamActive(false)
            setStreamTasks([])
          } else if (msg.type === 'activity') {
            setStreamActivities(prev => [msg, ...prev.slice(0, 99)])
          }
        } catch {}
      }
    } catch {}
    return () => {
      try { ws?.close() } catch {}
    }
  }, [tab])

  useEffect(() => {
    try {
      const savedKeys = JSON.parse(localStorage.getItem('ales_saved_api_keys') || '{}')
      const savedMode = localStorage.getItem('ales_selected_mode') || ''
      if (Object.keys(savedKeys).length > 0 || savedMode) {
        authFetch(`${API_URL}/api/session/sync`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keys: savedKeys, mode: savedMode })
        }).catch(() => {})
      }
    } catch (e) {}

    authFetch(`${API_URL}/config`).then(r => r.json()).then(cfg => {
      if (cfg && !cfg.groq_key && !cfg.gemini_key && !cfg.cerebras_key && !cfg.nvidia_key && !cfg.openrouter_key) {
        try {
          const savedKeys = JSON.parse(localStorage.getItem('ales_saved_api_keys') || '{}')
          if (Object.keys(savedKeys).length === 0) {
            setShowOnboarding(true)
          }
        } catch {
          setShowOnboarding(true)
        }
      }
    }).catch(() => {})
  }, [])

  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const reconnectRef = useRef(null)
  const recRef = useRef(null)
  const mediaRecorderRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const [transcribing, setTranscribing] = useState(false)
  // HUD/ses koordinasyonu:
  // speakingRealRef — backend GERCEK "speaking" olayi gonderiyorsa true olur.
  //   ESKIDEN 'message' olayinda 4 saniyelik bir zamanlayici ile konusma
  //   TAKLIT ediliyordu. Akan ses acikken bu taklit gercek olayla kavga
  //   ediyordu (ses hala calarken rozet sonuyordu). Gercek olay bir kez
  //   geldiyse taklidi bir daha kullanmiyoruz.
  const speakingRealRef = useRef(false)
  const speakTimerRef = useRef(null)
  // Ses kuyrugu: parcalar SIRAYLA calinmali. Ayni anda new Audio().play()
  // demek, cumlelerin ust uste binmesi demek.
  const audioQueueRef = useRef([])
  const audioPlayingRef = useRef(false)
  const audioElRef = useRef(null)
  const audioUnlockedRef = useRef(false)
  const [audioBlocked, setAudioBlocked] = useState(false)
  const lastAssistantMsgRef = useRef('')

  const unlockAudio = useCallback(() => {
    if (audioUnlockedRef.current) return
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext
      if (AudioCtx) {
        const ctx = new AudioCtx()
        if (ctx.state === 'suspended') ctx.resume()
      }
      const silent = new Audio("data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA")
      silent.play().then(() => {
        audioUnlockedRef.current = true
        setAudioBlocked(false)
      }).catch(() => {})
    } catch (e) {}
  }, [])

  useEffect(() => { const t = setInterval(()=>setTime(new Date()),1000); return ()=>clearInterval(t) }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({behavior:'smooth'}) }, [messages, activeTools])
  useEffect(() => { if (isElectron) window.ales?.onModeChange?.(m=>setMode(m)) }, [])
  useEffect(() => {
    if (screen!=='app') return
    const iv = setInterval(async()=>{
      try { const r=await authFetch(`${API_URL}/approvals`); const d=await r.json(); setApprovals(d.approvals||[]) } catch{}
    },1500)
    return ()=>clearInterval(iv)
  }, [screen])

  const loadConversations = useCallback(async () => {
    try { const r = await authFetch(`${API_URL}/conversations`); const d = await r.json(); setConversations(d.conversations||[]) } catch {}
  }, [])

  const loadLogs = useCallback(async () => {
    try { const r = await authFetch(`${API_URL}/logs`); const d = await r.json(); setLogs(d.logs||[]) } catch {}
  }, [])

  const refreshStats = useCallback(() => {
    authFetch(`${API_URL}/stats`).then(r=>r.json()).then(setStats).catch(()=>{})
  }, [])

  const addEarning = useCallback(async () => {
    const amount = parseFloat(String(earnAmount).replace(',', '.'))
    if (!amount || amount <= 0) return
    try {
      await authFetch(`${API_URL}/earnings`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ amount, note: earnNote }) })
      setEarnAmount(''); setEarnNote(''); refreshStats()
    } catch {}
  }, [earnAmount, earnNote, refreshStats])

  useEffect(() => {
    if (tab==='stats') refreshStats()
  }, [tab, refreshStats])

  useEffect(() => { if (screen==='app') { loadConversations(); loadLogs() } }, [screen, loadConversations, loadLogs])
  useEffect(() => {
    // Proaktif bildirimlerin (notifier.py) isletim sistemi bildirimi olarak
    // gorunebilmesi icin - tek seferlik izin istegi, kullanici reddederse
    // tekrar tekrar sormuyoruz (tarayici zaten kendisi engelliyor).
    try {
      if (screen==='app' && typeof Notification !== 'undefined' && Notification.permission === 'default') {
        Notification.requestPermission()
      }
    } catch {}
  }, [screen])

  const openConversation = async (id) => {
    try {
      const r = await authFetch(`${API_URL}/conversations/${id}`)
      const d = await r.json()
      if (d.error) return
      setMessages((d.messages||[]).map(m=>({role:m.role==='assistant'?'ales':m.role, content:m.content, id:Math.random()})))
      setActiveConvId(id)
      setTab('chat')
    } catch {}
  }

  const startNewConversation = async () => {
    try {
      const r = await authFetch(`${API_URL}/conversations`, {method:'POST'})
      const d = await r.json()
      setActiveConvId(d.id)
      setMessages([])
      setTab('chat')
      loadConversations()
    } catch {}
  }

  const deleteConversation = async (id, e) => {
    e?.stopPropagation()
    try {
      await authFetch(`${API_URL}/conversations/${id}`, {method:'DELETE'})
      if (id===activeConvId) { setActiveConvId(null); setMessages([]) }
      loadConversations()
    } catch {}
  }

  const playTTS = useCallback(async (text) => {
    if (!text) return
    unlockAudio()
    if (audioElRef.current) {
      try { audioElRef.current.pause() } catch {}
      audioElRef.current = null
    }
    setSpeaking(true)
    try {
      const res = await authFetch(`${API_URL}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      })
      const d = await res.json()
      if (d.ok && d.audio) {
        const audio = new Audio(`data:${d.mime || 'audio/mpeg'};base64,${d.audio}`)
        audioElRef.current = audio
        audio.onended = () => {
          setSpeaking(false)
          audioElRef.current = null
        }
        audio.onerror = () => {
          setSpeaking(false)
          audioElRef.current = null
        }
        const playPromise = audio.play()
        if (playPromise !== undefined) {
          playPromise.then(() => {
            audioUnlockedRef.current = true
            setAudioBlocked(false)
          }).catch((err) => {
            console.warn("Autoplay tarayıcı tarafından duraklatıldı:", err)
            setAudioBlocked(true)
            setSpeaking(false)
          })
        }
      } else {
        setSpeaking(false)
      }
    } catch (err) {
      console.warn("playTTS hatasi:", err)
      setSpeaking(false)
    }
  }, [unlockAudio])

  const stopListening = () => {
    if (recRef.current) {
      try { recRef.current.stop() } catch {}
      recRef.current = null
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try { mediaRecorderRef.current.stop() } catch {}
    }
    if (mediaStreamRef.current) {
      try { mediaStreamRef.current.getTracks().forEach(t => t.stop()) } catch {}
      mediaStreamRef.current = null
    }
    setListening(false)
  }

  const startMediaRecorderFallback = async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("Mikrofon erişimi desteklenmiyor.")
        setListening(false)
        return
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const chunks = []
      let mimeType = 'audio/webm'
      if (typeof MediaRecorder !== 'undefined') {
        if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
          mimeType = 'audio/webm;codecs=opus'
        } else if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm'
        } else if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/mp4')) {
          mimeType = 'audio/mp4'
        }
      }
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          chunks.push(e.data)
        }
      }

      recorder.onstop = async () => {
        setListening(false)
        if (mediaStreamRef.current) {
          try { mediaStreamRef.current.getTracks().forEach(t => t.stop()) } catch {}
          mediaStreamRef.current = null
        }
        if (chunks.length === 0) return
        setTranscribing(true)
        const blob = new Blob(chunks, { type: mimeType || 'audio/webm' })
        const formData = new FormData()
        formData.append('file', blob, 'recording.webm')

        try {
          const resp = await fetch(`${API_URL}/api/transcribe`, {
            method: 'POST',
            headers: isCloud ? { 'X-ALES-Key': getCloudKey() } : {},
            body: formData
          })
          const res = await resp.json()
          if (res.ok && res.text) {
            setInput(prev => prev ? (prev.trim() + ' ' + res.text.trim()) : res.text.trim())
          } else if (res.error) {
            console.warn("Transkripsiyon hatası:", res.error)
          }
        } catch (err) {
          console.warn("Transkripsiyon ağı hatası:", err)
        } finally {
          setTranscribing(false)
        }
      }

      recorder.start(250)
      setListening(true)
    } catch (err) {
      console.warn("Mikrofon hatası:", err)
      setListening(false)
      alert("Mikrofon erişimi reddedildi veya bulunamadı. Lütfen mikrofon izinlerini kontrol edin.")
    }
  }

  const startListening = () => {
    unlockAudio()
    // Electron ortamında Chromium Google Speech API desteği olmadığı için doğrudan MediaRecorder + Whisper kullanılır
    if (isElectron) {
      startMediaRecorderFallback()
      return
    }

    try {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition
      if (!SR) {
        startMediaRecorderFallback()
        return
      }
      const rec = new SR()
      rec.lang = 'tr-TR'
      rec.continuous = false
      rec.interimResults = true
      rec.onresult = e => {
        let transcript = ''
        for (let i = 0; i < e.results.length; i++) {
          transcript += e.results[i][0].transcript
        }
        if (transcript) setInput(transcript)
      }
      rec.onerror = (err) => {
        console.warn("Web Speech API hatası, MediaRecorder yedeğine geçiliyor:", err)
        try { rec.abort() } catch {}
        recRef.current = null
        startMediaRecorderFallback()
      }
      rec.onend = () => {
        setListening(false)
        recRef.current = null
      }
      recRef.current = rec
      rec.start()
      setListening(true)
    } catch (err) {
      console.warn("Web Speech API başlatılamadı, yedeğe geçiliyor:", err)
      startMediaRecorderFallback()
    }
  }

  // ─── AKAN SES KUYRUGU (audio_streamer.py karsiligi) ─────────────
  // Backend cumle cumle mp3 gonderir: {"type":"audio_chunk", seq, last}.
  // Her parca TAM bir mp3'tur (backend birlestirir), yani <audio> her
  // birini tek basina calabilir.
  //
  // NEDEN KUYRUK: parcalar geldigi anda calinsa cumleler ust uste biner.
  // Bir sonrakini ancak oncekinin onended'inde basliyoruz. seq'e gore
  // sirali ekleme yapiyoruz cunku websocket sirasi garantili olsa da
  // sentez sureleri farkli oldugu icin backend'de sira kayabilir.
  const playNextAudio = useCallback(() => {
    if (audioPlayingRef.current) return
    const next = audioQueueRef.current.shift()
    if (!next) {
      audioPlayingRef.current = false
      // Kuyruk bosaldi: gercek olay yoksa rozeti biz indiriyoruz.
      if (!speakingRealRef.current) setSpeaking(false)
      return
    }
    audioPlayingRef.current = true
    try {
      const audio = new Audio(`data:${next.mime||'audio/mpeg'};base64,${next.data}`)
      audioElRef.current = audio
      const done = () => {
        audioPlayingRef.current = false
        audioElRef.current = null
        playNextAudio()
      }
      audio.onended = done
      // HATA DA BITISTIR: onerror'da done cagirmazsak tek bozuk parca
      // butun kuyrugu sonsuza kadar kilitler.
      audio.onerror = done
      audio.play().catch(done)
    } catch {
      audioPlayingRef.current = false
      audioElRef.current = null
    }
  }, [])

  const enqueueAudio = useCallback((chunk) => {
    if (!chunk || !chunk.data) return      // son isaret parcasi bos gelebilir
    const q = audioQueueRef.current
    const seq = Number.isFinite(chunk.seq) ? chunk.seq : q.length
    let i = q.length
    while (i > 0 && (q[i-1].seq ?? 0) > seq) i--
    q.splice(i, 0, {...chunk, seq})
    playNextAudio()
  }, [playNextAudio])

  const stopAudio = useCallback(() => {
    audioQueueRef.current = []
    try { audioElRef.current?.pause() } catch {}
    audioElRef.current = null
    audioPlayingRef.current = false
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState===WebSocket.OPEN) return
    const ws = new WebSocket(isCloud ? `${WS_URL}?key=${encodeURIComponent(getCloudKey())}` : WS_URL)
    wsRef.current = ws
    ws.onopen = ()=>{
      setConnected(true);
      clearTimeout(reconnectRef.current);
      try {
        const savedKeys = JSON.parse(localStorage.getItem('ales_saved_api_keys') || '{}')
        const savedMode = localStorage.getItem('ales_selected_mode') || ''
        if (Object.keys(savedKeys).length > 0 || savedMode) {
          ws.send(JSON.stringify({ type: 'sync_session', keys: savedKeys, mode: savedMode }))
        }
      } catch (e) {}
    }
    ws.onclose = (e)=>{
      setConnected(false); setThinking(false)
      // 4001: backend erisim anahtarini reddetti (cloud modu). Sonsuz
      // yeniden baglanma dongusune girmek yerine kilitli ekrana don.
      if (isCloud && e.code === 4001) {
        try { localStorage.removeItem('ales_cloud_key') } catch {}
        setCloudUnlocked(false)
        return
      }
      reconnectRef.current=setTimeout(connect,3000)
    }
    ws.onerror = ()=>ws.close()
    ws.onmessage = e => {
      const d = JSON.parse(e.data)
      if (d.type==='connected') {
        if (d.setup_needed) { setShowOnboarding(true) }
        setMessages([{role:'ales',content:d.content,id:Date.now()}]); setThinking(false)
      } else if (d.type==='conversation_created') {
        setActiveConvId(d.id)
        loadConversations()
      } else if (d.type==='audio') {
        // ChatGPT'deki gibi aninda ses: backend artik mp3 dosyasi acmiyor,
        // ham ses verisini burada <audio> ile hemen calıyoruz - hangi
        // cihazdan (PC/telefon) bakiliyorsa sesi de o cihaz veriyor.
        try {
          const audio = new Audio(`data:${d.mime||'audio/mpeg'};base64,${d.data}`)
          audio.play().catch(()=>{})
        } catch {}
      } else if (d.type==='earnings') {
        // Canli kazanc guncellemesi: pano acikken sayfayi yenilemeye gerek
        // kalmadan sayac/grafik aninda guncellenir (WebSocket push).
        setStats(p => p ? {...p, earnings: d.summary} : p)
      } else if (d.type==='notification') {
        // Proaktif bildirim: sekme arka planda/simge durumunda bile
        // isletim sistemi bildirimi olarak gosterilsin (Web Notification API).
        // Izin yoksa/reddedilmisse sessizce atlanir, sohbet gecmisindeki
        // [BILDIRIM] mesaji zaten ayrica geliyor.
        try {
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            new Notification(d.title || 'ALES', { body: d.content, icon: '/icon.png' })
          }
        } catch {}
      } else if (d.type==='message') {
        setThinking(false); setActiveTools([])
        // KONUSMA ROZETI: gercek 'speaking' olayi geldiyse (akan ses acik)
        // taklit zamanlayiciyi HIC kurmuyoruz. Kurarsak 4 saniye sonra
        // rozeti indirip hala calan sesle celiskiye duser.
        if (!speakingRealRef.current) {
          setSpeaking(true)
          clearTimeout(speakTimerRef.current)
          speakTimerRef.current = setTimeout(()=>setSpeaking(false),4000)
        }
        setStreamPreview('')
        setMessages(p=>[...p,{role:'ales',content:d.content,id:Date.now()}])
        loadConversations()
        lastAssistantMsgRef.current = d.content || ''
        if (autoSpeakRef.current && d.content) {
          playTTS(d.content)
        }
      } else if (d.type==='speaking') {
        // GERCEK konusma durumu (send_tts_audio / akan ses). Bundan sonra
        // taklit zamanlayici devre disi: kaynak artik backend.
        speakingRealRef.current = true
        clearTimeout(speakTimerRef.current)
        setSpeaking(!!d.on)
        if (!d.on && !audioPlayingRef.current) stopAudio()
      } else if (d.type==='audio_chunk') {
        // Cumle cumle akan ses. Sirali kuyruga koy; oynatici zincirleme
        // calar (bkz. playNextAudio).
        enqueueAudio({data:d.data, mime:d.mime, seq:d.seq})
        if (d.data) setSpeaking(true)
      } else if (d.type==='skill_proposal') {
        // Beceri onerisi (skills_autogrowth). ONAY KULLANICIDA: burada
        // sadece haber veriyoruz, otomatik kabul YOK.
        setSkillProposals(p=>p+1)
        const nm = d.proposal?.name || d.proposal?.id || 'yeni beceri'
        setSysLogs(p=>[{level:'INFO',message:`Beceri önerisi: ${nm} — onay bekliyor (Ayarlar > Gelişmiş > Beceriler)`,time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
        try {
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            new Notification('ALES — beceri önerisi', { body: `${nm} onayını bekliyor`, icon:'/icon.png' })
          }
        } catch {}
      } else if (d.type==='plugin_event') {
        // Eklenti yasam dongusu (plugin_loader). Hata seviyesini ayirmak
        // onemli: "yuklendi" ile "yuklenemedi" ayni renkte gorunmemeli.
        const lvl = d.event==='error' ? 'ERROR' : 'INFO'
        const txt = `Eklenti ${d.plugin||'?'}: ${d.event||'olay'}${d.detail?` — ${d.detail}`:''}`
        setSysLogs(p=>[{level:lvl,message:txt,time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      } else if (d.type==='puter_call') {
        // ─── BIG ALES KOPRUSU ──────────────────────────────────────────
        // Puter girisi TARAYICI TARAFLI oldugu icin cagriyi backend degil
        // BURASI yapar; sonucu ayni WebSocket'ten geri yolluyoruz
        // (bkz. backend/puter_connector.py: call_puter_model).
        // API ANAHTARI YOK: ucreti kullanicinin kendi Puter hesabi karsilar,
        // giris bir kez yapilir ve jeton backend'de sifreli saklanir.
        ;(async () => {
          const reply = (o) => { try { wsRef.current?.send(JSON.stringify({type:'puter_result',request_id:d.request_id,...o})) } catch {} }
          try {
            // ─── file:// KAPISI (artik YEDEK YOL) ─────────────────────
            // file:// bir "opaque origin": puter.js'in giris akisi
            // puter.com'a acilan pencere + postMessage uzerine kurulu ve
            // jetonun yasayacagi bir depo istiyor — ikisi de orada YOK.
            // puter.js bunu "Unsupported Protocol - file://" hatasiyla
            // dogrudan soyluyor.
            //
            // 2026-09-08'DEN ITIBAREN NORMAL YOL BURASI DEGIL: paketlenmis
            // Electron arayuzu artik backend'in http kaynagindan yukluyor
            // (electron-main.js: loadURL('http://localhost:8000')), yani
            // bu sayfanin KENDISI gercek bir origin'de calisiyor ve cagri
            // asagida dogrudan yapilabiliyor. Bu dal, arayuz bir sekilde
            // yine file:// uzerinden acilirsa (elle acilan index.html,
            // eski bir kurulum) Big ALES'in sessizce olmemesi icin
            // duruyor. Sonucu kopru sayfasi POST /puter-bridge/result ile
            // gonderir, o yuzden burada reply ETMIYORUZ (etsek bekleyen
            // cagri erken cozulurdu).
            if (location.protocol === 'file:' && d.bridge) {
              const w = window.open(API_URL + d.bridge, 'ales_puter',
                                    'width=580,height=460')
              if (!w) reply({ok:false,error:'Puter kopru penceresi acilamadi (engellendi)'})
              return
            }
            if (!window.puter?.ai?.chat) { reply({ok:false,error:'Puter SDK yuklenemedi (cevrimdisi olabilir)'}); return }
            // Giris yoksa Puter'in KENDI giris penceresini ac. Bu, istenen
            // "login redirection" davranisi; kullanici bir kez onaylar.
            let username = null
            try {
              // Promise.resolve ZORUNLU: puter.js surumlerinin bir kismi
              // isSignedIn()'i SENKRON boolean, bir kismi Promise olarak
              // veriyor. Await etmezsek Promise nesnesi her zaman "dogru"
              // sayilir, giris ADIMI ATLANIR ve hemen ardindan getUser()
              // patlar — yani mod hic calismaz. Iki sekli de karsiliyoruz.
              const signed = window.puter.auth?.isSignedIn
                ? await Promise.resolve(window.puter.auth.isSignedIn())
                : false
              if (!signed) await window.puter.auth.signIn()
              const u = await window.puter.auth?.getUser?.()
              username = u?.username || null
            } catch (e) {
              reply({ok:false,error:'Puter girisi tamamlanmadi: '+(e?.message||e)}); return
            }
            const res = await window.puter.ai.chat(d.prompt, {
              model: d.model,
              ...(d.system ? { system: d.system } : {}),
            })
            // SDK surumune gore yanit sekli degisebiliyor; hepsini karsila.
            const text = typeof res === 'string' ? res
              : (res?.message?.content ?? res?.text ?? res?.content ?? '')
            const flat = Array.isArray(text)
              ? text.map(p => (typeof p === 'string' ? p : (p?.text || ''))).join('')
              : String(text || '')
            reply({ok:!!flat.trim(), text:flat, error:flat.trim()?null:'Puter bos yanit dondurdu',
                   session:{signed_in:true, username}})
          } catch (e) {
            reply({ok:false,error:String(e?.message||e)})
          }
        })()
      } else if (d.type==='token') {
        // HIZ: model cevabi TOKEN TOKEN geldikce aninda gosterilir (Groq
        // streaming) - kullanici cevabin tamamini beklemek yerine ilk
        // kelimeyi ~aninda gorur. Bu sadece bir ONIZLEME balonu; tool-call
        // turlarinda (bu balon commit edilmeden once) temizlenir, kalici
        // mesaj hala 'message' eventiyle (final) geliyor.
        setThinking(false)
        setStreamPreview(p => p + d.content)
      } else if (d.type==='worldview') {
        setWorldviewText(d.content)
        setTab('worldview')
      } else if (d.type==='tool_use') {
        setThinking(true)
        setStreamPreview('')
        setActiveTools(p=>[...p.filter(t=>t.tool!==d.tool),{tool:d.tool,label:TL[d.tool]||d.tool}])
        setLogs(p=>[{time:new Date().toISOString(),text:TL[d.tool]||d.tool},...p].slice(0,50))
        // Ekrana bakma araclari: otomatik floating moda gec ve tarama
        // animasyonu baslat - boylece ALES ekrani kapatmaz, kullanici
        // ne yaptigini gorebilir
        if (d.tool==='analyze_screen'||d.tool==='take_screenshot'||d.tool==='find_on_screen') {
          setScanning(true)
          if (isElectron && mode==='fullscreen') window.ales?.toggleFloat?.()
        }
      } else if (d.type==='tool_progress') {
        // Uzun suren araclar (Fiverr/Bionluk tarayici otomasyonu gibi)
        // gercek zamanli ilerleme bildirir - "tarayici aciliyor...",
        // "sayfaya gidiliyor..." gibi. Ayni satirin etiketini guncelliyoruz,
        // boylece Ali sadece sonucu degil SURECI de gorur.
        setActiveTools(p=>p.map(t=>t.tool===d.tool?{...t,label:d.message}:t))
      } else if (d.type==='tool_result') {
        setActiveTools(p=>p.filter(t=>t.tool!==d.tool))
        if (d.tool==='analyze_screen'||d.tool==='take_screenshot'||d.tool==='find_on_screen') {
          setScanning(false)
        }
        if (d.tool==='add_pending_approval') {
          // HIZ: 4sn'lik polling'i beklemeden ANINDA yenile - kullanici
          // onay banner'ini gecikmesiz gorsun
          authFetch(`${API_URL}/approvals`).then(r=>r.json()).then(dd=>setApprovals(dd.approvals||[])).catch(()=>{})
        }
      } else if (d.type==='system_log') {
        // GOREV sekmesindeki canli terminal. Backend broadcast_system_log()
        // ile gonderiyordu ama burada HIC karsiligi yoktu - mesajlar sessizce
        // dusuyordu. Artik en yeni ustte olacak sekilde birikiyor.
        setSysLogs(p=>[{level:d.level||'INFO',message:d.message,time:d.time},...p].slice(0,200))
      } else if (d.type==='system_status') {
        // Baslat/durdur sonrasi backend'in ittigi taze durum.
        setSysStatus(d.status||null)
        // Onay bekleyen beceri sayisini SUNUCUDAN aliyoruz. Sadece
        // 'skill_proposal' olaylarini saymak yetmez: kullanici sayfayi
        // yenilediginde sayac sifirlanip bekleyen oneriler gorunmez olur.
        if (d.status && typeof d.status.skill_proposals === 'number') {
          setSkillProposals(d.status.skill_proposals)
        }
      } else if (d.type==='resource_alert') {
        // Kaynak esigi asildi: otomatik kapatma YOK, sadece uyari satiri.
        const b=(d.breached||[]).map(x=>`${(x.metric||'').toUpperCase()} %${x.value}`).join(', ')
        setSysLogs(p=>[{level:'WARN',message:`Kaynak uyarisi: ${b||'esik asildi'}`,time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      } else if (d.type==='sleep_state') {
        setSysLogs(p=>[{level:'INFO',message:d.asleep?'Uyku moduna gecildi':'Uyku modundan cikildi',time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      } else if (d.type==='council') {
        // LLM Meclisi ozeti: kac model yanitladi, hangi strateji, hakem kim.
        setCouncilInfo(d.summary||null)
      } else if (d.type==='error') {
        setThinking(false); setActiveTools([]); setStreamPreview('')
        setMessages(p=>[...p,{role:'error',content:d.content,id:Date.now()}])
      }
    }
    // NOT: enqueueAudio/stopAudio kimlikleri sabit (useCallback bagimliliklari
    // bos), bu yuzden listeye eklemek yeniden baglanmaya YOL ACMAZ.
  }, [enqueueAudio, stopAudio])

  useEffect(() => {
    if (screen==='app') setTimeout(()=>connect(),600)
    return ()=>{ clearTimeout(reconnectRef.current); wsRef.current?.close() }
  }, [screen, connect])

  // ─── GOREV sekmesi: gercek sistem kontrolu ──────────────────────
  // loadStatus  -> TAM anlik goruntu /system/status (isleyiciler + mod +
  //                kaynak + calisma-zamani + modul defteri). Sekmeye
  //                girerken, anahtar cevrildiginde ve baslat/durdur sonrasi.
  // loadLive    -> yalniz degisen sayilar: /resources + /runtime?modules=false.
  //                3 saniyelik poll BUNU cagirir (statik yuku tasimaz).
  // loadSystem  -> durum + profil listesi (profil listesi diskte rglob ile
  //                boyut hesapladigi icin PAHALI -> sadece sekmeye girerken
  //                ve elle YENILE'de cagrilir, poll icinde ASLA).
  const loadStatus = useCallback(() => {
    authFetch(`${API_URL}/system/status`).then(r=>r.json())
      .then(d=>setSysStatus(d)).catch(()=>{})
  }, [])

  const loadSystem = useCallback(() => {
    loadStatus()
    authFetch(`${API_URL}/browser-profiles`).then(r=>r.json())
      .then(d=>setProfiles(d.profiles||[])).catch(()=>{})
  }, [loadStatus])

  // loadLive -> 3 saniyelik yoklamanin CANLI ucu. /system/status her cagrida
  // statik yuku de tasiyordu: mod zinciri, isleyici sozlugu ve 10 kayitlik
  // modul defteri (label+note metinleriyle) dakikada 20 kez yeniden gidiyordu.
  // Artik sadece degisen sayilar cekiliyor: /resources + /runtime?modules=false.
  // Ikisi PARALEL istenir ve mevcut sysStatus'un UZERINE bindirilir; workers /
  // mode / modules KORUNUR (dogrudan setSysStatus(d) yazmak onlari silerdi —
  // ayni tuzak /system/start yanitinda da vardi, bkz. systemAction notu).
  const loadLive = useCallback(() => {
    Promise.all([
      authFetch(`${API_URL}/resources`).then(r=>r.json()),
      authFetch(`${API_URL}/runtime?modules=false`).then(r=>r.json()),
    ]).then(([res, rt]) => {
      setSysStatus(prev => {
        // Bindirecek taban yok (ilk tam cekim henuz donmedi) -> dokunma.
        if (!prev) return prev
        const pausedSet = new Set(rt?.paused || [])
        return {
          ...prev,
          resources: res,
          runtime: {
            ...(prev.runtime||{}),
            ...(rt||{}),
            // Defter lean yanitta GELMEZ. Elimizdekini koruyup yalnizca
            // DURAKLADI rozetlerini taze 'paused' listesine gore yeniden
            // isaretliyoruz; yoksa kaynak baskisiyla duraklatilan bir modul
            // rozetsiz kalirdi (sekmeye yeniden girene kadar).
            modules: (prev.runtime?.modules||[]).map(m=>({...m, paused:pausedSet.has(m.id)})),
          },
        }
      })
    }).catch(()=>{})
  }, [])

  useEffect(() => { if (tab==='tasks') loadSystem() }, [tab, loadSystem])

  // Kaynak degerleri canli kalsin: GOREV sekmesi ACIKKEN 3 saniyede bir
  // tazele. Sekme kapaliyken poll YOK — bos yere istek atmayalim. Esik
  // asimi/uyku gibi OLAYLAR ayrica WebSocket ile aninda geliyor; bu poll
  // sadece surekli degisen sayilar (CPU/RAM/GPU/disk/bosta sayaci) icin.
  useEffect(() => {
    if (tab!=='tasks') return
    const id = setInterval(loadLive, 3000)
    return ()=>clearInterval(id)
  }, [tab, loadLive])

  const systemAction = async (action) => {
    setSysBusy(true)
    try {
      const r = await authFetch(`${API_URL}/system/${action}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(action==='start' ? {profiles:selProfiles} : {})
      })
      const d = await r.json()
      // NOT: /system/start|stop yaniti "status" alaninda SADECE workers
      // sozlugunu doner (tam anlik goruntuyu degil). Dogrudan sysStatus'a
      // yazmak kaynak/runtime bloklarini silerdi; sadece workers'i guncelle,
      // tam tazelemeyi loadSystem() yapar.
      if (d.status) setSysStatus(p=>({...(p||{}), workers:d.status}))
      if (d.ok === false) {
        setSysLogs(p=>[{level:'ERROR',message:d.error||'islem basarisiz',
          time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      }
      loadSystem()
    } catch (e) {
      setSysLogs(p=>[{level:'ERROR',message:String(e),
        time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
    } finally { setSysBusy(false) }
  }

  // ── Faz-3 mod anahtarlari (performance / heavy / headless / sleep) ──
  // Backend'de /system/toggle ZATEN vardi ama arayuzden hic cagrilmiyordu,
  // yani anahtarlara erisim yoktu. Artik buradan cevriliyor.
  const toggleMode = async (which, on) => {
    setSysBusy(true)
    try {
      const r = await authFetch(`${API_URL}/system/toggle`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({which, on})
      })
      const d = await r.json()
      if (d.ok === false) {
        setSysLogs(p=>[{level:'ERROR',message:d.error||'anahtar degistirilemedi',
          time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      }
      // Backend ayrica tum istemcilere 'system_status' yayinliyor; burada
      // yine tazeliyoruz ki anahtari ceviren sekme beklemeden gorsun.
      // Profil listesi degismedigi icin ucuz olan loadStatus yeterli.
      loadStatus()
    } catch (e) {
      setSysLogs(p=>[{level:'ERROR',message:String(e),
        time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
    } finally { setSysBusy(false) }
  }

  // Olen arka plan gorevini elle yeniden baslat (POST /selfheal/restart/{ad}).
  // NEDEN GOREV SEKMESINDE: denetci gorevi kendisi yeniden baslatir, ama
  // MAX_RESTARTS'i doldurup "vazgecti" durumuna dusen bir gorev kendiliginden
  // GERI GELMEZ. O anda elle bir dugme olmazsa zamanlayici sessizce olu kalir
  // ve kullanici bunu ancak hicbir gorev calismadigini fark edince anlar.
  const healRestart = async (name, force) => {
    setSysBusy(true)
    try {
      const r = await authFetch(
        `${API_URL}/selfheal/restart/${encodeURIComponent(name)}${force?'?force=true':''}`,
        { method:'POST' })
      const d = await r.json()
      setSysLogs(p=>[{level:d.ok?'INFO':'ERROR',
        message:`Denetçi: ${name} — ${d.ok?'yeniden başlatıldı':(d.error||'başarısız')}`,
        time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
      loadStatus()
    } catch (e) {
      setSysLogs(p=>[{level:'ERROR',message:String(e),
        time:new Date().toLocaleTimeString('tr-TR')},...p].slice(0,200))
    } finally { setSysBusy(false) }
  }

  const sendMessage = (text) => {
    if (!text || !connected || showOnboarding) return
    setMessages(p=>[...p,{role:'user',content:text,id:Date.now()}])
    setThinking(true)
    setStreamPreview('')
    wsRef.current?.send(JSON.stringify({type:'message',content:text,conversation_id:activeConvId}))
    setTab('chat')
  }

  const send = () => {
    unlockAudio()
    const text = input.trim()
    if (!text || !connected || thinking || showOnboarding) return
    setInput('')
    sendMessage(text)
    inputRef.current?.focus()
  }

  const fmt = d=>d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})

  // Calisma suresi: 5400 -> "1sa 30dk". Saniye/dakika/saat esigine gore kisalir.
  const fmtUptime = (s) => {
    if (s===null || s===undefined) return '—'
    const t = Math.max(0, Math.round(s))
    const h = Math.floor(t/3600), m = Math.floor((t%3600)/60)
    if (h > 0) return `${h}sa ${m}dk`
    if (m > 0) return `${m}dk`
    return `${t}sn`
  }
  const fmtDate = d=>d.toLocaleDateString('tr-TR',{weekday:'long',day:'numeric',month:'long'})

  if (isCloud && !cloudUnlocked) return <CloudGate onOk={()=>setCloudUnlocked(true)} />
  if (screen==='splash') return <Splash onDone={()=>setScreen('app')} />
  if (screen==='setup') return <Setup onDone={()=>setScreen('app')} />
  const isFloat = mode==='floating'
  // HUD, runtime_state'te 'opendex_ui' duraklatilmissa gizlenir (headless
  // modda otomatik duraklatilir — bkz. runtime_state.py:360). Durum
  // bilinmiyorsa GOSTERILIR: bilgi eksikligi yuzunden gorsel geri
  // bildirimi kaybetmek, gereksiz gostermekten daha kotu.
  const hudHidden = Array.isArray(sysStatus?.runtime?.paused)
    ? sysStatus.runtime.paused.includes('opendex_ui')
    : false

  return (
    <div className="app-container" style={{width:'100vw',height:'100vh',background:'#121212',fontFamily:"'Inter',sans-serif",display:'flex',flexDirection:'column',overflow:'hidden',color:'#E4E4E7',userSelect:'none',position:'relative'}}>
      {/* BG */}
      <div style={{position:'absolute',inset:0,backgroundImage:'linear-gradient(rgba(255,255,255,0.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.02) 1px,transparent 1px)',backgroundSize:'52px 52px',pointerEvents:'none'}} />
      <div style={{position:'absolute',top:-400,left:'50%',transform:'translateX(-50%)',width:900,height:700,background:'radial-gradient(ellipse,rgba(255,255,255,0.04) 0%,transparent 70%)',pointerEvents:'none'}} />

      {/* TITLEBAR */}
      <div className="app-titlebar" style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 16px',height:48,background:'#121212',borderBottom:'1px solid rgba(255,255,255,0.12)',flexShrink:0,zIndex:10,WebkitAppRegion:'drag'}}>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <div style={{width:22,height:22,borderRadius:'50%',background:'radial-gradient(circle,#bbbbbb,#ffffff)',boxShadow:'0 0 10px #ffffff',animation:'pulse 2s infinite'}} />
          <span style={{fontFamily:"'Share Tech Mono',monospace",fontSize:16,fontWeight:700,color:'#ffffff',letterSpacing:5}}>ALES</span>
          <span style={{fontSize:10,color:'#A1A1AA',fontFamily:'monospace'}}>v3.0</span>
        </div>
        {!isFloat && <div className="app-titlebar-time" style={{display:'flex',flexDirection:'column',alignItems:'center'}}>
          <span style={{fontFamily:"'Share Tech Mono',monospace",fontSize:16,color:'#E4E4E7',letterSpacing:2}}>{fmt(time)}</span>
          <span style={{fontSize:10,color:'#A1A1AA',letterSpacing:1}}>{fmtDate(time)}</span>
        </div>}
        <div style={{display:'flex',alignItems:'center',gap:8,WebkitAppRegion:'no-drag'}}>
          {speaking && <span style={{fontSize:10,padding:'3px 8px',borderRadius:8,background:'rgba(255,255,255,0.2)',color:'#ffffff',fontFamily:'monospace',animation:'pulse 1s infinite'}}>SES</span>}
          {skillProposals>0 && <span title="Onay bekleyen beceri önerisi" onClick={()=>setTab('settings')} style={{fontSize:10,padding:'3px 8px',borderRadius:8,background:'rgba(255,255,255,0.16)',color:'#ffffff',fontFamily:'monospace',cursor:'pointer'}}>{skillProposals} BECERİ</span>}
          {approvals.length>0 && <span style={{fontSize:10,padding:'3px 8px',borderRadius:8,background:'rgba(200,200,200,0.3)',color:'#ffffff',fontFamily:'monospace',animation:'pulse 1s infinite'}}>{approvals.length} ONAY</span>}
          <div style={{width:8,height:8,borderRadius:'50%',background:connected?'#4ade80':'#666666',boxShadow:connected?'0 0 6px #4ade80':'none'}} />
          <div style={{display:'flex',gap:6}}>
            <button style={{width:28,height:28,borderRadius:6,background:tab==='settings'?'rgba(255,255,255,0.25)':'rgba(255,255,255,0.1)',border:'1px solid rgba(255,255,255,0.25)',color:'#ffffff',fontSize:14,cursor:'pointer',display:'flex',alignItems:'center',justifyContent:'center'}} onClick={()=>setTab(t=>t==='settings'?'chat':'settings')} title="Ayarlar">⚙</button>
            {isElectron && [{i:'⊡',a:()=>window.ales?.toggleFloat?.()},{i:'─',a:()=>window.ales?.minimize?.()},{i:'✕',a:()=>window.ales?.close?.(),r:true}].map((b,idx)=>(
              <button key={idx} style={{width:28,height:28,borderRadius:6,background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.18)',color:b.r?'#ff6b6b':'#ffffff',fontSize:13,cursor:'pointer'}} onClick={b.a}>{b.i}</button>
            ))}
          </div>
        </div>
      </div>

      {/* SETTINGS MODAL (IF OPENED DIRECTLY) */}
      {showSettings && <SettingsPanel onClose={()=>setShowSettings(false)} pendingSkills={skillProposals} onSkillsChange={setSkillProposals} autoSpeak={autoSpeak} onAutoSpeakChange={setAutoSpeak} />}

      {/* ONBOARDING MODAL (TASK 4) */}
      <OnboardingModal isOpen={showOnboarding} onDone={()=>setShowOnboarding(false)} />

      {/* YEREL HUD — OpenDex yerine (ayri surec/pencere yok) */}
      <TalkingDot on={speaking} hidden={hudHidden||isFloat} />
      <HudStrip typing={!!streamPreview} speaking={speaking}
                toolLabel={activeTools[0]?.label || ''}
                chars={streamPreview.length} hidden={hudHidden||isFloat} />

      {/* APPROVALS */}
      {approvals.length>0 && <div style={{background:'#1E1E24',borderBottom:'1px solid rgba(255,255,255,0.15)',padding:'8px 16px',flexShrink:0}}>
        {approvals.map(ap=>(
          <div key={ap.id} style={{padding:'4px 0'}}>
            <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}>
              <span style={{fontSize:13,color:'#E4E4E7',flex:1,cursor:'pointer'}} onClick={()=>setExpandedApproval(p=>p===ap.id?null:ap.id)}>⚠ {ap.description} <span style={{color:'#A1A1AA',fontSize:11}}>({expandedApproval===ap.id?'detayı gizle':'detay'})</span></span>
              <div style={{display:'flex',gap:6}}>
                <button onClick={async()=>{await authFetch(`${API_URL}/approve/${ap.id}`,{method:'POST'});setApprovals(p=>p.filter(a=>a.id!==ap.id))}} style={{padding:'5px 12px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.12)',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}}>ONAYLA</button>
                <button onClick={async()=>{await authFetch(`${API_URL}/approve/${ap.id}`,{method:'DELETE'});setApprovals(p=>p.filter(a=>a.id!==ap.id))}} style={{padding:'5px 12px',border:'1px solid rgba(239,68,68,0.4)',background:'rgba(239,68,68,0.15)',color:'#f87171',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}}>REDDET</button>
              </div>
            </div>
            {expandedApproval===ap.id && <div style={{marginTop:6,marginBottom:4,padding:'8px 12px',background:'#121212',borderRadius:6,fontSize:12,fontFamily:'monospace',color:'#E4E4E7',border:'1px solid rgba(255,255,255,0.1)'}}>
              <div><b style={{color:'#ffffff'}}>işlem:</b> {ap.action}</div>
              <div style={{marginTop:4,whiteSpace:'pre-wrap',wordBreak:'break-all'}}><b style={{color:'#ffffff'}}>parametreler:</b> {JSON.stringify(ap.params, null, 2)}</div>
            </div>}
          </div>
        ))}
      </div>}

      {/* CLOUD LIMITATION BANNER (TASK 4) */}
      {isCloud && (
        <div style={{
          background: 'rgba(59, 130, 246, 0.12)',
          borderBottom: '1px solid rgba(59, 130, 246, 0.3)',
          padding: '8px 16px',
          color: '#93c5fd',
          fontSize: 12,
          fontFamily: 'monospace',
          textAlign: 'center',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 8,
          lineHeight: 1.4
        }}>
          <span>🌐</span>
          <span><b>Bulut Modu:</b> Sadece sohbet, analiz ve belge oluşturma aktiftir. Masaüstü kontrolü için yerel EXE'yi kullanın.</span>
        </div>
      )}

      {/* TABS */}
      <div className="app-tabs-bar" style={{display:'flex',alignItems:'center',padding:'0 12px',background:'#121212',borderBottom:'1px solid rgba(255,255,255,0.12)',flexShrink:0,height:40,gap:6,overflowX:'auto',whiteSpace:'nowrap',maxWidth:'100vw'}}>
        {[
          {id:'chat',label:'SOHBET'},
          {id:'history',label:'GEÇMİŞ'},
          {id:'log',label:'LOG'},
          {id:'worldview',label:'DÜNYA'},
          {id:'tasks',label:'GÖREV'},
          ...(!isCloud ? [{id:'live',label:'CANLI İZLE'}] : []),
          {id:'memory',label:'HAFIZA'},
          {id:'stats',label:'PANO'},
          {id:'status',label:'DURUM'},
          {id:'metrics',label:'METRİKLER'},
          {id:'settings',label:'AYARLAR'},
          {id:'advanced',label:'GELİŞMİŞ'},
        ].map(t=>(
          <button key={t.id} className="app-tab-btn" style={{padding:'6px 12px',border:tab===t.id?'1px solid rgba(255,255,255,0.45)':'1px solid transparent',background:tab===t.id?'rgba(255,255,255,0.18)':'transparent',color:tab===t.id?'#ffffff':'#A1A1AA',fontFamily:'monospace',fontSize:12,fontWeight:tab===t.id?700:500,letterSpacing:1,cursor:'pointer',borderRadius:6,flexShrink:0,transition:'all .15s'}} onClick={()=>setTab(t.id)}>
            {t.label}
          </button>
        ))}
        <div style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:8,flexShrink:0}}>
          <button onClick={startNewConversation} title="Yeni Sohbet" style={{padding:'5px 12px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.12)',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}}>+ YENİ</button>
          <div style={{width:8,height:8,borderRadius:'50%',background:connected?'#4ade80':'#666666',boxShadow:connected?'0 0 6px #4ade80':'none'}} />
          <span style={{fontSize:11,fontFamily:'monospace',color:'#E4E4E7',fontWeight:600}}>{connected?'BAĞLI':'BAĞLANIYOR'}</span>
        </div>
      </div>

      {/* MAIN */}
      <main style={{flex:1,overflow:'hidden',position:'relative',background:'#121212',color:'#E4E4E7'}}>

        {tab==='chat' && <div style={{height:'100%',overflowY:'auto',padding:'14px 16px',display:'flex',flexDirection:'column',gap:12}}>
          {messages.map(m=>(
            <div key={m.id} style={{display:'flex',alignItems:'flex-end',gap:8,animation:'fadeUp .2s ease',justifyContent:m.role==='user'?'flex-end':'flex-start'}}>
              {m.role!=='user' && <div style={{width:28,height:28,borderRadius:'50%',background:'linear-gradient(135deg,#222222,#444444)',border:'1px solid rgba(255,255,255,0.2)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:10,fontWeight:700,color:'#ffffff',flexShrink:0,fontFamily:'monospace'}}>A</div>}
              <div className="chat-message-bubble" style={{maxWidth:'82%',padding:'10px 14px',borderRadius:12,fontSize:14,lineHeight:1.6,whiteSpace:'pre-wrap',wordBreak:'break-word',...(m.role==='user'?{background:'rgba(255,255,255,0.1)',border:'1px solid rgba(255,255,255,0.18)',color:'#ffffff',borderBottomRightRadius:3}:m.role==='error'?{background:'rgba(239,68,68,0.15)',border:'1px solid rgba(239,68,68,0.3)',color:'#f87171',borderBottomLeftRadius:3}:{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.15)',color:'#E4E4E7',borderBottomLeftRadius:3})}}>
                {renderMessageContent(m.content)}
              </div>
              {m.role!=='user' && (
                <button
                  onClick={()=>{
                    unlockAudio()
                    setAudioBlocked(false)
                    if (speaking) {
                      stopAudio()
                      setSpeaking(false)
                    } else {
                      playTTS(m.content)
                    }
                  }}
                  title={speaking ? "Sesi Durdur" : "Sesli Oku"}
                  style={{
                    background:'rgba(255,255,255,0.08)',
                    border:'1px solid rgba(255,255,255,0.15)',
                    color: speaking ? '#4ade80' : '#E4E4E7',
                    cursor:'pointer',
                    fontSize:13,
                    padding:'5px 8px',
                    borderRadius:6,
                    flexShrink:0,
                    marginBottom:2,
                    transition:'all .15s'
                  }}
                  onMouseEnter={e=>e.currentTarget.style.color='#fff'}
                  onMouseLeave={e=>e.currentTarget.style.color=speaking?'#4ade80':'#E4E4E7'}
                >
                  {speaking ? '⏹️' : '🔊'}
                </button>
              )}
              {m.role==='user' && <div style={{width:28,height:28,borderRadius:'50%',background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.18)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:8,color:'#E4E4E7',fontWeight:600,flexShrink:0,fontFamily:'monospace'}}>SEN</div>}
            </div>
          ))}
          {activeTools.map(t=>(
            <div key={t.tool} style={{display:'flex',alignItems:'center',gap:7,paddingLeft:33}}>
              <span style={{color:'#cccccc',fontSize:10,animation:'spin 1s linear infinite',display:'inline-block'}}>◌</span>
              <span style={{fontSize:10,color:'#cccccc',fontFamily:'monospace'}}>{t.label}</span>
            </div>
          ))}
          {streamPreview && <div style={{display:'flex',alignItems:'flex-end',gap:7,animation:'fadeUp .2s ease'}}>
            <div style={{width:26,height:26,borderRadius:'50%',background:'linear-gradient(135deg,#111111,#222222)',border:'1px solid #ffffff33',display:'flex',alignItems:'center',justifyContent:'center',fontSize:9,fontWeight:700,color:'#cccccc',flexShrink:0,fontFamily:'monospace'}}>A</div>
            <div style={{maxWidth:'79%',padding:'8px 12px',borderRadius:12,fontSize:13,lineHeight:1.65,whiteSpace:'pre-wrap',wordBreak:'break-word',background:'rgba(255,255,255,0.07)',border:'1px solid rgba(255,255,255,0.15)',color:'#f0f0f0',borderBottomLeftRadius:3}}>
              {streamPreview}<TypingCursor active />
            </div>
          </div>}
          {thinking&&activeTools.length===0&&!streamPreview && <div style={{display:'flex',alignItems:'flex-end',gap:7}}>
            <div style={{width:26,height:26,borderRadius:'50%',background:'linear-gradient(135deg,#111111,#222222)',border:'1px solid #ffffff33',display:'flex',alignItems:'center',justifyContent:'center',fontSize:9,fontWeight:700,color:'#cccccc',fontFamily:'monospace'}}>A</div>
            <div style={{display:'flex',gap:4,padding:'8px 12px',background:'rgba(255,255,255,0.06)',border:'1px solid rgba(255,255,255,0.12)',borderRadius:12,borderBottomLeftRadius:3}}>
              {[0,1,2].map(i=><span key={i} style={{color:'#cccccc',fontSize:6,animation:`d${i+1} 1.2s infinite`}}>●</span>)}
            </div>
          </div>}
          <div ref={bottomRef} />
        </div>}

        {tab==='history' && <div style={{height:'100%',overflowY:'auto',padding:'14px 16px',display:'flex',flexDirection:'column',gap:8}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
            <span style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2}}>SOHBETLER — {conversations.length}</span>
            <button onClick={startNewConversation} style={{padding:'6px 14px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.12)',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}}>+ YENİ SOHBET</button>
          </div>
          {conversations.length===0 && <div style={{color:'#A1A1AA',fontSize:13,fontFamily:'monospace',textAlign:'center',marginTop:40}}>Henüz sohbet yok.</div>}
          {conversations.map(c=>(
            <div key={c.id} onClick={()=>openConversation(c.id)} style={{padding:'12px 14px',background:c.id===activeConvId?'rgba(255,255,255,0.12)':'#1E1E24',border:`1px solid ${c.id===activeConvId?'rgba(255,255,255,0.4)':'rgba(255,255,255,0.12)'}`,borderRadius:8,cursor:'pointer',display:'flex',justifyContent:'space-between',alignItems:'center',gap:10}}>
              <div style={{minWidth:0,flex:1}}>
                <div style={{fontSize:14,fontWeight:600,color:'#ffffff',fontFamily:'monospace',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{c.title}</div>
                <div style={{fontSize:12,color:'#A1A1AA',marginTop:3,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{c.preview}</div>
              </div>
              <button onClick={(e)=>deleteConversation(c.id,e)} style={{flexShrink:0,width:26,height:26,border:'1px solid rgba(255,255,255,0.2)',background:'transparent',color:'#E4E4E7',borderRadius:6,cursor:'pointer',fontSize:13}}>✕</button>
            </div>
          ))}
        </div>}

        {tab==='log' && <div style={{height:'100%',overflowY:'auto',padding:'14px 16px',display:'flex',flexDirection:'column',gap:6}}>
          <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2,marginBottom:8}}>ALES NE YAPTI — SON {logs.length}</div>
          {logs.length===0 && <div style={{color:'#A1A1AA',fontSize:13,fontFamily:'monospace',textAlign:'center',marginTop:40}}>Henüz kayıt yok.</div>}
          {logs.map((l,i)=>(
            <div key={i} style={{display:'flex',gap:10,alignItems:'baseline',padding:'6px 0',borderBottom:'1px solid rgba(255,255,255,0.06)'}}>
              <span style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',flexShrink:0,width:46}}>{new Date(l.time).toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'})}</span>
              <span style={{fontSize:14,color:'#E4E4E7',lineHeight:1.5}}>{l.text}</span>
            </div>
          ))}
        </div>}

        {tab==='worldview' && <div style={{height:'100%',overflowY:'auto',display:'flex',flexDirection:'column'}}>
          <div style={{position:'relative',height:260,flexShrink:0,overflow:'hidden',borderRadius:0,borderBottom:'1px solid rgba(255,255,255,0.12)'}}>
            <Worldview3D data={worldviewText} />
            <div style={{position:'absolute',bottom:12,right:12,display:'flex',gap:6,zIndex:3}}>
              <button style={{padding:'6px 12px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(0,0,0,0.85)',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}} onClick={()=>sendMessage('Guncel worldview bilgisini getir')}>↻ YENİLE</button>
            </div>
          </div>
          <div style={{padding:'14px 16px',display:'flex',flexDirection:'column',gap:10}}>
            {worldviewText ? (
              worldviewText.split('\n\n').filter(s=>s.trim()).map((sec,i)=>(
                <div key={i} style={{padding:'12px 14px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:8}}>
                  {sec.split('\n').map((line,j)=>(
                    <div key={j} style={{fontSize:13,fontFamily:'monospace',lineHeight:1.7,color:line.startsWith('[')&&line.includes(']:')?'#ffffff':line.startsWith('=')?'rgba(255,255,255,0.3)':'#E4E4E7'}}>{line}</div>
                  ))}
                </div>
              ))
            ) : (
              <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(140px, 1fr))',gap:10}}>
                {[
                  {l:'Haberler',a:"Turkiyeden guncel haberleri getir"},
                  {l:'Döviz',a:'Guncel doviz kurlarini getir'},
                  {l:'Kripto',a:'Bitcoin fiyatlarini getir'},
                  {l:'Hava',a:'Istanbul hava durumunu getir'},
                  {l:'Pencereler',a:'Açık pencereleri listele'},
                  {l:'Sistem',a:'Sistem bilgilerini goster'},
                ].map(item=>(
                  <button key={item.l} style={{padding:'16px 12px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.15)',borderRadius:8,color:'#E4E4E7',fontSize:13,fontWeight:600,cursor:'pointer',fontFamily:'monospace',transition:'all .15s'}} onClick={()=>sendMessage(item.a)}>{item.l}</button>
                ))}
              </div>
            )}
          </div>
        </div>}

        {tab==='tasks' && <div style={{height:'100%',overflowY:'auto',padding:'16px 20px',background:'#121212',color:'#E4E4E7',display:'flex',flexDirection:'column',gap:16,lineHeight:1.5}}>
          {/* ── Baslik + yenile ── */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <span style={{fontSize:15,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2}}>SİSTEM KONTROLÜ</span>
            <button onClick={loadSystem} style={{padding:'7px 16px',border:'1px solid rgba(255,255,255,0.25)',background:'#1E1E24',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:13,fontWeight:600,fontFamily:'monospace',transition:'all .15s'}}>↻ YENİLE</button>
          </div>

          {/* ── Isleyici durum kartlari (canli) ── */}
          <div style={{display:'flex',gap:10}}>
            {[
              {k:'scheduler',l:'ZAMANLAYICI'},
              {k:'notifier',l:'BİLDİRİMCİ'},
              {k:'resource_monitor',l:'KAYNAK İZLEYİCİ'},
            ].map(w=>{
              const on = !!(sysStatus?.workers?.[w.k])
              return (
                <div key={w.k} style={{flex:1,padding:'14px 12px',background:'#1E1E24',border:`1px solid ${on?'rgba(74,222,128,0.4)':'rgba(255,255,255,0.12)'}`,borderRadius:8,textAlign:'center'}}>
                  <div style={{width:10,height:10,borderRadius:'50%',background:on?'#4ade80':'#666666',boxShadow:on?'0 0 8px #4ade80':'none',margin:'0 auto 8px'}} />
                  <div style={{fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace',letterSpacing:1}}>{w.l}</div>
                  <div style={{fontSize:12,fontWeight:600,color:on?'#4ade80':'#A1A1AA',fontFamily:'monospace',marginTop:4}}>{on?'ÇALIŞIYOR':'DURDU'}</div>
                </div>
              )
            })}
          </div>

          {/* ── Kaynak kullanimi (izleyici acikken doluyor) ── */}
          {sysStatus?.resources && !sysStatus.resources.unavailable && (
            <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)'}}>
              <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10}}>
                KAYNAK ({sysStatus.resources.scope==='self'?'ALES süreci':'sistem geneli'})
                {sysStatus.resources.degraded && <span style={{color:'#f59e0b',fontWeight:600}}> · DÜŞÜK TÜKETİM</span>}
                {sysStatus.resources.running===false && <span style={{color:'#A1A1AA'}}> · İZLEYİCİ DURDU</span>}
              </div>
              <div style={{display:'flex',gap:10}}>
                {[
                  {k:'cpu', v:sysStatus.resources.values?.cpu, lim:sysStatus.resources.thresholds?.cpu, t:'CPU kullanımı'},
                  {k:'ram', v:sysStatus.resources.values?.ram, lim:sysStatus.resources.thresholds?.ram, t:'RAM kullanımı'},
                  {k:'gpu', v:sysStatus.resources.values?.gpu, lim:sysStatus.resources.thresholds?.gpu, t:'GPU her zaman CİHAZ GENELİ ölçülür'},
                  {k:'disk',v:sysStatus.resources.disk, lim:null, t:'Disk cihaz geneli ölçülür'},
                ].map(({k,v,lim,t})=>{
                  if (v===null||v===undefined) return (
                    <div key={k} title={t} style={{flex:1,padding:'12px 10px',background:'rgba(255,255,255,0.05)',border:'1px solid rgba(255,255,255,0.12)',borderRadius:8,textAlign:'center'}}>
                      <div style={{fontSize:18,fontWeight:700,fontFamily:'monospace',color:'#A1A1AA'}}>—</div>
                      <div style={{fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace',marginTop:4}}>{k.toUpperCase()}</div>
                    </div>
                  )
                  const over = lim!=null && v>lim
                  return (
                    <div key={k} title={t} style={{flex:1,padding:'12px 10px',background:'rgba(255,255,255,0.05)',border:`1px solid ${over?'rgba(245,158,11,0.6)':'rgba(255,255,255,0.15)'}`,borderRadius:8,textAlign:'center'}}>
                      <div style={{fontSize:18,fontWeight:700,fontFamily:'monospace',color:over?'#f59e0b':'#ffffff'}}>%{v}</div>
                      <div style={{height:5,background:'rgba(255,255,255,0.15)',borderRadius:3,margin:'8px 0 6px',overflow:'hidden'}}>
                        <div style={{height:'100%',width:`${Math.min(100,Math.max(0,v))}%`,background:over?'#f59e0b':'#ffffff',transition:'width .4s'}} />
                      </div>
                      <div style={{fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace'}}>{k.toUpperCase()}{lim!=null?` / %${lim}`:''}</div>
                    </div>
                  )
                })}
              </div>
              {(sysStatus.resources.ram_mb!=null || sysStatus.resources.procs!=null) && (
                <div style={{fontSize:13,fontWeight:500,color:'#E4E4E7',fontFamily:'monospace',marginTop:10}}>
                  ALES: <b style={{color:'#ffffff'}}>{sysStatus.resources.ram_mb ?? '—'} MB</b> · <b style={{color:'#ffffff'}}>{sysStatus.resources.procs ?? '—'} süreç</b>
                  {sysStatus.resources.gpu_mem_used_mb!=null &&
                    ` · GPU ${sysStatus.resources.gpu_mem_used_mb}/${sysStatus.resources.gpu_mem_total_mb} MB`}
                  {sysStatus.resources.gpu_backend && ` · ${sysStatus.resources.gpu_backend}`}
                </div>
              )}
            </div>
          )}

          {/* ── MODLAR: Faz-3 anahtarlari (backend: POST /system/toggle) ── */}
          {sysStatus?.runtime && !sysStatus.runtime.unavailable && (
            <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)'}}>
              <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10,display:'flex',justifyContent:'space-between',gap:8}}>
                <span>MODLAR</span>
                <span style={{color:'#A1A1AA',fontSize:13,fontWeight:500,textAlign:'right'}}>
                  {sysStatus.mode?.label ? `${sysStatus.mode.label} · ` : ''}
                  ÇALIŞMA {fmtUptime(sysStatus.runtime.uptime_s)}
                  {sysStatus.runtime.asleep
                    ? <span style={{color:'#f59e0b'}}> · UYUYOR</span>
                    : (sysStatus.runtime.idle_s!=null ? ` · boşta ${Math.round(sysStatus.runtime.idle_s)}sn` : '')}
                </span>
              </div>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>
                {[
                  {k:'performance',l:'DÜŞÜK KAYNAK (Low Resource)',  f:'performance_mode',s:'düşük tüketim',  d:'Düşük Kaynak Modu: Ağır yerel modüller duraklatılır, işlem buluta kayar, log seviyesi ERROR olur.'},
                  {k:'heavy',      l:'AĞIR (HEAVY)',f:'heavy_mode',      s:'maliyet artar',  d:'En güçlü modeller paralel çalışır, Fast Path kapanır. Token maliyeti belirgin şekilde artar.'},
                  {k:'headless',   l:'ARAYÜZSÜZ',   f:'headless_mode',   s:'ekran kapalı',   d:'Durum kaydedilir; arayüzü gerçekten gizleyecek pencere bağlantısı henüz yok.'},
                  {k:'sleep',      l:'UYKU İZNİ',   f:'sleep_mode',      s:null,             d:'Boşta kalınca otomatik uyku izni. Kapatılırsa ALES hiç uyumaz.'},
                ].map(m=>{
                  const on = !!sysStatus.runtime[m.f]
                  const sub = m.k==='sleep'
                    ? `${Math.round((sysStatus.runtime.sleep_after_s||300)/60)} dk boştan sonra`
                    : m.s
                  return (
                    <button key={m.k} disabled={sysBusy} title={m.d}
                      onClick={()=>{
                        if (m.k==='heavy' && !on && !window.confirm(
                          'AĞIR mod en güçlü modelleri paralel çalıştırır ve token maliyeti belirgin şekilde artar. Açılsın mı?')) return
                        toggleMode(m.k, !on)
                      }}
                      style={{display:'flex',alignItems:'center',gap:10,padding:'12px 14px',textAlign:'left',
                        background:on?'rgba(255,255,255,0.12)':'rgba(255,255,255,0.04)',
                        border:`1px solid ${on?'rgba(255,255,255,0.35)':'rgba(255,255,255,0.12)'}`,
                        borderRadius:8,cursor:sysBusy?'default':'pointer',opacity:sysBusy?0.55:1,
                        fontFamily:'monospace',transition:'all .15s'}}>
                      <span style={{width:24,height:14,borderRadius:7,flexShrink:0,position:'relative',
                        background:on?'#ffffff':'rgba(255,255,255,0.2)',transition:'background .2s'}}>
                        <span style={{position:'absolute',top:2,left:on?12:2,width:10,height:10,borderRadius:'50%',
                          background:on?'#000000':'#aaaaaa',transition:'left .2s'}} />
                      </span>
                      <span style={{minWidth:0}}>
                        <span style={{display:'block',fontSize:13,fontWeight:600,letterSpacing:0.5,color:on?'#ffffff':'#E4E4E7'}}>{m.l}</span>
                        <span style={{display:'block',fontSize:12,color:on?'#E4E4E7':'#A1A1AA',marginTop:2}}>{sub}</span>
                      </span>
                    </button>
                  )
                })}
              </div>

              {/* Modul kayit defteri */}
              {(sysStatus.runtime.modules||[]).length>0 && (
                <div style={{marginTop:14}}>
                  <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:8}}>MODÜLLER</div>
                  <div style={{display:'flex',flexWrap:'wrap',gap:8}}>
                    {sysStatus.runtime.modules.map(md=>(
                      <span key={md.id} title={md.note||''}
                        style={{fontSize:13,fontWeight:600,fontFamily:'monospace',padding:'6px 12px',borderRadius:6,
                          border:`1px solid ${md.paused?'rgba(245,158,11,0.4)':(md.available?'rgba(255,255,255,0.22)':'rgba(255,255,255,0.12)')}`,
                          background:md.paused?'rgba(245,158,11,0.2)':(md.available?'rgba(255,255,255,0.1)':'rgba(255,255,255,0.05)'),
                          color:md.paused?'#fbbf24':(md.available?'#ffffff':'#A1A1AA')}}>
                        {md.label}{md.paused?' · DURAKLADI':(md.available?'':' · YOK')}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── DENETCI (self_heal): arka plan gorevleri gercekten yasiyor mu ── */}
          {sysStatus?.selfheal && !sysStatus.selfheal.error && (
            <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)'}}>
              <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10,display:'flex',justifyContent:'space-between',gap:8}}>
                <span>DENETÇİ</span>
                <span style={{color:sysStatus.selfheal.running?'#4ade80':'#f59e0b',fontSize:13,fontWeight:600}}>
                  {sysStatus.selfheal.running?'✓ İZLİYOR':'DENETÇİ DURDU'}
                  {(sysStatus.selfheal.given_up||[]).length>0 &&
                    <span style={{color:'#f87171'}}> · {sysStatus.selfheal.given_up.length} VAZGEÇİLDİ</span>}
                </span>
              </div>
              <div style={{display:'flex',flexDirection:'column',gap:8}}>
                {(sysStatus.selfheal.workers||[]).length===0 && (
                  <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace'}}>Denetime kayıtlı görev yok.</div>
                )}
                {(sysStatus.selfheal.workers||[]).map(w=>{
                  const col = w.given_up ? '#ef4444' : (w.alive ? '#4ade80' : '#f59e0b')
                  return (
                    <div key={w.name} style={{display:'flex',alignItems:'center',gap:12,padding:'12px 14px',
                      background:'rgba(255,255,255,0.05)',
                      border:`1px solid ${w.given_up?'rgba(239,68,68,0.4)':'rgba(255,255,255,0.14)'}`,
                      borderRadius:8,fontFamily:'monospace'}}>
                      <span style={{width:10,height:10,borderRadius:'50%',background:col,boxShadow:`0 0 8px ${col}`,flexShrink:0}} />
                      <span style={{flex:1,minWidth:0}}>
                        <span style={{display:'block',fontSize:14,fontWeight:600,color:'#ffffff'}}>
                          {w.name}
                          {w.critical && <span style={{fontSize:11,fontWeight:700,color:'#f59e0b',marginLeft:8,letterSpacing:1}}>KRİTİK</span>}
                        </span>
                        <span style={{display:'block',fontSize:13,fontWeight:500,color:w.alive?'#4ade80':'#A1A1AA',marginTop:3}}>
                          {w.given_up ? 'vazgeçildi — elle başlatılmalı'
                            : (w.alive ? 'çalışıyor / canlı' : 'ölü, denetçi deneyecek')}
                          {w.restarts_in_window>0 && <span style={{color:'#A1A1AA'}}> · {w.restarts_in_window}/{w.max_restarts} yeniden başlatma</span>}
                          {!w.alive && w.next_try_in_s>0 && <span style={{color:'#A1A1AA'}}> · {w.next_try_in_s}sn sonra</span>}
                        </span>
                        {w.last_error && (
                          <span style={{display:'block',fontSize:12,color:'#f87171',marginTop:4,
                            whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}} title={w.last_error}>
                            Hata: {w.last_error}
                          </span>
                        )}
                      </span>
                      {!w.alive && (
                        <button disabled={sysBusy} onClick={()=>healRestart(w.name, !!w.given_up)}
                          title={w.given_up?'Vazgeçme sayacını sıfırlar ve görevi yeniden başlatır.':'Görevi hemen yeniden başlatır.'}
                          style={{padding:'6px 14px',border:'1px solid rgba(255,255,255,0.3)',
                            background:'rgba(255,255,255,0.12)',color:sysBusy?'#777':'#ffffff',borderRadius:6,
                            cursor:sysBusy?'default':'pointer',fontSize:13,fontWeight:600,fontFamily:'monospace',flexShrink:0}}>
                          ↻ BAŞLAT
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:10,lineHeight:1.5}}>
                Denetçi yalnızca arka plan görevlerini yeniden başlatır. Kendi kodunu
                değiştirmez, kendini kopyalamaz, ALES sürecini yeniden başlatmaz.
              </div>
            </div>
          )}
          {sysStatus?.selfheal?.error && (
            <div style={{fontSize:13,color:'#f87171',fontFamily:'monospace',padding:'10px 12px',background:'rgba(239,68,68,0.1)',borderRadius:6}}>
              Denetçi durumu okunamadı: {sysStatus.selfheal.error}
            </div>
          )}

          {/* ── Bekleyen beceri onerileri (skills_autogrowth) ── */}
          {(sysStatus?.skill_proposals > 0 || skillProposals > 0) && (
            <button onClick={()=>setTab('settings')}
              style={{display:'flex',alignItems:'center',gap:12,padding:'14px 16px',textAlign:'left',
                background:'#1E1E24',border:'1px solid rgba(255,255,255,0.3)',
                borderRadius:8,cursor:'pointer',fontFamily:'monospace'}}>
              <span style={{fontSize:18,color:'#ffffff'}}>✦</span>
              <span style={{flex:1,minWidth:0}}>
                <span style={{display:'block',fontSize:14,fontWeight:700,color:'#ffffff',letterSpacing:1}}>
                  {sysStatus?.skill_proposals ?? skillProposals} BECERİ ÖNERİSİ BEKLİYOR
                </span>
                <span style={{display:'block',fontSize:13,color:'#A1A1AA',marginTop:4}}>
                  AYARLAR → GELİŞMİŞ → BECERİ ile onayla veya reddet. Onaylanmadan hiçbiri kullanılmaz.
                </span>
              </span>
              <span style={{fontSize:16,color:'#ffffff',fontWeight:700,flexShrink:0}}>→</span>
            </button>
          )}

          {/* ── Tarayici profilleri: secim kutulari ── */}
          <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10}}>
              <span style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5}}>TARAYICI PROFİLLERİ — {profiles.length}</span>
              {profiles.length>0 && (
                <button onClick={()=>setSelProfiles(selProfiles.length===profiles.length?[]:profiles.map(p=>p.id))}
                  style={{padding:'5px 12px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.1)',color:'#ffffff',borderRadius:6,cursor:'pointer',fontSize:12,fontWeight:600,fontFamily:'monospace'}}>
                  {selProfiles.length===profiles.length?'HİÇBİRİ':'HEPSİ'}
                </button>
              )}
            </div>
            {profiles.length===0 && (
              <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',padding:'10px 0'}}>
                Kayıtlı profil yok. Profiller %APPDATA%\ALES\browser_profiles\profiles.json içinde tutulur.
              </div>
            )}
            <div style={{display:'flex',flexDirection:'column',gap:8}}>
              {profiles.map(p=>{
                const on = selProfiles.includes(p.id)
                return (
                  <label key={p.id} style={{display:'flex',alignItems:'center',gap:12,padding:'12px 14px',background:on?'rgba(255,255,255,0.1)':'rgba(255,255,255,0.04)',border:`1px solid ${on?'rgba(255,255,255,0.35)':'rgba(255,255,255,0.12)'}`,borderRadius:8,cursor:'pointer'}}>
                    <input type="checkbox" checked={on} onChange={()=>setSelProfiles(s=>on?s.filter(x=>x!==p.id):[...s,p.id])} style={{accentColor:'#fff',cursor:'pointer',width:18,height:18}} />
                    <div style={{flex:1,minWidth:0}}>
                      <div style={{fontSize:14,fontWeight:600,color:'#ffffff',fontFamily:'monospace',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{p.label||p.id}</div>
                      {p.note && <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:3}}>{p.note}</div>}
                    </div>
                    <span style={{fontSize:13,fontWeight:600,color:p.exists?'#E4E4E7':'#888888',fontFamily:'monospace'}}>{p.exists?`${p.size_mb} MB`:'boş'}</span>
                  </label>
                )
              })}
            </div>
          </div>

          {/* ── BASLAT / DURDUR ── */}
          <div style={{display:'flex',gap:12}}>
            <button disabled={sysBusy} onClick={()=>systemAction('start')} style={{flex:1,padding:'14px',border:'1px solid rgba(255,255,255,0.4)',background:sysBusy?'rgba(255,255,255,0.06)':'#ffffff',color:sysBusy?'#888888':'#000000',borderRadius:8,cursor:sysBusy?'default':'pointer',fontSize:14,fontWeight:700,fontFamily:'monospace',letterSpacing:2}}>
              {sysBusy?'...':'▶ BAŞLAT'}
            </button>
            <button disabled={sysBusy} onClick={()=>systemAction('stop')} style={{flex:1,padding:'14px',border:'1px solid rgba(255,255,255,0.25)',background:'#1E1E24',color:sysBusy?'#888888':'#ffffff',borderRadius:8,cursor:sysBusy?'default':'pointer',fontSize:14,fontWeight:700,fontFamily:'monospace',letterSpacing:2}}>
              ■ DURDUR
            </button>
          </div>

          {/* ── Canli sistem logu (WebSocket) ── */}
          <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)',flex:1,minHeight:160}}>
            <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10}}>CANLI LOG</div>
            <div style={{background:'#121212',border:'1px solid rgba(255,255,255,0.15)',borderRadius:8,padding:'12px 14px',maxHeight:240,overflowY:'auto',display:'flex',flexDirection:'column',gap:6}}>
              {sysLogs.length===0 && <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace'}}>Henüz olay yok. BAŞLAT/DURDUR ile işlem yapın.</div>}
              {sysLogs.map((l,i)=>(
                <div key={i} style={{fontSize:13,fontFamily:'monospace',display:'flex',gap:10,lineHeight:1.5}}>
                  <span style={{color:'#A1A1AA',flexShrink:0,fontWeight:500}}>{l.time}</span>
                  <span style={{color:l.level==='ERROR'?'#f87171':l.level==='WARN'?'#fbbf24':'#4ade80',fontWeight:700,flexShrink:0}}>{l.level}</span>
                  <span style={{color:'#E4E4E7',wordBreak:'break-word',fontWeight:500}}>{l.message}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Hızlı Komutlar ── */}
          <div style={{background:'#1E1E24',padding:'14px 16px',borderRadius:8,border:'1px solid rgba(255,255,255,0.12)'}}>
            <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10}}>HIZLI KOMUTLAR</div>
            <div style={{display:'flex',flexDirection:'column',gap:8}}>
              {[
                {l:'Masaüstü Not Defteri Aç ve Test Et',a:'Not defterini aç ve Merhaba ALES yaz'},
                {l:'Açık Pencereleri Listele',a:'Açık pencereleri listele'},
                {l:'Ekran Görüntüsü Al',a:'Ekran görüntüsü al'},
                {l:'Sistem Kaynak Durumunu Göster',a:'Sistem bilgilerini göster'},
              ].map(item=>(
                <button key={item.l} style={{padding:'12px 16px',background:'rgba(255,255,255,0.06)',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8,color:'#E4E4E7',fontSize:13,fontWeight:600,cursor:'pointer',fontFamily:'monospace',textAlign:'left',transition:'all .15s'}} onClick={()=>sendMessage(item.a)}>{item.l}</button>
              ))}
            </div>
          </div>
        </div>}

        {tab==='live' && <div style={{height:'100%',overflowY:'auto',padding:'16px 20px',background:'#121212',color:'#E4E4E7',display:'flex',flexDirection:'column',gap:16,lineHeight:1.5}}>
          {/* Header */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:10}}>
            <div style={{display:'flex',alignItems:'center',gap:12}}>
              <span style={{fontSize:15,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2}}>CANLI EKRAN VE AKTİVİTE İZLEME</span>
              <span style={{
                display:'inline-flex',alignItems:'center',gap:6,padding:'4px 12px',borderRadius:20,fontSize:12,fontWeight:600,fontFamily:'monospace',
                background: streamActive ? 'rgba(74,222,128,0.15)' : 'rgba(255,255,255,0.08)',
                color: streamActive ? '#4ade80' : '#A1A1AA',
                border: `1px solid ${streamActive ? 'rgba(74,222,128,0.4)' : 'rgba(255,255,255,0.15)'}`
              }}>
                <span style={{width:8,height:8,borderRadius:'50%',background:streamActive?'#4ade80':'#888888',boxShadow:streamActive?'0 0 6px #4ade80':'none'}} />
                {streamActive ? 'CANLI YAYINDA (Görev Aktif)' : 'BOŞTA (Bekleniyor)'}
              </span>
            </div>
            {streamTasks.length > 0 && (
              <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                {streamTasks.map((t, i) => (
                  <span key={i} style={{fontSize:12,fontWeight:600,fontFamily:'monospace',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.2)',padding:'4px 10px',borderRadius:6,color:'#ffffff'}}>
                    ⚙ {t}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Main 2-column layout */}
          <div style={{display:'flex',gap:16,flex:1,minHeight:450,flexWrap:'wrap'}}>
            {/* Screen Frame Display (Left 60%) */}
            <div style={{flex:'3 1 450px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16,display:'flex',flexDirection:'column'}}>
              <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:12,display:'flex',justifyContent:'space-between'}}>
                <span>EKRAN AKIŞI (640x360 / {streamActive ? '8 FPS' : '4 FPS'})</span>
                <span style={{fontSize:12,color:streamActive ? '#4ade80' : '#A1A1AA'}}>{streamActive ? 'Görev yürütülüyor (8 FPS)' : 'Canlı önizleme (Boşta / 4 FPS)'}</span>
              </div>
              <div style={{flex:1,display:'flex',alignItems:'center',justifyContent:'center',background:'#121212',borderRadius:8,border:'1px solid rgba(255,255,255,0.08)',overflow:'hidden',minHeight:360,position:'relative'}}>
                {streamFrame ? (
                  <div style={{position:'relative',width:'100%',height:'100%',display:'flex',alignItems:'center',justifyContent:'center'}}>
                    <img src={streamFrame} alt="Live Stream" style={{width:'100%',height:'auto',maxHeight:'100%',objectFit:'contain',display:'block'}} />
                    {!streamActive && (
                      <div style={{position:'absolute',top:10,left:10,background:'rgba(0,0,0,0.75)',border:'1px solid rgba(255,255,255,0.2)',padding:'4px 10px',borderRadius:6,fontSize:11,fontWeight:600,fontFamily:'monospace',color:'#A1A1AA',backdropFilter:'blur(4px)'}}>
                        CANLI ÖNİZLEME (BOŞTA)
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{textAlign:'center',padding:30}}>
                    <div style={{fontSize:38,marginBottom:12}}>🖥️</div>
                    <div style={{fontSize:15,fontWeight:600,color:'#ffffff',marginBottom:6}}>Ekran Akışı Bekleniyor...</div>
                    <div style={{fontSize:13,color:'#A1A1AA',maxWidth:380,margin:'0 auto'}}>
                      Görüntü akışı başlatılıyor. Ekranınız canlı olarak burada görüntülenecektir.
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Activity Feed (Right 40%) */}
            <div style={{flex:'2 1 300px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16,display:'flex',flexDirection:'column'}}>
              <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:12}}>
                ANLIK AKTİVİTE AKIŞI
              </div>
              <div style={{flex:1,overflowY:'auto',display:'flex',flexDirection:'column',gap:8,paddingRight:4,maxHeight:450}}>
                {streamActivities.length === 0 ? (
                  <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',padding:'14px 0',textAlign:'center'}}>
                    Henüz aktivite kaydedilmedi.
                  </div>
                ) : (
                  streamActivities.map((act, i) => {
                    const isSuccess = act.level === 'SUCCESS'
                    const isErr = act.level === 'ERROR'
                    const isWarn = act.level === 'WARN'
                    const col = isSuccess ? '#4ade80' : isErr ? '#f87171' : isWarn ? '#fbbf24' : '#60a5fa'
                    return (
                      <div key={i} style={{padding:'8px 12px',background:'rgba(255,255,255,0.04)',borderRadius:6,border:'1px solid rgba(255,255,255,0.08)',fontSize:13,lineHeight:1.4}}>
                        <div style={{display:'flex',justifyContent:'space-between',marginBottom:4}}>
                          <span style={{fontSize:11,color:'#A1A1AA',fontFamily:'monospace'}}>{act.time}</span>
                          <span style={{fontSize:11,fontWeight:700,color:col,fontFamily:'monospace'}}>{act.level}</span>
                        </div>
                        <div style={{color:'#E4E4E7',wordBreak:'break-word'}}>
                          {act.tool && <span style={{fontSize:11,fontWeight:600,background:'rgba(255,255,255,0.1)',padding:'2px 6px',borderRadius:4,marginRight:6,color:'#ffffff',fontFamily:'monospace'}}>{act.tool}</span>}
                          {act.message}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </div>}

        {tab==='memory' && <div style={{height:'100%',overflowY:'auto',padding:'14px 16px'}}>
          <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2,marginBottom:14}}>HAFIZA & PROFİL</div>
          <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {[
              {l:'Profilimi Göster',a:'Profilimi goster'},
              {l:'Öğrendiklerini Listele',a:'Tum ogrendiklerini listele'},
              {l:'Zamanlamaları Göster',a:'Zamanlamalarimi listele'},
              {l:'Bildirimleri Göster',a:'Bildirim kurallarimi listele'},
              {l:'Mevcut Modları Göster',a:'Kullanilabilir modlari listele'},
            ].map(item=>(
              <button key={item.l} style={{padding:'13px 16px',background:'rgba(255,255,255,0.06)',border:'1px solid rgba(255,255,255,0.18)',borderRadius:9,color:'#ffffff',fontSize:13,fontWeight:600,cursor:'pointer',fontFamily:'monospace',textAlign:'left',transition:'all .15s'}} onClick={()=>sendMessage(item.a)}>{item.l}</button>
            ))}
          </div>
        </div>}

        {tab==='stats' && <div style={{height:'100%',overflowY:'auto',padding:'14px 16px'}}>
          <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2,marginBottom:14}}>KULLANIM PANOSU</div>
          {!stats ? (
            <div style={{fontSize:12,color:'#aaaaaa',fontFamily:'monospace'}}>Yükleniyor...</div>
          ) : (
            <div style={{display:'flex',flexDirection:'column',gap:16}}>
              <div style={{display:'flex',gap:8}}>
                {[
                  {l:'Sohbet', v:stats.total_conversations},
                  {l:'Mesaj', v:stats.total_messages},
                  {l:'İşlem', v:stats.total_actions},
                ].map(s=>(
                  <div key={s.l} style={{flex:1,padding:'12px 10px',background:'rgba(255,255,255,0.05)',border:'1px solid rgba(255,255,255,0.14)',borderRadius:9,textAlign:'center'}}>
                    <div style={{fontSize:22,fontFamily:'monospace',color:'#ffffff',fontWeight:700}}>{s.v}</div>
                    <div style={{fontSize:12,color:'#d0d0d0',fontFamily:'monospace',marginTop:4,letterSpacing:1,fontWeight:600}}>{s.l.toUpperCase()}</div>
                  </div>
                ))}
              </div>

              <div>
                <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1.5,marginBottom:10}}>KAZANÇ (Proje & Görevler)</div>
                {(() => {
                  const e = stats.earnings || {total:0,today:0,month:0,currency:'TRY'}
                  const sym = e.currency==='TRY' ? '₺' : (e.currency||'')
                  return (
                    <div style={{display:'flex',gap:8}}>
                      {[
                        {l:'Bugün', v:e.today},
                        {l:'Bu Ay', v:e.month},
                        {l:'Toplam', v:e.total},
                      ].map(s=>(
                        <div key={s.l} style={{flex:1,padding:'12px 10px',background:'rgba(255,255,255,0.05)',border:'1px solid rgba(255,255,255,0.14)',borderRadius:9,textAlign:'center'}}>
                          <div style={{fontSize:20,fontFamily:'monospace',color:'#ffffff',fontWeight:700}}>{sym}{(s.v||0).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
                          <div style={{fontSize:12,color:'#d0d0d0',fontFamily:'monospace',marginTop:4,letterSpacing:1,fontWeight:600}}>{s.l.toUpperCase()}</div>
                        </div>
                      ))}
                    </div>
                  )
                })()}
                <div style={{display:'flex',gap:8,marginTop:10}}>
                  <input value={earnAmount} onChange={e=>setEarnAmount(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')addEarning()}} inputMode="decimal" placeholder="Tutar" style={{width:100,padding:'9px 12px',background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:7,color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none'}} />
                  <input value={earnNote} onChange={e=>setEarnNote(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')addEarning()}} placeholder="Not (ör. logo tasarımı)" style={{flex:1,padding:'9px 12px',background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:7,color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none'}} />
                  <button onClick={addEarning} style={{padding:'9px 16px',border:'1px solid rgba(255,255,255,0.3)',background:'rgba(255,255,255,0.12)',color:'#ffffff',borderRadius:7,cursor:'pointer',fontSize:13,fontWeight:600,fontFamily:'monospace'}}>EKLE</button>
                </div>

                {/* 30 gunluk trend cizgisi — saf SVG, ek kutuphane yok */}
                {(() => {
                  const daily = stats.earnings?.daily || []
                  if (!daily.length) return null
                  const max = Math.max(1, ...daily.map(d=>d.amount))
                  const W = 300, H = 46
                  const pts = daily.map((d,i)=>{
                    const x = (i/(daily.length-1||1))*W
                    const y = H - (d.amount/max)*(H-4) - 2
                    return `${x.toFixed(1)},${y.toFixed(1)}`
                  }).join(' ')
                  const e = stats.earnings || {}
                  return (
                    <div style={{marginTop:10}}>
                      <div style={{display:'flex',justifyContent:'space-between',marginBottom:5}}>
                        <span style={{fontSize:9,color:'#888',fontFamily:'monospace',letterSpacing:1}}>SON 30 GÜN TRENDİ</span>
                        <span style={{fontSize:9,color:'#777',fontFamily:'monospace'}}>ort/gün {e.avg_per_day_30??0}</span>
                      </div>
                      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{width:'100%',height:46,display:'block'}}>
                        <polyline points={pts} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
                      </svg>
                    </div>
                  )
                })()}

                {/* Kaynak kirilimi */}
                {(stats.earnings?.by_source||[]).length>0 && (
                  <div style={{marginTop:12}}>
                    <div style={{fontSize:12,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:8}}>KAYNAĞA GÖRE</div>
                    <div style={{display:'flex',flexDirection:'column',gap:8}}>
                      {stats.earnings.by_source.slice(0,6).map(s=>{
                        const max = Math.max(1, ...stats.earnings.by_source.map(x=>x.amount))
                        return (
                          <div key={s.source} style={{display:'flex',alignItems:'center',gap:10}}>
                            <div style={{width:130,fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace',flexShrink:0,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{s.source}</div>
                            <div style={{flex:1,height:8,background:'rgba(255,255,255,0.08)',borderRadius:4,overflow:'hidden'}}>
                              <div style={{width:`${(s.amount/max)*100}%`,height:'100%',background:'rgba(255,255,255,0.45)'}} />
                            </div>
                            <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',width:60,textAlign:'right'}}>{s.amount}</div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>

              <div>
                <div style={{fontSize:12,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:8}}>SON 14 GÜN AKTİVİTE</div>
                <div style={{display:'flex',alignItems:'flex-end',gap:3,height:60,padding:'0 2px'}}>
                  {(stats.activity_by_day||[]).map(d=>{
                    const max = Math.max(1, ...stats.activity_by_day.map(x=>x.count))
                    const h = Math.max(2, Math.round((d.count/max)*54))
                    return (
                      <div key={d.date} title={`${d.date}: ${d.count}`} style={{flex:1,height:h,background:d.count>0?'rgba(255,255,255,0.45)':'rgba(255,255,255,0.08)',borderRadius:2}} />
                    )
                  })}
                </div>
              </div>

              <div>
                <div style={{fontSize:12,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:8}}>SON 60 DAKİKA (İŞLEM / DK)</div>
                <div style={{display:'flex',alignItems:'flex-end',gap:1,height:44,padding:'0 2px'}}>
                  {(stats.activity_by_minute||[]).map(d=>{
                    const max = Math.max(1, ...stats.activity_by_minute.map(x=>x.count))
                    const h = Math.max(1, Math.round((d.count/max)*40))
                    return (
                      <div key={d.minute} title={`${d.minute}: ${d.count}`} style={{flex:1,height:h,background:d.count>0?'rgba(255,255,255,0.4)':'rgba(255,255,255,0.06)',borderRadius:1}} />
                    )
                  })}
                </div>
              </div>

              <div>
                <div style={{fontSize:12,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:8}}>EN ÇOK KULLANILAN ARAÇLAR</div>
                <div style={{display:'flex',flexDirection:'column',gap:8}}>
                  {(stats.top_tools||[]).length===0 && <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace'}}>Henüz veri yok.</div>}
                  {(stats.top_tools||[]).map(t=>{
                    const max = Math.max(1, ...stats.top_tools.map(x=>x.count))
                    return (
                      <div key={t.label} style={{display:'flex',alignItems:'center',gap:10}}>
                        <div style={{width:140,fontSize:13,fontWeight:600,color:'#E4E4E7',fontFamily:'monospace',flexShrink:0,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{t.label}</div>
                        <div style={{flex:1,height:8,background:'rgba(255,255,255,0.08)',borderRadius:4,overflow:'hidden'}}>
                          <div style={{width:`${(t.count/max)*100}%`,height:'100%',background:'rgba(255,255,255,0.45)'}} />
                        </div>
                        <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',width:30,textAlign:'right'}}>{t.count}</div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
        </div>}

        {tab==='status' && <StatusPanel />}
        {tab==='metrics' && <MetricsPanel />}
        {tab==='settings' && (
          <div style={{height:'100%',overflowY:'auto',padding:'16px 20px',background:'#121212',color:'#E4E4E7'}}>
            <SettingsPanel isTab={true} onClose={()=>setTab('chat')} pendingSkills={skillProposals} onSkillsChange={setSkillProposals} autoSpeak={autoSpeak} onAutoSpeakChange={setAutoSpeak} />
          </div>
        )}
        {tab==='advanced' && (
          <div style={{height:'100%',overflowY:'auto',padding:'12px 14px'}}>
            <AdvancedPanel defaultOpen={true} />
          </div>
        )}
      </main>

      {/* INPUT */}
      <footer className="chat-footer" style={{padding:'10px 14px 12px',borderTop:'1px solid rgba(255,255,255,0.12)',background:'#121212',flexShrink:0}}>
        {/* SES VE KAYIT BİLGİLENDİRME BANTLARI */}
        {listening && (
          <div style={{
            display:'flex',
            alignItems:'center',
            justifyContent:'space-between',
            gap:8,
            padding:'8px 12px',
            background:'rgba(239, 68, 68, 0.16)',
            border:'1px solid rgba(239, 68, 68, 0.45)',
            borderRadius:7,
            marginBottom:8,
            color:'#f87171',
            fontSize:12,
            fontFamily:'monospace'
          }}>
            <div style={{display:'flex',alignItems:'center',gap:8}}>
              <span style={{width:9,height:9,borderRadius:'50%',background:'#ef4444',boxShadow:'0 0 10px #ef4444',display:'inline-block',animation:'pulse 1s infinite'}}></span>
              <span style={{fontWeight:700}}>🔴 Kaydediliyor... Mikrofon dinliyor (Konuşun)</span>
            </div>
            <button
              onClick={stopListening}
              style={{
                background:'#ef4444',
                color:'#ffffff',
                border:'none',
                borderRadius:5,
                padding:'4px 10px',
                fontSize:11,
                fontWeight:700,
                cursor:'pointer',
                fontFamily:'monospace'
              }}
            >
              BİTİR & GÖNDER
            </button>
          </div>
        )}

        {transcribing && (
          <div style={{
            display:'flex',
            alignItems:'center',
            gap:8,
            padding:'8px 12px',
            background:'rgba(59, 130, 246, 0.16)',
            border:'1px solid rgba(59, 130, 246, 0.45)',
            borderRadius:7,
            marginBottom:8,
            color:'#60a5fa',
            fontSize:12,
            fontFamily:'monospace'
          }}>
            <span style={{animation:'spin 1s linear infinite',display:'inline-block'}}>◌</span>
            <span>⏳ Ses yazıya çevriliyor (Whisper API)...</span>
          </div>
        )}

        {audioBlocked && autoSpeak && (
          <div style={{
            display:'flex',
            alignItems:'center',
            justifyContent:'space-between',
            gap:8,
            padding:'8px 12px',
            background:'rgba(234, 179, 8, 0.16)',
            border:'1px solid rgba(234, 179, 8, 0.45)',
            borderRadius:7,
            marginBottom:8,
            color:'#facc15',
            fontSize:12,
            fontFamily:'monospace'
          }}>
            <span>🔇 Tarayıcı otomatik ses çalmayı duraklattı</span>
            <button
              onClick={()=>{
                unlockAudio();
                setAudioBlocked(false);
                if (lastAssistantMsgRef.current) {
                  playTTS(lastAssistantMsgRef.current);
                }
              }}
              style={{
                background:'#facc15',
                color:'#000000',
                border:'none',
                borderRadius:5,
                padding:'4px 10px',
                fontSize:11,
                fontWeight:700,
                cursor:'pointer',
                fontFamily:'monospace'
              }}
            >
              🔊 Sesi Başlat
            </button>
          </div>
        )}

        <div style={{display:'flex',gap:8,alignItems:'flex-end'}}>
          <button
            style={{
              width:40,
              height:40,
              flexShrink:0,
              border:'1px solid ' + (listening ? '#ef4444' : 'rgba(255,255,255,0.2)'),
              borderRadius:8,
              fontSize:16,
              cursor:'pointer',
              display:'flex',
              alignItems:'center',
              justifyContent:'center',
              background:listening ? 'rgba(239,68,68,0.25)' : '#1E1E24',
              boxShadow:listening ? '0 0 12px rgba(239,68,68,0.5)' : 'none',
              transition:'all .2s'
            }}
            title={transcribing ? "Ses işleniyor (Whisper)..." : (listening ? "Dinlemeyi Durdur" : "Sesle Yaz (Mikrofon)")}
            onClick={listening ? stopListening : startListening}
          >
            {transcribing ? '⏳' : '🎤'}
          </button>
          <textarea ref={inputRef} className="chat-input" style={{flex:1,background:'#1E1E24',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8,padding:'10px 12px',color:'#E4E4E7',fontSize:14,fontFamily:"'Inter',sans-serif",resize:'none',lineHeight:1.5,userSelect:'text',transition:'border-color .2s'}} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}} placeholder={showOnboarding ? 'Lütfen önce API anahtarınızı kaydedin...' : (connected?(transcribing?'Ses yazıya çevriliyor...':(listening?'Dinleniyor...':"ALES'e yaz...")):'Backend baslatiliyor...')} disabled={!connected||thinking||showOnboarding} rows={1} />
          <button style={{width:40,height:40,flexShrink:0,background:'#ffffff',border:'none',borderRadius:8,color:'#000000',fontSize:15,fontWeight:700,cursor:'pointer',boxShadow:'0 0 12px rgba(255,255,255,0.25)',opacity:(!connected||thinking||!input.trim()||showOnboarding)?0.25:1,transition:'opacity .2s'}} onClick={send} disabled={!connected||thinking||!input.trim()||showOnboarding}>▶</button>
        </div>
      </footer>

      <style>{`
        @keyframes spin{to{transform:rotate(360deg)}}
        @keyframes d1{0%,100%{opacity:.1}25%{opacity:1}}
        @keyframes d2{0%,100%{opacity:.1}50%{opacity:1}}
        @keyframes d3{0%,100%{opacity:.1}75%{opacity:1}}
        @keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
        @keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
        textarea:focus{outline:none;border-color:rgba(255,255,255,0.5)!important}
        button:active{opacity:.7}
        ::-webkit-scrollbar{width:2px}
        ::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.3);border-radius:2px}
        @keyframes scanLine{0%{top:-4px;opacity:0}10%{opacity:1}90%{opacity:1}100%{top:100%;opacity:0}}
        @keyframes waveRipple{0%{transform:scale(0.8);opacity:0.8}100%{transform:scale(2.8);opacity:0}}
        @keyframes scanPulse{0%,100%{opacity:0.6}50%{opacity:1}}
        /* Yerel HUD (TalkingDot): konusan noktanin nefes alisi. waveRipple
           halkalari zaten yukarida tanimli, yeniden yazmiyoruz. */
        @keyframes hudBreathe{0%,100%{transform:scale(1);opacity:.85}50%{transform:scale(1.22);opacity:1}}
        /* HAREKET AZALTMA: sistem ayari "reduce" ise sureklilik arz eden
           animasyonlari CSS tarafinda da kesiyoruz. Bilesenler bunu JS ile
           de yapiyor; bu ikinci kemer, kacan bir yer kalmasin diye. */
        @media (prefers-reduced-motion: reduce){
          *{animation-duration:.001ms!important;animation-iteration-count:1!important}
        }
      `}</style>
      {/* TARAMA ANİMASYONU */}
      {scanning && (
        <div style={{position:'fixed',inset:0,pointerEvents:'none',zIndex:999,overflow:'hidden'}}>
          <div style={{position:'absolute',left:0,right:0,height:2,background:'linear-gradient(90deg,transparent,#ffffff,#eeeeee,#ffffff,transparent)',boxShadow:'0 0 20px #ffffff,0 0 40px #ffffff44',animation:'scanLine 1.8s ease-in-out infinite'}} />
          {['tl','tr','bl','br'].map(p=>(
            <div key={p} style={{position:'absolute',width:20,height:20,animation:'scanPulse 1.5s infinite',...(p==='tl'?{top:6,left:6,borderTop:'2px solid #ffffff',borderLeft:'2px solid #ffffff'}:p==='tr'?{top:6,right:6,borderTop:'2px solid #ffffff',borderRight:'2px solid #ffffff'}:p==='bl'?{bottom:6,left:6,borderBottom:'2px solid #ffffff',borderLeft:'2px solid #ffffff'}:{bottom:6,right:6,borderBottom:'2px solid #ffffff',borderRight:'2px solid #ffffff'})}} />
          ))}
          {[0,1,2].map(i=>(
            <div key={i} style={{position:'absolute',top:'50%',left:'50%',width:50,height:50,marginTop:-25,marginLeft:-25,borderRadius:'50%',border:'1px solid #ffffff44',animation:`waveRipple 1.8s ease-out ${i*0.6}s infinite`}} />
          ))}
          <div style={{position:'absolute',top:14,left:'50%',transform:'translateX(-50%)',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.35)',borderRadius:6,padding:'3px 12px',fontSize:9,color:'#dddddd',fontFamily:'monospace',letterSpacing:2}}>
            EKRAN TARANIYOR...
          </div>
        </div>
      )}
    </div>
  )
}

// ─── MOD SECICI ──────────────────────────────────────────────────
// 7 mod: Task/Cheat/Auto/Multi/Performance/Heavy/Council. Liste SABIT DEGIL —
// backend /modes'tan gelir (config_manager.DEFAULT_MODES tek kaynak), bu yuzden
// yeni bir mod eklemek icin burada kod degismez; sadece EMOJI haritasina bir
// satir eklenir (yoksa '•' kullanilir). Aktif modu + cozumlenmis zinciri
// (hangi saglayici/model) de ayni cagri dondurur; secim /mode POST ile aninda
// uygulanir. Zaman asimlari (katman bazli, sn) katlanabilir bolumde /config'e
// kaydedilir.
function ModeSelector() {
  const [data, setData] = useState(null)   // {modes, active, active_chain, providers, timeouts}
  const [busy, setBusy] = useState(false)
  const [tdraft, setTdraft] = useState(null)
  const [tsaved, setTsaved] = useState(false)
  const [showT, setShowT] = useState(false)
  // LLM MECLISI: birden fazla modeli ayni soruya paralel kosup hakem
  // modelle en iyisini sectiren/harmanlayan katman. Heavy modda config'ten
  // bagimsiz olarak zaten acik (mode override), bu anahtar diger modlar icin.
  const [council, setCouncil] = useState(null)
  const [showC, setShowC] = useState(false)
  // BIG ALES: Puter uzerinden calisan orkestrator. API ANAHTARI YOK —
  // odemeyi kullanicinin kendi Puter hesabi karsilar, giris bir kez yapilir.
  const [bigAles, setBigAles] = useState(null)
  const [showB, setShowB] = useState(false)

  useEffect(() => {
    authFetch(API_URL+'/modes').then(r=>r.json())
      .then(d=>{ setData(d); setTdraft(d?.timeouts||null) }).catch(()=>{})
    authFetch(API_URL+'/council').then(r=>r.json()).then(setCouncil).catch(()=>{})
    authFetch(API_URL+'/big-ales').then(r=>r.json()).then(setBigAles).catch(()=>{})
  }, [])

  const saveBigAles = async (patch) => {
    setBigAles(p=>({...p, config:{...p.config, ...patch}}))
    try {
      const r = await authFetch(API_URL+'/big-ales',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)})
      const d = await r.json()
      if (d.ok) setBigAles(p=>({...p, config:d.config}))
      else if (d.error) setBigAles(p=>({...p, lastError:d.error}))
    } catch(e) {}
  }

  const puterLogout = async () => {
    try {
      const r = await authFetch(API_URL+'/big-ales/logout',{method:'POST'})
      const d = await r.json()
      if (d.session) setBigAles(p=>({...p, session:d.session}))
    } catch(e) {}
  }

  const saveCouncil = async (patch) => {
    setCouncil(p=>({...p, config:{...p.config, ...patch}}))
    try {
      const r = await authFetch(API_URL+'/council',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)})
      const d = await r.json()
      if (d.ok) setCouncil(p=>({...p, config:d.config}))
    } catch(e) {}
  }

  const pick = async (id) => {
    if (busy || !data || id === data.active) return
    setBusy(true)
    try {
      try { localStorage.setItem('ales_selected_mode', id) } catch (e) {}
      const r = await authFetch(API_URL+'/mode', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:id})})
      const d = await r.json()
      if (d.ok) setData(p=>({...p, active:d.mode, active_chain:d.active_chain||p.active_chain,
                             modes:(p.modes||[]).map(m=>({...m, active:m.id===d.mode}))}))
    } catch(e) {}
    setBusy(false)
  }

  const saveTimeouts = async () => {
    try { await authFetch(API_URL+'/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({timeouts:tdraft})}) } catch(e){}
    setTsaved(true); setTimeout(()=>setTsaved(false),1200)
  }

  if (!data) return null
  const EMOJI = {task:'⚡',cheat:'🔓',auto:'🧭',multi:'🎭',performance:'🚀',heavy:'🧠',council:'🏛️',big_ales:'🐘'}
  const TKEYS = [['fast_s','Fast'],['fallback_s','Fallback'],['vision_s','Vision'],['code_s','Code'],['unrestricted_s','Cheat'],['heavy_s','Heavy']]
  const nStyle = {background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:6,padding:'8px 10px',color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none',width:'100%',marginTop:4,boxSizing:'border-box'}
  const active = (data.modes||[]).find(m=>m.active)

  return (
    <div style={{marginBottom:14,paddingBottom:12,borderBottom:'1px solid rgba(255,255,255,0.12)'}}>
      <div style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2,marginBottom:10}}>MOD SEÇİMİ</div>
      <div className="responsive-grid-3" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(110px, 1fr))',gap:8,marginBottom:10}}>
        {(data.modes||[]).map(m=>(
          <button key={m.id} title={m.description} onClick={()=>pick(m.id)} disabled={busy}
            style={{padding:'10px 8px',borderRadius:7,cursor:busy?'default':'pointer',fontFamily:'monospace',fontSize:13,fontWeight:m.active?700:500,
                    border:'1px solid '+(m.active?'#ffffff':'rgba(255,255,255,0.2)'),
                    background:m.active?'rgba(255,255,255,0.22)':'rgba(255,255,255,0.06)',
                    color:m.active?'#ffffff':'#E4E4E7',opacity:busy&&!m.active?0.5:1}}>
            {EMOJI[m.id]||'•'} {m.label}
          </button>
        ))}
      </div>
      {active?.description && (
        <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',marginBottom:8,lineHeight:1.5}}>{active.description}</div>
      )}
      <div style={{fontSize:13,color:'#E4E4E7',fontFamily:'monospace',marginBottom:10,lineHeight:1.5}}>
        Zincir: {(data.active_chain||[]).map(l=>`${l.provider}/${(l.model||'').split('/').pop()}`).join(' → ') || '—'}
      </div>
      <button onClick={()=>setShowT(s=>!s)} style={{background:'none',border:'none',color:'#ffffff',fontSize:13,fontWeight:600,fontFamily:'monospace',cursor:'pointer',padding:'4px 0'}}>
        {showT?'▾':'▸'} ZAMAN AŞIMI (sn)
      </button>
      {showT && tdraft && (
        <div style={{marginTop:6}}>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(95px, 1fr))',gap:8,margin:'8px 0'}}>
            {TKEYS.map(([k,lbl])=>(
              <label key={k} style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace'}}>{lbl}
                <input type="number" step="0.5" min="0" value={tdraft[k]??''} onChange={e=>setTdraft(p=>({...p,[k]:e.target.value}))} style={nStyle} />
              </label>
            ))}
          </div>
          <button onClick={saveTimeouts} style={{width:'100%',padding:'8px',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.3)',borderRadius:7,color:'#ffffff',fontSize:12,fontWeight:600,cursor:'pointer',fontFamily:'monospace'}}>{tsaved?'✓ KAYDEDİLDİ':'ZAMAN AŞIMINI KAYDET'}</button>
        </div>
      )}

      {/* ── LLM MECLISI ── */}
      {council && (
        <div style={{marginTop:10,paddingTop:10,borderTop:'1px solid rgba(255,255,255,0.1)'}}>
          <button onClick={()=>setShowC(s=>!s)} style={{background:'none',border:'none',color:'#ffffff',fontSize:12,fontWeight:600,fontFamily:'monospace',cursor:'pointer',padding:'4px 0'}}>
            {showC?'▾':'▸'} LLM MECLİSİ {council.config?.enabled?'· AÇIK':'· KAPALI'}
          </button>
          {showC && (
            <div style={{marginTop:10}}>
              <label style={{display:'flex',alignItems:'center',gap:8,cursor:'pointer',marginBottom:10}}>
                <input type="checkbox" checked={!!council.config?.enabled}
                  onChange={e=>saveCouncil({enabled:e.target.checked})}
                  style={{accentColor:'#fff',cursor:'pointer',width:16,height:16}} />
                <span style={{fontSize:13,color:'#ffffff',fontFamily:'monospace',fontWeight:600}}>Meclis modunu etkinleştir</span>
              </label>
              <div style={{fontSize:12,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.5,marginBottom:10}}>
                Aynı soru {council.available_providers?.length||0} modele paralel gider, yanıtlar
                anonimleştirilip karıştırılır, hakem model en iyisini seçer/harmanlar.
                Yavaş ve çok token harcar — kısa/günlük sorularda otomatik atlanır.
                {(council.heavy_modes||[]).length>0 && ` ${council.heavy_modes.join(', ')} modunda bu anahtardan bağımsız olarak zaten açık.`}
              </div>
              <label style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace',display:'block',marginBottom:10}}>STRATEJİ
                <select value={council.config?.strategy||'synthesized'} onChange={e=>saveCouncil({strategy:e.target.value})} style={{...nStyle,cursor:'pointer'}}>
                  {(council.strategies||[]).map(s=>(<option key={s} value={s} style={{background:'#1a1a1a',color:'#ffffff'}}>{s}</option>))}
                </select>
              </label>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:8}}>
                <label style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace'}}>MODEL BAŞI ZAMAN AŞIMI (sn)
                  <input type="number" step="0.5" min="1" value={council.config?.timeout_s??5}
                    onChange={e=>setCouncil(p=>({...p,config:{...p.config,timeout_s:e.target.value}}))}
                    onBlur={e=>saveCouncil({timeout_s:parseFloat(e.target.value)||5})} style={nStyle} />
                </label>
                <label style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace'}}>HAKEM ZAMAN AŞIMI (sn)
                  <input type="number" step="1" min="1" value={council.config?.judge_timeout_s??20}
                    onChange={e=>setCouncil(p=>({...p,config:{...p.config,judge_timeout_s:e.target.value}}))}
                    onBlur={e=>saveCouncil({judge_timeout_s:parseFloat(e.target.value)||20})} style={nStyle} />
                </label>
              </div>
              <label style={{display:'flex',alignItems:'center',gap:8,cursor:'pointer',marginTop:10}}>
                <input type="checkbox" checked={council.config?.cache!==false}
                  onChange={e=>saveCouncil({cache:e.target.checked})}
                  style={{accentColor:'#fff',cursor:'pointer',width:16,height:16}} />
                <span style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace'}}>Sonuçları önbelleğe al (aynı soru tekrar gelirse meclis çalışmaz)</span>
              </label>
              <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace',marginTop:10,lineHeight:1.5}}>
                Üye modeller: {(council.available_providers||[]).join(', ')||'anahtar yok'}
                {(council.missing_providers||[]).length>0 && ` · anahtarı eksik: ${council.missing_providers.join(', ')}`}
                <br/>Gereken en az üye: {council.min_members??2} · şu an hazır: {council.member_count??0}
                {council.available===false && ' · MECLİS ŞU AN ÇALIŞMAZ'}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── BIG ALES (PUTER) ── */}
      {bigAles && (
        <div style={{marginTop:10,paddingTop:10,borderTop:'1px solid rgba(255,255,255,0.1)'}}>
          <button onClick={()=>setShowB(s=>!s)} style={{background:'none',border:'none',color:'#ffffff',fontSize:12,fontWeight:600,fontFamily:'monospace',cursor:'pointer',padding:'4px 0'}}>
            {showB?'▾':'▸'} BIG ALES (Puter – Giriş Gerekli) {(bigAles.config?.enabled||bigAles.mode_active)?'· AÇIK':'· KAPALI'}
          </button>
          {showB && (
            <div style={{marginTop:10}}>
              <label style={{display:'flex',alignItems:'center',gap:8,cursor:'pointer',marginBottom:10}}>
                <input type="checkbox" checked={!!bigAles.config?.enabled}
                  onChange={e=>saveBigAles({enabled:e.target.checked})}
                  style={{accentColor:'#fff',cursor:'pointer',width:16,height:16}} />
                <span style={{fontSize:13,color:'#ffffff',fontFamily:'monospace',fontWeight:600}}>Big ALES (Puter – Giriş Gerekli)</span>
              </label>
              <div style={{fontSize:12,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.5,marginBottom:10}}>
                İstek önce büyük modele (Hermes) gönderilip net ve yasal biçimde
                YENİDEN YAZILIR, sonra normal ALES zincirinden geçer. Orkestratör
                yürütmez, yalnızca isteği netleştirir.
                <br/><b style={{color:'#a3e635'}}>API ANAHTARI GEREKMEZ</b> — ücreti kendi Puter
                hesabınız karşılar; giriş ilk istekte bir kez yapılır.
                <br/>Mod çubuğundan 🐘 Big ALES seçerek de açabilirsiniz (bu anahtardan bağımsız).
              </div>
              <label style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace',display:'block',marginBottom:10}}>ORKESTRATÖR MODELİ
                <select value={bigAles.config?.model||''} onChange={e=>saveBigAles({model:e.target.value})} style={{...nStyle,cursor:'pointer'}}>
                  {(bigAles.models||[]).map(m=>(<option key={m} value={m} style={{background:'#1a1a1a',color:'#ffffff'}}>{m}</option>))}
                </select>
              </label>
              <label style={{fontSize:12,color:'#e0e0e0',fontFamily:'monospace',display:'block',marginBottom:10}}>ZAMAN AŞIMI (sn)
                <input type="number" step="5" min="5" value={bigAles.config?.timeout_s??60}
                  onChange={e=>setBigAles(p=>({...p,config:{...p.config,timeout_s:e.target.value}}))}
                  onBlur={e=>saveBigAles({timeout_s:parseFloat(e.target.value)||60})} style={nStyle} />
              </label>
              <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace',marginTop:10,lineHeight:1.5}}>
                Puter oturumu: {bigAles.session?.signed_in
                  ? `AÇIK${bigAles.session?.username?' ('+bigAles.session.username+')':''}`
                  : 'YOK — ilk istekte giriş penceresi açılır'}
                <br/>Jeton şifreleme: {bigAles.session?.encryption==='dpapi'
                  ? 'Windows DPAPI (kullanıcı hesabına bağlı)'
                  : 'YOK — yalnızca dosya izinleri'}
                {typeof location!=='undefined' && location.protocol==='file:' && (
                  <><br/>Giriş, ilk istekte küçük bir <b>Puter penceresinde</b> açılır
                  (127.0.0.1:8000/puter-bridge) — kapatmayın, giriş bitince kendisi kapanır.</>
                )}
                {bigAles.available===false && <><br/><b style={{color:'#fca5a5'}}>puter_connector yüklenemedi — Big ALES şu an çalışmaz</b></>}
                {bigAles.breaker?.open && <><br/><b style={{color:'#fca5a5'}}>Devre kesici AÇIK ({bigAles.breaker.fail_streak} ardışık hata) — istekler beklemeden normal zincire gidiyor. Giriş yapınca kendiliğinden açılır.</b></>}
                {bigAles.lastError && <><br/><b style={{color:'#fca5a5'}}>{bigAles.lastError}</b></>}
              </div>
              {bigAles.session?.stored && (
                <button onClick={puterLogout} style={{marginTop:10,padding:'7px 12px',borderRadius:6,cursor:'pointer',fontFamily:'monospace',fontSize:12,fontWeight:600,border:'1px solid rgba(255,255,255,0.25)',background:'rgba(255,255,255,0.1)',color:'#ffffff'}}>
                  Puter oturumunu sil
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StatusPanel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const loadStatus = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await authFetch(API_URL + '/api/system/status')
      const json = await res.json()
      if (json.ok && json.capabilities) {
        setData(json.capabilities)
      } else {
        setErr(json.error || 'Durum bilgisi okunamadı')
      }
    } catch (e) {
      setErr('Backend sunucusuna ulaşılamadı')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadStatus() }, [loadStatus])

  const badgeStyle = (st) => {
    switch (st) {
      case 'working': return { bg: 'rgba(34, 197, 94, 0.15)', border: '#22c55e', text: '#4ade80', label: 'ÇALIŞIYOR' }
      case 'beta': return { bg: 'rgba(234, 179, 8, 0.15)', border: '#eab308', text: '#fde047', label: 'BETA' }
      case 'experimental': return { bg: 'rgba(168, 85, 247, 0.15)', border: '#a855f7', text: '#c084fc', label: 'DENEYSEL' }
      default: return { bg: 'rgba(239, 68, 68, 0.15)', border: '#ef4444', text: '#f87171', label: 'KAPALI / YOK' }
    }
  }

  return (
    <div style={{height:'100%',overflowY:'auto',padding:'16px 20px',background:'#121212',color:'#E4E4E7',fontFamily:'monospace'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16,flexWrap:'wrap',gap:10}}>
        <div>
          <div style={{fontSize:15,color:'#ffffff',letterSpacing:2,fontWeight:700}}>ALES GERÇEK SİSTEM VE MODÜL DURUMU</div>
          <div style={{fontSize:13,color:'#A1A1AA',marginTop:4}}>Tüm bileşenler, API anahtarları ve masaüstü motoru anlık olarak test edilir.</div>
        </div>
        <button onClick={loadStatus} disabled={loading} style={{padding:'8px 16px',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.3)',borderRadius:6,color:'#ffffff',cursor:loading?'not-allowed':'pointer',fontSize:13,fontWeight:600}}>
          {loading ? 'TARANIYOR...' : '↻ YENİLE'}
        </button>
      </div>

      {loading && !data && (
        <div style={{textAlign:'center',padding:40,color:'#A1A1AA',fontSize:14}}>
          Sistem bileşenleri canlı olarak denetleniyor...
        </div>
      )}

      {err && (
        <div style={{padding:'12px 16px',background:'rgba(239,68,68,0.15)',border:'1px solid rgba(239,68,68,0.35)',borderRadius:8,color:'#f87171',fontSize:13,marginBottom:16}}>
          {err}
        </div>
      )}

      {data && (
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill, minmax(320px, 1fr))',gap:12}}>
          {Object.entries(data).map(([key, item]) => {
            const b = badgeStyle(item.status)
            return (
              <div key={key} style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.14)',borderRadius:8,padding:16,display:'flex',flexDirection:'column',justifyContent:'space-between',gap:12}}>
                <div>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:8}}>
                    <div style={{fontSize:14,color:'#ffffff',fontWeight:700}}>{item.label}</div>
                    <span style={{fontSize:11,padding:'4px 8px',borderRadius:4,background:b.bg,border:`1px solid ${b.border}`,color:b.text,fontWeight:700,letterSpacing:0.5}}>{b.label}</span>
                  </div>
                  <div style={{fontSize:13,color:'#E4E4E7',lineHeight:1.5}}>{item.details}</div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function MetricsPanel() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [resetting, setResetting] = useState(false)

  const loadMetrics = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await authFetch(API_URL + '/api/telemetry')
      const json = await res.json()
      if (json.ok && json.data) {
        setMetrics(json.data)
      } else {
        setErr(json.error || 'Metrik bilgisi okunamadı')
      }
    } catch (e) {
      setErr('Backend sunucusuna ulaşılamadı')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMetrics()
    const timer = setInterval(loadMetrics, 5000)
    return () => clearInterval(timer)
  }, [loadMetrics])

  const handleReset = async () => {
    if (!confirm('Tüm telemetri sayaçlarını sıfırlamak istediğinize emin misiniz?')) return
    setResetting(true)
    try {
      await authFetch(API_URL + '/api/telemetry/reset', { method: 'POST' })
      await loadMetrics()
    } catch (e) {
      alert('Sıfırlama hatası')
    } finally {
      setResetting(false)
    }
  }

  const summary = metrics?.summary || {}
  const apiProviders = metrics?.api || {}
  const cache = metrics?.cache || {}
  const gui = metrics?.gui || {}
  const tasks = metrics?.tasks || {}

  return (
    <div style={{height:'100%',overflowY:'auto',padding:'16px 20px',background:'#121212',color:'#E4E4E7',lineHeight:1.5}}>
      {/* Header */}
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:10,marginBottom:20}}>
        <div>
          <div style={{fontSize:16,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2}}>
            SİSTEM PERFORMANS VE BAŞARI METRİKLERİ
          </div>
          <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:4}}>
            Model çağrıları, önbellek etkinliği, GUI etkileşimleri ve görev başarı oranları
          </div>
        </div>
        <div style={{display:'flex',gap:10}}>
          <button
            onClick={loadMetrics}
            disabled={loading}
            style={{padding:'6px 14px',background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.2)',color:'#ffffff',borderRadius:6,fontFamily:'monospace',fontSize:12,cursor:'pointer'}}
          >
            {loading ? 'YENİLENİYOR...' : '↻ YENİLE'}
          </button>
          <button
            onClick={handleReset}
            disabled={resetting}
            style={{padding:'6px 14px',background:'rgba(239,68,68,0.15)',border:'1px solid rgba(239,68,68,0.3)',color:'#f87171',borderRadius:6,fontFamily:'monospace',fontSize:12,cursor:'pointer'}}
          >
            {resetting ? 'SIFIRLANIYOR...' : 'SAYAÇLARI SIFIRLA'}
          </button>
        </div>
      </div>

      {err && (
        <div style={{background:'rgba(239,68,68,0.15)',border:'1px solid rgba(239,68,68,0.3)',color:'#f87171',padding:'12px 16px',borderRadius:8,marginBottom:16,fontFamily:'monospace',fontSize:13}}>
          ⚠️ {err}
        </div>
      )}

      {/* KPI Cards */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(210px, 1fr))',gap:14,marginBottom:24}}>
        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontFamily:'monospace',color:'#A1A1AA'}}>GENEL API BAŞARISI</div>
          <div style={{fontSize:28,fontWeight:700,fontFamily:'monospace',color:summary.overall_api_rate_pct >= 90 ? '#4ade80' : '#f59e0b',marginTop:6}}>
            %{summary.overall_api_rate_pct ?? 100}
          </div>
          <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:4}}>
            Toplam: {summary.total_api_calls ?? 0} çağrı
          </div>
        </div>

        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontFamily:'monospace',color:'#A1A1AA'}}>ÖNBELLEK İSABET ORANI</div>
          <div style={{fontSize:28,fontWeight:700,fontFamily:'monospace',color:'#60a5fa',marginTop:6}}>
            %{cache.hit_rate_pct ?? 0}
          </div>
          <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:4}}>
            {cache.hits ?? 0} isabet / {cache.misses ?? 0} ıskalama
          </div>
        </div>

        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontFamily:'monospace',color:'#A1A1AA'}}>AKSİYON KORUMASI (BAYPAS)</div>
          <div style={{fontSize:28,fontWeight:700,fontFamily:'monospace',color:'#f59e0b',marginTop:6}}>
            {cache.bypasses ?? 0}
          </div>
          <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:4}}>
            Kritik komutlar önbellekten korundu
          </div>
        </div>

        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:16}}>
          <div style={{fontSize:12,fontFamily:'monospace',color:'#A1A1AA'}}>MASAÜSTÜ / GUI BAŞARISI</div>
          <div style={{fontSize:28,fontWeight:700,fontFamily:'monospace',color:gui.rate_pct >= 90 ? '#4ade80' : '#f87171',marginTop:6}}>
            %{gui.rate_pct ?? 100}
          </div>
          <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:4}}>
            {gui.success ?? 0} başarılı / {gui.fail ?? 0} hata
          </div>
        </div>
      </div>

      {/* Grid: Providers & Details */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(360px, 1fr))',gap:16}}>
        {/* Model Providers */}
        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:18}}>
          <div style={{fontSize:14,fontWeight:700,fontFamily:'monospace',color:'#ffffff',marginBottom:14}}>
            MODEL SAĞLAYICILARI PERFORMANSI
          </div>
          {Object.keys(apiProviders).length === 0 ? (
            <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',padding:'16px 0'}}>
              Henüz API çağrısı kaydedilmedi.
            </div>
          ) : (
            <div style={{display:'flex',flexDirection:'column',gap:10}}>
              {Object.entries(apiProviders).map(([prov, p]) => (
                <div key={prov} style={{background:'#121212',border:'1px solid rgba(255,255,255,0.08)',borderRadius:8,padding:'10px 14px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                  <div>
                    <div style={{fontWeight:600,color:'#ffffff',fontSize:13}}>{prov}</div>
                    <div style={{fontSize:11,color:'#A1A1AA',fontFamily:'monospace',marginTop:2}}>
                      {p.success} başarılı · {p.fail} başarısız · ort. {p.avg_latency_s}s
                    </div>
                  </div>
                  <div style={{textAlign:'right'}}>
                    <span style={{
                      display:'inline-block',
                      padding:'3px 10px',
                      borderRadius:6,
                      fontSize:13,
                      fontWeight:700,
                      fontFamily:'monospace',
                      background: p.rate_pct >= 90 ? 'rgba(74,222,128,0.15)' : 'rgba(239,68,68,0.15)',
                      color: p.rate_pct >= 90 ? '#4ade80' : '#f87171',
                      border: `1px solid ${p.rate_pct >= 90 ? 'rgba(74,222,128,0.3)' : 'rgba(239,68,68,0.3)'}`
                    }}>
                      %{p.rate_pct}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* GUI Tools Breakdown */}
        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.12)',borderRadius:10,padding:18}}>
          <div style={{fontSize:14,fontWeight:700,fontFamily:'monospace',color:'#ffffff',marginBottom:14}}>
            GUI VE MASAÜSTÜ ARAÇ AYRINTILARI
          </div>
          {(!gui.tools || Object.keys(gui.tools).length === 0) ? (
            <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',padding:'16px 0'}}>
              Henüz GUI/Masaüstü eylemi kaydedilmedi.
            </div>
          ) : (
            <div style={{display:'flex',flexDirection:'column',gap:8}}>
              {Object.entries(gui.tools).map(([toolName, t]) => {
                const total = (t.success || 0) + (t.fail || 0);
                const rate = total > 0 ? Math.round((t.success / total) * 100) : 100;
                return (
                  <div key={toolName} style={{background:'#121212',border:'1px solid rgba(255,255,255,0.08)',borderRadius:8,padding:'8px 12px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                    <div>
                      <span style={{fontFamily:'monospace',color:'#ffffff',fontSize:13}}>{toolName}</span>
                      <div style={{fontSize:11,color:'#A1A1AA',fontFamily:'monospace'}}>
                        {t.success} başarılı · {t.fail} başarısız
                      </div>
                    </div>
                    <span style={{
                      fontSize:12,
                      fontFamily:'monospace',
                      fontWeight:600,
                      color: rate >= 90 ? '#4ade80' : '#f87171'
                    }}>
                      %{rate}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Manager Tasks */}
          <div style={{marginTop:18,paddingTop:14,borderTop:'1px solid rgba(255,255,255,0.08)'}}>
            <div style={{fontSize:13,fontWeight:700,fontFamily:'monospace',color:'#ffffff',marginBottom:8}}>
              GÖREV VE HEDEF YÖNETİMİ
            </div>
            <div style={{background:'#121212',border:'1px solid rgba(255,255,255,0.08)',borderRadius:8,padding:'10px 14px',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
              <div>
                <div style={{color:'#ffffff',fontSize:13,fontWeight:500}}>Manager-Executor Başarısı</div>
                <div style={{fontSize:11,color:'#A1A1AA',fontFamily:'monospace',marginTop:2}}>
                  {tasks.success ?? 0} tamamlandı · {tasks.fail ?? 0} başarısız
                </div>
              </div>
              <span style={{
                fontSize:14,
                fontFamily:'monospace',
                fontWeight:700,
                color: (tasks.rate_pct ?? 100) >= 90 ? '#4ade80' : '#f87171'
              }}>
                %{tasks.rate_pct ?? 100}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function SettingsPanel({ onClose, pendingSkills = 0, onSkillsChange, autoSpeak, onAutoSpeakChange, isTab = false }) {
  const [subTab, setSubTab] = useState('basic') // 'basic' | 'advanced'
  const [keys, setKeys] = useState(() => {
    const base = { groq:'', cerebras:'', elevenlabs:'', elevenlabs_voice: VOICE_OPTIONS[0].id, edge_voice: 'tr-TR-AhmetNeural', gemini:'', sambanova:'', openrouter:'', nvidia:'' }
    try {
      const saved = JSON.parse(localStorage.getItem('ales_saved_api_keys') || '{}')
      return { ...base, ...saved }
    } catch (e) {
      return base
    }
  })
  const [rememberKeys, setRememberKeys] = useState(() => {
    try {
      const r = localStorage.getItem('ales_remember_keys')
      return r !== null ? r === 'true' : true
    } catch (e) {
      return true
    }
  })
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [cloudStatus, setCloudStatus] = useState(null)
  const [serverCfg, setServerCfg] = useState(null)
  const [refreshingModels, setRefreshingModels] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')

  useEffect(() => {
    authFetch(API_URL+'/config').then(r=>r.json()).then(cfg=>{
      if (cfg) {
        setServerCfg(cfg)
        if (cfg.elevenlabs_voice) setKeys(p=>({...p, elevenlabs_voice: cfg.elevenlabs_voice}))
        if (cfg.edge_voice) setKeys(p=>({...p, edge_voice: cfg.edge_voice}))
      }
    }).catch(()=>{})

    authFetch(API_URL+'/voices').then(r=>r.json()).then(d=>{
      if (d?.current) setKeys(p=>({...p, elevenlabs_voice: d.current}))
      if (d?.current_edge_voice) setKeys(p=>({...p, edge_voice: d.current_edge_voice}))
    }).catch(()=>{})

    if (isCloud) {
      authFetch(API_URL+'/status').then(r=>r.json()).then(setCloudStatus).catch(()=>{})
    }
  }, [])

  const refreshModels = async () => {
    setRefreshingModels(true)
    setRefreshMsg('')
    try {
      const res = await authFetch(API_URL + '/api/models/refresh', { method: 'POST' })
      const data = await res.json()
      if (data.ok) {
        setRefreshMsg('✓ Canlı modeller tarandı ve otomatik onarıldı')
      } else {
        setRefreshMsg(`⚠️ Hata: ${data.error || 'Bilinmeyen hata'}`)
      }
    } catch (e) {
      setRefreshMsg(`⚠️ Bağlantı hatası: ${e?.message || e}`)
    }
    setRefreshingModels(false)
    setTimeout(() => setRefreshMsg(''), 6000)
  }

  const save = async () => {
    const data = {}
    if (keys.groq.trim()) data.groq_key = keys.groq.trim()
    if (keys.cerebras.trim()) data.cerebras_key = keys.cerebras.trim()
    if (keys.elevenlabs.trim()) data.elevenlabs_key = keys.elevenlabs.trim()
    if (keys.gemini.trim()) data.gemini_key = keys.gemini.trim()
    if (keys.sambanova.trim()) data.sambanova_key = keys.sambanova.trim()
    if (keys.openrouter.trim()) data.openrouter_key = keys.openrouter.trim()
    if (keys.nvidia.trim()) data.nvidia_key = keys.nvidia.trim()
    if (keys.elevenlabs_voice) data.elevenlabs_voice = keys.elevenlabs_voice
    if (keys.edge_voice) data.edge_voice = keys.edge_voice

    if (rememberKeys) {
      try {
        localStorage.setItem('ales_saved_api_keys', JSON.stringify({
          groq: keys.groq.trim(),
          cerebras: keys.cerebras.trim(),
          elevenlabs: keys.elevenlabs.trim(),
          gemini: keys.gemini.trim(),
          sambanova: keys.sambanova.trim(),
          openrouter: keys.openrouter.trim(),
          nvidia: keys.nvidia.trim(),
        }))
        localStorage.setItem('ales_remember_keys', 'true')
      } catch (e) {}
    } else {
      try {
        localStorage.removeItem('ales_saved_api_keys')
        localStorage.setItem('ales_remember_keys', 'false')
      } catch (e) {}
    }

    if (isElectron) { try { await window.ales.saveConfig(data) } catch(e) {} }
    try {
      await authFetch(API_URL+'/config', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(data)
      })
      await authFetch(API_URL+'/api/session/sync', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ keys: data })
      }).catch(()=>{})
      authFetch(API_URL+'/config').then(r=>r.json()).then(setServerCfg).catch(()=>{})
      if (isCloud) authFetch(API_URL+'/status').then(r=>r.json()).then(setCloudStatus).catch(()=>{})
    } catch(e) {}
    setSaved(true)
    setTimeout(()=>{
      setSaved(false)
      if (onClose && !isTab) onClose()
    }, 1200)
  }

  const logoutCloud = () => {
    try { localStorage.removeItem('ales_cloud_key') } catch {}
    window.location.reload()
  }

  const testVoice = async () => {
    setTesting(true)
    try {
      const r = await authFetch(API_URL+'/speak_test', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ voice_id: keys.elevenlabs_voice, elevenlabs_key: keys.elevenlabs.trim(), edge_voice: keys.edge_voice })
      })
      const d = await r.json()
      if (d.ok && d.audio) {
        new Audio(`data:${d.mime||'audio/mpeg'};base64,${d.audio}`).play().catch(()=>{})
      }
    } catch(e) {}
    setTimeout(()=>setTesting(false), 1500)
  }

  const iStyle = {background:'#1E1E24',border:'1px solid rgba(255,255,255,0.22)',borderRadius:8,padding:'10px 12px',color:'#E4E4E7',fontSize:14,fontFamily:'monospace',outline:'none',width:'100%',boxSizing:'border-box'}

  return (
    <div className="settings-modal-content" style={{background:'#121212',borderBottom: isTab ? 'none' : '1px solid rgba(255,255,255,0.15)',padding: isTab ? '10px 0 30px' : '18px 20px',flexShrink:0,zIndex:9,maxHeight: isTab ? 'none' : '85vh',overflowY:'auto',color:'#E4E4E7'}}>
      {isCloud && (
        <div style={{background:'#1E1E24',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8,padding:'14px 16px',marginBottom:16}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10,flexWrap:'wrap',gap:8}}>
            <div style={{fontSize:14,fontWeight:700,color:'#4ade80',fontFamily:'monospace',letterSpacing:1}}>🌐 CLOUD MODU AKTİF</div>
            <button style={{padding:'6px 12px',background:'rgba(255,255,255,0.1)',border:'1px solid rgba(255,255,255,0.25)',borderRadius:6,color:'#ffffff',fontSize:12,fontWeight:600,cursor:'pointer',fontFamily:'monospace'}} onClick={logoutCloud}>
              ERİŞİM KODUNU DEĞİŞTİR / ÇIKIŞ
            </button>
          </div>
          <div style={{fontSize:13,color:'#A1A1AA',fontFamily:'monospace',marginBottom:10,lineHeight:1.5}}>
            Girdiğiniz API anahtarları sunucu oturumuna kaydedilir. Kalıcı kullanım için Render/Railway ortam değişkenlerinden de tanımlayabilirsiniz.
          </div>
          <div className="responsive-grid-2" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(140px, 1fr))',gap:8}}>
            {[
              {k:'has_groq',n:'Groq'},{k:'has_gemini',n:'Gemini'},{k:'has_cerebras',n:'Cerebras'},
              {k:'has_sambanova',n:'SambaNova'},{k:'has_openrouter',n:'OpenRouter'},{k:'has_nvidia',n:'NVIDIA'},
            ].map(p=>(
              <div key={p.k} style={{background:'#121212',border:'1px solid rgba(255,255,255,0.12)',borderRadius:6,padding:'6px 10px',display:'flex',alignItems:'center',gap:8,fontSize:12,color:'#ffffff',fontFamily:'monospace'}}>
                <div style={{width:8,height:8,borderRadius:'50%',background:(cloudStatus?.[p.k] || serverCfg?.[p.k])?'#4ade80':'#666666'}} />
                {p.n}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* APPLE / CLAUDE STİLİ SEKMELER: TEMEL & GELİŞMİŞ */}
      <div style={{
        display:'flex',
        background:'#1E1E24',
        borderRadius:10,
        padding:4,
        marginBottom:18,
        border:'1px solid rgba(255,255,255,0.14)'
      }}>
        <button
          onClick={()=>setSubTab('basic')}
          style={{
            flex:1,
            padding:'10px 14px',
            borderRadius:8,
            border:'none',
            background:subTab==='basic'?'#ffffff':'transparent',
            color:subTab==='basic'?'#000000':'#A1A1AA',
            fontWeight:700,
            fontSize:13,
            fontFamily:'monospace',
            cursor:'pointer',
            transition:'all .15s'
          }}
        >
          ✨ TEMEL (Sohbet & Model)
        </button>
        <button
          onClick={()=>setSubTab('advanced')}
          style={{
            flex:1,
            padding:'10px 14px',
            borderRadius:8,
            border:'none',
            background:subTab==='advanced'?'#ffffff':'transparent',
            color:subTab==='advanced'?'#000000':'#A1A1AA',
            fontWeight:700,
            fontSize:13,
            fontFamily:'monospace',
            cursor:'pointer',
            transition:'all .15s'
          }}
        >
          ⚙️ GELİŞMİŞ (Tüm Ayarlar)
        </button>
      </div>

      {/* ─── TEMEL AYARLAR (BASIC) ─── */}
      {subTab === 'basic' && (
        <div style={{display:'flex',flexDirection:'column',gap:16}}>
          {/* Model / Mod Seçimi */}
          <ModeSelector />

          {/* Temel API Anahtarları: Sadece Groq ve Gemini */}
          <div>
            <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:10}}>
              TEMEL API ANAHTARLARI
            </div>
            <div className="responsive-grid-2" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(220px, 1fr))',gap:12}}>
              {[
                {k:'groq',h:'has_groq',label:'Groq API Key (Hızlı Sohbet & Whisper Ses)',p:'gsk_...'},
                {k:'gemini',h:'has_gemini',label:'Gemini API Key (Google AI Görsel/Zeka)',p:'AIza... / AQ...'}
              ].map(f=>(
                <div key={f.k} style={{display:'flex',flexDirection:'column',gap:4}}>
                  <label style={{fontSize:12,color:'#E4E4E7',fontFamily:'monospace',fontWeight:600}}>{f.label}</label>
                  <input
                    style={iStyle}
                    type="password"
                    placeholder={serverCfg?.[f.h] ? `${f.p} (Mevcut: Ayarlandı)` : f.p}
                    value={keys[f.k]}
                    onChange={e=>setKeys(p=>({...p,[f.k]:e.target.value}))}
                  />
                  {serverCfg?.[f.h] && (
                    <span style={{fontSize:11,color:'#4ade80',fontFamily:'monospace'}}>✓ Aktif ve Tanımlı</span>
                  )}
                </div>
              ))}
            </div>
            <div style={{fontSize:12,color:'#A1A1AA',fontFamily:'monospace',marginTop:8}}>
              💡 ALES'in yanıt verebilmesi ve konuşabilmesi için Groq veya Gemini anahtarından en az biri yeterlidir.
            </div>
          </div>

          {/* Otomatik Seslendirme Toggle */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'12px 16px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8}}>
            <div style={{display:'flex',flexDirection:'column'}}>
              <span style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace'}}>OTOMATİK SESLENDİRME (AUTO-SPEAK)</span>
              <span style={{fontSize:13,color:'#A1A1AA',marginTop:3}}>Yanıtlar tamamlandığında sesli olarak okunur</span>
            </div>
            <button
              onClick={() => {
                const next = !autoSpeak;
                onAutoSpeakChange && onAutoSpeakChange(next);
                try { localStorage.setItem('ales_autospeak', String(next)); } catch {}
              }}
              style={{
                padding:'8px 16px',
                borderRadius:6,
                border:`1px solid ${autoSpeak ? '#ffffff' : 'rgba(255,255,255,0.3)'}`,
                background:autoSpeak ? '#ffffff' : '#222222',
                color:autoSpeak ? '#000000' : '#ffffff',
                fontWeight:700,
                fontSize:13,
                fontFamily:'monospace',
                cursor:'pointer'
              }}
            >
              {autoSpeak ? 'AÇIK' : 'KAPALI'}
            </button>
          </div>

          {/* Kaydet Butonu */}
          <div style={{display:'flex',gap:8,marginTop:6}}>
            <button style={{flex:1,padding:'12px',background:'#ffffff',border:'none',borderRadius:8,color:'#000000',fontWeight:'bold',fontSize:13,cursor:'pointer',fontFamily:'monospace'}} onClick={save}>
              {saved?'✓ KAYDEDİLDİ':'KAYDET'}
            </button>
            {onClose && (
              <button style={{flex:1,padding:'12px',background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.25)',borderRadius:8,color:'#ffffff',fontWeight:'600',fontSize:13,cursor:'pointer',fontFamily:'monospace'}} onClick={onClose}>
                {isTab ? 'SOHBETE DÖN' : 'İPTAL'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ─── GELİŞMİŞ AYARLAR (ADVANCED) ─── */}
      {subTab === 'advanced' && (
        <div style={{display:'flex',flexDirection:'column',gap:16}}>
          {/* Uyarı Bandı */}
          <div style={{
            display:'flex',
            alignItems:'center',
            gap:10,
            padding:'12px 16px',
            background:'rgba(234, 179, 8, 0.12)',
            border:'1px solid rgba(234, 179, 8, 0.35)',
            borderRadius:8,
            color:'#facc15',
            fontSize:13,
            fontFamily:'monospace',
            fontWeight:600
          }}>
            <span>⚠️ Gelişmiş ayarlar. Emin değilseniz dokunmayın.</span>
          </div>

          {/* Diğer Sağlayıcı Anahtarları */}
          <div>
            <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:1,marginBottom:10}}>
              DİĞER MODEL SAĞLAYICI ANAHTARLARI
            </div>
            <div className="responsive-grid-2" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit, minmax(220px, 1fr))',gap:10}}>
              {[
                {k:'cerebras',h:'has_cerebras',p:'Cerebras Key (csk_...)'},
                {k:'nvidia',h:'has_nvidia',p:'NVIDIA NIM Key (nvapi-...)'},
                {k:'sambanova',h:'has_sambanova',p:'SambaNova Key (sk_-)'},
                {k:'openrouter',h:'has_openrouter',p:'OpenRouter Key (sk-or-...)'},
                {k:'elevenlabs',h:'has_elevenlabs',p:'ElevenLabs Key (sk_...)'},
              ].map(f=>(
                <div key={f.k} style={{position:'relative',display:'flex',flexDirection:'column'}}>
                  <input
                    style={iStyle}
                    type="password"
                    placeholder={serverCfg?.[f.h] ? `${f.p} (Mevcut: Ayarlandı)` : f.p}
                    value={keys[f.k]}
                    onChange={e=>setKeys(p=>({...p,[f.k]:e.target.value}))}
                  />
                  {serverCfg?.[f.h] && (
                    <span style={{fontSize:11,color:'#4ade80',marginTop:3,fontFamily:'monospace'}}>✓ Sunucuda tanımlı</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Ses Motoru Seçimi */}
          <div>
            <div style={{fontSize:13,color:'#E4E4E7',fontFamily:'monospace',marginBottom:6,fontWeight:600}}>ELEVENLABS SESİ & TEST</div>
            <div style={{display:'flex',gap:10,marginBottom:12,alignItems:'center',flexWrap:'wrap'}}>
              <select style={{...iStyle,flex:'1 1 200px'}} value={keys.elevenlabs_voice} onChange={e=>setKeys(p=>({...p,elevenlabs_voice:e.target.value}))}>
                {VOICE_OPTIONS.map(v=><option key={v.id} value={v.id} style={{background:'#1a1a1a',color:'#ffffff'}}>{v.name}</option>)}
              </select>
              <button style={{padding:'11px 18px',background:'#2a2a2a',border:'1px solid rgba(255,255,255,0.35)',borderRadius:8,color:'#ffffff',fontSize:13,fontWeight:600,cursor:'pointer',fontFamily:'monospace',whiteSpace:'nowrap',flexShrink:0}} onClick={testVoice} disabled={testing}>
                {testing ? 'ÇALINIYOR...' : '▶ SESİ TEST ET'}
              </button>
            </div>
            <div style={{fontSize:13,color:'#E4E4E7',fontFamily:'monospace',marginBottom:6,fontWeight:600}}>ÜCRETSİZ SES (Edge-TTS - ElevenLabs yoksa kullanılır)</div>
            <select style={iStyle} value={keys.edge_voice} onChange={e=>setKeys(p=>({...p,edge_voice:e.target.value}))}>
              {EDGE_VOICE_OPTIONS.map(v=><option key={v.id} value={v.id} style={{background:'#1a1a1a',color:'#ffffff'}}>{v.name}</option>)}
            </select>
          </div>

          {/* Model Keşfi & Kendini Onarma */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'12px 16px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8,flexWrap:'wrap',gap:10}}>
            <div style={{display:'flex',flexDirection:'column'}}>
              <span style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace'}}>MODEL KEŞFİ & KENDİNİ ONARMA</span>
              <span style={{fontSize:13,color:'#A1A1AA',marginTop:3}}>Canlı API'leri (Groq, Gemini, Cerebras) tara, ölü modelleri otomatik onar</span>
              {refreshMsg && (
                <span style={{fontSize:12,color:refreshMsg.startsWith('✓') ? '#4ade80' : '#f87171',marginTop:4,fontFamily:'monospace',fontWeight:600}}>{refreshMsg}</span>
              )}
            </div>
            <button
              onClick={refreshModels}
              disabled={refreshingModels}
              style={{
                padding:'8px 16px',
                borderRadius:6,
                border:'1px solid rgba(255,255,255,0.3)',
                background:refreshingModels ? '#333333' : '#222222',
                color:'#ffffff',
                fontWeight:700,
                fontSize:13,
                fontFamily:'monospace',
                cursor:refreshingModels ? 'wait' : 'pointer'
              }}
            >
              {refreshingModels ? '🔄 TARANIYOR...' : '🔄 MODELLERİ TARA'}
            </button>
          </div>

          {/* Bu Cihaza Kaydet (Beni Hatırla) */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'12px 16px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.18)',borderRadius:8,flexWrap:'wrap',gap:10}}>
            <div style={{display:'flex',flexDirection:'column'}}>
              <span style={{fontSize:14,fontWeight:700,color:'#ffffff',fontFamily:'monospace'}}>BU CİHAZA KAYDET (BENİ HATIRLA)</span>
              <span style={{fontSize:13,color:'#A1A1AA',marginTop:3}}>API anahtarlarını tarayıcıda saklar; yenilemede otomatik yükler.</span>
            </div>
            <button
              onClick={() => {
                const next = !rememberKeys;
                setRememberKeys(next);
                try { localStorage.setItem('ales_remember_keys', String(next)); } catch {}
              }}
              style={{
                padding:'8px 16px',
                borderRadius:6,
                border:`1px solid ${rememberKeys ? '#ffffff' : 'rgba(255,255,255,0.3)'}`,
                background:rememberKeys ? '#ffffff' : '#222222',
                color:rememberKeys ? '#000000' : '#ffffff',
                fontWeight:700,
                fontSize:13,
                fontFamily:'monospace',
                cursor:'pointer'
              }}
            >
              {rememberKeys ? 'AÇIK (SAKLANIYOR)' : 'KAPALI'}
            </button>
          </div>

          {/* Kaydet Butonu */}
          <div style={{display:'flex',gap:8,marginTop:6}}>
            <button style={{flex:1,padding:'12px',background:'#ffffff',border:'none',borderRadius:8,color:'#000000',fontWeight:'bold',fontSize:13,cursor:'pointer',fontFamily:'monospace'}} onClick={save}>
              {saved?'✓ KAYDEDİLDİ':'KAYDET'}
            </button>
            {onClose && (
              <button style={{flex:1,padding:'12px',background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.25)',borderRadius:8,color:'#ffffff',fontWeight:'600',fontSize:13,cursor:'pointer',fontFamily:'monospace'}} onClick={onClose}>
                {isTab ? 'SOHBETE DÖN' : 'İPTAL'}
              </button>
            )}
          </div>

          {/* Ek Gelişmiş Paneller */}
          <SystemPromptPanel />
          <VaultPanel />
          <SkillsConnectorsPanel />
          <AdvancedPanel pendingSkills={pendingSkills} onSkillsChange={onSkillsChange} />
        </div>
      )}
    </div>
  )
}

// ─── GELISMIS PANEL: 8 YENI MODULUN ARAYUZU ───────────────────────
// NEDEN TEK PANEL: sekiz modul icin sekiz ayri acilir bolum, Ayarlar
// ekranini okunamaz hale getiriyordu. Burada tek katlanir bolum + alt
// sekmeler var; sadece ACIK sekme veri ceker (kapali panel istek yapmaz).
//
// TASARIM KURALI (VaultPanel ile ayni): hicbir alt panel fetch hatasinda
// KAYBOLMAZ. Hata durumunda "erisilemedi" satiri gosterilir, cunku bos
// ekran kullaniciya "boyle bir sey yok" der — yanlis bilgi.
function AdvancedPanel({ pendingSkills = 0, onSkillsChange, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const [sub, setSub] = useState('discovery')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  // Her alt sekmenin kendi verisi. null = henuz cekilmedi, {} = cekildi.
  const [tts, setTts] = useState(null)
  const [plugins, setPlugins] = useState(null)
  const [props, setProps] = useState(null)
  const [models, setModels] = useState(null)
  const [disc, setDisc] = useState(null)
  const [ca, setCa] = useState(null)
  const [jit, setJit] = useState(null)
  const [desk, setDesk] = useState(null)
  const [diag, setDiag] = useState(null)
  const [heal, setHeal] = useState(null)
  const [vec, setVec] = useState(null)
  // Faz 2-6 panelleri. Her biri BIRDEN FAZLA uctan beslenir, o yuzden
  // tek bir nesnede birlestirilir (asagidaki getMulti).
  const [spd, setSpd] = useState(null)    // hiz:     batch · spec · depo · pred
  const [iq, setIq] = useState(null)      // zeka:    moa · cer · reflection
  const [evo, setEvo] = useState(null)    // evrim:   self-evolution · darwin-godel
  const [ctrl, setCtrl] = useState(null)  // kontrol: openclaw · evocua
  const [hlt, setHlt] = useState(null)    // saglik:  timeout · surum · kesif
  // CodeAct plan/onay akisi
  const [task, setTask] = useState('')
  const [plan, setPlan] = useState(null)
  const [runOut, setRunOut] = useState(null)
  const [deskTitle, setDeskTitle] = useState('')
  const [deskTesting, setDeskTesting] = useState(false)
  const [deskTestResult, setDeskTestResult] = useState(null)

  const runDesktopTest = async () => {
    setDeskTesting(true)
    setDeskTestResult(null)
    try {
      const res = await authFetch(`${API_URL}/desktop/test`, { method: 'POST' })
      const d = await res.json()
      setDeskTestResult(d)
      flash(d.ok ? 'Desktop testi tamamlandı!' : (d.error || 'Desktop testi başarısız'))
    } catch (err) {
      setDeskTestResult({ ok: false, error: String(err) })
      flash('Test isteği başarısız oldu')
    } finally {
      setDeskTesting(false)
    }
  }

  const flash = (t) => { setMsg(t); setTimeout(()=>setMsg(''), 3500) }

  // Tek fetch sarmalayici: hata YUTULMAZ, ekrana yazilir.
  const get = useCallback(async (url, set) => {
    try {
      const r = await authFetch(`${API_URL}${url}`)
      const d = await r.json()
      set(d)
      return d
    } catch (e) {
      set({ _offline: true, error: 'sunucuya erişilemedi' })
      return null
    }
  }, [])

  // Bir sekmede birden fazla uc varsa: hepsini AYNI ANDA cek ve tek
  // nesnede birlestir. Sirayla cekmek 4 uclu bir sekmede gozle gorulur
  // gecikme yapardi. Bir uc patlasa DIGERLERI yine gosterilir — o alan
  // {_offline:true} olur, panel "alınamadı" yazar.
  const getMulti = useCallback(async (map, set) => {
    const keys = Object.keys(map)
    const pairs = await Promise.all(keys.map(async k => {
      try {
        const r = await authFetch(`${API_URL}${map[k]}`)
        return [k, await r.json()]
      } catch (e) { return [k, { _offline: true, error: 'sunucuya erişilemedi' }] }
    }))
    const obj = {}
    pairs.forEach(([k, v]) => { obj[k] = v })
    set(obj)
    return obj
  }, [])

  const call = useCallback(async (url, opts, after) => {
    setBusy(true)
    try {
      const r = await authFetch(`${API_URL}${url}`, opts)
      const d = await r.json()
      flash(d?.error ? `hata: ${d.error}` : (d?.message || 'tamam'))
      after && await after(d)
      return d
    } catch (e) {
      flash('istek başarısız — sunucu kapalı olabilir')
      return null
    } finally { setBusy(false) }
  }, [])

  // Sadece acik olan sekmeyi yukle. Kapali panel HIC istek yapmaz.
  useEffect(() => {
    if (!open) return
    if (sub==='tts') get('/tts/engine', setTts)
    else if (sub==='plugins') get('/plugins', setPlugins)
    else if (sub==='skills') get('/skills/proposals?status=pending', setProps)
    else if (sub==='models') get('/models', setModels)
    else if (sub==='discovery') get('/model-discovery', setDisc)
    else if (sub==='codeact') { get('/codeact', setCa); get('/jit?limit=25', setJit) }
    else if (sub==='desktop') get('/desktop/backend', setDesk)
    else if (sub==='diag') { get('/diagnostics', setDiag); get('/selfheal/status', setHeal); get('/memory/long/vector', setVec) }
    else if (sub==='hiz') getMulti({batch:'/batch-inference/stats', spec:'/spec-cache/stats',
                                    depo:'/token-optimizer/stats', pred:'/predictive/stats'}, setSpd)
    else if (sub==='zeka') getMulti({moa:'/moa/stats', cer:'/cer/stats',
                                     cerList:'/cer/experiences?limit=12',
                                     refl:'/reflection/stats'}, setIq)
    else if (sub==='evrim') getMulti({se:'/self-evolution/stats', dgm:'/darwin-godel/stats',
                                      trial:'/darwin-godel/trial'}, setEvo)
    else if (sub==='kontrol') getMulti({claw:'/openclaw/status', cua:'/evocua/status'}, setCtrl)
    else if (sub==='saglik') getMulti({to:'/adaptive-timeouts/stats',
                                       vers:'/config-versions?limit=15',
                                       env:'/env-status',
                                       disc:'/auto-discovery/status'}, setHlt)
  }, [open, sub, get, getMulti])

  // Bekleyen oneri sayisi degistiyse (baska yerden onay/red) listeyi tazele.
  useEffect(() => {
    if (open && sub==='skills') get('/skills/proposals?status=pending', setProps)
  }, [pendingSkills, open, sub, get])

  const iStyle = {background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:6,padding:'8px 12px',color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none',width:'100%',boxSizing:'border-box'}
  const bStyle = {padding:'7px 12px',background:'rgba(255,255,255,0.14)',border:'1px solid rgba(255,255,255,0.3)',borderRadius:6,color:'#ffffff',fontSize:12,fontWeight:600,cursor:busy?'default':'pointer',fontFamily:'monospace',opacity:busy?0.5:1,whiteSpace:'nowrap'}
  const tabStyle = (a) => ({flex:'1 1 auto',padding:'8px 10px',background:a?'rgba(255,255,255,0.25)':'rgba(255,255,255,0.06)',border:'1px solid '+(a?'#ffffff':'rgba(255,255,255,0.2)'),borderRadius:6,color:a?'#ffffff':'#cccccc',fontSize:11,fontWeight:a?700:500,cursor:'pointer',fontFamily:'monospace',letterSpacing:0.5})
  const row = {display:'flex',alignItems:'center',gap:8,padding:'7px 10px',background:'rgba(255,255,255,0.05)',border:'1px solid rgba(255,255,255,0.14)',borderRadius:6,marginBottom:5,fontSize:12,fontFamily:'monospace',color:'#e0e0e0'}
  const dot = (ok) => ({width:7,height:7,borderRadius:'50%',flexShrink:0,background:ok?'#4ade80':'#666666',boxShadow:ok?'0 0 6px #4ade80':'none'})
  const label = {fontSize:12,color:'#d0d0d0',fontFamily:'monospace',marginBottom:6,letterSpacing:0.5,fontWeight:600}
  const pre = {margin:0,padding:'8px 10px',background:'rgba(0,0,0,0.6)',border:'1px solid rgba(255,255,255,0.18)',borderRadius:6,fontSize:12,fontFamily:'monospace',color:'#e0e0e0',whiteSpace:'pre-wrap',wordBreak:'break-all',maxHeight:180,overflowY:'auto'}
  const off = (d) => d?._offline || d?.unavailable

  const SUBS = [
    {id:'tts',     n:'SES'},
    {id:'plugins', n:'EKLENTİ'},
    {id:'skills',  n:`BECERİ${pendingSkills>0?` (${pendingSkills})`:''}`},
    {id:'models',  n:'MODEL'},
    {id:'discovery', n:'MODEL KEŞFİ'},
    {id:'codeact', n:'CODEACT'},
    {id:'desktop', n:'MASAÜSTÜ'},
    {id:'hiz',     n:'HIZ'},
    {id:'zeka',    n:'ZEKA'},
    {id:'evrim',   n:'EVRİM (Deneysel)'},
    {id:'kontrol', n:'KONTROL'},
    {id:'saglik',  n:'SAĞLIK'},
    {id:'diag',    n:'TEŞHİS'},
  ]

  // Saglik durumu ETIKETLE gosterilir, RENKLE degil: bu arayuz bilincli
  // olarak tek renkli (siyah/gri/beyaz). Yesil-kirmizi eklemek temayi bozardi,
  // ustelik renk tek basina erisilebilir bir isaret degil.
  const HEALTH = {
    OK:          {t:'OK',          ok:true },
    WARN:        {t:'UYARI',       ok:false},
    ERROR:       {t:'HATA',        ok:false},
    UNAVAILABLE: {t:'ANAHTAR YOK', ok:false},
  }
  const fmtTime = (iso) => {
    if (!iso) return 'hiç'
    const d = new Date(iso)
    return isNaN(d) ? String(iso) : d.toLocaleString('tr-TR')
  }

  return (
    <div style={{marginTop:12,borderTop:'1px solid rgba(255,255,255,0.12)',paddingTop:12}}>
      <div
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(prev => !prev);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setOpen(prev => !prev);
          }
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: 'pointer',
          padding: '8px 12px',
          borderRadius: 6,
          background: open ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.04)',
          marginBottom: open ? 12 : 0
        }}
      >
        <span style={{fontSize:13,color:'#ffffff',fontWeight:700,fontFamily:'monospace',letterSpacing:2}}>
          {open ? '▾ GELİŞMİŞ' : '▸ GELİŞMİŞ'}
        </span>
        {pendingSkills>0 && <span style={{fontSize:11,padding:'2px 8px',borderRadius:7,background:'rgba(255,255,255,0.2)',color:'#ffffff',fontFamily:'monospace',fontWeight:600}}>{pendingSkills} beceri</span>}
        <span style={{fontSize:11,color:'#bbbbbb',fontFamily:'monospace',marginLeft:'auto'}}>
          {open ? '▲ kapat' : '▼ model keşfi · model · hız · zeka · teşhis'}
        </span>
      </div>

      {Boolean(open) && (
        <div style={{marginTop: 8}}>
          <div style={{display:'flex',gap:5,marginBottom:10,flexWrap:'wrap'}}>
            {SUBS.map(s=>(
              <button key={s.id} style={{...tabStyle(sub===s.id),minWidth:68}} onClick={()=>setSub(s.id)}>{s.n}</button>
            ))}
          </div>
          {msg && <div style={{fontSize:12,color:'#ffffff',fontFamily:'monospace',marginBottom:8,padding:'6px 10px',background:'rgba(255,255,255,0.12)',borderRadius:5,fontWeight:600}}>{msg}</div>}

          {/* ─── SES: akan TTS ───────────────────────────────── */}
          {sub==='tts' && (
            <div>
              {!tts && <div style={label}>yükleniyor…</div>}
              {off(tts) && <div style={label}>ses motoru bilgisi alınamadı ({tts?.error||'modül yok'})</div>}
              {tts && !off(tts) && <>
                <div style={row}><div style={dot(tts.available)} />motor: <b style={{color:'#ffffff'}}>{tts.engine||'yok'}</b>
                  <span style={{marginLeft:'auto',color:'#cccccc'}}>{tts.mime}</span></div>
                <div style={row}><div style={dot(tts.stream_on)} />cümle cümle akış: <b style={{color:'#ffffff'}}>{tts.stream_on?'AÇIK':'KAPALI'}</b>
                  {tts.avg_first_audio_s!=null && <span style={{marginLeft:'auto',color:'#cccccc'}}>ilk ses ~{tts.avg_first_audio_s}s</span>}</div>
                {/* KRITIK BILGI: yerel oynatma = ses PC hoparlorunden cikar.
                    Telefondan kullanan biri "ses gelmiyor" der ve nedenini
                    hicbir yerde goremez; o yuzden acikca yaziyoruz. */}
                {tts.local_playback && <div style={{...row,borderColor:'rgba(255,255,255,0.2)'}}>⚠ bu motor sesi <b style={{color:'#ffffff'}}>bilgisayarın hoparlöründen</b> çalar — telefondan duyulmaz</div>}
                <div style={{display:'flex',gap:5,marginTop:6,marginBottom:6}}>
                  <button style={{...bStyle,flex:1}} disabled={busy}
                    onClick={()=>call('/tts/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:!tts.stream_on})},()=>get('/tts/engine',setTts))}>
                    {tts.stream_on?'AKIŞI KAPAT':'AKIŞI AÇ'}
                  </button>
                  <button style={bStyle} disabled={busy} onClick={()=>get('/tts/engine',setTts)}>YENİLE</button>
                </div>
                <div style={label}>MOTOR SEÇİMİ (kurulu olmayanlar seçilemez)</div>
                {(tts.engines||[]).map(e=>(
                  <div key={e.name} style={row}>
                    <div style={dot(e.installed)} />
                    <span style={{color:e.name===tts.engine?'#fff':'#999'}}>{e.name}</span>
                    {e.local_playback && <span style={{color:'#cccccc'}}>· yerel</span>}
                    <span style={{marginLeft:'auto',display:'flex',gap:5,alignItems:'center'}}>
                      {!e.installed && <span style={{color:'#aaaaaa',fontSize:11}}>{e.reason}</span>}
                      {e.installed && e.name!==tts.engine && <button style={bStyle} disabled={busy}
                        onClick={()=>call('/tts/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:e.name})},()=>get('/tts/engine',setTts))}>SEÇ</button>}
                    </span>
                  </div>
                ))}
                <div style={label}>TÜRKÇE SES</div>
                <div style={{display:'flex',gap:5}}>
                  {(tts.voices||[]).map(v=>(
                    <button key={v} style={{...bStyle,flex:1,color:v===tts.voice?'#fff':'#888'}} disabled={busy}
                      onClick={()=>call('/tts/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:v})},()=>get('/tts/engine',setTts))}>{v}</button>
                  ))}
                </div>
              </>}
            </div>
          )}

          {/* ─── EKLENTILER ──────────────────────────────────── */}
          {sub==='plugins' && (
            <div>
              {!plugins && <div style={label}>yükleniyor…</div>}
              {off(plugins) && <div style={label}>eklenti yükleyici yok ({plugins?.error||'modül yüklenemedi'})</div>}
              {plugins && !off(plugins) && <>
                <div style={{...label,marginBottom:6}}>klasör: {plugins.dir||'?'} — dosya ekle/çıkar, sonra YENİDEN TARA (ALES'i kapatmak gerekmez)</div>
                <div style={{display:'flex',gap:5,marginBottom:7}}>
                  <button style={{...bStyle,flex:1}} disabled={busy}
                    onClick={()=>call('/plugins/reload',{method:'POST'},()=>get('/plugins',setPlugins))}>YENİDEN TARA</button>
                  <span style={{...label,marginBottom:0,alignSelf:'center'}}>{plugins.stats?.enabled_now??0}/{plugins.stats?.plugins??0} aktif · {plugins.stats?.tools??0} araç</span>
                </div>
                {(plugins.plugins||[]).length===0 && <div style={pre}>Yüklü eklenti yok. {plugins.dir||'plugins/'} altına register() fonksiyonu olan bir .py dosyası koy ve YENİDEN TARA'ya bas.</div>}
                {(plugins.plugins||[]).map(p=>(
                  <div key={p.id} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(p.enabled && !p.load_error)} />
                    <b style={{color:'#ffffff'}}>{p.id}</b>
                    <span style={{color:'#cccccc'}}>v{p.version} · {p.tool_count} araç</span>
                    <span style={{marginLeft:'auto',display:'flex',gap:4}}>
                      <button style={bStyle} disabled={busy}
                        onClick={()=>call(`/plugins/${p.id}/toggle`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:!p.enabled})},()=>get('/plugins',setPlugins))}>{p.enabled?'KAPAT':'AÇ'}</button>
                      <button style={bStyle} disabled={busy}
                        onClick={()=>call(`/plugins/${p.id}/reload`,{method:'POST'},()=>get('/plugins',setPlugins))}>YENİLE</button>
                      {/* NOT: bu DOSYAYI SILMEZ, sadece bellekten kaldirir. */}
                      <button style={bStyle} disabled={busy}
                        onClick={()=>call(`/plugins/${p.id}`,{method:'DELETE'},()=>get('/plugins',setPlugins))}>KALDIR</button>
                    </span>
                    <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{p.description}</div>
                    {p.load_error && <div style={{flexBasis:'100%',color:'#e8e8e8',fontSize:11}}>!! yüklenemedi: {p.load_error}</div>}
                    {(p.warnings||[]).map((w,i)=><div key={i} style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>· {w}</div>)}
                  </div>
                ))}
              </>}
            </div>
          )}

          {/* ─── BECERI ONERILERI ────────────────────────────── */}
          {sub==='skills' && (
            <div>
              {!props && <div style={label}>yükleniyor…</div>}
              {off(props) && <div style={label}>beceri öğrenme modülü yok ({props?.error||'modül yüklenemedi'})</div>}
              {props && !off(props) && <>
                <div style={{...label,marginBottom:7,lineHeight:1.5}}>
                  ALES tekrar eden istekleri izler ve aynı araçlarla çözülen kalıpları
                  beceri olarak ÖNERİR. Onaylamadan hiçbiri skills.json'a yazılmaz;
                  onaylanan beceri anında Fast Path'e girer (o istek artık LLM'e gitmez).
                </div>
                {(props.proposals||[]).length===0 && <div style={pre}>Onay bekleyen öneri yok. {props.stats?.observed??0} gözlem yapıldı, {props.stats?.proposed??0} öneri üretildi.</div>}
                {(props.proposals||[]).map(p=>(
                  <div key={p.id} style={{...row,flexDirection:'column',alignItems:'stretch',gap:4}}>
                    <div style={{display:'flex',alignItems:'center',gap:6}}>
                      <div style={dot(true)} />
                      <b style={{color:'#ffffff'}}>{p.entry?.name||p.id}</b>
                      <span style={{color:'#cccccc'}}>{p.occurrences}× görüldü</span>
                      <span style={{marginLeft:'auto',display:'flex',gap:4}}>
                        <button style={bStyle} disabled={busy}
                          onClick={()=>call(`/skills/proposals/${p.id}/approve`,{method:'POST'},async()=>{
                            const d = await get('/skills/proposals?status=pending', setProps)
                            onSkillsChange && onSkillsChange(d?.pending ?? 0)
                          })}>ONAYLA</button>
                        <button style={bStyle} disabled={busy}
                          onClick={()=>call(`/skills/proposals/${p.id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'elle reddedildi'})},async()=>{
                            const d = await get('/skills/proposals?status=pending', setProps)
                            onSkillsChange && onSkillsChange(d?.pending ?? 0)
                          })}>REDDET</button>
                      </span>
                    </div>
                    <div style={{color:'#d0d0d0',fontSize:11}}>{p.why}</div>
                    <div style={{color:'#d0d0d0',fontSize:11}}>risk: {p.risk}</div>
                    <div style={{color:'#d0d0d0',fontSize:11}}>araçlar: {(p.tools||[]).join(' → ')}</div>
                    <div style={{color:'#cccccc',fontSize:11}}>anahtar kelimeler: {(p.entry?.match?.keywords||[]).join(', ')}</div>
                    {(p.samples||[]).slice(0,3).map((s,i)=><div key={i} style={{color:'#cccccc',fontSize:11}}>örnek: "{s}"</div>)}
                  </div>
                ))}
                <div style={{display:'flex',gap:5,marginTop:6}}>
                  <button style={bStyle} disabled={busy} onClick={()=>get('/skills/proposals?status=pending',setProps)}>YENİLE</button>
                  <button style={bStyle} disabled={busy}
                    onClick={()=>call('/skills/observations',{method:'DELETE'},()=>get('/skills/proposals?status=pending',setProps))}>GÖZLEMLERİ TEMİZLE</button>
                </div>
              </>}
            </div>
          )}

          {/* ─── MODEL KATMANLARI (Kimi K3 dahil) ────────────── */}
          {sub==='models' && (
            <div>
              {!models && <div style={label}>yükleniyor…</div>}
              {off(models) && <div style={label}>model tablosu alınamadı</div>}
              {models && !off(models) && <>
                <div style={{...label,marginBottom:7}}>aktif mod: <b style={{color:'#ffffff'}}>{models.mode}</b> · heavy {models.heavy_available?'kullanılabilir':'kapalı'}</div>
                {(models.layers||[]).map(l=>(
                  <div key={l.layer} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(l.active_now)} />
                    <b style={{color:'#ffffff'}}>{l.layer}</b>
                    {l.heavy_only && <span style={{fontSize:11,padding:'0 5px',borderRadius:6,background:'rgba(255,255,255,0.12)',color:'#ffffff'}}>HEAVY</span>}
                    <span style={{color:'#d0d0d0'}}>{l.provider}</span>
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>{l.timeout_s}s</span>
                    <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{l.model}</div>
                    {/* Neden kapali oldugunu ACIKCA yaz: "anahtar yok" ile
                        "bu modda kapali" tamamen farkli iki cozum ister. */}
                    {!l.active_now && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>kapalı: {l.reason||(l.heavy_only?'Heavy/Meclis modu gerekir':'?')}</div>}
                    {!l.has_key && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>anahtar yok ({l.provider}) — Ayarlar'dan gir</div>}
                  </div>
                ))}
                <div style={label}>SAĞLAYICILAR: {(models.providers||[]).join(', ')||'yok'}</div>
              </>}
            </div>
          )}

          {/* ─── MODEL KESFI (model_registry) ─────────────────── */}
          {sub==='discovery' && (
            <div>
              {!disc && <div style={label}>yükleniyor…</div>}
              {off(disc) && <div style={label}>model keşfi bilgisi alınamadı ({disc?.error||'modül yok'})</div>}
              {disc && !off(disc) && disc.available===false && (
                <div style={row}>⚠ model keşfi kullanılamıyor: {disc.error}</div>
              )}
              {disc && !off(disc) && disc.available!==false && <>
                {/* ÜST SATIR: kullanicinin bakmasi gereken tek sayi. */}
                <div style={{...row,flexWrap:'wrap'}}>
                  <div style={dot(disc.running)} />
                  son güncelleme: <b style={{color:'#ffffff'}}>{fmtTime(disc.last_refresh)}</b>
                  <span style={{marginLeft:'auto',color:'#cccccc'}}>
                    her {Math.round((disc.interval_s||1800)/60)} dk · {disc.timeout_s}s zaman aşımı
                  </span>
                  <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>
                    {disc.totals?.models ?? 0} model · {disc.totals?.ok ?? 0} sağlayıcı OK
                    {disc.totals?.warn ? ` · ${disc.totals.warn} uyarı` : ''}
                    {disc.totals?.error ? ` · ${disc.totals.error} hata` : ''}
                    {disc.totals?.unavailable ? ` · ${disc.totals.unavailable} anahtarsız` : ''}
                    {!disc.running && ' · ⚠ zamanlayıcı ÇALIŞMIYOR'}
                  </div>
                </div>

                {/* Eskimis katman varsa EN TEPEDE uyar: asil eylem burasi. */}
                {disc.totals?.stale_layers > 0 && (
                  <div style={{...row,borderColor:'rgba(255,255,255,0.2)',flexWrap:'wrap'}}>
                    ⚠ <b style={{color:'#ffffff'}}>{disc.totals.stale_layers} katmanın</b> model adı sağlayıcı listesinde yok
                    <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>
                      Çağrılar yine denenir. Sağlayıcı gerçekten reddederse ALES kendiliğinden
                      aynı aileden geçerli bir modele geçer.
                    </div>
                  </div>
                )}

                <div style={{display:'flex',gap:5,marginTop:6,marginBottom:7}}>
                  <button style={{...bStyle,flex:1}} disabled={busy}
                    onClick={()=>call('/model-discovery/refresh',{method:'POST'},()=>get('/model-discovery',setDisc))}>
                    {busy?'YENİLENİYOR…':'YENİLE'}
                  </button>
                  <button style={{...bStyle,background:'rgba(239,68,68,0.15)',border:'1px solid rgba(239,68,68,0.3)',color:'#fca5a5'}} disabled={busy}
                    onClick={()=>call('/model-discovery/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({what:'blacklist'})},()=>get('/model-discovery',setDisc))}>
                    Reset Model Blacklist
                  </button>
                  <button style={bStyle} disabled={busy}
                    onClick={()=>call('/model-discovery/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({what:'all'})},()=>get('/model-discovery',setDisc))}>
                    SIFIRLA
                  </button>
                </div>

                {/* ─── SAGLAYICI SAGLIK TABLOSU ─── */}
                <div style={label}>SAĞLAYICILAR</div>
                {(disc.providers||[]).map(p=>{
                  const h = HEALTH[p.status] || {t:p.status,ok:false}
                  return (
                    <div key={p.provider} style={{...row,flexWrap:'wrap'}}>
                      <div style={dot(h.ok)} />
                      <b style={{color:'#ffffff'}}>{p.label}</b>
                      <span style={{fontSize:11,padding:'0 5px',borderRadius:6,background:'rgba(255,255,255,0.1)',color:'#ffffff'}}>{h.t}</span>
                      <span style={{marginLeft:'auto',color:'#cccccc'}}>{p.count} model</span>
                      <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>
                        {p.used_by?.length? `katman: ${p.used_by.join(', ')}` : 'hiçbir katman kullanmıyor'}
                        {' · '}
                        {/* "canli" ile "onbellekten" ayrimi kritik: ikinci
                            durumda gordugunuz liste ESKI olabilir. */}
                        {p.source==='live'?'canlı':p.source==='cache'?'önbellekten':p.source==='static'?'statik yedek liste':'liste yok'}
                        {p.fetched_at? ` · ${fmtTime(p.fetched_at)}`:''}
                      </div>
                      {!p.has_key && p.auth_required && (
                        <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>anahtar yok — Ayarlar'dan gir (bu sağlayıcı atlanıyor)</div>
                      )}
                      {p.error && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11,wordBreak:'break-all'}}>{p.error}</div>}
                      {p.source==='static' && (
                        <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>⚠ genel model listesi ucu yok — doğrulama bu sağlayıcı için kapalı</div>
                      )}
                      {!!(p.overrides && Object.keys(p.overrides).length) && Object.entries(p.overrides).map(([d,l])=>(
                        <div key={d} style={{flexBasis:'100%',color:'#e0e0e0',fontSize:11}}>otomatik değişim: {d} → <b style={{color:'#ffffff'}}>{l}</b></div>
                      ))}
                      {!!p.blacklisted?.length && (
                        <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>kara liste: {p.blacklisted.join(', ')}</div>
                      )}
                    </div>
                  )
                })}

                {/* ─── KATMAN DOGRULAMASI ─── */}
                <div style={{...label,marginTop:7}}>KATMAN DOĞRULAMASI</div>
                {(disc.layers||[]).map(l=>(
                  <div key={l.layer} style={{...row,flexWrap:'wrap'}}>
                    {/* known===null: liste alinamadi, HUKUM YOK. Bunu "bozuk"
                        gostermek yanlis alarm olurdu. */}
                    <div style={dot(l.known!==false)} />
                    <b style={{color:'#ffffff'}}>{l.layer}</b>
                    <span style={{color:'#d0d0d0'}}>{l.provider}</span>
                    <span style={{marginLeft:'auto',color:'#cccccc',fontSize:11}}>
                      {l.known===true?'listede var':l.known===false?'LİSTEDE YOK':'doğrulanamadı'}
                    </span>
                    <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>
                      {l.effective_model}
                      {l.overridden && <span style={{color:'#e0e0e0'}}> ← otomatik ({l.model})</span>}
                    </div>
                    {l.blacklisted && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>kara listede — bu katman atlanıyor</div>}
                    {l.known===null && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{l.provider} listesi alınamadı ({l.list_source}) — çağrı engellenmiyor</div>}
                    {!!l.suggestions?.length && (
                      <div style={{flexBasis:'100%',color:'#e0e0e0',fontSize:11,wordBreak:'break-all'}}>öneri: {l.suggestions.slice(0,3).join(' · ')}</div>
                    )}
                  </div>
                ))}

                {/* ─── KESIF GUNLUGU: yeni / kaldirilan modeller ─── */}
                <div style={{...label,marginTop:7}}>SON DEĞİŞİKLİKLER</div>
                {!disc.events?.length && <div style={{...label,color:'#aaaaaa'}}>henüz değişiklik yok</div>}
                {!!disc.events?.length && (
                  <pre style={pre}>{disc.events.map(e=>{
                    const k = e.kind==='added'?'+ yeni':e.kind==='removed'?'- kaldırıldı':e.kind==='blacklisted'?'x kara liste':e.kind==='substituted'?'» değiştirildi':e.kind==='revived'?'^ geri döndü':e.kind
                    return `${fmtTime(e.time)}  ${e.provider}  ${k}  ${e.model}${e.extra?`  (${e.extra})`:''}`
                  }).join('\n')}</pre>
                )}

                {/* ─── KARAR GUNLUGU (dogrulama + fallback) ─── */}
                <div style={{...label,marginTop:7}}>KARAR GÜNLÜĞÜ</div>
                {!disc.log?.length && <div style={{...label,color:'#aaaaaa'}}>kayıt yok</div>}
                {!!disc.log?.length && (
                  <pre style={pre}>{disc.log.map(e=>`${fmtTime(e.time)}  [${e.level}]  ${e.text}`).join('\n')}</pre>
                )}

                <div style={{...label,marginTop:7,lineHeight:1.5,color:'#d0d0d0'}}>
                  {disc.note}
                  <br/>Önbellek: {disc.cache_file}
                </div>
              </>}
            </div>
          )}

          {/* ─── CODEACT + JIT ───────────────────────────────── */}
          {sub==='codeact' && (
            <div>
              {/* GUVENLIK METNI: kullanici neyi onayladigini bilmeli. */}
              <div style={{...label,marginBottom:7,lineHeight:1.5}}>
                Görev tek kod bloğu olarak yazılır ve ayrı bir süreçte, zaman
                sınırlı, kısıtlı import'larla çalışır. Kod ÖNCE gösterilir —
                sen ONAYLA'ya basmadan hiçbir şey çalışmaz. Bu kapı hiçbir modda
                (cheat dahil) kalkmaz.
              </div>
              {ca && !ca.available && <div style={{...row}}>⚠ codeact yüklenemedi: {ca.error}</div>}
              {ca?.available && <div style={row}>
                <div style={dot(true)} />zaman sınırı {ca.info?.timeout_s}s · node {ca.info?.node_available?'var':'yok'} · python {ca.info?.python_available?'var':'yok'} · {ca.stats?.runs??0} çalıştırma / {ca.stats?.blocked??0} engellendi
              </div>}
              <div style={{...label,marginTop:6}}>GÖREV</div>
              <textarea style={{...iStyle,minHeight:52,resize:'vertical'}} value={task}
                onChange={e=>setTask(e.target.value)} placeholder="örn: masaüstündeki .txt dosyalarını listele ve satır sayılarını topla" />
              <div style={{display:'flex',gap:5,marginTop:5}}>
                <button style={{...bStyle,flex:1}} disabled={busy||!task.trim()}
                  onClick={async()=>{
                    setRunOut(null); setPlan(null); setBusy(true)
                    try {
                      const r = await authFetch(`${API_URL}/codeact/plan`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task})})
                      const d = await r.json(); setPlan(d)
                      if (d?.error) flash(d.error)
                    } catch { flash('plan isteği başarısız') } finally { setBusy(false) }
                  }}>1) PLANLA (çalıştırmaz)</button>
                <button style={bStyle} disabled={busy} onClick={()=>{setPlan(null);setRunOut(null)}}>TEMİZLE</button>
              </div>
              {plan && <div style={{marginTop:7}}>
                <div style={label}>ÜRETİLEN KOD ({plan.lang||'python'}) {plan.ok?'· statik denetim geçti':'· REDDEDİLDİ'}</div>
                {plan.code && <pre style={pre}>{plan.code}</pre>}
                {plan.error && <div style={{...row,marginTop:4}}>⚠ {plan.error}</div>}
                {(plan.static?.blocked||[]).map((b,i)=><div key={i} style={{...label,color:'#e0e0e0'}}>engel: {b}</div>)}
                {(plan.static?.warnings||[]).map((w,i)=><div key={i} style={{...label}}>uyarı: {w}</div>)}
                {plan.reply && !plan.code && <pre style={pre}>{plan.reply}</pre>}
                {plan.ok && plan.code && <button style={{...bStyle,width:'100%',marginTop:5,background:'rgba(255,255,255,0.14)',color:'#fff'}} disabled={busy}
                  onClick={async()=>{
                    setBusy(true)
                    try {
                      const r = await authFetch(`${API_URL}/codeact/run`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:plan.code,lang:plan.lang,approved:true})})
                      setRunOut(await r.json())
                    } catch { flash('çalıştırma isteği başarısız') } finally { setBusy(false); get('/codeact',setCa) }
                  }}>2) ONAYLA VE ÇALIŞTIR</button>}
              </div>}
              {runOut && <div style={{marginTop:7}}>
                <div style={label}>SONUÇ {runOut.ok?'· başarılı':'· hata'} {runOut.result?.elapsed!=null?`· ${runOut.result.elapsed}s`:''}</div>
                <pre style={pre}>{runOut.result?.stdout || runOut.result?.stderr || runOut.error || JSON.stringify(runOut,null,1)}</pre>
              </div>}

              <div style={{...label,marginTop:10}}>DERLENMİŞ GÖREVLER (JIT) — aynı görev tekrar gelirse LLM'e hiç gitmez</div>
              {jit && off(jit) && <div style={label}>jit modülü yok</div>}
              {jit && !off(jit) && <>
                <div style={row}><div style={dot((jit.stats?.entries??0)>0)} />
                  {jit.stats?.entries??0} kayıt · isabet %{Math.round((jit.stats?.hit_rate||0)*100)} · {jit.stats?.llm_calls_saved??0} LLM turu atlandı
                  <span style={{marginLeft:'auto',display:'flex',gap:4}}>
                    <button style={bStyle} disabled={busy} onClick={()=>call('/jit/stats/reset',{method:'POST'},()=>get('/jit?limit=25',setJit))}>SAYAÇ SIFIRLA</button>
                    <button style={bStyle} disabled={busy} onClick={()=>call('/jit',{method:'DELETE'},()=>get('/jit?limit=25',setJit))}>HEPSİNİ SİL</button>
                  </span>
                </div>
                {(jit.entries||[]).map(e=>(
                  <div key={e.key} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(!e.quarantined && !e.stale)} />
                    <span style={{color:'#ffffff',flex:1,overflow:'hidden',textOverflow:'ellipsis'}}>{e.task}</span>
                    <span style={{color:'#cccccc'}}>{e.uses}× · {e.ok_count}✓/{e.fail_count}✗</span>
                    <span style={{display:'flex',gap:4}}>
                      {!e.quarantined && <button style={bStyle} disabled={busy}
                        onClick={()=>call(`/jit/${e.key}/quarantine`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'elle karantina'})},()=>get('/jit?limit=25',setJit))}>KARANTİNA</button>}
                      <button style={bStyle} disabled={busy} onClick={()=>call(`/jit/${e.key}`,{method:'DELETE'},()=>get('/jit?limit=25',setJit))}>SİL</button>
                    </span>
                    {e.quarantined && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>karantinada: {e.quarantine_reason}</div>}
                    {e.stale && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>eski sürüm — yeniden derlenecek</div>}
                  </div>
                ))}
              </>}
            </div>
          )}

          {/* ─── MASAUSTU (uiautomation / pywinauto) ─────────── */}
          {sub==='desktop' && (
            <div>
              {!desk && <div style={label}>yükleniyor…</div>}
              {desk && desk.available===false && <div style={{...row}}>⚠ {desk.error||'masaüstü modülü yok'}</div>}
              {desk && desk.available!==false && <>
                {/* IKI KATMAN: pencere yonetimi her zaman calisir (ctypes),
                    element bazli denetim paket ister. Ayrimi gostermek sart:
                    "neden tiklayamiyor" sorusunun cevabi bu. */}
                <div style={row}><div style={dot(desk.window_control)} />pencere yönetimi (listele/öne al/kapat): <b style={{color:'#ffffff'}}>{desk.window_control?'açık':'kapalı'}</b> <span style={{marginLeft:'auto',color:'#cccccc'}}>{desk.window_backend||'-'}</span></div>
                <div style={row}><div style={dot(desk.element_control)} />element bazlı denetim (buton/kutu): <b style={{color:'#ffffff'}}>{desk.element_control?'açık':'kapalı'}</b> <span style={{marginLeft:'auto',color:'#cccccc'}}>{desk.element_backend||'-'}</span></div>
                {(desk.backends||[]).map(b=>(
                  <div key={b.name} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(b.installed)} />
                    <span style={{color:b.installed?'#ddd':'#888'}}>{b.name}</span>
                    {b.element_level && <span style={{fontSize:11,color:'#d0d0d0'}}>· element</span>}
                    <span style={{marginLeft:'auto',color:'#cccccc',fontSize:11}}>{b.installed?'kurulu':b.reason}</span>
                    <div style={{flexBasis:'100%',color:'#cccccc',fontSize:11}}>{b.note}</div>
                  </div>
                ))}
                {desk.install_hint && <div style={{...label,color:'#e0e0e0'}}>kurulum: {desk.install_hint}</div>}
                {desk.note && <div style={{...label,lineHeight:1.5}}>{desk.note}</div>}
                {desk.mobile && <div style={{...label,lineHeight:1.5}}>{desk.mobile}</div>}
                {/* ─── TASK 1: TEST DESKTOP CONTROL ─── */}
                <div style={{padding:'10px',background:'rgba(255,255,255,0.04)',border:'1px solid rgba(255,255,255,0.14)',borderRadius:8,marginTop:8}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                    <span style={{fontSize:13,fontWeight:700,color:'#fff',fontFamily:'monospace'}}>MASAÜSTÜ TESTİ (COMPUTER USE)</span>
                    <button
                      style={{
                        padding:'6px 14px',
                        background: deskTesting ? 'rgba(255,255,255,0.1)' : '#ffffff',
                        color: deskTesting ? '#aaa' : '#000',
                        fontWeight: 700,
                        border:'none',
                        borderRadius:6,
                        fontSize:13,
                        fontFamily:'monospace',
                        cursor: deskTesting ? 'not-allowed' : 'pointer',
                        boxShadow: deskTesting ? 'none' : '0 0 10px rgba(255,255,255,0.2)'
                      }}
                      disabled={deskTesting}
                      onClick={runDesktopTest}
                    >
                      {deskTesting ? 'TEST ÇALIŞIYOR...' : '▶ TEST DESKTOP CONTROL'}
                    </button>
                  </div>
                  <div style={{fontSize:12,color:'#d0d0d0',lineHeight:1.4}}>
                    Not Defteri'ni açar, "Hello from ALES" yazar ve çalıştığını doğrulamak için anlık ekran görüntüsü alır.
                  </div>
                  {deskTestResult && (
                    <div style={{marginTop:8,padding:'8px',background:'rgba(0,0,0,0.5)',borderRadius:6,border:'1px solid rgba(255,255,255,0.1)'}}>
                      <div style={{fontSize:13,color:deskTestResult.ok ? '#4ade80' : '#f87171',fontFamily:'monospace',marginBottom:6}}>
                        {deskTestResult.ok ? '✓ ' + deskTestResult.message : '✗ ' + deskTestResult.error}
                      </div>
                      {deskTestResult.screenshot && (
                        <div style={{marginTop:6}}>
                          <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',marginBottom:4}}>ALINAN EKRAN GÖRÜNTÜSÜ:</div>
                          <img
                            src={`data:image/png;base64,${deskTestResult.screenshot}`}
                            alt="Desktop Test Screenshot"
                            style={{maxWidth:'100%',borderRadius:6,border:'1px solid rgba(255,255,255,0.2)'}}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div style={{display:'flex',gap:5,marginTop:8}}>
                  <button style={{...bStyle,flex:1}} disabled={busy} onClick={async()=>{
                    const d = await get('/desktop/windows', ()=>{})
                    if (d) { setDesk(p=>({...p, _windows:d.windows||[], _fg:d.foreground})) ; flash(`${(d.windows||[]).length} pencere`) }
                  }}>PENCERELERİ LİSTELE</button>
                </div>
                {desk._fg?.title && <div style={{...label,marginTop:6}}>ön planda: {desk._fg.title}</div>}
                {(desk._windows||[]).slice(0,25).map(w=>(
                  <div key={w.hwnd} style={row}>
                    <div style={dot(!w.minimized)} />
                    <span style={{flex:1,overflow:'hidden',textOverflow:'ellipsis',color:w.foreground?'#fff':'#ccc'}}>{w.title||'(başlıksız)'}</span>
                    <span style={{color:'#cccccc',fontSize:11}}>{w.minimized?'simge':''}</span>
                    <button style={bStyle} disabled={busy}
                      onClick={()=>call('/desktop/focus',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:w.title})})}>ÖNE AL</button>
                  </div>
                ))}
                <div style={{...label,marginTop:8}}>PENCEREDEKİ ÖĞELERİ İNCELE</div>
                <div style={{display:'flex',gap:5}}>
                  <input style={iStyle} value={deskTitle} onChange={e=>setDeskTitle(e.target.value)} placeholder="pencere başlığı (kısmi eşleşir)" />
                  <button style={bStyle} disabled={busy||!deskTitle.trim()} onClick={async()=>{
                    const d = await get(`/desktop/controls?title=${encodeURIComponent(deskTitle)}&depth=4`, ()=>{})
                    setDesk(p=>({...p, _controls: d?.text || d?.error || 'sonuç yok'}))
                  }}>İNCELE</button>
                </div>
                {desk._controls && <pre style={{...pre,marginTop:5}}>{desk._controls}</pre>}
              </>}
            </div>
          )}

          {/* ─── HIZ (Faz 2): toplu sevkiyat · spec-cache · DEPO · öngörü ─── */}
          {sub==='hiz' && (
            <div>
              {/* DURUSTLUK: bu sayilar OLCULMUS degerlerdir. Makalelerin
                  "4x hizlanma / -%60 token" gibi rakamlari BU kurulumda
                  olculmedigi icin hicbir yerde gosterilmiyor. */}
              <div style={{...label,marginBottom:7,lineHeight:1.5}}>
                Aşağıdaki sayılar bu bilgisayarda gerçekten ölçülen değerlerdir.
                Makalelerdeki hızlanma oranları burada gösterilmez — bu kurulumda
                ölçülmediler.
              </div>
              <button style={{...bStyle,width:'100%',marginBottom:7}} disabled={busy}
                onClick={()=>getMulti({batch:'/batch-inference/stats',spec:'/spec-cache/stats',depo:'/token-optimizer/stats',pred:'/predictive/stats',jitg:'/jit/graphs'},setSpd)}>YENİLE</button>
              {!spd && <div style={label}>yükleniyor…</div>}
              {spd && <>
                {/* ── JIT CIZGE: karisik turlarda paralellestirme ──────
                    Bu bolum, "cizge katmani yazildi ama calisiyor mu"
                    sorusunun tek durust cevabi. compiled=0 ise katman hic
                    devreye girmemis demektir ve bunu SAKLAMIYORUZ. */}
                <div style={label}>JIT ÇİZGE — karışık turda bağımsız çağrıları aynı anda çalıştırır</div>
                {off(spd.jitg) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot((spd.jitg.executed??0)>0)} />
                    {spd.jitg.compiled??0} çizge derlendi · {spd.jitg.executed??0} çalıştı · {spd.jitg.nodes_run??0} düğüm / {spd.jitg.layers??0} katman</div>
                  <div style={row}><div style={dot((spd.jitg.nodes_per_layer??1)>1)} />
                    {spd.jitg.nodes_per_layer==null
                      ? 'katman başına düğüm: henüz ölçülmedi (hiç çizge çalışmadı)'
                      : `katman başına ${spd.jitg.nodes_per_layer} düğüm${spd.jitg.nodes_per_layer>1?' — paralelleşme var':' — hiçbir şey paralelleşmedi'}`}
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>{spd.jitg.active?'açık':'kapalı'}</span></div>
                  <div style={{...label,color:'#cccccc'}}>{spd.jitg.note}</div>
                  {(spd.jitg.graphs||[]).slice(0,3).map(g=>(
                    <div key={g.graph_id} style={row}><div style={dot(g.finished)} />
                      <span style={{color:'#d0d0d0'}}>{g.graph_id}</span>
                      <span style={{marginLeft:6}}>{g.node_count} düğüm · {Object.values(g.nodes||{}).map(n=>n.tool).join(' → ')}</span></div>
                  ))}
                </>}

                <div style={{...label,marginTop:8}}>TOPLU ÇIKARIM (CONCUR) — yan etkisiz istekleri tek partide gönderir</div>
                {off(spd.batch) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot((spd.batch.batches_executed??0)>0)} />
                    {spd.batch.batches_executed??0} parti · {spd.batch.items_batched??0} istek toplandı · ortalama {spd.batch.avg_batch_size??0} istek/parti</div>
                  <div style={row}><div style={dot(false)} />
                    {spd.batch.direct_executions??0} doğrudan gönderildi (yan etkili — toplanmaz) · şu an kuyrukta {spd.batch.queued_now??0}
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>{spd.batch.window_ms}ms pencere · en çok {spd.batch.batch_size}</span></div>
                </>}

                <div style={{...label,marginTop:8}}>SPEC-CACHE — aynı isteğin cevabını ve ortak ön-eki yeniden kullanır</div>
                {off(spd.spec) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot((spd.spec.hits??0)>0)} />
                    {spd.spec.entries??0}/{spd.spec.max_entries} kayıt · isabet %{Math.round((spd.spec.hit_rate||0)*100)} ({spd.spec.hits??0} isabet / {spd.spec.misses??0} ıska)</div>
                  {/* KV ön-ek satırı BİLİNÇLİ olarak "token kazanıldı"
                      DEMİYOR. Ölçtüğümüz şey: aynı sistem ön-ekinin kaç kez
                      görüldüğü ve kaç token'lık sabit metin olduğu. Gerçek
                      prefill tasarrufu sağlayıcının kendi prompt cache'inde
                      olur (Groq/Gemini/Cerebras HTTP API'sinde bize bunu
                      söyleyen bir alan yok), bizim sayacımızda değil. */}
                  <div style={row}><div style={dot((spd.spec.kv_prefix_hits??0)>0)} />
                    KV ön-ek: {spd.spec.kv_entries??0} kayıt · aynı ön-ek {spd.spec.kv_prefix_hits??0} kez görüldü · ~{spd.spec.kv_tokens_saved??0} token sabit metin</div>
                  <div style={row}><div style={dot((spd.spec.speculative_hits??0)>0)} />
                    tahminli: {spd.spec.speculative_prefetches??0} ön-getirme → {spd.spec.speculative_hits??0} işe yaradı
                    <span style={{marginLeft:'auto',display:'flex',gap:4}}>
                      <button style={bStyle} disabled={busy} onClick={()=>call('/spec-cache/clear',{method:'POST'},()=>getMulti({batch:'/batch-inference/stats',spec:'/spec-cache/stats',depo:'/token-optimizer/stats',pred:'/predictive/stats',jitg:'/jit/graphs'},setSpd))}>TEMİZLE</button>
                    </span></div>
                </>}

                <div style={{...label,marginTop:8}}>DEPO — istemi kısaltır (araç sonuçlarını ve eski turları budar)</div>
                {off(spd.depo) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot((spd.depo.prompts_optimized??0)>0)} />
                    {spd.depo.prompts_optimized??0} istem kısaltıldı · ~{spd.depo.tokens_saved_approx??0} token düşürüldü · ortalama %{spd.depo.avg_reduction_percent??0}</div>
                  <div style={row}><div style={dot(false)} />
                    {spd.depo.redundant_turns_pruned??0} gereksiz tur budandı · {spd.depo.messages_shrunk??0} mesaj küçültüldü
                    <span style={{marginLeft:'auto'}}>
                      <button style={bStyle} disabled={busy} onClick={()=>call('/token-optimizer/reset',{method:'POST'},()=>getMulti({batch:'/batch-inference/stats',spec:'/spec-cache/stats',depo:'/token-optimizer/stats',pred:'/predictive/stats',jitg:'/jit/graphs'},setSpd))}>SAYAÇ SIFIRLA</button>
                    </span></div>
                </>}

                <div style={{...label,marginTop:8}}>ÖNGÖRÜLÜ ÖN-YÜKLEME — sıradaki SALT-OKUNUR çağrıyı şimdiden başlatır</div>
                {off(spd.pred) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot((spd.pred.hits??0)>0)} />
                    {spd.pred.scheduled??0} ön-getirme başlatıldı → {spd.pred.hits??0} işe yaradı (%{Math.round((spd.pred.hit_rate||0)*100)}) · ~{spd.pred.saved_s??0}s kazanç</div>
                  <div style={row}><div style={dot(false)} />
                    {spd.pred.pairs_learned??0} öğrenilmiş sıra ({spd.pred.pairs_tracked??0} izleniyor) · {spd.pred.expired??0} zaman aşımı · {spd.pred.skipped_unsafe??0} güvenli olmadığı için atlandı</div>
                  {/* KAPI ACIKLAMASI: kullanici "neden her arac on-getirilmiyor"
                      diye sorabilir; cevabi burada yaziyor. */}
                  <div style={{...label,color:'#cccccc'}}>
                    yalnızca izin listesindeki salt-okunur araçlar ön-getirilir; ekranı/dosyayı değiştiren hiçbir araç ön-getirilmez
                    <span style={{marginLeft:6}}>
                      <button style={bStyle} disabled={busy} onClick={()=>call('/predictive/clear',{method:'POST'},()=>getMulti({batch:'/batch-inference/stats',spec:'/spec-cache/stats',depo:'/token-optimizer/stats',pred:'/predictive/stats',jitg:'/jit/graphs'},setSpd))}>ÖNBELLEĞİ TEMİZLE</button>
                    </span>
                  </div>
                </>}
              </>}
            </div>
          )}

          {/* ─── ZEKA (Faz 3): MoA/DMoA · CER · Reflexion/SAGE ───── */}
          {sub==='zeka' && (
            <div>
              <button style={{...bStyle,width:'100%',marginBottom:7}} disabled={busy}
                onClick={()=>getMulti({moa:'/moa/stats',cer:'/cer/stats',cerList:'/cer/experiences?limit=12',refl:'/reflection/stats'},setIq)}>YENİLE</button>
              {!iq && <div style={label}>yükleniyor…</div>}
              {iq && <>
                <div style={label}>MoA / DMoA — aynı soru birkaç modele sorulur, yanıtlar sentezlenir</div>
                {off(iq.moa) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot((iq.moa.moa_runs??0)>0)} />
                    {iq.moa.moa_runs??0} tur · {iq.moa.proposals_generated??0} öneri · {iq.moa.synthesized_answers??0} sentez · ortalama {iq.moa.avg_elapsed_s??0}s</div>
                  <div style={row}><div style={dot((iq.moa.dmoa_balanced??0)>0)} />
                    {iq.moa.dmoa_balanced??0} kez dinamik (DMoA) — soruya göre önerici sayısı ayarlandı</div>
                  {/* MALIYET UYARISI: bu bir "bedava zeka" degil. */}
                  <div style={{...label,color:'#cccccc'}}>her tur 4-5 model isteğidir; yalnızca Multi modunda ve araç gerektirmeyen sorularda devreye girer</div>
                </>}

                <div style={{...label,marginTop:8}}>DENEYİM TEKRARI (CER) — eğitim yok, geçmiş yörünge isteme eklenir</div>
                {off(iq.cer) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot((iq.cer.total_experiences??0)>0)} />
                    {iq.cer.total_experiences??0}/{iq.cer.max_experiences} deneyim · {iq.cer.successes??0} başarılı yörünge · {iq.cer.reflections??0} yansıma</div>
                  <div style={row}><div style={dot((iq.cer.replays_injected??0)>0)} />
                    {iq.cer.replays_injected??0} kez isteme eklendi</div>
                  {(iq.cerList?.experiences||[]).map((e,i)=>(
                    <div key={i} style={{...row,flexWrap:'wrap'}}>
                      <div style={dot(e.success)} />
                      <span style={{color:'#ffffff',flex:1,overflow:'hidden',textOverflow:'ellipsis'}}>{e.task||'(görev yok)'}</span>
                      <span style={{color:'#cccccc'}}>{e.success?'başarılı':'başarısız'} · {(e.trajectory||[]).length} adım</span>
                    </div>
                  ))}
                </>}

                <div style={{...label,marginTop:8}}>ÖZ-YANSIMA (Reflexion / RetroAct / SAGE) — hatadan ders çıkarır</div>
                {off(iq.refl) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot((iq.refl.reflections_triggered??0)>0)} />
                    {iq.refl.reflections_triggered??0} yansıma · {iq.refl.corrections_successful??0} düzeltme işe yaradı</div>
                  <div style={row}><div style={dot((iq.refl.sage_triads_run??0)>0)} />
                    {iq.refl.sage_triads_run??0} SAGE üçlüsü · {iq.refl.checker_catches??0} denetçi yakalaması</div>
                  {/* YALNIZCA "stratejik ders" bolumu kural olur — kullanici
                      neden her hatadan kural cikmadigini gormeli. */}
                  <div style={{...label,color:'#cccccc'}}>her hata kural üretmez: yalnızca yanıtın "stratejik ders" bölümü kalıcı ilkeye dönüşür</div>
                </>}
              </>}
            </div>
          )}

          {/* ─── EVRİM (Faz 6): SE-Agent/MUSE/RSI · Darwin Gödel ─── */}
          {sub==='evrim' && (
            <div>
              {/* KAPSAM METNI: "kendi kodunu degistirir" iddiasi YOK. */}
              <div style={{...label,marginBottom:7,lineHeight:1.5}}>
                Öğrenilen şey METİNDİR — sistem istemine eklenen ilke ve tarif.
                ALES kendi kaynak kodunu değiştirmez, model ağırlığı eğitmez.
              </div>
              <button style={{...bStyle,width:'100%',marginBottom:7}} disabled={busy}
                onClick={()=>getMulti({se:'/self-evolution/stats',dgm:'/darwin-godel/stats',trial:'/darwin-godel/trial'},setEvo)}>YENİLE</button>
              {!evo && <div style={label}>yükleniyor…</div>}
              {evo && <>
                <div style={label}>SE-AGENT + MUSE — yörünge sadeleştirme ve hiyerarşik bellek</div>
                {off(evo.se) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot((evo.se.strategic_rules??0)>0)} />
                    {evo.se.strategic_rules??0} stratejik ilke · {evo.se.procedural_recipes??0} prosedürel tarif</div>
                  <div style={row}><div style={dot((evo.se.trajectories_optimized??0)>0)} />
                    {evo.se.trajectories_optimized??0} yörünge sadeleştirildi · {evo.se.loops_pruned??0} tekrar/döngü ayıklandı</div>
                  <div style={row}><div style={dot((evo.se.rsi_cycles??0)>0)} />
                    {evo.se.rsi_cycles??0} RSI döngüsü · {evo.se.agent0_verifications??0} Agent0 öz-doğrulaması
                    <span style={{marginLeft:'auto'}}>
                      <button style={bStyle} disabled={busy} onClick={()=>call('/self-evolution/rsi',{method:'POST'},()=>getMulti({se:'/self-evolution/stats',dgm:'/darwin-godel/stats',trial:'/darwin-godel/trial'},setEvo))}>RSI DÖNGÜSÜ ÇALIŞTIR</button>
                    </span></div>
                </>}

                <div style={{...label,marginTop:8}}>DARWIN GÖDEL — iskele stratejileri A/B denenir, kanıtlanan şampiyon olur</div>
                {off(evo.dgm) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot((evo.dgm.generation??0)>0)} />
                    nesil {evo.dgm.generation??0} · arşivde {evo.dgm.archive_count??0} iskele ({evo.dgm.proven_count??0} kanıtlanmış) · {evo.dgm.promotions??0} terfi / {evo.dgm.rejections??0} ret</div>
                  {/* ŞAMPİYON + ADAY: fitness null ise SAYI YAZILMAZ.
                      Eski surumde panel kanit olmadan 0.99 gosteriyordu. */}
                  {evo.trial?.trial?.champion && <div style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(true)} />şampiyon: <b style={{color:'#ffffff'}}>{evo.trial.trial.champion.name}</b>
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>
                      {evo.trial.trial.champion.fitness!=null
                        ? `uyum ${evo.trial.trial.champion.fitness}`
                        : `henüz ölçülmedi (${evo.trial.trial.champion.trials??0}/${evo.trial.trial.min_trials} deneme)`}
                    </span>
                  </div>}
                  {evo.trial?.trial?.challenger ? <>
                    <div style={{...row,flexWrap:'wrap'}}>
                      <div style={dot(false)} />aday: <b style={{color:'#ffffff'}}>{evo.trial.trial.challenger.name}</b>
                      <span style={{marginLeft:'auto',color:'#cccccc'}}>
                        {evo.trial.trial.challenger.trials??0}/{evo.trial.trial.challenger.needed??evo.trial.trial.min_trials} deneme
                        {evo.trial.trial.challenger.fitness!=null
                          ? ` · uyum ${evo.trial.trial.challenger.fitness}`
                          : ' · uyum henüz ölçülmedi'}
                      </span>
                    </div>
                    {/* ILERLEME CUBUGU: deneme sayisi / gereken deneme.
                        Bu bir UYUM cubugu DEGIL — kanit birikimini gosterir. */}
                    <div style={{height:4,background:'rgba(255,255,255,0.07)',borderRadius:3,overflow:'hidden',marginBottom:4}}>
                      <div style={{height:'100%',width:`${Math.min(100,Math.round(100*(evo.trial.trial.challenger.trials||0)/Math.max(1,evo.trial.trial.challenger.needed||evo.trial.trial.min_trials||1)))}%`,background:'rgba(255,255,255,0.5)'}} />
                    </div>
                  </> : <div style={{...label,color:'#cccccc'}}>şu an denenen aday yok</div>}
                  <div style={row}><div style={dot(!!evo.trial?.loop_running)} />
                    otomatik evrim döngüsü: <b style={{color:'#ffffff'}}>{evo.trial?.loop_running?'ÇALIŞIYOR':'DURDU'}</b>
                    {evo.trial?.evolve_interval_minutes!=null && <span style={{color:'#cccccc'}}>· {evo.trial.evolve_interval_minutes} dk</span>}
                    <span style={{marginLeft:'auto'}}>
                      <button style={bStyle} disabled={busy} onClick={()=>call('/darwin-godel/evolve',{method:'POST'},()=>getMulti({se:'/self-evolution/stats',dgm:'/darwin-godel/stats',trial:'/darwin-godel/trial'},setEvo))}>ŞİMDİ BİR NESİL ÜRET</button>
                    </span></div>
                  {evo.trial?.active_strategy && <pre style={pre}>{typeof evo.trial.active_strategy==='string'?evo.trial.active_strategy:JSON.stringify(evo.trial.active_strategy,null,1)}</pre>}
                </>}
              </>}
            </div>
          )}

          {/* ─── KONTROL (Faz 4): OpenClaw köprüsü · OSWorld eylem uzayı ─── */}
          {sub==='kontrol' && (
            <div>
              <button style={{...bStyle,width:'100%',marginBottom:7}} disabled={busy}
                onClick={()=>getMulti({claw:'/openclaw/status',cua:'/evocua/status'},setCtrl)}>YENİLE</button>
              {!ctrl && <div style={label}>yükleniyor…</div>}
              {ctrl && <>
                <div style={label}>OPENCLAW KÖPRÜSÜ — harici daemon yoksa yerel yedeklere düşer</div>
                {off(ctrl.claw) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot(!!ctrl.claw.daemon_connected)} />
                    daemon: <b style={{color:'#ffffff'}}>{ctrl.claw.daemon_connected?'BAĞLI':'YOK'}</b>
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>{ctrl.claw.openclaw_url}</span></div>
                  {/* EN ONEMLI SATIR: daemon yokken de is YAPILIR. Kullanici
                      "BAGLI degil" gorup yeteneği kayip sanmasin. */}
                  {ctrl.claw.fallback_active && <div style={{...row,borderColor:'rgba(255,255,255,0.2)'}}>
                    ⚠ daemon yok — masaüstü/tarayıcı/komut işleri <b style={{color:'#ffffff'}}>yerel yedeklerle yine çalışır</b> (uiautomation · playwright · kabuk)
                  </div>}
                  <div style={row}><div style={dot((ctrl.claw.stats?.openclaw_calls??0)>0)} />
                    {ctrl.claw.stats?.desktop_actions??0} masaüstü · {ctrl.claw.stats?.browser_actions??0} tarayıcı · {ctrl.claw.stats?.terminal_actions??0} komut · {ctrl.claw.stats?.fallback_to_native??0} yedeğe düşme</div>
                </>}

                <div style={{...label,marginTop:8}}>OSWORLD / WAA EYLEM UZAYI — 0-1000 normalize koordinat → piksel</div>
                {off(ctrl.cua) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot(true)} />
                    {ctrl.cua.role} · {ctrl.cua.executor} · ekran {ctrl.cua.screen_resolution}</div>
                  <div style={row}><div style={dot((ctrl.cua.stats?.actions_executed??0)>0)} />
                    {ctrl.cua.stats?.actions_executed??0} eylem · {ctrl.cua.stats?.grounded_clicks??0} tık/sürükle · {ctrl.cua.stats?.typed_characters??0} karakter · {ctrl.cua.stats?.hotkeys_pressed??0} kısayol</div>
                  {/* KUM HAVUZU: ACIKKEN hicbir eylem ekrana dokunmaz.
                      Bu daha once YANLIS calisiyordu (docstring simule
                      diyordu, kod gercekten tikliyordu) — duzeltildi. */}
                  <div style={row}><div style={dot(!ctrl.cua.sandbox_mode)} />
                    kum havuzu: <b style={{color:'#ffffff'}}>{ctrl.cua.sandbox_mode?'AÇIK — eylemler SİMÜLE edilir, ekrana dokunulmaz':'KAPALI — eylemler gerçekten icra edilir'}</b>
                    <span style={{marginLeft:'auto'}}>
                      <button style={bStyle} disabled={busy}
                        onClick={()=>call('/evocua/sandbox',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!ctrl.cua.sandbox_mode})},()=>getMulti({claw:'/openclaw/status',cua:'/evocua/status'},setCtrl))}>
                        {ctrl.cua.sandbox_mode?'KUM HAVUZUNU KAPAT':'KUM HAVUZUNU AÇ'}
                      </button>
                    </span></div>
                  {(ctrl.cua.stats?.sandboxed_blocked??0)>0 && <div style={{...label,color:'#cccccc'}}>{ctrl.cua.stats.sandboxed_blocked} eylem kum havuzunda simüle edildi (icra edilmedi)</div>}
                  <div style={{...label,color:'#cccccc'}}>desteklenen eylemler: {(ctrl.cua.action_space||[]).join(' · ')}</div>
                  {/* SKOR IDDIASI YOK: kiyaslama rakamlari o modellere ait. */}
                  <div style={{...label,color:'#cccccc',lineHeight:1.5}}>
                    bu köprü bir model barındırmaz — eylemleri yönlendirici (router) modelleri üretir.
                    EvoCUA/InAgent kıyaslama skorları o modellere aittir, bu köprüye değil.
                    {ctrl.cua.cua_model_endpoint ? ` Yerel uç: ${ctrl.cua.cua_model_endpoint}` : ' Yerel bir CUA ucu tanımlı değil.'}
                  </div>
                </>}
              </>}
            </div>
          )}

          {/* ─── SAĞLIK (Faz 5): dinamik zaman aşımı · sürüm · keşif ─── */}
          {sub==='saglik' && (
            <div>
              <button style={{...bStyle,width:'100%',marginBottom:7}} disabled={busy}
                onClick={()=>getMulti({to:'/adaptive-timeouts/stats',vers:'/config-versions?limit=15',env:'/env-status',disc:'/auto-discovery/status'},setHlt)}>YENİLE</button>
              {!hlt && <div style={label}>yükleniyor…</div>}
              {hlt && <>
                {/* EN BASA KOYULDU: bir sey calismiyorsa ilk bakilacak yer
                    burasidir. "Anahtar yok" hatasi, sanki model bozukmus
                    gibi gorunen arizalarin en sik sebebi. */}
                <div style={label}>ANAHTAR KAYNAĞI (.env + config.json)</div>
                {off(hlt.env) ? <div style={row}>alınamadı</div> : <>
                  <div style={row}><div style={dot(!!hlt.env.loaded)} />
                    .env: <b style={{color:'#ffffff'}}>{hlt.env.loaded?`okundu · ${hlt.env.count} değişken`:'bulunamadı'}</b>
                    {hlt.env.path && <span style={{marginLeft:'auto',color:'#cccccc',overflow:'hidden',textOverflow:'ellipsis'}}>{hlt.env.path}</span>}</div>
                  {!hlt.env.loaded && <div style={{...label,color:'#cccccc',lineHeight:1.5}}>
                    şu yollara bakıldı — dosyayı bunlardan birine koy:
                    {(hlt.env.searched||[]).map((p,i)=><div key={i} style={{color:'#d0d0d0'}}>· {p}</div>)}
                  </div>}
                  <div style={{...row,flexWrap:'wrap',gap:6}}>
                    <div style={dot((hlt.env.keys_ok_count??0)>0)} />
                    <span>{hlt.env.keys_ok_count??0}/7 anahtar çözülebiliyor</span>
                    <span style={{marginLeft:'auto',display:'flex',gap:6,flexWrap:'wrap'}}>
                      {Object.entries(hlt.env.keys_resolved||{}).map(([k,v])=>(
                        <span key={k} style={{color:v?'#ddd':'#555'}}>{v?'✓':'✗'} {k.replace('_key','')}</span>
                      ))}
                    </span>
                  </div>
                  {/* DEGER GOSTERMIYORUZ: yalnizca var/yok. */}
                  <div style={{...label,color:'#cccccc'}}>anahtar değerleri ve değişken adları burada gösterilmez — yalnızca var/yok. config.json'daki değer .env'i geçer; .env ise elle tanımlanmış bir ortam değişkenini ezmez</div>
                </>}

                <div style={{...label,marginTop:8}}>DİNAMİK ZAMAN AŞIMI — ölçülen gecikmeye göre ayarlanır, sabit değer yok</div>
                {off(hlt.to) ? <div style={row}>modül yok</div>
                  : Object.keys(hlt.to||{}).length===0
                    ? <div style={{...label,color:'#cccccc'}}>henüz ölçüm yok — ilk isteklerden sonra dolar</div>
                    : Object.entries(hlt.to).map(([k,v])=>(
                        <div key={k} style={row}>
                          <div style={dot((v.samples??0)>0)} />
                          <span style={{color:'#ffffff',flex:1}}>{k}</span>
                          <span style={{color:'#cccccc'}}>ort {v.avg_s}s ±{v.std_s} · sınır {v.dynamic_timeout_s}s · {v.samples} örnek · %{Math.round((v.success_rate||0)*100)} başarı</span>
                        </div>
                      ))}
                {!off(hlt.to) && Object.keys(hlt.to||{}).length>0 && <button style={{...bStyle,width:'100%',marginTop:4}} disabled={busy}
                  onClick={()=>call('/adaptive-timeouts/reset',{method:'POST'},()=>getMulti({to:'/adaptive-timeouts/stats',vers:'/config-versions?limit=15',env:'/env-status',disc:'/auto-discovery/status'},setHlt))}>ÖLÇÜMLERİ SIFIRLA</button>}

                <div style={{...label,marginTop:8}}>YAPILANDIRMA SÜRÜMLERİ — anında geri alma</div>
                {/* GUVENLIK NOTU: API anahtarlari surumlerde SAKLANMIYOR,
                    bu yuzden geri alma anahtarlari EZMEZ. Kullanici bunu
                    bilmeden geri almaya cekinir. */}
                <div style={{...label,color:'#cccccc'}}>API anahtarları sürümlerde saklanmaz — geri alma çalışan anahtarlara dokunmaz</div>
                {(hlt.vers?.versions||[]).length===0 && <div style={{...label,color:'#cccccc'}}>kayıtlı sürüm yok</div>}
                {(hlt.vers?.versions||[]).map(v=>(
                  <div key={v.version_id} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(true)} />
                    <span style={{color:'#ffffff',flex:1,overflow:'hidden',textOverflow:'ellipsis'}}>{v.time_str||v.version_id} · {v.category}</span>
                    <span style={{color:'#cccccc'}}>{v.keys_count} anahtar</span>
                    <button style={bStyle} disabled={busy}
                      onClick={()=>call(`/config-versions/rollback/${v.version_id}`,{method:'POST'},()=>getMulti({to:'/adaptive-timeouts/stats',vers:'/config-versions?limit=15',env:'/env-status',disc:'/auto-discovery/status'},setHlt))}>GERİ AL</button>
                    {v.reason && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{v.reason}</div>}
                  </div>
                ))}

                <div style={{...label,marginTop:8}}>MODEL UZLAŞTIRMA — yapılandırılan katmanları sağlayıcı kataloğuyla karşılaştırır</div>
                {off(hlt.disc) ? <div style={row}>modül yok</div> : <>
                  <div style={row}><div style={dot(!!hlt.disc.active)} />
                    döngü: <b style={{color:'#ffffff'}}>{hlt.disc.active?'ÇALIŞIYOR':'DURDU'}</b>
                    <span style={{marginLeft:'auto',color:'#cccccc'}}>{hlt.disc.reconcile_interval_minutes} dk · katalog: {hlt.disc.catalog_scanner}</span></div>
                  <div style={row}><div style={dot((hlt.disc.stats?.reconciles_completed??0)>0)} />
                    {hlt.disc.stats?.reconciles_completed??0} tur · {hlt.disc.stats?.models_discovered??0} model katalogda · {hlt.disc.stats?.deprecated_detected??0} kaldırılmış tespiti ({hlt.disc.stats?.alternatives_suggested??0} öneri)</div>
                  {/* EN KRITIK CUMLE: tespit ETMEK, kapatmak DEGILDIR.
                      Katalogda gorunmemek modelin olu oldugunu kanitlamaz. */}
                  <div style={{...row,borderColor:'rgba(255,255,255,0.2)'}}>
                    ⚠ tespitler yalnızca <b style={{color:'#ffffff'}}>rapordur</b> — hiçbir katman otomatik kapatılmaz veya değiştirilmez, çağrı yine denenir
                  </div>
                  <div style={{...label,color:'#cccccc'}}>son tarama: {hlt.disc.last_scan_time} · son uzlaştırma: {hlt.disc.last_reconcile_time}</div>
                  <button style={{...bStyle,width:'100%',marginTop:4}} disabled={busy}
                    onClick={()=>call('/auto-discovery/run',{method:'POST'},()=>getMulti({to:'/adaptive-timeouts/stats',vers:'/config-versions?limit=15',env:'/env-status',disc:'/auto-discovery/status'},setHlt))}>ŞİMDİ TARA (katalogları zorla yenile)</button>
                </>}
              </>}
            </div>
          )}

          {/* ─── TESHIS: 9 MODUL + DENETCI + VEKTOR HAFIZA ───── */}
          {sub==='diag' && (
            <div>
              <div style={{display:'flex',gap:5,marginBottom:7}}>
                <button style={{...bStyle,flex:1}} disabled={busy} onClick={()=>{get('/diagnostics',setDiag);get('/selfheal/status',setHeal);get('/memory/long/vector',setVec)}}>YENİLE</button>
              </div>
              {!diag && <div style={label}>yükleniyor…</div>}
              {diag?._offline && <div style={label}>teşhis alınamadı — sunucu kapalı olabilir</div>}
              {diag && !diag._offline && <>
                <div style={label}>MODÜLLER</div>
                {Object.entries(diag.modules||{}).map(([k,v])=>(
                  <div key={k} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(v.loaded && v.available && !v.paused)} />
                    <b style={{color:'#ffffff'}}>{k}</b>
                    <span style={{marginLeft:'auto',color:'#d0d0d0'}}>
                      {!v.loaded ? 'yüklenemedi' : v.paused ? 'duraklatıldı' : v.available ? 'hazır' : 'eksik bağımlılık'}
                    </span>
                    {v.error && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{v.error}</div>}
                    {v.info?.note && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{v.info.note}</div>}
                    {v.info?.reason && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>{v.info.reason}</div>}
                  </div>
                ))}
              </>}

              <div style={{...label,marginTop:8}}>KENDİNİ TOPARLAMA (denetçi)</div>
              {heal?._offline && <div style={label}>denetçi durumu alınamadı</div>}
              {heal && heal.unavailable && <div style={label}>self_heal modülü yüklenemedi</div>}
              {heal && !heal._offline && !heal.unavailable && <>
                {/* SINIRLARI ACIKCA GOSTER: bu panelin "kendini yeniden yazan
                    yapay zeka" olmadigini kullanici gorebilmeli. */}
                <div style={{...label,lineHeight:1.5,color:'#d0d0d0'}}>{heal.policy}</div>
                {(heal.supervisors||[]).flatMap(s=>s.workers||[]).map(w=>(
                  <div key={w.name} style={{...row,flexWrap:'wrap'}}>
                    <div style={dot(w.alive)} />
                    <b style={{color:'#ffffff'}}>{w.name}</b>
                    {w.critical && <span style={{fontSize:11,color:'#d0d0d0'}}>kritik</span>}
                    <span style={{marginLeft:'auto',color:'#d0d0d0'}}>
                      {w.given_up ? 'vazgeçildi' : w.alive ? 'çalışıyor' : 'durdu'}
                      {w.restarts_in_window>0 && ` · ${w.restarts_in_window}/${w.max_restarts} yeniden başlatma`}
                    </span>
                    {w.last_error && <div style={{flexBasis:'100%',color:'#d0d0d0',fontSize:11}}>son hata: {w.last_error}</div>}
                    {(!w.alive || w.given_up) && <button style={{...bStyle,marginTop:3}} disabled={busy}
                      onClick={()=>call(`/selfheal/restart/${w.name}?force=true`,{method:'POST'},()=>get('/selfheal/status',setHeal))}>YENİDEN BAŞLAT</button>}
                  </div>
                ))}
                {(heal.checkpoints||[]).length>0 && <div style={label}>kurtarma noktaları: {(heal.checkpoints||[]).join(', ')}</div>}
                {(heal.incidents||[]).slice(0,6).map((it,i)=>(
                  <div key={i} style={{...label,color:'#d0d0d0'}}>· {it.kind||it.type||'olay'} {it.name?`(${it.name})`:''} {it.error?`— ${String(it.error).slice(0,90)}`:''}</div>
                ))}
                <div style={{display:'flex',gap:5,marginTop:5}}>
                  <button style={bStyle} disabled={busy} onClick={()=>call('/selfheal/incidents',{method:'DELETE'},()=>get('/selfheal/status',setHeal))}>OLAY GEÇMİŞİNİ TEMİZLE</button>
                </div>
              </>}

              <div style={{...label,marginTop:8}}>VEKTÖR HAFIZA (sqlite-vec)</div>
              {vec?._offline && <div style={label}>vektör hafıza durumu alınamadı</div>}
              {vec && vec.unavailable && <div style={label}>uzun hafıza modülü yok</div>}
              {vec && !vec._offline && !vec.unavailable && <>
                <div style={row}><div style={dot(vec.extension_loaded)} />
                  sqlite-vec: {vec.extension_loaded?'yüklü':'yüklü değil — Python kosinüs yolu kullanılıyor'}</div>
                <div style={row}><div style={dot((vec.indexed||0)>0)} />{vec.indexed||0}/{vec.memories||0} anı indekste</div>
                {/* needs_rebuild: eklenti SONRADAN kuruldu -> eski anilar
                    indekste degil. Yarim indeks sessizce yanlis KNN verir. */}
                {vec.needs_rebuild && <div style={{...row,borderColor:'rgba(255,255,255,0.2)'}}>⚠ indeks eksik — aşağıdan yeniden kur</div>}
                <button style={{...bStyle,width:'100%',marginTop:4}} disabled={busy}
                  onClick={()=>call('/memory/long/vector/rebuild',{method:'POST'},()=>get('/memory/long/vector',setVec))}>İNDEKSİ YENİDEN KUR</button>
              </>}

              <div style={{...label,marginTop:8}}>ÖNGÖRÜLÜ ÖN-YÜKLEME</div>
              <button style={{...bStyle,width:'100%'}} disabled={busy} onClick={async()=>{
                const d = await get('/predictive/stats', ()=>{})
                flash(d ? `isabet ${d.hits??0}/${(d.hits??0)+(d.misses??0)} · ${d.active?'aktif':'pasif'}${d.unavailable?' (modül yok)':''}` : 'alınamadı')
              }}>DURUMU GÖSTER</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── KALICI SISTEM PROMPTU (LUBV) ─────────────────────────────────
// Metin system_prompts.json'da durur (AppData kopyasi repo kopyasini
// golgeler) ve backend her konusmada sistem promptunun BASINA ekler —
// meclis yolu dahil. Bu panel onu duzenlenebilir yapar; dosyayi elle
// acmak gerekmez.
// GUVENLIK: buraya sifre/API key/mahrem bilgi YAZILMAZ. Metin her istekte
// saglayiciya gonderilir; kasa (Credential Manager) icin asagidaki KASA
// sekmesi vardir.
// ACIK/KAPALI ayrimi bilincli: metni kaydetmek onu ETKINLESTIRMEZ. Yarim
// yapistirilmis bir yonergenin sessizce her konusmaya girmesini istemiyoruz.
function SystemPromptPanel() {
  const [sp, setSp] = useState(null)      // {enabled, text, chars, active}
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [open, setOpen] = useState(false)

  const load = () => authFetch(API_URL+'/system-prompt').then(r=>r.json())
    .then(d=>{ setSp(d); setDraft(d.text||'') })
    // Istek duserse panel YOK OLMAMALI — kullanicinin LUBV metnini
    // yapistiracagi yer burasi; gorunmezse "ozellik yok" sanilir.
    .catch(()=>setSp({enabled:false, text:'', chars:0, active:false, offline:true}))
  useEffect(() => { load() }, [])

  const post = async (body) => {
    setBusy(true)
    try {
      const r = await authFetch(API_URL+'/system-prompt', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      const d = await r.json()
      if (d.ok) { setSp(d); if (body.text!==undefined) setDraft(d.text||''); setSaved(true); setTimeout(()=>setSaved(false),1300) }
    } catch(e) {}
    setBusy(false)
  }

  if (!sp) return null
  const dirty = draft !== (sp.text||'')
  const bStyle = {padding:'8px 14px',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.28)',borderRadius:6,color:'#ffffff',fontSize:12,fontWeight:600,cursor:busy?'default':'pointer',fontFamily:'monospace',opacity:busy?0.5:1}

  return (
    <div style={{marginTop:14,paddingTop:12,borderTop:'1px solid rgba(255,255,255,0.12)'}}>
      <button onClick={()=>setOpen(o=>!o)} style={{background:'none',border:'none',color:'#ffffff',fontSize:12,fontWeight:700,fontFamily:'monospace',letterSpacing:2,cursor:'pointer',padding:'4px 0'}}>
        {open?'▾':'▸'} KALICI SİSTEM PROMPTU {sp.active ? '· AKTİF' : (sp.text ? '· KAPALI' : '· BOŞ')}
      </button>
      {open && (
        <div style={{marginTop:10}}>
          <div style={{fontSize:12,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.6,marginBottom:10}}>
            Bu metin HER konuşmada sistem promptunun başına eklenir (Meclis modu dahil).
            Kaydetmek etkinleştirmez — metni gözden geçirip ETKİNLEŞTİR'e basın.
            Buraya şifre/API key yazmayın: metin her istekte modele gider.
          </div>
          <textarea value={draft} onChange={e=>setDraft(e.target.value)} rows={8}
            placeholder="LUBV metnini buraya yapıştırın..."
            style={{background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:7,padding:'10px 12px',color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none',width:'100%',resize:'vertical',lineHeight:1.5,boxSizing:'border-box'}} />
          <div style={{display:'flex',gap:8,alignItems:'center',marginTop:8,flexWrap:'wrap'}}>
            <button disabled={busy||!dirty} onClick={()=>post({text:draft})} style={{...bStyle,opacity:(busy||!dirty)?0.4:1}}>
              {saved?'✓ KAYDEDİLDİ':'METNİ KAYDET'}
            </button>
            <button disabled={busy||!draft.trim()} onClick={()=>post({text:dirty?draft:undefined, enabled:!sp.enabled})}
              style={{...bStyle,opacity:(busy||!draft.trim())?0.4:1,borderColor:sp.enabled?'#ffffff':'rgba(255,255,255,0.3)'}}>
              {sp.enabled?'DEVRE DIŞI BIRAK':'ETKİNLEŞTİR'}
            </button>
            <span style={{fontSize:11,color:'#cccccc',fontFamily:'monospace'}}>
              {draft.length} karakter{dirty?' · KAYDEDİLMEDİ':''}
            </span>
          </div>
          {!sp.text && (
            <div style={{fontSize:12,color:'#fca5a5',fontFamily:'monospace',marginTop:8,lineHeight:1.5}}>
              {sp.offline
                ? 'Backend\'e ulaşılamadı — kaydetmek şu an çalışmaz.'
                : 'Şu an BOŞ — hiçbir şey enjekte edilmiyor (tam no-op). Metin girilene kadar davranış değişmez.'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── KASA / PROFILLER / DAYANIKLILIK / HAFIZA ────────────────────
// Dort modul backend'de vardi ama arayuz yuzu YOKTU:
//   credentials     — sirlar OS kasasinda (Windows Credential Manager)
//   browser_profiles— izole tarayici profilleri (GOREV sekmesi yalnizca
//                     SECIYORDU; olusturma/silme/cerez temizleme yoktu)
//   retry_util      — hic cagrilmayan olu import; artik LTM embedding'inde
//                     kullaniliyor ve sayaclari burada gorunuyor
//   long_term_memory— /memory/long ucu vardi ama hicbir yerden cagrilmiyordu;
//                     embedding uzayi uyari alanlari da gorunmuyordu
// Veriler panel acilisinda BIR KEZ cekilir. /browser-profiles profil
// dizinlerini rglob'layip boyut topladigi icin ASLA periyodik cekilmez.
function VaultPanel() {
  const [tab, setTab] = useState('vault')   // 'vault' | 'profiles' | 'retry' | 'ltm'
  const [open, setOpen] = useState(false)
  const [audit, setAudit] = useState(null)
  const [profiles, setProfiles] = useState([])
  const [pdir, setPdir] = useState('')
  const [rstats, setRstats] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [secret, setSecret] = useState({name:'', value:''})
  const [np, setNp] = useState({id:'', label:'', note:''})
  const [ltm, setLtm] = useState(null)
  const [batch, setBatch] = useState(null)
  const [lq, setLq] = useState('')
  const [lres, setLres] = useState(null)
  const [lnote, setLnote] = useState('')

  const loadAudit = () => authFetch(API_URL+'/credentials/audit').then(r=>r.json()).then(setAudit).catch(()=>{})
  const loadProfiles = () => authFetch(API_URL+'/browser-profiles').then(r=>r.json())
    .then(d=>{ setProfiles(d.profiles||[]); setPdir(d.dir||'') }).catch(()=>{})
  const loadRetry = () => authFetch(API_URL+'/retry/stats').then(r=>r.json()).then(setRstats).catch(()=>{})
  const loadLtm = () => {
    authFetch(API_URL+'/memory/long').then(r=>r.json()).then(setLtm).catch(()=>{})
    authFetch(API_URL+'/batch/stats').then(r=>r.json()).then(setBatch).catch(()=>{})
  }

  useEffect(() => { if (open) { loadAudit(); loadProfiles(); loadRetry(); loadLtm() } }, [open])

  const flash = (t) => { setMsg(t); setTimeout(()=>setMsg(''), 2600) }
  const call = async (url, opts, after) => {
    setBusy(true)
    try {
      const r = await authFetch(API_URL+url, opts)
      const d = await r.json()
      if (after) after(d)
      return d
    } catch(e) { flash('istek basarisiz'); return null }
    finally { setBusy(false) }
  }

  const migrate = () => call('/credentials/migrate', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}, d=>{
    flash(d.ok ? `${(d.migrated||[]).length} key tasindi${(d.failed||[]).length?` · ${d.failed.length} basarisiz`:''}`
               : (d.error||'tasima basarisiz'))
    loadAudit()
  })
  const saveSecret = () => {
    if (!secret.name.trim() || !secret.value.trim()) return
    call('/credentials/set', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:secret.name.trim(), value:secret.value})}, d=>{
      flash(d.ok ? `'${secret.name.trim()}' kasaya yazildi` : 'kasaya yazilamadi')
      setSecret({name:'', value:''}); loadAudit()
    })
  }
  const delSecret = (name) => call(`/credentials/${encodeURIComponent(name)}`, {method:'DELETE'}, d=>{
    flash(d.ok ? `'${name}' kasadan silindi` : 'silinemedi'); loadAudit()
  })
  const createProfile = () => {
    if (!np.id.trim()) return
    call('/browser-profiles', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(np)}, d=>{
      flash(d.ok===false ? (d.error||'olusturulamadi') : `profil '${np.id.trim()}' olusturuldu`)
      setNp({id:'', label:'', note:''}); loadProfiles()
    })
  }
  const clearProfile = (pid) => call(`/browser-profiles/${encodeURIComponent(pid)}/clear`, {method:'POST'}, d=>{
    flash(d.ok===false ? (d.error||'temizlenemedi') : `'${pid}' cerez/depolama verisi silindi`); loadProfiles()
  })
  const delProfile = (pid) => call(`/browser-profiles/${encodeURIComponent(pid)}?wipe=true`, {method:'DELETE'}, d=>{
    flash(d.ok===false ? (d.error||'silinemedi') : `profil '${pid}' silindi`); loadProfiles()
  })
  const ltmSearch = () => {
    if (!lq.trim()) { setLres(null); return }
    call(`/memory/long?q=${encodeURIComponent(lq.trim())}&k=8`, {}, d=>{
      setLres(d.results||[]); if (d.stats) setLtm(d)
    })
  }
  const ltmAdd = () => {
    if (!lnote.trim()) return
    call('/memory/long', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:lnote.trim(), kind:'note', source:'ui', importance:1.0})}, d=>{
      flash(d.ok ? (d.record?.reinforced ? 'zaten vardi -> pekistirildi' : 'kalici hafizaya eklendi') : (d.error||'eklenemedi'))
      if (d.ok) { setLnote(''); if (d.stats) setLtm(p=>({...(p||{}), stats:d.stats})) }
    })
  }
  const ltmForget = () => call('/memory/long/forget', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}, d=>{
    flash(d.ok ? `${d.forgotten} bayat kayit silindi` : (d.error||'temizlenemedi'))
    if (d.stats) setLtm(p=>({...(p||{}), stats:d.stats}))
  })

  const iStyle = {background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:6,padding:'8px 10px',color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none',width:'100%',boxSizing:'border-box'}
  const bStyle = {padding:'7px 12px',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.28)',borderRadius:6,color:'#ffffff',fontSize:12,fontWeight:600,cursor:busy?'default':'pointer',fontFamily:'monospace',opacity:busy?0.5:1,whiteSpace:'nowrap'}
  const tabStyle = (a) => ({flex:1,padding:'8px 6px',background:a?'rgba(255,255,255,0.22)':'rgba(255,255,255,0.06)',border:'1px solid '+(a?'#ffffff':'rgba(255,255,255,0.2)'),borderRadius:6,color:a?'#ffffff':'#cccccc',fontSize:11,fontWeight:a?700:500,cursor:'pointer',fontFamily:'monospace',letterSpacing:0.5})

  return (
    <div style={{marginTop:14,paddingTop:12,borderTop:'1px solid rgba(255,255,255,0.12)'}}>
      <button onClick={()=>setOpen(o=>!o)} style={{background:'none',border:'none',color:'#ffffff',fontSize:12,fontWeight:700,fontFamily:'monospace',letterSpacing:2,cursor:'pointer',padding:'4px 0'}}>
        {open?'▾':'▸'} KASA · PROFİLLER · DAYANIKLILIK · HAFIZA
      </button>
      {!open && (
        <div style={{fontSize:11,color:'#cccccc',fontFamily:'monospace',marginTop:5}}>
          API key kasası, izole tarayıcı profilleri, yeniden deneme sayaçları ve
          uzun-süreli hafıza.
        </div>
      )}
      {open && (
        <div style={{marginTop:8}}>
          <div style={{display:'flex',gap:6,marginBottom:8}}>
            <button style={tabStyle(tab==='vault')} onClick={()=>setTab('vault')}>KASA</button>
            <button style={tabStyle(tab==='profiles')} onClick={()=>setTab('profiles')}>PROFILLER ({profiles.length})</button>
            <button style={tabStyle(tab==='retry')} onClick={()=>setTab('retry')}>DAYANIKLILIK</button>
            <button style={tabStyle(tab==='ltm')} onClick={()=>setTab('ltm')}>HAFIZA</button>
          </div>
          {msg && <div style={{fontSize:12,color:'#9c9',fontFamily:'monospace',marginBottom:8}}>{msg}</div>}

          {/* ── KASA ── */}
          {tab==='vault' && (
            <div>
              <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.6,marginBottom:8}}>
                Sirlar isletim sisteminin kasasinda tutulur (Windows'ta Credential
                Manager, DPAPI ile kullanici hesabina bagli). config.json'da DUZ METIN
                duran key varsa asagida gorunur — TASI'ya basmak onlari kasaya alip
                dosyadan siler. Dosyada bir kez duz metin durduysa yedeklerde kopyasi
                kalmis olabilir: tasima sonrasi key'leri saglayici panelinden
                YENILEMENIZ onerilir.
              </div>
              {audit ? (
                <div>
                  <div style={{fontSize:12,fontFamily:'monospace',color:audit.vault_available?'#9c9':'#c99',marginBottom:8}}>
                    Kasa: {audit.vault_available?'KULLANILABILIR':'KULLANILAMIYOR'} · {audit.backend}
                    {!audit.vault_available && ' — sirlar config.json/ortam degiskeninden okunur'}
                  </div>
                  <div style={{display:'flex',flexDirection:'column',gap:3,marginBottom:8}}>
                    {(audit.findings||[]).map(f=>(
                      <div key={f.key} style={{display:'flex',alignItems:'center',gap:8,padding:'5px 0',borderBottom:'1px solid rgba(255,255,255,0.05)'}}>
                        <span style={{flex:1,fontSize:12,color:'#ffffff',fontFamily:'monospace'}}>{f.key}</span>
                        {f.in_config_plaintext && <span style={{fontSize:11,color:'#e88',fontFamily:'monospace'}}>config'te DUZ METIN {f.preview}</span>}
                        <span style={{fontSize:11,color:f.in_vault?'#9c9':'#555',fontFamily:'monospace'}}>{f.in_vault?'kasada':'kasada yok'}</span>
                        {f.in_vault && <button disabled={busy} onClick={()=>delSecret(f.key)} style={{...bStyle,padding:'2px 7px',fontSize:11}}>SIL</button>}
                      </div>
                    ))}
                  </div>
                  <button disabled={busy||!audit.vault_available||!audit.exposed_count} onClick={migrate}
                    style={{...bStyle,width:'100%',opacity:(busy||!audit.vault_available||!audit.exposed_count)?0.4:1}}>
                    {audit.exposed_count ? `${audit.exposed_count} DUZ METIN KEY'I KASAYA TASI` : 'TASINACAK DUZ METIN KEY YOK'}
                  </button>
                  <div style={{marginTop:10,paddingTop:8,borderTop:'1px solid rgba(255,255,255,0.06)'}}>
                    <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',marginBottom:5}}>ELLE SIR EKLE / GUNCELLE</div>
                    <div style={{display:'flex',gap:5}}>
                      <input style={{...iStyle,flex:1}} placeholder="ad (or. groq_key)" value={secret.name} onChange={e=>setSecret(p=>({...p,name:e.target.value}))} />
                      <input style={{...iStyle,flex:1}} type="password" placeholder="deger" value={secret.value} onChange={e=>setSecret(p=>({...p,value:e.target.value}))} />
                      <button disabled={busy||!audit.vault_available} onClick={saveSecret} style={bStyle}>YAZ</button>
                    </div>
                  </div>
                </div>
              ) : <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace'}}>yukleniyor...</div>}
            </div>
          )}

          {/* ── PROFILLER ── */}
          {tab==='profiles' && (
            <div>
              <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.6,marginBottom:8}}>
                Her profil kendi cerez/oturum deposunu tutar — testler birbirine
                karismaz. Profil sifreleri profiles.json'a ASLA yazilmaz, kasaya
                gider. TEMIZLE cerez/depolama verisini siler ("her yerden cikis");
                SIL profili tumuyle kaldirir.
                {pdir && <><br/>Dizin: {pdir}</>}
              </div>
              <div style={{display:'flex',flexDirection:'column',gap:4,marginBottom:8}}>
                {profiles.length===0 && <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace'}}>Kayitli profil yok.</div>}
                {profiles.map(p=>(
                  <div key={p.id} style={{display:'flex',alignItems:'center',gap:7,padding:'6px 0',borderBottom:'1px solid rgba(255,255,255,0.05)'}}>
                    <div style={{flex:1,minWidth:0}}>
                      <div style={{fontSize:13,color:'#e8e8e8',fontFamily:'monospace',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{p.label||p.id}</div>
                      <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace'}}>{p.id}{p.note?` · ${p.note}`:''}</div>
                    </div>
                    <span style={{fontSize:11,color:p.exists?'#888':'#555',fontFamily:'monospace'}}>{p.exists?`${p.size_mb} MB`:'bos'}</span>
                    <button disabled={busy} onClick={()=>clearProfile(p.id)} style={{...bStyle,padding:'2px 7px',fontSize:11}}>TEMIZLE</button>
                    <button disabled={busy} onClick={()=>delProfile(p.id)} style={{...bStyle,padding:'2px 7px',fontSize:11}}>SIL</button>
                  </div>
                ))}
              </div>
              <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',marginBottom:5}}>YENI PROFIL</div>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:5,marginBottom:5}}>
                <input style={iStyle} placeholder="id (or. test1)" value={np.id} onChange={e=>setNp(p=>({...p,id:e.target.value}))} />
                <input style={iStyle} placeholder="etiket (istege bagli)" value={np.label} onChange={e=>setNp(p=>({...p,label:e.target.value}))} />
              </div>
              <div style={{display:'flex',gap:5}}>
                <input style={{...iStyle,flex:1}} placeholder="not (istege bagli)" value={np.note} onChange={e=>setNp(p=>({...p,note:e.target.value}))} />
                <button disabled={busy||!np.id.trim()} onClick={createProfile} style={{...bStyle,opacity:(busy||!np.id.trim())?0.4:1}}>OLUSTUR</button>
              </div>
            </div>
          )}

          {/* ── DAYANIKLILIK ── */}
          {tab==='retry' && (
            <div>
              <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.6,marginBottom:8}}>
                Gecici hatalar (429/503/ag kopmasi) ussel geri-alimla yeniden denenir.
                "kurtarilan" = ilk denemede patlayip sonraki denemede basarili olan
                cagri sayisi. Sayaclar surec icinde tutulur, ALES kapaninca sifirlanir.
              </div>
              {rstats ? (
                <div>
                  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:5,marginBottom:8}}>
                    {[['cagri',rstats.calls],['yeniden deneme',rstats.retries],
                      ['kurtarilan',rstats.recovered],['pes edilen',rstats.failed],
                      ['beklenen sure',`${rstats.slept_s}s`]].map(([l,v])=>(
                      <div key={l} style={{background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.07)',borderRadius:6,padding:'6px 8px'}}>
                        <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace'}}>{l}</div>
                        <div style={{fontSize:12,color:'#e8e8e8',fontFamily:'monospace'}}>{v}</div>
                      </div>
                    ))}
                  </div>
                  {(rstats.by_label||[]).length>0 && (
                    <div style={{marginBottom:8}}>
                      {(rstats.by_label||[]).map(s=>(
                        <div key={s.label} style={{display:'flex',gap:8,fontSize:11,color:'#e0e0e0',fontFamily:'monospace',padding:'3px 0',borderBottom:'1px solid rgba(255,255,255,0.04)'}}>
                          <span style={{flex:1}}>{s.label}</span>
                          <span>{s.calls} cagri</span><span>{s.retries} deneme</span>
                          <span>{s.recovered} kurtarildi</span><span>{s.failed} pes</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {rstats.last && (
                    <div style={{fontSize:11,color:'#a99',fontFamily:'monospace',marginBottom:8}}>
                      Son: {rstats.last.label} · deneme {rstats.last.attempt} · {rstats.last.error_type} · {rstats.last.delay_s}s beklendi
                    </div>
                  )}
                  <div style={{display:'flex',gap:5}}>
                    <button disabled={busy} onClick={loadRetry} style={{...bStyle,flex:1}}>YENILE</button>
                    <button disabled={busy} onClick={()=>call('/retry/stats/reset',{method:'POST'},d=>{setRstats(d); flash('sayaclar sifirlandi')})} style={{...bStyle,flex:1}}>SIFIRLA</button>
                  </div>
                </div>
              ) : <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace'}}>yukleniyor...</div>}
            </div>
          )}
          {/* ── HAFIZA (uzun sureli + toplu kuyruk) ── */}
          {tab==='ltm' && (
            <div>
              <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',lineHeight:1.6,marginBottom:8}}>
                Kalici uzun-sureli hafiza: tek bir SQLite dosyasi, vektor benzerligi +
                Ebbinghaus unutma egrisi. Hatirlanan kayit GUCLENIR, hatirlanmayan
                zamanla zayiflar. "Bayatlari temizle" yalnizca zayif VE onemsiz
                (importance &lt; 3) kayitlari siler.
              </div>
              {ltm && ltm.available===false && (
                <div style={{fontSize:12,color:'#c99',fontFamily:'monospace'}}>
                  long_term_memory yuklenemedi — {ltm.error||'modul yok'}
                </div>
              )}
              {ltm && ltm.stats && (
                <div>
                  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:5,marginBottom:8}}>
                    {[['kayit',ltm.stats.total],
                      ['embedding uzayi',ltm.stats.embedding],
                      ['sqlite-vec',ltm.stats.vec_extension?'acik':'kapali (Python kosinus)'],
                      ['tur sayisi',Object.keys(ltm.stats.by_kind||{}).length]].map(([l,v])=>(
                      <div key={l} style={{background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.07)',borderRadius:6,padding:'6px 8px'}}>
                        <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace'}}>{l}</div>
                        <div style={{fontSize:11,color:'#e8e8e8',fontFamily:'monospace'}}>{String(v)}</div>
                      </div>
                    ))}
                  </div>
                  {/* Bu iki uyari item-1 duzeltmesinin GORUNUR yuzu: eskiden
                      sessizce olan seyi artik soyluyor. */}
                  {ltm.stats.gemini_down && (
                    <div style={{fontSize:11,color:'#ca9',fontFamily:'monospace',marginBottom:6,lineHeight:1.5}}>
                      Gemini embedding bu oturumda dustu -&gt; yerel 256-boyutlu
                      embedder'a gecildi (kilitli). Uzayin surec ortasinda degismesini
                      onlemek icin bilincli: yeniden denemek karisik veritabani yaratirdi.
                    </div>
                  )}
                  {ltm.stats.mixed_dims && (
                    <div style={{fontSize:11,color:'#e99',fontFamily:'monospace',marginBottom:6,lineHeight:1.5}}>
                      KARISIK VERITABANI: kayitlar iki farkli embedding uzayinda
                      ({Object.entries(ltm.stats.dims||{}).map(([d,c])=>`${d} boyut: ${c}`).join(' · ')}).
                      Kosinus yalnizca ayni uzayda anlamlidir; azinlikta kalan kayitlar
                      hatirlanamaz. Bu, duzeltmeden ONCE yazilmis kayitlarin izidir —
                      istersen onlari silip yeniden ekleyerek tek uzaya indirebilirsin.
                    </div>
                  )}
                  <div style={{display:'flex',gap:5,marginBottom:6}}>
                    <input style={{...iStyle,flex:1}} placeholder="hafizada ara (anlamsal)..." value={lq}
                      onChange={e=>setLq(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')ltmSearch()}} />
                    <button disabled={busy} onClick={ltmSearch} style={bStyle}>ARA</button>
                  </div>
                  {lres && (
                    <div style={{marginBottom:8}}>
                      {lres.length===0 && <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace'}}>Eslesme yok.</div>}
                      {lres.map(m=>(
                        <div key={m.id} style={{padding:'5px 0',borderBottom:'1px solid rgba(255,255,255,0.05)'}}>
                          <div style={{fontSize:12,color:'#ffffff',fontFamily:'monospace',lineHeight:1.5}}>{m.text}</div>
                          <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace'}}>
                            skor {m.score} · benzerlik {m.similarity} · {m.kind} · {m.access_count}x hatirlandi
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div style={{display:'flex',gap:5,marginBottom:6}}>
                    <input style={{...iStyle,flex:1}} placeholder="kalici not ekle..." value={lnote}
                      onChange={e=>setLnote(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')ltmAdd()}} />
                    <button disabled={busy||!lnote.trim()} onClick={ltmAdd} style={{...bStyle,opacity:(busy||!lnote.trim())?0.4:1}}>EKLE</button>
                  </div>
                  <div style={{display:'flex',gap:5}}>
                    <button disabled={busy} onClick={loadLtm} style={{...bStyle,flex:1}}>YENILE</button>
                    <button disabled={busy} onClick={ltmForget} style={{...bStyle,flex:1}}>BAYATLARI TEMIZLE</button>
                  </div>
                  {batch && batch.available && (
                    <div style={{fontSize:11,color:'#d0d0d0',fontFamily:'monospace',marginTop:8,lineHeight:1.5}}>
                      Toplu kuyruk: {batch.stats?.batches||0} yigin · {batch.stats?.items||0} istek ·
                      {' '}{batch.stats?.saved_calls||0} cagri tasarruf edildi · {batch.pending} bekliyor
                    </div>
                  )}
                </div>
              )}
              {!ltm && <div style={{fontSize:12,color:'#cccccc',fontFamily:'monospace'}}>yukleniyor...</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SkillsConnectorsPanel() {
  const [tab, setTab] = useState('skills') // 'skills' | 'connectors'
  const [skills, setSkills] = useState([])
  const [conns, setConns] = useState([])
  const [showAddSkill, setShowAddSkill] = useState(false)
  const [newSkill, setNewSkill] = useState({ id: '', md: '', py: '' })
  const [showAddConn, setShowAddConn] = useState(false)
  const [newConn, setNewConn] = useState({ id: '', name: '', base_url: '', description: '' })
  const [keyDrafts, setKeyDrafts] = useState({}) // connector_id -> taslak api key

  const loadSkills = () => authFetch(API_URL+'/skills').then(r=>r.json()).then(d=>setSkills(d.skills||[])).catch(()=>{})
  const loadConns = () => authFetch(API_URL+'/connectors').then(r=>r.json()).then(d=>setConns(d.connectors||[])).catch(()=>{})

  useEffect(() => { loadSkills(); loadConns() }, [])

  const iStyle = {background:'#1e1e1e',border:'1px solid rgba(255,255,255,0.25)',borderRadius:7,padding:'8px 12px',color:'#ffffff',fontSize:13,fontFamily:'monospace',outline:'none',width:'100%',boxSizing:'border-box'}
  const btnStyle = {padding:'7px 12px',background:'rgba(255,255,255,0.12)',border:'1px solid rgba(255,255,255,0.28)',borderRadius:6,color:'#ffffff',fontSize:12,fontWeight:600,cursor:'pointer',fontFamily:'monospace'}
  const tabStyle = (active) => ({flex:1,padding:'8px 6px',background:active?'rgba(255,255,255,0.22)':'rgba(255,255,255,0.06)',border:'1px solid '+(active?'#ffffff':'rgba(255,255,255,0.2)'),borderRadius:6,color:active?'#ffffff':'#cccccc',fontSize:11,fontWeight:active?700:500,cursor:'pointer',fontFamily:'monospace',letterSpacing:0.5})

  const toggleSkill = async (id, enabled) => {
    await authFetch(API_URL+`/skills/${id}/toggle`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})})
    loadSkills()
  }
  const removeSkill = async (id) => { await authFetch(API_URL+`/skills/${id}`, {method:'DELETE'}); loadSkills() }
  const installSkill = async () => {
    if (!newSkill.id.trim() || !newSkill.md.trim()) return
    await authFetch(API_URL+'/skills/install', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({skill_id:newSkill.id.trim(), skill_md:newSkill.md, skill_py:newSkill.py})})
    setNewSkill({ id:'', md:'', py:'' }); setShowAddSkill(false); loadSkills()
  }

  const saveConnKey = async (id) => {
    await authFetch(API_URL+`/connectors/${id}/configure`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:(keyDrafts[id]||'').trim(), enabled:true})})
    setKeyDrafts(p=>({...p,[id]:''})); loadConns()
  }
  const toggleConn = async (id, enabled) => {
    await authFetch(API_URL+`/connectors/${id}/configure`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})})
    loadConns()
  }
  const removeConn = async (id) => { await authFetch(API_URL+`/connectors/${id}`, {method:'DELETE'}); loadConns() }
  const installConn = async () => {
    if (!newConn.id.trim() || !newConn.base_url.trim()) return
    await authFetch(API_URL+'/connectors/install', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(newConn)})
    setNewConn({ id:'', name:'', base_url:'', description:'' }); setShowAddConn(false); loadConns()
  }

  return (
    <div style={{marginTop:14,paddingTop:12,borderTop:'1px solid rgba(255,255,255,0.08)'}}>
      <div style={{fontSize:13,fontWeight:700,color:'#ffffff',fontFamily:'monospace',letterSpacing:2,marginBottom:10}}>SKILLS & CONNECTORS</div>
      <div style={{display:'flex',gap:6,marginBottom:8}}>
        <button style={tabStyle(tab==='skills')} onClick={()=>setTab('skills')}>SKILLS ({skills.length})</button>
        <button style={tabStyle(tab==='connectors')} onClick={()=>setTab('connectors')}>CONNECTORS ({conns.length})</button>
      </div>

      {tab === 'skills' && (
        <div>
          <div style={{fontSize:12,color:'#cccccc',marginBottom:8,lineHeight:1.5}}>
            Yeni bir yetenek: SKILL.md (aciklama) + skill.py (kod) ile ALES'e
            yeni bir arac kazandirir - Claude'a skill yukleme mantiginin ayni.
          </div>
          {skills.map(s => (
            <div key={s.id} style={{display:'flex',alignItems:'center',gap:8,padding:'6px 0',borderBottom:'1px solid rgba(255,255,255,0.05)'}}>
              <div style={{width:7,height:7,borderRadius:'50%',background:s.enabled?'#8f8':'#555',flexShrink:0}} />
              <div style={{flex:1,minWidth:0}}>
                <div style={{fontSize:13,color:'#ffffff',fontFamily:'monospace'}}>{s.name}</div>
                <div style={{fontSize:11,color:'#cccccc',fontFamily:'monospace',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{s.description}{s.load_error ? ' ⚠️ '+s.load_error : ''}</div>
              </div>
              <button style={btnStyle} onClick={()=>toggleSkill(s.id, !s.enabled)}>{s.enabled?'KAPAT':'AC'}</button>
              <button style={{...btnStyle,color:'#a55'}} onClick={()=>removeSkill(s.id)}>SIL</button>
            </div>
          ))}
          {!showAddSkill ? (
            <button style={{...btnStyle,width:'100%',marginTop:8}} onClick={()=>setShowAddSkill(true)}>+ YENI SKILL EKLE</button>
          ) : (
            <div style={{marginTop:8,display:'flex',flexDirection:'column',gap:6}}>
              <input style={iStyle} placeholder="skill id, örn: hava_widget" value={newSkill.id} onChange={e=>setNewSkill(p=>({...p,id:e.target.value}))} />
              <textarea style={{...iStyle,minHeight:70,resize:'vertical'}} placeholder={'SKILL.md içeriği (---\\nid: ...\\nname: ...\\ndescription: ...\\nkeywords: [..]\\nenabled: true\\n---\\naçıklama metni)'} value={newSkill.md} onChange={e=>setNewSkill(p=>({...p,md:e.target.value}))} />
              <textarea style={{...iStyle,minHeight:70,resize:'vertical'}} placeholder={'skill.py içeriği (opsiyonel - boş bırakılırsa sadece referans/döküman olur)\nSKILL_TOOLS = [...]\ndef run(tool_name, args, progress_cb=None): ...'} value={newSkill.py} onChange={e=>setNewSkill(p=>({...p,py:e.target.value}))} />
              <div style={{display:'flex',gap:6}}>
                <button style={{...btnStyle,flex:1,background:'#fff',color:'#000'}} onClick={installSkill}>KAYDET</button>
                <button style={{...btnStyle,flex:1}} onClick={()=>setShowAddSkill(false)}>IPTAL</button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'connectors' && (
        <div>
          <div style={{fontSize:12,color:'#cccccc',marginBottom:8,lineHeight:1.5}}>
            Bir connector'ı açmak için API key/token girip AÇ'a bas. Key girilene
            kadar hiçbir dış servise istek atılmaz.
          </div>
          {conns.map(c => (
            <div key={c.id} style={{padding:'7px 0',borderBottom:'1px solid rgba(255,255,255,0.05)'}}>
              <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:6}}>
                <div style={{width:7,height:7,borderRadius:'50%',background:c.enabled?'#8f8':'#555',flexShrink:0}} />
                <div style={{flex:1,fontSize:13,color:'#ffffff',fontFamily:'monospace'}}>{c.icon} {c.name}</div>
                {c.custom && <button style={{...btnStyle,color:'#a55'}} onClick={()=>removeConn(c.id)}>SIL</button>}
                <button style={btnStyle} onClick={()=>toggleConn(c.id, !c.enabled)} disabled={!c.has_key && !c.enabled}>{c.enabled?'KAPAT':'AC'}</button>
              </div>
              <div style={{fontSize:11,color:'#cccccc',fontFamily:'monospace',marginBottom:6}}>{c.description}</div>
              <div style={{display:'flex',gap:6}}>
                <input style={iStyle} type="password" placeholder={c.has_key ? 'key girilmiş - değiştirmek için yaz' : 'API key / token'} value={keyDrafts[c.id]||''} onChange={e=>setKeyDrafts(p=>({...p,[c.id]:e.target.value}))} />
                <button style={btnStyle} onClick={()=>saveConnKey(c.id)}>KAYDET</button>
              </div>
            </div>
          ))}
          {!showAddConn ? (
            <button style={{...btnStyle,width:'100%',marginTop:8}} onClick={()=>setShowAddConn(true)}>+ ÖZEL CONNECTOR EKLE</button>
          ) : (
            <div style={{marginTop:8,display:'flex',flexDirection:'column',gap:6}}>
              <input style={iStyle} placeholder="id, örn: myapi" value={newConn.id} onChange={e=>setNewConn(p=>({...p,id:e.target.value}))} />
              <input style={iStyle} placeholder="görünen isim" value={newConn.name} onChange={e=>setNewConn(p=>({...p,name:e.target.value}))} />
              <input style={iStyle} placeholder="base URL, örn: https://api.example.com" value={newConn.base_url} onChange={e=>setNewConn(p=>({...p,base_url:e.target.value}))} />
              <input style={iStyle} placeholder="açıklama (opsiyonel)" value={newConn.description} onChange={e=>setNewConn(p=>({...p,description:e.target.value}))} />
              <div style={{display:'flex',gap:6}}>
                <button style={{...btnStyle,flex:1,background:'#fff',color:'#000'}} onClick={installConn}>KAYDET</button>
                <button style={{...btnStyle,flex:1}} onClick={()=>setShowAddConn(false)}>IPTAL</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
