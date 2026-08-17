import os
import json
import locale
from typing import Dict
# NOTE: tkinter is intentionally not imported at module level — it is only used
# in the commented-out GUI demo below, and importing it unconditionally made this
# module unimportable in headless environments (no Tk) despite not needing a GUI.

# 100+言語対応のフォントマップ例（必要に応じて拡張）
FONT_MAP = {
    'ja': 'Yu Gothic UI', 'en': 'Arial', 'zh': 'Noto Sans SC', 'zh-tw': 'Microsoft JhengHei',
    'ko': 'Malgun Gothic', 'ru': 'Arial', 'ar': 'Noto Naskh Arabic', 'hi': 'Noto Sans Devanagari',
    'th': 'Tahoma', 'vi': 'Arial', 'es': 'Arial', 'fr': 'Arial', 'de': 'Arial', 'pt': 'Arial',
    'id': 'Arial', 'bn': 'Noto Sans Bengali', 'ur': 'Noto Nastaliq Urdu', # ...追加可
}
LOCALES_DIR = os.path.join(os.path.dirname(__file__), 'i18n', 'locales')


def _discover_supported_langs():
    try:
        return frozenset(
            f[:-5] for f in os.listdir(LOCALES_DIR) if f.endswith('.json')
        ) or frozenset({'en'})
    except OSError:
        return frozenset({'en'})


# dashboard.py's get_lang() passes request.args.get('lang') — a fully
# attacker-controlled, unvalidated string — straight into I18N(lang), which
# used it directly as a key into the process-wide, unbounded
# _translation_cache class dict. An unauthenticated caller sending a unique
# ?lang= value on every request grows that cache without bound (memory
# exhaustion) and lets an arbitrary string get stored in the session/
# reflected into rendered URLs. Constraining to the actual locale files
# present bounds the cache to a fixed, small size regardless of input.
_SUPPORTED_LANGS = _discover_supported_langs()


class I18N:
    # 言語コード → 翻訳辞書。プロセス全体で共有するのでキーは
    # _SUPPORTED_LANGS へクランプ済み（load_translation 参照）。
    _translation_cache: Dict[str, Dict] = {}
    def __init__(self, lang=None):
        # self.lang keeps the raw detected/requested value (e.g. "fr" from
        # SATIN_LANG) — it's used for FONT_MAP.get(self.lang, 'Arial')
        # font-matching for languages that have a font mapping but no
        # translation file. Only the *cache key* inside load_translation is
        # clamped to the small, fixed set of languages that actually have a
        # locale file, so an arbitrary caller-supplied lang can't grow
        # _translation_cache without bound.
        self.lang = lang or self.detect_language()
        self.translations = self.load_translation(self.lang)
        self.font = FONT_MAP.get(self.lang, 'Arial')
    def detect_language(self):
        lang = os.environ.get('SATIN_LANG')
        if lang:
            return lang.lower()
        try:
            loc = locale.getlocale()[0]
        except Exception:
            loc = None
        if loc:
            return loc.lower().split('_')[0]
        return 'en'
    def load_translation(self, lang):
        # lang can be an arbitrary caller-supplied string (dashboard.py's
        # get_lang() used to pass request.args.get('lang') through
        # unvalidated). Clamping to the known-safe set BEFORE building any
        # path/cache key closes two issues at once: (1) unbounded growth of
        # the process-wide _translation_cache class dict from unique inputs
        # (memory-exhaustion DoS), and (2) path traversal — the old code
        # built os.path.join(LOCALES_DIR, f'{lang}.json') from the raw value
        # before ever checking it, so lang="../../config/mood_config" would
        # attempt to open and JSON-parse a file outside LOCALES_DIR entirely.
        cache_key = lang if lang in _SUPPORTED_LANGS else 'en'
        if cache_key in self._translation_cache:
            return self._translation_cache[cache_key]
        path = os.path.join(LOCALES_DIR, f'{cache_key}.json')
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
                data = data if isinstance(data, dict) else {}
                self._translation_cache[cache_key] = data
                return data
        except Exception:
            return {}
    def t(self, key, default=None):
        # `default or key` would collapse a falsy-but-intentional default (""，0)
        # to the raw key. Distinguish "no default given" (None) from a falsy one.
        val = self.translations.get(key)
        if val is not None:
            return val
        return key if default is None else default
    def get_font(self, size=12, weight="normal"):
        return (self.font, size, weight)
# --- Flask/Web用: 言語切替はリクエストやセッションから ---
# --- サンプルGUI統合例 ---
# if __name__ == "__main__":
#     i18n = I18N()
#     root = tk.Tk()
#     root.title(i18n.t("title", "Satin 多言語デモ"))
#     tk.Label(root, text=i18n.t("hello", "こんにちは!"), font=i18n.get_font(16)).pack(padx=20, pady=20)
#     tk.Label(root, text=i18n.t("desc", "このUIは自動で言語・フォントが切り替わります。"), font=i18n.get_font(12)).pack(pady=10)
#     root.mainloop()
