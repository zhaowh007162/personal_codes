# -*- coding: utf-8 -*-
"""
多功能应用（加密存档 + 内置存档 + 设置 + 导入导出 + 随机点名 + 权重）
============================================================
窗口策略：全屏铺满可用区域（不挡任务栏），尺寸固定，无法拖动 / 缩放。
管理员解锁：Alt+Z → 松开 → 点讲台 → 松开 → Alt+X → 弹口令框
           ★ 必须作者按钮累计点击 6 次
概率菜单解锁：
    ★ 至少点击过一次「班级名单」后
    ★ 按 Ctrl+M
    ★ 3 秒内点击「导入座位表」→ 弹口令框（独立密码 123456）

教室布局：8 列 × 5 排 + 第 6 排 4 个座位（共 44 个座位）
排座规则：上一次坐在最后三排的同学，这次不能再坐最后三排（最高优先级）
         ★ 例外：第 4 排第 3/4/5/6 列不算「后排」
         ★ 空位学生优先安排到后排，不参与排座、点名、后排轮换
         ★ 关注学生可设「目标坐前排概率」，触发时强制到前 3 排
偏好同桌：1 名「关注学生」 + 最多 14 名「同桌」，按概率配对
非意愿同桌（暗箱，最多 3 人）：永远不能与关注学生成为同桌
         ★ 优先级高于配对概率（暗改）
         ★ 严格遵守最高指令：不得破坏后排轮换
         ★ 循环拆分：只要关注学生仍与任一非意愿同桌同桌，就继续拆
随机点名：支持点名频率，实际被点概率 ≈ x × (1/44)

存档目录（分开放置，避免一处被全删）
    主存档：D:/JiXiu  → 1/2/3/4/5/6/7/8/9/10/11/12.dat
    备  份：D:/Program Files/MMY → chart_bak.dat / recycle_bak.dat / seat_bak.dat
             logs/  ← 每次导出座位表自动写一份明文 txt

加密方案：
    · AES-256-GCM  · PBKDF2-HMAC-SHA256(600000) → 主密钥
    · 每文件独立子密钥 HKDF-SHA256(info="seat_file:<salt>")
    · 随机 12 字节 nonce，base64(nonce ‖ ct)
    · 需要 cryptography：pip install cryptography

Windows 首次运行验证（唯一联网检查点）：
    · 首次密码的 SHA256 哈希值硬编码（代码里不出现明文）
    · 加密后写入注册表 tp2 / 验证通过写 tp3 / 一次机会写 tp4
    · 已锁定 / 密码错误 / 取消 → 静默退出，无任何弹窗
    · 输密码时检查联网状态，断网直接锁定
    · macOS / Linux 完全跳过首次验证与网络检测

启动行为：
    · 首次运行（设备第一次输密码）：主界面正常显示，红×真正关闭程序
    · 后续启动：主界面隐藏；托盘图标 + 置顶悬浮窗常驻
    · 点击悬浮窗 → 弹出小面板（随机点名 / 排座主界面），再点关闭
    · 面板与悬浮窗绑定，一起移动，受可用区域限制
    · 托盘右键 → 显示主界面 / 退出
    · 已运行实例：第二次启动会唤起第一个实例的主界面并静默退出
    · 托盘不可用时（如 GNOME），主界面仍可隐藏，靠悬浮窗恢复

开机自启原理（跨平台）：
    · 总开关：autostart_pref（存于 12.dat，加密），默认 "true"（开启）
    · Windows：写 HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
               键名 SeatApp_AutoStart，值为程序完整路径
    · macOS：写 ~/Library/LaunchAgents/com.jixiu.seatapp.plist
    · Linux：写 ~/.config/autostart/seatapp.desktop
    · 首次运行不写；后续启动根据 autostart_pref 幂等写入
    · 管理员菜单可勾选/取消「开机自动启动」

暗箱开关（仅 Windows，明文，完全静默）：
    · HKCU\Software\SeatCrypto\JiXiu\am
    · HKCU\Software\SeatCrypto\JiXiu\pc
    · 程序启动时自动确保存在，默认 "false"
    · 只有手动改为 "true" 时对应菜单才能打开
    · 未启用时静默 return，不弹任何提示
    · macOS / Linux 直接放行

单实例：
    · 通过 D:/JiXiu/.app.lock 文件锁防止多开
    · 通过 QLocalServer / QLocalSocket 实现进程间唤起
"""
import os
import re
import sys
import socket
import hashlib
import base64
import zlib
import json
import random
import secrets
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidTag
except ImportError:
    _err_msg = (
        "\n============================================================\n"
        "  缺少密码学库 cryptography\n"
        "  请运行：pip install cryptography\n"
        "============================================================\n"
    )
    _ok = False
    try:
        if sys.stderr is not None:
            sys.stderr.write(_err_msg)
            _ok = True
    except Exception:
        pass
    if not _ok:
        try:
            if (sys.stderr is not None and hasattr(sys.stderr, "buffer")
                    and sys.stderr.buffer is not None):
                sys.stderr.buffer.write(_err_msg.encode("utf-8", "replace"))
                _ok = True
        except Exception:
            pass
    if not _ok:
        try:
            import tempfile
            _log = os.path.join(tempfile.gettempdir(), "seat_app_error.log")
            with open(_log, "w", encoding="utf-8") as f:
                f.write(_err_msg)
        except Exception:
            pass
    sys.exit(1)


ADMIN_SHORTCUT = "Alt+Z"
ADMIN_UNLOCK_TIMEOUT_MS = 3000

MASTER_PASSPHRASE = b"SeatCrypto_v2_Master_@2024#JiXiu!$Secure^Pass%word&2026"
MASTER_SALT = b"SeatCrypto_v2_master_salt_2024_"
PBKDF2_ITERATIONS = 600_000

REGISTRY_SUBKEY = r"Software\SeatCrypto\JiXiu"
REGISTRY_VALUE_NAME = "tp"

MAX_DESK_CHOICES = 14
MAX_NON_DESIRED = 3
BACK_ROWS = 3
BACK_EXEMPT_SEATS = {(3, 2), (3, 3), (3, 4), (3, 5)}
EMPTY_STUDENT_MARKERS = ("(空)", "（空）")
DESK_COOLDOWN_TIMES = 3
DESIRED_COOLDOWN_TIMES = 1

FILE_PASSWORD = "1.dat"
FILE_DESK_PREFS = "2.dat"
FILE_SEATING = "3.dat"
FILE_PICK_MENU_PWD = "4.dat"
FILE_UI = "5.dat"
FILE_TEACHER_PASSWORD = "6.dat"
FILE_STUDENTS = "7.dat"
FILE_PICK_WEIGHTS = "8.dat"
FILE_LAST_BACK = "9.dat"
FILE_RECENT_DESKMATES = "10.dat"
FILE_NON_DESIRED = "11.dat"
FILE_AUTOSTART_PREF = "12.dat"

FILE_LAST_BACK_BAK = "seat_bak.dat"
FILE_SEATING_BAK = "chart_bak.dat"
FILE_RECENT_DESKMATES_BAK = "recycle_bak.dat"

RECENT_EMPTY_MARKER = "__EMPTY__"

UI_DEFAULT_WIDTH = 560
UI_DEFAULT_HEIGHT = 720
DEFAULT_PICK_WEIGHT = 1.0
MAX_PICK_WEIGHT = 20.0

MIN_PICK_SELECTED = 4

SEAT_WIDTH = 96
SEAT_HEIGHT = 52
PAIR_GAP = 2
PAIR_SPACING = 24
ROW_SPACING = 10
LABEL_WIDTH = 52
LABEL_GAP = 8

NETWORK_TARGETS = [
    ("114.114.114.114", 53),
    ("223.5.5.5", 53),
]
NETWORK_TIMEOUT_STARTUP = 2.0
NETWORK_TIMEOUT_RUNTIME = 1.0

# ★ 默认密码「123456」的字符码形式
_DEFAULT_PWD_BYTES = bytes([0x31, 0x32, 0x33, 0x34, 0x35, 0x36])
_DEFAULT_PWD = _DEFAULT_PWD_BYTES.decode("ascii")

# ★ 首次运行密码「123456」的字节码 + SHA256
_FIRST_RUN_PASSWORD_BYTES = bytes([0x31, 0x32, 0x33, 0x34, 0x35, 0x36])
_FIRST_RUN_HASH = hashlib.sha256(_FIRST_RUN_PASSWORD_BYTES).hexdigest()

# ★ 概率修改菜单密码「123456」的字节码
_PICK_MENU_PWD_BYTES = bytes([0x31, 0x32, 0x33, 0x34, 0x35, 0x36])
_PICK_MENU_PWD_DEFAULT = _PICK_MENU_PWD_BYTES.decode("ascii")

# ★ 作者标识
AUTHOR_NAME = "007162"

REGISTRY_PICK_MENU_PWD_NAME = "pick_pwd"
REGISTRY_ADMIN_ENABLED_NAME = "am"
REGISTRY_PICK_MENU_ENABLED_NAME = "pc"

REGISTRY_RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_RUN_VALUE_NAME = "SeatApp_AutoStart"

AUTOSTART_MACOS_LABEL = "com.jixiu.seatapp"
AUTOSTART_LINUX_FILENAME = "seatapp.desktop"

STUDENT_NAMES = [
    "同学01", "同学02", "同学03", "同学04", "同学05",
    "同学06", "同学07", "同学08", "同学09", "同学10",
    "同学11", "同学12", "同学13", "同学14", "同学15",
    "同学16", "同学17", "同学18", "同学19", "同学20",
    "同学21", "同学22", "同学23", "同学24", "同学25",
    "同学26", "同学27", "同学28", "同学29", "同学30",
    "同学31", "同学32", "同学33", "同学34", "同学35",
    "同学36", "同学37", "同学38", "同学39", "同学40",
    "同学41", "同学42", "同学43", "同学44",
]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _check_network(timeout: float = NETWORK_TIMEOUT_RUNTIME) -> bool:
    if not _is_windows():
        return True
    for host, port in NETWORK_TARGETS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            continue
    return False


def _hard_exit(code: int = 1):
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception:
        pass
    try:
        os._exit(code)
    except Exception:
        sys.exit(code)


_BUILTIN_ARCHIVE_JSON = json.dumps(
    {
        "password": _DEFAULT_PWD,
        "teacher_password": "",
        "desk_prefs": "同学23\n80\n75\n同学03\n同学07\n同学08\n同学09\n同学10\n同学11\n同学13\n同学15\n同学17\n同学19\n同学36\n同学41\n同学29\n同学12",
        "last_seating": "",
        "pick_weights": "同学07,0.9\n同学08,0.9\n同学09,0.9\n同学10,0.9\n同学11,0.9\n同学12,0.9\n同学13,0.9\n同学15,0.9\n同学18,2.0\n同学19,0.9\n同学23,0.1\n同学29,0.9\n同学36,0.9\n同学41,0.9",
        "non_desired_list": "同学05\n同学20\n同学44",
        "autostart_pref": "true",
    },
    ensure_ascii=False,
)

BUILTIN_ARCHIVE_B64 = base64.b64encode(
    zlib.compress(_BUILTIN_ARCHIVE_JSON.encode("utf-8"))
).decode("ascii")

COLS = 8
ROWS_NORMAL = 5
LAST_ROW_SEATS = 4


def is_empty_student(name) -> bool:
    if not name:
        return False
    return name.strip() in EMPTY_STUDENT_MARKERS


def _probe_writable(path: str) -> bool:
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".writetest")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return True
    except Exception:
        return False


def _safe_abspath(p):
    try:
        if not p:
            return None
        return os.path.abspath(p)
    except Exception:
        return None


def _collect_archive_candidates():
    candidates = []
    if _is_windows():
        candidates.append("D:/JiXiu")
    try:
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            candidates.append(os.path.join(home, ".JiXiu"))
    except Exception:
        pass
    exe_path = _safe_abspath(sys.argv[0]) if sys.argv else None
    if exe_path:
        candidates.append(os.path.join(os.path.dirname(exe_path), "JiXiu"))
    try:
        candidates.append(os.path.join(os.getcwd(), "JiXiu"))
    except Exception:
        pass
    try:
        import tempfile
        candidates.append(os.path.join(tempfile.gettempdir(), "JiXiu"))
    except Exception:
        pass
    return candidates


def _collect_backup_candidates():
    candidates = []
    if _is_windows():
        candidates.append("D:/Program Files/MMY")
    try:
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            candidates.append(os.path.join(home, ".MMY"))
    except Exception:
        pass
    exe_path = _safe_abspath(sys.argv[0]) if sys.argv else None
    if exe_path:
        candidates.append(os.path.join(
            os.path.dirname(exe_path), "Program Files", "MMY"))
    try:
        candidates.append(os.path.join(os.getcwd(), "Program Files", "MMY"))
    except Exception:
        pass
    try:
        import tempfile
        candidates.append(os.path.join(tempfile.gettempdir(), "MMY"))
    except Exception:
        pass
    return candidates


def _get_archive_dir():
    candidates = _collect_archive_candidates()
    for path in candidates:
        if _probe_writable(path):
            return path
    return candidates[0] if candidates else "."


def _get_backup_dir():
    candidates = _collect_backup_candidates()
    for path in candidates:
        if _probe_writable(path):
            return path
    return candidates[0] if candidates else "."


def get_safe_window_size(desired_w, desired_h, widget=None):
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return desired_w, desired_h
        screen = None
        target = widget
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
BACKUP_DIR = _get_backup_dir()
LOGS_DIR = os.path.join(BACKUP_DIR, "logs")

try:
    os.makedirs(LOGS_DIR, exist_ok=True)
