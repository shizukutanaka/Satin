"""
会話履歴ログ。

ユーザーのコメントとアバターの応答を既存の AvatarEventLogger (JSONL) に記録し、
タイムラインビューア / ダッシュボード / レポートなど既存のイベントログ
ツールチェーンから会話を閲覧できるようにする。これまでイベントログ基盤は
存在したが、プロダクト本体からは一切書き込まれていなかった（＝会話が残らない）。

イベント種別:
  - user_comment: ユーザーが入力したコメント  details={"text": ...}
  - avatar_reply: アバターの応答              details={"text": ..., "to": <元コメント>}

記録の失敗（ディスクフル等）は呼び出し元の UI/TTS を壊さないよう必ず握り潰す。
依存は標準ライブラリのみ。
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from typing import Dict, Generator, List, Optional

from avatar_event_logger import AvatarEventLogger

logger = logging.getLogger(__name__)

# 既存ツール (dashboard / timeline viewer / alert) の既定と同じファイルを共有する。
# 単なるファイル名（相対パス）だとプロセスの cwd 次第でどこに書かれるか変わり、
# デスクトップショートカット起動・別ディレクトリからのターミナル起動・
# `pytest tests/` 実行のどれでも別の場所に会話ログが分裂しうる（実際、リポジトリ
# 直下にテスト実行のたび肥大するファイルが生成される実害があった）。
# manage_satin.py が既に自前で "_ROOT からの絶対パス" にワークアラウンドして
# いた通り、ここを唯一の真実の源として絶対パスに固定する。
DEFAULT_LOGFILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "avatar_event_log.jsonl",
)

EVENT_USER_COMMENT = "user_comment"
EVENT_AVATAR_REPLY = "avatar_reply"

# 集計・表示時に「ユーザー発話」「アバター発話」とみなすイベント種別の正準集合。
# 正規値に加え、過去ログ/外部ログ互換のためのレガシー別名 ("user"/"avatar") を含む。
# dashboard と daily_summary が同じ分類を共有し、同一ログで集計が食い違わないようにする
# 単一の真実の源（single source of truth）。
USER_EVENT_TYPES = frozenset({EVENT_USER_COMMENT, "user"})
AVATAR_EVENT_TYPES = frozenset({EVENT_AVATAR_REPLY, "avatar"})

# CSV/formula injection (OWASP): Excel/Sheets/LibreOffice treat a cell whose
# content starts with one of these characters as a formula to evaluate on
# open. to_csv() previously wrote user-controlled conversation text
# (and the speaker label) verbatim — a logged message like
# "=cmd|'/C calc'!A1" or "=HYPERLINK(...)" would execute/exfiltrate the
# moment the exported CSV is opened in a spreadsheet app.
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_formula_safe(value: str) -> str:
    """先頭が数式トリガ文字の場合、シングルクォートを前置して無害化する。"""
    text = str(value)
    if text.startswith(_CSV_FORMULA_TRIGGERS):
        return "'" + text
    return text


# ------------------------------------------------------------------
# 関連度順検索（研究 A4）: 単純な部分一致 search() では「旅行が楽しかった」を
# 「楽しかった旅行」で引けず、関連度で並べ替えることもできない。BM25 で
# 関連度スコアを付けて「最も関連する過去の発話」を想起する。
# LLM・埋め込み・外部依存なし（純 Python）で決定論的。
# 日本語は形態素解析器を使わず文字バイグラム、英数字は単語トークンで索引する
# （CJK でよく使われる依存性ゼロの手法）。
# ------------------------------------------------------------------
import re as _re
import math as _math
import unicodedata as _ud
from collections import Counter as _Counter

_ASCII_WORD_RE = _re.compile(r"[a-z0-9]+")
# ひらがな・カタカナ・CJK 統合漢字・半角カナの連続
_CJK_RUN_RE = _re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]+")


def _tokenize_for_retrieval(text: str) -> List[str]:
    """検索用トークン列を返す（英数字は単語、CJK は文字バイグラム）。"""
    norm = _ud.normalize("NFC", str(text).lower())
    tokens: List[str] = _ASCII_WORD_RE.findall(norm)
    for run in _CJK_RUN_RE.findall(norm):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _bm25_scores(query_tokens: List[str], docs_tokens: List[List[str]],
                 k1: float = 1.5, b: float = 0.75) -> List[float]:
    """Okapi BM25 で各文書の関連度スコアを返す（クエリ語が無ければ全て 0）。"""
    n_docs = len(docs_tokens)
    if n_docs == 0 or not query_tokens:
        return [0.0] * n_docs
    doc_counters = [_Counter(toks) for toks in docs_tokens]
    doc_lens = [len(toks) for toks in docs_tokens]
    avgdl = sum(doc_lens) / n_docs if n_docs else 0.0

    dfs: Dict[str, int] = {}
    for c in doc_counters:
        for term in c:
            dfs[term] = dfs.get(term, 0) + 1

    q_terms = set(query_tokens)
    idf: Dict[str, float] = {}
    for term in q_terms:
        df = dfs.get(term, 0)
        # 標準的な BM25 idf。極端に頻出な語で負値にならないよう 0 で下限クリップ。
        idf[term] = max(0.0, _math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0))

    scores: List[float] = []
    for i, c in enumerate(doc_counters):
        dl = doc_lens[i]
        s = 0.0
        for term in q_terms:
            f = c.get(term, 0)
            if not f:
                continue
            denom = f + k1 * (1 - b + b * (dl / avgdl if avgdl else 0.0))
            s += idf[term] * (f * (k1 + 1)) / denom
        scores.append(s)
    return scores


def _archive_sort_key(path: str) -> tuple:
    """アーカイブのソートキーを返す。

    命名規則 ``<logfile>.<YYYYMMDD_HHMMSS>.gz`` のタイムスタンプ部分を使う。
    バックアップ復元後に mtime がリセットされても正しい時系列順を保つ。
    フォールバックとして mtime を使う（命名規則が異なる旧ファイル向け）。
    """
    import re
    m = re.search(r"\.(\d{8}_\d{6})\.gz$", path)
    if m:
        return (0, m.group(1))  # (優先度, タイムスタンプ文字列)
    try:
        return (1, os.path.getmtime(path))  # フォールバック: mtime (float 比較で正確)
    except OSError:
        return (1, 0.0)


def _find_archives(logfile: str) -> List[str]:
    """ローテートされた gzip アーカイブを古い順で返す。

    avatar_event_log_rotate.rotate_log() は ``<logfile>.<YYYYMMDD_HHMMSS>.gz``
    という命名規則でアーカイブを作成する。ファイル名に埋め込まれたタイムスタンプで
    ソートするため、バックアップ復元後に mtime がリセットされても順序が壊れない。
    ログファイルが存在しない・ディレクトリが読めない場合は空リスト。
    """
    try:
        log_dir = os.path.dirname(os.path.abspath(logfile))
        basename = os.path.basename(logfile) + "."
        files = [
            os.path.join(log_dir, f)
            for f in os.listdir(log_dir)
            if f.startswith(basename) and f.endswith(".gz")
        ]
        return sorted(files, key=_archive_sort_key)
    except OSError:
        return []


def _iter_gz_lines(gz_path: str) -> Generator[str, None, None]:
    """gzip アーカイブの各行を文字列として yield する。読み込みエラーは握りつぶす。"""
    try:
        with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line
    except Exception as e:  # pragma: no cover - OS/format error
        logger.debug("アーカイブの読み込みをスキップします (%s): %s", gz_path, e)


class ConversationLog:
    """ユーザーとアバターの会話を JSONL イベントログへ記録・読み出しするクラス。"""

    def __init__(self, logfile: Optional[str] = None):
        # 省略時は呼び出し時点の DEFAULT_LOGFILE（get_conversation_log と同じ理由）。
        self.logfile = logfile if logfile is not None else DEFAULT_LOGFILE
        self._logger = AvatarEventLogger(self.logfile)

    # ---- 記録 ------------------------------------------------------------ #
    def log_user_comment(self, text: str) -> None:
        """ユーザーのコメントを記録する。失敗しても例外は送出しない。"""
        if not text:
            return
        try:
            self._logger.log_event(EVENT_USER_COMMENT, text=str(text))
        except Exception as e:  # pragma: no cover - defensive: UI を壊さない
            logger.warning("会話ログの記録に失敗しました: %s", e)

    def log_avatar_reply(self, text: str, to: Optional[str] = None) -> None:
        """アバターの応答を記録する。to には応答対象の元コメントを渡せる。"""
        if not text:
            return
        details = {"text": str(text)}
        if to:
            details["to"] = str(to)
        try:
            self._logger.log_event(EVENT_AVATAR_REPLY, **details)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("会話ログの記録に失敗しました: %s", e)

    def log_exchange(self, comment: str, reply: str) -> None:
        """「コメント → 応答」の 1 往復をまとめて記録する。"""
        self.log_user_comment(comment)
        # オウム返し (reply == comment) は応答として二重記録しない
        if reply and reply != comment:
            self.log_avatar_reply(reply, to=comment)

    # ---- 読み出し ---------------------------------------------------------- #
    def recent(self, n: int = 20) -> List[Dict]:
        """直近 n 件の会話イベント (user_comment / avatar_reply) を古い順で返す。

        ログファイルが無い・壊れた行がある場合も安全に処理する。
        ライブファイルの件数が n に満たない場合（ローテーション直後など）は
        アーカイブも遡って補完する。
        """
        if n <= 0:
            return []
        # まずライブファイルから収集する
        live_entries: List[Dict] = []
        _conv_types = USER_EVENT_TYPES | AVATAR_EVENT_TYPES
        if os.path.exists(self.logfile):
            try:
                with open(self.logfile, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(ev, dict) and ev.get("event_type") in _conv_types:
                            live_entries.append(ev)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("会話ログの読み出しに失敗しました: %s", e)
        # ライブファイルで n 件揃う場合はアーカイブ走査は不要
        if len(live_entries) >= n:
            return live_entries[-n:]
        # 不足分をアーカイブ（新しい順）から補完する
        # 各アーカイブのエントリをブロック単位で先頭に挿入し、古→新の時系列順を保つ。
        # フラットに追記して後で逆順にする方法はアーカイブ境界をまたぐと順序が崩れる。
        need = n - len(live_entries)
        archive_blocks: List[List[Dict]] = []
        total_archive = 0
        for gz_path in reversed(_find_archives(self.logfile)):
            block: List[Dict] = []
            for line in _iter_gz_lines(gz_path):
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict) and ev.get("event_type") in _conv_types:
                    block.append(ev)
            archive_blocks.insert(0, block)  # 先頭挿入で古→新順を維持
            total_archive += len(block)
            if total_archive >= need:
                break
        # ブロックを結合して古→新の連続リストにし、末尾 need 件を取る
        archive_entries: List[Dict] = [ev for blk in archive_blocks for ev in blk]
        archive_tail = archive_entries[-need:]
        return archive_tail + live_entries

    def recent_texts(
        self,
        n: int = 20,
        user_label: str = "You",
        avatar_label: str = "Avatar",
    ) -> List[str]:
        """直近 n 件を「[YYYY-MM-DD HH:MM:SS] You: ...」形式の文字列リストで返す（表示用）。

        user_label / avatar_label でラベルをカスタマイズできる（例: ペルソナ名）。
        """
        from datetime import datetime as _dt
        lines = []
        for ev in self.recent(n):
            text = (ev.get("details") or {}).get("text", "")
            prefix = user_label if ev.get("event_type") in USER_EVENT_TYPES else avatar_label
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"[{dt_str}] {prefix}: {text}")
            except (OSError, OverflowError, ValueError, TypeError):
                lines.append(f"{prefix}: {text}")
        return lines

    def search(self, query: str, n: int = 0, include_archives: bool = True) -> List[Dict]:
        """会話履歴からキーワード検索し、一致したイベントを古い順で返す。

        Args:
            query: 検索クエリ（大文字小文字を無視した部分一致）。空なら全件。
            n: 返す最大件数（0 = 全件）。
            include_archives: True（既定）のとき、ローテートされた gzip アーカイブも
                検索する。ログローテーション後も会話履歴が消えないようにするための
                「コンパニオンが記憶を失わない」保証。

        Returns:
            会話イベント（user/avatar、レガシー別名含む）のうち text フィールドに
            query を含むイベントのリスト。イベント分類は USER_EVENT_TYPES /
            AVATAR_EVENT_TYPES（dashboard と共有の正準集合）に従う。
        """
        import unicodedata
        q_lower = unicodedata.normalize("NFC", query.strip().lower()) if query else ""
        conv_types = USER_EVENT_TYPES | AVATAR_EVENT_TYPES
        entries: List[Dict] = []

        def _collect_line(line: str) -> None:
            if not line.strip():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(ev, dict) or ev.get("event_type") not in conv_types:
                return
            text = ((ev.get("details") or {}).get("text") or "")
            # NFC 正規化で NFC/NFD 混在入力でも一致（日本語の濁点合字対応）
            if not q_lower or q_lower in unicodedata.normalize("NFC", str(text).lower()):
                entries.append(ev)

        # アーカイブを古い順に検索（ローテーション後も履歴が途切れない）
        if include_archives:
            for gz_path in _find_archives(self.logfile):
                for line in _iter_gz_lines(gz_path):
                    _collect_line(line)

        # 現行ログファイル
        if os.path.exists(self.logfile):
            try:
                with open(self.logfile, encoding="utf-8") as f:
                    for line in f:
                        _collect_line(line)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("会話ログの検索に失敗しました: %s", e)

        return entries[-n:] if n > 0 else entries

    def search_relevant(self, query: str, n: int = 5,
                        include_archives: bool = True) -> List[Dict]:
        """クエリに**関連度が高い順**で会話イベントを返す（BM25、研究 A4）。

        部分一致の search() と異なり、語順・活用・言い回しの違いを越えて
        「最も関連する過去の発話」を想起できる（例: 「楽しかった旅行」で
        「旅行が楽しかった」を引ける）。関連度 0 の文書は返さない。

        Args:
            query: 検索クエリ。空・空白のみなら空リストを返す。
            n: 返す最大件数（<=0 は全件、関連度降順）。
            include_archives: True（既定）でローテート済み gzip も対象。

        Returns:
            関連度降順の会話イベントのリスト。同点は元の時系列（古い順）を保つ。
        """
        q_tokens = _tokenize_for_retrieval(query) if query else []
        if not q_tokens:
            return []

        conv_types = USER_EVENT_TYPES | AVATAR_EVENT_TYPES
        events: List[Dict] = []

        def _collect_line(line: str) -> None:
            if not line.strip():
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            if not isinstance(ev, dict) or ev.get("event_type") not in conv_types:
                return
            events.append(ev)

        if include_archives:
            for gz_path in _find_archives(self.logfile):
                for line in _iter_gz_lines(gz_path):
                    _collect_line(line)
        if os.path.exists(self.logfile):
            try:
                with open(self.logfile, encoding="utf-8") as f:
                    for line in f:
                        _collect_line(line)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("会話ログの関連度検索に失敗しました: %s", e)

        if not events:
            return []

        docs_tokens = [
            _tokenize_for_retrieval((ev.get("details") or {}).get("text") or "")
            for ev in events
        ]
        scores = _bm25_scores(q_tokens, docs_tokens)
        # enumerate インデックスで安定ソート（同点は元順＝古い順を維持）。
        ranked = sorted(
            ((sc, idx) for idx, sc in enumerate(scores) if sc > 0.0),
            key=lambda pair: (-pair[0], pair[1]),
        )
        result = [events[idx] for _sc, idx in ranked]
        return result[:n] if n and n > 0 else result

    def to_csv(self, n: int = 0, user_label: str = "You", avatar_label: str = "Avatar",
               include_archives: bool = True) -> str:
        """会話履歴を CSV 形式の文字列で返す。

        Args:
            n: 直近 n 件（0 = 全件）
            user_label:   CSV の speaker 列でユーザーを表すラベル
            avatar_label: CSV の speaker 列でアバターを表すラベル
            include_archives: True（既定）のとき、ローテート済みアーカイブも含む。

        Returns:
            header + rows の CSV 文字列（UTF-8、CRLF 改行）。
        """
        import csv
        import io
        from datetime import datetime as _dt

        entries = self.search("", n=n, include_archives=include_archives)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(["timestamp", "datetime", "speaker", "text"])
        for ev in entries:
            ts = ev.get("timestamp", 0)
            try:
                dt_str = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, OverflowError, ValueError, TypeError):
                dt_str = ""
            et = ev.get("event_type", "")
            speaker = user_label if et in USER_EVENT_TYPES else avatar_label
            text = (ev.get("details") or {}).get("text", "")
            writer.writerow([ts, dt_str, _csv_formula_safe(speaker), _csv_formula_safe(text)])
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# プロセス内シングルトン（全ビューアで同じログファイルを共有）
# --------------------------------------------------------------------------- #
_conversation_log: Optional[ConversationLog] = None
_lock = threading.Lock()


def get_conversation_log(logfile: Optional[str] = None) -> ConversationLog:
    """共有 ConversationLog を返す（初回呼び出し時に生成）。

    logfile 省略時は呼び出し時点の DEFAULT_LOGFILE を使う（関数定義時に束縛した
    デフォルト引数値ではなく）。これにより、テストが conftest.py 等で
    conversation_log.DEFAULT_LOGFILE を差し替えれば、引数省略で呼ぶ全モジュール
    （avatar_3d_autonomous_tts / persona_cli 等）が即座にそれに従う。
    """
    global _conversation_log
    if _conversation_log is None:
        with _lock:
            if _conversation_log is None:
                _conversation_log = ConversationLog(
                    logfile if logfile is not None else DEFAULT_LOGFILE
                )
    return _conversation_log


def reset_conversation_log() -> None:
    """シングルトンを破棄する（テスト・ログファイル切替用）。"""
    global _conversation_log
    with _lock:
        _conversation_log = None
