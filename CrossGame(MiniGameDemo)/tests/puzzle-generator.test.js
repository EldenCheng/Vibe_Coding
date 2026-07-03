/**
 * tests/puzzle-generator.test.js
 *
 * scripts/puzzle-generator.js 棋盘工具函数的单元测试
 * 覆盖范围：createBoard、placeWord、hasConflict、fitsOnBoard、trimBoard
 */

import { describe, it, expect } from 'vitest';
import {
  createBoard,
  placeWord,
  hasConflict,
  fitsOnBoard,
  trimBoard,
  tryPlaceWord,
  isConnected,
  buildPuzzleSet,
  generatePuzzleSets,
  BOARD_SIZE,
} from '../scripts/puzzle-generator.js';

// ─────────────────────────────────────────────
// createBoard
// ─────────────────────────────────────────────

describe('createBoard', () => {
  it('默认创建 20×20 的棋盘', () => {
    const board = createBoard();
    expect(board).toHaveLength(BOARD_SIZE);
    for (const row of board) {
      expect(row).toHaveLength(BOARD_SIZE);
    }
  });

  it('所有格子初始化为 null', () => {
    const board = createBoard();
    for (const row of board) {
      for (const cell of row) {
        expect(cell).toBeNull();
      }
    }
  });

  it('可指定自定义尺寸 5×8', () => {
    const board = createBoard(5, 8);
    expect(board).toHaveLength(5);
    for (const row of board) {
      expect(row).toHaveLength(8);
    }
  });

  it('1×1 最小棋盘', () => {
    const board = createBoard(1, 1);
    expect(board).toHaveLength(1);
    expect(board[0]).toHaveLength(1);
    expect(board[0][0]).toBeNull();
  });

  it('各行互相独立（修改一行不影响其他行）', () => {
    const board = createBoard(3, 3);
    board[0][0] = 'A';
    expect(board[1][0]).toBeNull();
    expect(board[2][0]).toBeNull();
  });
});

// ─────────────────────────────────────────────
// placeWord
// ─────────────────────────────────────────────

describe('placeWord', () => {
  it('横向 (across) 放置单词', () => {
    const board = createBoard(5, 10);
    placeWord(board, 'apple', 2, 3, 'across');
    expect(board[2][3]).toBe('a');
    expect(board[2][4]).toBe('p');
    expect(board[2][5]).toBe('p');
    expect(board[2][6]).toBe('l');
    expect(board[2][7]).toBe('e');
  });

  it('纵向 (down) 放置单词', () => {
    const board = createBoard(10, 5);
    placeWord(board, 'plane', 1, 2, 'down');
    expect(board[1][2]).toBe('p');
    expect(board[2][2]).toBe('l');
    expect(board[3][2]).toBe('a');
    expect(board[4][2]).toBe('n');
    expect(board[5][2]).toBe('e');
  });

  it('放置后不影响其他格子', () => {
    const board = createBoard(5, 10);
    placeWord(board, 'cat', 0, 0, 'across');
    // 行 0 后续格子应仍为 null
    expect(board[0][3]).toBeNull();
    // 其他行不受影响
    expect(board[1][0]).toBeNull();
  });

  it('单字母单词放置', () => {
    const board = createBoard(3, 3);
    placeWord(board, 'a', 1, 1, 'across');
    expect(board[1][1]).toBe('a');
  });

  it('两个单词共享交叉字母格', () => {
    // 横向 "apple" 从 (3,2)，纵向 "plane" 从 (1,4)
    // 'apple'[2] = 'p', row=3, col=4 → board[3][4] = 'p'
    // 'plane'[2] = 'a', row=3, col=4 → board[3][4] = 'a'  (覆盖)
    // 实际交叉：'apple'[0]='a' at (3,2)，'plan_'...
    // 用 'car' across (2,0) 和 'arc' down (0,2)：交叉 board[2][2]='r'
    const board = createBoard(6, 6);
    placeWord(board, 'car', 2, 0, 'across'); // board[2][0]='c', [2][1]='a', [2][2]='r'
    placeWord(board, 'arc', 0, 2, 'down');   // board[0][2]='a', [1][2]='r', [2][2]='c' → 覆盖
    // 交叉格由后写入的 'c' 覆盖
    expect(board[2][2]).toBe('c'); // 'arc'[2] = 'c'
  });
});

