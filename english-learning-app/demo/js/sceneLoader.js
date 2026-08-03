// Scene Loader Module
class SceneLoader {
    constructor() {
        this.currentScene = null;
        this.currentIndex = 0;
    }

    async loadScene(sceneId) {
        try {
            // Load index.json first to check if scene exists
            const indexResponse = await fetch('assets/scenes/index.json');
            if (!indexResponse.ok) {
                throw new Error('Failed to load scene index');
            }

            const indexData = await indexResponse.json();
            if (!indexData.scenes.includes(sceneId)) {
                throw new Error(`Scene "${sceneId}" not found`);
            }

            // Load scene metadata
            const metaResponse = await fetch(`assets/scenes/${sceneId}/meta.json`);
            if (!metaResponse.ok) {
                throw new Error('Failed to load scene metadata');
            }

            const meta = await metaResponse.json();

            // Load questions
            const questionsResponse = await fetch(`assets/scenes/${sceneId}/questions.json`);
            if (!questionsResponse.ok) {
                throw new Error('Failed to load questions');
            }

            const questionsData = await questionsResponse.json();

            // Construct complete scene object
            this.currentScene = {
                meta: meta,
                questions: questionsData.questions.sort((a, b) => a.order - b.order)
            };

            this.currentIndex = 0;
            return this.currentScene;
        } catch (error) {
            console.error('Scene loading error:', error);
            throw error;
        }
    }

    getCurrentQuestion() {
        if (!this.currentScene || this.currentIndex >= this.currentScene.questions.length) {
            return null;
        }
        return this.currentScene.questions[this.currentIndex];
    }

    nextQuestion() {
        this.currentIndex++;
        return this.getCurrentQuestion();
    }

    getCurrentScene() {
        return this.currentScene;
    }

    getImagePath() {
        if (!this.currentScene) {
            return null;
        }
        return `assets/scenes/${this.currentScene.meta.id}/image.jpg`;
    }

    getImageDescription() {
        if (!this.currentScene) {
            return null;
        }
        return this.currentScene.meta.imageDescription;
    }

    getSceneTitle() {
        if (!this.currentScene) {
            return null;
        }
        return this.currentScene.meta.title;
    }

    getGradeLevel() {
        if (!this.currentScene) {
            return null;
        }
        return this.currentScene.meta.gradeLevel;
    }
}

// Export for use in other modules
const sceneLoader = new SceneLoader();