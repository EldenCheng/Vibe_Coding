class UI {
    constructor() {
        this.cells = document.querySelectorAll('.cell');
        this.statusEl = document.getElementById('status');
        this.boardEl = document.getElementById('board');
        this.scoreXEl = document.getElementById('score-x');
        this.scoreOEl = document.getElementById('score-o');
        this.scoreDrawEl = document.getElementById('score-draw');
        this.historyListEl = document.getElementById('history-list');
        this.btnPvp = document.getElementById('btn-pvp');
        this.btnPve = document.getElementById('btn-pve');
        this.btnEasy = document.getElementById('btn-easy');
        this.btnMedium = document.getElementById('btn-medium');
        this.btnHard = document.getElementById('btn-hard');
        this.difficultySelector = document.getElementById('difficulty-selector');
        this.btnRestart = document.getElementById('btn-restart');
        this.btnClearHistory = document.getElementById('btn-clear-history');

        this.bindEvents();
    }

    bindEvents() {
        this.cells.forEach(cell => {
            cell.addEventListener('click', (e) => this.handleCellClick(e));
        });

        this.btnPvp.addEventListener('click', () => this.setMode('pvp'));
        this.btnPve.addEventListener('click', () => this.setMode('pve'));

        this.btnEasy.addEventListener('click', () => this.setDifficulty('easy'));
        this.btnMedium.addEventListener('click', () => this.setDifficulty('medium'));
        this.btnHard.addEventListener('click', () => this.setDifficulty('hard'));

        this.btnRestart.addEventListener('click', () => this.restart());
        this.btnClearHistory.addEventListener('click', () => this.clearHistory());
    }

    handleCellClick(e) {
        const index = parseInt(e.target.dataset.index);

        if (game.gameOver) return;
        if (game.mode === 'pve' && game.currentPlayer === 'O') return;

        if (!game.makeMove(index)) return;

        sound.init();
        sound.play('place');

        this.renderCell(index, game.currentPlayer);

        const result = game.checkWinner();
        if (result) {
            this.handleGameEnd(result);
            return;
        }

        game.switchPlayer();
        this.updateStatus();

        if (game.mode === 'pve' && game.currentPlayer === 'O') {
            setTimeout(() => this.aiMove(), 500);
        }
    }

    aiMove() {
        if (game.gameOver) return;

        const move = ai.getMove([...game.board], game.difficulty);
        if (move === null) return;

        game.makeMove(move);
        sound.play('place');
        this.renderCell(move, 'O');

        const result = game.checkWinner();
        if (result) {
            this.handleGameEnd(result);
            return;
        }

        game.switchPlayer();
        this.updateStatus();
    }

    handleGameEnd(result) {
        game.gameOver = true;

        if (result.winner === 'draw') {
            this.statusEl.textContent = '平局!';
            sound.play('draw');
            game.updateScore('draw');
            history.addRecord(game.mode, '平局');
        } else {
            const winner = result.winner;
            result.pattern.forEach(index => {
                this.cells[index].classList.add('win');
            });

            if (game.mode === 'pve') {
                if (winner === 'X') {
                    this.statusEl.textContent = '你赢了!';
                    sound.play('win');
                } else {
                    this.statusEl.textContent = 'AI 赢了!';
                    sound.play('lose');
                }
            } else {
                this.statusEl.textContent = `玩家 ${winner} 获胜!`;
                sound.play('win');
            }

            game.updateScore(winner);
            history.addRecord(game.mode, winner === 'X' ? 'X胜' : 'O胜');
        }

        this.updateScores();
        this.renderHistory();
    }

    renderCell(index, player) {
        const cell = this.cells[index];
        cell.textContent = player;
        cell.classList.add('taken', player.toLowerCase());
    }

    updateStatus() {
        if (game.mode === 'pve') {
            this.statusEl.textContent = game.currentPlayer === 'X' ? '你的回合' : 'AI 思考中...';
        } else {
            this.statusEl.textContent = `玩家 ${game.currentPlayer} 的回合`;
        }
    }

    updateScores() {
        this.scoreXEl.textContent = game.scores.X;
        this.scoreOEl.textContent = game.scores.O;
        this.scoreDrawEl.textContent = game.scores.draw;
    }

    renderHistory() {
        const records = history.getRecords();
        if (records.length === 0) {
            this.historyListEl.innerHTML = '<div class="empty-history">暂无记录</div>';
            return;
        }

        this.historyListEl.innerHTML = records.map(record => {
            let resultClass = 'draw';
            if (record.result === 'X胜') resultClass = 'win';
            if (record.result === 'O胜') resultClass = 'lose';

            return `<div class="history-item ${resultClass}">${record.id}. ${record.mode} - ${record.result}</div>`;
        }).join('');

        this.historyListEl.scrollTop = this.historyListEl.scrollHeight;
    }

    setMode(mode) {
        game.mode = mode;
        this.btnPvp.classList.toggle('active', mode === 'pvp');
        this.btnPve.classList.toggle('active', mode === 'pve');
        this.difficultySelector.classList.toggle('hidden', mode === 'pvp');
        this.restart();
    }

    setDifficulty(difficulty) {
        game.difficulty = difficulty;
        this.btnEasy.classList.toggle('active', difficulty === 'easy');
        this.btnMedium.classList.toggle('active', difficulty === 'medium');
        this.btnHard.classList.toggle('active', difficulty === 'hard');
        this.restart();
    }

    restart() {
        game.reset();
        this.cells.forEach(cell => {
            cell.textContent = '';
            cell.className = 'cell';
        });
        this.updateStatus();
    }

    clearHistory() {
        history.clear();
        game.scores = { X: 0, O: 0, draw: 0 };
        this.updateScores();
        this.renderHistory();
    }
}

const ui = new UI();
