
let me = null, target = null;
// 重构：删除全局 msgs 数组，使用 currentChatMsgs 仅存储当前聊天的消息
let cache = { users: {}, groups: {}, read_markers: {}, pinned: {}, remarks: {} };
let currentChatMsgs = [];  // 仅存储当前激活聊天的消息（约30-50条）
let lastId = 0, selUids = new Set(), devClicks = 0;
let pollingTimer = null;
let preventRenderChat = false;  // 防止在发送消息后立即重新渲染
let uploadQueue = [], isUploading = false;
let visualOn = false;

// ==================== 版本控制 ====================
// 用户和群组的版本号追踪，用于检测服务器端的变更
let userVersions = {};   // {uid: version, ...}
let groupVersions = {};  // {gid: version, ...}

// ==================== 类型安全工具函数 ====================
/**
 * 安全 ID 转换函数 - 确保所有 ID 比较使用统一的 String 类型
 * 解决审计报告中的核心问题：SQLite INTEGER ID vs JS String/Number 类型不匹配
 * @param {any} value - 任意类型的 ID 值
 * @returns {string} - 统一的 String 类型 ID
 */
function safeId(value) {
    if (value === null || value === undefined) return '';
    return String(value);
}

/**
 * 安全 ID 比较函数 - 确保两个 ID 值的比较不受类型影响
 * @param {any} id1 - 第一个 ID
 * @param {any} id2 - 第二个 ID
 * @returns {boolean} - 是否相等
 */
function safeIdEqual(id1, id2) {
    return safeId(id1) === safeId(id2);
}

/**
 * 在数组中查找消息的索引 - 使用安全 ID 比较
 * @param {Array} arr - 消息数组
 * @param {any} id - 要查找的 ID
 * @returns {number} - 索引，找不到返回 -1
 */
function findMsgIndexById(arr, id) {
    var targetId = safeId(id);
    for (var i = 0; i < arr.length; i++) {
        if (safeId(arr[i].id) === targetId) return i;
    }
    return -1;
}

/**
 * 在数组中查找消息 - 使用安全 ID 比较
 * @param {Array} arr - 消息数组
 * @param {any} id - 要查找的 ID
 * @returns {Object|undefined} - 找到的消息或 undefined
 */
function findMsgById(arr, id) {
    var idx = findMsgIndexById(arr, id);
    return idx !== -1 ? arr[idx] : undefined;
}

let isMulti = false;
let selMsgs = new Set();
let fwdMode = null;
let ctxMsg = null;
let quoteMsg = null;
let ctxFwdData = null;
let fwdStack = [];
let listCtxTargetId = null;
let profileTargetUid = null;

let currentNotifChatId = null;
let notifTimer = null;
let isFirstSync = true;
let scrollUnreadCount = 0;
// ==================== 日志级别控制系统 ====================
const LOG_LEVEL = {
    NONE: 0,
    ERROR: 1,
    WARN: 2,
    INFO: 3,
    DEBUG: 4
};

// 生产环境设置为 NONE（完全静默），开发时可通过控制台调整
// 调试方法: localStorage.setItem('LOG_LEVEL', '4'); location.reload();
let CURRENT_LOG_LEVEL = LOG_LEVEL.NONE;
try {
    const savedLevel = localStorage.getItem('LOG_LEVEL');
    if (savedLevel !== null) {
        CURRENT_LOG_LEVEL = parseInt(savedLevel);
    }
} catch (e) { }

// 封装日志函数
function logDebug(tag, ...args) {
    if (CURRENT_LOG_LEVEL >= LOG_LEVEL.DEBUG) {
        console.log(`[${tag}]`, ...args);
    }
}

function logInfo(tag, ...args) {
    if (CURRENT_LOG_LEVEL >= LOG_LEVEL.INFO) {
        console.log(`[${tag}]`, ...args);
    }
}

function logWarn(tag, ...args) {
    if (CURRENT_LOG_LEVEL >= LOG_LEVEL.WARN) {
        console.warn(`[${tag}]`, ...args);
    }
}

function logError(tag, ...args) {
    if (CURRENT_LOG_LEVEL >= LOG_LEVEL.ERROR) {
        console.error(`[${tag}]`, ...args);
    }
}

let lastScrollTop = 0;

// 页面加载时间戳，用于区分历史消息和实时新消息
const pageLoadTimestamp = Date.now() / 1000;

// ==================== 懒加载配置（优化版 - 丝滑无限滚动） ====================
const LAZY_LOAD_CONFIG = {
    initialLoadCount: 50,       // 初始加载的消息数量（增加到50减少初次加载后触发预加载的频率）
    loadMoreCount: 50,          // 每次向上滚动时加载更多的数量（增加到50减少请求频率）
    loadThreshold: 800,         // 距离顶部多少像素时触发加载（约1.5-2屏高度，提前预加载）
    loadThresholdBottom: 800,   // 距离底部多少像素时触发加载（用于跳转模式向下加载）
    isLoadingHistory: false,    // 是否正在加载历史消息
    isSilentLoading: false,     // 是否是静默加载（不显示spinner）
    hasMoreHistory: {},         // 每个聊天是否还有更早的消息 { chatId: bool }
    oldestMsgId: {},           // 每个聊天中最早的消息ID { chatId: id }
    isInitialLoad: true,        // 是否是初始加载（用于区分sync和历史加载）
    lastFetchTime: 0,           // 上次请求的时间戳（用于节流）
    pendingPrefetch: null       // 待执行的预加载Promise（用于检测静默加载是否完成）
};

// ==================== 消息ID追踪 ====================
// 用于严格的按需懒加载
let minMsgId = 0;  // 当前聊天视图中最旧消息的ID
let maxMsgId = 0;  // 当前聊天视图中最新消息的ID
let activeChatLoaded = false;  // 当前聊天是否已完成初始加载

// ==================== 跳转模式状态 ====================
let isInJumpMode = false;  // 是否处于跳转模式（通过引用消息跳转后）
let hasNewerMessages = false;  // 是否还有更新的消息可加载
let isLoadingNewer = false;  // 是否正在加载更新的消息

// ==================== UnreadManager 未读状态管理器 ====================
/**
 * 未读消息状态管理器 - 统一管理所有未读状态
 * 
 * 核心设计原则：
 * 1. 单一数据源：后端是未读计数的权威来源
 * 2. 乐观更新：前端即时响应，后端异步校验
 * 3. 类型安全：所有 ID 比较统一使用字符串
 * 4. 事件驱动：状态变更触发统一的 UI 更新
 */
const UnreadManager = {
    // 用于证该模块已加载
    _initialized: false,

    /**
     * 初始化管理器
     */
    init() {
        this._initialized = true;
        logInfo('UnreadManager', '✓ 未读状态管理器已初始化');
    },

    /**
     * 获取指定聊天的未读数
     * @param {string} chatId - 聊天 ID
     * @param {string} type - 聊天类型 ('group' 或 'private')
     * @returns {number} 未读消息数
     */
    getCount(chatId, type) {
        // 获取 _sidebar 数据
        const sidebarData = this._getSidebarData(chatId, type);

        // 如果没有 _sidebar 数据，说明没有消息
        if (!sidebarData) return 0;

        // 检查最后一条消息是否是自己发的
        // 如果是自己发的，不显示红点
        const lastMsgFromUid = sidebarData.lastMsgFromUid || null;
        if (me && lastMsgFromUid && String(lastMsgFromUid) === String(me.uid)) {
            return 0;
        }

        // 返回后端计算的未读数
        return sidebarData.unreadCount || 0;
    },

    /**
     * 处理新消息到达时的未读状态更新
     * @param {Object} msg - 消息对象
     */
    onNewMessage(msg) {
        if (!msg || !me) return;

        // 系统消息不计入未读数
        if (msg.type === 'system') return;

        // 自己发的消息不计入未读数
        if (String(msg.from_uid) === String(me.uid)) return;

        // 确定这条消息属于哪个聊天
        const chatInfo = this._getChatInfoFromMsg(msg);
        if (!chatInfo) return;

        const { chatId, type } = chatInfo;

        // 关键修复：统一转换为 String 进行比较，避免类型不匹配
        // 如果用户当前正在查看这个聊天，不增加未读数
        if (target && String(target.id) === String(chatId)) return;

        // 乐观更新：立即增加未读计数
        this._incrementUnreadCount(chatId, type);

        // 触发 UI 更新
        this.notifyUI();
    },

    /**
     * 标记聊天为已读（乐观更新）
     * @param {string} chatId - 聊天 ID
     * @param {string} type - 聊天类型
     * @param {string} msgId - 要标记已读的消息 ID
     * @returns {Promise} 后端请求结果
     */
    async markAsRead(chatId, type, msgId) {
        if (!me || !chatId || !msgId) return;

        // **乐观更新**：立即重置未读计数
        this._setUnreadCount(chatId, type, 0);

        // 更新本地已读标记
        if (!cache.read_markers) cache.read_markers = {};
        if (!cache.read_markers[me.uid]) cache.read_markers[me.uid] = {};

        const currentRead = cache.read_markers[me.uid][chatId] || '0';
        if (compareIds(msgId, currentRead) > 0) {
            cache.read_markers[me.uid][chatId] = String(msgId);
        }

        // 立即触发 UI 更新
        this.notifyUI();

        // 异步发送后端请求（带校验）
        try {
            const response = await fetch('/mark_read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    uid: me.uid,
                    chat_id: chatId,
                    msg_id: msgId
                })
            });

            const result = await response.json();

            // **服务端校验**：如果后端返回的未读数与乐观更新不一致，修正它
            if (result.unread_count !== undefined && result.unread_count !== 0) {
                logDebug('UnreadManager', '校验修正：', chatId, '后端未读数=', result.unread_count);
                this._setUnreadCount(chatId, type, result.unread_count);
                this.notifyUI();
            }

            return result;
        } catch (e) {
            logError('UnreadManager', 'mark_read 请求失败:', e);
        }
    },

    /**
     * 从服务端同步状态（当收到 /sync 响应时调用）
     * @param {Object} syncData - /sync 接口返回的数据
     */
    syncFromServer(syncData) {
        if (!syncData) return;

        // 同步 read_markers
        if (syncData.read_markers) {
            if (!cache.read_markers) cache.read_markers = {};

            for (const uid in syncData.read_markers) {
                if (!cache.read_markers[uid]) cache.read_markers[uid] = {};

                for (const chatId in syncData.read_markers[uid]) {
                    const serverValue = syncData.read_markers[uid][chatId];
                    const localValue = cache.read_markers[uid][chatId] || '0';

                    // 对于当前用户，取较大值（避免回退）
                    if (me && uid === me.uid) {
                        if (compareIds(serverValue, localValue) > 0) {
                            cache.read_markers[uid][chatId] = String(serverValue);
                        }
                    } else {
                        // 对于其他用户，直接用服务端值
                        cache.read_markers[uid][chatId] = String(serverValue);
                    }
                }
            }
        }

        // 服务端的 _sidebar.unreadCount 已经包含在 users 和 groups 中
        // 不需要额外处理，由 sync() 函数处理合并逻辑
    },

    /**
     * 当用户进入聊天时调用（乐观清除未读）
     * @param {string} chatId - 聊天 ID
     * @param {string} type - 聊天类型
     */
    onEnterChat(chatId, type) {
        // 立即清除未读计数（乐观更新）
        this._setUnreadCount(chatId, type, 0);
        this.notifyUI();
    },

    /**
     * 通知 UI 更新
     */
    notifyUI() {
        // 更新侧边栏列表
        if (typeof updateListUI === 'function') {
            updateListUI();
        }

        // 更新移动端未读消息气泡
        if (typeof updateMobileUnreadBadge === 'function') {
            updateMobileUnreadBadge();
        }
    },

    // ==================== 私有方法 ====================

    /**
     * 获取 _sidebar 数据
     */
    _getSidebarData(chatId, type) {
        if (type === 'group') {
            const g = cache.groups[chatId];
            return g && g._sidebar ? g._sidebar : null;
        } else {
            const u = cache.users[chatId];
            return u && u._sidebar ? u._sidebar : null;
        }
    },

    /**
     * 从消息对象确定属于哪个聊天
     */
    _getChatInfoFromMsg(msg) {
        if (!me) return null;

        // 群聊消息
        if (cache.groups[msg.to_uid]) {
            return { chatId: msg.to_uid, type: 'group' };
        }

        // 私聊消息
        if (String(msg.from_uid) === String(me.uid)) {
            // 我发的消息，聊天对象是接收者
            return { chatId: msg.to_uid, type: 'private' };
        } else if (String(msg.to_uid) === String(me.uid)) {
            // 发给我的消息，聊天对象是发送者
            return { chatId: msg.from_uid, type: 'private' };
        }

        return null;
    },

    /**
     * 增加未读计数
     */
    _incrementUnreadCount(chatId, type) {
        const sidebarData = this._getSidebarData(chatId, type);
        if (sidebarData) {
            sidebarData.unreadCount = (sidebarData.unreadCount || 0) + 1;
        }
    },

    /**
     * 设置未读计数
     */
    _setUnreadCount(chatId, type, count) {
        if (type === 'group') {
            if (cache.groups[chatId] && cache.groups[chatId]._sidebar) {
                cache.groups[chatId]._sidebar.unreadCount = count;
            }
        } else {
            if (cache.users[chatId] && cache.users[chatId]._sidebar) {
                cache.users[chatId]._sidebar.unreadCount = count;
            }
        }
    }
};

// 初始化 UnreadManager
UnreadManager.init();

// Emoji映射表 - 将emoji字符映射到本地图片(动态加载)
let emojiMapping = {};

// 将emoji字符转换为图片标签
function emojiToImg(emoji) {
    const filename = emojiMapping[emoji];
    if (filename) {
        return '<img src="/static/emoji/' + filename + '" class="emoji-img" alt="' + emoji + '" title="' + emoji + '">';
    }
    return emoji;
}

// 将emoji字符转换为分类栏使用的图片标签(更大尺寸)
function categoryEmojiToImg(emoji) {
    const filename = emojiMapping[emoji];
    if (filename) {
        return '<img src="/static/emoji/' + filename + '" class="emoji-img-category" alt="' + emoji + '" title="' + emoji + '">';
    }
    return emoji;
}

// 将文本中的emoji字符批量转换为图片
function convertEmojiToImg(text) {
    let result = '';
    for (const char of text) {
        if (emojiMapping[char]) {
            result += emojiToImg(char);
        } else {
            result += char;
        }
    }
    return result;
}

// 加载Emoji映射表
async function loadEmojiMapping() {
    logDebug('Emoji Mapping', '开始加载emoji映射表...');
    logDebug('Emoji Mapping', '请求URL: /static/emoji_mapping.json');
    try {
        const response = await fetch('/static/emoji_mapping.json');
        logDebug('Emoji Mapping', '响应状态:', response.status, response.statusText);

        if (!response.ok) {
            throw new Error('Emoji mapping not found, status: ' + response.status);
        }

        const jsonData = await response.json();
        emojiMapping = jsonData;

        logInfo('Emoji Mapping', '✓ Emoji映射表加载成功');
        logDebug('Emoji Mapping', '包含emoji数量:', Object.keys(emojiMapping).length);
        logDebug('Emoji Mapping', '示例数据:', Object.entries(emojiMapping).slice(0, 3));
        logDebug('Emoji Mapping', 'emojiMapping类型:', typeof emojiMapping);
        logDebug('Emoji Mapping', 'emojiMapping是否为null:', emojiMapping === null);

        return true;
    } catch (e) {
        logError('Emoji Mapping', '✗ Emoji映射表加载失败');
        logError('Emoji Mapping', '错误类型:', e.name);
        logError('Emoji Mapping', '错误信息:', e.message);
        logError('Emoji Mapping', '错误堆栈:', e.stack);
        logError('Emoji Mapping', 'Emoji功能将无法正常工作');

        return false;
    }
}

// ==================== Telegram动态表情系统 ====================

// Telegram表情配置
const STICKER_CONFIG = {
    pageSize: 30,           // 每页显示30个表情
    currentPage: 0,         // 当前页码
    currentCategory: 'recent',  // 当前分类
    loadedGifs: new Set(),  // 已加载的GIF URL集合
    maxLoaded: 100,         // 内存池上限
    useDynamic: true,       // 是否使用动态表情（默认开启，显示WebP）
    categories: ['recent', 'smileys_emotion', 'people_body', 'animals_nature', 'food_drink', 'activity', 'objects', 'travel_places', 'symbols_flags']
};

// Telegram表情数据
let telegramStickerMapping = {};  // emoji → {file, category, size}
let stickersByCategory = {};       // category → [{emoji, file, category}]
let useTelegramStickers = false;   // 是否加载了Telegram表情

// 新增：静态Emoji数据（从60hz目录同步）
let staticEmojiCategories = {};    // category → [emoji, emoji, ...]
let dynamicEmojiList = [];          // 60hz目录中的所有动态emoji列表
let emojiCategoriesData = null;     // 从 emoji_categories.json 加载的分类数据

// Intersection Observer for lazy loading
let gifObserver = null;

// 检测性能等级
function detectPerformanceLevel() {
    const memory = navigator.deviceMemory || 4;
    const cores = navigator.hardwareConcurrency || 2;

    if (memory < 2 || cores < 2) {
        return 'low';
    } else if (memory < 4 || cores < 4) {
        return 'medium';
    } else {
        return 'high';
    }
}

// 加载Telegram表情映射表
async function loadTelegramStickers() {
    logDebug('Telegram Stickers', '========== 开始加载映射表 ==========');
    try {
        logDebug('Telegram Stickers', 'Fetching /static/telegram_stickers/mapping.json...');
        const response = await fetch('/static/telegram_stickers/mapping.json');
        logDebug('Telegram Stickers', '响应状态:', response.status, response.ok);
        if (!response.ok) {
            throw new Error('Mapping not found, status: ' + response.status);
        }

        telegramStickerMapping = await response.json();
        logInfo('Telegram Stickers', '✓ 映射表加载成功');
        logDebug('Telegram Stickers', '包含 emoji 数量:', Object.keys(telegramStickerMapping).length);
        logDebug('Telegram Stickers', '示例数据:', Object.entries(telegramStickerMapping).slice(0, 2));

        // 构建分类索引
        stickersByCategory = { recent: [] };
        for (let [emoji, data] of Object.entries(telegramStickerMapping)) {
            if (!stickersByCategory[data.category]) {
                stickersByCategory[data.category] = [];
            }
            stickersByCategory[data.category].push({
                emoji: emoji,
                ...data
            });
        }

        // 输出分类统计
        logDebug('Telegram Stickers', '✓ 分类索引构建完成');
        logDebug('Telegram Stickers', '可用分类:', Object.keys(stickersByCategory));
        for (let [cat, items] of Object.entries(stickersByCategory)) {
            if (cat !== 'recent') {  // recent 初始为空
                logDebug('Telegram Stickers', `  - ${cat}: ${items.length} 个表情`);
            }
        }

        // 从localStorage读取最近使用
        try {
            const recent = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]');
            stickersByCategory.recent = recent.slice(0, 20).map(emoji => ({
                emoji: emoji,
                ...(telegramStickerMapping[emoji] || {})
            })).filter(item => item.file);
        } catch (e) { }

        useTelegramStickers = true;
        logInfo('Telegram Stickers', '✓✓✓ GIF系统启用成功 ✓✓✓');
        logDebug('Telegram Stickers', 'useTelegramStickers =', useTelegramStickers);

        return true;
    } catch (e) {
        logWarn('Telegram Stickers', '✗✗✗ 加载失败，降级到PNG系统 ✗✗✗');
        logError('Telegram Stickers', '错误类型:', e.name);
        logError('Telegram Stickers', '错误信息:', e.message);
        logError('Telegram Stickers', '错误堆栈:', e.stack);
        useTelegramStickers = false;
        return false;
    }
}

// 新增：加载静态Emoji分类数据（从memoji分类表.txt解析）
async function loadEmojiCategories() {
    logDebug('Emoji Categories', '开始加载分类数据...');
    try {
        const response = await fetch('/static/emoji_categories.json');
        if (!response.ok) {
            logWarn('Emoji Categories', '分类数据不存在，使用默认分类');
            return false;
        }

        emojiCategoriesData = await response.json();
        logInfo('Emoji Categories', '✓ 分类数据加载成功');
        logDebug('Emoji Categories', '总分类数:', emojiCategoriesData.total_categories);
        logDebug('Emoji Categories', '总 Emoji 数:', emojiCategoriesData.total_emojis);

        // 构建静态分类索引
        staticEmojiCategories = {};
        emojiCategoriesData.categories.forEach(cat => {
            staticEmojiCategories[cat.id] = cat.emojis;
        });

        logDebug('Emoji Categories', '静态分类:', Object.keys(staticEmojiCategories));
        return true;
    } catch (e) {
        logError('Emoji Categories', '加载失败:', e.message);
        return false;
    }
}

// 新增：从60hz目录获取动态emoji列表（通过后端 API）
async function loadDynamicEmojiList() {
    logDebug('Dynamic Emoji', '开始加载60hz动态emoji列表...');
    try {
        // 如果有Telegram sticker mapping，直接从mapping中提取
        if (Object.keys(telegramStickerMapping).length > 0) {
            dynamicEmojiList = Object.keys(telegramStickerMapping);
            logInfo('Dynamic Emoji', '✓ 从telera sticker mapping提取到', dynamicEmojiList.length, '个动态emoji');
            return true;
        }

        logWarn('Dynamic Emoji', '未找到Telegram mapping，无法获取动态列表');
        return false;
    } catch (e) {
        logError('Dynamic Emoji', '加载失败:', e.message);
        return false;
    }
}

function initGifObserver() {
    if ('IntersectionObserver' in window) {
        gifObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src && !img.src) {
                        loadGif(img);
                    }
                }
            });
        }, {
            rootMargin: '50px',
            threshold: 0.01
        });
    }
}

// 加载单个GIF
function loadGif(img) {
    // 检查内存池
    if (STICKER_CONFIG.loadedGifs.size >= STICKER_CONFIG.maxLoaded) {
        unloadOldestGif();
    }

    const gifSrc = img.dataset.src;
    img.src = gifSrc;
    STICKER_CONFIG.loadedGifs.add(gifSrc);

    img.onload = () => {
        img.classList.add('loaded');
    };

    img.onerror = () => {
        // 降级到PNG
        const emoji = img.alt;
        const pngFile = emojiMapping[emoji];
        if (pngFile) {
            img.src = '/static/emoji/' + pngFile;
        } else {
            // 最终降级：显示字符
            img.style.display = 'none';
            img.parentElement.textContent = emoji;
        }
    };
}

// 卸载最旧的不可见GIF
function unloadOldestGif() {
    const imgs = document.querySelectorAll('.sticker-gif.loaded');
    for (let img of imgs) {
        const rect = img.getBoundingClientRect();
        // 如果GIF在视口外200px以上
        if (rect.top < -200 || rect.bottom > window.innerHeight + 200) {
            img.src = '';
            img.classList.remove('loaded');
            STICKER_CONFIG.loadedGifs.delete(img.dataset.src);
            break;
        }
    }
}

// 定期清理内存
setInterval(() => {
    if (STICKER_CONFIG.loadedGifs.size > STICKER_CONFIG.maxLoaded * 1.5) {
        const imgs = document.querySelectorAll('.sticker-gif.loaded');
        imgs.forEach(img => {
            const rect = img.getBoundingClientRect();
            if (rect.top < -300 || rect.bottom > window.innerHeight + 300) {
                img.src = '';
                img.classList.remove('loaded');
                STICKER_CONFIG.loadedGifs.delete(img.dataset.src);
            }
        });
    }
}, 30000);  // 每30秒清理一次

// ==================== 结束Telegram表情系统 ====================

function loadVisualSettings() {
    const v = localStorage.getItem('qq_visual_on');
    visualOn = (v === 'true');
    if (visualOn) { document.body.classList.add('visual-on'); document.getElementById('vis-toggle').classList.add('on'); }
    try { cache.pinned = JSON.parse(localStorage.getItem('qq_pinned') || '{}'); } catch (e) { cache.pinned = {}; }
}
function toggleVisual() {
    visualOn = !visualOn;
    if (visualOn) { document.body.classList.add('visual-on'); document.getElementById('vis-toggle').classList.add('on'); }
    else { document.body.classList.remove('visual-on'); document.getElementById('vis-toggle').classList.remove('on'); }
    localStorage.setItem('qq_visual_on', visualOn);
}

function showToast(msg) {
    var t = document.getElementById('toast');
    t.innerText = msg;
    t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 2000);
}

function getName(uid) {
    if (cache.remarks[uid]) return cache.remarks[uid];
    if (cache.users[uid]) return cache.users[uid].name;
    if (uid === 'system') return '系统通知';
    if (uid === me.uid) return me.name;
    return 'Unknown';
}

function backMobileList() {
    document.body.classList.remove('mobile-chat-active');
    target = null;
    updateListUI(); // 使用 updateListUI 替代 renderList

    // 隐藏移动端未读消息气泡
    var badge = document.getElementById('mobile-unread-badge');
    if (badge) {
        badge.classList.remove('show');
    }
}

const upPanel = document.getElementById('upload-panel'); const upHeader = document.getElementById('up-header');
let upX = 0, upY = 0, upDragging = false;
upHeader.onmousedown = (e) => { e.preventDefault(); upDragging = true; upX = e.clientX - upPanel.offsetLeft; upY = e.clientY - upPanel.offsetTop; document.addEventListener('mousemove', onUpMove); document.addEventListener('mouseup', onUpEnd); };
function onUpMove(e) { if (!upDragging) return; e.preventDefault(); let l = Math.max(0, Math.min(window.innerWidth - upPanel.offsetWidth, e.clientX - upX)); let t = Math.max(0, Math.min(window.innerHeight - upPanel.offsetHeight, e.clientY - upY)); upPanel.style.left = l + 'px'; upPanel.style.top = t + 'px'; upPanel.style.right = 'auto'; upPanel.style.bottom = 'auto'; }
function onUpEnd() { upDragging = false; document.removeEventListener('mousemove', onUpMove); document.removeEventListener('mouseup', onUpEnd); }

const appEl = document.getElementById('app');
appEl.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); };
appEl.ondrop = (e) => { e.preventDefault(); e.stopPropagation(); if (target && e.dataTransfer.files.length > 0) upFiles(e.dataTransfer.files); };
document.getElementById('inp-msg').addEventListener('paste', (e) => { if (e.clipboardData.files.length > 0) { e.preventDefault(); if (target) upFiles(e.clipboardData.files); } });

let lbScale = 1, lbX = 0, lbY = 0, lbDragging = false, lbStartX = 0, lbStartY = 0;
const lb = document.getElementById('lightbox'); const lbImg = document.getElementById('lightbox-img');
function viewImg(src) { lbImg.src = src; lbScale = 1; lbX = 0; lbY = 0; updateLbTransform(); lb.classList.add('active'); }
function closeLightbox() { lb.classList.remove('active'); }
function zoomImg(e) { e.preventDefault(); const delta = e.deltaY * -0.001; lbScale = Math.min(Math.max(0.5, lbScale + delta), 5); updateLbTransform(); }
function startDrag(e) { e.preventDefault(); lbDragging = true; lbStartX = e.clientX - lbX; lbStartY = e.clientY - lbY; lbImg.style.cursor = 'grabbing'; document.addEventListener('mousemove', onDragMove); document.addEventListener('mouseup', onDragEnd); }
function onDragMove(e) { if (!lbDragging) return; e.preventDefault(); lbX = e.clientX - lbStartX; lbY = e.clientY - lbStartY; updateLbTransform(); }
function onDragEnd() { lbDragging = false; lbImg.style.cursor = 'grab'; document.removeEventListener('mousemove', onDragMove); document.removeEventListener('mouseup', onDragEnd); }
function updateLbTransform() { lbImg.style.transform = 'translate(' + lbX + 'px, ' + lbY + 'px) scale(' + lbScale + ')'; }
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox(); });

document.getElementById('msg-box').addEventListener('scroll', () => {
    const box = document.getElementById('msg-box');
    const currentScrollTop = box.scrollTop;
    const isBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;

    const direction = currentScrollTop > lastScrollTop ? 'down' : 'up';
    lastScrollTop = currentScrollTop <= 0 ? 0 : currentScrollTop;

    updateFloatButton(isBottom, direction);

    if (isBottom && scrollUnreadCount > 0) {
        scrollUnreadCount = 0;
        updateFloatButton(isBottom, direction);
        markRead();
    }
    if (isBottom) markRead();
});

function updateFloatButton(isBottom, direction) {
    const btn = document.getElementById('unread-float');
    const txt = btn.querySelector('span');

    btn.className = 'unread-float show';

    if (scrollUnreadCount > 0) {
        btn.style.display = 'flex';
        txt.innerText = scrollUnreadCount > 99 ? '99+' : scrollUnreadCount;
        txt.style.display = 'block';
    } else {
        if (isBottom) {
            btn.style.display = 'none';
        } else {
            if (direction === 'down') {
                btn.style.display = 'flex';
                txt.style.display = 'none';
            } else if (direction === 'up') {
                btn.style.display = 'none';
            }
        }
    }
}

