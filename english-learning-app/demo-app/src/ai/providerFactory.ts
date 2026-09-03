import type { AppConfig } from '../config/configLoader'
import { GeminiProvider } from './geminiProvider'
import { LocalProvider } from './localProvider'
import type { EvaluateParams as GParams } from './geminiProvider'
import type { EvaluationResult } from '../scoring/parseEvaluation'

export type AIProvider = {
  evaluate(params: GParams): Promise<EvaluationResult>
  name: string
}

export function createAIProvider(config: AppConfig, overrideProvider?: string): AIProvider {
  const provider = (overrideProvider ?? config.aiProvider).toLowerCase()
  const geminiTimeout = config.demo.evaluationTimeoutMs ?? 15000
  // local 至少 40s，避免 Gemma4 因 15s 被提前 abort
  const rawLocalTimeout = config.demo.localEvaluationTimeoutMs ?? 40000
  const localTimeout = Math.max(rawLocalTimeout, 40000)
  if (provider === 'local' || provider === 'gemma' || provider === 'gemma4') {
    return { evaluate: (p) => new LocalProvider(config.local, localTimeout).evaluate(p), name: 'local' }
  }
  // default gemini
  return { evaluate: (p) => new GeminiProvider(config.gemini, geminiTimeout).evaluate(p), name: 'gemini' }
}
