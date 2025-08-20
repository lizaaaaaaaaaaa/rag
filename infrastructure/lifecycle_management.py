# infrastructure/lifecycle_management.py - 自動削除・ライフサイクル管理（完全修正版）

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from google.cloud import storage, firestore, scheduler_v1
from google.cloud import functions_v1
from google.cloud.scheduler_v1 import CloudSchedulerClient
from google.cloud.scheduler_v1.types import Job, PubsubTarget, UpdateJobRequest, CreateJobRequest
from google.protobuf import field_mask_pb2
import json

logger = logging.getLogger(__name__)

class DataLifecycleManager:
    """データライフサイクル管理システム"""
    
    def __init__(self):
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
        self.storage_client = storage.Client()
        self.firestore_client = firestore.Client()
        
        # 保持期間設定
        self.retention_policies = {
            "consent_logs": {"years": 5, "auto_delete": False},  # WORM保護、自動削除なし
            "chat_logs": {"years": 1, "max_years": 5, "auto_delete": True},
            "audit_logs": {"years": 7, "auto_delete": True},
            "analytics_data": {"months": 14, "max_months": 26, "auto_delete": True},
            "session_data": {"days": 30, "auto_delete": True},
            "temp_files": {"days": 7, "auto_delete": True}
        }
        
        # データベース接続設定
        self.db_config = {
            "host": os.getenv("DB_HOST"),
            "port": int(os.getenv("DB_PORT", 5432)),
            "database": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD")
        }
    
    async def run_lifecycle_cleanup(self) -> Dict[str, Any]:
        """ライフサイクル清掃を実行"""
        cleanup_id = f"lifecycle_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info(f"🧹 Starting lifecycle cleanup: {cleanup_id}")
        
        cleanup_results = {
            "cleanup_id": cleanup_id,
            "start_time": datetime.now().isoformat(),
            "data_types_processed": [],
            "total_deleted": 0,
            "errors": [],
            "summary": {}
        }
        
        try:
            # 1. チャットログの清掃
            chat_cleanup = await self._cleanup_chat_logs()
            cleanup_results["data_types_processed"].append(chat_cleanup)
            
            # 2. セッションデータの清掃
            session_cleanup = await self._cleanup_session_data()
            cleanup_results["data_types_processed"].append(session_cleanup)
            
            # 3. 一時ファイルの清掃
            temp_cleanup = await self._cleanup_temporary_files()
            cleanup_results["data_types_processed"].append(temp_cleanup)
            
            # 4. 分析データの清掃
            analytics_cleanup = await self._cleanup_analytics_data()
            cleanup_results["data_types_processed"].append(analytics_cleanup)
            
            # 5. 期限切れ監査ログの清掃
            audit_cleanup = await self._cleanup_old_audit_logs()
            cleanup_results["data_types_processed"].append(audit_cleanup)
            
            # 6. 結果集計
            cleanup_results["total_deleted"] = sum(
                result.get("deleted_count", 0) for result in cleanup_results["data_types_processed"]
            )
            cleanup_results["summary"] = self._generate_cleanup_summary(cleanup_results["data_types_processed"])
            
            # 7. 清掃結果をログに保存
            await self._save_cleanup_log(cleanup_results)
            
            cleanup_results["status"] = "completed"
            cleanup_results["end_time"] = datetime.now().isoformat()
            
            logger.info(f"✅ Lifecycle cleanup completed: {cleanup_results['total_deleted']} items deleted")
            
        except Exception as e:
            logger.error(f"❌ Lifecycle cleanup failed: {e}")
            cleanup_results["status"] = "failed"
            cleanup_results["error"] = str(e)
            cleanup_results["end_time"] = datetime.now().isoformat()
        
        return cleanup_results
    
    async def _cleanup_chat_logs(self) -> Dict[str, Any]:
        """チャットログの清掃"""
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 保持期間を超えたチャットログを特定
                    retention_date = datetime.now() - timedelta(days=365 * self.retention_policies["chat_logs"]["years"])
                    
                    # 削除対象を確認
                    cur.execute("""
                        SELECT COUNT(*) as expired_count
                        FROM chat_logs 
                        WHERE created_at < %s
                    """, (retention_date,))
                    
                    expired_count = cur.fetchone()["expired_count"]
                    
                    if expired_count > 0:
                        # 削除実行
                        cur.execute("""
                            DELETE FROM chat_logs 
                            WHERE created_at < %s
                        """, (retention_date,))
                        
                        deleted_count = cur.rowcount
                        conn.commit()
                        
                        logger.info(f"🗑️ Deleted {deleted_count} expired chat logs")
                    else:
                        deleted_count = 0
                        logger.info("ℹ️ No expired chat logs to delete")
            
            return {
                "data_type": "chat_logs",
                "status": "completed",
                "expired_count": expired_count,
                "deleted_count": deleted_count,
                "retention_policy": f"{self.retention_policies['chat_logs']['years']} years"
            }
            
        except Exception as e:
            logger.error(f"❌ Chat logs cleanup failed: {e}")
            return {
                "data_type": "chat_logs",
                "status": "failed",
                "error": str(e),
                "deleted_count": 0
            }
    
    async def _cleanup_session_data(self) -> Dict[str, Any]:
        """セッションデータの清掃"""
        try:
            with psycopg2.connect(**self.db_config) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # セッションテーブルがある場合の清掃
                    retention_date = datetime.now() - timedelta(days=self.retention_policies["session_data"]["days"])
                    
                    try:
                        cur.execute("""
                            DELETE FROM user_sessions 
                            WHERE last_activity < %s OR created_at < %s
                        """, (retention_date, retention_date))
                        
                        deleted_count = cur.rowcount
                        conn.commit()
                        
                        logger.info(f"🗑️ Deleted {deleted_count} expired sessions")
                        
                    except psycopg2.errors.UndefinedTable:
                        # テーブルが存在しない場合
                        deleted_count = 0
                        logger.info("ℹ️ No session table found")
            
            return {
                "data_type": "session_data",
                "status": "completed",
                "deleted_count": deleted_count,
                "retention_policy": f"{self.retention_policies['session_data']['days']} days"
            }
            
        except Exception as e:
            logger.error(f"❌ Session data cleanup failed: {e}")
            return {
                "data_type": "session_data",
                "status": "failed",
                "error": str(e),
                "deleted_count": 0
            }
    
    async def _cleanup_temporary_files(self) -> Dict[str, Any]:
        """一時ファイルの清掃（GCS）"""
        try:
            deleted_count = 0
            retention_date = datetime.now() - timedelta(days=self.retention_policies["temp_files"]["days"])
            
            # 一時ファイル用バケットの清掃
            temp_bucket_name = f"temp-files-{self.project_id}"
            
            try:
                bucket = self.storage_client.bucket(temp_bucket_name)
                blobs = bucket.list_blobs()
                
                for blob in blobs:
                    if blob.time_created and blob.time_created.replace(tzinfo=None) < retention_date:
                        blob.delete()
                        deleted_count += 1
                        
                logger.info(f"🗑️ Deleted {deleted_count} temporary files")
                
            except Exception as e:
                logger.warning(f"⚠️ Temp bucket cleanup warning: {e}")
            
            return {
                "data_type": "temporary_files",
                "status": "completed", 
                "deleted_count": deleted_count,
                "retention_policy": f"{self.retention_policies['temp_files']['days']} days"
            }
            
        except Exception as e:
            logger.error(f"❌ Temporary files cleanup failed: {e}")
            return {
                "data_type": "temporary_files",
                "status": "failed",
                "error": str(e),
                "deleted_count": 0
            }
    
    async def _cleanup_analytics_data(self) -> Dict[str, Any]:
        """分析データの清掃"""
        try:
            deleted_count = 0
            retention_months = self.retention_policies["analytics_data"]["months"]
            retention_date = datetime.now() - timedelta(days=30 * retention_months)
            
            # Firestore の分析データ清掃
            analytics_collection = self.firestore_client.collection("analytics_data")
            
            # 期限切れドキュメントのクエリ
            expired_docs = analytics_collection.where("timestamp", "<", retention_date).limit(100).stream()
            
            for doc in expired_docs:
                doc.reference.delete()
                deleted_count += 1
            
            logger.info(f"🗑️ Deleted {deleted_count} expired analytics records")
            
            return {
                "data_type": "analytics_data",
                "status": "completed",
                "deleted_count": deleted_count,
                "retention_policy": f"{retention_months} months"
            }
            
        except Exception as e:
            logger.error(f"❌ Analytics data cleanup failed: {e}")
            return {
                "data_type": "analytics_data",
                "status": "failed",
                "error": str(e),
                "deleted_count": 0
            }
    
    async def _cleanup_old_audit_logs(self) -> Dict[str, Any]:
        """古い監査ログの清掃"""
        try:
            deleted_count = 0
            retention_years = self.retention_policies["audit_logs"]["years"]
            retention_date = datetime.now() - timedelta(days=365 * retention_years)
            
            # Firestore の監査ログ清掃
            audit_collection = self.firestore_client.collection("audit_logs")
            
            # 期限切れドキュメントのクエリ
            expired_docs = audit_collection.where("start_time", "<", retention_date.isoformat()).limit(50).stream()
            
            for doc in expired_docs:
                doc.reference.delete()
                deleted_count += 1
            
            logger.info(f"🗑️ Deleted {deleted_count} expired audit logs")
            
            return {
                "data_type": "audit_logs",
                "status": "completed",
                "deleted_count": deleted_count,
                "retention_policy": f"{retention_years} years"
            }
            
        except Exception as e:
            logger.error(f"❌ Audit logs cleanup failed: {e}")
            return {
                "data_type": "audit_logs",
                "status": "failed",
                "error": str(e),
                "deleted_count": 0
            }
    
    def _generate_cleanup_summary(self, cleanup_results: List[Dict]) -> Dict[str, Any]:
        """清掃サマリーを生成"""
        successful_cleanups = [r for r in cleanup_results if r.get("status") == "completed"]
        failed_cleanups = [r for r in cleanup_results if r.get("status") == "failed"]
        
        return {
            "total_data_types": len(cleanup_results),
            "successful_cleanups": len(successful_cleanups),
            "failed_cleanups": len(failed_cleanups),
            "total_items_deleted": sum(r.get("deleted_count", 0) for r in cleanup_results),
            "success_rate": (len(successful_cleanups) / len(cleanup_results)) * 100 if cleanup_results else 0
        }
    
    async def _save_cleanup_log(self, cleanup_results: Dict[str, Any]):
        """清掃ログを保存"""
        try:
            # Firestore に保存
            doc_ref = self.firestore_client.collection("lifecycle_logs").document(cleanup_results["cleanup_id"])
            doc_ref.set({
                **cleanup_results,
                "saved_at": datetime.now().isoformat()
            })
            
            logger.info(f"💾 Cleanup log saved: {cleanup_results['cleanup_id']}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save cleanup log: {e}")

