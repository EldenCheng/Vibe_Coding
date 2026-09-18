// ASR Service — 封装浏览器 SpeechRecognition
// v0.2.7: 连续录音——continuous + interim 实时上屏；停顿/网络抖动导致的自发结束
//         在用户未按"停止"时自动重启续录（finalBase 跨重启保留）；用户停止后触发 onSessionEnd
import type { AppConfig } from '../config/configLoader'

export interface ASRService {
  isAvailable(): boolean
  startRecording(lang: string): void
  stopRecording(): void
  onResult(cb: (transcript: string) => void): void
  onSessionEnd(cb: (r: ASRSessionEndResult) => void): void
  onEmptyResult(cb: () => void): void // 兼容保留：会话结束且无文本时仍会触发
  onError(cb: (err: Error) => void): void
}

export interface ASRSessionEndResult {
  transcript: string // 本会话累计 final 文本（跨自动重启保留）
  hasText: boolean
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance
  }
}

interface SpeechRecognitionInstance {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onresult: ((
    e: {
      resultIndex?: number
      results: { [i: number]: { [j: number]: { transcript: string }; isFinal?: boolean }; length: number }
    }
  ) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}

const RESTART_DELAY_MS = 250 // 自动重启等待（给浏览器一点恢复时间）
const MAX_RESTARTS = 5 // 连续失败重启上限（有成功识别即重置计数）

export class WebSpeechASRService implements ASRService {
  private asrConfig: AppConfig['asr']
  private recognition: SpeechRecognitionInstance | null = null
  private resultCbs: Array<(t: string) => void> = []
  private sessionEndCbs: Array<(r: ASRSessionEndResult) => void> = []
  private emptyCbs: Array<() => void> = []
  private errorCbs: Array<(err: Error) => void> = []
  private shouldListen = false // 用户意图：仍处于录音中（未按停止）
  private sessionActive = false // 底层会话是否活跃（start 成功 → onend 之间）
  private finalBase = '' // 本会话累计 final 文本（跨自动重启保留）
  private restartCount = 0 // 连续失败重启计数
  private restartTimer: ReturnType<typeof setTimeout> | null = null
  private lang = ''

  constructor(asrConfig: AppConfig['asr']) {
    this.asrConfig = asrConfig
  }

  isAvailable(): boolean {
    if (typeof window === 'undefined') return false
    if (!window.isSecureContext) return false
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  }

  private createRecognition(): SpeechRecognitionInstance | null {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Ctor) return null
    const rec = new Ctor()
    rec.lang = this.lang || this.asrConfig.lang || 'en-US'
    // v0.2.7 核心：continuous 容忍停顿思考；interim 实时上屏
    rec.continuous = true
    rec.interimResults = true
    rec.maxAlternatives = 1
    rec.onresult = (e) => {
      if (this.recognition !== rec) return // 过期实例（已被新会话取代）忽略
      // 只把 isFinal 段落累计入 finalBase；interim 仅用于实时显示
      const start = e.resultIndex ?? 0
      let interim = ''
      for (let i = start; i < e.results.length; i++) {
        const res = e.results[i]
        const alt = res?.[0]
        if (!alt) continue
        if (res.isFinal) {
          const t = alt.transcript.trim()
          if (t) {
            this.finalBase = this.finalBase ? `${this.finalBase} ${t}` : t
            this.restartCount = 0 // 成功识别，重置失败连击
          }
        } else {
          interim += alt.transcript
        }
      }
      const interimTrim = interim.trim()
      const display = interimTrim
        ? (this.finalBase ? `${this.finalBase} ${interimTrim}` : interimTrim)
        : this.finalBase
      if (display) this.resultCbs.forEach((cb) => cb(display))
    }
    rec.onerror = (e) => {
      if (this.recognition !== rec) return
      if (
        e.error === 'no-speech' ||
        e.error === 'audio-capture' ||
        e.error === 'network' ||
        e.error === 'aborted'
      ) {
        // 可恢复错误：不外抛，交给 onend 走自动重启；最终无文本时走空结果提示
        return
      }
      // 致命错误（not-allowed / service-not-allowed 等）：终止本次录音
      this.shouldListen = false
      this.errorCbs.forEach((cb) => cb(new Error(e.error)))
    }
    rec.onend = () => {
      if (this.recognition !== rec) return // 过期实例忽略（旧会话被 abort 时会触发）
      this.sessionActive = false
      if (!this.shouldListen) {
        // 用户已按停止（或致命错误后）：会话结束，结算文本
        this.finishSession()
        return
      }
      // 用户未按停止却被结束（静音超时/网络抖动）：自动重启续录
      this.scheduleRestartOrFinish()
    }
    return rec
  }

