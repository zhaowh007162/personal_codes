# -*- coding: utf-8 -*-
"""
存档解密编辑器 —— 用于编辑主程序生成的加密存档
============================================================
功能：
    · 图形化编辑 2.dat（偏好配置：偏好学生 / 配对概率 / 目标坐前排概率 / 意愿同桌）
    · 图形化编辑 7.dat（点名权重：每个学生的被点倍率）
    · 代码输出台：实时把当前配置输出成可粘贴进主程序的 Python 代码
    · 使用与主程序一致的 XOR + Base64 加解密
    · 自动从 6.dat 读取学生名单

使用：
    把本脚本和主程序放在同一台电脑上，运行即可。
    存档目录默认 D:/JiXiu，可在顶部修改。
"""

import os
import re
import sys
import base64
import hashlib

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QGuiApplication
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox,
    QComboBox, QSlider, QDoubleSpinBox, QLineEdit,
    QScrollArea, QGroupBox, QTabWidget, QFileDialog,
    QTextEdit, QSplitter,
)


# ============================================================
#  配置（必须与主程序一致，否则无法解密）
# ============================================================
CRYPTO_SEED = "SeatCrypto_2024_@#!$%^"

MAX_DESK_CHOICES = 14
MAX_PICK_WEIGHT = 20.0
DEFAULT_PICK_WEIGHT = 1.0

FILE_DESK_PREFS = "2.dat"
FILE_PICK_WEIGHTS = "7.dat"
FILE_STUDENTS = "6.dat"

EMPTY_STUDENT_MARKERS = ("(空)", "（空）")
DEFAULT_STUDENT_NAMES = [f"学生{i:02d}" for i in range(1, 45)]


def is_empty_student(name):
    if not name:
        return False
    return name.strip() in EMPTY_STUDENT_MARKERS


# ============================================================
#  加密 / 解密
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


