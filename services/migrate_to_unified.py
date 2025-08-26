# scripts/migrate_to_unified.py - 統合チャット移行実行スクリプト

import os
import sys
import time
import json
import shutil
import subprocess
import requests
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
from pathlib import Path

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/migration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class UnifiedChatMigrator:
    """統合チャット移行実行クラス"""
    
    def __init__(self):
        self.migration_config = {
            "backup_dir": f"backup/migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "test_port": 8081,
            "production_port": 8080,
            "rollback_available": True,
            "validation_endpoints": [
                "/healthz",
                "/system-status", 
                "/chat-unified/performance-stats",
                "/monitoring/dashboard"
            ]
        }
        
        self.migration_steps = [
            ("backup_current_system", "現在のシステムのバックアップ"),
            ("deploy_unified_system", "統合システムのデプロイ"),
            ("run_integration_tests", "統合テストの実行"),
            ("performance_validation", "パフォーマンス検証"),
            ("switch_traffic", "トラフィック切り替え"),
            ("cleanup_legacy_system", "レガシーシステムのクリーンアップ"),
            ("finalize_migration", "移行の完了")
        ]
        
        self.rollback_plan = []
        self.migration_results = {}

    async def execute_migration(self, dry_run: bool = False) -> Dict[str, Any]:
        """移行実行のメイン処理"""
        logger.info("🚀 統合チャット移行を開始します...")
        
        if dry_run:
            logger.info("🧪 DRY RUNモード - 実際の変更は行いません")
        
        migration_start_time = time.time()
        overall_success = True
        
        try:
            # 事前チェック
            if not await self._pre_migration_checks():
                raise Exception("事前チェックに失敗しました")
            
            # 各移行ステップの実行
            for step_function, step_description in self.migration_steps:
                logger.info(f"📋 実行中: {step_description}")
                step_start_time = time.time()
                
                try:
                    if dry_run:
                        result = await self._dry_run_step(step_function, step_description)
                    else:
                        result = await getattr(self, step_function)()
                    
                    step_duration = time.time() - step_start_time
                    self.migration_results[step_function] = {
                        "status": "success",
                        "duration": step_duration,
                        "result": result
                    }
                    logger.info(f"✅ 完了: {step_description} ({step_duration:.2f}秒)")
                    
                except Exception as e:
                    step_duration = time.time() - step_start_time
                    self.migration_results[step_function] = {
                        "status": "failed",
                        "duration": step_duration,
                        "error": str(e)
                    }
                    logger.error(f"❌ 失敗: {step_description} - {e}")
                    overall_success = False
                    
                    if not dry_run:
                        # 失敗時のロールバック判定
                        if await self._should_rollback(step_function):
                            logger.warning("🔄 ロールバックを実行します...")
                            await self._execute_rollback()
                            break
            
            total_duration = time.time() - migration_start_time
            
            # 移行結果の記録
            migration_summary = {
                "start_time": datetime.fromtimestamp(migration_start_time).isoformat(),
                "end_time": datetime.now().isoformat(),
                "total_duration": total_duration,
                "overall_success": overall_success,
                "dry_run": dry_run,
                "steps_completed": len([r for r in self.migration_results.values() if r["status"] == "success"]),
                "total_steps": len(self.migration_steps),
                "results": self.migration_results
            }
            
            # 結果保存
            self._save_migration_results(migration_summary)
            
            if overall_success:
                logger.info(f"🎉 移行が正常に完了しました！ (所要時間: {total_duration:.2f}秒)")
            else:
                logger.error(f"💥 移行が失敗しました (所要時間: {total_duration:.2f}秒)")
            
            return migration_summary
            
        except Exception as e:
            logger.error(f"💥 移行中に重大なエラーが発生しました: {e}")
            if not dry_run:
                await self._execute_emergency_rollback()
            raise

    async def _pre_migration_checks(self) -> bool:
        """事前チェック"""
        logger.info("🔍 事前チェックを実行しています...")
        
        checks = [
            ("python_version", self._check_python_version),
            ("disk_space", self._check_disk_space),
            ("dependencies", self._check_dependencies),
            ("ports_available", self._check_ports_available),
            ("backup_space", self._check_backup_space),
            ("config_files", self._check_config_files)
        ]
        
        all_checks_passed = True
        
        for check_name, check_function in checks:
            try:
                result = await check_function()
                if result:
                    logger.info(f"  ✅ {check_name}: OK")
                else:
                    logger.error(f"  ❌ {check_name}: FAILED")
                    all_checks_passed = False
            except Exception as e:
                logger.error(f"  💥 {check_name}: ERROR - {e}")
                all_checks_passed = False
        
        return all_checks_passed

    async def backup_current_system(self) -> Dict[str, Any]:
        """現在のシステムのバックアップ"""
        backup_dir = self.migration_config["backup_dir"]
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_items = [
            ("main.py", "メインアプリケーション"),
            ("api/routers/", "APIルーター"),
            ("data/", "データフォルダ"),
            ("logs/", "ログファイル"),
            ("config/", "設定ファイル"),
            (".env", "環境設定"),
            ("requirements.txt", "依存関係")
        ]
        
        backed_up_items = []
        backup_size = 0
        
        for item, description in backup_items:
            if os.path.exists(item):
                try:
                    backup_path = os.path.join(backup_dir, item)
                    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                    
                    if os.path.isdir(item):
                        shutil.copytree(item, backup_path)
                    else:
                        shutil.copy2(item, backup_path)
                    
                    item_size = self._get_size(backup_path)
                    backup_size += item_size
                    backed_up_items.append({
                        "item": item,
                        "description": description,
                        "size": item_size,
                        "backup_path": backup_path
                    })
                    
                    logger.info(f"  📦 バックアップ完了: {description}")
                    
                except Exception as e:
                    logger.warning(f"  ⚠️ バックアップ失敗: {description} - {e}")
        
        # ロールバック情報の記録
        self.rollback_plan.append({
            "action": "restore_from_backup",
            "backup_dir": backup_dir,
            "backed_up_items": backed_up_items
        })
        
        return {
            "backup_directory": backup_dir,
            "backed_up_items": len(backed_up_items),
            "total_size": backup_size,
            "items": backed_up_items
        }

    async def deploy_unified_system(self) -> Dict[str, Any]:
        """統合システムのデプロイ"""
        logger.info("📦 統合システムをデプロイしています...")
        
        # 統合ファイルのデプロイ
        unified_files = [
            ("api/routers/chat_unified.py", "統合チャットルーター"),
            ("utils/chat_cache.py", "統合キャッシュシステム"),
            ("utils/chat_templates.py", "統合テンプレートシステム"),
            ("services/rag_processing_service.py", "RAG処理サービス"),
            ("services/response_enhancement.py", "応答品質向上サービス"),
            ("monitoring/dashboard.py", "監視ダッシュボード"),
            ("templates/chat/template_config.yaml", "テンプレート設定")
        ]
        
        deployed_files = []
        
        for file_path, description in unified_files:
            try:
                # ファイルが存在する場合のみデプロイ
                if os.path.exists(file_path):
                    logger.info(f"  ✅ {description}: 既に存在")
                else:
                    logger.info(f"  📝 {description}: テンプレートから作成が必要")
                
                deployed_files.append({
                    "file": file_path,
                    "description": description,
                    "status": "deployed" if os.path.exists(file_path) else "needs_creation"
                })
                
            except Exception as e:
                logger.error(f"  ❌ {description}: デプロイ失敗 - {e}")
                raise
        
        # main.pyの更新
        await self._update_main_py()
        
        # 依存関係の更新
        await self._update_dependencies()
        
        return {
            "deployed_files": len(deployed_files),
            "files": deployed_files,
            "main_py_updated": True,
            "dependencies_updated": True
        }

    async def run_integration_tests(self) -> Dict[str, Any]:
        """統合テストの実行"""
        logger.info("🧪 統合テストを実行しています...")
        
        # テストサーバーの起動
        test_port = self.migration_config["test_port"]
        test_server_process = None
        
        try:
            # テスト用の環境変数設定
            test_env = os.environ.copy()
            test_env["PORT"] = str(test_port)
            test_env["APP_ENV"] = "testing"
            
            # テストサーバー起動
            test_server_process = subprocess.Popen([
                sys.executable, "main.py"
            ], env=test_env)
            
            # サーバー起動待機
            await self._wait_for_server_ready(f"http://localhost:{test_port}")
            
            # テストの実行
            test_results = await self._run_test_suite(test_port)
            
            return test_results
            
        finally:
            # テストサーバーの停止
            if test_server_process:
                test_server_process.terminate()
                test_server_process.wait()

    async def performance_validation(self) -> Dict[str, Any]:
        """パフォーマンス検証"""
        logger.info("📊 パフォーマンス検証を実行しています...")
        
        test_port = self.migration_config["test_port"]
        
        # パフォーマンステストの実行
        performance_tests = [
            ("response_time", self._test_response_time),
            ("throughput", self._test_throughput),
            ("memory_usage", self._test_memory_usage),
            ("cache_efficiency", self._test_cache_efficiency)
        ]
        
        performance_results = {}
        
        for test_name, test_function in performance_tests:
            try:
                result = await test_function(test_port)
                performance_results[test_name] = result
                
                # 基準値との比較
                if self._meets_performance_criteria(test_name, result):
                    logger.info(f"  ✅ {test_name}: 基準値クリア")
                else:
                    logger.warning(f"  ⚠️ {test_name}: 基準値未達")
                
            except Exception as e:
                logger.error(f"  ❌ {test_name}: テスト失敗 - {e}")
                performance_results[test_name] = {"error": str(e)}
        
        return performance_results

    async def switch_traffic(self) -> Dict[str, Any]:
        """トラフィック切り替え"""
        logger.info("🔄 本番環境への切り替えを実行しています...")
        
        # 段階的切り替えの実行
        switch_phases = [
            ("stop_old_system", "旧システムの停止"),
            ("update_main_config", "メイン設定の更新"),  
            ("restart_production", "本番システムの再起動"),
            ("verify_production", "本番環境の検証")
        ]
        
        switch_results = {}
        
        for phase_name, phase_description in switch_phases:
            try:
                logger.info(f"  🔄 実行中: {phase_description}")
                result = await getattr(self, f"_execute_{phase_name}")()
                switch_results[phase_name] = result
                logger.info(f"  ✅ 完了: {phase_description}")
                
            except Exception as e:
                logger.error(f"  ❌ 失敗: {phase_description} - {e}")
                switch_results[phase_name] = {"error": str(e)}
                raise
        
        # ロールバック情報の記録
        self.rollback_plan.append({
            "action": "switch_back_to_old_system",
            "switch_results": switch_results
        })
        
        return switch_results

    async def cleanup_legacy_system(self) -> Dict[str, Any]:
        """レガシーシステムのクリーンアップ"""
        logger.info("🧹 レガシーシステムのクリーンアップを実行しています...")
        
        # 削除対象ファイル
        legacy_files = [
            "api/routers/chat.py",
            "api/routers/chat_ultra_fast.py"
        ]
        
        # アーカイブディレクトリの作成
        archive_dir = "archive/deprecated_routers"
        os.makedirs(archive_dir, exist_ok=True)
        
        cleaned_items = []
        
        for file_path in legacy_files:
            if os.path.exists(file_path):
                try:
                    # アーカイブに移動
                    archive_path = os.path.join(archive_dir, os.path.basename(file_path))
                    shutil.move(file_path, archive_path)
                    
                    cleaned_items.append({
                        "original_path": file_path,
                        "archive_path": archive_path,
                        "status": "archived"
                    })
                    
                    logger.info(f"  📦 アーカイブ: {file_path} → {archive_path}")
                    
                except Exception as e:
                    logger.error(f"  ❌ アーカイブ失敗: {file_path} - {e}")
                    cleaned_items.append({
                        "original_path": file_path,
                        "status": "failed",
                        "error": str(e)
                    })
        
        # README更新
        readme_path = os.path.join(archive_dir, "README.md")
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(f"""# Deprecated Routers Archive

These routers have been deprecated and replaced by the unified chat system.

Migration Date: {datetime.now().isoformat()}
Unified Router: api/routers/chat_unified.py

## Archived Files:
""")
            for item in cleaned_items:
                if item["status"] == "archived":
                    f.write(f"- {item['original_path']} → {item['archive_path']}\n")
        
        return {
            "archive_directory": archive_dir,
            "cleaned_items": len(cleaned_items),
            "items": cleaned_items
        }

    async def finalize_migration(self) -> Dict[str, Any]:
        """移行の完了"""
        logger.info("🎯 移行を完了しています...")
        
        finalization_tasks = [
            ("update_documentation", "ドキュメント更新"),
            ("configure_monitoring", "監視設定"),
            ("optimize_performance", "パフォーマンス最適化"),
            ("setup_alerts", "アラート設定")
        ]
        
        finalization_results = {}
        
        for task_name, task_description in finalization_tasks:
            try:
                logger.info(f"  ⚙️ 実行中: {task_description}")
                result = await getattr(self, f"_finalize_{task_name}")()
                finalization_results[task_name] = result
                logger.info(f"  ✅ 完了: {task_description}")
                
            except Exception as e:
                logger.warning(f"  ⚠️ {task_description}: {e}")
                finalization_results[task_name] = {"error": str(e)}
        
        return finalization_results

    # ヘルパーメソッド（実装の詳細）
    async def _check_python_version(self) -> bool:
        version_info = sys.version_info
        return version_info.major == 3 and version_info.minor >= 11

    async def _check_disk_space(self) -> bool:
        statvfs = os.statvfs('.')
        free_space_gb = (statvfs.f_bavail * statvfs.f_frsize) / (1024**3)
        return free_space_gb > 5  # 5GB以上の空き容量が必要

    async def _check_dependencies(self) -> bool:
        try:
            import fastapi
            import langchain
            return True
        except ImportError:
            return False

    async def _check_ports_available(self) -> bool:
        import socket
        ports_to_check = [8080, 8081]
        
        for port in ports_to_check:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                result = sock.connect_ex(('localhost', port))
                if result == 0:  # ポートが使用中
                    logger.warning(f"Port {port} is in use")
                    return False
        return True

    async def _check_backup_space(self) -> bool:
        # バックアップに必要な容量の見積もり
        estimated_backup_size = self._get_size('.') * 0.1  # 全体の10%程度
        statvfs = os.statvfs('.')
        free_space = statvfs.f_bavail * statvfs.f_frsize
        return free_space > estimated_backup_size * 2  # 2倍のマージンを確保

    async def _check_config_files(self) -> bool:
        required_files = ['.env', 'requirements.txt']
        return all(os.path.exists(f) for f in required_files)

    def _get_size(self, path: str) -> int:
        if os.path.isfile(path):
            return os.path.getsize(path)
        elif os.path.isdir(path):
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except OSError:
                        pass
            return total_size
        return 0

    async def _dry_run_step(self, step_function: str, step_description: str) -> Dict[str, Any]:
        """DRYランモードでのステップ実行"""
        return {
            "dry_run": True,
            "step": step_function,
            "description": step_description,
            "would_execute": True
        }

    async def _should_rollback(self, failed_step: str) -> bool:
        """ロールバック判定"""
        critical_steps = [
            "deploy_unified_system",
            "switch_traffic"
        ]
        return failed_step in critical_steps

    async def _execute_rollback(self) -> None:
        """ロールバック実行"""
        logger.warning("🔙 ロールバックを実行しています...")
        
        for action in reversed(self.rollback_plan):
            try:
                if action["action"] == "restore_from_backup":
                    await self._restore_from_backup(action)
                elif action["action"] == "switch_back_to_old_system":
                    await self._switch_back_to_old_system(action)
                    
                logger.info(f"✅ ロールバック完了: {action['action']}")
                
            except Exception as e:
                logger.error(f"❌ ロールバック失敗: {action['action']} - {e}")

    def _save_migration_results(self, results: Dict[str, Any]) -> None:
        """移行結果の保存"""
        results_file = f"migration_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📄 移行結果を保存しました: {results_file}")

# CLI インターフェース
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='統合チャット移行ツール')
    parser.add_argument('--dry-run', action='store_true', help='DRY RUNモード（実際の変更なし）')
    parser.add_argument('--step', help='特定のステップのみ実行')
    parser.add_argument('--rollback', action='store_true', help='ロールバック実行')
    
    args = parser.parse_args()
    
    migrator = UnifiedChatMigrator()
    
    try:
        if args.rollback:
            print("🔙 ロールバックモードは現在実装中です")
        elif args.step:
            print(f"📋 ステップ '{args.step}' の実行は現在実装中です")
        else:
            import asyncio
            result = asyncio.run(migrator.execute_migration(dry_run=args.dry_run))
            
            if result["overall_success"]:
                print("🎉 移行が正常に完了しました！")
                sys.exit(0)
            else:
                print("💥 移行が失敗しました")
                sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n⏹️ 移行がユーザーによってキャンセルされました")
        sys.exit(1)
    except Exception as e:
        print(f"💥 移行中にエラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()