/**
 * ValidityStateSync - 处理传输有效性状态同步
 * 
 * 功能:
 * - 开发状态同步机制
 * - 实现失效状态的UI更新
 * - 添加重新打开界面时的有效性检查
 * - 通过RealtimeSync实时通知失效状态
 * - 更新数据库失效信息
 */

class ValidityStateSync {
    constructor() {
        this.realtimeSync = null; // RealtimeSync实例
        this.dbSync = null; // DatabaseSync实例
        this.validityChecker = null; // ValidityChecker实例
        this.expiredTransfers = new Map(); // 已失效的传输
        this.syncCallbacks = new Map(); // 同步回调
        
        // 设置事件监听器
        this.setupEventListeners();
    }

    /**
     * 设置RealtimeSync实例
     * @param {Object} realtimeSync - RealtimeSync实例
     */
    setRealtimeSync(realtimeSync) {
        this.realtimeSync = realtimeSync;
        console.log('[ValidityStateSync] RealtimeSync已设置');
        
        // 注册有效性更新回调
        if (this.realtimeSync && this.realtimeSync.onValidityUpdate) {
            this.realtimeSync.onValidityUpdate = (data) => {
                this.handleValidityUpdate(data);
            };
        }
    }

    /**
     * 设置DatabaseSync实例
     * @param {Object} dbSync - DatabaseSync实例
     */
    setDatabaseSync(dbSync) {
        this.dbSync = dbSync;
        console.log('[ValidityStateSync] DatabaseSync已设置');
    }

    /**
     * 设置ValidityChecker实例
     * @param {Object} validityChecker - ValidityChecker实例
     */
    setValidityChecker(validityChecker) {
        this.validityChecker = validityChecker;
        console.log('[ValidityStateSync] ValidityChecker已设置');
    }

