/**
 * game-controller.js — GameController 模块
 *
 * 负责：
 *   - 加载单个 PuzzleSet JSON 文件（包含所有难度的题目）
 *   - 从 localStorage 读取进度，跳过已使用的题目
 *   - 随机抽取 3 题作为一局游戏
 *   - 每关完成后将 puzzleId 记入 localStorage
 *   - 维护 ErrorCount
 *   - 执行答案比对（不区分大小写）
 *   - 触发胜利/失败流程
 *   - 更新进度文字和星星
 */

import { PuzzleBoard } from './puzzle-board.js';
import { DataSourceConfig } from './data-source-config.js';
import { sampleWithoutReplacement, checkAnswer, qs } from './utils.js';

const STORAGE_KEY = 'crossword-game-progress';
const LEVELS_PER_GAME = 3;

/** @type {Object} */
let gameState = {
  scope: '',
  difficulty: '',
  levels: [],
  currentLevelIndex: 0,
  errorCount: 0,
  totalLevels: 0,
  puzzleSets: [],
};

/** @type {PuzzleBoard} */
let puzzleBoard = null;

/** @type {number} */
const MAX_ERRORS = 3;

async function init() {
  puzzleBoard = new PuzzleBoard(document.getElementById('puzzle-board'));

  const params = new URLSearchParams(window.location.search);
  const scope = params.get('scope');
  const difficulty = params.get('difficulty') || 'easy';

  if (!scope) {
    showToast('参数错误，返回首页');
    setTimeout(() => goToStart(), 2000);
    return;
  }

  gameState.scope = scope;
  gameState.difficulty = difficulty;
  gameState.errorCount = 0;

  try {
    await loadPuzzleSets();
    initLevelSequence();
    loadLevel(0);
    setupEventListeners();
    updateAchievementBadge();

  } catch (err) {
    console.error('游戏初始化失败:', err);
    showToast('关卡数据加载失败，请返回重试');
    setTimeout(() => goToStart(), 2000);
  }
}

/**
 * 从 data-sources.json 获取数据路径，加载全部 PuzzleSet。
 */
async function loadPuzzleSets() {
  const config = await DataSourceConfig.load();
  const path = config.getPath(gameState.scope);

  if (!path) {
    throw new Error('所选单词库不可用');
  }

  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`加载失败: ${response.status}`);
  }

  const puzzleSets = await response.json();

  if (!Array.isArray(puzzleSets) || puzzleSets.length === 0) {
    throw new Error('关卡数据为空');
  }

  gameState.puzzleSets = puzzleSets;
}

/**
 * 从 localStorage 读取进度，随机选取 3 个未使用的 puzzleId。
 * 如果全部用完，则重新开始循环（随机选取 3 个）。
 */
function initLevelSequence() {
  const allPuzzles = gameState.puzzleSets;

  if (allPuzzles.length < LEVELS_PER_GAME) {
    throw new Error('关卡数据不足，无法开始游戏');
  }

  const progress = loadProgress(gameState.scope);
  const usedIds = progress ? progress.usedIds : [];

  // 找出未使用的题目
  const unusedPuzzles = allPuzzles.filter(p => !usedIds.includes(p.id));

  let selectedPuzzles;
  if (unusedPuzzles.length >= LEVELS_PER_GAME) {
    // 从未使用的题目中随机抽取
    selectedPuzzles = sampleWithoutReplacement(unusedPuzzles, LEVELS_PER_GAME);
  } else {
    // 全部用完，重新循环：从未使用的题目 + 随机补充
    const remaining = sampleWithoutReplacement(unusedPuzzles, unusedPuzzles.length);
    const extraCount = LEVELS_PER_GAME - unusedPuzzles.length;
    const extra = sampleWithoutReplacement(allPuzzles, extraCount);
    selectedPuzzles = [...remaining, ...extra];
  }

  gameState.levels = selectedPuzzles.map(p => p.id);
  gameState.currentLevelIndex = 0;
  gameState.totalLevels = selectedPuzzles.length;

  saveGameState();
}

/**
 * 加载指定索引的关卡并渲染棋盘。
 */
