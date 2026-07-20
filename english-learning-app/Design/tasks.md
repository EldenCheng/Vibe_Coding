# Implementation Plan: English Learning App

## Overview

Build a React TypeScript SPA for interactive English learning. The app generates AI images via Google Gemini, conducts three-round spoken Q&A sessions, records and evaluates children's answers using the Web Speech API, and persists session history in Firebase Firestore. Implementation follows the session state machine defined in the design and the provider abstraction pattern.

## Tasks

- [ ] 1. Project setup and core TypeScript interfaces
  - Scaffold a React + TypeScript + Vite project
  - Install dependencies: `firebase`, `@google/generative-ai`, `fast-check`, `vitest`, `@vitest/ui`, `axe-core`
  - Create directory structure: `src/types`, `src/services`, `src/hooks`, `src/components`, `src/utils`
  - Define all TypeScript interfaces and types from the design: `Profile`, `GradeLevel`, `Session`, `Round`, `EvaluationScores`, `Report`, `AIProviderInterface`, `GeneratedImage`, `QuestionParams`, `EvaluationParams`, `EncouragementParams`, `ReportParams`, `TTSService`, `ASRService`
  - Create `src/types/index.ts` exporting all interfaces
  - _Requirements: 1.1, 2.1, 6.2, 8.1_

- [ ] 2. Config loader and validation
  - [ ] 2.1 Implement config loader
    - Create `public/config.json` with the schema defined in the design (placeholder values)
    - Create `src/utils/configLoader.ts` that fetches and parses `config.json` at startup
    - Implement `validateConfig(config)` function that checks all required fields: `aiProvider`, `[provider].apiKey`, `[provider].imageModel`, `[provider].textModel`, `tts.lang`, `firebase.projectId`, `firebase.apiKey`
    - Return a typed `AppConfig` object on success or a structured error on failure
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 2.2 Write property test for config validation (Property 7)
    - **Property 7: Config validation correctly classifies configs**
    - Generate arbitrary config objects with at least one required field missing → assert `validateConfig` returns failure
    - Generate arbitrary config objects with all required fields present and non-empty → assert `validateConfig` returns success
    - **Validates: Requirements 10.2, 10.4**

  - [ ]* 2.3 Write unit tests for config loader
    - Test: valid full config returns success
    - Test: missing `apiKey` returns error with field name
    - Test: empty string `projectId` returns error
    - Test: entirely missing config object returns error
    - _Requirements: 10.2, 10.4_

- [ ] 3. Firebase service layer
  - [ ] 3.1 Implement Firebase initialization and Firestore service
    - Create `src/services/firebaseService.ts`
    - Initialize Firebase app using config values loaded in Task 2
    - Implement `firestoreService` with functions: `createProfile`, `updateProfile`, `deleteProfile`, `getProfiles`, `saveSession`, `getSessionsByProfile`, `getSessionById`
    - Use the Firestore collection structure: `users/{userId}/profiles/{profileId}` and `users/{userId}/sessions/{sessionId}`
    - Enable offline persistence using Firebase SDK's built-in support
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 8.5, 9.4_

  - [ ] 3.2 Implement Firebase Authentication wrapper
    - Create `src/services/authService.ts` with anonymous sign-in (or simple email/password) so Firestore security rules can enforce per-user data isolation
    - Create `src/components/AuthWrapper.tsx` that signs in on mount and renders children only when authenticated
    - _Requirements: 1.5, 9.4_

- [ ] 4. Profile validator and management logic
  - [ ] 4.1 Implement profile name validator
    - Create `src/utils/profileValidator.ts`
    - Implement `validateProfileName(name: string): { valid: boolean; error?: string }` — reject empty strings and whitespace-only strings
    - _Requirements: 1.6_

  - [ ]* 4.2 Write property test for profile name whitespace rejection (Property 1)
    - **Property 1: Profile name whitespace rejection**
    - Generate strings composed entirely of whitespace characters (space, tab, newline, carriage return) with length ≥ 1 → assert `validateProfileName` returns `{ valid: false }`
    - **Validates: Requirements 1.6**

  - [ ] 4.3 Implement profile serialization / deserialization
    - Create `src/utils/profileSerializer.ts` with `serializeProfile(profile: Profile)` and `deserializeProfile(doc: FirestoreDoc): Profile`
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ]* 4.4 Write property test for profile round-trip serialization (Property 2)
    - **Property 2: Profile round-trip serialization**
    - Generate arbitrary valid profiles (non-empty name, valid grade level) → serialize → deserialize → assert deep equality with the original
    - **Validates: Requirements 1.1, 1.2**

