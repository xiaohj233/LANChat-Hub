/**
 * StateRestoration - 负责页面加载时恢复传输状态
 * 
 * 该类从数据库加载传输历史，渲染所有历史传输消息，
 * 并对未完成的传输启动有效性检查。
 */
class StateRestoration {
    constructor() {
        this.dbSync = new DatabaseSync();
        this.validityChecker = new ValidityChecker();
        this.restoredMessages = new Map();
    }
    
    /**
     * 恢复传输消息
     * @param {string} userId - 用户ID
     * @param {string} chatId - 聊天ID
     * @returns {Promise<Array>} 恢复的消息列表
     */
    async restoreTransferMessages(userId, chatId) {
        try {
            console.log(`Restoring transfer messages for user ${userId} in chat ${chatId}`);
            
            // 从数据库加载传输历史
            const messages = await this.dbSync.loadTransferHistory(userId, chatId);
            
            console.log(`Loaded ${messages.length} transfer messages from database`);
            
            // 渲染每条消息
            for (const message of messages) {
                this.renderTransferMessage(message);
                this.restoredMessages.set(message.id, message);
                
                // 对于未完成的传输，启动有效性检查
                if (this.isActiveTransfer(message.transferInfo.status)) {
                    this.validityChecker.startValidityCheck(
                        message.transferInfo.id,
                        {
                            ...message.fileInfo,
                            senderId: message.senderId
                        }
                    );
                }
            }
            
            console.log(`Restored ${messages.length} transfer messages`);
            return messages;
        } catch (error) {
            console.error('Failed to restore transfer messages:', error);
            return [];
        }
    }
    
    /**
     * 判断是否为活跃传输
     * @param {string} status - 传输状态
     * @returns {boolean} 是否为活跃传输
     */
    isActiveTransfer(status) {
        const activeStatuses = ['pending', 'accepted', 'connecting', 'transferring'];
        return activeStatuses.includes(status);
    }
    
    /**
     * 渲染传输消息
     * @param {Object} messageData - 消息数据
     * @returns {HTMLElement|null} 渲染的消息元素
     */
    renderTransferMessage(messageData) {
        try {
            // 检查是否已经渲染
            const existingElement = document.querySelector(`[data-message-id="${messageData.id}"]`);
            if (existingElement) {
                console.log(`Message ${messageData.id} already rendered`);
                return existingElement;
            }
            
            // 创建传输消息元素
            const messageElement = this.createTransferMessageElement(messageData);
            
            // 添加到聊天界面
            const chatContainer = document.getElementById('chat-messages');
            if (chatContainer) {
                chatContainer.appendChild(messageElement);
                console.log(`Rendered transfer message ${messageData.id}`);
                return messageElement;
            } else {
                console.warn('Chat container not found');
                return null;
            }
        } catch (error) {
            console.error(`Failed to render transfer message ${messageData.id}:`, error);
            return null;
        }
    }
    
    /**
     * 创建传输消息元素
     * @param {Object} messageData - 消息数据
     * @returns {HTMLElement} 消息元素
     */
    createTransferMessageElement(messageData) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'transfer-message';
        messageDiv.dataset.messageId = messageData.id;
        
        // 添加状态类
        messageDiv.classList.add(messageData.transferInfo.status);
        
        // 添加发送方/接收方类
        const currentUserId = window.currentUserId || 'unknown';
        if (messageData.senderId === currentUserId) {
            messageDiv.classList.add('sender');
        } else {
            messageDiv.classList.add('receiver');
        }
        
        // 构建消息内容
        messageDiv.innerHTML = this.buildMessageHTML(messageData);
        
