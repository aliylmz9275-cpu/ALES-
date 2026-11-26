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

// Render PDF download pills & links inside assistant messages
function renderMessageContent(text) {
  if (!text || typeof text !== 'string') return text
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)|(https?:\/\/[^\s)"',`]+|\/static\/pdfs\/[^\s)"',`]+)/g
  if (!linkRegex.test(text)) return text
  const parts = []
  let lastIndex = 0
  let match
  linkRegex.lastIndex = 0
  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.substring(lastIndex, match.index))
    const url = (match[2] || match[3] || '').trim()
    const label = (match[1] || url.split('/').pop() || 'Dosya').trim()
    const fullUrl = url.startsWith('/') && !url.startsWith('//') ? `${API_URL}${url}` : url
    const isPdf = url.toLowerCase().includes('.pdf') || url.includes('/static/pdfs/')
    if (isPdf) {
      parts.push(
        <a key={match.index} href={fullUrl} target="_blank" rel="noopener noreferrer" download className="pdf-pill">
          <span>📄</span>
          <span>{label}</span>
          <span style={{ opacity: 0.75, fontSize: 11 }}>PDF ⬇</span>
        </a>
      )
    } else {
      parts.push(
        <a key={match.index} href={fullUrl} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'underline' }}>
          {label}
        </a>
      )
    }
    lastIndex = linkRegex.lastIndex
  }
  if (lastIndex < text.length) parts.push(text.substring(lastIndex))
  return parts
}

