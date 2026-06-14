"""
ファイルシステム関連の小さなユーティリティ。

会話履歴・好感度などユーザーの私的データを、共有環境で他ユーザーに読まれない
よう保護する目的の権限制限ヘルパを提供する。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


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
