#!/usr/bin/env python3
"""Satin の検証ゲート — これ 1 本で「緑かどうか」が決まる。

    python check.py            # 全チェック
    python check.py --fast     # 起動スモークを飛ばす（編集中の高速ループ用）
    python check.py --list     # 何を実行するかだけ表示

なぜこのファイルがあるか
------------------------
検証手順は今まで「pytest と ruff と mypy と validate を叩いて、ついでに
--chat が動くか見る」という**記憶に頼った手順**だった。記憶に頼る手順は
必ず食い違う — 人によって、日によって、CI とローカルで。実際 CI の yml と
手元で叩くコマンドは既に少しずつずれていた。

そこで「緑の定義」をこのファイル 1 箇所に置き、CI もここを呼ぶ。ローカルで
通ったものは CI でも通る、が構造的に保証される（コマンドが同一だから）。

スモークテストについて
----------------------
ユニットテストはモジュールを直接 import するので、**エントリポイントが実際に
起動するか**は見ていない。起動経路の配線ミス（import 順、引数解析、任意依存の
フォールバック）はユニットテストを全て通過したまま壊れうるので、ここで
`--version` と `--chat` と dashboard の疎通を別途確認する。

スモークは会話ログ・好感度を書き換えるため、一時ディレクトリへ隔離してから
実行する（ゲートを回しただけでユーザーの好感度が動くのは副作用として不当）。

任意依存の有無について
----------------------
**このゲートの結果は、入っている任意依存に左右される。** 実際、PyQt5 を入れて
いない環境では緑なのに、入れると 197 件落ちる状態が長く続いていた（テストが
`object.__new__(QOpenGLWidget のサブクラス)` を使っており、Qt が本物になると
TypeError になるため）。CI は requirements.txt を全部入れるので、CI を有効化
した時点で赤になる — 「手元で緑なら CI でも緑」という前提が、環境差で崩れる。

そこで実行のたびに任意依存の状態を表示する。緑であることと、**何をもって
緑なのか**をセットで見せる。全部入りで検証したければ:

    pip install -r setup/requirements.txt
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.abspath(__file__))
_MAIN = os.path.join(_ROOT, "main")

# 任意依存。有無でテストの通り方が変わりうるので、実行のたびに状態を出す。
_OPTIONAL_DEPS = ("PyQt5", "OpenGL", "flask", "numpy", "pygltflib", "pyttsx3")

# 端末が UTF-8 でない場合に備え、記号はここで一元管理する。
_OK, _NG, _SKIP = "PASS", "FAIL", "SKIP"


class Result:
    __slots__ = ("name", "status", "detail", "seconds")

    def __init__(self, name: str, status: str, detail: str = "", seconds: float = 0.0):
        self.name = name
        self.status = status
        self.detail = detail
        self.seconds = seconds


def _run(name: str, argv: list[str], *, env: dict | None = None,
         cwd: str | None = None, stdin: str | None = None,
         timeout: int = 600) -> Result:
    """1 コマンドを実行して Result を返す。失敗しても例外にしない。"""
    print(f"  → {name} ...", end="", flush=True)
    started = time.time()
    full_env = dict(os.environ)
    full_env.setdefault("PYTHONPATH", _MAIN)
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(
            argv, cwd=cwd or _ROOT, env=full_env, timeout=timeout,
            input=stdin, capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - started
        print(f" {_NG} ({elapsed:.1f}s, timeout)")
        return Result(name, _NG, f"{timeout} 秒でタイムアウト", elapsed)
    except FileNotFoundError as e:
        elapsed = time.time() - started
        print(f" {_SKIP}")
        return Result(name, _SKIP, str(e), elapsed)
    elapsed = time.time() - started
    if proc.returncode == 0:
        print(f" {_OK} ({elapsed:.1f}s)")
        return Result(name, _OK, "", elapsed)
    print(f" {_NG} ({elapsed:.1f}s)")
    tail = (proc.stdout or "") + (proc.stderr or "")
    return Result(name, _NG, "\n".join(tail.strip().split("\n")[-25:]), elapsed)


# --------------------------------------------------------------------------- #
# 個別チェック
# --------------------------------------------------------------------------- #
def check_tests() -> Result:
    return _run("pytest", [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"])


def check_lint() -> Result:
    return _run("ruff", [sys.executable, "-m", "ruff", "check",
                         "main/", "tests/", "satin_launcher.py"])


def check_types() -> Result:
    # 引数を渡さない。対象は mypy.ini の files= が決める — ここで明示すると
    # 設定と実行がずれ、検査漏れに気づけなくなる。
    return _run("mypy", [sys.executable, "-m", "mypy"])


def check_configs() -> Result:
    return _run("config validate",
                [sys.executable, os.path.join("main", "manage_satin.py"), "validate"])


def check_compile() -> Result:
    """全モジュールが構文として読めること（import 不能な依存があっても通る）。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(_MAIN):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        files.extend(os.path.join(dirpath, f)
                     for f in filenames if f.endswith(".py"))
    return _run("py_compile", [sys.executable, "-m", "py_compile", *sorted(files)])


