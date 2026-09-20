// StartScreen — v0.3.4 开始页：单列居中，只留 Title / 年龄 / 题型 / CTA 四要素，其余为纯装饰
import { useState } from 'react'
import type { AgeRange, QuestionFilter, SessionSetup } from '../demo/usePresetSession'
import { readSavedSetup } from '../demo/usePresetSession'

interface Props {
  onStart: (setup: SessionSetup) => void
}

const AGES: Array<{ value: AgeRange; label: string; emoji: string }> = [
  { value: '10-12', label: 'Ages 10-12', emoji: '🧒' },
  { value: '13-15', label: 'Ages 13-15', emoji: '🧑' },
  { value: '16-18', label: 'Ages 16-18', emoji: '🧑‍🎓' },
]

const FILTERS: Array<{ value: QuestionFilter; label: string; emoji: string; sub: string }> = [
  { value: 'groundedOnly', label: 'Picture-only', emoji: '🖼️', sub: 'Only things visible in the picture. Faster, no photo upload.' },
  { value: 'all', label: 'Beyond-picture too', emoji: '💭', sub: 'Also your ideas and experiences. Some questions upload the photo.' },
]

// 内联 SVG logo：对话气泡 + 笑脸 + 挥手，无外部资源
function Mascot() {
  return (
    <svg className="mascot" viewBox="0 0 96 96" role="img" aria-label="Chat With Me mascot">
      <rect x="8" y="14" width="66" height="50" rx="18" fill="url(#mascotBubble)" />
      <path d="M26 62 L20 78 L40 64 Z" fill="#3b82f6" />
      <circle cx="33" cy="36" r="4.5" fill="#0f2f5a" />
      <circle cx="51" cy="36" r="4.5" fill="#0f2f5a" />
      <circle cx="34.5" cy="34.5" r="1.5" fill="#fff" />
      <circle cx="52.5" cy="34.5" r="1.5" fill="#fff" />
      <path d="M31 48 Q42 57 53 48" stroke="#0f2f5a" strokeWidth="3.5" strokeLinecap="round" fill="none" />
      <circle cx="24" cy="45" r="3.5" fill="#7dd3fc" opacity="0.7" />
      <circle cx="60" cy="45" r="3.5" fill="#7dd3fc" opacity="0.7" />
      <rect x="60" y="52" width="30" height="27" rx="13" fill="#e0f2fe" stroke="#ffffff" strokeWidth="2.5" />
      <path d="M68 72 L64 82 L75 74 Z" fill="#e0f2fe" />
      <text x="75" y="70" fontSize="16" textAnchor="middle">👋</text>
      <defs>
        <linearGradient id="mascotBubble" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b82f6" />
          <stop offset="1" stopColor="#06b6d4" />
        </linearGradient>
      </defs>
    </svg>
  )
}

export function StartScreen({ onStart }: Props) {
  const saved = readSavedSetup()
  const [age, setAge] = useState<AgeRange>(saved?.ageRange ?? '13-15')
  const [filter, setFilter] = useState<QuestionFilter>(saved?.filter ?? 'all')

  return (
    <div className="start-screen">
      {/* 环境装饰：柔光色块 + 漂浮表情芯片（Look/Say/Score 的氛围化表达） */}
      <div className="start-bg" aria-hidden="true">
        <span className="blob blob-a" />
        <span className="blob blob-b" />
        <span className="blob blob-c" />
        <span className="float-chip chip-1">👀</span>
        <span className="float-chip chip-2">🎤</span>
        <span className="float-chip chip-3">⭐</span>
        <span className="float-chip chip-4">💬</span>
      </div>

      <div className="start-inner">
        <header className="start-hero">
          <div className="mascot-wrap">
            <Mascot />
            <span className="mascot-bubble">Hi! 今天一起说英语 👋</span>
          </div>
          <h1 className="start-title">Chat With Me!</h1>
          <p className="start-tagline">看图聊英语 · 说出你看到的世界</p>
        </header>

        <section className="start-group">
          <h2 className="start-label">学生年龄 · Age</h2>
          <div className="age-seg" role="radiogroup" aria-label="Student age range">
            {AGES.map((a) => (
              <button
                key={a.value}
                type="button"
                role="radio"
                aria-checked={age === a.value}
                className={`age-seg-btn ${age === a.value ? 'is-on' : ''}`}
                onClick={() => setAge(a.value)}
              >
                <span className="age-seg-emoji" aria-hidden="true">{a.emoji}</span>
                <span className="age-seg-label">{a.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="start-group">
          <h2 className="start-label">题型 · Question types</h2>
          <div className="mode-row" role="radiogroup" aria-label="Question type">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                role="radio"
                aria-checked={filter === f.value}
                className={`mode-card ${filter === f.value ? 'is-on' : ''}`}
                onClick={() => setFilter(f.value)}
              >
                <span className="mode-check" aria-hidden="true">✓</span>
                <span className="mode-head">
                  <span className="mode-emoji" aria-hidden="true">{f.emoji}</span>
                  <span className="mode-label">{f.label}</span>
                </span>
                <span className="mode-sub">{f.sub}</span>
              </button>
            ))}
          </div>
        </section>

        <button type="button" className="start-cta" onClick={() => onStart({ ageRange: age, filter })}>
          开始对话 · Let's Go
          <span className="start-cta-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}
