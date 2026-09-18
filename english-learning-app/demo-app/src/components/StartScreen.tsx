import { useState } from 'react'
import type { AgeRange, QuestionFilter, SessionSetup } from '../demo/usePresetSession'
import { readSavedSetup } from '../demo/usePresetSession'

interface Props {
  onStart: (setup: SessionSetup) => void
}

// 年龄只做选项（v0.3.2 起不再渲染小字说明，sub 仅保留作文档参考，不参与评分逻辑）
const AGES: Array<{ value: AgeRange; title: string }> = [
  { value: '10-12', title: 'Ages 10-12' },
  { value: '13-15', title: 'Ages 13-15' },
  { value: '16-18', title: 'Ages 16-18' },
]

// 小字说明只在题型下保留（用户确认）
const FILTERS: Array<{ value: QuestionFilter; title: string; sub: string }> = [
  { value: 'groundedOnly', title: 'Picture-only', sub: 'Only questions about things visible in the picture. Faster, no photo upload.' },
  { value: 'all', title: 'Beyond-picture too', sub: 'Also asks about your ideas and experiences. Some questions upload the photo.' },
]

// 内联 SVG logo：对话气泡 + 笑脸，配色与 level-badge 同系（#e0f2fe/#0369a1），无外部资源
function HeroLogo() {
  return (
    <svg className="hero-logo" viewBox="0 0 64 64" role="img" aria-label="Chat With Me logo">
      <rect x="4" y="8" width="44" height="34" rx="12" fill="#ffffff" opacity="0.95" />
      <path d="M16 42 L12 52 L24 43 Z" fill="#ffffff" opacity="0.95" />
      <circle cx="20" cy="24" r="3" fill="#0369a1" />
      <circle cx="32" cy="24" r="3" fill="#0369a1" />
      <path d="M20 31 Q26 36 32 31" stroke="#0369a1" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      <rect x="36" y="26" width="24" height="22" rx="11" fill="#e0f2fe" stroke="#ffffff" strokeWidth="2" />
      <path d="M44 41 L42 47 L49 42 Z" fill="#e0f2fe" />
      <circle cx="44" cy="35" r="1.8" fill="#0369a1" />
      <circle cx="50" cy="35" r="1.8" fill="#0369a1" />
    </svg>
  )
}

export function StartScreen({ onStart }: Props) {
  const saved = readSavedSetup()
  const [age, setAge] = useState<AgeRange>(saved?.ageRange ?? '13-15')
  const [filter, setFilter] = useState<QuestionFilter>(saved?.filter ?? 'all')

  return (
    <div className="start-screen">
      {/* 活泼 Hero：渐变横幅 + Logo + Title，与问题页蓝系保持一致 */}
      <div className="start-hero">
        <HeroLogo />
        <div className="hero-text">
          <h2 className="hero-title">Chat With Me!</h2>
          <p className="hero-sub">看图聊英语 · 说出你看到的世界</p>
        </div>
      </div>

      {/* 三步玩法说明 */}
      <div className="how3" aria-label="How it works">
        <span className="how3-item">👀 Look</span>
        <span className="how3-arrow">→</span>
        <span className="how3-item">🎤 Say</span>
        <span className="how3-arrow">→</span>
        <span className="how3-item">⭐ Score</span>
      </div>

      <h2 className="start-title">Before we start…</h2>

      <section className="start-group">
        <h3 className="start-group-title">How old is the student?</h3>
        <div className="pill-row" role="radiogroup" aria-label="Student age range">
          {AGES.map((a) => (
            <button
              key={a.value}
              type="button"
              role="radio"
              aria-checked={age === a.value}
              className={`pill-btn ${age === a.value ? 'selected' : ''}`}
              onClick={() => setAge(a.value)}
            >
              {a.title}
            </button>
          ))}
        </div>
      </section>

      <section className="start-group">
        <h3 className="start-group-title">Which questions can appear?</h3>
        <div className="filter-row" role="radiogroup" aria-label="Question type">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="radio"
              aria-checked={filter === f.value}
              className={`filter-btn ${filter === f.value ? 'selected' : ''}`}
              onClick={() => setFilter(f.value)}
            >
              <span className="option-title">{f.title}</span>
              <span className="option-sub">{f.sub}</span>
            </button>
          ))}
        </div>
      </section>

      <button type="button" className="submit-btn start-btn" onClick={() => onStart({ ageRange: age, filter })}>
        Start / 开始
      </button>
    </div>
  )
}