# 好感度・会話ログ・プロフィールなど、スモークが副作用として書き換えうる
# 個人データ。パスはリポジトリ相対で解決されるため環境変数では逃がせない。
_PERSONAL_DATA = (
    "mood.json", "mood_history.jsonl", "user_profile.json", "satin.lock",
)


@contextlib.contextmanager
def _personal_data_preserved():
    """スモークの間だけ個人データを退避し、終了時に必ず書き戻す。

    ゲートを回しただけでユーザーの好感度や会話履歴が動くのは、副作用として
    不当である（「チェックしただけ」のつもりが親密度を進めてしまう）。
    退避対象が実行中に**新規作成**された場合は削除して元の状態に戻す。
    """
    cfg = os.path.join(_ROOT, "config")
    with tempfile.TemporaryDirectory() as tmp:
        saved: dict[str, str | None] = {}
        for name in _PERSONAL_DATA:
            src = os.path.join(cfg, name)
            if os.path.exists(src):
                dst = os.path.join(tmp, name)
                shutil.copy2(src, dst)
                saved[src] = dst
            else:
                saved[src] = None  # 実行前は存在しなかった
        try:
            yield
        finally:
            for src, dst in saved.items():
                if dst is not None:
                    shutil.copy2(dst, src)
                elif os.path.exists(src):
                    os.unlink(src)


def check_smoke_version() -> Result:
    return _run("smoke: --version",
                [sys.executable, "satin_launcher.py", "--version"], timeout=120)


def check_smoke_chat() -> Result:
    """--chat が起動し、挨拶・別れの一往復を返すこと。"""
    return _run("smoke: --chat",
                [sys.executable, "satin_launcher.py", "--chat"],
                env={"SATIN_LANG": "ja"},
                stdin="こんにちは\nさようなら\n", timeout=180)


