# api/routers/financial_api.py
# 資金計画LIFF・API統合実装

import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from api.routers.line_bot_financial_planner import (
    FinancialPlanInput, 
    FinancialCalculationEngine,
    FinancialPlanResult
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/financial", tags=["financial-planning"])

# ==============================================================================
# リクエストモデル
# ==============================================================================
class FinancialCalculationRequest(BaseModel):
    annual_income: Optional[int] = None  # 円単位
    monthly_payment: Optional[int] = None  # 円単位
    loan_period: Optional[int] = None  # 年
    family_composition: Optional[str] = None
    other_expenses: Optional[int] = None  # 円単位

class LiffPageRequest(BaseModel):
    liff_id: str
    user_id: Optional[str] = None

# 計算エンジンインスタンス
calculation_engine = FinancialCalculationEngine()

# ==============================================================================
# LIFF資金計画ページ
# ==============================================================================
@router.get("/liff-page")
async def get_financial_liff_page():
    """資金計画LIFF ページ（HTML）"""
    
    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI資金診断 - キノエデザイン</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 16px;
        }
        
        .container {
            max-width: 420px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 12px 48px rgba(0,0,0,0.15);
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 24px;
            text-align: center;
        }
        
        .title {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 8px;
        }
        
        .subtitle {
            font-size: 14px;
            opacity: 0.9;
            line-height: 1.4;
        }
        
        .progress-container {
            padding: 20px 24px 0;
        }
        
        .progress-label {
            font-size: 14px;
            color: #666;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #f0f0f0;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            width: 0%;
        }
        
        .form-container {
            padding: 24px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .label {
            display: block;
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
            font-size: 15px;
        }
        
        .required {
            color: #e74c3c;
            font-size: 12px;
        }
        
        .input, .select {
            width: 100%;
            padding: 14px 16px;
            border: 2px solid #eee;
            border-radius: 12px;
            font-size: 16px;
            transition: border-color 0.2s ease;
        }
        
        .input:focus, .select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .input-hint {
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }
        
        .btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 24px;
            transition: transform 0.2s ease;
        }
        
        .btn:hover {
            transform: translateY(-1px);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .result {
            background: #f8f9fa;
            padding: 24px;
            margin-top: 24px;
            border-radius: 12px;
            display: none;
            border-left: 4px solid #667eea;
        }
        
        .result-title {
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin-bottom: 16px;
        }
        
        .result-item {
            margin-bottom: 12px;
            padding: 12px;
            background: white;
            border-radius: 8px;
        }
        
        .result-label {
            font-weight: 600;
            color: #667eea;
        }
        
        .result-value {
            font-size: 18px;
            font-weight: bold;
            color: #333;
        }
        
        .privacy-notice {
            font-size: 11px;
            color: #666;
            text-align: center;
            padding: 16px 24px;
            line-height: 1.4;
            background: #f8f9fa;
            border-top: 1px solid #eee;
        }
        
        .privacy-notice a {
            color: #667eea;
            text-decoration: none;
        }
        
        .privacy-notice a:hover {
            text-decoration: underline;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
        }
        
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 16px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error-message {
            background: #ffe6e6;
            color: #d32f2f;
            padding: 12px 16px;
            border-radius: 8px;
            margin: 16px 0;
            font-size: 14px;
            display: none;
        }
        
        .success-message {
            background: #e8f5e8;
            color: #2e7d32;
            padding: 12px 16px;
            border-radius: 8px;
            margin: 16px 0;
            font-size: 14px;
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">💰 AI資金診断</div>
            <div class="subtitle">
                匿名で利用可能・回答内容は保存されません<br>
                算出される金額は試算（概算）です
            </div>
        </div>
        
        <div class="progress-container">
            <div class="progress-label">
                <span>入力進捗</span>
                <span id="progressText">0%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="progressBar"></div>
            </div>
        </div>
        
        <div class="form-container">
            <div id="errorMessage" class="error-message"></div>
            <div id="successMessage" class="success-message"></div>
            
            <form id="financialForm">
                <div class="form-group">
                    <label class="label">
                        年収（概算可）<span class="required">*</span>
                    </label>
                    <input 
                        type="number" 
                        class="input" 
                        id="annualIncome" 
                        placeholder="例：600"
                        min="100"
                        max="2000"
                    >
                    <div class="input-hint">万円単位で入力してください</div>
                </div>
                
                <div class="form-group">
                    <label class="label">
                        毎月のご希望返済額<span class="required">*</span>
                    </label>
                    <input 
                        type="number" 
                        class="input" 
                        id="monthlyPayment" 
                        placeholder="例：8"
                        min="3"
                        max="50"
                    >
                    <div class="input-hint">万円単位で入力してください</div>
                </div>
                
                <div class="form-group">
                    <label class="label">
                        住宅ローンのご希望借入期間<span class="required">*</span>
                    </label>
                    <select class="select" id="loanPeriod">
                        <option value="">選択してください</option>
                        <option value="15">15年</option>
                        <option value="20">20年</option>
                        <option value="25">25年</option>
                        <option value="30">30年</option>
                        <option value="35">35年</option>
                        <option value="40">40年</option>
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
                    <input 
                        type="number" 
                        class="input" 
                        id="otherExpenses" 
                        placeholder="例：3（車ローンなど）、なければ0"
                        min="0"
                        max="30"
                        value="0"
                    >
                    <div class="input-hint">万円単位で入力してください（0でも構いません）</div>
                </div>
                
                <button type="submit" class="btn" id="calculateBtn">
                    💰 概算結果を計算
                </button>
            </form>
            
            <div class="loading" id="loadingArea">
                <div class="spinner"></div>
                <div>計算中です...</div>
            </div>
            
            <div class="result" id="resultArea">
                <div class="result-title">✅ 概算結果</div>
                <div id="calculationResult"></div>
                <button class="btn" id="sendToLineBtn" style="margin-top: 16px;">
                    📱 LINEに結果を送信
                </button>
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
        let liffInitialized = false;
        let liffUserProfile = null;
        let calculationResult = null;
        
        // LIFF初期化
        liff.init({
            liffId: 'YOUR_LIFF_ID_HERE'  // 実際のLIFF IDに置き換えてください
        }).then(() => {
            console.log('✅ LIFF初期化成功');
            liffInitialized = true;
            
            // ユーザープロフィール取得
            if (liff.isLoggedIn()) {
                liff.getProfile().then(profile => {
                    liffUserProfile = profile;
                    console.log('✅ ユーザープロフィール取得成功:', profile.displayName);
                }).catch(err => {
                    console.warn('⚠️ プロフィール取得失敗:', err);
                });
            }
        }).catch((err) => {
            console.error('❌ LIFF初期化失敗:', err);
            showError('LIFF の初期化に失敗しました。LINEアプリから再度お試しください。');
        });
        
        // プログレスバー更新
        function updateProgress() {
            const requiredInputs = ['annualIncome', 'monthlyPayment', 'loanPeriod'];
            const allInputs = ['annualIncome', 'monthlyPayment', 'loanPeriod', 'familyComposition', 'otherExpenses'];
            
            let filledRequired = 0;
            let filledAll = 0;
            
            requiredInputs.forEach(id => {
                const input = document.getElementById(id);
                if (input && input.value.trim() !== '') {
                    filledRequired++;
                }
            });
            
            allInputs.forEach(id => {
                const input = document.getElementById(id);
                if (input && input.value.trim() !== '') {
                    filledAll++;
                }
            });
            
            const progress = (filledAll / allInputs.length) * 100;
            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            
            progressBar.style.width = progress + '%';
            progressText.textContent = Math.round(progress) + '%';
            
            // 計算ボタンの有効/無効
            const calculateBtn = document.getElementById('calculateBtn');
            const canCalculate = filledRequired === requiredInputs.length;
            calculateBtn.disabled = !canCalculate;
            
            if (canCalculate) {
                calculateBtn.textContent = '💰 概算結果を計算';
                calculateBtn.style.opacity = '1';
            } else {
                calculateBtn.textContent = `💰 概算結果を計算 (必須項目 ${filledRequired}/${requiredInputs.length})`;
                calculateBtn.style.opacity = '0.7';
            }
        }
        
        // 入力変更監視
        document.addEventListener('input', updateProgress);
        document.addEventListener('change', updateProgress);
        
        // エラー表示
        function showError(message) {
            const errorElement = document.getElementById('errorMessage');
            errorElement.textContent = message;
            errorElement.style.display = 'block';
            setTimeout(() => {
                errorElement.style.display = 'none';
            }, 5000);
        }
        
        // 成功表示
        function showSuccess(message) {
            const successElement = document.getElementById('successMessage');
            successElement.textContent = message;
            successElement.style.display = 'block';
            setTimeout(() => {
                successElement.style.display = 'none';
            }, 3000);
        }
        
        // 結果表示フォーマット
        function formatResult(result) {
            return `
                <div class="result-item">
                    <div class="result-label">💰 買える金額の目安（総予算）</div>
                    <div class="result-value">約${result.affordable_budget_min.toLocaleString()}万〜${result.affordable_budget_max.toLocaleString()}万円</div>
                    <div style="font-size: 12px; color: #666; margin-top: 4px;">この範囲で探すと、むりが出にくい目安です</div>
                </div>
                
                <div class="result-item">
                    <div class="result-label">💳 毎月の支払いの目安（ローン返済）</div>
                    <div class="result-value">約${result.monthly_payment_suggestion.toLocaleString()}円</div>
                    <div style="font-size: 12px; color: #666; margin-top: 4px;">いまの生活と両立しやすい金額の目安です</div>
                </div>
                
                <div class="result-item">
                    <div class="result-label">📊 借りられる上限の目安（ローン上限）</div>
                    <div class="result-value">最大${result.max_loan_amount.toLocaleString()}万円</div>
                    <div style="font-size: 12px; color: #666; margin-top: 4px;">これ以上だと負担が大きくなる可能性があります</div>
                </div>
                
                <div style="margin-top: 16px; padding: 12px; background: #fff3cd; border-radius: 8px; font-size: 13px; color: #856404;">
                    ※金利や諸費用、物件条件によって前後します。詳しい金額はスタッフがご案内します。
                </div>
            `;
        }
        
        // フォーム送信処理
        document.getElementById('financialForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = {
                annual_income: parseInt(document.getElementById('annualIncome').value) * 10000 || null,
                monthly_payment: parseInt(document.getElementById('monthlyPayment').value) * 10000 || null,
                loan_period: parseInt(document.getElementById('loanPeriod').value) || null,
                family_composition: document.getElementById('familyComposition').value || null,
                other_expenses: parseInt(document.getElementById('otherExpenses').value || 0) * 10000
            };
            
            // 必須項目チェック
            if (!formData.annual_income || !formData.monthly_payment || !formData.loan_period) {
                showError('年収、毎月の返済希望額、借入期間は必須項目です。');
                return;
            }
            
            // UI状態変更
            const calculateBtn = document.getElementById('calculateBtn');
            const loadingArea = document.getElementById('loadingArea');
            const resultArea = document.getElementById('resultArea');
            
            calculateBtn.style.display = 'none';
            loadingArea.style.display = 'block';
            resultArea.style.display = 'none';
            
            try {
                // API呼び出し
                const response = await fetch('/financial/calculate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(formData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    // 結果表示
                    document.getElementById('calculationResult').innerHTML = formatResult(result.calculation);
                    resultArea.style.display = 'block';
                    calculationResult = result;
                    
                    showSuccess('計算が完了しました！');
                    
                } else {
                    throw new Error(result.error || '計算中にエラーが発生しました');
                }
                
            } catch (error) {
                console.error('❌ API呼び出しエラー:', error);
                showError('計算中にエラーが発生しました。再度お試しください。');
                
                // ボタンを復旧
                calculateBtn.style.display = 'block';
                calculateBtn.disabled = false;
            }
            
            loadingArea.style.display = 'none';
        });
        
        // LINEに送信ボタン
        document.getElementById('sendToLineBtn').addEventListener('click', async () => {
            if (!liffInitialized) {
                showError('LINEアプリから開いてください。');
                return;
            }
            
            if (!calculationResult) {
                showError('計算結果がありません。');
                return;
            }
            
            try {
                // LINEメッセージとして送信
                const lineMessage = calculationResult.line_message;
                
                if (liff.isInClient()) {
                    await liff.sendMessages([{
                        type: 'text',
                        text: lineMessage
                    }]);
                    
                    showSuccess('LINEに結果を送信しました！');
                    
                    // 3秒後にウィンドウを閉じる
                    setTimeout(() => {
                        liff.closeWindow();
                    }, 3000);
                    
                } else {
                    // ブラウザの場合はクリップボードにコピー
                    await navigator.clipboard.writeText(lineMessage);
                    showSuccess('結果をクリップボードにコピーしました！');
                }
                
            } catch (error) {
                console.error('❌ LINE送信エラー:', error);
                showError('送信中にエラーが発生しました。');
            }
        });
        
        // 初期プログレス更新
        setTimeout(updateProgress, 100);
    </script>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)