function loadLevel(index) {
  if (index < 0 || index >= gameState.levels.length) {
    return;
  }

  gameState.currentLevelIndex = index;
  saveGameState();

  const puzzleId = gameState.levels[index];
  const puzzleSet = gameState.puzzleSets.find(p => p.id === puzzleId);

  if (!puzzleSet) {
    showToast('关卡数据丢失');
    goToStart();
    return;
  }

  puzzleBoard.render(puzzleSet, gameState.difficulty);
  updateProgressText();
  updateErrorCountText();
}

function updateProgressText() {
  const progressText = document.getElementById('progress-text');
  const current = gameState.currentLevelIndex + 1;
  const total = gameState.totalLevels;
  progressText.textContent = `第 ${current} 关 / 共 ${total} 关`;
}

function updateErrorCountText() {
  const errorCountEl = document.getElementById('error-count');
  const remaining = MAX_ERRORS - gameState.errorCount;
  errorCountEl.textContent = `剩余机会：${remaining}`;
}

/**
 * 在游戏页 header 显示当前单词库的星星。
 */
function updateAchievementBadge() {
  const badge = document.getElementById('achievement-badge');
  if (!badge) return;

  const progress = loadProgress(gameState.scope);
  if (!progress || progress.total === 0) {
    badge.innerHTML = '';
    return;
  }

  const used = progress.usedIds.length;
  const total = progress.total;
  const percent = total > 0 ? used / total : 0;

  if (percent >= 1) {
    badge.textContent = '⭐⭐⭐';
  } else if (percent >= 0.6) {
    badge.textContent = '⭐⭐';
  } else if (percent >= 0.3) {
    badge.textContent = '⭐';
  } else {
    badge.textContent = '';
  }
}

function setupEventListeners() {
  const cancelBtn = document.getElementById('cancel-btn');
  const submitBtn = document.getElementById('submit-btn');
  const backBtn = document.getElementById('back-btn');

  cancelBtn.addEventListener('click', handleCancel);
  submitBtn.addEventListener('click', handleSubmit);
  backBtn.addEventListener('click', goToStart);
}

function handleCancel() {
  puzzleBoard.clearValues();
}

function handleSubmit() {
  const values = puzzleBoard.getValues();
  const puzzleSet = puzzleBoard.getPuzzleSet();

  if (hasEmptyCells(values)) {
    showToast('还有空格未填写，请填完再提交！');
    return;
  }

  const allCorrect = checkAllAnswers(values, puzzleSet);

  if (allCorrect) {
    handleCorrectAnswer();
  } else {
    handleIncorrectAnswer();
  }
}

function hasEmptyCells(values) {
  for (const row in values) {
    for (const col in values[row]) {
      if (!values[row][col] && !puzzleBoard.isHintCell(Number(row), Number(col))) {
        return true;
      }
    }
  }
  return false;
}

function checkAllAnswers(values, puzzleSet) {
  for (const word of puzzleSet.words) {
    const { word: correctWord, row, col, direction } = word;

    for (let i = 0; i < correctWord.length; i++) {
      const r = direction === 'across' ? row : row + i;
      const c = direction === 'across' ? col + i : col;

      if (puzzleBoard.isHintCell(r, c)) continue;

      const userValue = (values[r]?.[c] || '').toUpperCase();
      if (userValue !== correctWord[i].toUpperCase()) {
        return false;
      }
    }
  }

  return true;
}

/**
 * 答对时：将当前 puzzleId 记入 localStorage，然后进入下一关或胜利。
 */
function handleCorrectAnswer() {
  // 将当前 puzzleId 记入进度
  saveProgress(gameState.scope, gameState.levels[gameState.currentLevelIndex]);

  if (gameState.currentLevelIndex >= gameState.totalLevels - 1) {
    triggerWin();
  } else {
    showToast('回答正确！');
    setTimeout(() => {
      loadLevel(gameState.currentLevelIndex + 1);
      updateAchievementBadge();
    }, 1000);
  }
}

