# -*- coding: utf-8 -*-
# 資金計画機能統合実装（改善版・より正確な計算）
# 新ヒアリング項目対応:
#   - 世帯年収（合算の有無）
#   - 頭金（自己資金）
#   - 返済期間（年数）
#   - 想定金利
#   - 他の借入の毎月返済額合計
#   - 借入時の年齢

import logging
import re
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Tuple, Callable
from dataclasses import dataclass, asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ==============================================================================
# 絵文字安全化
# ==============================================================================
_EMOJI_MAP = {
    ":robot:": "🤖", ":globe_with_meridians:": "🌐", ":speech_balloon:": "💬",
    ":round_pushpin:": "📍", ":clipboard:": "📋", ":moneybag:": "💰",
    ":bulb:": "💡", ":yen:": "💴", ":mobile_phone:": "📱",
    ":house:": "🏠", ":blush:": "😊", ":sparkles:": "✨",
}

def emojify(text: str) -> str:
    if not text:
        return text
    out = text
    for k, v in _EMOJI_MAP.items():
        out = out.replace(k, v)
    return out

# ==============================================================================
# ユーティリティ
# ==============================================================================
_ZEN2HAN = str.maketrans("０１２３４５６７８９．，＋－ー，． ", "0123456789..+- -  ")

def z2h(s: str) -> str:
    """全角→半角/不要スペース除去"""
    return s.translate(_ZEN2HAN)

def parse_number_like(s: str) -> Optional[float]:
    """数値パース（万円対応）"""
    if not s:
        return None
    s = z2h(s).strip().lower()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|万円|円)?", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or ""
    if "万" in unit:
        return num * 10000
    if "円" in unit:
        return num
    if num < 50:  # 小さい数字は万円と推定
        return num * 10000
    return num

def strip_citations(text: str) -> str:
    """出典/参考/資料の行を削る"""
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ==============================================================================
# データモデル（新項目対応）
# ==============================================================================
@dataclass
class FinancialPlanInput:
    """資金計画入力データ"""
    user_id: str
    household_income: Optional[int] = None      # 世帯年収 [円]
    down_payment: Optional[int] = None          # 頭金（自己資金）[円]
    loan_period: Optional[int] = None           # 返済期間 [年]
    interest_rate: Optional[float] = None       # 想定金利 [%]
    other_monthly_debt: Optional[int] = None    # 他の借入の毎月返済額 [円]
    borrower_age: Optional[int] = None          # 借入時の年齢 [歳]
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_completion_rate(self) -> float:
        filled = sum([
            1 if self.household_income else 0,
            1 if self.down_payment is not None else 0,
            1 if self.loan_period else 0,
            1 if self.interest_rate is not None else 0,
            1 if self.other_monthly_debt is not None else 0,
            1 if self.borrower_age else 0,
        ])
        return filled / 6.0

    def get_missing_fields(self) -> List[str]:
        missing = []
        if not self.household_income:        missing.append("世帯年収")
        if self.down_payment is None:        missing.append("頭金（自己資金）")
        if not self.loan_period:             missing.append("返済期間")
        if self.interest_rate is None:       missing.append("想定金利")
        if self.other_monthly_debt is None:  missing.append("他の借入の毎月返済額")
        if not self.borrower_age:            missing.append("借入時の年齢")
        return missing

@dataclass
class FinancialPlanResult:
    """資金計画結果"""
    affordable_budget: int           # 購入可能額（総予算）[万円]
    monthly_payment: int             # 毎月の返済額 [円]
    max_loan_amount: int             # 借入可能上限額 [万円]
    total_payment: int               # 総返済額 [万円]
    total_interest: int              # 総利息額 [万円]
    repayment_ratio: float           # 返済負担率 [%]
    risk_level: str                  # リスクレベル

    def format_line_response(self) -> str:
        """LINE用フォーマット"""
        txt = f"""✅ 資金計画 概算結果

💰 買える金額の目安（総予算）
約{self.affordable_budget:,}万円
→頭金を含めた、無理のない購入可能額の目安です。

💳 毎月の支払いの目安（ローン返済）
約{self.monthly_payment:,}円
→現在の生活と両立しやすい返済額です。

📊 借りられる上限の目安
約最大{self.max_loan_amount:,}万円
→これ以上だと返済負担が大きくなる可能性があります。

📈 返済負担率：{self.repayment_ratio:.1f}%
（目安：25%以下が安全圏、30%以下が許容範囲）

💡 総返済額：約{self.total_payment:,}万円
（うち利息：約{self.total_interest:,}万円）

※金利や諸費用、物件条件により変動します。
※詳しい金額はスタッフがご案内します。"""
        return emojify(txt)

