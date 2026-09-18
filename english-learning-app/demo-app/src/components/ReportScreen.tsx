// ReportScreen — 多题 C1 折叠 + 本地综合 + 整批重试 + 日志下载（§9.1）
// 顶部综合为本地拼接（零额外 LLM），每题折叠头部即见分数，详情层懒展开

import { useMemo, useState } from 'react'
import type { PresetEvaluationResult } from '../demo/sceneEvaluator'
import { modelLogger } from '../utils/modelLogger'

interface Props {
  results: PresetEvaluationResult[]
  onRetrySingle: (questionId: string) => void
  onRestart: () => void
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

// 本地综合计算
function useComposite(results: PresetEvaluationResult[]) {
  return useMemo(() => {
    const valid = results.filter((r) => r.result && r.result.scores.overall !== null)
    const overalls = valid.map((r) => r.result!.scores.overall as number)
    const composite = overalls.length ? Math.round(overalls.reduce((a, b) => a + b, 0) / overalls.length) : null
    const ratedCount = valid.length
    const total = results.length

    // 评语拼接：comment 取最高分题，strengths 取最高分题，weaknesses 汇总最弱 1-2 维度
    let comment: string | null = null
    let commentZh: string | null = null
    let strengths: string | null = null
    let strengthsZh: string | null = null
    let weaknessesList: string[] = []
    let weaknessesZhList: string[] = []

    if (valid.length) {
      const best = [...valid].sort((a, b) => (b.result!.scores.overall as number) - (a.result!.scores.overall as number))[0]
      comment = best.result!.comment || null
      commentZh = best.result!.commentZh || null
      strengths = best.result!.strengths || null
      strengthsZh = best.result!.strengthsZh || null

      // 收集最弱维度（按分数升序取 2）
      const dimScores: Array<{ dim: string; score: number; reason: string; reasonZh: string }> = []
      for (const r of valid) {
        const s = r.result!.scores
        if (s.vocabulary !== null) dimScores.push({ dim: 'Vocabulary', score: s.vocabulary, reason: s.vocabulary_reason, reasonZh: s.vocabulary_reason_zh })
        if (s.grammar !== null) dimScores.push({ dim: 'Grammar', score: s.grammar, reason: s.grammar_reason, reasonZh: s.grammar_reason_zh })
        if (s.relevance !== null) dimScores.push({ dim: 'Relevance', score: s.relevance, reason: s.relevance_reason, reasonZh: s.relevance_reason_zh })
      }
      dimScores.sort((a, b) => a.score - b.score)
      const weakest = dimScores.slice(0, 2)
      weaknessesList = weakest.map((w) => `${w.dim} ${w.score}: ${w.reason || '—'}`)
      weaknessesZhList = weakest.map((w) => `${w.dim} ${w.score}: ${w.reasonZh || w.reason || '—'}`)
      // 若 valid 有 weaknesses，也可追加一句
      if (weakest.length === 0 && best.result!.weaknesses) {
        weaknessesList = [best.result!.weaknesses]
        weaknessesZhList = best.result!.weaknessesZh ? [best.result!.weaknessesZh] : []
      }
    }

    return { composite, ratedCount, total, comment, commentZh, strengths, strengthsZh, weaknessesList, weaknessesZhList }
  }, [results])
}

function QuestionCard({
  result,
  index,
  defaultOpen,
  onRetrySingle,
}: {
  result: PresetEvaluationResult
  index: number
  defaultOpen: boolean
  onRetrySingle: (id: string) => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [showCommentZh, setShowCommentZh] = useState(false)
  const [showStrengthsZh, setShowStrengthsZh] = useState(false)
  const [showWeaknessesZh, setShowWeaknessesZh] = useState(false)
  const [showSuggestionsZh, setShowSuggestionsZh] = useState(false)
  const [retrying, setRetrying] = useState(false)

  const ev = result.result
  const scores = ev?.scores ?? null
  const allScores = scores ? [scores.vocabulary, scores.grammar, scores.relevance] : []
  const isTruncated = ev?.truncated || (scores && allScores.some((v) => v === null))
  const needRetry = result.timedOut || !ev

  const handleRetry = async () => {
    setRetrying(true)
    try {
      await onRetrySingle(result.questionId)
    } finally {
      setRetrying(false)
    }
  }

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

  const exampleEn = ev ? extractExample(ev.suggestions) : null
  // const exampleZh = ev ? extractExample(ev.suggestionsZh) : null

  return (
    <div className={`accordion-card ${needRetry ? 'needs-retry' : ''}`}>
      <button type="button" className="accordion-header" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="accordion-title">
          <span className="accordion-qindex">Q{index + 1}</span>
          <span className="accordion-qtext" title={result.questionText}>
            {result.questionText}
          </span>
        </span>
        <span className="accordion-scores">
          {scores ? (
            <>
              <span className="accordion-overall">
                <ScoreBadge value={scores.overall} />
              </span>
              <span className="accordion-dims">
                V<ScoreBadge value={scores.vocabulary} /> G<ScoreBadge value={scores.grammar} /> R<ScoreBadge value={scores.relevance} />
              </span>
            </>
          ) : (
            <span className="score-badge na">—</span>
          )}
          <span className="accordion-chevron">{open ? '▴' : '▾'}</span>
        </span>
      </button>

      {needRetry && (
        <div className="banner warning" style={{ margin: '8px 12px 0' }}>
          <div>
            {result.timedOut
              ? result.errorKind === 'timeout'
                ? '该批次评分超时（Gemini 90s / Local 150s），已保留作答；可整批重试。'
                : result.errorKind === 'api'
                  ? '该批次因大模型 API 错误未评分（可能是 429 限流/404 模型名），已保留作答；可整批重试。'
                  : '该批次评分失败，已保留作答；可整批重试。'
              : '该题暂无评分。'}
          </div>
          {result.error && (
            <details style={{ marginTop: 6 }} open={result.errorKind !== 'timeout'}>
              <summary style={{ cursor: 'pointer', fontSize: 12 }}>
                查看错误详情 / Error details [{result.errorKind}]
              </summary>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 11, margin: '6px 0 0', maxHeight: 200, overflow: 'auto' }}>
                {result.error}
              </pre>
            </details>
          )}
        </div>
      )}
      {isTruncated && !needRetry && (
        <div className="banner warning" style={{ margin: '8px 12px 0', fontSize: 12 }}>
          ⚠ 该题评价因输出过长被截断，已保留可用部分；可单题重试获取完整版。
        </div>
      )}

      {!open && (
        <div className="accordion-preview">
          <span className="preview-answer" title={result.answer}>
            你的回答：{result.answer.slice(0, 80)}
            {result.answer.length > 80 ? '…' : ''}
          </span>
          <button type="button" className="toggle-zh small" onClick={() => setOpen(true)}>
            查看详细评价 ▸
          </button>
        </div>
      )}

      {open && (
        <div className="accordion-body">
          <div className="result-block">
            <h3>你的回答 / Your answer</h3>
            <p className="result-answer">{result.answer}</p>
          </div>

          {ev ? (
            <>
              <div className="result-block">
                <h3>分项得分与扣分原因 / Scores & reasons</h3>
                <div className="scores-grid">
                  <div className={`score-item ${isWeakScore(scores!.vocabulary, allScores) ? 'weak' : ''}`}>
                    <div className="score-item-head">
                      <span className="score-label">
                        词汇 Vocabulary {isWeakScore(scores!.vocabulary, allScores) && <span className="weak-tag">⚠ 失分</span>}
                      </span>
                      <ScoreBadge value={scores!.vocabulary} />
                    </div>
                    <ScoreReason reason={scores!.vocabulary_reason} reasonZh={scores!.vocabulary_reason_zh} />
                  </div>
                  <div className={`score-item ${isWeakScore(scores!.grammar, allScores) ? 'weak' : ''}`}>
                    <div className="score-item-head">
                      <span className="score-label">
                        语法 Grammar {isWeakScore(scores!.grammar, allScores) && <span className="weak-tag">⚠ 失分</span>}
                      </span>
                      <ScoreBadge value={scores!.grammar} />
                    </div>
                    <ScoreReason reason={scores!.grammar_reason} reasonZh={scores!.grammar_reason_zh} />
                  </div>
                  <div className={`score-item ${isWeakScore(scores!.relevance, allScores) ? 'weak' : ''}`}>
                    <div className="score-item-head">
                      <span className="score-label">
                        相关度 Relevance {isWeakScore(scores!.relevance, allScores) && <span className="weak-tag">⚠ 失分</span>}
                      </span>
                      <ScoreBadge value={scores!.relevance} />
                    </div>
                    <ScoreReason reason={scores!.relevance_reason} reasonZh={scores!.relevance_reason_zh} />
                  </div>
                </div>
              </div>

              <div className="result-block comment-block">
                <h3>老师点评 / Feedback</h3>
                <p className="comment-en">{ev.comment || 'Good effort!'}</p>
                {ev.commentZh && (
                  <>
                    <button type="button" className="toggle-zh" onClick={() => setShowCommentZh((v) => !v)}>
                      {showCommentZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
                    </button>
                    {showCommentZh && <p className="comment-zh">{ev.commentZh}</p>}
                  </>
                )}
              </div>

              {(ev.strengths || ev.strengthsZh) && (
                <div className="result-block strengths-block">
                  <h3>亮点 / Strengths</h3>
                  <p className="comment-en">{ev.strengths || '—'}</p>
                  {ev.strengthsZh && (
                    <>
                      <button type="button" className="toggle-zh" onClick={() => setShowStrengthsZh((v) => !v)}>
                        {showStrengthsZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
                      </button>
                      {showStrengthsZh && <p className="comment-zh">{ev.strengthsZh}</p>}
                    </>
                  )}
                </div>
              )}

              {(ev.weaknesses || ev.weaknessesZh) && (
                <div className="result-block weaknesses-block">
                  <h3>失分项 / Issues</h3>
                  <p className="comment-en weakness-text">{ev.weaknesses || '—'}</p>
                  {ev.weaknessesZh && (
                    <>
                      <button type="button" className="toggle-zh" onClick={() => setShowWeaknessesZh((v) => !v)}>
                        {showWeaknessesZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
                      </button>
                      {showWeaknessesZh && <p className="comment-zh">{ev.weaknessesZh}</p>}
                    </>
                  )}
                </div>
              )}

              {(ev.suggestions || ev.suggestionsZh) && (
                <div className="result-block suggestions-block">
                  <h3>改进建议 / How to improve</h3>
                  <p className="comment-en" style={{ whiteSpace: 'pre-wrap' }}>
                    {ev.suggestions || '—'}
                  </p>
                  {exampleEn && (
                    <button type="button" className="toggle-zh" onClick={() => speakExample(exampleEn)}>
                      🔊 朗读例句 / Read example
                    </button>
                  )}
                  {ev.suggestionsZh && (
                    <>
                      <button type="button" className="toggle-zh" onClick={() => setShowSuggestionsZh((v) => !v)}>
                        {showSuggestionsZh ? '隐藏中文 / Hide 中文' : '显示中文翻译 / Show 中文'}
                      </button>
                      {showSuggestionsZh && <p className="comment-zh" style={{ whiteSpace: 'pre-wrap' }}>{ev.suggestionsZh}</p>}
                    </>
                  )}
                </div>
              )}

              <details className="raw-details" open={!!isTruncated}>
                <summary>查看原始响应 / Raw response {isTruncated && '(已截断)'}</summary>
                <pre className="raw-pre">
                  {ev.raw.slice(0, 4096)}
                  {ev.raw.length > 4096 ? '\n…truncated for display' : ''}
                </pre>
              </details>
            </>
          ) : (
            <div className="result-block">
              <p className="comment-en">该题暂无评分结果，可重试。</p>
            </div>
          )}

          <div className="accordion-actions">
            <button type="button" className="secondary-btn small" onClick={handleRetry} disabled={retrying}>
              {retrying ? '重试中...' : '整批重试 / Retry batch'}
            </button>
            <button type="button" className="secondary-btn small" onClick={() => setOpen(false)}>
              收起 / Collapse
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export function ReportScreen({ results, onRetrySingle, onRestart }: Props) {
  const { composite, ratedCount, total, comment, commentZh, strengths, strengthsZh, weaknessesList, weaknessesZhList } = useComposite(results)
  const [showCompositeZh, setShowCompositeZh] = useState(false)
  const [showStrengthsZh, setShowStrengthsZh] = useState(false)
  const [showWeaknessesZh, setShowWeaknessesZh] = useState(false)

  const compositeCls = composite !== null && composite >= 80 ? 'high' : composite !== null && composite >= 60 ? 'mid' : 'low'

  return (
    <div className="report-screen">
      <div className="composite-section">
        <h2>综合成绩 / Overall</h2>
        <div className="overall-wrap">
          <div className={`overall-score ${compositeCls}`}>{composite ?? '—'}</div>
          <span className="overall-label">/ 100</span>
          <span className="rated-hint">
            已评分 {ratedCount}/{total}
          </span>
        </div>
        {ratedCount === 0 && <p className="comment-en">暂无综合评分，请整批重试。</p>}
        {comment && (
          <div className="result-block comment-block" style={{ marginTop: 12 }}>
            <h3>综合点评 / Overall feedback</h3>
            <p className="comment-en">{comment}</p>
            {commentZh && (
              <>
                <button type="button" className="toggle-zh" onClick={() => setShowCompositeZh((v) => !v)}>
                  {showCompositeZh ? '隐藏中文 / Hide' : '显示中文 / Show 中文'}
                </button>
                {showCompositeZh && <p className="comment-zh">{commentZh}</p>}
              </>
            )}
          </div>
        )}
        {strengths && (
          <div className="result-block strengths-block">
            <h3>综合亮点 / Highlights</h3>
            <p className="comment-en">{strengths}</p>
            {strengthsZh && (
              <>
                <button type="button" className="toggle-zh" onClick={() => setShowStrengthsZh((v) => !v)}>
                  {showStrengthsZh ? '隐藏中文 / Hide' : '显示中文 / Show 中文'}
                </button>
                {showStrengthsZh && <p className="comment-zh">{strengthsZh}</p>}
              </>
            )}
          </div>
        )}
        {weaknessesList.length > 0 && (
          <div className="result-block weaknesses-block">
            <h3>待改进 / To improve</h3>
            {weaknessesList.map((w, i) => (
              <p key={i} className="comment-en weakness-text">
                {w}
              </p>
            ))}
            {weaknessesZhList.length > 0 && (
              <>
                <button type="button" className="toggle-zh" onClick={() => setShowWeaknessesZh((v) => !v)}>
                  {showWeaknessesZh ? '隐藏中文 / Hide' : '显示中文 / Show 中文'}
                </button>
                {showWeaknessesZh && (
                  <div className="comment-zh">
                    {weaknessesZhList.map((w, i) => (
                      <p key={i} style={{ margin: '4px 0' }}>
                        {w}
                      </p>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="report-questions">
        <h3 style={{ fontSize: 13, color: '#64748b', letterSpacing: '0.05em', textTransform: 'uppercase' as const }}>
          分题详情 / Per-question details · 点击“查看详细评价”展开
        </h3>
        {results.map((r, i) => (
          <QuestionCard key={r.questionId} result={r} index={i} defaultOpen={i === 0} onRetrySingle={onRetrySingle} />
        ))}
      </div>

      <div className="result-actions" style={{ marginTop: 16 }}>
        <button type="button" className="secondary-btn" onClick={onRestart}>
          再来一次 / Restart
        </button>
        <button
          type="button"
          className="secondary-btn small"
          onClick={() => modelLogger.download()}
          title="下载大模型交互日志 JSON（排查超时/截断/429）"
        >
          下载日志 JSON / Download logs
        </button>
        <button
          type="button"
          className="secondary-btn small"
          onClick={() => modelLogger.downloadText()}
          title="下载可读文本日志"
        >
          下载日志文本
        </button>
        <button
          type="button"
          className="secondary-btn small"
          onClick={() => {
            if (confirm('清空本地日志？')) modelLogger.clear()
          }}
          title="清空 localStorage 中的模型日志"
        >
          清空日志
        </button>
      </div>
      <details className="raw-details" style={{ marginTop: 12 }}>
        <summary>调试：最近日志条数 {modelLogger.getAll().length}（F12 控制台 window.__modelLogger 也可查看）</summary>
        <pre className="raw-pre" style={{ maxHeight: 240, overflow: 'auto' }}>
          {JSON.stringify(modelLogger.getAll().slice(-3), null, 2).slice(0, 4000)}
        </pre>
      </details>
    </div>
  )
}
