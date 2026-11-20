import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'

export default function Worldview3D({ data, onClose }) {
  const mountRef = useRef(null)
  const sceneRef = useRef(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const W = mountRef.current.clientWidth
    const H = mountRef.current.clientHeight

    // Scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x000000)

    // Camera
    const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 1000)
    camera.position.z = 2.8

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(W, H)
    renderer.setPixelRatio(window.devicePixelRatio)
    mountRef.current.appendChild(renderer.domElement)
    sceneRef.current = { scene, camera, renderer }

    // Stars
    const starGeo = new THREE.BufferGeometry()
    const stars = []
    for (let i = 0; i < 8000; i++) {
      stars.push((Math.random() - 0.5) * 400)
      stars.push((Math.random() - 0.5) * 400)
      stars.push((Math.random() - 0.5) * 400)
    }
    starGeo.setAttribute('position', new THREE.Float32BufferAttribute(stars, 3))
    const starMat = new THREE.PointsMaterial({ color: 0xcccccc, size: 0.18, transparent: true, opacity: 0.7 })
    scene.add(new THREE.Points(starGeo, starMat))

    // Earth - texture yükle
    const loader = new THREE.TextureLoader()
    const earthGeo = new THREE.SphereGeometry(1, 64, 64)

    // NASA'nın açık texture'ı
    loader.load(
      'https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/textures/planets/earth_atmos_2048.jpg',
      (texture) => {
        const earthMat = new THREE.MeshPhongMaterial({
          map: texture,
          specular: new THREE.Color(0x333333),
          shininess: 25,
        })
        const earth = new THREE.Mesh(earthGeo, earthMat)
        earth.name = 'earth'
        scene.add(earth)

        // Atmosphere glow
        const atmosGeo = new THREE.SphereGeometry(1.02, 64, 64)
        const atmosMat = new THREE.MeshPhongMaterial({
          color: 0xffffff,
          transparent: true,
          opacity: 0.12,
          side: THREE.FrontSide,
        })
        scene.add(new THREE.Mesh(atmosGeo, atmosMat))

        // Outer glow ring
        const glowGeo = new THREE.SphereGeometry(1.08, 64, 64)
        const glowMat = new THREE.MeshPhongMaterial({
          color: 0xdddddd,
          transparent: true,
          opacity: 0.05,
          side: THREE.BackSide,
        })
        scene.add(new THREE.Mesh(glowGeo, glowMat))

        setLoaded(true)
      },
      undefined,
      () => {
        // Texture yüklenemezse düz mavi küre
        const earthMat = new THREE.MeshPhongMaterial({
          color: 0x333333,
          emissive: 0x111111,
          wireframe: false,
        })
        const earth = new THREE.Mesh(earthGeo, earthMat)
        earth.name = 'earth'
        scene.add(earth)

        // Wireframe overlay
        const wireMat = new THREE.MeshBasicMaterial({ color: 0xffffff, wireframe: true, transparent: true, opacity: 0.15 })
        scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.001, 32, 32), wireMat))
        setLoaded(true)
      }
    )

    // Clouds
    loader.load(
      'https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/textures/planets/earth_clouds_1024.png',
      (texture) => {
        const cloudGeo = new THREE.SphereGeometry(1.015, 64, 64)
        const cloudMat = new THREE.MeshPhongMaterial({ map: texture, transparent: true, opacity: 0.4 })
        const clouds = new THREE.Mesh(cloudGeo, cloudMat)
        clouds.name = 'clouds'
        scene.add(clouds)
      }
    )

    // Işıklar
    scene.add(new THREE.AmbientLight(0x444444, 1.2))
    const sunLight = new THREE.DirectionalLight(0xffffff, 2.5)
    sunLight.position.set(5, 3, 5)
    scene.add(sunLight)
    const rimLight = new THREE.DirectionalLight(0xffffff, 0.5)
    rimLight.position.set(-5, -2, -5)
    scene.add(rimLight)

    // Mouse drag
    let isDragging = false
    let prevX = 0, prevY = 0
    let rotX = 0, rotY = 0
    let velX = 0, velY = 0

    const onMouseDown = e => { isDragging = true; prevX = e.clientX; prevY = e.clientY }
    const onMouseMove = e => {
      if (!isDragging) return
      velX = (e.clientX - prevX) * 0.008
      velY = (e.clientY - prevY) * 0.008
      rotX += velY; rotY += velX
      prevX = e.clientX; prevY = e.clientY
    }
    const onMouseUp = () => { isDragging = false }

    // Touch
    const onTouchStart = e => { isDragging = true; prevX = e.touches[0].clientX; prevY = e.touches[0].clientY }
    const onTouchMove = e => {
      if (!isDragging) return
      velX = (e.touches[0].clientX - prevX) * 0.008
      velY = (e.touches[0].clientY - prevY) * 0.008
      rotX += velY; rotY += velX
      prevX = e.touches[0].clientX; prevY = e.touches[0].clientY
    }

    renderer.domElement.addEventListener('mousedown', onMouseDown)
    renderer.domElement.addEventListener('mousemove', onMouseMove)
    renderer.domElement.addEventListener('mouseup', onMouseUp)
    renderer.domElement.addEventListener('touchstart', onTouchStart)
    renderer.domElement.addEventListener('touchmove', onTouchMove)
    renderer.domElement.addEventListener('touchend', onMouseUp)

    // Animate
    let animId
    const animate = () => {
      animId = requestAnimationFrame(animate)
      const earth = scene.getObjectByName('earth')
      const clouds = scene.getObjectByName('clouds')
      if (!isDragging) { velX *= 0.95; velY *= 0.95; rotY += velX; rotX += velY; rotY += 0.002 }
      if (earth) { earth.rotation.y = rotY; earth.rotation.x = rotX }
      if (clouds) { clouds.rotation.y = rotY + Date.now() * 0.00005; clouds.rotation.x = rotX }
      renderer.render(scene, camera)
    }
    animate()

    // Resize
    const onResize = () => {
      const W2 = mountRef.current?.clientWidth || W
      const H2 = mountRef.current?.clientHeight || H
      camera.aspect = W2 / H2
      camera.updateProjectionMatrix()
      renderer.setSize(W2, H2)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('mousedown', onMouseDown)
      renderer.domElement.removeEventListener('mousemove', onMouseMove)
      renderer.domElement.removeEventListener('mouseup', onMouseUp)
      if (mountRef.current) mountRef.current.removeChild(renderer.domElement)
      renderer.dispose()
    }
  }, [])

  const sections = data ? data.split('\n\n') : []

  return (
    <div style={{ position:'relative', width:'100%', height:'100%', background:'#000000' }}>
      {/* 3D Canvas */}
      <div ref={mountRef} style={{ position:'absolute', inset:0 }} />

      {/* Overlay gradient */}
      <div style={{ position:'absolute', inset:0, background:'linear-gradient(to right, rgba(2,4,8,0.85) 0%, transparent 45%, transparent 55%, rgba(2,4,8,0.85) 100%)', pointerEvents:'none' }} />
      <div style={{ position:'absolute', inset:0, background:'linear-gradient(to bottom, rgba(2,4,8,0.6) 0%, transparent 20%, transparent 80%, rgba(2,4,8,0.8) 100%)', pointerEvents:'none' }} />

      {/* Sol panel — veri */}
      <div style={{ position:'absolute', left:0, top:0, bottom:0, width:300, overflowY:'auto', padding:'20px 16px', display:'flex', flexDirection:'column', gap:10 }}>
        <div style={{ fontFamily:"'Share Tech Mono',monospace", fontSize:12, color:'#ffffff', letterSpacing:3, marginBottom:4 }}>DUNYA DURUMU</div>
        {!loaded && <div style={{ fontSize:11, color:'#ffffff33', fontFamily:'monospace' }}>Yukluyor...</div>}
        {sections.map((s,i) => (
          <div key={i} style={{ background:'rgba(26,111,255,0.06)', border:'1px solid rgba(26,111,255,0.15)', borderRadius:8, padding:'10px 12px' }}>
            {s.split('\n').map((line,j) => (
              <div key={j} style={{ fontSize:11, color: line.startsWith('[') ? '#ffffff' : '#bbbbbb', fontFamily:'monospace', lineHeight:1.7 }}>
                {line.replace(/\[|\]/g, '')}
              </div>
            ))}
          </div>
        ))}
        {sections.length === 0 && loaded && (
          <div style={{ fontSize:11, color:'#ffffff33', fontFamily:'monospace' }}>Veri yok. ALES'e "gündem" de.</div>
        )}
      </div>

      {/* Sağ panel — bilgi */}
      <div style={{ position:'absolute', right:0, top:0, bottom:0, width:260, padding:'20px 16px', display:'flex', flexDirection:'column', gap:8 }}>
        <div style={{ fontFamily:"'Share Tech Mono',monospace", fontSize:10, color:'#ffffff44', letterSpacing:2 }}>COGRAFYA</div>
        {[
          { label:'Nüfus', val:'8.1 Milyar' },
          { label:'Ülke', val:'195' },
          { label:'Okyanus', val:'5' },
          { label:'Kıta', val:'7' },
        ].map(item => (
          <div key={item.label} style={{ display:'flex', justifyContent:'space-between', padding:'6px 10px', background:'rgba(255,255,255,0.03)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:6 }}>
            <span style={{ fontSize:10, color:'#ffffff55', fontFamily:'monospace' }}>{item.label}</span>
            <span style={{ fontSize:10, color:'#ffffff', fontFamily:'monospace' }}>{item.val}</span>
          </div>
        ))}
        <div style={{ marginTop:'auto', fontSize:9, color:'#ffffff22', fontFamily:'monospace' }}>
          Surukle: dondur<br/>
          "Gundem" de: canli veri
        </div>
      </div>

      {/* Merkez bilgi */}
      <div style={{ position:'absolute', bottom:20, left:'50%', transform:'translateX(-50%)', textAlign:'center' }}>
        <div style={{ fontFamily:"'Share Tech Mono',monospace", fontSize:20, color:'#fff', letterSpacing:6, textShadow:'0 0 20px #ffffff' }}>DUNYA</div>
        <div style={{ fontSize:9, color:'#ffffff', fontFamily:'monospace', letterSpacing:3, marginTop:2 }}>CANLI WORLDVIEW</div>
      </div>
    </div>
  )
}
