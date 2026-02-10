/**
 * TransferCancellation - 处理P2P传输取消功能
 * 
 * 功能:
 * - 添加取消传输按钮
 * - 实现取消传输逻辑
 * - 释放传输相关资源
 * - 更新数据库取消状态
 * 
 */

class TransferCancellation {
    constructor() {
        this.cancelledTransfers = new Set(); // 跟踪已取消的传输
        this.cancelCallbacks = new Map(); // 取消回调函数
        this.resourceCleanupHandlers = new Map(); // 资源清理处理器
    }

    /**
     * 添加取消按钮到传输消息
     * @param {string} transferId - 传输ID
     * @param {HTMLElement} messageElement - 消息元素
     */
    addCancelButton(transferId, messageElement) {
        // 检查是否已经有取消按钮
        if (messageElement.querySelector('.cancel-transfer-btn')) {
            return;
        }

        // 查找操作按钮区域
        let actionsArea = messageElement.querySelector('.transfer-actions');
        if (!actionsArea) {
            actionsArea = document.createElement('div');
            actionsArea.className = 'transfer-actions';
            messageElement.appendChild(actionsArea);
        }

        // 创建取消按钮
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-transfer-btn';
        cancelBtn.dataset.transferId = transferId;
        cancelBtn.innerHTML = `
            <span class="cancel-icon">🚫</span>
            <span class="cancel-text">取消传输</span>
        `;

        actionsArea.appendChild(cancelBtn);

        // 添加样式
        if (!document.getElementById('cancel-transfer-styles')) {
            const style = document.createElement('style');
            style.id = 'cancel-transfer-styles';
            style.textContent = `
                .transfer-actions {
                    margin-top: 12px;
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .cancel-transfer-btn {
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    background-color: #dc3545;
                    color: white;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.2s ease;
                }
                .cancel-transfer-btn:hover {
                    background-color: #c82333;
                    transform: translateY(-1px);
                    box-shadow: 0 2px 8px rgba(220, 53, 69, 0.3);
                }
                .cancel-transfer-btn:active {
                    transform: translateY(0);
                }
                .cancel-transfer-btn:disabled {
                    background-color: #6c757d;
                    cursor: not-allowed;
                    transform: none;
                }
                .cancel-icon {
                    font-size: 16px;
                }
                .cancel-text {
                    font-size: 14px;
                }
                .cancelling-status {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #f8d7da;
                    border: 1px solid #f5c6cb;
                    border-radius: 6px;
                }
                .cancelling-info {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .cancelling-icon {
                    font-size: 20px;
                }
                .cancelling-text {
                    font-size: 14px;
                    color: #721c24;
                    font-weight: 500;
                }
                .cancelled-status {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #e2e3e5;
                    border: 1px solid #d6d8db;
                    border-radius: 6px;
                }
                .cancelled-info {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .cancelled-icon {
                    font-size: 20px;
                }
                .cancelled-text {
                    font-size: 14px;
                    color: #383d41;
                }
            `;
            document.head.appendChild(style);
        }

        // 绑定点击事件
        cancelBtn.addEventListener('click', () => {
            this.confirmAndCancel(transferId);
        });
    }

    /**
     * 确认并取消传输
     * @param {string} transferId - 传输ID
     */
    confirmAndCancel(transferId) {
        // 显示确认对话框
        const confirmed = confirm('确定要取消这个传输吗？取消后无法恢复。');
        if (!confirmed) {
            console.log(`[TransferCancellation] 用户取消了取消操作: ${transferId}`);
            return;
        }

        console.log(`[TransferCancellation] 用户确认取消传输: ${transferId}`);
        this.cancelTransfer(transferId);
    }

    /**
     * 取消传输
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async cancelTransfer(transferId) {
        console.log(`[TransferCancellation] 开始取消传输: ${transferId}`);

        // 标记为已取消
        this.cancelledTransfers.add(transferId);

        // 更新UI显示取消中状态
        this.showCancellingStatus(transferId);

        try {
            // 1. 停止传输并释放资源
            await this.stopTransferAndReleaseResources(transferId);

            // 2. 更新数据库状态
            await this.updateDatabaseStatus(transferId);

            // 3. 通知对方（通过取消通知机制）
            await this.notifyPeer(transferId);

            // 4. 更新UI显示已取消状态
            this.showCancelledStatus(transferId);

            // 5. 触发取消事件
            this.triggerCancelEvent(transferId);

            console.log(`[TransferCancellation] 传输已成功取消: ${transferId}`);

        } catch (error) {
            console.error(`[TransferCancellation] 取消传输失败:`, error);
            this.showCancelError(transferId, error.message);
        }
    }

    /**
     * 停止传输并释放资源
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async stopTransferAndReleaseResources(transferId) {
        console.log(`[TransferCancellation] 停止传输并释放资源: ${transferId}`);

        // 调用注册的资源清理处理器
        const cleanupHandler = this.resourceCleanupHandlers.get(transferId);
        if (cleanupHandler) {
            try {
                await cleanupHandler();
                console.log(`[TransferCancellation] 资源清理完成: ${transferId}`);
            } catch (error) {
                console.error(`[TransferCancellation] 资源清理失败:`, error);
            }
        }

        // 触发资源释放事件
        const event = new CustomEvent('p2p-transfer-resources-release', {
            detail: { transferId }
        });
        document.dispatchEvent(event);

        // 清理本地状态
        this.resourceCleanupHandlers.delete(transferId);
    }

    /**
     * 更新数据库状态
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async updateDatabaseStatus(transferId) {
        console.log(`[TransferCancellation] 更新数据库状态: ${transferId}`);

        try {
            const response = await fetch(`/api/p2p/messages/${transferId}/status`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    status: 'cancelled',
                    cancelTime: Date.now(),
                    cancelReason: 'user_requested'
                })
            });

            if (!response.ok) {
                throw new Error(`更新数据库失败: ${response.status}`);
            }

            console.log(`[TransferCancellation] 数据库状态已更新: ${transferId}`);
        } catch (error) {
            console.error(`[TransferCancellation] 更新数据库失败:`, error);
            throw error;
        }
    }

    /**
     * 通知对方传输已取消
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async notifyPeer(transferId) {
        console.log(`[TransferCancellation] 通知对方传输已取消: ${transferId}`);

        // 触发取消通知事件（由取消通知机制处理）
        const event = new CustomEvent('p2p-transfer-cancelled', {
            detail: {
                transferId,
                cancelTime: Date.now(),
                cancelReason: 'user_requested'
            }
        });
        document.dispatchEvent(event);
    }

    /**
     * 显示取消中状态
     * @param {string} transferId - 传输ID
     */
    showCancellingStatus(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        // 禁用取消按钮
        const cancelBtn = messageElement.querySelector('.cancel-transfer-btn');
        if (cancelBtn) {
            cancelBtn.disabled = true;
            cancelBtn.innerHTML = `
                <span class="cancel-icon">⏳</span>
                <span class="cancel-text">取消中...</span>
            `;
        }

        // 添加取消中状态提示
        let statusArea = messageElement.querySelector('.cancelling-status');
        if (!statusArea) {
            statusArea = document.createElement('div');
            statusArea.className = 'cancelling-status';
            messageElement.appendChild(statusArea);
        }

        statusArea.innerHTML = `
            <div class="cancelling-info">
                <div class="cancelling-icon">⏳</div>
                <div class="cancelling-text">正在取消传输...</div>
            </div>
        `;
    }

