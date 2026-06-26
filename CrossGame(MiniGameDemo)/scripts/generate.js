/**
 * generate.js — 入口脚本
 *
 * 运行方式：
 *   npm run generate
 *   或
 *   node scripts/generate.js
 *
 * 功能：
 *   1. 加载原始单词表 JSON
 *   2. 调用 WordLoader 过滤合法单词
 *   3. 根据单词总量动态计算目标 PuzzleSet 数量
 *   4. 生成 PuzzleSet 并写入单个 JSON 文件
 *   5. 增加生成保护，避免无限循环
 */

import { loadWords } from './word-loader.js';
import { generatePuzzleSets } from './puzzle-generator.js';
import { writeFileSync, mkdirSync } from 'fs';
import { dirname, resolve } from 'path';

const __dirname = decodeURI(dirname(new URL(import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1'));

const WORD_LIST_PATH = resolve(__dirname, '../广州科教版小学英语三至五年级单词表.json');
const DATA_DIR = resolve(__dirname, '../data');

const WORDS_PER_PUZZLE = 5;
const COVERAGE_TARGET = 0.9;
const MAX_CONSECUTIVE_FAILURES = 50000;

const OUTPUT_FILE = '小学-填字游戏.json';

function main() {
  console.log('=== 英语填字游戏数据生成脚本 ===\n');

  try {
    console.log('1/3 加载单词表...');
    const words = loadWords(WORD_LIST_PATH);
    console.log(`   ✅ 加载到 ${words.length} 个合法单词`);

    if (words.length === 0) {
      console.error('   ❌ 单词表为空，无法生成 PuzzleSet');
      process.exit(1);
    }

    const targetCount = Math.ceil(words.length / WORDS_PER_PUZZLE * COVERAGE_TARGET);
    console.log(`   📊 单词数 ${words.length}，目标生成 ${targetCount} 组（覆盖率 ${(COVERAGE_TARGET * 100).toFixed(0)}%）`);

    mkdirSync(DATA_DIR, { recursive: true });

    console.log('\n2/3 生成 PuzzleSet...');

    const puzzleSets = generatePuzzleSets(words, 'easy', targetCount, MAX_CONSECUTIVE_FAILURES);

    if (puzzleSets.length === 0) {
      console.error('   ❌ 未能生成任何有效 PuzzleSet');
      process.exit(1);
    }

    if (puzzleSets.length < targetCount) {
      console.warn(`   ⚠️ 生成了 ${puzzleSets.length} 组（目标 ${targetCount} 组），部分单词组合可能无法形成有效交叉`);
    }

    console.log(`\n3/3 保存文件...`);

    const outputPath = resolve(DATA_DIR, OUTPUT_FILE);
    writeFileSync(outputPath, JSON.stringify(puzzleSets, null, 2), 'utf-8');

    console.log(`   ✅ 已保存 ${puzzleSets.length} 组到 ${outputPath}`);

    const avgWords = puzzleSets.reduce((sum, p) => sum + p.words.length, 0) / puzzleSets.length;
    console.log(`   📊 平均每组 ${avgWords.toFixed(1)} 个单词`);

    const allWords = new Set();
    puzzleSets.forEach(p => p.words.forEach(w => allWords.add(w.word)));
    console.log(`   📊 覆盖 ${allWords.size} 个不同单词（总池 ${words.length} 个，覆盖率 ${(allWords.size / words.length * 100).toFixed(1)}%）`);

    console.log('\n=== 数据生成完成！===');
    console.log(`\n生成的文件：`);
    console.log(`  - ${OUTPUT_FILE}`);
    console.log('\n可直接在浏览器中打开 start.html 开始游戏');

  } catch (err) {
    console.error('\n❌ 生成过程出错：');
    console.error(err.message);
    console.error(err.stack);
    process.exit(1);
  }
}

main();