def save_encrypted(path, text, salt=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(encrypt_text(text, salt))


def load_encrypted(path, salt=""):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        b64 = f.read().strip()
    if not b64:
        return ""
    return decrypt_text(b64, salt)


# ============================================================
#  存档目录解析
# ============================================================
def resolve_archive_dir():
    primary = "D:/JiXiu"
    try:
        os.makedirs(primary, exist_ok=True)
        test = os.path.join(primary, ".writetest")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return primary
    except Exception:
        fallback = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "JiXiu"
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


# ============================================================
#  样式
# ============================================================
QSS_BTN = """
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

QSS_BTN_COPY = """
QPushButton {
    background-color: #00897b; color: #ffffff;
    border: none; border-radius: 6px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton:hover  { background-color: #00796b; }
QPushButton:pressed{ background-color: #00695c; }
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


# ============================================================
#  工具：生成 / 解析 字符串
# ============================================================
def build_desk_prefs_string(preferred, probability, front_prob, deskmates):
    lines = [preferred, str(probability), str(front_prob)]
    lines.extend([n for n in deskmates if n])
    return "\n".join(lines)


def build_pick_weights_string(weights_dict):
    lines = []
    for name, w in weights_dict.items():
        if abs(w - DEFAULT_PICK_WEIGHT) > 1e-9:
            lines.append("%s,%s" % (name, w))
    return "\n".join(lines)


def escape_python_string(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def python_literal_from_lines(raw):
    return escape_python_string(raw)


def parse_desk_prefs_from_literal(text):
    real = text.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
    lines = real.splitlines()
    preferred = lines[0].strip() if lines else ""
    probability = 80
    front_prob = 0
    deskmates = []

    idx = 1
    if len(lines) > 1:
        try:
            p = int(lines[1].strip())
            if 0 <= p <= 100:
                probability = p
                idx = 2
        except ValueError:
            idx = 1

    if len(lines) > idx:
        try:
            b = int(lines[idx].strip())
            if 0 <= b <= 100:
                front_prob = b
                idx += 1
        except ValueError:
            pass

    for line in lines[idx:]:
        name = line.strip()
        if name:
            deskmates.append(name)

    return preferred, probability, front_prob, deskmates


def parse_pick_weights_from_literal(text):
    real = text.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
    result = {}
    for line in real.splitlines():
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
        if name:
            result[name] = w
    return result


# ============================================================
#  偏好配置编辑 Tab（2.dat）
# ============================================================
class DeskPrefsTab(QWidget):
    def __init__(self, get_archive_dir, get_students, set_status,
                 on_changed=None):
        super().__init__()
        self.get_archive_dir = get_archive_dir
        self.get_students = get_students
        self.set_status = set_status
        self.on_changed = on_changed

        self.desk_combos = []
        self._build_ui()
        self.refresh_students()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self.btn_load = QPushButton("📂  读取 2.dat")
        self.btn_save = QPushButton("💾  保存到 2.dat")
        self.btn_load.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_save.setStyleSheet(QSS_BTN)
        for b in (self.btn_load, self.btn_save):
            b.setMinimumHeight(36)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_load.clicked.connect(self.load_from_file)
        self.btn_save.clicked.connect(self.save_to_file)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_save)
        bar.addStretch()
        root.addLayout(bar)

        pref_group = QGroupBox("偏好学生")
        pref_group.setStyleSheet(QSS_GROUPBOX)
        pref_layout = QHBoxLayout(pref_group)
        pref_layout.setContentsMargins(12, 12, 12, 12)
        pref_layout.addWidget(QLabel("偏好学生："))
        self.pref_combo = QComboBox()
        self.pref_combo.setFixedWidth(220)
        self.pref_combo.setFont(QFont("Microsoft YaHei", 10))
        self.pref_combo.addItem("（未设置）", "")
        self.pref_combo.currentIndexChanged.connect(self._on_any_changed)
        pref_layout.addWidget(self.pref_combo)
        pref_layout.addStretch()
        root.addWidget(pref_group)

        prob_group = QGroupBox("概率设置")
        prob_group.setStyleSheet(QSS_GROUPBOX)
        prob_layout = QGridLayout(prob_group)
        prob_layout.setContentsMargins(12, 12, 12, 12)
        prob_layout.setHorizontalSpacing(12)
        prob_layout.setVerticalSpacing(10)

        prob_layout.addWidget(QLabel("配对概率："), 0, 0)
        self.prob_slider = QSlider(Qt.Horizontal)
        self.prob_slider.setRange(0, 100)
        self.prob_slider.setValue(80)
        self.prob_slider.setFixedWidth(300)
        self.prob_slider.setCursor(Qt.PointingHandCursor)
        self.prob_slider.valueChanged.connect(self._on_prob_changed)
        prob_layout.addWidget(self.prob_slider, 0, 1)
        self.prob_label = QLabel("80%")
        self.prob_label.setFixedWidth(60)
        self.prob_label.setAlignment(Qt.AlignCenter)
        self.prob_label.setStyleSheet(
            "QLabel { font-size: 13px; font-weight: bold; color: #1976d2;"
            " background: #e3f2fd; border-radius: 4px; padding: 3px 0; }"
        )
        prob_layout.addWidget(self.prob_label, 0, 2)

        prob_layout.addWidget(QLabel("目标坐前排概率："), 1, 0)
        self.front_slider = QSlider(Qt.Horizontal)
        self.front_slider.setRange(0, 100)
        self.front_slider.setValue(0)
        self.front_slider.setFixedWidth(300)
        self.front_slider.setCursor(Qt.PointingHandCursor)
        self.front_slider.valueChanged.connect(self._on_front_changed)
        prob_layout.addWidget(self.front_slider, 1, 1)
        self.front_label = QLabel("0%")
        self.front_label.setFixedWidth(60)
        self.front_label.setAlignment(Qt.AlignCenter)
        self.front_label.setStyleSheet(
            "QLabel { font-size: 13px; font-weight: bold; color: #2e7d32;"
            " background: #e8f5e9; border-radius: 4px; padding: 3px 0; }"
        )
        prob_layout.addWidget(self.front_label, 1, 2)

        prob_layout.setColumnStretch(3, 1)
        root.addWidget(prob_group)

        desk_group = QGroupBox(
            "意愿同桌（最多 %d 人，留空表示不使用）" % MAX_DESK_CHOICES
        )
        desk_group.setStyleSheet(QSS_GROUPBOX)
        desk_outer = QVBoxLayout(desk_group)
        desk_outer.setContentsMargins(12, 12, 12, 12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        grid = QGridLayout(inner)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)

        for i in range(MAX_DESK_CHOICES):
            lbl = QLabel("第 %02d 位" % (i + 1))
            lbl.setFixedWidth(70)
            lbl.setStyleSheet("QLabel { color: #607d8b; font-size: 12px; }")

            combo = QComboBox()
            combo.setFixedWidth(230)
            combo.setFont(QFont("Microsoft YaHei", 10))
            combo.addItem("（空）", "")
            combo.currentIndexChanged.connect(self._on_any_changed)
            self.desk_combos.append(combo)

            grid.addWidget(lbl, i, 0)
            grid.addWidget(combo, i, 1)

        grid.setColumnStretch(2, 1)
        scroll.setWidget(inner)
        desk_outer.addWidget(scroll)
        root.addWidget(desk_group, 1)

    def _on_prob_changed(self, val):
        self.prob_label.setText("%d%%" % val)
        self._on_any_changed()

    def _on_front_changed(self, val):
        self.front_label.setText("%d%%" % val)
        self._on_any_changed()

    def _on_any_changed(self):
        if self.on_changed:
            self.on_changed()

    def refresh_students(self):
        students = self.get_students()

        cur_pref = self.pref_combo.currentData()
        self.pref_combo.blockSignals(True)
        self.pref_combo.clear()
        self.pref_combo.addItem("（未设置）", "")
        for s in students:
            if not is_empty_student(s):
                self.pref_combo.addItem(s, s)
        idx = self.pref_combo.findData(cur_pref)
        if idx >= 0:
            self.pref_combo.setCurrentIndex(idx)
        self.pref_combo.blockSignals(False)

        cur_values = [c.currentData() for c in self.desk_combos]
        for i, combo in enumerate(self.desk_combos):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("（空）", "")
            for s in students:
                if not is_empty_student(s):
                    combo.addItem(s, s)
            if i < len(cur_values) and cur_values[i]:
                idx = combo.findData(cur_values[i])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def load_from_file(self):
        path = os.path.join(self.get_archive_dir(), FILE_DESK_PREFS)
        if not os.path.exists(path):
            self._apply_values("", 80, 0, [])
            self.set_status("2.dat 不存在，使用默认空配置")
            return
        try:
            text = load_encrypted(path, salt="desk")
        except Exception as e:
            QMessageBox.critical(
                self, "解密失败",
                "无法解密该文件：\n%s\n\n"
                "可能原因：加密种子不一致 / 文件已损坏。" % e
            )
            return

        if not text:
            self._apply_values("", 80, 0, [])
            self.set_status("2.dat 内容为空，使用默认空配置")
            return

        lines = text.splitlines()
        preferred = lines[0].strip() if lines else ""
        probability = 80
        front_prob = 0
        deskmates = []

        idx = 1
        if len(lines) > 1:
            try:
                p = int(lines[1].strip())
                if 0 <= p <= 100:
                    probability = p
                    idx = 2
            except ValueError:
                idx = 1

        if len(lines) > idx:
            try:
                b = int(lines[idx].strip())
                if 0 <= b <= 100:
                    front_prob = b
                    idx += 1
            except ValueError:
                pass

        for line in lines[idx:]:
            name = line.strip()
            if name:
                deskmates.append(name)

        self._apply_values(preferred, probability, front_prob, deskmates)
        self.set_status("已从 2.dat 读取")

    def _apply_values(self, preferred, probability, front_prob, deskmates):
        i = self.pref_combo.findData(preferred)
        if i >= 0:
            self.pref_combo.setCurrentIndex(i)
        else:
            self.pref_combo.setCurrentIndex(0)

        self.prob_slider.setValue(int(probability))
        self.front_slider.setValue(int(front_prob))

        for i, combo in enumerate(self.desk_combos):
            if i < len(deskmates):
                idx2 = combo.findData(deskmates[i])
                if idx2 >= 0:
                    combo.setCurrentIndex(idx2)
                else:
                    combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(0)

        if self.on_changed:
            self.on_changed()

    def get_values(self):
        preferred = self.pref_combo.currentData() or ""
        probability = self.prob_slider.value()
        front_prob = self.front_slider.value()
        deskmates = []
        for combo in self.desk_combos:
            name = combo.currentData()
            if name:
                deskmates.append(name)
        return preferred, probability, front_prob, deskmates

    def save_to_file(self):
        path = os.path.join(self.get_archive_dir(), FILE_DESK_PREFS)
        preferred, probability, front_prob, deskmates = self.get_values()

        if preferred and preferred in deskmates:
            QMessageBox.warning(
                self, "校验失败",
                "偏好学生「%s」同时出现在意愿同桌中，请调整。" % preferred
            )
            return

        raw = build_desk_prefs_string(
            preferred, probability, front_prob, deskmates
        )
        try:
            save_encrypted(path, raw, salt="desk")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return

        self.set_status("已保存到 2.dat")


# ============================================================
#  点名权重编辑 Tab（7.dat）
# ============================================================
class PickWeightsTab(QWidget):
    def __init__(self, get_archive_dir, get_students, set_status,
                 on_changed=None):
        super().__init__()
        self.get_archive_dir = get_archive_dir
        self.get_students = get_students
        self.set_status = set_status
        self.on_changed = on_changed

        self.spins = {}
        self.prob_labels = {}
        self._build_ui()
        self.refresh_students()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self.btn_load = QPushButton("📂  读取 7.dat")
        self.btn_save = QPushButton("💾  保存到 7.dat")
        self.btn_reset = QPushButton("🔄  全部重置为 1.0")
        self.btn_load.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_save.setStyleSheet(QSS_BTN)
        self.btn_reset.setStyleSheet(QSS_BTN_NORMAL)
        for b in (self.btn_load, self.btn_save, self.btn_reset):
            b.setMinimumHeight(36)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_load.clicked.connect(self.load_from_file)
        self.btn_save.clicked.connect(self.save_to_file)
        self.btn_reset.clicked.connect(self._reset_all)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_reset)
        bar.addStretch()
        root.addLayout(bar)

        tip = QLabel(
            "默认每个学生的被点概率为 1/44（约 2.27%）。\n"
            "设置倍率 x 后，该学生被点到的概率约为 x × (1/44)。\n"
            "倍率 0 表示不会被点到；倍率 1.0 为默认值。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        root.addWidget(tip)

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
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.inner = QWidget()
        self.inner.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.inner)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.grid.setContentsMargins(0, 4, 0, 4)

        scroll.setWidget(self.inner)
        root.addWidget(scroll, 1)

    def refresh_students(self):
        cur_values = {n: s.value() for n, s in self.spins.items()}

        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.spins = {}
        self.prob_labels = {}

        students = [s for s in self.get_students() if not is_empty_student(s)]
        if not students:
            students = list(DEFAULT_STUDENT_NAMES)

        for i, name in enumerate(students):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("QLabel { color: #37474f; font-size: 12px; }")

            spin = QDoubleSpinBox()
            spin.setRange(0.0, MAX_PICK_WEIGHT)
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setFixedWidth(120)
            spin.setValue(cur_values.get(name, DEFAULT_PICK_WEIGHT))
            spin.setStyleSheet("""
                QDoubleSpinBox {
                    padding: 3px 6px; border: 1px solid #cfd8dc;
                    border-radius: 4px; background: #ffffff; font-size: 12px;
                }
            """)
            spin.valueChanged.connect(self._on_spin_changed)

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

        self._refresh_all_probs()

    def _on_spin_changed(self):
        self._refresh_all_probs()
        if self.on_changed:
            self.on_changed()

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
        if self.on_changed:
            self.on_changed()
        self.set_status("已重置为默认 1.0")

    def load_from_file(self):
        path = os.path.join(self.get_archive_dir(), FILE_PICK_WEIGHTS)
        if not os.path.exists(path):
            self._reset_all()
            self.set_status("7.dat 不存在，使用默认空配置")
            return
        try:
            text = load_encrypted(path, salt="pick")
        except Exception as e:
            QMessageBox.critical(
                self, "解密失败",
                "无法解密该文件：\n%s\n\n"
                "可能原因：加密种子不一致 / 文件已损坏。" % e
            )
            return

        for spin in self.spins.values():
            spin.blockSignals(True)
            spin.setValue(DEFAULT_PICK_WEIGHT)
            spin.blockSignals(False)

        loaded_count = 0
        if text:
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
                if name in self.spins:
                    self.spins[name].blockSignals(True)
                    self.spins[name].setValue(w)
                    self.spins[name].blockSignals(False)
                    loaded_count += 1

        self._refresh_all_probs()
        if self.on_changed:
            self.on_changed()
        self.set_status("已从 7.dat 读取 %d 条权重" % loaded_count)

    def save_to_file(self):
        path = os.path.join(self.get_archive_dir(), FILE_PICK_WEIGHTS)
        weights_dict = {n: s.value() for n, s in self.spins.items()}
        raw = build_pick_weights_string(weights_dict)

        try:
            save_encrypted(path, raw, salt="pick")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return

        non_default = len([1 for n, s in self.spins.items()
                           if abs(s.value() - DEFAULT_PICK_WEIGHT) > 1e-9])
        self.set_status("已保存到 7.dat（%d 条非默认权重）" % non_default)

    def get_weights_dict(self):
        return {n: s.value() for n, s in self.spins.items()}


# ============================================================
#  代码输出台
# ============================================================
class CodeOutputTab(QWidget):
    def __init__(self, get_desk_values, get_pick_weights,
                 apply_desk_values, apply_pick_weights, set_status):
        super().__init__()
        self.get_desk_values = get_desk_values
        self.get_pick_weights = get_pick_weights
        self.apply_desk_values = apply_desk_values
        self.apply_pick_weights = apply_pick_weights
        self.set_status = set_status

        self._build_ui()
        # 注意：初始化时暂不调用 refresh_output()
        # 因为外部 lambda 依赖的 desk_tab / pick_tab 可能尚未创建。
        # 由主窗口在全部 Tab 都创建好后再统一调用。

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        tip = QLabel(
            "把当前编辑结果实时输出为「内置存档」可用的 Python 代码片段。\n"
            "直接把下面两行复制粘贴到主程序的 _BUILTIN_ARCHIVE_JSON 里即可。\n"
            "也可以把别人的代码粘回下方输入区，点「从代码导入」反向填充编辑界面。"
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        root.addWidget(tip)

        splitter = QSplitter(Qt.Vertical)

        # ---------- 上半：输出区 ----------
        out_group = QGroupBox("代码输出（实时同步）")
        out_group.setStyleSheet(QSS_GROUPBOX)
        out_layout = QVBoxLayout(out_group)
        out_layout.setContentsMargins(12, 12, 12, 12)

        self.out_edit = QTextEdit()
        self.out_edit.setFont(QFont("Consolas", 11))
        self.out_edit.setStyleSheet("""
            QTextEdit {
                background: #fafafa; border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 8px;
                color: #263238;
            }
        """)
        out_layout.addWidget(self.out_edit)

        out_btns = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄  刷新输出")
        self.btn_copy_all = QPushButton("📋  复制全部")
        self.btn_copy_desk = QPushButton("📋  仅复制 desk_prefs")
        self.btn_copy_pick = QPushButton("📋  仅复制 pick_weights")

        self.btn_refresh.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_copy_all.setStyleSheet(QSS_BTN_COPY)
        self.btn_copy_desk.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_copy_pick.setStyleSheet(QSS_BTN_NORMAL)

        for b in (self.btn_refresh, self.btn_copy_all,
                  self.btn_copy_desk, self.btn_copy_pick):
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)

        self.btn_refresh.clicked.connect(self.refresh_output)
        self.btn_copy_all.clicked.connect(self._copy_all)
        self.btn_copy_desk.clicked.connect(self._copy_desk)
        self.btn_copy_pick.clicked.connect(self._copy_pick)

        out_btns.addWidget(self.btn_refresh)
        out_btns.addWidget(self.btn_copy_all)
        out_btns.addWidget(self.btn_copy_desk)
        out_btns.addWidget(self.btn_copy_pick)
        out_btns.addStretch()
        out_layout.addLayout(out_btns)

        splitter.addWidget(out_group)

        # ---------- 下半：输入区 ----------
        in_group = QGroupBox("代码导入（粘贴代码片段后点击导入）")
        in_group.setStyleSheet(QSS_GROUPBOX)
        in_layout = QVBoxLayout(in_group)
        in_layout.setContentsMargins(12, 12, 12, 12)

        self.in_edit = QTextEdit()
        self.in_edit.setFont(QFont("Consolas", 11))
        self.in_edit.setPlaceholderText(
            '把类似下面这样的代码整段贴进来：\n'
            '"desk_prefs": "\\n80\\n0\\n学生01\\n学生05",\n'
            '"pick_weights": "学生01,2.0\\n学生05,0.5",'
        )
        self.in_edit.setStyleSheet("""
            QTextEdit {
                background: #fafafa; border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 8px;
                color: #263238;
            }
        """)
        in_layout.addWidget(self.in_edit)

        in_btns = QHBoxLayout()
        self.btn_import = QPushButton("⬇️  从代码导入到编辑界面")
        self.btn_clear = QPushButton("清空输入区")
        self.btn_import.setStyleSheet(QSS_BTN)
        self.btn_clear.setStyleSheet(QSS_BTN_NORMAL)
        for b in (self.btn_import, self.btn_clear):
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_import.clicked.connect(self._import_from_text)
        self.btn_clear.clicked.connect(lambda: self.in_edit.clear())
        in_btns.addWidget(self.btn_import)
        in_btns.addWidget(self.btn_clear)
        in_btns.addStretch()
        in_layout.addLayout(in_btns)

        splitter.addWidget(in_group)

        splitter.setSizes([300, 260])
        root.addWidget(splitter, 1)

    def refresh_output(self):
        try:
            preferred, probability, front_prob, deskmates = self.get_desk_values()
            weights = self.get_pick_weights()
        except AttributeError:
            # 外部 Tab 尚未就绪，直接返回
            return

        desk_raw = build_desk_prefs_string(
            preferred, probability, front_prob, deskmates
        )
        pick_raw = build_pick_weights_string(weights)

        desk_literal = python_literal_from_lines(desk_raw)
        pick_literal = python_literal_from_lines(pick_raw)

        lines = []
        lines.append('"desk_prefs": "%s",' % desk_literal)
        lines.append('"pick_weights": "%s",' % pick_literal)

        text = "\n".join(lines)
        self.out_edit.blockSignals(True)
        self.out_edit.setPlainText(text)
        self.out_edit.blockSignals(False)

    def _copy_to_clipboard(self, text, msg):
        cb = QGuiApplication.clipboard()
        cb.setText(text)
        self.set_status(msg)

    def _copy_all(self):
        self._copy_to_clipboard(self.out_edit.toPlainText(),
                                "已复制全部代码")

    def _copy_desk(self):
        preferred, probability, front_prob, deskmates = self.get_desk_values()
        desk_raw = build_desk_prefs_string(
            preferred, probability, front_prob, deskmates
        )
        desk_literal = python_literal_from_lines(desk_raw)
        line = '"desk_prefs": "%s",' % desk_literal
        self._copy_to_clipboard(line, "已复制 desk_prefs 代码")

    def _copy_pick(self):
        weights = self.get_pick_weights()
        pick_raw = build_pick_weights_string(weights)
        pick_literal = python_literal_from_lines(pick_raw)
        line = '"pick_weights": "%s",' % pick_literal
        self._copy_to_clipboard(line, "已复制 pick_weights 代码")

    def _import_from_text(self):
        text = self.in_edit.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "提示", "输入区为空。")
            return

        m = re.search(
            r'"desk_prefs"\s*:\s*"(.*?)"\s*[,}]',
            text, re.DOTALL
        )
        if m:
            raw = m.group(1)
            preferred, prob, front, deskmates = parse_desk_prefs_from_literal(raw)
            self.apply_desk_values(preferred, prob, front, deskmates)

        m2 = re.search(
            r'"pick_weights"\s*:\s*"(.*?)"\s*[,}]',
            text, re.DOTALL
        )
        if m2:
            raw = m2.group(1)
            weights = parse_pick_weights_from_literal(raw)
            self.apply_pick_weights(weights)

        self.refresh_output()
        self.set_status("已从代码导入到编辑界面")


# ============================================================
#  主窗口
# ============================================================
class ArchiveEditor(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("存档解密编辑器 · 含代码输出台")
        self.setMinimumSize(820, 760)

        self.archive_dir = resolve_archive_dir()
        self.students = []

        self._build_ui()
        self._load_students()
        # 学生名单加载后刷新两个编辑 Tab 的下拉框
        self.desk_tab.refresh_students()
        self.pick_tab.refresh_students()
        # 再读取存档
        self.desk_tab.load_from_file()
        self.pick_tab.load_from_file()
        # 最后统一生成一次代码输出
        self.code_tab.refresh_output()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet("background-color: #f5f7fa;")

        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        # ---------- 顶部：存档目录 ----------
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)

        dir_label = QLabel("存档目录：")
        dir_label.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        dir_row.addWidget(dir_label)

        self.dir_edit = QLineEdit(self.archive_dir)
        self.dir_edit.setFont(QFont("Microsoft YaHei", 10))
        self.dir_edit.setStyleSheet(
            "QLineEdit { padding: 5px 8px; border: 1px solid #cfd8dc;"
            " border-radius: 4px; background: #ffffff; }"
        )
        self.dir_edit.editingFinished.connect(self._on_dir_changed)
        dir_row.addWidget(self.dir_edit, 1)

        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.clicked.connect(self._on_browse)
        dir_row.addWidget(self.btn_browse)

        self.btn_reload = QPushButton("重新载入")
        self.btn_reload.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._reload_all)
        dir_row.addWidget(self.btn_reload)

        root.addLayout(dir_row)

        # ---------- 标签页 ----------
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cfd8dc; border-radius: 6px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #eceff1; color: #37474f;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #ffffff; color: #1976d2;
            }
        """)

        # ★ 关键：先创建 desk_tab 和 pick_tab，再创建 code_tab
        self.desk_tab = DeskPrefsTab(
            get_archive_dir=lambda: self.archive_dir,
            get_students=lambda: self.students,
            set_status=self._set_status,
            on_changed=self._on_edit_changed,
        )
        self.pick_tab = PickWeightsTab(
            get_archive_dir=lambda: self.archive_dir,
            get_students=lambda: self.students,
            set_status=self._set_status,
            on_changed=self._on_edit_changed,
        )
        self.code_tab = CodeOutputTab(
            get_desk_values=lambda: self.desk_tab.get_values(),
            get_pick_weights=lambda: self.pick_tab.get_weights_dict(),
            apply_desk_values=self._apply_desk_values_to_tab,
            apply_pick_weights=self._apply_pick_weights_to_tab,
            set_status=self._set_status,
        )

        self.tabs.addTab(self.desk_tab, "偏好配置（2.dat）")
        self.tabs.addTab(self.pick_tab, "点名权重（7.dat）")
        self.tabs.addTab(self.code_tab, "代码输出台")

        root.addWidget(self.tabs, 1)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    # --------------------------------------------------------
    def _on_edit_changed(self):
        if hasattr(self, "code_tab"):
            self.code_tab.refresh_output()

    def _on_tab_changed(self, idx):
        if self.tabs.widget(idx) is self.code_tab:
            self.code_tab.refresh_output()

    def _apply_desk_values_to_tab(self, preferred, prob, front, deskmates):
        self.desk_tab._apply_values(preferred, prob, front, deskmates)

    def _apply_pick_weights_to_tab(self, weights):
        for name, spin in self.pick_tab.spins.items():
            spin.blockSignals(True)
            if name in weights:
                spin.setValue(weights[name])
            else:
                spin.setValue(DEFAULT_PICK_WEIGHT)
            spin.blockSignals(False)
        self.pick_tab._refresh_all_probs()

    # --------------------------------------------------------
    def _load_students(self):
        path = os.path.join(self.archive_dir, FILE_STUDENTS)
        names = []
        if os.path.exists(path):
            try:
                text = load_encrypted(path, salt="students")
                if text:
                    names = [ln.strip() for ln in text.splitlines() if ln.strip()]
            except Exception:
                names = []

        if not names:
            names = list(DEFAULT_STUDENT_NAMES)
        self.students = names

    def _reload_all(self):
        self._load_students()
        self.desk_tab.refresh_students()
        self.pick_tab.refresh_students()
        self.desk_tab.load_from_file()
        self.pick_tab.load_from_file()
        self.code_tab.refresh_output()

    def _on_dir_changed(self):
        new_dir = self.dir_edit.text().strip()
        if not new_dir:
            return
        if not os.path.isdir(new_dir):
            QMessageBox.warning(self, "提示", "目录不存在：\n%s" % new_dir)
            return
        self.archive_dir = new_dir
        self._reload_all()

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择存档目录", self.archive_dir
        )
        if d:
            self.dir_edit.setText(d)
            self.archive_dir = d
            self._reload_all()

    def _set_status(self, msg):
        self.statusBar().showMessage(msg, 5000)


# ============================================================
#  入口
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    win = ArchiveEditor()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