- [ ] 5. AI provider abstraction and Gemini adapter
  - [ ] 5.1 Implement AI provider factory and Gemini adapter
    - Create `src/services/ai/AIProviderInterface.ts` (re-export the interface from types)
    - Create `src/services/ai/GeminiProvider.ts` implementing `AIProviderInterface`
    - Implement `generateImage`, `generateQuestion`, `evaluateAnswer`, `generateEncouragement`, `generateReport` methods using `@google/generative-ai` SDK
    - Create `src/services/ai/providerFactory.ts` with `createProvider(config: AppConfig): AIProviderInterface`
    - _Requirements: 2.1, 2.3, 3.1, 6.1, 7.1, 8.1, 10.5_

  - [ ]* 5.2 Write property test for provider factory (Property 8)
    - **Property 8: Provider factory returns correct adapter**
    - For any supported provider name in the config, `createProvider` SHALL return an object implementing `AIProviderInterface` (check all required method names are present as functions)
    - **Validates: Requirements 10.5**

  - [ ] 5.3 Implement question prompt builder
    - Create `src/utils/promptBuilder.ts` with `buildQuestionPrompt(params: QuestionParams): string`
    - Include grade-level-specific instructions as defined in the design
    - Include continuity clause for Round 2 and Round 3 (embed previous question texts)
    - `imageDescription` is the description of the currently displayed image regardless of whether it came from the AI provider or a fallback — the builder must accept and embed both sources identically (Req 2.3)
    - _Requirements: 2.3, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 5.4 Write property test for grade-level question prompts (Property 4)
    - **Property 4: Grade-level-specific question prompts**
    - For each grade level, assert the built prompt contains that grade's instruction vocabulary and does NOT contain the other grades' instruction vocabulary
    - **Validates: Requirements 3.2, 3.3, 3.4**

  - [ ]* 5.5 Write property test for round continuity in prompts (Property 5)
    - **Property 5: Round 2 and 3 prompts include prior context**
    - For any session with at least one completed round, assert the next round's prompt contains the text of all previous questions
    - **Validates: Requirements 3.6**

  - [ ] 5.6 Implement evaluation prompt builder and response parser
    - Create `src/utils/evaluationParser.ts` with `buildEvaluationPrompt(params: EvaluationParams): string` and `parseEvaluationResponse(raw: string): EvaluationScores | Partial<EvaluationScores>`
    - Handle malformed JSON gracefully — parse what is available, default missing dimensions to null
    - _Requirements: 6.1, 6.2, 6.4_

  - [ ]* 5.7 Write unit tests for evaluation response parser
    - Test: valid JSON returns all four scores
    - Test: malformed JSON returns partial scores without throwing
    - Test: missing `grammar` field returns null for that dimension
    - _Requirements: 6.2, 6.4_

- [ ] 6. Composite score calculator
  - [ ] 6.1 Implement composite score calculator
    - Create `src/utils/scoreCalculator.ts` with `calculateCompositeScore(rounds: Round[]): number`
    - Use equal weighting (0.25 each) across all four dimensions and all three rounds
    - Clamp output to [0, 100] and round to nearest integer
    - _Requirements: 8.2_

  - [ ]* 6.2 Write property test for composite score range (Property 6)
    - **Property 6: Composite score stays within valid range**
    - Generate arrays of exactly 3 rounds, each with four dimension scores in [0, 100] → assert `calculateCompositeScore` returns a value in [0, 100]
    - **Validates: Requirements 8.2**

  - [ ]* 6.3 Write unit tests for composite score calculator
    - Test: all scores 0 → composite 0
    - Test: all scores 100 → composite 100
    - Test: mixed scores → correct weighted average
    - _Requirements: 8.2_

