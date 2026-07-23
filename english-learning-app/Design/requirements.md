# Requirements Document：Chat With Me

## Introduction

Chat With Me 是一个互动英语口语练习 Web 应用，专为中国大陆的儿童设计。应用提供两种练习模式：**固定场景模式（Mode 1）** 使用预先准备好的图片和问题，让孩子流畅地完成对话练习；**AI 动态模式（Mode 2）** 使用 Google Gemini 实时生成图片和问题，提供无限多样的练习内容。两种模式均通过 AI 对孩子的口语回答进行评分，并生成鼓励性反馈。系统支持多个儿童档案，通过 Firebase Firestore 实现多设备历史记录同步。

---

## Glossary

- **App**：本文档描述的 Chat With Me Web 应用。
- **User**：配置应用并管理儿童档案的家长或监护人。
- **Child**：使用应用练习英语的学习者。
- **Profile**：代表一个孩子的命名账户，存储其年级和学习历史。
- **Session**：一次完整的学习单元，包含图片展示、若干轮问答和最终报告。
- **Round**：Session 中的一轮问答循环。
- **Grade_Level**：三个基于年龄的学习层级 —— Primary（10–12 岁）、Junior（13–15 岁）、Senior（16–18 岁）。
- **Mode 1 / Preset Mode**：固定场景模式，使用预先准备好的场景资源。
- **Mode 2 / Dynamic Mode**：AI 动态模式，图片和问题均由 AI 实时生成。
- **Scene**：Mode 1 中的一个对话场景，包含一张图片和若干预设问题。
- **AI_Provider**：用于文字生成、图片生成（Mode 2）和答案评分的外部 AI 服务，默认使用 Google Gemini。
- **TTS_Engine**：文字转语音组件，使用浏览器内置 Web Speech API。
- **ASR_Engine**：语音识别组件，使用浏览器内置 Web Speech API，将孩子的口语转为文字。
- **Evaluator**：AI_Provider 中对孩子回答进行四维评分的功能。
- **Config_File**：用户可编辑的配置文件，指定 AI 提供商、API 密钥、模型名称等设置。
- **Score**：0–100 范围内单个评分维度的数值评级。
- **Report**：AI 生成的对孩子在一次 Session 中表现的简短总结。
- **Firebase**：用于云端数据存储和多设备同步的 Google Firebase 平台。

---

## Requirements

### Requirement 0：应用入口与模式选择

**User Story：** 作为家长，我希望在进入应用时清楚地看到两种练习模式，并能选择合适的模式开始练习。

#### Acceptance Criteria

1. 应用启动后 SHALL 显示主页，展示"固定场景对话"（Mode 1）和"AI 动态对话"（Mode 2）两个模式入口。
2. 每个模式入口 SHALL 显示该模式的简短说明文字。
3. 若某个模式尚未实现，该模式的入口按钮 SHALL 置灰（disabled）并显示"即将推出"标签，不可点击。
4. 模式的可用状态 SHALL 通过代码中的 feature flag 常量控制，无需修改应用逻辑代码。

---

### Requirement 1：儿童档案管理

**User Story：** 作为家长，我希望为每个孩子创建独立的档案，使各自的学习记录分开保存并可在任意设备访问。

#### Acceptance Criteria

1. App SHALL 允许用户创建包含名称和 Grade_Level 的 Profile。
2. App SHALL 允许用户编辑现有 Profile 的名称和 Grade_Level。
3. App SHALL 允许用户删除 Profile 及其所有关联的 Session 历史。
4. 打开 App 时 SHALL 显示所有现有 Profile，并允许用户在开始 Session 前选择一个。
5. App SHALL 将所有 Profile 数据和 Session 历史存储在 Firebase 中，以便多设备访问。
6. 若 Profile 名称为空或仅含空白字符，App SHALL 拒绝输入并显示错误信息。

---

### Requirement 2：Mode 1 —— 场景资源管理

**User Story：** 作为内容准备者，我希望通过文件系统方便地管理对话场景，无需通过 Web 页面操作。

#### Acceptance Criteria

