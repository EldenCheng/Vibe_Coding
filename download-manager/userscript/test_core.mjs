/**
 * 油猴脚本核心逻辑的 Node 桩测试（无需浏览器、无需管理器在跑）。
 *
 *   node userscript/test_core.mjs
 *
 * 覆盖三件最容易写错的事：
 *   1. 域名 → 预选下载器/方式（@match 白名单与实际域名是否对得上）；
 *   2. 集数/页码范围的校验（格式 + 语义）；
 *   3. buildTaskPayload() 生成的 {type,kind,form} 键，是否与后端各 adapter 的
 *      form_schema 一一对应（ebook 用 book、ehentai 用 url+range、video 用 mode+url+…）。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, 'download-to-manager.user.js'), 'utf8');

// ---- 最小桩：只够脚本加载与调用纯函数 ----
const menu = [];
globalThis.GM_registerMenuCommand = (name) => { menu.push(name); };
globalThis.GM_getValue = (_k, d) => d;
globalThis.GM_setValue = () => {};
globalThis.GM_xmlhttpRequest = () => {};
globalThis.document = { createElement: () => ({ style: {}, attachShadow: () => ({}) }) };
globalThis.window = globalThis;
globalThis.location = { href: 'https://example.com/' };

vm.runInThisContext(src, { filename: 'download-to-manager.user.js' });
const api = globalThis.__dmUserscript;

let failed = 0;
function check(name, cond, extra = '') {
  console.log((cond ? '  [OK]   ' : '  [FAIL] ') + name + (extra ? '  ' + extra : ''));
  if (!cond) failed++;
}
function throws(fn) {
  try { fn(); return null; } catch (e) { return e.message; }
}

console.log('== 0. 脚本暴露的接口 ==');
check('__dmUserscript 已暴露', !!api);
check('纯函数齐全', ['domainPreset', 'isEmbeddedSite', 'cautionFor', 'isValidSpec',
                     'statusLabel', 'fieldPlan', 'buildTaskPayload']
      .every((k) => typeof api[k] === 'function'));
check('注册了 3 个菜单项', menu.length === 3, JSON.stringify(menu));
check('用的是 GM_xmlhttpRequest（不是 fetch）',
      /GM_xmlhttpRequest/.test(src) && !/[^.\w]fetch\s*\(/.test(src));

console.log('== 0b. 任务状态文案（不能把英文枚举甩给用户）==');
const stCases = [['running', '运行中'], ['queued', '排队中'], ['completed', '已完成'],
                 ['partial_failed', '部分失败'], ['failed', '失败'], ['stopped', '已停止'],
                 ['interrupted', '服务重启中断']];
for (const [code, want] of stCases) {
  check(`statusLabel(${code}) = ${want}`, api.statusLabel({ status: code }) === want,
        api.statusLabel({ status: code }));
}
check('排队中带队列位置', api.statusLabel({ status: 'queued', queue_position: 2 }) === '排队中（第 2 位）',
      api.statusLabel({ status: 'queued', queue_position: 2 }));
check('未知状态不显示空白', api.statusLabel({ status: 'weird' }) === 'weird');
check('无状态字段回退为「已加入」', api.statusLabel({}) === '已加入');

console.log('== 1. 域名 → 预选 ==');
const presetCases = [
  ['https://e-hentai.org/g/3743290/8eee725d8c/', 'ehentai', ''],
  ['https://exhentai.org/g/1/ab/', 'ehentai', ''],
  ['https://xn--1jqx9a.als1004.space/other/chapters/id/32157.html', 'ebook', ''],
  ['https://www.bilibili.com/video/BV1xx411c7mD', 'video', 'ytdlp'],
  ['https://youtu.be/abc', 'video', 'ytdlp'],
  ['https://www.mvffm.net/play/123/', 'video', 'batch'],
  ['https://www1.ikanbot.com/play/968393', 'video', 'batch'],
  ['https://eacg.net/vodplay/1-2-3.html', 'video', 'batch'],
  ['https://未知站点.example/list/1', 'video', 'batch'],
  ['https://cdn.example.com/hls/abc/index.m3u8', 'video', 'get'],
];
for (const [href, type, mode] of presetCases) {
  const p = api.domainPreset(href);
  check(`domainPreset(${new URL(href).hostname}) = ${type}/${mode || '-'}`,
        p.type === type && p.mode === mode, JSON.stringify(p));
}

console.log('== 1b. @match ↔ SITES 单表必须一致（加站点改这两处，漏一个就报错）==');
// @match 只能在文件头部静态声明，无法由 SITES 生成，所以用测试来保证两者不脏。
const meta = src.slice(0, src.indexOf('==/UserScript=='));
const matchHosts = new Set();
for (const m of meta.matchAll(/@match\s+\*:\/\/([^/]+)\//g)) {
  let h = m[1].toLowerCase();
  if (h === '*') continue;            // 被注释掉的 *://*/* 宽匹配
  if (h.startsWith('*.')) h = h.slice(2);
  matchHosts.add(h);
}
const siteHosts = new Set(api.SITES.flatMap((s) => s.hosts.map((h) => h.toLowerCase())));
const missingInMatch = [...siteHosts].filter((h) => !matchHosts.has(h));
const extraInMatch = [...matchHosts].filter((h) => !siteHosts.has(h));
check('SITES 里的每个域名都写进了 @match', missingInMatch.length === 0,
      missingInMatch.length ? '缺: ' + missingInMatch.join(', ') : '');
