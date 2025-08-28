# scripts/capture_liff_screens.py
# 使い方:
#   pip install playwright && playwright install
#   python scripts/capture_liff_screens.py --url https://.../liff/consent
#   # 追加で /privacy /terms /cookie も撮影
#   python scripts/capture_liff_screens.py --url https://.../liff/consent --with-legal

import argparse
import os
import sys
from urllib.parse import urljoin

def _parse_viewport(v: str) -> tuple[int, int]:
    """
    "390x844" 形式を (390, 844) に変換。失敗時はデフォルトを返す。
    """
    try:
        w_str, h_str = v.lower().split("x", 1)
        w, h = int(w_str), int(h_str)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 390, 844  # default (iPhone 12相当)

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="LIFF consent URL (e.g., https://.../liff/consent)")
    ap.add_argument("--outdir", default="screens", help="output directory")
    ap.add_argument("--viewport", default="390x844", help='WxH (e.g., "390x844")')
    ap.add_argument("--with-legal", action="store_true", help="also capture /privacy /terms /cookie")
    ap.add_argument("--headful", action="store_true", help="run headed (for visual check)")
    args = ap.parse_args()

    # 遅延インポート（Pylance の MissingImports を回避）
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
    except Exception as e:
        print(
            "Playwright が見つかりません。以下を実行してください:\n"
            "  pip install playwright && playwright install",
            file=sys.stderr,
        )
        sys.exit(1)

    os.makedirs(args.outdir, exist_ok=True)
    w, h = _parse_viewport(args.viewport)

    with sync_playwright() as p:
        browser = None
        ctx = None
        try:
            browser = p.chromium.launch(headless=not args.headful)
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=2,
            )
            page = ctx.new_page()

            # 1) consent 初期
            page.goto(args.url, wait_until="networkidle")
            page.screenshot(path=os.path.join(args.outdir, "consent.png"))

            # 2) チェックON状態（?mock=1 で擬似）
            mock_url = args.url + ("&" if "?" in args.url else "?") + "mock=1"
            page.goto(mock_url, wait_until="networkidle")
            page.screenshot(path=os.path.join(args.outdir, "consent_checked.png"))

            # 3) 法務ページの一括撮影（任意）
            if args.with_legal:
                base = args.url.split("/liff/consent")[0] + "/"
                for name in ["privacy", "terms", "cookie"]:
                    page.goto(urljoin(base, name), wait_until="networkidle")
                    page.screenshot(path=os.path.join(args.outdir, f"{name}.png"))

        finally:
            # 例外があっても確実にクローズ
            try:
                if ctx is not None:
                    ctx.close()
            finally:
                if browser is not None:
                    browser.close()

if __name__ == "__main__":
    main()