/**
 * 收集当前关卡中用户填错的单词。
 * 遍历每个单词的每个字母，跳过预填提示格，对比用户输入值和正确答案。
 * 只要某个单词有任意一个字母填错，就把该单词（含中文意思）收集进来。
 *
 * @param {Object} values - 当前棋盘所有格子的值 { row: { col: value } }
 * @param {Object} puzzleSet - 当前关卡的 PuzzleSet 数据
 * @returns {{ word: string, meaning: string }[]} 错误单词列表（已去重）
 */
function collectWrongWords(values, puzzleSet) {
  const wrongWords = [];
  const seen = new Set();

  for (const wordData of puzzleSet.words) {
    const { word: correctWord, meaning, row, col, direction } = wordData;
    let isWrong = false;

    for (let i = 0; i < correctWord.length; i++) {
      const r = direction === 'across' ? row : row + i;
      const c = direction === 'across' ? col + i : col;

      if (puzzleBoard.isHintCell(r, c)) continue;

      const userValue = (values[r]?.[c] || '').toUpperCase();
      if (userValue !== correctWord[i].toUpperCase()) {
        isWrong = true;
        break;
      }
    }

    if (isWrong && !seen.has(correctWord)) {
      seen.add(correctWord);
      wrongWords.push({ word: correctWord, meaning });
    }
  }

  return wrongWords;
}

function handleIncorrectAnswer() {
  if (gameState.errorCount >= MAX_ERRORS - 1) {
    // 最后一次机会用尽，收集当前关的错词
    const values = puzzleBoard.getValues();
    const puzzleSet = puzzleBoard.getPuzzleSet();
    gameState.wrongWords = collectWrongWords(values, puzzleSet);

    gameState.errorCount = MAX_ERRORS;
    updateErrorCountText();
    triggerFail();
  } else {
    gameState.errorCount++;
    updateErrorCountText();
    const remaining = MAX_ERRORS - gameState.errorCount;
    showToast(`答案有误，请再检查一下！（剩余机会：${remaining} 次）`);
  }
}

function triggerWin() {
  sessionStorage.setItem('gameResult', JSON.stringify({
    result: 'win',
    errorCount: gameState.errorCount,
  }));
  sessionStorage.removeItem('gameState');
  window.location.href = 'result.html';
}

function triggerFail() {
  sessionStorage.setItem('gameResult', JSON.stringify({
    result: 'fail',
    errorCount: gameState.errorCount,
  }));

  // 将错词数据写入 sessionStorage，供错词页读取
  if (gameState.wrongWords && gameState.wrongWords.length > 0) {
    sessionStorage.setItem('wrongWords', JSON.stringify(gameState.wrongWords));
  }

  sessionStorage.removeItem('gameState');
  window.location.href = 'result.html';
}

function saveGameState() {
  sessionStorage.setItem('gameState', JSON.stringify(gameState));
}

/**
 * 从 localStorage 读取指定单词库的进度。
 * @param {string} scope
 * @returns {{ usedIds: number[], total: number }|null}
 */
function loadProgress(scope) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const all = JSON.parse(raw);
    return all[scope] || null;
  } catch (e) {
    return null;
  }
}

/**
 * 将完成的 puzzleId 记入 localStorage 进度。
 * 如果该 scope 尚无记录，则创建新记录。
 * @param {string} scope
 * @param {number} puzzleId
 */
function saveProgress(scope, puzzleId) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    let all = raw ? JSON.parse(raw) : {};

    if (!all[scope]) {
      all[scope] = { usedIds: [], total: gameState.puzzleSets.length };
    }

    if (!all[scope].usedIds.includes(puzzleId)) {
      all[scope].usedIds.push(puzzleId);
    }

    // 更新 total（以防数据文件更新）
    all[scope].total = gameState.puzzleSets.length;

    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch (e) {
    console.warn('保存进度失败:', e);
  }
}

function goToStart() {
  sessionStorage.removeItem('gameState');
  window.location.href = 'start.html';
}

function showToast(message) {
  const toast = document.getElementById('message-toast');
  toast.textContent = message;
  toast.classList.add('show');

  setTimeout(() => {
    toast.classList.remove('show');
  }, 2000);
}

document.addEventListener('DOMContentLoaded', init);
