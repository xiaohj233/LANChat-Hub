/**
 * DegradationHandler - 处理P2P传输降级到常规传输
 * 
 * 功能:
 * - 提供降级到常规传输的选项UI
 * - 实现传输方式切换逻辑
 * - 提供用户选择界面
 * - 通过服务器中转完成文件传输
 * 
 */

class DegradationHandler {
    constructor() {
        this.degradedTransfers = new Map(); // 跟踪已降级的传输
        this.degradationCallbacks = new Map(); // 降级回调函数
    }

    /**
     * 显示降级选项
     * @param {string} transferId - 传输ID
     * @param {string} reason - 降级原因
     */
    showDegradationOption(transferId, reason = 'connection_failed') {
        console.log(`[DegradationHandler] 显示降级选项: transferId=${transferId}, reason=${reason}`);

        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[DegradationHandler] 找不到传输消息元素: ${transferId}`);
            return;
        }

        // 创建降级选项UI
        let degradationUI = messageElement.querySelector('.degradation-ui');
        if (!degradationUI) {
            degradationUI = document.createElement('div');
            degradationUI.className = 'degradation-ui';
            messageElement.appendChild(degradationUI);
        }

        const reasonText = this.getReasonText(reason);

        degradationUI.innerHTML = `
            <div class="degradation-prompt">
                <div class="degradation-icon">⚠️</div>
                <div class="degradation-message">
                    <div class="degradation-title">P2P传输遇到问题</div>
                    <div class="degradation-reason">${reasonText}</div>
                    <div class="degradation-suggestion">
                        建议切换到常规传输（通过服务器中转）
                    </div>
                </div>
                <div class="degradation-actions">
                    <button class="switch-to-regular-btn" data-transfer-id="${transferId}">
                        切换到常规传输
                    </button>
                    <button class="keep-p2p-btn" data-transfer-id="${transferId}">
                        继续尝试P2P
                    </button>
                </div>
            </div>
        `;

        // 添加样式
        if (!document.getElementById('degradation-ui-styles')) {
            const style = document.createElement('style');
            style.id = 'degradation-ui-styles';
            style.textContent = `
                .degradation-ui {
                    margin-top: 12px;
                }
                .degradation-prompt {
                    padding: 16px;
                    background: linear-gradient(135deg, #fff3cd 0%, #ffe8a1 100%);
                    border: 2px solid #ffc107;
                    border-radius: 8px;
                }
                .degradation-icon {
                    font-size: 32px;
                    margin-bottom: 12px;
                }
                .degradation-message {
                    margin-bottom: 16px;
                }
                .degradation-title {
                    font-size: 16px;
                    font-weight: 600;
                    color: #856404;
                    margin-bottom: 8px;
                }
                .degradation-reason {
                    font-size: 14px;
                    color: #856404;
                    margin-bottom: 8px;
                }
                .degradation-suggestion {
                    font-size: 13px;
                    color: #856404;
                    font-style: italic;
                }
                .degradation-actions {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .switch-to-regular-btn, .keep-p2p-btn {
                    padding: 10px 20px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }
                .switch-to-regular-btn {
                    background-color: #28a745;
                    color: white;
                    flex: 1;
                }
                .switch-to-regular-btn:hover {
                    background-color: #218838;
                    transform: translateY(-1px);
                    box-shadow: 0 2px 8px rgba(40, 167, 69, 0.3);
                }
                .keep-p2p-btn {
                    background-color: #6c757d;
                    color: white;
                }
                .keep-p2p-btn:hover {
                    background-color: #5a6268;
                }
                .degradation-progress {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #d1ecf1;
                    border: 1px solid #bee5eb;
                    border-radius: 6px;
                }
                .degradation-progress-icon {
                    font-size: 20px;
                    margin-bottom: 8px;
                }
                .degradation-progress-text {
                    font-size: 14px;
                    color: #0c5460;
                }
            `;
            document.head.appendChild(style);
        }

        // 绑定事件监听器
        this.bindDegradationEvents(transferId);
    }

    /**
     * 获取降级原因文本
     * @param {string} reason - 原因代码
     * @returns {string} - 原因文本
     */
    getReasonText(reason) {
        const reasons = {
            'connection_failed': 'P2P连接失败，无法建立直接连接',
            'network_unstable': '网络不稳定，传输速度过慢',
            'timeout': '连接超时，无法完成传输',
            'peer_offline': '对方已离线，无法继续P2P传输',
            'firewall': '防火墙或NAT限制，无法穿透',
            'browser_incompatible': '浏览器不支持P2P传输功能'
        };
        return reasons[reason] || '未知原因导致P2P传输失败';
    }

    /**
     * 绑定降级选项事件
     * @param {string} transferId - 传输ID
     */
    bindDegradationEvents(transferId) {
        // 切换到常规传输按钮
        const switchBtn = document.querySelector(`.switch-to-regular-btn[data-transfer-id="${transferId}"]`);
        if (switchBtn) {
            switchBtn.addEventListener('click', async () => {
                console.log(`[DegradationHandler] 用户选择切换到常规传输: ${transferId}`);
                await this.switchToRegularTransfer(transferId);
            });
        }

        // 继续尝试P2P按钮
        const keepBtn = document.querySelector(`.keep-p2p-btn[data-transfer-id="${transferId}"]`);
        if (keepBtn) {
            keepBtn.addEventListener('click', () => {
                console.log(`[DegradationHandler] 用户选择继续尝试P2P: ${transferId}`);
                this.keepP2PTransfer(transferId);
            });
        }
    }

    /**
     * 切换到常规传输
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async switchToRegularTransfer(transferId) {
        console.log(`[DegradationHandler] 开始切换到常规传输: ${transferId}`);

        // 显示切换进度
        this.showSwitchingProgress(transferId);

        try {
            // 通知服务器切换传输方式
            const response = await fetch(`/api/p2p/switch-to-regular`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    transferId,
                    reason: 'user_requested'
                })
            });

            if (!response.ok) {
                throw new Error(`切换失败: ${response.status}`);
            }

            const result = await response.json();
            console.log(`[DegradationHandler] 切换成功:`, result);

            // 标记为已降级
            this.degradedTransfers.set(transferId, {
                originalMethod: 'p2p',
                newMethod: 'regular',
                switchTime: Date.now()
            });

            // 更新UI
            this.showSwitchSuccess(transferId);

            // 触发降级事件
            const event = new CustomEvent('p2p-degraded', {
                detail: {
                    transferId,
                    newMethod: 'regular',
                    uploadUrl: result.uploadUrl
                }
            });
            document.dispatchEvent(event);

            // 开始常规传输
            await this.startRegularTransfer(transferId, result.uploadUrl);

        } catch (error) {
            console.error(`[DegradationHandler] 切换失败:`, error);
            this.showSwitchError(transferId, error.message);
        }
    }

    /**
     * 显示切换进度
     * @param {string} transferId - 传输ID
     */
    showSwitchingProgress(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const degradationUI = messageElement.querySelector('.degradation-ui');
        if (degradationUI) {
            degradationUI.innerHTML = `
                <div class="degradation-progress">
                    <div class="degradation-progress-icon">🔄</div>
                    <div class="degradation-progress-text">
                        正在切换到常规传输...
                    </div>
                </div>
            `;
        }
    }

    /**
     * 显示切换成功
     * @param {string} transferId - 传输ID
     */
    showSwitchSuccess(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const degradationUI = messageElement.querySelector('.degradation-ui');
        if (degradationUI) {
            degradationUI.innerHTML = `
                <div class="degradation-progress">
                    <div class="degradation-progress-icon">✅</div>
                    <div class="degradation-progress-text">
                        已切换到常规传输，正在上传文件...
                    </div>
                </div>
            `;

            // 3秒后移除提示
            setTimeout(() => {
                if (degradationUI && degradationUI.parentNode) {
                    degradationUI.remove();
                }
            }, 3000);
        }
    }

    /**
     * 显示切换错误
     * @param {string} transferId - 传输ID
     * @param {string} errorMessage - 错误消息
     */
    showSwitchError(transferId, errorMessage) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const degradationUI = messageElement.querySelector('.degradation-ui');
        if (degradationUI) {
            degradationUI.innerHTML = `
                <div class="degradation-error">
                    <div class="error-icon">❌</div>
                    <div class="error-text">
                        切换失败: ${errorMessage}
                    </div>
                    <button class="retry-switch-btn" data-transfer-id="${transferId}">
                        重试
                    </button>
                </div>
            `;

            // 绑定重试按钮
            const retryBtn = degradationUI.querySelector('.retry-switch-btn');
            if (retryBtn) {
                retryBtn.addEventListener('click', async () => {
                    await this.switchToRegularTransfer(transferId);
                });
            }
        }
    }

    /**
     * 开始常规传输
     * @param {string} transferId - 传输ID
     * @param {string} uploadUrl - 上传URL
     * @returns {Promise<void>}
     */
    async startRegularTransfer(transferId, uploadUrl) {
        console.log(`[DegradationHandler] 开始常规传输: ${transferId}`);

        // 触发常规传输开始事件
        const event = new CustomEvent('regular-transfer-start', {
            detail: {
                transferId,
                uploadUrl
            }
        });
        document.dispatchEvent(event);
    }

    /**
     * 继续尝试P2P传输
     * @param {string} transferId - 传输ID
     */
    keepP2PTransfer(transferId) {
        console.log(`[DegradationHandler] 用户选择继续尝试P2P: ${transferId}`);

        // 移除降级UI
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (messageElement) {
            const degradationUI = messageElement.querySelector('.degradation-ui');
            if (degradationUI) {
                degradationUI.remove();
            }
        }

        // 触发继续P2P事件
        const event = new CustomEvent('p2p-continue-requested', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
    }

    /**
     * 检查传输是否已降级
     * @param {string} transferId - 传输ID
     * @returns {boolean}
     */
    isDegraded(transferId) {
        return this.degradedTransfers.has(transferId);
    }

    /**
     * 获取降级信息
     * @param {string} transferId - 传输ID
     * @returns {Object|null}
     */
    getDegradationInfo(transferId) {
        return this.degradedTransfers.get(transferId) || null;
    }

    /**
     * 注册降级回调
     * @param {string} transferId - 传输ID
     * @param {Function} callback - 回调函数
     */
    registerDegradationCallback(transferId, callback) {
        this.degradationCallbacks.set(transferId, callback);
    }

    /**
     * 注销降级回调
     * @param {string} transferId - 传输ID
     */
    unregisterDegradationCallback(transferId) {
        this.degradationCallbacks.delete(transferId);
    }

    /**
     * 清理降级信息
     * @param {string} transferId - 传输ID
     */
    clearDegradation(transferId) {
        this.degradedTransfers.delete(transferId);
        this.degradationCallbacks.delete(transferId);

        // 移除UI
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (messageElement) {
            const degradationUI = messageElement.querySelector('.degradation-ui');
            if (degradationUI) {
                degradationUI.remove();
            }
        }
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.degradedTransfers.clear();
        this.degradationCallbacks.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.DegradationHandler = DegradationHandler;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DegradationHandler;
}