window.onload = async () => {
    setupContextMenu();
    setupScrollListener(); // 初始化滚动懒加载监听
    loadVisualSettings();
    await loadEmojiMapping(); // 加载emoji映射表
    initStickers();
    initCompactMode(); // 初始化窄屏优化
    initGifPauseControl(); // 初始化GIF暂停控制
    initP2PManager(); // 初始化P2P传输管理器
    const storedUid = localStorage.getItem('qq_uid');
    if (storedUid) {
        try {
            const r = await fetch('/get_user_info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid: storedUid }) });

            // **安全控制：检查会话状态**
            if (r.status === 403) {
                const errData = await r.json();
                if (errData.error === 'session_invalidated') {
                    alert(errData.message || '您的账户已被禁用，请重新登录');
                    localStorage.removeItem('qq_uid');
                    document.getElementById('md-login').style.display = 'flex';
                    return;
                }
            }

            if (r.ok) {
                me = await r.json();
                document.getElementById('md-login').style.display = 'none'; document.getElementById('app').style.opacity = '1';
                upMe();
                startPolling();

                // 尝试恢复上次的会话状态
                var targetChat = null;
                try {
                    var savedChat = localStorage.getItem('qq_current_chat');
                    if (savedChat) {
                        targetChat = JSON.parse(savedChat);
                    }
                } catch (e) {
                    logWarn('Session', '读取保存的会话状态失败:', e);
                }

                // 等待第一次 sync 完成后再决定打开哪个聊天
                setTimeout(() => {
                    var chatToOpen = null;

                    if (targetChat) {
                        // 验证保存的会话是否仍然有效
                        if (targetChat.type === 'group') {
                            // 检查群聊是否存在
                            if (cache.groups[targetChat.id]) {
                                chatToOpen = targetChat;
                            }
                        } else if (targetChat.type === 'private') {
                            // 检查私聊用户是否存在
                            if (cache.users[targetChat.id]) {
                                chatToOpen = targetChat;
                            }
                        }
                    }

                    // 如果没有有效的保存会话，默认进入主群聊
                    if (!chatToOpen) {
                        chatToOpen = { id: 'group_global', type: 'group', name: '全员交流群' };
                    }

                    switchChat(chatToOpen.id, chatToOpen.type, chatToOpen.name);
                }, 500); // 等待500ms确保 sync有足够时间加载数据

                return;
            }
        } catch (e) { }
        localStorage.removeItem('qq_uid');
    }
    document.getElementById('md-login').style.display = 'flex';
};

function renderStickers() {
    logDebug('Render', '==================== 开始渲染表情面板 ====================');
    logDebug('Render', '当前分类:', STICKER_CONFIG.currentCategory);
    logDebug('Render', '当前页码:', STICKER_CONFIG.currentPage);
    logDebug('Render', '动态模式:', STICKER_CONFIG.useDynamic);

    const p = document.getElementById('sticker-content');
    const category = STICKER_CONFIG.currentCategory;
    const page = STICKER_CONFIG.currentPage;
    const useDynamic = STICKER_CONFIG.useDynamic;

    // 获取当前分类的表情列表
    let list = [];

    if (category === 'recent') {
        // 最近使用（动静态共享）
        logDebug('Render', '处理"最近使用"分类...');
        try {
            const recents = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]');
            list = recents.slice(0, 20).map(emoji => ({ emoji: emoji }));
            logDebug('Render', '最近使用包含', list.length, '个表情');
        } catch (e) {
            logWarn('Render', '读取最近使用失败:', e.message);
        }
    } else if (useDynamic) {
        // 动态模式：使用 60hz WebP 资源
        logDebug('Render', '★★★ 动态模式启用 ★★★');

        if (staticEmojiCategories[category]) {
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
            logDebug('Render', '使用分类数据:', category, '包含', list.length, '个');
        } else if (useTelegramStickers && stickersByCategory[category]) {
            list = stickersByCategory[category];
            logDebug('Render', '降级到Telegram分类:', list.length, '个');
        } else if (dynamicEmojiList.length > 0) {
            list = dynamicEmojiList.map(emoji => ({ emoji: emoji }));
            logDebug('Render', '使用全部动态列表:', list.length, '个');
        } else {
            // 最终降级：使用 emojiMapping 中的所有 emoji
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
            logDebug('Render', '降级到emojiMapping:', list.length, '个');
        }
    } else {
        // 静态模式：使用静态 PNG 资源
        logDebug('Render', '◆◆◆ 静态模式启用 ◆◆◆');

        if (staticEmojiCategories[category]) {
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
            logDebug('Render', '使用静态分类:', category, '包含', list.length, '个');
        } else {
            // 降级：使用 emojiMapping 中的所有 emoji
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
            logDebug('Render', '降级到emojiMapping:', list.length, '个');
        }
    }

    // 分页计算
    const pageSize = STICKER_CONFIG.pageSize;
    const totalPages = Math.ceil(list.length / pageSize);
    const start = page * pageSize;
    const end = Math.min(start + pageSize, list.length);
    const pageItems = list.slice(start, end);

    // 渲染表情
    let h = '';
    let gifCount = 0, pngCount = 0, unicodeCount = 0;

    pageItems.forEach(item => {
        const emoji = item.emoji;

        if (useDynamic) {
            // 动态模式：优先显示 WebP
            const gifData = telegramStickerMapping[emoji];
            if (gifData && gifData.file) {
                h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', true)"><img class="sticker-gif" data-src="/static/telegram_stickers/' + gifData.file + '" alt="' + emoji + '"></div>';
                gifCount++;
            } else if (emojiMapping[emoji]) {
                // 降级到PNG
                h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)">' + emojiToImg(emoji) + '</div>';
                pngCount++;
            } else {
                // 最终降级：显示Unicode字符
                h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', true)"><span style="font-size:28px">' + emoji + '</span></div>';
                unicodeCount++;
            }
        } else {
            // 静态模式：优先显示 PNG
            if (emojiMapping[emoji]) {
                h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)">' + emojiToImg(emoji) + '</div>';
                pngCount++;
            } else {
                h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)"><span style="font-size:28px">' + emoji + '</span></div>';
                unicodeCount++;
            }
        }
    });

    logDebug('Render', '渲染完成 - 本页共', pageItems.length, '个表情');
    logDebug('Render', '  - GIF:', gifCount, '个');
    logDebug('Render', '  - PNG:', pngCount, '个');
    logDebug('Render', '  - Unicode:', unicodeCount, '个');

    p.innerHTML = h;

    // 更新分页信息
    document.getElementById('sticker-page-info').innerText = (page + 1) + ' / ' + Math.max(1, totalPages);
    document.getElementById('sticker-prev').disabled = (page === 0);
    document.getElementById('sticker-next').disabled = (page >= totalPages - 1);

    // 启动懒加载观察（仅动态模式）
    if (useDynamic && gifObserver) {
        const gifImages = p.querySelectorAll('.sticker-gif');
        logDebug('Render', '✓ 启动GIF懒加载，观察', gifImages.length, '个GIF元素');
        gifImages.forEach(img => {
            gifObserver.observe(img);
        });
    }

    logDebug('Render', '==================== 渲染完成 ====================');
}

function switchStickerCategory(cat) {
    STICKER_CONFIG.currentCategory = cat;
    STICKER_CONFIG.currentPage = 0;

    // 更新分类标签样式
    document.querySelectorAll('.sticker-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    const activeTab = document.querySelector('.sticker-tab[data-category="' + cat + '"]');
    if (activeTab) {
        activeTab.classList.add('active');
    }

    renderStickers();

    // 平滑滚动到激活的分类标签
    if (activeTab) {
        const tabsContainer = document.querySelector('.sticker-tabs');
        const tabOffsetLeft = activeTab.offsetLeft;
        const tabWidth = activeTab.offsetWidth;
        const containerWidth = tabsContainer.offsetWidth;
        const scrollLeft = tabOffsetLeft - (containerWidth - tabWidth) / 2;

        // 使用平滑滚动
        tabsContainer.scrollTo({
            left: scrollLeft,
            behavior: 'smooth'
        });
    }

    // 更新进度条
    setTimeout(updateStickerTabsScrollbar, 50);
}

function stickerPagePrev() {
    const category = STICKER_CONFIG.currentCategory;
    let list = [];

    // 根据当前模式和分类获取正确的表情列表（与renderStickers函数保持一致）
    if (category === 'recent') {
        // 最近使用（动静态共享）
        try {
            const recents = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]');
            list = recents.slice(0, 20).map(emoji => ({ emoji: emoji }));
        } catch (e) { }
    } else if (useTelegramStickers) {
        // 动态模式：使用 60hz WebP 资源
        if (staticEmojiCategories[category]) {
            // 使用分类数据过滤
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
        } else if (stickersByCategory[category]) {
            // 降级：使用Telegram分类数据
            list = stickersByCategory[category];
        } else if (dynamicEmojiList.length > 0) {
            // 再次降级：全部动态emoji
            list = dynamicEmojiList.map(emoji => ({ emoji: emoji }));
        } else {
            // 最终降级：使用 emojiMapping
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
        }
    } else {
        // 静态模式：使用静态 PNG 资源
        if (staticEmojiCategories[category]) {
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
        } else {
            // 降级：使用 emojiMapping
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
        }
    }

    const totalPages = Math.ceil(list.length / STICKER_CONFIG.pageSize);

    if (STICKER_CONFIG.currentPage > 0) {
        STICKER_CONFIG.currentPage--;
        renderStickers();
    }
}

function stickerPageNext() {
    const category = STICKER_CONFIG.currentCategory;
    let list = [];

    // 根据当前模式和分类获取正确的表情列表（与renderStickers函数保持一致）
    if (category === 'recent') {
        // 最近使用（动静态共享）
        try {
            const recents = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]');
            list = recents.slice(0, 20).map(emoji => ({ emoji: emoji }));
        } catch (e) { }
    } else if (useTelegramStickers) {
        // 动态模式：使用 60hz WebP 资源
        if (staticEmojiCategories[category]) {
            // 使用分类数据过滤
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
        } else if (stickersByCategory[category]) {
            // 降级：使用Telegram分类数据
            list = stickersByCategory[category];
        } else if (dynamicEmojiList.length > 0) {
            // 再次降级：全部动态emoji
            list = dynamicEmojiList.map(emoji => ({ emoji: emoji }));
        } else {
            // 最终降级：使用 emojiMapping
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
        }
    } else {
        // 静态模式：使用静态 PNG 资源
        if (staticEmojiCategories[category]) {
            list = staticEmojiCategories[category].map(emoji => ({ emoji: emoji }));
        } else {
            // 降级：使用 emojiMapping
            list = Object.keys(emojiMapping).map(emoji => ({ emoji: emoji }));
        }
    }

    const totalPages = Math.ceil(list.length / STICKER_CONFIG.pageSize);

    if (STICKER_CONFIG.currentPage < totalPages - 1) {
        STICKER_CONFIG.currentPage++;
        renderStickers();
    }
}

async function initStickers() {
    logDebug('Init', '╔════════════════════════════════════════════════════╗');
    logDebug('Init', '║     初始化表情系统                                  ║');
    logDebug('Init', '╚════════════════════════════════════════════════════╝');

    // 检查emojiMapping状态
    logDebug('Init', '步骤0: 检查emojiMapping加载状态...');
    logDebug('Init', 'emojiMapping类型:', typeof emojiMapping);
    logDebug('Init', 'emojiMapping大小:', Object.keys(emojiMapping).length);
    logDebug('Init', 'emojiMapping示例:', Object.entries(emojiMapping).slice(0, 2));

    // 步骤1: 加载Telegram表情映射（动态资源）
    logDebug('Init', '步骤1: 加载Telegram表情映射...');
    const loaded = await loadTelegramStickers();
    logDebug('Init', '步骤1 结果:', loaded ? '成功' : '失败');

    // 步骤1.5: 加载动态emoji列表
    logDebug('Init', '步骤1.5: 加载动态emoji列表...');
    await loadDynamicEmojiList();

    // 步骤1.6: 加载静态分类数据
    logDebug('Init', '步骤1.6: 加载静态分类数据...');
    await loadEmojiCategories();

    // 步骤2: 初始化GIF懒加载
    logDebug('Init', '步骤2: 初始化GIF懒加载Observer...');
    initGifObserver();
    logDebug('Init', '步骤2 完成');

    // 步骤3: 渲染表情面板
    logDebug('Init', '步骤3: 首次渲染表情面板...');
    renderStickers();

    // 步骤4: 同步 Toggle 开关的视觉状态
    logDebug('Init', '步骤4: 同步Toggle开关状态...');
    const toggle = document.getElementById('dynamic-emoji-toggle');
    const toggleContainer = toggle.parentElement;

    // 如果没有加载到动态表情，隐藏整个开关容器
    if (!loaded || !useTelegramStickers) {
        toggleContainer.style.display = 'none';
        logInfo('Init', 'Toggle开关: 已隐藏（无动态资源）');
    } else {
        toggleContainer.style.display = 'flex';
        if (STICKER_CONFIG.useDynamic) {
            toggle.classList.add('on');
            logDebug('Init', 'Toggle开关: 已设置为开启状态');
        } else {
            toggle.classList.remove('on');
            logDebug('Init', 'Toggle开关: 已设置为关闭状态');
        }
    }

    logInfo('Init', '========== 初始化完成 ==========');

    // 窗口大小改变时调整面板位置
    function adjustStickerPanelPosition() {
        const panel = document.getElementById('sticker-panel');
        if (panel && panel.style.display === 'flex') {
            const panelRect = panel.getBoundingClientRect();
            const viewportWidth = window.innerWidth;

            // 如果面板右侧超出视口，调整其位置
            if (panelRect.right > viewportWidth) {
                const overflow = panelRect.right - viewportWidth;
                const currentLeft = parseInt(panel.style.left) || 20;
                const newLeft = Math.max(10, currentLeft - overflow);
                panel.style.left = newLeft + 'px';
            }

            // 确保面板左侧不会超出视口左侧
            if (panelRect.left < 0) {
                panel.style.left = '10px';
            }
        }
    }

    // 监听窗口大小改变事件
    window.addEventListener('resize', adjustStickerPanelPosition);

    // 点击外部关闭面板
    document.addEventListener('click', function (e) {
        if (!e.target.closest('#sticker-panel') && !e.target.closest('.btn-icon')) {
            document.getElementById('sticker-panel').style.display = 'none';
        }
    });

    // 分页按钮事件
    document.getElementById('sticker-prev').addEventListener('click', (e) => {
        e.stopPropagation();
        stickerPagePrev();
    });
    document.getElementById('sticker-next').addEventListener('click', (e) => {
        e.stopPropagation();
        stickerPageNext();
    });

    // 分类标签事件
    document.querySelectorAll('.sticker-tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.stopPropagation();
            const cat = tab.dataset.category;
            switchStickerCategory(cat);
        });
    });

    // 监听分类标签容器的滚动事件，更新进度条
    const tabsContainer = document.querySelector('.sticker-tabs');
    if (tabsContainer) {
        // 使用节流来优化滚动事件处理
        let ticking = false;
        const onScroll = function () {
            if (!ticking) {
                requestAnimationFrame(function () {
                    updateStickerTabsScrollbar();
                    ticking = false;
                });
                ticking = true;
            }
        };

        tabsContainer.addEventListener('scroll', onScroll);

        // 添加鼠标滚轮支持水平滚动，带平滑效果
        let scrollTimeout;
        tabsContainer.addEventListener('wheel', function (e) {
            if (e.deltaY !== 0) {
                e.preventDefault();
                // 增加滑动距离，原来是e.deltaY，现在乘以2增加滑动距离
                const scrollDistance = e.deltaY * 2;
                // 使用平滑滚动
                tabsContainer.scrollBy({
                    left: scrollDistance,
                    behavior: 'smooth'
                });

                // 更新进度条
                clearTimeout(scrollTimeout);
                scrollTimeout = setTimeout(updateStickerTabsScrollbar, 100);
            }
        }, { passive: false });
    }

    // 初始化滑动进度条
    setTimeout(initStickerTabsScrollbar, 100);

}

// 更新滑动进度条
function updateStickerTabsScrollbar() {
    const tabsContainer = document.querySelector('.sticker-tabs');
    const scrollbar = document.querySelector('.sticker-tabs-scrollbar');
    const scrollbarThumb = document.querySelector('.sticker-tabs-scrollbar-thumb');

    if (!tabsContainer || !scrollbar || !scrollbarThumb) return;

    const scrollWidth = tabsContainer.scrollWidth;
    const clientWidth = tabsContainer.clientWidth;

    if (scrollWidth <= clientWidth) {
        scrollbar.style.display = 'none';
        return;
    }

    scrollbar.style.display = 'block';
    const scrollRatio = clientWidth / scrollWidth;
    const thumbWidth = Math.max(scrollRatio * clientWidth, 20); // 最小宽度20px
    const scrollPercent = tabsContainer.scrollLeft / (scrollWidth - clientWidth);
    const thumbPosition = scrollPercent * (clientWidth - thumbWidth);

    scrollbarThumb.style.width = thumbWidth + 'px';
    scrollbarThumb.style.left = thumbPosition + 'px';
}

// 初始化滑动进度条
function initStickerTabsScrollbar() {
    const tabsContainer = document.querySelector('.sticker-tabs');
    const scrollbar = document.querySelector('.sticker-tabs-scrollbar');
    const scrollbarThumb = document.querySelector('.sticker-tabs-scrollbar-thumb');

    if (!tabsContainer || !scrollbar || !scrollbarThumb) return;

    // 更新滚动条
    function updateScrollbar() {
        updateStickerTabsScrollbar();
    }

    // 监听滚动事件
    tabsContainer.addEventListener('scroll', updateScrollbar);

    // 监听窗口大小变化
    window.addEventListener('resize', updateScrollbar);

    // 初始更新
    setTimeout(updateScrollbar, 100); // 延迟更新以确保DOM渲染完成
}



// 切换动静态表情模式
function toggleDynamicEmoji() {
    STICKER_CONFIG.useDynamic = !STICKER_CONFIG.useDynamic;
    const toggle = document.getElementById('dynamic-emoji-toggle');

    if (STICKER_CONFIG.useDynamic) {
        toggle.classList.add('on');
        logDebug('Toggle', '✓ 已切换到动态模式');
    } else {
        toggle.classList.remove('on');
        logDebug('Toggle', '✓ 已切换到静态模式');
    }

    // 保持当前页码并重新渲染（不重置页码）
    // STICKER_CONFIG.currentPage = 0;  // 移除此行以保持当前页码
    renderStickers();
}

function toggleSticker() {
    const p = document.getElementById('sticker-panel');
    if (p.style.display === 'flex') p.style.display = 'none';
    else {
        p.style.display = 'flex';
        // 调整面板位置以确保在视口内
        adjustStickerPanelPosition();
        renderStickers();
    }
}

async function sendSticker(content, isDynamic) {
    if (!target) return;
    document.getElementById('sticker-panel').style.display = 'none';

    // 更新最近使用
    let recents = [];
    try { recents = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]'); } catch (e) { }
    recents = recents.filter(x => x !== content);
    recents.unshift(content);
    if (recents.length > 10) recents = recents.slice(0, 10);
    localStorage.setItem('qq_recent_stickers', JSON.stringify(recents));
    renderStickers();

    // 发送消息（动静态分离发送）
    // 修复：添加随机数确保临时ID唯一，避免快速连续发送时ID冲突
    var tmpId = Date.now() * 10000 + Math.floor(Math.random() * 10000);
    var msgType = isDynamic ? 'sticker' : 'text';  // 动态用sticker，静态用text
    var localMsg = {
        id: tmpId,
        from_uid: me.uid,
        to_uid: target.id,
        type: msgType,
        content: content,
        timestamp: Date.now() / 1000,  // 修复：使用秒级时间戳，与服务器保持一致
        tmp: true,
        quote: null
    };

    currentChatMsgs.push(localMsg);
    // 修复：使用renderNewMessages而不是renderChat，避免重复渲染
    renderNewMessages();
    scrollToBottomRobust();

    await fetch('/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            uid: me.uid,
            to_uid: target.id,
            content: content,
            type: msgType
        })
    });

    if (pollingTimer) clearTimeout(pollingTimer);
    sync();
}

async function doLogin() {
    const n = document.getElementById('inp-nick').value.trim(); const p = document.getElementById('inp-pwd').value.trim();
    if (!n || !p) return alert('请输入昵称和密码');
    try {
        const r = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nickname: n, password: p }) });
        if (!r.ok) { const err = await r.json(); throw new Error(err.error || '登录失败'); }
        me = await r.json(); localStorage.setItem('qq_uid', me.uid);
        document.getElementById('md-login').style.display = 'none'; document.getElementById('app').style.opacity = '1';
        upMe();
        startPolling();

        // 登录后等待数据加载，然后进入默认聊天（主群聊）
        setTimeout(() => {
            switchChat('group_global', 'group', '全员交流群');
        }, 500);
    } catch (e) { alert(e.message); }
}
function doLogout() { if (confirm('确定要退出登录吗？')) { localStorage.removeItem('qq_uid'); location.reload(); } }

function startPolling() { if (pollingTimer) clearTimeout(pollingTimer); sync(); }

// ==================== 类型安全工具函数 ====================
/**
 * 安全的 BigInt 转换函数（Semgrep 规则：防止类型强制转换漏洞）
 * Context7 最佳实践：JavaScript 处理大整数 ID 时必须使用 BigInt 类型
 * @param {*} value - 任意值
 * @returns {BigInt} BigInt 值
 */
function safeBigInt(value) {
    if (typeof value === 'bigint') return value;
    if (typeof value === 'number') return BigInt(Math.floor(value));
    if (typeof value === 'string') {
        // 移除非数字字符（防御性编程）
        var cleaned = value.replace(/[^0-9]/g, '');
        if (cleaned === '') return BigInt(0);
        return BigInt(cleaned);
    }
    // 其他类型默认返回 0
    return BigInt(0);
}

/**
 * 安全的 ID 比较函数（解决 String vs Integer 类型不一致问题）
 * Semgrep 安全规则：禁止直接使用 > < 比较混合类型的 ID
 * @param {*} id1 - ID 1
 * @param {*} id2 - ID 2
 * @returns {number} -1(id1<id2), 0(相等), 1(id1>id2)
 */
function compareIds(id1, id2) {
    var big1 = safeBigInt(id1);
    var big2 = safeBigInt(id2);
    if (big1 < big2) return -1;
    if (big1 > big2) return 1;
    return 0;
}

/**
 * 检查消息是否属于指定的聊天
 * SQLite 修复：统一转换为 String 进行比较，避免 Integer vs String 类型不匹配
 * @param {Object} m - 消息对象
 * @param {Object} chatTarget - 聊天目标 {id, type}
 * @returns {boolean}
 */
function isMsgBelongsToChat(m, chatTarget) {
    if (!m || !chatTarget) return false;

    // 统一转换为 String 进行比较，避免 SQLite Integer vs JS String 类型不匹配
    var mFromUid = String(m.from_uid || '');
    var mToUid = String(m.to_uid || '');
    var targetId = String(chatTarget.id || '');
    var myUid = String(me.uid || '');

    if (chatTarget.type === 'group') {
        // 群聊：消息的 to_uid 等于群ID
        return mToUid === targetId;
    } else {
        // 私聊
        if (targetId === myUid) {
            // 与自己聊天
            return mFromUid === myUid && mToUid === myUid;
        } else {
            // 普通私聊：我发给对方 或 对方发给我
            return (mFromUid === myUid && mToUid === targetId) ||
                (mFromUid === targetId && mToUid === myUid);
        }
    }
}

/**
 * 更新侧边栏预览数据（重构版）
 * 当收到新消息时，更新预览信息并委托 UnreadManager 处理未读计数
 * @param {Object} m - 消息对象
 */
function updateSidebarPreview(m) {
    if (!m) return;

    const preview = formatMsgPreview(m);
    const timestamp = m.timestamp;
    const fromName = getName(m.from_uid);

    // 确定这条消息属于哪个聊天
    if (cache.groups[m.to_uid]) {
        // 群聊消息
        const gid = m.to_uid;
        if (!cache.groups[gid]._sidebar) cache.groups[gid]._sidebar = { unreadCount: 0 };
        cache.groups[gid]._sidebar.lastMsgPreview = fromName + ': ' + preview;
        cache.groups[gid]._sidebar.lastMsgTime = timestamp;
        cache.groups[gid]._sidebar.lastMsgId = String(m.id);
        cache.groups[gid]._sidebar.lastMsgFromUid = String(m.from_uid);
    } else {
        // 私聊消息
        let chatPartnerId = null;
        if (String(m.from_uid) === String(me.uid)) {
            // 我发的消息
            chatPartnerId = m.to_uid;
        } else if (String(m.to_uid) === String(me.uid)) {
            // 发给我的消息
            chatPartnerId = m.from_uid;
        }

        if (chatPartnerId && cache.users[chatPartnerId]) {
            if (!cache.users[chatPartnerId]._sidebar) cache.users[chatPartnerId]._sidebar = { unreadCount: 0 };
            cache.users[chatPartnerId]._sidebar.lastMsgPreview = preview;
            cache.users[chatPartnerId]._sidebar.lastMsgTime = timestamp;
            cache.users[chatPartnerId]._sidebar.lastMsgId = String(m.id);
            cache.users[chatPartnerId]._sidebar.lastMsgFromUid = String(m.from_uid);
        }
    }

    // 委托 UnreadManager 处理未读计数逻辑
    UnreadManager.onNewMessage(m);
}

/**
 * 格式化消息预览文本
 */
function formatMsgPreview(m) {
    if (m.type === 'system') return '[系统消息]';
    if (m.is_recalled) return '[已撤回]';
    if (m.content && m.content.startsWith('{"type":"merge_fwd"')) return '[聊天记录]';
    if (m.type === 'sticker') return '[表情]';
    if (m.type === 'file') return '[文件]';
    return m.content || '';
}

// ==================== 统一的消息更新框架 ====================

/**
 * 统一的消息 DOM 更新函数
 * 偱守规范：所有消息变更必须通过此函数处理，确保变更后立即同步到DOM
 * @param {number} msgId - 消息 ID
 * @param {Object} newData - 新的消息数据（可为空，仅刷新 DOM）
 * @param {boolean} forceRender - 是否强制重新渲染
 * @returns {boolean} 是否成功更新
 */
function updateMessageInDOM(msgId, newData, forceRender) {
    // 查找本地消息 - SQLite 修复：使用安全 ID 比较
    var localIdx = findMsgIndexById(currentChatMsgs, msgId);
    var localMsg = localIdx !== -1 ? currentChatMsgs[localIdx] : null;

    // 如果提供了新数据，更新本地消息
    if (newData && localIdx !== -1) {
        currentChatMsgs[localIdx] = newData;
        localMsg = newData;
    }

    if (!localMsg) return false;

    // 查找 DOM 元素 - 类型安全：确保 ID 为 String
    var el = document.getElementById('msg-' + safeId(msgId));
    if (!el) return false;

    // 生成新的 DOM 元素
    var newEl;
    if (localMsg.type === 'system' || localMsg.is_recalled) {
        newEl = renderSystemMsg(localMsg);
    } else {
        newEl = renderMessageElement(localMsg, false);
    }

    if (newEl) {
        // 替换 DOM 元素
        el.outerHTML = newEl.outerHTML;
        return true;
    }
    return false;
}

/**
 * 检测消息是否需要更新
 * @param {Object} oldMsg - 旧消息数据
 * @param {Object} newMsg - 新消息数据
 * @returns {boolean} 是否需要更新
 */
function shouldUpdateMessage(oldMsg, newMsg) {
    if (!oldMsg || !newMsg) return true;

    // 检测关键属性变化
    return (
        oldMsg.is_recalled !== newMsg.is_recalled ||      // 撤回状态
        oldMsg.content !== newMsg.content ||              // 内容变化
        oldMsg.type !== newMsg.type ||                    // 类型变化
        oldMsg.server_filename !== newMsg.server_filename || // 文件名变化
        oldMsg.is_img !== newMsg.is_img ||                // 图片状态变化
        oldMsg.filename !== newMsg.filename ||            // 文件名变化
        JSON.stringify(oldMsg.quote) !== JSON.stringify(newMsg.quote) // 引用变化
    );
}

/**
 * 处理消息撤回 - 统一更新数据和 DOM
 * SQLite 修复：统一使用 String 类型进行比较，避免 Integer vs String 类型不匹配
 * @param {number|string} msgId - 被撤回的消息 ID
 */
function handleMessageRecall(msgId) {
    // SQLite 修复：统一转换为 String 进行比较
    var targetId = String(msgId);

    // 更新本地消息数据
    var localIdx = currentChatMsgs.findIndex(function (m) {
        return String(m.id) === targetId;
    });
    if (localIdx !== -1) {
        currentChatMsgs[localIdx].is_recalled = true;
    }

    // 更新 DOM
    var el = document.getElementById('msg-' + targetId);
    if (el && !el.classList.contains('sys')) {
        var localMsg = localIdx !== -1 ? currentChatMsgs[localIdx] : { id: msgId, is_recalled: true };
        var newEl = renderSystemMsg(localMsg);
        if (newEl) {
            el.outerHTML = newEl.outerHTML;
        }
    }

    // 更新引用了该消息的其他消息
    currentChatMsgs.forEach(function (m) {
        // SQLite 修复：引用消息的 ID 也需要统一转换为 String 比较
        if (m.quote && String(m.quote.id) === targetId) {
            m.quote.is_recalled = true;
            var qEl = document.querySelector('#msg-' + String(m.id) + ' .quote-box');
            if (qEl) {
                qEl.innerHTML = '<div class="q-txt quote-recalled">原消息已被撤回</div>';
                qEl.onclick = null;
            }
        }
    });

    // 更新侧边栏预览
    updateListUI();
}

