# -*- mode: python ; coding: utf-8 -*-
"""
桌面收纳 —— 正式打包脚本
========================
用 `py -3.14 -m PyInstaller 桌面收纳.spec --noconfirm` 打包，
产物在 `dist\\桌面收纳\\桌面收纳.exe`（整个 dist\\桌面收纳 目录要一起拷走）。

关键设置说明（都是踩过坑的地方）：

1. **datas 不要塞 `libs/`**
   `libs/` 是开发时用的自带 PyQt6（约 207 MB）。打包时完全不需要：
   PyInstaller 会从 site-packages 正确收集 PyQt6 和 Qt6 平台插件。
   塞进去只会让成品多出一整套重复的 Qt6 DLL（之前成品 515 MB，就是这个原因）。

2. **upx=False**
   本机没装 upx；而且被压缩过的 Qt DLL 容易被杀软误报，
   也可能触发 Windows 的完整性检查导致进程直接 abort。

3. **console=False**
   正式版不弹黑窗口。出错时 main.py 会自己写日志并弹提示框，
   所以不会出现"双击没反应又看不到原因"的情况。

4. **不打包运行期目录**
   `.data` / `.desktop-nest` / `.icon-cache` 是运行时生成的，
   不要打进成品（之前误打进去了，会导致"配置被固化"）。

5. **hiddenimports 里必须有 `PyQt6.QtNetwork`**
   `single_instance.py` 里那句 `from PyQt6.QtNetwork import ...` 是写在
   `try/except` 里的（拿不到就降级成"只拦不叫醒"），PyInstaller 的静态分析
   容易把这种"包在异常处理里的可选依赖"整个漏掉。漏掉的后果不是崩溃，
   而是**第二个实例被挡住之后，第一个实例不会亮面板**——用户看到的是
   "双击了没反应"。显式写进 hiddenimports 才能带上那个 200KB 左右的 pyd。
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],                      # ← 不塞 libs
    hiddenimports=[
        # 单实例的"叫醒"通道（见文件头第 5 条）。包在 try/except 里的可选依赖，
        # 不显式列出来会被静态分析漏掉。
        'PyQt6.QtNetwork',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 用不到的大件，剔掉能省下几百 MB
        'tkinter', '_tkinter',
        'numpy', 'PIL', 'setuptools', 'pkg_resources',
        'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtDesigner',
        'PyQt6.QtTest', 'PyQt6.QtSql', 'PyQt6.QtBluetooth', 'PyQt6.QtNfc',
        'PyQt6.QtSerialPort', 'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors',
        'PyQt6.QtSpatialAudio', 'PyQt6.QtTextToSpeech',
        'PyQt6.QtPositioning', 'PyQt6.QtHelp', 'PyQt6.QtDBus',
        'PyQt6.QtWebSockets', 'PyQt6.QtWebChannel', 'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets', 'PyQt6.QtStateMachine', 'PyQt6.QtSvg',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='桌面收纳',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # 不压缩，避免误报和完整性检查失败
    console=False,                 # 正式版不弹黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='桌面收纳',
)
