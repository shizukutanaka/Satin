"""
ペルソナ対話 CLI（ヘッドレス・チャット）。

これまで persona.respond() / conversation_log といった会話機能はすべて Qt GUI
(avatar_3d_autonomous_tts.speak_comment) 経由でしか到達できず、ディスプレイや GPU
の無い環境（サーバー / CI / SSH 越し）ではアバターと会話できなかった。本モジュールは
標準入出力だけで動く REPL を提供し、構築済みのペルソナ・応答・会話ログ機能を
ヘッドレスで使えるようにする。

依存は標準ライブラリのみ。input/output 関数を注入できるため完全にテスト可能。

コマンド:
  /help               コマンド一覧
  /history            会話履歴の直近を表示
  /search <キーワード> 会話履歴をキーワード検索（アーカイブ含む）
  /export-log [パス]   会話履歴を CSV へエクスポート（既定: conversation_export.csv）
  /clear-log          会話履歴を全消去（アーカイブ含む・二段階確認）
  /callme <名前>       アバターに呼んでほしい名前を覚えさせる
  /birthday MM-DD      誕生日を覚えさせる（当日に祝ってくれる）
  /like <好きなもの>    好きなものを覚えさせる（例: /like アニメ）
  /forget <好きなもの>  覚えた好きなものを忘れさせる
  /forget-fact <内容>   一問一答で覚えた事実のうち、内容が一致するものを1件忘れさせる
  /gift <プレゼント>    アバターにプレゼントを贈る（/gift list でカタログ表示）
  /whoami             今記憶している呼び名・誕生日・好きなものを表示
  /forget-me          覚えた個人情報（呼び名・誕生日・趣味・記憶）を全消去
  /mood               好感度レベルと今日のアバターの気分を表示
  /reset-mood         好感度をニュートラルにリセット
  /recap              今日の会話サマリーと直近のやりとりを表示
  /feeling            最近のあなたの気分にアバターが寄り添う（/checkin も同じ）
  /stats              会話統計を表示
  /name               ペルソナ名を表示
  /quit               終了（/exit, /q も同じ）
"""
from __future__ import annotations

import time as _time
from typing import Any, Callable, List, Optional

from persona import Persona, get_persona

try:
    from conversation_log import ConversationLog, get_conversation_log
except Exception:  # pragma: no cover - defensive
    ConversationLog = None  # type: ignore
    get_conversation_log = None  # type: ignore[assignment]

try:
    from mood import (
        MoodTracker, get_mood_tracker,
        absence_message as _absence_message_fn,
        anniversary_message as _anniversary_message_fn,
        check_level_milestone as _check_level_milestone,
        check_confession_event as _check_confession_event,
        check_interaction_milestone as _check_interaction_milestone,
        check_daily_login as _check_daily_login,
        check_hurt_event as _check_hurt_event,
        affinity_level,
        affinity_label as _affinity_label,
    )
except Exception:  # pragma: no cover - defensive
    MoodTracker = None  # type: ignore
    get_mood_tracker = None  # type: ignore[assignment]
    _absence_message_fn = None  # type: ignore
    _anniversary_message_fn = None  # type: ignore
    _check_level_milestone = None  # type: ignore
    _check_confession_event = None  # type: ignore
    _check_interaction_milestone = None  # type: ignore
    _check_daily_login = None  # type: ignore
    _check_hurt_event = None  # type: ignore
    affinity_level = None  # type: ignore
    _affinity_label = None  # type: ignore

try:
    from user_profile import (
        get_user_profile, personalize as _personalize,
        _default_profile_path as _profile_path,
    )
except Exception:  # pragma: no cover - defensive
    get_user_profile = None  # type: ignore[assignment]
    _personalize = None  # type: ignore
    _profile_path = None  # type: ignore

try:
    from special_days import (
        seasonal_greeting as _seasonal_greeting,
        birthday_greeting as _birthday_greeting,
        BIRTHDAY_AFFINITY_BONUS as _BIRTHDAY_BONUS,
    )
except Exception:  # pragma: no cover - defensive
    _seasonal_greeting = None  # type: ignore
    _birthday_greeting = None  # type: ignore
    _BIRTHDAY_BONUS = 0.0

try:
    from gifts import (
        lookup_gift as _lookup_gift,
        lookup_gift_key as _lookup_gift_key,
        gift_catalog_text as _gift_catalog_text,
        cooldown_message as _gift_cooldown_message,
        all_gift_keys as _all_gift_keys,
    )
except Exception:  # pragma: no cover - defensive
    _lookup_gift = None  # type: ignore
    _lookup_gift_key = None  # type: ignore
    _gift_catalog_text = None  # type: ignore
    _gift_cooldown_message = None  # type: ignore
    _all_gift_keys = None  # type: ignore

try:
    import ai_disclosure as _ai_disclosure
except Exception:  # pragma: no cover - defensive
    _ai_disclosure = None  # type: ignore

try:
    from crisis_support import crisis_reply as _crisis_reply
except Exception:  # pragma: no cover - defensive
    _crisis_reply = None  # type: ignore

try:
    from farewell_integrity import is_farewell as _is_farewell
except Exception:  # pragma: no cover - defensive
    _is_farewell = None  # type: ignore

try:
    from everyday_distress import is_distressed as _is_distressed
except Exception:  # pragma: no cover - defensive
    _is_distressed = None  # type: ignore

try:
    from daily_summary import summary_greeting as _summary_greeting
except Exception:  # pragma: no cover - defensive
    _summary_greeting = None  # type: ignore

try:
    from user_wellbeing import wellbeing_summary as _wellbeing_summary
    from user_wellbeing import wellbeing_message as _wellbeing_message
except Exception:  # pragma: no cover - defensive
    _wellbeing_summary = None  # type: ignore
    _wellbeing_message = None  # type: ignore

try:
    from daily_mood import (
        get_daily_mood as _get_daily_mood,
        mood_label as _mood_label,
        mood_description as _mood_description,
        mood_emoji as _mood_emoji,
        mood_affinity_multiplier as _mood_affinity_multiplier,
    )
except Exception:  # pragma: no cover - defensive
    _get_daily_mood = None  # type: ignore
    _mood_label = None  # type: ignore
    _mood_description = None  # type: ignore
    _mood_emoji = None  # type: ignore
    _mood_affinity_multiplier = None  # type: ignore

try:
    from profile_questions import (
        next_unanswered_question as _next_unanswered_question,
        acknowledge_answer as _acknowledge_answer,
        recall_fact as _recall_fact,
    )
except Exception:  # pragma: no cover - defensive
    _next_unanswered_question = None  # type: ignore
    _acknowledge_answer = None  # type: ignore
    _recall_fact = None  # type: ignore


_QUIT_COMMANDS = {"/quit", "/exit", "/q"}
_HISTORY_DEFAULT = 10
_MOOD_RESET_COMMANDS = {"/reset-mood", "/resetmood"}
# 個人情報（呼び名・誕生日・趣味・記憶）を消去するプライバシーコマンド
_FORGET_ME_COMMANDS = {"/forget-me", "/forgetme"}

_CLEAR_LOG_COMMANDS = {"/clear-log", "/clearlog"}
# N 回ごとにアバターから「聞き返し」質問を添えて会話を続けやすくする
_FOLLOW_UP_EVERY = 4

# 謝罪・おやすみキーワードで好感度に小さなボーナスを与える。
# これにより「謝ったら許してもらえた（関係回復）」「おやすみを言い合う習慣」が育つ。
_APOLOGY_BONUS = 3.0     # 謝罪による回復
_GOODNIGHT_BONUS = 2.0   # おやすみ就寝ルーティンのボーナス

