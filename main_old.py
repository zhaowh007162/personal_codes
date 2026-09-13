# -*- coding: utf-8 -*-
"""
多功能应用（加密存档 + 内置存档 + 设置 + 导入导出 + 随机点名 + 权重）
============================================================
教室布局：8 列 × 5 排 + 第 6 排 4 个座位（共 44 个座位）
排座规则：上一次坐在最后三排的同学，这次不能再坐最后三排
         ★ 例外：第 4 排第 3/4/5/6 列不算「后排」
         ★ 空位学生优先安排到后排，不参与排座、点名、后排轮换
         ★ 偏好学生可设「目标坐前排概率」，触发时强制到前 3 排，
           且该学生本轮仍按「坐过后排」计（后排轮换规则不变）
偏好同桌：1 名「偏好学生」 + 最多 14 名「意愿同桌」，按概率配对
         ★ 同桌冷却：最近 3 次坐过的同桌，本次不会再配对
随机点名：支持点名权重，实际被点概率 ≈ x × (1/44)
管理员解锁：快捷键 → 点讲台 → 再按快捷键（每步限时 2 秒）
存档目录：D:/JiXiu（D 盘不可用时自动回退到程序目录下的 JiXiu）
    ┌───────────────────────────────────────────────┐
    │  存档文件含义（纯数字，学生看不出对应功能）    │
    │    1.dat  →  管理员密码                       │
    │    2.dat  →  偏好配置                         │
    │    3.dat  →  上一次座位表                     │
    │    4.dat  →  管理员菜单窗口尺寸               │
    │    5.dat  →  教师密码                         │
    │    6.dat  →  学生名单（含空位标记）           │
    │    7.dat  →  点名权重                         │
    │    8.dat  →  上一次坐后排的学生名单           │
    │    9.dat  →  偏好学生的最近同桌记录（主）     │
    │   10.dat  →  偏好学生的最近同桌记录（备）     │
    └───────────────────────────────────────────────┘

「偏好学生的最近同桌记录」采用三重备份：
    ① 9.dat   —— 主文件
    ② 10.dat  —— 镜像备份（每次与 9.dat 同步写入）
    ③ 导出 txt 里的「存档码」—— 外部备份
读取顺序：9.dat → 10.dat → 空
导入座位表时若检测到有效存档码，会覆盖本地两份记录。

兼容性处理：
    · 左侧工具栏按钮使用 FlowLayout，窄窗口自动换行，不再被挤压/裁字
    · FlowLayout.minimumSize 只取最宽按钮宽度，窗口可缩到 560px 以下
    · 「作者 / 设置 / − / ×」按钮固定于窗口右上角，不随工具栏换行移动
    · 座位标签文字超宽时自动省略号（elidedText），不再被硬裁
    · 主窗口监听屏幕变化 / 窗口尺寸变化，动态重算按钮最小宽度
    · 各对话框在小屏上自动收缩，不会顶到底边
    · 对话框尺寸按「父窗口所在屏幕」计算（多显示器友好）
"""

import os
import re
import sys
import base64
import zlib
import json
import hashlib
import random
from datetime import datetime


# ============================================================
#  ⚙️  用户配置区
# ============================================================

# ---- 管理员解锁序列 ----
#   1) 按快捷键
#   2) 点一下讲台
#   3) 再按快捷键 → 弹出密码框
#   每步之间限时 ADMIN_UNLOCK_TIMEOUT_MS 毫秒，超时自动重置
ADMIN_SHORTCUT = "Alt+Z"
ADMIN_UNLOCK_TIMEOUT_MS = 2000

CRYPTO_SEED = "SeatCrypto_2024_@#!$%^"
MAX_DESK_CHOICES = 14
BACK_ROWS = 3
BACK_EXEMPT_SEATS = {(3, 2), (3, 3), (3, 4), (3, 5)}
EMPTY_STUDENT_MARKERS = ("(空)", "（空）")

# 同桌冷却次数：最近 N 次坐过的同桌，本次不再配对
DESK_COOLDOWN_TIMES = 3

FILE_PASSWORD = "1.dat"
FILE_DESK_PREFS = "2.dat"
FILE_SEATING = "3.dat"
FILE_UI = "4.dat"
FILE_TEACHER_PASSWORD = "5.dat"
FILE_STUDENTS = "6.dat"
FILE_PICK_WEIGHTS = "7.dat"
FILE_LAST_BACK = "8.dat"
FILE_RECENT_DESKMATES = "9.dat"
FILE_RECENT_DESKMATES_BAK = "10.dat"

# 内部占位：表示该次排座没有同桌
RECENT_EMPTY_MARKER = "__EMPTY__"

UI_DEFAULT_WIDTH = 560
UI_DEFAULT_HEIGHT = 720
DEFAULT_PICK_WEIGHT = 1.0
MAX_PICK_WEIGHT = 20.0

SEAT_WIDTH = 96
SEAT_HEIGHT = 52
PAIR_GAP = 2
PAIR_SPACING = 24
ROW_SPACING = 10
LABEL_WIDTH = 52
LABEL_GAP = 8

STUDENT_NAMES = [
    "同学壹", "同学贰", "同学叁", "同学肆", "同学伍",
    "同学陆", "同学柒", "同学捌", "同学玖", "同学拾",
    "同学拾壹", "同学拾贰", "同学拾叁", "同学拾肆", "同学拾伍",
    "同学拾陆", "同学拾柒", "同学拾捌", "同学拾玖", "同学贰拾",
    "同学贰拾壹", "同学贰拾贰", "同学贰拾叁", "同学贰拾肆", "同学贰拾伍",
    "同学贰拾陆", "同学贰拾柒", "同学贰拾捌", "同学贰拾玖", "同学叁拾",
    "同学叁拾壹", "同学叁拾贰", "同学叁拾叁", "同学叁拾肆", "同学叁拾伍",
    "同学叁拾陆", "同学叁拾柒", "同学叁拾捌", "同学叁拾玖", "同学肆拾",
    "同学肆拾壹", "同学肆拾贰", "同学肆拾叁", "同学肆拾肆",
]


# ============================================================
#  📦  内置存档
# ============================================================
_BUILTIN_ARCHIVE_JSON = json.dumps(
    {
        "password": "123456",
        "teacher_password": "",
        "desk_prefs": "同学贰拾叁\n60\n75\n同学叁\n同学柒\n同学捌\n同学玖\n同学拾\n同学拾壹\n同学拾叁\n同学拾伍\n同学拾柒\n同学拾玖\n同学叁拾陆\n同学肆拾壹\n同学肆拾叁",
        "last_seating": "",
        "pick_weights": "同学贰拾叁,0.3",
    },
    ensure_ascii=False,
)

BUILTIN_ARCHIVE_B64 = base64.b64encode(
    zlib.compress(_BUILTIN_ARCHIVE_JSON.encode("utf-8"))
).decode("ascii")


# ============================================================
#  座位布局配置
# ============================================================
COLS = 8
ROWS_NORMAL = 5
LAST_ROW_SEATS = 4


def is_empty_student(name) -> bool:
    if not name:
        return False
    return name.strip() in EMPTY_STUDENT_MARKERS


# ============================================================
#  存档目录
# ============================================================
def _get_archive_dir():
    primary = "D:/JiXiu"
    try:
        os.makedirs(primary, exist_ok=True)
        test_path = os.path.join(primary, ".writetest")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return primary
    except Exception:
        fallback = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "JiXiu"
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


def get_safe_window_size(desired_w, desired_h, widget=None):
    """按「widget 所在的屏幕」收缩窗口尺寸（多显示器友好）。

    下界放宽到 380×360，避免 800×600 屏幕上对话框顶到任务栏。
    widget 为 None 时回退到主屏。
    """
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return desired_w, desired_h

        screen = None
        target = widget
        # 依次尝试：widget 自身窗口 → 其父窗口 → 主屏
        while target is not None and screen is None:
            if hasattr(target, "windowHandle"):
                try:
                    handle = target.windowHandle()
                    if handle is not None and hasattr(handle, "screen"):
                        s = handle.screen()
                        if s is not None:
                            screen = s
                            break
                except Exception:
                    pass
            if hasattr(target, "parent"):
                try:
                    target = target.parent()
                except Exception:
                    target = None
            else:
                target = None

        if screen is None:
            screen = app.primaryScreen()
        if screen is None:
            return desired_w, desired_h

        avail = screen.availableGeometry()
        max_w = max(380, avail.width() - 60)
        max_h = max(360, avail.height() - 80)
        return min(desired_w, max_w), min(desired_h, max_h)
    except Exception:
        return desired_w, desired_h


ARCHIVE_DIR = _get_archive_dir()
PASSWORD_FILE = os.path.join(ARCHIVE_DIR, FILE_PASSWORD)
DESK_PREFS_FILE = os.path.join(ARCHIVE_DIR, FILE_DESK_PREFS)
SEATING_FILE = os.path.join(ARCHIVE_DIR, FILE_SEATING)
UI_FILE = os.path.join(ARCHIVE_DIR, FILE_UI)
TEACHER_PASSWORD_FILE = os.path.join(ARCHIVE_DIR, FILE_TEACHER_PASSWORD)
STUDENTS_FILE = os.path.join(ARCHIVE_DIR, FILE_STUDENTS)
PICK_WEIGHTS_FILE = os.path.join(ARCHIVE_DIR, FILE_PICK_WEIGHTS)
LAST_BACK_FILE = os.path.join(ARCHIVE_DIR, FILE_LAST_BACK)
RECENT_DESKMATES_FILE = os.path.join(ARCHIVE_DIR, FILE_RECENT_DESKMATES)
RECENT_DESKMATES_BAK_FILE = os.path.join(
    ARCHIVE_DIR, FILE_RECENT_DESKMATES_BAK
)


# ============================================================
#  简单加密 / 解密
# ============================================================
def _make_keystream(length, salt=b""):
    seed_bytes = (CRYPTO_SEED.encode("utf-8") + salt)
    stream = b""
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(seed_bytes + counter.to_bytes(4, "big")).digest()
        stream += block
        counter += 1
    return stream[:length]


def encrypt_text(text: str, salt: str = "") -> str:
    raw = text.encode("utf-8")
    key = _make_keystream(len(raw), salt.encode("utf-8"))
    encrypted = bytes(b ^ k for b, k in zip(raw, key))
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_text(b64_text: str, salt: str = "") -> str:
    raw = base64.b64decode(b64_text.encode("ascii"))
    key = _make_keystream(len(raw), salt.encode("utf-8"))
    decrypted = bytes(b ^ k for b, k in zip(raw, key))
    return decrypted.decode("utf-8")


