class Game {
    constructor() {
        this.board = Array(9).fill(null);
        this.currentPlayer = 'X';
        this.gameOver = false;
        this.mode = 'pvp';
        this.difficulty = 'medium';
        this.scores = { X: 0, O: 0, draw: 0 };
        this.winPatterns = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],
            [0, 3, 6], [1, 4, 7], [2, 5, 8],
            [0, 4, 8], [2, 4, 6]
        ];
    }

    reset() {
        this.board = Array(9).fill(null);
        this.currentPlayer = 'X';
        this.gameOver = false;
    }

    makeMove(index) {
        if (this.board[index] !== null || this.gameOver) {
            return false;
        }

        this.board[index] = this.currentPlayer;
        return true;
    }

    switchPlayer() {
        this.currentPlayer = this.currentPlayer === 'X' ? 'O' : 'X';
    }

    checkWinner() {
        for (const pattern of this.winPatterns) {
            const [a, b, c] = pattern;
            if (this.board[a] && this.board[a] === this.board[b] && this.board[a] === this.board[c]) {
                return { winner: this.board[a], pattern };
            }
        }

        if (this.board.every(cell => cell !== null)) {
            return { winner: 'draw', pattern: null };
        }

        return null;
    }

    getEmptyCells() {
        return this.board.reduce((acc, cell, index) => {
            if (cell === null) acc.push(index);
            return acc;
        }, []);
    }

    updateScore(result) {
        if (result === 'draw') {
            this.scores.draw++;
        } else {
            this.scores[result]++;
        }
    }
}

const game = new Game();
