# api/routers/line_bot_financial_planner.py
# 資金計画機能統合実装（指定文面統一版）

import logging
import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
import math

logger = logging.getLogger(__name__)

# ==============================================================================
# 資金計画データモデル
# ==============================================================================
@dataclass
class FinancialPlanInput:
    """資金計画入力データ"""
    user_id: str
    annual_income: Optional[int] = None  # 年収
    monthly_payment: Optional[int] = None  # 毎月返済希望額
    loan_period: Optional[int] = None  # 借入期間（年）
    family_composition: Optional[str] = None  # 家族構成
    other_expenses: Optional[int] = None  # その他負担額
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def get_completion_rate(self) -> float:
        """入力完了率を計算"""
        filled_fields = sum([
            1 if self.annual_income else 0,
            1 if self.monthly_payment else 0,
            1 if self.loan_period else 0,
            1 if self.family_composition else 0,
            1 if self.other_expenses is not None else 0  # 0も有効な値
        ])
        return filled_fields / 5.0
    
    def get_missing_fields(self) -> List[str]:
        """未入力フィールドを取得"""
        missing = []
        if not self.annual_income: missing.append("年収")
        if not self.monthly_payment: missing.append("毎月返済希望額")
        if not self.loan_period: missing.append("借入期間")
        if not self.family_composition: missing.append("家族構成")
        if self.other_expenses is None: missing.append("その他負担")
        return missing

@dataclass
class FinancialPlanResult:
    """資金計画結果データ"""
    affordable_budget_min: int  # 購入可能金額（下限）
    affordable_budget_max: int  # 購入可能金額（上限）
    monthly_payment_suggestion: int  # 推奨月額返済
    max_loan_amount: int  # 最大借入可能額
    down_payment_suggestion: int  # 推奨頭金
    total_interest: int  # 総利息額
    risk_level: str  # リスクレベル（low/medium/high）
    
    def format_line_response(self) -> str:
        """LINE用の結果表示フォーマット"""
        return f"""✅ **資金計画 概算結果**

💰 **買える金額の目安（総予算）**
約{self.affordable_budget_min:,}万〜{self.affordable_budget_max:,}万円
→この範囲で探すと、むりが出にくい目安です。

💳 **毎月の支払いの目安（ローン返済）**
約{self.monthly_payment_suggestion:,}円
→いまの生活と両立しやすい金額の目安です。

📊 **借りられる上限の目安（ローン上限）**
最大{self.max_loan_amount:,}万円
→これ以上だと負担が大きくなる可能性があります。

※金利や諸費用、物件条件によって前後します。詳しい金額はスタッフがご案内します。

🔎 **チェック（3点）**
・**暮らしの流れ**：今の生活費＋教育/車など将来支出と両立できる？
・**使い勝手**：通勤/学校/買物など日常の移動と合う？
・**将来性**：家族構成の変化や金利の上下に耐えられる？

⚠️ **注意**（キノエデザインの前提）
**断熱・空調計画、法規/構造、地域差**で条件が変わることがあります。結果は**概算**です。

（必要なら**再計算**もOK：「頭金を＋○万円に」「35年→30年なら？」など）"""

# ==============================================================================
# 資金計画状態管理
# ==============================================================================
class FinancialPlanningStateManager:
    """資金計画状態管理クラス"""
    
    def __init__(self):
        self.user_states: Dict[str, FinancialPlanInput] = {}
        self.session_timeout = timedelta(hours=2)  # 2時間でセッション失効
    
    def start_session(self, user_id: str) -> FinancialPlanInput:
        """資金計画セッション開始"""
        # 既存セッションのクリーンアップ
        self._cleanup_expired_sessions()
        
        # 新しいセッション作成
        self.user_states[user_id] = FinancialPlanInput(user_id=user_id)
        logger.info(f"💰 Started financial planning session for user: {user_id}")
        return self.user_states[user_id]
    
    def get_session(self, user_id: str) -> Optional[FinancialPlanInput]:
        """セッション取得"""
        self._cleanup_expired_sessions()
        return self.user_states.get(user_id)
    
    def update_session(self, user_id: str, field: str, value: Any) -> Optional[FinancialPlanInput]:
        """セッション更新"""
        session = self.get_session(user_id)
        if session:
            setattr(session, field, value)
            logger.info(f"💾 Updated {field} for user {user_id}: {value}")
            return session
        return None
    
    def end_session(self, user_id: str) -> bool:
        """セッション終了"""
        if user_id in self.user_states:
            del self.user_states[user_id]
            logger.info(f"🏁 Ended financial planning session for user: {user_id}")
            return True
        return False
    
    def _cleanup_expired_sessions(self):
        """期限切れセッションのクリーンアップ"""
        current_time = datetime.now()
        expired_users = []
        
        for user_id, session in self.user_states.items():
            if current_time - session.created_at > self.session_timeout:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            del self.user_states[user_id]
            logger.info(f"🧹 Cleaned up expired session for user: {user_id}")