# ==============================================================================
# 資金計算API
# ==============================================================================
@router.post("/calculate")
async def calculate_financial_plan(request: FinancialCalculationRequest):
    """資金計画計算API"""
    try:
        # 入力データ変換
        input_data = FinancialPlanInput(
            user_id="liff_user",  # LIFF用仮ID
            annual_income=request.annual_income,
            monthly_payment=request.monthly_payment,
            loan_period=request.loan_period,
            family_composition=request.family_composition,
            other_expenses=request.other_expenses
        )
        
        # 必須項目チェック
        if not all([input_data.annual_income, input_data.monthly_payment, input_data.loan_period]):
            raise HTTPException(
                status_code=400, 
                detail="年収、毎月の返済希望額、借入期間は必須です"
            )
        
        # 計算実行
        calculation_result = calculation_engine.calculate_financial_plan(input_data)
        
        # LINE用メッセージ生成
        line_message = calculation_result.format_line_response()
        
        return {
            "success": True,
            "calculation": {
                "affordable_budget_min": calculation_result.affordable_budget_min,
                "affordable_budget_max": calculation_result.affordable_budget_max,
                "monthly_payment_suggestion": calculation_result.monthly_payment_suggestion,
                "max_loan_amount": calculation_result.max_loan_amount,
                "down_payment_suggestion": calculation_result.down_payment_suggestion,
                "total_interest": calculation_result.total_interest,
                "risk_level": calculation_result.risk_level
            },
            "line_message": line_message,
            "input_data": input_data.to_dict(),
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Financial calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"計算中にエラーが発生しました: {str(e)}")

