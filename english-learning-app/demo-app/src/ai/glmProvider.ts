// GLM Provider — 火山方舟 Ark OpenAI 兼容接口（GLM-5.3-Flash，GLM-5 系列首个原生多模态模型）
// 能力依据：https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash.md
// 传图：OpenAI 格式 image_url（支持 Base64 Data URL）；思考模式强制开启，
// reasoning 内容在协议独立字段（reasoning_content）中，不污染 content 的 JSON 输出。
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

export class GLMProvider {
  private cfg: NonNullable<AppConfig['glm']>
  private timeoutMs: number
  // Ark 若拒绝 reasoning_effort 参数（400），降级为不带该参数重试
  private effortDisabled = false

  constructor(cfg: AppConfig['glm'], timeoutMs: number) {
    if (!cfg) throw new Error('config.glm is required for GLMProvider')
    this.cfg = cfg
    this.timeoutMs = timeoutMs
  }

  private buildBody(messages: unknown[], maxTokens: number, useJsonMode: boolean): Record<string, unknown> {
    return {
      model: this.cfg.model,
      messages,
      temperature: 0.7,
      max_tokens: maxTokens,
      // 评分任务用低思考强度提速（默认 low）；被服务端拒绝后自动摘除
      ...(this.cfg.reasoningEffort && !this.effortDisabled ? { reasoning_effort: this.cfg.reasoningEffort } : {}),
      ...(useJsonMode ? { response_format: { type: 'json_object' } } : {}),
    }
  }

  private buildMessages(prompt: string, imageBase64: string | null, imageMimeType: string): unknown[] {
    if (imageBase64) {
      const mime = imageMimeType || 'image/jpeg'
      return [
        {
          role: 'user',
          content: [
            { type: 'text', text: prompt },
            { type: 'image_url', image_url: { url: `data:${mime};base64,${imageBase64}` } },
          ],
        },
      ]
    }
    return [{ role: 'user', content: prompt }]
  }

