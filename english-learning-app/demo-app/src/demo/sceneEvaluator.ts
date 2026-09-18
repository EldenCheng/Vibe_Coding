// SceneEvaluator — 复刻 detailed-design.md §4B，支持 3 合一批量（单次读图 + 整批重试）
// 批量：submitAll 后 evaluateBatchOnce；保留旧 Map 逻辑作降级，但主路径为批量

import { createAIProvider } from '../ai/providerFactory'
import { GeminiProvider } from '../ai/geminiProvider'
import { LocalProvider } from '../ai/localProvider'
import { GLMProvider } from '../ai/glmProvider'
import type { EvaluationResult, BatchEvaluationItem } from '../scoring/parseEvaluation'
import type { AppConfig } from '../config/configLoader'

export interface PresetEvaluationRequest {
  questionId: string
  questionText: string
  answer: string
  level?: number
  kind?: 'grounded' | 'open' // v0.3.0 题型（决定 imageForOpenOnly 是否发图）
  ageRange?: string // v0.3.0 开始页年龄，注入单题 prompt
  imageBase64: string | null
  imageMimeType: string
  imageDescription: string
}

export type EvaluationErrorKind = 'timeout' | 'api' | 'parse' | 'unknown'

export interface PresetEvaluationResult {
  questionId: string
  questionText: string
  answer: string
  result: EvaluationResult | null
  timedOut: boolean
  errorKind: EvaluationErrorKind
  error?: string
}

function classifyError(e: unknown): { kind: EvaluationErrorKind; msg: string } {
  const s = String(e)
  if (s.includes('Timeout after') || s.includes('AbortError') || s.includes('aborted') || s.includes('TimeoutError')) return { kind: 'timeout', msg: s }
  if (s.includes('Gemini error 429') || s.includes('429') || s.includes('ResourceExhausted') || s.includes('quota')) return { kind: 'api', msg: s }
  if (s.includes('Gemini error 404') || s.includes('404') || s.includes('model not found') || s.includes('Gemini error 5')) return { kind: 'api', msg: s }
  if (s.includes('No JSON') || s.includes('parse') || s.includes('JSON')) return { kind: 'parse', msg: s }
  if (s.includes('Gemini error') || s.includes('Local model error') || s.includes('GLM error')) return { kind: 'api', msg: s }
  return { kind: 'unknown', msg: s }
}

export class SceneEvaluator {
  // 兼容旧 Map（单题重试时仍可用），主批量路径用 batchPending
  private pendingEvaluations: Map<string, Promise<PresetEvaluationResult>> = new Map()
  private abortControllers: Map<string, AbortController> = new Map()
  private batchAbortController: AbortController | null = null
  private batchPending: Promise<PresetEvaluationResult[]> | null = null
  private config: AppConfig
  private providerName: string
  private timeoutMs: number // 外层 batch 超时（Gemini 90s / Local 150s）
  private audience?: string // 按场景注入评分受众（meta.audience）

  constructor(config: AppConfig, providerName: string, timeoutMs: number) {
    this.config = config
    this.providerName = providerName
    this.timeoutMs = timeoutMs
  }

  updateProvider(providerName: string, timeoutMs: number) {
    this.providerName = providerName
    this.timeoutMs = timeoutMs
  }

  setAudience(audience?: string) {
    this.audience = audience
  }

  // 批量：收集 3 题后单次 evaluateBatch（1 次读图）
  submitBatch(requests: PresetEvaluationRequest[]): void {
    const outerMs = this.timeoutMs
    const controller = new AbortController()
    this.batchAbortController = controller
    let timer: ReturnType<typeof setTimeout> | null = null
    const timeoutPromise = new Promise<PresetEvaluationResult[]>((resolve) => {
      timer = setTimeout(() => {
        console.warn(`[SceneEvaluator:batch] outer timeout ${outerMs}ms won, abort inner`)
        try { controller.abort(`Batch outer timeout ${outerMs}ms`) } catch {}
        resolve(requests.map((r) => ({
          questionId: r.questionId,
          questionText: r.questionText,
          answer: r.answer,
          result: null,
          timedOut: true,
          errorKind: 'timeout' as EvaluationErrorKind,
          error: `Batch timeout after ${outerMs}ms (inner ~${outerMs - 2000}ms)`,
        })))
      }, outerMs)
    })

    const inner = this.evaluateBatchInner(requests, controller.signal)
    const raced = Promise.race([
      inner.then((res) => {
        if (timer) clearTimeout(timer)
        console.warn(`[SceneEvaluator:batch] inner won, results=${res.map((r) => `${r.questionId}:${r.timedOut ? r.errorKind : 'ok'}`).join(',')}`)
        return res
      }),
      timeoutPromise,
    ])
    this.batchPending = raced
    // 同时填充旧 Map，便于按题取结果（ReportScreen 复用）
    raced.then((results) => {
      for (const r of results) {
        this.pendingEvaluations.set(r.questionId, Promise.resolve(r))
      }
    })
    console.warn(`[SceneEvaluator:batch] submit batch size=${requests.length} outer=${outerMs}ms ids=${requests.map((r) => r.questionId).join(',')}`)
  }

