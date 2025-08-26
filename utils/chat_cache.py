# utils/chat_cache.py - 統合キャッシュシステム（独立ユーティリティ）

import hashlib
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)

class ChatCacheManager:
    """チャット用統合キャッシュ管理システム"""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds  # Time To Live
        
        # プラットフォーム分離キャッシュ
        self.caches = {
            "web_general": {},
            "web_rag": {},
            "line_general": {},
            "line_rag": {},
            "template": {},  # プラットフォーム共通テンプレート
            "system": {}     # システム情報キャッシュ
        }
        
        # アクセス時刻管理
        self.access_times: Dict[str, float] = {}
        self.creation_times: Dict[str, float] = {}
        
        # 統計情報
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expired": 0,
            "total_requests": 0
        }
        
        # 定期クリーンアップ設定
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5分毎
        
        # 永続化設定（オプション）
        self.persistence_enabled = os.getenv("CACHE_PERSISTENCE", "false").lower() == "true"
        self.cache_file = "data/chat_cache.json"
        
        if self.persistence_enabled:
            self._load_from_disk()

    def _generate_cache_key(self, query: str, platform: str, cache_type: str, 
                          additional_params: Optional[Dict] = None) -> str:
        """統一キー生成"""
        # クエリの正規化
        normalized_query = query.lower().strip()[:500]  # 長いクエリを切り詰め
        
        # 追加パラメータの処理
        params_str = ""
        if additional_params:
            params_str = json.dumps(additional_params, sort_keys=True)
        
        # キー構成要素
        key_components = f"{platform}:{cache_type}:{normalized_query}:{params_str}"
        
        # ハッシュ化してキー生成
        return hashlib.md5(key_components.encode()).hexdigest()

    def get(self, query: str, platform: str = "web", cache_type: str = "general", 
            additional_params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """キャッシュ取得"""
        self.stats["total_requests"] += 1
        
        # 定期クリーンアップチェック
        if time.time() - self.last_cleanup > self.cleanup_interval:
            self._cleanup_expired()
        
        # キー生成とキャッシュ選択
        cache_key = self._generate_cache_key(query, platform, cache_type, additional_params)
        cache_name = f"{platform}_{cache_type}"
        
        if cache_name not in self.caches:
            cache_name = "system"  # フォールバック
        
        cache_dict = self.caches[cache_name]
        
        # キャッシュエントリ存在チェック
        if cache_key not in cache_dict:
            self.stats["misses"] += 1
            return None
        
        # TTLチェック
        if self._is_expired(cache_key):
            self._remove_entry(cache_key)
            self.stats["expired"] += 1
            self.stats["misses"] += 1
            return None
        
        # ヒット処理
        self.access_times[cache_key] = time.time()
        self.stats["hits"] += 1
        
        entry = cache_dict[cache_key]
        
        logger.info(f"🎯 Cache HIT ({platform}/{cache_type}): {query[:30]}...")
        
        return {
            "answer": entry["answer"],
            "sources": entry.get("sources", []),
            "metadata": entry.get("metadata", {}),
            "cached_at": entry["cached_at"],
            "hit_count": entry.get("hit_count", 0) + 1
        }

    def set(self, query: str, response: Dict[str, Any], platform: str = "web", 
            cache_type: str = "general", additional_params: Optional[Dict] = None,
            custom_ttl: Optional[int] = None) -> bool:
        """キャッシュ保存"""
        try:
            # 容量チェック・必要に応じて削除
            if self._total_cache_size() >= self.max_size:
                self._evict_lru()
            
            # キー生成とキャッシュ選択
            cache_key = self._generate_cache_key(query, platform, cache_type, additional_params)
            cache_name = f"{platform}_{cache_type}"
            
            if cache_name not in self.caches:
                cache_name = "system"
            
            cache_dict = self.caches[cache_name]
            
            # エントリ作成
            current_time = time.time()
            ttl = custom_ttl or self.ttl_seconds
            
            cache_entry = {
                "answer": response.get("answer", ""),
                "sources": response.get("sources", []),
                "metadata": {
                    "platform": platform,
                    "cache_type": cache_type,
                    "query_length": len(query),
                    "response_length": len(response.get("answer", "")),
                    "source": response.get("source", "unknown"),
                    "processing_time": response.get("processing_time", 0.0),
                    "ttl": ttl,
                    "additional_params": additional_params
                },
                "cached_at": current_time,
                "expires_at": current_time + ttl,
                "hit_count": 0,
                "query_hash": cache_key,
                "original_query": query[:100]  # デバッグ用
            }
            
            # 保存
            cache_dict[cache_key] = cache_entry
            self.access_times[cache_key] = current_time
            self.creation_times[cache_key] = current_time
            
            logger.info(f"💾 Cache SET ({platform}/{cache_type}): {query[:30]}... (TTL: {ttl}s)")
            
            # 永続化
            if self.persistence_enabled:
                self._save_to_disk_async()
            
            return True
            
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    def invalidate(self, query: str, platform: str = "web", cache_type: str = "general",
                   additional_params: Optional[Dict] = None) -> bool:
        """特定キャッシュの無効化"""
        cache_key = self._generate_cache_key(query, platform, cache_type, additional_params)
        return self._remove_entry(cache_key)

    def invalidate_pattern(self, pattern: str, platform: Optional[str] = None,
                          cache_type: Optional[str] = None) -> int:
        """パターンマッチングでキャッシュ無効化"""
        removed_count = 0
        
        for cache_name, cache_dict in self.caches.items():
            # プラットフォーム・タイプフィルタリング
            if platform and not cache_name.startswith(platform):
                continue
            if cache_type and cache_type not in cache_name:
                continue
            
            keys_to_remove = []
            for key, entry in cache_dict.items():
                if pattern in entry.get("original_query", "").lower():
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                if self._remove_entry(key):
                    removed_count += 1
        
        logger.info(f"🧹 Pattern invalidation '{pattern}': {removed_count} entries removed")
        return removed_count

    def clear_all(self, preserve_system: bool = True) -> Dict[str, int]:
        """全キャッシュクリア"""
        old_sizes = {}
        
        for cache_name, cache_dict in self.caches.items():
            if preserve_system and cache_name == "system":
                continue
            
            old_sizes[cache_name] = len(cache_dict)
            
            # キーの削除（access_times, creation_timesからも）
            keys_to_remove = list(cache_dict.keys())
            for key in keys_to_remove:
                self.access_times.pop(key, None)
                self.creation_times.pop(key, None)
            
            cache_dict.clear()
        
        # 統計リセット
        self.stats["hits"] = 0
        self.stats["misses"] = 0
        
        total_cleared = sum(old_sizes.values())
        logger.info(f"🗑️ Cache cleared: {total_cleared} entries removed")
        
        return old_sizes

    def get_stats(self) -> Dict[str, Any]:
        """詳細統計取得"""
        total_requests = self.stats["total_requests"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        # キャッシュ別サイズ
        cache_sizes = {name: len(cache) for name, cache in self.caches.items()}
        
        # TTL分布
        current_time = time.time()
        ttl_distribution = {"expired": 0, "expires_soon": 0, "healthy": 0}
        
        for cache_dict in self.caches.values():
            for entry in cache_dict.values():
                expires_at = entry.get("expires_at", current_time + self.ttl_seconds)
                time_left = expires_at - current_time
                
                if time_left <= 0:
                    ttl_distribution["expired"] += 1
                elif time_left <= 300:  # 5分以内
                    ttl_distribution["expires_soon"] += 1
                else:
                    ttl_distribution["healthy"] += 1
        
        return {
            "performance": {
                "hit_rate": hit_rate,
                "total_requests": total_requests,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "evictions": self.stats["evictions"],
                "expired": self.stats["expired"]
            },
            "cache_sizes": cache_sizes,
            "total_entries": sum(cache_sizes.values()),
            "max_size": self.max_size,
            "utilization": (sum(cache_sizes.values()) / self.max_size * 100),
            "ttl_distribution": ttl_distribution,
            "configuration": {
                "ttl_seconds": self.ttl_seconds,
                "cleanup_interval": self.cleanup_interval,
                "persistence_enabled": self.persistence_enabled
            },
            "last_cleanup": datetime.fromtimestamp(self.last_cleanup).isoformat(),
            "uptime": time.time() - self.creation_times.get("_system_start", time.time())
        }

    def get_cache_health(self) -> Dict[str, Any]:
        """キャッシュヘルスチェック"""
        stats = self.get_stats()
        
        health_status = "healthy"
        issues = []
        
        # ヒット率チェック
        if stats["performance"]["hit_rate"] < 50:
            health_status = "degraded"
            issues.append("Low hit rate")
        
        # 使用率チェック
        if stats["utilization"] > 90:
            health_status = "warning"
            issues.append("High memory utilization")
        
        # 期限切れエントリチェック
        if stats["ttl_distribution"]["expired"] > 100:
            health_status = "warning"
            issues.append("Many expired entries")
        
        return {
            "status": health_status,
            "issues": issues,
            "recommendations": self._get_health_recommendations(stats),
            "stats_summary": stats
        }

    def _is_expired(self, cache_key: str) -> bool:
        """TTL有効期限チェック"""
        # cache_keyからエントリを検索
        for cache_dict in self.caches.values():
            if cache_key in cache_dict:
                entry = cache_dict[cache_key]
                expires_at = entry.get("expires_at", 0)
                return time.time() > expires_at
        return True

    def _remove_entry(self, cache_key: str) -> bool:
        """エントリ削除"""
        removed = False
        
        for cache_dict in self.caches.values():
            if cache_key in cache_dict:
                del cache_dict[cache_key]
                removed = True
        
        self.access_times.pop(cache_key, None)
        self.creation_times.pop(cache_key, None)
        
        return removed

    def _total_cache_size(self) -> int:
        """総キャッシュサイズ"""
        return sum(len(cache) for cache in self.caches.values())

    def _evict_lru(self) -> bool:
        """LRU削除"""
        if not self.access_times:
            return False
        
        # 最も古いアクセス時刻のキーを取得
        oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        
        if self._remove_entry(oldest_key):
            self.stats["evictions"] += 1
            logger.debug(f"🗑️ LRU eviction: {oldest_key}")
            return True
        
        return False

    def _cleanup_expired(self) -> int:
        """期限切れエントリのクリーンアップ"""
        current_time = time.time()
        expired_keys = []
        
        for cache_dict in self.caches.values():
            for key, entry in cache_dict.items():
                expires_at = entry.get("expires_at", current_time + self.ttl_seconds)
                if current_time > expires_at:
                    expired_keys.append(key)
        
        removed_count = 0
        for key in expired_keys:
            if self._remove_entry(key):
                removed_count += 1
        
        self.last_cleanup = current_time
        
        if removed_count > 0:
            logger.info(f"🧹 Cleanup: {removed_count} expired entries removed")
        
        return removed_count

    def _get_health_recommendations(self, stats: Dict[str, Any]) -> List[str]:
        """ヘルス改善推奨事項"""
        recommendations = []
        
        if stats["performance"]["hit_rate"] < 50:
            recommendations.append("Consider increasing cache TTL or reviewing cache keys")
        
        if stats["utilization"] > 90:
            recommendations.append("Increase max_size or reduce TTL to prevent memory issues")
        
        if stats["performance"]["evictions"] > stats["performance"]["hits"] * 0.1:
            recommendations.append("High eviction rate - consider increasing cache size")
        
        if stats["ttl_distribution"]["expired"] > 50:
            recommendations.append("Run cleanup more frequently")
        
        return recommendations

    def _load_from_disk(self) -> bool:
        """ディスクからキャッシュ復元"""
        try:
            if not os.path.exists(self.cache_file):
                return False
            
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # キャッシュデータ復元
            self.caches = data.get("caches", self.caches)
            self.access_times = data.get("access_times", {})
            self.creation_times = data.get("creation_times", {})
            self.stats = data.get("stats", self.stats)
            
            # 期限切れエントリのクリーンアップ
            self._cleanup_expired()
            
            logger.info(f"📂 Cache loaded from disk: {self._total_cache_size()} entries")
            return True
            
        except Exception as e:
            logger.error(f"Cache load error: {e}")
            return False

    def _save_to_disk_async(self) -> None:
        """非同期ディスク保存"""
        try:
            import threading
            
            def save_worker():
                try:
                    os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                    
                    data = {
                        "caches": self.caches,
                        "access_times": self.access_times,
                        "creation_times": self.creation_times,
                        "stats": self.stats,
                        "saved_at": time.time()
                    }
                    
                    with open(self.cache_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    
                except Exception as e:
                    logger.error(f"Cache save error: {e}")
            
            thread = threading.Thread(target=save_worker, daemon=True)
            thread.start()
            
        except Exception as e:
            logger.error(f"Async cache save error: {e}")

# グローバルキャッシュインスタンス（シングルトン）
_global_cache_instance = None

def get_global_cache() -> ChatCacheManager:
    """グローバルキャッシュインスタンス取得"""
    global _global_cache_instance
    
    if _global_cache_instance is None:
        # 環境変数から設定読み込み
        max_size = int(os.getenv("CACHE_MAX_SIZE", "1000"))
        ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
        
        _global_cache_instance = ChatCacheManager(max_size=max_size, ttl_seconds=ttl_seconds)
        _global_cache_instance.creation_times["_system_start"] = time.time()
    
    return _global_cache_instance

def reset_global_cache() -> ChatCacheManager:
    """グローバルキャッシュリセット"""
    global _global_cache_instance
    _global_cache_instance = None
    return get_global_cache()

# 便利関数群
def quick_cache_get(query: str, platform: str = "web") -> Optional[str]:
    """クイックキャッシュ取得（回答のみ）"""
    cache = get_global_cache()
    result = cache.get(query, platform)
    return result["answer"] if result else None

def quick_cache_set(query: str, answer: str, platform: str = "web", 
                   source: str = "unknown") -> bool:
    """クイックキャッシュ保存"""
    cache = get_global_cache()
    response = {"answer": answer, "source": source}
    return cache.set(query, response, platform)

def cache_health_check() -> bool:
    """キャッシュヘルスチェック（簡易版）"""
    cache = get_global_cache()
    health = cache.get_cache_health()
    return health["status"] == "healthy"