# api/routers/liff_pages.py
# LIFF同意ページ：UIDを正送信（X-User-Id / body.user_id）し、同意後に after-consent を確実に叩く
from __future__ import annotations
import os
import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(prefix="", tags=["liff"])


def _query(q: str) -> str:
    return ("?" + q) if q else ""


# --- 既存導線：/liff/add などはログイン開始へ302 ---
@router.get("/liff/add")
async def liff_add(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)


@router.get("/liff/line")
async def liff_line(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)


@router.get("/liff/contact")
async def liff_contact(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)


# --- LIFF同意ページ本体 ---
@router.get("/liff")
async def liff_consent(_: Request):
    cfg = {
        "API_BASE": (os.getenv("PUBLIC_API_BASE", "").rstrip("/")),
        "LIFF_ID": os.getenv("LIFF_ID", ""),
        "CONSENT_URL": os.getenv("LIFF_CONSENT_URL", ""),
        "LINE_BASIC_ID": os.getenv("LINE_BASIC_ID", "").lstrip("@"),
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False)

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>AI相談のご利用前の同意</title>
<!-- LIFF SDK -->
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>
  html,body{{margin:0;padding:0;background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}}
  .wrap{{max-width:640px;margin:0 auto;padding:22px}}
  h1{{font-size:22px;margin:0 0 12px}}
  .item{{margin:8px 0}}
  .btn{{width:100%;padding:14px 18px;border:0;border-radius:10px;background:#06c755;color:#fff;font-size:16px;opacity:.5}}
  .btn.enabled{{opacity:1}}
  .note{{margin-top:10px;font-size:12px;color:#666}}
  .box{{margin-top:12px;padding:10px;border-radius:8px;font-size:12px}}
  .ok{{background:#e7f7e9;color:#1b5e20;display:none}}
  .err{{background:#ffebee;color:#c62828;display:none}}
  a{{color:#1976d2;text-decoration:none}}
</style>
</head>
<body>
<div class="wrap">
  <h1>AI相談のご利用前の同意</h1>
  <div class="item">・プライバシーポリシー：<a href="/privacy" target="_blank" rel="noopener">こちら</a></div>
  <div class="item">・利用規約：<a href="/terms" target="_blank" rel="noopener">こちら</a></div>
  <div class="item">・Cookie（外部送信の詳細）：<a href="/cookie" target="_blank" rel="noopener">こちら</a></div>

  <div class="item"><label><input type="checkbox" id="c1" checked> プライバシーポリシーに同意します</label></div>
  <div class="item"><label><input type="checkbox" id="c2" checked> 入力内容が外部サービスへ送信される場合があることを理解しました</label></div>
  <div class="item"><label><input type="checkbox" id="c3" checked> AIの誤答・限界があることを理解しました</label></div>
  <div class="item"><label><input type="checkbox" id="c4" checked> Cookie等の利用（計測を含む）に同意します</label></div>

  <button id="agree" class="btn" disabled>同意して開始</button>
  <div class="note">※同意は公式LINE内の「AI相談」にのみ適用されます。</div>

  <div id="ok" class="box ok"></div>
  <div id="er" class="box err"></div>
</div>

<script>
window.__CFG__ = {cfg_json};

(function(){{
  const cfg = window.__CFG__ || {{}};
  const API_BASE = cfg.API_BASE || location.origin;
  const LIFF_ID  = cfg.LIFF_ID || "";
  const BASIC_ID = cfg.LINE_BASIC_ID || "";

  const okEl = document.getElementById('ok');
  const erEl = document.getElementById('er');
  const btn  = document.getElementById('agree');
  const checks = Array.from(document.querySelectorAll('input[type=checkbox]'));

  function showOK(m) {{ okEl.textContent=m; okEl.style.display='block'; erEl.style.display='none'; }}
  function showER(m) {{ erEl.textContent=m; erEl.style.display='block'; okEl.style.display='none'; }}

  let accessToken = "";    // liff.getAccessToken()（WORMログ用途に維持）
  let lineUID = "";        // ★ U で始まる LINE ユーザーID（Push の to に使用）
  let liffReady = false;

  // ★★★ 修正箇所1：tokenFromURL() 関数を削除 ★★★
  // ❌ 削除された関数：
  // function tokenFromURL(){{
  //   const qs = new URLSearchParams(location.search);
  //   return qs.get('user_token') || '';
  // }}

  function enableIfReady(){{
    const ok = checks.every(b=>b.checked) && (accessToken || lineUID);
    btn.disabled = !ok; btn.classList.toggle('enabled', ok);
  }}

  async function init(){{
    try {{
      if (typeof liff === 'undefined') throw new Error('LIFF SDKの読み込みに失敗しました');
      await liff.init({{ liffId: LIFF_ID }});
      liffReady = true;

      if (!liff.isLoggedIn()) {{
        // LIFFブラウザ/外部ブラウザ問わずログインを促す
        liff.login();
        return;
      }}

      try {{ accessToken = liff.getAccessToken() || ""; }} catch(_e){{ accessToken=""; }}

      // UID 優先取得：decodedIDToken.sub → profile.userId
      try {{
        const d = liff.getDecodedIDToken && liff.getDecodedIDToken();
        if (d && d.sub && d.sub.startsWith('U')) lineUID = d.sub;
      }} catch(_e){{}}
      if (!lineUID) {{
        try {{
          const p = await liff.getProfile();
          if (p && p.userId && p.userId.startsWith('U')) lineUID = p.userId;
        }} catch(_e){{}}
      }}

      // ★★★ 修正箇所2：URL経由のトークン取得を削除 ★★★
      // ❌ 削除された行：
      // if (!accessToken) accessToken = tokenFromURL();

      checks.forEach(b=>b.addEventListener('change', enableIfReady));
      enableIfReady();

      btn.addEventListener('click', onAgree);
    }} catch(e) {{
      showER('LIFF初期化に失敗: ' + e.message);
    }}
  }}

  async function onAgree(){{
    if (btn.disabled) return;
    btn.disabled = true; btn.textContent = '処理中...';

    try {{
      // 1) 同意保存（WORMログ整合のため user_token は accessToken/UID のどちらか）
      const saveUrl = `${{API_BASE}}/consent/save?user_token=${{encodeURIComponent(accessToken || lineUID)}}&scope=ai`;
      const saveRes = await fetch(saveUrl, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Token': accessToken || lineUID,
          'X-LIFF-ID': LIFF_ID
        }},
        body: JSON.stringify({{
          agree_privacy: true,
          understand_external_send: true,
          understand_ai_may_be_wrong: true,
          agree_cookie: true,
          meta: {{ source: 'liff_consent', liff_id: LIFF_ID, ua: navigator.userAgent }}
        }}),
        keepalive: true
      }});
      if (!saveRes.ok) throw new Error('同意保存に失敗: ' + saveRes.status);
      const saved = await saveRes.json();

      // 2) 同意後のPush（★ UID を明示送信）
      const acRes = await fetch(`${{API_BASE}}/line/after-consent`, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Id': lineUID || '',     // ★ 最重要：ヘッダに U...
          'X-LIFF-ID': LIFF_ID
        }},
        body: JSON.stringify({{
          user_token: accessToken || lineUID,   // 互換維持
          user_id: lineUID || '',               // ★ ボディにも UID
          source: 'liff_consent',
          consent_id: saved.consent_id || 'unknown',
          meta: {{ liff_id: LIFF_ID }}
        }}),
        keepalive: true
      }});
      if (!acRes.ok) {{
        // Push が非200でもユーザ体験優先でクローズする（ログはサーバ側で残る）
        console.warn('after-consent non-200:', acRes.status, await acRes.text());
      }}

      showOK('同意が完了しました。LINEに戻ります…');
      btn.textContent = '完了！';

      setTimeout(()=>{{
        try {{
          if (liffReady && liff.isInClient()) liff.closeWindow();
          else window.location.href = `https://line.me/R/ti/p/@${{BASIC_ID}}`;
        }} catch(_e) {{
          window.location.href = `https://line.me/R/ti/p/@${{BASIC_ID}}`;
        }}
      }}, 1200);
    }} catch(e) {{
      showER('エラー: ' + e.message);
      btn.disabled = false; btn.textContent = '同意して開始';
    }}
  }}

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}})();
</script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/liff/ping")
def liff_ping():
    return {"ok": True}