# -*- coding: utf-8 -*-

import os
import sys
import threading
import logging
from dataclasses import dataclass
from typing import Callable

import xbmc
import xbmcvfs
import xbmcaddon

import utils
import kodilogging

from resources.lib import migrate
from myepisodes import MyEpisodes, SHOW_ID_ERR

_addon = xbmcaddon.Addon()
_language = _addon.getLocalizedString

kodilogging.config()
logger = logging.getLogger(__name__)

# A refused migration would otherwise replay its four website requests on every
# start and every settings change. One attempt per Kodi run is enough.
_migration_tried = False


def _acquire_api_key() -> tuple[str, bool]:
    """Return the key to work with, and whether a pre-4.0.0 login was found."""
    global _migration_tried

    api_key = utils.getSetting("ApiKey")
    if api_key:
        return api_key, False

    # Kodi keeps the stored value of a setting we have since deleted, so a
    # leftover Username marks an install that predates the API key.
    stored = xbmcvfs.translatePath(
        os.path.join(_addon.getAddonInfo("profile"), "settings.xml")
    )
    username, password = migrate.stored_credentials(stored)
    if not username or not password or _migration_tried:
        return "", bool(username)

    _migration_tried = True
    logger.debug("Trading the stored login of '%s' for an API key.", username)
    api_key = migrate.mint_api_key(username, password)
    if not api_key:
        return "", True

    utils.setSetting("ApiKey", api_key)
    utils.notif(_language(32913), time=5000)
    return api_key, True


def init_myepisodes() -> MyEpisodes:
    api_key, had_password_login = _acquire_api_key()

    if not api_key:
        # Point an upgrading user at what changed, rather than at a bare
        # authentication failure they cannot act on.
        utils.notif(_language(32910 if had_password_login else 32912), time=5000)
        return MyEpisodes("")

    mye = MyEpisodes(api_key)
    mye.login()
    if not mye.is_logged:
        utils.notif(_language(32912), time=2500)
        return mye

    utils.notif(f"{mye.username} {_language(32911)}", time=2500)
    if not mye.populate_shows():
        utils.notif(_language(32927), time=2500)
    return mye


class MEMonitor(xbmc.Monitor):
    def __init__(self, action: Callable[[], None]) -> None:
        xbmc.Monitor.__init__(self)
        self.action = action

    def onSettingsChanged(self) -> None:
        logger.debug("User changed settings")
        self.action()


@dataclass
class MEProperties:
    showid: int = 0
    season: int = 0
    episode: int = 0
    title: str = ""
    is_excluded: bool = False
    total_time: int = sys.maxsize
    last_pos: float = 0