// ─────────────────────────────────────────────
// hasConflict
// ─────────────────────────────────────────────

describe('hasConflict', () => {
  it('空棋盘无冲突', () => {
    const board = createBoard();
    expect(hasConflict(board, 'apple', 5, 3, 'across')).toBe(false);
  });

  it('相同字母共享格子 → 无冲突', () => {
    // 'apple' across (5,3)：a(5,3) p(5,4) p(5,5) l(5,6) e(5,7)
    // 纵向 'spa' down (3,5)：s(3,5) p(4,5) a(5,5)
    // 交叉格 (5,5)：apple[2]='p'，spa[2]='a' → 不同 → 冲突，不能用
    //
    // 改用：'apple' across (5,3)，纵向 'lip' down (4,5)
    // lip: l(4,5) i(5,5) p(6,5)
    // board[5][5]='p'（apple[2]），lip[1]='i' ≠ 'p' → 冲突，也不行
    //
    // 最清晰的例子：横向 'pen' (3,0)，纵向 'pin' (3,0)
    // 交叉格 (3,0)：pen[0]='p'，pin[0]='p' → 相同 → 无冲突
    const board = createBoard();
    placeWord(board, 'pen', 3, 0, 'across'); // board[3][0]='p', [3][1]='e', [3][2]='n'
    // 纵向 'pin' 从 (3,0)：p(3,0) i(4,0) n(5,0)
    // board[3][0]='p'，pin[0]='p' → 相同 → 无冲突
    expect(hasConflict(board, 'pin', 3, 0, 'down')).toBe(false);
  });

  it('不同字母占用同一格 → 有冲突', () => {
    const board = createBoard();
    placeWord(board, 'apple', 5, 3, 'across'); // board[5][3]='a'
    // 纵向 'big' 从 (5,3)：'b' at (5,3) vs board[5][3]='a' → 冲突
    expect(hasConflict(board, 'big', 5, 3, 'down')).toBe(true);
  });

  it('非交叉区域无冲突', () => {
    const board = createBoard();
    placeWord(board, 'apple', 0, 0, 'across');
    // 完全不同位置的单词
    expect(hasConflict(board, 'dog', 5, 5, 'down')).toBe(false);
  });

  it('冲突检测在单词中间位置也有效', () => {
    const board = createBoard();
    placeWord(board, 'hello', 5, 0, 'across');
    // board[5][2] = 'l'
    // 纵向 'fly' 从 (5,2)：'f' at (5,2) vs 'l' → 冲突
    expect(hasConflict(board, 'fly', 5, 2, 'down')).toBe(true);
  });

  it('交叉格字母相同（大小写敏感，按原始字符比较）', () => {
    const board = createBoard();
    // 放置小写字母
    placeWord(board, 'pen', 3, 3, 'across'); // board[3][3]='p'
    // 纵向单词首字母是大写 'P' vs 小写 'p' → 视为不同 → 冲突
    expect(hasConflict(board, 'Pan', 3, 3, 'down')).toBe(true);
    // 同为小写 → 无冲突
    expect(hasConflict(board, 'pin', 3, 3, 'down')).toBe(false);
  });
});

// ─────────────────────────────────────────────
// fitsOnBoard
// ─────────────────────────────────────────────

