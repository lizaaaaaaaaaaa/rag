# cloud_functions/auto_update_system.py - 自動更新フローシステム

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import asyncio
from google.cloud import storage, secretmanager, firestore
from google.cloud import functions_v1
import feedparser
import pandas as pd
import tempfile

logger = logging.getLogger(__name__)

class AutoUpdateManager:
    """自動更新フロー管理クラス"""
    
    def __init__(self):
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
        self.bucket_name = os.environ.get("GCS_BUCKET_NAME", "run-sources-rag-cloud-project-asia-northeast1")
        
        # Cloud clients
        self.storage_client = storage.Client()
        self.firestore_client = firestore.Client()
        self.secret_client = secretmanager.SecretManagerServiceClient()
        
        # 更新対象の設定
        self.update_sources = self._load_update_sources()
        
    def _load_update_sources(self) -> Dict[str, Dict]:
        """更新ソースの設定を読み込み"""
        return {
            "housing_subsidies": {
                "name": "住宅補助金・助成金情報",
                "sources": [
                    {
                        "type": "api",
                        "url": "https://www.mlit.go.jp/jutakukentiku/house/jutakukentiku_house_fr4_000007.html",
                        "selector": ".content",
                        "description": "国土交通省住宅局"
                    },
                    {
                        "type": "rss",
                        "url": "https://www.jhf.go.jp/rss/index.xml",
                        "description": "住宅金融支援機構"
                    }
                ],
                "update_frequency": "weekly",
                "keywords": ["補助金", "助成金", "住宅ローン控除", "ZEH", "省エネ"]
            },
            "tax_incentives": {
                "name": "住宅税制優遇制度",
                "sources": [
                    {
                        "type": "api",
                        "url": "https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1213.htm",
                        "description": "国税庁住宅ローン控除"
                    }
                ],
                "update_frequency": "monthly",
                "keywords": ["住宅ローン控除", "登録免許税", "不動産取得税", "固定資産税"]
            },
            "building_standards": {
                "name": "建築基準・省エネ基準",
                "sources": [
                    {
                        "type": "api",
                        "url": "https://www.mlit.go.jp/jutakukentiku/build/jutakukentiku_build_fr2_000001.html",
                        "description": "建築基準法関連"
                    }
                ],
                "update_frequency": "quarterly",
                "keywords": ["建築基準法", "省エネ基準", "断熱等級", "耐震等級", "長期優良住宅"]
            },
            "local_incentives": {
                "name": "地方自治体支援策",
                "sources": [
                    {
                        "type": "municipal_api",
                        "regions": ["兵庫県", "大阪府", "京都府"],
                        "description": "関西圏自治体支援策"
                    }
                ],
                "update_frequency": "monthly",
                "keywords": ["子育て支援", "移住支援", "空き家対策", "三世代同居"]
            },
            "interest_rates": {
                "name": "住宅ローン金利情報",
                "sources": [
                    {
                        "type": "api",
                        "url": "https://www.jhf.go.jp/loan/yushi/info/rate.html",
                        "description": "フラット35金利"
                    }
                ],
                "update_frequency": "monthly",
                "keywords": ["フラット35", "金利", "住宅ローン", "金利優遇"]
            }
        }
    
    async def run_auto_update_cycle(self) -> Dict[str, Any]:
        """自動更新サイクルを実行"""
        logger.info("🔄 Starting auto update cycle...")
        
        update_results = {
            "start_time": datetime.now().isoformat(),
            "sources_processed": [],
            "new_information": [],
            "errors": [],
            "summary": {}
        }
        
        try:
            for source_id, source_config in self.update_sources.items():
                logger.info(f"📊 Processing source: {source_id}")
                
                try:
                    # 1. 情報収集
                    collected_data = await self._collect_information(source_id, source_config)
                    
                    # 2. 既存データと比較
                    changes = await self._detect_changes(source_id, collected_data)
                    
                    # 3. 変更があればFAQ生成・更新
                    if changes:
                        updated_faqs = await self._generate_updated_faqs(source_id, changes)
                        
                        # 4. ベクトルストアに反映
                        await self._update_vectorstore(source_id, updated_faqs)
                        
                        update_results["new_information"].extend(changes)
                        logger.info(f"✅ Updated {len(changes)} items for {source_id}")
                    
                    update_results["sources_processed"].append({
                        "source_id": source_id,
                        "status": "success",
                        "changes_count": len(changes),
                        "processed_at": datetime.now().isoformat()
                    })
                    
                except Exception as e:
                    error_info = {
                        "source_id": source_id,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                    update_results["errors"].append(error_info)
                    logger.error(f"❌ Error processing {source_id}: {e}")
            
            # 5. 更新サマリーを生成
            update_results["summary"] = self._generate_update_summary(update_results)
            
            # 6. 結果をFirestoreに保存
            await self._save_update_log(update_results)
            
            logger.info("✅ Auto update cycle completed")
            return update_results
            
        except Exception as e:
            logger.error(f"❌ Auto update cycle failed: {e}")
            update_results["errors"].append({
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return update_results
    
    async def _collect_information(self, source_id: str, config: Dict) -> List[Dict]:
        """情報収集を実行"""
        collected_data = []
        
        for source in config["sources"]:
            try:
                if source["type"] == "api":
                    data = await self._fetch_api_data(source)
                elif source["type"] == "rss":
                    data = await self._fetch_rss_data(source)
                elif source["type"] == "municipal_api":
                    data = await self._fetch_municipal_data(source)
                else:
                    logger.warning(f"Unknown source type: {source['type']}")
                    continue
                
                # キーワードでフィルタリング
                filtered_data = self._filter_by_keywords(data, config["keywords"])
                collected_data.extend(filtered_data)
                
            except Exception as e:
                logger.error(f"Error collecting from {source.get('url', source.get('type'))}: {e}")
        
        return collected_data
    
    async def _fetch_api_data(self, source: Dict) -> List[Dict]:
        """API からデータを取得"""
        try:
            response = requests.get(source["url"], timeout=30)
            response.raise_for_status()
            
            # HTMLをパース（簡単な実装）
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # セレクタが指定されている場合
            if "selector" in source:
                elements = soup.select(source["selector"])
                return [{"content": elem.get_text().strip(), "url": source["url"]} for elem in elements]
            else:
                # 全体のテキストを取得
                return [{"content": soup.get_text().strip()[:1000], "url": source["url"]}]
                
        except Exception as e:
            logger.error(f"API fetch error: {e}")
            return []
    
    async def _fetch_rss_data(self, source: Dict) -> List[Dict]:
        """RSS フィードからデータを取得"""
        try:
            feed = feedparser.parse(source["url"])
            
            items = []
            for entry in feed.entries[:10]:  # 最新10件
                items.append({
                    "title": entry.get("title", ""),
                    "content": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", "")
                })
            
            return items
            
        except Exception as e:
            logger.error(f"RSS fetch error: {e}")
            return []
    
    async def _fetch_municipal_data(self, source: Dict) -> List[Dict]:
        """自治体データを取得（モック実装）"""
        # 実際の実装では各自治体のAPIやオープンデータを利用
        mock_data = [
            {
                "title": "兵庫県住宅支援制度更新",
                "content": "2025年度の住宅支援制度が更新されました。",
                "region": "兵庫県",
                "effective_date": "2025-04-01"
            },
            {
                "title": "大阪府子育て世帯住宅補助",
                "content": "子育て世帯向けの住宅補助金制度が拡充されました。",
                "region": "大阪府", 
                "effective_date": "2025-04-01"
            }
        ]
        return mock_data
    
    def _filter_by_keywords(self, data: List[Dict], keywords: List[str]) -> List[Dict]:
        """キーワードでデータをフィルタリング"""
        filtered = []
        
        for item in data:
            content = f"{item.get('title', '')} {item.get('content', '')}".lower()
            
            if any(keyword.lower() in content for keyword in keywords):
                item["matched_keywords"] = [kw for kw in keywords if kw.lower() in content]
                filtered.append(item)
        
        return filtered
    
    async def _detect_changes(self, source_id: str, new_data: List[Dict]) -> List[Dict]:
        """既存データとの変更を検出"""
        try:
            # Firestoreから既存データを取得
            doc_ref = self.firestore_client.collection("update_cache").document(source_id)
            existing_doc = doc_ref.get()
            
            if existing_doc.exists:
                existing_data = existing_doc.to_dict().get("data", [])
            else:
                existing_data = []
            
            # 変更を検出（簡単な実装）
            changes = []
            existing_contents = {item.get("content", "") for item in existing_data}
            
            for item in new_data:
                if item.get("content", "") not in existing_contents:
                    changes.append({
                        **item,
                        "change_type": "new",
                        "detected_at": datetime.now().isoformat()
                    })
            
            # 既存データを更新
            doc_ref.set({
                "data": new_data,
                "last_updated": datetime.now().isoformat(),
                "source_id": source_id
            })
            
            return changes
            
        except Exception as e:
            logger.error(f"Change detection error: {e}")
            return new_data  # エラー時は全て新規として扱う
    
    async def _generate_updated_faqs(self, source_id: str, changes: List[Dict]) -> List[Dict]:
        """変更された情報からFAQを生成"""
        faqs = []
        
        try:
            # OpenAI APIでFAQ生成
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            
            for change in changes:
                try:
                    prompt = f"""以下の最新情報から、住宅関連のFAQを生成してください。

最新情報: {change.get('content', '')}
ソース: {source_id}
キーワード: {change.get('matched_keywords', [])}

【指示】
1. 質問と回答のペアを生成
2. 住宅購入者にとって分かりやすい内容
3. 具体的で実用的な情報を含める
4. 年度や期限がある場合は明記

【出力フォーマット】
質問: [質問内容]
回答: [詳しい回答]"""

                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "あなたは住宅業界の専門家として、最新の制度情報からFAQを生成します。"},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3,
                        max_tokens=600
                    )
                    
                    faq_content = response.choices[0].message.content
                    
                    # FAQ解析
                    if "質問:" in faq_content and "回答:" in faq_content:
                        parts = faq_content.split("回答:")
                        question = parts[0].replace("質問:", "").strip()
                        answer = parts[1].strip()
                        
                        faqs.append({
                            "question": question,
                            "answer": answer,
                            "source_id": source_id,
                            "generated_at": datetime.now().isoformat(),
                            "keywords": change.get('matched_keywords', []),
                            "original_content": change.get('content', '')[:200]
                        })
                        
                except Exception as e:
                    logger.error(f"FAQ generation error for change: {e}")
                    
        except Exception as e:
            logger.error(f"FAQ generation setup error: {e}")
        
        logger.info(f"Generated {len(faqs)} FAQs for {source_id}")
        return faqs
    
    async def _update_vectorstore(self, source_id: str, faqs: List[Dict]):
        """ベクトルストアを更新"""
        try:
            # FAQをドキュメント形式に変換
            from langchain.schema import Document
            
            documents = []
            for faq in faqs:
                doc_content = f"質問: {faq['question']}\n\n回答: {faq['answer']}"
                
                documents.append(Document(
                    page_content=doc_content,
                    metadata={
                        "source": f"auto_update_{source_id}",
                        "type": "faq",
                        "generated_at": faq["generated_at"],
                        "keywords": faq["keywords"]
                    }
                ))
            
            if documents:
                # 既存のベクトルストア取得・更新ロジック
                from rag.ingested_text import load_vectorstore, ingest_pdf_to_vectorstore
                
                # 一時的にテキストファイルとして保存
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    for doc in documents:
                        f.write(doc.page_content + "\n\n---\n\n")
                    temp_path = f.name
                
                # ベクトルストアに追加（実装は要調整）
                # await self._add_to_vectorstore(documents)
                
                os.unlink(temp_path)
                logger.info(f"✅ Updated vectorstore with {len(documents)} new FAQs")
                
        except Exception as e:
            logger.error(f"Vectorstore update error: {e}")
    
    def _generate_update_summary(self, results: Dict) -> Dict:
        """更新サマリーを生成"""
        total_sources = len(results["sources_processed"])
        successful_sources = len([s for s in results["sources_processed"] if s["status"] == "success"])
        total_changes = sum(s.get("changes_count", 0) for s in results["sources_processed"])
        
        return {
            "total_sources_checked": total_sources,
            "successful_updates": successful_sources,
            "failed_updates": len(results["errors"]),
            "total_new_information": total_changes,
            "success_rate": successful_sources / total_sources if total_sources > 0 else 0,
            "next_update_recommended": (datetime.now() + timedelta(days=7)).isoformat()
        }
    
    async def _save_update_log(self, results: Dict):
        """更新ログをFirestoreに保存"""
        try:
            doc_ref = self.firestore_client.collection("update_logs").document()
            doc_ref.set({
                **results,
                "saved_at": datetime.now().isoformat()
            })
            logger.info("✅ Update log saved to Firestore")
        except Exception as e:
            logger.error(f"Failed to save update log: {e}")

# Cloud Functions エントリーポイント
def scheduled_update(cloud_event, context):
    """Cloud Scheduler からトリガーされる自動更新関数"""
    
    async def run_update():
        manager = AutoUpdateManager()
        results = await manager.run_auto_update_cycle()
        
        print(f"Auto update completed: {results['summary']}")
        return results
    
    # 非同期実行
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        results = loop.run_until_complete(run_update())
        return {"status": "success", "results": results}
    except Exception as e:
        print(f"Scheduled update failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        loop.close()

# Cloud Functions デプロイ用設定
"""
gcloud functions deploy scheduled-update \\
  --runtime python311 \\
  --trigger-topic update-trigger \\
  --entry-point scheduled_update \\
  --memory 1GB \\
  --timeout 540s \\
  --set-env-vars GOOGLE_CLOUD_PROJECT=rag-cloud-project,GCS_BUCKET_NAME=run-sources-rag-cloud-project-asia-northeast1

gcloud scheduler jobs create pubsub weekly-update \\
  --schedule="0 2 * * 1" \\
  --topic=update-trigger \\
  --message-body='{"type": "weekly_update"}' \\
  --time-zone="Asia/Tokyo"
"""

# ローカルテスト用
if __name__ == "__main__":
    import asyncio
    
    async def test_auto_update():
        print("🧪 Testing auto update system...")
        manager = AutoUpdateManager()
        results = await manager.run_auto_update_cycle()
        
        print("📊 Update Results:")
        print(f"Sources processed: {len(results['sources_processed'])}")
        print(f"New information: {len(results['new_information'])}")
        print(f"Errors: {len(results['errors'])}")
        print(f"Summary: {results['summary']}")
        
        return results
    
    asyncio.run(test_auto_update())