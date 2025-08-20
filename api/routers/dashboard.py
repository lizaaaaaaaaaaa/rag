"""
監査ダッシュボード API ルーター
リアルタイム監査・統計・可視化

エンドポイント:
- GET /api/dashboard/overview - ダッシュボード概要
- GET /api/dashboard/real-time - リアルタイムデータ
- GET /api/dashboard/charts - チャートデータ
- GET /api/dashboard/alerts - アラート一覧
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db_session
from api.services.worm_service import EnhancedWORMManager

# ロギング設定
logger = logging.getLogger(__name__)

# ルーター作成
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ==================================================
# データモデル
# ==================================================

class DashboardOverview(BaseModel):
    """ダッシュボード概要"""
    generated_at: datetime
    
    # 基本統計
    total_consents: int
    active_consents: int
    withdrawn_consents: int
    expired_consents: int
    
    # 今日の統計
    today_new_consents: int
    today_withdrawals: int
    today_audit_logs: int
    
    # システム状況
    system_health: str
    worm_storage_health: str
    last_manifest_date: Optional[date]
    
    # アラート
    active_alerts: int
    critical_alerts: int

class RealTimeData(BaseModel):
    """リアルタイムデータ"""
    timestamp: datetime
    
    # 現在のメトリクス
    current_active_users: int
    current_consent_rate: float
    recent_activities: List[Dict[str, Any]]
    
    # パフォーマンス
    avg_response_time_ms: float
    error_rate_percent: float
    
    # 容量情報
    storage_usage_percent: float
    database_size_mb: float

class ChartData(BaseModel):
    """チャートデータ"""
    chart_type: str
    period: str
    data_points: List[Dict[str, Any]]
    labels: List[str]
    datasets: List[Dict[str, Any]]

class AlertInfo(BaseModel):
    """アラート情報"""
    alert_id: str
    alert_type: str
    severity: str
    title: str
    message: str
    created_at: datetime
    acknowledged: bool
    acknowledged_at: Optional[datetime]
    details: Dict[str, Any]

# ==================================================
# エンドポイント
# ==================================================

@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    worm_manager: EnhancedWORMManager = Depends()
):
    """ダッシュボード概要取得"""
    try:
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 基本同意統計
            consent_stats_query = text("""
                SELECT 
                    COUNT(*) as total_consents,
                    COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at > NOW()) as active_consents,
                    COUNT(*) FILTER (WHERE withdrawn = TRUE) as withdrawn_consents,
                    COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at <= NOW()) as expired_consents
                FROM consent_records
            """)
            
            consent_stats_result = await db.execute(consent_stats_query)
            consent_stats = consent_stats_result.fetchone()
            
            # 今日の統計
            today = date.today()
            today_stats_query = text("""
                SELECT 
                    COUNT(*) FILTER (WHERE table_name = 'consent_records' AND DATE(created_at) = :today) as today_consents,
                    COUNT(*) FILTER (WHERE table_name = 'consent_withdrawals' AND DATE(created_at) = :today) as today_withdrawals,
                    COUNT(*) FILTER (WHERE DATE(created_at) = :today) as today_audit_logs
                FROM audit_logs
                WHERE DATE(created_at) = :today
            """)
            
            today_stats_result = await db.execute(today_stats_query, {"today": today})
            today_stats = today_stats_result.fetchone()
            
            # システムヘルス確認
            worm_health = await worm_manager.health_check()
            worm_status = worm_health.get('status', 'unknown')
            
            # 最新マニフェスト日付確認
            try:
                manifest_query = text("""
                    SELECT MAX(stat_date) 
                    FROM daily_consent_stats 
                    WHERE generated_at IS NOT NULL
                """)
                manifest_result = await db.execute(manifest_query)
                last_manifest_date = manifest_result.scalar()
            except Exception:
                last_manifest_date = None
            
            # アクティブアラート数（簡易実装）
            active_alerts = 0
            critical_alerts = 0
            
            # システム全体の健康状態判定
            system_health = "healthy"
            if worm_status != "healthy":
                system_health = "degraded"
            if last_manifest_date and last_manifest_date < today - timedelta(days=2):
                system_health = "degraded"
            
            return DashboardOverview(
                generated_at=datetime.utcnow(),
                total_consents=consent_stats.total_consents or 0,
                active_consents=consent_stats.active_consents or 0,
                withdrawn_consents=consent_stats.withdrawn_consents or 0,
                expired_consents=consent_stats.expired_consents or 0,
                today_new_consents=today_stats.today_consents if today_stats else 0,
                today_withdrawals=today_stats.today_withdrawals if today_stats else 0,
                today_audit_logs=today_stats.today_audit_logs if today_stats else 0,
                system_health=system_health,
                worm_storage_health=worm_status,
                last_manifest_date=last_manifest_date,
                active_alerts=active_alerts,
                critical_alerts=critical_alerts
            )
            
    except Exception as e:
        logger.error(f"Failed to get dashboard overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/real-time", response_model=RealTimeData)
async def get_real_time_data():
    """リアルタイムデータ取得"""
    try:
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 最近のアクティビティ
            recent_activities_query = text("""
                SELECT 
                    action_type, table_name, created_at, success,
                    actor_type, actor_id
                FROM audit_logs 
                WHERE created_at >= NOW() - INTERVAL '1 hour'
                ORDER BY created_at DESC 
                LIMIT 20
            """)
            
            activities_result = await db.execute(recent_activities_query)
            activities = activities_result.fetchall()
            
            recent_activities = [
                {
                    "action": activity.action_type,
                    "table": activity.table_name,
                    "timestamp": activity.created_at.isoformat(),
                    "success": activity.success,
                    "actor": f"{activity.actor_type}:{activity.actor_id}"
                }
                for activity in activities
            ]
            
            # アクティブユーザー数（過去1時間）
            active_users_query = text("""
                SELECT COUNT(DISTINCT actor_id) 
                FROM audit_logs 
                WHERE created_at >= NOW() - INTERVAL '1 hour'
                AND actor_type = 'user'
            """)
            
            active_users_result = await db.execute(active_users_query)
            current_active_users = active_users_result.scalar() or 0
            
            # 同意率計算（過去24時間）
            consent_rate_query = text("""
                SELECT 
                    COUNT(*) FILTER (WHERE action_type = 'CREATE' AND table_name = 'consent_records') as consents,
                    COUNT(*) FILTER (WHERE action_type = 'CREATE' AND table_name = 'consent_withdrawals') as withdrawals
                FROM audit_logs 
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            
            consent_rate_result = await db.execute(consent_rate_query)
            consent_data = consent_rate_result.fetchone()
            
            total_actions = (consent_data.consents or 0) + (consent_data.withdrawals or 0)
            current_consent_rate = (
                (consent_data.consents / total_actions * 100) if total_actions > 0 else 0
            )
            
            # エラー率計算
            error_rate_query = text("""
                SELECT 
                    COUNT(*) as total_actions,
                    COUNT(*) FILTER (WHERE success = FALSE) as failed_actions
                FROM audit_logs 
                WHERE created_at >= NOW() - INTERVAL '1 hour'
            """)
            
            error_rate_result = await db.execute(error_rate_query)
            error_data = error_rate_result.fetchone()
            
            error_rate_percent = (
                (error_data.failed_actions / error_data.total_actions * 100) 
                if error_data.total_actions > 0 else 0
            )
            
            # データベースサイズ（簡易推定）
            db_size_query = text("""
                SELECT 
                    pg_size_pretty(pg_database_size(current_database())) as size_pretty,
                    pg_database_size(current_database()) as size_bytes
            """)
            
            try:
                db_size_result = await db.execute(db_size_query)
                db_size_data = db_size_result.fetchone()
                database_size_mb = db_size_data.size_bytes / (1024 * 1024) if db_size_data else 0
            except Exception:
                # PostgreSQL以外の場合
                database_size_mb = 0
            
            return RealTimeData(
                timestamp=datetime.utcnow(),
                current_active_users=current_active_users,
                current_consent_rate=current_consent_rate,
                recent_activities=recent_activities,
                avg_response_time_ms=150.0,  # 実際の実装ではメトリクスから取得
                error_rate_percent=error_rate_percent,
                storage_usage_percent=25.0,  # 実際の実装ではストレージ監視から取得
                database_size_mb=database_size_mb
            )
            
    except Exception as e:
        logger.error(f"Failed to get real-time data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/charts/{chart_type}")