  private async callGlm(
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
          Authorization: `Bearer ${this.cfg.apiKey || ''}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      const elapsed = Date.now() - start
      if (!res.ok) {
        const t = await res.text()
        const errMsg = `GLM error ${res.status}: ${t.slice(0, 800)}`
        modelLogger.append({
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          timestamp: new Date().toISOString(),
          provider: 'glm',
          mode: logContext?.mode ?? 'single',
          request: {
            model: body.model as string,
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
        choices?: Array<{ message?: { content?: string; reasoning_content?: string }; finish_reason?: string }>
      }
      const choice = data.choices?.[0]
      // 仅取 content；reasoning_content（思考内容）不参与 JSON 解析
      const text = choice?.message?.content ?? ''
      const elapsed2 = Date.now() - start
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'glm',
        mode: logContext?.mode ?? 'single',
        request: {
          model: body.model as string,
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
      if ((e as Error).message?.includes('GLM error')) throw e
      const elapsed = Date.now() - start
      modelLogger.append({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        timestamp: new Date().toISOString(),
        provider: 'glm',
        mode: logContext?.mode ?? 'single',
        request: {
          model: body.model as string,
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

  private isRetryable429or503(msg: string): boolean {
    return (
      msg.includes('GLM error 429') ||
      (msg.includes('429') && (msg.includes('quota') || msg.includes('rate') || msg.includes('RateLimit'))) ||
      msg.includes('GLM error 503') ||
      msg.includes('overloaded')
    )
  }

  // 单题评分：1800 为主，截断重试 2200 + 精简提示；JSON 模式失败降级非 JSON
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
    let lastError: unknown
    for (const useJsonMode of [true, false]) {
      for (const maxTokens of [1800, 2200]) {
        const promptForAttempt = maxTokens === 2200 ? prompt + '\n\nIMPORTANT: Keep each reason under 20 words. Be concise.' : prompt
        const messagesForAttempt = this.buildMessages(promptForAttempt, params.imageBase64, params.imageMimeType)
        let retry429Count = 0
        while (retry429Count <= 2) {
          try {
            const body = this.buildBody(messagesForAttempt, maxTokens, useJsonMode)
            const { text, finishReason } = await this.callGlm(body, { mode: 'single', promptPreview: prompt, maxTokens, useJsonMode })
            if (finishReason === 'length' && maxTokens === 1800) throw new Error('GLM truncated length')
            if (!text || !text.trim()) throw new Error('GLM empty response')
            return parseEvaluationResponse(text)
          } catch (e) {
            const msg = String(e)
            if (msg.includes('GLM truncated length') || msg.includes('GLM empty response')) {
              if (maxTokens === 1800) break // 去下一个 maxTokens=2200
              lastError = e
              break
            }
            if (useJsonMode && msg.includes('400') && (msg.includes('response_format') || msg.includes('json_object'))) break
            // reasoning_effort 参数被 Ark 拒绝：摘除该参数后原地重试一次
            if (msg.includes('400') && msg.includes('reasoning') && !this.effortDisabled) {
              this.effortDisabled = true
              console.warn('[GLMProvider] reasoning_effort rejected (400), retrying without it')
              continue
            }
            if (this.isRetryable429or503(msg) && retry429Count < 2) {
              const backoff = 2000 * Math.pow(2, retry429Count) // 2s, 4s
              console.warn(`[GLMProvider] retryable ${msg.slice(0, 120)} -> backoff ${backoff}ms (${retry429Count + 1}/2)`)
              await new Promise((r) => setTimeout(r, backoff))
              retry429Count++
              continue
            }
            lastError = e
            break
          }
        }
        if (lastError && (String(lastError).includes('GLM truncated length') || String(lastError).includes('GLM empty response'))) continue // 2200 / 非 JSON 再试
        if (lastError) break
      }
      if (lastError && (String(lastError).includes('GLM truncated length') || String(lastError).includes('GLM empty response'))) continue // 非 JSON 模式再试
      if (lastError) break
    }
    throw lastError ?? new Error('GLM model unreachable')
  }

  // 三合一批量：单档 3500，JSON 模式失败降级非 JSON
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
    const messages = this.buildMessages(prompt, params.imageBase64, params.imageMimeType)
    const expectedIds = params.items.map((it) => it.questionId)
    let lastError: unknown
    for (const useJsonMode of [true, false]) {
      let retry429Count = 0
      while (retry429Count <= 2) {
        try {
          const body = this.buildBody(messages, 3500, useJsonMode)
          const { text, finishReason } = await this.callGlm(body, { mode: 'batch', promptPreview: prompt, maxTokens: 3500, useJsonMode, itemsPreview: params.items })
          if (finishReason === 'length') throw new Error('GLM truncated length (batch)')
          if (!text || !text.trim()) throw new Error('GLM empty response (batch)')
          return parseBatchEvaluationResponse(text, expectedIds)
        } catch (e) {
          const msg = String(e)
          if (msg.includes('No JSON found') || msg.includes('Batch JSON')) break // 换非 JSON 模式
          if (useJsonMode && msg.includes('400') && (msg.includes('response_format') || msg.includes('json_object'))) break
          if (msg.includes('400') && msg.includes('reasoning') && !this.effortDisabled) {
            this.effortDisabled = true
            console.warn('[GLMProvider:batch] reasoning_effort rejected (400), retrying without it')
            continue
          }
          if (this.isRetryable429or503(msg) && retry429Count < 2) {
            const backoff = 2000 * Math.pow(2, retry429Count)
            console.warn(`[GLMProvider:batch] retryable ${msg.slice(0, 120)} -> backoff ${backoff}ms (${retry429Count + 1}/2)`)
            await new Promise((r) => setTimeout(r, backoff))
            retry429Count++
            continue
          }
          lastError = e
          break
        }
      }
      if (lastError && (String(lastError).includes('GLM truncated length') || String(lastError).includes('GLM empty response'))) continue
      if (lastError) break
    }
    throw lastError ?? new Error('GLM batch unreachable')
  }
}