_APOLOGY_KEYWORDS = frozenset([
    "ごめん", "すまない", "すみません", "許して", "ごめんなさい", "謝る",
    "sorry", "apologize", "my bad", "forgive",
])
_GOODNIGHT_KEYWORDS = frozenset([
    "おやすみ", "おやすみなさい",
    "good night", "goodnight", "nighty night", "sweet dreams",
])


def _detect_ritual_event(text: str):
    """謝罪またはおやすみキーワードを検出して (event_name, bonus) を返す。

    複数のイベントが同一発話に含まれる場合はより大きいボーナスを優先。
    何も検出しなければ None。
    """
    import unicodedata as _ud
    norm = _ud.normalize("NFC", text.strip().lower())
    found_apology = any(kw in norm for kw in _APOLOGY_KEYWORDS)
    found_goodnight = any(kw in norm for kw in _GOODNIGHT_KEYWORDS)
    if found_apology and found_goodnight:
        bonus = max(_APOLOGY_BONUS, _GOODNIGHT_BONUS)
        return ("apology_goodnight", bonus)
    if found_apology:
        return ("apology", _APOLOGY_BONUS)
    if found_goodnight:
        return ("goodnight", _GOODNIGHT_BONUS)
    return None


def respond_to(
    text: str,
    persona: Persona,
    conv_log: "Optional[ConversationLog]" = None,
    level: Optional[str] = None,
) -> str:
    """1 つの入力に対する応答を決定し、会話ログがあれば記録して返す。

    level（好感度レベル）を渡すと persona.respond_by_affinity ルールが優先される。
    応答が空（ルール・fallback とも無し）の場合はオウム返しにフォールバックする。
    会話ログへの記録失敗は握り潰す。
    """
    reply = persona.respond(text, level=level)
    if not reply:
        reply = text  # フォールバック: オウム返し
    if conv_log is not None:
        try:
            conv_log.log_exchange(text, reply)
        except Exception:  # pragma: no cover - defensive: 記録失敗で会話を止めない
            pass
    return reply


# --------------------------------------------------------------------------- #
# コマンドの使い方表示（GUI と CLI で共有）
# --------------------------------------------------------------------------- #
# 同じコマンドの使い方が、GUI では「使い方:」CLI では「使用方法:」と割れていた。
# 誕生日の例に至っては 03-14 と 06-15 で別々だった。どちらも同じアバターが
# 同じコマンドについて説明しているのだから、割れる理由が無い。
#
# GUI（avatar_3d_autonomous_tts）は既にこのモジュールから import しているので、
# 定義をここに一本化する。文言を直すときは 1 箇所で済み、片方だけ直して
# ずれることが起こらない。
_COMMAND_USAGE = {
    "callme": {
        "ja": "使い方: /callme <呼んでほしい名前>",
        "en": "Usage: /callme <your name>",
    },
    "birthday": {
        "ja": "使い方: /birthday MM-DD  例: /birthday 03-14",
        "en": "Usage: /birthday MM-DD  e.g. /birthday 03-14",
    },
    "like": {
        "ja": "使い方: /like <好きなもの>  例: /like アニメ",
        "en": "Usage: /like <thing you enjoy>  e.g. /like anime",
    },
    "forget": {
        "ja": "使い方: /forget <好きなもの>",
        "en": "Usage: /forget <thing>  — removes it from memory",
    },
    "forget-fact": {
        "ja": "使い方: /forget-fact <覚えていることの一部>",
        "en": "Usage: /forget-fact <something I said I remember>",
    },
    "gift": {
        "ja": "使い方: /gift <プレゼント>",
        "en": "Usage: /gift <present>",
    },
    "search": {
        "ja": "使い方: /search <キーワード>",
        "en": "Usage: /search <keyword>",
    },
}


def command_usage(command: str, lang: str = "ja") -> str:
    """コマンドの使い方の一行を返す（GUI / CLI 共通）。

    未知のコマンドは空文字を返す（呼び出し側が独自の案内を出せる）。
    """
    entry = _COMMAND_USAGE.get(command)
    if not entry:
        return ""
    return entry["en" if str(lang).lower().startswith("en") else "ja"]


def _help_text(lang: str = "ja", *, with_disclosure: bool = True) -> str:
    """コマンド一覧。

    「これは何なのか」を確かめに来る場所なので、既定では末尾で AI である旨も示す
    （セッション開始時 + 3 時間ごとの開示とは別の、常設の手がかり）。
    ただし起動直後は法定のセッション開始開示が直後に続くため、そこだけ
    with_disclosure=False で外す — 同じ文が 2 行続くと「バグ表示」に見え、
    読み飛ばす習慣がつく。開示は目立つときにだけ効く。
    """
    tail = ""
    if with_disclosure and _ai_disclosure is not None:
        tail = "\n" + _ai_disclosure.session_notice(lang)
    return (
        "コマンド: /help 一覧 | /history 履歴 | /search <キーワード> 検索 | "
        "/export-log [パス] CSV出力 | /clear-log 履歴全消去 | "
        "/callme <名前> 呼び名設定 | /birthday MM-DD 誕生日設定 | "
        "/like <好きなもの> 趣味記憶 | /forget <好きなもの> 忘れる | "
        "/forget-fact <内容> 覚えた事実を忘れる | "
        "/gift <プレゼント> 贈る | /whoami 確認 | /forget-me 記憶を全消去 | "
        "/mood 好感度 | /reset-mood リセット | /recap 今日のまとめ | /feeling 気分 | /stats 統計 | /name 名前 | /quit 終了"
        + tail
    )


