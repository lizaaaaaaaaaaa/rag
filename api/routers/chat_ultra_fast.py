# api/routers/chat_ultra_fast.py - 超高速Webチャット応答システム

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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 超高速キャッシュシステム
class UltraFastCache:
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def _generate_key(self, query: str) -> str:
        """クエリからキャッシュキーを生成"""
        normalized = query.lower().strip()[:200]  # 200文字に制限
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
            "query_original": query[:100]  # デバッグ用
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

# 超高速応答生成クラス
class UltraFastResponseGenerator:
    def __init__(self):
        self.cache = UltraFastCache(max_size=500)
        self.response_templates = self._load_response_templates()
        
    def _load_response_templates(self) -> Dict[str, str]:
        """頻出質問の回答テンプレート"""
        return {
            "坪単価": "坪単価については、標準仕様で約70〜85万円/坪が目安となります。お客様のご希望される仕様や設備によって変動いたしますので、詳細なお見積りをご提供いたします。",
            "標準仕様": "標準仕様については、耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。",
            "断熱性能": "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能で、一年中快適にお過ごしいただけます。",
            "耐震性能": "耐震性能については、耐震等級3を標準とし、地震に強い安心・安全な住まいをご提供しています。構造計算に基づいた確かな技術で建築いたします。",
            "資料請求": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。",
            "見学予約": "展示場見学のご予約を承ります。ご希望の日時をお聞かせください。スタッフが丁寧にご案内いたします。"
        }
    
    async def generate_fast_response(self, query: str, user: str) -> Dict[str, Any]:
        """超高速レスポンス生成"""
        start_time = time.time()
        
        try:
            # 1. キャッシュチェック（0.001秒以内）
            cached_response = self.cache.get(query)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "status": "ok"
                }
            
            # 2. テンプレート即座マッチング（0.01秒以内）
            template_response = self._match_template(query)
            if template_response:
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "status": "ok"
                }
                self.cache.set(query, result)
                return result
            
            # 3. 並列RAG処理（2秒タイムアウト）
            rag_response = await self._parallel_rag_processing(query)
            if rag_response:
                result = {
                    "answer": rag_response,
                    "processing_time": time.time() - start_time,
                    "source": "rag",
                    "status": "ok"
                }
                self.cache.set(query, result)
                return result
            
            # 4. 高速フォールバック
            fallback_response = self._generate_fallback(query)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "status": "ok"
            }
            return result
            
        except Exception as e:
            logger.error(f"Fast response generation error: {e}")
            return {
                "answer": "申し訳ございません。一時的にエラーが発生しました。再度お試しください。",
                "processing_time": time.time() - start_time,
                "source": "error",
                "status": "error"
            }
    
    def _match_template(self, query: str) -> Optional[str]:
        """テンプレートマッチング（超高速）"""
        query_lower = query.lower()
        
        for keyword, template in self.response_templates.items():
            if keyword in query_lower:
                logger.info(f"🎯 Template match: {keyword}")
                return template
        
        return None
    
    async def _parallel_rag_processing(self, query: str) -> Optional[str]:
        """並列RAG処理（タイムアウト付き）"""
        try:
            # アプリのグローバル変数を取得
            globals_dict = self._get_app_globals()
            rag_chain = globals_dict.get('rag_chain_template')
            
            if not rag_chain:
                return None
            
            # 非同期でRAG処理
            def run_rag():
                try:
                    result = rag_chain.invoke({"query": query})
                    return result.get("result", "")
                except Exception as e:
                    logger.error(f"RAG processing error: {e}")
                    return None
            
            # 2秒タイムアウトで実行
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = loop.run_in_executor(executor, run_rag)
                try:
                    rag_result = await asyncio.wait_for(future, timeout=2.0)
                    if rag_result and len(rag_result.strip()) > 10:
                        # 回答をクリーンアップ
                        cleaned = self._clean_rag_response(rag_result)
                        logger.info(f"⚡ Fast RAG success: {len(cleaned)} chars")
                        return cleaned
                except asyncio.TimeoutError:
                    logger.warning("⏰ RAG processing timeout (2s)")
                    return None
                    
        except Exception as e:
            logger.error(f"Parallel RAG error: {e}")
        
        return None
    
    def _clean_rag_response(self, raw_response: str) -> str:
        """RAG回答の高速クリーンアップ"""
        import re
        
        # 最小限のクリーンアップ
        cleaned = raw_response.strip()
        
        # 不要パターンを削除
        unwanted_patterns = [
            r"【[^】]*】",
            r"出典[:：][^\n]*",
            r"参考[:：][^\n]*",
            r"関連文書が見つかりました[:：]?\s*",
        ]
        
        for pattern in unwanted_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
        
        # 〜しましょうを除去
        cleaned = re.sub(r'[^\s]*しましょう[。！？]*', '', cleaned)
        
        # 文末調整
        if not cleaned.endswith(('。', '！', '？')):
            if cleaned.endswith('です') or cleaned.endswith('ます'):
                cleaned += '。'
        
        return cleaned.strip()
    
    def _generate_fallback(self, query: str) -> str:
        """高速フォールバック応答"""
        if "坪単価" in query or "価格" in query:
            return "坪単価については、約70〜85万円/坪が目安です。詳細なお見積りをご提供いたします。"
        elif "仕様" in query:
            return "住宅仕様について詳しくご案内いたします。展示場でご確認いただけます。"
        elif "性能" in query:
            return "住宅性能について詳しくご説明いたします。お気軽にお問い合わせください。"
        else:
            return "お尋ねの件について、詳しくはお問い合わせください。スタッフが丁寧にご対応いたします。"
    
    def _get_app_globals(self):
        """アプリのグローバル変数を取得"""
        try:
            import main
            return {
                'vectorstore': getattr(main, 'vectorstore', None),
                'rag_chain_template': getattr(main, 'rag_chain_template', None),
                'llm_instance': getattr(main, 'llm_instance', None)
            }
        except Exception as e:
            logger.error(f"Failed to get app globals: {e}")
            return {'vectorstore': None, 'rag_chain_template': None, 'llm_instance': None}

