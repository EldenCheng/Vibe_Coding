/**
 * utils.js — 通用工具函数
 *
 * 本模块以 ES Module 格式编写，可在浏览器中直接 import，
 * 也可在 Node.js（Vitest）环境中通过 import 使用。
 * 不依赖 `require`，不依赖任何第三方库。
 */

// ─────────────────────────────────────────────
// 随机抽取（无放回）
// ─────────────────────────────────────────────

/**
 * 从数组 pool 中无放回地随机抽取 n 个元素（Fisher-Yates 洗牌后取前 n 个）。
 *
 * @param {Array} pool - 候选元素数组，不会被修改（内部使用浅拷贝）
 * @param {number} n   - 需要抽取的数量，必须为非负整数
 * @returns {Array}    长度为 min(n, pool.length) 的数组
 *
 * 关于 n > pool.length 的处理策略：
 *   返回全部元素的随机排列，而不是抛出错误。
 *   这样 GameController 在 pool 数量恰好不足时仍能获得最大可用集合，
 *   再由调用方决定是否因数量不足而终止流程（见需求 6.4）。
 *   如需严格校验，调用方应在调用前检查 pool.length >= n。
 */
export function sampleWithoutReplacement(pool, n) {
  const arr = [...pool]; // 浅拷贝，避免修改原数组
  const take = Math.min(n, arr.length); // 实际取出数量，不超过池大小

  // Fisher-Yates 原地洗牌（从末尾向前扫描）
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }

  return arr.slice(0, take);
}

// ─────────────────────────────────────────────
// 答案比对
// ─────────────────────────────────────────────

/**
 * 比对用户输入与正确答案，大小写不敏感。
 *
 * 处理流程：
 *   1. 对 userInput 执行 trim()，去除首尾空白（防止意外空格）
 *   2. 将两侧均转换为大写后比较
 *
 * @param {string} userInput   - 用户在输入格中填写的字符串
 * @param {string} correctWord - PuzzleSet 中存储的正确单词
 * @returns {boolean}          true 表示答案正确，false 表示错误
 */
export function checkAnswer(userInput, correctWord) {
  return userInput.trim().toUpperCase() === correctWord.toUpperCase();
}

// ─────────────────────────────────────────────
// DOM 工具函数（浏览器环境专用）
// ─────────────────────────────────────────────

/**
 * document.querySelector 的简写封装。
 *
 * @param {string} selector - CSS 选择器字符串
 * @param {Element|Document} [scope=document] - 可选的查找范围，默认为 document
 * @returns {Element|null}  匹配的第一个元素，未找到时返回 null
 */
export function qs(selector, scope = document) {
  return scope.querySelector(selector);
}

/**
 * document.querySelectorAll 的简写封装。
 *
 * @param {string} selector - CSS 选择器字符串
 * @param {Element|Document} [scope=document] - 可选的查找范围，默认为 document
 * @returns {NodeList}      匹配的所有元素组成的 NodeList（可能为空）
 */
export function qsa(selector, scope = document) {
  return scope.querySelectorAll(selector);
}
