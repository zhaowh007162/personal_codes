# -*- coding: utf-8 -*-
"""
seat_decrypt_ui.py
============================================================
存档 / 备份  解密 · 修改  可视化控制台
（版本通用，不硬编码任何班级姓名；所有窗口均可自由调整大小）
============================================================
功能：
  · 可视化列出 D:/JiXiu（存档）与 D:/Program Files/MMY（备份）
  · 点击任意文件，解密并显示明文，可直接编辑、保存（自动备份）
  · 2.dat（偏好配置）结构化编辑器
  · 8.dat（点名频率）结构化编辑器
  · 11.dat（非意愿同桌列表，≤3 人）结构化编辑器
  · 12.dat（开机自启偏好）结构化编辑器
  · 学生名单从 7.dat 动态读取，本脚本不存储任何班级姓名
  · 一键生成「内置存档代码」：直接复制到 seat_app.py
  · 明文导出 / 从明文导入并加密覆盖
  · 一键删除文件（二次确认）
  · 解析「座位表_*.txt」中的存档码
  · 读取 Windows 注册表教师口令

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
#  ⚙️  用户配置区
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

# salt 必须与 seat_app.py 保持完全一致
FILE_SPECS = [
    ("1.dat",           "password",       "管理员口令",              "archive"),
    ("2.dat",           "desk",           "偏好配置",                "archive"),
    ("3.dat",           "seating",        "座位表（主）",            "archive"),
    ("4.dat",           "pick_menu",      "概率菜单（密码+名单）",   "archive"),
    ("5.dat",           "ui",             "管理员菜单窗口尺寸",      "archive"),
    ("6.dat",           "teacher",        "教师口令",                "archive"),
    ("7.dat",           "students",       "学生名单",                "archive"),
    ("8.dat",           "pick",           "点名频率",                "archive"),
    ("9.dat",           "lastback",       "上次坐后排学生名单",      "archive"),
    ("10.dat",          "recent",         "最近同桌记录",            "archive"),
    ("11.dat",          "non_desired",    "非意愿同桌列表（≤3 人）", "archive"),
    ("12.dat",          "autostart_pref", "开机自启偏好",            "archive"),
    ("chart_bak.dat",   "seating_bak",    "座位表（备）",            "backup"),
    ("recycle_bak.dat", "recent_bak",     "最近同桌记录（备）",      "backup"),
    ("seat_bak.dat",    "lastback_bak",   "上次坐后排名单（备）",    "backup"),
]

SALT_EXPORT_CODE = "export_code"
SALT_TEACHER_REGISTRY = "teacher_registry"
REGISTRY_SUBKEY = r"Software\SeatCrypto\JiXiu"
REGISTRY_VALUE_NAME = "tp"

UI_DEFAULT_WIDTH = 1100
UI_DEFAULT_HEIGHT = 820
UI_MIN_WIDTH = 900
UI_MIN_HEIGHT = 600

MAX_DESK_CHOICES = 14
MAX_NON_DESIRED = 3
DEFAULT_PICK_WEIGHT = 1.0
MAX_PICK_WEIGHT = 20.0


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


def _is_empty_marker(name: str) -> bool:
    return name in ("(空)", "（空）")


# ============================================================
#  📖  动态读取学生名单 / 辅助读取
# ============================================================
def read_7dat_students(archive_dir: str):
    path = os.path.join(archive_dir, "7.dat")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return []
        text = decrypt_text(b64, "students")
    except Exception:
        return []
    names = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not _is_empty_marker(ln):
            names.append(ln)
    return names


def read_2dat_deskmates(archive_dir: str):
    path = os.path.join(archive_dir, "2.dat")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return []
        text = decrypt_text(b64, "desk")
    except Exception:
        return []
    lines = text.splitlines()
    idx = 1
    if len(lines) > 1:
        try:
            int(lines[1].strip())
            idx = 2
        except ValueError:
            idx = 1
    if len(lines) > idx:
        try:
            int(lines[idx].strip())
            idx += 1
        except ValueError:
            pass
    names = []
    for line in lines[idx:]:
        n = line.strip()
        if n and not _is_empty_marker(n):
            names.append(n)
    return names


def read_8dat_names(archive_dir: str):
    path = os.path.join(archive_dir, "8.dat")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return []
        text = decrypt_text(b64, "pick")
    except Exception:
        return []
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",", 1)
        if len(parts) != 2:
            continue
        n = parts[0].strip()
        if n and not _is_empty_marker(n):
            names.append(n)
    return names


def read_11dat_names(archive_dir: str):
    path = os.path.join(archive_dir, "11.dat")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return []
        text = decrypt_text(b64, "non_desired")
    except Exception:
        return []
    names = []
    seen = set()
    for line in text.splitlines():
        n = line.strip()
        if not n or _is_empty_marker(n):
            continue
        if n in seen:
            continue
        seen.add(n)
        names.append(n)
        if len(names) >= MAX_NON_DESIRED:
            break
    return names


def read_12dat_autostart(archive_dir: str):
    path = os.path.join(archive_dir, "12.dat")
    if not os.path.exists(path):
        return "true"
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return "true"
        text = decrypt_text(b64, "autostart_pref").strip().lower()
    except Exception:
        return "true"
    return "true" if text == "true" else "false"


def build_student_list(archive_dir: str, extra_from=None):
    result = []
    seen = set()
    for n in read_7dat_students(archive_dir):
        if n not in seen:
            seen.add(n)
            result.append(n)
    if extra_from:
        for n in extra_from:
            if n and not _is_empty_marker(n) and n not in seen:
                seen.add(n)
                result.append(n)
    return result


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
    QComboBox, QSlider, QDoubleSpinBox, QSpinBox, QInputDialog,
    QRadioButton, QButtonGroup,
)


# ============================================================
#  ★ 所有对话框通用的窗口标志
# ============================================================
DIALOG_FLAGS = (
    Qt.Window
    | Qt.WindowTitleHint
    | Qt.WindowMinMaxButtonsHint
    | Qt.WindowCloseButtonHint
)


# ============================================================
#  FlowLayout
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
#  样式
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


def _build_info_box(fname, salt, desc, loc, path):
    box = QGroupBox("%s  ·  %s" % (fname, desc))
    box.setStyleSheet(QSS_GROUPBOX)
    lay = QGridLayout(box)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setHorizontalSpacing(10)
    lay.setVerticalSpacing(4)

    lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
    val_style = "QLabel { color: #263238; font-size: 12px; }"

    def mk(ridx, tag, value):
        l1 = QLabel(tag); l1.setStyleSheet(lbl_style); l1.setFixedWidth(60)
        v1 = QLabel(value); v1.setStyleSheet(val_style)
        v1.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v1.setWordWrap(True)
        lay.addWidget(l1, ridx, 0)
        lay.addWidget(v1, ridx, 1, 1, 3)

    mk(0, "位置：", "存档" if loc == "archive" else "备份")
    mk(1, "路径：", path)
    if os.path.exists(path):
        mk(2, "状态：", "存在  ·  %s" % fmt_size(os.path.getsize(path)))
    else:
        mk(2, "状态：", "文件不存在")
    mk(3, "salt：", salt)
    return box


# ============================================================
#  ★ 生成"内置存档代码"
# ============================================================
def build_builtin_snippet(field_name: str, text: str) -> str:
    literal = json.dumps(text, ensure_ascii=False)
    return '"%s": %s,' % (field_name, literal)


class BuiltinCodeDialog(QDialog):
    """显示可粘贴到 seat_app.py 的 _BUILTIN_ARCHIVE_JSON 字段"""

    def __init__(self, field_name, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("内置存档代码 —— %s" % field_name)
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(640, 420)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(820, 560)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        tip = QLabel(
            "将下面这一行复制到 seat_app.py 里的 _BUILTIN_ARCHIVE_JSON 中，"
            "覆盖对应字段即可。\n"
            "注意：字段末尾的逗号要保留（最后一个字段除外）。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        field_lbl = QLabel("字段名：%s" % field_name)
        field_lbl.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        v.addWidget(field_lbl)

        snippet = build_builtin_snippet(field_name, text)
        self.code_edit = QTextEdit()
        self.code_edit.setPlainText(snippet)
        self.code_edit.setFont(get_ui_font(11))
        self.code_edit.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 10px;
            }
        """)
        self.code_edit.setMinimumHeight(70)
        self.code_edit.setMaximumHeight(150)
        v.addWidget(self.code_edit)

        ctx_title = QLabel("完整上下文（可整段替换 _BUILTIN_ARCHIVE_JSON）")
        ctx_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        v.addWidget(ctx_title)

        self.ctx_edit = QTextEdit()
        self.ctx_edit.setReadOnly(True)
        self.ctx_edit.setFont(get_ui_font(11))
        self.ctx_edit.setStyleSheet("""
            QTextEdit {
                background: #263238; color: #e0e0e0;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 10px;
            }
        """)
        self.ctx_edit.setPlainText(self._build_context(field_name, text))
        v.addWidget(self.ctx_edit, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_copy_snippet = QPushButton("复制字段行")
        btn_copy_snippet.setStyleSheet(QSS_BTN_PRIMARY)
        btn_copy_snippet.setMinimumHeight(36)
        btn_copy_snippet.setCursor(Qt.PointingHandCursor)
        btn_copy_snippet.clicked.connect(
            lambda: self._copy(self.code_edit.toPlainText(), "字段行")
        )
        btn_row.addWidget(btn_copy_snippet)

        btn_copy_ctx = QPushButton("复制完整上下文")
        btn_copy_ctx.setStyleSheet(QSS_BTN_IMPORT)
        btn_copy_ctx.setMinimumHeight(36)
        btn_copy_ctx.setCursor(Qt.PointingHandCursor)
        btn_copy_ctx.clicked.connect(
            lambda: self._copy(self.ctx_edit.toPlainText(), "完整上下文")
        )
        btn_row.addWidget(btn_copy_ctx)

        btn_row.addStretch()

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(QSS_BTN_NORMAL)
        btn_close.setMinimumHeight(36)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        v.addLayout(btn_row)

    def _build_context(self, field_name, text):
        """根据字段名，生成与 seat_app.py 保持一致的完整 _BUILTIN_ARCHIVE_JSON。"""
        literal = json.dumps(text, ensure_ascii=False)

        desk_literal = '"..."'
        pick_literal = '"..."'
        nd_literal = '"..."'
        autostart_literal = '"true"'

        if field_name == "desk_prefs":
            desk_literal = literal
        elif field_name == "pick_weights":
            pick_literal = literal
        elif field_name == "non_desired_list":
            nd_literal = literal
        elif field_name == "autostart_pref":
            autostart_literal = literal

        return (
            "_BUILTIN_ARCHIVE_JSON = json.dumps(\n"
            "    {\n"
            '        "password": _DEFAULT_PWD,\n'
            '        "teacher_password": "",\n'
            '        "desk_prefs": %s,\n'
            '        "last_seating": "",\n'
            '        "pick_weights": %s,\n'
            '        "non_desired_list": %s,\n'
            '        "autostart_pref": %s,\n'
            "    },\n"
            "    ensure_ascii=False,\n"
            ")"
            % (desk_literal, pick_literal, nd_literal, autostart_literal)
        )

    def _copy(self, text, label):
        try:
            cb = QApplication.clipboard()
            cb.setText(text)
            QMessageBox.information(self, "完成", "已复制到剪贴板（%s）" % label)
        except Exception as e:
            QMessageBox.warning(self, "提示", "复制失败：%s" % e)


# ============================================================
#  ★ 2.dat 偏好配置结构化编辑器
# ============================================================
class DeskPrefsEditorDialog(QDialog):
    def __init__(self, console, parent=None):
        super().__init__(parent)
        self.console = console
        self.fname = "2.dat"
        self.salt = "desk"
        self.desc = "偏好配置"
        self.path = os.path.join(console.archive_dir, "2.dat")

        self.setWindowTitle("偏好配置 (2.dat) —— 结构化编辑")
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(820, 720)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(1000, 900)

        self.pref_student = ""
        self.probability = 80
        self.target_front_prob = 0
        self.deskmates = []

        self._load_current()

        extra = list(self.deskmates)
        if self.pref_student:
            extra.append(self.pref_student)
        self.student_names = build_student_list(
            console.archive_dir, extra_from=extra
        )

        self._build_ui()
        self._refresh_text()

    def _load_current(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            if not b64:
                return
            text = decrypt_text(b64, self.salt)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        lines = text.splitlines()
        if lines:
            p = lines[0].strip()
            if not _is_empty_marker(p):
                self.pref_student = p
        idx = 1
        if len(lines) > 1:
            try:
                p2 = int(lines[1].strip())
                if 0 <= p2 <= 100:
                    self.probability = p2
                    idx = 2
            except ValueError:
                idx = 1
        if len(lines) > idx:
            try:
                b = int(lines[idx].strip())
                if 0 <= b <= 100:
                    self.target_front_prob = b
                    idx += 1
            except ValueError:
                pass
        for line in lines[idx:]:
            name = line.strip()
            if name and not _is_empty_marker(name):
                self.deskmates.append(name)

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        v.addWidget(_build_info_box(
            self.fname, self.salt, self.desc, "archive", self.path
        ))

        pref_row = QHBoxLayout()
        pref_lbl = QLabel("关注学生：")
        pref_lbl.setFixedWidth(80)
        pref_lbl.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        pref_row.addWidget(pref_lbl)

        self.pref_combo = QComboBox()
        self.pref_combo.setMinimumWidth(240)
        self.pref_combo.setMaxVisibleItems(20)
        self.pref_combo.setFont(get_ui_font(10))
        self.pref_combo.setEditable(True)
        self.pref_combo.addItem("（未设置）", "")
        for s in self.student_names:
            self.pref_combo.addItem(s, s)
        self.pref_combo.setCurrentIndex(0)
        if self.pref_student:
            i = self.pref_combo.findData(self.pref_student)
            if i >= 0:
                self.pref_combo.setCurrentIndex(i)
            else:
                self.pref_combo.setEditText(self.pref_student)
        self.pref_combo.setStyleSheet(
            "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
            " border-radius: 4px; background: #ffffff; }"
        )
        self.pref_combo.currentIndexChanged.connect(self._refresh_text)
        self.pref_combo.editTextChanged.connect(self._refresh_text)
        pref_row.addWidget(self.pref_combo)
        pref_row.addStretch()
        v.addLayout(pref_row)

        prob_group = QGroupBox("配对频率")
        prob_group.setStyleSheet(QSS_GROUPBOX)
        pl = QHBoxLayout(prob_group)
        pl.setContentsMargins(12, 8, 12, 10)
        pl.setSpacing(10)
        self.prob_slider = QSlider(Qt.Horizontal)
        self.prob_slider.setRange(0, 100)
        self.prob_slider.setValue(self.probability)
        self.prob_slider.setCursor(Qt.PointingHandCursor)
        self.prob_slider.valueChanged.connect(self._on_prob_changed)
        pl.addWidget(self.prob_slider, 1)
        self.prob_label = QLabel("%d%%" % self.probability)
        self.prob_label.setFixedWidth(56)
        self.prob_label.setAlignment(Qt.AlignCenter)
        self.prob_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; color: #1976d2;"
            " background: #e3f2fd; border-radius: 4px; padding: 3px 0; }"
        )
        pl.addWidget(self.prob_label)
        v.addWidget(prob_group)

        front_group = QGroupBox("关注学生位置倾向（目标坐前排概率）")
        front_group.setStyleSheet(QSS_GROUPBOX)
        fl = QHBoxLayout(front_group)
        fl.setContentsMargins(12, 8, 12, 10)
        fl.setSpacing(10)
        self.front_slider = QSlider(Qt.Horizontal)
        self.front_slider.setRange(0, 100)
        self.front_slider.setValue(self.target_front_prob)
        self.front_slider.setCursor(Qt.PointingHandCursor)
        self.front_slider.valueChanged.connect(self._on_front_changed)
        fl.addWidget(self.front_slider, 1)
        self.front_label = QLabel("%d%%" % self.target_front_prob)
        self.front_label.setFixedWidth(56)
        self.front_label.setAlignment(Qt.AlignCenter)
        self.front_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; color: #2e7d32;"
            " background: #e8f5e9; border-radius: 4px; padding: 3px 0; }"
        )
        fl.addWidget(self.front_label)
        v.addWidget(front_group)

        dm_group = QGroupBox(
            "同桌名单（最多 %d 人，留空表示不使用）" % MAX_DESK_CHOICES
        )
        dm_group.setStyleSheet(QSS_GROUPBOX)
        dm_outer = QVBoxLayout(dm_group)
        dm_outer.setContentsMargins(12, 8, 12, 10)
        dm_outer.setSpacing(6)

        dm_btn_row = QHBoxLayout()
        btn_clear_dm = QPushButton("全部清空")
        btn_clear_dm.setStyleSheet(QSS_BTN_DELETE)
        btn_clear_dm.setMinimumHeight(28)
        btn_clear_dm.setCursor(Qt.PointingHandCursor)
        btn_clear_dm.clicked.connect(self._clear_deskmates)
        dm_btn_row.addWidget(btn_clear_dm)
        dm_btn_row.addStretch()
        dm_outer.addLayout(dm_btn_row)

        dm_scroll = QScrollArea()
        dm_scroll.setWidgetResizable(True)
        dm_scroll.setFrameShape(QScrollArea.NoFrame)
        dm_scroll.setMinimumHeight(280)
        dm_scroll.setStyleSheet(
            "QScrollArea { background: #ffffff; border: 1px solid #cfd8dc;"
            " border-radius: 6px; }"
        )
        dm_content = QWidget()
        dm_content.setStyleSheet("background: transparent;")
        dm_grid = QGridLayout(dm_content)
        dm_grid.setHorizontalSpacing(8)
        dm_grid.setVerticalSpacing(5)
        dm_grid.setContentsMargins(8, 8, 8, 8)

        self.desk_combos = []
        for i in range(MAX_DESK_CHOICES):
            idx_lbl = QLabel("第 %02d 位" % (i + 1))
            idx_lbl.setFixedWidth(60)
            idx_lbl.setStyleSheet(
                "QLabel { color: #607d8b; font-size: 12px; }"
            )
            combo = QComboBox()
            combo.setMinimumWidth(240)
            combo.setMaxVisibleItems(20)
            combo.setFont(get_ui_font(10))
            combo.setEditable(True)
            combo.addItem("（空）", "")
            for s in self.student_names:
                combo.addItem(s, s)
            combo.setCurrentIndex(0)
            if i < len(self.deskmates):
                idx = combo.findData(self.deskmates[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(self.deskmates[i])
            combo.setStyleSheet(
                "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
                " border-radius: 4px; background: #ffffff; }"
            )
            combo.currentIndexChanged.connect(self._refresh_text)
            combo.editTextChanged.connect(self._refresh_text)
            self.desk_combos.append(combo)
            dm_grid.addWidget(idx_lbl, i, 0)
            dm_grid.addWidget(combo, i, 1)

        dm_grid.setRowStretch(MAX_DESK_CHOICES, 1)
        dm_scroll.setWidget(dm_content)
        dm_outer.addWidget(dm_scroll)
        v.addWidget(dm_group, 1)

        txt_group = QGroupBox("生成的原始文本（保存到 2.dat 的明文）")
        txt_group.setStyleSheet(QSS_GROUPBOX)
        tg = QVBoxLayout(txt_group)
        tg.setContentsMargins(12, 8, 12, 10)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(get_ui_font(11))
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.preview.setFixedHeight(120)
        tg.addWidget(self.preview)
        v.addWidget(txt_group, 0)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_reload = QPushButton("重新读取")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setMinimumHeight(36)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(self.btn_reload)

        self.btn_builtin = QPushButton("生成内置代码")
        self.btn_builtin.setStyleSheet(QSS_BTN_PICK)
        self.btn_builtin.setMinimumHeight(36)
        self.btn_builtin.setCursor(Qt.PointingHandCursor)
        self.btn_builtin.clicked.connect(self._show_builtin)
        btn_row.addWidget(self.btn_builtin)

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

    def _on_prob_changed(self, val):
        self.prob_label.setText("%d%%" % val)
        self._refresh_text()

    def _on_front_changed(self, val):
        self.front_label.setText("%d%%" % val)
        self._refresh_text()

    def _current_pref_name(self):
        txt = self.pref_combo.currentText().strip()
        if not txt or txt == "（未设置）":
            return ""
        return txt

    def _clear_deskmates(self):
        for combo in self.desk_combos:
            combo.setCurrentIndex(0)
            combo.setEditText("")
        self._refresh_text()

    def _refresh_text(self):
        pref = self._current_pref_name()
        prob = self.prob_slider.value()
        front = self.front_slider.value()
        lines = [pref, str(prob), str(front)]
        for combo in self.desk_combos:
            txt = combo.currentText().strip()
            if txt and txt != "（空）":
                lines.append(txt)
        self.preview.setPlainText("\n".join(lines))

    def _show_builtin(self):
        text = self.preview.toPlainText()
        dlg = BuiltinCodeDialog("desk_prefs", text, self)
        dlg.exec_()

    def _reload(self):
        self.pref_student = ""
        self.probability = 80
        self.target_front_prob = 0
        self.deskmates = []
        self._load_current()

        extra = list(self.deskmates)
        if self.pref_student:
            extra.append(self.pref_student)
        self.student_names = build_student_list(
            self.console.archive_dir, extra_from=extra
        )

        self.pref_combo.blockSignals(True)
        self.pref_combo.clear()
        self.pref_combo.addItem("（未设置）", "")
        for s in self.student_names:
            self.pref_combo.addItem(s, s)
        if self.pref_student:
            i = self.pref_combo.findData(self.pref_student)
            if i >= 0:
                self.pref_combo.setCurrentIndex(i)
            else:
                self.pref_combo.setEditText(self.pref_student)
        else:
            self.pref_combo.setCurrentIndex(0)
        self.pref_combo.blockSignals(False)

        self.prob_slider.blockSignals(True)
        self.prob_slider.setValue(self.probability)
        self.prob_slider.blockSignals(False)
        self.prob_label.setText("%d%%" % self.probability)

        self.front_slider.blockSignals(True)
        self.front_slider.setValue(self.target_front_prob)
        self.front_slider.blockSignals(False)
        self.front_label.setText("%d%%" % self.target_front_prob)

        for j, combo in enumerate(self.desk_combos):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("（空）", "")
            for s in self.student_names:
                combo.addItem(s, s)
            if j < len(self.deskmates):
                idx = combo.findData(self.deskmates[j])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(self.deskmates[j])
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

        self._refresh_text()

    def _save(self):
        text = self.preview.toPlainText()
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
            QMessageBox.information(
                self, "完成",
                "已保存到：\n%s\n\n原文件已自动备份（.orig.时间戳）" % self.path
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", "写入失败：%s" % e)

    def _export(self):
        os.makedirs(self.console.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            self.console.output_dir, "2.dat_%s.txt" % ts
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.preview.toPlainText())
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

        lines = text.splitlines()
        pref = lines[0].strip() if lines else ""
        if _is_empty_marker(pref):
            pref = ""
        prob = 80
        front = 0
        idx = 1
        if len(lines) > 1:
            try:
                p = int(lines[1].strip())
                if 0 <= p <= 100:
                    prob = p
                    idx = 2
            except ValueError:
                idx = 1
        if len(lines) > idx:
            try:
                b = int(lines[idx].strip())
                if 0 <= b <= 100:
                    front = b
                    idx += 1
            except ValueError:
                pass
        deskmates = []
        for line in lines[idx:]:
            n = line.strip()
            if n and not _is_empty_marker(n):
                deskmates.append(n)

        extra = list(deskmates)
        if pref:
            extra.append(pref)
        self.student_names = build_student_list(
            self.console.archive_dir, extra_from=extra
        )

        self.pref_combo.blockSignals(True)
        self.pref_combo.clear()
        self.pref_combo.addItem("（未设置）", "")
        for s in self.student_names:
            self.pref_combo.addItem(s, s)
        if pref:
            i = self.pref_combo.findData(pref)
            if i >= 0:
                self.pref_combo.setCurrentIndex(i)
            else:
                self.pref_combo.setEditText(pref)
        else:
            self.pref_combo.setCurrentIndex(0)
        self.pref_combo.blockSignals(False)

        self.prob_slider.blockSignals(True)
        self.prob_slider.setValue(prob)
        self.prob_slider.blockSignals(False)
        self.prob_label.setText("%d%%" % prob)

        self.front_slider.blockSignals(True)
        self.front_slider.setValue(front)
        self.front_slider.blockSignals(False)
        self.front_label.setText("%d%%" % front)

        for j, combo in enumerate(self.desk_combos):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("（空）", "")
            for s in self.student_names:
                combo.addItem(s, s)
            if j < len(deskmates):
                idx2 = combo.findData(deskmates[j])
                if idx2 >= 0:
                    combo.setCurrentIndex(idx2)
                else:
                    combo.setEditText(deskmates[j])
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

        self._refresh_text()
        QMessageBox.information(
            self, "完成",
            "已载入 %s\n\n请点「保存（加密回写）」写入文件。" % path
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
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)


# ============================================================
#  ★ 8.dat 点名频率结构化编辑器
# ============================================================
class PickWeightsEditorDialog(QDialog):
    def __init__(self, console, parent=None):
        super().__init__(parent)
        self.console = console
        self.fname = "8.dat"
        self.salt = "pick"
        self.desc = "点名频率"
        self.path = os.path.join(console.archive_dir, "8.dat")

        self.setWindowTitle("点名频率 (8.dat) —— 结构化编辑")
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(700, 720)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(820, 880)

        self.weights = {}

        self._load_current()

        self.student_names = build_student_list(
            console.archive_dir, extra_from=list(self.weights.keys())
        )

        self._build_ui()
        self._refresh_text()

    def _load_current(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            if not b64:
                return
            text = decrypt_text(b64, self.salt)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 1)
            if len(parts) != 2:
                continue
            name = parts[0].strip()
            try:
                w = float(parts[1].strip())
            except ValueError:
                continue
            if name and not _is_empty_marker(name):
                self.weights[name] = w

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        v.addWidget(_build_info_box(
            self.fname, self.salt, self.desc, "archive", self.path
        ))

        tip = QLabel(
            "每位学生的默认值为 1.0。\n"
            "数值越高，越容易出现在结果中；数值为 0 时不会被点到（最多 1 人）。\n"
            "（学生列表来自 7.dat，本脚本不存储任何姓名）"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(400)
        scroll.setStyleSheet(
            "QScrollArea { background: #ffffff; border: 1px solid #cfd8dc;"
            " border-radius: 6px; }"
        )
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(content)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.grid.setContentsMargins(10, 10, 10, 10)

        scroll.setWidget(content)
        v.addWidget(scroll, 1)

        self.spins = {}
        self.prob_labels = {}
        self._rebuild_grid(content)

        txt_group = QGroupBox("生成的原始文本（保存到 8.dat 的明文）")
        txt_group.setStyleSheet(QSS_GROUPBOX)
        tg = QVBoxLayout(txt_group)
        tg.setContentsMargins(12, 8, 12, 10)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(get_ui_font(11))
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.preview.setFixedHeight(110)
        tg.addWidget(self.preview)
        v.addWidget(txt_group, 0)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_reset = QPushButton("全部重置为 1.0")
        self.btn_reset.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reset.setMinimumHeight(36)
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_all)
        btn_row.addWidget(self.btn_reset)

        self.btn_reload = QPushButton("重新读取")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setMinimumHeight(36)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(self.btn_reload)

        self.btn_add = QPushButton("添加一行")
        self.btn_add.setStyleSheet(QSS_BTN_ROSTER)
        self.btn_add.setMinimumHeight(36)
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self._add_row)
        btn_row.addWidget(self.btn_add)

        self.btn_builtin = QPushButton("生成内置代码")
        self.btn_builtin.setStyleSheet(QSS_BTN_PICK)
        self.btn_builtin.setMinimumHeight(36)
        self.btn_builtin.setCursor(Qt.PointingHandCursor)
        self.btn_builtin.clicked.connect(self._show_builtin)
        btn_row.addWidget(self.btn_builtin)

        self.btn_export = QPushButton("导出明文")
        self.btn_export.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_export.setMinimumHeight(36)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export)
        btn_row.addWidget(self.btn_export)

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

    def _rebuild_grid(self, content):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.spins = {}
        self.prob_labels = {}

        h1 = QLabel("学生")
        h1.setStyleSheet(
            "QLabel { color: #455a64; font-size: 12px; font-weight: bold; }"
        )
        h2 = QLabel("权重")
        h2.setStyleSheet(
            "QLabel { color: #455a64; font-size: 12px; font-weight: bold; }"
        )
        h2.setFixedWidth(120)
        h3 = QLabel("占比")
        h3.setStyleSheet(
            "QLabel { color: #455a64; font-size: 12px; font-weight: bold; }"
        )
        h3.setFixedWidth(90)
        self.grid.addWidget(h1, 0, 0)
        self.grid.addWidget(h2, 0, 1)
        self.grid.addWidget(h3, 0, 2)

        for i, name in enumerate(self.student_names, 1):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(
                "QLabel { color: #37474f; font-size: 12px; }"
            )

            spin = QDoubleSpinBox()
            spin.setRange(0.0, MAX_PICK_WEIGHT)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setFixedWidth(120)
            spin.setValue(self.weights.get(name, DEFAULT_PICK_WEIGHT))
            spin.setStyleSheet("""
                QDoubleSpinBox {
                    padding: 3px 6px; border: 1px solid #cfd8dc;
                    border-radius: 4px; background: #ffffff; font-size: 12px;
                }
            """)
            spin.valueChanged.connect(self._refresh_text)

            prob_lbl = QLabel()
            prob_lbl.setFixedWidth(90)
            prob_lbl.setStyleSheet(
                "QLabel { color: #1976d2; font-size: 12px; }"
            )

            self.spins[name] = spin
            self.prob_labels[name] = prob_lbl
            self.grid.addWidget(name_lbl, i, 0)
            self.grid.addWidget(spin, i, 1)
            self.grid.addWidget(prob_lbl, i, 2)

        self.grid.setRowStretch(len(self.student_names) + 1, 1)

    def _add_row(self):
        name, ok = QInputDialog.getText(
            self, "添加一行", "请输入学生姓名：", QLineEdit.Normal, ""
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if name in self.student_names:
            QMessageBox.information(self, "提示", "该学生已在列表中。")
            return
        self.student_names.append(name)
        scroll = self.grid.parentWidget()
        self._rebuild_grid(scroll)
        self._refresh_text()

    def _refresh_text(self):
        total = sum(spin.value() for spin in self.spins.values())
        for name, spin in self.spins.items():
            if total <= 0:
                self.prob_labels[name].setText("—")
            else:
                p = spin.value() / total
                self.prob_labels[name].setText("%.2f%%" % (p * 100))

        lines = []
        for name, spin in self.spins.items():
            v = spin.value()
            if abs(v - DEFAULT_PICK_WEIGHT) > 1e-9:
                lines.append("%s,%s" % (name, v))
        self.preview.setPlainText("\n".join(lines))

    def _show_builtin(self):
        text = self.preview.toPlainText()
        dlg = BuiltinCodeDialog("pick_weights", text, self)
        dlg.exec_()

    def _reset_all(self):
        for spin in self.spins.values():
            spin.blockSignals(True)
            spin.setValue(DEFAULT_PICK_WEIGHT)
            spin.blockSignals(False)
        self._refresh_text()

    def _reload(self):
        self.weights = {}
        self._load_current()
        self.student_names = build_student_list(
            self.console.archive_dir, extra_from=list(self.weights.keys())
        )
        scroll = self.grid.parentWidget()
        self._rebuild_grid(scroll)
        for name, spin in self.spins.items():
            spin.blockSignals(True)
            spin.setValue(self.weights.get(name, DEFAULT_PICK_WEIGHT))
            spin.blockSignals(False)
        self._refresh_text()

    def _save(self):
        text = self.preview.toPlainText()
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
            QMessageBox.information(
                self, "完成",
                "已保存到：\n%s\n\n原文件已自动备份（.orig.时间戳）" % self.path
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", "写入失败：%s" % e)

    def _export(self):
        os.makedirs(self.console.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            self.console.output_dir, "8.dat_%s.txt" % ts
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.preview.toPlainText())
            QMessageBox.information(self, "完成", "已导出：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出失败：%s" % e)

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
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)


# ============================================================
#  ★ 11.dat 非意愿同桌列表编辑器（最多 3 人）
# ============================================================
class NonDesiredEditorDialog(QDialog):
    def __init__(self, console, parent=None):
        super().__init__(parent)
        self.console = console
        self.fname = "11.dat"
        self.salt = "non_desired"
        self.desc = "非意愿同桌列表（≤3 人）"
        self.path = os.path.join(console.archive_dir, "11.dat")

        self.setWindowTitle("非意愿同桌列表 (11.dat) —— 结构化编辑")
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(700, 520)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(820, 640)

        self.names = []

        self._load_current()

        self.student_names = build_student_list(
            console.archive_dir, extra_from=list(self.names)
        )

        self._build_ui()
        self._refresh_text()

    def _load_current(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            if not b64:
                return
            text = decrypt_text(b64, self.salt)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        seen = set()
        for line in text.splitlines():
            n = line.strip()
            if not n or _is_empty_marker(n):
                continue
            if n in seen:
                continue
            seen.add(n)
            self.names.append(n)
            if len(self.names) >= MAX_NON_DESIRED:
                break

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        v.addWidget(_build_info_box(
            self.fname, self.salt, self.desc, "archive", self.path
        ))

        tip = QLabel(
            "最多可设置 %d 名「非意愿同桌」。\n"
            "这些学生永远不会与「关注学生」成为同桌，"
            "优先级高于配对概率（暗改），且严格不破坏后排轮换规则。\n"
            "（学生列表来自 7.dat，本脚本不存储任何姓名）"
            % MAX_NON_DESIRED
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        row_box = QGroupBox("非意愿同桌")
        row_box.setStyleSheet(QSS_GROUPBOX)
        row_lay = QVBoxLayout(row_box)
        row_lay.setContentsMargins(12, 10, 12, 10)
        row_lay.setSpacing(8)

        self.combos = []
        for i in range(MAX_NON_DESIRED):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel("第 %d 位：" % (i + 1))
            lbl.setFixedWidth(70)
            lbl.setStyleSheet(
                "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
            )
            row.addWidget(lbl)

            combo = QComboBox()
            combo.setMinimumWidth(280)
            combo.setMaxVisibleItems(20)
            combo.setFont(get_ui_font(10))
            combo.setEditable(True)
            combo.addItem("（未设置）", "")
            for s in self.student_names:
                combo.addItem(s, s)
            combo.setCurrentIndex(0)
            if i < len(self.names):
                idx = combo.findData(self.names[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(self.names[i])
            combo.setStyleSheet(
                "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
                " border-radius: 4px; background: #ffffff; }"
            )
            combo.currentIndexChanged.connect(self._refresh_text)
            combo.editTextChanged.connect(self._refresh_text)
            self.combos.append(combo)
            row.addWidget(combo)
            row.addStretch()
            row_lay.addLayout(row)

        v.addWidget(row_box)

        txt_group = QGroupBox("生成的原始文本（保存到 11.dat 的明文）")
        txt_group.setStyleSheet(QSS_GROUPBOX)
        tg = QVBoxLayout(txt_group)
        tg.setContentsMargins(12, 8, 12, 10)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(get_ui_font(11))
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.preview.setFixedHeight(110)
        tg.addWidget(self.preview)
        v.addWidget(txt_group, 0)

        v.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_reload = QPushButton("重新读取")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setMinimumHeight(36)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(self.btn_reload)

        self.btn_clear = QPushButton("全部清空")
        self.btn_clear.setStyleSheet(QSS_BTN_DELETE)
        self.btn_clear.setMinimumHeight(36)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_all)
        btn_row.addWidget(self.btn_clear)

        self.btn_builtin = QPushButton("生成内置代码")
        self.btn_builtin.setStyleSheet(QSS_BTN_PICK)
        self.btn_builtin.setMinimumHeight(36)
        self.btn_builtin.setCursor(Qt.PointingHandCursor)
        self.btn_builtin.clicked.connect(self._show_builtin)
        btn_row.addWidget(self.btn_builtin)

        self.btn_export = QPushButton("导出明文")
        self.btn_export.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_export.setMinimumHeight(36)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export)
        btn_row.addWidget(self.btn_export)

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

    def _current_names(self):
        result = []
        seen = set()
        for combo in self.combos:
            txt = combo.currentText().strip()
            if not txt or txt == "（未设置）":
                continue
            if txt in seen:
                continue
            seen.add(txt)
            result.append(txt)
            if len(result) >= MAX_NON_DESIRED:
                break
        return result

    def _refresh_text(self):
        names = self._current_names()
        self.preview.setPlainText("\n".join(names))

    def _clear_all(self):
        for combo in self.combos:
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.setEditText("")
            combo.blockSignals(False)
        self._refresh_text()

    def _show_builtin(self):
        text = self.preview.toPlainText()
        dlg = BuiltinCodeDialog("non_desired_list", text, self)
        dlg.exec_()

    def _reload(self):
        self.names = []
        self._load_current()
        self.student_names = build_student_list(
            self.console.archive_dir, extra_from=list(self.names)
        )
        for i, combo in enumerate(self.combos):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("（未设置）", "")
            for s in self.student_names:
                combo.addItem(s, s)
            if i < len(self.names):
                idx = combo.findData(self.names[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(self.names[i])
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._refresh_text()

    def _save(self):
        text = self.preview.toPlainText()
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
            QMessageBox.information(
                self, "完成",
                "已保存到：\n%s\n\n原文件已自动备份（.orig.时间戳）" % self.path
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", "写入失败：%s" % e)

    def _export(self):
        os.makedirs(self.console.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            self.console.output_dir, "11.dat_%s.txt" % ts
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.preview.toPlainText())
            QMessageBox.information(self, "完成", "已导出：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出失败：%s" % e)

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
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)


# ============================================================
#  ★ 12.dat 开机自启偏好编辑器
# ============================================================
class AutostartEditorDialog(QDialog):
    def __init__(self, console, parent=None):
        super().__init__(parent)
        self.console = console
        self.fname = "12.dat"
        self.salt = "autostart_pref"
        self.desc = "开机自启偏好"
        self.path = os.path.join(console.archive_dir, "12.dat")

        self.setWindowTitle("开机自启偏好 (12.dat) —— 结构化编辑")
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(560, 380)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(640, 440)

        self.current_value = "true"

        self._load_current()
        self._build_ui()
        self._refresh_text()

    def _load_current(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                b64 = f.read().strip()
            if not b64:
                return
            text = decrypt_text(b64, self.salt).strip().lower()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        self.current_value = "true" if text == "true" else "false"

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        v.addWidget(_build_info_box(
            self.fname, self.salt, self.desc, "archive", self.path
        ))

        tip = QLabel(
            "开启后，程序在**非首次运行**时会自动写入开机自启项：\n"
            "  · Windows → HKCU\\...\\Run\\SeatApp_AutoStart\n"
            "  · macOS   → ~/Library/LaunchAgents/com.jixiu.seatapp.plist\n"
            "  · Linux   → ~/.config/autostart/seatapp.desktop\n\n"
            "首次运行（设备第一次输密码）不会写入。\n"
            "在管理员菜单取消勾选后，下次启动也不会再写入。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        mode_box = QGroupBox("开机自启")
        mode_box.setStyleSheet(QSS_GROUPBOX)
        ml = QVBoxLayout(mode_box)
        ml.setContentsMargins(14, 12, 14, 12)
        ml.setSpacing(8)

        self.radio_true = QRadioButton("开启（true）")
        self.radio_false = QRadioButton("关闭（false）")
        self.radio_true.setFont(get_ui_font(11, bold=True))
        self.radio_false.setFont(get_ui_font(11, bold=True))
        self.radio_true.setStyleSheet(
            "QRadioButton { color: #2e7d32; padding: 4px 0; }"
        )
        self.radio_false.setStyleSheet(
            "QRadioButton { color: #c62828; padding: 4px 0; }"
        )
        self.group = QButtonGroup(self)
        self.group.addButton(self.radio_true, 0)
        self.group.addButton(self.radio_false, 1)
        ml.addWidget(self.radio_true)
        ml.addWidget(self.radio_false)
        v.addWidget(mode_box)

        txt_group = QGroupBox("生成的原始文本（保存到 12.dat 的明文）")
        txt_group.setStyleSheet(QSS_GROUPBOX)
        tg = QVBoxLayout(txt_group)
        tg.setContentsMargins(12, 8, 12, 10)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(get_ui_font(11))
        self.preview.setStyleSheet("""
            QTextEdit {
                background: #1e272e; color: #b2bec3;
                border: 1px solid #37474f;
                border-radius: 6px; padding: 8px;
            }
        """)
        self.preview.setFixedHeight(60)
        tg.addWidget(self.preview)
        v.addWidget(txt_group)

        v.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_reload = QPushButton("重新读取")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setMinimumHeight(36)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload)
        btn_row.addWidget(self.btn_reload)

        self.btn_builtin = QPushButton("生成内置代码")
        self.btn_builtin.setStyleSheet(QSS_BTN_PICK)
        self.btn_builtin.setMinimumHeight(36)
        self.btn_builtin.setCursor(Qt.PointingHandCursor)
        self.btn_builtin.clicked.connect(self._show_builtin)
        btn_row.addWidget(self.btn_builtin)

        self.btn_export = QPushButton("导出明文")
        self.btn_export.setStyleSheet(QSS_BTN_IMPORT)
        self.btn_export.setMinimumHeight(36)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export)
        btn_row.addWidget(self.btn_export)

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

        self.radio_true.toggled.connect(self._refresh_text)
        self.radio_false.toggled.connect(self._refresh_text)

        if self.current_value == "false":
            self.radio_false.setChecked(True)
        else:
            self.radio_true.setChecked(True)

    def _current_value(self):
        if self.radio_false.isChecked():
            return "false"
        return "true"

    def _refresh_text(self):
        self.preview.setPlainText(self._current_value())

    def _show_builtin(self):
        text = self.preview.toPlainText()
        dlg = BuiltinCodeDialog("autostart_pref", text, self)
        dlg.exec_()

    def _reload(self):
        self.current_value = "true"
        self._load_current()
        if self.current_value == "false":
            self.radio_false.setChecked(True)
        else:
            self.radio_true.setChecked(True)
        self._refresh_text()

    def _save(self):
        text = self.preview.toPlainText()
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
            QMessageBox.information(
                self, "完成",
                "已保存到：\n%s\n\n原文件已自动备份（.orig.时间戳）\n\n"
                "注意：该偏好仅在下一次启动时生效。" % self.path
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", "写入失败：%s" % e)

    def _export(self):
        os.makedirs(self.console.output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(
            self.console.output_dir, "12.dat_%s.txt" % ts
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "导出明文", default, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.preview.toPlainText())
            QMessageBox.information(self, "完成", "已导出：\n%s" % path)
        except Exception as e:
            QMessageBox.critical(self, "错误", "导出失败：%s" % e)

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
        except Exception as e:
            QMessageBox.critical(self, "错误", "删除失败：%s" % e)


# ============================================================
#  通用文件编辑对话框
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
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(560, 480)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(820, 720)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        v.addWidget(_build_info_box(
            fname, self.salt, self.desc, self.loc, self.path
        ))

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

        self.tip_label = QLabel("")
        self.tip_label.setStyleSheet(
            "QLabel { color: #607d8b; font-size: 12px; }"
        )
        self.tip_label.setWordWrap(True)
        v.addWidget(self.tip_label)

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

    def _reload(self):
        if not os.path.exists(self.path):
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
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(560, 480)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(820, 660)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        tip = QLabel(
            "输入或粘贴「座位表_*.txt」的内容（或直接粘贴以「存档码」开头的段落）。\n"
            "点击「解析」，将解密并显示其中的 JSON。\n"
            "v5 版本存档码新增 non_desired_list 字段（非意愿同桌列表）。"
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

        chunks = []
        in_code = False
        for raw in text.splitlines():
            s = raw.strip()
            if s.startswith("存档码"):
                in_code = True
                continue
            if not in_code:
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
        self.setWindowFlags(DIALOG_FLAGS)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(440, 280)
        self.setStyleSheet("background-color: #fafafa;")
        self.resize(600, 380)

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
        path_label.setWordWrap(True)
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
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(UI_MIN_WIDTH, UI_MIN_HEIGHT)

        self.archive_dir = detect_dir(ARCHIVE_CANDIDATES)
        self.backup_dir = detect_dir(BACKUP_CANDIDATES)
        self.logs_dir = os.path.join(self.backup_dir, "logs")
        self.output_dir = DEFAULT_OUTPUT_DIR

        self._toolbar_widget = None
        self._toolbar_layout = None
        self._right_box = None

        self._build_ui()
        self._refresh_list()

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
            w = min(UI_DEFAULT_WIDTH, max(UI_MIN_WIDTH, avail.width() - 80))
            h = min(UI_DEFAULT_HEIGHT, max(UI_MIN_HEIGHT, avail.height() - 100))
            self.resize(w, h)
            self.move(
                avail.x() + (avail.width() - w) // 2,
                avail.y() + (avail.height() - h) // 2,
            )
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_positioned", False):
            self._positioned = True
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

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet("background-color: #f5f7fa;")

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(10)

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

        dir_box = QGroupBox("目录")
        dir_box.setStyleSheet(QSS_GROUPBOX)
        dir_lay = QGridLayout(dir_box)
        dir_lay.setContentsMargins(12, 10, 12, 10)
        dir_lay.setHorizontalSpacing(10)
        dir_lay.setVerticalSpacing(4)

        self.lbl_archive = self._make_dir_label(self.archive_dir)
        self.lbl_backup = self._make_dir_label(self.backup_dir)
        self.lbl_logs = self._make_dir_label(self.logs_dir)
        self.lbl_output = self._make_dir_label(self.output_dir)

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

        split = QSplitter(Qt.Horizontal)
        split.setStyleSheet("""
            QSplitter::handle { background: #cfd8dc; width: 2px; }
        """)

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
        split.setSizes([480, 520])

        root.addWidget(split, 1)

        self.statusBar().setStyleSheet(
            "QStatusBar { background: #eceff1; color: #37474f; font-size: 12px; }"
        )
        self.statusBar().showMessage("就绪")

        QTimer.singleShot(0, self._refresh_toolbar_height)

    def _make_dir_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("QLabel { color: #263238; font-size: 12px; }")
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setToolTip(text)
        lbl.setWordWrap(True)
        return lbl

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

    def path_of(self, fname):
        spec = spec_of(fname)
        if spec is None:
            return None
        base = self.archive_dir if spec[3] == "archive" else self.backup_dir
        return os.path.join(base, spec[0])

    def _open_item(self, item):
        fname = item.data(Qt.UserRole)
        if not fname:
            return
        spec = spec_of(fname)
        if spec is None:
            return

        # 分发到专用结构化编辑器
        if fname == "2.dat":
            dlg = DeskPrefsEditorDialog(self, self)
        elif fname == "8.dat":
            dlg = PickWeightsEditorDialog(self, self)
        elif fname == "11.dat":
            dlg = NonDesiredEditorDialog(self, self)
        elif fname == "12.dat":
            dlg = AutostartEditorDialog(self, self)
        else:
            dlg = FileEditDialog(self, fname, self)
        dlg.exec_()
        self._refresh_list()

    def _open_current(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        self._open_item(item)

    def _quick_preview(self):
        fname = self._current_fname()
        if not fname:
            QMessageBox.information(self, "提示", "请先选中左侧某个文件。")
            return
        spec = spec_of(fname)
        if spec is None:
            return
        path = self.path_of(fname)
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
        path = self.path_of(fname)
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
        path = self.path_of(fname)
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
            "    · 2.dat（偏好配置）→ 结构化编辑器：\n"
            "        关注学生 / 配对频率 / 目标前排 / 同桌名单\n"
            "    · 8.dat（点名频率）→ 结构化编辑器：\n"
            "        每人权重（默认 1.0，范围 0~20）\n"
            "    · 11.dat（非意愿同桌）→ 结构化编辑器：\n"
            "        最多 3 人，永远不能与关注学生成为同桌\n"
            "    · 12.dat（开机自启偏好）→ 结构化编辑器：\n"
            "        true（开启）/ false（关闭）\n"
            "    · 其他文件 → 通用纯文本编辑器\n"
            "    编辑后下方自动生成「原始文本」，点保存加密回写\n"
            "    原文件会自动备份为 .orig.时间戳\n\n"
            "② ★ 内置存档代码：\n"
            "    在 2 / 8 / 11 / 12 的编辑器里点「生成内置代码」，\n"
            "    会弹出可粘贴到 seat_app.py 的 _BUILTIN_ARCHIVE_JSON\n"
            "    的字段格式，可一键复制。\n\n"
            "③ 学生列表说明：\n"
            "    · 自动从 7.dat 读取，本脚本不存储任何姓名\n"
            "    · 改班级、改名、加减人，脚本自动适配\n"
            "    · 下拉框可手动输入名单里没有的名字\n\n"
            "④ 所有窗口均可自由拖动边缘调整大小（右下角有调整手柄）\n\n"
            "⑤ 顶部工具按钮：\n"
            "    · 刷新列表      重新扫描文件状态\n"
            "    · 打开导出目录  在系统文件管理器中打开\n"
            "    · 解析存档码    解密「座位表_*.txt」中的存档码\n"
            "    · 注册表口令    Windows 上读取教师口令\n\n"
            "════════ 存档文件一览 ════════\n\n"
            "【主存档 D:/JiXiu/】\n"
            "  1.dat  管理员口令\n"
            "  2.dat  偏好配置（关注学生 / 频率 / 目标前排 / 同桌）\n"
            "  3.dat  座位表（主）\n"
            "  4.dat  概率菜单（密码 + 点名名单）\n"
            "  5.dat  管理员菜单窗口尺寸\n"
            "  6.dat  教师口令\n"
            "  7.dat  学生名单\n"
            "  8.dat  点名频率（权重）\n"
            "  9.dat  上次坐后排学生名单\n"
            " 10.dat  最近同桌记录\n"
            " 11.dat  非意愿同桌列表（≤3 人）\n"
            " 12.dat  开机自启偏好（true / false）\n\n"
            "【备份 D:/Program Files/MMY/】\n"
            "  chart_bak.dat    座位表备份\n"
            "  recycle_bak.dat  最近同桌备份\n"
            "  seat_bak.dat     上次坐后排名单备份\n"
            "  logs/            每次导出座位表自动写入明文 txt\n"
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
