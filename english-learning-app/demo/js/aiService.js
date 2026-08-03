// AI Service Module for Gemini API
class AIService {
    constructor() {
        this.config = null;
    }

    setConfig(config) {
        this.config = config;
    }

    async evaluateAnswer(params) {
        try {
            const { question, answer, imageDescription, gradeLevel, imagePath } = params;
            
            if (!this.config?.apiKey) {
                throw new Error('API key not configured');
            }

            const prompt = this.buildEvaluationPrompt(question, answer, imageDescription, gradeLevel);
            
            // 构造请求内容：包含图片和文字提示词
            const contents = [];
            
            // 如果提供了图片路径，加载图片并作为 inlineData 发送
            if (imagePath) {
                try {
                    const imageData = await this.loadImageAsBase64(imagePath);
                    contents.push({
                        parts: [
                            {
                                inlineData: {
                                    mimeType: imageData.mimeType,
                                    data: imageData.base64
                                }
                            },
                            { text: prompt }
                        ]
                    });
                } catch (imgError) {
                    console.warn('Failed to load image, falling back to text-only:', imgError);
                    // 图片加载失败时降级为纯文字
                    contents.push({ parts: [{ text: prompt }] });
                }
            } else {
                contents.push({ parts: [{ text: prompt }] });
            }

            const response = await fetch(
                `${this.config.baseUrl}/v1beta/models/${this.config.textModel}:generateContent?key=${this.config.apiKey}`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        contents: contents,
                        generationConfig: {
                            temperature: 0.7,
                            maxOutputTokens: 1000,
                        }
                    })
                }
            );

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`API error: ${response.status} - ${errorText}`);
            }

            const data = await response.json();
            return this.parseEvaluationResponse(data);
        } catch (error) {
            console.error('AI evaluation error:', error);
            throw error;
        }
    }

    // 加载图片并转换为 base64
    async loadImageAsBase64(imagePath) {
        const response = await fetch(imagePath);
        if (!response.ok) {
            throw new Error(`Failed to fetch image: ${response.status}`);
        }
        const blob = await response.blob();
        
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                const dataUrl = reader.result;
                // dataUrl 格式: "data:image/jpeg;base64,<base64data>"
                const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
                if (!match) {
                    reject(new Error('Invalid data URL format'));
                    return;
                }
                resolve({
                    mimeType: match[1],
                    base64: match[2]
                });
            };
            reader.onerror = () => reject(new Error('Failed to read image file'));
            reader.readAsDataURL(blob);
        });
    }

    buildEvaluationPrompt(question, answer, imageDescription, gradeLevel) {
        const gradeInstructions = {
            primary: `You are helping a Chinese student aged 10-12 practice English. Use encouraging language appropriate for this age.`,
            junior: `You are helping a Chinese student aged 13-15 practice English. Use encouraging language appropriate for teenagers.`,
            senior: `You are helping a Chinese student aged 16-18 practice English. Use encouraging language appropriate for older students.`
        };

        return `
${gradeInstructions[gradeLevel] || gradeInstructions.junior}

I have provided you with an image of a scene. Here is additional context about the image:
"${imageDescription}"

The student was asked this question about the image:
"${question}"

The student's answer is:
"${answer}"

Task: Evaluate the student's answer based on the image and question, and provide:
1. Vocabulary score (0-100): Assess range and accuracy of vocabulary
2. Grammar score (0-100): Assess sentence structure and grammatical correctness
3. Relevance score (0-100): How well the answer addresses the question and matches the image
4. Pronunciation score (0-100): Assess based on common pronunciation patterns (this is text-based, so estimate based on spelling and typical issues)
5. Brief encouraging comment (2-3 sentences): Provide specific praise and one suggestion for improvement

IMPORTANT: Respond ONLY with a valid JSON object in this exact format:
{
  "vocabulary": 85,
  "grammar": 90,
  "relevance": 88,
  "pronunciation": 82,
  "comment": "Your answer is clear and relevant..."
}

Do not include any other text before or after the JSON.
`;
    }

    parseEvaluationResponse(data) {
        try {
            const content = data.candidates?.[0]?.content?.parts?.[0]?.text;
            if (!content) {
                throw new Error('Empty response from AI');
            }

            // Extract JSON from the response
            const jsonMatch = content.match(/\{[\s\S]*\}/);
            if (!jsonMatch) {
                throw new Error('No JSON found in response');
            }

            const parsed = JSON.parse(jsonMatch[0]);
            
            // Validate and clamp scores
            const scores = {
                vocabulary: this.clampScore(parsed.vocabulary),
                grammar: this.clampScore(parsed.grammar),
                relevance: this.clampScore(parsed.relevance),
                pronunciation: this.clampScore(parsed.pronunciation),
                comment: parsed.comment || 'Good effort! Keep practicing!'
            };

            return scores;
        } catch (error) {
            console.error('Response parsing error:', error);
            // Return default scores on error
            return {
                vocabulary: 75,
                grammar: 75,
                relevance: 75,
                pronunciation: 75,
                comment: 'We had trouble processing your answer. Please try again!'
            };
        }
    }

    clampScore(value) {
        if (typeof value !== 'number' || isNaN(value)) {
            return 75; // Default score
        }
        return Math.min(100, Math.max(0, Math.round(value)));
    }

    calculateCompositeScore(scores) {
        const weights = { vocabulary: 0.25, grammar: 0.25, relevance: 0.25, pronunciation: 0.25 };
        const composite = 
            scores.vocabulary * weights.vocabulary +
            scores.grammar * weights.grammar +
            scores.relevance * weights.relevance +
            scores.pronunciation * weights.pronunciation;
        
        return Math.min(100, Math.max(0, Math.round(composite)));
    }
}

// Export for use in other modules
const aiService = new AIService();