class RetentionPolicyManager:
    """保持期間ポリシー管理"""
    
    def __init__(self):
        self.firestore_client = firestore.Client()
    
    async def update_retention_policy(self, data_type: str, new_policy: Dict[str, Any]) -> bool:
        """保持期間ポリシーを更新"""
        try:
            doc_ref = self.firestore_client.collection("retention_policies").document(data_type)
            doc_ref.set({
                **new_policy,
                "updated_at": datetime.now().isoformat(),
                "updated_by": "system"
            })
            
            logger.info(f"📋 Retention policy updated for {data_type}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update retention policy: {e}")
            return False
    
    async def get_retention_policies(self) -> Dict[str, Any]:
        """全ての保持期間ポリシーを取得"""
        try:
            policies = {}
            docs = self.firestore_client.collection("retention_policies").stream()
            
            for doc in docs:
                policies[doc.id] = doc.to_dict()
            
            return policies
            
        except Exception as e:
            logger.error(f"❌ Failed to get retention policies: {e}")
            return {}
    
    async def validate_compliance(self) -> Dict[str, Any]:
        """保持期間コンプライアンスの検証"""
        try:
            validation_results = {
                "compliant_policies": [],
                "non_compliant_policies": [],
                "recommendations": []
            }
            
            policies = await self.get_retention_policies()
            
            for data_type, policy in policies.items():
                if self._is_policy_compliant(data_type, policy):
                    validation_results["compliant_policies"].append(data_type)
                else:
                    validation_results["non_compliant_policies"].append(data_type)
                    validation_results["recommendations"].append(
                        f"{data_type}: ポリシーがコンプライアンス要件を満たしていません"
                    )
            
            return validation_results
            
        except Exception as e:
            logger.error(f"❌ Compliance validation failed: {e}")
            return {"error": str(e)}
    
    def _is_policy_compliant(self, data_type: str, policy: Dict[str, Any]) -> bool:
        """ポリシーがコンプライアントかチェック"""
        # データタイプ別のコンプライアンス要件
        compliance_requirements = {
            "consent_logs": {"min_years": 5, "max_years": 5},
            "chat_logs": {"min_years": 1, "max_years": 5},
            "audit_logs": {"min_years": 7, "max_years": 10}
        }
        
        if data_type not in compliance_requirements:
            return True  # 要件が定義されていない場合は合格
        
        requirements = compliance_requirements[data_type]
        policy_years = policy.get("years", 0)
        
        return requirements["min_years"] <= policy_years <= requirements["max_years"]

