"""ドキュメントが実在しないファイルを指していないことの検証。

なぜ必要か
----------
このリポジトリでは実際に「どのディレクトリにも存在したことがない
`python backup_cli.py` を実行せよ」と書かれた手順が長期間残っていた。
コードの死んだ参照は ruff の F821 や mypy が捕まえるが、**ドキュメントの
死んだ参照を捕まえるものは何も無い**。そして読者にとっての被害はむしろ
こちらのほうが大きい — 動かないコマンドを渡された人は、自分の環境が
壊れていると考えて時間を溶かす。

大規模な削除（モジュール 59 本）を経たあとは特に腐りやすいので、
「壊れたら赤くなる」形にしておく。

CHANGELOG.md と docs/history/ を対象外にする理由
------------------------------------------------
変更履歴と過去セッションのアーカイブは記録であり、「かつて存在したが削除した」
と書くのが正しい。過去形の記述を現在の実在で検証するのは誤り。
（docs/history/README.md 自身が「現在有効なドキュメントではなく」と宣言している。）

ただし**リンク切れは記録かどうかに関係なく壊れている**ので、Markdown の
相対リンクは全ドキュメントを対象に検証する。
"""
from __future__ import annotations

import os
import sys
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 変更履歴・過去セッションのアーカイブは対象外（上の docstring を参照）。
_EXCLUDED_DOCS = {"CHANGELOG.md"}
_ARCHIVE_DIRS = {os.path.join("docs", "history")}

# 実在を要求しないもの:
#   - プレースホルダ（<name>.py, foo.py など、書式説明のための仮名）
#   - サードパーティ/標準ライブラリの名前
_PLACEHOLDER_RE = re.compile(r"^(<.*>|\.\.\.|xxx|foo|bar|your_.*|[A-Z_]+)\.py$")
_NOT_OURS = {
    "setup.py",      # 一般的な Python の慣習として言及されうる
    "conftest.py",   # tests/ 配下（別途 _resolve が拾う）
}

# ドキュメント中の Python ファイル参照。バッククォート内・素のテキスト双方を拾う。
_PY_REF_RE = re.compile(r"[\w./-]+\.py\b")


# 走査から外すディレクトリ（バージョン管理・キャッシュ・依存物）。
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache",
              "node_modules", ".venv", "venv", ".mypy_cache"}


def _all_docs() -> list[str]:
    """リポジトリ内の全 Markdown（アーカイブ・変更履歴も含む）。

    root と docs/ だけを見ていた時期があり、そのあいだ最も壊れていた
    setup/README.md（実行すると失敗するコマンドを 3 つ載せていた）が
    検査から漏れていた。インストール手順は読者が最初に触る文書なので、
    走査対象から外れていること自体が最も高くつく。
    """
    paths = []
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        paths.extend(os.path.join(dirpath, f)
                     for f in sorted(filenames) if f.endswith(".md"))
    return paths


def _docs() -> list[str]:
    """「今このリポジトリはこうである」と主張しているドキュメントだけ。"""
    live = []
    for path in _all_docs():
        rel = os.path.relpath(path, _ROOT)
        if os.path.basename(rel) in _EXCLUDED_DOCS:
            continue
        if any(rel.startswith(d + os.sep) for d in _ARCHIVE_DIRS):
            continue
        live.append(path)
    return live


def _resolve(ref: str) -> bool:
    """参照が実在ファイルに解決できるか。

    ドキュメントはリポジトリ root からの相対でも、`main/` 内の裸のモジュール名
    でも書かれうるので、実際に読者が辿りうる候補をすべて試す。
    """
    ref = ref.lstrip("./")
    candidates = [
        os.path.join(_ROOT, ref),
        os.path.join(_ROOT, "main", ref),
        os.path.join(_ROOT, "tests", ref),
    ]
    return any(os.path.exists(c) for c in candidates)


def _dead_refs_in(path: str) -> list[tuple[int, str]]:
    dead = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            for ref in _PY_REF_RE.findall(line):
                base = os.path.basename(ref)
                if _PLACEHOLDER_RE.match(base) or base in _NOT_OURS:
                    continue
                if not _resolve(ref):
                    dead.append((lineno, ref))
    return dead


class DocumentationReferenceTests(unittest.TestCase):
    def test_docs_do_not_reference_deleted_modules(self):
        """ドキュメントが実在しない .py を指していないこと。"""
        for path in _docs():
            rel = os.path.relpath(path, _ROOT)
            with self.subTest(doc=rel):
                dead = _dead_refs_in(path)
                detail = "\n".join(f"  {rel}:{n}: {r}" for n, r in dead)
                self.assertEqual(
                    dead, [],
                    f"\n{rel} が実在しないファイルを参照しています:\n{detail}")

    def test_referenced_directories_exist(self):
        """`xxx/` 形式でディレクトリを案内している箇所が実在すること。

        削除したディレクトリ（plugin_system/ や examples/ など）への案内が
        残っていると、読者はそこに何かがあると思って探しに行く。
        """
        dir_re = re.compile(r"`((?:main/|tests/|setup/|config/|docs/)?[\w.-]+/)`")
        known_absent_ok = {"logs/", "backups/", "models/", "output/", "cache/"}
        for path in _docs():
            rel = os.path.relpath(path, _ROOT)
            missing = []
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    for ref in dir_re.findall(line):
                        if ref in known_absent_ok:
                            continue  # 実行時に生成されるディレクトリ
                        if not os.path.isdir(os.path.join(_ROOT, ref.rstrip("/"))):
                            missing.append((lineno, ref))
            with self.subTest(doc=rel):
                detail = "\n".join(f"  {rel}:{n}: {r}" for n, r in missing)
                self.assertEqual(
                    missing, [],
                    f"\n{rel} が実在しないディレクトリを参照しています:\n{detail}")