def check_smoke_dashboard() -> Result:
    """flask がある場合のみ、主要ルートが 200 を返すこと。"""
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "try:\n"
        "    import flask  # noqa: F401\n"
        "except Exception:\n"
        "    sys.exit(77)\n"
        "import dashboard\n"
        "c = dashboard.app.test_client()\n"
        "bad = [(p, c.get(p).status_code) for p in "
        "('/', '/healthz', '/stats', '/summary', '/mood')"
        " if c.get(p).status_code != 200]\n"
        "assert not bad, bad\n" % _MAIN
    )
    res = _run("smoke: dashboard", [sys.executable, "-c", script], timeout=180)
    # 77 は「flask 未導入」の合図。失敗ではなく SKIP として扱う。
    if res.status == _NG and "SystemExit: 77" not in res.detail:
        proc = subprocess.run([sys.executable, "-c", script], cwd=_ROOT,
                              capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": _MAIN})
        if proc.returncode == 77:
            return Result(res.name, _SKIP, "flask 未導入", res.seconds)
    return res


_GUI_SMOKE_SCRIPT = """\
import sys
sys.path.insert(0, %r)
try:
    from PyQt5.QtWidgets import QApplication
except Exception:
    sys.exit(77)
import avatar_3d_autonomous_tts as av
app = QApplication([])
w = av.MainWindow()
w.show()
app.processEvents()
v = w.viewer
w.toggle_autonomous()
assert v.is_autonomous, "autonomous mode did not start"
x_max, y_max = v._movement_bounds()
for tick in range(400):
    v.update_autonomous()
    assert abs(v.position[0]) <= x_max + 1e-9, (tick, v.position)
    assert abs(v.position[1]) <= y_max + 1e-9, (tick, v.position)
w.toggle_autonomous()
assert not v.is_autonomous, "autonomous mode did not stop"
w.close()
app.processEvents()
"""


def check_smoke_gui() -> Result:
    """PyQt5 と X サーバ（実物か xvfb）がある場合のみ、実 GUI で自律モードを回す。

    アバターが画面外へ歩き去る欠陥は、xvfb で実際に起動して座標を実測する
    まで、どの静的検査・単体テストにも掛からなかった。実 Qt タイマー経路
    （update_autonomous → _advance_autonomous_state → paintGL の座標）を
    400 ティック回し、位置が常に可視範囲内に留まることを検証する。
    手で二度やった検証は自動化する（5 ステップの最終段）。
    """
    script = _GUI_SMOKE_SCRIPT % _MAIN
    cmd = [sys.executable, "-c", script]
    if not os.environ.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            return Result("smoke: GUI", _SKIP, "DISPLAY も xvfb-run も無い", 0.0)
        cmd = [xvfb, "-a", *cmd]
    res = _run("smoke: GUI", cmd, timeout=300)
    # 77 は「PyQt5 未導入」の合図。失敗ではなく SKIP として扱う。
    if res.status == _NG and "SystemExit: 77" not in res.detail:
        proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
        if proc.returncode == 77:
            return Result(res.name, _SKIP, "PyQt5 未導入", res.seconds)
    return res


_STATIC = [
    ("py_compile", check_compile),
    ("ruff", check_lint),
    ("mypy", check_types),
    ("pytest", check_tests),
    ("config validate", check_configs),
]

_SMOKE = [
    ("smoke: --version", check_smoke_version),
    ("smoke: --chat", check_smoke_chat),
    ("smoke: dashboard", check_smoke_dashboard),
    ("smoke: GUI", check_smoke_gui),
]


def _optional_dep_status() -> tuple[list[str], list[str]]:
    """導入済み / 未導入の任意依存を返す。"""
    import importlib.util
    present, missing = [], []
    for name in _OPTIONAL_DEPS:
        try:
            found = importlib.util.find_spec(name) is not None
        except Exception:  # pragma: no cover - defensive: 壊れた spec でも止めない
            found = False
        (present if found else missing).append(name)
    return present, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Satin の検証ゲート（CI とローカルで同一のコマンド）")
    parser.add_argument("--fast", action="store_true",
                        help="起動スモークを飛ばす（編集中の高速ループ用）")
    parser.add_argument("--list", action="store_true",
                        help="実行内容を表示するだけで実行しない")
    args = parser.parse_args(argv)

    plan = list(_STATIC) + ([] if args.fast else list(_SMOKE))

    if args.list:
        for name, _ in plan:
            print(name)
        return 0

    print(f"Satin 検証ゲート — {len(plan)} 項目"
          + ("（--fast: スモーク省略）" if args.fast else ""))
    present, missing = _optional_dep_status()
    if missing:
        print(f"  任意依存: {len(present)}/{len(_OPTIONAL_DEPS)} 導入済み"
              f"（未導入: {', '.join(missing)}）")
        print("  ※ 未導入の依存に関わるテストは、CI（全部入り）と結果が"
              "異なりうる。全部入りで確かめるには "
              "pip install -r setup/requirements.txt")
    else:
        print(f"  任意依存: 全 {len(_OPTIONAL_DEPS)} 件導入済み（CI と同条件）")
    started = time.time()
    results = [fn() for _, fn in _STATIC]
    if not args.fast:
        # スモークは実プロセスを起動するので個人データを書き換えうる。
        # 退避・書き戻しはスモーク全体を包む必要がある（--chat だけを包むと、
        # その後に走る dashboard スモークの書き込みが漏れる）。
        with _personal_data_preserved():
            results += [fn() for _, fn in _SMOKE]
    total = time.time() - started

    failed = [r for r in results if r.status == _NG]
    skipped = [r for r in results if r.status == _SKIP]

    for r in failed:
        print(f"\n{'=' * 70}\n{_NG}: {r.name}\n{'=' * 70}\n{r.detail}")

    print(f"\n{'-' * 70}")
    passed = len(results) - len(failed) - len(skipped)
    summary = f"{passed} 件成功"
    if skipped:
        summary += f" / {len(skipped)} 件スキップ（{', '.join(r.name for r in skipped)}）"
    if failed:
        summary += f" / {len(failed)} 件失敗"
    print(f"{summary}  [{total:.1f}s]")
    print("緑です。" if not failed else "赤です。上の失敗を直してください。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