# ==============================================================================
# 資金計画設定・管理エンドポイント
# ==============================================================================
@router.get("/settings")
async def get_financial_settings():
    """資金計画設定取得"""
    return {
        "calculation_parameters": {
            "default_interest_rate": calculation_engine.default_interest_rate,
            "default_down_payment_rate": calculation_engine.default_down_payment_rate,
            "income_multiplier_safe": calculation_engine.income_multiplier_safe,
            "income_multiplier_max": calculation_engine.income_multiplier_max,
            "debt_to_income_ratio": calculation_engine.debt_to_income_ratio
        },
        "validation_rules": {
            "annual_income_range": "100万円〜2000万円",
            "monthly_payment_range": "3万円〜50万円",
            "loan_period_range": "15年〜40年",
            "other_expenses_range": "0円〜30万円"
        },
        "features": [
            "Anonymous Calculation",
            "No Data Storage",
            "Real-time Validation",
            "Risk Assessment",
            "LINE Integration",
            "LIFF Support"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/settings/update")
async def update_financial_settings(
    interest_rate: Optional[float] = None,
    down_payment_rate: Optional[float] = None,
    income_multiplier_safe: Optional[float] = None,
    income_multiplier_max: Optional[float] = None,
    debt_to_income_ratio: Optional[float] = None
):
    """資金計画設定更新"""
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
        updates["debt_to_income_ratio"] = debt_to_income_ratio
    
    return {
        "success": True,
        "updates": updates,
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# テスト・デバッグエンドポイント
# ==============================================================================
@router.post("/test-calculation")
async def test_financial_calculation():
    """資金計算テスト"""
    test_data = FinancialCalculationRequest(
        annual_income=6000000,  # 600万円
        monthly_payment=80000,   # 8万円
        loan_period=35,          # 35年
        family_composition="大人2名・お子さま1名",
        other_expenses=30000     # 3万円
    )
    
    try:
        result = await calculate_financial_plan(test_data)
        return {
            "test_success": True,
            "test_data": test_data.dict(),
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "test_success": False,
            "error": str(e),
            "test_data": test_data.dict(),
            "timestamp": datetime.now().isoformat()
        }

@router.get("/health")
async def financial_health_check():
    """資金計画機能ヘルスチェック"""
    return {
        "status": "healthy",
        "components": {
            "calculation_engine": "ok",
            "liff_page": "ok", 
            "api_endpoints": "ok",
            "line_integration": "ok"
        },
        "features": [
            "Financial Calculation Engine",
            "LIFF Page Integration",
            "Anonymous Processing",
            "Real-time Validation",
            "Risk Assessment",
            "LINE Message Integration"
        ],
        "timestamp": datetime.now().isoformat()
    }