  private async evaluateBatchInner(requests: PresetEvaluationRequest[], signal?: AbortSignal): Promise<PresetEvaluationResult[]> {
    if (signal?.aborted) {
      return requests.map((r) => ({ questionId: r.questionId, questionText: r.questionText, answer: r.answer, result: null, timedOut: true, errorKind: 'timeout', error: 'Aborted before batch start' }))
    }
    try {
      // 内层比外层少 2s，避免同值竞速（外层赢时内层已提前 abort）
      const innerTimeout = Math.max(this.timeoutMs - 2000, 1000)
      const providerNameLower = this.providerName.toLowerCase()
      let provider: {
        evaluateBatch?: (p: { items: BatchEvaluationItem[]; imageBase64: string | null; imageMimeType: string; imageDescription: string; audience?: string }) => Promise<{ results: EvaluationResult[] }>
        evaluate: (p: unknown) => Promise<EvaluationResult>
      }
      if (providerNameLower === 'local' || providerNameLower === 'gemma' || providerNameLower === 'gemma4') {
        provider = new LocalProvider(this.config.local, innerTimeout) as unknown as typeof provider
      } else if (providerNameLower === 'glm' || providerNameLower === 'ark' || providerNameLower.startsWith('glm-')) {
        if (!this.config.glm) throw new Error('config.glm is required for provider glm')
        provider = new GLMProvider(this.config.glm, innerTimeout) as unknown as typeof provider
      } else {
        provider = new GeminiProvider(this.config.gemini, innerTimeout) as unknown as typeof provider
      }
      const items: BatchEvaluationItem[] = requests.map((r) => ({ questionId: r.questionId, question: r.questionText, answer: r.answer, level: r.level }))
      // 1 次读图：取首个请求的 imageBase64（3 题同图）
      const imageBase64 = requests[0]?.imageBase64 ?? null
      const imageMimeType = requests[0]?.imageMimeType ?? 'image/jpeg'
      const imageDescription = requests[0]?.imageDescription ?? ''
      // 优先批量接口
      if (typeof provider.evaluateBatch === 'function') {
        const batchRes = await provider.evaluateBatch({ items, imageBase64, imageMimeType, imageDescription, audience: this.audience })
        return requests.map((req, idx) => {
          const ev = batchRes.results[idx] ?? null
          if (!ev || ev.scores.overall === null) {
            // 截断或空结果：按 parse 标记 truncated 透出
            const truncated = (ev as unknown as { truncated?: boolean })?.truncated
            return { questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: ev, timedOut: !ev, errorKind: truncated ? 'parse' as EvaluationErrorKind : 'api' as EvaluationErrorKind, error: truncated ? 'Batch item truncated/empty' : 'Batch item empty' }
          }
          return { questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: ev, timedOut: false, errorKind: 'unknown' }
        })
      }
      // 降级：若 provider 无批量，串行单题（不推荐，仅兜底）
      const results: PresetEvaluationResult[] = []
      for (const req of requests) {
        try {
          const single = await provider.evaluate({ question: req.questionText, answer: req.answer, level: req.level, imageBase64: req.imageBase64, imageMimeType: req.imageMimeType, imageDescription: req.imageDescription } as unknown as never)
          results.push({ questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: single, timedOut: false, errorKind: 'unknown' })
        } catch (e) {
          const { kind, msg } = classifyError(e)
          results.push({ questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: null, timedOut: kind === 'timeout', errorKind: kind, error: msg })
        }
      }
      return results
    } catch (e) {
      const { kind, msg } = classifyError(e)
      console.warn(`[SceneEvaluator:batch] batch failed kind=${kind} msg=${msg.slice(0, 400)}`)
      return requests.map((r) => ({ questionId: r.questionId, questionText: r.questionText, answer: r.answer, result: null, timedOut: kind === 'timeout', errorKind: kind, error: msg }))
    }
  }

