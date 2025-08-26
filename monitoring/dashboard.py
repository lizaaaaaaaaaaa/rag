# monitoring/dashboard.py - パフォーマンス監視ダッシュボード

import asyncio
import time
import psutil
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
# --- Robust import for enhancement service (handles VSCode/Pylance & runtime) ---
try:
    # Standard absolute import when project root is on sys.path
    from services.response_enhancement import get_response_enhancement_service  # type: ignore[reportMissingImports]
except Exception:
    try:
        # Fallback when running as a package (e.g., app context)
        from ..services.response_enhancement import get_response_enhancement_service  # type: ignore[reportRelativeImport, reportMissingImports]
    except Exception:  # Final fallback keeps dashboard alive even if module missing
        get_response_enhancement_service = None  # type: ignore


logger = logging.getLogger(__name__)

class SystemMetrics:
    """システムメトリクス収集クラス"""
    
    def __init__(self):
        self.metrics_history = []
        self.max_history_size = 1000
        self.collection_interval = 30  # 30秒間隔
        self.is_collecting = False
        self.start_time = time.time()

    async def start_collection(self):
        """メトリクス収集開始"""
        if self.is_collecting:
            return
        
        self.is_collecting = True
        asyncio.create_task(self._collect_metrics_loop())
        logger.info("📊 System metrics collection started")

    async def stop_collection(self):
        """メトリクス収集停止"""
        self.is_collecting = False
        logger.info("📊 System metrics collection stopped")

    async def _collect_metrics_loop(self):
        """メトリクス収集ループ"""
        while self.is_collecting:
            try:
                metrics = await self._collect_current_metrics()
                
                # 履歴に追加
                self.metrics_history.append(metrics)
                
                # 履歴サイズ制限
                if len(self.metrics_history) > self.max_history_size:
                    self.metrics_history.pop(0)
                
                await asyncio.sleep(self.collection_interval)
                
            except Exception as e:
                logger.error(f"Metrics collection error: {e}")
                await asyncio.sleep(self.collection_interval)

    async def _collect_current_metrics(self) -> Dict[str, Any]:
        """現在のメトリクス収集"""
        try:
            # システムメトリクス
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # プロセスメトリクス
            process = psutil.Process()
            process_memory = process.memory_info()
            
            # 統合チャットシステムメトリクス
            chat_metrics = await self._collect_chat_metrics()
            
            timestamp = datetime.now()
            
            return {
                "timestamp": timestamp.isoformat(),
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_total": memory.total,
                    "memory_used": memory.used,
                    "memory_percent": memory.percent,
                    "memory_available": memory.available,
                    "disk_total": disk.total,
                    "disk_used": disk.used,
                    "disk_percent": disk.percent
                },
                "process": {
                    "memory_rss": process_memory.rss,
                    "memory_vms": process_memory.vms,
                    "cpu_percent": process.cpu_percent(),
                    "num_threads": process.num_threads(),
                    "connections": len(process.connections())
                },
                "chat_system": chat_metrics
            }
            
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }

    async def _collect_chat_metrics(self) -> Dict[str, Any]:
        """チャットシステム固有メトリクス収集"""
        try:
            from utils.chat_cache import get_global_cache
            from utils.chat_templates import get_template_manager
            from api.routers.chat_unified import unified_generator
            from services.rag_processing_service import get_rag_service            # キャッシュメトリクス
            cache = get_global_cache()
            cache_stats = cache.get_stats()
            
            # テンプレートメトリクス
            template_manager = get_template_manager()
            template_stats = template_manager.get_template_stats()
            
            # 統合ルーターメトリクス
            unified_stats = unified_generator.get_performance_stats()
            
            # RAGサービスメトリクス
            rag_service = get_rag_service()
            rag_stats = rag_service.get_service_stats()
            
            # 応答品質向上メトリクス
            enhancement_service = get_response_enhancement_service() if get_response_enhancement_service else None
            enhancement_stats = enhancement_service.get_service_stats() if enhancement_service else {
                "performance": {"total_enhancements": 0, "average_improvement_score": 0.0, "completeness_fixes": 0}
            }
            
            return {
                "cache": {
                    "total_entries": cache_stats["cache_sizes"]["total"],
                    "hit_rate": cache_stats["hit_rates"]["overall"],
                    "utilization": cache_stats["utilization"]
                },
                "templates": {
                    "match_rate": template_stats["performance"]["match_rate"],
                    "total_requests": template_stats["performance"]["total_requests"],
                    "web_matches": template_stats["platform_distribution"]["web_matches"],
                    "line_matches": template_stats["platform_distribution"]["line_matches"]
                },
                "unified_router": {
                    "total_requests": unified_stats["unified_performance"]["total_requests"],
                    "template_rate": unified_stats["unified_performance"]["template_rate"],
                    "rag_rate": unified_stats["unified_performance"]["rag_rate"],
                    "cache_rate": unified_stats["unified_performance"]["cache_rate"]
                },
                "rag": {
                    "total_queries": rag_stats["performance"]["total_queries"],
                    "success_rate": rag_stats["performance"]["success_rate"],
                    "avg_retrieval_time": rag_stats["performance"]["average_retrieval_time"],
                    "avg_generation_time": rag_stats["performance"]["average_generation_time"]
                },
                "enhancement": {
                    "total_enhancements": enhancement_stats["performance"]["total_enhancements"],
                    "avg_improvement_score": enhancement_stats["performance"]["average_improvement_score"],
                    "completeness_fixes": enhancement_stats["performance"]["completeness_fixes"]
                }
            }
            
        except Exception as e:
            logger.error(f"Error collecting chat metrics: {e}")
            return {"error": str(e)}

    def get_recent_metrics(self, minutes: int = 30) -> List[Dict[str, Any]]:
        """直近のメトリクス取得"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        recent_metrics = []
        for metric in self.metrics_history:
            try:
                metric_time = datetime.fromisoformat(metric["timestamp"])
                if metric_time >= cutoff_time:
                    recent_metrics.append(metric)
            except:
                continue
        
        return recent_metrics

    def get_summary_stats(self) -> Dict[str, Any]:
        """要約統計の取得"""
        if not self.metrics_history:
            return {}
        
        recent_metrics = self.get_recent_metrics(60)  # 過去1時間
        
        if not recent_metrics:
            return {}
        
        # CPU使用率の統計
        cpu_values = [m["system"]["cpu_percent"] for m in recent_metrics if "system" in m]
        
        # メモリ使用率の統計
        memory_values = [m["system"]["memory_percent"] for m in recent_metrics if "system" in m]
        
        # チャット応答時間の統計
        response_times = []
        for m in recent_metrics:
            if "chat_system" in m and "rag" in m["chat_system"]:
                total_time = (m["chat_system"]["rag"]["avg_retrieval_time"] + 
                            m["chat_system"]["rag"]["avg_generation_time"])
                if total_time > 0:
                    response_times.append(total_time)
        
        return {
            "collection_duration": time.time() - self.start_time,
            "total_data_points": len(self.metrics_history),
            "recent_data_points": len(recent_metrics),
            "cpu_stats": {
                "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                "max": max(cpu_values) if cpu_values else 0,
                "min": min(cpu_values) if cpu_values else 0
            },
            "memory_stats": {
                "avg": sum(memory_values) / len(memory_values) if memory_values else 0,
                "max": max(memory_values) if memory_values else 0,
                "min": min(memory_values) if memory_values else 0
            },
            "response_time_stats": {
                "avg": sum(response_times) / len(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "min": min(response_times) if response_times else 0,
                "count": len(response_times)
            }
        }

# グローバルメトリクス収集インスタンス
metrics_collector = SystemMetrics()

# モニタリング用ルーター
monitoring_router = APIRouter()

@monitoring_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """ダッシュボードページ"""
    html_content = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>統合チャットシステム - パフォーマンス監視ダッシュボード</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem 0;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 2.5rem; margin-bottom: 0.5rem; }
        .header p { font-size: 1.2rem; opacity: 0.9; }
        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
            margin-bottom: 2rem;
        }
        .metric-card {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }
        .metric-card h3 {
            color: #4a5568;
            margin-bottom: 1rem;
            font-size: 1.1rem;
            display: flex;
            align-items: center;
        }
        .metric-card h3::before {
            content: '📊';
            margin-right: 0.5rem;
            font-size: 1.2rem;
        }
        .metric-value {
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }
        .metric-label {
            color: #718096;
            font-size: 0.9rem;
        }
        .chart-container {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07);
        }
        .chart-container h3 {
            color: #4a5568;
            margin-bottom: 1rem;
            font-size: 1.3rem;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 0.5rem;
        }
        .status-healthy { background-color: #48bb78; }
        .status-warning { background-color: #ed8936; }
        .status-error { background-color: #f56565; }
        .refresh-button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1rem;
            transition: transform 0.2s ease;
            margin-bottom: 1rem;
        }
        .refresh-button:hover {
            transform: translateY(-1px);
        }
        .last-updated {
            color: #718096;
            font-size: 0.9rem;
            text-align: center;
            margin-top: 2rem;
        }
        .alerts {
            background: #fed7d7;
            border: 1px solid #feb2b2;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            display: none;
        }
        .alerts.show { display: block; }
        .performance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin: 1rem 0;
        }
        .performance-item {
            background: #f7fafc;
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .performance-item strong {
            color: #2d3748;
        }
        @media (max-width: 768px) {
            .metrics-grid {
                grid-template-columns: 1fr;
            }
            .header h1 { font-size: 2rem; }
            .container { padding: 1rem; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 統合チャットシステム</h1>
        <p>パフォーマンス監視ダッシュボード</p>
    </div>
    
    <div class="container">
        <button class="refresh-button" onclick="refreshAllData()">🔄 データを更新</button>
        
        <div id="alerts" class="alerts">
            <strong>⚠️ アラート</strong>
            <div id="alert-content"></div>
        </div>
        
        <div class="metrics-grid" id="metrics-grid">
            <!-- メトリクスカードがここに動的に追加される -->
        </div>
        
        <div class="chart-container">
            <h3>📈 システムパフォーマンス (過去30分)</h3>
            <canvas id="performanceChart" width="400" height="200"></canvas>
        </div>
        
        <div class="chart-container">
            <h3>💬 チャットシステム統計</h3>
            <div class="performance-grid" id="chat-stats">
                <!-- チャット統計がここに表示される -->
            </div>
        </div>
        
        <div class="last-updated">
            最終更新: <span id="last-updated">--</span>
        </div>
    </div>

    <script>
        let performanceChart = null;
        
        // データ更新関数
        async function refreshAllData() {
            try {
                await updateMetrics();
                await updateChartData();
                await updateChatStats();
                
                document.getElementById('last-updated').textContent = new Date().toLocaleString('ja-JP');
            } catch (error) {
                console.error('Data refresh error:', error);
                showAlert('データの更新中にエラーが発生しました: ' + error.message);
            }
        }
        
        // メトリクス更新
        async function updateMetrics() {
            const response = await fetch('/monitoring/current-metrics');
            const data = await response.json();
            
            if (data.error) {
                showAlert('メトリクス取得エラー: ' + data.error);
                return;
            }
            
            const metricsGrid = document.getElementById('metrics-grid');
            metricsGrid.innerHTML = '';
            
            // システムメトリクス
            if (data.system) {
                addMetricCard('CPU使用率', data.system.cpu_percent.toFixed(1) + '%', getHealthStatus(data.system.cpu_percent, 80, 90));
                addMetricCard('メモリ使用率', data.system.memory_percent.toFixed(1) + '%', getHealthStatus(data.system.memory_percent, 70, 85));
                addMetricCard('ディスク使用率', data.system.disk_percent.toFixed(1) + '%', getHealthStatus(data.system.disk_percent, 80, 90));
            }
            
            // プロセスメトリクス
            if (data.process) {
                const memoryMB = (data.process.memory_rss / 1024 / 1024).toFixed(1);
                addMetricCard('プロセスメモリ', memoryMB + ' MB', getHealthStatus(parseFloat(memoryMB), 300, 500));
                addMetricCard('プロセスCPU', data.process.cpu_percent.toFixed(1) + '%', getHealthStatus(data.process.cpu_percent, 50, 80));
                addMetricCard('スレッド数', data.process.num_threads, getHealthStatus(data.process.num_threads, 20, 30));
            }
            
            // チャットシステムメトリクス
            if (data.chat_system && data.chat_system.cache) {
                addMetricCard('キャッシュヒット率', data.chat_system.cache.hit_rate.toFixed(1) + '%', getHealthStatus(data.chat_system.cache.hit_rate, 50, 30, true));
                addMetricCard('キャッシュエントリ数', data.chat_system.cache.total_entries, '');
            }
        }
        
        // チャート更新
        async function updateChartData() {
            const response = await fetch('/monitoring/recent-metrics?minutes=30');
            const data = await response.json();
            
            if (!data || data.length === 0) return;
            
            const labels = data.map(item => {
                const date = new Date(item.timestamp);
                return date.toLocaleTimeString('ja-JP', {hour: '2-digit', minute: '2-digit'});
            });
            
            const cpuData = data.map(item => item.system?.cpu_percent || 0);
            const memoryData = data.map(item => item.system?.memory_percent || 0);
            
            if (performanceChart) {
                performanceChart.destroy();
            }
            
            const ctx = document.getElementById('performanceChart').getContext('2d');
            performanceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'CPU使用率 (%)',
                            data: cpuData,
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.1)',
                            tension: 0.4
                        },
                        {
                            label: 'メモリ使用率 (%)',
                            data: memoryData,
                            borderColor: '#764ba2',
                            backgroundColor: 'rgba(118, 75, 162, 0.1)',
                            tension: 0.4
                        }
                    ]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'top',
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });
        }
        
        // チャット統計更新
        async function updateChatStats() {
            const response = await fetch('/monitoring/chat-system-stats');
            const data = await response.json();
            
            const statsContainer = document.getElementById('chat-stats');
            statsContainer.innerHTML = '';
            
            if (data.unified_router) {
                addPerformanceItem('総リクエスト数', data.unified_router.total_requests);
                addPerformanceItem('テンプレート応答率', data.unified_router.template_rate.toFixed(1) + '%');
                addPerformanceItem('RAG応答率', data.unified_router.rag_rate.toFixed(1) + '%');
                addPerformanceItem('キャッシュ利用率', data.unified_router.cache_rate.toFixed(1) + '%');
            }
            
            if (data.rag) {
                addPerformanceItem('RAG成功率', data.rag.success_rate.toFixed(1) + '%');
                addPerformanceItem('平均検索時間', data.rag.avg_retrieval_time.toFixed(3) + 's');
                addPerformanceItem('平均生成時間', data.rag.avg_generation_time.toFixed(3) + 's');
            }
            
            if (data.enhancement) {
                addPerformanceItem('応答品質向上数', data.enhancement.total_enhancements);
                addPerformanceItem('平均改善スコア', data.enhancement.avg_improvement_score.toFixed(3));
            }
        }
        
        // ヘルパー関数
        function addMetricCard(title, value, status) {
            const grid = document.getElementById('metrics-grid');
            const card = document.createElement('div');
            card.className = 'metric-card';
            
            const statusIndicator = status ? `<span class="status-indicator status-${status}"></span>` : '';
            
            card.innerHTML = `
                <h3>${statusIndicator}${title}</h3>
                <div class="metric-value">${value}</div>
            `;
            
            grid.appendChild(card);
        }
        
        function addPerformanceItem(label, value) {
            const container = document.getElementById('chat-stats');
            const item = document.createElement('div');
            item.className = 'performance-item';
            item.innerHTML = `<strong>${label}:</strong> ${value}`;
            container.appendChild(item);
        }
        
        function getHealthStatus(value, warningThreshold, errorThreshold, inverse = false) {
            if (inverse) {
                if (value >= warningThreshold) return 'healthy';
                if (value >= errorThreshold) return 'warning';
                return 'error';
            } else {
                if (value < warningThreshold) return 'healthy';
                if (value < errorThreshold) return 'warning';
                return 'error';
            }
        }
        
        function showAlert(message) {
            const alertsDiv = document.getElementById('alerts');
            const alertContent = document.getElementById('alert-content');
            alertContent.textContent = message;
            alertsDiv.classList.add('show');
            
            setTimeout(() => {
                alertsDiv.classList.remove('show');
            }, 5000);
        }
        
        // 初期化
        document.addEventListener('DOMContentLoaded', function() {
            refreshAllData();
            
            // 30秒毎に自動更新
            setInterval(refreshAllData, 30000);
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)

@monitoring_router.get("/current-metrics")
async def get_current_metrics():
    """現在のメトリクス取得"""
    try:
        current_metrics = await metrics_collector._collect_current_metrics()
        return current_metrics
    except Exception as e:
        logger.error(f"Error getting current metrics: {e}")
        return {"error": str(e)}

@monitoring_router.get("/recent-metrics")
async def get_recent_metrics(minutes: int = 30):
    """直近のメトリクス取得"""
    try:
        recent_metrics = metrics_collector.get_recent_metrics(minutes)
        return recent_metrics
    except Exception as e:
        logger.error(f"Error getting recent metrics: {e}")
        return {"error": str(e)}

@monitoring_router.get("/summary-stats")
async def get_summary_stats():
    """要約統計取得"""
    try:
        summary = metrics_collector.get_summary_stats()
        return summary
    except Exception as e:
        logger.error(f"Error getting summary stats: {e}")
        return {"error": str(e)}

@monitoring_router.get("/chat-system-stats")
async def get_chat_system_stats():
    """チャットシステム統計取得"""
    try:
        chat_metrics = await metrics_collector._collect_chat_metrics()
        return chat_metrics
    except Exception as e:
        logger.error(f"Error getting chat system stats: {e}")
        return {"error": str(e)}

@monitoring_router.get("/health-check")
async def monitoring_health_check():
    """監視システム自体のヘルスチェック"""
    try:
        current_time = datetime.now()
        uptime = time.time() - metrics_collector.start_time
        
        # 各コンポーネントのヘルスチェック
        health_status = {
            "monitoring_system": {
                "status": "healthy" if metrics_collector.is_collecting else "stopped",
                "uptime_seconds": uptime,
                "metrics_count": len(metrics_collector.metrics_history)
            }
        }
        
        # 統合チャットシステムのヘルスチェック
        try:
            from utils.chat_cache import get_global_cache
            from services.rag_processing_service import get_rag_service
            
            cache_health = get_global_cache().get_cache_health()
            rag_health = get_rag_service().health_check()
            
            health_status["chat_system"] = {
                "cache_status": cache_health["status"],
                "rag_status": rag_health["status"],
                "cache_issues": cache_health.get("issues", []),
                "rag_issues": rag_health.get("issues", [])
            }
            
        except Exception as e:
            health_status["chat_system"] = {"error": str(e)}
        
        # 全体的な健康状態判定
        overall_healthy = (
            health_status["monitoring_system"]["status"] == "healthy" and
            health_status.get("chat_system", {}).get("cache_status") != "error" and
            health_status.get("chat_system", {}).get("rag_status") != "error"
        )
        
        return {
            "overall_status": "healthy" if overall_healthy else "degraded",
            "timestamp": current_time.isoformat(),
            "details": health_status
        }
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "overall_status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@monitoring_router.post("/start-collection")
async def start_metrics_collection():
    """メトリクス収集開始"""
    await metrics_collector.start_collection()
    return {"status": "started", "message": "Metrics collection started"}

@monitoring_router.post("/stop-collection")
async def stop_metrics_collection():
    """メトリクス収集停止"""
    await metrics_collector.stop_collection()
    return {"status": "stopped", "message": "Metrics collection stopped"}

@monitoring_router.get("/export-metrics")
async def export_metrics():
    """メトリクス履歴エクスポート"""
    try:
        summary = metrics_collector.get_summary_stats()
        recent_metrics = metrics_collector.get_recent_metrics(60)  # 過去1時間
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "summary": summary,
            "metrics_data": recent_metrics
        }
        
        return export_data
        
    except Exception as e:
        logger.error(f"Metrics export error: {e}")
        return {"error": str(e)}

# 自動開始用の初期化関数
async def initialize_monitoring():
    """監視システム初期化"""
    try:
        await metrics_collector.start_collection()
        logger.info("🎯 Monitoring system initialized successfully")
    except Exception as e:
        logger.error(f"Monitoring initialization error: {e}")

# main.pyに追加するためのルーター登録関数
def register_monitoring_router(app):
    """メインアプリケーションに監視ルーターを登録"""
    app.include_router(monitoring_router, prefix="/monitoring", tags=["monitoring"])
    
    # 起動時に監視システムを開始
    @app.on_event("startup")
    async def startup_monitoring():
        await initialize_monitoring()
    
    logger.info("📊 Monitoring dashboard registered at /monitoring/dashboard")