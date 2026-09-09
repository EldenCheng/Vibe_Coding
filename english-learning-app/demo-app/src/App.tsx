import { useEffect, useState } from 'react'
import { loadConfig, type AppConfig } from './config/configLoader'
import { useDemoSession } from './demo/useDemoSession'
import { SceneImageDisplay } from './components/SceneImageDisplay'
import { QuestionCard } from './components/QuestionCard'
import { AnswerEditor } from './components/AnswerEditor'
import { WaitingOverlay } from './components/WaitingOverlay'
import { ResultPanel } from './components/ResultPanel'
import './App.css'

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)

  useEffect(() => {
    loadConfig()
      .then(setConfig)
      .catch((e) => setConfigError((e as Error).message))
  }, [])

  if (configError) {
    return (
      <div className="app error-screen">
        <h1>Configuration Error</h1>
        <pre className="error-pre">{configError}</pre>
        <p>请检查 demo-app/public/config.json 或 VITE_GEMINI_API_KEY 环境变量</p>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="app loading-screen">
        <div className="spinner large" />
        <p>加载配置中... / Loading config...</p>
      </div>
    )
  }

  return <DemoView config={config} />
}

function DemoView({ config }: { config: AppConfig }) {
  const session = useDemoSession(config)

  const showWaiting = session.status === 'Evaluating'
  const showResult = session.status === 'ShowingResult' && session.evaluation && session.question
  const showError = session.status === 'Error'

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">Chat With Me — Demo</h1>
        <div className="header-controls">
          <label className="provider-select-label">
            AI:
            <select
              value={session.providerName}
              onChange={(e) => session.setProviderName(e.target.value)}
              className="provider-select"
              aria-label="Select AI provider"
            >
              <option value="gemini">Gemini ({config.gemini.textModel})</option>
              <option value="local">Local Gemma4 ({config.local.model})</option>
            </select>
          </label>
          <span className="secure-hint" title="ASR requires HTTPS or localhost">
            {session.asrAvailable ? '🎤 Ready' : '⚠️ Mic needs HTTPS/localhost'}
          </span>
        </div>
      </header>

      {/* 安全上下文提示 */}
      {!session.asrAvailable && (
        <div className="banner warning">
          麦克风功能需要 HTTPS 环境，请通过 https:// 访问或使用 http://localhost。/ Microphone requires HTTPS or http://localhost.
        </div>
      )}

      {/* 加载场景 */}
      {session.status === 'Loading' && (
        <div className="loading-screen">
          <div className="spinner large" />
          <p>正在准备对话场景... / Preparing scene...</p>
        </div>
      )}

      {/* 错误横幅 */}
      {showError && (
        <div className="banner error">
          <p>{session.errorMessage}</p>
          <button type="button" className="secondary-btn small" onClick={session.retry}>
            重试 / Retry
          </button>
        </div>
      )}

      {/* 主内容：仅在非 Loading 且非 Result 时展示 */}
      {session.status !== 'Loading' && !showResult && session.meta && session.question && (
        <main className="main-content">
          <SceneImageDisplay imagePath={session.imagePath} alt={session.meta.imageAlt} />

          <QuestionCard
            questionText={session.question.text}
            isSpeaking={session.isSpeaking}
            ttsAvailable={session.ttsAvailable}
            onSpeak={session.speakQuestion}
            onStop={session.stopSpeaking}
          />

          <AnswerEditor
            transcript={session.transcript}
            status={session.status}
            retryPrompt={session.retryPrompt}
            onTranscriptChange={session.updateTranscript}
            onStartRecording={session.startRecording}
            onStopRecording={session.stopRecording}
            onSubmit={session.submitAnswer}
          />

          {session.errorMessage && session.status !== 'Error' && (
            <div className="inline-error">{session.errorMessage}</div>
          )}
        </main>
      )}

      {/* 等待遮罩 */}
      {showWaiting && <WaitingOverlay provider={session.providerName} />}

      {/* 结果页 */}
      {showResult && (
        <main className="main-content">
          <ResultPanel
            question={session.question!.text}
            answer={session.transcript}
            evaluation={session.evaluation!}
            onRetry={session.retry}
            onNewQuestion={session.pickAnotherQuestion}
          />
          <button type="button" className="secondary-btn" onClick={() => window.location.reload()}>
            重新开始 / Restart
          </button>
        </main>
      )}

      <footer className="app-footer">
        <span>Demo — 单场景单题闭环 / Single-scene single-question demo</span>
        <span className="footer-meta">{session.meta?.title ?? ''} · 固定 junior 难度</span>
      </footer>
    </div>
  )
}
