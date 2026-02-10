/**
 * SystemMessage - 系统消息组件
 * 
 * 该类负责显示P2P传输相关的系统通知消息，如接收、拒绝、取消等通知。
 * 系统消息具有特殊的样式，居中显示，用于告知用户传输状态变化。
 */
class SystemMessage {
    constructor(messageData) {
        this.messageId = messageData.id || `system-${Date.now()}`;
        this.type = messageData.type || 'info';
        this.content = messageData.content || '';
        this.timestamp = messageData.timestamp || (Date.now() / 1000);  // 秒级时间戳
        this.transferId = messageData.transferId || null;
        this.userName = messageData.userName || '';
        this.fileName = messageData.fileName || '';
        
        // DOM元素引用
        this.element = null;
    }
    
    /**
     * 渲染系统消息
     * @returns {HTMLElement} 消息DOM元素
     */
    render() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'system-message';
        messageDiv.setAttribute('data-message-id', this.messageId);
        messageDiv.setAttribute('data-message-type', 'system');
        
        if (this.transferId) {
            messageDiv.setAttribute('data-transfer-id', this.transferId);
        }
        
        // 根据类型渲染不同的内容
        let icon = '';
        let text = '';
        
        switch (this.type) {
            case 'transfer_accepted':
                icon = '✅';
                text = `${this.escapeHtml(this.userName)} 接受了文件 ${this.escapeHtml(this.fileName)}`;
                break;
            case 'transfer_rejected':
                icon = '❌';
                text = `${this.escapeHtml(this.userName)} 拒绝了文件 ${this.escapeHtml(this.fileName)}`;
                break;
            case 'transfer_cancelled':
                icon = '🚫';
                text = `${this.escapeHtml(this.userName)} 取消了文件传输 ${this.escapeHtml(this.fileName)}`;
                break;
            case 'transfer_completed':
                icon = '🎉';
                text = `文件 ${this.escapeHtml(this.fileName)} 传输完成`;
                break;
            case 'transfer_failed':
                icon = '⚠️';
                text = `文件 ${this.escapeHtml(this.fileName)} 传输失败`;
                break;
            case 'info':
            default:
                icon = 'ℹ️';
                text = this.escapeHtml(this.content);
                break;
        }
        
        messageDiv.innerHTML = `
            <div class="system-icon">${icon}</div>
            <div class="system-text">${text}</div>
            <div class="system-time">${this.formatTimestamp(this.timestamp)}</div>
        `;
        
        this.element = messageDiv;
        return messageDiv;
    }
    
    /**
     * 格式化时间戳
     * @param {number} timestamp - 时间戳
     * @returns {string} 格式化的时间
     */
    formatTimestamp(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;
        
        if (diff < 60000) {
            return '刚刚';
        } else if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes}分钟前`;
        } else if (diff < 86400000) {
            const hours = Math.floor(diff / 3600000);
            return `${hours}小时前`;
        } else {
            const date = new Date(timestamp);
            return `${date.getMonth() + 1}月${date.getDate()}日`;
        }
    }
    
    /**
     * 转义HTML特殊字符
     * @param {string} text - 要转义的文本
     * @returns {string} 转义后的文本
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    /**
     * 创建接收通知消息
     * @param {string} userName - 用户名
     * @param {string} fileName - 文件名
     * @param {string} transferId - 传输ID
     * @returns {SystemMessage} 系统消息实例
     */
    static createAcceptedMessage(userName, fileName, transferId) {
        return new SystemMessage({
            type: 'transfer_accepted',
            userName: userName,
            fileName: fileName,
            transferId: transferId,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
    
    /**
     * 创建拒绝通知消息
     * @param {string} userName - 用户名
     * @param {string} fileName - 文件名
     * @param {string} transferId - 传输ID
     * @returns {SystemMessage} 系统消息实例
     */
    static createRejectedMessage(userName, fileName, transferId) {
        return new SystemMessage({
            type: 'transfer_rejected',
            userName: userName,
            fileName: fileName,
            transferId: transferId,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
    
    /**
     * 创建取消通知消息
     * @param {string} userName - 用户名
     * @param {string} fileName - 文件名
     * @param {string} transferId - 传输ID
     * @returns {SystemMessage} 系统消息实例
     */
    static createCancelledMessage(userName, fileName, transferId) {
        return new SystemMessage({
            type: 'transfer_cancelled',
            userName: userName,
            fileName: fileName,
            transferId: transferId,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
    
    /**
     * 创建完成通知消息
     * @param {string} fileName - 文件名
     * @param {string} transferId - 传输ID
     * @returns {SystemMessage} 系统消息实例
     */
    static createCompletedMessage(fileName, transferId) {
        return new SystemMessage({
            type: 'transfer_completed',
            fileName: fileName,
            transferId: transferId,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
    
    /**
     * 创建失败通知消息
     * @param {string} fileName - 文件名
     * @param {string} transferId - 传输ID
     * @returns {SystemMessage} 系统消息实例
     */
    static createFailedMessage(fileName, transferId) {
        return new SystemMessage({
            type: 'transfer_failed',
            fileName: fileName,
            transferId: transferId,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
    
    /**
     * 创建自定义信息消息
     * @param {string} content - 消息内容
     * @returns {SystemMessage} 系统消息实例
     */
    static createInfoMessage(content) {
        return new SystemMessage({
            type: 'info',
            content: content,
            timestamp: Date.now() / 1000  // 秒级时间戳
        });
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SystemMessage;
}
