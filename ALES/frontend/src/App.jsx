import { useState, useEffect, useRef, useCallback } from 'react'

const isElectron = typeof window !== 'undefined' && window.ales?.isElectron
const isLocalDev = typeof window !== 'undefined' && window.location.port === '5173'
const isCloud = typeof window !== 'undefined' && window.location.protocol !== 'file:' && !isElectron && !isLocalDev
const backendHost = (typeof window !== 'undefined' && window.location.hostname) || 'localhost'
const API_URL = isCloud ? window.location.origin : `http://${backendHost}:8000`
const WS_URL = isCloud ? window.location.origin.replace(/^http/, 'ws') + '/ws' : `ws://${backendHost}:8000/ws`

const ACCESS_CODE_KEY = 'ales_access_code'
const CONV_STORAGE_KEY = 'ales_conversations_v2'

function authFetch(url, opts = {}) {
  return fetch(url, { ...opts, headers: { ...(opts.headers || {}) } })
}

// ─── LOGIN SCREEN ────────────────────────────────────────────────
function LoginScreen({ onAuthenticated }) {
  const [accessCode, setAccessCode] = useState('')
  const [registerMode, setRegisterMode] = useState(false)
  const [groqKey, setGroqKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e) => {
    e.preventDefault()
    const code = accessCode.trim()
    if (!code) { setError('Lütfen erişim kodunuzu girin.'); return }
    setLoading(true); setError('')
    try {
      if (registerMode) {
        const res = await authFetch(`${API_URL}/api/profile/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_code: code, keys: { groq_key: groqKey.trim(), gemini_key: geminiKey.trim() } })
        })
        const data = await res.json()
        if (data.ok || data.success) {
          localStorage.setItem(ACCESS_CODE_KEY, code)
          onAuthenticated({ access_code: code, name: data.name || `Profil_${code}` })
        } else { setError(data.error || 'Profil oluşturulamadı.') }
      } else {
        const res = await authFetch(`${API_URL}/api/profile/load`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_code: code })
        })
        const data = await res.json()
        if (res.ok && (data.success || data.ok)) {
          localStorage.setItem(ACCESS_CODE_KEY, code)
          onAuthenticated({ access_code: code, name: data.name || `Profil_${code}` })
        } else { setError(data.error || 'Geçersiz erişim kodu.') }
      }
    } catch { setError('Sunucuya bağlanılamadı.') }
    finally { setLoading(false) }
  }

  return (
    <div className="auth-wrapper">
      <form className="auth-card" onSubmit={handleLogin}>
        <div className="auth-brand">
          <div className="auth-logo">A</div>
          <div className="auth-title">ALES Code</div>
          <div className="auth-subtitle">
            {registerMode ? 'Yeni profil oluşturun.' : 'Erişim kodunuzla giriş yapın.'}
          </div>
        </div>
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          <div className="form-group">
            <label className="form-label">Erişim Kodu</label>
            <input type="password" className="input-field" placeholder="Erişim kodunuz..."
              value={accessCode} onChange={e => setAccessCode(e.target.value)} autoFocus />
          </div>
          {registerMode && (<>
            <div className="form-group">
              <label className="form-label">Groq API Key</label>
              <input type="password" className="input-field" placeholder="gsk_..."
                value={groqKey} onChange={e => setGroqKey(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Gemini API Key</label>
              <input type="password" className="input-field" placeholder="AIza..."
                value={geminiKey} onChange={e => setGeminiKey(e.target.value)} />
            </div>
          </>)}
        </div>
        {error && <div className="auth-error">{error}</div>}
        <button type="submit" className="btn btn-primary" disabled={loading || !accessCode.trim()} style={{width:'100%',padding:'11px 16px'}}>
          {loading ? 'Doğrulanıyor...' : registerMode ? 'Profil Oluştur' : 'Giriş Yap'}
        </button>
        <button type="button" className="auth-link" onClick={() => { setRegisterMode(!registerMode); setError('') }}>
          {registerMode ? '← Zaten erişim kodum var' : 'Yeni erişim kodu oluştur'}
        </button>
      </form>
    </div>
  )
}

// ─── PERMISSION MODAL ────────────────────────────────────────────
function PermissionModal({ command, onAllow, onDeny }) {
  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="modal-header">
          <div className="modal-title" style={{ color:'#fb923c' }}>⚠️ İzin Gerekli</div>
        </div>
        <div style={{ fontSize:13, color:'var(--text-secondary)', marginBottom:12 }}>
          ALES potansiyel olarak riskli bir terminal komutu çalıştırmak istiyor:
        </div>
        <div className="perm-command">{command}</div>
        <div style={{ display:'flex', gap:10, justifyContent:'flex-end', marginTop:16 }}>
          <button className="btn btn-secondary" onClick={onDeny}>🚫 Reddet</button>
          <button className="btn btn-primary" onClick={onAllow}>✅ İzin Ver</button>
        </div>
      </div>
    </div>
  )
}

// ─── SETTINGS MODAL ──────────────────────────────────────────────
function SettingsModal({ accessCode, onClose }) {
  const [keys, setKeys] = useState({ groq_key:'', gemini_key:'', openrouter_key:'', nvidia_key:'' })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const handleSave = async (e) => {
    e.preventDefault(); setSaving(true); setMsg('')
    try {
      const nonEmpty = {}
      Object.entries(keys).forEach(([k,v]) => { if (v.trim()) nonEmpty[k] = v.trim() })
      if (accessCode && Object.keys(nonEmpty).length > 0) {
        await authFetch(`${API_URL}/api/profile/save`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ access_code: accessCode, keys: nonEmpty })
        })
        await authFetch(`${API_URL}/config`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify(nonEmpty)
        })
      }
      setMsg('✅ Ayarlar kaydedildi.')
      setKeys({ groq_key:'', gemini_key:'', openrouter_key:'', nvidia_key:'' })
    } catch { setMsg('❌ Kaydetme hatası.') }
    finally { setSaving(false) }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={e => e.stopPropagation()} style={{ maxWidth:480 }}>
        <div className="modal-header">
          <div>
            <div className="modal-title">Ayarlar</div>
            <div style={{ fontSize:12, color:'var(--text-muted)', marginTop:2 }}>
              API anahtarları sunucu profilinizde şifreli saklanır.
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} style={{ padding:'6px 10px' }}>✕</button>
        </div>
        <form onSubmit={handleSave} style={{ display:'flex', flexDirection:'column', gap:12 }}>
          {[
            ['groq_key','Groq API Key','gsk_...'],
            ['gemini_key','Gemini API Key','AIza...'],
            ['openrouter_key','OpenRouter API Key','sk-or-...'],
            ['nvidia_key','NVIDIA API Key','nvapi-...'],
          ].map(([field,label,ph]) => (
            <div key={field} className="form-group">
              <label className="form-label">{label}</label>
              <input type="password" className="input-field" placeholder={`Yeni anahtar (${ph})`}
                value={keys[field]} onChange={e => setKeys(p => ({ ...p, [field]: e.target.value }))} />
            </div>
          ))}
          {msg && <div style={{ fontSize:12, color: msg.startsWith('✅') ? 'var(--success)' : 'var(--danger)', padding:'6px 10px', background: msg.startsWith('✅') ? 'rgba(34,197,94,.1)' : 'rgba(239,68,68,.1)', borderRadius:6 }}>{msg}</div>}
          <div style={{ display:'flex', justifyContent:'flex-end', gap:10, marginTop:6 }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Kapat</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? 'Kaydediliyor...' : 'Kaydet'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── TODO SIDEBAR ─────────────────────────────────────────────────
function TodoSidebar({ todos, onClose }) {
  const statusIcon = { pending:'○', in_progress:'◉', done:'✓' }
  const statusColor = { pending:'var(--text-muted)', in_progress:'#60a5fa', done:'var(--success)' }
  return (
    <div className="todo-panel">
      <div className="todo-header">
        <span>📋 Görev Listesi</span>
        <button className="btn btn-ghost" onClick={onClose} style={{ padding:'2px 8px', fontSize:12 }}>✕</button>
      </div>
      {todos.length === 0 ? (
        <div className="todo-empty">Henüz görev yok.<br/>Ajandan todo_write çağrısı bekleniyor.</div>
      ) : (
        <div className="todo-list">
          {todos.map(item => (
            <div key={item.id} className={`todo-item ${item.status}`}>
              <span className="todo-icon" style={{ color: statusColor[item.status] || 'var(--text-muted)' }}>
                {statusIcon[item.status] || '○'}
              </span>
              <span className="todo-text" style={{ textDecoration: item.status === 'done' ? 'line-through' : 'none', color: item.status === 'done' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                {item.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── CONSOLE STEP RENDERER ───────────────────────────────────────
function ConsoleStepList({ steps }) {
  if (!steps || steps.length === 0) return null
  return (
    <div className="console-stream">
      {steps.map((s, idx) => {
        switch (s.kind) {
          case 'thought':
            return (
              <div key={idx} className="console-line console-thought">
                <span className="console-icon">🧠</span>
                <span><b>Thinking:</b> {s.text}</span>
              </div>
            )
          case 'tool_call': {
            const name = s.tool
            const argStr = JSON.stringify(s.args || {})
            const short = argStr.length > 160 ? argStr.slice(0, 160) + '…' : argStr
            return (
              <div key={idx} className="console-line console-tool">
                <span className="console-icon">🛠️</span>
                <span><b>{name}</b>({short})</span>
              </div>
            )
          }
          case 'tool_result':
            return (
              <div key={idx} className="console-line console-obs">
                <span className="console-icon">👁️</span>
                <div style={{ flex:1 }}>
                  <div style={{ color:'#94a3b8', fontSize:11, marginBottom:4 }}>Observation · {s.tool}</div>
                  <pre className="console-output">{s.text}</pre>
                </div>
              </div>
            )
          case 'success':
            return (
              <div key={idx} className="console-line console-success">
                <span className="console-icon">✅</span>
                <span>{s.text || 'Görev tamamlandı.'}</span>
              </div>
            )
          case 'status':
            return (
              <div key={idx} className="console-line console-status">
                <span className="console-icon">ℹ️</span>
                <span>{s.text}</span>
              </div>
            )
          case 'denied':
            return (
              <div key={idx} className="console-line" style={{ color:'#f87171' }}>
                <span className="console-icon">🚫</span>
                <span>Reddedildi: <code>{s.text}</code></span>
              </div>
            )
          default: return null
        }
      })}
    </div>
  )
}

// ─── MAIN APP ────────────────────────────────────────────────────
export default function App() {
  const [authChecking, setAuthChecking] = useState(true)
  const [authUser, setAuthUser] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window !== 'undefined' ? window.innerWidth > 768 : true)
  const [tab, setTab] = useState('chat')
  const [showSettings, setShowSettings] = useState(false)
  const [showTodos, setShowTodos] = useState(false)

  const [conversations, setConversations] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CONV_STORAGE_KEY) || '[]')
      if (Array.isArray(saved) && saved.length > 0) return saved
    } catch {}
    return [{ id: `conv_${Date.now()}`, title: 'Yeni Sohbet', messages: [] }]
  })
  const [activeConvId, setActiveConvId] = useState(() => conversations[0]?.id)

  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [liveSteps, setLiveSteps] = useState([])
  const [agentLog, setAgentLog] = useState([])
  const [permissionReq, setPermissionReq] = useState(null)
  const [todos, setTodos] = useState([])

  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const reconnectRef = useRef(null)
  const liveStepsRef = useRef([])

  const activeConv = conversations.find(c => c.id === activeConvId) || conversations[0]
  const messages = activeConv?.messages || []

  // Persist conversations
  useEffect(() => {
    try { localStorage.setItem(CONV_STORAGE_KEY, JSON.stringify(conversations.slice(0, 30))) } catch {}
  }, [conversations])

  // Auto-login
  useEffect(() => {
    const savedCode = localStorage.getItem(ACCESS_CODE_KEY)
    if (!savedCode) { setAuthChecking(false); return }
    authFetch(`${API_URL}/api/profile/load`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ access_code: savedCode })
    })
      .then(async r => {
        const d = await r.json()
        if (r.ok && (d.success || d.ok)) setAuthUser({ access_code: savedCode, name: d.name || `Profil_${savedCode}` })
        else localStorage.removeItem(ACCESS_CODE_KEY)
      })
      .catch(() => {})
      .finally(() => setAuthChecking(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior:'smooth' })
  }, [messages.length, liveSteps.length, thinking])

  const appendMessage = useCallback((msg) => {
    setConversations(prev => prev.map(c => {
      if (c.id !== activeConvId) return c
      const nextMsgs = [...c.messages, msg]
      const nextTitle = (c.title === 'Yeni Sohbet' && msg.role === 'user')
        ? msg.content.slice(0, 36) + (msg.content.length > 36 ? '…' : '')
        : c.title
      return { ...c, title: nextTitle, messages: nextMsgs }
    }))
  }, [activeConvId])

  const pushStep = useCallback((step) => {
    liveStepsRef.current = [...liveStepsRef.current, step]
    setLiveSteps(liveStepsRef.current)
  }, [])

  const connectWS = useCallback(() => {
    if (!authUser) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => { setConnected(false); reconnectRef.current = setTimeout(connectWS, 3000) }
      ws.onerror = () => ws.close()
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          switch (data.type) {
            case 'thinking':
              setThinking(true)
              setAgentLog(p => [...p, { type:'thinking', text: data.content, time: Date.now() }])
              break
            case 'thought':
              setThinking(true)
              pushStep({ kind:'thought', text: data.content })
              setAgentLog(p => [...p, { type:'thinking', text: data.content, time: Date.now() }])
              break
            case 'tool_call':
              pushStep({ kind:'tool_call', tool: data.tool, args: data.args })
              setAgentLog(p => [...p, { type:'tool', name: data.tool, args: data.args, time: Date.now() }])
              break
            case 'tool_result':
              pushStep({ kind:'tool_result', tool: data.tool, text: data.result })
              setAgentLog(p => [...p, { type:'result', name: data.tool, text: data.result, time: Date.now() }])
              break
            case 'tool_denied':
              pushStep({ kind:'denied', text: data.command })
              setAgentLog(p => [...p, { type:'denied', command: data.command, time: Date.now() }])
              break
            case 'permission_request':
              setPermissionReq({ command: data.command, tool_call_id: data.tool_call_id })
              break
            case 'status':
              if (data.content?.includes('tamamlandı') || data.content?.includes('Task completed')) {
                pushStep({ kind:'success', text: data.content })
              } else {
                pushStep({ kind:'status', text: data.content })
              }
              setAgentLog(p => [...p, { type:'status', text: data.content, time: Date.now() }])
              break
            case 'todos':
              setTodos(data.items || [])
              if (!showTodos && (data.items || []).length > 0) setShowTodos(true)
              break
            case 'response': {
              setThinking(false)
              const snap = liveStepsRef.current
              liveStepsRef.current = []
              setLiveSteps([])
              appendMessage({ role:'assistant', content: data.content, steps: snap })
              setAgentLog(p => [...p, { type:'response', text: data.content?.substring(0,200), time: Date.now() }])
              break
            }
            case 'error': {
              setThinking(false)
              const snap = liveStepsRef.current
              liveStepsRef.current = []
              setLiveSteps([])
              appendMessage({ role:'assistant', content: `❌ ${data.content}`, steps: snap })
              break
            }
          }
        } catch {}
      }
    } catch {}
  }, [authUser, appendMessage, pushStep, showTodos])

  useEffect(() => {
    if (authUser) connectWS()
    return () => { clearTimeout(reconnectRef.current); wsRef.current?.close() }
  }, [authUser, connectWS])

  const sendMessage = (overrideText) => {
    const text = (typeof overrideText === 'string' ? overrideText : input).trim()
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    liveStepsRef.current = []
    setLiveSteps([])
    appendMessage({ role:'user', content: text })
    setAgentLog(p => [...p, { type:'user', text, time: Date.now() }])
    wsRef.current.send(JSON.stringify({ type:'chat', message: text }))
    if (typeof overrideText !== 'string') setInput('')
    setThinking(true)
    if (tab !== 'chat') setTab('chat')
  }

  const createNewChat = () => {
    const newId = `conv_${Date.now()}`
    setConversations(prev => [{ id: newId, title:'Yeni Sohbet', messages:[] }, ...prev])
    setActiveConvId(newId)
    setTab('chat')
    liveStepsRef.current = []
    setLiveSteps([])
    setTodos([])
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type:'clear' }))
    }
  }

  const deleteConv = (e, id) => {
    e.stopPropagation()
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id)
      if (next.length === 0) {
        const fresh = { id:`conv_${Date.now()}`, title:'Yeni Sohbet', messages:[] }
        setActiveConvId(fresh.id); return [fresh]
      }
      if (activeConvId === id) setActiveConvId(next[0].id)
      return next
    })
  }

  const handlePermission = (allowed) => {
    if (!permissionReq || !wsRef.current) return
    wsRef.current.send(JSON.stringify({ type:'permission_response', tool_call_id: permissionReq.tool_call_id, allowed }))
    setPermissionReq(null)
  }

  const logout = () => {
    localStorage.removeItem(ACCESS_CODE_KEY)
    wsRef.current?.close()
    setAuthUser(null); setConnected(false)
  }

  if (authChecking) return (
    <div className="auth-wrapper">
      <div style={{ color:'var(--text-secondary)', fontSize:13 }}>Oturum doğrulanıyor...</div>
    </div>
  )

  if (!authUser) return <LoginScreen onAuthenticated={u => setAuthUser(u)} />

  const NAV_ITEMS = [
    { id:'chat',     label:'Konsol',       icon:'⌘' },
    { id:'terminal', label:'ReAct Günlüğü', icon:'📄' },
  ]

  const doneTodos = todos.filter(t => t.status === 'done').length

  return (
    <div className="app-shell">
      {permissionReq && (
        <PermissionModal command={permissionReq.command} onAllow={() => handlePermission(true)} onDeny={() => handlePermission(false)} />
      )}
      {showSettings && <SettingsModal accessCode={authUser.access_code} onClose={() => setShowSettings(false)} />}

      {/* LEFT SIDEBAR */}
      <aside className={`sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="brand-row">
            <div className="brand-mark">A</div>
            {sidebarOpen && <span className="brand-name">ALES Code</span>}
          </div>
          {sidebarOpen && (
            <button className="btn btn-secondary" onClick={createNewChat} style={{ padding:'5px 10px', fontSize:11 }}>
              + Yeni
            </button>
          )}
        </div>

        <div className="sidebar-section">
          {sidebarOpen && <div className="sidebar-label">Görünüm</div>}
          {NAV_ITEMS.map(item => (
            <button key={item.id} className={`nav-item ${tab === item.id ? 'active' : ''}`} onClick={() => setTab(item.id)} title={item.label}>
              <span>{item.icon}</span>
              {sidebarOpen && <span>{item.label}</span>}
            </button>
          ))}
          <button className={`nav-item ${showTodos ? 'active' : ''}`} onClick={() => setShowTodos(v => !v)} title="Görev Listesi">
            <span>📋</span>
            {sidebarOpen && (
              <span>Görevler {todos.length > 0 && <span className="todo-badge">{doneTodos}/{todos.length}</span>}</span>
            )}
          </button>
        </div>

        {sidebarOpen && (
          <>
            <div className="sidebar-label" style={{ paddingLeft:20 }}>Geçmiş</div>
            <div className="sidebar-history">
              {conversations.map(c => (
                <div key={c.id} className={`history-item ${c.id === activeConvId && tab === 'chat' ? 'active' : ''}`}
                  onClick={() => { setActiveConvId(c.id); setTab('chat') }}>
                  <span className="history-title">{c.title}</span>
                  <button className="history-del" onClick={e => deleteConv(e, c.id)} title="Sil">✕</button>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-footer">
          <button className="nav-item" onClick={() => setShowSettings(true)} title="Ayarlar">
            <span>⚙️</span>
            {sidebarOpen && <span>Ayarlar</span>}
          </button>
          {sidebarOpen && (
            <div className="profile-pill">
              <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', color:'var(--text-secondary)', fontSize:11 }}>
                {authUser.name}
              </span>
              <button className="btn-ghost" onClick={logout} style={{ fontSize:10, padding:'2px 6px', borderRadius:4, cursor:'pointer' }}>
                Çıkış
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* MAIN AREA */}
      <main className="main-area">
        {/* TOPBAR */}
        <header className="topbar">
          <div className="topbar-left">
            <button className="btn btn-ghost" onClick={() => setSidebarOpen(v => !v)} style={{ padding:'6px 10px' }}>☰</button>
            <span className="topbar-title">
              {tab === 'chat' ? '⌘ ALES · Claude Code Engine v7' : '📄 ReAct Günlüğü'}
            </span>
          </div>
          <div className="topbar-right">
            {todos.length > 0 && (
              <button className="btn btn-ghost" onClick={() => setShowTodos(v => !v)} style={{ fontSize:11, padding:'4px 10px' }}>
                📋 {doneTodos}/{todos.length} görev
              </button>
            )}
            <div className="status-badge">
              <span className="status-dot" style={{ background: connected ? 'var(--success)' : 'var(--danger)' }} />
              <span>{connected ? 'Bağlı' : 'Çevrimdışı'}</span>
            </div>
            <button className="btn btn-secondary" onClick={() => setShowSettings(true)} style={{ padding:'5px 12px', fontSize:12 }}>
              Ayarlar
            </button>
          </div>
        </header>

        <div className="workspace">
          {/* CHAT / TERMINAL TAB */}
          <div className="content-scroll">
            {tab === 'chat' && (
              <div className="chat-container">
                {messages.length === 0 && !thinking && (
                  <div className="chat-empty">
                    <div className="auth-logo" style={{ width:52, height:52, fontSize:22 }}>A</div>
                    <div className="chat-empty-title">ALES Otonom Kodlama Ajanı</div>
                    <div className="chat-empty-sub">
                      8 çekirdek araç: <code>bash</code> · <code>read_file</code> · <code>write_file</code> · <code>edit_file</code> · <code>grep_search</code> · <code>glob_search</code> · <code>task</code> · <code>todo_write</code>
                    </div>
                    <div className="suggestion-grid">
                      {[
                        "Create a python script that prints 'Hello', run it, then change 'Hello' to 'Hi' using edit_file.",
                        "Mevcut dizindeki tüm dosyaları listele ve yapıyı analiz et.",
                        "MoviePy ile 5 saniyelik bir video oluşturan Python betiği yaz ve çalıştır.",
                        "Projedeki tüm Python dosyalarını tara, fonksiyon sayısını bul.",
                      ].map((p, i) => (
                        <button key={i} className="suggestion-card" onClick={() => sendMessage(p)}>{p}</button>
                      ))}
                    </div>
                  </div>
                )}

                {messages.map((m, i) => (
                  <div key={i} style={{ display:'flex', flexDirection:'column', gap:4 }}>
                    {m.role === 'assistant' && m.steps?.length > 0 && <ConsoleStepList steps={m.steps} />}
                    <div className={`msg-row ${m.role}`}>
                      {m.role === 'user'
                        ? <div className="msg-bubble-user">{m.content}</div>
                        : (
                          <div className="msg-assistant">
                            <div className="assistant-avatar">A</div>
                            <div className="msg-assistant-body">{m.content}</div>
                          </div>
                        )
                      }
                    </div>
                  </div>
                ))}

                {liveSteps.length > 0 && <ConsoleStepList steps={liveSteps} />}

                {thinking && (
                  <div className="msg-row assistant">
                    <div className="thinking-pill">
                      <span className="pulse-dot" />
                      <span>Ajan çalışıyor...</span>
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            )}

            {tab === 'terminal' && (
              <div className="panel-container">
                <div className="panel-header">
                  <div className="panel-title">Ham ReAct Günlüğü</div>
                  <button className="btn btn-secondary" onClick={() => setAgentLog([])} style={{ fontSize:12 }}>Temizle</button>
                </div>
                <div className="terminal-log">
                  {agentLog.length === 0 && (
                    <div style={{ color:'var(--text-muted)', padding:32, textAlign:'center' }}>Henüz aktivite yok.</div>
                  )}
                  {agentLog.map((entry, i) => {
                    const t = new Date(entry.time).toLocaleTimeString('tr-TR', { hour:'2-digit', minute:'2-digit', second:'2-digit' })
                    if (entry.type === 'thinking') return <div key={i} style={{ color:'#fbbf24' }}><span style={{color:'var(--text-muted)'}}>{t}</span> 🧠 {entry.text}</div>
                    if (entry.type === 'tool')     return <div key={i} style={{ color:'#60a5fa' }}><span style={{color:'var(--text-muted)'}}>{t}</span> 🛠️ <b>{entry.name}</b>({JSON.stringify(entry.args||{}).substring(0,160)})</div>
                    if (entry.type === 'result')   return <div key={i} style={{ color:'#4ade80' }}><span style={{color:'var(--text-muted)'}}>{t}</span> 👁️ [{entry.name}] {entry.text?.substring(0,500)}</div>
                    if (entry.type === 'denied')   return <div key={i} style={{ color:'#f87171' }}><span style={{color:'var(--text-muted)'}}>{t}</span> 🚫 Denied: {entry.command}</div>
                    if (entry.type === 'status')   return <div key={i} style={{ color:'#c084fc' }}><span style={{color:'var(--text-muted)'}}>{t}</span> ℹ️ {entry.text}</div>
                    if (entry.type === 'response') return <div key={i} style={{ color:'#34d399' }}><span style={{color:'var(--text-muted)'}}>{t}</span> ✅ {entry.text}</div>
                    if (entry.type === 'user')     return <div key={i} style={{ color:'#e4e4e7' }}><span style={{color:'var(--text-muted)'}}>{t}</span> 👤 {entry.text?.substring(0,200)}</div>
                    return null
                  })}
                  <div ref={bottomRef} />
                </div>
              </div>
            )}
          </div>

          {/* TODO SIDEBAR (RIGHT PANE) */}
          {showTodos && (
            <TodoSidebar todos={todos} onClose={() => setShowTodos(false)} />
          )}
        </div>

        {/* COMPOSER */}
        {tab === 'chat' && (
          <div className="composer-wrap">
            <div className="composer-box">
              <textarea
                className="composer-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                placeholder={connected ? "ALES'e bir kodlama görevi verin... (Enter = Gönder, Shift+Enter = Yeni satır)" : 'Bağlanıyor...'}
                disabled={!connected}
                rows={1}
                style={{ resize:'none', minHeight:40, maxHeight:120, overflowY:'auto' }}
              />
              <button className="btn btn-primary" onClick={() => sendMessage()}
                disabled={!connected || !input.trim()} style={{ padding:'8px 16px', alignSelf:'flex-end' }}>
                ↑
              </button>
            </div>
            <div className="composer-hint">
              8 araç aktif · {connected ? '🟢 Bağlı' : '🔴 Çevrimdışı'} · Shift+Enter yeni satır
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
