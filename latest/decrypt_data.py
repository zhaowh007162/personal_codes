# -*- coding: utf-8 -*-
"""
seat_decrypt_ui.py
============================================================
存档 / 备份  解密 · 修改  可视化控制台
（UI 与 seat_app_B.py 风格一致）
============================================================
功能：
  · 可视化列出 D:/JiXiu（存档）与 D:/Program Files/MMY（备份）
  · 点击任意文件，解密并显示明文，可直接编辑、保存（自动备份）
  · 明文导出 / 从明文导入并加密覆盖
  · 一键删除文件（二次确认）
  · 解析「座位表_*.txt」中的存档码
  · 读取 Windows 注册表教师口令
  · 全部默认值写死在代码顶部，可编辑

依赖：
    pip install PyQt5 cryptography
"""

import os
import re
import sys
import json
import base64
import shutil
import secrets
import tempfile
from datetime import datetime


# ============================================================
#  🔐  强加密依赖检测
# ============================================================
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
except ImportError:
    sys.stderr.write(
        "\n缺少密码学库 cryptography\n"
        "请运行：pip install cryptography\n\n"
    )
    sys.exit(1)


# ============================================================
#  ⚙️  用户配置区（写死在代码里，与主程序一一对应）
# ============================================================
MASTER_PASSPHRASE = b"SeatCrypto_v2_Master_@2024#JiXiu!$Secure^Pass%word&2026"
MASTER_SALT = b"SeatCrypto_v2_master_salt_2024_"
PBKDF2_ITERATIONS = 600_000

ARCHIVE_CANDIDATES = [
    "D:/JiXiu",
    os.path.join(os.path.expanduser("~"), ".JiXiu"),
    os.path.join(os.getcwd(), "JiXiu"),
    os.path.join(tempfile.gettempdir(), "JiXiu"),
]

BACKUP_CANDIDATES = [
    "D:/Program Files/MMY",
    os.path.join(os.path.expanduser("~"), ".MMY"),
    os.path.join(os.getcwd(), "Program Files", "MMY"),
    os.path.join(tempfile.gettempdir(), "MMY"),
]

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "seat_export")

FILE_SPECS = [
    ("1.dat",           "password",     "管理员口令",             "archive"),
    ("2.dat",           "desk",         "偏好配置",               "archive"),
    ("3.dat",           "seating",      "座位表（主）",           "archive"),
    ("5.dat",           "ui",           "管理员菜单窗口尺寸",     "archive"),
    ("6.dat",           "teacher",      "教师口令",               "archive"),
    ("7.dat",           "students",     "学生名单",               "archive"),
    ("8.dat",           "pick",         "点名频率",               "archive"),
    ("9.dat",           "lastback",     "上次坐后排学生名单",     "archive"),
    ("10.dat",          "recent",       "最近同桌记录",           "archive"),
    ("chart_bak.dat",   "seating_bak",  "座位表（备）",           "backup"),
    ("recycle_bak.dat", "recent_bak",   "最近同桌记录（备）",     "backup"),
    ("seat_bak.dat",    "lastback_bak", "上次坐后排名单（备）",   "backup"),
]

SALT_EXPORT_CODE = "export_code"
SALT_TEACHER_REGISTRY = "teacher_registry"
REGISTRY_SUBKEY = r"Software\SeatCrypto\JiXiu"
REGISTRY_VALUE_NAME = "tp"

UI_DEFAULT_WIDTH = 900
UI_DEFAULT_HEIGHT = 720


# ============================================================
#  🔑  加密 / 解密
# ============================================================
_MASTER_KEY = None
_FILE_KEY_CACHE = {}


def get_master_key() -> bytes:
    global _MASTER_KEY
    if _MASTER_KEY is None:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=MASTER_SALT,
            iterations=PBKDF2_ITERATIONS,
        )
        _MASTER_KEY = kdf.derive(MASTER_PASSPHRASE)
    return _MASTER_KEY


def get_file_key(salt: str) -> bytes:
    if salt in _FILE_KEY_CACHE:
        return _FILE_KEY_CACHE[salt]
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"seat_file:" + salt.encode("utf-8"),
    )
    key = hkdf.derive(get_master_key())
    _FILE_KEY_CACHE[salt] = key
    return key


def decrypt_text(b64_text: str, salt: str) -> str:
    key = get_file_key(salt)
    aesgcm = AESGCM(key)
    try:
        blob = base64.b64decode(b64_text.encode("ascii"))
    except Exception:
        raise ValueError("数据无法读取，可能是文件已损坏。")
    if len(blob) < 12 + 16:
        raise ValueError("数据无法读取，可能是文件已损坏。")
    nonce = blob[:12]
    ct = blob[12:]
    try:
        pt = aesgcm.decrypt(nonce, ct, None)
    except InvalidTag:
        raise ValueError("认证失败（密钥错误或内容被篡改）。")
    except Exception:
        raise ValueError("数据无法读取，可能是文件已损坏。")
    try:
        return pt.decode("utf-8")
    except Exception:
        raise ValueError("数据无法读取，可能是文件已损坏。")