1. 所有场景资源 SHALL 存放在 `public/scenes/` 目录下，每个场景为一个子文件夹。
2. 场景文件夹命名 SHALL 遵循 `{gradeLevel}_{描述}` 格式（如 `primary_zoo`），App 通过文件夹名前缀自动识别年级。
3. 每个场景文件夹 SHALL 包含：`meta.json`（元数据）、`image.jpg`（场景图片）、`questions.json`（问题列表，3–5 个问题）。
4. `public/scenes/index.json` SHALL 维护所有场景 ID 的列表，App 通过此文件发现可用场景。
5. 增加场景 SHALL 只需：创建场景文件夹并在 `index.json` 中添加场景 ID。
6. 删除场景 SHALL 只需：删除场景文件夹并从 `index.json` 移除对应 ID。
7. `meta.json` 中的 `gradeLevel` 字段与文件夹名前缀不一致时，App SHALL 打印警告但不中断运行。

---

### Requirement 3：Mode 1 —— 固定场景会话流程

**User Story：** 作为孩子，我希望看到一张图片并回答关于它的问题，通过自然对话练习英语。

#### Acceptance Criteria

1. 选择 Profile 并进入 Mode 1 后，App SHALL 从可用场景中随机选择一个场景开始 Session。
2. 随机选择 SHALL 优先选择该 Profile 尚未完成过的场景；若所有场景均已完成则重置，从全部场景中重新随机选取。
3. App SHALL 在会话全程显示场景图片，图片不因进入下一题而消失。
4. App SHALL 逐题展示预设问题，每题展示时 TTS_Engine SHALL 自动朗读问题。
5. 每道题 SHALL 显示录音按钮，孩子按下后 ASR_Engine 开始录音，停止后显示识别文字。
6. ASR 识别结果 SHALL 显示在可编辑的文本框中，孩子可在提交前修改文字。
7. 孩子点击提交后，App SHALL 立即在后台向 AI_Provider 发起该题的评分请求（不等待结果），并立即进入下一题。
8. 所有问题回答完毕后，App SHALL 等待所有后台评分请求完成（或超时），然后进入结算页。
9. 单个评分请求超时时间为 15 秒；超时的题目在结算页显示"评分不可用"，不阻塞整体结算。
10. 结算页 SHALL 展示每题的问题、孩子的回答、四维分数和鼓励语。
11. App SHALL 记录每个 Profile 完成过的场景 ID，用于历史展示和随机场景去重。

---

### Requirement 4：Mode 2 —— AI 动态会话初始化

**User Story：** 作为孩子，我希望 App 为我生成一张新图片并提问，让我有话题用英语描述。

#### Acceptance Criteria

1. 选择 Profile 并进入 Mode 2 后，App SHALL 向 AI_Provider 发送请求，生成适合该 Profile Grade_Level 的图片。
2. AI_Provider 返回图片后，App SHALL 将图片显示在屏幕上。
3. 图片展示后，App SHALL 请求 AI_Provider 生成第一道问题（Round 1），无论图片是 AI 生成还是 fallback 静态图片。
4. 若 AI 图片生成失败，App SHALL 使用预置的 fallback 静态图片并继续流程，不中断 Session。
5. 若问题生成失败，App SHALL 显示用户友好的错误信息并提供重试选项。

---

### Requirement 5：年龄适配内容生成（Mode 2）

**User Story：** 作为家长，我希望图片和问题符合孩子的年龄和英语水平。

#### Acceptance Criteria

1. 生成图片时，AI_Provider SHALL 生成视觉上简洁、主题适合指定 Grade_Level 的内容。
2. Grade_Level 为 Primary 时，问题 SHALL 为有明确答案的简单事实性问题。
3. Grade_Level 为 Junior 时，问题 SHALL 为开放式引导性问题。
4. Grade_Level 为 Senior 时，问题 SHALL 为需要个人思考的反思性或分析性问题。
5. 生成 Round 2 和 Round 3 的问题时，AI_Provider SHALL 确保问题与同一图片相关，且不重复前几轮的提问角度。

---

### Requirement 6：语音录制与识别（两个模式共用）

**User Story：** 作为孩子，我希望通过录音按钮录下我的回答，让 App 听到我说的话。

#### Acceptance Criteria

1. 每题 SHALL 显示醒目的录音按钮。
2. 按下录音按钮后，ASR_Engine SHALL 开始从麦克风捕获音频，并显示视觉录音指示（脉冲动画）。
3. 再次按下（或松开）按钮后，ASR_Engine SHALL 将音频转为文字并显示在屏幕上。
4. 若 ASR_Engine 发生技术故障（麦克风不可用、API 错误等），App SHALL 显示错误信息并允许重试。
5. 若转录结果为空（非技术故障，如孩子未发声），App SHALL 显示重试提示，**不显示错误信息**。
6. App 在非安全上下文（HTTP 非 localhost）运行时，SHALL 显示明确的 HTTPS 要求提示，而非通用的浏览器不支持提示。

