/**
 * DatabaseQueryOptimizer - 数据库查询优化器
 * 
 * 功能:
 * - 使用索引优化查询性能
 * - 实现分页查询
 * - 添加查询结果缓存
 * - 优化批量更新操作
 * 
 */

class DatabaseQueryOptimizer {
    constructor() {
        this.queryCache = new Map();
        this.cacheTimeout = 30000; // 30秒缓存过期
        this.pageSize = 50; // 每页50条记录
        this.maxBatchSize = 100; // 最大批量更新数量
    }
    
    /**
     * 获取活跃传输（使用索引优化）
     * @param {string} userId - 用户ID
     * @param {number} limit - 限制数量
     * @returns {Promise<Array>} 活跃传输列表
     */
    async getActiveTransfers(userId, limit = 50) {
        const cacheKey = `active_${userId}_${limit}`;
        
        // 检查缓存
        const cached = this.getCachedResult(cacheKey);
        if (cached) {
            return cached;
        }
        
        try {
            // 使用索引优化的查询
            const response = await fetch(`/api/p2p/messages/active?userId=${userId}&limit=${limit}`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            const result = data.messages || [];
            
            // 缓存结果
            this.cacheResult(cacheKey, result);
            
            return result;
        } catch (error) {
            console.error('Failed to get active transfers:', error);
            return [];
        }
    }
    
    /**
     * 分页获取传输历史
     * @param {string} chatId - 聊天ID
     * @param {number} page - 页码（从0开始）
     * @param {number} pageSize - 每页大小
     * @returns {Promise<Object>} 分页结果 {messages, total, hasMore}
     */
    async getTransferHistoryPaginated(chatId, page = 0, pageSize = null) {
        pageSize = pageSize || this.pageSize;
        const offset = page * pageSize;
        const cacheKey = `history_${chatId}_${page}_${pageSize}`;
        
        // 检查缓存
        const cached = this.getCachedResult(cacheKey);
        if (cached) {
            return cached;
        }
        
        try {
            const response = await fetch(
                `/api/p2p/messages/history?chatId=${chatId}&limit=${pageSize}&offset=${offset}`
            );
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            const result = {
                messages: data.messages || [],
                total: data.total || 0,
                hasMore: data.hasMore || false,
                page: page,
                pageSize: pageSize
            };
            
            // 缓存结果
            this.cacheResult(cacheKey, result);
            
            return result;
        } catch (error) {
            console.error('Failed to get transfer history:', error);
            return {
                messages: [],
                total: 0,
                hasMore: false,
                page: page,
                pageSize: pageSize
            };
        }
    }
    
    /**
     * 批量更新进度（优化版）
     * @param {Array} updates - 更新数组
     * @returns {Promise<Object>} 更新结果
     */
    async batchUpdateProgress(updates) {
        if (!Array.isArray(updates) || updates.length === 0) {
            return { success: true, updatedCount: 0 };
        }
        
        // 如果更新数量超过最大批量大小，分批处理
        if (updates.length > this.maxBatchSize) {
            return await this.batchUpdateProgressChunked(updates);
        }
        
        try {
            const response = await fetch('/api/p2p/messages/batch-update', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ updates })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();
            
            // 清除相关缓存
            this.invalidateRelatedCache(updates);
            
            return result;
        } catch (error) {
            console.error('Failed to batch update progress:', error);
            throw error;
        }
    }
    
    /**
     * 分块批量更新进度
     * @param {Array} updates - 更新数组
     * @returns {Promise<Object>} 更新结果
     */
    async batchUpdateProgressChunked(updates) {
        const chunks = [];
        for (let i = 0; i < updates.length; i += this.maxBatchSize) {
            chunks.push(updates.slice(i, i + this.maxBatchSize));
        }
        
        let totalUpdated = 0;
        const errors = [];
        
        for (const chunk of chunks) {
            try {
                const result = await this.batchUpdateProgress(chunk);
                totalUpdated += result.updatedCount || 0;
            } catch (error) {
                errors.push(error);
            }
        }
        
        if (errors.length > 0) {
            console.error(`Failed to update ${errors.length} chunks`);
        }
        
        return {
            success: errors.length === 0,
            updatedCount: totalUpdated,
            errors: errors.length
        };
    }
    
    /**
     * 按状态查询传输消息
     * @param {string} userId - 用户ID
     * @param {Array<string>} statuses - 状态数组
     * @param {number} limit - 限制数量
     * @returns {Promise<Array>} 传输消息列表
     */
    async getTransfersByStatus(userId, statuses, limit = 50) {
        const statusStr = statuses.join(',');
        const cacheKey = `status_${userId}_${statusStr}_${limit}`;
        
        // 检查缓存
        const cached = this.getCachedResult(cacheKey);
        if (cached) {
            return cached;
        }
        
        try {
            const response = await fetch(
                `/api/p2p/messages/by-status?userId=${userId}&statuses=${statusStr}&limit=${limit}`
            );
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            const result = data.messages || [];
            
            // 缓存结果
            this.cacheResult(cacheKey, result);
            
            return result;
        } catch (error) {
            console.error('Failed to get transfers by status:', error);
            return [];
        }
    }
    
