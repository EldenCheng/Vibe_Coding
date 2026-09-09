// 评分响应解析 — 兼容 fence/截断/尾逗号/平衡括号；严格版：3维+分维度归因；支持 JSON 与 markdown 回退

export interface EvaluationScores {
  vocabulary: number | null
  grammar: number | null
  relevance: number | null
  overall: number | null
  vocabulary_reason: string
  vocabulary_reason_zh: string
  grammar_reason: string
  grammar_reason_zh: string
  relevance_reason: string
  relevance_reason_zh: string
}

export interface EvaluationResult {
  scores: EvaluationScores
  comment: string
  commentZh: string
  strengths: string
  strengthsZh: string
  weaknesses: string
  weaknessesZh: string
  suggestions: string
  suggestionsZh: string
  raw: string
  truncated?: boolean
}

function clampScore(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  const n = Math.round(v)
  if (n < 0 || n > 100) return null
  return n
}

function stripFences(text: string): string {
  let t = text.replace(/```(?:json)?\s*/gi, '').replace(/```/g, '')
  t = t.replace(/<think>[\s\S]*?<\/think>/gi, '')
  return t.trim()
}

function extractBalancedJson(text: string): string | null {
  const start = text.indexOf('{')
  if (start === -1) return null
  let depth = 0
  let inString = false
  let escape = false
  for (let i = start; i < text.length; i++) {
    const ch = text[i]
    if (inString) {
      if (escape) {
        escape = false
      } else if (ch === '\\') {
        escape = true
      } else if (ch === '"') {
        inString = false
      }
    } else {
      if (ch === '"') {
        inString = true
      } else if (ch === '{') {
        depth++
      } else if (ch === '}') {
        depth--
        if (depth === 0) {
          return text.slice(start, i + 1)
        }
      }
    }
  }
  return text.slice(start)
}

function tryParseJson(candidate: string): Record<string, unknown> | null {
  const cleaned = candidate.replace(/,\s*([}\]])/g, '$1').trim()
  try {
    return JSON.parse(cleaned) as Record<string, unknown>
  } catch {
    return null
  }
}

