// 通用工具类
class UIUtils {
    static showNotification(message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <i class="icon-${type}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <i class="icon-close"></i>
            </button>
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            if (notification.parentElement) {
                notification.classList.add('fade-out');
                setTimeout(() => notification.remove(), 300);
            }
        }, duration);
    }
    
    static showLoading(element, text = '加载中...') {
        element.classList.add('loading');
        element.innerHTML = `<i class="icon-spinner"></i> ${text}`;
        element.disabled = true;
    }
    
    static hideLoading(element, originalText) {
        element.classList.remove('loading');
        element.innerHTML = originalText;
        element.disabled = false;
    }
}

// 表单验证增强（续）
class FormValidator {
    constructor(form) {
        this.form = form;
        this.rules = {};
        this.init();
    }

    init() {
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
        this.setupRealTimeValidation();
    }

    addRule(fieldName, validator, message) {
        if (!this.rules[fieldName]) {
            this.rules[fieldName] = [];
        }
        this.rules[fieldName].push({ validator, message });
    }

    setupRealTimeValidation() {
        const inputs = this.form.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
            input.addEventListener('blur', () => this.validateField(input));
            input.addEventListener('input', () => this.clearFieldError(input));
        });
    }

    validateField(field) {
        const fieldName = field.name;
        const rules = this.rules[fieldName];

        if (!rules) return true;

        for (const rule of rules) {
            if (!rule.validator(field.value)) {
                this.showFieldError(field, rule.message);
                return false;
            }
        }

        this.clearFieldError(field);
        return true;
    }

    showFieldError(field, message) {
        field.classList.add('error');
        let errorDiv = field.parentNode.querySelector('.field-error');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'field-error';
            field.parentNode.appendChild(errorDiv);
        }
        errorDiv.textContent = message;
    }

    clearFieldError(field) {
        field.classList.remove('error');
        const errorDiv = field.parentNode.querySelector('.field-error');
        if (errorDiv) {
            errorDiv.remove();
        }
    }

    handleSubmit(e) {
        let isValid = true;
        const inputs = this.form.querySelectorAll('input, textarea, select');

        inputs.forEach(input => {
            if (!this.validateField(input)) {
                isValid = false;
            }
        });

        if (!isValid) {
            e.preventDefault();
            UIUtils.showNotification('请检查表单中的错误', 'error');
        }
    }
}

// 文件上传增强类
class FileUploader {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            maxSize: 100 * 1024 * 1024, // 100MB
            allowedTypes: ['video/mp4', 'video/avi', 'video/mov'],
            allowedExtensions: ['mp4', 'avi', 'mov', 'dav'],
            ...options
        };
        this.currentFile = null;
        this.init();
    }

    init() {
        this.setupDropZone();
        this.setupFileInput();
    }

    setupDropZone() {
        const dropZone = this.container.querySelector('#uploadZone');
        if (!dropZone) return;

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.handleFile(files[0]);
            }
        });

        dropZone.addEventListener('click', () => {
            const fileInput = this.container.querySelector('#fileInput');
            if (fileInput) fileInput.click();
        });
    }

    setupFileInput() {
        const fileInput = this.container.querySelector('#fileInput');
        if (!fileInput) return;

        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleFile(e.target.files[0]);
            }
        });
    }

    handleFile(file) {
        if (!this.validateFile(file)) return;

        this.showFilePreview(file);
        this.enableSubmit();
    }

    validateFile(file) {
        const errors = [];

        // 文件大小检查
        if (file.size > this.options.maxSize) {
            errors.push(`文件大小超过限制 (${Math.round(this.options.maxSize / 1024 / 1024)}MB)`);
        }

        // 文件类型检查
        const fileName = file.name.toLowerCase();
        const fileExtension = fileName.split('.').pop();

        if (!this.options.allowedTypes.includes(file.type) &&
            !this.options.allowedExtensions.includes(fileExtension)) {
            errors.push('不支持的文件格式，请上传MP4、AVI、MOV或DAV格式的视频文件');
        }

        // 文件名安全检查
        if (!/^[a-zA-Z0-9._-]+$/.test(file.name)) {
            errors.push('文件名包含非法字符，请使用英文字母、数字、点号、下划线或连字符');
        }

        if (errors.length > 0) {
            UIUtils.showNotification(errors.join('；'), 'error');
            return false;
        }

        return true;
    }
    showFilePreview(file) {
        const preview = this.container.querySelector('#filePreview');
        const uploadZone = this.container.querySelector('#uploadZone');

        if (preview && uploadZone) {
            uploadZone.style.display = 'none';
            preview.style.display = 'block';

            preview.querySelector('#fileName').textContent = file.name;
            preview.querySelector('#fileSize').textContent = this.formatFileSize(file.size);
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    enableSubmit() {
        const submitBtn = this.container.querySelector('#submitBtn');
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.add('btn-enabled');
        }
    }
}

