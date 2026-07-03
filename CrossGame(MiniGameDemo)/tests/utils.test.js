/**
 * tests/utils.test.js
 *
 * js/utils.js 的单元测试（例子测试）
 * 测试范围：sampleWithoutReplacement、checkAnswer
 */

import { describe, it, expect } from 'vitest';
import { sampleWithoutReplacement, checkAnswer } from '../js/utils.js';

// ─────────────────────────────────────────────
// sampleWithoutReplacement
// ─────────────────────────────────────────────

describe('sampleWithoutReplacement', () => {
  const pool = ['a', 'b', 'c', 'd', 'e'];

  it('返回的数组长度等于 n', () => {
    expect(sampleWithoutReplacement(pool, 3)).toHaveLength(3);
  });

  it('n === pool.length 时返回全部元素', () => {
    const result = sampleWithoutReplacement(pool, pool.length);
    expect(result).toHaveLength(pool.length);
    // 集合内容与原数组相同
    expect([...result].sort()).toEqual([...pool].sort());
  });

  it('返回的元素均来自原始 pool（无放回）', () => {
    const result = sampleWithoutReplacement(pool, 4);
    for (const item of result) {
      expect(pool).toContain(item);
    }
  });

  it('返回的元素不重复', () => {
    const result = sampleWithoutReplacement(pool, 4);
    const unique = new Set(result);
    expect(unique.size).toBe(result.length);
  });

  it('不修改原数组', () => {
    const original = [...pool];
    sampleWithoutReplacement(pool, 3);
    expect(pool).toEqual(original);
  });

  it('n 为 0 时返回空数组', () => {
    expect(sampleWithoutReplacement(pool, 0)).toEqual([]);
  });

  it('n > pool.length 时返回全部元素（不抛错）', () => {
    const result = sampleWithoutReplacement(pool, 10);
    expect(result).toHaveLength(pool.length);
    expect([...result].sort()).toEqual([...pool].sort());
  });

  it('pool 为空时返回空数组', () => {
    expect(sampleWithoutReplacement([], 3)).toEqual([]);
  });

  it('对数字数组同样有效', () => {
    const numPool = [1, 2, 3, 4, 5, 6];
    const result = sampleWithoutReplacement(numPool, 3);
    expect(result).toHaveLength(3);
    for (const item of result) {
      expect(numPool).toContain(item);
    }
  });
});

// ─────────────────────────────────────────────
// checkAnswer
// ─────────────────────────────────────────────

describe('checkAnswer', () => {
  it('完全相同字符串返回 true', () => {
    expect(checkAnswer('apple', 'apple')).toBe(true);
  });

  it('用户输入全大写仍返回 true', () => {
    expect(checkAnswer('APPLE', 'apple')).toBe(true);
  });

  it('用户输入全小写、答案全大写仍返回 true', () => {
    expect(checkAnswer('apple', 'APPLE')).toBe(true);
  });

  it('混合大小写输入仍返回 true', () => {
    expect(checkAnswer('ApPlE', 'apple')).toBe(true);
  });

  it('答案混合大小写时仍返回 true', () => {
    expect(checkAnswer('plane', 'Plane')).toBe(true);
  });

  it('用户输入两端有空白时自动 trim 后比对', () => {
    expect(checkAnswer('  apple  ', 'apple')).toBe(true);
  });

  it('错误答案返回 false', () => {
    expect(checkAnswer('orange', 'apple')).toBe(false);
  });

  it('部分匹配返回 false', () => {
    expect(checkAnswer('app', 'apple')).toBe(false);
  });

  it('空字符串与非空答案返回 false', () => {
    expect(checkAnswer('', 'apple')).toBe(false);
  });

  it('单字母比对（大小写不敏感）', () => {
    expect(checkAnswer('A', 'a')).toBe(true);
    expect(checkAnswer('b', 'B')).toBe(true);
  });
});
