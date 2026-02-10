/**
 * MessageIntegration - P2P传输消息集成类
 * 
 * 该类负责将P2P传输功能集成到聊天消息系统中，管理传输消息的创建、更新和用户交互。
 * 处理接收、拒绝、取消等用户操作，并通过DatabaseSync和RealtimeSync进行状态同步。
 */
class MessageIntegration {
    constructor() {
        this.dbSync = new DatabaseSync();
        this.realtimeSync = new RealtimeSync();
        this.transferMessages = new Map(); // 存储TransferMessage实例
        this.currentUserId = null;
        this.currentChatId = null;
        
        // 注册系统消息回调
        this.realtimeSync.onSystemMessage = (payload) => {
            this.handleSystemMessage(payload);
        };
    }
    
    /**
     * 初始化
     * @param {string} userId - 当前用户ID
     * @param {string} chatId - 当前聊天ID
     */
    initialize(userId, chatId) {
        this.currentUserId = userId;
        this.currentChatId = chatId;
    }
    
    /**
     * 创建传输消息
     * @param {Object} fileInfo - 文件信息
     * @param {string} transferId - 传输ID
     * @param {string} targetUserId - 目标用户ID
     * @param {string} senderName - 发送方名称
     * @returns {Promise<Object>} 消息数据
     */
    async createTransferMessage(fileInfo, transferId, targetUserId, senderName = '', isSender = true) {
        // 检查消息是否已存在（避免重复创建）
        if (this.transferMessages.has(transferId)) {
            console.log('[MessageIntegration] Transfer message already exists:', transferId);
            return this.transferMessages.get(transferId);
        }
        
        const messageData = {
            id: transferId,
            type: 'p2p_transfer',
            senderId: isSender ? this.currentUserId : targetUserId,
            receiverId: isSender ? targetUserId : this.currentUserId,
            chatId: this.currentChatId,
            timestamp: Date.now() / 1000,  // 转换为秒级时间戳，与普通消息保持一致
            fileInfo: fileInfo,
            transferInfo: {
                id: transferId,
                method: 'p2p',
                status: 'pending',
                progress: 0,
                speed: 0,
                avgSpeed: 0,
                estimatedTime: null,
                isValid: true
            },
            isSender: isSender,
            senderName: senderName
        };
        
        try {
            // 保存到数据库
            await this.dbSync.saveTransferMessage(messageData);
            
            // 添加到聊天界面
            this.addMessageToChat(messageData);
            
            // 注册实时更新回调
            this.realtimeSync.registerCallbacks(transferId, {
                onStatusUpdate: (payload) => this.handleStatusUpdate(transferId, payload),
                onProgressUpdate: (payload) => this.handleProgressUpdate(transferId, payload),
                onValidityUpdate: (payload) => this.handleValidityUpdate(transferId, payload)
            });
            
            return messageData;
        } catch (error) {
            console.error('Failed to create transfer message:', error);
            throw error;
        }
    }
    
    /**
     * 更新消息状态
     * @param {string} messageId - 消息ID
     * @param {string} status - 新状态
     * @param {Object} data - 附加数据
     */
    async updateMessageStatus(messageId, status, data = {}) {
        try {
            // 更新数据库（异步，不阻塞UI）
            this.dbSync.updateTransferStatus(messageId, status, data).catch(err => {
                // 404错误是正常的（消息可能不存在），其他错误才记录
                if (!err.message.includes('404')) {
                    console.error('[MessageIntegration] Failed to update database:', err);
                }
            });
            
            // 更新UI（立即执行）
            const transferMessage = this.transferMessages.get(messageId);
            if (transferMessage) {
                transferMessage.updateStatus(status, data);
            }
        } catch (error) {
            console.error('[MessageIntegration] Failed to update message status:', error);
            // 不抛出错误，避免阻塞其他操作
        }
    }
    
