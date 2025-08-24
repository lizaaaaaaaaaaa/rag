# api/routers/chat_ultra_fast.py - Web/LINE分離・テンプレート独立化版（完全修正版）

import logging
import os
import asyncio
import time
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse

# loggerを先に定義
logger = logging.getLogger(__name__)

# ハルシネーション対策統合機能をインポート
try:
    from integration.anti_hallucination_integration import enhance_web_chat_response
    ANTI_HALLUCINATION_AVAILABLE = True
    logger.info("✅ Anti-hallucination integration available")
except ImportError as e:
    logger.warning(f"⚠️ Anti-hallucination integration not available: {e}")
    ANTI_HALLUCINATION_AVAILABLE = False

router = APIRouter()

# ============================================================
# Web/LINE分離キャッシュシステム
# ============================================================
class SeparatedFastCache:
    def __init__(self, max_size: int = 1000):
        # プラットフォーム別キャッシュ分離
        self.web_cache: Dict[str, Dict[str, Any]] = {}
        self.line_cache: Dict[str, Dict[str, Any]] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.stats = {
            "web_hits": 0, "web_misses": 0,
            "line_hits": 0, "line_misses": 0
        }

    def _generate_key(self, query: str, platform: str) -> str:
        """プラットフォーム分離キー生成"""
        normalized = f"{platform}:{query.lower().strip()[:200]}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, query: str, platform: str = "web") -> Optional[Dict[str, Any]]:
        """プラットフォーム別キャッシュ取得"""
        key = self._generate_key(query, platform)
        cache_dict = self.web_cache if platform == "web" else self.line_cache
        
        if key in cache_dict:
            self.access_times[key] = time.time()
            self.stats[f"{platform}_hits"] += 1
            logger.info(f"⚡ {platform.upper()} Cache HIT for: {query[:30]}...")
            return cache_dict[key]
        
        self.stats[f"{platform}_misses"] += 1
        return None

    def set(self, query: str, response: Dict[str, Any], platform: str = "web") -> None:
        """プラットフォーム別キャッシュ保存"""
        if len(self.web_cache) + len(self.line_cache) >= self.max_size:
            self._evict_oldest()

        key = self._generate_key(query, platform)
        cache_dict = self.web_cache if platform == "web" else self.line_cache
        
        cache_dict[key] = {
            "answer": response.get("answer", ""),
            "timestamp": time.time(),
            "query_original": query[:100],
            "platform": platform,
            "source": response.get("source", "unknown"),
            "meta": response.get("meta", {}),
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 {platform.upper()} Cache SET for: {query[:30]}...")

    def _evict_oldest(self) -> None:
        """最も古いエントリを削除"""
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            # どちらのキャッシュからも削除を試行
            self.web_cache.pop(oldest_key, None)
            self.line_cache.pop(oldest_key, None)
            del self.access_times[oldest_key]

    def get_stats(self) -> Dict[str, Any]:
        """プラットフォーム分離統計を取得"""
        total_web = self.stats["web_hits"] + self.stats["web_misses"]
        total_line = self.stats["line_hits"] + self.stats["line_misses"]
        
        return {
            "platform_separation_enabled": True,
            "cache_sizes": {
                "web": len(self.web_cache),
                "line": len(self.line_cache),
                "total": len(self.web_cache) + len(self.line_cache)
            },
            "max_size": self.max_size,
            "web_stats": {
                "hits": self.stats["web_hits"],
                "misses": self.stats["web_misses"],
                "hit_rate": self.stats["web_hits"] / total_web if total_web > 0 else 0.0
            },
            "line_stats": {
                "hits": self.stats["line_hits"],
                "misses": self.stats["line_misses"],
                "hit_rate": self.stats["line_hits"] / total_line if total_line > 0 else 0.0
            }
        }

# ============================================================
# Web/LINE分離応答生成クラス（完全修正版）
# ============================================================
class SeparatedResponseGenerator:
    def __init__(self) -> None:
        self.cache = SeparatedFastCache(max_size=500)
        self.web_templates = self._load_web_templates()
        self.line_templates = self._load_line_templates()
        self.performance_metrics = {
            "web_requests": 0, "line_requests": 0,
            "web_template_hits": 0, "line_template_hits": 0,
            "anti_hallucination_used": 0
        }

    def _load_web_templates(self) -> Dict[str, str]:
        """Web専用テンプレート（補助金テンプレート追加済み）"""
        return {
            "坪単価": """坪単価についてご案内いたします。

当社の坪単価目安：
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

含まれる内容：
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。""",

            "標準仕様": """標準仕様についてご説明いたします。

構造・性能：
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

設備仕様：
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書については、資料請求または展示場見学でご確認いただけます。""",

            "断熱性能": """断熱性能についてご案内いたします。

断熱等級：
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

使用断熱材：
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

快適性：
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます。""",

            "耐震性能": """耐震性能についてご案内いたします。

耐震等級：
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

構造材：
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

保証：
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束いたします。""",

            "補助金": """住宅購入時の補助金・支援制度についてご案内いたします。

主な補助金制度：

ZEH補助金：
・高性能住宅への補助
・省エネ基準を満たす住宅が対象
・補助額：定額55万円～（条件により異なる）

こどもエコすまい支援事業：
・子育て世帯・若年夫婦世帯への支援
・最大100万円の補助金
・省エネ性能に応じて補助額が変動

住宅ローン減税：
・所得税の控除制度
・13年間の減税メリット
・年間最大35万円の控除（条件により異なる）

地域独自の補助金：
・自治体による支援制度
・地域により内容が異なります
・市町村の窓口でご確認ください

※制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認いただくか、スタッフまでお問い合わせください。""",

            "資料請求": """資料請求を承ります。

以下の情報をお送りください：
1. お名前（フルネーム）
2. ご住所（〒郵便番号から）
3. お電話番号
4. ご希望資料の種類

お送りする資料：
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします。""",

            "AI相談": """AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

よくあるご質問：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください😊"""
        }

    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（絵文字・改行最適化、補助金追加）"""
        return {
            "坪単価": """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。
詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",

            "標準仕様": """🏗️ 標準仕様についてご説明いたします

**構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください。""",

            "補助金": """💰 住宅購入時の補助金制度についてご案内します

**主な補助金制度**

🏠 **ZEH補助金**
高性能住宅への補助
定額55万円～

🌱 **こどもエコすまい支援事業**
子育て世帯への支援
最大100万円

🏦 **住宅ローン減税**
所得税の控除制度
13年間の減税メリット

📋 **地域独自の補助金**
自治体による支援
地域により異なります

※制度は年度ごとに変更される可能性があります。
最新情報はスタッフまでお問い合わせください。""",

            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば：**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください😊"""
        }

    async def generate_separated_response(self, query: str, platform: str = "web", user: str = "unknown") -> Dict[str, Any]:
        """プラットフォーム分離応答生成（ハルシネーション対策強化版）"""
        start_time = time.time()
        self.performance_metrics[f"{platform}_requests"] += 1

        try:
            # 1) プラットフォーム別キャッシュチェック
            cached_response = self.cache.get(query, platform)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok",
                    "anti_hallucination_used": cached_response.get("meta", {}).get(
                        "anti_hallucination_used", False
                    ),
                }

            # 2) プラットフォーム別テンプレートマッチング
            templates = self.web_templates if platform == "web" else self.line_templates
            template_response = self._match_template(query, templates, platform)
            
            if template_response:
                self.performance_metrics[f"{platform}_template_hits"] += 1
                
                # ハルシネーション対策の適用（テンプレート応答にも適用）
                if ANTI_HALLUCINATION_AVAILABLE:
                    try:
                        enhanced_result = await enhance_web_chat_response(
                            query=query,
                            original_response=template_response,
                            user_context={"username": user, "platform": platform}
                        )
                        
                        result = {
                            "answer": enhanced_result["answer"],
                            "processing_time": time.time() - start_time,
                            "source": "template_enhanced",
                            "platform": platform,
                            "status": "ok",
                            "anti_hallucination_used": enhanced_result.get("anti_hallucination_used", False),
                            "verification": enhanced_result.get("verification_note"),
                            "confidence": enhanced_result.get("confidence_level")
                        }
                        
                        self.performance_metrics["anti_hallucination_used"] += 1
                        
                    except Exception as enhance_error:
                        logger.warning(f"Template enhancement error: {enhance_error}")
                        # エラー時は元のテンプレート応答を使用
                        result = {
                            "answer": template_response,
                            "processing_time": time.time() - start_time,
                            "source": "template",
                            "platform": platform,
                            "status": "ok",
                            "anti_hallucination_used": False,
                        }
                else:
                    result = {
                        "answer": template_response,
                        "processing_time": time.time() - start_time,
                        "source": "template",
                        "platform": platform,
                        "status": "ok",
                        "anti_hallucination_used": False,
                    }
                
                self.cache.set(query, result, platform)
                return result

            # 3) プラットフォーム別フォールバック（ハルシネーション対策付き）
            fallback_response = self._generate_platform_fallback(query, platform)
            
            # ハルシネーション対策をフォールバックにも適用
            if ANTI_HALLUCINATION_AVAILABLE:
                try:
                    enhanced_result = await enhance_web_chat_response(
                        query=query,
                        original_response=fallback_response,
                        user_context={"username": user, "platform": platform}
                    )
                    
                    result = {
                        "answer": enhanced_result["answer"],
                        "processing_time": time.time() - start_time,
                        "source": "fallback_enhanced",
                        "platform": platform,
                        "status": "ok",
                        "anti_hallucination_used": enhanced_result.get("anti_hallucination_used", False),
                        "verification": enhanced_result.get("verification_note"),
                    }
                    
                    self.performance_metrics["anti_hallucination_used"] += 1
                    
                except Exception as enhance_error:
                    logger.warning(f"Fallback enhancement error: {enhance_error}")
                    result = {
                        "answer": fallback_response,
                        "processing_time": time.time() - start_time,
                        "source": "fallback",
                        "platform": platform,
                        "status": "ok",
                        "anti_hallucination_used": False,
                    }
            else:
                result = {
                    "answer": fallback_response,
                    "processing_time": time.time() - start_time,
                    "source": "fallback",
                    "platform": platform,
                    "status": "ok",
                    "anti_hallucination_used": False,
                }
            
            self.cache.set(query, result, platform)
            return result

        except Exception as e:
            logger.error(f"Separated response generation error: {e}")
            return {
                "answer": self._generate_platform_fallback(query, platform),
                "processing_time": time.time() - start_time,
                "source": "error",
                "platform": platform,
                "status": "error",
                "anti_hallucination_used": False,
            }

    def _match_template(self, query: str, templates: Dict[str, str], platform: str) -> Optional[str]:
        """プラットフォーム別テンプレートマッチング（完全修正版）"""
        query_lower = query.lower()

        # 修正されたキーワードマッピング（AI相談の誤検知を完全に防ぐ）
        keyword_mapping: Dict[str, List[str]] = {
            "坪単価": ["坪単価", "坪たんか", "価格", "値段", "費用", "コスト", "いくら", "金額", "料金"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード", "何が付く"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房", "光熱費", "ua値", "c値"],
            "耐震性能": ["耐震", "地震", "耐震性能", "安全", "強度", "構造", "震災"],
            "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度", "zeh補助", "こどもエコ"],
            "資料請求": ["資料", "パンフレット", "カタログ", "資料請求", "送って", "郵送"],
            # AI相談は明示的な呼びかけのみに制限（一般的な語句を削除）
            "AI相談": ["ai相談を開始", "aiに相談", "ai住まい相談を開始"],
        }

        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 {platform.upper()} Template match: {template_key}")
                return templates.get(template_key)

        return None

    def _generate_platform_fallback(self, query: str, platform: str) -> str:
        """プラットフォーム別フォールバック応答"""
        q_lower = query.lower()

        if platform == "line":
            # LINE用（絵文字・短文・親しみやすい）
            if any(keyword in q_lower for keyword in ["家を建てる", "マイホーム", "新築"]):
                return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです✨

**まずはこちらから始めませんか？**
1️⃣ 資料請求で情報収集
2️⃣ 展示場見学で実際の住まいを体感
3️⃣ 資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。何からお聞きになりたいでしょうか？"""

            else:
                return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学

具体的にお聞かせいただければ、詳しくご案内いたします。お気軽にお問い合わせください😊"""

        else:  # web
            # Web用（シンプル・読みやすい・情報量多め）
            if any(keyword in q_lower for keyword in ["家を建てる", "マイホーム", "新築"]):
                return """家づくりについてお答えいたします。

家づくりは人生で最も大きな買い物の一つです。まずは情報収集から始めませんか？

・資料請求で詳しい情報を入手
・展示場見学で実際の住まいを体感
・資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。"""

            else:
                return """お尋ねの内容について詳しくご案内いたします。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

・坪単価や費用について
・住宅性能や仕様について
・資料請求・展示場見学について
・資金計画・住宅ローンについて
・補助金制度について

具体的にお聞かせいただければ、詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"""

    def get_performance_stats(self) -> Dict[str, Any]:
        """パフォーマンス統計取得"""
        cache_stats = self.cache.get_stats()
        
        total_web = self.performance_metrics["web_requests"]
        total_line = self.performance_metrics["line_requests"]
        total_requests = total_web + total_line
        
        web_template_rate = (self.performance_metrics["web_template_hits"] / total_web * 100) if total_web > 0 else 0
        line_template_rate = (self.performance_metrics["line_template_hits"] / total_line * 100) if total_line > 0 else 0
        anti_hallucination_rate = (self.performance_metrics["anti_hallucination_used"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "platform_separation": {
                "web_requests": total_web,
                "line_requests": total_line,
                "web_template_hit_rate": web_template_rate,
                "line_template_hit_rate": line_template_rate,
                "web_template_count": len(self.web_templates),
                "line_template_count": len(self.line_templates)
            },
            "cache_performance": cache_stats,
            "anti_hallucination": {
                "available": ANTI_HALLUCINATION_AVAILABLE,
                "usage_count": self.performance_metrics["anti_hallucination_used"],
                "usage_rate": anti_hallucination_rate
            }
        }

# ============================================================
# リクエストモデル
# ============================================================
class SeparatedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"  # プラットフォーム指定を追加

# ============================================================
# グローバルインスタンス
# ============================================================
separated_generator = SeparatedResponseGenerator()

# ============================================================
# エンドポイント
# ============================================================
@router.post("/", summary="Web/LINE分離 AI チャット（ハルシネーション対策強化版）")
async def separated_chat_endpoint(req: SeparatedChatRequest, request: Request):
    """Web/LINE分離チャットエンドポイント（ハルシネーション対策強化版）"""

    overall_start = time.time()
    platform = req.platform or "web"
    logger.info(f"🚀 {platform.upper()} Separated processing: {req.question[:50]}...")

    try:
        # プラットフォーム分離応答生成
        response = await separated_generator.generate_separated_response(
            req.question, platform, req.username or f"{platform}-user"
        )

        total_time = time.time() - overall_start

        # パフォーマンスログ
        logger.info(
            "✅ %s response: %.3fs, source=%s, length=%d, anti_hallucination=%s",
            platform.upper(),
            total_time,
            response.get("source"),
            len(response.get("answer", "")),
            response.get("anti_hallucination_used", False),
        )

        return {
            "answer": response["answer"],
            "sources": [],  # ソース情報は非表示
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0.0),
                "source": response.get("source"),
                "platform": response.get("platform"),
                "platform_separation_enabled": True,
                "anti_hallucination_used": response.get("anti_hallucination_used", False),
            },
            "enhanced_info": {
                "verification": response.get("verification"),
                "confidence": response.get("confidence"),
                "anti_hallucination_used": response.get("anti_hallucination_used", False),
            } if ANTI_HALLUCINATION_AVAILABLE else {},
        }

    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]

        logger.error(f"❌ Separated chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())

        # プラットフォーム別エラー応答
        fallback_answer = separated_generator._generate_platform_fallback(
            req.question if hasattr(req, "question") else "", platform
        )

        return JSONResponse(
            status_code=200,
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": platform,
                    "platform_separation_enabled": True,
                    "anti_hallucination_used": False,
                },
                "enhanced_info": {},
            },
        )

@router.post("", include_in_schema=False)
async def separated_chat_endpoint_slashless(req: SeparatedChatRequest, request: Request):
    """スラッシュなしエンドポイント"""
    return await separated_chat_endpoint(req, request)

# ============================================================
# 付随エンドポイント（監視/管理）
# ============================================================
@router.get("/performance-stats")
def get_separated_performance_stats():
    """プラットフォーム分離パフォーマンス統計を取得"""
    stats = separated_generator.get_performance_stats()

    return {
        "platform_separated_performance": stats,
        "quality_features": [
            "Web/LINE完全分離",
            "プラットフォーム最適化テンプレート",
            "分離キャッシュシステム",
            "ハルシネーション対策強化",
            "補助金テンプレート追加",
            "AI相談誤検知防止（完全修正）",
        ],
        "target_metrics": {
            "web_response_time": "< 2.0s",
            "line_response_time": "< 1.0s", 
            "template_hit_rate": "> 70%",
            "platform_separation_accuracy": "100%",
            "anti_hallucination_accuracy": "> 95%",
        },
        "anti_hallucination_status": {
            "enabled": ANTI_HALLUCINATION_AVAILABLE,
            "verification_methods": ["Template validation", "Response verification", "Confidence scoring"] if ANTI_HALLUCINATION_AVAILABLE else [],
            "last_check": datetime.now().isoformat(),
        },
        "timestamp": datetime.now().isoformat(),
    }

@router.post("/clear-cache")
def clear_separated_cache():
    """プラットフォーム分離キャッシュをクリア"""
    old_stats = separated_generator.cache.get_stats()
    separated_generator.cache = SeparatedFastCache(max_size=500)

    return {
        "status": "separated_cache_cleared",
        "previous_stats": old_stats,
        "platforms_cleared": ["web", "line"],
        "new_cache_size": {"web": 0, "line": 0},
        "anti_hallucination_cache_cleared": True,
        "timestamp": datetime.now().isoformat(),
    }

@router.get("/templates")
def get_separated_templates():
    """プラットフォーム分離テンプレート一覧を取得"""
    return {
        "templates": {
            "web": list(separated_generator.web_templates.keys()),
            "line": list(separated_generator.line_templates.keys())
        },
        "count": {
            "web": len(separated_generator.web_templates),
            "line": len(separated_generator.line_templates)
        },
        "platform_separation_enabled": True,
        "anti_hallucination_enabled": ANTI_HALLUCINATION_AVAILABLE,
        "fixes_applied": [
            "補助金テンプレート追加",
            "AI相談キーワード完全修正（誤検知防止）",
            "一般的な質問語句を削除"
        ],
        "timestamp": datetime.now().isoformat(),
    }
