class AI {
    constructor() {
        this.winPatterns = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],
            [0, 3, 6], [1, 4, 7], [2, 5, 8],
            [0, 4, 8], [2, 4, 6]
        ];
    }

    getMove(board, difficulty) {
        const emptyCells = board.reduce((acc, cell, index) => {
            if (cell === null) acc.push(index);
            return acc;
        }, []);

        if (emptyCells.length === 0) return null;

        switch (difficulty) {
            case 'easy':
                return this.randomMove(emptyCells);
            case 'medium':
                return Math.random() < 0.5 ? this.bestMove(board, emptyCells) : this.randomMove(emptyCells);
            case 'hard':
                return this.bestMove(board, emptyCells);
            default:
                return this.randomMove(emptyCells);
        }
    }

    randomMove(emptyCells) {
        return emptyCells[Math.floor(Math.random() * emptyCells.length)];
    }

    bestMove(board, emptyCells) {
        let bestScore = -Infinity;
        let bestMove = emptyCells[0];

        for (const index of emptyCells) {
            board[index] = 'O';
            const score = this.minimax(board, 0, false);
            board[index] = null;

            if (score > bestScore) {
                bestScore = score;
                bestMove = index;
            }
        }

        return bestMove;
    }

    minimax(board, depth, isMaximizing) {
        const result = this.checkWinnerForMinimax(board);

        if (result !== null) {
            if (result === 'O') return 10 - depth;
            if (result === 'X') return depth - 10;
            return 0;
        }

        const emptyCells = board.reduce((acc, cell, index) => {
            if (cell === null) acc.push(index);
            return acc;
        }, []);

        if (isMaximizing) {
            let bestScore = -Infinity;
            for (const index of emptyCells) {
                board[index] = 'O';
                const score = this.minimax(board, depth + 1, false);
                board[index] = null;
                bestScore = Math.max(score, bestScore);
            }
            return bestScore;
        } else {
            let bestScore = Infinity;
            for (const index of emptyCells) {
                board[index] = 'X';
                const score = this.minimax(board, depth + 1, true);
                board[index] = null;
                bestScore = Math.min(score, bestScore);
            }
            return bestScore;
        }
    }

    checkWinnerForMinimax(board) {
        for (const [a, b, c] of this.winPatterns) {
            if (board[a] && board[a] === board[b] && board[a] === board[c]) {
                return board[a];
            }
        }

        if (board.every(cell => cell !== null)) {
            return 'draw';
        }

        return null;
    }
}

const ai = new AI();
