@echo off
rem VidScoop 本地助手注册脚本（当前用户，免管理员）
rem 作用：首次自动建环境装依赖 → 生成本机宿主清单 → 注册给 Chrome
setlocal
set "DIR=%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 3.10+ 并勾选 Add to PATH
  pause & exit /b 1
)

if not exist "%DIR%.venv\" (
  echo 首次运行：创建虚拟环境并安装依赖（约 1-2 分钟）...
  python -m venv "%DIR%.venv" || (echo [错误] venv 创建失败 & pause & exit /b 1)
  "%DIR%.venv\Scripts\pip.exe" install -r "%DIR%requirements.txt" --quiet || (echo [错误] 依赖安装失败 & pause & exit /b 1)
)

rem 由模板生成本机宿主清单（路径自动填当前目录；扩展 ID 由「绑定扩展ID.bat」回填）
"%DIR%.venv\Scripts\python.exe" -X utf8 -c "import io;s=io.open(r'%DIR%com.localbot.ingest.json.template',encoding='utf-8').read().replace('{{BASE}}',r'%DIR%'.replace('\\','/'));io.open(r'%DIR%com.localbot.ingest.json','w',encoding='utf-8').write(s)"

reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.localbot.ingest" /ve /t REG_SZ /d "%DIR%com.localbot.ingest.json" /f

echo.
echo [完成] 本地助手已注册。
echo 下一步：按 README 加载扩展，然后双击「绑定扩展ID.bat」完成对接。
pause
