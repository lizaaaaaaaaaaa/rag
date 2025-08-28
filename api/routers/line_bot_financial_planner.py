# -*- coding: utf-8 -*-
# 資金計画機能統合実装（FastAPI ルータ同梱・絵文字安全化・LIFF 対応）
# 互換維持:
#   - get_financial_planning_handler()
#   - is_financial_planning_message(message)
#   - handle_financial_message_for_line(user_id, message)
#   - run_financial_plan(message: str, user_id: Optional[str] = None)
# 追加:
#   - FastAPI APIRouter を内蔵し、/api/financial-calculate と /liff/financial を提供

import logging
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Tuple, Callable
from dataclasses import dataclass, asdict

# --- FastAPI 追加 ---
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ==============================================================================
# 絵文字安全化（:robot: などのコロン表記→Unicode に置換）
# ==============================================================================
_EMOJI_MAP = {
    ":robot:": "🤖",
    ":globe_with_meridians:": "🌐",
    ":speech_balloon:": "💬",
    ":round_pushpin:": "📍",
    ":clipboard:": "📋",
    ":moneybag:": "💰",
    ":bulb:": "💡",
    ":yen:": "💴",
    ":mobile_phone:": "📱",
    ":house:": "🏠",
    ":blush:": "😊",
    ":sparkles:": "✨",
}

def emojify(text: str) -> str:
    if not text:
        return text
    out = text
    for k, v in _EMOJI_MAP.items():
        out = out.replace(k, v)
    return out

# ==============================================================================
# ユーティリティ（正規化）
# ==============================================================================
_ZEN2HAN = str.maketrans(
    "０１２３４５６７８９．，＋－ー，． ",
    "0123456789..+- -  "
)

def z2h(s: str) -> str:
    """全角→半角/不要スペース除去"""
    return s.translate(_ZEN2HAN)

def parse_number_like(s: str) -> Optional[int]:
    """
    「600」「600万」「600万円」「8万」「80000円」「月8万」「3.5万」などを概ね整数円へ。
    """
    if not s:
        return None
    s = z2h(s).strip().lower()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|万円|円)?", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or ""
    if "万" in unit:
        return int(num * 10000)
    if "円" in unit:
        return int(num)
    if num < 50:
        return int(num * 10000)
    return int(num)

def strip_citations(text: str) -> str:
    """出典/参考/資料の行を削る（UI非表示要件）"""
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ==============================================================================
# データモデル
# ==============================================================================
@dataclass
class FinancialPlanInput:
    """資金計画入力データ（円・年・自由文）"""
    user_id: str
    annual_income: Optional[int] = None       # 年収 [円]
    monthly_payment: Optional[int] = None     # 月額返済希望 [円]
    loan_period: Optional[int] = None         # 借入期間 [年]
    family_composition: Optional[str] = None  # 家族構成 [自由文]
    other_expenses: Optional[int] = None      # その他負担 [円]
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_completion_rate(self) -> float:
        filled = sum([
            1 if self.annual_income else 0,
            1 if self.monthly_payment else 0,
            1 if self.loan_period else 0,
            1 if self.family_composition else 0,
            1 if self.other_expenses is not None else 0,  # 0円も有効
        ])
        return filled / 5.0

    def get_missing_fields(self) -> List[str]:
        missing = []
        if not self.annual_income:      missing.append("年収")
        if not self.monthly_payment:    missing.append("毎月返済希望額")
        if not self.loan_period:        missing.append("借入期間")
        if not self.family_composition: missing.append("家族構成")
        if self.other_expenses is None: missing.append("その他負担")
        return missing

@dataclass
class FinancialPlanResult:
    """資金計画結果（表示は主に万円・円の混在注意）"""
    affordable_budget_min: int      # 万円
    affordable_budget_max: int      # 万円
    monthly_payment_suggestion: int # 円
    max_loan_amount: int            # 万円
    down_payment_suggestion: int    # 万円
    total_interest: int             # 万円
    risk_level: str                 # 'low'|'medium'|'high'

    def format_line_response(self) -> str:
        """LINE用フォーマット（出典/参考/資料 なし）"""
        txt = f"""✅ 資金計画 概算結果

💰 買える金額の目安（総予算）
約{self.affordable_budget_min:,}万〜{self.affordable_budget_max:,}万円
→この範囲で探すと、むりが出にくい目安です。

💳 毎月の支払いの目安（ローン返済）
約{self.monthly_payment_suggestion:,}円
→いまの生活と両立しやすい金額の目安です。

📊 借りられる上限の目安（ローン上限）
最大{self.max_loan_amount:,}万円
→これ以上だと負担が大きくなる可能性があります。

※金利や諸費用、物件条件によって前後します。詳しい金額はスタッフがご案内します。

🔎 チェック（3点）
・暮らしの流れ：今の生活費＋教育/車など将来支出と両立できる？
・使い勝手：通勤/学校/買物など日常の移動と合う？
・将来性：家族構成の変化や金利の上下に耐えられる？

（必要なら再計算もOK：「頭金を＋○万円に」「35年→30年なら？」など）"""
        return emojify(txt)