class AutomatedLifecycleScheduler:
    """自動ライフサイクルスケジューラー（Job 型で厳格化）"""
    
    def __init__(self):
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
        self.scheduler_client: CloudSchedulerClient = CloudSchedulerClient()
        self.location = "asia-northeast1"
    
    async def setup_lifecycle_schedules(self) -> Dict[str, Any]:
        """ライフサイクルスケジュールを設定（Pylance 型エラー解消版）"""
        try:
            parent = f"projects/{self.project_id}/locations/{self.location}"
            
            schedules = [
                {
                    "name": "daily-lifecycle-cleanup",
                    "schedule": "0 2 * * *",  # 毎日午前2時
                    "description": "Daily data lifecycle cleanup",
                    "target_function": "lifecycle_cleanup_function"
                },
                {
                    "name": "weekly-retention-check", 
                    "schedule": "0 3 * * 1",  # 毎週月曜日午前3時
                    "description": "Weekly retention policy compliance check",
                    "target_function": "retention_check_function"
                },
                {
                    "name": "monthly-deep-cleanup",
                    "schedule": "0 4 1 * *",  # 毎月1日午前4時
                    "description": "Monthly deep cleanup and optimization",
                    "target_function": "deep_cleanup_function"
                }
            ]
            
            setup_results = []
            
            for schedule_config in schedules:
                try:
                    job_name = f"{parent}/jobs/{schedule_config['name']}"
                    
                    # Pub/Sub ターゲット（型オブジェクトで構築）
                    target_payload = json.dumps({
                        "function": schedule_config["target_function"],
                        "schedule": schedule_config["name"]
                    }).encode()
                    
                    pubsub_target = PubsubTarget(
                        topic_name=f"projects/{self.project_id}/topics/lifecycle-triggers",
                        data=target_payload
                    )
                    
                    # Job オブジェクトを正しく作成（dict ではなく types.Job）
                    job = Job(
                        name=job_name,
                        schedule=schedule_config["schedule"],
                        time_zone="Asia/Tokyo",
                        description=schedule_config["description"],
                        pubsub_target=pubsub_target,
                    )
                    
                    # 既存チェック
                    try:
                        existing = self.scheduler_client.get_job(name=job_name)
                        # 既存なら更新（更新マスクを明示）
                        update_mask = field_mask_pb2.FieldMask(
                            paths=["schedule", "time_zone", "description", "pubsub_target"]
                        )
                        update_req = UpdateJobRequest(job=job, update_mask=update_mask)
                        self.scheduler_client.update_job(request=update_req)
                        logger.info(f"📅 Updated schedule: {schedule_config['name']}")
                    except Exception:
                        # なければ作成
                        create_req = CreateJobRequest(parent=parent, job=job)
                        self.scheduler_client.create_job(request=create_req)
                        logger.info(f"🆕 Created schedule: {schedule_config['name']}")
                    
                    setup_results.append({
                        "schedule": schedule_config["name"],
                        "status": "success"
                    })
                    
                except Exception as e:
                    logger.error(f"❌ Failed to setup schedule {schedule_config['name']}: {e}")
                    setup_results.append({
                        "schedule": schedule_config["name"],
                        "status": "failed",
                        "error": str(e)
                    })
            
            return {
                "status": "completed",
                "schedules": setup_results,
                "success_count": len([r for r in setup_results if r["status"] == "success"])
            }
            
        except Exception as e:
            logger.error(f"❌ Lifecycle schedule setup failed: {e}")
            return {"status": "failed", "error": str(e)}