async function sync() {
    try {
        // ============ 版本控制：构建带版本信息的请求 URL ============
        var syncUrl = '/sync?uid=' + me.uid + '&last_msg_id=' + lastId;

        // 添加版本信息参数（用于检测用户/群组信息变更）
        if (Object.keys(userVersions).length > 0) {
            syncUrl += '&user_version=' + encodeURIComponent(JSON.stringify(userVersions));
        }
        if (Object.keys(groupVersions).length > 0) {
            syncUrl += '&group_version=' + encodeURIComponent(JSON.stringify(groupVersions));
        }
        // 添加客户端群组列表（用于检测被踢/解散）
        var clientGroups = Object.keys(cache.groups);
        if (clientGroups.length > 0) {
            syncUrl += '&client_groups=' + encodeURIComponent(JSON.stringify(clientGroups));
        }

        const r = await fetch(syncUrl);

        // **安全控制：检查会话状态**
        if (r.status === 403) {
            const errData = await r.json();
            if (errData.error === 'session_invalidated') {
                // 会话已失效，强制退出登录
                if (pollingTimer) clearTimeout(pollingTimer);
                alert(errData.message || '您的账户已被禁用，请重新登录');
                localStorage.removeItem('qq_uid');
                location.reload();
                return;
            }
        }

        const d = await r.json();

        // ============ 版本控制：处理被踢出的群组 ============
        if (d.kicked_from_groups && d.kicked_from_groups.length > 0) {
            d.kicked_from_groups.forEach(function (gid) {
                // 从缓存中移除
                delete cache.groups[gid];
                delete groupVersions[gid];
                // 如果当前正在该群，强制退出
                if (target && target.id === gid) {
                    target = null;
                    currentChatMsgs = [];
                    document.getElementById('chat-t').innerText = '您已被移出群聊';
                    document.getElementById('input-area').style.display = 'none';
                    document.getElementById('btn-grp-set').style.display = 'none';
                    document.getElementById('msg-box').innerHTML = '<div class="empty-chat">您已被移出此群组</div>';
                }
            });
        }

        // ============ 版本控制：处理已解散的群组 ============
        if (d.deleted_groups && d.deleted_groups.length > 0) {
            d.deleted_groups.forEach(function (gid) {
                delete cache.groups[gid];
                delete groupVersions[gid];
                if (target && target.id === gid) {
                    target = null;
                    currentChatMsgs = [];
                    document.getElementById('chat-t').innerText = '群组已解散';
                    document.getElementById('input-area').style.display = 'none';
                    document.getElementById('btn-grp-set').style.display = 'none';
                    document.getElementById('msg-box').innerHTML = '<div class="empty-chat">该群组已解散</div>';
                }
            });
        }

        // ============ 版本控制：处理用户信息变更 ============
        if (d.changed_users) {
            for (var uid in d.changed_users) {
                var changedUser = d.changed_users[uid];

                // 修复"幽灵用户"漏洞：处理被删除用户
                if (changedUser.deleted) {
                    // 用户已被注销，更新缓存标记
                    if (cache.users[uid]) {
                        cache.users[uid].name = changedUser.name + ' (已注销)';
                        cache.users[uid].avatar_bg = '#999';  // 使用灰色头像表示已注销
                        cache.users[uid].status = 'offline';   // 标记为离线
                        cache.users[uid].deleted = true;       // 标记删除状态
                    }
                    // 如果当前正在与该用户私聊，强制退出并提示
                    if (target && target.type === 'private' && target.id === uid) {
                        target = null;
                        currentChatMsgs = [];
                        document.getElementById('chat-t').innerText = '用户已注销';
                        document.getElementById('input-area').style.display = 'none';
                        document.getElementById('msg-box').innerHTML = '<div class="empty-chat">该用户已被注销</div>';
                        showToast('该用户已被管理员注销');
                    }
                } else {
                    // 正常更新用户信息
                    if (cache.users[uid]) {
                        cache.users[uid].name = changedUser.name;
                        cache.users[uid].avatar_bg = changedUser.avatar_bg;
                    }
                    // 如果当前正在与该用户私聊，更新标题栏
                    if (target && target.type === 'private' && target.id === uid) {
                        document.getElementById('chat-t').innerText = getName(uid);
                    }
                    // 关键修复：如果当前聊天界面涉及该用户，立即刷新聊天消息中的用户信息
                    if (target) {
                        var needsRefresh = false;
                        // 检查是否是私聊对象
                        if (target.type === 'private' && target.id === uid) {
                            needsRefresh = true;
                        }
                        // 检查是否是群聊中的成员（当前聊天中可能有该用户发送的消息）
                        if (target.type === 'group') {
                            // 检查 currentChatMsgs 中是否有该用户的消息
                            for (var i = 0; i < currentChatMsgs.length; i++) {
                                if (currentChatMsgs[i].from_uid === uid) {
                                    needsRefresh = true;
                                    break;
                                }
                            }
                        }
                        // 如果需要刷新，重新渲染聊天界面（不滚动）
                        // 修复：如果刚发送消息，不要立即重新渲染，避免删除刚创建的时间戳元素
                        if (needsRefresh && !preventRenderChat) {
                            renderChat(false, false);
                        }
                    }
                }

                // 更新版本号
                userVersions[uid] = changedUser.version || 0;
            }

            // 刷新侧边栏，移除已注销用户或更新显示
            updateListUI();
            updateContactUI();
        }

        // ============ 版本控制：处理群组信息变更 ============
        if (d.changed_groups) {
            for (var gid in d.changed_groups) {
                var changedGroup = d.changed_groups[gid];
                if (cache.groups[gid]) {
                    // 更新缓存中的群组信息
                    cache.groups[gid].name = changedGroup.name;
                    cache.groups[gid].members = changedGroup.members;
                    cache.groups[gid].owner = changedGroup.owner;
                } else {
                    // 新加入的群组
                    cache.groups[gid] = changedGroup;
                }
                // 更新版本号
                groupVersions[gid] = changedGroup.version || 0;

                // 如果当前正在该群，更新标题栏
                if (target && target.type === 'group' && target.id === gid) {
                    document.getElementById('chat-t').innerText = changedGroup.name;
                }
            }
        }

        // ============ 记录服务端返回的最新同步点（但不立即更新 lastId）============
        // SQLite 修复：确保 last_synced_id 是数字类型
        var serverSyncedId = Number(d.last_synced_id) || 0;
        var newLastId = lastId;  // 用于追踪本次同步后的最大消息ID

        // ============ 合并用户数据，保留 _sidebar 信息 ============
        // 关键修复：unreadCount 由 UnreadManager 统一管理，不被服务端覆盖
        for (var uid in d.users) {
            if (!cache.users[uid]) {
                cache.users[uid] = d.users[uid];
            } else {
                // 保留已有的 _sidebar 信息
                var existingSidebar = cache.users[uid]._sidebar;
                var serverSidebar = d.users[uid]._sidebar;
                // 保存本地的 unreadCount（由 UnreadManager 管理）
                var localUnreadCount = existingSidebar ? existingSidebar.unreadCount : 0;

                cache.users[uid] = d.users[uid];

                // 合并 _sidebar，但保留本地的 unreadCount
                if (serverSidebar) {
                    cache.users[uid]._sidebar = serverSidebar;
                    // 关键：保留本地的 unreadCount，取较大值（避免回退）
                    var serverUnread = serverSidebar.unreadCount || 0;
                    cache.users[uid]._sidebar.unreadCount = Math.max(localUnreadCount, serverUnread);
                } else if (existingSidebar) {
                    cache.users[uid]._sidebar = existingSidebar;
                }
            }
        }

        // ============ 合并群组数据，保留 _sidebar 信息 ============
        // 关键修复：unreadCount 由 UnreadManager 统一管理，不被服务端覆盖
        for (var gid in d.groups) {
            if (!cache.groups[gid]) {
                cache.groups[gid] = d.groups[gid];
            } else {
                var existingSidebar = cache.groups[gid]._sidebar;
                var serverSidebar = d.groups[gid]._sidebar;
                // 保存本地的 unreadCount（由 UnreadManager 管理）
                var localUnreadCount = existingSidebar ? existingSidebar.unreadCount : 0;

                cache.groups[gid] = d.groups[gid];

                // 合并 _sidebar，但保留本地的 unreadCount
                if (serverSidebar) {
                    cache.groups[gid]._sidebar = serverSidebar;
                    // 关键：保留本地的 unreadCount，取较大值（避免回退）
                    var serverUnread = serverSidebar.unreadCount || 0;
                    cache.groups[gid]._sidebar.unreadCount = Math.max(localUnreadCount, serverUnread);
                } else if (existingSidebar) {
                    cache.groups[gid]._sidebar = existingSidebar;
                }
            }
        }
        // 清理已不存在的群组
        for (var gid in cache.groups) {
            if (!d.groups[gid]) delete cache.groups[gid];
        }

        cache.remarks = d.remarks || {};

        // ============ 重构：委托 UnreadManager 处理 read_markers 同步 ============
        if (d.read_markers) {
            UnreadManager.syncFromServer(d);
        }

        if (d.recalled_ids && d.recalled_ids.length > 0) {
            d.recalled_ids.forEach(function (rid) {
                // SQLite 修复：将撤回 ID 统一转换为 String 后处理
                handleMessageRecall(String(rid));
            });
        }

        var needsRender = false;
        var currentChatNewMsgs = [];  // 用于追踪当前聊天的新消息

        if (d.messages && d.messages.length) {
            d.messages.forEach(m => {
                // SQLite 修复：确保消息 ID 是数字类型进行比较
                var msgId = Number(m.id) || 0;
                if (msgId > lastId) {
                    // ============ 更新侧边栏预览数据 ============
                    updateSidebarPreview(m);

                    // ============ 处理当前聊天的消息 ============
                    if (target && activeChatLoaded && isMsgBelongsToChat(m, target)) {
                        // ========== 修复：跳转模式下的新消息处理 ==========
                        // 如果处于跳转模式，且新消息 ID 大于当前视图的 maxMsgId
                        // 则设置 hasNewerMessages 标志，但不立即渲染
                        if (isInJumpMode && m.id > maxMsgId) {
                            hasNewerMessages = true;
                            // 更新侧边栏，但不添加到 currentChatMsgs
                            // 用户向下滚动时会加载这些新消息
                        } else {
                            // 正常模式：正常处理新消息
                            // 检查是否是临时消息的确认
                            var tmpIdx = -1;
                            for (var i = 0; i < currentChatMsgs.length; i++) {
                                if (currentChatMsgs[i].tmp && currentChatMsgs[i].content === m.content) {
                                    tmpIdx = i; break;
                                }
                            }
                            // SQLite 修复：使用安全 ID 比较函数
                            var existsIdx = findMsgIndexById(currentChatMsgs, m.id);

                            if (existsIdx !== -1) {
                                // 消息已存在，检测是否需要更新
                                var oldMsg = currentChatMsgs[existsIdx];

                                // 使用统一的检测函数判断是否需要更新 DOM
                                if (shouldUpdateMessage(oldMsg, m)) {
                                    // 更新数据
                                    currentChatMsgs[existsIdx] = m;
                                    // 使用统一的 DOM 更新函数
                                    updateMessageInDOM(m.id, m, true);
                                } else {
                                    // 无需更新 DOM，但仍更新数据
                                    currentChatMsgs[existsIdx] = m;
                                }
                            } else if (tmpIdx !== -1) {
                                // 替换临时消息
                                var tmpMsgId = currentChatMsgs[tmpIdx].id;
                                var el = document.getElementById('msg-' + tmpMsgId);
                                if (el) {
                                    el.id = 'msg-' + m.id;
                                    el.dataset.id = m.id;
                                    var bub = el.querySelector('.msg-bub'); if (bub) bub.classList.remove('sending');
                                }
                                // 修复：同时更新时间戳元素的ID（如果存在）
                                var oldTimeEl = document.getElementById('time-' + tmpMsgId);
                                if (oldTimeEl) {
                                    oldTimeEl.id = 'time-' + m.id;
                                }
                                currentChatMsgs[tmpIdx] = m;
                                // 更新 maxMsgId
                                if (m.id > maxMsgId) {
                                    maxMsgId = m.id;
                                }
                            } else {
                                // 新消息，添加到当前聊天并渲染
                                currentChatMsgs.push(m);
                                currentChatNewMsgs.push(m);
                                needsRender = true;
                                // 更新 maxMsgId
                                if (m.id > maxMsgId) {
                                    maxMsgId = m.id;
                                }
                            }
                        } // end of else (normal mode)
                    }
                    // 不属于当前聊天的消息不存储，只更新侧边栏

                    // 修复通知泛滥：只对页面加载后的新消息触发通知
                    const isRealtimeMessage = m.timestamp > pageLoadTimestamp;
                    if (isRealtimeMessage && m.from_uid !== me.uid && m.type !== 'system') {
                        let notifyChatId = null;
                        let notifyType = '';
                        if (cache.groups[m.to_uid]) { notifyChatId = m.to_uid; notifyType = 'group'; }
                        else if (m.to_uid === me.uid) { notifyChatId = m.from_uid; notifyType = 'private'; }

                        if (notifyChatId && (!target || target.id !== notifyChatId)) {
                            triggerInAppNotification(m, notifyChatId, notifyType);
                        }

                        if (target && notifyChatId === target.id) {
                            const box = document.getElementById('msg-box');
                            const isBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;
                            if (!isBottom) {
                                scrollUnreadCount++;
                                updateFloatButton(isBottom, 'down');
                            }
                        }
                    }

                    // 更新本次同步的最大消息ID（使用数字类型）
                    newLastId = Math.max(newLastId, msgId);
                }
            });
        }

        // ============ 在处理完所有消息后，再更新 lastId ============
        // 这是关键修复：确保消息处理逻辑不会被提前更新的 lastId 跳过
        if (newLastId > lastId) {
            lastId = newLastId;
        }
        // 如果服务端返回的 serverSyncedId 更大（可能是其他聊天的消息），也要更新
        if (serverSyncedId > lastId) {
            lastId = serverSyncedId;
        }

        if (isFirstSync) isFirstSync = false;

        // 只在当前聊天中渲染新消息
        if (target && needsRender) {
            const box = document.getElementById('msg-box');
            const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;

            // 使用优化的渲染方式（只渲染新消息）
            renderNewMessages();

            // 如果之前在底部，滚动到底部（使用健壮的滚动策略）
            if (wasAtBottom) {
                scrollToBottomRobust();
            }

            if (wasAtBottom) {
                markRead();
            }
        }
        if (target) updateReadStatusIndicators();

        // ============ P2P会话处理============
        if (d.p2p_sessions && p2pManager) {
            d.p2p_sessions.forEach(async function (session) {
                // 处理接收方的会话
                if (session.role === 'receiver') {
                    if (session.status === 'pending') {
                        // 待处理会话：显示传输请求
                        if (!p2pTransfers.has(session.session_id)) {
                            logDebug('P2P', '📥 New transfer request');

                            // 立即标记为已处理，避免重复创建
                            const transferObj = {
                                sessionId: session.session_id,
                                status: 'pending',
                                role: 'receiver',
                                files: session.files,
                                filename: session.files.length > 1
                                    ? `${session.files.length}个文件`
                                    : session.files[0].filename,
                                progress: 0,
                                speed: 0,
                                canResume: false
                            };
                            p2pTransfers.set(session.session_id, transferObj);

                            // 创建P2P会话对象并添加到管理器
                            const p2pSession = new P2PSession(
                                session.session_id,
                                session.files,
                                session.peer_uid,
                                'receiver',
                                p2pManager.signalingClient,
                                session.chat_type
                            );

                            // 添加到活跃会话
                            p2pManager.activeSessions.set(session.session_id, p2pSession);
                            p2pManager.setupSessionCallbacks(p2pSession);
                            logDebug('P2P', '✓ Receiver session added to activeSessions:', session.session_id);
                            logDebug('P2P', 'Active sessions count:', p2pManager.activeSessions.size);

                            // 使用新的消息化P2P系统显示传输请求
                            if (window.p2pMessageIntegration) {
                                try {
                                    // 初始化MessageIntegration（如果还没初始化）
                                    if (!window.p2pMessageIntegration.currentUserId) {
                                        window.p2pMessageIntegration.initialize(me.uid, session.peer_uid);
                                    }

                                    // 创建接收方的传输消息
                                    const fileInfo = session.files.length > 1
                                        ? {
                                            name: `${session.files.length}个文件`,
                                            size: session.total_size,
                                            type: 'multiple'
                                        }
                                        : {
                                            name: session.files[0].filename,
                                            size: session.files[0].size,
                                            type: session.files[0].type || 'application/octet-stream'
                                        };

                                    // 确保发送方的用户信息在cache中
                                    if (!cache.users[session.peer_uid]) {
                                        logWarn('P2P', 'Sender not in cache, will use default avatar');
                                        // 创建一个临时用户信息
                                        cache.users[session.peer_uid] = {
                                            uid: session.peer_uid,
                                            name: getName(session.peer_uid),
                                            avatar_bg: '#' + Math.floor(Math.random() * 16777215).toString(16), // 随机颜色
                                            status: 'unknown'
                                        };
                                    }

                                    await window.p2pMessageIntegration.createTransferMessage(
                                        fileInfo,
                                        session.session_id,
                                        session.peer_uid,
                                        getName(session.peer_uid),
                                        false  // isSender = false (这是接收方)
                                    );
                                    logDebug('P2P', 'Transfer request message created in chat');
                                } catch (error) {
                                    logError('P2P', 'Failed to create transfer request message:', error);
                                    // 回退到旧的模态框
                                    if (typeof showP2PRequest === 'function') {
                                        showP2PRequest({
                                            session_id: session.session_id,
                                            sender_uid: session.peer_uid,
                                            chat_type: session.chat_type,
                                            files: session.files,
                                            total_size: session.total_size,
                                            file_count: session.file_count
                                        });
                                    }
                                }
                            } else {
                                logWarn('P2P', 'MessageIntegration not available, falling back to old UI');
                                // 回退到旧的模态框
                                if (typeof showP2PRequest === 'function') {
                                    showP2PRequest({
                                        session_id: session.session_id,
                                        sender_uid: session.peer_uid,
                                        chat_type: session.chat_type,
                                        files: session.files,
                                        total_size: session.total_size,
                                        file_count: session.file_count
                                    });
                                }
                            }

                            // 已在开头标记为已处理
                        }
                    } else if (session.status === 'active' || session.status === 'connecting') {
                        // 活跃会话：确保会话对象存在（只创建一次）
                        if (!p2pManager.activeSessions.has(session.session_id)) {
                            logDebug('P2P', '🔄 Restoring receiver session:', session.session_id);

                            const p2pSession = new P2PSession(
                                session.session_id,
                                session.files,
                                session.peer_uid,
                                'receiver',
                                p2pManager.signalingClient,
                                session.chat_type
                            );

                            // 设置状态为connecting（准备接收WebRTC信令）
                            p2pSession.setStatus('connecting');

                            // 设置WebRTC（准备接收offer）
                            p2pSession.setupWebRTC().catch(err => {
                                logError('P2P', 'Failed to setup WebRTC:', err);
                            });

                            // 添加到活跃会话
                            p2pManager.activeSessions.set(session.session_id, p2pSession);
                            p2pManager.setupSessionCallbacks(p2pSession);

                            // 同时添加到跟踪信息（防止重复创建）
                            const transferObj = {
                                sessionId: session.session_id,
                                status: session.status,
                                role: 'receiver',
                                files: session.files,
                                filename: session.files.length > 1
                                    ? `${session.files.length}个文件`
                                    : session.files[0].filename,
                                progress: 0,
                                speed: 0,
                                canResume: false
                            };
                            p2pTransfers.set(session.session_id, transferObj);
                        }
                    }
                }
                // 处理发送方的会话
                else if (session.role === 'sender') {
                    if (session.status === 'pending' || session.status === 'active' || session.status === 'connecting') {
                        const p2pSession = p2pManager.activeSessions.get(session.session_id);

                        // 私聊：检测状态变化（pending -> connecting）
                        if (session.chat_type === 'private') {
                            // 检查是否需要更新UI状态
                            const currentTransfer = p2pTransfers.get(session.session_id);
                            const statusChanged = !currentTransfer || currentTransfer.status !== session.status;

                            if (statusChanged && currentTransfer) {
                                // 定义状态优先级（防止状态倒退）
                                const statusPriority = {
                                    'pending': 1,
                                    'accepted': 2,
                                    'connecting': 3,
                                    'active': 3,  // active 和 connecting 同级
                                    'transferring': 4,
                                    'completed': 5,
                                    'failed': 5,
                                    'cancelled': 5,
                                    'expired': 5
                                };

                                const currentPriority = statusPriority[currentTransfer.status] || 0;
                                const newPriority = statusPriority[session.status] || 0;

                                // 只允许状态向前推进，不允许倒退
                                if (newPriority < currentPriority && currentPriority < 5) {
                                    logDebug('P2P', '📡 Ignoring status downgrade from', currentTransfer.status, 'to', session.status);
                                } else {
                                    logDebug('P2P', '📡 Sender detected status change:', session.session_id,
                                        currentTransfer.status, '->', session.status);

                                    // 更新传输跟踪状态
                                    currentTransfer.status = session.status;

                                    // 更新消息UI状态
                                    if (window.p2pMessageIntegration) {
                                        window.p2pMessageIntegration.updateMessageStatus(session.session_id, session.status, {})
                                            .catch(err => logError('P2P', 'Failed to update message status:', err));
                                    }
                                }
                            }

                            // 如果状态是connecting，启动WebRTC
                            if (session.status === 'connecting' && p2pSession) {
                                if (!p2pSession.peerConnection) {
                                    logDebug('P2P', '🚀 Receiver accepted, starting WebRTC...');
                                    p2pSession.setupWebRTC().catch(err => {
                                        logError('P2P', '❌ Failed to setup WebRTC:', err);
                                    });
                                }
                            } else if (session.status === 'connecting' && !p2pSession && !processedSessions.has(session.session_id)) {
                                // 只对未处理过的会话记录一次警告
                                logWarn('P2P', '⚠️ Session not in activeSessions (old session):', session.session_id);
                                processedSessions.add(session.session_id);
                            }
                        }

                        // 群聊：检查参与者状态变化
                        if (session.chat_type === 'group' && session.participants) {
                            if (p2pSession && p2pSession instanceof P2PGroupSession) {
                                session.participants.forEach(function (participant) {
                                    // 检查是否有新接受的参与者
                                    if (participant.status === 'accepted' && !p2pSession.acceptedReceivers.has(participant.uid)) {
                                        logDebug('P2P', '🚀 Participant accepted:', participant.uid);
                                        p2pSession.onReceiverAccepted(participant.uid);
                                    }
                                });
                            }
                        }

                        // 更新跟踪信息
                        if (!p2pTransfers.has(session.session_id)) {
                            p2pTransfers.set(session.session_id, {
                                sessionId: session.session_id,
                                status: session.status,
                                role: 'sender',
                                files: session.files,
                                filename: session.files.length > 1
                                    ? `${session.files.length}个文件`
                                    : session.files[0].filename,
                                progress: 0,
                                speed: 0,
                                canResume: false
                            });
                        }
                    }
                }
            });
        }

        // 处理P2P信令
        if (d.p2p_signals && d.p2p_signals.length > 0 && p2pManager) {
            logDebug('P2P', '📨 Received', d.p2p_signals.length, 'signals');
            d.p2p_signals.forEach(async function (signal) {
                const session = p2pManager.activeSessions.get(signal.session_id);
                if (session) {
                    logDebug('P2P', '📨', signal.signal_type);
                    await session.handleSignal(signal.signal_type, signal.signal_data);
                }
            });
        }

        updateListUI(); updateContactUI();
        if (target && target.type === 'group' && !cache.groups[target.id] && target.id !== 'group_global') { target = null; document.getElementById('chat-t').innerText = '群组已解散'; document.getElementById('input-area').style.display = 'none'; document.getElementById('btn-grp-set').style.display = 'none'; }
    } catch (e) {
        logError('Sync', 'sync error:', e);
    }
    // 优化：减少轮询间隔以提高实时性
    pollingTimer = setTimeout(sync, 500);
}

function triggerInAppNotification(msg, chatId, type) {
    currentNotifChatId = { id: chatId, type: type, name: (type === 'group' ? cache.groups[chatId].name : getName(chatId)) };
    var banner = document.getElementById('notif-banner');
    var av = document.getElementById('notif-av');
    var tit = document.getElementById('notif-title');
    var txt = document.getElementById('notif-text');

    var senderName = getName(msg.from_uid);
    var content = msg.type === 'file' ? '[文件] ' + msg.filename : msg.content;
    if (content.startsWith('{"type":"merge_fwd"')) content = '[聊天记录]';
    if (msg.type === 'sticker') content = '[表情]';

    if (type === 'group') {
        var gName = cache.groups[chatId].name;
        tit.innerText = gName;
        txt.innerText = senderName + ": " + content;
        av.innerText = gName[0];
        av.style.background = '#007aff';
    } else {
        tit.innerText = senderName;
        txt.innerText = content;
        av.innerText = '';
        av.style.background = cache.users[chatId].avatar_bg;
    }

    banner.classList.add('show');
    if (notifTimer) clearTimeout(notifTimer);
    notifTimer = setTimeout(function () {
        banner.classList.remove('show');
    }, 4000);
}

function handleNotifClick() {
    if (currentNotifChatId) {
        switchChat(currentNotifChatId.id, currentNotifChatId.type, currentNotifChatId.name);
        document.getElementById('notif-banner').classList.remove('show');
    }
}

/**
 * 健壮的滚动到底部辅助函数
 * 使用三重定位策略确保滚动到绝对底部：
 * 1. 立即设置 scrollTop
 * 2. 使用 requestAnimationFrame 在下一帧再次设置
 * 3. 使用 setTimeout 延迟后再次设置，捕获图片加载等布局变化
 */
function scrollToBottomRobust(callback) {
    const box = document.getElementById('msg-box');
    if (!box) return;

    // 第一次立即设置
    box.scrollTop = box.scrollHeight;

    // 第二次：下一帧
    requestAnimationFrame(() => {
        box.scrollTop = box.scrollHeight;
        lastScrollTop = box.scrollTop;

        // 第三次：再下一帧（处理布局回流）
        requestAnimationFrame(() => {
            box.scrollTop = box.scrollHeight;
            lastScrollTop = box.scrollTop;

            // 第四次：50ms 后（捕获图片/懒加载元素）
            setTimeout(() => {
                box.scrollTop = box.scrollHeight;
                lastScrollTop = box.scrollTop;

                // 第五次：100ms 后（最终兜底）
                setTimeout(() => {
                    box.scrollTop = box.scrollHeight;
                    lastScrollTop = box.scrollTop;
                    if (callback) callback();
                }, 50);
            }, 50);
        });
    });
}

/**
 * 跳转到底部（优化版）
 * 如果处于跳转模式，先退出跳转模式并重新加载最新消息
 * 否则直接滚动到当前视图的底部
 */
async function jumpToBottom() {
    scrollUnreadCount = 0;
    updateFloatButton(true, 'down');

    // 检查是否处于跳转模式
    if (isInJumpMode) {
        // 退出跳转模式并重新加载最新消息
        await returnToLatest();
        // returnToLatest 会调用 loadActiveChat，自动滚动到底部
    } else {
        // 直接滚动到底部
        scrollToBottomRobust(() => {
            markRead();
        });
    }
}

/**
 * 标记已读（重构版）
 * 委托 UnreadManager 处理乐观更新和后端同步
 * @param {string} chatId - 聊天 ID（可选，默认为当前聊天）
 * @param {string} msgId - 要标记已读的消息 ID（可选，默认为最后一条）
 */
async function markRead(chatId, msgId) {
    if (!target || currentChatMsgs.length === 0) return;
    if (!chatId) chatId = target.id;

    var lastMsgIdInChat = msgId;
    if (!lastMsgIdInChat) {
        // 计算要标记已读的消息 ID
        // 群聊：标记该群的所有消息
        // 私聊：只标记对方发给我的消息
        // 特殊处理：与自己聊天时，标记所有自己发给自己的消息
        var relMsgs = [];
        for (var i = 0; i < currentChatMsgs.length; i++) {
            var m = currentChatMsgs[i];
            if (target.type === 'group') {
                if (m.to_uid === chatId) {
                    relMsgs.push(m);
                }
            } else if (chatId === me.uid) {
                if (m.from_uid === me.uid && m.to_uid === me.uid) {
                    relMsgs.push(m);
                }
            } else {
                if (m.from_uid === chatId && m.to_uid === me.uid) {
                    relMsgs.push(m);
                }
            }
        }
        if (relMsgs.length > 0) lastMsgIdInChat = relMsgs[relMsgs.length - 1].id;
    }
    if (!lastMsgIdInChat) return;

    // 委托 UnreadManager 处理（包括乐观更新 + 后端同步 + UI 更新）
    await UnreadManager.markAsRead(chatId, target.type, lastMsgIdInChat);
}

function updateReadStatusIndicators() {
    if (!target || target.type !== 'private') return;

    // 特殊处理：与自己聊天时，显示已读状态
    if (target.id === me.uid) {
        var myReadId = 0;
        if (cache.read_markers && cache.read_markers[me.uid]) {
            myReadId = cache.read_markers[me.uid][me.uid] || 0;
        }

        var rows = document.querySelectorAll('.msg-row.me');
        rows.forEach(row => {
            var mid = parseInt(row.dataset.id);
            var stat = row.querySelector('.read-stat');
            if (stat) {
                if (mid <= myReadId) {
                    stat.classList.add('read');
                    stat.innerText = '已读';
                } else {
                    stat.classList.remove('read');
                    stat.innerText = '未读';
                }
            }
        });
        return;
    }

    // 修复已读状态显示逻辑
    // read_markers[reader_uid][chat_id] = msg_id 表示 reader_uid 已读 chat_id 会话到 msg_id
    // 对于私聊：需要查询对方(target.id)对当前会话(me.uid)的已读位置

    var otherReadId = 0;
    if (cache.read_markers[target.id]) {
        // 在私聊中，对方查看的是与我(me.uid)的会话
        otherReadId = cache.read_markers[target.id][me.uid] || 0;
    }

    var rows = document.querySelectorAll('.msg-row.me');
    rows.forEach(row => {
        var mid = parseInt(row.dataset.id);
        var stat = row.querySelector('.read-stat');
        if (stat) {
            if (mid <= otherReadId) {
                stat.classList.add('read');
                stat.innerText = '已读';
            } else {
                stat.classList.remove('read');
                stat.innerText = '未读';
            }
        }
    });
}