describe('fitsOnBoard', () => {
  const ROWS = 10;
  const COLS = 10;

  // —— 横向 (across) ——

  it('across：单词完全在边界内 → true', () => {
    // 'apple'(5) 从 (3, 2)：结束在 col 6，< 10 ✓
    expect(fitsOnBoard('apple', 3, 2, 'across', ROWS, COLS)).toBe(true);
  });

  it('across：单词末尾恰好到达最后一列 → true', () => {
    // 'apple'(5) 从 (0, 5)：结束在 col 9 = 10-1 ✓
    expect(fitsOnBoard('apple', 0, 5, 'across', ROWS, COLS)).toBe(true);
  });

  it('across：单词超出右边界 → false', () => {
    // 'apple'(5) 从 (0, 6)：结束在 col 10 = COLS → 越界
    expect(fitsOnBoard('apple', 0, 6, 'across', ROWS, COLS)).toBe(false);
  });

  it('across：起始列为负数 → false', () => {
    expect(fitsOnBoard('cat', 0, -1, 'across', ROWS, COLS)).toBe(false);
  });

  it('across：行超出范围 → false', () => {
    expect(fitsOnBoard('cat', 10, 0, 'across', ROWS, COLS)).toBe(false);
  });

  it('across：行为负数 → false', () => {
    expect(fitsOnBoard('cat', -1, 0, 'across', ROWS, COLS)).toBe(false);
  });

  it('across：单字母单词从最后一行最后一列 → true', () => {
    expect(fitsOnBoard('a', 9, 9, 'across', ROWS, COLS)).toBe(true);
  });

  // —— 纵向 (down) ——

  it('down：单词完全在边界内 → true', () => {
    // 'plane'(5) 从 (2, 3)：结束在 row 6，< 10 ✓
    expect(fitsOnBoard('plane', 2, 3, 'down', ROWS, COLS)).toBe(true);
  });

  it('down：单词末尾恰好到达最后一行 → true', () => {
    // 'plane'(5) 从 (5, 0)：结束在 row 9 = 10-1 ✓
    expect(fitsOnBoard('plane', 5, 0, 'down', ROWS, COLS)).toBe(true);
  });

  it('down：单词超出下边界 → false', () => {
    // 'plane'(5) 从 (6, 0)：结束在 row 10 = ROWS → 越界
    expect(fitsOnBoard('plane', 6, 0, 'down', ROWS, COLS)).toBe(false);
  });

  it('down：起始行为负数 → false', () => {
    expect(fitsOnBoard('cat', -1, 0, 'down', ROWS, COLS)).toBe(false);
  });

  it('down：列超出范围 → false', () => {
    expect(fitsOnBoard('cat', 0, 10, 'down', ROWS, COLS)).toBe(false);
  });

  it('down：列为负数 → false', () => {
    expect(fitsOnBoard('cat', 0, -1, 'down', ROWS, COLS)).toBe(false);
  });

  it('down：单字母单词从最后一行最后一列 → true', () => {
    expect(fitsOnBoard('a', 9, 9, 'down', ROWS, COLS)).toBe(true);
  });

  it('棋盘为 1×1，单字母单词 (0,0) across → true', () => {
    expect(fitsOnBoard('a', 0, 0, 'across', 1, 1)).toBe(true);
  });

  it('棋盘为 1×1，两字母单词 (0,0) across → false', () => {
    expect(fitsOnBoard('ab', 0, 0, 'across', 1, 1)).toBe(false);
  });
});

// ─────────────────────────────────────────────
// trimBoard
// ─────────────────────────────────────────────