        return messageDiv;
    }
    
    /**
     * 构建消息HTML
     * @param {Object} messageData - 消息数据
     * @returns {string} HTML字符串
     */
    buildMessageHTML(messageData) {
        const { fileInfo, transferInfo } = messageData;
        
        let html = `
            <div class="file-info">
                <div class="file-icon">${this.getFileIcon(transferInfo.status)}</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(fileInfo.size)}</div>
                    <div class="transfer-method">P2P传输</div>
                </div>
            </div>
        `;
        
        // 根据状态添加不同的内容
        switch (transferInfo.status) {
            case 'pending':
                html += this.buildPendingHTML(messageData);
                break;
            case 'accepted':
            case 'connecting':
                html += this.buildConnectingHTML(messageData);
                break;
            case 'transferring':
                html += this.buildTransferringHTML(messageData);
                break;
            case 'completed':
                html += this.buildCompletedHTML(messageData);
                break;
            case 'failed':
            case 'cancelled':
            case 'expired':
                html += this.buildFailedHTML(messageData);
                break;
        }
        
        return html;
    }
    
    /**
     * 构建等待状态HTML
     */
    buildPendingHTML(messageData) {
        return `
            <div class="transfer-status">
                <div class="status-text">等待对方响应...</div>
            </div>
        `;
    }
    
    /**
     * 构建连接中状态HTML
     */
    buildConnectingHTML(messageData) {
        return `
            <div class="transfer-status">
                <div class="status-text">正在连接...</div>
            </div>
        `;
    }
    
    /**
     * 构建传输中状态HTML
     */
    buildTransferringHTML(messageData) {
        const { transferInfo } = messageData;
        const speedCalc = new SpeedCalculator();
        
        return `
            <div class="progress-section">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${transferInfo.progress}%"></div>
                </div>
                <div class="progress-info">
                    <span class="progress-text">${transferInfo.progress.toFixed(1)}%</span>
                    <span class="speed-text">${speedCalc.formatSpeed(transferInfo.speed)}</span>
                </div>
                ${transferInfo.estimatedTime ? `
                    <div class="time-estimate">预计剩余时间: ${speedCalc.formatTime(transferInfo.estimatedTime)}</div>
                ` : ''}
            </div>
        `;
    }
    
    /**
     * 构建完成状态HTML
     */
    buildCompletedHTML(messageData) {
        const { transferInfo } = messageData;
        const speedCalc = new SpeedCalculator();
        const duration = transferInfo.endTime - transferInfo.startTime;
        
        return `
            <div class="completion-info">
                传输完成 - 平均速度: ${speedCalc.formatSpeed(transferInfo.avgSpeed)} - 用时: ${speedCalc.formatTime(Math.floor(duration / 1000))}
            </div>
        `;
    }
    
    /**
     * 构建失败状态HTML
     */
    buildFailedHTML(messageData) {
        const { transferInfo } = messageData;
        let reason = '传输失败';
        
        if (transferInfo.status === 'expired') {
            if (transferInfo.invalidReason === 'sender_offline') {
                reason = '发送方已离线';
            } else if (transferInfo.invalidReason === 'file_unavailable') {
                reason = '文件不可用';
            } else {
                reason = '传输已失效';
            }
        } else if (transferInfo.status === 'cancelled') {
            reason = '传输已取消';
        }
        
        return `
            <div class="failure-info">
                <div class="failure-reason">${reason}</div>
            </div>
        `;
    }
    
    /**
     * 获取文件图标
     */
    getFileIcon(status) {
        const icons = {
            'pending': '📁',
            'accepted': '📁',
            'connecting': '🔄',
            'transferring': '📤',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫',
            'expired': '⚠️'
        };
        return icons[status] || '📁';
    }
    
    /**
     * 格式化文件大小
     */
    formatFileSize(bytes) {
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
     * 转义HTML
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * 获取已恢复的消息
     * @param {string} messageId - 消息ID
     * @returns {Object|null} 消息数据
     */
    getRestoredMessage(messageId) {
        return this.restoredMessages.get(messageId) || null;
    }
    
    /**
     * 获取所有已恢复的消息
     * @returns {Array} 消息列表
     */
    getAllRestoredMessages() {
        return Array.from(this.restoredMessages.values());
    }
    
    /**
     * 清理资源
     */
    destroy() {
        this.restoredMessages.clear();
        
        if (this.validityChecker) {
            this.validityChecker.destroy();
        }
        
        if (this.dbSync) {
            this.dbSync.destroy();
        }
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = StateRestoration;
}
