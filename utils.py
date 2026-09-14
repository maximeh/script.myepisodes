# -*- coding: utf-8 -*-

import logging
import xbmcgui
import xbmcvfs
import xbmcaddon

logger = logging.getLogger(__name__)

_addon = xbmcaddon.Addon()
_icon_path = _addon.getAddonInfo("icon")
_icon = xbmcvfs.translatePath(_icon_path)
_scriptname = _addon.getAddonInfo("name")


def getSettingAsBool(setting: str) -> bool:
    return _addon.getSettings().getBool(setting)


def getSetting(setting: str) -> str:
    return _addon.getSettings().getString(setting).strip()


def getSettingAsInt(setting: str) -> int:
    return _addon.getSettings().getInt(setting)


def setSetting(setting: str, value: str) -> None:
    # Not getSettings().setString(): on Kodi 20 that writes memory only, because
    # CAddonSettings::Save() is a stub returning false there. Kodi 21 fixed it.
    # Addon.setSetting goes through UpdateSetting + SaveSettings on both.
    _addon.setSetting(setting, value)


def notif(msg: str, time: int = 5000) -> None:
    xbmcgui.Dialog().notification(_scriptname, msg, _icon, time)


def is_excluded(filename: str) -> bool:
    logger.debug("_is_excluded(): Check if '%s' is a URL.", filename)
    excluded_protocols = ["pvr://", "http://", "https://"]
    if any(protocol in filename for protocol in excluded_protocols):
        logger.debug("_is_excluded(): '%s' is a URL; it's excluded.", filename)
        return True

    logger.debug("_is_excluded(): Check if '%s' is in an excluded path.", filename)

    for index in range(1, 4):
        index_str = "" if index == 1 else str(index)
        exclude_option = getSettingAsBool(f"ExcludePathOption{index_str}")
        logger.debug("ExcludePathOption%s", index_str)
        if not exclude_option:
            continue
        exclude_path = getSetting(f"ExcludePath{index_str}")
        logger.debug("testing with '%s'", exclude_path)
        if exclude_path == "":
            continue
        if exclude_path in filename:
            logger.debug(
                "_is_excluded(): Video is excluded (ExcludePath%s).", index_str
            )
            return True
    return False
