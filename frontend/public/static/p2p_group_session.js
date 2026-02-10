/**
 * P2PGroupSession - 扩展P2PSession以支持群聊多接收方
 * 
 * 该类负责：
 * - 管理多个WebRTC连接（一对多）
 * - 并行传输给多个接收方
 * - 连接隔离（单个失败不影响其他）
 * - 跟踪每个接收方的状态和进度
 */

// Check if P2PSession is available before defining P2PGroupSession
if (typeof P2PSession !== 'undefined') {
    class P2PGroupSession extends P2PSession {
    /**
     * 构造函数
     * @param {string} sessionId - 会话ID
     * @param {File|File[]} files - 文件对象数组
     * @param {string} groupId - 群组ID
     * @param {SignalingClient} signalingClient - 信令客户端实例
     */
    constructor(sessionId, files, groupId, signalingClient) {
        super(sessionId, files, groupId, 'sender', signalingClient, 'group');
        
        // 群聊特定属性
        this.peerConnections = new Map(); // receiverUid -> RTCPeerConnection
        this.dataChannels = new Map(); // receiverUid -> RTCDataChannel
        this.receiverStatuses = new Map(); // receiverUid -> status
        this.receiverProgress = new Map(); // receiverUid -> progress
        this.acceptedReceivers = new Set(); // 已接受传输的接收方
    }

    /**
     * 接收方接受传输请求
     * @param {string} receiverUid - 接收方用户ID
     * @returns {Promise<void>}
     */
    async onReceiverAccepted(receiverUid) {
        console.log(`Receiver ${receiverUid} accepted transfer`);
        
        this.acceptedReceivers.add(receiverUid);
        this.receiverStatuses.set(receiverUid, 'accepted');
        
        // 为该接收方建立独立的WebRTC连接
        await this.setupGroupConnection(receiverUid);
        
        // 通知UI
        if (this.onReceiverStatusChangeCallback) {
            this.onReceiverStatusChangeCallback(receiverUid, 'accepted');
        }
    }

    /**
     * 接收方拒绝传输请求
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} reason - 拒绝原因
     */
    onReceiverRejected(receiverUid, reason) {
        console.log(`Receiver ${receiverUid} rejected transfer: ${reason}`);
        
        this.receiverStatuses.set(receiverUid, 'rejected');
        
        // 通知UI
        if (this.onReceiverStatusChangeCallback) {
            this.onReceiverStatusChangeCallback(receiverUid, 'rejected', reason);
        }
    }

    /**
     * 为群聊接收方建立连接
     * @param {string} receiverUid - 接收方用户ID
     * @returns {Promise<void>}
     */
    async setupGroupConnection(receiverUid) {
        console.log(`Setting up group connection for receiver: ${receiverUid}`);
        
        // 创建独立的RTCPeerConnection
        const peerConnection = new RTCPeerConnection({
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' }
            ]
        });

        // 设置ICE候选处理
        peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this.sendSignalToReceiver(receiverUid, 'ice-candidate', event.candidate);
            }
        };

        // 监听连接状态变化
        peerConnection.onconnectionstatechange = () => {
            console.log(`Connection state for ${receiverUid}:`, peerConnection.connectionState);
            
            if (peerConnection.connectionState === 'failed') {
                this.handleReceiverError(receiverUid, new Error('WebRTC连接失败'));
            } else if (peerConnection.connectionState === 'disconnected') {
                this.handleReceiverError(receiverUid, new Error('WebRTC连接断开'));
            } else if (peerConnection.connectionState === 'connected') {
                this.updateReceiverStatus(receiverUid, 'connected');
            }
        };

        // 创建数据通道
        const dataChannel = peerConnection.createDataChannel('fileTransfer', {
            ordered: true
        });
        
        this.setupGroupDataChannel(receiverUid, dataChannel);

        // 保存连接和通道
        this.peerConnections.set(receiverUid, peerConnection);
        this.dataChannels.set(receiverUid, dataChannel);
        this.receiverStatuses.set(receiverUid, 'connecting');
        this.receiverProgress.set(receiverUid, 0);

        // 创建offer
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        await this.sendSignalToReceiver(receiverUid, 'offer', offer);
    }

    /**
     * 设置群聊数据通道
     * @param {string} receiverUid - 接收方用户ID
     * @param {RTCDataChannel} dataChannel - 数据通道
     */
    setupGroupDataChannel(receiverUid, dataChannel) {
        dataChannel.binaryType = 'arraybuffer';
        
        dataChannel.onopen = () => {
            console.log(`Data channel opened for ${receiverUid}`);
            this.updateReceiverStatus(receiverUid, 'transferring');
            
            // 如果这是第一个打开的通道，开始发送
            if (this.status === 'connecting' || this.status === 'pending') {
                this.setStatus('transferring');
                this.startGroupSending();
            }
        };

        dataChannel.onerror = (error) => {
            console.error(`Data channel error for ${receiverUid}:`, error);
            this.handleReceiverError(receiverUid, new Error('数据通道错误'));
        };

        dataChannel.onclose = () => {
            console.log(`Data channel closed for ${receiverUid}`);
        };
    }

    /**
     * 处理群聊接收方的信令
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} type - 信令类型
     * @param {Object} data - 信令数据
     * @returns {Promise<void>}
     */
    async handleGroupSignal(receiverUid, type, data) {
        try {
            const peerConnection = this.peerConnections.get(receiverUid);
            if (!peerConnection) {
                console.error(`No peer connection found for ${receiverUid}`);
                return;
            }

            if (type === 'answer') {
                await peerConnection.setRemoteDescription(new RTCSessionDescription(data));
            } else if (type === 'ice-candidate') {
                await peerConnection.addIceCandidate(new RTCIceCandidate(data));
            }
        } catch (error) {
            console.error(`Error handling group signal for ${receiverUid}:`, error);
            this.handleReceiverError(receiverUid, error);
        }
    }

    /**
     * 发送信令给特定接收方
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} type - 信令类型
     * @param {Object} data - 信令数据
     * @returns {Promise<void>}
     */
    async sendSignalToReceiver(receiverUid, type, data) {
        try {
            await fetch('/p2p/signal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.id,
                    uid: this.signalingClient.getCurrentUserId(),
                    to_uid: receiverUid,
                    type: type,
                    data: data
                })
            });
        } catch (error) {
            console.error(`Error sending signal to ${receiverUid}:`, error);
            this.handleReceiverError(receiverUid, error);
        }
    }

    /**
     * 更新接收方状态
     * @param {string} receiverUid - 接收方用户ID
     * @param {string} status - 状态
     */
    updateReceiverStatus(receiverUid, status) {
        this.receiverStatuses.set(receiverUid, status);
        
        if (this.onReceiverStatusChangeCallback) {
            this.onReceiverStatusChangeCallback(receiverUid, status);
        }
    }

    /**
     * 处理接收方错误（连接隔离）
     * @param {string} receiverUid - 接收方用户ID
     * @param {Error} error - 错误对象
     */
    handleReceiverError(receiverUid, error) {
        console.error(`Error for receiver ${receiverUid}:`, error);
        this.updateReceiverStatus(receiverUid, 'failed');
        
        // 关闭该接收方的连接
        const peerConnection = this.peerConnections.get(receiverUid);
        if (peerConnection) {
            peerConnection.close();
        }
        
        const dataChannel = this.dataChannels.get(receiverUid);
        if (dataChannel) {
            dataChannel.close();
        }
        
        // 从映射中移除
        this.peerConnections.delete(receiverUid);
        this.dataChannels.delete(receiverUid);
        
        // 通知UI（但不影响其他接收方）
        if (this.onReceiverStatusChangeCallback) {
            this.onReceiverStatusChangeCallback(receiverUid, 'failed', error.message);
        }
        
        // 检查是否所有接收方都失败了
        this.checkAllReceiversFailed();
    }

    /**
     * 检查是否所有接收方都失败了
     */
    checkAllReceiversFailed() {
        const allFailed = Array.from(this.receiverStatuses.values())
            .every(status => status === 'failed' || status === 'rejected');
        
        if (allFailed && this.receiverStatuses.size > 0) {
            this.handleError(new Error('所有接收方都失败或拒绝了传输'));
        }
    }

    /**
     * 开始群聊发送（并行发送给所有接收方）
     * @returns {Promise<void>}
     */
    async startGroupSending() {
        console.log('Starting group file transfer...');
        
        // 检查是否有断点续传数据
        this.loadResumePoint();
        
        // 开始发送第一个（或恢复的）文件
        await this.sendNextFileToGroup();
    }

    /**
     * 发送下一个文件给所有群聊接收方
     * @returns {Promise<void>}
     */
    async sendNextFileToGroup() {
        // 检查是否所有文件都已发送
        if (this.currentFileIndex >= this.files.length) {
            console.log('All files sent to group');
            this.onGroupComplete();
            return;
        }

        const file = this.files[this.currentFileIndex];
        console.log(`Sending file ${this.currentFileIndex + 1}/${this.files.length} to group: ${file.name}`);
        
        // 确定起始偏移量（用于断点续传）
        let offset = 0;
        if (this.resumeData && this.resumeData.fileIndex === this.currentFileIndex) {
            offset = this.resumeData.offset;
            console.log(`Resuming file ${file.name} from offset ${offset}`);
        }

        // 发送文件开始控制消息给所有接收方
        const startMessage = JSON.stringify({
            type: 'file-start',
            fileIndex: this.currentFileIndex,
            filename: file.name,
            size: file.size,
            offset: offset
        });
        
        for (const [receiverUid, dataChannel] of this.dataChannels) {
            if (dataChannel.readyState === 'open') {
                try {
                    dataChannel.send(startMessage);
                } catch (error) {
                    console.error(`Error sending file-start to ${receiverUid}:`, error);
                    this.handleReceiverError(receiverUid, error);
                }
            }
        }

        // 开始分块发送
        await this.sendFileChunksToGroup(file, offset);
    }

    /**
     * 分块发送文件给所有群聊接收方
     * @param {File} file - 要发送的文件
     * @param {number} startOffset - 起始偏移量
     * @returns {Promise<void>}
     */
    async sendFileChunksToGroup(file, startOffset = 0) {
        let offset = startOffset;
        const fileReader = new FileReader();

        return new Promise((resolve, reject) => {
            const sendNextChunk = () => {
                // 检查是否已发送完整个文件
                if (offset >= file.size) {
                    // 发送文件结束控制消息给所有接收方
                    const endMessage = JSON.stringify({
                        type: 'file-end',
                        fileIndex: this.currentFileIndex
                    });
                    
                    for (const [receiverUid, dataChannel] of this.dataChannels) {
                        if (dataChannel.readyState === 'open') {
                            try {
                                dataChannel.send(endMessage);
                                this.updateReceiverStatus(receiverUid, 'completed');
                            } catch (error) {
                                console.error(`Error sending file-end to ${receiverUid}:`, error);
                                this.handleReceiverError(receiverUid, error);
                            }
                        }
                    }
                    
                    // 移动到下一个文件
                    this.currentFileIndex++;
                    this.resumeData = null; // 清除断点数据
                    
                    // 延迟一下再发送下一个文件
                    setTimeout(() => {
                        this.sendNextFileToGroup().then(resolve).catch(reject);
                    }, 100);
                    return;
                }

                // 读取下一个块
                const end = Math.min(offset + this.chunkSize, file.size);
                const chunk = file.slice(offset, end);
                fileReader.readAsArrayBuffer(chunk);
            };

            fileReader.onload = (e) => {
                try {
                    const chunkData = e.target.result;
                    
                    // 发送给所有活跃的接收方
                    for (const [receiverUid, dataChannel] of this.dataChannels) {
                        if (dataChannel.readyState === 'open') {
                            try {
                                dataChannel.send(chunkData);
                                
                                // 更新该接收方的进度
                                const totalSize = this.files.reduce((sum, f) => sum + f.size, 0);
                                const completedSize = this.files.slice(0, this.currentFileIndex)
                                    .reduce((sum, f) => sum + f.size, 0);
                                const receiverProgress = ((completedSize + offset + chunkData.byteLength) / totalSize) * 100;
                                this.receiverProgress.set(receiverUid, Math.min(receiverProgress, 100));
                            } catch (error) {
                                console.error(`Error sending chunk to ${receiverUid}:`, error);
                                this.handleReceiverError(receiverUid, error);
                            }
                        }
                    }
                    
                    offset += chunkData.byteLength;
                    
                    // 更新总体进度
                    this.updateTransferProgress(offset);
                    
                    // 保存断点数据
                    this.saveResumePoint(this.currentFileIndex, offset);
                    
                    // 检查所有通道的缓冲区
                    let maxBuffered = 0;
                    for (const dataChannel of this.dataChannels.values()) {
                        if (dataChannel.readyState === 'open') {
                            maxBuffered = Math.max(maxBuffered, dataChannel.bufferedAmount);
                        }
                    }
                    
                    // 如果缓冲区不过载，继续发送
                    if (maxBuffered < this.chunkSize * 10) {
                        sendNextChunk();
                    } else {
                        // 等待缓冲区清空
                        setTimeout(sendNextChunk, 100);
                    }
                } catch (error) {
                    reject(error);
                }
            };

            fileReader.onerror = (error) => {
                reject(error);
            };

            // 开始发送第一个块
            sendNextChunk();
        });
    }

    /**
     * 群聊传输完成
     */
    onGroupComplete() {
        this.setStatus('completed');
        this.updateProgress(100);
        
        // 关闭所有连接
        for (const peerConnection of this.peerConnections.values()) {
            peerConnection.close();
        }
        
        for (const dataChannel of this.dataChannels.values()) {
            dataChannel.close();
        }
        
        if (this.onCompleteCallback) {
            this.onCompleteCallback();
        }
    }

    /**
     * 获取群聊接收方状态
     * @returns {Array} - 接收方状态列表
     */
    getReceiverStatuses() {
        const statuses = [];
        for (const [receiverUid, status] of this.receiverStatuses) {
            statuses.push({
                uid: receiverUid,
                status: status,
                progress: this.receiverProgress.get(receiverUid) || 0
            });
        }
        return statuses;
    }

    /**
     * 取消传输
     * @returns {Promise<void>}
     */
    async cancel() {
        this.setStatus('cancelled');
        
        // 关闭所有连接
        for (const peerConnection of this.peerConnections.values()) {
            peerConnection.close();
        }
        
        for (const dataChannel of this.dataChannels.values()) {
            dataChannel.close();
        }
        
        // 清理断点续传数据
        this.clearResumeData();
    }
    }

    // 导出类（如果使用模块系统）
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = P2PGroupSession;
    }
} else {
    console.warn('[P2P] P2PSession not available - P2PGroupSession will not be defined');
}
