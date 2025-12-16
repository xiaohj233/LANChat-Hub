/**
 * SpeedCalculator - 计算传输速度、平均速度和预计剩余时间
 * 
 * 该类负责跟踪传输速度并提供格式化的速度和时间显示。
 * 使用最近10个样本计算平均速度，以提供更稳定的速度估算。
 */
class SpeedCalculator {
    constructor() {
        this.samples = [];
        this.maxSamples = 10; // 保留最近10个样本
        this.lastBytes = 0;
        this.lastTime = Date.now();
    }
    
    /**
     * 计算当前速度（bytes/s）
     * @param {number} currentBytes - 当前已传输的字节数
     * @returns {number} 当前速度（bytes/s）
     */
    calculateSpeed(currentBytes) {
        const now = Date.now();
        const timeDiff = (now - this.lastTime) / 1000; // 转换为秒
        const bytesDiff = currentBytes - this.lastBytes;
        
        if (timeDiff > 0) {
            const speed = bytesDiff / timeDiff;
            this.samples.push(speed);
            
            // 保持样本数量在限制内
            if (this.samples.length > this.maxSamples) {
                this.samples.shift();
            }
            
            this.lastBytes = currentBytes;
            this.lastTime = now;
            
            return speed;
        }
        
        return 0;
    }
    
    /**
     * 计算平均速度
     * @returns {number} 平均速度（bytes/s）
     */
    getAverageSpeed() {
        if (this.samples.length === 0) return 0;
        const sum = this.samples.reduce((a, b) => a + b, 0);
        return sum / this.samples.length;
    }
    
    /**
     * 估算剩余时间（秒）
     * @param {number} currentBytes - 当前已传输的字节数
     * @param {number} totalBytes - 总字节数
     * @returns {number|null} 预计剩余时间（秒），如果无法估算则返回null
     */
    estimateRemainingTime(currentBytes, totalBytes) {
        const avgSpeed = this.getAverageSpeed();
        if (avgSpeed === 0) return null;
        
        const remainingBytes = totalBytes - currentBytes;
        return Math.ceil(remainingBytes / avgSpeed);
    }
    
    /**
     * 格式化速度显示
     * @param {number} bytesPerSecond - 速度（bytes/s）
     * @returns {string} 格式化的速度字符串
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
     * 格式化时间显示
     * @param {number} seconds - 时间（秒）
     * @returns {string} 格式化的时间字符串
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
     * 重置计算器状态
     */
    reset() {
        this.samples = [];
        this.lastBytes = 0;
        this.lastTime = Date.now();
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SpeedCalculator;
}
