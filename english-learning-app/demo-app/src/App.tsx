import { useEffect, useState } from 'react'
import { loadConfig, normalizeQuestionTransition, type AppConfig } from './config/configLoader'
import { usePresetSession } from './demo/usePresetSession'
import { SceneImageDisplay } from './components/SceneImageDisplay'
import { QuestionCard } from './components/QuestionCard'
import { AnswerEditor } from './components/AnswerEditor'
import { StartScreen } from './components/StartScreen'
import { SingleResultPanel } from './components/SingleResultPanel'
import { SummaryScreen } from './components/SummaryScreen'
import { QuestionTransition } from './components/QuestionTransition'
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
  const session = usePresetSession(config)
  const transition = normalizeQuestionTransition(config.demo.questionTransition)

  const showStart = session.status === 'Start'
  const showError = session.status === 'Error'
  // 答题态（图片下方为问题+录音）
  const answering =
    session.status === 'ShowingQuestion' ||
    session.status === 'Recording' ||
    session.status === 'Transcribing' ||
    session.status === 'ShowingTranscript'
  // 单题结果态（图片不动，下半区刷新为分数+折叠评价）
  const showSingle = session.status === 'SubmittingSingle' || session.status === 'ShowingSingleResult'
  const showSummary = session.status === 'ShowingSummary'
  const showQuestionArea = (answering || showSingle) && session.meta && session.currentQuestion

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
              <option value="glm">GLM 5.3 Flash (火山 Ark)</option>
              <option value="local">Local Gemma4 ({config.local.model})</option>
            </select>
          </label>
          <span className="secure-hint" title="ASR requires HTTPS or localhost">
            {session.asrAvailable ? '🎤 Ready' : '⚠️ Mic needs HTTPS/localhost'}
          </span>
        </div>
      </header>

      {/* 安全上下文提示 */}
      {!session.asrAvailable && !showStart && (
        <div className="banner warning">
          麦克风功能需要 HTTPS 环境，请通过 https:// 访问或使用 http://localhost。/ Microphone requires HTTPS or http://localhost.
        </div>
      )}

      {/* 开始页 */}
      {showStart && (
        <main className="main-content">
          <StartScreen onStart={session.startSession} />
        </main>
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
          <div className="result-actions" style={{ marginTop: 8 }}>
            <button type="button" className="secondary-btn small" onClick={session.retry}>
              重试 / Retry
            </button>
            <button type="button" className="secondary-btn small" onClick={session.backToStart}>
              返回开始页 / Start over
            </button>
          </div>
        </div>
      )}

      {/* 进度条：逐题（有几题算几题） */}
      {session.questions.length > 0 && !showStart && !showSummary && session.status !== 'Loading' && (
        <div className="progress-bar">
          <span className="progress-text">
            第 {session.currentIndex + 1} 题 / 共 {session.questions.length} 题{session.perQuestionResults.length > 0 ? ` · 已评分 ${session.perQuestionResults.length}` : ''}
          </span>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${(session.currentIndex / session.questions.length) * 100}%` }} />
          </div>
        </div>
      )}

      {/* 主内容：图片常驻不刷新，下半区按状态切换 */}
      {showQuestionArea && (
        <main className="main-content">
          <SceneImageDisplay imagePath={session.imagePath} alt={session.meta!.imageAlt} />

          {answering && (
            <QuestionTransition transitionKey={`${session.sceneId ?? 'scene'}-${session.currentIndex}`} effect={transition}>
              <QuestionCard
                questionText={session.currentQuestion!.text}
                level={session.currentQuestion!.level}
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
                onClearTranscript={session.clearTranscript}
                onSubmit={session.submitAnswer}
              />
            </QuestionTransition>
          )}

          {showSingle && (
            <SingleResultPanel
              result={session.singleResult}
              submitting={session.status === 'SubmittingSingle'}
              isLastQuestion={session.isLastQuestion}
              errorMessage={session.errorMessage}
              onRetry={session.retrySingleQuestion}
              onSkip={session.skipQuestion}
              onNext={session.nextQuestion}
              onSummary={session.goSummary}
            />
          )}

          {session.errorMessage && answering && (
            <div className="inline-error">{session.errorMessage}</div>
          )}
        </main>
      )}

      {/* 本地轻量汇总 */}
      {showSummary && (
        <main className="main-content">
          <SummaryScreen
            questions={session.questions}
            results={session.perQuestionResults}
            onRestart={session.restartSession}
            onBackToStart={session.backToStart}
          />
        </main>
      )}

      <footer className="app-footer">
        <span>Demo — 逐题即时评分 · 图片常驻同页出分 / Per-question scoring</span>
        <span className="footer-meta">{session.meta?.title ?? ''} · {session.meta?.gradeLevel ?? ''} · {session.meta?.id ?? ''}</span>
      </footer>
    </div>
  )
}
