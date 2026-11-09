import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from match import decide, edition_penalty, norm, rank_candidates, score_candidate


class MatchTests(unittest.TestCase):
    def test_norm_strips_punctuation_and_year(self):
        self.assertEqual(norm("花样年华 花樣年華‎ (2000)"), "花样年华花樣年華")
        self.assertEqual(norm("2001: A Space Odyssey"), "2001aspaceodyssey")

    def test_book_subtitle_and_author(self):
        item = {"type": "book", "title": "置身事内", "creator": "兰小欢", "year": 2021}
        cand = {
            "title": "置身事内 : 中国政府与经济发展",
            "creator": "兰小欢",
            "year": "2021",
            "raw": "兰小欢 / 上海人民出版社 / 2021-8 / 65.00元",
        }
        self.assertGreaterEqual(score_candidate(item, cand), 0.90)

    def test_edition_is_penalised(self):
        item = {"type": "book", "title": "乡土中国", "creator": "费孝通"}
        cand = {
            "title": "乡土中国 : 费孝通社会学奠基之作 整本书阅读高中版",
            "creator": "费孝通",
            "raw": "费孝通 / 北京大学出版社 / 高中生推荐阅读",
        }
        self.assertGreater(edition_penalty(cand["title"]), 0)
        status, _, notes = decide(item, rank_candidates(item, [cand]), 0.8)
        self.assertEqual(status, "review")
        self.assertTrue(any("edition" in n for n in notes))

    def test_film_title_and_year_without_director(self):
        item = {"type": "film", "title": "花样年华", "creator": "王家卫", "year": 2000}
        cand = {
            "title": "花样年华 花樣年華‎ (2000)",
            "creator": "",
            "year": "2000",
            "raw": "中国香港 / 剧情 / 爱情 / 103分钟",
        }
        self.assertGreaterEqual(score_candidate(item, cand), 0.90)

    def test_wrong_title_is_low(self):
        item = {"type": "film", "title": "悲情城市", "creator": "侯孝贤", "year": 1989}
        cand = {
            "title": "侯孝贤画像 (1997)",
            "creator": "",
            "year": "1997",
            "raw": "法国 / 纪录片",
        }
        self.assertLess(score_candidate(item, cand), 0.6)

    def test_ambiguous_runner_up_is_review(self):
        item = {"type": "music", "title": "Kind of Blue", "creator": "Miles Davis"}
        a = {"title": "Kind of Blue", "creator": "Miles Davis", "raw": "Miles Davis / 1959"}
        b = {"title": "Kind of Blue (Legacy Edition)", "creator": "Miles Davis", "raw": "Miles Davis / 1997"}
        ranked = rank_candidates(item, [a, b])
        status, _, notes = decide(item, ranked, 0.8)
        # exact title + creator should win decisively; not ambiguous
        self.assertEqual(status, "matched")
        self.assertGreater(ranked[0]["confidence"], ranked[1]["confidence"])

    def test_miss_on_empty(self):
        item = {"type": "book", "title": "不存在", "creator": "无"}
        status, best, notes = decide(item, [], 0.8)
        self.assertEqual(status, "miss")
        self.assertIsNone(best)
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
