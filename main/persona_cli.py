"""
ペルソナ対話 CLI（ヘッドレス・チャット）。

これまで persona.respond() / conversation_log といった会話機能はすべて Qt GUI
(avatar_3d_autonomous_tts.speak_comment) 経由でしか到達できず、ディスプレイや GPU
の無い環境（サーバー / CI / SSH 越し）ではアバターと会話できなかった。本モジュールは
標準入出力だけで動く REPL を提供し、構築済みのペルソナ・応答・会話ログ機能を
ヘッドレスで使えるようにする。

依存は標準ライブラリのみ。input/output 関数を注入できるため完全にテスト可能。

コマンド:
  /help     コマンド一覧
  /history  会話履歴の直近を表示
  /name     ペルソナ名を表示
  /quit     終了（/exit, /q も同じ）
"""
from __future__ import annotations

from typing import Callable, List, Optional

from persona import Persona, get_persona

try:
    from conversation_log import ConversationLog, get_conversation_log
except Exception:  # pragma: no cover - defensive
    ConversationLog = None  # type: ignore
    get_conversation_log = None


_QUIT_COMMANDS = {"/quit", "/exit", "/q"}
_HISTORY_DEFAULT = 10


def respond_to(
    text: str,
    persona: Persona,
    conv_log: "Optional[ConversationLog]" = None,
) -> str:
    """1 つの入力に対する応答を決定し、会話ログがあれば記録して返す。

    応答は persona.respond() を使い、空（ルール・fallback とも無し）の場合は
    オウム返しにフォールバックする。会話ログへの記録失敗は握り潰す。
    """
    reply = persona.respond(text)
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
        "コマンド: /help 一覧 | /history 履歴 | /name 名前 | /quit 終了"
    )


def run_chat(
    persona: Optional[Persona] = None,
    conv_log: "Optional[ConversationLog]" = None,
    input_fn: Optional[Callable[[str], str]] = None,
    output_fn: Optional[Callable[[str], None]] = None,
    greet: bool = True,
) -> int:
    """対話ループを実行する。

    Args:
        persona: 使用する Persona（省略時は共有シングルトン）。
        conv_log: 会話ログ（省略時は共有シングルトン、利用不可なら無効）。
        input_fn: 入力取得関数（省略時は組み込み input。テスト用に差し替え可能）。
        output_fn: 出力関数（省略時は組み込み print。テスト用に差し替え可能）。
        greet: 開始時に時刻依存のあいさつを表示するか。

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

    name = persona.name or "Avatar"
    if greet:
        greeting = persona.greeting()
        if greeting:
            output_fn(f"{name}: {greeting}")
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
            output_fn(f"{name}: {farewell}")
            break
        if text.lower() == "/help":
            output_fn(_help_text())
            continue
        if text.lower() == "/name":
            output_fn(f"{name}")
            continue
        if text.lower() == "/history":
            _print_history(conv_log, output_fn)
            continue

        # 通常の会話
        reply = respond_to(text, persona, conv_log)
        output_fn(f"{name}: {reply}")
        exchanges += 1

    return exchanges


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


def main(argv: Optional[List[str]] = None) -> int:
    """`python -m persona_cli` / ランチャー --chat 用エントリポイント。"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="persona_cli",
        description="Satin アバターとヘッドレスで会話する CLI",
    )
    parser.add_argument("--lang", default=None, help="会話言語 (例: ja, en)")
    parser.add_argument("--no-greet", action="store_true", help="開始時のあいさつを省略")
    args = parser.parse_args(argv)

    persona = Persona.load(lang=args.lang) if args.lang else get_persona()
    run_chat(persona=persona, greet=not args.no_greet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
