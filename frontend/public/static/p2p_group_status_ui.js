/**
 * P2P Group Transfer Status UI Component
 * 
 * 显示群聊P2P传输的状态：
 * - 每个成员的接收状态
 * - 整体完成状态
 * 
 */

class P2PGroupStatusUI {
    /**
     * 构造函数
     * @param {string} containerId - 容器元素ID
     */
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`Container ${containerId} not found`);
        }
    }

    /**
     * 显示群聊传输状态
     * @param {string} sessionId - 会话ID
     * @param {Array} receiverStatuses - 接收方状态列表
     * @param {Object} transferInfo - 传输信息
     */
    displayGroupTransferStatus(sessionId, receiverStatuses, transferInfo) {
        if (!this.container) return;

        // 创建状态容器
        const statusDiv = document.createElement('div');
        statusDiv.className = 'p2p-group-status';
        statusDiv.id = `group-status-${sessionId}`;

        // 标题
        const title = document.createElement('h4');
        title.textContent = '群聊文件传输状态';
        statusDiv.appendChild(title);

        // 文件信息
        const fileInfo = document.createElement('div');
        fileInfo.className = 'file-info';
        fileInfo.innerHTML = `
            <p><strong>文件:</strong> ${transferInfo.filename || '多个文件'}</p>
            <p><strong>大小:</strong> ${this.formatFileSize(transferInfo.totalSize)}</p>
            <p><strong>文件数:</strong> ${transferInfo.fileCount}</p>
        `;
        statusDiv.appendChild(fileInfo);

        // 整体进度
        const overallProgress = this.calculateOverallProgress(receiverStatuses);
        const progressDiv = document.createElement('div');
        progressDiv.className = 'overall-progress';
        progressDiv.innerHTML = `
            <p><strong>整体进度:</strong> ${overallProgress.completed}/${overallProgress.total} 接收方完成</p>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${overallProgress.percentage}%"></div>
            </div>
            <p class="progress-text">${overallProgress.percentage.toFixed(1)}%</p>
        `;
        statusDiv.appendChild(progressDiv);

        // 接收方状态列表
        const receiversDiv = document.createElement('div');
        receiversDiv.className = 'receivers-status';
        receiversDiv.innerHTML = '<h5>接收方状态:</h5>';

        const receiversList = document.createElement('ul');
        receiversList.className = 'receivers-list';

        for (const receiver of receiverStatuses) {
            const li = document.createElement('li');
            li.className = `receiver-item status-${receiver.status}`;
            
            const statusIcon = this.getStatusIcon(receiver.status);
            const statusText = this.getStatusText(receiver.status);
            
            li.innerHTML = `
                <span class="receiver-uid">${receiver.uid}</span>
                <span class="receiver-status">
                    ${statusIcon} ${statusText}
                </span>
                <span class="receiver-progress">${receiver.progress.toFixed(1)}%</span>
            `;
            
            receiversList.appendChild(li);
        }

        receiversDiv.appendChild(receiversList);
        statusDiv.appendChild(receiversDiv);

        // 添加到容器
        this.container.appendChild(statusDiv);

        // 添加样式
        this.injectStyles();
    }

    /**
     * 更新接收方状态
     * @param {string} sessionId - 会话ID
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} status - 状态
     * @param {number} progress - 进度
     */
    updateReceiverStatus(sessionId, receiverUid, status, progress) {
        const statusDiv = document.getElementById(`group-status-${sessionId}`);
        if (!statusDiv) return;

        // 查找接收方项
        const receiverItems = statusDiv.querySelectorAll('.receiver-item');
        for (const item of receiverItems) {
            const uidSpan = item.querySelector('.receiver-uid');
            if (uidSpan && uidSpan.textContent === receiverUid) {
                // 更新状态类
                item.className = `receiver-item status-${status}`;
                
                // 更新状态文本
                const statusSpan = item.querySelector('.receiver-status');
                if (statusSpan) {
                    const statusIcon = this.getStatusIcon(status);
                    const statusText = this.getStatusText(status);
                    statusSpan.innerHTML = `${statusIcon} ${statusText}`;
                }
                
                // 更新进度
                const progressSpan = item.querySelector('.receiver-progress');
                if (progressSpan) {
                    progressSpan.textContent = `${progress.toFixed(1)}%`;
                }
                
                break;
            }
        }

        // 更新整体进度
        this.updateOverallProgress(sessionId);
    }

    /**
     * 更新整体进度
     * @param {string} sessionId - 会话ID
     */
    updateOverallProgress(sessionId) {
        const statusDiv = document.getElementById(`group-status-${sessionId}`);
        if (!statusDiv) return;

        // 收集所有接收方状态
        const receiverStatuses = [];
        const receiverItems = statusDiv.querySelectorAll('.receiver-item');
        
        for (const item of receiverItems) {
            const uidSpan = item.querySelector('.receiver-uid');
            const progressSpan = item.querySelector('.receiver-progress');
            const statusClass = item.className.match(/status-(\w+)/);
            
            if (uidSpan && progressSpan && statusClass) {
                receiverStatuses.push({
                    uid: uidSpan.textContent,
                    status: statusClass[1],
                    progress: parseFloat(progressSpan.textContent)
                });
            }
        }

        // 计算整体进度
        const overallProgress = this.calculateOverallProgress(receiverStatuses);

        // 更新显示
        const progressDiv = statusDiv.querySelector('.overall-progress');
        if (progressDiv) {
            progressDiv.innerHTML = `
                <p><strong>整体进度:</strong> ${overallProgress.completed}/${overallProgress.total} 接收方完成</p>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${overallProgress.percentage}%"></div>
                </div>
                <p class="progress-text">${overallProgress.percentage.toFixed(1)}%</p>
            `;
        }
    }

    /**
     * 计算整体进度
     * @param {Array} receiverStatuses - 接收方状态列表
     * @returns {Object} - 整体进度信息
     */
    calculateOverallProgress(receiverStatuses) {
        const total = receiverStatuses.length;
        const completed = receiverStatuses.filter(r => r.status === 'completed').length;
        const percentage = total > 0 ? (completed / total) * 100 : 0;

        return {
            total: total,
            completed: completed,
            percentage: percentage
        };
    }

    /**
     * 获取状态图标
     * @param {string} status - 状态
     * @returns {string} - 图标HTML
     */
    getStatusIcon(status) {
        const icons = {
            'pending': '⏳',
            'accepted': '✅',
            'rejected': '❌',
            'connecting': '🔄',
            'transferring': '📤',
            'completed': '✔️',
            'failed': '⚠️'
        };
        return icons[status] || '❓';
    }

    /**
     * 获取状态文本
     * @param {string} status - 状态
     * @returns {string} - 状态文本
     */
    getStatusText(status) {
        const texts = {
            'pending': '等待响应',
            'accepted': '已接受',
            'rejected': '已拒绝',
            'connecting': '连接中',
            'transferring': '传输中',
            'completed': '已完成',
            'failed': '失败'
        };
        return texts[status] || '未知';
    }

    /**
     * 格式化文件大小
     * @param {number} bytes - 字节数
     * @returns {string} - 格式化后的大小
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * 移除群聊传输状态显示
     * @param {string} sessionId - 会话ID
     */
    removeGroupTransferStatus(sessionId) {
        const statusDiv = document.getElementById(`group-status-${sessionId}`);
        if (statusDiv) {
            statusDiv.remove();
        }
    }

    /**
     * 注入样式
     */
    injectStyles() {
        // 检查是否已经注入
        if (document.getElementById('p2p-group-status-styles')) {
            return;
        }

        const style = document.createElement('style');
        style.id = 'p2p-group-status-styles';
        style.textContent = `
            .p2p-group-status {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                margin: 10px 0;
                background-color: #f9f9f9;
            }

            .p2p-group-status h4 {
                margin-top: 0;
                color: #333;
            }

            .p2p-group-status h5 {
                margin-top: 15px;
                margin-bottom: 10px;
                color: #555;
            }

            .file-info {
                margin-bottom: 15px;
                padding: 10px;
                background-color: #fff;
                border-radius: 4px;
            }

            .file-info p {
                margin: 5px 0;
            }

            .overall-progress {
                margin-bottom: 15px;
                padding: 10px;
                background-color: #fff;
                border-radius: 4px;
            }

            .progress-bar {
                width: 100%;
                height: 20px;
                background-color: #e0e0e0;
                border-radius: 10px;
                overflow: hidden;
                margin: 10px 0;
            }

            .progress-fill {
                height: 100%;
                background-color: #4CAF50;
                transition: width 0.3s ease;
            }

            .progress-text {
                text-align: center;
                font-weight: bold;
                color: #333;
            }

            .receivers-status {
                background-color: #fff;
                border-radius: 4px;
                padding: 10px;
            }

            .receivers-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }

            .receiver-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px;
                margin: 5px 0;
                border-radius: 4px;
                border: 1px solid #ddd;
            }

            .receiver-item.status-pending {
                background-color: #fff3cd;
                border-color: #ffc107;
            }

            .receiver-item.status-accepted {
                background-color: #d4edda;
                border-color: #28a745;
            }

            .receiver-item.status-rejected {
                background-color: #f8d7da;
                border-color: #dc3545;
            }

            .receiver-item.status-connecting {
                background-color: #d1ecf1;
                border-color: #17a2b8;
            }

            .receiver-item.status-transferring {
                background-color: #cfe2ff;
                border-color: #0d6efd;
            }

            .receiver-item.status-completed {
                background-color: #d1e7dd;
                border-color: #198754;
            }

            .receiver-item.status-failed {
                background-color: #f8d7da;
                border-color: #dc3545;
            }

            .receiver-uid {
                font-weight: bold;
                flex: 1;
            }

            .receiver-status {
                flex: 1;
                text-align: center;
            }

            .receiver-progress {
                flex: 0 0 60px;
                text-align: right;
                font-weight: bold;
            }
        `;
        document.head.appendChild(style);
    }
}

// 导出类（如果使用模块系统）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = P2PGroupStatusUI;
}
