/**
 * puzzle-generator.js
 * PuzzleGenerator 模块 — 生成填字游戏棋盘布局并输出 PuzzleSet JSON。
 *
 * 本文件分三个部分（对应任务 3.1 / 3.2 / 3.3）：
 *   3.1  棋盘操作工具函数（本部分）
 *   3.2  放置算法主逻辑（后续任务）
 *   3.3  主入口与文件输出（后续任务）
 *
 * 用法（Node.js ES Module）：
 *   import { createBoard, placeWord, hasConflict, fitsOnBoard, trimBoard }
 *     from './puzzle-generator.js';
 */

// ─────────────────────────────────────────────────────────────────────────────
// 常量
// ─────────────────────────────────────────────────────────────────────────────

/** 棋盘初始大小（行列均使用此值） */
export const BOARD_SIZE = 20;

// ─────────────────────────────────────────────────────────────────────────────
// 3.1 棋盘操作工具函数
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 创建一个空棋盘（二维数组），所有格子初始化为 null。
 *
 * @param {number} [rows=BOARD_SIZE] - 棋盘行数，默认 20
 * @param {number} [cols=BOARD_SIZE] - 棋盘列数，默认 20
 * @returns {Array<Array<string|null>>} 二维数组，board[row][col] 为 null 表示空格子
 */
export function createBoard(rows = BOARD_SIZE, cols = BOARD_SIZE) {
  const board = [];
  for (let r = 0; r < rows; r++) {
    board.push(new Array(cols).fill(null));
  }
  return board;
}

/**
 * 将单词放置到棋盘上（直接修改传入的棋盘）。
 *
 * 方向说明：
 *   - 'across'：横向放置，沿列方向（col 递增）写入字母
 *   - 'down'  ：纵向放置，沿行方向（row 递增）写入字母
 *
 * 注意：本函数不做边界检查和冲突检查，调用前请先使用
 * `fitsOnBoard` 和 `hasConflict` 校验。
 *
 * @param {Array<Array<string|null>>} board     - 棋盘（将被直接修改）
 * @param {string}                   word       - 要放置的单词（纯英文字母）
 * @param {number}                   row        - 起始行（0-indexed）
 * @param {number}                   col        - 起始列（0-indexed）
 * @param {'across'|'down'}          direction  - 放置方向
 * @returns {void}
 */
export function placeWord(board, word, row, col, direction) {
  for (let i = 0; i < word.length; i++) {
    if (direction === 'across') {
      board[row][col + i] = word[i];
    } else {
      board[row + i][col] = word[i];
    }
  }
}

/**
 * 检测将单词放置到指定位置时是否与棋盘已有字母发生冲突。
 *
 * 冲突定义：某格已有字母，且与当前单词对应位置的字母不同。
 * 若某格为空（null）或字母相同（共享字母格），则视为无冲突。
 *
 * @param {Array<Array<string|null>>} board     - 棋盘（只读）
 * @param {string}                   word       - 要放置的单词
 * @param {number}                   row        - 起始行（0-indexed）
 * @param {number}                   col        - 起始列（0-indexed）
 * @param {'across'|'down'}          direction  - 放置方向
 * @returns {boolean} true 表示存在冲突，false 表示无冲突
 */
export function hasConflict(board, word, row, col, direction) {
  for (let i = 0; i < word.length; i++) {
    const r = direction === 'across' ? row : row + i;
    const c = direction === 'across' ? col + i : col;
    const existing = board[r][c];
    if (existing !== null && existing !== word[i]) {
      return true;
    }
  }
  return false;
}

/**
 * 检查将单词放置到指定位置时是否完全在棋盘边界内。
 *
 * 边界规则：
 *   - 'across'：需要 col + word.length - 1 < maxCols，且 row 在 [0, maxRows) 内
 *   - 'down'  ：需要 row + word.length - 1 < maxRows，且 col 在 [0, maxCols) 内
 *
 * @param {string}          word      - 要放置的单词
 * @param {number}          row       - 起始行（0-indexed）
 * @param {number}          col       - 起始列（0-indexed）
 * @param {'across'|'down'} direction - 放置方向
 * @param {number}          maxRows   - 棋盘最大行数
 * @param {number}          maxCols   - 棋盘最大列数
 * @returns {boolean} true 表示完全在边界内，false 表示超出边界
 */
export function fitsOnBoard(word, row, col, direction, maxRows, maxCols) {
  if (direction === 'across') {
    return (
      row >= 0 &&
      row < maxRows &&
      col >= 0 &&
      col + word.length - 1 < maxCols
    );
  } else {
    // 'down'
    return (
      col >= 0 &&
      col < maxCols &&
      row >= 0 &&
      row + word.length - 1 < maxRows
    );
  }
}

