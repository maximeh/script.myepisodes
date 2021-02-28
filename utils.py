# -*- coding: utf-8 -*-

import logging
import xbmc
import xbmcvfs
import xbmcaddon

logger = logging.getLogger(__name__)

_addon = xbmcaddon.Addon()
_icon_path = _addon.getAddonInfo("icon")
_icon = xbmcvfs.translatePath(_icon_path)
_scriptname = _addon.getAddonInfo("name")


def getSettingAsBool(setting):
    return _addon.getSetting(setting).lower() == "true"


def getSetting(setting):
    return _addon.getSetting(setting).strip()


def getSettingAsInt(setting):
    try:
        return int(getSetting(setting))
    except ValueError:
        return 0


def notif(msg, time=5000):
    logger.debug(f"notif with XBMC.Notification(MyEpisodes, {msg}, {time}, {_icon})")
    xbmc.executebuiltin(f"Notification(MyEpisodes, {msg}, {time}, {_icon})")


def is_excluded(filename):
    logger.debug("_is_excluded(): Check if '%s' is a URL.", filename)
    excluded_protocols = ["pvr://", "http://", "https://"]
    if any(protocol in filename for protocol in excluded_protocols):
        logger.debug("_is_excluded(): '%s' is a URL; it's excluded.", filename)
        return True

    logger.debug("_is_excluded(): Check if '%s' is in an excluded path.", filename)

    for index in range(1, 4):
        if index == 1:
            index = ""
        exclude_option = getSettingAsBool("ExcludePathOption{}".format(index))
        logger.debug("ExcludePathOption%s", index)
        logger.debug("testing with %s", exclude_option)
        if not exclude_option:
            continue
        exclude_path = getSetting("ExcludePath{}".format(index))
        logger.debug("testing with %s", exclude_path)
        if exclude_path == "":
            continue
        if exclude_path in filename:
            logger.debug("_is_excluded(): Video is excluded (ExcludePath%s).", index)
            return True
    return False
