# api/routers/liff_pages.py (修正版 - LIFF SDK初期化対応)
from __future__ import annotations
import os, json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(prefix="", tags=["liff"])

def _query(q: str) -> str:
    return ("?" + q) if q else ""

@router.get("/liff/add")
async def liff_add(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff/line")
async def liff_line(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff/contact")
async def liff_contact(request: Request):
    return RedirectResponse("/line-login/start" + _query(request.url.query), status_code=302)

@router.get("/liff")
async def liff_consent(_: Request):
    # 設定を環境変数から取得
    cfg = {
        "API_BASE": (os.getenv("PUBLIC_API_BASE", "").rstrip("/")),
        "LIFF_ID": os.getenv("LIFF_ID", "2007887876-vMNe74eX"),  # 既定値を設定
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

    html = f"""<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI相談のご利用前の同意</title>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
{css}
</head><body>
<div class="wrap">
  <h1>AI相談のご利用前の同意</h1>
  <div class="links">
    ・プライバシーポリシー：<a href="/privacy" target="_blank" rel="noopener">こちら</a><br/>
    ・利用規約：<a href="/terms" target="_blank" rel="noopener">こちら</a><br/>
    ・Cookie（外部送信の詳細）：<a href="/cookie" target="_blank" rel="noopener">こちら</a>
  </div>
  <div class="section">
    <label><input type="checkbox" id="c1" checked> プライバシーポリシーに同意します</label><br/>
    <label><input type="checkbox" id="c2" checked> 入力内容が外部サービスへ送信される場合があることを理解しました</label><br/>
    <label><input type="checkbox" id="c3" checked> AIの誤答・限界があることを理解しました</label><br/>
    <label><input type="checkbox" id="c4" checked> Cookie等の利用（計測を含む）に同意します</label>
  </div>
  <button id="agree" class="btn" disabled>同意して開始</button>
  <div class="note">※同意は公式LINE内の「AI相談」にのみ適用されます。</div>
  <div id="debug" class="debug">デバッグ情報: 初期化中...</div>
  <div id="error" class="error"></div>
</div>

<script>
window.__CFG__ = {cfg_json};

(function(){{
  const debugEl = document.getElementById('debug');
  const errorEl = document.getElementById('error');
  
  function log(msg) {{ 
    console.log(msg); 
    debugEl.textContent = msg; 
  }}
  
  function showError(msg) {{ 
    console.error(msg);
    errorEl.textContent = msg; 
    errorEl.style.display = 'block'; 
  }}
  
  const cfg = window.__CFG__ || {{}};
  const API_BASE = cfg.API_BASE || location.origin;
  const LIFF_ID = cfg.LIFF_ID || '2007887876-vMNe74eX';
  
  let userToken = '';
  let isLiffReady = false;
  
  // LIFF SDK初期化
  async function initLiff() {{
    try {{
      log('LIFF SDK初期化中...');
      
      await liff.init({{ liffId: LIFF_ID }});
      
      log('LIFF SDK初期化完了');
      isLiffReady = true;
      
      // ユーザートークン取得
      if (liff.isLoggedIn()) {{
        userToken = liff.getAccessToken();
        log(`ユーザートークン取得完了: ${{userToken ? '✓' : '✗'}}`);
      }} else {{
        log('ユーザーがログインしていません');
        // 外部ブラウザの場合はログインが必要
        if (!liff.isInClient()) {{
          liff.login();
          return;
        }}
      }}
      
      // URLパラメータからも取得を試行（フォールバック）
      const qs = new URLSearchParams(location.search);
      const urlToken = qs.get('user_token');
      if (!userToken && urlToken) {{
        userToken = urlToken;
        log('URLパラメータからトークン取得');
      }}
      
      updateUI();
      
    }} catch (error) {{
      console.error('LIFF初期化エラー:', error);
      showError(`LIFF初期化エラー: ${{error.message}}`);
      
      // フォールバック: URLパラメータから取得
      const qs = new URLSearchParams(location.search);
      userToken = qs.get('user_token') || '';
      if (userToken) {{
        log('フォールバック: URLパラメータからトークン取得');
        updateUI();
      }} else {{
        showError('ユーザートークンを取得できませんでした');
      }}
    }}
  }}
  
  function updateUI() {{
    const boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
    const btn = document.getElementById('agree');
    
    function tick() {{
      const allChecked = boxes.every(b => b.checked);
      const hasToken = !!userToken;
      const canSubmit = allChecked && hasToken;
      
      btn.disabled = !canSubmit;
      btn.classList.toggle('enabled', canSubmit);
      
      log(`チェック状態: ${{allChecked ? '✓' : '✗'}} / トークン: ${{hasToken ? '✓' : '✗'}} / 送信可能: ${{canSubmit ? '✓' : '✗'}}`);
    }}
    
    boxes.forEach(b => b.addEventListener('change', tick));
    tick();
    
    // 同意ボタンクリック処理
    btn.addEventListener('click', handleConsent);
  }}
  
  async function handleConsent() {{
    const btn = document.getElementById('agree');
    if (btn.disabled) return;
    
    btn.disabled = true;
    btn.textContent = '処理中...';
    log('同意処理開始...');
    
    try {{
      // 同意データ準備
      const consentData = {{
        agree_privacy: true,
        understand_external_send: true,
        understand_ai_may_be_wrong: true,
        agree_cookie: true,
        meta: {{
          source: 'liff_consent',
          liff_id: LIFF_ID,
          timestamp: new Date().toISOString()
        }}
      }};
      
      // 1. 同意保存API呼び出し
      log('同意保存中...');
      const saveUrl = `${{API_BASE}}/consent/save?user_token=${{encodeURIComponent(userToken)}}&scope=ai`;
      
      const saveResponse = await fetch(saveUrl, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Token': userToken
        }},
        body: JSON.stringify(consentData),
        keepalive: true
      }});
      
      if (!saveResponse.ok) {{
        throw new Error(`同意保存失敗: ${{saveResponse.status}} ${{saveResponse.statusText}}`);
      }}
      
      const saveResult = await saveResponse.json();
      log('同意保存完了: ' + JSON.stringify(saveResult));
      
      // 2. LINE通知API呼び出し
      log('LINE通知中...');
      const afterConsentUrl = `${{API_BASE}}/line/after-consent`;
      
      const afterResponse = await fetch(afterConsentUrl, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Id': userToken
        }},
        body: JSON.stringify({{
          user_token: userToken,
          source: 'liff_consent',
          meta: {{ liff_id: LIFF_ID }}
        }}),
        keepalive: true
      }});
      
      if (!afterResponse.ok) {{
        console.warn('LINE通知失敗:', afterResponse.status, afterResponse.statusText);
        log('LINE通知でエラーが発生しましたが、処理を続行します');
      }} else {{
        const afterResult = await afterResponse.json();
        log('LINE通知完了: ' + JSON.stringify(afterResult));
      }}
      
      // 3. 完了メッセージ表示
      btn.textContent = '完了！';
      log('同意処理が完了しました。画面を閉じます...');
      
      // 4. 画面を閉じる（改善版）
      setTimeout(() => {{
        closeLiffWindow();
      }}, 1000);
      
    }} catch (error) {{
      console.error('同意処理エラー:', error);
      showError('エラーが発生しました: ' + error.message);
      btn.disabled = false;
      btn.textContent = '同意して開始';
      log('エラーのため処理を中断しました');
    }}
  }}
  
  function closeLiffWindow() {{
    try {{
      log('画面を閉じる処理を開始...');
      
      // LIFF環境で実行されているかチェック
      if (isLiffReady && liff.isInClient()) {{
        log('LIFF環境内で実行中 - liff.closeWindow()を呼び出し');
        liff.closeWindow();
      }} else if (isLiffReady && !liff.isInClient()) {{
        log('外部ブラウザで実行中 - LINEアプリへリダイレクト');
        // 外部ブラウザの場合
        window.location.href = 'https://line.me/R/ti/p/@' + (cfg.LINE_BASIC_ID || '487urklv');
      }} else {{
        log('LIFF SDKが利用できない - フォールバック処理');
        // フォールバック
        if (window.close) {{
          window.close();
        }} else {{
          window.location.href = 'https://line.me/R/ti/p/@' + (cfg.LINE_BASIC_ID || '487urklv');
        }}
      }}
      
    }} catch (error) {{
      console.error('画面を閉じる処理でエラー:', error);
      log('画面を閉じる処理でエラーが発生 - フォールバック実行');
      
      // 最終フォールバック
      try {{
        window.location.href = 'https://line.me/R/ti/p/@' + (cfg.LINE_BASIC_ID || '487urklv');
      }} catch (e) {{
        log('フォールバック処理も失敗しました');
      }}
    }}
  }}
  
  // 初期化実行
  log('LIFF初期化を開始します...');
  initLiff().catch(error => {{
    console.error('初期化で予期しないエラー:', error);
    showError('初期化で予期しないエラーが発生しました');
  }});
  
}})();
</script>
</body></html>"""
    
    return HTMLResponse(html)

@router.get("/liff/ping")
def liff_ping():
    return {"ok": True}