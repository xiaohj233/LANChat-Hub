/**
 * P2PTransferManager - 管理P2P传输的整个生命周期
 * 
 * 该类负责管理多个并发传输，集成SpeedCalculator进行速度计算，
 * 集成DatabaseSync进行状态同步，并提供状态回调接口。
 */
class P2PTransferManagerNew {
    constructor() {
        this.activeTransfers = new Map();
        this.statusCallbacks = new Map();
        this.speedCalculators = new Map();
        this.dbSync = new DatabaseSync();
        this.lastSyncTime = new Map();
    }
    
    /**
     * 生成传输ID
     * @returns {string} 传输ID
     */
    generateTransferId() {
        return `transfer-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }
    
    /**
     * 启动P2P传输
     * @param {Object} fileInfo - 文件信息
     * @param {string} targetUserId - 目标用户ID
     * @param {string} chatId - 聊天ID
     * @returns {Promise<string>} 传输ID
     */
    async initiateTransfer(fileInfo, targetUserId, chatId) {
        const transferId = this.generateTransferId();
        const speedCalc = new SpeedCalculator();
        this.speedCalculators.set(transferId, speedCalc);
        
        // 创建传输记录
        const transferData = {
            id: transferId,
            senderId: window.currentUserId || 'unknown',
            receiverId: targetUserId,
            chatId: chatId,
            timestamp: Date.now() / 1000,  // 转换为秒级时间戳，与普通消息保持一致
            fileInfo: {
                name: fileInfo.name,
                size: fileInfo.size,
                type: fileInfo.type,
                hash: fileInfo.hash || ''
            },
            transferInfo: {
                id: transferId,
                method: 'p2p',
                status: 'pending',
                progress: 0,
                speed: 0,
                avgSpeed: 0,
                estimatedTime: null,
                startTime: null,
                endTime: null,
                bytesTransferred: 0,
                isValid: true
            }
        };
        
        // 保存到数据库
        try {
            await this.dbSync.saveTransferMessage(transferData);
            this.activeTransfers.set(transferId, transferData);
            console.log(`Transfer ${transferId} initiated`);
            return transferId;
        } catch (error) {
            console.error('Failed to initiate transfer:', error);
            throw error;
        }
    }
    
    /**
     * 处理接收方的响应
     * @param {string} transferId - 传输ID
     * @param {string} response - 响应类型 ('accepted' 或 'rejected')
     * @returns {Promise<void>}
     */
    async handleTransferResponse(transferId, response) {
        const transfer = this.activeTransfers.get(transferId);
        if (!transfer) {
            console.warn(`Transfer ${transferId} not found`);
            return;
        }
        
        // 更新状态
        transfer.transferInfo.status = response;
        
        if (response === 'accepted') {
            transfer.transferInfo.startTime = Date.now();
        }
        
        // 更新数据库
        await this.dbSync.updateTransferStatus(transferId, response, {
            startTime: transfer.transferInfo.startTime
        });
        
        // 触发回调
        this.notifyStatusChange(transferId, response);
        
        console.log(`Transfer ${transferId} ${response}`);
    }
    
    /**
     * 更新传输进度和速度
     * @param {string} transferId - 传输ID
     * @param {number} bytesTransferred - 已传输字节数
     * @param {number} totalBytes - 总字节数
     */
    updateTransferProgress(transferId, bytesTransferred, totalBytes) {
        const transfer = this.activeTransfers.get(transferId);
        if (!transfer) {
            console.warn(`Transfer ${transferId} not found`);
            return;
        }
        
        const speedCalc = this.speedCalculators.get(transferId);
        if (!speedCalc) {
            console.warn(`SpeedCalculator for ${transferId} not found`);
            return;
        }
        
        // 计算速度和进度
        const speed = speedCalc.calculateSpeed(bytesTransferred);
        const avgSpeed = speedCalc.getAverageSpeed();
        const estimatedTime = speedCalc.estimateRemainingTime(bytesTransferred, totalBytes);
        const progress = (bytesTransferred / totalBytes) * 100;
        
        // 更新传输信息
        transfer.transferInfo.progress = progress;
        transfer.transferInfo.speed = speed;
        transfer.transferInfo.avgSpeed = avgSpeed;
        transfer.transferInfo.estimatedTime = estimatedTime;
        transfer.transferInfo.bytesTransferred = bytesTransferred;
        
        // 更新数据库（每5秒一次）
        if (this.shouldSyncToDb(transferId)) {
            this.dbSync.updateTransferProgress(transferId, {
                progress,
                speed,
                avgSpeed,
                estimatedTime,
                bytesTransferred
            });
        }
        
        // 实时更新UI
        this.notifyProgressUpdate(transferId, {
            progress,
            speed,
            avgSpeed,
            estimatedTime,
            bytesTransferred
        });
    }
    
    /**
     * 标记传输完成
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async completeTransfer(transferId) {
        const transfer = this.activeTransfers.get(transferId);
        if (!transfer) {
            console.warn(`Transfer ${transferId} not found`);
            return;
        }
        
        const speedCalc = this.speedCalculators.get(transferId);
        const avgSpeed = speedCalc ? speedCalc.getAverageSpeed() : 0;
        
        transfer.transferInfo.status = 'completed';
        transfer.transferInfo.endTime = Date.now();
        transfer.transferInfo.progress = 100;
        transfer.transferInfo.avgSpeed = avgSpeed;
        
        // 更新数据库
        await this.dbSync.updateTransferStatus(transferId, 'completed', {
            endTime: transfer.transferInfo.endTime,
            avgSpeed: avgSpeed,
            progress: 100
        });
        
        // 触发回调
        this.notifyStatusChange(transferId, 'completed');
        
        // 清理资源
        this.cleanupTransfer(transferId);
        
        console.log(`Transfer ${transferId} completed`);
    }
    
    /**
     * 标记传输失败
     * @param {string} transferId - 传输ID
     * @param {string} reason - 失败原因
     * @returns {Promise<void>}
     */
    async failTransfer(transferId, reason) {
        const transfer = this.activeTransfers.get(transferId);
        if (!transfer) {
            console.warn(`Transfer ${transferId} not found`);
            return;
        }
        
        transfer.transferInfo.status = 'failed';
        transfer.transferInfo.endTime = Date.now();
        
        // 更新数据库
        await this.dbSync.updateTransferStatus(transferId, 'failed', {
            endTime: transfer.transferInfo.endTime,
            failureReason: reason
        });
        
        // 触发回调
        this.notifyStatusChange(transferId, 'failed', { reason });
        
        // 清理资源
        this.cleanupTransfer(transferId);
        
        console.log(`Transfer ${transferId} failed: ${reason}`);
    }
    
    /**
     * 取消传输
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async cancelTransfer(transferId) {
        const transfer = this.activeTransfers.get(transferId);
        if (!transfer) {
            console.warn(`Transfer ${transferId} not found`);
            return;
        }
        
        transfer.transferInfo.status = 'cancelled';
        transfer.transferInfo.endTime = Date.now();
        
        // 更新数据库
        await this.dbSync.updateTransferStatus(transferId, 'cancelled', {
            endTime: transfer.transferInfo.endTime
        });
        
        // 触发回调
        this.notifyStatusChange(transferId, 'cancelled');
        
        // 清理资源
        this.cleanupTransfer(transferId);
        
        console.log(`Transfer ${transferId} cancelled`);
    }
    
    /**
     * 检查是否应该同步到数据库
     * @param {string} transferId - 传输ID
     * @returns {boolean} 是否应该同步
     */
    shouldSyncToDb(transferId) {
        return this.dbSync.shouldSyncToDb(transferId);
    }
    
    /**
     * 注册状态回调
     * @param {string} transferId - 传输ID
     * @param {Function} callback - 回调函数
     */
    registerStatusCallback(transferId, callback) {
        if (!this.statusCallbacks.has(transferId)) {
            this.statusCallbacks.set(transferId, []);
        }
        this.statusCallbacks.get(transferId).push(callback);
    }
    
    /**
     * 通知状态变化
     * @param {string} transferId - 传输ID
     * @param {string} status - 新状态
     * @param {Object} data - 附加数据
     */
    notifyStatusChange(transferId, status, data = {}) {
        const callbacks = this.statusCallbacks.get(transferId);
        if (callbacks) {
            callbacks.forEach(callback => {
                try {
                    callback({ status, ...data });
                } catch (error) {
                    console.error('Error in status callback:', error);
                }
            });
        }
    }
    
    /**
     * 通知进度更新
     * @param {string} transferId - 传输ID
     * @param {Object} progressData - 进度数据
     */
    notifyProgressUpdate(transferId, progressData) {
        const callbacks = this.statusCallbacks.get(transferId);
        if (callbacks) {
            callbacks.forEach(callback => {
                try {
                    callback({ type: 'progress', ...progressData });
                } catch (error) {
                    console.error('Error in progress callback:', error);
                }
            });
        }
    }
    
    /**
     * 清理传输资源
     * @param {string} transferId - 传输ID
     */
    cleanupTransfer(transferId) {
        // 清理速度计算器
        if (this.speedCalculators.has(transferId)) {
            this.speedCalculators.delete(transferId);
        }
        
        // 清理回调
        if (this.statusCallbacks.has(transferId)) {
            this.statusCallbacks.delete(transferId);
        }
        
        // 从活跃传输中移除
        this.activeTransfers.delete(transferId);
        
        console.log(`Cleaned up resources for transfer ${transferId}`);
    }
    
    /**
     * 获取传输信息
     * @param {string} transferId - 传输ID
     * @returns {Object|null} 传输信息
     */
    getTransfer(transferId) {
        return this.activeTransfers.get(transferId) || null;
    }
    
    /**
     * 获取所有活跃传输
     * @returns {Array} 活跃传输列表
     */
    getActiveTransfers() {
        return Array.from(this.activeTransfers.values());
    }
    
    /**
     * 清理所有资源
     */
    destroy() {
        this.activeTransfers.clear();
        this.statusCallbacks.clear();
        this.speedCalculators.clear();
        this.lastSyncTime.clear();
        
        if (this.dbSync) {
            this.dbSync.destroy();
        }
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = P2PTransferManagerNew;
}
