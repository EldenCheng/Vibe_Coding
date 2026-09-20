// usePresetSession — v0.3.0 逐题即时评分（开始页 → 逐题同页出分 → 本地轻量汇总）
// 批量 submitBatch/collectAllResults 保留兼容（旧 ReportScreen 路径），主路径为 evaluateSingle
// 图片整场只加载一次（imagePath 不变）；下半区按状态切换答题/单题结果/汇总

import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppConfig } from '../config/configLoader'
import { normalizeImageStrategy, shouldSendImage } from '../config/configLoader'
import { audienceForAge } from '../scoring/parseEvaluation'
import { WebSpeechTTSService } from '../speech/ttsService'
import { WebSpeechASRService } from '../speech/asrService'
import { SceneEvaluator, type PresetEvaluationResult } from './sceneEvaluator'

export type PresetSessionStatus =
  | 'Start' // v0.3.0 开始页（未选年龄/题型）
  | 'Loading'
  | 'ShowingQuestion'
  | 'Recording'
  | 'Transcribing'
  | 'ShowingTranscript'
  | 'Submitting' // 旧批量兼容（保留）
  | 'SubmittingSingle' // v0.3.0 单题评分中
  | 'ShowingSingleResult' // v0.3.0 同页出分（默认折叠）
  | 'ShowingResults' // 旧批量等待（保留兼容）
  | 'ShowingReport' // 旧批量报告（保留兼容）
  | 'ShowingSummary' // v0.3.0 本地轻量汇总
  | 'Error'

export type AgeRange = '10-12' | '13-15' | '16-18'
export type QuestionKind = 'grounded' | 'open'
export type QuestionFilter = 'groundedOnly' | 'all'

export interface SessionSetup {
  ageRange: AgeRange
  filter: QuestionFilter
}

export interface SceneQuestion {
  id: string
  text: string
  order: number
  level?: number // 难度级别 1/2/3/4；缺失时按 Level 1 处理
  kind?: QuestionKind // v0.3.0 题型；缺失按 grounded 处理
}

export interface SceneMeta {
  id: string
  title: string
  gradeLevel: string
  audience?: string // 旧字段保留；v0.3.0 起受众由开始页年龄决定
  imageAlt: string
  imageDescription: string
  scoringDescription?: string // 单段按题聚焦描述，descriptionOnly 时替代发图
}

export interface SubmittedAnswer {
  questionId: string
  questionText: string
  answerText: string
  level?: number
  kind?: QuestionKind
}

const START_AGE_KEY = 'el-start-age'
const START_FILTER_KEY = 'el-start-filter'

// 差异化超时（批量，保留兼容）：传图档用大档，描述档用小档
function getBatchTimeout(config: AppConfig, providerName: string): number {
  const strategy = normalizeImageStrategy(config.demo.imageStrategy)
  if (providerName === 'local') {
    if (strategy === 'descriptionOnly') return 60000
    return Math.max(config.demo.localEvaluationTimeoutMs ?? 360000, 120000)
  }
  if (providerName === 'glm') {
    if (strategy === 'descriptionOnly') return 60000
    return Math.max(config.demo.glmEvaluationTimeoutMs ?? 120000, 80000)
  }
  if (strategy === 'descriptionOnly') return 45000
  return Math.max(config.demo.evaluationTimeoutMs ?? 120000, 80000)
}

// v0.3.0 单题超时：描述档小档，传图档中档（批量 120s/360s 太大，单题收紧）
function getSingleTimeout(config: AppConfig, providerName: string, hasImage: boolean): number {
  if (!hasImage) {
    if (providerName === 'local') return 60000
    if (providerName === 'glm') return 60000
    return 45000
  }
  if (providerName === 'local') return Math.max(Math.min(config.demo.localEvaluationTimeoutMs ?? 120000, 180000), 120000)
  if (providerName === 'glm') return Math.max(Math.min(config.demo.glmEvaluationTimeoutMs ?? 80000, 120000), 80000)
  return Math.max(Math.min(config.demo.evaluationTimeoutMs ?? 80000, 120000), 80000)
}

