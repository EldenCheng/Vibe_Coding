// Local Provider — OpenAI Compatible (Gemma4 at http://172.18.0.110:8080/v1)
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

export class LocalProvider {
  private cfg: AppConfig['local']
  private timeoutMs: number

  constructor(cfg: AppConfig['local'], timeoutMs: number) {
    this.cfg = cfg
    this.timeoutMs = timeoutMs
  }

  private async callLocal(
    body: Record<string, unknown>,
    logContext?: { mode: 'single' | 'batch'; promptPreview?: string; maxTokens?: number; useJsonMode?: boolean; itemsPreview?: unknown }
  ): Promise<{ text: string; finishReason?: string }> {
    const url = `${this.cfg.baseURL.replace(/\/$/, '')}/chat/completions`
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs)
    const start = Date.now()
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.cfg.apiKey || 'EMPTY'}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      const elapsed = Date.now() - start
      if (!res.ok) {
        const t = await res.text()
        const errMsg = `Local model error ${res.status}: ${t.slice(0, 800)}`
        modelLogger.append({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          timestamp: new Date().toISOString(),
          provider: 'local',
          mode: logContext?.mode ?? 'single',
          request: {
            model: (body as Record<string, unknown>).model as string,
            promptPreview: logContext?.promptPreview?.slice(0, 500),
            items: logContext?.itemsPreview as never,
            maxTokens: logContext?.maxTokens,
            useJsonMode: logContext?.useJsonMode,
          },
          response: { elapsedMs: elapsed, status: res.status, contentLength: t.length, rawPreview: t.slice(0, 800) },
          error: errMsg,
        })
        throw new Error(errMsg)
      }
      const rawText = await res.text()
      const data = JSON.parse(rawText) as {
        choices?: Array<{ message?: { content?: string }; finish_reason?: string }>
      }
      const choice = data.choices?.[0]
      const text = choice?.message?.content ?? ''
      const elapsed2 = Date.now() - start
      // 日志：记录请求/响应（避免存完整 base64，仅长度）
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'local',
        mode: logContext?.mode ?? 'single',
        request: {
          model: (body as Record<string, unknown>).model as string,
          promptPreview: logContext?.promptPreview?.slice(0, 500),
          items: logContext?.itemsPreview as never,
          maxTokens: logContext?.maxTokens,
          useJsonMode: logContext?.useJsonMode,
        },
        response: {
          elapsedMs: elapsed2,
          status: res.status,
          finishReason: choice?.finish_reason,
          contentLength: text.length,
          contentPreview: text.slice(0, 800),
          rawPreview: rawText.slice(0, 800),
          truncated: choice?.finish_reason === 'length' || !text.trim(),
        },
      })
      return { text, finishReason: choice?.finish_reason }
    } catch (e) {
      if ((e as Error).message?.includes('Local model error')) throw e
      const elapsed = Date.now() - start
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'local',
        mode: logContext?.mode ?? 'single',
        request: {
          model: (body as Record<string, unknown>).model as string,
          promptPreview: logContext?.promptPreview?.slice(0, 500),
          maxTokens: logContext?.maxTokens,
          useJsonMode: logContext?.useJsonMode,
        },
        response: { elapsedMs: elapsed, contentLength: 0 },
        error: (e as Error).message?.slice(0, 1000),
      })
      throw e
    } finally {
      clearTimeout(timeout)
    }
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

    let messages: unknown[]
    if (params.imageBase64) {
      const mime = params.imageMimeType || 'image/jpeg'
      messages = [
        {
          role: 'user',
          content: [
            { type: 'text', text: prompt },
            { type: 'image_url', image_url: { url: `data:${mime};base64,${params.imageBase64}` } },
          ],
        },
      ]
    } else {
      messages = [{ role: 'user', content: prompt }]
    }

    for (const useJsonMode of [true, false]) {
      for (const maxTokens of [1800, 2200]) {
        const promptForAttempt = maxTokens === 2200 ? prompt + '\n\nIMPORTANT: Keep each reason under 20 words. Be concise.' : prompt
        const messagesForAttempt =
          maxTokens === 2200 && Array.isArray(messages)
            ? (messages as unknown[]).map((m) => {
                const mm = m as Record<string, unknown>
                if (Array.isArray(mm.content)) {
                  return {
                    ...mm,
                    content: (mm.content as unknown[]).map((c) => {
                      const cc = c as Record<string, unknown>
                      return cc.type === 'text' ? { ...cc, text: promptForAttempt } : c
                    }),
                  }
                }
                return { ...mm, content: promptForAttempt }
              })
            : messages
        const body: Record<string, unknown> = {
          model: this.cfg.model,
          messages: messagesForAttempt,
          temperature: 0.7,
          max_tokens: maxTokens,
          ...(useJsonMode ? { response_format: { type: 'json_object' } } : {}),
        }
        try {
          const { text, finishReason } = await this.callLocal(body, { mode: 'single', promptPreview: prompt, maxTokens, useJsonMode })
          if ((!text || !text.trim()) && finishReason === 'length') throw new Error('Local truncated length (empty)')
          if (finishReason === 'length' && maxTokens === 1800) throw new Error('Local truncated length')
          if (!text || !text.trim()) throw new Error('Local model empty response')
          return parseEvaluationResponse(text)
        } catch (e) {
          const msg = String(e)
          if (msg.includes('Local truncated length') || msg.includes('empty response')) {
            if (maxTokens === 1800) continue
            break
          }
          if (useJsonMode && msg.includes('400') && (msg.includes('response_format') || msg.includes('json_object'))) break
          throw e
        }
      }
    }
    throw new Error('Local model unreachable')
  }

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
    let messages: unknown[]
    if (params.imageBase64) {
      const mime = params.imageMimeType || 'image/jpeg'
      messages = [
        {
          role: 'user',
          content: [
            { type: 'text', text: prompt },
            { type: 'image_url', image_url: { url: `data:${mime};base64,${params.imageBase64}` } },
          ],
        },
      ]
    } else {
      messages = [{ role: 'user', content: prompt }]
    }
    const expectedIds = params.items.map((it) => it.questionId)
    // 传图档实测 2800 在 Local 也易 length 空，改为单档 3500 首试即收敛已在 prompt 内
    for (const useJsonMode of [true, false]) {
      for (const maxTokens of [3500]) {
        const body: Record<string, unknown> = {
          model: this.cfg.model,
          messages,
          temperature: 0.7,
          max_tokens: maxTokens,
          ...(useJsonMode ? { response_format: { type: 'json_object' } } : {}),
        }
        try {
          const { text, finishReason } = await this.callLocal(body, { mode: 'batch', promptPreview: prompt, maxTokens, useJsonMode, itemsPreview: params.items })
          if ((!text || !text.trim()) && finishReason === 'length') throw new Error('Local truncated length (empty batch)')
          if (finishReason === 'length') throw new Error('Local truncated length')
          if (!text || !text.trim()) throw new Error('Local model empty response')
          return parseBatchEvaluationResponse(text, expectedIds)
        } catch (e) {
          const msg = String(e)
          if (msg.includes('Local truncated length') || msg.includes('empty response')) continue
          if (msg.includes('No JSON found') || msg.includes('Batch JSON')) {
            continue
          }
          if (useJsonMode && msg.includes('400') && (msg.includes('response_format') || msg.includes('json_object'))) break
          throw e
        }
      }
    }
    throw new Error('Local batch unreachable')
  }
}
