// 验证测试框架可正常运行的占位测试
import { describe, it, expect } from 'vitest';

describe('项目环境验证', () => {
  it('Vitest 测试框架正常工作', () => {
    expect(1 + 1).toBe(2);
  });

  it('fast-check 可正常导入', async () => {
    const fc = await import('fast-check');
    expect(typeof fc.assert).toBe('function');
    expect(typeof fc.property).toBe('function');
    expect(typeof fc.string).toBe('function');
  });
});