describe('trimBoard', () => {
  it('空单词列表返回 boardRows=0, boardCols=0', () => {
    const board = createBoard();
    const result = trimBoard(board, []);
    expect(result.boardRows).toBe(0);
    expect(result.boardCols).toBe(0);
    expect(result.adjustedWords).toEqual([]);
  });

  it('单个横向单词的棋盘尺寸正确', () => {
    const board = createBoard();
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 5, col: 3, direction: 'across' },
    ];
    placeWord(board, 'apple', 5, 3, 'across');
    const { boardRows, boardCols, adjustedWords } = trimBoard(board, placedWords);

    // 仅一个单词 'apple'(5)：minRow=5,maxRow=5,minCol=3,maxCol=7
    expect(boardRows).toBe(1);       // 5-5+1
    expect(boardCols).toBe(5);       // 7-3+1
    expect(adjustedWords[0].row).toBe(0);  // 5-5
    expect(adjustedWords[0].col).toBe(0);  // 3-3
  });

  it('单个纵向单词的棋盘尺寸正确', () => {
    const board = createBoard();
    const placedWords = [
      { word: 'plane', meaning: '飞机', row: 2, col: 7, direction: 'down' },
    ];
    placeWord(board, 'plane', 2, 7, 'down');
    const { boardRows, boardCols, adjustedWords } = trimBoard(board, placedWords);

    // 'plane'(5)：minRow=2,maxRow=6,minCol=7,maxCol=7
    expect(boardRows).toBe(5);   // 6-2+1
    expect(boardCols).toBe(1);   // 7-7+1
    expect(adjustedWords[0].row).toBe(0);  // 2-2
    expect(adjustedWords[0].col).toBe(0);  // 7-7
  });

  it('两个交叉单词的棋盘尺寸正确', () => {
    // 'apple' across (5,3)：占 row5, col 3-7
    // 'plane' down (3,5)  ：占 row 3-7, col5
    // minRow=3, maxRow=7, minCol=3, maxCol=7
    const board = createBoard();
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 5, col: 3, direction: 'across' },
      { word: 'plane', meaning: '飞机', row: 3, col: 5, direction: 'down'   },
    ];
    const { boardRows, boardCols, adjustedWords } = trimBoard(board, placedWords);

    expect(boardRows).toBe(5);  // 7-3+1
    expect(boardCols).toBe(5);  // 7-3+1

    // apple: row 5-3=2, col 3-3=0
    const apple = adjustedWords.find(w => w.word === 'apple');
    expect(apple.row).toBe(2);
    expect(apple.col).toBe(0);

    // plane: row 3-3=0, col 5-3=2
    const plane = adjustedWords.find(w => w.word === 'plane');
    expect(plane.row).toBe(0);
    expect(plane.col).toBe(2);
  });

  it('原始 placedWords 数组不被修改', () => {
    const board = createBoard();
    const placedWords = [
      { word: 'cat', meaning: '猫', row: 8, col: 10, direction: 'across' },
    ];
    const originalRow = placedWords[0].row;
    const originalCol = placedWords[0].col;
    trimBoard(board, placedWords);
    // 原数组坐标保持不变
    expect(placedWords[0].row).toBe(originalRow);
    expect(placedWords[0].col).toBe(originalCol);
  });

  it('坐标从 (0,0) 开始的单词，调整后坐标仍为 (0,0)', () => {
    const board = createBoard();
    const placedWords = [
      { word: 'dog', meaning: '狗', row: 0, col: 0, direction: 'across' },
    ];
    const { adjustedWords } = trimBoard(board, placedWords);
    expect(adjustedWords[0].row).toBe(0);
    expect(adjustedWords[0].col).toBe(0);
  });

  it('adjustedWords 包含 word 和 meaning 等原始字段', () => {
    const board = createBoard();
    const placedWords = [
      { word: 'sun', meaning: '太阳', row: 3, col: 4, direction: 'across' },
    ];
    const { adjustedWords } = trimBoard(board, placedWords);
    expect(adjustedWords[0].word).toBe('sun');
    expect(adjustedWords[0].meaning).toBe('太阳');
    expect(adjustedWords[0].direction).toBe('across');
  });
});

// ─────────────────────────────────────────────
// tryPlaceWord
// ─────────────────────────────────────────────

