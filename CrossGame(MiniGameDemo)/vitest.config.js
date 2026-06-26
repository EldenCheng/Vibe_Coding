import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // 默认环境为 node（用于 scripts/ 逻辑测试）
    environment: 'node',
    // 仅扫描 tests/ 目录下的测试文件
    include: ['tests/**/*.test.js'],
    // PuzzleBoard 等 DOM 相关测试使用 jsdom 环境
    environmentMatchGlobs: [
      ['tests/puzzle-board*.test.js', 'jsdom'],
      ['tests/start-page*.test.js',  'jsdom'],
      ['tests/game-page*.test.js',   'jsdom'],
      ['tests/result-page*.test.js', 'jsdom']
    ]
  }
});
