# utils/cache.py (新規作成)
import os
import redis
import json
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class RAGCache:
    def __init__(self):
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(redis_url)
        self.cache_ttl = 3600  # 1時間
    
    def _get_cache_key(self, query: str) -> str:
        """クエリからキャッシュキーを生成"""
        return f"rag_cache:{hashlib.md5(query.encode()).hexdigest()}"
    
    def get(self, query: str) -> Optional[dict]:
        """キャッシュから回答を取得"""
        try:
            key = self._get_cache_key(query)
            cached_data = self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        return None
    
    def set(self, query: str, response: dict):
        """回答をキャッシュに保存"""
        try:
            key = self._get_cache_key(query)
            self.redis_client.setex(
                key, 
                self.cache_ttl, 
                json.dumps(response, ensure_ascii=False)
            )
        except Exception as e:
            logger.error(f"Cache set error: {e}")