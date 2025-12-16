/**
 * ConnectionErrorHandler - 处理P2P连接失败和重试逻辑
 * 
 * 功能:
 * - 自动重试连接（最多3次）
 * - 递增延迟机制（1秒、3秒、5秒）
 * - 显示重试进度和状态
 * - 提供降级到常规传输的选项
 * 
 */

class ConnectionErrorHandler {
    constructor() {
        this.maxRetries = 3;
        this.retryDelays = [1000, 3000, 5000]; // 递增延迟：1秒、3秒、5秒
        this.activeRetries = new Map(); // 跟踪活跃的重试
        this.retryCallbacks = new Map(); // 重试回调函数
    }

    /**
     * 处理连接失败
     * @param {string} transferId - 传输ID
     * @param {number} attempt - 当前重试次数（从0开始）
     * @param {Function} retryFunction - 重试时调用的函数
     * @returns {Promise<boolean>} - 是否成功连接
     */
    async handleConnectionFailure(transferId, attempt = 0, retryFunction) {
        console.log(`[ConnectionErrorHandler] 处理连接失败: transferId=${transferId}, attempt=${attempt}`);

        // 检查是否达到最大重试次数
        if (attempt >= this.maxRetries) {
            console.log(`[ConnectionErrorHandler] 达到最大重试次数 (${this.maxRetries})`);
            this.showDegradationOptions(transferId);
            this.activeRetries.delete(transferId);
            return false;
        }

        // 记录活跃重试
        this.activeRetries.set(transferId, {
            attempt: attempt + 1,
            maxRetries: this.maxRetries,
            startTime: Date.now()
        });

        // 更新UI显示重试信息
        this.updateRetryStatus(transferId, attempt + 1);

        // 等待延迟后重试
        const delay = this.retryDelays[attempt];
        console.log(`[ConnectionErrorHandler] 等待 ${delay}ms 后重试...`);
        await this.delay(delay);

        try {
            // 执行重试
            console.log(`[ConnectionErrorHandler] 执行第 ${attempt + 1} 次重试`);
            const success = await retryFunction();
            
            if (success) {
                console.log(`[ConnectionErrorHandler] 重试成功`);
                this.activeRetries.delete(transferId);
                this.updateRetrySuccess(transferId);
                return true;
            } else {
                // 重试失败，继续下一次重试
                console.log(`[ConnectionErrorHandler] 重试失败，继续下一次重试`);
                return await this.handleConnectionFailure(transferId, attempt + 1, retryFunction);
            }
        } catch (error) {
            console.error(`[ConnectionErrorHandler] 重试过程中发生错误:`, error);
            // 重试失败，继续下一次重试
            return await this.handleConnectionFailure(transferId, attempt + 1, retryFunction);
        }
    }

    /**
     * 更新重试状态显示
     * @param {string} transferId - 传输ID
     * @param {number} attempt - 当前重试次数
     */
    updateRetryStatus(transferId, attempt) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[ConnectionErrorHandler] 找不到传输消息元素: ${transferId}`);
            return;
        }

        // 查找或创建状态显示区域
        let statusArea = messageElement.querySelector('.retry-status');
        if (!statusArea) {
            statusArea = document.createElement('div');
            statusArea.className = 'retry-status';
            messageElement.appendChild(statusArea);
        }

        // 更新状态文本
        statusArea.innerHTML = `
            <div class="retry-info">
                <div class="retry-icon">🔄</div>
                <div class="retry-text">
                    正在重试连接... (${attempt}/${this.maxRetries})
                </div>
                <div class="retry-progress">
                    <div class="retry-progress-bar" style="width: ${(attempt / this.maxRetries) * 100}%"></div>
                </div>
            </div>
        `;

        // 添加样式
        if (!document.getElementById('retry-status-styles')) {
            const style = document.createElement('style');
            style.id = 'retry-status-styles';
            style.textContent = `
                .retry-status {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #fff3cd;
                    border-radius: 8px;
                    border: 1px solid #ffc107;
                }
                .retry-info {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }
                .retry-icon {
                    font-size: 24px;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                .retry-text {
                    font-size: 14px;
                    color: #856404;
                    font-weight: 500;
                }
                .retry-progress {
                    width: 100%;
                    height: 6px;
                    background-color: #fff;
                    border-radius: 3px;
                    overflow: hidden;
                }
                .retry-progress-bar {
                    height: 100%;
                    background: linear-gradient(90deg, #ffc107 0%, #ff9800 100%);
                    transition: width 0.3s ease;
                }
            `;
            document.head.appendChild(style);
        }
    }

    /**
     * 更新重试成功状态
     * @param {string} transferId - 传输ID
     */
    updateRetrySuccess(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const statusArea = messageElement.querySelector('.retry-status');
        if (statusArea) {
            statusArea.innerHTML = `
                <div class="retry-success">
                    <div class="success-icon">✅</div>
                    <div class="success-text">连接成功！</div>
                </div>
            `;

            // 2秒后移除成功消息
            setTimeout(() => {
                if (statusArea && statusArea.parentNode) {
                    statusArea.remove();
                }
            }, 2000);
        }
    }

    /**
     * 显示降级选项
     * @param {string} transferId - 传输ID
     */
    showDegradationOptions(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[ConnectionErrorHandler] 找不到传输消息元素: ${transferId}`);
            return;
        }

