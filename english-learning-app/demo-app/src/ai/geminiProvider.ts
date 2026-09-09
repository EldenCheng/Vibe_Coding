// Gemini Provider — 直接 REST 调用 Generative Language API
import type { AppConfig } from '../config/configLoader'
import {
  buildEvaluationPrompt,
  parseEvaluationResponse,
  type EvaluationResult,
} from '../scoring/parseEvaluation'

export interface EvaluateParams {
  question: string
  answer: string
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
    maxTokens: number
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
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`Gemini error ${res.status}: ${text.slice(0, 500)}`)
      }
      const data = (await res.json()) as {
        candidates?: Array<{
          content?: { parts?: Array<{ text?: string }> }
          finishReason?: string
        }>
      }
      const cand = data.candidates?.[0]
      const text = cand?.content?.parts?.map((p) => p.text ?? '').join('') ?? ''
      if (!text) throw new Error('Gemini empty response')
      return { text, finishReason: cand?.finishReason }
    } finally {
      clearTimeout(timeout)
    }
  }

  async evaluate(params: EvaluateParams): Promise<EvaluationResult> {
    const prompt = buildEvaluationPrompt({
      question: params.question,
      answer: params.answer,
      imageDescription: params.imageDescription,
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
          try {
            const usePrompt = attempt === 2200 ? prompt + '\n\nIMPORTANT: Keep each reason under 20 words. Be concise.' : prompt
            const useParts =
              attempt === 2200 && parts.length === 2
                ? [{ inlineData: (parts[0] as Record<string, unknown>).inlineData }, { text: usePrompt }]
                : attempt === 2200
                  ? [{ text: usePrompt }]
                  : parts
            const { text, finishReason } = await this.callGemini(model, useParts as unknown[], useJsonMode, attempt)
            if (finishReason === 'MAX_TOKENS' && attempt === 1800) {
              // 主动重试更大限额而非直接解析截断
              throw new Error('Gemini truncated MAX_TOKENS')
            }
            return parseEvaluationResponse(text)
          } catch (e) {
            const msg = String(e)
            if (msg.includes('Gemini truncated MAX_TOKENS')) {
              continue // 重试 2200
            }
            if (useJsonMode && msg.includes('400') && msg.includes('responseMimeType')) {
              break // 换非 JSON 模式
            }
            if (params.imageBase64 && msg.includes('inlineData')) {
              try {
                const { text: raw2 } = await this.callGemini(model, [{ text: prompt }], useJsonMode, attempt)
                return parseEvaluationResponse(raw2)
              } catch (e2) {
                if (useJsonMode && String(e2).includes('400') && String(e2).includes('responseMimeType')) {
                  break
                }
                lastError = e2
              }
            } else {
              lastError = e
            }
            if (msg.includes('Gemini truncated MAX_TOKENS')) continue
            break
          }
        }
        if (lastError && String(lastError).includes('truncated')) continue
      }
    }
    throw lastError
  }
}
