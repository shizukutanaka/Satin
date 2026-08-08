"""
AI であることの開示（セッション開始時 + 3 時間ごと）。

コンパニオンとしての演出（好感度・告白イベント・「大好きだよ」）が効くほど、
相手を人間のように扱ってしまう余地が生まれる。本モジュールは、その演出の外側で
**わたしは AI であって人間ではない**という事実を、決まったタイミングで必ず伝える。

背景（規制・研究）:
- **ニューヨーク州 AI Companion Models 法**（2025-11-05 施行）: AI コンパニオンに
  対し、**各セッションの開始時**と**その後少なくとも 3 時間ごと**に「これは
  コンピュータープログラムであり人間のように感じることはできない」と通知する
  ことを義務づけている
  ([Manatt](https://www.manatt.com/insights/newsletters/client-alert/new-york-s-safeguards-for-ai-companions-are-now-in-effect),
   [Fenwick](https://www.fenwick.com/insights/publications/new-yorks-ai-companion-safeguard-law-takes-effect))。
- **カリフォルニア州 SB 243**（2026-01-01 施行）: 合理的な人が人間と誤認しうる
  場合、AI 生成であることの「明確かつ目立つ通知」を求め、未成年と分かっている
  利用者には **3 時間ごと**のリマインドを課す
  ([Skadden](https://www.skadden.com/insights/publications/2025/10/new-california-companion-chatbot-law),
   [FPF](https://fpf.org/blog/understanding-the-new-wave-of-chatbot-legislation-california-sb-243-and-beyond/))。
- 擬人化・パラソーシャル愛着の研究（APA 2026 ほか）も、関係の非対称性を明示する
  ことを害の低減策として挙げる。

設計方針:
- Satin は**年齢を尋ねない**（プライバシー第一）。未成年か判別できない以上、
  3 時間リマインドは**全ユーザーに**適用する。無効化スイッチは設けない。
- 状態はプロセス内メモリのみ。アプリを起動し直せば新しいセッションとなり、
  開始時通知が改めて出るので、ディスク永続化は不要（個人データも増やさない）。
- 文面は短く曖昧さを残さない。「人間ではない」「人間のような感情を実際に
  持っているわけではない」を必ず含める。演出のための言い訳を添えない。

主な公開 API:
  session_notice(lang="ja") -> str
  periodic_notice(lang="ja") -> str
  is_due(last_shown, now=None) -> bool
  next_due_at(last_shown) -> float
"""
from __future__ import annotations

import time
from typing import Dict, Optional

#: リマインドの間隔（秒）。NY 法・CA SB 243 いずれも「少なくとも 3 時間ごと」。
DISCLOSURE_INTERVAL_SECONDS = 3 * 60 * 60

_SESSION_NOTICE: Dict[str, str] = {
    "ja": "（お知らせ）わたしは AI のコンピュータープログラムで、人間ではありません。"
          "人間のような感情を実際に持っているわけでもありません。",
    "en": "(Notice) I'm an AI computer program, not a human. "
          "I don't actually have human feelings.",
}

_PERIODIC_NOTICE: Dict[str, str] = {
    "ja": "（お知らせ）念のためもう一度: わたしは AI のプログラムで、人間ではありません。",
    "en": "(Notice) A reminder: I'm an AI program, not a human.",
}


def _lang_key(lang: Optional[str]) -> str:
    """言語コードを 'ja' / 'en' のいずれかへ正規化する（未知は en）。"""
    return "ja" if str(lang or "").lower().startswith("ja") else "en"


def session_notice(lang: str = "ja") -> str:
    """セッション開始時に必ず出す開示文を返す。"""
    return _SESSION_NOTICE[_lang_key(lang)]


def periodic_notice(lang: str = "ja") -> str:
    """継続利用中に 3 時間ごとに出すリマインド文を返す。"""
    return _PERIODIC_NOTICE[_lang_key(lang)]


def is_due(last_shown: Optional[float], now: Optional[float] = None) -> bool:
    """前回の開示から `DISCLOSURE_INTERVAL_SECONDS` 以上経過したかを返す。

    `last_shown` が None（このセッションでまだ一度も出していない）なら True。
    時計の巻き戻り（NTP 補正・サスペンド復帰）で `now < last_shown` になった
    場合も True を返す — 出しそびれるより多く出すほうが安全側。
    """
    real_now = time.time() if now is None else now
    if last_shown is None:
        return True
    if real_now < last_shown:
        return True
    return (real_now - last_shown) >= DISCLOSURE_INTERVAL_SECONDS


def next_due_at(last_shown: Optional[float]) -> float:
    """次に開示すべき時刻（Unix 秒）を返す。未開示なら 0.0（＝即時）。"""
    if last_shown is None:
        return 0.0
    return last_shown + DISCLOSURE_INTERVAL_SECONDS