class MarkdownLinkTests(unittest.TestCase):
    """相対リンクの解決。アーカイブも含めた全 Markdown が対象。

    リンク切れは「その記述が過去のものかどうか」と無関係に壊れている。
    実際 docs/history/README.md は `../CHANGELOG.md` と書いていたが、
    自身が docs/history/ にあるため指す先は docs/CHANGELOG.md であり、
    存在しなかった（正しくは `../../CHANGELOG.md`）。
    """

    _LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

    def test_relative_links_resolve(self):
        for path in _all_docs():
            rel = os.path.relpath(path, _ROOT)
            broken = []
            base = os.path.dirname(path)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    for target in self._LINK_RE.findall(line):
                        target = target.split("#", 1)[0].strip()
                        if not target or "://" in target or target.startswith("mailto:"):
                            continue  # 外部 URL はネットワークに触れないので検証しない
                        if not os.path.exists(os.path.join(base, target)):
                            broken.append((lineno, target))
            with self.subTest(doc=rel):
                detail = "\n".join(f"  {rel}:{n}: {t}" for n, t in broken)
                self.assertEqual(broken, [], f"\n{rel} のリンク切れ:\n{detail}")



class ReviewChecklistTests(unittest.TestCase):
    """PRODUCT_REVIEW §5 lists the numbers a human has to sign off on.

    A checklist that has drifted from the code is worse than no checklist: the
    reviewer approves values that are not the ones running. Every number in the
    table is checked against its constant here, so changing a threshold without
    updating the table turns the suite red.
    """

    @classmethod
    def setUpClass(cls):
        main = os.path.join(_ROOT, "main")
        if main not in sys.path:
            sys.path.insert(0, main)
        with open(os.path.join(_ROOT, "PRODUCT_REVIEW.md"), encoding="utf-8") as fh:
            cls.doc = fh.read()

    def _table_row(self, label):
        for line in self.doc.splitlines():
            if line.startswith("|") and label in line:
                return line
        self.fail(f"PRODUCT_REVIEW §5 has no row for {label!r}")

    def test_affinity_numbers_match_the_code(self):
        import mood
        row = self._table_row("関係の成長弧")
        self.assertIn(str(mood._MAX_DAILY_CONVERSATION_GAIN), row)
        row = self._table_row("好感度の自然低下")
        self.assertIn(str(mood._DEFAULT_DECAY_RATE), row)
        row = self._table_row("告白の下限")
        self.assertIn(str(int(mood._CONFESSION_MIN_DAYS)), row)
        self.assertIn(str(mood._CONFESSION_MIN_INTERACTIONS), row)

    def test_login_and_ritual_bonuses_match_the_code(self):
        import mood
        import persona_cli
        row = self._table_row("デイリーログイン")
        self.assertIn(str(mood._DAILY_LOGIN_BASE_BONUS), row)
        self.assertIn(str(mood._DAILY_LOGIN_MAX_BONUS), row)
        row = self._table_row("謝罪 / おやすみ")
        self.assertIn(str(persona_cli._APOLOGY_BONUS), row)
        self.assertIn(str(persona_cli._GOODNIGHT_BONUS), row)

    def test_guardrail_thresholds_match_the_code(self):
        import usage_guardrails
        row = self._table_row("深夜利用の定義")
        self.assertIn(str(usage_guardrails._LATE_NIGHT_START_HOUR), row)
        self.assertIn(str(usage_guardrails._LATE_NIGHT_END_HOUR), row)
        self.assertIn(str(usage_guardrails._LATE_NIGHT_MIN_EVENTS), row)

    def test_break_reminder_defaults_match_the_code(self):
        import break_reminder
        row = self._table_row("休憩リマインダー")
        for value in (break_reminder._DEFAULT_WORK_MINUTES,
                      break_reminder._DEFAULT_SHORT_BREAK,
                      break_reminder._DEFAULT_LONG_BREAK,
                      break_reminder._DEFAULT_CYCLES_BEFORE_LONG):
            self.assertIn(str(value), row)

    def test_ai_disclosure_interval_matches_the_code(self):
        import ai_disclosure
        row = self._table_row("AI 開示の間隔")
        hours = ai_disclosure.DISCLOSURE_INTERVAL_SECONDS // 3600
        self.assertIn(f"{hours} 時間", row)

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
