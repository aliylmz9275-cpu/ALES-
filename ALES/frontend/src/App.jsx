import { useState, useEffect, useRef, useCallback } from 'react'

const isElectron = typeof window !== 'undefined' && window.ales?.isElectron
const isLocalDev = typeof window !== 'undefined' && window.location.port === '5173'
const isCloud = typeof window !== 'undefined' && window.location.protocol !== 'file:' && !isElectron && !isLocalDev
const backendHost = (typeof window !== 'undefined' && window.location.hostname) || 'localhost'
const API_URL = isCloud ? window.location.origin : `http://${backendHost}:8000`
const WS_URL = isCloud ? window.location.origin.replace(/^http/, 'ws') + '/ws' : `ws://${backendHost}:8000/ws`

function getCloudKey() {
  try { return isCloud ? (localStorage.getItem('ales_cloud_key') || '') : '' } catch { return '' }
}
function setCloudKey(key) {
  try { if (isCloud) localStorage.setItem('ales_cloud_key', key) } catch {}
}
function authFetch(url, opts = {}) {
  const key = getCloudKey()
  const headers = { ...(opts.headers || {}), ...(key ? { 'X-ALES-Key': key } : {}) }
  return fetch(url, { ...opts, headers })
}

// Render PDF download buttons and links in messages
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
    let url = (match[2] || match[3] || '').trim()
    let label = (match[1] || url.split('/').pop() || 'File').trim()
    const fullUrl = url.startsWith('/') && !url.startsWith('//') ? `${API_URL}${url}` : url
    const isPdf = url.toLowerCase().includes('.pdf') || url.includes('/static/pdfs/')
    if (isPdf) {
      parts.push(
        <a key={match.index} href={fullUrl} target="_blank" rel="noopener noreferrer" download
          style={{display:'inline-flex',alignItems:'center',gap:8,background:'rgba(239,68,68,0.2)',border:'1px solid rgba(239,68,68,0.5)',color:'#fecaca',padding:'6px 14px',borderRadius:8,textDecoration:'none',fontWeight:600,fontSize:13,margin:'6px 2px',cursor:'pointer'}}>
          <span style={{fontSize:16}}>📄</span>
          <span>{label}</span>
          <span style={{fontSize:11,background:'rgba(239,68,68,0.35)',padding:'2px 8px',borderRadius:5,fontWeight:700}}>PDF ⬇</span>
        </a>
      )
    } else {
      parts.push(<a key={match.index} href={fullUrl} target="_blank" rel="noopener noreferrer" style={{color:'#60a5fa',textDecoration:'underline'}}>{label}</a>)
    }
    lastIndex = linkRegex.lastIndex
  }
  if (lastIndex < text.length) parts.push(text.substring(lastIndex))
  return parts
}

// ─── TOOL ICON MAP ──────────────────────────────────────────────
const TOOL_ICONS = {
  read_file: '📖', write_file: '✍️', edit_file: '✏️',
  run_bash: '💻', grep_search: '🔍', glob_search: '📁',
  generate_pdf: '📄'
}

