#!/usr/bin/env python3
"""
Internationalization (i18n) Module for Memo System
==================================================
Multi-language support with automatic translation and locale detection.
Based on JSON translation files in locales directory.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import locale


class I18N:
    """Internationalization manager for memo system"""

    LOCALES_DIR = Path("locales")
    SUPPORTED_LANGUAGES = {
        'en': 'English', 'ja': '日本語', 'zh': '中文', 'es': 'Español', 'fr': 'Français',
        'de': 'Deutsch', 'ko': '한국어', 'ru': 'Русский', 'ar': 'العربية', 'pt': 'Português',
        'it': 'Italiano', 'nl': 'Nederlands', 'sv': 'Svenska', 'da': 'Dansk', 'no': 'Norsk',
        'fi': 'Suomi', 'pl': 'Polski', 'cs': 'Čeština', 'sk': 'Slovenčina', 'hu': 'Magyar',
        'tr': 'Türkçe', 'el': 'Ελληνικά', 'he': 'עברית', 'th': 'ไทย', 'vi': 'Tiếng Việt',
        'id': 'Bahasa Indonesia', 'ms': 'Bahasa Melayu', 'tl': 'Filipino', 'hi': 'हिन्दी',
        'bn': 'বাংলা', 'ta': 'தமிழ்', 'te': 'తెలుగు', 'mr': 'मराठी', 'gu': 'ગુજરાતી',
        'kn': 'ಕನ್ನಡ', 'ml': 'മലയാളം', 'pa': 'ਪੰਜਾਬੀ', 'ur': 'اردو', 'fa': 'فارسی',
        'am': 'አማርኛ', 'sw': 'Kiswahili', 'zu': 'isiZulu', 'af': 'Afrikaans', 'xh': 'isiXhosa',
        'st': 'Sesotho', 'tn': 'Setswana', 'ts': 'Xitsonga', 'ss': 'siSwati', 've': 'Tshivenda',
        'nr': 'isiNdebele', 'nso': 'Sesotho sa Leboa', 'uk': 'Українська', 'bg': 'Български',
        'hr': 'Hrvatski', 'sl': 'Slovenščina', 'et': 'Eesti', 'lv': 'Latviešu', 'lt': 'Lietuvių',
        'ro': 'Română', 'sr': 'Српски', 'mk': 'Македонски', 'sq': 'Shqip', 'bs': 'Bosanski',
        'me': 'Crnogorski'
    }
    TRANSLATIONS: Dict[str, Dict[str, str]] = {}
    _external_loaded = False

    def __init__(self, language: Optional[str] = None):
        """Initialize i18n with specified or detected language"""
        self.load_external_resources()
        preferred = language or self._detect_language()
        try:
            self.set_language(preferred)
        except ValueError:
            self.set_language('en')

    def _detect_language(self) -> str:
        """Detect system language"""
        # Try environment variable first
        lang = os.environ.get('MEMO_LANG', '').lower()[:2]
        if lang in self.SUPPORTED_LANGUAGES:
            return lang

        # Try system locale
        try:
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                lang_code = system_locale.split('_')[0].lower()
                if lang_code in self.SUPPORTED_LANGUAGES:
                    return lang_code
        except:
            pass

        # Default to English
        return 'en'

    @classmethod
    def load_external_resources(cls) -> None:
        """Load translations from locales directory once."""
        if cls._external_loaded:
            return

        if cls.LOCALES_DIR.exists():
            for file_path in cls.LOCALES_DIR.glob("*.json"):
                language_code = file_path.stem.lower()
                try:
                    with open(file_path, 'r', encoding='utf-8') as fh:
                        payload = json.load(fh)
                except (OSError, json.JSONDecodeError):
                    continue

                translations, language_name = cls._normalize_payload(payload)
                if not translations:
                    continue

                existing = cls.TRANSLATIONS.setdefault(language_code, {})
                existing.update(translations)
                if language_name:
                    cls.SUPPORTED_LANGUAGES[language_code] = language_name
                else:
                    cls.SUPPORTED_LANGUAGES.setdefault(language_code, language_code)

        cls._external_loaded = True

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> tuple:
        """Separate translation entries from metadata."""
        if not isinstance(payload, dict):
            return {}, None

        meta = payload.get('__meta__')
        language_name: Optional[str] = None
        if isinstance(meta, dict):
            language_name = meta.get('language_name')

        translations = {
            key: value
            for key, value in payload.items()
            if isinstance(key, str) and not key.startswith('__')
        }

        return translations, language_name

    def get(self, key: str, **kwargs) -> str:
        """Get translated string with optional formatting"""
        # Try direct translation first
        translation = self.translations.get(key, None)

        # Fall back to key if no translation available
        if translation is None:
            translation = key

        # Apply formatting if provided
        if kwargs:
            try:
                translation = translation.format(**kwargs)
            except:
                pass

        return translation

    def set_language(self, language: str):
        """Change current language"""
        self.load_external_resources()
        normalized = language.lower()
        if normalized in self.TRANSLATIONS:
            self.language = normalized
            self.translations = self.TRANSLATIONS.get(normalized, self.TRANSLATIONS['en'])
            return

        raise ValueError(f"Unsupported language: {language}")

    def get_supported_languages(self) -> Dict[str, str]:
        """Get list of supported languages"""
        self.load_external_resources()
        return self.SUPPORTED_LANGUAGES.copy()

    def format_date(self, date_obj) -> str:
        """Format date according to locale"""
        try:
            # Get date format for current language
            format_map = {
                'en': '%Y-%m-%d %H:%M:%S', 'ja': '%Y年%m月%d日 %H:%M:%S',
                'zh': '%Y年%m月%d日 %H:%M:%S', 'es': '%d/%m/%Y %H:%M:%S',
                'fr': '%d/%m/%Y %H:%M:%S', 'de': '%d.%m.%Y %H:%M:%S',
                'ko': '%Y년 %m월 %d일 %H:%M:%S', 'ru': '%d.%m.%Y %H:%M:%S',
                'ar': '%Y-%m-%d %H:%M:%S', 'pt': '%d/%m/%Y %H:%M:%S',
                'it': '%d/%m/%Y %H:%M:%S', 'nl': '%d-%m-%Y %H:%M:%S',
            }
            date_format = format_map.get(self.language, '%Y-%m-%d %H:%M:%S')
            return date_obj.strftime(date_format)
        except:
            return str(date_obj)


# Global i18n instance
_i18n_instance = None


def get_i18n() -> I18N:
    """Get global i18n instance"""
    global _i18n_instance
    if _i18n_instance is None:
        _i18n_instance = I18N()
    return _i18n_instance


def _(key: str, **kwargs) -> str:
    """Shortcut for translation"""
    return get_i18n().get(key, **kwargs)