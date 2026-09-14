# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import final, TypeVar, Any, Callable, cast

import logging
import re
import requests
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SHOW_ID_ERR = -1

# This is totally stolen from script.xbmc.subtitles plugin !
REGEX_EXPRESSIONS = [
    r"[Ss]([0-9]+)[][._-]*[Ee]([0-9]+)([^\\\\/]*)$",
    r"[\._ \-]([0-9]+)x([0-9]+)([^\\/]*)",  # foo.1x09
    r"[\._ \-]([0-9]+)([0-9][0-9])([\._ \-][^\\/]*)",  # foo.109
    r"([0-9]+)([0-9][0-9])([\._ \-][^\\/]*)",
    r"[\\\\/\\._ -]([0-9]+)([0-9][0-9])[^\\/]*",
    r"Season ([0-9]+) - Episode ([0-9]+)[^\\/]*",  # Season 01 - Episode 02
    r"Season ([0-9]+) Episode ([0-9]+)[^\\/]*",  # Season 01 Episode 02
    r"[\\\\/\\._ -][0]*([0-9]+)x[0]*([0-9]+)[^\\/]*",
    r"\[[Ss]([0-9]+)\]_\[[Ee]([0-9]+)([^\\/]*)",  # foo_[s01]_[e01]
    r"[\._ \-][Ss]([0-9]+)[\.\-]?[Ee]([0-9]+)([^\\/]*)",  # foo, s01e01, foo.s01.e01, foo.s01-e01
    r"s([0-9]+)ep([0-9]+)[^\\/]*",  # foo - s01ep03, foo - s1ep03
    r"[Ss]([0-9]+)[][ ._-]*[Ee]([0-9]+)([^\\\\/]*)$",
    r"[\\\\/\\._ \\[\\(-]([0-9]+)x([0-9]+)([^\\\\/]*)$",
]

API_URL = "https://api.myepisodes.com/v1"
MAX_RETRY_ATTEMPTS = 5

# Lookups run on Kodi's playback callback, so a failing site must not hold that
# thread. Two status retries with a 0.5 backoff cap one request at ~3 seconds.
MAX_STATUS_RETRIES = 2

# A list endpoint serves at most 1000 rows and refuses an offset past 10,000.
PAGE_LIMIT = 1000
MAX_OFFSET = 10000


def sanitize(title: str, replace: str) -> str:
    for char in ["[", "]", "_", "(", ")", ".", "-"]:
        title = title.replace(char, replace)
    return title


def spellings(show_name: str) -> set[str]:
    # A title lifted from a filename has lost its punctuation, so a show is
    # matched under the name the catalogue holds and the flattened spellings
    # a filename produces: "Mr. Robot", "Mr Robot", "S W A T".
    lowered = show_name.lower()
    forms = {
        lowered,
        sanitize(lowered, ""),
        " ".join(sanitize(lowered, " ").split()),
    }
    # A name made only of punctuation flattens to "", which would then be a
    # prefix of every lookup.
    return {form for form in forms if form}


def payload_of(response: requests.Response) -> dict[str, Any]:
    """The decoded body, or {} when the server sent nothing usable."""
    if response.status_code != 200:
        return {}

    try:
        body = response.json()
    except ValueError:
        logger.debug("'%s' answered 200 with a body that is not JSON.", response.url)
        return {}

    if not isinstance(body, dict):
        logger.debug(
            "'%s' answered 200 with %s, not an object.", response.url, type(body)
        )
        return {}

    return body


F = TypeVar("F", bound=Callable[..., Any])


def logged(func: F) -> F:
    def wrapper(*args: MyEpisodes, **kwargs: str) -> F:
        mye = args[0]
        if not mye.is_logged:
            mye.login()
        return func(*args, **kwargs)

    return cast(F, wrapper)


def retry_session(retries: int, backoff_factor: float = 0.5) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        status=MAX_STATUS_RETRIES,
        # The API allows 10 requests a second and answers 429 with a
        # Retry-After above that, which urllib3 honours on its own.
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=backoff_factor,
        allowed_methods=None,
        raise_on_status=False,
        raise_on_redirect=False,
    )

    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


