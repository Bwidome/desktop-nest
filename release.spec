# -*- mode: python ; coding: utf-8 -*-
"""
Desktop Nest —— onefile 打包方案（**当前未采用**，保留备查）
==========================================================
用法：
    py -3.14 -m PyInstaller release.spec --noconfirm
产物：
    dist\\DesktopNest.exe     ← 单文件

⚠️ 为什么发行版**没有**用它：

    实测这个 onefile 产物在受限环境里**起不来** —— 进程停在 11 MB、
    既不建窗口也不退出，`--selftest` 也不输出任何东西。
    同一份代码用 onedir 打包则完全正常（`--selftest` 退出码 0）。

    为排除是本项目代码的问题，另做了一个**最小探针**：只 import PyQt6、
    造一个空 QWidget 就退出，完全不碰本项目任何模块 —— 用 onefile
    打包后同样异常退出。所以问题出在 onefile 的引导器（它需要把自己
    解压到 `%TEMP%\\_MEIxxxx` 再启动），不是业务代码。

    因此发行版走 onedir（见 `桌面收纳.spec`）：启动更快、不依赖
    `%TEMP%` 解包，也不容易被杀软当成"自解压行为"误报。
    压缩包 `desktop-nest-release-v0.1.zip` 里就是 onedir 产物。

如果将来要改用 onefile，请先在有代表性的目标机上验证：
  1. 双击能否出托盘图标与菜单栏；
  2. `DesktopNest.exe --selftest` 退出码是否为 0；
  3. 配置是否落在 `%LOCALAPPDATA%\\DesktopNest`（而不是临时解包目录）。

以下设置无论 onefile / onedir 都适用，都是踩过坑的地方：

1. **datas 不塞 `libs/`**
   `libs/` 是开发时自带的 PyQt6（约 215 MB）。打包完全不需要：
   PyInstaller 会从 site-packages 正确收集 PyQt6 与 Qt6 平台插件。
   塞进去只会多出一整套重复的 Qt6 DLL（曾经把成品撑到 515 MB）。

2. **upx=False**
   本机没装 upx；且被压缩过的 Qt DLL 容易被杀软误报、
   也可能触发 Windows 完整性检查导致进程直接 abort。

3. **路径解析必须对冻结环境安全**
   `config.default_project_dir()` 在冻结时返回 **exe 所在目录**、
   `icons.cache_dir()` 落在 `config.data_dir()`
   （`%LOCALAPPDATA%\\DesktopNest`）下。
   否则配置和图标缓存每次启动都从零开始。

4. **console=False**
   发行版不弹黑窗口。出错时 `main.py` 会自己写日志并弹提示框。
   排查用 `DesktopNest.exe --selftest`；应急还原用 `--restore`。

5. **hiddenimports 必须有 `PyQt6.QtNetwork`**
   `single_instance.py` 里那句 `from PyQt6.QtNetwork import ...` 包在
   `try/except` 中（拿不到就降级成"只拦不叫醒"），PyInstaller 的静态分析
   容易整个漏掉。漏掉的后果不是崩溃，而是**第二个实例被挡住后第一个实例
   不亮面板** —— 用户看到的就是"双击了没反应"。

6. **excludes 剔掉用不到的大件**
   只用到 QtCore / QtGui / QtWidgets / QtNetwork 四个模块。
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # 见文件头第 5 条：包在 try/except 里的可选依赖，静态分析会漏
        'PyQt6.QtNetwork',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'numpy', 'PIL', 'setuptools', 'pkg_resources',
        'test', 'unittest', 'pydoc', 'doctest', 'distutils',
        'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D',
        'PyQt6.QtQuickWidgets', 'PyQt6.QtQuickControls2',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebSockets', 'PyQt6.QtWebChannel',
        'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtDesigner',
        'PyQt6.QtTest', 'PyQt6.QtSql', 'PyQt6.QtBluetooth', 'PyQt6.QtNfc',
        'PyQt6.QtSerialPort', 'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors',
        'PyQt6.QtSpatialAudio', 'PyQt6.QtTextToSpeech',
        'PyQt6.QtPositioning', 'PyQt6.QtHelp', 'PyQt6.QtDBus',
        'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtStateMachine',
        'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtPrintSupport',
        'PyQt6.QtXml', 'PyQt6.QtConcurrent', 'PyQt6.QtUiTools',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DesktopNest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # 见文件头第 2 条
    runtime_tmpdir=None,            # 默认解到 %TEMP%
    console=False,                  # 见文件头第 4 条
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],               # 需求：用工作区里的 app.ico
)