    /**
     * 创建系统消息
     * @param {string} type - 消息类型
     * @param {Object} data - 消息数据
     */
    async createSystemMessage(type, data) {
        let systemMessage;
        
        switch (type) {
            case 'transfer_accepted':
                systemMessage = SystemMessage.createAcceptedMessage(
                    data.userName,
                    data.fileName,
                    data.transferId
                );
                break;
            case 'transfer_rejected':
                systemMessage = SystemMessage.createRejectedMessage(
                    data.userName,
                    data.fileName,
                    data.transferId
                );
                break;
            case 'transfer_cancelled':
                systemMessage = SystemMessage.createCancelledMessage(
                    data.userName,
                    data.fileName,
                    data.transferId
                );
                break;
            case 'transfer_completed':
                systemMessage = SystemMessage.createCompletedMessage(
                    data.fileName,
                    data.transferId
                );
                break;
            case 'transfer_failed':
                systemMessage = SystemMessage.createFailedMessage(
                    data.fileName,
                    data.transferId
                );
                break;
            default:
                systemMessage = SystemMessage.createInfoMessage(data.content || '');
        }
        
        // 添加到聊天界面
        this.addSystemMessageToChat(systemMessage);
        
        // 系统消息不保存到数据库（避免复杂性和错误）
        // 系统消息是临时的UI反馈，不需要持久化
    }
    