// ============ 重构：使用 UnreadManager 获取未读数量 ============
/**
 * 获取指定聊天的未读消息数（重构版）
 * 委托给 UnreadManager 统一管理
 * @param {string} chatId - 聊天 ID
 * @param {string} type - 聊天类型 ('group' 或 'private')
 * @returns {number} 未读消息数（0 表示无未读）
 */
function getUnreadCount(chatId, type) {
    return UnreadManager.getCount(chatId, type);
}

// 更新移动端未读消息气泡
function updateMobileUnreadBadge() {
    var badge = document.getElementById('mobile-unread-badge');
    if (!badge) return;

    // 严格的显示条件：
    // 1. 屏幕宽度 <= 768px (移动端)
    // 2. 用户处于聊天界面 (target 存在)
    // 3. body 有 mobile-chat-active 类
    var isMobile = window.innerWidth <= 768;
    var inChatView = target !== null;
    var isMobileChatActive = document.body.classList.contains('mobile-chat-active');

    // 如果不满足基本条件，强制隐藏
    if (!isMobile || !inChatView || !isMobileChatActive) {
        badge.classList.remove('show');
        return;
    }

    // 统计除当前聊天外的所有未读消息
    var totalUnread = 0;

    // 遍历所有群聊
    for (var gid in cache.groups) {
        if (gid !== target.id) {
            totalUnread += getUnreadCount(gid, 'group');
        }
    }

    // 遍历所有私聊（从 _sidebar 获取）
    for (var uid in cache.users) {
        var u = cache.users[uid];
        if (u._sidebar && u._sidebar.lastMsgTime && uid !== target.id) {
            totalUnread += getUnreadCount(uid, 'private');
        }
    }

    // 更新气泡显示
    if (totalUnread > 0) {
        badge.textContent = totalUnread > 99 ? '99+' : totalUnread;
        badge.classList.add('show');
    } else {
        badge.classList.remove('show');
    }
}

function formatListTime(ts) {
    if (!ts) return '';
    var date = new Date(ts * 1000);
    var now = new Date();
    var isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
    var isYesterday = new Date(now.getTime() - 86400000).getDate() === date.getDate();
    var hrs = date.getHours();
    var min = date.getMinutes();
    var timeStr = (hrs < 10 ? '0' : '') + hrs + ':' + (min < 10 ? '0' : '') + min;
    if (isToday) return timeStr;
    if (isYesterday) return '昨天';
    var mo = date.getMonth() + 1;
    var da = date.getDate();
    return mo + '-' + da;
}

// FIX BUG 3: Smart chat time formatting (Today/Yesterday/Date)
function formatChatTime(ts) {
    var d = new Date(ts * 1000);
    var now = new Date();
    var isToday = d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    var yesterday = new Date(now.getTime() - 86400000);
    var isYesterday = d.getDate() === yesterday.getDate() && d.getMonth() === yesterday.getMonth() && d.getFullYear() === yesterday.getFullYear();

    var timeStr = (d.getHours() < 10 ? '0' : '') + d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();

    if (isToday) return timeStr;
    if (isYesterday) return '昨天 ' + timeStr;
    if (d.getFullYear() === now.getFullYear()) return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + timeStr;
    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + timeStr;
}

function updateListUI() {
    var listItems = [];
    // ============ 从 _sidebar 读取群聊预览 ============
    for (var gid in cache.groups) {
        var g = cache.groups[gid];
        var sidebar = g._sidebar || {};
        var ts = sidebar.lastMsgTime || 0;
        var lastText = sidebar.lastMsgPreview || '';
        listItems.push({ id: gid, type: 'group', name: g.name, ts: ts, pinned: cache.pinned[gid] ? 1 : 0, lastText: lastText, html: '', obj: g });
    }
    // ============ 从 _sidebar 读取私聊预览 ============
    // 不再遍历消息数组，而是遍历所有有 _sidebar 数据的用户
    for (var uid in cache.users) {
        var u = cache.users[uid];
        if (u._sidebar && u._sidebar.lastMsgTime) {
            var sidebar = u._sidebar;
            var ts = sidebar.lastMsgTime || 0;
            var lastText = sidebar.lastMsgPreview || '';
            listItems.push({ id: uid, type: 'private', name: getName(uid), ts: ts, pinned: cache.pinned[uid] ? 1 : 0, lastText: lastText, html: '', obj: u });
        }
    }
    listItems.sort(function (a, b) { if (a.pinned !== b.pinned) return b.pinned - a.pinned; return b.ts - a.ts; });
    var renderItems = [];
    listItems.forEach(function (item) {
        var act = (target && target.id === item.id) ? 'active' : '';
        var pinCls = item.pinned ? 'pinned' : '';
        var unread = getUnreadCount(item.id, item.type);
        var badge = (unread > 0 && act === '') ? '<div class="unread-badge">' + (unread > 99 ? '99+' : unread) + '</div>' : '';
        var timeStr = formatListTime(item.ts);
        var avHtml = item.type === 'group' ? '<div class="item-av" style="background:#007aff">' + item.name[0] + '</div>' : '<div class="item-av" style="background:' + item.obj.avatar_bg + '"></div>';
        var html = avHtml + '<div class="item-body"><div class="item-top"><div class="item-t">' + item.name + '</div><div class="item-time">' + timeStr + '</div></div><div class="item-btm"><div class="item-d">' + item.lastText + '</div>' + badge + '</div></div>';
        renderItems.push({ id: item.id, cls: 'list-item clickable ' + act + ' ' + pinCls, click: (function (id, type, name) { return function () { switchChat(id, type, name) } })(item.id, item.type, item.name), context: (function (id) { return function (e) { handleListContextMenu(e, id) } })(item.id), html: html });
    });
    applyDiff(document.getElementById('ls-msg'), renderItems);

    // 更新移动端未读消息气泡
    updateMobileUnreadBadge();
}

function updateContactUI() {
    var items = [];
    items.push({ id: 'h-grp', cls: '', html: '<div style="font-size:12px;color:#888;margin:10px 0 5px 5px;">群组</div>', click: null });
    for (var gid in cache.groups) {
        items.push({ id: 'c-' + gid, cls: 'list-item clickable', click: (function (id, n) { return function () { switchChat(id, 'group', n) } })(gid, cache.groups[gid].name), html: '<div class="item-av" style="background:#007aff">' + cache.groups[gid].name[0] + '</div><div class="item-body"><div class="item-t">' + cache.groups[gid].name + '</div></div>' });
    }

    // 添加"我自己"选项，允许用户向自己发起私聊
    items.push({ id: 'h-self', cls: '', html: '<div style="font-size:12px;color:#888;margin:15px 0 5px 5px;">我自己</div>', click: null });
    var myBg = cache.users[me.uid] ? (cache.users[me.uid].avatar_bg || '#ccc') : '#ccc';
    var mySelfHtml = '<div class="item-av" style="background:' + myBg + '"></div><div class="item-body"><div class="item-t">' + getName(me.uid) + '</div><div class="item-d">与自己的聊天</div></div>';
    items.push({ id: 'c-' + me.uid, cls: 'list-item clickable', click: (function (id, n) { return function () { switchChat(id, 'private', n) } })(me.uid, getName(me.uid)), context: (function (id) { return function (e) { handleListContextMenu(e, id) } })(me.uid), html: mySelfHtml });

    items.push({ id: 'h-usr', cls: '', html: '<div style="font-size:12px;color:#888;margin:15px 0 5px 5px;">在线好友</div>', click: null });
    for (var uid in cache.users) {
        if (uid !== me.uid && cache.users[uid].status === 'online') {
            var uBg = cache.users[uid].avatar_bg || '#ccc';
            var htmlStr = '<div class="item-av" style="background:' + uBg + '"></div><div class="item-body"><div class="item-t">' + getName(uid) + '</div><div class="item-d">在线</div></div>';
            items.push({ id: 'c-' + uid, cls: 'list-item clickable', click: (function (id, n) { return function () { switchChat(id, 'private', n) } })(uid, getName(uid)), context: (function (id) { return function (e) { handleListContextMenu(e, id) } })(uid), html: htmlStr });
        }
    }
    applyDiff(document.getElementById('ls-con'), items);
}

// ============ 重构：从 _sidebar 读取最后消息信息 ============
function getLastMsgInfo(tid, type) {
    if (type === 'group') {
        var g = cache.groups[tid];
        return g && g._sidebar ? g._sidebar : null;
    } else {
        var u = cache.users[tid];
        return u && u._sidebar ? u._sidebar : null;
    }
}

function getSysText(m) {
    if (!m.content) return "";
    try {
        var sys = JSON.parse(m.content);
        if (sys.sys_type === 'nudge') {
            var fromName = getName(sys.from_uid) || 'Unknown';
            var toName = (sys.target_uid === me.uid) ? '你' : (getName(sys.target_uid) || 'Unknown');
            if (sys.from_uid === me.uid) fromName = '你';
            return fromName + " 戳了戳 " + toName;
        } else if (sys.sys_type === 'group_rename') {
            var opName = getName(sys.operator_uid);
            return opName + " 修改群名为 '" + sys.new_name + "'";
        } else if (sys.sys_type === 'group_create') {
            return "群组 '" + sys.group_name + "' 已创建";
        } else if (sys.sys_type === 'group_invite') {
            var opName = getName(sys.operator_uid);
            return opName + " 邀请了成员加入群聊";
        } else if (sys.sys_type === 'group_kick') {
            var opName = getName(sys.operator_uid);
            var tName = getName(sys.target_uid);
            return opName + " 将 " + tName + " 移出群聊";
        }
    } catch (e) { }
    return m.content;
}

function fmt(m) {
    if (m.type === 'system') return '[系统消息]';
    if (m.is_recalled) return '[已撤回]';
    if (m.content && m.content.startsWith('{"type":"merge_fwd"')) return '[聊天记录]';
    if (m.type === 'sticker') return '[表情]';
    return m.type === 'file' ? '[文件]' : m.content;
}

function applyDiff(container, items) {
    var children = Array.from(container.children); children.forEach(el => { var exists = false; for (var i = 0; i < items.length; i++) { if (items[i].id === el.dataset.id) { exists = true; break; } } if (!exists) el.remove(); });
    items.forEach((item, index) => {
        var el = container.querySelector('[data-id="' + item.id + '"]');
        if (!el) { el = document.createElement('div'); el.dataset.id = item.id; el.className = item.cls || 'list-item clickable'; el.onclick = item.click; if (item.context) { el.oncontextmenu = item.context; let timer; el.ontouchstart = function (e) { timer = setTimeout(function () { item.context(e); }, 600); }; el.ontouchend = function () { clearTimeout(timer); }; el.ontouchmove = function () { clearTimeout(timer); }; } el.innerHTML = item.html; if (index >= container.children.length) container.appendChild(el); else container.insertBefore(el, container.children[index]); }
        else { if (index < container.children.length && container.children[index] !== el) container.insertBefore(el, container.children[index]); if (item.cls && el.className !== item.cls) el.className = item.cls; if (el.innerHTML !== item.html) el.innerHTML = item.html; el.onclick = item.click; if (item.context) el.oncontextmenu = item.context; }
    });
}

function handleListContextMenu(e, id) {
    e.preventDefault(); e.stopPropagation();
    listCtxTargetId = id;
    var menu = document.getElementById('list-ctx-menu');
    var lbl = document.getElementById('lbl-pin');
    lbl.innerText = cache.pinned[id] ? '取消置顶' : '置顶聊天';
    var rmk = document.getElementById('list-ctx-remark');
    if (cache.groups[id]) rmk.style.display = 'none'; else rmk.style.display = 'flex';

    var x = e.clientX || (e.touches && e.touches[0].clientX);
    var y = e.clientY || (e.touches && e.touches[0].clientY);
    if (!x && x !== 0) { x = window.innerWidth / 2; y = window.innerHeight / 2; }
    menu.style.left = x + 'px'; menu.style.top = y + 'px'; menu.style.display = 'flex';
    document.addEventListener('click', closeListCtx, { once: true });
}
function closeListCtx() { document.getElementById('list-ctx-menu').style.display = 'none'; }

function listMenuAction(act) {
    if (act === 'pin' && listCtxTargetId) {
        if (cache.pinned[listCtxTargetId]) delete cache.pinned[listCtxTargetId]; else cache.pinned[listCtxTargetId] = 1; localStorage.setItem('qq_pinned', JSON.stringify(cache.pinned)); updateListUI();
    } else if (act === 'remark' && listCtxTargetId) {
        openProfile(listCtxTargetId);
    }
    closeListCtx();
}

function switchChat(id, type, name) {
    // 在移动端模式下，即使是同一个聊天，也允许重新打开（修复响应式切换问题）
    if (target && target.id === id && window.innerWidth > 768) return;
    target = { id: id, type: type, name: name };
    exitMulti(); cancelQuote();
    scrollUnreadCount = 0;
    lastScrollTop = 0;
    updateFloatButton(true, 'down');

    // ============ 重构：使用 UnreadManager 统一处理未读清除 ============
    // 当用户进入聊天窗口时，委托 UnreadManager 清除未读红点
    UnreadManager.onEnterChat(id, type);

    // ============ 完全重置状态 ============
    // Step 1: 清空当前聊天消息数组
    currentChatMsgs = [];

    // Step 2: 重置消息ID追踪变量
    minMsgId = 0;
    maxMsgId = 0;
    activeChatLoaded = false;

    // Step 3: 重置懒加载状态
    LAZY_LOAD_CONFIG.isLoadingHistory = false;
    LAZY_LOAD_CONFIG.isInitialLoad = true;

    // Step 3.1: 重置跳转模式状态
    isInJumpMode = false;
    hasNewerMessages = false;
    isLoadingNewer = false;

    // 保存当前会话状态到 localStorage
    try {
        localStorage.setItem('qq_current_chat', JSON.stringify({
            id: id,
            type: type,
            name: name
        }));
    } catch (e) {
        logWarn('Session', '保存会话状态失败:', e);
    }

    if (window.innerWidth <= 768) document.body.classList.add('mobile-chat-active');
    document.getElementById('chat-t').innerText = name;
    document.getElementById('input-area').style.display = 'block';
    var btn = document.getElementById('btn-grp-set');
    if (type === 'group') {
        var g = cache.groups[id];
        document.getElementById('chat-s').innerText = g ? g.members.length + ' 人' : '';
        if (g && !g.system && g.owner === me.uid) btn.style.display = 'flex'; else btn.style.display = 'none';
    } else {
        var u = cache.users[id];
        document.getElementById('chat-s').innerHTML = (u && u.status === 'online') ? '<div class="dot"></div> 在线' : '离线';
        btn.style.display = 'none';
    }

    // Step 4: 清空聊天框并显示加载中
    var box = document.getElementById('msg-box');
    box.innerHTML = '<div class="history-loading-spinner" style="text-align:center;padding:20px;color:#999;"><div class="spinner"></div>加载中...</div>';

    // Step 5: 加载历史消息
    loadInitialHistory();

    updateListUI();

    // 更新移动端未读消息气泡
    updateMobileUnreadBadge();
}

// ==================== 懒加载核心函数 ====================


/**
 * 加载初始历史消息（最新的30条）
 */
async function loadInitialHistory() {
    if (!target || !me) return;

    const chatId = target.id;
    const chatType = target.type;

    try {
        // 调用历史消息API，before_id=0表示获取最新的
        const url = `/api/history?uid=${encodeURIComponent(me.uid)}&chat_id=${encodeURIComponent(chatId)}&chat_type=${chatType}&limit=${LAZY_LOAD_CONFIG.initialLoadCount}`;
        const r = await fetch(url);

        if (r.status === 403) {
            const errData = await r.json();
            if (errData.error === 'session_invalidated') {
                alert(errData.message || '您的账户已被禁用，请重新登录');
                localStorage.removeItem('qq_uid');
                location.reload();
                return;
            }
        }

        const data = await r.json();
        const box = document.getElementById('msg-box');

        if (target.id !== chatId) return; // 用户已切换聊天

        // 更新懒加载状态
        LAZY_LOAD_CONFIG.hasMoreHistory[chatId] = data.has_more;
        if (data.messages.length > 0) {
            LAZY_LOAD_CONFIG.oldestMsgId[chatId] = data.messages[0].id;
        }

        // 将消息存储到当前聊天数组（不再使用全局 cache.msgs）
        currentChatMsgs = data.messages.slice();  // 复制数组

        // 设置消息ID追踪变量
        if (data.messages.length > 0) {
            minMsgId = data.messages[0].id;  // 第一条是最旧的
            maxMsgId = data.messages[data.messages.length - 1].id;  // 最后一条是最新的
        }

        // 标记当前聊天已完成初始加载
        activeChatLoaded = true;

        // 清空加载提示
        box.innerHTML = '';

        // 渲染所有消息（包括P2P消息）
        if (data.messages.length > 0) {
            renderHistoryMessages(data.messages, false);
            // 滚动到底部（使用健壮的滚动策略）
            scrollToBottomRobust();
        } else {
            box.innerHTML = '<div class="empty">暂无消息</div>';
        }

        LAZY_LOAD_CONFIG.isInitialLoad = false;

        // 标记已读
        setTimeout(() => { markRead(); }, 100);

    } catch (e) {
        logError('History', '加载历史消息失败:', e);
        const box = document.getElementById('msg-box');
        box.innerHTML = '<div class="empty">加载失败，请刷新重试</div>';
    }
}

/**
 * 加载更多历史消息（向上滚动时触发）
 * @param {boolean} silent - 是否静默加载（不显示spinner）
 * @returns {Promise} - 加载完成的Promise
 */
async function loadMoreHistory(silent = false) {
    if (!target || !me) return;
    if (LAZY_LOAD_CONFIG.isLoadingHistory) return;

    const chatId = target.id;
    const chatType = target.type;

    // 检查是否还有更多历史
    if (LAZY_LOAD_CONFIG.hasMoreHistory[chatId] === false) return;

    const oldestId = LAZY_LOAD_CONFIG.oldestMsgId[chatId];
    if (!oldestId) return;

    // 节流检查：防止快速滚动时重复请求
    const now = Date.now();
    if (now - LAZY_LOAD_CONFIG.lastFetchTime < LAZY_LOAD_CONFIG.minTimeBetweenFetches) {
        return;
    }

    LAZY_LOAD_CONFIG.isLoadingHistory = true;
    LAZY_LOAD_CONFIG.isSilentLoading = silent;
    LAZY_LOAD_CONFIG.lastFetchTime = now;

    const box = document.getElementById('msg-box');
    let loadingIndicator = null;

    // 只有非静默模式才显示加载提示
    if (!silent) {
        loadingIndicator = document.getElementById('history-loading-top');
        if (!loadingIndicator) {
            loadingIndicator = document.createElement('div');
            loadingIndicator.id = 'history-loading-top';
            loadingIndicator.className = 'history-loading-spinner';
            loadingIndicator.innerHTML = '<div class="spinner"></div> 加载中...';
            loadingIndicator.style.cssText = 'text-align:center;padding:10px;color:#999;font-size:12px;';
            box.insertBefore(loadingIndicator, box.firstChild);
        }
    }

    // 创建Prefetch Promise用于跟踪静默加载状态
    const prefetchPromise = (async () => {
        try {
            const url = `/api/history?uid=${encodeURIComponent(me.uid)}&chat_id=${encodeURIComponent(chatId)}&chat_type=${chatType}&before_id=${oldestId}&limit=${LAZY_LOAD_CONFIG.loadMoreCount}`;
            const r = await fetch(url);
            const data = await r.json();

            if (target.id !== chatId) {
                LAZY_LOAD_CONFIG.isLoadingHistory = false;
                LAZY_LOAD_CONFIG.isSilentLoading = false;
                LAZY_LOAD_CONFIG.pendingPrefetch = null;
                return;
            }

            // 移除加载提示（如果存在）
            loadingIndicator = document.getElementById('history-loading-top');
            if (loadingIndicator) loadingIndicator.remove();

            if (data.messages.length === 0) {
                LAZY_LOAD_CONFIG.hasMoreHistory[chatId] = false;
                LAZY_LOAD_CONFIG.isLoadingHistory = false;
                LAZY_LOAD_CONFIG.isSilentLoading = false;
                LAZY_LOAD_CONFIG.pendingPrefetch = null;
                return;
            }

            // 更新状态
            LAZY_LOAD_CONFIG.hasMoreHistory[chatId] = data.has_more;
            LAZY_LOAD_CONFIG.oldestMsgId[chatId] = data.messages[0].id;

            // 更新minMsgId
            if (data.messages.length > 0) {
                minMsgId = data.messages[0].id;
            }

            // 将消息添加到当前聊天数组头部
            data.messages.forEach(m => {
                if (!currentChatMsgs.find(x => x.id === m.id)) {
                    currentChatMsgs.unshift(m);
                }
            });

            // **滚动锚定：记录当前滚动位置和高度**
            const oldScrollHeight = box.scrollHeight;
            const oldScrollTop = box.scrollTop;

            // 渲染新消息到顶部
            renderHistoryMessages(data.messages, true);

            // **滚动锚定：同步调整滚动位置以保持视图不动**
            // 使用同步操作确保DOM更新后立即调整
            const newScrollHeight = box.scrollHeight;
            const scrollDiff = newScrollHeight - oldScrollHeight;
            box.scrollTop = oldScrollTop + scrollDiff;

            // 使用rAF确保最终位置正确
            requestAnimationFrame(() => {
                const finalScrollHeight = box.scrollHeight;
                if (finalScrollHeight !== newScrollHeight) {
                    // 如果高度变化了（图片加载等），重新计算
                    box.scrollTop = oldScrollTop + (finalScrollHeight - oldScrollHeight);
                }
                lastScrollTop = box.scrollTop;
            });

        } catch (e) {
            logError('History', '加载更多历史失败:', e);
            const li = document.getElementById('history-loading-top');
            if (li) li.remove();
        }

        LAZY_LOAD_CONFIG.isLoadingHistory = false;
        LAZY_LOAD_CONFIG.isSilentLoading = false;
        LAZY_LOAD_CONFIG.pendingPrefetch = null;
    })();

    // 如果是静默加载，保存Promise引用
    if (silent) {
        LAZY_LOAD_CONFIG.pendingPrefetch = prefetchPromise;
    }

    return prefetchPromise;
}

/**
 * 显示加载指示器（当用户滚动到顶部且静默加载未完成时）
 */
function showLoadingSpinner() {
    const box = document.getElementById('msg-box');
    if (!box) return;

    let loadingIndicator = document.getElementById('history-loading-top');
    if (!loadingIndicator && LAZY_LOAD_CONFIG.isLoadingHistory) {
        loadingIndicator = document.createElement('div');
        loadingIndicator.id = 'history-loading-top';
        loadingIndicator.className = 'history-loading-spinner';
        loadingIndicator.innerHTML = '<div class="spinner"></div> 加载中...';
        loadingIndicator.style.cssText = 'text-align:center;padding:10px;color:#999;font-size:12px;';
        box.insertBefore(loadingIndicator, box.firstChild);
    }
}

/**
 * 加载更新的消息（向下滚动时触发，仅在跳转模式下可用）
 */
async function loadMoreNewer() {
    if (!target || !me) return;
    if (!isInJumpMode) return;  // 只有在跳转模式下才需要向下加载
    if (isLoadingNewer) return;
    if (!hasNewerMessages) return;

    const chatId = target.id;
    const chatType = target.type;

    if (maxMsgId === 0) return;

    isLoadingNewer = true;

    // 显示加载提示
    const box = document.getElementById('msg-box');
    let loadingIndicator = document.getElementById('history-loading-bottom');
    if (!loadingIndicator) {
        loadingIndicator = document.createElement('div');
        loadingIndicator.id = 'history-loading-bottom';
        loadingIndicator.className = 'history-loading-spinner';
        loadingIndicator.innerHTML = '<div class="spinner"></div> 加载中...';
        loadingIndicator.style.cssText = 'text-align:center;padding:10px;color:#999;font-size:12px;';
        box.appendChild(loadingIndicator);
    }

    try {
        const url = `/api/history?uid=${encodeURIComponent(me.uid)}&chat_id=${encodeURIComponent(chatId)}&chat_type=${chatType}&after_id=${maxMsgId}&limit=${LAZY_LOAD_CONFIG.loadMoreCount}`;
        const r = await fetch(url);
        const data = await r.json();

        if (target.id !== chatId) {
            isLoadingNewer = false;
            return;
        }

        // 移除加载提示
        loadingIndicator = document.getElementById('history-loading-bottom');
        if (loadingIndicator) loadingIndicator.remove();

        if (data.messages.length === 0) {
            hasNewerMessages = false;
            isLoadingNewer = false;
            // 退出跳转模式
            isInJumpMode = false;
            return;
        }

        // 更新状态
        hasNewerMessages = data.has_newer || false;

        // 更新 maxMsgId
        if (data.messages.length > 0) {
            maxMsgId = data.messages[data.messages.length - 1].id;
        }

        // 将消息添加到当前聊天数组尾部
        data.messages.forEach(m => {
            if (!currentChatMsgs.find(x => x.id === m.id)) {
                currentChatMsgs.push(m);
            }
        });

        // 渲染新消息到底部
        renderHistoryMessages(data.messages, false);

        // 如果没有更新的消息了，退出跳转模式
        if (!hasNewerMessages) {
            isInJumpMode = false;
        }

    } catch (e) {
        logError('History', '加载更新消息失败:', e);
        const li = document.getElementById('history-loading-bottom');
        if (li) li.remove();
    }

    isLoadingNewer = false;
}

/**
 * 跳转模式下的“返回最新消息”功能
 */
async function returnToLatest() {
    if (!target || !me) return;

    // 重新加载当前聊天的最新消息
    isInJumpMode = false;
    hasNewerMessages = false;

    // 清空当前消息数组和ID追踪
    currentChatMsgs = [];
    minMsgId = 0;
    maxMsgId = 0;

    // 重置懒加载状态
    LAZY_LOAD_CONFIG.isLoadingHistory = false;
    LAZY_LOAD_CONFIG.isInitialLoad = true;
    isLoadingNewer = false;

    // 重新加载最新消息
    await loadInitialHistory();
}

/**
 * 渲染历史消息到DOM
 * @param {Array} messages - 消息数组（按时间升序）
 * @param {boolean} prepend - 是否插入到顶部
 */
function renderHistoryMessages(messages, prepend) {
    if (!target || messages.length === 0) return;

    const box = document.getElementById('msg-box');
    const fragment = document.createDocumentFragment();
    let lastTime = 0;

    // 如果是prepend，需要获取当前第一条消息的时间戳作为参考
    if (prepend) {
        const firstExisting = box.querySelector('.msg-row');
        if (firstExisting && firstExisting.dataset.id) {
            // SQLite 修复：使用安全 ID 比较函数
            const existingMsg = findMsgById(currentChatMsgs, firstExisting.dataset.id);
            if (existingMsg) {
                // 不需要设置，lastTime保持为0，让新消息依然显示时间
            }
        }
    }

    // 跟踪已创建的时间戳元素ID，避免在同一个fragment中重复创建
    const createdTimeIds = new Set();

    messages.forEach((m, idx) => {
        // 跳过已存在的DOM元素
        // 类型安全：确保 ID 为 String 格式
        if (document.getElementById('msg-' + safeId(m.id))) return;

        // 时间分隔符
        const msgTime = m.timestamp;
        if (msgTime - lastTime > 300) {
            const tDivId = 'time-' + m.id;
            // 检查DOM和当前fragment中是否已存在
            if (!document.getElementById(tDivId) && !createdTimeIds.has(tDivId)) {
                const tDiv = document.createElement('div');
                tDiv.id = tDivId;
                tDiv.className = 'chat-time';
                tDiv.innerText = formatChatTime(msgTime);
                fragment.appendChild(tDiv);
                createdTimeIds.add(tDivId);
            }
            lastTime = msgTime;
        }

        // 渲染消息
        let div;
        if (m.type === 'system' || m.is_recalled) {
            div = renderSystemMsg(m);
        } else {
            div = renderMessageElement(m, false);
        }
        fragment.appendChild(div);
    });

    if (prepend) {
        // 插入到顶部
        box.insertBefore(fragment, box.firstChild);
    } else {
        box.appendChild(fragment);
    }

    // 为新渲染的GIF启动懒加载观察
    if (gifObserver) {
        box.querySelectorAll('.msg-sticker-gif:not(.observed)').forEach(img => {
            img.classList.add('observed');
            gifObserver.observe(img);
        });
    }

    updateReadStatusIndicators();
}

/**
 * 设置滚动事件监听器（用于懒加载）
 * 优化版：实现积极的预加载和丝滑滚动体验
 */
function setupScrollListener() {
    const box = document.getElementById('msg-box');
    if (!box) return;

    let scrollTimeout = null;
    let isScrolling = false;

    // 使用passive监听器提高滚动性能
    box.addEventListener('scroll', function () {
        isScrolling = true;

        // 节流处理：使用requestAnimationFrame代替setTimeout获得更平滑的体验
        if (scrollTimeout) cancelAnimationFrame(scrollTimeout);

        scrollTimeout = requestAnimationFrame(() => {
            const scrollTop = box.scrollTop;
            const scrollHeight = box.scrollHeight;
            const clientHeight = box.clientHeight;
            const distanceToBottom = scrollHeight - scrollTop - clientHeight;
            const distanceToTop = scrollTop;

            // ==================== 向上滚动预加载逻辑 ====================
            // 检查是否进入预加载区域（距离顶部 800px）
            if (distanceToTop < LAZY_LOAD_CONFIG.loadThreshold) {
                // 检查是否有更多历史
                const chatId = target ? target.id : null;
                const hasMore = chatId && LAZY_LOAD_CONFIG.hasMoreHistory[chatId] !== false;

                if (hasMore) {
                    if (distanceToTop === 0) {
                        // 已经滚动到绝对顶部
                        if (LAZY_LOAD_CONFIG.isLoadingHistory && LAZY_LOAD_CONFIG.isSilentLoading) {
                            // 静默加载还在进行中，显示spinner
                            showLoadingSpinner();
                        } else if (!LAZY_LOAD_CONFIG.isLoadingHistory) {
                            // 没有在加载，立即触发显式加载（显示spinner）
                            loadMoreHistory(false);
                        }
                    } else {
                        // 在触发区域内但未到顶部，触发静默预加载
                        if (!LAZY_LOAD_CONFIG.isLoadingHistory) {
                            loadMoreHistory(true);  // 静默加载，不显示spinner
                        }
                    }
                }
            }

            // ==================== 向下滚动加载逻辑（跳转模式） ====================
            if (distanceToBottom < LAZY_LOAD_CONFIG.loadThresholdBottom && isInJumpMode && hasNewerMessages) {
                loadMoreNewer();
            }

            // ==================== 更新浮动按钮状态 ====================
            const isBottom = distanceToBottom < 50;
            if (isBottom) {
                scrollUnreadCount = 0;
            }
            updateFloatButton(isBottom, 'auto');
            lastScrollTop = scrollTop;
            isScrolling = false;
        });
    }, { passive: true });
}

