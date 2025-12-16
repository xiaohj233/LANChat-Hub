# QQ Web Pro v10.0

一个现代化的网页聊天应用，支持实时消息、P2P 文件传输和群组聊天功能。

## 主要特性

- **实时消息传输**：基于 WebSocket 的即时消息推送
- **P2P 文件传输**：使用 WebRTC 技术实现点对点文件共享
- **群组聊天**：创建和管理群组对话
- **媒体支持**：支持图片、文件等多种媒体内容分享
- **安全认证**：密码保护的管理面板和启动验证
- **轻量级存储**：使用 SQLite 数据库，便于部署和迁移
- **响应式设计**：适配桌面和移动设备
- **自定义头像**：万花筒风格的头像生成系统
- **管理后台**：用户管理和系统监控功能

## 技术栈

- **后端**：Python 3.x, Flask
- **数据库**：SQLite (WAL 模式支持并发访问)
- **前端**：HTML5, CSS3, JavaScript
- **实时通信**：WebSocket
- **P2P 传输**：WebRTC
- **文件传输**：支持最大 500MB 的文件

## 系统要求

- Python 3.7 或更高版本
- Flask 框架
- SQLite3
- 支持 WebRTC 的现代浏览器

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/qq-web-pro.git
cd qq-web-pro
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置密码（可选）

复制配置文件示例：

```bash
copy config.json.example config.json
```

编辑 `config.json` 或 `main.py` 设置管理员密码：

```python
# 在 main.py 中
ADMIN_PASSWORD_1 = "your_admin_password"  # 账户管理面板密码
ADMIN_PASSWORD_2 = "your_logs_password"   # 管理员日志密码
SERVER_STARTUP_PASSWORD = "your_startup_password"  # 服务器启动密码
```

### 4. 运行应用

```bash
python main.py
```

服务器将在 `http://localhost:5000` 启动（或显示您的本地 IP 地址）。

## 表情资源配置

### 静态表情（已包含）

本项目使用来自 [emoji-datasource-apple](https://www.npmjs.com/package/emoji-datasource-apple) 的静态表情图片（MIT 许可证），已包含在仓库中。

### 动画表情（可选）

动画表情包因版权考虑未包含在仓库中。

**应用在仅使用静态表情的情况下可以完全正常工作。** 动画表情切换开关仅在安装动画资源后才会显示。

#### 添加动画表情（可选步骤）：

1. 从合法来源获取动画表情文件（`.webp` 格式）
2. 将文件放置在 `30hz/` 文件夹中
3. 运行配置脚本：

```bash
cd 其他
setup_refactor.bat
```

此脚本将同步动画表情到 `static/telegram_stickers/` 并在界面中启用动画表情切换功能。

**推荐的动画表情来源：**
- 使用 Adobe After Effects + Lottie 等工具自行创建
- 使用开源动画表情库（请仔细检查许可证）
- 购买授权的动画表情包

**说明：**
- 静态表情图片来自 `emoji-datasource-apple`（MIT 许可证）
- 应用会自动检测可用资源并调整界面
- 无动画资源 = 仅静态表情（不显示切换开关）
- 有动画资源 = 可选择静态或动画表情

## 文档

- [密码配置指南](README_密码配置.md) - 密码配置详细说明（中文）
- [管理员密码配置说明](管理员密码配置说明.md) - 管理员密码设置（中文）
- [服务器启动密码说明](服务器启动密码说明.md) - 启动密码指南（中文）
- [功能实现总结](功能实现总结.md) - 功能实现摘要（中文）
- [表情资源设置](EMOJI_SETUP.md) - 表情资源配置详情

## 安全特性

### 三层密码保护

1. **启动密码**：启动服务器时需要输入（可选）
2. **管理密码 1**：访问账户管理面板
3. **管理密码 2**：访问管理员日志和监控

### 默认密码

- 管理密码 1：`123`（生产环境请务必修改！）
- 管理密码 2：`321`（生产环境请务必修改！）
- 启动密码：无（默认禁用）

**重要提示**：部署到生产环境前请修改默认密码！

## 核心功能说明

### P2P 文件传输

- 使用 WebRTC 实现点对点文件共享
- 无需服务器存储 P2P 传输的文件
- 支持大文件传输并显示进度
- P2P 失败时自动降级到服务器传输
- 支持断点续传功能

### 群组聊天

- 默认"全员摸鱼群"
- 创建自定义群组
- 群组文件共享
- 成员管理

### 用户管理

- 用户注册和认证
- 头像自定义
- 用户备注/昵称
- 会话管理
- 账户合并功能

## 项目结构

```
qq-web-pro/
├── main.py                 # 主应用程序文件
├── static/                 # 静态资源（CSS、JS、图片）
├── uploads/                # 用户上传的文件
├── config.json.example     # 配置文件模板
├── requirements.txt        # Python 依赖
├── README.md              # 本文件
└── 文档/                   # 中文文档
```

## 数据库优化

应用使用 SQLite 的 WAL（预写式日志）模式，具有以下特性：
- 支持并发读写操作
- 在机械硬盘上性能更好
- 减少数据库锁定问题

### 性能配置

- 32MB 缓存大小
- 256MB 内存映射
- 30 秒忙等待超时
- 自动 WAL 检查点

## 测试

运行测试套件：

```bash
python 测试完整启动流程.py
python 测试启动密码.py
```

## 构建可执行文件

项目包含 PyInstaller 配置文件，可用于创建独立可执行文件：

```bash
pyinstaller main.spec
```

## 贡献

欢迎提交 Pull Request！

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

### 第三方资源

- **表情图片**：[emoji-datasource-apple](https://github.com/iamcal/emoji-data)（MIT 许可证）
- 表情图片由 emoji-datasource-apple 包提供，该包采用 MIT 许可证，可免费用于开源和商业项目。

## 故障排除

### 数据库锁定错误

如果遇到"数据库已锁定"错误：
- 应用使用 WAL 模式来最小化此问题
- 检查是否有其他进程正在访问数据库
- 可在配置中增加忙等待超时时间

### P2P 传输问题

如果 P2P 传输失败：
- 检查防火墙设置
- 确保浏览器支持 WebRTC
- 系统会自动降级到服务器传输

### 端口已被占用

如果端口 5000 已被占用：
- 在 `main.py` 中修改端口
- 或停止占用端口 5000 的进程

## 支持

如有问题和疑问：
- 查看 `文档/` 文件夹中的文档
- 查看故障排除指南：[启动问题排查指南.md](启动问题排查指南.md)
- 在 GitHub 上提交 Issue

## 致谢

使用 Flask、SQLite 和现代 Web 技术构建。

---

**版本**：10.0  
**最后更新**：2024 年 12 月
