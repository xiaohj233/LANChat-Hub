/**
 * TransferInterruptionHandler - 处理P2P传输中断和断点续传
 * 
 * 功能:
 * - 处理传输中断
 * - 保存和加载断点信息
 * - 提供恢复和重新开始选项
 * - 支持断点续传
 * 
 */

class TransferInterruptionHandler {
    constructor() {
        this.resumeSupported = true;
        this.checkpoints = new Map(); // 存储断点信息
        this.interruptedTransfers = new Set(); // 跟踪中断的传输
    }

    /**
     * 处理传输中断
     * @param {string} transferId - 传输ID
     * @param {Object} lastCheckpoint - 最后的断点信息
     * @returns {Promise<void>}
     */
    async handleInterruption(transferId, lastCheckpoint) {
        console.log(`[TransferInterruptionHandler] 处理传输中断: transferId=${transferId}`, lastCheckpoint);

        // 保存断点信息
        await this.saveCheckpoint(transferId, lastCheckpoint);

        // 标记为中断状态
        this.interruptedTransfers.add(transferId);

        // 更新UI显示中断信息
        this.updateInterruptionStatus(transferId, lastCheckpoint);

        // 显示恢复选项
        this.showResumeOptions(transferId, lastCheckpoint);
    }

    /**
     * 保存断点信息
     * @param {string} transferId - 传输ID
     * @param {Object} checkpoint - 断点信息
     * @returns {Promise<void>}
     */
    async saveCheckpoint(transferId, checkpoint) {
        const checkpointData = {
            transferId,
            progress: checkpoint.progress || 0,
            bytesTransferred: checkpoint.bytesTransferred || 0,
            totalBytes: checkpoint.totalBytes || 0,
            timestamp: Date.now(),
            chunkIndex: checkpoint.chunkIndex || 0,
            metadata: checkpoint.metadata || {}
        };

        // 保存到内存
        this.checkpoints.set(transferId, checkpointData);

        // 保存到localStorage（持久化）
        try {
            const key = `p2p_checkpoint_${transferId}`;
            localStorage.setItem(key, JSON.stringify(checkpointData));
            console.log(`[TransferInterruptionHandler] 断点已保存: ${transferId}`);
        } catch (error) {
            console.error(`[TransferInterruptionHandler] 保存断点失败:`, error);
        }

        // 可选：保存到服务器
        try {
            await this.saveCheckpointToServer(transferId, checkpointData);
        } catch (error) {
            console.warn(`[TransferInterruptionHandler] 保存断点到服务器失败:`, error);
        }
    }

    /**
     * 加载断点信息
     * @param {string} transferId - 传输ID
     * @returns {Promise<Object|null>} - 断点信息
     */
    async loadCheckpoint(transferId) {
        // 先从内存加载
        if (this.checkpoints.has(transferId)) {
            console.log(`[TransferInterruptionHandler] 从内存加载断点: ${transferId}`);
            return this.checkpoints.get(transferId);
        }

        // 从localStorage加载
        try {
            const key = `p2p_checkpoint_${transferId}`;
            const data = localStorage.getItem(key);
            if (data) {
                const checkpoint = JSON.parse(data);
                this.checkpoints.set(transferId, checkpoint);
                console.log(`[TransferInterruptionHandler] 从localStorage加载断点: ${transferId}`);
                return checkpoint;
            }
        } catch (error) {
            console.error(`[TransferInterruptionHandler] 从localStorage加载断点失败:`, error);
        }

        // 从服务器加载
        try {
            const checkpoint = await this.loadCheckpointFromServer(transferId);
            if (checkpoint) {
                this.checkpoints.set(transferId, checkpoint);
                console.log(`[TransferInterruptionHandler] 从服务器加载断点: ${transferId}`);
                return checkpoint;
            }
        } catch (error) {
            console.warn(`[TransferInterruptionHandler] 从服务器加载断点失败:`, error);
        }

        return null;
    }

