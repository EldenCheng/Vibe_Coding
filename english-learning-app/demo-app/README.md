# Chat With Me — Demo App

最小可跑闭环 Demo：多场景（v0.2.6：场景1 集市 13 题三级题库 / 场景2 Yoyo 生日会 16 题四级题库含角色扮演；打开随机选场景，URL `?scene=scene02` 可指定）每级随机抽 1 题本页内不重复 → TTS 读题 → STT 录音（v0.2.7 连续录音：停顿不断开、停止后可追加续录、实时上屏）→可编辑→答完批量发大模型识图评分（图片/场景描述+问题+回答，一次请求）→ 折叠报告展示每题分数+短评（英文+中文翻译切换）+ 等待水果掉落小游戏。评分受众按场景注入（scene01 面向 13-15 初中、scene02 面向 10-12 小学高年级）。

> **新环境？请直接看 [`运行教程.md`](./运行教程.md) —— 含环境要求、Key 获取、HTTPS、常见问题的逐步教程。**

## 快速开始
```bash
cd english-learning-app/demo-app
npm install
# 1) 配置 Key（推荐环境变量，不提交到仓库；也可写入 .env.local）
# Gemini:
$env:VITE_GEMINI_API_KEY="你的key"; npm run dev
# 火山方舟 GLM（可选）:
$env:VITE_GLM_API_KEY="你的Ark key"; npm run dev
# 也可直接填到 public/config.json 的 gemini.apiKey / glm.apiKey

# 2) 启动（http://localhost:5173）
npm run dev
# 局域网平板访问需 HTTPS：一键脚本 pwsh ./scripts/setup-https.ps1（mkcert 自动化，详见 局域网HTTPS证书分发详细教程.md）；本机用 http://localhost:5173 即可
```

## 配置
`public/config.json`：
- `aiProvider`: `gemini` | `glm` | `local`（默认 `gemini`，页面右上角可实时切换，无需重启）
- `gemini.textModel`: 默认 `gemini-3.6-flash`，失败回落 `gemini-3.5-flash`（2.0/2.5 Flash 已于 2026 年对新用户停服，实测 404 提示用 3.6）
- `glm.model`: 默认 `glm-5-3-flash-260828`（火山方舟 Ark，GLM-5 系列首个原生多模态模型；走 `/glm-v1` Vite 代理，key 用 `VITE_GLM_API_KEY`）
- `local.baseURL`: `/local-v1`（Vite proxy 到 `http://172.18.0.110:8080/v1`），`directBaseURL` 为直连地址
- `demo.imageStrategy`: 评分模式 `descriptionOnly`（默认，只发 scoringDescription，快）| `image`（发压缩图，慢但保真）——切换方法与影响详见 `运行教程.md` §4.4
- `demo` 超时分档：传图档 Gemini/GLM 120s、Local 360s；描述档（`imageStrategy: "descriptionOnly"`，不发图仅发 scoringDescription）Gemini 45s、GLM/Local 60s
- `tts` / `asr`：`lang: en-US`, `rate:0.9, pitch:1.0`

## 目录
- `public/scenes/index.json` — 场景注册表（新增场景后在此登记 id）
- `public/scenes/scene01/`、`scene02/` — 场景资源（image.jfif + meta.json 含 audience/两种描述 + questions.json 含 level）
- `src/config/configLoader.ts` — 加载校验（含 `VITE_GEMINI_API_KEY`/`VITE_GLM_API_KEY` 环境变量注入）
- `src/speech/` — TTS/ASR 封装
- `src/ai/` — Gemini / GLM（火山 Ark）/ Local 三 Provider
- `src/demo/usePresetSession.ts` — 多题状态机 + 多场景解析 + 每级随机选题；`deprecated/useDemoSession.ts` 为 v0.1.x 单题存档（无引用）
- `src/components/` — 图片/问答/等待/折叠报告

## 常见问题
- **麦克风不可用**：ASR 要求 `HTTPS` 或 `http://localhost`，局域网 `http://192.168.x.x` 会被浏览器拒绝；用 `pwsh ./scripts/setup-https.ps1` 一键自签证书或只用 `localhost` 测试
- **Gemini 报错 404/model not found**：`2.0/2.5 Flash` 已对新用户停服，实测提示改用 `gemini-3.6-flash`；已在配置中改为 `3.6-flash`→`3.5-flash` 自动回落
- **GLM 报错 model not found**：确认 `glm.model` 与火山 Ark 控制台模型页示例代码一致（当前 `glm-5-3-flash-260828`，页面 slug 为 `glm-5-3-flash` 不带后缀）；或改用 ep-xxx 接入点 ID
- **本地 Gemma4 / 火山 Ark CORS**：已通过 `vite.config.ts` 的 `/local-v1`、`/glm-v1` proxy 解决；不要直连
- **本地超时**：Local 传图档 360s（`demo.localEvaluationTimeoutMs`），等待页会显示预计时长提示

## 构建
```bash
npm run build && npm run preview
```
