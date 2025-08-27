# monitoring/dashboard.py - パフォーマンス監視ダッシュボード（完全修正版）

import asyncio
import time
import psutil
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

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


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


class SystemMetrics:
    """システム＆チャットメトリクス収集クラス（安全・軽量・依存性最小）"""

    def __init__(self):
        self.metrics_history: List[Dict[str, Any]] = []
        self.max_history_size = 1000
        self.collection_interval = 30  # 秒
        self.is_collecting = False
        self._task: asyncio.Task | None = None
        self.start_time = time.time()

        # cpu_percent の初回 0.0 を避けるため prime
        try:
            psutil.cpu_percent(interval=None)
            psutil.Process().cpu_percent(interval=None)
        except Exception:
            pass

    async def start_collection(self):
        """メトリクス収集開始"""
        if self.is_collecting and self._task and not self._task.done():
            return

        self.is_collecting = True
        self._task = asyncio.create_task(self._collect_metrics_loop())
        logger.info("📊 System metrics collection started")

    async def stop_collection(self):
        """メトリクス収集停止"""
        self.is_collecting = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("📊 System metrics collection stopped")

    async def _collect_metrics_loop(self):
        """メトリクス収集ループ"""
        try:
            while self.is_collecting:
                try:
                    metrics = await self._collect_current_metrics()
                    # 履歴に追加
                    self.metrics_history.append(metrics)
                    # 履歴サイズ制限
                    if len(self.metrics_history) > self.max_history_size:
                        self.metrics_history.pop(0)
                except Exception as e:
                    logger.error(f"Metrics collection error: {e}")

                await asyncio.sleep(self.collection_interval)
        except asyncio.CancelledError:
            # stop_collection() からのキャンセル
            pass
        except Exception as e:
            logger.error(f"Metrics loop fatal error: {e}")

    async def _collect_current_metrics(self) -> Dict[str, Any]:
        """現在のメトリクス収集（ブロッキングを避ける）"""
        try:
            # システムメトリクス（ノンブロッキング）
            cpu_percent = _safe_float(psutil.cpu_percent(interval=None))
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # プロセスメトリクス（ノンブロッキング／権限差異に強い）
            process = psutil.Process()
            process_memory = process.memory_info()
            proc_cpu = _safe_float(process.cpu_percent(interval=None))
            num_threads = process.num_threads()
            # 非推奨／権限要件の高いコネクション参照は削除（問題の温床だった）
            # connections = len(process.connections())  # ← 削除

            # チャットシステムメトリクス（外部依存が無ければゼロ値）
            chat_metrics = await self._collect_chat_metrics()

            timestamp = datetime.now().isoformat()

            return {
                "timestamp": timestamp,
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_total": int(memory.total),
                    "memory_used": int(memory.used),
                    "memory_percent": _safe_float(memory.percent),
                    "memory_available": int(memory.available),
                    "disk_total": int(disk.total),
                    "disk_used": int(disk.used),
                    "disk_percent": _safe_float(disk.percent),
                },
                "process": {
                    "memory_rss": int(process_memory.rss),
                    "memory_vms": int(process_memory.vms),
                    "cpu_percent": proc_cpu,
                    "num_threads": int(num_threads),
                },
                "chat_system": chat_metrics,
            }

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            }

    async def _collect_chat_metrics(self) -> Dict[str, Any]:
        """チャットシステム固有メトリクス収集（安全デフォルトを返す）"""

        # まずは安全なデフォルト
        defaults = {
            "cache": {"total_entries": 0, "hit_rate": 0.0, "utilization": 0.0},
            "templates": {"match_rate": 0.0, "total_requests": 0, "web_matches": 0, "line_matches": 0},
            "unified_router": {"total_requests": 0, "template_rate": 0.0, "rag_rate": 0.0, "cache_rate": 0.0},
            "rag": {
                "total_queries": 0,
                "success_rate": 0.0,
                "avg_retrieval_time": 0.0,
                "avg_generation_time": 0.0,
            },
            "enhancement": {
                "total_enhancements": 0,
                "avg_improvement_score": 0.0,
                "completeness_fixes": 0,
            },
        }

        try:
            # キャッシュ
            try:
                from utils.chat_cache import get_global_cache  # type: ignore
                cache_stats = get_global_cache().get_stats()  # 期待: dict
                defaults["cache"]["total_entries"] = int(
                    cache_stats.get("cache_sizes", {}).get("total", 0)
                )
                defaults["cache"]["hit_rate"] = _safe_float(
                    cache_stats.get("hit_rates", {}).get("overall", 0.0)
                )
                defaults["cache"]["utilization"] = _safe_float(
                    cache_stats.get("utilization", 0.0)
                )
            except Exception:
                pass

            # テンプレート
            try:
                from utils.chat_templates import get_template_manager  # type: ignore
                template_stats = get_template_manager().get_template_stats()
                perf = template_stats.get("performance", {})
                dist = template_stats.get("platform_distribution", {})
                defaults["templates"]["match_rate"] = _safe_float(perf.get("match_rate", 0.0))
                defaults["templates"]["total_requests"] = int(perf.get("total_requests", 0))
                defaults["templates"]["web_matches"] = int(dist.get("web_matches", 0))
                defaults["templates"]["line_matches"] = int(dist.get("line_matches", 0))
            except Exception:
                pass

            # 統合ルーター
            try:
                from api.routers.chat_unified import unified_generator  # type: ignore
                unified_stats = unified_generator.get_performance_stats()
                up = unified_stats.get("unified_performance", {})
                defaults["unified_router"]["total_requests"] = int(up.get("total_requests", 0))
                defaults["unified_router"]["template_rate"] = _safe_float(up.get("template_rate", 0.0))
                defaults["unified_router"]["rag_rate"] = _safe_float(up.get("rag_rate", 0.0))
                defaults["unified_router"]["cache_rate"] = _safe_float(up.get("cache_rate", 0.0))
            except Exception:
                pass

            # RAG サービス
            try:
                from services.rag_processing_service import get_rag_service  # type: ignore
                rag_stats = get_rag_service().get_service_stats()
                perf = rag_stats.get("performance", {})
                defaults["rag"]["total_queries"] = int(perf.get("total_queries", 0))
                defaults["rag"]["success_rate"] = _safe_float(perf.get("success_rate", 0.0))
                defaults["rag"]["avg_retrieval_time"] = _safe_float(perf.get("average_retrieval_time", 0.0))
                defaults["rag"]["avg_generation_time"] = _safe_float(perf.get("average_generation_time", 0.0))
            except Exception:
                pass

            # 応答品質向上サービス（存在しない環境でもゼロ値）
            try:
                enhancement_service = (
                    get_response_enhancement_service() if get_response_enhancement_service else None
                )
                if enhancement_service:
                    enhancement_stats = enhancement_service.get_service_stats()
                    perf = enhancement_stats.get("performance", {})
                    defaults["enhancement"]["total_enhancements"] = int(perf.get("total_enhancements", 0))
                    defaults["enhancement"]["avg_improvement_score"] = _safe_float(
                        perf.get("average_improvement_score", 0.0)
                    )
                    defaults["enhancement"]["completeness_fixes"] = int(perf.get("completeness_fixes", 0))
            except Exception:
                pass

            return defaults

        except Exception as e:
            logger.error(f"Error collecting chat metrics: {e}")
            return {"error": str(e)}

    def get_recent_metrics(self, minutes: int = 30) -> List[Dict[str, Any]]:
        """直近のメトリクス取得"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        recent_metrics: List[Dict[str, Any]] = []
        for metric in self.metrics_history:
            try:
                metric_time = datetime.fromisoformat(str(metric.get("timestamp")))
                if metric_time >= cutoff_time:
                    recent_metrics.append(metric)
            except Exception:
                continue
        return recent_metrics

    def get_summary_stats(self) -> Dict[str, Any]:
        """要約統計の取得（キー欠損に強い）"""
        if not self.metrics_history:
            return {}

        recent_metrics = self.get_recent_metrics(60)  # 過去1時間
        if not recent_metrics:
            return {}

        # CPU使用率の統計
        cpu_values = [
            _safe_float(m.get("system", {}).get("cpu_percent", 0.0))
            for m in recent_metrics
        ]

        # メモリ使用率の統計
        memory_values = [
            _safe_float(m.get("system", {}).get("memory_percent", 0.0))
            for m in recent_metrics
        ]

        # チャット応答時間の統計
        response_times: List[float] = []
        for m in recent_metrics:
            rag = m.get("chat_system", {}).get("rag") if isinstance(m.get("chat_system"), dict) else None
            if rag:
                total_time = _safe_float(rag.get("avg_retrieval_time", 0.0)) + _safe_float(
                    rag.get("avg_generation_time", 0.0)
                )
                if total_time > 0:
                    response_times.append(total_time)

        def _stat(values: List[float]) -> Dict[str, float | int]:
            return {
                "avg": (sum(values) / len(values)) if values else 0.0,
                "max": max(values) if values else 0.0,
                "min": min(values) if values else 0.0,
                "count": len(values),
            }

        return {
            "collection_duration": time.time() - self.start_time,
            "total_data_points": len(self.metrics_history),
            "recent_data_points": len(recent_metrics),
            "cpu_stats": {k: float(v) for k, v in _stat(cpu_values).items() if k != "count"} | {"count": _stat(cpu_values)["count"]},
            "memory_stats": {k: float(v) for k, v in _stat(memory_values).items() if k != "count"} | {"count": _stat(memory_values)["count"]},
            "response_time_stats": _stat(response_times),
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
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js" integrity="sha512-jh3aM9s7h1dZr6bY0oGx0mZCkqH4eN2uXoJwJX2Q1S4x2Gg5PZ2n9m7t0nQKQ1wzvI7rGJx2l9zGZ3x1S5Qq+w==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
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
        .metric-value { font-size: 2rem; font-weight: bold; margin-bottom: 0.5rem; }
        .chart-container {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07);
        }
        .chart-container h3 { color: #4a5568; margin-bottom: 1rem; font-size: 1.3rem; }
        .status-indicator { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 0.5rem; }
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
        .refresh-button:hover { transform: translateY(-1px); }
        .last-updated { color: #718096; font-size: 0.9rem; text-align: center; margin-top: 2rem; }
        .alerts { background: #fed7d7; border: 1px solid #feb2b2; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; display: none; }
        .alerts.show { display: block; }
        .performance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
            margin: 1rem 0;
        }
        .performance-item { background: #f7fafc; padding: 1rem; border-radius: 8px; border-left: 4px solid #667eea; }
        .performance-item strong { color: #2d3748; }
        @media (max-width: 768px) {
            .metrics-grid { grid-template-columns: 1fr; }
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

        <div class="metrics-grid" id="metrics-grid"></div>

        <div class="chart-container">
            <h3>📈 システムパフォーマンス (過去30分)</h3>
            <canvas id="performanceChart" width="400" height="200"></canvas>
        </div>

        <div class="chart-container">
            <h3>💬 チャットシステム統計</h3>
            <div class="performance-grid" id="chat-stats"></div>
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
                showAlert('データの更新中にエラーが発生しました: ' + (error?.message || error));
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
                addMetricCard('CPU使用率', Number(data.system.cpu_percent).toFixed(1) + '%', getHealthStatus(data.system.cpu_percent, 80, 90));
                addMetricCard('メモリ使用率', Number(data.system.memory_percent).toFixed(1) + '%', getHealthStatus(data.system.memory_percent, 70, 85));
                addMetricCard('ディスク使用率', Number(data.system.disk_percent).toFixed(1) + '%', getHealthStatus(data.system.disk_percent, 80, 90));
            }

            // プロセスメトリクス
            if (data.process) {
                const memoryMB = (Number(data.process.memory_rss) / 1024 / 1024);
                addMetricCard('プロセスメモリ', memoryMB.toFixed(1) + ' MB', getHealthStatus(memoryMB, 300, 500));
                addMetricCard('プロセスCPU', Number(data.process.cpu_percent).toFixed(1) + '%', getHealthStatus(data.process.cpu_percent, 50, 80));
                addMetricCard('スレッド数', Number(data.process.num_threads), getHealthStatus(Number(data.process.num_threads), 20, 30));
            }

            // チャットシステムメトリクス
            if (data.chat_system && data.chat_system.cache) {
                const hr = Number(data.chat_system.cache.hit_rate);
                addMetricCard('キャッシュヒット率', hr.toFixed(1) + '%', getHealthStatus(hr, 50, 30, true));
                addMetricCard('キャッシュエントリ数', Number(data.chat_system.cache.total_entries), '');
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

            const cpuData = data.map(item => item.system?.cpu_percent ?? 0);
            const memoryData = data.map(item => item.system?.memory_percent ?? 0);

            if (performanceChart) performanceChart.destroy();

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
                    plugins: { legend: { position: 'top' } },
                    scales: {
                        y: { beginAtZero: true, max: 100 }
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
                addPerformanceItem('総リクエスト数', Number(data.unified_router.total_requests));
                addPerformanceItem('テンプレート応答率', Number(data.unified_router.template_rate).toFixed(1) + '%');
                addPerformanceItem('RAG応答率', Number(data.unified_router.rag_rate).toFixed(1) + '%');
                addPerformanceItem('キャッシュ利用率', Number(data.unified_router.cache_rate).toFixed(1) + '%');
            }

            if (data.rag) {
                addPerformanceItem('RAG成功率', Number(data.rag.success_rate).toFixed(1) + '%');
                addPerformanceItem('平均検索時間', Number(data.rag.avg_retrieval_time).toFixed(3) + 's');
                addPerformanceItem('平均生成時間', Number(data.rag.avg_generation_time).toFixed(3) + 's');
            }

            if (data.enhancement) {
                addPerformanceItem('応答品質向上数', Number(data.enhancement.total_enhancements));
                addPerformanceItem('平均改善スコア', Number(data.enhancement.avg_improvement_score).toFixed(3));
            }
        }

        // ヘルパー関数
        function addMetricCard(title, value, status) {
            const grid = document.getElementById('metrics-grid');
            const card = document.createElement('div');
            card.className = 'metric-card';
            const statusIndicator = status ? `<span class="status-indicator status-${status}"></span>` : '';
            card.innerHTML = `<h3>${statusIndicator}${title}</h3><div class="metric-value">${value}</div>`;
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
            const v = Number(value);
            if (inverse) {
                if (v >= warningThreshold) return 'healthy';
                if (v >= errorThreshold) return 'warning';
                return 'error';
            } else {
                if (v < warningThreshold) return 'healthy';
                if (v < errorThreshold) return 'warning';
                return 'error';
            }
        }

        function showAlert(message) {
            const alertsDiv = document.getElementById('alerts');
            const alertContent = document.getElementById('alert-content');
            alertContent.textContent = message;
            alertsDiv.classList.add('show');
            setTimeout(() => alertsDiv.classList.remove('show'), 5000);
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
    """チャットシステム統計取得（依存が無い環境でもゼロ値で返す）"""
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
        uptime = time.time() - metrics_collector.start_time

        # 各コンポーネントのヘルスチェック
        health_status: Dict[str, Any] = {
            "monitoring_system": {
                "status": "healthy" if metrics_collector.is_collecting else "stopped",
                "uptime_seconds": uptime,
                "metrics_count": len(metrics_collector.metrics_history),
            }
        }

        # 統合チャットシステムのヘルスチェック（存在しなくても degrade にはしない）
        try:
            from utils.chat_cache import get_global_cache  # type: ignore
            from services.rag_processing_service import get_rag_service  # type: ignore

            cache_health = get_global_cache().get_cache_health()
            rag_health = get_rag_service().health_check()

            health_status["chat_system"] = {
                "cache_status": cache_health.get("status", "unknown"),
                "rag_status": rag_health.get("status", "unknown"),
                "cache_issues": cache_health.get("issues", []),
                "rag_issues": rag_health.get("issues", []),
            }
        except Exception as e:
            health_status["chat_system"] = {"note": "optional component not available", "detail": str(e)}

        overall_healthy = health_status["monitoring_system"]["status"] == "healthy"
        return {
            "overall_status": "healthy" if overall_healthy else "degraded",
            "timestamp": datetime.now().isoformat(),
            "details": health_status,
        }

    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "overall_status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
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
            "metrics_data": recent_metrics,
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
