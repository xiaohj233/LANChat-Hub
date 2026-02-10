/**
 * P2P传输前端重新设计 - JavaScript类型定义
 * 

/**
 * 传输状态枚举
 * @enum {string}
 */
const TransferStatus = {
    PENDING: 'pending',           // 等待响应
    ACCEPTED: 'accepted',         // 已接收
    REJECTED: 'rejected',         // 已拒绝
    CONNECTING: 'connecting',     // 连接中
    TRANSFERRING: 'transferring', // 传输中
    COMPLETED: 'completed',       // 已完成
    FAILED: 'failed',            // 传输失败
    CANCELLED: 'cancelled',       // 已取消
    EXPIRED: 'expired'           // 已失效
};

/**
 * 文件信息类
 */
class FileInfo {
    /**
     * @param {string} name - 文件名
     * @param {number} size - 文件大小（字节）
     * @param {string} [type] - 文件MIME类型
     * @param {string} [hash] - 文件哈希值
     */
    constructor(name, size, type = null, hash = null) {
        this.name = name;
        this.size = size;
        this.type = type;
        this.hash = hash;
    }

    /**
     * 转换为普通对象
     * @returns {Object}
     */
    toObject() {
        return {
            name: this.name,
            size: this.size,
            type: this.type,
            hash: this.hash
        };
    }

    /**
     * 从普通对象创建实例
     * @param {Object} data
     * @returns {FileInfo}
     */
    static fromObject(data) {
        return new FileInfo(
            data.name,
            data.size,
            data.type,
            data.hash
        );
    }
}

/**
 * 传输信息类
 */
class TransferInfo {
    /**
     * @param {string} id - 传输ID
     * @param {Object} options - 可选参数
     */
    constructor(id, options = {}) {
        this.id = id;
        this.method = options.method || 'p2p';
        this.status = options.status || TransferStatus.PENDING;
        this.progress = options.progress || 0;
        this.speed = options.speed || 0;
        this.avgSpeed = options.avgSpeed || 0;
        this.estimatedTime = options.estimatedTime || null;
        this.startTime = options.startTime || null;
        this.endTime = options.endTime || null;
        this.bytesTransferred = options.bytesTransferred || 0;
        this.isValid = options.isValid !== undefined ? options.isValid : true;
        this.invalidReason = options.invalidReason || null;
        this.invalidTime = options.invalidTime || null;
    }

    /**
     * 转换为普通对象
     * @returns {Object}
     */
    toObject() {
        return {
            id: this.id,
            method: this.method,
            status: this.status,
            progress: this.progress,
            speed: this.speed,
            avgSpeed: this.avgSpeed,
            estimatedTime: this.estimatedTime,
            startTime: this.startTime,
            endTime: this.endTime,
            bytesTransferred: this.bytesTransferred,
            isValid: this.isValid,
            invalidReason: this.invalidReason,
            invalidTime: this.invalidTime
        };
    }

    /**
     * 从普通对象创建实例
     * @param {Object} data
     * @returns {TransferInfo}
     */
    static fromObject(data) {
        return new TransferInfo(data.id, {
            method: data.method,
            status: data.status,
            progress: data.progress,
            speed: data.speed,
            avgSpeed: data.avgSpeed,
            estimatedTime: data.estimatedTime,
            startTime: data.startTime,
            endTime: data.endTime,
            bytesTransferred: data.bytesTransferred,
            isValid: data.isValid,
            invalidReason: data.invalidReason,
            invalidTime: data.invalidTime
        });
    }
}

/**
 * UI配置类
 */
class UIConfig {
    /**
     * @param {Object} options - 可选参数
     */
    constructor(options = {}) {
        this.showActions = options.showActions !== undefined ? options.showActions : true;
        this.allowCancel = options.allowCancel !== undefined ? options.allowCancel : true;
        this.showProgress = options.showProgress !== undefined ? options.showProgress : true;
    }

    /**
     * 转换为普通对象
     * @returns {Object}
     */
    toObject() {
        return {
            showActions: this.showActions,
            allowCancel: this.allowCancel,
            showProgress: this.showProgress
        };
    }

    /**
     * 从普通对象创建实例
     * @param {Object} data
     * @returns {UIConfig}
     */
    static fromObject(data) {
        return new UIConfig({
            showActions: data.showActions,
            allowCancel: data.allowCancel,
            showProgress: data.showProgress
        });
    }
}

/**
 * 传输消息数据模型类
 */
class TransferMessageData {
    /**
     * @param {Object} options - 消息参数
     */
    constructor(options = {}) {
        this.id = options.id || `msg-${this.generateId()}`;
        this.type = options.type || 'p2p_transfer';
        this.senderId = options.senderId || '';
        this.receiverId = options.receiverId || '';
        this.chatId = options.chatId || '';
        this.timestamp = options.timestamp || Date.now();
        
        // 嵌套对象
        this.fileInfo = options.fileInfo instanceof FileInfo 
            ? options.fileInfo 
            : (options.fileInfo ? FileInfo.fromObject(options.fileInfo) : null);
        
        this.transferInfo = options.transferInfo instanceof TransferInfo 
            ? options.transferInfo 
            : (options.transferInfo ? TransferInfo.fromObject(options.transferInfo) : null);
        
        this.ui = options.ui instanceof UIConfig 
            ? options.ui 
            : (options.ui ? UIConfig.fromObject(options.ui) : new UIConfig());
    }

