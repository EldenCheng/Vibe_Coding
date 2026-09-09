// ASR Service — 封装浏览器 SpeechRecognition
import type { AppConfig } from '../config/configLoader'

export interface ASRService {
  isAvailable(): boolean
  startRecording(lang: string): void
  stopRecording(): void
  onResult(cb: (transcript: string) => void): void
  onEmptyResult(cb: () => void): void
  onError(cb: (err: Error) => void): void
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
  onresult: ((e: { results: { [i: number]: { [j: number]: { transcript: string } }; length: number } }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}

export class WebSpeechASRService implements ASRService {
  private asrConfig: AppConfig['asr']
  private recognition: SpeechRecognitionInstance | null = null
  private resultCbs: Array<(t: string) => void> = []
  private emptyCbs: Array<() => void> = []
  private errorCbs: Array<(err: Error) => void> = []
  private isRecording = false
  private hasResult = false
  private hasFiredEmptyOrResult = false

  constructor(asrConfig: AppConfig['asr']) {
    this.asrConfig = asrConfig
  }

  isAvailable(): boolean {
    if (typeof window === 'undefined') return false
    if (!window.isSecureContext) return false
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  }

  private createRecognition(lang: string): SpeechRecognitionInstance | null {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!Ctor) return null
    const rec = new Ctor()
    rec.lang = lang || this.asrConfig.lang || 'en-US'
    rec.continuous = false
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (e) => {
      this.hasResult = true
      this.hasFiredEmptyOrResult = true
      const lastIdx = e.results.length - 1
      const transcript = e.results[lastIdx]?.[0]?.transcript?.trim() ?? ''
      if (transcript) {
        this.resultCbs.forEach((cb) => cb(transcript))
      } else {
        this.emptyCbs.forEach((cb) => cb())
      }
    }
    rec.onerror = (e) => {
      if (e.error === 'no-speech' || e.error === 'audio-capture') {
        if (!this.hasFiredEmptyOrResult && !this.hasResult) {
          this.hasFiredEmptyOrResult = true
          this.emptyCbs.forEach((cb) => cb())
        }
        return
      }
      this.hasFiredEmptyOrResult = true
      this.errorCbs.forEach((cb) => cb(new Error(e.error)))
    }
    rec.onend = () => {
      this.isRecording = false
      if (!this.hasFiredEmptyOrResult && !this.hasResult) {
        setTimeout(() => {
          if (!this.hasFiredEmptyOrResult && !this.hasResult) {
            this.hasFiredEmptyOrResult = true
            this.emptyCbs.forEach((cb) => cb())
          }
        }, 50)
      }
    }
    return rec
  }

  startRecording(lang: string): void {
    // 若已在录音，先强制结束旧实例
    if (this.isRecording && this.recognition) {
      try {
        this.recognition.abort()
      } catch {
        // ignore
      }
      this.isRecording = false
    }
    this.hasResult = false
    this.hasFiredEmptyOrResult = false
    this.recognition = this.createRecognition(lang)
    if (!this.recognition) {
      this.errorCbs.forEach((cb) => cb(new Error('SpeechRecognition not available')))
      return
    }
    this.isRecording = true
    try {
      this.recognition.start()
    } catch (e) {
      this.isRecording = false
      this.errorCbs.forEach((cb) => cb(e as Error))
    }
  }

  stopRecording(): void {
    // 立即标记为不在录音，避免重复点击 start
    this.isRecording = false
    if (this.recognition) {
      try {
        this.recognition.stop()
      } catch {
        try {
          this.recognition.abort()
        } catch {
          // ignore
        }
      }
    }
  }

  onResult(cb: (transcript: string) => void): void {
    this.resultCbs.push(cb)
  }
  onEmptyResult(cb: () => void): void {
    this.emptyCbs.push(cb)
  }
  onError(cb: (err: Error) => void): void {
    this.errorCbs.push(cb)
  }
}
