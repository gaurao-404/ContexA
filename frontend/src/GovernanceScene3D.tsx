import { useEffect, useRef } from 'react'

/**
 * A small dependency-free 3D scene for the ContexA dashboard.
 * Geometry is transformed in 3D and perspective-projected on canvas: the crystal
 * is a rotating icosahedron, the rings are 3D orbital planes, and the glass asset
 * chips travel around the core with real depth scaling/occlusion.
 */
export default function GovernanceScene3D({ score = 94, motionLevel = 'studio' }: { score?: number; motionLevel?: 'calm' | 'studio' | 'cinematic' }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const host = hostRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !host || !ctx) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const motionFactor = motionLevel === 'calm' ? 0.46 : motionLevel === 'cinematic' ? 1.52 : 1
    let raf = 0
    let width = 360
    let height = 240
    let dpr = Math.min(window.devicePixelRatio || 1, 2)
    let pointerX = 0
    let pointerY = 0
    let lastTime = 0
    const faces: number[][] = [
      [0,11,5],[0,5,1],[0,1,7],[0,7,10],[0,10,11],
      [1,5,9],[5,11,4],[11,10,2],[10,7,6],[7,1,8],
      [3,9,4],[3,4,2],[3,2,6],[3,6,8],[3,8,9],
      [4,9,5],[2,4,11],[6,2,10],[8,6,7],[9,8,1],
    ]
    const t = (1 + Math.sqrt(5)) / 2
    const raw: number[][] = [
      [-1,t,0],[1,t,0],[-1,-t,0],[1,-t,0],[0,-1,t],[0,1,t],
      [0,-1,-t],[0,1,-t],[t,0,-1],[t,0,1],[-t,0,-1],[-t,0,1],
    ]
    const vertices = raw.map(v => { const n = Math.hypot(v[0],v[1],v[2]); return v.map(x => x / n * 63) })
    const particles = Array.from({ length: 42 }, (_, i) => ({
      angle: i * 2.39996, radius: 83 + (i % 5) * 12,
      yScale: .26 + (i % 4) * .09, tilt: (i % 3 - 1) * .65,
      size: .7 + (i % 4) * .32, hue: i % 3,
    }))
    const chips = [
      { label: 'CLAIMS', short: 'C', angle: .7, speed: .58, radius: 91, tilt: .66, hue: 0 },
      { label: 'POLICY', short: 'P', angle: 2.85, speed: -.43, radius: 107, tilt: -.46, hue: 1 },
      { label: 'ACCESS', short: 'A', angle: 4.8, speed: .46, radius: 96, tilt: .92, hue: 2 },
      { label: 'PRICE', short: '$', angle: 5.6, speed: -.51, radius: 116, tilt: .32, hue: 0 },
    ]
    // Recognisable document tiles orbit the policy crystal as actual perspective-projected planes.
    const documentNodes = [
      { label: 'PDF', angle: .28, speed: -.20, rx: 132, ry: 54, tilt: .34, yaw: .54, hue: 0 },
      { label: 'PPT', angle: 2.47, speed: .16, rx: 139, ry: 49, tilt: -.62, yaw: -.38, hue: 1 },
      { label: 'DOC', angle: 4.75, speed: -.18, rx: 126, ry: 61, tilt: .88, yaw: .72, hue: 2 },
    ]
    const parseCssColor = (property: string, fallback: {r:number;g:number;b:number}) => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(property).trim()
      const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
      if (hex) {
        const raw = hex[1].length === 3 ? hex[1].split('').map(ch => ch + ch).join('') : hex[1]
        return { r: parseInt(raw.slice(0,2),16), g: parseInt(raw.slice(2,4),16), b: parseInt(raw.slice(4,6),16) }
      }
      const rgb = value.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i)
      return rgb ? { r:Number(rgb[1]), g:Number(rgb[2]), b:Number(rgb[3]) } : fallback
    }
    const readPalette = () => [
      parseCssColor('--teal', { r:245, g:154, b:120 }),
      parseCssColor('--purple', { r:178, g:161, b:237 }),
      parseCssColor('--blue', { r:142, g:200, b:232 }),
    ]
    let colorSet = readPalette()
    const themeObserver = new MutationObserver(() => { colorSet = readPalette() })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const color = (c: {r:number;g:number;b:number}, a:number) => `rgba(${c.r},${c.g},${c.b},${a})`
    const rotate = (v: number[], ax: number, ay: number, az: number) => {
      let [x,y,z] = v
      let c = Math.cos(ax), s = Math.sin(ax); [y,z] = [y*c-z*s, y*s+z*c]
      c = Math.cos(ay); s = Math.sin(ay); [x,z] = [x*c+z*s, -x*s+z*c]
      c = Math.cos(az); s = Math.sin(az); [x,y] = [x*c-y*s, x*s+y*c]
      return [x,y,z]
    }
    const project = (v: number[], cx:number, cy:number, zoom = 1) => {
      const focal = 360
      const perspective = focal / (focal - v[2])
      return { x: cx + v[0] * perspective * zoom, y: cy + v[1] * perspective * zoom, z: v[2], scale: perspective * zoom }
    }
    const roundedRect = (x:number,y:number,w:number,h:number,r:number) => {
      ctx.beginPath(); ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.quadraticCurveTo(x+w,y,x+w,y+r)
      ctx.lineTo(x+w,y+h-r); ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h); ctx.lineTo(x+r,y+h)
      ctx.quadraticCurveTo(x,y+h,x,y+h-r); ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath()
    }
    const drawDocumentNode = (node: typeof documentNodes[number], time: number, cx: number, cy: number) => {
      const a = node.angle + time * node.speed
      const centre = rotate([Math.cos(a)*node.rx, Math.sin(a)*node.ry, Math.sin(a*1.7)*32], node.tilt, node.yaw, a*.24)
      const corners3 = [[-12,-16,0],[12,-16,0],[12,16,0],[-12,16,0]].map(([x,y,z]) => {
        const offset = rotate([x,y,z], node.tilt + Math.sin(a)*.12, node.yaw + Math.cos(a)*.13, a*.24)
        return project([centre[0]+offset[0],centre[1]+offset[1],centre[2]+offset[2]],cx,cy,.95)
      })
      ctx.save(); ctx.globalAlpha = Math.min(.98, Math.max(.46, .76 + centre[2]/350))
      ctx.beginPath(); ctx.moveTo(corners3[0].x,corners3[0].y); corners3.slice(1).forEach(pt => ctx.lineTo(pt.x,pt.y)); ctx.closePath()
      const g = ctx.createLinearGradient(corners3[0].x,corners3[0].y,corners3[2].x,corners3[2].y)
      g.addColorStop(0,'rgba(255,255,255,.16)'); g.addColorStop(.45,'rgba(54,45,74,.94)'); g.addColorStop(1,'rgba(17,16,28,.97)')
      ctx.fillStyle = g; ctx.fill(); ctx.strokeStyle = color(colorSet[node.hue],.72); ctx.lineWidth = 1; ctx.stroke()
      // Folded-corner detail and writing lines make each floating plane read as a real content asset.
      const mix = (p: {x:number;y:number;z:number;scale:number}, q: {x:number;y:number;z:number;scale:number}, f:number) => ({x:p.x+(q.x-p.x)*f,y:p.y+(q.y-p.y)*f,z:0,scale:1})
      const foldA=mix(corners3[0],corners3[1],.70), foldB=mix(corners3[0],corners3[1],1), foldC=mix(corners3[0],corners3[3],.28)
      ctx.beginPath(); ctx.moveTo(foldA.x,foldA.y); ctx.lineTo(foldC.x,foldC.y); ctx.lineTo(foldB.x,foldB.y); ctx.closePath(); ctx.fillStyle=color(colorSet[node.hue],.34); ctx.fill()
      for(let line=0;line<3;line++) { const f=.43+line*.12; const left=mix(corners3[0],corners3[3],f); const right=mix(corners3[1],corners3[2],f); ctx.beginPath(); ctx.moveTo(left.x,left.y); ctx.lineTo(left.x+(right.x-left.x)*(.72+(line%2)*.12),left.y+(right.y-left.y)*(.72+(line%2)*.12)); ctx.strokeStyle='rgba(246,240,255,.33)'; ctx.lineWidth=.8; ctx.stroke() }
      const footL=mix(corners3[3],corners3[2],.15), footR=mix(corners3[3],corners3[2],.85)
      ctx.beginPath(); ctx.moveTo(footL.x,footL.y); ctx.lineTo(footR.x,footR.y); ctx.strokeStyle=color(colorSet[node.hue],.78); ctx.lineWidth=1.6; ctx.stroke()
      ctx.restore()
    }
    const sizeCanvas = () => {
      const rect = host.getBoundingClientRect()
      width = Math.max(240, rect.width || 360)
      height = Math.max(190, rect.height || 240)
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      canvas.style.width = '100%'; canvas.style.height = '100%'
      const unit = Math.min(canvas.width / 360, canvas.height / 240)
      ctx.setTransform(unit, 0, 0, unit, (canvas.width - 360 * unit) / 2, (canvas.height - 240 * unit) / 2)
    }
    const draw = (now: number) => {
      if (!reducedMotion.matches) raf = window.requestAnimationFrame(draw)
      else raf = 0
      const time = reducedMotion.matches ? 1.4 : now / 1000 * motionFactor
      if (Math.abs(now - lastTime) < 16 && !reducedMotion.matches) return
      lastTime = now
      ctx.clearRect(0,0,360,240)
      const cx = 181 + pointerX * 5
      const cy = 115 + pointerY * 4
      const ax = .34 + time * .43 + pointerY * .11
      const ay = time * .73 + pointerX * .14
      const az = -.12 + time * .30

      // Deep orbital ellipses (three different planes) — not a flashing glow effect.
      const rings = [
        { rx: 112, ry: 45, ax: .76, ay: -.18, az: time * .10, color: color(colorSet[1], .43), dash: [] as number[] },
        { rx: 99, ry: 66, ax: 1.13, ay: .70, az: -time * .075, color: color(colorSet[2], .34), dash: [3,5] },
        { rx: 129, ry: 31, ax: .28, ay: .38, az: time * .12, color: 'rgba(255,255,255,.17)', dash: [1,7] },
      ]
      rings.forEach(ring => {
        ctx.beginPath(); ctx.setLineDash(ring.dash); ctx.strokeStyle = ring.color; ctx.lineWidth = 1
        for (let i=0;i<=120;i++) {
          const a = i / 120 * Math.PI * 2
          const q = rotate([Math.cos(a)*ring.rx, Math.sin(a)*ring.ry, 0], ring.ax, ring.ay, ring.az)
          const p = project(q,cx,cy)
          if (i===0) ctx.moveTo(p.x,p.y); else ctx.lineTo(p.x,p.y)
        }
        ctx.stroke(); ctx.setLineDash([])
      })

      // Background orbit motes with perspective scaling and varied depth.
      particles.forEach((p,i) => {
        const a = p.angle + (reducedMotion.matches ? 0 : time * (.06 + i % 4 * .012))
        const v = rotate([Math.cos(a)*p.radius, Math.sin(a)*p.radius*p.yScale, Math.sin(a*1.7)*18], p.tilt, .42+pointerX*.08, -.08)
        const q = project(v,cx,cy,.93)
        const alpha = .20 + ((Math.sin(a*2)+1)*.14)
        ctx.beginPath(); ctx.fillStyle = color(colorSet[p.hue],alpha); ctx.arc(q.x,q.y,p.size*q.scale,0,Math.PI*2); ctx.fill()
      })

      // Orbiting document thumbnails use actual 3D coordinates and front/back depth ordering.
      const documentPositions = documentNodes.map(node => {
        const a = node.angle + time * node.speed
        const centre = rotate([Math.cos(a)*node.rx, Math.sin(a)*node.ry, Math.sin(a*1.7)*32], node.tilt, node.yaw, a*.24)
        return { node, z: centre[2] }
      }).sort((a,b)=>a.z-b.z)
      documentPositions.filter(d=>d.z<0).forEach(d=>drawDocumentNode(d.node,time,cx,cy))

      // Orbiting content/rule objects. Draw far chips first; foreground chips are redrawn later.
      const chipPositions = chips.map((chip,index) => {
        const a = chip.angle + (reducedMotion.matches ? 0 : time*chip.speed)
        const v = rotate([Math.cos(a)*chip.radius, Math.sin(a)*chip.radius*.48, Math.sin(a*1.5)*28], chip.tilt, .35 + index*.43 + pointerX*.08, .06)
        return { chip, index, v, p: project(v,cx,cy,.93) }
      }).sort((a,b) => a.p.z-b.p.z)
      const drawChip = (item: typeof chipPositions[number]) => {
        const { chip, p, v } = item
        const w = (chip.label === 'ACCESS' ? 65 : 62) * p.scale
        const h = 27 * p.scale
        const x = p.x-w/2, y = p.y-h/2
        // A tether makes the object feel anchored to the 3D rule graph.
        ctx.beginPath(); ctx.moveTo(p.x,p.y); ctx.lineTo(cx + v[0]*.19, cy + v[1]*.19)
        ctx.strokeStyle = color(colorSet[chip.hue],.19*p.scale); ctx.lineWidth=.8; ctx.stroke()
        ctx.save(); ctx.shadowColor = color(colorSet[chip.hue],.22); ctx.shadowBlur = 12*p.scale
        roundedRect(x,y,w,h,6*p.scale)
        const grad = ctx.createLinearGradient(x,y,x+w,y+h)
        grad.addColorStop(0,'rgba(58,48,82,.94)'); grad.addColorStop(1,'rgba(21,17,37,.92)')
        ctx.fillStyle=grad; ctx.fill(); ctx.shadowBlur=0
        ctx.strokeStyle=color(colorSet[chip.hue],.54); ctx.lineWidth=.85; ctx.stroke()
        // Small dimensional inset and a meaningful label, rather than an empty glowing dot.
        roundedRect(x+4*p.scale,y+5*p.scale,16*p.scale,16*p.scale,4*p.scale)
        ctx.fillStyle=color(colorSet[chip.hue],.18); ctx.fill()
        ctx.strokeStyle=color(colorSet[chip.hue],.38); ctx.stroke()
        ctx.fillStyle=color(colorSet[chip.hue],.98); ctx.font=`600 ${8*p.scale}px ui-monospace, SFMono-Regular, monospace`; ctx.textAlign='center'; ctx.textBaseline='middle'
        ctx.fillText(chip.short,x+12*p.scale,y+13*p.scale)
        ctx.fillStyle='rgba(246,240,255,.95)'; ctx.font=`600 ${6.4*p.scale}px ui-monospace, SFMono-Regular, monospace`; ctx.textAlign='left'
        ctx.fillText(chip.label,x+24*p.scale,y+14*p.scale)
        ctx.restore()
      }
      chipPositions.filter(c => c.p.z < 0).forEach(drawChip)

      // Rotating low-poly crystal (icosahedron), with face shading from a fixed key light.
      const rotated = vertices.map(v => rotate(v,ax,ay,az))
      const faceData = faces.map((f,i) => {
        const vs = f.map(ix => rotated[ix])
        const avg = vs.reduce((a,v) => a+v[2],0)/3
        const ux=vs[1][0]-vs[0][0], uy=vs[1][1]-vs[0][1], uz=vs[1][2]-vs[0][2]
        const vx=vs[2][0]-vs[0][0], vy=vs[2][1]-vs[0][1], vz=vs[2][2]-vs[0][2]
        let nx=uy*vz-uz*vy, ny=uz*vx-ux*vz, nz=ux*vy-uy*vx
        const nn=Math.hypot(nx,ny,nz)||1; nx/=nn; ny/=nn; nz/=nn
        const light=Math.max(0,nx*(-.46)+ny*(-.65)+nz*.61)
        return { f,i,vs,avg,light,nz }
      }).sort((a,b)=>a.avg-b.avg)
      faceData.forEach(face => {
        const ps=face.vs.map(v=>project(v,cx,cy))
        ctx.beginPath(); ctx.moveTo(ps[0].x,ps[0].y); ctx.lineTo(ps[1].x,ps[1].y); ctx.lineTo(ps[2].x,ps[2].y); ctx.closePath()
        const select = (face.i % 5 === 0) ? colorSet[0] : (face.i % 3 === 0 ? colorSet[2] : colorSet[1])
        const alpha = .28 + face.light*.32 + Math.max(0,face.nz)*.12
        ctx.fillStyle=color(select,alpha); ctx.fill()
        ctx.strokeStyle=`rgba(224,213,255,${.19+face.light*.31})`; ctx.lineWidth=.85; ctx.stroke()
        // A light-catching bevel on selected edges is a stable geometry highlight, not a pulse.
        if (face.light > .68) { ctx.beginPath(); ctx.moveTo(ps[0].x,ps[0].y); ctx.lineTo(ps[1].x,ps[1].y); ctx.strokeStyle=`rgba(239,255,202,${.16+face.light*.24})`; ctx.lineWidth=1.35; ctx.stroke() }
      })

      // A rotating, offset wire-ring passes across the crystal in genuine perspective.
      for (let ring=0;ring<2;ring++) {
        ctx.beginPath()
        for(let i=0;i<=130;i++) {
          const a=i/130*Math.PI*2
          const v=ring===0 ? rotate([Math.cos(a)*78, Math.sin(a)*78, 0], .95, time*.34, .36) : rotate([Math.cos(a)*88, Math.sin(a)*29, 0], .28, -.78, -time*.20)
          const p=project(v,cx,cy)
          if(i===0) ctx.moveTo(p.x,p.y); else ctx.lineTo(p.x,p.y)
        }
        ctx.strokeStyle=ring===0?color(colorSet[0],.6):color(colorSet[2],.47); ctx.lineWidth=ring===0?1.1:.85; ctx.stroke()
      }

      // A floating central glass seal, front-facing by design so the brand remains readable.
      ctx.save(); ctx.translate(cx,cy); ctx.rotate(Math.sin(time*.23)*.09)
      ctx.beginPath(); ctx.moveTo(0,-19); ctx.lineTo(15,-13); ctx.lineTo(13,6); ctx.lineTo(0,18); ctx.lineTo(-13,6); ctx.lineTo(-15,-13); ctx.closePath()
      const seal=ctx.createLinearGradient(-15,-16,16,16); seal.addColorStop(0,color(colorSet[0],.42)); seal.addColorStop(.45,color(colorSet[1],.26)); seal.addColorStop(1,color(colorSet[2],.22))
      ctx.fillStyle=seal; ctx.fill(); ctx.strokeStyle='rgba(250,255,226,.88)'; ctx.lineWidth=1.2; ctx.stroke()
      ctx.beginPath(); ctx.moveTo(-6,0); ctx.lineTo(-1,6); ctx.lineTo(8,-5); ctx.strokeStyle='#f1ffd1'; ctx.lineWidth=2; ctx.lineCap='round'; ctx.lineJoin='round'; ctx.stroke()
      ctx.restore()

      chipPositions.filter(c => c.p.z >= 0).forEach(drawChip)
      documentPositions.filter(d=>d.z>=0).forEach(d=>drawDocumentNode(d.node,time,cx,cy))

      // Small HUD labels and scale ticks establish this as an inspectable system graphic.
      ctx.textAlign='left'; ctx.textBaseline='alphabetic'; ctx.font='600 7px ui-monospace, SFMono-Regular, monospace'; ctx.fillStyle='rgba(217,205,244,.79)'
      ctx.fillText('RULE GRAPH',12,17)
      ctx.fillStyle=color(colorSet[0],.86); ctx.fillText(String(score).padStart(2,'0')+'% INTEGRITY',12,229)
      ctx.strokeStyle='rgba(225,213,255,.19)'; ctx.lineWidth=.7
      ctx.beginPath(); ctx.moveTo(12,24); ctx.lineTo(98,24); ctx.moveTo(260,18); ctx.lineTo(347,18); ctx.moveTo(12,216); ctx.lineTo(66,216); ctx.moveTo(299,221); ctx.lineTo(347,221); ctx.stroke()
    }

    const onPointerMove = (event: PointerEvent) => {
      const r = host.getBoundingClientRect()
      pointerX = ((event.clientX-r.left)/Math.max(1,r.width)-.5)*2
      pointerY = ((event.clientY-r.top)/Math.max(1,r.height)-.5)*2
    }
    const onPointerLeave = () => { pointerX *= .1; pointerY *= .1 }
    const onResize = () => {
      sizeCanvas()
      if (reducedMotion.matches) {
        if (raf) window.cancelAnimationFrame(raf)
        raf = window.requestAnimationFrame(draw)
      }
    }
    const onMotionPreferenceChange = () => {
      if (raf) window.cancelAnimationFrame(raf)
      raf = window.requestAnimationFrame(draw)
    }
    sizeCanvas()
    host.addEventListener('pointermove',onPointerMove)
    host.addEventListener('pointerleave',onPointerLeave)
    reducedMotion.addEventListener('change', onMotionPreferenceChange)
    const observer = new ResizeObserver(onResize); observer.observe(host)
    raf = window.requestAnimationFrame(draw)
    return () => {
      if (raf) window.cancelAnimationFrame(raf)
      observer.disconnect()
      themeObserver.disconnect()
      reducedMotion.removeEventListener('change', onMotionPreferenceChange)
      host.removeEventListener('pointermove',onPointerMove)
      host.removeEventListener('pointerleave',onPointerLeave)
    }
  }, [score, motionLevel])

  return <div ref={hostRef} className="governance-scene3d" aria-hidden="true"><canvas ref={canvasRef} className="governance-scene3d-canvas" /><div className="scene-depth-caption"><span>LIVE GUIDELINE GRAPH</span></div></div>
}