/**
 * 检查两个单词是否存在无关相邻（平行且紧贴但不共享格子）。
 * 这种情况下，两个单词的格子在视觉上连在一起但实际无关，容易误导用户。
 *
 * @param {PlacedWord} w1 - 第一个单词
 * @param {PlacedWord} w2 - 第二个单词
 * @returns {boolean} true 表示存在无关相邻违规
 */
function hasParallelAdjacency(w1, w2) {
  // 只检查同方向的单词（平行单词）
  if (w1.direction !== w2.direction) return false;

  // 收集 w1 的所有格子坐标
  const w1Cells = new Set();
  for (let i = 0; i < w1.word.length; i++) {
    const r = w1.direction === 'across' ? w1.row : w1.row + i;
    const c = w1.direction === 'across' ? w1.col + i : w1.col;
    w1Cells.add(`${r},${c}`);
  }

  // 检查 w2 的每个格子是否与 w1 的格子相邻（共享边）
  for (let i = 0; i < w2.word.length; i++) {
    const r = w2.direction === 'across' ? w2.row : w2.row + i;
    const c = w2.direction === 'across' ? w2.col + i : w2.col;

    const neighbors = [[r - 1, c], [r + 1, c], [r, c - 1], [r, c + 1]];
    for (const [nr, nc] of neighbors) {
      if (w1Cells.has(`${nr},${nc}`)) {
        return true; // w2 的格子与 w1 的格子相邻 → 违规
      }
    }
  }
  return false;
}

/**
 * 检查已放置的单词列表中是否存在平行相邻违规。
 * @param {PlacedWord[]} placedWords
 * @returns {boolean} true 表示存在违规
 */
function hasAnyParallelAdjacency(placedWords) {
  for (let i = 0; i < placedWords.length; i++) {
    for (let j = i + 1; j < placedWords.length; j++) {
      if (hasParallelAdjacency(placedWords[i], placedWords[j])) {
        return true;
      }
    }
  }
  return false;
}

/**
 * @typedef {Object} PlacedWord
 * @property {string}          word      - 英文单词
 * @property {string}          meaning   - 中文释义
 * @property {number}          row       - 起始行（0-indexed，裁剪前坐标）
 * @property {number}          col       - 起始列（0-indexed，裁剪前坐标）
 * @property {'across'|'down'} direction - 放置方向
 */

/**
 * @typedef {Object} TrimResult
 * @property {number}          boardRows      - 裁剪后棋盘行数（≤ 20）
 * @property {number}          boardCols      - 裁剪后棋盘列数（≤ 20）
 * @property {PlacedWord[]}    adjustedWords  - 坐标调整后的单词数组副本
 */

/**
 * 计算所有已放置单词的最小外包矩形，并裁剪棋盘坐标。
 *
 * 步骤：
 *   1. 遍历所有已放置单词，计算占用格子的 minRow / maxRow / minCol / maxCol
 *   2. boardRows = maxRow - minRow + 1；boardCols = maxCol - minCol + 1
 *   3. 对每个单词：row -= minRow，col -= minCol
 *   4. 保证 boardRows ≤ 20，boardCols ≤ 20（超出时截断，实际算法应确保不超出）
 *
 * 本函数不修改传入的 placedWords 数组，返回新的副本。
 *
 * @param {Array<Array<string|null>>} board        - 当前棋盘（仅用于上下文，本函数不修改）
 * @param {PlacedWord[]}              placedWords  - 已放置单词列表
 * @returns {TrimResult}
 */
export function trimBoard(board, placedWords) {
  if (placedWords.length === 0) {
    return { boardRows: 0, boardCols: 0, adjustedWords: [] };
  }

  let minRow = Infinity;
  let maxRow = -Infinity;
  let minCol = Infinity;
  let maxCol = -Infinity;

  // 计算所有已放置单词实际占用格子的边界
  for (const pw of placedWords) {
    const { word, row, col, direction } = pw;
    const endRow = direction === 'down'   ? row + word.length - 1 : row;
    const endCol = direction === 'across' ? col + word.length - 1 : col;

    if (row    < minRow) minRow = row;
    if (endRow > maxRow) maxRow = endRow;
    if (col    < minCol) minCol = col;
    if (endCol > maxCol) maxCol = endCol;
  }

  let boardRows = maxRow - minRow + 1;
  let boardCols = maxCol - minCol + 1;

  // 确保不超过最大棋盘尺寸（安全截断）
  if (boardRows > BOARD_SIZE) boardRows = BOARD_SIZE;
  if (boardCols > BOARD_SIZE) boardCols = BOARD_SIZE;

  // 生成坐标调整后的单词数组副本
  const adjustedWords = placedWords.map((pw) => ({
    ...pw,
    row: pw.row - minRow,
    col: pw.col - minCol,
  }));

  return { boardRows, boardCols, adjustedWords };
}

