import os
import json
from functools import lru_cache

import locale
import tkinter as tk

# 100+言語対応のフォントマップ例（必要に応じて拡張）
FONT_MAP = {
    'ja': 'Yu Gothic UI', 'en': 'Arial', 'zh': 'Noto Sans SC', 'zh-tw': 'Microsoft JhengHei',
    'ko': 'Malgun Gothic', 'ru': 'Arial', 'ar': 'Noto Naskh Arabic', 'hi': 'Noto Sans Devanagari',
    'th': 'Tahoma', 'vi': 'Arial', 'es': 'Arial', 'fr': 'Arial', 'de': 'Arial', 'pt': 'Arial',
    'id': 'Arial', 'bn': 'Noto Sans Bengali', 'ur': 'Noto Nastaliq Urdu', # ...追加可
}
LOCALES_DIR = os.path.join(os.path.dirname(__file__), 'locales')

class I18N:
    _translation_cache = {}
    def __init__(self, lang=None):
        self.lang = lang or self.detect_language()
        self.translations = self.load_translation(self.lang)
        self.font = FONT_MAP.get(self.lang, 'Arial')
    def detect_language(self):
        lang = os.environ.get('SATIN_LANG')
        if lang:
            return lang.lower()
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc.lower().split('_')[0]
        return 'en'
    def load_translation(self, lang):
        if lang in self._translation_cache:
            return self._translation_cache[lang]
        path = os.path.join(LOCALES_DIR, f'{lang}.json')
        if not os.path.exists(path):
            path = os.path.join(LOCALES_DIR, 'en.json')
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
                self._translation_cache[lang] = data
                return data
        except Exception:
            return {}
    def t(self, key, default=None):
        return self.translations.get(key, default or key)
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