class MEPlayer(xbmc.Player):
    def __init__(self) -> None:
        xbmc.Player.__init__(self)
        logger.debug("MEPlayer - init")
        # Kodi keeps every Monitor it is handed, so build exactly one.
        self.monitor = MEMonitor(self._reset)
        self._playback_lock = threading.Event()
        self._tracker = threading.Thread(target=self._track_position)
        self._resetting = False
        self._reset()

    def _reset(self) -> None:
        # Writing the migrated key fires onSettingsChanged, whose action is
        # this method. Let the first pass finish rather than race itself.
        if self._resetting:
            return

        self._resetting = True
        try:
            logger.debug("_reset called")
            self.resetTracker()
            self.props = MEProperties()
            self.mye: MyEpisodes = init_myepisodes()
            if self.mye.is_logged:
                logger.debug("MyePlayer - account is logged successfully.")
        finally:
            self._resetting = False

    def resetTracker(self) -> None:
        self._playback_lock.clear()
        if self._tracker.is_alive():
            self._tracker.join()
        self._tracker = threading.Thread(target=self._track_position)

    def _track_position(self) -> None:
        while self._playback_lock.is_set() and not self.monitor.abortRequested():
            try:
                self.props.last_pos = self.getTime()
            except Exception:
                logger.debug("Playback ended while tracking.", exc_info=True)
                self._playback_lock.clear()
            logger.debug("Tracker time = %d", self.props.last_pos)
            xbmc.sleep(250)
        logger.debug("Tracker time (ended) = %d", self.props.last_pos)

    def _add_show(self) -> None:
        if not utils.getSettingAsBool("auto-add"):
            logger.debug("Auto-add function disabled.")
            return

        # self.mye.shows is already current: find_show_id refreshed it, and so
        # does every add that goes through.
        if self.props.showid in self.mye.shows.values():
            logger.debug("Show is already in the account.")
            return

        added = 32925 if self.mye.add_show(self.props.showid) else 32926
        utils.notif(f"{self.props.title} {_language(added)}")

    def onAVStarted(self) -> None:
        if not self.mye.is_logged:
            return

        self._playback_lock.set()
        self.props.total_time = self.getTotalTime()
        self._tracker.start()

        filename_full_path = self.getPlayingFile()
        # We don't want to take care of any URL because we can't really gain
        # information from it.
        self.props.is_excluded = False
        if utils.is_excluded(filename_full_path):
            self.props.is_excluded = True
            self.resetTracker()
            return

        # Try to find the title with the help of Kodi (Theses came from
        # Kodi.Subtitles add-ons)
        try:
            self.props.season = int(xbmc.getInfoLabel("VideoPlayer.Season"))
        except ValueError:
            self.props.season = 0
        logger.debug("Player - Season: %02d", self.props.season)

        try:
            self.props.episode = int(xbmc.getInfoLabel("VideoPlayer.Episode"))
        except ValueError:
            self.props.episode = 0
        logger.debug("Player - Episode: %02d", self.props.episode)

        self.props.title = xbmc.getInfoLabel("VideoPlayer.TVshowtitle")
        logger.debug("Player - TVShow: %s", self.props.title)

        if self.props.title == "":
            filename = os.path.basename(filename_full_path)
            logger.debug("Player - Filename: '%s'", filename)
            self.props.title, self.props.season, self.props.episode = self.mye.get_info(
                filename
            )
            logger.debug("Player - TVShow: '%s'", self.props.title)

        logger.debug(
            "Title: '%s' - Season: %02d - Ep: %02d ",
            self.props.title,
            self.props.season,
            self.props.episode,
        )
        if not self.props.season and not self.props.episode:
            # It's not a show. If it should be recognised as one. Send a bug.
            self.resetTracker()
            return

        self.props.showid = self.mye.find_show_id(self.props.title)
        if self.props.showid == SHOW_ID_ERR:
            utils.notif(f"{self.props.title} {_language(32923)}", time=3000)
            self.resetTracker()
            return
        logger.debug(
            "Player - Found : '%s' - %02d (S%02d E%02d",
            self.props.title,
            self.props.showid,
            self.props.season,
            self.props.episode,
        )

        utils.notif(self.props.title, time=2000)
        self._add_show()

    def onPlayBackStopped(self) -> None:
        # User stopped the playback
        self.onPlayBackEnded()

    def onPlayBackEnded(self) -> None:
        self.resetTracker()

        if not self.mye.is_logged:
            return

        logger.debug("onPlayBackEnded: is_exluded: %r", self.props.is_excluded)
        if self.props.is_excluded:
            return

        logger.debug(
            "last_pos / total_time : %d / %d",
            self.props.last_pos,
            self.props.total_time,
        )

        actual_percent = (self.props.last_pos / self.props.total_time) * 100
        logger.debug(
            "last_pos / total_time : %d / %d = %d%%",
            self.props.last_pos,
            self.props.total_time,
            actual_percent,
        )

        # The settings file states the domain, so no clamp is needed here.
        min_percent = utils.getSettingAsInt("watched-percent")
        logger.debug("min_percent: %d%%", min_percent)
        if actual_percent < min_percent:
            return

        # In case it was deleted or whatever happened during playback
        self._add_show()

        # Playback is finished, set the items to watched
        found = (
            32924
            if self.mye.set_episode_watched(
                self.props.showid, self.props.season, self.props.episode
            )
            else 32923
        )
        utils.notif(
            f"{self.props.title} ({self.props.season:02} - {self.props.episode:02}) {_language(found)}"
        )


def run() -> None:
    player = MEPlayer()

    logger.debug(
        "[%s] - Version: %s Started",
        _addon.getAddonInfo("name"),
        _addon.getAddonInfo("version"),
    )

    # Stay alive without a key. onSettingsChanged is how the key the user has
    # just pasted gets picked up, and a service that has exited never hears it.
    player.monitor.waitForAbort()
    player.resetTracker()
