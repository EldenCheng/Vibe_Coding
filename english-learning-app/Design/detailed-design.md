# 详细设计文档：Chat With Me（模块级）

> 本文档是 `design.md` 的模块级展开，面向需要直接实现代码的开发者（或低级 AI 模型）。每个模块描述：文件路径、职责、所有导出的函数/类签名、内部实现步骤、依赖关系和错误处理规则。

---

## 目录

1. [应用概述与模式说明](#1-应用概述与模式说明)
2. [项目结构总览](#2-项目结构总览)
3. [共享模块](#3-共享模块)
   - 3A. Config Loader
   - 3B. Profile Validator
   - 3C. Firestore Service
   - 3D. AI Provider Factory
   - 3E. Gemini Provider（共享部分）
   - 3F. Score Calculator
   - 3G. TTS Service
   - 3H. ASR Service
   - 3I. History Sorter
4. [Mode 1：固定场景模式（Preset Mode）](#4-mode-1固定场景模式)
   - 4A. Scene Loader
   - 4B. Scene Evaluator（Mode 1 专用 AI 调用）
   - 4C. usePresetSession（Mode 1 状态机）
   - 4D. Mode 1 UI 组件
5. [Mode 2：AI 动态模式（Dynamic Mode）](#5-mode-2ai-动态模式)
   - 5A. Gemini Provider（Mode 2 完整）
   - 5B. Prompt Builders
   - 5C. useDynamicSession（Mode 2 状态机）
   - 5D. Mode 2 UI 组件
6. [共享 UI 组件](#6-共享-ui-组件)
7. [应用入口与路由](#7-应用入口与路由)
8. [模块间依赖图](#8-模块间依赖图)
9. [文件路径速查表](#9-文件路径速查表)
10. [模块实现顺序建议](#10-模块实现顺序建议)
11. [部署要求：HTTPS 与安全上下文](#11-部署要求https-与安全上下文)

---

## 1. 应用概述与模式说明

**应用名称：** Chat With Me

**核心体验：** 儿童通过看图说话练习英语口语，AI 对回答进行评分和鼓励。

### 两种模式

| 特性 | Mode 1：固定场景模式 | Mode 2：AI 动态模式 |
|---|---|---|
| 图片来源 | 预先准备的静态文件 | Gemini 实时生成 |
| 问题来源 | 预先准备的静态 JSON | Gemini 实时生成 |
| AI 调用时机 | 仅在每题提交后（后台评分） | 贯穿整个会话 |
| 等待体验 | 流畅，AI 等待分散在答题中 | 每步均有 AI 等待 |
| 场景管理 | 文件系统直接操作 | 无需管理 |
| 适用场景 | 日常练习，体验流畅 | 探索新话题，内容无限 |

### 模式可用性控制

首页显示两个模式入口按钮。当某个模式尚未实现时，对应按钮置灰（`disabled`）并显示"即将推出"标签。可用性由 `src/config/featureFlags.ts` 中的常量控制：

```typescript
export const FEATURE_FLAGS = {
  MODE_1_PRESET: true,   // 改为 false 可禁用 Mode 1
  MODE_2_DYNAMIC: false, // 改为 true 启用 Mode 2
} as const;
```

---

## 2. 项目结构总览

```
chat-with-me/
├── public/
│   ├── config.json                  ← 用户可编辑的配置文件
│   └── scenes/                      ← Mode 1 对话场景资源根目录
│       ├── primary_zoo/             ← 场景文件夹（命名格式：{gradeLevel}_{name}）
│       │   ├── meta.json            ← 场景元数据
│       │   ├── image.jpg            ← 场景图片
│       │   └── questions.json       ← 问题列表
│       ├── junior_citylife/
│       │   └── ...
│       └── senior_environment/
│           └── ...
├── src/
│   ├── main.tsx                     ← React 入口
│   ├── App.tsx                      ← 根组件
│   ├── config/
│   │   ├── configLoader.ts          ← 模块 3A
│   │   └── featureFlags.ts          ← 模式可用性开关
│   ├── profile/
│   │   └── profileValidator.ts      ← 模块 3B
│   ├── firebase/
│   │   └── firestoreService.ts      ← 模块 3C
│   ├── ai/
│   │   ├── providerFactory.ts       ← 模块 3D
│   │   ├── geminiProvider.ts        ← 模块 3E / 5A
│   │   └── promptBuilders.ts        ← 模块 5B（Mode 2 专用）
│   ├── scoring/
│   │   └── scoreCalculator.ts       ← 模块 3F
│   ├── speech/
│   │   ├── ttsService.ts            ← 模块 3G
│   │   └── asrService.ts            ← 模块 3H
│   ├── history/
│   │   └── historySorter.ts         ← 模块 3I
│   ├── mode1/                       ← Mode 1 专属
│   │   ├── sceneLoader.ts           ← 模块 4A
│   │   ├── sceneEvaluator.ts        ← 模块 4B
│   │   ├── usePresetSession.ts      ← 模块 4C
│   │   └── components/
│   │       ├── PresetSessionView.tsx
│   │       ├── SceneImageDisplay.tsx
│   │       ├── PresetQuestionCard.tsx
│   │       ├── AnswerEditor.tsx
│   │       └── PresetReportScreen.tsx
│   ├── mode2/                       ← Mode 2 专属
│   │   ├── useDynamicSession.ts     ← 模块 5C
│   │   └── components/
│   │       ├── DynamicSessionView.tsx
│   │       ├── ImageDisplay.tsx
│   │       ├── QuestionCard.tsx
│   │       ├── RecordButton.tsx
│   │       ├── TranscriptDisplay.tsx
│   │       ├── ScorePanel.tsx
│   │       ├── EncouragementCard.tsx
│   │       └── DynamicReportScreen.tsx
│   └── components/                  ← 共享 UI 组件
│       ├── ConfigGuard.tsx
│       ├── AuthWrapper.tsx
│       ├── HomeScreen.tsx
│       ├── ProfileSelector.tsx
│       ├── ProfileEditor.tsx
│       ├── HistoryView.tsx
│       ├── SessionHistoryList.tsx
│       └── SessionDetailView.tsx
├── package.json
├── vite.config.ts
└── tsconfig.json
```

### 场景文件夹命名约定

格式：`{gradeLevel}_{描述性名称}`，全小写，空格用下划线替代。

- `gradeLevel` 必须是 `primary`、`junior`、`senior` 之一
- App 通过文件夹名前缀自动识别年龄段，**无需在 meta.json 中重复声明**（meta.json 中的 gradeLevel 字段作为校验用途）

示例：`primary_zoo`、`junior_city_life`、`senior_climate_change`

---

## 3. 共享模块

### 3A. Config Loader

**文件路径：** `src/config/configLoader.ts`

**职责：** 在应用启动时加载并校验 `public/config.json`，提供类型安全的配置对象。

### 导出的类型

```typescript
export interface AppConfig {
  aiProvider: string;           // 当前仅支持 "gemini"
  gemini: {
    apiKey: string;
    imageModel: string;         // e.g. "gemini-2.0-flash-exp"（Mode 2 生图用）
    textModel: string;          // e.g. "gemini-1.5-flash"
  };
  tts: {
    lang: string;               // e.g. "en-US"
    voice: string;
    rate: number;               // 0.1–10.0，推荐 0.9
    pitch: number;              // 0.0–2.0，推荐 1.0
  };
  asr: {
    lang: string;               // e.g. "en-US"
  };
  firebase: {
    apiKey: string;
    authDomain: string;
    projectId: string;
    storageBucket: string;
    messagingSenderId: string;
    appId: string;
  };
  mode1: {
    evaluationTimeoutMs: number; // 评分请求超时，推荐 15000
  };
}

export interface ConfigValidationResult {
  valid: boolean;
  errors: string[];
}
```

### 导出的函数

```typescript
export async function loadConfig(): Promise<AppConfig>
export function validateConfig(raw: unknown): ConfigValidationResult
```

### 内部实现步骤（loadConfig）

1. `fetch('/config.json')`，非 200 则 throw `'Config file not found'`。
2. `response.json()` 解析，失败则 throw `'Config file is not valid JSON'`。
3. 调用 `validateConfig(raw)`，失败则将所有 errors 拼接后 throw。
4. 返回类型转换后的 `AppConfig`。

### 必填字段检查表

| 字段路径 | 说明 |
|---|---|
| `aiProvider` | 非空字符串 |
| `gemini.apiKey` | 非空字符串 |
| `gemini.textModel` | 非空字符串 |
| `tts.lang` | 非空字符串 |
| `firebase.apiKey` | 非空字符串 |
| `firebase.projectId` | 非空字符串 |
| `mode1.evaluationTimeoutMs` | 正整数 |

> `gemini.imageModel` 仅 Mode 2 需要；Mode 1 不调用图片生成，缺失时仅在 Mode 2 入口处警告，不阻止启动。

---

### 3B. Profile Validator

**文件路径：** `src/profile/profileValidator.ts`

与原设计相同，纯函数校验 Profile 名称和年级。

```typescript
export function validateProfileName(name: string): { valid: boolean; message?: string }
export function validateGradeLevel(gradeLevel: string): { valid: boolean; message?: string }
export function validateProfile(name: string, gradeLevel: string): ProfileValidationResult
```

规则：名称不能为空/纯空白/超过 50 字符；gradeLevel 必须是 `'primary' | 'junior' | 'senior'`。

---

### 3C. Firestore Service

**文件路径：** `src/firebase/firestoreService.ts`

**职责：** 封装所有 Firestore 读写，提供面向业务的 API。两个模式共用同一套 Profile 管理和 Session 存储，通过 `sessionMode` 字段区分。

### Firestore 数据结构

```
users/{userId}/
  profiles/{profileId}
  sessions/{sessionId}          ← 两个模式的 Session 都存这里
```

Session 文档新增字段：

```typescript
interface Session {
  // ... 原有字段 ...
  sessionMode: 'preset' | 'dynamic';  // 新增：区分模式
  sceneId?: string;                    // 新增：Mode 1 专用，记录使用的场景 ID
}
```

### 导出的函数

```typescript
export function initFirebase(firebaseConfig: AppConfig['firebase']): void

// Profile 操作（与原设计相同）
export async function createProfile(userId: string, name: string, gradeLevel: GradeLevel): Promise<Profile>
export async function updateProfile(userId: string, profileId: string, updates: Partial<Pick<Profile, 'name' | 'gradeLevel'>>): Promise<void>
export async function deleteProfile(userId: string, profileId: string): Promise<void>
export async function getProfiles(userId: string): Promise<Profile[]>

// Session 操作
export async function createSession(
  userId: string,
  profileId: string,
  sessionMode: 'preset' | 'dynamic',
  imageDescription: string,
  imageUrl: string,
  sceneId?: string              // Mode 1 时传入场景 ID
): Promise<Session>

export async function appendRound(userId: string, sessionId: string, round: Round): Promise<void>
export async function finalizeSession(userId: string, sessionId: string, report: Report, compositeScore: number): Promise<void>
export async function getSessions(userId: string, profileId: string): Promise<Session[]>

// Mode 1 专用：查询某 Profile 完成过的场景 ID 列表
export async function getCompletedSceneIds(userId: string, profileId: string): Promise<string[]>
```

### getCompletedSceneIds 实现步骤

1. 查询 `users/{userId}/sessions` where `profileId == profileId` AND `sessionMode == 'preset'` AND `status == 'complete'`。
2. 提取每个文档的 `sceneId` 字段（过滤掉 undefined）。
3. 返回去重后的 `string[]`。

---

### 3D. AI Provider Factory

**文件路径：** `src/ai/providerFactory.ts`

```typescript
export function createAIProvider(config: AppConfig): AIProviderInterface
```

内部用 `switch(config.aiProvider)` 实例化对应 Provider。目前仅支持 `"gemini"`。

---

### 3E. Gemini Provider（共享基础）

**文件路径：** `src/ai/geminiProvider.ts`

Mode 1 只需要 `evaluateAnswer`、`generateEncouragement`、`generateReport`。  
Mode 2 额外需要 `generateImage`、`generateQuestion`。  
所有方法在同一个类中实现，Mode 1 不会调用 `generateImage` 和 `generateQuestion`。

类结构见第 5A 节（完整定义）。

---

### 3F. Score Calculator

**文件路径：** `src/scoring/scoreCalculator.ts`

两个模式共用相同的计分逻辑。

```typescript
export function calculateCompositeScore(rounds: Round[]): number
export function calculateDimensionAverage(rounds: Round[], dimension: keyof EvaluationScores): number
```

实现：每维度权重均等（各 25%），各维度先对所有轮次求平均，再加权求和，结果 `Math.round` 并钳制在 `[0, 100]`。

---

### 3G. TTS Service

**文件路径：** `src/speech/ttsService.ts`

两个模式共用，封装浏览器 `SpeechSynthesis`。

```typescript
export class WebSpeechTTSService implements TTSService {
  constructor(ttsConfig: AppConfig['tts'])
  isAvailable(): boolean
  isSpeaking(): boolean
  speak(text: string, lang: string): Promise<void>
  interruptAndSpeak(text: string, lang: string): Promise<void>
  stop(): void
  onStart(cb: () => void): void
  onEnd(cb: () => void): void
  onError(cb: (err: Error) => void): void
}
```

`interruptAndSpeak` 使用私有标志位 `_suppressNextStartCb`，确保中断时不触发 `onStart` 回调（UI 层自行重置动画）。

---

### 3H. ASR Service

**文件路径：** `src/speech/asrService.ts`

两个模式共用，封装浏览器 `SpeechRecognition`。

```typescript
export class WebSpeechASRService implements ASRService {
  constructor(asrConfig: AppConfig['asr'])
  isAvailable(): boolean          // 同时检查 window.isSecureContext
  startRecording(lang: string): void
  stopRecording(): void
  onResult(cb: (transcript: string) => void): void
  onEmptyResult(cb: () => void): void
  onError(cb: (err: Error) => void): void
}
```

**关键区分：**
- `no-speech` 错误 → 调用 `onEmptyResult`（不是错误，显示重试提示）
- 其他错误 → 调用 `onError`（显示错误信息）
- `isAvailable()` 在非安全上下文（HTTP 非 localhost）时返回 `false`

---

### 3I. History Sorter

**文件路径：** `src/history/historySorter.ts`

```typescript
export function sortSessionsDescending(sessions: Session[]): Session[]
```

返回按 `createdAt` 降序排列的数组副本，相同时间以 `id` 字典序为二次键。

---

## 4. Mode 1：固定场景模式（Preset Mode）

### 场景文件格式规范

**`meta.json`**
```json
{
  "id": "primary_zoo",
  "title": "A Day at the Zoo",
  "gradeLevel": "primary",
  "imageAlt": "A colorful zoo scene with elephants, giraffes and children",
  "imageDescription": "A busy zoo on a sunny day. Children are feeding giraffes near a pond. An elephant stands in the background. A zookeeper is explaining something to a group of students.",
  "createdAt": "2024-01-15"
}
```

字段说明：
- `id`：与文件夹名一致，作为唯一标识
- `gradeLevel`：与文件夹名前缀一致（校验用）
- `imageDescription`：当图片发送失败时的降级文字描述，也用于 AI 评分的上下文补充

**`questions.json`**
```json
{
  "questions": [
    {
      "id": "q1",
      "text": "What animals can you see in this picture?",
      "order": 1
    },
    {
      "id": "q2",
      "text": "What is the boy in the red shirt doing?",
      "order": 2
    },
    {
      "id": "q3",
      "text": "Have you ever been to a zoo? What did you see?",
      "order": 3
    }
  ]
}
```

问题数量：3–5 个，按 `order` 字段排序。

---

### 4A. Scene Loader

**文件路径：** `src/mode1/sceneLoader.ts`

**职责：** 扫描 `public/scenes/` 目录，加载所有可用场景的元数据，支持按年级过滤和随机选择（排除已完成场景）。

### 导出的类型

```typescript
export interface SceneMeta {
  id: string;
  title: string;
  gradeLevel: GradeLevel;
  imageAlt: string;
  imageDescription: string;
  imagePath: string;            // e.g. "/scenes/primary_zoo/image.jpg"
  questionsPath: string;        // e.g. "/scenes/primary_zoo/questions.json"
}

export interface SceneQuestion {
  id: string;
  text: string;
  order: number;
}

export interface LoadedScene {
  meta: SceneMeta;
  questions: SceneQuestion[];   // 按 order 排序
}
```

### 导出的函数

```typescript
/**
 * 获取所有可用场景的元数据列表。
 * 通过 fetch('/scenes/index.json') 获取场景目录索引。
 * 若某个场景的 meta.json 加载失败，跳过该场景并 console.warn，不中断整体。
 */
export async function loadAllSceneMeta(): Promise<SceneMeta[]>

/**
 * 加载指定场景的完整数据（meta + questions）。
 * questions 按 order 字段升序排列后返回。
 */
export async function loadScene(sceneId: string): Promise<LoadedScene>

/**
 * 从可用场景中随机选择一个，排除已完成的场景 ID。
 * 若所有场景都已完成，则重置（忽略 completedIds），从全部场景中随机选。
 * gradeLevel 为可选过滤条件；若不传则从所有年级中选。
 */
export function pickRandomScene(
  allScenes: SceneMeta[],
  completedIds: string[],
  gradeLevel?: GradeLevel
): SceneMeta
```

### 场景索引文件 `public/scenes/index.json`

为避免在浏览器环境中无法直接列出目录，使用一个索引文件记录所有场景 ID：

```json
{
  "scenes": [
    "primary_zoo",
    "junior_city_life",
    "senior_climate_change"
  ]
}
```

**管理说明（给内容准备者）：**
- 新增场景：创建场景文件夹 → 在 `index.json` 的 `scenes` 数组中添加场景 ID
- 删除场景：删除场景文件夹 → 从 `index.json` 的 `scenes` 数组中移除该 ID
- App 会自动按文件夹名前缀识别年级，`meta.json` 中的 `gradeLevel` 与文件夹名不一致时打印警告

### 内部实现步骤（loadAllSceneMeta）

1. `fetch('/scenes/index.json')`，解析得到 `sceneIds: string[]`。
2. 对每个 sceneId，并行 `fetch('/scenes/{sceneId}/meta.json')`。
3. 解析每个 meta，从文件夹名提取 gradeLevel 前缀，校验与 `meta.gradeLevel` 是否一致。
4. 补充 `imagePath` 和 `questionsPath` 字段。
5. 返回成功加载的 `SceneMeta[]`（失败的跳过并 warn）。

### 内部实现步骤（pickRandomScene）

```typescript
export function pickRandomScene(
  allScenes: SceneMeta[],
  completedIds: string[],
  gradeLevel?: GradeLevel
): SceneMeta {
  let candidates = gradeLevel
    ? allScenes.filter(s => s.gradeLevel === gradeLevel)
    : allScenes;

  // 排除已完成，若全部完成则重置
  const unfinished = candidates.filter(s => !completedIds.includes(s.id));
  if (unfinished.length > 0) candidates = unfinished;
  // 否则 candidates 保持全部（重置循环）

  const idx = Math.floor(Math.random() * candidates.length);
  return candidates[idx];
}
```

---

### 4B. Scene Evaluator

**文件路径：** `src/mode1/sceneEvaluator.ts`

**职责：** Mode 1 专用的 AI 评分调用封装。每题提交后立即发起后台评分，结果存入 Promise Map，结算时汇总。

### 导出的类型

```typescript
export interface PresetEvaluationRequest {
  questionId: string;
  questionText: string;
  answer: string;               // STT + 用户编辑后的最终文字
  imageBase64: string;          // 图片 base64（主路径）
  imageMimeType: string;
  imageDescription: string;     // meta.json 中的描述（降级备用）
  gradeLevel: GradeLevel;
  childName: string;
}

export interface PresetEvaluationResult {
  questionId: string;
  scores: EvaluationScores | null;   // null = 超时或失败
  encouragement: string | null;
  timedOut: boolean;
}
```

### 导出的类

```typescript
export class SceneEvaluator {
  private pendingEvaluations: Map<string, Promise<PresetEvaluationResult>>;
  private aiProvider: AIProviderInterface;
  private timeoutMs: number;

  constructor(aiProvider: AIProviderInterface, timeoutMs: number)

  /**
   * 提交一道题的评分请求，立即返回（fire-and-forget）。
   * 内部将 Promise 存入 pendingEvaluations Map，key 为 questionId。
   */
  submitEvaluation(request: PresetEvaluationRequest): void

  /**
   * 等待所有已提交的评分完成（或超时）。
   * 调用时机：所有问题回答完毕，进入结算页前。
   * 返回所有结果，包括超时/失败的（timedOut: true, scores: null）。
   */
  async collectAllResults(): Promise<PresetEvaluationResult[]>

  /**
   * 清空所有待处理的评分请求（会话取消时调用）。
   */
  reset(): void
}
```

### 内部实现步骤（submitEvaluation）

```typescript
submitEvaluation(request: PresetEvaluationRequest): void {
  const evaluationPromise = this.runWithTimeout(
    this.evaluate(request),
    this.timeoutMs,
    request.questionId
  );
  this.pendingEvaluations.set(request.questionId, evaluationPromise);
}
```

### 内部实现步骤（evaluate 私有方法）

1. 构造评分提示词（包含问题文字、学生答案、年级、图片描述作为上下文）。
2. 调用 `aiProvider.evaluateAnswerWithImage(request)` —— 主路径：发送图片 base64 + 提示词。
3. 若图片发送失败，降级调用 `aiProvider.evaluateAnswer(...)` —— 仅发文字描述。
4. 同时调用 `aiProvider.generateEncouragement(...)` 获取鼓励语。
5. 返回 `PresetEvaluationResult`。

### 内部实现步骤（runWithTimeout 私有方法）

```typescript
private async runWithTimeout<T>(
  promise: Promise<T>,
  ms: number,
  questionId: string
): Promise<PresetEvaluationResult> {
  const timeout = new Promise<PresetEvaluationResult>(resolve =>
    setTimeout(() => resolve({
      questionId,
      scores: null,
      encouragement: null,
      timedOut: true
    }), ms)
  );
  return Promise.race([promise, timeout]);
}
```

### 内部实现步骤（collectAllResults）

```typescript
async collectAllResults(): Promise<PresetEvaluationResult[]> {
  const results = await Promise.all(
    Array.from(this.pendingEvaluations.values())
  );
  return results;
}
```

---

### 4C. usePresetSession

**文件路径：** `src/mode1/usePresetSession.ts`

**职责：** Mode 1 的 React custom hook，驱动固定场景会话的完整生命周期。

### 状态类型

```typescript
export type PresetSessionStatus =
  | 'Idle'
  | 'LoadingScene'           // 加载场景数据
  | 'ShowingQuestion'        // 展示问题，等待录音
  | 'Recording'              // 录音中
  | 'ShowingTranscript'      // 展示 STT 结果，等待编辑/提交
  | 'Submitting'             // 提交答案（后台发起评分，立即进入下一题）
  | 'ShowingResults'         // 所有问题完成，收集评分结果
  | 'ShowingReport'          // 展示最终报告
  | 'Error';

export interface PresetSessionState {
  status: PresetSessionStatus;
  scene: LoadedScene | null;
  currentQuestionIndex: number;        // 0-based
  currentTranscript: string;           // 可编辑，初始为 STT 结果
  submittedAnswers: SubmittedAnswer[];  // 已提交的答案
  evaluationResults: PresetEvaluationResult[] | null; // 收集完成后填入
  errorMessage: string | null;
  retryPrompt: boolean;
}

export interface SubmittedAnswer {
  questionId: string;
  questionText: string;
  answerText: string;
}
```

### Hook 签名

```typescript
export function usePresetSession(
  profile: Profile,
  aiProvider: AIProviderInterface,
  ttsService: TTSService,
  asrService: ASRService,
  config: AppConfig
): {
  state: PresetSessionState;
  startSession: () => void;
  startRecording: () => void;
  stopRecording: () => void;
  updateTranscript: (text: string) => void;   // 用户编辑 STT 结果
  submitAnswer: () => void;                    // 提交当前答案，后台发起评分
  replaySpeaker: () => void;
  cancelSession: () => void;
  retryLastAction: () => void;
}
```

### 状态转换表

| 当前状态 | 触发事件 | 下一状态 | 副作用 |
|---|---|---|---|
| Idle | `startSession()` | LoadingScene | 调用 `sceneLoader.loadAllSceneMeta`，查询 `completedSceneIds`，`pickRandomScene` |
| LoadingScene | sceneLoaded | ShowingQuestion | 加载场景完整数据，TTS 朗读第一个问题 |
| LoadingScene | loadError | Error | 设置 errorMessage |
| ShowingQuestion | `startRecording()` | Recording | 调用 `asrService.startRecording` |
| Recording | `stopRecording()` | ShowingTranscript | 调用 `asrService.stopRecording`，填入 transcript |
| Recording | transcriptEmpty | ShowingQuestion | `retryPrompt = true` |
| Recording | asrError | ShowingQuestion | `retryPrompt = true`（技术错误也显示重试，不中断会话）|
| ShowingTranscript | `updateTranscript(text)` | ShowingTranscript | 更新 `currentTranscript`（纯 UI 操作）|
| ShowingTranscript | `submitAnswer()` | Submitting | 保存答案，调用 `sceneEvaluator.submitEvaluation`（后台）|
| Submitting | 非最后一题 | ShowingQuestion | currentQuestionIndex++，TTS 朗读下一题 |
| Submitting | 最后一题 | ShowingResults | 调用 `sceneEvaluator.collectAllResults`，等待结果 |
| ShowingResults | resultsCollected | ShowingReport | 计算 compositeScore，调用 firestoreService 保存 |
| Error | `retryLastAction()` | Idle | 重置状态 |

### 关键实现细节

**图片预加载：** 在 `LoadingScene` 阶段，将图片转为 base64 存入状态，供 `submitEvaluation` 直接使用：

```typescript
async function loadImageAsBase64(imagePath: string): Promise<{ base64: string; mimeType: string }> {
  const response = await fetch(imagePath);
  const blob = await response.blob();
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result as string;
      const [header, base64] = dataUrl.split(',');
      const mimeType = header.match(/:(.*?);/)?.[1] ?? 'image/jpeg';
      resolve({ base64, mimeType });
    };
    reader.readAsDataURL(blob);
  });
}
```

**ASR 在 Mode 1 的处理：** Mode 1 中 ASR 错误不应中断会话（不同于 Mode 2），技术错误也只显示软提示，让孩子重试或直接手动输入。

**结算等待处理：** `ShowingResults` 状态下，若 `collectAllResults` 超过 3 秒仍未返回（理论上不会，因为每个 Promise 已有超时保障），显示"正在计算结果"加载动画。

---

### 4D. Mode 1 UI 组件

**文件路径：** `src/mode1/components/`

---

#### PresetSessionView.tsx

```typescript
interface PresetSessionViewProps {
  profile: Profile;
  config: AppConfig;
  userId: string;
  onSessionComplete: (session: Session) => void;
  onCancel: () => void;
}
```

**行为：**
1. 实例化服务（TTS、ASR、AIProvider），调用 `usePresetSession`。
2. 根据 `state.status` 渲染：
   - `LoadingScene`：全屏加载动画（"正在准备对话场景..."）
   - `ShowingQuestion` / `Recording` / `ShowingTranscript`：渲染 `SceneImageDisplay` + `PresetQuestionCard` + `AnswerEditor`
   - `ShowingResults`：全屏加载动画（"正在计算你的成绩..."）
   - `ShowingReport`：渲染 `PresetReportScreen`
   - `Error`：错误横幅 + 重试按钮

---

#### SceneImageDisplay.tsx

```typescript
interface SceneImageDisplayProps {
  imagePath: string;    // e.g. "/scenes/primary_zoo/image.jpg"
  alt: string;
}
```

**行为：** 渲染 `<img src={imagePath} alt={alt}>`，带加载骨架屏。图片固定显示在顶部，整个会话过程中不消失。

---

#### PresetQuestionCard.tsx

```typescript
interface PresetQuestionCardProps {
  question: SceneQuestion;
  questionTotal: number;        // 总题数
  ttsService: TTSService;
  isAnswered: boolean;          // 已提交的题目显示已完成标记
}
```

**行为：**
1. 显示题号（"第 2 题 / 共 3 题"）。
2. 显示问题文字（最小 16px）。
3. 朗读按钮：点击调用 TTS，已在说话时调用 `interruptAndSpeak`。
4. 问题展示后自动触发一次 TTS 朗读。

---

#### AnswerEditor.tsx

```typescript
interface AnswerEditorProps {
  transcript: string;
  status: PresetSessionStatus;
  retryPrompt: boolean;
  onTranscriptChange: (text: string) => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onSubmit: () => void;
}
```

**行为：**
1. 录音按钮（麦克风图标）：`ShowingQuestion` 时可点击开始录音，`Recording` 时显示停止按钮 + 脉冲动画。
2. 文本编辑区：`ShowingTranscript` 时显示可编辑的 `<textarea>`，初始值为 STT 结果，用户可直接修改。字体最小 16px。
3. 提交按钮：`ShowingTranscript` 且 `transcript` 非空时可点击。
4. `retryPrompt` 为 true 时，在录音按钮上方显示软提示（"没有听清，请再试一次，或直接输入你的回答"）。
5. 提交按钮点击后立即进入下一题（`Submitting` 状态），不需要等待评分。

---

#### PresetReportScreen.tsx

```typescript
interface PresetReportScreenProps {
  scene: LoadedScene;
  submittedAnswers: SubmittedAnswer[];
  evaluationResults: PresetEvaluationResult[];
  profile: Profile;
  compositeScore: number;
  onBackToProfiles: () => void;
  onStartNewSession: () => void;
}
```

**行为：**
1. 顶部显示场景标题 + 总分徽章。
2. 每道题显示一个卡片：问题文字 → 孩子的回答 → 四维分数（若超时则显示"—"）→ 鼓励语。
3. 底部显示综合评语（由最后一次 `generateReport` 生成，若不可用则不显示）。
4. "再来一次"和"返回主页"按钮。

---

## 5. Mode 2：AI 动态模式（Dynamic Mode）

### 5A. Gemini Provider（完整实现）

**文件路径：** `src/ai/geminiProvider.ts`

**职责：** 实现完整的 `AIProviderInterface`，包含 Mode 1 和 Mode 2 所有 AI 调用。

```typescript
import { GoogleGenerativeAI } from '@google/generative-ai';

export class GeminiProvider implements AIProviderInterface {
  private genAI: GoogleGenerativeAI;
  private imageModelName: string;
  private textModelName: string;

  constructor(cfg: AppConfig['gemini'])

  // Mode 2 专用
  async generateImage(prompt: string, gradeLevel: GradeLevel): Promise<GeneratedImage>
  async generateQuestion(params: QuestionParams): Promise<string>

  // 两个模式共用
  async evaluateAnswer(params: EvaluationParams): Promise<EvaluationScores>
  async evaluateAnswerWithImage(params: EvaluationWithImageParams): Promise<EvaluationScores>
  async generateEncouragement(params: EncouragementParams): Promise<string>
  async generateReport(params: ReportParams): Promise<Report>
}
```

### 新增接口类型

```typescript
// Mode 1 专用：包含图片 base64 的评分请求
interface EvaluationWithImageParams extends EvaluationParams {
  imageBase64: string;
  imageMimeType: string;
}
```

### evaluateAnswerWithImage 实现步骤

1. 构造 multipart 请求，包含：
   - Part 1：`inlineData`（图片 base64 + mimeType）
   - Part 2：文字提示词（与 `buildEvaluationPrompt` 相同结构，但去掉 imageDescription 行，因为图片已直接提供）
2. 调用文本模型（`textModel`，Gemini 的视觉理解能力包含在文本模型中）。
3. 解析 JSON 响应，返回 `EvaluationScores`。
4. 若失败，throw，由 `SceneEvaluator` 降级到纯文字评分。

### generateImage 实现步骤

1. 调用模块 5B 的 `buildImagePrompt(gradeLevel, category)`。
2. 使用 `imageModel`（`gemini-2.0-flash-exp`）发起请求，`responseModalities: ['IMAGE', 'TEXT']`。
3. 提取响应中的 `inlineData`（base64 + mimeType）和文字描述。
4. 返回 `GeneratedImage`。若失败则 throw，由状态机触发 fallback。

### parseEvaluationResponse 私有方法

```typescript
private parseEvaluationResponse(text: string): EvaluationScores {
  // 1. 用正则 /\{[\s\S]*?\}/ 提取第一个 JSON 块
  // 2. JSON.parse
  // 3. 对每个维度：存在且为 [0,100] 整数则使用，否则置 null
  // 4. 完全无法解析则 throw
}
```

---

### 5B. Prompt Builders

**文件路径：** `src/ai/promptBuilders.ts`

**职责：** Mode 2 专用，构造所有 AI 提示词字符串（纯函数）。

```typescript
export const IMAGE_CATEGORIES = [
  'animals', 'nature', 'city life', 'school',
  'sports', 'food', 'family', 'travel'
] as const;
export type ImageCategory = typeof IMAGE_CATEGORIES[number];

export const FALLBACK_IMAGE_DESCRIPTIONS: Record<ImageCategory, string> = {
  animals:     'A colorful scene with various animals in a natural habitat',
  nature:      'A peaceful landscape with mountains, trees, and a river',
  'city life': 'A busy city street with people, cars, and tall buildings',
  school:      'A classroom with students studying at their desks',
  sports:      'Children playing football on a green field',
  food:        'A table with various delicious dishes from around the world',
  family:      'A family having a picnic in a sunny park',
  travel:      'A traveler with a backpack exploring a famous landmark',
};

export function buildImagePrompt(gradeLevel: GradeLevel, category: ImageCategory): string
export function buildQuestionPrompt(params: QuestionParams): string
export function buildEvaluationPrompt(params: EvaluationParams): string
```

### buildImagePrompt 实现

```typescript
export function buildImagePrompt(gradeLevel: GradeLevel, category: ImageCategory): string {
  const styles = {
    primary: `Generate a simple, colorful illustration suitable for children aged 10-12. The scene should show ${category} with clear, recognizable elements. Avoid complex backgrounds. Style: flat illustration, bright colors.`,
    junior:  `Generate an engaging scene suitable for teenagers aged 13-15. The image should depict ${category} with enough detail to prompt descriptive discussion. Style: realistic illustration.`,
    senior:  `Generate a thought-provoking scene suitable for students aged 16-18. The image should depict ${category} with rich contextual detail that invites reflection. Style: photorealistic.`
  };
  return styles[gradeLevel];
}
```

### buildQuestionPrompt 实现

```typescript
export function buildQuestionPrompt(params: QuestionParams): string {
  const gradeInstructions = {
    primary: `Ask a simple factual question with a clear answer (e.g., "What color is the dog?"). Use vocabulary appropriate for ages 10-12.`,
    junior:  `Ask an open-ended descriptive question (e.g., "Could you tell me what is happening here?"). Suitable for ages 13-15.`,
    senior:  `Ask a reflective or analytical question requiring personal thought (e.g., "How does this scene make you feel?"). Suitable for ages 16-18.`
  };
  const continuityClause = params.previousQuestions.length > 0
    ? `The previous questions were: ${params.previousQuestions.map((q, i) => `Round ${i+1}: "${q}"`).join('; ')}. Generate a new question that explores a different aspect of the same image.`
    : '';
  return `
    You are helping a Chinese student practice English.
    Image description: "${params.imageDescription}"
    Round: ${params.roundNumber} of 3.
    ${continuityClause}
    ${gradeInstructions[params.gradeLevel]}
    Respond with ONLY the question text, no additional explanation.
  `;
}
```

---

### 5C. useDynamicSession

**文件路径：** `src/mode2/useDynamicSession.ts`

**职责：** Mode 2 的 React custom hook，实现 AI 全程驱动的动态会话状态机。

### 状态类型

```typescript
export type DynamicSessionStatus =
  | 'Idle'
  | 'GeneratingImage'
  | 'GeneratingQuestion'
  | 'AwaitingAnswer'
  | 'Recording'
  | 'Transcribing'
  | 'Evaluating'
  | 'ShowingScores'
  | 'GeneratingEncouragement'
  | 'RoundComplete'
  | 'GeneratingReport'
  | 'ShowingReport'
  | 'Error';

export interface DynamicSessionState {
  status: DynamicSessionStatus;
  currentRound: 0 | 1 | 2 | 3;
  image: GeneratedImage | null;
  currentQuestion: string | null;
  currentTranscript: string | null;
  rounds: Round[];
  report: Report | null;
  errorMessage: string | null;
  retryPrompt: boolean;
  session: Session | null;
}
```

### Hook 签名

```typescript
export function useDynamicSession(
  profile: Profile,
  aiProvider: AIProviderInterface,
  ttsService: TTSService,
  asrService: ASRService
): {
  state: DynamicSessionState;
  startSession: () => void;
  startRecording: () => void;
  stopRecording: () => void;
  replaySpeaker: () => void;
  cancelSession: () => void;
  retryLastAction: () => void;
}
```

### 状态转换表

| 当前状态 | 触发事件 | 下一状态 | 副作用 |
|---|---|---|---|
| Idle | `startSession()` | GeneratingImage | 调用 `aiProvider.generateImage` |
| GeneratingImage | imageReady | GeneratingQuestion | 保存图片，调用 `generateQuestion` |
| GeneratingImage | imageFailed | GeneratingQuestion | 使用 fallback 图片（`mimeType: 'local'`）|
| GeneratingQuestion | questionReady | AwaitingAnswer | 保存问题，TTS 朗读 |
| GeneratingQuestion | questionError | Error | 设置 errorMessage |
| AwaitingAnswer | `startRecording()` | Recording | 调用 `asrService.startRecording` |
| Recording | `stopRecording()` | Transcribing | 等待 ASR 结果 |
| Transcribing | transcriptReady | Evaluating | 调用 `aiProvider.evaluateAnswer` |
| Transcribing | transcriptEmpty | AwaitingAnswer | `retryPrompt = true` |
| Evaluating | scoresReady | ShowingScores | 保存 scores |
| Evaluating | evaluationError | ShowingScores | 部分 scores 降级 |
| ShowingScores | （1500ms 后自动）| GeneratingEncouragement | 调用 `generateEncouragement` |
| GeneratingEncouragement | encouragementReady | RoundComplete | 保存，调用 `appendRound` |
| RoundComplete | rounds < 3 | GeneratingQuestion | currentRound++，下一题 |
| RoundComplete | rounds === 3 | GeneratingReport | 调用 `generateReport` |
| GeneratingReport | reportReady | ShowingReport | 调用 `finalizeSession` |
| GeneratingReport | reportError | ShowingReport | 保存部分数据 |
| Error | `retryLastAction()` | Idle | 重置 |

### 实现结构

使用 `useReducer` + `useEffect`，与 Mode 1 状态机结构相同但状态类型独立。

```typescript
const [state, dispatch] = useReducer(dynamicSessionReducer, initialState);

useEffect(() => {
  switch (state.status) {
    case 'GeneratingImage':   generateImageEffect(); break;
    case 'GeneratingQuestion': generateQuestionEffect(); break;
    case 'ShowingScores':
      const timer = setTimeout(() => dispatch({ type: 'SCORES_DISPLAYED' }), 1500);
      return () => clearTimeout(timer);
    // ...
  }
}, [state.status]);
```

### generateImageEffect

```typescript
async function generateImageEffect() {
  try {
    const image = await aiProvider.generateImage('', profile.gradeLevel);
    dispatch({ type: 'IMAGE_READY', image });
  } catch {
    const category = IMAGE_CATEGORIES[Math.floor(Math.random() * IMAGE_CATEGORIES.length)];
    const fallbackImage: GeneratedImage = {
      base64Data: '',
      mimeType: 'local',
      description: FALLBACK_IMAGE_DESCRIPTIONS[category],
    };
    dispatch({ type: 'IMAGE_FALLBACK', image: fallbackImage, category });
  }
}
```

---

### 5D. Mode 2 UI 组件

**文件路径：** `src/mode2/components/`

组件与原设计一致，仅更新命名前缀。

#### DynamicSessionView.tsx
与原 `SessionView` 相同结构，使用 `useDynamicSession` hook。

#### ImageDisplay.tsx
- `mimeType === 'local'`：渲染 `<img src={/fallback-images/${category}.jpg}>`
- 否则：渲染 base64 data URL

#### QuestionCard.tsx
显示轮次标记 + 问题文字 + TTS 朗读按钮，含中断重播逻辑。

#### RecordButton.tsx
录音/停止切换按钮，含脉冲动画和软提示文字。

#### TranscriptDisplay.tsx
显示 ASR 识别文字（只读，与 Mode 1 不同，Mode 2 不允许编辑）。

#### ScorePanel.tsx
四维分数展示，含进度条，null 维度显示"—"。

#### EncouragementCard.tsx
显示 AI 鼓励语，第 1/2 轮显示"下一题"按钮。

#### DynamicReportScreen.tsx
显示三轮汇总报告，含总分徽章 + AI 分析文字。

---

## 6. 共享 UI 组件

**文件路径：** `src/components/`

---

### ConfigGuard.tsx

```typescript
interface ConfigGuardProps {
  children: (config: AppConfig) => React.ReactNode;
}
```

**行为：**
1. `useEffect` 中调用 `loadConfig()`，管理 loading/error 状态。
2. 加载成功：调用 `initFirebase(config.firebase)`，渲染 `children(config)`。
3. 加载失败：显示配置错误屏幕，列出字段级错误。
4. 同时检查 `!asrService.isAvailable()`，若原因是 `!window.isSecureContext`，在错误屏幕附加 HTTPS 提示。

---

### AuthWrapper.tsx

```typescript
interface AuthWrapperProps {
  config: AppConfig;
  children: (userId: string) => React.ReactNode;
}
```

Firebase Anonymous Auth，登录成功后渲染 children。

---

### HomeScreen.tsx

```typescript
interface HomeScreenProps {
  userId: string;
  config: AppConfig;
}
```

**行为：**
1. 显示 App 名称"Chat With Me"。
2. 显示两个模式入口卡片：
   - **固定场景对话**（Mode 1）：`FEATURE_FLAGS.MODE_1_PRESET` 为 false 时置灰
   - **AI 动态对话**（Mode 2）：`FEATURE_FLAGS.MODE_2_DYNAMIC` 为 false 时置灰，显示"即将推出"标签
3. 入口卡片包含模式简介文字（一句话说明该模式的特点）。
4. 右上角有"历史记录"和"档案管理"按钮。

---

### ProfileSelector.tsx

```typescript
interface ProfileSelectorProps {
  userId: string;
  selectedMode: 'preset' | 'dynamic';
  onSelectProfile: (profile: Profile) => void;
  onCreateProfile: () => void;
  onEditProfile: (profile: Profile) => void;
  onDeleteProfile: (profileId: string) => void;
}
```

**行为：** 加载并展示所有 Profile 卡片，删除前弹出确认对话框。

---

### ProfileEditor.tsx

创建/编辑 Profile 表单，提交前调用 `validateProfile`，年级用三个单选按钮选择。

---

### HistoryView.tsx

```typescript
interface HistoryViewProps {
  userId: string;
  profile: Profile;
  onBack: () => void;
}
```

**行为：**
1. 加载中显示全屏 loading，**不渲染部分数据**。
2. 加载完成后调用 `sortSessionsDescending` 排序。
3. 历史列表区分模式：在每条记录上显示"固定场景"或"动态"标签。
4. 点击进入 `SessionDetailView`。

---

### SessionDetailView.tsx

展示完整 Session 详情。根据 `session.sessionMode` 区分展示方式：
- `preset`：显示场景标题 + 每题问答 + 各维度分数 + 鼓励语
- `dynamic`：显示图片（若 imageUrl 存在）+ 每轮问答 + 各维度分数 + 报告

---

## 7. 应用入口与路由

**文件路径：** `src/App.tsx`

使用简单的状态路由（无 React Router），通过 `useState` 管理当前页面：

```typescript
type AppPage =
  | { name: 'Home' }
  | { name: 'ProfileSelect'; mode: 'preset' | 'dynamic' }
  | { name: 'PresetSession'; profile: Profile }
  | { name: 'DynamicSession'; profile: Profile }
  | { name: 'History'; profile: Profile }
  | { name: 'ProfileEditor'; existing?: Profile };

export default function App() {
  return (
    <ConfigGuard>
      {(config) => (
        <AuthWrapper config={config}>
          {(userId) => <AppRouter userId={userId} config={config} />}
        </AuthWrapper>
      )}
    </ConfigGuard>
  );
}
```

`AppRouter` 组件持有 `currentPage` 状态，根据页面类型渲染对应组件，通过 props 传递导航回调。

---

## 8. 模块间依赖图

```
App.tsx
  ├── ConfigGuard ──► configLoader (3A), featureFlags
  └── AuthWrapper
       └── AppRouter
            ├── HomeScreen ──► featureFlags
            ├── ProfileSelector ──► firestoreService (3C)
            ├── ProfileEditor ──► profileValidator (3B), firestoreService (3C)
            ├── HistoryView ──► firestoreService (3C), historySorter (3I)
            │
            ├── [Mode 1] PresetSessionView
            │    └── usePresetSession (4C)
            │         ├── sceneLoader (4A)
            │         ├── sceneEvaluator (4B)
            │         │    └── geminiProvider (3E/5A)
            │         ├── ttsService (3G)
            │         ├── asrService (3H)
            │         └── firestoreService (3C)
            │
            └── [Mode 2] DynamicSessionView
                 └── useDynamicSession (5C)
                      ├── providerFactory (3D)
                      │    └── geminiProvider (5A)
                      │         ├── promptBuilders (5B)
                      │         └── scoreCalculator (3F)
                      ├── ttsService (3G)
                      ├── asrService (3H)
                      └── firestoreService (3C)
```

---

## 9. 文件路径速查表

| 模块 | 文件路径 | 测试文件 |
|---|---|---|
| 3A Config Loader | `src/config/configLoader.ts` | `src/config/configLoader.test.ts` |
| Feature Flags | `src/config/featureFlags.ts` | — |
| 3B Profile Validator | `src/profile/profileValidator.ts` | `src/profile/profileValidator.test.ts` |
| 3C Firestore Service | `src/firebase/firestoreService.ts` | `src/firebase/firestoreService.test.ts` |
| 3D Provider Factory | `src/ai/providerFactory.ts` | `src/ai/providerFactory.test.ts` |
| 3E/5A Gemini Provider | `src/ai/geminiProvider.ts` | `src/ai/geminiProvider.test.ts` |
| 3F Score Calculator | `src/scoring/scoreCalculator.ts` | `src/scoring/scoreCalculator.test.ts` |
| 3G TTS Service | `src/speech/ttsService.ts` | `src/speech/ttsService.test.ts` |
| 3H ASR Service | `src/speech/asrService.ts` | `src/speech/asrService.test.ts` |
| 3I History Sorter | `src/history/historySorter.ts` | `src/history/historySorter.test.ts` |
| 4A Scene Loader | `src/mode1/sceneLoader.ts` | `src/mode1/sceneLoader.test.ts` |
| 4B Scene Evaluator | `src/mode1/sceneEvaluator.ts` | `src/mode1/sceneEvaluator.test.ts` |
| 4C usePresetSession | `src/mode1/usePresetSession.ts` | `src/mode1/usePresetSession.test.ts` |
| 5B Prompt Builders | `src/ai/promptBuilders.ts` | `src/ai/promptBuilders.test.ts` |
| 5C useDynamicSession | `src/mode2/useDynamicSession.ts` | `src/mode2/useDynamicSession.test.ts` |
| Mode 1 组件 | `src/mode1/components/*.tsx` | `src/mode1/components/*.test.tsx` |
| Mode 2 组件 | `src/mode2/components/*.tsx` | `src/mode2/components/*.test.tsx` |
| 共享组件 | `src/components/*.tsx` | `src/components/*.test.tsx` |
| 场景索引 | `public/scenes/index.json` | — |
| 场景文件夹 | `public/scenes/{id}/` | — |
| 配置文件 | `public/config.json` | — |

---

## 10. 模块实现顺序建议

### 阶段一：基础层（无外部依赖，纯函数）

1. `featureFlags.ts` — 常量，2 分钟
2. `profileValidator.ts` (3B) — 纯函数
3. `scoreCalculator.ts` (3F) — 纯函数
4. `historySorter.ts` (3I) — 纯函数
5. `promptBuilders.ts` (5B) — 纯函数（Mode 2 用）

### 阶段二：服务层

6. `configLoader.ts` (3A) — 依赖 fetch
7. `firestoreService.ts` (3C) — 依赖 Firebase SDK（用 emulator 测试）
8. `ttsService.ts` (3G) — 依赖浏览器 API（mock 测试）
9. `asrService.ts` (3H) — 依赖浏览器 API（mock 测试）
10. `geminiProvider.ts` (3E/5A) — 依赖 Gemini SDK（mock 测试）
11. `providerFactory.ts` (3D) — 依赖 geminiProvider

### 阶段三：Mode 1 核心

12. `sceneLoader.ts` (4A) — 依赖 fetch
13. `sceneEvaluator.ts` (4B) — 依赖 geminiProvider
14. `usePresetSession.ts` (4C) — 依赖 4A、4B、3C、3G、3H
15. Mode 1 UI 组件 (4D)

### 阶段四：Mode 2 核心

16. `useDynamicSession.ts` (5C) — 依赖 5A/3E、3C、3G、3H
17. Mode 2 UI 组件 (5D)

### 阶段五：共享 UI 与入口

18. 共享组件（ConfigGuard、AuthWrapper、HomeScreen 等）
19. `App.tsx` 路由整合

---

## 11. 部署要求：HTTPS 与安全上下文

### 为什么必须使用 HTTPS（或 localhost）

| API | HTTP 局域网 IP | http://localhost | HTTPS |
|---|---|---|---|
| `SpeechRecognition`（ASR） | ❌ 直接拒绝 | ✅ 正常 | ✅ 正常 |
| `SpeechSynthesis`（TTS） | ⚠️ 不稳定 | ✅ 正常 | ✅ 正常 |
| 麦克风 `getUserMedia` | ❌ `NotAllowedError` | ✅ 正常 | ✅ 正常 |

**结论：局域网内平板/手机访问必须配置 HTTPS。**

### 方案一：仅本机 localhost（无需证书）

```bash
npm run dev
# 访问 http://localhost:5173
```

### 方案二：mkcert 自签名证书（推荐家用）

```powershell
choco install mkcert
mkcert -install
mkcert localhost 127.0.0.1 192.168.1.100
```

`vite.config.ts` 配置：
```typescript
server: {
  https: { cert: fs.readFileSync('./localhost+2.pem'), key: fs.readFileSync('./localhost+2-key.pem') },
  host: '0.0.0.0',
  port: 5173,
}
```

其他设备安装根证书：将 `mkcert -CAROOT` 下的 `rootCA.pem` 传到设备并手动信任（iOS 还需在证书信任设置中开启）。

### 在代码中检测非安全上下文

```typescript
// src/speech/asrService.ts
isAvailable(): boolean {
  if (typeof window !== 'undefined' && !window.isSecureContext) return false;
  return 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window;
}
```

非安全上下文时，`ConfigGuard` 显示明确提示："麦克风功能需要 HTTPS 环境，请通过 https:// 访问或使用 http://localhost。"

---

## 12. 场景管理教程（Mode 1 内容准备指南）

本章节面向内容准备者（通常是家长），说明如何增加、删除和维护 Mode 1 的对话场景，以及如何借助 AI 工具高效地准备场景内容。

---

### 12.1 场景文件夹结构回顾

每个场景是 `public/scenes/` 下的一个子文件夹，包含三个固定文件：

```
public/scenes/
└── primary_zoo/              ← 文件夹名 = 场景 ID
    ├── meta.json             ← 场景元数据
    ├── image.jpg             ← 场景图片（也可以是 image.png）
    └── questions.json        ← 问题列表
```

---

### 12.2 文件夹命名规则

格式：**`{gradeLevel}_{描述性名称}`**

| gradeLevel 前缀 | 对应年龄段 | 示例 |
|---|---|---|
| `primary_` | 10–12 岁 | `primary_zoo`、`primary_farm` |
| `junior_` | 13–15 岁 | `junior_city_life`、`junior_market` |
| `senior_` | 16–18 岁 | `senior_climate`、`senior_technology` |

- 全部小写，空格用下划线替代
- App 通过前缀自动识别年级，**文件夹名前缀必须准确**

---

### 12.3 各文件的完整格式

**`meta.json`**

```json
{
  "id": "primary_zoo",
  "title": "A Day at the Zoo",
  "gradeLevel": "primary",
  "imageAlt": "A colorful zoo scene with elephants, giraffes and children",
  "imageDescription": "A busy zoo on a sunny day. Children are feeding giraffes near a pond. An elephant stands in the background. A zookeeper is explaining something to a group of students.",
  "createdAt": "2024-01-15"
}
```

字段说明：

| 字段 | 说明 | 注意事项 |
|---|---|---|
| `id` | 必须与文件夹名完全一致 | 不一致会触发警告 |
| `title` | 场景的展示标题 | 显示在历史记录和报告中 |
| `gradeLevel` | 必须与文件夹名前缀一致 | `primary` / `junior` / `senior` |
| `imageAlt` | 图片的无障碍描述（一句话） | 简洁描述图片主要内容 |
| `imageDescription` | 详细的图片文字描述 | **重要**：评分失败时作为降级备用；内容越详细，AI 评分越准确 |
| `createdAt` | 创建日期（`YYYY-MM-DD`） | 仅供记录，不影响功能 |

**`questions.json`**

```json
{
  "questions": [
    {
      "id": "q1",
      "text": "What animals can you see in this picture?",
      "order": 1
    },
    {
      "id": "q2",
      "text": "What is the boy in the red shirt doing?",
      "order": 2
    },
    {
      "id": "q3",
      "text": "Have you ever been to a zoo? What did you like most?",
      "order": 3
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 问题唯一标识，同一场景内不重复，推荐 `q1`、`q2`... |
| `text` | 问题文字，TTS 会朗读此内容 |
| `order` | 展示顺序，从 1 开始，App 按此排序 |

问题数量：**3–5 个**，建议 3 个（小学）到 5 个（高中）。

---

### 12.4 新增场景的完整步骤

#### 第一步：用 AI 生成图片

推荐使用以下任意工具：
- **Gemini**（gemini.google.com）
- **ChatGPT / DALL·E**
- **Midjourney**、**Stable Diffusion** 等

给 AI 的提示词示例（根据年级调整）：

```
# Primary（10-12 岁）
Generate a simple, colorful illustration of a zoo scene.
Include elephants, giraffes, and children feeding animals.
Style: flat illustration, bright colors, clear and recognizable elements.
No complex backgrounds.

# Junior（13-15 岁）
Generate an engaging scene showing a busy city market.
Include vendors, shoppers, and various food stalls.
Style: realistic illustration with enough detail for discussion.

# Senior（16-18 岁）
Generate a thought-provoking scene showing the effects of climate change.
Include contrasting elements: a healthy forest vs. a barren landscape.
Style: photorealistic, rich in contextual detail.
```

保存图片为 `image.jpg`（或 `image.png`），建议分辨率不低于 800×600，文件大小控制在 500KB 以内。

#### 第二步：用 AI 生成问题和元数据

将图片上传给 AI（Gemini、ChatGPT 均支持图片输入），发送以下提示词：

```
I'm creating an English speaking practice activity for Chinese students.

Please look at this image and generate the following in JSON format:

1. A "meta" object with:
   - "title": a short English title for this scene (5 words max)
   - "imageAlt": a one-sentence description of the image (for accessibility)
   - "imageDescription": a detailed description (3-5 sentences) covering all visible elements, 
     actions, and context in the image. This will be used as a backup when the image 
     cannot be sent to the AI evaluator.

2. A "questions" array with 3 questions suitable for [PRIMARY/JUNIOR/SENIOR] students 
   (ages [10-12/13-15/16-18]):
   - PRIMARY: simple factual questions with clear answers (e.g., "What color is the dog?")
   - JUNIOR: open-ended descriptive questions (e.g., "What is happening in this picture?")
   - SENIOR: reflective or analytical questions (e.g., "How does this scene make you feel?")
   
   Each question should have: "id" (q1, q2, q3...), "text", "order"

Respond ONLY with valid JSON, no extra explanation.
```

AI 返回的 JSON 示例：

```json
{
  "meta": {
    "title": "A Day at the Zoo",
    "imageAlt": "A colorful zoo scene with children feeding giraffes",
    "imageDescription": "A sunny day at the zoo. Two children in colorful clothes are feeding a giraffe near a wooden fence. An elephant is visible in the background near a water pond. A zookeeper in a green uniform is talking to a group of students. The sky is clear blue with a few white clouds."
  },
  "questions": [
    { "id": "q1", "text": "What animals can you see in this picture?", "order": 1 },
    { "id": "q2", "text": "What are the children doing?", "order": 2 },
    { "id": "q3", "text": "Have you ever been to a zoo? What did you see there?", "order": 3 }
  ]
}
```

#### 第三步：创建文件夹和文件

1. 在 `public/scenes/` 下创建新文件夹，按命名规则命名（如 `primary_zoo`）
2. 将图片保存为 `image.jpg` 放入文件夹
3. 创建 `meta.json`，内容为：

```json
{
  "id": "primary_zoo",
  "title": "A Day at the Zoo",
  "gradeLevel": "primary",
  "imageAlt": "A colorful zoo scene with children feeding giraffes",
  "imageDescription": "A sunny day at the zoo. Two children in colorful clothes...",
  "createdAt": "2024-01-15"
}
```

4. 创建 `questions.json`，内容为问题数组（格式见上方）

#### 第四步：更新场景索引

打开 `public/scenes/index.json`，在 `scenes` 数组末尾添加新场景的 ID：

```json
{
  "scenes": [
    "primary_farm",
    "junior_market",
    "primary_zoo"
  ]
}
```

**完成！** App 下次启动时会自动发现新场景。

---

### 12.5 删除场景

1. 删除 `public/scenes/` 下对应的场景文件夹（连同里面所有文件）
2. 打开 `public/scenes/index.json`，从 `scenes` 数组中删除该场景的 ID

```json
{
  "scenes": [
    "primary_farm",
    "junior_market"
  ]
}
```

> **注意：** 删除场景不会影响已保存在 Firebase 中的历史记录，历史记录中该场景的 `sceneId` 字段仍然保留，只是再选择时不会再次出现。

---

### 12.6 修改现有场景

- **修改问题**：直接编辑 `questions.json`，修改 `text` 字段。已有的历史记录不受影响（历史记录中存的是问题文字本身，不是引用）。
- **替换图片**：直接替换 `image.jpg` 文件，保持文件名不变。
- **修改元数据**：直接编辑 `meta.json`，修改 `title` 或 `imageDescription`。
- **修改场景 ID（改文件夹名）**：需要同时更新 `meta.json` 中的 `id` 字段和 `index.json` 中的场景 ID，并重命名文件夹。**不建议修改已有历史记录对应的场景 ID**，会导致历史记录中的 `sceneId` 无法对应到场景标题。

---

### 12.7 场景设计建议

**图片选择：**
- 图片内容要有足够的细节，让孩子有话可说（避免只有一个物体的过于简单的图片）
- 避免包含文字（如招牌、标语），防止孩子直接读出答案
- 图片风格参考年级：小学用卡通/插画风，初中用写实插画，高中可用摄影风

**问题设计：**
- 问题之间应有递进关系：第一题最简单（描述看到的），后续题目逐渐加深
- 最后一道题最好有开放性，让孩子联系自身经历
- 避免需要非常专业词汇才能回答的问题
- 问题使用孩子年龄段熟悉的语法结构

**`imageDescription` 写作建议：**
- 从整体到细节：先描述场景背景，再描述前景的具体动作和人物
- 包含颜色、数量、位置等具体信息（对 AI 评分"答案相关性"维度很重要）
- 3–5 句话，覆盖图片中所有可能被问到的内容

---

### 12.8 快速上手：用 AI 批量准备场景

如果要一次准备多个场景，可以用以下批量提示词（一次发给 AI）：

```
I need to create 3 English speaking practice scenes for Chinese students.
Please generate a complete scene package for each of the following topics:

1. Topic: "Farm animals" | Grade: Primary (ages 10-12)
2. Topic: "A busy market" | Grade: Junior (ages 13-15)  
3. Topic: "City transportation" | Grade: Junior (ages 13-15)

For each scene, provide:
- A suggested image generation prompt (for DALL-E or Midjourney)
- meta.json content (title, imageAlt, imageDescription - describe what the generated image would look like)
- questions.json content (3 questions appropriate for the grade level)

Format: one JSON block per scene, labeled with the topic name.
```

这样可以一次得到多个场景的完整内容，再逐个生成图片并按步骤创建文件即可。
