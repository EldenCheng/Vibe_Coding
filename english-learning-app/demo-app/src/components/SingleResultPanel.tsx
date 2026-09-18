import { useState } from 'react'
import type { PresetEvaluationResult } from '../demo/sceneEvaluator'

interface Props {
  result: PresetEvaluationResult | null
  submitting: boolean
  isLastQuestion: boolean
  errorMessage: string | null
  onRetry: () => void
  onSkip: () => void
  onNext: () => void
  onSummary: () => void
}

function ScoreBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="score-badge na">—</span>
  const cls = value >= 80 ? 'high' : value >= 60 ? 'mid' : 'low'
  return <span className={`score-badge ${cls}`}>{value}</span>
}

function ZhToggle({ zh, label }: { zh: string; label: string }) {
  const [show, setShow] = useState(false)
  if (!zh) return null
  return (
    <>
      <button type="button" className="toggle-zh" onClick={() => setShow((v) => !v)}>
        {show ? '隐藏中文 / Hide 中文' : `${label} / Show 中文`}
      </button>
      {show && <p className="comment-zh">{zh}</p>}
    </>
  )
}

// v0.3.0 逐题同页出分：分数头常显，详细评价默认折叠，点击展开
export function SingleResultPanel({ result, submitting, isLastQuestion, errorMessage, onRetry, onSkip, onNext, onSummary }: Props) {
  const [open, setOpen] = useState(false)

  if (submitting) {
    return (
      <div className="result-panel">
        <div className="loading-screen">
          <div className="spinner large" />
          <p>Scoring… / 评分中…</p>
        </div>
      </div>
    )
  }

  // 失败态：停在原题，只能重试/跳过
  if (!result || !result.result) {
    return (
      <div className="result-panel">
        <div className="banner warning">
          <div>{errorMessage ?? result?.error ?? '评分失败，可重试或跳过 / Scoring failed, retry or skip.'}</div>
          {result?.error && result.error !== errorMessage && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12 }}>查看错误详情 / Error details</summary>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 11, margin: '6px 0 0' }}>{result.error}</pre>
            </details>
          )}
        </div>
        <div className="result-actions">
          <button type="button" className="secondary-btn" onClick={onRetry}>重试评分 / Retry</button>
          <button type="button" className="secondary-btn" onClick={onSkip}>跳过本题 / Skip</button>
        </div>
      </div>
    )
  }

  const ev = result.result
  const scores = ev.scores

  return (
    <div className="result-panel">
      <div className="result-header">
        <h2>你的得分 / Your Score</h2>
        <div className="overall-wrap">
          <div className={`overall-score ${scores.overall !== null && scores.overall >= 80 ? 'high' : scores.overall !== null && scores.overall >= 60 ? 'mid' : 'low'}`}>
            {scores.overall ?? '—'}
          </div>
          <span className="overall-label">/ 100</span>
        </div>
        <div className="accordion-dims" style={{ justifyContent: 'center', marginTop: 6 }}>
          V<ScoreBadge value={scores.vocabulary} /> G<ScoreBadge value={scores.grammar} /> R<ScoreBadge value={scores.relevance} />
        </div>
      </div>

      <div className="result-block">
        <h3>你的回答 / Your answer</h3>
        <p className="result-answer">{result.answer}</p>
      </div>

      <button type="button" className="secondary-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? '收起详细评价 / Hide details ▴' : '查看详细评价 / Show details ▾'}
      </button>

      {open && (
        <div className="accordion-body" style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}>
          <div className="result-block">
            <h3>分项扣分原因 / Why points were lost</h3>
            <p className="reason-text">V: {scores.vocabulary_reason || '—'}</p>
            {scores.vocabulary_reason_zh && <p className="reason-text-zh">{scores.vocabulary_reason_zh}</p>}
            <p className="reason-text" style={{ marginTop: 6 }}>G: {scores.grammar_reason || '—'}</p>
            {scores.grammar_reason_zh && <p className="reason-text-zh">{scores.grammar_reason_zh}</p>}
            <p className="reason-text" style={{ marginTop: 6 }}>R: {scores.relevance_reason || '—'}</p>
            {scores.relevance_reason_zh && <p className="reason-text-zh">{scores.relevance_reason_zh}</p>}
          </div>
          <div className="result-block comment-block">
            <h3>老师点评 / Feedback</h3>
            <p className="comment-en">{ev.comment || 'Good effort!'}</p>
            <ZhToggle zh={ev.commentZh} label="显示中文翻译" />
          </div>
          {(ev.strengths || ev.strengthsZh) && (
            <div className="result-block strengths-block">
              <h3>亮点 / Strengths</h3>
              <p className="comment-en">{ev.strengths || '—'}</p>
              <ZhToggle zh={ev.strengthsZh} label="显示中文翻译" />
            </div>
          )}
          {(ev.weaknesses || ev.weaknessesZh) && (
            <div className="result-block weaknesses-block">
              <h3>失分项 / Issues</h3>
              <p className="comment-en weakness-text">{ev.weaknesses || '—'}</p>
              <ZhToggle zh={ev.weaknessesZh} label="显示中文翻译" />
            </div>
          )}
          {(ev.suggestions || ev.suggestionsZh) && (
            <div className="result-block suggestions-block">
              <h3>改进建议 / How to improve</h3>
              <p className="comment-en" style={{ whiteSpace: 'pre-wrap' }}>{ev.suggestions || '—'}</p>
              <ZhToggle zh={ev.suggestionsZh} label="显示中文翻译" />
            </div>
          )}
        </div>
      )}

      <div className="result-actions">
        {isLastQuestion ? (
          <button type="button" className="submit-btn" onClick={onSummary}>查看汇总 / Summary</button>
        ) : (
          <button type="button" className="submit-btn" onClick={onNext}>下一题 / Next</button>
        )}
      </div>
    </div>
  )
}
