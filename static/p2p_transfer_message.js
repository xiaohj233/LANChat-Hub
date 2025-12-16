/**
 * TransferMessage - P2P传输消息组件
 * 
 * 该类负责显示P2P传输相关的消息，包括文件信息、状态、进度和传输速度。
 * 支持多种状态显示：等待响应、连接中、传输中、已完成、已失效等。
 */
class TransferMessage {
    constructor(messageData) {
        this.messageId = messageData.id;
        this.senderId = messageData.senderId;
        this.receiverId = messageData.receiverId;
        this.fileInfo = messageData.fileInfo || {};
        this.transferInfo = messageData.transferInfo || {};
        this.status = this.transferInfo.status || 'pending';
        this.progress = this.transferInfo.progress || 0;
        this.speed = this.transferInfo.speed || 0;
        this.avgSpeed = this.transferInfo.avgSpeed || 0;
        this.estimatedTime = this.transferInfo.estimatedTime || null;
        this.isValid = this.transferInfo.isValid !== false;
        // 使用timestamp字段，如果不存在则使用lastUpdate或当前时间（秒级）
        this.timestamp = messageData.timestamp || messageData.lastUpdate || (Date.now() / 1000);
        this.lastUpdate = this.timestamp; // 保持向后兼容
        this.isSender = messageData.isSender || false;
        this.senderName = messageData.senderName || '';
        this.receiverName = messageData.receiverName || '';
        
        // DOM元素引用
        this.element = null;
    }
    
    /**
     * 渲染传输消息
     * @returns {HTMLElement} 消息DOM元素
     */
    render() {
        // 创建消息行容器（类似普通消息）
        const messageRow = document.createElement('div');
        messageRow.id = 'msg-' + this.messageId;  // 设置id属性，与普通消息保持一致
        messageRow.className = 'msg-row' + (this.isSender ? ' me' : '');
        messageRow.setAttribute('data-message-id', this.messageId);
        messageRow.setAttribute('data-id', this.messageId);  // 添加data-id属性，与普通消息保持一致
        messageRow.setAttribute('data-transfer-id', this.transferInfo.id || this.messageId);
        messageRow.setAttribute('data-timestamp', this.timestamp.toString());
        
        // 获取用户信息
        const userInfo = this.getUserInfo();
        
        // 创建消息内部结构
        const msgInner = document.createElement('div');
        msgInner.className = 'msg-inner';
        
        // 创建头像
        const avatar = document.createElement('div');
        avatar.className = 'msg-av';
        avatar.style.background = userInfo.avatar_bg;
        
        // 创建内容容器
        const contentWrapper = document.createElement('div');
        
        // 创建发送人名称
        const nameDiv = document.createElement('div');
        nameDiv.className = 'msg-name';
        nameDiv.textContent = userInfo.name;
        
        // 创建传输消息气泡
        const bubbleDiv = document.createElement('div');
        bubbleDiv.className = 'msg-bub transfer-message-bubble';
        
        // 根据状态渲染不同的内容
        let contentHTML = '';
        if (this.status === 'pending') {
            contentHTML = this.renderPendingState();
        } else if (this.status === 'connecting') {
            contentHTML = this.renderConnectingState();
        } else if (this.status === 'transferring') {
            contentHTML = this.renderTransferringState();
        } else if (this.status === 'completed') {
            contentHTML = this.renderCompletedState();
        } else if (this.status === 'expired' || !this.isValid) {
            contentHTML = this.renderExpiredState();
        } else if (this.status === 'rejected') {
            contentHTML = this.renderRejectedState();
        } else if (this.status === 'cancelled') {
            contentHTML = this.renderCancelledState();
        } else if (this.status === 'failed') {
            contentHTML = this.renderFailedState();
        } else {
            contentHTML = this.renderDefaultState();
        }
        
        bubbleDiv.innerHTML = contentHTML;
        
        // 组装DOM结构
        contentWrapper.appendChild(nameDiv);
        contentWrapper.appendChild(bubbleDiv);
        
        msgInner.appendChild(avatar);
        msgInner.appendChild(contentWrapper);
        
        messageRow.appendChild(msgInner);
        
        this.element = messageRow;
        return messageRow;
    }
    