// 按 Level 分组随机抽题：过滤池里每级至多 1 题，空级跳过（有几题算几题）； usedIds 内存不重复
function pickQuestionsPerLevel(all: SceneQuestion[], usedIds: Set<string>, filter: QuestionFilter): SceneQuestion[] {
  const pool = filter === 'groundedOnly' ? all.filter((q) => (q.kind ?? 'grounded') === 'grounded') : [...all]
  const levels = Array.from(new Set(pool.map((q) => q.level ?? 1))).sort((a, b) => a - b)
  const picked: SceneQuestion[] = []
  for (const level of levels) {
    let candidates = pool.filter((q) => (q.level ?? 1) === level && !usedIds.has(q.id))
    if (candidates.length === 0) {
      // 该级在过滤池内已用尽：若该级还有题（全被用过）则重置该级；若该级本就无题则跳过
      const levelAll = pool.filter((q) => (q.level ?? 1) === level)
      if (levelAll.length === 0) continue
      for (const q of levelAll) usedIds.delete(q.id)
      candidates = levelAll
    }
    const chosen = candidates[Math.floor(Math.random() * candidates.length)]
    usedIds.add(chosen.id)
    picked.push(chosen)
  }
  picked.sort((a, b) => (a.level ?? 1) - (b.level ?? 1))
  return picked
}

// 年龄档 → 场景学段映射（v0.3.6 场景按学段过滤）
const GRADE_FOR_AGE: Record<AgeRange, string> = {
  '10-12': 'primary',
  '13-15': 'junior',
  '16-18': 'senior',
}

interface SceneIndexEntry {
  id: string
  gradeLevel?: string
}

// 场景解析：URL ?scene= 优先（需存在于 index.json，不受学段限制，便于调试/指定），
// 否则在所选年龄同学段的场景里随机选一个；该学段无场景直接报错（不跨学段回退）
async function resolveSceneId(ageRange: AgeRange): Promise<string> {
  const res = await fetch('/scenes/index.json')
  if (!res.ok) throw new Error('Failed to load scenes index (/scenes/index.json)')
  const idx = (await res.json()) as { scenes?: SceneIndexEntry[] }
  const list = Array.isArray(idx.scenes) ? idx.scenes : []
  if (list.length === 0) throw new Error('No scenes registered in /scenes/index.json')
  const requested = new URLSearchParams(window.location.search).get('scene')
  if (requested && list.some((s) => s.id === requested)) return requested
  const grade = GRADE_FOR_AGE[ageRange]
  const matching = list.filter((s) => s.gradeLevel === grade)
  if (matching.length === 0) {
    throw new Error(`该年龄段（${ageRange} 岁 · ${grade}）暂无对应场景，请返回选择其他年龄段 / No scenes available for the selected age group.`)
  }
  return matching[Math.floor(Math.random() * matching.length)].id
}

// 前端 canvas 压缩：把原始 base64 按最长边等比缩到 maxSide，JPEG quality 0.72
function compressImageBase64(base64: string, mime: string, maxSide: number, quality: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      let { width, height } = img
      if (width > maxSide || height > maxSide) {
        const scale = maxSide / Math.max(width, height)
        width = Math.round(width * scale)
        height = Math.round(height * scale)
      }
      // 若无需缩放且已是 jpeg 且原质量接近，可直接回传
      if (width === img.width && height === img.height && base64.length < 200000) {
        resolve(base64)
        return
      }
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) { resolve(base64); return }
      ctx.drawImage(img, 0, 0, width, height)
      const outMime = mime.includes('png') ? 'image/jpeg' : (mime || 'image/jpeg')
      const dataUrl = canvas.toDataURL(outMime, quality)
      const outB64 = dataUrl.split(',')[1] ?? ''
      // 若压缩后反而更大则回落原图
      if (outB64 && outB64.length < base64.length) resolve(outB64)
      else resolve(base64)
    }
    img.onerror = () => reject(new Error('Image load failed for compress'))
    img.src = `data:${mime};base64,${base64}`
  })
}

export function readSavedSetup(): SessionSetup | null {
  try {
    const age = window.localStorage.getItem(START_AGE_KEY) as AgeRange | null
    const filter = window.localStorage.getItem(START_FILTER_KEY) as QuestionFilter | null
    if (age === '10-12' || age === '13-15' || age === '16-18') {
      return { ageRange: age, filter: filter === 'groundedOnly' ? 'groundedOnly' : 'all' }
    }
  } catch {}
  return null
}