except Exception:
    pass

PASSWORD_FILE = os.path.join(ARCHIVE_DIR, FILE_PASSWORD)
DESK_PREFS_FILE = os.path.join(ARCHIVE_DIR, FILE_DESK_PREFS)
SEATING_FILE = os.path.join(ARCHIVE_DIR, FILE_SEATING)
PICK_MENU_PWD_FILE = os.path.join(ARCHIVE_DIR, FILE_PICK_MENU_PWD)
UI_FILE = os.path.join(ARCHIVE_DIR, FILE_UI)
TEACHER_PASSWORD_FILE = os.path.join(ARCHIVE_DIR, FILE_TEACHER_PASSWORD)
STUDENTS_FILE = os.path.join(ARCHIVE_DIR, FILE_STUDENTS)
PICK_WEIGHTS_FILE = os.path.join(ARCHIVE_DIR, FILE_PICK_WEIGHTS)
LAST_BACK_FILE = os.path.join(ARCHIVE_DIR, FILE_LAST_BACK)
RECENT_DESKMATES_FILE = os.path.join(ARCHIVE_DIR, FILE_RECENT_DESKMATES)
NON_DESIRED_FILE = os.path.join(ARCHIVE_DIR, FILE_NON_DESIRED)
AUTOSTART_PREF_FILE = os.path.join(ARCHIVE_DIR, FILE_AUTOSTART_PREF)
SEATING_BAK_FILE = os.path.join(BACKUP_DIR, FILE_SEATING_BAK)
RECENT_DESKMATES_BAK_FILE = os.path.join(BACKUP_DIR, FILE_RECENT_DESKMATES_BAK)
LAST_BACK_BAK_FILE = os.path.join(BACKUP_DIR, FILE_LAST_BACK_BAK)


SINGLE_INSTANCE_LOCK_FILE = os.path.join(ARCHIVE_DIR, ".app.lock")
SINGLE_INSTANCE_SERVER_NAME = "SeatApp_SingleInstance_v1"
_SINGLE_INSTANCE_LOCK_HANDLE = None
_SINGLE_INSTANCE_SERVER = None


def _acquire_single_instance_lock() -> bool:
    global _SINGLE_INSTANCE_LOCK_HANDLE
    if _SINGLE_INSTANCE_LOCK_HANDLE is not None:
        return True
    try:
        f = open(SINGLE_INSTANCE_LOCK_FILE, "a+")
    except Exception:
        return True
    try:
        if _is_windows():
            import msvcrt
            f.seek(0, 2)
            if f.tell() < 1:
                f.write("X")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _SINGLE_INSTANCE_LOCK_HANDLE = f
        return True
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return False


from PyQt5.QtCore import Qt, QTimer, QRect, QSize, QPoint, QEvent
from PyQt5.QtGui import (
    QFont, QFontDatabase, QKeySequence, QFontMetrics,
    QIcon, QPixmap, QPainter, QColor, QBrush, QPen,
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QDialog,
    QDialogButtonBox, QFileDialog, QLineEdit, QSlider,
    QComboBox, QInputDialog, QScrollArea, QShortcut, QGroupBox,
    QTextEdit, QDoubleSpinBox, QLayout, QSizePolicy, QListWidget,
    QCheckBox,
    QSystemTrayIcon, QMenu, QAction,
)

try:
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    _HAS_QTNETWORK = True
except Exception:
    _HAS_QTNETWORK = False


def _try_notify_existing_instance(max_retries: int = 3,
                                  retry_delay_ms: int = 150) -> bool:
    if not _HAS_QTNETWORK:
        return False
    for i in range(max_retries):
        try:
            sock = QLocalSocket()
            sock.connectToServer(SINGLE_INSTANCE_SERVER_NAME)
            if sock.waitForConnected(400):
                sock.write(b"SHOW_MAIN\n")
                sock.flush()
                sock.waitForBytesWritten(400)
                try:
                    sock.disconnectFromServer()
                except Exception:
                    pass
                return True
        except Exception:
            pass
        if i < max_retries - 1:
            try:
                import time
                time.sleep(retry_delay_ms / 1000.0)
            except Exception:
                pass
    return False


def _start_single_instance_server(on_message_callback) -> bool:
    global _SINGLE_INSTANCE_SERVER
    if not _HAS_QTNETWORK:
        return False
    if _SINGLE_INSTANCE_SERVER is not None:
        return True
    try:
        try:
            QLocalServer.removeServer(SINGLE_INSTANCE_SERVER_NAME)
        except Exception:
            pass
        server = QLocalServer()
        if not server.listen(SINGLE_INSTANCE_SERVER_NAME):
            return False

        def _on_new_connection():
            try:
                conn = server.nextPendingConnection()
                if conn is None:
                    return

                def _try_read():
                    try:
                        if (conn.bytesAvailable() > 0
                                or conn.waitForReadyRead(80)):
                            data = bytes(conn.readAll()).decode(
                                "utf-8", "replace"
                            )
                            if "SHOW_MAIN" in data:
                                try:
                                    on_message_callback()
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    finally:
                        try:
                            conn.disconnectFromServer()
                        except Exception:
                            pass

                QTimer.singleShot(80, _try_read)
            except Exception:
                pass

        server.newConnection.connect(_on_new_connection)
        _SINGLE_INSTANCE_SERVER = server
        return True
    except Exception:
        return False


_MASTER_KEY_CACHE = None
_FILE_KEYS_CACHE = {}


def _get_master_key():
    global _MASTER_KEY_CACHE
    if _MASTER_KEY_CACHE is not None:
        return _MASTER_KEY_CACHE
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=MASTER_SALT,
        iterations=PBKDF2_ITERATIONS,
    )
    _MASTER_KEY_CACHE = kdf.derive(MASTER_PASSPHRASE)
    return _MASTER_KEY_CACHE


def _get_file_key(salt: str) -> bytes:
    if salt in _FILE_KEYS_CACHE:
        return _FILE_KEYS_CACHE[salt]
    master = _get_master_key()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"seat_file:" + salt.encode("utf-8"),
    )
    key = hkdf.derive(master)
    _FILE_KEYS_CACHE[salt] = key
    return key


def encrypt_text(text: str, salt: str = "") -> str:
    key = _get_file_key(salt)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aesgcm.encrypt(nonce, text.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_text(b64_text: str, salt: str = "") -> str:
    key = _get_file_key(salt)
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
        raise ValueError("数据无法读取，可能是文件已损坏。")
    except Exception:
        raise ValueError("数据无法读取，可能是文件已损坏。")
    try:
        return pt.decode("utf-8")
    except Exception:
        raise ValueError("数据无法读取，可能是文件已损坏。")


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
        raise ValueError("数据无法读取，可能是文件已损坏。")


# ============================================================
#  ★ 开机自启（跨平台）
# ============================================================
def _get_exe_command_parts():
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), None
    exe = sys.executable or "/usr/bin/python3"
    if _is_windows() and exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            exe = cand
    return exe, os.path.abspath(sys.argv[0])


def _is_autostart_enabled_windows() -> bool:
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_RUN_SUBKEY, 0,
                winreg.KEY_READ,
            )
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(key, REGISTRY_RUN_VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _is_autostart_enabled_macos() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home:
            return False
        return os.path.exists(os.path.join(
            home, "Library", "LaunchAgents",
            AUTOSTART_MACOS_LABEL + ".plist"
        ))
    except Exception:
        return False


def _is_autostart_enabled_linux() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home:
            return False
        return os.path.exists(os.path.join(
            home, ".config", "autostart", AUTOSTART_LINUX_FILENAME
        ))
    except Exception:
        return False


def _is_autostart_enabled() -> bool:
    if _is_windows():
        return _is_autostart_enabled_windows()
    if _is_macos():
        return _is_autostart_enabled_macos()
    if _is_linux():
        return _is_autostart_enabled_linux()
    return False


def _enable_autostart_windows() -> bool:
    try:
        import winreg
        exe, script = _get_exe_command_parts()
        cmd = ('"%s"' % exe) if script is None else ('"%s" "%s"' % (exe, script))
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_RUN_SUBKEY, 0,
            winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _enable_autostart_macos() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home or not os.path.isdir(home):
            return False
        la_dir = os.path.join(home, "Library", "LaunchAgents")
        os.makedirs(la_dir, exist_ok=True)
        plist_path = os.path.join(la_dir, AUTOSTART_MACOS_LABEL + ".plist")
        exe, script = _get_exe_command_parts()
        args = [exe] if script is None else [exe, script]
        arg_xml = "\n".join(
            "        <string>%s</string>" % a.replace("&", "&amp;")
            for a in args
        )
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            '    <key>Label</key>\n'
            '    <string>%s</string>\n'
            '    <key>ProgramArguments</key>\n'
            '    <array>\n' + arg_xml + '\n    </array>\n'
            '    <key>RunAtLoad</key>\n'
            '    <true/>\n'
            '    <key>KeepAlive</key>\n'
            '    <false/>\n'
            '</dict>\n'
            '</plist>\n'
        ) % AUTOSTART_MACOS_LABEL
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def _enable_autostart_linux() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home or not os.path.isdir(home):
            return False
        autostart_dir = os.path.join(home, ".config", "autostart")
        os.makedirs(autostart_dir, exist_ok=True)
        desktop_path = os.path.join(autostart_dir, AUTOSTART_LINUX_FILENAME)
        exe, script = _get_exe_command_parts()
        exec_line = ('"%s"' % exe) if script is None else \
            ('"%s" "%s"' % (exe, script))
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=SeatApp\n"
            "Comment=点名排座\n"
            "Exec=%s\n"
            "X-GNOME-Autostart-enabled=true\n"
            "Hidden=false\n"
            "Terminal=false\n"
        ) % exec_line
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            os.chmod(desktop_path, 0o644)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _enable_autostart() -> bool:
    if _is_windows():
        return _enable_autostart_windows()
    if _is_macos():
        return _enable_autostart_macos()
    if _is_linux():
        return _enable_autostart_linux()
    return False


def _disable_autostart_windows() -> bool:
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_RUN_SUBKEY, 0,
                winreg.KEY_SET_VALUE,
            )
        except FileNotFoundError:
            return True
        try:
            try:
                winreg.DeleteValue(key, REGISTRY_RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _disable_autostart_macos() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home:
            return True
        plist_path = os.path.join(
            home, "Library", "LaunchAgents",
            AUTOSTART_MACOS_LABEL + ".plist"
        )
        if os.path.exists(plist_path):
            try:
                os.remove(plist_path)
            except Exception:
                return False
        return True
    except Exception:
        return False


def _disable_autostart_linux() -> bool:
    try:
        home = os.path.expanduser("~")
        if not home:
            return True
        desktop_path = os.path.join(
            home, ".config", "autostart", AUTOSTART_LINUX_FILENAME
        )
        if os.path.exists(desktop_path):
            try:
                os.remove(desktop_path)
            except Exception:
                return False
        return True
    except Exception:
        return False


def _disable_autostart() -> bool:
    if _is_windows():
        return _disable_autostart_windows()
    if _is_macos():
        return _disable_autostart_macos()
    if _is_linux():
        return _disable_autostart_linux()
    return False


# ============================================================
#  ★ 暗箱开关（仅 Windows，明文）
# ============================================================
def _check_admin_enabled() -> bool:
    if not _is_windows():
        return True
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return False
        try:
            val, _ = winreg.QueryValueEx(key, REGISTRY_ADMIN_ENABLED_NAME)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
        return str(val).strip().lower() == "true"
    except Exception:
        return False


def _check_pick_menu_enabled() -> bool:
    if not _is_windows():
        return True
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return False
        try:
            val, _ = winreg.QueryValueEx(key, REGISTRY_PICK_MENU_ENABLED_NAME)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
        return str(val).strip().lower() == "true"
    except Exception:
        return False


def _ensure_switches_in_registry():
    if not _is_windows():
        return
    try:
        import winreg
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            for name in (REGISTRY_ADMIN_ENABLED_NAME,
                         REGISTRY_PICK_MENU_ENABLED_NAME):
                try:
                    winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, "false")
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass


def _save_teacher_password_to_registry(pwd: str) -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        encrypted = encrypt_text(pwd, salt="teacher_registry")
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, encrypted
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _load_teacher_password_from_registry():
    if not _is_windows():
        return None
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return None
        try:
            encrypted, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
        except FileNotFoundError:
            return None
        finally:
            winreg.CloseKey(key)
        if not encrypted:
            return ""
        try:
            return decrypt_text(encrypted, salt="teacher_registry")
        except Exception:
            return ""
    except Exception:
        return None


def _delete_teacher_password_from_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0,
                winreg.KEY_SET_VALUE,
            )
        except FileNotFoundError:
            return True
        try:
            try:
                winreg.DeleteValue(key, REGISTRY_VALUE_NAME)
            except FileNotFoundError:
                pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _save_pick_menu_pwd_to_registry(pwd: str) -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        encrypted = encrypt_text(pwd, salt="pick_menu_registry")
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_PICK_MENU_PWD_NAME, 0, winreg.REG_SZ, encrypted
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _load_pick_menu_pwd_from_registry():
    if not _is_windows():
        return None
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return None
        try:
            encrypted, _ = winreg.QueryValueEx(key, REGISTRY_PICK_MENU_PWD_NAME)
        except FileNotFoundError:
            return None
        finally:
            winreg.CloseKey(key)
        if not encrypted:
            return ""
        try:
            return decrypt_text(encrypted, salt="pick_menu_registry")
        except Exception:
            return ""
    except Exception:
        return None


