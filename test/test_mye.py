"""Tests for the MyEpisodes v1 JSON API client.

Two tiers:

* Offline tests need neither a key nor a network. They always run.
* Live tests run against the real API and are skipped unless the environment
  variable MYEPISODES_API_KEY holds a key. Never hard-code a key here.

NO TEST IN THIS FILE MUTATES THE ACCOUNT. Every live test only reads. The
key used for development belongs to a real account with real watched history,
and del_show destroys that history irreversibly, so add_show, del_show,
set_episode_watched and set_episode_unwatched are deliberately left uncovered
rather than exercised against real data.
"""

import os
import unittest
from typing import List

import requests

import myepisodes

API_KEY = os.environ.get("MYEPISODES_API_KEY", "")
NEEDS_KEY = "set MYEPISODES_API_KEY to run the live API tests"

# A key-shaped string that is not a key. Used offline only.
FAKE_KEY = "myeps_0000000000000000000000000000000000000000"

# The characters sanitize() rewrites.
PUNCTUATION = "[]_().-"

# Stable catalogue facts, checked against the live API:
#   * "Breaking Bad" is showid 3077 and is the only show with that exact name.
#     The literal search also returns "Breaking Bad: Original Minisodes"
#     (24668), so resolving the name means picking the exact match, not the
#     first row.
#   * Searching is literal: search="Mr Robot" finds nothing, while
#     search="Mr. Robot" finds 15082. A title recovered from a filename has
#     already lost the dot, so the catalogue alone cannot resolve it.
CATALOGUE_SHOW = "Breaking Bad"
CATALOGUE_SHOW_ID = 3077

NONSENSE_SHOW = "Zzzqqx Not A Real Show 91735"


class TestSanitize(unittest.TestCase):
    def test_replaces_every_punctuation_character(self) -> None:
        self.assertEqual(myepisodes.sanitize("a[b]c_d(e)f.g-h", ""), "abcdefgh")

    def test_replaces_with_the_given_string(self) -> None:
        self.assertEqual(myepisodes.sanitize("a.b", " "), "a b")
        self.assertEqual(myepisodes.sanitize("a.b", "-"), "a-b")

    def test_drops_the_dot_in_a_show_name(self) -> None:
        self.assertEqual(myepisodes.sanitize("Mr. Robot", ""), "Mr Robot")

    def test_drops_the_parentheses_in_a_show_name(self) -> None:
        self.assertEqual(myepisodes.sanitize("Top Gear (UK)", ""), "Top Gear UK")

    def test_leaves_other_punctuation_alone(self) -> None:
        # Commas, ampersands, apostrophes, colons and bangs are not rewritten.
        name = "Penn & Teller: Tell a Lie, Great Job! O'Neill"
        self.assertEqual(myepisodes.sanitize(name, ""), name)

    def test_leaves_letters_digits_and_spaces_alone(self) -> None:
        self.assertEqual(myepisodes.sanitize("South Park 7", ""), "South Park 7")

    def test_empty_string(self) -> None:
        self.assertEqual(myepisodes.sanitize("", "x"), "")


def canned(body: str, status: int = 200) -> requests.Response:
    """A Response carrying exactly what a server would have sent."""
    response = requests.Response()
    response.status_code = status
    response.url = "https://api.myepisodes.com/v1/me"
    response._content = body.encode("utf-8")
    return response


class TestPayloadOf(unittest.TestCase):
    """A 200 is not a promise of JSON. Captive portals and proxies send HTML."""

    def test_a_json_object_comes_back_whole(self) -> None:
        self.assertEqual(
            myepisodes.payload_of(canned('{"username": "bob"}')), {"username": "bob"}
        )

    def test_html_behind_a_200_is_refused(self) -> None:
        self.assertEqual(
            myepisodes.payload_of(canned("<html>Sign in to the wifi</html>")), {}
        )

    def test_an_empty_body_behind_a_200_is_refused(self) -> None:
        self.assertEqual(myepisodes.payload_of(canned("")), {})

    def test_a_json_array_is_refused(self) -> None:
        # The client always indexes the body, so a list is not usable.
        self.assertEqual(myepisodes.payload_of(canned("[1, 2, 3]")), {})

    def test_an_error_status_is_refused_even_with_good_json(self) -> None:
        self.assertEqual(myepisodes.payload_of(canned('{"code": "oops"}', 500)), {})

    def test_a_bad_body_does_not_raise(self) -> None:
        mye = myepisodes.MyEpisodes(FAKE_KEY)
        mye.req.mount("https://", _RefusingAdapter("<html>nope</html>"))
        mye.login()
        self.assertFalse(mye.is_logged)
        self.assertFalse(mye.populate_shows())


class _RefusingAdapter(requests.adapters.HTTPAdapter):
    """Answers every request with a 200 and a body that is not JSON."""

    def __init__(self, body: str) -> None:
        super().__init__()
        self.body = body

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        return canned(self.body)