  // v0.3.0 单题路径（逐题即时评分主路径）：透传 kind/ageRange/audience
  private async evaluateOne(req: PresetEvaluationRequest, signal?: AbortSignal): Promise<PresetEvaluationResult> {
    if (signal?.aborted) return { questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: null, timedOut: true, errorKind: 'timeout', error: 'Aborted before start' }
    try {
      const provider = createAIProvider(this.config, this.providerName)
      const result = await provider.evaluate({ question: req.questionText, answer: req.answer, level: req.level, kind: req.kind, ageRange: req.ageRange, audience: this.audience, imageBase64: req.imageBase64, imageMimeType: req.imageMimeType, imageDescription: req.imageDescription })
      return { questionId: req.questionId, questionText: req.questionText, answer: req.answer, result, timedOut: false, errorKind: 'unknown' }
    } catch (e) {
      const { kind, msg } = classifyError(e)
      return { questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: null, timedOut: kind === 'timeout', errorKind: kind, error: msg }
    }
  }

  // v0.3.0 逐题评分：单题外层超时竞速（timeoutMs 由调用方按单题分档传入）
  async evaluateSingle(req: PresetEvaluationRequest, timeoutMs?: number): Promise<PresetEvaluationResult> {
    const outerMs = timeoutMs ?? this.timeoutMs
    const controller = new AbortController()
    const innerPromise = this.evaluateOne(req, controller.signal)
    const p = this.runWithTimeout(innerPromise, outerMs, req, controller)
    const res = await p
    this.pendingEvaluations.set(req.questionId, Promise.resolve(res))
    return res
  }

  private runWithTimeout(promise: Promise<PresetEvaluationResult>, ms: number, req: PresetEvaluationRequest, controller: AbortController): Promise<PresetEvaluationResult> {
    let timer: ReturnType<typeof setTimeout> | null = null
    const timeout = new Promise<PresetEvaluationResult>((resolve) => {
      timer = setTimeout(() => {
        try { controller.abort(`Outer timeout ${ms}ms`) } catch {}
        resolve({ questionId: req.questionId, questionText: req.questionText, answer: req.answer, result: null, timedOut: true, errorKind: 'timeout', error: `Timeout after ${ms}ms` })
      }, ms)
    })
    return Promise.race([promise.then((v) => { if (timer) clearTimeout(timer); return v }), timeout])
  }

  submitEvaluation(req: PresetEvaluationRequest): void {
    const outerMs = this.timeoutMs
    const controller = new AbortController()
    this.abortControllers.set(req.questionId, controller)
    const innerPromise = this.evaluateOne(req, controller.signal)
    const p = this.runWithTimeout(innerPromise, outerMs, req, controller)
    p.finally(() => this.abortControllers.delete(req.questionId))
    this.pendingEvaluations.set(req.questionId, p)
  }

  retrySingle(req: PresetEvaluationRequest): void {
    const old = this.abortControllers.get(req.questionId)
    if (old) try { old.abort('Retry superseded') } catch {}
    this.submitEvaluation(req)
  }

  // 批量重试：整批重试（用户要求）
  retryBatch(requests: PresetEvaluationRequest[]): void {
    if (this.batchAbortController) try { this.batchAbortController.abort('Retry batch') } catch {}
    this.submitBatch(requests)
  }

  async collectAllResults(): Promise<PresetEvaluationResult[]> {
    if (this.batchPending) {
      const res = await this.batchPending
      // 同步到 Map
      for (const r of res) this.pendingEvaluations.set(r.questionId, Promise.resolve(r))
      return res
    }
    const results = await Promise.all(Array.from(this.pendingEvaluations.values()))
    return results
  }

  async collectBatchResults(): Promise<PresetEvaluationResult[]> {
    return this.collectAllResults()
  }

  async getResult(questionId: string): Promise<PresetEvaluationResult | null> {
    const p = this.pendingEvaluations.get(questionId)
    if (!p) return null
    return p
  }

  hasPending(questionId: string): boolean { return this.pendingEvaluations.has(questionId) }

  reset(): void {
    if (this.batchAbortController) try { this.batchAbortController.abort('reset') } catch {}
    this.batchAbortController = null
    this.batchPending = null
    for (const c of this.abortControllers.values()) try { c.abort('reset') } catch {}
    this.abortControllers.clear()
    this.pendingEvaluations.clear()
  }
}
