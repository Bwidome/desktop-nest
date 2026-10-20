# 桌面收纳 · Desktop Nest

把杂乱的 Windows 桌面**收进一个隐藏目录**，还你一张干净的桌面。

桌面上的文件、文件夹、快捷方式会被一次性移入 `~/.desktop-nest/`，然后通过一条贴底悬浮的 **Dock** 随时取用。Dock 支持长按排序、Nexus 风格的弹簧让位动画，并在别的窗口压住它时自动让开。

<p align="center">
  <img src="shots/panel-main.png" alt="主面板：收纳状态、常用启动、空间统计" width="760">
</p>

<p align="center">
  <sub>纯 Python + PyQt6 原生桌面应用，不是 Electron，没有 Web 技术栈。</sub>
</p>

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [界面预览](#界面预览)
- [核心功能](#核心功能)
- [交互速查](#交互速查)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [安装与快速开始](#安装与快速开始)
- [开发运行](#开发运行)
- [测试与自检](#测试与自检)
- [构建与打包](#构建与打包)
- [项目目录结构](#项目目录结构)
- [核心模块说明](#核心模块说明)
- [设计系统与实现细节](#设计系统与实现细节)
- [已知限制](#已知限制)
- [开发计划](#开发计划)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 它解决什么问题

Windows 桌面越用越乱：临时文件、下载的安装包、几十个快捷方式摊满一屏，找东西全靠肉眼。

常见做法是建个“待整理”文件夹自己拖进去，但**桌面空了，东西也就不好找了**。

这个项目的取舍是：**桌面要空，但要随时够得着。**

- 文件是**移动**到隐藏目录，不是删除，随时能打开、还原、撤销；
- 桌面上只留一条贴底的悬浮 Dock，常用软件一键直达；
- 退出程序时自动把东西放回桌面，不留“后遗症”。

---

## 界面预览

### 底部 Dock

Dock 是纯透明的悬浮条，只有图标浮在桌面之上（左起第一个「桌面整理」入口，随后是常用启动）。

<table>
<tr>
<td width="50%" align="center"><img src="shots/dock.png" alt="底部 Dock"><br><sub>常态：纯透明底 + 图标浮层</sub></td>
<td width="50%" align="center"><img src="shots/dock-reorder.png" alt="长按拖拽排序，其余图标弹簧让位"><br><sub>长按拖拽排序：其余图标弹簧让位</sub></td>
</tr>
</table>

### 收纳面板（上滑磨砂玻璃浮层）

点 Dock 最左边的「桌面整理」打开，DWM 提供真正的背景模糊，再按圆角裁一刀。

<table>
<tr>
<td width="50%" align="center"><img src="shots/popup-glass.png" alt="收纳面板"><br><sub>分页浏览 + 搜索 + 右键菜单</sub></td>
<td width="50%" align="center"><img src="shots/popup-manage.png" alt="管理模式"><br><sub>管理模式：卡片角标增删常用</sub></td>
</tr>
</table>

> 仓库目前只有上述 5 张静态截图，**没有 GIF 或演示视频**。如果你需要动图演示（拖拽排序、窗口自动让开），见 [开发计划](#开发计划)。

---

## 核心功能

### 桌面收纳

| 能力 | 说明 |
|---|---|
| 一键收纳 | 桌面上的文件 / 文件夹 / 快捷方式移入 `~/.desktop-nest/desktop/`，桌面变空 |
| 同时处理公共桌面 | 个人桌面与 `C:\Users\Public\Desktop` 一起收，还原时各回各家 |
| 收纳后隐藏图标 | 走 Explorer 的 `HideIcons`，做到“桌面完全空白”而不是“图标还在只是被盖住” |
| 自动收纳 / 自动还原 | 启动时收纳、退出时还原，两项都可单独关闭 |
| 收纳流水与撤销 | 每次收纳 / 还原都记一条，可在主面板「操作历史」页逐条**撤销**；撤销不弹确认框，连点几行就是连续撤销 |
| 冲突处理 | 重名自动加序号；还原遇同名可选「替换 / 跳过 / 取消」，**任何情况下都不静默覆盖** |
| 安全校验 | 拒绝盘符根目录、系统文件（`desktop.ini` 等）、收纳目录自身 |
| 应急还原 | `--restore` 一个命令把东西全部搬回桌面，不依赖 Python 环境（已做进 exe） |

### 底部 Dock

- **纯透明**、无边框、始终置顶的贴底悬浮条，图标之间是真实的桌面背景
- **可拖到屏幕任意位置**（横竖都行），位置写入配置，重启后回到原处
- 图标多了**自动换行**，永不跑出屏幕，也不会被挤扁
- 单击启动、拖动整条、**长按 320ms 进入排序**
- 可以直接把文件 / 快捷方式**从资源管理器拖进 Dock**，立即加为常用

### 常用启动与拖拽排序

- 在收纳面板进入「管理模式」，点卡片角上的 `＋ / －` 增删；角标分左上（已常用）/ 右上（未常用）
- 支持「从文件添加常用软件…」与「批量移除常用软件…」
- 也可以在面板里**长按卡片拖到顶部常用栏**加入
- 排序：长按图标 → 拖动 → 其余图标**弹簧让位** → 松手落位，顺序当场写盘，重启保持

### Nexus 风格弹簧动画

排序不是“瞬间跳格”，而是每个图标挂一个独立弹簧积分器逐帧求解：

| 角色 | stiffness | damping ratio | 手感 |
|---|---|---|---|
| 让位图标 | `340.0` | `0.80` | 略欠阻尼，到位时轻微过冲一下 |
| 被拖图标 | `2600.0` | `1.0` | 临界阻尼，紧跟指针且**绝不过冲** |

帧循环约 60fps（`PreciseTimer`），积分器带子步长限制，掉帧时不会数值发散；拖拽期间冻结槽位，避免布局和弹簧互相抢位置。

### 窗口避让（Window Dodge）

**已实现并有真机测试**：别的窗口压住 Dock 所在区域时，Dock 自动滑出隐藏；窗口移走 / 缩小 / 最小化 / 关闭后自动滑回。

| 实现要点 | 具体做法 |
|---|---|
| 判定 | `EnumWindows` 枚举全部可见顶层窗口，矩形相交且**横向压住 ≥24px、纵向 ≥6px** 才算遮挡（擦边不算） |
| 排除 | 本进程窗口、不可见 / 最小化、DWM `cloaked`（UWP 挂起、其它虚拟桌面）、桌面与任务栏类名、`WS_EX_TOOLWINDOW` / `WS_EX_NOACTIVATE`、无标题宿主窗口 |
| 触发 | `SetWinEventHook` 挂三段事件（对象显隐/移动/销毁、前台切换、最小化）+ **120ms 兜底轮询**，事件侧只置脏标记并在 60ms 内合并 |
| 动画 | 200ms，位置与不透明度同一曲线驱动：向下滑出 + 淡出 / 从下方滑入 + 淡入 |
| 不挡点击 | 滑出期间给窗口加 `WS_EX_TRANSPARENT`，这 200ms 里点击穿透到底下窗口，结束后立即清除 |
| 边缘唤回 | **只在桌面上生效**：前台窗口是桌面本身、且没人占着 Dock 那块时，鼠标停留 150ms 才唤回，保持 2.5s 并持续续期。全屏播放器 / 浏览器里把鼠标甩到屏幕底部**不会**弹出来 |
| 防闪烁 | 首次响应不等待确认，但两次显隐之间至少间隔 300ms；动画期间冻结状态判断 |

开关在托盘右键菜单：「**窗口遮挡时自动隐藏菜单栏**」（配置项 `dock_avoid_overlap`，默认开启）。关掉后回到“只有最大化 / 全屏窗口才让开”的老行为。

Dock 上右键（图标上和空白处都有）可以直接「**隐藏菜单栏**」，隐藏后从托盘右键菜单勾选「显示底部菜单栏」恢复。

> **验证范围**：该功能在真实桌面上实测通过 61 项断言（真窗口覆盖、移走、最小化、关闭、遮挡时鼠标碰底部不弹、动画位移采样、DPI 坐标换算、自身窗口不误判、双窗口叠加不误判、命中测试）。**多显示器、DPI 动态切换、独占全屏游戏尚未实测**，详见 [已知限制](#已知限制)。

### 收纳面板

- DWM 磨砂玻璃 + 圆角裁切，贴底上滑的浮层，不抢焦点
- 分页浏览，每页数量为 `14 / 21 / 28 / 35 / 42`（默认 28），在面板「更多」菜单里改
- 搜索、卡片两行省略、悬停轻微放大（1.12，不超过 1.15）
- 右键菜单：打开 / 打开文件所在位置 / 加为常用启动 / 还原到桌面 / 复制完整路径 / **删除（移到回收站）**
- 删除走 Windows Shell 的 `SHFileOperationW + FOF_ALLOWUNDO`，与资源管理器按 Delete 同一条路径，**代码里没有任何永久删除调用**

### 主面板与设置

- 主面板两个标签页：「面板内容」与「操作历史」（可对历史操作逐条撤销）
- 设置窗口可改：启动自动收纳 / 退出自动还原 / 收纳后隐藏桌面图标 / 深色主题 / 显示文件后缀名 / 启动时主面板行为 / 被收纳的桌面路径 / 开机自启
- 另有「打开收纳目录」「立刻还原桌面」「清空图标缓存」三个动作按钮

### 外观与主题

- 一套 Design Token 驱动全部配色与尺寸：`light` / `dark` / `glass` 三套语义色板，同一个 QSS 出口
- 磨砂玻璃由 `DwmSetWindowAttribute` 提供：Win11 用 acrylic，Win10 自动退回 blur
- 深色主题是一个开关；玻璃质感用于两张悬浮卡片（主面板、收纳面板），不是独立配色选项

### 工程与可靠性

| 能力 | 说明 |
|---|---|
| 单实例 | 命名互斥体（`Global\`）+ 本地套接字；重复双击会把已有实例的面板叫醒，而不是开第二个 |
| 搬运不阻塞界面 | 收纳 / 还原跑在后台线程，界面走进度回调与 Toast |
| 异常不丢文件 | 移动是逐项进行的，失败项留在原处并计入明细；程序崩溃后下次启动会先还原未完成的部分 |
| 启动自检 | `--selftest` 逐环节打印（Qt 后端、插件目录、单实例闸、构造实例、目录可写），打包后排查“双击没反应”用 |
| 图标缓存 | 按 `devicePixelRatio` 取高清图标并落盘缓存，缓存键含版本号，升级自动失效 |
| 托盘常驻 | 主窗口默认不出现，只驻留托盘 |

---

## 交互速查

### 快捷键

均作用于**收纳面板获得焦点时**（没有全局热键）：

| 按键 | 作用 |
|---|---|
| `Ctrl` + `F` | 聚焦搜索框 |
| `←` `→` | 在图标间移动选中；走到首/尾时自动翻到上一页 / 下一页 |
| `Enter` | 打开选中项 |
| `PageUp` / `PageDown` | 上一页 / 下一页 |
| `Ctrl` + 滚轮 | 翻页（普通滚轮留给滚动条） |
| `Esc` | 有搜索词时先清空，否则隐藏面板 |

### 托盘右键菜单

```
常用启动（子菜单）
管理常用启动…
打开主面板
打开收纳面板（分页浏览）
──────────
显示底部菜单栏
回到桌面自动显示菜单栏
窗口遮挡时自动隐藏菜单栏
──────────
刷新
收纳桌面
还原桌面
──────────
设置
开机自启
退出程序
```

托盘图标：**左键单击**开关收纳面板，**双击**打开主面板。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python（开发环境实测 3.14.3） |
| GUI | **PyQt6 / Qt Widgets**（`qt_compat.py` 优先 PyQt6，可回退 PySide6） |
| Qt 版本 | PyQt6 `6.11.0` + Qt `6.11.2`（见 `libs/*.dist-info`） |
| 原生能力 | `ctypes` 直调 Win32（EnumWindows / SetWinEventHook / DWM / Shell / 注册表），**不依赖 pywin32** |
| 动画 | 自研弹簧积分器 `springs.py` + `QVariantAnimation` |
| 打包 | PyInstaller `6.22.3`，onedir |
| 依赖清单 | `requirements.txt`（仅 `PyQt6>=6.5`，Pillow 为可选项） |

> 没有 `pyproject.toml` / `setup.py`，本项目不以 pip 包形式分发。

---

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | **仅 Windows 10 / 11（64 位）** |
| 打包版运行 | 不需要 Python、不需要 PyQt6，解压即用 |
| 源码运行 | Python + `PyQt6>=6.5`（最低 Python 版本**待确认**，开发环境为 3.14.3） |
| 管理员权限 | 一般不需要；只有 `修复公共桌面.bat` 需要以管理员身份运行 |
| 屏幕缩放 | 已适配 125% / 150% 高 DPI |

> 代码强依赖 `ctypes.windll`、`winreg`、DWM 与 Shell API，**不支持 macOS / Linux**。

---

## 安装与快速开始

### 方式一：使用打包版（面向使用者）

本仓库**不包含预编译二进制**——`.gitignore` 排除了 `desktop-nest-release-*.zip`。需要免安装版本时，按 [构建与打包](#构建与打包) 生成，或从项目 Release 页面下载（若尚未发布，请使用方式二）。

拿到 zip 后：

```
DesktopNest.exe
_internal/
使用说明.txt
LICENSE
```

1. 解压到**任意目录**（桌面、D 盘都行）
2. 双击 `DesktopNest.exe`

> ⚠️ 不要把 `DesktopNest.exe` 单独拖出来——它和同级的 `_internal/` 是一体的，缺了会启动失败。

### 方式二：从源码运行

```bat
git clone https://github.com/Bwidome/desktop-nest.git
cd desktop-nest

:: 1) 装依赖（会自动找 Python，先试 pip，失败则下载到 libs\）
安装依赖.bat

:: 2) 启动
启动桌面收纳.bat
```

等价的手动命令：

```bat
python -m pip install PyQt6
start "" pythonw.exe main.py
```

如果机器上没有可用的 pip，可以改用脚本自带的兜底安装器：

```bat
python setup_libs.py
```

> `libs/` 里自带的是 **CPython 3.12 / win_amd64** 的 wheel。用其它 Python 版本时请走 `pip install PyQt6`，不要依赖 `libs/`。

---

## 开发运行

直接跑源码即可，没有编译步骤：

```bat
python main.py
```

命令行参数（`main.py`）：

| 参数 | 作用 |
|---|---|
| 无参数 | 正常启动，托盘常驻 |
| `--silent` | 不弹任何窗口（开机自启用） |
| `--selftest` | 逐环节启动自检，打印结果后退出 |
| `--restore` | 应急还原：把收纳内容搬回桌面，弹窗汇报 |

启动后发生三件事：底部出现 Dock、桌面内容被收进收纳目录、托盘出现图标。

---

## 测试与自检

项目**没有使用 pytest / unittest**，测试是一组自带 `check()` 与汇总行的独立脚本，由 `dev/run_all.py` 统一调度。测试数量本身就是主要的质量证据。

```bat
:: 跑全部测试套件
python dev\run_all.py

:: 只列出会跑哪些套件
python dev\run_all.py --list

:: 额外生成界面截图到 shots\
python dev\run_all.py --shots

:: 指定解释器 / 按名字过滤
python dev\run_all.py --python <解释器>
python dev\run_all.py test_core test_nest
```

当前规模：**27 个套件、约 1548 项断言**，绝大多数跑在离屏平台（`QT_QPA_PLATFORM=offscreen`）。

其中两个套件需要**真实桌面**（运行时会短暂弹出测试窗口）：

| 套件 | 项数 | 覆盖内容 |
|---|---|---|
| `dev/test_dodge_live.py` | 29 | 真窗口覆盖 / 移走 / 最小化 / 关闭、**遮挡时鼠标碰底部不弹**、动画位移采样 |
| `dev/test_dodge_acceptance.py` | 32 | DPI 换算、自身窗口不自我隐藏、双窗口叠加、遮挡时鼠标碰底部不弹、`WindowFromPoint` 命中测试、cloaked 过滤、钩子不重复注册 |

离屏套件里 `dev/test_dock_edge.py`（29 项）专门盯这次修的两个 bug：边缘唤回的「只在桌面」闸门、保持期不许压过遮挡、两个右键菜单里的「隐藏菜单栏」。

> 在受限（沙箱）环境里，`dev/test_round6.py` 有 2 项会失败：它们需要读取 `C:\$Recycle.Bin` 校验“真的删进回收站”，读不到即失败。这与功能无关，在普通终端下全绿。

其他专用检查：

| 命令 | 作用 |
|---|---|
| `python main.py --selftest` | 8 个环节的启动自检 |
| `python dev\check_release_zip.py` | 把 zip 解压到沙盒、隔离 `USERPROFILE`/`LOCALAPPDATA` 后跑 `--selftest` |
| `python dev\test_release.py` | spec 关键设置、冻结环境自启命令、发行说明、zip 结构 |

---

## 构建与打包

```bat
:: 打包 + 改名 + 补说明 + 压缩，一条命令
python dev\make_release.py --version v1.0

:: 只重新压缩，跳过 PyInstaller
python dev\make_release.py --no-build

:: 指定装了 PyInstaller 与 PyQt6 的解释器
python dev\make_release.py --python <解释器>
```

脚本做三件事：

| 步骤 | 内容 |
|---|---|
| 1. 打包 | 用 `桌面收纳.spec` 跑 PyInstaller（**onedir**），产物落在 `.tmp\release-build\dist\桌面收纳\` |
| 2. 整理 | `桌面收纳.exe` → `DesktopNest.exe`，并拷入 `release\使用说明.txt` |
| 3. 压缩 | 只把产物目录**里面的内容**打进 `desktop-nest-release-<版本>.zip` |

最终结构（解压即用，没有多余的一层目录）：

```
desktop-nest-release-v1.0.zip
├── DesktopNest.exe
├── _internal/            # Qt6 运行库与插件
├── 使用说明.txt
└── LICENSE               # GPL-3.0 全文（分发要求）
```

实测产物约 **41 MB / 195 个条目**。

也可以直接用 PyInstaller（但不会改名、不补说明）：

```bat
python -m PyInstaller 桌面收纳.spec --noconfirm --distpath dist --workpath build
```

> 为什么是 onedir 而不是 onefile：onefile 每次启动要把整包解到 `%TEMP%\_MEIxxxx` 再运行，在受限环境里会卡住；onedir 启动更稳定，也避免图标缓存路径落在临时目录里被清掉。

---

## 项目目录结构

只列有意义的文件；`__pycache__`、`.data`、`.tmp` 等运行期目录已省略。

```
desktop-nest/
├── main.py                  入口：--selftest / --restore / 正常启动
├── tray_app.py              托盘常驻程序，装配所有部件
│
├── dock.py                  底部 Dock：弹簧排序、拖拽、缩放、自动换行
├── dock_dodge.py            窗口避让状态机（Window Dodge）
├── panel.py                 主面板（面板内容 / 操作历史）
├── desktop_browser.py       收纳面板（上滑磨砂玻璃浮层）
├── settings.py              设置窗口
├── widgets.py               共用界面零件（Toast、玻璃卡片、图标按钮…）
│
├── theme.py                 设计系统：三套语义色板 + 唯一 QSS 出口
├── anim.py                  微交互动画（淡入、抬升、对话框缩放）
├── springs.py               弹簧物理积分器
├── acrylic.py               DWM 亚克力 / 模糊
│
├── nest.py                  收纳目录管理（搬运、流水、图标可见性）
├── engine.py                收纳引擎（批量搬运 + 进度回调）
├── safety.py                安全校验（系统目录、系统文件）
├── recycle.py               删除到 Windows 回收站
├── restore_desktop.py       应急还原
├── icons.py                 图标提取 + 磁盘缓存
├── winlink.py               .lnk 创建
├── textutil.py              搜索匹配
│
├── config.py                配置持久化 + 开机自启（HKCU\...\Run）
├── qt_compat.py             Qt 绑定加载器（PyQt6 / PySide6）
├── single_instance.py       单实例守卫（互斥体 + 本地套接字）
├── setup_libs.py            无 pip 时把 PyQt6 wheel 解包到 libs/
├── create_shortcut.py       创建桌面 / 开始菜单快捷方式
├── fix_public_desktop.py    公共桌面修复工具
│
├── 桌面收纳.spec            ← 打包实际使用的 spec
├── release.spec             历史遗留 spec（待确认是否仍在用）
├── requirements.txt         PyQt6>=6.5
├── app.ico                  程序图标
│
├── shots/                   截图（5 张）
├── release/使用说明.txt       发行包内的用户手册模板
├── dev/                     测试、打包、诊断脚本
├── libs/                    自带 PyQt6（~207 MB，已被 .gitignore 排除）
└── *.bat                    7 个双击即用的 Windows 脚本
```

运行时数据（不在仓库里）：

| 路径 | 内容 |
|---|---|
| `%LOCALAPPDATA%\DesktopNest\` | `config.json`、`app.log`、`crash.log` |
| `~/.desktop-nest/` | 收纳根目录：`desktop/`（被收纳的文件）、`links.json`、流水记录 |
| `~/.desktop-nest/desktop/` | 桌面文件实际的落脚处 |

---

## 核心模块说明

| 模块 | 职责 | 关键点 |
|---|---|---|
| `main.py` | 入口与命令行分发 | `--selftest` / `--restore` 都不构造托盘实例，避免抢桌面文件 |
| `tray_app.py` | 装配与调度中心 | 托盘菜单、面板显隐、扫描线程、退出清理 |
| `dock.py` | Dock 控件 | 长按 320ms 判定排序；拖拽期间冻结槽位；纯透明不画底板 |
| `dock_dodge.py` | 窗口避让状态机 | 唯一决策点 `evaluate()`，其他模块不直接 show/hide |
| `desktop_browser.py` | 收纳面板 | 分页、搜索、右键菜单、拖放添加常用 |
| `panel.py` | 主面板 | 两个标签页 + 历史撤销 |
| `nest.py` | 收纳目录 | `nest_root()` 按“已有内容的目录优先”选根，避免换目录后图标全丢 |
| `engine.py` | 搬运引擎 | 后台线程 + 进度回调 + 失败明细 |
| `safety.py` | 安全校验 | 拒绝根目录 / 系统文件 / 收纳目录自身 |
| `theme.py` | 设计系统 | 语义 token → 扁平色板 → QSS，三套 scheme 共用同一组键 |
| `config.py` | 配置与自启 | `%LOCALAPPDATA%` 不可写时退到用户目录，最后退到程序目录 |
| `single_instance.py` | 单实例 | 互斥体是权威判据，套接字负责“叫醒” |
| `qt_compat.py` | Qt 兼容层 | 只在这里 import Qt，其余模块统一从这里取 |

---

## 设计系统与实现细节

<details>
<summary><b>三层 Design Token</b></summary>

1. **语义 token**：`COLOR_TOKENS["light"|"dark"|"glass"]`，三套用完全相同的一组键，所以换主题只换值、不换规则；
2. **扁平色板**：`LIGHT` / `DARK` / `GLASS` 由 token 展开，不是第二套色板；
3. **QSS 规则**：`theme.stylesheet(dark, glass=False)` 是**唯一**样式出口，九类组件（Button / Input / Checkbox / Tab / Card / Tooltip / Toast / Dialog / Menu）各自具备 Hover / Focus / Disabled 三态。

玻璃规则块必须放在整份 QSS 的**最后**：放在中间会被后面同名的 `#Popup { background: ... }` 规则覆盖，表现为“玻璃没生效”。

</details>

<details>
<summary><b>关键参数一览</b></summary>

| 参数 | 值 | 位置 |
|---|---|---|
| 长按排序阈值 | `HOLD_MS = 320` | `dock.py` |
| 让位弹簧 | `stiffness=340.0, ratio=0.80` | `dock.py` |
| 被拖图标弹簧 | `stiffness=2600.0, ratio=1.0` | `dock.py` |
| 避让命中阈值 | 横向 ≥24px、纵向 ≥6px | `dock_dodge.py` |
| 避让轮询 | 120ms；事件合并 60ms | `dock_dodge.py` |
| 显隐动画 | 200ms | `dock_dodge.py` |
| 边缘唤回 | 停留 150ms 触发，保持 2.5s；**仅当前台是桌面时** | `dock_dodge.py` |
| 两次显隐最小间隔 | 300ms | `dock_dodge.py` |
| 每页数量 | `14 / 21 / 28 / 35 / 42` | `desktop_browser.py` |
| 图标缓存版本 | `v5` | `icons.py` |

</details>

<details>
<summary><b>几个踩过的坑（避免回归）</b></summary>

- **高 DPI 字号**：字号必须用 `pt`，用 `px` 会导致系统缩放时只有文字不变大；Dock 图标宽度要按 `QFontMetrics` 实测，写死会被“任务管理器”这类长名字撑叠。
- **Dock 底板**：早期用 `paintEvent` 画阴影，结果整条变成不透明色块；现在是纯透明窗口，不加任何自绘背景。
- **图标边缘**：直接按内容裁切会削掉圆形图标的边缘，需要向外补透明余量（当前裁剪比例 6%，保底 4px）。
- **`ctypes` 句柄**：`GetWindowRect` 等函数必须显式声明 `argtypes` / `restype`，否则 64 位下 `HWND` 会被截断成 `c_int`，表现为“检测永远不成立”。
- **位置被抢**：Dock 有个异步 `_settle` 定时器会矫正位置，滑入动画必须先把位置锁住，否则动画放到一半被搬回原位。
- **onefile 引导器**：在受限环境里会卡在启动阶段，所以发行版固定用 onedir。

</details>

---

## 已知限制

- **仅 Windows**。依赖 Win32 / DWM / Shell，**暂不支持 macOS / Linux**。
- **窗口避让是矩形级判定**，不是像素级：两个窗口叠成“只露出 L 形”这种遮挡算不出来（菜单栏是 TOPMOST，所以“区域被占用”等价于“被挡住”）。
- **窗口避让未实测的场景**：多显示器、DPI 动态切换、独占全屏游戏。代码按“菜单栏所在屏幕 + 各窗口自身矩形”计算，理论正确但缺实机验证。
- **UWP 快捷方式**没有普通文件路径，会退回显示类型图标。
- **收纳目录不能设在桌面内部**，程序会主动拒绝（否则自己搬自己）。
- **系统禁用通知区域**时，程序会记日志并直接显示主面板。
- **开机自启**写 `HKCU\...\Run`，被安全软件拦截时改用「启动」文件夹。
- **杀软误报**：PyInstaller 打包的常见现象，加白名单即可，不是病毒。

---

## 开发计划

以下按当前实际缺口排列，不代表承诺的排期。

**待验证**

- [ ] 多显示器下的避让区域正确性
- [ ] 跨不同缩放比例屏幕拖动时的坐标换算
- [ ] 独占全屏 / 游戏全屏窗口的避让

**待补充**

- [ ] 拖拽排序与窗口避让的 GIF 演示（仓库目前只有静态截图）
- [ ] 源码运行的最低 Python 版本声明（`run.bat` 提示 3.9+，但无代码约束）

**待决定**

- [ ] 是否引入 CI（当前所有测试均为本地手动执行）
- [ ] 是否引入 lint / formatter / 类型检查（当前没有任何配置文件）
- [ ] `release.spec` 与 `桌面收纳.spec` 是否需要合并

---

## 常见问题

<details>
<summary><b>桌面上的文件去哪了？</b></summary>

在 `~/.desktop-nest/desktop/`。这是个普通隐藏文件夹，可以直接在资源管理器里打开查看；也可以在「设置」窗口点「打开收纳目录」跳过去。

</details>

<details>
<summary><b>会不会把我的文件删掉？</b></summary>

不会。收纳与还原都是**移动**，冲突时自动改名而不是覆盖。唯一会“删”的地方是你在收纳面板右键 **删除（移到回收站）**，走的是 Windows 回收站，且盘符根目录、系统文件、收纳目录本身会被拦住。

</details>

<details>
<summary><b>双击没反应怎么办？</b></summary>

先等 10–20 秒（首次要扫描桌面、建图标缓存）。仍然没反应，在程序目录打开命令行执行：

```bat
DesktopNest.exe --selftest
```

它会逐环节打印卡在哪一步。日志在 `%LOCALAPPDATA%\DesktopNest\app.log` 与 `crash.log`。

</details>

<details>
<summary><b>Dock 突然不见了？</b></summary>

先检查托盘菜单里「显示底部菜单栏」是否被取消勾选。如果是被别的窗口挡住后自动让开的，把窗口挪开 / 最小化 / 关掉，Dock 会自己回来；也可以从托盘右键菜单勾选「显示底部菜单栏」立刻叫回来。

> 鼠标停在屏幕底部**不会**再把 Dock 叫出来了——这是有意为之：全屏看视频时鼠标往下甩是去找播放控制条的，那时候弹 Dock 纯属添乱。只有回到桌面、且没有窗口占着 Dock 那块时，鼠标停留才会唤回。

</details>

<details>
<summary><b>桌面空了想立刻恢复？</b></summary>

```bat
DesktopNest.exe --restore
```

或者托盘菜单「还原桌面」。只移动、不删除，重名自动加序号。

</details>

<details>
<summary><b>为什么没有 macOS / Linux 版？</b></summary>

整个实现建立在 Win32 API 之上（窗口枚举、DWM 磨砂、Shell 回收站、注册表自启、`.lnk` 创建），移植等于重写。

</details>

---

## 贡献指南

欢迎提 Issue 与 PR。提交前请确认以下几点。

**1. 先跑测试，确保没有回归**

```bat
python dev\run_all.py
```

如果改动涉及 Dock、收纳面板或窗口避让，请额外跑两个真机套件（会短暂弹出测试窗口）：

```bat
python dev\test_dodge_live.py
python dev\test_dodge_acceptance.py
```

**2. 补测试**

这个项目的测试是自研脚本，不是 pytest。新功能请按现有风格在 `dev/` 下新增 `test_*.py`，用 `check("描述", 条件)` 记录断言，并在结尾打印 `通过 N 项，失败 M 项` 汇总行——`run_all.py` 靠这行解析结果。

**3. 注释写「为什么」**

现有代码大量注释解释的是“为什么这样做”以及“不这样做会踩什么坑”，请保持一致。

**4. 不要提交构建产物**

`libs/`、`.tmp/`、`dist*`、`desktop-nest-release-*.zip` 都已在 `.gitignore` 里。

---

## 许可证

本项目以 **GNU General Public License v3.0** 分发，完整条款见 [LICENSE](LICENSE)。

```
Desktop Nest（桌面收纳）
Copyright (C) 2026 Bwisdome

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```

### 为什么是 GPL-3.0

界面依赖 **PyQt6**，它采用 **GPL v3 / 商业授权双许可**。发行包（`desktop-nest-release-*.zip`）里打包了 PyQt6 与 Qt6 的二进制，按 GPL v3 的要求，整个作品需要以 GPL v3 兼容的方式授权，并向接收者提供对应源码。

如果将来想改用更宽松的协议（例如 MIT），需要先换成 **PySide6**（LGPLv3）或取得 PyQt6 商业授权。`qt_compat.py` 已经预留了 PySide6 回退，改造是可行的，但当前发行链条仍是 PyQt6。

### 分发时请注意

- 分发 `desktop-nest-release-*.zip` 时，需同时提供本项目的对应源码（给出仓库地址即可）。
- 发行包里已自动带上 `LICENSE`（`dev/make_release.py` 会拷贝到产物根目录），解压后请保留，不要删掉。
