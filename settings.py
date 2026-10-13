#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置窗口
========
一个简洁的单页设置，改动即时保存到本地 json。

分三块：
* 收纳行为：启动自动收纳 / 退出自动还原 / 隐藏桌面图标
* 外观与启动：主题、主面板显示时机、桌面位置
* 其他：开机自启、缓存、配置目录
"""

from __future__ import annotations

from pathlib import Path

from qt_compat import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, Qt,
)

import config
import engine
import icons
import nest
import theme as theme_mod


class SettingsDialog(QDialog):
    """设置对话框。"""

    def __init__(self, cfg: config.Config, parent=None, dark: bool = False):
        super().__init__(parent)
        self.cfg = cfg
        self.dark = dark if "dark" not in cfg.data else bool(cfg.get("dark"))
        self.setWindowTitle("设置 · 桌面收纳")
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setStyleSheet(theme_mod.stylesheet(self.dark))
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QLabel("设置")
        title.setObjectName("Title")
        root.addWidget(title)

        # ---- 收纳行为 ----
        root.addWidget(self._section("收纳行为", "决定桌面什么时候被收起来、什么时候放回来"))
        self.chk_auto_take = QCheckBox("启动程序时自动收纳桌面")
        root.addWidget(self.chk_auto_take)
        self.chk_restore_exit = QCheckBox("退出程序时自动还原桌面")
        root.addWidget(self.chk_restore_exit)
        self.chk_hide_icons = QCheckBox("收纳后隐藏桌面图标（让桌面完全空白）")
        root.addWidget(self.chk_hide_icons)

        hint = QLabel(
            "说明：所有文件都只是**移动**到收纳目录，绝不删除。\n"
            "即使程序异常退出，下次启动时也会先把上次没收完的还原回去。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(self._divider())

        # ---- 外观与启动 ----
        root.addWidget(self._section("外观与启动", ""))
        self.chk_dark = QCheckBox("使用深色主题（底部菜单栏固定深色）")
        self.chk_dark.toggled.connect(self._preview_theme)
        root.addWidget(self.chk_dark)

        panel_row = QHBoxLayout()
        panel_row.setSpacing(8)
        panel_hint = QLabel("启动时主面板")
        panel_hint.setObjectName("Hint")
        panel_row.addWidget(panel_hint)
        self.panel_mode = QComboBox()
        self.panel_mode.addItem("第一次运行显示一次（默认）", "first")
        self.panel_mode.addItem("每次启动都显示", "always")
        self.panel_mode.addItem("从不显示，只驻留托盘", "never")
        self.panel_mode.setMinimumWidth(220)
        panel_row.addWidget(self.panel_mode)
        panel_row.addStretch(1)
        root.addLayout(panel_row)

        desktop_row = QHBoxLayout()
        desktop_row.setSpacing(8)
        desktop_hint = QLabel("被收纳的桌面")
        desktop_hint.setObjectName("Hint")
        desktop_row.addWidget(desktop_hint)
        self.desktop_edit = QLineEdit()
        desktop_row.addWidget(self.desktop_edit, 1)
        browse_desktop = QPushButton("浏览…")
        browse_desktop.clicked.connect(self._pick_desktop)
        desktop_row.addWidget(browse_desktop)
        reset_desktop = QPushButton("恢复默认")
        reset_desktop.clicked.connect(
            lambda: self.desktop_edit.setText(str(config.get_desktop_dir())))
        desktop_row.addWidget(reset_desktop)
        root.addLayout(desktop_row)

        root.addWidget(self._divider())

        # ---- 其他 ----
        root.addWidget(self._section("其他", ""))
        self.chk_autostart = QCheckBox("开机自动启动（登录后自动驻留托盘并收纳桌面）")
        root.addWidget(self.chk_autostart)

        info = QLabel(
            f"收纳目录：{nest.nest_root()}\n"
            f"配置文件：{config.config_path()}\n"
            f"图标缓存：{icons.cache_dir()}")
        info.setObjectName("Hint")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(info)

        action_row = QHBoxLayout()
        open_nest = QPushButton("打开收纳目录")
        open_nest.clicked.connect(lambda: engine.open_in_explorer(nest.nest_root()))
        action_row.addWidget(open_nest)
        restore_now = QPushButton("立刻还原桌面")
        restore_now.clicked.connect(self._restore_now)
        action_row.addWidget(restore_now)
        clear_icons = QPushButton("清空图标缓存")
        clear_icons.clicked.connect(self._clear_icon_cache)
        action_row.addWidget(clear_icons)
        action_row.addStretch(1)
        root.addLayout(action_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _section(self, title: str, subtitle: str) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        return frame

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

    # ------------------------------------------------------------------
    def _load(self) -> None:
        self.chk_auto_take.setChecked(bool(self.cfg.get("auto_take_on_start", True)))
        self.chk_restore_exit.setChecked(bool(self.cfg.get("restore_on_exit", True)))
        self.chk_hide_icons.setChecked(bool(self.cfg.get("hide_desktop_icons", True)))
        self.chk_dark.setChecked(bool(self.cfg.get("dark")))
        self.desktop_edit.setText(str(self.cfg.desktop))

        mode = str(self.cfg.get("panel_on_start", "first"))
        index = self.panel_mode.findData(mode)
        self.panel_mode.setCurrentIndex(index if index >= 0 else 0)

        status = config.autostart_status()
        self.chk_autostart.setChecked(
            bool(status) if status is not None else bool(self.cfg.get("autostart")))

    def _preview_theme(self, checked: bool) -> None:
        self.setStyleSheet(theme_mod.stylesheet(checked))

    def _pick_desktop(self) -> None:
        start = Path(self.desktop_edit.text()) if self.desktop_edit.text() else Path.home()
        chosen = config.pick_folder("选择要收纳的桌面目录", start)
        if chosen:
            self.desktop_edit.setText(str(chosen))

    def _clear_icon_cache(self) -> None:
        removed = icons.clear_cache()
        QMessageBox.information(self, "图标缓存", f"已清理 {removed} 个缓存文件。")

    def _restore_now(self) -> None:
        result = nest.restore_to_desktop(Path(self.desktop_edit.text().strip()))
        nest.set_icons_visible(True)
        message = result.summary()
        if result.failed:
            message += "\n\n未能还原：\n" + "\n".join(
                f"· {n}：{r}" for n, r in result.failed[:6])
            QMessageBox.warning(self, "还原桌面", message)
        else:
            QMessageBox.information(self, "还原桌面", message)

    # ------------------------------------------------------------------
    def _save(self) -> None:
        desktop = Path(self.desktop_edit.text().strip())
        if not str(desktop) or not desktop.is_absolute():
            QMessageBox.warning(self, "设置", "桌面路径不合法，请重新选择。")
            return

        self.cfg.update({
            "desktop": str(desktop),
            "dark": bool(self.chk_dark.isChecked()),
            "auto_take_on_start": bool(self.chk_auto_take.isChecked()),
            "restore_on_exit": bool(self.chk_restore_exit.isChecked()),
            "hide_desktop_icons": bool(self.chk_hide_icons.isChecked()),
            "panel_on_start": self.panel_mode.currentData() or "first",
        })

        want_autostart = bool(self.chk_autostart.isChecked())
        if want_autostart != bool(self.cfg.get("autostart")):
            if config.set_autostart(want_autostart):
                self.cfg.set("autostart", want_autostart)
            else:
                QMessageBox.warning(self, "开机自启",
                                    "写入开机自启项失败，可能是权限被拦截。\n"
                                    "可以手动把本程序的快捷方式放进\n"
                                    "「开始菜单 → 启动」文件夹。")
        self.accept()
