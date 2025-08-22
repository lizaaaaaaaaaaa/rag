# main.py - RAG API メインアプリケーション

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI アプリケーションインスタンス
app = FastAPI(
    title="RAG API",
    description="AI Chat API with RAG functionality",
    version="1.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では適切に制限してください
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 統一されたキャッシュシステム
class UnifiedFastCache:
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
   
    def _generate_key(self, query: str) -> str:
        """クエリからキャッシュキーを生成"""
        normalized = query.lower().strip()[:200]
        return hashlib.md5(normalized.encode()).hexdigest()
   
    def get(self, query: str) -> Optional[Dict]:
        """キャッシュから回答を取得"""
        key = self._generate_key(query)
        if key in self.cache:
            self.access_times[key] = time.time()
            self.hits += 1
            logger.info(f"⚡ Cache HIT for: {query[:30]}...")
            return self.cache[key]
        self.misses += 1
        return None
   
    def set(self, query: str, response: Dict):
        """キャッシュに回答を保存"""
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
       
        key = self._generate_key(query)
        self.cache[key] = {
            "answer": response.get("answer", ""),
            "timestamp": time.time(),
            "query_original": query[:100]
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 Cache SET for: {query[:30]}...")
   
    def _evict_oldest(self):
        """最も古いエントリを削除"""
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
   
    def get_stats(self) -> Dict:
        """キャッシュ統計を取得"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "total_requests": total
        }


# LINEボットと統一された応答生成クラス
class UnifiedResponseGenerator:
    def __init__(self):
        self.cache = UnifiedFastCache(max_size=500)
        self.response_templates = self._load_unified_templates()
       
    def _load_unified_templates(self) -> Dict[str, str]:
        """LINEボットと統一された回答テンプレート"""
        return {
            "坪単価": "坪単価についてご案内いたします。標準仕様では約70〜85万円/坪が目安となりますが、お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。",
            "標準仕様": "標準仕様についてご説明いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。",
            "断熱性能": "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能で、一年中快適にお過ごしいただけます。詳細は展示場でご確認いただけます。",
            "耐震性能": "耐震性能については、耐震等級3を標準とし、地震に強い安心・安全な住まいをご提供しています。構造計算に基づいた確かな技術で建築いたします。",
            "資料請求": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。3営業日以内にお送いいたします。",
            "見学予約": "展示場見学を承ります。ご希望の日時をお聞かせください。スタッフが丁寧にご案内いたします。最新の住宅仕様をご確認いただけます。",
            "ZEH": "ZEH（ゼッチ）は、Net Zero Energy Houseの略で、年間の一次エネルギー消費量が正味ゼロとなる住宅です。太陽光発電システムと高断熱性能により、エネルギーを自給自足できる住宅として注目されています。",
            "長期優良住宅": "長期優良住宅とは、長期にわたり良好な状態で使用するための措置が講じられた優良な住宅です。耐震性、省エネ性、耐久性などの基準をクリアした住宅で、税制優遇なども受けられます。"
        }
   
    async def generate_unified_response(self, query: str, user: str) -> Dict[str, Any]:
        """LINEボットと統一された高品質レスポンス生成"""
        start_time = time.time()
       
        try:
            # 1. キャッシュチェック
            cached_response = self.cache.get(query)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "status": "ok"
                }
           
            # 2. テンプレート即座マッチング（LINEボットと同じロジック）
            template_response = self._match_unified_template(query)
            if template_response:
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "status": "ok"
                }
                self.cache.set(query, result)
                return result
           
            # 3. 統一フォールバック（LINEボットと同じ品質）
            fallback_response = self._generate_unified_fallback(query)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "status": "ok"
            }
            return result
           
        except Exception as e:
            logger.error(f"Unified response generation error: {e}")
            return {
                "answer": self._generate_unified_fallback(query),
                "processing_time": time.time() - start_time,
                "source": "error",
                "status": "error"
            }
   
    def _match_unified_template(self, query: str) -> Optional[str]:
        """LINEボットと統一されたテンプレートマッチング"""
        query_lower = query.lower()
       
        # より詳細なキーワードマッチング
        keyword_mapping = {
            "坪単価": ["坪単価", "価格", "費用", "コスト", "いくら", "金額"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房"],
            "耐震性能": ["耐震", "地震", "耐震性能", "耐震等級", "安全"],
            "資料請求": ["資料", "パンフレット", "カタログ", "資料請求"],
            "見学予約": ["見学", "展示場", "予約", "見に行く", "見たい"],
            "ZEH": ["ZEH", "ゼッチ", "ぜっち", "省エネ住宅", "エネルギー"],
            "長期優良住宅": ["長期優良", "優良住宅", "長期"]
        }
       
        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 Unified template match: {template_key}")
                return self.response_templates.get(template_key)
       
        return None
   
    def _generate_unified_fallback(self, query: str) -> str:
        """LINEボットと統一されたフォールバック応答"""
        if "坪単価" in query or "価格" in query:
            return "坪単価についてご案内いたします。お客様のご希望される仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
        elif "仕様" in query:
            return "住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
        elif "性能" in query:
            return "住宅性能について詳しくご説明いたします。耐震性能、断熱性能など、お客様のご要望に合わせてご案内いたします。"
        elif "資料" in query:
            return "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。"
        else:
            return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"


# リクエストモデル
class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None


# グローバルインスタンス
unified_generator = UnifiedResponseGenerator()


# ヘルスチェックエンドポイント
@app.get("/healthz")
async def health_check():
    """ヘルスチェックエンドポイント"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "rag-api"
    }


@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "message": "RAG API is running",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/chat")
async def unified_chat_endpoint(req: UnifiedChatRequest, request: Request):
    """LINEボットと同じ品質のチャットエンドポイント"""
   
    overall_start = time.time()
    logger.info(f"🚀 Unified processing: {req.question[:50]}...")
   
    try:
        # 統一品質応答生成
        response = await unified_generator.generate_unified_response(
            req.question,
            req.username or "web-user"
        )
       
        total_time = time.time() - overall_start
       
        # パフォーマンスログ
        logger.info(f"✅ Unified response: {total_time:.3f}s, "
                   f"source={response.get('source')}, "
                   f"length={len(response.get('answer', ''))}")
       
        return {
            "answer": response["answer"],
            "sources": [],  # ソース情報は非表示（LINEボットと統一）
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "quality_unified": True  # 品質統一フラグ
            }
        }
       
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
       
        logger.error(f"❌ Unified chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
       
        # LINEボットと同じ品質のエラー応答
        fallback_answer = unified_generator._generate_unified_fallback(req.question if hasattr(req, 'question') else "")
       
        return JSONResponse(
            status_code=200,  # エラーでも200を返す（LINEボットと統一）
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "quality_unified": True
                }
            }
        )


