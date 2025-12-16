# Emoji 和表情包设置指南

## ℹ️ 重要说明

**应用默认使用静态 Emoji，无需额外配置即可正常使用。**

动画表情包是**可选功能**。如果不安装动画资源：
- ✅ 应用正常工作，使用静态 Emoji
- ✅ UI 自动适配，不显示动态开关
- ✅ 用户体验完整，无任何错误

## ⚠️ 版权声明

动画表情包资源需要用户自行准备，以避免版权问题。

## 📁 目录结构

```
static/
├── emoji/              # Unicode Emoji 图片
└── telegram_stickers/  # Telegram 风格表情包
```

## 🎨 推荐的开源 Emoji 资源

### 1. Twemoji (Twitter Emoji)
- **许可证**: MIT / CC-BY 4.0
- **下载**: https://github.com/twitter/twemoji
- **说明**: Twitter 的开源 Emoji 实现，可商用

### 2. Noto Emoji (Google)
- **许可证**: Apache 2.0
- **下载**: https://github.com/googlefonts/noto-emoji
- **说明**: Google 的开源 Emoji 字体和图片

### 3. OpenMoji
- **许可证**: CC BY-SA 4.0
- **下载**: https://openmoji.org/
- **说明**: 开源的 Emoji 项目

## 📦 安装步骤

### 方法 1: 使用 Twemoji (推荐)

1. 下载 Twemoji:
```bash
git clone https://github.com/twitter/twemoji.git
```

2. 复制 PNG 图片到项目:
```bash
cp -r twemoji/assets/72x72/*.png static/emoji/
```

3. 重命名文件以匹配 Unicode 编码格式 (如 `1f600.png`)

### 方法 2: 使用 CDN (无需下载)

修改前端代码，使用 CDN 加载 Emoji:

```javascript
// 使用 Twemoji CDN
const emojiUrl = `https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/${code}.png`;
```

## 🎭 Telegram 表情包替代方案

### 选项 1: 使用开源动画表情包
- **Animated Emoji**: https://github.com/googlefonts/noto-emoji/tree/main/png
- **Lottie Animations**: https://lottiefiles.com/ (注意许可证)

### 选项 2: 创建自己的表情包
- 使用工具如 Adobe After Effects + Lottie
- 或使用在线工具创建简单动画

### 选项 3: 仅使用静态 Emoji
- 移除 Telegram 表情包功能
- 仅保留标准 Unicode Emoji

## 🔧 配置说明

### emoji_mapping.json
此文件映射 Unicode 编码到文件名，格式如下:

```json
{
  "😀": "1f600",
  "😁": "1f601",
  ...
}
```

### emoji_categories.json
此文件定义 Emoji 分类，格式如下:

```json
{
  "smileys": {
    "name": "笑脸与情感",
    "emojis": ["😀", "😁", "😂", ...]
  },
  ...
}
```

## ⚖️ 许可证建议

如果你使用开源 Emoji 资源，请在项目中添加相应的许可证声明:

### 使用 Twemoji 时添加:
```
Emoji graphics are from Twemoji (https://github.com/twitter/twemoji)
Licensed under CC-BY 4.0: https://creativecommons.org/licenses/by/4.0/
```

### 使用 Noto Emoji 时添加:
```
Emoji graphics are from Noto Emoji (https://github.com/googlefonts/noto-emoji)
Licensed under Apache License 2.0
```

## 🚫 不要做的事

1. ❌ 不要从 Apple 设备直接提取 Emoji 图片
2. ❌ 不要从 Telegram 应用直接提取表情包
3. ❌ 不要使用未经授权的商业表情包
4. ❌ 不要将有版权的资源上传到公开仓库

## ✅ 最佳实践

1. ✅ 使用开源 Emoji 库（Twemoji, Noto Emoji）
2. ✅ 在 README 中声明 Emoji 资源来源和许可证
3. ✅ 提供用户自行下载 Emoji 的说明
4. ✅ 考虑使用 CDN 而不是本地存储

## 📞 获取帮助

如果你不确定某个资源是否可以使用，请:
1. 检查资源的许可证
2. 联系资源的创作者
3. 咨询法律专业人士

---

**重要提示**: 本指南仅供参考，不构成法律建议。使用任何资源前，请确保你有合法的使用权限。
