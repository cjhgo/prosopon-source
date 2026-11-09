"""Title / creator / year matching for cover search results.

Pure functions only: no network, no IO. This is the part that decides whether
an automatically fetched cover is actually the right edition/album/film.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")

# Editions / formats that usually mean "this is not the edition I want".
EDITION_WORDS = (
    "高中", "初中", "小学", "青少年", "青少", "少儿", "学生版", "注音", "插图",
    "彩图", "缩写", "导读", "名著", "新课标", "教材", "教辅", "同步", "套装",
    "全集", "文集", "修订版", "第2版", "第二版", "第三版", "纪念版", "特别版",
    "导演剪辑", "未删减", "加长版", "4K", "蓝光", "重制", "修复", "特别收藏",
    "legacy", "deluxe", "remaster", "anniversary", "expanded",
)

STRONG_EDITION_WORDS = ("高中", "初中", "小学", "青少年", "青少", "少儿", "注音", "教材", "教辅", "同步")


def norm(text: str | None) -> str:
    """Normalise a title/creator for comparison.

    Keeps CJK and alphanumerics, drops punctuation, parenthesised year/asides,
    and lowercases Latin text. Traditional vs simplified is intentionally not
    converted: SequenceMatcher still gives partial credit, and conversion would
    add a heavy dependency.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).lower()
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", s)
    s = re.sub(r"[^\w㐀-鿿]+", "", s)
    return s


def years(text: str | None) -> list[str]:
    if not text:
        return []
    return YEAR_RE.findall(str(text))


def edition_penalty(title: str | None) -> float:
    t = str(title or "").lower()
    if any(w.lower() in t for w in STRONG_EDITION_WORDS):
        return 0.26
    if any(w.lower() in t for w in EDITION_WORDS):
        return 0.16
    return 0.0


def query_titles(item: dict) -> list[str]:
    """Original title plus optional English/alt titles (both used for matching)."""
    values = [item.get("title"), item.get("alt"), item.get("wiki")]
    out = []
    for value in values:
        n = norm(value)
        if n and n not in out:
            out.append(n)
    return out


def score_candidate(item: dict, cand: dict) -> float:
    """Return 0..1 confidence that `cand` is the requested work.

    Weights differ by medium:
      - film: title + year dominate; Douban's film abstract has no director.
      - music: title + artist dominate.
      - book: title + author dominate, with edition penalty.
    """
    typ = item.get("type", "book")
    q_titles = query_titles(item)
    c_titles = [norm(cand.get("title"))]
    for alt in cand.get("alt_titles") or []:
        n = norm(alt)
        if n and n not in c_titles:
            c_titles.append(n)
    c_titles = [c for c in c_titles if c]
    if not q_titles or not c_titles:
        return 0.0

    title_sim = max(SequenceMatcher(None, q, c).ratio() for q in q_titles for c in c_titles)
    contains = 1.0 if any(q in c or c in q for q in q_titles for c in c_titles) else 0.0
    exact = any(q == c for q in q_titles for c in c_titles)

    q_creator = norm(item.get("creator"))
    blob = norm(
        " ".join(
            str(cand.get(k, ""))
            for k in ("creator", "raw", "title")
        )
    )
    creator_match = 1.0 if q_creator and q_creator in blob else 0.0

    cand_years = set(years(cand.get("year")) + years(cand.get("title")) + years(cand.get("raw")))
    year_match = 1.0 if item.get("year") and str(item["year"]) in cand_years else 0.0

    penalty = edition_penalty(cand.get("title"))

    if typ == "film":
        weights = (0.78, 0.00, 0.12, 0.10)
    elif typ == "music":
        weights = (0.55, 0.30, 0.05, 0.10)
    else:
        weights = (0.55, 0.30, 0.08, 0.07)

    # A query title contained in the candidate title (e.g. with a subtitle,
    # translated title, or year) is a strong signal; don't let SequenceMatcher
    # dilute it.
    title_component = (0.92 + 0.08 * title_sim) if contains else title_sim

    conf = (
        weights[0] * title_component
        + weights[1] * creator_match
        + weights[2] * year_match
        + weights[3] * contains
    )

    # A clean exact-title hit is essentially decisive, except for books where
    # an unknown author still warrants a look.
    if exact:
        if typ == "film" or creator_match:
            conf = max(conf, 0.97)
        else:
            conf = max(conf, 0.86)
    elif contains and typ == "film" and not year_match:
        # English alt title matched but year is absent in the catalog entry.
        conf = max(conf, 0.88)

    conf -= penalty
    return round(min(1.0, max(0.0, conf)), 3)


def rank_candidates(item: dict, candidates: list[dict]) -> list[dict]:
    """Score, annotate, and sort candidates. Returns new dicts."""
    ranked = []
    for cand in candidates:
        conf = score_candidate(item, cand)
        entry = dict(cand)
        entry["confidence"] = conf
        entry["edition_penalty"] = edition_penalty(cand.get("title"))
        ranked.append(entry)
    ranked.sort(key=lambda c: c["confidence"], reverse=True)
    return ranked


def decide(item: dict, ranked: list[dict], min_confidence: float = 0.80) -> tuple[str, dict | None, list[str]]:
    """Return (status, chosen_candidate, notes).

    status: matched | review | miss
    """
    if not ranked:
        return "miss", None, ["no candidates"]

    best = ranked[0]
    notes: list[str] = []
    if best["confidence"] < min_confidence:
        notes.append(f"confidence {best['confidence']} < {min_confidence}")
    if best.get("edition_penalty", 0) > 0:
        notes.append(f"edition penalty {best['edition_penalty']}")
    if len(ranked) > 1 and best["confidence"] - ranked[1]["confidence"] < 0.05:
        a = norm(best.get("title"))
        b = norm(ranked[1].get("title"))
        same_work = bool(a and b and (a in b or b in a))
        best_exact = any(norm(best.get("title")) == q for q in query_titles(item))
        if not same_work and not best_exact:
            notes.append(
                f"ambiguous: runner-up {ranked[1].get('title')} at {ranked[1]['confidence']}"
            )

    if notes:
        return "review", best, notes
    return "matched", best, notes