        // 移除重试状态
        const retryStatus = messageElement.querySelector('.retry-status');
        if (retryStatus) {
            retryStatus.remove();
        }

        // 创建降级选项UI
        const degradationUI = document.createElement('div');
        degradationUI.className = 'degradation-options';
        degradationUI.innerHTML = `
            <div class="error-message">
                <div class="error-icon">⚠️</div>
                <div class="error-text">P2P连接失败，已重试${this.maxRetries}次</div>
                <div class="error-actions">
                    <button class="retry-p2p-btn" data-transfer-id="${transferId}">
                        再次尝试P2P
                    </button>
                    <button class="switch-regular-btn" data-transfer-id="${transferId}">
                        切换到常规传输
                    </button>
                </div>
            </div>
        `;

        messageElement.appendChild(degradationUI);

        // 添加样式
        if (!document.getElementById('degradation-options-styles')) {
            const style = document.createElement('style');
            style.id = 'degradation-options-styles';
            style.textContent = `
                .degradation-options {
                    margin-top: 12px;
                }
                .error-message {
                    padding: 16px;
                    background-color: #f8d7da;
                    border: 1px solid #f5c6cb;
                    border-radius: 8px;
                }
                .error-icon {
                    font-size: 32px;
                    margin-bottom: 8px;
                }
                .error-text {
                    font-size: 14px;
                    color: #721c24;
                    margin-bottom: 12px;
                    font-weight: 500;
                }
                .error-actions {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .retry-p2p-btn, .switch-regular-btn {
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }
                .retry-p2p-btn {
                    background-color: #007bff;
                    color: white;
                }
                .retry-p2p-btn:hover {
                    background-color: #0056b3;
                }
                .switch-regular-btn {
                    background-color: #28a745;
                    color: white;
                }
                .switch-regular-btn:hover {
                    background-color: #218838;
                }
                .retry-success {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px;
                    background-color: #d4edda;
                    border-radius: 6px;
                }
                .success-icon {
                    font-size: 20px;
                }
                .success-text {
                    font-size: 14px;
                    color: #155724;
                    font-weight: 500;
                }
            `;
            document.head.appendChild(style);
        }

        // 绑定事件监听器
        this.bindDegradationEvents(transferId);
    }

    /**
     * 绑定降级选项事件
     * @param {string} transferId - 传输ID
     */
    bindDegradationEvents(transferId) {
        // 再次尝试P2P按钮
        const retryBtn = document.querySelector(`.retry-p2p-btn[data-transfer-id="${transferId}"]`);
        if (retryBtn) {
            retryBtn.addEventListener('click', () => {
                console.log(`[ConnectionErrorHandler] 用户选择再次尝试P2P: ${transferId}`);
                this.onRetryP2P(transferId);
            });
        }

        // 切换到常规传输按钮
        const switchBtn = document.querySelector(`.switch-regular-btn[data-transfer-id="${transferId}"]`);
        if (switchBtn) {
            switchBtn.addEventListener('click', () => {
                console.log(`[ConnectionErrorHandler] 用户选择切换到常规传输: ${transferId}`);
                this.onSwitchToRegular(transferId);
            });
        }
    }

    /**
     * 处理用户选择再次尝试P2P
     * @param {string} transferId - 传输ID
     */
    onRetryP2P(transferId) {
        // 移除降级选项UI
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (messageElement) {
            const degradationUI = messageElement.querySelector('.degradation-options');
            if (degradationUI) {
                degradationUI.remove();
            }
        }

        // 触发重试回调
        const callback = this.retryCallbacks.get(transferId);
        if (callback) {
            callback();
        } else {
            console.warn(`[ConnectionErrorHandler] 没有找到重试回调: ${transferId}`);
        }
    }

    /**
     * 处理用户选择切换到常规传输
     * @param {string} transferId - 传输ID
     */
    onSwitchToRegular(transferId) {
        // 触发降级事件
        const event = new CustomEvent('p2p-degradation-requested', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
    }

    /**
     * 注册重试回调
     * @param {string} transferId - 传输ID
     * @param {Function} callback - 回调函数
     */
    registerRetryCallback(transferId, callback) {
        this.retryCallbacks.set(transferId, callback);
    }

    /**
     * 注销重试回调
     * @param {string} transferId - 传输ID
     */
    unregisterRetryCallback(transferId) {
        this.retryCallbacks.delete(transferId);
    }

    /**
     * 取消重试
     * @param {string} transferId - 传输ID
     */
    cancelRetry(transferId) {
        this.activeRetries.delete(transferId);
        this.retryCallbacks.delete(transferId);

        // 移除UI
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (messageElement) {
            const retryStatus = messageElement.querySelector('.retry-status');
            if (retryStatus) {
                retryStatus.remove();
            }
        }
    }

    /**
     * 获取活跃重试信息
     * @param {string} transferId - 传输ID
     * @returns {Object|null} - 重试信息
     */
    getRetryInfo(transferId) {
        return this.activeRetries.get(transferId) || null;
    }

    /**
     * 延迟函数
     * @param {number} ms - 延迟毫秒数
     * @returns {Promise}
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.activeRetries.clear();
        this.retryCallbacks.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.ConnectionErrorHandler = ConnectionErrorHandler;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ConnectionErrorHandler;
}
