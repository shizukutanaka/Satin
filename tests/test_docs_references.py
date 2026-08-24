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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
