# api/routers/financial_api.py
# 資金計画 LIFF・API 統合（LLM要約オプション付き）

from __future__ import annotations

import logging
import os
import importlib
from datetime import datetime
from typing import Any, Dict, Optional  # 型は安全側に

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/financial", tags=["financial-planning"])

# =============================================================================
# 入力モデル（フロントは 万円 → API では 円を想定）
# =============================================================================
class FinancialCalculationRequest(BaseModel):
    annual_income: Optional[int] = Field(None, description="年収（円）")
    monthly_payment: Optional[int] = Field(None, description="毎月返済（円）")
    loan_period: Optional[int] = Field(None, description="借入年数（年）")
    family_composition: Optional[str] = None
    other_expenses: Optional[int] = Field(None, description="その他大きな負担（円）")

# LIFF ページ（開くユーザー情報は LIFF 側 JS で取得）
class LiffPageRequest(BaseModel):
    liff_id: str
    user_id: Optional[str] = None


# =============================================================================
# 既存の資金計画エンジンの解決（場所差異に強い）
# =============================================================================
def _resolve_financial_engine():
    """
    FinancialPlanInput / FinancialCalculationEngine / FinancialPlanResult を解決して返す。
    既定: api.routers.line_bot_financial_planner
    フォールバック: line_bot_financial_planner
    """
    candidates = [
        "api.routers.line_bot_financial_planner",
        "line_bot_financial_planner",
    ]
    last_err = None
    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
            FPI = getattr(mod, "FinancialPlanInput")
            FCE = getattr(mod, "FinancialCalculationEngine")
            FPR = getattr(mod, "FinancialPlanResult")
            return FPI, FCE, FPR
        except Exception as e:
            last_err = e
    raise ImportError(f"Financial engine not found: {last_err}")

FinancialPlanInput, FinancialCalculationEngine, FinancialPlanResult = _resolve_financial_engine()
calculation_engine = FinancialCalculationEngine()


# =============================================================================
# LLM（任意）— ChatGPT要約（出典や参考は出さない）
# =============================================================================
def _get_llm_instance():
    """
    優先: llm/llm_runner.get_cached_llm_instance()
    予備: llm_runner.get_cached_llm_instance()
    最終: ChatOpenAI(model_name=ENV or gpt-3.5-turbo)
    """
    try:
        mod = importlib.import_module("llm.llm_runner")
        fn = getattr(mod, "get_cached_llm_instance", None)
        if callable(fn):
            return fn()
        alt = getattr(mod, "load_llm", None)
        if callable(alt):
            res = alt()
            return res[0] if isinstance(res, tuple) else res
    except Exception:
        pass

    try:
        mod = importlib.import_module("llm_runner")
        fn = getattr(mod, "get_cached_llm_instance", None)
        if callable(fn):
            return fn()
    except Exception:
        pass

    try:
        from langchain_openai import ChatOpenAI
        model = os.getenv("FINANCIAL_MODEL", "gpt-3.5-turbo")
        return ChatOpenAI(model_name=model, temperature=0)
    except Exception as e:
        logger.warning(f"LLM fallback failed: {e}")
        return None


def _summarize_with_llm(payload: Dict[str, Any]) -> Optional[str]:
    """
    数値結果に基づいた自然文要約を生成。出典/参考は一切出さない。
    """
    if os.getenv("FINANCIAL_LLM_SUMMARY", "true").lower() != "true":
        return None

    llm = _get_llm_instance()
    if not llm:
        return None

    p = f"""
あなたは住宅資金計画のAIアシスタントです。以下の試算結果をもとに、日本語で利用者向けの簡潔な説明文を作成してください。
- 数値は与えられた範囲をそのまま使い、過度な断定は避ける
- 出典や参考・資料などの文言は一切出さない
- 3〜5行の短い段落または箇条書きで丁寧に
- 最後に「次の一歩」の提案を1つ書く

[試算結果]
- 購入予算の目安（総額）: 約{payload.get('affordable_budget_min')}万〜{payload.get('affordable_budget_max')}万円
- 毎月の支払い目安: 約{payload.get('monthly_payment_suggestion')}円
- 借入上限の目安: 最大{payload.get('max_loan_amount')}万円
- 頭金の目安: 約{payload.get('down_payment_suggestion')}万円
- 総利息の概算: 約{payload.get('total_interest')}万円
- リスクレベル: {payload.get('risk_level')}
- 家族構成: {payload.get('family_composition')}
- 借入年数: {payload.get('loan_period')}年
- その他の負担（例：車ローン等）: {payload.get('other_expenses')}円
    """.strip()

    try:
        if hasattr(llm, "invoke"):
            out = llm.invoke(p)
            return getattr(out, "content", str(out))
        if hasattr(llm, "predict"):
            return llm.predict(p)
        return str(llm(p))
    except Exception as e:
        logger.debug(f"LLM summary error: {e}")
        return None


