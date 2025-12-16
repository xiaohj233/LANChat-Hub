/**
 * P2PTransferManager - 管理P2P传输的整个生命周期
 * 
 * 该类负责：
 * - 发起传输（文件大小路由逻辑）
 * - 接受/拒绝传输请求
 * - 取消传输
 * - 并发控制和队列管理
 */
class P2PTransferManager {
    /**
     * 构造函数
     * @param {SignalingClient} signalingClient - 信令客户端实例
     * @param {Object} uiHandler - UI处理器（可选）
     */
    constructor(signalingClient, uiHandler = null) {
        this.signalingClient = signalingClient;
        this.uiHandler = uiHandler;
        
        // 会话管理
        this.activeSessions = new Map(); // session_id -> P2PSession
        this.maxConcurrent = 3; // 最大并发传输数
        this.queue = []; // 排队的传输请求
        
        // 文件大小阈值（500MB）
        this.p2pThreshold = 500 * 1024 * 1024;
    }

    /**
     * 发起传输
     * @param {File|File[]} files - 要传输的文件或文件数组
     * @param {string} toUid - 接收方用户ID或群组ID
     * @param {string} chatType - 聊天类型 ('private' 或 'group')
     * @returns {Promise<Object>} - 返回传输信息
     */
    async initiateTransfer(files, toUid, chatType) {
        // 确保files是数组
        const fileArray = Array.isArray(files) ? files : [files];
        
        // 计算总大小
        const totalSize = fileArray.reduce((sum, file) => sum + file.size, 0);
        
        // 文件大小路由逻辑
        if (totalSize <= this.p2pThreshold) {
            // 小文件使用传统上传
            return await this.fallbackToTraditionalUpload(fileArray, toUid, chatType);
        }
        
        // 大文件使用P2P传输
        return await this.initiateP2PTransfer(fileArray, toUid, chatType);
    }

    /**
     * 发起P2P传输
     * @param {File[]} files - 文件数组
     * @param {string} toUid - 接收方用户ID或群组ID
     * @param {string} chatType - 聊天类型
     * @returns {Promise<Object>} - 返回传输信息
     */
    async initiateP2PTransfer(files, toUid, chatType) {
        // 检查WebRTC支持
        if (!this.checkWebRTCSupport()) {
            throw new Error('浏览器不支持WebRTC，无法进行P2P传输');
        }
        
        // 检查并发限制
        if (this.activeSessions.size >= this.maxConcurrent) {
            // 加入队列
            return await this.addToQueue(files, toUid, chatType);
        }
        
        // 创建会话
        const sessionId = await this.signalingClient.createSession(files, toUid, chatType);
        
        // 根据聊天类型创建不同的会话对象
        let session;
        if (chatType === 'group') {
            // 群聊使用P2PGroupSession
            session = new P2PGroupSession(
                sessionId,
                files,
                toUid,
                this.signalingClient
            );
        } else {
            // 私聊使用P2PSession
            session = new P2PSession(
                sessionId,
                files,
                toUid,
                'sender',
                this.signalingClient,
                chatType
            );
        }
        
        // 设置回调
        this.setupSessionCallbacks(session);
        
        // 添加到活跃会话
        this.activeSessions.set(sessionId, session);
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onTransferInitiated) {
            this.uiHandler.onTransferInitiated(session);
        }
        