def encrypt_text(text: str, salt: str) -> str:
    key = get_file_key(salt)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aesgcm.encrypt(nonce, text.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


# ============================================================
#  📁  目录探测
# ============================================================
def _probe_writable(path: str) -> bool:
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".writetest")
        with open(test, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test)
        return True
    except Exception:
        return False


def detect_dir(candidates) -> str:
    for p in candidates:
        if _probe_writable(p):
            return os.path.abspath(p)
    return os.path.abspath(candidates[0]) if candidates else "."


def fmt_size(n: int) -> str:
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


# ============================================================
#  🪟  Windows 注册表
# ============================================================
def read_registry_teacher_password():
    if not sys.platform.startswith("win"):
        return None, "非 Windows 系统，无注册表项。"
    try:
        import winreg
    except ImportError:
        return None, "无法导入 winreg。"
    try:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ
            )
        except FileNotFoundError:
            return None, "未找到注册表项 HKCU\\%s" % REGISTRY_SUBKEY
        try:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
        except FileNotFoundError:
            return None, "注册表值 %s 不存在" % REGISTRY_VALUE_NAME
        finally:
            winreg.CloseKey(key)
        if not value:
            return "", None
        return decrypt_text(value, SALT_TEACHER_REGISTRY), None
    except Exception as e:
        return None, "读取失败：%s" % e


# ============================================================
#  PyQt 导入
# ============================================================
from PyQt5.QtCore import Qt, QTimer, QRect, QSize, QPoint, QEvent
from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QDialog,
    QDialogButtonBox, QFileDialog, QLineEdit, QScrollArea,
    QGroupBox, QTextEdit, QLayout, QSizePolicy, QFrame,
    QListWidget, QListWidgetItem, QSplitter,
)


# ============================================================
#  FlowLayout（与主程序一致）
# ============================================================
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=10, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        if not self._items:
            return QSize(0, 0)
        max_h = 0
        total_w = 0
        count_visible = 0
        for item in self._items:
            wid = item.widget()
            if wid is not None and wid.isHidden():
                continue
            sz = item.sizeHint()
            max_h = max(max_h, sz.height())
            total_w += sz.width()
            count_visible += 1
        if count_visible > 1:
            total_w += self._h_spacing * (count_visible - 1)
        margins = self.contentsMargins()
        return QSize(
            total_w + margins.left() + margins.right(),
            max_h + margins.top() + margins.bottom(),
        )

    def minimumSize(self):
        if not self._items:
            return QSize(0, 0)
        max_w = 0
        max_h = 0
        for item in self._items:
            wid = item.widget()
            if wid is not None and wid.isHidden():
                continue
            sz = item.minimumSize()
            max_w = max(max_w, sz.width())
            max_h = max(max_h, sz.height())
        margins = self.contentsMargins()
        return QSize(
            max_w + margins.left() + margins.right(),
            max_h + margins.top() + margins.bottom(),
        )

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(),
            -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            if wid is not None and wid.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


# ============================================================
#  跨平台中文字体
# ============================================================
_FONT_CACHE = {}


