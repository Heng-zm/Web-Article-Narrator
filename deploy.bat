@echo off
echo Preparing deployment for Wasmer Edge...

:: Install all requirements locally into a vendor folder
pip install -r requirements.txt -t packages/

echo.
echo ✅ Dependencies bundled successfully!
echo Now run: wasmer deploy