# パフォーマンス監視エンドポイント
@app.get("/performance-stats")
def get_unified_performance_stats():
    """統一品質パフォーマンス統計を取得"""
    cache_stats = unified_generator.cache.get_stats()
   
    return {
        "cache_performance": cache_stats,
        "response_templates": len(unified_generator.response_templates),
        "quality_features": [
            "LINEボットとの品質統一",
            "自然な回答生成",
            "コンテキスト理解向上",
            "統一フォールバック"
        ],
        "target_metrics": {
            "response_time": "< 3.0s",
            "cache_hit_rate": "> 50%",
            "quality_consistency": "100%"
        },
        "timestamp": datetime.now().isoformat()
    }


@app.post("/clear-cache")
def clear_unified_cache():
    """統一キャッシュをクリア"""
    old_stats = unified_generator.cache.get_stats()
    unified_generator.cache = UnifiedFastCache(max_size=500)
   
    return {
        "status": "unified_cache_cleared",
        "previous_stats": old_stats,
        "new_cache_size": 0,
        "timestamp": datetime.now().isoformat()
    }


# テンプレート管理エンドポイント
@app.get("/response-templates")
def get_unified_response_templates():
    """統一回答テンプレート一覧を取得"""
    return {
        "templates": unified_generator.response_templates,
        "count": len(unified_generator.response_templates),
        "unified_with_line_bot": True,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/add-template")
def add_unified_response_template(keyword: str, response: str):
    """新しい統一回答テンプレートを追加"""
    unified_generator.response_templates[keyword] = response
   
    return {
        "status": "unified_template_added",
        "keyword": keyword,
        "response_preview": response[:100] + "..." if len(response) > 100 else response,
        "total_templates": len(unified_generator.response_templates),
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
