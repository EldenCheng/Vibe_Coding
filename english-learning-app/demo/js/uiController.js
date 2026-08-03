// UI Controller Module
class UIController {
    constructor() {
        this.screens = {
            welcome: document.getElementById('welcome-screen'),
            loading: document.getElementById('loading-screen'),
            question: document.getElementById('question-screen'),
            evaluating: document.getElementById('evaluating-screen'),
            result: document.getElementById('result-screen'),
            error: document.getElementById('error-screen')
        };

        this.elements = {
            // Welcome screen
            startBtn: document.getElementById('start-btn'),
            configWarning: document.getElementById('config-warning'),
            ttsWarning: document.getElementById('tts-warning'),
            
            // Loading screen
            loadingMessage: document.getElementById('loading-message'),
            
            // Question screen
            backBtn: document.getElementById('back-btn'),
            currentQ: document.getElementById('current-q'),
            sceneImage: document.getElementById('scene-image'),
            imageLoading: document.getElementById('image-loading'),
            ttsBtn: document.getElementById('tts-btn'),
            questionText: document.getElementById('question-text'),
            answerInput: document.getElementById('answer-input'),
            submitBtn: document.getElementById('submit-btn'),
            
            // Result screen
            compositeScore: document.getElementById('composite-score'),
            vocabScore: document.getElementById('vocab-score'),
            grammarScore: document.getElementById('grammar-score'),
            relevanceScore: document.getElementById('relevance-score'),
            pronunciationScore: document.getElementById('pronunciation-score'),
            aiComment: document.getElementById('ai-comment'),
            confirmBtn: document.getElementById('confirm-btn'),
            retryBtn: document.getElementById('retry-btn'),
            
            // Error screen
            errorMessage: document.getElementById('error-message'),
            retryErrorBtn: document.getElementById('retry-error-btn'),
            backToWelcomeBtn: document.getElementById('back-to-welcome-btn')
        };

        this.currentScreen = 'welcome';
    }

    showScreen(screenName) {
        // Hide current screen
        if (this.screens[this.currentScreen]) {
            this.screens[this.currentScreen].classList.remove('active');
        }
        
        // Show new screen
        if (this.screens[screenName]) {
            this.screens[screenName].classList.add('active');
            this.currentScreen = screenName;
        }
    }

    updateLoadingMessage(message) {
        if (this.elements.loadingMessage) {
            this.elements.loadingMessage.textContent = message;
        }
    }

    showConfigWarning() {
        if (this.elements.configWarning) {
            this.elements.configWarning.classList.remove('hidden');
        }
    }

    hideConfigWarning() {
        if (this.elements.configWarning) {
            this.elements.configWarning.classList.add('hidden');
        }
    }

    showTTSWarning() {
        if (this.elements.ttsWarning) {
            this.elements.ttsWarning.classList.remove('hidden');
        }
    }

    hideTTSWarning() {
        if (this.elements.ttsWarning) {
            this.elements.ttsWarning.classList.add('hidden');
        }
    }

    updateQuestionScreen(questionNumber, questionText) {
        if (this.elements.currentQ) {
            this.elements.currentQ.textContent = questionNumber;
        }
        if (this.elements.questionText) {
            this.elements.questionText.textContent = questionText;
        }
    }

    loadImage(imageUrl) {
        return new Promise((resolve, reject) => {
            if (this.elements.imageLoading) {
                this.elements.imageLoading.classList.remove('hidden');
            }

            if (this.elements.sceneImage) {
                this.elements.sceneImage.src = imageUrl;
                this.elements.sceneImage.onload = () => {
                    if (this.elements.imageLoading) {
                        this.elements.imageLoading.classList.add('hidden');
                    }
                    resolve();
                };
                this.elements.sceneImage.onerror = () => {
                    if (this.elements.imageLoading) {
                        this.elements.imageLoading.classList.add('hidden');
                    }
                    reject(new Error('Failed to load image'));
                };
            }
        });
    }

    getAnswerText() {
        return this.elements.answerInput ? this.elements.answerInput.value.trim() : '';
    }

    clearAnswerInput() {
        if (this.elements.answerInput) {
            this.elements.answerInput.value = '';
        }
        this.updateSubmitButton();
    }

    updateSubmitButton() {
        const answerText = this.getAnswerText();
        if (this.elements.submitBtn) {
            this.elements.submitBtn.disabled = answerText.length === 0;
        }
    }

    updateResultScreen(scores, compositeScore) {
        if (this.elements.compositeScore) {
            this.elements.compositeScore.textContent = compositeScore;
        }
        if (this.elements.vocabScore) {
            this.elements.vocabScore.textContent = scores.vocabulary;
        }
        if (this.elements.grammarScore) {
            this.elements.grammarScore.textContent = scores.grammar;
        }
        if (this.elements.relevanceScore) {
            this.elements.relevanceScore.textContent = scores.relevance;
        }
        if (this.elements.pronunciationScore) {
            this.elements.pronunciationScore.textContent = scores.pronunciation;
        }
        if (this.elements.aiComment) {
            this.elements.aiComment.textContent = scores.comment;
        }
    }

    showError(message) {
        if (this.elements.errorMessage) {
            this.elements.errorMessage.textContent = message;
        }
        this.showScreen('error');
    }

    reset() {
        this.clearAnswerInput();
        this.hideConfigWarning();
        this.hideTTSWarning();
    }
}

// Export for use in other modules
const uiController = new UIController();