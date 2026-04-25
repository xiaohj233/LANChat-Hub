# LANChat Hub - 局域网聊天应用

<div align="center">

![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.7+-green.svg)
![Flask](https://img.shields.io/badge/flask-2.0+-orange.svg)
![Werkzeug](https://img.shields.io/badge/werkzeug-2.0+-orange.svg)
![Waitress](https://img.shields.io/badge/waitress-2.1+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-brightgreen.svg)

一个功能强大、易于部署的局域网聊天应用，支持 P2P 文件传输、实时消息同步、表情包和贴纸等丰富功能。

[功能特性](#功能特性) • [快速开始](#快速开始) • [部署指南](#部署指南) • [使用说明](#使用说明) • [技术架构](#技术架构)

</div>

---

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [部署指南](#部署指南)
- [使用说明](#使用说明)
- [技术架构](#技术架构)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 功能特性

### 核心功能

- **零配置部署** - 开箱即用，无需复杂配置
- **实时聊天** - 支持私聊和群聊，消息实时同步
- **P2P 文件传输** - 基于 WebRTC 的点对点文件传输，无需服务器中转
- **断点续传** - 支持大文件传输中断后继续传输
- **传输监控** - 实时显示传输速度、进度和预计剩余时间

### 用户体验

- **万花筒头像** - 自动生成独特的渐变头像
- **丰富表情** - 内置大量 Emoji 和 Telegram 风格贴纸
- **消息通知** - 支持已读标记和消息撤回
- **文件置顶** - 智能文件去重，自动引用已上传文件
- **用户管理** - 支持昵称备注、用户删除和账户合并

### 管理功能

- **访问控制** - 支持密码保护和用户注册审核
- **审计日志** - 完整的 P2P 传输审计记录
- **安全防护** - 会话管理、密码加密、SQL 注入防护
- **性能优化** - SQLite WAL 模式、内存缓存、查询优化

### 便携性

- **USB 便携模式** - 支持从 U 盘直接运行
- **单文件部署** - 可打包为独立 EXE 文件
- **跨平台支持** - Windows、Linux、macOS 全平台兼容

---

## 快速开始

### 方式一：使用预编译版本（推荐）

如果你不想配置 Python 环境，可以直接下载预编译的可执行文件：

1. 前往 [Releases](https://github.com/xiaohj233/LANChat-Hub/releases) 页面
2. 下载最新版本的压缩包（例如：`LANChat-Hub-v1.1.0-Windows.zip`）
3. 解压到任意目录
4. 双击运行 `聊天室.exe`
5. 在浏览器输入命令行显示的地址，例如：`http://192.168.1.100:5000`

**注意：** 预编译版本已包含所有必需的依赖和资源文件，无需额外配置。

### 方式二：从源码运行

#### 环境要求

- Python 3.7 或更高版本
- 现代浏览器（Chrome、Firefox、Edge 等）
- 局域网环境

#### 安装步骤

1. **克隆仓库**

```bash
git clone https://github.com/xiaohj233/LANChat-Hub.git
cd LANChat-Hub
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **启动服务器**

```bash
python main.py
```

4. **访问应用**

服务器启动后，会自动显示访问地址，例如：
```
服务器运行在: http://192.168.1.100:5000
```

在浏览器中打开该地址即可开始使用。

---

## 部署指南

### 开发环境部署

适合开发和测试使用：

```bash
# 使用 Flask 内置服务器
python main.py
```

### 生产环境部署

推荐使用 Waitress 作为生产服务器：

```bash
# 安装 Waitress
pip install waitress

# 启动生产服务器
waitress-serve --host=0.0.0.0 --port=5000 main:app
```

### Docker 部署

```bash
# 构建镜像
docker build -t lanchat-hub .

# 运行容器
docker run -d -p 5000:5000 -v ./data:/app/data lanchat-hub
```

### 打包为独立程序

如果你想自己打包程序：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包（带命令行窗口，方便查看日志）
pyinstaller -F --add-data "static;static" -n "聊天室" main.py

```

打包后的程序位于 `dist` 目录中，可直接分发使用。

**注意：** 
- Linux/macOS 系统使用冒号分隔：`--add-data "static:static"`
- 建议普通用户直接下载 [Releases](https://github.com/xiaohj233/lanchat-hub/releases) 中的预编译版本

---

## 使用说明

### 首次使用

1. **注册账户**
   - 输入昵称和密码（可选）
   - 系统自动生成独特的万花筒头像

2. **加入聊天**
   - 默认加入"全员交流群"
   - 可创建新群组或发起私聊

3. **发送消息**
   - 支持文本、图片、文件、表情包
   - 支持引用回复和消息撤回

### P2P 文件传输

1. **发起传输**
   - 点击文件按钮选择文件
   - 选择 P2P 传输模式
   - 等待接收方响应

2. **接收文件**
   - 收到传输请求后点击接受
   - 自动建立 P2P 连接
   - 实时显示传输进度

3. **断点续传**
   - 传输中断后自动保存进度
   - 重新连接后可继续传输

### 管理功能

1. **进入管理面板**
   - 在设置界面，连续点击 10 次"修改密码"文字标题
   - 会弹出"SYSTEM CORE"对话框
   - 输入对应的管理员密码进入相应面板

2. **账户管理面板**
   - 在"SYSTEM CORE"对话框中输入密码 1（默认：`123`）
   - 功能：删除用户、合并账户、强制下线等

3. **日志查看面板**
   - 在"SYSTEM CORE"对话框中输入密码 2（默认：`321`）
   - 功能：查看 P2P 传输审计日志、系统操作记录等

---

## 技术架构

### 后端技术栈

- **Web 框架**: Flask 2.0+
- **WSGI 工具库**: Werkzeug 2.0+
- **数据库**: SQLite 3（WAL 模式）
- **WSGI 服务器**: Waitress（生产环境）
- **文件传输**: WebRTC P2P

### 前端技术栈

- **原生 JavaScript** - 无框架依赖
- **WebRTC API** - P2P 连接和数据传输
- **IndexedDB** - 本地数据缓存
- **CSS3** - 响应式布局和动画

### 数据库设计

```
users              # 用户表
├── uid            # 用户ID
├── name           # 昵称
├── password       # 密码哈希
├── avatar_bg      # 头像背景
└── version        # 版本号（用于同步）

messages           # 消息表
├── id             # 消息ID
├── from_uid       # 发送者
├── to_uid         # 接收者
├── content        # 消息内容
└── timestamp      # 时间戳

groups             # 群组表
├── id             # 群组ID
├── name           # 群组名称
├── owner          # 群主
└── version        # 版本号

p2p_sessions       # P2P会话表
├── session_id     # 会话ID
├── sender_uid     # 发送者
├── receiver_uid   # 接收者
├── status         # 状态
└── file_count     # 文件数量
```

### 性能优化

- **SQLite 优化**
  - WAL 模式：支持并发读写
  - 内存缓存：32MB 缓存大小
  - 内存映射：256MB mmap_size
  - 索引优化：为高频查询创建索引

- **文件传输优化**
  - 智能去重：基于 SHA256 哈希
  - 分块传输：支持大文件传输
  - 断点续传：保存传输进度
  - 速度控制：自适应传输速率

---

## 配置说明

### 密码配置

**重要：密码配置优先级**

密码配置遵循以下优先级（从高到低）：
1. `main.py` 中的配置（ADMIN_PASSWORD_1, ADMIN_PASSWORD_2）
2. `config.json` 配置文件
3. 默认密码（"123", "321"）

**如果在 `main.py` 中设置了密码（非空字符串），则 `config.json` 中的密码配置将被忽略。**

#### 方式一：在 main.py 中配置（优先级最高）

在 `main.py` 文件顶部修改：

```python
# 账户管理面板密码
ADMIN_PASSWORD_1 = "your_password"  # 留空则使用配置文件或默认密码

# 日志查看密码
ADMIN_PASSWORD_2 = "your_password"  # 留空则使用配置文件或默认密码

# 服务器启动密码（可选，留空则不需要密码）
SERVER_STARTUP_PASSWORD = ""
```

**注意：** 
- 如果设置了非空密码，配置文件中的密码将无效
- 服务器启动密码只能在 `main.py` 中设置，无法通过配置文件修改

#### 方式二：使用配置文件（优先级中等）

创建 `config.json` 文件：

```json
{
  "admin_password_1": "123",
  "admin_password_2": "321",
  "max_file_size": 524288000,
  "session_timeout": 300
}
```

**注意：** 仅当 `main.py` 中对应密码为空字符串时，配置文件中的密码才会生效。

#### 方式三：使用默认密码（优先级最低）

如果以上两种方式都未设置密码，系统将使用默认密码：
- 账户管理面板密码：`123`
- 日志查看密码：`321`

### 环境变量

```bash
# 设置端口
export FLASK_PORT=5000

# 设置主机
export FLASK_HOST=0.0.0.0

# 开启调试模式
export FLASK_DEBUG=1

# 设置 Flask 密钥（生产环境强烈建议修改）
export SECRET_KEY=your_random_secret_key_here
```

**安全提示：** 生产环境中建议通过环境变量 `SECRET_KEY` 设置一个随机的密钥，而不是使用默认值。

---

## 常见问题

### Q: 如何修改服务器端口？

A: 在 `main.py` 文件末尾修改 `app.run()` 的 `port` 参数。

### Q: P2P 传输失败怎么办？

A: 检查以下几点：
- 确保双方同时处于同一个聊天界面
- 检查防火墙设置

### Q: 如何备份聊天数据？

A: 备份以下文件即可：
- `qq_data.db` - 数据库文件
- `uploads/` - 上传文件目录

### Q: 支持多少并发用户？

A: 理论上无限制，实际取决于服务器性能。测试环境下支持 100+ 并发用户。

### Q: 如何重置管理员密码？

A: 根据你的配置方式，有以下几种重置方法：

**方法一：如果密码在 main.py 中配置**
1. 打开 `main.py` 文件
2. 找到以下代码：
   ```python
   ADMIN_PASSWORD_1 = "your_password"
   ADMIN_PASSWORD_2 = "your_password"
   ```
3. 将密码改为空字符串 `""` 或修改为新密码
4. 重启服务器

**方法二：如果密码在 config.json 中配置**
1. 确保 `main.py` 中的密码为空字符串（`ADMIN_PASSWORD_1 = ""`）
2. 打开或创建 `config.json` 文件
3. 修改密码配置：
   ```json
   {
     "admin_password_1": "新密码",
     "admin_password_2": "新密码"
   }
   ```
4. 重启服务器

**方法三：恢复默认密码**
1. 确保 `main.py` 中的密码为空字符串
2. 删除 `config.json` 文件（如果存在）
3. 重启服务器
4. 密码将恢复为默认值：
   - 账户管理面板密码：`123`
   - 日志查看密码：`321`

**注意：** 如果 `main.py` 中设置了非空密码，则必须修改 `main.py` 才能重置密码，删除 `config.json` 无效。

---

## 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 贡献流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发规范

- 遵循 PEP 8 代码规范
- 添加必要的注释和文档
- 确保代码通过测试
- 更新相关文档

---

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 致谢

- Flask 框架团队
- Werkzeug 工具库
- Waitress 服务器
- SQLite 数据库
- WebRTC 技术社区
- 所有贡献者和用户

---

## 联系方式

- 项目主页: [GitHub](https://github.com/xiaohj233/LANChat-Hub)
- 问题反馈: [Issues](https://github.com/xiaohj233/LANChat-Hub/issues)

---

<div align="center">

**如果这个项目对你有帮助，请给个 Star 支持一下！**

Made by [@xiaohj233](https://github.com/xiaohj233)

</div>
