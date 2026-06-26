/**
 * word-loader.js
 * WordLoader 模块 — 读取广州科教版单词表 JSON，扁平化提取合法词条。
 *
 * JSON 层级结构：
 *   Array<Grade>
 *     grade.terms: Array<Term>
 *       term.units: Array<Unit>
 *         unit.words: Array<{en, zh}>
 *
 * 用法（Node.js ES Module）：
 *   import { loadWords, isValidWord } from './word-loader.js';
 *   const words = loadWords('./广州科教版小学英语三至五年级单词表.json');
 */

import { readFileSync } from 'fs';
import { resolve } from 'path';

/** 合法单词正则：纯英文字母，长度 3–20 */
const VALID_WORD_RE = /^[A-Za-z]{3,20}$/;

/**
 * 判断字符串是否为合法单词。
 * @param {string} str
 * @returns {boolean}
 */
export function isValidWord(str) {
  return typeof str === 'string' && VALID_WORD_RE.test(str);
}

/**
 * 从词表 JSON 文件加载并过滤合法单词。
 *
 * 递归遍历 grade → terms → units → words，提取 en/zh 字段。
 * 过滤规则：en 必须匹配 /^[A-Za-z]{3,20}$/
 *
 * 对不完整层级（缺少 terms/units/words 字段，或字段非数组）采用防御性处理，
 * 直接跳过而非抛出错误。
 *
 * @param {string} filePath - JSON 文件路径（相对或绝对路径均可）
 * @returns {Array<{word: string, meaning: string}>}
 */
export function loadWords(filePath) {
  const absolutePath = resolve(filePath);
  const raw = readFileSync(absolutePath, 'utf-8');

  /** @type {any} */
  let data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    throw new Error(`word-loader: 无法解析 JSON 文件 "${absolutePath}"：${err.message}`);
  }

  if (!Array.isArray(data)) {
    throw new Error(`word-loader: 词表 JSON 根节点应为数组，实际为 ${typeof data}`);
  }

  /** @type {Array<{word: string, meaning: string}>} */
  const results = [];

  for (const grade of data) {
    if (!grade || typeof grade !== 'object') continue;

    const terms = grade.terms;
    if (!Array.isArray(terms)) continue;

    for (const term of terms) {
      if (!term || typeof term !== 'object') continue;

      const units = term.units;
      if (!Array.isArray(units)) continue;

      for (const unit of units) {
        if (!unit || typeof unit !== 'object') continue;

        const words = unit.words;
        if (!Array.isArray(words)) continue;

        for (const entry of words) {
          if (!entry || typeof entry !== 'object') continue;

          const en = entry.en;
          const zh = entry.zh;

          // 过滤：en 必须是合法单词，zh 必须是非空字符串
          if (isValidWord(en) && typeof zh === 'string' && zh.trim().length > 0) {
            results.push({ word: en, meaning: zh.trim() });
          }
        }
      }
    }
  }

  // 按 word 字段去重，保留首次出现的条目（防止不同年级/单元的重复词条）
  const uniqueMap = new Map();
  for (const item of results) {
    if (!uniqueMap.has(item.word)) {
      uniqueMap.set(item.word, item);
    }
  }
  return Array.from(uniqueMap.values());
}
