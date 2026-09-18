// Local 批量实测脚本：3 问 3 答 + 1 图 + 计时 + 截断判定
// 用法: node scripts/testLocalBatch.mjs
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const publicDir = path.resolve(__dirname, '../public')
const configPath = path.join(publicDir, 'config.json')
const metaPath = path.join(publicDir, 'scenes/scene01/meta.json')
const qsPath = path.join(publicDir, 'scenes/scene01/questions.json')
const imagePath = path.join(publicDir, 'scenes/scene01/image.jfif')

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'))
const qs = JSON.parse(fs.readFileSync(qsPath, 'utf8')).questions.sort((a, b) => a.order - b.order)

const imageBuf = fs.readFileSync(imagePath)
const imageBase64 = imageBuf.toString('base64')
const imageMime = 'image/jpeg'

// 中学生简短口语答案（模拟正常 junior）
const answers = [
  'There are green apples, yellow bananas and oranges on the table.',
  'He is taking a photo of the market. He looks happy.',
  'It is sunny. The sky is bright and people wear short sleeves.',
]

const items = qs.map((q, i) => ({
  questionId: q.id,
  question: q.text,
  answer: answers[i] ?? answers[0],
}))

function buildBatchEvaluationPrompt({ imageDescription, items }) {
  const qaBlocks = items
    .map((it, idx) => `Q${idx + 1} (id:${it.questionId}): "${it.question}"\nA${idx + 1}: "${it.answer}"`)
    .join('\n\n')
  return `You are a STRICT but supportive English teacher for Chinese junior students (13-15, average level in mainland China).

Image description: "${imageDescription}"

Three questions and student answers (same image, junior level):
${qaBlocks}

Task: Grade EACH answer strictly on 0-100: vocabulary, grammar, relevance. Also overall 0-100 per answer. No pronunciation. Be honest - high scores must still have deductions. Even overall 88 must have at least two distinct issues in different dimensions.

Rules (apply to EACH of the 3 answers):
- For EACH of vocabulary, grammar, relevance: give int score AND one-sentence reason (≤15 English words / 25 Chinese chars). If score < 90, reason MUST quote a short fragment from that student's answer with "..." that caused deduction.
- Overall 88 must list at least two distinct issues (different dimensions) and two actionable suggestions, each with ONE corrected example sentence (≤10 words) the student can imitate.
- Keep each of strengths/weaknesses/suggestions to 1 sentence, concise. Total JSON for 3 answers must be under 500 words.
- Tone: one sentence praise first, then direct improvements. No empty praise.
- You MUST output a single JSON object and nothing else. Do not use markdown headings like "Strengths ZH:" outside JSON. Start with { and end with }. Example:
{"results":[{"questionId":"q1","vocabulary":85,"vocabulary_reason":"Repetition of \\"good\\" in \\"...good fruits...\\"","vocabulary_reason_zh":"中文...\\"","grammar":82,"grammar_reason":"...","grammar_reason_zh":"...","relevance":90,"relevance_reason":"...","relevance_reason_zh":"...","overall":85,"comment":"...","comment_zh":"...","strengths":"...","strengths_zh":"...","weaknesses":"...","weaknesses_zh":"...","suggestions":"...","suggestions_zh":"..."}, {"questionId":"q2", ...}, {"questionId":"q3", ...}]}
- Respond ONLY with JSON:
{
  "results": [
    {
      "questionId": "q1",
      "vocabulary": int,
      "vocabulary_reason": "EN one sentence, quote \\"...\\" if <90",
      "vocabulary_reason_zh": "中文一句话，引用\\"...\\"",
      "grammar": int,
      "grammar_reason": "EN one sentence, quote \\"...\\" if <90",
      "grammar_reason_zh": "中文一句话，引用\\"...\\"",
      "relevance": int,
      "relevance_reason": "EN one sentence, quote \\"...\\" if <90",
      "relevance_reason_zh": "中文一句话，引用\\"...\\"",
      "overall": int,
      "comment": "1 sentence praise EN",
      "comment_zh": "对应的中文鼓励",
      "strengths": "1 sentence EN - what was good",
      "strengths_zh": "中文亮点",
      "weaknesses": "1 sentence EN - specific error, quote \\"...\\"",
      "weaknesses_zh": "中文指错并引用原文",
      "suggestions": "2 numbered tips EN, each with Example: \\"...\\"",
      "suggestions_zh": "中文2条技巧各带仿写句"
    },
    {"questionId":"q2", ...},
    {"questionId":"q3", ...}
  ]
}

No explanation outside JSON.`
}