def _delete_pick_menu_pwd_from_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0,
                winreg.KEY_SET_VALUE,
            )
        except FileNotFoundError:
            return True
        try:
            try:
                winreg.DeleteValue(key, REGISTRY_PICK_MENU_PWD_NAME)
            except FileNotFoundError:
                pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


REGISTRY_FIRST_RUN_PWD = "tp2"
REGISTRY_FIRST_RUN_FLAG = "tp3"
REGISTRY_LOCKOUT_FLAG = "tp4"
REGISTRY_FIRST_RUN_FAIL = "tp_fail"

FIRST_RUN_MAX_ATTEMPTS = 1


def _save_first_run_password_to_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        encrypted = encrypt_text(_FIRST_RUN_HASH, salt="first_run")
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_FIRST_RUN_PWD, 0, winreg.REG_SZ, encrypted
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _load_first_run_password_from_registry():
    if not _is_windows():
        return None
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return None
        try:
            encrypted, _ = winreg.QueryValueEx(key, REGISTRY_FIRST_RUN_PWD)
        except FileNotFoundError:
            return None
        finally:
            winreg.CloseKey(key)
        if not encrypted:
            return ""
        try:
            return decrypt_text(encrypted, salt="first_run")
        except Exception:
            return None
    except Exception:
        return None


def _save_first_run_flag_to_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_FIRST_RUN_FLAG, 0, winreg.REG_SZ, "ok"
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _check_first_run_flag_in_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(key, REGISTRY_FIRST_RUN_FLAG)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _write_lockout_flag_to_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(key, REGISTRY_LOCKOUT_FLAG, 0, winreg.REG_SZ, "1")
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _check_lockout_flag_in_registry() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(key, REGISTRY_LOCKOUT_FLAG)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _save_first_run_fail_count_to_registry(count: int) -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_WRITE,
        )
        try:
            winreg.SetValueEx(
                key, REGISTRY_FIRST_RUN_FAIL, 0, winreg.REG_DWORD, int(count)
            )
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _load_first_run_fail_count_from_registry() -> int:
    if not _is_windows():
        return 0
    try:
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_SUBKEY, 0, winreg.KEY_READ,
            )
        except FileNotFoundError:
            return 0
        try:
            val, _ = winreg.QueryValueEx(key, REGISTRY_FIRST_RUN_FAIL)
            return int(val)
        except (FileNotFoundError, ValueError, TypeError):
            return 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        return 0


def extract_builtin_archive() -> dict:
    raw = zlib.decompress(base64.b64decode(BUILTIN_ARCHIVE_B64))
    return json.loads(raw.decode("utf-8"))


def ensure_archive_files():
    need_password = not os.path.exists(PASSWORD_FILE)
    need_desk = not os.path.exists(DESK_PREFS_FILE)
    need_teacher = not os.path.exists(TEACHER_PASSWORD_FILE)
    need_pick = not os.path.exists(PICK_WEIGHTS_FILE)
    need_pick_menu = not os.path.exists(PICK_MENU_PWD_FILE)
    need_non_desired = not os.path.exists(NON_DESIRED_FILE)
    need_autostart = not os.path.exists(AUTOSTART_PREF_FILE)
    if not (need_password or need_desk or need_teacher or need_pick
            or need_pick_menu or need_non_desired or need_autostart):
        return
    archive = extract_builtin_archive()
    if need_password:
        save_encrypted(PASSWORD_FILE,
                       archive.get("password", _DEFAULT_PWD), salt="password")
    if need_desk:
        save_encrypted(DESK_PREFS_FILE,
                       archive.get("desk_prefs", "\n80\n0"), salt="desk")
    if need_teacher:
        save_encrypted(TEACHER_PASSWORD_FILE,
                       archive.get("teacher_password", ""), salt="teacher")
    if need_pick:
        save_encrypted(PICK_WEIGHTS_FILE,
                       archive.get("pick_weights", ""), salt="pick")
    if need_pick_menu:
        init_data = {"password": _PICK_MENU_PWD_DEFAULT, "selected": []}
        save_encrypted(
            PICK_MENU_PWD_FILE,
            json.dumps(init_data, ensure_ascii=False),
            salt="pick_menu",
        )
    if need_non_desired:
        save_encrypted(NON_DESIRED_FILE,
                       archive.get("non_desired_list", ""),
                       salt="non_desired")
    if need_autostart:
        save_encrypted(AUTOSTART_PREF_FILE,
                       archive.get("autostart_pref", "true"),
                       salt="autostart_pref")


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
    parts = re.split(r"[　\t]+| {2,}", text)
    return [p.strip() for p in parts if p.strip()]


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