check('@match 里的每个域名都在 SITES 表里', extraInMatch.length === 0,
      extraInMatch.length ? '多: ' + extraInMatch.join(', ') : '');
check('SITES 派生出的 PRESETS 数量一致', api.PRESETS.length === api.SITES.length,
      `${api.PRESETS.length} vs ${api.SITES.length}`);

console.log('== 2. 内嵌播放器站点（决定显示"线路"还是"每集候选"）==');
check('mvffm → 内嵌', api.isEmbeddedSite('https://www.mvffm.net/play/1/') === true);
check('movieffm → 内嵌', api.isEmbeddedSite('https://movieffm.net/x') === true);
check('ikanbot → 内嵌', api.isEmbeddedSite('https://www1.ikanbot.com/play/968393') === true);
check('eacg → 非内嵌（应显示每集候选）', api.isEmbeddedSite('https://eacg.net/vodplay/1-2-3.html') === false);
check('javdock 有警示文案', /滑动窗口/.test(api.cautionFor('https://javdock.com/x')));
check('普通站点无警示', api.cautionFor('https://eacg.net/x') === '');

console.log('== 2b. 字段显隐判断（线路/候选互斥；每集间隔对两种站点都有效）==');
let fp = api.fieldPlan('video', 'batch', 'https://www1.ikanbot.com/play/432956');
check('内嵌站点：显示线路、隐藏候选', fp.showLine === true && fp.showPick === false,
      JSON.stringify({ line: fp.showLine, pick: fp.showPick }));
check('内嵌站点：集数与间隔都可见', fp.showEpisodes === true && fp.showInterval === true);
fp = api.fieldPlan('video', 'batch', 'https://eacg.net/vodplay/1-2-3.html');
check('需嗅探站点：显示候选、隐藏线路', fp.showPick === true && fp.showLine === false,
      JSON.stringify({ line: fp.showLine, pick: fp.showPick }));
check('需嗅探站点：集数与间隔都可见', fp.showEpisodes === true && fp.showInterval === true);
fp = api.fieldPlan('video', 'ytdlp', 'https://www.bilibili.com/video/BV1');
check('ytdlp：batch 专属字段全隐藏',
      !fp.showEpisodes && !fp.showLine && !fp.showPick && !fp.showInterval);
fp = api.fieldPlan('video', 'get', 'https://cdn.example.com/index.m3u8');
check('get：显示 Referer/Cookie 区、隐藏 batch 字段',
      fp.showGet === true && !fp.showEpisodes && !fp.showPick);
fp = api.fieldPlan('ehentai', 'batch', 'https://e-hentai.org/g/1/ab/');
check('ehentai：只显示页码范围', fp.showRange === true && !fp.isVideo && !fp.showEpisodes);

console.log('== 3. 集数/页码范围校验 ==');const specCases = [['', true], ['1', true], ['1-12', true], ['1-12,15', true],
                   ['1-12, 15-20', true], ['abc', false], ['12-', false], ['1,,2', false],
                   ['0', false], ['5-3', false], ['1-0', false], ['-3', false]];
