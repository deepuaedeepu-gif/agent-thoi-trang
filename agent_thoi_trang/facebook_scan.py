"""Quét reel công khai trên Facebook bằng trình duyệt do chính người dùng đăng nhập.

- App mở một cửa sổ Chromium riêng (hồ sơ lưu ở `data/browser/facebook`). Người dùng tự đăng nhập
  trong cửa sổ đó; app không bao giờ nhận hay lưu mật khẩu.
- Agent mở các link được đưa, cuộn tab Reels chậm, đọc link + lượt xem hiển thị, chọn video tốt nhất,
  rồi tải video về bằng yt-dlp (dùng cookie của phiên đăng nhập đó).

Lưu ý: điều khoản của Meta không cho phép thu thập dữ liệu tự động. Tài khoản dùng để quét có thể bị
yêu cầu xác minh hoặc khoá tạm thời. Module này giới hạn tốc độ và số video để giảm rủi ro.

Chạy riêng (app gọi bằng subprocess để không xung đột vòng lặp sự kiện của Streamlit):
    python -m agent_thoi_trang.facebook_scan login
    python -m agent_thoi_trang.facebook_scan scan --out work/scan URL [URL ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

PROFILE_DIR = Path("data/browser/facebook")
MAX_SCROLLS = 25           # mỗi kênh
MAX_DOWNLOADS = 20         # tổng số video tải về
PAUSE_RANGE = (2.0, 5.0)   # giây nghỉ ngẫu nhiên giữa các thao tác

_UNITS = {"k": 1e3, "n": 1e3, "nghìn": 1e3, "ngàn": 1e3, "m": 1e6, "tr": 1e6, "triệu": 1e6, "b": 1e9, "tỷ": 1e9}


def parse_count(text: str | None) -> int | None:
    """'1,2K' / '1.2K' / '12 N' / '3,4 Tr' / '987' -> số nguyên."""
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(nghìn|ngàn|triệu|tỷ|tr|k|n|m|b)?\b", text.strip().lower())
    if not m:
        return None
    number, unit = m.group(1), m.group(2)
    if unit:
        return int(float(number.replace(",", ".")) * _UNITS[unit])
    return int(re.sub(r"[.,]", "", number))


def reels_tab_url(url: str) -> str | None:
    """Đổi link trang/profile thành link tab Reels. Trả về None nếu đã là link một reel/video."""
    u = urlparse(url)
    if "/reel/" in u.path or "/videos/" in u.path or "/watch" in u.path:
        return None
    if u.path.rstrip("/") == "/profile.php":
        q = parse_qs(u.query)
        q["sk"] = ["reels_tab"]
        return urlunparse(u._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return urlunparse(u._replace(path=u.path.rstrip("/") + "/reels/", query=""))


def canonical_reel(href: str) -> str | None:
    m = re.search(r"/reel/(\d+)", href)
    return f"https://www.facebook.com/reel/{m.group(1)}" if m else None


def pick_top(items: list[dict], n: int) -> list[dict]:
    """Chọn n reel nhiều lượt xem nhất; reel không đọc được lượt xem xếp cuối."""
    return sorted(items, key=lambda x: x.get("views") or -1, reverse=True)[:n]


def _pause(page) -> None:
    page.wait_for_timeout(int(random.uniform(*PAUSE_RANGE) * 1000))


def _launch(p, headless: bool = False):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # Mặc định dùng Chromium của Playwright; đặt AGENT_CHROME_PATH để dùng Chrome có sẵn trên máy.
    extra = {"executable_path": os.environ["AGENT_CHROME_PATH"]} if os.environ.get("AGENT_CHROME_PATH") else {}
    return p.chromium.launch_persistent_context(str(PROFILE_DIR), headless=headless, locale="vi-VN",
                                                viewport={"width": 1280, "height": 900}, **extra)


def login() -> None:
    """Mở cửa sổ để người dùng tự đăng nhập. Đóng cửa sổ khi xong."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/login")
        print("Hãy đăng nhập Facebook trong cửa sổ vừa mở, rồi đóng cửa sổ.", flush=True)
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        ctx.close()


def has_session() -> bool:
    """Đã từng mở cửa sổ đăng nhập (có file cookie). Không đảm bảo phiên còn hiệu lực."""
    return any(f.exists() and f.stat().st_size > 0
               for f in (PROFILE_DIR / "Default" / "Network" / "Cookies", PROFILE_DIR / "Default" / "Cookies"))