        return {
            sessionId: sessionId,
            method: 'p2p',
            status: 'pending',
            session: session,
            chatType: chatType
        };
    }

    /**
     * 接受传输请求
     * @param {string} sessionId - 会话ID
     * @returns {Promise<void>}
     */
    async acceptTransfer(sessionId) {
        console.log('[P2P] acceptTransfer called for session:', sessionId);
        
        const session = this.activeSessions.get(sessionId);
        if (!session) {
            console.error('[P2P] ❌ Session not found in activeSessions');
            console.error('[P2P] Available sessions:', Array.from(this.activeSessions.keys()));
            console.error('[P2P] This may happen if the session expired or was already processed');
            throw new Error('会话不存在或已过期');
        }
        
        console.log('[P2P] ✓ Session found, responding to server...');
        
        // 响应信令服务器
        await this.signalingClient.respondToSession(sessionId, true);
        
        console.log('[P2P] ✓ Server notified, starting WebRTC connection...');
        
        // 接受传输
        await session.accept();
        
        console.log('[P2P] ✓ WebRTC connection initiated');
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onTransferAccepted) {
            this.uiHandler.onTransferAccepted(session);
        }
    }

    /**
     * 拒绝传输请求
     * @param {string} sessionId - 会话ID
     * @param {string} reason - 拒绝原因（可选）
     * @returns {Promise<void>}
     */
    async rejectTransfer(sessionId, reason = '用户拒绝') {
        // 响应信令服务器
        await this.signalingClient.respondToSession(sessionId, false, reason);
        
        // 从活跃会话中移除
        const session = this.activeSessions.get(sessionId);
        if (session) {
            this.activeSessions.delete(sessionId);
        }
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onTransferRejected) {
            this.uiHandler.onTransferRejected(sessionId, reason);
        }
    }

    /**
     * 取消传输
     * @param {string} sessionId - 会话ID
     * @returns {Promise<void>}
     */
    async cancelTransfer(sessionId) {
        console.log('[P2PTransferManager] cancelTransfer called with sessionId:', sessionId);
        console.log('[P2PTransferManager] Active sessions:', Array.from(this.activeSessions.keys()));
        console.log('[P2PTransferManager] Queue:', this.queue.map(item => item.sessionId));
        
        const session = this.activeSessions.get(sessionId);
        if (!session) {
            console.log('[P2PTransferManager] Session not in active sessions, checking queue...');
            
            // 可能在队列中
            const queueIndex = this.queue.findIndex(item => item.sessionId === sessionId);
            if (queueIndex !== -1) {
                console.log('[P2PTransferManager] Found in queue at index:', queueIndex);
                this.queue.splice(queueIndex, 1);
                
                // 通知UI
                if (this.uiHandler && this.uiHandler.onTransferCancelled) {
                    console.log('[P2PTransferManager] Calling onTransferCancelled callback');
                    this.uiHandler.onTransferCancelled(sessionId);
                }
                console.log('[P2PTransferManager] Queue item cancelled successfully');
                return;
            }
            
            console.error('[P2PTransferManager] Session not found in active sessions or queue');
            throw new Error('会话不存在');
        }
        
        console.log('[P2PTransferManager] Found active session, cancelling...');
        
        // 取消会话
        await session.cancel();
        console.log('[P2PTransferManager] Session.cancel() completed');
        
        // 从活跃会话中移除
        this.activeSessions.delete(sessionId);
        console.log('[P2PTransferManager] Removed from active sessions');
        
        // 处理队列中的下一个传输
        await this.processQueue();
        console.log('[P2PTransferManager] Queue processed');
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onTransferCancelled) {
            console.log('[P2PTransferManager] Calling onTransferCancelled callback');
            this.uiHandler.onTransferCancelled(sessionId);
        }
        
        console.log('[P2PTransferManager] cancelTransfer completed successfully');
    }

    /**
     * 设置会话回调
     * @param {P2PSession} session - 会话对象
     */
    setupSessionCallbacks(session) {
        // 进度回调
        session.onProgressCallback = (sessionId, progress, speed, integrityStatus) => {
            if (this.uiHandler && this.uiHandler.onProgress) {
                this.uiHandler.onProgress(sessionId, progress, speed, integrityStatus);
            }
        };
        
        // 完成回调
        session.onCompleteCallback = () => {
            // 从活跃会话中移除
            this.activeSessions.delete(session.id);
            
            // 处理队列中的下一个传输
            this.processQueue();
            
            // 通知UI
            if (this.uiHandler && this.uiHandler.onComplete) {
                this.uiHandler.onComplete(session.id);
            }
        };
        
        // 错误回调
        session.onErrorCallback = (error) => {
            // 从活跃会话中移除
            this.activeSessions.delete(session.id);
            
            // 处理队列中的下一个传输
            this.processQueue();
            
            // 通知UI
            if (this.uiHandler && this.uiHandler.onError) {
                this.uiHandler.onError(session.id, error);
            }
        };
        
        // 状态变化回调
        session.onStatusChangeCallback = (status) => {
            if (this.uiHandler && this.uiHandler.onStatusChange) {
                this.uiHandler.onStatusChange(session.id, status);
            }
        };
    }

    /**
     * 添加到队列
     * @param {File[]} files - 文件数组
     * @param {string} toUid - 接收方用户ID
     * @param {string} chatType - 聊天类型
     * @returns {Promise<Object>} - 返回队列信息
     */
    async addToQueue(files, toUid, chatType) {
        const queueItem = {
            sessionId: `queue_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            files: files,
            toUid: toUid,
            chatType: chatType,
            addedAt: Date.now()
        };
        
        this.queue.push(queueItem);
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onAddedToQueue) {
            this.uiHandler.onAddedToQueue(queueItem);
        }
        
        return {
            sessionId: queueItem.sessionId,
            method: 'p2p',
            status: 'queued',
            queuePosition: this.queue.length
        };
    }

    /**
     * 处理队列中的下一个传输
     * @returns {Promise<void>}
     */
    async processQueue() {
        // 检查是否有空闲槽位
        if (this.activeSessions.size >= this.maxConcurrent) {
            return;
        }
        
        // 检查队列是否为空
        if (this.queue.length === 0) {
            return;
        }
        
        // 取出队列中的第一个
        const queueItem = this.queue.shift();
        
        try {
            // 发起传输
            await this.initiateP2PTransfer(
                queueItem.files,
                queueItem.toUid,
                queueItem.chatType
            );
            
            // 通知UI
            if (this.uiHandler && this.uiHandler.onQueueProcessed) {
                this.uiHandler.onQueueProcessed(queueItem.sessionId);
            }
        } catch (error) {
            console.error('Error processing queue item:', error);
            
            // 通知UI
            if (this.uiHandler && this.uiHandler.onError) {
                this.uiHandler.onError(queueItem.sessionId, error);
            }
        }
    }

    /**
     * 回退到传统上传
     * @param {File[]} files - 文件数组
     * @param {string} toUid - 接收方用户ID
     * @param {string} chatType - 聊天类型
     * @returns {Promise<Object>} - 返回上传信息
     */
    async fallbackToTraditionalUpload(files, toUid, chatType) {
        // 这里应该调用现有的文件上传逻辑
        // 具体实现取决于现有系统的上传API
        
        console.log('Using traditional upload for files:', files);
        
        // 通知UI
        if (this.uiHandler && this.uiHandler.onFallbackToTraditional) {
            this.uiHandler.onFallbackToTraditional(files, toUid, chatType);
        }
        
        return {
            method: 'traditional',
            status: 'uploading',
            files: files
        };
    }

    /**
     * 检查WebRTC支持
     * @returns {boolean} - 是否支持WebRTC
     */
    checkWebRTCSupport() {
        return typeof RTCPeerConnection !== 'undefined' &&
               typeof RTCDataChannel !== 'undefined';
    }

    /**
     * 获取活跃传输列表
     * @returns {Array} - 活跃传输列表
     */
    getActiveTransfers() {
        const transfers = [];
        for (const [sessionId, session] of this.activeSessions) {
            transfers.push({
                sessionId: sessionId,
                peer: session.peer,
                role: session.role,
                status: session.status,
                progress: session.progress,
                files: session.files.map(f => ({
                    name: f.name,
                    size: f.size
                }))
            });
        }
        return transfers;
    }

    /**
     * 获取队列列表
     * @returns {Array} - 队列列表
     */
    getQueuedTransfers() {
        return this.queue.map((item, index) => ({
            sessionId: item.sessionId,
            toUid: item.toUid,
            chatType: item.chatType,
            queuePosition: index + 1,
            files: item.files.map(f => ({
                name: f.name,
                size: f.size
            }))
        }));
    }

    /**
     * 获取会话
     * @param {string} sessionId - 会话ID
     * @returns {P2PSession|null} - 会话对象
     */
    getSession(sessionId) {
        return this.activeSessions.get(sessionId) || null;
    }

    /**
     * 处理群聊接收方接受传输
     * @param {string} sessionId - 会话ID
     * @param {string} receiverUid - 接收方用户ID
     * @returns {Promise<void>}
     */
    async onGroupReceiverAccepted(sessionId, receiverUid) {
        const session = this.activeSessions.get(sessionId);
        if (!session || !(session instanceof P2PGroupSession)) {
            console.error('Invalid group session');
            return;
        }
        
        await session.onReceiverAccepted(receiverUid);
    }

    /**
     * 处理群聊接收方拒绝传输
     * @param {string} sessionId - 会话ID
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} reason - 拒绝原因
     */
    onGroupReceiverRejected(sessionId, receiverUid, reason) {
        const session = this.activeSessions.get(sessionId);
        if (!session || !(session instanceof P2PGroupSession)) {
            console.error('Invalid group session');
            return;
        }
        
        session.onReceiverRejected(receiverUid, reason);
    }

    /**
     * 处理群聊信令
     * @param {string} sessionId - 会话ID
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} type - 信令类型
     * @param {Object} data - 信令数据
     * @returns {Promise<void>}
     */
    async handleGroupSignal(sessionId, receiverUid, type, data) {
        const session = this.activeSessions.get(sessionId);
        if (!session || !(session instanceof P2PGroupSession)) {
            console.error('Invalid group session');
            return;
        }
        
        await session.handleGroupSignal(receiverUid, type, data);
    }

    /**
     * 获取群聊接收方状态
     * @param {string} sessionId - 会话ID
     * @returns {Array} - 接收方状态列表
     */
    getGroupReceiverStatuses(sessionId) {
        const session = this.activeSessions.get(sessionId);
        if (!session || !(session instanceof P2PGroupSession)) {
            return [];
        }
        
        return session.getReceiverStatuses();
    }
}

// 导出类（如果使用模块系统）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = P2PTransferManager;
}