# ==============================================================================
# 資金計算エンジン
# ==============================================================================
class FinancialCalculationEngine:
    """資金計算エンジン"""
    
    def __init__(self):
        # デフォルト設定
        self.default_interest_rate = 1.5  # 年利1.5%
        self.default_down_payment_rate = 0.2  # 頭金20%
        self.income_multiplier_safe = 5.0  # 年収倍率（安全）
        self.income_multiplier_max = 7.0  # 年収倍率（最大）
        self.debt_to_income_ratio = 0.25  # 返済負担率25%
    
    def calculate_financial_plan(self, input_data: FinancialPlanInput) -> FinancialPlanResult:
        """資金計画を計算"""
        try:
            # 基本パラメータ設定
            annual_income = input_data.annual_income or 0
            monthly_payment = input_data.monthly_payment or 0
            loan_period = input_data.loan_period or 35
            other_expenses = input_data.other_expenses or 0
            
            # 年収ベース計算
            income_based_budget_safe = int(annual_income * self.income_multiplier_safe / 10000) * 10000
            income_based_budget_max = int(annual_income * self.income_multiplier_max / 10000) * 10000
            
            # 返済額ベース計算
            if monthly_payment > 0:
                loan_amount = self._calculate_loan_amount(monthly_payment, loan_period, self.default_interest_rate)
                total_budget_from_payment = int((loan_amount + loan_amount * self.default_down_payment_rate) / 10000) * 10000
            else:
                total_budget_from_payment = income_based_budget_safe
            
            # 安全な予算範囲の決定
            affordable_min = min(income_based_budget_safe, total_budget_from_payment)
            affordable_max = max(income_based_budget_safe, total_budget_from_payment)
            
            # 最大借入可能額
            max_monthly_payment = int((annual_income / 12) * self.debt_to_income_ratio - other_expenses)
            max_loan_amount = self._calculate_loan_amount(max_monthly_payment, loan_period, self.default_interest_rate)
            
            # 推奨月額返済（家計に無理のない範囲）
            suggested_monthly = min(
                monthly_payment if monthly_payment > 0 else int((annual_income / 12) * 0.2),
                max_monthly_payment
            )
            
            # 頭金推奨額
            suggested_down_payment = int(affordable_min * self.default_down_payment_rate)
            
            # 総利息計算
            total_interest = int(suggested_monthly * loan_period * 12 - (affordable_min - suggested_down_payment))
            
            # リスクレベル評価
            risk_level = self._evaluate_risk_level(input_data, max_monthly_payment)
            
            return FinancialPlanResult(
                affordable_budget_min=int(affordable_min / 10000),  # 万円単位
                affordable_budget_max=int(affordable_max / 10000),  # 万円単位
                monthly_payment_suggestion=suggested_monthly,
                max_loan_amount=int(max_loan_amount / 10000),  # 万円単位
                down_payment_suggestion=int(suggested_down_payment / 10000),  # 万円単位
                total_interest=int(total_interest / 10000),  # 万円単位
                risk_level=risk_level
            )
            
        except Exception as e:
            logger.error(f"❌ Financial calculation error: {e}")
            # エラー時のデフォルト値
            return FinancialPlanResult(
                affordable_budget_min=2000,
                affordable_budget_max=3000,
                monthly_payment_suggestion=80000,
                max_loan_amount=2500,
                down_payment_suggestion=500,
                total_interest=500,
                risk_level="medium"
            )
    
    def _calculate_loan_amount(self, monthly_payment: int, period_years: int, annual_rate: float) -> int:
        """月額返済額から借入可能額を計算"""
        monthly_rate = annual_rate / 100 / 12
        total_months = period_years * 12
        
        if monthly_rate == 0:
            return monthly_payment * total_months
        
        loan_amount = monthly_payment * (1 - (1 + monthly_rate) ** (-total_months)) / monthly_rate
        return int(loan_amount)
    
    def _evaluate_risk_level(self, input_data: FinancialPlanInput, max_monthly: int) -> str:
        """リスクレベル評価"""
        if not input_data.annual_income or not input_data.monthly_payment:
            return "medium"
        
        payment_ratio = (input_data.monthly_payment + (input_data.other_expenses or 0)) / (input_data.annual_income / 12)
        
        if payment_ratio < 0.2:
            return "low"
        elif payment_ratio < 0.3:
            return "medium"
        else:
            return "high"

