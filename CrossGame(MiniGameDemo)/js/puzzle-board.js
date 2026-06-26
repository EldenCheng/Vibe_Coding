/**
 * puzzle-board.js — PuzzleBoard 组件
 *
 * 负责：
 *   - 根据 PuzzleSet 数据渲染填字棋盘
 *   - 区分输入格与暗格
 *   - 绘制单词编号上标
 *   - 渲染下方提示列表
 *   - 处理单字符输入与过滤
 *   - 处理软键盘遮挡
 *   - 按单词顺序导航焦点（填完一个单词后跳到下一个单词的第一个空格）
 */

export class PuzzleBoard {
  /** @type {HTMLElement} */
  #container;

  /** @type {Object} */
  #puzzleSet;

  /** @type {string} */
  #difficulty = 'easy';

  /** @type {HTMLInputElement[][]} */
  #inputs = [];

  /** @type {number} */
  #cellSize = 36;

  /** @type {Array<Array<{row: number, col: number}>>} 每个单词的格子列表（有序） */
  #wordCellMap = [];

  /** @type {Object} 格子坐标 → 属于哪些单词 [wordIndex, ...] */
  #cellToWords = {};

  /** @type {number} 当前正在填的单词索引 */
  #currentWordIndex = 0;

  /**
   * 创建 PuzzleBoard 实例。
   * @param {HTMLElement} container - 棋盘容器元素
   */
  constructor(container) {
    this.#container = container;
  }

  /**
   * 渲染棋盘。
   * @param {Object} puzzleSet - PuzzleSet 数据
   * @param {string} difficulty - 难度级别 (easy/medium/hard)
   */
  render(puzzleSet, difficulty = 'easy') {
    this.#puzzleSet = puzzleSet;
    this.#difficulty = difficulty;
    this.#inputs = [];

    this.#container.innerHTML = '';

    const { boardRows, boardCols, words } = puzzleSet;

    this.#calculateCellSize();

    this.#container.style.gridTemplateColumns = `repeat(${boardCols}, ${this.#cellSize}px)`;
    this.#container.style.gridTemplateRows = `repeat(${boardRows}, ${this.#cellSize}px)`;

    const inputPositions = this.#buildInputPositions(words);
    const numberPositions = this.#buildNumberPositions(words);

    for (let row = 0; row < boardRows; row++) {
      this.#inputs[row] = [];

      for (let col = 0; col < boardCols; col++) {
        const cell = document.createElement('div');
        cell.className = 'cell';

        const isInputCell = inputPositions[row]?.[col] !== undefined;

        if (isInputCell) {
          cell.classList.add('input-cell');

          const input = document.createElement('input');
          input.type = 'text';
          input.maxLength = 1;
          input.className = 'cell-input';

          this.#setupInput(input, row, col);
          cell.appendChild(input);
          this.#inputs[row][col] = input;

          if (numberPositions[row]?.[col]) {
            const numberSpan = document.createElement('span');
            numberSpan.className = 'cell-number';
            numberSpan.textContent = numberPositions[row][col];
            cell.appendChild(numberSpan);
          }

        } else {
          cell.classList.add('dark-cell');
        }

        this.#container.appendChild(cell);
      }
    }

    this.#buildNavigationMap(words);
    this.#applyGridHints(words, difficulty);
    this.#renderHints(words, difficulty);
  }

