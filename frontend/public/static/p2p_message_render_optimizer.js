/**
 * MessageRenderOptimizer - 消息渲染优化器
 * 
 * 功能:
 * - 虚拟滚动机制
 * - 增量更新功能
 * - 批量渲染队列
 * - 优化DOM操作性能
 * 
 * Feature: p2p-frontend-redesign
 * Requirements: 性能优化
 */

class MessageRenderOptimizer {
    constructor() {
        this.visibleRange = { start: 0, end: 50 };
        this.messageCache = new Map();
        this.renderQueue = [];
        this.isRendering = false;
        this.intersectionObserver = null;
    }
    
    /**
     * 设置虚拟滚动
     * @param {HTMLElement} container - 消息容器元素
     * @returns {IntersectionObserver} 观察器实例
     */
    setupVirtualScroll(container) {
        if (this.intersectionObserver) {
            this.intersectionObserver.disconnect();
        }
        
        this.intersectionObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                const messageId = entry.target.dataset.messageId;
                if (!messageId) return;
                
                if (entry.isIntersecting) {
                    this.renderMessage(messageId);
                } else {
                    this.unrenderMessage(messageId);
                }
            });
        }, {
            root: container,
            rootMargin: '100px', // 提前100px开始加载
            threshold: 0.01
        });
        
        return this.intersectionObserver;
    }
    
    /**
     * 渲染单个消息
     * @param {string} messageId - 消息ID
     */
    renderMessage(messageId) {
        const messageData = this.messageCache.get(messageId);
        if (!messageData) return;
        
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) return;
        
        // 如果消息已经渲染，跳过
        if (messageElement.dataset.rendered === 'true') return;
        
        // 渲染消息内容
        this.renderMessageContent(messageElement, messageData);
        messageElement.dataset.rendered = 'true';
    }
    
    /**
     * 取消渲染消息（保留占位符）
     * @param {string} messageId - 消息ID
     */
    unrenderMessage(messageId) {
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) return;
        
        // 保留消息高度，但清空内容以节省内存
        const height = messageElement.offsetHeight;
        messageElement.style.minHeight = `${height}px`;
        messageElement.innerHTML = '';
        messageElement.dataset.rendered = 'false';
    }
    
    /**
     * 渲染消息内容
     * @param {HTMLElement} element - 消息元素
     * @param {Object} messageData - 消息数据
     */
    renderMessageContent(element, messageData) {
        // 这个方法将由具体的消息组件实现
        // 这里只是一个占位符
        if (messageData.render && typeof messageData.render === 'function') {
            const content = messageData.render();
            element.innerHTML = '';
            element.appendChild(content);
        }
    }
    
    /**
     * 增量更新消息
     * @param {string} messageId - 消息ID
     * @param {Object} changes - 变化的数据
     */
    updateMessageIncremental(messageId, changes) {
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (!messageElement) return;
        
        // 只更新变化的部分，避免重新渲染整个消息
        if (changes.progress !== undefined) {
            const progressBar = messageElement.querySelector('.progress-fill');
            if (progressBar) {
                progressBar.style.width = `${changes.progress}%`;
            }
            
            const progressText = messageElement.querySelector('.progress-text');
            if (progressText && changes.bytesTransferred && changes.totalBytes) {
                progressText.textContent = `${changes.progress}% (${this.formatSize(changes.bytesTransferred)} / ${this.formatSize(changes.totalBytes)})`;
            }
        }
        
        if (changes.speed !== undefined) {
            const speedText = messageElement.querySelector('.speed-text');
            if (speedText) {
                speedText.textContent = this.formatSpeed(changes.speed);
            }
            
            const currentSpeedText = messageElement.querySelector('.current-speed');
            if (currentSpeedText) {
                currentSpeedText.textContent = `当前速度: ${this.formatSpeed(changes.speed)}`;
            }
        }
        
        if (changes.avgSpeed !== undefined) {
            const avgSpeedText = messageElement.querySelector('.avg-speed');
            if (avgSpeedText) {
                avgSpeedText.textContent = `平均速度: ${this.formatSpeed(changes.avgSpeed)}`;
            }
        }
        
        if (changes.estimatedTime !== undefined) {
            const timeText = messageElement.querySelector('.time-estimate');
            if (timeText) {
                timeText.textContent = `预计剩余时间: ${this.formatTime(changes.estimatedTime)}`;
            }
        }
        
        if (changes.status !== undefined) {
            const statusText = messageElement.querySelector('.status-text');
            if (statusText) {
                statusText.textContent = this.getStatusText(changes.status);
            }
            
            // 更新状态类
            messageElement.className = messageElement.className.replace(/\b(pending|accepted|connecting|transferring|completed|failed|cancelled|expired)\b/g, '');
            messageElement.classList.add(changes.status);
        }
    }
    
    /**
     * 批量渲染消息
     * @param {Array} messages - 消息数组
     */
    batchRender(messages) {
        this.renderQueue.push(...messages);
        if (!this.isRendering) {
            this.processRenderQueue();
        }
    }
    
    /**
     * 处理渲染队列
     */
    async processRenderQueue() {
        this.isRendering = true;
        
        while (this.renderQueue.length > 0) {
            const batch = this.renderQueue.splice(0, 10); // 每次处理10条
            
            for (const message of batch) {
                this.renderMessage(message.id);
                this.messageCache.set(message.id, message);
            }
            
            // 让出主线程，避免阻塞UI
            await new Promise(resolve => setTimeout(resolve, 0));
        }
        
        this.isRendering = false;
    }
    
    /**
     * 缓存消息数据
     * @param {string} messageId - 消息ID
     * @param {Object} messageData - 消息数据
     */
    cacheMessage(messageId, messageData) {
        this.messageCache.set(messageId, messageData);
    }
    
    /**
     * 获取缓存的消息
     * @param {string} messageId - 消息ID
     * @returns {Object|null} 消息数据
     */
    getCachedMessage(messageId) {
        return this.messageCache.get(messageId) || null;
    }
    
    /**
     * 清除消息缓存
     * @param {string} messageId - 消息ID
     */
    clearMessageCache(messageId) {
        this.messageCache.delete(messageId);
    }
    
    /**
     * 格式化文件大小
     * @param {number} bytes - 字节数
     * @returns {string} 格式化后的大小
     */
    formatSize(bytes) {
        if (bytes < 1024) {
            return `${bytes} B`;
        } else if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(2)} KB`;
        } else if (bytes < 1024 * 1024 * 1024) {
            return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
        } else {
            return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
        }
    }
    
    /**
     * 格式化速度
     * @param {number} bytesPerSecond - 每秒字节数
     * @returns {string} 格式化后的速度
     */
    formatSpeed(bytesPerSecond) {
        if (bytesPerSecond < 1024) {
            return `${bytesPerSecond.toFixed(0)} B/s`;
        } else if (bytesPerSecond < 1024 * 1024) {
            return `${(bytesPerSecond / 1024).toFixed(2)} KB/s`;
        } else {
            return `${(bytesPerSecond / (1024 * 1024)).toFixed(2)} MB/s`;
        }
    }
    
    /**
     * 格式化时间
     * @param {number} seconds - 秒数
     * @returns {string} 格式化后的时间
     */
    formatTime(seconds) {
        if (seconds < 60) {
            return `${seconds}秒`;
        } else if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            return `${minutes}分钟`;
        } else {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${hours}小时${minutes}分钟`;
        }
    }
    
    /**
     * 获取状态文本
     * @param {string} status - 状态
     * @returns {string} 状态文本
     */
    getStatusText(status) {
        const statusTexts = {
            'pending': '等待对方响应...',
            'accepted': '已接受',
            'rejected': '已拒绝',
            'connecting': '正在连接...',
            'transferring': '传输中...',
            'completed': '传输完成',
            'failed': '传输失败',
            'cancelled': '已取消',
            'expired': '已失效'
        };
        return statusTexts[status] || status;
    }
    
    /**
     * 销毁优化器
     */
    destroy() {
        if (this.intersectionObserver) {
            this.intersectionObserver.disconnect();
            this.intersectionObserver = null;
        }
        this.messageCache.clear();
        this.renderQueue = [];
        this.isRendering = false;
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.MessageRenderOptimizer = MessageRenderOptimizer;
}

// 导出供Node.js使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MessageRenderOptimizer;
}
