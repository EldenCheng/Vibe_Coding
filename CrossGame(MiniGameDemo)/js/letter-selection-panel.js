export class LetterSelectionPanel {
  #container;
  #puzzleBoard;
  #tiles = [];

  constructor(container, puzzleBoard) {
    this.#container = container;
    this.#puzzleBoard = puzzleBoard;
  }

  render(puzzleSet, difficulty, hintPositions) {
    this.#container.innerHTML = '';
    this.#tiles = [];

    const hintSet = new Set(hintPositions.map(p => `${p.row},${p.col}`));

    if (difficulty === 'easy') {
      const allLetters = [];
      const seenCells = new Set();
      puzzleSet.words.forEach(w => {
        const word = w.word.toUpperCase();
        for (let i = 0; i < word.length; i++) {
          const r = w.direction === 'across' ? w.row : w.row + i;
          const c = w.direction === 'across' ? w.col + i : w.col;
          const cellKey = `${r},${c}`;
          if (!hintSet.has(cellKey) && !seenCells.has(cellKey)) {
            seenCells.add(cellKey);
            allLetters.push(word[i]);
          }
        }
      });
      const shuffled = this.#shuffle(allLetters);
      shuffled.forEach(letter => {
        this.#addTile(letter, 1, false);
      });
    } else {
      const counts = {};
      const seenCells = new Set();
      puzzleSet.words.forEach(w => {
        const word = w.word.toUpperCase();
        for (let i = 0; i < word.length; i++) {
          const r = w.direction === 'across' ? w.row : w.row + i;
          const c = w.direction === 'across' ? w.col + i : w.col;
          const cellKey = `${r},${c}`;
          if (!hintSet.has(cellKey) && !seenCells.has(cellKey)) {
            seenCells.add(cellKey);
            const letter = word[i];
            counts[letter] = (counts[letter] || 0) + 1;
          }
        }
      });

      let decoys = [];
      if (difficulty === 'hard') {
        const usedLetters = new Set(Object.keys(counts));
        const decoyCount = Math.floor(Math.random() * 2) + 2;
        const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
        for (let i = 0; i < decoyCount * 10 && decoys.length < decoyCount; i++) {
          const rl = alphabet[Math.floor(Math.random() * 26)];
          if (!usedLetters.has(rl)) {
            usedLetters.add(rl);
            decoys.push(rl);
          }
        }
      }

      const tileData = [];
      for (const [letter, count] of Object.entries(counts)) {
        tileData.push({ letter, count: difficulty === 'hard' ? Infinity : count, isDecoy: false });
      }
      decoys.forEach(letter => {
        tileData.push({ letter, count: Infinity, isDecoy: true });
      });

      const shuffled = this.#shuffle(tileData);
      shuffled.forEach(({ letter, count, isDecoy }) => {
        this.#addTile(letter, count, isDecoy);
      });
    }
  }

  #addTile(letter, remaining, isDecoy) {
    const tile = document.createElement('button');
    tile.className = 'letter-tile';
    tile.textContent = letter;

    this.#tiles.push({ letter, remaining, element: tile, isDecoy });
    tile.addEventListener('click', () => {
      this.#handleTileClick(tile);
    });
    this.#container.appendChild(tile);
  }

  #handleTileClick(tile) {
    const index = Array.from(this.#container.children).indexOf(tile);
    const tileData = this.#tiles[index];
    if (!tileData || tileData.remaining <= 0 || tile.classList.contains('used')) return;

    const filled = this.#puzzleBoard.fillCurrentCell(tileData.letter);
    if (filled) {
      if (isFinite(tileData.remaining)) {
        tileData.remaining--;
        if (tileData.remaining <= 0) {
          tile.classList.add('used');
        }
      }
    }
  }

  /**
   * 恢复一个字母按钮的状态（当用户从棋盘格子上删除字母时调用）。
   * @param {string} letter 被删除的字母
   */
  restoreLetter(letter) {
    const upper = letter.toUpperCase();
    for (const tileData of this.#tiles) {
      if (tileData.letter === upper && !tileData.isDecoy) {
        if (isFinite(tileData.remaining)) {
          tileData.remaining++;
          tileData.element.classList.remove('used');
        }
        return;
      }
    }
  }

  #shuffle(arr) {
    const copy = [...arr];
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  clear() {
    this.#container.innerHTML = '';
    this.#tiles = [];
  }
}
