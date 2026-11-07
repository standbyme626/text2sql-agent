@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
  echo [1/5] 创建虚拟环境并安装依赖...
  python -m venv .venv
  "%PY%" -m pip install -q -r backend\requirements.txt
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo   [!] 已生成 .env，请填入 MODELSCOPE_API_KEY / SILICONFLOW_API_KEY
  echo       只想先看界面可在 .env 设 MOCK_MODE=true
)

if not exist "backend\data\ecommerce.db" (
  echo [2/5] 初始化 50 张电商表与模拟数据...
  "%PY%" backend\scripts\init_db.py
)

if not exist "backend\data\schema_index.json" (
  echo [3/5] 构建向量索引...
  "%PY%" backend\scripts\build_index.py || echo   [!] 索引未生成，将降级为关键词选表
)

if not exist "backend\static\index.html" (
  echo [4/5] 前端产物缺失，请在有 Node.js 的环境执行:
  echo       cd frontend ^&^& npm install ^&^& npm run build
  echo       然后把 frontend\dist\ 里的内容拷到 backend\static\
)

echo [5/5] 启动服务: http://127.0.0.1:3388
echo       本机回环地址未设 AUTH_PASSWORD 时免登录；对外服务必须设置密码
echo.
"%PY%" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 3388
