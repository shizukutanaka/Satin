"""
多言語サポートモジュール
バージョン: 1.0.0
"""
import json
from pathlib import Path
from typing import Dict, Optional

class I18nManager:
    """多言語管理クラス"""
    def __init__(self):
        self.locale_dir = Path(__file__).parent / "locales"
        self.translations = {}
        self.current_lang = "en"
        self.load_language("en")
    
    def load_language(self, lang_code: str) -> bool:
        """言語を読み込む"""
        try:
            with open(self.locale_dir / f"{lang_code}.json", 'r', encoding='utf-8') as f:
                self.translations[lang_code] = json.load(f)
            self.current_lang = lang_code
            return True
        except Exception:
            return False
    
    def get(self, key: str, **kwargs) -> str:
        """翻訳を取得"""
        keys = key.split('.')
        try:
            value = self.translations[self.current_lang]
            for k in keys:
                value = value[k]
            return value.format(**kwargs) if isinstance(value, str) else str(value)
        except (KeyError, AttributeError):
            return key

# グローバルインスタンス
i18n = I18nManager()

def _(key: str, **kwargs) -> str:
    """翻訳を取得するショートカット"""
    return i18n.get(key, **kwargs)