describe('tryPlaceWord', () => {
  it('已放置单词为空时返回失败', () => {
    const board = createBoard();
    const result = tryPlaceWord('apple', [], board);
    expect(result.success).toBe(false);
  });

  it('能找到共享字母并成功放置（横向→纵向）', () => {
    const board = createBoard();
    placeWord(board, 'apple', 10, 8, 'across');
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 10, col: 8, direction: 'across' },
    ];

    const result = tryPlaceWord('plane', placedWords, board);
    expect(result.success).toBe(true);
    expect(result.placedWord).toBeDefined();
    expect(result.placedWord?.word).toBe('plane');
    expect(result.placedWord?.direction).toBe('down');
  });

  it('能找到共享字母并成功放置（纵向→横向）', () => {
    const board = createBoard();
    placeWord(board, 'plane', 8, 10, 'down');
    const placedWords = [
      { word: 'plane', meaning: '飞机', row: 8, col: 10, direction: 'down' },
    ];

    const result = tryPlaceWord('apple', placedWords, board);
    expect(result.success).toBe(true);
    expect(result.placedWord?.direction).toBe('across');
  });

  it('无共享字母时返回失败', () => {
    const board = createBoard();
    placeWord(board, 'apple', 10, 10, 'across');
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 10, col: 10, direction: 'across' },
    ];

    const result = tryPlaceWord('xyz', placedWords, board);
    expect(result.success).toBe(false);
  });
});

// ─────────────────────────────────────────────
// isConnected
// ─────────────────────────────────────────────

describe('isConnected', () => {
  it('空数组返回 true', () => {
    expect(isConnected([])).toBe(true);
  });

  it('单个单词返回 true', () => {
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 10, col: 10, direction: 'across' },
    ];
    expect(isConnected(placedWords)).toBe(true);
  });

  it('两个交叉单词返回 true', () => {
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 10, col: 8, direction: 'across' },
      { word: 'paper', meaning: '纸', row: 8, col: 9, direction: 'down' },
    ];
    expect(isConnected(placedWords)).toBe(true);
  });

  it('三个单词链式交叉返回 true', () => {
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 10, col: 8, direction: 'across' },
      { word: 'paper', meaning: '纸', row: 8, col: 9, direction: 'down' },
      { word: 'pen', meaning: '钢笔', row: 11, col: 8, direction: 'across' },
    ];
    expect(isConnected(placedWords)).toBe(true);
  });

  it('两个不交叉单词返回 false', () => {
    const placedWords = [
      { word: 'apple', meaning: '苹果', row: 2, col: 2, direction: 'across' },
      { word: 'xyz', meaning: 'XYZ', row: 15, col: 15, direction: 'down' },
    ];
    expect(isConnected(placedWords)).toBe(false);
  });
});

// ─────────────────────────────────────────────
// buildPuzzleSet
// ─────────────────────────────────────────────

