/**
 * FileSizeDetector - 负责检测文件大小并自动选择传输模式
 * 
 * 该类实现文件大小阈值检测（500MB），自动选择P2P或常规传输模式，
 * 并集成到现有的文件选择流程中。
 */
class FileSizeDetector {
    constructor() {
        // 500MB阈值
        this.P2P_THRESHOLD = 500 * 1024 * 1024; // 500MB in bytes
    }
    
    /**
     * 检测文件大小并确定传输模式
     * @param {number} fileSize - 文件大小（字节）
     * @returns {string} 传输模式 ('p2p' 或 'regular')
     */
    detectTransferMode(fileSize) {
        if (fileSize > this.P2P_THRESHOLD) {
            return 'p2p';
        }
        return 'regular';
    }
    
    /**
     * 检查文件是否应该使用P2P传输
     * @param {File} file - 文件对象
     * @returns {boolean} 是否应该使用P2P传输
     */
    shouldUseP2P(file) {
        return file.size > this.P2P_THRESHOLD;
    }
    
    /**
     * 批量检测多个文件
     * @param {FileList|Array} files - 文件列表
     * @returns {Object} 分类结果 { p2pFiles: [], regularFiles: [] }
     */
    categorizeFiles(files) {
        const result = {
            p2pFiles: [],
            regularFiles: []
        };
        
        for (const file of files) {
            if (this.shouldUseP2P(file)) {
                result.p2pFiles.push(file);
            } else {
                result.regularFiles.push(file);
            }
        }
        
        return result;
    }
    
    /**
     * 格式化文件大小显示
     * @param {number} bytes - 字节数
     * @returns {string} 格式化的大小字符串
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
     * 获取传输模式的显示文本
     * @param {string} mode - 传输模式
     * @returns {string} 显示文本
     */
    getTransferModeLabel(mode) {
        return mode === 'p2p' ? 'P2P传输' : '常规传输';
    }
    
    /**
     * 创建传输模式标识元素
     * @param {string} mode - 传输模式
     * @returns {HTMLElement} 标识元素
     */
    createTransferModeLabel(mode) {
        const label = document.createElement('span');
        label.className = `transfer-mode-label ${mode}`;
        label.textContent = this.getTransferModeLabel(mode);
        
        if (mode === 'p2p') {
            label.style.backgroundColor = '#007bff';
            label.style.color = 'white';
            label.style.padding = '2px 8px';
            label.style.borderRadius = '4px';
            label.style.fontSize = '12px';
            label.style.fontWeight = '500';
        }
        
        return label;
    }
    
    /**
     * 处理文件选择事件
     * @param {Event} event - 文件选择事件
     * @param {Function} onP2PFile - P2P文件处理回调
     * @param {Function} onRegularFile - 常规文件处理回调
     */
    handleFileSelection(event, onP2PFile, onRegularFile) {
        const files = event.target.files;
        if (!files || files.length === 0) {
            return;
        }
        
        const categorized = this.categorizeFiles(files);
        
        // 处理P2P文件
        categorized.p2pFiles.forEach(file => {
            console.log(`File ${file.name} (${this.formatFileSize(file.size)}) will use P2P transfer`);
            if (onP2PFile) {
                onP2PFile(file);
            }
        });
        
        // 处理常规文件
        categorized.regularFiles.forEach(file => {
            console.log(`File ${file.name} (${this.formatFileSize(file.size)}) will use regular transfer`);
            if (onRegularFile) {
                onRegularFile(file);
            }
        });
    }
    
    /**
     * 显示文件传输模式提示
     * @param {File} file - 文件对象
     * @returns {string} 提示信息
     */
    getTransferModeNotification(file) {
        const mode = this.detectTransferMode(file.size);
        const size = this.formatFileSize(file.size);
        
        if (mode === 'p2p') {
            return `文件 "${file.name}" (${size}) 将使用P2P传输模式`;
        } else {
            return `文件 "${file.name}" (${size}) 将使用常规传输模式`;
        }
    }
    
    /**
     * 获取阈值信息
     * @returns {Object} 阈值信息
     */
    getThresholdInfo() {
        return {
            bytes: this.P2P_THRESHOLD,
            formatted: this.formatFileSize(this.P2P_THRESHOLD),
            description: `文件大小超过 ${this.formatFileSize(this.P2P_THRESHOLD)} 时自动使用P2P传输`
        };
    }
    
    /**
     * 设置自定义阈值
     * @param {number} thresholdMB - 阈值（MB）
     */
    setThreshold(thresholdMB) {
        this.P2P_THRESHOLD = thresholdMB * 1024 * 1024;
        console.log(`P2P threshold set to ${thresholdMB} MB`);
    }
    
    /**
     * 验证文件对象
     * @param {File} file - 文件对象
     * @returns {boolean} 是否有效
     */
    isValidFile(file) {
        return file instanceof File && file.size > 0;
    }
    
    /**
     * 获取文件信息
     * @param {File} file - 文件对象
     * @returns {Object} 文件信息
     */
    getFileInfo(file) {
        const mode = this.detectTransferMode(file.size);
        
        return {
            name: file.name,
            size: file.size,
            type: file.type,
            formattedSize: this.formatFileSize(file.size),
            transferMode: mode,
            transferModeLabel: this.getTransferModeLabel(mode),
            shouldUseP2P: mode === 'p2p',
            lastModified: file.lastModified,
            lastModifiedDate: new Date(file.lastModified)
        };
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FileSizeDetector;
}

// 全局实例（可选）
if (typeof window !== 'undefined') {
    window.fileSizeDetector = new FileSizeDetector();
}
