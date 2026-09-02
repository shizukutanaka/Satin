"""
ファイルシステム関連の小さなユーティリティ。

会話履歴・好感度などユーザーの私的データを、共有環境で他ユーザーに読まれない
よう保護する目的の権限制限ヘルパと、JSONL（1行1 JSON）ファイルを安全に読む
共通ローダを提供する。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


def iter_jsonl_dicts(path: str, *, encoding: str = "utf-8") -> Iterator[Dict]:
    """JSONL ファイルを1行ずつ読み、dict 行のみを順に yield する。

    次の行はスキップする（例外を投げない）:
      - 空行 / 空白のみの行
      - JSON 構文エラー行（クラッシュで途中まで書かれた等）
      - dict 以外の JSON 値（``null`` / 配列 / 数値 / 文字列）

    特に ``json.loads("null")`` は例外を出さず ``None`` を返すため、後段で
    ``ev.get(...)`` 等を呼ぶと ``AttributeError`` になる——という本コードベースで
    繰り返し発生したバグクラスを、ここで一元的にガードする。

    ファイルが存在しない／読み込めない場合は何も yield しない。
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding=encoding) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError as e:  # pragma: no cover - defensive
        logger.debug("JSONL 読み込みに失敗しました (%s): %s", path, e)
        return


def load_jsonl_dicts(path: str, *, encoding: str = "utf-8") -> List[Dict]:
    """``iter_jsonl_dicts`` のリスト版。dict 行のみのリストを返す。

    末尾 n 件だけ欲しい場合は ``load_jsonl_dicts(path)[-n:]`` とする。
    """
    return list(iter_jsonl_dicts(path, encoding=encoding))


def atomic_write_text(
    path: str,
    content: str,
    *,
    encoding: str = "utf-8",
    fsync: bool = True,
    restrict: bool = False,
    newline: Optional[str] = None,
) -> None:
    """content を path へアトミックに書き込む。

    write-to-temp-then-os.replace は複数の呼び出し元（user_profile.py /
    mood.py / config_manager_enhanced.py）でそれぞれ独自に
    ``tmp = f"{path}.tmp"`` という固定名を使って実装されていた。この
    固定名は書き込み者ごとに一意ではないため、同じ path へ同時に
    save() する 2 者（例: GUI スレッドと autonomous_behavior のバック
    グラウンドスレッド）が同じ一時ファイルを取り合い、片方の
    open(tmp, "w") がもう片方の書き込み中の一時ファイルを切り詰め、
    負けた側の os.replace(tmp, path) は FileNotFoundError で失敗する
    （呼び出し元の広い except Exception に飲み込まれ、更新が黙って
    失われる）。tempfile.mkstemp で書き込み者ごとに一意な一時ファイル
    名を割り当てることでこの競合を無くす。

    失敗時は一時ファイルを削除したうえで例外を re-raise する
    （呼び出し元の既存の try/except パターンに判断を委ねる）。

    newline は組み込み open と同じ意味。CSV を書くときは csv モジュールが
    自前で "\r\n" を出すので newline="" を渡すこと（既定の None だと
    Windows で "\n" → "\r\n" の変換が二重に掛かり "\r\r\n" になる）。
    """
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=parent, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            f.write(content)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        if restrict:
            restrict_to_owner(tmp)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def restrict_to_owner(path: str) -> bool:
    """ファイルのパーミッションを所有者のみ読み書き可 (0o600) に制限する。

    会話ログや好感度ファイルは既定 umask だと 0o644（他ユーザーも読める）で
    作られるため、マルチユーザー環境では私的な会話内容が漏れうる。これを
    防ぐためのベストエフォートのハードニング。

    Windows など chmod が意味を持たない/失敗する環境では静かに False を返し、
    呼び出し側の動作は壊さない。

    Returns:
        制限に成功したら True、失敗（非対応OS・ファイル無し等）なら False。
    """
    try:
        os.chmod(path, 0o600)
        return True
    except OSError as e:  # pragma: no cover - platform dependent
        logger.debug("パーミッション制限に失敗しました (%s): %s", path, e)
        return False