def _strip_citation_like(text: str) -> str:
    """「出典」「参考」「資料」など、UIに出したくない語を削除（行単位）。"""
    if not text:
        return text
    import re
    txt = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    txt = re.sub(r"【出典】[\s\S]*$", "", txt, flags=re.MULTILINE)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


# =============================================================================
# LIFF 資金計画ページ（f文字列を使わず、置換でLIFF IDを注入）
# =============================================================================
@router.get("/liff-page")
async def get_financial_liff_page():
    liff_id = os.getenv("LIFF_ID_FINANCIAL", "YOUR_LIFF_ID_HERE")
    html = LIFF_HTML_TEMPLATE.replace("__LIFF_ID__", liff_id)
    return HTMLResponse(content=html)


# --- ここから下はプレーン文字列。波カッコはそのままでOK（f文字列ではない） ---
LIFF_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI資金診断 - キノエデザイン</title>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:16px}
.container{max-width:420px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.15)}
.header{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:24px;text-align:center}
.title{font-size:24px;font-weight:bold;margin-bottom:8px}.subtitle{font-size:14px;opacity:.9;line-height:1.4}
.progress-container{padding:20px 24px 0}.progress-label{font-size:14px;color:#666;margin-bottom:8px;display:flex;justify-content:space-between}
.progress-bar{width:100%;height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden}.progress-fill{height:100%;background:linear-gradient(90deg,#667eea 0%,#764ba2 100%);transition:width .3s ease;width:0%}
.form-container{padding:24px}.form-group{margin-bottom:20px}.label{display:block;font-weight:600;color:#333;margin-bottom:8px;font-size:15px}
.required{color:#e74c3c;font-size:12px}.input,.select{width:100%;padding:14px 16px;border:2px solid #eee;border-radius:12px;font-size:16px;transition:border-color .2s ease}
.input:focus,.select:focus{outline:none;border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,.1)}.input-hint{font-size:12px;color:#888;margin-top:4px}
.btn{width:100%;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:bold;cursor:pointer;margin-top:24px;transition:transform .2s ease}
.btn:hover{transform:translateY(-1px)}.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.result{background:#f8f9fa;padding:24px;margin-top:24px;border-radius:12px;display:none;border-left:4px solid #667eea}
.result-title{font-size:18px;font-weight:bold;color:#333;margin-bottom:16px}.result-item{margin-bottom:12px;padding:12px;background:#fff;border-radius:8px}
.result-label{font-weight:600;color:#667eea}.result-value{font-size:18px;font-weight:bold;color:#333}
.privacy-notice{font-size:11px;color:#666;text-align:center;padding:16px 24px;line-height:1.4;background:#f8f9fa;border-top:1px solid #eee}
.privacy-notice a{color:#667eea;text-decoration:none}.privacy-notice a:hover{text-decoration:underline}
.loading{display:none;text-align:center;padding:20px}.spinner{border:3px solid #f3f3f3;border-top:3px solid #667eea;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}.error-message{background:#ffe6e6;color:#d32f2f;padding:12px 16px;border-radius:8px;margin:16px 0;font-size:14px;display:none}
.success-message{background:#e8f5e8;color:#2e7d32;padding:12px 16px;border-radius:8px;margin:16px 0;font-size:14px;display:none}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="title">💰 AI資金診断</div>
    <div class="subtitle">匿名で利用可能・回答内容は保存されません<br>算出される金額は試算（概算）です</div>
  </div>

  <div class="progress-container">
    <div class="progress-label"><span>入力進捗</span><span id="progressText">0%</span></div>
    <div class="progress-bar"><div class="progress-fill" id="progressBar"></div></div>
  </div>

  <div class="form-container">
    <div id="errorMessage" class="error-message"></div>
    <div id="successMessage" class="success-message"></div>

    <form id="financialForm">
      <div class="form-group">
        <label class="label">年収（概算可）<span class="required">*</span></label>
        <input type="number" class="input" id="annualIncome" placeholder="例：600" min="100" max="2000">
        <div class="input-hint">万円単位で入力してください</div>
      </div>

      <div class="form-group">
        <label class="label">毎月のご希望返済額<span class="required">*</span></label>
        <input type="number" class="input" id="monthlyPayment" placeholder="例：8" min="3" max="50">
        <div class="input-hint">万円単位で入力してください</div>
      </div>

      <div class="form-group">
        <label class="label">住宅ローンのご希望借入期間<span class="required">*</span></label>
        <select class="select" id="loanPeriod">
          <option value="">選択してください</option>
          <option value="15">15年</option><option value="20">20年</option><option value="25">25年</option>
          <option value="30">30年</option><option value="35">35年</option><option value="40">40年</option>
        </select>
      </div>

      <div class="form-group">
        <label class="label">ご家族構成</label>
        <select class="select" id="familyComposition">
          <option value="">選択してください</option>
          <option value="大人1名">大人1名（単身）</option>
          <option value="大人2名">大人2名（夫婦）</option>
          <option value="大人2名・お子さま1名">大人2名・お子さま1名</option>
          <option value="大人2名・お子さま2名">大人2名・お子さま2名</option>
          <option value="大人2名・お子さま3名">大人2名・お子さま3名</option>
          <option value="大人3名以上">大人3名以上</option>
        </select>
      </div>

      <div class="form-group">
        <label class="label">その他の大きなご負担</label>
        <input type="number" class="input" id="otherExpenses" placeholder="例：3（車ローンなど）、なければ0" min="0" max="30" value="0">
        <div class="input-hint">万円単位で入力してください（0でも構いません）</div>
      </div>

      <button type="submit" class="btn" id="calculateBtn">💰 概算結果を計算</button>
    </form>

    <div class="loading" id="loadingArea"><div class="spinner"></div><div>計算中です...</div></div>

    <div class="result" id="resultArea">
      <div class="result-title">✅ 概算結果</div>
      <div id="calculationResult"></div>
      <button class="btn" id="sendToLineBtn" style="margin-top:16px;">📱 LINEに結果を送信</button>
    </div>
  </div>

  <div class="privacy-notice">
    必ず以下をご確認ください：
    <a href="https://preview.studio.site/live/EjOQljz1WJ/privacy-policy" target="_blank">プライバシーポリシー</a>・
    <a href="https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service" target="_blank">利用規約</a>・
    <a href="https://preview.studio.site/live/EjOQljz1WJ/cookie" target="_blank">Cookie</a>
  </div>
</div>

<script>
let liffInitialized=false, liffUserProfile=null, calculationResult=null;

liff.init({ liffId: "__LIFF_ID__" }).then(() => {
  liffInitialized=true;
  if (liff.isLoggedIn()) {
    liff.getProfile().then(p => { liffUserProfile=p; }).catch(()=>{});
  }
}).catch(() => {
  showError('LIFF の初期化に失敗しました。LINEアプリから再度お試しください。');
});

function updateProgress(){
  const req=['annualIncome','monthlyPayment','loanPeriod'];
  const all=['annualIncome','monthlyPayment','loanPeriod','familyComposition','otherExpenses'];
  let r=0,a=0;
  req.forEach(id=>{const el=document.getElementById(id); if(el && el.value.trim()!=='') r++;});
  all.forEach(id=>{const el=document.getElementById(id); if(el && el.value.trim()!=='') a++;});
  const prog=(a/all.length)*100|0;
  document.getElementById('progressBar').style.width=prog+'%';
  document.getElementById('progressText').textContent=prog+'%';
  const btn=document.getElementById('calculateBtn');
  const ok=r===req.length; btn.disabled=!ok;
  btn.textContent= ok ? '💰 概算結果を計算' : `💰 概算結果を計算 (必須項目 ${r}/${req.length})`;
}
document.addEventListener('input', updateProgress);
document.addEventListener('change', updateProgress);

function showError(m){const e=document.getElementById('errorMessage'); e.textContent=m; e.style.display='block'; setTimeout(()=>e.style.display='none',5000);}
function showSuccess(m){const e=document.getElementById('successMessage'); e.textContent=m; e.style.display='block'; setTimeout(()=>e.style.display='none',3000);}

function formatResult(r){
  const jl = (n)=> (n||0).toLocaleString();
  return `
    <div class="result-item">
      <div class="result-label">💰 買える金額の目安（総予算）</div>
      <div class="result-value">約${jl(r.affordable_budget_min)}万〜${jl(r.affordable_budget_max)}万円</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">この範囲で探すと、むりが出にくい目安です</div>
    </div>
    <div class="result-item">
      <div class="result-label">💳 毎月の支払いの目安（ローン返済）</div>
      <div class="result-value">約${jl(r.monthly_payment_suggestion)}円</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">いまの生活と両立しやすい金額の目安です</div>
    </div>
    <div class="result-item">
      <div class="result-label">📊 借りられる上限の目安（ローン上限）</div>
      <div class="result-value">最大${jl(r.max_loan_amount)}万円</div>
      <div style="font-size:12px;color:#666;margin-top:4px;">これ以上だと負担が大きくなる可能性があります</div>
    </div>
    ${r.ai_summary ? `<div class="result-item"><div class="result-label">📝 AIからの補足</div><div style="white-space:pre-wrap;line-height:1.5">${r.ai_summary}</div></div>` : ``}
    <div style="margin-top:16px;padding:12px;background:#fff3cd;border-radius:8px;font-size:13px;color:#856404;">
      ※金利や諸費用、物件条件によって前後します。詳しい金額はスタッフがご案内します。
    </div>`;
}

document.getElementById('financialForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = {
    annual_income: parseInt(document.getElementById('annualIncome').value) * 10000 || null,
    monthly_payment: parseInt(document.getElementById('monthlyPayment').value) * 10000 || null,
    loan_period: parseInt(document.getElementById('loanPeriod').value) || null,
    family_composition: document.getElementById('familyComposition').value || null,
    other_expenses: parseInt(document.getElementById('otherExpenses').value || 0) * 10000
  };
  if (!formData.annual_income || !formData.monthly_payment || !formData.loan_period) {
    showError('年収、毎月の返済希望額、借入期間は必須項目です。'); return;
  }

  const btn=document.getElementById('calculateBtn'), load=document.getElementById('loadingArea'), res=document.getElementById('resultArea');
  btn.style.display='none'; load.style.display='block'; res.style.display='none';
  try {
    const r = await fetch('/financial/calculate', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(formData) });
    const data = await r.json();
    if (data.success) {
      document.getElementById('calculationResult').innerHTML = formatResult(data.calculation);
      res.style.display='block'; calculationResult=data;
      showSuccess('計算が完了しました！');
    } else {
      throw new Error(data.error || '計算中にエラーが発生しました');
    }
  } catch (err) {
    showError('計算中にエラーが発生しました。再度お試しください。');
    btn.style.display='block'; btn.disabled=false;
  }
  load.style.display='none';
});

document.getElementById('sendToLineBtn').addEventListener('click', async () => {
  if (!liffInitialized) { showError('LINEアプリから開いてください。'); return; }
  if (!calculationResult) { showError('計算結果がありません。'); return; }
  try {
    const lineMessage = calculationResult.line_message;
    if (liff.isInClient()) {
      await liff.sendMessages([{ type:'text', text: lineMessage }]);
      showSuccess('LINEに結果を送信しました！');
      setTimeout(()=>liff.closeWindow(), 2000);
    } else {
      await navigator.clipboard.writeText(lineMessage);
      showSuccess('結果をクリップボードにコピーしました！');
    }
  } catch (err) {
    showError('送信中にエラーが発生しました。');
  }
});

setTimeout(updateProgress, 100);
</script>
</body></html>"""


# =============================================================================
# 計算 API（数値 + LINEメッセージ + LLM サマリー）
# =============================================================================
@router.post("/calculate")
async def calculate_financial_plan(request: FinancialCalculationRequest):
    try:
        # 必須チェック
        if not request.annual_income or not request.monthly_payment or not request.loan_period:
            raise HTTPException(status_code=400, detail="年収、毎月の返済希望額、借入期間は必須です")

        # マイナス/極端値の防御
        if any(x is not None and x < 0 for x in [
            request.annual_income, request.monthly_payment, request.other_expenses
        ]):
            raise HTTPException(status_code=400, detail="金額は0以上で入力してください")

        if request.loan_period < 5 or request.loan_period > 50:
            raise HTTPException(status_code=400, detail="借入期間は5〜50年で入力してください")

        # 既存エンジンで試算
        input_data = FinancialPlanInput(
            user_id="liff_user",
            annual_income=request.annual_income,
            monthly_payment=request.monthly_payment,
            loan_period=request.loan_period,
            family_composition=request.family_composition,
            other_expenses=request.other_expenses or 0
        )

        calculation_result = calculation_engine.calculate_financial_plan(input_data)  # 型注釈を外して安全側
        line_message = calculation_result.format_line_response()

        # API レスポンス用に整形（単位に注意）
        calc_payload: Dict[str, Any] = {
            "affordable_budget_min": calculation_result.affordable_budget_min,   # 万円
            "affordable_budget_max": calculation_result.affordable_budget_max,   # 万円
            "monthly_payment_suggestion": calculation_result.monthly_payment_suggestion,  # 円
            "max_loan_amount": calculation_result.max_loan_amount,               # 万円
            "down_payment_suggestion": calculation_result.down_payment_suggestion,  # 万円
            "total_interest": calculation_result.total_interest,                 # 万円
            "risk_level": calculation_result.risk_level,
            "family_composition": request.family_composition,
            "loan_period": request.loan_period,
            "other_expenses": request.other_expenses or 0,
        }

        # LLM 要約（任意）
        ai_summary = _summarize_with_llm(calc_payload)
        if ai_summary:
            ai_summary = _strip_citation_like(ai_summary)

        return {
            "success": True,
            "calculation": {**calc_payload, "ai_summary": ai_summary},
            "line_message": line_message,
            "input_data": {
                "annual_income": request.annual_income,
                "monthly_payment": request.monthly_payment,
                "loan_period": request.loan_period,
                "family_composition": request.family_composition,
                "other_expenses": request.other_expenses or 0
            },
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Financial calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"計算中にエラーが発生しました: {str(e)}")


# =============================================================================
# 設定参照・更新・ヘルス
# =============================================================================
@router.get("/settings")
async def get_financial_settings():
    return {
        "calculation_parameters": {
            "default_interest_rate": calculation_engine.default_interest_rate,
            "default_down_payment_rate": calculation_engine.default_down_payment_rate,
            "income_multiplier_safe": calculation_engine.income_multiplier_safe,
            "income_multiplier_max": calculation_engine.income_multiplier_max,
            "debt_to_income_ratio": calculation_engine.debt_to_income_ratio,
        },
        "validation_rules": {
            "annual_income_range": "100万円〜2000万円（目安）",
            "monthly_payment_range": "3万円〜50万円（目安）",
            "loan_period_range": "5年〜50年（システム上の許容）",
            "other_expenses_range": "0円〜30万円（目安）",
        },
        "features": [
            "Anonymous Calculation",
            "No Data Storage",
            "Real-time Validation",
            "Risk Assessment",
            "LINE Integration (sendMessages)",
            "LIFF Support",
            "Optional LLM Summary",
        ],
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/settings/update")
async def update_financial_settings(
    interest_rate: Optional[float] = None,
    down_payment_rate: Optional[float] = None,
    income_multiplier_safe: Optional[float] = None,
    income_multiplier_max: Optional[float] = None,
    debt_to_income_ratio: Optional[float] = None,
):
    updates = {}
    if interest_rate is not None:
        calculation_engine.default_interest_rate = interest_rate
        updates["interest_rate"] = interest_rate
    if down_payment_rate is not None:
        calculation_engine.default_down_payment_rate = down_payment_rate
        updates["down_payment_rate"] = down_payment_rate
    if income_multiplier_safe is not None:
        calculation_engine.income_multiplier_safe = income_multiplier_safe
        updates["income_multiplier_safe"] = income_multiplier_safe
    if income_multiplier_max is not None:
        calculation_engine.income_multiplier_max = income_multiplier_max
        updates["income_multiplier_max"] = income_multiplier_max
    if debt_to_income_ratio is not None:
        calculation_engine.debt_to_income_ratio = debt_to_income_ratio

    return {"success": True, "updates": updates, "timestamp": datetime.now().isoformat()}


@router.get("/health")
async def financial_health_check():
    return {
        "status": "healthy",
        "components": {
            "calculation_engine": "ok",
            "liff_page": "ok",
            "api_endpoints": "ok",
            "line_integration": "ok",
        },
        "features": [
            "Financial Calculation Engine",
            "LIFF Page Integration",
            "Anonymous Processing",
            "Real-time Validation",
            "Risk Assessment",
            "LINE Message Integration",
            "Optional LLM Summary",
        ],
        "timestamp": datetime.now().isoformat(),
    }
