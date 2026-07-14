/**
 * wrong-word-modal.js — 错词展示弹窗组件
 *
 * 在游戏中每关提交后弹出，展示本关错词，
 * 用户关闭后自动进入下一关。
 */

export class WrongWordModal {
  /** @type {HTMLElement} */
  #overlay;
  /** @type {HTMLElement} */
  #listContainer;
  /** @type {HTMLElement} */
  #closeBtn;
  /** @type {function} */
  #onClose;

  constructor(container) {
    this.#overlay = container;
    this.#listContainer = container.querySelector('.modal-wrong-words-list');
    this.#closeBtn = container.querySelector('.modal-close-btn');

    this.#closeBtn.addEventListener('click', () => {
      this.#hide();
    });
  }

  /**
   * 显示错词弹窗
   * @param {Array<{word: string, meaning: string}>} wrongWords 
   * @param {number} deductedChances 本次扣减的次数
   * @param {function} onClose 关闭后的回调
   */
  show(wrongWords, deductedChances, onClose) {
    this.#onClose = onClose;

    if (!wrongWords || wrongWords.length === 0) {
      if (onClose) onClose();
      return;
    }

    this.#renderWords(wrongWords);

    const info = this.#overlay.querySelector('.modal-chances-info');
    info.textContent = `本次扣减 ${deductedChances} 次机会`;

    this.#overlay.classList.remove('hidden');
  }

  #renderWords(wrongWords) {
    this.#listContainer.innerHTML = '';
    wrongWords.forEach(item => {
      const li = document.createElement('li');
      li.className = 'modal-wrong-word-item';
      li.innerHTML = `
        <span class="word-en">${item.word}</span>
        <span class="word-zh">${item.meaning}</span>
      `;
      this.#listContainer.appendChild(li);
    });
  }

  #hide() {
    this.#overlay.classList.add('hidden');
    if (this.#onClose) {
      this.#onClose();
      this.#onClose = null;
    }
  }
}
