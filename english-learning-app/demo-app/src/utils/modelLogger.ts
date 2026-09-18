// modelLogger — 浏览器端持久化大模型交互日志，供下载排查“每次都在猜”
// 存储于 localStorage + 内存，ReportScreen 提供“下载日志”按钮，另可通过控制台 window.__modelLogger 获取

export interface ModelLogEntry {
  id: string
  timestamp: string // ISO
  provider: 'gemini' | 'local' | string
  mode: 'single' | 'batch'
  request: {
    imageMimeType?: string
    imageBase64Length?: number
    imageDescriptionPreview?: string
    items?: Array<{ questionId: string; question: string; answer: string }>
    question?: string
    answer?: string
    promptPreview?: string // 前 500 字
    maxTokens?: number
    useJsonMode?: boolean
    model?: string
  }
  response?: {
    elapsedMs: number
    status?: number
    finishReason?: string
    contentLength?: number
    contentPreview?: string // 前 800 字
    rawPreview?: string // 原始 HTTP 响应前 800
    truncated?: boolean
  }
  error?: string
}

const STORAGE_KEY = 'chat-with-me:model-logs'
const MAX_ENTRIES = 20

function load(): ModelLogEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw) as ModelLogEntry[]
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function save(entries: ModelLogEntry[]) {
  try {
    const toSave = entries.slice(-MAX_ENTRIES)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
  } catch {}
}

export const modelLogger = {
  append(entry: ModelLogEntry) {
    const entries = load()
    entries.push(entry)
    save(entries)
    // 同时 console 输出，方便 F12 直接看
    console.log(`[ModelLogger] ${entry.provider}/${entry.mode} ${entry.id}`, entry)
  },

  getAll(): ModelLogEntry[] {
    return load()
  },

  clear() {
    localStorage.removeItem(STORAGE_KEY)
  },

  download(filename = `model-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`) {
    const entries = load()
    const blob = new Blob([JSON.stringify(entries, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },

  downloadText(filename = `model-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`) {
    const entries = load()
    const lines = entries.map((e) => {
      return [
        `=== ${e.timestamp} [${e.provider}/${e.mode}] id=${e.id} ===`,
        `Request: ${JSON.stringify(e.request, null, 2).slice(0, 1200)}`,
        e.response ? `Response: elapsed=${e.response.elapsedMs}ms finish=${e.response.finishReason} len=${e.response.contentLength} truncated=${e.response.truncated}` : 'Response: <none>',
        e.response?.contentPreview ? `Content preview: ${e.response.contentPreview.slice(0, 800)}` : '',
        e.error ? `Error: ${e.error.slice(0, 1000)}` : '',
        '',
      ].join('\n')
    }).join('\n')
    const blob = new Blob([lines], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },
}

// 挂到 window 供控制台直接调用
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__modelLogger = modelLogger
}