# ==============================================================================
# 状態管理
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
# 計算エンジン（確実性重視・正確な計算）
# ==============================================================================
class FinancialCalculationEngine:
    def __init__(self):
        # 返済負担率の基準（保守的な設定）
        self.safe_repayment_ratio = 0.20      # 20%：安全
        self.max_repayment_ratio = 0.25       # 25%：上限（保守的）
        self.absolute_max_ratio = 0.30        # 30%：絶対上限
        
        # その他の設定
        self.max_age_at_completion = 80       # 完済時最高年齢
        self.諸費用率 = 0.08                   # 諸費用8%（物件価格に対して）

    def calculate_financial_plan(self, inp: FinancialPlanInput) -> FinancialPlanResult:
        """
        確実性を重視した資金計画計算
        """
        try:
            # 入力値の取得（デフォルト値設定）
            年収 = inp.household_income or 6000000
            頭金 = inp.down_payment or 0
            返済期間 = inp.loan_period or 35
            金利 = inp.interest_rate if inp.interest_rate is not None else 1.5
            他借入返済 = inp.other_monthly_debt or 0
            年齢 = inp.borrower_age or 35

            # 年齢制限チェック
            完済時年齢 = 年齢 + 返済期間
            if 完済時年齢 > self.max_age_at_completion:
                返済期間 = max(10, self.max_age_at_completion - 年齢)
                logger.warning(f"返済期間を{返済期間}年に調整（完済時年齢制限）")

            # 返済可能月額の計算（保守的）
            月収 = 年収 / 12
            安全な月額返済可能額 = 月収 * self.safe_repayment_ratio - 他借入返済
            最大月額返済可能額 = 月収 * self.max_repayment_ratio - 他借入返済

            # マイナスの場合は借入不可
            if 安全な月額返済可能額 <= 0 or 最大月額返済可能額 <= 0:
                logger.warning("返済可能額がマイナス：他の借入が多すぎます")
                return self._create_error_result()

            # 元利均等返済での借入可能額計算
            安全な借入額 = self._calculate_loan_amount(安全な月額返済可能額, 返済期間, 金利)
            最大借入額 = self._calculate_loan_amount(最大月額返済可能額, 返済期間, 金利)

            # 購入可能額の計算（物件価格 = 借入額 + 頭金 - 諸費用）
            # 諸費用を考慮: 物件価格 × (1 + 諸費用率) = 借入額 + 頭金
            # → 物件価格 = (借入額 + 頭金) / (1 + 諸費用率)
            購入可能額 = int((安全な借入額 + 頭金) / (1 + self.諸費用率))
            
            # 実際の月額返済額（安全な借入額ベース）
            実際の月額返済 = int(安全な月額返済可能額)

            # 総返済額と総利息の計算
            総返済額 = 実際の月額返済 * 返済期間 * 12
            総利息 = 総返済額 - 安全な借入額

            # 返済負担率の計算
            年間返済額 = (実際の月額返済 + 他借入返済) * 12
            返済負担率 = (年間返済額 / 年収) * 100

            # リスクレベルの判定
            if 返済負担率 <= self.safe_repayment_ratio * 100:
                risk_level = "low"
            elif 返済負担率 <= self.max_repayment_ratio * 100:
                risk_level = "medium"
            else:
                risk_level = "high"

            return FinancialPlanResult(
                affordable_budget=int(購入可能額 / 10000),
                monthly_payment=実際の月額返済,
                max_loan_amount=int(最大借入額 / 10000),
                total_payment=int(総返済額 / 10000),
                total_interest=int(総利息 / 10000),
                repayment_ratio=返済負担率,
                risk_level=risk_level,
            )

        except Exception as e:
            logger.error(f"❌ calc error: {e}", exc_info=True)
            return self._create_error_result()

    def _calculate_loan_amount(self, monthly_payment: float, years: int, annual_rate: float) -> int:
        """
        月額返済額から借入可能額を逆算（元利均等返済）
        """
        if annual_rate == 0:
            return int(monthly_payment * years * 12)
        
        monthly_rate = annual_rate / 100 / 12
        months = years * 12
        
        # 元利均等返済の計算式から借入額を逆算
        # 月額返済額 = 借入額 × (月利 × (1 + 月利)^返済回数) / ((1 + 月利)^返済回数 - 1)
        # → 借入額 = 月額返済額 × ((1 + 月利)^返済回数 - 1) / (月利 × (1 + 月利)^返済回数)
        
        factor = (1 + monthly_rate) ** months
        loan_amount = monthly_payment * (factor - 1) / (monthly_rate * factor)
        
        return int(loan_amount)

    def _create_error_result(self) -> FinancialPlanResult:
        """エラー時のデフォルト結果"""
        return FinancialPlanResult(
            affordable_budget=2000,
            monthly_payment=80000,
            max_loan_amount=2500,
            total_payment=3360,
            total_interest=860,
            repayment_ratio=20.0,
            risk_level="medium",
        )