# ==============================================================================
# 入力パーサー
# ==============================================================================
class FinancialInputParser:
    """資金計画入力パーサー"""
    
    def parse_user_input(self, message: str, session: FinancialPlanInput) -> Dict[str, Any]:
        """ユーザー入力を解析"""
        message_lower = message.lower().replace(" ", "").replace("　", "")
        
        parse_result = {
            "field_updated": None,
            "value": None,
            "success": False,
            "message": ""
        }
        
        # 年収パターン
        income_match = re.search(r'年収[：:]*(\d+)(?:万円?|万|円)?', message) or \
                      re.search(r'(\d+)万円?(?:の年収|年収)', message) or \
                      re.search(r'^(\d+)万?$', message)
        
        if income_match and not session.annual_income:
            income_value = int(income_match.group(1))
            if 100 <= income_value <= 2000:  # 100万〜2000万の範囲
                parse_result.update({
                    "field_updated": "annual_income",
                    "value": income_value * 10000,  # 万円を円に変換
                    "success": True,
                    "message": f"年収 {income_value}万円 を記録しました。"
                })
                return parse_result
        
        # 月額返済希望額パターン
        payment_match = re.search(r'(?:月額?|毎月|返済)[：:]*(\d+)(?:万円?|万|円)?', message) or \
                       re.search(r'(\d+)万円?(?:ずつ|毎月|月)', message) or \
                       re.search(r'月(\d+)(?:万円?|万)', message)
        
        if payment_match and not session.monthly_payment:
            payment_value = int(payment_match.group(1))
            # 万円単位と円単位の判別
            if payment_value < 50:  # 50未満は万円と判断
                payment_value *= 10000
            parse_result.update({
                "field_updated": "monthly_payment",
                "value": payment_value,
                "success": True,
                "message": f"毎月の返済希望額 {payment_value:,}円 を記録しました。"
            })
            return parse_result
        
        # 借入期間パターン
        period_match = re.search(r'(?:期間|年数)[：:]*(\d+)年', message) or \
                      re.search(r'(\d+)年(?:ローン|借入|返済)', message) or \
                      re.search(r'^(\d+)年$', message)
        
        if period_match and not session.loan_period:
            period_value = int(period_match.group(1))
            if 10 <= period_value <= 50:  # 10年〜50年の範囲
                parse_result.update({
                    "field_updated": "loan_period",
                    "value": period_value,
                    "success": True,
                    "message": f"借入期間 {period_value}年 を記録しました。"
                })
                return parse_result
        
        # 家族構成パターン
        family_patterns = [
            (r'(?:大人|夫婦)(\d+)(?:人|名).*(?:子ども?|お子さま?)(\d+)(?:人|名)', lambda m: f"大人{m.group(1)}名・お子さま{m.group(2)}名"),
            (r'(?:夫婦|2人).*(?:子ども?|お子さま?)(\d+)(?:人|名)', lambda m: f"大人2名・お子さま{m.group(1)}名"),
            (r'(?:子ども?|お子さま?)(\d+)(?:人|名)', lambda m: f"大人2名・お子さま{m.group(1)}名"),
            (r'(?:夫婦|2人)(?:だけ|のみ)', lambda m: "大人2名"),
            (r'(?:一人|独身|単身)', lambda m: "大人1名"),
            (r'(\d+)人家族', lambda m: f"大人2名・お子さま{int(m.group(1))-2}名" if int(m.group(1)) > 2 else "大人2名")
        ]
        
        if not session.family_composition:
            for pattern, formatter in family_patterns:
                match = re.search(pattern, message)
                if match:
                    family_comp = formatter(match)
                    parse_result.update({
                        "field_updated": "family_composition",
                        "value": family_comp,
                        "success": True,
                        "message": f"家族構成 {family_comp} を記録しました。"
                    })
                    return parse_result
        
        # その他負担パターン
        expenses_match = re.search(r'(?:自動車|車|ローン|負担)[：:]*(\d+)(?:万円?|万|円)?', message) or \
                        re.search(r'(?:月|毎月)(\d+)(?:万円?|万)(?:の|負担)', message) or \
                        re.search(r'(?:なし|ない|0)', message)
        
        if expenses_match and session.other_expenses is None:
            if re.search(r'(?:なし|ない|0)', message):
                expenses_value = 0
                msg = "その他負担 なし を記録しました。"
            else:
                expenses_value = int(expenses_match.group(1))
                if expenses_value < 50:  # 50未満は万円と判断
                    expenses_value *= 10000
                msg = f"その他負担 {expenses_value:,}円 を記録しました。"
            
            parse_result.update({
                "field_updated": "other_expenses",
                "value": expenses_value,
                "success": True,
                "message": msg
            })
            return parse_result
        
        # パースできない場合
        parse_result["message"] = "申し訳ございません。形式を確認して再度ご入力ください。"
        return parse_result

