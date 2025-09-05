from __future__ import annotations

import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

router = APIRouter(prefix="", tags=["liff"])

# ====== 環境変数 ======
LIFF_ID = os.getenv("LIFF_ID", "").strip()
LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").strip()  # 例: https://liff.line.me/xxxx-yyyy
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "").rstrip("/")  # 例: https://rag-api-xxxxxxxx.a.run.app
GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID", "").strip()  # 任意


# ------------------------------------------------------------
# 1) /liff/consent: LIFF ランチャー（302）
#    受け取ったクエリ（user_token, state, utm_* など）は丸ごと維持して LIFF へ転送
# ------------------------------------------------------------
@router.get("/liff/consent", response_class=RedirectResponse)
def liff_consent_redirect(request: Request):
    if not LIFF_CONSENT_URL:
        return JSONResponse({"detail": "LIFF_CONSENT_URL is not configured"}, status_code=500)
    qs = str(request.query_params)  # そのまま引き継ぐ
    url = f"{LIFF_CONSENT_URL}" + (f"?{qs}" if qs else "")
    return RedirectResponse(url, status_code=302)


# ------------------------------------------------------------
# 2) /liff: LIFF ページ本体（同意モーダル内蔵）
#    静的な web/liff/*.html は使用しない
#    ※ f-string で埋め込みつつ、CSS/JS の波括弧はすべて二重にしてエスケープ
# ------------------------------------------------------------
@router.get("/liff", response_class=HTMLResponse)
async def liff_root(request: Request):
    # API の絶対URL（未設定なら現在ホストを使う）
    api_base = PUBLIC_API_BASE or f"{request.url.scheme}://{request.url.netloc}"

    html = f"""<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\" />
  <title>AI相談のご利用前の同意</title>
  <!-- GA4（存在する場合のみ） -->
  {'<script async src=\"https://www.googletagmanager.com/gtag/js?id=' + GA4_MEASUREMENT_ID + '\"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag(\"js\",new Date());gtag(\"config\",\"' + GA4_MEASUREMENT_ID + '\");</script>' if GA4_MEASUREMENT_ID else ''}
  <!-- LIFF SDK -->
  <script src=\"https://static.line-scdn.net/liff/edge/2/sdk.js\"></script>
  <style>
    body{{font-family: system-ui,-apple-system,Segoe UI,Roboto,'Helvetica Neue',Arial,'Noto Sans JP','Hiragino Kaku Gothic ProN',Meiryo,sans-serif;}}
    .wrap{{padding:24px;line-height:1.9}}
    .title{{font-size:22px;font-weight:700;margin:8px 0 16px;}}
    .note{{color:#666;font-size:14px;}}
    .section{{margin-top:18px;}}
    .btn{{margin-top:20px;display:inline-block;padding:12px 18px;border-radius:8px;border:none;background:#06C755;color:#fff;font-weight:700;font-size:16px;opacity:.5;}}
    .btn.enabled{{opacity:1;}}
    a{{color:#1a73e8;}}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"title\">AI相談のご利用前の同意</div>
    <div class=\"section\">
      ・プライバシーポリシー：<a href=\"/privacy\" target=\"_blank\" rel=\"noopener\">こちら</a><br/>
      ・利用規約：<a href=\"/terms\" target=\"_blank\" rel=\"noopener\">こちら</a><br/>
      ・Cookie（外部送信の詳細）：<a href=\"/cookie\" target=\"_blank\" rel=\"noopener\">こちら</a>
    </div>

    <div class=\"section\">
      <label><input type=\"checkbox\" id=\"c1\" checked> プライバシーポリシーに同意します</label><br/>
      <label><input type=\"checkbox\" id=\"c2\" checked> 入力内容が外部サービスへ送信される場合があることを理解しました</label><br/>
      <label><input type=\"checkbox\" id=\"c3\" checked> AIの誤答・限界があることを理解しました</label><br/>
      <label><input type=\"checkbox\" id=\"c4\" checked> Cookie等の利用（計測を含む）に同意します</label>
    </div>

    <button id=\"agree\" class=\"btn\" disabled>同意して開始</button>
    <div class=\"note\">※同意は公式LINE内の「AI相談」にのみ適用されます。</div>
  </div>

<script>
(function() {{
  const API_BASE = {api_base!r};

  // --- クエリは liff.state も含めて吸い上げる（user_token 等の取りこぼし防止）
  const all = new URLSearchParams(location.search);
  const stateQS = new URLSearchParams(all.get("liff.state") || "");
  const get = (k) => all.get(k) || stateQS.get(k) || "";

  const userToken    = get("user_token");
  const state        = get("state");
  const ab           = get("ab");
  const utm_source   = get("utm_source");
  const utm_medium   = get("utm_medium");
  const utm_campaign = get("utm_campaign");
  const utm_content  = get("utm_content");

  // --- 4チェックすべて必須（Cookie含む）+ user_token 必須 でボタン活性
  const boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
  const btn = document.getElementById("agree");
  function tick() {{
    const ok = boxes.every(b => b.checked) && !!userToken;
    btn.disabled = !ok;
    btn.classList.toggle("enabled", ok);
  }}
  boxes.forEach(b => b.addEventListener("change", tick));
  tick();

  // --- 同意保存API: API_BASE + "/consent/save?user_token=...&scope=ai"
  async function postConsent() {{
    const payload = {{
      agree_privacy: boxes[0].checked,
      understand_external_send: boxes[1].checked,
      understand_ai_may_be_wrong: boxes[2].checked,
      agree_cookie: boxes[3].checked,
      meta: {{ state, ab, utm_source, utm_medium, utm_campaign, utm_content, ua: navigator.userAgent }}
    }};
    const q = new URLSearchParams({{ user_token: userToken, scope: "ai" }}).toString();
    const res = await fetch(API_BASE + "/consent/save?" + q, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json", "X-User-Token": userToken }},
      body: JSON.stringify(payload)
    }});
    if (!res.ok) throw new Error("consent api " + res.status);
  }}

  async function initLiff() {{
    try {{ await liff.init({{ liffId: {LIFF_ID!r} }}); }} catch(e) {{ console.error("liff.init failed", e); }}
  }}

  document.getElementById("agree").addEventListener("click", async () => {{
    try {{
      await postConsent();
      // 体感速度を落とさずAI相談を自動開始（失敗してもUIは止めない）
      fetch(API_BASE + "/line/after-consent", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "X-User-Id": userToken }},
        body: JSON.stringify({{ user_token: userToken }}),
        keepalive: true
      }}).catch(() => {{}});
    }} finally {{
      if (window.liff && liff.isInClient()) {{ liff.closeWindow(); }} else {{ window.close(); }}
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


# ------------------------------------------------------------
# 3) LP互換エイリアス（/line /liff → 正規入口 /line-login/start に 302）
#    UTM/AB/state などのクエリはそのまま引き継ぐ
# ------------------------------------------------------------
@router.get("/line")
@router.get("/line/add")
@router.get("/line/contact")
def line_entry_alias(request: Request):
    qs = str(request.query_params)
    url = "/line-login/start" + (f"?{qs}" if qs else "")
    return RedirectResponse(url, status_code=302)


@router.get("/liff/add")
@router.get("/liff/contact")
@router.get("/liff/line")
def liff_entry_alias(request: Request):
    qs = str(request.query_params)
    url = "/line-login/start" + (f"?{qs}" if qs else "")
    return RedirectResponse(url, status_code=302)