    /**
     * 接收传输
     * @param {string} messageId - 消息ID
     */
    async acceptTransfer(messageId) {
        try {
            const transferMessage = this.transferMessages.get(messageId);
            if (!transferMessage) {
                console.error('[MessageIntegration] Transfer message not found:', messageId);
                return;
            }
            
            // 等待P2P Manager初始化（最多等待5秒）
            if (!window.p2pManager) {
                console.log('[MessageIntegration] Waiting for p2pManager to initialize...');
                let attempts = 0;
                while (!window.p2pManager && attempts < 50) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                    attempts++;
                }
                
                if (!window.p2pManager) {
                    console.error('[MessageIntegration] p2pManager not available after waiting');
                    alert('P2P系统未就绪，请稍后再试');
                    return;
                }
            }
            
            // 先更新UI状态（立即反馈）
            transferMessage.updateStatus('accepted');
            
            // 开始建立P2P连接（调用P2P Manager的acceptTransfer方法）
            console.log('[MessageIntegration] Calling p2pManager.acceptTransfer:', messageId);
            await window.p2pManager.acceptTransfer(messageId);
            
            // 更新传输对象状态
            if (window.p2pTransfers && window.p2pTransfers.has(messageId)) {
                const transfer = window.p2pTransfers.get(messageId);
                transfer.status = 'connecting';
            }
            
            // 更新数据库状态（异步，不阻塞）
            this.updateMessageStatus(messageId, 'accepted').catch(err => {
                console.warn('[MessageIntegration] Failed to update database status:', err);
                // 数据库更新失败不影响P2P传输
            });
            
            console.log('[MessageIntegration] Transfer accepted successfully');
        } catch (error) {
            console.error('[MessageIntegration] Failed to accept transfer:', error);
            // 更新UI状态为错误
            if (transferMessage) {
                transferMessage.updateStatus('failed', { error: error.message });
            }
            alert('接收失败：' + error.message);
        }
    }
    
    /**
     * 拒绝传输
     * @param {string} messageId - 消息ID
     */
    async rejectTransfer(messageId) {
        try {
            const transferMessage = this.transferMessages.get(messageId);
            if (!transferMessage) {
                console.error('Transfer message not found:', messageId);
                return;
            }
            
            // 更新状态为已拒绝
            await this.updateMessageStatus(messageId, 'rejected');
            
            // 创建系统消息通知发送方
            await this.createSystemMessage('transfer_rejected', {
                userName: '你', // 应该从用户信息中获取
                fileName: transferMessage.fileInfo.name,
                transferId: messageId
            });
            
            // 通过RealtimeSync通知对方
            this.realtimeSync.send({
                type: 'transfer_response',
                transferId: messageId,
                response: 'rejected',
                userId: this.currentUserId
            });
        } catch (error) {
            console.error('Failed to reject transfer:', error);
        }
    }
    
    /**
     * 取消传输
     * @param {string} messageId - 消息ID
     */
    async cancelTransfer(messageId) {
        console.log('[MessageIntegration] cancelTransfer called with messageId:', messageId);
        
        try {
            const transferMessage = this.transferMessages.get(messageId);
            if (!transferMessage) {
                console.error('[MessageIntegration] Transfer message not found:', messageId);
                console.log('[MessageIntegration] Available transfer messages:', Array.from(this.transferMessages.keys()));
                return;
            }
            
            console.log('[MessageIntegration] Found transfer message:', transferMessage);
            
            // 停止传输（这部分由P2PTransferManager处理）
            // 注意：实际使用的是window.p2pManager，不是window.p2pTransferManager
            let cancelled = false;
            
            if (window.p2pManager) {
                try {
                    console.log('[MessageIntegration] Calling p2pManager.cancelTransfer...');
                    await window.p2pManager.cancelTransfer(messageId);
                    console.log('[MessageIntegration] Transfer cancelled via p2pManager:', messageId);
                    cancelled = true;
                } catch (error) {
                    console.error('[MessageIntegration] Failed to cancel via p2pManager:', error);
                }
            } else if (window.p2pTransferManager) {
                try {
                    console.log('[MessageIntegration] Calling p2pTransferManager.cancelTransfer...');
                    await window.p2pTransferManager.cancelTransfer(messageId);
                    console.log('[MessageIntegration] Transfer cancelled via p2pTransferManager:', messageId);
                    cancelled = true;
                } catch (error) {
                    console.error('[MessageIntegration] Failed to cancel via p2pTransferManager:', error);
                }
            } else {
                console.warn('[MessageIntegration] No P2P manager available to cancel transfer');
                console.log('[MessageIntegration] window.p2pManager:', window.p2pManager);
                console.log('[MessageIntegration] window.p2pTransferManager:', window.p2pTransferManager);
            }
            
            // 更新状态为已取消
            console.log('[MessageIntegration] Updating message status to cancelled...');
            await this.updateMessageStatus(messageId, 'cancelled');
            
            // 创建系统消息通知对方
            try {
                console.log('[MessageIntegration] Creating system message...');
                await this.createSystemMessage('transfer_cancelled', {
                    userName: '你', // 应该从用户信息中获取
                    fileName: transferMessage.fileInfo.name,
                    transferId: messageId
                });
            } catch (error) {
                console.error('[MessageIntegration] Failed to create system message:', error);
            }
            
            // 通过RealtimeSync通知对方
            try {
                console.log('[MessageIntegration] Sending realtime sync notification...');
                this.realtimeSync.send({
                    type: 'transfer_cancelled',
                    transferId: messageId,
                    userId: this.currentUserId
                });
            } catch (error) {
                console.error('[MessageIntegration] Failed to send realtime sync:', error);
            }
            
            // 注销回调
            try {
                console.log('[MessageIntegration] Unregistering callbacks...');
                this.realtimeSync.unregisterCallbacks(messageId);
            } catch (error) {
                console.error('[MessageIntegration] Failed to unregister callbacks:', error);
            }
            
            console.log('[MessageIntegration] cancelTransfer completed successfully');
            
        } catch (error) {
            console.error('[MessageIntegration] Failed to cancel transfer:', error);
            console.error('[MessageIntegration] Error stack:', error.stack);
        }
    }
    
    /**
     * 打开文件
     * @param {string} messageId - 消息ID
     */
    async openFile(messageId) {
        // 这部分需要与后端API交互
        console.log('Opening file for message:', messageId);
        // TODO: 实现打开文件功能
    }
    
    /**
     * 显示文件位置
     * @param {string} messageId - 消息ID
     */
    async showFileLocation(messageId) {
        // 这部分需要与后端API交互
        console.log('Showing file location for message:', messageId);
        // TODO: 实现显示文件位置功能
    }
    
    /**
     * 添加消息到聊天界面
     * @param {Object} messageData - 消息数据
     */
    addMessageToChat(messageData) {
        // 检查消息是否已经存在于DOM中
        const existingElement = document.getElementById('msg-' + messageData.id);
        if (existingElement) {
            console.log('[P2P] Message already exists in DOM:', messageData.id);
            return;
        }
        
        const transferMessage = new TransferMessage(messageData);
        const messageElement = transferMessage.render();
        
        // 存储实例
        this.transferMessages.set(messageData.id, transferMessage);
        
        // 添加到聊天容器
        const chatContainer = document.getElementById('msg-box');
        if (chatContainer) {
            // 移除"选择左侧会话开始聊天"的空状态提示
            const emptyDiv = chatContainer.querySelector('.empty');
            if (emptyDiv) {
                emptyDiv.remove();
            }
            
            // 按照时间戳找到正确的插入位置
            const messageTimestamp = messageData.timestamp;
            console.log('[P2P] ========== Adding P2P Message ==========');
            console.log('[P2P] Message ID:', messageData.id);
            console.log('[P2P] Message timestamp:', messageTimestamp, 'type:', typeof messageTimestamp);
            console.log('[P2P] Message time (formatted):', new Date(messageTimestamp * 1000).toLocaleString());
            console.log('[P2P] Current chat container children count:', chatContainer.children.length);
            
            const existingMessages = Array.from(chatContainer.children);
            let insertBeforeElement = null;
            let checkedCount = 0;
            let foundTimestamps = [];
            
            for (let i = 0; i < existingMessages.length; i++) {
                const existingMsg = existingMessages[i];
                
                // 跳过时间分隔符和空状态
                if (existingMsg.classList.contains('chat-time') || existingMsg.classList.contains('empty')) {
                    continue;
                }
                
                checkedCount++;
                
                // 获取现有消息的时间戳
                let existingTimestamp = null;
                
                // 尝试从data-timestamp属性获取
                if (existingMsg.dataset.timestamp) {
                    existingTimestamp = parseFloat(existingMsg.dataset.timestamp);
                    console.log('[P2P] Message', checkedCount, '- Found data-timestamp:', existingTimestamp, 'element:', existingMsg.id);
                }
                // 尝试从消息ID获取（普通消息的ID格式：msg-{id}）
                else if (existingMsg.id && existingMsg.id.startsWith('msg-')) {
                    const msgId = existingMsg.id.replace('msg-', '');
                    // 从currentChatMsgs中查找对应消息的时间戳
                    if (window.currentChatMsgs) {
                        const msg = window.currentChatMsgs.find(m => String(m.id) === msgId);
                        if (msg) {
                            existingTimestamp = msg.timestamp;
                            console.log('[P2P] Message', checkedCount, '- Found from currentChatMsgs:', existingTimestamp, 'msg:', msgId);
                        } else {
                            console.log('[P2P] Message', checkedCount, '- NOT found in currentChatMsgs, msg:', msgId);
                        }
                    }
                }
                
                if (existingTimestamp !== null) {
                    foundTimestamps.push({index: i, timestamp: existingTimestamp, id: existingMsg.id});
                }
                
                // 如果找到了时间戳且当前P2P消息应该插入在这条消息之前
                if (existingTimestamp !== null && messageTimestamp < existingTimestamp) {
                    insertBeforeElement = existingMsg;
                    console.log('[P2P] ✓ Found insert position! Before message with timestamp:', existingTimestamp, '(', new Date(existingTimestamp * 1000).toLocaleString(), ')');
                    break;
                }
            }
            
            console.log('[P2P] Checked', checkedCount, 'messages, found', foundTimestamps.length, 'timestamps');
            console.log('[P2P] All found timestamps:', foundTimestamps);
            console.log('[P2P] Insert before element:', insertBeforeElement ? insertBeforeElement.id : 'null (append to end)');
            
            // 插入到正确位置
            if (insertBeforeElement) {
                console.log('[P2P] ✓ Inserting P2P message BEFORE element:', insertBeforeElement.id);
                chatContainer.insertBefore(messageElement, insertBeforeElement);
            } else {
                // 如果没有找到插入位置，说明这是最新的消息，添加到末尾
                console.log('[P2P] ✓ Appending P2P message to END');
                chatContainer.appendChild(messageElement);
            }
            console.log('[P2P] ========== P2P Message Added ==========');
            
            // 滚动到底部（如果是新消息）
            if (!insertBeforeElement) {
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        } else {
            console.error('Chat container not found');
        }
    }
    
    /**
     * 添加系统消息到聊天界面
     * @param {SystemMessage} systemMessage - 系统消息实例
     */
    addSystemMessageToChat(systemMessage) {
        const messageElement = systemMessage.render();
        
        // 添加到聊天容器
        const chatContainer = document.getElementById('msg-box');
        if (chatContainer) {
            // 移除"选择左侧会话开始聊天"的空状态提示
            const emptyDiv = chatContainer.querySelector('.empty');
            if (emptyDiv) {
                emptyDiv.remove();
            }
            
            // 系统消息总是添加到末尾（因为它们是实时生成的）
            chatContainer.appendChild(messageElement);
            
            // 滚动到底部
            chatContainer.scrollTop = chatContainer.scrollHeight;
        } else {
            console.error('Chat container not found');
        }
    }
    
    /**
     * 处理状态更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    handleStatusUpdate(transferId, payload) {
        console.log('[MessageIntegration] Status update:', transferId, payload.status);
        const transferMessage = this.transferMessages.get(transferId);
        if (transferMessage) {
            transferMessage.updateStatus(payload.status, payload);
        } else {
            console.warn('[MessageIntegration] Transfer message not found for status update:', transferId);
        }
    }
    
    /**
     * 处理进度更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    handleProgressUpdate(transferId, payload) {
        const transferMessage = this.transferMessages.get(transferId);
        if (transferMessage) {
            if (payload.progress !== undefined) {
                transferMessage.updateProgress(payload.progress);
            }
            if (payload.speed !== undefined) {
                transferMessage.updateSpeed(
                    payload.speed,
                    payload.avgSpeed || 0,
                    payload.estimatedTime || null
                );
            }
        }
    }
    
    /**
     * 处理有效性更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    handleValidityUpdate(transferId, payload) {
        const transferMessage = this.transferMessages.get(transferId);
        if (transferMessage) {
            transferMessage.isValid = payload.isValid;
            transferMessage.updateStatus(payload.isValid ? transferMessage.status : 'expired', {
                isValid: payload.isValid,
                invalidReason: payload.reason
            });
        }
    }
    
    /**
     * 处理系统消息
     * @param {Object} payload - 消息数据
     */
    handleSystemMessage(payload) {
        this.createSystemMessage(payload.messageType, {
            userName: payload.userName,
            fileName: payload.fileName,
            transferId: payload.transferId,
            content: payload.content
        });
    }
    
    /**
     * 获取TransferMessage实例
     * @param {string} messageId - 消息ID
     * @returns {TransferMessage|null} TransferMessage实例
     */
    getTransferMessageInstance(messageId) {
        return this.transferMessages.get(messageId) || null;
    }
    
    /**
     * 清理资源
     */
    destroy() {
        // 注销所有回调
        this.transferMessages.forEach((_, transferId) => {
            this.realtimeSync.unregisterCallbacks(transferId);
        });
        
        // 清空实例
        this.transferMessages.clear();
        
        // 关闭连接
        this.realtimeSync.close();
        this.dbSync.destroy();
    }
}

// 创建全局实例
if (typeof window !== 'undefined') {
    window.p2pMessageIntegration = new MessageIntegration();
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = MessageIntegration;
}
