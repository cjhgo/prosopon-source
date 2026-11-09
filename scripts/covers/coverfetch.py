#!/usr/bin/env python3
"""coverfetch — authoring-time cover pipeline for 三境居 / MOUSEION.

Standalone by design: it does not import or touch the Quartz engine. It reads an
items manifest, searches Douban/iTunes/Open Library/Wikipedia/TMDB, scores the
matches, downloads and resizes the chosen cover, and writes a manifest/report/
preview under `--out`.

Examples:
    python3 scripts/covers/coverfetch.py fetch --limit-per-type 6
    python3 scripts/covers/coverfetch.py fetch --types film --accept-review
    python3 scripts/covers/coverfetch.py report
    python3 scripts/covers/coverfetch.py preview

Outputs (default under scripts/covers/out/):
    cache.json          per-item cache (safe to delete; re-fetches)
    manifest.json       one row per item; the integration contract
    report.md/.html     human review sheet
    preview.html        2D cover wall preview
    raw/                downloaded originals
    covers/<type>/      resized WebP/JPEG covers
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import imageops
import sources
from match import decide, rank_candidates
from store import Cache, RateLimiter, key_for

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ITEMS = os.path.join(HERE, "items.json")
DEFAULT_OUT = os.path.join(HERE, "out")
RATE = {
    "neodb": 1.0,
    "itunes": 1.0,
    "openlibrary": 1.2,
    "wikipedia": 1.0,
    "tmdb": 0.5,
}
MAX_WIDTH = {"book": 480, "film": 480, "music": 600}


def slugify(text: str, used: set[str]) -> str:
    base = re.sub(r"[\\/:*?\"<>|\s]+", "-", str(text)).strip("-")[:60] or "cover"
    candidate = base
    i = 2
    while candidate in used:
        candidate = f"{base}-{i}"
        i += 1
    used.add(candidate)
    return candidate


def load_items(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("items", [])
    for item in data:
        if item.get("type") not in ("book", "film", "music"):
            raise ValueError(f"bad type for {item!r}")
        if not item.get("title"):
            raise ValueError(f"missing title for {item!r}")
    return data


def search_item(item: dict, limiter: RateLimiter, args) -> tuple[list[dict], list[str]]:
    """Search all sources in priority order; return ranked candidates + notes."""
    all_candidates: list[dict] = []
    notes: list[str] = []
    chain = sources.source_chain(item, args.tmdb_key)
    for source in chain:
        queries = [None]
        if source == "neodb":
            q1 = item.get("title", "")
            q2 = " ".join(x for x in (q1, item.get("creator", "")) if x).strip()
            queries = [q1] if q1 == q2 else [q1, q2]
        for query in queries:
            limiter.wait(source)
            try:
                found = sources.search(
                    source, item, query=query, proxy=args.proxy, tmdb_key=args.tmdb_key
                )
            except Exception as exc:  # network/opencli failure shouldn't kill the run
                notes.append(f"{source}: {type(exc).__name__}: {exc}")
                found = []
            if found:
                all_candidates.extend(found)
                break
        if all_candidates:
            ranked = rank_candidates(item, all_candidates)
            # A decisive hit from a higher-priority source is enough.
            status, best, _ = decide(item, ranked, args.min_confidence)
            if status == "matched":
                return ranked, notes
    return rank_candidates(item, all_candidates), notes


def fetch_one(item: dict, cache: Cache, limiter: RateLimiter, used_slugs: dict[str, set[str]], args) -> dict:
    key = key_for(item)
    cached = cache.get(key)
    if cached and not args.refresh:
        cover = cached.get("cover", "")
        if cover and os.path.exists(os.path.join(args.out, cover)):
            print(f"  cache  {item['type']:5} {item['title']} -> {cached.get('source_title')}")
            return cached

    print(f"  search {item['type']:5} {item['title']} ...", flush=True)
    ranked, notes = search_item(item, limiter, args)
    status, best, decision_notes = decide(item, ranked, args.min_confidence)
    notes.extend(decision_notes)

    entry = {
        "key": key,
        "type": item["type"],
        "title": item.get("title", ""),
        "creator": item.get("creator", ""),
        "year": item.get("year", ""),
        "status": status,
        "confidence": best.get("confidence") if best else 0,
        "source": best.get("source") if best else "",
        "source_id": best.get("id") if best else "",
        "source_title": best.get("title") if best else "",
        "source_creator": best.get("creator") if best else "",
        "source_url": best.get("url") if best else "",
        "cover_url": best.get("cover") if best else "",
        "raw": best.get("raw") if best else "",
        "notes": notes,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    should_download = best and best.get("cover") and (status == "matched" or args.accept_review)
    if should_download and not args.dry_run:
        slugs = used_slugs.setdefault(item["type"], set())
        slug = slugify(item.get("title", ""), slugs)
        raw_ext = ".raw"
        raw_path = os.path.join(args.out, "raw", f"{item['type']}-{slug}{raw_ext}")
        dest_base = os.path.join(args.out, "covers", item["type"], f"{slug}.webp")
        try:
            imageops.download(
                best["cover"], raw_path, referer=best.get("referer"), proxy=args.proxy
            )
            cover_path = imageops.to_webp(raw_path, dest_base, MAX_WIDTH[item["type"]])
            rel = os.path.relpath(cover_path, args.out)
            w, h = imageops.dimensions(cover_path)
            entry.update(
                {
                    "cover": rel,
                    "width": w,
                    "height": h,
                    "sha256": imageops.sha256(cover_path),
                }
            )
            entry["status"] = "matched" if status == "matched" else "review"
            if status == "review":
                entry["notes"] = notes + ["downloaded best candidate under --accept-review"]
            print(f"  saved  {item['type']:5} {item['title']} -> {rel} ({w}x{h})")
        except Exception as exc:
            entry["status"] = "review" if status == "review" else "miss"
            entry["notes"] = notes + [f"download failed: {type(exc).__name__}: {exc}"]
            print(f"  fail   {item['type']:5} {item['title']} -> {exc}")
    else:
        if status == "matched" and not args.dry_run:
            entry["status"] = "review"
            entry["notes"] = notes + ["matched but no downloadable cover"]
        print(f"  {entry['status']:6} {item['type']:5} {item['title']} ({entry['confidence']:.2f})")

    cache.set(key, entry)
    return entry


def fetch(args) -> list[dict]:
    items = load_items(args.items)
    if args.types:
        wanted = {t.strip() for t in args.types.split(",") if t.strip()}
        items = [i for i in items if i["type"] in wanted]
    if args.limit_per_type:
        counts: dict[str, int] = defaultdict(int)
        limited = []
        for item in items:
            if counts[item["type"]] >= args.limit_per_type:
                continue
            counts[item["type"]] += 1
            limited.append(item)
        items = limited

    os.makedirs(args.out, exist_ok=True)
    cache = Cache(os.path.join(args.out, "cache.json"))
    limiter = RateLimiter(RATE)
    used_slugs: dict[str, set[str]] = defaultdict(set)
    # Pre-seed used slugs from existing manifest so reruns don't collide.
    manifest_path = os.path.join(args.out, "manifest.json")
    existing = []
    if os.path.exists(manifest_path):
        try:
            existing = json.load(open(manifest_path, encoding="utf-8"))
        except Exception:
            existing = []
    for row in existing:
        cover = row.get("cover", "")
        if cover:
            used_slugs[row["type"]].add(os.path.splitext(os.path.basename(cover))[0])

    entries = []
    for idx, item in enumerate(items, 1):
        print(f"[{idx}/{len(items)}] {item['title']}", flush=True)
        try:
            entries.append(fetch_one(item, cache, limiter, used_slugs, args))
        except Exception as exc:
            print(f"  ERROR {item['title']}: {type(exc).__name__}: {exc}")
            entries.append(
                {
                    "key": key_for(item),
                    "type": item["type"],
                    "title": item.get("title", ""),
                    "creator": item.get("creator", ""),
                    "year": item.get("year", ""),
                    "status": "miss",
                    "confidence": 0,
                    "notes": [f"fatal: {type(exc).__name__}: {exc}"],
                }
            )

    # Merge with previous manifest rows not in this run (so repeated --limit runs accumulate).
    by_key = {row.get("key"): row for row in existing}
    for row in entries:
        by_key[row.get("key")] = row
    merged = sorted(by_key.values(), key=lambda r: (r.get("type", ""), r.get("title", "")))
    write_json(manifest_path, merged)
    write_report(args.out, merged)
    if not args.no_preview:
        write_preview(args.out, merged)
    return merged


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_report(out: str, rows: list[dict]) -> None:
    counts = Counter(r.get("status", "?") for r in rows)
    by_source = Counter(r.get("source", "") for r in rows if r.get("source"))
    lines = [
        "# cover fetch report",
        "",
        f"- total: {len(rows)}",
        f"- matched: {counts.get('matched', 0)}",
        f"- review: {counts.get('review', 0)}",
        f"- miss: {counts.get('miss', 0)}",
        f"- sources: {dict(by_source)}",
        "",
        "## needs review",
        "",
        "| type | title | confidence | candidate | notes |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("status") != "review":
            continue
        notes = "; ".join(r.get("notes") or [])[:160]
        lines.append(
            f"| {r.get('type')} | {r.get('title')} | {r.get('confidence')} | "
            f"{r.get('source_title','')} | {notes} |"
        )
    lines += ["", "## misses", "", "| type | title | notes |", "|---|---|---|"]
    for r in rows:
        if r.get("status") != "miss":
            continue
        lines.append(f"| {r.get('type')} | {r.get('title')} | {'; '.join(r.get('notes') or [])[:160]} |")
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # HTML contact sheet for visual review
    cards = []
    for r in rows:
        cover = r.get("cover")
        img = (
            f'<img src="{html.escape(cover)}" loading="lazy">'
            if cover
            else '<div class="ph">NO COVER</div>'
        )
        cls = r.get("status", "miss")
        cards.append(
            f'<figure class="{cls}">{img}<figcaption>'
            f'<b>{html.escape(r.get("title",""))}</b>'
            f'<span>{html.escape(r.get("source_title",""))}</span>'
            f'<em>{r.get("status")} · {r.get("confidence")} · {html.escape(r.get("source",""))}</em>'
            f'</figcaption></figure>'
        )
    doc = f"""<!doctype html><meta charset="utf-8"><title>cover review</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;background:#f3efe5;color:#1e2a2b;margin:0;padding:28px}}
