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
  /callme <名前>       アバターに呼んでほしい名前を覚えさせる
  /birthday MM-DD      誕生日を覚えさせる（当日に祝ってくれる）
  /like <好きなもの>    好きなものを覚えさせる（例: /like アニメ）
  /forget <好きなもの>  覚えた好きなものを忘れさせる
  /gift <プレゼント>    アバターにプレゼントを贈る（/gift list でカタログ表示）
  /whoami             今記憶している呼び名・誕生日・好きなものを表示
  /mood               好感度レベルと今日のアバターの気分を表示
  /reset-mood         好感度をニュートラルにリセット
  /stats              会話統計を表示
  /name               ペルソナ名を表示
  /quit               終了（/exit, /q も同じ）
"""
from __future__ import annotations

from typing import Callable, List, Optional

from persona import Persona, get_persona

try:
    from conversation_log import ConversationLog, get_conversation_log
except Exception:  # pragma: no cover - defensive
    ConversationLog = None  # type: ignore
    get_conversation_log = None

try:
    from mood import (
        MoodTracker, get_mood_tracker,
        absence_message as _absence_message_fn,
        anniversary_message as _anniversary_message_fn,
        check_level_milestone as _check_level_milestone,
        check_confession_event as _check_confession_event,
        check_interaction_milestone as _check_interaction_milestone,
        check_daily_login as _check_daily_login,
        affinity_level,
        affinity_label as _affinity_label,
    )
except Exception:  # pragma: no cover - defensive
    MoodTracker = None  # type: ignore
    get_mood_tracker = None
    _absence_message_fn = None  # type: ignore
    _anniversary_message_fn = None  # type: ignore
    _check_level_milestone = None  # type: ignore
    _check_confession_event = None  # type: ignore
    _check_interaction_milestone = None  # type: ignore
    _check_daily_login = None  # type: ignore
    affinity_level = None  # type: ignore
    _affinity_label = None  # type: ignore

try:
    from user_profile import (
        get_user_profile, personalize as _personalize,
        _default_profile_path as _profile_path,
    )
except Exception:  # pragma: no cover - defensive
    get_user_profile = None
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
    from gifts import lookup_gift as _lookup_gift, gift_catalog_text as _gift_catalog_text
except Exception:  # pragma: no cover - defensive
    _lookup_gift = None  # type: ignore
    _gift_catalog_text = None  # type: ignore

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


_QUIT_COMMANDS = {"/quit", "/exit", "/q"}
_HISTORY_DEFAULT = 10
_MOOD_RESET_COMMANDS = {"/reset-mood", "/resetmood"}
# N 回ごとにアバターから「聞き返し」質問を添えて会話を続けやすくする
_FOLLOW_UP_EVERY = 4


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


def _help_text() -> str:
    return (
        "コマンド: /help 一覧 | /history 履歴 | /search <キーワード> 検索 | "
        "/callme <名前> 呼び名設定 | /birthday MM-DD 誕生日設定 | /whoami 確認 | "
        "/mood 好感度 | /reset-mood リセット | /stats 統計 | /name 名前 | /quit 終了"
    )


def run_chat(
    persona: Optional[Persona] = None,
    conv_log: "Optional[ConversationLog]" = None,
    input_fn: Optional[Callable[[str], str]] = None,
    output_fn: Optional[Callable[[str], None]] = None,
    greet: bool = True,
    mood: "Optional[MoodTracker]" = None,
    profile=None,
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
            if profile is not None and getattr(profile, "name", "") \
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
        if _seasonal_greeting is not None:
            try:
                season = _seasonal_greeting(lang=lang)
                if season:
                    _say(season)
            except Exception:  # pragma: no cover - defensive
                pass

        # デイリームード（その日のアバターの気質を一言で添える）
        if _get_daily_mood is not None and _mood_description is not None:
            try:
                salt = profile.name if profile is not None else ""
                dmood = _get_daily_mood(salt=salt)
                desc = _mood_description(dmood, lang=lang)
                if desc:
                    _say(desc)
            except Exception:  # pragma: no cover - defensive
                pass
    output_fn(_help_text())

    exchanges = 0
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

        # コマンド処理
        if text.lower() in _QUIT_COMMANDS:
            farewell = persona.respond("さようなら") or "またね！"
            _say(farewell)
            break
        if text.lower() == "/help":
            output_fn(_help_text())
            continue
        if text.lower() == "/name":
            output_fn(f"{name}")
            continue
        if text.lower().startswith("/callme"):
            new_name = text[len("/callme"):].strip()
            _set_user_name(profile, new_name, name, lang, output_fn)
            continue
        if text.lower().startswith("/birthday"):
            new_bday = text[len("/birthday"):].strip()
            _set_birthday(profile, new_bday, name, lang, output_fn)
            continue
        if text.lower().startswith("/gift"):
            item = text[len("/gift"):].strip()
            _give_gift(item, mood, name, lang, output_fn)
            continue
        if text.lower().startswith("/like"):
            thing = text[len("/like"):].strip()
            _add_interest(profile, thing, name, lang, output_fn)
            continue
        if text.lower().startswith("/forget"):
            thing = text[len("/forget"):].strip()
            _remove_interest(profile, thing, name, lang, output_fn)
            continue
        if text.lower() == "/whoami":
            _print_user_name(profile, lang, output_fn)
            continue
        if text.lower() == "/history":
            _print_history(conv_log, output_fn)
            continue
        if text.lower() == "/mood":
            _print_mood(mood, lang, output_fn, profile=profile)
            continue
        if text.lower() in _MOOD_RESET_COMMANDS:
            _reset_mood(mood, lang, output_fn)
            continue
        if text.lower() == "/stats":
            _print_stats(conv_log, exchanges, lang, output_fn)
            continue
        if text.lower().startswith("/search"):
            query = text[len("/search"):].strip()
            _print_search(conv_log, query, output_fn)
            continue

        # 好感度を更新（指定時のみ）
        milestone_msg = ""
        if mood is not None:
            try:
                before_affinity = mood.affinity
                before_interactions = mood.interactions
                raw_delta = mood.register(text)
                # デイリームードによる好感度感度変調（明るい日は上がりやすい）
                if raw_delta != 0 and _get_daily_mood is not None and _mood_affinity_multiplier is not None:
                    try:
                        salt = profile.name if profile is not None else ""
                        dmood = _get_daily_mood(salt=salt)
                        multiplier = _mood_affinity_multiplier(dmood)
                        if multiplier != 1.0:
                            extra = raw_delta * (multiplier - 1.0)
                            mood.adjust(extra)
                    except Exception:
                        pass
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
                        output_fn(f"── 関係: {fl} {arrow} {tl} ──")
                # 会話回数マイルストーン（節目ごとに一言）
                if not milestone_msg and _check_interaction_milestone is not None:
                    inter_ms = _check_interaction_milestone(
                        before_interactions, mood.interactions, lang=lang
                    )
                    if inter_ms:
                        milestone_msg = inter_ms
                # save confession_done persistently
                if milestone_msg and getattr(mood, "_confession_done", False):
                    try:
                        mood.save(mood._path) if hasattr(mood, "_path") else None
                    except Exception:
                        pass
            except Exception:  # pragma: no cover - defensive
                pass

        # 通常の会話 (好感度レベルがあれば mood-specific ルールを優先)
        level = mood.level if mood is not None else None
        reply = respond_to(text, persona, conv_log, level=level)
        if milestone_msg:
            reply = (reply + " " + milestone_msg).strip() if reply else milestone_msg
        exchanges += 1
        # 数回ごとにアバターから話題を振る（受け身すぎないように）。
        # ただし返答が既に疑問文で終わっていれば二重質問を避ける。
        if _FOLLOW_UP_EVERY > 0 and exchanges % _FOLLOW_UP_EVERY == 0 \
                and not reply.rstrip().endswith(("？", "?")):
            try:
                # 8 交換ごと（_FOLLOW_UP_EVERY の 2 倍）かつ趣味が記憶されていれば
                # 趣味を引用した思い出し質問を優先する（level >= neutral のとき）
                question = ""
                recall_levels = {"neutral", "friendly", "close"}
                if (exchanges % (_FOLLOW_UP_EVERY * 2) == 0
                        and profile is not None
                        and getattr(profile, "interests", [])
                        and level in recall_levels):
                    question = _interest_recall(profile, lang)
                if not question:
                    question = persona.follow_up_question(level=level)
            except Exception:  # pragma: no cover - defensive
                question = ""
            if question:
                reply = (reply + " " + question).strip() if reply else question
        _say(reply)

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


def _print_mood(mood, lang: str, output_fn: Callable[[str], None],
                profile=None) -> None:
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
    # デイリームードを添える
    if _get_daily_mood is not None and _mood_label is not None and _mood_emoji is not None:
        try:
            salt = profile.name if profile is not None else ""
            dmood = _get_daily_mood(salt=salt)
            emoji = _mood_emoji(dmood)
            dlabel = _mood_label(dmood, lang)
            dmood_prefix = "Today's mood" if lang == "en" else "今日の気分"
            output_fn(f"{dmood_prefix}: {emoji} {dlabel}")
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
        # デイリーログインの連続記録も仕切り直す
        mood._last_login_date = ""
        mood._login_streak = 0
        if lang == "en":
            output_fn(f"Affinity reset to neutral ({int(AFFINITY_START)}/100).")
        else:
            output_fn(f"好感度をニュートラル（{int(AFFINITY_START)}/100）にリセットしました。")
    except Exception:  # pragma: no cover - defensive
        output_fn("(好感度のリセットに失敗しました)")


def _set_user_name(profile, new_name: str, avatar_name: str, lang: str,
                   output_fn: Callable[[str], None]) -> None:
    """ユーザーの呼び名を設定して永続化し、アバターが確認の返事をする。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    if not new_name:
        output_fn("使用方法: /callme <呼んでほしい名前>")
        return
    try:
        saved = profile.set_name(new_name)
        if _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(呼び名の保存に失敗しました)")
        return
    if not saved:
        output_fn("(その名前は使えません)")
        return
    if lang == "en":
        output_fn(f"{avatar_name}: Got it — I'll call you {saved} from now on!")
    else:
        output_fn(f"{avatar_name}: わかった、これからは{saved}って呼ぶね！")