def _collect_reels(page, url: str) -> list[dict]:
    tab = reels_tab_url(url)
    if tab is None:
        reel = canonical_reel(url) or url
        return [{"url": reel, "views": None, "source": url}]
    page.goto(tab)
    _pause(page)
    found: dict[str, dict] = {}
    stale = 0
    for _ in range(MAX_SCROLLS):
        anchors = page.eval_on_selector_all(
            "a[href*='/reel/']", "els => els.map(e => ({href: e.href, text: e.innerText || e.getAttribute('aria-label') || ''}))")
        before = len(found)
        for a in anchors:
            reel = canonical_reel(a["href"])
            if reel and reel not in found:
                found[reel] = {"url": reel, "views": parse_count(a["text"]), "source": url}
        stale = stale + 1 if len(found) == before else 0
        if stale >= 3:
            break
        page.mouse.wheel(0, random.randint(1200, 2000))
        _pause(page)
    return list(found.values())


def _reel_details(page, item: dict) -> dict:
    """Đọc caption và số tương tác hiển thị trên trang reel (cố gắng hết mức, có thể thiếu)."""
    page.goto(item["url"])
    _pause(page)
    caption = page.eval_on_selector("meta[property='og:description']", "e => e.content") \
        if page.query_selector("meta[property='og:description']") else None
    labels = " | ".join(page.eval_on_selector_all("[aria-label]", "els => els.map(e => e.getAttribute('aria-label'))")[:400])

    def near(pattern: str) -> int | None:
        m = re.search(r"([\d.,]+\s*(?:nghìn|ngàn|triệu|tr|k|n|m)?)\s*" + pattern, labels, re.I)
        return parse_count(m.group(1)) if m else None

    item.update(caption=caption, likes=near(r"(?:cảm xúc|reactions?|lượt thích|likes?)"),
                comments=near(r"(?:bình luận|comments?)"), shares=near(r"(?:lượt chia sẻ|chia sẻ|shares?)"))
    return item


def _write_cookies_txt(ctx, path: Path) -> None:
    lines = ["# Netscape HTTP Cookie File"]
    for c in ctx.cookies():
        if "facebook" not in c["domain"]:
            continue
        lines.append("\t".join([c["domain"], "TRUE" if c["domain"].startswith(".") else "FALSE", c["path"],
                                "TRUE" if c["secure"] else "FALSE", str(int(c.get("expires") or 0)),
                                c["name"], c["value"]]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def download(items: list[dict], out_dir: Path, cookies: Path) -> None:
    for i, item in enumerate(items):
        vid = f"reel_{i + 1:02d}"
        item["video_id"] = vid
        cmd = [sys.executable, "-m", "yt_dlp", "--cookies", str(cookies), "-f", "mp4/best",
               "-o", str(out_dir / f"{vid}.%(ext)s"), "--no-playlist", "--quiet", item["url"]]
        result = subprocess.run(cmd, capture_output=True, text=True)
        item["downloaded"] = result.returncode == 0
        if result.returncode != 0:
            print(f"Không tải được {item['url']}: {result.stderr.strip()[:200]}", flush=True)
        time.sleep(random.uniform(*PAUSE_RANGE))


def scan(urls: list[str], out_dir: Path, top_n: int = 20, headless: bool = False) -> list[dict]:
    """Quét các link, chọn top_n reel nhiều view nhất, đọc chi tiết, tải video, ghi metadata.csv."""
    from playwright.sync_api import sync_playwright

    top_n = min(top_n, MAX_DOWNLOADS)
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        items: list[dict] = []
        for url in urls:
            print(f"Đang quét {url}", flush=True)
            got = _collect_reels(page, url)
            print(f"  tìm thấy {len(got)} reel", flush=True)
            items += got
        top = pick_top(items, top_n)
        for i, item in enumerate(top):
            print(f"Đọc chi tiết {i + 1}/{len(top)}", flush=True)
            _reel_details(page, item)
        cookies = out_dir / ".cookies.txt"
        _write_cookies_txt(ctx, cookies)
        ctx.close()
    try:
        download(top, out_dir, cookies)
    finally:
        cookies.unlink(missing_ok=True)
    with open(out_dir / "metadata.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "caption", "views", "likes", "comments", "shares", "url"])
        w.writeheader()
        for item in top:
            if item.get("downloaded"):
                w.writerow({k: item.get(k) for k in w.fieldnames})
    (out_dir / "scan.json").write_text(json.dumps(top, ensure_ascii=False, indent=2), encoding="utf-8")
    return top


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["login", "scan"])
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--out", default="work/scan")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)
    if args.command == "login":
        login()
    else:
        if not args.urls:
            ap.error("Cần ít nhất 1 link")
        top = scan(args.urls, Path(args.out), args.top)
        print(f"Xong: tải được {sum(1 for t in top if t.get('downloaded'))}/{len(top)} video -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
