# SeatApp 代码保护与打包指南

> 面向 Python 桌面程序的代码混淆、加密与 exe 封装完整方案。
> 目标：**反编译难度最大化** + **一键打包** 

---

## 目录

- [一、方案对比](#一方案对比)
- [二、推荐方案 Nuitka](#二推荐方案-nuitka)
- [三、备选方案 PyArmor + PyInstaller](#三备选方案-pyarmor--pyinstaller)
- [四、注释剥离脚本](#四注释剥离脚本)
- [五、一键构建脚本 build.py](#五一键构建脚本-buildpy)
- [六、一体化构建工具 seat_build_tool.py](#六一体化构建工具-seat_build_toolpy)
- [七、安全性评估](#七安全性评估)
- [八、额外建议](#八额外建议)
- [九、一句话总结](#九一句话总结)

---

## 一、方案对比

| 方案 | 反编译难度 | 打包 exe | 适用性 | 推荐度 |
|---|---|---|---|---|
| **PyInstaller 裸打包** | ⭐ 极低（uncompyle6 一键还原） | ✅ | 只防小白 | ❌ |
| **PyArmor + PyInstaller** | ⭐⭐⭐⭐ 高 | ✅ | 商业软件常用 | ✅✅✅ |
| **Nuitka standalone** | ⭐⭐⭐⭐⭐ 极高（C 编译） | ✅ | 最强 | ✅✅✅✅ |
| **Cython 关键模块** | ⭐⭐⭐⭐⭐ 极高 | ✅ 配合 PyInstaller | 只保护核心逻辑 | ✅ |

**不要做的事：**

- ❌ 用 `base64` 或 `zlib` 编码源码再 `exec`——一行代码就还原
- ❌ 用 `py_compile` 只生成 `.pyc`——uncompyle6 秒反

---

## 二、推荐方案 Nuitka

Nuitka 把 Python 编译成 C，再编译成 exe。**反编译需要反汇编机器码，实战中没人干。**

### 2.1 环境准备

```powershell
# 安装 Nuitka
pip install nuitka

# Windows 上还需要：
# 1) 安装 Visual Studio Build Tools（勾选"使用 C++ 的桌面开发"）
#    https://visualstudio.microsoft.com/visual-cpp-build-tools/
# 2) 安装 ccache（可选，加速重复编译）
```

### 2.2 一键编译

在源文件所在目录打开 PowerShell：

```powershell
python -m nuitka --standalone --onefile --windows-console-mode=disable --windows-icon-from-ico=1.ico --company-name=G2504电教 --product-name=多功能应用 --file-version=9.1.7.8 --product-version=6.7.6.7 --output-dir=build --output-filename=SeatApp.exe --remove-output --assume-yes-for-downloads --python-flag=-OO --lto=yes --enable-plugin=pyqt5 --include-qt-plugins=sensible,styles seat_app_C.py
```

**参数说明：**

| 参数 | 作用 |
|---|---|
| `--standalone` | 打包所有依赖，独立运行 |
| `--onefile` | 打成单个 exe |
| `--windows-console-mode=disable` | 隐藏黑框（GUI 程序必备） |
| `--windows-icon-from-ico` | 指定图标 |
| `--output-dir=build` | 输出目录 |
| `--remove-output` | 编译完删中间文件 |
| `--python-flag=-OO` | 去掉 docstring 和 assert |
| `--lto=yes` | 链接时优化，进一步混淆符号 |
| `--plugin-enable=qt-plugins` | PyQt5 插件自动处理 |

编译产物：`build/SeatApp.exe`，约 **40–80 MB**（带 Python 运行时和 cryptography 库）。

### 2.3 减小体积（可选）

介意体积和启动速度的话，去掉 `--onefile`，改成 `--standalone`，出一个文件夹，**启动飞快**：

```powershell
python -m nuitka --standalone --windows-console-mode=disable seat_app_C.py
```

产物是一个文件夹，双击里面的 `seat_app_C.exe` 即可。

---

## 三、备选方案 PyArmor + PyInstaller

如果嫌 Nuitka 编译太慢（几分钟），可以用 PyArmor。**注意要装 8.x 版本，旧版有已知绕过。**

### 3.1 环境

```powershell
pip install pyarmor==8.5.11
pip install pyinstaller
```

### 3.2 混淆 + 打包

```powershell
# 第一步：混淆（生成 obfuscated/ 目录，源码变密文）
pyarmor gen -O obfuscated --enable-jit --enable-bcc seat_app_C.py

# 第二步：用混淆后的代码打包
pyinstaller --onefile --windowed ^
    --name SeatApp ^
    --icon app.ico ^
    --distpath build ^
    obfuscated/seat_app_C.py
```

产物：`build/SeatApp.exe`，PyArmor 的运行时会在启动时解密字节码。

---

## 四、注释剥离脚本

**Nuitka 和 PyArmor 都会自动剥离注释**，这一步只在你想手动给源码"净化"时使用。

`strip_comments.py`：

```python
# -*- coding: utf-8 -*-
"""
用 AST 剥离注释和 docstring，保留代码逻辑。
用法：
    python strip_comments.py seat_app_C.py seat_app_C_clean.py
"""
import ast
import sys


def strip(src_path, out_path):
    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    # 移除所有 docstring
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    # unparse 会丢掉所有注释
    cleaned = ast.unparse(tree)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write(cleaned)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python strip_comments.py <输入.py> <输出.py>")
        sys.exit(1)
    strip(sys.argv[1], sys.argv[2])
```

用法：

```powershell
python strip_comments.py seat_app_C.py seat_app_C_clean.py
```

**⚠️ 警告：** `ast.unparse` 会重新格式化代码（缩进、括号风格全变），可能影响 `%` 格式化字符串中依赖原格式的位置。**建议只用来做展示，不要拿去跑。**

---

## 五、一键构建脚本 build.py

把 Nuitka + PyArmor + 清理合到一个脚本里。

```python
# -*- coding: utf-8 -*-
"""
SeatApp 一键构建脚本
============================================================
用法：
    python build.py              # 默认用 Nuitka
    python build.py --pyarmor    # 改用 PyArmor + PyInstaller
    python build.py --clean      # 清理构建目录
"""
import os
import sys
import shutil
import subprocess
import argparse

SRC = "seat_app_C.py"
APP_NAME = "SeatApp"
VERSION = "1.0.0"
ICON = "app.ico"            # 没有图标就改成 None
BUILD_DIR = "build"
DIST_DIR = "dist"
OBFUSCATED_DIR = "obfuscated"


def run(cmd):
    print("\n>>> " + " ".join(cmd))
    ret = subprocess.call(cmd, shell=False)
    if ret != 0:
        print("[错误] 命令失败，退出码 %d" % ret)
        sys.exit(ret)


def clean():
    for d in (BUILD_DIR, DIST_DIR, OBFUSCATED_DIR, SRC + ".build",
              SRC + ".dist", SRC + ".onefile-build"):
        if os.path.isdir(d):
            print("[清理] " + d)
            shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            print("[清理] " + f)
            os.remove(f)


def build_nuitka():
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile",
        "--windows-console-mode=disable",
        "--company-name=G2504",
        "--product-name=" + APP_NAME,
        "--file-version=" + VERSION + ".0",
        "--product-version=" + VERSION + ".0",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=" + APP_NAME + ".exe",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--python-flag=-OO",
        "--lto=yes",
        "--plugin-enable=qt-plugins",
    ]
    if ICON and os.path.isfile(ICON):
        cmd.append("--windows-icon-from-ico=" + ICON)
    cmd.append(SRC)
    run(cmd)
    print("\n[完成] " + os.path.join(BUILD_DIR, APP_NAME + ".exe"))


def build_pyarmor():
    # 第 1 步：PyArmor 混淆
    run([sys.executable, "-m", "pyarmor", "gen",
         "-O", OBFUSCATED_DIR,
         "--enable-jit", "--enable-bcc",
         SRC])

    # 第 2 步：PyInstaller 打包
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", BUILD_DIR,
        "--workpath", BUILD_DIR + "/_work",
        "--specpath", BUILD_DIR + "/_spec",
        "--noconfirm",
    ]
    if ICON and os.path.isfile(ICON):
        cmd += ["--icon", ICON]
    cmd.append(os.path.join(OBFUSCATED_DIR, SRC))
    run(cmd)
    print("\n[完成] " + os.path.join(BUILD_DIR, APP_NAME + ".exe"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pyarmor", action="store_true",
                    help="使用 PyArmor + PyInstaller 方案")
    ap.add_argument("--clean", action="store_true",
                    help="清理构建产物后退出")
    args = ap.parse_args()

    if not os.path.isfile(SRC):
        print("[错误] 找不到源文件：" + SRC)
        sys.exit(1)

    if args.clean:
        clean()
        return

    if args.pyarmor:
        build_pyarmor()
    else:
        build_nuitka()


if __name__ == "__main__":
    main()
```

用法：

```powershell
# 最强保护（推荐）
python build.py

# 快速构建（几分钟搞定）
python build.py --pyarmor

# 清理
python build.py --clean
```

---

## 六、一体化构建工具 seat_build_tool.py

一个文件搞定所有事：**剥离注释 + Nuitka 打包 + PyArmor 打包 + 生成 README + 清理**。

```python
# -*- coding: utf-8 -*-
"""
SeatApp 构建工具（一体化）
============================================================
功能：
    strip     剥离源码注释与 docstring（AST 重写）
    build     用 Nuitka 编译成 exe（最强保护，推荐）
    pyarmor   用 PyArmor + PyInstaller 打包（编译快）
    readme    生成 README.md
    clean     清理所有构建产物
    all       一条命令走完：strip → build → readme

用法示例：
    python seat_build_tool.py strip
    python seat_build_tool.py build
    python seat_build_tool.py pyarmor
    python seat_build_tool.py readme
    python seat_build_tool.py clean
    python seat_build_tool.py all

配置：
    改下面的 SRC / APP_NAME / VERSION / ICON 即可。
============================================================
"""
import os
import sys
import ast
import shutil
import argparse
import subprocess


# ============================================================
#  ⚙️  配置区
# ============================================================
SRC = "seat_app_C.py"           # 源文件
APP_NAME = "SeatApp"            # 生成的 exe 名（不含 .exe）
VERSION = "1.0.0"               # 版本号
ICON = "app.ico"                # 图标文件；没有就填 None
BUILD_DIR = "build"             # 输出目录
OBFUSCATED_DIR = "obfuscated"   # PyArmor 中间产物
CLEAN_SRC = "seat_app_C_clean.py"   # strip 后的源码文件名


# ============================================================
#  🛠️  通用工具
# ============================================================
def _run(cmd, shell=False):
    print("\n>>> " + (" ".join(cmd) if isinstance(cmd, list) else cmd))
    ret = subprocess.call(cmd, shell=shell)
    if ret != 0:
        print("[错误] 命令失败，退出码 %d" % ret)
        sys.exit(ret)


def _need_file(path):
    if not os.path.isfile(path):
        print("[错误] 找不到文件：%s" % path)
        sys.exit(1)


# ============================================================
#  🧹  strip —— 剥离注释与 docstring
# ============================================================
def cmd_strip():
    """
    用 AST 解析源码，移除所有 docstring，unparse 后写出。
    注意：unparse 会重新格式化代码（缩进、括号风格改变），
          可能影响 `%` 格式化字符串中依赖原格式的位置。
          仅用于「净化」或展示，不建议直接拿来跑主程序。
    """
    _need_file(SRC)
    with open(SRC, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)

    # 移除所有 docstring
    removed = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
                removed += 1

    cleaned = ast.unparse(tree)

    with open(CLEAN_SRC, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write(cleaned)

    print("\n[完成] 已剥离 %d 个 docstring" % removed)
    print("[输出] %s（%d 字节）" % (CLEAN_SRC, os.path.getsize(CLEAN_SRC)))


# ============================================================
#  🚀  build —— Nuitka 编译
# ============================================================
def cmd_build():
    """
    用 Nuitka 把源码编译成 C，再编译成 exe。
    反编译难度极高，实战中几乎无人能破。
    """
    _need_file(SRC)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile",
        "--windows-console-mode=disable",
        "--company-name=G2504",
        "--product-name=" + APP_NAME,
        "--file-version=" + VERSION + ".0",
        "--product-version=" + VERSION + ".0",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=" + APP_NAME + ".exe",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--python-flag=-OO",
        "--lto=yes",
        "--plugin-enable=qt-plugins",
    ]
    if ICON and os.path.isfile(ICON):
        cmd.append("--windows-icon-from-ico=" + ICON)
    cmd.append(SRC)

    _run(cmd)

    out = os.path.join(BUILD_DIR, APP_NAME + ".exe")
    if os.path.isfile(out):
        size_mb = os.path.getsize(out) / 1024.0 / 1024.0
        print("\n[完成] %s（%.1f MB）" % (out, size_mb))
    else:
        print("\n[完成] 编译结束，请检查 %s 目录" % BUILD_DIR)


# ============================================================
#  🚀  pyarmor —— PyArmor + PyInstaller
# ============================================================
def cmd_pyarmor():
    """
    先用 PyArmor 混淆源码，再用 PyInstaller 打包。
    编译速度快，但保护强度略低于 Nuitka。
    """
    _need_file(SRC)

    # 第 1 步：PyArmor 混淆
    _run([sys.executable, "-m", "pyarmor", "gen",
          "-O", OBFUSCATED_DIR,
          "--enable-jit", "--enable-bcc",
          SRC])

    # 第 2 步：PyInstaller 打包
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", BUILD_DIR,
        "--workpath", os.path.join(BUILD_DIR, "_work"),
        "--specpath", os.path.join(BUILD_DIR, "_spec"),
        "--noconfirm",
    ]
    if ICON and os.path.isfile(ICON):
        cmd += ["--icon", ICON]
    cmd.append(os.path.join(OBFUSCATED_DIR, SRC))
    _run(cmd)

    out = os.path.join(BUILD_DIR, APP_NAME + ".exe")
    if os.path.isfile(out):
        size_mb = os.path.getsize(out) / 1024.0 / 1024.0
        print("\n[完成] %s（%.1f MB）" % (out, size_mb))
    else:
        print("\n[完成] 打包结束，请检查 %s 目录" % BUILD_DIR)


# ============================================================
#  📄  readme —— 生成 README.md
# ============================================================
README_TEXT = """# SeatApp 代码保护与打包指南

> 面向 {src} 的代码混淆、加密与 exe 封装完整方案。

## 快速开始

    python seat_build_tool.py strip
    python seat_build_tool.py build
    python seat_build_tool.py pyarmor
    python seat_build_tool.py readme
    python seat_build_tool.py clean
    python seat_build_tool.py all
"""


def cmd_readme():
    """生成 README.md"""
    text = README_TEXT.format(src=SRC, app=APP_NAME)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(text)
    print("\n[完成] 已生成 README.md（%d 字节）" % os.path.getsize("README.md"))


# ============================================================
#  🧽  clean —— 清理构建产物
# ============================================================
def cmd_clean():
    """删除所有构建产物，恢复到干净状态。"""
    targets = [
        BUILD_DIR,
        OBFUSCATED_DIR,
        "__pycache__",
        SRC + ".build",
        SRC + ".dist",
        SRC + ".onefile-build",
        APP_NAME + ".build",
        APP_NAME + ".dist",
        APP_NAME + ".onefile-build",
    ]
    for d in targets:
        if os.path.isdir(d):
            print("[清理] " + d)
            shutil.rmtree(d, ignore_errors=True)

    # 清理 .spec 文件
    for f in os.listdir("."):
        if f.endswith(".spec"):
            print("[清理] " + f)
            try:
                os.remove(f)
            except Exception:
                pass

    # 清理 strip 后的源码（可选）
    if os.path.isfile(CLEAN_SRC):
        ans = input("是否删除 %s ？（y/N）: " % CLEAN_SRC).strip().lower()
        if ans == "y":
            os.remove(CLEAN_SRC)
            print("[清理] " + CLEAN_SRC)

    print("\n[完成] 清理结束。")


# ============================================================
#  🎯  all —— 全流程
# ============================================================
def cmd_all():
    """strip → build → readme"""
    print("=" * 60)
    print("  全流程：strip → build → readme")
    print("=" * 60)
    cmd_strip()
    cmd_build()
    cmd_readme()
    print("\n" + "=" * 60)
    print("  全部完成")
    print("=" * 60)


# ============================================================
#  🚀  入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="SeatApp 构建工具（一体化）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    python seat_build_tool.py strip        # 剥离注释
    python seat_build_tool.py build        # Nuitka 编译
    python seat_build_tool.py pyarmor      # PyArmor 打包
    python seat_build_tool.py readme       # 生成 README
    python seat_build_tool.py clean        # 清理产物
    python seat_build_tool.py all          # 全流程
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("strip", help="剥离源码注释与 docstring")
    sub.add_parser("build", help="用 Nuitka 编译成 exe（推荐）")
    sub.add_parser("pyarmor", help="用 PyArmor + PyInstaller 打包")
    sub.add_parser("readme", help="生成 README.md")
    sub.add_parser("clean", help="清理所有构建产物")
    sub.add_parser("all", help="strip → build → readme")

    args = parser.parse_args()

    dispatch = {
        "strip": cmd_strip,
        "build": cmd_build,
        "pyarmor": cmd_pyarmor,
        "readme": cmd_readme,
        "clean": cmd_clean,
        "all": cmd_all,
    }
    dispatch[args.cmd]()


if __name__ == "__main__":
    main()
```

### 6.1 使用说明

**放在 `seat_app_C.py` 同目录**，然后：

```powershell
# 1) 剥离注释（生成 seat_app_C_clean.py）
python seat_build_tool.py strip

# 2) Nuitka 编译成 exe（推荐）
python seat_build_tool.py build

# 3) 生成 README.md
python seat_build_tool.py readme

# 4) 一键全流程
python seat_build_tool.py all

# 5) 清理所有构建产物
python seat_build_tool.py clean
```

### 6.2 目录结构（运行后）

```
你的工作目录/
├── seat_app_C.py               ← 原始源码
├── seat_app_C_clean.py         ← strip 后的无注释版
├── seat_build_tool.py          ← 本工具
├── README.md                   ← 生成的说明文档
├── build/
│   └── SeatApp.exe             ← 最终可执行文件
├── obfuscated/                 ← PyArmor 中间产物（仅 pyarmor 模式）
└── __pycache__/                ← Python 缓存
```

### 6.3 关键设计

| 设计 | 说明 |
|---|---|
| **单文件无依赖** | 只用标准库 `os / sys / ast / shutil / argparse / subprocess`，无需额外 pip 安装 |
| **配置集中** | 文件顶部 `SRC / APP_NAME / VERSION / ICON` 一处修改 |
| **子命令式** | `strip / build / pyarmor / readme / clean / all` 六个动作 |
| **README 内嵌** | `README_TEXT` 常量里直接维护，`readme` 命令写文件 |
| **安全退出** | 任一编译步骤失败立即 `sys.exit`，不会留下半成品 |
| **清理智能** | 自动识别并删除 `.spec / .build / .dist / __pycache__` 等中间产物 |

改 `SRC = "seat_app_C.py"` 就能用于任何其他 Python 项目，通用型构建工具。

---

## 七、安全性评估

| 攻击者 | Nuitka | PyArmor |
|---|---|---|
| 普通用户双击 exe 想改个密码 | ✅ 完全防住 | ✅ 完全防住 |
| 会用 `uncompyle6` 反编译 pyc | ✅ 完全防住 | ✅ 完全防住 |
| 会用 `pyinstxtractor` 拆包 | ✅ 完全防住 | ⚠️ 能拆出加密的 pyc，但解不开 |
| 会用 `ghidra` 反汇编机器码 | ⚠️ 能反汇编，但读懂逻辑耗时极大 | ❌ 需要脱壳（难） |
| 有无限时间和资源的专业逆向 | ❌ 理论上总能破 | ❌ 理论上总能破 |

---

## 八、额外建议

### 8.1 别把密码写死在 exe 里

如果代码里有明文常量（比如 `MASTER_PASSPHRASE`），Nuitka 编译后是只读数据段，用 `strings` 能扫出来。

**改成从环境变量读取：**

```python
import os
MASTER_PASSPHRASE = os.environ.get("SEAT_MASTER_KEY", "").encode("utf-8")
if not MASTER_PASSPHRASE:
    raise SystemExit("请先设置环境变量 SEAT_MASTER_KEY")
```

### 8.2 主密钥随机化

`.dat` 文件加密密钥同理——硬编码的密钥能扫出来。

真要防，改成**首次运行时随机生成一个主密钥**存到用户目录，然后用它加密：

```python
import os
import secrets

KEY_PATH = os.path.join(os.path.expanduser("~"), ".JiXiu", ".key")

def load_or_create_master_key():
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            return f.read()
    key = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    return key
```

### 8.3 cryptography 库的坑

`cryptography` 有 C 扩展，Nuitka 处理起来比较麻烦，**打包机器上先装好 `cryptography` 的 wheel**。

### 8.4 打包体积与启动速度

- `--onefile`：单文件，首次启动解压到临时目录，**约 2–4 秒**
- `--standalone`：文件夹形式，**启动飞快**，但要整体分发

按需求取舍。

---

## 九、一句话总结

> 用 Nuitka `--onefile --standalone` 一条命令就能编译成 exe，**自动去掉注释、反编译难度极高**，是当前 Python 桌面程序最强的保护方案。
