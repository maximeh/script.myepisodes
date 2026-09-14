# -*- coding: utf-8 -*-

"""One-shot upgrade from the old username and password to an API key.

An install that predates 4.0.0 still holds a login in the Kodi settings. The
v1 API has no endpoint that issues a key, but the website form does, so the
add-on drives that form once with the stored login and keeps the key. The user
does nothing. Delete this module once the old settings can no longer be found
in the wild.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from xml.etree import ElementTree

import requests

SITE_URL = "https://www.myepisodes.com"

# The name shows on the user's API keys page, so it says who owns the key.
KEY_NAME = "Kodi (script.myepisodes)"
# The add-on follows shows and marks episodes, so a read-only key is not enough.
KEY_SCOPES = "read,write"

logger = logging.getLogger(__name__)

_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
_API_KEY = re.compile(r"myeps_[A-Za-z0-9_-]+")


def stored_credentials(settings_path: str) -> tuple[str, str]:
    """Return the (username, password) a pre-4.0.0 install left behind."""
    try:
        root = ElementTree.parse(settings_path).getroot()
    except (OSError, ElementTree.ParseError):
        logger.debug("No readable stored settings at '%s'.", settings_path)
        return "", ""

    values = {"Username": "", "Password": ""}
    for setting in root.iter("setting"):
        setting_id = setting.get("id", "")
        if setting_id not in values:
            continue
        # Kodi has written the value as element text and as a value attribute
        # across versions.
        values[setting_id] = (setting.text or setting.get("value") or "").strip()

    return values["Username"], values["Password"]


def extract_field(html: str, name: str) -> str:
    """Return the value of the first hidden input called `name`."""
    for tag in _INPUT_TAG.findall(html):
        attributes = dict(_ATTRIBUTE.findall(tag))
        if attributes.get("name") == name:
            return attributes.get("value", "")
    return ""


def extract_key(html: str) -> str:
    """Return the API key a page shows, or "" when it shows none."""
    # The page prints a truncated prefix next to the key itself, so length
    # tells the two apart.
    matches = _API_KEY.findall(html)
    return max(matches, key=len) if matches else ""


def mint_api_key(
    username: str, password: str, session: Optional[requests.Session] = None
) -> str:
    """Log in with the old credentials and create a key. "" if that fails."""
    try:
        if session is not None:
            return _create_key(session, username, password)
        with requests.Session() as own_session:
            return _create_key(own_session, username, password)
    except requests.RequestException:
        logger.debug("Could not reach the site to create a key.", exc_info=True)
        return ""


def _body(response: requests.Response) -> str:
    return response.text if response.status_code == 200 else ""


def _create_key(session: requests.Session, username: str, password: str) -> str:
    login_page = _body(session.get(f"{SITE_URL}/login/"))
    token = extract_field(login_page, "csrf_token")
    if not token:
        logger.debug("The login page carried no CSRF token.")
        return ""

    signed_in = _body(
        session.post(
            f"{SITE_URL}/login/",
            data={
                "username": username,
                "password": password,
                "action": "Login",
                "u": "",
                "csrf_token": token,
            },
        )
    )
    if username.lower() not in signed_in.lower():
        logger.debug("The stored login was refused.")
        return ""

    # This page hands out its own pair of tokens. The login page's token is
    # spent and will not do.
    keys_page = _body(session.get(f"{SITE_URL}/account/apikeys/"))
    keys_token = extract_field(keys_page, "csrf_token")
    if not keys_token:
        logger.debug("The API keys page carried no CSRF token.")
        return ""

    created = _body(
        session.post(
            f"{SITE_URL}/account/apikeys/",
            data={
                "csrf_token": keys_token,
                "csrf": extract_field(keys_page, "csrf"),
                "do": "create",
                "name": KEY_NAME,
                "scopes": KEY_SCOPES,
            },
        )
    )
    return extract_key(created)