const prompt = buildBatchEvaluationPrompt({ imageDescription: meta.imageDescription, items })

const target = config.local.baseURL && config.local.baseURL.startsWith('/') ? 'http://172.18.0.110:8080/v1' : config.local.baseURL
const url = `${target.replace(/\/$/, '')}/chat/completions`

console.log('=== Local Batch Test ===')
console.log('image:', imagePath, `size=${(imageBuf.length/1024).toFixed(1)}KB base64=${(imageBase64.length/1024).toFixed(1)}KB`)
console.log('questions:', qs.map(q=>q.id).join(','))
console.log('answers:', answers)
console.log('prompt length:', prompt.length, 'prompt preview:', prompt.slice(0, 200).replace(/\n/g,' '))
console.log('target:', url, 'model:', config.local.model)
console.log('--- sending ---')

function extractBalancedJson(text) {
  const start = text.indexOf('{')
  if (start===-1) return null
  let depth=0, inStr=false, esc=false
  for(let i=start;i<text.length;i++){
    const ch=text[i]
    if(inStr){ if(esc) esc=false; else if(ch==='\\') esc=true; else if(ch==='"') inStr=false }
    else { if(ch==='"') inStr=true; else if(ch==='{') depth++; else if(ch==='}'){ depth--; if(depth===0) return text.slice(start,i+1)}}
  }
  return text.slice(start)
}

async function call(maxTokens, useJsonMode){
  const messages = [{
    role:'user',
    content:[
      {type:'text', text: prompt},
      {type:'image_url', image_url:{url:`data:${imageMime};base64,${imageBase64}`}},
    ]
  }]
  const body = {
    model: config.local.model,
    messages,
    temperature:0.7,
    max_tokens: maxTokens,
    ...(useJsonMode?{response_format:{type:'json_object'}}:{}),
  }
  const start = Date.now()
  const res = await fetch(url, {
    method:'POST',
    headers:{'Content-Type':'application/json', Authorization:`Bearer ${config.local.apiKey||'EMPTY'}`},
    body: JSON.stringify(body),
    // 不设 signal，让其跑完以测真实耗时
  })
  const elapsed = Date.now()-start
  console.log(`\n--- response maxTokens=${maxTokens} jsonMode=${useJsonMode} elapsed=${elapsed}ms status=${res.status} ---`)
  const textRaw = await res.text()
  let data
  try{ data = JSON.parse(textRaw)}catch(e){ console.log('Raw not JSON, first 800:', textRaw.slice(0,800)); throw e}
  const choice = data.choices?.[0]
  const content = choice?.message?.content ?? ''
  console.log('finish_reason:', choice?.finish_reason, 'content length:', content.length)
  console.log('content preview 0-800:', content.slice(0,800))
  // 尝试解析批次
  const candidate = extractBalancedJson(content)
  if(!candidate) console.log('No balanced JSON found')
  else {
    console.log('candidate length:', candidate.length, 'endsWith }:', candidate.trim().endsWith('}'))
    try{
      const obj = JSON.parse(candidate)
      console.log('parsed keys:', Object.keys(obj), 'results len:', Array.isArray(obj.results)?obj.results.length:'N/A')
      if(Array.isArray(obj.results)){
        obj.results.forEach((r,i)=>{
          console.log(`  [${i}] ${r.questionId} overall=${r.overall} V=${r.vocabulary} G=${r.grammar} R=${r.relevance} truncated? len reasons=${(r.vocabulary_reason||'').length}/${(r.grammar_reason||'').length}`)
        })
      }
    }catch(e){ console.log('candidate JSON parse failed:', e.message, candidate.slice(0,500))}
  }
  const truncated = choice?.finish_reason==='length' || content.length>= maxTokens*3 // 粗略
  console.log('疑似截断:', truncated, 'finish_reason length?', choice?.finish_reason==='length')
  return {elapsed, finish_reason: choice?.finish_reason, contentLength: content.length, raw: content}
}

try{
  // 默认 2800 json_mode true
  const r1 = await call(2800, true)
  // 若截断则再试 3500
  if(r1.finish_reason==='length' || r1.contentLength> 2500){
    console.log('\n=== retry 3500 ===')
    await call(3500, true)
  }
  // 再试无 json_mode 的 2800（对比）
  console.log('\n=== also test without json_mode 2800 ===')
  await call(2800, false)
}catch(e){
  console.error('Test failed:', e.message)
  console.error(e.stack)
}
