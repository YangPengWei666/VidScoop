@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
set "DIR=%~dp0"
title VidScoop 配置向导

echo ============================================
echo            VidScoop 配置向导
echo ============================================
echo.
echo 这个向导会帮你生成配置文件，不用手动编辑。
echo 需要提前准备两个免费的 API Key（申请地址见 README）。
echo.
echo 按任意键开始，或直接关窗口退出。
pause >nul
echo.

rem ---------- 检查是否已有配置 ----------
if exist "%DIR%.env" (
  echo [提示] 检测到已有 .env 配置文件。
  set /p OVERWRITE=是否重新配置并覆盖？(y/N):
  if /i not "!OVERWRITE!"=="y" (
    echo 已取消，保留原配置。
    pause & exit /b 0
  )
  echo.
)

rem ---------- Groq Key ----------
echo ---------------------------------------------
echo 第 1 步：Groq API Key
echo ---------------------------------------------
echo 申请地址：https://console.groq.com/keys
echo 注册后点 Create Key，复制以 gsk_ 开头的那串
echo.
:INPUT_GROQ
set /p GROQ_KEY=请粘贴 Groq Key（留空退出）:
if "!GROQ_KEY!"=="" (
  echo 已取消。
  pause & exit /b 1
)
rem 用字符串截取判断前缀，避免特殊字符问题
set "PRE=!GROQ_KEY:~0,4!"
if /i not "!PRE!"=="gsk_" (
  echo [警告] 这不像 Groq 的 Key（通常以 gsk_ 开头），请重新输入。
  echo.
  goto INPUT_GROQ
)
echo [完成] 已记录。
echo.

rem ---------- 硅基流动 Key ----------
echo ---------------------------------------------
echo 第 2 步：硅基流动 API Key
echo ---------------------------------------------
echo 申请地址：https://cloud.siliconflow.cn/account/ak
echo 注册需要手机号实名，完成后点「新建 API 密钥」
echo.
:INPUT_SF
set /p SF_KEY=请粘贴硅基流动 Key（留空退出）:
if "!SF_KEY!"=="" (
  echo 已取消。
  pause & exit /b 1
)
set "PRE2=!SF_KEY:~0,3!"
if /i not "!PRE2!"=="sk-" (
  echo [警告] 这不像硅基流动的 Key（通常以 sk- 开头），请重新输入。
  echo.
  goto INPUT_SF
)
echo [完成] 已记录。
echo.

rem ---------- 笔记保存路径 ----------
echo ---------------------------------------------
echo 第 3 步：笔记保存位置
echo ---------------------------------------------
echo 笔记会存到「你填的目录/00-Clip/」文件夹里。
echo 用 Obsidian 就填库的根目录，不用也行。
echo 注意：路径请用正斜杠，例如 D:/我的笔记
echo.
:INPUT_DIR
set /p NOTE_DIR=请粘贴保存路径（留空使用默认 D:/VidScoop笔记）:
if "!NOTE_DIR!"=="" set "NOTE_DIR=D:/VidScoop笔记"
rem 反斜杠转换成正斜杠
set "NOTE_DIR=!NOTE_DIR:\=/!"
echo [完成] 笔记将保存到：!NOTE_DIR!/00-Clip/
echo.

rem ---------- 生成 .env ----------
echo ---------------------------------------------
echo 正在写入配置文件...
echo ---------------------------------------------

> "%DIR%.env" (
  echo # VidScoop 配置（由配置向导生成）
  echo # 生成时间：%date% %time%
  echo.
  echo # ===== API Key =====
  echo GROQ_API_KEY=!GROQ_KEY!
  echo SILICONFLOW_API_KEY=!SF_KEY!
  echo.
  echo # ===== 笔记保存位置 =====
  echo VAULT_DIR=!NOTE_DIR!
)

if not exist "%DIR%.env" (
  echo [错误] 配置文件写入失败，请检查目录权限。
  pause & exit /b 1
)

echo [成功] 配置文件已生成：%DIR%.env
echo.

rem ---------- 验证配置 ----------
echo 正在验证配置...
"%DIR%.venv\Scripts\python.exe" -X utf8 -c "import sys,os;sys.path.insert(0,r'%DIR%');from localbot import config;ok=bool(config.GROQ_API_KEY and config.SILICONFLOW_API_KEY);print('  Groq Key:', '已配置' if config.GROQ_API_KEY else '缺失');print('  硅基 Key:', '已配置' if config.SILICONFLOW_API_KEY else '缺失');print('  保存路径:', config.VAULT_DIR or '缺失');sys.exit(0 if ok else 1)" 2>nul
if errorlevel 1 (
  echo.
  echo [提示] 验证未通过，可能是虚拟环境还没装好。
  echo         请先运行「安装本地助手.bat」完成环境安装。
) else (
  echo.
  echo ============================================
  echo                配置完成
  echo ============================================
  echo.
  echo 接下来：
  echo   1. 如果还没装环境，双击「安装本地助手.bat」
  echo   2. 按 README 加载浏览器扩展
  echo   3. 打开视频页，点悬浮按钮
)

echo.
pause