    /**
     * 获取用户信息（头像和名称）
     * @returns {Object} 用户信息
     */
    getUserInfo() {
        // 确定要显示的用户ID
        // 对于发送方：显示自己的信息
        // 对于接收方：显示发送方的信息
        const userId = this.isSender ? 
            (typeof me !== 'undefined' && me.uid) : 
            this.senderId;
        
        console.log('[TransferMessage] getUserInfo:', {
            isSender: this.isSender,
            userId: userId,
            senderId: this.senderId,
            receiverId: this.receiverId,
            senderName: this.senderName
        });
        
        // 尝试从全局cache获取用户信息
        if (typeof cache !== 'undefined' && cache.users && userId) {
            const user = cache.users[userId];
            console.log('[TransferMessage] User from cache:', user);
            
            if (user) {
                return {
                    name: user.name || this.senderName || '未知用户',
                    avatar_bg: user.avatar_bg || '#ccc'
                };
            }
        }
        
        // 降级方案：使用传入的名称和默认头像
        console.warn('[TransferMessage] Using fallback user info');
        return {
            name: this.senderName || '未知用户',
            avatar_bg: '#ccc'
        };
    }
    

    
    /**
     * 渲染等待响应状态
     * @returns {string} HTML字符串
     */
    renderPendingState() {
        return `
            <div class="file-info">
                <div class="file-icon">📁</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    ${this.isSender ? '<div class="transfer-method">P2P传输</div>' : `<div class="sender-name">${this.escapeHtml(this.senderName)} 想要发送文件给你</div>`}
                </div>
            </div>
            <div class="transfer-status">
                ${this.isSender ? '<div class="status-text">等待对方响应...</div>' : ''}
                <div class="status-indicator pending"></div>
            </div>
            ${!this.isSender ? this.renderActionButtons() : ''}
        `;
    }
    
    /**
     * 渲染连接中状态
     * @returns {string} HTML字符串
     */
    renderConnectingState() {
        return `
            <div class="file-info">
                <div class="file-icon">📁</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                </div>
            </div>
            <div class="transfer-status">
                <div class="status-text">正在连接...</div>
                <div class="status-indicator connecting"></div>
            </div>
        `;
    }
    
    /**
     * 渲染传输中状态（简化版）
     * @returns {string} HTML字符串
     */
    renderTransferringState() {
        return `
            <div class="file-info">
                <div class="file-icon">📁</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                </div>
            </div>
            <div class="progress-section">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${this.progress}%"></div>
                </div>
                <div class="progress-info">
                    <span class="progress-text">${this.progress.toFixed(1)}%</span>
                    <span class="speed-text">${this.formatSpeed(this.speed)}</span>
                </div>
                <div class="speed-details">
                    <span class="current-speed">当前: ${this.formatSpeed(this.speed)}</span>
                    <span class="avg-speed">平均: ${this.formatSpeed(this.avgSpeed)}</span>
                    ${this.estimatedTime ? `<span class="time-estimate">剩余: ${this.formatTime(this.estimatedTime)}</span>` : ''}
                </div>
                <button class="cancel-btn" onclick="window.p2pMessageIntegration.cancelTransfer('${this.messageId}')">取消</button>
            </div>
        `;
    }
    
    /**
     * 渲染已完成状态（简化版）
     * @returns {string} HTML字符串
     */
    renderCompletedState() {
        const totalTime = this.transferInfo.endTime && this.transferInfo.startTime 
            ? Math.floor((this.transferInfo.endTime - this.transferInfo.startTime) / 1000)
            : 0;
        
        return `
            <div class="file-info">
                <div class="file-icon">✅</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="completion-info">
                        传输完成${totalTime > 0 ? ` (${this.formatTime(totalTime)})` : ''}
                    </div>
                </div>
            </div>
            ${!this.isSender ? `
            <div class="completion-actions">
                <button onclick="window.p2pMessageIntegration.openFile('${this.messageId}')">打开</button>
                <button onclick="window.p2pMessageIntegration.showFileLocation('${this.messageId}')">位置</button>
            </div>
            ` : ''}
        `;
    }
    
    /**
     * 渲染已失效状态
     * @returns {string} HTML字符串
     */
    renderExpiredState() {
        const reason = this.transferInfo.invalidReason || 'unknown';
        const reasonText = {
            'sender_offline': '发送方已离线',
            'file_unavailable': '文件不可用',
            'file_deleted': '文件已被删除',
            'file_moved': '文件已被移动',
            'unknown': '文件已失效'
        };
        
        return `
            <div class="file-info">
                <div class="file-icon">⚠️</div>
                <div class="file-details">
                    <div class="file-name expired-text">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size expired-text">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="expiry-reason">文件已失效 - ${reasonText[reason]}</div>
                </div>
            </div>
        `;
    }
    
    /**
     * 渲染已拒绝状态
     * @returns {string} HTML字符串
     */
    renderRejectedState() {
        return `
            <div class="file-info">
                <div class="file-icon">❌</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="status-info">传输已被拒绝</div>
                </div>
            </div>
        `;
    }
    
    /**
     * 渲染已取消状态
     * @returns {string} HTML字符串
     */
    renderCancelledState() {
        return `
            <div class="file-info">
                <div class="file-icon">🚫</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="status-info">传输已取消</div>
                </div>
            </div>
        `;
    }
    
    /**
     * 渲染失败状态
     * @returns {string} HTML字符串
     */
    renderFailedState() {
        return `
            <div class="file-info">
                <div class="file-icon">❌</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="status-info error">传输失败</div>
                </div>
            </div>
        `;
    }
    
    /**
     * 渲染默认状态
     * @returns {string} HTML字符串
     */
    renderDefaultState() {
        return `
            <div class="file-info">
                <div class="file-icon">📁</div>
                <div class="file-details">
                    <div class="file-name">${this.escapeHtml(this.fileInfo.name)}</div>
                    <div class="file-size">${this.formatFileSize(this.fileInfo.size)}</div>
                    <div class="status-info">状态: ${this.status}</div>
                </div>
            </div>
        `;
    }
    
