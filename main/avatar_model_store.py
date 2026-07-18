"""
選択されたアバターモデルの永続化と解決（純ロジック・LLM/GUI 非依存）。

`avatar_loader.py`（`--avatar-loader` で開くファイル選択ダイアログ）が選んだ
アバターファイルのパスを保存し、本体 3D GUI（`avatar_3d_autonomous_tts.py`）が
起動時にそれを読み取って描画できるようにする「唯一の受け渡し口」。

従来 `avatar_loader.py` は cwd 相対の `avatar_history.json` に履歴を書くだけで、
どのモジュールもそれを読まず、ユーザーが選んだアバターがどこにも反映されな
かった（商用品質監査 W7 の残課題）。ここに canonical な保存先とアトミック
書き込み・堅牢な読み込み・拡張子/実在チェック付きの解決を集約する。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import List, Optional

# 描画側 (pygltflib) が読める拡張子。.vrm は GLB コンテナなので glTF として
# 読める見込み。.fbx はバイナリ独自形式で本ワイヤーフレーム描画の対象外。
SUPPORTED_MODEL_EXTS = (".glb", ".gltf", ".vrm")

_MAX_HISTORY = 5


def _repo_root() -> str:
    """リポジトリルート（この main/ の親）を返す。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def history_path() -> str:
    """アバター選択履歴の canonical な保存先（config/avatar_history.json）。

    `mood._default_mood_path` と同じ root 導出パターン。cwd に依存しないため、
    どのディレクトリから起動しても同じ履歴を参照できる。
    """
    return os.path.join(_repo_root(), "config", "avatar_history.json")


def _legacy_cwd_path() -> str:
    """旧 `avatar_loader.py` が書いていた cwd 相対の履歴ファイル。"""
    return os.path.abspath("avatar_history.json")


def _read_list(path: str) -> Optional[List[str]]:
    """path から履歴 list を読む。存在しない/破損/list 以外なら None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    # 破損ファイルが list 以外（dict/str 等）でも安全に扱う。
    if not isinstance(data, list):
        return None
    return [str(p) for p in data]


def load_history() -> List[str]:
    """アバター選択履歴（新しい順）を返す。無ければ空リスト。

    canonical パスを優先し、無ければ旧 cwd 相対ファイルへフォールバックする
    （既存ユーザーの履歴を失わないため）。
    """
    result = _read_list(history_path())
    if result is not None:
        return result
    legacy = _read_list(_legacy_cwd_path())
    return legacy if legacy is not None else []


def save_selection(path: str) -> List[str]:
    """選択されたアバター path を履歴の先頭に追加して保存し、更新後の履歴を返す。

    重複は除去し先頭へ、上限 _MAX_HISTORY 件。アトミック書き込み
    (mkstemp + os.replace) で途中クラッシュ時の破損を防ぐ
    （`avatar_loader.add_history` のパターンを移設・共通化）。
    空/None path は no-op（現在の履歴を返す）。
    """
    if not path:
        return load_history()
    history = load_history()
    if path in history:
        history.remove(path)
    history.insert(0, path)
    history = history[:_MAX_HISTORY]

    dest = history_path()
    _dir = os.path.dirname(dest) or "."
    os.makedirs(_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return history


def clear() -> bool:
    """アバター選択履歴を削除する（canonical + 旧 cwd 相対の両方）。

    「全データ消去」でユーザーの選択痕跡も消すために使う。1 つでも削除したら
    True。どちらも存在しなければ False。
    """
    removed = False
    for path in (history_path(), _legacy_cwd_path()):
        try:
            if os.path.exists(path):
                os.remove(path)
                removed = True
        except OSError:
            pass
    return removed


def resolve_selected_avatar() -> Optional[str]:
    """描画に使える「現在のアバター」のパスを返す。無ければ None。

    履歴を新しい順に見て、実在し かつ 対応拡張子 (.glb/.gltf/.vrm) の最初の
    パスを返す。ユーザーが最後に選んだモデルが（まだ存在すれば）採用される。
    """
    for path in load_history():
        if not path:
            continue
        if os.path.splitext(path)[1].lower() not in SUPPORTED_MODEL_EXTS:
            continue
        if os.path.isfile(path):
            return path
    return None