# ==============================================================================
# 資金計画統合ハンドラ（指定文面統一版）
# ==============================================================================
class FinancialPlanningHandler:
    """資金計画統合ハンドラー（指定文面統一版）"""
    
    def __init__(self):
        self.state_manager = FinancialPlanningStateManager()
        self.parser = FinancialInputParser()
        self.calculator = FinancialCalculationEngine()
    
    def handle_financial_planning_message(self, user_id: str, message: str) -> str:
        """資金計画メッセージ処理（指定文面統一版）"""
        try:
            # 1. 既存セッションチェック
            session = self.state_manager.get_session(user_id)
            
            # 2. 新規セッション開始（リッチメニューからの場合）
            if not session and any(keyword in message.lower() for keyword in ["資金計画", "💰"]):
                session = self.state_manager.start_session(user_id)
                return self._get_initial_guidance_message()
            
            # 3. 既存セッションでの入力処理
            if session:
                parse_result = self.parser.parse_user_input(message, session)
                
                if parse_result["success"]:
                    # 入力値を更新
                    self.state_manager.update_session(
                        user_id, 
                        parse_result["field_updated"], 
                        parse_result["value"]
                    )
                    
                    # 更新されたセッションを取得
                    updated_session = self.state_manager.get_session(user_id)
                    completion_rate = updated_session.get_completion_rate()
                    
                    # 完了チェック
                    if completion_rate >= 1.0:
                        # 計算実行
                        result = self.calculator.calculate_financial_plan(updated_session)
                        
                        # セッション終了
                        self.state_manager.end_session(user_id)
                        
                        return result.format_line_response()
                    
                    else:
                        # 次の入力を促す
                        return self._get_next_input_message(updated_session, parse_result["message"])
                
                else:
                    # パースに失敗
                    return f"{parse_result['message']}\n\n{self._get_input_examples()}"
            
            # 4. セッションがない場合の処理
            return self._get_session_start_message()
            
        except Exception as e:
            logger.error(f"❌ Financial planning handler error: {e}")
            return """申し訳ございません。資金計画の処理中にエラーが発生しました。

「💰 資金計画」をもう一度タップして再開してください。"""
    
    def _get_initial_guidance_message(self) -> str:
        """初期案内メッセージ（指定文面統一版）"""
        return """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。"""
    
    def _get_next_input_message(self, session: FinancialPlanInput, current_update: str) -> str:
        """次の入力を促すメッセージ"""
        missing_fields = session.get_missing_fields()
        completion_rate = session.get_completion_rate()
        
        message = f"{current_update}\n\n"
        
        if len(missing_fields) > 0:
            message += f"📝 **入力状況** {int(completion_rate * 100)}% 完了\n\n"
            message += "**残りの項目：**\n"
            for field in missing_fields[:2]:  # 最大2項目表示
                if field == "年収":
                    message += "・年収（例：600万円）\n"
                elif field == "毎月返済希望額":
                    message += "・毎月の返済希望額（例：月8万円）\n"
                elif field == "借入期間":
                    message += "・借入期間（例：35年）\n"
                elif field == "家族構成":
                    message += "・家族構成（例：夫婦と子ども1人）\n"
                elif field == "その他負担":
                    message += "・その他負担（例：車ローン月3万円、またはなし）\n"
            
            if len(missing_fields) > 2:
                message += f"・他{len(missing_fields) - 2}項目\n"
            
            message += "\n引き続きご入力ください😊"
        
        return message
    
    def _get_input_examples(self) -> str:
        """入力例を表示"""
        return """💡 **入力例**
年収：「年収600万円」「600万」
返済額：「月8万円」「毎月10万」
期間：「35年」「30年ローン」
家族：「夫婦と子ども1人」「大人2名お子さま1名」
その他：「車ローン月3万円」「なし」「0円」"""
    
    def _get_session_start_message(self) -> str:
        """セッション開始メッセージ"""
        return """資金計画をご希望でしたら「💰 資金計画」ボタンをタップしてください。

または「資金計画」とメッセージをお送りください😊"""

