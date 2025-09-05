# api/routers/liff_pages.py (修正版 - エラーハンドリング強化)
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
        "LIFF_ID": os.getenv("LIFF_ID", "2007887876-vMNe74eX"),
        "CONSENT_URL": os.getenv("LIFF_CONSENT_URL", ""),
        "LINE_BASIC_ID": os.getenv("LINE_BASIC_ID", "487urklv").lstrip("@"),
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
  .success{background:#e6ffe6;padding:10px;margin-top:10px;color:#00a152;border-radius:4px;display:none}
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
  <div id="success" class="success"></div>
</div>

<script>
window.__CFG__ = {cfg_json};

(function(){{
  const debugEl = document.getElementById('debug');
  const errorEl = document.getElementById('error');
  const successEl = document.getElementById('success');
  
  function log(msg, level = 'info') {{ 
    console.log(`[LIFF] ${{level.toUpperCase()}}: ${{msg}}`); 
    debugEl.textContent = msg; 
  }}
  
  function showError(msg) {{ 
    console.error(`[LIFF] ERROR: ${{msg}}`);
    errorEl.textContent = msg; 
    errorEl.style.display = 'block';
    successEl.style.display = 'none';
  }}
  
  function showSuccess(msg) {{
    console.info(`[LIFF] SUCCESS: ${{msg}}`);
    successEl.textContent = msg;
    successEl.style.display = 'block';
    errorEl.style.display = 'none';
  }}
  
  const cfg = window.__CFG__ || {{}};
  const API_BASE = cfg.API_BASE || location.origin;
  const LIFF_ID = cfg.LIFF_ID || '2007887876-vMNe74eX';
  const LINE_BASIC_ID = cfg.LINE_BASIC_ID || '487urklv';
  
  let userToken = '';
  let isLiffReady = false;
  let fallbackUserId = '';
  let initRetryCount = 0;
  const MAX_RETRY = 3;
  
  // URLパラメータからuser_tokenを取得（フォールバック）
  function getTokenFromURL() {{
    const qs = new URLSearchParams(location.search);
    return qs.get('user_token') || '';
  }}
  
  // LIFF SDK初期化（リトライ機能付き）
  async function initLiff() {{
    try {{
      log('LIFF SDK初期化中...');
      
      // LIFF存在確認
      if (typeof liff === 'undefined') {{
        throw new Error('LIFF SDK が読み込まれていません。CSPやネットワークを確認してください。');
      }}
      
      // LIFF初期化（タイムアウト付き）
      const initPromise = liff.init({{ liffId: LIFF_ID }});
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('LIFF初期化がタイムアウトしました')), 10000)
      );
      
      await Promise.race([initPromise, timeoutPromise]);
      log('LIFF SDK初期化完了');
      isLiffReady = true;
      
      // ログイン状態確認
      if (liff.isLoggedIn()) {{
        log('ユーザーはログイン済み');
        
        // アクセストークン取得
        try {{
          userToken = liff.getAccessToken();
          log(`アクセストークン取得: ${{userToken ? '成功' : '失敗'}}`);
        }} catch (tokenError) {{
          log(`アクセストークン取得エラー: ${{tokenError.message}}`, 'warn');
        }}
        
        // ユーザーID取得（代替手段）
        try {{
          const profile = await liff.getProfile();
          fallbackUserId = profile.userId;
          log(`ユーザーID取得: ${{fallbackUserId ? '成功' : '失敗'}}`);
          
          // トークンが取得できない場合はユーザーIDを使用
          if (!userToken && fallbackUserId) {{
            userToken = fallbackUserId;
            log('フォールバック: ユーザーIDをトークンとして使用');
          }}
        }} catch (profileError) {{
          log(`プロフィール取得エラー: ${{profileError.message}}`, 'warn');
        }}
      }} else {{
        log('ユーザーがログインしていません');
        
        // 外部ブラウザでログインが必要な場合
        if (!liff.isInClient()) {{
          log('外部ブラウザ環境を検出');
          showError('LINEアプリでこのページを開いてください。');
          showManualLoginButton();
          return;
        }}
      }}
      
      // URLパラメータからも取得を試行（最終フォールバック）
      const urlToken = getTokenFromURL();
      if (!userToken && urlToken) {{
        userToken = urlToken;
        log('URLパラメータからトークン取得');
      }}
      
      // 最終確認
      if (!userToken) {{
        throw new Error('ユーザートークンを取得できませんでした');
      }}
      
      log(`トークン取得完了: ${{userToken.substring(0, 10)}}...`);
      updateUI();
      
    }} catch (error) {{
      console.error('LIFF初期化エラー:', error);
      log(`LIFF初期化エラー: ${{error.message}}`, 'error');
      
      // リトライロジック
      if (initRetryCount < MAX_RETRY) {{
        initRetryCount++;
        log(`リトライ ${{initRetryCount}}/${{MAX_RETRY}} を実行中...`);
        setTimeout(() => initLiff(), 2000);
        return;
      }}
      
      // フォールバック: URLパラメータから取得
      const urlToken = getTokenFromURL();
      if (urlToken) {{
        userToken = urlToken;
        log('緊急フォールバック: URLパラメータからトークン取得');
        updateUI();
      }} else {{
        showError(`LIFF初期化に失敗しました: ${{error.message}}`);
        showManualLoginButton();
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
      
      log(`状態: チェック ${{allChecked ? 'OK' : 'NG'}} / トークン ${{hasToken ? 'OK' : 'NG'}} / 送信可能 ${{canSubmit ? 'YES' : 'NO'}}`);
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
        liff_os: isLiffReady ? (liff.isInClient() ? 'liff-app' : 'liff-browser') : 'unknown',
        meta: {{
          source: 'liff_consent',
          liff_id: LIFF_ID,
          timestamp: new Date().toISOString(),
          user_agent: navigator.userAgent,
          retry_count: initRetryCount
        }}
      }};
      
      // 1. 同意保存API呼び出し（タイムアウト付き）
      log('同意保存API呼び出し中...');
      const saveUrl = `${{API_BASE}}/consent/save?user_token=${{encodeURIComponent(userToken)}}&scope=ai`;
      
      const controller = new AbortController();
      setTimeout(() => controller.abort(), 15000); // 15秒タイムアウト
      
      const saveResponse = await fetch(saveUrl, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Token': userToken,
          'X-LIFF-ID': LIFF_ID
        }},
        body: JSON.stringify(consentData),
        signal: controller.signal,
        keepalive: true
      }});
      
      log(`同意保存レスポンス: ${{saveResponse.status}}`);
      
      if (!saveResponse.ok) {{
        const errorText = await saveResponse.text();
        throw new Error(`同意保存失敗: ${{saveResponse.status}} - ${{errorText}}`);
      }}
      
      const saveResult = await saveResponse.json();
      log('同意保存完了');
      
      // 2. LINE通知API呼び出し
      log('LINE通知API呼び出し中...');
      const afterConsentUrl = `${{API_BASE}}/line/after-consent`;
      
      const afterController = new AbortController();
      setTimeout(() => afterController.abort(), 10000); // 10秒タイムアウト
      
      const afterResponse = await fetch(afterConsentUrl, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-User-Id': userToken,
          'X-LIFF-ID': LIFF_ID
        }},
        body: JSON.stringify({{
          user_token: userToken,
          source: 'liff_consent',
          consent_id: saveResult.consent_id || 'unknown',
          meta: {{ liff_id: LIFF_ID }}
        }}),
        signal: afterController.signal,
        keepalive: true
      }});
      
      log(`LINE通知レスポンス: ${{afterResponse.status}}`);
      
      if (!afterResponse.ok) {{
        console.warn('LINE通知失敗:', afterResponse.status, await afterResponse.text());
        log('LINE通知でエラーが発生しましたが、処理を続行します', 'warn');
      }} else {{
        const afterResult = await afterResponse.json();
        log('LINE通知完了');
      }}
      
      // 3. 完了メッセージ表示
      btn.textContent = '完了！';
      btn.style.background = '#28a745';
      showSuccess('同意処理が完了しました。LINEに戻ります...');
      log('同意処理が完了しました。LINEに戻ります...');
      
      // 4. 画面を閉じる
      setTimeout(() => {{
        closeLiffWindow();
      }}, 2000);
      
    }} catch (error) {{
      console.error('同意処理エラー:', error);
      showError(`エラーが発生しました: ${{error.message}}`);
      btn.disabled = false;
      btn.textContent = '同意して開始';
      log(`エラーのため処理を中断しました: ${{error.message}}`, 'error');
    }}
  }}
  
  function closeLiffWindow() {{
    try {{
      log('画面を閉じる処理を開始...');
      
      if (isLiffReady && liff.isInClient()) {{
        log('LIFF環境内 - closeWindow実行');
        liff.closeWindow();
      }} else if (isLiffReady && !liff.isInClient()) {{
        log('外部ブラウザ - LINEアプリへリダイレクト');
        window.location.href = `https://line.me/R/ti/p/@${{LINE_BASIC_ID}}`;
      }} else {{
        log('LIFF未対応 - フォールバック実行');
        if (window.close) {{
          window.close();
        }} else {{
          window.location.href = `https://line.me/R/ti/p/@${{LINE_BASIC_ID}}`;
        }}
      }}
      
    }} catch (error) {{
      console.error('画面を閉じる処理でエラー:', error);
      log('最終フォールバック実行', 'warn');
      try {{
        window.location.href = `https://line.me/R/ti/p/@${{LINE_BASIC_ID}}`;
      }} catch (e) {{
        log('すべての閉じる処理が失敗しました', 'error');
      }}
    }}
  }}
  
  // 手動ログインボタン（必要に応じて表示）
  function showManualLoginButton() {{
    const existingBtn = document.getElementById('manual-login-btn');
    if (existingBtn) return;
    
    const btn = document.createElement('button');
    btn.id = 'manual-login-btn';
    btn.textContent = 'LINEログイン';
    btn.className = 'btn enabled';
    btn.style.marginTop = '10px';
    btn.onclick = () => {{
      if (isLiffReady) {{
        liff.login();
      }} else {{
        showError('LIFF SDKが利用できません。LINEアプリでページを開き直してください。');
      }}
    }};
    document.querySelector('.wrap').appendChild(btn);
  }}
  
  // 初期化実行
  log('システム初期化開始...');
  
  // DOMContentLoaded後に実行（確実性向上）
  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initLiff);
  }} else {{
    initLiff();
  }}
  
}})();
</script>
</body></html>"""
    
    return HTMLResponse(html)

@router.get("/liff/ping")
def liff_ping():
    return {"ok": True}