for (const [spec, want] of specCases) {
  check(`isValidSpec(${JSON.stringify(spec)}) = ${want}`, api.isValidSpec(spec) === want);
}

console.log('== 4. buildTaskPayload：键必须与后端 form_schema 对齐 ==');
// 期望键集合来自 backend/adapters/*.py 的 form_schema
const ALLOWED = {
  ebook: ['book'],
  ehentai: ['url', 'range'],
  video: ['mode', 'url', 'referer', 'cookie', 'episodes', 'line', 'pick', 'interval'],
};
function payloadKeys(state) {
  const p = api.buildTaskPayload(state);
  const bad = Object.keys(p.form).filter((k) => !ALLOWED[p.type].includes(k));
  return { p, bad };
}

let r = payloadKeys({ type: 'ebook', url: 'https://xn--1jqx9a.als1004.space/other/chapters/id/32157.html' });
check('ebook → form.book', r.p.form.book && !r.bad.length, JSON.stringify(r.p.form));
check('ebook → type/kind 正确', r.p.type === 'ebook' && r.p.kind === 'download');

r = payloadKeys({ type: 'ehentai', url: 'https://e-hentai.org/g/3743290/8eee725d8c/', range: '1-10,20' });
check('ehentai → form.url + range', r.p.form.url && r.p.form.range === '1-10,20' && !r.bad.length,
      JSON.stringify(r.p.form));
check('ehentai 留空 range 时不发该键',
      api.buildTaskPayload({ type: 'ehentai', url: 'https://e-hentai.org/g/1/ab/' }).form.range === undefined);
check('ehentai 画廊 URL 格式不对 → 抛错',
      /画廊 URL/.test(throws(() => api.buildTaskPayload({ type: 'ehentai', url: 'https://e-hentai.org/tag/a' })) || ''));

r = payloadKeys({ type: 'video', mode: 'batch', url: 'https://eacg.net/list/1',
                  episodes: '1-12,15', line: '', pick: '1', interval: '60' });
check('video/batch → mode+url+episodes+pick+interval',
      r.p.form.mode === 'batch' && r.p.form.episodes === '1-12,15'
      && r.p.form.pick === 1 && r.p.form.interval === 60 && !r.bad.length,
      JSON.stringify(r.p.form));
check('video/batch 集数非法 → 抛错',
      /集数范围/.test(throws(() => api.buildTaskPayload(
        { type: 'video', mode: 'batch', url: 'https://x/y', episodes: '1-' })) || ''));
check('video/batch pick 非整数 → 抛错',
      /整数/.test(throws(() => api.buildTaskPayload(
        { type: 'video', mode: 'batch', url: 'https://x/y', pick: 'abc' })) || ''));

r = payloadKeys({ type: 'video', mode: 'batch', url: 'https://www.mvffm.net/play/1/',
                  episodes: '', line: 'FLV 22 推薦31', pick: '', interval: '' });
check('video/batch 自定义线路 → form.line', r.p.form.line === 'FLV 22 推薦31' && !r.bad.length,
      JSON.stringify(r.p.form));

r = payloadKeys({ type: 'video', mode: 'get', url: 'https://cdn/x/index.m3u8',
                  referer: 'https://a/', cookie: 'k=v' });
check('video/get → referer+cookie', r.p.form.referer === 'https://a/' && r.p.form.cookie === 'k=v'
      && !r.bad.length, JSON.stringify(r.p.form));

r = payloadKeys({ type: 'video', mode: 'ytdlp', url: 'https://www.bilibili.com/video/BV1xx' });
check('video/ytdlp → 只有 mode+url', Object.keys(r.p.form).sort().join(',') === 'mode,url'
      && !r.bad.length, JSON.stringify(r.p.form));

check('空地址 → 抛错', /请填写地址/.test(throws(() => api.buildTaskPayload({ type: 'video', url: '' })) || ''));
check('非 http 地址 → 抛错',
      /http/.test(throws(() => api.buildTaskPayload({ type: 'video', url: 'ftp://x' })) || ''));
check('未知下载器 → 抛错',
      /未知下载器/.test(throws(() => api.buildTaskPayload({ type: 'music', url: 'https://x' })) || ''));

console.log('\n结果:', failed ? `失败 ${failed} 项` : '全部通过');
process.exit(failed ? 1 : 0);
