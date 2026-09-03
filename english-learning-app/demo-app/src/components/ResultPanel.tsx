import { useState } from 'react'
import type { EvaluationResult } from '../scoring/parseEvaluation'

interface Props {
  question: string
  answer: string
  evaluation: EvaluationResult
  onRetry: () => void
  onNewQuestion: () => void
}

function ScoreBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="score-badge na">—</span>
  const cls = value >= 80 ? 'high' : value >= 60 ? 'mid' : 'low'
  return <span className={`score-badge ${cls}`}>{value}</span>
}

function isWeakScore(value: number | null, allScores: Array<number | null>): boolean {
  if (value === null) return false
  if (value >= 90) return false
  const min = Math.min(...allScores.filter((v): v is number => v !== null))
  return value === min || value < 90
}

function ScoreReason({
  reason,
  reasonZh,
}: {
  reason: string
  reasonZh: string
  label: string
}) {
  const [showZh, setShowZh] = useState(false)
  if (!reason && !reasonZh) return null
  return (
    <div className="reason-wrap">
      <p className="reason-text">{reason || '—'}</p>
      {reasonZh && (
        <>
          <button type="button" className="toggle-zh small" onClick={() => setShowZh((v) => !v)}>
            {showZh ? '隐藏中文 / Hide' : '显示中文 / Show 中文'}
          </button>
          {showZh && <p className="reason-text-zh">{reasonZh}</p>}
        </>
      )}
    </div>
  )
}

