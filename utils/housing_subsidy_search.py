# utils/housing_subsidy_search.py - 住宅補助金ハルチネーション対策システム

import os
import logging
import requests
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import openai
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

@dataclass
class SubsidySearchResult:
    """補助金検索結果"""
    title: str
    url: str
    content: str
    last_updated: Optional[str]
    source_domain: str
    relevance_score: float
    is_current_year: bool
    subsidy_type: str

class HousingSubsidySearcher:
    """住宅補助金専用検索・ハルチネーション対策クラス"""
    
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.google_api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        self.google_cx = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
        self.search_endpoint = "https://www.googleapis.com/customsearch/v1"
        
        # 住宅補助金関連の信頼できるサイト
        self.trusted_domains = [
            "mlit.go.jp",  # 国土交通省
            "nta.go.jp",   # 国税庁
            "jhf.go.jp",   # 住宅金融支援機構
            "flat35.com",  # フラット35
            "pref.hyogo.lg.jp",  # 兵庫県
            "pref.osaka.lg.jp",  # 大阪府
            "city.kato.lg.jp",   # 加東市
            "city.kakogawa.lg.jp", # 加古川市
            "city.akashi.lg.jp",   # 明石市
            "city.miki.lg.jp",     # 三木市
            "city.neyagawa.osaka.jp", # 寝屋川市
            "city.osaka.lg.jp"     # 大阪市
        ]
        
        # 補助金キーワードマッピング
        self.subsidy_keywords = {
            "住宅ローン控除": ["住宅ローン控除", "住宅ローン減税", "住宅借入金等特別控除"],
            "ZEH補助金": ["ZEH", "ゼロエネルギーハウス", "ネット・ゼロ・エネルギー・ハウス"],
            "省エネ住宅": ["省エネ住宅", "断熱改修", "省エネリフォーム"],
            "耐震改修": ["耐震改修", "耐震補強", "耐震診断"],
            "子育て支援": ["子育て世帯", "若年夫婦世帯", "新婚世帯"],
            "地域型住宅": ["地域型住宅グリーン化事業", "長期優良住宅"],
            "空き家対策": ["空き家", "中古住宅", "リノベーション"],
            "バリアフリー": ["バリアフリー", "高齢者住宅改修", "介護保険"]
        }
        
        self.current_year = datetime.now().year
    
    async def search_with_anti_hallucination(
        self, 
        query: str, 
        user_location: str = "関西"
    ) -> Dict[str, any]:
        """ハルチネーション対策付き補助金検索"""
        
        logger.info(f"🔍 住宅補助金検索開始: {query}")
        
        # 1. 検索キーワードの拡張と分類
        expanded_queries = self._expand_search_queries(query)
        
        # 2. 複数の検索戦略で情報収集
        search_results = []
        for expanded_query in expanded_queries:
            results = await self._multi_strategy_search(expanded_query, user_location)
            search_results.extend(results)
        
        # 3. 結果の検証とフィルタリング
        verified_results = await self._verify_and_filter_results(search_results, query)
        
        # 4. ハルチネーション対策の実行
        anti_hallucination_result = await self._apply_anti_hallucination_logic(
            query, verified_results
        )
        
        # 5. 最終回答の生成
        final_answer = await self._generate_verified_answer(
            query, anti_hallucination_result
        )
        
        return {
            "answer": final_answer["answer"],
            "last_updated": final_answer["last_updated"],
            "sources": final_answer["sources"],
            "confidence_level": final_answer["confidence_level"],
            "verification_status": final_answer["verification_status"],
            "search_strategy_used": anti_hallucination_result["strategy_used"]
        }
    
    def _expand_search_queries(self, original_query: str) -> List[str]:
        """検索クエリの拡張"""
        expanded = [original_query]
        
        # 年度を含むクエリ
        expanded.append(f"{original_query} {self.current_year}年度")
        expanded.append(f"{original_query} 令和{self.current_year-2018}年度")
        
        # 補助金タイプ別のクエリ拡張
        for category, keywords in self.subsidy_keywords.items():
            if any(keyword in original_query for keyword in keywords):
                for keyword in keywords:
                    if keyword not in original_query:
                        expanded.append(f"{keyword} {self.current_year}年度 補助金")
        
        # 地域別クエリ
        expanded.append(f"{original_query} 兵庫県")
        expanded.append(f"{original_query} 大阪府")
        
        return list(set(expanded))  # 重複除去
    
    async def _multi_strategy_search(
        self, 
        query: str, 
        location: str
    ) -> List[SubsidySearchResult]:
        """複数戦略での検索実行"""
        
        results = []
        
        # 戦略1: 信頼できるサイト限定検索
        trusted_results = await self._search_trusted_sites(query)
        results.extend(trusted_results)
        
        # 戦略2: 一般検索（最新情報優先）
        general_results = await self._search_general_with_date_filter(query)
        results.extend(general_results)
        
        # 戦略3: 類似キーワード検索（情報が少ない場合）
        if len(results) < 3:
            similar_results = await self._search_similar_keywords(query)
            results.extend(similar_results)
        
        return results
    
    async def _search_trusted_sites(self, query: str) -> List[SubsidySearchResult]:
        """信頼できるサイト限定検索"""
        results = []
        
        for domain in self.trusted_domains[:5]:  # 上位5サイトで検索
            site_query = f"{query} site:{domain}"
            
            try:
                search_results = await self._google_search(site_query, num_results=3)
                
                for result in search_results:
                    subsidy_result = await self._create_subsidy_result(result, query)
                    if subsidy_result:
                        results.append(subsidy_result)
                        
            except Exception as e:
                logger.error(f"Trusted site search error for {domain}: {e}")
        
        return results
    
    async def _search_general_with_date_filter(self, query: str) -> List[SubsidySearchResult]:
        """日付フィルター付き一般検索"""
        # 過去1年以内の結果を優先
        date_filtered_query = f"{query} after:{self.current_year-1}"
        
        try:
            search_results = await self._google_search(date_filtered_query, num_results=5)
            
            results = []
            for result in search_results:
                subsidy_result = await self._create_subsidy_result(result, query)
                if subsidy_result:
                    results.append(subsidy_result)
            
            return results
            
        except Exception as e:
            logger.error(f"Date filtered search error: {e}")
            return []
    
    async def _search_similar_keywords(self, query: str) -> List[SubsidySearchResult]:
        """類似キーワード検索"""
        results = []
        
        # 類似キーワードの生成
        similar_queries = self._generate_similar_queries(query)
        
        for similar_query in similar_queries[:3]:  # 上位3つの類似クエリ
            try:
                search_results = await self._google_search(similar_query, num_results=3)
                
                for result in search_results:
                    subsidy_result = await self._create_subsidy_result(result, query)
                    if subsidy_result:
                        subsidy_result.relevance_score *= 0.8  # 類似検索なので関連度を下げる
                        results.append(subsidy_result)
                        
            except Exception as e:
                logger.error(f"Similar keyword search error: {e}")
        
        return results
    
    def _generate_similar_queries(self, original_query: str) -> List[str]:
        """類似クエリの生成"""
        similar = []
        
        # 同義語マッピング
        synonyms = {
            "補助金": ["助成金", "支援金", "給付金"],
            "住宅": ["家", "マイホーム", "戸建て"],
            "リフォーム": ["改修", "改築", "リノベーション"],
            "省エネ": ["エコ", "環境配慮", "断熱"],
            "耐震": ["地震対策", "構造補強"]
        }
        
        for word, synonym_list in synonyms.items():
            if word in original_query:
                for synonym in synonym_list:
                    similar.append(original_query.replace(word, synonym))
        
        return similar
    
    async def _google_search(self, query: str, num_results: int = 5) -> List[Dict]:
        """Google Custom Search API呼び出し"""
        if not self.google_api_key or not self.google_cx:
            logger.warning("Google Search API credentials not configured")
            return []
        
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cx,
                "q": query,
                "num": num_results,
                "hl": "ja",
                "gl": "jp"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.search_endpoint, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("items", [])
                    else:
                        logger.error(f"Google Search API error: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Google Search error: {e}")
            return []
    
    async def _create_subsidy_result(
        self, 
        search_item: Dict, 
        original_query: str
    ) -> Optional[SubsidySearchResult]:
        """検索結果からSubsidySearchResultを作成"""
        
        try:
            url = search_item.get("link", "")
            domain = urlparse(url).netloc
            
            # ページ内容の取得と最終更新日の抽出
            last_updated, content = await self._extract_page_info(url)
            
            # 関連度スコアの計算
            relevance_score = self._calculate_relevance_score(
                search_item.get("title", ""),
                search_item.get("snippet", ""),
                content,
                original_query
            )
            
            # 補助金タイプの判定
            subsidy_type = self._determine_subsidy_type(
                search_item.get("title", "") + " " + search_item.get("snippet", "")
            )
            
            # 現年度情報かチェック
            is_current_year = self._is_current_year_info(content, last_updated)
            
            return SubsidySearchResult(
                title=search_item.get("title", ""),
                url=url,
                content=content,
                last_updated=last_updated,
                source_domain=domain,
                relevance_score=relevance_score,
                is_current_year=is_current_year,
                subsidy_type=subsidy_type
            )
            
        except Exception as e:
            logger.error(f"Error creating subsidy result: {e}")
            return None
    
    async def _extract_page_info(self, url: str) -> Tuple[Optional[str], str]:
        """ページから最終更新日と内容を抽出"""
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # 最終更新日の抽出
                        last_updated = self._extract_last_updated_date(soup)
                        
                        # メインコンテンツの抽出
                        content = self._extract_main_content(soup)
                        
                        return last_updated, content
                    else:
                        return None, ""
                        
        except Exception as e:
            logger.error(f"Error extracting page info from {url}: {e}")
            return None, ""
    
    def _extract_last_updated_date(self, soup: BeautifulSoup) -> Optional[str]:
        """最終更新日の抽出"""
        
        # よくある更新日のパターン
        date_patterns = [
            # メタタグ
            soup.find("meta", {"name": "last-modified"}),
            soup.find("meta", {"property": "article:modified_time"}),
            
            # クラス名での検索
            soup.find(class_=lambda x: x and any(
                keyword in x.lower() for keyword in ["update", "modified", "date", "更新"]
            )),
            
            # テキストパターン
            soup.find(string=re.compile(r"更新日|最終更新|更新：|Updated|Modified")),
        ]
        
        for pattern in date_patterns:
            if pattern:
                if hasattr(pattern, 'get'):
                    date_str = pattern.get('content', '')
                elif hasattr(pattern, 'parent'):
                    date_str = pattern.parent.get_text()
                else:
                    date_str = str(pattern)
                
                # 日付の正規化
                normalized_date = self._normalize_date(date_str)
                if normalized_date:
                    return normalized_date
        
        return None
    
    def _normalize_date(self, date_str: str) -> Optional[str]:
        """日付文字列の正規化"""
        
        # 日付パターンの正規表現
        patterns = [
            r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})',  # 2024-01-01, 2024年1月1日
            r'令和(\d+)年(\d{1,2})月(\d{1,2})日',        # 令和6年1月1日
            r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})', # ISO形式
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                try:
                    if '令和' in pattern:
                        # 令和を西暦に変換
                        reiwa_year = int(match.group(1))
                        year = 2018 + reiwa_year
                        month = int(match.group(2))
                        day = int(match.group(3))
                    else:
                        year = int(match.group(1))
                        month = int(match.group(2))
                        day = int(match.group(3))
                    
                    return f"{year}年{month}月{day}日"
                    
                except (ValueError, IndexError):
                    continue
        
        return None
    
    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """メインコンテンツの抽出"""
        
        # 不要な要素を削除
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        
        # メインコンテンツの候補
        main_content_selectors = [
            "main",
            "article", 
            ".content",
            ".main-content",
            "#content",
            "#main"
        ]
        
        for selector in main_content_selectors:
            element = soup.select_one(selector)
            if element:
                return element.get_text(strip=True)[:2000]  # 2000文字まで
        
        # フォールバック: body全体
        body = soup.find("body")
        if body:
            return body.get_text(strip=True)[:2000]
        
        return soup.get_text(strip=True)[:2000]
    
    def _calculate_relevance_score(
        self, 
        title: str, 
        snippet: str, 
        content: str, 
        query: str
    ) -> float:
        """関連度スコアの計算"""
        
        score = 0.0
        query_words = query.lower().split()
        
        # タイトルマッチ（重要度高）
        title_lower = title.lower()
        for word in query_words:
            if word in title_lower:
                score += 0.3
        
        # スニペットマッチ
        snippet_lower = snippet.lower()
        for word in query_words:
            if word in snippet_lower:
                score += 0.2
        
        # コンテンツマッチ
        content_lower = content.lower()
        for word in query_words:
            if word in content_lower:
                score += 0.1
        
        # 補助金関連キーワードボーナス
        subsidy_keywords = ["補助金", "助成金", "支援", "制度", "申請"]
        for keyword in subsidy_keywords:
            if keyword in title_lower or keyword in snippet_lower:
                score += 0.2
        
        return min(score, 1.0)  # 最大1.0
    
    def _determine_subsidy_type(self, text: str) -> str:
        """補助金タイプの判定"""
        
        text_lower = text.lower()
        
        type_keywords = {
            "住宅ローン控除": ["住宅ローン控除", "減税"],
            "ZEH補助金": ["zeh", "ゼロエネルギー"],
            "省エネ補助金": ["省エネ", "断熱"],
            "耐震補助金": ["耐震", "地震"],
            "子育て支援": ["子育て", "若年"],
            "リフォーム補助金": ["リフォーム", "改修"],
            "その他": []
        }
        
        for subsidy_type, keywords in type_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                return subsidy_type
        
        return "その他"
    
    def _is_current_year_info(self, content: str, last_updated: Optional[str]) -> bool:
        """現年度の情報かチェック"""
        
        current_year_str = str(self.current_year)
        current_reiwa = f"令和{self.current_year - 2018}"
        
        # コンテンツに現年度の記載があるか
        if current_year_str in content or current_reiwa in content:
            return True
        
        # 最終更新日が現年度か
        if last_updated and current_year_str in last_updated:
            return True
        
        return False
    
    async def _verify_and_filter_results(
        self, 
        results: List[SubsidySearchResult], 
        original_query: str
    ) -> List[SubsidySearchResult]:
        """検索結果の検証とフィルタリング"""
        
        # 関連度でソート
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        # 信頼できるドメインを優先
        trusted_results = [r for r in results if any(domain in r.source_domain for domain in self.trusted_domains)]
        other_results = [r for r in results if not any(domain in r.source_domain for domain in self.trusted_domains)]
        
        # 現年度情報を優先
        current_year_results = [r for r in trusted_results + other_results if r.is_current_year]
        other_year_results = [r for r in trusted_results + other_results if not r.is_current_year]
        
        # 最終的な結果（上位10件まで）
        verified_results = (current_year_results + other_year_results)[:10]
        
        return verified_results
    
    async def _apply_anti_hallucination_logic(
        self, 
        query: str, 
        verified_results: List[SubsidySearchResult]
    ) -> Dict[str, any]:
        """ハルチネーション対策ロジックの適用"""
        
        if not verified_results:
            # 情報が見つからない場合のフォールバック戦略
            return await self._fallback_strategy(query)
        
        # 信頼性レベルの判定
        confidence_level = self._calculate_confidence_level(verified_results)
        
        if confidence_level >= 0.8:
            # 高信頼性：通常の回答生成
            strategy = "high_confidence"
            verification_status = "verified"
            
        elif confidence_level >= 0.5:
            # 中信頼性：注意書き付きの回答
            strategy = "medium_confidence"
            verification_status = "partially_verified"
            
        else:
            # 低信頼性：一般的な回答 + 最新情報確認の推奨
            strategy = "low_confidence"
            verification_status = "unverified"
        
        return {
            "results": verified_results,
            "confidence_level": confidence_level,
            "strategy_used": strategy,
            "verification_status": verification_status
        }
    
    def _calculate_confidence_level(self, results: List[SubsidySearchResult]) -> float:
        """信頼性レベルの計算"""
        
        if not results:
            return 0.0
        
        # 信頼できるサイトからの結果の割合
        trusted_count = sum(1 for r in results if any(domain in r.source_domain for domain in self.trusted_domains))
        trusted_ratio = trusted_count / len(results)
        
        # 現年度情報の割合
        current_year_count = sum(1 for r in results if r.is_current_year)
        current_year_ratio = current_year_count / len(results)
        
        # 平均関連度スコア
        avg_relevance = sum(r.relevance_score for r in results) / len(results)
        
        # 総合信頼性スコア
        confidence = (trusted_ratio * 0.4) + (current_year_ratio * 0.4) + (avg_relevance * 0.2)
        
        return min(confidence, 1.0)
    
    async def _fallback_strategy(self, query: str) -> Dict[str, any]:
        """フォールバック戦略"""
        
        # より広範囲での検索を試行
        broader_queries = [
            f"住宅 補助金 {self.current_year}",
            f"住宅 助成金 関西",
            "住宅 支援制度 最新"
        ]
        
        fallback_results = []
        for broader_query in broader_queries:
            results = await self._google_search(broader_query, num_results=3)
            for result in results:
                subsidy_result = await self._create_subsidy_result(result, query)
                if subsidy_result:
                    fallback_results.append(subsidy_result)
        
        return {
            "results": fallback_results,
            "confidence_level": 0.3,
            "strategy_used": "fallback",
            "verification_status": "fallback_search"
        }
    
    async def _generate_verified_answer(
        self, 
        query: str, 
        anti_hallucination_result: Dict[str, any]
    ) -> Dict[str, any]:
        """検証済み回答の生成"""
        
        results = anti_hallucination_result["results"]
        confidence_level = anti_hallucination_result["confidence_level"]
        verification_status = anti_hallucination_result["verification_status"]
        
        if not results:
            return {
                "answer": "申し訳ございません。現在、お尋ねの補助金に関する最新情報が見つかりませんでした。住宅補助金の制度は年度ごとに変更される可能性がありますので、最新情報については管轄の行政機関にお問い合わせいただくことをお勧めいたします。",
                "last_updated": None,
                "sources": [],
                "confidence_level": 0.0,
                "verification_status": "no_information_found"
            }
        
        # OpenAI APIで回答生成
        if self.openai_api_key:
            try:
                answer = await self._generate_openai_answer(query, results, confidence_level)
            except Exception as e:
                logger.error(f"OpenAI answer generation failed: {e}")
                answer = self._generate_fallback_answer(query, results)
        else:
            answer = self._generate_fallback_answer(query, results)
        
        # 最新の更新日を取得
        latest_update = self._get_latest_update_date(results)
        
        # ソース情報
        sources = [
            {
                "title": r.title,
                "url": r.url,
                "domain": r.source_domain,
                "last_updated": r.last_updated,
                "subsidy_type": r.subsidy_type
            }
            for r in results[:3]  # 上位3件
        ]
        
        return {
            "answer": answer,
            "last_updated": latest_update,
            "sources": sources,
            "confidence_level": confidence_level,
            "verification_status": verification_status
        }
    
    async def _generate_openai_answer(
        self, 
        query: str, 
        results: List[SubsidySearchResult], 
        confidence_level: float
    ) -> str:
        """OpenAI APIを使用した回答生成"""
        
        # コンテキスト情報の準備
        context_info = []
        for result in results[:3]:
            context_info.append(f"【{result.title}】\n内容: {result.content[:300]}...\n更新日: {result.last_updated or '不明'}\nURL: {result.url}")
        
        context = "\n\n".join(context_info)
        
        # 信頼性レベルに応じたプロンプト調整
        if confidence_level >= 0.8:
            confidence_note = ""
        elif confidence_level >= 0.5:
            confidence_note = "\n\n※この情報は複数のソースを参照していますが、最新の詳細については公式サイトでご確認ください。"
        else:
            confidence_note = "\n\n※限られた情報に基づく回答のため、最新の正確な情報については必ず管轄の行政機関にお問い合わせください。"
        
        system_prompt = f"""あなたは住宅補助金制度の専門アドバイザーです。
以下の検索結果を基に、ユーザーの質問に対して正確で有用な回答を提供してください。

【重要な指示】
- 検索結果に基づいて回答し、推測や憶測は避ける
- 年度や期限などの重要な情報は必ず明記する
- 申請条件や手続きについて具体的に説明する
- 情報の出典は明記しない（回答に含めない）
- 自然で分かりやすい日本語で回答する
- 信頼性レベル: {confidence_level:.1f}"""

        user_prompt = f"""質問: {query}

検索結果:
{context}

上記の情報を基に、質問に対して具体的で有用な回答を提供してください。{confidence_note}"""

        try:
            client = openai.OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def _generate_fallback_answer(
        self, 
        query: str, 
        results: List[SubsidySearchResult]
    ) -> str:
        """フォールバック回答の生成"""
        
        if not results:
            return "申し訳ございません。お尋ねの補助金制度について、現在最新の情報を取得できませんでした。"
        
        # 最も関連度の高い結果を使用
        best_result = results[0]
        
        answer = f"『{query}』について、以下の情報が見つかりました。\n\n"
        answer += f"{best_result.content[:300]}...\n\n"
        
        if best_result.last_updated:
            answer += f"※この情報は{best_result.last_updated}時点のものです。"
        
        answer += "最新の詳細については、管轄の行政機関に直接お問い合わせいただくことをお勧めいたします。"
        
        return answer
    
    def _get_latest_update_date(self, results: List[SubsidySearchResult]) -> Optional[str]:
        """最新の更新日を取得"""
        
        dates_with_results = [(r.last_updated, r) for r in results if r.last_updated]
        
        if not dates_with_results:
            return None
        
        # 最新の日付を選択（簡易的な比較）
        latest_date = None
        for date_str, result in dates_with_results:
            if latest_date is None or self.current_year in date_str:
                latest_date = date_str
        
        return latest_date


# 使用例とテスト用の関数
async def test_housing_subsidy_search():
    """テスト用関数"""
    searcher = HousingSubsidySearcher()
    
    test_queries = [
        "住宅ローン控除 2025年度",
        "ZEH補助金 兵庫県",
        "子育て世帯向け住宅支援制度",
        "耐震改修 補助金 加東市"
    ]
    
    for query in test_queries:
        print(f"\n{'='*50}")
        print(f"テストクエリ: {query}")
        print('='*50)
        
        try:
            result = await searcher.search_with_anti_hallucination(query)
            
            print(f"回答: {result['answer']}")
            print(f"\n最終更新日: {result['last_updated']}")
            print(f"信頼性レベル: {result['confidence_level']:.2f}")
            print(f"検証状況: {result['verification_status']}")
            
            if result['sources']:
                print("\nソース:")
                for i, source in enumerate(result['sources'], 1):
                    print(f"  {i}. {source['title']}")
                    print(f"     更新日: {source['last_updated']}")
                    print(f"     URL: {source['url']}")
        
        except Exception as e:
            print(f"エラー: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_housing_subsidy_search())