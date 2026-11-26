import { useState, useEffect, useRef, useCallback } from 'react'

const isElectron = typeof window !== 'undefined' && window.ales?.isElectron
const isLocalDev = typeof window !== 'undefined' && window.location.port === '5173'
const isCloud = typeof window !== 'undefined' && window.location.protocol !== 'file:' && !isElectron && !isLocalDev
const backendHost = (typeof window !== 'undefined' && window.location.hostname) || 'localhost'
const API_URL = isCloud ? window.location.origin : `http://${backendHost}:8000`
const WS_URL = isCloud ? window.location.origin.replace(/^http/, 'ws') + '/ws' : `ws://${backendHost}:8000/ws`

const ACCESS_CODE_KEY = 'ales_access_code'
const CONV_STORAGE_KEY = 'ales_conversations_v1'

function authFetch(url, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  return fetch(url, { ...opts, headers })
}

// ─── ACCESS CODE LOGIN SCREEN ────────────────────────────────────
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
    if (!code) {
      setError('Lütfen erişim kodunuzu girin.')
      return
    }
    setLoading(true)
    setError('')
    try {
      if (registerMode) {
        const res = await authFetch(`${API_URL}/api/profile/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            access_code: code,
            keys: { groq_key: groqKey.trim(), gemini_key: geminiKey.trim() }
          })
        })
        const data = await res.json()
        if (data.ok || data.success) {
          localStorage.setItem(ACCESS_CODE_KEY, code)
          onAuthenticated({ access_code: code, name: data.name || `Profil_${code}` })
        } else {
          setError(data.error || 'Profil oluşturulamadı.')
        }
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
        } else {
          setError(data.error || 'Geçersiz erişim kodu.')
        }
      }
    } catch {
      setError('Sunucuya bağlanılamadı. Lütfen tekrar deneyin.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-wrapper">
      <form className="auth-card" onSubmit={handleLogin}>
        <div className="auth-brand">
          <div className="auth-logo">A</div>
          <div className="auth-title">ALES'e Hoş Geldiniz</div>
          <div className="auth-subtitle">
            {registerMode
              ? 'Yeni bir erişim kodu oluşturun ve API anahtarlarınızı kaydedin.'
              : 'Devam etmek için erişim kodunuzu girin.'}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>
              Erişim Kodu
            </label>
            <input
              type="password"
              className="input-field"
              placeholder="Erişim kodunuz..."
              value={accessCode}
              onChange={(e) => setAccessCode(e.target.value)}
              autoFocus
            />
          </div>

          {registerMode && (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>
                  Groq API Key (Opsiyonel)
                </label>
                <input
                  type="password"
                  className="input-field"
                  placeholder="gsk_..."
                  value={groqKey}
                  onChange={(e) => setGroqKey(e.target.value)}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>
                  Gemini API Key (Opsiyonel)
                </label>
                <input
                  type="password"
                  className="input-field"
                  placeholder="AIza..."
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                />
              </div>
            </>
          )}
        </div>

        {error && <div className="auth-error">{error}</div>}

        <button type="submit" className="btn btn-primary" disabled={loading || !accessCode.trim()} style={{ width: '100%', padding: '11px 16px' }}>
          {loading ? 'Doğrulanıyor...' : registerMode ? 'Profil Oluştur ve Giriş Yap' : 'Giriş Yap'}
        </button>

        <button
          type="button"
          className="auth-link"
          onClick={() => { setRegisterMode(!registerMode); setError('') }}
        >
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
          <div className="modal-title" style={{ color: 'var(--warning)' }}>⚠️ İzin Gerekli</div>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          ALES potansiyel olarak riskli bir terminal komutu çalıştırmak istiyor:
        </div>
        <div style={{
          background: '#09090b', border: '1px solid var(--border-subtle)',
          borderRadius: 8, padding: '12px 14px', fontFamily: 'var(--font-mono)',
          fontSize: 13, color: '#fca5a5', wordBreak: 'break-all'
        }}>
          {command}
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onDeny}>Reddet</button>
          <button className="btn btn-primary" onClick={onAllow}>İzin Ver</button>
        </div>
      </div>
    </div>
  )
}

// ─── SETTINGS MODAL ──────────────────────────────────────────────
function SettingsModal({ accessCode, onClose }) {
  const [keys, setKeys] = useState({
    groq_key: '', gemini_key: '', openrouter_key: '', nvidia_key: ''
  })
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setSavedMsg('')
    try {
      const nonEmpty = {}
      Object.entries(keys).forEach(([k, v]) => {
        if (v.trim()) nonEmpty[k] = v.trim()
      })
      if (accessCode) {
        await authFetch(`${API_URL}/api/profile/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_code: accessCode, keys: nonEmpty })
        })
      }
      if (Object.keys(nonEmpty).length > 0) {
        await authFetch(`${API_URL}/config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(nonEmpty)
        })
      }
      setSavedMsg('Ayarlar güvenli şekilde kaydedildi.')
      setKeys({ groq_key: '', gemini_key: '', openrouter_key: '', nvidia_key: '' })
    } catch {
      setSavedMsg('Kaydetme sırasında hata oluştu.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
        <div className="modal-header">
          <div>
            <div className="modal-title">Ayarlar</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              API anahtarları sunucu profilinizde saklanır.
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} style={{ padding: '6px 10px' }}>✕</button>
        </div>

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            ['groq_key', 'Groq API Key (llama-3.3-70b-versatile)', 'gsk_...'],
            ['gemini_key', 'Gemini API Key (gemini-3.8-flash)', 'AIza...'],
            ['openrouter_key', 'OpenRouter API Key', 'sk-or-...'],
            ['nvidia_key', 'NVIDIA API Key', 'nvapi-...'],
          ].map(([field, label, ph]) => (
            <div key={field} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>{label}</label>
              <input
                type="password"
                className="input-field"
                placeholder={`Yeni anahtar girin (${ph})`}
                value={keys[field]}
                onChange={(e) => setKeys(prev => ({ ...prev, [field]: e.target.value }))}
              />
            </div>
          ))}

          {savedMsg && (
            <div style={{ fontSize: 12, color: 'var(--success)', padding: '6px 10px', background: 'rgba(34,197,94,0.1)', borderRadius: 6 }}>
              {savedMsg}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 6 }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>Kapat</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Kaydediliyor...' : 'Kaydet'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── CONSOLE STEP RENDERER ───────────────────────────────────────
function ConsoleStepList({ steps }) {
  if (!steps || steps.length === 0) return null
  return (
    <div className="console-stream">
      {steps.map((s, idx) => {
        if (s.kind === 'thought') {
          return (
            <div key={idx} className="console-line console-thought">
              <span>🧠</span>
              <span><b>Thinking:</b> {s.text}</span>
            </div>
          )
        }
        if (s.kind === 'tool_call') {
          const argSummary = JSON.stringify(s.args || {})
          return (
            <div key={idx} className="console-line console-tool">
              <span>🛠️</span>
              <span><b>Tool Call:</b> {s.tool}({argSummary.length > 140 ? argSummary.slice(0, 140) + '…' : argSummary})</span>
            </div>
          )
        }
        if (s.kind === 'tool_result') {
          return (
            <div key={idx} className="console-line" style={{ flexDirection: 'column', gap: 4 }}>
              <span style={{ color: '#94a3b8' }}>📄 <b>Output:</b></span>
              <pre className="console-output">{s.text}</pre>
            </div>
          )
        }
        if (s.kind === 'success') {
          return (
            <div key={idx} className="console-line console-success">
              <span>✅</span>
              <span><b>Success:</b> {s.text || 'Task completed.'}</span>
            </div>
          )
        }
        if (s.kind === 'status') {
          return (
            <div key={idx} className="console-line" style={{ color: '#c084fc' }}>
              <span>ℹ️</span>
              <span>{s.text}</span>
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

// ─── MAIN APPLICATION ────────────────────────────────────────────
export default function App() {
  const [authChecking, setAuthChecking] = useState(true)
  const [authUser, setAuthUser] = useState(null)

  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window !== 'undefined' ? window.innerWidth > 768 : true)
  const [tab, setTab] = useState('chat')
  const [showSettings, setShowSettings] = useState(false)

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

  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const reconnectRef = useRef(null)
  const liveStepsRef = useRef([])

  const activeConv = conversations.find(c => c.id === activeConvId) || conversations[0]
  const messages = activeConv?.messages || []

  useEffect(() => {
    try {
      localStorage.setItem(CONV_STORAGE_KEY, JSON.stringify(conversations.slice(0, 30)))
    } catch {}
  }, [conversations])

  // Auto-login on startup if access code exists in localStorage
  useEffect(() => {
    const savedCode = localStorage.getItem(ACCESS_CODE_KEY)
    if (!savedCode) {
      setAuthChecking(false)
      return
    }
    authFetch(`${API_URL}/api/profile/load`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_code: savedCode })
    })
      .then(async (r) => {
        const d = await r.json()
        if (r.ok && (d.success || d.ok)) {
          setAuthUser({ access_code: savedCode, name: d.name || `Profil_${savedCode}` })
        } else {
          localStorage.removeItem(ACCESS_CODE_KEY)
        }
      })
      .catch(() => {})
      .finally(() => setAuthChecking(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, liveSteps.length, thinking, agentLog.length])

  const appendMessageToActive = useCallback((msg) => {
    setConversations(prev => prev.map(c => {
      if (c.id !== activeConvId) return c
      const nextMsgs = [...c.messages, msg]
      const nextTitle = (c.title === 'Yeni Sohbet' && msg.role === 'user')
        ? msg.content.slice(0, 34) + (msg.content.length > 34 ? '…' : '')
        : c.title
      return { ...c, title: nextTitle, messages: nextMsgs }
    }))
  }, [activeConvId])

  const pushLiveStep = useCallback((step) => {
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
      ws.onclose = () => {
        setConnected(false)
        reconnectRef.current = setTimeout(connectWS, 3000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          switch (data.type) {
            case 'thinking':
              setThinking(true)
              setAgentLog(prev => [...prev, { type: 'thinking', text: data.content, time: Date.now() }])
              break
            case 'thought':
              setThinking(true)
              pushLiveStep({ kind: 'thought', text: data.content })
              setAgentLog(prev => [...prev, { type: 'thinking', text: data.content, time: Date.now() }])
              break
            case 'tool_call':
              pushLiveStep({ kind: 'tool_call', tool: data.tool, args: data.args })
              setAgentLog(prev => [...prev, { type: 'tool', name: data.tool, args: data.args, time: Date.now() }])
              break
            case 'tool_result':
              pushLiveStep({ kind: 'tool_result', tool: data.tool, text: data.result })
              setAgentLog(prev => [...prev, { type: 'result', name: data.tool, text: data.result, time: Date.now() }])
              break
            case 'tool_denied':
              pushLiveStep({ kind: 'status', text: `🚫 Reddedildi: ${data.command}` })
              setAgentLog(prev => [...prev, { type: 'denied', name: data.tool, command: data.command, time: Date.now() }])
              break
            case 'permission_request':
              setPermissionReq({ command: data.command, tool_call_id: data.tool_call_id })
              break
            case 'status':
              if (data.content?.includes('Task completed')) {
                pushLiveStep({ kind: 'success', text: 'Task completed.' })
              } else {
                pushLiveStep({ kind: 'status', text: data.content })
              }
              setAgentLog(prev => [...prev, { type: 'status', text: data.content, time: Date.now() }])
              break
            case 'response': {
              setThinking(false)
              const stepsSnapshot = liveStepsRef.current
              liveStepsRef.current = []
              setLiveSteps([])
              appendMessageToActive({ role: 'assistant', content: data.content, steps: stepsSnapshot })
              setAgentLog(prev => [...prev, { type: 'response', text: data.content?.substring(0, 200), time: Date.now() }])
              break
            }
            case 'error': {
              setThinking(false)
              const stepsSnapshot = liveStepsRef.current
              liveStepsRef.current = []
              setLiveSteps([])
              appendMessageToActive({ role: 'assistant', content: `❌ ${data.content}`, steps: stepsSnapshot })
              break
            }
          }
        } catch {}
      }
    } catch {}
  }, [authUser, appendMessageToActive, pushLiveStep])

  useEffect(() => {
    if (authUser) connectWS()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [authUser, connectWS])

  const sendMessage = (overrideText) => {
    const text = (typeof overrideText === 'string' ? overrideText : input).trim()
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    liveStepsRef.current = []
    setLiveSteps([])
    appendMessageToActive({ role: 'user', content: text })
    setAgentLog(prev => [...prev, { type: 'user', text, time: Date.now() }])
    wsRef.current.send(JSON.stringify({ type: 'chat', message: text }))
    if (typeof overrideText !== 'string') setInput('')
    setThinking(true)
    if (tab !== 'chat') setTab('chat')
  }

  const createNewChat = () => {
    const newId = `conv_${Date.now()}`
    setConversations(prev => [{ id: newId, title: 'Yeni Sohbet', messages: [] }, ...prev])
    setActiveConvId(newId)
    setTab('chat')
    liveStepsRef.current = []
    setLiveSteps([])
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'clear' }))
    }
  }

  const deleteConversation = (e, id) => {
    e.stopPropagation()
    setConversations(prev => {
      const next = prev.filter(c => c.id !== id)
      if (next.length === 0) {
        const fresh = { id: `conv_${Date.now()}`, title: 'Yeni Sohbet', messages: [] }
        setActiveConvId(fresh.id)
        return [fresh]
      }
      if (activeConvId === id) setActiveConvId(next[0].id)
      return next
    })
  }

  const handlePermission = (allowed) => {
    if (!permissionReq || !wsRef.current) return
    wsRef.current.send(JSON.stringify({
      type: 'permission_response',
      tool_call_id: permissionReq.tool_call_id,
      allowed
    }))
    setPermissionReq(null)
  }

  const logout = () => {
    localStorage.removeItem(ACCESS_CODE_KEY)
    wsRef.current?.close()
    setAuthUser(null)
    setConnected(false)
  }

  if (authChecking) {
    return (
      <div className="auth-wrapper">
        <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Oturum doğrulanıyor...</div>
      </div>
    )
  }

  if (!authUser) {
    return <LoginScreen onAuthenticated={(user) => setAuthUser(user)} />
  }

  const NAV_ITEMS = [
    { id: 'chat', label: 'Konsol / Sohbet', icon: '⌘' },
    { id: 'terminal', label: 'Ham İzleme', icon: '📄' },
  ]

  return (
    <div className="app-shell">
      {permissionReq && (
        <PermissionModal
          command={permissionReq.command}
          onAllow={() => handlePermission(true)}
          onDeny={() => handlePermission(false)}
        />
      )}

      {showSettings && (
        <SettingsModal
          accessCode={authUser.access_code}
          onClose={() => setShowSettings(false)}
        />
      )}

      <aside className={`sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="brand-row">
            <div className="brand-mark">A</div>
            <span className="brand-name">ALES Code</span>
          </div>
          <button className="btn btn-secondary" onClick={createNewChat} style={{ padding: '6px 10px', fontSize: 12 }}>
            + Yeni
          </button>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-label">Görünüm</div>
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              className={`nav-item ${tab === item.id ? 'active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-label" style={{ paddingLeft: 20 }}>Geçmiş</div>
        <div className="sidebar-history">
          {conversations.map(c => (
            <div
              key={c.id}
              className={`history-item ${c.id === activeConvId && tab === 'chat' ? 'active' : ''}`}
              onClick={() => { setActiveConvId(c.id); setTab('chat') }}
            >
              <span className="history-title">{c.title}</span>
              <button className="history-del" onClick={(e) => deleteConversation(e, c.id)} title="Sil">✕</button>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <button className="nav-item" onClick={() => setShowSettings(true)}>
            <span>⚙️</span>
            <span>Ayarlar</span>
          </button>
          <div className="profile-pill">
            <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {authUser.name}
            </span>
            <button className="btn-ghost" onClick={logout} style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, cursor: 'pointer' }}>
              Çıkış
            </button>
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button className="btn btn-ghost" onClick={() => setSidebarOpen(v => !v)} style={{ padding: '6px 10px' }}>
              ☰
            </button>
            <span className="topbar-title">
              {tab === 'chat' ? 'Claude Code 1:1 Konsol' : 'Ham İzleme Günlüğü'}
            </span>
          </div>

          <div className="topbar-right">
            <div className="status-badge">
              <span className="status-dot" style={{ background: connected ? 'var(--success)' : 'var(--danger)' }} />
              <span>{connected ? 'Bağlı' : 'Çevrimdışı'}</span>
            </div>
            <button className="btn btn-secondary" onClick={() => setShowSettings(true)} style={{ padding: '6px 12px', fontSize: 12 }}>
              Ayarlar
            </button>
          </div>
        </header>

        <div className="content-scroll">
          {tab === 'chat' && (
            <div className="chat-container">
              {messages.length === 0 && !thinking && (
                <div className="chat-empty">
                  <div className="auth-logo" style={{ width: 48, height: 48, fontSize: 20 }}>A</div>
                  <div className="chat-empty-title">ALES Otonom Kodlama Ajanı</div>
                  <div className="chat-empty-sub">
                    6 çekirdek araç (read_file, write_file, edit_file, run_bash, grep_search, glob_search) ile doğrudan uygular.
                  </div>
                  <div className="suggestion-grid">
                    {[
                      "Create a python script that prints 'hello', run it, then change it to 'hello world' using edit_file.",
                      'Projedeki tüm Python dosyalarını tara ve yapıyı özetle',
                      'MoviePy ile 5 saniyelik bir video oluşturan Python betiği yaz ve çalıştır',
                      'Mevcut çalışma dizinindeki dosyaları listele'
                    ].map((prompt, idx) => (
                      <button key={idx} className="suggestion-card" onClick={() => sendMessage(prompt)}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {m.role === 'assistant' && m.steps && m.steps.length > 0 && (
                    <ConsoleStepList steps={m.steps} />
                  )}
                  <div className={`msg-row ${m.role}`}>
                    {m.role === 'user' ? (
                      <div className="msg-bubble-user">{m.content}</div>
                    ) : (
                      <div className="msg-assistant">
                        <div className="assistant-avatar">A</div>
                        <div className="msg-assistant-body">{m.content}</div>
                      </div>
                    )}
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
                <button className="btn btn-secondary" onClick={() => setAgentLog([])} style={{ fontSize: 12 }}>
                  Temizle
                </button>
              </div>
              <div className="terminal-log">
                {agentLog.length === 0 && (
                  <div style={{ color: 'var(--text-muted)', padding: 32, textAlign: 'center' }}>
                    Henüz aktivite yok.
                  </div>
                )}
                {agentLog.map((entry, i) => {
                  const timeStr = new Date(entry.time).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                  if (entry.type === 'thinking') return <div key={i} style={{ color: '#fbbf24' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 🧠 Thinking: {entry.text}</div>
                  if (entry.type === 'tool') return <div key={i} style={{ color: '#60a5fa' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 🛠️ Tool Call: <b>{entry.name}</b>({JSON.stringify(entry.args || {}).substring(0, 140)})</div>
                  if (entry.type === 'result') return <div key={i} style={{ color: '#4ade80' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 📄 Output [{entry.name}]: {entry.text?.substring(0, 400)}</div>
                  if (entry.type === 'denied') return <div key={i} style={{ color: '#f87171' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 🚫 Denied: {entry.command}</div>
                  if (entry.type === 'status') return <div key={i} style={{ color: '#c084fc' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> ℹ️ {entry.text}</div>
                  if (entry.type === 'response') return <div key={i} style={{ color: '#34d399' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> ✅ Success: {entry.text}</div>
                  if (entry.type === 'user') return <div key={i} style={{ color: '#e4e4e7' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 👤 {entry.text?.substring(0, 200)}</div>
                  return null
                })}
                <div ref={bottomRef} />
              </div>
            </div>
          )}
        </div>

        {tab === 'chat' && (
          <div className="composer-wrap">
            <div className="composer-box">
              <input
                className="composer-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder={connected ? "ALES'e bir kodlama görevi verin..." : 'Bağlanıyor...'}
                disabled={!connected}
              />
              <button
                className="btn btn-primary"
                onClick={() => sendMessage()}
                disabled={!connected || !input.trim()}
                style={{ padding: '8px 14px' }}
              >
                Gönder
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