export function usePresetSession(config: AppConfig | null) {
  const [status, setStatus] = useState<PresetSessionStatus>('Start')
  const [meta, setMeta] = useState<SceneMeta | null>(null)
  const [questions, setQuestions] = useState<SceneQuestion[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [sceneId, setSceneId] = useState<string | null>(null)
  const [imageBase64, setImageBase64] = useState<string | null>(null)
  const [imageMime, setImageMime] = useState<string>('image/jpeg')
  const [transcript, setTranscript] = useState('')
  const [submittedAnswers, setSubmittedAnswers] = useState<SubmittedAnswer[]>([])
  const [perQuestionResults, setPerQuestionResults] = useState<PresetEvaluationResult[]>([])
  const [singleResult, setSingleResult] = useState<PresetEvaluationResult | null>(null)
  // 旧批量结果（保留兼容，ReportScreen 路径）
  const [evaluationResults, setEvaluationResults] = useState<PresetEvaluationResult[] | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [retryPrompt, setRetryPrompt] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [providerName, setProviderName] = useState<string>(() => config?.aiProvider ?? 'gemini')
  const [setup, setSetup] = useState<SessionSetup | null>(null)

  const ttsRef = useRef<WebSpeechTTSService | null>(null)
  const asrRef = useRef<WebSpeechASRService | null>(null)
  const evaluatorRef = useRef<SceneEvaluator | null>(null)
  const allQuestionsRef = useRef<SceneQuestion[]>([])
  const usedIdsRef = useRef<Set<string>>(new Set())
  const sessionBaseRef = useRef('')
  const audienceRef = useRef<string | undefined>(undefined)
  const setupRef = useRef<SessionSetup | null>(null)
  const loadingRef = useRef(false)

  const currentQuestion = questions[currentIndex] ?? null
  const isLastQuestion = currentIndex === questions.length - 1
  const imagePath = sceneId ? `/scenes/${sceneId}/image.jfif` : ''

  const applyAudience = useCallback((s: SessionSetup | null) => {
    const audience = audienceForAge(s?.ageRange)
    audienceRef.current = audience
    evaluatorRef.current?.setAudience(audience)
  }, [])

  useEffect(() => {
    if (!config) return
    const tts = new WebSpeechTTSService(config.tts)
    const asr = new WebSpeechASRService(config.asr)
    tts.onStart(() => setIsSpeaking(true))
    tts.onEnd(() => setIsSpeaking(false))
    tts.onError(() => setIsSpeaking(false))
    asr.onResult((t) => {
      // v0.2.7 追加续录：显示 = 本题已有文本 + 本次会话累计；录音中实时上屏，不切状态
      const base = sessionBaseRef.current.trim()
      setTranscript(base ? `${base} ${t}` : t)
      setRetryPrompt(false)
    })
    asr.onSessionEnd(({ transcript, hasText }) => {
      const base = sessionBaseRef.current.trim()
      if (hasText) {
        setTranscript(base ? `${base} ${transcript}` : transcript)
        setStatus('ShowingTranscript')
      } else if (base) {
        setStatus('ShowingTranscript')
      } else {
        setRetryPrompt(true)
        setStatus('ShowingQuestion')
      }
    })
    asr.onError((err) => {
      setErrorMessage(err.message)
      setRetryPrompt(true)
      setStatus('ShowingQuestion')
    })
    ttsRef.current = tts
    asrRef.current = asr
    setProviderName(config.aiProvider)
    evaluatorRef.current = new SceneEvaluator(config, config.aiProvider, getBatchTimeout(config, config.aiProvider))
    applyAudience(setupRef.current)
    if (tts.isAvailable()) window.speechSynthesis.getVoices()
  }, [config, applyAudience])

  useEffect(() => {
    if (config && evaluatorRef.current) {
      evaluatorRef.current.updateProvider(providerName, getBatchTimeout(config, providerName))
      evaluatorRef.current.setAudience(audienceRef.current)
    }
  }, [providerName, config])

  useEffect(() => {
    if (status === 'ShowingQuestion' && currentQuestion) {
      const t = setTimeout(() => speakQuestion(), 400)
      return () => clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, currentQuestion])

  // 场景加载（开始页确认后调用；restart 保持同场景仅重抽题）
  const loadScene = useCallback(async (s: SessionSetup, keepSceneId: string | null) => {
    if (!config || !evaluatorRef.current) return
    if (loadingRef.current) return
    loadingRef.current = true
    setStatus('Loading')
    setErrorMessage(null)
    try {
      const id = keepSceneId ?? (await resolveSceneId(s.ageRange))
      const base = `/scenes/${id}`
      const [metaRes, qRes] = await Promise.all([fetch(`${base}/meta.json`), fetch(`${base}/questions.json`)])
      if (!metaRes.ok || !qRes.ok) throw new Error('Failed to load scene data')
      const metaJson = (await metaRes.json()) as SceneMeta
      const qJson = (await qRes.json()) as { questions: SceneQuestion[] }
      const all = [...qJson.questions].sort((a, b) => (a.level ?? 1) - (b.level ?? 1) || a.order - b.order)
      const selected = all.some((q) => q.level !== undefined)
        ? pickQuestionsPerLevel(all, usedIdsRef.current, s.filter)
        : (s.filter === 'groundedOnly' ? all.filter((q) => (q.kind ?? 'grounded') === 'grounded') : all)
      if (selected.length === 0) throw new Error('No questions match the selected type / 所选类型下没有题目')
      allQuestionsRef.current = all
      // 图片整场加载一次（后续切题 imagePath 不变，不刷新）
      let base64: string | null = null
      let mime = 'image/jpeg'
      try {
        const imgRes = await fetch(`${base}/image.jfif`)
        const blob = await imgRes.blob()
        mime = blob.type || 'image/jpeg'
        const rawBase64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onloadend = () => {
            const dataUrl = reader.result as string
            resolve(dataUrl.split(',')[1] ?? '')
          }
          reader.onerror = () => reject(new Error('Failed to read image'))
          reader.readAsDataURL(blob)
        })
        // imageAll / 按题型(open)才需要压缩发图；descriptionOnly 仍保留原图展示用
        const maxSide = config?.demo.imageMaxSide ?? 1024
        const quality = config?.demo.imageQuality ?? 0.72
        try {
          base64 = rawBase64 ? await compressImageBase64(rawBase64, mime, maxSide, quality) : null
        } catch {
          base64 = rawBase64
        }
      } catch {}
      applyAudience(s)
      setSceneId(id)
      setMeta(metaJson)
      setImageBase64(base64)
      setImageMime(mime)
      setQuestions(selected)
      setCurrentIndex(0)
      setSubmittedAnswers([])
      setPerQuestionResults([])
      setSingleResult(null)
      setTranscript('')
      setErrorMessage(null)
      setRetryPrompt(false)
      setStatus('ShowingQuestion')
    } catch (e) {
      setErrorMessage((e as Error).message)
      setStatus('Error')
    } finally {
      loadingRef.current = false
    }
  }, [config, applyAudience])

  const startSession = useCallback((s: SessionSetup) => {
    setupRef.current = s
    setSetup(s)
    try {
      window.localStorage.setItem(START_AGE_KEY, s.ageRange)
      window.localStorage.setItem(START_FILTER_KEY, s.filter)
    } catch {}
    usedIdsRef.current = new Set()
    evaluatorRef.current?.reset()
    void loadScene(s, null)
  }, [loadScene])

  const speakQuestion = useCallback((text?: string) => {
    const q = text ?? currentQuestion?.text
    if (!q || !ttsRef.current || !config) return
    if (!ttsRef.current.isAvailable()) return
    // 10-12 岁降速 0.85（config 率基础上微调，可关：改回 config.tts.rate 即恢复）
    const rate = setupRef.current?.ageRange === '10-12' ? Math.min(config.tts.rate, 0.85) : config.tts.rate
    ttsRef.current.interruptAndSpeak(q, config.tts.lang, rate).catch(() => setIsSpeaking(false))
  }, [currentQuestion, config])

  const startRecording = useCallback(() => {
    if (!asrRef.current || !config) return
    if (!asrRef.current.isAvailable()) {
      setErrorMessage('麦克风需要 HTTPS 环境，请用 https:// 或 http://localhost 访问。 / Microphone requires HTTPS or localhost.')
      return
    }
    sessionBaseRef.current = transcript
    setRetryPrompt(false)
    setErrorMessage(null)
    asrRef.current.startRecording(config.asr.lang)
    setStatus('Recording')
  }, [config, transcript])

  const stopRecording = useCallback(() => {
    asrRef.current?.stopRecording()
    setStatus('Transcribing')
  }, [])

  const updateTranscript = useCallback((t: string) => setTranscript(t), [])

  // v0.3.0 逐题提交：单题评分，同页出分（图片不刷新）
  const submitAnswer = useCallback(async () => {
    if (!currentQuestion || !config || !meta || !evaluatorRef.current) return
    if (!transcript.trim()) {
      setErrorMessage('请先录音或输入你的回答 / Please record or type your answer first.')
      return
    }
    const answerText = transcript.trim()
    const kind: QuestionKind = currentQuestion.kind ?? 'grounded'
    const strategy = normalizeImageStrategy(config.demo.imageStrategy)
    const sendImage = shouldSendImage(strategy, kind)
    const desc = (!sendImage && meta.scoringDescription?.trim()) ? meta.scoringDescription.trim() : meta.imageDescription
    const req = {
      questionId: currentQuestion.id,
      questionText: currentQuestion.text,
      answer: answerText,
      level: currentQuestion.level,
      kind,
      ageRange: setupRef.current?.ageRange ?? '13-15',
      imageBase64: sendImage ? imageBase64 : null,
      imageMimeType: imageMime,
      imageDescription: desc,
    }
    const submitted: SubmittedAnswer = {
      questionId: currentQuestion.id,
      questionText: currentQuestion.text,
      answerText,
      level: currentQuestion.level,
      kind,
    }
    setSubmittedAnswers((prev) => {
      const withoutCurrent = prev.filter((p) => p.questionId !== currentQuestion.id)
      return [...withoutCurrent, submitted]
    })
    setStatus('SubmittingSingle')
    setErrorMessage(null)
    try {
      const res = await evaluatorRef.current.evaluateSingle(req, getSingleTimeout(config, providerName, sendImage))
      setSingleResult(res)
      setPerQuestionResults((prev) => {
        const withoutCurrent = prev.filter((p) => p.questionId !== res.questionId)
        return [...withoutCurrent, res]
      })
      setStatus('ShowingSingleResult')
      if (!res.result) {
        setErrorMessage(res.error ?? '评分失败，可重试或跳过 / Scoring failed, retry or skip.')
      }
    } catch (e) {
      setErrorMessage((e as Error).message)
      setStatus('ShowingSingleResult')
    }
  }, [currentQuestion, config, meta, transcript, imageBase64, imageMime, providerName])

  // 单题重试（用户确认：停在原题）
  const retrySingleQuestion = useCallback(async () => {
    if (!currentQuestion || !config || !meta || !evaluatorRef.current) return
    const lastAnswer = submittedAnswers.find((s) => s.questionId === currentQuestion.id)?.answerText ?? transcript.trim()
    if (!lastAnswer) return
    const kind: QuestionKind = currentQuestion.kind ?? 'grounded'
    const strategy = normalizeImageStrategy(config.demo.imageStrategy)
    const sendImage = shouldSendImage(strategy, kind)
    const desc = (!sendImage && meta.scoringDescription?.trim()) ? meta.scoringDescription.trim() : meta.imageDescription
    setStatus('SubmittingSingle')
    setErrorMessage(null)
    try {
      const res = await evaluatorRef.current.evaluateSingle({
        questionId: currentQuestion.id,
        questionText: currentQuestion.text,
        answer: lastAnswer,
        level: currentQuestion.level,
        kind,
        ageRange: setupRef.current?.ageRange ?? '13-15',
        imageBase64: sendImage ? imageBase64 : null,
        imageMimeType: imageMime,
        imageDescription: desc,
      }, getSingleTimeout(config, providerName, sendImage))
      setSingleResult(res)
      setPerQuestionResults((prev) => {
        const withoutCurrent = prev.filter((p) => p.questionId !== res.questionId)
        return [...withoutCurrent, res]
      })
      setStatus('ShowingSingleResult')
      if (!res.result) setErrorMessage(res.error ?? '评分失败，可重试或跳过 / Scoring failed, retry or skip.')
    } catch (e) {
      setErrorMessage((e as Error).message)
      setStatus('ShowingSingleResult')
    }
  }, [currentQuestion, config, meta, transcript, submittedAnswers, imageBase64, imageMime, providerName])

  // 跳过本题（记一条空结果，汇总时标 Skipped）
  const skipQuestion = useCallback(() => {
    if (!currentQuestion) return
    const skipped: PresetEvaluationResult = {
      questionId: currentQuestion.id,
      questionText: currentQuestion.text,
      answer: submittedAnswers.find((s) => s.questionId === currentQuestion.id)?.answerText ?? transcript.trim(),
      result: null,
      timedOut: false,
      errorKind: 'unknown',
      error: 'Skipped by user / 已跳过',
    }
    setPerQuestionResults((prev) => {
      const withoutCurrent = prev.filter((p) => p.questionId !== skipped.questionId)
      return [...withoutCurrent, skipped]
    })
    setSingleResult(null)
    if (isLastQuestion) {
      setTranscript('')
      setErrorMessage(null)
      setRetryPrompt(false)
      setStatus('ShowingSummary')
    } else {
      setTranscript('')
      setErrorMessage(null)
      setRetryPrompt(false)
      setCurrentIndex((i) => i + 1)
      setStatus('ShowingQuestion')
    }
  }, [currentQuestion, submittedAnswers, transcript, isLastQuestion])

  const nextQuestion = useCallback(() => {
    if (isLastQuestion) {
      setStatus('ShowingSummary')
      return
    }
    setSingleResult(null)
    setTranscript('')
    setErrorMessage(null)
    setRetryPrompt(false)
    setCurrentIndex((i) => i + 1)
    setStatus('ShowingQuestion')
  }, [isLastQuestion])

  const goSummary = useCallback(() => setStatus('ShowingSummary'), [])

  // 旧批量路径（保留兼容，不再是主路径）
  const retryBatch = useCallback(async () => {
    await retrySingleQuestion()
  }, [retrySingleQuestion])

  const retrySingle = useCallback(async (_questionId: string) => {
    await retrySingleQuestion()
  }, [retrySingleQuestion])

  const retry = useCallback(() => {
    setErrorMessage(null)
    if (singleResult) setStatus('ShowingSingleResult')
    else if (perQuestionResults.length > 0 && isLastQuestion) setStatus('ShowingSummary')
    else if (setup && questions.length === 0) {
      // 场景加载失败（网络/学段无场景等）：重走加载流程，避免停在空题屏
      void loadScene(setup, null)
    } else setStatus(setup ? 'ShowingQuestion' : 'Start')
  }, [singleResult, perQuestionResults.length, isLastQuestion, setup, questions.length, loadScene])

  const stopSpeaking = useCallback(() => {
    ttsRef.current?.stop()
    setIsSpeaking(false)
  }, [])

  const clearTranscript = useCallback(() => {
    setTranscript('')
    setRetryPrompt(false)
    setErrorMessage(null)
  }, [])

  const restartSession = useCallback(() => {
    evaluatorRef.current?.reset()
    const s = setupRef.current
    if (!s) {
      setStatus('Start')
      return
    }
    const all = allQuestionsRef.current
    if (all.length > 0) {
      setQuestions(pickQuestionsPerLevel(all, usedIdsRef.current, s.filter))
    } else {
      void loadScene(s, sceneId)
      return
    }
    setCurrentIndex(0)
    setSubmittedAnswers([])
    setPerQuestionResults([])
    setSingleResult(null)
    setEvaluationResults(null)
    setTranscript('')
    setErrorMessage(null)
    setRetryPrompt(false)
    setStatus('ShowingQuestion')
  }, [loadScene, sceneId])

  const backToStart = useCallback(() => {
    evaluatorRef.current?.reset()
    ttsRef.current?.stop()
    setIsSpeaking(false)
    setupRef.current = null
    setSetup(null)
    setQuestions([])
    setCurrentIndex(0)
    setSceneId(null)
    setMeta(null)
    setImageBase64(null)
    setSubmittedAnswers([])
    setPerQuestionResults([])
    setSingleResult(null)
    setEvaluationResults(null)
    setTranscript('')
    setErrorMessage(null)
    setRetryPrompt(false)
    setStatus('Start')
  }, [])

  return {
    status,
    meta,
    questions,
    currentQuestion,
    currentIndex,
    isLastQuestion,
    sceneId,
    imagePath,
    transcript,
    submittedAnswers,
    perQuestionResults,
    singleResult,
    evaluationResults,
    errorMessage,
    retryPrompt,
    isSpeaking,
    providerName,
    setProviderName,
    setup,
    startSession,
    backToStart,
    speakQuestion: () => speakQuestion(),
    stopSpeaking,
    startRecording,
    stopRecording,
    updateTranscript,
    clearTranscript,
    submitAnswer,
    retrySingleQuestion,
    skipQuestion,
    nextQuestion,
    goSummary,
    retrySingle, // 兼容旧 UI
    retryBatch, // 兼容旧 UI（实际为单题重试）
    retry,
    restartSession,
    ttsAvailable: ttsRef.current?.isAvailable() ?? true,
    asrAvailable: asrRef.current?.isAvailable() ?? true,
  }
}
