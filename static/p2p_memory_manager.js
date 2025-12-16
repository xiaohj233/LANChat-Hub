/**
 * MemoryManager - 内存管理器
 * 
 * 功能:
 * - LRU缓存机制
 * - 已完成传输的清理逻辑
 * - 资源释放功能
 * - 限制缓存消息数量（最多100条）
 * 
 * Feature: p2p-frontend-redesign
 * Requirements: 性能优化
 */

/**
 * LRU缓存实现
 */
class LRUCache {
    constructor(capacity) {
        this.capacity = capacity;
        this.cache = new Map();
    }
    
    /**
     * 获取缓存值
     * @param {string} key - 键
     * @returns {*} 值，如果不存在返回null
     */
    get(key) {
        if (!this.cache.has(key)) {
            return null;
        }
        
        // 移到最后（最近使用）
        const value = this.cache.get(key);
        this.cache.delete(key);
        this.cache.set(key, value);
        
        return value;
    }
    
    /**
     * 设置缓存值
     * @param {string} key - 键
     * @param {*} value - 值
     */
    set(key, value) {
        // 如果已存在，先删除
        if (this.cache.has(key)) {
            this.cache.delete(key);
        }
        
        // 如果超过容量，删除最旧的
        if (this.cache.size >= this.capacity) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
        
        this.cache.set(key, value);
    }
    
    /**
     * 检查键是否存在
     * @param {string} key - 键
     * @returns {boolean} 是否存在
     */
    has(key) {
        return this.cache.has(key);
    }
    
    /**
     * 删除缓存值
     * @param {string} key - 键
     * @returns {boolean} 是否删除成功
     */
    delete(key) {
        return this.cache.delete(key);
    }
    
    /**
     * 清空缓存
     */
    clear() {
        this.cache.clear();
    }
    
    /**
     * 获取缓存大小
     * @returns {number} 缓存大小
     */
    size() {
        return this.cache.size;
    }
    
    /**
     * 获取所有键
     * @returns {Array} 键数组
     */
    keys() {
        return Array.from(this.cache.keys());
    }
    
    /**
     * 获取所有值
     * @returns {Array} 值数组
     */
    values() {
        return Array.from(this.cache.values());
    }
    
    /**
     * 遍历缓存
     * @param {Function} callback - 回调函数 (value, key)
     */
    forEach(callback) {
        this.cache.forEach((value, key) => {
            callback(value, key);
        });
    }
}

/**
 * 内存管理器
 */
class MemoryManager {
    constructor() {
        this.maxCachedMessages = 100; // 最多缓存100条消息
        this.messageCache = new LRUCache(this.maxCachedMessages);
        this.speedCalculators = new Map();
        this.callbacks = new Map();
        this.domReferences = new Map();
        this.cleanupInterval = 60000; // 60秒清理一次
        this.retentionPeriod = 24 * 60 * 60 * 1000; // 24小时保留期
        this.cleanupTimer = null;
        
        this.startCleanupTimer();
    }
    
    /**
     * 缓存消息
     * @param {string} messageId - 消息ID
     * @param {Object} messageData - 消息数据
     */
    cacheMessage(messageId, messageData) {
        this.messageCache.set(messageId, {
            ...messageData,
            cachedAt: Date.now()
        });
    }
    
    /**
     * 获取缓存的消息
     * @param {string} messageId - 消息ID
     * @returns {Object|null} 消息数据
     */
    getCachedMessage(messageId) {
        return this.messageCache.get(messageId);
    }
    
    /**
     * 注册速度计算器
     * @param {string} transferId - 传输ID
     * @param {Object} calculator - 速度计算器实例
     */
    registerSpeedCalculator(transferId, calculator) {
        this.speedCalculators.set(transferId, calculator);
    }
    
    /**
     * 获取速度计算器
     * @param {string} transferId - 传输ID
     * @returns {Object|null} 速度计算器实例
     */
    getSpeedCalculator(transferId) {
        return this.speedCalculators.get(transferId) || null;
    }
    
    /**
     * 注册回调函数
     * @param {string} transferId - 传输ID
     * @param {Object} callbacks - 回调函数对象
     */
    registerCallbacks(transferId, callbacks) {
        this.callbacks.set(transferId, callbacks);
    }
    
    /**
     * 获取回调函数
     * @param {string} transferId - 传输ID
     * @returns {Object|null} 回调函数对象
     */
    getCallbacks(transferId) {
        return this.callbacks.get(transferId) || null;
    }
    
    /**
     * 注册DOM引用
     * @param {string} transferId - 传输ID
     * @param {HTMLElement} element - DOM元素
     */
    registerDOMReference(transferId, element) {
        this.domReferences.set(transferId, element);
    }
    
    /**
     * 获取DOM引用
     * @param {string} transferId - 传输ID
     * @returns {HTMLElement|null} DOM元素
     */
    getDOMReference(transferId) {
        return this.domReferences.get(transferId) || null;
    }
    
