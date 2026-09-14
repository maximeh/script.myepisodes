"""Tests for the one-shot credentials-to-API-key migration.

Every test here is offline. The website is replaced by a fake session that
serves canned pages and records what was asked of it, so the whole login and
key-minting flow is exercised without a network, an account or a password.

The page fragments below are shaped like the real ones: the apikeys form
carries BOTH a `csrf_token` and a shorter `csrf`, and the page shown after a
key is created prints a truncated prefix of the key next to the full key.
Those two traps are what most of the parsing tests are about.
"""

import os
import tempfile
import unittest
from typing import Dict, List, NamedTuple, Optional, Sequence, Union, cast

import requests

from resources.lib import migrate

USERNAME = "BobTheUser"
PASSWORD = "s3cret pass&word"

# The login page and the apikeys page each carry their own csrf_token, and the
# two values differ. The apikeys POST must use the apikeys one.
LOGIN_TOKEN = "1b0d6f7c5c9f4f2a8e3d1c0b9a8f7e6d5c4b3a29180716253443526170f8e9d0c"
APIKEYS_TOKEN = "f8c997c55cb71198ec304bd1e77a4b4f39dc6df440d864cfdecb2c3178f485a8"
APIKEYS_CSRF = "35189a5c30d1d5323604c3569b43c92f"

LOGIN_PAGE = (
    '<form method="post" action="/login/">\n'
    '    <input type="hidden" name="csrf_token" value="' + LOGIN_TOKEN + '">\n'
    '    <input type="hidden" name="u" value="">\n'
    '    <input type="text" name="username" size="20">\n'
    '    <input type="password" name="password" size="20">\n'
    '    <input type="submit" name="action" value="Login">\n'
    "</form>\n"
)

LOGGED_IN_PAGE = (
    '<div id="header"><a href="/profile/">bobtheuser</a>'
    ' &middot; <a href="/logout/">Logout</a></div>\n'
)

LOGIN_FAILED_PAGE = (
    '<div class="error">Wrong username or password.</div>\n' + LOGIN_PAGE
)

# The fragment the task supplied, copied from the real page.
APIKEYS_PAGE = (
    '<form method="post" class="create">'
    '<input type="hidden" name="csrf_token" value="' + APIKEYS_TOKEN + '">\n'
    '    <input type="hidden" name="csrf" value="' + APIKEYS_CSRF + '">\n'
    '    <input type="hidden" name="do"   value="create">\n'
    '    <input type="text" name="name" maxlength="60" size="34" required>\n'
    '    <input type="radio" name="scopes" value="read" checked>\n'
    '    <input type="submit" value="Create key">\n'
    "</form>\n"
)

FULL_KEY = "myeps_ExampleKey-0123456789_abcdefghijklmnopqrs"
TRUNCATED_KEY = "myeps_ExampleKey"

# The key list shows the prefix first; the full key is only printed once, in
# the "copy it now" banner underneath.
CREATED_PAGE = (
    '<table class="keys"><tr><td>Kodi (script.myepisodes)</td>'
    "<td><code>" + TRUNCATED_KEY + "</code></td><td>read,write</td></tr></table>\n"
    '<div class="alert">Copy this key now, it is not shown again:'
    "<code>" + FULL_KEY + "</code></div>\n"
)

EXPECTED_KEY_NAME = "Kodi (script.myepisodes)"
EXPECTED_SCOPES = "read,write"


class Call(NamedTuple):
    """One request the code under test made."""

    method: str
    url: str
    data: Dict[str, str]


