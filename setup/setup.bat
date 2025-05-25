@echo off
REM Satin セットアップスクリプト
REM 必要なPythonパッケージをインストール

python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Satinセットアップ完了！
pause