- [ ] 7. Session history sorter
  - [ ] 7.1 Implement history sort utility
    - Create `src/utils/historySorter.ts` with `sortSessionsChronological(sessions: Session[]): Session[]` that returns sessions sorted in reverse-chronological order (most recent first)
    - _Requirements: 9.2_

  - [ ]* 7.2 Write property test for session history ordering (Property 10)
    - **Property 10: Session history is chronologically ordered**
    - Generate arbitrary lists of sessions with random `createdAt` timestamps → assert the returned list is sorted most-recent-first regardless of insertion order
    - **Validates: Requirements 9.2**

- [ ] 8. Checkpoint — core utilities and services complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Speech services (TTS and ASR)
  - [ ] 9.1 Implement TTS service
    - Create `src/services/ttsService.ts` implementing `TTSService` using `window.SpeechSynthesis`
    - `isAvailable()` returns false if `window.speechSynthesis` is undefined
    - Expose `onStart`, `onEnd`, `onError` callbacks; implement `speak`, `stop`, `isSpeaking()`, and `interruptAndSpeak()`
    - `isSpeaking()` returns true while `SpeechSynthesis.speaking` is true
    - `interruptAndSpeak(text, lang)` calls `stop()` then `speak()` as a single atomic operation; the visual indicator cycle resets immediately on the call site — `onStart` is NOT fired for this path (Req 4.6)
    - `onStart` callback fires ONLY when TTS transitions from the idle (default) state to speaking; it must NOT fire during `interruptAndSpeak` while already speaking (Req 4.3)
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ] 9.2 Implement ASR service
    - Create `src/services/asrService.ts` implementing `ASRService` using `window.SpeechRecognition` (with webkit prefix fallback)
    - `isAvailable()` returns false if neither `SpeechRecognition` nor `webkitSpeechRecognition` is present
    - Expose three distinct callbacks: `onResult(cb)` for a non-empty transcript, `onEmptyResult(cb)` for a silent/empty recording with no technical failure, and `onError(cb)` for technical failures (mic unavailable, API error, etc.)
    - When recording ends with an empty transcript and no technical failure, fire `onEmptyResult` only — do NOT fire `onError` (Req 5.7)
    - When a technical failure occurs, fire `onError` only — do NOT fire `onEmptyResult` (Req 5.6)
    - _Requirements: 5.2, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 9.3 Write unit tests for TTS and ASR availability detection
    - Test: `ttsService.isAvailable()` returns false when `window.speechSynthesis` is undefined
    - Test: `asrService.isAvailable()` returns false when both `SpeechRecognition` variants are absent
    - Test: `ttsService.isSpeaking()` returns true while speech is active and false after `stop()`
    - Test: `interruptAndSpeak()` calls `stop()` then `speak()` and does NOT fire `onStart` when already speaking (Req 4.3, 4.6)
    - Test: `ttsService.onStart` fires when `speak()` is called from idle state
    - Test: `asrService.onEmptyResult` fires (and `onError` does NOT fire) when recording ends with an empty transcript and no technical failure (Req 5.7)
    - Test: `asrService.onError` fires (and `onEmptyResult` does NOT fire) on a technical failure such as mic unavailable (Req 5.6)
    - _Requirements: 4.3, 4.5, 4.6, 5.6, 5.7_

- [ ] 10. Session state machine
  - [ ] 10.1 Implement session state machine hook
    - Create `src/hooks/useSession.ts` implementing the state machine from the design diagram
    - States: `Idle`, `GeneratingImage`, `GeneratingQuestion`, `AwaitingAnswer`, `Recording`, `Transcribing`, `Evaluating`, `ShowingScores`, `GeneratingEncouragement`, `RoundComplete`, `GeneratingReport`, `ShowingReport`, `Error`
    - Expose `state`, `dispatch`, `sessionData`, and `error` to the UI layer
    - Integrate AI provider, TTS service, ASR service, and Firestore service
    - _Requirements: 2.1, 2.2, 2.3, 5.2, 5.4, 6.1, 7.1, 7.3, 7.4, 8.1_

  - [ ]* 10.2 Write property test for session not terminating before three rounds (Property 9)
    - **Property 9: Session does not terminate before three rounds**
    - Generate session states with `rounds.length < 3` → assert the state is NOT `ShowingReport` or `complete`
    - **Validates: Requirements 7.4**

  - [ ]* 10.3 Write unit tests for session state machine transitions
    - Test: `startSession()` from `Idle` transitions to `GeneratingImage`
    - Test: `imageError` from `GeneratingImage` transitions to `Error`
    - Test: error state entry always sets the error banner visible AND the retry action present, even simultaneously — banner is never suppressed (Req 2.5)
    - Test: `imageReady` from `GeneratingImage` using a fallback-image description transitions to `GeneratingQuestion` (Req 2.3)
    - Test: question prompt built in `GeneratingQuestion` after a fallback image contains the fallback image's description (Req 2.3)
    - Test: `transcriptEmpty` from `Transcribing` returns to `AwaitingAnswer` without setting error state (Req 5.7)
    - Test: after round 3 complete, state transitions to `GeneratingReport`
    - Test: `retry()` from `Error` returns to `Idle`
    - _Requirements: 2.3, 2.5, 5.6, 5.7, 7.3, 7.4_

