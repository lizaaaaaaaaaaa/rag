# richmenu_repair.py - リッチメニュー修復スクリプト

import os
import requests
import json
import logging
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LineRichMenuManager:
    def __init__(self):
        # Secret Manager または環境変数からトークンを取得
        self.access_token = self._get_access_token()
        self.base_url = "https://api.line.me/v2/bot"
        
        if not self.access_token:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN not found")
        
        # ヘッダー設定
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def _get_access_token(self) -> str:
        """Access Tokenを取得"""
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        
        if not token:
            # Secret Managerから取得を試行
            try:
                from google.cloud import secretmanager
                client = secretmanager.SecretManagerServiceClient()
                project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
                
                secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                response = client.access_secret_version(request={"name": secret_name})
                token = response.payload.data.decode("UTF-8")
            except Exception as e:
                logger.error(f"Failed to get token from Secret Manager: {e}")
                return ""
        
        # トークンのクリーンアップ
        if token:
            token = token.strip()
            if token.startswith("Bearer "):
                token = token[7:].strip()
            if token.startswith("b'") and token.endswith("'"):
                token = token[2:-1]
            token = token.replace('"', '').replace("'", "")
        
        return token
    
    def test_api_connection(self) -> bool:
        """API接続テスト"""
        try:
            response = requests.get(f"{self.base_url}/info", headers=self.headers)
            
            if response.status_code == 200:
                bot_info = response.json()
                logger.info(f"✅ API接続成功: {bot_info.get('displayName', 'Unknown Bot')}")
                return True
            else:
                logger.error(f"❌ API接続失敗: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ API接続エラー: {e}")
            return False
    
    def get_current_richmenus(self) -> List[Dict]:
        """現在のリッチメニュー一覧を取得"""
        try:
            response = requests.get(f"{self.base_url}/richmenu/list", headers=self.headers)
            
            if response.status_code == 200:
                richmenus = response.json().get("richmenus", [])
                logger.info(f"📱 現在のリッチメニュー数: {len(richmenus)}")
                
                for menu in richmenus:
                    logger.info(f"  - ID: {menu.get('richMenuId')}")
                    logger.info(f"    名前: {menu.get('name')}")
                    logger.info(f"    選択状態: {menu.get('selected')}")
                
                return richmenus
            else:
                logger.error(f"❌ リッチメニュー取得失敗: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"❌ リッチメニュー取得エラー: {e}")
            return []
    
    def delete_all_richmenus(self) -> bool:
        """全てのリッチメニューを削除"""
        richmenus = self.get_current_richmenus()
        
        for menu in richmenus:
            menu_id = menu.get("richMenuId")
            if menu_id:
                try:
                    response = requests.delete(
                        f"{self.base_url}/richmenu/{menu_id}", 
                        headers=self.headers
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ リッチメニュー削除成功: {menu_id}")
                    else:
                        logger.error(f"❌ リッチメニュー削除失敗: {menu_id} - {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"❌ リッチメニュー削除エラー: {menu_id} - {e}")
        
        return True
    
    def create_richmenu(self) -> Optional[str]:
        """新しいリッチメニューを作成"""
        richmenu_data = {
            "size": {"width": 2500, "height": 1686},
            "selected": True,
            "name": "キノエデザイン住まいコンシェルジュリッチメニュー",
            "chatBarText": "メニュー",
            "areas": [
                {
                    "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "AI相談"}
                },
                {
                    "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "AI住まいサイト"}
                },
                {
                    "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "資料請求"}
                },
                {
                    "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "展示場来場予約"}
                },
                {
                    "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "資金計画"}
                },
                {
                    "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "チャット相談"}
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/richmenu",
                headers=self.headers,
                json=richmenu_data
            )
            
            if response.status_code == 200:
                richmenu_id = response.json().get("richMenuId")
                logger.info(f"✅ リッチメニュー作成成功: {richmenu_id}")
                return richmenu_id
            else:
                logger.error(f"❌ リッチメニュー作成失敗: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"❌ リッチメニュー作成エラー: {e}")
            return None
    
    def set_default_richmenu(self, richmenu_id: str) -> bool:
        """デフォルトリッチメニューに設定"""
        try:
            response = requests.post(
                f"{self.base_url}/user/all/richmenu/{richmenu_id}",
                headers=self.headers
            )
            
            if response.status_code == 200:
                logger.info(f"✅ デフォルトリッチメニュー設定成功: {richmenu_id}")
                return True
            else:
                logger.error(f"❌ デフォルトリッチメニュー設定失敗: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ デフォルトリッチメニュー設定エラー: {e}")
            return False
    
    def repair_richmenu(self) -> bool:
        """リッチメニューを修復"""
        logger.info("🔧 リッチメニュー修復開始...")
        
        # 1. API接続テスト
        if not self.test_api_connection():
            logger.error("❌ API接続に失敗しました。トークンを確認してください。")
            return False
        
        # 2. 既存のリッチメニューを削除
        logger.info("🗑️ 既存のリッチメニューを削除中...")
        self.delete_all_richmenus()
        
        # 3. 新しいリッチメニューを作成
        logger.info("🆕 新しいリッチメニューを作成中...")
        richmenu_id = self.create_richmenu()
        
        if not richmenu_id:
            logger.error("❌ リッチメニュー作成に失敗しました")
            return False
        
        # 4. デフォルトに設定
        logger.info("⚙️ デフォルトリッチメニューに設定中...")
        if self.set_default_richmenu(richmenu_id):
            logger.info("✅ リッチメニュー修復完了!")
            logger.info("📱 LINEアプリでリッチメニューを確認してください")
            return True
        else:
            logger.error("❌ デフォルト設定に失敗しました")
            return False
    
    def diagnose_webhook_settings(self):
        """Webhook設定の診断"""
        logger.info("🔍 Webhook設定の診断...")
        
        expected_webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
        
        print(f"""
📋 Webhook設定確認事項:

1. LINE Developers Console にログイン:
   https://developers.line.biz/console/

2. 該当のChannelを選択

3. Messaging API設定で以下を確認:
   - Webhook URL: {expected_webhook_url}
   - Use webhook: Enabled
   - Auto-reply messages: Disabled
   - Greeting messages: Disabled

4. Channel access token が正しく設定されていることを確認

5. Webhook URLが正しく応答することをテスト:
   curl -X POST {expected_webhook_url} -H "Content-Type: application/json" -d '{{"test": "ping"}}'
        """)

def main():
    """メイン実行関数"""
    try:
        manager = LineRichMenuManager()
        
        print("🤖 LINE リッチメニュー修復ツール")
        print("=" * 50)
        
        # 現在の状態確認
        print("📊 現在の状態確認...")
        manager.get_current_richmenus()
        
        # Webhook設定診断
        manager.diagnose_webhook_settings()
        
        # 修復実行確認
        response = input("\nリッチメニューを修復しますか？ (y/N): ")
        
        if response.lower() in ['y', 'yes']:
            success = manager.repair_richmenu()
            
            if success:
                print("\n🎉 リッチメニュー修復が完了しました!")
                print("📱 LINEアプリでメニューが表示されることを確認してください")
                print("⏱️ 反映には数分かかる場合があります")
            else:
                print("\n❌ リッチメニュー修復に失敗しました")
                print("🔧 手動での設定確認が必要です")
        else:
            print("キャンセルしました")
    
    except Exception as e:
        logger.error(f"❌ 実行エラー: {e}")
        print(f"\n💥 エラーが発生しました: {e}")
        print("🔧 LINE_CHANNEL_ACCESS_TOKEN の設定を確認してください")

if __name__ == "__main__":
    main()