function renderSystemMsg(m) {
    var div = document.createElement('div');
    div.id = 'msg-' + m.id;
    div.dataset.id = m.id;
    div.dataset.timestamp = m.timestamp;  // 添加时间戳属性，用于P2P消息排序
    div.className = 'msg-row sys';

    var txt = m.content;
    if (m.is_recalled && m.type !== 'system') {
        var nick = getName(m.from_uid);
        if (m.from_uid === me.uid) nick = '你';
        txt = nick + " 撤回了一条消息";
    } else {
        txt = getSysText(m);
    }

    div.innerHTML = '<div class="msg-bub">' + txt + '</div>';
    return div;
}

// 渲染P2P文件传输消息
function renderP2PFileMessage(m) {
    var status = m.p2p_status || 'pending';
    var progress = m.p2p_progress || 0;
    var speed = m.p2p_speed || 0;
    var avgSpeed = m.p2p_avg_speed || 0;
    var sessionId = m.p2p_session_id || '';

    var fileIcon = '📄';
    var statusHTML = '';
    var actionsHTML = '';

    // 根据状态渲染不同的UI
    switch (status) {
        case 'pending':
            statusHTML = '<div class="p2p-status">⏳ 等待对方响应...</div>';
            if (m.from_uid === me.uid) {
                actionsHTML = '<button class="p2p-btn cancel-btn" onclick="cancelP2PTransfer(\\''+sessionId+'\\', event)">取消</button>';
            } else {
                actionsHTML = '<button class="p2p-btn accept-btn" onclick="acceptP2PTransfer(\\''+sessionId+'\\', event)">接收</button>';
                actionsHTML += '<button class="p2p-btn reject-btn" onclick="rejectP2PTransfer(\\''+sessionId+'\\', event)">拒绝</button>';
            }
            break;
        case 'connecting':
            fileIcon = '🔄';
            statusHTML = '<div class="p2p-status">🔗 正在连接...</div>';
            actionsHTML = '<button class="p2p-btn cancel-btn" onclick="cancelP2PTransfer(\\''+sessionId+'\\', event)">取消</button>';
            break;
        case 'transferring':
            fileIcon = '📤';
            statusHTML = '<div class="p2p-progress-container">';
            statusHTML += '<div class="p2p-progress-bar"><div class="p2p-progress-fill" style="width:' + progress + '%"></div></div>';
            statusHTML += '<div class="p2p-progress-info">';
            statusHTML += '<span>' + progress.toFixed(1) + '%</span>';
            statusHTML += '<span>' + formatSpeed(speed) + '</span>';
            statusHTML += '</div></div>';
            actionsHTML = '<button class="p2p-btn cancel-btn" onclick="cancelP2PTransfer(\\''+sessionId+'\\', event)">取消</button>';
            break;
        case 'completed':
            fileIcon = '✅';
            statusHTML = '<div class="p2p-status success">✓ 传输完成</div>';
            if (m.server_filename) {
                actionsHTML = '<button class="p2p-btn download-btn" onclick="downloadFile(\\''+m.server_filename+'\\', \\''+m.filename+'\\')">下载</button>';
            }
            break;
        case 'failed':
            fileIcon = '❌';
            statusHTML = '<div class="p2p-status error">✗ 传输失败</div>';
            break;
        case 'cancelled':
            fileIcon = '🚫';
            statusHTML = '<div class="p2p-status error">已取消</div>';
            break;
        case 'expired':
            fileIcon = '⚠️';
            statusHTML = '<div class="p2p-status error">已失效</div>';
            break;
        case 'rejected':
            fileIcon = '🚫';
            statusHTML = '<div class="p2p-status error">已拒绝</div>';
            break;
        default:
            statusHTML = '<div class="p2p-status">未知状态</div>';
    }

    return '<div class="msg-bub p2p-transfer-message" data-p2p-session="' + sessionId + '">' +
        '<div class="p2p-file-info">' +
        '<div class="p2p-file-icon">' + fileIcon + '</div>' +
        '<div class="p2p-file-details">' +
        '<div class="p2p-file-name">' + m.filename + '</div>' +
        '<div class="p2p-file-size">' + formatFileSize(m.size) + '</div>' +
        '<div class="p2p-method">P2P传输</div>' +
        '</div>' +
        '</div>' +
        statusHTML +
        (actionsHTML ? '<div class="p2p-actions">' + actionsHTML + '</div>' : '') +
        '</div>';
}

// 渲染单条消息的DOM元素
function renderMessageElement(m, animate) {
    var u = cache.users[m.from_uid];
    if (!u) u = { name: '?', avatar_bg: '#ccc' };

    var displayName = getName(m.from_uid);
    var isMe = m.from_uid === me.uid;
    var animClass = (visualOn && animate) ? (isMe ? 'anim-in-right' : 'anim-in-left') : '';
    var div = document.createElement('div');
    div.id = 'msg-' + m.id;
    div.dataset.id = m.id;
    div.dataset.timestamp = m.timestamp;  // 添加时间戳属性，用于P2P消息排序 

    var chkCls = selMsgs.has(m.id.toString()) ? 'checked' : '';
    var chk = '<div class="msg-chk ' + chkCls + '" onclick="toggleSel(\\''+m.id+'\\', event)"></div>';

    var quoteHtml = '';
    if (m.quote) {
        var qContent = m.quote.content;
        if (m.quote.is_recalled) qContent = '<span class="quote-recalled">原消息已被撤回</span>';
        var qJumpAttr = m.quote.id && !m.quote.is_recalled ? 'onclick="jumpToMsg(\\''+m.quote.id+'\\', event)"' : '';
        quoteHtml = '<div class="quote-box" ' + qJumpAttr + '><div class="q-name">' + getName(m.quote.name ? 'unknown' : 'unknown') + ':</div><div class="q-txt">' + qContent + '</div></div>';
        if (m.quote.name) quoteHtml = '<div class="quote-box" ' + qJumpAttr + '><div class="q-name">' + m.quote.name + ':</div><div class="q-txt">' + qContent + '</div></div>';
    }
    var c = '';
    if (m.content && m.content.startsWith('{"type":"merge_fwd"')) {
        try {
            var fwd = JSON.parse(m.content);
            c = '<div class="fwd-card" onclick="viewFwd(this)" data-fwd-json="' + m.content.replace(/"/g, '&quot;') + '"><div class="fwd-head">' + fwd.title + '</div><div class="fwd-body">';
            fwd.preview.forEach(function (p) { c += '<div class="fwd-row">' + p + '</div>'; });
            c += '</div><div class="fwd-foot">查看' + fwd.list.length + '条转发消息</div></div>';
        } catch (e) { c = '<div class="msg-bub">[转发消息解析失败]</div>'; }
    } else {
        if (m.type === 'sticker') {
            var stickerHtml = '';
            var emoji = m.content;
            var data = useTelegramStickers ? telegramStickerMapping[emoji] : null;

            if (data && data.file) {
                stickerHtml = '<img class="sticker-gif msg-sticker-gif" data-src="/static/telegram_stickers/' + data.file + '" alt="' + emoji + '" title="' + emoji + '" style="width:80px;height:80px;">';
            } else {
                stickerHtml = emojiToImg(emoji);
            }
            c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
        } else if (m.type === 'text' && emojiMapping[m.content]) {
            var emoji = m.content;
            var stickerHtml = emojiToImg(emoji);
            c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
        } else if (m.type === 'file') {
            // 检查是否是P2P传输消息
            if (m.transfer_method === 'p2p') {
                c = renderP2PFileMessage(m);
            } else {
                // 普通文件消息
                if (m.is_img) {
                    c = '<div class="msg-bub transparent-bub"><img class="chat-img" src="/uploads/' + m.server_filename + '" onclick="viewImg(this.src)"></div>';
                }
                else { c = '<div class="msg-bub file-card clickable" onclick="downloadFile(\\'' + m.server_filename + '\\', \\'' + m.filename + '\\')"><div class="file-icon" style="margin-right:10px">📄</div><div><div>' + m.filename + '</div><div style="font-size:10px;opacity:0.7">点击下载</div></div></div>'; }
            }
        } else {
            c = '<div class="msg-bub ' + (m.tmp ? 'sending' : '') + '">' + quoteHtml + m.content + '</div>';
        }
    }

    var readHtml = '<div class="read-stat">未读</div>';
    if (target.type === 'group') readHtml = '';

    var dblClickAttr = (m.from_uid !== me.uid) ? 'ondblclick="doNudge(\\''+m.from_uid+'\\')"' : '';
    div.className = 'msg-row ' + (isMe ? 'me' : '') + ' ' + animClass;
    div.innerHTML = chk + '<div class="msg-inner"><div class="msg-av" style="background:' + u.avatar_bg + '" ' + dblClickAttr + '></div><div><div class="msg-name">' + displayName + '</div>' + c + '</div>' + readHtml + '</div>';

    if (isMulti && !m.is_recalled) { div.onclick = function (e) { toggleSel(m.id, e); }; }
    if (animClass) { setTimeout(function () { div.classList.remove('anim-in-right', 'anim-in-left'); }, 500); }

    return div;
}

function renderChat(forceScroll, animate) {
    if (!target) return;
    var box = document.getElementById('msg-box');
    // 重构：使用 currentChatMsgs 而不是 cache.msgs
    var rel = currentChatMsgs.slice();  // 复制数组
    if (rel.length === 0) { box.innerHTML = '<div class="empty">暂无消息</div>'; return; }
    var emptyEl = box.querySelector('.empty'); if (emptyEl) emptyEl.remove();

    // 优化渲染：使用DocumentFragment批量添加元素减少DOM重排
    var fragment = document.createDocumentFragment();
    var hasNewElements = false;

    // 跟踪已创建的时间戳元素ID，避免在同一个fragment中重复创建
    var createdTimeIds = new Set();

    // 修复：从最后一条已渲染消息的时间戳开始，避免重复显示时间戳
    var lastTime = 0;
    // 直接从DOM中获取最后一条消息的时间戳，避免ID不一致问题
    var lastMsgEl = box.querySelector('.msg-row:last-of-type');
    if (lastMsgEl && lastMsgEl.dataset.timestamp) {
        lastTime = parseFloat(lastMsgEl.dataset.timestamp);
    }

    rel.forEach(m => {
        var divId = 'msg-' + m.id;
        var div = document.getElementById(divId);

        if (m.type === 'system' || m.is_recalled) {
            var sysRow = renderSystemMsg(m);
            if (!div) {
                fragment.appendChild(sysRow);
                hasNewElements = true;
            } else {
                if (div.innerHTML !== sysRow.innerHTML) div.innerHTML = sysRow.innerHTML;
                if (div.className !== sysRow.className) div.className = sysRow.className;
            }
            // 更新lastTime以保持连续性
            lastTime = m.timestamp;
            return;
        }

        var msgTime = m.timestamp;
        var tDivId = 'time-' + m.id;

        // 修复：无论消息是否已渲染，都要检查时间戳是否应该存在
        if (msgTime - lastTime > 300) {
            // 检查DOM和当前fragment中是否已存在时间戳元素
            if (!document.getElementById(tDivId) && !createdTimeIds.has(tDivId)) {
                var tDiv = document.createElement('div');
                tDiv.id = tDivId;
                tDiv.className = 'chat-time';
                tDiv.innerText = formatChatTime(msgTime);

                // 修复：如果消息已存在，直接插入到消息之前；否则添加到fragment
                if (div) {
                    box.insertBefore(tDiv, div);
                } else {
                    fragment.appendChild(tDiv);
                }
                createdTimeIds.add(tDivId);
                hasNewElements = true;
            }
        }
        // 更新lastTime（无论是否显示时间戳）
        lastTime = msgTime;

        if (!div) {
            var u = cache.users[m.from_uid];
            if (!u) u = { name: '?', avatar_bg: '#ccc' };

            var displayName = getName(m.from_uid);
            var isMe = m.from_uid === me.uid;
            var animClass = (visualOn && animate) ? (isMe ? 'anim-in-right' : 'anim-in-left') : '';
            div = document.createElement('div');
            div.id = divId;
            div.dataset.id = m.id;
            div.dataset.timestamp = m.timestamp;  // 添加时间戳属性，用于P2P消息排序 

            var chkCls = selMsgs.has(m.id.toString()) ? 'checked' : '';
            var chk = '<div class="msg-chk ' + chkCls + '" onclick="toggleSel(\\''+m.id+'\\', event)"></div>';

            var quoteHtml = '';
            if (m.quote) {
                var qContent = m.quote.content;
                if (m.quote.is_recalled) qContent = '<span class="quote-recalled">原消息已被撤回</span>';
                var qJumpAttr = m.quote.id && !m.quote.is_recalled ? 'onclick="jumpToMsg(\\''+m.quote.id+'\\', event)"' : '';
                quoteHtml = '<div class="quote-box" ' + qJumpAttr + '><div class="q-name">' + getName(m.quote.name ? 'unknown' : 'unknown') + ':</div><div class="q-txt">' + qContent + '</div></div>';
                if (m.quote.name) quoteHtml = '<div class="quote-box" ' + qJumpAttr + '><div class="q-name">' + m.quote.name + ':</div><div class="q-txt">' + qContent + '</div></div>';
            }
            var c = '';
            if (m.content && m.content.startsWith('{"type":"merge_fwd"')) {
                try {
                    var fwd = JSON.parse(m.content);
                    c = '<div class="fwd-card" onclick="viewFwd(this)" data-fwd-json="' + m.content.replace(/"/g, '&quot;') + '"><div class="fwd-head">' + fwd.title + '</div><div class="fwd-body">';
                    fwd.preview.forEach(function (p) { c += '<div class="fwd-row">' + p + '</div>'; });
                    c += '</div><div class="fwd-foot">查看' + fwd.list.length + '条转发消息</div></div>';
                } catch (e) { c = '<div class="msg-bub">[转发消息解析失败]</div>'; }
            } else {
                if (m.type === 'sticker') {
                    var stickerHtml = '';
                    var emoji = m.content;
                    var data = useTelegramStickers ? telegramStickerMapping[emoji] : null;

                    if (data && data.file) {
                        // 使用Telegram GIF
                        stickerHtml = '<img class="sticker-gif msg-sticker-gif" data-src="/static/telegram_stickers/' + data.file + '" alt="' + emoji + '" title="' + emoji + '" style="width:80px;height:80px;">';
                    } else {
                        // 降级到PNG
                        stickerHtml = emojiToImg(emoji);
                    }
                    c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
                } else if (m.type === 'text' && emojiMapping[m.content]) {
                    // 静态PNG格式的Emoji表情也以大图形式显示
                    var emoji = m.content;
                    var stickerHtml = emojiToImg(emoji);
                    c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
                } else if (m.type === 'file') {
                    if (m.is_img) {
                        c = '<div class="msg-bub transparent-bub"><img class="chat-img" src="/uploads/' + m.server_filename + '" onclick="viewImg(this.src)"></div>';
                    }
                    else { c = '<div class="msg-bub file-card clickable" onclick="downloadFile(\\'' + m.server_filename + '\\', \\'' + m.filename + '\\')"><div class="file-icon" style="margin-right:10px">📄</div><div><div>' + m.filename + '</div><div style="font-size:10px;opacity:0.7">点击下载</div></div></div>'; }
                } else {
                    c = '<div class="msg-bub ' + (m.tmp ? 'sending' : '') + '">' + quoteHtml + m.content + '</div>';
                }
            }

            var readHtml = '<div class="read-stat">未读</div>';
            if (target.type === 'group') readHtml = '';

            var dblClickAttr = (m.from_uid !== me.uid) ? 'ondblclick="doNudge(\\''+m.from_uid+'\\')"' : '';

            div.className = 'msg-row ' + (isMe ? 'me' : '') + ' ' + animClass;
            div.innerHTML = chk + '<div class="msg-inner"><div class="msg-av" style="background:' + u.avatar_bg + '" ' + dblClickAttr + '></div><div><div class="msg-name">' + displayName + '</div>' + c + '</div>' + readHtml + '</div>';

            if (isMulti && !m.is_recalled) { div.onclick = function (e) { toggleSel(m.id, e); }; }
            if (animClass) { setTimeout(function () { div.classList.remove('anim-in-right', 'anim-in-left'); }, 500); }
            fragment.appendChild(div);
            hasNewElements = true;
        } else {
            // 修复：实时更新用户昵称
            var nameEl = div.querySelector('.msg-name');
            var curName = getName(m.from_uid);
            if (nameEl && nameEl.innerText !== curName) nameEl.innerText = curName;

            // 修复：实时更新用户头像
            var avEl = div.querySelector('.msg-av');
            if (avEl) {
                var u = cache.users[m.from_uid];
                if (u && u.avatar_bg) {
                    var currentBg = avEl.style.background;
                    var newBg = u.avatar_bg;
                    // 只有当头像背景发生变化时才更新
                    if (currentBg !== newBg) {
                        avEl.style.background = newBg;
                    }
                }
            }

            if (isMulti && !m.is_recalled) {
                div.onclick = isMulti ? function (e) { toggleSel(m.id, e); } : null;
                var chk = div.querySelector('.msg-chk');
                if (chk) { if (selMsgs.has(m.id.toString())) chk.classList.add('checked'); else chk.classList.remove('checked'); }
            }
        }
    });

    // 批量添加所有新元素，减少DOM重排
    if (hasNewElements) {
        box.appendChild(fragment);
    }

    if (forceScroll) {
        // 强制滚动到底部（用于发送消息等场景）
        scrollToBottomRobust();
    }
    updateReadStatusIndicators();

    // 为新渲染的消息中的GIF启动懒加载观察
    if (gifObserver) {
        box.querySelectorAll('.msg-sticker-gif:not(.observed)').forEach(img => {
            img.classList.add('observed');
            gifObserver.observe(img);
        });
    }
}

/**
 * 渲染新消息（用于sync时增量更新）
 * 只渲染当前聊天中新增的消息，使用DocumentFragment优化性能
 */
function renderNewMessages() {
    if (!target) return;

    const box = document.getElementById('msg-box');
    const fragment = document.createDocumentFragment();
    let hasNewElements = false;
    let lastTime = 0;

    // 跟踪已创建的时间戳元素ID，避免在同一个fragment中重复创建
    const createdTimeIds = new Set();

    // 重构：使用 currentChatMsgs
    const rel = currentChatMsgs.slice();

    // 找到最后一个已渲染的消息的时间戳
    // 修复：使用querySelector确保获取的是消息元素
    const lastRenderedElement = box.querySelector('.msg-row:last-of-type');
    if (lastRenderedElement && lastRenderedElement.dataset.timestamp) {
        lastTime = parseFloat(lastRenderedElement.dataset.timestamp);
    }

    // 只渲染新消息
    rel.forEach(m => {
        const divId = 'msg-' + m.id;
        const div = document.getElementById(divId);

        // 如果已经存在，更新lastTime后跳过
        if (div) {
            lastTime = m.timestamp;
            return;
        }

        // 时间分隔符
        const msgTime = m.timestamp;
        const tDivId = 'time-' + m.id;

        if (msgTime - lastTime > 300) {
            // 修复：同时检查DOM和当前fragment中是否已创建，避免重复创建
            if (!document.getElementById(tDivId) && !createdTimeIds.has(tDivId)) {
                const tDiv = document.createElement('div');
                tDiv.id = tDivId;
                tDiv.className = 'chat-time';
                tDiv.innerText = formatChatTime(msgTime);
                fragment.appendChild(tDiv);
                createdTimeIds.add(tDivId);
                hasNewElements = true;
            }
        }
        // 修复：无论是否创建时间戳，都要更新lastTime
        lastTime = msgTime;

        // 渲染消息
        let msgDiv;
        if (m.type === 'system' || m.is_recalled) {
            msgDiv = renderSystemMsg(m);
        } else {
            msgDiv = renderMessageElement(m, true); // 带动画
        }

        fragment.appendChild(msgDiv);
        hasNewElements = true;
    });

    // 批量添加新元素
    if (hasNewElements) {
        box.appendChild(fragment);
    }

    updateReadStatusIndicators();

    // 为新渲染的GIF启动懒加载观察
    if (gifObserver) {
        box.querySelectorAll('.msg-sticker-gif:not(.observed)').forEach(img => {
            img.classList.add('observed');
            gifObserver.observe(img);
        });
    }
}

/**
 * 跳转到指定消息
 * 如果消息在当前 DOM 中，直接滚动并高亮
 * 如果消息不在，调用 /api/message/context 加载上下文后再跳转
 */
async function jumpToMsg(mid, e) {
    if (e) e.stopPropagation();

    // 第一步：尝试在当前 DOM 中查找
    var el = document.getElementById('msg-' + mid);
    if (el) {
        // 消息已在 DOM 中，直接滚动并高亮
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('highlight');
        setTimeout(function () { el.classList.remove('highlight'); }, 1500);
        return;
    }

    // 第二步：消息不在当前 DOM 中，需要加载上下文
    if (!target) {
        showToast('请先选择聊天');
        return;
    }

    try {
        const response = await fetch('/api/message/context?uid=' + me.uid + '&msg_id=' + mid);

        if (!response.ok) {
            const errData = await response.json();
            if (errData.error === 'Message not found') {
                showToast('原消息已被删除');
            } else {
                showToast('无法加载消息');
            }
            return;
        }

        const data = await response.json();

        if (!data.messages || data.messages.length === 0) {
            showToast('消息不存在');
            return;
        }

        // 第三步：替换当前聊天消息并重新渲染
        // 更新 currentChatMsgs
        currentChatMsgs = data.messages;

        // 更新 minMsgId 和 maxMsgId
        if (currentChatMsgs.length > 0) {
            minMsgId = currentChatMsgs[0].id;
            maxMsgId = currentChatMsgs[currentChatMsgs.length - 1].id;
        }

        // 设置跳转模式状态
        isInJumpMode = true;
        hasNewerMessages = true;  // 默认假设有更新的消息，向下滚动时会通过 API 验证
        isLoadingNewer = false;

        // 更新懒加载状态
        LAZY_LOAD_CONFIG.hasMoreHistory[target.id] = true;  // 假设还有更早的历史
        LAZY_LOAD_CONFIG.oldestMsgId[target.id] = minMsgId;

        // 清空 DOM 并重新渲染
        var box = document.getElementById('msg-box');
        box.innerHTML = '';

        // 渲染所有消息
        renderHistoryMessages(currentChatMsgs, false);

        // 等待渲染完成后滚动到目标消息
        requestAnimationFrame(() => {
            setTimeout(() => {
                var targetEl = document.getElementById('msg-' + mid);
                if (targetEl) {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    targetEl.classList.add('highlight');
                    setTimeout(function () { targetEl.classList.remove('highlight'); }, 1500);
                } else {
                    showToast('跳转失败');
                }
            }, 100);
        });

    } catch (err) {
        logError('Message', '加载消息上下文失败:', err);
        showToast('加载失败，请重试');
    }
}

async function send() {
    var el = document.getElementById('inp-msg'); var t = el.value.trim(); if (!t || !target) return;
    el.value = '';
    // 修复：添加随机数确保临时ID唯一，避免快速连续发送时ID冲突
    var tmpId = Date.now() * 10000 + Math.floor(Math.random() * 10000);
    var qContent = quoteMsg ? (quoteMsg.type === 'file' ? '[文件] ' + quoteMsg.filename : quoteMsg.content) : '';
    if (qContent && qContent.startsWith('{"type":"merge_fwd"')) qContent = '[聊天记录]';
    if (quoteMsg && quoteMsg.is_recalled) qContent = '原消息已被撤回';
    var quoteData = quoteMsg ? { name: (quoteMsg.pseudoName || getName(quoteMsg.from_uid)), content: qContent, id: quoteMsg.id, is_recalled: quoteMsg.is_recalled } : null;
    // 修复：使用秒级时间戳，与服务器保持一致
    var localMsg = { id: tmpId, from_uid: me.uid, to_uid: target.id, type: 'text', content: t, timestamp: Date.now() / 1000, tmp: true, quote: quoteData };
    cancelQuote(); currentChatMsgs.push(localMsg);
    // 修复：使用renderNewMessages而不是renderChat，避免重复渲染
    renderNewMessages();
    scrollToBottomRobust();

    // ========== 修复：获取服务器返回的真实 msg_id 并更新本地消息 ==========
    try {
        const response = await fetch('/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid: me.uid, to_uid: target.id, content: t, quote: quoteData })
        });
        const result = await response.json();

        if (result.msg_id) {
            // 用服务器返回的真实 ID 更新本地临时消息
            // 修复：先尝试通过tmpId查找，如果找不到（可能sync()已经更新了），则通过真实ID查找
            var tmpIdx = currentChatMsgs.findIndex(m => m.id === tmpId);
            if (tmpIdx === -1) {
                // 可能sync()已经更新了ID，尝试通过真实ID查找
                tmpIdx = currentChatMsgs.findIndex(m => m.id === result.msg_id);
            }

            if (tmpIdx !== -1) {
                // 检查是否已经被sync()更新过
                var alreadyUpdated = currentChatMsgs[tmpIdx].id === result.msg_id;

                if (!alreadyUpdated) {
                    currentChatMsgs[tmpIdx].id = result.msg_id;
                    currentChatMsgs[tmpIdx].tmp = false;
                    // 同时更新 DOM 元素的 id
                    var oldEl = document.getElementById('msg-' + tmpId);
                    if (oldEl) {
                        oldEl.id = 'msg-' + result.msg_id;
                        oldEl.dataset.id = result.msg_id;
                        var bub = oldEl.querySelector('.msg-bub');
                        if (bub) bub.classList.remove('sending');
                    }
                    // 修复：更新时间戳元素的ID（如果存在）
                    var oldTimeEl = document.getElementById('time-' + tmpId);
                    if (oldTimeEl) {
                        oldTimeEl.id = 'time-' + result.msg_id;
                    }
                }
                // 更新 maxMsgId
                if (result.msg_id > maxMsgId) {
                    maxMsgId = result.msg_id;
                }
            }
        }
    } catch (e) {
        logError('Message', '发送消息失败:', e);
    }

    // 修复：设置标志，防止在sync()时重新渲染导致时间戳元素被删除
    preventRenderChat = true;

    // 修复：当用户发送消息给自己时，立即标记为已读
    if (target.type === 'private' && target.id === me.uid) {
        // 延迟标记已读，确保消息已同步到服务器并获得真实ID
        if (pollingTimer) clearTimeout(pollingTimer);
        await sync();
        // 同步完成后立即标记已读
        setTimeout(() => {
            markRead();
            updateReadStatusIndicators();
        }, 100);
    } else {
        if (pollingTimer) clearTimeout(pollingTimer);
        sync();
    }

    // 修复：在sync()完成后才允许重新渲染
    setTimeout(() => {
        preventRenderChat = false;
    }, 500);  // 500ms后允许重新渲染
}

function openProfile(uid) {
    var u = cache.users[uid];
    if (!u) return;
    profileTargetUid = uid;
    document.getElementById('pf-av').style.background = u.avatar_bg;
    document.getElementById('pf-nick').innerText = u.name;
    document.getElementById('pf-uid').innerText = "UID: " + uid;
    document.getElementById('pf-remark').value = cache.remarks[uid] || "";
    document.getElementById('md-profile').style.display = 'flex';
    closeCtx();
    closeListCtx();
}

async function saveRemark() {
    var val = document.getElementById('pf-remark').value.trim();
    if (!profileTargetUid) return;
    if (!val) delete cache.remarks[profileTargetUid];
    else cache.remarks[profileTargetUid] = val;
    if (target) {
        if (target.type === 'private' && target.id === profileTargetUid) {
            document.getElementById('chat-t').innerText = getName(profileTargetUid);
        }
        renderChat(false, false);
    }
    updateListUI();
    updateContactUI();
    closeMd('md-profile');
    await fetch('/set_remark', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid: me.uid, target_uid: profileTargetUid, remark: val }) });
}

async function doNudge(targetUid) {
    if (!targetUid || targetUid === me.uid) return;
    showToast("戳了一下 " + getName(targetUid));
    var groupId = (target.type === 'group') ? target.id : null;
    await fetch('/nudge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: me.uid, target_uid: targetUid, group_id: groupId })
    });
    sync();
}

