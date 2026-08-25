"""
会話ログの保存期間（storage limitation）。

Satin の売りは「ローカル完結・完全消去できる」プライバシー設計で、実際に
0600 パーミッション・`/forget-all`・`data purge` を備えている。しかし**時間軸の
制御だけが無かった**。`AvatarEventLogger` のローテーションは
5 MB × 5 世代 = 約 30 MB の**サイズ**上限であって、これはディスク衛生の仕組みで
あって保存期間の仕組みではない。ときどき話すユーザーは、何年前の打ち明け話も
（`crisis_support` が拾うような内容も含めて）永久に手元へ残し続けることになる。
消す手段は `/clear-log` / `/forget-all` の全消去しかなく、「関係は続けたいが
古い生ログは残したくない」という当たり前の選択ができなかった。

背景（標準・技術）:
- **GDPR 第 5 条 1 項 (e)「記憶域の制限」**: 個人データは、処理の目的に必要な
  期間を超えて識別可能な形で保持してはならない。保持期間は目的から導く。
- **データ最小化 / Privacy by Design**（[NIST Privacy Framework](https://www.nist.gov/privacy-framework)
  の CT.DM / PR.DS）でも、収集そのものだけでなく**保持**の最小化が独立した
  管理策として挙げられる。
- コンパニオンアプリの会話は自己開示の密度が高く、漏えい時の被害が大きい。
  保持期間の短縮は、暗号化のような新規依存を増やさずに実効的な被害低減になる。

設計方針:
- **既定は現状維持（0 = 無期限）**。アップグレードしただけでユーザーの思い出が
  黙って消える、という事態は絶対に起こさない。有効化は明示的な設定のみ。
- 日付を持たない行は**消さない**。時刻が読めないものを「古い」と判断しない。
- ライブ JSONL は 0600 のまま原子的に書き戻す（`fsutil.atomic_write_text`）。
- gzip アーカイブはファイル名のローテーション時刻で判定する。ローテーション時刻
  より新しいイベントはその中に存在しえないので、時刻が cutoff より古い
  アーカイブは丸ごと削除してよい（展開不要）。

主な公開 API:
  configured_retention_days(config_path=None) -> int
  cutoff_timestamp(days, now=None) -> float
  prune_conversation_log(logfile=None, days=None, now=None) -> Dict
  apply_retention_if_configured(logfile=None, config_path=None) -> Dict
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re as _re
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

#: `config/config.json` の `settings` 内に置く設定キー。
CONFIG_KEY = "conversation_retention_days"

#: 既定は 0 = 無期限保持（従来の挙動）。
DEFAULT_RETENTION_DAYS = 0

_ARCHIVE_TS_RE = _re.compile(r"\.(\d{8}_\d{6})\.gz$")

try:
    from fsutil import atomic_write_text as _atomic_write_text
except Exception:  # pragma: no cover - defensive fallback
    _atomic_write_text = None  # type: ignore[assignment]

try:
    from conversation_log import DEFAULT_LOGFILE as _DEFAULT_LOGFILE
except Exception:  # pragma: no cover - defensive fallback
    _DEFAULT_LOGFILE = "avatar_event_log.jsonl"


def _default_config_path() -> Optional[str]:
    """既定の config.json パスを解決する（persona._default_persona_path と同様）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "config", "config.json"),
        os.path.join(os.path.dirname(here), "config", "config.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def configured_retention_days(config_path: Optional[str] = None) -> int:
    """設定された保存日数を返す（未設定・不正値なら 0 = 無期限）。

    読めない設定で会話ログを消してしまうことのないよう、あらゆる異常は
    0（何もしない）へ倒す。
    """
    path = config_path or _default_config_path()
    if not path or not os.path.exists(path):
        return DEFAULT_RETENTION_DAYS
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        settings = data.get("settings")
        if not isinstance(settings, dict):
            return DEFAULT_RETENTION_DAYS
        days = int(settings.get(CONFIG_KEY, DEFAULT_RETENTION_DAYS))
    except Exception as e:
        logger.debug("保存期間設定の読み込みに失敗（無期限として扱います）: %s", e)
        return DEFAULT_RETENTION_DAYS
    return days if days > 0 else DEFAULT_RETENTION_DAYS


def cutoff_timestamp(days: int, now: Optional[float] = None) -> float:
    """days 日より前を示す境界の Unix 時刻を返す（days <= 0 なら 0.0）。"""
    if not days or days <= 0:
        return 0.0
    real_now = time.time() if now is None else now
    return real_now - days * 86400.0


def _archive_epoch(path: str) -> Optional[float]:
    """`<logfile>.<YYYYMMDD_HHMMSS>.gz` のローテーション時刻を Unix 秒で返す。"""
    m = _ARCHIVE_TS_RE.search(path)
    if not m:
        return None
    try:
        # rotate_log は datetime.now()（ローカル時刻）で命名するので strptime も
        # ローカル時刻として解釈する。
        return time.mktime(time.strptime(m.group(1), "%Y%m%d_%H%M%S"))
    except (ValueError, OverflowError):
        return None


def _archives_for(logfile: str) -> List[str]:
    """logfile に対応する gzip アーカイブのパス一覧を返す。"""
    directory = os.path.dirname(os.path.abspath(logfile)) or "."
    basename = os.path.basename(logfile)
    try:
        names = os.listdir(directory)
    except OSError:  # pragma: no cover - defensive
        return []
    return [
        os.path.join(directory, name)
        for name in names
        if name.startswith(basename + ".") and name.endswith(".gz")
    ]


def prune_conversation_log(
    logfile: Optional[str] = None,
    days: Optional[int] = None,
    now: Optional[float] = None,
) -> Dict:
    """days 日より古い会話イベントを削除する。

    Args:
        logfile: 対象の JSONL（省略時は `conversation_log.DEFAULT_LOGFILE`）。
        days: 保存日数。None なら設定値を読む。0 以下なら**何もしない**。
        now: 判定基準時刻（テスト用）。

    Returns dict:
        {"pruned": bool, "kept": int, "removed": int, "archives_removed": int,
         "days": int}

    タイムスタンプが読めない行は残す（古いと判断しない）。ライブログの書き戻しは
    原子的に行い、0600 を維持する。
    """
    path = logfile if logfile is not None else _DEFAULT_LOGFILE
    retention = configured_retention_days() if days is None else int(days)
    result: Dict = {"pruned": False, "kept": 0, "removed": 0,
                    "archives_removed": 0, "days": retention}
    if retention <= 0:
        return result

    cutoff = cutoff_timestamp(retention, now=now)

    kept_lines: List[str] = []
    removed = 0
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        kept_lines.append(line.rstrip("\n"))  # 読めない行は残す
                        continue
                    ts = obj.get("timestamp") if isinstance(obj, dict) else None
                    if isinstance(ts, (int, float)) and ts < cutoff:
                        removed += 1
                        continue
                    kept_lines.append(line.rstrip("\n"))
        except OSError as e:  # pragma: no cover - defensive
            logger.warning("会話ログの読み込みに失敗しました: %s", e)
            return result

        if removed:
            content = ("\n".join(kept_lines) + "\n") if kept_lines else ""
            try:
                if _atomic_write_text is not None:
                    _atomic_write_text(path, content, restrict=True)
                else:  # pragma: no cover - fsutil は常に存在する想定
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(content)
            except Exception as e:
                logger.warning("会話ログの書き戻しに失敗しました: %s", e)
                return result

    archives_removed = 0
    for archive in _archives_for(path):
        epoch = _archive_epoch(archive)
        if epoch is None or epoch >= cutoff:
            continue
        # ローテーション時刻より新しいイベントはこのアーカイブに存在しえないので、
        # 丸ごと削除してよい（展開不要）。
        try:
            os.remove(archive)
            archives_removed += 1
        except OSError as e:  # pragma: no cover - defensive
            logger.debug("アーカイブの削除に失敗しました (%s): %s", archive, e)

    result.update({
        "pruned": bool(removed or archives_removed),
        "kept": len(kept_lines),
        "removed": removed,
        "archives_removed": archives_removed,
    })
    return result


def apply_retention_if_configured(
    logfile: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict:
    """設定に保存日数があれば適用する（無ければ何もしない）。

    起動時に 1 回呼ぶことを想定した薄いラッパ。例外は握りつぶす — 保存期間の
    適用に失敗してもアプリの起動は止めない。
    """
    try:
        days = configured_retention_days(config_path)
        if days <= 0:
            return {"pruned": False, "kept": 0, "removed": 0,
                    "archives_removed": 0, "days": 0}
        return prune_conversation_log(logfile=logfile, days=days)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("保存期間の適用に失敗しました: %s", e)
        return {"pruned": False, "kept": 0, "removed": 0,
                "archives_removed": 0, "days": 0}