async def get_chart_data(
    chart_type: str,
    period: str = Query("7d", description="期間 (1d, 7d, 30d, 90d)"),
    start_date: Optional[date] = Query(None, description="開始日"),
    end_date: Optional[date] = Query(None, description="終了日")
):
    """チャートデータ取得"""
    try:
        # 期間設定
        if start_date is None or end_date is None:
            end_date = date.today()
            if period == "1d":
                start_date = end_date
            elif period == "7d":
                start_date = end_date - timedelta(days=7)
            elif period == "30d":
                start_date = end_date - timedelta(days=30)
            elif period == "90d":
                start_date = end_date - timedelta(days=90)
            else:
                start_date = end_date - timedelta(days=7)
        
        async with get_db_session() as db:
            from sqlalchemy import text
            
            if chart_type == "consent_trend":
                # 同意傾向チャート
                query = text("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) FILTER (WHERE table_name = 'consent_records') as consents,
                        COUNT(*) FILTER (WHERE table_name = 'consent_withdrawals') as withdrawals
                    FROM audit_logs 
                    WHERE DATE(created_at) BETWEEN :start_date AND :end_date
                    AND action_type = 'CREATE'
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                
                result = await db.execute(query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                data = result.fetchall()
                
                labels = [row.date.isoformat() for row in data]
                datasets = [
                    {
                        "label": "新規同意",
                        "data": [row.consents for row in data],
                        "borderColor": "rgb(75, 192, 192)",
                        "backgroundColor": "rgba(75, 192, 192, 0.2)"
                    },
                    {
                        "label": "同意取り消し",
                        "data": [row.withdrawals for row in data],
                        "borderColor": "rgb(255, 99, 132)",
                        "backgroundColor": "rgba(255, 99, 132, 0.2)"
                    }
                ]
                
            elif chart_type == "user_activity":
                # ユーザーアクティビティチャート
                query = text("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(DISTINCT actor_id) as unique_users,
                        COUNT(*) as total_actions
                    FROM audit_logs 
                    WHERE DATE(created_at) BETWEEN :start_date AND :end_date
                    AND actor_type = 'user'
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                
                result = await db.execute(query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                data = result.fetchall()
                
                labels = [row.date.isoformat() for row in data]
                datasets = [
                    {
                        "label": "アクティブユーザー",
                        "data": [row.unique_users for row in data],
                        "borderColor": "rgb(54, 162, 235)",
                        "backgroundColor": "rgba(54, 162, 235, 0.2)"
                    },
                    {
                        "label": "総アクション数",
                        "data": [row.total_actions for row in data],
                        "borderColor": "rgb(255, 206, 86)",
                        "backgroundColor": "rgba(255, 206, 86, 0.2)"
                    }
                ]
                
            elif chart_type == "system_performance":
                # システムパフォーマンスチャート
                query = text("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as total_actions,
                        COUNT(*) FILTER (WHERE success = TRUE) as successful_actions,
                        AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100 as success_rate
                    FROM audit_logs 
                    WHERE DATE(created_at) BETWEEN :start_date AND :end_date
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                
                result = await db.execute(query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                data = result.fetchall()
                
                labels = [row.date.isoformat() for row in data]
                datasets = [
                    {
                        "label": "成功率 (%)",
                        "data": [float(row.success_rate or 0) for row in data],
                        "borderColor": "rgb(75, 192, 192)",
                        "backgroundColor": "rgba(75, 192, 192, 0.2)"
                    }
                ]
                
            else:
                raise HTTPException(status_code=400, detail=f"Unknown chart type: {chart_type}")
            
            return ChartData(
                chart_type=chart_type,
                period=period,
                data_points=[dict(row._mapping) for row in data],
                labels=labels,
                datasets=datasets
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get chart data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/alerts", response_model=List[AlertInfo])
async def get_dashboard_alerts(
    severity: Optional[str] = Query(None, description="重要度フィルター"),
    acknowledged: Optional[bool] = Query(None, description="確認済みフィルター"),
    limit: int = Query(50, description="取得件数上限")
):
    """アラート一覧取得"""
    try:
        # 実際の実装では、アラートテーブルから取得
        # ここでは簡易的なサンプルアラートを生成
        
        sample_alerts = []
        
        # システムヘルスベースのアラート生成
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 最近のエラー確認
            error_query = text("""
                SELECT COUNT(*) 
                FROM audit_logs 
                WHERE success = FALSE 
                AND created_at >= NOW() - INTERVAL '1 hour'
            """)
            
            error_result = await db.execute(error_query)
            recent_errors = error_result.scalar() or 0
            
            if recent_errors > 10:
                sample_alerts.append(AlertInfo(
                    alert_id="alert_high_error_rate",
                    alert_type="SYSTEM_ERROR",
                    severity="HIGH",
                    title="高エラー率検出",
                    message=f"過去1時間で{recent_errors}件のエラーが発生しています",
                    created_at=datetime.utcnow() - timedelta(minutes=15),
                    acknowledged=False,
                    acknowledged_at=None,
                    details={"error_count": recent_errors, "threshold": 10}
                ))
            
            # 期限切れ同意確認
            expired_query = text("""
                SELECT COUNT(*) 
                FROM consent_records 
                WHERE expires_at < NOW() 
                AND withdrawn = FALSE
            """)
            
            expired_result = await db.execute(expired_query)
            expired_consents = expired_result.scalar() or 0
            
            if expired_consents > 0:
                sample_alerts.append(AlertInfo(
                    alert_id="alert_expired_consents",
                    alert_type="COMPLIANCE",
                    severity="MEDIUM",
                    title="期限切れ同意検出",
                    message=f"{expired_consents}件の期限切れ同意があります",
                    created_at=datetime.utcnow() - timedelta(hours=2),
                    acknowledged=False,
                    acknowledged_at=None,
                    details={"expired_count": expired_consents}
                ))
        
        # フィルタリング
        filtered_alerts = sample_alerts
        
        if severity:
            filtered_alerts = [a for a in filtered_alerts if a.severity == severity.upper()]
        
        if acknowledged is not None:
            filtered_alerts = [a for a in filtered_alerts if a.acknowledged == acknowledged]
        
        return filtered_alerts[:limit]
        
    except Exception as e:
        logger.error(f"Failed to get dashboard alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """アラート確認"""
    try:
        # 実際の実装では、アラートテーブルを更新
        acknowledged_at = datetime.utcnow()
        
        return {
            "message": "Alert acknowledged successfully",
            "alert_id": alert_id,
            "acknowledged_at": acknowledged_at.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to acknowledge alert: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export/csv")
async def export_dashboard_data(
    data_type: str = Query(..., description="エクスポートするデータタイプ"),
    start_date: date = Query(..., description="開始日"),
    end_date: date = Query(..., description="終了日")
):
    """ダッシュボードデータCSVエクスポート"""
    try:
        from fastapi.responses import StreamingResponse
        import csv
        import io
        
        # CSV データ準備
        output = io.StringIO()
        writer = csv.writer(output)
        
        if data_type == "consent_summary":
            async with get_db_session() as db:
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as total_consents,
                        COUNT(*) FILTER (WHERE withdrawn = FALSE) as active_consents,
                        COUNT(*) FILTER (WHERE withdrawn = TRUE) as withdrawn_consents
                    FROM consent_records 
                    WHERE DATE(created_at) BETWEEN :start_date AND :end_date
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                
                result = await db.execute(query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                
                # CSV ヘッダー
                writer.writerow(["Date", "Total Consents", "Active Consents", "Withdrawn Consents"])
                
                # データ行
                for row in result.fetchall():
                    writer.writerow([
                        row.date.isoformat(),
                        row.total_consents,
                        row.active_consents,
                        row.withdrawn_consents
                    ])
        
        output.seek(0)
        
        # レスポンス準備
        response = StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={data_type}_{start_date}_{end_date}.csv"}
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to export dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def dashboard_health():
    """ダッシュボードヘルスチェック"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {}
        }
        
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # データベース接続確認
            simple_query = text("SELECT 1")
            await db.execute(simple_query)
            health_status["checks"]["database_connection"] = True
            
            # 最近のデータ確認
            data_query = text("""
                SELECT COUNT(*) 
                FROM audit_logs 
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            
            data_result = await db.execute(data_query)
            recent_data = data_result.scalar() or 0
            
            health_status["checks"]["recent_data_available"] = recent_data > 0
            health_status["checks"]["recent_data_count"] = recent_data
        
        return health_status
        
    except Exception as e:
        logger.error(f"Dashboard health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# ==================================================
# エクスポート
# ==================================================

__all__ = ["router"]