- [ ] 11. Checkpoint — state machine and speech services complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. UI components — profile management
  - [ ] 12.1 Implement `ProfileSelector` component
    - Create `src/components/ProfileSelector.tsx`
    - List all profiles from Firestore with name and grade level displayed
    - Include "Create New Profile" button
    - Show loading indicator while profiles are fetching
    - _Requirements: 1.4, 9.5_

  - [ ] 12.2 Implement `ProfileEditor` component
    - Create `src/components/ProfileEditor.tsx`
    - Form fields: name (text input), grade level (radio or select: Primary / Junior / Senior)
    - Validate name on submit using `validateProfileName`; display inline error if invalid
    - Support both create and edit modes; trigger `createProfile` or `updateProfile` on Firestore
    - Include delete button (with confirmation) that calls `deleteProfile` and removes all sessions
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [ ]* 12.3 Write unit tests for ProfileEditor validation
    - Test: submitting a whitespace-only name shows error and does not call Firestore
    - Test: submitting valid name and grade level calls `createProfile`
    - _Requirements: 1.6_

- [ ] 13. UI components — session view
  - [ ] 13.1 Implement `ImageDisplay` component
    - Create `src/components/ImageDisplay.tsx`
    - Display base64 image returned by Gemini with a loading skeleton while generating
    - Use `alt` text from `imageDescription` for accessibility
    - On AI image or question generation failure, always render the error banner AND the retry button together — the banner must never be suppressed when a retry option is present (Req 2.5)
    - _Requirements: 2.2, 2.5, 11.3, 11.5_

  - [ ] 13.2 Implement `QuestionCard` with TTS button
    - Create `src/components/QuestionCard.tsx`
    - Display question text at ≥16px font size
    - Include speaker icon button; on click call `ttsService.speak()`
    - Animate icon while TTS is playing; restore on end
    - If TTS unavailable, show notification and disable speaker button
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 11.3_

  - [ ] 13.3 Implement `RecordButton` component
    - Create `src/components/RecordButton.tsx`
    - Prominent microphone button; on press call `asrService.startRecording()`, on release/tap call `stopRecording()`
    - Show pulsing animation while recording
    - If ASR unavailable, show browser compatibility warning (suggest Chrome/Edge)
    - _Requirements: 5.1, 5.2, 5.3, 5.6_

  - [ ] 13.4 Implement `TranscriptDisplay` and `ScorePanel` components
    - Create `src/components/TranscriptDisplay.tsx` — display transcribed text; if empty prompt retry
    - Create `src/components/ScorePanel.tsx` — display all four dimension scores after evaluation; show "unavailable" for null scores
    - _Requirements: 5.5, 5.7, 6.3, 6.4_

  - [ ] 13.5 Implement `EncouragementCard` component
    - Create `src/components/EncouragementCard.tsx`
    - Display AI-generated encouragement message in a warm, child-friendly style
    - Auto-advance to next round after showing encouragement (after a brief display delay)
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 13.6 Implement `ReportScreen` component
    - Create `src/components/ReportScreen.tsx`
    - Display composite score prominently, written analysis (≤150 words), and all round scores
    - If report generation failed, show individual round scores and "Report unavailable" message
    - Include "Back to Profiles" navigation button
    - _Requirements: 8.2, 8.3, 8.4, 8.6_