    /**
     * 显示已取消状态
     * @param {string} transferId - 传输ID
     */
    showCancelledStatus(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        // 移除取消中状态
        const cancellingStatus = messageElement.querySelector('.cancelling-status');
        if (cancellingStatus) {
            cancellingStatus.remove();
        }

        // 移除取消按钮
        const cancelBtn = messageElement.querySelector('.cancel-transfer-btn');
        if (cancelBtn) {
            cancelBtn.remove();
        }

        // 添加已取消状态
        let statusArea = messageElement.querySelector('.cancelled-status');
        if (!statusArea) {
            statusArea = document.createElement('div');
            statusArea.className = 'cancelled-status';
            messageElement.appendChild(statusArea);
        }

        const cancelTime = new Date().toLocaleString('zh-CN');
        statusArea.innerHTML = `
            <div class="cancelled-info">
                <div class="cancelled-icon">🚫</div>
                <div class="cancelled-text">
                    传输已取消 - ${cancelTime}
                </div>
            </div>
        `;

        // 更新消息样式
        messageElement.classList.add('transfer-cancelled');
        messageElement.style.opacity = '0.7';
    }

    /**
     * 显示取消错误
     * @param {string} transferId - 传输ID
     * @param {string} errorMessage - 错误消息
     */
    showCancelError(transferId, errorMessage) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        // 移除取消中状态
        const cancellingStatus = messageElement.querySelector('.cancelling-status');
        if (cancellingStatus) {
            cancellingStatus.remove();
        }

        // 恢复取消按钮
        const cancelBtn = messageElement.querySelector('.cancel-transfer-btn');
        if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = `
                <span class="cancel-icon">🚫</span>
                <span class="cancel-text">取消传输</span>
            `;
        }

        // 显示错误消息
        alert(`取消传输失败: ${errorMessage}`);
    }

    /**
     * 触发取消事件
     * @param {string} transferId - 传输ID
     */
    triggerCancelEvent(transferId) {
        // 调用注册的取消回调
        const callback = this.cancelCallbacks.get(transferId);
        if (callback) {
            try {
                callback();
            } catch (error) {
                console.error(`[TransferCancellation] 取消回调执行失败:`, error);
            }
        }

        // 触发全局取消事件
        const event = new CustomEvent('p2p-transfer-cancel-complete', {
            detail: {
                transferId,
                cancelTime: Date.now()
            }
        });
        document.dispatchEvent(event);
    }

    /**
     * 注册资源清理处理器
     * @param {string} transferId - 传输ID
     * @param {Function} handler - 清理处理器函数
     */
    registerResourceCleanupHandler(transferId, handler) {
        this.resourceCleanupHandlers.set(transferId, handler);
    }

    /**
     * 注册取消回调
     * @param {string} transferId - 传输ID
     * @param {Function} callback - 回调函数
     */
    registerCancelCallback(transferId, callback) {
        this.cancelCallbacks.set(transferId, callback);
    }

    /**
     * 检查传输是否已取消
     * @param {string} transferId - 传输ID
     * @returns {boolean}
     */
    isCancelled(transferId) {
        return this.cancelledTransfers.has(transferId);
    }

    /**
     * 移除取消按钮
     * @param {string} transferId - 传输ID
     */
    removeCancelButton(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const cancelBtn = messageElement.querySelector('.cancel-transfer-btn');
        if (cancelBtn) {
            cancelBtn.remove();
        }
    }

    /**
     * 清理取消信息
     * @param {string} transferId - 传输ID
     */
    clearCancellation(transferId) {
        this.cancelledTransfers.delete(transferId);
        this.cancelCallbacks.delete(transferId);
        this.resourceCleanupHandlers.delete(transferId);
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.cancelledTransfers.clear();
        this.cancelCallbacks.clear();
        this.resourceCleanupHandlers.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.TransferCancellation = TransferCancellation;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TransferCancellation;
}
