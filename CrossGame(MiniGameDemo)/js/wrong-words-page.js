/**
 * wrong-words-page.js — 错词回顾页逻辑
 *
 * 负责：
 *   - 从 sessionStorage 读取失败关卡的错词数据
 *   - 渲染错词列表（英文单词 + 中文意思）
 *   - 关闭按钮点击后清除数据并返回首页
 */

function init() {
  const wrongWords = loadWrongWords();
  renderWrongWords(wrongWords);
  setupEventListeners();
}

/**
 * 从 sessionStorage 读取错词数据。
 * @returns {{ word: string, meaning: string }[]}
 */
function loadWrongWords() {
  try {
    const raw = sessionStorage.getItem('wrongWords');
    if (raw) {
      return JSON.parse(raw);
    }
  } catch (err) {
    console.error('读取错词数据失败:', err);
  }
  return [];
}

/**
 * 渲染错词列表。
 * @param {{ word: string, meaning: string }[]} wrongWords
 */
function renderWrongWords(wrongWords) {
  const list = document.getElementById('wrong-words-list');

  if (wrongWords.length === 0) {
    list.innerHTML = '<li class="empty-hint">没有记录到错词</li>';
    return;
  }

  list.innerHTML = '';
  wrongWords.forEach(item => {
    const li = document.createElement('li');
    li.className = 'wrong-word-item';

    const wordSpan = document.createElement('span');
    wordSpan.className = 'word-en';
    wordSpan.textContent = item.word;

    const meaningSpan = document.createElement('span');
    meaningSpan.className = 'word-zh';
    meaningSpan.textContent = item.meaning;

    li.appendChild(wordSpan);
    li.appendChild(meaningSpan);
    list.appendChild(li);
  });
}

function setupEventListeners() {
  const closeBtn = document.getElementById('close-btn');
  closeBtn.addEventListener('click', handleClose);
}

function handleClose() {
  sessionStorage.removeItem('wrongWords');
  window.location.href = 'start.html';
}

document.addEventListener('DOMContentLoaded', init);