function setupContextMenu() { document.getElementById('msg-box').addEventListener('contextmenu', function (e) { handleContextMenu(e, 'main'); }); document.getElementById('fwd-content').addEventListener('contextmenu', function (e) { handleContextMenu(e, 'fwd'); }); document.addEventListener('click', function () { closeCtx(); }); }
function handleContextMenu(e, mode) {
    if (isMulti && mode === 'main') return;
    var row = e.target.closest(mode === 'main' ? '.msg-row' : '.fwd-item'); if (!row) return;
    if (mode === 'main') { if (row.classList.contains('sys')) return; var mid = row.dataset.id; if (!mid) return; ctxMsg = findMsgById(currentChatMsgs, mid); ctxFwdData = null; }
    else { ctxMsg = null; ctxFwdData = { content: row.dataset.content, type: row.dataset.type, filename: row.dataset.filename, sender: row.dataset.sender, id: row.id.replace('fwd-msg-', ''), quote: JSON.parse(row.dataset.quote || 'null'), is_recalled: row.dataset.isrecalled === 'true' }; }
    if (!ctxMsg && !ctxFwdData) return;
    e.preventDefault(); e.stopPropagation();
    var menu = document.getElementById('ctx-menu'); var recallBtn = document.getElementById('ctx-recall'); var recallLine = document.getElementById('ctx-recall-line'); var multiBtn = document.getElementById('ctx-multi'); var fwdBtn = document.getElementById('ctx-fwd'); var quoteBtn = document.getElementById('ctx-quote'); var rmkBtn = document.getElementById('ctx-remark');
    if (mode === 'fwd') { recallBtn.style.display = 'none'; recallLine.style.display = 'none'; multiBtn.style.display = 'none'; fwdBtn.style.display = 'flex'; quoteBtn.style.display = 'flex'; rmkBtn.style.display = 'none'; }
    else {
        multiBtn.style.display = 'flex'; fwdBtn.style.display = 'flex'; quoteBtn.style.display = 'flex';
        if (ctxMsg.from_uid !== me.uid && ctxMsg.from_uid !== 'system') rmkBtn.style.display = 'flex'; else rmkBtn.style.display = 'none';
        var isMe = ctxMsg.from_uid === me.uid; var isFresh = (Date.now() / 1000 - ctxMsg.timestamp) < 120; if (isMe && !ctxMsg.is_recalled && isFresh) { recallBtn.style.display = 'flex'; recallLine.style.display = 'block'; } else { recallBtn.style.display = 'none'; recallLine.style.display = 'none'; }
    }
    var x = e.clientX; var y = e.clientY; var w = menu.offsetWidth || 140; var h = menu.offsetHeight || 200; if (x + w > window.innerWidth) x = x - w; if (y + h > window.innerHeight) y = y - h; menu.style.left = x + 'px'; menu.style.top = y + 'px'; menu.style.display = 'flex';
}
function closeCtx() { document.getElementById('ctx-menu').style.display = 'none'; }
function menuAction(act) {
    closeCtx(); var item = ctxMsg || ctxFwdData; if (!item) return;
    var content = item.content; var type = item.type; var filename = item.filename;
    if (act === 'copy') { if (content && content.startsWith('{"type":"merge_fwd"')) return showToast('合并转发不支持直接复制，请点开查看'); copyToClip(type === 'file' ? filename : content); }
    else if (act === 'forward') { if (ctxMsg) { selMsgs.clear(); selMsgs.add(ctxMsg.id.toString()); openForwardPicker('seq'); } else { var txt = type === 'file' ? '[文件] ' + filename : content; openSimpleForwardPicker(txt); } }
    else if (act === 'multi') enterMulti(ctxMsg ? ctxMsg.id : null);
    else if (act === 'quote') { if (ctxMsg) startQuote(ctxMsg); else { startQuote({ from_uid: 'unknown', pseudoName: item.sender || '转发消息', type: item.type, filename: item.filename, content: item.content, id: item.id, quote: item.quote, is_recalled: item.is_recalled }); } }
    else if (act === 'recall') {
        // ========== 使用统一的消息撤回处理框架 ==========
        const msgId = ctxMsg.id;
        fetch('/recall', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid: me.uid, msg_id: msgId }) })
            .then(r => r.json())
            .then(d => {
                if (d.error) {
                    alert(d.error);
                } else {
                    // 使用统一的撤回处理函数，确保数据和DOM同步更新
                    handleMessageRecall(msgId);
                    // 后台同步以确保一致性
                    sync();
                }
            });
    }
    else if (act === 'remark') { openProfile(ctxMsg.from_uid); }
}
function copyToClip(txt) { var t = document.createElement("textarea"); t.value = txt; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); showToast('已复制'); }
function startQuote(msg) { quoteMsg = msg; var name = msg.pseudoName || getName(msg.from_uid); var txt = msg.type === 'file' ? '[文件] ' + msg.filename : msg.content; if (txt && txt.startsWith('{"type":"merge_fwd"')) txt = '[聊天记录]'; if (msg.is_recalled) txt = '<span class="quote-recalled">原消息已被撤回</span>'; document.getElementById('reply-content').innerHTML = "回复 " + name + ": " + txt; document.getElementById('reply-bar').style.display = 'flex'; document.getElementById('inp-msg').focus(); }
function cancelQuote() { quoteMsg = null; document.getElementById('reply-bar').style.display = 'none'; }
function enterMulti(initialId) { isMulti = true; document.body.classList.add('multi-mode'); selMsgs.clear(); if (initialId) selMsgs.add(initialId.toString()); renderChat(false); }
function exitMulti() { isMulti = false; document.body.classList.remove('multi-mode'); selMsgs.clear(); renderChat(false); }
function toggleSel(id, e) { if (!isMulti) return; if (e) e.stopPropagation(); id = id.toString(); if (selMsgs.has(id)) selMsgs.delete(id); else selMsgs.add(id); renderChat(false); }
function multiAction(act) { if (selMsgs.size === 0) return alert('请至少选择一条消息'); if (act === 'copy') { var txt = ""; var ids = Array.from(selMsgs).sort(); ids.forEach(mid => { var m = findMsgById(currentChatMsgs, mid); if (m) txt += '[' + getName(m.from_uid) + ']: ' + m.content + '\\n'; }); copyToClip(txt); exitMulti(); } else openForwardPicker(act); }

let simpleFwdContent = null;
function openSimpleForwardPicker(content) { simpleFwdContent = content; fwdMode = 'simple'; renderFwdPickerUI(); }
function openForwardPicker(mode) { fwdMode = mode; renderFwdPickerUI(); }
function renderFwdPickerUI() { var html = ''; for (var gid in cache.groups) html += '<div class="list-item clickable" onclick="selFwdTarget(this,\\''+gid+'\\',\\'group\\')"><div class="item-av" style="background:#007aff">' + cache.groups[gid].name[0] + '</div><div class="item-t">' + cache.groups[gid].name + '</div></div>'; for (var uid in cache.users) if (uid !== me.uid) html += '<div class="list-item clickable" onclick="selFwdTarget(this,\\''+uid+'\\',\\'private\\')"><div class="item-av" style="background:' + cache.users[uid].avatar_bg + '"></div><div class="item-t">' + getName(uid) + '</div></div>'; document.getElementById('picker-list').innerHTML = html; document.getElementById('md-picker').style.display = 'flex'; }
let fwdTarget = null;
function selFwdTarget(el, id, type) { var prev = document.querySelector('#picker-list .active'); if (prev) prev.classList.remove('active'); el.classList.add('active'); fwdTarget = { id: id, type: type }; }
async function submitForward() {
    if (!fwdTarget) return;

    // 辅助函数：发送消息并处理本地渲染
    async function sendAndRenderLocally(content, type) {
        var tmpId = Date.now() * 10000 + Math.floor(Math.random() * 1000);
        var isCurrentChat = target && (
            (fwdTarget.type === 'group' && fwdTarget.id === target.id) ||
            (fwdTarget.type === 'private' && fwdTarget.id === target.id)
        );

        // 如果转发目标是当前聊天，创建本地临时消息并立即渲染
        if (isCurrentChat) {
            var localMsg = {
                id: tmpId,
                from_uid: me.uid,
                to_uid: fwdTarget.id,
                type: type || 'text',
                content: content,
                timestamp: Date.now() / 1000,
                tmp: true
            };
            currentChatMsgs.push(localMsg);
            renderNewMessages();
            // 滚动到底部以显示新消息
            scrollToBottomRobust();
        }

        // 发送到服务器
        try {
            const response = await fetch('/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid: me.uid, to_uid: fwdTarget.id, content: content })
            });
            const result = await response.json();

            // 用服务器返回的真实 ID 更新本地临时消息
            if (result.msg_id && isCurrentChat) {
                var tmpIdx = currentChatMsgs.findIndex(m => m.id === tmpId);
                if (tmpIdx !== -1) {
                    currentChatMsgs[tmpIdx].id = result.msg_id;
                    currentChatMsgs[tmpIdx].tmp = false;
                    var oldEl = document.getElementById('msg-' + tmpId);
                    if (oldEl) {
                        oldEl.id = 'msg-' + result.msg_id;
                        oldEl.dataset.id = result.msg_id;
                        var bub = oldEl.querySelector('.msg-bub');
                        if (bub) bub.classList.remove('sending');
                    }
                    // 修复：更新时间戳元素的ID（如果存在）
                    var oldTimeEl = document.getElementById('time-' + tmpId);
                    if (oldTimeEl) {
                        oldTimeEl.id = 'time-' + result.msg_id;
                    }
                    if (result.msg_id > maxMsgId) {
                        maxMsgId = result.msg_id;
                    }
                }
            }
        } catch (e) {
            logError('Message', '转发消息失败:', e);
        }
    }

    if (fwdMode === 'simple') {
        await sendAndRenderLocally(simpleFwdContent, 'text');
    } else {
        if (selMsgs.size === 0) return;
        var ids = Array.from(selMsgs).sort();

        if (fwdMode === 'seq') {
            // 逐条转发 - SQLite 修复：使用安全 ID 比较函数
            for (var mid of ids) {
                var m = findMsgById(currentChatMsgs, mid);
                if (m) {
                    await sendAndRenderLocally(m.content, m.type);
                }
            }
        } else {
            // 合并转发
            var preview = []; var fullList = [];
            var title = "群聊聊天记录";
            if (target && target.type !== 'group') {
                title = me.name + "和" + target.name + "的聊天记录";
            }
            ids.forEach(function (mid, idx) {
                // SQLite 修复：使用安全 ID 比较函数
                var m = findMsgById(currentChatMsgs, mid);
                if (m) {
                    var sender = getName(m.from_uid);
                    var txt = m.type === 'file' ? '[文件] ' + m.filename : m.content;
                    if (idx < 3) preview.push(sender + ": " + txt);
                    fullList.push({
                        sender: sender,
                        content: m.content,
                        type: m.type,
                        filename: m.filename,
                        server_filename: m.server_filename,
                        time: m.timestamp,
                        id: m.id,
                        quote: m.quote
                    });
                }
            });
            var payload = JSON.stringify({ type: 'merge_fwd', title: title, preview: preview, list: fullList });
            await sendAndRenderLocally(payload, 'text');
        }
    }

    closeMd('md-picker');
    if (isMulti) exitMulti();
    showToast('转发成功');
    sync();
}
function closeMd(id) { document.getElementById(id).style.display = 'none'; fwdTarget = null; }

function viewFwd(el) {
    var jsonStr = el.dataset.fwdJson; if (!jsonStr) return;
    try {
        var fwd = JSON.parse(jsonStr);
        var isInModal = el.closest('#fwd-content');
        if (!isInModal) { fwdStack = [fwd]; } else { fwdStack.push(fwd); }
        renderFwdList(fwd); document.getElementById('md-fwd-detail').style.display = 'flex'; updateFwdNav();
    } catch (e) { alert('无法查看详情'); }
}
function popFwdStack() { if (fwdStack.length > 1) { fwdStack.pop(); var prev = fwdStack[fwdStack.length - 1]; renderFwdList(prev); updateFwdNav(); } }
function updateFwdNav() { var backBtn = document.getElementById('fwd-back'); if (fwdStack.length > 1) backBtn.style.display = 'block'; else backBtn.style.display = 'none'; }
function closeFwdMd() { closeMd('md-fwd-detail'); fwdStack = []; }

function renderFwdList(fwd) {
    var list = fwd.list || []; var html = ''; document.getElementById('fwd-title').innerText = fwd.title || '聊天记录';
    list.forEach(function (item) {
        var d = new Date(item.time * 1000); var timeStr = d.getHours() + ':' + (d.getMinutes() < 10 ? '0' : '') + d.getMinutes();
        var contentHtml = item.content; var clickAttr = ''; var styleAttr = '';
        if (item.content && item.content.startsWith('{"type":"merge_fwd"')) {
            try {
                var subFwd = JSON.parse(item.content);
                contentHtml = '<div class="fwd-card" style="border:1px solid #eee;"><div class="fwd-head">' + subFwd.title + '</div><div class="fwd-body" style="font-size:11px;color:#aaa">';
                subFwd.preview.forEach(function (p) { contentHtml += '<div class="fwd-row">' + p + '</div>'; }); contentHtml += '</div></div>';
                var subJson = item.content.replace(/"/g, '&quot;'); clickAttr = 'onclick="viewFwd(this)" data-fwd-json="' + subJson + '"'; styleAttr = 'cursor:pointer;';
            } catch (e) { }
        } else if (item.type === 'file') { contentHtml = '[文件] ' + item.filename; }
        var quoteHtml = '';
        if (item.quote) { var qText = item.quote.content; if (item.quote.is_recalled) qText = '<span class="quote-recalled">原消息已被撤回</span>'; quoteHtml = '<div class="quote-box"><div class="q-name">' + item.quote.name + ':</div><div class="q-txt">' + qText + '</div></div>'; }
        html += '<div class="fwd-item" id="fwd-msg-' + item.id + '" ' + clickAttr + ' data-content="' + (item.content || '').replace(/"/g, '&quot;') + '" data-type="' + item.type + '" data-filename="' + (item.filename || '') + '" data-sender="' + (item.sender || '') + '" data-quote="' + (item.quote ? JSON.stringify(item.quote).replace(/"/g, '&quot;') : '') + '" data-isrecalled="' + (item.is_recalled || false) + '" style="margin-bottom:10px;border-bottom:1px solid rgba(0,0,0,0.05);padding-bottom:5px;' + styleAttr + '">' + '<div style="font-size:12px;color:#888;display:flex;justify-content:space-between;"><span>' + item.sender + '</span><span>' + timeStr + '</span></div>' + quoteHtml + '<div style="font-size:14px;margin-top:2px;">' + contentHtml + '</div></div>';
    });
    document.getElementById('fwd-content').innerHTML = html;
}
function jumpToFwdMsg(mid, e) { if (e) e.stopPropagation(); showToast('合并记录内暂不支持跳转'); }
function upFiles(files) {
    if (!target || files.length === 0) return;

    // 计算总大小
    var totalSize = Array.from(files).reduce((sum, f) => sum + f.size, 0);
    var p2pThreshold = 500 * 1024 * 1024; // 500MB
    var useP2P = totalSize > p2pThreshold;
    var supportsWebRTC = typeof RTCPeerConnection !== 'undefined' && typeof RTCDataChannel !== 'undefined';

    // 检查群聊P2P传输限制
    if (useP2P && supportsWebRTC && target.type === 'group') {
        // 群聊不支持P2P传输，提示用户使用私聊
        var fileSizeStr = formatFileSize(totalSize);
        showToast('大文件P2P传输仅支持私聊\\n\\n文件大小: ' + fileSizeStr + '\\n请在私聊中发送此文件', 5000);
        logWarn('P2P', 'Group chat P2P transfer not supported. File size:', fileSizeStr);
        return; // 阻止上传
    }

    // 只在使用服务器上传时显示上传面板
    var panel = document.getElementById('upload-panel');
    var list = document.getElementById('up-list');
    if (!useP2P || !supportsWebRTC) {
        panel.style.display = 'flex';
    }

    Array.from(files).forEach(f => {
        var task = {
            id: 'up-' + Date.now() + Math.random().toString(36).substr(2, 5),
            file: f,
            to_uid: target.id,
            progress: 0,
            status: 'pending',
            useP2P: useP2P && supportsWebRTC
        };
        uploadQueue.push(task);

        // P2P传输不显示在上传面板中
        if (useP2P && supportsWebRTC) {
            logDebug('Upload', 'File will use P2P transfer:', f.name);
            return; // 跳过UI创建，但任务已添加到队列
        }

        // 只有服务器上传才创建上传面板项目
        // 格式化文件大小
        var sizeStr = formatFileSize(f.size);

        // 服务器上传
        var methodStr = '服务器上传';
        var methodClass = 'method-server';

        var item = document.createElement('div');
        item.className = 'up-item';
        item.id = task.id;
        item.style.position = 'relative';
        item.innerHTML = '<div class="up-status">⌛</div>' +
            '<div class="up-name">' + f.name + '</div>' +
            '<div class="up-info">' +
            '<span class="up-size">' + sizeStr + '</span>' +
            '<span class="up-method ' + methodClass + '">' + methodStr + '</span>' +
            '</div>' +
            '<div class="up-progress"><div class="up-bar"></div></div>';
        list.appendChild(item);
    });
    document.querySelector('input[type=file]').value = ''; processQueue();
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    var k = 1024;
    var sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
}

function formatSpeed(bytesPerSecond) {
    if (bytesPerSecond === 0) return '0 B/s';
    var k = 1024;
    var sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
    var i = Math.floor(Math.log(bytesPerSecond) / Math.log(k));
    return (bytesPerSecond / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
}

// P2P传输操作函数
async function acceptP2PTransfer(sessionId, event) {
    if (event) event.stopPropagation();
    logInfo('P2P', 'Accepting transfer:', sessionId);

    if (!window.p2pManager) {
        alert('P2P系统未就绪');
        return;
    }

    try {
        await window.p2pManager.acceptTransfer(sessionId);
        logInfo('P2P', 'Transfer accepted');
    } catch (error) {
        logError('P2P', 'Failed to accept transfer:', error);
        alert('接收失败：' + error.message);
    }
}

async function rejectP2PTransfer(sessionId, event) {
    if (event) event.stopPropagation();
    logInfo('P2P', 'Rejecting transfer:', sessionId);

    try {
        // 更新消息状态为rejected
        await fetch('/api/p2p/messages/' + sessionId + '/status', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'rejected' })
        });

        // 更新本地消息
        var msgIndex = currentChatMsgs.findIndex(m => m.p2p_session_id === sessionId);
        if (msgIndex !== -1) {
            currentChatMsgs[msgIndex].p2p_status = 'rejected';
            updateMessageInDOM(currentChatMsgs[msgIndex].id, currentChatMsgs[msgIndex], true);
        }

        logInfo('P2P', 'Transfer rejected');
    } catch (error) {
        logError('P2P', 'Failed to reject transfer:', error);
    }
}

async function cancelP2PTransfer(sessionId, event) {
    if (event) event.stopPropagation();
    logInfo('P2P', 'Cancelling transfer:', sessionId);

    if (window.p2pManager) {
        try {
            await window.p2pManager.cancelTransfer(sessionId);
        } catch (error) {
            logError('P2P', 'Failed to cancel via p2pManager:', error);
        }
    }

    try {
        // 更新消息状态为cancelled
        await fetch('/api/p2p/messages/' + sessionId + '/status', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: 'cancelled' })
        });

        // 更新本地消息
        var msgIndex = currentChatMsgs.findIndex(m => m.p2p_session_id === sessionId);
        if (msgIndex !== -1) {
            currentChatMsgs[msgIndex].p2p_status = 'cancelled';
            updateMessageInDOM(currentChatMsgs[msgIndex].id, currentChatMsgs[msgIndex], true);
        }

        logInfo('P2P', 'Transfer cancelled');
    } catch (error) {
        logError('P2P', 'Failed to cancel transfer:', error);
    }
}

function closeUploadPanel() { document.getElementById('upload-panel').style.display = 'none'; var list = document.getElementById('up-list'); Array.from(list.children).forEach(el => { var task = uploadQueue.find(t => t.id === el.id); if (!task || task.status === 'done' || task.status === 'error') el.remove(); }); }
async function processQueue() {
    if (isUploading || uploadQueue.length === 0) return;
    var task = uploadQueue.find(t => t.status === 'pending');
    if (!task) {
        if (uploadQueue.every(t => t.status !== 'pending' && t.status !== 'uploading')) {
            if (pollingTimer) clearTimeout(pollingTimer);
            sync();
        }
        return;
    }

    isUploading = true;
    task.status = 'uploading';

    // 检查是否使用P2P传输
    if (task.useP2P && p2pManager) {
        logInfo('P2P', 'Starting P2P transfer for file:', task.file.name, 'size:', task.file.size);
        logDebug('P2P', 'Target:', task.to_uid, 'Type:', target.type);
        try {
            // 确定聊天类型
            var chatType = target.type === 'group' ? 'group' : 'private';
            logDebug('P2P', 'Chat type:', chatType);

            // 发起P2P传输
            logDebug('P2P', 'Calling initiateTransfer...');
            const result = await p2pManager.initiateTransfer(task.file, task.to_uid, chatType);
            logInfo('P2P', 'Transfer initiated:', result);

            // 添加到传输跟踪Map
            if (result.sessionId) {
                p2pTransfers.set(result.sessionId, {
                    sessionId: result.sessionId,
                    filename: task.file.name,
                    filesize: task.file.size,
                    peer: task.to_uid,
                    role: 'sender',
                    status: result.status || 'pending',
                    progress: 0,
                    speed: 0,
                    chatType: chatType
                });
                logDebug('P2P', 'Added to p2pTransfers:', result.sessionId);

                // 使用新的消息化P2P系统创建传输消息
                if (window.p2pMessageIntegration) {
                    try {
                        // 初始化MessageIntegration（如果还没初始化）
                        // chatId应该是当前聊天的ID，对于私聊就是target.uid
                        if (!window.p2pMessageIntegration.currentUserId) {
                            window.p2pMessageIntegration.initialize(me.uid, task.to_uid);
                        }

                        // 创建传输消息
                        await window.p2pMessageIntegration.createTransferMessage(
                            {
                                name: task.file.name,
                                size: task.file.size,
                                type: task.file.type || 'application/octet-stream'
                            },
                            result.sessionId,
                            task.to_uid,
                            me.name || '我'
                        );
                        logDebug('P2P', 'Transfer message created in chat');
                    } catch (error) {
                        logError('P2P', 'Failed to create transfer message:', error);
                        // 即使消息创建失败，P2P传输仍然继续
                    }
                } else {
                    logWarn('P2P', 'MessageIntegration not available, falling back to old UI');
                    // 回退到旧的P2P面板（如果新系统不可用）
                    if (typeof openP2PPanel === 'function') {
                        openP2PPanel();
                    }
                }
            }

            // P2P传输已启动，更新UI
            var statEl = document.querySelector('#' + task.id + ' .up-status');
            if (statEl) statEl.innerText = '🔄';

            // 标记为完成（P2P传输在后台进行）
            task.status = 'done';
            isUploading = false;
            processQueue();

        } catch (error) {
            logError('P2P', 'Failed to initiate P2P transfer:', error);
            // P2P失败，回退到传统上传（如果文件<=500MB）
            if (task.file.size <= 500 * 1024 * 1024) {
                logInfo('P2P', 'Falling back to traditional upload');
                task.useP2P = false;
                task.status = 'pending';
                isUploading = false;
                processQueue();
            } else {
                // 文件太大，无法回退
                task.status = 'error';
                var statEl = document.querySelector('#' + task.id + ' .up-status');
                if (statEl) statEl.innerText = '❌';
                showToast('P2P传输失败，文件过大无法使用服务器上传');
                isUploading = false;
                processQueue();
            }
        }
    } else {
        // 传统HTTP上传
        var fd = new FormData();
        fd.append('file', task.file);
        fd.append('uid', me.uid);
        fd.append('to_uid', task.to_uid);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload', true);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                var percent = (e.loaded / e.total) * 100;
                var bar = document.querySelector('#' + task.id + ' .up-bar');
                if (bar) bar.style.width = percent + '%';

                // 当上传完成时，显示"处理中"状态
                if (percent >= 100) {
                    var statEl = document.querySelector('#' + task.id + ' .up-status');
                    if (statEl) statEl.innerText = '⚙️';
                    var nameEl = document.querySelector('#' + task.id + ' .up-name');
                    if (nameEl && !nameEl.dataset.originalText) {
                        nameEl.dataset.originalText = nameEl.innerText;
                        nameEl.innerText = nameEl.innerText + ' (处理中...)';
                    }
                }
            }
        };
        xhr.onload = () => {
            isUploading = false;
            var statEl = document.querySelector('#' + task.id + ' .up-status');
            var nameEl = document.querySelector('#' + task.id + ' .up-name');

            // 恢复原始文件名
            if (nameEl && nameEl.dataset.originalText) {
                nameEl.innerText = nameEl.dataset.originalText;
                delete nameEl.dataset.originalText;
            }

            if (xhr.status === 200) {
                task.status = 'done';
                if (statEl) statEl.innerText = '✅';

                // 立即同步消息，让文件消息快速显示在聊天界面
                if (pollingTimer) clearTimeout(pollingTimer);
                sync();
            } else {
                task.status = 'error';
                if (statEl) statEl.innerText = '❌';
            }
            processQueue();
        };
        xhr.onerror = () => {
            isUploading = false;
            task.status = 'error';
            var statEl = document.querySelector('#' + task.id + ' .up-status');
            if (statEl) statEl.innerText = '❌';

            // 恢复原始文件名
            var nameEl = document.querySelector('#' + task.id + ' .up-name');
            if (nameEl && nameEl.dataset.originalText) {
                nameEl.innerText = nameEl.dataset.originalText;
                delete nameEl.dataset.originalText;
            }

            processQueue();
        };
        xhr.send(fd);
    }
}
function tab(t) { ['msg', 'con', 'file'].forEach(x => document.getElementById('tab-' + x).style.display = 'none'); document.getElementById('tab-' + t).style.display = 'flex'; document.querySelectorAll('.nav-btn').forEach(e => e.classList.remove('active')); var navBtn = document.getElementById('nav-' + t); if (navBtn) navBtn.classList.add('active'); document.querySelectorAll('.m-nav-item').forEach(e => e.classList.remove('active')); var mNavBtn = document.getElementById('mn-' + t); if (mNavBtn) mNavBtn.classList.add('active'); if (t === 'file') loadFiles(); }
// 文件列表状态管理
var fileListState = {
    files: [],
    hasMore: false,
    loading: false,
    searchKeyword: '',
    lastFileId: null,
    hasPinnedContent: false
};

async function checkPinnedFolder() {
    try {
        const r = await fetch('/api/pinned_files/check');
        const data = await r.json();
        fileListState.hasPinnedContent = data.has_content || false;
    } catch (error) {
        logError('File', '检查置顶文件夹失败:', error);
        fileListState.hasPinnedContent = false;
    }
}

async function loadFiles(reset = true) {
    if (reset) {
        fileListState.files = [];
        fileListState.lastFileId = null;
        fileListState.searchKeyword = '';
        document.getElementById('file-search-input').value = '';
        // 检查置顶文件夹
        await checkPinnedFolder();
    }

    if (fileListState.loading) return;
    fileListState.loading = true;

    try {
        let url = '/api/files?uid=' + me.uid;
        if (fileListState.lastFileId) {
            url += '&before_id=' + fileListState.lastFileId;
        }
        if (fileListState.searchKeyword) {
            url += '&search=' + encodeURIComponent(fileListState.searchKeyword);
        }

        const r = await fetch(url);
        const data = await r.json();

        // 处理新旧API响应格式
        const files = data.files || data;
        fileListState.hasMore = data.has_more || false;

        if (reset) {
            fileListState.files = files;
        } else {
            fileListState.files = fileListState.files.concat(files);
        }

        // 更新lastFileId用于下次懒加载
        if (files.length > 0) {
            fileListState.lastFileId = files[files.length - 1].id;
        }

        renderFileList();
    } catch (error) {
        logError('File', '加载文件列表失败:', error);
        showToast('加载文件列表失败');
    } finally {
        fileListState.loading = false;
    }
}

function renderFileList() {
    const container = document.getElementById('ls-file');
    let h = '';

    // 添加置顶文件夹（仅在非搜索模式下且有内容时显示）
    if (!fileListState.searchKeyword && fileListState.hasPinnedContent) {
        h += '<div class="list-item clickable" onclick="openPinnedFolder()">';
        h += '<div class="item-av" style="background:#eee;color:#333">📌</div>';
        h += '<div class="item-body"><div class="item-t">置顶文件</div></div>';
        h += '</div>';
    }

    if (fileListState.files.length === 0) {
        h += '<div class="empty">' + (fileListState.searchKeyword ? '未找到匹配的文件' : '暂无文件') + '</div>';
    } else {
        fileListState.files.forEach(f => {
            h += '<div class="list-item clickable" onclick="downloadFile(\\'' + f.name + '\\', \\'' + f.display_name + '\\')"><div class="item-av" style="background:#eee;color:#333">📄</div><div class="item-body"><div class="item-t">' + f.display_name + '</div></div></div>';
        });

        // 添加加载更多指示器或结束提示
        if (fileListState.hasMore) {
            h += '<div id="file-load-more" style="text-align:center; padding:15px; color:var(--text-sub); font-size:13px;">滚动加载更多...</div>';
        } else if (fileListState.files.length > 0) {
            h += '<div style="text-align:center; padding:15px; color:var(--text-sub); font-size:13px;">没有更多文件了</div>';
        }
    }

    container.innerHTML = h;
}

function handleFileListScroll() {
    const container = document.getElementById('ls-file');
    const scrollTop = container.scrollTop;
    const scrollHeight = container.scrollHeight;
    const clientHeight = container.clientHeight;

    // 当滚动到底部附近时加载更多
    if (scrollHeight - scrollTop - clientHeight < 100 && fileListState.hasMore && !fileListState.loading) {
        loadFiles(false);
    }
}

async function searchFiles() {
    const keyword = document.getElementById('file-search-input').value.trim();
    fileListState.searchKeyword = keyword;
    fileListState.files = [];
    fileListState.lastFileId = null;
    await loadFiles(false);
}