class TestSpellings(unittest.TestCase):
    """spellings() is what lets a title taken from a filename find its show."""

    def test_an_unpunctuated_name_has_one_spelling(self) -> None:
        self.assertEqual(myepisodes.spellings("South Park"), {"south park"})

    def test_a_dotted_name_also_answers_to_the_flat_form(self) -> None:
        self.assertEqual(myepisodes.spellings("Mr. Robot"), {"mr. robot", "mr robot"})

    def test_an_initialism_answers_to_three_forms(self) -> None:
        self.assertEqual(
            myepisodes.spellings("S.W.A.T."),
            {"s.w.a.t.", "swat", "s w a t"},
        )

    def test_every_spelling_is_lowercased(self) -> None:
        for spelling in myepisodes.spellings("Mr. ROBOT"):
            self.assertEqual(spelling, spelling.lower())


class TestFromAccount(unittest.TestCase):
    """The cached account lookup, which runs before any request goes out."""

    def setUp(self) -> None:
        self.mye = myepisodes.MyEpisodes(FAKE_KEY)
        self.mye._remember(15082, "Mr. Robot")
        self.mye._remember(628, "South Park")

    def test_an_exact_name_resolves(self) -> None:
        self.assertEqual(self.mye._from_account("south park"), 628)

    def test_a_spelling_without_punctuation_resolves(self) -> None:
        self.assertEqual(self.mye._from_account("mr robot"), 15082)

    def test_a_partial_name_matching_one_show_resolves(self) -> None:
        # "robot" hits both spellings of the same show, which is still one show.
        self.assertEqual(self.mye._from_account("robot"), 15082)

    def test_a_partial_name_matching_two_shows_is_refused(self) -> None:
        self.mye._remember(1, "Robot Wars")
        self.assertEqual(self.mye._from_account("robot"), myepisodes.SHOW_ID_ERR)

    def test_an_unknown_name_is_refused(self) -> None:
        self.assertEqual(self.mye._from_account("no such show"), myepisodes.SHOW_ID_ERR)

    def test_an_empty_cache_is_refused(self) -> None:
        empty = myepisodes.MyEpisodes(FAKE_KEY)
        self.assertEqual(empty._from_account("south park"), myepisodes.SHOW_ID_ERR)


class TestGetInfo(unittest.TestCase):
    """get_info is pure: it parses a filename and touches no network.

    Titles are compared lowercased. find_show_id is documented
    case-insensitive, so the case get_info returns is not part of the
    contract; the punctuation, the trimming and the dropped extension are.
    """

    def setUp(self) -> None:
        self.mye = myepisodes.MyEpisodes(FAKE_KEY)

    def test_dotted_sxxexx(self) -> None:
        title, season, episode = self.mye.get_info("Mr.Robot.S01E02.mkv")
        self.assertEqual(title.lower(), "mr robot")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 2)

    def test_x_separated(self) -> None:
        title, season, episode = self.mye.get_info("foo.1x09.avi")
        self.assertEqual(title.lower(), "foo")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 9)

    def test_spelled_out_season_and_episode(self) -> None:
        title, season, episode = self.mye.get_info("Season 01 - Episode 02")
        self.assertEqual(title, "")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 2)

    def test_bracketed_and_underscored(self) -> None:
        title, season, episode = self.mye.get_info("foo_[s01]_[e01]")
        self.assertEqual(title.lower(), "foo")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 1)

    def test_compact_sxepxx(self) -> None:
        title, season, episode = self.mye.get_info("s1ep03")
        self.assertEqual(title, "")
        self.assertEqual(season, 1)
        self.assertEqual(episode, 3)

    def test_filename_with_no_episode_marker(self) -> None:
        # A filename with no digits at all cannot match any season/episode
        # pattern. A movie filename carrying a year is NOT tested here: the
        # inherited pattern list reads a bare three-digit run as season plus
        # episode, so "Some.Movie.2019.mkv" is a known false positive that is
        # out of scope for this release and must not be pinned by a test.
        self.assertEqual(
            self.mye.get_info("Some.Movie.mkv"),
            ("", myepisodes.SHOW_ID_ERR, myepisodes.SHOW_ID_ERR),
        )

    def test_empty_filename(self) -> None:
        self.assertEqual(
            self.mye.get_info(""),
            ("", myepisodes.SHOW_ID_ERR, myepisodes.SHOW_ID_ERR),
        )


class TestInitialState(unittest.TestCase):
    """Constructing the client talks to nobody and asserts nothing about the key."""

    def setUp(self) -> None:
        self.mye = myepisodes.MyEpisodes(FAKE_KEY)

    def test_not_logged_in_before_login(self) -> None:
        self.assertFalse(self.mye.is_logged)

    def test_username_is_empty_before_login(self) -> None:
        self.assertEqual(self.mye.username, "")

    def test_shows_is_empty_before_populate(self) -> None:
        self.assertEqual(self.mye.shows, {})

    def test_repr_does_not_leak_the_key(self) -> None:
        text = repr(self.mye)
        self.assertNotIn(FAKE_KEY, text)
        # Not the secret half on its own either.
        self.assertNotIn(FAKE_KEY.split("_", 1)[1], text)

    def test_repr_is_not_empty(self) -> None:
        self.assertIn("MyEpisodes", repr(self.mye))