// 密码强度检测器
class PasswordStrengthChecker {
    constructor(passwordInput, strengthIndicator) {
        this.passwordInput = passwordInput;
        this.strengthIndicator = strengthIndicator;
        this.init();
    }

    init() {
        this.passwordInput.addEventListener('input', () => {
            this.checkStrength(this.passwordInput.value);
        });
    }

    checkStrength(password) {
        let score = 0;
        let feedback = [];

        // 长度检查
        if (password.length >= 8) score += 1;
        else feedback.push('至少8个字符');

        // 大写字母
        if (/[A-Z]/.test(password)) score += 1;
        else feedback.push('包含大写字母');

        // 小写字母
        if (/[a-z]/.test(password)) score += 1;
        else feedback.push('包含小写字母');

        // 数字
        if (/\d/.test(password)) score += 1;
        else feedback.push('包含数字');

        // 特殊字符
        if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) score += 1;
        else feedback.push('包含特殊字符');

        this.updateStrengthDisplay(score, feedback);
    }

    updateStrengthDisplay(score, feedback) {
        const strengthFill = this.strengthIndicator.querySelector('#strengthFill');
        const strengthText = this.strengthIndicator.querySelector('#strengthText');

        const levels = ['很弱', '弱', '一般', '强', '很强'];
        const colors = ['#e74c3c', '#e67e22', '#f39c12', '#27ae60', '#2ecc71'];

        const level = Math.min(score, 4);
        const percentage = (score / 5) * 100;

        strengthFill.style.width = `${percentage}%`;
        strengthFill.style.backgroundColor = colors[level];
        strengthText.textContent = `密码强度：${levels[level]}`;

        if (feedback.length > 0 && score < 4) {
            strengthText.textContent += ` (建议：${feedback.slice(0, 2).join('、')})`;
        }
    }
}

// Ajax请求封装
class ApiClient {
    static async request(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            ...options
        };

        try {
            const response = await fetch(url, defaultOptions);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            }

            return await response.text();
        } catch (error) {
            console.error('API请求失败:', error);
            UIUtils.showNotification('网络请求失败，请稍后重试', 'error');
            throw error;
        }
    }

    static async get(url, params = {}) {
        const urlParams = new URLSearchParams(params);
        const fullUrl = urlParams.toString() ? `${url}?${urlParams}` : url;
        return this.request(fullUrl);
    }

    static async post(url, data = {}) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    static async postForm(url, formData) {
        return this.request(url, {
            method: 'POST',
            headers: {}, // 让浏览器自动设置Content-Type
            body: formData
        });
    }
}

// 实时进度监控
class ProgressMonitor {
    constructor(videoId) {
        this.videoId = videoId;
        this.isPolling = false;
        this.pollInterval = null;
        this.maxRetries = 5;
        this.retryCount = 0;
        this.pollDelay = 2000; // 2秒轮询间隔
    }

    async checkProgress() {
        try {
            const data = await ApiClient.get(`/check_progress/${this.videoId}`);
            this.retryCount = 0; // 重置重试计数
            this.updateProgress(data);

            if (data.processed) {
                this.stop();
                this.onComplete(data);
            }
        } catch (error) {
            this.retryCount++;
            console.error(`进度检查失败 (${this.retryCount}/${this.maxRetries}):`, error);

            if (this.retryCount >= this.maxRetries) {
                this.stop();
                UIUtils.showNotification('进度检查失败次数过多，请刷新页面重试', 'error');
            } else {
                // 指数退避重试
                this.pollDelay = Math.min(this.pollDelay * 1.5, 10000);
            }
        }
    }

