@echo off
rem VidScoop 配置向导启动器
rem 实际逻辑在 setup_wizard.py 里（用 Python 写，避免 bat 编码问题）
setlocal
set "DIR=%~dp0"

rem 优先用项目虚拟环境里的 Python
if exist "%DIR%.venv\Scripts\python.exe" (
  "%DIR%.venv\Scripts\python.exe" -X utf8 "%DIR%setup_wizard.py"
  goto :done
)

rem 没装环境，用系统 Python
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [错误] 找不到 Python
  echo.
  echo  请先双击「安装本地助手.bat」完成环境安装。
  echo  如果那一步也失败，说明系统没装 Python，请先去 python.org 安装
  echo  安装时记得勾选 "Add Python to PATH"
  echo.
  pause
  exit /b 1
)
python -X utf8 "%DIR%setup_wizard.py"

:done
echo.
pause
