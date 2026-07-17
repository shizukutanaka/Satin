@echo off
REM ====================================
REM Satin セットアップスクリプト (Windows版)
REM 最終更新: 2026-07-13
REM ====================================

:: このスクリプト自身の場所からリポジトリルートを解決する
:: (setup\win\setup.bat からの相対パスに依存しない)
set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%..\.."

:: 管理者権限の確認
net session >nul 2>&1
if %errorLevel% == 0 (
    echo 管理者権限で実行されています。
) else (
    echo 管理者権限が必要な場合があります。
    echo セットアップを続行しますが、問題が発生した場合は管理者として実行してください。
)

:: Pythonの存在確認
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo エラー: Pythonがインストールされていないか、パスが通っていません。
    echo Python 3.8 以降をインストールしてから再度お試しください。
    pause
    exit /b 1
)

:: 必要なパッケージのインストール
echo 必要なパッケージをインストールしています...
python -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 (
    echo エラー: pipのアップグレードに失敗しました。
    pause
    exit /b 1
)

pip install -r "%ROOT_DIR%\setup\requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo エラー: 依存関係のインストールに失敗しました。
    pause
    exit /b 1
)

:: 完了メッセージ
echo.
echo ====================================
echo Satinのセットアップが完了しました！
echo 以下のコマンドで起動できます：
echo launch\win\run_satin.bat
echo ====================================
pause
