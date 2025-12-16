/**
 * DatabaseSync - 负责将传输消息和状态同步到数据库
 * 
 * 该类提供数据库操作的接口，包括保存、更新和加载传输消息。
 * 使用批量更新队列机制来优化性能，每5秒同步一次进度数据。
 */
class DatabaseSync {
    constructor() {
        this.syncQueue = [];
        this.syncInterval = 5000; // 5秒同步一次
        this.lastSyncTime = new Map();
        this.syncTimer = null;
        this.startSyncTimer();
    }
    
    /**
     * 保存新的传输消息到数据库
     * @param {Object} messageData - 消息数据
     * @returns {Promise<Object>} 保存结果
     */
    async saveTransferMessage(messageData) {
        try {
            const response = await fetch('/api/p2p/messages', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(messageData)
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('Failed to save transfer message:', error);
            throw error;
        }
    }
    
    /**
     * 更新传输状态
     * @param {string} transferId - 传输ID
     * @param {string} status - 新状态
     * @param {Object} additionalData - 附加数据
     * @returns {Promise<Object>} 更新结果
     */
    async updateTransferStatus(transferId, status, additionalData = {}) {
        try {
            const response = await fetch(`/api/p2p/messages/${transferId}/status`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status, ...additionalData })
            });
            
            if (!response.ok) {
                // 404表示消息不存在，这是正常情况（可能是旧会话）
                if (response.status === 404) {
                    console.warn(`[DatabaseSync] Transfer message not found: ${transferId} (skipping update)`);
                    return { success: true, skipped: true };
                }
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            // 只在非404错误时记录错误
            if (!error.message.includes('404')) {
                console.error('[DatabaseSync] Failed to update transfer status:', error);
            }
            throw error;
        }
    }
    
    /**
     * 更新传输进度（批量处理）
     * @param {string} transferId - 传输ID
     * @param {Object} progressData - 进度数据
     */
    async updateTransferProgress(transferId, progressData) {
        // 添加到同步队列
        this.syncQueue.push({ transferId, progressData });
    }
    
    /**
     * 启动定时同步机制
     */
    startSyncTimer() {
        // 清除现有定时器
        if (this.syncTimer) {
            clearInterval(this.syncTimer);
        }
        
        // 定期同步队列中的进度数据
        this.syncTimer = setInterval(async () => {
            if (this.syncQueue.length === 0) return;
            
            const batch = [...this.syncQueue];
            this.syncQueue = [];
            
            try {
                const response = await fetch('/api/p2p/messages/batch-update', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ updates: batch })
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                console.log(`Synced ${batch.length} progress updates to database`);
            } catch (error) {
                console.error('Failed to sync progress batch:', error);
                // 重新加入队列
                this.syncQueue.push(...batch);
            }
        }, this.syncInterval);
    }
    
    /**
     * 停止定时同步
     */
    stopSyncTimer() {
        if (this.syncTimer) {
            clearInterval(this.syncTimer);
            this.syncTimer = null;
        }
    }
    
    /**
     * 从数据库加载传输历史
     * @param {string} userId - 用户ID
     * @param {string} chatId - 聊天ID
     * @returns {Promise<Array>} 传输消息列表
     */
    async loadTransferHistory(userId, chatId) {
        try {
            const response = await fetch(`/api/p2p/messages?userId=${userId}&chatId=${chatId}`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            return data.messages || [];
        } catch (error) {
            console.error('Failed to load transfer history:', error);
            return [];
        }
    }
    
    /**
     * 立即同步所有待处理的更新
     * @returns {Promise<void>}
     */
    async flushQueue() {
        if (this.syncQueue.length === 0) return;
        
        const batch = [...this.syncQueue];
        this.syncQueue = [];
        
        try {
            const response = await fetch('/api/p2p/messages/batch-update', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ updates: batch })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            console.log(`Flushed ${batch.length} progress updates to database`);
        } catch (error) {
            console.error('Failed to flush progress batch:', error);
            // 重新加入队列
            this.syncQueue.push(...batch);
            throw error;
        }
    }
    
    /**
     * 检查是否应该同步到数据库
     * @param {string} transferId - 传输ID
     * @returns {boolean} 是否应该同步
     */
    shouldSyncToDb(transferId) {
        const lastSync = this.lastSyncTime.get(transferId) || 0;
        const now = Date.now();
        
        if (now - lastSync >= this.syncInterval) {
            this.lastSyncTime.set(transferId, now);
            return true;
        }
        
        return false;
    }
    
    /**
     * 清理资源
     */
    destroy() {
        this.stopSyncTimer();
        this.syncQueue = [];
        this.lastSyncTime.clear();
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DatabaseSync;
}
