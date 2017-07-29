#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import threading
import xbmc
import xbmcaddon

_addon         = xbmcaddon.Addon()
_cwd           = _addon.getAddonInfo('path')
_icon_path     = _addon.getAddonInfo("icon")
_icon          = xbmc.translatePath(_icon_path).decode('utf-8')
_scriptname    = _addon.getAddonInfo('name')
_version       = _addon.getAddonInfo('version')
_language      = _addon.getLocalizedString
_resource_path = os.path.join(_cwd, 'resources', 'lib')
_resource      = xbmc.translatePath(_resource_path).decode('utf-8')

from resources.lib.myepisodes import MyEpisodes

class Monitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs['action']

    def onSettingsChanged(self):
        log('#DEBUG# onSettingsChanged')
        self.action()

class Player(xbmc.Player):
    MAX_LOGIN_ATTEMPTS = 3

    def __init__(self):
        xbmc.Player.__init__(self)
        log('Player - init')
        self.login_attempts = 0
        self.mye = self._createMyEpisodes()
        if self.mye is not None:
            self._tryLogin()

        self.showid = self.episode = self.title = self.season = None
        self._total_time = 999999
        self._last_pos = 0
        self._min_percent = int(_addon.getSetting('watched-percent'))
        self._tracker = None
        self._playback_lock = threading.Event()
        self._monitor = Monitor(action=self._reset)

    def _reset(self):
        self._tearDown()
        if self.mye:
            del self.mye
        self.__init__()

    def _trackPosition(self):
        while self._playback_lock.isSet() and not xbmc.abortRequested:
            try:
                self._last_pos = self.getTime()
            except:
                self._playback_lock.clear()
            log('Inside Player. Tracker time = %s' % self._last_pos)
            xbmc.sleep(250)
        log('Position tracker ending with last_pos = %s' % self._last_pos)

    def _setUp(self):
        self._playback_lock.set()
        self._tracker = threading.Thread(target=self._trackPosition)
        self.mye.is_title_filename = False

    def _tearDown(self):
        if hasattr(self, '_playback_lock'):
            self._playback_lock.clear()
        self._monitor = None
        if not hasattr(self, '_tracker'):
            return
        if self._tracker is None:
            return
        if self._tracker.isAlive():
            self._tracker.join()
        self._tracker = None

    def _createMyEpisodes(self):
        username = _addon.getSetting('Username').decode('utf-8', 'replace')
        password = _addon.getSetting('Password')

        login_notif = _language(32912)
        if username is "" or password is "":
            notif(login_notif, time=2500)
            self.login_attempts = self.MAX_LOGIN_ATTEMPTS
            return None

        mye = MyEpisodes(username, password)
        return mye

    def _tryLogin(self):
        if self.mye.is_logged:
            return True

        keep_trying = self.mye.login()

        if self.mye.is_logged:
            login_notif = "%s %s" % (_addon.getSetting('Username'), _language(32911))
            self.login_attempts = 0
        else:
            login_notif = _language(32912)
            self.login_attempts += 1

        notif(login_notif, time=2500)

        if self.mye.is_logged and (not self.mye.get_show_list()):
            notif(_language(32927), time=2500)

        return self.mye.is_logged

    def _addShow(self):
        # Add the show if it's not already in our account
        if self.showid in self.mye.shows.values():
            notif(self.title, time=2000)
            return
        was_added = self.mye.add_show(self.showid)
        added = 32926
        if was_added:
            added = 32925
        notif("%s %s" % (self.title, _language(added)))

    def keepGoing(self):
        return self.MAX_LOGIN_ATTEMPTS > self.login_attempts

    def onPlayBackStarted(self):
        if not self._tryLogin():
            return

        self._setUp()
        self._total_time = self.getTotalTime()
        self._tracker.start()

        filename_full_path = self.getPlayingFile().decode('utf-8')
        # We don't want to take care of any URL because we can't really gain
        # information from it.
        if _is_excluded(filename_full_path):
            self._tearDown()
            return

        # Try to find the title with the help of XBMC (Theses came from
        # XBMC.Subtitles add-ons)
        self.season = str(xbmc.getInfoLabel("VideoPlayer.Season"))
        log('Player - Season: %s' % self.season)
        self.episode = str(xbmc.getInfoLabel("VideoPlayer.Episode"))
        log('Player - Episode: %s' % self.episode)
        self.title = xbmc.getInfoLabel("VideoPlayer.TVshowtitle")
        log('Player - TVShow: %s' % self.title)
        if self.title == "":
            filename = os.path.basename(filename_full_path)
            log('Player - Filename: %s' % filename)
            self.title, self.season, self.episode = self.mye.get_info(filename)
            log('Player - TVShow: %s' % self.title)

        log("Title: %s - Season: %s - Ep: %s" % (self.title,
                                                 self.season,
                                                 self.episode))
        if not self.season and not self.episode:
            # It's not a show. If it should be recognised as one. Send a bug.
            self._tearDown()
            return

        self.showid = self.mye.find_show_id(self.title)
        if self.showid is None:
            notif("%s %s" % (self.title, _language(32923)), time=3000)
            self._tearDown()
            return
        log('Player - Found : %s - %d (S%s E%s)' % (self.title,
                                                    self.showid,
                                                    self.season,
                                                    self.episode))

        if _addon.getSetting('auto-add') == "true":
            self._addShow()

    def onPlayBackStopped(self):
        # User stopped the playback
        self.onPlayBackEnded()

    def onPlayBackEnded(self):
        if not self._tryLogin():
            return

        self._tearDown()

        actual_percent = (self._last_pos/self._total_time)*100
        log('last_pos / total_time : %s / %s = %s %%' % (self._last_pos,
                                                         self._total_time,
                                                         actual_percent))
        if actual_percent < self._min_percent:
            return

        # Playback is finished, set the items to watched
        found = 32923
        if self.mye.set_episode_watched(self.showid, self.season, self.episode):
            found = 32924
        notif("%s (%s - %s) %s" % (self.title, self.season, self.episode,
                                   _language(found)))

def notif(msg, time=5000):
    notif_msg = "%s, %s, %i, %s" % ('MyEpisodes', msg, time, _icon)
    notif_msg = notif_msg.encode('utf-8', 'replace')
    xbmc.executebuiltin("XBMC.Notification(%s)" % notif_msg)

def log(msg):
    xbmc.log("### [%s] - %s" % (_scriptname, msg.encode('utf-8'), ),
             level=xbmc.LOGDEBUG)

def _is_excluded(filename):
    log("_is_excluded(): Check if '%s' is a URL." % filename)
    excluded_protocols = ["pvr://", "http://", "https://"]
    if any(protocol in filename for protocol in excluded_protocols):
        return True

    for setting_name in ["ExcludePath", "ExcludePath2", "ExcludePath3"]:
        exclude = _addon.getSetting(setting_name)
        if exclude == "":
            continue
        excludepath = xbmc.translatePath(exclude).decode('utf-8')
        if excludepath in filename:
            log("_is_excluded(): Video is excluded (%s)." % setting_name)
            return True

if __name__ == "__main__":
    player = Player()

    log("[%s] - Version: %s Started" % (_scriptname, _version))

    while not xbmc.abortRequested and player.keepGoing():
        xbmc.sleep(100)

    player._tearDown()
    sys.exit(0)

