/**
 * CancelNotification - 处理P2P传输取消通知机制
 * 
 * 功能:
 * - 实现取消通知发送
 * - 创建取消系统消息
 * - 通过RealtimeSync通知对方
 * - 更新双方的传输消息状态
 * 
 */

class CancelNotification {
    constructor() {
        this.realtimeSync = null; // RealtimeSync实例
        this.dbSync = null; // DatabaseSync实例
        this.pendingNotifications = new Map(); // 待发送的通知
        this.sentNotifications = new Set(); // 已发送的通知
        
        // 监听取消事件
        this.setupEventListeners();
    }

    /**
     * 设置RealtimeSync实例
     * @param {Object} realtimeSync - RealtimeSync实例
     */
    setRealtimeSync(realtimeSync) {
        this.realtimeSync = realtimeSync;
        console.log('[CancelNotification] RealtimeSync已设置');
    }

    /**
     * 设置DatabaseSync实例
     * @param {Object} dbSync - DatabaseSync实例
     */
    setDatabaseSync(dbSync) {
        this.dbSync = dbSync;
        console.log('[CancelNotification] DatabaseSync已设置');
    }

    /**
     * 设置事件监听器
     */
    setupEventListeners() {
        // 监听传输取消事件
        document.addEventListener('p2p-transfer-cancelled', (event) => {
            const { transferId, cancelTime, cancelReason } = event.detail;
            this.handleTransferCancelled(transferId, cancelTime, cancelReason);
        });

        // 监听取消通知接收事件
        document.addEventListener('p2p-cancel-notification-received', (event) => {
            const { transferId, senderName, fileName } = event.detail;
            this.handleCancelNotificationReceived(transferId, senderName, fileName);
        });
    }

    /**
     * 处理传输取消事件
     * @param {string} transferId - 传输ID
     * @param {number} cancelTime - 取消时间
     * @param {string} cancelReason - 取消原因
     */
    async handleTransferCancelled(transferId, cancelTime, cancelReason) {
        console.log(`[CancelNotification] 处理传输取消: transferId=${transferId}`);

        try {
            // 1. 发送取消通知给对方
            await this.sendCancelNotification(transferId, cancelTime, cancelReason);

            // 2. 创建系统消息
            await this.createCancelSystemMessage(transferId, 'self');

            // 3. 更新双方的传输消息状态
            await this.updateTransferMessageStatus(transferId);

            console.log(`[CancelNotification] 取消通知处理完成: ${transferId}`);
        } catch (error) {
            console.error(`[CancelNotification] 处理取消通知失败:`, error);
        }
    }

