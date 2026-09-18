import type { AppConfig } from '../config/configLoader'
import { GeminiProvider } from './geminiProvider'
import { LocalProvider } from './localProvider'
import { GLMProvider } from './glmProvider'
import type { EvaluateParams as GParams } from './geminiProvider'
import type { EvaluationResult } from '../scoring/parseEvaluation'

export type AIProvider = {
  evaluate(params: GParams): Promise<EvaluationResult>
  name: string
}

export function createAIProvider(config: AppConfig, overrideProvider?: string): AIProvider {
  const provider = (overrideProvider ?? config.aiProvider).toLowerCase()
  // 三合一批次分档：Gemini 120s / GLM 120s / Local 360s（单题 15s/40s 已过紧，批量需 2min 内）
  const rawGemini = config.demo.evaluationTimeoutMs ?? 90000
  const geminiTimeout = rawGemini < 80000 ? 90000 : rawGemini
  const rawGlm = config.demo.glmEvaluationTimeoutMs ?? 120000
  const glmTimeout = rawGlm < 80000 ? 120000 : rawGlm
  const rawLocalTimeout = config.demo.localEvaluationTimeoutMs ?? 150000
  const localTimeout = rawLocalTimeout < 120000 ? 150000 : rawLocalTimeout
  if (provider === 'local' || provider === 'gemma' || provider === 'gemma4') {
    return { evaluate: (p) => new LocalProvider(config.local, localTimeout).evaluate(p), name: 'local' }
  }
  if (provider === 'glm' || provider === 'ark' || provider.startsWith('glm-')) {
    if (!config.glm) throw new Error('config.glm is required for provider glm')
    return { evaluate: (p) => new GLMProvider(config.glm!, glmTimeout).evaluate(p), name: 'glm' }
  }
  // default gemini
  return { evaluate: (p) => new GeminiProvider(config.gemini, geminiTimeout).evaluate(p), name: 'gemini' }
}