// ─── PERMISSION MODAL ───────────────────────────────────────────
function PermissionModal({ command, onAllow, onDeny }) {
  return (
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.85)',backdropFilter:'blur(8px)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:10000}}>
      <div style={{width:480,maxWidth:'92vw',padding:'28px 24px',background:'#1a1a2e',border:'1px solid rgba(255,165,0,0.5)',borderRadius:16,boxShadow:'0 20px 60px rgba(0,0,0,0.9)'}}>
        <div style={{fontSize:20,fontWeight:700,color:'#ffa500',marginBottom:12,display:'flex',alignItems:'center',gap:10}}>
          ⚠️ Permission Required
        </div>
        <div style={{fontSize:13,color:'#ccc',marginBottom:16,lineHeight:1.6}}>
          ALES wants to run a potentially destructive command:
        </div>
        <div style={{background:'#0d0d1a',border:'1px solid rgba(255,255,255,0.1)',borderRadius:8,padding:'12px 16px',fontFamily:'monospace',fontSize:13,color:'#ff6b6b',marginBottom:20,wordBreak:'break-all'}}>
          {command}
        </div>
        <div style={{display:'flex',gap:12}}>
          <button onClick={onDeny} style={{flex:1,padding:'12px',background:'rgba(255,255,255,0.08)',color:'#aaa',border:'1px solid rgba(255,255,255,0.2)',borderRadius:8,fontSize:14,fontWeight:600,cursor:'pointer',fontFamily:'monospace'}}>
            ✕ Deny
          </button>
          <button onClick={onAllow} style={{flex:1,padding:'12px',background:'rgba(255,165,0,0.25)',color:'#ffa500',border:'1px solid rgba(255,165,0,0.5)',borderRadius:8,fontSize:14,fontWeight:600,cursor:'pointer',fontFamily:'monospace'}}>
            ✓ Allow
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── SETUP MODAL ────────────────────────────────────────────────
function SetupModal({ onDone }) {
  const [groqKey, setGroqKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [status, setStatus] = useState('')
  const [ok, setOk] = useState(false)

  const test = async () => {
    if (!groqKey.trim()) return
    setTesting(true); setStatus('')
    try {
      const r = await authFetch(API_URL + '/test-key', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({provider:'groq', key:groqKey.trim()})
      })
      const d = await r.json()
      if (d.ok) { setStatus('✓ Connected!'); setOk(true) }
      else setStatus('✕ ' + (d.error || 'Failed'))
    } catch(e) { setStatus('✕ Connection error') }
    setTesting(false)
  }

  const save = async () => {
    if (!ok) return
    await authFetch(API_URL + '/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({groq_key: groqKey.trim()})
    }).catch(() => {})
    onDone()
  }

  return (
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.9)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:10000}}>
      <div style={{width:420,padding:'32px 28px',background:'#1E1E24',border:'1px solid rgba(255,255,255,0.2)',borderRadius:16,display:'flex',flexDirection:'column',gap:16}}>
        <div style={{fontSize:22,fontWeight:800,color:'#fff',letterSpacing:2,fontFamily:"'Share Tech Mono',monospace"}}>ALES SETUP</div>
        <div style={{fontSize:12,color:'#999'}}>Enter a Groq API key to get started.</div>
        <input type="password" placeholder="gsk_..." value={groqKey} onChange={e => setGroqKey(e.target.value)}
          style={{padding:'10px 12px',background:'#121212',border:'1px solid rgba(255,255,255,0.2)',borderRadius:8,color:'#fff',fontSize:14,fontFamily:'monospace',outline:'none'}} />
        <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" style={{fontSize:11,color:'#38bdf8'}}>Get a free Groq key →</a>
        {status && <div style={{fontSize:13,color:ok?'#4ade80':'#f87171'}}>{status}</div>}
        <div style={{display:'flex',gap:10}}>
          <button onClick={test} disabled={testing||!groqKey.trim()} style={{flex:1,padding:'12px',background:'rgba(255,255,255,0.1)',color:'#fff',border:'1px solid rgba(255,255,255,0.2)',borderRadius:8,cursor:'pointer',fontFamily:'monospace',fontWeight:600}}>
            {testing ? 'Testing...' : 'Test'}
          </button>
          <button onClick={save} disabled={!ok} style={{flex:1,padding:'12px',background:ok?'#fff':'rgba(255,255,255,0.1)',color:ok?'#000':'#555',border:'none',borderRadius:8,cursor:ok?'pointer':'not-allowed',fontFamily:'monospace',fontWeight:700}}>
            Save & Start
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── MAIN APP ───────────────────────────────────────────────────
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [tab, setTab] = useState('chat')
  const [showSetup, setShowSetup] = useState(false)
  const [agentLog, setAgentLog] = useState([]) // For terminal tab
  const [permissionReq, setPermissionReq] = useState(null) // {command, tool_call_id}
  const [settings, setSettings] = useState({})
  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const reconnectRef = useRef(null)

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, agentLog])

  // Check if setup is needed
  useEffect(() => {
    authFetch(`${API_URL}/config`).then(r => r.json()).then(cfg => {
      setSettings(cfg)
      if (!cfg.groq_key && !cfg.gemini_key) setShowSetup(true)
    }).catch(() => {})
  }, [])

  // WebSocket connection
  const connectWS = useCallback(() => {
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
          switch(data.type) {
            case 'thinking':
              setThinking(true)
              setAgentLog(prev => [...prev, {type:'thinking', text: data.content, time: Date.now()}])
              break
            case 'tool_call':
              setAgentLog(prev => [...prev, {type:'tool', name: data.tool, args: data.args, time: Date.now()}])
              break
            case 'tool_result':
              setAgentLog(prev => [...prev, {type:'result', name: data.tool, text: data.result, time: Date.now()}])
              break
            case 'tool_denied':
              setAgentLog(prev => [...prev, {type:'denied', name: data.tool, command: data.command, time: Date.now()}])
              break
            case 'permission_request':
              setPermissionReq({ command: data.command, tool_call_id: data.tool_call_id })
              break
            case 'status':
              setAgentLog(prev => [...prev, {type:'status', text: data.content, time: Date.now()}])
              break
            case 'response':
              setThinking(false)
              setMessages(prev => [...prev, {role:'assistant', content: data.content}])
              setAgentLog(prev => [...prev, {type:'response', text: data.content?.substring(0, 200), time: Date.now()}])
              break
            case 'error':
              setThinking(false)
              setMessages(prev => [...prev, {role:'assistant', content: `❌ ${data.content}`}])
              break
          }
        } catch {}
      }
    } catch {}
  }, [])

  useEffect(() => {
    connectWS()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connectWS])

  const send = () => {
    const text = input.trim()
    if (!text || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, {role:'user', content: text}])
    setAgentLog(prev => [...prev, {type:'user', text, time: Date.now()}])
    wsRef.current.send(JSON.stringify({type:'chat', message: text}))
    setInput('')
    setThinking(true)
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

  // ─── RENDER ──────────────────────────────────────────────────
  const tabStyle = (t) => ({
    padding: '8px 20px', cursor: 'pointer', fontSize: 12, fontWeight: 700,
    letterSpacing: 2, fontFamily: 'monospace', border: 'none',
    background: tab === t ? 'rgba(255,255,255,0.12)' : 'transparent',
    color: tab === t ? '#fff' : '#666',
    borderBottom: tab === t ? '2px solid #fff' : '2px solid transparent',
    transition: 'all .15s'
  })

  return (
    <div style={{width:'100vw',height:'100vh',background:'#0a0a0f',color:'#e4e4e7',display:'flex',flexDirection:'column',fontFamily:"'Inter',system-ui,sans-serif"}}>
      {/* Permission Modal */}
      {permissionReq && (
        <PermissionModal
          command={permissionReq.command}
          onAllow={() => handlePermission(true)}
          onDeny={() => handlePermission(false)}
        />
      )}

      {/* Setup Modal */}
      {showSetup && <SetupModal onDone={() => { setShowSetup(false); connectWS() }} />}

      {/* Header */}
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 20px',height:48,borderBottom:'1px solid rgba(255,255,255,0.08)',flexShrink:0}}>
        <div style={{display:'flex',alignItems:'center',gap:12}}>
          <span style={{fontSize:16,fontWeight:900,letterSpacing:3,fontFamily:"'Share Tech Mono',monospace",color:'#fff'}}>ALES</span>
          <span style={{fontSize:9,color:'#555',fontFamily:'monospace'}}>v4.0 · Claude Code Architecture</span>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <div style={{width:7,height:7,borderRadius:'50%',background:connected?'#4ade80':'#f87171'}} />
          <span style={{fontSize:10,color:'#777',fontFamily:'monospace'}}>{connected ? 'CONNECTED' : 'OFFLINE'}</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{display:'flex',borderBottom:'1px solid rgba(255,255,255,0.06)',flexShrink:0}}>
        <button style={tabStyle('chat')} onClick={() => setTab('chat')}>SOHBET</button>
        <button style={tabStyle('terminal')} onClick={() => setTab('terminal')}>TERMİNAL</button>
        <button style={tabStyle('settings')} onClick={() => setTab('settings')}>AYARLAR</button>
      </div>

      {/* Content */}
      <div style={{flex:1,overflow:'auto',padding:'16px 20px'}}>
        {/* ─── CHAT TAB ──────────────────────────────── */}
        {tab === 'chat' && (
          <div style={{maxWidth:800,margin:'0 auto'}}>
            {messages.length === 0 && !thinking && (
              <div style={{textAlign:'center',paddingTop:80,color:'#444'}}>
                <div style={{fontSize:48,marginBottom:16}}>⚡</div>
                <div style={{fontSize:16,fontWeight:600,color:'#666'}}>ALES v4.0</div>
                <div style={{fontSize:12,color:'#444',marginTop:8,fontFamily:'monospace'}}>Claude Code Architecture · 7 Tools · ReAct Loop</div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{
                marginBottom:16, padding:'14px 18px',
                background: m.role === 'user' ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.03)',
                borderRadius: 12, borderLeft: m.role === 'user' ? '3px solid #555' : '3px solid #333'
              }}>
                <div style={{fontSize:10,color:'#555',fontFamily:'monospace',marginBottom:6}}>
                  {m.role === 'user' ? '👤 YOU' : '🤖 ALES'}
                </div>
                <div style={{fontSize:14,lineHeight:1.7,whiteSpace:'pre-wrap',color:'#ddd'}}>
                  {renderMessageContent(m.content)}
                </div>
              </div>
            ))}
            {thinking && (
              <div style={{padding:'14px 18px',background:'rgba(255,255,255,0.03)',borderRadius:12,borderLeft:'3px solid #ffa500'}}>
                <div style={{fontSize:13,color:'#ffa500',fontFamily:'monospace',display:'flex',alignItems:'center',gap:8}}>
                  <span style={{animation:'pulse 1.5s infinite'}}>🧠</span> Thinking...
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {/* ─── TERMINAL TAB (Agent Activity Log) ─────── */}
        {tab === 'terminal' && (
          <div style={{fontFamily:'monospace',fontSize:12,maxWidth:900,margin:'0 auto'}}>
            <div style={{color:'#555',marginBottom:12,fontSize:11}}>Agent Activity Log — ReAct Loop Trace</div>
            {agentLog.length === 0 && (
              <div style={{color:'#444',padding:40,textAlign:'center'}}>No activity yet. Send a message in SOHBET tab.</div>
            )}
            {agentLog.map((entry, i) => {
              const timeStr = new Date(entry.time).toLocaleTimeString('tr-TR', {hour:'2-digit',minute:'2-digit',second:'2-digit'})
              if (entry.type === 'thinking') return (
                <div key={i} style={{padding:'4px 0',color:'#ffa500'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> 🧠 {entry.text}
                </div>
              )
              if (entry.type === 'tool') return (
                <div key={i} style={{padding:'4px 0',color:'#38bdf8'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> 🛠️ <b>{entry.name}</b>({JSON.stringify(entry.args || {}).substring(0, 120)})
                </div>
              )
              if (entry.type === 'result') return (
                <div key={i} style={{padding:'4px 0',color:'#86efac'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> 💻 <span style={{color:'#666'}}>[{entry.name}]</span> {entry.text?.substring(0, 300)}
                </div>
              )
              if (entry.type === 'denied') return (
                <div key={i} style={{padding:'4px 0',color:'#f87171'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> 🚫 Denied: {entry.command}
                </div>
              )
              if (entry.type === 'status') return (
                <div key={i} style={{padding:'4px 0',color:'#a78bfa'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> ℹ️ {entry.text}
                </div>
              )
              if (entry.type === 'response') return (
                <div key={i} style={{padding:'4px 0',color:'#4ade80'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> ✅ Response: {entry.text}
                </div>
              )
              if (entry.type === 'user') return (
                <div key={i} style={{padding:'4px 0',color:'#e4e4e7'}}>
                  <span style={{color:'#555'}}>{timeStr}</span> 👤 {entry.text?.substring(0, 200)}
                </div>
              )
              return null
            })}
            <div ref={bottomRef} />
          </div>
        )}

        {/* ─── SETTINGS TAB ──────────────────────────── */}
        {tab === 'settings' && (
          <div style={{maxWidth:500,margin:'0 auto'}}>
            <div style={{fontSize:16,fontWeight:700,marginBottom:20,color:'#fff'}}>⚙️ Settings</div>
            {['groq_key', 'gemini_key', 'openrouter_key', 'openai_key', 'elevenlabs_key'].map(k => (
              <div key={k} style={{marginBottom:14}}>
                <label style={{fontSize:12,color:'#999',fontFamily:'monospace',display:'block',marginBottom:4}}>{k}</label>
                <input
                  type="password"
                  placeholder={k}
                  defaultValue={settings[k] || ''}
                  onBlur={e => {
                    const val = e.target.value.trim()
                    if (val) {
                      authFetch(API_URL + '/config', {
                        method: 'POST',
                        headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({[k]: val})
                      }).catch(() => {})
                    }
                  }}
                  style={{width:'100%',padding:'10px 12px',background:'#121218',border:'1px solid rgba(255,255,255,0.15)',borderRadius:8,color:'#fff',fontSize:13,fontFamily:'monospace',outline:'none'}}
                />
              </div>
            ))}
            <div style={{marginTop:20,padding:'14px',background:'rgba(255,255,255,0.04)',borderRadius:8,fontSize:11,color:'#666',fontFamily:'monospace',lineHeight:1.6}}>
              <div>Architecture: Claude Code (7 Pillars)</div>
              <div>Tools: read_file, write_file, edit_file, run_bash, grep_search, glob_search, generate_pdf</div>
              <div>Max Agent Turns: 15</div>
              <div>Auto-Compact: 70% context threshold</div>
              <div>Permission Gate: destructive commands require approval</div>
            </div>
          </div>
        )}
      </div>

      {/* Input Bar */}
      <div style={{flexShrink:0,borderTop:'1px solid rgba(255,255,255,0.08)',padding:'12px 20px',display:'flex',gap:10}}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder={connected ? "Ask ALES anything..." : "Connecting..."}
          disabled={!connected}
          style={{flex:1,padding:'12px 16px',background:'rgba(255,255,255,0.06)',border:'1px solid rgba(255,255,255,0.1)',borderRadius:10,color:'#fff',fontSize:14,outline:'none',fontFamily:"'Inter',sans-serif"}}
        />
        <button onClick={send} disabled={!connected || !input.trim()}
          style={{padding:'12px 24px',background:input.trim()?'#fff':'rgba(255,255,255,0.1)',color:input.trim()?'#000':'#555',border:'none',borderRadius:10,fontWeight:700,cursor:input.trim()?'pointer':'not-allowed',fontSize:14,fontFamily:'monospace',letterSpacing:1}}>
          ➤
        </button>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1}50%{opacity:0.4} }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
      `}</style>
    </div>
  )
}
