import unittest
import myepisodes

USERNAME = "test1337"
PASSWORD = "test1234"


class TestMyEpisodes(unittest.TestCase):
    mye = myepisodes.MyEpisodes(USERNAME, PASSWORD)

    def test_false_login(self) -> None:
        mye_wrong_login = myepisodes.MyEpisodes("aaaa", "bbbb")
        mye_wrong_login.login()
        self.assertFalse(mye_wrong_login.is_logged)

    def test_login(self) -> None:
        self.mye.login()
        self.assertTrue(self.mye.is_logged)

    def test_populate_shows(self) -> None:
        self.mye.populate_shows()
        results = {
            "scandal": 8603,
            "zbrodnia": 16034,
            "mr. robot": 15082,
            "mr robot": 15082,
        }
        self.assertDictEqual(self.mye.shows, results)

    def test_find_show_id(self) -> None:
        self.assertNotEqual(self.mye.shows, {})

        self.assertEqual(self.mye.find_show_id("South Park"), 7)
        self.assertEqual(self.mye.find_show_id("Doctor Who"), 114)
        self.assertEqual(self.mye.find_show_id("Scandal"), 8603)
        self.assertEqual(self.mye.find_show_id("Scandal Us"), 8603)
        self.assertEqual(self.mye.find_show_id("Mr Robot"), 15082)

    def test_add_show(self) -> None:
        self.mye.add_show(6585)
        self.assertTrue("pretty little liars" in list(self.mye.shows.keys()))
        self.assertEqual(self.mye.shows["pretty little liars"], 6585)

    def test_del_show(self) -> None:
        self.mye.del_show(6585)
        self.assertFalse("pretty little liars" in list(self.mye.shows.keys()))

    def test_set_episode_watched(self) -> None:
        ret = self.mye.set_episode_watched(15082, 1, 2)
        self.assertTrue(ret)
        ret = self.mye.set_episode_watched(8603, 7, 18)
        self.assertTrue(ret)

    def test_set_episode_unwatched(self) -> None:
        ret = self.mye.set_episode_unwatched(15082, 1, 2)
        self.assertTrue(ret)
        ret = self.mye.set_episode_unwatched(8603, 7, 18)
        self.assertTrue(ret)


if __name__ == "__main__":
    unittest.main()