// ─────────────────────────────────────────────────────────────────────────────
// 3.2 交叉放置算法主逻辑
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 尝试将一个单词放置到棋盘上，与已放置单词形成交叉。
 *
 * 遍历已放置单词，寻找可共享的字母位置。若找到有效位置，放置单词并返回 true；
 * 否则返回 false。
 *
 * @param {string}       word        - 要放置的单词（纯英文字母）
 * @param {PlacedWord[]} placedWords - 已放置单词列表
 * @param {Array<Array<string|null>>} board - 棋盘（将被直接修改）
 * @returns {{success: boolean, placedWord?: PlacedWord}}
 */
export function tryPlaceWord(word, placedWords, board) {
  if (placedWords.length === 0) {
    return { success: false };
  }

  for (const placedWord of placedWords) {
    const pWord = placedWord.word;
    const pRow = placedWord.row;
    const pCol = placedWord.col;
    const pDir = placedWord.direction;

    for (let i = 0; i < word.length; i++) {
      for (let j = 0; j < pWord.length; j++) {
        if (word[i] === pWord[j]) {
          const newDir = pDir === 'across' ? 'down' : 'across';

          let newRow, newCol;
          if (newDir === 'across') {
            newRow = pRow + (pDir === 'down' ? j : 0);
            newCol = pCol - i;
          } else {
            newRow = pRow - i;
            newCol = pCol + (pDir === 'across' ? j : 0);
          }

          if (fitsOnBoard(word, newRow, newCol, newDir, BOARD_SIZE, BOARD_SIZE)) {
            if (!hasConflict(board, word, newRow, newCol, newDir)) {
              placeWord(board, word, newRow, newCol, newDir);
              return {
                success: true,
                placedWord: {
                  word,
                  row: newRow,
                  col: newCol,
                  direction: newDir,
                },
              };
            }
          }
        }
      }
    }
  }

  return { success: false };
}

/**
 * @typedef {Object} WordEntry
 * @property {string} word      - 英文单词
 * @property {string} meaning   - 中文释义
 */

/**
 * @typedef {Object} PuzzleSet
 * @property {string}   id          - 唯一标识，格式 puzzle-XXXX
 * @property {WordEntry[]} words    - 单词条目数组
 * @property {number}   boardRows   - 棋盘行数
 * @property {number}   boardCols   - 棋盘列数
 */

/**
 * 难度配置：每组单词数量范围
 */
const DIFFICULTY_CONFIG = {
  easy:   { minWords: 4, maxWords: 4 },
  medium: { minWords: 4, maxWords: 4 },
  hard:   { minWords: 4, maxWords: 4 },
};

/**
 * 尝试构建一个有效的 PuzzleSet。
 *
 * 步骤：
 *   1. 随机抽取指定数量的单词
 *   2. 第一个单词横向放置在棋盘中心
 *   3. 后续单词依次尝试与已放置单词交叉
 *   4. 无法放置时尝试最多 min(10, 剩余候选数) 次替换
 *   5. 所有单词放置成功后进行连通性校验
 *   6. 校验通过则裁剪棋盘并输出
 *
 * @param {WordEntry[]} wordPool   - 单词池（含 word 和 meaning）
 * @param {'easy'|'medium'|'hard'} difficulty - 难度等级
 * @param {number} maxAttempts     - 最大尝试次数（默认 1000）
 * @returns {PuzzleSet|null} 成功返回 PuzzleSet，失败返回 null
 */