def run_chat(
    persona: Optional[Persona] = None,
    conv_log: "Optional[ConversationLog]" = None,
    input_fn: Optional[Callable[[str], str]] = None,
    output_fn: Optional[Callable[[str], None]] = None,
    greet: bool = True,
    mood: "Optional[MoodTracker]" = None,
    profile: Any = None,
) -> int:
    """対話ループを実行する。

    Args:
        persona: 使用する Persona（省略時は共有シングルトン）。
        conv_log: 会話ログ（省略時は共有シングルトン、利用不可なら無効）。
        input_fn: 入力取得関数（省略時は組み込み input。テスト用に差し替え可能）。
        output_fn: 出力関数（省略時は組み込み print。テスト用に差し替え可能）。
        greet: 開始時に時刻依存のあいさつを表示するか。
        mood: 好感度トラッカー（指定時のみ各発話で好感度を更新。None なら無効）。
        profile: ユーザープロファイル（呼び名の記憶。省略時は共有シングルトン）。

    Returns:
        処理したユーザー発話の件数（コマンドを除く）。
    """
    # 既定は呼び出し時に解決する（def 時に束縛すると後からの patch が効かない）
    if input_fn is None:
        input_fn = input
    if output_fn is None:
        output_fn = print
    if persona is None:
        persona = get_persona()
    if conv_log is None and get_conversation_log is not None:
        try:
            conv_log = get_conversation_log()
        except Exception:  # pragma: no cover - defensive
            conv_log = None
    if profile is None and get_user_profile is not None:
        try:
            profile = get_user_profile()
        except Exception:  # pragma: no cover - defensive
            profile = None

    name = persona.name or "Avatar"
    lang = "en" if str(persona.lang).startswith("en") else "ja"

    def _say(text: str) -> None:
        """{user} を呼び名へ置換してアバター発話を出力する。"""
        if _personalize is not None:
            text = _personalize(text, profile, lang)
        output_fn(f"{name}: {text}")
    if greet:
        # 前回の会話から長期間経過していたら不在への言及を先に表示する
        if mood is not None:
            absence_msg = _absence_message(mood, name, lang)
            if absence_msg:
                _say(absence_msg)
        # 好感度レベルがあれば、関係性に応じたあいさつを優先する
        level = mood.level if mood is not None else None
        greeting = persona.greeting(level=level)
        if greeting:
            # 呼び名が分かっていれば冒頭に添えて「覚えている」ことを示す
            # （文頭の呼びかけは日英どちらでも自然: 「たろう、おはよう」/「Taro, ...」）
            # 既定値は "" ではなく None（getattr の typeshed オーバーロードは
            # 空文字だと bool 版に当たって型が合わない）。空文字も None も
            # falsy なので判定結果は変わらない。
            if profile is not None and getattr(profile, "name", None) \
                    and "{user}" not in greeting:
                sep = ", " if lang == "en" else "、"
                greeting = f"{profile.name}{sep}{greeting}"
            _say(greeting)
        # デイリーログイン: その日初回なら好感度ボーナス＋お祝い（連続日数を追う）
        if mood is not None and _check_daily_login is not None:
            try:
                login_msg = _check_daily_login(mood, lang=lang)
                if login_msg:
                    _say(login_msg)
            except Exception:  # pragma: no cover - defensive
                pass
        # 出会ってからの記念日（節目）に達していたら祝う
        if mood is not None and _anniversary_message_fn is not None:
            try:
                anniv = _anniversary_message_fn(mood, lang=lang)
                if anniv:
                    _say(anniv)
            except Exception:  # pragma: no cover - defensive
                pass
        # 誕生日なら祝う（年 1 回、好感度ボーナス付き）— 恋愛ゲームの定番演出
        if profile is not None and _birthday_greeting is not None:
            try:
                bday = _birthday_greeting(profile, lang=lang)
                if bday:
                    _say(bday)
                    if mood is not None and _BIRTHDAY_BONUS:
                        try:
                            mood.adjust(_BIRTHDAY_BONUS)
                        except Exception:  # pragma: no cover - defensive
                            pass
                    # 祝った年フラグ等を永続化（重複祝いを防ぐ）
                    if _profile_path is not None:
                        profile.save(_profile_path())
            except Exception:  # pragma: no cover - defensive
                pass
        # 季節イベント（正月・バレンタイン・クリスマス等）の特別あいさつ
        # 好感度レベルがあれば関係の深さに応じた特別版を優先する
        if _seasonal_greeting is not None:
            try:
                season_level = mood.level if mood is not None else None
                season = _seasonal_greeting(lang=lang, level=season_level)
                if season:
                    _say(season)
            except Exception:  # pragma: no cover - defensive
                pass

        # デイリームード（その日のアバターの気質を一言で添える）
        if _get_daily_mood is not None and _mood_description is not None:
            try:
                # 日付のみで決定（名前 salt は使わない）。可変の呼び名で日中に
                # 気分が変わったり、ギフト経路と食い違ったりするのを防ぐ。
                dmood = _get_daily_mood()
                desc = _mood_description(dmood, lang=lang)
                if desc:
                    _say(desc)
            except Exception:  # pragma: no cover - defensive
                pass

        # 気分への寄り添い（自発）: 直近の発話に明確なトレンドがある時だけ、
        # あいさつに続けてそっと一言添える。トレンド無し/データ不足なら何も言わない
        # ので、普段のあいさつを邪魔しない。会話ログは実際に書き込む先（conv_log）
        # を参照し、テストの一時ログでは発話ゼロ→無言になる。
        if mood is not None and _wellbeing_summary is not None and _wellbeing_message is not None:
            try:
                _wb_path = getattr(conv_log, "logfile", None)
                summary = (_wellbeing_summary(event_log_path=_wb_path, days=3)
                           if _wb_path else _wellbeing_summary(days=3))
                wb = _wellbeing_message(summary, lang=lang)
                if wb:
                    _say(wb)
            except Exception:  # pragma: no cover - defensive
                pass
    output_fn(_help_text(lang, with_disclosure=False))

    # AI であることをセッション開始時に必ず伝える（NY AI Companion Models 法 /
    # CA SB 243）。以降は 3 時間ごとにリマインドする。greet の有無に関わらず出す。
    _last_ai_disclosure_ts: Optional[float] = None
    if _ai_disclosure is not None:
        _say(_ai_disclosure.session_notice(lang))
        _last_ai_disclosure_ts = _time.time()

    exchanges = 0
    # 一問一答（getting-to-know-you）: アバターが質問を出すと、その答え待ち状態の
    # facts キーをここに保持する。次のユーザー発話（コマンド以外）を回答として記憶する。
    pending_fact_key: Optional[str] = None
    # /reset-mood の二段階確認フラグ（誤操作による好感度全消しを防ぐ）
    _reset_mood_pending: bool = False
    # /forget-me の二段階確認フラグ（誤操作による個人情報全消去を防ぐ）
    _forget_me_pending: bool = False
    # /clear-log の二段階確認フラグ（誤操作による会話履歴全消去を防ぐ）
    _clear_log_pending: bool = False
    while True:
        try:
            raw = input_fn("You: ")
        except (EOFError, KeyboardInterrupt):
            # パイプ終端 / Ctrl-D / Ctrl-C はループ終了として扱う
            output_fn("")
            break

        if raw is None:
            break
        text = raw.strip()
        if not text:
            continue

        # /reset-mood の確認待ちが他のコマンド/テキストでキャンセルされた場合
        if _reset_mood_pending and text.lower() not in _MOOD_RESET_COMMANDS:
            _reset_mood_pending = False
        # /forget-me の確認待ちが他のコマンド/テキストでキャンセルされた場合
        if _forget_me_pending and text.lower() not in _FORGET_ME_COMMANDS:
            _forget_me_pending = False
        # /clear-log の確認待ちが他のコマンド/テキストでキャンセルされた場合
        if _clear_log_pending and text.lower() not in _CLEAR_LOG_COMMANDS:
            _clear_log_pending = False

        # コマンド処理
        if text.lower() in _QUIT_COMMANDS:
            farewell = persona.respond("さようなら") or "またね！"
            _say(farewell)
            break
        if text.lower() == "/help":
            output_fn(_help_text(lang))
            continue
        if text.lower() == "/name":
            output_fn(f"{name}")
            continue
        if text.lower() == "/callme" or text.lower().startswith("/callme "):
            new_name = text[len("/callme"):].strip()
            reply = _set_user_name(profile, new_name, name, lang, output_fn)
            if conv_log is not None and reply:
                conv_log.log_exchange(text, reply)
            continue
        if text.lower() == "/birthday" or text.lower().startswith("/birthday "):
            new_bday = text[len("/birthday"):].strip()
            reply = _set_birthday(profile, new_bday, name, lang, output_fn)
            if conv_log is not None and reply:
                conv_log.log_exchange(text, reply)
            continue
        if text.lower() == "/gift" or text.lower().startswith("/gift "):
            item = text[len("/gift"):].strip()
            gift_reply = _give_gift(item, mood, name, lang, output_fn)
            if conv_log is not None and gift_reply:
                conv_log.log_exchange(text, gift_reply)
            continue
        if text.lower() == "/like" or text.lower().startswith("/like "):
            thing = text[len("/like"):].strip()
            reply = _add_interest(profile, thing, name, lang, output_fn)
            if conv_log is not None and reply:
                conv_log.log_exchange(text, reply)
            continue
        # /forget-me は /forget より具体的なので先に判定する（前方一致の誤爆防止）
        if text.lower() in _FORGET_ME_COMMANDS:
            if not _forget_me_pending:
                if lang == "en":
                    output_fn(f"{name}: This will erase everything I remember about you "
                              "(name, birthday, interests, and answers). "
                              "Type /forget-me again to confirm.")
                else:
                    output_fn(f"{name}: 覚えている個人情報（呼び名・誕生日・趣味・会話で覚えたこと）を"
                              "すべて消去します。本当によければ、もう一度 /forget-me を入力してください。")
                _forget_me_pending = True
            else:
                _forget_me(profile, lang, output_fn)
                _forget_me_pending = False
            continue
        # /forget-fact は /forget より具体的なので先に判定する（前方一致の誤爆防止）
        if text.lower() == "/forget-fact" or text.lower().startswith("/forget-fact "):
            fact_text = text[len("/forget-fact"):].strip()
            reply = _remove_fact(profile, fact_text, name, lang, output_fn)
            if conv_log is not None and reply:
                conv_log.log_exchange(text, reply)
            continue
        if text.lower() == "/forget" or text.lower().startswith("/forget "):
            thing = text[len("/forget"):].strip()
            reply = _remove_interest(profile, thing, name, lang, output_fn)
            if conv_log is not None and reply:
                conv_log.log_exchange(text, reply)
            continue
        if text.lower() == "/whoami":
            _print_user_name(profile, lang, output_fn)
            continue
        if text.lower() == "/history":
            _print_history(conv_log, output_fn)
            continue
        if text.lower() == "/mood":
            _print_mood(mood, lang, output_fn)
            continue
        if text.lower() in _MOOD_RESET_COMMANDS:
            if not _reset_mood_pending:
                if lang == "en":
                    output_fn(f"{name}: This will reset our relationship to neutral. "
                              "Type /reset-mood again to confirm.")
                else:
                    output_fn(f"{name}: 好感度をニュートラルにリセットします。"
                              "本当によければ、もう一度 /reset-mood を入力してください。")
                _reset_mood_pending = True
            else:
                _reset_mood(mood, lang, output_fn)
                _reset_mood_pending = False
            continue
        if text.lower() == "/stats":
            _print_stats(conv_log, exchanges, lang, output_fn)
            continue
        if text.lower() == "/recap":
            _print_recap(conv_log, lang, output_fn)
            continue
        if text.lower() in ("/feeling", "/checkin"):
            _print_feeling(lang, output_fn)
            continue
        if text.lower() == "/search" or text.lower().startswith("/search "):
            query = text[len("/search"):].strip()
            _print_search(conv_log, query, output_fn, lang)
            continue
        if text.lower() == "/export-log" or text.lower().startswith("/export-log "):
            dest = text[len("/export-log"):].strip() or "conversation_export.csv"
            _export_log(conv_log, dest, lang, output_fn)
            continue
        if text.lower() in _CLEAR_LOG_COMMANDS:
            if not _clear_log_pending:
                if lang == "en":
                    output_fn(f"{name}: This will erase the ENTIRE conversation history "
                              "(including archives). Type /clear-log again to confirm.")
                else:
                    output_fn(f"{name}: 会話履歴を（アーカイブも含めて）すべて消去します。"
                              "本当によければ、もう一度 /clear-log を入力してください。")
                _clear_log_pending = True
            else:
                _clear_log(conv_log, lang, output_fn)
                _clear_log_pending = False
            continue

        # ---------- 危機表明（自傷・自殺念慮）----------
        # スラッシュコマンドの次、他のどの処理よりも先に扱う。ここで打ち切ることで、
        # 危機の開示が好感度・会話回数・プロフィール記憶・聞き返し質問といった
        # 「関係を進める」仕掛けに一切流れ込まないようにする（ゲーム化しない）。
        # GUI 側 (avatar_3d_autonomous_tts.speak_comment) と同じ扱い。
        if _crisis_reply is not None:
            try:
                support = _crisis_reply(text, lang=lang)
            except Exception:  # pragma: no cover - defensive
                support = ""
            if support:
                pending_fact_key = None  # Q&A の答えとして記録しない
                _say(support)
                if conv_log is not None:
                    try:
                        conv_log.log_exchange(text, support)
                    except Exception:  # pragma: no cover - defensive
                        pass
                continue

        # 一問一答の回答待ちなら、このコマンド以外の発話を答えとして記憶する。
        # 確認文 (ack) を後段の reply に前置する（会話は通常どおり続ける）。
        ack_msg = ""
        if pending_fact_key and profile is not None and _acknowledge_answer is not None:
            try:
                saved = profile.set_fact(pending_fact_key, text)
                if saved:
                    ack_msg = _acknowledge_answer(pending_fact_key, saved, lang=lang)
                    if _profile_path is not None:
                        profile.save(_profile_path())
            except Exception:  # pragma: no cover - defensive
                pass
            pending_fact_key = None

        # 好感度を更新（指定時のみ）
        milestone_msg = ""
        hurt_msg = ""
        if mood is not None:
            try:
                before_affinity = mood.affinity
                before_interactions = mood.interactions
                raw_delta = mood.register(text)
                # デイリームードによる好感度感度変調（明るい日は上がりやすい）
                if raw_delta != 0 and _get_daily_mood is not None and _mood_affinity_multiplier is not None:
                    try:
                        # 日付のみで決定（名前 salt は使わない）— 全経路で同じ気分にする
                        dmood = _get_daily_mood()
                        multiplier = _mood_affinity_multiplier(dmood)
                        if multiplier != 1.0:
                            extra = raw_delta * (multiplier - 1.0)
                            mood.adjust(extra)
                    except Exception:
                        pass
                # 謝罪・おやすみルーティン: 小さな好感度ボーナスで「仲直り/就寝の習慣」を演出
                ritual = _detect_ritual_event(text)
                if ritual is not None:
                    mood.adjust(ritual[1])
                # 傷つきイベント: 大きな好感度低下で通常応答を感情反応に差し替える
                hurt_msg = ""
                if _check_hurt_event is not None:
                    hurt_msg = _check_hurt_event(raw_delta, lang=lang) or ""
                after_affinity = mood.affinity
                # 告白イベント（friendly→close の初回のみ）
                if _check_confession_event is not None:
                    confession = _check_confession_event(mood, before_affinity, after_affinity, lang=lang)
                    if confession:
                        milestone_msg = confession
                # 関係ステージ変化（告白でない場合は通常マイルストーン）
                if not milestone_msg and _check_level_milestone is not None:
                    ms = _check_level_milestone(before_affinity, after_affinity, lang=lang)
                    if ms and ms.get("message"):
                        milestone_msg = ms["message"]
                # 視覚的バナー（ステージ変化時）
                if milestone_msg and _affinity_label is not None and callable(affinity_level):
                    new_level = affinity_level(after_affinity) if after_affinity != before_affinity else None
                    if new_level and affinity_level(before_affinity) != new_level:
                        fl = _affinity_label(before_affinity, lang)
                        tl = _affinity_label(after_affinity, lang)
                        arrow = "↑" if after_affinity > before_affinity else "↓"
                        rel_label = "Relationship" if lang == "en" else "関係"
                        output_fn(f"── {rel_label}: {fl} {arrow} {tl} ──")
                # 会話回数マイルストーン（節目ごとに一言）
                if not milestone_msg and _check_interaction_milestone is not None:
                    inter_ms = _check_interaction_milestone(
                        before_interactions, mood.interactions, lang=lang
                    )
                    if inter_ms:
                        milestone_msg = inter_ms
                # save confession_done persistently so a mid-session crash
                # does not allow the once-per-lifetime confession to replay
                if milestone_msg and getattr(mood, "_confession_done", False):
                    try:
                        from mood import _default_mood_path as _mp
                        mood.save(_mp())
                    except Exception:
                        pass
            except Exception:  # pragma: no cover - defensive
                pass

        # 通常の会話 (好感度レベルがあれば mood-specific ルールを優先)
        level = mood.level if mood is not None else None
        # 傷つきイベント: 通常応答を上書き（マイルストーンは引き続き添付）
        if hurt_msg:
            reply = hurt_msg
        else:
            # conv_log=None: suppress internal logging so we log the full composed reply below
            reply = respond_to(text, persona, None, level=level)
        if milestone_msg:
            reply = (reply + " " + milestone_msg).strip() if reply else milestone_msg
        # 一問一答の回答を覚えたら、その確認をすぐ前置きして「ちゃんと聞いてる」を示す
        if ack_msg:
            reply = (ack_msg + " " + reply).strip() if reply else ack_msg
        exchanges += 1
        # 数回ごとにアバターから話題を振る（受け身すぎないように）。
        # ただし返答が既に疑問文で終わっていれば二重質問を避ける。
        # 別れの挨拶には絶対に付けない。「またね！ところでストレス発散は
        # どうしてる？」は、去ろうとしている相手に応答の義務を作る形であり、
        # farewell_integrity が PRESSURE_TO_RESPOND として禁じている型そのもの
        # である。あちらは台詞そのものを検査するが、ここは「別れの直後に質問を
        # 連結する」という組み立て側の漏れだったので、入口で止める。
        # つらさを打ち明けられた直後にも付けない。「ひとりで抱えなくていい
        # からね。 最近どんなことが楽しかった？」は、受け止めた直後に楽しい
        # 話題へ振り直す形で、共感を帳消しにする。別れと同じく、話題を進める
        # 権利は相手の側にある。
        _leaving = _is_farewell is not None and _is_farewell(text)
        _hurting = _is_distressed is not None and _is_distressed(text)
        if _FOLLOW_UP_EVERY > 0 and exchanges % _FOLLOW_UP_EVERY == 0 \
                and not _leaving and not _hurting \
                and not reply.rstrip().endswith(("？", "?")):
            try:
                question = ""
                recall_levels = {"neutral", "friendly", "close"}
                # getting-to-know-you: neutral 以上かつ未回答の質問があれば、半々の確率で
                # アバターから質問して回答待ち状態にする（Q&A ループの起点）。
                if (level in recall_levels and profile is not None
                        and pending_fact_key is None
                        and _next_unanswered_question is not None):
                    import random as _rnd
                    if _rnd.random() < 0.5:
                        qpair = _next_unanswered_question(profile, lang)
                        if qpair:
                            pending_fact_key, question = qpair
                # 8 交換ごと: 覚えた事実→趣味の順で思い出し話題を振る
                if (not question and exchanges % (_FOLLOW_UP_EVERY * 2) == 0
                        and profile is not None and level in recall_levels):
                    if _recall_fact is not None:
                        question = _recall_fact(profile, lang)
                    if not question and getattr(profile, "interests", []):
                        question = _interest_recall(profile, lang)
                if not question:
                    question = persona.follow_up_question(level=level)
            except Exception:  # pragma: no cover - defensive
                question = ""
            if question:
                reply = (reply + " " + question).strip() if reply else question
        # AI であることの定期開示（前回から 3 時間以上の継続利用で 1 回）。
        # 演出の外側に置くため、応答とは別行で先に出す。
        if _ai_disclosure is not None and _ai_disclosure.is_due(_last_ai_disclosure_ts):
            _say(_ai_disclosure.periodic_notice(lang))
            _last_ai_disclosure_ts = _time.time()
        _say(reply)
        # Log the fully-composed reply (hurt override + milestone + ack + follow-up included)
        if conv_log is not None:
            try:
                conv_log.log_exchange(text, reply)
            except Exception:  # pragma: no cover - defensive: log failure must not stop chat
                pass

    return exchanges


