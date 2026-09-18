// Config Loader — 负责加载并校验 public/config.json
export interface AppConfig {
  aiProvider: string
  gemini: {
    apiKey: string
    textModel: string
    fallbackModel: string
  }
  glm?: {
    baseURL: string // 通常为 Vite 代理路径 /glm-v1
    directBaseURL?: string // 真实 Ark 端点，仅备注/排查用
    apiKey: string // 优先读环境变量 VITE_GLM_API_KEY
    model: string // e.g. "glm-5-3-flash" 或 ep-xxx 接入点 ID
    reasoningEffort?: string // GLM 思考强度 low/high/max，评分任务建议 low
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
    evaluationTimeoutMs: number // Gemini 传图档 120s / 描述档 45s
    localEvaluationTimeoutMs?: number // Local 传图档 360s / 描述档 60s
    glmEvaluationTimeoutMs?: number // GLM 传图档 120s / 描述档 60s
    imageStrategy?: ImageStrategy | 'image' // v0.3.0 三档；旧值 image 兼容映射为 imageAll
    imageMaxSide?: number // 传图档前端压缩最长边，默认 1024
    imageQuality?: number // JPEG 质量 0-1，默认 0.72
    questionTransition?: QuestionTransition // v0.3.0 切题转场，缺省 flip
  }
}

// v0.3.0 三档上传策略：descriptionOnly 全发描述；imageForOpenOnly 按题型；imageAll 全发原图
export type ImageStrategy = 'descriptionOnly' | 'imageForOpenOnly' | 'imageAll'
// v0.3.0 切题转场
export type QuestionTransition = 'none' | 'fade' | 'slide' | 'flip' | 'scatter' | 'random'
export type QuestionKind = 'grounded' | 'open'

const IMAGE_STRATEGIES: ImageStrategy[] = ['descriptionOnly', 'imageForOpenOnly', 'imageAll']
const TRANSITIONS: QuestionTransition[] = ['none', 'fade', 'slide', 'flip', 'scatter', 'random']

// 归一化：旧值 image → imageAll；缺省 → imageForOpenOnly（按题型分流主模式）
export function normalizeImageStrategy(raw: unknown): ImageStrategy {
  if (raw === 'image' || raw === 'imageAll') return 'imageAll'
  if (raw === 'descriptionOnly' || raw === 'imageForOpenOnly') return raw
  return 'imageForOpenOnly'
}

// 单题是否发原图：descriptionOnly 全否；imageAll 全是；imageForOpenOnly 仅 open 题发图
export function shouldSendImage(strategy: ImageStrategy, kind: QuestionKind | undefined): boolean {
  if (strategy === 'descriptionOnly') return false
  if (strategy === 'imageAll') return true
  return (kind ?? 'grounded') === 'open'
}

export function normalizeQuestionTransition(raw: unknown): QuestionTransition {
  return TRANSITIONS.includes(raw as QuestionTransition) ? (raw as QuestionTransition) : 'flip'
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

  // glm 字段仅当 aiProvider === 'glm' 时强制要求；其余情况允许缺省以便后续切换
  if (cfg.aiProvider === 'glm') {
    const glm = cfg.glm as Record<string, unknown> | undefined
    if (!glm) {
      errors.push('glm config is required when aiProvider is glm')
    } else {
      const envKey = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GLM_API_KEY
      const hasKey = (glm.apiKey && String(glm.apiKey).trim()) || (envKey && envKey.trim())
      if (!hasKey) errors.push('glm.apiKey is required (set VITE_GLM_API_KEY or config.glm.apiKey)')
      if (!glm.model || !String(glm.model).trim()) errors.push('glm.model is required')
      if (!glm.baseURL || !String(glm.baseURL).trim()) errors.push('glm.baseURL is required')
    }
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
  if (demo && demo.glmEvaluationTimeoutMs !== undefined) {
    if (typeof demo.glmEvaluationTimeoutMs !== 'number' || demo.glmEvaluationTimeoutMs <= 0) {
      errors.push('demo.glmEvaluationTimeoutMs must be a positive number when provided')
    }
  }
  if (demo && demo.imageStrategy !== undefined) {
    const v = demo.imageStrategy as string
    if (v !== 'image' && !(IMAGE_STRATEGIES as string[]).includes(v)) {
      errors.push('demo.imageStrategy must be "descriptionOnly" | "imageForOpenOnly" | "imageAll" (legacy "image" maps to "imageAll")')
    }
  }
  if (demo && demo.questionTransition !== undefined) {
    if (!(TRANSITIONS as string[]).includes(demo.questionTransition as string)) {
      errors.push('demo.questionTransition must be "none" | "fade" | "slide" | "flip" | "scatter" | "random"')
    }
  }
  if (demo && demo.imageMaxSide !== undefined) {
    if (typeof demo.imageMaxSide !== 'number' || demo.imageMaxSide < 256 || demo.imageMaxSide > 4096) {
      errors.push('demo.imageMaxSide must be a number in [256, 4096] when provided')
    }
  }
  if (demo && demo.imageQuality !== undefined) {
    if (typeof demo.imageQuality !== 'number' || demo.imageQuality <= 0 || demo.imageQuality > 1) {
      errors.push('demo.imageQuality must be a number in (0, 1] when provided')
    }
  }

  return { valid: errors.length === 0, errors }
}

// 合并环境变量的 apiKey（Gemini / GLM 同模式：环境变量优先，回落 config.json 明文）
function resolveKeyFromEnv(envName: string, fallback: string | undefined): string {
  const envKey = (import.meta as unknown as { env: Record<string, string> }).env?.[envName]
  if (envKey && envKey.trim()) return envKey.trim()
  return fallback ?? ''
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
  cfg.gemini.apiKey = resolveKeyFromEnv('VITE_GEMINI_API_KEY', cfg.gemini?.apiKey)
  if (cfg.glm) cfg.glm.apiKey = resolveKeyFromEnv('VITE_GLM_API_KEY', cfg.glm.apiKey)
  return cfg
}