    /**
     * 清理已完成的传输数据
     */
    cleanupCompletedTransfers() {
        const completedStatuses = ['completed', 'rejected', 'expired', 'cancelled'];
        const now = Date.now();
        const messagesToRemove = [];
        
        // 遍历缓存的消息
        this.messageCache.forEach((message, id) => {
            const status = message.transferInfo?.status || message.status;
            const timestamp = message.timestamp || message.cachedAt || 0;
            
            if (completedStatuses.includes(status)) {
                const age = now - timestamp;
                if (age > this.retentionPeriod) {
                    messagesToRemove.push(id);
                }
            }
        });
        
        // 移除过期的消息
        messagesToRemove.forEach(id => {
            this.releaseResources(id);
        });
        
        console.log(`[MemoryManager] Cleaned up ${messagesToRemove.length} completed transfers`);
    }
    
    /**
     * 启动清理定时器
     */
    startCleanupTimer() {
        if (this.cleanupTimer) {
            clearInterval(this.cleanupTimer);
        }
        
        this.cleanupTimer = setInterval(() => {
            this.cleanupCompletedTransfers();
        }, this.cleanupInterval);
    }
    
    /**
     * 停止清理定时器
     */
    stopCleanupTimer() {
        if (this.cleanupTimer) {
            clearInterval(this.cleanupTimer);
            this.cleanupTimer = null;
        }
    }
    
    /**
     * 释放资源
     * @param {string} transferId - 传输ID
     */
    releaseResources(transferId) {
        // 清理速度计算器
        if (this.speedCalculators.has(transferId)) {
            const calculator = this.speedCalculators.get(transferId);
            if (calculator && typeof calculator.destroy === 'function') {
                calculator.destroy();
            }
            this.speedCalculators.delete(transferId);
        }
        
        // 清理回调函数
        if (this.callbacks.has(transferId)) {
            this.callbacks.delete(transferId);
        }
        
        // 清理DOM引用
        if (this.domReferences.has(transferId)) {
            const element = this.domReferences.get(transferId);
            if (element && element.parentNode) {
                // 不直接删除DOM元素，只清除引用
                // DOM元素的删除应该由UI层控制
            }
            this.domReferences.delete(transferId);
        }
        
        // 清理消息缓存
        this.messageCache.delete(transferId);
    }
    
    /**
     * 强制清理所有资源
     */
    forceCleanup() {
        // 清理所有速度计算器
        this.speedCalculators.forEach((calculator, transferId) => {
            if (calculator && typeof calculator.destroy === 'function') {
                calculator.destroy();
            }
        });
        this.speedCalculators.clear();
        
        // 清理所有回调
        this.callbacks.clear();
        
        // 清理所有DOM引用
        this.domReferences.clear();
        
        // 清理消息缓存
        this.messageCache.clear();
        
        console.log('[MemoryManager] Force cleanup completed');
    }
    
    /**
     * 获取内存使用统计
     * @returns {Object} 统计信息
     */
    getMemoryStats() {
        return {
            cachedMessages: this.messageCache.size(),
            speedCalculators: this.speedCalculators.size,
            callbacks: this.callbacks.size,
            domReferences: this.domReferences.size,
            maxCapacity: this.maxCachedMessages,
            retentionPeriod: this.retentionPeriod,
            cleanupInterval: this.cleanupInterval
        };
    }
    
    /**
     * 设置最大缓存数量
     * @param {number} max - 最大数量
     */
    setMaxCachedMessages(max) {
        if (typeof max === 'number' && max > 0) {
            this.maxCachedMessages = max;
            // 重新创建缓存以应用新容量
            const oldCache = this.messageCache;
            this.messageCache = new LRUCache(max);
            
            // 迁移现有数据（只保留最新的max条）
            const keys = oldCache.keys();
            const keepCount = Math.min(keys.length, max);
            for (let i = keys.length - keepCount; i < keys.length; i++) {
                const key = keys[i];
                this.messageCache.set(key, oldCache.get(key));
            }
        }
    }
    
    /**
     * 设置保留期
     * @param {number} period - 保留期（毫秒）
     */
    setRetentionPeriod(period) {
        if (typeof period === 'number' && period > 0) {
            this.retentionPeriod = period;
        }
    }
    
    /**
     * 设置清理间隔
     * @param {number} interval - 清理间隔（毫秒）
     */
    setCleanupInterval(interval) {
        if (typeof interval === 'number' && interval > 0) {
            this.cleanupInterval = interval;
            this.startCleanupTimer(); // 重启定时器
        }
    }
    
    /**
     * 检查是否需要清理
     * @returns {boolean} 是否需要清理
     */
    needsCleanup() {
        return this.messageCache.size() >= this.maxCachedMessages * 0.9; // 90%容量时需要清理
    }
    
    /**
     * 获取可清理的消息数量
     * @returns {number} 可清理的消息数量
     */
    getCleanableCount() {
        const completedStatuses = ['completed', 'rejected', 'expired', 'cancelled'];
        const now = Date.now();
        let count = 0;
        
        this.messageCache.forEach((message, id) => {
            const status = message.transferInfo?.status || message.status;
            const timestamp = message.timestamp || message.cachedAt || 0;
            
            if (completedStatuses.includes(status)) {
                const age = now - timestamp;
                if (age > this.retentionPeriod) {
                    count++;
                }
            }
        });
        
        return count;
    }
    
    /**
     * 销毁内存管理器
     */
    destroy() {
        this.stopCleanupTimer();
        this.forceCleanup();
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.LRUCache = LRUCache;
    window.MemoryManager = MemoryManager;
}

// 导出供Node.js使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MemoryManager, LRUCache };
}