  // 自动重启续录（达到上限则报错结算）；仅在 shouldListen 时生效
  private scheduleRestartOrFinish(): void {
    if (this.restartCount >= MAX_RESTARTS) {
      this.shouldListen = false
      this.errorCbs.forEach((cb) => cb(new Error('ASR restarted too many times, please tap record again')))
      this.finishSession()
      return
    }
    this.restartCount += 1
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      if (!this.shouldListen) {
        // 等待期间用户按了停止：直接结算
        this.finishSession()
        return
      }
      this.spawn()
    }, RESTART_DELAY_MS)
  }

  private spawn(): void {
    this.recognition = this.createRecognition()
    if (!this.recognition) {
      this.shouldListen = false
      this.errorCbs.forEach((cb) => cb(new Error('SpeechRecognition not available')))
      this.finishSession()
      return
    }
    try {
      this.recognition.start()
      this.sessionActive = true
    } catch {
      // start 失败（如上一会话尚未完全释放）：走重启路径（未 start 成功则无 onend）
      this.sessionActive = false
      this.scheduleRestartOrFinish()
    }
  }

  // 会话结算：把累计文本交给回调（有文本 → sessionEnd；无文本 → 兼容 empty + sessionEnd(false)）
  private finishSession(): void {
    const text = this.finalBase.trim()
    if (text) {
      this.sessionEndCbs.forEach((cb) => cb({ transcript: text, hasText: true }))
    } else {
      this.emptyCbs.forEach((cb) => cb())
      this.sessionEndCbs.forEach((cb) => cb({ transcript: '', hasText: false }))
    }
  }

  startRecording(lang: string): void {
    // 清理重启等待与旧会话（onend 由 "recognition !== rec" 守卫忽略，不会误重启）
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    if (this.recognition) {
      try {
        this.recognition.abort()
      } catch {
        // ignore
      }
    }
    this.recognition = null
    this.lang = lang || this.asrConfig.lang || 'en-US'
    this.shouldListen = true
    this.sessionActive = false
    this.finalBase = '' // 新会话从零累计（追加由 hook 层基于快照拼接）
    this.restartCount = 0
    this.spawn()
  }

  stopRecording(): void {
    this.shouldListen = false // 用户意图：结束录音
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    if (this.sessionActive && this.recognition) {
      try {
        this.recognition.stop() // 优雅停止：让最后的 final 结果冲刷完再 onend
      } catch {
        try {
          this.recognition.abort()
        } catch {
          // ignore
        }
      }
    } else {
      // 无活跃会话（正处重启等待窗口 / start 尚未成功）：直接结算
      this.finishSession()
    }
  }

  onResult(cb: (transcript: string) => void): void {
    this.resultCbs.push(cb)
  }
  onSessionEnd(cb: (r: ASRSessionEndResult) => void): void {
    this.sessionEndCbs.push(cb)
  }
  onEmptyResult(cb: () => void): void {
    this.emptyCbs.push(cb)
  }
  onError(cb: (err: Error) => void): void {
    this.errorCbs.push(cb)
  }
}
