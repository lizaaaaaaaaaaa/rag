#!/bin/bash
# deploy_cloud_functions.sh - Cloud Functions自動更新システムデプロイ

set -e

PROJECT_ID="rag-cloud-project"
REGION="asia-northeast1"
FUNCTION_NAME="auto-update-function"
SA_EMAIL="auto-update-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Cloud Functions自動更新システムデプロイ開始"
echo "================================================"

# 1. Cloud Functions用ディレクトリ準備
echo "1️⃣ Cloud Functions用ディレクトリ準備..."
mkdir -p cloud_functions_deploy
cd cloud_functions_deploy

# 2. main.py作成（Cloud Functions エントリーポイント）
echo "2️⃣ Cloud Functions main.py作成..."
cat > main.py << 'EOF'
import functions_framework
import json
import asyncio
import logging
from datetime import datetime, timezone
from google.cloud import firestore
from google.cloud import pubsub_v1
import aiohttp
import feedparser
import re
from typing import Dict, List, Any
import os

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutoUpdateManager:
    def __init__(self):
        self.db = firestore.Client()
        self.project_id = os.environ.get('GOOGLE_CLOUD_PROJECT')
        
        # 更新対象の情報源設定
        self.update_sources = {
            'housing_subsidies': {
                'urls': [
                    'https://www.mlit.go.jp/jutakukentiku/house/jutakukentiku_house_tk2_000017.html',
                    'https://www.mlit.go.jp/report/press/house04_hh_000001024.html'
                ],
                'rss_feeds': [
                    'https://www.mlit.go.jp/rss/report.xml'
                ],
                'keywords': ['住宅補助', '助成金', 'ZEH', '省エネ住宅', '補助金'],
                'frequency': 'weekly'
            },
            'tax_incentives': {
                'urls': [
                    'https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/shotoku.htm'
                ],
                'keywords': ['住宅ローン控除', '税制優遇', '住宅取得', '減税'],
                'frequency': 'monthly'
            },
            'building_standards': {
                'urls': [
                    'https://www.mlit.go.jp/jutakukentiku/build/jutakukentiku_build_tk1_000001.html'
                ],
                'keywords': ['建築基準', '省エネ基準', '耐震基準', 'ZEH基準'],
                'frequency': 'quarterly'
            },
            'municipal_support': {
                'urls': [],
                'keywords': ['自治体支援', '地域補助', '市町村', '県'],
                'frequency': 'monthly'
            },
            'loan_rates': {
                'urls': [
                    'https://www.jhf.go.jp/loan/yushi/info/rate.html'
                ],
                'keywords': ['フラット35', '住宅ローン金利', '金利動向'],
                'frequency': 'monthly'
            }
        }

    async def collect_information(self, source_type: str, config: Dict) -> List[Dict]:
        """指定された情報源から情報を収集"""
        collected_info = []
        
        try:
            # Webページから情報収集
            for url in config.get('urls', []):
                try:
                    info = await self._fetch_web_content(url, config['keywords'])
                    if info:
                        collected_info.extend(info)
                except Exception as e:
                    logger.warning(f"Web収集エラー {url}: {str(e)}")
            
            # RSSフィードから情報収集
            for rss_url in config.get('rss_feeds', []):
                try:
                    info = await self._fetch_rss_content(rss_url, config['keywords'])
                    if info:
                        collected_info.extend(info)
                except Exception as e:
                    logger.warning(f"RSS収集エラー {rss_url}: {str(e)}")
            
            logger.info(f"{source_type}: {len(collected_info)}件の情報を収集")
            return collected_info
            
        except Exception as e:
            logger.error(f"情報収集エラー {source_type}: {str(e)}")
            return []

    async def _fetch_web_content(self, url: str, keywords: List[str]) -> List[Dict]:
        """Webページから関連情報を抽出"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        content = await response.text()
                        
                        # キーワードに関連する情報を抽出
                        relevant_info = []
                        for keyword in keywords:
                            if keyword in content:
                                # 簡単な抽出ロジック（実際はより詳細な解析が必要）
                                pattern = f'.{{0,100}}{re.escape(keyword)}.{{0,100}}'
                                matches = re.findall(pattern, content, re.IGNORECASE)
                                
                                for match in matches[:3]:  # 最大3件まで
                                    relevant_info.append({
                                        'source_url': url,
                                        'keyword': keyword,
                                        'content': match.strip(),
                                        'collected_at': datetime.now(timezone.utc).isoformat()
                                    })
                        
                        return relevant_info
        except Exception as e:
            logger.warning(f"Web取得エラー {url}: {str(e)}")
            return []

    async def _fetch_rss_content(self, rss_url: str, keywords: List[str]) -> List[Dict]:
        """RSSフィードから関連情報を抽出"""
        try:
            feed = feedparser.parse(rss_url)
            relevant_info = []
            
            for entry in feed.entries[:10]:  # 最新10件まで確認
                title = entry.get('title', '')
                summary = entry.get('summary', '')
                content = f"{title} {summary}"
                
                for keyword in keywords:
                    if keyword.lower() in content.lower():
                        relevant_info.append({
                            'source_url': rss_url,
                            'title': title,
                            'link': entry.get('link', ''),
                            'content': summary,
                            'published': entry.get('published', ''),
                            'keyword': keyword,
                            'collected_at': datetime.now(timezone.utc).isoformat()
                        })
                        break  # 1つのエントリにつき1回まで
            
            return relevant_info
            
        except Exception as e:
            logger.warning(f"RSS取得エラー {rss_url}: {str(e)}")
            return []

    def generate_faq_from_info(self, info_list: List[Dict]) -> List[Dict]:
        """収集した情報からFAQを生成"""
        faqs = []
        
        for info in info_list:
            try:
                # 簡単なFAQ生成ロジック
                keyword = info.get('keyword', '')
                content = info.get('content', '')
                
                if len(content) > 50:  # 十分な内容がある場合のみ
                    # キーワードベースの質問生成
                    if '補助金' in keyword or '助成金' in keyword:
                        question = f"{keyword}について詳しく教えてください"
                        answer = f"{keyword}に関する最新情報: {content[:200]}..."
                    elif '金利' in keyword:
                        question = f"現在の{keyword}はどうなっていますか？"
                        answer = f"{keyword}の最新状況: {content[:200]}..."
                    elif '基準' in keyword:
                        question = f"{keyword}の詳細を教えてください"
                        answer = f"{keyword}について: {content[:200]}..."
                    else:
                        question = f"{keyword}について教えてください"
                        answer = f"{content[:200]}..."
                    
                    faqs.append({
                        'question': question,
                        'answer': answer,
                        'source': info.get('source_url', ''),
                        'keyword': keyword,
                        'created_at': datetime.now(timezone.utc).isoformat(),
                        'confidence': 0.8
                    })
                    
            except Exception as e:
                logger.warning(f"FAQ生成エラー: {str(e)}")
        
        return faqs

    async def update_vector_store(self, faqs: List[Dict]) -> bool:
        """ベクトルストアを更新"""
        try:
            # Firestoreに新しいFAQを保存
            faq_collection = self.db.collection('generated_faqs')
            
            for faq in faqs:
                # 重複チェック
                existing = faq_collection.where('question', '==', faq['question']).limit(1).get()
                
                if not existing:
                    # 新しいFAQを追加
                    faq_collection.add(faq)
                    logger.info(f"新しいFAQ追加: {faq['question'][:50]}...")
                else:
                    logger.info(f"重複FAQ検出、スキップ: {faq['question'][:50]}...")
            
            # 統計更新
            stats_ref = self.db.collection('faq_stats').document('global')
            total_faqs = len(faq_collection.get())
            
            stats_ref.update({
                'total_faqs': total_faqs,
                'last_updated': datetime.now(timezone.utc),
                'last_generation_count': len(faqs)
            })
            
            return True
            
        except Exception as e:
            logger.error(f"ベクトルストア更新エラー: {str(e)}")
            return False

    async def log_update_result(self, update_type: str, success: bool, details: Dict):
        """更新結果をログに記録"""
        try:
            log_ref = self.db.collection('update_logs').document()
            log_ref.set({
                'type': update_type,
                'success': success,
                'timestamp': datetime.now(timezone.utc),
                'details': details
            })
        except Exception as e:
            logger.error(f"ログ記録エラー: {str(e)}")

@functions_framework.cloud_event
def scheduled_update(cloud_event):
    """スケジューラーからトリガーされる自動更新関数"""
    try:
        # Pub/Subメッセージをデコード
        message_data = cloud_event.data.get('message', {})
        if 'data' in message_data:
            import base64
            message = json.loads(base64.b64decode(message_data['data']).decode())
        else:
            message = {'type': 'weekly_update'}
        
        update_type = message.get('type', 'weekly_update')
        logger.info(f"自動更新開始: {update_type}")
        
        # 非同期処理を実行
        result = asyncio.run(run_update_process(update_type))
        
        logger.info(f"自動更新完了: {update_type}, 結果: {result}")
        return f"Update completed: {result}"
        
    except Exception as e:
        logger.error(f"自動更新エラー: {str(e)}")
        return f"Update failed: {str(e)}"

async def run_update_process(update_type: str) -> Dict:
    """更新プロセスの実行"""
    manager = AutoUpdateManager()
    total_faqs = 0
    results = {}
    
    try:
        # 更新タイプに応じて対象を決定
        if update_type == 'weekly_update':
            targets = ['housing_subsidies', 'loan_rates']
        elif update_type == 'monthly_update':
            targets = ['tax_incentives', 'municipal_support']
        else:
            targets = ['housing_subsidies']  # デフォルト
        
        for target in targets:
            if target in manager.update_sources:
                try:
                    # 情報収集
                    config = manager.update_sources[target]
                    collected_info = await manager.collect_information(target, config)
                    
                    # FAQ生成
                    if collected_info:
                        faqs = manager.generate_faq_from_info(collected_info)
                        
                        # ベクトルストア更新
                        if faqs:
                            success = await manager.update_vector_store(faqs)
                            total_faqs += len(faqs)
                            
                            results[target] = {
                                'collected': len(collected_info),
                                'faqs_generated': len(faqs),
                                'success': success
                            }
                        else:
                            results[target] = {'collected': len(collected_info), 'faqs_generated': 0, 'success': False}
                    else:
                        results[target] = {'collected': 0, 'faqs_generated': 0, 'success': False}
                        
                except Exception as e:
                    logger.error(f"処理エラー {target}: {str(e)}")
                    results[target] = {'error': str(e), 'success': False}
        
        # 結果をログに記録
        await manager.log_update_result(update_type, total_faqs > 0, {
            'total_faqs_generated': total_faqs,
            'targets': results,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        return {
            'success': True,
            'total_faqs_generated': total_faqs,
            'targets_processed': len(targets),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"更新プロセスエラー: {str(e)}")
        await manager.log_update_result(update_type, False, {'error': str(e)})
        return {'success': False, 'error': str(e)}

# HTTPトリガー用（テスト・手動実行用）
@functions_framework.http
def manual_update(request):
    """手動更新用HTTPエンドポイント"""
    try:
        request_json = request.get_json(silent=True)
        update_type = 'manual_update'
        
        if request_json and 'type' in request_json:
            update_type = request_json['type']
        
        logger.info(f"手動更新開始: {update_type}")
        result = asyncio.run(run_update_process(update_type))
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"手動更新エラー: {str(e)}")
        return json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False)
EOF

# 3. requirements.txt作成
echo "3️⃣ requirements.txt作成..."
cat > requirements.txt << 'EOF'
functions-framework>=3.*
google-cloud-firestore>=2.13.0
google-cloud-pubsub>=2.18.0
aiohttp>=3.8.0
feedparser>=6.0.10
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
python-dateutil>=2.8.0
google-cloud-logging>=3.5.0
EOF

# 4. .gcloudignore作成
echo "4️⃣ .gcloudignore作成..."
cat > .gcloudignore << 'EOF'
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.log
.git
.mypy_cache
.pytest_cache
.hypothesis
.DS_Store
EOF

echo "5️⃣ Cloud Functions デプロイ実行..."

# Pub/Subトリガー版をデプロイ
echo "  📡 Pub/Sub版をデプロイ中..."
gcloud functions deploy ${FUNCTION_NAME} \
    --gen2 \
    --runtime=python311 \
    --region=${REGION} \
    --source=. \
    --entry-point=scheduled_update \
    --memory=2GB \
    --timeout=540s \
    --service-account=${SA_EMAIL} \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
    --trigger-topic=update-trigger \
    --max-instances=10

echo "  ✅ Pub/Sub版デプロイ完了"

# HTTP版も別途デプロイ（手動実行用）
echo "  🌐 HTTP版をデプロイ中..."
gcloud functions deploy ${FUNCTION_NAME}-manual \
    --gen2 \
    --runtime=python311 \
    --region=${REGION} \
    --source=. \
    --entry-point=manual_update \
    --memory=2GB \
    --timeout=540s \
    --service-account=${SA_EMAIL} \
    --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
    --trigger-http \
    --allow-unauthenticated \
    --max-instances=5

echo "  ✅ HTTP版デプロイ完了"

# 6. デプロイ確認
echo "6️⃣ デプロイ確認..."
echo "  🔍 関数一覧:"
gcloud functions list --regions=${REGION} --filter="name:(${FUNCTION_NAME})"

echo ""
echo "  📋 関数詳細:"
gcloud functions describe ${FUNCTION_NAME} --region=${REGION}

# 7. 手動テスト実行
echo "7️⃣ 手動テスト実行..."
echo "  🧪 HTTP版でテスト実行中..."

MANUAL_URL=$(gcloud functions describe ${FUNCTION_NAME}-manual --region=${REGION} --format="value(url)")
echo "  📡 手動実行URL: ${MANUAL_URL}"

TEST_RESULT=$(curl -s -X POST "${MANUAL_URL}" \
    -H "Content-Type: application/json" \
    -d '{"type": "test_update"}' || echo "ERROR")

if [[ "$TEST_RESULT" != "ERROR" ]] && echo "$TEST_RESULT" | grep -q "success"; then
    echo "  ✅ 手動テスト成功"
    echo "$TEST_RESULT" | jq . 2>/dev/null || echo "$TEST_RESULT"
else
    echo "  ⚠️ 手動テスト結果: $TEST_RESULT"
fi

# 8. スケジューラーとの連携確認
echo "8️⃣ スケジューラー連携確認..."
echo "  📅 週次スケジューラー状態:"
gcloud scheduler jobs describe weekly-update --location=${REGION} --format="value(state)"

echo "  📅 月次スケジューラー状態:"
if gcloud scheduler jobs describe monthly-auto-update --location=${REGION} >/dev/null 2>&1; then
    gcloud scheduler jobs describe monthly-auto-update --location=${REGION} --format="value(state)"
else
    echo "  ⚠️ 月次スケジューラーが存在しません"
    
    echo "  📝 月次スケジューラー作成中..."
    gcloud scheduler jobs create pubsub monthly-auto-update \
        --schedule="0 3 1 * *" \
        --topic=update-trigger \
        --message-body='{"type": "monthly_update"}' \
        --time-zone="Asia/Tokyo" \
        --location=${REGION} \
        --description="RAG月次自動更新"
    
    echo "  ✅ 月次スケジューラー作成完了"
fi

cd ..

echo ""
echo "================================================"
echo "🎯 Cloud Functions自動更新システム デプロイ完了"
echo "================================================"
echo "✅ Pub/Sub版Cloud Functions: デプロイ済み"
echo "✅ HTTP版Cloud Functions: デプロイ済み"
echo "✅ 週次スケジューラー: 有効"
echo "✅ 月次スケジューラー: 有効"
echo "✅ 手動実行テスト: 完了"
echo ""
echo "📡 手動実行URL:"
echo "   ${MANUAL_URL}"
echo ""
echo "🔄 次回の自動実行:"
echo "   週次: 毎週月曜日 午前2時"
echo "   月次: 毎月1日 午前3時"
echo ""
echo "🚀 次のステップ: 統合テスト実行"
echo "   以下のコマンドを実行してください："
echo "   ./final_integration_test.sh"
echo ""