import { useMemo, useState } from 'react'
import type { PresetEvaluationResult } from '../demo/sceneEvaluator'
import type { SceneQuestion } from '../demo/usePresetSession'

interface Props {
  questions: SceneQuestion[]
  results: PresetEvaluationResult[]
  onRestart: () => void
  onBackToStart: () => void
}

const ATTENTION_THRESHOLD = 60
const PAGE_SIZE = 2

function ScoreBadge({ value, suffix }: { value: number | null; suffix?: string }) {
  if (value === null || value === undefined) return <span className="score-badge na">{suffix ?? '—'}</span>
  const cls = value >= 80 ? 'high' : value >= 60 ? 'mid' : 'low'
  return <span className={`score-badge ${cls}`}>{value}</span>
}

// v0.3.0 本地轻量汇总：零额外 LLM；平均分 + 各题分表 + Needs attention 表格（弱项分页）
export function SummaryScreen({ questions, results, onRestart, onBackToStart }: Props) {
  const [page, setPage] = useState(0)

  const { average, ratedCount, total, attention } = useMemo(() => {
    const byId = new Map(results.map((r) => [r.questionId, r]))
    const orderedQs = questions.length > 0 ? questions : results.map((r) => ({ id: r.questionId, text: r.questionText, order: 0 }) as SceneQuestion)
    const valid = results.filter((r) => r.result && r.result.scores.overall !== null)
    const overalls = valid.map((r) => r.result!.scores.overall as number)
    const avg = overalls.length ? Math.round(overalls.reduce((a, b) => a + b, 0) / overalls.length) : null
    const att = orderedQs
      .map((q, i) => ({ q, i, r: byId.get(q.id) ?? null }))
      .filter(({ r }) => !r || !r.result || r.result.scores.overall === null || (r.result.scores.overall as number) < ATTENTION_THRESHOLD)
    return { average: avg, ratedCount: valid.length, total: orderedQs.length, attention: att }
  }, [questions, results])

  const pageCount = Math.max(1, Math.ceil(attention.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const pageItems = attention.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)
  const avgCls = average !== null && average >= 80 ? 'high' : average !== null && average >= 60 ? 'mid' : 'low'

  return (
    <div className="report-screen">
      <div className="composite-section">
        <h2>综合成绩 / Overall</h2>
        <div className="overall-wrap">
          <div className={`overall-score ${avgCls}`}>{average ?? '—'}</div>
          <span className="overall-label">/ 100</span>
          <span className="rated-hint">已评分 {ratedCount}/{total}</span>
        </div>

        <div className="result-block">
          <h3>各题得分 / Scores</h3>
          <div className="summary-table-wrap">
            <table className="summary-table">
              <thead>
                <tr><th>#</th><th>Question</th><th>Score</th></tr>
              </thead>
              <tbody>
                {questions.map((q, i) => {
                  const r = results.find((x) => x.questionId === q.id) ?? null
                  const skipped = r && !r.result && r.error?.includes('Skipped')
                  return (
                    <tr key={q.id}>
                      <td>Q{i + 1}</td>
                      <td title={q.text}>{q.text.length > 60 ? `${q.text.slice(0, 60)}…` : q.text}</td>
                      <td>{skipped ? <span className="score-badge na">Skip</span> : <ScoreBadge value={r?.result?.scores.overall ?? null} suffix={r ? 'Fail' : '—'} />}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {attention.length > 0 && (
          <div className="result-block weaknesses-block">
            <h3>特别提醒 / Needs attention ({attention.length})</h3>
            {pageItems.map(({ q, i, r }) => (
              <div key={q.id} className="attention-card">
                <p className="comment-en"><strong>Q{i + 1}</strong> · {q.text}</p>
                {r?.answer && <p className="preview-answer" style={{ whiteSpace: 'normal' }}>你的回答：{r.answer}</p>}
                {r?.result ? (
                  <>
                    <p className="comment-en weakness-text">{r.result.weaknesses || '—'}</p>
                    {r.result.weaknessesZh && <p className="comment-zh">{r.result.weaknessesZh}</p>}
                    <p className="comment-en" style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>{r.result.suggestions || ''}</p>
                    {r.result.suggestionsZh && <p className="comment-zh" style={{ whiteSpace: 'pre-wrap' }}>{r.result.suggestionsZh}</p>}
                  </>
                ) : (
                  <p className="comment-en">{r?.error ?? '暂无评分'}</p>
                )}
              </div>
            ))}
            {pageCount > 1 && (
              <div className="pagination-row">
                <button type="button" className="secondary-btn small" disabled={safePage === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>上一页 / Prev</button>
                <span className="pagination-hint">Page {safePage + 1} of {pageCount}</span>
                <button type="button" className="secondary-btn small" disabled={safePage >= pageCount - 1} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>下一页 / Next</button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="result-actions" style={{ marginTop: 16 }}>
        <button type="button" className="secondary-btn" onClick={onRestart}>再来一次 / Restart</button>
        <button type="button" className="secondary-btn" onClick={onBackToStart}>返回开始页 / Start over</button>
      </div>
    </div>
  )
}
