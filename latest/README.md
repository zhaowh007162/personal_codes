# SeatApp 代码保护与打包指南

> 面向 Python 桌面程序的代码混淆、加密与 exe 封装完整方案。
> 目标：**反编译难度最大化** + **一键打包** + **删除所有注释**。

---

## 目录

- [一、方案对比](#一方案对比)
- [二、推荐方案：Nuitka](#二推荐方案nuitka)
- [三、备选方案：PyArmor + PyInstaller](#三备选方案pyarmor--pyinstaller)
- [四、注释剥离](#四注释剥离)
- [五、安全性评估](#五安全性评估)
- [六、额外建议](#六额外建议)
- [七、一句话总结](#七一句话总结)

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

## 二、推荐方案：Nuitka

Nuitka 把 Python 编译成 C，再编译成 exe。**反编译需要反汇编机器码，实战中没人干。**

### 2.1 环境准备

```powershell
# 安装 Nuitka
pip install nuitka

# Windows 上还需要：
# 1) 安装 Visual Studio Build Tools（勾选"使用 C++ 的桌面开发"）
#    https://visualstudio.microsoft.com/visual-cpp-build-tools/
# 2) 安装 ccache（可选，加速重复编译）