    /**
     * 渲染操作按钮
     * @returns {string} HTML字符串
     */
    renderActionButtons() {
        return `
            <div class="action-buttons">
                <button class="accept-btn" onclick="window.p2pMessageIntegration.acceptTransfer('${this.messageId}')">接收</button>
                <button class="reject-btn" onclick="window.p2pMessageIntegration.rejectTransfer('${this.messageId}')">拒绝</button>
            </div>
        `;
    }
    
    /**
     * 更新传输状态
     * @param {string} newStatus - 新状态
     * @param {Object} data - 附加数据
     */
    updateStatus(newStatus, data = {}) {
        this.status = newStatus;
        
        if (data.progress !== undefined) this.progress = data.progress;
        if (data.speed !== undefined) this.speed = data.speed;
        if (data.avgSpeed !== undefined) this.avgSpeed = data.avgSpeed;
        if (data.estimatedTime !== undefined) this.estimatedTime = data.estimatedTime;
        if (data.isValid !== undefined) this.isValid = data.isValid;
        
        this.lastUpdate = Date.now();
        
        // 查找元素（优先使用缓存的引用，否则通过data属性查找）
        let targetElement = null;
        
        if (this.element && this.element.parentNode) {
            targetElement = this.element;
        } else {
            // 尝试通过data属性查找
            targetElement = document.querySelector(`[data-message-id="${this.messageId}"]`);
            if (targetElement) {
                this.element = targetElement; // 更新缓存的引用
            }
        }
        
        // 重新渲染
        if (targetElement && targetElement.parentNode) {
            const newElement = this.render();
            targetElement.parentNode.replaceChild(newElement, targetElement);
        } else {
            console.warn(`Cannot update message ${this.messageId}: element not in DOM`);
        }
    }
    
    /**
     * 更新传输速度（性能优化版：减少DOM操作）
     * @param {number} speed - 当前速度
     * @param {number} avgSpeed - 平均速度
     * @param {number} estimatedTime - 预计剩余时间
     */
    updateSpeed(speed, avgSpeed, estimatedTime) {
        this.speed = speed;
        this.avgSpeed = avgSpeed;
        this.estimatedTime = estimatedTime;
        
        // 只更新速度相关的DOM元素，避免完全重新渲染
        // 使用requestAnimationFrame批量更新，提升性能
        if (this.element && this.status === 'transferring') {
            if (this._speedUpdateFrame) {
                cancelAnimationFrame(this._speedUpdateFrame);
            }
            
            this._speedUpdateFrame = requestAnimationFrame(() => {
                const speedText = this.element.querySelector('.speed-text');
                const currentSpeed = this.element.querySelector('.current-speed');
                const avgSpeedElem = this.element.querySelector('.avg-speed');
                const timeEstimate = this.element.querySelector('.time-estimate');
                
                if (speedText) speedText.textContent = this.formatSpeed(speed);
                if (currentSpeed) currentSpeed.textContent = `当前: ${this.formatSpeed(speed)}`;
                if (avgSpeedElem) avgSpeedElem.textContent = `平均: ${this.formatSpeed(avgSpeed)}`;
                
                if (timeEstimate && estimatedTime) {
                    timeEstimate.textContent = `剩余: ${this.formatTime(estimatedTime)}`;
                }
                
                this._speedUpdateFrame = null;
            });
        }
    }
    
    /**
     * 更新传输进度（性能优化版：减少DOM操作和重排）
     * @param {number} progress - 进度百分比
     */
    updateProgress(progress) {
        this.progress = progress;
        
        // 只更新进度相关的DOM元素
        // 使用requestAnimationFrame批量更新，提升性能
        if (this.element && this.status === 'transferring') {
            if (this._progressUpdateFrame) {
                cancelAnimationFrame(this._progressUpdateFrame);
            }
            
            this._progressUpdateFrame = requestAnimationFrame(() => {
                const progressFill = this.element.querySelector('.progress-fill');
                const progressText = this.element.querySelector('.progress-text');
                
                if (progressFill) {
                    // 使用transform代替width，性能更好（避免重排）
                    // 但为了简单起见，这里仍使用width
                    progressFill.style.width = `${progress}%`;
                }
                
                if (progressText) {
                    progressText.textContent = `${progress.toFixed(1)}%`;
                }
                
                this._progressUpdateFrame = null;
            });
        }
    }
    
    /**
     * 格式化文件大小
     * @param {number} bytes - 字节数
     * @returns {string} 格式化的文件大小
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
     * 格式化速度
     * @param {number} bytesPerSecond - 速度（bytes/s）
     * @returns {string} 格式化的速度
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
     * @param {number} seconds - 时间（秒）
     * @returns {string} 格式化的时间
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
     * 转义HTML特殊字符
     * @param {string} text - 要转义的文本
     * @returns {string} 转义后的文本
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TransferMessage;
}
