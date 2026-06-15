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
  /whoami             今記憶している呼び名を表示
  /mood               好感度レベルを表示
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
    )
except Exception:  # pragma: no cover - defensive
    MoodTracker = None  # type: ignore
    get_mood_tracker = None
    _absence_message_fn = None  # type: ignore
    _anniversary_message_fn = None  # type: ignore
    _check_level_milestone = None  # type: ignore

try:
    from user_profile import (
        get_user_profile, personalize as _personalize,
        _default_profile_path as _profile_path,
    )
except Exception:  # pragma: no cover - defensive
    get_user_profile = None
    _personalize = None  # type: ignore
    _profile_path = None  # type: ignore


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
        "/callme <名前> 呼び名設定 | /whoami 呼び名確認 | /mood 好感度 | "
        "/reset-mood リセット | /stats 統計 | /name 名前 | /quit 終了"
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
        # 出会ってからの記念日（節目）に達していたら祝う
        if mood is not None and _anniversary_message_fn is not None:
            try:
                anniv = _anniversary_message_fn(mood, lang=lang)
                if anniv:
                    _say(anniv)
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
                mood.register(text)
                if _check_level_milestone is not None:
                    ms = _check_level_milestone(before_affinity, mood.affinity, lang=lang)
                    if ms and ms.get("message"):
                        milestone_msg = ms["message"]
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
                question = persona.follow_up_question(level=level)
            except Exception:  # pragma: no cover - defensive
                question = ""
            if question:
                reply = (reply + " " + question).strip() if reply else question
        _say(reply)

    return exchanges


def _absence_message(mood, name: str, lang: str) -> str:  # name is kept for API compat
    """前回の会話から長期間経過していた場合に不在への言及メッセージを返す。

    24 時間未満・初回・会話回数 0 の場合は空文字を返す。
    mood.absence_message() に委譲する（GUI 自律モードとの共有ヘルパ）。
    """
    if _absence_message_fn is not None:
        return _absence_message_fn(mood, lang=lang)
    return ""


def _print_mood(mood, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在の好感度レベルを表示する。"""
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


def _print_user_name(profile, lang: str, output_fn: Callable[[str], None]) -> None:
    """現在記憶している呼び名を表示する。"""
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