def get_ui_font(size=10, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return QFont(_FONT_CACHE[key])

    preferred = [
        "Microsoft YaHei UI", "Microsoft YaHei",
        "PingFang SC", "Hiragino Sans GB",
        "Noto Sans CJK SC", "WenQuanYi Micro Hei",
        "Source Han Sans SC", "SimHei", "SimSun",
    ]
    chosen = None
    try:
        families = set(QFontDatabase().families())
        for name in preferred:
            if name in families:
                chosen = name
                break
    except Exception:
        chosen = None

    if chosen:
        f = QFont(chosen, size)
    else:
        f = QFont()
        f.setPointSize(size)
    f.setBold(bold)
    _FONT_CACHE[key] = f
    return QFont(f)


# ============================================================
#  样式（与主程序一致）
# ============================================================
QSS_BTN_PRIMARY = """
QPushButton {
    background-color: #1976d2; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #1565c0; }
QPushButton:pressed{ background-color: #0d47a1; }
"""
QSS_BTN_NORMAL = """
QPushButton {
    background-color: #eceff1; color: #37474f;
    border: 1px solid #cfd8dc; border-radius: 6px;
    padding: 8px 16px; font-size: 14px;
}
QPushButton:hover  { background-color: #e0e6e9; }
QPushButton:pressed{ background-color: #cfd8dc; }
"""
QSS_BTN_PICK = """
QPushButton {
    background-color: #7e57c2; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #673ab7; }
QPushButton:pressed{ background-color: #512da8; }
"""
QSS_BTN_TEACHER = """
QPushButton {
    background-color: #00897b; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #00796b; }
QPushButton:pressed{ background-color: #00695c; }
"""
QSS_BTN_IMPORT = """
QPushButton {
    background-color: #fb8c00; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #f57c00; }
QPushButton:pressed{ background-color: #ef6c00; }
"""
QSS_BTN_ROSTER = """
QPushButton {
    background-color: #26a69a; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #00897b; }
QPushButton:pressed{ background-color: #00695c; }
"""
QSS_BTN_DELETE = """
QPushButton {
    background-color: #ef5350; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 6px 14px; font-size: 12px; font-weight: bold;
}
QPushButton:hover  { background-color: #e53935; }
QPushButton:pressed{ background-color: #c62828; }
"""
QSS_BTN_CLOSE = """
QPushButton {
    background-color: #ef5350; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 0px;
    font-size: 20px; font-weight: bold;
}
QPushButton:hover  { background-color: #e53935; }
QPushButton:pressed{ background-color: #c62828; }
"""
QSS_BTN_SYMBOL = """
QPushButton {
    background-color: #eceff1; color: #37474f;
    border: 1px solid #cfd8dc; border-radius: 6px;
    padding: 0px;
    font-size: 20px; font-weight: bold;
}
QPushButton:hover  { background-color: #e0e6e9; }
QPushButton:pressed{ background-color: #cfd8dc; }
"""
QSS_GROUPBOX = """
QGroupBox {
    font-size: 13px; font-weight: bold; color: #37474f;
    border: 1px solid #cfd8dc; border-radius: 6px;
    margin-top: 10px; padding-top: 10px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px; padding: 0 4px;
}
"""
QSS_INPUT = """
QLineEdit {
    padding: 5px 8px; border: 1px solid #cfd8dc;
    border-radius: 4px; background: #ffffff; font-size: 12px;
}
"""


# ============================================================
#  文件信息辅助
# ============================================================
def spec_of(name):
    low = name.lower()
    for spec in FILE_SPECS:
        if spec[0].lower() == low:
            return spec
    return None


# ============================================================
#  文件编辑对话框
# ============================================================
class FileEditDialog(QDialog):
    def __init__(self, console, fname, parent=None):
        super().__init__(parent)
        self.console = console
        self.fname = fname
        spec = spec_of(fname)
        self.salt = spec[1]
        self.desc = spec[2]
        self.loc = spec[3]
        self.path = console.path_of(fname)

        self.setWindowTitle("查看 / 编辑 —— %s（%s）" % (fname, self.desc))
        self.setMinimumSize(560, 480)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(760, 640)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        # —— 顶部信息条 ——
        info_box = QGroupBox("%s  ·  %s" % (fname, self.desc))
        info_box.setStyleSheet(QSS_GROUPBOX)
        info_lay = QGridLayout(info_box)
        info_lay.setContentsMargins(12, 10, 12, 10)
        info_lay.setHorizontalSpacing(10)
        info_lay.setVerticalSpacing(4)

        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        val_style = "QLabel { color: #263238; font-size: 12px; }"

        l1 = QLabel("位置："); l1.setStyleSheet(lbl_style); l1.setFixedWidth(60)
        self.lbl_loc = QLabel("存档" if self.loc == "archive" else "备份")
        self.lbl_loc.setStyleSheet(val_style)

        l2 = QLabel("路径："); l2.setStyleSheet(lbl_style); l2.setFixedWidth(60)
        self.lbl_path = QLabel(self.path)
        self.lbl_path.setStyleSheet(val_style)
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)

        l3 = QLabel("状态："); l3.setStyleSheet(lbl_style); l3.setFixedWidth(60)
        self.lbl_status = QLabel("—")
        self.lbl_status.setStyleSheet(val_style)

        l4 = QLabel("salt："); l4.setStyleSheet(lbl_style); l4.setFixedWidth(60)
        self.lbl_salt = QLabel(self.salt)
        self.lbl_salt.setStyleSheet(val_style)
        self.lbl_salt.setTextInteractionFlags(Qt.TextSelectableByMouse)

        info_lay.addWidget(l1, 0, 0); info_lay.addWidget(self.lbl_loc, 0, 1, 1, 3)
        info_lay.addWidget(l2, 1, 0); info_lay.addWidget(self.lbl_path, 1, 1, 1, 3)
        info_lay.addWidget(l3, 2, 0); info_lay.addWidget(self.lbl_status, 2, 1, 1, 3)
        info_lay.addWidget(l4, 3, 0); info_lay.addWidget(self.lbl_salt, 3, 1, 1, 3)

        v.addWidget(info_box)

        # —— 明文编辑区 ——
        edit_title = QLabel("明文内容（可直接编辑）")
        edit_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        v.addWidget(edit_title)

        self.editor = QTextEdit()
        self.editor.setFont(get_ui_font(11))
        self.editor.setStyleSheet("""
            QTextEdit {
                background: #ffffff;
                border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 8px;
                color: #263238;
            }
        """)
        self.editor.setMinimumHeight(240)
        v.addWidget(self.editor, 1)

        # —— 状态提示 ——
        self.tip_label = QLabel("")
        self.tip_label.setStyleSheet(
            "QLabel { color: #607d8b; font-size: 12px; }"
        )
        v.addWidget(self.tip_label)

        # —— 底部按钮 ——
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_reload = QPushButton("重新读取")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setMinimumHeight(36)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(self.btn_reload)

        self.btn_export = QPushButton("导出明文")
        self.btn_export.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_export.setMinimumHeight(36)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export)
        btn_row.addWidget(self.btn_export)

        self.btn_import = QPushButton("从明文导入")
        self.btn_import.setStyleSheet(QSS_BTN_ROSTER)
        self.btn_import.setMinimumHeight(36)
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.clicked.connect(self._import)
        btn_row.addWidget(self.btn_import)

        self.btn_delete = QPushButton("删除文件")
        self.btn_delete.setStyleSheet(QSS_BTN_DELETE)
        self.btn_delete.setMinimumHeight(36)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self._delete)
        btn_row.addWidget(self.btn_delete)

        btn_row.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Save).setText("保存（加密回写）")
        btns.button(QDialogButtonBox.Close).setText("关闭")
        btns.button(QDialogButtonBox.Save).setStyleSheet(QSS_BTN_PRIMARY)
        btns.button(QDialogButtonBox.Save).setMinimumHeight(36)
        btns.button(QDialogButtonBox.Save).setCursor(Qt.PointingHandCursor)
        btns.button(QDialogButtonBox.Close).setStyleSheet(QSS_BTN_NORMAL)
        btns.button(QDialogButtonBox.Close).setMinimumHeight(36)
        btns.button(QDialogButtonBox.Close).setCursor(Qt.PointingHandCursor)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        btn_row.addWidget(btns)

        v.addLayout(btn_row)

        self._reload()

    # --------------------------------------------------------
    def _reload(self):
        exists = os.path.exists(self.path)
        size = fmt_size(os.path.getsize(self.path)) if exists else "-"
        self.lbl_status.setText(
            ("存在  ·  %s" % size) if exists else "文件不存在"
        )
        if not exists:
            self.editor.setPlainText("")
            self.tip_label.setText("（文件不存在，可编辑后保存创建）")
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            text = "" if not b64 else decrypt_text(b64, self.salt)
            self.editor.setPlainText(text)
            self.tip_label.setText(
                "已解密，%d 字符。修改后点「保存（加密回写）」即可。" % len(text)
            )
        except Exception as e:
            self.editor.setPlainText("")
            self.tip_label.setText("[读取失败] %s" % e)

    def _save(self):
        text = self.editor.toPlainText()

        if os.path.exists(self.path):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak = "%s.orig.%s" % (self.path, ts)
            try:
                shutil.copy2(self.path, bak)
            except Exception as e:
                QMessageBox.warning(self, "警告", "备份失败：%s" % e)
        try:
            ct = encrypt_text(text, self.salt)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(ct)
            self.tip_label.setText(
                "已加密写入，%d 字符 → %d 字节。原文件已自动备份。" %
                (len(text), len(ct))
            )
            QMessageBox.information(
                self, "完成",
                "已保存到：\n%s\n\n原文件已备份（.orig.时间戳）" % self.path
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", "写入失败：%s" % e)

    def _export(self):
        os.makedirs(self.console.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            self.console.output_dir, "%s_%s.txt" % (self.fname, ts)
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            QMessageBox.information(self, "完成", "已导出：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出失败：%s" % e)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "从明文导入", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="gbk") as f:
                    text = f.read()
            except Exception as e:
                QMessageBox.critical(self, "错误", "读取失败：%s" % e)
                return
        except Exception as e:
            QMessageBox.critical(self, "错误", "读取失败：%s" % e)
            return
        self.editor.setPlainText(text)
        self.tip_label.setText(
            "已载入 %s（%d 字符），点保存加密覆盖。" % (path, len(text))
        )

    def _delete(self):
        if not os.path.exists(self.path):
            QMessageBox.information(self, "提示", "文件不存在。")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除吗？\n\n%s\n\n此操作不可恢复。" % self.path,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(self.path)
            QMessageBox.information(self, "完成", "已删除。")
            self._reload()
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)


