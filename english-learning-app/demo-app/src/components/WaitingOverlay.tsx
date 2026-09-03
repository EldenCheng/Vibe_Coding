import { useEffect, useRef, useState } from 'react'

const MESSAGES = [
  '老师正在认真听你的回答... / Teacher is listening...',
  '正在分析发音与语法... / Analyzing pronunciation...',
  '正在给你的回答打分... / Scoring your answer...',
  '马上就好，别走开... / Almost there...',
]

// 简单水果掉落 Canvas 小游戏 — 更宽容的点击判定
export function WaitingOverlay({ provider }: { provider?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const scoreRef = useRef(0)
  const [score, setScore] = useState(0)
  const [msgIdx, setMsgIdx] = useState(0)

  useEffect(() => {
    const t = setInterval(() => setMsgIdx((i) => (i + 1) % MESSAGES.length), 2000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const emojis = ['🍎', '🍊', '🍌', '🍉', '🍇']
    type Fruit = {
      x: number
      y: number
      cx: number
      cy: number
      vx: number
      vy: number
      emoji: string
      size: number // 字号（像素）
      hitRadius: number
    }
    const fruits: Fruit[] = []

    const spawn = () => {
      const rect = canvas.getBoundingClientRect()
      const size = 26 + Math.random() * 14 // 26-40px，更大更易点
      const hitRadius = size * 0.75 // 更宽容：半径为 75% 字号
      const x = Math.random() * (rect.width - size)
      const y = -size
      fruits.push({
        x,
        y,
        cx: x + size / 2,
        cy: y + size / 2,
        vx: (Math.random() - 0.5) * 1.1,
        vy: 1 + Math.random() * 1.4,
        emoji: emojis[Math.floor(Math.random() * emojis.length)],
        size,
        hitRadius,
      })
    }

    let spawnTimer = 0
    let animId = 0

    const handleHit = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect()
      const x = clientX - rect.left
      const y = clientY - rect.top
      for (let i = fruits.length - 1; i >= 0; i--) {
        const f = fruits[i]
        const dx = x - f.cx
        const dy = y - f.cy
        if (Math.sqrt(dx * dx + dy * dy) < f.hitRadius) {
          fruits.splice(i, 1)
          scoreRef.current += 1
          setScore(scoreRef.current)
          break
        }
      }
    }

    const handleClick = (e: MouseEvent) => handleHit(e.clientX, e.clientY)
    const handleTouch = (e: TouchEvent) => {
      if (e.touches.length > 0) {
        e.preventDefault()
        handleHit(e.touches[0].clientX, e.touches[0].clientY)
      }
    }

    canvas.addEventListener('click', handleClick)
    canvas.addEventListener('touchstart', handleTouch, { passive: false })

    // 居中绘制确保 cx/cy 与视觉一致
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'

    const loop = () => {
      const rect = canvas.getBoundingClientRect()
      ctx.clearRect(0, 0, rect.width, rect.height)

      spawnTimer += 1
      if (spawnTimer > 24) {
        // 稍快一点更好玩
        spawnTimer = 0
        spawn()
      }

      for (let i = fruits.length - 1; i >= 0; i--) {
        const f = fruits[i]
        f.x += f.vx
        f.y += f.vy
        f.cx = f.x + f.size / 2
        f.cy = f.y + f.size / 2
        f.vy += 0.05
        ctx.font = `${f.size}px serif`
        ctx.fillText(f.emoji, f.cx, f.cy)
        if (f.cy - f.size / 2 > rect.height + 24) fruits.splice(i, 1)
      }

      animId = requestAnimationFrame(loop)
    }
    loop()

    return () => {
      window.removeEventListener('resize', resize)
      canvas.removeEventListener('click', handleClick)
      canvas.removeEventListener('touchstart', handleTouch)
      cancelAnimationFrame(animId)
    }
  }, [])

  return (
    <div className="waiting-overlay">
      <div className="waiting-card">
        <div className="spinner" aria-hidden />
        <p className="waiting-msg">{MESSAGES[msgIdx]}</p>
        <p className="waiting-sub">
          {provider === 'local' ? '本地模型约 30–40 秒 / Local model ~30–40s' : '评分通常需要 5–15 秒 / Usually 5–15s'}
        </p>
      </div>
      <div className="game-area">
        <div className="game-header">
          <span>等待小游戏：点击水果 / Tap fruits</span>
          <span className="game-score">Score: {score}</span>
        </div>
        <canvas ref={canvasRef} className="fruit-canvas" style={{ touchAction: 'none' }} />
        <p className="game-hint"> easy to tap! 点得越多越厉害，分数不影响真实评分哦</p>
      </div>
    </div>
  )
}