describe('buildPuzzleSet', () => {
  const wordPool = [
    { word: 'apple', meaning: '苹果' },
    { word: 'plane', meaning: '飞机' },
    { word: 'pear', meaning: '梨' },
    { word: 'pen', meaning: '钢笔' },
    { word: 'pencil', meaning: '铅笔' },
    { word: 'book', meaning: '书' },
    { word: 'ball', meaning: '球' },
    { word: 'banana', meaning: '香蕉' },
    { word: 'cat', meaning: '猫' },
    { word: 'car', meaning: '汽车' },
    { word: 'cake', meaning: '蛋糕' },
    { word: 'dog', meaning: '狗' },
    { word: 'door', meaning: '门' },
    { word: 'desk', meaning: '书桌' },
    { word: 'egg', meaning: '鸡蛋' },
    { word: 'elephant', meaning: '大象' },
    { word: 'fish', meaning: '鱼' },
    { word: 'flower', meaning: '花' },
    { word: 'fruit', meaning: '水果' },
    { word: 'girl', meaning: '女孩' },
  ];

  it('初级难度生成包含 3 个单词的 PuzzleSet', () => {
    const puzzle = buildPuzzleSet(wordPool, 'easy');
    expect(puzzle).not.toBeNull();
    expect(puzzle?.words).toHaveLength(3);
    expect(puzzle?.id).toMatch(/^puzzle-\d{4}$/);
    expect(puzzle?.boardRows).toBeGreaterThan(0);
    expect(puzzle?.boardCols).toBeGreaterThan(0);
  });

  it('中级难度生成包含 4-6 个单词的 PuzzleSet', () => {
    const puzzle = buildPuzzleSet(wordPool, 'medium');
    expect(puzzle).not.toBeNull();
    expect(puzzle?.words.length).toBeGreaterThanOrEqual(4);
    expect(puzzle?.words.length).toBeLessThanOrEqual(6);
  });

  it('高级难度生成包含 7-10 个单词的 PuzzleSet', () => {
    const puzzle = buildPuzzleSet(wordPool, 'hard');
    expect(puzzle).not.toBeNull();
    expect(puzzle?.words.length).toBeGreaterThanOrEqual(7);
    expect(puzzle?.words.length).toBeLessThanOrEqual(10);
  });

  it('生成的 PuzzleSet 包含完整字段', () => {
    const puzzle = buildPuzzleSet(wordPool, 'easy');
    expect(puzzle).not.toBeNull();
    expect(puzzle?.id).toBeDefined();
    expect(puzzle?.words).toBeDefined();
    expect(puzzle?.boardRows).toBeDefined();
    expect(puzzle?.boardCols).toBeDefined();

    for (const word of puzzle?.words || []) {
      expect(word.word).toBeDefined();
      expect(word.meaning).toBeDefined();
      expect(word.row).toBeDefined();
      expect(word.col).toBeDefined();
      expect(word.direction).toBeDefined();
      expect(['across', 'down']).toContain(word.direction);
    }
  });

  it('未知难度抛出错误', () => {
    expect(() => {
      // @ts-expect-error
      buildPuzzleSet(wordPool, 'unknown');
    }).toThrow('未知难度级别');
  });
});

// ─────────────────────────────────────────────
// generatePuzzleSets
// ─────────────────────────────────────────────

describe('generatePuzzleSets', () => {
  const wordPool = [
    { word: 'apple', meaning: '苹果' },
    { word: 'plane', meaning: '飞机' },
    { word: 'pear', meaning: '梨' },
    { word: 'pen', meaning: '钢笔' },
    { word: 'pencil', meaning: '铅笔' },
    { word: 'book', meaning: '书' },
    { word: 'ball', meaning: '球' },
    { word: 'banana', meaning: '香蕉' },
    { word: 'cat', meaning: '猫' },
    { word: 'car', meaning: '汽车' },
    { word: 'cake', meaning: '蛋糕' },
    { word: 'dog', meaning: '狗' },
    { word: 'door', meaning: '门' },
    { word: 'desk', meaning: '书桌' },
    { word: 'egg', meaning: '鸡蛋' },
    { word: 'elephant', meaning: '大象' },
    { word: 'fish', meaning: '鱼' },
    { word: 'flower', meaning: '花' },
    { word: 'fruit', meaning: '水果' },
    { word: 'girl', meaning: '女孩' },
  ];

  it('生成指定数量的 PuzzleSet', () => {
    const puzzles = generatePuzzleSets(wordPool, 'easy', 5);
    expect(puzzles).toHaveLength(5);
  });

  it('生成的 PuzzleSet 单词集合不重复', () => {
    const puzzles = generatePuzzleSets(wordPool, 'easy', 3);
    const wordSetKeys = new Set();

    for (const puzzle of puzzles) {
      const key = puzzle.words.map(w => w.word).sort().join(',');
      expect(wordSetKeys.has(key)).toBe(false);
      wordSetKeys.add(key);
    }
  });
});
