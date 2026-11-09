"""Cover search adapters.

Each adapter returns a list of normalised candidates:

    {
      "source": "douban" | "itunes" | "openlibrary" | "wikipedia" | "tmdb",
      "id": "...",
      "title": "...",
      "creator": "...",       # author / artist / director when available
      "year": "2000",
      "cover": "https://...", # remote image URL
      "referer": "https://...",  # required by some image CDNs
      "raw": "...",           # abstract / description, used by the matcher
      "url": "https://..."    # human-facing source page
    }

No downloads happen here; coverfetch.py owns caching, rate limiting and IO.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) prosopon-coverfetch/0.1"
def _opener(proxy: str | None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def get_json(url: str, proxy: str | None = None, timeout: int = 25) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
    )
    with _opener(proxy).open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _first_year(*values: str | None) -> str:
    import re

    for value in values:
        if not value:
            continue
        m = re.search(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", str(value))
        if m:
            return m.group(1)
    return ""


def itunes_search(item: dict, limit: int = 5, timeout: int = 25) -> list[dict]:
    """iTunes Search API — free, no key, best for international albums."""
    country = item.get("country") or ("CN" if item["type"] == "music" and _is_cjk(item.get("title", "")) else "US")
    term = urllib.parse.quote(" ".join(x for x in (item.get("title", ""), item.get("creator", "")) if x))
    url = f"https://itunes.apple.com/search?term={term}&entity=album&limit={limit}&country={country}"
    try:
        data = get_json(url, timeout=timeout)
    except Exception:
        return []
    result = []
    for row in data.get("results") or []:
        art = str(row.get("artworkUrl100", ""))
        cover = art.replace("100x100bb", "600x600bb") if art else ""
        result.append(
            {
                "source": "itunes",
                "id": str(row.get("collectionId", "")),
                "title": str(row.get("collectionName", "")),
                "creator": str(row.get("artistName", "")),
                "year": str(row.get("releaseDate", ""))[:4],
                "cover": cover,
                "referer": "",
                "raw": " ".join(
                    str(row.get(k, ""))
                    for k in ("artistName", "collectionName", "primaryGenreName", "releaseDate")
                ),
                "url": str(row.get("collectionViewUrl", "")),
            }
        )
    return result


def _is_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text or "")


def openlibrary_search(item: dict, limit: int = 5, timeout: int = 25, proxy: str | None = None) -> list[dict]:
    title = urllib.parse.quote(item.get("title", ""))
    author = urllib.parse.quote(item.get("creator", ""))
    url = f"https://openlibrary.org/search.json?title={title}&author={author}&limit={limit}"
    try:
        data = get_json(url, proxy=proxy, timeout=timeout)
    except Exception:
        return []
    result = []
    for doc in data.get("docs") or []:
        cover_id = doc.get("cover_i")
        cover = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else ""
        authors = doc.get("author_name") or []
        result.append(
            {
                "source": "openlibrary",
                "id": str(doc.get("key", "")),
                "title": str(doc.get("title", "")),
                "creator": " / ".join(str(a) for a in authors[:2]),
                "year": str(doc.get("first_publish_year", "")),
                "cover": cover,
                "referer": "",
                "raw": " ".join(
                    str(x)
                    for x in (
                        doc.get("subtitle", ""),
                        " ".join(str(a) for a in authors),
                        doc.get("first_publish_year", ""),
                    )
                ),
                "url": "https://openlibrary.org" + str(doc.get("key", "")),
            }
        )
    return result


def wikipedia_search(item: dict, timeout: int = 25, proxy: str | None = None) -> list[dict]:
    """Wikipedia REST summary. Requires an English page slug in item["wiki"]/["alt"]."""
    page = item.get("wiki") or item.get("alt")
    if not page:
        return []
    slug = urllib.parse.quote(str(page).replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    try:
        data = get_json(url, proxy=proxy, timeout=timeout)
    except Exception:
        return []
    thumb = (data.get("thumbnail") or {}).get("source") or (data.get("originalimage") or {}).get("source")
    if not thumb:
        return []
    description = str(data.get("description", ""))
    return [
        {
            "source": "wikipedia",
            "id": str(data.get("pageid", "")),
            "title": str(data.get("title", page)),
            "creator": "",
            "year": _first_year(description, data.get("extract", "")),
            "cover": str(thumb),
            "referer": "https://en.wikipedia.org/",
            "raw": description + " " + str(data.get("extract", ""))[:400],
            "url": str(data.get("content_urls", {}).get("desktop", {}).get("page", "")),
        }
    ]


def tmdb_search(item: dict, api_key: str, timeout: int = 25, proxy: str | None = None) -> list[dict]:
    if not api_key or item.get("type") != "film":
        return []
    query = urllib.parse.quote(item.get("title", ""))
    year = item.get("year", "")
    url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={query}"
    if year:
        url += f"&year={year}"
    try:
        data = get_json(url, proxy=proxy, timeout=timeout)
    except Exception:
        return []
    result = []
    for row in data.get("results") or []:
        poster = row.get("poster_path")
        result.append(
            {
                "source": "tmdb",
                "id": str(row.get("id", "")),
                "title": str(row.get("title", "")),
                "creator": "",
                "year": str(row.get("release_date", ""))[:4],
                "cover": f"https://image.tmdb.org/t/p/w500{poster}" if poster else "",
                "referer": "https://www.themoviedb.org/",
                "raw": str(row.get("overview", "")),
                "url": f"https://www.themoviedb.org/movie/{row.get('id', '')}",
            }
        )
    return result



NEODB_CAT = {"book": "book", "film": "movie", "music": "music"}


def neodb_search(item: dict, query: str | None = None, limit: int = 8, timeout: int = 30, proxy: str | None = None) -> list[dict]:
    """NeoDB catalog search (federated Douban-like database, includes covers)."""
    q = query or " ".join(x for x in (item.get("title", ""), item.get("creator", "")) if x).strip()
    cat = NEODB_CAT.get(item.get("type", "book"), "book")
    url = f"https://neodb.social/api/catalog/search?query={urllib.parse.quote(q)}&category={cat}"
    try:
        data = get_json(url, proxy=proxy, timeout=timeout)
    except Exception:
        return []
    rows = data.get("data") or []
    result = []
    for row in rows[:limit]:
        credits = row.get("credits") or []
        names = [str(c.get("name", "")) for c in credits if c.get("name")]
        creator = " / ".join(names[:2])
        year = str(row.get("pub_year") or row.get("pub_month") or "")
        title = str(row.get("display_title") or row.get("title") or "")
        if not title:
            continue
        alt_titles = []
        for loc in row.get("localized_title") or []:
            text = str(loc.get("text", "")).strip()
            if text and text not in alt_titles:
                alt_titles.append(text)
        orig = str(row.get("orig_title") or "").strip()
        if orig and orig not in alt_titles:
            alt_titles.append(orig)
        result.append(
            {
                "source": "neodb",
                "id": str(row.get("uuid", "")),
                "title": title,
                "alt_titles": alt_titles,
                "creator": creator,
                "year": year,
                "cover": str(row.get("cover_image_url", "")),
                "referer": "https://neodb.social/",
                "raw": " ".join(
                    [str(row.get("description", ""))[:300], " ".join(names), year, " ".join(alt_titles)]
                ),
                "url": "https://neodb.social" + str(row.get("url", "")),
                "api_url": str(row.get("api_url", "")),
            }
        )
    return result


def neodb_detail(cand: dict, typ: str, timeout: int = 30, proxy: str | None = None) -> dict:
    """Fetch the full NeoDB record for a search candidate."""
    api = cand.get("api_url") or ""
    if not api:
        cat = {"book": "book", "film": "movie", "music": "album"}.get(typ, "book")
        api = f"/api/{cat}/{cand.get('id','')}"
    url = api if api.startswith("http") else "https://neodb.social" + api
    return get_json(url, proxy=proxy, timeout=timeout)


def source_chain(item: dict, tmdb_key: str | None = None) -> list[str]:
    typ = item.get("type")
    if typ == "film":
        chain = ["neodb"]
        if tmdb_key:
            chain.append("tmdb")
        if item.get("wiki") or item.get("alt"):
            chain.append("wikipedia")
        return chain
    if typ == "music":
        return ["neodb", "itunes"]
    return ["neodb", "openlibrary"]


def search(source: str, item: dict, query: str | None = None, *, proxy: str | None = None, tmdb_key: str | None = None) -> list[dict]:
    if source == "neodb":
        return neodb_search(item, query=query, proxy=proxy)
    if source == "itunes":
        return itunes_search(item)
    if source == "openlibrary":
        return openlibrary_search(item, proxy=proxy)
    if source == "wikipedia":
        return wikipedia_search(item, proxy=proxy)
    if source == "tmdb":
        return tmdb_search(item, tmdb_key or os.environ.get("TMDB_API_KEY", ""), proxy=proxy)
    return []
