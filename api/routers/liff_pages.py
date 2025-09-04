# api/routers/liff_pages.py — LIFF同意モーダル（単一ページ）版
# - consent.html は使いません。/liff が LIFF 内でモーダルを描画します
# - /liff/consent は liff.line.me の LIFF URL に 302 リダイレクト（クエリは全て維持）
# - 法務リンクは PUBLIC_FRONT_BASE を使った絶対URLにして 404 によるハングを防止
from __future__ import annotations

import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

router = APIRouter(prefix="", tags=["liff"])

# ====== 環境変数 ======
LIFF_ID = os.getenv("LIFF_ID", "").strip()
LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").strip()  # 例: https://liff.line.me/xxxx-yyyy
PUBLIC_FRONT_BASE = os.getenv("PUBLIC_FRONT_BASE", "").rstrip("/")
GA4_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "").strip()  # 任意（あれば自動挿入）

def _abs(url_path: str) -> str:
    """フロントの絶対URLを作る（/legal/privacy.html などを 404 にしない）"""
    if not PUBLIC_FRONT_BASE:
        return url_path
    if url_path.startswith("http"):
        return url_path
    if not url_path.startswith("/"):
        url_path = "/" + url_path
    return f"{PUBLIC_FRONT_BASE}{url_path}"

# ------------------------------------------------------------
# 1) /liff/consent: LIFF ランチャー（302）
#    受け取ったクエリ（user_token, state, utm_* など）は丸ごと維持して LIFF へ転送
# ------------------------------------------------------------
@router.get("/liff/consent", response_class=RedirectResponse)
def liff_consent_redirect(request: Request):
    if not LIFF_CONSENT_URL:
        return JSONResponse({"detail": "LIFF_CONSENT_URL is not configured"}, status_code=500)
    qs = str(request.query_params)          # そのまま引き継ぐ
    url = f"{LIFF_CONSENT_URL}" + (f"?{qs}" if qs else "")
    return RedirectResponse(url, status_code=302)

# ------------------------------------------------------------
# 2) /liff: LIFF ページ本体（同意モーダル内蔵）
#    consent.html は使わず、JS でモーダルを出す → 同意POST → liff.closeWindow()
# ------------------------------------------------------------
@router.get("/liff", response_class=HTMLResponse)
async def liff_root(request: Request):
    html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI相談のご利用前の同意</title>
  <!-- GA4（存在する場合のみ） -->
  {'<script async src="https://www.googletagmanager.com/gtag/js?id='+GA4_MEASUREMENT_ID+'"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag("js",new Date());gtag("config","'+GA4_MEASUREMENT_ID+'");</script>' if GA4_MEASUREMENT_ID else ''}
  <!-- LIFF SDK -->
  <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
  <style>
    body{{font-family: system-ui,-apple-system,Segoe UI,Roboto,'Helvetica Neue',Arial,'Noto Sans JP','Hiragino Kaku Gothic ProN',Meiryo,sans-serif;}}
    .wrap{{padding:24px;}}
    .title{{font-size:22px;font-weight:700;margin:8px 0 16px;}}
    .note{{color:#666;font-size:14px;}}
    .section{{margin-top:18px;line-height:1.9;}}
    .btn{{margin-top:20px;display:inline-block;padding:12px 18px;border-radius:8px;border:none;background:#06C755;color:#fff;font-weight:700;font-size:16px;opacity:.5;}}
    .btn.enabled{{opacity:1;}}
    .links a{{color:#1a73e8;}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">AI相談のご利用前の同意</div>
    <div class="section">
      ・プライバシーポリシー：<a href="{_abs('/legal/privacy.html')}" target="_blank" rel="noopener">こちら</a><br/>
      ・利用規約：<a href="{_abs('/legal/terms.html')}" target="_blank" rel="noopener">こちら</a><br/>
      ・Cookie（外部送信の詳細）：<a href="{_abs('/legal/cookie.html')}" target="_blank" rel="noopener">こちら</a>
    </div>

    <div class="section">
      <label><input type="checkbox" id="c1" checked> プライバシーポリシーに同意します</label><br/>
      <label><input type="checkbox" id="c2" checked> 入力内容が外部サービスへ送信される場合があることを理解しました</label><br/>
      <label><input type="checkbox" id="c3" checked> AIの誤答・限界があることを理解しました</label><br/>
      <label><input type="checkbox" id="c4" checked> Cookie等の利用（計測を含む）に同意します（任意）</label>
    </div>

    <button id="agree" class="btn" disabled>同意して開始</button>
    <div class="note">※同意は公式LINE内の「AI相談」にのみ適用されます。</div>
  </div>

<script>
(function() {{
  const qs = new URLSearchParams(window.location.search);
  const userToken   = qs.get("user_token") || "";
  const state       = qs.get("state") || "";
  const ab          = qs.get("ab") || "";
  const utm_source  = qs.get("utm_source") || "";
  const utm_medium  = qs.get("utm_medium") || "";
  const utm_campaign= qs.get("utm_campaign") || "";
  const utm_content = qs.get("utm_content") || "";

  // 4チェックONでボタン活性（user_token必須）
  const boxes = [...document.querySelectorAll('input[type="checkbox"]')];
  const btn = document.getElementById("agree");
  function tick() {{
    const ok = boxes.every(b => b.checked) && userToken;
    btn.disabled = !ok;
    btn.classList.toggle("enabled", ok);
  }}
  boxes.forEach(b => b.addEventListener("change", tick));
  tick();

  async function postConsent() {{
    // 既存の同意記録APIに合わせてエンドポイント名を調整してください
    const payload = {{
      user_token: userToken,
      source: "liff",
      state, ab, utm_source, utm_medium, utm_campaign, utm_content
    }};
    try {{
      const res = await fetch("/consent/check", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload)
      }});
      if (!res.ok) throw new Error("consent api " + res.status);
      return true;
    }} catch (e) {{
      alert("同意の記録に失敗しました。通信環境をご確認のうえ、もう一度お試しください。");
      return false;
    }}
  }}

  async function initLiff() {{
    try {{
      await liff.init({{ liffId: "{LIFF_ID}" }});
      // トーク内なら login は不要
    }} catch(e) {{
      console.error("liff.init failed", e);
    }}
  }}

  document.getElementById("agree").addEventListener("click", async () => {{
    if (!await postConsent()) return;
    try {{
      if (liff.isInClient()) {{
        liff.closeWindow();     // LINEトークに復帰
      }} else {{
        // ブラウザ起動時のフォールバック（任意）
        window.close();
      }}
    }} catch (e) {{
      console.error(e);
      window.close();
    }}
  }});

  initLiff();
}})();
</script>
</body>
</html>
"""
    return HTMLResponse(html)

@router.get("/liff/ping")
def liff_ping():
    return {"ok": True}
