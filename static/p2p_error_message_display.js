/**
 * ErrorMessageDisplay - 处理P2P传输错误消息显示
 * 
 * 功能:
 * - 创建错误消息组件
 * - 实现不同错误类型的消息显示
 * - 添加错误图标和描述
 * - 提供错误恢复操作按钮
 * 
 */

class ErrorMessageDisplay {
    constructor() {
        this.errorMessages = this.initializeErrorMessages();
        this.activeErrors = new Map(); // 跟踪活跃的错误
        this.recoveryHandlers = new Map(); // 恢复处理器
    }

    /**
     * 初始化错误消息定义
     * @returns {Object} 错误消息映射
     */
    initializeErrorMessages() {
        return {
            CONNECTION_FAILED: {
                title: "连接失败",
                message: "无法建立P2P连接，正在重试...",
                icon: "🔌",
                severity: "error",
                actions: ["手动重试", "切换到常规传输"]
            },
            TRANSFER_INTERRUPTED: {
                title: "传输中断",
                message: "网络连接中断，支持断点续传",
                icon: "⏸️",
                severity: "warning",
                actions: ["继续传输", "重新开始"]
            },
            FILE_UNAVAILABLE: {
                title: "文件不可用",
                message: "发送方的文件已被删除或移动",
                icon: "❌",
                severity: "error",
                actions: ["联系发送方"]
            },
            SENDER_OFFLINE: {
                title: "发送方离线",
                message: "发送方已断开连接，文件暂时不可用",
                icon: "📴",
                severity: "warning",
                actions: ["稍后重试"]
            },
            NETWORK_TIMEOUT: {
                title: "网络超时",
                message: "网络连接不稳定，建议切换传输方式",
                icon: "⏱️",
                severity: "warning",
                actions: ["调整参数重试", "切换到常规传输"]
            },
            PERMISSION_DENIED: {
                title: "权限不足",
                message: "无法访问文件，请检查文件权限",
                icon: "🔒",
                severity: "error",
                actions: ["检查权限"]
            },
            BROWSER_INCOMPATIBLE: {
                title: "浏览器不兼容",
                message: "当前浏览器不支持P2P传输功能",
                icon: "🌐",
                severity: "error",
                actions: ["切换到常规传输", "更新浏览器"]
            },
            FIREWALL_BLOCKED: {
                title: "防火墙阻止",
                message: "防火墙或NAT限制导致无法建立连接",
                icon: "🛡️",
                severity: "error",
                actions: ["检查防火墙设置", "切换到常规传输"]
            },
            CHUNK_VERIFICATION_FAILED: {
                title: "数据校验失败",
                message: "传输的数据块校验失败，可能已损坏",
                icon: "⚠️",
                severity: "error",
                actions: ["重新传输", "切换到常规传输"]
            },
            UNKNOWN_ERROR: {
                title: "未知错误",
                message: "发生了未知错误，请稍后重试",
                icon: "❓",
                severity: "error",
                actions: ["重试", "联系支持"]
            }
        };
    }

    /**
     * 显示错误消息
     * @param {string} transferId - 传输ID
     * @param {string} errorType - 错误类型
     * @param {Object} options - 额外选项
     */
    showError(transferId, errorType, options = {}) {
        console.log(`[ErrorMessageDisplay] 显示错误: ${transferId}, type=${errorType}`);

        const errorConfig = this.errorMessages[errorType] || this.errorMessages.UNKNOWN_ERROR;
        
        // 合并自定义选项
        const config = {
            ...errorConfig,
            ...options
        };

        // 记录错误
        this.activeErrors.set(transferId, {
            type: errorType,
            config,
            timestamp: Date.now()
        });

        // 显示错误UI
        this.renderErrorMessage(transferId, config);
    }

