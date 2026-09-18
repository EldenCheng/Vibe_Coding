// 细分测试：单题 vs 批量，有图 vs 无图
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const publicDir = path.resolve(__dirname, '../public')
const config = JSON.parse(fs.readFileSync(path.join(publicDir,'config.json'),'utf8'))
const meta = JSON.parse(fs.readFileSync(path.join(publicDir,'scenes/scene01/meta.json'),'utf8'))
const qs = JSON.parse(fs.readFileSync(path.join(publicDir,'scenes/scene01/questions.json'),'utf8')).questions.sort((a,b)=>a.order-b.order)
const imageBuf = fs.readFileSync(path.join(publicDir,'scenes/scene01/image.jfif'))
const imageBase64 = imageBuf.toString('base64')

const target = 'http://172.18.0.110:8080/v1'
const url = `${target}/chat/completions`

function buildSingle(q,a){
  return `You are a STRICT but supportive English teacher for Chinese junior students (13-15).
Image description: "${meta.imageDescription}"
Question: "${q}"
Student answer: "${a}"
Grade strictly on 0-100: vocabulary, grammar, relevance. Also overall 0-100.
Rules: For EACH of vocabulary, grammar, relevance: give int score AND one-sentence reason (≤15 words). If score <90, quote "..." fragment.
Respond ONLY with JSON: {"vocabulary":int,"vocabulary_reason":"EN ...","vocabulary_reason_zh":"中文...","grammar":int,"grammar_reason":"...","grammar_reason_zh":"...","relevance":int,"relevance_reason":"...","relevance_reason_zh":"...","overall":int,"comment":"...","comment_zh":"...","strengths":"...","strengths_zh":"...","weaknesses":"...","weaknesses_zh":"...","suggestions":"...","suggestions_zh":"..."}`
}

function buildBatch(items){
  const qa = items.map((it,i)=>`Q${i+1}(id:${it.questionId}): "${it.question}"\nA${i+1}: "${it.answer}"`).join('\n\n')
  return `You are a STRICT but supportive English teacher for Chinese junior students (13-15).
Image description: "${meta.imageDescription}"
Three questions:
${qa}
Grade EACH answer 0-100 vocabulary,grammar,relevance,overall. Respond ONLY JSON {"results":[{"questionId":"q1","vocabulary":int,"vocabulary_reason":"EN ...","vocabulary_reason_zh":"中文...","grammar":int,"grammar_reason":"...","grammar_reason_zh":"...","relevance":int,"relevance_reason":"...","relevance_reason_zh":"...","overall":int,"comment":"...","comment_zh":"...","strengths":"...","strengths_zh":"...","weaknesses":"...","weaknesses_zh":"...","suggestions":"...","suggestions_zh":"..."},...]}`
}

async function call(prompt, withImage, maxTokens, useJson){
  const messages = withImage ? [{
    role:'user',
    content:[
      {type:'text', text:prompt},
      {type:'image_url', image_url:{url:`data:image/jpeg;base64,${imageBase64}`}},
    ]
  }] : [{role:'user', content:prompt}]
  const body={model:config.local.model, messages, temperature:0.7, max_tokens:maxTokens, ...(useJson?{response_format:{type:'json_object'}}:{})}
  const t0=Date.now()
  const res=await fetch(url,{method:'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer EMPTY`}, body:JSON.stringify(body)})
  const elapsed=Date.now()-t0
  const txt=await res.text()
  let data; try{data=JSON.parse(txt)}catch(e){console.log('HTTP not JSON',txt.slice(0,500)); return}
  const content=data.choices?.[0]?.message?.content ?? ''
  console.log(`  elapsed=${elapsed}ms status=${res.status} finish=${data.choices?.[0]?.finish_reason} contentLen=${content.length} maxTokens=${maxTokens} json=${useJson} withImage=${withImage}`)
  console.log('  preview:', content.slice(0,400).replace(/\n/g,' '))
  return {elapsed, content}
}

console.log('=== Test 1: Single with image, json, 1800 (baseline) ===')
await call(buildSingle(qs[0].text, 'There are green apples, yellow bananas and oranges on the table.'), true, 1800, true)
console.log('\n=== Test 2: Single with image, json, 2800 ===')
await call(buildSingle(qs[0].text, 'There are green apples, yellow bananas and oranges on the table.'), true, 2800, true)
console.log('\n=== Test 3: Batch 3 with image, json, 2800 ===')
await call(buildBatch(qs.map((q,i)=>({questionId:q.id, question:q.text, answer:['There are green apples, yellow bananas and oranges on the table.','He is taking a photo of the market. He looks happy.','It is sunny. The sky is bright and people wear short sleeves.'][i]}))), true, 2800, true)
console.log('\n=== Test 4: Batch 3 NO image, json, 2800 ===')
await call(buildBatch(qs.map((q,i)=>({questionId:q.id, question:q.text, answer:['There are green apples, yellow bananas and oranges on the table.','He is taking a photo of the market. He looks happy.','It is sunny. The sky is bright and people wear short sleeves.'][i]}))), false, 2800, true)
console.log('\n=== Test 5: Batch 3 with image, NO json, 2800 ===')
await call(buildBatch(qs.map((q,i)=>({questionId:q.id, question:q.text, answer:['There are green apples, yellow bananas and oranges on the table.','He is taking a photo of the market. He looks happy.','It is sunny. The sky is bright and people wear short sleeves.'][i]}))), true, 2800, false)
