# utils/housing_subsidy_anti_hallucination.py - 統合ハルチネーション対策システム

import os
import logging
import requests
import re
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import openai
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import hashlib

logger = logging.getLogger(__name__)

@dataclass
class SubsidyInfo:
    """補助金情報"""
    title: str
    content: str
    url: str
    last_updated: Optional[str]
    source_domain: str
    subsidy_type: str
    target_year: str
    reliability_score: float
    is_current: bool

@dataclass
class AntiHallucinationResult:
    """ハルチネーション対策結果"""
    answer: str
    sources: List[SubsidyInfo]
    confidence_level: float
    verification_method: str
    last_updated: Optional[str]
    warnings: List[str]
    search_strategy_used: str

class HousingSubsidyAntiHallucination:
    """住宅補助金ハルチネーション対策システム"""
    
    def __init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        self.google_api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        self.google_cx = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
        
        # 信頼できるドメインの優先リスト（提供されたURLから抽出）
        self.trusted_domains = [
            # 国の機関
            "mlit.go.jp",           # 国土交通省
            "nta.go.jp",            # 国税庁
            "jhf.go.jp",            # 住宅金融支援機構
            "flat35.com",           # フラット35
            "kosodate-sc.jp",       # 子育てサポートセンター
            "jutaku-shoene2025.mlit.go.jp",  # 住宅省エネ
            "heco-hojo.jp",         # 住宅エコポイント
            
            # 兵庫県・市町村
            "eco-hyogo.jp",         # エコひょうご
            "web.pref.hyogo.lg.jp", # 兵庫県
            "city.kato.lg.jp",      # 加東市
            "city.kakogawa.lg.jp",  # 加古川市
            "city.akashi.lg.jp",    # 明石市
            "city.miki.lg.jp",      # 三木市
            
            # 大阪府・市町村
            "pref.osaka.lg.jp",     # 大阪府
            "city.neyagawa.osaka.jp", # 寝屋川市
            "city.osaka.lg.jp"      # 大阪市
        ]
        
        # 補助金タイプの詳細分類
        self.subsidy_categories = {
            "住宅ローン控除": {
                "keywords": ["住宅ローン控除", "住宅ローン減税", "住宅借入金等特別控除"],
                "search_terms": ["住宅ローン控除 2025", "住宅ローン減税"],
                "domains": ["nta.go.jp"]
            },
            "ZEH補助金": {
                "keywords": ["ZEH", "ゼロエネルギーハウス", "ネット・ゼロ・エネルギー・ハウス"],
                "search_terms": ["ZEH補助金 2025", "ゼロエネルギーハウス 支援"],
                "domains": ["mlit.go.jp", "jutaku-shoene2025.mlit.go.jp"]
            },
            "省エネ住宅": {
                "keywords": ["省エネ住宅", "断熱改修", "省エネリフォーム", "給湯省エネ"],
                "search_terms": ["省エネ住宅ポイント", "断熱リフォーム補助金"],
                "domains": ["mlit.go.jp", "heco-hojo.jp"]
            },
            "子育て支援": {
                "keywords": ["子育て世帯", "若年夫婦世帯", "新婚世帯", "こどもエコすまい"],
                "search_terms": ["子育て世帯支援 住宅", "こどもエコすまい支援事業"],
                "domains": ["mlit.go.jp", "kosodate-sc.jp"]
            },
            "地方補助金": {
                "keywords": ["兵庫県", "大阪府", "加東市", "明石市", "地域", "自治体"],
                "search_terms": ["兵庫県 住宅補助金", "大阪府 住宅支援"],
                "domains": ["web.pref.hyogo.lg.jp", "pref.osaka.lg.jp"]
            }
        }
        
        self.current_year = datetime.now().year
        self.cache = {}  # 検索結果キャッシュ
        
    async def process_query_with_anti_hallucination(
        self, 
        user_query: str, 
        user_location: str = "関西",
        platform: str = "web"  # "web" or "line"
    ) -> AntiHallucinationResult:
        """ハルチネーション対策付きクエリ処理"""
        
        logger.info(f"🛡️ Anti-hallucination processing: {user_query} (platform: {platform})")
        
        try:
            # 1. クエリ分析と分類
            query_analysis = self._analyze_query(user_query)
            
            # 2. 多段階検索戦略の実行
            search_results = await self._execute_multi_stage_search(
                user_query, query_analysis, user_location
            )
            
            # 3. 情報の検証と信頼性評価
            verified_results = await self._verify_information_quality(
                search_results, user_query
            )
            
            # 4. ハルチネーション対策ロジック適用
            anti_hallucination_result = await self._apply_anti_hallucination_logic(
                user_query, verified_results, platform
            )
            
            # 5. プラットフォーム特化の回答生成
            final_answer = await self._generate_platform_specific_answer(
                user_query, anti_hallucination_result, platform
            )
            
            return final_answer
            
        except Exception as e:
            logger.error(f"❌ Anti-hallucination processing error: {e}")
            return self._create_error_response(user_query, str(e))
    
    def _analyze_query(self, query: str) -> Dict[str, Any]:
        """クエリの詳細分析"""
        analysis = {
            "original_query": query,
            "detected_categories": [],
            "year_mentioned": None,
            "location_mentioned": [],
            "urgency_level": "normal",
            "information_type": "general"
        }
        
        # カテゴリ検出
        for category, config in self.subsidy_categories.items():
            if any(keyword in query for keyword in config["keywords"]):
                analysis["detected_categories"].append(category)
        
        # 年度検出
        year_patterns = [
            r'(\d{4})年度?',
            r'令和(\d+)年?',
            r'R(\d+)',
            r'(2024|2025|2026)'
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, query)
            if match:
                if '令和' in pattern:
                    reiwa_year = int(match.group(1))
                    analysis["year_mentioned"] = 2018 + reiwa_year
                else:
                    analysis["year_mentioned"] = int(match.group(1))
                break
        
        # 地域検出
        location_keywords = ["兵庫", "大阪", "関西", "加東", "明石", "三木", "寝屋川", "加古川"]
        for location in location_keywords:
            if location in query:
                analysis["location_mentioned"].append(location)
        
        # 緊急度判定
        urgent_keywords = ["最新", "現在", "今", "急いで", "すぐ"]
        if any(keyword in query for keyword in urgent_keywords):
            analysis["urgency_level"] = "high"
        
        # 情報タイプ
        if any(word in query for word in ["申請", "手続き", "方法"]):
            analysis["information_type"] = "procedural"
        elif any(word in query for word in ["金額", "額", "いくら"]):
            analysis["information_type"] = "financial"
        elif any(word in query for word in ["条件", "対象", "要件"]):
            analysis["information_type"] = "eligibility"
        
        return analysis
    
    async def _execute_multi_stage_search(
        self, 
        original_query: str,
        query_analysis: Dict[str, Any],
        user_location: str
    ) -> List[SubsidyInfo]:
        """多段階検索戦略の実行"""
        
        all_results = []
        
        # Stage 1: 信頼できるドメイン限定検索
        logger.info("🔍 Stage 1: Trusted domain search")
        trusted_results = await self._search_trusted_domains(original_query, query_analysis)
        all_results.extend(trusted_results)
        
        # Stage 2: カテゴリ特化検索
        if query_analysis["detected_categories"]:
            logger.info("🔍 Stage 2: Category-specific search")
            category_results = await self._search_by_category(
                original_query, query_analysis["detected_categories"]
            )
            all_results.extend(category_results)
        
        # Stage 3: 年度特化検索
        target_year = query_analysis["year_mentioned"] or self.current_year
        logger.info(f"🔍 Stage 3: Year-specific search ({target_year})")
        year_results = await self._search_by_year(original_query, target_year)
        all_results.extend(year_results)
        
        # Stage 4: 地域特化検索
        if query_analysis["location_mentioned"] or user_location:
            logger.info("🔍 Stage 4: Location-specific search")
            location_results = await self._search_by_location(
                original_query, query_analysis["location_mentioned"] or [user_location]
            )
            all_results.extend(location_results)
        
        # Stage 5: フォールバック検索（情報が不十分な場合）
        if len(all_results) < 3:
            logger.info("🔍 Stage 5: Fallback search")
            fallback_results = await self._fallback_search(original_query)
            all_results.extend(fallback_results)
        
        return all_results
    
    async def _search_trusted_domains(
        self, 
        query: str, 
        analysis: Dict[str, Any]
    ) -> List[SubsidyInfo]:
        """信頼できるドメイン限定検索"""
        
        results = []
        
        # 分析結果に基づいて検索ドメインを絞り込み
        target_domains = self.trusted_domains
        if analysis["detected_categories"]:
            category_domains = []
            for category in analysis["detected_categories"]:
                category_domains.extend(
                    self.subsidy_categories[category].get("domains", [])
                )
            if category_domains:
                target_domains = list(set(category_domains) & set(self.trusted_domains))
        
        # 各ドメインで検索実行
        for domain in target_domains[:5]:  # 上位5ドメインのみ
            search_query = f"{query} site:{domain}"
            
            try:
                search_results = await self._google_search(search_query, num_results=3)
                
                for result in search_results:
                    subsidy_info = await self._create_subsidy_info(result, query, "trusted_domain")
                    if subsidy_info:
                        results.append(subsidy_info)
                        
            except Exception as e:
                logger.error(f"Error searching domain {domain}: {e}")
        
        return results
    
    async def _search_by_category(
        self, 
        query: str, 
        categories: List[str]
    ) -> List[SubsidyInfo]:
        """カテゴリ特化検索"""
        
        results = []
        
        for category in categories:
            category_config = self.subsidy_categories.get(category, {})
            search_terms = category_config.get("search_terms", [])
            
            # カテゴリ特有の検索語で検索
            for search_term in search_terms:
                try:
                    search_results = await self._google_search(search_term, num_results=3)
                    
                    for result in search_results:
                        subsidy_info = await self._create_subsidy_info(
                            result, query, f"category_{category}"
                        )
                        if subsidy_info:
                            results.append(subsidy_info)
                            
                except Exception as e:
                    logger.error(f"Error in category search for {category}: {e}")
        
        return results
    
    async def _search_by_year(self, query: str, year: int) -> List[SubsidyInfo]:
        """年度特化検索"""
        
        year_queries = [
            f"{query} {year}年度",
            f"{query} 令和{year-2018}年",
            f"{query} {year}"
        ]
        
        results = []
        
        for year_query in year_queries:
            try:
                search_results = await self._google_search(year_query, num_results=3)
                
                for result in search_results:
                    subsidy_info = await self._create_subsidy_info(
                        result, query, f"year_{year}"
                    )
                    if subsidy_info:
                        results.append(subsidy_info)
                        
            except Exception as e:
                logger.error(f"Error in year search: {e}")
        
        return results
    
    async def _search_by_location(
        self, 
        query: str, 
        locations: List[str]
    ) -> List[SubsidyInfo]:
        """地域特化検索"""
        
        results = []
        
        for location in locations:
            location_queries = [
                f"{query} {location}",
                f"{location} 住宅補助金",
                f"{location} 住宅支援制度"
            ]
            
            for location_query in location_queries:
                try:
                    search_results = await self._google_search(location_query, num_results=3)
                    
                    for result in search_results:
                        subsidy_info = await self._create_subsidy_info(
                            result, query, f"location_{location}"
                        )
                        if subsidy_info:
                            results.append(subsidy_info)
                            
                except Exception as e:
                    logger.error(f"Error in location search for {location}: {e}")
        
        return results
    
    async def _fallback_search(self, query: str) -> List[SubsidyInfo]:
        """フォールバック検索（情報が不十分な場合）"""
        
        # より広範囲な検索語を生成
        fallback_queries = [
            f"住宅補助金 {self.current_year}",
            f"住宅支援制度 最新",
            f"マイホーム 助成金",
            "住宅ローン控除 最新",
            "省エネ住宅 補助金"
        ]
        
        results = []
        
        for fallback_query in fallback_queries:
            try:
                search_results = await self._google_search(fallback_query, num_results=2)
                
                for result in search_results:
                    subsidy_info = await self._create_subsidy_info(
                        result, query, "fallback"
                    )
                    if subsidy_info:
                        results.append(subsidy_info)
                        
            except Exception as e:
                logger.error(f"Error in fallback search: {e}")
        
        return results
    
    async def _google_search(self, query: str, num_results: int = 5) -> List[Dict]:
        """Google Custom Search API呼び出し"""
        
        if not self.google_api_key or not self.google_cx:
            logger.warning("Google Search API credentials not configured")
            return []
        
        # キャッシュチェック
        cache_key = hashlib.md5(f"{query}_{num_results}".encode()).hexdigest()
        if cache_key in self.cache:
            cache_time, cached_results = self.cache[cache_key]
            if (datetime.now() - cache_time).seconds < 3600:  # 1時間キャッシュ
                return cached_results
        
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cx,
                "q": query,
                "num": num_results,
                "hl": "ja",
                "gl": "jp",
                "dateRestrict": "y1"  # 1年以内の結果を優先
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.googleapis.com/customsearch/v1", 
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("items", [])
                        
                        # キャッシュに保存
                        self.cache[cache_key] = (datetime.now(), results)
                        
                        return results
                    else:
                        logger.error(f"Google Search API error: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Google Search error: {e}")
            return []
    
    async def _create_subsidy_info(
        self, 
        search_result: Dict, 
        original_query: str,
        search_method: str
    ) -> Optional[SubsidyInfo]:
        """検索結果からSubsidyInfoを作成"""
        
        try:
            url = search_result.get("link", "")
            domain = urlparse(url).netloc
            
            # ページ内容と最終更新日を取得
            last_updated, content = await self._extract_page_content(url)
            
            # 信頼性スコア計算
            reliability_score = self._calculate_reliability_score(
                search_result, content, domain, search_method
            )
            
            # 補助金タイプ判定
            subsidy_type = self._determine_subsidy_type(
                search_result.get("title", "") + " " + content
            )
            
            # 対象年度検出
            target_year = self._extract_target_year(content, last_updated)
            
            # 現在有効かチェック
            is_current = self._check_if_current(content, last_updated, target_year)
            
            return SubsidyInfo(
                title=search_result.get("title", ""),
                content=content,
                url=url,
                last_updated=last_updated,
                source_domain=domain,
                subsidy_type=subsidy_type,
                target_year=target_year,
                reliability_score=reliability_score,
                is_current=is_current
            )
            
        except Exception as e:
            logger.error(f"Error creating subsidy info: {e}")
            return None
    
    async def _extract_page_content(self, url: str) -> Tuple[Optional[str], str]:
        """ページ内容と最終更新日を抽出"""
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # 最終更新日の抽出
                        last_updated = self._extract_last_updated(soup)
                        
                        # メインコンテンツの抽出
                        content = self._extract_main_content(soup)
                        
                        return last_updated, content
                    else:
                        return None, ""
                        
        except Exception as e:
            logger.error(f"Error extracting page content from {url}: {e}")
            return None, ""
    
    def _extract_last_updated(self, soup: BeautifulSoup) -> Optional[str]:
        """最終更新日の抽出（改良版）"""
        
        # メタタグからの抽出
        meta_patterns = [
            soup.find("meta", {"name": "last-modified"}),
            soup.find("meta", {"property": "article:modified_time"}),
            soup.find("meta", {"name": "date"}),
        ]
        
        for meta in meta_patterns:
            if meta and meta.get("content"):
                date_str = self._normalize_date_string(meta.get("content"))
                if date_str:
                    return date_str
        
        # テキストからの抽出
        date_text_patterns = [
            r'更新日[:：]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}日?)',
            r'最終更新[:：]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}日?)',
            r'令和(\d+)年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})年(\d{1,2})月(\d{1,2})日'
        ]
        
        page_text = soup.get_text()
        for pattern in date_text_patterns:
            match = re.search(pattern, page_text)
            if match:
                if '令和' in pattern:
                    reiwa_year = int(match.group(1))
                    year = 2018 + reiwa_year
                    month = int(match.group(2))
                    day = int(match.group(3))
                    return f"{year}年{month}月{day}日"
                else:
                    date_str = self._normalize_date_string(match.group(0))
                    if date_str:
                        return date_str
        
        return None
    
    def _normalize_date_string(self, date_str: str) -> Optional[str]:
        """日付文字列の正規化"""
        
        if not date_str:
            return None
        
        # ISO形式の処理
        if 'T' in date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime("%Y年%m月%d日")
            except:
                pass
        
        # 日本語形式の処理
        patterns = [
            (r'(\d{4})[-年](\d{1,2})[-月](\d{1,2})', r'\1年\2月\3日'),
            (r'(\d{4})/(\d{1,2})/(\d{1,2})', r'\1年\2月\3日'),
        ]
        
        for pattern, replacement in patterns:
            match = re.search(pattern, date_str)
            if match:
                year, month, day = match.groups()
                return f"{year}年{int(month)}月{int(day)}日"
        
        return None
    
    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """メインコンテンツの抽出（改良版）"""
        
        # 不要な要素を削除
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "menu"]):
            tag.decompose()
        
        # メインコンテンツの候補を優先順で試行
        content_selectors = [
            "main",
            "article",
            ".content",
            ".main-content",
            "#content",
            "#main",
            ".post-content",
            ".entry-content"
        ]
        
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if len(text) > 100:  # 十分な内容があるか確認
                    return text[:2000]  # 2000文字まで
        
        # フォールバック
        body = soup.find("body")
        if body:
            return body.get_text(strip=True)[:2000]
        
        return soup.get_text(strip=True)[:2000]
    
    def _calculate_reliability_score(
        self, 
        search_result: Dict, 
        content: str, 
        domain: str,
        search_method: str
    ) -> float:
        """信頼性スコアの計算"""
        
        score = 0.0
        
        # ドメインの信頼性
        if domain in self.trusted_domains:
            score += 0.4
        
        # 政府系ドメインの追加ボーナス
        if any(gov_domain in domain for gov_domain in ["go.jp", "lg.jp"]):
            score += 0.2
        
        # 検索方法による信頼性
        method_scores = {
            "trusted_domain": 0.3,
            "category_": 0.2,
            "year_": 0.2,
            "location_": 0.1,
            "fallback": 0.05
        }
        
        for method, method_score in method_scores.items():
            if search_method.startswith(method):
                score += method_score
                break
        
        # コンテンツの質
        if len(content) > 500:
            score += 0.1
        
        # 最新年度の言及
        current_year_str = str(self.current_year)
        if current_year_str in content:
            score += 0.1
        
        return min(score, 1.0)
    
    def _determine_subsidy_type(self, text: str) -> str:
        """補助金タイプの判定"""
        
        text_lower = text.lower()
        
        for category, config in self.subsidy_categories.items():
            keywords = config.get("keywords", [])
            if any(keyword.lower() in text_lower for keyword in keywords):
                return category
        
        return "その他"
    
    def _extract_target_year(self, content: str, last_updated: Optional[str]) -> str:
        """対象年度の抽出"""
        
        # コンテンツから年度を検索
        year_patterns = [
            rf'({self.current_year}|{self.current_year+1})年度',
            rf'令和({self.current_year-2018}|{self.current_year-2017})年',
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, content)
            if match:
                if '令和' in pattern:
                    reiwa_year = int(match.group(1))
                    return str(2018 + reiwa_year)
                else:
                    return match.group(1)
        
        # 最終更新日から推測
        if last_updated and str(self.current_year) in last_updated:
            return str(self.current_year)
        
        return str(self.current_year)
    
    def _check_if_current(
        self, 
        content: str, 
        last_updated: Optional[str], 
        target_year: str
    ) -> bool:
        """現在有効な情報かチェック"""
        
        # 現年度の情報かチェック
        if target_year == str(self.current_year):
            return True
        
        # 最終更新日が最近かチェック
        if last_updated:
            try:
                # 簡易的な日付チェック
                if str(self.current_year) in last_updated:
                    return True
                if str(self.current_year - 1) in last_updated:
                    # 前年度の更新でも年度跨ぎの可能性で有効とする
                    current_month = datetime.now().month
                    if current_month <= 6:  # 上半期なら前年度情報も有効
                        return True
            except:
                pass
        
        return False
    
    async def _verify_information_quality(
        self, 
        search_results: List[SubsidyInfo], 
        original_query: str
    ) -> List[SubsidyInfo]:
        """情報品質の検証"""
        
        # 信頼性スコアでソート
        sorted_results = sorted(
            search_results, 
            key=lambda x: (x.reliability_score, x.is_current), 
            reverse=True
        )
        
        # 重複除去
        unique_results = []
        seen_urls = set()
        
        for result in sorted_results:
            if result.url not in seen_urls:
                unique_results.append(result)
                seen_urls.add(result.url)
        
        # 上位結果のみ返却
        return unique_results[:10]
    
    async def _apply_anti_hallucination_logic(
        self, 
        query: str, 
        verified_results: List[SubsidyInfo],
        platform: str
    ) -> Dict[str, Any]:
        """ハルチネーション対策ロジックの適用"""
        
        if not verified_results:
            return {
                "confidence_level": 0.0,
                "verification_method": "no_information_found",
                "warnings": ["最新の情報が見つかりませんでした"],
                "strategy": "fallback_response"
            }
        
        # 信頼性レベルの計算
        confidence_level = self._calculate_overall_confidence(verified_results)
        
        # 警告の生成
        warnings = self._generate_warnings(verified_results)
        
        # 検証方法の判定
        verification_methods = set()
        for result in verified_results:
            if result.source_domain in self.trusted_domains:
                verification_methods.add("trusted_source")
            if result.is_current:
                verification_methods.add("current_information")
            if result.reliability_score > 0.7:
                verification_methods.add("high_reliability")
        
        verification_method = ", ".join(verification_methods) if verification_methods else "basic_search"
        
        # 戦略決定
        if confidence_level >= 0.8:
            strategy = "high_confidence_answer"
        elif confidence_level >= 0.5:
            strategy = "moderate_confidence_with_warning"
        else:
            strategy = "low_confidence_general_advice"
        
        return {
            "results": verified_results,
            "confidence_level": confidence_level,
            "verification_method": verification_method,
            "warnings": warnings,
            "strategy": strategy
        }
    
    def _calculate_overall_confidence(self, results: List[SubsidyInfo]) -> float:
        """全体の信頼性レベル計算"""
        
        if not results:
            return 0.0
        
        # 信頼できるソースの割合
        trusted_count = sum(1 for r in results if r.source_domain in self.trusted_domains)
        trusted_ratio = trusted_count / len(results)
        
        # 現在有効な情報の割合
        current_count = sum(1 for r in results if r.is_current)
        current_ratio = current_count / len(results)
        
        # 平均信頼性スコア
        avg_reliability = sum(r.reliability_score for r in results) / len(results)
        
        # 情報の一貫性
        unique_types = len(set(r.subsidy_type for r in results))
        consistency_bonus = 0.1 if unique_types <= 2 else 0.0
        
        # 総合信頼性
        overall_confidence = (
            trusted_ratio * 0.3 +
            current_ratio * 0.3 +
            avg_reliability * 0.3 +
            consistency_bonus
        )
        
        return min(overall_confidence, 1.0)
    
    def _generate_warnings(self, results: List[SubsidyInfo]) -> List[str]:
        """警告メッセージの生成"""
        
        warnings = []
        
        # 古い情報の警告
        outdated_count = sum(1 for r in results if not r.is_current)
        if outdated_count > 0:
            warnings.append("一部古い情報が含まれている可能性があります")
        
        # 信頼性の低い情報の警告
        low_reliability_count = sum(1 for r in results if r.reliability_score < 0.5)
        if low_reliability_count > len(results) / 2:
            warnings.append("情報の信頼性が限定的です")
        
        # 情報不足の警告
        if len(results) < 3:
            warnings.append("情報が限定的です")
        
        return warnings
    
    async def _generate_platform_specific_answer(
        self, 
        query: str,
        anti_hallucination_result: Dict[str, Any],
        platform: str
    ) -> AntiHallucinationResult:
        """プラットフォーム特化回答生成"""
        
        results = anti_hallucination_result.get("results", [])
        confidence_level = anti_hallucination_result["confidence_level"]
        strategy = anti_hallucination_result["strategy"]
        warnings = anti_hallucination_result["warnings"]
        
        # 回答生成
        if self.openai_api_key and results:
            answer = await self._generate_ai_answer(
                query, results, confidence_level, platform, strategy
            )
        else:
            answer = self._generate_fallback_answer(query, results, strategy)
        
        # 最新更新日の取得
        latest_update = self._get_latest_update_date(results)
        
        # ソース情報（プラットフォームに応じて調整）
        sources = self._format_sources_for_platform(results, platform)
        
        return AntiHallucinationResult(
            answer=answer,
            sources=sources,
            confidence_level=confidence_level,
            verification_method=anti_hallucination_result["verification_method"],
            last_updated=latest_update,
            warnings=warnings,
            search_strategy_used=strategy
        )
    
    async def _generate_ai_answer(
        self,
        query: str,
        results: List[SubsidyInfo],
        confidence_level: float,
        platform: str,
        strategy: str
    ) -> str:
        """AI回答生成"""
        
        # プラットフォーム別の文字数制限
        max_length = 300 if platform == "line" else 600
        
        # コンテキスト準備
        context_info = []
        for result in results[:3]:  # 上位3件
            context_info.append(
                f"【{result.title}】\n"
                f"内容: {result.content[:200]}...\n"
                f"更新日: {result.last_updated or '不明'}\n"
                f"信頼性: {result.reliability_score:.1f}"
            )
        
        context = "\n\n".join(context_info)
        
        # 戦略別プロンプト調整
        confidence_instruction = self._get_confidence_instruction(strategy, confidence_level)
        platform_instruction = self._get_platform_instruction(platform, max_length)
        
        system_prompt = f"""あなたは住宅補助金制度の専門アドバイザーです。
ハルチネーション（情報の捏造）を絶対に避け、提供された検索結果のみに基づいて回答してください。

{confidence_instruction}
{platform_instruction}

【絶対禁止】
- 検索結果にない情報の追加
- 推測や憶測による回答
- 古い情報を最新として提示
- 金額や期限の不正確な情報"""

        user_prompt = f"""質問: {query}

検索結果:
{context}

上記の検索結果のみを基に、質問に回答してください。
情報が不十分な場合は、その旨を明記し、正確な情報の入手方法を案内してください。"""

        try:
            client = openai.OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # 創造性を抑制
                max_tokens=max_length + 100
            )
            
            generated_answer = response.choices[0].message.content
            
            # 回答の後処理
            return self._post_process_answer(generated_answer, max_length, platform)
            
        except Exception as e:
            logger.error(f"AI answer generation error: {e}")
            return self._generate_fallback_answer(query, results, strategy)
    
    def _get_confidence_instruction(self, strategy: str, confidence_level: float) -> str:
        """信頼性レベル別の指示"""
        
        if strategy == "high_confidence_answer":
            return "検索結果は信頼性が高いため、確実な情報として回答してください。"
        elif strategy == "moderate_confidence_with_warning":
            return f"検索結果の信頼性は中程度です（{confidence_level:.1f}）。回答に注意書きを含めてください。"
        else:
            return "検索結果の信頼性が限定的です。一般的な案内に留め、公式確認を強く推奨してください。"
    
    def _get_platform_instruction(self, platform: str, max_length: int) -> str:
        """プラットフォーム別の指示"""
        
        if platform == "line":
            return f"""【LINEチャット用指示】
- {max_length}文字以内で簡潔に
- 読みやすい改行を使用
- 絵文字は控えめに使用
- 重要な情報を冒頭に"""
        else:
            return f"""【Webサイト用指示】
- {max_length}文字程度で詳しく
- 段落分けを適切に
- 具体的な手続き方法も含める"""
    
    def _post_process_answer(self, answer: str, max_length: int, platform: str) -> str:
        """回答の後処理"""
        
        # 長さ調整
        if len(answer) > max_length:
            # 文単位で切り詰め
            sentences = answer.split('。')
            truncated = ""
            for sentence in sentences:
                if len(truncated + sentence + '。') <= max_length - 20:
                    truncated += sentence + '。'
                else:
                    break
            
            if truncated:
                answer = truncated + "詳細は公式サイトをご確認ください。"
            else:
                answer = answer[:max_length-20] + "...詳細は公式サイトをご確認ください。"
        
        # プラットフォーム別調整
        if platform == "line":
            # LINE用の改行調整
            answer = re.sub(r'([。！？])', r'\1\n', answer)
            answer = re.sub(r'\n+', '\n', answer)
        
        return answer.strip()
    
    def _generate_fallback_answer(
        self, 
        query: str, 
        results: List[SubsidyInfo], 
        strategy: str
    ) -> str:
        """フォールバック回答生成"""
        
        if not results:
            return f"『{query}』について、現在最新の補助金情報を確認できませんでした。住宅補助金の制度は年度ごとに変更される可能性がありますので、最新情報については管轄の行政機関にお問い合わせいただくことをお勧めいたします。"
        
        # 最も信頼性の高い結果を使用
        best_result = max(results, key=lambda x: x.reliability_score)
        
        answer = f"『{query}』について、以下の情報を確認いたしました。\n\n"
        answer += f"{best_result.content[:300]}...\n\n"
        
        if best_result.last_updated:
            answer += f"※この情報は{best_result.last_updated}時点のものです。"
        
        answer += "最新の詳細については、必ず公式サイトで確認いただくか、管轄の行政機関にお問い合わせください。"
        
        return answer
    
    def _get_latest_update_date(self, results: List[SubsidyInfo]) -> Optional[str]:
        """最新の更新日を取得"""
        
        valid_dates = [r.last_updated for r in results if r.last_updated]
        
        if not valid_dates:
            return None
        
        # 最新の日付を選択（簡易比較）
        latest_date = None
        for date_str in valid_dates:
            if latest_date is None or str(self.current_year) in date_str:
                latest_date = date_str
        
        return latest_date
    
    def _format_sources_for_platform(
        self, 
        results: List[SubsidyInfo], 
        platform: str
    ) -> List[SubsidyInfo]:
        """プラットフォーム別ソース情報整形"""
        
        # プラットフォームに応じてソース数を調整
        max_sources = 2 if platform == "line" else 5
        
        # 上位の信頼できるソースのみ返却
        top_sources = sorted(
            results, 
            key=lambda x: (x.reliability_score, x.is_current), 
            reverse=True
        )[:max_sources]
        
        return top_sources
    
    def _create_error_response(self, query: str, error_msg: str) -> AntiHallucinationResult:
        """エラーレスポンス作成"""
        
        return AntiHallucinationResult(
            answer=f"申し訳ございません。『{query}』についての検索中にエラーが発生しました。しばらく時間を置いてから再度お試しいただくか、直接行政機関にお問い合わせください。",
            sources=[],
            confidence_level=0.0,
            verification_method="error",
            last_updated=None,
            warnings=[f"検索エラー: {error_msg}"],
            search_strategy_used="error_handling"
        )