export function ResultPanel({ question, answer, evaluation, onRetry, onNewQuestion }: Props) {
  const [showCommentZh, setShowCommentZh] = useState(false)
  const [showStrengthsZh, setShowStrengthsZh] = useState(false)
  const [showWeaknessesZh, setShowWeaknessesZh] = useState(false)
  const [showSuggestionsZh, setShowSuggestionsZh] = useState(false)
  const { scores, comment, commentZh, strengths, strengthsZh, weaknesses, weaknessesZh, suggestions, suggestionsZh } = evaluation
  const overall = scores.overall
  const allScores = [scores.vocabulary, scores.grammar, scores.relevance]

  const speakExample = (text: string) => {
    if (!('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'en-US'
    u.rate = 0.9
    window.speechSynthesis.speak(u)
  }

  const extractExample = (s: string): string | null => {
    const m = s.match(/Example:\s*["“]([^"”]+)["”]/i) || s.match(/["“]([^"”]{8,})["”]/) || s.match(/例句[:：]\s*["“]([^"”]+)["”]/)
    return m ? m[1] : null
  }
  const exampleEn = extractExample(suggestions)
  const exampleZh = extractExample(suggestionsZh)

  const isTruncated = evaluation.truncated || allScores.some((v) => v === null)

  return (
    <div className="result-panel">
      {isTruncated && (
        <div className="banner warning" style={{ marginBottom: 12 }}>
          ⚠ 评价因模型输出过长被截断，已保留可用部分（如“{scores.vocabulary_reason.slice(0, 30)}…”）；语法/相关度待补，请点“重试评分”获取完整版 / Response truncated, retry for full report.
        </div>
      )}
      <div className="result-header">
        <h2>你的得分 / Your Score</h2>
        <div className="overall-wrap">
          <div className={`overall-score ${overall !== null && overall >= 80 ? 'high' : overall !== null && overall >= 60 ? 'mid' : 'low'}`}>
            {overall ?? '—'}
          </div>
          <span className="overall-label">/ 100</span>
        </div>
      </div>

      <div className="result-block">
        <h3>问题 / Question</h3>
        <p className="result-question">{question}</p>
        <h3>你的回答 / Your answer</h3>
        <p className="result-answer">{answer}</p>
      </div>

      <div className="result-block">
        <h3>分项得分与扣分原因 / Scores & reasons</h3>
        <div className="scores-grid">
          <div className={`score-item ${isWeakScore(scores.vocabulary, allScores) ? 'weak' : ''}`}>
            <div className="score-item-head">
              <span className="score-label">词汇 Vocabulary {isWeakScore(scores.vocabulary, allScores) && <span className="weak-tag">⚠ 失分</span>}</span>
              <ScoreBadge value={scores.vocabulary} />
            </div>
            <ScoreReason reason={scores.vocabulary_reason} reasonZh={scores.vocabulary_reason_zh} label="vocab" />
          </div>
          <div className={`score-item ${isWeakScore(scores.grammar, allScores) ? 'weak' : ''}`}>
            <div className="score-item-head">
              <span className="score-label">语法 Grammar {isWeakScore(scores.grammar, allScores) && <span className="weak-tag">⚠ 失分</span>}</span>
              <ScoreBadge value={scores.grammar} />
            </div>
            <ScoreReason reason={scores.grammar_reason} reasonZh={scores.grammar_reason_zh} label="grammar" />
          </div>
          <div className={`score-item ${isWeakScore(scores.relevance, allScores) ? 'weak' : ''}`}>
            <div className="score-item-head">
              <span className="score-label">相关度 Relevance {isWeakScore(scores.relevance, allScores) && <span className="weak-tag">⚠ 失分</span>}</span>
              <ScoreBadge value={scores.relevance} />
            </div>
            <ScoreReason reason={scores.relevance_reason} reasonZh={scores.relevance_reason_zh} label="relevance" />
          </div>
        </div>
      </div>

      <div className="result-block comment-block">
        <h3>老师点评 / Feedback</h3>
        <p className="comment-en">{comment || 'Good effort!'}</p>
        {commentZh && (
          <>
            <button type="button" className="toggle-zh" onClick={() => setShowCommentZh((v) => !v)}>
              {showCommentZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
            </button>
            {showCommentZh && <p className="comment-zh">{commentZh}</p>}
          </>
        )}
      </div>

      {(strengths || strengthsZh) && (
        <div className="result-block strengths-block">
          <h3>亮点 / Strengths</h3>
          <p className="comment-en">{strengths || '—'}</p>
          {strengthsZh && (
            <>
              <button type="button" className="toggle-zh" onClick={() => setShowStrengthsZh((v) => !v)}>
                {showStrengthsZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
              </button>
              {showStrengthsZh && <p className="comment-zh">{strengthsZh}</p>}
            </>
          )}
        </div>
      )}

      {(weaknesses || weaknessesZh) && (
        <div className="result-block weaknesses-block">
          <h3>失分项 / Issues causing deduction</h3>
          <p className="comment-en weakness-text">{weaknesses || '—'}</p>
          {weaknessesZh && (
            <>
              <button type="button" className="toggle-zh" onClick={() => setShowWeaknessesZh((v) => !v)}>
                {showWeaknessesZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
              </button>
              {showWeaknessesZh && <p className="comment-zh">{weaknessesZh}</p>}
            </>
          )}
        </div>
      )}

      {(suggestions || suggestionsZh) && (
        <div className="result-block suggestions-block">
          <h3>改进建议 / How to improve</h3>
          <p className="comment-en" style={{ whiteSpace: 'pre-wrap' }}>{suggestions || '—'}</p>
          {exampleEn && (
            <button type="button" className="toggle-zh" onClick={() => speakExample(exampleEn)} aria-label="Read example">
              🔊 朗读例句 / Read example
            </button>
          )}
          {suggestionsZh && (
            <>
              <button type="button" className="toggle-zh" onClick={() => setShowSuggestionsZh((v) => !v)}>
                {showSuggestionsZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
              </button>
              {showSuggestionsZh && <p className="comment-zh" style={{ whiteSpace: 'pre-wrap' }}>{suggestionsZh}</p>}
              {showSuggestionsZh && exampleZh && (
                <button type="button" className="toggle-zh" onClick={() => speakExample(exampleZh)}>
                  🔊 朗读例句 / Read example
                </button>
              )}
            </>
          )}
        </div>
      )}

      <div className="result-actions">
        <button type="button" className="secondary-btn" onClick={onNewQuestion}>
          再试一题 / Another question
        </button>
        <button type="button" className="secondary-btn" onClick={onRetry}>
          重试评分 / Retry scoring
        </button>
      </div>

      <details className="raw-details" open={isTruncated}>
        <summary>查看原始响应 / Raw response {isTruncated && '(已截断 truncated)'}</summary>
        <pre className="raw-pre">{evaluation.raw.slice(0, 4096)}{evaluation.raw.length > 4096 ? '\n…truncated for display' : ''}</pre>
      </details>
    </div>
  )
}
