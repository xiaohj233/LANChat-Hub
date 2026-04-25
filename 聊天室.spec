# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# PyInstaller 打包配置 - 聊天室（控制台版）
# 目标: Python 3.8 + Windows 7 兼容的独立 EXE
# 命令: pyinstaller 聊天室.spec --clean --noconfirm
# ============================================================

from PyInstaller.building.datastruct import Tree

# 分析阶段：收集依赖与资源
a = Analysis(
    # 入口文件：Flask 聊天应用
    ['main.py'],
    pathex=[],
    binaries=[],
    # 静态资源：初始为空，下面用 Tree 追加
    datas=[],
    # 显式声明隐藏导入，防止 PyInstaller 遗漏
    hiddenimports=[
        # Web 框架核心
        'flask',
        'werkzeug',
        'werkzeug.debug',
        'werkzeug.serving',
        # 标准库（应用直接使用的）
        'sqlite3',
        'hashlib',
        'uuid',
        'mimetypes',
        'json',
        'logging',
        'datetime',
        'socket',
        're',
        'subprocess',
        'html',
        # GUI 密码对话框（Windows 动态导入）
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除不需要的重型库，减小打包体积
    excludes=[
        # 图像处理库（本应用不需要）
        'PIL',
        'Pillow',
        # 科学计算库
        'numpy',
        'pandas',
        'matplotlib',
        'scipy',
        # GUI 框架（仅使用 tkinter）
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        # 加密库（应用使用标准库 hashlib）
        'Crypto',
        'cryptography',
        # 邮件相关
        'email',
        # 测试框架
        'test',
        'unittest',
        # 打包/分发工具
        'distutils',
        'setuptools',
        'pip',
        'wheel',
        # 大体积机器学习库
        'tensorflow',
        'torch',
        # 计算机视觉
        'opencv',
        'cv2',
    ],
    noarchive=False,
    # 字节码优化（-OO：移除 docstring，减小体积提升性能）
    optimize=2,
)

# 静态资源树：递归遍历 static/ 目录，排除 telegram_stickers（版权/体积原因）
a.datas += Tree('static', excludes=['telegram_stickers'])

# PY Z 归档：将纯 Python 模块打包为一个文件
pyz = PYZ(a.pure)

# 生成 EXE
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='聊天室',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩：减小 EXE 体积
    upx=True,
    # UPX 压缩排除列表：防止某些系统 DLL 被 UPX 损坏
    upx_exclude=[
        'api-ms-win-*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
        'ucrtbase*.dll',
    ],
    # 临时目录：None = 系统默认（兼容 Windows 7）
    runtime_tmpdir=None,
    # 显示控制台窗口（推荐：可查看服务器日志）
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