def _set_birthday(profile, new_bday: str, avatar_name: str, lang: str,
                  output_fn: Callable[[str], None]) -> None:
    """ユーザーの誕生日（MM-DD）を設定して永続化し、アバターが確認の返事をする。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    if not new_bday:
        output_fn("使用方法: /birthday MM-DD （例: /birthday 06-15）")
        return
    try:
        saved = profile.set_birthday(new_bday)
        if saved and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(誕生日の保存に失敗しました)")
        return
    if not saved:
        if lang == "en":
            output_fn("Please use MM-DD, e.g. /birthday 06-15.")
        else:
            output_fn("MM-DD 形式で教えてね。例: /birthday 06-15")
        return
    if lang == "en":
        output_fn(f"{avatar_name}: Got it — your birthday is {saved}. "
                  f"I won't forget it!")
    else:
        output_fn(f"{avatar_name}: 覚えた、誕生日は{saved}だね。忘れないよ！")


def _give_gift(item: str, mood, avatar_name: str, lang: str,
               output_fn: Callable[[str], None]) -> None:
    """ユーザーがアバターにプレゼントを贈り、好感度ボーナスと反応台詞を返す。"""
    if not item or item.lower() == "list":
        if _gift_catalog_text is not None:
            cat = _gift_catalog_text(lang)
            if lang == "en":
                output_fn("Available gifts (bonus):")
            else:
                output_fn("贈れるプレゼント一覧（ボーナス）:")
            output_fn(cat)
        else:
            output_fn("使用方法: /gift <プレゼント>")
        return
    if _lookup_gift is None:
        output_fn("(プレゼント機能は利用できません)")
        return
    result = _lookup_gift(item, lang=lang)
    if result is None:
        if lang == "en":
            output_fn(f"Hmm, I'm not sure about {item}. Try /gift list to see options.")
        else:
            output_fn(f"「{item}」はよく分からないな。/gift list で確認してね。")
        return
    bonus, reply = result
    # 好感度ボーナスを適用
    if mood is not None:
        try:
            mood.adjust(bonus)
        except Exception:
            pass
    _say_fn = lambda text: output_fn(f"{avatar_name}: {text}")  # noqa: E731
    _say_fn(reply)
    if lang == "en":
        output_fn(f"(+{int(bonus)} affinity)")
    else:
        output_fn(f"（好感度 +{int(bonus)}）")


def _add_interest(profile, thing: str, avatar_name: str, lang: str,
                  output_fn: Callable[[str], None]) -> None:
    """ユーザーの趣味を追加して永続化する。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    if not thing:
        if lang == "en":
            output_fn("Usage: /like <thing you enjoy>  e.g. /like anime")
        else:
            output_fn("使用方法: /like <好きなもの>  例: /like アニメ")
        return
    try:
        saved = profile.add_interest(thing)
        if saved and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(保存に失敗しました)")
        return
    if not saved:
        if lang == "en":
            output_fn(f"Couldn't save that — maybe the list is full (max 10)?")
        else:
            output_fn(f"うまく保存できなかったよ（上限10件かも？）")
        return
    if lang == "en":
        output_fn(f"{avatar_name}: Oh, you like {saved}? I'll remember that!")
    else:
        output_fn(f"{avatar_name}: {saved}が好きなんだね！覚えておくよ。")