# リクエストモデル
class UltraFastChatRequest(BaseModel):
    question: str
    username: str | None = None

# グローバルインスタンス
ultra_fast_generator = UltraFastResponseGenerator()

@router.post("/", summary="Ultra Fast AI チャット")
async def ultra_fast_chat_endpoint(req: UltraFastChatRequest, request: Request):
    """超高速チャットエンドポイント（目標：1秒以内応答）"""
    
    overall_start = time.time()
    logger.info(f"🚀 Ultra fast processing: {req.question[:50]}...")
    
    try:
        # 超高速応答生成
        response = await ultra_fast_generator.generate_fast_response(
            req.question, 
            req.username or "web-user"
        )
        
        total_time = time.time() - overall_start
        
        # パフォーマンスログ
        logger.info(f"✅ Ultra fast response: {total_time:.3f}s, "
                   f"source={response.get('source')}, "
                   f"length={len(response.get('answer', ''))}")
        
        # 1秒を超えた場合は警告
        if total_time > 1.0:
            logger.warning(f"⚠️ Slow response detected: {total_time:.3f}s")
        
        return {
            "answer": response["answer"],
            "sources": [],  # ソース情報は非表示
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "target_achieved": total_time <= 1.0
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Ultra fast chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        return JSONResponse(
            status_code=500,
            content={
                "answer": f"システムエラーが発生しました。（エラーID: {error_id}）",
                "sources": [],
                "status": "error",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "target_achieved": False
                }
            }
        )

@router.post("", include_in_schema=False)
async def ultra_fast_chat_endpoint_slashless(req: UltraFastChatRequest, request: Request):
    """スラッシュなしエンドポイント"""
    return await ultra_fast_chat_endpoint(req, request)

# パフォーマンス監視エンドポイント
@router.get("/performance-stats")
def get_performance_stats():
    """パフォーマンス統計を取得"""
    cache_stats = ultra_fast_generator.cache.get_stats()
    
    return {
        "cache_performance": cache_stats,
        "response_templates": len(ultra_fast_generator.response_templates),
        "target_response_time": "1.0s",
        "optimization_features": [
            "Ultra Fast Cache",
            "Template Matching",
            "Parallel RAG Processing",
            "2s Timeout Protection",
            "Smart Fallback"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache")
def clear_ultra_fast_cache():
    """キャッシュをクリア"""
    old_stats = ultra_fast_generator.cache.get_stats()
    ultra_fast_generator.cache = UltraFastCache(max_size=500)
    
    return {
        "status": "cache_cleared",
        "previous_stats": old_stats,
        "new_cache_size": 0,
        "timestamp": datetime.now().isoformat()
    }

# テンプレート管理エンドポイント
@router.get("/response-templates")
def get_response_templates():
    """回答テンプレート一覧を取得"""
    return {
        "templates": ultra_fast_generator.response_templates,
        "count": len(ultra_fast_generator.response_templates),
        "timestamp": datetime.now().isoformat()
    }

@router.post("/add-template")
def add_response_template(keyword: str, response: str):
    """新しい回答テンプレートを追加"""
    ultra_fast_generator.response_templates[keyword] = response
    
    return {
        "status": "template_added",
        "keyword": keyword,
        "response_preview": response[:100] + "..." if len(response) > 100 else response,
        "total_templates": len(ultra_fast_generator.response_templates),
        "timestamp": datetime.now().isoformat()
    }