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
    │    9.dat  →  偏好学生的最近同桌记录           │
    └───────────────────────────────────────────────┘
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
ADMIN_SHORTCUT = "Ctrl+X"
ADMIN_UNLOCK_TIMEOUT_MS = 500

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
    "q1", "q2", "q3", "q4", "q5",
    "q6", "q7", "q8", "q9", "q10",
    "q11", "q12", "q13", "q14", "q15",
    "q16", "q17", "q18", "q19", "q20",
    "q21", "q22", "q23", "q24", "q25",
    "q26", "q27", "q28", "q29", "q30",
    "q31", "q32", "q33", "q34", "q35",
    "q36", "q37", "q38", "q39", "q40",
    "q41", "q42", "q43", "q44",
]


# ============================================================
#  📦  内置存档
# ============================================================
_BUILTIN_ARCHIVE_JSON = json.dumps(
    {
        "password": "1",
        "teacher_password": "",
        "desk_prefs": "q23\n60\n75\nq3\nq4\nq5\nq6",
        "last_seating": "",
        "pick_weights": "q23,0.3",
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


def get_safe_window_size(desired_w, desired_h):
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return desired_w, desired_h
        screen = app.primaryScreen()
        if screen is None:
            return desired_w, desired_h
        avail = screen.availableGeometry()
        max_w = max(420, avail.width() - 80)
        max_h = max(520, avail.height() - 100)
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
                       archive.get("password", "1"),
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
    return pos[0] < get_front_row_count()


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
            # 跳过存档码区域
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
    parts = re.split(r"[　\t]+|\s{2,}", text)
    return [p.strip() for p in parts if p.strip()]


# ============================================================
#  PyQt 导入（提前导入，方便定义 get_ui_font）
# ============================================================
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QFontDatabase, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QDialog,
    QDialogButtonBox, QFileDialog, QLineEdit, QSlider,
    QComboBox, QInputDialog, QScrollArea, QShortcut, QGroupBox,
    QTextEdit, QDoubleSpinBox,
)


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
    padding: 0px; font-size: 14px; font-weight: bold;
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
        self.setWindowTitle("点名概率设置")
        self.setMinimumSize(460, 620)
        self.setStyleSheet("background-color: #fafafa;")
        self.students = [s for s in students if not is_empty_student(s)]

        w0, h0 = get_safe_window_size(520, 700)
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
            "默认每个学生的被点概率为 1/44（约 2.27%）。\n"
            "设置倍率 x 后，该学生被点到的概率约为 x × (1/44)。\n"
            "倍率 0 表示不会被点到；倍率 1.0 为默认值。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        header = QHBoxLayout()
        h1 = QLabel("学生")
        h1.setStyleSheet("QLabel { color: #455a64; font-size: 12px; font-weight: bold; }")
        h2 = QLabel("倍率 x")
        h2.setStyleSheet("QLabel { color: #455a64; font-size: 12px; font-weight: bold; }")
        h2.setFixedWidth(120)
        h3 = QLabel("实际概率")
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
        self.setMinimumSize(520, 440)
        self.setStyleSheet("background-color: #263238;")
        self.all_names = [n for n in names if n and not is_empty_student(n)]
        if not self.all_names:
            self.all_names = ["（无学生）"]
        self.weights = dict(weights) if weights else {}
        self.history = []

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
        self.setMinimumSize(520, 600)
        self.setStyleSheet("background-color: #fafafa;")
        self._new_teacher_password = None
        self._final_students = None

        w0, h0 = get_safe_window_size(600, 760)
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
        self.students_edit.setMinimumHeight(240)
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

        status_text = "当前状态：已设置" if teacher_password_set else "当前状态：未设置（打开设置无需密码）"
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
            "提示：设置密码后，打开设置需要输入该密码或管理员密码。\n"
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
        reverted = []
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
                reverted.append((i, name, default[i]))

        return result, reverted

    def _on_ok(self):
        names = [ln.strip() for ln in self.students_edit.toPlainText().splitlines()
                 if ln.strip()]
        if not names:
            QMessageBox.warning(self, "提示", "学生名单不能为空。")
            return

        names, _ = self._detect_and_revert_swaps(names)
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
        self.setMinimumSize(420, 480)
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
            "⑤ 点名概率：可设置每个学生被点到的倍率。\n"
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

        pick_group = QGroupBox("点名概率")
        pick_group.setStyleSheet(QSS_GROUPBOX)
        pick_layout = QHBoxLayout(pick_group)
        pick_layout.setContentsMargins(12, 8, 12, 10)
        pick_layout.setSpacing(10)

        pick_hint = QLabel(
            "默认每个学生被点到的概率为 1/44。\n"
            "可设置倍率 x，使该学生被点概率 ≈ x × (1/44)。"
        )
        pick_hint.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        pick_hint.setWordWrap(True)
        pick_layout.addWidget(pick_hint, 1)

        self.btn_pick = QPushButton("设置点名概率")
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
            combo.setFixedWidth(230)
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
                "点名概率已更新，点确定保存管理员设置后写入存档。"
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

    def set_name(self, name):
        if name and not is_empty_student(name):
            self.setText(name)
            if self.is_back:
                self.setStyleSheet(QSS_BACK)
            else:
                self.setStyleSheet(QSS_NORMAL)
            tip = f"第 {self.row + 1} 排  第 {self.col + 1} 列\n{name}"
            if self.is_back:
                tip += "\n（后排）"
            self.setToolTip(tip)
        else:
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
        # 去掉标题栏（无边框窗口）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(720, 520)

        self.students = []
        self.preferred_student = ""
        self.desired_deskmates = []
        self.probability = 80
        self.target_front_probability = 0
        self.saved_password = "1"
        self.teacher_password = ""
        self.pick_weights = {}
        self.last_back_students = set()
        # 偏好学生的同桌历史（最新的在尾部，最多 DESK_COOLDOWN_TIMES 条）
        self.recent_deskmates = []

        self.seat_positions = get_seat_positions()
        self.seat_widgets = {}
        self.current_seating = {}
        self.last_seating = {}

        # 标记：按钮自适应宽度是否已经处理过（在 showEvent 里只处理一次）
        self._btn_widths_fixed = False

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
    #  窗口显示时，按内容自适应按钮宽度（跨 DPI 更稳）
    # --------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._btn_widths_fixed:
            self._btn_widths_fixed = True
            self._apply_adaptive_btn_widths()

    def _apply_adaptive_btn_widths(self):
        """在 UI 完全就绪后，按内容宽度自适应设置"作者"和"设置"按钮

        兼容旧版本 Qt：Qt 5.11 之前没有 horizontalAdvance，用 width() 兜底。
        """
        try:
            for btn in (getattr(self, "btn_author", None),
                        getattr(self, "btn_teacher", None)):
                if btn is None:
                    continue
                fm = btn.fontMetrics()
                # 兼容不同 Qt 版本
                if hasattr(fm, "horizontalAdvance"):
                    text_w = fm.horizontalAdvance(btn.text())
                else:
                    text_w = fm.width(btn.text())
                btn.setMinimumWidth(max(text_w + 40, btn.sizeHint().width()))
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
        """管理员解锁状态机：
           空闲 → 按快捷键：进入等待点讲台
           已点讲台 → 按快捷键：打开管理员菜单
           其他情况 → 重置为闲置
        """
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
        """讲台被点击：只有第一步完成后才有效，且只响应左键"""
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
            text = "1"
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
    #  偏好学生的最近同桌记录（9.dat）
    # --------------------------------------------------------
    def _load_recent_deskmates(self):
        self.recent_deskmates = []
        if not os.path.exists(RECENT_DESKMATES_FILE):
            return
        try:
            text = load_encrypted(RECENT_DESKMATES_FILE, salt="recent")
        except ValueError:
            return
        if not text:
            return
        for line in text.splitlines():
            name = line.strip()
            if name == RECENT_EMPTY_MARKER:
                self.recent_deskmates.append("")
            elif name and not is_empty_student(name):
                self.recent_deskmates.append(name)
        self.recent_deskmates = self.recent_deskmates[-DESK_COOLDOWN_TIMES:]

    def _save_recent_deskmates(self):
        lines = []
        for name in self.recent_deskmates[-DESK_COOLDOWN_TIMES:]:
            if name:
                lines.append(name)
            else:
                lines.append(RECENT_EMPTY_MARKER)
        save_encrypted(RECENT_DESKMATES_FILE, "\n".join(lines), salt="recent")

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
            return get_safe_window_size(UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT)
        if not text:
            return get_safe_window_size(UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT)

        w, h = UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT
        try:
            parts = text.strip().split(",")
            w = int(parts[0])
            h = int(parts[1])
        except Exception:
            pass
        return get_safe_window_size(w, h)

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

        bar = QHBoxLayout()
        bar.setSpacing(10)

        # ---------- 左侧：常用操作 ----------
        self.btn_generate = QPushButton("🎲  随机排座位")
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
            bar.addWidget(btn)

        # ---------- 中间弹性空白 ----------
        bar.addStretch()

        # ---------- 右侧：作者、设置、最小化、关闭 ----------
        self.btn_author = QPushButton("作者")
        self.btn_teacher = QPushButton("设置")
        self.btn_minimize = QPushButton("−")     # U+2212 数学减号
        self.btn_close = QPushButton("✕")        # U+2715 乘号

        # 符号按钮：字号加大，样式去掉 padding 以免符号被裁切
        symbol_font = get_ui_font(20, bold=True)
        self.btn_minimize.setFont(symbol_font)
        self.btn_close.setFont(symbol_font)
        self.btn_minimize.setStyleSheet(QSS_BTN_SYMBOL)
        self.btn_close.setStyleSheet(QSS_BTN_CLOSE)

        self.btn_author.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_teacher.setStyleSheet(QSS_BTN_TEACHER)

        # 符号按钮：固定大小，防止符号变形
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
            bar.addWidget(btn)

        root.addLayout(bar)

        self.btn_generate.clicked.connect(self.generate_seating)
        self.btn_pick.clicked.connect(self.open_name_picker)
        self.btn_reload.clicked.connect(self.reload_archive)
        self.btn_export.clicked.connect(self.export_seating)
        self.btn_import.clicked.connect(self.import_seating)
        self.btn_author.clicked.connect(self.show_author)
        self.btn_teacher.clicked.connect(self.open_teacher_menu)
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_close.clicked.connect(self.close)

        podium_row = QHBoxLayout()
        podium_row.addStretch()
        podium = QLabel("讲　　台")
        # 讲台支持点击：用于管理员解锁序列（故意不加手型光标，避免被发现）
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
        QMessageBox.information(self, "作者", "作者：从摸鱼做起")

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

        # 同步同桌历史里的名字
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

        back_assigned_names = set(back_people)

        target_triggered = False
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
                    if self._force_student_to_front(
                        new_seating, self.preferred_student,
                        strict_front_positions
                    ):
                        target_triggered = True
                        back_assigned_names.add(self.preferred_student)

        new_seating, matched = self._apply_desk_preferences(new_seating)

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

        self.current_seating = new_seating
        self._refresh_seats()
        self._save_seating(new_seating)
        self.last_seating = dict(new_seating)
        self.last_back_students = back_assigned_names
        self._save_last_back_students()

        msg = "排座完成，共 %d 人" % len(real_students)
        if empty_count > 0:
            msg += "（空位 %d 已安排到后排）" % empty_count
        if target_triggered:
            msg += "；%s 已按概率安排到前排（仍计入后排轮换）" % self.preferred_student
        self.statusBar().showMessage(msg + "。", 3000)

    def _force_student_to_front(self, seating, name, front_positions):
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

        swap_candidates = list(front_positions)
        random.shuffle(swap_candidates)

        for swap_pos in swap_candidates:
            swap_name = seating.get(swap_pos, "")
            if not swap_name:
                seating[swap_pos] = name
                del seating[cur_pos]
                return True
            seating[swap_pos] = name
            seating[cur_pos] = swap_name
            return True

        return False

    # --------------------------------------------------------
    #  偏好同桌应用（含同桌冷却）
    # --------------------------------------------------------
    def _apply_desk_preferences(self, seating):
        if not self.preferred_student or not self.desired_deskmates:
            return seating, 0
        if is_empty_student(self.preferred_student):
            return seating, 0

        banned = self._recent_banned_partners()

        pref_pos = None
        for pos, name in seating.items():
            if name == self.preferred_student:
                pref_pos = pos
                break
        if pref_pos is None:
            return seating, 0

        pref_pair = None
        for p1, p2 in get_desk_pairs(self.seat_positions):
            if pref_pos == p1 or pref_pos == p2:
                pref_pair = (p1, p2)
                break
        if pref_pair is None:
            return seating, 0

        other_pos = pref_pair[0] if pref_pos == pref_pair[1] else pref_pair[1]
        current_partner = seating.get(other_pos, "")

        if (current_partner in self.desired_deskmates
                and current_partner not in banned):
            return seating, 1

        probability = self.probability / 100.0
        if random.random() > probability:
            return seating, 0

        candidates = [
            n for n in self.desired_deskmates
            if n and not is_empty_student(n) and n in seating.values()
            and n != self.preferred_student
            and n not in banned
        ]
        if not candidates:
            return seating, 0

        chosen = random.choice(candidates)
        chosen_pos = None
        for pos, name in seating.items():
            if name == chosen:
                chosen_pos = pos
                break
        if chosen_pos is None:
            return seating, 0

        seating[other_pos] = chosen
        seating[chosen_pos] = current_partner
        return seating, 1

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
            except Exception as e:
                QMessageBox.critical(self, "导入失败", "无法读取文件：\n" + str(e))
                return
        except OSError as e:
            QMessageBox.critical(self, "导入失败", str(e))
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

        self.statusBar().showMessage(
            "座位表已导入，共 %d 个座位。" % len(new_seating), 3000
        )

    # --------------------------------------------------------
    #  导出座位表（含"存档码"，纯威慑）
    # --------------------------------------------------------
    def export_seating(self):
        if not self.current_seating:
            QMessageBox.information(self, "提示", "当前没有座位表，请先排座。")
            return

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
        # 存档码（伪）：内容其实是把座位表原文再加密一次，
        # 仅供学生看，程序导入时并不校验。学生看到这句话后不敢删改。
        # ============================================================
        raw_for_code = "\n".join(lines)
        try:
            code_text = encrypt_text(raw_for_code, salt="export_code")
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
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
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
            min(720, max(480, avail.width() - 200)),
            min(520, max(360, avail.height() - 200)),
        )

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
