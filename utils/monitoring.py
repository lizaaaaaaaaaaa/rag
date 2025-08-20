# ====================
# utils/monitoring.py
# ====================

import asyncio
import time
import psutil
import gc
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import deque
import logging
from database import get_db_context
from sqlalchemy import text
from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

@dataclass
class SystemMetrics:
    """システムメトリクス"""
    timestamp: str
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    process_count: int
    thread_count: int

@dataclass
class DatabaseMetrics:
    """データベースメトリクス"""
    timestamp: str
    active_connections: int
    total_connections: int
    query_count: int
    avg_query_time_ms: float
    slow_queries: int
    database_size_mb: float

class MetricsCollector:
    """メトリクス収集クラス"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.system_metrics_history: deque = deque(maxlen=max_history)
        self.database_metrics_history: deque = deque(maxlen=max_history)
        self.query_times: deque = deque(maxlen=1000)  # クエリ実行時間の履歴
        self.error_count = 0
        self.request_count = 0
        self.start_time = time.time()
    
    def collect_system_metrics(self) -> SystemMetrics:
        """システムメトリクスの収集"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # メモリ使用率
            memory = psutil.virtual_memory()
            
            # ディスク使用率
            disk = psutil.disk_usage('/')
            
            # プロセス情報
            process = psutil.Process()
            
            metrics = SystemMetrics(
                timestamp=datetime.utcnow().isoformat(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / 1024 / 1024,
                memory_available_mb=memory.available / 1024 / 1024,
                disk_usage_percent=disk.percent,
                disk_free_gb=disk.free / 1024 / 1024 / 1024,
                process_count=len(psutil.pids()),
                thread_count=process.num_threads()
            )
            
            self.system_metrics_history.append(metrics)
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            raise
    
    async def collect_database_metrics(self) -> DatabaseMetrics:
        """データベースメトリクスの収集"""
        try:
            async with get_db_context() as session:
                # アクティブ接続数の取得
                result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
                )
                active_connections = result.scalar()
                
                # 総接続数の取得
                result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity")
                )
                total_connections = result.scalar()
                
                # データベースサイズの取得
                result = await session.execute(
                    text("SELECT pg_size_pretty(pg_database_size(current_database()))")
                )
                db_size_str = result.scalar()
                
                # クエリ統計の取得
                result = await session.execute(
                    text("""
                        SELECT 
                            sum(calls) as query_count,
                            avg(mean_exec_time) as avg_query_time,
                            count(*) filter (where mean_exec_time > 1000) as slow_queries
                        FROM pg_stat_statements 
                        WHERE calls > 0
                    """)
                )
                query_stats = result.fetchone()
                
                # データベースサイズをMBに変換
                db_size_mb = self._parse_db_size(db_size_str)
                
                metrics = DatabaseMetrics(
                    timestamp=datetime.utcnow().isoformat(),
                    active_connections=active_connections or 0,
                    total_connections=total_connections or 0,
                    query_count=query_stats[0] if query_stats[0] else 0,
                    avg_query_time_ms=query_stats[1] if query_stats[1] else 0.0,
                    slow_queries=query_stats[2] if query_stats[2] else 0,
                    database_size_mb=db_size_mb
                )
                
                self.database_metrics_history.append(metrics)
                return metrics
                
        except Exception as e:
            logger.error(f"Failed to collect database metrics: {e}")
            # デフォルト値を返す
            return DatabaseMetrics(
                timestamp=datetime.utcnow().isoformat(),
                active_connections=0,
                total_connections=0,
                query_count=0,
                avg_query_time_ms=0.0,
                slow_queries=0,
                database_size_mb=0.0
            )
    
    def _parse_db_size(self, size_str: str) -> float:
        """データベースサイズ文字列をMBに変換"""
        try:
            if 'MB' in size_str:
                return float(size_str.replace(' MB', ''))
            elif 'GB' in size_str:
                return float(size_str.replace(' GB', '')) * 1024
            elif 'kB' in size_str:
                return float(size_str.replace(' kB', '')) / 1024
            else:
                return 0.0
        except:
            return 0.0
    
    def record_query_time(self, execution_time_ms: float):
        """クエリ実行時間の記録"""
        self.query_times.append(execution_time_ms)
    
    def increment_request_count(self):
        """リクエスト数のインクリメント"""
        self.request_count += 1
    
    def increment_error_count(self):
        """エラー数のインクリメント"""
        self.error_count += 1
    
    def get_application_metrics(self) -> Dict[str, Any]:
        """アプリケーションメトリクスの取得"""
        uptime_seconds = time.time() - self.start_time
        
        # クエリ時間の統計
        query_times_list = list(self.query_times)
        avg_query_time = sum(query_times_list) / len(query_times_list) if query_times_list else 0
        max_query_time = max(query_times_list) if query_times_list else 0
        min_query_time = min(query_times_list) if query_times_list else 0
        
        # ガベージコレクション情報
        gc_stats = gc.get_stats()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": uptime_seconds,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.request_count, 1),
            "query_metrics": {
                "avg_time_ms": avg_query_time,
                "max_time_ms": max_query_time,
                "min_time_ms": min_query_time,
                "total_queries": len(query_times_list)
            },
            "garbage_collection": {
                "collections": sum(stat['collections'] for stat in gc_stats),
                "collected": sum(stat['collected'] for stat in gc_stats),
                "uncollectable": sum(stat['uncollectable'] for stat in gc_stats)
            }
        }
    
    def get_recent_metrics(self, minutes: int = 5) -> Dict[str, Any]:
        """最近のメトリクス取得"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        
        # システムメトリクスのフィルタリング
        recent_system = [
            asdict(metric) for metric in self.system_metrics_history
            if datetime.fromisoformat(metric.timestamp) > cutoff_time
        ]
        
        # データベースメトリクスのフィルタリング
        recent_database = [
            asdict(metric) for metric in self.database_metrics_history
            if datetime.fromisoformat(metric.timestamp) > cutoff_time
        ]
        
        return {
            "period_minutes": minutes,
            "system_metrics": recent_system,
            "database_metrics": recent_database,
            "application_metrics": self.get_application_metrics()
        }
    
    async def generate_performance_report(self) -> Dict[str, Any]:
        """パフォーマンスレポートの生成"""
        current_system = self.collect_system_metrics()
        current_database = await self.collect_database_metrics()
        application_metrics = self.get_application_metrics()
        
        # アラートの生成
        alerts = []
        
        if current_system.cpu_percent > 80:
            alerts.append("High CPU usage detected")
        
        if current_system.memory_percent > 85:
            alerts.append("High memory usage detected")
        
        if current_system.disk_usage_percent > 90:
            alerts.append("Low disk space")
        
        if current_database.active_connections > 50:
            alerts.append("High database connection count")
        
        if application_metrics["error_rate"] > 0.05:  # 5%以上のエラー率
            alerts.append("High error rate detected")
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "current_metrics": {
                "system": asdict(current_system),
                "database": asdict(current_database),
                "application": application_metrics
            },
            "recent_trends": self.get_recent_metrics(30),
            "alerts": alerts,
            "recommendations": self._generate_recommendations(current_system, current_database, application_metrics)
        }
    
    def _generate_recommendations(
        self,
        system: SystemMetrics,
        database: DatabaseMetrics,
        application: Dict[str, Any]
    ) -> List[str]:
        """パフォーマンス改善の推奨事項生成"""
        recommendations = []
        
        if system.memory_percent > 70:
            recommendations.append("Consider increasing memory allocation or optimizing memory usage")
        
        if database.slow_queries > 10:
            recommendations.append("Review and optimize slow database queries")
        
        if application["error_rate"] > 0.01:
            recommendations.append("Investigate and fix recurring errors")
        
        if database.avg_query_time_ms > 100:
            recommendations.append("Database query optimization needed")
        
        if system.cpu_percent > 60:
            recommendations.append("Consider CPU optimization or scaling")
        
        return recommendations

# シングルトンインスタンス
metrics_collector = MetricsCollector()

# 便利関数
async def get_performance_report() -> Dict[str, Any]:
    """パフォーマンスレポート取得（便利関数）"""
    return await metrics_collector.generate_performance_report()

def record_query_execution(execution_time_ms: float):
    """クエリ実行時間記録（便利関数）"""
    metrics_collector.record_query_time(execution_time_ms)