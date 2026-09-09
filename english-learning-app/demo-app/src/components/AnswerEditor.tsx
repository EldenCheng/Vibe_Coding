interface Props {
  transcript: string
  status: string
  retryPrompt: boolean
  onTranscriptChange: (t: string) => void
  onStartRecording: () => void
  onStopRecording: () => void
  onSubmit: () => void
}

export function AnswerEditor({
  transcript,
  status,
  retryPrompt,
  onTranscriptChange,
  onStartRecording,
  onStopRecording,
  onSubmit,
}: Props) {
  const isRecording = status === 'Recording'
  const isTranscribing = status === 'Transcribing'
  const canSubmit = status === 'ShowingTranscript' || !!transcript.trim()

  return (
    <div className="answer-editor">
      {/* 录音按钮区域 */}
      <div className="record-row">
        {retryPrompt && (
          <div className="retry-prompt">没有听清，请再试一次，或直接输入你的回答 / Didn&apos;t catch that — try again or type directly</div>
        )}
        {isRecording ? (
          <button type="button" className="record-btn recording" onClick={onStopRecording} aria-label="Stop recording">
            <span className="mic-icon">⏹</span> 停止录音 / Stop
            <span className="recording-pulse" />
          </button>
        ) : isTranscribing ? (
          <button type="button" className="record-btn transcribing" disabled aria-label="Converting">
            <span className="spinner small" aria-hidden />
            Please Wait for the Text Conversion... / 正在转换文字...
          </button>
        ) : (
          <button type="button" className="record-btn" onClick={onStartRecording} aria-label="Start recording">
            <span className="mic-icon">🎤</span> 点击录音 / Tap to record
          </button>
        )}
        <span className="record-hint">或在下方直接输入 / Or type below</span>
      </div>

      {/* 文本编辑区 — Recording 时只读提示，ShowingTranscript 时可编辑 */}
      <div className="transcript-area">
        <label htmlFor="transcript-input" className="transcript-label">
          Your answer
        </label>
        <textarea
          id="transcript-input"
          className="transcript-input"
          value={transcript}
          onChange={(e) => onTranscriptChange(e.target.value)}
          placeholder="Tap 🎤 to record, or type your answer here... / 点击麦克风录音，或在此输入..."
          rows={3}
        />
      </div>

      {/* 提交 */}
      <button
        type="button"
        className="submit-btn"
        onClick={onSubmit}
        disabled={!transcript.trim() || status === 'Evaluating'}
      >
        提交并评分 / Submit &amp; Score
      </button>
      {!canSubmit && status === 'ShowingQuestion' && <div className="submit-hint">录音或输入后即可提交</div>}
    </div>
  )
}
