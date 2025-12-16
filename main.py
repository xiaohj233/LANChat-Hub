# -*- coding: utf-8 -*-
"""
LANChat Hub v1.0.0 - 局域网聊天应用
"""

import os
import json
import time
import uuid
import random
import hashlib
import sys
import mimetypes
import sqlite3
import socket
import werkzeug.utils
import datetime
import logging
from flask import Flask, request, jsonify, send_from_directory, render_template_string, g

# ================= 配置区 =================
app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.secret_key = 'lanchat_hub_secret_key_v1_0_0'

# 性能优化配置
# 启用响应流式传输，减少内存占用
app.config['SEND_FILE_OPTIONS'] = {
    'conditional': True,  # 启用条件请求（ETag, Last-Modified）
    'max_age': 0  # 文件下载不缓存
}

# ================= 管理员密码配置 =================
# 优先级：main.py 配置 > config.json 配置 > 默认密码
# 如果不想在代码中设置密码，请保持为空字符串 ""
# 密码1：账户管理面板密码
ADMIN_PASSWORD_1 = ""  # 留空则使用配置文件或默认密码 "123"
# 密码2：管理员日志查看密码
ADMIN_PASSWORD_2 = ""  # 留空则使用配置文件或默认密码 "321"

# ================= 服务器启动密码配置 =================
# 启动密码：运行程序时需要输入的密码才能启动服务器
# 留空则不需要密码直接启动
# 注意：此密码无法通过 config.json 配置文件更改，只能在此处设置
SERVER_STARTUP_PASSWORD = ""  # 留空则不需要密码

# --- 关键修改：智能路径判断 (USB 便携模式) ---
if getattr(sys, 'frozen', False):
    # 如果是打包后的 EXE，使用 EXE 所在的目录 (即 U 盘目录)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是脚本运行，使用脚本所在目录
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 日志配置 =================
# 配置日志输出到控制台（仅显示警告和错误）
logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('app')

# 修复PyInstaller打包后静态资源访问问题


def get_static_folder():
    """获取静态资源文件夹路径，正确处理PyInstaller打包环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller打包环境，静态资源在_MEIPASS目录中
        static_folder = os.path.join(sys._MEIPASS, 'static')
        # 如果_MEIPASS中没有static目录，则使用exe同级目录的static
        if not os.path.exists(static_folder):
            static_folder = os.path.join(BASE_DIR, 'static')
        return static_folder
    else:
        # 开发环境
        return os.path.join(BASE_DIR, 'static')


UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
STATIC_FOLDER = get_static_folder()
DATA_FILE = os.path.join(BASE_DIR, 'qq_data.json')
DATABASE_FILE = os.path.join(BASE_DIR, 'qq_data.db')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER)
    except OSError:
        pass


# ================= 管理员密码加载 =================
def load_admin_passwords():
    """
    加载管理员密码，优先级：
    1. main.py 中的配置（ADMIN_PASSWORD_1, ADMIN_PASSWORD_2）
    2. config.json 配置文件
    3. 默认密码（"123", "321"）
    
    返回：(password1, password2) 元组
    """
    # 默认密码
    default_password_1 = "123"
    default_password_2 = "321"
    
    # 从配置文件读取
    config_password_1 = None
    config_password_2 = None
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                config_password_1 = config.get('admin_password_1', '')
                config_password_2 = config.get('admin_password_2', '')
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")
    
    # 优先级判断：main.py > config.json > 默认值
    password_1 = ADMIN_PASSWORD_1 if ADMIN_PASSWORD_1 else (config_password_1 if config_password_1 else default_password_1)
    password_2 = ADMIN_PASSWORD_2 if ADMIN_PASSWORD_2 else (config_password_2 if config_password_2 else default_password_2)
    
    return password_1, password_2


# 加载管理员密码
FINAL_ADMIN_PASSWORD_1, FINAL_ADMIN_PASSWORD_2 = load_admin_passwords()

# ================= SQLite 数据库层 =================


def get_db_connection():
    """
    获取当前请求的数据库连接
    
    连接特性：
    - 使用 Flask g 对象存储（请求级别）
    - 预配置所有性能优化 PRAGMA
    - 启用 Row 工厂以支持字典式访问
    - 30 秒超时避免永久阻塞
    
    应用的 PRAGMA 设置：
    - journal_mode=WAL: 启用预写式日志，允许读写并发
    - synchronous=NORMAL: 平衡性能和数据安全性，强制终止时保证数据完整性
    - cache_size=-32000: 32MB 内存缓存，减少磁盘读取
    - temp_store=MEMORY: 临时表存储在内存中，加速临时操作
    - mmap_size=268435456: 256MB 内存映射，将频繁访问的数据缓存在 RAM 中
    - busy_timeout=30000: 30 秒锁等待超时，避免立即的"数据库已锁定"错误
    - wal_autocheckpoint=1000: 每 1000 页自动检查点，防止 WAL 文件无限增长
    - foreign_keys=ON: 启用外键约束，保持数据完整性
    
    返回：
        sqlite3.Connection: 优化配置的数据库连接

    """
    if 'db' not in g:
        # 创建连接，设置 30 秒超时避免永久阻塞
        g.db = sqlite3.connect(DATABASE_FILE, check_same_thread=False, timeout=30.0)
        g.db.row_factory = sqlite3.Row
        
        # ========== 性能优化 PRAGMA 配置 ==========
        # 这些配置针对机械硬盘优化，减少 I/O 阻塞和延迟
        
        # 启用 WAL 模式：允许读写并发，避免"数据库已锁定"错误
        g.db.execute('PRAGMA journal_mode=WAL')
        
        # 设置同步模式为 NORMAL：平衡性能和数据安全性
        # NORMAL 模式在关键时刻同步，即使进程被强制终止也能保证数据完整性
        g.db.execute('PRAGMA synchronous=NORMAL')
        
        # 设置缓存大小为 32MB：减少磁盘读取次数
        # 负值表示 KB 单位，-32000 = 32MB
        g.db.execute('PRAGMA cache_size=-32000')
        
        # 临时表存储在内存：加速临时操作
        g.db.execute('PRAGMA temp_store=MEMORY')
        
        # 设置内存映射大小为 256MB：将频繁访问的数据缓存在 RAM 中
        g.db.execute('PRAGMA mmap_size=268435456')
        
        # 设置锁等待超时为 30 秒：避免立即的"数据库已锁定"错误
        g.db.execute('PRAGMA busy_timeout=30000')
        
        # 设置 WAL 自动检查点：每 1000 页自动合并 WAL 文件
        # 防止 WAL 文件无限增长
        g.db.execute('PRAGMA wal_autocheckpoint=1000')
        
        # 启用外键约束：保持数据完整性
        g.db.execute('PRAGMA foreign_keys=ON')
        
        # ========== 结束性能优化配置 ==========
        
    return g.db


@app.teardown_appcontext
def close_db_connection(exception):
    """请求结束时关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库表结构

    版本控制说明：
    - users 和 groups 表新增 version 字段，用于追踪数据变更
    - 每次 UPDATE/DELETE 操作时递增 version
    - /sync 接口通过比对 version 检测变更，实现实时同步
    
    性能优化说明：
    - 启用 WAL 模式以支持并发读写
    - 配置 synchronous=NORMAL 平衡性能和安全性
    - 设置内存缓存和内存映射以减少磁盘 I/O
    - 配置超时和自动检查点以优化机械硬盘性能
    """
    conn = sqlite3.connect(DATABASE_FILE, timeout=30.0)
    cursor = conn.cursor()
    
    # ========== 性能优化 PRAGMA 配置 ==========
    # 这些配置针对机械硬盘优化，减少 I/O 阻塞和延迟
    
    # 启用 WAL 模式：允许读写并发，避免"数据库已锁定"错误
    cursor.execute('PRAGMA journal_mode=WAL')
    
    # 设置同步模式为 NORMAL：平衡性能和数据安全性
    cursor.execute('PRAGMA synchronous=NORMAL')
    
    # 设置缓存大小为 32MB：减少磁盘读取次数
    cursor.execute('PRAGMA cache_size=-32000')
    
    # 临时表存储在内存：加速临时操作
    cursor.execute('PRAGMA temp_store=MEMORY')
    
    # 设置内存映射大小为 256MB：将频繁访问的数据缓存在 RAM 中
    cursor.execute('PRAGMA mmap_size=268435456')
    
    # 设置 WAL 自动检查点：每 1000 页自动合并 WAL 文件
    cursor.execute('PRAGMA wal_autocheckpoint=1000')
    # ========== 结束性能优化配置 ==========

    # 用户表（新增 version 字段用于变更追踪）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            password TEXT,
            avatar_bg TEXT,
            last_active REAL DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            deleted_at REAL,
            deleted_name TEXT,
            merged_to TEXT,
            merged_at REAL,
            session_invalidated INTEGER DEFAULT 0,
            session_invalidated_at REAL,
            version INTEGER DEFAULT 0
        )
    ''')

    # 迁移：为现有表添加 version 字段（如果不存在）
    try:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN version INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在

    # 迁移：为现有表添加 registered_at 字段（如果不存在）
    try:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN registered_at REAL DEFAULT NULL')
    except sqlite3.OperationalError:
        pass  # 字段已存在

    # 迁移：为现有表添加 unrestricted_access 字段（如果不存在）
    try:
        cursor.execute(
            'ALTER TABLE users ADD COLUMN unrestricted_access INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在

    # 消息表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            from_uid TEXT NOT NULL,
            to_uid TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            content TEXT,
            timestamp REAL,
            is_recalled INTEGER DEFAULT 0,
            quote_json TEXT,
            filename TEXT,
            server_filename TEXT,
            size INTEGER,
            is_img INTEGER DEFAULT 0,
            file_hash TEXT,
            transfer_method TEXT DEFAULT 'server',
            p2p_session_id TEXT
        )
    ''')
    
    # 迁移：为现有表添加 file_hash 字段（如果不存在）
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN file_hash TEXT')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    # 迁移：为现有表添加 transfer_method 字段（如果不存在）
    # transfer_method: 'server' (传统服务器上传) 或 'p2p' (P2P直接传输)
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN transfer_method TEXT DEFAULT \'server\'')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    # 迁移：为现有表添加 p2p_session_id 字段（如果不存在）
    # p2p_session_id: P2P传输的会话ID（仅用于审计）
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN p2p_session_id TEXT')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    # 迁移：为P2P传输添加状态字段
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN p2p_status TEXT DEFAULT NULL')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN p2p_progress REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN p2p_speed INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE messages ADD COLUMN p2p_avg_speed INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    #
    # 索引设计原则：
    # 1. 为高频查询的过滤列创建索引
    # 2. 为 ORDER BY 和 JOIN 列创建索引
    # 3. 使用 CREATE INDEX IF NOT EXISTS 确保幂等性
    #
    # 索引列表及用途：
    # - idx_messages_to_uid: 群聊消息查询（WHERE to_uid = ?）
    # - idx_messages_from_uid: 私聊消息查询（WHERE from_uid = ?）
    # - idx_messages_timestamp: 时间范围过滤（WHERE timestamp >= ?）
    # - idx_users_registered_at: 访问控制查询（WHERE registered_at IS NOT NULL）
    #
    # 性能验证：使用 test_query_performance.py 运行 EXPLAIN QUERY PLAN 分析
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_messages_to_uid ON messages(to_uid)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_messages_from_uid ON messages(from_uid)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_users_registered_at ON users(registered_at)')

    # 群组表（新增 version 字段用于变更追踪）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT,
            is_system INTEGER DEFAULT 0,
            version INTEGER DEFAULT 0
        )
    ''')

    # 迁移：为现有表添加 version 字段（如果不存在）
    try:
        cursor.execute(
            'ALTER TABLE groups ADD COLUMN version INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在

    # 群组成员表（新增 version 字段追踪成员变更）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_members (
            group_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            PRIMARY KEY (group_id, uid),
            FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
    ''')

    # 已读标记表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS read_markers (
            uid TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            msg_id INTEGER DEFAULT 0,
            PRIMARY KEY (uid, chat_id)
        )
    ''')

    # 备注表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS remarks (
            uid TEXT NOT NULL,
            target_uid TEXT NOT NULL,
            remark TEXT,
            PRIMARY KEY (uid, target_uid)
        )
    ''')

    # P2P传输会话表
    # 用于管理P2P文件传输的会话信息
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_sessions (
            session_id TEXT PRIMARY KEY,
            sender_uid TEXT NOT NULL,
            receiver_uid TEXT,
            group_id TEXT,
            chat_type TEXT NOT NULL,
            total_size INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            completed_at REAL,
            error_message TEXT,
            supports_resume INTEGER DEFAULT 1
        )
    ''')
    
    # 迁移：为 p2p_sessions 表添加新字段（如果不存在）
    try:
        cursor.execute('ALTER TABLE p2p_sessions ADD COLUMN protocol_version INTEGER DEFAULT 17')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE p2p_sessions ADD COLUMN truncated_chunks INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE p2p_sessions ADD COLUMN retransmission_count INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    try:
        cursor.execute('ALTER TABLE p2p_sessions ADD COLUMN final_truncation_rate REAL DEFAULT 0.0')
    except sqlite3.OperationalError:
        pass  # 字段已存在
    
    # 为 p2p_sessions 表创建索引以优化查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_sessions_sender ON p2p_sessions(sender_uid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_sessions_receiver ON p2p_sessions(receiver_uid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_sessions_group ON p2p_sessions(group_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_sessions_status ON p2p_sessions(status)')
    
    # P2P会话文件表（多文件支持）
    # 用于存储单个会话中的多个文件信息
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_session_files (
            session_id TEXT NOT NULL,
            file_index INTEGER NOT NULL,
            filename TEXT NOT NULL,
            size INTEGER NOT NULL,
            file_hash TEXT NOT NULL,
            mime_type TEXT,
            status TEXT DEFAULT 'pending',
            completed_at REAL,
            PRIMARY KEY (session_id, file_index),
            FOREIGN KEY (session_id) REFERENCES p2p_sessions(session_id) ON DELETE CASCADE
        )
    ''')
    
    # 为 p2p_session_files 表创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_files_session ON p2p_session_files(session_id)')
    
    # P2P会话参与者表（群聊支持）
    # 用于跟踪群聊中每个成员对P2P传输的响应状态
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_session_participants (
            session_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            responded_at REAL,
            completed_at REAL,
            PRIMARY KEY (session_id, uid),
            FOREIGN KEY (session_id) REFERENCES p2p_sessions(session_id) ON DELETE CASCADE
        )
    ''')
    
    # 为 p2p_session_participants 表创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_participants_uid ON p2p_session_participants(uid)')
    
    # P2P信令数据表（临时存储）
    # 用于转发WebRTC信令数据（offer/answer/ICE候选）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            from_uid TEXT NOT NULL,
            to_uid TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            signal_data TEXT NOT NULL,
            created_at REAL NOT NULL,
            consumed INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES p2p_sessions(session_id) ON DELETE CASCADE
        )
    ''')
    
    # 为 p2p_signals 表创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_signals_session ON p2p_signals(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_signals_to_uid ON p2p_signals(to_uid, consumed)')
    
    # P2P断点续传表
    # 用于记录传输中断时的位置，支持从断点继续传输
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_resume_points (
            session_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            file_index INTEGER NOT NULL,
            offset INTEGER NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (session_id, uid, file_index),
            FOREIGN KEY (session_id) REFERENCES p2p_sessions(session_id) ON DELETE CASCADE
        )
    ''')
    
    # 为 p2p_resume_points 表创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_resume_session ON p2p_resume_points(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_resume_uid ON p2p_resume_points(uid)')

    # P2P传输审计日志表
    # 用于记录所有P2P传输的开始、结果和统计信息（不包含文件内容）
    # 注意：不使用外键约束，因为审计日志应该独立存在，即使会话被删除也要保留
    
    # 迁移：如果表已存在且有外键约束，需要重建表
    try:
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='p2p_audit_logs'")
        if cursor.fetchone():
            # 表存在，检查是否有外键约束
            cursor.execute("PRAGMA foreign_key_list(p2p_audit_logs)")
            if cursor.fetchone():
                # 有外键约束，需要重建表
                # 1. 备份数据
                cursor.execute('''
                    CREATE TEMPORARY TABLE p2p_audit_logs_backup AS 
                    SELECT * FROM p2p_audit_logs
                ''')
                # 2. 删除旧表
                cursor.execute('DROP TABLE p2p_audit_logs')
                # 3. 创建新表（无外键）
                cursor.execute('''
                    CREATE TABLE p2p_audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        sender_uid TEXT NOT NULL,
                        receiver_uid TEXT,
                        group_id TEXT,
                        chat_type TEXT NOT NULL,
                        total_size INTEGER NOT NULL,
                        file_count INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        completed_at REAL,
                        duration REAL,
                        error_message TEXT
                    )
                ''')
                # 4. 恢复数据
                cursor.execute('''
                    INSERT INTO p2p_audit_logs 
                    SELECT * FROM p2p_audit_logs_backup
                ''')
                # 5. 删除备份表
                cursor.execute('DROP TABLE p2p_audit_logs_backup')
            else:
                # 没有外键约束，表结构正确
                pass
        else:
            # 表不存在，创建新表
            cursor.execute('''
                CREATE TABLE p2p_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sender_uid TEXT NOT NULL,
                    receiver_uid TEXT,
                    group_id TEXT,
                    chat_type TEXT NOT NULL,
                    total_size INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    duration REAL,
                    error_message TEXT
                )
            ''')
    except Exception as e:
        # 如果迁移失败，尝试直接创建表
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS p2p_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sender_uid TEXT NOT NULL,
                    receiver_uid TEXT,
                    group_id TEXT,
                    chat_type TEXT NOT NULL,
                    total_size INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    duration REAL,
                    error_message TEXT
                )
            ''')
        except:
            pass
    
    # 为 p2p_audit_logs 表创建索引以优化查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_audit_session ON p2p_audit_logs(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_audit_sender ON p2p_audit_logs(sender_uid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_audit_receiver ON p2p_audit_logs(receiver_uid)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_audit_status ON p2p_audit_logs(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_audit_started ON p2p_audit_logs(started_at)')

    # P2P传输消息表（前端重新设计）
    # 用于在聊天界面中显示和管理P2P传输消息
    # 支持消息持久化、实时同步和状态恢复
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS p2p_transfer_messages (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'p2p_transfer',
            sender_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            
            -- 文件信息
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_type TEXT,
            file_hash TEXT,
            
            -- 传输信息
            transfer_id TEXT NOT NULL,
            transfer_method TEXT DEFAULT 'p2p',
            status TEXT NOT NULL DEFAULT 'pending',
            progress REAL DEFAULT 0,
            speed INTEGER DEFAULT 0,
            avg_speed INTEGER DEFAULT 0,
            estimated_time INTEGER DEFAULT NULL,
            start_time INTEGER DEFAULT NULL,
            end_time INTEGER DEFAULT NULL,
            bytes_transferred INTEGER DEFAULT 0,
            is_valid INTEGER DEFAULT 1,
            
            -- 失效信息
            invalid_reason TEXT DEFAULT NULL,
            invalid_time INTEGER DEFAULT NULL
        )
    ''')
    
    # 为 p2p_transfer_messages 表创建索引以优化查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_sender ON p2p_transfer_messages(sender_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_receiver ON p2p_transfer_messages(receiver_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_chat ON p2p_transfer_messages(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_id ON p2p_transfer_messages(transfer_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_status ON p2p_transfer_messages(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_p2p_transfer_timestamp ON p2p_transfer_messages(timestamp)')

    # 创建默认全员摸鱼群（包含 version 字段）
    cursor.execute('SELECT id FROM groups WHERE id = ?', ('group_global',))
    if cursor.fetchone() is None:
        cursor.execute(
            'INSERT INTO groups (id, name, owner, is_system, version) VALUES (?, ?, ?, ?, ?)',
            ('group_global', '全员摸鱼群', 'system', 1, 0)
        )

    conn.commit()
    conn.close()


# 应用启动时初始化数据库
init_db()

# ================= 核心数据结构 =================

MSG_ID_COUNTER = 0

# 管理员会话管理（用于账户管理面板）
ADMIN_PASSWORD_HASH = hashlib.sha256(FINAL_ADMIN_PASSWORD_1.encode()).hexdigest()
ADMIN_SESSIONS = {}  # {session_token: {'created_at': timestamp, 'expires_at': timestamp}}
ADMIN_SESSION_TIMEOUT = 300  # 5分钟超时

# 已登录用户会话跟踪（用于安全控制）
ACTIVE_USER_SESSIONS = {}  # {uid: {'last_check': timestamp}}


def generate_session_token():
    """生成会话 token"""
    return hashlib.sha256(f"{uuid.uuid4()}{time.time()}".encode()).hexdigest()


def create_admin_session():
    """创建管理员会话"""
    token = generate_session_token()
    ADMIN_SESSIONS[token] = {
        'created_at': time.time(),
        'expires_at': time.time() + ADMIN_SESSION_TIMEOUT
    }
    return token


def validate_admin_session(token):
    """验证管理员会话"""
    if not token or token not in ADMIN_SESSIONS:
        return False
    session = ADMIN_SESSIONS[token]
    if time.time() > session['expires_at']:
        del ADMIN_SESSIONS[token]
        return False
    return True


def terminate_user_sessions(uid):
    """终止用户的所有活跃会话"""
    if uid in ACTIVE_USER_SESSIONS:
        del ACTIVE_USER_SESSIONS[uid]
    # 在数据库中标记会话失效
    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET session_invalidated = 1, session_invalidated_at = ? WHERE uid = ?',
        (time.time(), uid)
    )
    conn.commit()


def get_unique_msg_id():
    global MSG_ID_COUNTER
    now_ms = int(time.time() * 1000)
    if MSG_ID_COUNTER >= 999:
        MSG_ID_COUNTER = 0
    MSG_ID_COUNTER += 1
    return int(f"{now_ms}{MSG_ID_COUNTER:03d}")


def get_local_ip():
    """获取本机局域网IP地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ================= 辅助函数 =================

def generate_kaleidoscope_avatar():
    palettes = [
        ['#a8edea', '#fed6e3'], ['#f5f7fa', '#c3cfe2'], ['#e0c3fc', '#8ec5fc'],
        ['#4facfe', '#00f2fe'], ['#43e97b', '#38f9d7'], ['#fa709a', '#fee140'],
        ['#667eea', '#764ba2'], ['#89f7fe', '#66a6ff'], ['#c471f5', '#fa71cd'],
        ['#ff9a9e', '#fecfef'], ['#fbc2eb', '#a6c1ee'], ['#fdcbf1', '#e6dee9'],
        ['#2AF598', '#009EFD'], ['#B721FF', '#21D4FD'], ['#FF3CAC', '#784BA0']
    ]
    colors = random.choice(palettes)
    c1, c2 = colors[0], colors[1]
    angle = random.randint(0, 360)
    mode = random.choice(['prism', 'aura', 'holo'])
    if mode == 'prism':
        step = random.randint(10, 45)
        return f"radial-gradient(circle at 20% 20%, rgba(255,255,255,0.4), transparent 60%), repeating-conic-gradient(from {angle}deg, {c1} 0deg {step}deg, {c2} {step}deg {step * 2}deg)"
    elif mode == 'aura':
        return f"linear-gradient({angle}deg, rgba(255,255,255,0.6) 0%, transparent 80%), repeating-radial-gradient(circle at 50% 100%, {c1}, {c2} 20%, {c1} 40%)"
    else:
        return f"linear-gradient({angle}deg, {c1}, transparent), linear-gradient({angle + 120}deg, {c2}, transparent), linear-gradient({angle + 240}deg, #ffffff, transparent), {c1}"


def hash_pwd(password):
    return hashlib.sha256(password.encode()).hexdigest()


def is_image_file(filename):
    """
    判断文件是否为图片
    
    Args:
        filename: 文件名
        
    Returns:
        bool: True表示是图片，False表示不是
    """
    if not filename:
        return False
    
    # 获取文件扩展名（转为小写）
    ext = os.path.splitext(filename)[1].lower()
    
    # 支持的图片格式列表
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico', '.tiff', '.tif'}
    
    if ext in image_extensions:
        return True
    
    # 使用 mimetypes 作为备用方案
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type and mime_type.startswith('image')


def calculate_file_hash(file_path):
    """
    计算文件的 SHA256 哈希值
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 文件的 SHA256 哈希值（十六进制字符串）
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # 分块读取文件，避免大文件占用过多内存
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating file hash: {e}")
        return None


def find_file_in_pinned_folder_by_hash(file_hash):
    """
    在置顶文件夹中查找具有指定哈希值的文件
    
    Args:
        file_hash: 文件的 SHA256 哈希值
        
    Returns:
        dict: 包含 relative_path, size, is_img 的字典，如果不存在则返回 None
    """
    if not file_hash:
        return None
    
    pinned_root = os.path.join(UPLOAD_FOLDER, '置顶')
    
    if not os.path.exists(pinned_root):
        return None
    
    try:
        # 递归遍历置顶文件夹
        for root, dirs, files in os.walk(pinned_root):
            for filename in files:
                # 跳过隐藏文件
                if filename.startswith('.'):
                    continue
                
                file_path = os.path.join(root, filename)
                
                # 计算文件哈希
                file_file_hash = calculate_file_hash(file_path)
                
                if file_file_hash == file_hash:
                    # 找到匹配的文件
                    # 计算相对于 uploads 文件夹的路径
                    relative_path = os.path.relpath(file_path, UPLOAD_FOLDER).replace('\\', '/')
                    
                    # 判断是否是图片（使用新的判断函数，支持webp）
                    is_img = 1 if is_image_file(filename) else 0
                    
                    return {
                        'server_filename': relative_path,
                        'size': os.path.getsize(file_path),
                        'is_img': is_img
                    }
        
        return None
        
    except Exception as e:
        logger.error(f"Error finding file in pinned folder by hash: {e}")
        return None


def find_existing_file_by_hash(file_hash):
    """
    根据文件哈希值查找已存在的文件
    
    优先级：
    1. 置顶文件夹中的文件
    2. 数据库中已有的文件记录
    
    Args:
        file_hash: 文件的 SHA256 哈希值
        
    Returns:
        dict: 包含 server_filename, size, is_img 的字典，如果不存在则返回 None
    """
    if not file_hash:
        return None
    
    # 优先查找置顶文件夹中的文件
    pinned_file = find_file_in_pinned_folder_by_hash(file_hash)
    if pinned_file:
        return pinned_file
    
    try:
        conn = get_db_connection()
        # 查找具有相同哈希值的文件记录
        result = conn.execute(
            '''SELECT server_filename, size, is_img 
               FROM messages 
               WHERE file_hash = ? AND server_filename IS NOT NULL
               LIMIT 1''',
            (file_hash,)
        ).fetchone()
        
        if result:
            # 验证文件是否真实存在
            server_filename = result['server_filename']
            filepath = os.path.join(UPLOAD_FOLDER, server_filename)
            if os.path.exists(filepath):
                return {
                    'server_filename': server_filename,
                    'size': result['size'],
                    'is_img': result['is_img']
                }
            else:
                # 文件记录存在但实际文件不存在，记录警告
                logger.warning(f"File record exists but file missing: {server_filename}")
                return None
        
        return None
    except Exception as e:
        logger.error(f"Error finding existing file by hash: {e}")
        return None


def log_p2p_transfer_start(session_id, sender_uid, receiver_uid, group_id, chat_type, total_size, file_count):
    """
    记录P2P传输开始的审计日志
    

    Args:
        session_id: P2P会话ID
        sender_uid: 发送方用户ID
        receiver_uid: 接收方用户ID（私聊时使用）
        group_id: 群组ID（群聊时使用）
        chat_type: 聊天类型（'private' 或 'group'）
        total_size: 文件总大小（字节）
        file_count: 文件数量
    
    """
    try:
        conn = get_db_connection()
        started_at = time.time()
        
        # 插入审计日志记录（不包含文件内容，只记录元数据）
        conn.execute(
            '''INSERT INTO p2p_audit_logs 
               (session_id, sender_uid, receiver_uid, group_id, chat_type, 
                total_size, file_count, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)''',
            (session_id, sender_uid, receiver_uid, group_id, chat_type, 
             total_size, file_count, started_at)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error logging P2P transfer start: {e}")


def log_p2p_transfer_result(session_id, status, error_message=None):
    """
    记录P2P传输结果的审计日志
    

    Args:
        session_id: P2P会话ID
        status: 最终状态（'completed', 'failed', 'cancelled', 'timeout'）
        error_message: 错误信息（如果失败）
    
    """
    try:
        conn = get_db_connection()
        completed_at = time.time()
        
        # 查找对应的开始日志记录
        log_entry = conn.execute(
            'SELECT started_at FROM p2p_audit_logs WHERE session_id = ? ORDER BY id DESC LIMIT 1',
            (session_id,)
        ).fetchone()
        
        if log_entry:
            started_at = log_entry['started_at']
            duration = completed_at - started_at
            
            # 更新审计日志记录
            conn.execute(
                '''UPDATE p2p_audit_logs 
                   SET status = ?, completed_at = ?, duration = ?, error_message = ?
                   WHERE session_id = ? AND status = 'started' ''',
                (status, completed_at, duration, error_message, session_id)
            )
            conn.commit()

        else:
            logger.warning(f"No start log found for session {session_id}")
    except Exception as e:
        logger.error(f"Error logging P2P transfer result: {e}")


def detect_p2p_anomalies():
    """
    检测P2P传输异常模式并记录警告
    
    检测以下异常：
    - 频繁失败：同一用户在短时间内多次传输失败
    - 异常大文件：超过正常范围的文件大小
    - 异常传输模式：可疑的传输行为
    

    Returns:
        dict: 包含检测到的异常信息
    """
    try:
        conn = get_db_connection()
        current_time = time.time()
        anomalies = []
        
        # 检测频繁失败：过去1小时内同一用户失败超过5次
        one_hour_ago = current_time - 60 * 60
        frequent_failures = conn.execute(
            '''SELECT sender_uid, COUNT(*) as failure_count
               FROM p2p_audit_logs
               WHERE status IN ('failed', 'timeout') 
               AND started_at > ?
               GROUP BY sender_uid
               HAVING failure_count >= 5
               ORDER BY failure_count DESC''',
            (one_hour_ago,)
        ).fetchall()
        
        for row in frequent_failures:
            anomaly = {
                'type': 'frequent_failures',
                'user_id': row['sender_uid'],
                'failure_count': row['failure_count'],
                'time_window': '1 hour',
                'severity': 'high' if row['failure_count'] >= 10 else 'medium'
            }
            anomalies.append(anomaly)
            logger.warning(
                f"P2P anomaly detected: Frequent failures - "
                f"user={row['sender_uid']}, failures={row['failure_count']} in 1 hour"
            )
        
        # 检测异常大文件：超过10GB的文件
        large_file_threshold = 10 * 1024 * 1024 * 1024  # 10GB
        large_files = conn.execute(
            '''SELECT session_id, sender_uid, total_size, file_count
               FROM p2p_audit_logs
               WHERE total_size > ?
               AND started_at > ?
               ORDER BY total_size DESC
               LIMIT 10''',
            (large_file_threshold, one_hour_ago)
        ).fetchall()
        
        for row in large_files:
            anomaly = {
                'type': 'large_file',
                'session_id': row['session_id'],
                'user_id': row['sender_uid'],
                'file_size': row['total_size'],
                'file_count': row['file_count'],
                'severity': 'low'
            }
            anomalies.append(anomaly)
            logger.warning(
                f"P2P anomaly detected: Large file transfer - "
                f"user={row['sender_uid']}, size={row['total_size']} bytes, "
                f"session={row['session_id']}"
            )
        
        # 检测异常传输模式：同一用户在短时间内发起大量传输
        high_frequency_threshold = 20  # 1小时内超过20次传输
        high_frequency_users = conn.execute(
            '''SELECT sender_uid, COUNT(*) as transfer_count
               FROM p2p_audit_logs
               WHERE started_at > ?
               GROUP BY sender_uid
               HAVING transfer_count >= ?
               ORDER BY transfer_count DESC''',
            (one_hour_ago, high_frequency_threshold)
        ).fetchall()
        
        for row in high_frequency_users:
            anomaly = {
                'type': 'high_frequency',
                'user_id': row['sender_uid'],
                'transfer_count': row['transfer_count'],
                'time_window': '1 hour',
                'severity': 'medium'
            }
            anomalies.append(anomaly)
            logger.warning(
                f"P2P anomaly detected: High frequency transfers - "
                f"user={row['sender_uid']}, count={row['transfer_count']} in 1 hour"
            )
        
        # 检测长时间未完成的会话
        long_running_threshold = current_time - 2 * 60 * 60  # 2小时前创建的会话
        long_running_sessions = conn.execute(
            '''SELECT session_id, sender_uid, total_size, created_at, status
               FROM p2p_sessions
               WHERE status IN ('active', 'connecting')
               AND created_at < ?
               ORDER BY created_at ASC
               LIMIT 10''',
            (long_running_threshold,)
        ).fetchall()
        
        for row in long_running_sessions:
            duration = current_time - row['created_at']
            anomaly = {
                'type': 'long_running_session',
                'session_id': row['session_id'],
                'user_id': row['sender_uid'],
                'duration': duration,
                'status': row['status'],
                'severity': 'medium'
            }
            anomalies.append(anomaly)
            logger.warning(
                f"P2P anomaly detected: Long running session - "
                f"session={row['session_id']}, user={row['sender_uid']}, "
                f"duration={duration:.0f}s, status={row['status']}"
            )
        
        return {
            'anomalies_detected': len(anomalies),
            'anomalies': anomalies
        }
        
    except Exception as e:
        logger.error(f"Error in detect_p2p_anomalies: {e}")
        return {
            'anomalies_detected': 0,
            'anomalies': [],
            'error': str(e)
        }


def cleanup_expired_p2p_sessions():
    """
    清理过期的P2P会话和断点续传数据
    
    定时任务清理30分钟无活动的会话，清理24小时过期的断点数据
    
    清理规则:
    - 清理超过30分钟且状态为pending或active的会话
    - 清理超过24小时的断点续传数据
    - 清理超过1小时的已消费信令数据
    

    Returns:
        dict: 包含清理统计信息
    """
    try:
        conn = get_db_connection()
        current_time = time.time()
        
        expired_sessions = conn.execute(
            '''SELECT session_id FROM p2p_sessions 
               WHERE expires_at < ? AND status IN ('pending', 'active', 'connecting')''',
            (current_time,)
        ).fetchall()
        
        expired_count = 0
        for session in expired_sessions:
            session_id = session['session_id']
            conn.execute(
                'UPDATE p2p_sessions SET status = ?, error_message = ? WHERE session_id = ?',
                ('failed', '会话超时', session_id)
            )
            log_p2p_transfer_result(
                session_id=session_id,
                status='timeout',
                error_message='会话超时'
            )
            expired_count += 1
        
        resume_cutoff = current_time - 24 * 60 * 60  # 24小时前
        resume_result = conn.execute(
            'DELETE FROM p2p_resume_points WHERE updated_at < ?',
            (resume_cutoff,)
        )
        resume_count = resume_result.rowcount
        
        # 清理超过1小时的已消费信令数据
        signal_cutoff = current_time - 60 * 60  # 1小时前
        signal_result = conn.execute(
            'DELETE FROM p2p_signals WHERE consumed = 1 AND created_at < ?',
            (signal_cutoff,)
        )
        signal_count = signal_result.rowcount
        
        conn.commit()
        

        
        return {
            'expired_sessions': expired_count,
            'resume_points': resume_count,
            'signals': signal_count
        }
        
    except Exception as e:
        logger.error(f"Error in cleanup_expired_p2p_sessions: {e}")
        return {
            'expired_sessions': 0,
            'resume_points': 0,
            'signals': 0,
            'error': str(e)
        }


def get_user_groups(uid):
    """获取用户所在的所有群组"""
    conn = get_db_connection()
    user_groups = {}

    # 获取所有群组
    groups = conn.execute('SELECT * FROM groups').fetchall()
    for group in groups:
        gid = group['id']
        # 检查是否是系统群或用户是群成员
        if gid == 'group_global':
            members = [row['uid'] for row in conn.execute(
                'SELECT uid FROM group_members WHERE group_id = ?', (gid,)
            ).fetchall()]
            user_groups[gid] = {
                'id': gid,
                'name': group['name'],
                'members': members,
                'is_group': True,
                'system': bool(group['is_system']),
                'owner': group['owner']
            }
        else:
            # 检查用户是否在群中
            member = conn.execute(
                'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
                (gid, uid)
            ).fetchone()
            if member:
                members = [row['uid'] for row in conn.execute(
                    'SELECT uid FROM group_members WHERE group_id = ?', (gid,)
                ).fetchall()]
                user_groups[gid] = {
                    'id': gid,
                    'name': group['name'],
                    'members': members,
                    'is_group': True,
                    'system': bool(group['is_system']),
                    'owner': group['owner']
                }
    return user_groups


def check_permission(uid, msg_dict):
    """检查用户是否有权限查看消息"""
    to_uid = msg_dict.get('to_uid')
    conn = get_db_connection()

    # 检查是否是群组消息
    group = conn.execute(
        'SELECT id FROM groups WHERE id = ?', (to_uid,)).fetchone()
    if group:
        if to_uid == 'group_global':
            return True
        # 检查用户是否在群中
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            (to_uid, uid)
        ).fetchone()
        return member is not None

    # 私聊消息
    return uid == msg_dict.get('from_uid') or uid == to_uid


# ================= 访问控制函数 =================

def apply_registration_time_filter(uid, base_query, params):
    """
    应用基于注册时间的消息过滤
    
    实现三级优先级逻辑：
    1. unrestricted_access = 1 → 无限制访问（最高优先级）
    2. registered_at IS NULL → 无限制访问（向后兼容）
    3. 正常过滤逻辑 → 基于注册时间过滤（带60秒容差）
    

    Args:
        uid: 用户ID
        base_query: 基础 SQL 查询字符串
        params: 查询参数列表
    
    Returns:
        (modified_query, modified_params): 修改后的查询和参数
    """
    try:
        conn = get_db_connection()
        
        # 查询用户的注册时间和无限制访问状态
        user = conn.execute(
            'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
            (uid,)
        ).fetchone()
        
        if not user:
            # 用户不存在，返回原查询（不应该发生，但作为安全默认）
            logger.warning(f"Access control filter: User not found - uid={uid}")
            return (base_query, params)
        
        # NULL 值处理
        unrestricted_access = user['unrestricted_access'] if user['unrestricted_access'] is not None else 0
        registered_at = user['registered_at']
        
        # 优先级 1: 管理员授权的无限制访问
        if unrestricted_access == 1:
            return (base_query, params)
        
        # 优先级 2: 向后兼容 - NULL 表示无限制访问
        if registered_at is None:
            return (base_query, params)
        
        # 时钟偏差容差 - 添加 60 秒容差
        # 这样可以处理服务器时钟不同步的情况
        tolerance = 60  # 60秒容差
        adjusted_registered_at = registered_at - tolerance
        
        # 检测时钟偏差并记录警告
        current_time = time.time()
        if registered_at > current_time:
            # 注册时间在未来，说明存在时钟偏差
            skew_seconds = registered_at - current_time
            logger.warning(
                f"Clock skew detected - "
                f"uid={uid}, "
                f"registered_at={registered_at}, "
                f"current_time={current_time}, "
                f"skew={skew_seconds:.2f} seconds (registration time is in the future)"
            )
        
        # 优先级 3: 正常过滤逻辑（使用调整后的注册时间）
        # 添加时间过滤条件：消息时间戳 >= 调整后的注册时间 OR 消息是用户自己发送的
        # 注意：需要在 WHERE 子句中添加条件
        
        # 检查查询中是否已有 WHERE 子句
        if 'WHERE' in base_query.upper():
            # 已有 WHERE，使用 AND 添加条件
            modified_query = base_query.replace(
                'WHERE',
                'WHERE (timestamp >= ? OR from_uid = ?) AND',
                1  # 只替换第一个 WHERE
            )
        else:
            # 没有 WHERE，需要在 ORDER BY 或 LIMIT 之前添加
            # 查找插入位置
            insert_pos = -1
            for keyword in ['ORDER BY', 'LIMIT', 'GROUP BY']:
                pos = base_query.upper().find(keyword)
                if pos != -1:
                    if insert_pos == -1 or pos < insert_pos:
                        insert_pos = pos
            
            if insert_pos != -1:
                modified_query = (
                    base_query[:insert_pos] +
                    'WHERE (timestamp >= ? OR from_uid = ?) ' +
                    base_query[insert_pos:]
                )
            else:
                # 没有找到关键字，添加到末尾
                modified_query = base_query + ' WHERE (timestamp >= ? OR from_uid = ?)'
        
        # 在参数列表开头添加过滤参数（使用调整后的注册时间）
        modified_params = [adjusted_registered_at, uid] + params
        return (modified_query, modified_params)
    
    except sqlite3.Error as e:
        # 数据库错误处理 - 记录完整错误堆栈
        logger.error(
            f"Database error in apply_registration_time_filter - "
            f"uid={uid}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 返回原查询作为安全默认（允许访问，避免完全阻止用户）
        return (base_query, params)
    
    except Exception as e:
        # 捕获其他异常
        logger.error(
            f"Unexpected error in apply_registration_time_filter - "
            f"uid={uid}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 返回原查询作为安全默认
        return (base_query, params)


def is_message_accessible(uid, msg_id):
    """
    检查用户是否有权访问指定消息
    
    用于引用消息访问控制：如果用户有权访问父消息，则允许访问引用消息
    
    Args:
        uid: 用户ID
        msg_id: 消息ID
    
    Returns:
        bool: True 表示可访问，False 表示不可访问
    """
    # 数据库错误处理
    try:
        conn = get_db_connection()
        
        # 获取消息
        msg = conn.execute(
            'SELECT from_uid, timestamp FROM messages WHERE id = ?',
            (msg_id,)
        ).fetchone()
        
        if not msg:
            # 消息不存在，返回不可访问
            return False
        
        # NULL 值处理 - 处理消息时间戳为 NULL 的情况
        msg_timestamp = msg['timestamp']
        if msg_timestamp is None:
            # 消息时间戳无效，作为安全默认允许访问
            logger.warning(f"Message has NULL timestamp - msg_id={msg_id}, treating as accessible")
            return True
        
        # 获取用户的访问控制信息
        user = conn.execute(
            'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
            (uid,)
        ).fetchone()
        
        if not user:
            # 用户不存在，返回不可访问
            return False
        
        # NULL 值处理
        unrestricted_access = user['unrestricted_access'] if user['unrestricted_access'] is not None else 0
        registered_at = user['registered_at']
        
        # 优先级 1: 无限制访问
        if unrestricted_access == 1:
            return True
        
        # 优先级 2: 向后兼容 - NULL 表示无限制访问
        if registered_at is None:
            return True
        
        # 优先级 3: 检查是否是用户自己发送的消息
        if msg['from_uid'] == uid:
            return True
        
        # 时钟偏差容差 - 添加 60 秒容差
        tolerance = 60
        adjusted_registered_at = registered_at - tolerance
        
        # 优先级 4: 检查消息时间戳是否在调整后的注册时间之后
        if msg_timestamp >= adjusted_registered_at:
            return True
        
        # 不满足任何条件，不可访问
        return False
    
    except sqlite3.Error as e:
        # 数据库错误处理
        logger.error(
            f"Database error in is_message_accessible - "
            f"uid={uid}, msg_id={msg_id}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 作为安全默认，返回 False（拒绝访问）
        return False
    
    except Exception as e:
        # 捕获其他异常
        logger.error(
            f"Unexpected error in is_message_accessible - "
            f"uid={uid}, msg_id={msg_id}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 作为安全默认，返回 False
        return False


def enrich_quoted_message(uid, msg_dict):
    """
    为消息中的引用内容补充完整信息（如果用户有权访问）
    
    - 如果用户有权访问父消息，则在引用中包含完整的消息内容
    - 如果用户无权访问父消息，则标记为不可访问
    
    Args:
        uid: 用户ID
        msg_dict: 消息字典（已解析 quote_json）
    
    Returns:
        修改后的 msg_dict（原地修改）
    """
    if not msg_dict.get('quote') or not msg_dict['quote'].get('id'):
        # 没有引用或引用ID无效
        return msg_dict
    
    try:
        quoted_msg_id = int(msg_dict['quote']['id'])
    except (ValueError, TypeError):
        # 引用ID无效
        return msg_dict
    
    # 首先获取被引用的消息
    conn = get_db_connection()
    quoted_msg = conn.execute(
        'SELECT * FROM messages WHERE id = ?',
        (quoted_msg_id,)
    ).fetchone()
    
    if not quoted_msg:
        # 被引用的消息不存在（可能已被删除）
        msg_dict['quote']['accessible'] = False
        msg_dict['quote']['access_denied_reason'] = '原消息不存在'
        return msg_dict
    
    # 检查用户是否有权访问被引用的消息
    if not is_message_accessible(uid, quoted_msg_id):
        # 用户无权访问被引用的消息，标记为不可访问
        msg_dict['quote']['accessible'] = False
        msg_dict['quote']['access_denied_reason'] = '该消息发送于您的注册时间之前'
        return msg_dict
    
    # 用户有权访问，补充完整的引用消息信息
    msg_dict['quote']['accessible'] = True
    msg_dict['quote']['from_uid'] = quoted_msg['from_uid']
    msg_dict['quote']['content'] = quoted_msg['content']
    msg_dict['quote']['type'] = quoted_msg['type']
    msg_dict['quote']['timestamp'] = quoted_msg['timestamp']
    msg_dict['quote']['is_recalled'] = bool(quoted_msg['is_recalled'])
    
    # 如果引用的消息是文件类型，也包含文件信息
    if quoted_msg['type'] in ['file', 'image']:
        msg_dict['quote']['filename'] = quoted_msg['filename']
        msg_dict['quote']['size'] = quoted_msg['size']
        msg_dict['quote']['is_img'] = bool(quoted_msg['is_img'])
    
    return msg_dict


def log_filtered_message_count(uid, chat_id, chat_type, result_count):
    """
    记录过滤后的消息数量审计日志
    
    此函数应在查询执行后调用，用于记录实际返回的消息数量
    
    Args:
        uid: 用户ID
        chat_id: 聊天目标ID
        chat_type: 'group' 或 'private'
        result_count: 查询返回的消息数量
    """
    conn = get_db_connection()
    
    # 获取用户的访问控制信息
    user = conn.execute(
        'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
        (uid,)
    ).fetchone()
    
    if not user:
        return
    
    unrestricted_access = user['unrestricted_access'] or 0
    registered_at = user['registered_at']
    
    # 如果有访问限制，计算被过滤的消息数量
    if unrestricted_access == 0 and registered_at is not None:
        # 计算该聊天中被过滤的消息总数
        if chat_type == 'group':
            restricted_count = conn.execute(
                '''SELECT COUNT(*) as cnt FROM messages 
                   WHERE to_uid = ? AND timestamp < ? AND from_uid != ?''',
                (chat_id, registered_at, uid)
            ).fetchone()
        else:
            # 私聊
            if chat_id == uid:
                restricted_count = conn.execute(
                    '''SELECT COUNT(*) as cnt FROM messages 
                       WHERE from_uid = ? AND to_uid = ? AND timestamp < ? AND from_uid != ?''',
                    (uid, uid, registered_at, uid)
                ).fetchone()
            else:
                restricted_count = conn.execute(
                    '''SELECT COUNT(*) as cnt FROM messages 
                       WHERE ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?))
                       AND timestamp < ? AND from_uid != ?''',
                    (uid, chat_id, chat_id, uid, registered_at, uid)
                ).fetchone()
        
        filtered_count = restricted_count['cnt'] if restricted_count else 0


def get_access_boundary_info(uid, chat_id, chat_type):
    """
    获取用户在特定聊天中的访问边界信息
    
    Args:
        uid: 用户ID
        chat_id: 聊天目标ID（群组ID或私聊对方UID）
        chat_type: 'group' 或 'private'
    
    Returns:
        {
            'has_restricted_access': bool,      # 是否有访问限制
            'registration_time': float,         # 注册时间戳
            'registration_date': str,           # 格式化的注册日期
            'oldest_accessible_msg_id': str,    # 最早可访问的消息ID
            'total_restricted_count': int,      # 被限制的消息总数
            'reached': bool                     # 是否已到达边界
        }
    """
    # 数据库错误处理
    try:
        conn = get_db_connection()
        
        # 查询用户的注册时间和无限制访问状态
        user = conn.execute(
            'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
            (uid,)
        ).fetchone()
        
        if not user:
            # 用户不存在，返回默认值
            return {
                'has_restricted_access': False,
                'registration_time': None,
                'registration_date': None,
                'oldest_accessible_msg_id': None,
                'total_restricted_count': 0,
                'reached': False
            }
        
        # NULL 值处理
        unrestricted_access = user['unrestricted_access'] if user['unrestricted_access'] is not None else 0
        registered_at = user['registered_at']
        
        # 如果有无限制访问权限或注册时间为 NULL，则无限制
        if unrestricted_access == 1 or registered_at is None:
            return {
                'has_restricted_access': False,
                'registration_time': None,
                'registration_date': None,
                'oldest_accessible_msg_id': None,
                'total_restricted_count': 0,
                'reached': False
            }
        
        # 格式化注册日期
        try:
            registration_date = datetime.datetime.fromtimestamp(registered_at).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError) as e:
            # 处理无效的时间戳
            logger.warning(f"Invalid registered_at timestamp - uid={uid}, registered_at={registered_at}, error={str(e)}")
            registration_date = "Invalid Date"
        
        # 时钟偏差容差 - 使用调整后的注册时间
        tolerance = 60
        adjusted_registered_at = registered_at - tolerance
        
        # 构建查询条件（使用调整后的注册时间）
        if chat_type == 'group':
            # 群聊：查询该群中最早可访问的消息
            oldest_msg = conn.execute(
                '''SELECT id FROM messages 
                   WHERE to_uid = ? AND (timestamp >= ? OR from_uid = ?)
                   ORDER BY id ASC LIMIT 1''',
                (chat_id, adjusted_registered_at, uid)
            ).fetchone()
            
            # 统计被限制的消息数量（使用调整后的注册时间）
            restricted_count = conn.execute(
                '''SELECT COUNT(*) as cnt FROM messages 
                   WHERE to_uid = ? AND timestamp < ? AND from_uid != ?''',
                (chat_id, adjusted_registered_at, uid)
            ).fetchone()
        else:
            # 私聊：查询双方消息中最早可访问的
            if chat_id == uid:
                # 与自己聊天
                oldest_msg = conn.execute(
                    '''SELECT id FROM messages 
                       WHERE from_uid = ? AND to_uid = ? AND (timestamp >= ? OR from_uid = ?)
                       ORDER BY id ASC LIMIT 1''',
                    (uid, uid, adjusted_registered_at, uid)
                ).fetchone()
                
                restricted_count = conn.execute(
                    '''SELECT COUNT(*) as cnt FROM messages 
                       WHERE from_uid = ? AND to_uid = ? AND timestamp < ? AND from_uid != ?''',
                    (uid, uid, adjusted_registered_at, uid)
                ).fetchone()
            else:
                # 普通私聊
                oldest_msg = conn.execute(
                    '''SELECT id FROM messages 
                       WHERE ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?))
                       AND (timestamp >= ? OR from_uid = ?)
                       ORDER BY id ASC LIMIT 1''',
                    (uid, chat_id, chat_id, uid, adjusted_registered_at, uid)
                ).fetchone()
                
                restricted_count = conn.execute(
                    '''SELECT COUNT(*) as cnt FROM messages 
                       WHERE ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?))
                       AND timestamp < ? AND from_uid != ?''',
                    (uid, chat_id, chat_id, uid, adjusted_registered_at, uid)
                ).fetchone()
        
        oldest_accessible_msg_id = str(oldest_msg['id']) if oldest_msg else None
        total_restricted_count = restricted_count['cnt'] if restricted_count else 0
        
        return {
            'has_restricted_access': True,
            'registration_time': registered_at,
            'registration_date': registration_date,
            'oldest_accessible_msg_id': oldest_accessible_msg_id,
            'total_restricted_count': total_restricted_count,
            'reached': False  # 这个字段在实际使用时会被更新
        }
    
    except sqlite3.Error as e:
        # 数据库错误处理
        logger.error(
            f"Database error in get_access_boundary_info - "
            f"uid={uid}, chat_id={chat_id}, chat_type={chat_type}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 返回默认值（无限制访问）作为安全默认
        return {
            'has_restricted_access': False,
            'registration_time': None,
            'registration_date': None,
            'oldest_accessible_msg_id': None,
            'total_restricted_count': 0,
            'reached': False
        }
    
    except Exception as e:
        # 捕获其他异常
        logger.error(
            f"Unexpected error in get_access_boundary_info - "
            f"uid={uid}, chat_id={chat_id}, chat_type={chat_type}, "
            f"error={str(e)}",
            exc_info=True
        )
        # 返回默认值
        return {
            'has_restricted_access': False,
            'registration_time': None,
            'registration_date': None,
            'oldest_accessible_msg_id': None,
            'total_restricted_count': 0,
            'reached': False
        }


# ================= API =================

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/test_p2p')
def test_p2p():
    with open('test_p2p_load.html', 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/test_p2p_api_page')
def test_p2p_api_page():
    with open('test_p2p_api.html', 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/test_p2p_api', methods=['POST'])
def test_p2p_api():
    """测试P2P API是否可访问"""
    try:
        data = request.json
        return jsonify({
            'status': 'ok',
            'received': data,
            'message': 'P2P API is working'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_user_info', methods=['POST'])
def get_user_info():
    uid = request.json.get('uid')
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE uid = ?', (uid,)).fetchone()

    if user:
        # **安全控制：检查账户状态**
        if user['deleted'] or user['session_invalidated']:
            return jsonify({
                'error': 'session_invalidated',
                'message': '您的账户已被禁用，请重新登录'
            }), 403

        # 更新最后活跃时间
        conn.execute(
            'UPDATE users SET last_active = ? WHERE uid = ?', (time.time(), uid))

        # 确保用户在全员群中
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            ('group_global', uid)
        ).fetchone()
        if not member:
            conn.execute(
                'INSERT OR IGNORE INTO group_members (group_id, uid) VALUES (?, ?)',
                ('group_global', uid)
            )
        conn.commit()

        return jsonify({
            'uid': uid,
            'name': user['name'],
            'avatar_bg': user['avatar_bg'] or '#ccc'
        })

    return jsonify({'error': 'User not found'}), 404


@app.route('/login', methods=['POST'])
def login():
    nickname = request.json.get('nickname')
    password = request.json.get('password')
    if not nickname or not password:
        return jsonify({'error': 'Required fields missing'}), 400

    try:
        conn = get_db_connection()

        # 查找用户
        user = conn.execute(
            'SELECT * FROM users WHERE name = ?', (nickname,)).fetchone()

        if user:
            uid = user['uid']
            # 检查账户是否已被删除或合并
            if user['deleted']:
                return jsonify({'error': '该账户已被禁用，无法登录'}), 403

            stored_pwd = user['password']
            if stored_pwd:
                if stored_pwd != hash_pwd(password):
                    return jsonify({'error': '密码错误'}), 401
            else:
                conn.execute(
                    'UPDATE users SET password = ? WHERE uid = ?', (hash_pwd(password), uid))

            # 更新最后活跃时间
            conn.execute(
                'UPDATE users SET last_active = ?, session_invalidated = 0 WHERE uid = ?', (time.time(), uid))
            avatar_bg = user['avatar_bg']
        else:
            # 创建新用户
            uid = str(uuid.uuid4())[:8]
            avatar_bg = generate_kaleidoscope_avatar()
            current_time = time.time()
            # 为新用户设置 registered_at
            conn.execute(
                'INSERT INTO users (uid, name, password, avatar_bg, last_active, registered_at) VALUES (?, ?, ?, ?, ?, ?)',
                (uid, nickname, hash_pwd(password), avatar_bg, current_time, current_time)
            )

        # 确保用户在全员群中
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            ('group_global', uid)
        ).fetchone()
        if not member:
            conn.execute(
                'INSERT OR IGNORE INTO group_members (group_id, uid) VALUES (?, ?)',
                ('group_global', uid)
            )

        conn.commit()

        return jsonify({'uid': uid, 'name': nickname, 'avatar_bg': avatar_bg})
    except Exception as e:
        return jsonify({'error': 'Server Error'}), 500


@app.route('/update_profile', methods=['POST'])
def update_profile():
    uid = request.json.get('uid')
    new_nick = request.json.get('nickname')
    new_pwd = request.json.get('password')

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE uid = ?', (uid,)).fetchone()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    if new_nick and new_nick != user['name']:
        # 检查昵称是否已存在
        existing = conn.execute(
            'SELECT uid FROM users WHERE name = ? AND uid != ?',
            (new_nick, uid)
        ).fetchone()
        if existing:
            return jsonify({'error': '昵称已存在'}), 400
        # 版本控制：昵称变更时递增 version，确保其他用户能通过 /sync 检测到变化
        conn.execute('UPDATE users SET name = ?, version = version + 1 WHERE uid = ?',
                     (new_nick, uid))

    if new_pwd:
        conn.execute('UPDATE users SET password = ? WHERE uid = ?',
                     (hash_pwd(new_pwd), uid))

    conn.commit()

    result_name = new_nick if new_nick else user['name']
    return jsonify({'status': 'ok', 'name': result_name})


@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    uid = request.json.get('uid')
    conn = get_db_connection()
    user = conn.execute(
        'SELECT uid FROM users WHERE uid = ?', (uid,)).fetchone()

    if user:
        new_bg = generate_kaleidoscope_avatar()
        # 版本控制：头像变更时递增 version，确保其他用户能通过 /sync 检测到变化
        conn.execute(
            'UPDATE users SET avatar_bg = ?, version = version + 1 WHERE uid = ?', (new_bg, uid))
        conn.commit()
        return jsonify({'status': 'ok', 'avatar_bg': new_bg})

    return jsonify({'error': 'User not found'}), 404


@app.route('/set_remark', methods=['POST'])
def set_remark():
    uid = request.json.get('uid')
    target_uid = request.json.get('target_uid')
    remark = request.json.get('remark')
    if not uid or not target_uid:
        return jsonify({'error': 'Missing args'}), 400

    conn = get_db_connection()

    if not remark:
        conn.execute(
            'DELETE FROM remarks WHERE uid = ? AND target_uid = ?',
            (uid, target_uid)
        )
    else:
        conn.execute(
            'INSERT OR REPLACE INTO remarks (uid, target_uid, remark) VALUES (?, ?, ?)',
            (uid, target_uid, remark)
        )

    conn.commit()
    return jsonify({'status': 'ok'})


@app.route('/nudge', methods=['POST'])
def nudge():
    uid = request.json.get('uid')
    target_uid = request.json.get('target_uid')
    group_id = request.json.get('group_id')

    conn = get_db_connection()
    to_id = group_id if group_id else target_uid

    if group_id:
        group = conn.execute(
            'SELECT id FROM groups WHERE id = ?', (group_id,)).fetchone()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            (group_id, uid)
        ).fetchone()
        if not member:
            return jsonify({'error': 'Not in group'}), 403

    content = json.dumps({
        'sys_type': 'nudge',
        'from_uid': uid,
        'target_uid': target_uid
    })

    msg_id = get_unique_msg_id()
    conn.execute(
        '''INSERT INTO messages (id, from_uid, to_uid, type, content, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (msg_id, uid, to_id, 'system', content, time.time())
    )
    conn.commit()

    return jsonify({'status': 'ok'})


@app.route('/mark_read', methods=['POST'])
def mark_read():
    """
    标记已读接口 - 重构版本

    功能：
    1. 更新用户对某个聊天的已读位置
    2. 计算并返回剩余未读数，支持前端乐观更新校验

    返回：
    - status: 'ok'
    - updated: 是否实际更新了已读位置
    - unread_count: 标记后的剩余未读数
    - read_position: 当前已读位置（String 类型）
    """
    uid = request.json.get('uid')
    chat_id = request.json.get('chat_id')
    msg_id_raw = request.json.get('msg_id')

    # 类型安全：统一转换为整数进行比较
    try:
        msg_id = int(msg_id_raw) if msg_id_raw else 0
    except (ValueError, TypeError):
        msg_id = 0

    conn = get_db_connection()

    # 获取当前已读位置
    current = conn.execute(
        'SELECT msg_id FROM read_markers WHERE uid = ? AND chat_id = ?',
        (uid, chat_id)
    ).fetchone()
    current_id = int(current['msg_id']) if current and current['msg_id'] else 0

    updated = False
    if msg_id > current_id:
        conn.execute(
            'INSERT OR REPLACE INTO read_markers (uid, chat_id, msg_id) VALUES (?, ?, ?)',
            (uid, chat_id, msg_id)
        )
        conn.commit()
        updated = True
        current_id = msg_id  # 更新为新的已读位置

    # 计算剩余未读数
    unread_count = 0

    # 判断是群聊还是私聊
    is_group = chat_id.startswith('group_')

    if is_group:
        # 群聊：统计该群中 id > 已读位置 且 from_uid != 自己 且 非系统消息 的数量
        # FIX: 应用访问控制过滤，只计算用户可以访问的消息
        base_query = '''
            SELECT COUNT(*) as cnt FROM messages
            WHERE to_uid = ? AND id > ? AND from_uid != ? AND type != 'system'
        '''
        params = [chat_id, current_id, uid]
        
        # 应用注册时间过滤
        filtered_query, filtered_params = apply_registration_time_filter(uid, base_query, params)
        
        count_result = conn.execute(filtered_query, filtered_params).fetchone()
        unread_count = count_result['cnt'] if count_result else 0
    else:
        # 私聊：统计对方发给我的消息中 id > 已读位置 且 非系统消息 的数量
        # FIX: 应用访问控制过滤，只计算用户可以访问的消息
        base_query = '''
            SELECT COUNT(*) as cnt FROM messages
            WHERE from_uid = ? AND to_uid = ? AND id > ? AND type != 'system'
        '''
        params = [chat_id, uid, current_id]
        
        # 应用注册时间过滤
        filtered_query, filtered_params = apply_registration_time_filter(uid, base_query, params)
        
        count_result = conn.execute(filtered_query, filtered_params).fetchone()
        unread_count = count_result['cnt'] if count_result else 0

    return jsonify({
        'status': 'ok',
        'updated': updated,
        'unread_count': unread_count,
        'read_position': str(current_id)
    })


@app.route('/sync', methods=['GET'])
def sync():
    """
    同步接口 - 完整版本控制实现

    新增参数：
    - user_version: 客户端持有的用户版本号 JSON，格式 {uid: version, ...}
    - group_version: 客户端持有的群组版本号 JSON，格式 {gid: version, ...}

    返回新增字段：
    - changed_users: 版本变更的用户完整信息
    - changed_groups: 版本变更的群组完整信息
    - kicked_from_groups: 用户被踢出的群组ID列表
    - deleted_groups: 已解散的群组ID列表

    类型安全：
    - 所有 ID 返回时均转换为 String 类型，避免前端比较问题
    """
    uid = request.args.get('uid')
    try:
        last_msg_id = int(request.args.get('last_msg_id', 0))
    except:
        last_msg_id = 0

    # 解析客户端的版本信息
    try:
        client_user_versions = json.loads(
            request.args.get('user_version', '{}'))
    except:
        client_user_versions = {}
    try:
        client_group_versions = json.loads(
            request.args.get('group_version', '{}'))
    except:
        client_group_versions = {}
    # 客户端之前加入的群组列表（用于检测被踢）
    try:
        client_group_ids = json.loads(request.args.get('client_groups', '[]'))
    except:
        client_group_ids = []

    conn = get_db_connection()

    # **安全控制：检查用户账户状态**
    if uid:
        user = conn.execute(
            'SELECT * FROM users WHERE uid = ?', (uid,)).fetchone()
        if user:
            if user['deleted']:
                return jsonify({
                    'error': 'session_invalidated',
                    'message': '您的账户已被删除或合并，请重新登录'
                }), 403
            if user['session_invalidated']:
                return jsonify({
                    'error': 'session_invalidated',
                    'message': '您的会话已被终止，请重新登录'
                }), 403
            conn.execute(
                'UPDATE users SET last_active = ? WHERE uid = ?', (time.time(), uid))
            conn.commit()

    # 获取用户群组
    my_groups = get_user_groups(uid)

    # ============ 版本控制：检测被踢出的群组 ============
    kicked_from_groups = []
    for gid in client_group_ids:
        if gid not in my_groups and gid != 'group_global':
            # 客户端认为自己在这个群，但服务器说不在 -> 被踢了
            kicked_from_groups.append(str(gid))

    # ============ 版本控制：检测已解散的群组 ============
    deleted_groups = []
    for gid in client_group_ids:
        # 检查群组是否存在
        group_exists = conn.execute(
            'SELECT id FROM groups WHERE id = ?', (gid,)).fetchone()
        if not group_exists:
            deleted_groups.append(str(gid))

    # ============ 获取当前最大消息ID ============
    current_max_id_row = conn.execute(
        'SELECT MAX(id) as max_id FROM messages').fetchone()
    current_max_id = current_max_id_row['max_id'] if current_max_id_row['max_id'] else 0

    relevant_msgs = []
    recalled_ids = []
    last_synced_id = current_max_id  # 默认返回当前最大ID

    # ============ 条件性消息查询 ============
    if last_msg_id == 0:
        # 客户端初始化/刷新：不查询消息内容，只返回状态
        # 消息列表保持为空，通过 last_synced_id 告诉客户端从哪里开始监听
        pass
    else:
        # 正常同步：查询新消息
        messages = conn.execute(
            '''SELECT * FROM messages WHERE id > ? ORDER BY id LIMIT 500''',
            (last_msg_id,)
        ).fetchall()

        for m in messages:
            msg_dict = dict(m)
            # 类型安全：将消息 ID 转换为 String
            msg_dict['id'] = str(msg_dict['id'])

            # 解析quote_json
            if msg_dict['quote_json']:
                try:
                    msg_dict['quote'] = json.loads(msg_dict['quote_json'])
                    # 类型安全：引用消息的 ID 也转换为 String
                    if msg_dict['quote'] and 'id' in msg_dict['quote']:
                        msg_dict['quote']['id'] = str(msg_dict['quote']['id'])
                except:
                    msg_dict['quote'] = None
            else:
                msg_dict['quote'] = None
            del msg_dict['quote_json']

            if msg_dict['is_recalled']:
                # 类型安全：撤回 ID 也转换为 String
                recalled_ids.append(msg_dict['id'])

            # 检查权限
            has_perm = False
            to_id = msg_dict['to_uid']
            if to_id == uid or msg_dict['from_uid'] == uid:
                has_perm = True
            elif to_id == 'group_global':
                has_perm = True
            elif to_id in my_groups:
                has_perm = True

            if has_perm:
                # 引用消息访问控制：补充引用消息的完整内容（如果用户有权访问）
                enrich_quoted_message(uid, msg_dict)
                
                relevant_msgs.append(msg_dict)

        # 应用访问控制过滤到 relevant_msgs
        # 添加容差处理以处理时钟偏差（-60秒）
        if relevant_msgs:
            # 获取用户的注册时间和无限制访问状态
            user_info = conn.execute(
                'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
                (uid,)
            ).fetchone()
            
            if user_info:
                unrestricted_access = user_info['unrestricted_access'] or 0
                registered_at = user_info['registered_at']
                
                # 如果有访问限制（非无限制访问且有注册时间）
                if unrestricted_access != 1 and registered_at is not None:
                    # 添加60秒容差以处理时钟偏差
                    tolerance = 60
                    adjusted_registered_at = registered_at - tolerance
                    
                    # 过滤消息：保留时间戳 >= 调整后的注册时间 OR 用户自己发送的消息
                    filtered_msgs = []
                    for msg in relevant_msgs:
                        msg_timestamp = msg.get('timestamp', 0)
                        msg_from_uid = msg.get('from_uid', '')
                        
                        # 保留条件：时间戳 >= 调整后的注册时间 OR 是用户自己发送的
                        if msg_timestamp >= adjusted_registered_at or msg_from_uid == uid:
                            filtered_msgs.append(msg)
                    
                    relevant_msgs = filtered_msgs

        # 更新 last_synced_id 为这批消息的最大ID
        if relevant_msgs:
            # 类型安全：mid已转换为String，需转回int比较
            last_synced_id = max(int(m['id']) for m in relevant_msgs)

    # ============ 获取用户的已读标记（用于计算未读数量） ============
    user_read_markers = {}
    user_markers = conn.execute(
        'SELECT chat_id, msg_id FROM read_markers WHERE uid = ?', (uid,)
    ).fetchall()
    for marker in user_markers:
        user_read_markers[marker['chat_id']] = marker['msg_id']

    # ============ 获取当前用户的备注 ============
    my_remarks = {}
    remarks = conn.execute(
        'SELECT target_uid, remark FROM remarks WHERE uid = ?', (uid,)).fetchall()
    for r in remarks:
        my_remarks[r['target_uid']] = r['remark']

    # ============ 辅助函数：获取用户显示名称（优先显示备注） ============
    def get_display_name(user_id):
        """Get user display name with remark priority"""
        # 优先使用备注
        if user_id in my_remarks:
            return my_remarks[user_id]
        # 其次使用用户名
        user = conn.execute(
            'SELECT name FROM users WHERE uid = ?', (user_id,)).fetchone()
        return user['name'] if user else 'Unknown'

    # ============ 获取侧边栏预览数据（每个群组的最后消息） ============
    group_ids = list(my_groups.keys())
    if group_ids:
        # 为每个群组获取最后一条消息的预览
        placeholders = ','.join(['?' for _ in group_ids])
        sidebar_msgs = conn.execute(f'''
            SELECT m.* FROM messages m
            INNER JOIN (
                SELECT to_uid, MAX(id) as max_id
                FROM messages
                WHERE to_uid IN ({placeholders})
                GROUP BY to_uid
            ) latest ON m.id = latest.max_id
        ''', group_ids).fetchall()

        # 计算每个群组的未读消息数量
        group_unread_counts = {}
        for gid in group_ids:
            my_read = user_read_markers.get(gid, 0)
            # 统计未读消息：id > 已读位置 且 from_uid != 自己（自己发的不算未读）
            # FIX: 排除 type='system' 的消息（时间提示等系统消息不计入未读数）
            # FIX: 应用访问控制过滤，只计算用户可以访问的消息
            base_query = '''
                SELECT COUNT(*) as cnt FROM messages
                WHERE to_uid = ? AND id > ? AND from_uid != ? AND type != 'system'
            '''
            params = [gid, my_read, uid]
            
            # 应用注册时间过滤
            filtered_query, filtered_params = apply_registration_time_filter(uid, base_query, params)
            
            count_result = conn.execute(filtered_query, filtered_params).fetchone()
            group_unread_counts[gid] = count_result['cnt'] if count_result else 0

        for m in sidebar_msgs:
            gid = m['to_uid']
            if gid in my_groups:
                content = m['content'] or ''
                msg_type = m['type']
                from_uid = m['from_uid']

                # 格式化预览文本
                if msg_type == 'file':
                    preview = '[文件]'
                elif msg_type == 'sticker':
                    preview = '[表情]'
                elif msg_type == 'system':
                    preview = '[系统消息]'
                elif m['is_recalled']:
                    preview = '[已撤回]'
                elif content.startswith('{"type":"merge_fwd"'):
                    preview = '[聊天记录]'
                else:
                    preview = content[:50] if len(content) > 50 else content

                # 关键修复：群聊预览添加发送者名字前缀（支持备注）
                sender_name = get_display_name(from_uid)
                full_preview = sender_name + ': ' + preview

                my_groups[gid]['_sidebar'] = {
                    'lastMsgId': m['id'],
                    'lastMsgTime': m['timestamp'],
                    'lastMsgPreview': full_preview,  # 使用带发送者名字的完整预览
                    # FIX: 统一转换为 String 类型
                    'lastMsgFromUid': str(from_uid),
                    'unreadCount': group_unread_counts.get(gid, 0)  # 新增：未读消息数量
                }

    # ============ 获取私聊的侧边栏预览数据 ============
    # 查询与当前用户相关的私聊最后消息
    private_msgs = conn.execute('''
        SELECT m.* FROM messages m
        INNER JOIN (
            SELECT 
                CASE WHEN from_uid = ? THEN to_uid ELSE from_uid END as chat_partner,
                MAX(id) as max_id
            FROM messages
            WHERE (from_uid = ? OR to_uid = ?)
              AND to_uid NOT LIKE 'group_%'
              AND from_uid != to_uid
            GROUP BY chat_partner
        ) latest ON m.id = latest.max_id
    ''', (uid, uid, uid)).fetchall()

    # 获取用户列表
    now = time.time()
    online_users = {}
    users = conn.execute(
        'SELECT uid, name, avatar_bg, last_active FROM users WHERE deleted = 0').fetchall()
    for u in users:
        status = 'online' if (
            now - (u['last_active'] or 0) < 30) else 'offline'
        online_users[u['uid']] = {
            'name': u['name'],
            'avatar_bg': u['avatar_bg'] or '#555',
            'status': status
        }

    # 为私聊用户添加侧边栏预览
    for m in private_msgs:
        # 确定聊天对象
        partner_uid = m['to_uid'] if m['from_uid'] == uid else m['from_uid']
        if partner_uid in online_users:
            content = m['content'] or ''
            msg_type = m['type']
            # 格式化预览文本
            if msg_type == 'file':
                preview = '[文件]'
            elif msg_type == 'sticker':
                preview = '[表情]'
            elif msg_type == 'system':
                preview = '[系统消息]'
            elif m['is_recalled']:
                preview = '[已撤回]'
            elif content.startswith('{"type":"merge_fwd"'):
                preview = '[聊天记录]'
            else:
                preview = content[:50] if len(content) > 50 else content

            # 计算私聊的未读消息数量：对方发给我的消息，id > 已读位置
            # FIX: 排除 type='system' 的消息（系统消息不计入未读数）
            # FIX: 应用访问控制过滤，只计算用户可以访问的消息
            my_read = user_read_markers.get(partner_uid, 0)
            base_query = '''
                SELECT COUNT(*) as cnt FROM messages
                WHERE from_uid = ? AND to_uid = ? AND id > ? AND type != 'system'
            '''
            params = [partner_uid, uid, my_read]
            
            # 应用注册时间过滤
            filtered_query, filtered_params = apply_registration_time_filter(uid, base_query, params)
            
            private_unread = conn.execute(filtered_query, filtered_params).fetchone()
            unread_count = private_unread['cnt'] if private_unread else 0

            online_users[partner_uid]['_sidebar'] = {
                'lastMsgId': m['id'],
                'lastMsgTime': m['timestamp'],
                'lastMsgPreview': preview,
                'lastMsgFromUid': str(m['from_uid']),  # FIX: 统一转换为 String 类型
                'unreadCount': unread_count  # 新增：未读消息数量
            }

    # 获取已读标记
    read_markers_snapshot = {}
    markers = conn.execute('SELECT * FROM read_markers').fetchall()
    for marker in markers:
        if marker['uid'] not in read_markers_snapshot:
            read_markers_snapshot[marker['uid']] = {}
        # FIX BUG: 强制转换已读标记 ID 为字符串
        # 原代码: read_markers_snapshot[marker['uid']][marker['chat_id']] = marker['msg_id']
        # 问题: msg_id 是巨大的 Snowflake 整数，JavaScript Number 类型会丢失末位精度
        # 例如: 1733...（18位整数）-> JavaScript 变成末位为0的数字，导致与 String 类型比较失效
        # 修复: 显式转换为字符串，确保前端接收到准确的 ID 值
        read_markers_snapshot[marker['uid']
                              ][marker['chat_id']] = str(marker['msg_id'])

    # ============ 修复：独立查询最近被撤回的消息 ID ============
    if last_msg_id > 0:
        # 查询最近50条最近被撤回的消息（性能优化：限制数量避免全表扫描）
        recently_recalled = conn.execute(
            '''SELECT id, from_uid, to_uid FROM messages 
               WHERE is_recalled = 1 
               ORDER BY id DESC LIMIT 50'''
        ).fetchall()

        # 过滤出用户有权限查看的撤回消息，并去重合并
        existing_recalled_set = set(recalled_ids)
        for rm in recently_recalled:
            # 类型安全：转换为 String
            msg_id_str = str(rm['id'])
            # 检查权限
            to_id = rm['to_uid']
            has_perm = False
            if to_id == uid or rm['from_uid'] == uid:
                has_perm = True
            elif to_id == 'group_global':
                has_perm = True
            elif to_id in my_groups:
                has_perm = True

            # 有权限且未在列表中，则添加
            if has_perm and msg_id_str not in existing_recalled_set:
                recalled_ids.append(msg_id_str)
                existing_recalled_set.add(msg_id_str)

    # ============ 版本控制：检测用户信息变更 ============
    # 修复"幽灵用户"漏洞：移除 WHERE deleted = 0，确保被删除用户也能同步
    changed_users = {}
    all_users_with_version = conn.execute(
        'SELECT uid, name, avatar_bg, last_active, version, deleted FROM users'
    ).fetchall()
    for u in all_users_with_version:
        u_uid = u['uid']
        server_version = u['version'] or 0
        client_version = client_user_versions.get(u_uid, -1)  # 默认-1表示未知

        # 如果服务器版本高于客户端，返回完整信息（包括 deleted 状态）
        if server_version > client_version:
            changed_users[u_uid] = {
                'name': u['name'],
                'avatar_bg': u['avatar_bg'] or '#555',
                'version': server_version,
                'deleted': bool(u['deleted'])  # 前端需要此字段判断用户是否被注销
            }

    # ============ 版本控制：检测群组信息变更 ============
    changed_groups = {}
    for gid, group_data in my_groups.items():
        # 获取群组版本号
        group_row = conn.execute(
            'SELECT version FROM groups WHERE id = ?', (gid,)
        ).fetchone()
        server_version = (group_row['version'] if group_row else 0) or 0
        client_version = client_group_versions.get(gid, -1)

        if server_version > client_version:
            # 返回完整的群组信息
            changed_groups[gid] = {
                'id': gid,
                'name': group_data.get('name', ''),
                'members': group_data.get('members', []),
                'is_group': True,
                'owner': group_data.get('owner', ''),
                'system': group_data.get('system', False),
                'version': server_version
            }

    # ============ 类型安全：对侧边栏预览的 ID 进行转换 ============
    for gid in my_groups:
        if '_sidebar' in my_groups[gid] and my_groups[gid]['_sidebar']:
            my_groups[gid]['_sidebar']['lastMsgId'] = str(
                my_groups[gid]['_sidebar'].get('lastMsgId', 0))

    for u_uid in online_users:
        if '_sidebar' in online_users[u_uid] and online_users[u_uid]['_sidebar']:
            online_users[u_uid]['_sidebar']['lastMsgId'] = str(
                online_users[u_uid]['_sidebar'].get('lastMsgId', 0))

    # ============ P2P会话查询============
    p2p_sessions = []
    if uid:
        # 只查询最近1小时内创建的活跃会话（避免返回过期的旧会话）
        one_hour_ago = time.time() - 3600
        
        # 查询用户作为发送方的活跃会话
        sender_sessions = conn.execute('''
            SELECT s.session_id, s.receiver_uid, s.group_id, s.chat_type, s.total_size, 
                   s.file_count, s.status, s.created_at, s.expires_at
            FROM p2p_sessions s
            WHERE s.sender_uid = ? 
            AND s.status IN ('pending', 'active', 'connecting')
            AND s.created_at > ?
            ORDER BY s.created_at DESC
        ''', (uid, one_hour_ago)).fetchall()
        
        for session in sender_sessions:
            # 获取文件列表
            files = conn.execute('''
                SELECT filename, size, file_hash, mime_type, status
                FROM p2p_session_files
                WHERE session_id = ?
                ORDER BY file_index
            ''', (session['session_id'],)).fetchall()
            
            session_data = {
                'session_id': session['session_id'],
                'role': 'sender',
                'peer_uid': session['receiver_uid'] or session['group_id'],
                'chat_type': session['chat_type'],
                'files': [dict(f) for f in files],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            }
            
            # 如果是群聊，获取参与者状态
            if session['chat_type'] == 'group':
                participants = conn.execute('''
                    SELECT uid, status, responded_at, completed_at
                    FROM p2p_session_participants
                    WHERE session_id = ?
                ''', (session['session_id'],)).fetchall()
                session_data['participants'] = [dict(p) for p in participants]
            
            p2p_sessions.append(session_data)
        
        # 查询用户作为接收方的待处理会话（私聊）
        receiver_sessions = conn.execute('''
            SELECT s.session_id, s.sender_uid, s.chat_type, s.total_size, 
                   s.file_count, s.status, s.created_at, s.expires_at
            FROM p2p_sessions s
            WHERE s.receiver_uid = ? 
            AND s.status IN ('pending', 'active', 'connecting')
            AND s.created_at > ?
            ORDER BY s.created_at DESC
        ''', (uid, one_hour_ago)).fetchall()
        
        for session in receiver_sessions:
            # 获取文件列表
            files = conn.execute('''
                SELECT filename, size, file_hash, mime_type, status
                FROM p2p_session_files
                WHERE session_id = ?
                ORDER BY file_index
            ''', (session['session_id'],)).fetchall()
            
            p2p_sessions.append({
                'session_id': session['session_id'],
                'role': 'receiver',
                'peer_uid': session['sender_uid'],
                'chat_type': session['chat_type'],
                'files': [dict(f) for f in files],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            })
        
        # 查询用户作为群聊参与者的待处理会话
        group_participant_sessions = conn.execute('''
            SELECT s.session_id, s.sender_uid, s.group_id, s.chat_type, s.total_size,
                   s.file_count, s.status, s.created_at, s.expires_at,
                   p.status as participant_status
            FROM p2p_sessions s
            JOIN p2p_session_participants p ON s.session_id = p.session_id
            WHERE p.uid = ? 
            AND p.status IN ('pending', 'accepted') 
            AND s.status IN ('pending', 'active', 'connecting')
            AND s.created_at > ?
            ORDER BY s.created_at DESC
        ''', (uid, one_hour_ago)).fetchall()
        
        for session in group_participant_sessions:
            # 获取文件列表
            files = conn.execute('''
                SELECT filename, size, file_hash, mime_type, status
                FROM p2p_session_files
                WHERE session_id = ?
                ORDER BY file_index
            ''', (session['session_id'],)).fetchall()
            
            p2p_sessions.append({
                'session_id': session['session_id'],
                'role': 'receiver',
                'peer_uid': session['sender_uid'],
                'group_id': session['group_id'],
                'chat_type': session['chat_type'],
                'files': [dict(f) for f in files],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'participant_status': session['participant_status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            })
    
    # ============ P2P信令查询============
    p2p_signals = []
    if uid:
        # 查询待处理的信令数据
        pending_signals = conn.execute(
            '''SELECT * FROM p2p_signals 
               WHERE to_uid = ? AND consumed = 0
               ORDER BY created_at ASC''',
            (uid,)
        ).fetchall()
        
        for signal in pending_signals:
            p2p_signals.append({
                'id': signal['id'],
                'session_id': signal['session_id'],
                'from_uid': signal['from_uid'],
                'signal_type': signal['signal_type'],
                'signal_data': json.loads(signal['signal_data']),
                'created_at': signal['created_at']
            })
            
            # 标记信令为已消费
            conn.execute(
                'UPDATE p2p_signals SET consumed = 1 WHERE id = ?',
                (signal['id'],)
            )
        
        if p2p_signals:
            conn.commit()

    return jsonify({
        'messages': relevant_msgs,
        'recalled_ids': recalled_ids,
        'users': online_users,
        'groups': my_groups,
        'read_markers': read_markers_snapshot,
        'remarks': my_remarks,
        'last_synced_id': str(last_synced_id),  # 类型安全：转换为 String
        # 版本控制新增字段
        'changed_users': changed_users,
        'changed_groups': changed_groups,
        'kicked_from_groups': kicked_from_groups,
        'deleted_groups': deleted_groups,
        # P2P会话信息
        'p2p_sessions': p2p_sessions,
        'p2p_signals': p2p_signals
    })


@app.route('/send', methods=['POST'])
def send_msg():
    req = request.json
    uid = req.get('uid')
    to_uid = req.get('to_uid')
    content = req.get('content')
    quote = req.get('quote')
    msg_type = req.get('type', 'text')

    conn = get_db_connection()

    # **安全控制：检查发送者账户状态**
    if uid:
        user = conn.execute(
            'SELECT deleted, session_invalidated FROM users WHERE uid = ?', (uid,)).fetchone()
        if user and (user['deleted'] or user['session_invalidated']):
            return jsonify({
                'error': 'session_invalidated',
                'message': '您的账户已被禁用'
            }), 403

    # 检查是否在群组中
    group = conn.execute(
        'SELECT id FROM groups WHERE id = ?', (to_uid,)).fetchone()
    if group and to_uid != 'group_global':
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            (to_uid, uid)
        ).fetchone()
        if not member:
            return jsonify({'error': '不在群组中'}), 403

    msg_id = get_unique_msg_id()
    quote_json = json.dumps(quote) if quote else None

    conn.execute(
        '''INSERT INTO messages (id, from_uid, to_uid, type, content, timestamp, quote_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (msg_id, uid, to_uid, msg_type, content, time.time(), quote_json)
    )
    conn.commit()

    # 类型安全：返回 String 类型的 msg_id
    return jsonify({'status': 'ok', 'msg_id': str(msg_id)})


@app.route('/recall', methods=['POST'])
def recall_msg():
    req = request.json
    uid = req.get('uid')
    msg_id = req.get('msg_id')

    conn = get_db_connection()
    target_msg = conn.execute(
        'SELECT * FROM messages WHERE id = ?', (msg_id,)).fetchone()

    if not target_msg:
        return jsonify({'error': '消息不存在'}), 404

    is_self = (target_msg['from_uid'] == uid)
    is_owner = False

    # 检查是否是群主
    group = conn.execute(
        'SELECT owner FROM groups WHERE id = ?',
        (target_msg['to_uid'],)
    ).fetchone()
    if group and group['owner'] == uid:
        is_owner = True

    if not (is_self or is_owner):
        return jsonify({'error': '无权撤回'}), 403

    if time.time() - target_msg['timestamp'] > 120:
        return jsonify({'error': '发送超过2分钟，无法撤回'}), 403

    conn.execute('UPDATE messages SET is_recalled = 1 WHERE id = ?', (msg_id,))
    conn.commit()

    return jsonify({'status': 'ok'})


@app.route('/upload', methods=['POST'])
def upload_file():
    files = request.files.getlist('file')
    uid = request.form.get('uid')
    to_uid = request.form.get('to_uid')
    if not files:
        return jsonify({'error': 'No file'}), 400

    if not os.path.exists(UPLOAD_FOLDER):
        try:
            os.makedirs(UPLOAD_FOLDER)
        except:
            return jsonify({'error': 'Storage not available'}), 503

    conn = get_db_connection()

    # 检查是否在群组中
    group = conn.execute(
        'SELECT id FROM groups WHERE id = ?', (to_uid,)).fetchone()
    if group and to_uid != 'group_global':
        member = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            (to_uid, uid)
        ).fetchone()
        if not member:
            return jsonify({'error': '无权发送'}), 403

    saved_msgs = []
    for file in files:
        if file and file.filename:
            try:
                safe_name = werkzeug.utils.secure_filename(
                    file.filename) or "unknown_file"
                
                # 先保存到临时位置以计算哈希
                temp_filename = f"temp_{uuid.uuid4().hex}"
                temp_filepath = os.path.join(UPLOAD_FOLDER, temp_filename)
                file.save(temp_filepath)
                
                # 计算文件哈希
                file_hash = calculate_file_hash(temp_filepath)
                file_size = os.path.getsize(temp_filepath)
                # 判断是否是图片（使用新的判断函数，支持webp）
                is_img = 1 if is_image_file(file.filename) else 0
                
                # 检查是否已存在相同哈希的文件
                existing_file = find_existing_file_by_hash(file_hash)
                
                if existing_file:
                    # 文件已存在，删除临时文件，复用已有文件
                    try:
                        os.remove(temp_filepath)
                    except:
                        pass
                    
                    server_filename = existing_file['server_filename']
                    file_size = existing_file['size']
                    is_img = existing_file['is_img']
                else:
                    # 文件不存在，重命名临时文件为正式文件名
                    server_filename = f"{int(time.time())}_{uuid.uuid4().hex[:6]}_{safe_name}"
                    final_filepath = os.path.join(UPLOAD_FOLDER, server_filename)
                    os.rename(temp_filepath, final_filepath)
                
                # 创建消息记录（使用用户上传的原始文件名）
                msg_id = get_unique_msg_id()
                conn.execute(
                    '''INSERT INTO messages (id, from_uid, to_uid, type, content, filename, server_filename, size, timestamp, is_img, file_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (msg_id, uid, to_uid, 'file',
                     f"文件: {file.filename}", file.filename, server_filename, file_size, time.time(), is_img, file_hash)
                )
                # 立即提交每个文件的消息，确保前端能快速同步
                conn.commit()
                saved_msgs.append(msg_id)
            except Exception as e:
                logger.error(f"Error uploading file {file.filename}: {e}")
                # 清理可能的临时文件
                try:
                    if 'temp_filepath' in locals() and os.path.exists(temp_filepath):
                        os.remove(temp_filepath)
                except:
                    pass

    return jsonify({'status': 'ok', 'count': len(saved_msgs)})


# ================= 文件存在性检查函数 =================

def check_file_exists(server_filename):
    """
    检查文件是否存在于uploads目录
    
    实现路径遍历防护和异常处理，确保安全性
    
    Args:
        server_filename: 服务器文件名
        
    Returns:
        bool: True表示文件存在，False表示不存在
        
    异常处理:
        - 捕获所有文件系统异常，返回False
        - 处理None或空字符串输入
        - 处理路径遍历攻击尝试
    
    """
    # 处理NULL和空字符串输入（包括仅包含空白字符的字符串）
    if not server_filename or server_filename is None or not server_filename.strip():
        return False
    
    # 路径遍历防护 - 检测危险模式
    # 只拒绝真正的路径遍历模式，允许文件名中包含 .. （如 file..zip）
    # 检测路径分隔符
    if '/' in server_filename or '\\' in server_filename:
        logger.warning(f"Path traversal attempt detected - filename contains path separator: {server_filename}")
        return False
    
    # 检测父目录引用模式（../ 或 ..\）
    # 使用规范化路径来检测是否试图访问父目录
    try:
        normalized_path = os.path.normpath(os.path.join(UPLOAD_FOLDER, server_filename))
        expected_prefix = os.path.normpath(UPLOAD_FOLDER)
        if not normalized_path.startswith(expected_prefix):
            logger.warning(f"Path traversal attempt detected - normalized path escapes upload folder: {server_filename}")
            return False
    except Exception as e:
        logger.warning(f"Path normalization error for filename={server_filename}: {e}")
        return False
    
    # 文件存在性检查，捕获所有异常
    try:
        file_path = os.path.join(UPLOAD_FOLDER, server_filename)
        exists = os.path.exists(file_path)
        return exists
    except (OSError, IOError) as e:
        # 文件系统错误（权限、磁盘故障等）
        logger.error(f"File system error checking {server_filename}: {e}")
        return False
    except Exception as e:
        # 捕获意外错误
        logger.error(f"Unexpected error checking {server_filename}: {e}")
        return False


def log_missing_file(uid, msg_id, filename, server_filename):
    """
    记录缺失文件的审计日志
    
    实现静默失败机制，确保日志错误不影响业务逻辑
    
    Args:
        uid: 用户ID
        msg_id: 消息ID
        filename: 显示文件名（原始文件名）
        server_filename: 服务器文件名
    
    日志格式:
        包含时间戳、用户ID、消息ID、文件名、服务器文件名
    
    异常处理:
        - 捕获所有日志写入异常，静默失败
        - 日志失败不影响业务逻辑
    
    """
    # 实现静默失败机制
    try:
        # 创建专门的云文件日志记录器（如果还没有）
        cloud_file_logger = logging.getLogger('cloud_file')
        
        # 记录缺失文件信息，包含所有必需字段
        cloud_file_logger.warning(
            f"Missing file detected - "
            f"uid={uid}, "
            f"msg_id={msg_id}, "
            f"filename={filename}, "
            f"server_filename={server_filename}"
        )
    except Exception as e:
        # 静默失败 - 日志错误不影响业务逻辑
        # 不抛出异常，不影响调用方
        pass


def escape_like_pattern(keyword):
    """
    转义LIKE查询中的特殊字符
    
    实现SQL LIKE查询的安全转义，防止SQL注入和意外的通配符匹配
    
    Args:
        keyword: 用户输入的搜索关键词
        
    Returns:
        str: 转义后的关键词，可安全用于LIKE查询
        
    异常处理:
        - 处理None输入，返回空字符串
        - 处理空字符串输入，返回空字符串
        - 捕获所有异常，返回空字符串作为安全默认
    
    转义规则:
        - 反斜杠 (\\) -> \\\\\\\\
        - 百分号 (%) -> \\\\%
        - 下划线 (_) -> \\\\_
    
    """
    # 处理NULL和空字符串输入
    if keyword is None or keyword == '':
        return ''
    
    # 转义LIKE特殊字符
    try:
        # 先转义反斜杠（必须先转义，否则会影响后续转义）
        keyword = keyword.replace('\\', '\\\\')
        # 转义百分号（LIKE通配符，匹配任意字符）
        keyword = keyword.replace('%', '\\%')
        # 转义下划线（LIKE通配符，匹配单个字符）
        keyword = keyword.replace('_', '\\_')
        return keyword
    except Exception as e:
        # 捕获意外错误，返回空字符串作为安全默认
        logger.error(f"Error escaping LIKE pattern '{keyword}': {e}")
        return ''


@app.route('/uploads/<path:filename>')
def download_file(filename):
    """
    下载文件接口（增强版 + 性能优化）
    
    实现功能：
    - 文件名安全性验证（路径遍历检查）
    - 文件不存在时返回JSON格式的404错误
    - 非法路径返回JSON格式的400错误
    - 使用原始文件名进行下载（而不是服务器文件名）
    - 提供清晰的中文错误消息
    
    性能优化：
    - 提前验证文件存在性，避免不必要的数据库查询
    - 优化数据库查询，使用索引
    - 启用条件请求支持（ETag, Last-Modified）
    - 设置合适的缓存策略
    
    """
    # 检查uploads目录是否存在
    if not os.path.exists(UPLOAD_FOLDER):
        return jsonify({
            'error': 'Storage not available',
            'message': '文件存储服务暂时不可用'
        }), 404
    
    # 文件名安全性验证（路径遍历检查）
    # 检查路径遍历模式（../ 或 ..\），但允许文件名中包含 ..
    dangerous_patterns = ['../', '..\\']
    for pattern in dangerous_patterns:
        if pattern in filename:
            logger.warning(f"Path traversal attempt in download - filename={filename}")
            return jsonify({
                'error': 'Invalid path',
                'message': '文件路径包含非法字符'
            }), 400
    
    # 额外检查：确保规范化后的路径仍在 uploads 目录内
    try:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file_path_abs = os.path.abspath(file_path)
        upload_folder_abs = os.path.abspath(UPLOAD_FOLDER)
        
        if not file_path_abs.startswith(upload_folder_abs):
            logger.warning(f"Path traversal detected - filename={filename}, resolved_path={file_path_abs}")
            return jsonify({
                'error': 'Invalid path',
                'message': '文件路径包含非法字符'
            }), 400
    except Exception as e:
        logger.error(f"Error validating path for {filename}: {e}")
        return jsonify({
            'error': 'Invalid path',
            'message': '文件路径验证失败'
        }), 400
    
    # 检查文件是否存在（file_path 已在上面构建）
    if not os.path.exists(file_path):
        return jsonify({
            'error': 'File not found',
            'message': '请求的文件在服务器上不存在'
        }), 404
    
    # 性能优化：提前查询原始文件名，避免在send_from_directory之后再查询
    download_name = filename  # 默认使用服务器文件名
    try:
        conn = get_db_connection()
        message = conn.execute(
            'SELECT filename FROM messages WHERE server_filename = ? AND type = "file" LIMIT 1',
            (filename,)
        ).fetchone()
        
        if message:
            download_name = message['filename']
    except Exception as e:
        logger.error(f"Error querying original filename for {filename}: {e}")
    
    # 文件存在，正常返回
    # 使用 download_name 参数指定下载时的文件名
    # as_attachment=True 强制下载，而不是浏览器预览
    # conditional=True 启用条件请求支持（ETag, Last-Modified）
    response = send_from_directory(
        UPLOAD_FOLDER, 
        filename, 
        as_attachment=True,
        download_name=download_name,
        conditional=True,  # 启用条件请求，支持断点续传
        max_age=0  # 不缓存，确保获取最新文件
    )
    
    # 添加安全相关的HTTP头
    # X-Content-Type-Options: nosniff 防止浏览器进行MIME类型嗅探
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # 性能优化：添加 Accept-Ranges 头，支持分块下载
    response.headers['Accept-Ranges'] = 'bytes'
    
    return response


# 注释掉自定义静态资源路由，使用Flask默认的静态文件服务
# @app.route('/static/<path:filename>')
# def serve_static(filename):
#     """提供静态资源服务，包括emoji图片"""
#     if not os.path.exists(STATIC_FOLDER):
#         return "Static files not available", 404
#     return send_from_directory(STATIC_FOLDER, filename)


@app.route('/static/<path:filename>')
def serve_static(filename):
    """提供静态资源服务，包括emoji图片"""
    # 重新获取静态资源路径，确保在每次请求时都能正确处理
    static_folder = get_static_folder()
    if not os.path.exists(static_folder):
        return "Static files not available", 404
    return send_from_directory(static_folder, filename)


@app.route('/static/telegram_stickers/<path:filename>')
def serve_telegram_sticker(filename):
    """Telegram GIF表情专用路由，强缓存优化性能"""
    # 重新获取静态资源路径，确保在每次请求时都能正确处理
    static_folder = get_static_folder()
    sticker_folder = os.path.join(static_folder, 'telegram_stickers')

    if not os.path.exists(sticker_folder):
        return "Telegram stickers not available", 404

    response = send_from_directory(sticker_folder, filename)

    # 强缓存配置（1年）
    response.cache_control.max_age = 31536000  # 1年 = 365天 × 24小时 × 3600秒
    response.cache_control.public = True
    response.cache_control.immutable = True

    return response

@app.route('/api/files', methods=['GET'])
def list_files():
    """
    获取文件列表 - 支持懒加载和搜索
    
    参数:
        uid: 用户ID（必需）
        before_id: 获取此消息ID之前的文件（可选，用于懒加载）
        limit: 返回数量（可选，默认50，最大100）
        search: 搜索关键词（可选，用于文件名搜索）
    
    返回:
        {
            "files": [...],
            "has_more": bool
        }
    
    边缘情况处理:
        - uploads目录不存在时返回空列表
        - server_filename为NULL时跳过记录
        - 使用Flask线程本地存储确保并发安全
    
    """
    uid = request.args.get('uid')
    
    # 边缘情况处理 - uploads目录不存在时返回空列表
    if not os.path.exists(UPLOAD_FOLDER):
        logger.warning(f"Uploads folder does not exist - returning empty file list")
        return jsonify({
            'files': [],
            'has_more': False
        })
    
    # 解析参数
    try:
        before_id = int(request.args.get('before_id', 0))
    except (ValueError, TypeError):
        before_id = 0
    
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
    except (ValueError, TypeError):
        limit = 50
    
    search = request.args.get('search', '').strip()
    
    files = []
    # 并发请求的线程安全 - 使用Flask的get_db_connection()
    # Flask的g对象是线程本地存储，每个请求都有独立的数据库连接
    conn = get_db_connection()
    
    # 构建动态SQL查询
    # 基础查询
    base_query = "SELECT * FROM messages WHERE type = 'file' AND is_recalled = 0"
    params = []
    
    # 添加搜索条件（如果提供）
    if search:
        # 使用escape_like_pattern转义搜索关键词
        escaped_search = escape_like_pattern(search)
        base_query += " AND filename LIKE ? ESCAPE '\\'"
        params.append(f'%{escaped_search}%')
    
    # 添加分页条件（如果提供before_id）
    if before_id > 0:
        base_query += " AND id < ?"
        params.append(before_id)
    
    # 添加排序和限制
    # 查询limit+1条记录以判断has_more
    base_query += " ORDER BY id DESC LIMIT ?"
    params.append(limit + 1)
    
    # 执行查询
    messages = conn.execute(base_query, params).fetchall()
    
    # 判断has_more
    has_more = len(messages) > limit
    
    # 如果查询到limit+1条，只取前limit条
    if has_more:
        messages = messages[:limit]
    
    # 文件去重：使用字典来跟踪已添加的文件（基于 file_hash 和 filename）
    seen_files = {}  # key: (file_hash, filename), value: True
    
    # 处理每条消息，进行权限检查和文件存在性验证
    for m in messages:
        msg_dict = dict(m)
        
        # 权限检查
        if not check_permission(uid, msg_dict):
            continue
        
        # 文件存在性检查
        server_filename = m['server_filename']
        
        # 边缘情况处理 - 跳过NULL或空的server_filename
        if not server_filename:
            continue
        
        # 文件去重：检查是否已添加相同哈希值和文件名的文件
        file_hash = m['file_hash']
        filename = m['filename']
        dedup_key = (file_hash, filename)
        
        if dedup_key in seen_files:
            # 已经添加过相同哈希和文件名的文件，跳过
            continue
        
        # 检查文件是否存在
        try:
            if not check_file_exists(server_filename):
                # 记录缺失文件的审计日志
                log_missing_file(
                    uid=uid,
                    msg_id=m['id'],
                    filename=m['filename'],
                    server_filename=server_filename
                )
                continue
        except Exception as e:
            # 错误恢复 - 单个文件检查失败不影响其他文件
            logger.error(f"Error checking file existence for {server_filename}: {e}")
            continue
        
        # 标记为已添加
        seen_files[dedup_key] = True
        
        # 添加文件到结果列表（包含id字段）
        files.append({
            'id': str(m['id']),
            'name': m['server_filename'],
            'display_name': m['filename'],
            'size': m['size'] or 0,
            'time': m['timestamp'],
            'from_uid': m['from_uid']
        })
    
    # 返回新的响应格式
    return jsonify({
        'files': files,
        'has_more': has_more
    })


@app.route('/api/pinned_files/check', methods=['GET'])
def check_pinned_folder():
    """
    检查置顶文件夹是否有内容
    
    返回:
        {
            "has_content": bool  # 是否有内容
        }
    """
    pinned_root = os.path.join(UPLOAD_FOLDER, '置顶')
    
    # 如果文件夹不存在，返回无内容
    if not os.path.exists(pinned_root):
        return jsonify({'has_content': False})
    
    try:
        # 递归检查是否有任何文件
        for root, dirs, files in os.walk(pinned_root):
            # 过滤隐藏文件
            files = [f for f in files if not f.startswith('.')]
            if files:
                return jsonify({'has_content': True})
        
        # 没有找到任何文件
        return jsonify({'has_content': False})
        
    except Exception as e:
        logger.error(f"Error checking pinned folder: {e}")
        return jsonify({'has_content': False})


@app.route('/api/pinned_files', methods=['GET'])
def list_pinned_files():
    """
    获取置顶文件夹内容
    
    参数:
        path: 子路径（可选，默认为根目录）
    
    返回:
        {
            "folders": [...],  # 文件夹列表
            "files": [...],    # 文件列表
            "current_path": str  # 当前路径
        }
    
    安全性：
        - 防止路径遍历攻击
        - 只允许访问置顶文件夹内的内容
    """
    # 获取子路径参数
    sub_path = request.args.get('path', '').strip()
    
    # 置顶文件夹的根目录
    pinned_root = os.path.join(UPLOAD_FOLDER, '置顶')
    
    # 确保置顶文件夹存在
    if not os.path.exists(pinned_root):
        try:
            os.makedirs(pinned_root)
        except:
            pass
    
    # 安全性检查：防止路径遍历攻击
    if sub_path:
        # 移除开头的斜杠
        sub_path = sub_path.lstrip('/\\')
        
        # 检查是否包含危险的路径遍历模式
        dangerous_patterns = ['../', '..\\', '\\\\', '//']
        for pattern in dangerous_patterns:
            if pattern in sub_path:
                logger.warning(f"Path traversal attempt in pinned files - path={sub_path}")
                return jsonify({'error': 'Invalid path'}), 400
        
        # 构建完整路径
        target_path = os.path.join(pinned_root, sub_path)
        
        # 验证路径是否在置顶文件夹内
        try:
            target_path = os.path.abspath(target_path)
            pinned_root_abs = os.path.abspath(pinned_root)
            
            if not target_path.startswith(pinned_root_abs):
                logger.warning(f"Path traversal attempt detected - target={target_path}, root={pinned_root_abs}")
                return jsonify({'error': 'Invalid path'}), 400
        except Exception as e:
            logger.error(f"Error validating path: {e}")
            return jsonify({'error': 'Invalid path'}), 400
    else:
        target_path = pinned_root
    
    # 检查目标路径是否存在
    if not os.path.exists(target_path):
        return jsonify({'error': 'Path not found'}), 404
    
    # 检查是否是目录
    if not os.path.isdir(target_path):
        return jsonify({'error': 'Not a directory'}), 400
    
    folders = []
    files = []
    
    try:
        # 列出目录内容
        for item in os.listdir(target_path):
            item_path = os.path.join(target_path, item)
            
            # 跳过隐藏文件
            if item.startswith('.'):
                continue
            
            try:
                if os.path.isdir(item_path):
                    # 文件夹
                    folders.append({
                        'name': item,
                        'path': os.path.join(sub_path, item).replace('\\', '/') if sub_path else item
                    })
                elif os.path.isfile(item_path):
                    # 文件
                    file_size = os.path.getsize(item_path)
                    file_time = os.path.getmtime(item_path)
                    
                    files.append({
                        'name': item,
                        'size': file_size,
                        'time': file_time,
                        'path': os.path.join(sub_path, item).replace('\\', '/') if sub_path else item
                    })
            except Exception as e:
                logger.error(f"Error processing item {item}: {e}")
                continue
        
        # 排序：文件夹在前，按名称排序
        folders.sort(key=lambda x: x['name'])
        files.sort(key=lambda x: x['name'])
        
        return jsonify({
            'folders': folders,
            'files': files,
            'current_path': sub_path
        })
        
    except Exception as e:
        logger.error(f"Error listing pinned files: {e}")
        return jsonify({'error': 'Failed to list files'}), 500


@app.route('/pinned/<path:filename>')
def download_pinned_file(filename):
    """
    下载置顶文件夹中的文件（性能优化版）
    
    参数:
        filename: 文件路径（相对于置顶文件夹）
    
    安全性：
        - 防止路径遍历攻击
        - 只允许下载置顶文件夹内的文件
    
    性能优化：
        - 启用条件请求支持（ETag, Last-Modified）
        - 支持分块下载和断点续传
    """
    # 置顶文件夹的根目录
    pinned_root = os.path.join(UPLOAD_FOLDER, '置顶')
    
    # 安全性检查：防止路径遍历攻击
    dangerous_patterns = ['../', '..\\', '\\\\']
    for pattern in dangerous_patterns:
        if pattern in filename:
            logger.warning(f"Path traversal attempt in pinned file download - filename={filename}")
            return jsonify({'error': 'Invalid path'}), 400
    
    # 构建完整路径
    file_path = os.path.join(pinned_root, filename)
    
    # 验证路径是否在置顶文件夹内
    try:
        file_path_abs = os.path.abspath(file_path)
        pinned_root_abs = os.path.abspath(pinned_root)
        
        if not file_path_abs.startswith(pinned_root_abs):
            logger.warning(f"Path traversal attempt detected - file={file_path_abs}, root={pinned_root_abs}")
            return jsonify({'error': 'Invalid path'}), 400
    except Exception as e:
        logger.error(f"Error validating path: {e}")
        return jsonify({'error': 'Invalid path'}), 400
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # 检查是否是文件
    if not os.path.isfile(file_path):
        return jsonify({'error': 'Not a file'}), 400
    
    # 获取文件名（用于下载）
    download_name = os.path.basename(filename)
    
    # 返回文件
    try:
        # 获取文件所在的目录和文件名
        file_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        
        response = send_from_directory(
            file_dir,
            file_name,
            as_attachment=True,
            download_name=download_name,
            conditional=True,  # 启用条件请求，支持断点续传
            max_age=0  # 不缓存，确保获取最新文件
        )
        
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # 性能优化：添加 Accept-Ranges 头，支持分块下载
        response.headers['Accept-Ranges'] = 'bytes'
        
        return response
        
    except Exception as e:
        logger.error(f"Error sending pinned file {filename}: {e}")
        return jsonify({'error': 'Failed to send file'}), 500


@app.route('/api/history', methods=['GET'])
def get_history():
    """获取历史消息 - 用于懒加载/无限滚动

    参数:
        uid: 用户ID
        before_id: 获取此ID之前的消息（可选，默认为最新）
        after_id: 获取此ID之后的消息（可选，用于向下加载）
        chat_id: 聊天目标ID（群组ID或私聊对方UID）
        chat_type: 'group' 或 'private'
        limit: 返回数量（默认 30，最大 100）

    返回:
        messages: 消息列表（按时间升序，旧 -> 新）
        has_more: 是否还有更早的消息
        has_newer: 是否还有更新的消息（仅当使用after_id时返回）
    """
    uid = request.args.get('uid')
    chat_id = request.args.get('chat_id')
    chat_type = request.args.get('chat_type', 'group')

    try:
        before_id = int(request.args.get('before_id', 0))
    except:
        before_id = 0

    try:
        after_id = int(request.args.get('after_id', 0))
    except:
        after_id = 0

    try:
        limit = min(int(request.args.get('limit', 50)), 100)
    except:
        limit = 50

    if not uid or not chat_id:
        return jsonify({'error': 'Missing parameters'}), 400

    conn = get_db_connection()

    # 检查用户状态
    user = conn.execute(
        'SELECT deleted, session_invalidated FROM users WHERE uid = ?', (uid,)).fetchone()
    if user and (user['deleted'] or user['session_invalidated']):
        return jsonify({'error': 'session_invalidated'}), 403

    # 权限检查
    if chat_type == 'group':
        group = conn.execute(
            'SELECT id FROM groups WHERE id = ?', (chat_id,)).fetchone()
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        if chat_id != 'group_global':
            member = conn.execute(
                'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
                (chat_id, uid)
            ).fetchone()
            if not member:
                return jsonify({'error': 'Not in group'}), 403

    # 构建查询条件
    params = []
    use_after = after_id > 0  # 是否使用向下加载模式

    if chat_type == 'group':
        if use_after:
            # 向下加载：获取 after_id 之后的消息
            query = '''SELECT * FROM messages WHERE to_uid = ? AND id > ? ORDER BY id ASC LIMIT ?'''
            params = [chat_id, after_id, limit + 1]
        elif before_id > 0:
            query = '''SELECT * FROM messages WHERE to_uid = ? AND id < ? ORDER BY id DESC LIMIT ?'''
            params = [chat_id, before_id, limit + 1]
        else:
            query = '''SELECT * FROM messages WHERE to_uid = ? ORDER BY id DESC LIMIT ?'''
            params = [chat_id, limit + 1]
    else:
        # 私聊: 获取双方的消息
        if chat_id == uid:
            # 自己与自己的聊天
            if use_after:
                query = '''SELECT * FROM messages WHERE from_uid = ? AND to_uid = ? AND id > ? ORDER BY id ASC LIMIT ?'''
                params = [uid, uid, after_id, limit + 1]
            elif before_id > 0:
                query = '''SELECT * FROM messages WHERE from_uid = ? AND to_uid = ? AND id < ? ORDER BY id DESC LIMIT ?'''
                params = [uid, uid, before_id, limit + 1]
            else:
                query = '''SELECT * FROM messages WHERE from_uid = ? AND to_uid = ? ORDER BY id DESC LIMIT ?'''
                params = [uid, uid, limit + 1]
        else:
            if use_after:
                query = '''SELECT * FROM messages WHERE 
                          ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?)) 
                          AND id > ? 
                          ORDER BY id ASC LIMIT ?'''
                params = [uid, chat_id, chat_id, uid, after_id, limit + 1]
            elif before_id > 0:
                query = '''SELECT * FROM messages WHERE 
                          ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?)) 
                          AND id < ? 
                          ORDER BY id DESC LIMIT ?'''
                params = [uid, chat_id, chat_id, uid, before_id, limit + 1]
            else:
                query = '''SELECT * FROM messages WHERE 
                          ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?)) 
                          ORDER BY id DESC LIMIT ?'''
                params = [uid, chat_id, chat_id, uid, limit + 1]

    # 应用访问控制过滤
    query, params = apply_registration_time_filter(uid, query, params)

    rows = conn.execute(query, params).fetchall()

    # 判断是否还有更多消息
    has_more_result = len(rows) > limit
    if has_more_result:
        rows = rows[:limit]

    # 获取访问边界信息
    boundary_info = get_access_boundary_info(uid, chat_id, chat_type)
    
    # 处理结果
    messages = []
    if use_after:
        # 向下加载时，结果已经按 id ASC 排序，直接使用
        for m in rows:
            msg_dict = dict(m)
            # 类型安全：将消息 ID 转换为 String
            msg_dict['id'] = str(msg_dict['id'])
            if msg_dict['quote_json']:
                try:
                    msg_dict['quote'] = json.loads(msg_dict['quote_json'])
                    # 类型安全：引用消息的 ID 也转换为 String
                    if msg_dict['quote'] and 'id' in msg_dict['quote']:
                        msg_dict['quote']['id'] = str(msg_dict['quote']['id'])
                except:
                    msg_dict['quote'] = None
            else:
                msg_dict['quote'] = None
            del msg_dict['quote_json']
            
            # 引用消息访问控制：补充引用消息的完整内容（如果用户有权访问）
            enrich_quoted_message(uid, msg_dict)
            
            messages.append(msg_dict)

        return jsonify({
            'messages': messages,
            'has_more': False,  # 向下加载时 has_more 表示向上无意义
            'has_newer': has_more_result  # 是否还有更新的消息
        })
    else:
        # 向上加载时，需要反转结果使消息按时间升序（旧 -> 新）
        for m in reversed(rows):
            msg_dict = dict(m)
            # 类型安全：将消息 ID 转换为 String
            msg_dict['id'] = str(msg_dict['id'])
            if msg_dict['quote_json']:
                try:
                    msg_dict['quote'] = json.loads(msg_dict['quote_json'])
                    # 类型安全：引用消息的 ID 也转换为 String
                    if msg_dict['quote'] and 'id' in msg_dict['quote']:
                        msg_dict['quote']['id'] = str(msg_dict['quote']['id'])
                except:
                    msg_dict['quote'] = None
            else:
                msg_dict['quote'] = None
            del msg_dict['quote_json']
            
            # 引用消息访问控制：补充引用消息的完整内容（如果用户有权访问）
            enrich_quoted_message(uid, msg_dict)
            
            messages.append(msg_dict)

        # 检查是否到达访问边界
        # 如果有限制且没有更多消息，或者最早的消息就是最早可访问的消息，则到达边界
        reached_boundary = False
        if boundary_info['has_restricted_access'] and not has_more_result:
            # 没有更多消息了，检查是否因为访问限制
            if boundary_info['total_restricted_count'] > 0:
                reached_boundary = True
        elif boundary_info['has_restricted_access'] and messages:
            # 检查最早的消息是否是最早可访问的消息
            oldest_msg_id = messages[0]['id']
            if oldest_msg_id == boundary_info['oldest_accessible_msg_id']:
                reached_boundary = True
                has_more_result = False  # 到达边界时设置 has_more = False

        # 构建响应
        response = {
            'messages': messages,
            'has_more': has_more_result
        }

        # 实现空状态区分
        if not messages:
            # 没有消息，需要区分是"无消息"还是"无可访问消息"
            if boundary_info['has_restricted_access'] and boundary_info['total_restricted_count'] > 0:
                # 有消息但都不可访问
                response['empty_state'] = 'no_accessible_messages'
                response['empty_message'] = f"该聊天中有 {boundary_info['total_restricted_count']} 条消息发送于您的注册时间之前，您无法查看"
            else:
                # 真的没有消息
                response['empty_state'] = 'no_messages'
                response['empty_message'] = '暂无消息'

        # 添加访问边界信息
        if boundary_info['has_restricted_access']:
            boundary_info['reached'] = reached_boundary
            response['access_boundary'] = {
                'reached': reached_boundary,
                'registration_time': boundary_info['registration_time'],
                'registration_date': boundary_info['registration_date'],
                'message': f"您只能查看注册后的消息（注册时间：{boundary_info['registration_date']}）" if reached_boundary else None,
                'total_restricted_count': boundary_info['total_restricted_count']
            }

        return jsonify(response)


@app.route('/api/message/context', methods=['GET'])
def get_message_context():
    """获取指定消息的上下文（前后各15条消息）

    用于引用消息跳转：当目标消息不在当前DOM中时，
    需要加载包含该消息的上下文，以便定位跳转。

    参数:
        uid: 用户ID（用于权限检查和私聊判断）
        msg_id: 目标消息ID

    返回:
        messages: 消息列表（目标消息前后各15条，共约31条）
        target_msg_id: 目标消息ID
    """
    uid = request.args.get('uid')
    try:
        msg_id = int(request.args.get('msg_id', 0))
    except:
        return jsonify({'error': 'Invalid msg_id'}), 400

    if not uid or not msg_id:
        return jsonify({'error': 'Missing parameters'}), 400

    conn = get_db_connection()

    # 检查用户状态
    user = conn.execute(
        'SELECT deleted, session_invalidated FROM users WHERE uid = ?', (uid,)).fetchone()
    if user and (user['deleted'] or user['session_invalidated']):
        return jsonify({'error': 'session_invalidated'}), 403

    # 获取目标消息
    target_msg = conn.execute(
        'SELECT * FROM messages WHERE id = ?', (msg_id,)).fetchone()
    if not target_msg:
        return jsonify({'error': 'Message not found'}), 404

    target_msg_dict = dict(target_msg)
    to_uid = target_msg_dict['to_uid']
    from_uid = target_msg_dict['from_uid']

    # 判断是群聊还是私聊
    group = conn.execute(
        'SELECT id FROM groups WHERE id = ?', (to_uid,)).fetchone()
    is_group = group is not None

    # 权限检查
    if is_group:
        # 群聊消息
        if to_uid != 'group_global':
            member = conn.execute(
                'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
                (to_uid, uid)
            ).fetchone()
            if not member:
                return jsonify({'error': 'Not in group'}), 403
    else:
        # 私聊消息：必须是发送者或接收者
        if uid != from_uid and uid != to_uid:
            return jsonify({'error': 'Permission denied'}), 403

    # 访问控制：检查目标消息是否可访问
    user_info = conn.execute(
        'SELECT registered_at, unrestricted_access FROM users WHERE uid = ?',
        (uid,)
    ).fetchone()
    
    if user_info:
        unrestricted_access = user_info['unrestricted_access'] or 0
        registered_at = user_info['registered_at']
        
        # 如果有访问限制（非无限制访问且有注册时间）
        if unrestricted_access != 1 and registered_at is not None:
            # 检查目标消息是否在注册时间之前且不是用户自己发送的
            target_timestamp = target_msg_dict['timestamp']
            if target_timestamp < registered_at and from_uid != uid:
                # 目标消息不可访问，返回 403 错误
                registration_date = datetime.datetime.fromtimestamp(registered_at).strftime('%Y-%m-%d %H:%M:%S')
                return jsonify({
                    'error': 'access_denied',
                    'message': '该消息发送于您的注册时间之前',
                    'details': {
                        'registration_time': registered_at,
                        'registration_date': registration_date,
                        'requested_message_time': target_timestamp
                    }
                }), 403

    # 构建查询条件
    context_limit = 15

    if is_group:
        # 群聊：查询 to_uid 等于群ID 的消息
        # 获取目标消息之前的15条
        before_query = '''SELECT * FROM messages 
               WHERE to_uid = ? AND id < ? 
               ORDER BY id DESC LIMIT ?'''
        before_params = [to_uid, msg_id, context_limit]
        
        # 应用访问控制过滤
        before_query, before_params = apply_registration_time_filter(uid, before_query, before_params)
        before_msgs = conn.execute(before_query, before_params).fetchall()

        # 获取目标消息之后的15条
        after_query = '''SELECT * FROM messages 
               WHERE to_uid = ? AND id > ? 
               ORDER BY id ASC LIMIT ?'''
        after_params = [to_uid, msg_id, context_limit]
        
        # 应用访问控制过滤
        after_query, after_params = apply_registration_time_filter(uid, after_query, after_params)
        after_msgs = conn.execute(after_query, after_params).fetchall()
    else:
        # 私聊：查询 from_uid/to_uid 双向组合
        if from_uid == to_uid:
            # 与自己聊天
            before_query = '''SELECT * FROM messages 
                   WHERE from_uid = ? AND to_uid = ? AND id < ? 
                   ORDER BY id DESC LIMIT ?'''
            before_params = [from_uid, to_uid, msg_id, context_limit]
            
            # 应用访问控制过滤
            before_query, before_params = apply_registration_time_filter(uid, before_query, before_params)
            before_msgs = conn.execute(before_query, before_params).fetchall()

            after_query = '''SELECT * FROM messages 
                   WHERE from_uid = ? AND to_uid = ? AND id > ? 
                   ORDER BY id ASC LIMIT ?'''
            after_params = [from_uid, to_uid, msg_id, context_limit]
            
            # 应用访问控制过滤
            after_query, after_params = apply_registration_time_filter(uid, after_query, after_params)
            after_msgs = conn.execute(after_query, after_params).fetchall()
        else:
            # 普通私聊
            before_query = '''SELECT * FROM messages 
                   WHERE ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?)) 
                   AND id < ? 
                   ORDER BY id DESC LIMIT ?'''
            before_params = [from_uid, to_uid, to_uid, from_uid, msg_id, context_limit]
            
            # 应用访问控制过滤
            before_query, before_params = apply_registration_time_filter(uid, before_query, before_params)
            before_msgs = conn.execute(before_query, before_params).fetchall()

            after_query = '''SELECT * FROM messages 
                   WHERE ((from_uid = ? AND to_uid = ?) OR (from_uid = ? AND to_uid = ?)) 
                   AND id > ? 
                   ORDER BY id ASC LIMIT ?'''
            after_params = [from_uid, to_uid, to_uid, from_uid, msg_id, context_limit]
            
            # 应用访问控制过滤
            after_query, after_params = apply_registration_time_filter(uid, after_query, after_params)
            after_msgs = conn.execute(after_query, after_params).fetchall()

    # 组合消息：before(反转) + target + after
    all_msgs = []

    # before 是按 id DESC 排序的，需要反转
    for m in reversed(before_msgs):
        all_msgs.append(m)

    # 添加目标消息
    all_msgs.append(target_msg)

    # after 已经是按 id ASC 排序的
    for m in after_msgs:
        all_msgs.append(m)

    # 转换为可序列化格式并解析 quote_json
    messages = []
    for m in all_msgs:
        msg_dict = dict(m)
        # 类型安全：将消息 ID 转换为 String
        msg_dict['id'] = str(msg_dict['id'])
        if msg_dict['quote_json']:
            try:
                msg_dict['quote'] = json.loads(msg_dict['quote_json'])
                # 类型安全：引用消息的 ID 也转换为 String
                if msg_dict['quote'] and 'id' in msg_dict['quote']:
                    msg_dict['quote']['id'] = str(msg_dict['quote']['id'])
            except:
                msg_dict['quote'] = None
        else:
            msg_dict['quote'] = None
        del msg_dict['quote_json']
        
        # 引用消息访问控制：补充引用消息的完整内容（如果用户有权访问）
        enrich_quoted_message(uid, msg_dict)
        
        messages.append(msg_dict)

    return jsonify({
        'messages': messages,
        'target_msg_id': str(msg_id),  # 类型安全：转换为 String
        'chat_id': to_uid,
        'is_group': is_group
    })


@app.route('/api/admin/logs', methods=['POST'])
def get_admin_logs():
    """
    管理员日志查看接口
    
    - 此接口不调用 apply_registration_time_filter()
    - 返回所有消息，不受注册时间限制
    - 管理员可以查看完整的历史记录用于审计和管理
    """
    if request.json.get('password') != FINAL_ADMIN_PASSWORD_2:
        return jsonify({'error': 'Access Denied'}), 403

    conn = get_db_connection()

    # 获取所有消息（类型安全：ID 转换为 String）
    # 注意：管理员查询不应用访问控制过滤，可以查看所有历史消息
    messages = []
    for m in conn.execute('SELECT * FROM messages ORDER BY id').fetchall():
        msg_dict = dict(m)
        # 类型安全：将消息 ID 转换为 String，避免前端 JavaScript 精度问题
        msg_dict['id'] = str(msg_dict['id'])
        if msg_dict['quote_json']:
            try:
                msg_dict['quote'] = json.loads(msg_dict['quote_json'])
                # 类型安全：引用消息的 ID 也转换为 String
                if msg_dict['quote'] and 'id' in msg_dict['quote']:
                    msg_dict['quote']['id'] = str(msg_dict['quote']['id'])
            except:
                msg_dict['quote'] = None
        else:
            msg_dict['quote'] = None
        del msg_dict['quote_json']
        
        # 管理员也需要看到完整的引用消息内容
        # 由于管理员有无限制访问权限，这里使用一个虚拟的管理员uid
        # 或者直接在这里补充引用消息内容（不检查访问控制）
        if msg_dict.get('quote') and msg_dict['quote'].get('id'):
            try:
                quoted_msg_id = int(msg_dict['quote']['id'])
                quoted_msg = conn.execute(
                    'SELECT * FROM messages WHERE id = ?',
                    (quoted_msg_id,)
                ).fetchone()
                
                if quoted_msg:
                    msg_dict['quote']['accessible'] = True
                    msg_dict['quote']['from_uid'] = quoted_msg['from_uid']
                    msg_dict['quote']['content'] = quoted_msg['content']
                    msg_dict['quote']['type'] = quoted_msg['type']
                    msg_dict['quote']['timestamp'] = quoted_msg['timestamp']
                    msg_dict['quote']['is_recalled'] = bool(quoted_msg['is_recalled'])
                    
                    if quoted_msg['type'] in ['file', 'image']:
                        msg_dict['quote']['filename'] = quoted_msg['filename']
                        msg_dict['quote']['size'] = quoted_msg['size']
                        msg_dict['quote']['is_img'] = bool(quoted_msg['is_img'])
                else:
                    msg_dict['quote']['accessible'] = False
                    msg_dict['quote']['access_denied_reason'] = '原消息不存在'
            except (ValueError, TypeError):
                pass
        
        messages.append(msg_dict)

    # 获取所有用户
    users = {}
    for u in conn.execute('SELECT * FROM users').fetchall():
        users[u['uid']] = dict(u)

    # 获取所有群组
    groups = {}
    for g in conn.execute('SELECT * FROM groups').fetchall():
        gid = g['id']
        members = [row['uid'] for row in conn.execute(
            'SELECT uid FROM group_members WHERE group_id = ?', (gid,)
        ).fetchall()]
        groups[gid] = {
            'id': gid,
            'name': g['name'],
            'members': members,
            'is_group': True,
            'system': bool(g['is_system']),
            'owner': g['owner']
        }

    return jsonify({'messages': messages, 'users': users, 'groups': groups})


# ================= P2P文件传输信令服务器 API =================

@app.route('/p2p/initiate', methods=['POST'])
def p2p_initiate():
    """
    发起P2P传输会话
    
    接收文件元数据（支持多文件），生成唯一session_id，
    创建会话记录和文件记录，处理群聊广播逻辑
    
    请求体:
    {
        "uid": "sender_uid",
        "to_uid": "receiver_uid_or_group_id",
        "chat_type": "private|group",
        "files": [
            {
                "filename": "large_file1.zip",
                "size": 1073741824,
                "file_hash": "abc123...",
                "mime_type": "application/zip"
            }
        ]
    }
    
    响应:
    {
        "session_id": "p2p_session_uuid",
        "status": "pending",
        "expires_at": 1234567890,
        "total_size": 3221225472,
        "file_count": 2
    }
    
    """
    try:
        req = request.json
        uid = req.get('uid')
        to_uid = req.get('to_uid')
        chat_type = req.get('chat_type', 'private')
        files = req.get('files', [])
        
        # 验证必需字段
        if not uid or not to_uid or not files:
            return jsonify({'error': '缺少必需字段'}), 400
        
        # 验证文件列表
        if not isinstance(files, list) or len(files) == 0:
            return jsonify({'error': '文件列表不能为空'}), 400
        
        # 计算总大小和文件数量
        total_size = sum(f.get('size', 0) for f in files)
        file_count = len(files)
        
        # 生成唯一的session_id (使用UUID确保唯一性)
        session_id = f"p2p_{uuid.uuid4().hex}"
        
        # 设置会话过期时间（30分钟后）
        created_at = time.time()
        expires_at = created_at + 30 * 60  # 30分钟
        
        conn = get_db_connection()
        
        # 检查发送者账户状态
        user = conn.execute(
            'SELECT deleted, session_invalidated FROM users WHERE uid = ?', 
            (uid,)
        ).fetchone()
        if user and (user['deleted'] or user['session_invalidated']):
            return jsonify({
                'error': 'session_invalidated',
                'message': '您的账户已被禁用'
            }), 403
        
        # 如果是群聊，验证发送者是否在群组中
        if chat_type == 'group':
            group = conn.execute(
                'SELECT id FROM groups WHERE id = ?', 
                (to_uid,)
            ).fetchone()
            if not group:
                return jsonify({'error': '群组不存在'}), 404
            
            if to_uid != 'group_global':
                member = conn.execute(
                    'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
                    (to_uid, uid)
                ).fetchone()
                if not member:
                    return jsonify({'error': '不在群组中'}), 403
        
        # 创建P2P会话记录
        if chat_type == 'private':
            conn.execute(
                '''INSERT INTO p2p_sessions 
                   (session_id, sender_uid, receiver_uid, group_id, chat_type, 
                    total_size, file_count, status, created_at, expires_at, supports_resume, protocol_version)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, 'pending', ?, ?, 1, 17)''',
                (session_id, uid, to_uid, chat_type, total_size, file_count, 
                 created_at, expires_at)
            )
        else:  # group
            conn.execute(
                '''INSERT INTO p2p_sessions 
                   (session_id, sender_uid, receiver_uid, group_id, chat_type, 
                    total_size, file_count, status, created_at, expires_at, supports_resume, protocol_version)
                   VALUES (?, ?, NULL, ?, ?, ?, ?, 'pending', ?, ?, 1, 17)''',
                (session_id, uid, to_uid, chat_type, total_size, file_count, 
                 created_at, expires_at)
            )
        
        # 创建文件记录
        for idx, file_info in enumerate(files):
            conn.execute(
                '''INSERT INTO p2p_session_files 
                   (session_id, file_index, filename, size, file_hash, mime_type, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')''',
                (session_id, idx, file_info.get('filename', ''), 
                 file_info.get('size', 0), file_info.get('file_hash', ''),
                 file_info.get('mime_type', ''))
            )
        
        # 如果是群聊，创建参与者记录（广播给所有在线成员）
        if chat_type == 'group':
            # 获取群组所有成员
            members = conn.execute(
                'SELECT uid FROM group_members WHERE group_id = ?',
                (to_uid,)
            ).fetchall()
            
            for member in members:
                member_uid = member['uid']
                # 不包括发送者自己
                if member_uid != uid:
                    conn.execute(
                        '''INSERT INTO p2p_session_participants 
                           (session_id, uid, status)
                           VALUES (?, ?, 'pending')''',
                        (session_id, member_uid)
                    )
        
        conn.commit()
        
        # 记录到审计日志数据库（不包含文件内容）
        log_p2p_transfer_start(
            session_id=session_id,
            sender_uid=uid,
            receiver_uid=to_uid if chat_type == 'private' else None,
            group_id=to_uid if chat_type == 'group' else None,
            chat_type=chat_type,
            total_size=total_size,
            file_count=file_count
        )
        
        return jsonify({
            'session_id': session_id,
            'status': 'pending',
            'expires_at': expires_at,
            'total_size': total_size,
            'file_count': file_count,
            'protocol_version': 17,
            'chunk_integrity_enabled': True
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_initiate: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/respond', methods=['POST'])
def p2p_respond():
    """
    接收方响应传输请求
    
    处理接收方的接受/拒绝响应，更新会话状态，通知发送方
    
    请求体:
    {
        "session_id": "p2p_session_uuid",
        "uid": "receiver_uid",
        "accept": true,
        "reason": null
    }
    
    响应:
    {
        "status": "accepted|rejected"
    }
    
    """
    try:
        req = request.json
        session_id = req.get('session_id')
        uid = req.get('uid')
        accept = req.get('accept', False)
        reason = req.get('reason')
        
        # 验证必需字段
        if not session_id or not uid:
            return jsonify({'error': '缺少必需字段'}), 400
        
        conn = get_db_connection()
        
        # 检查会话是否存在
        session = conn.execute(
            'SELECT * FROM p2p_sessions WHERE session_id = ?',
            (session_id,)
        ).fetchone()
        
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        
        # 检查会话是否过期
        if time.time() > session['expires_at']:
            return jsonify({'error': '会话已过期'}), 410
        
        # 检查用户是否有权响应此会话
        chat_type = session['chat_type']
        if chat_type == 'private':
            if uid != session['receiver_uid']:
                return jsonify({'error': '无权响应此会话'}), 403
        else:  # group
            # 检查是否是群成员
            participant = conn.execute(
                'SELECT * FROM p2p_session_participants WHERE session_id = ? AND uid = ?',
                (session_id, uid)
            ).fetchone()
            if not participant:
                return jsonify({'error': '无权响应此会话'}), 403
        
        # 更新响应状态
        responded_at = time.time()
        
        if chat_type == 'private':
            # 私聊：更新会话状态
            if accept:
                # 设置为connecting状态，保持会话在活跃列表中
                conn.execute(
                    'UPDATE p2p_sessions SET status = ? WHERE session_id = ?',
                    ('connecting', session_id)
                )
            else:
                conn.execute(
                    'UPDATE p2p_sessions SET status = ?, error_message = ? WHERE session_id = ?',
                    ('rejected', reason or '接收方拒绝', session_id)
                )
                log_p2p_transfer_result(
                    session_id=session_id,
                    status='rejected',
                    error_message=reason or '接收方拒绝'
                )
        else:  # group
            # 群聊：更新参与者状态
            if accept:
                conn.execute(
                    '''UPDATE p2p_session_participants 
                       SET status = ?, responded_at = ? 
                       WHERE session_id = ? AND uid = ?''',
                    ('accepted', responded_at, session_id, uid)
                )
                # 如果有人接受，将会话状态改为active
                conn.execute(
                    'UPDATE p2p_sessions SET status = ? WHERE session_id = ? AND status = ?',
                    ('active', session_id, 'pending')
                )
            else:
                conn.execute(
                    '''UPDATE p2p_session_participants 
                       SET status = ?, responded_at = ? 
                       WHERE session_id = ? AND uid = ?''',
                    ('rejected', responded_at, session_id, uid)
                )
        
        conn.commit()
        
        return jsonify({
            'status': 'accepted' if accept else 'rejected'
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_respond: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/signal', methods=['POST'])
def p2p_signal():
    """
    转发WebRTC信令数据
    
    转发WebRTC信令数据（offer/answer/ICE候选），验证会话有效性，
    存储信令数据到p2p_signals表
    
    请求体:
    {
        "session_id": "p2p_session_uuid",
        "from_uid": "sender_or_receiver_uid",
        "to_uid": "target_uid",
        "signal_type": "offer|answer|ice-candidate",
        "signal_data": { /* SDP or ICE candidate */ }
    }
    
    响应:
    {
        "status": "ok"
    }
    
    """
    try:
        req = request.json
        session_id = req.get('session_id')
        from_uid = req.get('from_uid')
        to_uid = req.get('to_uid')  # 可选，群聊时使用
        signal_type = req.get('signal_type')
        signal_data = req.get('signal_data')
        
        # 验证必需字段
        if not all([session_id, from_uid, signal_type, signal_data]):
            return jsonify({'error': '缺少必需字段'}), 400
        
        # 验证signal_type
        valid_types = ['offer', 'answer', 'ice-candidate']
        if signal_type not in valid_types:
            return jsonify({'error': '无效的信令类型'}), 400
        
        conn = get_db_connection()
        
        session = conn.execute(
            'SELECT * FROM p2p_sessions WHERE session_id = ?',
            (session_id,)
        ).fetchone()
        
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        
        # 检查会话是否过期
        if time.time() > session['expires_at']:
            return jsonify({'error': '会话已过期'}), 410
        
        # 如果没有指定to_uid，根据会话类型确定
        if not to_uid:
            if session['chat_type'] == 'private':
                # 私聊：确定对方是谁
                if from_uid == session['sender_uid']:
                    to_uid = session['receiver_uid']
                else:
                    to_uid = session['sender_uid']
            else:
                # 群聊必须指定to_uid
                return jsonify({'error': '群聊信令必须指定to_uid'}), 400
        
        # 将signal_data转换为JSON字符串存储
        signal_data_json = json.dumps(signal_data)
        created_at = time.time()
        
        conn.execute(
            '''INSERT INTO p2p_signals 
               (session_id, from_uid, to_uid, signal_type, signal_data, created_at, consumed)
               VALUES (?, ?, ?, ?, ?, ?, 0)''',
            (session_id, from_uid, to_uid, signal_type, signal_data_json, created_at)
        )
        
        conn.commit()
        
        logger.debug(
            f"P2P signal forwarded - "
            f"session_id={session_id}, "
            f"from_uid={from_uid}, "
            f"to_uid={to_uid}, "
            f"signal_type={signal_type}"
        )
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        logger.error(f"Error in p2p_signal: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/sessions', methods=['GET'])
def p2p_sessions():
    """
    获取用户的活跃P2P会话
    
    查询用户的活跃P2P会话，返回会话状态和进度
    此接口将集成到/sync接口中
    
    查询参数:
    - uid: 用户ID
    
    响应:
    {
        "sessions": [
            {
                "session_id": "p2p_session_uuid",
                "role": "sender|receiver",
                "peer_uid": "other_user_uid",
                "chat_type": "private|group",
                "total_size": 1073741824,
                "file_count": 2,
                "status": "pending|active|completed|failed",
                "created_at": 1234567890,
                "expires_at": 1234567890
            }
        ],
        "pending_signals": [
            {
                "session_id": "p2p_session_uuid",
                "from_uid": "sender_uid",
                "signal_type": "offer|answer|ice-candidate",
                "signal_data": { /* SDP or ICE candidate */ },
                "created_at": 1234567890
            }
        ]
    }
    
    """
    try:
        uid = request.args.get('uid')
        
        if not uid:
            return jsonify({'error': '缺少uid参数'}), 400
        
        conn = get_db_connection()
        
        sessions = []
        
        # 查询作为发送方的会话
        sender_sessions = conn.execute(
            '''SELECT * FROM p2p_sessions 
               WHERE sender_uid = ? AND status IN ('pending', 'active', 'connecting')
               ORDER BY created_at DESC''',
            (uid,)
        ).fetchall()
        
        for session in sender_sessions:
            sessions.append({
                'session_id': session['session_id'],
                'role': 'sender',
                'peer_uid': session['receiver_uid'] or session['group_id'],
                'chat_type': session['chat_type'],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            })
        
        # 查询作为接收方的会话（私聊）
        receiver_sessions = conn.execute(
            '''SELECT * FROM p2p_sessions 
               WHERE receiver_uid = ? AND status IN ('pending', 'active', 'connecting')
               ORDER BY created_at DESC''',
            (uid,)
        ).fetchall()
        
        for session in receiver_sessions:
            sessions.append({
                'session_id': session['session_id'],
                'role': 'receiver',
                'peer_uid': session['sender_uid'],
                'chat_type': session['chat_type'],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            })
        
        # 查询作为群成员的会话
        group_sessions = conn.execute(
            '''SELECT s.* FROM p2p_sessions s
               INNER JOIN p2p_session_participants p ON s.session_id = p.session_id
               WHERE p.uid = ? AND s.status IN ('pending', 'active', 'connecting')
               ORDER BY s.created_at DESC''',
            (uid,)
        ).fetchall()
        
        for session in group_sessions:
            sessions.append({
                'session_id': session['session_id'],
                'role': 'receiver',
                'peer_uid': session['sender_uid'],
                'chat_type': session['chat_type'],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at']
            })
        
        # 查询待处理的信令数据
        pending_signals = conn.execute(
            '''SELECT * FROM p2p_signals 
               WHERE to_uid = ? AND consumed = 0
               ORDER BY created_at ASC''',
            (uid,)
        ).fetchall()
        
        signals = []
        for signal in pending_signals:
            signals.append({
                'id': signal['id'],
                'session_id': signal['session_id'],
                'from_uid': signal['from_uid'],
                'signal_type': signal['signal_type'],
                'signal_data': json.loads(signal['signal_data']),
                'created_at': signal['created_at']
            })
            
            # 标记信令为已消费
            conn.execute(
                'UPDATE p2p_signals SET consumed = 1 WHERE id = ?',
                (signal['id'],)
            )
        
        conn.commit()
        
        return jsonify({
            'sessions': sessions,
            'pending_signals': signals
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_sessions: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/complete', methods=['POST'])
def p2p_complete():
    """
    标记传输完成并创建消息记录
    
    标记传输完成，创建聊天消息记录（支持多文件），更新会话状态
    
    请求体:
    {
        "session_id": "p2p_session_uuid",
        "uid": "sender_uid",
        "to_uid": "receiver_uid_or_group_id",
        "verified_hashes": ["abc123...", "def456..."]
    }
    
    响应:
    {
        "message_id": 12345,
        "status": "ok"
    }
    
    """
    try:
        req = request.json
        session_id = req.get('session_id')
        uid = req.get('uid')
        to_uid = req.get('to_uid')
        verified_hashes = req.get('verified_hashes', [])
        
        # 验证必需字段
        if not all([session_id, uid, to_uid]):
            return jsonify({'error': '缺少必需字段'}), 400
        
        conn = get_db_connection()
        
        # 检查会话是否存在
        session = conn.execute(
            'SELECT * FROM p2p_sessions WHERE session_id = ?',
            (session_id,)
        ).fetchone()
        
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        
        # 获取会话的所有文件
        files = conn.execute(
            '''SELECT * FROM p2p_session_files 
               WHERE session_id = ? 
               ORDER BY file_index ASC''',
            (session_id,)
        ).fetchall()
        
        if not files:
            return jsonify({'error': '会话没有文件'}), 400
        
        msg_id = get_unique_msg_id()
        
        # 构建消息内容
        if len(files) == 1:
            # 单文件
            file = files[0]
            content = f"P2P传输: {file['filename']}"
            filename = file['filename']
            size = file['size']
            file_hash = file['file_hash']
        else:
            # 多文件
            filenames = [f['filename'] for f in files]
            content = f"P2P传输 ({len(files)}个文件): " + ", ".join(filenames)
            filename = json.dumps(filenames)  # 存储为JSON数组
            size = sum(f['size'] for f in files)
            file_hash = json.dumps([f['file_hash'] for f in files])  # 存储为JSON数组
        
        # 插入消息记录
        conn.execute(
            '''INSERT INTO messages 
               (id, from_uid, to_uid, type, content, filename, size, timestamp, 
                transfer_method, p2p_session_id, file_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (msg_id, uid, to_uid, 'p2p_file', content, filename, size, 
             time.time(), 'p2p', session_id, file_hash)
        )
        
        # 更新会话状态
        completed_at = time.time()
        conn.execute(
            'UPDATE p2p_sessions SET status = ?, completed_at = ? WHERE session_id = ?',
            ('completed', completed_at, session_id)
        )
        
        # 更新所有文件状态
        for file in files:
            conn.execute(
                '''UPDATE p2p_session_files 
                   SET status = ?, completed_at = ? 
                   WHERE session_id = ? AND file_index = ?''',
                ('completed', completed_at, session_id, file['file_index'])
            )
        
        conn.commit()
        
        # 记录到审计日志数据库
        log_p2p_transfer_result(
            session_id=session_id,
            status='completed',
            error_message=None
        )
        
        return jsonify({
            'message_id': msg_id,
            'status': 'ok'
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_complete: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/resume', methods=['POST'])
def p2p_resume():
    """
    请求断点续传信息
    
    查询断点续传数据，验证会话未过期，返回恢复位置
    
    请求体:
    {
        "session_id": "p2p_session_uuid",
        "uid": "user_uid",
        "file_index": 0,
        "current_offset": 524288000
    }
    
    响应:
    {
        "can_resume": true,
        "resume_from": 524288000,
        "file_index": 0
    }
    
    """
    try:
        req = request.json
        session_id = req.get('session_id')
        uid = req.get('uid')
        file_index = req.get('file_index', 0)
        current_offset = req.get('current_offset', 0)
        
        # 验证必需字段
        if not all([session_id, uid is not None]):
            return jsonify({'error': '缺少必需字段'}), 400
        
        conn = get_db_connection()
        
        # 检查会话是否存在
        session = conn.execute(
            'SELECT * FROM p2p_sessions WHERE session_id = ?',
            (session_id,)
        ).fetchone()
        
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        
        # 检查会话是否过期
        if time.time() > session['expires_at']:
            return jsonify({
                'can_resume': False,
                'error': '会话已过期'
            }), 410
        
        # 检查是否支持断点续传
        if not session['supports_resume']:
            return jsonify({
                'can_resume': False,
                'error': '此会话不支持断点续传'
            }), 400
        
        # 查询断点续传数据
        resume_point = conn.execute(
            '''SELECT * FROM p2p_resume_points 
               WHERE session_id = ? AND uid = ? AND file_index = ?''',
            (session_id, uid, file_index)
        ).fetchone()
        
        if resume_point:
            # 检查断点数据是否过期（24小时）
            if time.time() - resume_point['updated_at'] > 24 * 60 * 60:
                # 清理过期的断点数据
                conn.execute(
                    '''DELETE FROM p2p_resume_points 
                       WHERE session_id = ? AND uid = ? AND file_index = ?''',
                    (session_id, uid, file_index)
                )
                conn.commit()
                
                return jsonify({
                    'can_resume': False,
                    'error': '断点数据已过期'
                })
            
            return jsonify({
                'can_resume': True,
                'resume_from': resume_point['offset'],
                'file_index': file_index
            })
        else:
            # 没有断点数据，从头开始
            return jsonify({
                'can_resume': True,
                'resume_from': 0,
                'file_index': file_index
            })
        
    except Exception as e:
        logger.error(f"Error in p2p_resume: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/cleanup', methods=['POST'])
def p2p_cleanup():
    """
    手动触发P2P会话清理
    
    清理过期的会话、断点数据和信令数据
    此接口可以由定时任务调用，或者在应用启动时调用
    
    响应:
    {
        "status": "ok",
        "expired_sessions": 5,
        "resume_points": 10,
        "signals": 20
    }
    
    """
    try:
        result = cleanup_expired_p2p_sessions()
        return jsonify({
            'status': 'ok',
            **result
        })
    except Exception as e:
        logger.error(f"Error in p2p_cleanup: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/stats', methods=['GET'])
def p2p_stats():
    """
    获取P2P传输统计信息（管理员接口）
    
    实现管理员统计API
    提供数据完整性相关的统计信息，包括截断率、重传成功率等
    
    监控指标说明：
    1. avg_truncation_rate: 平均截断率 - 监控网络质量和数据完整性
       - 目标值: <0.1% (0.001)
       - 警告阈值: >1% (0.01)
       - 严重阈值: >5% (0.05)
    
    2. retransmission_success_rate: 重传成功率 - 监控错误恢复能力
       - 目标值: >99.9% (0.999)
       - 警告阈值: <99% (0.99)
    
    3. final_data_loss_rate: 最终数据丢失率 - 监控系统可靠性
       - 目标值: 0% (0.0)
       - 任何非零值都需要立即关注
    
    4. adaptive_mechanism_triggers: 自适应机制触发次数 - 监控网络适应性
       - 正常范围: 10-30% 的传输会触发自适应调整
       - 过高可能表示网络不稳定
    
    5. high_truncation_warnings: 高截断率警告数量 - 监控异常情况
       - 目标值: 0
       - 任何非零值都需要调查网络或系统问题
    
    查询参数:
    - admin_token: 管理员认证token（可选，用于权限验证）
    
    响应:
    {
        "total_transfers": 1000,
        "completed_transfers": 850,
        "success_rate": 0.85,
        "avg_truncation_rate": 0.001,
        "retransmission_success_rate": 0.99,
        "final_data_loss_rate": 0.0,
        "adaptive_mechanism_triggers": 150,
        "high_truncation_warnings": 5,
        "total_data_transferred": 10737418240,
        "active_sessions": 5
    }
    
    """
    try:
        conn = get_db_connection()
        
        # 总传输次数
        total_result = conn.execute(
            'SELECT COUNT(*) as count FROM p2p_audit_logs'
        ).fetchone()
        total_transfers = total_result['count'] if total_result else 0
        
        # 按状态统计
        status_stats = {}
        status_results = conn.execute(
            '''SELECT status, COUNT(*) as count 
               FROM p2p_audit_logs 
               GROUP BY status'''
        ).fetchall()
        
        for row in status_results:
            status_stats[row['status']] = row['count']
        
        # 计算成功和失败数量
        completed_transfers = status_stats.get('completed', 0)
        failed_transfers = status_stats.get('failed', 0)
        rejected_transfers = status_stats.get('rejected', 0)
        timeout_transfers = status_stats.get('timeout', 0)
        cancelled_transfers = status_stats.get('cancelled', 0)
        
        # 计算成功率
        if total_transfers > 0:
            success_rate = completed_transfers / total_transfers
        else:
            success_rate = 0.0
        
        # 查询平均截断率（AVG(final_truncation_rate)）
        truncation_result = conn.execute(
            '''SELECT AVG(final_truncation_rate) as avg_truncation_rate,
                      COUNT(*) as sessions_with_truncation_data
               FROM p2p_sessions 
               WHERE final_truncation_rate IS NOT NULL AND final_truncation_rate >= 0'''
        ).fetchone()
        avg_truncation_rate = truncation_result['avg_truncation_rate'] if truncation_result and truncation_result['avg_truncation_rate'] else 0.0
        
        # 查询重传成功率
        # 重传成功率 = 有重传且最终成功的会话 / 有重传的会话总数
        retransmission_stats = conn.execute(
            '''SELECT 
                   COUNT(*) as total_retransmissions,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_retransmissions
               FROM p2p_sessions 
               WHERE retransmission_count > 0'''
        ).fetchone()
        
        if retransmission_stats and retransmission_stats['total_retransmissions'] > 0:
            retransmission_success_rate = retransmission_stats['successful_retransmissions'] / retransmission_stats['total_retransmissions']
        else:
            retransmission_success_rate = 1.0  # 如果没有重传，则认为成功率为100%
        
        # 查询最终数据丢失率（应为0）
        # 最终数据丢失率 = 最终失败的传输 / 总传输数
        final_data_loss_rate = failed_transfers / total_transfers if total_transfers > 0 else 0.0
        
        # 查询自适应机制触发次数
        # 自适应机制触发次数 = 截断率 > 0 的会话数量（表示触发了自适应调整）
        adaptive_triggers = conn.execute(
            '''SELECT COUNT(*) as count 
               FROM p2p_sessions 
               WHERE final_truncation_rate > 0'''
        ).fetchone()
        adaptive_mechanism_triggers = adaptive_triggers['count'] if adaptive_triggers else 0
        
        # 检测异常高截断率（>5%）并记录警告
        high_truncation_sessions = conn.execute(
            '''SELECT COUNT(*) as count 
               FROM p2p_sessions 
               WHERE final_truncation_rate > 0.05'''
        ).fetchone()
        high_truncation_warnings = high_truncation_sessions['count'] if high_truncation_sessions else 0
        
        # 如果检测到异常高截断率，记录警告
        if high_truncation_warnings > 0:
            logger.warning(
                f"P2P stats: Detected {high_truncation_warnings} sessions with high truncation rate (>5%). "
                f"This may indicate network issues or system problems."
            )
        
        # 总传输数据量（只计算成功的传输）
        data_result = conn.execute(
            '''SELECT SUM(total_size) as total 
               FROM p2p_audit_logs 
               WHERE status = 'completed' '''
        ).fetchone()
        total_data_transferred = data_result['total'] if data_result and data_result['total'] else 0
        
        # 活跃会话数量
        active_result = conn.execute(
            '''SELECT COUNT(*) as count 
               FROM p2p_sessions 
               WHERE status IN ('pending', 'active', 'connecting')'''
        ).fetchone()
        active_sessions = active_result['count'] if active_result else 0
        
        # 平均传输时长（只计算已完成的）
        duration_result = conn.execute(
            '''SELECT AVG(duration) as avg_duration 
               FROM p2p_audit_logs 
               WHERE status = 'completed' AND duration IS NOT NULL'''
        ).fetchone()
        avg_transfer_duration = duration_result['avg_duration'] if duration_result and duration_result['avg_duration'] else 0.0
        
        # 获取活跃会话详情
        active_sessions_detail = []
        active_sessions_rows = conn.execute(
            '''SELECT session_id, sender_uid, receiver_uid, group_id, chat_type, 
                      total_size, file_count, status, created_at, expires_at,
                      protocol_version, truncated_chunks, retransmission_count, final_truncation_rate
               FROM p2p_sessions 
               WHERE status IN ('pending', 'active', 'connecting')
               ORDER BY created_at DESC
               LIMIT 50'''
        ).fetchall()
        
        for session in active_sessions_rows:
            active_sessions_detail.append({
                'session_id': session['session_id'],
                'sender_uid': session['sender_uid'],
                'receiver_uid': session['receiver_uid'],
                'group_id': session['group_id'],
                'chat_type': session['chat_type'],
                'total_size': session['total_size'],
                'file_count': session['file_count'],
                'status': session['status'],
                'created_at': session['created_at'],
                'expires_at': session['expires_at'],
                'protocol_version': session['protocol_version'],
                'truncated_chunks': session['truncated_chunks'],
                'retransmission_count': session['retransmission_count'],
                'final_truncation_rate': session['final_truncation_rate']
            })
        
        return jsonify({
            'total_transfers': total_transfers,
            'completed_transfers': completed_transfers,
            'failed_transfers': failed_transfers,
            'rejected_transfers': rejected_transfers,
            'timeout_transfers': timeout_transfers,
            'cancelled_transfers': cancelled_transfers,
            'success_rate': round(success_rate, 4),
            'avg_truncation_rate': round(avg_truncation_rate, 6),
            'retransmission_success_rate': round(retransmission_success_rate, 4),
            'final_data_loss_rate': round(final_data_loss_rate, 6),
            'adaptive_mechanism_triggers': adaptive_mechanism_triggers,
            'high_truncation_warnings': high_truncation_warnings,
            'total_data_transferred': total_data_transferred,
            'active_sessions': active_sessions,
            'avg_transfer_duration': round(avg_transfer_duration, 2) if avg_transfer_duration else 0.0,
            'stats_by_status': status_stats,
            'active_sessions_detail': active_sessions_detail
        })
        
    except Exception as e:
        logger.error(f"Error in p2p_stats: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/p2p/anomalies', methods=['GET'])
def p2p_anomalies():
    """
    检测并返回P2P传输异常
    
    检测频繁失败、异常大文件、异常传输模式等，并记录警告日志
    
    查询参数:
    - admin_token: 管理员认证token（可选，用于权限验证）
    
    响应:
    {
        "anomalies_detected": 5,
        "anomalies": [
            {
                "type": "frequent_failures",
                "user_id": "user123",
                "failure_count": 8,
                "time_window": "1 hour",
                "severity": "high"
            },
            {
                "type": "large_file",
                "session_id": "p2p_abc123",
                "user_id": "user456",
                "file_size": 15000000000,
                "severity": "low"
            }
        ]
    }
    
    """
    try:
        result = detect_p2p_anomalies()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in p2p_anomalies: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


# ================= P2P传输消息API（前端重新设计） =================
# 创建传输消息API接口

@app.route('/api/p2p/messages', methods=['POST'])
def create_p2p_transfer_message():
    """
    创建P2P传输消息（整合到messages表）
    
    当用户发起P2P传输时，在messages表中创建一条文件消息记录
    
    请求体:
    {
        "senderId": "user-123",
        "receiverId": "user-456",
        "chatId": "chat-789",
        "fileInfo": {
            "name": "document.pdf",
            "size": 750000000,
            "type": "application/pdf",
            "hash": "abc123..."
        }
    }
    
    响应:
    {
        "success": true,
        "messageId": 12345,
        "timestamp": 1234567890.123
    }
    
    """
    start_time = time.time()
    try:
        req = request.json
        
        # 验证请求数据
        if not req:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400
        
        sender_id = req.get('senderId')
        receiver_id = req.get('receiverId')
        chat_id = req.get('chatId')  # 对于私聊，chat_id就是receiver_id；对于群聊，是group_id
        file_info = req.get('fileInfo', {})
        transfer_info = req.get('transferInfo', {})
        
        # 生成消息ID（使用数据库自增ID）
        transfer_id = transfer_info.get('id') or req.get('id') or f"transfer_{uuid.uuid4().hex}"
        
        # 处理时间戳：统一使用秒级时间戳
        frontend_timestamp = req.get('timestamp')
        if frontend_timestamp:
            # 如果是毫秒时间戳（大于10位数），转换为秒
            timestamp = frontend_timestamp / 1000 if frontend_timestamp > 10000000000 else frontend_timestamp
        else:
            timestamp = time.time()
        
        conn = get_db_connection()
        
        # 在messages表中插入P2P传输消息
        # type='file', transfer_method='p2p', p2p_status='pending'
        cursor = conn.execute('''
            INSERT INTO messages (
                from_uid, to_uid, type, content, timestamp,
                filename, size, is_img, file_hash,
                transfer_method, p2p_session_id, p2p_status, p2p_progress,
                p2p_speed, p2p_avg_speed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sender_id, chat_id, 'file', f'[P2P传输] {file_info.get("name")}', timestamp,
            file_info.get('name'), file_info.get('size'), 0, file_info.get('hash'),
            'p2p', transfer_id, 'pending', 0,
            0, 0
        ))
        
        message_id = cursor.lastrowid
        conn.commit()
        
        return jsonify({
            'success': True,
            'messageId': message_id,
            'transferId': transfer_id,
            'timestamp': timestamp
        })
        
    except Exception as e:
        logger.error(f"Error creating P2P transfer message: {e}")
        logger.error(f"Request data: {request.json}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'服务器内部错误: {str(e)}'}), 500


@app.route('/api/p2p/messages/<transfer_id>/status', methods=['PUT'])
def update_p2p_transfer_status(transfer_id):
    """
    更新P2P传输状态
    
    当传输状态发生变化时（接收、拒绝、连接中、传输中、完成等），更新数据库记录
    
    请求体:
    {
        "status": "accepted",
        "additionalData": {
            "startTime": 1234567890,
            "endTime": 1234567900,
            "avgSpeed": 2100000
        }
    }
    
    响应:
    {
        "success": true,
        "timestamp": 1234567890
    }
    
    """
    try:
        req = request.json
        status = req.get('status')
        additional_data = req.get('additionalData', {})
        
        # 验证必需字段
        if not status:
            return jsonify({'success': False, 'error': '缺少状态字段'}), 400
        
        # 验证状态值
        valid_statuses = ['pending', 'accepted', 'rejected', 'connecting', 'transferring', 'completed', 'failed', 'cancelled', 'expired']
        if status not in valid_statuses:
            return jsonify({'success': False, 'error': '无效的状态值'}), 400
        
        conn = get_db_connection()
        
        # 检查传输消息是否存在（在messages表中查找）
        message = conn.execute(
            'SELECT id FROM messages WHERE p2p_session_id = ? AND transfer_method = ?',
            (transfer_id, 'p2p')
        ).fetchone()
        
        if not message:
            # 消息不存在（可能是旧会话），返回成功（幂等性）
            logger.warning(f"Transfer message not found for transfer_id: {transfer_id}, skipping update")
            return jsonify({
                'success': True,
                'timestamp': time.time(),
                'skipped': True,
                'reason': 'Message not found'
            })
        
        # 构建更新SQL
        update_fields = ['p2p_status = ?']
        update_values = [status]
        
        # 处理附加数据
        if 'progress' in additional_data:
            update_fields.append('p2p_progress = ?')
            update_values.append(additional_data['progress'])
        
        if 'speed' in additional_data:
            update_fields.append('p2p_speed = ?')
            update_values.append(additional_data['speed'])
        
        if 'avgSpeed' in additional_data:
            update_fields.append('p2p_avg_speed = ?')
            update_values.append(additional_data['avgSpeed'])
        
        # 如果传输完成，更新server_filename字段（用于后续下载）
        if status == 'completed' and 'server_filename' in additional_data:
            update_fields.append('server_filename = ?')
            update_values.append(additional_data['server_filename'])
        
        # 添加transfer_id到值列表
        update_values.append(transfer_id)
        
        # 执行更新
        sql = f"UPDATE messages SET {', '.join(update_fields)} WHERE p2p_session_id = ? AND transfer_method = 'p2p'"
        conn.execute(sql, update_values)
        conn.commit()
        
        return jsonify({
            'success': True,
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Error updating P2P transfer status: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/messages/batch-update', methods=['PUT'])
def batch_update_p2p_progress():
    """
    批量更新P2P传输进度
    
    用于批量更新多个传输的进度信息，减少数据库写入次数
    
    请求体:
    {
        "updates": [
            {
                "transferId": "transfer-123",
                "progressData": {
                    "progress": 45,
                    "speed": 2400000,
                    "avgSpeed": 2100000,
                    "estimatedTime": 180,
                    "bytesTransferred": 337500000
                }
            }
        ]
    }
    
    响应:
    {
        "success": true,
        "updatedCount": 1
    }
    
    """
    try:
        req = request.json
        updates = req.get('updates', [])
        
        if not updates or not isinstance(updates, list):
            return jsonify({'success': False, 'error': '更新列表不能为空'}), 400
        
        conn = get_db_connection()
        updated_count = 0
        
        for update in updates:
            transfer_id = update.get('transferId')
            progress_data = update.get('progressData', {})
            
            if not transfer_id:
                continue
            
            # 构建更新SQL
            update_fields = []
            update_values = []
            
            if 'progress' in progress_data:
                update_fields.append('progress = ?')
                update_values.append(progress_data['progress'])
            
            if 'speed' in progress_data:
                update_fields.append('speed = ?')
                update_values.append(progress_data['speed'])
            
            if 'avgSpeed' in progress_data:
                update_fields.append('avg_speed = ?')
                update_values.append(progress_data['avgSpeed'])
            
            if 'estimatedTime' in progress_data:
                update_fields.append('estimated_time = ?')
                update_values.append(progress_data['estimatedTime'])
            
            if 'bytesTransferred' in progress_data:
                update_fields.append('bytes_transferred = ?')
                update_values.append(progress_data['bytesTransferred'])
            
            if not update_fields:
                continue
            
            # 检查记录是否存在
            exists = conn.execute(
                'SELECT 1 FROM p2p_transfer_messages WHERE transfer_id = ?',
                (transfer_id,)
            ).fetchone()
            
            if not exists:
                # 记录不存在，跳过（可能是旧会话）
                continue
            
            # 添加transfer_id到值列表
            update_values.append(transfer_id)
            
            # 执行更新
            sql = f"UPDATE p2p_transfer_messages SET {', '.join(update_fields)} WHERE transfer_id = ?"
            conn.execute(sql, update_values)
            updated_count += 1
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'updatedCount': updated_count
        })
        
    except Exception as e:
        logger.error(f"Error batch updating P2P progress: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/messages', methods=['GET'])
def get_p2p_transfer_history():
    """
    加载P2P传输历史
    
    从数据库加载指定用户和聊天的所有传输消息
    
    查询参数:
    - userId: 用户ID
    - chatId: 聊天ID
    - limit: 限制返回数量（可选，默认100）
    - offset: 偏移量（可选，默认0）
    
    响应:
    {
        "success": true,
        "messages": [
            {
                "id": "msg-123",
                "type": "p2p_transfer",
                "senderId": "user-123",
                "receiverId": "user-456",
                "timestamp": 1234567890,
                "fileInfo": {
                    "name": "document.pdf",
                    "size": 750000000,
                    "type": "application/pdf",
                    "hash": "abc123..."
                },
                "transferInfo": {
                    "id": "transfer-123",
                    "method": "p2p",
                    "status": "completed",
                    "progress": 100,
                    "speed": 0,
                    "avgSpeed": 2100000,
                    "estimatedTime": null,
                    "startTime": 1234567890,
                    "endTime": 1234567900,
                    "bytesTransferred": 750000000,
                    "isValid": true
                }
            }
        ]
    }
    
    """
    try:
        user_id = request.args.get('userId')
        chat_id = request.args.get('chatId')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # 验证必需参数
        if not user_id or not chat_id:
            return jsonify({'success': False, 'error': '缺少必需参数'}), 400
        
        conn = get_db_connection()
        
        # 查询P2P传输消息（从messages表中查询）
        # 对于私聊：to_uid = chat_id 且 from_uid = user_id，或 from_uid = chat_id 且 to_uid = user_id
        # 对于群聊：to_uid = chat_id
        messages = conn.execute('''
            SELECT * FROM messages
            WHERE transfer_method = 'p2p'
            AND (
                (to_uid = ? AND from_uid = ?)
                OR (from_uid = ? AND to_uid = ?)
                OR to_uid = ?
            )
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        ''', (chat_id, user_id, chat_id, user_id, chat_id, limit, offset)).fetchall()
        
        # 格式化消息数据
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                'id': msg['id'],
                'type': 'p2p_transfer',
                'senderId': msg['from_uid'],
                'receiverId': msg['to_uid'],
                'timestamp': msg['timestamp'],
                'fileInfo': {
                    'name': msg['filename'],
                    'size': msg['size'],
                    'type': None,  # messages表中没有存储mime type
                    'hash': msg['file_hash']
                },
                'transferInfo': {
                    'id': msg['p2p_session_id'],
                    'method': 'p2p',
                    'status': msg['p2p_status'] or 'pending',
                    'progress': msg['p2p_progress'] or 0,
                    'speed': msg['p2p_speed'] or 0,
                    'avgSpeed': msg['p2p_avg_speed'] or 0,
                    'estimatedTime': None,
                    'startTime': None,
                    'endTime': None,
                    'bytesTransferred': int((msg['p2p_progress'] or 0) * msg['size'] / 100) if msg['size'] else 0,
                    'isValid': msg['p2p_status'] not in ['expired', 'failed', 'cancelled']
                }
            })
        
        return jsonify({
            'success': True,
            'messages': formatted_messages
        })
        
    except Exception as e:
        logger.error(f"Error loading P2P transfer history: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


# 创建文件和用户状态API接口

@app.route('/api/p2p/file-availability', methods=['POST'])
def check_file_availability():
    """
    检查文件可用性
    
    验证发送方的文件是否仍然可用（未被删除或移动）
    
    请求体:
    {
        "fileHash": "abc123...",
        "senderId": "user-123"
    }
    
    响应:
    {
        "available": true
    }
    
    """
    try:
        req = request.json
        file_hash = req.get('fileHash')
        sender_id = req.get('senderId')
        
        # 验证必需字段
        if not file_hash or not sender_id:
            return jsonify({'available': False, 'error': '缺少必需字段'}), 400
        
        conn = get_db_connection()
        
        # 检查发送方是否在线（通过last_active判断，5分钟内活跃视为在线）
        user = conn.execute(
            'SELECT last_active FROM users WHERE uid = ?',
            (sender_id,)
        ).fetchone()
        
        if not user:
            return jsonify({'available': False, 'reason': 'sender_not_found'})
        
        # 检查用户是否在线（5分钟内有活动）
        current_time = time.time()
        is_online = (current_time - user['last_active']) < 300  # 5分钟
        
        if not is_online:
            return jsonify({'available': False, 'reason': 'sender_offline'})
        
        # 检查文件是否存在于消息记录中（作为文件可用性的代理指标）
        # 注意：这里我们检查是否有该文件哈希的消息记录
        file_message = conn.execute(
            'SELECT id FROM messages WHERE file_hash = ? AND from_uid = ? LIMIT 1',
            (file_hash, sender_id)
        ).fetchone()
        
        # 如果找到文件记录，假设文件可用
        # 在实际实现中，可能需要更复杂的文件系统检查
        available = file_message is not None
        
        return jsonify({
            'available': available,
            'reason': None if available else 'file_not_found'
        })
        
    except Exception as e:
        logger.error(f"Error checking file availability: {e}")
        return jsonify({'available': False, 'error': '服务器内部错误'}), 500


@app.route('/api/users/<user_id>/online-status', methods=['GET'])
def get_user_online_status(user_id):
    """
    检查用户在线状态
    
    根据用户的最后活跃时间判断是否在线
    
    路径参数:
    - user_id: 用户ID
    
    响应:
    {
        "online": true,
        "lastSeen": 1234567890
    }
    
    """
    try:
        conn = get_db_connection()
        
        # 查询用户信息
        user = conn.execute(
            'SELECT last_active FROM users WHERE uid = ?',
            (user_id,)
        ).fetchone()
        
        if not user:
            return jsonify({'online': False, 'lastSeen': None, 'error': '用户不存在'}), 404
        
        # 判断是否在线（5分钟内有活动）
        current_time = time.time()
        last_active = user['last_active'] or 0
        is_online = (current_time - last_active) < 300  # 5分钟
        
        return jsonify({
            'online': is_online,
            'lastSeen': last_active
        })
        
    except Exception as e:
        logger.error(f"Error checking user online status: {e}")
        return jsonify({'online': False, 'error': '服务器内部错误'}), 500


# ================= P2P传输实时同步API（轮询方式） =================
#
# 注意：由于Flask-SocketIO未安装，这里使用长轮询(long-polling)方式实现实时同步
# 客户端通过定期轮询此端点来获取更新

# 全局变量：存储待推送的更新消息
# 结构: {user_id: [update1, update2, ...]}
pending_updates = {}
pending_updates_lock = None


# 性能监控统计
p2p_api_stats = {
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'average_response_time': 0,
    'last_reset': time.time()
}

def record_api_call(endpoint, success, response_time):
    """记录API调用统计"""
    p2p_api_stats['total_requests'] += 1
    if success:
        p2p_api_stats['successful_requests'] += 1
    else:
        p2p_api_stats['failed_requests'] += 1
    
    # 更新平均响应时间
    total = p2p_api_stats['total_requests']
    current_avg = p2p_api_stats['average_response_time']
    p2p_api_stats['average_response_time'] = (current_avg * (total - 1) + response_time) / total

def validate_transfer_message_data(data):
    """验证传输消息数据的完整性"""
    required_fields = ['senderId', 'receiverId', 'chatId', 'fileInfo']
    for field in required_fields:
        if field not in data:
            return False, f'缺少必需字段: {field}'
    
    file_info = data.get('fileInfo', {})
    if not file_info.get('name') or not file_info.get('size'):
        return False, '文件信息不完整'
    
    # 验证文件大小合理性
    if file_info.get('size', 0) <= 0:
        return False, '文件大小无效'
    
    if file_info.get('size', 0) > 100 * 1024 * 1024 * 1024:  # 100GB
        return False, '文件大小超过限制'
    
    return True, None

def sanitize_error_message(error):
    """清理错误消息，避免泄露敏感信息"""
    error_str = str(error)
    # 移除可能的文件路径
    import re
    error_str = re.sub(r'[A-Za-z]:\\[^:]+', '[PATH]', error_str)
    error_str = re.sub(r'/[^:]+/', '[PATH]/', error_str)
    return error_str

def init_pending_updates_lock():
    """初始化线程锁"""
    global pending_updates_lock
    if pending_updates_lock is None:
        import threading
        pending_updates_lock = threading.Lock()

def add_pending_update(user_id, update_data):
    """添加待推送的更新到队列"""
    init_pending_updates_lock()
    with pending_updates_lock:
        if user_id not in pending_updates:
            pending_updates[user_id] = []
        pending_updates[user_id].append(update_data)
        
        # 限制队列大小，防止内存溢出
        if len(pending_updates[user_id]) > 100:
            pending_updates[user_id] = pending_updates[user_id][-100:]

def get_pending_updates(user_id):
    """获取并清空用户的待推送更新"""
    init_pending_updates_lock()
    with pending_updates_lock:
        updates = pending_updates.get(user_id, [])
        if user_id in pending_updates:
            pending_updates[user_id] = []
        return updates


@app.route('/api/p2p/updates', methods=['GET'])
def get_p2p_updates():
    """
    获取P2P传输更新（长轮询）
    
    客户端通过此端点获取实时更新，包括状态更新、进度更新、有效性更新等
    
    查询参数:
    - userId: 用户ID
    - timeout: 超时时间（秒，可选，默认30秒）
    
    响应:
    {
        "updates": [
            {
                "type": "status_update",
                "transferId": "transfer-123",
                "payload": {
                    "status": "accepted",
                    "timestamp": 1234567890
                }
            },
            {
                "type": "progress_update",
                "transferId": "transfer-123",
                "payload": {
                    "progress": 45,
                    "speed": 2400000,
                    "avgSpeed": 2100000,
                    "estimatedTime": 180
                }
            }
        ]
    }
    
    """
    try:
        user_id = request.args.get('userId')
        timeout = request.args.get('timeout', 30, type=int)
        
        if not user_id:
            return jsonify({'error': '缺少用户ID'}), 400
        
        # 限制超时时间
        timeout = min(timeout, 60)  # 最多60秒
        
        # 长轮询：等待更新或超时
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            updates = get_pending_updates(user_id)
            if updates:
                return jsonify({'updates': updates})
            
            # 短暂休眠，避免CPU占用过高
            time.sleep(0.5)
        
        # 超时，返回空更新列表
        return jsonify({'updates': []})
        
    except Exception as e:
        logger.error(f"Error getting P2P updates: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


@app.route('/api/p2p/broadcast', methods=['POST'])
def broadcast_p2p_update():
    """
    广播P2P传输更新
    
    服务器内部使用，用于向指定用户推送更新消息
    
    请求体:
    {
        "userId": "user-123",
        "updateType": "status_update",
        "transferId": "transfer-123",
        "payload": {
            "status": "accepted",
            "timestamp": 1234567890
        }
    }
    
    响应:
    {
        "success": true
    }
    
    """
    try:
        req = request.json
        user_id = req.get('userId')
        update_type = req.get('updateType')
        transfer_id = req.get('transferId')
        payload = req.get('payload', {})
        
        if not user_id or not update_type:
            return jsonify({'success': False, 'error': '缺少必需字段'}), 400
        
        # 构建更新消息
        update_data = {
            'type': update_type,
            'transferId': transfer_id,
            'payload': payload,
            'timestamp': time.time()
        }
        
        # 添加到待推送队列
        add_pending_update(user_id, update_data)
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error broadcasting P2P update: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/subscribe', methods=['POST'])
def subscribe_p2p_updates():
    """
    订阅P2P传输更新
    
    客户端订阅特定传输的更新通知
    
    请求体:
    {
        "userId": "user-123",
        "transferId": "transfer-123"
    }
    
    响应:
    {
        "success": true
    }
    
    """
    try:
        req = request.json
        user_id = req.get('userId')
        transfer_id = req.get('transferId')
        
        if not user_id or not transfer_id:
            return jsonify({'success': False, 'error': '缺少必需字段'}), 400
        
        # 在实际实现中，这里可以维护订阅列表
        # 目前简化实现，直接返回成功
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error subscribing to P2P updates: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/unsubscribe', methods=['POST'])
def unsubscribe_p2p_updates():
    """
    取消订阅P2P传输更新
    
    客户端取消订阅特定传输的更新通知
    
    请求体:
    {
        "userId": "user-123",
        "transferId": "transfer-123"
    }
    
    响应:
    {
        "success": true
    }
    
    """
    try:
        req = request.json
        user_id = req.get('userId')
        transfer_id = req.get('transferId')
        
        if not user_id or not transfer_id:
            return jsonify({'success': False, 'error': '缺少必需字段'}), 400
        
        # 在实际实现中，这里可以从订阅列表中移除
        # 目前简化实现，直接返回成功
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error unsubscribing from P2P updates: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/heartbeat', methods=['POST'])
def p2p_heartbeat():
    """
    P2P传输心跳
    
    客户端定期发送心跳以保持连接活跃
    
    请求体:
    {
        "userId": "user-123"
    }
    
    响应:
    {
        "success": true,
        "timestamp": 1234567890
    }
    
    """
    try:
        req = request.json
        user_id = req.get('userId')
        
        if not user_id:
            return jsonify({'success': False, 'error': '缺少用户ID'}), 400
        
        # 更新用户的最后活跃时间
        conn = get_db_connection()
        conn.execute(
            'UPDATE users SET last_active = ? WHERE uid = ?',
            (time.time(), user_id)
        )
        conn.commit()
        
        return jsonify({
            'success': True,
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Error processing P2P heartbeat: {e}")
        return jsonify({'success': False, 'error': '服务器内部错误'}), 500


@app.route('/api/p2p/stats', methods=['GET'])
def get_p2p_api_stats():
    """
    获取P2P API统计信息
    
    返回API调用统计和性能指标
    
    响应:
    {
        "totalRequests": 1000,
        "successfulRequests": 950,
        "failedRequests": 50,
        "averageResponseTime": 0.15,
        "uptime": 3600,
        "activeTransfers": 5
    }
    
    """
    try:
        conn = get_db_connection()
        
        # 统计活跃传输数量
        active_transfers = conn.execute('''
            SELECT COUNT(*) as count FROM p2p_transfer_messages
            WHERE status IN ('pending', 'accepted', 'connecting', 'transferring')
        ''').fetchone()
        
        uptime = time.time() - p2p_api_stats['last_reset']
        
        return jsonify({
            'totalRequests': p2p_api_stats['total_requests'],
            'successfulRequests': p2p_api_stats['successful_requests'],
            'failedRequests': p2p_api_stats['failed_requests'],
            'averageResponseTime': round(p2p_api_stats['average_response_time'], 3),
            'uptime': round(uptime, 0),
            'activeTransfers': active_transfers['count'] if active_transfers else 0
        })
        
    except Exception as e:
        logger.error(f"Error getting P2P API stats: {e}")
        return jsonify({'error': '服务器内部错误'}), 500


# ================= 账户信息合并管理面板 API =================

@app.route('/api/admin/auth', methods=['POST'])
def admin_auth():
    """管理员身份验证 - 生成 session token"""
    password = request.json.get('password')
    if not password:
        return jsonify({'error': '密码不能为空'}), 400

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != ADMIN_PASSWORD_HASH:
        return jsonify({'error': 'Access Denied'}), 403

    # 生成会话 token
    token = create_admin_session()
    return jsonify({'status': 'ok', 'token': token, 'expires_in': ADMIN_SESSION_TIMEOUT})


@app.route('/api/admin/account_panel', methods=['POST'])
def get_account_panel():
    """账户信息合并管理面板 - 验证 token 并获取账户列表"""
    token = request.json.get('token')
    if not validate_admin_session(token):
        return jsonify({'error': 'Session expired or invalid'}), 403

    conn = get_db_connection()

    # 获取所有用户信息（排除已删除的账户）
    accounts = []
    users = conn.execute('SELECT * FROM users WHERE deleted = 0').fetchall()
    for user in users:
        # 格式化注册时间为可读格式
        registered_at = user['registered_at']
        registered_at_formatted = None
        if registered_at:
            try:
                registered_at_formatted = datetime.datetime.fromtimestamp(registered_at).strftime('%Y-%m-%d %H:%M:%S')
            except:
                registered_at_formatted = None
        
        # 获取 unrestricted_access 字段（处理可能不存在的情况）
        try:
            unrestricted_access = bool(user['unrestricted_access'])
        except (KeyError, IndexError):
            unrestricted_access = False
        
        accounts.append({
            'uid': user['uid'],
            'name': user['name'],
            'avatar_bg': user['avatar_bg'] or '#ccc',
            'last_active': user['last_active'] or 0,
            'registered_at': registered_at,
            'registered_at_formatted': registered_at_formatted,
            'unrestricted_access': unrestricted_access
        })

    # 统计每个用户的消息数量
    msg_counts = {}
    for row in conn.execute(
        "SELECT from_uid, COUNT(*) as cnt FROM messages WHERE from_uid != 'system' GROUP BY from_uid"
    ).fetchall():
        msg_counts[row['from_uid']] = row['cnt']

    for acc in accounts:
        acc['msg_count'] = msg_counts.get(acc['uid'], 0)

    return jsonify({'status': 'ok', 'accounts': accounts})


@app.route('/api/admin/delete_account', methods=['POST'])
def delete_account():
    """删除账户 - 仅删除个人资料，保留聊天记录，阻止再次登录"""
    token = request.json.get('token')
    if not validate_admin_session(token):
        return jsonify({'error': 'Session expired or invalid'}), 403

    target_uid = request.json.get('target_uid')
    if not target_uid:
        return jsonify({'error': '请选择要删除的账户'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE uid = ?',
                        (target_uid,)).fetchone()

    if not user:
        return jsonify({'error': '账户不存在'}), 404

    if user['deleted']:
        return jsonify({'error': '该账户已被删除'}), 400

    old_name = user['name']

    # 标记账户为已删除（版本控制：递增 version 确保客户端能通过 /sync 感知删除状态）
    # 保留 registered_at 字段用于历史追踪，不清空该值
    conn.execute(
        '''UPDATE users SET deleted = 1, deleted_at = ?, deleted_name = ?, 
           password = NULL, name = ?, version = version + 1 WHERE uid = ?''',
        (time.time(), old_name, f"[已删除]{old_name}_{target_uid}", target_uid)
    )

    # 从所有群组中移除该用户
    conn.execute('DELETE FROM group_members WHERE uid = ?', (target_uid,))

    # 如果是群主，将群组所有权转移给 system
    conn.execute('UPDATE groups SET owner = ? WHERE owner = ?',
                 ('system', target_uid))

    # 删除该用户的已读标记
    conn.execute('DELETE FROM read_markers WHERE uid = ?', (target_uid,))

    # 删除该用户设置的备注
    conn.execute('DELETE FROM remarks WHERE uid = ?', (target_uid,))

    conn.commit()

    # **安全控制：终止用户所有会话**
    terminate_user_sessions(target_uid)

    return jsonify({
        'status': 'ok',
        'message': f'账户 {old_name} (UID: {target_uid}) 已成功删除，所有会话已终止'
    })


@app.route('/api/admin/merge_accounts', methods=['POST'])
def merge_accounts():
    """合并账户 - 将源账户的所有信息合并到目标账户"""
    token = request.json.get('token')
    if not validate_admin_session(token):
        return jsonify({'error': 'Session expired or invalid'}), 403

    source_uid = request.json.get('source_uid')
    target_uid = request.json.get('target_uid')

    if not source_uid or not target_uid:
        return jsonify({'error': '请选择源账户和目标账户'}), 400

    if source_uid == target_uid:
        return jsonify({'error': '源账户和目标账户不能相同'}), 400

    conn = get_db_connection()

    source_user = conn.execute(
        'SELECT * FROM users WHERE uid = ?', (source_uid,)).fetchone()
    target_user = conn.execute(
        'SELECT * FROM users WHERE uid = ?', (target_uid,)).fetchone()

    if not source_user:
        return jsonify({'error': '源账户不存在'}), 404
    if not target_user:
        return jsonify({'error': '目标账户不存在'}), 404

    if source_user['deleted']:
        return jsonify({'error': '源账户已被删除，无法合并'}), 400
    if target_user['deleted']:
        return jsonify({'error': '目标账户已被删除，无法作为合并目标'}), 400

    source_name = source_user['name']
    target_name = target_user['name']

    # 1. 将所有消息的 from_uid 从源账户改为目标账户
    result = conn.execute(
        'UPDATE messages SET from_uid = ? WHERE from_uid = ?',
        (target_uid, source_uid)
    )
    merged_msg_count = result.rowcount

    # 同时处理私聊消息的 to_uid
    conn.execute(
        'UPDATE messages SET to_uid = ? WHERE to_uid = ?',
        (target_uid, source_uid)
    )

    # 2. 将源账户加入的群组成员身份转移给目标账户
    # 先获取源账户所在的群组
    source_groups = conn.execute(
        'SELECT group_id FROM group_members WHERE uid = ?', (source_uid,)
    ).fetchall()

    for row in source_groups:
        gid = row['group_id']
        # 检查目标账户是否已在群中
        exists = conn.execute(
            'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
            (gid, target_uid)
        ).fetchone()
        if not exists:
            conn.execute(
                'INSERT INTO group_members (group_id, uid) VALUES (?, ?)',
                (gid, target_uid)
            )

    # 删除源账户的群组成员记录
    conn.execute('DELETE FROM group_members WHERE uid = ?', (source_uid,))

    # 如果源账户是群主，转移给目标账户
    conn.execute(
        'UPDATE groups SET owner = ? WHERE owner = ?',
        (target_uid, source_uid)
    )

    # 3. 合并已读标记
    source_markers = conn.execute(
        'SELECT chat_id, msg_id FROM read_markers WHERE uid = ?', (source_uid,)
    ).fetchall()

    for marker in source_markers:
        chat_id = marker['chat_id']
        msg_id = marker['msg_id']
        # 检查目标账户是否有该标记
        target_marker = conn.execute(
            'SELECT msg_id FROM read_markers WHERE uid = ? AND chat_id = ?',
            (target_uid, chat_id)
        ).fetchone()
        if not target_marker or msg_id > target_marker['msg_id']:
            conn.execute(
                'INSERT OR REPLACE INTO read_markers (uid, chat_id, msg_id) VALUES (?, ?, ?)',
                (target_uid, chat_id, msg_id)
            )

    conn.execute('DELETE FROM read_markers WHERE uid = ?', (source_uid,))

    # 4. 合并备注（目标账户的备注优先）
    source_remarks = conn.execute(
        'SELECT target_uid, remark FROM remarks WHERE uid = ?', (source_uid,)
    ).fetchall()

    for r in source_remarks:
        remarked_uid = r['target_uid']
        remark = r['remark']
        # 仅在目标账户没有备注时才迁移
        exists = conn.execute(
            'SELECT 1 FROM remarks WHERE uid = ? AND target_uid = ?',
            (target_uid, remarked_uid)
        ).fetchone()
        if not exists:
            conn.execute(
                'INSERT INTO remarks (uid, target_uid, remark) VALUES (?, ?, ?)',
                (target_uid, remarked_uid, remark)
            )

    conn.execute('DELETE FROM remarks WHERE uid = ?', (source_uid,))

    # 5. 将其他用户对源账户的备注转移到目标账户
    other_remarks = conn.execute(
        'SELECT uid, remark FROM remarks WHERE target_uid = ?', (source_uid,)
    ).fetchall()

    for r in other_remarks:
        remarker_uid = r['uid']
        remark = r['remark']
        if remarker_uid != target_uid:
            exists = conn.execute(
                'SELECT 1 FROM remarks WHERE uid = ? AND target_uid = ?',
                (remarker_uid, target_uid)
            ).fetchone()
            if not exists:
                conn.execute(
                    'INSERT INTO remarks (uid, target_uid, remark) VALUES (?, ?, ?)',
                    (remarker_uid, target_uid, remark)
                )

    conn.execute('DELETE FROM remarks WHERE target_uid = ?', (source_uid,))

    # 6. 合并注册时间和无限制访问权限
    # 获取两个账户的 registered_at 和 unrestricted_access 值
    source_registered_at = source_user['registered_at']
    target_registered_at = target_user['registered_at']
    # 使用 try-except 处理字段可能不存在的情况
    try:
        source_unrestricted = source_user['unrestricted_access']
    except (KeyError, IndexError):
        source_unrestricted = 0
    try:
        target_unrestricted = target_user['unrestricted_access']
    except (KeyError, IndexError):
        target_unrestricted = 0
    
    # 确定合并后的注册时间（NULL 优先，保留最大权限）
    if source_registered_at is None or target_registered_at is None:
        # 任一为 NULL，结果为 NULL（保留最大权限）
        merged_registered_at = None
    else:
        # 都有值，使用较早的时间
        merged_registered_at = min(source_registered_at, target_registered_at)
    
    # 确定合并后的无限制访问权限（OR 逻辑）
    merged_unrestricted_access = 1 if (source_unrestricted or target_unrestricted) else 0
    
    # 更新目标账户的注册时间和无限制访问权限
    conn.execute(
        '''UPDATE users SET registered_at = ?, unrestricted_access = ?, version = version + 1 
           WHERE uid = ?''',
        (merged_registered_at, merged_unrestricted_access, target_uid)
    )

    # 7. 标记源账户为已合并（禁止登录）（版本控制：递增 version 确保客户端能通过 /sync 感知合并状态）
    # 保留源账户的 registered_at 字段用于历史追踪
    conn.execute(
        '''UPDATE users SET deleted = 1, merged_to = ?, merged_at = ?, 
           password = NULL, name = ?, version = version + 1 WHERE uid = ?''',
        (target_uid, time.time(),
         f"[已合并至{target_name}]{source_name}_{source_uid}", source_uid)
    )

    conn.commit()

    # **安全控制：终止源账户所有会话**
    terminate_user_sessions(source_uid)

    return jsonify({
        'status': 'ok',
        'message': f'账户 {source_name} 已成功合并到 {target_name}，共迁移 {merged_msg_count} 条消息，源账户会话已终止'
    })


@app.route('/api/admin/toggle_unrestricted_access', methods=['POST'])
def toggle_unrestricted_access():
    """管理员切换用户的无限制访问权限"""
    token = request.json.get('token')
    if not validate_admin_session(token):
        return jsonify({'error': 'Session expired or invalid'}), 403

    target_uid = request.json.get('target_uid')
    unrestricted_access = request.json.get('unrestricted_access')

    if not target_uid:
        return jsonify({'error': '请指定目标用户'}), 400
    
    if unrestricted_access is None:
        return jsonify({'error': '请指定 unrestricted_access 参数'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE uid = ?', (target_uid,)).fetchone()

    if not user:
        return jsonify({'error': '用户不存在'}), 404

    # 转换为整数值（0 或 1）
    unrestricted_value = 1 if unrestricted_access else 0

    # 更新用户的 unrestricted_access 字段并递增 version
    conn.execute(
        'UPDATE users SET unrestricted_access = ?, version = version + 1 WHERE uid = ?',
        (unrestricted_value, target_uid)
    )
    conn.commit()

    status_text = "启用" if unrestricted_value else "禁用"
    return jsonify({
        'status': 'ok',
        'uid': target_uid,
        'unrestricted_access': bool(unrestricted_value),
        'message': f'已为用户 {user["name"]} ({target_uid}) {status_text}无限制访问'
    })


@app.route('/api/admin/batch_toggle_unrestricted_access', methods=['POST'])
def batch_toggle_unrestricted_access():
    """管理员批量切换所有用户的无限制访问权限"""
    token = request.json.get('token')
    if not validate_admin_session(token):
        return jsonify({'error': 'Session expired or invalid'}), 403

    enable = request.json.get('enable', True)
    value = 1 if enable else 0

    conn = get_db_connection()
    result = conn.execute(
        'UPDATE users SET unrestricted_access = ?, version = version + 1 WHERE deleted = 0',
        (value,)
    )
    affected_count = result.rowcount
    conn.commit()

    status_text = "启用" if value else "禁用"
    return jsonify({
        'status': 'ok',
        'affected_count': affected_count,
        'message': f'已为 {affected_count} 个用户{status_text}无限制访问'
    })


@app.route('/create_group', methods=['POST'])
def create_group():
    req = request.json
    group_name = req.get('name')
    creator_uid = req.get('uid')
    initial_members = req.get('members', [])
    if not group_name:
        return jsonify({'error': '群名不能为空'}), 400

    conn = get_db_connection()

    if creator_uid not in initial_members:
        initial_members.append(creator_uid)

    group_id = str(uuid.uuid4())[:8]

    # 创建群组
    conn.execute(
        'INSERT INTO groups (id, name, owner, is_system) VALUES (?, ?, ?, ?)',
        (group_id, group_name, creator_uid, 0)
    )

    # 添加群成员
    for member_uid in initial_members:
        conn.execute(
            'INSERT OR IGNORE INTO group_members (group_id, uid) VALUES (?, ?)',
            (group_id, member_uid)
        )

    # 发送系统消息
    content = json.dumps(
        {'sys_type': 'group_create', 'operator_uid': creator_uid, 'group_name': group_name})
    msg_id = get_unique_msg_id()
    conn.execute(
        '''INSERT INTO messages (id, from_uid, to_uid, type, content, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (msg_id, 'system', group_id, 'system', content, time.time())
    )

    conn.commit()
    return jsonify({'status': 'ok', 'group_id': group_id})


@app.route('/group/manage', methods=['POST'])
def manage_group():
    req = request.json
    action = req.get('action')
    gid = req.get('group_id')
    uid = req.get('uid')

    conn = get_db_connection()

    group = conn.execute(
        'SELECT * FROM groups WHERE id = ?', (gid,)).fetchone()
    if not group:
        return jsonify({'error': '群不存在'}), 404

    if group['is_system']:
        return jsonify({'error': '系统群不可操作'}), 403

    if group['owner'] != uid:
        return jsonify({'error': '只有群主可操作'}), 403

    sys_content = ""

    if action == 'rename':
        new_name = req.get('name')
        # 版本控制：群名变更时递增 version，确保所有成员能通过 /sync 检测到变化
        conn.execute('UPDATE groups SET name = ?, version = version + 1 WHERE id = ?',
                     (new_name, gid))
        sys_content = json.dumps(
            {'sys_type': 'group_rename', 'operator_uid': uid, 'new_name': new_name})

    elif action == 'invite':
        new_ids = req.get('members', [])
        invited_uids = []
        for nid in new_ids:
            # 检查是否已在群中
            exists = conn.execute(
                'SELECT 1 FROM group_members WHERE group_id = ? AND uid = ?',
                (gid, nid)
            ).fetchone()
            if not exists:
                conn.execute(
                    'INSERT INTO group_members (group_id, uid) VALUES (?, ?)',
                    (gid, nid)
                )
                invited_uids.append(nid)
        if invited_uids:
            # 版本控制：成员变动时递增群组 version
            conn.execute(
                'UPDATE groups SET version = version + 1 WHERE id = ?', (gid,))
            sys_content = json.dumps(
                {'sys_type': 'group_invite', 'operator_uid': uid, 'target_uids': invited_uids})

    elif action == 'kick':
        target = req.get('target_uid')
        if target != group['owner']:
            conn.execute(
                'DELETE FROM group_members WHERE group_id = ? AND uid = ?',
                (gid, target)
            )
            # 版本控制：成员被踢时递增群组 version，被踢用户能通过 /sync 检测到自己被移除
            conn.execute(
                'UPDATE groups SET version = version + 1 WHERE id = ?', (gid,))
            sys_content = json.dumps(
                {'sys_type': 'group_kick', 'operator_uid': uid, 'target_uid': target})

    elif action == 'dissolve':
        conn.execute('DELETE FROM group_members WHERE group_id = ?', (gid,))
        conn.execute('DELETE FROM groups WHERE id = ?', (gid,))
        conn.commit()
        return jsonify({'status': 'ok', 'dissolved': True})

    if sys_content:
        msg_id = get_unique_msg_id()
        conn.execute(
            '''INSERT INTO messages (id, from_uid, to_uid, type, content, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (msg_id, 'system', gid, 'system', sys_content, time.time())
        )

    conn.commit()
    return jsonify({'status': 'ok'})


# ================= Frontend =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>LANChat Hub</title>
    <!-- FIX BUG 2: IE Check Script (Modified to be non-blocking) -->
    <script>
    (function(){
        function isIE() { return (!!window.ActiveXObject || "ActiveXObject" in window); }
        if(isIE()){
            window.onload = function() {
                var div = document.createElement('div');
                div.style.cssText = 'position:fixed;top:0;left:0;width:100%;padding:10px;background:#ffcc00;color:black;z-index:99999;text-align:center;border-bottom:1px solid #d4a000;font-family:sans-serif;font-size:14px;';
                div.innerHTML = '⚠️ 检测到您正在使用旧版/IE内核浏览器，为了获得更好的体验，建议切换至 <b>极速模式</b> (Chrome内核) 或更换浏览器。';
                document.body.insertBefore(div, document.body.firstChild);
            };
        }
    })();
    </script>

    <style>
        :root { --bg-app: #f2f2f7; --bg-sidebar: #1e1e1e; --bg-list: rgba(255, 255, 255, 0.85); --bg-chat: #ffffff; --accent: #007aff; --text-main: #000; --text-sub: #8e8e93; --border: rgba(0,0,0,0.1); --font: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", "Segoe UI", "SF Pro Text", "Helvetica Neue", sans-serif; 

        /* VISUAL TOGGLE VARIABLES */
        --glass: none; 
        --shadow: none; 
        --anim-dur: 0s;
        --sh-card: none; 
        --sh-float: none;
        --sh-ctx: none;
        --sh-av: none;
        --sh-bub: none;
        --sh-av-ring: none;
        --sh-badge: none;
        --sh-item-av: none;
        --sh-input-focus: none;
        --sh-modal-av: none;
        --img-render: -webkit-optimize-contrast; 

        --bg-float: rgba(255, 255, 255, 0.95);
        --text-float: #007aff;
        --border-float: rgba(0,0,0,0.05);
        }

        body.visual-on { 
            --glass: blur(10px); 
            --shadow: 0 10px 40px rgba(0,0,0,0.3); 
            --anim-dur: 0.3s; 
            --sh-card: 0 10px 40px rgba(0,0,0,0.2);
            --sh-float: 0 4px 15px rgba(0,0,0,0.1);
            --sh-ctx: 0 10px 30px rgba(0,0,0,0.5);
            --sh-av: 0 4px 10px rgba(0,0,0,0.2);
            --sh-bub: 0 1px 2px rgba(0,0,0,0.05);
            --sh-av-ring: 0 0 0 2px rgba(255,255,255,0.15);
            --sh-badge: 0 2px 5px rgba(255,59,48,0.3);
            --sh-item-av: 0 2px 5px rgba(0,0,0,0.05);
            --sh-input-focus: 0 0 0 2px rgba(0,122,255,0.2);
            --sh-modal-av: 0 5px 20px rgba(0,0,0,0.15);
            --img-render: auto;
        }

        @media (prefers-color-scheme: dark) { 
            :root { 
                --bg-app: #000; --bg-sidebar: #1c1c1e; --bg-list: #2c2c2e; --bg-chat: #1c1c1e; --text-main: #fff; --text-sub: #aeaeb2; --border: rgba(255,255,255,0.1); 
                --bg-float: rgba(50, 50, 50, 0.95);
                --text-float: #0a84ff;
                --border-float: rgba(255,255,255,0.1);
            } 
        }

        * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; outline: none; -webkit-tap-highlight-color: transparent; font-family: var(--font); }

        /* FIX BUG 2: IE Fallbacks */
        body { background: #f2f2f7; background: var(--bg-app); height: 100vh; width: 100vw; overflow: hidden; display: flex; color: var(--text-main); }
        #app { width: 100%; height: 100%; display: flex; background: var(--bg-chat); opacity: 0; transition: opacity 0.5s; }

        * { scrollbar-width: thin; scrollbar-color: rgba(128, 128, 128, 0.3) transparent; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(128, 128, 128, 0.3); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(128, 128, 128, 0.5); }

        @keyframes flyInRight { from { opacity: 0; transform: translateX(20px) scale(0.9); } to { opacity: 1; transform: translateX(0) scale(1); } }
        @keyframes flyInLeft { from { opacity: 0; transform: translateX(-20px) scale(0.9); } to { opacity: 1; transform: translateX(0) scale(1); } }
        @keyframes jellyPop { 0% { transform: scale(0.9); opacity: 0; } 50% { transform: scale(1.05); } 100% { transform: scale(1); opacity: 1; } }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
        @keyframes flash { 0%{background:rgba(0,122,255,0.2);} 100%{background:transparent;} }

        .clickable { cursor: pointer; transition: transform 0.1s cubic-bezier(0.175, 0.885, 0.32, 1.275), background var(--anim-dur); }
        .clickable:active { transform: scale(0.94); }

        /* FIX BUG 2: IE Fallbacks */
        .sidebar { background: #1e1e1e; background: var(--bg-sidebar); width: 68px; display: flex; flex-direction: column; align-items: center; padding-top: 30px; flex-shrink: 0; z-index: 10; }
        .avatar-box { width: 44px; height: 44px; border-radius: 14px; margin-bottom: 30px; transition: transform 0.5s; box-shadow: var(--sh-av-ring), var(--sh-av); }
        .avatar-box.spin { animation: spin 0.5s ease-out; }
        .nav-btn { width: 40px; height: 40px; border-radius: 10px; margin-bottom: 15px; display: flex; justify-content: center; align-items: center; fill: #888; }
        .nav-btn:hover { background: rgba(255,255,255,0.1); }
        .nav-btn.active { fill: #007aff; fill: var(--accent); background: rgba(0, 122, 255, 0.15); }

        /* FIX BUG 2: IE Fallbacks */
        .list-pane { background: #fff; background: var(--bg-list); width: 260px; border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; backdrop-filter: var(--glass); }
        .search-header { height: 60px; padding: 0 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); flex-shrink: 0; }
        .search-title { font-size: 18px; font-weight: 700; letter-spacing: -0.5px; }
        .btn-circle { width: 28px; height: 28px; border-radius: 50%; background: rgba(128,128,128,0.1); display: flex; justify-content: center; align-items: center; color: var(--accent); }
        .list-content { flex: 1; overflow-y: auto; padding: 10px; }
        .list-item { display: flex; align-items: center; padding: 12px; border-radius: 12px; margin-bottom: 4px; position: relative; transition: background var(--anim-dur); }
        .list-item:hover { background: rgba(128,128,128,0.08); }
        .list-item.active { background: rgba(128,128,128,0.15); }
        .list-item.pinned { background: rgba(128,128,128,0.05); border-left: 3px solid var(--accent); }
        .item-av { width: 42px; height: 42px; border-radius: 14px; margin-right: 12px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; font-size: 16px; text-shadow: 0 1px 2px rgba(0,0,0,0.1); box-shadow: var(--sh-item-av); }
        .item-body { flex: 1; min-width: 0; }
        .item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px; }
        .item-t { font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .item-time { font-size: 11px; color: var(--text-sub); margin-left: 5px; flex-shrink: 0; }
        .item-btm { display: flex; justify-content: space-between; align-items: center; }
        .item-d { font-size: 13px; color: var(--text-sub); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
        .unread-badge { background: #ff3b30; color: white; border-radius: 10px; padding: 0 6px; font-size: 10px; height: 16px; line-height: 16px; min-width: 16px; text-align: center; margin-left: 5px; font-weight: 600; box-shadow: var(--sh-badge); }

        /* FIX BUG 2: IE Fallbacks */
        .chat-pane { background: #fff; background: var(--bg-chat); flex: 1; display: flex; flex-direction: column; position: relative; min-width: 0; }
        .chat-top { height: 60px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; padding: 0 20px; background: rgba(255,255,255,0.8); backdrop-filter: var(--glass); z-index: 5; }
        @media (prefers-color-scheme: dark) { .chat-top { background: rgba(28,28,30,0.8); } }
        .chat-name { font-size: 16px; font-weight: 600; }
        .chat-stat { font-size: 12px; color: var(--text-sub); display: flex; align-items: center; }
        .chat-stat > *:not(:last-child) { margin-right: 5px; }

        .dot { width: 8px; height: 8px; background: #30d158; border-radius: 50%; }
        .mobile-back { 
            display: none; 
            font-size: 24px; 
            color: var(--accent); 
            margin-right: 8px; 
            cursor: pointer; 
            font-weight: 300;
            line-height: 1; /* 确保行高不影响垂直对齐 */
            display: flex; /* 使用flex确保内容居中 */
            align-items: center; /* 垂直居中 */
            justify-content: center; /* 水平居中 */
        }
        
        /* 移动端未读消息气泡 - 优化位置和显示逼辑 */
        .mobile-unread-badge {
            display: none; /* 默认完全隐藏 */
            width: 26px;
            height: 26px;
            background: rgba(142, 142, 147, 0.9);
            border-radius: 50%;
            align-items: center;
            justify-content: center;
            margin-right: 12px;
            font-size: 11px;
            font-weight: 700;
            color: white;
            box-shadow: 0 2px 6px rgba(0,0,0,0.12);
            flex-shrink: 0;
            /* 过渡动画 */
            opacity: 0;
            transform: scale(0.7);
            transition: opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1), 
                        transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            /* 确保垂直居中 - 关键修正 */
            align-self: center; /* 在flex容器中强制垂直居中 */
        }
        @media (prefers-color-scheme: dark) {
            .mobile-unread-badge {
                background: rgba(99, 99, 102, 0.9);
                box-shadow: 0 2px 6px rgba(0,0,0,0.25);
            }
        }
        /* 显示状态：仅在移动端且有未读时显示 */
        .mobile-unread-badge.show {
            display: flex;
            opacity: 1;
            transform: scale(1);
        }
        .btn-icon { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 8px; font-size: 18px; }
        .btn-icon:hover { background: rgba(128,128,128,0.1); }

        .msg-area { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 20px; display: flex; flex-direction: column; }
        /* 防止初始渲染时出现从顶部到底部的滚动效果 */
        .msg-area:empty { overflow: hidden; }
        /* 优化滚动性能和稳定性 */
        .msg-area { will-change: scroll-position; }
        /* FIX BUG 1: Chrome 60 Flex Squeeze Fix */
        .msg-row { display: flex; max-width: 80%; opacity: 0; align-items: flex-start; border-radius:8px; transition: background var(--anim-dur); margin-bottom: 10px; min-width: 0; }
        .msg-row.highlight { animation: flash 1s; }
        .msg-row.anim-in-right { animation: flyInRight 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }
        .msg-row.anim-in-left { animation: flyInLeft 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }
        .msg-row:not(.anim-in-right):not(.anim-in-left) { opacity: 1; }
        .msg-row.me { align-self: flex-end; flex-direction: row-reverse; }

        .msg-row.sys { align-self: center; max-width: 100%; width: 100%; justify-content: center; }
        .msg-row.sys .msg-av { display: none !important; } 
        .msg-row.sys .msg-bub { background: transparent; color: var(--text-sub); font-size: 12px; padding: 2px 8px; box-shadow: none; text-align: center; margin: 0 auto; }
        .msg-row.sys .msg-name { display: none !important; }

        .msg-av { width: 34px; height: 34px; border-radius: 12px; flex-shrink: 0; }
        /* FIX BUG 1: Chrome 60 Wrapper for message content to allow shrinking/growing */
        .msg-content-wrapper { flex: 1; min-width: 0; display: block; }

        /* FIX BUG 1: Force word break to prevent layout squeeze in Chrome 69 */
        .msg-bub { padding: 9px 14px; border-radius: 14px; font-size: 14px; line-height: 1.45; word-break: break-all; overflow-wrap: break-word; white-space: pre-wrap; background: #e9e9eb; color: black; transition: all var(--anim-dur); box-shadow: var(--sh-bub); max-width: 100%; }
        .msg-bub.transparent-bub { background: transparent !important; box-shadow: none !important; padding: 0 !important; }

        @media (prefers-color-scheme: dark) { .msg-bub { background: #3a3a3c; color: white; } }
        .msg-row.me .msg-bub { background: #007aff; background: var(--accent); color: white; border-bottom-right-radius: 4px; }
        .msg-row:not(.me) .msg-bub { border-bottom-left-radius: 4px; }

        .msg-name { font-size: 11px; color: var(--text-sub); margin-bottom: 2px; }
        .msg-row.me .msg-name { text-align: right; }
        .file-card { display: flex; align-items: center; }
        .file-card > :first-child { margin-right: 10px; }

        .chat-img { max-width: 240px; max-height: 240px; border-radius: 12px; cursor: zoom-in; display: block; margin: 0; transition: opacity 0.2s; border: 1px solid rgba(0,0,0,0.1); image-rendering: var(--img-render); }

        .read-stat { font-size: 10px; color: #999; margin: 0 5px; white-space:nowrap; display:none; align-self: flex-end; margin-bottom: 5px; }
        .read-stat.read { color: #30d158; }
        .msg-row.me .read-stat { display: block; }

        .quote-box { background: rgba(0,0,0,0.05); border-radius: 8px; padding: 8px; margin-bottom: 6px; font-size: 13px; border-left: 3px solid #bbb; display: flex; flex-direction: column; max-width: 100%; max-height: 80px; box-sizing: border-box; overflow: hidden; cursor:pointer; }
        @media (prefers-color-scheme: dark) { .quote-box { background: rgba(255,255,255,0.1); border-left-color: #666; } }
        .q-name { font-weight: 600; font-size: 12px; opacity: 0.7; margin-bottom: 2px; flex-shrink: 0; }
        .q-txt { opacity: 0.8; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: break-all; line-height: 1.4; max-width: 100%; }

        .fwd-card { width: 240px; background: white; color: black; border-radius: 12px; overflow: hidden; cursor: pointer; border: 1px solid rgba(0,0,0,0.1); }
        @media (prefers-color-scheme: dark) { .fwd-card { background: #444; color: white; border: 1px solid rgba(255,255,255,0.1); } }
        .fwd-head { padding: 10px 12px; font-size: 14px; font-weight: 600; border-bottom: 1px solid rgba(0,0,0,0.05); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .fwd-body { padding: 10px 12px; font-size: 12px; color: #888; display: flex; flex-direction: column; }
        .fwd-row { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
        .fwd-row:last-child { margin-bottom: 0; }
        .fwd-foot { padding: 8px 12px; border-top: 1px solid rgba(0,0,0,0.05); font-size: 10px; color: #aaa; }

        .chat-time { width: 100%; text-align: center; font-size: 11px; color: #aaa; margin: 15px 0 5px 0; }
        
        /* P2P传输消息样式 */
        .p2p-transfer-message { background: #f8f9fa !important; color: #333 !important; padding: 12px !important; min-width: 280px; }
        @media (prefers-color-scheme: dark) { .p2p-transfer-message { background: #2a2a2c !important; color: #e0e0e0 !important; } }
        .msg-row.me .p2p-transfer-message { background: #e3f2fd !important; }
        @media (prefers-color-scheme: dark) { .msg-row.me .p2p-transfer-message { background: #1a3a52 !important; } }
        
        .p2p-file-info { display: flex; align-items: center; margin-bottom: 10px; }
        .p2p-file-icon { font-size: 32px; margin-right: 12px; }
        .p2p-file-details { flex: 1; }
        .p2p-file-name { font-weight: 600; font-size: 14px; margin-bottom: 4px; word-break: break-all; }
        .p2p-file-size { font-size: 12px; color: #666; margin-bottom: 2px; }
        @media (prefers-color-scheme: dark) { .p2p-file-size { color: #999; } }
        .p2p-method { font-size: 11px; color: #007aff; font-weight: 500; }
        
        .p2p-status { font-size: 13px; color: #666; margin-bottom: 8px; }
        @media (prefers-color-scheme: dark) { .p2p-status { color: #999; } }
        .p2p-status.success { color: #28a745; }
        .p2p-status.error { color: #dc3545; }
        
        .p2p-progress-container { margin-bottom: 10px; }
        .p2p-progress-bar { width: 100%; height: 6px; background: rgba(0,0,0,0.1); border-radius: 3px; overflow: hidden; margin-bottom: 6px; }
        @media (prefers-color-scheme: dark) { .p2p-progress-bar { background: rgba(255,255,255,0.1); } }
        .p2p-progress-fill { height: 100%; background: #007aff; transition: width 0.3s ease; }
        .p2p-progress-info { display: flex; justify-content: space-between; font-size: 12px; color: #666; }
        @media (prefers-color-scheme: dark) { .p2p-progress-info { color: #999; } }
        
        .p2p-actions { display: flex; gap: 8px; margin-top: 10px; }
        .p2p-btn { padding: 6px 16px; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; transition: all 0.2s; font-weight: 500; }
        .p2p-btn:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
        .p2p-btn.accept-btn { background: #28a745; color: white; }
        .p2p-btn.accept-btn:hover { background: #218838; }
        .p2p-btn.reject-btn { background: #6c757d; color: white; }
        .p2p-btn.reject-btn:hover { background: #5a6268; }
        .p2p-btn.cancel-btn { background: #dc3545; color: white; }
        .p2p-btn.cancel-btn:hover { background: #c82333; }
        .p2p-btn.download-btn { background: #007aff; color: white; }
        .p2p-btn.download-btn:hover { background: #0056b3; }

        /* 懒加载指示器样式 */
        #load-more-indicator {
            padding: 10px 20px;
            background: rgba(128,128,128,0.05);
            border-radius: 12px;
            margin: 10px auto;
            display: inline-block;
            transition: all 0.2s;
        }
        #load-more-indicator:hover {
            background: rgba(128,128,128,0.1);
        }
        
        /* 历史消息加载指示器 */
        .history-loading-spinner {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #999;
            font-size: 14px;
        }
        
        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid #f3f3f3;
            border-top: 2px solid #007aff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }

        /* FIX BUG 2: IE Fallbacks */
        .chat-bottom { padding: 15px 20px; border-top: 1px solid var(--border); background: #fff; background: var(--bg-chat); transition: transform var(--anim-dur); position: relative; }
        .reply-bar { position: absolute; bottom: 100%; left: 0; width: 100%; max-width: 100%; max-height: 60px; box-sizing: border-box; background: rgba(240,240,240,0.95); backdrop-filter: var(--glass); padding: 8px 15px; display: none; align-items: flex-start; justify-content: space-between; font-size: 13px; border-top: 1px solid var(--border); color: #666; overflow: hidden; }
        @media (prefers-color-scheme: dark) { .reply-bar { background: rgba(40,40,40,0.95); color: #aaa; } }
        .reply-content { flex: 1; min-width: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: break-all; line-height: 1.4; margin-right: 10px; }
        .reply-close { cursor: pointer; font-size: 18px; padding: 0 5px; flex-shrink: 0; align-self: flex-start; margin-top: 2px; }

        .input-wrap { display: flex; align-items: flex-end; background: rgba(128,128,128,0.1); border-radius: 20px; padding: 6px 12px; transition: background 0.2s; position: relative; }
        .input-wrap:focus-within { background: rgba(128,128,128,0.15); box-shadow: var(--sh-input-focus); }
        .inp-txt { flex: 1; background: transparent; border: none; padding: 8px; font-size: 15px; max-height: 100px; resize: none; color: var(--text-main); }
        .btn-send { background: var(--accent); color: white; border: none; border-radius: 16px; padding: 6px 14px; font-size: 14px; font-weight: 600; margin-bottom: 4px; margin-left: 6px; }

        .sticker-panel { position: absolute; bottom: 65px; left: 20px; width: min(350px, calc(100vw - 40px)); background: var(--bg-list); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--sh-card); backdrop-filter: var(--glass); display: none; flex-direction: column; z-index: 50; overflow: hidden; }
        .sticker-tabs-container { position: relative; flex-shrink: 0; }
        .sticker-tabs { display: flex; justify-content: flex-start; padding: 8px 5px; border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.02); overflow-x: auto; scrollbar-width: none; /* Firefox */ -ms-overflow-style: none; /* IE */ -webkit-overflow-scrolling: touch; }
        .sticker-tabs::-webkit-scrollbar { display: none; /* Chrome, Safari, Opera */ }
        .sticker-tab { font-size: 24px; cursor: pointer; padding: 5px 10px; border-radius: 8px; transition: all 0.1s ease; opacity: 0.6; user-select: none; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
        .sticker-tab:hover { opacity: 1; background: rgba(128,128,128,0.1); }
        .sticker-tab.active { opacity: 1; background: var(--accent); color: white; }
        .sticker-tabs-scrollbar { position: absolute; bottom: 0; left: 0; right: 0; height: 3px; background: rgba(128,128,128,0.3); border-radius: 2px; z-index: 10; transition: opacity 0.1s ease; }
        .sticker-tabs-scrollbar-thumb { position: absolute; height: 100%; background: var(--accent); border-radius: 2px; transition: all 0.1s ease; }
        .emoji-img-category { width: 24px; height: 24px; object-fit: contain; }

        .sticker-content { display: grid; grid-template-columns: repeat(5, 1fr); gap: 5px; padding: 10px; max-height: 250px; overflow-y: auto; flex: 1; }
        .sticker-pagination { display: flex; justify-content: center; align-items: center; padding: 8px; border-top: 1px solid var(--border); background: rgba(0,0,0,0.02); gap: 15px; flex-shrink: 0; }
        .sticker-page-btn { background: var(--accent); color: white; border: none; border-radius: 6px; padding: 4px 12px; font-size: 14px; cursor: pointer; transition: all 0.2s; }
        .sticker-page-btn:hover:not(:disabled) { opacity: 0.8; transform: scale(1.05); }
        .sticker-page-btn:disabled { opacity: 0.3; cursor: not-allowed; }
        .sticker-page-info { font-size: 12px; color: var(--text-sub); min-width: 40px; text-align: center; }
        .sticker-item { font-size: 28px; cursor: pointer; text-align: center; padding: 5px; border-radius: 8px; transition: background var(--anim-dur); user-select: none; display: flex; align-items: center; justify-content: center; aspect-ratio: 1; }
        .sticker-item:hover { background: rgba(128,128,128,0.15); transform: scale(1.1); }
        .sticker-item img.emoji-img { width: 28px; height: 28px; }
        .sticker-gif { width: 100%; height: 100%; object-fit: contain; opacity: 0; transition: opacity 0.3s; transform: translateZ(0); }
        .sticker-gif.loaded { opacity: 1; }
        .sticker-gif:not(.loaded) { background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%); background-size: 200% 100%; animation: loading 1.5s infinite; }
        @keyframes loading { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        @media (prefers-color-scheme: dark) { 
            .sticker-gif:not(.loaded) { 
                background: linear-gradient(90deg, #2a2a2a 25%, #1a1a1a 50%, #2a2a2a 75%); 
                background-size: 200% 100%; 
            } 
            /* mix-blend-mode 已移除，以提升 WebP 动画播放性能 */
        }
        .msg-sticker { font-size: 50px; line-height: 1; user-select: none; cursor: default; transition: transform 0.2s; }
        .msg-sticker:hover { transform: scale(1.1); }
        .emoji-img { display: inline-block; width: 1.2em; height: 1.2em; vertical-align: -0.2em; object-fit: contain; }

        .lightbox { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.9); z-index: 200; justify-content: center; align-items: center; opacity: 0; transition: opacity 0.2s; }
        .lightbox.active { display: flex; opacity: 1; }
        .lightbox img { max-width: 90%; max-height: 90%; transition: transform 0.1s cubic-bezier(0.25, 0.46, 0.45, 0.94); cursor: grab; }
        .lightbox-close { position: absolute; top: 20px; right: 20px; color: white; font-size: 30px; cursor: pointer; z-index: 201; }

        .modal-bg { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 300; justify-content: center; align-items: center; backdrop-filter: var(--glass); transition: opacity var(--anim-dur); }
        .modal-box { background: #fff; background: var(--bg-list); width: 320px; border-radius: 24px; padding: 30px; box-shadow: var(--shadow); display: flex; flex-direction: column; max-height: 80vh; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); }
        body.visual-on .modal-box { animation: jellyPop 0.4s ease-out; }
        .modal-h { font-size: 20px; font-weight: 700; margin-bottom: 20px; text-align: center; letter-spacing: -0.5px; flex-shrink: 0; }
        .modal-inp { width: 100%; padding: 14px; border-radius: 14px; border: 1px solid var(--border); background: rgba(128,128,128,0.1); color: var(--text-main); margin-bottom: 15px; transition: all 0.2s; font-size: 15px; flex-shrink: 0; }
        .btn-block { width: 100%; padding: 14px; border-radius: 14px; background: var(--accent); color: white; border: none; font-weight: 600; margin-bottom: 10px; font-size: 16px; flex-shrink: 0; }
        .empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-sub); font-size: 14px; }

        .toast { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.8); color: white; padding: 10px 20px; border-radius: 20px; font-size: 14px; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 2000; }
        .toast.show { opacity: 1; }

        .setting-section { margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 10px; flex-shrink: 0; }
        .setting-label { font-size: 13px; color: var(--text-sub); margin-bottom: 6px; display:flex; justify-content:space-between; align-items: center; }
        .toggle-switch { width: 36px; height: 20px; background: #ccc; border-radius: 10px; position: relative; cursor: pointer; transition: background 0.2s; }
        .toggle-switch.on { background: #30d158; }
        .toggle-switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; background: white; border-radius: 50%; transition: transform 0.2s; }
        .toggle-switch.on::after { transform: translateX(16px); }
        .user-row { display:flex; align-items:center; padding:8px; border-radius:8px; margin-bottom:4px; }
        .user-row:hover { background:rgba(128,128,128,0.1); }
        .user-row.sel .chk { display:block; }
        #dev-logs-content { flex:1; overflow-y:auto; font-family: monospace; font-size:12px; color:#33d17a; background:#1e1e1e; padding:10px; border-radius:8px; margin-bottom:10px; max-height: 60vh; }
        .log-entry { margin-bottom:5px; border-bottom:1px solid #333; padding-bottom:2px; }
        .log-file-link { color: #4facfe; text-decoration: underline; cursor: pointer; }
        #upload-panel { display: none; position: fixed; bottom: 20px; right: 20px; width: 300px; background: var(--bg-list); border-radius: 16px; box-shadow: var(--sh-card); z-index: 150; border: 1px solid var(--border); backdrop-filter: var(--glass); overflow: hidden; flex-direction: column; }
        .up-header { padding: 12px 15px; background: rgba(0,0,0,0.05); font-size: 13px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); cursor: move; user-select: none; }
        .up-list { max-height: 200px; overflow-y: auto; padding: 5px; }
        .up-item { display: flex; flex-direction: column; padding: 10px; font-size: 12px; border-bottom: 1px solid rgba(0,0,0,0.05); }
        .up-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; font-weight: 500; }
        .up-info { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 11px; }
        .up-size { color: var(--text-sub); }
        .up-method { padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
        .method-p2p { background: rgba(48, 209, 88, 0.15); color: #30d158; }
        .method-server { background: rgba(0, 122, 255, 0.15); color: #007aff; }
        .method-error { background: rgba(255, 59, 48, 0.15); color: #ff3b30; }
        .up-progress { width: 100%; height: 4px; background: rgba(0,0,0,0.1); border-radius: 2px; overflow: hidden; margin-bottom: 4px; }
        .up-bar { height: 100%; background: #30d158; width: 0%; transition: width 0.2s; }
        .up-status { width: 16px; text-align: center; position: absolute; right: 10px; top: 10px; }
        .mobile-nav { display: none; position: fixed; bottom: 0; left: 0; width: 100%; height: 50px; background: var(--bg-list); border-top: 1px solid var(--border); z-index: 50; justify-content: space-around; align-items: center; backdrop-filter: var(--glass); }
        .m-nav-item { flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; color: var(--text-sub); font-size: 10px; cursor: pointer; }
        .m-nav-item.active { color: var(--accent); }
        .m-nav-item svg { width: 24px; height: 24px; margin-bottom: 2px; fill: currentColor; }

        .msg-inner { display: flex; max-width: 100%; align-items: flex-start; }
        .msg-inner > .msg-av { margin-right: 10px; }

        .msg-row.me .msg-inner { flex-direction: row-reverse; }
        .msg-row.me .msg-inner > .msg-av { margin-right: 0; margin-left: 10px; }

        .msg-chk { width: 24px; height: 24px; border-radius: 50%; border: 2px solid #888; margin-top: 6px; flex-shrink: 0; display: none; align-items: center; justify-content: center; cursor: pointer; margin-right: 10px; transition: all 0.2s; }
        .msg-row.me .msg-chk { margin-right: 0; margin-left: 10px; }
        .msg-chk.checked { background: var(--accent); border-color: var(--accent); }
        .msg-chk::after { content: '✓'; color: white; font-size: 14px; display: none; }
        .msg-chk.checked::after { display: block; }
        body.multi-mode .msg-chk { display: flex; }
        body.multi-mode .chat-bottom { transform: translateY(100%); position: absolute; bottom:0; width:100%; }
        body.multi-mode .msg-row { cursor: pointer; }

        .ctx-menu { position: fixed; background: rgba(40,40,42,0.95); backdrop-filter: var(--glass); border-radius: 12px; padding: 6px; width: 140px; display: none; z-index: 1000; box-shadow: var(--sh-ctx); border: 1px solid rgba(255,255,255,0.1); flex-direction: column; animation: jellyPop var(--anim-dur) ease-out; }
        .ctx-item { padding: 10px 12px; color: white; font-size: 14px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; transition: background 0.1s; }
        .ctx-item:hover { background: var(--accent); }
        .ctx-icon { width: 18px; height: 18px; fill: currentColor; opacity: 0.8; margin-right: 10px; }
        .ctx-line { height: 1px; background: rgba(255,255,255,0.15); margin: 4px 8px; }

        .multi-bar { position: absolute; bottom: 0; left: 0; width: 100%; height: 60px; background: #2c2c2e; display: none; align-items: center; justify-content: space-around; z-index: 100; border-top: 1px solid rgba(255,255,255,0.1); animation: slideUp var(--anim-dur) cubic-bezier(0.175, 0.885, 0.32, 1.275); }
        body.multi-mode .multi-bar { display: flex; }
        .m-btn { display: flex; flex-direction: column; align-items: center; justify-content: center; color: white; font-size: 10px; opacity: 0.8; cursor: pointer; width: 60px; }
        .m-btn:hover { opacity: 1; }
        .m-btn svg { width: 24px; height: 24px; fill: white; background: #444; border-radius: 50%; padding: 4px; box-sizing: content-box; margin-bottom: 4px; }
        .m-close { position: absolute; top: -40px; right: 20px; width: 30px; height: 30px; background: rgba(0,0,0,0.5); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; backdrop-filter: var(--glass); }

        .notif-banner { position: absolute; top: -80px; left: 50%; transform: translateX(-50%); width: 90%; max-width: 400px; background: rgba(255, 255, 255, 0.95); backdrop-filter: var(--glass); box-shadow: var(--sh-float); border-radius: 16px; padding: 12px 15px; display: flex; align-items: center; z-index: 100; transition: top var(--anim-dur) cubic-bezier(0.175, 0.885, 0.32, 1.275); cursor: pointer; border: 1px solid rgba(0,0,0,0.05); }
        .notif-banner.show { top: 10px; }
        .notif-av { width: 36px; height: 36px; border-radius: 50%; margin-right: 10px; flex-shrink: 0; background-size: cover; background-position: center; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px; }
        .notif-body { flex: 1; min-width: 0; }
        .notif-title { font-weight: 600; font-size: 13px; margin-bottom: 2px; }
        .notif-text { font-size: 12px; color: #666; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        @media (prefers-color-scheme: dark) { .notif-banner { background: rgba(40,40,40,0.95); border: 1px solid rgba(255,255,255,0.1); } .notif-text { color: #aaa; } }

        .unread-float {
            position: absolute;
            bottom: 90px;
            right: 20px;
            background: var(--bg-float);
            color: var(--text-float);
            padding: 8px 16px;
            border-radius: 24px;
            font-size: 13px;
            font-weight: 600;
            box-shadow: var(--sh-float);
            cursor: pointer;
            display: none;
            z-index: 90;
            animation: jellyPop var(--anim-dur);
            align-items: center;
            justify-content: center;
            backdrop-filter: var(--glass);
            border: 1px solid var(--border-float);
            min-width: 50px; 
            height: 36px;    
            transition: all 0.2s ease;
        }

        .unread-float:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0,0,0,0.15);
        }

        .unread-float:active {
            transform: scale(0.95);
        }

        .unread-float.show { display: flex; }

        .unread-float svg { 
            fill: currentColor;
            width: 16px; 
            height: 16px; 
            margin-right: 6px; 
        }

        .unread-float span {
            display: block;
        }

        @media (max-width: 768px) {
            .sidebar { display: none; }
            .list-pane { width: 100%; border-right: none; padding-bottom: 50px; }
            .chat-pane { display: none; width: 100%; position: fixed; top: 0; left: 0; height: 100%; z-index: 20; }
            .mobile-back { display: block; }
            body.mobile-chat-active .list-pane { display: none; }
            body.mobile-chat-active .chat-pane { display: flex; }
            body.mobile-chat-active .mobile-nav { display: none; }
            .mobile-nav { display: flex; }
            
            /* 移动端未读消息气泡 - 只在移动端聊天界面显示 */
            body.mobile-chat-active .mobile-unread-badge.show {
                display: flex;
            }
        }
        
        /* 宽屏模式强制隐藏气泡 */
        @media (min-width: 769px) {
            .mobile-unread-badge {
                display: none !important;
            }
        }
        
        /* ==================== GIF性能优化：默认暂停，按需播放 ==================== */
        .sticker-gif.paused {
            filter: brightness(0.9);
            position: relative;
        }
        .sticker-gif.paused::after {
            content: '▶';
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 16px;
            color: rgba(255,255,255,0.8);
            background: rgba(0,0,0,0.3);
            border-radius: 50%;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            pointer-events: none;
        }
        .sticker-gif:hover.paused {
            filter: brightness(1);
        }
        
        /* 消息中的GIF默认暂停 */
        .msg-bub img[src*=".webp"],
        .msg-bub img[src*="telegram_stickers"] {
            cursor: pointer;
        }

        body.visual-on .avatar-box.spin { animation: spin 0.5s ease-out; }
        body.visual-on .msg-row.anim-in-right { animation: flyInRight 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }
        body.visual-on .msg-row.anim-in-left { animation: flyInLeft 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; }

        .quote-recalled { font-style: italic; color: #aaa; text-decoration: line-through; }
        body.multi-mode .msg-area { padding-bottom: 80px; }
        
        /* P2P传输UI样式 - 简化版（朴实无华，性能优先） */
        
        /* 传输消息气泡 - 覆盖msg-bub的默认样式 */
        .msg-bub.transfer-message-bubble { 
            padding: 10px !important;
            font-size: 13px !important;
            min-width: 280px;
            max-width: 100% !important;
            background: #f5f5f5 !important;
            border-radius: 8px !important;
            word-break: normal !important;
            box-shadow: none !important;
            line-height: 1.4 !important;
            white-space: normal !important;
        }
        @media (prefers-color-scheme: dark) { 
            .msg-bub.transfer-message-bubble { 
                background: #2a2a2a !important;
            } 
        }
        /* 发送方的P2P消息也使用中性背景色 */
        .msg-row.me .msg-bub.transfer-message-bubble {
            background: #e3f2fd !important;
        }
        @media (prefers-color-scheme: dark) { 
            .msg-row.me .msg-bub.transfer-message-bubble {
                background: #1a3a52 !important;
            } 
        }
        
        /* 文件信息区域 */
        .transfer-message-bubble .file-info { 
            display: flex; 
            align-items: center;
            margin-bottom: 8px;
        }
        .transfer-message-bubble .file-icon { 
            font-size: 24px;
            margin-right: 10px;
            flex-shrink: 0;
        }
        .transfer-message-bubble .file-details { 
            flex: 1; 
            min-width: 0;
        }
        .transfer-message-bubble .file-name { 
            font-weight: 500;
            margin-bottom: 3px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .transfer-message-bubble .file-size { 
            font-size: 12px; 
            color: #666;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .file-size { color: #999; } 
        }
        .transfer-message-bubble .transfer-method,
        .transfer-message-bubble .sender-name,
        .transfer-message-bubble .status-info { 
            font-size: 12px; 
            color: #666;
            margin-top: 3px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .transfer-method,
            .transfer-message-bubble .sender-name,
            .transfer-message-bubble .status-info { color: #999; } 
        }
        
        /* 状态区域 */
        .transfer-message-bubble .transfer-status { 
            display: flex; 
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .transfer-message-bubble .status-text { 
            font-size: 12px; 
            color: #666;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .status-text { color: #999; } 
        }
        .transfer-message-bubble .status-indicator { 
            width: 8px;
            height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .transfer-message-bubble .status-indicator.pending { background: #ff9500; }
        .transfer-message-bubble .status-indicator.connecting { background: #007aff; }
        .transfer-message-bubble .status-indicator.transferring { background: #28a745; }
        
        /* 进度条区域 */
        .transfer-message-bubble .progress-section { 
            margin-top: 8px;
        }
        .transfer-message-bubble .progress-bar { 
            width: 100%; 
            height: 4px; 
            background: #ddd;
            border-radius: 2px;
            overflow: hidden;
            margin-bottom: 6px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .progress-bar { background: #444; } 
        }
        .transfer-message-bubble .progress-fill { 
            height: 100%; 
            background: #28a745;
            width: 0%;
            /* 移除transition以提升性能 */
        }
        .transfer-message-bubble .progress-info { 
            display: flex; 
            justify-content: space-between;
            font-size: 11px; 
            color: #666;
            margin-bottom: 4px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .progress-info { color: #999; } 
        }
        .transfer-message-bubble .speed-details { 
            font-size: 11px; 
            color: #666;
            margin-bottom: 4px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .speed-details { color: #999; } 
        }
        .transfer-message-bubble .speed-details .current-speed { 
            margin-right: 10px;
        }
        .transfer-message-bubble .time-estimate { 
            font-size: 11px; 
            color: #666;
            margin-bottom: 6px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble .time-estimate { color: #999; } 
        }
        
        /* 按钮样式 */
        .transfer-message-bubble button { 
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 3px;
            font-size: 12px;
            background: white;
            color: #333;
            cursor: pointer;
            margin-right: 6px;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble button { 
                background: #3a3a3a; 
                color: #ddd;
                border-color: #555;
            } 
        }
        .transfer-message-bubble button:hover { 
            background: #f0f0f0;
        }
        @media (prefers-color-scheme: dark) { 
            .transfer-message-bubble button:hover { background: #4a4a4a; } 
        }
        .transfer-message-bubble .accept-btn { 
            background: #28a745;
            color: white;
            border-color: #28a745;
        }
        .transfer-message-bubble .accept-btn:hover { 
            background: #218838;
        }
        .transfer-message-bubble .reject-btn,
        .transfer-message-bubble .cancel-btn { 
            background: #dc3545;
            color: white;
            border-color: #dc3545;
        }
        .transfer-message-bubble .reject-btn:hover,
        .transfer-message-bubble .cancel-btn:hover { 
            background: #c82333;
        }
        
        /* 完成状态 */
        .transfer-message-bubble .completion-info { 
            font-size: 12px; 
            color: #28a745;
            margin-top: 3px;
        }
        .transfer-message-bubble .completion-actions { 
            margin-top: 8px;
        }
        
        /* 失效/错误状态 */
        .transfer-message-bubble .expired-text { 
            color: #999;
            text-decoration: line-through;
        }
        .transfer-message-bubble .expiry-reason { 
            font-size: 12px; 
            color: #ff9500;
            margin-top: 3px;
        }
        .transfer-message-bubble .status-info.error { 
            color: #dc3545;
        }
        
        /* 操作按钮容器 */
        .transfer-message-bubble .action-buttons { 
            margin-top: 8px;
        }
    </style>
    
    <!-- P2P传输模块 - 核心传输层 -->
    <script src="/static/p2p_signaling_client.js?v=23"></script>
    <script src="/static/p2p_session.js?v=23"></script>
    <script src="/static/p2p_group_session.js?v=23"></script>
    <script src="/static/p2p_transfer_manager.js?v=23"></script>
    
    <!-- P2P传输模块 - 新消息化界面 (Frontend Redesign) -->
    <script src="/static/p2p_transfer_types.js?v=1"></script>
    <script src="/static/p2p_speed_calculator.js?v=1"></script>
    <script src="/static/p2p_database_sync.js?v=1"></script>
    <script src="/static/p2p_realtime_sync.js?v=1"></script>
    <script src="/static/p2p_transfer_manager_new.js?v=3"></script>
    <script src="/static/p2p_validity_checker.js?v=1"></script>
    <script src="/static/p2p_state_restoration.js?v=1"></script>
    <script src="/static/p2p_file_size_detector.js?v=1"></script>
    <script src="/static/p2p_transfer_message.js?v=3"></script>
    <script src="/static/p2p_system_message.js?v=3"></script>
    <script src="/static/p2p_message_integration.js?v=3"></script>
    <script src="/static/p2p_connection_error_handler.js?v=1"></script>
    <script src="/static/p2p_transfer_interruption_handler.js?v=1"></script>
    <script src="/static/p2p_degradation_handler.js?v=1"></script>
    <script src="/static/p2p_transfer_cancellation.js?v=1"></script>
    <script src="/static/p2p_cancel_notification.js?v=1"></script>
    <script src="/static/p2p_validity_state_sync.js?v=1"></script>
    <script src="/static/p2p_error_message_display.js?v=1"></script>
    <script src="/static/p2p_message_render_optimizer.js?v=1"></script>
    <script src="/static/p2p_state_update_optimizer.js?v=1"></script>
    <script src="/static/p2p_memory_manager.js?v=1"></script>
    <script src="/static/p2p_database_query_optimizer.js?v=1"></script>
    
    <!-- P2P传输样式 -->
    <link rel="stylesheet" href="/static/p2p_transfer_message.css?v=1">
</head>
<body>

<div id="toast" class="toast"></div>
<div id="upload-panel"><div class="up-header" id="up-header"><span id="up-title">文件传输助手</span><span style="cursor:pointer" onclick="closeUploadPanel()">✕</span></div><div class="up-list" id="up-list"></div></div>
<div id="lightbox" class="lightbox" onclick="closeLightbox()"><div class="lightbox-close">&times;</div><img id="lightbox-img" class="transition" onclick="event.stopPropagation()" onwheel="zoomImg(event)" onmousedown="startDrag(event)" ondragstart="return false"></div>

<div id="ctx-menu" class="ctx-menu">
    <div class="ctx-item" onclick="menuAction('copy')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>复制</div>
    <div class="ctx-item" id="ctx-fwd" onclick="menuAction('forward')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>转发</div>
    <div class="ctx-item" id="ctx-multi" onclick="menuAction('multi')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M22 10l-6-6H2v16h20V10zm-2 8H4V6h10.17l3.83 3.83V18zM11.44 8.97l-4.97 4.94-2.5-2.47-1.41 1.41 3.91 3.91 6.37-6.38z"/></svg>多选</div>
    <div class="ctx-item" id="ctx-quote" onclick="menuAction('quote')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z"/></svg>引用</div>
    <div class="ctx-item" id="ctx-remark" onclick="menuAction('remark')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>查看资料/备注</div>
    <div id="ctx-recall-line" class="ctx-line"></div>
    <div id="ctx-recall" class="ctx-item" onclick="menuAction('recall')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z"/></svg>撤回</div>
</div>

<div id="list-ctx-menu" class="ctx-menu">
    <div class="ctx-item" onclick="listMenuAction('pin')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M16 9V4l1 1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1l1-1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/></svg><span id="lbl-pin">置顶</span></div>
    <div class="ctx-item" id="list-ctx-remark" onclick="listMenuAction('remark')"><svg class="ctx-icon" viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>查看资料/备注</div>
</div>

<div id="multi-bar" class="multi-bar">
    <div class="m-close" onclick="exitMulti()">✕</div>
    <div class="m-btn" onclick="multiAction('seq')"><svg viewBox="0 0 24 24"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>逐条转发</div>
    <div class="m-btn" onclick="multiAction('merge')"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/><path d="M0 0h24v24H0z" fill="none"/></svg>合并转发</div>
    <div class="m-btn" onclick="multiAction('copy')"><svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>复制</div>
</div>

<!-- MODALS -->
<div id="md-login" class="modal-bg" style="display:none;"><div class="modal-box"><div class="modal-h">QQ Pro V10.0</div><form onsubmit="doLogin(); return false;" style="display:contents;"><input id="inp-nick" class="modal-inp" placeholder="输入昵称" maxlength="10" style="text-align:center;"><input id="inp-pwd" type="password" class="modal-inp" placeholder="设置/输入密码" style="text-align:center;" onkeypress="if(event.keyCode==13)doLogin()"><button class="btn-block clickable" type="button" onclick="doLogin()">注册 / 登录</button></form></div></div>
<div id="md-create" class="modal-bg"><div class="modal-box"><div class="modal-h">新建群组</div><input id="inp-grp-name" class="modal-inp" placeholder="群组名称"><div style="font-size:12px; margin-bottom:10px; color:var(--text-sub);">选择好友:</div><div id="create-list" style="flex:1; overflow-y:auto; margin-bottom:15px; min-height:100px;"></div><button class="btn-block clickable" onclick="submitCreate()">创建</button><div style="text-align:center; margin-top:5px; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeMd('md-create')">取消</div></div></div>
<div id="md-manage" class="modal-bg"><div class="modal-box"><div class="modal-h">群组管理</div><div class="setting-section"><div class="setting-label">群名称</div><input id="mng-grp-name" class="modal-inp" placeholder="修改群名"><button class="btn-block clickable" style="margin-bottom:0; padding:8px; font-size:13px;" onclick="doRename()">保存名称</button></div><div class="setting-section" style="padding-bottom:0; border:none;"><div class="setting-label">成员管理</div><button class="btn-block clickable" style="background:#30d158; margin-bottom:10px;" onclick="openInvite()">+ 邀请新成员</button><div id="mng-mem-list" style="max-height:150px; overflow-y:auto; background:rgba(0,0,0,0.03); border-radius:8px; padding:5px;"></div></div><button class="btn-block clickable" style="background:#ff3b30; margin-top:15px;" onclick="doDissolve()">解散群组</button><div style="text-align:center; margin-top:10px; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeMd('md-manage')">关闭</div></div></div>
<div id="md-invite" class="modal-bg"><div class="modal-box"><div class="modal-h">邀请成员</div><div id="invite-list" style="flex:1; overflow-y:auto; margin-bottom:15px; min-height:100px;"></div><button class="btn-block clickable" onclick="submitInvite()">邀请加入</button><div style="text-align:center; margin-top:5px; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeMd('md-invite')">取消</div></div></div>
<div id="md-set" class="modal-bg"><div class="modal-box" style="width: 340px;"><div class="modal-h">设置</div><div class="setting-section" style="text-align:center; border:none;"><div id="set-av" class="clickable" style="width:80px; height:80px; border-radius:24px; margin:0 auto 15px auto; box-shadow:var(--sh-modal-av); border: 3px solid white;"></div><button class="btn-block clickable" style="width:auto; font-size:12px; padding:5px 15px; background:#30d158;" onclick="changeAv()">🎲 随机头像</button></div><div class="setting-section"><div class="setting-label">修改昵称</div><input id="set-new-nick" class="modal-inp" placeholder="新昵称" style="margin-bottom:5px;"></div><div class="setting-section"><div class="setting-label"><span>视觉特效 (毛玻璃/阴影/动画)</span><div id="vis-toggle" class="toggle-switch" onclick="toggleVisual()"></div></div><div style="font-size:11px; color:#999;">开启后界面更美观，但可能增加卡顿</div></div><form onsubmit="return false;" style="display:contents;"><div class="setting-section" style="border:none;"><div class="setting-label"><span style="cursor:text;" onclick="triggerDev()">修改密码</span></div><input id="set-new-pwd" type="password" class="modal-inp" placeholder="新密码 (留空不修改)" style="margin-bottom:5px;"></div></form><button class="btn-block clickable" onclick="saveProfile()">保存修改</button><button class="btn-block clickable" style="background:#ff3b30; margin-top:10px;" onclick="doLogout()">退出登录</button><div style="text-align:center; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeMd('md-set')">关闭</div></div></div>
<div id="md-profile" class="modal-bg"><div class="modal-box"><div class="modal-h">用户资料</div><div style="text-align:center;"><div id="pf-av" style="width:100px; height:100px; border-radius:30px; margin:0 auto 20px auto; box-shadow:var(--sh-modal-av);"></div><div id="pf-nick" style="font-size:22px; font-weight:700; margin-bottom:5px;"></div><div id="pf-uid" style="font-size:12px; color:#888; margin-bottom:20px;"></div></div><div class="setting-section" style="border:none;"><div class="setting-label">备注名</div><input id="pf-remark" class="modal-inp" placeholder="设置备注 (留空显示原名)" style="text-align:center;"></div><button class="btn-block clickable" onclick="saveRemark()">保存</button><div style="text-align:center; font-size:12px; cursor:pointer; color:var(--text-sub); margin-top:10px;" onclick="closeMd('md-profile')">关闭</div></div></div>
<div id="md-dev-auth" class="modal-bg" style="backdrop-filter: var(--glass); background:rgba(0,0,0,0.8);"><div class="modal-box" style="background:#111; border:1px solid #333; color:#ddd;"><div class="modal-h" style="color:#33d17a;">SYSTEM CORE</div><form onsubmit="verifyDev(); return false;" style="display:contents;"><input id="dev-pwd" type="password" class="modal-inp" style="background:#222; border-color:#444; color:#33d17a; text-align:center; letter-spacing:2px;" placeholder="PASSCODE"><button class="btn-block clickable" style="background:#33d17a; color:#000;" type="button" onclick="verifyDev()">ACCESS</button></form><div style="text-align:center; margin-top:10px; font-size:12px; cursor:pointer; color:#666;" onclick="closeMd('md-dev-auth')">TERMINATE</div></div></div>
<div id="md-dev-logs" class="modal-bg"><div class="modal-box" style="width: 800px; max-width:95%; height:80vh; background:#111; color:#ccc;"><div class="modal-h" style="color:#33d17a;">Global Logs (Audit)</div><div id="dev-logs-content"></div><div style="text-align:center; margin-top:10px; font-size:12px; cursor:pointer; color:#666;" onclick="closeMd('md-dev-logs')">CLOSE</div></div></div>
<div id="md-picker" class="modal-bg"><div class="modal-box"><div class="modal-h">选择目标</div><div id="picker-list" style="flex:1;overflow-y:auto;max-height:300px;margin-bottom:15px;"></div><button class="btn-block clickable" onclick="submitForward()">发送</button><div style="text-align:center;font-size:12px;color:#888;cursor:pointer;" onclick="closeMd('md-picker')">取消</div></div></div>
<div id="md-pinned" class="modal-bg"><div class="modal-box" style="width: 500px; max-width:95%; height:70vh; display:flex; flex-direction:column;"><div id="pinned-content" style="flex:1; overflow:hidden; display:flex; flex-direction:column;"></div><div style="text-align:center; margin-top:10px; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeMd('md-pinned')">关闭</div></div></div>
<div id="md-fwd-detail" class="modal-bg"><div class="modal-box" style="width: 400px; max-width:95%; height:70vh;"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;"><div id="fwd-back" class="clickable" style="font-size:14px;color:var(--accent);display:none;" onclick="popFwdStack()">‹ 返回</div><div class="modal-h" id="fwd-title" style="margin-bottom:0;font-size:16px;">聊天记录</div><div style="width:30px;"></div></div><div id="fwd-content" style="flex:1;overflow-y:auto;padding:10px;background:rgba(0,0,0,0.03);border-radius:8px;"></div><div style="text-align:center; margin-top:10px; font-size:12px; cursor:pointer; color:var(--text-sub);" onclick="closeFwdMd()">关闭</div></div></div>

<!-- 账户信息合并管理面板 -->
<div id="md-account-panel" class="modal-bg" style="backdrop-filter: var(--glass); background:rgba(0,0,0,0.85);">
    <div class="modal-box" style="width: 700px; max-width:95%; max-height:85vh; background:#111; border:1px solid #333; color:#ddd; display:flex; flex-direction:column;">
        <div class="modal-h" style="color:#ff9500; font-size:18px; display:flex; align-items:center; justify-content:space-between;">
            <span>🔐 账户信息合并管理面板</span>
            <span style="font-size:10px; color:#666; font-weight:normal;">SYSTEM ADMIN</span>
        </div>
        <div style="padding:10px 0; border-bottom:1px solid #333; margin-bottom:10px;">
            <div style="display:flex; gap:10px;">
                <button class="btn-block clickable" style="flex:1; background:#30d158; margin:0; padding:10px; font-size:13px;" onclick="showAccessControlSection()">🔓 访问控制</button>
                <button class="btn-block clickable" style="flex:1; background:#ff3b30; margin:0; padding:10px; font-size:13px;" onclick="showDeleteAccountSection()">🗑️ 删除账户</button>
                <button class="btn-block clickable" style="flex:1; background:#007aff; margin:0; padding:10px; font-size:13px;" onclick="showMergeAccountSection()">🔗 合并账户</button>
            </div>
        </div>
        
        <!-- 访问控制区域 -->
        <div id="access-control-section" style="display:none; flex:1; overflow-y:auto;">
            <div style="background:#1a1a1a; padding:12px; border-radius:8px; margin-bottom:10px; border-left:3px solid #30d158;">
                <div style="color:#30d158; font-weight:600; margin-bottom:5px;">🔓 无限制访问说明</div>
                <div style="font-size:12px; color:#999; line-height:1.5;">
                    • 启用后，用户可以查看所有历史消息，不受注册时间限制<br>
                    • 适用场景：学校机房时钟不准确、助教/管理员账户<br>
                    • 可以单独为某个用户启用，也可以批量为所有用户启用
                </div>
            </div>
            <div style="display:flex; gap:10px; margin-bottom:15px;">
                <button class="btn-block clickable" style="flex:1; background:#30d158; margin:0; padding:10px; font-size:12px;" onclick="batchToggleAccess(true)">✅ 批量启用所有用户</button>
                <button class="btn-block clickable" style="flex:1; background:#ff9500; margin:0; padding:10px; font-size:12px;" onclick="batchToggleAccess(false)">❌ 批量禁用所有用户</button>
            </div>
            <div style="color:#888; font-size:12px; margin-bottom:8px;">单独管理用户访问权限：</div>
            <div id="access-control-list" style="flex:1; overflow-y:auto; max-height:300px; background:#1a1a1a; border-radius:8px; padding:5px;"></div>
        </div>
        
        <!-- 删除账户区域 -->
        <div id="delete-account-section" style="display:none; flex:1; overflow-y:auto;">
            <div style="background:#1a1a1a; padding:12px; border-radius:8px; margin-bottom:10px; border-left:3px solid #ff3b30;">
                <div style="color:#ff3b30; font-weight:600; margin-bottom:5px;">⚠️ 删除账户说明</div>
                <div style="font-size:12px; color:#999; line-height:1.5;">
                    • 删除操作仅清除该账户的个人资料信息（昵称、头像等）<br>
                    • 历史聊天记录仍将保留在系统中<br>
                    • 被删除账户将无法再次登录系统<br>
                    • 同名新账号将被视为全新账户，不继承任何历史记录
                </div>
            </div>
            <div style="color:#888; font-size:12px; margin-bottom:8px;">选择要删除的账户：</div>
            <div id="delete-account-list" style="flex:1; overflow-y:auto; max-height:250px; background:#1a1a1a; border-radius:8px; padding:5px;"></div>
            <div style="margin-top:15px;">
                <button class="btn-block clickable" style="background:#ff3b30;" onclick="confirmDeleteAccount()">确认删除选中账户</button>
            </div>
        </div>
        
        <!-- 合并账户区域 -->
        <div id="merge-account-section" style="display:none; flex:1; overflow-y:auto;">
            <div style="background:#1a1a1a; padding:12px; border-radius:8px; margin-bottom:10px; border-left:3px solid #007aff;">
                <div style="color:#007aff; font-weight:600; margin-bottom:5px;">🔗 合并账户说明</div>
                <div style="font-size:12px; color:#999; line-height:1.5;">
                    • 将源账户的所有消息、群组关系迁移到目标账户<br>
                    • 合并后，所有源账户发送的消息将显示为目标账户发送<br>
                    • 目标账户保留原有的登录凭证（用户名与密码）<br>
                    • 源账户将自动失效且不可恢复
                </div>
            </div>
            <div style="display:flex; gap:15px;">
                <div style="flex:1;">
                    <div style="color:#ff9500; font-size:12px; margin-bottom:8px; font-weight:600;">源账户 (将被合并)：</div>
                    <div id="merge-source-list" style="height:200px; overflow-y:auto; background:#1a1a1a; border-radius:8px; padding:5px; border:1px solid #333;"></div>
                </div>
                <div style="display:flex; align-items:center; color:#666; font-size:24px;">→</div>
                <div style="flex:1;">
                    <div style="color:#30d158; font-size:12px; margin-bottom:8px; font-weight:600;">目标账户 (保留)：</div>
                    <div id="merge-target-list" style="height:200px; overflow-y:auto; background:#1a1a1a; border-radius:8px; padding:5px; border:1px solid #333;"></div>
                </div>
            </div>
            <div id="merge-preview" style="margin-top:10px; padding:10px; background:#1a1a1a; border-radius:8px; display:none;">
                <div style="font-size:12px; color:#888;">合并预览：</div>
                <div id="merge-preview-content" style="font-size:13px; color:#ddd; margin-top:5px;"></div>
            </div>
            <div style="margin-top:15px;">
                <button class="btn-block clickable" style="background:#007aff;" onclick="confirmMergeAccounts()">确认合并账户</button>
            </div>
        </div>
        
        <div style="text-align:center; margin-top:15px; font-size:12px; cursor:pointer; color:#666;" onclick="closeMd('md-account-panel')">关闭面板</div>
    </div>
</div>

<!-- Old P2P UI elements removed - now using message-based interface -->

<div id="app">
    <div class="sidebar">
        <div id="my-av" class="avatar-box clickable" onclick="openSet()"></div>
        <div class="nav-btn clickable active" id="nav-msg" onclick="tab('msg')"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div>
        <div class="nav-btn clickable" id="nav-con" onclick="tab('con')"><svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg></div>
        <div class="nav-btn clickable" id="nav-file" onclick="tab('file')"><svg viewBox="0 0 24 24"><path d="M6 2c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6H6zm7 7V3.5L18.5 9H13z"/></svg></div>
    </div>

    <div class="list-pane">
        <div id="tab-msg" style="display:flex; flex-direction:column; height:100%;"><div class="search-header"><div class="search-title">消息</div><div class="btn-circle clickable" onclick="openCreate()">+</div></div><div class="list-content" id="ls-msg"></div></div>
        <div id="tab-con" style="display:none; flex-direction:column; height:100%;"><div class="search-header"><div class="search-title">通讯录</div></div><div class="list-content" id="ls-con"></div></div>
        <div id="tab-file" style="display:none; flex-direction:column; height:100%;">
            <div class="search-header">
                <div class="search-title">文件</div>
                <div class="btn-circle clickable" onclick="loadFiles()">↻</div>
            </div>
            <div style="padding: 10px 15px; border-bottom: 1px solid var(--border);">
                <div class="input-wrap" style="border-radius: 12px; padding: 4px 10px; display: flex; align-items: center;">
                    <input type="text" id="file-search-input" class="inp-txt" placeholder="搜索文件名..." style="padding: 6px; font-size: 14px; flex: 1; min-width: 0;" onkeypress="if(event.key==='Enter') searchFiles()">
                    <button class="btn-send" onclick="searchFiles()" style="padding: 4px 10px; font-size: 13px; flex-shrink: 0; white-space: nowrap;">搜索</button>
                </div>
            </div>
            <div class="list-content" id="ls-file" onscroll="handleFileListScroll()"></div>
        </div>
    </div>

    <div class="chat-pane" id="chat-pane">
        <div id="notif-banner" class="notif-banner" onclick="handleNotifClick()">
            <div id="notif-av" class="notif-av"></div>
            <div class="notif-body">
                <div id="notif-title" class="notif-title"></div>
                <div id="notif-text" class="notif-text"></div>
            </div>
        </div>

        <div class="chat-top">
            <div style="display:flex; align-items:center;">
                <div class="mobile-back" onclick="backMobileList()">‹</div>
                <div id="mobile-unread-badge" class="mobile-unread-badge">0</div>
                <div><div class="chat-name" id="chat-t">未选择</div><div class="chat-stat" id="chat-s"></div></div>
            </div>
            <div id="btn-grp-set" class="btn-icon clickable" style="display:none;" onclick="openManage()">⚙️</div>
        </div>
        <div class="msg-area" id="msg-box" onclick="closeCtx()">
            <div class="empty">选择左侧会话开始聊天</div>
        </div>
        <div id="unread-float" class="unread-float" onclick="jumpToBottom()"><svg viewBox="0 0 24 24"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg><span>0</span></div>
        <div class="chat-bottom" id="input-area" style="display:none;">
            <div id="sticker-panel" class="sticker-panel">
                <div class="sticker-tabs-container">
                    <div class="sticker-tabs">
                        <div class="sticker-tab active" data-category="recent" title="最近使用"><img src="/static/emoji/23f0.png" class="emoji-img-category" alt="⏰" title="最近使用"></div>
                        <div class="sticker-tab" data-category="smileys_emotion" title="表情与情感"><img src="/static/emoji/1f600.png" class="emoji-img-category" alt="😀" title="表情与情感"></div>
                        <div class="sticker-tab" data-category="people_body" title="人物与手势"><img src="/static/emoji/1f44b.png" class="emoji-img-category" alt="👋" title="人物与手势"></div>
                        <div class="sticker-tab" data-category="animals_nature" title="动物与自然"><img src="/static/emoji/1f43b.png" class="emoji-img-category" alt="🐻" title="动物与自然"></div>
                        <div class="sticker-tab" data-category="food_drink" title="食物与饮料"><img src="/static/emoji/1f354.png" class="emoji-img-category" alt="🍔" title="食物与饮料"></div>
                        <div class="sticker-tab" data-category="activity" title="活动与娱乐"><img src="/static/emoji/26bd.png" class="emoji-img-category" alt="⚽" title="活动与娱乐"></div>
                        <div class="sticker-tab" data-category="objects" title="物体"><img src="/static/emoji/1f4a1.png" class="emoji-img-category" alt="💡" title="物体"></div>
                        <div class="sticker-tab" data-category="travel_places" title="旅行与地点"><img src="/static/emoji/1f680.png" class="emoji-img-category" alt="🚀" title="旅行与地点"></div>
                        <div class="sticker-tab" data-category="symbols_flags" title="符号与旗帜"><img src="/static/emoji/2049-fe0f.png" class="emoji-img-category" alt="⁉️" title="符号与旗帜"></div>
                    </div>
                    <div class="sticker-tabs-scrollbar">
                        <div class="sticker-tabs-scrollbar-thumb"></div>
                    </div>
                </div>
                <div class="sticker-content" id="sticker-content"></div>
                <div class="sticker-pagination">
                    <button id="sticker-prev" class="sticker-page-btn">◀</button>
                    <span id="sticker-page-info" class="sticker-page-info">1 / 1</span>
                    <button id="sticker-next" class="sticker-page-btn">▶</button>
                    <div style="margin-left: auto; display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 11px; color: var(--text-sub);">动态</span>
                        <div id="dynamic-emoji-toggle" class="toggle-switch" onclick="toggleDynamicEmoji()" title="切换动态/静态表情"></div>
                    </div>
                </div>
            </div>
            <div class="reply-bar" id="reply-bar">
                <div class="reply-content" id="reply-content"></div>
                <div class="reply-close" onclick="cancelQuote()">×</div>
            </div>
            <div class="input-wrap">
                <label class="btn-icon clickable" onclick="toggleSticker()"><svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm3.5-9c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-7 0c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/></svg></label>
                <label class="btn-icon clickable"><svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5a2.5 2.5 0 0 0 5 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg><input type="file" multiple hidden onchange="upFiles(this.files)"></label>
                <textarea id="inp-msg" class="inp-txt" rows="1" placeholder="发送消息..."></textarea>
                <button class="btn-send clickable" onclick="send()">发送</button>
            </div>
        </div>
    </div>

    <div class="mobile-nav">
        <div class="m-nav-item active" id="mn-msg" onclick="tab('msg')"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg><span>消息</span></div>
        <div class="m-nav-item" id="mn-con" onclick="tab('con')"><svg viewBox="0 0 24 24"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg><span>通讯录</span></div>
        <div class="m-nav-item" id="mn-file" onclick="tab('file')"><svg viewBox="0 0 24 24"><path d="M6 2c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6H6zm7 7V3.5L18.5 9H13z"/></svg><span>文件</span></div>
        <div class="m-nav-item" onclick="openSet()"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg><span>我</span></div>
    </div>
</div>

<script>
    let me = null, target = null;
    // 重构：删除全局 msgs 数组，使用 currentChatMsgs 仅存储当前聊天的消息
    let cache = { users:{}, groups:{}, read_markers:{}, pinned: {}, remarks: {} };
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
    } catch(e) {}
    
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
        } catch(e) {
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
            } catch(e) {}

            useTelegramStickers = true;
            logInfo('Telegram Stickers', '✓✓✓ GIF系统启用成功 ✓✓✓');
            logDebug('Telegram Stickers', 'useTelegramStickers =', useTelegramStickers);

            return true;
        } catch(e) {
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
        } catch(e) {
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
        } catch(e) {
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
        if(visualOn) { document.body.classList.add('visual-on'); document.getElementById('vis-toggle').classList.add('on'); }
        try { cache.pinned = JSON.parse(localStorage.getItem('qq_pinned') || '{}'); } catch(e) { cache.pinned = {}; }
    }
    function toggleVisual() {
        visualOn = !visualOn;
        if(visualOn) { document.body.classList.add('visual-on'); document.getElementById('vis-toggle').classList.add('on'); } 
        else { document.body.classList.remove('visual-on'); document.getElementById('vis-toggle').classList.remove('on'); }
        localStorage.setItem('qq_visual_on', visualOn);
    }

    function showToast(msg) {
        var t = document.getElementById('toast');
        t.innerText = msg;
        t.classList.add('show');
        setTimeout(function(){ t.classList.remove('show'); }, 2000);
    }

    function getName(uid) {
        if(cache.remarks[uid]) return cache.remarks[uid];
        if(cache.users[uid]) return cache.users[uid].name;
        if(uid === 'system') return '系统通知';
        if(uid === me.uid) return me.name;
        return 'Unknown';
    }

    function backMobileList() { 
        document.body.classList.remove('mobile-chat-active'); 
        target = null; 
        updateListUI(); // 使用 updateListUI 替代 renderList
        
        // 隐藏移动端未读消息气泡
        var badge = document.getElementById('mobile-unread-badge');
        if(badge) {
            badge.classList.remove('show');
        }
    }

    const upPanel = document.getElementById('upload-panel'); const upHeader = document.getElementById('up-header');
    let upX = 0, upY = 0, upDragging = false;
    upHeader.onmousedown = (e) => { e.preventDefault(); upDragging = true; upX = e.clientX - upPanel.offsetLeft; upY = e.clientY - upPanel.offsetTop; document.addEventListener('mousemove', onUpMove); document.addEventListener('mouseup', onUpEnd); };
    function onUpMove(e) { if(!upDragging) return; e.preventDefault(); let l = Math.max(0, Math.min(window.innerWidth-upPanel.offsetWidth, e.clientX-upX)); let t = Math.max(0, Math.min(window.innerHeight-upPanel.offsetHeight, e.clientY-upY)); upPanel.style.left=l+'px'; upPanel.style.top=t+'px'; upPanel.style.right='auto'; upPanel.style.bottom='auto'; }
    function onUpEnd() { upDragging = false; document.removeEventListener('mousemove', onUpMove); document.removeEventListener('mouseup', onUpEnd); }

    const appEl = document.getElementById('app');
    appEl.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); };
    appEl.ondrop = (e) => { e.preventDefault(); e.stopPropagation(); if(target && e.dataTransfer.files.length > 0) upFiles(e.dataTransfer.files); };
    document.getElementById('inp-msg').addEventListener('paste', (e) => { if(e.clipboardData.files.length > 0) { e.preventDefault(); if(target) upFiles(e.clipboardData.files); } });

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
                const r = await fetch('/get_user_info', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({uid: storedUid}) });
                
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
                        if(savedChat) {
                            targetChat = JSON.parse(savedChat);
                        }
                    } catch(e) {
                        logWarn('Session', '读取保存的会话状态失败:', e);
                    }
                    
                    // 等待第一次 sync 完成后再决定打开哪个聊天
                    setTimeout(() => {
                        var chatToOpen = null;
                        
                        if(targetChat) {
                            // 验证保存的会话是否仍然有效
                            if(targetChat.type === 'group') {
                                // 检查群聊是否存在
                                if(cache.groups[targetChat.id]) {
                                    chatToOpen = targetChat;
                                }
                            } else if(targetChat.type === 'private') {
                                // 检查私聊用户是否存在
                                if(cache.users[targetChat.id]) {
                                    chatToOpen = targetChat;
                                }
                            }
                        }
                        
                        // 如果没有有效的保存会话，默认进入主群聊
                        if(!chatToOpen) {
                            chatToOpen = {id: 'group_global', type: 'group', name: '全员摸鱼群'};
                        }
                        
                        switchChat(chatToOpen.id, chatToOpen.type, chatToOpen.name);
                    }, 500); // 等待500ms确保 sync有足够时间加载数据
                    
                    return;
                }
            } catch (e) {}
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
            } catch(e) {
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
                    h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', true)"><img class="sticker-gif" data-src="/static/telegram_stickers/'+gifData.file+'" alt="'+emoji+'"></div>';
                    gifCount++;
                } else if (emojiMapping[emoji]) {
                    // 降级到PNG
                    h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)">'+emojiToImg(emoji)+'</div>';
                    pngCount++;
                } else {
                    // 最终降级：显示Unicode字符
                    h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', true)"><span style="font-size:28px">'+emoji+'</span></div>';
                    unicodeCount++;
                }
            } else {
                // 静态模式：优先显示 PNG
                if (emojiMapping[emoji]) {
                    h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)">'+emojiToImg(emoji)+'</div>';
                    pngCount++;
                } else {
                    h += '<div class="sticker-item" onclick="sendSticker(\\''+emoji+'\\', false)"><span style="font-size:28px">'+emoji+'</span></div>';
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
        const activeTab = document.querySelector('.sticker-tab[data-category="'+cat+'"]');
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
            } catch(e) {}
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
            } catch(e) {}
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
        document.addEventListener('click', function(e) {
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
            const onScroll = function() {
                if (!ticking) {
                    requestAnimationFrame(function() {
                        updateStickerTabsScrollbar();
                        ticking = false;
                    });
                    ticking = true;
                }
            };
            
            tabsContainer.addEventListener('scroll', onScroll);
            
            // 添加鼠标滚轮支持水平滚动，带平滑效果
            let scrollTimeout;
            tabsContainer.addEventListener('wheel', function(e) {
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
        if(!target) return;
        document.getElementById('sticker-panel').style.display = 'none';

        // 更新最近使用
        let recents = [];
        try { recents = JSON.parse(localStorage.getItem('qq_recent_stickers') || '[]'); } catch(e){}
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
            method:'POST', 
            headers:{'Content-Type':'application/json'}, 
            body:JSON.stringify({
                uid:me.uid, 
                to_uid:target.id, 
                content:content, 
                type: msgType
            }) 
        });
        
        if(pollingTimer) clearTimeout(pollingTimer); 
        sync();
    }

    async function doLogin() {
        const n = document.getElementById('inp-nick').value.trim(); const p = document.getElementById('inp-pwd').value.trim();
        if(!n || !p) return alert('请输入昵称和密码');
        try {
            const r = await fetch('/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({nickname:n, password:p}) });
            if(!r.ok) { const err = await r.json(); throw new Error(err.error || '登录失败'); }
            me = await r.json(); localStorage.setItem('qq_uid', me.uid);
            document.getElementById('md-login').style.display = 'none'; document.getElementById('app').style.opacity = '1';
            upMe(); 
            startPolling(); 
            
            // 登录后等待数据加载，然后进入默认聊天（主群聊）
            setTimeout(() => {
                switchChat('group_global','group','全员摸鱼群');
            }, 500);
        } catch(e){ alert(e.message); }
    }
    function doLogout() { if(confirm('确定要退出登录吗？')) { localStorage.removeItem('qq_uid'); location.reload(); } }

    function startPolling() { if(pollingTimer) clearTimeout(pollingTimer); sync(); }

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
        if(!m || !chatTarget) return false;
        
        // 统一转换为 String 进行比较，避免 SQLite Integer vs JS String 类型不匹配
        var mFromUid = String(m.from_uid || '');
        var mToUid = String(m.to_uid || '');
        var targetId = String(chatTarget.id || '');
        var myUid = String(me.uid || '');
        
        if(chatTarget.type === 'group') {
            // 群聊：消息的 to_uid 等于群ID
            return mToUid === targetId;
        } else {
            // 私聊
            if(targetId === myUid) {
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
        if(!m) return;
        
        const preview = formatMsgPreview(m);
        const timestamp = m.timestamp;
        const fromName = getName(m.from_uid);
        
        // 确定这条消息属于哪个聊天
        if(cache.groups[m.to_uid]) {
            // 群聊消息
            const gid = m.to_uid;
            if(!cache.groups[gid]._sidebar) cache.groups[gid]._sidebar = { unreadCount: 0 };
            cache.groups[gid]._sidebar.lastMsgPreview = fromName + ': ' + preview;
            cache.groups[gid]._sidebar.lastMsgTime = timestamp;
            cache.groups[gid]._sidebar.lastMsgId = String(m.id);
            cache.groups[gid]._sidebar.lastMsgFromUid = String(m.from_uid);
        } else {
            // 私聊消息
            let chatPartnerId = null;
            if(String(m.from_uid) === String(me.uid)) {
                // 我发的消息
                chatPartnerId = m.to_uid;
            } else if(String(m.to_uid) === String(me.uid)) {
                // 发给我的消息
                chatPartnerId = m.from_uid;
            }
            
            if(chatPartnerId && cache.users[chatPartnerId]) {
                if(!cache.users[chatPartnerId]._sidebar) cache.users[chatPartnerId]._sidebar = { unreadCount: 0 };
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
        if(m.type === 'system') return '[系统消息]';
        if(m.is_recalled) return '[已撤回]';
        if(m.content && m.content.startsWith('{"type":"merge_fwd"')) return '[聊天记录]';
        if(m.type === 'sticker') return '[表情]';
        if(m.type === 'file') return '[文件]';
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
        if(newData && localIdx !== -1) {
            currentChatMsgs[localIdx] = newData;
            localMsg = newData;
        }
        
        if(!localMsg) return false;
        
        // 查找 DOM 元素 - 类型安全：确保 ID 为 String
        var el = document.getElementById('msg-' + safeId(msgId));
        if(!el) return false;
        
        // 生成新的 DOM 元素
        var newEl;
        if(localMsg.type === 'system' || localMsg.is_recalled) {
            newEl = renderSystemMsg(localMsg);
        } else {
            newEl = renderMessageElement(localMsg, false);
        }
        
        if(newEl) {
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
        if(!oldMsg || !newMsg) return true;
        
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
        var localIdx = currentChatMsgs.findIndex(function(m) {
            return String(m.id) === targetId;
        });
        if(localIdx !== -1) {
            currentChatMsgs[localIdx].is_recalled = true;
        }
        
        // 更新 DOM
        var el = document.getElementById('msg-' + targetId);
        if(el && !el.classList.contains('sys')) {
            var localMsg = localIdx !== -1 ? currentChatMsgs[localIdx] : {id: msgId, is_recalled: true};
            var newEl = renderSystemMsg(localMsg);
            if(newEl) {
                el.outerHTML = newEl.outerHTML;
            }
        }
        
        // 更新引用了该消息的其他消息
        currentChatMsgs.forEach(function(m) {
            // SQLite 修复：引用消息的 ID 也需要统一转换为 String 比较
            if(m.quote && String(m.quote.id) === targetId) {
                m.quote.is_recalled = true;
                var qEl = document.querySelector('#msg-' + String(m.id) + ' .quote-box');
                if(qEl) {
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
            if(Object.keys(userVersions).length > 0) {
                syncUrl += '&user_version=' + encodeURIComponent(JSON.stringify(userVersions));
            }
            if(Object.keys(groupVersions).length > 0) {
                syncUrl += '&group_version=' + encodeURIComponent(JSON.stringify(groupVersions));
            }
            // 添加客户端群组列表（用于检测被踢/解散）
            var clientGroups = Object.keys(cache.groups);
            if(clientGroups.length > 0) {
                syncUrl += '&client_groups=' + encodeURIComponent(JSON.stringify(clientGroups));
            }
            
            const r = await fetch(syncUrl);
            
            // **安全控制：检查会话状态**
            if (r.status === 403) {
                const errData = await r.json();
                if (errData.error === 'session_invalidated') {
                    // 会话已失效，强制退出登录
                    if(pollingTimer) clearTimeout(pollingTimer);
                    alert(errData.message || '您的账户已被禁用，请重新登录');
                    localStorage.removeItem('qq_uid');
                    location.reload();
                    return;
                }
            }
            
            const d = await r.json();
            
            // ============ 版本控制：处理被踢出的群组 ============
            if(d.kicked_from_groups && d.kicked_from_groups.length > 0) {
                d.kicked_from_groups.forEach(function(gid) {
                    // 从缓存中移除
                    delete cache.groups[gid];
                    delete groupVersions[gid];
                    // 如果当前正在该群，强制退出
                    if(target && target.id === gid) {
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
            if(d.deleted_groups && d.deleted_groups.length > 0) {
                d.deleted_groups.forEach(function(gid) {
                    delete cache.groups[gid];
                    delete groupVersions[gid];
                    if(target && target.id === gid) {
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
            if(d.changed_users) {
                for(var uid in d.changed_users) {
                    var changedUser = d.changed_users[uid];
                    
                    // 修复"幽灵用户"漏洞：处理被删除用户
                    if(changedUser.deleted) {
                        // 用户已被注销，更新缓存标记
                        if(cache.users[uid]) {
                            cache.users[uid].name = changedUser.name + ' (已注销)';
                            cache.users[uid].avatar_bg = '#999';  // 使用灰色头像表示已注销
                            cache.users[uid].status = 'offline';   // 标记为离线
                            cache.users[uid].deleted = true;       // 标记删除状态
                        }
                        // 如果当前正在与该用户私聊，强制退出并提示
                        if(target && target.type === 'private' && target.id === uid) {
                            target = null;
                            currentChatMsgs = [];
                            document.getElementById('chat-t').innerText = '用户已注销';
                            document.getElementById('input-area').style.display = 'none';
                            document.getElementById('msg-box').innerHTML = '<div class="empty-chat">该用户已被注销</div>';
                            showToast('该用户已被管理员注销');
                        }
                    } else {
                        // 正常更新用户信息
                        if(cache.users[uid]) {
                            cache.users[uid].name = changedUser.name;
                            cache.users[uid].avatar_bg = changedUser.avatar_bg;
                        }
                        // 如果当前正在与该用户私聊，更新标题栏
                        if(target && target.type === 'private' && target.id === uid) {
                            document.getElementById('chat-t').innerText = getName(uid);
                        }
                        // 关键修复：如果当前聊天界面涉及该用户，立即刷新聊天消息中的用户信息
                        if(target) {
                            var needsRefresh = false;
                            // 检查是否是私聊对象
                            if(target.type === 'private' && target.id === uid) {
                                needsRefresh = true;
                            }
                            // 检查是否是群聊中的成员（当前聊天中可能有该用户发送的消息）
                            if(target.type === 'group') {
                                // 检查 currentChatMsgs 中是否有该用户的消息
                                for(var i = 0; i < currentChatMsgs.length; i++) {
                                    if(currentChatMsgs[i].from_uid === uid) {
                                        needsRefresh = true;
                                        break;
                                    }
                                }
                            }
                            // 如果需要刷新，重新渲染聊天界面（不滚动）
                            // 修复：如果刚发送消息，不要立即重新渲染，避免删除刚创建的时间戳元素
                            if(needsRefresh && !preventRenderChat) {
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
            if(d.changed_groups) {
                for(var gid in d.changed_groups) {
                    var changedGroup = d.changed_groups[gid];
                    if(cache.groups[gid]) {
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
                    if(target && target.type === 'group' && target.id === gid) {
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
            for(var uid in d.users) {
                if(!cache.users[uid]) {
                    cache.users[uid] = d.users[uid];
                } else {
                    // 保留已有的 _sidebar 信息
                    var existingSidebar = cache.users[uid]._sidebar;
                    var serverSidebar = d.users[uid]._sidebar;
                    // 保存本地的 unreadCount（由 UnreadManager 管理）
                    var localUnreadCount = existingSidebar ? existingSidebar.unreadCount : 0;
                    
                    cache.users[uid] = d.users[uid];
                    
                    // 合并 _sidebar，但保留本地的 unreadCount
                    if(serverSidebar) {
                        cache.users[uid]._sidebar = serverSidebar;
                        // 关键：保留本地的 unreadCount，取较大值（避免回退）
                        var serverUnread = serverSidebar.unreadCount || 0;
                        cache.users[uid]._sidebar.unreadCount = Math.max(localUnreadCount, serverUnread);
                    } else if(existingSidebar) {
                        cache.users[uid]._sidebar = existingSidebar;
                    }
                }
            }
            
            // ============ 合并群组数据，保留 _sidebar 信息 ============
            // 关键修复：unreadCount 由 UnreadManager 统一管理，不被服务端覆盖
            for(var gid in d.groups) {
                if(!cache.groups[gid]) {
                    cache.groups[gid] = d.groups[gid];
                } else {
                    var existingSidebar = cache.groups[gid]._sidebar;
                    var serverSidebar = d.groups[gid]._sidebar;
                    // 保存本地的 unreadCount（由 UnreadManager 管理）
                    var localUnreadCount = existingSidebar ? existingSidebar.unreadCount : 0;
                    
                    cache.groups[gid] = d.groups[gid];
                    
                    // 合并 _sidebar，但保留本地的 unreadCount
                    if(serverSidebar) {
                        cache.groups[gid]._sidebar = serverSidebar;
                        // 关键：保留本地的 unreadCount，取较大值（避免回退）
                        var serverUnread = serverSidebar.unreadCount || 0;
                        cache.groups[gid]._sidebar.unreadCount = Math.max(localUnreadCount, serverUnread);
                    } else if(existingSidebar) {
                        cache.groups[gid]._sidebar = existingSidebar;
                    }
                }
            }
            // 清理已不存在的群组
            for(var gid in cache.groups) {
                if(!d.groups[gid]) delete cache.groups[gid];
            }
            
            cache.remarks = d.remarks || {};

            // ============ 重构：委托 UnreadManager 处理 read_markers 同步 ============
            if (d.read_markers) {
                UnreadManager.syncFromServer(d);
            }

            if (d.recalled_ids && d.recalled_ids.length > 0) {
                d.recalled_ids.forEach(function(rid) {
                    // SQLite 修复：将撤回 ID 统一转换为 String 后处理
                    handleMessageRecall(String(rid));
                });
            }

            var needsRender = false;
            var currentChatNewMsgs = [];  // 用于追踪当前聊天的新消息
            
            if(d.messages && d.messages.length){ 
                d.messages.forEach(m => {
                    // SQLite 修复：确保消息 ID 是数字类型进行比较
                    var msgId = Number(m.id) || 0;
                    if(msgId > lastId){
                        // ============ 更新侧边栏预览数据 ============
                        updateSidebarPreview(m);
                        
                        // ============ 处理当前聊天的消息 ============
                        if(target && activeChatLoaded && isMsgBelongsToChat(m, target)) {
                            // ========== 修复：跳转模式下的新消息处理 ==========
                            // 如果处于跳转模式，且新消息 ID 大于当前视图的 maxMsgId
                            // 则设置 hasNewerMessages 标志，但不立即渲染
                            if(isInJumpMode && m.id > maxMsgId) {
                                hasNewerMessages = true;
                                // 更新侧边栏，但不添加到 currentChatMsgs
                                // 用户向下滚动时会加载这些新消息
                            } else {
                                // 正常模式：正常处理新消息
                                // 检查是否是临时消息的确认
                                var tmpIdx = -1;
                                for(var i=0; i<currentChatMsgs.length; i++) { 
                                    if(currentChatMsgs[i].tmp && currentChatMsgs[i].content === m.content) { 
                                        tmpIdx=i; break; 
                                    } 
                                }
                                // SQLite 修复：使用安全 ID 比较函数
                                var existsIdx = findMsgIndexById(currentChatMsgs, m.id);

                                if(existsIdx !== -1) {
                                    // 消息已存在，检测是否需要更新
                                    var oldMsg = currentChatMsgs[existsIdx];
                                    
                                    // 使用统一的检测函数判断是否需要更新 DOM
                                    if(shouldUpdateMessage(oldMsg, m)) {
                                        // 更新数据
                                        currentChatMsgs[existsIdx] = m;
                                        // 使用统一的 DOM 更新函数
                                        updateMessageInDOM(m.id, m, true);
                                    } else {
                                        // 无需更新 DOM，但仍更新数据
                                        currentChatMsgs[existsIdx] = m;
                                    }
                                } else if(tmpIdx !== -1) {
                                    // 替换临时消息
                                    var tmpMsgId = currentChatMsgs[tmpIdx].id;
                                    var el = document.getElementById('msg-' + tmpMsgId);
                                    if(el) { 
                                        el.id = 'msg-' + m.id; 
                                        el.dataset.id = m.id; 
                                        var bub = el.querySelector('.msg-bub'); if(bub) bub.classList.remove('sending'); 
                                    }
                                    // 修复：同时更新时间戳元素的ID（如果存在）
                                    var oldTimeEl = document.getElementById('time-' + tmpMsgId);
                                    if(oldTimeEl) {
                                        oldTimeEl.id = 'time-' + m.id;
                                    }
                                    currentChatMsgs[tmpIdx] = m;
                                    // 更新 maxMsgId
                                    if(m.id > maxMsgId) {
                                        maxMsgId = m.id;
                                    }
                                } else {
                                    // 新消息，添加到当前聊天并渲染
                                    currentChatMsgs.push(m);
                                    currentChatNewMsgs.push(m);
                                    needsRender = true;
                                    // 更新 maxMsgId
                                    if(m.id > maxMsgId) {
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
            if(newLastId > lastId) {
                lastId = newLastId;
            }
            // 如果服务端返回的 serverSyncedId 更大（可能是其他聊天的消息），也要更新
            if(serverSyncedId > lastId) {
                lastId = serverSyncedId;
            }

            if(isFirstSync) isFirstSync = false;

            // 只在当前聊天中渲染新消息
            if(target && needsRender) { 
                const box = document.getElementById('msg-box');
                const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;

                // 使用优化的渲染方式（只渲染新消息）
                renderNewMessages();
                
                // 如果之前在底部，滚动到底部（使用健壮的滚动策略）
                if(wasAtBottom) {
                    scrollToBottomRobust();
                }
                
                if(wasAtBottom) {
                    markRead(); 
                }
            }
            if(target) updateReadStatusIndicators();

            // ============ P2P会话处理============
            if(d.p2p_sessions && p2pManager) {
                d.p2p_sessions.forEach(async function(session) {
                    // 处理接收方的会话
                    if(session.role === 'receiver') {
                        if(session.status === 'pending') {
                            // 待处理会话：显示传输请求
                            if(!p2pTransfers.has(session.session_id)) {
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
                                                avatar_bg: '#' + Math.floor(Math.random()*16777215).toString(16), // 随机颜色
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
                        } else if(session.status === 'active' || session.status === 'connecting') {
                            // 活跃会话：确保会话对象存在（只创建一次）
                            if(!p2pManager.activeSessions.has(session.session_id)) {
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
                    else if(session.role === 'sender') {
                        if(session.status === 'pending' || session.status === 'active' || session.status === 'connecting') {
                            const p2pSession = p2pManager.activeSessions.get(session.session_id);
                            
                            // 私聊：检测状态变化（pending -> connecting）
                            if(session.chat_type === 'private') {
                                // 检查是否需要更新UI状态
                                const currentTransfer = p2pTransfers.get(session.session_id);
                                const statusChanged = !currentTransfer || currentTransfer.status !== session.status;
                                
                                if(statusChanged && currentTransfer) {
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
                                if(session.status === 'connecting' && p2pSession) {
                                    if(!p2pSession.peerConnection) {
                                        logDebug('P2P', '🚀 Receiver accepted, starting WebRTC...');
                                        p2pSession.setupWebRTC().catch(err => {
                                            logError('P2P', '❌ Failed to setup WebRTC:', err);
                                        });
                                    }
                                } else if(session.status === 'connecting' && !p2pSession && !processedSessions.has(session.session_id)) {
                                    // 只对未处理过的会话记录一次警告
                                    logWarn('P2P', '⚠️ Session not in activeSessions (old session):', session.session_id);
                                    processedSessions.add(session.session_id);
                                }
                            }
                            
                            // 群聊：检查参与者状态变化
                            if(session.chat_type === 'group' && session.participants) {
                                if(p2pSession && p2pSession instanceof P2PGroupSession) {
                                    session.participants.forEach(function(participant) {
                                        // 检查是否有新接受的参与者
                                        if(participant.status === 'accepted' && !p2pSession.acceptedReceivers.has(participant.uid)) {
                                            logDebug('P2P', '🚀 Participant accepted:', participant.uid);
                                            p2pSession.onReceiverAccepted(participant.uid);
                                        }
                                    });
                                }
                            }
                            
                            // 更新跟踪信息
                            if(!p2pTransfers.has(session.session_id)) {
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
            if(d.p2p_signals && d.p2p_signals.length > 0 && p2pManager) {
                logDebug('P2P', '📨 Received', d.p2p_signals.length, 'signals');
                d.p2p_signals.forEach(async function(signal) {
                    const session = p2pManager.activeSessions.get(signal.session_id);
                    if(session) {
                        logDebug('P2P', '📨', signal.signal_type);
                        await session.handleSignal(signal.signal_type, signal.signal_data);
                    }
                });
            }

            updateListUI(); updateContactUI();
            if(target && target.type === 'group' && !cache.groups[target.id] && target.id !== 'group_global'){ target = null; document.getElementById('chat-t').innerText = '群组已解散'; document.getElementById('input-area').style.display = 'none'; document.getElementById('btn-grp-set').style.display='none'; }
        } catch(e){
            logError('Sync', 'sync error:', e);
        }
        // 优化：减少轮询间隔以提高实时性
        pollingTimer = setTimeout(sync, 500);
    }

    function triggerInAppNotification(msg, chatId, type) {
        currentNotifChatId = { id: chatId, type: type, name: (type==='group' ? cache.groups[chatId].name : getName(chatId)) };
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
        notifTimer = setTimeout(function() {
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
        if(!box) return;
        
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
                        if(callback) callback();
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
        if(isInJumpMode) {
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
        if(!target || currentChatMsgs.length === 0) return;
        if (!chatId) chatId = target.id;
        
        var lastMsgIdInChat = msgId;
        if (!lastMsgIdInChat) {
            // 计算要标记已读的消息 ID
            // 群聊：标记该群的所有消息
            // 私聊：只标记对方发给我的消息
            // 特殊处理：与自己聊天时，标记所有自己发给自己的消息
            var relMsgs = [];
            for(var i=0; i<currentChatMsgs.length; i++) {
                var m = currentChatMsgs[i];
                if(target.type==='group') {
                    if(m.to_uid===chatId) {
                        relMsgs.push(m);
                    }
                } else if(chatId === me.uid) {
                    if(m.from_uid === me.uid && m.to_uid === me.uid) {
                        relMsgs.push(m);
                    }
                } else {
                    if(m.from_uid===chatId && m.to_uid===me.uid) {
                        relMsgs.push(m);
                    }
                }
            }
            if(relMsgs.length > 0) lastMsgIdInChat = relMsgs[relMsgs.length - 1].id;
        }
        if (!lastMsgIdInChat) return;
        
        // 委托 UnreadManager 处理（包括乐观更新 + 后端同步 + UI 更新）
        await UnreadManager.markAsRead(chatId, target.type, lastMsgIdInChat);
    }

    function updateReadStatusIndicators() {
        if(!target || target.type !== 'private') return;
        
        // 特殊处理：与自己聊天时，显示已读状态
        if(target.id === me.uid) {
            var myReadId = 0;
            if (cache.read_markers && cache.read_markers[me.uid]) {
                myReadId = cache.read_markers[me.uid][me.uid] || 0;
            }
            
            var rows = document.querySelectorAll('.msg-row.me');
            rows.forEach(row => {
                var mid = parseInt(row.dataset.id);
                var stat = row.querySelector('.read-stat');
                if(stat) {
                    if(mid <= myReadId) {
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
            if(stat) {
                if(mid <= otherReadId) {
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
        if(!badge) return;
        
        // 严格的显示条件：
        // 1. 屏幕宽度 <= 768px (移动端)
        // 2. 用户处于聊天界面 (target 存在)
        // 3. body 有 mobile-chat-active 类
        var isMobile = window.innerWidth <= 768;
        var inChatView = target !== null;
        var isMobileChatActive = document.body.classList.contains('mobile-chat-active');
        
        // 如果不满足基本条件，强制隐藏
        if(!isMobile || !inChatView || !isMobileChatActive) {
            badge.classList.remove('show');
            return;
        }
        
        // 统计除当前聊天外的所有未读消息
        var totalUnread = 0;
        
        // 遍历所有群聊
        for(var gid in cache.groups) {
            if(gid !== target.id) {
                totalUnread += getUnreadCount(gid, 'group');
            }
        }
        
        // 遍历所有私聊（从 _sidebar 获取）
        for(var uid in cache.users) {
            var u = cache.users[uid];
            if(u._sidebar && u._sidebar.lastMsgTime && uid !== target.id) {
                totalUnread += getUnreadCount(uid, 'private');
            }
        }
        
        // 更新气泡显示
        if(totalUnread > 0) {
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

        var timeStr = (d.getHours()<10?'0':'')+d.getHours() + ':' + (d.getMinutes()<10?'0':'')+d.getMinutes();

        if (isToday) return timeStr;
        if (isYesterday) return '昨天 ' + timeStr;
        if (d.getFullYear() === now.getFullYear()) return (d.getMonth()+1)+'月'+d.getDate()+'日 ' + timeStr;
        return d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日 ' + timeStr;
    }

    function updateListUI() {
        var listItems = [];
        // ============ 从 _sidebar 读取群聊预览 ============
        for(var gid in cache.groups) {
            var g = cache.groups[gid];
            var sidebar = g._sidebar || {};
            var ts = sidebar.lastMsgTime || 0;
            var lastText = sidebar.lastMsgPreview || '';
            listItems.push({ id: gid, type: 'group', name: g.name, ts: ts, pinned: cache.pinned[gid] ? 1 : 0, lastText: lastText, html: '', obj: g });
        }
        // ============ 从 _sidebar 读取私聊预览 ============
        // 不再遍历消息数组，而是遍历所有有 _sidebar 数据的用户
        for(var uid in cache.users) {
            var u = cache.users[uid];
            if(u._sidebar && u._sidebar.lastMsgTime) {
                var sidebar = u._sidebar;
                var ts = sidebar.lastMsgTime || 0;
                var lastText = sidebar.lastMsgPreview || '';
                listItems.push({ id: uid, type: 'private', name: getName(uid), ts: ts, pinned: cache.pinned[uid] ? 1 : 0, lastText: lastText, html: '', obj: u });
            }
        }
        listItems.sort(function(a, b) { if (a.pinned !== b.pinned) return b.pinned - a.pinned; return b.ts - a.ts; });
        var renderItems = [];
        listItems.forEach(function(item) {
            var act = (target && target.id===item.id) ? 'active' : '';
            var pinCls = item.pinned ? 'pinned' : '';
            var unread = getUnreadCount(item.id, item.type);
            var badge = (unread > 0 && act === '') ? '<div class="unread-badge">' + (unread > 99 ? '99+' : unread) + '</div>' : '';
            var timeStr = formatListTime(item.ts);
            var avHtml = item.type === 'group' ? '<div class="item-av" style="background:#007aff">' + item.name[0] + '</div>' : '<div class="item-av" style="background:' + item.obj.avatar_bg + '"></div>';
            var html = avHtml + '<div class="item-body"><div class="item-top"><div class="item-t">' + item.name + '</div><div class="item-time">' + timeStr + '</div></div><div class="item-btm"><div class="item-d">' + item.lastText + '</div>' + badge + '</div></div>';
            renderItems.push({ id: item.id, cls: 'list-item clickable ' + act + ' ' + pinCls, click: (function(id, type, name){ return function(){ switchChat(id, type, name) } })(item.id, item.type, item.name), context: (function(id){ return function(e){ handleListContextMenu(e, id) } })(item.id), html: html });
        });
        applyDiff(document.getElementById('ls-msg'), renderItems);
        
        // 更新移动端未读消息气泡
        updateMobileUnreadBadge();
    }

   function updateContactUI() {
        var items = [];
        items.push({ id: 'h-grp', cls: '', html: '<div style="font-size:12px;color:#888;margin:10px 0 5px 5px;">群组</div>', click: null });
        for(var gid in cache.groups) {
             items.push({ id: 'c-' + gid, cls: 'list-item clickable', click: (function(id, n){ return function(){switchChat(id, 'group', n)} })(gid, cache.groups[gid].name), html: '<div class="item-av" style="background:#007aff">' + cache.groups[gid].name[0] + '</div><div class="item-body"><div class="item-t">' + cache.groups[gid].name + '</div></div>' });
        }
        
        // 添加"我自己"选项，允许用户向自己发起私聊
        items.push({ id: 'h-self', cls: '', html: '<div style="font-size:12px;color:#888;margin:15px 0 5px 5px;">我自己</div>', click: null });
        var myBg = cache.users[me.uid] ? (cache.users[me.uid].avatar_bg || '#ccc') : '#ccc';
        var mySelfHtml = '<div class="item-av" style="background:' + myBg + '"></div><div class="item-body"><div class="item-t">' + getName(me.uid) + '</div><div class="item-d">与自己的聊天</div></div>';
        items.push({ id: 'c-' + me.uid, cls: 'list-item clickable', click: (function(id, n){ return function(){switchChat(id, 'private', n)} })(me.uid, getName(me.uid)), context: (function(id){ return function(e){ handleListContextMenu(e, id) } })(me.uid), html: mySelfHtml });
        
        items.push({ id: 'h-usr', cls: '', html: '<div style="font-size:12px;color:#888;margin:15px 0 5px 5px;">在线好友</div>', click: null });
        for(var uid in cache.users){ 
            if(uid!==me.uid && cache.users[uid].status==='online') {
                 var uBg = cache.users[uid].avatar_bg || '#ccc';
                 var htmlStr = '<div class="item-av" style="background:' + uBg + '"></div><div class="item-body"><div class="item-t">' + getName(uid) + '</div><div class="item-d">在线</div></div>';
                 items.push({ id: 'c-' + uid, cls: 'list-item clickable', click: (function(id, n){ return function(){switchChat(id, 'private', n)} })(uid, getName(uid)), context: (function(id){ return function(e){ handleListContextMenu(e, id) } })(uid), html: htmlStr });
            }
        }
        applyDiff(document.getElementById('ls-con'), items);
    }

    // ============ 重构：从 _sidebar 读取最后消息信息 ============
    function getLastMsgInfo(tid, type){ 
        if(type === 'group') {
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
                if(sys.from_uid === me.uid) fromName = '你';
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
        } catch(e) {}
        return m.content; 
    }

    function fmt(m){ 
        if(m.type === 'system') return '[系统消息]'; 
        if(m.is_recalled) return '[已撤回]';
        if(m.content && m.content.startsWith('{"type":"merge_fwd"')) return '[聊天记录]'; 
        if(m.type === 'sticker') return '[表情]';
        return m.type==='file'?'[文件]':m.content; 
    }

    function applyDiff(container, items) {
        var children = Array.from(container.children); children.forEach(el => { var exists = false; for(var i=0; i<items.length; i++) { if(items[i].id === el.dataset.id) { exists=true; break; } } if(!exists) el.remove(); });
        items.forEach((item, index) => {
            var el = container.querySelector('[data-id="' + item.id + '"]');
            if (!el) { el = document.createElement('div'); el.dataset.id = item.id; el.className = item.cls || 'list-item clickable'; el.onclick = item.click; if(item.context) { el.oncontextmenu = item.context; let timer; el.ontouchstart = function(e) { timer = setTimeout(function(){ item.context(e); }, 600); }; el.ontouchend = function() { clearTimeout(timer); }; el.ontouchmove = function() { clearTimeout(timer); }; } el.innerHTML = item.html; if (index >= container.children.length) container.appendChild(el); else container.insertBefore(el, container.children[index]); } 
            else { if (index < container.children.length && container.children[index] !== el) container.insertBefore(el, container.children[index]); if(item.cls && el.className !== item.cls) el.className = item.cls; if(el.innerHTML !== item.html) el.innerHTML = item.html; el.onclick = item.click; if(item.context) el.oncontextmenu = item.context; }
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
        if(!x && x!==0) { x = window.innerWidth/2; y=window.innerHeight/2; } 
        menu.style.left = x + 'px'; menu.style.top = y + 'px'; menu.style.display = 'flex'; 
        document.addEventListener('click', closeListCtx, {once:true}); 
    }
    function closeListCtx() { document.getElementById('list-ctx-menu').style.display = 'none'; }

    function listMenuAction(act) { 
        if(act === 'pin' && listCtxTargetId) { 
            if(cache.pinned[listCtxTargetId]) delete cache.pinned[listCtxTargetId]; else cache.pinned[listCtxTargetId] = 1; localStorage.setItem('qq_pinned', JSON.stringify(cache.pinned)); updateListUI(); 
        } else if (act === 'remark' && listCtxTargetId) {
            openProfile(listCtxTargetId);
        }
        closeListCtx(); 
    }

    function switchChat(id, type, name){ 
        // 在移动端模式下，即使是同一个聊天，也允许重新打开（修复响应式切换问题）
        if(target && target.id === id && window.innerWidth > 768) return; 
        target = {id: id, type: type, name: name}; 
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
        } catch(e) {
            logWarn('Session', '保存会话状态失败:', e);
        }

        if(window.innerWidth <= 768) document.body.classList.add('mobile-chat-active'); 
        document.getElementById('chat-t').innerText = name; 
        document.getElementById('input-area').style.display = 'block'; 
        var btn = document.getElementById('btn-grp-set'); 
        if(type === 'group'){ 
            var g = cache.groups[id]; 
            document.getElementById('chat-s').innerText = g ? g.members.length + ' 人' : ''; 
            if(g && !g.system && g.owner === me.uid) btn.style.display = 'flex'; else btn.style.display = 'none'; 
        } else { 
            var u = cache.users[id]; 
            document.getElementById('chat-s').innerHTML = (u && u.status==='online') ? '<div class="dot"></div> 在线' : '离线'; 
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
        if(!target || !me) return;
        
        const chatId = target.id;
        const chatType = target.type;
        
        try {
            // 调用历史消息API，before_id=0表示获取最新的
            const url = `/api/history?uid=${encodeURIComponent(me.uid)}&chat_id=${encodeURIComponent(chatId)}&chat_type=${chatType}&limit=${LAZY_LOAD_CONFIG.initialLoadCount}`;
            const r = await fetch(url);
            
            if(r.status === 403) {
                const errData = await r.json();
                if(errData.error === 'session_invalidated') {
                    alert(errData.message || '您的账户已被禁用，请重新登录');
                    localStorage.removeItem('qq_uid');
                    location.reload();
                    return;
                }
            }
            
            const data = await r.json();
            const box = document.getElementById('msg-box');
            
            if(target.id !== chatId) return; // 用户已切换聊天
            
            // 更新懒加载状态
            LAZY_LOAD_CONFIG.hasMoreHistory[chatId] = data.has_more;
            if(data.messages.length > 0) {
                LAZY_LOAD_CONFIG.oldestMsgId[chatId] = data.messages[0].id;
            }
            
            // 将消息存储到当前聊天数组（不再使用全局 cache.msgs）
            currentChatMsgs = data.messages.slice();  // 复制数组
            
            // 设置消息ID追踪变量
            if(data.messages.length > 0) {
                minMsgId = data.messages[0].id;  // 第一条是最旧的
                maxMsgId = data.messages[data.messages.length - 1].id;  // 最后一条是最新的
            }
            
            // 标记当前聊天已完成初始加载
            activeChatLoaded = true;
            
            // 清空加载提示
            box.innerHTML = '';
            
            // 渲染所有消息（包括P2P消息）
            if(data.messages.length > 0) {
                renderHistoryMessages(data.messages, false);
                // 滚动到底部（使用健壮的滚动策略）
                scrollToBottomRobust();
            } else {
                box.innerHTML = '<div class="empty">暂无消息</div>';
            }
            
            LAZY_LOAD_CONFIG.isInitialLoad = false;
            
            // 标记已读
            setTimeout(() => { markRead(); }, 100);
            
        } catch(e) {
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
        if(!target || !me) return;
        if(LAZY_LOAD_CONFIG.isLoadingHistory) return;
        
        const chatId = target.id;
        const chatType = target.type;
        
        // 检查是否还有更多历史
        if(LAZY_LOAD_CONFIG.hasMoreHistory[chatId] === false) return;
        
        const oldestId = LAZY_LOAD_CONFIG.oldestMsgId[chatId];
        if(!oldestId) return;
        
        // 节流检查：防止快速滚动时重复请求
        const now = Date.now();
        if(now - LAZY_LOAD_CONFIG.lastFetchTime < LAZY_LOAD_CONFIG.minTimeBetweenFetches) {
            return;
        }
        
        LAZY_LOAD_CONFIG.isLoadingHistory = true;
        LAZY_LOAD_CONFIG.isSilentLoading = silent;
        LAZY_LOAD_CONFIG.lastFetchTime = now;
        
        const box = document.getElementById('msg-box');
        let loadingIndicator = null;
        
        // 只有非静默模式才显示加载提示
        if(!silent) {
            loadingIndicator = document.getElementById('history-loading-top');
            if(!loadingIndicator) {
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
                
                if(target.id !== chatId) {
                    LAZY_LOAD_CONFIG.isLoadingHistory = false;
                    LAZY_LOAD_CONFIG.isSilentLoading = false;
                    LAZY_LOAD_CONFIG.pendingPrefetch = null;
                    return;
                }
                
                // 移除加载提示（如果存在）
                loadingIndicator = document.getElementById('history-loading-top');
                if(loadingIndicator) loadingIndicator.remove();
                
                if(data.messages.length === 0) {
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
                if(data.messages.length > 0) {
                    minMsgId = data.messages[0].id;
                }
                
                // 将消息添加到当前聊天数组头部
                data.messages.forEach(m => {
                    if(!currentChatMsgs.find(x => x.id === m.id)) {
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
                    if(finalScrollHeight !== newScrollHeight) {
                        // 如果高度变化了（图片加载等），重新计算
                        box.scrollTop = oldScrollTop + (finalScrollHeight - oldScrollHeight);
                    }
                    lastScrollTop = box.scrollTop;
                });
                
            } catch(e) {
                logError('History', '加载更多历史失败:', e);
                const li = document.getElementById('history-loading-top');
                if(li) li.remove();
            }
            
            LAZY_LOAD_CONFIG.isLoadingHistory = false;
            LAZY_LOAD_CONFIG.isSilentLoading = false;
            LAZY_LOAD_CONFIG.pendingPrefetch = null;
        })();
        
        // 如果是静默加载，保存Promise引用
        if(silent) {
            LAZY_LOAD_CONFIG.pendingPrefetch = prefetchPromise;
        }
        
        return prefetchPromise;
    }
    
    /**
     * 显示加载指示器（当用户滚动到顶部且静默加载未完成时）
     */
    function showLoadingSpinner() {
        const box = document.getElementById('msg-box');
        if(!box) return;
        
        let loadingIndicator = document.getElementById('history-loading-top');
        if(!loadingIndicator && LAZY_LOAD_CONFIG.isLoadingHistory) {
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
        if(!target || !me) return;
        if(!isInJumpMode) return;  // 只有在跳转模式下才需要向下加载
        if(isLoadingNewer) return;
        if(!hasNewerMessages) return;
        
        const chatId = target.id;
        const chatType = target.type;
        
        if(maxMsgId === 0) return;
        
        isLoadingNewer = true;
        
        // 显示加载提示
        const box = document.getElementById('msg-box');
        let loadingIndicator = document.getElementById('history-loading-bottom');
        if(!loadingIndicator) {
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
            
            if(target.id !== chatId) {
                isLoadingNewer = false;
                return;
            }
            
            // 移除加载提示
            loadingIndicator = document.getElementById('history-loading-bottom');
            if(loadingIndicator) loadingIndicator.remove();
            
            if(data.messages.length === 0) {
                hasNewerMessages = false;
                isLoadingNewer = false;
                // 退出跳转模式
                isInJumpMode = false;
                return;
            }
            
            // 更新状态
            hasNewerMessages = data.has_newer || false;
            
            // 更新 maxMsgId
            if(data.messages.length > 0) {
                maxMsgId = data.messages[data.messages.length - 1].id;
            }
            
            // 将消息添加到当前聊天数组尾部
            data.messages.forEach(m => {
                if(!currentChatMsgs.find(x => x.id === m.id)) {
                    currentChatMsgs.push(m);
                }
            });
            
            // 渲染新消息到底部
            renderHistoryMessages(data.messages, false);
            
            // 如果没有更新的消息了，退出跳转模式
            if(!hasNewerMessages) {
                isInJumpMode = false;
            }
            
        } catch(e) {
            logError('History', '加载更新消息失败:', e);
            const li = document.getElementById('history-loading-bottom');
            if(li) li.remove();
        }
        
        isLoadingNewer = false;
    }
    
    /**
     * 跳转模式下的“返回最新消息”功能
     */
    async function returnToLatest() {
        if(!target || !me) return;
        
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
        if(!target || messages.length === 0) return;
        
        const box = document.getElementById('msg-box');
        const fragment = document.createDocumentFragment();
        let lastTime = 0;
        
        // 如果是prepend，需要获取当前第一条消息的时间戳作为参考
        if(prepend) {
            const firstExisting = box.querySelector('.msg-row');
            if(firstExisting && firstExisting.dataset.id) {
                // SQLite 修复：使用安全 ID 比较函数
                const existingMsg = findMsgById(currentChatMsgs, firstExisting.dataset.id);
                if(existingMsg) {
                    // 不需要设置，lastTime保持为0，让新消息依然显示时间
                }
            }
        }
        
        // 跟踪已创建的时间戳元素ID，避免在同一个fragment中重复创建
        const createdTimeIds = new Set();
        
        messages.forEach((m, idx) => {
            // 跳过已存在的DOM元素
            // 类型安全：确保 ID 为 String 格式
            if(document.getElementById('msg-' + safeId(m.id))) return;
            
            // 时间分隔符
            const msgTime = m.timestamp;
            if(msgTime - lastTime > 300) {
                const tDivId = 'time-' + m.id;
                // 检查DOM和当前fragment中是否已存在
                if(!document.getElementById(tDivId) && !createdTimeIds.has(tDivId)) {
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
            if(m.type === 'system' || m.is_recalled) {
                div = renderSystemMsg(m);
            } else {
                div = renderMessageElement(m, false);
            }
            fragment.appendChild(div);
        });
        
        if(prepend) {
            // 插入到顶部
            box.insertBefore(fragment, box.firstChild);
        } else {
            box.appendChild(fragment);
        }
        
        // 为新渲染的GIF启动懒加载观察
        if(gifObserver) {
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
        if(!box) return;
        
        let scrollTimeout = null;
        let isScrolling = false;
        
        // 使用passive监听器提高滚动性能
        box.addEventListener('scroll', function() {
            isScrolling = true;
            
            // 节流处理：使用requestAnimationFrame代替setTimeout获得更平滑的体验
            if(scrollTimeout) cancelAnimationFrame(scrollTimeout);
            
            scrollTimeout = requestAnimationFrame(() => {
                const scrollTop = box.scrollTop;
                const scrollHeight = box.scrollHeight;
                const clientHeight = box.clientHeight;
                const distanceToBottom = scrollHeight - scrollTop - clientHeight;
                const distanceToTop = scrollTop;
                
                // ==================== 向上滚动预加载逻辑 ====================
                // 检查是否进入预加载区域（距离顶部 800px）
                if(distanceToTop < LAZY_LOAD_CONFIG.loadThreshold) {
                    // 检查是否有更多历史
                    const chatId = target ? target.id : null;
                    const hasMore = chatId && LAZY_LOAD_CONFIG.hasMoreHistory[chatId] !== false;
                    
                    if(hasMore) {
                        if(distanceToTop === 0) {
                            // 已经滚动到绝对顶部
                            if(LAZY_LOAD_CONFIG.isLoadingHistory && LAZY_LOAD_CONFIG.isSilentLoading) {
                                // 静默加载还在进行中，显示spinner
                                showLoadingSpinner();
                            } else if(!LAZY_LOAD_CONFIG.isLoadingHistory) {
                                // 没有在加载，立即触发显式加载（显示spinner）
                                loadMoreHistory(false);
                            }
                        } else {
                            // 在触发区域内但未到顶部，触发静默预加载
                            if(!LAZY_LOAD_CONFIG.isLoadingHistory) {
                                loadMoreHistory(true);  // 静默加载，不显示spinner
                            }
                        }
                    }
                }
                
                // ==================== 向下滚动加载逻辑（跳转模式） ====================
                if(distanceToBottom < LAZY_LOAD_CONFIG.loadThresholdBottom && isInJumpMode && hasNewerMessages) {
                    loadMoreNewer();
                }
                
                // ==================== 更新浮动按钮状态 ====================
                const isBottom = distanceToBottom < 50;
                if(isBottom) {
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
            if(m.from_uid === me.uid) nick = '你';
            txt = nick + " 撤回了一条消息";
        } else {
            txt = getSysText(m);
        }

        div.innerHTML = '<div class="msg-bub">'+txt+'</div>';
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
        switch(status) {
            case 'pending':
                statusHTML = '<div class="p2p-status">⏳ 等待对方响应...</div>';
                if(m.from_uid === me.uid) {
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
                statusHTML += '<div class="p2p-progress-bar"><div class="p2p-progress-fill" style="width:'+progress+'%"></div></div>';
                statusHTML += '<div class="p2p-progress-info">';
                statusHTML += '<span>'+progress.toFixed(1)+'%</span>';
                statusHTML += '<span>'+formatSpeed(speed)+'</span>';
                statusHTML += '</div></div>';
                actionsHTML = '<button class="p2p-btn cancel-btn" onclick="cancelP2PTransfer(\\''+sessionId+'\\', event)">取消</button>';
                break;
            case 'completed':
                fileIcon = '✅';
                statusHTML = '<div class="p2p-status success">✓ 传输完成</div>';
                if(m.server_filename) {
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
        
        return '<div class="msg-bub p2p-transfer-message" data-p2p-session="'+sessionId+'">' +
            '<div class="p2p-file-info">' +
            '<div class="p2p-file-icon">'+fileIcon+'</div>' +
            '<div class="p2p-file-details">' +
            '<div class="p2p-file-name">'+m.filename+'</div>' +
            '<div class="p2p-file-size">'+formatFileSize(m.size)+'</div>' +
            '<div class="p2p-method">P2P传输</div>' +
            '</div>' +
            '</div>' +
            statusHTML +
            (actionsHTML ? '<div class="p2p-actions">'+actionsHTML+'</div>' : '') +
            '</div>';
    }
    
    // 渲染单条消息的DOM元素
    function renderMessageElement(m, animate) {
        var u = cache.users[m.from_uid];
        if (!u) u = {name:'?', avatar_bg:'#ccc'};

        var displayName = getName(m.from_uid);
        var isMe = m.from_uid === me.uid;
        var animClass = (visualOn && animate) ? (isMe ? 'anim-in-right' : 'anim-in-left') : '';
        var div = document.createElement('div');
        div.id = 'msg-' + m.id;
        div.dataset.id = m.id;
        div.dataset.timestamp = m.timestamp;  // 添加时间戳属性，用于P2P消息排序 

        var chkCls = selMsgs.has(m.id.toString()) ? 'checked' : '';
        var chk = '<div class="msg-chk '+chkCls+'" onclick="toggleSel(\\''+m.id+'\\', event)"></div>';

        var quoteHtml = '';
        if(m.quote) {
            var qContent = m.quote.content;
            if(m.quote.is_recalled) qContent = '<span class="quote-recalled">原消息已被撤回</span>';
            var qJumpAttr = m.quote.id && !m.quote.is_recalled ? 'onclick="jumpToMsg(\\''+m.quote.id+'\\', event)"' : '';
            quoteHtml = '<div class="quote-box" '+qJumpAttr+'><div class="q-name">'+getName(m.quote.name ? 'unknown' : 'unknown')+':</div><div class="q-txt">'+qContent+'</div></div>'; 
            if(m.quote.name) quoteHtml = '<div class="quote-box" '+qJumpAttr+'><div class="q-name">'+m.quote.name+':</div><div class="q-txt">'+qContent+'</div></div>';
        }
        var c = '';
        if (m.content && m.content.startsWith('{"type":"merge_fwd"')) {
            try {
                var fwd = JSON.parse(m.content);
                c = '<div class="fwd-card" onclick="viewFwd(this)" data-fwd-json="'+m.content.replace(/"/g, '&quot;')+'"><div class="fwd-head">' + fwd.title + '</div><div class="fwd-body">';
                fwd.preview.forEach(function(p){ c += '<div class="fwd-row">' + p + '</div>'; });
                c += '</div><div class="fwd-foot">查看' + fwd.list.length + '条转发消息</div></div>'; 
            } catch(e) { c = '<div class="msg-bub">[转发消息解析失败]</div>'; }
        } else {
            if (m.type === 'sticker') {
                var stickerHtml = '';
                var emoji = m.content;
                var data = useTelegramStickers ? telegramStickerMapping[emoji] : null;

                if (data && data.file) {
                    stickerHtml = '<img class="sticker-gif msg-sticker-gif" data-src="/static/telegram_stickers/'+data.file+'" alt="'+emoji+'" title="'+emoji+'" style="width:80px;height:80px;">';
                } else {
                    stickerHtml = emojiToImg(emoji);
                }
                c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
            } else if (m.type === 'text' && emojiMapping[m.content]) {
                var emoji = m.content;
                var stickerHtml = emojiToImg(emoji);
                c = '<div class="msg-bub transparent-bub"><div class="msg-sticker">' + stickerHtml + '</div></div>';
            } else if(m.type==='file'){ 
                // 检查是否是P2P传输消息
                if(m.transfer_method === 'p2p') {
                    c = renderP2PFileMessage(m);
                } else {
                    // 普通文件消息
                    if(m.is_img) { 
                        c = '<div class="msg-bub transparent-bub"><img class="chat-img" src="/uploads/'+m.server_filename+'" onclick="viewImg(this.src)"></div>'; 
                    } 
                    else { c = '<div class="msg-bub file-card clickable" onclick="downloadFile(\\'' + m.server_filename + '\\', \\'' + m.filename + '\\')"><div class="file-icon" style="margin-right:10px">📄</div><div><div>'+m.filename+'</div><div style="font-size:10px;opacity:0.7">点击下载</div></div></div>'; } 
                }
            } else {
                c = '<div class="msg-bub ' + (m.tmp?'sending':'') + '">'+quoteHtml+m.content+'</div>';
            }
        }

        var readHtml = '<div class="read-stat">未读</div>';
        if (target.type === 'group') readHtml = ''; 

        var dblClickAttr = (m.from_uid !== me.uid) ? 'ondblclick="doNudge(\\''+m.from_uid+'\\')"' : '';
        div.className = 'msg-row ' + (isMe?'me':'') + ' ' + animClass;
        div.innerHTML = chk + '<div class="msg-inner"><div class="msg-av" style="background:'+u.avatar_bg+'" '+dblClickAttr+'></div><div><div class="msg-name">'+displayName+'</div>'+c+'</div>'+readHtml+'</div>';

        if(isMulti && !m.is_recalled) { div.onclick = function(e) { toggleSel(m.id, e); }; }
        if(animClass) { setTimeout(function(){ div.classList.remove('anim-in-right', 'anim-in-left'); }, 500); }
        
        return div;
    }

    function renderChat(forceScroll, animate){
        if(!target) return;
        var box = document.getElementById('msg-box');
        // 重构：使用 currentChatMsgs 而不是 cache.msgs
        var rel = currentChatMsgs.slice();  // 复制数组
        if(rel.length===0) { box.innerHTML='<div class="empty">暂无消息</div>'; return; }
        var emptyEl = box.querySelector('.empty'); if(emptyEl) emptyEl.remove();
        
        // 优化渲染：使用DocumentFragment批量添加元素减少DOM重排
        var fragment = document.createDocumentFragment();
        var hasNewElements = false;
        
        // 跟踪已创建的时间戳元素ID，避免在同一个fragment中重复创建
        var createdTimeIds = new Set();
        
        // 修复：从最后一条已渲染消息的时间戳开始，避免重复显示时间戳
        var lastTime = 0;
        // 直接从DOM中获取最后一条消息的时间戳，避免ID不一致问题
        var lastMsgEl = box.querySelector('.msg-row:last-of-type');
        if(lastMsgEl && lastMsgEl.dataset.timestamp) {
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
                    if(div.innerHTML !== sysRow.innerHTML) div.innerHTML = sysRow.innerHTML;
                    if(div.className !== sysRow.className) div.className = sysRow.className;
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
                    if(div) {
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

            if(!div) {
                var u = cache.users[m.from_uid];
                if (!u) u = {name:'?', avatar_bg:'#ccc'};

                var displayName = getName(m.from_uid);
                var isMe = m.from_uid===me.uid;
                var animClass = (visualOn && animate) ? (isMe ? 'anim-in-right' : 'anim-in-left') : '';
                div = document.createElement('div');
                div.id = divId;
                div.dataset.id = m.id;
                div.dataset.timestamp = m.timestamp;  // 添加时间戳属性，用于P2P消息排序 

                var chkCls = selMsgs.has(m.id.toString()) ? 'checked' : '';
                var chk = '<div class="msg-chk '+chkCls+'" onclick="toggleSel(\\''+m.id+'\\', event)"></div>';

                var quoteHtml = '';
                if(m.quote) {
                    var qContent = m.quote.content;
                    if(m.quote.is_recalled) qContent = '<span class="quote-recalled">原消息已被撤回</span>';
                    var qJumpAttr = m.quote.id && !m.quote.is_recalled ? 'onclick="jumpToMsg(\\''+m.quote.id+'\\', event)"' : '';
                    quoteHtml = '<div class="quote-box" '+qJumpAttr+'><div class="q-name">'+getName(m.quote.name ? 'unknown' : 'unknown')+':</div><div class="q-txt">'+qContent+'</div></div>'; 
                    if(m.quote.name) quoteHtml = '<div class="quote-box" '+qJumpAttr+'><div class="q-name">'+m.quote.name+':</div><div class="q-txt">'+qContent+'</div></div>';
                }
                var c = '';
                if (m.content && m.content.startsWith('{"type":"merge_fwd"')) {
                    try {
                        var fwd = JSON.parse(m.content);
                        c = '<div class="fwd-card" onclick="viewFwd(this)" data-fwd-json="'+m.content.replace(/"/g, '&quot;')+'"><div class="fwd-head">' + fwd.title + '</div><div class="fwd-body">';
                        fwd.preview.forEach(function(p){ c += '<div class="fwd-row">' + p + '</div>'; });
                        c += '</div><div class="fwd-foot">查看' + fwd.list.length + '条转发消息</div></div>'; 
                    } catch(e) { c = '<div class="msg-bub">[转发消息解析失败]</div>'; }
                } else {
                    if (m.type === 'sticker') {
                        var stickerHtml = '';
                        var emoji = m.content;
                        var data = useTelegramStickers ? telegramStickerMapping[emoji] : null;

                        if (data && data.file) {
                            // 使用Telegram GIF
                            stickerHtml = '<img class="sticker-gif msg-sticker-gif" data-src="/static/telegram_stickers/'+data.file+'" alt="'+emoji+'" title="'+emoji+'" style="width:80px;height:80px;">';
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
                    } else if(m.type==='file'){ 
                        if(m.is_img) { 
                            c = '<div class="msg-bub transparent-bub"><img class="chat-img" src="/uploads/'+m.server_filename+'" onclick="viewImg(this.src)"></div>'; 
                        } 
                        else { c = '<div class="msg-bub file-card clickable" onclick="downloadFile(\\'' + m.server_filename + '\\', \\'' + m.filename + '\\')"><div class="file-icon" style="margin-right:10px">📄</div><div><div>'+m.filename+'</div><div style="font-size:10px;opacity:0.7">点击下载</div></div></div>'; } 
                    } else {
                        c = '<div class="msg-bub ' + (m.tmp?'sending':'') + '">'+quoteHtml+m.content+'</div>';
                    }
                }

                var readHtml = '<div class="read-stat">未读</div>';
                if (target.type === 'group') readHtml = ''; 

                var dblClickAttr = (m.from_uid !== me.uid) ? 'ondblclick="doNudge(\\''+m.from_uid+'\\')"' : '';

                div.className = 'msg-row ' + (isMe?'me':'') + ' ' + animClass;
                div.innerHTML = chk + '<div class="msg-inner"><div class="msg-av" style="background:'+u.avatar_bg+'" '+dblClickAttr+'></div><div><div class="msg-name">'+displayName+'</div>'+c+'</div>'+readHtml+'</div>';

                if(isMulti && !m.is_recalled) { div.onclick = function(e) { toggleSel(m.id, e); }; }
                if(animClass) { setTimeout(function(){ div.classList.remove('anim-in-right', 'anim-in-left'); }, 500); }
                fragment.appendChild(div);
                hasNewElements = true;
            } else {
                // 修复：实时更新用户昵称
                var nameEl = div.querySelector('.msg-name');
                var curName = getName(m.from_uid);
                if(nameEl && nameEl.innerText !== curName) nameEl.innerText = curName;
                
                // 修复：实时更新用户头像
                var avEl = div.querySelector('.msg-av');
                if(avEl) {
                    var u = cache.users[m.from_uid];
                    if(u && u.avatar_bg) {
                        var currentBg = avEl.style.background;
                        var newBg = u.avatar_bg;
                        // 只有当头像背景发生变化时才更新
                        if(currentBg !== newBg) {
                            avEl.style.background = newBg;
                        }
                    }
                }

                if(isMulti && !m.is_recalled) {
                    div.onclick = isMulti ? function(e) { toggleSel(m.id, e); } : null;
                    var chk = div.querySelector('.msg-chk');
                    if(chk) { if(selMsgs.has(m.id.toString())) chk.classList.add('checked'); else chk.classList.remove('checked'); }
                }
            }
        });
        
        // 批量添加所有新元素，减少DOM重排
        if(hasNewElements) {
            box.appendChild(fragment);
        }
        
        if(forceScroll) {
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
        if(!target) return;
        
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
        if(lastRenderedElement && lastRenderedElement.dataset.timestamp) {
            lastTime = parseFloat(lastRenderedElement.dataset.timestamp);
        }
        
        // 只渲染新消息
        rel.forEach(m => {
            const divId = 'msg-' + m.id;
            const div = document.getElementById(divId);
            
            // 如果已经存在，更新lastTime后跳过
            if(div) {
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
        if(hasNewElements) {
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
        if(e) e.stopPropagation();
        
        // 第一步：尝试在当前 DOM 中查找
        var el = document.getElementById('msg-' + mid);
        if(el) {
            // 消息已在 DOM 中，直接滚动并高亮
            el.scrollIntoView({behavior: 'smooth', block: 'center'});
            el.classList.add('highlight');
            setTimeout(function(){ el.classList.remove('highlight'); }, 1500);
            return;
        }
        
        // 第二步：消息不在当前 DOM 中，需要加载上下文
        if(!target) {
            showToast('请先选择聊天');
            return;
        }
        
        try {
            const response = await fetch('/api/message/context?uid=' + me.uid + '&msg_id=' + mid);
            
            if(!response.ok) {
                const errData = await response.json();
                if(errData.error === 'Message not found') {
                    showToast('原消息已被删除');
                } else {
                    showToast('无法加载消息');
                }
                return;
            }
            
            const data = await response.json();
            
            if(!data.messages || data.messages.length === 0) {
                showToast('消息不存在');
                return;
            }
            
            // 第三步：替换当前聊天消息并重新渲染
            // 更新 currentChatMsgs
            currentChatMsgs = data.messages;
            
            // 更新 minMsgId 和 maxMsgId
            if(currentChatMsgs.length > 0) {
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
                    if(targetEl) {
                        targetEl.scrollIntoView({behavior: 'smooth', block: 'center'});
                        targetEl.classList.add('highlight');
                        setTimeout(function(){ targetEl.classList.remove('highlight'); }, 1500);
                    } else {
                        showToast('跳转失败');
                    }
                }, 100);
            });
            
        } catch(err) {
            logError('Message', '加载消息上下文失败:', err);
            showToast('加载失败，请重试');
        }
    }

    async function send(){
        var el = document.getElementById('inp-msg'); var t = el.value.trim(); if(!t || !target) return; 
        el.value=''; 
        // 修复：添加随机数确保临时ID唯一，避免快速连续发送时ID冲突
        var tmpId = Date.now() * 10000 + Math.floor(Math.random() * 10000); 
        var qContent = quoteMsg ? (quoteMsg.type==='file'?'[文件] '+quoteMsg.filename:quoteMsg.content) : '';
        if(qContent && qContent.startsWith('{"type":"merge_fwd"')) qContent = '[聊天记录]';
        if(quoteMsg && quoteMsg.is_recalled) qContent = '原消息已被撤回';
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
                method:'POST', 
                headers:{'Content-Type':'application/json'}, 
                body:JSON.stringify({uid:me.uid, to_uid:target.id, content:t, quote:quoteData}) 
            });
            const result = await response.json();
            
            if(result.msg_id) {
                // 用服务器返回的真实 ID 更新本地临时消息
                // 修复：先尝试通过tmpId查找，如果找不到（可能sync()已经更新了），则通过真实ID查找
                var tmpIdx = currentChatMsgs.findIndex(m => m.id === tmpId);
                if(tmpIdx === -1) {
                    // 可能sync()已经更新了ID，尝试通过真实ID查找
                    tmpIdx = currentChatMsgs.findIndex(m => m.id === result.msg_id);
                }
                
                if(tmpIdx !== -1) {
                    // 检查是否已经被sync()更新过
                    var alreadyUpdated = currentChatMsgs[tmpIdx].id === result.msg_id;
                    
                    if(!alreadyUpdated) {
                        currentChatMsgs[tmpIdx].id = result.msg_id;
                        currentChatMsgs[tmpIdx].tmp = false;
                        // 同时更新 DOM 元素的 id
                        var oldEl = document.getElementById('msg-' + tmpId);
                        if(oldEl) {
                            oldEl.id = 'msg-' + result.msg_id;
                            oldEl.dataset.id = result.msg_id;
                            var bub = oldEl.querySelector('.msg-bub');
                            if(bub) bub.classList.remove('sending');
                        }
                        // 修复：更新时间戳元素的ID（如果存在）
                        var oldTimeEl = document.getElementById('time-' + tmpId);
                        if(oldTimeEl) {
                            oldTimeEl.id = 'time-' + result.msg_id;
                        }
                    }
                    // 更新 maxMsgId
                    if(result.msg_id > maxMsgId) {
                        maxMsgId = result.msg_id;
                    }
                }
            }
        } catch(e) {
            logError('Message', '发送消息失败:', e);
        }
        
        // 修复：设置标志，防止在sync()时重新渲染导致时间戳元素被删除
        preventRenderChat = true;
        
        // 修复：当用户发送消息给自己时，立即标记为已读
        if(target.type === 'private' && target.id === me.uid) {
            // 延迟标记已读，确保消息已同步到服务器并获得真实ID
            if(pollingTimer) clearTimeout(pollingTimer);
            await sync();
            // 同步完成后立即标记已读
            setTimeout(() => {
                markRead();
                updateReadStatusIndicators();
            }, 100);
        } else {
            if(pollingTimer) clearTimeout(pollingTimer);
            sync();
        }
        
        // 修复：在sync()完成后才允许重新渲染
        setTimeout(() => {
            preventRenderChat = false;
        }, 500);  // 500ms后允许重新渲染
    }

    function openProfile(uid) {
        var u = cache.users[uid];
        if(!u) return;
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
        if(!val) delete cache.remarks[profileTargetUid];
        else cache.remarks[profileTargetUid] = val;
        if(target) {
            if(target.type === 'private' && target.id === profileTargetUid) {
                document.getElementById('chat-t').innerText = getName(profileTargetUid);
            }
            renderChat(false, false); 
        }
        updateListUI();
        updateContactUI();
        closeMd('md-profile');
        await fetch('/set_remark', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ uid: me.uid, target_uid: profileTargetUid, remark: val }) });
    }

    async function doNudge(targetUid) {
        if (!targetUid || targetUid === me.uid) return;
        showToast("戳了一下 " + getName(targetUid));
        var groupId = (target.type === 'group') ? target.id : null;
        await fetch('/nudge', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ uid: me.uid, target_uid: targetUid, group_id: groupId })
        });
        sync();
    }

    function setupContextMenu() { document.getElementById('msg-box').addEventListener('contextmenu', function(e) { handleContextMenu(e, 'main'); }); document.getElementById('fwd-content').addEventListener('contextmenu', function(e) { handleContextMenu(e, 'fwd'); }); document.addEventListener('click', function() { closeCtx(); }); }
    function handleContextMenu(e, mode) {
        if(isMulti && mode === 'main') return;
        var row = e.target.closest(mode === 'main' ? '.msg-row' : '.fwd-item'); if(!row) return;
        if (mode === 'main') { if(row.classList.contains('sys')) return; var mid = row.dataset.id; if(!mid) return; ctxMsg = findMsgById(currentChatMsgs, mid); ctxFwdData = null; } 
        else { ctxMsg = null; ctxFwdData = { content: row.dataset.content, type: row.dataset.type, filename: row.dataset.filename, sender: row.dataset.sender, id: row.id.replace('fwd-msg-', ''), quote: JSON.parse(row.dataset.quote || 'null'), is_recalled: row.dataset.isrecalled === 'true' }; }
        if(!ctxMsg && !ctxFwdData) return;
        e.preventDefault(); e.stopPropagation();
        var menu = document.getElementById('ctx-menu'); var recallBtn = document.getElementById('ctx-recall'); var recallLine = document.getElementById('ctx-recall-line'); var multiBtn = document.getElementById('ctx-multi'); var fwdBtn = document.getElementById('ctx-fwd'); var quoteBtn = document.getElementById('ctx-quote'); var rmkBtn = document.getElementById('ctx-remark');
        if (mode === 'fwd') { recallBtn.style.display = 'none'; recallLine.style.display = 'none'; multiBtn.style.display = 'none'; fwdBtn.style.display = 'flex'; quoteBtn.style.display = 'flex'; rmkBtn.style.display='none'; } 
        else { 
            multiBtn.style.display = 'flex'; fwdBtn.style.display = 'flex'; quoteBtn.style.display = 'flex'; 
            if(ctxMsg.from_uid !== me.uid && ctxMsg.from_uid !== 'system') rmkBtn.style.display = 'flex'; else rmkBtn.style.display='none';
            var isMe = ctxMsg.from_uid === me.uid; var isFresh = (Date.now()/1000 - ctxMsg.timestamp) < 120; if (isMe && !ctxMsg.is_recalled && isFresh) { recallBtn.style.display='flex'; recallLine.style.display='block'; } else { recallBtn.style.display='none'; recallLine.style.display='none'; } 
        }
        var x = e.clientX; var y = e.clientY; var w = menu.offsetWidth || 140; var h = menu.offsetHeight || 200; if (x + w > window.innerWidth) x = x - w; if (y + h > window.innerHeight) y = y - h; menu.style.left = x + 'px'; menu.style.top = y + 'px'; menu.style.display = 'flex';
    }
    function closeCtx() { document.getElementById('ctx-menu').style.display = 'none'; }
    function menuAction(act) {
        closeCtx(); var item = ctxMsg || ctxFwdData; if (!item) return;
        var content = item.content; var type = item.type; var filename = item.filename;
        if (act === 'copy') { if (content && content.startsWith('{"type":"merge_fwd"')) return showToast('合并转发不支持直接复制，请点开查看'); copyToClip(type === 'file' ? filename : content); }
        else if (act === 'forward') { if (ctxMsg) { selMsgs.clear(); selMsgs.add(ctxMsg.id.toString()); openForwardPicker('seq'); } else { var txt = type === 'file' ? '[文件] '+filename : content; openSimpleForwardPicker(txt); } }
        else if (act === 'multi') enterMulti(ctxMsg ? ctxMsg.id : null);
        else if (act === 'quote') { if (ctxMsg) startQuote(ctxMsg); else { startQuote({ from_uid: 'unknown', pseudoName: item.sender || '转发消息', type: item.type, filename: item.filename, content: item.content, id: item.id, quote: item.quote, is_recalled: item.is_recalled }); } }
        else if (act === 'recall') { 
            // ========== 使用统一的消息撤回处理框架 ==========
            const msgId = ctxMsg.id;
            fetch('/recall', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({uid:me.uid, msg_id:msgId}) })
            .then(r=>r.json())
            .then(d => { 
                if(d.error) {
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
    function startQuote(msg) { quoteMsg = msg; var name = msg.pseudoName || getName(msg.from_uid); var txt = msg.type === 'file' ? '[文件] '+msg.filename : msg.content; if(txt && txt.startsWith('{"type":"merge_fwd"')) txt = '[聊天记录]'; if(msg.is_recalled) txt = '<span class="quote-recalled">原消息已被撤回</span>'; document.getElementById('reply-content').innerHTML = "回复 " + name + ": " + txt; document.getElementById('reply-bar').style.display = 'flex'; document.getElementById('inp-msg').focus(); }
    function cancelQuote() { quoteMsg = null; document.getElementById('reply-bar').style.display = 'none'; }
    function enterMulti(initialId) { isMulti = true; document.body.classList.add('multi-mode'); selMsgs.clear(); if(initialId) selMsgs.add(initialId.toString()); renderChat(false); }
    function exitMulti() { isMulti = false; document.body.classList.remove('multi-mode'); selMsgs.clear(); renderChat(false); }
    function toggleSel(id, e) { if (!isMulti) return; if(e) e.stopPropagation(); id = id.toString(); if (selMsgs.has(id)) selMsgs.delete(id); else selMsgs.add(id); renderChat(false); }
    function multiAction(act) { if (selMsgs.size === 0) return alert('请至少选择一条消息'); if (act === 'copy') { var txt = ""; var ids = Array.from(selMsgs).sort(); ids.forEach(mid => { var m = findMsgById(currentChatMsgs, mid); if(m) txt += '['+getName(m.from_uid)+']: '+m.content+'\\n'; }); copyToClip(txt); exitMulti(); } else openForwardPicker(act); }

    let simpleFwdContent = null;
    function openSimpleForwardPicker(content) { simpleFwdContent = content; fwdMode = 'simple'; renderFwdPickerUI(); }
    function openForwardPicker(mode) { fwdMode = mode; renderFwdPickerUI(); }
    function renderFwdPickerUI() { var html = ''; for(var gid in cache.groups) html += '<div class="list-item clickable" onclick="selFwdTarget(this,\\''+gid+'\\',\\'group\\')"><div class="item-av" style="background:#007aff">'+cache.groups[gid].name[0]+'</div><div class="item-t">'+cache.groups[gid].name+'</div></div>'; for(var uid in cache.users) if(uid!==me.uid) html += '<div class="list-item clickable" onclick="selFwdTarget(this,\\''+uid+'\\',\\'private\\')"><div class="item-av" style="background:'+cache.users[uid].avatar_bg+'"></div><div class="item-t">'+getName(uid)+'</div></div>'; document.getElementById('picker-list').innerHTML = html; document.getElementById('md-picker').style.display = 'flex'; }
    let fwdTarget = null;
    function selFwdTarget(el, id, type) { var prev = document.querySelector('#picker-list .active'); if(prev) prev.classList.remove('active'); el.classList.add('active'); fwdTarget = {id: id, type: type}; }
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
            if(isCurrentChat) {
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
                    method:'POST', 
                    headers:{'Content-Type':'application/json'}, 
                    body:JSON.stringify({uid:me.uid, to_uid:fwdTarget.id, content:content}) 
                });
                const result = await response.json();
                
                // 用服务器返回的真实 ID 更新本地临时消息
                if(result.msg_id && isCurrentChat) {
                    var tmpIdx = currentChatMsgs.findIndex(m => m.id === tmpId);
                    if(tmpIdx !== -1) {
                        currentChatMsgs[tmpIdx].id = result.msg_id;
                        currentChatMsgs[tmpIdx].tmp = false;
                        var oldEl = document.getElementById('msg-' + tmpId);
                        if(oldEl) {
                            oldEl.id = 'msg-' + result.msg_id;
                            oldEl.dataset.id = result.msg_id;
                            var bub = oldEl.querySelector('.msg-bub');
                            if(bub) bub.classList.remove('sending');
                        }
                        // 修复：更新时间戳元素的ID（如果存在）
                        var oldTimeEl = document.getElementById('time-' + tmpId);
                        if(oldTimeEl) {
                            oldTimeEl.id = 'time-' + result.msg_id;
                        }
                        if(result.msg_id > maxMsgId) {
                            maxMsgId = result.msg_id;
                        }
                    }
                }
            } catch(e) {
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
                    if(m) {
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
                ids.forEach(function(mid, idx) { 
                    // SQLite 修复：使用安全 ID 比较函数
                    var m = findMsgById(currentChatMsgs, mid); 
                    if(m) { 
                        var sender = getName(m.from_uid); 
                        var txt = m.type==='file'?'[文件] '+m.filename : m.content; 
                        if(idx < 3) preview.push(sender + ": " + txt); 
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
        if(isMulti) exitMulti(); 
        showToast('转发成功'); 
        sync();
    }
    function closeMd(id) { document.getElementById(id).style.display='none'; fwdTarget=null; }

    function viewFwd(el) {
        var jsonStr = el.dataset.fwdJson; if(!jsonStr) return;
        try {
            var fwd = JSON.parse(jsonStr);
            var isInModal = el.closest('#fwd-content');
            if (!isInModal) { fwdStack = [fwd]; } else { fwdStack.push(fwd); }
            renderFwdList(fwd); document.getElementById('md-fwd-detail').style.display = 'flex'; updateFwdNav();
        } catch(e) { alert('无法查看详情'); }
    }
    function popFwdStack() { if (fwdStack.length > 1) { fwdStack.pop(); var prev = fwdStack[fwdStack.length - 1]; renderFwdList(prev); updateFwdNav(); } }
    function updateFwdNav() { var backBtn = document.getElementById('fwd-back'); if (fwdStack.length > 1) backBtn.style.display = 'block'; else backBtn.style.display = 'none'; }
    function closeFwdMd() { closeMd('md-fwd-detail'); fwdStack = []; }

    function renderFwdList(fwd) {
        var list = fwd.list || []; var html = ''; document.getElementById('fwd-title').innerText = fwd.title || '聊天记录';
        list.forEach(function(item){
           var d = new Date(item.time * 1000); var timeStr = d.getHours() + ':' + (d.getMinutes()<10?'0':'') + d.getMinutes();
           var contentHtml = item.content; var clickAttr = ''; var styleAttr = '';
           if(item.content && item.content.startsWith('{"type":"merge_fwd"')) {
               try {
                   var subFwd = JSON.parse(item.content);
                   contentHtml = '<div class="fwd-card" style="border:1px solid #eee;"><div class="fwd-head">' + subFwd.title + '</div><div class="fwd-body" style="font-size:11px;color:#aaa">';
                    subFwd.preview.forEach(function(p){ contentHtml += '<div class="fwd-row">' + p + '</div>'; }); contentHtml += '</div></div>';
                    var subJson = item.content.replace(/"/g, '&quot;'); clickAttr = 'onclick="viewFwd(this)" data-fwd-json="'+subJson+'"'; styleAttr = 'cursor:pointer;';
               } catch(e) {}
           } else if(item.type === 'file') { contentHtml = '[文件] ' + item.filename; }
           var quoteHtml = '';
           if (item.quote) { var qText = item.quote.content; if(item.quote.is_recalled) qText = '<span class="quote-recalled">原消息已被撤回</span>'; quoteHtml = '<div class="quote-box"><div class="q-name">'+item.quote.name+':</div><div class="q-txt">'+qText+'</div></div>'; }
           html += '<div class="fwd-item" id="fwd-msg-'+item.id+'" '+clickAttr+' data-content="'+(item.content||'').replace(/"/g,'&quot;')+'" data-type="'+item.type+'" data-filename="'+(item.filename||'')+'" data-sender="'+(item.sender||'')+'" data-quote="'+(item.quote ? JSON.stringify(item.quote).replace(/"/g,'&quot;') : '')+'" data-isrecalled="'+(item.is_recalled||false)+'" style="margin-bottom:10px;border-bottom:1px solid rgba(0,0,0,0.05);padding-bottom:5px;'+styleAttr+'">' + '<div style="font-size:12px;color:#888;display:flex;justify-content:space-between;"><span>'+item.sender+'</span><span>'+timeStr+'</span></div>' + quoteHtml + '<div style="font-size:14px;margin-top:2px;">'+contentHtml+'</div></div>';
        });
        document.getElementById('fwd-content').innerHTML = html;
    }
    function jumpToFwdMsg(mid, e) { if(e) e.stopPropagation(); showToast('合并记录内暂不支持跳转'); }
    function upFiles(files){
        if(!target || files.length === 0) return;
        
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
                '<div class="up-name">'+f.name+'</div>' +
                '<div class="up-info">' +
                '<span class="up-size">'+sizeStr+'</span>' +
                '<span class="up-method '+methodClass+'">'+methodStr+'</span>' +
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
        if(event) event.stopPropagation();
        logInfo('P2P', 'Accepting transfer:', sessionId);
        
        if(!window.p2pManager) {
            alert('P2P系统未就绪');
            return;
        }
        
        try {
            await window.p2pManager.acceptTransfer(sessionId);
            logInfo('P2P', 'Transfer accepted');
        } catch(error) {
            logError('P2P', 'Failed to accept transfer:', error);
            alert('接收失败：' + error.message);
        }
    }
    
    async function rejectP2PTransfer(sessionId, event) {
        if(event) event.stopPropagation();
        logInfo('P2P', 'Rejecting transfer:', sessionId);
        
        try {
            // 更新消息状态为rejected
            await fetch('/api/p2p/messages/' + sessionId + '/status', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({status: 'rejected'})
            });
            
            // 更新本地消息
            var msgIndex = currentChatMsgs.findIndex(m => m.p2p_session_id === sessionId);
            if(msgIndex !== -1) {
                currentChatMsgs[msgIndex].p2p_status = 'rejected';
                updateMessageInDOM(currentChatMsgs[msgIndex].id, currentChatMsgs[msgIndex], true);
            }
            
            logInfo('P2P', 'Transfer rejected');
        } catch(error) {
            logError('P2P', 'Failed to reject transfer:', error);
        }
    }
    
    async function cancelP2PTransfer(sessionId, event) {
        if(event) event.stopPropagation();
        logInfo('P2P', 'Cancelling transfer:', sessionId);
        
        if(window.p2pManager) {
            try {
                await window.p2pManager.cancelTransfer(sessionId);
            } catch(error) {
                logError('P2P', 'Failed to cancel via p2pManager:', error);
            }
        }
        
        try {
            // 更新消息状态为cancelled
            await fetch('/api/p2p/messages/' + sessionId + '/status', {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({status: 'cancelled'})
            });
            
            // 更新本地消息
            var msgIndex = currentChatMsgs.findIndex(m => m.p2p_session_id === sessionId);
            if(msgIndex !== -1) {
                currentChatMsgs[msgIndex].p2p_status = 'cancelled';
                updateMessageInDOM(currentChatMsgs[msgIndex].id, currentChatMsgs[msgIndex], true);
            }
            
            logInfo('P2P', 'Transfer cancelled');
        } catch(error) {
            logError('P2P', 'Failed to cancel transfer:', error);
        }
    }
    
    function closeUploadPanel() { document.getElementById('upload-panel').style.display = 'none'; var list = document.getElementById('up-list'); Array.from(list.children).forEach(el => { var task = uploadQueue.find(t => t.id === el.id); if(!task || task.status === 'done' || task.status === 'error') el.remove(); }); }
    async function processQueue() {
        if (isUploading || uploadQueue.length === 0) return; 
        var task = uploadQueue.find(t => t.status === 'pending'); 
        if (!task) { 
            if (uploadQueue.every(t => t.status !== 'pending' && t.status !== 'uploading')) { 
                if(pollingTimer) clearTimeout(pollingTimer); 
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
                if(statEl) statEl.innerText = '🔄';
                
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
                    if(statEl) statEl.innerText = '❌';
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
                    if(bar) bar.style.width = percent + '%'; 
                    
                    // 当上传完成时，显示"处理中"状态
                    if (percent >= 100) {
                        var statEl = document.querySelector('#' + task.id + ' .up-status');
                        if(statEl) statEl.innerText = '⚙️';
                        var nameEl = document.querySelector('#' + task.id + ' .up-name');
                        if(nameEl && !nameEl.dataset.originalText) {
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
                if(nameEl && nameEl.dataset.originalText) {
                    nameEl.innerText = nameEl.dataset.originalText;
                    delete nameEl.dataset.originalText;
                }
                
                if (xhr.status === 200) { 
                    task.status = 'done'; 
                    if(statEl) statEl.innerText = '✅'; 
                    
                    // 立即同步消息，让文件消息快速显示在聊天界面
                    if(pollingTimer) clearTimeout(pollingTimer);
                    sync();
                } else { 
                    task.status = 'error'; 
                    if(statEl) statEl.innerText = '❌'; 
                } 
                processQueue(); 
            };
            xhr.onerror = () => { 
                isUploading = false; 
                task.status = 'error'; 
                var statEl = document.querySelector('#' + task.id + ' .up-status'); 
                if(statEl) statEl.innerText = '❌'; 
                
                // 恢复原始文件名
                var nameEl = document.querySelector('#' + task.id + ' .up-name');
                if(nameEl && nameEl.dataset.originalText) {
                    nameEl.innerText = nameEl.dataset.originalText;
                    delete nameEl.dataset.originalText;
                }
                
                processQueue(); 
            }; 
            xhr.send(fd);
        }
    }
    function tab(t){ ['msg','con','file'].forEach(x => document.getElementById('tab-'+x).style.display='none'); document.getElementById('tab-'+t).style.display='flex'; document.querySelectorAll('.nav-btn').forEach(e=>e.classList.remove('active')); var navBtn = document.getElementById('nav-'+t); if(navBtn) navBtn.classList.add('active'); document.querySelectorAll('.m-nav-item').forEach(e=>e.classList.remove('active')); var mNavBtn = document.getElementById('mn-'+t); if(mNavBtn) mNavBtn.classList.add('active'); if(t==='file') loadFiles(); }
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
    function renderUserSelect(containerId) { selUids.clear(); let h = ''; var currentMembers = (containerId === 'invite-list' && target && cache.groups[target.id]) ? cache.groups[target.id].members : []; for(var uid in cache.users){ if(uid!==me.uid && cache.users[uid].status==='online' && !currentMembers.includes(uid)){ var u = cache.users[uid]; h += '<div class="user-row clickable" onclick="tog(this,\\''+uid+'\\')"><div class="item-av" style="background:'+u.avatar_bg+';width:30px;height:30px;"></div><div class="item-body">'+getName(uid)+'</div><div class="chk" style="display:none;color:var(--accent)">✓</div></div>'; } } document.getElementById(containerId).innerHTML = h || '<div class="empty">无其他在线好友</div>'; }
    function openCreate(){ renderUserSelect('create-list'); document.getElementById('md-create').style.display='flex'; }
    function openInvite(){ renderUserSelect('invite-list'); document.getElementById('md-invite').style.display='flex'; closeMd('md-manage'); }
    function tog(el, uid){ if(selUids.has(uid)){ selUids.delete(uid); el.querySelector('.chk').style.display='none'; el.classList.remove('sel'); } else { selUids.add(uid); el.querySelector('.chk').style.display='block'; el.classList.add('sel'); } }
    async function submitCreate(){ const n = document.getElementById('inp-grp-name').value; if(!n) return alert('输入群名'); await fetch('/create_group', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:n, uid:me.uid, members:Array.from(selUids)}) }); closeMd('md-create'); if(pollingTimer) clearTimeout(pollingTimer); sync(); }
    async function submitInvite(){ if(!target || target.type !== 'group') return; await fetch('/group/manage', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'invite', group_id:target.id, uid:me.uid, members:Array.from(selUids)}) }); closeMd('md-invite'); if(pollingTimer) clearTimeout(pollingTimer); sync(); }
    function openManage() { if(!target || target.type !== 'group') return; var g = cache.groups[target.id]; document.getElementById('mng-grp-name').value = g.name; var h = ''; g.members.forEach(mid => { var u = cache.users[mid] || {name:'Unknown'}; var isOwner = mid === g.owner; var btn = (!isOwner && mid !== me.uid) ? '<div class="clickable" style="color:red;font-size:12px;" onclick="doKick(\\''+mid+'\\')">移出</div>' : ''; h += '<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid rgba(0,0,0,0.05);"><span>'+getName(mid)+' '+(isOwner?'(群主)':'')+'</span>'+btn+'</div>'; }); document.getElementById('mng-mem-list').innerHTML = h; document.getElementById('md-manage').style.display = 'flex'; }
    async function doRename() { const n = document.getElementById('mng-grp-name').value; if(!n) return; await fetch('/group/manage', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'rename', group_id:target.id, uid:me.uid, name:n}) }); if(pollingTimer) clearTimeout(pollingTimer); sync(); }
    async function doKick(uid) { if(!confirm('确定移除该成员？')) return; await fetch('/group/manage', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'kick', group_id:target.id, uid:me.uid, target_uid:uid}) }); openManage(); if(pollingTimer) clearTimeout(pollingTimer); sync(); }
    async function doDissolve() { if(!confirm('确定解散群组？')) return; await fetch('/group/manage', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'dissolve', group_id:target.id, uid:me.uid}) }); closeMd('md-manage'); target=null; if(pollingTimer) clearTimeout(pollingTimer); sync(); }
    function openSet(){ document.getElementById('set-av').style.background = me.avatar_bg; document.getElementById('set-new-nick').value = me.name; document.getElementById('set-new-pwd').value = ''; devClicks = 0; document.getElementById('md-set').style.display='flex'; }
    async function changeAv(){ const avBox = document.getElementById('set-av'); avBox.classList.remove('spin'); void avBox.offsetWidth; avBox.classList.add('spin'); const r = await fetch('/update_avatar', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({uid:me.uid}) }); const d = await r.json(); me.avatar_bg = d.avatar_bg; upMe(); setTimeout(() => avBox.style.background = me.avatar_bg, 250); }
    async function saveProfile() { const nick = document.getElementById('set-new-nick').value.trim(); const pwd = document.getElementById('set-new-pwd').value.trim(); if(!nick) return alert('昵称不能为空'); const r = await fetch('/update_profile', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ uid: me.uid, nickname: nick, password: pwd }) }); const d = await r.json(); if(!r.ok) return alert(d.error || '保存失败'); me.name = d.name; closeMd('md-set'); }
    function triggerDev() { devClicks++; if(devClicks >= 10) { devClicks = 0; closeMd('md-set'); document.getElementById('dev-pwd').value = ''; document.getElementById('md-dev-auth').style.display = 'flex'; } }
    async function verifyDev() { 
        const p = document.getElementById('dev-pwd').value; 
        // 尝试进行管理员身份验证
        const authenticated = await authenticateAdmin(p);
        if (authenticated) {
            try {
                const r = await fetch('/api/admin/account_panel', { 
                    method: 'POST', 
                    headers: {'Content-Type':'application/json'}, 
                    body: JSON.stringify({ token: adminToken }) 
                });
                if(!r.ok) throw new Error('Access Denied');
                const data = await r.json();
                closeMd('md-dev-auth');
                openAccountPanel(data.accounts);
            } catch(e) {
                alert('认证失败');
                document.getElementById('dev-pwd').value = '';
            }
            return;
        }
        // 原有的日志查看密码验证
        try { 
            const r = await fetch('/api/admin/logs', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ password: p }) }); 
            if(!r.ok) throw new Error('Access Denied'); 
            const data = await r.json(); 
            closeMd('md-dev-auth'); 
            renderDevLogs(data); 
            document.getElementById('md-dev-logs').style.display = 'flex'; 
        } catch(e) { 
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
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ password: password })
            });
            if (!r.ok) throw new Error('Authentication failed');
            const data = await r.json();
            adminToken = data.token;  // 存储 token
            return true;
        } catch(e) {
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
                headers: {'Content-Type': 'application/json'},
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
        } catch(e) {
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
                headers: {'Content-Type': 'application/json'},
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
        } catch(e) {
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
                headers: {'Content-Type': 'application/json'},
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
        } catch(e) {
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
            sourceH += '<div class="account-item clickable" style="display:flex; align-items:center; padding:8px; margin:3px 0; background:' + bgColor + '; border-radius:6px; border:1px solid ' + borderColor + '; opacity:' + opacity + ';" onclick="' + onclickAttr + '">'+
                '<div style="width:30px; height:30px; border-radius:8px; background:' + acc.avatar_bg + '; margin-right:10px; flex-shrink:0;"></div>'+
                '<div style="flex:1; min-width:0;">'+
                    '<div style="font-size:13px; font-weight:600; color:#ddd;">' + acc.name + '</div>'+
                    '<div style="font-size:10px; color:#888;">消息数: ' + acc.msg_count + '</div>'+
                '</div>'+
                '<div style="color:' + checkColor + '; font-size:16px;">' + checkIcon + '</div>'+
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
            targetH += '<div class="account-item clickable" style="display:flex; align-items:center; padding:8px; margin:3px 0; background:' + bgColor + '; border-radius:6px; border:1px solid ' + borderColor + '; opacity:' + opacity + ';" onclick="' + onclickAttr + '">'+
                '<div style="width:30px; height:30px; border-radius:8px; background:' + acc.avatar_bg + '; margin-right:10px; flex-shrink:0;"></div>'+
                '<div style="flex:1; min-width:0;">'+
                    '<div style="font-size:13px; font-weight:600; color:#ddd;">' + acc.name + '</div>'+
                    '<div style="font-size:10px; color:#888;">消息数: ' + acc.msg_count + '</div>'+
                '</div>'+
                '<div style="color:' + checkColor + '; font-size:16px;">' + checkIcon + '</div>'+
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
                headers: {'Content-Type': 'application/json'},
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
        } catch(e) {
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
                } catch(e) {
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
    function upMe(){ document.getElementById('my-av').style.background=me.avatar_bg; }
    document.getElementById('inp-msg').onkeydown = (e) => { if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); } }

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
                    expandBtn.onclick = function(e) {
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
        window.addEventListener('resize', function() {
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


</script>
</body>
</html>
"""

if __name__ == '__main__':
    # 禁用 werkzeug 的 HTTP 请求日志
    import logging as log
    log.getLogger('werkzeug').setLevel(log.ERROR)
    
    # ================= 服务器启动密码验证 =================
    if SERVER_STARTUP_PASSWORD:
        print('\n' + '=' * 50)
        print('LANChat Hub - Server Startup Authentication')
        print('=' * 50)
        print('Please enter the startup password to continue.')
        print('-' * 50)
        
        max_attempts = 3
        authenticated = False
        
        for attempt in range(max_attempts):
            # 直接使用 input（Windows cmd 兼容性更好）
            user_input = input(f'Enter password : ')
            
            # 清理输入（去除首尾空格）
            user_input = user_input.strip()
            
            if user_input == SERVER_STARTUP_PASSWORD:
                authenticated = True
                print('-' * 50)
                print('✓ Authentication successful!')
                print('=' * 50)
                break
            else:
                remaining = max_attempts - attempt - 1
                if remaining > 0:
                    print(f'✗ Incorrect password. {remaining} attempt(s) remaining.')
                else:
                    print('-' * 50)
                    print('✗ Authentication failed. Server startup aborted.')
                    print('=' * 50)
                    sys.exit(1)
        
        if not authenticated:
            sys.exit(1)
    
    print('Initializing server...')
    
    # 检测 CPU 核心数，失败时默认为 2
    cpu_count = os.cpu_count() or 2
    
    # 计算线程数：min(cpu_count * 2, 8)
    threads = min(cpu_count * 2, 8)
    
    # 获取本地IP地址
    print('Getting local IP address...')
    try:
        local_ip = get_local_ip()
        print(f'Local IP: {local_ip}')
    except Exception as e:
        print(f"Warning: Failed to get local IP: {e}")
        local_ip = "127.0.0.1"
    
    port = 5000
    
    # 尝试使用 Waitress WSGI 服务器
    print('Loading server...')
    try:
        from waitress import serve
        
        print('')
        print('LANChat Hub - Server starting...')
        print(f'CPU cores: {cpu_count}, Threads: {threads}')
        print(f'Server ready at http://{local_ip}:{port}')
        print('')
        
        # 启动 Waitress 服务器
        serve(
            app,
            host='0.0.0.0',
            port=port,
            threads=threads,
            channel_timeout=120,
            cleanup_interval=30,
            asyncore_use_poll=True
        )
        
    except ImportError:
        # Waitress 未安装，回退到 Flask 开发服务器
        print('WARNING: Waitress not installed, using Flask dev server')
        print('For better performance: pip install waitress')
        print(f'Server ready at http://{local_ip}:{port}')
        
        # 使用 Flask 开发服务器
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