    /**
     * 获取传输统计信息
     * @param {string} userId - 用户ID
     * @param {string} chatId - 聊天ID（可选）
     * @returns {Promise<Object>} 统计信息
     */
    async getTransferStats(userId, chatId = null) {
        const cacheKey = `stats_${userId}_${chatId || 'all'}`;
        
        // 检查缓存
        const cached = this.getCachedResult(cacheKey);
        if (cached) {
            return cached;
        }
        
        try {
            let url = `/api/p2p/messages/stats?userId=${userId}`;
            if (chatId) {
                url += `&chatId=${chatId}`;
            }
            
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const result = await response.json();
            
            // 缓存结果
            this.cacheResult(cacheKey, result);
            
            return result;
        } catch (error) {
            console.error('Failed to get transfer stats:', error);
            return {
                total: 0,
                active: 0,
                completed: 0,
                failed: 0
            };
        }
    }
    
    /**
     * 缓存查询结果
     * @param {string} key - 缓存键
     * @param {*} value - 缓存值
     */
    cacheResult(key, value) {
        this.queryCache.set(key, {
            value,
            timestamp: Date.now()
        });
    }
    
    /**
     * 获取缓存的结果
     * @param {string} key - 缓存键
     * @returns {*} 缓存值，如果不存在或过期返回null
     */
    getCachedResult(key) {
        const cached = this.queryCache.get(key);
        if (!cached) {
            return null;
        }
        
        const age = Date.now() - cached.timestamp;
        if (age > this.cacheTimeout) {
            this.queryCache.delete(key);
            return null;
        }
        
        return cached.value;
    }
    
    /**
     * 使缓存失效
     * @param {string} key - 缓存键（支持通配符）
     */
    invalidateCache(key) {
        if (key.includes('*')) {
            // 通配符匹配
            const pattern = new RegExp(key.replace('*', '.*'));
            const keysToDelete = [];
            
            this.queryCache.forEach((value, cacheKey) => {
                if (pattern.test(cacheKey)) {
                    keysToDelete.push(cacheKey);
                }
            });
            
            keysToDelete.forEach(k => this.queryCache.delete(k));
        } else {
            this.queryCache.delete(key);
        }
    }
    
    /**
     * 使相关缓存失效
     * @param {Array} updates - 更新数组
     */
    invalidateRelatedCache(updates) {
        const userIds = new Set();
        const chatIds = new Set();
        
        updates.forEach(update => {
            if (update.userId) userIds.add(update.userId);
            if (update.chatId) chatIds.add(update.chatId);
        });
        
        // 清除相关用户和聊天的缓存
        userIds.forEach(userId => {
            this.invalidateCache(`active_${userId}_*`);
            this.invalidateCache(`status_${userId}_*`);
            this.invalidateCache(`stats_${userId}_*`);
        });
        
        chatIds.forEach(chatId => {
            this.invalidateCache(`history_${chatId}_*`);
            this.invalidateCache(`stats_*_${chatId}`);
        });
    }
    
    /**
     * 清空所有缓存
     */
    clearCache() {
        this.queryCache.clear();
    }
    
    /**
     * 获取缓存统计信息
     * @returns {Object} 统计信息
     */
    getCacheStats() {
        let validCount = 0;
        let expiredCount = 0;
        const now = Date.now();
        
        this.queryCache.forEach((cached, key) => {
            const age = now - cached.timestamp;
            if (age > this.cacheTimeout) {
                expiredCount++;
            } else {
                validCount++;
            }
        });
        
        return {
            total: this.queryCache.size,
            valid: validCount,
            expired: expiredCount,
            cacheTimeout: this.cacheTimeout,
            pageSize: this.pageSize,
            maxBatchSize: this.maxBatchSize
        };
    }
    
    /**
     * 设置缓存超时时间
     * @param {number} timeout - 超时时间（毫秒）
     */
    setCacheTimeout(timeout) {
        if (typeof timeout === 'number' && timeout > 0) {
            this.cacheTimeout = timeout;
        }
    }
    
    /**
     * 设置页面大小
     * @param {number} size - 页面大小
     */
    setPageSize(size) {
        if (typeof size === 'number' && size > 0) {
            this.pageSize = size;
        }
    }
    
    /**
     * 设置最大批量大小
     * @param {number} size - 最大批量大小
     */
    setMaxBatchSize(size) {
        if (typeof size === 'number' && size > 0) {
            this.maxBatchSize = size;
        }
    }
    
    /**
     * 预加载下一页
     * @param {string} chatId - 聊天ID
     * @param {number} currentPage - 当前页码
     */
    async preloadNextPage(chatId, currentPage) {
        // 在后台预加载下一页，不阻塞当前操作
        setTimeout(async () => {
            try {
                await this.getTransferHistoryPaginated(chatId, currentPage + 1);
            } catch (error) {
                // 预加载失败不影响主流程
                console.debug('Preload next page failed:', error);
            }
        }, 100);
    }
    
    /**
     * 销毁优化器
     */
    destroy() {
        this.clearCache();
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.DatabaseQueryOptimizer = DatabaseQueryOptimizer;
}

// 导出供Node.js使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DatabaseQueryOptimizer;
}
