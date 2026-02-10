/**
 * StateUpdateOptimizer - 状态更新优化器
 * 
 * 功能:
 * - 状态更新的防抖机制
 * - 批量更新逻辑
 * - 智能更新策略
 * - 优化更新频率
 * 
 * Feature: p2p-frontend-redesign
 * Requirements: 性能优化
 */

class StateUpdateOptimizer {
    constructor() {
        this.updateQueue = new Map();
        this.debounceDelay = 100; // 100ms防抖延迟
        this.batchSize = 10; // 每批处理10个更新
        this.batchDelay = 50; // 批次间隔50ms
        this.pendingBatches = [];
        this.isBatchProcessing = false;
    }
    
    /**
     * 防抖更新
     * @param {string} transferId - 传输ID
     * @param {Object} updateData - 更新数据
     * @param {Function} applyCallback - 应用更新的回调函数
     */
    debounceUpdate(transferId, updateData, applyCallback) {
        // 清除之前的定时器
        if (this.updateQueue.has(transferId)) {
            const existing = this.updateQueue.get(transferId);
            clearTimeout(existing.timer);
            
            // 合并更新数据
            updateData = { ...existing.data, ...updateData };
        }
        
        // 设置新的定时器
        const timer = setTimeout(() => {
            if (applyCallback && typeof applyCallback === 'function') {
                applyCallback(transferId, updateData);
            }
            this.updateQueue.delete(transferId);
        }, this.debounceDelay);
        
        this.updateQueue.set(transferId, { 
            timer, 
            data: updateData,
            callback: applyCallback
        });
    }
    
    /**
     * 立即应用更新（跳过防抖）
     * @param {string} transferId - 传输ID
     * @param {Object} updateData - 更新数据
     * @param {Function} applyCallback - 应用更新的回调函数
     */
    immediateUpdate(transferId, updateData, applyCallback) {
        // 取消任何待处理的防抖更新
        if (this.updateQueue.has(transferId)) {
            const existing = this.updateQueue.get(transferId);
            clearTimeout(existing.timer);
            this.updateQueue.delete(transferId);
        }
        
        // 立即应用更新
        if (applyCallback && typeof applyCallback === 'function') {
            applyCallback(transferId, updateData);
        }
    }
    
    /**
     * 批量更新
     * @param {Array} updates - 更新数组，每个元素包含 {transferId, data, callback}
     */
    batchUpdate(updates) {
        if (!Array.isArray(updates) || updates.length === 0) {
            return;
        }
        
        // 将更新分批
        const batches = [];
        for (let i = 0; i < updates.length; i += this.batchSize) {
            batches.push(updates.slice(i, i + this.batchSize));
        }
        
        // 添加到待处理批次
        this.pendingBatches.push(...batches);
        
        // 如果没有正在处理，开始处理
        if (!this.isBatchProcessing) {
            this.processBatches();
        }
    }
    
    /**
     * 处理批次
     */
    async processBatches() {
        this.isBatchProcessing = true;
        
        while (this.pendingBatches.length > 0) {
            const batch = this.pendingBatches.shift();
            
            // 处理当前批次
            for (const update of batch) {
                if (update.callback && typeof update.callback === 'function') {
                    update.callback(update.transferId, update.data);
                }
            }
            
            // 批次间延迟，避免阻塞UI
            if (this.pendingBatches.length > 0) {
                await new Promise(resolve => setTimeout(resolve, this.batchDelay));
            }
        }
        
        this.isBatchProcessing = false;
    }
    
    /**
     * 智能更新策略
     * @param {string} transferId - 传输ID
     * @param {Object} updateData - 更新数据
     * @param {Function} applyCallback - 应用更新的回调函数
     */
    smartUpdate(transferId, updateData, applyCallback) {
        // 根据更新类型选择策略
        const updateType = updateData.type || this.detectUpdateType(updateData);
        
        switch (updateType) {
            case 'progress':
                // 进度更新使用防抖，避免频繁更新
                this.debounceUpdate(transferId, updateData, applyCallback);
                break;
                
            case 'status':
                // 状态更新立即执行，确保用户及时看到状态变化
                this.immediateUpdate(transferId, updateData, applyCallback);
                break;
                
            case 'speed':
                // 速度更新使用防抖，但延迟更短
                const originalDelay = this.debounceDelay;
                this.debounceDelay = 50; // 50ms延迟
                this.debounceUpdate(transferId, updateData, applyCallback);
                this.debounceDelay = originalDelay;
                break;
                
            case 'validity':
                // 有效性更新立即执行
                this.immediateUpdate(transferId, updateData, applyCallback);
                break;
                
            default:
                // 默认使用防抖
                this.debounceUpdate(transferId, updateData, applyCallback);
                break;
        }
    }
    
