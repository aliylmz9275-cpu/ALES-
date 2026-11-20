import { StrictMode, Component } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
// Keskinlik/DPI kurallari. App.jsx'ten ONCE gelmeli: App.jsx satir ici
// stil kullaniyor ve satir ici stil her zaman kazanir, ama <style> ile
// enjekte ettigi @keyframes/global kurallar sirayla degerlendirilir.
import './index.css'

// Hata Sinirlari (Error Boundary)
// Eskiden tek bir undefined-degisken hatasi tum uygulamayi
// kalici siyah ekrana cikariyordu. Artik hata yakalanir,
// kullaniciya "Yeniden Baslat" secenegi gosterilir.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('[ALES] Yakalanan hata:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          position:'fixed', inset:0, background:'#060810', color:'#e0e8f5',
          display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center',
          fontFamily:"'Inter',sans-serif", gap:16, padding:24, textAlign:'center'
        }}>
          <div style={{fontFamily:"'Share Tech Mono',monospace", fontSize:22, letterSpacing:4, color:'#ff6b8a'}}>ALES - HATA</div>
          <div style={{fontSize:13, color:'#ffffff88', maxWidth:420, lineHeight:1.6}}>
            Bir seyler ters gitti ama merak etme, programin hicbir parcasi kaybolmadi.
          </div>
          <div style={{fontSize:11, color:'#ffffff44', fontFamily:'monospace', maxWidth:440, wordBreak:'break-word', background:'rgba(255,255,255,0.04)', padding:'10px 14px', borderRadius:8}}>
            {String(this.state.error?.message || this.state.error || 'Bilinmeyen hata')}
          </div>
          <button
            style={{padding:'10px 24px', background:'#1a6fff', border:'none', borderRadius:9, color:'#fff', fontSize:12, fontWeight:700, cursor:'pointer', fontFamily:'monospace', letterSpacing:2}}
            onClick={() => window.location.reload()}
          >YENIDEN BASLAT</button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
)