# ============================================================
#  存档码解析对话框
# ============================================================
class DecodeCodeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解析存档码")
        self.setMinimumSize(560, 460)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(720, 600)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        tip = QLabel(
            "输入或粘贴「座位表_*.txt」的内容（或直接粘贴以「存档码」开头的段落）。\n"
            "点击「解析」，将解密并显示其中的 JSON。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        in_title = QLabel("输入")
        in_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        v.addWidget(in_title)

        self.input_edit = QTextEdit()
        self.input_edit.setFont(get_ui_font(10))
        self.input_edit.setPlaceholderText(
            "在此粘贴座位表 txt 内容，或只粘贴存档码段落……"
        )
        self.input_edit.setStyleSheet("""
            QTextEdit {
                background: #ffffff; border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.input_edit.setMinimumHeight(140)
        v.addWidget(self.input_edit, 1)

        out_title = QLabel("解析结果（JSON）")
        out_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        v.addWidget(out_title)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setFont(get_ui_font(10))
        self.output_edit.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.output_edit.setMinimumHeight(180)
        v.addWidget(self.output_edit, 1)

        btn_row = QHBoxLayout()

        self.btn_from_file = QPushButton("从文件读取")
        self.btn_from_file.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_from_file.setMinimumHeight(36)
        self.btn_from_file.setCursor(Qt.PointingHandCursor)
        self.btn_from_file.clicked.connect(self._load_file)
        btn_row.addWidget(self.btn_from_file)

        self.btn_parse = QPushButton("解析")
        self.btn_parse.setStyleSheet(QSS_BTN_PRIMARY)
        self.btn_parse.setMinimumHeight(36)
        self.btn_parse.setCursor(Qt.PointingHandCursor)
        self.btn_parse.clicked.connect(self._parse)
        btn_row.addWidget(self.btn_parse)

        self.btn_save = QPushButton("保存结果")
        self.btn_save.setStyleSheet(QSS_BTN_ROSTER)
        self.btn_save.setMinimumHeight(36)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_result)
        btn_row.addWidget(self.btn_save)

        btn_row.addStretch()

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(QSS_BTN_NORMAL)
        btn_close.setMinimumHeight(36)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        v.addLayout(btn_row)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择座位表 txt", "", "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="gbk") as f:
                text = f.read()
        except Exception as e:
            QMessageBox.critical(self, "错误", "读取失败：%s" % e)
            return
        self.input_edit.setPlainText(text)

    def _parse(self):
        text = self.input_edit.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "提示", "请先输入内容。")
            return

        # 找出存档码块
        chunks = []
        in_code = False
        found_header = False
        for raw in text.splitlines():
            s = raw.strip()
            if s.startswith("存档码"):
                in_code = True
                found_header = True
                continue
            if not in_code:
                # 也兼容直接粘贴密文（无头部）
                if re.fullmatch(r"[A-Za-z0-9+/=]{40,}", s):
                    chunks.append(s)
                continue
            if s.startswith("（删除存档码"):
                break
            if not s:
                continue
            if s.startswith("-") or s.startswith("="):
                continue
            if re.match(r"^第\s*\d+\s*排", s):
                break
            chunks.append(s)

        if not chunks:
            self.output_edit.setPlainText(
                "未找到可解析的存档码块。\n"
                "请确认粘贴的内容包含「存档码：」段落，"
                "或直接粘贴纯 base64 密文。"
            )
            return

        b64 = "".join(chunks)
        try:
            raw_json = decrypt_text(b64, SALT_EXPORT_CODE)
        except Exception as e:
            self.output_edit.setPlainText("存档码解密失败：%s" % e)
            return
        try:
            data = json.loads(raw_json)
        except Exception as e:
            self.output_edit.setPlainText(
                "解密成功，但 JSON 解析失败：%s\n\n原文：\n%s" % (e, raw_json)
            )
            return

        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        self.output_edit.setPlainText(pretty)

    def _save_result(self):
        text = self.output_edit.toPlainText()
        if not text.strip():
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            os.path.expanduser("~"), "seat_export", "存档码解析_%s.json" % ts
        )
        os.makedirs(os.path.dirname(default), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存解析结果", default, "JSON 文件 (*.json);;文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "完成", "已保存：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "错误", "保存失败：%s" % e)


# ============================================================
#  注册表查看对话框
# ============================================================
class RegistryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("注册表教师口令")
        self.setMinimumSize(440, 280)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(560, 340)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        title = QLabel("Windows 注册表教师口令")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_ui_font(15, bold=True))
        title.setStyleSheet("QLabel { color: #00695c; padding: 4px 0; }")
        v.addWidget(title)

        path_label = QLabel("路径：HKCU\\%s\n值名：%s"
                            % (REGISTRY_SUBKEY, REGISTRY_VALUE_NAME))
        path_label.setStyleSheet(
            "QLabel { color: #607d8b; font-size: 12px; }"
        )
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(path_label)

        self.result_edit = QLineEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setFont(get_ui_font(14, bold=True))
        self.result_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px 12px; border: 1px solid #cfd8dc;
                border-radius: 6px; background: #ffffff;
                color: #263238;
            }
        """)
        v.addWidget(self.result_edit)

        self.tip = QLabel("")
        self.tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        self.tip.setWordWrap(True)
        v.addWidget(self.tip)

        v.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_refresh = QPushButton("重新读取")
        btn_refresh.setStyleSheet(QSS_BTN_NORMAL)
        btn_refresh.setMinimumHeight(36)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self._refresh)
        btn_row.addWidget(btn_refresh)

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(QSS_BTN_NORMAL)
        btn_close.setMinimumHeight(36)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        v.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        pwd, err = read_registry_teacher_password()
        if err:
            self.result_edit.setText("—")
            self.tip.setText("[提示] %s" % err)
        else:
            self.result_edit.setText(pwd if pwd else "（空）")
            self.tip.setText("已成功读取。")


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("存档解密 · 修改控制台")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self.archive_dir = detect_dir(ARCHIVE_CANDIDATES)
        self.backup_dir = detect_dir(BACKUP_CANDIDATES)
        self.logs_dir = os.path.join(self.backup_dir, "logs")
        self.output_dir = DEFAULT_OUTPUT_DIR

        self._toolbar_widget = None
        self._toolbar_layout = None
        self._right_box = None
        self._drag_pos = None

        self._build_ui()
        self._refresh_list()

    # --------------------------------------------------------
    def _snap_to_screen(self, *args):
        try:
            screen = None
            handle = self.windowHandle() if hasattr(self, "windowHandle") else None
            if handle is not None and hasattr(handle, "screen"):
                try:
                    screen = handle.screen()
                except Exception:
                    screen = None
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            w = min(UI_DEFAULT_WIDTH, max(720, avail.width() - 80))
            h = min(UI_DEFAULT_HEIGHT, max(520, avail.height() - 100))
            self.resize(w, h)
            self.move(
                avail.x() + (avail.width() - w) // 2,
                avail.y() + (avail.height() - h) // 2,
            )
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._snap_to_screen)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_toolbar_height()

    def _refresh_toolbar_height(self):
        if self._toolbar_widget is None or self._toolbar_layout is None:
            return
        try:
            w = self._toolbar_widget.width()
            if w <= 0:
                cw = self.centralWidget()
                if cw is not None:
                    base = cw.width() - 36
                    rb = getattr(self, "_right_box", None)
                    if rb is not None and rb.width() > 0:
                        base -= rb.width() + 10
                    w = max(100, base)
                else:
                    w = max(100, self.width() - 36)
            h = self._toolbar_layout.heightForWidth(w)
            h = max(h, 38)
            self._toolbar_widget.setFixedHeight(h)
        except Exception:
            pass

    # --------------------------------------------------------
    #  鼠标拖动（无边框）
    # --------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    # --------------------------------------------------------
    #  界面
    # --------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet("background-color: #f5f7fa;")

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(10)

        # —— 顶栏：左侧工具按钮 + 右侧功能按钮 ——
        top_bar = QWidget()
        top_bar.setStyleSheet("background: transparent;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        self._toolbar_widget = QWidget()
        self._toolbar_widget.setStyleSheet("background: transparent;")
        self._toolbar_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._toolbar_layout = FlowLayout(
            self._toolbar_widget, margin=0, h_spacing=10, v_spacing=8
        )

        self.btn_refresh = QPushButton("刷新列表")
        self.btn_export_dir = QPushButton("打开导出目录")
        self.btn_decode = QPushButton("解析存档码")
        self.btn_registry = QPushButton("注册表口令")
        self.btn_help = QPushButton("使用说明")

        for btn, style in [
            (self.btn_refresh, QSS_BTN_PRIMARY),
            (self.btn_export_dir, QSS_BTN_NORMAL),
            (self.btn_decode, QSS_BTN_PICK),
            (self.btn_registry, QSS_BTN_TEACHER),
            (self.btn_help, QSS_BTN_ROSTER),
        ]:
            btn.setMinimumHeight(38)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(style)
            self._toolbar_layout.addWidget(btn)

        top_layout.addWidget(self._toolbar_widget, 1)

        right_box = QWidget()
        right_box.setStyleSheet("background: transparent;")
        right_layout = QHBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self._right_box = right_box

        self.btn_minimize = QPushButton("−")
        self.btn_close = QPushButton("×")
        self.btn_minimize.setStyleSheet(QSS_BTN_SYMBOL)
        self.btn_close.setStyleSheet(QSS_BTN_CLOSE)
        self.btn_minimize.setFixedSize(46, 38)
        self.btn_close.setFixedSize(46, 38)
        self.btn_minimize.setToolTip("最小化")
        self.btn_close.setToolTip("关闭")
        for btn in (self.btn_minimize, self.btn_close):
            btn.setCursor(Qt.PointingHandCursor)
            right_layout.addWidget(btn)

        top_layout.addWidget(right_box, 0, Qt.AlignTop)
        root.addWidget(top_bar)

        self.btn_refresh.clicked.connect(self._refresh_list)
        self.btn_export_dir.clicked.connect(self._open_export_dir)
        self.btn_decode.clicked.connect(self._open_decode_code)
        self.btn_registry.clicked.connect(self._open_registry)
        self.btn_help.clicked.connect(self._show_help)
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_close.clicked.connect(self.close)

        # —— 目录信息条 ——
        dir_box = QGroupBox("目录")
        dir_box.setStyleSheet(QSS_GROUPBOX)
        dir_lay = QGridLayout(dir_box)
        dir_lay.setContentsMargins(12, 10, 12, 10)
        dir_lay.setHorizontalSpacing(10)
        dir_lay.setVerticalSpacing(4)

        self.lbl_archive = self._make_dir_label("存档目录", self.archive_dir)
        self.lbl_backup = self._make_dir_label("备份目录", self.backup_dir)
        self.lbl_logs = self._make_dir_label("日志目录", self.logs_dir)
        self.lbl_output = self._make_dir_label("导出目录", self.output_dir)

        dir_lay.addWidget(QLabel("存档目录："), 0, 0)
        dir_lay.addWidget(self.lbl_archive, 0, 1)
        dir_lay.addWidget(QLabel("备份目录："), 1, 0)
        dir_lay.addWidget(self.lbl_backup, 1, 1)
        dir_lay.addWidget(QLabel("日志目录："), 2, 0)
        dir_lay.addWidget(self.lbl_logs, 2, 1)
        dir_lay.addWidget(QLabel("导出目录："), 3, 0)
        dir_lay.addWidget(self.lbl_output, 3, 1)
        for i in range(4):
            lbl = dir_lay.itemAtPosition(i, 0).widget()
            if lbl:
                lbl.setStyleSheet(
                    "QLabel { color: #546e7a; font-size: 12px; }"
                )
                lbl.setFixedWidth(80)
        root.addWidget(dir_box)

        # —— 文件列表 + 预览 ——
        split = QSplitter(Qt.Horizontal)
        split.setStyleSheet("""
            QSplitter::handle { background: #cfd8dc; width: 2px; }
        """)

        # 左：文件列表
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        list_title = QLabel("存档 / 备份 文件清单")
        list_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        left_lay.addWidget(list_title)

        self.list_widget = QListWidget()
        self.list_widget.setFont(get_ui_font(11))
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #ffffff;
                border: 1px solid #cfd8dc;
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #f0f3f5;
                color: #37474f;
            }
            QListWidget::item:selected {
                background: #e3f2fd;
                color: #0d47a1;
            }
            QListWidget::item:hover {
                background: #f5f7fa;
            }
        """)
        self.list_widget.itemDoubleClicked.connect(self._open_item)
        left_lay.addWidget(self.list_widget, 1)

        tip = QLabel("双击任意文件 → 查看 / 编辑 / 保存")
        tip.setStyleSheet("QLabel { color: #90a4ae; font-size: 11px; }")
        left_lay.addWidget(tip)

        split.addWidget(left)

        # 右：操作面板
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        op_title = QLabel("操作")
        op_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        right_lay.addWidget(op_title)

        self.btn_open = QPushButton("查看 / 编辑选中项")
        self.btn_open.setStyleSheet(QSS_BTN_PRIMARY)
        self.btn_open.setMinimumHeight(40)
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self._open_current)
        right_lay.addWidget(self.btn_open)

        self.btn_quick_cat = QPushButton("快速预览（只读）")
        self.btn_quick_cat.setStyleSheet(QSS_BTN_ROSTER)
        self.btn_quick_cat.setMinimumHeight(38)
        self.btn_quick_cat.setCursor(Qt.PointingHandCursor)
        self.btn_quick_cat.clicked.connect(self._quick_preview)
        right_lay.addWidget(self.btn_quick_cat)

        self.btn_quick_export = QPushButton("导出选中项明文")
        self.btn_quick_export.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_quick_export.setMinimumHeight(38)
        self.btn_quick_export.setCursor(Qt.PointingHandCursor)
        self.btn_quick_export.clicked.connect(self._quick_export)
        right_lay.addWidget(self.btn_quick_export)

        self.btn_quick_delete = QPushButton("删除选中项")
        self.btn_quick_delete.setStyleSheet(QSS_BTN_DELETE)
        self.btn_quick_delete.setMinimumHeight(38)
        self.btn_quick_delete.setCursor(Qt.PointingHandCursor)
        self.btn_quick_delete.clicked.connect(self._quick_delete)
        right_lay.addWidget(self.btn_quick_delete)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #cfd8dc;")
        right_lay.addWidget(sep)

        preview_title = QLabel("快速预览")
        preview_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        right_lay.addWidget(preview_title)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(get_ui_font(10))
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.preview.setPlaceholderText("选中左侧文件后点「快速预览」查看明文……")
        right_lay.addWidget(self.preview, 1)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        split.setSizes([420, 460])

        root.addWidget(split, 1)

        # —— 状态栏 ——
        self.statusBar().setStyleSheet(
            "QStatusBar { background: #eceff1; color: #37474f; font-size: 12px; }"
        )
        self.statusBar().showMessage("就绪")

        QTimer.singleShot(0, self._refresh_toolbar_height)

    def _make_dir_label(self, tag, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("QLabel { color: #263238; font-size: 12px; }")
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setToolTip(text)
        return lbl

    # --------------------------------------------------------
    #  列表刷新
    # --------------------------------------------------------
    def _refresh_list(self):
        self.list_widget.clear()
        for i, (fname, salt, desc, loc) in enumerate(FILE_SPECS, 1):
            base = self.archive_dir if loc == "archive" else self.backup_dir
            path = os.path.join(base, fname)
            exists = os.path.exists(path)
            size = fmt_size(os.path.getsize(path)) if exists else "-"
            loc_str = "存档" if loc == "archive" else "备份"
            mark = "●" if exists else "○"
            text = ("%s  %-16s  [%s]  %-8s  %-8s  %s"
                    % (mark, fname, loc_str, ("存在" if exists else "缺失"),
                       size, desc))
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, fname)
            if not exists:
                item.setForeground(Qt.gray)
            self.list_widget.addItem(item)

        self.lbl_archive.setText(self.archive_dir)
        self.lbl_backup.setText(self.backup_dir)
        self.lbl_logs.setText(self.logs_dir)
        self.lbl_output.setText(self.output_dir)

        self.statusBar().showMessage(
            "已刷新：存档 %s  ·  备份 %s" % (self.archive_dir, self.backup_dir)
        )

    def _current_fname(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _path_of(self, fname):
        spec = spec_of(fname)
        if spec is None:
            return None
        base = self.archive_dir if spec[3] == "archive" else self.backup_dir
        return os.path.join(base, spec[0])

    # --------------------------------------------------------
    #  打开对话框
    # --------------------------------------------------------
    def _open_item(self, item):
        fname = item.data(Qt.UserRole)
        if not fname:
            return
        spec = spec_of(fname)
        if spec is None:
            return
        dlg = FileEditDialog(self, fname, self)
        dlg.exec_()
        self._refresh_list()

    def _open_current(self):
        fname = self._current_fname()
        if not fname:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        item = self.list_widget.currentItem()
        self._open_item(item)

    def _quick_preview(self):
        fname = self._current_fname()
        if not fname:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        spec = spec_of(fname)
        if spec is None:
            return
        path = self._path_of(fname)
        if not os.path.exists(path):
            self.preview.setPlainText("[文件不存在]\n%s" % path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            text = "" if not b64 else decrypt_text(b64, spec[1])
            self.preview.setPlainText(
                "════════ %s  (%s) ════════\n\n%s"
                % (fname, spec[2], text)
            )
            self.statusBar().showMessage("已预览 %s（%d 字符）"
                                         % (fname, len(text)), 3000)
        except Exception as e:
            self.preview.setPlainText("[读取失败] %s" % e)

    def _quick_export(self):
        fname = self._current_fname()
        if not fname:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        spec = spec_of(fname)
        path = self._path_of(fname)
        if not os.path.exists(path):
            QMessageBox.warning(self, "提示", "文件不存在。")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            text = "" if not b64 else decrypt_text(b64, spec[1])
        except Exception as e:
            QMessageBox.critical(self, "错误", "读取失败：%s" % e)
            return

        os.makedirs(self.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(self.output_dir, "%s_%s.txt" % (fname, ts))
        out, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not out:
            return
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "完成", "已导出：\n%s" % out)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出失败：%s" % e)

    def _quick_delete(self):
        fname = self._current_fname()
        if not fname:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        path = self._path_of(fname)
        if not os.path.exists(path):
            QMessageBox.information(self, "提示", "文件不存在。")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除吗？\n\n%s\n\n此操作不可恢复。" % path,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(path)
            self._refresh_list()
            self.statusBar().showMessage("已删除：%s" % path, 3000)
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)

    def _open_export_dir(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception:
            pass
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.output_dir)
            elif sys.platform == "darwin":
                os.system('open "%s"' % self.output_dir)
            else:
                os.system('xdg-open "%s"' % self.output_dir)
        except Exception as e:
            QMessageBox.information(self, "提示", "导出目录：\n%s\n\n(%s)"
                                    % (self.output_dir, e))

    def _open_decode_code(self):
        dlg = DecodeCodeDialog(self)
        dlg.exec_()

    def _open_registry(self):
        dlg = RegistryDialog(self)
        dlg.exec_()

    def _show_help(self):
        QMessageBox.information(
            self, "使用说明",
            "════════ 使用说明 ════════\n\n"
            "① 双击左侧任意文件 → 打开查看 / 编辑窗口\n"
            "    · 明文可直接修改，点「保存（加密回写）」写入\n"
            "    · 原文件会自动备份为 .orig.时间戳\n\n"
            "② 右键？没有。改用右侧按钮操作：\n"
            "    · 快速预览 → 只读查看明文\n"
            "    · 导出选中项明文 → 保存为 txt\n"
            "    · 删除选中项 → 二次确认后删除\n\n"
            "③ 顶部工具按钮：\n"
            "    · 刷新列表      重新扫描文件状态\n"
            "    · 打开导出目录  在系统文件管理器中打开\n"
            "    · 解析存档码    解密「座位表_*.txt」中的存档码\n"
            "    · 注册表口令    Windows 上读取教师口令\n\n"
            "④ 所有加密参数（密钥、盐、文件 salt）与\n"
            "   seat_app_B.py 完全一致，可直接互相读写。\n"
        )


# ============================================================
#  入口
# ============================================================
def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setFont(get_ui_font(10))

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