# ==============================================================================
# 状態管理（メモリ）
# ==============================================================================
class FinancialPlanningStateManager:
    def __init__(self):
        self.user_states: Dict[str, FinancialPlanInput] = {}
        self.session_timeout = timedelta(hours=2)

    def start_session(self, user_id: str) -> FinancialPlanInput:
        self._cleanup_expired_sessions()
        self.user_states[user_id] = FinancialPlanInput(user_id=user_id)
        logger.info(f"💰 Start session: {user_id}")
        return self.user_states[user_id]

    def get_session(self, user_id: str) -> Optional[FinancialPlanInput]:
        self._cleanup_expired_sessions()
        return self.user_states.get(user_id)

    def update_session(self, user_id: str, field: str, value: Any) -> Optional[FinancialPlanInput]:
        s = self.get_session(user_id)
        if s:
            setattr(s, field, value)
            logger.info(f"💾 Update {field} = {value} ({user_id})")
            return s
        return None

    def end_session(self, user_id: str) -> bool:
        if user_id in self.user_states:
            del self.user_states[user_id]
            logger.info(f"🏁 End session: {user_id}")
            return True
        return False

    def _cleanup_expired_sessions(self):
        now = datetime.now()
        expired = [uid for uid, s in self.user_states.items() if now - s.created_at > self.session_timeout]
        for uid in expired:
            del self.user_states[uid]
            logger.info(f"🧹 Clean expired session: {uid}")

# ==============================================================================
# 計算エンジン（軽量）
# ==============================================================================
class FinancialCalculationEngine:
    def __init__(self):
        self.default_interest_rate = 1.5       # 年利 [%]
        self.default_down_payment_rate = 0.2   # 頭金 20%
        self.income_multiplier_safe = 5.0      # 安全
        self.income_multiplier_max  = 7.0      # 上限
        self.debt_to_income_ratio   = 0.25     # 返済負担率 25%

    def calculate_financial_plan(self, inp: FinancialPlanInput) -> FinancialPlanResult:
        try:
            annual_income   = inp.annual_income or 0
            monthly_payment = inp.monthly_payment or 0
            loan_period     = inp.loan_period or 35
            other_expenses  = inp.other_expenses or 0

            income_based_budget_safe = int(annual_income * self.income_multiplier_safe / 10000) * 10000
            income_based_budget_max  = int(annual_income * self.income_multiplier_max  / 10000) * 10000

            if monthly_payment > 0:
                loan_amount = self._loan_from_monthly(monthly_payment, loan_period, self.default_interest_rate)
                total_budget_from_payment = int((loan_amount * (1 + self.default_down_payment_rate)) / 10000) * 10000
            else:
                total_budget_from_payment = income_based_budget_safe

            affordable_min = min(income_based_budget_safe, total_budget_from_payment)
            affordable_max = max(income_based_budget_safe, total_budget_from_payment)

            max_monthly_payment = max(0, int((annual_income / 12) * self.debt_to_income_ratio - other_expenses))
            max_loan_amount = self._loan_from_monthly(max_monthly_payment, loan_period, self.default_interest_rate)

            base_suggest = int((annual_income / 12) * 0.2)
            suggested_monthly = min(monthly_payment if monthly_payment > 0 else base_suggest, max_monthly_payment)

            suggested_down_payment = int(affordable_min * self.default_down_payment_rate)

            total_interest = max(0, int(suggested_monthly * loan_period * 12 - (affordable_min - suggested_down_payment)))

            risk_level = self._risk_level(inp, max_monthly_payment)

            return FinancialPlanResult(
                affordable_budget_min=int(affordable_min / 10000),
                affordable_budget_max=int(affordable_max / 10000),
                monthly_payment_suggestion=suggested_monthly,
                max_loan_amount=int(max_loan_amount / 10000),
                down_payment_suggestion=int(suggested_down_payment / 10000),
                total_interest=int(total_interest / 10000),
                risk_level=risk_level,
            )
        except Exception as e:
            logger.error(f"❌ calc error: {e}")
            return FinancialPlanResult(
                affordable_budget_min=2000,
                affordable_budget_max=3000,
                monthly_payment_suggestion=80000,
                max_loan_amount=2500,
                down_payment_suggestion=500,
                total_interest=500,
                risk_level="medium",
            )

    def _loan_from_monthly(self, monthly_payment: int, period_years: int, annual_rate: float) -> int:
        r = annual_rate / 100 / 12
        n = period_years * 12
        if r == 0:
            return monthly_payment * n
        return int(monthly_payment * (1 - (1 + r) ** (-n)) / r)

    def _risk_level(self, inp: FinancialPlanInput, max_m: int) -> str:
        if not inp.annual_income or not inp.monthly_payment:
            return "medium"
        ratio = (inp.monthly_payment + (inp.other_expenses or 0)) / max(1, (inp.annual_income / 12))
        if ratio < 0.2: return "low"
        if ratio < 0.3: return "medium"
        return "high"