def _get_symbol_font(size=20, bold=True):
    preferred = [
        "Segoe UI Symbol",
        "Apple Symbols",
        "Symbola",
        "Noto Sans Symbols",
        "Noto Sans Symbols 2",
        "DejaVu Sans",
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
    return f


def _make_app_icon():
    try:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(QBrush(QColor(25, 118, 210)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, 60, 60)
        p.setPen(QColor(255, 255, 255))
        p.setFont(_get_symbol_font(24))
        p.drawText(pm.rect(), Qt.AlignCenter, "⚙")
        p.end()
        return QIcon(pm)
    except Exception:
        return QIcon()


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
QSS_BTN_ROSTER_RED = """
QPushButton {
    background-color: #e53935; color: #ffffff;
    border: none; border-radius: 8px;
    font-weight: bold;
}
QPushButton:hover  { background-color: #d32f2f; }
QPushButton:pressed{ background-color: #b71c1c; }
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


class FloatingPanel(QWidget):
    def __init__(self, main_window, floating, parent=None):
        super().__init__(parent)
        self._main = main_window
        self._floating = floating
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedWidth(156)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet("""
            QWidget#card {
                background-color: #263238;
                border: 1px solid #4fc3f7;
                border-radius: 10px;
            }
        """)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        btn_pick = QPushButton("随机点名")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.setMinimumHeight(36)
        btn_pick.setStyleSheet("""
            QPushButton {
                background-color: #7e57c2; color: #ffffff;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
            }
            QPushButton:hover   { background-color: #673ab7; }
            QPushButton:pressed { background-color: #512da8; }
        """)
        btn_pick.clicked.connect(self._on_pick)
        v.addWidget(btn_pick)

        btn_main = QPushButton("排座主界面")
        btn_main.setCursor(Qt.PointingHandCursor)
        btn_main.setMinimumHeight(36)
        btn_main.setStyleSheet("""
            QPushButton {
                background-color: #1976d2; color: #ffffff;
                border: none; border-radius: 6px;
                font-size: 13px; font-weight: bold;
            }
            QPushButton:hover   { background-color: #1565c0; }
            QPushButton:pressed { background-color: #0d47a1; }
        """)
        btn_main.clicked.connect(self._on_main)
        v.addWidget(btn_main)

    def _on_pick(self):
        self.hide()
        try:
            self._main.open_name_picker()
        except Exception:
            pass

    def _on_main(self):
        self.hide()
        try:
            self._main._show_main()
        except Exception:
            pass


FLOATING_SIZE = 52


class FloatingWindow(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main = main_window
        self._panel = None
        self._drag_pos = None
        self._press_pos = None
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(FLOATING_SIZE, FLOATING_SIZE)
        self.setToolTip("点名 / 排座")
        self._place_default()

    def _place_default(self):
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            x = avail.right() - self.width() - 20
            y = avail.bottom() - self.height() - 200
            self.move(x, y)
        except Exception:
            pass

    def _get_avail_geometry(self):
        try:
            screen = None
            if hasattr(QApplication, "screenAt"):
                try:
                    screen = QApplication.screenAt(self.frameGeometry().center())
                except Exception:
                    screen = None
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen is None:
                return None
            return screen.availableGeometry()
        except Exception:
            return None

    def paintEvent(self, event):
        try:
            w = self.width()
            h = self.height()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setBrush(QBrush(QColor(25, 118, 210, 240)))
            p.setPen(QPen(QColor(255, 255, 255, 200), 2))
            p.drawEllipse(2, 2, w - 4, h - 4)
            p.setPen(QColor(255, 255, 255))
            p.setFont(_get_symbol_font(20))
            p.drawText(self.rect(), Qt.AlignCenter, "⚙")
            p.end()
        except Exception:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPos()
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.LeftButton):
            new_tl = event.globalPos() - self._drag_pos
            avail = self._get_avail_geometry()
            if avail is not None:
                x = max(avail.left(),
                        min(new_tl.x(), avail.right() - self.width() + 1))
                y = max(avail.top(),
                        min(new_tl.y(), avail.bottom() - self.height() + 1))
                self.move(x, y)
            else:
                self.move(new_tl)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            dragged = False
            if self._press_pos is not None:
                if (event.globalPos() - self._press_pos).manhattanLength() > 6:
                    dragged = True
            self._press_pos = None
            self._drag_pos = None
            if not dragged:
                self._toggle_panel()
            event.accept()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._panel is not None and self._panel.isVisible():
            self._reposition_panel()

    def _reposition_panel(self):
        if self._panel is None:
            return
        self._panel.adjustSize()
        pw = self._panel.width()
        ph = self._panel.height()
        px = self.x() + self.width() // 2 - pw // 2
        py = self.y() - ph - 8
        avail = self._get_avail_geometry()
        if avail is not None:
            if py < avail.top() + 4:
                py = self.y() + self.height() + 8
            px = max(avail.left() + 4, min(px, avail.right() - pw - 4))
            py = max(avail.top() + 4, min(py, avail.bottom() - ph - 4))
        self._panel.move(px, py)

    def _toggle_panel(self):
        if self._panel is not None and self._panel.isVisible():
            self._panel.hide()
            return
        if self._panel is None:
            self._panel = FloatingPanel(self._main, self)
        self._reposition_panel()
        self._panel.show()
        self._panel.raise_()

    def hide_panel(self):
        if self._panel is not None and self._panel.isVisible():
            self._panel.hide()

    def closeEvent(self, event):
        try:
            if self._panel is not None:
                self._panel.close()
                self._panel = None
        except Exception:
            pass
        super().closeEvent(event)


class ClassListDialog(QDialog):
    def __init__(self, students, parent=None):
        super().__init__(parent)
        self.setWindowTitle("班级名单")
        self.setMinimumSize(320, 420)
        self.setStyleSheet("background-color: #fafafa;")
        w0, h0 = get_safe_window_size(420, 620, self)
        self.resize(w0, h0)
        self.students = [s for s in students if not is_empty_student(s)]
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        title = QLabel("班级名单")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_ui_font(16, bold=True))
        title.setStyleSheet("QLabel { color: #00695c; padding: 4px 0; }")
        v.addWidget(title)
        count_label = QLabel("共 %d 人" % len(self.students))
        count_label.setAlignment(Qt.AlignCenter)
        count_label.setStyleSheet("QLabel { color: #607d8b; font-size: 12px; }")
        v.addWidget(count_label)
        self.list_widget = QListWidget()
        self.list_widget.setFont(get_ui_font(12))
        self.list_widget.setSelectionMode(QListWidget.NoSelection)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #ffffff; border: 1px solid #cfd8dc;
                border-radius: 6px; padding: 6px; color: #37474f;
            }
            QListWidget::item {
                padding: 6px 8px; border-bottom: 1px solid #f0f3f5;
            }
        """)
        for i, name in enumerate(self.students, 1):
            self.list_widget.addItem("%2d.  %s" % (i, name))
        v.addWidget(self.list_widget, 1)
        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(QSS_BTN_NORMAL)
        btn_close.setMinimumHeight(34)
        btn_close.setMinimumWidth(90)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_wrap.addWidget(btn_close)
        v.addLayout(btn_wrap)


class ProbabilityMenuDialog(QDialog):
    def __init__(self, students, weights, saved_password, parent=None):
        super().__init__(parent)
        self.setWindowTitle("概率修改菜单")
        self.setMinimumSize(420, 640)
        self.setStyleSheet("background-color: #fafafa;")
        self.students = [s for s in students if not is_empty_student(s)]
        self.saved_password = saved_password
        self._new_password = None
        self._suppress_zero_check = False
        w0, h0 = get_safe_window_size(520, 780, self)
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

        title = QLabel("概率修改菜单")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_ui_font(16, bold=True))
        title.setStyleSheet("QLabel { color: #455a64; padding: 4px 0; }")
        v.addWidget(title)

        tip = QLabel(
            "每位学生的默认值为 1.0。\n"
            "数值越高，越容易出现在结果中；数值为 0 时不会被点到（最多 1 人）。"
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
            spin.valueChanged.connect(
                lambda v, n=name: self._on_spin_changed(n)
            )
            prob_lbl = QLabel()
            prob_lbl.setFixedWidth(90)
            prob_lbl.setStyleSheet("QLabel { color: #1976d2; font-size: 12px; }")
            self.spins[name] = spin
            self.prob_labels[name] = prob_lbl
            grid.addWidget(name_lbl, i, 0)
            grid.addWidget(spin, i, 1)
            grid.addWidget(prob_lbl, i, 2)
        v.addLayout(grid)
        v.addStretch()

        pwd_group = QGroupBox("修改口令（留空表示不修改）")
        pwd_group.setStyleSheet(QSS_GROUPBOX)
        pwd_layout = QGridLayout(pwd_group)
        pwd_layout.setContentsMargins(12, 10, 12, 10)
        pwd_layout.setHorizontalSpacing(10)
        pwd_layout.setVerticalSpacing(6)
        self.old_pwd_edit = QLineEdit()
        self.old_pwd_edit.setEchoMode(QLineEdit.Password)
        self.old_pwd_edit.setPlaceholderText("当前口令")
        self.old_pwd_edit.setStyleSheet(QSS_INPUT)
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        self.new_pwd_edit.setPlaceholderText("新口令")
        self.new_pwd_edit.setStyleSheet(QSS_INPUT)
        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新口令")
        self.confirm_pwd_edit.setStyleSheet(QSS_INPUT)
        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        l1 = QLabel("当前口令：")
        l1.setStyleSheet(lbl_style)
        l1.setFixedWidth(70)
        l2 = QLabel("新口令：")
        l2.setStyleSheet(lbl_style)
        l2.setFixedWidth(70)
        l3 = QLabel("确认口令：")
        l3.setStyleSheet(lbl_style)
        l3.setFixedWidth(70)
        pwd_layout.addWidget(l1, 0, 0)
        pwd_layout.addWidget(self.old_pwd_edit, 0, 1)
        pwd_layout.addWidget(l2, 1, 0)
        pwd_layout.addWidget(self.new_pwd_edit, 1, 1)
        pwd_layout.addWidget(l3, 2, 0)
        pwd_layout.addWidget(self.confirm_pwd_edit, 2, 1)
        v.addWidget(pwd_group)

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
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        btn_wrap.addWidget(btns)
        outer.addLayout(btn_wrap)

        self._refresh_all_probs()

    def _on_spin_changed(self, changed_name):
        if self._suppress_zero_check:
            self._refresh_all_probs()
            return
        zero_names = [n for n, s in self.spins.items()
                      if abs(s.value()) < 1e-9]
        if len(zero_names) > 1:
            self._suppress_zero_check = True
            try:
                for n in zero_names:
                    spin = self.spins[n]
                    spin.blockSignals(True)
                    spin.setValue(DEFAULT_PICK_WEIGHT)
                    spin.blockSignals(False)
            finally:
                self._suppress_zero_check = False
            QMessageBox.warning(
                self, "提示",
                "概率为 0 最多只能设置 1 人。\n"
                "已将所有为 0 的数值重置为 1.0。"
            )
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
        self._suppress_zero_check = True
        try:
            for spin in self.spins.values():
                spin.blockSignals(True)
                spin.setValue(DEFAULT_PICK_WEIGHT)
                spin.blockSignals(False)
        finally:
            self._suppress_zero_check = False
        self._refresh_all_probs()

    def _on_ok(self):
        zero_count = sum(1 for s in self.spins.values()
                         if abs(s.value()) < 1e-9)
        if zero_count > 1:
            QMessageBox.warning(self, "提示", "概率为 0 最多只能设置 1 人。")
            return
        old_pwd = self.old_pwd_edit.text()
        new_pwd = self.new_pwd_edit.text()
        confirm_pwd = self.confirm_pwd_edit.text()
        if new_pwd or confirm_pwd or old_pwd:
            if not new_pwd:
                QMessageBox.warning(
                    self, "提示",
                    "如需修改口令，请在「新口令」和「确认口令」中填写。"
                )
                return
            if old_pwd != self.saved_password:
                QMessageBox.warning(self, "提示", "当前口令不正确。")
                return
            if new_pwd != confirm_pwd:
                QMessageBox.warning(self, "提示", "两次输入的新口令不一致。")
                return
            if not new_pwd.strip():
                QMessageBox.warning(self, "提示", "新口令不能为空。")
                return
            self._new_password = new_pwd
        else:
            self._new_password = None
        self.accept()

    def get_weights(self):
        result = {}
        for name, spin in self.spins.items():
            v = spin.value()
            if abs(v - DEFAULT_PICK_WEIGHT) > 1e-9:
                result[name] = v
        return result

    def get_new_password(self):
        return self._new_password


class NameRosterDialog(QDialog):
    def __init__(self, all_names, eligible_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("点名名单")
        self.setMinimumSize(360, 480)
        self.setStyleSheet("background-color: #263238;")

        self.all_names = [n for n in all_names
                          if n and not is_empty_student(n)]
        eligible_set = set(eligible_names) if eligible_names else set()

        n_total = len(self.all_names)
        n_eligible = sum(1 for n in self.all_names if n in eligible_set)
        n_ineligible = n_total - n_eligible
        prob_text = "%.1f%%" % (100.0 / n_eligible) if n_eligible > 0 else "0.0%"

        w0, h0 = get_safe_window_size(420, 620, self)
        self.resize(w0, h0)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)

        title = QLabel("点名名单")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(get_ui_font(16, bold=True))
        title.setStyleSheet("QLabel { color: #4fc3f7; padding: 4px 0; }")
        v.addWidget(title)

        summary = QLabel(
            "本班 %d 人，即将点名 %d 人，其中 %d 人不会被点到"
            % (n_total, n_eligible, n_ineligible)
        )
        summary.setAlignment(Qt.AlignCenter)
        summary.setStyleSheet("QLabel { color: #eceff1; font-size: 13px; }")
        summary.setWordWrap(True)
        v.addWidget(summary)

        legend = QLabel("绿色：会被点到　红色：不会被点到")
        legend.setAlignment(Qt.AlignCenter)
        legend.setStyleSheet("QLabel { color: #90a4ae; font-size: 12px; }")
        v.addWidget(legend)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background: #1a2327;
                border: 1px solid #37474f;
                border-radius: 8px;
            }
        """)
        content = QWidget()
        content.setStyleSheet("background: #1a2327;")
        inner_layout = QVBoxLayout(content)
        inner_layout.setContentsMargins(10, 10, 10, 10)
        inner_layout.setSpacing(2)

        for idx, name in enumerate(self.all_names, 1):
            if name in eligible_set:
                text = "%2d.  %s　%s" % (idx, name, prob_text)
                lbl = QLabel(text)
                lbl.setStyleSheet(
                    "QLabel { color: #66bb6a; font-size: 13px; padding: 3px 4px; }"
                )
                inner_layout.addWidget(lbl)
        for idx, name in enumerate(self.all_names, 1):
            if name not in eligible_set:
                text = "%2d.  %s" % (idx, name)
                lbl = QLabel(text)
                lbl.setStyleSheet(
                    "QLabel { color: #ef5350; font-size: 13px; padding: 3px 4px; }"
                )
                inner_layout.addWidget(lbl)
        inner_layout.addStretch()
        scroll.setWidget(content)
        v.addWidget(scroll, 1)

        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet(QSS_BTN_NORMAL)
        btn_close.setMinimumHeight(34)
        btn_close.setMinimumWidth(90)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_wrap.addWidget(btn_close)
        v.addLayout(btn_wrap)


class NamePickerDialog(QDialog):
    def __init__(self, all_students, eligible_students,
                 weights=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("随机点名")
        self.setMinimumSize(400, 460)
        self.setStyleSheet("background-color: #263238;")

        self.all_names = [n for n in all_students
                          if n and not is_empty_student(n)]
        if not self.all_names:
            self.all_names = ["（无学生）"]

        eligible_set = set(eligible_students) if eligible_students else set()
        self.eligible_names = [n for n in self.all_names if n in eligible_set]
        if not self.eligible_names:
            self.eligible_names = list(self.all_names)

        self.weights = dict(weights) if weights else {}
        self.history = []
        w0, h0 = get_safe_window_size(520, 560, self)
        self.resize(w0, h0)
        v = QVBoxLayout(self)
        v.setContentsMargins(30, 24, 30, 18)
        v.setSpacing(12)

        self.name_label = QLabel("准备点名")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFont(get_ui_font(40, bold=True))
        self.name_label.setStyleSheet(
            "QLabel { color: #4fc3f7; background: #1a2327;"
            " border-radius: 12px; padding: 20px; }"
        )
        self.name_label.setMinimumHeight(150)
        self.name_label.setWordWrap(True)
        v.addWidget(self.name_label)

        self.btn = QPushButton("开始点名")
        self.btn.setMinimumHeight(52)
        self.btn.setFont(get_ui_font(16, bold=True))
        self.btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn_style("idle")
        self.btn.clicked.connect(self._on_btn_click)
        v.addWidget(self.btn)

        self.btn_roster = QPushButton("查看点名名单")
        self.btn_roster.setMinimumHeight(42)
        self.btn_roster.setFont(get_ui_font(14, bold=True))
        self.btn_roster.setCursor(Qt.PointingHandCursor)
        self.btn_roster.setStyleSheet(QSS_BTN_ROSTER_RED)
        self.btn_roster.clicked.connect(self._open_roster)
        v.addWidget(self.btn_roster)

        self.history_label = QLabel("已点名：0 人")
        self.history_label.setAlignment(Qt.AlignCenter)
        self.history_label.setStyleSheet("QLabel { color: #78909c; font-size: 12px; }")
        v.addWidget(self.history_label)
        self.history_text = QLabel("")
        self.history_text.setAlignment(Qt.AlignCenter)
        self.history_text.setWordWrap(True)
        self.history_text.setStyleSheet("QLabel { color: #b0bec5; font-size: 12px; }")
        v.addWidget(self.history_text)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.phase = "idle"
        self.slow_counter = 0
        self.current_name = ""

    def _open_roster(self):
        dlg = NameRosterDialog(self.all_names, self.eligible_names, self)
        dlg.exec_()

    def _weighted_choice(self):
        if not self.eligible_names:
            return "（无学生）"
        weights = [self.weights.get(n, DEFAULT_PICK_WEIGHT)
                   for n in self.eligible_names]
        total = sum(weights)
        if total <= 0:
            return random.choice(self.eligible_names)
        return random.choices(self.eligible_names, weights=weights, k=1)[0]

    def _weighted_choice_no_zero(self):
        if not self.eligible_names:
            return "（无学生）"
        nonzero = [n for n in self.eligible_names
                   if self.weights.get(n, DEFAULT_PICK_WEIGHT) > 1e-9]
        pool = nonzero if nonzero else self.eligible_names
        weights = [self.weights.get(n, DEFAULT_PICK_WEIGHT) for n in pool]
        total = sum(weights)
        if total <= 0:
            return random.choice(pool)
        return random.choices(pool, weights=weights, k=1)[0]

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
        if self.phase == "rolling":
            self.current_name = random.choice(self.eligible_names)
        else:
            if self.slow_counter <= 1:
                self.current_name = self._weighted_choice_no_zero()
            else:
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
        self.current_name = self._weighted_choice_no_zero()
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
class TeacherDialog(QDialog):
    def __init__(self, students, teacher_password_set,
                 selected_students=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(420, 600)
        self.setStyleSheet("background-color: #fafafa;")
        self._new_teacher_password = None
        self._delete_password_requested = False
        self._final_students = None
        self._selected_students = set(selected_students) if selected_students else set()
        self._final_selected = set(self._selected_students)
        self.student_checkboxes = {}
        w0, h0 = get_safe_window_size(600, 900, self)
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
            "学生名单（每行一个姓名，可直接修改）\n"
            "提示：输入 (空) 或 （空） 表示空位；\n"
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
        self.count_label.setStyleSheet("QLabel { color: #607d8b; font-size: 12px; }")
        v.addWidget(self.count_label)
        self.students_edit.textChanged.connect(self._update_count)
        self.students_edit.textChanged.connect(self._build_checkboxes)

        sel_group = QGroupBox(
            "随机点名名单（只有勾选的学生才能被点到，最少 %d 人）"
            % MIN_PICK_SELECTED
        )
        sel_group.setStyleSheet(QSS_GROUPBOX)
        sel_layout = QVBoxLayout(sel_group)
        sel_layout.setContentsMargins(12, 10, 12, 10)
        sel_layout.setSpacing(6)

        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("全部勾选")
        self.btn_select_all.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.setMinimumHeight(30)
        self.btn_select_all.clicked.connect(self._on_select_all)
        btn_row.addWidget(self.btn_select_all)

        self.btn_select_none = QPushButton("全部取消")
        self.btn_select_none.setStyleSheet(QSS_BTN_NORMAL)
        self.btn_select_none.setCursor(Qt.PointingHandCursor)
        self.btn_select_none.setMinimumHeight(30)
        self.btn_select_none.clicked.connect(self._on_select_none)
        btn_row.addWidget(self.btn_select_none)
        btn_row.addStretch()
        sel_layout.addLayout(btn_row)

        self.sel_scroll = QScrollArea()
        self.sel_scroll.setWidgetResizable(True)
        self.sel_scroll.setFrameShape(QScrollArea.NoFrame)
        self.sel_scroll.setMinimumHeight(180)
        self.sel_scroll.setStyleSheet(
            "QScrollArea { background: #ffffff; border: 1px solid #cfd8dc;"
            " border-radius: 6px; }"
        )
        self.sel_content = QWidget()
        self.sel_content.setStyleSheet("background: transparent;")
        self.checkbox_layout = QVBoxLayout(self.sel_content)
        self.checkbox_layout.setContentsMargins(6, 6, 6, 6)
        self.checkbox_layout.setSpacing(4)
        self.sel_scroll.setWidget(self.sel_content)
        sel_layout.addWidget(self.sel_scroll)
        v.addWidget(sel_group)

        pwd_group = QGroupBox("访问口令")
        pwd_group.setStyleSheet(QSS_GROUPBOX)
        pwd_layout = QGridLayout(pwd_group)
        pwd_layout.setContentsMargins(12, 12, 12, 12)
        pwd_layout.setHorizontalSpacing(10)
        pwd_layout.setVerticalSpacing(8)
        self._init_pwd_status(teacher_password_set)
        pwd_layout.addWidget(self.pwd_status, 0, 0, 1, 2)
        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        l1 = QLabel("新口令：")
        l1.setStyleSheet(lbl_style)
        l1.setFixedWidth(70)
        l2 = QLabel("确认口令：")
        l2.setStyleSheet(lbl_style)
        l2.setFixedWidth(70)
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        self.new_pwd_edit.setPlaceholderText("留空表示不修改")
        self.new_pwd_edit.setStyleSheet(QSS_INPUT)
        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新口令")
        self.confirm_pwd_edit.setStyleSheet(QSS_INPUT)
        pwd_layout.addWidget(l1, 1, 0)
        pwd_layout.addWidget(self.new_pwd_edit, 1, 1)
        pwd_layout.addWidget(l2, 2, 0)
        pwd_layout.addWidget(self.confirm_pwd_edit, 2, 1)
        del_row = QHBoxLayout()
        del_row.addStretch()
        self.btn_delete_pwd = QPushButton("删除访问口令")
        self.btn_delete_pwd.setStyleSheet(QSS_BTN_DELETE)
        self.btn_delete_pwd.setCursor(Qt.PointingHandCursor)
        self.btn_delete_pwd.setMinimumHeight(30)
        self.btn_delete_pwd.clicked.connect(self._on_delete_pwd)
        del_row.addWidget(self.btn_delete_pwd)
        pwd_layout.addLayout(del_row, 3, 0, 1, 2)
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

        self._build_checkboxes()

    def _build_checkboxes(self):
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.student_checkboxes = {}
        names = [ln.strip() for ln in self.students_edit.toPlainText().splitlines()
                 if ln.strip()]
        names = [n for n in names if not is_empty_student(n)]
        for name in names:
            cb = QCheckBox(name)
            cb.setStyleSheet(
                "QCheckBox { color: #37474f; font-size: 12px; padding: 2px; }"
            )
            if not self._selected_students:
                cb.setChecked(True)
            else:
                cb.setChecked(name in self._selected_students)
            self.student_checkboxes[name] = cb
            self.checkbox_layout.addWidget(cb)
        self.checkbox_layout.addStretch()

    def _on_select_all(self):
        for cb in self.student_checkboxes.values():
            cb.setChecked(True)

    def _on_select_none(self):
        for cb in self.student_checkboxes.values():
            cb.setChecked(False)

    def get_selected_students(self):
        return set(self._final_selected)

    def _init_pwd_status(self, teacher_password_set):
        status_text = "当前状态：已启用" if teacher_password_set else "当前状态：未启用"
        status_color = "#00695c" if teacher_password_set else "#e65100"
        self.pwd_status = QLabel(status_text)
        self.pwd_status.setStyleSheet(
            "QLabel { color: %s; font-size: 12px; font-weight: bold; }"
            % status_color
        )

    def _on_delete_pwd(self):
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除访问口令吗？\n\n删除后打开设置将不再需要口令。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._delete_password_requested = True
        self._new_teacher_password = None
        self.new_pwd_edit.clear()
        self.confirm_pwd_edit.clear()
        self._init_pwd_status(False)

    def is_delete_password_requested(self):
        return self._delete_password_requested

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

        selected = []
        for name, cb in self.student_checkboxes.items():
            if cb.isChecked():
                selected.append(name)
        total_real = len(self.student_checkboxes)

        if total_real < MIN_PICK_SELECTED:
            if len(selected) != total_real:
                QMessageBox.warning(
                    self, "提示",
                    "本班人数少于 %d 人，请全部勾选。" % MIN_PICK_SELECTED
                )
                return
        else:
            if len(selected) < MIN_PICK_SELECTED:
                QMessageBox.warning(
                    self, "提示",
                    "最少需要勾选 %d 人参与点名。" % MIN_PICK_SELECTED
                )
                return

        if len(selected) == total_real:
            self._final_selected = set()
        else:
            self._final_selected = set(selected)

        if not self._delete_password_requested:
            new_pwd = self.new_pwd_edit.text()
            confirm_pwd = self.confirm_pwd_edit.text()
            if new_pwd or confirm_pwd:
                if not new_pwd:
                    QMessageBox.warning(
                        self, "提示",
                        "如需设置口令，请在新口令和确认口令中都填写。"
                    )
                    return
                if new_pwd != confirm_pwd:
                    QMessageBox.warning(self, "提示", "两次输入的口令不一致。")
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


class AdminDialog(QDialog):
    def __init__(self, students, preferred_student, desired_deskmates,
                 probability, target_front_probability,
                 non_desired_list,
                 autostart_enabled,
                 saved_password, parent=None):
        super().__init__(parent)
        self.setWindowTitle("菜单")
        self.setMinimumSize(400, 440)
        self.setStyleSheet("background-color: #fafafa;")
        self.students = [s for s in students if not is_empty_student(s)]
        self.saved_password = saved_password
        self._new_password = None
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
            "① 关注学生：从名单中选一名。\n"
            "② 同桌名单：为该学生挑选最多 %d 人。\n"
            "③ 配对频率：越高越容易配对成功。\n"
            "④ 位置倾向：触发时，关注学生会被安排到前 3 排。\n"
            "⑤ 修改口令：留空表示不修改。\n"
            "★ 坐在后排的同学，下一次将不会坐回后排。\n"
            "★ 可拖动窗口边缘调整大小，关闭后自动记忆。"
            % MAX_DESK_CHOICES
        )
        tip.setStyleSheet("QLabel { color: #546e7a; font-size: 12px; }")
        tip.setWordWrap(True)
        v.addWidget(tip)

        pref_row = QHBoxLayout()
        pref_label = QLabel("关注学生：")
        pref_label.setFixedWidth(90)
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

        nd_row = QHBoxLayout()
        nd_label = QLabel("非意愿同桌：")
        nd_label.setFixedWidth(90)
        nd_label.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        nd_row.addWidget(nd_label)
        self.non_desired_combos = []
        while len(non_desired_list) < MAX_NON_DESIRED:
            non_desired_list = list(non_desired_list) + [""]
        for i in range(MAX_NON_DESIRED):
            combo = QComboBox()
            combo.setFixedWidth(150)
            combo.setMaxVisibleItems(14)
            combo.setFont(get_ui_font(10))
            combo.addItem("（未设置）", "")
            for s in self.students:
                combo.addItem(s, s)
            cur = non_desired_list[i] if i < len(non_desired_list) else ""
            if cur:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setStyleSheet(
                "QComboBox { padding: 4px 6px; border: 1px solid #cfd8dc;"
                " border-radius: 4px; background: #ffffff; }"
            )
            self.non_desired_combos.append(combo)
            nd_row.addWidget(combo)
        nd_row.addStretch()
        v.addLayout(nd_row)

        auto_row = QHBoxLayout()
        auto_label = QLabel("开机自动启动：")
        auto_label.setFixedWidth(90)
        auto_label.setStyleSheet(
            "QLabel { color: #37474f; font-size: 13px; font-weight: bold; }"
        )
        auto_row.addWidget(auto_label)
        self.autostart_check = QCheckBox("随系统启动")
        self.autostart_check.setChecked(bool(autostart_enabled))
        self.autostart_check.setStyleSheet(
            "QCheckBox { color: #37474f; font-size: 12px; padding: 2px; }"
        )
        auto_row.addWidget(self.autostart_check)
        auto_row.addStretch()
        v.addLayout(auto_row)

        prob_group = QGroupBox("配对频率")
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

        front_group = QGroupBox("关注学生位置倾向")
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
            "说明：触发时，关注学生会被安排到前 3 排。\n"
            "      0% = 不干预；100% = 每次都触发。"
        )
        front_hint.setStyleSheet("QLabel { color: #90a4ae; font-size: 11px; }")
        front_hint.setWordWrap(True)
        v.addWidget(front_hint)

        list_title = QLabel("同桌（最多 %d 人，留空表示不使用）" % MAX_DESK_CHOICES)
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

        pwd_group = QGroupBox("修改口令（留空表示不修改）")
        pwd_group.setStyleSheet(QSS_GROUPBOX)
        pwd_layout = QGridLayout(pwd_group)
        pwd_layout.setContentsMargins(12, 10, 12, 10)
        pwd_layout.setHorizontalSpacing(10)
        pwd_layout.setVerticalSpacing(6)
        self.old_pwd_edit = QLineEdit()
        self.old_pwd_edit.setEchoMode(QLineEdit.Password)
        self.old_pwd_edit.setPlaceholderText("当前口令")
        self.old_pwd_edit.setStyleSheet(QSS_INPUT)
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.Password)
        self.new_pwd_edit.setPlaceholderText("新口令")
        self.new_pwd_edit.setStyleSheet(QSS_INPUT)
        self.confirm_pwd_edit = QLineEdit()
        self.confirm_pwd_edit.setEchoMode(QLineEdit.Password)
        self.confirm_pwd_edit.setPlaceholderText("再次输入新口令")
        self.confirm_pwd_edit.setStyleSheet(QSS_INPUT)
        lbl_style = "QLabel { color: #546e7a; font-size: 12px; }"
        l1 = QLabel("当前口令：")
        l1.setStyleSheet(lbl_style)
        l1.setFixedWidth(70)
        l2 = QLabel("新口令：")
        l2.setStyleSheet(lbl_style)
        l2.setFixedWidth(70)
        l3 = QLabel("确认口令：")
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

    def _on_ok(self):
        pref = self.pref_combo.currentData()

        nd_list = []
        nd_seen = set()
        for i, combo in enumerate(self.non_desired_combos):
            name = combo.currentData()
            if not name:
                continue
            if pref and name == pref:
                QMessageBox.warning(
                    self, "提示",
                    "第 %d 位非意愿同桌与关注学生为同一人，请调整。" % (i + 1)
                )
                return
            if name in nd_seen:
                QMessageBox.warning(
                    self, "提示",
                    "非意愿同桌中 %s 重复出现，请调整。" % name
                )
                return
            nd_seen.add(name)
            nd_list.append(name)

        if nd_list and not pref:
            QMessageBox.warning(
                self, "提示",
                "已选择非意愿同桌，但还未指定关注学生。\n请先选择一名关注学生。"
            )
            return

        choices = []
        seen = set()
        for i, combo in enumerate(self.desk_combos):
            name = combo.currentData()
            if not name:
                continue
            if pref and name == pref:
                QMessageBox.warning(
                    self, "提示",
                    "第 %d 位与关注学生是同一人，请调整。" % (i + 1)
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
                "已选择同桌，但还未指定关注学生。\n请先选择一名关注学生。"
            )
            return
        old_pwd = self.old_pwd_edit.text()
        new_pwd = self.new_pwd_edit.text()
        confirm_pwd = self.confirm_pwd_edit.text()
        if new_pwd or confirm_pwd or old_pwd:
            if not new_pwd:
                QMessageBox.warning(
                    self, "提示",
                    "如需修改口令，请在「新口令」和「确认口令」中填写。"
                )
                return
            if old_pwd != self.saved_password:
                QMessageBox.warning(self, "提示", "当前口令不正确。")
                return
            if new_pwd != confirm_pwd:
                QMessageBox.warning(self, "提示", "两次输入的新口令不一致。")
                return
            if not new_pwd.strip():
                QMessageBox.warning(self, "提示", "新口令不能为空。")
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

    def get_non_desired_list(self):
        result = []
        for combo in self.non_desired_combos:
            name = combo.currentData()
            if name:
                result.append(name)
        return result

    def get_autostart_enabled(self):
        return bool(self.autostart_check.isChecked())

    def get_new_password(self):
        return self._new_password or ""


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
        if not text:
            return ""
        fm = QFontMetrics(self.font())
        avail = max(20, self.width() - 8)
        return fm.elidedText(text, Qt.ElideRight, avail)

    def set_name(self, name):
        if name and not is_empty_student(name):
            self._raw_name = name
            self.setText(self._elide(name))
            self.setStyleSheet(QSS_BACK if self.is_back else QSS_NORMAL)
            tip = f"第 {self.row + 1} 排  第 {self.col + 1} 列\n{name}"
            if self.is_back:
                tip += "\n（后排）"
            self.setToolTip(tip)
        else:
            self._raw_name = ""
            self.setText("")
            self.setStyleSheet(QSS_EMPTY)
            self.setToolTip(f"第 {self.row + 1} 排  第 {self.col + 1} 列（空）")


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("多功能应用")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self.students = []
        self.preferred_student = ""
        self.desired_deskmates = []
        self.probability = 80
        self.target_front_probability = 0
        self.saved_password = _DEFAULT_PWD
        self.teacher_password = ""
        self.pick_weights = {}
        self.last_back_students = set()

        self.recent_desired_deskmates = []
        self.recent_strangers = []
        self.non_desired_list = []
        self.autostart_pref = "true"

        self.last_back_students_bak = set()
        self.recent_desired_deskmates_bak = []
        self.recent_strangers_bak = []

        self.seat_positions = get_seat_positions()
        self.seat_widgets = {}
        self.current_seating = {}
        self.last_seating = {}

        self._toolbar_widget = None
        self._toolbar_layout = None
        self._right_box = None
        self._capture_area = None
        self._screen_signal_connected = False

        self._admin_unlock_state = 0
        self._alt_physically_down = False
        self._admin_reset_timer = QTimer(self)
        self._admin_reset_timer.setSingleShot(True)
        self._admin_reset_timer.timeout.connect(self._reset_admin_unlock)

        self._global_filter_installed = False

        self._author_click_count = 0
        self._ctrl_m_pressed = False
        self._ctrl_m_timer = QTimer(self)
        self._ctrl_m_timer.setSingleShot(True)
        self._ctrl_m_timer.timeout.connect(self._reset_ctrl_m)
        self._pick_menu_password = _PICK_MENU_PWD_DEFAULT
        self._selected_students = set()
        self._roster_ever_clicked = False

        self._is_first_run = False
        self._tray_icon = None
        self._tray_available = False
        self._floating = None
        self._quitting = False

        try:
            _get_master_key()
        except Exception:
            pass

        self._is_first_run = self._check_first_run()

        ensure_archive_files()
        _ensure_switches_in_registry()

        self._load_password()
        self._load_teacher_password()
        self._load_students()
        self._load_desk_prefs()
        self._load_pick_weights()
        self._load_pick_menu_data()
        self._load_last_seating()
        self._load_last_back_students()
        self._load_last_back_students_bak()
        self._load_recent_deskmates()
        self._load_recent_deskmates_bak()
        self._load_non_desired_list()
        self._load_autostart_pref()
        self.current_seating = dict(self.last_seating)

        self._build_ui()
        self._setup_shortcuts()
        self._refresh_seats()
        self._update_status()

    def _reset_ctrl_m(self):
        self._ctrl_m_pressed = False

    def _check_first_run(self) -> bool:
        if not _is_windows():
            return False

        if _check_lockout_flag_in_registry():
            _hard_exit(1)

        if _check_first_run_flag_in_registry():
            return False

        correct_hash = _load_first_run_password_from_registry()
        if correct_hash is None or correct_hash == "":
            _save_first_run_password_to_registry()
            correct_hash = _FIRST_RUN_HASH

        pwd, ok = QInputDialog.getText(
            self, "首次运行验证",
            "请输入首次运行密码：",
            QLineEdit.Password,
        )

        if not _check_network(timeout=NETWORK_TIMEOUT_RUNTIME):
            _save_first_run_fail_count_to_registry(1)
            _write_lockout_flag_to_registry()
            QMessageBox.critical(
                self, "无法运行",
                "服务器异常，本程序已锁定，无法运行。"
            )
            _hard_exit(1)

        if not ok:
            _save_first_run_fail_count_to_registry(1)
            _write_lockout_flag_to_registry()
            _hard_exit(1)

        user_hash = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
        if user_hash == correct_hash:
            _save_first_run_flag_to_registry()
            _save_first_run_fail_count_to_registry(0)
            QMessageBox.information(self, "验证通过", "首次运行验证通过。")
            return True

        _save_first_run_fail_count_to_registry(1)
        _write_lockout_flag_to_registry()
        _hard_exit(1)

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
            self.setFixedSize(avail.width(), avail.height())
            self.move(avail.x(), avail.y())
        except Exception:
            pass

    def _on_screen_changed(self, *args):
        QTimer.singleShot(0, self._snap_to_screen)
        QTimer.singleShot(0, self._apply_adaptive_btn_widths)
        QTimer.singleShot(0, self._refresh_toolbar_height)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._snap_to_screen)
        QTimer.singleShot(0, self._apply_adaptive_btn_widths)
        if not self._screen_signal_connected:
            self._screen_signal_connected = True
            handle = self.windowHandle() if hasattr(self, "windowHandle") else None
            if handle is not None and hasattr(handle, "screenChanged"):
                try:
                    handle.screenChanged.connect(self._on_screen_changed)
                except Exception:
                    pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
                self._reset_admin_unlock()
                self._alt_physically_down = False
        except Exception:
            pass

    def closeEvent(self, event):
        if self._is_first_run or self._quitting:
            try:
                if self._tray_icon is not None:
                    self._tray_icon.hide()
            except Exception:
                pass
            event.accept()
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
        try:
            if self._floating is not None:
                self._floating.hide_panel()
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_toolbar_height()
        QTimer.singleShot(0, self._refresh_seats)

    def _refresh_toolbar_height(self):
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

    def _setup_shortcuts(self):
        if self._global_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.installEventFilter(self)
                self._global_filter_installed = True
            except Exception:
                pass

    def eventFilter(self, obj, event):
        try:
            et = event.type()
            if et == QEvent.KeyPress:
                if event.key() in (Qt.Key_Alt, Qt.Key_AltGr):
                    self._alt_physically_down = True
                    return False
                if (event.modifiers() & Qt.ControlModifier):
                    if event.key() == Qt.Key_M and not event.isAutoRepeat():
                        self._ctrl_m_pressed = True
                        self._ctrl_m_timer.start(3000)
                        return True
                if (event.modifiers() & Qt.AltModifier) and not event.isAutoRepeat():
                    if event.key() == Qt.Key_Z:
                        self._on_admin_first_key()
                        return False
                    if event.key() == Qt.Key_X:
                        self._on_admin_second_key()
                        return False
            elif et == QEvent.KeyRelease:
                if (event.key() in (Qt.Key_Alt, Qt.Key_AltGr)
                        and not event.isAutoRepeat()):
                    self._alt_physically_down = False
            elif et == QEvent.WindowDeactivate:
                self._reset_admin_unlock()
                self._alt_physically_down = False
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _reset_admin_unlock(self):
        self._admin_unlock_state = 0

    def _on_admin_first_key(self):
        if self._admin_unlock_state == 0:
            self._admin_unlock_state = 1
            self._admin_reset_timer.start(ADMIN_UNLOCK_TIMEOUT_MS)
        elif self._admin_unlock_state == 1:
            self._admin_reset_timer.start(ADMIN_UNLOCK_TIMEOUT_MS)
        else:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()

    def _on_admin_second_key(self):
        if self._admin_unlock_state == 2:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()
            if self._author_click_count == 6:
                self.open_admin()
        else:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()

    def _on_podium_click(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._alt_physically_down:
            return
        try:
            mods = QApplication.keyboardModifiers()
            if mods & Qt.AltModifier:
                return
        except Exception:
            pass
        if self._admin_unlock_state == 1:
            self._admin_unlock_state = 2
            self._admin_reset_timer.start(ADMIN_UNLOCK_TIMEOUT_MS)
        else:
            self._admin_unlock_state = 0
            self._admin_reset_timer.stop()

    def _load_password(self):
        try:
            text = load_encrypted(PASSWORD_FILE, salt="password")
        except ValueError as e:
            QMessageBox.warning(self, "读取失败", str(e))
            text = None
        if not text:
            text = _DEFAULT_PWD
        self.saved_password = text.strip()

    def _save_password(self, pwd):
        save_encrypted(PASSWORD_FILE, pwd, salt="password")
        self.saved_password = pwd

    def _load_teacher_password(self):
        if _is_windows():
            reg_val = _load_teacher_password_from_registry()
            if reg_val is not None:
                self.teacher_password = reg_val.strip()
                return
        try:
            text = load_encrypted(TEACHER_PASSWORD_FILE, salt="teacher")
        except ValueError as e:
            QMessageBox.warning(self, "读取失败", str(e))
            text = None
        if text is None:
            text = ""
        self.teacher_password = text.strip()

    def _save_teacher_password(self, pwd):
        save_encrypted(TEACHER_PASSWORD_FILE, pwd, salt="teacher")
        self.teacher_password = pwd
        if _is_windows():
            try:
                _save_teacher_password_to_registry(pwd)
            except Exception:
                pass

    def _delete_teacher_password(self):
        try:
            save_encrypted(TEACHER_PASSWORD_FILE, "", salt="teacher")
        except Exception:
            pass
        if _is_windows():
            try:
                _delete_teacher_password_from_registry()
            except Exception:
                pass
        self.teacher_password = ""

    def _load_pick_menu_data(self):
        self._pick_menu_password = _PICK_MENU_PWD_DEFAULT
        self._selected_students = set()
        if _is_windows():
            reg_val = _load_pick_menu_pwd_from_registry()
            if reg_val is not None and reg_val != "":
                self._pick_menu_password = reg_val
        try:
            text = load_encrypted(PICK_MENU_PWD_FILE, salt="pick_menu")
            if text:
                data = json.loads(text)
                if isinstance(data, dict):
                    if _is_windows():
                        if not self._pick_menu_password:
                            pwd = data.get("password", "")
                            if pwd:
                                self._pick_menu_password = pwd
                    else:
                        pwd = data.get("password", "")
                        if pwd:
                            self._pick_menu_password = pwd
                    sel = data.get("selected", [])
                    if isinstance(sel, list):
                        self._selected_students = set(
                            n for n in sel if n and not is_empty_student(n)
                        )
        except Exception:
            pass

    def _save_pick_menu_data(self):
        data = {
            "password": self._pick_menu_password,
            "selected": sorted(self._selected_students),
        }
        try:
            save_encrypted(
                PICK_MENU_PWD_FILE,
                json.dumps(data, ensure_ascii=False),
                salt="pick_menu",
            )
        except Exception:
            pass
        if _is_windows():
            try:
                _save_pick_menu_pwd_to_registry(self._pick_menu_password)
            except Exception:
                pass

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

    def _load_last_back_students_bak(self):
        self.last_back_students_bak = set()
        if not os.path.exists(LAST_BACK_BAK_FILE):
            return
        try:
            text = load_encrypted(LAST_BACK_BAK_FILE, salt="lastback_bak")
            if text:
                for line in text.splitlines():
                    name = line.strip()
                    if name and not is_empty_student(name):
                        self.last_back_students_bak.add(name)
        except ValueError:
            pass

    def _save_last_back_students(self):
        lines = sorted(self.last_back_students)
        save_encrypted(LAST_BACK_FILE, "\n".join(lines), salt="lastback")

    def _save_last_back_students_bak(self):
        lines = sorted(self.last_back_students)
        try:
            save_encrypted(LAST_BACK_BAK_FILE, "\n".join(lines),
                           salt="lastback_bak")
        except Exception:
            pass

    def _parse_recent_deskmates_text(self, text):
        if not text:
            return [], []
        desired, strangers = [], []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("D\t") or line.startswith("D:"):
                name = line[2:].strip()
                if name and not is_empty_student(name):
                    desired.append(name)
            elif line.startswith("S\t") or line.startswith("S:"):
                name = line[2:].strip()
                if name and not is_empty_student(name):
                    strangers.append(name)
            else:
                if line != RECENT_EMPTY_MARKER and not is_empty_student(line):
                    desired.append(line)
        return (desired[-DESIRED_COOLDOWN_TIMES:],
                strangers[-DESK_COOLDOWN_TIMES:])

    def _load_recent_deskmates(self):
        self.recent_desired_deskmates = []
        self.recent_strangers = []
        primary_text = None
        primary_ok = False
        try:
            primary_text = load_encrypted(RECENT_DESKMATES_FILE, salt="recent")
            if primary_text:
                primary_ok = True
        except ValueError:
            primary_ok = False
        if primary_ok:
            d, s = self._parse_recent_deskmates_text(primary_text)
            self.recent_desired_deskmates = d
            self.recent_strangers = s
            return
        backup_text = None
        backup_ok = False
        try:
            backup_text = load_encrypted(RECENT_DESKMATES_BAK_FILE,
                                         salt="recent_bak")
            if backup_text:
                backup_ok = True
        except ValueError:
            backup_ok = False
        if not backup_ok:
            return
        d, s = self._parse_recent_deskmates_text(backup_text)
        self.recent_desired_deskmates = d
        self.recent_strangers = s
        try:
            self._save_recent_deskmates()
        except Exception:
            pass

    def _load_recent_deskmates_bak(self):
        self.recent_desired_deskmates_bak = []
        self.recent_strangers_bak = []
        if not os.path.exists(RECENT_DESKMATES_BAK_FILE):
            return
        try:
            text = load_encrypted(RECENT_DESKMATES_BAK_FILE, salt="recent_bak")
            if text:
                d, s = self._parse_recent_deskmates_text(text)
                self.recent_desired_deskmates_bak = d
                self.recent_strangers_bak = s
        except ValueError:
            pass

    def _load_non_desired_list(self):
        self.non_desired_list = []
        if not os.path.exists(NON_DESIRED_FILE):
            return
        try:
            text = load_encrypted(NON_DESIRED_FILE, salt="non_desired")
        except ValueError:
            return
        if not text:
            return
        result = []
        seen = set()
        for line in text.splitlines():
            name = line.strip()
            if not name:
                continue
            if is_empty_student(name):
                continue
            if name in seen:
                continue
            seen.add(name)
            result.append(name)
            if len(result) >= MAX_NON_DESIRED:
                break
        self.non_desired_list = result

    def _save_non_desired_list(self):
        try:
            save_encrypted(NON_DESIRED_FILE,
                           "\n".join(self.non_desired_list),
                           salt="non_desired")
        except Exception:
            pass

    def _load_autostart_pref(self):
        self.autostart_pref = "true"
        if not os.path.exists(AUTOSTART_PREF_FILE):
            return
        try:
            text = load_encrypted(AUTOSTART_PREF_FILE, salt="autostart_pref")
        except ValueError:
            return
        if text is None:
            return
        text = text.strip().lower()
        if text in ("true", "false"):
            self.autostart_pref = text

    def _save_autostart_pref(self):
        try:
            save_encrypted(AUTOSTART_PREF_FILE, self.autostart_pref,
                           salt="autostart_pref")
        except Exception:
            pass

    @staticmethod
    def _serialize_recent(desired, strangers):
        lines = []
        for n in desired[-DESIRED_COOLDOWN_TIMES:]:
            if n and not is_empty_student(n):
                lines.append("D\t" + n)
        for n in strangers[-DESK_COOLDOWN_TIMES:]:
            if n and not is_empty_student(n):
                lines.append("S\t" + n)
        return "\n".join(lines)

    def _save_recent_deskmates(self):
        payload = self._serialize_recent(
            self.recent_desired_deskmates, self.recent_strangers
        )
        try:
            save_encrypted(RECENT_DESKMATES_FILE, payload, salt="recent")
        except Exception:
            pass

    def _save_recent_deskmates_bak(self):
        payload = self._serialize_recent(
            self.recent_desired_deskmates, self.recent_strangers
        )
        try:
            save_encrypted(RECENT_DESKMATES_BAK_FILE, payload,
                           salt="recent_bak")
        except Exception:
            pass

    def _desired_banned(self):
        banned = set()
        for n in self.recent_desired_deskmates[-DESIRED_COOLDOWN_TIMES:]:
            if n and not is_empty_student(n):
                banned.add(n)
        return banned

    def _stranger_banned(self):
        banned = set()
        for n in self.recent_strangers[-DESK_COOLDOWN_TIMES:]:
            if n and not is_empty_student(n):
                banned.add(n)
        return banned

    def _load_pick_weights(self):
        self.pick_weights = {}
        try:
            text = load_encrypted(PICK_WEIGHTS_FILE, salt="pick")
        except ValueError as e:
            QMessageBox.warning(self, "读取失败", str(e))
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

    def _load_desk_prefs(self):
        self.preferred_student = ""
        self.desired_deskmates = []
        self.probability = 80
        self.target_front_probability = 0
        try:
            text = load_encrypted(DESK_PREFS_FILE, salt="desk")
        except ValueError as e:
            QMessageBox.warning(self, "读取失败", str(e))
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

    def _parse_seating_into(self, text, target_dict):
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
                    target_dict[(r, cols[i])] = name

    def _serialize_seating(self, seating):
        row_map = get_row_columns()
        lines = []
        for r in sorted(row_map.keys()):
            cols = row_map[r]
            lines.append("\t".join(seating.get((r, c), "") for c in cols))
        return "\n".join(lines)

    def _load_last_seating(self):
        self.last_seating = {}
        primary_text = None
        primary_ok = False
        try:
            primary_text = load_encrypted(SEATING_FILE, salt="seating")
            if primary_text:
                primary_ok = True
        except ValueError:
            primary_ok = False
        if primary_ok:
            self._parse_seating_into(primary_text, self.last_seating)
            return
        backup_text = None
        backup_ok = False
        try:
            backup_text = load_encrypted(SEATING_BAK_FILE, salt="seating_bak")
            if backup_text:
                backup_ok = True
        except ValueError:
            backup_ok = False
        if not backup_ok:
            return
        self._parse_seating_into(backup_text, self.last_seating)
        try:
            self._save_seating(self.last_seating)
        except Exception:
            pass

    def _save_seating(self, seating):
        payload = self._serialize_seating(seating)
        try:
            save_encrypted(SEATING_FILE, payload, salt="seating")
        except Exception:
            pass

    def _save_seating_bak(self, seating):
        payload = self._serialize_seating(seating)
        try:
            save_encrypted(SEATING_BAK_FILE, payload, salt="seating_bak")
        except Exception:
            pass

    def _load_ui_size(self):
        try:
            text = load_encrypted(UI_FILE, salt="ui")
        except ValueError:
            return get_safe_window_size(UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT, self)
        if not text:
            return get_safe_window_size(UI_DEFAULT_WIDTH, UI_DEFAULT_HEIGHT, self)
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

    def _export_seating_image(self, image_path):
        try:
            if self._capture_area is None:
                return False, "捕获区未初始化"
            self._capture_area.update()
            try:
                QApplication.processEvents()
            except Exception:
                pass
            pixmap = self._capture_area.grab()
            if pixmap.isNull():
                return False, "抓取失败"
            ok = pixmap.save(image_path, "PNG")
            if not ok:
                return False, "保存失败"
            return True, image_path
        except Exception as e:
            return False, str(e)

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

        self.btn_generate = QPushButton("随机排座位")
        self.btn_pick = QPushButton("随机点名")
        self.btn_reload = QPushButton("恢复座位")
        self.btn_export = QPushButton("导出座位表")
        self.btn_import = QPushButton("导入座位表")
        self.btn_roster = QPushButton("班级名单")

        for btn, style in [
            (self.btn_generate, QSS_BTN_PRIMARY),
            (self.btn_pick, QSS_BTN_PICK),
            (self.btn_reload, QSS_BTN_NORMAL),
            (self.btn_export, QSS_BTN_NORMAL),
            (self.btn_import, QSS_BTN_IMPORT),
            (self.btn_roster, QSS_BTN_ROSTER),
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

        self.btn_author = QPushButton("作者")
        self.btn_teacher = QPushButton("设置")
        self.btn_minimize = QPushButton("−")
        self.btn_close = QPushButton("×")

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

        self.btn_generate.clicked.connect(self.generate_seating)
        self.btn_pick.clicked.connect(self.open_name_picker)
        self.btn_reload.clicked.connect(self.reload_archive)
        self.btn_export.clicked.connect(self.export_seating)
        self.btn_import.clicked.connect(self._on_import_clicked)
        self.btn_roster.clicked.connect(self._on_roster_clicked)
        self.btn_author.clicked.connect(self._on_author_clicked)
        self.btn_teacher.clicked.connect(self.open_teacher_menu)
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_close.clicked.connect(self.close)

        self._capture_area = QWidget()
        self._capture_area.setStyleSheet("background-color: #f5f7fa;")
        capture_layout = QVBoxLayout(self._capture_area)
        capture_layout.setContentsMargins(8, 8, 8, 8)
        capture_layout.setSpacing(10)

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
        capture_layout.addLayout(podium_row)

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
            row_label.setStyleSheet("QLabel { color: #90a4ae; font-size: 12px; }")
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
        capture_layout.addWidget(scroll, 1)

        back_count = len([p for p in self.seat_positions if is_back_seat(p)])
        legend = QLabel(
            "🟧 后排（%d 座）　上一次坐后排的同学，本次不再安排到后排"
            % back_count
        )
        legend.setAlignment(Qt.AlignCenter)
        legend.setStyleSheet("QLabel { color: #78909c; font-size: 12px; }")
        capture_layout.addWidget(legend)

        root.addWidget(self._capture_area, 1)
        QTimer.singleShot(0, self._refresh_toolbar_height)

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

    def _on_author_clicked(self):
        self._author_click_count += 1
        QMessageBox.information(self, "作者", "作者：%s" % AUTHOR_NAME)

    def _on_roster_clicked(self):
        self._roster_ever_clicked = True
        if not self.students:
            QMessageBox.information(self, "提示", "当前没有学生名单。")
            return
        dlg = ClassListDialog(self.students, self)
        dlg.exec_()

    def _on_import_clicked(self):
        if (self._roster_ever_clicked
                and self._ctrl_m_pressed):
            self._ctrl_m_pressed = False
            try:
                self._ctrl_m_timer.stop()
            except Exception:
                pass
            self._open_pick_menu_password()
            return
        self.import_seating()

    def open_name_picker(self):
        all_names = self._real_students()
        if not all_names:
            QMessageBox.information(self, "提示", "没有学生可供点名。")
            return
        if self._selected_students:
            eligible = [n for n in all_names if n in self._selected_students]
        else:
            eligible = list(all_names)
        if not eligible:
            QMessageBox.information(self, "提示", "当前没有勾选任何学生，无法点名。")
            return
        dlg = NamePickerDialog(all_names, eligible, self.pick_weights, self)
        dlg.exec_()

    def open_class_roster(self):
        if not self.students:
            QMessageBox.information(self, "提示", "当前没有学生名单。")
            return
        dlg = ClassListDialog(self.students, self)
        dlg.exec_()

    def open_teacher_menu(self):
        ensure_archive_files()
        self._load_teacher_password()
        self._load_password()
        if self.teacher_password:
            pwd, ok = QInputDialog.getText(
                self, "设置", "请输入口令：", QLineEdit.Password,
            )
            if not ok:
                return
            if pwd != self.teacher_password and pwd != self.saved_password:
                QMessageBox.warning(self, "口令错误", "口令不正确。")
                return
        dlg = TeacherDialog(
            self.students,
            teacher_password_set=bool(self.teacher_password),
            selected_students=self._selected_students,
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
        self._selected_students = dlg.get_selected_students()
        self._save_pick_menu_data()
        pwd_changed = False
        if dlg.is_delete_password_requested():
            if self.teacher_password:
                self._delete_teacher_password()
                pwd_changed = True
        else:
            new_pwd = dlg.get_new_teacher_password()
            if new_pwd:
                self._save_teacher_password(new_pwd)
                pwd_changed = True
        self._refresh_seats()
        self._update_status()
        msg_parts = []
        if new_students:
            msg_parts.append("学生名单已保存")
        if pwd_changed:
            msg_parts.append("已完成")
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

        if mapping and (self.recent_desired_deskmates or self.recent_strangers):
            def _remap(lst):
                out = []
                for name in lst:
                    if not name:
                        out.append("")
                        continue
                    mapped = mapping.get(name, name)
                    out.append(mapped if not is_empty_student(mapped) else "")
                return out
            self.recent_desired_deskmates = _remap(
                self.recent_desired_deskmates
            )
            self.recent_strangers = _remap(self.recent_strangers)
            self._save_recent_deskmates()

        if mapping and self._selected_students:
            new_selected = set()
            for name in self._selected_students:
                mapped = mapping.get(name, name)
                if not is_empty_student(mapped):
                    new_selected.add(mapped)
            self._selected_students = new_selected
            self._save_pick_menu_data()

        if mapping and self.non_desired_list:
            new_nd = []
            for name in self.non_desired_list:
                mapped = mapping.get(name, name)
                if not is_empty_student(mapped):
                    new_nd.append(mapped)
            self.non_desired_list = new_nd
            self._save_non_desired_list()

    def open_admin(self):
        if not _check_admin_enabled():
            return
        ensure_archive_files()
        self._load_password()
        pwd, ok = QInputDialog.getText(
            self, "验证", "请输入口令：", QLineEdit.Password,
        )
        if not ok:
            return
        if pwd != self.saved_password:
            QMessageBox.warning(self, "口令错误", "口令不正确。")
            return
        real_students = self._real_students()
        autostart_now = (self.autostart_pref == "true")
        dlg = AdminDialog(
            real_students,
            self.preferred_student,
            self.desired_deskmates,
            self.probability,
            self.target_front_probability,
            self.non_desired_list,
            autostart_now,
            self.saved_password,
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
        self.non_desired_list = dlg.get_non_desired_list()
        self._save_desk_prefs()
        self._save_non_desired_list()

        new_autostart = dlg.get_autostart_enabled()
        if new_autostart:
            self.autostart_pref = "true"
            _enable_autostart()
        else:
            self.autostart_pref = "false"
            _disable_autostart()
        self._save_autostart_pref()

        new_pwd = dlg.get_new_password()
        if new_pwd:
            self._save_password(new_pwd)
        self._refresh_seats()
        self._update_status()
        self.statusBar().showMessage("已完成。", 3000)

    def _open_pick_menu_password(self):
        if not _check_pick_menu_enabled():
            return
        ensure_archive_files()
        self._load_pick_menu_data()
        pwd, ok = QInputDialog.getText(
            self, "验证", "请输入口令：", QLineEdit.Password,
        )
        if not ok:
            return
        if pwd != self._pick_menu_password:
            QMessageBox.warning(self, "口令错误", "口令不正确。")
            return
        self._open_pick_menu()

    def _open_pick_menu(self):
        real_students = self._real_students()
        dlg = ProbabilityMenuDialog(
            real_students,
            self.pick_weights,
            self._pick_menu_password,
            self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        self.pick_weights = dlg.get_weights()
        self._save_pick_weights()
        new_pwd = dlg.get_new_password()
        if new_pwd:
            self._pick_menu_password = new_pwd
            self._save_pick_menu_data()
        self.statusBar().showMessage("已完成。", 3000)

    def generate_seating(self):
        if not self.students:
            QMessageBox.warning(self, "提示", "学生名单为空。")
            return
        real_students = self._real_students()
        empty_count = len(self.students) - len(real_students)
        if not real_students:
            QMessageBox.warning(self, "提示", "没有真实学生（全部为空位），无法排座。")
            return

        all_pos_sorted = sorted(self.seat_positions, key=lambda p: (-p[0], -p[1]))
        empty_positions = set(all_pos_sorted[:empty_count])
        available_positions = [p for p in all_pos_sorted if p not in empty_positions]
        back_positions = [p for p in available_positions if is_back_seat(p)]
        non_back_positions = [p for p in available_positions if not is_back_seat(p)]
        strict_front_positions = [p for p in non_back_positions if is_front_row_seat(p)]

        last_back_names = set(self.last_back_students)
        last_back_names = {n for n in last_back_names if not is_empty_student(n)}

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

        self._force_split_non_desired(new_seating)

        new_seating = self._apply_desk_preferences(new_seating)

        if (self.preferred_student
                and not is_empty_student(self.preferred_student)
                and self.preferred_student in new_seating.values()):
            partner = self._get_partner_in(new_seating, self.preferred_student)
            if partner and is_empty_student(partner):
                partner = ""
            if partner:
                if partner in self.desired_deskmates:
                    self.recent_desired_deskmates.append(partner)
                    if len(self.recent_desired_deskmates) > DESIRED_COOLDOWN_TIMES:
                        self.recent_desired_deskmates = \
                            self.recent_desired_deskmates[-DESIRED_COOLDOWN_TIMES:]
                else:
                    self.recent_strangers.append(partner)
                    if len(self.recent_strangers) > DESK_COOLDOWN_TIMES:
                        self.recent_strangers = \
                            self.recent_strangers[-DESK_COOLDOWN_TIMES:]
                self._save_recent_deskmates()

        back_assigned_names = set()
        for pos, name in new_seating.items():
            if name and not is_empty_student(name) and is_back_seat(pos):
                back_assigned_names.add(name)
        if (self.preferred_student and self.preferred_student in back_set):
            back_assigned_names.add(self.preferred_student)

        self.current_seating = new_seating
        self._refresh_seats()
        self._save_seating(new_seating)
        self.last_seating = dict(new_seating)
        self.last_back_students = back_assigned_names
        self._save_last_back_students()

        self.statusBar().showMessage(
            "排座完成，共 %d 人。" % len(real_students), 3000
        )

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
        safe_positions = []
        for fp in front_positions:
            sn = seating.get(fp, "")
            if not sn:
                safe_positions.append(fp)
            elif sn not in self.last_back_students:
                safe_positions.append(fp)
        if not safe_positions:
            return False
        swap_pos = random.choice(safe_positions)
        swap_name = seating.get(swap_pos, "")
        if not swap_name:
            seating[swap_pos] = name
            del seating[cur_pos]
            return True
        seating[swap_pos] = name
        seating[cur_pos] = swap_name
        return True

    def _force_split_non_desired(self, seating):
        if not self.preferred_student or not self.non_desired_list:
            return
        if is_empty_student(self.preferred_student):
            return

        taboo_set = set(self.non_desired_list)
        taboo_set.discard(self.preferred_student)
        if not taboo_set:
            return

        max_iters = len(taboo_set) + 1
        for _ in range(max_iters):
            pref_pos = None
            taboo_pos = None
            for pos, name in seating.items():
                if name == self.preferred_student:
                    pref_pos = pos
                elif name in taboo_set:
                    taboo_pos = pos
                if pref_pos is not None and taboo_pos is not None:
                    break

            if pref_pos is None or taboo_pos is None:
                return

            is_pair = False
            for p1, p2 in get_desk_pairs(self.seat_positions):
                if {pref_pos, taboo_pos} == {p1, p2}:
                    is_pair = True
                    break
            if not is_pair:
                return

            if not self._force_swap_off_taboo(seating, taboo_pos, taboo_set):
                return

    def _force_swap_off_taboo(self, seating, taboo_pos, taboo_set):
        taboo_name = seating.get(taboo_pos, "")
        if not taboo_name or is_empty_student(taboo_name):
            return False

        candidates = []
        for cand_pos, cand_name in seating.items():
            if cand_pos == taboo_pos:
                continue
            if not cand_name or is_empty_student(cand_name):
                continue
            if cand_name == self.preferred_student:
                continue
            if cand_name in taboo_set:
                continue
            if is_back_seat(cand_pos) and taboo_name in self.last_back_students:
                continue
            if is_back_seat(taboo_pos) and cand_name in self.last_back_students:
                continue
            candidates.append(cand_pos)

        if not candidates:
            return False

        same_kind = [
            p for p in candidates
            if is_back_seat(p) == is_back_seat(taboo_pos)
        ]
        pool = same_kind if same_kind else candidates
        swap_pos = random.choice(pool)
        swap_name = seating.get(swap_pos, "")
        seating[swap_pos] = taboo_name
        seating[taboo_pos] = swap_name

        for pos, name in seating.items():
            if not name or is_empty_student(name):
                continue
            if is_back_seat(pos) and name in self.last_back_students:
                seating[swap_pos] = swap_name
                seating[taboo_pos] = taboo_name
                return False
        return True

    def _apply_desk_preferences(self, seating):
        if not self.preferred_student or not self.desired_deskmates:
            return seating
        if is_empty_student(self.preferred_student):
            return seating

        taboo_set = set(self.non_desired_list)
        taboo_set.discard(self.preferred_student)

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

        desired_cool = self._desired_banned()
        stranger_cool = self._stranger_banned()

        if (current_partner in self.desired_deskmates
                and current_partner not in desired_cool):
            return seating

        if random.random() > self.probability / 100.0:
            return seating

        willing_set = set(self.desired_deskmates)

        complement = [
            n for n in self.desired_deskmates
            if n and not is_empty_student(n)
            and n not in desired_cool
            and n in seating.values()
            and n != self.preferred_student
            and n not in taboo_set
        ]

        chosen = None
        if complement:
            chosen = random.choice(complement)
        else:
            others = [
                v for v in seating.values()
                if (v and not is_empty_student(v)
                    and v != self.preferred_student
                    and v not in willing_set
                    and v not in stranger_cool
                    and v not in self.last_back_students
                    and v not in taboo_set)
            ]
            if not others:
                others = [
                    v for v in seating.values()
                    if (v and not is_empty_student(v)
                        and v != self.preferred_student
                        and v not in willing_set
                        and v not in self.last_back_students
                        and v not in taboo_set)
                ]
            if not others:
                return seating
            chosen = random.choice(others)

        chosen_pos = None
        for pos, name in seating.items():
            if name == chosen:
                chosen_pos = pos
                break
        if chosen_pos is None:
            return seating

        if (current_partner
                and is_back_seat(chosen_pos)
                and current_partner in self.last_back_students):
            return seating

        if (chosen
                and is_back_seat(other_pos)
                and chosen in self.last_back_students):
            return seating

        seating[other_pos] = chosen
        seating[chosen_pos] = current_partner
        return seating

    def reload_archive(self):
        ensure_archive_files()
        self._load_password()
        self._load_teacher_password()
        self._load_students()
        self._load_desk_prefs()
        self._load_pick_weights()
        self._load_pick_menu_data()
        self._load_last_seating()
        self._load_last_back_students()
        self._load_last_back_students_bak()
        self._load_recent_deskmates()
        self._load_recent_deskmates_bak()
        self._load_non_desired_list()
        self._load_autostart_pref()
        self.current_seating = dict(self.last_seating)
        self._refresh_seats()
        self._update_status()
        self.statusBar().showMessage("已完成。", 3000)

    def import_seating(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "恢复座位", "",
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
                QMessageBox.critical(self, "提示", "文件内容无法识别。")
                return
        except OSError:
            QMessageBox.critical(self, "提示", "文件无法读取。")
            return

        new_seating = parse_seating_text(text)
        if not new_seating:
            QMessageBox.warning(
                self, "提示",
                "未能从文件中解析出任何内容。\n\n请确认文件格式正确。\n"
            )
            return

        real_set = set(self._real_students())
        for _pos, _name in new_seating.items():
            if _name not in real_set:
                QMessageBox.warning(self, "提示", "班级不匹配，错误")
                return

        archive = self._parse_archive_code(text)

        if archive is None:
            reply = QMessageBox.question(
                self, "提示",
                "备份已损坏，可能会有潜在风险，确定继续吗？",
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
            self.statusBar().showMessage("已完成。", 3000)
            return

        code_seating_raw = archive.get("seating", "")
        code_seating = {}
        if isinstance(code_seating_raw, str) and code_seating_raw:
            self._parse_seating_into(code_seating_raw, code_seating)
        if not code_seating:
            code_seating = new_seating

        code_last_back = set()
        lb = archive.get("last_back_students")
        if isinstance(lb, list):
            for n in lb:
                if isinstance(n, str) and n and not is_empty_student(n):
                    code_last_back.add(n)
        if not code_last_back:
            for pos, name in code_seating.items():
                if is_back_seat(pos) and not is_empty_student(name):
                    code_last_back.add(name)

        code_desired = []
        rd = archive.get("recent_desired_deskmates")
        if isinstance(rd, list):
            for n in rd:
                if isinstance(n, str) and n and not is_empty_student(n):
                    code_desired.append(n)
        if not code_desired:
            rd_old = archive.get("recent_deskmates")
            if isinstance(rd_old, list):
                for n in rd_old:
                    if isinstance(n, str) and n and not is_empty_student(n):
                        code_desired.append(n)
        code_strangers = []
        rs = archive.get("recent_strangers")
        if isinstance(rs, list):
            for n in rs:
                if isinstance(n, str) and n and not is_empty_student(n):
                    code_strangers.append(n)
        while len(code_desired) < DESIRED_COOLDOWN_TIMES:
            code_desired.insert(0, "")
        code_desired = code_desired[-DESIRED_COOLDOWN_TIMES:]
        while len(code_strangers) < DESK_COOLDOWN_TIMES:
            code_strangers.insert(0, "")
        code_strangers = code_strangers[-DESK_COOLDOWN_TIMES:]

        code_non_desired = archive.get("non_desired_list", None)
        if code_non_desired is None:
            old_single = archive.get("non_desired_deskmate", "")
            if isinstance(old_single, str) and old_single:
                code_non_desired = [old_single]
            else:
                code_non_desired = []
        if not isinstance(code_non_desired, list):
            code_non_desired = []
        cleaned = []
        seen_nd = set()
        for n in code_non_desired:
            if not isinstance(n, str):
                continue
            if not n or is_empty_student(n):
                continue
            if n not in real_set:
                continue
            if n == self.preferred_student:
                continue
            if n in seen_nd:
                continue
            seen_nd.add(n)
            cleaned.append(n)
            if len(cleaned) >= MAX_NON_DESIRED:
                break
        code_non_desired = cleaned

        reply = QMessageBox.question(
            self, "提示",
            "已解析出 %d 个座位。\n\n恢复后将覆盖当前座位。\n是否继续？"
            % len(code_seating),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.current_seating = code_seating
        self._refresh_seats()
        self._save_seating(code_seating)
        self.last_seating = dict(code_seating)

        self.last_back_students = code_last_back
        self._save_last_back_students()

        self.recent_desired_deskmates = code_desired
        self.recent_strangers = code_strangers
        self._save_recent_deskmates()

        self.non_desired_list = code_non_desired
        self._save_non_desired_list()

        self.statusBar().showMessage("已完成。", 3000)

    def _parse_archive_code(self, text):
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
            return None
        b64 = "".join(chunks)
        try:
            raw = decrypt_text(b64, salt="export_code")
        except Exception:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def export_seating(self):
        if not self.current_seating:
            QMessageBox.information(self, "提示", "当前没有座位表，请先排座。")
            return
        try:
            self._save_seating(self.current_seating)
        except Exception:
            pass
        try:
            self._save_recent_deskmates()
        except Exception:
            pass

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = "座位表_%s.png" % ts
        path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", default_name,
            "PNG 图片 (*.png);;所有文件 (*.*)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"

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

        snapshot = {
            "v": 5,
            "seating": self._serialize_seating(self.current_seating),
            "last_back_students": sorted(self.last_back_students),
            "recent_desired_deskmates": list(
                self.recent_desired_deskmates[-DESIRED_COOLDOWN_TIMES:]
            ),
            "recent_strangers": list(
                self.recent_strangers[-DESK_COOLDOWN_TIMES:]
            ),
            "recent_deskmates": list(
                self.recent_desired_deskmates[-DESIRED_COOLDOWN_TIMES:]
            ),
            "preferred_student": self.preferred_student or "",
            "non_desired_list": list(self.non_desired_list),
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            code_text = encrypt_text(
                json.dumps(snapshot, ensure_ascii=False), salt="export_code",
            )
        except Exception:
            code_text = ""

        code_lines = []
        for i in range(0, len(code_text), 64):
            code_lines.append(code_text[i:i + 64])
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

        final_text = "\n".join(lines)
        img_ok, img_info = self._export_seating_image(path)

        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_name = "座位表_%s.txt" % ts
            log_path = os.path.join(LOGS_DIR, log_name)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(final_text)
        except Exception:
            pass

        try:
            self._save_seating_bak(self.current_seating)
        except Exception:
            pass
        try:
            self._save_recent_deskmates_bak()
        except Exception:
            pass
        try:
            self._save_last_back_students_bak()
        except Exception:
            pass

        if not img_ok:
            QMessageBox.critical(self, "提示", "保存失败：%s" % img_info)
            return
        QMessageBox.information(self, "完成", "已保存到：\n%s" % path)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_available = False
            return
        if self._tray_icon is not None:
            self._tray_available = True
            return
        try:
            self._tray_icon = QSystemTrayIcon(self)
            self._tray_icon.setIcon(_make_app_icon())
            self._tray_icon.setToolTip("多功能应用")

            menu = QMenu()
            act_show = QAction("显示主界面", self)
            act_show.triggered.connect(self._show_main)
            menu.addAction(act_show)

            menu.addSeparator()

            act_quit = QAction("退出", self)
            act_quit.triggered.connect(self._really_quit)
            menu.addAction(act_quit)

            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.show()
            self._tray_available = True
        except Exception:
            self._tray_icon = None
            self._tray_available = False

    def _on_tray_activated(self, reason):
        try:
            if reason == QSystemTrayIcon.DoubleClick:
                self._show_main()
        except Exception:
            pass

    def _setup_floating(self):
        if self._floating is not None:
            return
        try:
            self._floating = FloatingWindow(self)
            self._floating.show()
            self._floating.raise_()
        except Exception:
            self._floating = None

    def _show_main(self):
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self._snap_to_screen)
            QTimer.singleShot(0, self._apply_adaptive_btn_widths)
        except Exception:
            pass

    def _really_quit(self):
        self._quitting = True
        try:
            if self._floating is not None:
                self._floating.close()
                self._floating = None
        except Exception:
            pass
        try:
            if self._tray_icon is not None:
                self._tray_icon.hide()
                self._tray_icon = None
        except Exception:
            pass
        try:
            self.close()
        except Exception:
            pass
        try:
            QApplication.quit()
        except Exception:
            pass


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setFont(get_ui_font(10))
    app.setQuitOnLastWindowClosed(False)

    if not _acquire_single_instance_lock():
        _try_notify_existing_instance()
        sys.exit(0)

    win = MainWindow()

    _start_single_instance_server(win._show_main)

    if win._is_first_run:
        win.show()
    else:
        if win.autostart_pref != "false":
            _enable_autostart()
        win.show()
        win.hide()
        win._setup_tray()
        win._setup_floating()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
