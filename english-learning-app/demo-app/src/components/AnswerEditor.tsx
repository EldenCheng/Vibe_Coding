interface Props {
  transcript: string
  status: string
  retryPrompt: boolean
  onTranscriptChange: (t: string) => void
  onStartRecording: () => void
  onStopRecording: () => void
  onClearTranscript: () => void
  onSubmit: () => void
}

export function AnswerEditor({
  transcript,
  status,
  retryPrompt,
  onTranscriptChange,
  onStartRecording,
  onStopRecording,
  onClearTranscript,
  onSubmit,
}: Props) {
  const isRecording = status === 'Recording'
  const isTranscribing = status === 'Transcribing'
  const isSubmitting = status === 'SubmittingSingle' || status === 'Evaluating'
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
        {/* v0.2.7 清空重说：追加模式下说砸了可一键重来（录音中不清，避免与实时文本打架） */}
        {transcript.trim() && !isRecording && !isTranscribing && (
          <button type="button" className="clear-btn" onClick={onClearTranscript} aria-label="Clear and record again">
            🗑 清空重说 / Clear
          </button>
        )}
      </div>
      <div className="record-hint">停顿没关系，想好继续说；再次录音会接在后面 / Pauses are OK — recording again appends, or type below</div>

      {/* 文本编辑区 — Recording 时实时上屏，ShowingTranscript 时可编辑 */}
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
        disabled={!transcript.trim() || isSubmitting}
      >
        {isSubmitting ? '评分中… / Scoring…' : '提交并评分 / Submit & Score'}
      </button>
      {!canSubmit && status === 'ShowingQuestion' && <div className="submit-hint">录音或输入后即可提交</div>}
    </div>
  )
}