  /**
   * 计算单元格尺寸（固定32px，所有puzzle一致）。
   */
  #calculateCellSize() {
    this.#cellSize = 32;
  }

  /**
   * 构建输入格位置映射。
   * @param {Array} words - 单词列表
   * @returns {Object} - { row: { col: wordIndex } }
   */
  #buildInputPositions(words) {
    const positions = {};

    words.forEach((word, wordIndex) => {
      const { row, col, direction } = word;

      for (let i = 0; i < word.word.length; i++) {
        const r = direction === 'across' ? row : row + i;
        const c = direction === 'across' ? col + i : col;

        if (!positions[r]) positions[r] = {};
        positions[r][c] = wordIndex;
      }
    });

    return positions;
  }

  /**
   * 构建编号位置映射。
   * @param {Array} words - 单词列表
   * @returns {Object} - { row: { col: numberString } }
   */
  #buildNumberPositions(words) {
    const positions = {};

    words.forEach((word, wordIndex) => {
      const { row, col } = word;

      if (!positions[row]) positions[row] = {};

      if (positions[row][col]) {
        positions[row][col] = `${positions[row][col]},${wordIndex + 1}`;
      } else {
        positions[row][col] = String(wordIndex + 1);
      }
    });

    return positions;
  }

  /**
   * 构建焦点导航所需的数据结构。
   * - #wordCellMap: 每个单词的格子列表（按单词内字母顺序）
   * - #cellToWords: 每个格子属于哪些单词
   * - #currentWordIndex: 重置为 0
   * @param {Array} words - 单词列表
   */
  #buildNavigationMap(words) {
    this.#wordCellMap = [];
    this.#cellToWords = {};
    this.#currentWordIndex = 0;

    words.forEach((wordData, wordIndex) => {
      const { row, col, direction, word } = wordData;
      const cells = [];

      for (let i = 0; i < word.length; i++) {
        const r = direction === 'across' ? row : row + i;
        const c = direction === 'across' ? col + i : col;
        cells.push({ row: r, col: c });

        const key = `${r},${c}`;
        if (!this.#cellToWords[key]) {
          this.#cellToWords[key] = [];
        }
        this.#cellToWords[key].push(wordIndex);
      }

      this.#wordCellMap.push(cells);
    });
  }

  /**
   * 获取格子在指定单词中的字符索引位置。
   * @param {number} row
   * @param {number} col
   * @param {number} wordIndex
   * @returns {number} 字符索引，不在该单词中则返回 -1
   */
  #getCharIndexInWord(row, col, wordIndex) {
    const cells = this.#wordCellMap[wordIndex];
    if (!cells) return -1;

    for (let i = 0; i < cells.length; i++) {
      if (cells[i].row === row && cells[i].col === col) {
        return i;
      }
    }
    return -1;
  }

  /**
   * 在指定单词中，找到给定位置之后的下一个空格（未填入且非提示格）。
   * @param {number} wordIndex - 单词索引
   * @param {number} afterCharIndex - 从此位置之后开始找（不含该位置）
   * @returns {{row: number, col: number}|null} 下一个空格坐标，没有则返回 null
   */
  #findNextEmptyInWord(wordIndex, afterCharIndex) {
    const cells = this.#wordCellMap[wordIndex];
    if (!cells) return null;

    for (let i = afterCharIndex + 1; i < cells.length; i++) {
      const { row, col } = cells[i];
      const input = this.#inputs[row]?.[col];
      if (input && !input.readOnly && !input.value) {
        return { row, col };
      }
    }
    return null;
  }

  /**
   * 在指定单词中找到第一个空格（未填入且非提示格）。
   * @param {number} wordIndex - 单词索引
   * @returns {{row: number, col: number}|null} 第一个空格坐标，没有则返回 null
   */
  #findFirstEmptyInWord(wordIndex) {
    return this.#findNextEmptyInWord(wordIndex, -1);
  }

  /**
   * 找下一个未完成的单词（从 afterIndex 之后开始找）。
   * @param {number} afterIndex - 从此索引之后开始找
   * @returns {number} 下一个未完成单词的索引，全部完成则返回 -1
   */
  #findNextIncompleteWord(afterIndex) {
    const totalWords = this.#wordCellMap.length;

    // 先从 afterIndex+1 到末尾找
    for (let i = afterIndex + 1; i < totalWords; i++) {
      if (this.#findFirstEmptyInWord(i)) {
        return i;
      }
    }

    // 从头开始找（循环回去）
    for (let i = 0; i <= afterIndex; i++) {
      if (this.#findFirstEmptyInWord(i)) {
        return i;
      }
    }

    return -1;
  }

  /**
   * 处理格子点击事件：根据点击位置切换当前单词。
   * 在点击格子所属的单词中，找第一个未完成的单词作为当前单词。
   * @param {number} row
   * @param {number} col
   */
  #handleCellClick(row, col) {
    const key = `${row},${col}`;
    const wordIndices = this.#cellToWords[key];
    if (!wordIndices || wordIndices.length === 0) return;

    // 如果当前单词包含该格子且未完成，保持不变
    if (wordIndices.includes(this.#currentWordIndex)) {
      if (this.#findFirstEmptyInWord(this.#currentWordIndex)) {
        return;
      }
    }

    // 在该格子所属的单词中，找第一个未完成的
    for (const wi of wordIndices) {
      if (this.#findFirstEmptyInWord(wi)) {
        this.#currentWordIndex = wi;
        return;
      }
    }
  }

  /**
   * 设置输入框事件处理。
   * @param {HTMLInputElement} input
   * @param {number} row
   * @param {number} col
   */
  #setupInput(input, row, col) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' || e.key === 'Delete') {
        input.value = '';
      } else if (!/^[a-zA-Z]$/.test(e.key)) {
        e.preventDefault();
      }
    });

    input.addEventListener('input', (e) => {
      const value = e.target.value.toUpperCase();
      e.target.value = value;

      if (value.length === 1) {
        this.#moveToNext(row, col);
      }
    });

    input.addEventListener('click', () => {
      this.#handleCellClick(row, col);
    });

    input.addEventListener('focus', () => {
      setTimeout(() => {
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 300);
    });
  }

  /**
   * 按单词顺序移动焦点到下一个输入格。
   * 1. 在当前单词中找下一个空格
   * 2. 当前单词完成则跳到下一个未完成单词的第一个空格
   * @param {number} currentRow
   * @param {number} currentCol
   */
  #moveToNext(currentRow, currentCol) {
    // 确保当前格子属于 currentWordIndex 所指的单词
    const charIndex = this.#getCharIndexInWord(currentRow, currentCol, this.#currentWordIndex);

    if (charIndex !== -1) {
      // 当前格子在当前单词中，找该单词的下一个空格
      const next = this.#findNextEmptyInWord(this.#currentWordIndex, charIndex);
      if (next) {
        this.#inputs[next.row][next.col].focus();
        return;
      }

      // 当前单词完成，找下一个未完成的单词
      const nextWord = this.#findNextIncompleteWord(this.#currentWordIndex);
      if (nextWord !== -1) {
        this.#currentWordIndex = nextWord;
        const first = this.#findFirstEmptyInWord(nextWord);
        if (first) {
          this.#inputs[first.row][first.col].focus();
        }
      }
      return;
    }

    // 当前格子不在当前单词中（可能是共享格被其他单词填充），
    // 尝试在该格子所属的单词中找下一个空格
    const key = `${currentRow},${currentCol}`;
    const wordIndices = this.#cellToWords[key] || [];

    for (const wi of wordIndices) {
      const ci = this.#getCharIndexInWord(currentRow, currentCol, wi);
      if (ci !== -1) {
        const next = this.#findNextEmptyInWord(wi, ci);
        if (next) {
          this.#currentWordIndex = wi;
          this.#inputs[next.row][next.col].focus();
          return;
        }
      }
    }

    // 兜底：找下一个未完成的单词
    const nextWord = this.#findNextIncompleteWord(this.#currentWordIndex);
    if (nextWord !== -1) {
      this.#currentWordIndex = nextWord;
      const first = this.#findFirstEmptyInWord(nextWord);
      if (first) {
        this.#inputs[first.row][first.col].focus();
      }
    }
  }

  /**
   * 渲染提示列表。
   * @param {Array} words - 单词列表
   * @param {string} difficulty - 难度级别
   */
  #renderHints(words, difficulty) {
    const hintsList = document.getElementById('hints-list');
    hintsList.innerHTML = '';

    let hints = words.map((w, i) => ({
      index: i + 1,
      direction: w.direction === 'across' ? '横向' : '纵向',
      meaning: w.meaning,
    }));

    if (difficulty === 'medium' || difficulty === 'hard') {
      hints = hints.sort(() => Math.random() - 0.5);
      hints.forEach(h => {
        const li = document.createElement('li');
        li.textContent = `${h.direction}：${h.meaning}`;
        hintsList.appendChild(li);
      });
    } else {
      hints.forEach(h => {
        const li = document.createElement('li');
        li.textContent = `${h.index}. ${h.direction}：${h.meaning}`;
        hintsList.appendChild(li);
      });
    }
  }

  /**
   * 在棋盘中预填提示字母。
   * @param {Array} words - 单词列表
   * @param {string} difficulty - 难度级别
   */
  #applyGridHints(words, difficulty) {
    if (difficulty === 'easy') return;

    words.forEach((wordData) => {
      const { word, row, col, direction } = wordData;
      const letters = word.toUpperCase().split('');

      let hintPositions = [];
      if (difficulty === 'medium') {
        hintPositions = [0];
      } else if (difficulty === 'hard') {
        const nonFirstIndices = letters.slice(1).map((_, i) => i + 1);
        const shuffled = nonFirstIndices.sort(() => Math.random() - 0.5);
        hintPositions = shuffled.slice(0, Math.min(2, shuffled.length));
      }

      hintPositions.forEach(pos => {
        let r = row, c = col;
        if (direction === 'down') r += pos;
        else c += pos;

        if (this.#inputs[r] && this.#inputs[r][c]) {
          this.#inputs[r][c].value = letters[pos];
          this.#inputs[r][c].readOnly = true;
          this.#inputs[r][c].classList.add('hint-cell');
        }
      });
    });
  }

  /**
   * 判断指定位置是否为预填提示格。
   * @param {number} row
   * @param {number} col
   * @returns {boolean}
   */
  isHintCell(row, col) {
    return this.#inputs[row]?.[col]?.readOnly === true;
  }

  /**
   * 获取当前所有输入格的值。
   * @returns {Object} - { row: { col: value } }
   */
  getValues() {
    const values = {};
    const { boardRows, boardCols } = this.#puzzleSet;

    for (let row = 0; row < boardRows; row++) {
      values[row] = {};
      for (let col = 0; col < boardCols; col++) {
        if (this.#inputs[row]?.[col]) {
          values[row][col] = this.#inputs[row][col].value || '';
        }
      }
    }

    return values;
  }

  /**
   * 清空所有输入格，并重置当前单词索引。
   */
  clearValues() {
    const { boardRows, boardCols } = this.#puzzleSet;

    for (let row = 0; row < boardRows; row++) {
      for (let col = 0; col < boardCols; col++) {
        if (this.#inputs[row]?.[col] && !this.#inputs[row][col].readOnly) {
          this.#inputs[row][col].value = '';
        }
      }
    }

    this.#currentWordIndex = 0;
  }

  /**
   * 获取 PuzzleSet 数据。
   * @returns {Object}
   */
  getPuzzleSet() {
    return this.#puzzleSet;
  }
}