# ==============================================================================
# グローバルインスタンス
# ==============================================================================
financial_handler = FinancialPlanningHandler()

# ==============================================================================
# LIFFページ（資金計画用）
# ==============================================================================
def get_financial_planning_liff_page() -> str:
    """資金計画用LIFFページのHTML"""
    return """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI資金診断 - キノエデザイン</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container {
            max-width: 400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 24px;
        }
        .title {
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin: 8px 0;
        }
        .subtitle {
            font-size: 14px;
            color: #666;
            line-height: 1.4;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .label {
            display: block;
            font-weight: 600;
            color: #333;
            margin-bottom: 8px;
        }
        .input {
            width: 100%;
            padding: 12px;
            border: 2px solid #eee;
            border-radius: 8px;
            font-size: 16px;
            box-sizing: border-box;
        }
        .input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 16px;
        }
        .btn:hover {
            opacity: 0.9;
        }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .result {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }
        .privacy-notice {
            font-size: 12px;
            color: #666;
            text-align: center;
            margin-top: 16px;
            line-height: 1.4;
        }
        .privacy-notice a {
            color: #667eea;
            text-decoration: none;
        }
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            margin: 16px 0;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            width: 0%;
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
            <div class="progress-bar">
                <div class="progress-fill" id="progressBar"></div>
            </div>
        </div>
        
        <form id="financialForm">
            <div class="form-group">
                <label class="label">年収（概算可）</label>
                <input type="number" class="input" id="annualIncome" placeholder="例：600（万円）">
            </div>
            
            <div class="form-group">
                <label class="label">毎月のご希望返済額</label>
                <input type="number" class="input" id="monthlyPayment" placeholder="例：8（万円）">
            </div>
            
            <div class="form-group">
                <label class="label">住宅ローンのご希望借入期間</label>
                <select class="input" id="loanPeriod">
                    <option value="">選択してください</option>
                    <option value="20">20年</option>
                    <option value="25">25年</option>
                    <option value="30">30年</option>
                    <option value="35">35年</option>
                    <option value="40">40年</option>
                </select>
            </div>
            
            <div class="form-group">
                <label class="label">ご家族構成</label>
                <select class="input" id="familyComposition">
                    <option value="">選択してください</option>
                    <option value="大人1名">大人1名（単身）</option>
                    <option value="大人2名">大人2名（夫婦）</option>
                    <option value="大人2名・お子さま1名">大人2名・お子さま1名</option>
                    <option value="大人2名・お子さま2名">大人2名・お子さま2名</option>
                    <option value="大人2名・お子さま3名">大人2名・お子さま3名</option>
                    <option value="その他">その他</option>
                </select>
            </div>
            
            <div class="form-group">
                <label class="label">その他の大きなご負担</label>
                <input type="number" class="input" id="otherExpenses" placeholder="例：3（万円）、なければ0">
            </div>
            
            <button type="submit" class="btn" id="calculateBtn">概算結果を計算</button>
        </form>
        
        <div class="result" id="resultArea">
            <div id="calculationResult"></div>
        </div>
        
        <div class="privacy-notice">
            必ず<a href="https://preview.studio.site/live/EjOQljz1WJ/privacy-policy" target="_blank">プライバシーポリシー</a>、
            <a href="https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service" target="_blank">利用規約</a>、
            <a href="https://preview.studio.site/live/EjOQljz1WJ/cookie" target="_blank">Cookie</a>をご確認ください
        </div>
    </div>

    <script>
        // LIFF初期化
        liff.init({
            liffId: 'YOUR_LIFF_ID_HERE'  // 実際のLIFF IDに置き換え
        }).then(() => {
            console.log('LIFF初期化成功');
        }).catch((err) => {
            console.error('LIFF初期化失敗:', err);
        });
        
        // プログレスバー更新
        function updateProgress() {
            const form = document.getElementById('financialForm');
            const inputs = form.querySelectorAll('input, select');
            let filledCount = 0;
            
            inputs.forEach(input => {
                if (input.value.trim() !== '') {
                    filledCount++;
                }
            });
            
            const progress = (filledCount / inputs.length) * 100;
            document.getElementById('progressBar').style.width = progress + '%';
        }
        
        // 入力変更監視
        document.addEventListener('input', updateProgress);
        document.addEventListener('change', updateProgress);
        
        // フォーム送信
        document.getElementById('financialForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = {
                annual_income: parseInt(document.getElementById('annualIncome').value) * 10000 || null,
                monthly_payment: parseInt(document.getElementById('monthlyPayment').value) * 10000 || null,
                loan_period: parseInt(document.getElementById('loanPeriod').value) || null,
                family_composition: document.getElementById('familyComposition').value || null,
                other_expenses: parseInt(document.getElementById('otherExpenses').value) * 10000 || 0
            };
            
            const calculateBtn = document.getElementById('calculateBtn');
            calculateBtn.disabled = true;
            calculateBtn.textContent = '計算中...';
            
            try {
                // API呼び出し（実装時は実際のエンドポイントに変更）
                const response = await fetch('/api/financial-calculate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(formData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    // 結果表示
                    document.getElementById('calculationResult').innerHTML = result.formatted_result;
                    document.getElementById('resultArea').style.display = 'block';
                    
                    // LINEメッセージとして送信
                    if (liff.isInClient()) {
                        liff.sendMessages([{
                            type: 'text',
                            text: result.line_message
                        }]).then(() => {
                            liff.closeWindow();
                        });
                    }
                } else {
                    alert('計算中にエラーが発生しました。再度お試しください。');
                }
                
            } catch (error) {
                console.error('API呼び出しエラー:', error);
                alert('通信エラーが発生しました。再度お試しください。');
            }
            
            calculateBtn.disabled = false;
            calculateBtn.textContent = '概算結果を計算';
        });
    </script>
</body>
</html>"""

