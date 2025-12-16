/**
 * ValidityChecker - 负责检测传输消息的有效性
 * 
 * 该类定期检查发送方在线状态和文件可用性，
 * 如果检测到传输失效，会更新数据库并通知相关用户。
 */
class ValidityChecker {
    constructor() {
        this.checkInterval = 30000; // 30秒检查一次
        this.activeChecks = new Map();
        this.dbSync = new DatabaseSync();
    }
    
    /**
     * 启动有效性检查
     * @param {string} transferId - 传输ID
     * @param {Object} fileInfo - 文件信息
     */
    startValidityCheck(transferId, fileInfo) {
        // 如果已经在检查，先停止
        if (this.activeChecks.has(transferId)) {
            this.stopValidityCheck(transferId);
        }
        
        // 定义检查函数
        const checkFunction = async () => {
            try {
                // 检查发送方是否在线
                const senderOnline = await this.isSenderOnline(fileInfo.senderId);
                if (!senderOnline) {
                    await this.markAsExpired(transferId, 'sender_offline');
                    return;
                }
                
                // 检查文件是否存在
                const fileAvailable = await this.isFileAvailable(fileInfo);
                if (!fileAvailable) {
                    await this.markAsExpired(transferId, 'file_unavailable');
                    return;
                }
                
                console.log(`Validity check passed for transfer ${transferId}`);
            } catch (error) {
                console.error(`Validity check failed for transfer ${transferId}:`, error);
            }
        };
        
        // 立即执行一次检查
        checkFunction();
        
        // 设置定期检查
        const intervalId = setInterval(checkFunction, this.checkInterval);
        this.activeChecks.set(transferId, intervalId);
        
        console.log(`Started validity check for transfer ${transferId}`);
    }
    
    /**
     * 停止有效性检查
     * @param {string} transferId - 传输ID
     */
    stopValidityCheck(transferId) {
        const intervalId = this.activeChecks.get(transferId);
        if (intervalId) {
            clearInterval(intervalId);
            this.activeChecks.delete(transferId);
            console.log(`Stopped validity check for transfer ${transferId}`);
        }
    }
    
    /**
     * 标记为失效并更新数据库
     * @param {string} transferId - 传输ID
     * @param {string} reason - 失效原因
     * @returns {Promise<void>}
     */
    async markAsExpired(transferId, reason) {
        try {
            // 更新数据库状态
            await this.dbSync.updateTransferStatus(transferId, 'expired', {
                isValid: false,
                invalidReason: reason,
                invalidTime: Date.now()
            });
            
            console.log(`Transfer ${transferId} marked as expired: ${reason}`);
            
            // 停止有效性检查
            this.stopValidityCheck(transferId);
        } catch (error) {
            console.error(`Failed to mark transfer ${transferId} as expired:`, error);
        }
    }
    
    /**
     * 检查发送方是否在线
     * @param {string} senderId - 发送方ID
     * @returns {Promise<boolean>} 是否在线
     */
    async isSenderOnline(senderId) {
        try {
            const response = await fetch(`/api/users/${senderId}/online-status`);
            
            if (!response.ok) {
                console.warn(`Failed to check sender online status: ${response.status}`);
                return false;
            }
            
            const data = await response.json();
            return data.online === true;
        } catch (error) {
            console.error('Failed to check sender online status:', error);
            return false;
        }
    }
    
    /**
     * 检查文件是否可用
     * @param {Object} fileInfo - 文件信息
     * @returns {Promise<boolean>} 是否可用
     */
    async isFileAvailable(fileInfo) {
        try {
            const response = await fetch('/api/p2p/file-availability', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fileHash: fileInfo.hash,
                    senderId: fileInfo.senderId,
                    fileName: fileInfo.name
                })
            });
            
            if (!response.ok) {
                console.warn(`Failed to check file availability: ${response.status}`);
                return false;
            }
            
            const data = await response.json();
            return data.available === true;
        } catch (error) {
            console.error('Failed to check file availability:', error);
            return false;
        }
    }
    
    /**
     * 手动检查传输有效性
     * @param {string} transferId - 传输ID
     * @param {Object} fileInfo - 文件信息
     * @returns {Promise<Object>} 检查结果
     */
    async checkValidity(transferId, fileInfo) {
        const result = {
            valid: true,
            reason: null
        };
        
        try {
            // 检查发送方是否在线
            const senderOnline = await this.isSenderOnline(fileInfo.senderId);
            if (!senderOnline) {
                result.valid = false;
                result.reason = 'sender_offline';
                return result;
            }
            
            // 检查文件是否存在
            const fileAvailable = await this.isFileAvailable(fileInfo);
            if (!fileAvailable) {
                result.valid = false;
                result.reason = 'file_unavailable';
                return result;
            }
            
            return result;
        } catch (error) {
            console.error('Failed to check validity:', error);
            result.valid = false;
            result.reason = 'check_failed';
            return result;
        }
    }
    
    /**
     * 批量检查多个传输的有效性
     * @param {Array} transfers - 传输列表
     * @returns {Promise<Map>} 检查结果映射
     */
    async batchCheckValidity(transfers) {
        const results = new Map();
        
        const promises = transfers.map(async (transfer) => {
            const result = await this.checkValidity(transfer.id, transfer.fileInfo);
            results.set(transfer.id, result);
            
            // 如果失效，标记为过期
            if (!result.valid) {
                await this.markAsExpired(transfer.id, result.reason);
            }
        });
        
        await Promise.all(promises);
        return results;
    }
    
    /**
     * 停止所有有效性检查
     */
    stopAllChecks() {
        this.activeChecks.forEach((intervalId, transferId) => {
            clearInterval(intervalId);
            console.log(`Stopped validity check for transfer ${transferId}`);
        });
        this.activeChecks.clear();
    }
    
    /**
     * 获取活跃检查数量
     * @returns {number} 活跃检查数量
     */
    getActiveCheckCount() {
        return this.activeChecks.size;
    }
    
    /**
     * 清理资源
     */
    destroy() {
        this.stopAllChecks();
        
        if (this.dbSync) {
            this.dbSync.destroy();
        }
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ValidityChecker;
}