    /**
     * 发送取消通知给对方
     * @param {string} transferId - 传输ID
     * @param {number} cancelTime - 取消时间
     * @param {string} cancelReason - 取消原因
     * @returns {Promise<void>}
     */
    async sendCancelNotification(transferId, cancelTime, cancelReason) {
        console.log(`[CancelNotification] 发送取消通知: ${transferId}`);

        // 检查是否已发送
        if (this.sentNotifications.has(transferId)) {
            console.log(`[CancelNotification] 取消通知已发送，跳过: ${transferId}`);
            return;
        }

        const notification = {
            type: 'transfer_cancelled',
            transferId,
            cancelTime,
            cancelReason,
            timestamp: Date.now()
        };

        // 通过RealtimeSync发送
        if (this.realtimeSync) {
            try {
                this.realtimeSync.send({
                    type: 'cancel_notification',
                    transferId,
                    payload: notification
                });
                console.log(`[CancelNotification] 通过RealtimeSync发送取消通知: ${transferId}`);
            } catch (error) {
                console.error(`[CancelNotification] RealtimeSync发送失败:`, error);
            }
        }

        // 通过API发送（备用方案）
        try {
            const response = await fetch('/api/p2p/cancel-notification', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(notification)
            });

            if (!response.ok) {
                throw new Error(`发送取消通知失败: ${response.status}`);
            }

            console.log(`[CancelNotification] 通过API发送取消通知: ${transferId}`);
            this.sentNotifications.add(transferId);
        } catch (error) {
            console.error(`[CancelNotification] API发送失败:`, error);
            // 添加到待发送队列
            this.pendingNotifications.set(transferId, notification);
        }
    }

    /**
     * 创建取消系统消息
     * @param {string} transferId - 传输ID
     * @param {string} side - 'self' 或 'peer'
     * @returns {Promise<void>}
     */
    async createCancelSystemMessage(transferId, side = 'self') {
        console.log(`[CancelNotification] 创建取消系统消息: ${transferId}, side=${side}`);

        // 获取传输信息
        const transferInfo = await this.getTransferInfo(transferId);
        if (!transferInfo) {
            console.warn(`[CancelNotification] 找不到传输信息: ${transferId}`);
            return;
        }

        const { fileName, senderName, receiverName } = transferInfo;

        // 构建系统消息内容
        let messageContent;
        if (side === 'self') {
            messageContent = `你取消了文件 "${fileName}" 的传输`;
        } else {
            messageContent = `${senderName} 取消了文件 "${fileName}" 的传输`;
        }

        // 创建系统消息
        const systemMessage = {
            type: 'system',
            subtype: 'transfer_cancelled',
            transferId,
            content: messageContent,
            timestamp: Date.now(),
            icon: '🚫'
        };

        // 保存到数据库
        if (this.dbSync) {
            try {
                await this.dbSync.saveTransferMessage(systemMessage);
                console.log(`[CancelNotification] 系统消息已保存: ${transferId}`);
            } catch (error) {
                console.error(`[CancelNotification] 保存系统消息失败:`, error);
            }
        }

        // 添加到聊天界面
        this.addSystemMessageToChat(systemMessage);
    }

    /**
     * 添加系统消息到聊天界面
     * @param {Object} systemMessage - 系统消息
     */
    addSystemMessageToChat(systemMessage) {
        const chatContainer = document.getElementById('chat-messages');
        if (!chatContainer) {
            console.warn('[CancelNotification] 找不到聊天容器');
            return;
        }

        // 创建系统消息元素
        const messageElement = document.createElement('div');
        messageElement.className = 'system-message cancel-notification';
        messageElement.dataset.messageId = systemMessage.transferId;
        messageElement.innerHTML = `
            <div class="system-icon">${systemMessage.icon}</div>
            <div class="system-text">${systemMessage.content}</div>
            <div class="system-time">${this.formatTime(systemMessage.timestamp)}</div>
        `;

        // 添加到聊天容器
        chatContainer.appendChild(messageElement);

        // 滚动到底部
        chatContainer.scrollTop = chatContainer.scrollHeight;

        // 添加样式
        if (!document.getElementById('cancel-notification-styles')) {
            const style = document.createElement('style');
            style.id = 'cancel-notification-styles';
            style.textContent = `
                .system-message.cancel-notification {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 12px;
                    margin: 4px 0;
                    background-color: #f8f9fa;
                    border-radius: 8px;
                    font-size: 13px;
                    color: #6c757d;
                    justify-content: center;
                }
                .system-message.cancel-notification .system-icon {
                    font-size: 16px;
                }
                .system-message.cancel-notification .system-text {
                    flex: 1;
                    text-align: center;
                }
                .system-message.cancel-notification .system-time {
                    font-size: 11px;
                    color: #adb5bd;
                }
            `;
            document.head.appendChild(style);
        }
    }

    /**
     * 更新传输消息状态
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async updateTransferMessageStatus(transferId) {
        console.log(`[CancelNotification] 更新传输消息状态: ${transferId}`);

        // 更新数据库
        if (this.dbSync) {
            try {
                await this.dbSync.updateTransferStatus(transferId, 'cancelled', {
                    cancelTime: Date.now(),
                    cancelReason: 'user_requested'
                });
                console.log(`[CancelNotification] 数据库状态已更新: ${transferId}`);
            } catch (error) {
                console.error(`[CancelNotification] 更新数据库失败:`, error);
            }
        }

        // 更新UI
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (messageElement) {
            messageElement.classList.add('transfer-cancelled');
            messageElement.style.opacity = '0.7';
        }
    }

    /**
     * 处理接收到的取消通知
     * @param {string} transferId - 传输ID
     * @param {string} senderName - 发送者名称
     * @param {string} fileName - 文件名
     */
    async handleCancelNotificationReceived(transferId, senderName, fileName) {
        console.log(`[CancelNotification] 接收到取消通知: ${transferId}`);

        try {
            // 1. 创建系统消息
            await this.createCancelSystemMessage(transferId, 'peer');

            // 2. 更新传输消息状态
            await this.updateTransferMessageStatus(transferId);

            // 3. 显示通知
            this.showCancelNotification(senderName, fileName);

            console.log(`[CancelNotification] 取消通知处理完成: ${transferId}`);
        } catch (error) {
            console.error(`[CancelNotification] 处理接收到的取消通知失败:`, error);
        }
    }

    /**
     * 显示取消通知
     * @param {string} senderName - 发送者名称
     * @param {string} fileName - 文件名
     */
    showCancelNotification(senderName, fileName) {
        // 使用浏览器通知API
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('传输已取消', {
                body: `${senderName} 取消了文件 "${fileName}" 的传输`,
                icon: '/static/icons/cancel.png'
            });
        }

        // 显示页面内通知
        this.showInPageNotification(`${senderName} 取消了文件 "${fileName}" 的传输`);
    }

    /**
     * 显示页面内通知
     * @param {string} message - 通知消息
     */
    showInPageNotification(message) {
        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = 'in-page-notification cancel-notification-toast';
        notification.innerHTML = `
            <div class="notification-icon">🚫</div>
            <div class="notification-text">${message}</div>
        `;

        document.body.appendChild(notification);

        // 添加样式
        if (!document.getElementById('in-page-notification-styles')) {
            const style = document.createElement('style');
            style.id = 'in-page-notification-styles';
            style.textContent = `
                .in-page-notification {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    padding: 16px 20px;
                    background-color: #fff;
                    border-radius: 8px;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    z-index: 10000;
                    animation: slideIn 0.3s ease-out;
                }
                @keyframes slideIn {
                    from {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                @keyframes slideOut {
                    from {
                        transform: translateX(0);
                        opacity: 1;
                    }
                    to {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                }
                .in-page-notification.cancel-notification-toast {
                    border-left: 4px solid #dc3545;
                }
                .in-page-notification .notification-icon {
                    font-size: 24px;
                }
                .in-page-notification .notification-text {
                    font-size: 14px;
                    color: #212529;
                }
            `;
            document.head.appendChild(style);
        }

        // 3秒后移除
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 300);
        }, 3000);
    }

    /**
     * 获取传输信息
     * @param {string} transferId - 传输ID
     * @returns {Promise<Object|null>}
     */
    async getTransferInfo(transferId) {
        try {
            const response = await fetch(`/api/p2p/messages/${transferId}`);
            if (!response.ok) {
                throw new Error(`获取传输信息失败: ${response.status}`);
            }
            const data = await response.json();
            return {
                fileName: data.fileInfo?.name || '未知文件',
                senderName: data.senderName || '未知用户',
                receiverName: data.receiverName || '未知用户'
            };
        } catch (error) {
            console.error(`[CancelNotification] 获取传输信息失败:`, error);
            return null;
        }
    }

    /**
     * 格式化时间
     * @param {number} timestamp - 时间戳
     * @returns {string}
     */
    formatTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) {
            return '刚刚';
        } else if (diff < 3600000) {
            return `${Math.floor(diff / 60000)}分钟前`;
        } else if (diff < 86400000) {
            return `${Math.floor(diff / 3600000)}小时前`;
        } else {
            return date.toLocaleString('zh-CN');
        }
    }

    /**
     * 重试待发送的通知
     * @returns {Promise<void>}
     */
    async retryPendingNotifications() {
        if (this.pendingNotifications.size === 0) {
            return;
        }

        console.log(`[CancelNotification] 重试 ${this.pendingNotifications.size} 个待发送通知`);

        for (const [transferId, notification] of this.pendingNotifications.entries()) {
            try {
                await this.sendCancelNotification(
                    transferId,
                    notification.cancelTime,
                    notification.cancelReason
                );
                this.pendingNotifications.delete(transferId);
            } catch (error) {
                console.error(`[CancelNotification] 重试失败: ${transferId}`, error);
            }
        }
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.pendingNotifications.clear();
        this.sentNotifications.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.CancelNotification = CancelNotification;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CancelNotification;
}
