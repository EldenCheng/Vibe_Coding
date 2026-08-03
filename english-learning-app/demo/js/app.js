// Main Application Module
class App {
    constructor() {
        this.config = null;
        this.currentScene = null;
        this.currentQuestion = null;
        this.evaluationResults = null;
    }

    async init() {
        try {
            // Load configuration
            console.log('Loading configuration...');
            this.config = await configLoader.load();
            
            if (!configLoader.getGeminiConfig()?.apiKey) {
                uiController.showConfigWarning();
            }

            // Initialize TTS service
            ttsService.setConfig(configLoader.getTTSConfig());
            if (!ttsService.isAvailable()) {
                uiController.showTTSWarning();
            }

            // Initialize AI service
            aiService.setConfig(configLoader.getGeminiConfig());

            // Set up event listeners
            this.setupEventListeners();

            console.log('App initialized successfully');
        } catch (error) {
            console.error('App initialization error:', error);
            uiController.showError('Failed to initialize app: ' + error.message);
        }
    }

    setupEventListeners() {
        // Start button
        uiController.elements.startBtn.addEventListener('click', () => this.startSession());

        // Back button
        uiController.elements.backBtn.addEventListener('click', () => this.goToWelcome());

        // TTS button
        uiController.elements.ttsBtn.addEventListener('click', () => this.readQuestionAloud());

        // Answer input
        uiController.elements.answerInput.addEventListener('input', () => {
            uiController.updateSubmitButton();
        });

        // Submit button
        uiController.elements.submitBtn.addEventListener('click', () => this.submitAnswer());

        // Confirm button
        uiController.elements.confirmBtn.addEventListener('click', () => this.goToWelcome());

        // Retry button
        uiController.elements.retryBtn.addEventListener('click', () => this.startSession());

        // Error screen buttons
        uiController.elements.retryErrorBtn.addEventListener('click', () => this.startSession());
        uiController.elements.backToWelcomeBtn.addEventListener('click', () => this.goToWelcome());
    }

    async startSession() {
        try {
            // Check if API key is configured
            if (!configLoader.getGeminiConfig()?.apiKey) {
                uiController.showError('Please configure your Gemini API key in demo_config.json');
                return;
            }

            // Show loading screen
            uiController.showScreen('loading');
            uiController.updateLoadingMessage('Loading scene...');

            // Load scene
            const sceneId = configLoader.getDemoSettings().sceneId;
            this.currentScene = await sceneLoader.loadScene(sceneId);

            // Load image
            uiController.updateLoadingMessage('Loading image...');
            await uiController.loadImage(sceneLoader.getImagePath());

            // Prepare first question
            uiController.updateLoadingMessage('Preparing question...');
            this.currentQuestion = sceneLoader.getCurrentQuestion();

            // Update question screen
            uiController.updateQuestionScreen(1, this.currentQuestion.text);

            // Clear previous answers
            uiController.clearAnswerInput();

            // Show question screen
            uiController.showScreen('question');

            // Read question aloud
            this.readQuestionAloud();

        } catch (error) {
            console.error('Session start error:', error);
            uiController.showError('Failed to start session: ' + error.message);
        }
    }

    readQuestionAloud() {
        if (this.currentQuestion && ttsService.isAvailable()) {
            ttsService.speak(this.currentQuestion.text, 'en-US')
                .catch(error => {
                    console.error('TTS error:', error);
                    // Don't show error to user, just log it
                });
        }
    }

    async submitAnswer() {
        try {
            const answer = uiController.getAnswerText();
            
            if (!answer.trim()) {
                uiController.showError('Please enter your answer before submitting.');
                return;
            }

            // Show evaluating screen
            uiController.showScreen('evaluating');

            // Call AI service
            const params = {
                question: this.currentQuestion.text,
                answer: answer,
                imageDescription: sceneLoader.getImageDescription(),
                gradeLevel: sceneLoader.getGradeLevel(),
                imagePath: sceneLoader.getImagePath()
            };

            this.evaluationResults = await aiService.evaluateAnswer(params);
            
            // Calculate composite score
            const compositeScore = aiService.calculateCompositeScore(this.evaluationResults);

            // Update result screen
            uiController.updateResultScreen(this.evaluationResults, compositeScore);

            // Show result screen
            uiController.showScreen('result');

        } catch (error) {
            console.error('Answer submission error:', error);
            uiController.showError('Failed to evaluate answer: ' + error.message);
        }
    }

    goToWelcome() {
        // Stop any ongoing speech
        ttsService.stop();
        
        // Reset state
        this.currentScene = null;
        this.currentQuestion = null;
        this.evaluationResults = null;
        
        // Reset UI
        uiController.reset();
        uiController.showScreen('welcome');
    }
}

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    const app = new App();
    app.init();
});