h1{{font-family:Georgia,serif;font-weight:500;letter-spacing:.1em}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:16px}}
figure{{margin:0;background:#faf5ea;padding:8px;box-shadow:0 8px 20px -12px #0006;border-top:3px solid #ccc}}
figure.matched{{border-top-color:#2f8296}} figure.review{{border-top-color:#b3763a}} figure.miss{{border-top-color:#a33}}
img{{width:100%;height:190px;object-fit:contain;display:block;background:#e8e0d0}}
.ph{{height:190px;display:grid;place-items:center;background:#e8e0d0;color:#888;font-size:11px}}
figcaption{{display:flex;flex-direction:column;gap:2px;padding-top:6px;font-size:10px}}
figcaption span{{color:#777;font-size:9px}} figcaption em{{color:#999;font-size:8px;font-style:normal}}
</style><h1>COVER REVIEW</h1><p>{counts.get('matched',0)} matched · {counts.get('review',0)} review · {counts.get('miss',0)} miss</p>
<div class="grid">{''.join(cards)}</div>"""
    with open(os.path.join(out, "report.html"), "w", encoding="utf-8") as f:
        f.write(doc)


def write_preview(out: str, rows: list[dict]) -> None:
    """Generate a lightweight 2D cover wall preview from the manifest."""
    groups = {"book": [], "film": [], "music": []}
    for r in rows:
        groups.setdefault(r.get("type", "book"), []).append(r)

    def card(r):
        if r.get("cover"):
            return (
                f'<figure class="item"><div class="frame"><img src="{html.escape(r["cover"])}" '
                f'loading="lazy" alt="{html.escape(r.get("title",""))}">'
                f'<div class="cap"><span class="t">{html.escape(r.get("title",""))}</span>'
                f'<span class="a">{html.escape(r.get("creator",""))}</span></div></div></figure>'
            )
        return (
            f'<figure class="item"><div class="frame gen"><div class="gen-art"></div>'
            f'<div class="gen-cap"><span class="t">{html.escape(r.get("title",""))}</span>'
            f'<span class="a">{html.escape(r.get("creator",""))}</span></div></div></figure>'
        )

    sections = []
    for typ, label, num in (("book", "BOOKS", "I"), ("film", "FILMS", "II"), ("music", "MUSIC", "III")):
        items = groups.get(typ, [])
        if not items:
            continue
        sections.append(
            f'<section class="{typ}"><div class="head"><span>{num}</span><h2>{label}</h2>'
            f'<em>{len(items)} items</em></div><div class="ledge"><div class="items">'
            + "".join(card(r) for r in items)
            + '</div><div class="board"></div></div></section>'
        )
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mouseion preview</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500&family=Inter:wght@400;500&display=swap');
body{{margin:0;background:#f3efe5;color:#1e2a2b;font-family:Inter,sans-serif}}
.wrap{{max-width:1240px;margin:0 auto;padding:46px 30px 80px}}
.mast{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid #d3caba;padding-bottom:16px}}
h1{{font-family:"Cormorant Garamond",Georgia,serif;font-weight:500;font-size:54px;letter-spacing:.14em;margin:0}}
.kicker{{font-size:9px;letter-spacing:.2em;text-transform:uppercase;color:#72756a;margin-top:8px}}
.seal{{writing-mode:vertical-rl;font-family:"Songti SC",serif;font-size:13px;letter-spacing:.3em;color:#2f8296;border:1px solid #2f8296;padding:7px 4px}}
section{{padding:38px 0 24px;border-bottom:1px solid #d3caba}}
.head{{display:flex;align-items:baseline;gap:14px;margin-bottom:14px}}
.head span{{font-family:Georgia,serif;color:#b3763a;font-size:13px}}
.head h2{{font-family:"Cormorant Garamond",serif;font-weight:500;font-size:28px;letter-spacing:.16em;margin:0}}
.head em{{margin-left:auto;font-size:9px;letter-spacing:.14em;color:#72756a;font-style:normal;text-transform:uppercase}}
.ledge{{padding:26px 22px 0;background:radial-gradient(120% 100% at 50% 0%,#f2ecdf,#e5ddce 70%);border:1px solid #d6ccba;box-shadow:0 25px 50px -40px #0008}}
.items{{display:flex;align-items:flex-end;justify-content:center;gap:14px;flex-wrap:wrap}}
.item{{margin:0;transition:transform .16s}} .item:hover{{transform:translateY(-6px)}}
.frame{{display:flex;flex-direction:column;align-items:center;padding:6px 6px 4px;background:#faf5ea;box-shadow:0 12px 18px -12px #0008}}
.frame img{{height:170px;width:auto;max-width:210px;display:block}}
.cap{{display:flex;flex-direction:column;align-items:center;gap:1px;padding-top:4px;max-width:200px}}
.cap .t{{font-family:"Songti SC",serif;font-size:7.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}}
.cap .a{{font-size:6.2px;color:#777;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}}
.gen{{width:145px;height:185px;background:#b3763a;padding:8px;justify-content:space-between}}
.gen-art{{flex:1;border:1px solid #fff6;margin-bottom:26px;background:#ffffff22}}
.gen-cap{{display:flex;flex-direction:column;background:#faf5ea;padding:5px;margin:0 -2px -2px}}
.board{{height:12px;margin-top:0;background:linear-gradient(180deg,#9b704f,#5a3d2b 55%,#3f2a1e);box-shadow:0 10px 18px -8px #0008}}
.music .frame img{{height:140px}}
.foot{{display:flex;justify-content:space-between;border-top:1px solid #d3caba;margin-top:30px;padding-top:14px;font-size:8px;letter-spacing:.16em;text-transform:uppercase;color:#888}}
</style></head><body><div class="wrap">
<div class="mast"><div><h1>MOUSEION</h1><div class="kicker">A private collection of books, films &amp; records</div></div><div class="seal">三境居</div></div>
{''.join(sections)}
<div class="foot"><span>MOUSEION</span><span>Cover pipeline preview</span><span>books · films · music</span></div>
</div></body></html>"""
    with open(os.path.join(out, "preview.html"), "w", encoding="utf-8") as f:
        f.write(doc)


def cmd_report(args) -> None:
    path = os.path.join(args.out, "manifest.json")
    rows = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    write_report(args.out, rows)
    write_preview(args.out, rows)
    print(f"wrote {args.out}/report.md, report.html, preview.html")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Cover fetch pipeline for 三境居")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="search + download covers")
    f.add_argument("--items", default=DEFAULT_ITEMS)
    f.add_argument("--out", default=DEFAULT_OUT)
    f.add_argument("--types", default="", help="comma list: book,film,music")
    f.add_argument("--limit-per-type", type=int, default=0)
    f.add_argument("--min-confidence", type=float, default=0.80)
    f.add_argument("--accept-review", action="store_true", help="download best even when flagged review")
    f.add_argument("--refresh", action="store_true")
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--proxy", default=os.environ.get("FETCH_PROXY", ""),
                   help="HTTP proxy for OpenLibrary/Wikipedia/TMDB (Douban/iTunes direct)")
    f.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""))
    f.add_argument("--no-preview", action="store_true")
    f.set_defaults(func=fetch)

    r = sub.add_parser("report", help="regenerate report + preview from manifest")
    r.add_argument("--out", default=DEFAULT_OUT)
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
