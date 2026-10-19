@echo off
rem 把扩展 ID 回填进宿主清单。用法：先加载扩展，从 chrome://extensions 复制扩展 ID，再双击本脚本按提示粘贴。
setlocal
set "DIR=%~dp0"
set /p "EXTID=请粘贴扩展 ID（32 个小写字母）: "
if "%EXTID%"=="" (echo [取消] 未输入 & pause & exit /b 1)
"%DIR%.venv\Scripts\python.exe" -X utf8 -c "import io;p=r'%DIR%com.localbot.ingest.json';s=io.open(p,encoding='utf-8').read();s=s.replace('REPLACE_WITH_EXTENSION_ID','%EXTID%');io.open(p,'w',encoding='utf-8').write(s);print('[完成] 已绑定扩展 ID: %EXTID%')"
pause