export function buildPuzzleSet(wordPool, difficulty, maxAttempts = 1000) {
  const config = DIFFICULTY_CONFIG[difficulty];
  if (!config) {
    throw new Error(`未知难度级别: ${difficulty}`);
  }

  const targetCount = Math.floor(Math.random() * (config.maxWords - config.minWords + 1)) + config.minWords;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const candidates = sampleWithoutReplacement(wordPool, targetCount);
    if (candidates.length < targetCount) continue;

    const board = createBoard();
    const placedWords = [];

    const firstWord = candidates[0];
    const firstRow = Math.floor(BOARD_SIZE / 2);
    const firstCol = Math.floor((BOARD_SIZE - firstWord.word.length) / 2);
    placeWord(board, firstWord.word, firstRow, firstCol, 'across');
    placedWords.push({
      ...firstWord,
      row: firstRow,
      col: firstCol,
      direction: 'across',
    });

    let placedCount = 1;
    const remaining = candidates.slice(1);

    for (let i = 0; i < remaining.length; i++) {
      const result = tryPlaceWord(remaining[i].word, placedWords, board);

      if (result.success) {
        placedWords.push({
          ...remaining[i],
          ...result.placedWord,
        });
        placedCount++;
      } else {
        const replaceCount = Math.min(10, wordPool.length - candidates.length);
        let replaced = false;

        for (let r = 0; r < replaceCount; r++) {
          const poolCopy = wordPool.filter(
            w => !candidates.some(c => c.word === w.word)
          );
          if (poolCopy.length === 0) break;

          const replacement = poolCopy[Math.floor(Math.random() * poolCopy.length)];
          const replaceResult = tryPlaceWord(replacement.word, placedWords, board);

          if (replaceResult.success) {
            placedWords.push({
              ...replacement,
              ...replaceResult.placedWord,
            });
            placedCount++;
            replaced = true;
            break;
          }
        }

        if (!replaced) {
          break;
        }
      }
    }

    if (placedCount === targetCount && isConnected(placedWords) && !hasAnyParallelAdjacency(placedWords)) {
      const { boardRows, boardCols, adjustedWords } = trimBoard(board, placedWords);

      const puzzleId = `puzzle-${String(Math.floor(Math.random() * 10000)).padStart(4, '0')}`;

      return {
        id: puzzleId,
        words: adjustedWords.map(w => ({
          word: w.word,
          meaning: w.meaning,
          row: w.row,
          col: w.col,
          direction: w.direction,
        })),
        boardRows,
        boardCols,
      };
    }
  }

  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// 3.3 连通性校验与 PuzzleSet 结构化输出
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 检查两个单词是否共享至少一个字母格（交叉）。
 *
 * @param {PlacedWord} w1 - 第一个单词
 * @param {PlacedWord} w2 - 第二个单词
 * @returns {boolean} true 表示存在交叉
 */
function hasIntersection(w1, w2) {
  for (let i = 0; i < w1.word.length; i++) {
    for (let j = 0; j < w2.word.length; j++) {
      const w1Row = w1.direction === 'across' ? w1.row : w1.row + i;
      const w1Col = w1.direction === 'across' ? w1.col + i : w1.col;
      const w2Row = w2.direction === 'across' ? w2.row : w2.row + j;
      const w2Col = w2.direction === 'across' ? w2.col + j : w2.col;

      if (w1Row === w2Row && w1Col === w2Col && w1.word[i] === w2.word[j]) {
        return true;
      }
    }
  }
  return false;
}

/**
 * 使用 BFS 验证已放置单词形成的图是否连通。
 *
 * @param {PlacedWord[]} placedWords - 已放置单词列表
 * @returns {boolean} true 表示图是连通的
 */
export function isConnected(placedWords) {
  if (placedWords.length <= 1) {
    return true;
  }

  const visited = new Set();
  const queue = [0];
  visited.add(0);

  while (queue.length > 0) {
    const currentIndex = queue.shift();
    const currentWord = placedWords[currentIndex];

    for (let i = 0; i < placedWords.length; i++) {
      if (!visited.has(i) && hasIntersection(currentWord, placedWords[i])) {
        visited.add(i);
        queue.push(i);
      }
    }
  }

  return visited.size === placedWords.length;
}

/**
 * 生成指定数量的 PuzzleSet。
 *
 * @param {WordEntry[]} wordPool   - 单词池
 * @param {'easy'|'medium'|'hard'} difficulty - 难度等级
 * @param {number} targetCount     - 目标生成数量
 * @param {number} [maxFailures=5000] - 连续失败上限，超过则停止生成
 * @returns {PuzzleSet[]} 生成的 PuzzleSet 数组
 */
export function generatePuzzleSets(wordPool, difficulty, targetCount, maxFailures = 5000) {
  const puzzleSets = [];
  const usedWordSets = new Set();
  let consecutiveFailures = 0;

  while (puzzleSets.length < targetCount && consecutiveFailures < maxFailures) {
    const puzzle = buildPuzzleSet(wordPool, difficulty);

    if (puzzle) {
      const wordSetKey = puzzle.words.map(w => w.word).sort().join(',');

      if (!usedWordSets.has(wordSetKey)) {
        usedWordSets.add(wordSetKey);
        puzzleSets.push(puzzle);
        consecutiveFailures = 0;
      } else {
        consecutiveFailures++;
      }
    } else {
      consecutiveFailures++;
    }
  }

  return puzzleSets;
}

/**
 * Fisher-Yates 洗牌后取前 n 个（内部使用）。
 *
 * @param {Array} pool - 候选数组
 * @param {number} n   - 需要抽取的数量
 * @returns {Array}
 */
function sampleWithoutReplacement(pool, n) {
  const arr = [...pool];
  const take = Math.min(n, arr.length);

  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }

  return arr.slice(0, take);
}
