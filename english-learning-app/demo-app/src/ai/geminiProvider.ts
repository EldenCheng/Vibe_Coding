// Gemini Provider — 直接 REST 调用 Generative Language API
import type { AppConfig } from '../config/configLoader'
import {
  buildSingleEvaluationPrompt,
  buildBatchEvaluationPrompt,
  parseEvaluationResponse,
  parseBatchEvaluationResponse,
  type EvaluationResult,
  type BatchEvaluationItem,
  type BatchEvaluationResult,
} from '../scoring/parseEvaluation'
import { modelLogger } from '../utils/modelLogger'

export interface EvaluateParams {
  question: string
  answer: string
  level?: number
  kind?: 'grounded' | 'open' // v0.3.0 题型
  ageRange?: string // v0.3.0 开始页年龄 10-12/13-15/16-18
  audience?: string // 显式受众（优先于 ageRange 映射）
  imageBase64: string | null
  imageMimeType: string
  imageDescription: string
}

export class GeminiProvider {
  private cfg: AppConfig['gemini']
  private timeoutMs: number

  constructor(cfg: AppConfig['gemini'], timeoutMs: number) {
    this.cfg = cfg
    this.timeoutMs = timeoutMs
  }

  private async callGemini(
    model: string,
    parts: unknown[],
    useJsonMode: boolean,
    maxTokens: number,
    logContext?: { mode: 'single' | 'batch'; promptPreview?: string; itemsPreview?: unknown }
  ): Promise<{ text: string; finishReason?: string }> {
    const key = this.cfg.apiKey
    if (!key) throw new Error('Gemini API key missing')
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(key)}`
    const body: Record<string, unknown> = {
      contents: [{ role: 'user', parts }],
      generationConfig: {
        temperature: 0.7,
        maxOutputTokens: maxTokens,
        ...(useJsonMode ? { responseMimeType: 'application/json' } : {}),
      },
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs)
    const start = Date.now()
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      const elapsed = Date.now() - start
      if (!res.ok) {
        const text = await res.text()
        const errMsg = `Gemini error ${res.status}: ${text.slice(0, 800)}`
        modelLogger.append({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          timestamp: new Date().toISOString(),
          provider: 'gemini',
          mode: logContext?.mode ?? 'single',
          request: { model, promptPreview: logContext?.promptPreview?.slice(0, 500), items: logContext?.itemsPreview as never, maxTokens, useJsonMode },
          response: { elapsedMs: elapsed, status: res.status, contentLength: text.length, rawPreview: text.slice(0, 800) },
          error: errMsg,
        })
        throw new Error(errMsg)
      }
      const rawText = await res.text()
      const data = JSON.parse(rawText) as {
        candidates?: Array<{
          content?: { parts?: Array<{ text?: string }> }
          finishReason?: string
        }>
      }
      const cand = data.candidates?.[0]
      const text = cand?.content?.parts?.map((p) => p.text ?? '').join('') ?? ''
      const elapsed2 = Date.now() - start
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'gemini',
        mode: logContext?.mode ?? 'single',
        request: { model, promptPreview: logContext?.promptPreview?.slice(0, 500), items: logContext?.itemsPreview as never, maxTokens, useJsonMode },
        response: {
          elapsedMs: elapsed2,
          status: res.status,
          finishReason: cand?.finishReason,
          contentLength: text.length,
          contentPreview: text.slice(0, 800),
          rawPreview: rawText.slice(0, 800),
          truncated: cand?.finishReason === 'MAX_TOKENS' || !text.trim(),
        },
      })
      if (!text) throw new Error('Gemini empty response')
      return { text, finishReason: cand?.finishReason }
    } catch (e) {
      if ((e as Error).message?.includes('Gemini error')) throw e
      const elapsed = Date.now() - start
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'gemini',
        mode: logContext?.mode ?? 'single',
        request: { model, promptPreview: logContext?.promptPreview?.slice(0, 500), maxTokens, useJsonMode },
        response: { elapsedMs: elapsed, contentLength: 0 },
        error: (e as Error).message?.slice(0, 1000),
      })
      throw e
    } finally {
      clearTimeout(timeout)
    }
  }

  private isRetryable429or503(msg: string): boolean {
    return (
      msg.includes('Gemini error 429') ||
      (msg.includes('429') && (msg.includes('quota') || msg.includes('ResourceExhausted') || msg.includes('rate'))) ||
      msg.includes('Gemini error 503') ||
      msg.includes('503') ||
      msg.includes('overloaded') ||
      msg.includes('UNAVAILABLE')
    )
  }

  // 三合一批量：传图档 120s / 描述档 45s，首试即 3500 + 收敛（无需 2800→3200 两跳）
  async evaluateBatch(params: {
    items: BatchEvaluationItem[]
    imageBase64: string | null
    imageMimeType: string
    imageDescription: string
    audience?: string
  }): Promise<BatchEvaluationResult> {
    const prompt = buildBatchEvaluationPrompt({
      imageDescription: params.imageDescription,
      items: params.items,
      audience: params.audience,
    })
    let parts: unknown[]
    if (params.imageBase64) {
      parts = [
        { inlineData: { mimeType: params.imageMimeType || 'image/jpeg', data: params.imageBase64 } },
        { text: prompt },
      ]
    } else {
      parts = [{ text: prompt }]
    }
    const models = [this.cfg.textModel, this.cfg.fallbackModel].filter(Boolean)
    const expectedIds = params.items.map((it) => it.questionId)
    let lastError: unknown
    // 传图档实测 2800 必 MAX_TOKENS，改为单档 3500，失败仅在 MAX_TOKENS 时按原 prompt 重试一次非 json
    for (const model of models) {
      for (const useJsonMode of [true, false]) {
        for (const maxTokens of [3500]) {
          let retry429Count = 0
          while (retry429Count <= 2) {
            try {
              const { text, finishReason } = await this.callGemini(model, parts as unknown[], useJsonMode, maxTokens, { mode: 'batch', promptPreview: prompt, itemsPreview: params.items })
              if (finishReason === 'MAX_TOKENS') throw new Error('Gemini truncated MAX_TOKENS')
              return parseBatchEvaluationResponse(text, expectedIds)
            } catch (e) {
              const msg = String(e)
              if (msg.includes('Gemini truncated MAX_TOKENS')) break
              if (useJsonMode && msg.includes('400') && msg.includes('responseMimeType')) break
              if (this.isRetryable429or503(msg) && retry429Count < 2) {
                const backoff = 2000 * Math.pow(2, retry429Count)
                console.warn(`[GeminiProvider:batch] ${model} retryable -> backoff ${backoff}ms`)
                await new Promise((r) => setTimeout(r, backoff))
                retry429Count++
                continue
              }
              if (params.imageBase64 && msg.includes('inlineData')) {
                try {
                  const { text: raw2 } = await this.callGemini(model, [{ text: prompt }], useJsonMode, maxTokens, { mode: 'batch', promptPreview: prompt, itemsPreview: params.items })
                  return parseBatchEvaluationResponse(raw2, expectedIds)
                } catch (e2) {
                  if (useJsonMode && String(e2).includes('400') && String(e2).includes('responseMimeType')) break
                  lastError = e2
                }
              } else {
                lastError = e
              }
              break
            }
          }
          if (lastError && String(lastError).includes('truncated')) continue
        }
        if (lastError && String(lastError).includes('truncated')) continue
      }
    }
    throw lastError
  }

  async evaluate(params: EvaluateParams): Promise<EvaluationResult> {
    const prompt = buildSingleEvaluationPrompt({
      question: params.question,
      answer: params.answer,
      imageDescription: params.imageDescription,
      level: params.level,
      kind: params.kind,
      ageRange: params.ageRange,
      audience: params.audience,
    })

    let parts: unknown[]
    if (params.imageBase64) {
      parts = [
        { inlineData: { mimeType: params.imageMimeType || 'image/jpeg', data: params.imageBase64 } },
        { text: prompt },
      ]
    } else {
      parts = [{ text: prompt }]
    }

    const models = [this.cfg.textModel, this.cfg.fallbackModel].filter(Boolean)
    let lastError: unknown
    for (const model of models) {
      for (const useJsonMode of [true, false]) {
        // 1800 为主，MAX_TOKENS 时自动重试 2200 + 精简提示
        for (const attempt of [1800, 2200]) {
          let retry429Count = 0
          // 对 429/503 的内层重试（指数退避 2s/4s），与外层 SceneEvaluator 的 30s 竞争时不会无限拖
          while (retry429Count <= 2) {
            try {
              const usePrompt = attempt === 2200 ? prompt + '\n\nIMPORTANT: Keep each reason under 20 words. Be concise.' : prompt
              const useParts =
                attempt === 2200 && parts.length === 2
                  ? [{ inlineData: (parts[0] as Record<string, unknown>).inlineData }, { text: usePrompt }]
                  : attempt === 2200
                    ? [{ text: usePrompt }]
                    : parts
              const { text, finishReason } = await this.callGemini(model, useParts as unknown[], useJsonMode, attempt, { mode: 'single', promptPreview: prompt })
              if (finishReason === 'MAX_TOKENS' && attempt === 1800) {
                throw new Error('Gemini truncated MAX_TOKENS')
              }
              return parseEvaluationResponse(text)
            } catch (e) {
              const msg = String(e)
              if (msg.includes('Gemini truncated MAX_TOKENS')) {
                break // 退出 while，去下一个 attempt=2200
              }
              if (useJsonMode && msg.includes('400') && msg.includes('responseMimeType')) {
                break // 换非 JSON 模式（跳出 while）
              }
              // P2: 429/503 指数退避重试（最多 2 次：2s、4s），若仍在 SceneEvaluator 的 30s 窗口内可自愈
              if (this.isRetryable429or503(msg) && retry429Count < 2) {
                const backoff = 2000 * Math.pow(2, retry429Count) // 2s, 4s
                console.warn(`[GeminiProvider] ${model} retryable ${msg.slice(0, 120)} -> backoff ${backoff}ms (${retry429Count + 1}/2)`)
                await new Promise((r) => setTimeout(r, backoff))
                retry429Count++
                continue
              }
              if (params.imageBase64 && msg.includes('inlineData')) {
                try {
                  const { text: raw2 } = await this.callGemini(model, [{ text: prompt }], useJsonMode, attempt, { mode: 'single', promptPreview: prompt })
                  return parseEvaluationResponse(raw2)
                } catch (e2) {
                  const msg2 = String(e2)
                  if (useJsonMode && msg2.includes('400') && msg2.includes('responseMimeType')) {
                    break
                  }
                  if (this.isRetryable429or503(msg2) && retry429Count < 2) {
                    const backoff = 2000 * Math.pow(2, retry429Count)
                    console.warn(`[GeminiProvider] ${model} inlineData fallback retryable -> backoff ${backoff}ms`)
                    await new Promise((r) => setTimeout(r, backoff))
                    retry429Count++
                    continue
                  }
                  lastError = e2
                }
              } else {
                lastError = e
              }
              break // 不可重试错误，跳出 while 去下一个 attempt/jsonMode/model
            }
          } // while retry429
          if (lastError && String(lastError).includes('Gemini truncated MAX_TOKENS')) {
            continue // 去下一个 attempt 2200
          }
          if (this.isRetryable429or503(String(lastError)) && attempt === 1800) {
            continue // 429 已在 while 内重试过，若仍失败则让 2200 再试一次（可能 JSON 模式导致）
          }
        }
        if (lastError && String(lastError).includes('truncated')) continue
      }
    }
    throw lastError
  }
}
