// TTS Service Module
class TTSService {
    constructor() {
        this.synth = window.speechSynthesis;
        this.currentUtterance = null;
        this.isSpeaking = false;
        this.voices = [];
        this.enabled = false;
        this.config = null;

        this.loadVoices();
        
        // Load voices when they become available (Firefox loads voices asynchronously)
        if (this.synth.onvoiceschanged !== undefined) {
            this.synth.onvoiceschanged = () => this.loadVoices();
        }
    }

    setConfig(config) {
        this.config = config;
        this.enabled = config.enabled !== false && this.isAvailable();
        return this.enabled;
    }

    loadVoices() {
        this.voices = this.synth.getVoices();
    }

    isAvailable() {
        // 仅检查API是否存在；语音列表在部分浏览器（如Firefox）中异步加载，
        // 不能作为可用性判断依据，否则初始化时会误判为不可用
        return 'speechSynthesis' in window;
    }

    speak(text, lang = 'en-US') {
        return new Promise((resolve, reject) => {
            if (!this.isAvailable()) {
                reject(new Error('TTS not available'));
                return;
            }

            if (!this.enabled) {
                console.log('TTS is disabled');
                resolve();
                return;
            }

            // Cancel any ongoing speech
            this.stop();

            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = lang || this.config?.lang || 'en-US';
            utterance.rate = this.config?.rate || 0.9;
            utterance.pitch = this.config?.pitch || 1.0;

            // Set voice if specified in config
            if (this.config?.voice) {
                // 语音列表可能尚未加载完成（异步加载的浏览器），先尝试重新获取
                if (this.voices.length === 0) {
                    this.loadVoices();
                }
                const voice = this.voices.find(v => 
                    v.name === this.config.voice || 
                    v.name.includes(this.config.voice)
                );
                if (voice) {
                    utterance.voice = voice;
                }
            }

            utterance.onstart = () => {
                this.isSpeaking = true;
                this.currentUtterance = utterance;
            };

            utterance.onend = () => {
                this.isSpeaking = false;
                this.currentUtterance = null;
                resolve();
            };

            utterance.onerror = (event) => {
                this.isSpeaking = false;
                this.currentUtterance = null;
                reject(new Error(`TTS error: ${event.error}`));
            };

            this.synth.speak(utterance);
        });
    }

    stop() {
        if (this.synth.speaking) {
            this.synth.cancel();
        }
        this.isSpeaking = false;
        this.currentUtterance = null;
    }

    interruptAndSpeak(text, lang) {
        this.stop();
        return this.speak(text, lang);
    }
}

// Export for use in other modules
const ttsService = new TTSService();