    /**
     * 设置事件监听器
     */
    setupEventListeners() {
        // 监听页面加载完成事件
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                this.checkValidityOnPageLoad();
            });
        } else {
            this.checkValidityOnPageLoad();
        }

        // 监听页面可见性变化
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.checkValidityOnPageVisible();
            }
        });

        // 监听有效性更新事件
        document.addEventListener('p2p-validity-changed', (event) => {
            const { transferId, isValid, reason } = event.detail;
            this.handleValidityChanged(transferId, isValid, reason);
        });
    }

    /**
     * 页面加载时检查有效性
     */
    async checkValidityOnPageLoad() {
        console.log('[ValidityStateSync] 页面加载，检查传输有效性');

        try {
            // 获取所有活跃的传输消息
            const activeTransfers = await this.getActiveTransfers();
            
            if (activeTransfers.length === 0) {
                console.log('[ValidityStateSync] 没有活跃的传输');
                return;
            }

            console.log(`[ValidityStateSync] 找到 ${activeTransfers.length} 个活跃传输，开始检查`);

            // 批量检查有效性
            for (const transfer of activeTransfers) {
                await this.checkAndUpdateValidity(transfer);
            }

            console.log('[ValidityStateSync] 有效性检查完成');
        } catch (error) {
            console.error('[ValidityStateSync] 页面加载检查失败:', error);
        }
    }

    /**
     * 页面可见时检查有效性
     */
    async checkValidityOnPageVisible() {
        console.log('[ValidityStateSync] 页面变为可见，检查传输有效性');
        await this.checkValidityOnPageLoad();
    }

    /**
     * 获取活跃的传输
     * @returns {Promise<Array>} 活跃传输列表
     */
    async getActiveTransfers() {
        try {
            const response = await fetch('/api/p2p/active-transfers');
            if (!response.ok) {
                throw new Error(`获取活跃传输失败: ${response.status}`);
            }
            const data = await response.json();
            return data.transfers || [];
        } catch (error) {
            console.error('[ValidityStateSync] 获取活跃传输失败:', error);
            return [];
        }
    }

    /**
     * 检查并更新有效性
     * @param {Object} transfer - 传输对象
     */
    async checkAndUpdateValidity(transfer) {
        const { id: transferId, fileInfo, status } = transfer;

        // 只检查活跃状态的传输
        const activeStatuses = ['pending', 'accepted', 'connecting', 'transferring'];
        if (!activeStatuses.includes(status)) {
            return;
        }

        console.log(`[ValidityStateSync] 检查传输有效性: ${transferId}`);

        try {
            // 使用ValidityChecker检查
            if (this.validityChecker) {
                const result = await this.validityChecker.checkValidity(transferId, fileInfo);
                
                if (!result.valid) {
                    console.log(`[ValidityStateSync] 传输失效: ${transferId}, reason=${result.reason}`);
                    await this.markAsExpired(transferId, result.reason);
                }
            }
        } catch (error) {
            console.error(`[ValidityStateSync] 检查有效性失败: ${transferId}`, error);
        }
    }

    /**
     * 标记为失效
     * @param {string} transferId - 传输ID
     * @param {string} reason - 失效原因
     */
    async markAsExpired(transferId, reason) {
        console.log(`[ValidityStateSync] 标记为失效: ${transferId}, reason=${reason}`);

        // 记录失效信息
        this.expiredTransfers.set(transferId, {
            reason,
            expiredTime: Date.now()
        });

        // 1. 更新数据库
        await this.updateDatabaseValidity(transferId, false, reason);

        // 2. 更新UI
        this.updateUIValidity(transferId, false, reason);

        // 3. 通过RealtimeSync通知对方
        await this.notifyValidityChange(transferId, false, reason);

        // 4. 触发失效事件
        this.triggerValidityEvent(transferId, false, reason);
    }

    /**
     * 更新数据库有效性
     * @param {string} transferId - 传输ID
     * @param {boolean} isValid - 是否有效
     * @param {string} reason - 原因
     */
    async updateDatabaseValidity(transferId, isValid, reason) {
        console.log(`[ValidityStateSync] 更新数据库: ${transferId}, isValid=${isValid}`);

        if (this.dbSync) {
            try {
                await this.dbSync.updateTransferStatus(transferId, 'expired', {
                    isValid,
                    invalidReason: reason,
                    invalidTime: Date.now()
                });
                console.log(`[ValidityStateSync] 数据库已更新: ${transferId}`);
            } catch (error) {
                console.error(`[ValidityStateSync] 更新数据库失败:`, error);
            }
        }
    }

    /**
     * 更新UI有效性
     * @param {string} transferId - 传输ID
     * @param {boolean} isValid - 是否有效
     * @param {string} reason - 原因
     */
    updateUIValidity(transferId, isValid, reason) {
        console.log(`[ValidityStateSync] 更新UI: ${transferId}, isValid=${isValid}`);

        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[ValidityStateSync] 找不到传输消息元素: ${transferId}`);
            return;
        }

        if (!isValid) {
            // 添加失效样式
            messageElement.classList.add('transfer-expired');
            messageElement.style.opacity = '0.7';

            // 添加失效提示
            this.addExpiredIndicator(messageElement, reason);

            // 移除操作按钮
            const actionButtons = messageElement.querySelectorAll('.accept-btn, .reject-btn, .cancel-transfer-btn');
            actionButtons.forEach(btn => btn.remove());
        } else {
            // 移除失效样式
            messageElement.classList.remove('transfer-expired');
            messageElement.style.opacity = '1';

            // 移除失效提示
            const expiredIndicator = messageElement.querySelector('.expired-indicator');
            if (expiredIndicator) {
                expiredIndicator.remove();
            }
        }
    }

    /**
     * 添加失效指示器
     * @param {HTMLElement} messageElement - 消息元素
     * @param {string} reason - 失效原因
     */
    addExpiredIndicator(messageElement, reason) {
        // 检查是否已存在
        if (messageElement.querySelector('.expired-indicator')) {
            return;
        }

        const reasonText = this.getReasonText(reason);

        const indicator = document.createElement('div');
        indicator.className = 'expired-indicator';
        indicator.innerHTML = `
            <div class="expired-icon">⚠️</div>
            <div class="expired-text">${reasonText}</div>
        `;

        messageElement.appendChild(indicator);

        // 添加样式
        if (!document.getElementById('expired-indicator-styles')) {
            const style = document.createElement('style');
            style.id = 'expired-indicator-styles';
            style.textContent = `
                .transfer-expired {
                    position: relative;
                }
                .expired-indicator {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #f8d7da;
                    border: 1px solid #f5c6cb;
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }
                .expired-icon {
                    font-size: 20px;
                }
                .expired-text {
                    font-size: 14px;
                    color: #721c24;
                    font-weight: 500;
                }
            `;
            document.head.appendChild(style);
        }
    }

    /**
     * 获取失效原因文本
     * @param {string} reason - 原因代码
     * @returns {string} 原因文本
     */
    getReasonText(reason) {
        const reasons = {
            'sender_offline': '发送方已离线',
            'file_unavailable': '文件不可用',
            'file_deleted': '文件已被删除',
            'file_moved': '文件已被移动',
            'permission_denied': '无权访问文件',
            'timeout': '传输超时',
            'unknown': '未知原因'
        };
        return reasons[reason] || '传输已失效';
    }

    /**
     * 通知有效性变化
     * @param {string} transferId - 传输ID
     * @param {boolean} isValid - 是否有效
     * @param {string} reason - 原因
     */
    async notifyValidityChange(transferId, isValid, reason) {
        console.log(`[ValidityStateSync] 通知有效性变化: ${transferId}, isValid=${isValid}`);

        // 通过RealtimeSync发送
        if (this.realtimeSync) {
            try {
                this.realtimeSync.send({
                    type: 'validity_update',
                    transferId,
                    payload: {
                        isValid,
                        reason,
                        timestamp: Date.now()
                    }
                });
                console.log(`[ValidityStateSync] 已通过RealtimeSync发送: ${transferId}`);
            } catch (error) {
                console.error(`[ValidityStateSync] RealtimeSync发送失败:`, error);
            }
        }

        // 通过API发送（备用）
        try {
            await fetch('/api/p2p/validity-notification', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    transferId,
                    isValid,
                    reason,
                    timestamp: Date.now()
                })
            });
            console.log(`[ValidityStateSync] 已通过API发送: ${transferId}`);
        } catch (error) {
            console.error(`[ValidityStateSync] API发送失败:`, error);
        }
    }

    /**
     * 处理有效性更新（从RealtimeSync接收）
     * @param {Object} data - 更新数据
     */
    handleValidityUpdate(data) {
        const { transferId, isValid, reason } = data;
        console.log(`[ValidityStateSync] 接收到有效性更新: ${transferId}, isValid=${isValid}`);

        // 更新UI
        this.updateUIValidity(transferId, isValid, reason);

        // 触发事件
        this.triggerValidityEvent(transferId, isValid, reason);
    }

    /**
     * 处理有效性变化事件
     * @param {string} transferId - 传输ID
     * @param {boolean} isValid - 是否有效
     * @param {string} reason - 原因
     */
    handleValidityChanged(transferId, isValid, reason) {
        console.log(`[ValidityStateSync] 处理有效性变化: ${transferId}, isValid=${isValid}`);

        if (!isValid) {
            this.markAsExpired(transferId, reason);
        }
    }

    /**
     * 触发有效性事件
     * @param {string} transferId - 传输ID
     * @param {boolean} isValid - 是否有效
     * @param {string} reason - 原因
     */
    triggerValidityEvent(transferId, isValid, reason) {
        // 调用回调
        const callback = this.syncCallbacks.get(transferId);
        if (callback) {
            try {
                callback({ isValid, reason });
            } catch (error) {
                console.error(`[ValidityStateSync] 回调执行失败:`, error);
            }
        }

        // 触发全局事件
        const event = new CustomEvent('p2p-validity-sync-complete', {
            detail: {
                transferId,
                isValid,
                reason,
                timestamp: Date.now()
            }
        });
        document.dispatchEvent(event);
    }

    /**
     * 注册同步回调
     * @param {string} transferId - 传输ID
     * @param {Function} callback - 回调函数
     */
    registerSyncCallback(transferId, callback) {
        this.syncCallbacks.set(transferId, callback);
    }

    /**
     * 注销同步回调
     * @param {string} transferId - 传输ID
     */
    unregisterSyncCallback(transferId) {
        this.syncCallbacks.delete(transferId);
    }

    /**
     * 检查传输是否已失效
     * @param {string} transferId - 传输ID
     * @returns {boolean}
     */
    isExpired(transferId) {
        return this.expiredTransfers.has(transferId);
    }

    /**
     * 获取失效信息
     * @param {string} transferId - 传输ID
     * @returns {Object|null}
     */
    getExpiredInfo(transferId) {
        return this.expiredTransfers.get(transferId) || null;
    }

    /**
     * 清理失效信息
     * @param {string} transferId - 传输ID
     */
    clearExpired(transferId) {
        this.expiredTransfers.delete(transferId);
        this.syncCallbacks.delete(transferId);
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.expiredTransfers.clear();
        this.syncCallbacks.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.ValidityStateSync = ValidityStateSync;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ValidityStateSync;
}
