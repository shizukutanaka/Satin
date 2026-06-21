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
from typing import Dict, Iterator, List

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