def _interest_recall(profile, lang: str = "ja") -> str:
    """記憶した趣味のうちランダムな 1 件を引用した思い出し質問を返す。

    趣味が無い / プロファイルが None の場合は空文字を返す。
    """
    import random
    interests = getattr(profile, "interests", [])
    if not interests:
        return ""
    item = random.choice(interests)
    if lang == "en":
        templates = [
            f"Hey, you mentioned liking {item}! Any updates on that?",
            f"Speaking of {item} — anything new there?",
            f"So, still into {item}?",
        ]
    else:
        templates = [
            f"そういえば{item}が好きって言ってたよね。最近どう？",
            f"{item}の話、もっと聞かせて？",
            f"ねえ、{item}って最近どんな感じ？",
        ]
    return random.choice(templates)


def _absence_message(mood, name: str, lang: str) -> str:  # name is kept for API compat
    """前回の会話から長期間経過していた場合に不在への言及メッセージを返す。

    24 時間未満・初回・会話回数 0 の場合は空文字を返す。
    mood.absence_message() に委譲する（GUI 自律モードとの共有ヘルパ）。
    """
    if _absence_message_fn is not None:
        return _absence_message_fn(mood, lang=lang)
    return ""


def _next_interaction_milestone(interactions: int) -> Optional[int]:
    """次に到達する会話回数の節目を返す。全節目を超えていれば None。"""
    try:
        from mood import _INTERACTION_MILESTONES_SORTED
    except Exception:  # pragma: no cover - defensive
        return None
    for m in _INTERACTION_MILESTONES_SORTED:
        if interactions < m:
            return m
    return None


