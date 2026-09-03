import { useCallback, useEffect, useRef, useState } from 'react'
import type { AppConfig } from '../config/configLoader'
import { WebSpeechTTSService } from '../speech/ttsService'
import { WebSpeechASRService } from '../speech/asrService'
import { createAIProvider } from '../ai/providerFactory'
import type { EvaluationResult } from '../scoring/parseEvaluation'

export type DemoStatus =
  | 'Loading'
  | 'ShowingQuestion'
  | 'Recording'
  | 'Transcribing'
  | 'ShowingTranscript'
  | 'Evaluating'
  | 'ShowingResult'
  | 'Error'

export interface SceneQuestion {
  id: string
  text: string
  order: number
}

export interface SceneMeta {
  id: string
  title: string
  gradeLevel: string
  imageAlt: string
  imageDescription: string
}

export function useDemoSession(config: AppConfig | null) {
  const [status, setStatus] = useState<DemoStatus>('Loading')
  const [meta, setMeta] = useState<SceneMeta | null>(null)
  const [question, setQuestion] = useState<SceneQuestion | null>(null)
  const [allQuestions, setAllQuestions] = useState<SceneQuestion[]>([])
  const [imagePath] = useState('/scenes/scene01/image.jfif')
  const [imageBase64, setImageBase64] = useState<string | null>(null)
  const [imageMime, setImageMime] = useState<string>('image/jpeg')
  const [transcript, setTranscript] = useState('')
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [retryPrompt, setRetryPrompt] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [providerName, setProviderName] = useState<string>(() => config?.aiProvider ?? 'gemini')

  const ttsRef = useRef<WebSpeechTTSService | null>(null)
  const asrRef = useRef<WebSpeechASRService | null>(null)

  // 初始化 TTS/ASR
  useEffect(() => {
    if (!config) return
    const tts = new WebSpeechTTSService(config.tts)
    const asr = new WebSpeechASRService(config.asr)
    tts.onStart(() => setIsSpeaking(true))
    tts.onEnd(() => setIsSpeaking(false))
    tts.onError(() => setIsSpeaking(false))
    asr.onResult((t) => {
      setTranscript(t)
      setRetryPrompt(false)
      setStatus('ShowingTranscript')
    })
    asr.onEmptyResult(() => {
      setRetryPrompt(true)
      setStatus('ShowingQuestion')
    })
    asr.onError((err) => {
      setErrorMessage(err.message)
      setRetryPrompt(true)
      setStatus('ShowingQuestion')
    })
    ttsRef.current = tts
    asrRef.current = asr
    setProviderName(config.aiProvider)
    // 预热 voices
    if (tts.isAvailable()) window.speechSynthesis.getVoices()
  }, [config])

  // 加载场景与随机选题
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [metaRes, qRes] = await Promise.all([
          fetch('/scenes/scene01/meta.json'),
          fetch('/scenes/scene01/questions.json'),
        ])
        if (!metaRes.ok || !qRes.ok) throw new Error('Failed to load scene data')
        const metaJson = (await metaRes.json()) as SceneMeta
        const qJson = (await qRes.json()) as { questions: SceneQuestion[] }
        const sorted = [...qJson.questions].sort((a, b) => a.order - b.order)
        const picked = sorted[Math.floor(Math.random() * sorted.length)] ?? sorted[0]
        // 预加载图片 base64
        let base64: string | null = null
        let mime = 'image/jpeg'
        try {
          const imgRes = await fetch('/scenes/scene01/image.jfif')
          const blob = await imgRes.blob()
          mime = blob.type || 'image/jpeg'
          base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onloadend = () => {
              const dataUrl = reader.result as string
              const b64 = dataUrl.split(',')[1] ?? ''
              resolve(b64)
            }
            reader.onerror = () => reject(new Error('Failed to read image'))
            reader.readAsDataURL(blob)
          })
        } catch {
          // 忽略，降级为纯文字
        }
        if (cancelled) return
        setMeta(metaJson)
        setAllQuestions(sorted)
        setQuestion(picked)
        setImageBase64(base64)
        setImageMime(mime)
        setStatus('ShowingQuestion')
      } catch (e) {
        if (cancelled) return
        setErrorMessage((e as Error).message)
        setStatus('Error')
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  // 自动朗读
  const speakQuestion = useCallback(
    (text?: string) => {
      const q = text ?? question?.text
      if (!q || !ttsRef.current || !config) return
      if (!ttsRef.current.isAvailable()) return
      // 取消之前的
      ttsRef.current.interruptAndSpeak(q, config.tts.lang).catch(() => setIsSpeaking(false))
    },
    [question, config]
  )

  useEffect(() => {
    if (status === 'ShowingQuestion' && question) {
      const t = setTimeout(() => speakQuestion(), 400)
      return () => clearTimeout(t)
    }
  }, [status, question, speakQuestion])

  const startRecording = useCallback(() => {
    if (!asrRef.current || !config) return
    if (!asrRef.current.isAvailable()) {
      setErrorMessage('麦克风需要 HTTPS 环境，请用 https:// 或 http://localhost 访问。 / Microphone requires HTTPS or localhost.')
      return
    }
    setRetryPrompt(false)
    setErrorMessage(null)
    asrRef.current.startRecording(config.asr.lang)
    setStatus('Recording')
  }, [config])

  const stopRecording = useCallback(() => {
    asrRef.current?.stopRecording()
    // 立即进入转换中，按钮灰掉，避免用户反复点击
    setStatus('Transcribing')
  }, [])

  const updateTranscript = useCallback((t: string) => setTranscript(t), [])

  const pickAnotherQuestion = useCallback(() => {
    if (allQuestions.length <= 1) return
    const others = allQuestions.filter((q) => q.id !== question?.id)
    const next = others[Math.floor(Math.random() * others.length)]
    setQuestion(next)
    setTranscript('')
    setEvaluation(null)
    setErrorMessage(null)
    setRetryPrompt(false)
    setStatus('ShowingQuestion')
  }, [allQuestions, question])

  const submitAnswer = useCallback(async () => {
    if (!question || !config || !meta) return
    if (!transcript.trim()) {
      setErrorMessage('请先录音或输入你的回答 / Please record or type your answer first.')
      return
    }
    setStatus('Evaluating')
    setErrorMessage(null)
    try {
      const provider = createAIProvider(config, providerName)
      const result = await provider.evaluate({
        question: question.text,
        answer: transcript.trim(),
        imageBase64,
        imageMimeType: imageMime,
        imageDescription: meta.imageDescription,
      })
      setEvaluation(result)
      setStatus('ShowingResult')
    } catch (e) {
      setErrorMessage((e as Error).message)
      setStatus('Error')
    }
  }, [question, config, meta, transcript, providerName, imageBase64, imageMime])

  const retry = useCallback(() => {
    setErrorMessage(null)
    if (evaluation) {
      setStatus('ShowingResult')
    } else {
      setStatus('ShowingQuestion')
    }
  }, [evaluation])

  const stopSpeaking = useCallback(() => {
    ttsRef.current?.stop()
    setIsSpeaking(false)
  }, [])

  return {
    status,
    meta,
    question,
    imagePath,
    transcript,
    evaluation,
    errorMessage,
    retryPrompt,
    isSpeaking,
    providerName,
    setProviderName,
    speakQuestion: () => speakQuestion(),
    stopSpeaking,
    startRecording,
    stopRecording,
    updateTranscript,
    submitAnswer,
    pickAnotherQuestion,
    retry,
    ttsAvailable: ttsRef.current?.isAvailable() ?? true,
    asrAvailable: asrRef.current?.isAvailable() ?? true,
  }
}
