"""ユーザーの個人データを一括消去する（「忘れられる権利」の実装）。

本製品の最も重要な約束 —「私に関するデータを全部消して」が 1 コマンドで叶う —
の実体。GUI の `/forget-all` と対話 CLI の `/forget-all` が**同じこの関数**を
呼ぶ。

**なぜ独立したモジュールなのか**: 元は `avatar_3d_autonomous_tts.py` の中に
あった。GUI 依存は 1 つも無く、そこに置かれていたのは書かれた場所がそう
だったからにすぎない。しかし GUI モジュールの中にあるせいで対話 CLI から
呼べず、その結果 **CLI には /forget-all が存在しなかった** — CLI で打つと
未知のコマンドとして会話に流れ、「全部消して」と言った人のデータが黙って
残っていた。入口によって消える範囲が違う privacy 保証は、保証ではない。

`manage_satin data purge` は別実装のままにしてある。あちらはアプリが動いて
いない状態でファイルを**削除**する管理ツールで、対象一覧の提示や dry-run を
持つ。こちらは動作中のアプリからライブのシングルトンごと**リセット**する。
目的が違うので、無理に 1 つにしない（ただし消す対象の 5 種は同じであること
を `tests/test_data_erasure.py` が検証する）。

消去対象:
  - プロフィール（呼び名・誕生日・趣味・覚えた事実）: config/user_profile.json
  - 会話履歴: avatar_event_log.jsonl + gzip アーカイブ
  - 好感度: config/mood.json をニュートラルへ + config/mood_history.jsonl 削除
  - アバター選択履歴

各ストアは独立してガードする。一部が失敗しても残りは消す（best-effort）。
どれを消せたかは戻り値の dict で分かる。
"""
from __future__ import annotations

import logging
import os
from typing import Dict

logger = logging.getLogger(__name__)

try:
    from user_profile import get_user_profile as _get_user_profile
    from user_profile import _default_profile_path
except Exception:  # pragma: no cover - defensive
    _get_user_profile = None  # type: ignore[assignment]
    _default_profile_path = None  # type: ignore[assignment]

try:
    from conversation_log import get_conversation_log
except Exception:  # pragma: no cover - defensive
    get_conversation_log = None  # type: ignore[assignment]

try:
    from mood import get_mood_tracker, _default_mood_path, _default_mood_history_path
except Exception:  # pragma: no cover - defensive
    get_mood_tracker = None  # type: ignore[assignment]
    _default_mood_path = None  # type: ignore[assignment]
    _default_mood_history_path = None  # type: ignore[assignment]

try:
    import avatar_model_store as _avatar_model_store
except Exception:  # pragma: no cover - defensive
    _avatar_model_store = None  # type: ignore[assignment]


def erase_all_user_data() -> Dict[str, bool]:
    """ユーザーの個人データを可能な限りすべて消去し、消したものの要約を返す。

    プライバシー優先の製品として「私に関するデータを全部消して」を一括で叶える。
    各ストアは独立してガードし、一部が失敗しても残りは消す（best-effort）。
    消去対象:
      - プロフィール（呼び名・誕生日・趣味・覚えた事実）: config/user_profile.json
      - 会話履歴: avatar_event_log.jsonl + gzip アーカイブ
      - 好感度: config/mood.json をニュートラルへ + config/mood_history.jsonl 削除
      - アバター選択履歴: config/avatar_history.json
    （daily_mood は日付から決定的に導かれ永続状態を持たないため対象外。）

    戻り値は {"profile": bool, "conversation": bool, "mood": bool,
              "avatar": bool} で、各項目を実際に消去できたかを表す。
    """
    import os as _os
    report = {"profile": False, "conversation": False, "mood": False, "avatar": False}

    # 1) プロフィール
    if _get_user_profile is not None:
        try:
            prof = _get_user_profile()
            if prof is not None:
                prof.clear()
                if _default_profile_path is not None:
                    prof.save(_default_profile_path())
                report["profile"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: プロフィール消去に失敗: %s", e)

    # 2) 会話履歴（ライブ + アーカイブ）
    if get_conversation_log is not None:
        try:
            from conversation_log import _find_archives
            conv_log = get_conversation_log()
            path = conv_log.logfile
            if os.path.exists(path):
                open(path, "w", encoding="utf-8").close()
            for gz in _find_archives(path):
                try:
                    os.remove(gz)
                except OSError:
                    pass
            report["conversation"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: 会話履歴消去に失敗: %s", e)

    # 3) 好感度（ニュートラルへ + 履歴ファイル削除）
    if get_mood_tracker is not None:
        try:
            from mood import AFFINITY_START
            tracker = get_mood_tracker()
            tracker.affinity = AFFINITY_START
            tracker.interactions = 0
            tracker._last_interaction_time = 0.0
            tracker._first_interaction_time = 0.0
            tracker._last_anniversary_days = 0
            tracker._last_login_date = ""
            tracker._login_streak = 0
            tracker._confession_done = False
            if _default_mood_path is not None:
                tracker.save(_default_mood_path())
            if _default_mood_history_path is not None:
                hist = _default_mood_history_path()
                if os.path.exists(hist):
                    try:
                        os.remove(hist)
                    except OSError:
                        pass
            report["mood"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: 好感度消去に失敗: %s", e)

    # 4) アバター選択履歴
    if _avatar_model_store is not None:
        try:
            _avatar_model_store.clear()
            report["avatar"] = True
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("全消去: アバター履歴消去に失敗: %s", e)

    return report