# Cloud Functions エントリーポイント
def lifecycle_cleanup_function(cloud_event, context):
    """スケジュールされたライフサイクル清掃"""
    
    async def run_cleanup():
        manager = DataLifecycleManager()
        results = await manager.run_lifecycle_cleanup()
        
        print(f"Lifecycle cleanup completed: {results['summary']}")
        return results
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(run_cleanup())
        return {"status": "success", "results": results}
    except Exception as e:
        print(f"Lifecycle cleanup failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        loop.close()

def retention_check_function(cloud_event, context):
    """保持期間コンプライアンスチェック"""
    
    async def run_check():
        manager = RetentionPolicyManager()
        results = await manager.validate_compliance()
        
        print(f"Retention compliance check: {results}")
        return results
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(run_check())
        return {"status": "success", "results": results}
    except Exception as e:
        print(f"Retention check failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        loop.close()

# テスト・管理用スクリプト
if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("🔧 Data Lifecycle Management System")
        print("=" * 50)
        
        # 1. ライフサイクル管理テスト
        manager = DataLifecycleManager()
        cleanup_results = await manager.run_lifecycle_cleanup()
        
        print("🧹 Cleanup Results:")
        print(f"  Total deleted: {cleanup_results['total_deleted']}")
        print(f"  Status: {cleanup_results['status']}")
        
        if cleanup_results.get('summary'):
            summary = cleanup_results['summary']
            print(f"  Success rate: {summary['success_rate']:.1f}%")
        
        # 2. 保持期間ポリシー検証
        policy_manager = RetentionPolicyManager()
        compliance_results = await policy_manager.validate_compliance()
        
        print("\n📋 Compliance Check:")
        print(f"  Compliant policies: {len(compliance_results.get('compliant_policies', []))}")
        print(f"  Non-compliant: {len(compliance_results.get('non_compliant_policies', []))}")
        
        # 3. スケジュール設定
        scheduler = AutomatedLifecycleScheduler()
        schedule_results = await scheduler.setup_lifecycle_schedules()
        
        print("\n📅 Schedule Setup:")
        print(f"  Status: {schedule_results['status']}")
        print(f"  Successful schedules: {schedule_results.get('success_count', 0)}")
    
    asyncio.run(main())