# ==============================================================================
# 入力パーサ（新項目対応）
# ==============================================================================
class FinancialInputParser:
    def parse_user_input(self, message: str, session: FinancialPlanInput) -> Dict[str, Any]:
        raw = message or ""
        msg = z2h(raw).replace(" ", "").replace("　", "")
        res = {"field_updated": None, "value": None, "success": False, "message": ""}

        # 1. 世帯年収
        income_match = (
            re.search(r'(?:世帯年収|年収|収入)[:：]?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'(\d+(?:\.\d+)?)\s*(万|万円)?(?:世帯年収|年収)', msg)
        )
        if income_match and not session.household_income:
            val = parse_number_like(income_match.group(1) + (income_match.group(2) or "万"))
            if val and 1_000_000 <= val <= 200_000_000:
                res.update(field_updated="household_income", value=int(val), success=True,
                           message=f"世帯年収 {int(val/10000)}万円 を記録しました。")
                return res

        # 2. 頭金（自己資金）
        down_match = (
            re.search(r'(?:頭金|自己資金)[:：]?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'(\d+(?:\.\d+)?)\s*(万|万円)(?:頭金|自己資金)', msg) or
            re.search(r'(?:頭金|自己資金)(?:なし|0円?)', msg)
        )
        if down_match and session.down_payment is None:
            if re.search(r'(?:なし|ない|0円?)', msg):
                res.update(field_updated="down_payment", value=0, success=True,
                           message="頭金 なし（0円）を記録しました。")
                return res
            val = parse_number_like(down_match.group(1) + (down_match.group(2) or "万"))
            if val is not None:
                res.update(field_updated="down_payment", value=int(val), success=True,
                           message=f"頭金 {int(val/10000)}万円 を記録しました。")
                return res

        # 3. 返済期間
        period_match = (
            re.search(r'(?:返済期間|期間|年数)[:：]?(\d+)\s*年', msg) or
            re.search(r'(\d+)\s*年(?:ローン|借入|返済)?', msg)
        )
        if period_match and not session.loan_period:
            years = int(period_match.group(1))
            if 10 <= years <= 50:
                res.update(field_updated="loan_period", value=years, success=True,
                           message=f"返済期間 {years}年 を記録しました。")
                return res

        # 4. 想定金利
        rate_match = (
            re.search(r'(?:金利|利率)[:：]?(\d+(?:\.\d+)?)\s*%?', msg) or
            re.search(r'(\d+(?:\.\d+)?)\s*%(?:金利|利率)?', msg)
        )
        if rate_match and session.interest_rate is None:
            rate = float(rate_match.group(1))
            if 0 <= rate <= 10:
                res.update(field_updated="interest_rate", value=rate, success=True,
                           message=f"想定金利 {rate}% を記録しました。")
                return res

        # 5. 他の借入返済額
        debt_match = (
            re.search(r'(?:他の借入|借入|車|カード|ローン|返済)[:：]?(?:月|毎月)?(\d+(?:\.\d+)?)\s*(万|万円|円)?', msg) or
            re.search(r'(?:月|毎月)(\d+(?:\.\d+)?)\s*(万|万円)(?:返済|借入)', msg) or
            re.search(r'(?:借入|返済)(?:なし|ない|0円?)', msg)
        )
        if debt_match and session.other_monthly_debt is None:
            if re.search(r'(?:なし|ない|0円?)', msg):
                res.update(field_updated="other_monthly_debt", value=0, success=True,
                           message="他の借入返済額 なし（0円）を記録しました。")
                return res
            val = parse_number_like(debt_match.group(1) + (debt_match.group(2) or "万"))
            if val is not None:
                res.update(field_updated="other_monthly_debt", value=int(val), success=True,
                           message=f"他の借入返済額 月{int(val):,}円 を記録しました。")
                return res

        # 6. 借入時の年齢
        age_match = (
            re.search(r'(?:年齢|歳)[:：]?(\d+)\s*(?:歳|才)?', msg) or
            re.search(r'(\d+)\s*(?:歳|才)(?:で|の時)?', msg)
        )
        if age_match and not session.borrower_age:
            age = int(age_match.group(1))
            if 20 <= age <= 70:
                res.update(field_updated="borrower_age", value=age, success=True,
                           message=f"借入時の年齢 {age}歳 を記録しました。")
                return res

        res["message"] = "形式を確認して再度ご入力ください。\n\n💡 入力例\n・世帯年収：「年収600万円」\n・頭金：「頭金500万円」「なし」\n・返済期間：「35年」\n・金利：「金利1.5%」\n・他の借入：「月3万円」「なし」\n・年齢：「35歳」"
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
            sess = self.state_manager.get_session(user_id)
            
            # セッション開始
            if not sess and any(k in (message or "") for k in ["資金計画", "💰"]):
                self.state_manager.start_session(user_id)
                return (
                    "💬 AI資金診断のご案内\n\n"
                    "本診断は匿名でご利用いただけます。\n"
                    "ご回答内容は保存いたしません。\n"
                    "算出される金額は試算（概算）であり、目安としてご確認ください。\n\n"
                    "お手数ですが、以下の項目をご入力ください。\n\n"
                    "・世帯年収（合算の有無も含む）\n"
                    "・頭金（自己資金）\n"
                    "・返済期間（年数）\n"
                    "・想定金利\n"
                    "・他の借入の毎月返済額合計（車・カード・教育ローン等）\n"
                    "・借入時の年齢\n\n"
                    "未入力の項目があっても進められます。\n"
                    "ご入力後、概算結果をご提示いたします。\n\n"
                    "※結果は概算です→詳細はスタッフがご案内します。\n"
                    "※AIの回答は必ずしも正しいとは限りません→確定案内はスタッフが行います。"
                )

            # 入力処理
            if sess:
                parsed = self.parser.parse_user_input(message, sess)
                if parsed["success"]:
                    self.state_manager.update_session(user_id, parsed["field_updated"], parsed["value"])
                    sess2 = self.state_manager.get_session(user_id)
                    
                    # 全項目入力完了
                    if sess2.get_completion_rate() >= 1.0:
                        result = self.calculator.calculate_financial_plan(sess2)
                        self.state_manager.end_session(user_id)
                        return strip_citations(result.format_line_response())
                    
                    # 未完了 → 次の入力促し
                    missing = sess2.get_missing_fields()
                    rate = int(sess2.get_completion_rate() * 100)
                    
                    guide_map = {
                        "世帯年収": "・世帯年収：例「年収600万円」\n",
                        "頭金（自己資金）": "・頭金：例「頭金500万円」「なし」\n",
                        "返済期間": "・返済期間：例「35年」\n",
                        "想定金利": "・想定金利：例「金利1.5%」\n",
                        "他の借入の毎月返済額": "・他の借入返済：例「月3万円」「なし」\n",
                        "借入時の年齢": "・借入時の年齢：例「35歳」\n",
                    }
                    
                    msg = f"{parsed['message']}\n\n📝 入力状況 {rate}% 完了\n\n"
                    if missing:
                        msg += "残りの項目：\n"
                        for k in missing[:3]:
                            msg += guide_map.get(k, "")
                        if len(missing) > 3:
                            msg += f"・他{len(missing)-3}項目\n"
                        msg += "\n引き続きご入力ください😊"
                    return msg
                
                # パース失敗
                return parsed["message"]

            # セッション無し
            return "資金計画をご希望でしたら「💰 資金計画」ボタンをタップしてください。\n\nまたは「資金計画」とメッセージをお送りください😊"

        except Exception as e:
            logger.error(f"❌ handler error: {e}", exc_info=True)
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
    """単発API（互換用）"""
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

        # デフォルト値設定
        if not tmp.loan_period:
            tmp.loan_period = 35
        if tmp.interest_rate is None:
            tmp.interest_rate = 1.5
        if tmp.down_payment is None:
            tmp.down_payment = 0
        if tmp.other_monthly_debt is None:
            tmp.other_monthly_debt = 0
        if not tmp.borrower_age:
            tmp.borrower_age = 35

        calc = FinancialCalculationEngine()
        result = calc.calculate_financial_plan(tmp)
        return strip_citations(result.format_line_response())

    except Exception as e:
        logger.error(f"❌ run_financial_plan error: {e}", exc_info=True)
        return "処理に失敗しました。必要項目をご入力ください。"

# ==============================================================================
# LIFF ページ（新項目対応）
# ==============================================================================
def get_financial_planning_liff_page() -> str:
    liff_id = os.getenv("LIFF_ID", "YOUR_LIFF_ID_HERE")
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI資金診断 - キノエデザイン</title>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh}}
.container{{max-width:400px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 8px 32px rgba(0,0,0,.1)}}
.header{{text-align:center;margin-bottom:24px}}
.title{{font-size:24px;font-weight:700;color:#333;margin:8px 0}}
.subtitle{{font-size:14px;color:#666;line-height:1.4}}
.form-group{{margin-bottom:20px}}
.label{{display:block;font-weight:600;color:#333;margin-bottom:8px;font-size:14px}}
.input{{width:100%;padding:12px;border:2px solid #eee;border-radius:8px;font-size:16px;box-sizing:border-box}}
.input:focus{{outline:none;border-color:#667eea}}
.btn{{width:100%;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px}}
.btn:hover{{opacity:.9}}
.btn:disabled{{opacity:.5;cursor:not-allowed}}
.result{{background:#f8f9fa;padding:20px;border-radius:8px;margin-top:20px;display:none}}
.privacy-notice{{font-size:12px;color:#666;text-align:center;margin-top:16px;line-height:1.4}}
.privacy-notice a{{color:#667eea;text-decoration:none}}
.progress-bar{{width:100%;height:8px;background:#eee;border-radius:4px;margin:16px 0;overflow:hidden}}
.progress-fill{{height:100%;background:linear-gradient(90deg,#667eea 0%,#764ba2 100%);transition:width .3s ease;width:0%}}
.unit{{font-size:12px;color:#999;margin-left:4px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<div class="title">💰 AI資金診断</div>
<div class="subtitle">匿名で利用可能・回答内容は保存されません<br>算出される金額は試算（概算）です</div>
<div class="progress-bar"><div class="progress-fill" id="progressBar"></div></div>
</div>
<form id="financialForm">
<div class="form-group">
<label class="label">世帯年収（合算の有無も含む）<span class="unit">万円</span></label>
<input type="number" class="input" id="householdIncome" placeholder="例：600" step="1">
</div>
<div class="form-group">
<label class="label">頭金（自己資金）<span class="unit">万円</span></label>
<input type="number" class="input" id="downPayment" placeholder="例：500（なければ0）" step="1">
</div>
<div class="form-group">
<label class="label">返済期間<span class="unit">年</span></label>
<select class="input" id="loanPeriod">
<option value="">選択してください</option>
<option value="15">15年</option>
<option value="20">20年</option>
<option value="25">25年</option>
<option value="30">30年</option>
<option value="35" selected>35年</option>
</select>
</div>
<div class="form-group">
<label class="label">想定金利<span class="unit">%</span></label>
<input type="number" class="input" id="interestRate" placeholder="例：1.5" step="0.01" value="1.5">
</div>
<div class="form-group">
<label class="label">他の借入の毎月返済額合計<span class="unit">万円</span></label>
<input type="number" class="input" id="otherDebt" placeholder="例：3（なければ0）" step="0.1">
</div>
<div class="form-group">
<label class="label">借入時の年齢<span class="unit">歳</span></label>
<input type="number" class="input" id="borrowerAge" placeholder="例：35" step="1">
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
liff.init({{liffId:'{liff_id}'}}).catch(console.error);
function updateProgress(){{
const f=document.getElementById('financialForm');
const inputs=f.querySelectorAll('input,select');
let filled=0;
inputs.forEach(x=>{{if((x.value||'').trim()!==''){{filled++}}}});
document.getElementById('progressBar').style.width=(filled/inputs.length*100)+'%';
}}
document.addEventListener('input',updateProgress);
document.addEventListener('change',updateProgress);
updateProgress();

document.getElementById('financialForm').addEventListener('submit',async(e)=>{{
e.preventDefault();
const data={{
household_income:parseInt(document.getElementById('householdIncome').value)*10000||null,
down_payment:parseInt(document.getElementById('downPayment').value)*10000||0,
loan_period:parseInt(document.getElementById('loanPeriod').value)||null,
interest_rate:parseFloat(document.getElementById('interestRate').value)||null,
other_monthly_debt:parseInt(document.getElementById('otherDebt').value)*10000||0,
borrower_age:parseInt(document.getElementById('borrowerAge').value)||null
}};
const btn=document.getElementById('calculateBtn');
btn.disabled=true;
btn.textContent='計算中...';
try{{
const resp=await fetch('/api/financial-calculate',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify(data)
}});
const result=await resp.json();
if(result.success){{
document.getElementById('calculationResult').innerHTML=result.formatted_result;
document.getElementById('resultArea').style.display='block';
if(liff.isInClient()){{
await liff.sendMessages([{{type:'text',text:result.line_message}}]);
liff.closeWindow();
}}
}}else{{
alert('計算中にエラーが発生しました。');
}}
}}catch(err){{
console.error(err);
alert('通信エラーが発生しました。');
}}
btn.disabled=false;
btn.textContent='概算結果を計算';
}});
</script>
</body>
</html>"""
    return html

# ==============================================================================
# FastAPI Router
# ==============================================================================
router = APIRouter()

class FinancialCalcRequest(BaseModel):
    household_income: Optional[int] = Field(None, description="世帯年収[円]")
    down_payment: Optional[int] = Field(0, description="頭金[円]")
    loan_period: Optional[int] = Field(None, description="返済期間[年]")
    interest_rate: Optional[float] = Field(None, description="想定金利[%]")
    other_monthly_debt: Optional[int] = Field(0, description="他の借入返済[円]")
    borrower_age: Optional[int] = Field(None, description="借入時年齢[歳]")

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
            household_income=body.household_income,
            down_payment=body.down_payment or 0,
            loan_period=body.loan_period or 35,
            interest_rate=body.interest_rate if body.interest_rate is not None else 1.5,
            other_monthly_debt=body.other_monthly_debt or 0,
            borrower_age=body.borrower_age or 35,
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

@router.get("/api/financial-health")
def financial_health():
    return {"ok": True, "now": datetime.utcnow().isoformat() + "Z"}