    /**
     * 渲染错误消息
     * @param {string} transferId - 传输ID
     * @param {Object} config - 错误配置
     */
    renderErrorMessage(transferId, config) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[ErrorMessageDisplay] 找不到传输消息元素: ${transferId}`);
            return;
        }

        // 移除旧的错误消息
        const oldError = messageElement.querySelector('.error-message-container');
        if (oldError) {
            oldError.remove();
        }

        // 创建错误消息容器
        const errorContainer = document.createElement('div');
        errorContainer.className = `error-message-container severity-${config.severity}`;
        errorContainer.dataset.errorType = config.title;

        // 构建操作按钮HTML
        const actionsHTML = config.actions.map((action, index) => {
            return `<button class="error-action-btn" data-action="${action}" data-index="${index}">
                ${action}
            </button>`;
        }).join('');

        errorContainer.innerHTML = `
            <div class="error-message-content">
                <div class="error-header">
                    <div class="error-icon">${config.icon}</div>
                    <div class="error-title">${config.title}</div>
                </div>
                <div class="error-body">
                    <div class="error-description">${config.message}</div>
                    ${config.details ? `<div class="error-details">${config.details}</div>` : ''}
                </div>
                ${config.actions.length > 0 ? `
                    <div class="error-actions">
                        ${actionsHTML}
                    </div>
                ` : ''}
            </div>
        `;

        messageElement.appendChild(errorContainer);

        // 添加样式
        this.ensureStyles();

        // 绑定操作按钮事件
        this.bindActionButtons(transferId, errorContainer, config);

        // 添加动画
        setTimeout(() => {
            errorContainer.classList.add('show');
        }, 10);
    }

    /**
     * 确保样式已加载
     */
    ensureStyles() {
        if (document.getElementById('error-message-display-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'error-message-display-styles';
        style.textContent = `
            .error-message-container {
                margin-top: 12px;
                border-radius: 8px;
                overflow: hidden;
                opacity: 0;
                transform: translateY(-10px);
                transition: all 0.3s ease;
            }
            .error-message-container.show {
                opacity: 1;
                transform: translateY(0);
            }
            .error-message-container.severity-error {
                background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
                border: 2px solid #dc3545;
            }
            .error-message-container.severity-warning {
                background: linear-gradient(135deg, #fff3cd 0%, #ffe8a1 100%);
                border: 2px solid #ffc107;
            }
            .error-message-container.severity-info {
                background: linear-gradient(135deg, #d1ecf1 0%, #bee5eb 100%);
                border: 2px solid #17a2b8;
            }
            .error-message-content {
                padding: 16px;
            }
            .error-header {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 12px;
            }
            .error-icon {
                font-size: 32px;
                line-height: 1;
            }
            .error-title {
                font-size: 16px;
                font-weight: 600;
                color: #212529;
            }
            .severity-error .error-title {
                color: #721c24;
            }
            .severity-warning .error-title {
                color: #856404;
            }
            .severity-info .error-title {
                color: #0c5460;
            }
            .error-body {
                margin-bottom: 16px;
            }
            .error-description {
                font-size: 14px;
                line-height: 1.5;
                margin-bottom: 8px;
            }
            .severity-error .error-description {
                color: #721c24;
            }
            .severity-warning .error-description {
                color: #856404;
            }
            .severity-info .error-description {
                color: #0c5460;
            }
            .error-details {
                font-size: 13px;
                padding: 8px 12px;
                background-color: rgba(0, 0, 0, 0.05);
                border-radius: 4px;
                margin-top: 8px;
            }
            .error-actions {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .error-action-btn {
                padding: 8px 16px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
                background-color: #fff;
                color: #212529;
                border: 1px solid #dee2e6;
            }
            .error-action-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }
            .error-action-btn:active {
                transform: translateY(0);
            }
            .severity-error .error-action-btn:first-child {
                background-color: #dc3545;
                color: white;
                border-color: #dc3545;
            }
            .severity-error .error-action-btn:first-child:hover {
                background-color: #c82333;
            }
            .severity-warning .error-action-btn:first-child {
                background-color: #ffc107;
                color: #212529;
                border-color: #ffc107;
            }
            .severity-warning .error-action-btn:first-child:hover {
                background-color: #e0a800;
            }
            .error-dismiss-btn {
                position: absolute;
                top: 8px;
                right: 8px;
                width: 24px;
                height: 24px;
                border: none;
                background: none;
                cursor: pointer;
                font-size: 18px;
                color: #6c757d;
                padding: 0;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .error-dismiss-btn:hover {
                color: #212529;
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * 绑定操作按钮事件
     * @param {string} transferId - 传输ID
     * @param {HTMLElement} errorContainer - 错误容器
     * @param {Object} config - 错误配置
     */
    bindActionButtons(transferId, errorContainer, config) {
        const actionButtons = errorContainer.querySelectorAll('.error-action-btn');
        
        actionButtons.forEach((button, index) => {
            button.addEventListener('click', () => {
                const action = button.dataset.action;
                console.log(`[ErrorMessageDisplay] 用户点击操作: ${action}`);
                this.handleActionClick(transferId, action, index, config);
            });
        });
    }

    /**
     * 处理操作按钮点击
     * @param {string} transferId - 传输ID
     * @param {string} action - 操作名称
     * @param {number} index - 操作索引
     * @param {Object} config - 错误配置
     */
    handleActionClick(transferId, action, index, config) {
        // 调用注册的恢复处理器
        const handler = this.recoveryHandlers.get(transferId);
        if (handler) {
            try {
                handler(action, index);
            } catch (error) {
                console.error(`[ErrorMessageDisplay] 恢复处理器执行失败:`, error);
            }
        }

        // 触发操作事件
        const event = new CustomEvent('p2p-error-action', {
            detail: {
                transferId,
                action,
                index,
                errorType: config.title
            }
        });
        document.dispatchEvent(event);

        // 根据操作类型执行默认行为
        this.executeDefaultAction(transferId, action);
    }

    /**
     * 执行默认操作
     * @param {string} transferId - 传输ID
     * @param {string} action - 操作名称
     */
    executeDefaultAction(transferId, action) {
        switch (action) {
            case '手动重试':
            case '重试':
                this.triggerRetry(transferId);
                break;
            case '切换到常规传输':
                this.triggerDegradation(transferId);
                break;
            case '继续传输':
                this.triggerResume(transferId);
                break;
            case '重新开始':
                this.triggerRestart(transferId);
                break;
            case '稍后重试':
                this.dismissError(transferId);
                break;
            default:
                console.log(`[ErrorMessageDisplay] 未知操作: ${action}`);
        }
    }

    /**
     * 触发重试
     * @param {string} transferId - 传输ID
     */
    triggerRetry(transferId) {
        const event = new CustomEvent('p2p-retry-requested', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
        this.dismissError(transferId);
    }

    /**
     * 触发降级
     * @param {string} transferId - 传输ID
     */
    triggerDegradation(transferId) {
        const event = new CustomEvent('p2p-degradation-requested', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
    }

    /**
     * 触发恢复
     * @param {string} transferId - 传输ID
     */
    triggerResume(transferId) {
        const event = new CustomEvent('p2p-transfer-resume', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
        this.dismissError(transferId);
    }

    /**
     * 触发重新开始
     * @param {string} transferId - 传输ID
     */
    triggerRestart(transferId) {
        const event = new CustomEvent('p2p-transfer-restart', {
            detail: { transferId }
        });
        document.dispatchEvent(event);
        this.dismissError(transferId);
    }

    /**
     * 关闭错误消息
     * @param {string} transferId - 传输ID
     */
    dismissError(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const errorContainer = messageElement.querySelector('.error-message-container');
        if (errorContainer) {
            errorContainer.classList.remove('show');
            setTimeout(() => {
                errorContainer.remove();
            }, 300);
        }

        this.activeErrors.delete(transferId);
    }

    /**
     * 更新错误消息
     * @param {string} transferId - 传输ID
     * @param {Object} updates - 更新内容
     */
    updateError(transferId, updates) {
        const error = this.activeErrors.get(transferId);
        if (!error) return;

        const newConfig = {
            ...error.config,
            ...updates
        };

        this.activeErrors.set(transferId, {
            ...error,
            config: newConfig
        });

        this.renderErrorMessage(transferId, newConfig);
    }

    /**
     * 注册恢复处理器
     * @param {string} transferId - 传输ID
     * @param {Function} handler - 处理器函数
     */
    registerRecoveryHandler(transferId, handler) {
        this.recoveryHandlers.set(transferId, handler);
    }

    /**
     * 注销恢复处理器
     * @param {string} transferId - 传输ID
     */
    unregisterRecoveryHandler(transferId) {
        this.recoveryHandlers.delete(transferId);
    }

    /**
     * 检查是否有活跃错误
     * @param {string} transferId - 传输ID
     * @returns {boolean}
     */
    hasActiveError(transferId) {
        return this.activeErrors.has(transferId);
    }

    /**
     * 获取错误信息
     * @param {string} transferId - 传输ID
     * @returns {Object|null}
     */
    getError(transferId) {
        return this.activeErrors.get(transferId) || null;
    }

    /**
     * 清理错误信息
     * @param {string} transferId - 传输ID
     */
    clearError(transferId) {
        this.dismissError(transferId);
        this.recoveryHandlers.delete(transferId);
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.activeErrors.clear();
        this.recoveryHandlers.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.ErrorMessageDisplay = ErrorMessageDisplay;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ErrorMessageDisplay;
}