---

### Requirement 7：TTS 朗读（两个模式共用）

**User Story：** 作为孩子，我希望点击喇叭按钮时能听到问题的朗读，帮助我理解发音。

#### Acceptance Criteria

1. 每道问题旁 SHALL 显示朗读按钮（喇叭图标）。
2. 每题首次展示时，TTS_Engine SHALL 自动朗读问题一次。
3. 点击朗读按钮时，TTS_Engine SHALL 朗读问题。
4. TTS 开始播放时 SHALL 显示视觉动画；播放结束后图标恢复默认。
5. 在 TTS 正在播放时点击按钮，SHALL 中断当前播放并重新开始，同时重置视觉动画。
6. TTS 不可用时，App SHALL 显示通知，问题文字保持可见。

---

### Requirement 8：答案评分（两个模式共用）

**User Story：** 作为孩子，我希望 App 对我的回答从多个维度打分，让我知道哪里需要改进。

#### Acceptance Criteria

1. ASR_Engine 产生非空转录后（Mode 2）或孩子提交答案后（Mode 1），App SHALL 将答案发送给 Evaluator 评分。
2. Evaluator SHALL 对以下四个维度各返回 0–100 的 Score：词汇准确性、发音准确性、语法正确性、答案相关性。
3. Mode 1 评分时 SHALL 将场景图片（base64）连同提示词一起发送给 AI，以提高评分准确性；图片发送失败时降级为仅发文字描述。
4. 评分返回错误或不完整时，App SHALL 显示可用的分数，并标注无法评分的维度。

---

### Requirement 9：鼓励与报告

**User Story：** 作为孩子，我希望每次回答后收到鼓励，并在完成所有问题后看到总体报告。

#### Acceptance Criteria

1. Mode 2 中，每轮评分后 SHALL 显示 AI 生成的鼓励语，语气温和且适合儿童。
2. Mode 1 中，鼓励语随评分结果一同在结算页展示。
3. 所有问题完成后，App SHALL 显示结算报告页，包含综合分数（0–100）和简短分析（不超过 150 字）。
4. App SHALL 将完整 Session 数据（图片描述、问题、答案、分数、报告）保存到 Firebase。
5. 若报告生成失败，App SHALL 展示各题分数并说明总结无法生成，仍保存可用数据。

---

### Requirement 10：学习历史

**User Story：** 作为家长，我希望查看孩子的历史记录，追踪进步情况。

#### Acceptance Criteria

1. App SHALL 提供可从 Profile 主页访问的历史记录屏幕。
2. 历史列表 SHALL 按时间降序显示过去的 Session，每条显示日期、模式标签和综合分数。
3. 点击历史记录 SHALL 显示完整 Session 详情（问题、答案、各维度分数、报告）。
4. 加载历史数据期间 SHALL 显示全屏加载指示器，**不显示部分数据**，直到全部加载完成。

---

### Requirement 11：配置文件

**User Story：** 作为用户，我希望通过配置文件修改 AI 提供商和密钥，无需修改应用代码。

#### Acceptance Criteria

1. App SHALL 在启动时从 `public/config.json` 读取 AI 提供商设置。
2. 配置文件 SHALL 包含：AI 提供商名称、API 密钥、文本模型名称、TTS 语言/语音设置、Firebase 配置、Mode 1 评分超时时间。
3. 配置文件缺失或字段无效时，App SHALL 在启动时显示字段级错误信息，并阻止进入主应用。
4. `gemini.imageModel` 字段仅 Mode 2 需要；缺失时不阻止启动，但 Mode 2 入口 SHALL 显示相应警告。

---

### Requirement 12：UI 响应性与无障碍

**User Story：** 作为使用平板、手机或桌面浏览器的孩子，我希望界面清晰易用，专注于英语练习。

#### Acceptance Criteria

1. App SHALL 在 Chrome、Edge、Safari 的现代版本上正常运行（Firefox ASR 功能受限，应显示提示）。
2. App SHALL 在 375px–1440px 屏幕宽度范围内正确响应式渲染。
3. 问题文字和按钮标签字体 SHALL 不小于 16px。
4. 文字与背景的色彩对比度 SHALL 满足 WCAG 2.1 AA 标准。
5. 会话进行中 SHALL 在单列布局内展示所有元素，无需滚动；极小屏幕（低于约 360px 视口高度）允许滚动，但元素尺寸不得低于最小可读标准。
