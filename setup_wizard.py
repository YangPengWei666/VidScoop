# -*- coding: utf-8 -*-
"""VidScoop 配置向导 —— 交互式生成 .env 配置文件

用法：双击「配置向导.bat」（它会调用本脚本）
直接运行：python setup_wizard.py
"""
import os
import sys
import re

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, ".env")


def line(ch="─", n=54):
    print(ch * n)


def title(text):
    print()
    line("═")
    print(f"  {text}")
    line("═")


def ask(prompt, default="", required=False, validator=None, hint=None):
    """反复询问直到拿到有效输入。"""
    while True:
        if hint:
            print(f"  {hint}")
        s = input(f"  {prompt}" + (f"（默认 {default}）" if default else "") + "：").strip()
        if not s:
            if default:
                return default
            if required:
                print("  ⚠ 这一项必填，不能跳过。\n")
                continue
            return ""
        if validator:
            ok, msg = validator(s)
            if not ok:
                print(f"  ⚠ {msg}\n")
                continue
        return s


def v_groq(s):
    if not s.startswith("gsk_"):
        return False, "Groq 的 Key 应该以 gsk_ 开头，请检查是不是复制错了"
    if len(s) < 20:
        return False, "这串太短了，看起来不完整"
    return True, ""


def v_sf(s):
    if not s.startswith("sk-"):
        return False, "硅基流动的 Key 应该以 sk- 开头，请检查"
    if len(s) < 20:
        return False, "这串太短了，看起来不完整"
    return True, ""


def v_path(s):
    p = s.replace("\\", "/").rstrip("/")
    # 检查盘符格式
    if not re.match(r"^[A-Za-z]:/", p) and not p.startswith("/"):
        return False, "请填完整路径，例如 D:/我的笔记"
    return True, ""


def main():
    print()
    print("  VidScoop · 配置向导")
    print("  这个向导会帮你生成配置文件，不用手动编辑任何东西。")
    print()

    # ---- 已有配置？ ----
    if os.path.exists(ENV_PATH):
        print(f"  检测到已有配置文件：{ENV_PATH}")
        ans = input("  要重新配置并覆盖吗？(y/N)：").strip().lower()
        if ans != "y":
            print("\n  已取消，保留原配置。")
            print("  如果你想修改，可以直接编辑 .env 文件，或者删掉它再跑一次本向导。")
            return 0

    # ---- 第 1 步：Groq ----
    title("第 1 步 / 共 3 步：Groq API Key")
    print()
    print("  这是做什么的：把转写出来的文字整理通顺、并生成摘要。")
    print()
    print("  怎么获取：")
    print("    1. 浏览器打开  https://console.groq.com/keys")
    print("    2. 注册（用邮箱或 Google 账号都行，需要能上国际网）")
    print("    3. 登录后点「Create Key」")
    print("    4. 复制那串 gsk_ 开头的字符")
    print()
    print("  ⚠ 这个 Key 关掉页面就看不到了，拿到后立刻贴进来。")
    print()
    groq_key = ask("粘贴 Groq Key", required=True, validator=v_groq)

    # ---- 第 2 步：硅基流动 ----
    title("第 2 步 / 共 3 步：硅基流动 API Key")
    print()
    print("  这是做什么的：把视频里的声音转成文字（语音转写）。")
    print()
    print("  怎么获取：")
    print("    1. 浏览器打开  https://cloud.siliconflow.cn/account/ak")
    print("    2. 注册（需要手机号实名认证）")
    print("    3. 登录后进「API 密钥」页面")
    print("    4. 点「新建 API 密钥」，复制 sk- 开头的那串")
    print()
    sf_key = ask("粘贴硅基流动 Key", required=True, validator=v_sf)

    # ---- 第 3 步：保存路径 ----
    title("第 3 步 / 共 3 步：笔记保存到哪里")
    print()
    print("  转出来的笔记会存到这个文件夹下的 00-Clip 子目录里。")
    print("  如果你用 Obsidian，就填你笔记库的根目录。")
    print("  不用 Obsidian 也行，随便找个文件夹。")
    print()
    print("  注意：路径用正斜杠，例如  D:/我的笔记")
    print()
    note_dir = ask("保存路径", default="D:/VidScoop笔记", validator=v_path)
    note_dir = note_dir.replace("\\", "/").rstrip("/")

    # ---- 写入 ----
    title("正在保存配置")
    try:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("# VidScoop 配置（由配置向导生成）\n")
            f.write("# 这个文件含密钥，不要分享给别人，也不要上传到网上\n\n")
            f.write("# ===== API Key =====\n")
            f.write(f"GROQ_API_KEY={groq_key}\n")
            f.write(f"SILICONFLOW_API_KEY={sf_key}\n\n")
            f.write("# ===== 笔记保存位置 =====\n")
            f.write(f"VAULT_DIR={note_dir}\n")
    except Exception as e:
        print(f"\n  ✗ 写入失败：{e}")
        print("    请检查项目文件夹的写入权限，或以管理员身份重试。")
        return 1

    print(f"\n  ✓ 已保存到：{ENV_PATH}")

    # ---- 验证 ----
    title("验证配置")
    ok = True
    try:
        sys.path.insert(0, BASE)
        # 强制重新读取（避免已被 import 过）
        for k in list(os.environ.keys()):
            if k in ("GROQ_API_KEY", "SILICONFLOW_API_KEY", "VAULT_DIR"):
                del os.environ[k]
        from localbot import config
        import importlib
        importlib.reload(config)

        print(f"  Groq Key      ：{'✓ 已读取' if config.GROQ_API_KEY else '✗ 未读到'}")
        print(f"  硅基流动 Key  ：{'✓ 已读取' if config.SILICONFLOW_API_KEY else '✗ 未读到'}")
        print(f"  保存路径      ：{config.VAULT_DIR or '✗ 未读到'}")

        if not config.GROQ_API_KEY or not config.SILICONFLOW_API_KEY:
            ok = False
    except Exception as e:
        print(f"  ⚠ 无法自动验证（可能虚拟环境还没装好）：{e}")
        ok = None

    # ---- 创建保存目录 ----
    try:
        target = os.path.join(note_dir, "00-Clip")
        os.makedirs(target, exist_ok=True)
        print(f"  ✓ 保存目录已就绪：{target}")
    except Exception as e:
        print(f"  ⚠ 无法创建保存目录：{e}")
        print("    请确认路径正确，或手动建好这个文件夹。")

    # ---- 结尾 ----
    print()
    line("═")
    if ok is False:
        print("  ⚠ 配置写好了，但读取验证没通过。")
        print("     通常是虚拟环境还没装好，先跑一遍「安装本地助手.bat」。")
    elif ok is None:
        print("  ✓ 配置文件已生成（未能自动验证，请按下面步骤继续）")
    else:
        print("  ✓ 配置完成")
    line("═")
    print()
    print("  接下来：")
    print("    1. 如果还没安装环境 → 双击「安装本地助手.bat」")
    print("    2. 加载浏览器扩展 → 按 README「第三步」操作")
    print("    3. 打开 B站 / YouTube 视频页 → 点右侧悬浮按钮")
    print()
    return 0 if ok is not False else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  已取消。")
        sys.exit(130)