- [ ] 14. UI components — history view
  - [ ] 14.1 Implement `SessionHistoryList` and `SessionDetailView` components
    - Create `src/components/SessionHistoryList.tsx` — chronological list of past sessions using `sortSessionsChronological`; show date and composite score per entry; show loading indicator while loading
    - Do NOT render any session rows until ALL session data for the selected Profile has fully loaded from Firebase — hold back partial results and keep the loading indicator visible until the entire load resolves (Req 9.5)
    - Create `src/components/SessionDetailView.tsx` — full session details: questions, transcripts, dimension scores, report
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

  - [ ]* 14.2 Write unit tests for session history list
    - Test: sessions displayed in reverse-chronological order
    - Test: loading indicator shown while `isLoading` is true
    - Test: no session rows are rendered while `isLoading` is true (partial data must not appear) (Req 9.5)
    - Test: session rows appear only after the loading state resolves to false with full data
    - _Requirements: 9.2, 9.5_

- [ ] 15. Top-level app wiring and routing
  - [ ] 15.1 Implement `App`, `ConfigGuard`, and routing
    - Create `src/App.tsx` as the root component
    - Create `src/components/ConfigGuard.tsx` — load config on mount; if invalid display configuration error screen with field-level detail and block navigation; otherwise render children
    - Set up client-side routing (React Router or similar) for routes: `/` (ProfileSelector), `/session` (SessionView), `/history/:profileId` (HistoryView)
    - Wire `AuthWrapper` around all authenticated routes
    - _Requirements: 10.1, 10.4, 11.1_

  - [ ] 15.2 Apply responsive layout and accessibility styles
    - Create global CSS/Tailwind config ensuring minimum 16px for question text and button labels
    - Ensure responsive layout from 375px to 1440px (mobile-first)
    - Run `axe-core` scan and fix any reported accessibility violations on ProfileSelector, SessionView, HistoryView, and ReportScreen
    - Verify WCAG 2.1 AA color contrast for primary color palette
    - Write responsive layout tests covering two scenarios (Req 11.5):
      1. At standard breakpoints (≥375px width / standard viewport heights): assert the active-Round layout fits in a single uncluttered view with no scroll required and all elements are at least 16px
      2. At very small screen sizes (below the threshold where the single-screen layout would require elements smaller than 16px): assert scrolling is permitted and buttons, question text, and score display remain at or above the 16px minimum — they must not be clipped or shrunk below that size
    - _Requirements: 11.2, 11.3, 11.4, 11.5_

  - [ ]* 15.3 Write integration tests for profile CRUD and session save
    - Use Firebase emulator
    - Test: create profile → appears in `getProfiles`
    - Test: delete profile → profile and all its sessions removed from Firestore
    - Test: save completed session → retrievable by `getSessionById` with all fields intact
    - _Requirements: 1.1, 1.3, 1.5, 8.5_

  - [ ]* 15.4 Write property test for profile deletion cascade (Property 3)
    - **Property 3: Profile deletion removes all sessions**
    - For any profile with N ≥ 0 associated sessions, after `deleteProfile`, assert neither the profile nor any session with that `profileId` is present
    - **Validates: Requirements 1.3**

- [ ] 16. Final checkpoint — full integration complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use **fast-check** with a minimum of 100 iterations each
- Unit and integration tests use **Vitest**
- The design uses TypeScript throughout — all code must be typed
- Firebase emulator is required for integration tests (Task 15.3)
- Firefox users will see an ASR compatibility warning (SpeechRecognition not fully supported)
- API keys live in `public/config.json` — acceptable for a personal/family app; not suitable for multi-tenant production

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "4.1", "6.1", "7.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.2", "4.3", "6.2", "6.3", "7.2"] },
    { "id": 3, "tasks": ["3.1", "4.4", "5.1", "5.3"] },
    { "id": 4, "tasks": ["3.2", "5.2", "5.4", "5.5", "5.6", "9.1", "9.2"] },
    { "id": 5, "tasks": ["5.7", "9.3", "10.1"] },
    { "id": 6, "tasks": ["10.2", "10.3", "12.1", "12.2"] },
    { "id": 7, "tasks": ["12.3", "13.1", "13.2", "13.3", "13.4", "13.5", "13.6"] },
    { "id": 8, "tasks": ["14.1"] },
    { "id": 9, "tasks": ["14.2", "15.1"] },
    { "id": 10, "tasks": ["15.2", "15.3", "15.4"] }
  ]
}
```