function pickString(obj: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = obj[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return ''
}

function repairTruncated(candidate: string): string[] {
  const attempts: string[] = []
  const t = candidate.trim()
  attempts.push(t.replace(/,\s*""\s*$/, '').replace(/,\s*"\s*$/, '').replace(/,\s*$/, '') + '}')
  attempts.push(t.replace(/,\s*"[^"]*"\s*:?\s*"?\s*$/, '') + '}')
  const lastComma = t.lastIndexOf(',')
  if (lastComma > t.indexOf('{')) {
    attempts.push(t.slice(0, lastComma) + '}')
  }
  attempts.push(t + '}')
  attempts.push(t + '"}')
  return attempts
}

// Markdown 回退：模型直接输出 Strengths ZH: * ... Weaknesses EN: ... 形式
function parseMarkdownFallback(text: string): EvaluationResult | null {
  const normalized = text.replace(/\r\n/g, '\n')
  // 需至少包含 Strengths/Weaknesses/Suggestions 中两项才视为 markdown 响应
  const hasStrengths = /Strengths/i.test(normalized)
  const hasWeaknesses = /Weaknesses/i.test(normalized)
  const hasSuggestions = /Suggestions/i.test(normalized)
  const hitCount = [hasStrengths, hasWeaknesses, hasSuggestions].filter(Boolean).length
  if (hitCount < 2) return null

  const extractSection = (label: RegExp, nextLabels: RegExp[]): string => {
    const startMatch = normalized.match(label)
    if (!startMatch || startMatch.index === undefined) return ''
    const start = startMatch.index + startMatch[0].length
    let end = normalized.length
    for (const next of nextLabels) {
      const m = normalized.slice(start).match(next)
      if (m && m.index !== undefined) {
        end = Math.min(end, start + m.index)
      }
    }
    return normalized.slice(start, end).trim().replace(/^[:：\s*\-]+/, '').trim()
  }

  const strengths = extractSection(/Strengths(?:\s*ZH)?\s*[:：]*/i, [
    /Weaknesses/i,
    /Suggestions/i,
  ])
  const strengthsZh = '' // markdown 中 strengths 的 ZH 与 EN 常混在一起，统一放 strengths
  const weaknesses = extractSection(/Weaknesses(?:\s*EN)?\s*[:：]*/i, [/Suggestions/i, /Strengths/i])
  const suggestions = extractSection(/Suggestions(?:\s*EN)?\s*[:：]*/i, [/Strengths/i, /Weaknesses/i])

  // 尝试从全文抽分数
  const scoreFrom = (label: string): number | null => {
    const re = new RegExp(label + '\\D{0,20}(\\d{1,3})', 'i')
    const m = normalized.match(re)
    if (m) {
      const n = parseInt(m[1], 10)
      if (n >= 0 && n <= 100) return n
    }
    return null
  }
  const vocabulary = scoreFrom('vocabulary')
  const grammar = scoreFrom('grammar')
  const relevance = scoreFrom('relevance')
  const overall = scoreFrom('overall') ?? scoreFrom('total') ?? scoreFrom('score')

  // 若连 weaknesses 都抽不到，认为不是有效 markdown
  if (!weaknesses && !suggestions && !strengths) return null

  const scores: EvaluationScores = {
    vocabulary,
    grammar,
    relevance,
    overall,
    vocabulary_reason: '',
    vocabulary_reason_zh: '',
    grammar_reason: '',
    grammar_reason_zh: '',
    relevance_reason: '',
    relevance_reason_zh: '',
  }
  if (scores.overall === null) {
    const vals = [scores.vocabulary, scores.grammar, scores.relevance].filter((v): v is number => v !== null)
    if (vals.length > 0) {
      scores.overall = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
    }
  }

  return {
    scores,
    comment: strengths ? strengths.slice(0, 400) : 'Good effort — see details below.',
    commentZh: '',
    strengths,
    strengthsZh,
    weaknesses: weaknesses || 'See raw response.',
    weaknessesZh: '',
    suggestions: suggestions || '',
    suggestionsZh: '',
    raw: text,
  }
}

export function parseEvaluationResponse(text: string): EvaluationResult {
  const stripped = stripFences(text)

  let candidate = extractBalancedJson(stripped)
  if (!candidate) {
    const greedy = stripped.match(/\{[\s\S]*\}/)
    if (greedy) candidate = greedy[0]
  }
  let wasTruncated = false
  // 检测原始是否疑似截断（末尾非 } 或含悬空引号）
  if (candidate && !candidate.trim().endsWith('}')) wasTruncated = true
  if (candidate) {
    let obj = tryParseJson(candidate)
    if (!obj) {
      wasTruncated = true
      for (const attempt of repairTruncated(candidate)) {
        obj = tryParseJson(attempt)
        if (obj) {
          candidate = attempt
          break
        }
      }
      if (!obj) {
        obj = tryParseJson(candidate + '}')
        if (!obj) obj = tryParseJson(candidate + '"}')
        if (!obj) obj = tryParseJson(candidate.trim().replace(/,?\s*$/, '') + '}')
      }
    }
    if (obj) {
      const scores: EvaluationScores = {
        vocabulary: clampScore(obj.vocabulary),
        grammar: clampScore(obj.grammar),
        relevance: clampScore(obj.relevance),
        overall: clampScore(obj.overall ?? obj.composite ?? obj.total),
        vocabulary_reason: pickString(obj, 'vocabulary_reason', 'vocabularyReason', 'vocab_reason'),
        vocabulary_reason_zh: pickString(obj, 'vocabulary_reason_zh', 'vocabularyReasonZh', 'vocab_reason_zh'),
        grammar_reason: pickString(obj, 'grammar_reason', 'grammarReason'),
        grammar_reason_zh: pickString(obj, 'grammar_reason_zh', 'grammarReasonZh'),
        relevance_reason: pickString(obj, 'relevance_reason', 'relevanceReason'),
        relevance_reason_zh: pickString(obj, 'relevance_reason_zh', 'relevanceReasonZh'),
      }
      if (scores.overall === null) {
        const vals = [scores.vocabulary, scores.grammar, scores.relevance].filter((v): v is number => v !== null)
        if (vals.length > 0) {
          scores.overall = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
        }
      }
      const comment = pickString(obj, 'comment', 'feedback')
      const commentZh = pickString(obj, 'comment_zh', 'commentZh')
      const strengths = pickString(obj, 'strengths', 'strength', 'positive', 'goodPoints')
      const strengthsZh = pickString(obj, 'strengths_zh', 'strengthsZh', 'strength_zh')
      const weaknesses = pickString(obj, 'weaknesses', 'weakness', 'issues', 'problems', 'deductions')
      const weaknessesZh = pickString(obj, 'weaknesses_zh', 'weaknessesZh', 'weakness_zh', 'issues_zh')
      const suggestions = pickString(obj, 'suggestions', 'suggestion', 'improvements', 'advice', 'tips')
      const suggestionsZh = pickString(obj, 'suggestions_zh', 'suggestionsZh', 'suggestion_zh', 'improvements_zh')
      // 若有任一维 null 或任一 reason 为截断短句，标记 truncated
      const hasNullScore = scores.grammar === null || scores.relevance === null
      const shortReason = (s: string) => s.trim().length > 0 && s.trim().length < 15
      const truncatedReason = shortReason(scores.vocabulary_reason) || shortReason(scores.grammar_reason) || shortReason(scores.relevance_reason)
      const truncatedFlag = wasTruncated || hasNullScore || truncatedReason

      return {
        scores,
        comment,
        commentZh,
        strengths,
        strengthsZh,
        weaknesses,
        weaknessesZh,
        suggestions,
        suggestionsZh,
        raw: text,
        truncated: truncatedFlag || undefined,
      }
    }
  }

  // 无 JSON 时尝试 markdown 回退
  const fallback = parseMarkdownFallback(text)
  if (fallback) return fallback

  // 仍无 JSON，尝试将截断文本按可抢救 JSON 处理（加闭合）
  const truncatedAttempt = stripped.slice(stripped.indexOf('{')).trim()
  if (truncatedAttempt) {
    const repaired = repairTruncated(truncatedAttempt + '}')
    for (const a of repaired) {
      const o = tryParseJson(a)
      if (o) {
        // 递归一次
        return parseEvaluationResponse(a)
      }
    }
  }

  throw new Error('No JSON found in response: ' + stripped.slice(0, 400))
}

export function buildEvaluationPrompt(params: {
  question: string
  answer: string
  imageDescription: string
}): string {
  return `You are a STRICT but supportive English teacher for Chinese junior students (13-15, average level in mainland China).

Image description: "${params.imageDescription}"
Question: "${params.question}"
Student answer: "${params.answer}"

Grade strictly on 0-100: vocabulary, grammar, relevance. Also overall 0-100. No pronunciation. Be honest - high scores must still have deductions. Even overall 88 must have at least two distinct issues in different dimensions.

Rules:
- For EACH of vocabulary, grammar, relevance: give int score AND one-sentence reason (≤20 English words / 30 Chinese chars). If score < 90, reason MUST quote a short fragment from the student's answer with "..." that caused deduction.
- Overall 88 must list at least two distinct issues (different dimensions) and two actionable suggestions, each with ONE corrected example sentence (≤12 words) the student can imitate.
- Keep each of strengths/weaknesses/suggestions to 1-2 sentences, concise. Total JSON must be under 300 words.
- Tone: one sentence praise first, then direct improvements. No empty praise.
- You MUST output a single JSON object and nothing else. Do not use markdown headings like "Strengths ZH:" outside JSON. Start with { and end with }. Example:
{"vocabulary":85,"vocabulary_reason":"Repetition of \\"good\\" in \\"...good fruits...\\"","vocabulary_reason_zh":"中文...\\"","grammar":82,"grammar_reason":"...","grammar_reason_zh":"...","relevance":90,"relevance_reason":"...","relevance_reason_zh":"...","overall":85,"comment":"...","comment_zh":"...","strengths":"...","strengths_zh":"...","weaknesses":"...","weaknesses_zh":"...","suggestions":"...","suggestions_zh":"..."}
- Respond ONLY with JSON:
{
  "vocabulary": int,
  "vocabulary_reason": "EN one sentence, quote \\"...\\" if <90",
  "vocabulary_reason_zh": "中文一句话，引用\\"...\\"",
  "grammar": int,
  "grammar_reason": "EN one sentence, quote \\"...\\" if <90",
  "grammar_reason_zh": "中文一句话，引用\\"...\\"",
  "relevance": int,
  "relevance_reason": "EN one sentence, quote \\"...\\" if <90",
  "relevance_reason_zh": "中文一句话，引用\\"...\\"",
  "overall": int,
  "comment": "1 sentence praise EN",
  "comment_zh": "对应的中文鼓励",
  "strengths": "1 sentence EN - what was good",
  "strengths_zh": "中文亮点",
  "weaknesses": "2 sentences EN - specific errors causing point loss, quote student's error with \\"...\\"",
  "weaknesses_zh": "中文，逐条指错并引用原文",
  "suggestions": "2 numbered tips EN, each with Example: \\"...\\"",
  "suggestions_zh": "中文，2条可执行技巧各带仿写句，例如：1. ... 例句：\\"..." 2. ... 例句：\\"...""
}

No explanation outside JSON.`
}