class TestEmptyKeyLogin(unittest.TestCase):
    """The state every fresh install and every failed migration lands in."""

    def test_empty_key_does_not_raise_and_does_not_log_in(self) -> None:
        # No key means no request, so this needs neither an account nor a
        # network. It is the first branch an upgrading user hits.
        mye = myepisodes.MyEpisodes("")
        mye.login()
        self.assertFalse(mye.is_logged)
        self.assertEqual(mye.username, "")


@unittest.skipUnless(API_KEY, NEEDS_KEY)
class TestLiveLogin(unittest.TestCase):
    def test_bad_key_does_not_raise_and_does_not_log_in(self) -> None:
        mye = myepisodes.MyEpisodes("myeps_this_key_was_never_issued_0000000000")
        mye.login()
        self.assertFalse(mye.is_logged)
        self.assertEqual(mye.username, "")

    def test_real_key_logs_in_and_names_the_account(self) -> None:
        mye = myepisodes.MyEpisodes(API_KEY)
        mye.login()
        self.assertTrue(mye.is_logged)
        self.assertNotEqual(mye.username.strip(), "")


@unittest.skipUnless(API_KEY, NEEDS_KEY)
class TestLiveShows(unittest.TestCase):
    """Read-only checks against the live account. Nothing here writes."""

    mye: myepisodes.MyEpisodes
    populated: bool

    @classmethod
    def setUpClass(cls) -> None:
        cls.mye = myepisodes.MyEpisodes(API_KEY)
        cls.mye.login()
        cls.populated = cls.mye.populate_shows()

    def punctuated_keys(self) -> List[str]:
        """Account keys that sanitize() would rewrite."""
        return sorted(
            name for name in self.mye.shows if any(char in name for char in PUNCTUATION)
        )

    def test_populate_shows_reports_success(self) -> None:
        self.assertTrue(self.populated)

    def test_populate_shows_fills_the_dict(self) -> None:
        self.assertNotEqual(self.mye.shows, {})

    def test_every_key_is_lowercase_and_every_value_is_a_show_id(self) -> None:
        for name, show_id in self.mye.shows.items():
            self.assertEqual(name, name.lower(), name)
            self.assertIsInstance(show_id, int)
            self.assertGreater(show_id, 0, name)

    def test_punctuated_names_are_registered_twice(self) -> None:
        # "Mr. Robot" must give both "mr. robot" and "mr robot", mapped to the
        # same id, because a title recovered from a filename has lost the dot
        # and the catalogue search is literal.
        punctuated = self.punctuated_keys()
        if not punctuated:
            self.skipTest("no followed show has punctuation in its name")
        for name in punctuated:
            stripped = myepisodes.sanitize(name, "")
            self.assertIn(stripped, self.mye.shows, name)
            self.assertEqual(self.mye.shows[stripped], self.mye.shows[name], name)

    def test_find_show_id_resolves_names_from_the_account(self) -> None:
        # A handful, not all of them: if the lookup falls through to the
        # network, 40 of these in a row would trip the 10-per-second limit.
        for name in sorted(self.mye.shows)[:3]:
            self.assertEqual(self.mye.find_show_id(name), self.mye.shows[name], name)

    def test_find_show_id_ignores_case(self) -> None:
        name = sorted(self.mye.shows)[0]
        self.assertEqual(self.mye.find_show_id(name.upper()), self.mye.shows[name])
        self.assertEqual(self.mye.find_show_id(name.title()), self.mye.shows[name])

    def test_find_show_id_resolves_a_title_stripped_of_punctuation(self) -> None:
        # The hard case: the name as it comes out of a filename, with the
        # punctuation gone. The catalogue cannot answer this one.
        punctuated = self.punctuated_keys()
        if not punctuated:
            self.skipTest("no followed show has punctuation in its name")
        name = punctuated[0]
        stripped = myepisodes.sanitize(name, "")
        self.assertEqual(self.mye.find_show_id(stripped), self.mye.shows[name])

    def test_find_show_id_falls_through_to_the_catalogue(self) -> None:
        # Not followed, so it can only come from the public catalogue. The
        # literal search also returns "Breaking Bad: Original Minisodes", so
        # this fails if the first row is taken instead of the exact match.
        self.assertNotIn(CATALOGUE_SHOW.lower(), self.mye.shows)
        self.assertEqual(self.mye.find_show_id(CATALOGUE_SHOW), CATALOGUE_SHOW_ID)

    def test_catalogue_lookup_ignores_case(self) -> None:
        self.assertEqual(
            self.mye.find_show_id(CATALOGUE_SHOW.upper()), CATALOGUE_SHOW_ID
        )

    def test_find_show_id_rejects_an_unknown_name(self) -> None:
        self.assertEqual(self.mye.find_show_id(NONSENSE_SHOW), myepisodes.SHOW_ID_ERR)

    def test_find_show_id_rejects_an_empty_name(self) -> None:
        self.assertEqual(self.mye.find_show_id(""), myepisodes.SHOW_ID_ERR)


if __name__ == "__main__":
    unittest.main()
