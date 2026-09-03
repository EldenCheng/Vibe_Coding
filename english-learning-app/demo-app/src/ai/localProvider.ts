// Local Provider — OpenAI Compatible (Gemma4 at http://172.18.0.110:8080/v1)
import type { AppConfig } from '../config/configLoader'
import { buildEvaluationPrompt, parseEvaluationResponse, type EvaluationResult } from '../scoring/parseEvaluation'

export interface EvaluateParams {
  question: string
  answer: string
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
    body: Record<string, unknown>
  ): Promise<{ text: string; finishReason?: string }> {
    const url = `${this.cfg.baseURL.replace(/\/$/, '')}/chat/completions`
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs)
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
      if (!res.ok) {
        const t = await res.text()
        throw new Error(`Local model error ${res.status}: ${t.slice(0, 500)}`)
      }
      const data = (await res.json()) as {
        choices?: Array<{ message?: { content?: string }; finish_reason?: string }>
      }
      const choice = data.choices?.[0]
      const text = choice?.message?.content ?? ''
      if (!text) throw new Error('Local model empty response')
      return { text, finishReason: choice?.finish_reason }
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
          const { text, finishReason } = await this.callLocal(body)
          if (finishReason === 'length' && maxTokens === 1800) {
            throw new Error('Local truncated length')
          }
          return parseEvaluationResponse(text)
        } catch (e) {
          const msg = String(e)
          if (msg.includes('Local truncated length')) continue
          if (useJsonMode && msg.includes('400') && (msg.includes('response_format') || msg.includes('json_object'))) {
            break
          }
          throw e
        }
      }
    }
    throw new Error('Local model unreachable')
  }
}
