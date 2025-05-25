@echo off
REM ====================================
REM Satin バックアップ管理ツール (Windows版)
REM 最終更新: 2025-05-25
REM ====================================

:: 管理者権限の確認
net session >nul 2>&1
if %errorLevel% == 0 (
    echo 管理者権限で実行されています。
) else (
    echo 管理者権限が必要な場合があります。
)

:: Pythonの存在確認
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo エラー: Pythonがインストールされていないか、パスが通っていません。
    pause
    exit /b 1
)

:: 仮想環境の有効化 (存在する場合)
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

:: メインスクリプトの実行
echo Satin バックアップ管理ツールを起動しています...
python backup_cli.py %*

:: エラー時の処理
if %ERRORLEVEL% NEQ 0 (
    echo エラーが発生しました。終了コード: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

pause