# 便利な統合関数
async def process_housing_subsidy_query(
    query: str,
    user_location: str = "関西",
    platform: str = "web"
) -> AntiHallucinationResult:
    """住宅補助金クエリの統合処理"""
    
    anti_hallucination_system = HousingSubsidyAntiHallucination()
    result = await anti_hallucination_system.process_query_with_anti_hallucination(
        query, user_location, platform
    )
    
    return result

# 使用例（テスト用）
async def test_anti_hallucination_system():
    """ハルチネーション対策システムのテスト"""
    
    test_queries = [
        ("住宅ローン控除 2025年度", "web"),
        ("ZEH補助金 兵庫県", "line"),
        ("こどもエコすまい支援事業", "web"),
        ("省エネ住宅ポイント", "line"),
        ("加東市 住宅補助金", "web")
    ]
    
    for query, platform in test_queries:
        print(f"\n{'='*60}")
        print(f"テスト: {query} (プラットフォーム: {platform})")
        print('='*60)
        
        try:
            result = await process_housing_subsidy_query(query, "関西", platform)
            
            print(f"回答: {result.answer}")
            print(f"\n信頼性レベル: {result.confidence_level:.2f}")
            print(f"検証方法: {result.verification_method}")
            print(f"最終更新日: {result.last_updated}")
            
            if result.warnings:
                print(f"警告: {', '.join(result.warnings)}")
            
            if result.sources:
                print(f"\nソース ({len(result.sources)}件):")
                for i, source in enumerate(result.sources, 1):
                    print(f"  {i}. {source.title}")
                    print(f"     URL: {source.url}")
                    print(f"     更新日: {source.last_updated}")
                    print(f"     信頼性: {source.reliability_score:.2f}")
        
        except Exception as e:
            print(f"エラー: {e}")
    
if __name__ == "__main__":
    import asyncio
    asyncio.run(test_anti_hallucination_system())