def save_encrypted(path: str, text: str, salt: str = ""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(encrypt_text(text, salt))


def load_encrypted(path: str, salt: str = "") -> str:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            b64 = f.read().strip()
        if not b64:
            return ""
        return decrypt_text(b64, salt)
    except Exception:
        raise ValueError("存档无法读取，可能是文件已损坏。")


# ============================================================
#  内置存档解压
# ============================================================
def extract_builtin_archive() -> dict:
    raw = zlib.decompress(base64.b64decode(BUILTIN_ARCHIVE_B64))
    return json.loads(raw.decode("utf-8"))


def ensure_archive_files():
    need_password = not os.path.exists(PASSWORD_FILE)
    need_desk = not os.path.exists(DESK_PREFS_FILE)
    need_seating = not os.path.exists(SEATING_FILE)
    need_teacher = not os.path.exists(TEACHER_PASSWORD_FILE)
    need_pick = not os.path.exists(PICK_WEIGHTS_FILE)

    if not (need_password or need_desk or need_seating or need_teacher or need_pick):
        return

    archive = extract_builtin_archive()

    if need_password:
        save_encrypted(PASSWORD_FILE,
                       archive.get("password", "123456"),
                       salt="password")
    if need_teacher:
        save_encrypted(TEACHER_PASSWORD_FILE,
                       archive.get("teacher_password", ""),
                       salt="teacher")
    if need_desk:
        save_encrypted(DESK_PREFS_FILE,
                       archive.get("desk_prefs", "\n80\n0"),
                       salt="desk")
    if need_seating:
        save_encrypted(SEATING_FILE,
                       archive.get("last_seating", ""),
                       salt="seating")
    if need_pick:
        save_encrypted(PICK_WEIGHTS_FILE,
                       archive.get("pick_weights", ""),
                       salt="pick")


# ============================================================
#  座位位置计算
# ============================================================
def get_total_rows():
    return ROWS_NORMAL + (1 if LAST_ROW_SEATS > 0 else 0)


def get_back_start_row():
    return get_total_rows() - BACK_ROWS


def get_front_row_count():
    return get_back_start_row()


def get_seat_positions():
    positions = []
    for r in range(ROWS_NORMAL):
        for c in range(COLS):
            positions.append((r, c))
    if LAST_ROW_SEATS > 0:
        offset = (COLS - LAST_ROW_SEATS) // 2
        for i in range(LAST_ROW_SEATS):
            positions.append((ROWS_NORMAL, offset + i))
    return positions


def get_row_columns():
    row_map = {}
    for (r, c) in get_seat_positions():
        row_map.setdefault(r, []).append(c)
    for r in row_map:
        row_map[r].sort()
    return row_map


def get_desk_pairs(positions):
    row_map = {}
    for (r, c) in positions:
        row_map.setdefault(r, []).append(c)
    pairs = []
    for r, cols in row_map.items():
        cols.sort()
        for i in range(0, len(cols) - 1, 2):
            pairs.append(((r, cols[i]), (r, cols[i + 1])))
    return pairs


def is_back_seat(pos):
    r, c = pos
    if r < get_back_start_row():
        return False
    if pos in BACK_EXEMPT_SEATS:
        return False
    return True


def is_front_row_seat(pos):
    return pos[0] < get_back_start_row()


# ============================================================
#  座位表文本解析
# ============================================================
def parse_seating_text(text: str) -> dict:
    row_map = get_row_columns()
    total_rows = get_total_rows()
    new_seating = {}

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        m = re.match(r"^第\s*(\d+)\s*排", stripped)
        if not m:
            i += 1
            continue

        row_idx = int(m.group(1)) - 1
        if not (0 <= row_idx < total_rows):
            i += 1
            continue

        names = []
        rest = stripped[m.end():]
        rest = rest.replace("← 后排", "")
        rest = rest.lstrip("：:　 \t")
        if rest:
            names.extend(_split_names(rest))

        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                i += 1
                continue
            if re.match(r"^第\s*\d+\s*排", nxt):
                break
            if nxt.startswith("=") or nxt.startswith("-"):
                i += 1
                continue
            if nxt.startswith("存档码") or nxt.startswith("（删除存档码"):
                while i < len(lines):
                    if re.match(r"^第\s*\d+\s*排", lines[i].strip()):
                        break
                    i += 1
                break
            names.extend(_split_names(nxt))
            i += 1

        cols = row_map.get(row_idx, [])
        for j, name in enumerate(names):
            if j >= len(cols):
                break
            if name in ("（空）", "(空)"):
                continue
            new_seating[(row_idx, cols[j])] = name

    return new_seating


def _split_names(text: str):
    # 全角空格 / tab 优先；再退化到"连续两个及以上半角空格"
    # 用 ' {2,}' 而非 '\s{2,}'，避免误伤名字内部可能存在的单个 tab
    parts = re.split(r"[　\t]+| {2,}", text)
    return [p.strip() for p in parts if p.strip()]


# ============================================================
#  PyQt 导入（提前导入，方便定义 get_ui_font）
# ============================================================
from PyQt5.QtCore import Qt, QTimer, QRect, QSize, QPoint
from PyQt5.QtGui import QFont, QFontDatabase, QKeySequence, QFontMetrics
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QDialog,
    QDialogButtonBox, QFileDialog, QLineEdit, QSlider,
    QComboBox, QInputDialog, QScrollArea, QShortcut, QGroupBox,
    QTextEdit, QDoubleSpinBox, QLayout, QSizePolicy,
)


# ============================================================
#  FlowLayout：工具栏按钮自动换行（窄窗口不再挤压/裁字）
# ============================================================
class FlowLayout(QLayout):
    """简易流式布局：控件按行排列，超宽自动换行。

    参考 Qt 官方 FlowLayout 示例，用于让左侧工具栏按钮在窄窗口下
    自动折行，避免按钮文字被压成省略号或被裁切。
    """

    def __init__(self, parent=None, margin=0, h_spacing=10, v_spacing=8):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # ---- QLayout 必须实现的接口 ----
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
        # 不向任何方向扩展；用空 flags 兼容旧版本 PyQt5
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        # 首选尺寸：所有按钮排一行
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
        """最窄只放得下最宽的那个按钮。

        关键：不再对所有按钮宽度求和，否则 Qt 会认为整个窗口
        的最小宽度是"所有按钮一行排开"的宽度，导致窗口无法缩窄。
        """
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

    # ---- 实际布局 ----
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
#  跨平台中文字体（关键修复）
# ============================================================
_FONT_CACHE = {}


