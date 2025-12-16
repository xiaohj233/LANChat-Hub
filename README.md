# QQ Web Pro v10.0

A modern, feature-rich web-based chat application with real-time messaging, P2P file transfer, and group chat capabilities.

## ✨ Features

- 🚀 **Real-time Messaging**: Instant message delivery with WebSocket support
- 📁 **P2P File Transfer**: Direct peer-to-peer file sharing with WebRTC
- 👥 **Group Chat**: Create and manage group conversations
- 🖼️ **Media Support**: Share images, files, and rich media content
- 🔐 **Secure Authentication**: Password-protected admin panel and startup
- 💾 **SQLite Database**: Lightweight and portable data storage
- 📱 **Responsive Design**: Works on desktop and mobile devices
- 🎨 **Custom Avatars**: Kaleidoscope-style avatar generation
- 📊 **Admin Dashboard**: User management and system monitoring

## 🛠️ Tech Stack

- **Backend**: Python 3.x, Flask
- **Database**: SQLite with WAL mode for concurrent access
- **Frontend**: HTML5, CSS3, JavaScript
- **Real-time**: WebSocket for instant messaging
- **P2P**: WebRTC for direct file transfers
- **File Transfer**: Support for large files (up to 500MB)

## 📋 Requirements

- Python 3.7+
- Flask
- SQLite3
- Modern web browser with WebRTC support

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/qq-web-pro.git
cd qq-web-pro
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure passwords (optional)

Copy the example configuration:

```bash
copy config.json.example config.json
```

Edit `config.json` or `main.py` to set your admin passwords:

```python
# In main.py
ADMIN_PASSWORD_1 = "your_admin_password"  # Account management
ADMIN_PASSWORD_2 = "your_logs_password"   # Admin logs
SERVER_STARTUP_PASSWORD = "your_startup_password"  # Server startup
```

### 4. Run the application

```bash
python main.py
```

The server will start on `http://localhost:5000` (or your local IP address).

## 📖 Documentation

- [密码配置指南](README_密码配置.md) - Password configuration guide (Chinese)
- [管理员密码配置说明](管理员密码配置说明.md) - Admin password setup (Chinese)
- [服务器启动密码说明](服务器启动密码说明.md) - Startup password guide (Chinese)
- [功能实现总结](功能实现总结.md) - Feature implementation summary (Chinese)

## 🔒 Security Features

### Three-Layer Password Protection

1. **Startup Password**: Required to start the server (optional)
2. **Admin Password 1**: Access to account management panel
3. **Admin Password 2**: Access to admin logs and monitoring

### Default Passwords

- Admin Password 1: `123` (change in production!)
- Admin Password 2: `321` (change in production!)
- Startup Password: None (disabled by default)

⚠️ **Important**: Change default passwords before deploying to production!

## 🎯 Key Features Explained

### P2P File Transfer

- Direct peer-to-peer file sharing using WebRTC
- No server storage for P2P transfers
- Support for large files with progress tracking
- Automatic fallback to server transfer if P2P fails
- Resume capability for interrupted transfers

### Group Chat

- Default "全员摸鱼群" (All Members Group)
- Create custom groups
- Group file sharing
- Member management

### User Management

- User registration and authentication
- Avatar customization
- User remarks/nicknames
- Session management
- Account merging capability

## 📁 Project Structure

```
qq-web-pro/
├── main.py                 # Main application file
├── static/                 # Static assets (CSS, JS, images)
├── uploads/                # User uploaded files
├── config.json.example     # Configuration template
├── requirements.txt        # Python dependencies
├── README.md              # This file
└── 文档/                   # Chinese documentation
```

## 🔧 Configuration

### Database Optimization

The application uses SQLite with WAL (Write-Ahead Logging) mode for:
- Concurrent read/write operations
- Better performance on mechanical drives
- Reduced database locking issues

### Performance Settings

- 32MB cache size
- 256MB memory mapping
- 30-second busy timeout
- Automatic WAL checkpointing

## 🧪 Testing

Run the test suite:

```bash
python 测试完整启动流程.py
python 测试启动密码.py
```

## 🎨 Emoji Resources

### Static Emoji (Included)
This project uses static emoji images from [emoji-datasource-apple](https://www.npmjs.com/package/emoji-datasource-apple) (MIT License), which are included in the repository.

### Animated Stickers (Optional)
Animated emoji stickers are **not included** in this repository due to potential copyright concerns. 

**The app works perfectly fine with static emoji only.** The animated emoji toggle will only appear if you install animated stickers.

#### To add animated stickers (optional):

1. Obtain animated emoji files (`.webp` format) from a legal source
2. Place them in the `30hz/` folder
3. Run the setup script:

```bash
cd 其他
setup_refactor.bat
```

This will sync the animated stickers to `static/telegram_stickers/` and enable the animated emoji toggle in the UI.

**Recommended sources for animated emoji:**
- Create your own using tools like Adobe After Effects + Lottie
- Use open-source animated emoji libraries (check licenses carefully)
- Purchase licensed animated emoji packs

**Note**: 
- Static emoji images are sourced from `emoji-datasource-apple` (MIT License)
- The app automatically detects available resources and adjusts the UI accordingly
- No animated stickers = static emoji only (no toggle shown)
- With animated stickers = both static and animated options available

## 📦 Building Executable

The project includes PyInstaller spec files for creating standalone executables:

```bash
pyinstaller main.spec
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Third-Party Resources

- **Emoji Images**: [emoji-datasource-apple](https://github.com/iamcal/emoji-data) (MIT License)
- Emoji graphics are provided by the emoji-datasource-apple package, which is MIT licensed and free to use in both open-source and commercial projects.

## 🐛 Troubleshooting

### Database Locked Error

If you encounter "database is locked" errors:
- The application uses WAL mode to minimize this
- Check if another process is accessing the database
- Increase the busy timeout in configuration

### P2P Transfer Issues

If P2P transfers fail:
- Check firewall settings
- Ensure WebRTC is supported in your browser
- The system will automatically fallback to server transfer

### Port Already in Use

If port 5000 is already in use:
- Change the port in `main.py`
- Or stop the process using port 5000

## 📞 Support

For issues and questions:
- Check the documentation in the `文档/` folder
- Review the troubleshooting guide: [启动问题排查指南.md](启动问题排查指南.md)
- Open an issue on GitHub

## 🎉 Acknowledgments

Built with Flask, SQLite, and modern web technologies.

---

**Version**: 10.0  
**Last Updated**: December 2024
