# api/routers/liff_pages.py (修正版)
from __future__ import annotations
import os, json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(prefix="", tags=["liff"])

def _query(q: str) -> str:
    return ("?" + q) if q else ""

@router.get("/liff/add")
async def liff_add(request: Request):
    # Preserve utm/ab/state, etc.
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff/line")
async def liff_line(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff/contact")
async def liff_contact(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff")
async def liff_consent(_: Request):
    # 埋め込み用の設定（無ければ空でOK。JS側でlocation.originにフォールバック）
    cfg = {
        "API_BASE": (os.getenv("PUBLIC_API_BASE", "").rstrip("/")),
        "LIFF_ID": os.getenv("LIFF_ID", ""),
        "CONSENT_URL": os.getenv("LIFF_CONSENT_URL", ""),
        "LINE_BASIC_ID": os.getenv("LINE_BASIC_ID", "").lstrip("@"),
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False)

    css = """
<style>
  html,body{margin:0;padding:0;background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:640px;margin:0 auto;padding:24px}
  h1{font-size:22px;margin:0 0 8px}
  .section{margin-top:18px}
  .btn{width:100%;padding:14px 18px;border-radius:8px;border:0;background:#06c755;color:#fff;font-size:16px;opacity:.5}
  .btn.enabled{opacity:1}
  .links a{color:#1976d2;text-decoration:none}
  .note{color:#666;font-size:12px;margin-top:10px}
  .debug{background:#f5f5f5;padding:10px;margin-top:10px;font-size:12px;border-radius:4px}
  .error{background:#ffe6e6;padding:10px;margin-top:10px;color:#d63031;border-radius:4px;display:none}
</style>
"""

    html = (
        """<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"utf-8\">"""
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>AI相談のご利用前の同意</title>" + css + "</head><body>"
        "<div class=\"wrap\">"
        "  <h1>AI相談のご利用前の同意</h1>"
        "  <div class=\"links\">"
        "    ・プライバシーポリシー：<a href=\"/privacy\" target=\"_blank\" rel=\"noopener\">こちら</a><br/>"
        "    ・利用規約：<a href=\"/terms\" target=\"_blank\" rel=\"noopener\">こちら</a><br/>"
        "    ・Cookie（外部送信の詳細）：<a href=\"/cookie\" target=\"_blank\" rel=\"noopener\">こちら</a>"
        "  </div>"
        "  <div class=\"section\">"
        "    <label><input type=\"checkbox\" id=\"c1\" checked> プライバシーポリシーに同意します</label><br/>"
        "    <label><input type=\"checkbox\" id=\"c2\" checked> 入力内容が外部サービスへ送信される場合があることを理解しました</label><br/>"
        "    <label><input type=\"checkbox\" id=\"c3\" checked> AIの誤答・限界があることを理解しました</label><br/>"
        "    <label><input type=\"checkbox\" id=\"c4\" checked> Cookie等の利用（計測を含む）に同意します</label>"
        "  </div>"
        "  <button id=\"agree\" class=\"btn\" disabled>同意して開始</button>"
        "  <div class=\"note\">※同意は公式LINE内の「AI相談」にのみ適用されます。</div>"
        "  <div id=\"debug\" class=\"debug\">デバッグ情報: 初期化中...</div>"
        "  <div id=\"error\" class=\"error\"></div>"
        "</div>"
        f"<script>window.__CFG__ = {cfg_json};</script>"
        "<script>(function(){\n"
        "  const debugEl = document.getElementById('debug');\n"
        "  const errorEl = document.getElementById('error');\n"
        "  function log(msg) { console.log(msg); debugEl.textContent = msg; }\n"
        "  function showError(msg) { errorEl.textContent = msg; errorEl.style.display = 'block'; }\n"
        "  \n"
        "  const qs = new URLSearchParams(location.search);\n"
        "  const userToken = qs.get('user_token') || '';\n"
        "  const cfg = window.__CFG__ || {};\n"
        "  const API_BASE = cfg.API_BASE || location.origin;\n"
        "  \n"
        "  log(`初期化完了: userToken=${userToken}, API_BASE=${API_BASE}`);\n"
        "  \n"
        "  const afterConsent = API_BASE + '/line/after-consent';\n"
        "  const consentSave  = API_BASE + '/consent/save';\n"
        "  const boxes = Array.from(document.querySelectorAll('input[type=\\'checkbox\\']'));\n"
        "  const btn = document.getElementById('agree');\n"
        "  \n"
        "  function tick(){ \n"
        "    const ok = boxes.every(b=>b.checked) && !!userToken; \n"
        "    btn.disabled=!ok; \n"
        "    btn.classList.toggle('enabled', ok);\n"
        "    log(`チェック状態: ${ok ? '有効' : '無効'} (userToken: ${!!userToken})`);\n"
        "  }\n"
        "  \n"
        "  boxes.forEach(b=>b.addEventListener('change', tick)); \n"
        "  tick();\n"
        "  \n"
        "  btn.addEventListener('click', async function(){\n"
        "    if(btn.disabled) return;\n"
        "    \n"
        "    btn.disabled = true;\n"
        "    btn.textContent = '処理中...';\n"
        "    log('同意処理開始...');\n"
        "    \n"
        "    try{\n"
        "      const payload = {\n"
        "        version:'2025-09-01', \n"
        "        flags:{pp:true,tos:true,cookie:true,xfer:true,ai_limits:true}, \n"
        "        meta:Object.fromEntries(qs.entries())\n"
        "      };\n"
        "      \n"
        "      // 1. 同意保存\n"
        "      log('同意保存中...');\n"
        "      const saveUrl = consentSave + '?user_token=' + encodeURIComponent(userToken) + '&scope=ai';\n"
        "      const saveResponse = await fetch(saveUrl, {\n"
        "        method:'POST', \n"
        "        headers:{'Content-Type':'application/json'}, \n"
        "        body: JSON.stringify(payload),\n"
        "        keepalive:true\n"
        "      });\n"
        "      \n"
        "      if (!saveResponse.ok) {\n"
        "        throw new Error(`同意保存失敗: ${saveResponse.status} ${saveResponse.statusText}`);\n"
        "      }\n"
        "      log('同意保存完了');\n"
        "      \n"
        "      // 2. LINE通知\n"
        "      log('LINE通知中...');\n"
        "      const afterResponse = await fetch(afterConsent, {\n"
        "        method:'POST', \n"
        "        headers:{'Content-Type':'application/json','X-User-Id': userToken}, \n"
        "        body: JSON.stringify({source:'liff_consent', meta:Object.fromEntries(qs.entries())}),\n"
        "        keepalive:true\n"
        "      });\n"
        "      \n"
        "      if (!afterResponse.ok) {\n"
        "        console.warn('LINE通知失敗:', afterResponse.status, afterResponse.statusText);\n"
        "      } else {\n"
        "        log('LINE通知完了');\n"
        "      }\n"
        "      \n"
        "      // 3. LIFF画面を閉じる\n"
        "      log('画面を閉じています...');\n"
        "      try{ \n"
        "        if(window.liff && liff.closeWindow) {\n"
        "          liff.closeWindow(); \n"
        "        } else {\n"
        "          log('LIFF APIが利用できません。LINEに戻ります。');\n"
        "          location.href = 'https://line.me/';\n"
        "        }\n"
        "      }catch(e){\n"
        "        log('画面を閉じる処理でエラー。LINEに戻ります。');\n"
        "        location.href = 'https://line.me/';\n"
        "      }\n"
        "      \n"
        "    }catch(e){\n"
        "      console.error('同意処理エラー:', e);\n"
        "      showError('エラーが発生しました: ' + e.message);\n"
        "      btn.disabled = false;\n"
        "      btn.textContent = '同意して開始';\n"
        "    }\n"
        "  });\n"
        "})();</script>"
        "</body></html>"
    )
    return HTMLResponse(html)

@router.get("/liff/ping")
def liff_ping():
    return {"ok": True}