def _print_mood(mood, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在の好感度レベルとデイリームードを表示する。"""
    if mood is None:
        output_fn("(好感度は無効です)")
        return
    try:
        label = mood.label(lang)
        score = int(round(mood.affinity))
    except Exception:  # pragma: no cover - defensive
        output_fn("(好感度を取得できません)")
        return
    prefix = "Affinity" if lang == "en" else "好感度"
    output_fn(f"{prefix}: {label} ({score}/100)")
    # 関係性の統計（会話回数・出会ってからの日数）を添える
    try:
        interactions = int(getattr(mood, "interactions", 0) or 0)
        if interactions > 0:
            next_ms = _next_interaction_milestone(interactions)
            if lang == "en":
                line = f"Conversations: {interactions}"
                if next_ms:
                    line += f" (next milestone at {next_ms})"
                output_fn(line)
            else:
                line = f"会話回数: {interactions}回"
                if next_ms:
                    line += f"（次の節目は{next_ms}回）"
                output_fn(line)
        # 出会ってからの日数
        import time as _time
        first_ts = getattr(mood, "_first_interaction_time", 0.0) or 0.0
        if first_ts > 0:
            days = int((_time.time() - first_ts) / 86400.0)
            if lang == "en":
                unit = "day" if days == 1 else "days"
                output_fn(f"We've known each other for {days} {unit}.")
            else:
                output_fn(f"出会ってから{days}日目だよ。")
        # 連続ログイン日数
        streak = int(getattr(mood, "_login_streak", 0) or 0)
        if streak >= 2:
            if lang == "en":
                output_fn(f"Login streak: {streak} days in a row! 🔥")
            else:
                output_fn(f"連続ログイン: {streak}日連続！🔥")
    except Exception:  # pragma: no cover - defensive
        pass
    # デイリームードを添える（好感度変調倍率も表示して効果を見える化）
    if _get_daily_mood is not None and _mood_label is not None and _mood_emoji is not None:
        try:
            # 日付のみで決定（名前 salt は使わない）— /mood 表示とギフト倍率を一致させる
            dmood = _get_daily_mood()
            emoji = _mood_emoji(dmood)
            dlabel = _mood_label(dmood, lang)
            dmood_prefix = "Today's mood" if lang == "en" else "今日の気分"
            mood_line = f"{dmood_prefix}: {emoji} {dlabel}"
            if _mood_affinity_multiplier is not None:
                mult = _mood_affinity_multiplier(dmood)
                if mult != 1.0:
                    pct = int(round((mult - 1.0) * 100))
                    sign = "+" if pct > 0 else ""
                    if lang == "en":
                        mood_line += f" (affinity gain {sign}{pct}%)"
                    else:
                        mood_line += f"（好感度変化 {sign}{pct}%）"
            output_fn(mood_line)
        except Exception:  # pragma: no cover - defensive
            pass
    # 低好感度のときは関係改善のヒントを出す
    try:
        level = mood.level
        if level in ("distant", "reserved"):
            if lang == "en":
                output_fn("Tip: Try chatting more, giving a gift (/gift), or saying nice things!")
            else:
                output_fn("ヒント: もっとおしゃべりしたり、/gift でプレゼントを贈ったりしてみて！")
    except Exception:  # pragma: no cover - defensive
        pass


def _reset_mood(mood, lang: str, output_fn: Callable[[str], None]) -> None:
    """好感度をデフォルト（neutral）にリセットする。"""
    if mood is None:
        output_fn("(好感度は無効です)")
        return
    try:
        from mood import AFFINITY_START
        mood.affinity = AFFINITY_START
        mood.interactions = 0
        mood._last_interaction_time = 0.0
        # リセットは「関係の仕切り直し」: 出会いの起点と記念日マーカーも消す
        mood._first_interaction_time = 0.0
        mood._last_anniversary_days = 0
        # 告白フラグも仕切り直す（仲良し度を再び積み上げれば告白シーンが再発火できる）
        mood._confession_done = False
        # デイリーログインの連続記録も仕切り直す
        mood._last_login_date = ""
        mood._login_streak = 0
        if lang == "en":
            output_fn(f"Affinity reset to neutral ({int(AFFINITY_START)}/100).")
        else:
            output_fn(f"好感度をニュートラル（{int(AFFINITY_START)}/100）にリセットしました。")
    except Exception:  # pragma: no cover - defensive
        output_fn("(好感度のリセットに失敗しました)")


def _forget_me(profile, lang: str, output_fn: Callable[[str], None]) -> None:
    """覚えた個人情報（呼び名・誕生日・趣味・記憶）をすべて消去し、永続化する。

    プライバシー配慮: ユーザーがいつでも自分のデータを消せるようにする。
    好感度（関係の深さ）はここでは消さない（/reset-mood が担当）。
    """
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    try:
        profile.clear()
        if _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(個人情報の消去に失敗しました)")
        return
    if lang == "en":
        output_fn("Okay — I've forgotten everything personal about you. "
                  "We can start fresh whenever you like.")
    else:
        output_fn("わかった、あなたのことは全部忘れたよ。"
                  "また、いつでも教えてね。")


def _set_user_name(profile, new_name: str, avatar_name: str, lang: str,
                   output_fn: Callable[[str], None]) -> str:
    """ユーザーの呼び名を設定して永続化し、アバターが確認の返事をする。返事テキストを返す（ログ用）。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return ""
    if not new_name:
        output_fn(command_usage("callme", lang))
        return ""
    try:
        saved = profile.set_name(new_name)
        if _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(呼び名の保存に失敗しました)")
        return ""
    if not saved:
        output_fn("(その名前は使えません)")
        return ""
    if lang == "en":
        reply = f"Got it — I'll call you {saved} from now on!"
    else:
        reply = f"わかった、これからは{saved}って呼ぶね！"
    output_fn(f"{avatar_name}: {reply}")
    return reply


def _set_birthday(profile, new_bday: str, avatar_name: str, lang: str,
                  output_fn: Callable[[str], None]) -> str:
    """ユーザーの誕生日（MM-DD）を設定して永続化し、アバターが確認の返事をする。返事テキストを返す（ログ用）。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return ""
    if not new_bday:
        output_fn(command_usage("birthday", lang))
        return ""
    try:
        saved = profile.set_birthday(new_bday)
        if saved and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(誕生日の保存に失敗しました)")
        return ""
    if not saved:
        if lang == "en":
            output_fn("Please use MM-DD, e.g. /birthday 06-15.")
        else:
            output_fn("MM-DD 形式で教えてね。例: /birthday 06-15")
        return ""
    if lang == "en":
        reply = f"Got it — your birthday is {saved}. I won't forget it!"
    else:
        reply = f"覚えた、誕生日は{saved}だね。忘れないよ！"
    output_fn(f"{avatar_name}: {reply}")
    return reply


def _give_gift(item: str, mood, avatar_name: str, lang: str,
               output_fn: Callable[[str], None]) -> str:
    """ユーザーがアバターにプレゼントを贈り、好感度ボーナスと反応台詞を返す。

    アバターの返事テキストを返す（ログ用）。交換が発生しなかった場合は空文字。
    """
    if not item or item.lower() == "list":
        if _gift_catalog_text is not None:
            # 今日すでに贈ったギフトをマーク（贈ってから断られる体験を避ける）
            given_today: set = set()
            if mood is not None and _all_gift_keys is not None \
                    and hasattr(mood, "gift_received_today"):
                try:
                    given_today = {k for k in _all_gift_keys()
                                   if mood.gift_received_today(k)}
                except Exception:
                    given_today = set()
            cat = _gift_catalog_text(lang, given_keys=given_today or None)
            if lang == "en":
                output_fn("Available gifts (bonus):")
            else:
                output_fn("贈れるプレゼント一覧（ボーナス）:")
            output_fn(cat)
        else:
            output_fn(command_usage("gift", lang))
        return ""
    if _lookup_gift is None:
        output_fn("(プレゼント機能は利用できません)")
        return ""
    current_level = mood.level if mood is not None and hasattr(mood, "level") else None
    # デイリークールダウン: 同じギフトを今日すでに贈った場合は断る
    if mood is not None and _lookup_gift_key is not None:
        try:
            gift_key = _lookup_gift_key(item, lang=lang)
            if gift_key and hasattr(mood, "gift_received_today") and mood.gift_received_today(gift_key):
                msg = (_gift_cooldown_message(lang)
                       if _gift_cooldown_message is not None else "")
                if not msg:
                    msg = "また明日ね。" if lang != "en" else "Come back tomorrow!"
                output_fn(f"{avatar_name}: {msg}")
                return ""
        except Exception:
            pass
    result = _lookup_gift(item, lang=lang, level=current_level)
    if result is None:
        if lang == "en":
            output_fn(f"Hmm, I'm not sure about {item}. Try /gift list to see options.")
        else:
            output_fn(f"「{item}」はよく分からないな。/gift list で確認してね。")
        return ""
    bonus, reply = result
    _say_fn = lambda text: output_fn(f"{avatar_name}: {text}")  # noqa: E731
    _say_fn(reply)
    if bonus <= 0.0:
        # min_level 未達: 断り文句のみ、ボーナス表示・保存なし
        return reply
    # デイリームードの倍率を好感度ボーナスに適用（energetic は +20% など）
    effective_bonus = bonus
    if _get_daily_mood is not None and _mood_affinity_multiplier is not None:
        try:
            mult = _mood_affinity_multiplier(_get_daily_mood())
            effective_bonus = bonus * mult
        except Exception:
            pass
    # 好感度ボーナスを適用し、即時保存（Ctrl+C 等でもボーナスが消えないよう）
    if mood is not None:
        try:
            mood.adjust(effective_bonus)
            # 受け取り記録（デイリークールダウン用）
            if hasattr(mood, "record_gift") and _lookup_gift_key is not None:
                try:
                    gk = _lookup_gift_key(item, lang=lang)
                    if gk:
                        mood.record_gift(gk)
                except Exception:
                    pass
            try:
                from mood import _default_mood_path, _default_mood_history_path
                mood.save(_default_mood_path())
                mood.snapshot_to_history(_default_mood_history_path())
            except Exception:
                pass
        except Exception:
            pass
    if lang == "en":
        output_fn(f"(+{round(effective_bonus)} affinity)")
    else:
        output_fn(f"（好感度 +{round(effective_bonus)}）")
    return reply


def _add_interest(profile, thing: str, avatar_name: str, lang: str,
                  output_fn: Callable[[str], None]) -> str:
    """ユーザーの趣味を追加して永続化する。アバターの返事テキストを返す（ログ用）。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return ""
    if not thing:
        output_fn(command_usage("like", lang))
        return ""
    try:
        saved = profile.add_interest(thing)
        if saved and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(保存に失敗しました)")
        return ""
    if not saved:
        if lang == "en":
            output_fn("Couldn't save that — maybe the list is full (max 10)?")
        else:
            output_fn("うまく保存できなかったよ（上限10件かも？）")
        return ""
    if lang == "en":
        reply = f"Oh, you like {saved}? I'll remember that!"
    else:
        reply = f"{saved}が好きなんだね！覚えておくよ。"
    output_fn(f"{avatar_name}: {reply}")
    return reply


def _remove_interest(profile, thing: str, avatar_name: str, lang: str,
                     output_fn: Callable[[str], None]) -> str:
    """ユーザーの趣味を削除して永続化する。アバターの返事テキストを返す（ログ用）。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return ""
    if not thing:
        output_fn(command_usage("forget", lang))
        return ""
    try:
        removed = profile.remove_interest(thing)
        if removed and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(削除に失敗しました)")
        return ""
    if removed:
        if lang == "en":
            reply = f"Got it, I'll forget about {thing}."
        else:
            reply = f"わかった、{thing}のこと忘れておくね。"
        output_fn(f"{avatar_name}: {reply}")
        return reply
    else:
        if lang == "en":
            output_fn(f"I don't have '{thing}' in my memory.")
        else:
            output_fn(f"「{thing}」は覚えてないよ。")
        return ""


def _remove_fact(profile, text: str, avatar_name: str, lang: str,
                 output_fn: Callable[[str], None]) -> str:
    """一問一答で覚えた事実を削除して永続化する。アバターの返事テキストを返す（ログ用）。

    /whoami は fact のキーではなく回答テキスト（値）のみを表示するため、
    ユーザーはキーを知らない。よって値の大文字小文字を無視した部分一致で
    キーを逆引きしてから remove_fact(key) を呼ぶ（/forget が趣味を値で
    削除するのと同じ操作感にする）。
    """
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return ""
    if not text:
        output_fn(command_usage("forget-fact", lang))
        return ""
    facts = getattr(profile, "facts", {}) or {}
    needle = text.strip().lower()
    matched_key: Optional[str] = None
    for key, value in facts.items():
        if needle in str(value).strip().lower():
            matched_key = key
            break
    if matched_key is None:
        if lang == "en":
            output_fn(f"I don't have anything like '{text}' in my memory.")
        else:
            output_fn(f"「{text}」に近いことは覚えてないよ。")
        return ""
    try:
        removed = profile.remove_fact(matched_key)
        if removed and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(削除に失敗しました)")
        return ""
    if removed:
        if lang == "en":
            reply = "Okay, I've forgotten that."
        else:
            reply = "わかった、そのこと忘れておくね。"
        output_fn(f"{avatar_name}: {reply}")
        return reply
    if lang == "en":
        output_fn(f"I don't have anything like '{text}' in my memory.")
    else:
        output_fn(f"「{text}」に近いことは覚えてないよ。")
    return ""


def _print_user_name(profile, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在記憶している呼び名・誕生日・趣味・一問一答の事実を表示する。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    if getattr(profile, "name", ""):
        if lang == "en":
            output_fn(f"I'm calling you: {profile.name}")
        else:
            output_fn(f"あなたの呼び名: {profile.name}")
    else:
        if lang == "en":
            output_fn("I don't know your name yet. Try /callme <name>.")
        else:
            output_fn("まだ呼び名を知らないよ。/callme <名前> で教えてね。")
    bday = getattr(profile, "birthday", "")
    if bday:
        if lang == "en":
            output_fn(f"Your birthday: {bday}")
        else:
            output_fn(f"あなたの誕生日: {bday}")
    interests = getattr(profile, "interests", [])
    if interests:
        joined = "、".join(interests) if lang != "en" else ", ".join(interests)
        if lang == "en":
            output_fn(f"Things you like: {joined}")
        else:
            output_fn(f"好きなもの: {joined}")
    facts = getattr(profile, "facts", {})
    if facts:
        if lang == "en":
            output_fn("Things I remember about you:")
        else:
            output_fn("覚えていること:")
        for value in facts.values():
            output_fn(f"  - {value}")


def _print_recap(conv_log, lang: str, output_fn: Callable[[str], None]) -> None:
    """今日の会話サマリーと直近のやりとりを表示する（/recap コマンド）。"""
    is_en = lang.startswith("en")
    has_output = False
    # デイリーサマリーグリーティング（アバター口調）
    if _summary_greeting is not None:
        try:
            greeting = _summary_greeting(lang=lang)
            if greeting:
                output_fn(greeting)
                has_output = True
        except Exception:
            pass
    # 直近 3 件のやりとりをそのまま表示（文脈を思い出せるように）
    if conv_log is not None:
        try:
            recent = conv_log.recent(3)
            if recent:
                output_fn("── Recent exchanges ──" if is_en else "── 直近のやりとり ──")
                from conversation_log import USER_EVENT_TYPES
                for entry in recent:
                    et = entry.get("event_type", "")
                    text = (entry.get("details") or {}).get("text", "")
                    if not text:
                        continue
                    label = ("You" if is_en else "あなた") if et in USER_EVENT_TYPES else "Satin"
                    output_fn(f"  {label}: {text}")
                has_output = True
        except Exception:
            pass
    if not has_output:
        output_fn("No conversations yet today." if is_en else "今日はまだ会話が記録されていません。")


def _print_feeling(lang: str, output_fn: Callable[[str], None]) -> None:
    """直近のユーザー発話の感情傾向から寄り添いの一言を表示する（/feeling）。

    気分が読み取れない（データ不足・中立）ときは、押し付けずニュートラルな一言で返す。
    """
    is_en = lang.startswith("en")
    if _wellbeing_summary is None or _wellbeing_message is None:
        output_fn("(wellbeing unavailable)" if is_en
                  else "(気分の寄り添い機能は利用できません)")
        return
    try:
        summary = _wellbeing_summary(days=3)
        msg = _wellbeing_message(summary, lang=lang)
    except Exception:
        summary, msg = {}, ""
    if msg:
        output_fn(msg)
        return
    # データ不足／中立: そっとした中立メッセージ
    if summary.get("sample_size", 0) < 3:
        output_fn("Let's talk a bit more and I'll get a feel for how you're doing."
                  if is_en else "もう少しお話ししたら、あなたの調子がわかるよ。")
    else:
        output_fn("You seem steady lately — that's good." if is_en
                  else "最近は落ち着いてるみたいだね。いい感じ。")


def _print_stats(conv_log, session_exchanges: int, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在セッションおよび全体の会話統計を表示する。

    `session_exchanges` はスラッシュコマンドを含まない「会話のやりとり」の数で、
    累計側（会話ログ由来）はコマンドも記録に含む。定義が違う 2 つの数を
    「発言数」という同じ語で並べると、コマンドだけ打ったセッションで
    「今回: 0 / 累計: 4」となり、カウンタが壊れているように見える。
    ラベルで区別する。
    """
    is_en = lang.startswith("en")
    if is_en:
        output_fn(f"Conversation turns this session (commands excluded): "
                  f"{session_exchanges}")
    else:
        output_fn(f"今回のセッションの会話: {session_exchanges}件"
                  f"（/ で始まるコマンドは含みません）")
    if conv_log is None:
        return
    try:
        from conversation_log import USER_EVENT_TYPES
        all_events = conv_log.search("", include_archives=True)
        user_msgs = sum(1 for ev in all_events if ev.get("event_type") in USER_EVENT_TYPES)
        avatar_msgs = len(all_events) - user_msgs
        if is_en:
            output_fn(f"Total messages you've sent, all sessions "
                      f"(commands included): {user_msgs}")
            output_fn(f"Total replies from the avatar: {avatar_msgs}")
        else:
            output_fn(f"全セッション累計のあなたの発言: {user_msgs}件"
                      f"（コマンドを含みます）")
            output_fn(f"全セッション累計のアバターの返答: {avatar_msgs}件")
    except Exception:  # pragma: no cover - defensive
        pass


def _print_history(conv_log, output_fn: Callable[[str], None]) -> None:
    """会話ログの直近履歴を表示する。"""
    if conv_log is None:
        output_fn("(会話履歴は利用できません)")
        return
    try:
        lines: List[str] = conv_log.recent_texts(_HISTORY_DEFAULT)
    except Exception:  # pragma: no cover - defensive
        lines = []
    if not lines:
        output_fn("(まだ会話履歴はありません)")
        return
    for line in lines:
        output_fn(line)


def _print_search(conv_log, query: str, output_fn: Callable[[str], None],
                  lang: str = "ja") -> None:
    """会話ログをキーワード検索して結果を表示する（アーカイブ含む）。

    使い方の一行は `command_usage()` から取る。共有化するまで、ここは
    日本語固定で英語ユーザーにも日本語の案内を出していた。
    """
    if conv_log is None:
        output_fn("(会話履歴は利用できません)")
        return
    if not query:
        output_fn(command_usage("search", lang))
        return
    try:
        from conversation_log import USER_EVENT_TYPES
        from datetime import datetime as _dt
        results = conv_log.search(query, include_archives=True)
    except Exception:  # pragma: no cover - defensive
        output_fn("(検索に失敗しました)")
        return
    if not results:
        output_fn(f"(「{query}」に一致する会話は見つかりませんでした)")
        return
    output_fn(f"「{query}」の検索結果: {len(results)} 件")
    for ev in results[-20:]:
        ts = ev.get("timestamp", 0)
        try:
            dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, ValueError, TypeError):
            dt_str = "?"
        prefix = "You" if ev.get("event_type") in USER_EVENT_TYPES else "Avatar"
        text = (ev.get("details") or {}).get("text", "")
        output_fn(f"[{dt_str}] {prefix}: {text}")


