// TTS Service — 封装浏览器 SpeechSynthesis
import type { AppConfig } from '../config/configLoader'

export interface TTSService {
  isAvailable(): boolean
  isSpeaking(): boolean
  speak(text: string, lang: string): Promise<void>
  interruptAndSpeak(text: string, lang: string): Promise<void>
  stop(): void
  onStart(cb: () => void): void
  onEnd(cb: () => void): void
  onError(cb: (err: Error) => void): void
}

export class WebSpeechTTSService implements TTSService {
  private ttsConfig: AppConfig['tts']
  private startCbs: Array<() => void> = []
  private endCbs: Array<() => void> = []
  private errorCbs: Array<(err: Error) => void> = []
  private suppressNextStart = false

  constructor(ttsConfig: AppConfig['tts']) {
    this.ttsConfig = ttsConfig
  }

  isAvailable(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window
  }

  isSpeaking(): boolean {
    if (!this.isAvailable()) return false
    return window.speechSynthesis.speaking
  }

  // 内部：创建 utterance
  private createUtterance(text: string, lang: string): SpeechSynthesisUtterance {
    const utter = new SpeechSynthesisUtterance(text)
    utter.lang = lang || this.ttsConfig.lang
    utter.rate = this.ttsConfig.rate ?? 0.9
    utter.pitch = this.ttsConfig.pitch ?? 1.0
    // 尝试匹配 voice 名称
    if (this.ttsConfig.voice) {
      const voices = window.speechSynthesis.getVoices()
      const matched = voices.find((v) => v.name === this.ttsConfig.voice)
      if (matched) utter.voice = matched
    }
    utter.onstart = () => {
      if (this.suppressNextStart) {
        this.suppressNextStart = false
        return
      }
      this.startCbs.forEach((cb) => cb())
    }
    utter.onend = () => this.endCbs.forEach((cb) => cb())
    utter.onerror = (e) => this.errorCbs.forEach((cb) => cb(new Error((e as unknown as { error: string }).error || 'TTS error')))
    return utter
  }

  speak(text: string, lang: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.isAvailable()) {
        reject(new Error('TTS not available'))
        return
      }
      const utter = this.createUtterance(text, lang)
      const onEnd = () => {
        this.endCbs = this.endCbs.filter((cb) => cb !== wrappedEnd)
        this.errorCbs = this.errorCbs.filter((cb) => cb !== wrappedError)
        resolve()
      }
      const onError = (err: Error) => {
        this.endCbs = this.endCbs.filter((cb) => cb !== wrappedEnd)
        this.errorCbs = this.errorCbs.filter((cb) => cb !== wrappedError)
        reject(err)
      }
      const wrappedEnd = onEnd
      const wrappedError = onError
      // 临时监听本次
      this.onEnd(wrappedEnd)
      this.onError(wrappedError)
      window.speechSynthesis.speak(utter)
    })
  }

  async interruptAndSpeak(text: string, lang: string): Promise<void> {
    if (this.isSpeaking()) {
      this.suppressNextStart = true
      this.stop()
      // 给浏览器一点时间停止
      await new Promise((r) => setTimeout(r, 50))
    }
    return this.speak(text, lang)
  }

  stop(): void {
    if (this.isAvailable()) window.speechSynthesis.cancel()
  }

  onStart(cb: () => void): void {
    this.startCbs.push(cb)
  }
  onEnd(cb: () => void): void {
    this.endCbs.push(cb)
  }
  onError(cb: (err: Error) => void): void {
    this.errorCbs.push(cb)
  }
}