    /**
     * 生成唯一ID
     * @returns {string}
     */
    generateId() {
        return Math.random().toString(36).substring(2, 15) + 
               Math.random().toString(36).substring(2, 15);
    }

    /**
     * 转换为普通对象
     * @returns {Object}
     */
    toObject() {
        return {
            id: this.id,
            type: this.type,
            senderId: this.senderId,
            receiverId: this.receiverId,
            chatId: this.chatId,
            timestamp: this.timestamp,
            fileInfo: this.fileInfo ? this.fileInfo.toObject() : null,
            transferInfo: this.transferInfo ? this.transferInfo.toObject() : null,
            ui: this.ui ? this.ui.toObject() : null
        };
    }

    /**
     * 从普通对象创建实例
     * @param {Object} data
     * @returns {TransferMessage}
     */
    static fromObject(data) {
        return new TransferMessageData({
            id: data.id,
            type: data.type,
            senderId: data.senderId,
            receiverId: data.receiverId,
            chatId: data.chatId,
            timestamp: data.timestamp,
            fileInfo: data.fileInfo,
            transferInfo: data.transferInfo,
            ui: data.ui
        });
    }

    /**
     * 从数据库格式创建实例
     * @param {Object} dbData - 数据库行数据
     * @returns {TransferMessage}
     */
    static fromDbData(dbData) {
        // 重构文件信息
        const fileInfo = new FileInfo(
            dbData.file_name,
            dbData.file_size,
            dbData.file_type,
            dbData.file_hash
        );

        // 重构传输信息
        const transferInfo = new TransferInfo(dbData.transfer_id, {
            method: dbData.transfer_method,
            status: dbData.status,
            progress: dbData.progress,
            speed: dbData.speed,
            avgSpeed: dbData.avg_speed,
            estimatedTime: dbData.estimated_time,
            startTime: dbData.start_time,
            endTime: dbData.end_time,
            bytesTransferred: dbData.bytes_transferred,
            isValid: Boolean(dbData.is_valid),
            invalidReason: dbData.invalid_reason,
            invalidTime: dbData.invalid_time
        });

        return new TransferMessageData({
            id: dbData.id,
            type: dbData.type,
            senderId: dbData.sender_id,
            receiverId: dbData.receiver_id,
            chatId: dbData.chat_id,
            timestamp: dbData.timestamp,
            fileInfo: fileInfo,
            transferInfo: transferInfo
        });
    }
}

/**
 * 辅助函数：创建传输消息
 * @param {string} senderId - 发送者ID
 * @param {string} receiverId - 接收者ID
 * @param {string} chatId - 聊天ID
 * @param {string} fileName - 文件名
 * @param {number} fileSize - 文件大小
 * @param {string} [fileType] - 文件类型
 * @param {string} [fileHash] - 文件哈希
 * @returns {TransferMessage}
 */
function createTransferMessage(senderId, receiverId, chatId, fileName, fileSize, fileType = null, fileHash = null) {
    // 生成传输ID
    const transferId = `transfer-${Math.random().toString(36).substring(2, 15)}`;
    
    // 创建文件信息
    const fileInfo = new FileInfo(fileName, fileSize, fileType, fileHash);
    
    // 创建传输信息
    const transferInfo = new TransferInfo(transferId, {
        method: 'p2p',
        status: TransferStatus.PENDING
    });
    
    // 创建消息
    return new TransferMessageData({
        senderId: senderId,
        receiverId: receiverId,
        chatId: chatId,
        fileInfo: fileInfo,
        transferInfo: transferInfo
    });
}

/**
 * 辅助函数：检查是否为大文件
 * @param {number} fileSize - 文件大小（字节）
 * @param {number} [threshold=524288000] - 阈值（默认500MB）
 * @returns {boolean}
 */
function isLargeFile(fileSize, threshold = 500 * 1024 * 1024) {
    return fileSize > threshold;
}

/**
 * 辅助函数：格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string}
 */
function formatFileSize(bytes) {
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
 * 辅助函数：格式化传输速度
 * @param {number} bytesPerSecond - 每秒字节数
 * @returns {string}
 */
function formatSpeed(bytesPerSecond) {
    if (bytesPerSecond < 1024) {
        return `${bytesPerSecond.toFixed(0)} B/s`;
    } else if (bytesPerSecond < 1024 * 1024) {
        return `${(bytesPerSecond / 1024).toFixed(2)} KB/s`;
    } else {
        return `${(bytesPerSecond / (1024 * 1024)).toFixed(2)} MB/s`;
    }
}

/**
 * 辅助函数：格式化时间
 * @param {number} seconds - 秒数
 * @returns {string}
 */
function formatTime(seconds) {
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

// 导出（如果使用模块系统）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        TransferStatus,
        FileInfo,
        TransferInfo,
        UIConfig,
        TransferMessage,
        createTransferMessage,
        isLargeFile,
        formatFileSize,
        formatSpeed,
        formatTime
    };
}