def _export_log(conv_log, dest: str, lang: str,
                output_fn: Callable[[str], None]) -> None:
    """会話履歴（アーカイブ含む全件）を CSV ファイルへエクスポートする。

    /forget-me・/reset-mood と同じく「自分のデータを自分で扱える」対称性の
    ための出口。ConversationLog.to_csv() は実装済みだったが REPL から到達
    できなかった（manage_satin log csv のみ）。失敗しても例外は送出しない。
    """
    if conv_log is None:
        output_fn("(会話履歴は利用できません)")
        return
    avatar_label = "Avatar"
    try:
        p = get_persona()
        if p and p.name:
            avatar_label = p.name
    except Exception:
        pass
    try:
        csv_text = conv_log.to_csv(avatar_label=avatar_label, include_archives=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(csv_text)
    except Exception:  # pragma: no cover - defensive
        if lang == "en":
            output_fn(f"(Failed to export the log to '{dest}')")
        else:
            output_fn(f"(会話履歴のエクスポートに失敗しました: {dest})")
        return
    if lang == "en":
        output_fn(f"Conversation history exported to: {dest}")
    else:
        output_fn(f"会話履歴をエクスポートしました: {dest}")


def _clear_log(conv_log, lang: str, output_fn: Callable[[str], None]) -> None:
    """会話履歴（ライブファイル + gzip アーカイブ）を消去する。

    manage_satin.cmd_log_clear と同じ実体処理だが、あちらは input() 対話
    前提のため REPL では二段階確認（呼び出し側）+ 本ヘルパで行う。
    """
    if conv_log is None:
        output_fn("(会話履歴は利用できません)")
        return
    try:
        import os as _os
        from conversation_log import _find_archives
        path = conv_log.logfile
        archives = _find_archives(path)
        total = (1 if _os.path.exists(path) else 0) + len(archives)
        if total == 0:
            output_fn("(ログファイルが存在しません)" if lang != "en"
                      else "(No log file exists)")
            return
        if _os.path.exists(path):
            open(path, "w", encoding="utf-8").close()
        removed_archives = 0
        for gz in archives:
            try:
                _os.remove(gz)
                removed_archives += 1
            except OSError:
                pass
    except Exception:  # pragma: no cover - defensive
        output_fn("(会話履歴の消去に失敗しました)" if lang != "en"
                  else "(Failed to clear the conversation history)")
        return
    if lang == "en":
        note = f" ({removed_archives} archive(s) removed)" if removed_archives else ""
        output_fn(f"Conversation history cleared.{note}")
    else:
        note = f"（アーカイブ {removed_archives} 件を削除）" if removed_archives else ""
        output_fn(f"会話履歴を消去しました。{note}")


def main(argv: Optional[List[str]] = None) -> int:
    """`python -m persona_cli` / ランチャー --chat 用エントリポイント。"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="persona_cli",
        description="Satin アバターとヘッドレスで会話する CLI",
    )
    parser.add_argument("--lang", default=None, help="会話言語 (例: ja, en)")
    parser.add_argument("--no-greet", action="store_true", help="開始時のあいさつを省略")
    parser.add_argument("--no-mood", action="store_true", help="好感度トラッキングを無効化")
    args = parser.parse_args(argv)

    persona = Persona.load(lang=args.lang) if args.lang else get_persona()

    # 好感度は永続トラッカーを使用（セッションを跨いで関係が育つ）
    mood = None
    if not args.no_mood and get_mood_tracker is not None:
        try:
            mood = get_mood_tracker()
            # 前回セッションからの経過時間に応じて好感度を自然低下させる
            mood.auto_decay()
        except Exception:  # pragma: no cover - defensive
            mood = None

    run_chat(persona=persona, greet=not args.no_greet, mood=mood)

    # 終了時に好感度を保存 + 日次スナップショット
    if mood is not None:
        try:
            from mood import _default_mood_path, _default_mood_history_path
            mood.save(_default_mood_path())
            mood.snapshot_to_history(_default_mood_history_path())
        except Exception:  # pragma: no cover - defensive
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