    updateProgress(data) {
        const progressBar = document.querySelector('.progress-fill');
        const statusText = document.querySelector('#progressText');
        const progressPercentage = document.querySelector('#progressPercentage');
        const stageElements = document.querySelectorAll('.stage');

        // 更新进度条（使用模拟进度）
        if (progressBar) {
            const progress = data.progress || 0;
            progressBar.style.width = `${progress}%`;
            progressBar.style.transition = 'width 0.3s ease';
        }

        if (progressPercentage) {
            progressPercentage.textContent = `${data.progress || 0}%`;
        }

        if (statusText) {
            statusText.textContent = data.status || '处理中...';
        }

        // 更新统计数据
        this.updateStats(data);

        // 更新处理阶段
        if (data.stage !== undefined && stageElements.length > 0) {
            stageElements.forEach((el, index) => {
                el.classList.remove('active', 'completed');
                if (index < data.stage) {
                    el.classList.add('completed');
                } else if (index === data.stage) {
                    el.classList.add('active');
                }
            });
        }
    }

    updateStats(data) {
        const framesElement = document.getElementById('framesProcessed');
        const detectionElement = document.getElementById('detectionCount');
        const timeElement = document.getElementById('processingTime');

        if (framesElement && data.frames_processed !== undefined) {
            framesElement.textContent = data.frames_processed;
        }
        if (detectionElement && data.detection_count !== undefined) {
            detectionElement.textContent = data.detection_count;
        }
        if (timeElement && data.processing_time !== undefined) {
            timeElement.textContent = data.processing_time.toFixed(1) + 's';
        }
    }

    start() {
        if (this.isPolling) return;
        this.isPolling = true;
        this.pollInterval = setInterval(() => {
            this.checkProgress();
        }, this.pollDelay);
    }

    stop() {
        this.isPolling = false;
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    onComplete(data) {
        // 显示结果
        const resultsSection = document.getElementById('resultsSection');
        if (resultsSection) {
            resultsSection.style.display = 'block';
            if (data.results && Object.keys(data.results).length > 0) {
                this.displayResults(data.results);
            } else {
                resultsSection.innerHTML = '<h2>识别结果</h2><p>未识别到狗</p>';
            }
        }

        UIUtils.showNotification('视频处理完成！', 'success');
    }

    displayResults(results) {
        // 实现结果显示逻辑
        const topResult = Object.values(results).reduce((top, current) =>
            (current.confidence > top.confidence) ? current : top,
            { confidence: 0 }
        );

        const topResultCard = document.getElementById('topResultCard');
        if (topResultCard) {
            topResultCard.innerHTML = `
                <div class="result-highlight">
                    <h3>${topResult.name}</h3>
                    <div class="confidence-score">${topResult.confidence.toFixed(1)}%</div>
                </div>
            `;
        }

        const resultList = document.getElementById('resultList');
        if (resultList) {
            resultList.innerHTML = Object.entries(results).map(([id, data]) => `
                <div class="result-item">
                    <span class="result-name">${data.name}</span>
                    <span class="result-confidence">${data.confidence.toFixed(1)}%</span>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: ${data.confidence}%"></div>
                    </div>
                </div>
            `).join('');
        }
    }
}

// 全局初始化函数
function initializeApp() {
    // 初始化文件上传器
    const uploadContainer = document.querySelector('.upload-container');
    if (uploadContainer) {
        new FileUploader(uploadContainer);
    }

    // 初始化表单验证
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        const validator = new FormValidator(form);

        // 添加常见验证规则
        const usernameInput = form.querySelector('input[name="username"]');
        if (usernameInput) {
            validator.addRule('username',
                value => value.length >= 3 && value.length <= 20,
                '用户名长度必须在3-20个字符之间'
            );
        }

        const passwordInput = form.querySelector('input[name="password"]');
        if (passwordInput) {
            validator.addRule('password',
                value => value.length >= 6,
                '密码长度至少6个字符'
            );

            // 初始化密码强度检测
            const strengthIndicator = form.querySelector('.password-strength');
            if (strengthIndicator) {
                new PasswordStrengthChecker(passwordInput, strengthIndicator);
            }
        }
    });

    // 初始化进度监控
    const videoIdElement = document.querySelector('[data-video-id]');
    if (videoIdElement) {
        const videoId = videoIdElement.getAttribute('data-video-id');
        const monitor = new ProgressMonitor(videoId);
        monitor.start();
    }
}

// 当DOM加载完成时初始化
document.addEventListener('DOMContentLoaded', initializeApp);

// 全局错误处理
window.addEventListener('error', (event) => {
    console.error('全局错误:', event.error);
    UIUtils.showNotification('发生了一个错误，请刷新页面重试', 'error');
});

// 导出主要类供其他模块使用
window.UIUtils = UIUtils;
window.FormValidator = FormValidator;
window.FileUploader = FileUploader;
window.ApiClient = ApiClient;
window.ProgressMonitor = ProgressMonitor;