const TOOL_ICONS = {
  read_file: '📖', write_file: '✍️', edit_file: '✏️', run_bash: '💻',
  grep_search: '🔍', glob_search: '📁', generate_pdf: '📄',
  search_web: '🌐', remember_fact: '💾', recall_memory: '🧠',
  create_plan: '📋', update_plan_step: '✅', take_screenshot: '📸',
  mouse_click: '🖱️', keyboard_type: '⌨️'
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
            keys: {
              groq_key: groqKey.trim(),
              gemini_key: geminiKey.trim()
            }
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
    groq_key: '', gemini_key: '', openrouter_key: '',
    nvidia_key: '', openai_key: '', elevenlabs_key: ''
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
      setKeys({ groq_key: '', gemini_key: '', openrouter_key: '', nvidia_key: '', openai_key: '', elevenlabs_key: '' })
    } catch {
      setSavedMsg('Kaydetme sırasında hata oluştu.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 500 }}>
        <div className="modal-header">
          <div>
            <div className="modal-title">Ayarlar</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              API anahtarları sunucu profilinizde şifrelenmiş oturum olarak saklanır.
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} style={{ padding: '6px 10px' }}>✕</button>
        </div>

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            ['groq_key', 'Groq API Key', 'gsk_...'],
            ['gemini_key', 'Gemini API Key', 'AIza...'],
            ['openrouter_key', 'OpenRouter API Key', 'sk-or-...'],
            ['nvidia_key', 'NVIDIA API Key', 'nvapi-...'],
            ['openai_key', 'OpenAI API Key (TTS)', 'sk-...'],
            ['elevenlabs_key', 'ElevenLabs API Key', '...'],
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

// ─── MAIN APPLICATION ────────────────────────────────────────────
export default function App() {
  const [authChecking, setAuthChecking] = useState(true)
  const [authUser, setAuthUser] = useState(null)

  const [sidebarOpen, setSidebarOpen] = useState(() => typeof window !== 'undefined' ? window.innerWidth > 768 : true)
  const [tab, setTab] = useState('chat')
  const [showSettings, setShowSettings] = useState(false)

  // Conversations persisted in localStorage
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
  const [agentLog, setAgentLog] = useState([])
  const [permissionReq, setPermissionReq] = useState(null)
  const [plans, setPlans] = useState([])
  const [memories, setMemories] = useState([])
  const [memSearch, setMemSearch] = useState('')
  const [memResults, setMemResults] = useState('')
  const [latestScreenshot, setLatestScreenshot] = useState(null)

  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const reconnectRef = useRef(null)

  const activeConv = conversations.find(c => c.id === activeConvId) || conversations[0]
  const messages = activeConv?.messages || []

  // Persist conversations
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

  // Auto-scroll chat
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, thinking, agentLog.length])

  // Load tab data
  useEffect(() => {
    if (!authUser) return
    if (tab === 'plans') {
      authFetch(`${API_URL}/api/plans`).then(r => r.json()).then(setPlans).catch(() => {})
    } else if (tab === 'memory') {
      authFetch(`${API_URL}/api/memory`).then(r => r.json()).then(d => setMemories(d.items || [])).catch(() => {})
    }
  }, [tab, authUser])

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

  // WebSocket connection (only after auth)
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
            case 'tool_call':
              setAgentLog(prev => [...prev, { type: 'tool', name: data.tool, args: data.args, time: Date.now() }])
              break
            case 'tool_result':
              setAgentLog(prev => [...prev, { type: 'result', name: data.tool, text: data.result, time: Date.now() }])
              if (data.tool === 'take_screenshot' && data.result) {
                try {
                  const ssData = JSON.parse(data.result)
                  if (ssData.url) setLatestScreenshot(`${API_URL}${ssData.url}`)
                } catch {}
              }
              break
            case 'tool_denied':
              setAgentLog(prev => [...prev, { type: 'denied', name: data.tool, command: data.command, time: Date.now() }])
              break
            case 'permission_request':
              setPermissionReq({ command: data.command, tool_call_id: data.tool_call_id })
              break
            case 'status':
              setAgentLog(prev => [...prev, { type: 'status', text: data.content, time: Date.now() }])
              break
            case 'plan_update':
              setPlans(data.plans || [])
              break
            case 'response':
              setThinking(false)
              appendMessageToActive({ role: 'assistant', content: data.content })
              setAgentLog(prev => [...prev, { type: 'response', text: data.content?.substring(0, 200), time: Date.now() }])
              break
            case 'error':
              setThinking(false)
              appendMessageToActive({ role: 'assistant', content: `❌ ${data.content}` })
              break
          }
        } catch {}
      }
    } catch {}
  }, [authUser, appendMessageToActive])

  useEffect(() => {
    if (authUser) {
      connectWS()
    }
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [authUser, connectWS])

  const sendMessage = (overrideText) => {
    const text = (typeof overrideText === 'string' ? overrideText : input).trim()
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
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

  const searchMemory = async () => {
    if (!memSearch.trim()) return
    try {
      const r = await authFetch(`${API_URL}/api/memory/search?q=${encodeURIComponent(memSearch)}`)
      const d = await r.json()
      setMemResults(d.result || 'Sonuç bulunamadı.')
    } catch { setMemResults('Arama başarısız.') }
  }

  const deleteMemory = async (memId) => {
    try {
      await authFetch(`${API_URL}/api/memory/${memId}`, { method: 'DELETE' })
      setMemories(prev => prev.filter(m => m.id !== memId))
    } catch {}
  }

  const takeScreenshotNow = async () => {
    try {
      const r = await authFetch(`${API_URL}/api/screenshot`)
      const d = await r.json()
      if (d.url) setLatestScreenshot(`${API_URL}${d.url}`)
    } catch {}
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
    { id: 'chat', label: 'Sohbet', icon: '💬' },
    { id: 'terminal', label: 'Terminal', icon: '⌘' },
    { id: 'plans', label: 'Planlar', icon: '📋' },
    { id: 'memory', label: 'Hafıza', icon: '🧠' },
    { id: 'screen', label: 'Ekran', icon: '📸' },
  ]

  const activeNavLabel = NAV_ITEMS.find(n => n.id === tab)?.label || 'Sohbet'

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

      {/* Left Collapsible Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="brand-row">
            <div className="brand-mark">A</div>
            <span className="brand-name">ALES</span>
          </div>
          <button className="btn btn-secondary" onClick={createNewChat} style={{ padding: '6px 10px', fontSize: 12 }}>
            + Yeni
          </button>
        </div>

        <div className="sidebar-section">
          <div className="sidebar-label">Çalışma Alanı</div>
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

      {/* Main Content Area */}
      <main className="main-area">
        {/* Glassmorphic Top Navbar */}
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="btn btn-ghost"
              onClick={() => setSidebarOpen(v => !v)}
              style={{ padding: '6px 10px' }}
              title="Kenar Çubuğu"
            >
              ☰
            </button>
            <span className="topbar-title">{activeNavLabel}</span>
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

        {/* Scrollable View */}
        <div className="content-scroll">
          {/* ─── CHAT VIEW ─── */}
          {tab === 'chat' && (
            <div className="chat-container">
              {messages.length === 0 && !thinking && (
                <div className="chat-empty">
                  <div className="auth-logo" style={{ width: 48, height: 48, fontSize: 20 }}>A</div>
                  <div className="chat-empty-title">Bugün ne inşa edelim?</div>
                  <div className="chat-empty-sub">
                    Dosya düzenleme, terminal komutları, planlama, uzun süreli hafıza ve ekran kontrolü tek ajan döngüsünde.
                  </div>
                  <div className="suggestion-grid">
                    {[
                      'Proje dosyalarını tara ve özetle',
                      'Bir Python hesap makinesi uygulaması için plan oluştur',
                      'Ekran görüntüsü al ve analiz et',
                      'Önemli proje kararlarını hafızaya kaydet'
                    ].map((prompt, idx) => (
                      <button key={idx} className="suggestion-card" onClick={() => sendMessage(prompt)}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m, i) => (
                <div key={i} className={`msg-row ${m.role}`}>
                  {m.role === 'user' ? (
                    <div className="msg-bubble-user">{m.content}</div>
                  ) : (
                    <div className="msg-assistant">
                      <div className="assistant-avatar">A</div>
                      <div className="msg-assistant-body">{renderMessageContent(m.content)}</div>
                    </div>
                  )}
                </div>
              ))}

              {thinking && (
                <div className="msg-row assistant">
                  <div className="thinking-pill">
                    <span className="pulse-dot" />
                    <span>ALES düşünüyor...</span>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}

          {/* ─── TERMINAL VIEW ─── */}
          {tab === 'terminal' && (
            <div className="panel-container">
              <div className="panel-header">
                <div className="panel-title">Ajan Çalışma Günlüğü</div>
                <button className="btn btn-secondary" onClick={() => setAgentLog([])} style={{ fontSize: 12 }}>
                  Temizle
                </button>
              </div>
              <div className="terminal-log">
                {agentLog.length === 0 && (
                  <div style={{ color: 'var(--text-muted)', padding: 32, textAlign: 'center' }}>
                    Henüz aktivite yok. Sohbet sekmesinden bir komut gönderin.
                  </div>
                )}
                {agentLog.map((entry, i) => {
                  const timeStr = new Date(entry.time).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                  const icon = TOOL_ICONS[entry.name] || '🛠️'
                  if (entry.type === 'thinking') return <div key={i} style={{ color: '#fbbf24' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 🧠 {entry.text}</div>
                  if (entry.type === 'tool') return <div key={i} style={{ color: '#60a5fa' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> {icon} <b>{entry.name}</b>({JSON.stringify(entry.args || {}).substring(0, 120)})</div>
                  if (entry.type === 'result') return <div key={i} style={{ color: '#4ade80' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> {icon} [{entry.name}] {entry.text?.substring(0, 300)}</div>
                  if (entry.type === 'denied') return <div key={i} style={{ color: '#f87171' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 🚫 Reddedildi: {entry.command}</div>
                  if (entry.type === 'status') return <div key={i} style={{ color: '#c084fc' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> ℹ️ {entry.text}</div>
                  if (entry.type === 'response') return <div key={i} style={{ color: '#34d399' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> ✅ Yanıt: {entry.text}</div>
                  if (entry.type === 'user') return <div key={i} style={{ color: '#e4e4e7' }}><span style={{ color: 'var(--text-muted)' }}>{timeStr}</span> 👤 {entry.text?.substring(0, 200)}</div>
                  return null
                })}
                <div ref={bottomRef} />
              </div>
            </div>
          )}

          {/* ─── PLANS VIEW ─── */}
          {tab === 'plans' && (
            <div className="panel-container">
              <div className="panel-header">
                <div className="panel-title">Görev Planları</div>
                <button className="btn btn-secondary" onClick={() => authFetch(`${API_URL}/api/plans`).then(r => r.json()).then(setPlans).catch(() => {})}>
                  ↻ Yenile
                </button>
              </div>
              {plans.length === 0 ? (
                <div className="surface-card" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
                  Henüz plan yok. Sohbette ALES'ten bir plan oluşturmasını isteyin.
                </div>
              ) : plans.map((plan) => (
                <div key={plan.id} className="surface-card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 15 }}>{plan.goal}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{plan.id} · {plan.created_at?.substring(0, 19)}</div>
                    </div>
                    <span className="status-badge">{plan.status?.toUpperCase()}</span>
                  </div>
                  {plan.steps?.map((step, si) => (
                    <div key={si} className="plan-step">
                      <span>{step.status === 'done' ? '✅' : step.status === 'running' ? '⏳' : step.status === 'failed' ? '❌' : '⬜'}</span>
                      <span style={{ flex: 1, fontSize: 13 }}>{step.title}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{step.status}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* ─── MEMORY VIEW ─── */}
          {tab === 'memory' && (
            <div className="panel-container">
              <div className="panel-header">
                <div className="panel-title">Uzun Süreli Hafıza (ChromaDB)</div>
                <button className="btn btn-secondary" onClick={() => authFetch(`${API_URL}/api/memory`).then(r => r.json()).then(d => setMemories(d.items || [])).catch(() => {})}>
                  ↻ Yenile
                </button>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  className="input-field"
                  value={memSearch}
                  onChange={e => setMemSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && searchMemory()}
                  placeholder="Hafızada anlamsal arama yapın..."
                />
                <button className="btn btn-primary" onClick={searchMemory}>Ara</button>
              </div>
              {memResults && (
                <div className="surface-card" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#86efac', whiteSpace: 'pre-wrap' }}>
                  {memResults}
                </div>
              )}
              {memories.length === 0 ? (
                <div className="surface-card" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
                  Hafıza boş. ALES önemli bilgileri otomatik olarak buraya kaydeder.
                </div>
              ) : memories.map((mem) => (
                <div key={mem.id} className="surface-card" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{mem.text}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                      [{mem.category}] · {mem.timestamp?.substring(0, 19)}
                    </div>
                  </div>
                  <button className="btn btn-danger" onClick={() => deleteMemory(mem.id)} style={{ padding: '4px 8px', fontSize: 11 }}>
                    Sil
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* ─── SCREEN VIEW ─── */}
          {tab === 'screen' && (
            <div className="panel-container">
              <div className="panel-header">
                <div className="panel-title">Ekran Görüntüsü</div>
                <button className="btn btn-primary" onClick={takeScreenshotNow}>📸 Ekran Görüntüsü Al</button>
              </div>
              {latestScreenshot ? (
                <div className="surface-card">
                  <img src={latestScreenshot} alt="Screen" style={{ width: '100%', maxHeight: '68vh', objectFit: 'contain', borderRadius: 8 }} />
                </div>
              ) : (
                <div className="surface-card" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 48 }}>
                  Henüz ekran görüntüsü alınmadı. Yukarıdaki butona tıklayın veya sohbetten isteyin.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Chat Composer */}
        {tab === 'chat' && (
          <div className="composer-wrap">
            <div className="composer-box">
              <input
                className="composer-input"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                placeholder={connected ? "ALES'e bir görev verin..." : 'Bağlanıyor...'}
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