    /**
     * 保存断点到服务器
     * @param {string} transferId - 传输ID
     * @param {Object} checkpoint - 断点信息
     * @returns {Promise<void>}
     */
    async saveCheckpointToServer(transferId, checkpoint) {
        const response = await fetch('/api/p2p/checkpoint', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                transferId,
                checkpoint
            })
        });

        if (!response.ok) {
            throw new Error(`保存断点失败: ${response.status}`);
        }
    }

    /**
     * 从服务器加载断点
     * @param {string} transferId - 传输ID
     * @returns {Promise<Object|null>} - 断点信息
     */
    async loadCheckpointFromServer(transferId) {
        const response = await fetch(`/api/p2p/checkpoint/${transferId}`);
        
        if (!response.ok) {
            if (response.status === 404) {
                return null;
            }
            throw new Error(`加载断点失败: ${response.status}`);
        }

        const data = await response.json();
        return data.checkpoint;
    }

    /**
     * 更新中断状态显示
     * @param {string} transferId - 传输ID
     * @param {Object} checkpoint - 断点信息
     */
    updateInterruptionStatus(transferId, checkpoint) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) {
            console.warn(`[TransferInterruptionHandler] 找不到传输消息元素: ${transferId}`);
            return;
        }

        // 查找或创建状态显示区域
        let statusArea = messageElement.querySelector('.interruption-status');
        if (!statusArea) {
            statusArea = document.createElement('div');
            statusArea.className = 'interruption-status';
            messageElement.appendChild(statusArea);
        }

        const progress = checkpoint.progress || 0;
        const bytesTransferred = checkpoint.bytesTransferred || 0;
        const totalBytes = checkpoint.totalBytes || 0;

        statusArea.innerHTML = `
            <div class="interruption-info">
                <div class="interruption-icon">⏸️</div>
                <div class="interruption-text">
                    传输已中断，支持断点续传
                </div>
                <div class="interruption-progress">
                    <div class="progress-text">已传输: ${this.formatBytes(bytesTransferred)} / ${this.formatBytes(totalBytes)} (${progress.toFixed(1)}%)</div>
                </div>
            </div>
        `;

        // 添加样式
        if (!document.getElementById('interruption-status-styles')) {
            const style = document.createElement('style');
            style.id = 'interruption-status-styles';
            style.textContent = `
                .interruption-status {
                    margin-top: 12px;
                    padding: 12px;
                    background-color: #fff3cd;
                    border-radius: 8px;
                    border: 1px solid #ffc107;
                }
                .interruption-info {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }
                .interruption-icon {
                    font-size: 24px;
                }
                .interruption-text {
                    font-size: 14px;
                    color: #856404;
                    font-weight: 500;
                }
                .interruption-progress {
                    font-size: 13px;
                    color: #856404;
                }
                .progress-text {
                    margin-top: 4px;
                }
            `;
            document.head.appendChild(style);
        }
    }

    /**
     * 显示恢复选项
     * @param {string} transferId - 传输ID
     * @param {Object} checkpoint - 断点信息
     */
    showResumeOptions(transferId, checkpoint) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        // 创建恢复选项UI
        let resumeUI = messageElement.querySelector('.resume-options');
        if (!resumeUI) {
            resumeUI = document.createElement('div');
            resumeUI.className = 'resume-options';
            messageElement.appendChild(resumeUI);
        }

        resumeUI.innerHTML = `
            <div class="resume-actions">
                <button class="resume-btn" data-transfer-id="${transferId}">
                    继续传输
                </button>
                <button class="restart-btn" data-transfer-id="${transferId}">
                    重新开始
                </button>
            </div>
        `;

        // 添加样式
        if (!document.getElementById('resume-options-styles')) {
            const style = document.createElement('style');
            style.id = 'resume-options-styles';
            style.textContent = `
                .resume-options {
                    margin-top: 12px;
                }
                .resume-actions {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                }
                .resume-btn, .restart-btn {
                    padding: 8px 16px;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }
                .resume-btn {
                    background-color: #28a745;
                    color: white;
                }
                .resume-btn:hover {
                    background-color: #218838;
                }
                .restart-btn {
                    background-color: #007bff;
                    color: white;
                }
                .restart-btn:hover {
                    background-color: #0056b3;
                }
            `;
            document.head.appendChild(style);
        }

        // 绑定事件监听器
        this.bindResumeEvents(transferId);
    }

    /**
     * 绑定恢复选项事件
     * @param {string} transferId - 传输ID
     */
    bindResumeEvents(transferId) {
        // 继续传输按钮
        const resumeBtn = document.querySelector(`.resume-btn[data-transfer-id="${transferId}"]`);
        if (resumeBtn) {
            resumeBtn.addEventListener('click', async () => {
                console.log(`[TransferInterruptionHandler] 用户选择继续传输: ${transferId}`);
                await this.resumeTransfer(transferId);
            });
        }

        // 重新开始按钮
        const restartBtn = document.querySelector(`.restart-btn[data-transfer-id="${transferId}"]`);
        if (restartBtn) {
            restartBtn.addEventListener('click', () => {
                console.log(`[TransferInterruptionHandler] 用户选择重新开始: ${transferId}`);
                this.restartTransfer(transferId);
            });
        }
    }

    /**
     * 恢复传输
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async resumeTransfer(transferId) {
        // 加载断点信息
        const checkpoint = await this.loadCheckpoint(transferId);
        if (!checkpoint) {
            console.error(`[TransferInterruptionHandler] 找不到断点信息: ${transferId}`);
            alert('无法恢复传输：找不到断点信息');
            return;
        }

        // 移除中断状态UI
        this.clearInterruptionUI(transferId);

        // 更新状态为传输中
        this.updateResumingStatus(transferId, checkpoint);

        // 触发恢复事件
        const event = new CustomEvent('p2p-transfer-resume', {
            detail: {
                transferId,
                checkpoint
            }
        });
        document.dispatchEvent(event);

        // 从中断列表移除
        this.interruptedTransfers.delete(transferId);
    }

    /**
     * 重新开始传输
     * @param {string} transferId - 传输ID
     */
    restartTransfer(transferId) {
        // 清除断点信息
        this.clearCheckpoint(transferId);

        // 移除中断状态UI
        this.clearInterruptionUI(transferId);

        // 触发重新开始事件
        const event = new CustomEvent('p2p-transfer-restart', {
            detail: { transferId }
        });
        document.dispatchEvent(event);

        // 从中断列表移除
        this.interruptedTransfers.delete(transferId);
    }

    /**
     * 更新恢复中状态
     * @param {string} transferId - 传输ID
     * @param {Object} checkpoint - 断点信息
     */
    updateResumingStatus(transferId, checkpoint) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const statusArea = messageElement.querySelector('.interruption-status');
        if (statusArea) {
            statusArea.innerHTML = `
                <div class="resuming-info">
                    <div class="resuming-icon">▶️</div>
                    <div class="resuming-text">
                        正在从 ${checkpoint.progress.toFixed(1)}% 继续传输...
                    </div>
                </div>
            `;
        }
    }

    /**
     * 清除中断UI
     * @param {string} transferId - 传输ID
     */
    clearInterruptionUI(transferId) {
        const messageElement = document.querySelector(`[data-transfer-id="${transferId}"]`);
        if (!messageElement) return;

        const interruptionStatus = messageElement.querySelector('.interruption-status');
        if (interruptionStatus) {
            interruptionStatus.remove();
        }

        const resumeOptions = messageElement.querySelector('.resume-options');
        if (resumeOptions) {
            resumeOptions.remove();
        }
    }

    /**
     * 清除断点信息
     * @param {string} transferId - 传输ID
     */
    clearCheckpoint(transferId) {
        // 从内存清除
        this.checkpoints.delete(transferId);

        // 从localStorage清除
        try {
            const key = `p2p_checkpoint_${transferId}`;
            localStorage.removeItem(key);
        } catch (error) {
            console.error(`[TransferInterruptionHandler] 清除localStorage断点失败:`, error);
        }

        // 从服务器清除
        this.deleteCheckpointFromServer(transferId).catch(error => {
            console.warn(`[TransferInterruptionHandler] 清除服务器断点失败:`, error);
        });
    }

    /**
     * 从服务器删除断点
     * @param {string} transferId - 传输ID
     * @returns {Promise<void>}
     */
    async deleteCheckpointFromServer(transferId) {
        const response = await fetch(`/api/p2p/checkpoint/${transferId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error(`删除断点失败: ${response.status}`);
        }
    }

    /**
     * 检查传输是否中断
     * @param {string} transferId - 传输ID
     * @returns {boolean}
     */
    isInterrupted(transferId) {
        return this.interruptedTransfers.has(transferId);
    }

    /**
     * 格式化字节数
     * @param {number} bytes - 字节数
     * @returns {string} - 格式化后的字符串
     */
    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * 清理资源
     */
    cleanup() {
        this.checkpoints.clear();
        this.interruptedTransfers.clear();
    }
}

// 导出为全局变量（用于浏览器环境）
if (typeof window !== 'undefined') {
    window.TransferInterruptionHandler = TransferInterruptionHandler;
}

// 导出为模块（用于Node.js环境）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TransferInterruptionHandler;
}
