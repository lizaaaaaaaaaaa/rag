# utils/web_search.py - Google Custom Search API版

import os
import logging
import requests
from typing import Dict, List, Optional
import openai
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

class GoogleSearcher:
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        
        # Google Custom Search APIの設定
        self.google_api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        self.google_cx = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
        self.search_endpoint = "https://www.googleapis.com/customsearch/v1"
        
        # Secret Managerから取得する場合
        if not self.google_api_key and os.environ.get("ENV") == "production":
            self._load_from_secret_manager()
    
    def _load_from_secret_manager(self):
        """Google Secret Managerから認証情報を取得"""
        try:
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            # API Keyを取得
            api_key_name = f"projects/{project_id}/secrets/GOOGLE_SEARCH_API_KEY/versions/latest"
            api_key_response = client.access_secret_version(request={"name": api_key_name})
            self.google_api_key = api_key_response.payload.data.decode("UTF-8")
            
            # Search Engine IDを取得
            cx_name = f"projects/{project_id}/secrets/GOOGLE_SEARCH_ENGINE_ID/versions/latest"
            cx_response = client.access_secret_version(request={"name": cx_name})
            self.google_cx = cx_response.payload.data.decode("UTF-8")
            
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
    
    def search_web(self, query: str, num_results: int = 5) -> List[Dict]:
        """Google Custom Search APIを使用してWeb検索"""
        if not self.google_api_key or not self.google_cx:
            logger.warning("Google Search API credentials not found")
            return []
        
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cx,
                "q": query,
                "num": num_results,
                "hl": "ja",  # 日本語優先
                "gl": "jp",  # 日本の検索結果優先
            }
            
            response = requests.get(self.search_endpoint, params=params)
            response.raise_for_status()
            
            search_results = []
            data = response.json()
            
            if "items" in data:
                for item in data["items"][:num_results]:
                    search_results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                        "domain": item.get("displayLink", "")
                    })
            
            logger.info(f"Found {len(search_results)} search results for query: {query}")
            return search_results
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("Google Search API quota exceeded")
            else:
                logger.error(f"Google Search API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []
    
    def get_enhanced_answer(self, query: str, context: str = "", use_web_search: bool = True) -> str:
        """Web検索結果も含めて強化された回答を生成"""
        
        # Web検索結果を取得
        web_context = ""
        if use_web_search and self.should_search_web(query):
            logger.info(f"Performing web search for: {query}")
            search_results = self.search_web(query)
            
            if search_results:
                web_context = "\n\n【参考：最新のWeb情報】\n"
                for i, result in enumerate(search_results, 1):
                    web_context += f"{i}. {result['title']} ({result['domain']})\n"
                    web_context += f"   {result['snippet']}\n\n"
        
        # プロンプトを構築
        system_prompt = """あなたは親切で知識豊富な日本語のAIアシスタントです。
ユーザーの質問に対して、正確で分かりやすい回答を提供してください。
重要：出典や参考文献については言及せず、自然な会話として回答してください。"""

        # f-string内のバックスラッシュを回避
        context_section = f'【関連文書情報】\n{context}\n' if context else ''
        
        user_prompt = f"""{context_section}
{web_context if web_context else ''}

質問: {query}

以下の点に注意して回答してください：
- 自然で親しみやすい日本語で回答する
- 情報源については触れない
- 具体的で実用的な回答を心がける
- 必要に応じて例を挙げて説明する"""

        try:
            if self.openai_api_key:
                client = openai.OpenAI(api_key=self.openai_api_key)
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800
                )
                return response.choices[0].message.content
            else:
                return "申し訳ございません。回答を生成できませんでした。"
                
        except Exception as e:
            logger.error(f"Error generating enhanced answer: {e}")
            return "申し訳ございません。エラーが発生しました。もう一度お試しください。"
    
    def should_search_web(self, query: str) -> bool:
        """Web検索が必要かどうかを判定"""
        # 最新情報が必要そうなキーワード
        current_keywords = [
            "最新", "現在", "今", "2024", "2025", "ニュース", 
            "天気", "株価", "為替", "最近", "新しい", "トレンド",
            "価格", "値段", "料金", "コスト"
        ]
        
        # 一般的な知識で答えられそうな質問
        general_keywords = [
            "とは", "って何", "意味", "定義", "歴史", "基本",
            "仕組み", "原理", "理論"
        ]
        
        # 技術的な質問でもバージョン情報が必要な場合
        tech_keywords = [
            "バージョン", "アップデート", "リリース", "最新版"
        ]
        
        query_lower = query.lower()
        
        # 最新情報が必要な場合
        if any(keyword in query for keyword in current_keywords):
            return True
        
        # 技術的な最新情報が必要な場合
        if any(keyword in query for keyword in tech_keywords):
            return True
            
        # 一般的な質問の場合はFalse
        if any(keyword in query for keyword in general_keywords) and \
           not any(keyword in query for keyword in current_keywords):
            return False
            
        # 疑問詞で始まる具体的な質問は検索する可能性
        specific_questions = ["どこで", "いくら", "何円", "どの"]
        if any(query.startswith(q) for q in specific_questions):
            return True
            
        # デフォルトはFalse（RAGデータベースを優先）
        return False