@final
class MyEpisodes:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.username = ""
        self.req = retry_session(retries=MAX_RETRY_ATTEMPTS)
        self.req.headers["Authorization"] = f"Bearer {api_key}"
        self.is_logged = False
        self.shows: dict[str, int] = {}

    def __del__(self) -> None:
        self.req.close()

    def __repr__(self) -> str:
        # The key is a credential. Never let it reach a log line.
        return "MyEpisodes(api_key='***')"

    def login(self) -> None:
        # A key opens no session. This confirms the key is accepted and picks
        # up the account name for the welcome notification.
        if not self.api_key:
            return

        payload = payload_of(self.req.get(f"{API_URL}/me"))
        if not payload:
            return

        self.is_logged = True
        self.username = payload.get("username", "")

    def _remember(self, show_id: int, show_name: str) -> None:
        for spelling in spellings(show_name):
            self.shows[spelling] = show_id

    @logged
    def populate_shows(self) -> bool:
        self.shows.clear()

        offset = 0
        while offset <= MAX_OFFSET:
            payload = payload_of(
                self.req.get(
                    f"{API_URL}/me/shows",
                    params={
                        "ignored": "0",
                        "limit": str(PAGE_LIMIT),
                        "offset": str(offset),
                    },
                )
            )
            if not payload:
                return False

            rows = payload.get("data", [])
            for show in rows:
                self._remember(int(show["showid"]), show["showname"])

            if not rows or not payload.get("meta", {}).get("has_more"):
                break
            # Page by what the server served, not by what we asked for.
            offset += len(rows)

        return True

    @logged
    def find_show_id(self, show_name: str) -> int:
        # An empty term matches every show, so the first row would win.
        name = show_name.strip().lower()
        if not name:
            return SHOW_ID_ERR

        show_id = self._from_account(name)
        if show_id != SHOW_ID_ERR:
            return show_id

        # A miss can only mean the account has changed under us, so this is
        # the one place worth paying for a refresh.
        self.populate_shows()
        show_id = self._from_account(name)
        if show_id != SHOW_ID_ERR:
            return show_id

        # You should really never fall there, at this point, the show should be
        # in your account, except if you disabled the auto add feature.
        return self._search_catalogue(name)

    def _from_account(self, name: str) -> int:
        if name in self.shows:
            return self.shows[name]

        # A partial title still resolves as long as it points at one show.
        matches = {
            show: show_id
            for show, show_id in self.shows.items()
            if name in show or name.startswith(show)
        }
        if len(set(matches.values())) == 1:
            return next(iter(matches.values()))

        return SHOW_ID_ERR

    def _search_catalogue(self, name: str) -> int:
        show_id = self._best_match(name, name)
        if show_id != SHOW_ID_ERR:
            return show_id

        # The catalogue matches the search term literally, so a title taken
        # from a filename ("Mr Robot") never reaches its punctuated entry
        # ("Mr. Robot"). Search the longest word and match the rest here.
        words = name.split()
        if len(words) < 2:
            return SHOW_ID_ERR

        return self._best_match(max(words, key=len), name)

    def _best_match(self, term: str, name: str) -> int:
        payload = payload_of(self.req.get(f"{API_URL}/shows", params={"search": term}))
        results = payload.get("data", [])

        # An exact name wins. A prefix match is the fallback, which is how the
        # account lookup above resolves a partial title.
        prefix_match = SHOW_ID_ERR
        for show in results:
            names = spellings(show["showname"])
            if name in names:
                return int(show["showid"])
            if prefix_match == SHOW_ID_ERR and any(s.startswith(name) for s in names):
                prefix_match = int(show["showid"])

        return prefix_match

    # This is totally stolen from script.xbmc.subtitles plugin !
    def get_info(self, file_name: str) -> tuple[str, int, int]:
        title = ""
        season = SHOW_ID_ERR
        episode = SHOW_ID_ERR

        for regex in REGEX_EXPRESSIONS:
            response_file = re.findall(regex, file_name)
            if response_file:
                season = int(response_file[0][0])
                episode = int(response_file[0][1])
            else:
                continue
            title = re.split(regex, file_name)[0]
            title = sanitize(title, " ")
            title = title.strip()
            return title.title(), season, episode

        return title, season, episode

    def add_show(self, show_id: int) -> bool:
        return self._follow(show_id)

    def del_show(self, show_id: int) -> bool:
        return self._unfollow(show_id)

    @logged
    def _follow(self, show_id: int) -> bool:
        # Idempotent: 201 the first time, 200 after, and an existing watched
        # history is left alone.
        response = self.req.put(f"{API_URL}/me/shows/{show_id}")
        if response.status_code not in (200, 201):
            return False

        self.populate_shows()
        return True

    @logged
    def _unfollow(self, show_id: int) -> bool:
        # Destructive: this drops every acquired and watched flag for the
        # show, exactly as removing it on the site does.
        response = self.req.delete(f"{API_URL}/me/shows/{show_id}")
        if response.status_code != 200:
            return False

        self.populate_shows()
        return True

    def set_episode_watched(self, show_id: int, season: int, episode: int) -> bool:
        return self._set_episode_un_watched(show_id, season, episode)

    def set_episode_unwatched(self, show_id: int, season: int, episode: int) -> bool:
        return self._set_episode_un_watched(show_id, season, episode, watched=False)

    @logged
    def _set_episode_un_watched(
        self, show_id: int, season: int, episode: int, watched: bool = True
    ) -> bool:
        response = self.req.put(
            f"{API_URL}/me/episodes/{show_id}/{season}/{episode}",
            json={"watched": watched},
        )
        return response.status_code == 200