    /**
     * 检测更新类型
     * @param {Object} updateData - 更新数据
     * @returns {string} 更新类型
     */
    detectUpdateType(updateData) {
        if (updateData.status !== undefined) {
            return 'status';
        } else if (updateData.progress !== undefined) {
            return 'progress';
        } else if (updateData.speed !== undefined || updateData.avgSpeed !== undefined) {
            return 'speed';
        } else if (updateData.isValid !== undefined) {
            return 'validity';
        }
        return 'unknown';
    }
    
    /**
     * 取消待处理的更新
     * @param {string} transferId - 传输ID
     */
    cancelUpdate(transferId) {
        if (this.updateQueue.has(transferId)) {
            const existing = this.updateQueue.get(transferId);
            clearTimeout(existing.timer);
            this.updateQueue.delete(transferId);
        }
    }
    
    /**
     * 取消所有待处理的更新
     */
    cancelAllUpdates() {
        this.updateQueue.forEach((value, key) => {
            clearTimeout(value.timer);
        });
        this.updateQueue.clear();
        this.pendingBatches = [];
    }
    
    /**
     * 获取待处理更新数量
     * @returns {number} 待处理更新数量
     */
    getPendingUpdateCount() {
        let count = this.updateQueue.size;
        this.pendingBatches.forEach(batch => {
            count += batch.length;
        });
        return count;
    }
    
    /**
     * 强制刷新所有待处理的更新
     */
    flushUpdates() {
        // 立即应用所有防抖更新
        this.updateQueue.forEach((value, transferId) => {
            clearTimeout(value.timer);
            if (value.callback && typeof value.callback === 'function') {
                value.callback(transferId, value.data);
            }
        });
        this.updateQueue.clear();
        
        // 立即处理所有批次
        while (this.pendingBatches.length > 0) {
            const batch = this.pendingBatches.shift();
            for (const update of batch) {
                if (update.callback && typeof update.callback === 'function') {
                    update.callback(update.transferId, update.data);
                }
            }
        }
        
        this.isBatchProcessing = false;
    }
    
    /**
     * 设置防抖延迟
     * @param {number} delay - 延迟时间（毫秒）
     */
    setDebounceDelay(delay) {
        if (typeof delay === 'number' && delay >= 0) {
            this.debounceDelay = delay;
        }
    }
    
    /**
     * 设置批量大小
     * @param {number} size - 批量大小
     */
    setBatchSize(size) {
        if (typeof size === 'number' && size > 0) {
            this.batchSize = size;
        }
    }
    
    /**
     * 设置批次延迟
     * @param {number} delay - 延迟时间（毫秒）
     */
    setBatchDelay(delay) {
        if (typeof delay === 'number' && delay >= 0) {
            this.batchDelay = delay;
        }
    }
    
    /**
     * 获取优化器统计信息
     * @returns {Object} 统计信息
     */
    getStats() {
        return {
            pendingDebounceUpdates: this.updateQueue.size,
            pendingBatches: this.pendingBatches.length,
            totalPendingUpdates: this.getPendingUpdateCount(),
            isBatchProcessing: this.isBatchProcessing,
            config: {
                debounceDelay: this.debounceDelay,
                batchSize: this.batchSize,
                batchDelay: this.batchDelay
            }
        };
    }
    
    /**
     * 销毁优化器
     */
    destroy() {
        this.cancelAllUpdates();
        this.updateQueue.clear();
        this.pendingBatches = [];
        this.isBatchProcessing = false;
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.StateUpdateOptimizer = StateUpdateOptimizer;
}

// 导出供Node.js使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = StateUpdateOptimizer;
}
