interface Props {
  questionText: string
  isSpeaking: boolean
  ttsAvailable: boolean
  onSpeak: () => void
  onStop: () => void
  level?: number // 难度级别徽章 1/2/3/4
}

export function QuestionCard({ questionText, isSpeaking, ttsAvailable, onSpeak, onStop, level }: Props) {
  return (
    <div className="question-card">
      <div className="question-label">
        Question
        {level !== undefined && <span className="level-badge">Level {level}</span>}
      </div>
      <p className="question-text">{questionText}</p>
      <div className="question-actions">
        <button
          type="button"
          className={`speak-btn ${isSpeaking ? 'speaking' : ''}`}
          aria-label={isSpeaking ? 'Stop speaking' : 'Read the question'}
          onClick={isSpeaking ? onStop : onSpeak}
          disabled={!ttsAvailable}
        >
          <span className="speak-icon">{isSpeaking ? '🔊' : '🔈'}</span>
          {isSpeaking ? 'Stop' : 'Read'}
          {isSpeaking && <span className="pulse-dot" />}
        </button>
        {!ttsAvailable && <span className="tts-warning">TTS unavailable — text remains visible</span>}
      </div>
    </div>
  )
}
