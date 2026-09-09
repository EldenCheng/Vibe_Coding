// Config Loader — 负责加载并校验 public/config.json
export interface AppConfig {
  aiProvider: string
  gemini: {
    apiKey: string
    textModel: string
    fallbackModel: string
  }
  local: {
    baseURL: string
    directBaseURL: string
    apiKey: string
    model: string
  }
  tts: {
    lang: string
    voice: string
    rate: number
    pitch: number
  }
  asr: {
    lang: string
  }
  demo: {
    evaluationTimeoutMs: number
    localEvaluationTimeoutMs?: number
  }
}

export interface ConfigValidationResult {
  valid: boolean
  errors: string[]
}

// 校验原始对象，返回错误列表
export function validateConfig(raw: unknown): ConfigValidationResult {
  const errors: string[] = []
  const cfg = raw as Record<string, unknown>

  if (!cfg || typeof cfg !== 'object') {
    return { valid: false, errors: ['Config is not an object'] }
  }

  if (!cfg.aiProvider || typeof cfg.aiProvider !== 'string' || !(cfg.aiProvider as string).trim()) {
    errors.push('aiProvider is required (gemini | local)')
  }

  const gemini = cfg.gemini as Record<string, unknown> | undefined
  // gemini 字段仅当 aiProvider === 'gemini' 时强制要求；但为保持后续可切换，仍校验完整性并给出提示
  if (gemini) {
    if (cfg.aiProvider === 'gemini') {
      // apiKey 允许从环境变量注入，所以空字符串在文件层面不直接报错，运行时再检查
      // 但若两者皆空，给出警告
      const envKey = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GEMINI_API_KEY
      const hasKey = (gemini.apiKey && String(gemini.apiKey).trim()) || (envKey && envKey.trim())
      if (!hasKey) errors.push('gemini.apiKey is required (set VITE_GEMINI_API_KEY or config.gemini.apiKey)')
      if (!gemini.textModel || !String(gemini.textModel).trim()) errors.push('gemini.textModel is required')
    }
  } else if (cfg.aiProvider === 'gemini') {
    errors.push('gemini config is required when aiProvider is gemini')
  }

  const tts = cfg.tts as Record<string, unknown> | undefined
  if (!tts || !tts.lang || !String(tts.lang).trim()) errors.push('tts.lang is required')

  const demo = cfg.demo as Record<string, unknown> | undefined
  if (!demo || typeof demo.evaluationTimeoutMs !== 'number' || demo.evaluationTimeoutMs <= 0) {
    errors.push('demo.evaluationTimeoutMs must be a positive number')
  }
  if (demo && demo.localEvaluationTimeoutMs !== undefined) {
    if (typeof demo.localEvaluationTimeoutMs !== 'number' || demo.localEvaluationTimeoutMs <= 0) {
      errors.push('demo.localEvaluationTimeoutMs must be a positive number when provided')
    }
  }

  return { valid: errors.length === 0, errors }
}

// 合并环境变量的 apiKey
function resolveGeminiKey(cfg: AppConfig): string {
  const envKey = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GEMINI_API_KEY
  if (envKey && envKey.trim()) return envKey.trim()
  return cfg.gemini?.apiKey ?? ''
}

export async function loadConfig(): Promise<AppConfig> {
  const res = await fetch('/config.json')
  if (!res.ok) throw new Error('Config file not found (/config.json)')
  let raw: unknown
  try {
    raw = await res.json()
  } catch {
    throw new Error('Config file is not valid JSON')
  }
  const validation = validateConfig(raw)
  // 对于 gemini key 缺失，仅在 aiProvider=gemini 时视为错误；否则允许为空以便切到 local
  if (!validation.valid) {
    throw new Error('Config validation failed:\n' + validation.errors.join('\n'))
  }
  const cfg = raw as AppConfig
  // 注入环境变量的 key
  cfg.gemini.apiKey = resolveGeminiKey(cfg)
  return cfg
}