def _remove_interest(profile, thing: str, avatar_name: str, lang: str,
                     output_fn: Callable[[str], None]) -> None:
    """ユーザーの趣味を削除して永続化する。"""
    if profile is None:
        output_fn("(プロファイルは利用できません)")
        return
    if not thing:
        if lang == "en":
            output_fn("Usage: /forget <thing>  — removes it from memory")
        else:
            output_fn("使用方法: /forget <覚えさせたもの>")
        return
    try:
        removed = profile.remove_interest(thing)
        if removed and _profile_path is not None:
            profile.save(_profile_path())
    except Exception:  # pragma: no cover - defensive
        output_fn("(削除に失敗しました)")
        return
    if removed:
        if lang == "en":
            output_fn(f"{avatar_name}: Got it, I'll forget about {thing}.")
        else:
            output_fn(f"{avatar_name}: わかった、{thing}のこと忘れておくね。")
    else:
        if lang == "en":
            output_fn(f"I don't have '{thing}' in my memory.")
        else:
            output_fn(f"「{thing}」は覚えてないよ。")


def _print_user_name(profile, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在記憶している呼び名・誕生日・趣味を表示する。"""
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


def _print_stats(conv_log, session_exchanges: int, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在セッションおよび全体の会話統計を表示する。"""
    is_en = lang.startswith("en")
    if is_en:
        output_fn(f"Session exchanges: {session_exchanges}")
    else:
        output_fn(f"今回のセッション: {session_exchanges}件")
    if conv_log is None:
        return
    try:
        from conversation_log import USER_EVENT_TYPES
        all_events = conv_log.search("", include_archives=True)
        user_msgs = sum(1 for ev in all_events if ev.get("event_type") in USER_EVENT_TYPES)
        avatar_msgs = len(all_events) - user_msgs
        if is_en:
            output_fn(f"Total user messages (all time): {user_msgs}")
            output_fn(f"Total avatar replies (all time): {avatar_msgs}")
        else:
            output_fn(f"累計ユーザー発言数: {user_msgs}件")
            output_fn(f"累計アバター返答数: {avatar_msgs}件")
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


def _print_search(conv_log, query: str, output_fn: Callable[[str], None]) -> None:
    """会話ログをキーワード検索して結果を表示する（アーカイブ含む）。"""
    if conv_log is None:
        output_fn("(会話履歴は利用できません)")
        return
    if not query:
        output_fn("使用方法: /search <キーワード>")
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
        except (OSError, OverflowError, ValueError):
            dt_str = "?"
        prefix = "You" if ev.get("event_type") in USER_EVENT_TYPES else "Avatar"
        text = (ev.get("details") or {}).get("text", "")
        output_fn(f"[{dt_str}] {prefix}: {text}")


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
