import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from note_cover import render_background, upsert_background, upsert_cover_image, yaml_value


class NoteTests(unittest.TestCase):
    def test_yaml_arrays(self):
        self.assertEqual(yaml_value(["剧情", "爱情"]), '["剧情", "爱情"]')
        self.assertEqual(yaml_value(["a", 'b:c']), '["a", "b:c"]')

    def test_background_is_idempotent(self):
        block = render_background(
            "film",
            {
                "description": "一个背景。",
                "director": "Wong Kar-Wai",
                "cast": ["Tony Leung"],
                "release_date": "2000-05-20",
                "source_url": "https://neodb.social/movie/x",
            },
        )
        note = "# 花样年华\n\n我的感受。\n"
        once = upsert_background(note, block)
        twice = upsert_background(once, block)
        self.assertIn("我的感受。", twice)
        self.assertEqual(twice.count("<!-- gencover:begin -->"), 1)
        self.assertEqual(twice.count("## 背景"), 1)
        self.assertIn("- 导演：Wong Kar-Wai", twice)
        self.assertIn("一个背景。", twice)

    def test_cover_image_is_idempotent(self):
        note = "我的感受。\n"
        once = upsert_cover_image(note, "image/x/cover.webp")
        twice = upsert_cover_image(once, "image/x/cover.webp")
        self.assertTrue(once.startswith("<!-- gencover:cover:begin -->"))
        self.assertIn("我的感受。", twice)
        self.assertEqual(twice.count("![cover](image/x/cover.webp)"), 1)

    def test_cover_image_replaces_path(self):
        note = upsert_cover_image("正文\n", "image/old/cover.webp")
        changed = upsert_cover_image(note, "image/new/cover.webp")
        self.assertIn("image/new/cover.webp", changed)
        self.assertNotIn("image/old/cover.webp", changed)

    def test_book_heading(self):
        block = render_background("book", {"description": "简介", "author": ["兰小欢"]})
        self.assertIn("## 内容简介", block)
        self.assertIn("- 作者：兰小欢", block)


if __name__ == "__main__":
    unittest.main()
