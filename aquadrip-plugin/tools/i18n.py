# -*- coding: utf-8 -*-
"""i18n — 插件国际化支持(Qt Linguist 流程)

语言解析优先级:
  1. QSettings 中用户显式选择的语言(aQuaDrip/language)
  2. QGIS 界面语言(UI locale)

翻译文件: i18n/aquadrip_<locale>.qm(lrelease 编译产物)。
源语言为简体中文——无匹配翻译时字符串原样显示中文,
因此 zh_CN 不需要 .qm(零翻译即中文)。
"""

import os

from qgis.PyQt.QtCore import QSettings, QTranslator, QLocale
from qgis.PyQt.QtWidgets import QApplication

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")

# 支持的语言: 设置值 → (显示名, locale 名)
# locale 为 None 表示源语言(中文),不需要 .qm
LANGUAGES = {
    "auto": (None, None),          # 跟随 QGIS 界面语言
    "zh_CN": ("简体中文", None),
    "en_US": ("English", "en_US"),
}

SETTING_KEY = "aQuaDrip/language"

_translator = None  # 已安装的 QTranslator(unload 时移除)


def resolve_locale() -> str:
    """解析当前应使用的 locale(如 zh_CN / en_US)"""
    choice = QSettings().value(SETTING_KEY, "auto", type=str) or "auto"
    if choice == "auto":
        # 跟随 QGIS 界面语言。QgsApplication.locale() 反映 QGIS 的
        # 语言设置(含 override);注意 QApplication 没有 locale() 方法。
        try:
            from qgis.core import QgsApplication
            loc = str(QgsApplication.locale() or "").strip()
            if loc:
                return loc
        except Exception:
            pass
        return QLocale.system().name()
    lang = LANGUAGES.get(choice)
    if lang and lang[1]:
        return lang[1]
    return "zh_CN"  # 显式选中文或未知值


def install_translator() -> bool:
    """按解析出的 locale 加载并安装翻译器。

    必须在任何 UI 字符串求值之前调用(classFactory 里),
    语言不匹配或无翻译文件时字符串按源语言(中文)显示。
    """
    global _translator
    remove_translator()

    locale = resolve_locale()
    if not locale or locale.startswith("zh"):
        return False  # 中文是源语言,无需加载

    # 依次尝试精确匹配(en_US)与语言级匹配(en)
    translator = QTranslator()
    for candidate in (locale, locale.split("_")[0]):
        if translator.load(os.path.join(I18N_DIR, f"aquadrip_{candidate}.qm")):
            QApplication.instance().installTranslator(translator)
            _translator = translator
            return True
    return False


def remove_translator():
    """卸载已安装的翻译器(unload 时调用)"""
    global _translator
    if _translator is not None:
        app = QApplication.instance()
        if app is not None:
            app.removeTranslator(_translator)
        _translator = None


def set_language(choice: str) -> str:
    """持久化语言选择。返回提示用户重启所需的消息(已翻译上下文)。"""
    QSettings().setValue(SETTING_KEY, choice)
    from qgis.PyQt.QtWidgets import QApplication
    return QApplication.translate("AQuaDripPlugin",
                                  "语言设置已保存,重启 QGIS 后生效。")