def get_ui_font(size=10, bold=False):
    """
    按系统选择可用的中文字体，跨 Windows / macOS / Linux 都能正常显示。
    结果会缓存，避免重复查询字体数据库。
    """
    key = (size, bold)
    if key in _FONT_CACHE:
        return QFont(_FONT_CACHE[key])

    preferred = [
        "Microsoft YaHei UI",       # Windows 10+
        "Microsoft YaHei",          # Windows 7/8
        "PingFang SC",              # macOS
        "Hiragino Sans GB",         # macOS 旧版
        "Noto Sans CJK SC",         # Linux
        "WenQuanYi Micro Hei",      # Linux 中文
        "Source Han Sans SC",
        "SimHei",
        "SimSun",
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
QSS_NORMAL = """
QLabel {
    background-color: #ffffff;
    border: 2px solid #b0bec5;
    border-radius: 8px;
    color: #263238;
}
"""

QSS_BACK = """
QLabel {
    background-color: #fff3e0;
    border: 2px solid #ffb74d;
    border-radius: 8px;
    color: #e65100;
}
"""

QSS_EMPTY = """
QLabel {
    background-color: #fafafa;
    border: 2px dashed #dde3e6;
    border-radius: 8px;
    color: #cfd8dc;
}
"""

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

# 符号按钮（最小化）用独立样式：无 padding，让符号居中
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
#  点名权重设置对话框
# ============================================================
class PickWeightDialog(QDialog):
    def __init__(self, students, weights, parent=None):
        super().__init__(parent)
        self.setWindowTitle("点名设置")
        self.setMinimumSize(420, 520)
        self.setStyleSheet("background-color: #fafafa;")
        self.students = [s for s in students if not is_empty_student(s)]

        w0, h0 = get_safe_window_size(520, 700, self)
        self.resize(w0, h0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: #fafafa;")
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(8)

        tip = QLabel(
            "每位学生的默认值为 1.0。\n"
            "数值越高，越容易出现在结果中；数值为 0 时不会出现。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        header = QHBoxLayout()
        h1 = QLabel("学生")
        h1.setStyleSheet("QLabel { color: #455a64; font-size: 12px; font-weight: bold; }")
        h2 = QLabel("数值")
        h2.setStyleSheet("QLabel { color: #455a64; font-size: 12px; font-weight: bold; }")
        h2.setFixedWidth(120)
        h3 = QLabel("占比")
        h3.setStyleSheet("QLabel { color: #455a64; font-size: 12px; font-weight: bold; }")
        h3.setFixedWidth(90)
        header.addWidget(h1, 1)
        header.addWidget(h2)
        header.addWidget(h3)
        v.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(0, 4, 0, 4)

        self.spins = {}
        self.prob_labels = {}

        for i, name in enumerate(self.students):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("QLabel { color: #37474f; font-size: 12px; }")

            spin = QDoubleSpinBox()
            spin.setRange(0.0, MAX_PICK_WEIGHT)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setFixedWidth(120)
            spin.setValue(weights.get(name, DEFAULT_PICK_WEIGHT))
            spin.setStyleSheet("""
                QDoubleSpinBox {
                    padding: 3px 6px; border: 1px solid #cfd8dc;
                    border-radius: 4px; background: #ffffff; font-size: 12px;
                }
            """)
            spin.valueChanged.connect(self._refresh_all_probs)

            prob_lbl = QLabel()
            prob_lbl.setFixedWidth(90)
            prob_lbl.setStyleSheet(
                "QLabel { color: #1976d2; font-size: 12px; }"
            )

            self.spins[name] = spin
            self.prob_labels[name] = prob_lbl

            grid.addWidget(name_lbl, i, 0)
            grid.addWidget(spin, i, 1)
            grid.addWidget(prob_lbl, i, 2)

        v.addLayout(grid)
        v.addStretch()

        btn_wrap = QHBoxLayout()
        btn_reset = QPushButton("全部重置为 1.0")
        btn_reset.setStyleSheet(QSS_BTN_NORMAL)
        btn_reset.setMinimumHeight(34)
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.clicked.connect(self._reset_all)
        btn_wrap.addWidget(btn_reset)
        btn_wrap.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btn_wrap.addWidget(btns)
        outer.addLayout(btn_wrap)

        self._refresh_all_probs()

    def _refresh_all_probs(self):
        total = sum(s.value() for s in self.spins.values())
        for name, spin in self.spins.items():
            if total <= 0:
                self.prob_labels[name].setText("—")
            else:
                p = spin.value() / total
                self.prob_labels[name].setText("%.2f%%" % (p * 100))

    def _reset_all(self):
        for spin in self.spins.values():
            spin.blockSignals(True)
            spin.setValue(DEFAULT_PICK_WEIGHT)
            spin.blockSignals(False)
        self._refresh_all_probs()

    def get_weights(self):
        result = {}
        for name, spin in self.spins.items():
            v = spin.value()
            if abs(v - DEFAULT_PICK_WEIGHT) > 1e-9:
                result[name] = v
        return result


# ============================================================
#  随机点名器
# ============================================================
class NamePickerDialog(QDialog):
    def __init__(self, names, weights=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("随机点名")
        self.setMinimumSize(400, 400)
        self.setStyleSheet("background-color: #263238;")
        self.all_names = [n for n in names if n and not is_empty_student(n)]
        if not self.all_names:
            self.all_names = ["（无学生）"]
        self.weights = dict(weights) if weights else {}
        self.history = []

        w0, h0 = get_safe_window_size(520, 440, self)
        self.resize(w0, h0)

        v = QVBoxLayout(self)
        v.setContentsMargins(30, 30, 30, 20)
        v.setSpacing(16)

        self.name_label = QLabel("准备就绪")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFont(get_ui_font(40, bold=True))
        self.name_label.setStyleSheet(
            "QLabel { color: #4fc3f7; background: #1a2327;"
            " border-radius: 12px; padding: 20px; }"
        )
        self.name_label.setMinimumHeight(150)
        # 长名字自动换行，避免 5 字以上溢出
        self.name_label.setWordWrap(True)
        v.addWidget(self.name_label)

        self.btn = QPushButton("开始点名")
        self.btn.setMinimumHeight(52)
        self.btn.setFont(get_ui_font(16, bold=True))
        self.btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn_style("idle")
        self.btn.clicked.connect(self._on_btn_click)
        v.addWidget(self.btn)

        self.history_label = QLabel("已点名：0 人")
        self.history_label.setAlignment(Qt.AlignCenter)
        self.history_label.setStyleSheet(
            "QLabel { color: #78909c; font-size: 12px; }"
        )
        v.addWidget(self.history_label)

        self.history_text = QLabel("")
        self.history_text.setAlignment(Qt.AlignCenter)
        self.history_text.setWordWrap(True)
        self.history_text.setStyleSheet(
            "QLabel { color: #b0bec5; font-size: 12px; }"
        )
        v.addWidget(self.history_text)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self.phase = "idle"
        self.slow_counter = 0
        self.current_name = ""

    def _weighted_choice(self):
        if not self.all_names:
            return "（无学生）"
        weights = [self.weights.get(n, DEFAULT_PICK_WEIGHT)
                   for n in self.all_names]
        total = sum(weights)
        if total <= 0:
            return random.choice(self.all_names)
        return random.choices(self.all_names, weights=weights, k=1)[0]

    def _apply_btn_style(self, state):
        if state == "idle":
            self.btn.setStyleSheet("""
                QPushButton {
                    background-color: #4fc3f7; color: #0d1117;
                    border: none; border-radius: 8px; font-weight: bold;
                }
                QPushButton:hover { background-color: #29b6f6; }
                QPushButton:pressed { background-color: #03a9f4; }
            """)
        elif state == "rolling":
            self.btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef5350; color: #ffffff;
                    border: none; border-radius: 8px; font-weight: bold;
                }
                QPushButton:hover { background-color: #e53935; }
                QPushButton:pressed { background-color: #c62828; }
            """)
        elif state == "stopped":
            self.btn.setStyleSheet("""
                QPushButton {
                    background-color: #66bb6a; color: #ffffff;
                    border: none; border-radius: 8px; font-weight: bold;
                }
                QPushButton:hover { background-color: #4caf50; }
                QPushButton:pressed { background-color: #388e3c; }
            """)

    def _on_btn_click(self):
        if self.phase in ("idle", "stopped"):
            self._start_roll()
        elif self.phase == "rolling":
            self._begin_slow()

    def _start_roll(self):
        self.phase = "rolling"
        self.btn.setText("停 止")
        self._apply_btn_style("rolling")
        self.name_label.setStyleSheet(
            "QLabel { color: #4fc3f7; background: #1a2327;"
            " border-radius: 12px; padding: 20px; }"
        )
        self.timer.start(50)

    def _begin_slow(self):
        self.phase = "slowing"
        self.slow_counter = 8
        self.timer.setInterval(60)
        self.btn.setEnabled(False)

    def _tick(self):
        self.current_name = self._weighted_choice()
        self.name_label.setText(self.current_name)

        if self.phase == "slowing":
            self.slow_counter -= 1
            if self.slow_counter <= 0:
                self.timer.stop()
                self._finish()
            else:
                interval = 60 + (8 - self.slow_counter) * 30
                self.timer.setInterval(interval)

    def _finish(self):
        self.current_name = self._weighted_choice()
        self.name_label.setText(self.current_name)

        self.phase = "stopped"
        self.btn.setEnabled(True)
        self.btn.setText("再点一位")
        self._apply_btn_style("stopped")
        self.name_label.setStyleSheet(
            "QLabel { color: #ffeb3b; background: #1a2327;"
            " border: 3px solid #ffeb3b; border-radius: 12px; padding: 20px; }"
        )
        self.history.append(self.current_name)
        self.history_label.setText("已点名：%d 人" % len(self.history))
        recent = self.history[-10:]
        self.history_text.setText("　".join(recent))


# ============================================================
#  设置对话框（原教师菜单）
# ============================================================
class TeacherDialog(QDialog):
    def __init__(self, students, teacher_password_set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(420, 500)
        self.setStyleSheet("background-color: #fafafa;")
        self._new_teacher_password = None
        self._final_students = None

        w0, h0 = get_safe_window_size(600, 760, self)
        self.resize(w0, h0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: #fafafa;")
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        title = QLabel("设置")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_ui_font(16, bold=True))
        title.setStyleSheet("QLabel { color: #00695c; padding: 6px 0; }")
        v.addWidget(title)

        total_seats = len(get_seat_positions())
        list_hint = QLabel(
            "学生名单（每行一个姓名，可直接修改；保存后写入存档）\n"
            "提示：输入 (空) 或 （空） 表示空位，空位优先安排到后排；\n"
            "     名单总行数不能超过 %d 行（含空位）。" % total_seats
        )
        list_hint.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        list_hint.setWordWrap(True)
        v.addWidget(list_hint)

        self.students_edit = QTextEdit()
        self.students_edit.setFont(get_ui_font(11))
        self.students_edit.setPlainText("\n".join(students))
        self.students_edit.setMinimumHeight(200)
        self.students_edit.setStyleSheet("""
            QTextEdit {
                background: #ffffff; border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 6px;
            }
        """)
        v.addWidget(self.students_edit)

        self.count_label = QLabel("当前 %d 人" % len(students))
        self.count_label.setStyleSheet(
            "QLabel { color: #607d8b; font-size: 12px; }"
        )
        v.addWidget(self.count_label)
        self.students_edit.textChanged.connect(self._update_count)

        pwd_group = QGroupBox("密码")
        pwd_group.setStyleSheet(QSS_GROUPBOX)

        pwd_layout = QGridLayout(pwd_group)
        pwd_layout.setContentsMargins(12, 12, 12, 12)
        pwd_layout.setHorizontalSpacing(10)
        pwd_layout.setVerticalSpacing(8)

        status_text = "当前状态：已设置" if teacher_password_set else "当前状态：未设置"
        status_color = "#00695c" if teacher_password_set else "#e65100"
        self.pwd_status = QLabel(status_text)
        self.pwd_status.setStyleSheet(
            "QLabel { color: %s; font-size: 12px; font-weight: bold; }"
            % status_color
        )
        pwd_layout.addWidget(self.pwd_status, 0, 0, 1, 2)

        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        l1 = QLabel("新密码：")
        l1.setStyleSheet(lbl_style)
        l1.setFixedWidth(70)
        l2 = QLabel("确认密码：")
        l2.setStyleSheet(lbl_style)
        l2.setFixedWidth(70)

        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        self.new_pwd_edit.setPlaceholderText("留空表示不修改")
        self.new_pwd_edit.setStyleSheet(QSS_INPUT)

        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新密码")
        self.confirm_pwd_edit.setStyleSheet(QSS_INPUT)

        pwd_layout.addWidget(l1, 1, 0)
        pwd_layout.addWidget(self.new_pwd_edit, 1, 1)
        pwd_layout.addWidget(l2, 2, 0)
        pwd_layout.addWidget(self.confirm_pwd_edit, 2, 1)

        pwd_hint = QLabel(
            "提示：设置密码后，打开设置需要输入密码。\n"
            "      留空表示不修改当前密码。"
        )
        pwd_hint.setStyleSheet("QLabel { color: #90a4ae; font-size: 11px; }")
        pwd_hint.setWordWrap(True)
        pwd_layout.addWidget(pwd_hint, 3, 0, 1, 2)

        v.addWidget(pwd_group)
        v.addStretch()

        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        btn_wrap.addWidget(btns)
        outer.addLayout(btn_wrap)

    def _update_count(self):
        names = [ln.strip() for ln in self.students_edit.toPlainText().splitlines()
                 if ln.strip()]
        real = len([n for n in names if not is_empty_student(n)])
        empty = len(names) - real
        total_seats = len(get_seat_positions())
        if empty > 0:
            self.count_label.setText(
                "当前 %d 行（真实 %d，空位 %d）／上限 %d 行"
                % (len(names), real, empty, total_seats)
            )
        else:
            self.count_label.setText(
                "当前 %d 人／上限 %d 人" % (len(names), total_seats)
            )
        if len(names) > total_seats:
            self.count_label.setStyleSheet(
                "QLabel { color: #c62828; font-size: 12px; font-weight: bold; }"
            )
        else:
            self.count_label.setStyleSheet(
                "QLabel { color: #607d8b; font-size: 12px; }"
            )

    def _detect_and_revert_swaps(self, names):
        result = list(names)
        default = STUDENT_NAMES

        default_index = {}
        for idx, name in enumerate(default):
            if name not in default_index:
                default_index[name] = idx

        for i, name in enumerate(result):
            if i >= len(default):
                break
            if name in default_index and default_index[name] != i:
                result[i] = default[i]

        return result

    def _on_ok(self):
        names = [ln.strip() for ln in self.students_edit.toPlainText().splitlines()
                 if ln.strip()]
        if not names:
            QMessageBox.warning(self, "提示", "学生名单不能为空。")
            return

        names = self._detect_and_revert_swaps(names)
        self._final_students = list(names)

        total_seats = len(get_seat_positions())
        if len(names) > total_seats:
            QMessageBox.warning(
                self, "提示",
                "学生名单最多 %d 行（含空位），当前 %d 行。\n\n"
                "请删除多余行后重试。" % (total_seats, len(names))
            )
            return

        seen = set()
        dups = set()
        for n in names:
            if is_empty_student(n):
                continue
            if n in seen:
                dups.add(n)
            seen.add(n)
        if dups:
            QMessageBox.warning(
                self, "提示",
                "学生名单中存在重名：\n" + "、".join(sorted(dups))
                + "\n\n请修改后重试。"
            )
            return

        new_pwd = self.new_pwd_edit.text()
        confirm_pwd = self.confirm_pwd_edit.text()
        if new_pwd or confirm_pwd:
            if not new_pwd:
                QMessageBox.warning(
                    self, "提示",
                    "如需设置密码，请在新密码和确认密码中都填写。"
                )
                return
            if new_pwd != confirm_pwd:
                QMessageBox.warning(self, "提示", "两次输入的密码不一致。")
                return
            self._new_teacher_password = new_pwd

        self.accept()

    def get_students(self):
        if self._final_students is not None:
            return list(self._final_students)
        return [ln.strip() for ln in self.students_edit.toPlainText().splitlines()
                if ln.strip()]

    def get_new_teacher_password(self):
        return self._new_teacher_password


# ============================================================
#  管理员设置对话框
# ============================================================
class AdminDialog(QDialog):
    def __init__(self, students, preferred_student, desired_deskmates,
                 probability, target_front_probability,
                 saved_password, pick_weights, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理员设置")
        self.setMinimumSize(400, 440)
        self.setStyleSheet("background-color: #fafafa;")
        self.students = [s for s in students if not is_empty_student(s)]
        self.saved_password = saved_password
        self._new_password = None
        self._pick_weights = dict(pick_weights) if pick_weights else {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: #fafafa;")
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(8)

        tip = QLabel(
            "① 偏好学生：从名单中选一名（同时是「意愿同桌」和「目标坐前排」的对象）。\n"
            "② 意愿同桌：为该学生挑最多 %d 名意愿同桌。\n"
            "③ 配对概率：越高越容易配对成功。\n"
            "④ 目标坐前排概率：触发时，偏好学生被强制安排到前 3 排\n"
            "   （该学生本轮仍按「坐过后排」计，不影响后排轮换规则）。\n"
            "⑤ 点名设置：可调整每位学生的点名权重。\n"
            "⑥ 修改密码：留空表示不修改。\n"
            "★ 本次同桌不会与最近 3 次的同桌相同。\n"
            "★ 可拖动窗口边缘调整大小，关闭后自动记忆。"
            % MAX_DESK_CHOICES
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        pref_row = QHBoxLayout()
        pref_label = QLabel("偏好学生：")
        pref_label.setFixedWidth(70)
        pref_label.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        pref_row.addWidget(pref_label)

        self.pref_combo = QComboBox()
        self.pref_combo.setFixedWidth(200)
        self.pref_combo.setMaxVisibleItems(14)
        self.pref_combo.setFont(get_ui_font(10))
        self.pref_combo.addItem("（未设置）", "")
        for s in self.students:
            self.pref_combo.addItem(s, s)
        if preferred_student:
            idx = self.pref_combo.findData(preferred_student)
            if idx >= 0:
                self.pref_combo.setCurrentIndex(idx)
        self.pref_combo.setStyleSheet(
            "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
            " border-radius: 4px; background: #ffffff; }"
        )
        pref_row.addWidget(self.pref_combo)
        pref_row.addStretch()
        v.addLayout(pref_row)

        prob_group = QGroupBox("配对概率")
        prob_group.setStyleSheet(QSS_GROUPBOX)
        prob_layout = QHBoxLayout(prob_group)
        prob_layout.setContentsMargins(12, 8, 12, 10)
        prob_layout.setSpacing(10)

        self.prob_slider = QSlider(Qt.Horizontal)
        self.prob_slider.setRange(0, 100)
        self.prob_slider.setValue(int(probability))
        self.prob_slider.setCursor(Qt.PointingHandCursor)
        self.prob_slider.valueChanged.connect(self._on_prob_changed)
        prob_layout.addWidget(self.prob_slider, 1)

        self.prob_label = QLabel("%d%%" % int(probability))
        self.prob_label.setFixedWidth(56)
        self.prob_label.setAlignment(Qt.AlignCenter)
        self.prob_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; color: #1976d2;"
            " background: #e3f2fd; border-radius: 4px; padding: 3px 0; }"
        )
        prob_layout.addWidget(self.prob_label)
        v.addWidget(prob_group)

        front_group = QGroupBox("偏好学生目标坐前排概率")
        front_group.setStyleSheet(QSS_GROUPBOX)
        front_layout = QHBoxLayout(front_group)
        front_layout.setContentsMargins(12, 8, 12, 10)
        front_layout.setSpacing(10)

        self.front_slider = QSlider(Qt.Horizontal)
        self.front_slider.setRange(0, 100)
        self.front_slider.setValue(int(target_front_probability))
        self.front_slider.setCursor(Qt.PointingHandCursor)
        self.front_slider.valueChanged.connect(self._on_front_changed)
        front_layout.addWidget(self.front_slider, 1)

        self.front_label = QLabel("%d%%" % int(target_front_probability))
        self.front_label.setFixedWidth(56)
        self.front_label.setAlignment(Qt.AlignCenter)
        self.front_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; color: #2e7d32;"
            " background: #e8f5e9; border-radius: 4px; padding: 3px 0; }"
        )
        front_layout.addWidget(self.front_label)
        v.addWidget(front_group)

        front_hint = QLabel(
            "说明：触发时，偏好学生会被强制安排到前 3 排。\n"
            "      该学生本轮仍按「坐过后排」计（如果原本会被分到后排），\n"
            "      后排下一轮轮换规则不变。\n"
            "      0% = 不干预；100% = 每次排座都强制到前 3 排。"
        )
        front_hint.setStyleSheet("QLabel { color: #90a4ae; font-size: 11px; }")
        front_hint.setWordWrap(True)
        v.addWidget(front_hint)

        pick_group = QGroupBox("点名设置")
        pick_group.setStyleSheet(QSS_GROUPBOX)
        pick_layout = QHBoxLayout(pick_group)
        pick_layout.setContentsMargins(12, 8, 12, 10)
        pick_layout.setSpacing(10)

        pick_hint = QLabel(
            "可为每位学生设置不同的点名权重。"
        )
        pick_hint.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        pick_hint.setWordWrap(True)
        pick_layout.addWidget(pick_hint, 1)

        self.btn_pick = QPushButton("点名设置")
        self.btn_pick.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_pick.setMinimumHeight(34)
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.clicked.connect(self._open_pick_weights)
        pick_layout.addWidget(self.btn_pick)

        v.addWidget(pick_group)

        list_title = QLabel("意愿同桌（最多 %d 人，留空表示不使用）" % MAX_DESK_CHOICES)
        list_title.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold;"
            " padding-top: 4px; }"
        )
        v.addWidget(list_title)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        grid.setContentsMargins(0, 4, 0, 4)

        self.desk_combos = []
        for i in range(MAX_DESK_CHOICES):
            idx_lbl = QLabel("第 %02d 位" % (i + 1))
            idx_lbl.setFixedWidth(60)
            idx_lbl.setStyleSheet("QLabel { color: #607d8b; font-size: 12px; }")

            combo = QComboBox()
            combo.setFixedWidth(200)
            combo.setMaxVisibleItems(14)
            combo.setFont(get_ui_font(10))
            combo.addItem("（空）", "")
            for s in self.students:
                combo.addItem(s, s)
            if i < len(desired_deskmates):
                idx = combo.findData(desired_deskmates[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setStyleSheet(
                "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
                " border-radius: 4px; background: #ffffff; }"
            )
            self.desk_combos.append(combo)

            grid.addWidget(idx_lbl, i, 0)
            grid.addWidget(combo, i, 1)

        v.addWidget(inner)

        pwd_group = QGroupBox("修改密码（留空表示不修改）")
        pwd_group.setStyleSheet(QSS_GROUPBOX)

        pwd_layout = QGridLayout(pwd_group)
        pwd_layout.setContentsMargins(12, 10, 12, 10)
        pwd_layout.setHorizontalSpacing(10)
        pwd_layout.setVerticalSpacing(6)

        self.old_pwd_edit = QLineEdit()
        self.old_pwd_edit.setEchoMode(QLineEdit.Password)
        self.old_pwd_edit.setPlaceholderText("当前密码")
        self.old_pwd_edit.setStyleSheet(QSS_INPUT)

        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        self.new_pwd_edit.setPlaceholderText("新密码")
        self.new_pwd_edit.setStyleSheet(QSS_INPUT)

        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新密码")
        self.confirm_pwd_edit.setStyleSheet(QSS_INPUT)

        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        l1 = QLabel("当前密码：")
        l1.setStyleSheet(lbl_style)
        l1.setFixedWidth(70)
        l2 = QLabel("新密码：")
        l2.setStyleSheet(lbl_style)
        l2.setFixedWidth(70)
        l3 = QLabel("确认密码：")
        l3.setStyleSheet(lbl_style)
        l3.setFixedWidth(70)

        pwd_layout.addWidget(l1, 0, 0)
        pwd_layout.addWidget(self.old_pwd_edit, 0, 1)
        pwd_layout.addWidget(l2, 1, 0)
        pwd_layout.addWidget(self.new_pwd_edit, 1, 1)
        pwd_layout.addWidget(l3, 2, 0)
        pwd_layout.addWidget(self.confirm_pwd_edit, 2, 1)

        v.addWidget(pwd_group)
        v.addStretch()

        btn_wrap = QHBoxLayout()
        btn_wrap.setContentsMargins(16, 8, 16, 12)
        btn_wrap.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        btn_wrap.addWidget(btns)
        outer.addLayout(btn_wrap)

    def _on_prob_changed(self, val):
        self.prob_label.setText("%d%%" % val)

    def _on_front_changed(self, val):
        self.front_label.setText("%d%%" % val)

    def _open_pick_weights(self):
        dlg = PickWeightDialog(self.students, self._pick_weights, self)
        if dlg.exec_() == QDialog.Accepted:
            self._pick_weights = dlg.get_weights()
            QMessageBox.information(
                self, "已更新",
                "点名设置已更新，点确定保存后写入存档。"
            )

    def _on_ok(self):
        pref = self.pref_combo.currentData()

        choices = []
        seen = set()
        for i, combo in enumerate(self.desk_combos):
            name = combo.currentData()
            if not name:
                continue
            if pref and name == pref:
                QMessageBox.warning(
                    self, "提示",
                    "第 %d 位与偏好学生是同一人，请调整。" % (i + 1)
                )
                return
            if name in seen:
                QMessageBox.warning(
                    self, "提示",
                    "%s 在第 %d 位重复出现，请调整。" % (name, i + 1)
                )
                return
            seen.add(name)
            choices.append(name)

        if choices and not pref:
            QMessageBox.warning(
                self, "提示",
                "已选择意愿同桌，但还未指定偏好学生。\n请先选择一名偏好学生。"
            )
            return

        old_pwd = self.old_pwd_edit.text()
        new_pwd = self.new_pwd_edit.text()
        confirm_pwd = self.confirm_pwd_edit.text()

        if new_pwd or confirm_pwd or old_pwd:
            if not new_pwd:
                QMessageBox.warning(
                    self, "提示",
                    "如需修改密码，请在「新密码」和「确认密码」中填写。"
                )
                return
            if old_pwd != self.saved_password:
                QMessageBox.warning(self, "提示", "当前密码不正确。")
                return
            if new_pwd != confirm_pwd:
                QMessageBox.warning(self, "提示", "两次输入的新密码不一致。")
                return
            if not new_pwd.strip():
                QMessageBox.warning(self, "提示", "新密码不能为空。")
                return
            self._new_password = new_pwd
        else:
            self._new_password = ""

        self.accept()

    def get_pref_student(self):
        return self.pref_combo.currentData() or ""

    def get_desired_deskmates(self):
        result = []
        for combo in self.desk_combos:
            name = combo.currentData()
            if name:
                result.append(name)
        return result

    def get_probability(self):
        return self.prob_slider.value()

    def get_target_front_probability(self):
        return self.front_slider.value()

    def get_new_password(self):
        return self._new_password or ""

    def get_pick_weights(self):
        return dict(self._pick_weights)


# ============================================================
#  座位控件
# ============================================================
class SeatLabel(QLabel):
    def __init__(self, row, col, is_back=False, parent=None):
        super().__init__(parent)
        self.row = row
        self.col = col
        self.is_back = is_back
        self.setFixedSize(SEAT_WIDTH, SEAT_HEIGHT)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(get_ui_font(11))
        self.setStyleSheet(QSS_EMPTY)
        self.setToolTip(f"第 {row + 1} 排  第 {col + 1} 列")
        self._raw_name = ""

    def _elide(self, text):
        """文字超过座位宽度时自动省略，避免硬裁。"""
        if not text:
            return ""
        fm = QFontMetrics(self.font())
        avail = max(20, self.width() - 8)
        return fm.elidedText(text, Qt.ElideRight, avail)

    def set_name(self, name):
        if name and not is_empty_student(name):
            self._raw_name = name
            self.setText(self._elide(name))
            if self.is_back:
                self.setStyleSheet(QSS_BACK)
            else:
                self.setStyleSheet(QSS_NORMAL)
            tip = f"第 {self.row + 1} 排  第 {self.col + 1} 列\n{name}"
            if self.is_back:
                tip += "\n（后排）"
            self.setToolTip(tip)
        else:
            self._raw_name = ""
            self.setText("")
            self.setStyleSheet(QSS_EMPTY)
            self.setToolTip(f"第 {self.row + 1} 排  第 {self.col + 1} 列（空）")


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("多功能应用")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(560, 400)

        self.students = []
        self.preferred_student = ""
        self.desired_deskmates = []
        self.probability = 80
        self.target_front_probability = 0
        self.saved_password = "123456"
        self.teacher_password = ""
        self.pick_weights = {}
        self.last_back_students = set()
        self.recent_deskmates = []

        self.seat_positions = get_seat_positions()
        self.seat_widgets = {}
        self.current_seating = {}
        self.last_seating = {}

        # 左侧工具栏（FlowLayout，可换行）
        self._toolbar_widget = None
        self._toolbar_layout = None
        # 右上角固定按钮组
        self._right_box = None

        # 管理员解锁状态机
        self._admin_unlock_state = 0
        self._admin_reset_timer = QTimer(self)
        self._admin_reset_timer.setSingleShot(True)
        self._admin_reset_timer.timeout.connect(self._reset_admin_unlock)

        ensure_archive_files()

        self._load_password()
        self._load_teacher_password()
        self._load_students()
        self._load_desk_prefs()
        self._load_pick_weights()
        self._load_last_seating()
        self._load_last_back_students()
        self._load_recent_deskmates()
        self.current_seating = dict(self.last_seating)

        self._build_ui()
        self._setup_shortcuts()
        self._refresh_seats()
        self._update_status()

    # --------------------------------------------------------
    #  屏幕 / 尺寸变化处理（跨 DPI、跨屏）
    # --------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_adaptive_btn_widths)

        handle = self.windowHandle() if hasattr(self, "windowHandle") else None
        if handle is not None and hasattr(handle, "screenChanged"):
            try:
                handle.screenChanged.disconnect(self._on_screen_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                handle.screenChanged.connect(self._on_screen_changed)
            except Exception:
                pass

    def _on_screen_changed(self, *args):
        QTimer.singleShot(0, self._apply_adaptive_btn_widths)
        QTimer.singleShot(0, self._refresh_toolbar_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_toolbar_height()
        QTimer.singleShot(0, self._refresh_seats)

    def _refresh_toolbar_height(self):
        """根据当前可用宽度，重算左侧工具栏需要的高度（可能换行）。"""
        if self._toolbar_widget is None or self._toolbar_layout is None:
            return
        try:
            w = self._toolbar_widget.width()
            if w <= 0:
                cw = self.centralWidget()
                if cw is not None:
                    m_left = m_right = 18
                    lay = cw.layout()
                    if lay is not None:
                        m = lay.contentsMargins()
                        m_left = m.left()
                        m_right = m.right()
                    base = cw.width() - m_left - m_right
                    # 减去右上角固定按钮组的宽度与间距
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

    def _apply_adaptive_btn_widths(self):
        """让"作者"和"设置"按钮的最小宽度按内容自适应。

        兼容旧版本 Qt：Qt 5.11 之前没有 horizontalAdvance，用 width() 兜底。
        """
        try:
            for btn in (getattr(self, "btn_author", None),
                        getattr(self, "btn_teacher", None)):
                if btn is None:
                    continue
                fm = btn.fontMetrics()
                if hasattr(fm, "horizontalAdvance"):
                    text_w = fm.horizontalAdvance(btn.text())
                else:
                    text_w = fm.width(btn.text())
                btn.setMinimumWidth(max(text_w + 40, btn.sizeHint().width()))
            self._refresh_toolbar_height()
        except Exception:
            pass

    # --------------------------------------------------------
    #  快捷键 / 管理员解锁
    # --------------------------------------------------------
    def _setup_shortcuts(self):
        self.admin_shortcut = QShortcut(QKeySequence(ADMIN_SHORTCUT), self)
        self.admin_shortcut.setContext(Qt.ApplicationShortcut)
        self.admin_shortcut.activated.connect(self._on_admin_shortcut)

    def _reset_admin_unlock(self):
        self._admin_unlock_state = 0

    def _on_admin_shortcut(self):
        if self._admin_unlock_state == 0:
            self._admin_unlock_state = 1
            self._admin_reset_timer.start(ADMIN_UNLOCK_TIMEOUT_MS)
        elif self._admin_unlock_state == 2:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()
            self.open_admin()
        else:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()

    def _on_podium_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._admin_unlock_state == 1:
            self._admin_unlock_state = 2
            self._admin_reset_timer.start(ADMIN_UNLOCK_TIMEOUT_MS)
        else:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()

    # --------------------------------------------------------
    #  密码读写
    # --------------------------------------------------------
    def _load_password(self):
        try:
            text = load_encrypted(PASSWORD_FILE, salt="password")
        except ValueError as e:
            QMessageBox.warning(self, "存档读取失败", str(e))
            text = None
        if not text:
            text = "123456"
        self.saved_password = text.strip()

    def _save_password(self, pwd):
        save_encrypted(PASSWORD_FILE, pwd, salt="password")
        self.saved_password = pwd

    def _load_teacher_password(self):
        try:
            text = load_encrypted(TEACHER_PASSWORD_FILE, salt="teacher")
        except ValueError as e:
            QMessageBox.warning(self, "存档读取失败", str(e))
            text = None
        if text is None:
            text = ""
        self.teacher_password = text.strip()

    def _save_teacher_password(self, pwd):
        save_encrypted(TEACHER_PASSWORD_FILE, pwd, salt="teacher")
        self.teacher_password = pwd

    # --------------------------------------------------------
    #  学生名单读写
    # --------------------------------------------------------
    def _load_students(self):
        names = []
        if os.path.exists(STUDENTS_FILE):
            try:
                text = load_encrypted(STUDENTS_FILE, salt="students")
                if text:
                    names = [ln.strip() for ln in text.splitlines() if ln.strip()]
            except ValueError:
                names = []

        if names:
            self.students = names
        else:
            self.students = list(STUDENT_NAMES)
            self._save_students()

    def _save_students(self):
        save_encrypted(STUDENTS_FILE, "\n".join(self.students), salt="students")

    def _real_students(self):
        return [s for s in self.students if not is_empty_student(s)]

    # --------------------------------------------------------
    #  上次坐后排名单读写（8.dat）
    # --------------------------------------------------------
    def _load_last_back_students(self):
        self.last_back_students = set()
        loaded_from_file = False

        if os.path.exists(LAST_BACK_FILE):
            try:
                text = load_encrypted(LAST_BACK_FILE, salt="lastback")
                if text:
                    for line in text.splitlines():
                        name = line.strip()
                        if name and not is_empty_student(name):
                            self.last_back_students.add(name)
                    loaded_from_file = True
            except ValueError:
                pass

        if not loaded_from_file and self.last_seating:
            for pos, name in self.last_seating.items():
                if is_back_seat(pos) and not is_empty_student(name):
                    self.last_back_students.add(name)

    def _save_last_back_students(self):
        lines = sorted(self.last_back_students)
        save_encrypted(LAST_BACK_FILE, "\n".join(lines), salt="lastback")

    # --------------------------------------------------------
    #  偏好学生的最近同桌记录（9.dat + 10.dat 双备份）
    # --------------------------------------------------------
    def _parse_recent_deskmates_text(self, text):
        if not text:
            return []
        result = []
        for line in text.splitlines():
            name = line.strip()
            if name == RECENT_EMPTY_MARKER:
                result.append("")
            elif name and not is_empty_student(name):
                result.append(name)
        return result[-DESK_COOLDOWN_TIMES:]

    def _load_recent_deskmates(self):
        """读取顺序：9.dat → 10.dat → 空"""
        self.recent_deskmates = []

        text = None
        try:
            text = load_encrypted(RECENT_DESKMATES_FILE, salt="recent")
        except ValueError:
            text = None

        if text is None:
            try:
                text = load_encrypted(
                    RECENT_DESKMATES_BAK_FILE, salt="recent_bak"
                )
            except ValueError:
                text = None

        if not text:
            return

        self.recent_deskmates = self._parse_recent_deskmates_text(text)

    def _save_recent_deskmates(self):
        """同时写入 9.dat（主）和 10.dat（备），保证两份镜像一致。"""
        lines = []
        for name in self.recent_deskmates[-DESK_COOLDOWN_TIMES:]:
            if name:
                lines.append(name)
            else:
                lines.append(RECENT_EMPTY_MARKER)
        payload = "\n".join(lines)

        try:
            save_encrypted(RECENT_DESKMATES_FILE, payload, salt="recent")
        except Exception:
            pass

        try:
            save_encrypted(
                RECENT_DESKMATES_BAK_FILE, payload, salt="recent_bak"
            )
        except Exception:
            pass

    def _recent_banned_partners(self):
        banned = set()
        for name in self.recent_deskmates[-DESK_COOLDOWN_TIMES:]:
            if name and not is_empty_student(name):
                banned.add(name)
        return banned

    # --------------------------------------------------------
    #  点名权重读写
    # --------------------------------------------------------
    def _load_pick_weights(self):
        self.pick_weights = {}
        try:
            text = load_encrypted(PICK_WEIGHTS_FILE, salt="pick")
        except ValueError as e:
            QMessageBox.warning(self, "存档读取失败", str(e))
            return
        if not text:
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
            if name and not is_empty_student(name):
                self.pick_weights[name] = w

    def _save_pick_weights(self):
        lines = []
        for name, w in self.pick_weights.items():
            if is_empty_student(name):
                continue
            if abs(w - DEFAULT_PICK_WEIGHT) > 1e-9:
                lines.append("%s,%s" % (name, w))
        save_encrypted(PICK_WEIGHTS_FILE, "\n".join(lines), salt="pick")

    # --------------------------------------------------------
    #  偏好配置读写（含目标坐前排概率）
    # --------------------------------------------------------
    def _load_desk_prefs(self):
        self.preferred_student = ""
        self.desired_deskmates = []
        self.probability = 80
        self.target_front_probability = 0

        try:
            text = load_encrypted(DESK_PREFS_FILE, salt="desk")
        except ValueError as e:
            QMessageBox.warning(self, "存档读取失败", str(e))
            return
        if not text:
            return

        lines = text.splitlines()
        if lines:
            self.preferred_student = lines[0].strip()

        idx = 1
        if len(lines) > 1:
            try:
                p = int(lines[1].strip())
                if 0 <= p <= 100:
                    self.probability = p
                    idx = 2
            except ValueError:
                idx = 1

        if len(lines) > idx:
            try:
                b = int(lines[idx].strip())
                if 0 <= b <= 100:
                    self.target_front_probability = b
                    idx += 1
            except ValueError:
                pass

        for line in lines[idx:]:
            name = line.strip()
            if name:
                self.desired_deskmates.append(name)

        if is_empty_student(self.preferred_student):
            self.preferred_student = ""
        self.desired_deskmates = [
            n for n in self.desired_deskmates if not is_empty_student(n)
        ]

    def _save_desk_prefs(self):
        lines = [
            self.preferred_student,
            str(self.probability),
            str(self.target_front_probability),
        ]
        lines.extend([n for n in self.desired_deskmates
                      if not is_empty_student(n)])
        save_encrypted(DESK_PREFS_FILE, "\n".join(lines), salt="desk")

    # --------------------------------------------------------
    #  座位表读写
    # --------------------------------------------------------
    def _load_last_seating(self):
        self.last_seating = {}
        try:
            text = load_encrypted(SEATING_FILE, salt="seating")
        except ValueError as e:
            QMessageBox.warning(self, "存档读取失败", str(e))
            return
        if not text:
            return

        row_map = get_row_columns()
        for r, line in enumerate(text.splitlines()):
            if r not in row_map:
                continue
            cols = row_map[r]
            names = line.split("\t")
            for i, name in enumerate(names):
                name = name.strip()
                if i < len(cols) and name and not is_empty_student(name):
                    self.last_seating[(r, cols[i])] = name

    def _save_seating(self, seating):
        row_map = get_row_columns()
        lines = []
        for r in sorted(row_map.keys()):
            cols = row_map[r]
            lines.append("\t".join(seating.get((r, c), "") for c in cols))
        save_encrypted(SEATING_FILE, "\n".join(lines), salt="seating")

    # --------------------------------------------------------
    #  管理员菜单窗口尺寸
    # --------------------------------------------------------
    def _load_ui_size(self):
        try:
            text = load_encrypted(UI_FILE, salt="ui")
        except ValueError:
            return get_safe_window_size(
                UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT, self
            )
        if not text:
            return get_safe_window_size(
                UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT, self
            )

        w, h = UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT
        try:
            parts = text.strip().split(",")
            w = int(parts[0])
            h = int(parts[1])
        except Exception:
            pass
        return get_safe_window_size(w, h, self)

    def _save_ui_size(self, w, h):
        try:
            save_encrypted(UI_FILE, "%d,%d" % (w, h), salt="ui")
        except Exception:
            pass

    # --------------------------------------------------------
    #  工具：查询某人的同桌
    # --------------------------------------------------------
    def _get_partner_in(self, seating, name):
        if not name or not seating:
            return ""
        pos = None
        for p, n in seating.items():
            if n == name:
                pos = p
                break
        if pos is None:
            return ""
        for p1, p2 in get_desk_pairs(self.seat_positions):
            if pos == p1:
                return seating.get(p2, "")
            if pos == p2:
                return seating.get(p1, "")
        return ""

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

        # ---------- 顶栏：左侧工具栏（可换行） + 右上角固定按钮组 ----------
        top_bar = QWidget()
        top_bar.setStyleSheet("background: transparent;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        # === 左侧：FlowLayout 工具栏 ===
        self._toolbar_widget = QWidget()
        self._toolbar_widget.setStyleSheet("background: transparent;")
        self._toolbar_widget.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Fixed
        )

        self._toolbar_layout = FlowLayout(
            self._toolbar_widget, margin=0, h_spacing=10, v_spacing=8
        )

        self.btn_generate = QPushButton("随机排座位")
        self.btn_pick = QPushButton("随机点名")
        self.btn_reload = QPushButton("读取存档")
        self.btn_export = QPushButton("导出座位表")
        self.btn_import = QPushButton("导入座位表")

        for btn, style in [
            (self.btn_generate, QSS_BTN_PRIMARY),
            (self.btn_pick, QSS_BTN_PICK),
            (self.btn_reload, QSS_BTN_NORMAL),
            (self.btn_export, QSS_BTN_NORMAL),
            (self.btn_import, QSS_BTN_IMPORT),
        ]:
            btn.setMinimumHeight(38)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(style)
            self._toolbar_layout.addWidget(btn)

        top_layout.addWidget(self._toolbar_widget, 1)

        # === 右侧：固定在右上角的按钮组 ===
        right_box = QWidget()
        right_box.setStyleSheet("background: transparent;")
        right_layout = QHBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self._right_box = right_box

        self.btn_author = QPushButton("作者")
        self.btn_teacher = QPushButton("设置")
        self.btn_minimize = QPushButton("−")     # U+2212 数学减号
        self.btn_close = QPushButton("×")        # U+00D7 乘号

        self.btn_minimize.setStyleSheet(QSS_BTN_SYMBOL)
        self.btn_close.setStyleSheet(QSS_BTN_CLOSE)
        self.btn_author.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_teacher.setStyleSheet(QSS_BTN_TEACHER)

        self.btn_minimize.setFixedSize(46, 38)
        self.btn_close.setFixedSize(46, 38)
        self.btn_author.setMinimumHeight(38)
        self.btn_teacher.setMinimumHeight(38)

        self.btn_author.setToolTip("作者")
        self.btn_teacher.setToolTip("设置")
        self.btn_minimize.setToolTip("最小化")
        self.btn_close.setToolTip("关闭")

        for btn in (self.btn_author, self.btn_teacher,
                    self.btn_minimize, self.btn_close):
            btn.setCursor(Qt.PointingHandCursor)
            right_layout.addWidget(btn)

        top_layout.addWidget(right_box, 0, Qt.AlignTop)

        root.addWidget(top_bar)

        # 信号连接
        self.btn_generate.clicked.connect(self.generate_seating)
        self.btn_pick.clicked.connect(self.open_name_picker)
        self.btn_reload.clicked.connect(self.reload_archive)
        self.btn_export.clicked.connect(self.export_seating)
        self.btn_import.clicked.connect(self.import_seating)
        self.btn_author.clicked.connect(self.show_author)
        self.btn_teacher.clicked.connect(self.open_teacher_menu)
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_close.clicked.connect(self.close)

        # ---------- 讲台 ----------
        podium_row = QHBoxLayout()
        podium_row.addStretch()
        podium = QLabel("讲　　台")
        podium.mousePressEvent = self._on_podium_click
        podium.setAlignment(Qt.AlignCenter)
        podium.setFixedSize(340, 38)
        podium.setStyleSheet("""
            QLabel {
                background-color: #455a64; color: #ffffff;
                border-radius: 8px; font-size: 15px; font-weight: bold;
                letter-spacing: 4px;
            }
        """)
        podium_row.addWidget(podium)
        podium_row.addStretch()
        root.addLayout(podium_row)

        # ---------- 座位区 ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        grid_holder = QWidget()
        grid_holder.setStyleSheet("background: transparent;")

        rows_layout = QVBoxLayout(grid_holder)
        rows_layout.setContentsMargins(4, 4, 4, 4)
        rows_layout.setSpacing(ROW_SPACING)

        total_rows = get_total_rows()
        row_map = get_row_columns()

        for r in range(total_rows):
            cols = row_map.get(r, [])

            row_wrap = QHBoxLayout()
            row_wrap.setContentsMargins(0, 0, 0, 0)
            row_wrap.setSpacing(0)

            row_wrap.addStretch(1)

            row_label = QLabel(f"第{r + 1}排")
            row_label.setAlignment(Qt.AlignCenter)
            row_label.setFixedWidth(LABEL_WIDTH)
            row_label.setStyleSheet(
                "QLabel { color: #90a4ae; font-size: 12px; }"
            )
            row_wrap.addWidget(row_label)

            row_wrap.addSpacing(LABEL_GAP)

            pairs = []
            i = 0
            while i < len(cols):
                if i + 1 < len(cols) and cols[i + 1] == cols[i] + 1:
                    pairs.append((cols[i], cols[i + 1]))
                    i += 2
                else:
                    pairs.append((cols[i], None))
                    i += 1

            for pi, (c1, c2) in enumerate(pairs):
                if pi > 0:
                    row_wrap.addSpacing(PAIR_SPACING)

                pair_widget = QWidget()
                pair_widget.setStyleSheet("background: transparent;")
                pl = QHBoxLayout(pair_widget)
                pl.setContentsMargins(0, 0, 0, 0)
                pl.setSpacing(PAIR_GAP)

                if c2 is not None:
                    pair_widget.setFixedWidth(SEAT_WIDTH * 2 + PAIR_GAP)
                else:
                    pair_widget.setFixedWidth(SEAT_WIDTH)

                lbl1 = SeatLabel(r, c1, is_back=is_back_seat((r, c1)))
                self.seat_widgets[(r, c1)] = lbl1
                pl.addWidget(lbl1)

                if c2 is not None:
                    lbl2 = SeatLabel(r, c2, is_back=is_back_seat((r, c2)))
                    self.seat_widgets[(r, c2)] = lbl2
                    pl.addWidget(lbl2)

                row_wrap.addWidget(pair_widget)

            row_wrap.addSpacing(LABEL_WIDTH + LABEL_GAP)
            row_wrap.addStretch(1)

            rows_layout.addLayout(row_wrap)

        scroll.setWidget(grid_holder)
        root.addWidget(scroll, 1)

        back_count = len([p for p in self.seat_positions if is_back_seat(p)])
        legend = QLabel(
            "🟧 后排（%d 座）　"
            "规则：上一次坐后排的同学，本次不再安排到后排"
            % back_count
        )
        legend.setAlignment(Qt.AlignCenter)
        legend.setStyleSheet("QLabel { color: #78909c; font-size: 12px; }")
        root.addWidget(legend)

        QTimer.singleShot(0, self._refresh_toolbar_height)

    # --------------------------------------------------------
    #  刷新 / 状态
    # --------------------------------------------------------
    def _refresh_seats(self):
        for pos, lbl in self.seat_widgets.items():
            name = self.current_seating.get(pos, "")
            if is_empty_student(name):
                name = ""
            lbl.set_name(name)

    def _update_status(self):
        real = len(self._real_students())
        empty = len(self.students) - real
        msg = f"学生 {real} 人"
        if empty > 0:
            msg += f"（空位 {empty}）"
        msg += (f"　|　座位 {len(self.seat_positions)} 个　|　"
                f"共 {get_total_rows()} 排")
        self.statusBar().showMessage(msg)

    # --------------------------------------------------------
    #  显示作者
    # --------------------------------------------------------
    def show_author(self):
        QMessageBox.information(self, "作者", "作者：myself")

    # --------------------------------------------------------
    #  打开点名器
    # --------------------------------------------------------
    def open_name_picker(self):
        names = [n for n in self.current_seating.values()
                 if n and not is_empty_student(n)]
        if not names:
            names = self._real_students()
        if not names:
            QMessageBox.information(self, "提示", "没有学生可供点名。")
            return
        dlg = NamePickerDialog(names, self.pick_weights, self)
        dlg.exec_()

    # --------------------------------------------------------
    #  打开设置菜单
    # --------------------------------------------------------
    def open_teacher_menu(self):
        ensure_archive_files()
        self._load_teacher_password()
        self._load_password()

        if self.teacher_password:
            pwd, ok = QInputDialog.getText(
                self, "设置",
                "请输入密码：",
                QLineEdit.Password,
            )
            if not ok:
                return
            if pwd != self.teacher_password and pwd != self.saved_password:
                QMessageBox.warning(self, "密码错误", "密码不正确，无法打开设置。")
                return

        dlg = TeacherDialog(
            self.students,
            teacher_password_set=bool(self.teacher_password),
            parent=self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return

        new_students = dlg.get_students()
        if new_students and new_students != self.students:
            old_students = list(self.students)
            self.students = new_students
            self._save_students()
            self._remap_seating_names(old_students, new_students)

        new_pwd = dlg.get_new_teacher_password()
        pwd_changed = False
        if new_pwd:
            self._save_teacher_password(new_pwd)
            pwd_changed = True

        self._refresh_seats()
        self._update_status()

        msg_parts = []
        if new_students:
            msg_parts.append("学生名单已保存")
        if pwd_changed:
            msg_parts.append("密码已更新")
        if msg_parts:
            self.statusBar().showMessage("、".join(msg_parts) + "。", 3000)

    def _remap_seating_names(self, old_list, new_list):
        mapping = {}
        for i, old_name in enumerate(old_list):
            if i < len(new_list):
                mapping[old_name] = new_list[i]

        changed = False
        for pos, name in list(self.current_seating.items()):
            if name in mapping:
                new_name = mapping[name]
                if is_empty_student(new_name):
                    del self.current_seating[pos]
                    changed = True
                elif new_name != name:
                    self.current_seating[pos] = new_name
                    changed = True

        if changed:
            self._save_seating(self.current_seating)
            self.last_seating = dict(self.current_seating)

        if is_empty_student(self.preferred_student):
            self.preferred_student = ""
        elif self.preferred_student in mapping:
            mapped = mapping[self.preferred_student]
            if is_empty_student(mapped):
                self.preferred_student = ""
            else:
                self.preferred_student = mapped

        new_deskmates = []
        for n in self.desired_deskmates:
            mapped = mapping.get(n, n)
            if not is_empty_student(mapped):
                new_deskmates.append(mapped)
        self.desired_deskmates = new_deskmates
        self._save_desk_prefs()

        if self.pick_weights and mapping:
            new_weights = {}
            for name, w in self.pick_weights.items():
                mapped = mapping.get(name, name)
                if not is_empty_student(mapped):
                    new_weights[mapped] = w
            self.pick_weights = new_weights
            self._save_pick_weights()

        if self.last_back_students and mapping:
            new_last_back = set()
            for name in self.last_back_students:
                mapped = mapping.get(name, name)
                if not is_empty_student(mapped):
                    new_last_back.add(mapped)
            self.last_back_students = new_last_back
            self._save_last_back_students()

        if self.recent_deskmates and mapping:
            new_recent = []
            for name in self.recent_deskmates:
                if not name:
                    new_recent.append("")
                    continue
                mapped = mapping.get(name, name)
                if not is_empty_student(mapped):
                    new_recent.append(mapped)
                else:
                    new_recent.append("")
            self.recent_deskmates = new_recent
            self._save_recent_deskmates()

    # --------------------------------------------------------
    #  打开管理员菜单（密码由解锁序列守护）
    # --------------------------------------------------------
    def open_admin(self):
        ensure_archive_files()
        self._load_password()

        pwd, ok = QInputDialog.getText(
            self, "身份验证",
            "请输入密码：",
            QLineEdit.Password,
        )
        if not ok:
            return
        if pwd != self.saved_password:
            QMessageBox.warning(self, "密码错误", "密码不正确，无法打开该窗口。")
            return

        real_students = self._real_students()

        dlg = AdminDialog(
            real_students,
            self.preferred_student,
            self.desired_deskmates,
            self.probability,
            self.target_front_probability,
            self.saved_password,
            self.pick_weights,
            self,
        )

        w, h = self._load_ui_size()
        dlg.resize(w, h)

        result = dlg.exec_()

        self._save_ui_size(dlg.width(), dlg.height())

        if result != QDialog.Accepted:
            return

        self.preferred_student = dlg.get_pref_student()
        self.desired_deskmates = dlg.get_desired_deskmates()
        self.probability = dlg.get_probability()
        self.target_front_probability = dlg.get_target_front_probability()
        self._save_desk_prefs()

        self.pick_weights = dlg.get_pick_weights()
        self._save_pick_weights()

        new_pwd = dlg.get_new_password()
        if new_pwd:
            self._save_password(new_pwd)

        self._refresh_seats()
        self._update_status()
        self.statusBar().showMessage("设置已保存。", 3000)

    # --------------------------------------------------------
    #  生成座位
    # --------------------------------------------------------
    def generate_seating(self):
        if not self.students:
            QMessageBox.warning(self, "提示", "学生名单为空。")
            return

        real_students = self._real_students()
        empty_count = len(self.students) - len(real_students)

        if not real_students:
            QMessageBox.warning(self, "提示", "没有真实学生（全部为空位），无法排座。")
            return

        all_pos_sorted = sorted(
            self.seat_positions,
            key=lambda p: (-p[0], -p[1])
        )
        empty_positions = set(all_pos_sorted[:empty_count])
        available_positions = [p for p in all_pos_sorted
                               if p not in empty_positions]

        back_positions = [p for p in available_positions if is_back_seat(p)]
        non_back_positions = [p for p in available_positions
                              if not is_back_seat(p)]

        strict_front_positions = [p for p in non_back_positions
                                  if is_front_row_seat(p)]

        last_back_names = set(self.last_back_students)
        last_back_names = {n for n in last_back_names
                           if not is_empty_student(n)}

        students = list(real_students)
        random.shuffle(students)

        candidates = [s for s in students if s not in last_back_names]
        random.shuffle(candidates)

        n_back = min(len(back_positions), len(candidates))
        back_people = candidates[:n_back]
        back_set = set(back_people)

        other_people = [s for s in students if s not in back_set]
        random.shuffle(other_people)

        new_seating = {}
        for pos, name in zip(back_positions, back_people):
            new_seating[pos] = name
        for pos, name in zip(non_back_positions, other_people):
            new_seating[pos] = name

        # ---- 偏好学生「目标坐前排」概率处理 ----
        if (self.preferred_student
                and not is_empty_student(self.preferred_student)
                and self.target_front_probability > 0
                and self.preferred_student in new_seating.values()):
            pref_pos = None
            for pos, n in new_seating.items():
                if n == self.preferred_student:
                    pref_pos = pos
                    break
            if pref_pos is not None and is_back_seat(pref_pos):
                if random.random() < self.target_front_probability / 100.0:
                    self._force_student_to_front(
                        new_seating, self.preferred_student,
                        strict_front_positions
                    )

        new_seating = self._apply_desk_preferences(new_seating)

        # 记录本次偏好学生的同桌（用于"最近 N 次同桌冷却"）
        if (self.preferred_student
                and not is_empty_student(self.preferred_student)
                and self.preferred_student in new_seating.values()):
            partner = self._get_partner_in(new_seating, self.preferred_student)
            if partner and is_empty_student(partner):
                partner = ""
            self.recent_deskmates.append(partner or "")
            if len(self.recent_deskmates) > DESK_COOLDOWN_TIMES:
                self.recent_deskmates = \
                    self.recent_deskmates[-DESK_COOLDOWN_TIMES:]
            self._save_recent_deskmates()

        # ---- 以最终座位表为准，重新统计"这次坐后排"的学生 ----
        # 修复：偏好学生被挪到前排 / 同桌交换时，被换到后排的同学
        #       原本会被漏记。以最终落点为准，逐座扫描。
        back_assigned_names = set()
        for pos, name in new_seating.items():
            if name and not is_empty_student(name) and is_back_seat(pos):
                back_assigned_names.add(name)
        # 偏好学生若本轮曾一度被分到后排，即使后来被强制挪到前排，
        # 仍按「坐过后排」计（后排轮换规则不变）
        if (self.preferred_student
                and self.preferred_student in back_set):
            back_assigned_names.add(self.preferred_student)

        self.current_seating = new_seating
        self._refresh_seats()
        self._save_seating(new_seating)
        self.last_seating = dict(new_seating)
        self.last_back_students = back_assigned_names
        self._save_last_back_students()

        # 状态栏只报总数，不暴露空位 / 偏好 / 前排 / 概率等任何机制
        self.statusBar().showMessage(
            "排座完成，共 %d 人。" % len(real_students), 3000
        )

    def _force_student_to_front(self, seating, name, front_positions):
        """把指定学生挪到前排。

        等价于：随机挑一个前 3 排的座位，和他现在的位置互换。
        """
        cur_pos = None
        for pos, n in seating.items():
            if n == name:
                cur_pos = pos
                break
        if cur_pos is None:
            return False
        if is_front_row_seat(cur_pos):
            return True
        if not front_positions:
            return False

        swap_pos = random.choice(front_positions)
        swap_name = seating.get(swap_pos, "")
        if not swap_name:
            seating[swap_pos] = name
            del seating[cur_pos]
            return True
        seating[swap_pos] = name
        seating[cur_pos] = swap_name
        return True

    # --------------------------------------------------------
    #  偏好同桌应用（含同桌冷却）
    # --------------------------------------------------------
    def _apply_desk_preferences(self, seating):
        if not self.preferred_student or not self.desired_deskmates:
            return seating
        if is_empty_student(self.preferred_student):
            return seating

        banned = self._recent_banned_partners()

        pref_pos = None
        for pos, name in seating.items():
            if name == self.preferred_student:
                pref_pos = pos
                break
        if pref_pos is None:
            return seating

        pref_pair = None
        for p1, p2 in get_desk_pairs(self.seat_positions):
            if pref_pos == p1 or pref_pos == p2:
                pref_pair = (p1, p2)
                break
        if pref_pair is None:
            return seating

        other_pos = pref_pair[0] if pref_pos == pref_pair[1] else pref_pair[1]
        current_partner = seating.get(other_pos, "")

        if (current_partner in self.desired_deskmates
                and current_partner not in banned):
            return seating

        probability = self.probability / 100.0
        if random.random() > probability:
            return seating

        candidates = [
            n for n in self.desired_deskmates
            if n and not is_empty_student(n) and n in seating.values()
            and n != self.preferred_student
            and n not in banned
        ]
        if not candidates:
            return seating

        chosen = random.choice(candidates)
        chosen_pos = None
        for pos, name in seating.items():
            if name == chosen:
                chosen_pos = pos
                break
        if chosen_pos is None:
            return seating

        seating[other_pos] = chosen
        seating[chosen_pos] = current_partner
        return seating

    # --------------------------------------------------------
    #  读取存档
    # --------------------------------------------------------
    def reload_archive(self):
        ensure_archive_files()
        self._load_password()
        self._load_teacher_password()
        self._load_students()
        self._load_desk_prefs()
        self._load_pick_weights()
        self._load_last_seating()
        self._load_last_back_students()
        self._load_recent_deskmates()
        self.current_seating = dict(self.last_seating)
        self._refresh_seats()
        self._update_status()
        self.statusBar().showMessage("已重新载入存档。", 3000)

    # --------------------------------------------------------
    #  导入座位表
    # --------------------------------------------------------
    def import_seating(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入座位表", "",
            "文本文件 (*.txt);;所有文件 (*.*)"
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
            except Exception:
                QMessageBox.critical(
                    self, "导入失败",
                    "文件内容无法识别，请确认是本程序导出的 txt。"
                )
                return
        except OSError:
            QMessageBox.critical(
                self, "导入失败",
                "文件无法读取，请确认文件未被占用、路径有效。"
            )
            return

        new_seating = parse_seating_text(text)

        if not new_seating:
            QMessageBox.warning(
                self, "导入失败",
                "未能从文件中解析出任何座位信息。\n\n"
                "请确认文件格式与导出的座位表一致：\n"
                "  每排以「第 N 排」开头，名字用全角空格或制表符分隔。"
            )
            return

        reply = QMessageBox.question(
            self, "确认导入",
            "已解析出 %d 个座位。\n\n"
            "导入后将覆盖当前座位表，并写入存档。\n"
            "是否继续？" % len(new_seating),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.current_seating = new_seating
        self._refresh_seats()
        self._save_seating(new_seating)
        self.last_seating = dict(new_seating)

        new_last_back = set()
        for pos, name in new_seating.items():
            if is_back_seat(pos) and not is_empty_student(name):
                new_last_back.add(name)
        self.last_back_students = new_last_back
        self._save_last_back_students()

        # 尝试从存档码恢复同桌冷却记录（有效则覆盖本地两份）
        self._try_restore_cooldown_from_code(text)

        self.statusBar().showMessage(
            "座位表已导入，共 %d 个座位。" % len(new_seating), 3000
        )

    def _try_restore_cooldown_from_code(self, text):
        """从导入文件里尝试解析存档码，恢复同桌冷却记录。

        返回 True 表示成功恢复；False 表示没有存档码 / 无效 / 旧格式。
        无论成功与否都不影响座位表导入。
        """
        lines = text.splitlines()
        in_code = False
        chunks = []
        for ln in lines:
            s = ln.strip()
            if s.startswith("存档码"):
                in_code = True
                continue
            if not in_code:
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
            return False

        b64 = "".join(chunks)
        try:
            raw = decrypt_text(b64, salt="export_code")
        except Exception:
            return False

        try:
            data = json.loads(raw)
        except Exception:
            return False

        if not isinstance(data, dict):
            return False

        rd = data.get("recent_deskmates")
        if not isinstance(rd, list):
            return False

        real_set = set(self._real_students())
        valid = []
        for n in rd[-DESK_COOLDOWN_TIMES:]:
            if not isinstance(n, str):
                valid.append("")
            elif n == "" or is_empty_student(n):
                valid.append("")
            elif n in real_set:
                valid.append(n)
            else:
                valid.append("")

        while len(valid) < DESK_COOLDOWN_TIMES:
            valid.insert(0, "")

        # 覆盖内存 + 双文件（9.dat 主 / 10.dat 备）
        self.recent_deskmates = valid[-DESK_COOLDOWN_TIMES:]
        self._save_recent_deskmates()
        return True

    # --------------------------------------------------------
    #  导出座位表（含"存档码"）
    # --------------------------------------------------------
    def export_seating(self):
        if not self.current_seating:
            QMessageBox.information(self, "提示", "当前没有座位表，请先排座。")
            return

        # 导出前，先把当前记录同步到 9.dat 和 10.dat，
        # 保证本地两份备份与 txt 里的存档码完全一致
        try:
            self._save_recent_deskmates()
        except Exception:
            pass

        default_name = "座位表_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出座位表", default_name, "文本文件 (*.txt)"
        )
        if not path:
            return

        row_map = get_row_columns()

        lines = []
        lines.append("=" * 46)
        lines.append("座　位　表")
        lines.append("导出时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("=" * 46)
        lines.append("")

        for r in sorted(row_map.keys()):
            cols = row_map[r]
            names = [self.current_seating.get((r, c), "（空）") for c in cols]
            lines.append(f"第 {r + 1} 排：")
            lines.append("    " + "　".join(names))
            lines.append("")

        # ============================================================
        # 存档码：加密保存「偏好学生的最近同桌记录」等关键状态。
        # 导入座位表时若检测到有效存档码，会自动恢复这份记录，
        # 从而避免 9.dat / 10.dat 被误删 / 换机 / 反复随机排座
        # 导致的冷却丢失。
        # ============================================================
        snapshot = {
            "v": 1,
            "recent_deskmates": list(
                self.recent_deskmates[-DESK_COOLDOWN_TIMES:]
            ),
            "preferred_student": self.preferred_student or "",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            code_text = encrypt_text(
                json.dumps(snapshot, ensure_ascii=False),
                salt="export_code",
            )
        except Exception:
            code_text = ""

        code_lines = []
        for i in range(0, len(code_text), 64):
            code_lines.append(code_text[i:i + 64])

        # 兜底：加密失败时用随机字符填充，看起来同样像校验码
        if not code_lines:
            import string
            alphabet = string.ascii_letters + string.digits
            code_lines = [
                "".join(random.choice(alphabet) for _ in range(64))
                for _ in range(6)
            ]

        lines.append("")
        lines.append("-" * 46)
        lines.append("存档码：")
        for cl in code_lines:
            lines.append("    " + cl)
        lines.append("")
        lines.append("（删除存档码则有可能无法读取）")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError:
            QMessageBox.critical(
                self, "导出失败",
                "文件保存失败，请换个位置或检查磁盘空间。"
            )
            return

        QMessageBox.information(self, "导出成功", "座位表已导出到：\n" + path)


# ============================================================
#  入口
# ============================================================
def main():
    # ★ 高 DPI 支持：必须在 QApplication 创建之前设置
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setFont(get_ui_font(10))

    win = MainWindow()

    # 用 availableGeometry 铺满可用区域（不含任务栏），窗口本身无标题栏
    screen = app.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        win.setGeometry(avail)

        # 最小尺寸也按屏幕收缩，避免小屏上强制大尺寸
        win.setMinimumSize(
            min(560, max(400, avail.width() - 200)),
            min(400, max(300, avail.height() - 200)),
        )

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
