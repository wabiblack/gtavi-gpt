"""GTA VI YouTube trend radar (best-effort public metadata, no API key)."""
import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ytdlp_json

UPLOAD_DATE_SORT = "&sp=CAI%253D"


def video_url(item):
    raw = str(item.get("webpage_url") or item.get("url") or item.get("id") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={raw}"
    if raw.startswith("/watch"):
        return "https://www.youtube.com" + raw
    if (raw.startswith("https://") and "youtube.com" in raw) or raw.startswith("https://youtu.be/"):
        return raw
    return ""


def safe_detail(url):
    try:
        return ytdlp_json(url, ["--skip-download"])
    except (SystemExit, Exception):
        return None


def search(query, limit):
    errors = []
    methods = [
        ("recent YouTube search", f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}{UPLOAD_DATE_SORT}", ["--flat-playlist", "--playlist-end", str(limit)]),
        ("ytsearchdate fallback", f"ytsearchdate{limit}:{query}", ["--flat-playlist"]),
    ]
    for name, url, options in methods:
        try:
            data = ytdlp_json(url, options)
            entries = [e for e in (data.get("entries") or []) if isinstance(e, dict) and video_url(e) and "/shorts/" not in video_url(e)]
            if entries:
                return entries, name, errors
            errors.append(f"{name} returned no eligible results")
        except (SystemExit, Exception) as exc:
            errors.append(f"{name} failed: {str(exc)[:240]}")
    return [], "both methods unsuccessful", errors


def published_at(item):
    timestamp = item.get("timestamp") or item.get("release_timestamp")
    if timestamp:
        return float(timestamp), "exact"
    upload_date = item.get("upload_date")
    if upload_date:
        try:
            dt = datetime.strptime(str(upload_date), "%Y%m%d").replace(tzinfo=timezone.utc)
            return dt.timestamp(), "date only"
        except ValueError:
            pass
    return None, "unknown"


def safe_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="gta 6")
    ap.add_argument("--hours", type=float, default=168)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--out", default="trends.md")
    args = ap.parse_args()
    entries, method, errors = search(args.query, args.limit)
    urls = [video_url(e) for e in entries]
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(safe_detail, urls))
    rows, unverified = [], []
    stale, fetched = 0, sum(item is not None for item in details)
    now = time.time()
    for entry, details_item, url in zip(entries, details, urls):
        info = {**entry, **(details_item or {})}
        if info.get("is_live"):
            continue
        timestamp, precision = published_at(info)
        if timestamp is None:
            unverified.append((url, info.get("title") or "Untitled", "publish date unavailable"))
            continue
        age = max(0.25, (now - timestamp) / 3600)
        if age > args.hours + (24 if precision == "date only" else 0):
            stale += 1
            continue
        views = info.get("view_count")
        if views is None:
            unverified.append((url, info.get("title") or "Untitled", "view count unavailable"))
            continue
        rows.append((views / age, views, age, info.get("duration") or 0, info.get("channel") or info.get("uploader") or "", info.get("title") or "", url, bool(info.get("heatmap")), precision))
    rows.sort(reverse=True)
    lines = [
        f'# Trend radar: "{args.query}", last {args.hours:.0f} hours ({time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())})',
        "", "Date-only upload times are approximate; views/hour is an estimate.", "",
        "| # | views/h | views | age h | min | channel | title | most replayed | date precision |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for n, r in enumerate(rows, 1):
        lines.append(f"| {n} | {r[0]:,.0f} | {r[1]:,} | {r[2]:.1f} | {r[3] / 60:.0f} | {safe_cell(r[4])} | [{safe_cell(r[5][:70])}]({r[6]}) | {'yes' if r[7] else 'no'} | {r[8]} |")
    if not rows:
        lines.append("| | | | | | | No verified trends found | | |")
    lines += ["", "## Unverified candidates", "", "These are search results, NOT verified trending videos.", ""]
    for url, title, reason in unverified:
        lines.append(f"- [{safe_cell(title[:90])}]({url}): {reason}")
    lines += ["", "## Diagnostics", "", f"Search: {method}. Found {len(entries)} eligible results; retrieved {fetched} detail records; {stale} older results; {len(unverified)} unverified candidates."]
    for err in errors:
        lines.append(f"- {err}")
    if not rows:
        lines.append("- If no videos are verified, YouTube may be blocking requests or omitting dates/view counts on this GitHub runner.")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:15]))
    print(f"Verified {len(rows)} videos; report written to {args.out}")


if __name__ == "__main__":
    main()