# ==============================================================================
# 資金計画機能をline_bot_ultra_fastに統合するための関数
# ==============================================================================
def get_financial_planning_handler():
    """資金計画ハンドラーを取得（他のモジュールから呼び出し用）"""
    return financial_handler

def is_financial_planning_message(message: str) -> bool:
    """資金計画関連メッセージかチェック"""
    keywords = ["資金計画", "💰", "ローン計算", "予算診断", "支払い診断"]
    return any(keyword in message for keyword in keywords)

def handle_financial_message_for_line(user_id: str, message: str) -> str:
    """LINE Bot用資金計画メッセージ処理（指定文面統一版）"""
    return financial_handler.handle_financial_planning_message(user_id, message)

# ==============================================================================
# テスト関数
# ==============================================================================
def test_financial_planning():
    """資金計画機能テスト"""
    test_user_id = "test_user_123"
    handler = FinancialPlanningHandler()
    
    print("🧪 資金計画機能テスト開始（指定文面統一版）")
    print("=" * 50)
    
    # 1. セッション開始
    response1 = handler.handle_financial_planning_message(test_user_id, "💰 資金計画")
    print(f"1. セッション開始: {response1[:100]}...")
    
    # 2. 年収入力
    response2 = handler.handle_financial_planning_message(test_user_id, "年収600万円")
    print(f"2. 年収入力: {response2[:100]}...")
    
    # 3. 月額返済入力
    response3 = handler.handle_financial_planning_message(test_user_id, "月8万円")
    print(f"3. 月額返済: {response3[:100]}...")
    
    # 4. 借入期間入力
    response4 = handler.handle_financial_planning_message(test_user_id, "35年")
    print(f"4. 借入期間: {response4[:100]}...")
    
    # 5. 家族構成入力
    response5 = handler.handle_financial_planning_message(test_user_id, "夫婦と子ども1人")
    print(f"5. 家族構成: {response5[:100]}...")
    
    # 6. その他負担入力（完了）
    response6 = handler.handle_financial_planning_message(test_user_id, "車ローン月3万円")
    print(f"6. 最終結果: {response6[:200]}...")
    
    print("\n✅ テスト完了（指定文面統一版）")

if __name__ == "__main__":
    test_financial_planning()