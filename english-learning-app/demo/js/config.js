// Config Module
class ConfigLoader {
    constructor() {
        this.config = null;
        this.errors = [];
    }

    async load() {
        try {
            const response = await fetch('demo_config.json');
            if (!response.ok) {
                throw new Error('Failed to load config file');
            }

            const data = await response.json();
            this.validate(data);

            if (this.errors.length > 0) {
                throw new Error(`Config validation failed: ${this.errors.join(', ')}`);
            }

            this.config = data;
            return this.config;
        } catch (error) {
            console.error('Config loading error:', error);
            throw error;
        }
    }

    validate(config) {
        this.errors = [];

        // Check required fields
        if (!config.aiProvider || typeof config.aiProvider !== 'string') {
            this.errors.push('aiProvider is required and must be a string');
        }

        if (!config.gemini || typeof config.gemini !== 'object') {
            this.errors.push('gemini configuration is required');
        } else {
            if (!config.gemini.baseUrl || typeof config.gemini.baseUrl !== 'string') {
                this.errors.push('gemini.baseUrl is required');
            }
            // apiKey 缺失不阻止启动：欢迎页显示警告，开始会话时再拦截
            if (!config.gemini.textModel || typeof config.gemini.textModel !== 'string') {
                this.errors.push('gemini.textModel is required');
            }
        }

        if (!config.tts || typeof config.tts !== 'object') {
            this.errors.push('tts configuration is required');
        }

        if (!config.demoSettings || typeof config.demoSettings !== 'object') {
            this.errors.push('demoSettings configuration is required');
        }
    }

    get() {
        return this.config;
    }

    getGeminiConfig() {
        return this.config?.gemini;
    }

    getTTSConfig() {
        return this.config?.tts;
    }

    getDemoSettings() {
        return this.config?.demoSettings;
    }

    getUIConfig() {
        return this.config?.ui;
    }
}

// Export for use in other modules
const configLoader = new ConfigLoader();