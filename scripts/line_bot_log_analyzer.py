#!/usr/bin/env python3
"""
LINE Bot 詳細ログ解析・OA Manager設定確認スクリプト
python line_bot_log_analyzer.py
"""

import os
import json
import subprocess
import requests
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any

class LINEBotLogAnalyzer:
    def __init__(self):
        self.project_id = "rag-cloud-project"
        self.region = "asia-northeast1"
        self.service_name = "rag-api"
        
        print("📊 LINE Bot ログ解析システム")
        print(f"📅 実行時刻: {datetime.now()}")
        print("=" * 60)

    def analyze_cloud_run_logs(self) -> List[Dict]:
        """Cloud Run ログを解析"""
        print("\n🔍 Cloud Run ログ解析中...")
        
        # 1) 最新の ERROR ログ
        print("1️⃣ 最新のERRORログ取得...")
        try:
            error_cmd = [
                'gcloud', 'logging', 'read',
                f'resource.type="cloud_run_revision" AND resource.labels.service_name="{self.service_name}" AND severity>=ERROR',
                '--limit', '10',
                '--format', 'json'
            ]
            
            result = subprocess.run(error_cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                error_logs = json.loads(result.stdout)
                print(f"   ✅ ERRORログ: {len(error_logs)}件")
                
                for log in error_logs[:3]:  # 最新3件を表示
                    timestamp = log.get('timestamp', 'Unknown')
                    message = log.get('textPayload', log.get('jsonPayload', {}).get('message', 'No message'))
                    print(f"   ⚠️ {timestamp}: {message[:100]}...")
            else:
                print("   ✅ ERRORログなし（正常）")
        except Exception as e:
            print(f"   ❌ ERRORログ取得エラー: {e}")

        # 2) LINE関連ログ
        print("\n2️⃣ LINE関連ログ取得...")
        try:
            line_cmd = [
                'gcloud', 'logging', 'read',
                f'resource.type="cloud_run_revision" AND resource.labels.service_name="{self.service_name}" AND textPayload:"LINE"',
                '--limit', '15',
                '--format', 'json'
            ]
            
            result = subprocess.run(line_cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                line_logs = json.loads(result.stdout)
                print(f"   ✅ LINEログ: {len(line_logs)}件")
                
                # 関連ログをカテゴライズ
                webhook_logs = []
                signature_logs = []
                richmenu_logs = []
                
                for log in line_logs:
                    message = log.get('textPayload', '')
                    if 'webhook' in message.lower():
                        webhook_logs.append(log)
                    elif 'signature' in message.lower():
                        signature_logs.append(log)
                    elif 'richmenu' in message.lower() or 'rich menu' in message.lower():
                        richmenu_logs.append(log)
                
                print(f"     📨 Webhookログ: {len(webhook_logs)}件")
                print(f"     🔐 署名ログ: {len(signature_logs)}件")
                print(f"     📱 リッチメニューログ: {len(richmenu_logs)}件")
                
                # 重要なログを表示
                for log in (webhook_logs + signature_logs + richmenu_logs)[:5]:
                    timestamp = log.get('timestamp', 'Unknown')
                    message = log.get('textPayload', '')[:80]
                    print(f"     📄 {timestamp}: {message}...")
                    
            else:
                print("   ⚠️ LINEログなし")
        except Exception as e:
            print(f"   ❌ LINEログ取得エラー: {e}")

        # 3) Webhook関連ログ
        print("\n3️⃣ Webhook関連ログ取得...")
        try:
            webhook_cmd = [
                'gcloud', 'logging', 'read',
                f'resource.type="cloud_run_revision" AND resource.labels.service_name="{self.service_name}" AND (textPayload:"webhook" OR textPayload:"Webhook")',
                '--limit', '10',
                '--format', 'json'
            ]
            
            result = subprocess.run(webhook_cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                webhook_logs = json.loads(result.stdout)
                print(f"   ✅ Webhookログ: {len(webhook_logs)}件")
                
                # ステータスコード別に分析
                success_count = 0
                error_count = 0
                signature_error_count = 0
                
                for log in webhook_logs:
                    message = log.get('textPayload', '')
                    if '200' in message or 'success' in message.lower():
                        success_count += 1
                    elif '403' in message or '401' in message or 'signature' in message.lower():
                        signature_error_count += 1
                    elif any(code in message for code in ['400', '500', 'error']):
                        error_count += 1
                
                print(f"     ✅ 成功: {success_count}件")
                print(f"     🔐 署名エラー: {signature_error_count}件")
                print(f"     ❌ その他エラー: {error_count}件")
                
            else:
                print("   ⚠️ Webhookログなし")
        except Exception as e:
            print(f"   ❌ Webhookログ取得エラー: {e}")

        return []

    def check_oa_manager_settings(self) -> Dict:
        """OA Manager設定確認ガイドを表示"""
        print("\n🏢 LINE Official Account Manager 設定確認ガイド")
        print("=" * 60)
        
        settings_checklist = {
            "webhook_settings": {
                "title": "Webhook設定",
                "url": "https://manager.line.biz/",
                "steps": [
                    "1. LINE Official Account Manager にログイン",
                    "2. 該当のアカウントを選択",
                    "3. 左メニュー「設定」→「応答設定」",
                    "4. 確認項目:",
                    "   ✅ 応答メッセージ: オフ（重要！）",
                    "   ✅ あいさつメッセージ: オフ",
                    "   ✅ Webhook: オン",
                    "   ✅ リッチメニュー: オン"
                ]
            },
            "developers_console": {
                "title": "LINE Developers Console設定",
                "url": "https://developers.line.biz/console/",
                "steps": [
                    "1. LINE Developers Console にログイン",
                    "2. Messaging APIチャネルを選択",
                    "3. 「Messaging API」タブで確認:",
                    "   ✅ Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
                    "   ✅ Webhookの利用: オン",
                    "   ✅ チャネルアクセストークン（長期）: 有効期限内",
                    "4. 接続テストを実行 → 200 OK が返ること"
                ]
            }
        }
        
        for key, setting in settings_checklist.items():
            print(f"\n📋 {setting['title']}")
            print(f"🌐 URL: {setting['url']}")
            for step in setting['steps']:
                print(f"   {step}")
        
        print(f"\n⚠️ 最も重要な設定:")
        print(f"   LINE Official Account Manager で「応答メッセージ: オフ」にする")
        print(f"   これがオンだと、Webhookが動作してもLINE公式の自動応答が優先されます")
        
        return settings_checklist

    def test_webhook_connectivity(self) -> Dict:
        """Webhook接続性テスト"""
        print("\n🔗 Webhook接続性テスト")
        print("=" * 40)
        
        webhook_url = f"https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
        results = {}
        
        # 1) 基本的なHTTP接続テスト
        print("1️⃣ 基本HTTP接続テスト...")
        try:
            # HEADリクエストでエンドポイントの存在確認
            response = requests.head(webhook_url, timeout=10)
            print(f"   ステータス: {response.status_code}")
            
            if response.status_code in [200, 404, 405]:  # エンドポイントは存在
                print("   ✅ エンドポイントに到達可能")
                results["endpoint_reachable"] = True
            else:
                print(f"   ❌ エンドポイント到達不可: {response.status_code}")
                results["endpoint_reachable"] = False
                
        except Exception as e:
            print(f"   ❌ 接続エラー: {e}")
            results["endpoint_reachable"] = False

        # 2) Cloud Run サービス状態確認
        print("\n2️⃣ Cloud Run サービス状態確認...")
        try:
            status_url = f"https://rag-api-190389115361.asia-northeast1.run.app/line/status"
            response = requests.get(status_url, timeout=10)
            
            if response.status_code == 200:
                status_data = response.json()
                print("   ✅ サービス応答中")
                print(f"     LINE Bot設定: {status_data.get('line_bot_configured')}")
                print(f"     SDK利用可能: {status_data.get('line_sdk_available')}")
                results["service_responsive"] = True
                results["line_config"] = status_data
            else:
                print(f"   ❌ サービス異常: {response.status_code}")
                results["service_responsive"] = False
                
        except Exception as e:
            print(f"   ❌ サービス確認エラー: {e}")
            results["service_responsive"] = False

        # 3) DNS解決確認
        print("\n3️⃣ DNS解決確認...")
        try:
            import socket
            domain = "rag-api-190389115361.asia-northeast1.run.app"
            ip = socket.gethostbyname(domain)
            print(f"   ✅ DNS解決成功: {domain} → {ip}")
            results["dns_resolved"] = True
        except Exception as e:
            print(f"   ❌ DNS解決失敗: {e}")
            results["dns_resolved"] = False

        return results

    def generate_configuration_script(self):
        """設定修正スクリプトを生成"""
        print("\n🛠️ 緊急修正スクリプト生成")
        print("=" * 40)
        
        script_content = '''#!/bin/bash
# LINE Bot 緊急修正スクリプト

echo "🚨 LINE Bot 緊急修正開始..."

# 1. Secret Manager 最新バージョン確認
echo "1️⃣ Secret Manager 確認..."
gcloud secrets versions list LINE_CHANNEL_ACCESS_TOKEN --limit=3
gcloud secrets versions list LINE_CHANNEL_SECRET --limit=3

# 2. Cloud Run を最新Secret で強制更新
echo "2️⃣ Cloud Run 強制更新..."
gcloud run services update rag-api \\
    --region=asia-northeast1 \\
    --update-secrets=LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest \\
    --no-cpu-throttling \\
    --memory=16Gi \\
    --timeout=600s

# 3. デプロイ完了待ち
echo "3️⃣ デプロイ完了待ち..."
sleep 15

# 4. サービス状態確認
echo "4️⃣ サービス確認..."
curl -s https://rag-api-190389115361.asia-northeast1.run.app/healthz | jq

# 5. LINE Bot 状態確認
echo "5️⃣ LINE Bot 状態確認..."
curl -s https://rag-api-190389115361.asia-northeast1.run.app/line/status | jq

echo "✅ 緊急修正完了"
echo "次に LINE アプリでリッチメニューをテストしてください"
'''
        
        with open("emergency_fix.sh", "w") as f:
            f.write(script_content)
        
        print("📄 emergency_fix.sh を生成しました")
        print("実行方法: chmod +x emergency_fix.sh && ./emergency_fix.sh")

    def run_comprehensive_analysis(self):
        """包括的分析を実行"""
        print("🚀 LINE Bot 包括的ログ解析開始")
        
        # 1. Cloud Run ログ解析
        self.analyze_cloud_run_logs()
        
        # 2. OA Manager 設定確認ガイド
        self.check_oa_manager_settings()
        
        # 3. Webhook 接続テスト
        connectivity_results = self.test_webhook_connectivity()
        
        # 4. 緊急修正スクリプト生成
        self.generate_configuration_script()
        
        # 5. 総合判定
        print("\n📊 総合分析結果")
        print("=" * 50)
        
        if connectivity_results.get("endpoint_reachable") and connectivity_results.get("service_responsive"):
            print("✅ 技術的問題: なし")
            print("💡 可能性の高い原因:")
            print("   1. LINE Official Account Manager の「応答メッセージ」がオンになっている")
            print("   2. リッチメニューが正しく設定されていない")
            print("   3. チャネルアクセストークンの期限切れ")
        else:
            print("❌ 技術的問題: あり")
            print("💡 緊急対応:")
            print("   1. ./emergency_fix.sh を実行")
            print("   2. Cloud Run ログを確認")
            print("   3. Secret Manager の値を確認")
        
        print(f"\n📅 分析完了時刻: {datetime.now()}")

def main():
    analyzer = LINEBotLogAnalyzer()
    analyzer.run_comprehensive_analysis()

if __name__ == "__main__":
    main()