# ==============================================================================
# 入力パーサ
# ==============================================================================
class FinancialInputParser:
    def parse_user_input(self, message: str, session: FinancialPlanInput) -> Dict[str, Any]:
        raw = message or ""
        msg = z2h(raw).replace(" ", "").replace("　", "")
        res = {"field_updated": None, "value": None, "success": False, "message": ""}

        # 年収
        income_match = (
            re.search(r'年収[:：]?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'(\d+(?:\.\d+)?)\s*(万|万円)?年収', msg) or
            re.search(r'^(\d+(?:\.\d+)?)\s*(万|万円)$', msg)
        )
        if income_match and not session.annual_income:
            val = parse_number_like(income_match.group(1) + (income_match.group(2) or "万"))
            if val and 1_000_000 <= val <= 200_000_000:
                res.update(field_updated="annual_income", value=val, success=True,
                           message=f"年収 {int(val/10000)}万円 を記録しました。")
                return res

        # 月額返済
        payment_match = (
            re.search(r'(?:月額|毎月|返済)[:：]?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'月(\d+(?:\.\d+)?)\s*(万|万円)', msg) or
            re.search(r'(\d+(?:\.\d+)?)\s*(万|万円)(?:ずつ|毎月|月)', msg)
        )
        if payment_match and not session.monthly_payment:
            val = parse_number_like(payment_match.group(1) + (payment_match.group(2) or "万"))
            if val and val > 0:
                res.update(field_updated="monthly_payment", value=val, success=True,
                           message=f"毎月の返済希望額 {val:,}円 を記録しました。")
                return res

        # 期間（年）
        period_match = (
            re.search(r'(?:期間|年数)[:：]?(\d+)\s*年', msg) or
            re.search(r'(\d+)\s*年(?:ローン|借入|返済)?', msg) or
            re.search(r'^(\d+)\s*年$', msg)
        )
        if period_match and not session.loan_period:
            years = int(period_match.group(1))
            if 10 <= years <= 50:
                res.update(field_updated="loan_period", value=years, success=True,
                           message=f"借入期間 {years}年 を記録しました。")
                return res

        # 家族構成
        if not session.family_composition:
            family_patterns: List[Tuple[str, Callable[[re.Match], str]]] = [
                (r'(?:大人|夫婦)(\d+)(?:人|名).*?(?:子ども?|お子さま?)(\d+)(?:人|名)', lambda m: f"大人{m.group(1)}名・お子さま{m.group(2)}名"),
                (r'(?:夫婦|2人).*?(?:子ども?|お子さま?)(\d+)(?:人|名)',        lambda m: f"大人2名・お子さま{m.group(1)}名"),
                (r'(?:子ども?|お子さま?)(\d+)(?:人|名)',                       lambda m: f"大人2名・お子さま{m.group(1)}名"),
                (r'(?:夫婦|2人)(?:だけ|のみ)',                                  lambda m: "大人2名"),
                (r'(?:一人|独身|単身)',                                        lambda m: "大人1名"),
                (r'(\d+)\s*人家族',                                            lambda m: "大人2名" if int(m.group(1)) <= 2 else f"大人2名・お子さま{int(m.group(1))-2}名"),
            ]
            for pat, fmt in family_patterns:
                m = re.search(pat, msg)
                if m:
                    comp = fmt(m)
                    res.update(field_updated="family_composition", value=comp, success=True,
                               message=f"家族構成 {comp} を記録しました。")
                    return res

        # その他負担（円）
        expenses_match = (
            re.search(r'(?:自動車|車|ローン|負担)[:：]?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'(?:月|毎月)(\d+(?:\.\d+)?)\s*(万|万円)(?:の|負担)', msg) or
            re.search(r'(?:なし|ない|0円?)', msg)
        )
        if expenses_match and session.other_expenses is None:
            if re.search(r'(?:なし|ない|0円?)', msg):
                val = 0
                res.update(field_updated="other_expenses", value=val, success=True, message="その他負担 なし を記録しました。")
                return res
            val = parse_number_like(expenses_match.group(1) + (expenses_match.group(2) or "万"))
            if val is not None:
                res.update(field_updated="other_expenses", value=val, success=True,
                           message=f"その他負担 {val:,}円 を記録しました。")
                return res

        res["message"] = "形式を確認して再度ご入力ください。例：「年収600万円」「月8万円」「35年」「夫婦と子ども1人」「車ローン月3万円」"
        return res

# ==============================================================================
# 統合ハンドラ
# ==============================================================================
class FinancialPlanningHandler:
    def __init__(self):
        self.state_manager = FinancialPlanningStateManager()
        self.parser = FinancialInputParser()
        self.calculator = FinancialCalculationEngine()

    def handle_financial_planning_message(self, user_id: str, message: str) -> str:
        try:
            # セッション
            sess = self.state_manager.get_session(user_id)
            # リッチメニュー起点
            if not sess and any(k in (message or "") for k in ["資金計画", "💰"]):
                self.state_manager.start_session(user_id)
                return (
                    "💬 AI資金診断のご案内\n\n"
                    "本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。\n\n"
                    "お手数ですが、以下の5点をご入力ください。\n"
                    "・年収（概算可）\n"
                    "・毎月のご希望返済額\n"
                    "・住宅ローンのご希望借入期間\n"
                    "・ご家族構成（例：大人2名・お子さま1名）\n"
                    "・その他の大きなご負担（例：自動車ローン 等）\n\n"
                    "未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。"
                )

            # 入力処理
            if sess:
                parsed = self.parser.parse_user_input(message, sess)
                if parsed["success"]:
                    self.state_manager.update_session(user_id, parsed["field_updated"], parsed["value"])
                    sess2 = self.state_manager.get_session(user_id)
                    if sess2.get_completion_rate() >= 1.0:
                        result = self.calculator.calculate_financial_plan(sess2)
                        self.state_manager.end_session(user_id)
                        return strip_citations(result.format_line_response())
                    # 未完了 → 次の入力促し
                    missing = sess2.get_missing_fields()
                    rate = int(sess2.get_completion_rate() * 100)
                    guide_map = {
                        "年収": "・年収（例：600万円）\n",
                        "毎月返済希望額": "・毎月の返済希望額（例：月8万円）\n",
                        "借入期間": "・借入期間（例：35年）\n",
                        "家族構成": "・家族構成（例：夫婦と子ども1人）\n",
                        "その他負担": "・その他負担（例：車ローン月3万円、またはなし）\n",
                    }
                    msg = f"{parsed['message']}\n\n📝 入力状況 {rate}% 完了\n\n"
                    if missing:
                        msg += "残りの項目：\n"
                        for k in missing[:2]:
                            msg += guide_map.get(k, "")
                        if len(missing) > 2:
                            msg += f"・他{len(missing)-2}項目\n"
                        msg += "\n引き続きご入力ください😊"
                    return msg
                # パース失敗
                return (
                    f"{parsed['message']}\n\n"
                    "💡 入力例\n"
                    "年収：「年収600万円」「600万」\n"
                    "返済額：「月8万円」「毎月10万」\n"
                    "期間：「35年」「30年ローン」\n"
                    "家族：「夫婦と子ども1人」「大人2名お子さま1名」\n"
                    "その他：「車ローン月3万円」「なし」「0円」"
                )

            # セッション無し
            return "資金計画をご希望でしたら「💰 資金計画」ボタンをタップしてください。\n\nまたは「資金計画」とメッセージをお送りください😊"

        except Exception as e:
            logger.error(f"❌ handler error: {e}")
            return "申し訳ございません。処理中にエラーが発生しました。「💰 資金計画」をもう一度タップして再開してください。"

# グローバル・ハンドラ（既存互換）
financial_handler = FinancialPlanningHandler()

def get_financial_planning_handler():
    return financial_handler

def is_financial_planning_message(message: str) -> bool:
    keywords = ["資金計画", "💰", "ローン計算", "予算診断", "支払い診断"]
    return any(k in (message or "") for k in keywords)

def handle_financial_message_for_line(user_id: str, message: str) -> str:
    return financial_handler.handle_financial_planning_message(user_id, message)

def run_financial_plan(message: str, user_id: Optional[str] = None) -> str:
    """
    単発API（互換用）
    - user_id があればセッションを使った段階入力を継続
    - user_id がなければ「1メッセージからのベストエフォート概算」を返す
    """
    try:
        if user_id:
            return handle_financial_message_for_line(user_id, message)

        tmp = FinancialPlanInput(user_id="stateless")
        p = FinancialInputParser()
        chunks = re.split(r"[、。/\n・,]+", z2h(message or ""))
        for ch in filter(None, chunks):
            r = p.parse_user_input(ch, tmp)
            if r["success"]:
                setattr(tmp, r["field_updated"], r["value"])

        if not tmp.loan_period:
            tmp.loan_period = 35
        if tmp.other_expenses is None:
            tmp.other_expenses = 0

        calc = FinancialCalculationEngine()
        result = calc.calculate_financial_plan(tmp)
        return strip_citations(result.format_line_response())

    except Exception as e:
        logger.error(f"❌ run_financial_plan error: {e}")
        return "処理に失敗しました。必要項目（年収・毎月返済額・借入期間・家族構成・その他負担）をご入力ください。"

# ==============================================================================
# LIFF ページ（環境変数 LIFF_ID を差し込み）
# ==============================================================================
def get_financial_planning_liff_page() -> str:
    liff_id = os.getenv("LIFF_ID", "YOUR_LIFF_ID_HERE")
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI資金診断 - キノエデザイン</title><script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh}}
.container{{max-width:400px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 8px 32px rgba(0,0,0,.1)}}
.header{{text-align:center;margin-bottom:24px}}.title{{font-size:24px;font-weight:700;color:#333;margin:8px 0}}
.subtitle{{font-size:14px;color:#666;line-height:1.4}}.form-group{{margin-bottom:20px}}.label{{display:block;font-weight:600;color:#333;margin-bottom:8px}}
.input{{width:100%;padding:12px;border:2px solid #eee;border-radius:8px;font-size:16px;box-sizing:border-box}}.input:focus{{outline:none;border-color:#667eea}}
.btn{{width:100%;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px}}
.btn:hover{{opacity:.9}}.btn:disabled{{opacity:.5;cursor:not-allowed}}.result{{background:#f8f9fa;padding:20px;border-radius:8px;margin-top:20px;display:none}}
.privacy-notice{{font-size:12px;color:#666;text-align:center;margin-top:16px;line-height:1.4}}.privacy-notice a{{color:#667eea;text-decoration:none}}
.progress-bar{{width:100%;height:8px;background:#eee;border-radius:4px;margin:16px 0;overflow:hidden}}.progress-fill{{height:100%;background:linear-gradient(90deg,#667eea 0%,#764ba2 100%);transition:width .3s ease;width:0%}}</style>
</head><body><div class="container"><div class="header"><div class="title">💰 AI資金診断</div>
<div class="subtitle">匿名で利用可能・回答内容は保存されません<br>算出される金額は試算（概算）です</div>
<div class="progress-bar"><div class="progress-fill" id="progressBar"></div></div></div>
<form id="financialForm"><div class="form-group"><label class="label">年収（概算可）</label><input type="number" class="input" id="annualIncome" placeholder="例：600（万円）"></div>
<div class="form-group"><label class="label">毎月のご希望返済額</label><input type="number" class="input" id="monthlyPayment" placeholder="例：8（万円）"></div>
<div class="form-group"><label class="label">住宅ローンのご希望借入期間</label><select class="input" id="loanPeriod">
<option value="">選択してください</option><option value="20">20年</option><option value="25">25年</option><option value="30">30年</option><option value="35">35年</option><option value="40">40年</option>
</select></div>
<div class="form-group"><label class="label">ご家族構成</label><select class="input" id="familyComposition">
<option value="">選択してください</option><option value="大人1名">大人1名（単身）</option><option value="大人2名">大人2名（夫婦）</option>
<option value="大人2名・お子さま1名">大人2名・お子さま1名</option><option value="大人2名・お子さま2名">大人2名・お子さま2名</option><option value="大人2名・お子さま3名">大人2名・お子さま3名</option><option value="その他">その他</option>
</select></div>
<div class="form-group"><label class="label">その他の大きなご負担</label><input type="number" class="input" id="otherExpenses" placeholder="例：3（万円）、なければ0"></div>
<button type="submit" class="btn" id="calculateBtn">概算結果を計算</button></form>
<div class="result" id="resultArea"><div id="calculationResult"></div></div>
<div class="privacy-notice">必ず<a href="https://preview.studio.site/live/EjOQljz1WJ/privacy-policy" target="_blank">プライバシーポリシー</a>、
<a href="https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service" target="_blank">利用規約</a>、
<a href="https://preview.studio.site/live/EjOQljz1WJ/cookie" target="_blank">Cookie</a>をご確認ください</div></div>
<script>
liff.init({{liffId:'{liff_id}'}}).catch(console.error);
function updateProgress(){{const f=document.getElementById('financialForm');const i=f.querySelectorAll('input,select');let c=0;i.forEach(x=>{{if((x.value||'').trim()!==''){{c++}}}});document.getElementById('progressBar').style.width=(c/i.length*100)+'%'}}
document.addEventListener('input',updateProgress);document.addEventListener('change',updateProgress);
document.getElementById('financialForm').addEventListener('submit',async(e)=>{{e.preventDefault();
const data={{annual_income:parseInt(document.getElementById('annualIncome').value)*10000||null,
monthly_payment:parseInt(document.getElementById('monthlyPayment').value)*10000||null,
loan_period:parseInt(document.getElementById('loanPeriod').value)||null,
family_composition:document.getElementById('familyComposition').value||null,
other_expenses:parseInt(document.getElementById('otherExpenses').value)*10000||0}};
const btn=document.getElementById('calculateBtn');btn.disabled=true;btn.textContent='計算中...';
try{{const resp=await fetch('/api/financial-calculate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}}); 
const result=await resp.json();if(result.success){{document.getElementById('calculationResult').innerHTML=result.formatted_result;document.getElementById('resultArea').style.display='block';
if(liff.isInClient()){{await liff.sendMessages([{{type:'text',text:result.line_message}}]);liff.closeWindow();}}}}else{{alert('計算中にエラーが発生しました。');}}}}
catch(err){{console.error(err);alert('通信エラーが発生しました。');}}btn.disabled=false;btn.textContent='概算結果を計算';}});
</script></body></html>"""
    return html

# ==============================================================================
# FastAPI Router
# ==============================================================================
router = APIRouter()

class FinancialCalcRequest(BaseModel):
    annual_income: Optional[int] = Field(None, description="年収[円]")
    monthly_payment: Optional[int] = Field(None, description="毎月返済[円]")
    loan_period: Optional[int] = Field(None, description="借入期間[年]")
    family_composition: Optional[str] = None
    other_expenses: Optional[int] = Field(0, description="その他負担[円]")

class FinancialCalcResponse(BaseModel):
    success: bool
    formatted_result: str
    line_message: str

@router.get("/liff/financial", response_class=HTMLResponse)
def liff_financial():
    return HTMLResponse(get_financial_planning_liff_page())

@router.post("/api/financial-calculate", response_model=FinancialCalcResponse)
def financial_calculate(body: FinancialCalcRequest):
    try:
        inp = FinancialPlanInput(
            user_id="liff",
            annual_income=body.annual_income,
            monthly_payment=body.monthly_payment,
            loan_period=body.loan_period or 35,
            family_composition=body.family_composition,
            other_expenses=0 if body.other_expenses is None else body.other_expenses,
        )
        calc = FinancialCalculationEngine()
        res = calc.calculate_financial_plan(inp)
        formatted = strip_citations(res.format_line_response())
        return FinancialCalcResponse(
            success=True,
            formatted_result=formatted.replace("\n", "<br>"),
            line_message=formatted,
        )
    except Exception as e:
        logger.exception("financial_calculate failed")
        raise HTTPException(status_code=500, detail="calculation_failed")

# 簡易健全性チェック
@router.get("/api/financial-health")
def financial_health():
    return {"ok": True, "now": datetime.utcnow().isoformat() + "Z"}