function downloadFile(serverFilename, displayName) {
    // 创建一个隐藏的 <a> 标签来触发下载
    const link = document.createElement('a');
    link.href = '/uploads/' + serverFilename;
    link.download = displayName || serverFilename;  // 使用显示文件名作为下载文件名
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// 置顶文件夹相关功能
let pinnedFolderState = {
    currentPath: '',
    pathStack: []  // 用于面包屑导航
};

async function openPinnedFolder(path = '') {
    try {
        let url = '/api/pinned_files';
        if (path) {
            url += '?path=' + encodeURIComponent(path);
        }

        const r = await fetch(url);
        if (!r.ok) {
            showToast('加载置顶文件失败');
            return;
        }

        const data = await r.json();
        pinnedFolderState.currentPath = data.current_path || '';

        renderPinnedFolder(data);
        document.getElementById('md-pinned').style.display = 'flex';
    } catch (error) {
        logError('File', '加载置顶文件夹失败:', error);
        showToast('加载置顶文件夹失败');
    }
}

function renderPinnedFolder(data) {
    let h = '';

    // 面包屑导航
    h += '<div style="padding:10px 15px; border-bottom:1px solid rgba(0,0,0,0.1);">';
    h += '<div style="font-size:13px; color:var(--text-sub);">';
    h += '<span class="clickable" onclick="openPinnedFolder()" style="color:var(--accent);">置顶文件</span>';

    if (pinnedFolderState.currentPath) {
        const pathParts = pinnedFolderState.currentPath.split('/');
        let accumulatedPath = '';
        pathParts.forEach((part, index) => {
            accumulatedPath += (index > 0 ? '/' : '') + part;
            const currentAccPath = accumulatedPath;
            h += ' / ';
            h += '<span class="clickable" onclick="openPinnedFolder(\\'' + currentAccPath + '\\')" style="color:var(--accent);">' + part + '</span>';
        });
    }
    h += '</div></div>';

    // 文件列表容器
    h += '<div style="flex:1; overflow-y:auto;">';

    // 显示文件夹
    if (data.folders && data.folders.length > 0) {
        data.folders.forEach(folder => {
            h += '<div class="list-item clickable" onclick="openPinnedFolder(\\'' + folder.path + '\\')">';
            h += '<div class="item-av" style="background:#eee;color:#333">📁</div>';
            h += '<div class="item-body"><div class="item-t">' + folder.name + '</div></div>';
            h += '</div>';
        });
    }

    // 显示文件
    if (data.files && data.files.length > 0) {
        data.files.forEach(file => {
            const sizeStr = formatFileSize(file.size);
            h += '<div class="list-item clickable" onclick="downloadPinnedFile(\\'' + file.path + '\\', \\'' + file.name + '\\')">';
            h += '<div class="item-av" style="background:#eee;color:#333">📄</div>';
            h += '<div class="item-body"><div class="item-t">' + file.name + '</div></div>';
            h += '</div>';
        });
    }

    // 空状态
    if ((!data.folders || data.folders.length === 0) && (!data.files || data.files.length === 0)) {
        h += '<div class="empty">此文件夹为空</div>';
    }

    h += '</div>';

    document.getElementById('pinned-content').innerHTML = h;
}

function downloadPinnedFile(path, filename) {
    const link = document.createElement('a');
    link.href = '/pinned/' + path;
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
}
function renderUserSelect(containerId) { selUids.clear(); let h = ''; var currentMembers = (containerId === 'invite-list' && target && cache.groups[target.id]) ? cache.groups[target.id].members : []; for (var uid in cache.users) { if (uid !== me.uid && cache.users[uid].status === 'online' && !currentMembers.includes(uid)) { var u = cache.users[uid]; h += '<div class="user-row clickable" onclick="tog(this,\\''+uid+'\\')"><div class="item-av" style="background:' + u.avatar_bg + ';width:30px;height:30px;"></div><div class="item-body">' + getName(uid) + '</div><div class="chk" style="display:none;color:var(--accent)">✓</div></div>'; } } document.getElementById(containerId).innerHTML = h || '<div class="empty">无其他在线好友</div>'; }
function openCreate() { renderUserSelect('create-list'); document.getElementById('md-create').style.display = 'flex'; }
function openInvite() { renderUserSelect('invite-list'); document.getElementById('md-invite').style.display = 'flex'; closeMd('md-manage'); }
function tog(el, uid) { if (selUids.has(uid)) { selUids.delete(uid); el.querySelector('.chk').style.display = 'none'; el.classList.remove('sel'); } else { selUids.add(uid); el.querySelector('.chk').style.display = 'block'; el.classList.add('sel'); } }
async function submitCreate() { const n = document.getElementById('inp-grp-name').value; if (!n) return alert('输入群名'); await fetch('/create_group', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: n, uid: me.uid, members: Array.from(selUids) }) }); closeMd('md-create'); if (pollingTimer) clearTimeout(pollingTimer); sync(); }
async function submitInvite() { if (!target || target.type !== 'group') return; await fetch('/group/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'invite', group_id: target.id, uid: me.uid, members: Array.from(selUids) }) }); closeMd('md-invite'); if (pollingTimer) clearTimeout(pollingTimer); sync(); }
function openManage() { if (!target || target.type !== 'group') return; var g = cache.groups[target.id]; document.getElementById('mng-grp-name').value = g.name; var h = ''; g.members.forEach(mid => { var u = cache.users[mid] || { name: 'Unknown' }; var isOwner = mid === g.owner; var btn = (!isOwner && mid !== me.uid) ? '<div class="clickable" style="color:red;font-size:12px;" onclick="doKick(\\''+mid+'\\')">移出</div>' : ''; h += '<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid rgba(0,0,0,0.05);"><span>' + getName(mid) + ' ' + (isOwner ? '(群主)' : '') + '</span>' + btn + '</div>'; }); document.getElementById('mng-mem-list').innerHTML = h; document.getElementById('md-manage').style.display = 'flex'; }
async function doRename() { const n = document.getElementById('mng-grp-name').value; if (!n) return; await fetch('/group/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'rename', group_id: target.id, uid: me.uid, name: n }) }); if (pollingTimer) clearTimeout(pollingTimer); sync(); }
async function doKick(uid) { if (!confirm('确定移除该成员？')) return; await fetch('/group/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'kick', group_id: target.id, uid: me.uid, target_uid: uid }) }); openManage(); if (pollingTimer) clearTimeout(pollingTimer); sync(); }
async function doDissolve() { if (!confirm('确定解散群组？')) return; await fetch('/group/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'dissolve', group_id: target.id, uid: me.uid }) }); closeMd('md-manage'); target = null; if (pollingTimer) clearTimeout(pollingTimer); sync(); }
function openSet() { document.getElementById('set-av').style.background = me.avatar_bg; document.getElementById('set-new-nick').value = me.name; document.getElementById('set-new-pwd').value = ''; devClicks = 0; document.getElementById('md-set').style.display = 'flex'; }
async function changeAv() { const avBox = document.getElementById('set-av'); avBox.classList.remove('spin'); void avBox.offsetWidth; avBox.classList.add('spin'); const r = await fetch('/update_avatar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid: me.uid }) }); const d = await r.json(); me.avatar_bg = d.avatar_bg; upMe(); setTimeout(() => avBox.style.background = me.avatar_bg, 250); }
async function saveProfile() { const nick = document.getElementById('set-new-nick').value.trim(); const pwd = document.getElementById('set-new-pwd').value.trim(); if (!nick) return alert('昵称不能为空'); const r = await fetch('/update_profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid: me.uid, nickname: nick, password: pwd }) }); const d = await r.json(); if (!r.ok) return alert(d.error || '保存失败'); me.name = d.name; closeMd('md-set'); }
function triggerDev() { devClicks++; if (devClicks >= 10) { devClicks = 0; closeMd('md-set'); document.getElementById('dev-pwd').value = ''; document.getElementById('md-dev-auth').style.display = 'flex'; } }
async function verifyDev() {
    const p = document.getElementById('dev-pwd').value;
    // 尝试进行管理员身份验证
    const authenticated = await authenticateAdmin(p);
    if (authenticated) {
        try {
            const r = await fetch('/api/admin/account_panel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: adminToken })
            });
            if (!r.ok) throw new Error('Access Denied');
            const data = await r.json();
            closeMd('md-dev-auth');
            openAccountPanel(data.accounts);
        } catch (e) {
            alert('认证失败');
            document.getElementById('dev-pwd').value = '';
        }
        return;
    }
    // 原有的日志查看密码验证
    try {
        const r = await fetch('/api/admin/logs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: p }) });
        if (!r.ok) throw new Error('Access Denied');
        const data = await r.json();
        closeMd('md-dev-auth');
        renderDevLogs(data);
        document.getElementById('md-dev-logs').style.display = 'flex';
    } catch (e) {
        alert('认证失败');
        document.getElementById('dev-pwd').value = '';
    }
}

// ==================== 账户信息合并管理面板功能 ====================

let adminToken = null;  // 管理员会话 token（安全存储）
let accountPanelData = [];  // 存储账户列表数据
let selectedDeleteAccount = null;  // 选中要删除的账户
let selectedSourceAccount = null;  // 选中的源账户（合并）
let selectedTargetAccount = null;  // 选中的目标账户（合并）

async function authenticateAdmin(password) {
    // 管理员身份验证 - 获取 session token
    try {
        const r = await fetch('/api/admin/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: password })
        });
        if (!r.ok) throw new Error('Authentication failed');
        const data = await r.json();
        adminToken = data.token;  // 存储 token
        return true;
    } catch (e) {
        adminToken = null;
        return false;
    }
}

function openAccountPanel(accounts) {
    accountPanelData = accounts || [];
    selectedDeleteAccount = null;
    selectedSourceAccount = null;
    selectedTargetAccount = null;
    // 默认显示访问控制区域
    showAccessControlSection();
    document.getElementById('md-account-panel').style.display = 'flex';
}

function showAccessControlSection() {
    document.getElementById('access-control-section').style.display = 'block';
    document.getElementById('delete-account-section').style.display = 'none';
    document.getElementById('merge-account-section').style.display = 'none';
    renderAccessControlList();
}

function showDeleteAccountSection() {
    document.getElementById('access-control-section').style.display = 'none';
    document.getElementById('delete-account-section').style.display = 'block';
    document.getElementById('merge-account-section').style.display = 'none';
    renderDeleteAccountList();
}

function showMergeAccountSection() {
    document.getElementById('access-control-section').style.display = 'none';
    document.getElementById('delete-account-section').style.display = 'none';
    document.getElementById('merge-account-section').style.display = 'block';
    renderMergeAccountLists();
}

function renderAccessControlList() {
    const container = document.getElementById('access-control-list');
    if (!accountPanelData || accountPanelData.length === 0) {
        container.innerHTML = '<div style="text-align:center; color:#666; padding:20px;">暂无可操作的账户</div>';
        return;
    }
    let h = '';
    accountPanelData.forEach(acc => {
        const lastActive = acc.last_active ? new Date(acc.last_active * 1000).toLocaleString() : '从未登录';
        const regTime = acc.registered_at_formatted || '旧用户（无限制）';
        const hasUnrestricted = acc.unrestricted_access;
        const toggleBg = hasUnrestricted ? '#30d158' : '#444';
        const togglePos = hasUnrestricted ? 'translateX(20px)' : 'translateX(0)';
        const statusText = hasUnrestricted ? '✅ 无限制' : '🔒 受限';
        const statusColor = hasUnrestricted ? '#30d158' : '#ff9500';

        h += '<div class="account-item" style="display:flex; align-items:center; padding:10px; margin:5px 0; background:#222; border-radius:8px; border:1px solid #333;">' +
            '<div style="width:40px; height:40px; border-radius:12px; background:' + acc.avatar_bg + '; margin-right:12px; flex-shrink:0;"></div>' +
            '<div style="flex:1; min-width:0;">' +
            '<div style="font-size:14px; font-weight:600; color:#ddd;">' + acc.name + '</div>' +
            '<div style="font-size:11px; color:#888;">UID: ' + acc.uid + ' | 消息数: ' + acc.msg_count + '</div>' +
            '<div style="font-size:10px; color:#666;">注册时间: ' + regTime + '</div>' +
            '<div style="font-size:10px; color:' + statusColor + '; margin-top:2px;">' + statusText + '</div>' +
            '</div>' +
            '<div class="clickable" onclick="toggleUserAccess(&apos;' + acc.uid + '&apos;, ' + !hasUnrestricted + ')" style="position:relative; width:44px; height:24px; background:' + toggleBg + '; border-radius:12px; transition:all 0.3s;">' +
            '<div style="position:absolute; top:2px; left:2px; width:20px; height:20px; background:white; border-radius:50%; transform:' + togglePos + '; transition:transform 0.3s;"></div>' +
            '</div>' +
            '</div>';
    });
    container.innerHTML = h;
}

async function toggleUserAccess(uid, enable) {
    if (!adminToken) {
        alert('会话已过期，请重新认证');
        closeMd('md-account-panel');
        return;
    }

    try {
        const r = await fetch('/api/admin/toggle_unrestricted_access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: adminToken,
                target_uid: uid,
                unrestricted_access: enable
            })
        });
        const data = await r.json();
        if (!r.ok) {
            alert('操作失败: ' + (data.error || '未知错误'));
            return;
        }

        // 更新本地数据
        const acc = accountPanelData.find(a => a.uid === uid);
        if (acc) {
            acc.unrestricted_access = enable;
        }

        // 重新渲染列表
        renderAccessControlList();

        // 显示成功提示
        const statusText = enable ? '启用' : '禁用';
        logInfo('Admin', '✅ 已' + statusText + '用户 ' + uid + ' 的无限制访问');
    } catch (e) {
        alert('操作失败: ' + e.message);
    }
}

async function batchToggleAccess(enable) {
    const actionText = enable ? '启用' : '禁用';
    if (!confirm(`❗ 确定要${actionText}所有用户的无限制访问吗？\n\n这将影响所有用户的历史消息访问权限。`)) {
        return;
    }

    if (!adminToken) {
        alert('会话已过期，请重新认证');
        closeMd('md-account-panel');
        return;
    }

    try {
        const r = await fetch('/api/admin/batch_toggle_unrestricted_access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: adminToken,
                enable: enable
            })
        });
        const data = await r.json();
        if (!r.ok) {
            alert('操作失败: ' + (data.error || '未知错误'));
            return;
        }

        alert('✅ ' + data.message);

        // 更新本地数据
        accountPanelData.forEach(acc => {
            acc.unrestricted_access = enable;
        });

        // 重新渲染列表
        renderAccessControlList();
    } catch (e) {
        alert('操作失败: ' + e.message);
    }
}

function renderDeleteAccountList() {
    const container = document.getElementById('delete-account-list');
    if (!accountPanelData || accountPanelData.length === 0) {
        container.innerHTML = '<div style="text-align:center; color:#666; padding:20px;">暂无可操作的账户</div>';
        return;
    }
    let h = '';
    accountPanelData.forEach(acc => {
        const lastActive = acc.last_active ? new Date(acc.last_active * 1000).toLocaleString() : '从未登录';
        const isSelected = selectedDeleteAccount === acc.uid;
        const bgColor = isSelected ? 'rgba(255,59,48,0.3)' : '#222';
        const borderColor = isSelected ? '#ff3b30' : '#333';
        const checkColor = isSelected ? '#ff3b30' : '#444';
        const checkIcon = isSelected ? '✓' : '○';
        h += '<div class="account-item clickable" style="display:flex; align-items:center; padding:10px; margin:5px 0; background:' + bgColor + '; border-radius:8px; border:1px solid ' + borderColor + ';" onclick="selectDeleteAccount(&apos;' + acc.uid + '&apos;)">' +
            '<div style="width:40px; height:40px; border-radius:12px; background:' + acc.avatar_bg + '; margin-right:12px; flex-shrink:0;"></div>' +
            '<div style="flex:1; min-width:0;">' +
            '<div style="font-size:14px; font-weight:600; color:#ddd;">' + acc.name + '</div>' +
            '<div style="font-size:11px; color:#888;">UID: ' + acc.uid + ' | 消息数: ' + acc.msg_count + '</div>' +
            '<div style="font-size:10px; color:#666;">最后活跃: ' + lastActive + '</div>' +
            '</div>' +
            '<div style="color:' + checkColor + '; font-size:18px;">' + checkIcon + '</div>' +
            '</div>';
    });
    container.innerHTML = h;
}

function selectDeleteAccount(uid) {
    selectedDeleteAccount = (selectedDeleteAccount === uid) ? null : uid;
    renderDeleteAccountList();
}

async function confirmDeleteAccount() {
    if (!selectedDeleteAccount) {
        alert('请先选择要删除的账户');
        return;
    }
    const acc = accountPanelData.find(a => a.uid === selectedDeleteAccount);
    if (!acc) return;

    // 第一次确认
    if (!confirm(`❗ 确定要删除账户 "${acc.name}" (UID: ${acc.uid}) 吗？\n\n该账户将无法再次登录，但历史消息将保留。`)) {
        return;
    }


    // 第二次确认（输入确认）
    const confirmText = prompt('请输入 \"DELETE\" 确认删除操作：');
    if (confirmText !== 'DELETE') {
        alert('删除操作已取消');
        return;
    }

    // 验证 token 有效性
    if (!adminToken) {
        alert('会话已过期，请重新认证');
        closeMd('md-account-panel');
        return;
    }

    try {
        const r = await fetch('/api/admin/delete_account', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: adminToken,
                target_uid: selectedDeleteAccount
            })
        });
        const data = await r.json();
        if (!r.ok) {
            alert('删除失败: ' + (data.error || '未知错误'));
            return;
        }
        alert('\u2705 ' + data.message);
        // 从列表中移除已删除的账户
        accountPanelData = accountPanelData.filter(a => a.uid !== selectedDeleteAccount);
        selectedDeleteAccount = null;
        renderDeleteAccountList();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

function renderMergeAccountLists() {
    const sourceContainer = document.getElementById('merge-source-list');
    const targetContainer = document.getElementById('merge-target-list');

    if (!accountPanelData || accountPanelData.length < 2) {
        sourceContainer.innerHTML = '<div style="text-align:center; color:#666; padding:20px;">需要至少2个账户</div>';
        targetContainer.innerHTML = '<div style="text-align:center; color:#666; padding:20px;">需要至少2个账户</div>';
        return;
    }

    // 渲染源账户列表
    let sourceH = '';
    accountPanelData.forEach(acc => {
        const isSelected = selectedSourceAccount === acc.uid;
        const isDisabled = selectedTargetAccount === acc.uid;
        const bgColor = isSelected ? 'rgba(255,149,0,0.3)' : (isDisabled ? '#1a1a1a' : '#222');
        const borderColor = isSelected ? '#ff9500' : '#333';
        const opacity = isDisabled ? '0.5' : '1';
        const checkColor = isSelected ? '#ff9500' : '#444';
        const checkIcon = isSelected ? '✓' : '';
        const onclickAttr = isDisabled ? '' : 'selectSourceAccount(&apos;' + acc.uid + '&apos;)';
        sourceH += '<div class="account-item clickable" style="display:flex; align-items:center; padding:8px; margin:3px 0; background:' + bgColor + '; border-radius:6px; border:1px solid ' + borderColor + '; opacity:' + opacity + ';" onclick="' + onclickAttr + '">' +
            '<div style="width:30px; height:30px; border-radius:8px; background:' + acc.avatar_bg + '; margin-right:10px; flex-shrink:0;"></div>' +
            '<div style="flex:1; min-width:0;">' +
            '<div style="font-size:13px; font-weight:600; color:#ddd;">' + acc.name + '</div>' +
            '<div style="font-size:10px; color:#888;">消息数: ' + acc.msg_count + '</div>' +
            '</div>' +
            '<div style="color:' + checkColor + '; font-size:16px;">' + checkIcon + '</div>' +
            '</div>';
    });
    sourceContainer.innerHTML = sourceH;

    // 渲染目标账户列表
    let targetH = '';
    accountPanelData.forEach(acc => {
        const isSelected = selectedTargetAccount === acc.uid;
        const isDisabled = selectedSourceAccount === acc.uid;
        const bgColor = isSelected ? 'rgba(48,209,88,0.3)' : (isDisabled ? '#1a1a1a' : '#222');
        const borderColor = isSelected ? '#30d158' : '#333';
        const opacity = isDisabled ? '0.5' : '1';
        const checkColor = isSelected ? '#30d158' : '#444';
        const checkIcon = isSelected ? '✓' : '';
        const onclickAttr = isDisabled ? '' : 'selectTargetAccount(&apos;' + acc.uid + '&apos;)';
        targetH += '<div class="account-item clickable" style="display:flex; align-items:center; padding:8px; margin:3px 0; background:' + bgColor + '; border-radius:6px; border:1px solid ' + borderColor + '; opacity:' + opacity + ';" onclick="' + onclickAttr + '">' +
            '<div style="width:30px; height:30px; border-radius:8px; background:' + acc.avatar_bg + '; margin-right:10px; flex-shrink:0;"></div>' +
            '<div style="flex:1; min-width:0;">' +
            '<div style="font-size:13px; font-weight:600; color:#ddd;">' + acc.name + '</div>' +
            '<div style="font-size:10px; color:#888;">消息数: ' + acc.msg_count + '</div>' +
            '</div>' +
            '<div style="color:' + checkColor + '; font-size:16px;">' + checkIcon + '</div>' +
            '</div>';
    });
    targetContainer.innerHTML = targetH;

    // 更新合并预览
    updateMergePreview();
}

function selectSourceAccount(uid) {
    selectedSourceAccount = (selectedSourceAccount === uid) ? null : uid;
    renderMergeAccountLists();
}

function selectTargetAccount(uid) {
    selectedTargetAccount = (selectedTargetAccount === uid) ? null : uid;
    renderMergeAccountLists();
}

function updateMergePreview() {
    const previewEl = document.getElementById('merge-preview');
    const contentEl = document.getElementById('merge-preview-content');

    if (selectedSourceAccount && selectedTargetAccount) {
        const source = accountPanelData.find(a => a.uid === selectedSourceAccount);
        const target = accountPanelData.find(a => a.uid === selectedTargetAccount);
        if (source && target) {
            previewEl.style.display = 'block';
            contentEl.innerHTML = '将 <span style="color:#ff9500; font-weight:600;">' + source.name + '</span> (' + source.msg_count + '条消息) ' +
                '合并到 <span style="color:#30d158; font-weight:600;">' + target.name + '</span>';
            return;
        }
    }
    previewEl.style.display = 'none';
}

async function confirmMergeAccounts() {
    if (!selectedSourceAccount || !selectedTargetAccount) {
        alert('请分别选择源账户和目标账户');
        return;
    }

    const source = accountPanelData.find(a => a.uid === selectedSourceAccount);
    const target = accountPanelData.find(a => a.uid === selectedTargetAccount);
    if (!source || !target) return;

    // 第一次确认
    if (!confirm(`❗ 确定要将账户 "${source.name}" 合并到 "${target.name}" 吗？\n\n源账户的所有消息将转移到目标账户，源账户将无法再次登录。\n此操作不可撤销！`)) {
        return;
    }


    // 第二次确认（输入确认）
    const confirmText = prompt('请输入 \"MERGE\" 确认合并操作：');
    if (confirmText !== 'MERGE') {
        alert('合并操作已取消');
        return;
    }

    // 验证 token 有效性
    if (!adminToken) {
        alert('会话已过期，请重新认证');
        closeMd('md-account-panel');
        return;
    }

    try {
        const r = await fetch('/api/admin/merge_accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token: adminToken,
                source_uid: selectedSourceAccount,
                target_uid: selectedTargetAccount
            })
        });
        const data = await r.json();
        if (!r.ok) {
            alert('合并失败: ' + (data.error || '未知错误'));
            return;
        }
        alert('\u2705 ' + data.message);
        // 从列表中移除已合并的源账户，更新目标账户的消息数
        const sourceAcc = accountPanelData.find(a => a.uid === selectedSourceAccount);
        const targetAcc = accountPanelData.find(a => a.uid === selectedTargetAccount);
        if (sourceAcc && targetAcc) {
            targetAcc.msg_count += sourceAcc.msg_count;
        }
        accountPanelData = accountPanelData.filter(a => a.uid !== selectedSourceAccount);
        selectedSourceAccount = null;
        selectedTargetAccount = null;
        renderMergeAccountLists();
    } catch (e) {
        alert('合并失败: ' + e.message);
    }
}

function renderDevLogs(data) {
    const el = document.getElementById('dev-logs-content');
    const users = data.users;
    const msgs = data.messages;
    const groups = data.groups;
    let h = '';

    msgs.slice().reverse().forEach(m => {
        const d = new Date(m.timestamp * 1000);
        const timeStr = d.toLocaleString();
        const sender = users[m.from_uid] ? users[m.from_uid].name : (m.from_uid === 'system' ? 'SYSTEM' : 'Unknown');

        let to = 'Unknown';
        if (groups[m.to_uid]) {
            to = 'Group[' + groups[m.to_uid].name + ']';
        } else if (users[m.to_uid]) {
            to = 'User[' + users[m.to_uid].name + ']';
        } else {
            to = m.to_uid;
        }

        let content = m.content;

        // 处理合并转发消息
        if (content && content.startsWith('{"type":"merge_fwd"')) {
            try {
                var fwd = JSON.parse(content);
                var subJson = content.replace(/"/g, '&quot;');
                content = '<span style="cursor:pointer;text-decoration:underline;color:#4facfe" onclick="viewFwd(this)" data-fwd-json="' + subJson + '">[\u67e5\u770b\u8bb0\u5f55] ' + fwd.title + ' (' + fwd.list.length + '\u6761\u6d88\u606f)</span>';
            } catch (e) {
                content = '[\u804a\u5929\u8bb0\u5f55\u89e3\u6790\u5931\u8d25]';
            }
        } else if (m.type === 'file') {
            content = 'FILE: <a class="log-file-link" onclick="downloadFile(&apos;' + m.server_filename + '&apos;, &apos;' + m.filename + '&apos;)">' + m.filename + '</a>';
        }

        // 处理撤回标记
        if (m.is_recalled) {
            content += ' <span style="color:red;font-weight:bold;">[\u5df2\u64a4\u56de]</span>';
        }

        // 处理引用消息
        if (m.quote) {
            var qC = m.quote.content;
            if (qC && qC.startsWith('{"type":"merge_fwd"')) {
                qC = '[\u804a\u5929\u8bb0\u5f55]';
            }
            content += ' <span style="color:#666;font-size:10px;">(\u56de\u590d: ' + m.quote.name + ' - ' + qC + ')</span>';
        }

        h += '<div class="log-entry"><span style="color:#555">[' + timeStr + ']</span> <span style="color:#ccc">' + sender + '</span> -> <span style="color:#888">' + to + '</span>: <span style="color:#fff">' + content + '</span></div>';
    });

    el.innerHTML = h || 'No Logs.';
}
function upMe() { document.getElementById('my-av').style.background = me.avatar_bg; }
document.getElementById('inp-msg').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }

// ==================== 窄屏与隐蔽模式功能 ====================

let isCompactMode = false;
let originalTitle = document.title;

// 初始化窄屏优化
function initCompactMode() {
    // 检测窗口宽度
    function checkWindowSize() {
        const width = window.innerWidth;
        if (width <= 400 && !isCompactMode) {
            enableCompactMode();
        } else if (width > 400 && isCompactMode) {
            disableCompactMode();
        }
    }

    // 监听窗口大小变化
    window.addEventListener('resize', checkWindowSize);
    checkWindowSize();

    // 输入框聚焦/失焦自动展开/收起
    const inputArea = document.getElementById('input-area');
    const inpMsg = document.getElementById('inp-msg');

    if (inpMsg) {
        inpMsg.addEventListener('focus', () => {
            if (isCompactMode) {
                inputArea.classList.remove('compact');
            }
        });

        inpMsg.addEventListener('blur', () => {
            if (isCompactMode && !inpMsg.value.trim()) {
                setTimeout(() => {
                    inputArea.classList.add('compact');
                }, 200);
            }
        });
    }
}

function enableCompactMode() {
    isCompactMode = true;
    document.body.classList.add('compact-mode');
    const inputArea = document.getElementById('input-area');
    if (inputArea) {
        inputArea.classList.add('compact');
    }
    logDebug('Compact Mode', '启用窄屏优化模式');
}

function disableCompactMode() {
    isCompactMode = false;
    document.body.classList.remove('compact-mode');
    const inputArea = document.getElementById('input-area');
    if (inputArea) {
        inputArea.classList.remove('compact');
    }
    logDebug('Compact Mode', '禁用窄屏优化模式');
}

// 消息折叠功能（可选，在 renderChat 中调用）
function addMessageFoldFeature() {
    const msgBubbles = document.querySelectorAll('.msg-bub');
    msgBubbles.forEach(bubble => {
        // 如果消息超过3行，添加折叠
        const lineHeight = parseInt(window.getComputedStyle(bubble).lineHeight);
        const maxHeight = lineHeight * 3;

        if (bubble.scrollHeight > maxHeight + 10) { // 留有一定余量
            // 检查是否已有展开按钮
            const existingBtn = bubble.parentElement.querySelector('.msg-expand-btn');
            if (!existingBtn) {
                bubble.classList.add('folded');

                const expandBtn = document.createElement('div');
                expandBtn.className = 'msg-expand-btn';
                expandBtn.textContent = '展开↓';
                expandBtn.onclick = function (e) {
                    e.stopPropagation();
                    if (bubble.classList.contains('folded')) {
                        bubble.classList.remove('folded');
                        expandBtn.textContent = '收起↑';
                    } else {
                        bubble.classList.add('folded');
                        expandBtn.textContent = '展开↓';
                    }
                };

                bubble.parentElement.appendChild(expandBtn);
            }
        }
    });
}

// ==================== GIF性能优化：暂停/播放控制 ====================

let gifPauseEnabled = false; // 默认禁用，窄屏时启用
const gifStaticFrames = new Map(); // 存储GIF的静态帧

// 初始化GIF暂停功能
function initGifPauseControl() {
    // 检测窗口宽度，窄屏时启用
    function checkGifPause() {
        const width = window.innerWidth;
        gifPauseEnabled = (width <= 400);

        if (gifPauseEnabled) {
            logDebug('GIF Pause', '启用GIF暂停功能 (窄屏模式)');
        }
    }

    window.addEventListener('resize', checkGifPause);
    checkGifPause();

    // 添加窗口大小变化监听，实时更新未读消息气泡状态
    window.addEventListener('resize', function () {
        updateMobileUnreadBadge();
    });

    // 为表情面板中的GIF添加点击播放/暂停
    document.addEventListener('click', (e) => {
        const gif = e.target.closest('.sticker-gif');
        if (gif && gifPauseEnabled) {
            toggleGifPlayback(gif);
        }
    });

    // 为消息中的GIF添加点击播放
    document.addEventListener('click', (e) => {
        const msgGif = e.target.closest('.msg-bub img[src*="telegram_stickers"]');
        if (msgGif && gifPauseEnabled) {
            // 消息中的GIF点击就正常播放，不做暂停控制
            // 可以添加视觉反馈
            msgGif.style.transform = 'scale(0.95)';
            setTimeout(() => {
                msgGif.style.transform = 'scale(1)';
            }, 100);
        }
    });
}

// 切换GIF播放状态
function toggleGifPlayback(gif) {
    const isPaused = gif.classList.contains('paused');

    if (isPaused) {
        // 恢复播放
        gif.classList.remove('paused');
        if (gif.dataset.originalSrc) {
            gif.src = gif.dataset.originalSrc;
        }
    } else {
        // 暂停（实际上 WebP 不能真正暂停，只是添加视觉提示）
        gif.classList.add('paused');
    }
}

// 在渲染表情时，为窄屏模式下的GIF添加默认暂停标记
function applyGifPauseToPanel() {
    if (!gifPauseEnabled) return;

    const gifs = document.querySelectorAll('.sticker-content .sticker-gif');
    gifs.forEach(gif => {
        // 默认不添加paused，让用户可以直接看到动画
        // 如果需要默认暂停，取消注释下一行
        // gif.classList.add('paused');
    });
}

// ==================== P2P传输UI函数====================

// P2P传输管理器状态
let p2pManager = null;
let currentP2PRequest = null;
let p2pTransfers = new Map(); // session_id -> transfer info
let processedSessions = new Set(); // 已处理过的会话ID（避免重复警告）

/**
 * 初始化P2P传输管理器
 */
function initP2PManager() {
    logDebug('P2P', 'Attempting to initialize P2P manager...');
    logDebug('P2P', 'SignalingClient available:', typeof SignalingClient !== 'undefined');
    logDebug('P2P', 'P2PSession available:', typeof P2PSession !== 'undefined');
    logDebug('P2P', 'P2PGroupSession available:', typeof P2PGroupSession !== 'undefined');
    logDebug('P2P', 'P2PTransferManager available:', typeof P2PTransferManager !== 'undefined');

    if (typeof SignalingClient === 'undefined' ||
        typeof P2PSession === 'undefined' ||
        typeof P2PTransferManager === 'undefined') {
        logWarn('P2P', 'Core P2P libraries not loaded yet, retrying in 500ms...');
        setTimeout(initP2PManager, 500);
        return;
    }

    // P2PGroupSession is optional for group chat functionality
    if (typeof P2PGroupSession === 'undefined') {
        logWarn('P2P', 'P2PGroupSession not available - group chat P2P will be disabled');
    }

    try {
        const signalingClient = new SignalingClient('');
        p2pManager = new P2PTransferManager(signalingClient, {
            onProgress: updateP2PProgress,
            onComplete: handleP2PComplete,
            onError: handleP2PError,
            onStatusChange: handleP2PStatusChange,
            onTransferInitiated: handleP2PInitiated,
            onTransferAccepted: handleP2PAccepted
        });

        // 设置为全局变量，供其他模块使用
        window.p2pManager = p2pManager;

        logInfo('P2P', 'Manager initialized successfully');

    } catch (error) {
        logError('P2P', 'Failed to initialize manager:', error);
    }
}

/**
 * 显示P2P传输请求通知
 */
function showP2PRequest(requestData) {
    currentP2PRequest = requestData;

    // 设置发送方信息
    const senderUid = requestData.sender_uid;
    const sender = cache.users[senderUid] || { name: 'Unknown', avatar_bg: '#ccc' };
    document.getElementById('p2p-req-sender-av').style.background = sender.avatar_bg;
    document.getElementById('p2p-req-sender-name').innerText = getName(senderUid);

    // 设置聊天类型
    const chatType = requestData.chat_type === 'group' ? '群聊' : '私聊';
    document.getElementById('p2p-req-chat-type').innerText = chatType + '文件传输';

    // 渲染文件列表
    const fileListHtml = requestData.files.map(file => `
            <div class="p2p-file-item">
                <div class="p2p-file-icon">📄</div>
                <div class="p2p-file-info">
                    <div class="p2p-file-name">${escapeHtml(file.filename)}</div>
                    <div class="p2p-file-size">${formatFileSize(file.size)}</div>
                </div>
            </div>
        `).join('');
    document.getElementById('p2p-req-file-list').innerHTML = fileListHtml;

    // 设置总大小
    const totalSize = requestData.files.reduce((sum, f) => sum + f.size, 0);
    document.getElementById('p2p-req-total-size').innerText = formatFileSize(totalSize);

    // 显示模态框
    document.getElementById('md-p2p-request').style.display = 'flex';
}

/**
 * 接受P2P传输请求
 */
async function acceptP2PRequest() {
    if (!currentP2PRequest || !p2pManager) return;

    try {
        await p2pManager.acceptTransfer(currentP2PRequest.session_id);

        // 确保传输对象存在并正确设置
        if (!p2pTransfers.has(currentP2PRequest.session_id)) {
            logDebug('P2P', 'Creating transfer object for accepted request');
            p2pTransfers.set(currentP2PRequest.session_id, {
                sessionId: currentP2PRequest.session_id,
                status: 'connecting',
                role: 'receiver',
                files: currentP2PRequest.files,
                filename: currentP2PRequest.files.length > 1
                    ? `${currentP2PRequest.files.length}个文件`
                    : currentP2PRequest.files[0].filename,
                progress: 0,
                speed: 0,
                canResume: false
            });
        } else {
            // 更新现有传输对象的状态
            const transfer = p2pTransfers.get(currentP2PRequest.session_id);
            transfer.status = 'connecting';
        }

        renderP2PTransferList();
        closeMd('md-p2p-request');
        showToast('已接受传输请求');
        openP2PPanel();
    } catch (error) {
        logError('P2P', 'Failed to accept request:', error);
        showP2PError('接受失败', error.message, [
            { label: '重试', action: () => acceptP2PRequest() },
            { label: '取消', action: () => closeMd('md-p2p-error') }
        ]);
    }
}

/**
 * 拒绝P2P传输请求
 */
async function rejectP2PRequest() {
    if (!currentP2PRequest || !p2pManager) return;

    try {
        await p2pManager.rejectTransfer(currentP2PRequest.session_id, '用户拒绝');
        closeMd('md-p2p-request');
        showToast('已拒绝传输请求');
    } catch (error) {
        logError('P2P', 'Failed to reject request:', error);
    }
    currentP2PRequest = null;
}

/**
 * 更新P2P传输进度
 */
function updateP2PProgress(sessionId, progress, speed, integrityStatus) {
    const transfer = p2pTransfers.get(sessionId);
    if (!transfer) {
        logError('P2P', 'Transfer not found:', sessionId);
        return;
    }

    transfer.progress = progress;
    transfer.speed = speed;
    transfer.status = 'transferring';

    // 显示当前截断率
    if (integrityStatus) {
        transfer.truncationRate = integrityStatus.truncationRate;
        transfer.corruptedChunks = integrityStatus.corruptedChunks;
        transfer.retransmissionCount = integrityStatus.retransmissionCount;

        // 显示"检测到数据损坏，正在修复"提示
        if (integrityStatus.isRetransmitting) {
            transfer.integrityMessage = '🔧 检测到数据损坏，正在修复...';
        } else if (integrityStatus.truncationRate > 0) {
            transfer.integrityMessage = `📊 截断率: ${(integrityStatus.truncationRate * 100).toFixed(3)}%`;
        } else {
            transfer.integrityMessage = '✅ 数据完整性良好';
        }
    }

    // 更新新的消息系统
    if (window.p2pMessageIntegration) {
        const transferMessage = window.p2pMessageIntegration.getTransferMessageInstance(sessionId);
        if (transferMessage) {
            // 如果状态不是transferring，先更新状态
            if (transferMessage.status !== 'transferring') {
                transferMessage.updateStatus('transferring', {
                    progress: progress,
                    speed: speed,
                    avgSpeed: speed,
                    estimatedTime: null
                });
            } else {
                // 否则只更新进度和速度
                transferMessage.updateProgress(progress);
                if (speed) {
                    transferMessage.updateSpeed(speed, speed, null);
                }
            }
        }
    }

    renderP2PTransferList();
}

/**
 * 处理P2P传输完成
 */
function handleP2PComplete(sessionId) {
    const transfer = p2pTransfers.get(sessionId);
    if (!transfer) return;

    transfer.status = 'completed';
    transfer.progress = 100;
    transfer.integrityMessage = '✅ 数据完整性验证通过';

    // 更新新的消息系统
    if (window.p2pMessageIntegration) {
        window.p2pMessageIntegration.updateMessageStatus(sessionId, 'completed', {
            progress: 100
        }).catch(err => logError('P2P', 'Failed to update message status:', err));
    }

    renderP2PTransferList();
    showToast('✅ 文件传输完成，数据完整性验证通过');

    // 5秒后从列表中移除（增加时间让用户看到验证通过消息）
    setTimeout(() => {
        p2pTransfers.delete(sessionId);
        renderP2PTransferList();
    }, 5000);
}

/**
 * 处理P2P传输错误
 */
function handleP2PError(sessionId, error) {
    const transfer = p2pTransfers.get(sessionId);
    if (!transfer) return;

    transfer.status = 'failed';
    transfer.error = error.message;

    // 更新新的消息系统
    if (window.p2pMessageIntegration) {
        window.p2pMessageIntegration.updateMessageStatus(sessionId, 'failed', {
            error: error.message
        }).catch(err => logError('P2P', 'Failed to update message status:', err));
    }

    renderP2PTransferList();

    // 根据错误类型显示不同的处理选项
    const actions = [];

    if (error.type === 'connection_failed') {
        // 连接失败 - 提供重试和回退选项
        if (transfer.canFallback) {
            actions.push({ label: '重试P2P', action: () => retryP2PTransfer(sessionId) });
            actions.push({ label: '使用服务器上传', action: () => fallbackToServer(sessionId) });
        } else {
            actions.push({ label: '重试', action: () => retryP2PTransfer(sessionId) });
        }
    } else if (error.type === 'hash_mismatch') {
        // 哈希不匹配 - 只提供重试
        actions.push({ label: '重试传输', action: () => retryP2PTransfer(sessionId) });
    } else if (error.type === 'webrtc_not_supported') {
        // WebRTC不支持 - 无法使用P2P
        // 不提供任何操作
    } else {
        // 其他错误 - 提供重试
        actions.push({ label: '重试', action: () => retryP2PTransfer(sessionId) });
    }

    actions.push({ label: '取消', action: () => cancelP2PTransfer(sessionId) });

    showP2PError(error.title || '传输错误', error.message, actions);
}

/**
 * 处理P2P状态变化
 */
function handleP2PStatusChange(sessionId, status) {
    const transfer = p2pTransfers.get(sessionId);
    if (!transfer) return;

    // 定义状态优先级（数字越大优先级越高）
    const statusPriority = {
        'pending': 1,
        'accepted': 2,
        'connecting': 3,
        'transferring': 4,
        'completed': 5,
        'failed': 5,
        'cancelled': 5,
        'expired': 5
    };

    const currentPriority = statusPriority[transfer.status] || 0;
    const newPriority = statusPriority[status] || 0;

    // 只允许状态向前推进，不允许倒退（除非是终止状态）
    if (newPriority < currentPriority && currentPriority < 5) {
        logDebug('P2P', 'Ignoring status downgrade from', transfer.status, 'to', status);
        return;
    }

    transfer.status = status;

    // 更新新的消息系统
    if (window.p2pMessageIntegration) {
        const transferMessage = window.p2pMessageIntegration.getTransferMessageInstance(sessionId);
        if (transferMessage) {
            logDebug('P2P', 'Updating message status to:', status);
            transferMessage.updateStatus(status, {
                progress: transfer.progress || 0,
                speed: transfer.speed || 0,
                avgSpeed: transfer.speed || 0,
                estimatedTime: null
            });
        } else {
            logWarn('P2P', 'Transfer message not found for status update:', sessionId);
        }
    }

    renderP2PTransferList();
}

/**
 * 处理P2P传输发起
 */
function handleP2PInitiated(session) {
    logDebug('P2P', 'Transfer initiated:', session.id);
    // 传输已经在initiateP2PTransfer中添加到Map了
    renderP2PTransferList();
}

/**
 * 处理P2P传输接受
 */
function handleP2PAccepted(session) {
    logDebug('P2P', 'Transfer accepted:', session.id);
    const transfer = p2pTransfers.get(session.id);
    if (transfer) {
        transfer.status = 'connecting';
        renderP2PTransferList();
    }
}

/**
 * 显示P2P错误提示
 */
function showP2PError(title, message, actions) {
    document.getElementById('p2p-error-title').innerText = title;
    document.getElementById('p2p-error-message').innerText = message;

    const actionsHtml = actions.map(action => `
            <button class="btn-block clickable" onclick="${action.action.name}()" style="margin:0;">
                ${action.label}
            </button>
        `).join('');
    document.getElementById('p2p-error-actions').innerHTML = actionsHtml;

    document.getElementById('md-p2p-error').style.display = 'flex';
}

/**
 * 打开P2P传输列表面板
 */
function openP2PPanel() {
    document.getElementById('p2p-transfer-panel').style.display = 'flex';
    renderP2PTransferList();
}

/**
 * 关闭P2P传输列表面板
 */
function closeP2PPanel() {
    document.getElementById('p2p-transfer-panel').style.display = 'none';
}

/**
 * 渲染P2P传输列表
 */
function renderP2PTransferList() {
    // 使用新的消息化系统，禁用旧UI
    if (window.p2pMessageIntegration) {
        logDebug('P2P', 'Using new message system, old UI disabled');
        return;
    }

    const listEl = document.getElementById('p2p-transfer-list');

    if (!listEl) {
        logError('P2P', 'p2p-transfer-list element not found!');
        return;
    }

    if (p2pTransfers.size === 0) {
        listEl.innerHTML = '<div class="empty" style="padding:40px 20px;">暂无传输任务</div>';
        return;
    }

    const html = Array.from(p2pTransfers.values()).map(transfer => {
        const statusClass = `p2p-status-${transfer.status}`;
        const statusText = {
            'pending': '等待中',
            'connecting': '连接中',
            'transferring': '传输中',
            'completed': '已完成',
            'failed': '失败',
            'queued': '排队中'
        }[transfer.status] || transfer.status;

        let actionsHtml = '';
        if (transfer.status === 'transferring') {
            actionsHtml = `
                    <div class="p2p-transfer-actions">
                        <button class="p2p-action-btn p2p-btn-cancel" onclick="cancelP2PTransfer('${transfer.sessionId}')">取消</button>
                    </div>
                `;
        } else if (transfer.status === 'failed') {
            actionsHtml = `
                    <div class="p2p-transfer-actions">
                        <button class="p2p-action-btn p2p-btn-retry" onclick="retryP2PTransfer('${transfer.sessionId}')">重试</button>
                        <button class="p2p-action-btn p2p-btn-cancel" onclick="cancelP2PTransfer('${transfer.sessionId}')">取消</button>
                    </div>
                `;
        } else if (transfer.status === 'pending' && transfer.canResume) {
            actionsHtml = `
                    <div class="p2p-transfer-actions">
                        <button class="p2p-action-btn p2p-btn-resume" onclick="resumeP2PTransfer('${transfer.sessionId}')">继续</button>
                        <button class="p2p-action-btn p2p-btn-cancel" onclick="cancelP2PTransfer('${transfer.sessionId}')">取消</button>
                    </div>
                `;
        }

        // 显示重传进度和完整性信息
        let integrityHtml = '';
        if (transfer.integrityMessage) {
            integrityHtml = `
                    <div style="font-size:11px; color:var(--text-sub); margin-top:4px; padding:4px 8px; background:rgba(0,0,0,0.03); border-radius:6px;">
                        ${transfer.integrityMessage}
                    </div>
                `;
        }

        // 显示详细错误信息和建议操作
        let errorDetailHtml = '';
        if (transfer.status === 'failed' && transfer.error) {
            errorDetailHtml = `
                    <div style="font-size:11px; color:#e74c3c; margin-top:4px; padding:6px 8px; background:rgba(231,76,60,0.1); border-radius:6px; white-space:pre-wrap;">
                        ${escapeHtml(transfer.error)}
                    </div>
                `;
        }

        // 显示"数据完整性验证通过"或失败信息
        let verificationHtml = '';
        if (transfer.status === 'completed') {
            verificationHtml = `
                    <div style="font-size:11px; color:#27ae60; margin-top:4px; padding:4px 8px; background:rgba(39,174,96,0.1); border-radius:6px;">
                        ✅ 数据完整性验证通过
                    </div>
                `;
        }

        return `
                <div class="p2p-transfer-item">
                    <div class="p2p-transfer-header">
                        <div class="p2p-transfer-title">${escapeHtml(transfer.filename)}</div>
                        <div class="p2p-transfer-status ${statusClass}">${statusText}</div>
                    </div>
                    <div class="p2p-progress-bar">
                        <div class="p2p-progress-fill" style="width:${transfer.progress}%"></div>
                    </div>
                    <div class="p2p-transfer-info">
                        <span>${transfer.progress.toFixed(1)}%</span>
                        <span>${transfer.speed ? formatFileSize(transfer.speed) + '/s' : ''}</span>
                    </div>
                    ${integrityHtml}
                    ${errorDetailHtml}
                    ${verificationHtml}
                    ${actionsHtml}
                </div>
            `;
    }).join('');

    listEl.innerHTML = html;
}

/**
 * 取消P2P传输
 */
async function cancelP2PTransfer(sessionId) {
    if (!p2pManager) return;

    try {
        await p2pManager.cancelTransfer(sessionId);
        p2pTransfers.delete(sessionId);
        renderP2PTransferList();
        showToast('已取消传输');
    } catch (error) {
        logError('P2P', 'Failed to cancel transfer:', error);
    }
}

/**
 * 重试P2P传输
 */
async function retryP2PTransfer(sessionId) {
    closeMd('md-p2p-error');
    // 实现重试逻辑
    showToast('正在重试...');
}

/**
 * 恢复P2P传输
 */
async function resumeP2PTransfer(sessionId) {
    if (!p2pManager) return;

    try {
        await p2pManager.resumeTransfer(sessionId);
        showToast('正在恢复传输...');
    } catch (error) {
        logError('P2P', 'Failed to resume transfer:', error);
        showP2PError('恢复失败', error.message, [
            { label: '取消', action: () => closeMd('md-p2p-error') }
        ]);
    }
}

/**
 * 回退到服务器上传
 */
async function fallbackToServer(sessionId) {
    closeMd('md-p2p-error');
    // 实现回退到服务器上传的逻辑
    showToast('切换到服务器上传...');
}

/**
 * 渲染P2P文件消息
 */
function renderP2PFileMessage(msg) {
    const files = msg.files || [{ filename: msg.filename, size: msg.size }];
    const isMultiFile = files.length > 1;

    let html = `
            <div class="file-card">
                <div style="font-size:32px;">📦</div>
                <div>
                    <div style="font-weight:600; margin-bottom:4px;">
                        ${isMultiFile ? files.length + ' 个文件' : escapeHtml(files[0].filename)}
                        <span class="p2p-msg-badge">P2P传输</span>
                    </div>
                    <div style="font-size:12px; color:var(--text-sub);">
                        ${formatFileSize(files.reduce((sum, f) => sum + f.size, 0))}
                    </div>
                </div>
            </div>
        `;

    // 如果是多文件，显示文件列表
    if (isMultiFile) {
        html += '<div class="p2p-multi-file-list">';
        files.forEach(file => {
            html += `
                    <div class="p2p-multi-file-item">
                        ${escapeHtml(file.filename)} (${formatFileSize(file.size)})
                    </div>
                `;
        });
        html += '</div>';
    }

    // 如果发送方离线，显示提示
    if (msg.sender_offline) {
        html += '<div class="p2p-file-offline">⚠️ 发送方离线，文件不可用</div>';
    }

    return html;
}

/**
 * HTML转义函数
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 页面加载时初始化P2P管理器
window.addEventListener('load', () => {
    // 延迟初始化，等待P2P模块加载
    setTimeout(initP2PManager, 1000);
});



// Expose functions to global scope for inline HTML event handlers
window.renderDevLogs = renderDevLogs;
window.renderP2PTransferList = renderP2PTransferList;
window.sendAndRenderLocally = sendAndRenderLocally;
window.setupScrollListener = setupScrollListener;
window.renderFileList = renderFileList;
window.copyToClip = copyToClip;
window.showDeleteAccountSection = showDeleteAccountSection;
window.renderChat = renderChat;
window.openP2PPanel = openP2PPanel;
window.doRename = doRename;
window.formatFileSize = formatFileSize;
window.adjustStickerPanelPosition = adjustStickerPanelPosition;
window.initStickerTabsScrollbar = initStickerTabsScrollbar;
window.emojiToImg = emojiToImg;
window.closeMd = closeMd;
window.loadInitialHistory = loadInitialHistory;
window.toggleDynamicEmoji = toggleDynamicEmoji;
window.renderFwdPickerUI = renderFwdPickerUI;
window.openAccountPanel = openAccountPanel;
window.handleFileListScroll = handleFileListScroll;
window.loadTelegramStickers = loadTelegramStickers;
window.openInvite = openInvite;
window.onDragEnd = onDragEnd;
window.detectPerformanceLevel = detectPerformanceLevel;
window.popFwdStack = popFwdStack;
window.upMe = upMe;
window.switchChat = switchChat;
window.closeUploadPanel = closeUploadPanel;
window.selectSourceAccount = selectSourceAccount;
window.rejectP2PRequest = rejectP2PRequest;
window.handleP2PAccepted = handleP2PAccepted;
window.acceptP2PRequest = acceptP2PRequest;
window.loadMoreNewer = loadMoreNewer;
window.multiAction = multiAction;
window.toggleSticker = toggleSticker;
window.checkPinnedFolder = checkPinnedFolder;
window.triggerDev = triggerDev;
window.getUnreadCount = getUnreadCount;
window.safeId = safeId;
window.convertEmojiToImg = convertEmojiToImg;
window.compareIds = compareIds;
window.renderFwdList = renderFwdList;
window.showP2PError = showP2PError;
window.openSimpleForwardPicker = openSimpleForwardPicker;
window.send = send;
window.showToast = showToast;
window.renderUserSelect = renderUserSelect;
window.safeBigInt = safeBigInt;
window.toggleSel = toggleSel;
window.loadEmojiCategories = loadEmojiCategories;
window.openProfile = openProfile;
window.renderP2PFileMessage = renderP2PFileMessage;
window.onUpEnd = onUpEnd;
window.markRead = markRead;
window.closeP2PPanel = closeP2PPanel;
window.submitForward = submitForward;
window.addMessageFoldFeature = addMessageFoldFeature;
window.renderMergeAccountLists = renderMergeAccountLists;
window.saveRemark = saveRemark;
window.updateSidebarPreview = updateSidebarPreview;
window.tab = tab;
window.openCreate = openCreate;
window.submitInvite = submitInvite;
window.findMsgById = findMsgById;
window.onDragMove = onDragMove;
window.toggleUserAccess = toggleUserAccess;
window.showLoadingSpinner = showLoadingSpinner;
window.formatChatTime = formatChatTime;
window.upFiles = upFiles;
window.tog = tog;
window.loadFiles = loadFiles;
window.logWarn = logWarn;
window.updateContactUI = updateContactUI;
window.jumpToFwdMsg = jumpToFwdMsg;
window.zoomImg = zoomImg;
window.doNudge = doNudge;
window.openManage = openManage;
window.logDebug = logDebug;
window.checkGifPause = checkGifPause;
window.escapeHtml = escapeHtml;
window.loadEmojiMapping = loadEmojiMapping;
window.applyDiff = applyDiff;
window.formatSpeed = formatSpeed;
window.handleNotifClick = handleNotifClick;
window.renderMessageElement = renderMessageElement;
window.openSet = openSet;
window.closeListCtx = closeListCtx;
window.onUpMove = onUpMove;
window.toggleGifPlayback = toggleGifPlayback;
window.handleListContextMenu = handleListContextMenu;
window.isMsgBelongsToChat = isMsgBelongsToChat;
window.rejectP2PTransfer = rejectP2PTransfer;
window.checkWindowSize = checkWindowSize;
window.handleP2PInitiated = handleP2PInitiated;
window.getLastMsgInfo = getLastMsgInfo;
window.cancelQuote = cancelQuote;
window.renderAccessControlList = renderAccessControlList;
window.updateListUI = updateListUI;
window.startQuote = startQuote;
window.acceptP2PTransfer = acceptP2PTransfer;
window.initCompactMode = initCompactMode;
window.startDrag = startDrag;
window.closeFwdMd = closeFwdMd;
window.initP2PManager = initP2PManager;
window.showMergeAccountSection = showMergeAccountSection;
window.updateMobileUnreadBadge = updateMobileUnreadBadge;
window.batchToggleAccess = batchToggleAccess;
window.fallbackToServer = fallbackToServer;
window.jumpToMsg = jumpToMsg;
window.saveProfile = saveProfile;
window.shouldUpdateMessage = shouldUpdateMessage;
window.fmt = fmt;
window.retryP2PTransfer = retryP2PTransfer;
window.authenticateAdmin = authenticateAdmin;
window.updateP2PProgress = updateP2PProgress;
window.updateReadStatusIndicators = updateReadStatusIndicators;
window.openPinnedFolder = openPinnedFolder;
window.renderHistoryMessages = renderHistoryMessages;
window.logError = logError;
window.closeLightbox = closeLightbox;
window.applyGifPauseToPanel = applyGifPauseToPanel;
window.safeIdEqual = safeIdEqual;
window.confirmMergeAccounts = confirmMergeAccounts;
window.downloadPinnedFile = downloadPinnedFile;
window.handleP2PStatusChange = handleP2PStatusChange;
window.updateLbTransform = updateLbTransform;
window.openForwardPicker = openForwardPicker;
window.backMobileList = backMobileList;
window.doDissolve = doDissolve;
window.initGifPauseControl = initGifPauseControl;
window.switchStickerCategory = switchStickerCategory;
window.setupContextMenu = setupContextMenu;
window.sendSticker = sendSticker;
window.viewImg = viewImg;
window.loadGif = loadGif;
window.listMenuAction = listMenuAction;
window.showAccessControlSection = showAccessControlSection;
window.disableCompactMode = disableCompactMode;
window.submitCreate = submitCreate;
window.renderSystemMsg = renderSystemMsg;
window.selectTargetAccount = selectTargetAccount;
window.menuAction = menuAction;
window.unloadOldestGif = unloadOldestGif;
window.selFwdTarget = selFwdTarget;
window.doKick = doKick;
window.getName = getName;
window.handleMessageRecall = handleMessageRecall;
window.renderDeleteAccountList = renderDeleteAccountList;
window.selectDeleteAccount = selectDeleteAccount;
window.showP2PRequest = showP2PRequest;
window.loadDynamicEmojiList = loadDynamicEmojiList;
window.enableCompactMode = enableCompactMode;
window.startPolling = startPolling;
window.doLogin = doLogin;
window.doLogout = doLogout;
window.triggerInAppNotification = triggerInAppNotification;
window.formatListTime = formatListTime;
window.closeCtx = closeCtx;
window.downloadFile = downloadFile;
window.confirmDeleteAccount = confirmDeleteAccount;
window.updateFwdNav = updateFwdNav;
window.handleP2PError = handleP2PError;
window.initStickers = initStickers;
window.handleP2PComplete = handleP2PComplete;
window.renderStickers = renderStickers;
window.exitMulti = exitMulti;
window.sync = sync;
window.updateScrollbar = updateScrollbar;
window.toggleVisual = toggleVisual;
window.renderPinnedFolder = renderPinnedFolder;
window.initGifObserver = initGifObserver;
window.updateFloatButton = updateFloatButton;
window.stickerPagePrev = stickerPagePrev;
window.enterMulti = enterMulti;
window.loadVisualSettings = loadVisualSettings;
window.jumpToBottom = jumpToBottom;
window.searchFiles = searchFiles;
window.formatMsgPreview = formatMsgPreview;
window.scrollToBottomRobust = scrollToBottomRobust;
window.returnToLatest = returnToLatest;
window.verifyDev = verifyDev;
window.logInfo = logInfo;
window.stickerPageNext = stickerPageNext;
window.categoryEmojiToImg = categoryEmojiToImg;
window.cancelP2PTransfer = cancelP2PTransfer;
window.updateMergePreview = updateMergePreview;
window.renderNewMessages = renderNewMessages;
window.getSysText = getSysText;
window.changeAv = changeAv;
window.updateMessageInDOM = updateMessageInDOM;
window.findMsgIndexById = findMsgIndexById;
window.loadMoreHistory = loadMoreHistory;
window.handleContextMenu = handleContextMenu;
window.resumeP2PTransfer = resumeP2PTransfer;
window.processQueue = processQueue;
window.updateStickerTabsScrollbar = updateStickerTabsScrollbar;
window.viewFwd = viewFwd;