class FakeResponse:
    """Stands in for requests.Response, with only what the flow can need."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


Canned = Union[FakeResponse, Exception]


class FakeSession:
    """Serves canned responses in order and records every call.

    An Exception in the queue is raised instead of returned, which is how the
    network-failure cases are set up.
    """

    def __init__(self, responses: Sequence[Canned]) -> None:
        self.queue: List[Canned] = list(responses)
        self.calls: List[Call] = []

    @property
    def urls(self) -> List[str]:
        return [call.url for call in self.calls]

    def _answer(
        self, method: str, url: str, data: Optional[Dict[str, str]]
    ) -> FakeResponse:
        self.calls.append(Call(method, url, dict(data or {})))
        if not self.queue:
            raise AssertionError(
                "unexpected %s %s: nothing left to serve" % (method, url)
            )
        canned = self.queue.pop(0)
        if isinstance(canned, Exception):
            raise canned
        return canned

    def get(
        self, url: str, data: Optional[Dict[str, str]] = None, **kwargs: object
    ) -> FakeResponse:
        return self._answer("GET", url, data)

    def post(
        self, url: str, data: Optional[Dict[str, str]] = None, **kwargs: object
    ) -> FakeResponse:
        return self._answer("POST", url, data)


def happy_pages() -> List[Canned]:
    """The four responses of a successful migration, in the order they come."""
    return [
        FakeResponse(LOGIN_PAGE),
        FakeResponse(LOGGED_IN_PAGE),
        FakeResponse(APIKEYS_PAGE),
        FakeResponse(CREATED_PAGE),
    ]


def mint(session: FakeSession) -> str:
    return migrate.mint_api_key(USERNAME, PASSWORD, cast(requests.Session, session))


class TestStoredCredentials(unittest.TestCase):
    """Reads the settings.xml Kodi wrote for the old add-on."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = holder.name

    def write(self, xml: str) -> str:
        path = os.path.join(self.folder, "settings.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(xml)
        return path

    def test_value_attributes(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="Username" value="bob" />'
            '<setting id="Password" value="hunter2" />'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("bob", "hunter2"))

    def test_element_text(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="Username">bob</setting>'
            '<setting id="Password">hunter2</setting>'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("bob", "hunter2"))

    def test_one_of_each_form(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="Username" value="bob" />'
            '<setting id="Password">hunter2</setting>'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("bob", "hunter2"))

    def test_ignores_other_settings(self) -> None:
        path = self.write(
            '<settings version="2">'
            '<setting id="notify" value="true" />'
            '<setting id="Username" value="bob" />'
            '<setting id="delay" value="30" />'
            '<setting id="Password" value="hunter2" />'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("bob", "hunter2"))

    def test_strips_surrounding_whitespace(self) -> None:
        path = self.write(
            "<settings>\n"
            '    <setting id="Username" value="  bob  " />\n'
            '    <setting id="Password">\n        hunter2\n    </setting>\n'
            "</settings>\n"
        )
        self.assertEqual(migrate.stored_credentials(path), ("bob", "hunter2"))

    def test_missing_username_keeps_the_password(self) -> None:
        path = self.write(
            '<settings><setting id="Password" value="hunter2" /></settings>'
        )
        self.assertEqual(migrate.stored_credentials(path), ("", "hunter2"))

    def test_missing_password_keeps_the_username(self) -> None:
        path = self.write('<settings><setting id="Username" value="bob" /></settings>')
        self.assertEqual(migrate.stored_credentials(path), ("bob", ""))

    def test_empty_value(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="Username" value="" />'
            '<setting id="Password" value="" />'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("", ""))

    def test_setting_with_no_text_and_no_value(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="Username" />'
            '<setting id="Password" value="hunter2" />'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("", "hunter2"))

    def test_ids_are_case_sensitive(self) -> None:
        path = self.write(
            "<settings>"
            '<setting id="username" value="bob" />'
            '<setting id="PASSWORD" value="hunter2" />'
            "</settings>"
        )
        self.assertEqual(migrate.stored_credentials(path), ("", ""))

    def test_missing_file(self) -> None:
        path = os.path.join(self.folder, "there-is-no-such-file.xml")
        self.assertEqual(migrate.stored_credentials(path), ("", ""))

    def test_empty_path(self) -> None:
        self.assertEqual(migrate.stored_credentials(""), ("", ""))

    def test_malformed_xml(self) -> None:
        path = self.write('<settings><setting id="Username" value="bob">')
        self.assertEqual(migrate.stored_credentials(path), ("", ""))

    def test_file_that_is_not_xml_at_all(self) -> None:
        path = self.write("username=bob\npassword=hunter2\n")
        self.assertEqual(migrate.stored_credentials(path), ("", ""))

    def test_empty_file(self) -> None:
        path = self.write("")
        self.assertEqual(migrate.stored_credentials(path), ("", ""))


class TestExtractField(unittest.TestCase):
    def test_value_after_name(self) -> None:
        html = '<input type="hidden" name="csrf_token" value="abc123">'
        self.assertEqual(migrate.extract_field(html, "csrf_token"), "abc123")

    def test_value_before_name(self) -> None:
        html = '<input type="hidden" value="abc123" name="csrf_token">'
        self.assertEqual(migrate.extract_field(html, "csrf_token"), "abc123")

    def test_extra_whitespace_between_attributes(self) -> None:
        self.assertEqual(migrate.extract_field(APIKEYS_PAGE, "do"), "create")

    def test_absent_field(self) -> None:
        self.assertEqual(migrate.extract_field(LOGIN_PAGE, "csrf"), "")

    def test_empty_html(self) -> None:
        self.assertEqual(migrate.extract_field("", "csrf_token"), "")

    def test_first_of_several_matches(self) -> None:
        html = (
            '<input type="hidden" name="csrf_token" value="first">\n'
            '<input type="hidden" name="csrf_token" value="second">\n'
        )
        self.assertEqual(migrate.extract_field(html, "csrf_token"), "first")

    def test_csrf_is_not_csrf_token(self) -> None:
        # Both live on the apikeys page and posting one for the other fails.
        self.assertEqual(migrate.extract_field(APIKEYS_PAGE, "csrf"), APIKEYS_CSRF)

    def test_csrf_token_is_not_csrf(self) -> None:
        self.assertEqual(
            migrate.extract_field(APIKEYS_PAGE, "csrf_token"), APIKEYS_TOKEN
        )

    def test_csrf_wins_even_when_csrf_token_comes_first(self) -> None:
        # csrf_token is printed first on the real page, so a loose match finds
        # it while looking for csrf.
        self.assertNotEqual(migrate.extract_field(APIKEYS_PAGE, "csrf"), APIKEYS_TOKEN)

    def test_shorter_name_is_not_matched_by_a_longer_one(self) -> None:
        html = '<input type="hidden" name="csrf_token" value="longone">'
        self.assertEqual(migrate.extract_field(html, "csrf"), "")

    def test_empty_value(self) -> None:
        self.assertEqual(migrate.extract_field(LOGIN_PAGE, "u"), "")

    def test_input_with_no_value_does_not_borrow_the_next_input(self) -> None:
        # <input ... name="name" ... required> has no value attribute. The
        # radio right below it does, and it must not be handed over.
        self.assertEqual(migrate.extract_field(APIKEYS_PAGE, "name"), "")

    def test_reads_the_radio_value(self) -> None:
        self.assertEqual(migrate.extract_field(APIKEYS_PAGE, "scopes"), "read")


class TestExtractKey(unittest.TestCase):
    def test_returns_the_full_key_not_the_printed_prefix(self) -> None:
        self.assertEqual(migrate.extract_key(CREATED_PAGE), FULL_KEY)

    def test_order_on_the_page_does_not_matter(self) -> None:
        reversed_page = (
            "<code>" + FULL_KEY + "</code><code>" + TRUNCATED_KEY + "</code>"
        )
        self.assertEqual(migrate.extract_key(reversed_page), FULL_KEY)

    def test_key_on_its_own(self) -> None:
        self.assertEqual(migrate.extract_key(FULL_KEY), FULL_KEY)

    def test_no_key(self) -> None:
        self.assertEqual(migrate.extract_key(APIKEYS_PAGE), "")

    def test_empty_html(self) -> None:
        self.assertEqual(migrate.extract_key(""), "")


class TestMintApiKeyHappyPath(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession(happy_pages())
        self.key = mint(self.session)

    def test_returns_the_full_key(self) -> None:
        self.assertEqual(self.key, FULL_KEY)

    def test_makes_exactly_four_requests(self) -> None:
        self.assertEqual(len(self.session.calls), 4)

    def test_visits_the_login_page_then_the_apikeys_page(self) -> None:
        login = migrate.SITE_URL + "/login/"
        apikeys = migrate.SITE_URL + "/account/apikeys/"
        self.assertEqual(
            [(call.method, call.url) for call in self.session.calls],
            [
                ("GET", login),
                ("POST", login),
                ("GET", apikeys),
                ("POST", apikeys),
            ],
        )

    def test_login_post_sends_the_credentials(self) -> None:
        data = self.session.calls[1].data
        self.assertEqual(data.get("username"), USERNAME)
        self.assertEqual(data.get("password"), PASSWORD)

    def test_login_post_sends_the_action_and_the_empty_redirect(self) -> None:
        data = self.session.calls[1].data
        self.assertEqual(data.get("action"), "Login")
        self.assertEqual(data.get("u"), "")

    def test_login_post_sends_the_token_from_the_login_page(self) -> None:
        self.assertEqual(self.session.calls[1].data.get("csrf_token"), LOGIN_TOKEN)

    def test_apikeys_post_sends_the_token_from_the_apikeys_page(self) -> None:
        # Not the login page's token, which is still the one the session saw
        # most recently before this page.
        self.assertEqual(self.session.calls[3].data.get("csrf_token"), APIKEYS_TOKEN)

    def test_apikeys_post_sends_the_second_csrf_value(self) -> None:
        self.assertEqual(self.session.calls[3].data.get("csrf"), APIKEYS_CSRF)

    def test_apikeys_post_asks_to_create(self) -> None:
        self.assertEqual(self.session.calls[3].data.get("do"), "create")

    def test_apikeys_post_names_the_add_on(self) -> None:
        self.assertEqual(self.session.calls[3].data.get("name"), EXPECTED_KEY_NAME)

    def test_apikeys_post_asks_for_read_and_write(self) -> None:
        self.assertEqual(self.session.calls[3].data.get("scopes"), EXPECTED_SCOPES)

    def test_does_not_send_the_password_to_the_apikeys_page(self) -> None:
        self.assertNotIn(PASSWORD, self.session.calls[3].data.values())


class TestMintApiKeyLoginCheck(unittest.TestCase):
    def test_username_is_matched_case_insensitively(self) -> None:
        # The account page prints "bobtheuser"; the stored setting says
        # "BobTheUser". That is the same user.
        session = FakeSession(happy_pages())
        self.assertEqual(
            migrate.mint_api_key(
                "BOBTHEUSER", PASSWORD, cast(requests.Session, session)
            ),
            FULL_KEY,
        )

    def test_wrong_password_gives_no_key(self) -> None:
        pages = happy_pages()
        pages[1] = FakeResponse(LOGIN_FAILED_PAGE)
        session = FakeSession(pages)
        self.assertEqual(mint(session), "")

    def test_wrong_password_does_not_touch_the_apikeys_page(self) -> None:
        pages = happy_pages()
        pages[1] = FakeResponse(LOGIN_FAILED_PAGE)
        session = FakeSession(pages)
        mint(session)
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn(migrate.SITE_URL + "/account/apikeys/", session.urls)


class TestMintApiKeyFailures(unittest.TestCase):
    STEPS = ["GET login", "POST login", "GET apikeys", "POST apikeys"]

    def test_login_page_without_a_token(self) -> None:
        pages = happy_pages()
        pages[0] = FakeResponse("<html><body>Down for maintenance</body></html>")
        self.assertEqual(mint(FakeSession(pages)), "")

    def test_created_page_without_a_key(self) -> None:
        pages = happy_pages()
        pages[3] = FakeResponse('<div class="error">Key limit reached.</div>')
        self.assertEqual(mint(FakeSession(pages)), "")

    def test_any_step_answering_with_an_error_status(self) -> None:
        for index, step in enumerate(self.STEPS):
            with self.subTest(step=step):
                pages = happy_pages()
                served = pages[index]
                assert isinstance(served, FakeResponse)
                pages[index] = FakeResponse(served.text, 500)
                self.assertEqual(mint(FakeSession(pages)), "")

    def test_any_step_answering_with_a_redirect_status(self) -> None:
        # Anything other than 200 counts as a failure, including a 302 whose
        # body would otherwise parse.
        for index, step in enumerate(self.STEPS):
            with self.subTest(step=step):
                pages = happy_pages()
                served = pages[index]
                assert isinstance(served, FakeResponse)
                pages[index] = FakeResponse(served.text, 302)
                self.assertEqual(mint(FakeSession(pages)), "")

    def test_any_step_raising_a_request_exception(self) -> None:
        for index, step in enumerate(self.STEPS):
            with self.subTest(step=step):
                pages = happy_pages()
                pages[index] = requests.RequestException("boom")
                self.assertEqual(mint(FakeSession(pages)), "")

    def test_connection_error(self) -> None:
        pages = happy_pages()
        pages[0] = requests.ConnectionError("no route to host")
        self.assertEqual(mint(FakeSession(pages)), "")

    def test_timeout(self) -> None:
        pages = happy_pages()
        pages[2] = requests.Timeout("too slow")
        self.assertEqual(mint(FakeSession(pages)), "")

    def test_empty_credentials(self) -> None:
        # An empty username matches every page, so the login check cannot save
        # us here; the flow still has to end without inventing a key.
        session = FakeSession(
            [
                FakeResponse(LOGIN_PAGE),
                FakeResponse(LOGIN_FAILED_PAGE),
                FakeResponse(APIKEYS_PAGE),
                FakeResponse('<div class="error">Not logged in.</div>'),
            ]
        )
        self.assertEqual(
            migrate.mint_api_key("", "", cast(requests.Session, session)), ""
        )


if __name__ == "__main__":
    unittest.main()
