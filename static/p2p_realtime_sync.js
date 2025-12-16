/**
 * RealtimeSync - 负责实时同步数据库状态变化到前端界面
 * 
 * 该类通过WebSocket连接实现实时通信，支持状态更新、进度更新和有效性更新的实时推送。
 * 包含自动重连机制（指数退避）和心跳机制以保持连接稳定。
 * 如果WebSocket不可用，自动降级到轮询模式。
 */
class RealtimeSync {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 3; // 减少重试次数
        this.updateCallbacks = new Map();
        this.onSystemMessage = null;
        this.heartbeatInterval = null;
        this.heartbeatTimeout = null;
        this.isConnecting = false;
        this.usePolling = false; // 是否使用轮询模式
        this.pollingInterval = null;
        this.connect();
    }
    
    /**
     * 建立WebSocket连接
     */
    connect() {
        if (this.isConnecting || (this.ws && this.ws.readyState === WebSocket.OPEN)) {
            return;
        }
        
        // 如果已经达到最大重试次数，切换到轮询模式
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            if (window.CURRENT_LOG_LEVEL >= 3) {
                console.log('WebSocket连接失败次数过多，切换到轮询模式');
            }
            this.startPolling();
            return;
        }
        
        this.isConnecting = true;
        
        // 构建WebSocket URL
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/ws/p2p-updates`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                if (window.CURRENT_LOG_LEVEL >= 3) {
                    console.log('WebSocket connected');
                }
                this.reconnectAttempts = 0;
                this.isConnecting = false;
                this.usePolling = false;
                this.startHeartbeat();
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleUpdate(data);
                } catch (error) {
                    console.error('Failed to parse WebSocket message:', error);
                }
            };
            
            this.ws.onerror = (error) => {
                // 减少错误日志输出 - 只在WARN级别以上显示
                if (this.reconnectAttempts === 0 && window.CURRENT_LOG_LEVEL >= 2) {
                    console.warn('WebSocket连接失败，将尝试重连或切换到轮询模式');
                }
                this.isConnecting = false;
            };
            
            this.ws.onclose = () => {
                if (this.reconnectAttempts === 0 && window.CURRENT_LOG_LEVEL >= 3) {
                    console.log('WebSocket disconnected');
                }
                this.isConnecting = false;
                this.stopHeartbeat();
                this.attemptReconnect();
            };
        } catch (error) {
            console.error('Failed to create WebSocket connection:', error);
            this.isConnecting = false;
            this.attemptReconnect();
        }
    }
    
    /**
     * 处理从服务器接收的更新
     * @param {Object} data - 更新数据
     */
    handleUpdate(data) {
        const { type, transferId, payload } = data;
        
        switch (type) {
            case 'status_update':
                this.notifyStatusUpdate(transferId, payload);
                break;
            case 'progress_update':
                this.notifyProgressUpdate(transferId, payload);
                break;
            case 'validity_update':
                this.notifyValidityUpdate(transferId, payload);
                break;
            case 'system_message':
                this.notifySystemMessage(payload);
                break;
            case 'pong':
                this.handlePong();
                break;
            default:
                console.warn('Unknown message type:', type);
        }
    }
    
    /**
     * 通知状态更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    notifyStatusUpdate(transferId, payload) {
        const callbacks = this.updateCallbacks.get(transferId);
        if (callbacks && callbacks.onStatusUpdate) {
            callbacks.onStatusUpdate(payload);
        }
    }
    
    /**
     * 通知进度更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    notifyProgressUpdate(transferId, payload) {
        const callbacks = this.updateCallbacks.get(transferId);
        if (callbacks && callbacks.onProgressUpdate) {
            callbacks.onProgressUpdate(payload);
        }
    }
    
    /**
     * 通知有效性更新
     * @param {string} transferId - 传输ID
     * @param {Object} payload - 更新数据
     */
    notifyValidityUpdate(transferId, payload) {
        const callbacks = this.updateCallbacks.get(transferId);
        if (callbacks && callbacks.onValidityUpdate) {
            callbacks.onValidityUpdate(payload);
        }
    }
    
    /**
     * 通知系统消息
     * @param {Object} payload - 消息数据
     */
    notifySystemMessage(payload) {
        if (this.onSystemMessage) {
            this.onSystemMessage(payload);
        }
    }
    
    /**
     * 注册回调函数
     * @param {string} transferId - 传输ID
     * @param {Object} callbacks - 回调函数对象
     */
    registerCallbacks(transferId, callbacks) {
        this.updateCallbacks.set(transferId, callbacks);
        
        // 订阅该传输的更新
        this.send({
            type: 'subscribe',
            transferId: transferId
        });
    }
    
    /**
     * 注销回调函数
     * @param {string} transferId - 传输ID
     */
    unregisterCallbacks(transferId) {
        this.updateCallbacks.delete(transferId);
        
        // 取消订阅
        this.send({
            type: 'unsubscribe',
            transferId: transferId
        });
    }
    
    /**
     * 尝试重新连接
     */
    attemptReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            if (window.CURRENT_LOG_LEVEL >= 1) {
                console.error('Max reconnect attempts reached');
            }
            return;
        }
        
        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        
        if (window.CURRENT_LOG_LEVEL >= 3) {
            console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        }
        
        setTimeout(() => {
            this.connect();
        }, delay);
    }
    
    /**
     * 发送数据到服务器
     * @param {Object} data - 要发送的数据
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(data));
            } catch (error) {
                console.error('Failed to send WebSocket message:', error);
            }
        } else {
            console.warn('WebSocket is not connected, cannot send message');
        }
    }
    
    /**
     * 启动心跳机制
     */
    startHeartbeat() {
        // 清除现有的心跳
        this.stopHeartbeat();
        
        // 每30秒发送一次心跳
        this.heartbeatInterval = setInterval(() => {
            this.send({ type: 'ping' });
            
            // 设置心跳超时（10秒）
            this.heartbeatTimeout = setTimeout(() => {
                console.warn('Heartbeat timeout, closing connection');
                if (this.ws) {
                    this.ws.close();
                }
            }, 10000);
        }, 30000);
    }
    
    /**
     * 停止心跳机制
     */
    stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
        }
    }
    
    /**
     * 启动轮询模式（WebSocket不可用时的降级方案）
     */
    startPolling() {
        if (this.pollingInterval) {
            return; // 已经在轮询中
        }
        
        this.usePolling = true;
        if (window.CURRENT_LOG_LEVEL >= 3) {
            console.log('使用轮询模式进行实时同步');
        }
        
        // 每5秒轮询一次
        this.pollingInterval = setInterval(() => {
            // 这里可以调用API获取更新
            // 由于没有具体的轮询API，暂时只是占位
            // 实际使用时需要实现轮询逻辑
        }, 5000);
    }
    
    /**
     * 停止轮询
     */
    stopPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
        this.usePolling = false;
    }
    
    /**
     * 清理资源
     */
    destroy() {
        this.stopHeartbeat();
        this.stopPolling();
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.updateCallbacks.clear();
    }
    
    /**
     * 处理心跳响应
     */
    handlePong() {
        // 清除心跳超时
        if (this.heartbeatTimeout) {
            clearTimeout(this.heartbeatTimeout);
            this.heartbeatTimeout = null;
        }
    }
    
    /**
     * 关闭连接
     */
    close() {
        this.stopHeartbeat();
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.updateCallbacks.clear();
        this.reconnectAttempts = this.maxReconnectAttempts; // 防止自动重连
    }
    
    /**
     * 检查连接状态
     * @returns {boolean} 是否已连接
     */
    isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }
}

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RealtimeSync;
}
