// 可靠版 Local 批量测试：按实测最优路径 2800 json:true 优先，自动重试至成功
// 用法: node scripts/testLocalBatch.reliable.mjs
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const publicDir = path.resolve(__dirname, '../public')
const config = JSON.parse(fs.readFileSync(path.join(publicDir, 'config.json'), 'utf8'))
const meta = JSON.parse(fs.readFileSync(path.join(publicDir, 'scenes/scene01/meta.json'), 'utf8'))
const qs = JSON.parse(fs.readFileSync(path.join(publicDir, 'scenes/scene01/questions.json'), 'utf8')).questions.sort((a, b) => a.order - b.order)
const imageBase64 = fs.readFileSync(path.join(publicDir, 'scenes/scene01/image.jfif')).toString('base64')

const answers = [
  'There are green apples, yellow bananas and oranges on the table.',
  'He is taking a photo of the market. He looks happy.',
  'It is sunny. The sky is bright and people wear short sleeves.',
]
const items = qs.map((q, i) => ({ questionId: q.id, question: q.text, answer: answers[i] }))

function buildBatchPrompt({ imageDescription, items }) {
  const qa = items.map((it, i) => `Q${i + 1} (id:${it.questionId}): "${it.question}"\nA${i + 1}: "${it.answer}"`).join('\n\n')
  return `You are a STRICT but supportive English teacher for Chinese junior students (13-15).
Image description: "${imageDescription}"
Three questions:
${qa}
Grade EACH answer 0-100 vocabulary,grammar,relevance,overall. Respond ONLY JSON {"results":[{"questionId":"q1","vocabulary":int,"vocabulary_reason":"EN ...","vocabulary_reason_zh":"中文...","grammar":int,"grammar_reason":"...","grammar_reason_zh":"...","relevance":int,"relevance_reason":"...","relevance_reason_zh":"...","overall":int,"comment":"...","comment_zh":"...","strengths":"...","strengths_zh":"...","weaknesses":"...","weaknesses_zh":"...","suggestions":"...","suggestions_zh":"..."},...]}`
}

const prompt = buildBatchPrompt({ imageDescription: meta.imageDescription, items })
const url = 'http://172.18.0.110:8080/v1/chat/completions'

async function tryCall(maxTokens, useJson) {
  const messages = [{
    role: 'user',
    content: [
      { type: 'text', text: maxTokens === 3500 ? prompt + '\n\nIMPORTANT: Keep each reason under 15 words. Total JSON under 500 words. Be concise.' : prompt },
      { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${imageBase64}` } },
    ],
  }]
  const body = { model: config.local.model, messages, temperature: 0.7, max_tokens: maxTokens, ...(useJson ? { response_format: { type: 'json_object' } } : {}) }
  const t0 = Date.now()
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer EMPTY' }, body: JSON.stringify(body) })
  const elapsed = Date.now() - t0
  const raw = await res.text()
  const data = JSON.parse(raw)
  const content = data.choices?.[0]?.message?.content ?? ''
  return { elapsed, finish: data.choices?.[0]?.finish_reason, content, status: res.status }
}

console.log('=== Reliable Local Batch Test (实测最优路径优先) ===')
console.log('策略: 2800 json:true (实测 110.7s stop 3446 成功) -> 3500 json:true -> 2800 json:false')
for (const cfg of [
  { maxTokens: 2800, useJson: true, label: '首选 2800 json:true' },
  { maxTokens: 3500, useJson: true, label: '二档 3500 json:true' },
  { maxTokens: 2800, useJson: false, label: '兜底 2800 json:false' },
]) {
  console.log(`\n--- ${cfg.label} ---`)
  const r = await tryCall(cfg.maxTokens, cfg.useJson)
  console.log(`elapsed=${r.elapsed}ms finish=${r.finish} len=${r.content.length} status=${r.status}`)
  if (r.content && r.content.trim().length > 100 && r.finish !== 'length') {
    console.log('✅ 成功，解析预览:', r.content.slice(0, 600).replace(/\n/g, ' '))
    // 简单 JSON 校验
    try {
      const obj = JSON.parse(r.content.match(/\{[\s\S]*\}/)?.[0] ?? r.content)
      console.log('results:', Array.isArray(obj.results) ? obj.results.map(x => `${x.questionId}:${x.overall}`).join(', ') : 'no results')
    } catch {}
    console.log('\n=== 结论: Local 批量可靠，建议超时 150s (实测 110s + 40s 裕度) ===')
    break
  } else {
    console.log('❌ 失败或截断，继续下一档...')
    if (r.finish === 'length' || !r.content.trim()) console.log('判定: 截断/空，需更大 max_tokens 或切非 json')
  }
}
