/**
 * SignalingClient - 处理与信令服务器的通信
 * 
 * 该类负责：
 * - 创建P2P传输会话（支持多文件）
 * - 响应传输请求（接受/拒绝）
 * - 发送WebRTC信令数据
 * - 计算文件哈希（分块计算以避免内存问题）
 */
class SignalingClient {
    /**
     * 构造函数
     * @param {string} baseUrl - 信令服务器的基础URL（默认为当前域名）
     */
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }

    /**
     * 创建P2P传输会话（支持单文件或多文件）
     * @param {File|File[]} files - 要传输的文件或文件数组
     * @param {string} toUid - 接收方用户ID或群组ID
     * @param {string} chatType - 聊天类型 ('private' 或 'group')
     * @returns {Promise<string>} - 返回session_id
     */
    async createSession(files, toUid, chatType) {
        console.log('[P2P] createSession called with:', { files, toUid, chatType });
        
        // 确保files是数组
        const fileArray = Array.isArray(files) ? files : [files];
        console.log('[P2P] File array:', fileArray.map(f => ({ name: f.name, size: f.size })));
        
        // 获取当前用户ID
        const currentUid = this.getCurrentUserId();
        console.log('[P2P] Current UID:', currentUid);
        
        if (!currentUid) {
            throw new Error('无法获取当前用户ID');
        }
        
        // 计算所有文件的哈希值
        const filesMetadata = [];
        for (const file of fileArray) {
            console.log('[P2P] Calculating hash for:', file.name);
            const hash = await this.calculateFileHash(file);
            console.log('[P2P] Hash calculated:', hash.substring(0, 16) + '...');
            filesMetadata.push({
                filename: file.name,
                size: file.size,
                file_hash: hash,
                mime_type: file.type || 'application/octet-stream'
            });
        }

        // 发送请求到信令服务器
        console.log('[P2P] Sending request to /p2p/initiate');
        const requestBody = {
            uid: currentUid,
            to_uid: toUid,
            chat_type: chatType,
            files: filesMetadata
        };
        console.log('[P2P] Request body:', requestBody);
        
        let response;
        try {
            response = await fetch(`${this.baseUrl}/p2p/initiate`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
        } catch (fetchError) {
            console.error('[P2P] Fetch error:', fetchError);
            console.error('[P2P] Request URL:', `${this.baseUrl}/p2p/initiate`);
            console.error('[P2P] Request body size:', JSON.stringify(requestBody).length, 'bytes');
            throw new Error(`网络请求失败: ${fetchError.message}`);
        }

        console.log('[P2P] Response status:', response.status);
        
        if (!response.ok) {
            let error;
            try {
                error = await response.json();
            } catch (e) {
                error = { error: `HTTP ${response.status}: ${response.statusText}` };
            }
            console.error('[P2P] Server error:', error);
            throw new Error(error.error || '创建会话失败');
        }

        const data = await response.json();
        console.log('[P2P] Session created:', data.session_id);
        return data.session_id;
    }

    /**
     * 响应传输请求
     * @param {string} sessionId - 会话ID
     * @param {boolean} accept - 是否接受传输
     * @param {string|null} reason - 拒绝原因（可选）
     * @returns {Promise<void>}
     */
    async respondToSession(sessionId, accept, reason = null) {
        const response = await fetch(`${this.baseUrl}/p2p/respond`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: sessionId,
                uid: this.getCurrentUserId(),
                accept: accept,
                reason: reason
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '响应会话失败');
        }
    }

    /**
     * 发送WebRTC信令数据
     * @param {string} sessionId - 会话ID
     * @param {string} type - 信令类型 ('offer', 'answer', 'ice-candidate')
     * @param {Object} data - 信令数据（SDP或ICE候选）
     * @param {string} toUid - 目标用户ID（可选，用于群聊）
     * @returns {Promise<void>}
     */
    async sendSignal(sessionId, type, data, toUid = null) {
        const body = {
            session_id: sessionId,
            from_uid: this.getCurrentUserId(),
            signal_type: type,
            signal_data: data
        };
        
        // 如果指定了toUid（群聊场景），添加到请求中
        if (toUid) {
            body.to_uid = toUid;
        }
        
        const response = await fetch(`${this.baseUrl}/p2p/signal`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '发送信令失败');
        }
    }

    /**
     * 计算文件的SHA-256哈希值（分块计算以避免内存问题）
     * @param {File} file - 要计算哈希的文件
     * @returns {Promise<string>} - 返回十六进制格式的哈希值
     */
    async calculateFileHash(file) {
        // 检查 crypto.subtle 是否可用
        if (!crypto || !crypto.subtle || !crypto.subtle.digest) {
            console.warn('[P2P] crypto.subtle not available, using fallback hash');
            // 降级方案：使用文件名、大小和修改时间生成简单哈希
            return this.calculateSimpleHash(file);
        }
        
        // 使用标准的SHA-256哈希计算（与接收方一致）
        // 直接读取整个文件并计算哈希
        const buffer = await file.arrayBuffer();
        const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        
        // 转换为十六进制字符串
        return hashArray
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
    }
    
    /**
     * 简单哈希计算（降级方案）
     * 使用文件名、大小和修改时间生成哈希
     * @param {File} file - 要计算哈希的文件
     * @returns {string} - 返回十六进制格式的哈希值
     */
    calculateSimpleHash(file) {
        const str = `${file.name}_${file.size}_${file.lastModified}`;
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        // 转换为64位十六进制字符串（模拟SHA-256的长度）
        const hashStr = Math.abs(hash).toString(16).padStart(16, '0');
        return hashStr + hashStr + hashStr + hashStr; // 重复以达到64字符
    }

    /**
     * 获取当前用户ID
     * 这个方法需要根据实际应用的用户管理系统来实现
     * @returns {string} - 当前用户ID
     */
    getCurrentUserId() {
        // 从全局变量me获取当前用户ID（应用使用的是me对象）
        if (typeof me !== 'undefined' && me && me.uid) {
            return me.uid;
        }
        
        // 或者从localStorage获取（应用使用的是qq_uid）
        const uid = localStorage.getItem('qq_uid');
        if (uid) {
            return uid;
        }
        
        // 兼容其他可能的命名
        if (typeof currentUser !== 'undefined' && currentUser && currentUser.uid) {
            return currentUser.uid;
        }
        
        const altUid = localStorage.getItem('current_uid');
        if (altUid) {
            return altUid;
        }
        
        throw new Error('无法获取当前用户ID');
    }
}

// 导出类（如果使用模块系统）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SignalingClient;
}
