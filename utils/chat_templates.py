# utils/chat_templates.py - 統合テンプレートシステム（指定文面統一版）

import os
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import yaml

logger = logging.getLogger(__name__)

class ChatTemplateManager:
    """チャット用統合テンプレート管理システム（指定文面統一版）"""
    
    def __init__(self, template_dir: str = "templates/chat"):
        self.template_dir = template_dir
        self.templates = {}
        self.metadata = {}
        self.keyword_mappings = {}
        self.dynamic_variables = {}
        self.template_stats = {
            "web_matches": 0,
            "line_matches": 0,
            "total_requests": 0,
            "template_hits": {},
            "fallback_uses": 0
        }
        
        # 設定
        self.enable_dynamic_content = False  # 指定文面統一のため無効化
        self.enable_personalization = False  # 指定文面統一のため無効化
        self.fallback_language = "ja"
        
        # テンプレート読み込み（指定文面のみ）
        self._load_unified_templates()
        self._setup_unified_keyword_mappings()
        self._setup_dynamic_variables()

    def _load_unified_templates(self) -> None:
        """指定文面統一テンプレートの読み込み"""
        try:
            # 指定文面のみを使用
            self._load_specified_templates()
            logger.info(f"✅ Unified templates loaded: {len(self.templates)} templates")
            
        except Exception as e:
            logger.error(f"Template loading error: {e}")
            self._load_specified_templates()

    def _load_specified_templates(self) -> None:
        """指定文面のみのテンプレート読み込み"""
        
        # Web用テンプレート（基本的なもののみ保持）
        self.templates["web"] = {
            # Web用は指定されていないため、最小限のフォールバックのみ
            "fallback": {
                "content": """お尋ねの内容について詳しくご案内いたします。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

具体的にお聞かせいただければ、詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。""",
                "tags": ["fallback"],
                "priority": 1,
                "enabled": True
            }
        }
        
        # LINE用テンプレート（指定文面のみ）
        self.templates["line"] = {
            "AI相談": {
                "content": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie】""",
                "tags": ["AI相談", "案内"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },
            
            "AI住まいサイト": {
                "content": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",
                "tags": ["AI住まいサイト", "サイト", "案内"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            "資料請求": {
                "content": """📋ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie】""",
                "tags": ["資料請求", "資料", "案内"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            "展示場来場予約": {
                "content": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

【https://preview.studio.site/live/EjOQljz1WJ/reservation】

スタッフ一同、心よりお待ちしております！""",
                "tags": ["展示場来場予約", "展示場", "見学", "予約"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            "資金計画": {
                "content": """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",
                "tags": ["資金計画", "資金診断", "ローン"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            "チャット相談": {
                "content": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",
                "tags": ["チャット相談", "相談", "サポート"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            # 友だち追加時の挨拶（followイベント用）
            "follow_greeting": {
                "content": """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie】""",
                "tags": ["follow", "挨拶", "友だち追加"],
                "priority": 10,
                "enabled": True,
                "unified_message": True
            },

            # 最小限のフォールバック
            "fallback": {
                "content": """ご質問ありがとうございます😊

目的のボタンをタップしてください👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

具体的なご質問もお気軽にどうぞ✨""",
                "tags": ["fallback"],
                "priority": 1,
                "enabled": True,
                "unified_message": True
            }
        }

    def _setup_unified_keyword_mappings(self) -> None:
        """指定文面統一キーワードマッピングの設定"""
        self.keyword_mappings = {
            # 指定された6つの機能のみ
            "AI相談": ["🤖AI相談", "AI相談", "🤖 AI相談", "ai相談"],
            "AI住まいサイト": ["🌐AI住まいサイト", "AI住まいサイト", "🌐 AI住まいサイト", "サイト", "住まいサイト"],
            "資料請求": ["📋資料請求", "資料請求", "📋 資料請求", "資料"],
            "展示場来場予約": ["📍展示場来場予約", "展示場来場予約", "📍 展示場来場予約", "展示場", "来場予約", "見学"],
            "資金計画": ["💰資金計画", "資金計画", "💰 資金計画", "資金診断"],
            "チャット相談": ["💬チャット相談", "チャット相談", "💬 チャット相談", "相談"],
            
            # followイベント用
            "follow_greeting": ["follow", "友だち追加", "挨拶"]
        }

    def _setup_dynamic_variables(self) -> None:
        """動的変数の設定（最小限）"""
        self.dynamic_variables = {
            "current_date": datetime.now().strftime("%Y年%m月%d日"),
            "current_year": datetime.now().year,
            "current_month": datetime.now().month,
        }

    def find_template(self, query: str, platform: str = "line", 
                     user_context: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """指定文面統一テンプレート検索"""
        self.template_stats["total_requests"] += 1
        
        query_lower = query.lower().strip()
        platform_templates = self.templates.get(platform, {})
        
        if not platform_templates:
            logger.warning(f"No templates found for platform: {platform}")
            return None

        # 🚀 1. 完全一致チェック（指定文面）
        exact_match = self._find_exact_unified_match(query_lower, platform_templates)
        if exact_match:
            return exact_match
        
        # 🚀 2. キーワードマッチング（指定文面のみ）
        keyword_match = self._find_unified_keyword_match(query_lower, platform_templates)
        if keyword_match:
            return keyword_match
        
        # 🚀 3. フォールバック（最小限）
        return self._get_unified_fallback_template(platform, user_context)

    def _find_exact_unified_match(self, query: str, templates: Dict) -> Optional[Dict[str, Any]]:
        """指定文面完全一致検索"""
        # 指定された完全一致パターン
        exact_patterns = [
            ("🤖AI相談", "AI相談"),
            ("🤖 AI相談", "AI相談"),
            ("🌐AI住まいサイト", "AI住まいサイト"),
            ("🌐 AI住まいサイト", "AI住まいサイト"),
            ("📋資料請求", "資料請求"),
            ("📋 資料請求", "資料請求"),
            ("📍展示場来場予約", "展示場来場予約"),
            ("📍 展示場来場予約", "展示場来場予約"),
            ("💰資金計画", "資金計画"),
            ("💰 資金計画", "資金計画"),
            ("💬チャット相談", "チャット相談"),
            ("💬 チャット相談", "チャット相談")
        ]
        
        for pattern, template_key in exact_patterns:
            if pattern in query and template_key in templates and templates[template_key].get("enabled", False):
                return self._prepare_unified_template_result(template_key, templates[template_key], "exact_match")
        
        return None

    def _find_unified_keyword_match(self, query: str, templates: Dict) -> Optional[Dict[str, Any]]:
        """指定文面キーワードマッチング"""
        best_match = None
        max_score = 0
        
        for template_key, keywords in self.keyword_mappings.items():
            if (template_key not in templates or 
                not templates[template_key].get("enabled", False) or 
                not templates[template_key].get("unified_message", False)):
                continue
            
            # キーワードマッチングスコア計算
            score = 0
            matched_keywords = []
            
            for keyword in keywords:
                if keyword.lower() in query:
                    score += len(keyword) * 2  # 指定文面は高スコア
                    matched_keywords.append(keyword)
            
            if score > max_score:
                max_score = score
                best_match = {
                    "template_key": template_key,
                    "template": templates[template_key],
                    "score": score,
                    "matched_keywords": matched_keywords,
                    "match_type": "keyword_match"
                }
        
        if best_match and max_score > 0:
            return self._prepare_unified_template_result(
                best_match["template_key"], 
                best_match["template"], 
                "keyword_match",
                {"score": max_score, "matched_keywords": best_match["matched_keywords"]}
            )
        
        return None

    def _get_unified_fallback_template(self, platform: str, user_context: Optional[Dict]) -> Dict[str, Any]:
        """指定文面統一フォールバックテンプレート"""
        self.template_stats["fallback_uses"] += 1
        
        platform_templates = self.templates.get(platform, {})
        fallback_template = platform_templates.get("fallback")
        
        if fallback_template and fallback_template.get("enabled", False):
            return self._prepare_unified_template_result("fallback", fallback_template, "fallback")
        
        # 緊急時のハードコードフォールバック
        if platform == "line":
            fallback_content = """目的のボタンをタップしてください😊

🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット"""
        else:
            fallback_content = "お尋ねの内容について、詳しくはお問い合わせください。"
        
        return {
            "content": fallback_content,
            "template_key": "emergency_fallback",
            "match_type": "emergency_fallback",
            "platform": platform,
            "metadata": {
                "is_fallback": True,
                "generated_at": datetime.now().isoformat(),
                "unified_message": True
            }
        }

    def _prepare_unified_template_result(self, template_key: str, template_data: Dict, 
                               match_type: str, extra_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """指定文面統一テンプレート結果の準備"""
        # 統計更新
        platform = "line"  # 主にLINE用
        self.template_stats[f"{platform}_matches"] += 1
        
        if template_key not in self.template_stats["template_hits"]:
            self.template_stats["template_hits"][template_key] = 0
        self.template_stats["template_hits"][template_key] += 1
        
        # 指定文面をそのまま使用（動的処理なし）
        content = template_data["content"]
        
        result = {
            "content": content,
            "template_key": template_key,
            "match_type": match_type,
            "metadata": {
                "tags": template_data.get("tags", []),
                "priority": template_data.get("priority", 5),
                "generated_at": datetime.now().isoformat(),
                "unified_message": template_data.get("unified_message", False),
                **(extra_metadata or {})
            }
        }
        
        logger.info(f"🎯 Unified template matched: {template_key} ({match_type})")
        
        return result

    def get_template_stats(self) -> Dict[str, Any]:
        """テンプレート統計取得"""
        total_requests = self.template_stats["total_requests"]
        total_matches = self.template_stats["line_matches"]  # 主にLINE
        
        return {
            "performance": {
                "total_requests": total_requests,
                "total_matches": total_matches,
                "match_rate": (total_matches / total_requests * 100) if total_requests > 0 else 0,
                "fallback_rate": (self.template_stats["fallback_uses"] / total_requests * 100) if total_requests > 0 else 0
            },
            "platform_distribution": {
                "line_matches": self.template_stats["line_matches"],
                "web_matches": self.template_stats.get("web_matches", 0)
            },
            "template_popularity": dict(sorted(
                self.template_stats["template_hits"].items(),
                key=lambda x: x[1],
                reverse=True
            )),
            "template_counts": {
                "line_templates": len([t for t in self.templates.get("line", {}).values() if t.get("enabled", False)]),
                "web_templates": len([t for t in self.templates.get("web", {}).values() if t.get("enabled", False)]),
                "unified_templates": len([t for platform in self.templates.values() for t in platform.values() if t.get("unified_message", False)]),
                "total_enabled": len([t for platform in self.templates.values() for t in platform.values() if t.get("enabled", False)])
            },
            "configuration": {
                "unified_message_mode": True,
                "dynamic_content_enabled": self.enable_dynamic_content,
                "personalization_enabled": self.enable_personalization,
                "fallback_language": self.fallback_language
            }
        }

    def get_follow_greeting(self) -> str:
        """友だち追加時の挨拶取得"""
        follow_template = self.templates.get("line", {}).get("follow_greeting")
        if follow_template and follow_template.get("enabled", False):
            return follow_template["content"]
        
        # フォールバック
        return """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。"""

    # 既存メソッドの無効化（指定文面統一のため）
    def add_custom_template(self, platform: str, template_key: str, 
                          content: str, tags: List[str] = None, 
                          priority: int = 5) -> bool:
        """カスタムテンプレート追加（無効化）"""
        logger.warning("Custom template addition is disabled in unified message mode")
        return False

    def remove_template(self, platform: str, template_key: str) -> bool:
        """テンプレート削除（無効化）"""
        logger.warning("Template removal is disabled in unified message mode")
        return False

    def export_templates(self, file_path: str) -> bool:
        """テンプレートのエクスポート（読み取り専用）"""
        try:
            export_data = {
                "unified_message_templates": self.templates,
                "keyword_mappings": self.keyword_mappings,
                "metadata": {
                    "exported_at": datetime.now().isoformat(),
                    "version": "2.0_unified",
                    "mode": "specified_messages_only",
                    "total_templates": sum(len([t for t in templates.values() if t.get("enabled", False)]) 
                                         for templates in self.templates.values())
                }
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(export_data, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"📤 Unified templates exported to: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Template export error: {e}")
            return False

# グローバルテンプレートマネージャー（指定文面統一版）
_global_template_manager = None

def get_template_manager() -> ChatTemplateManager:
    """グローバルテンプレートマネージャー取得（指定文面統一版）"""
    global _global_template_manager
    
    if _global_template_manager is None:
        template_dir = os.getenv("TEMPLATE_DIR", "templates/chat")
        _global_template_manager = ChatTemplateManager(template_dir)
        logger.info("✅ Unified template manager initialized")
    
    return _global_template_manager

def reset_template_manager() -> ChatTemplateManager:
    """テンプレートマネージャーリセット"""
    global _global_template_manager
    _global_template_manager = None
    return get_template_manager()

def get_unified_richmenu_response(button_text: str) -> Optional[str]:
    """統一リッチメニュー応答取得"""
    manager = get_template_manager()
    result = manager.find_template(button_text, "line")
    
    if result and result.get("metadata", {}).get("unified_message", False):
        return result["content"]
    
    return None

def get_follow_greeting() -> str:
    """友だち追加挨拶取得"""
    manager = get_template_manager()
    return manager.get_follow_greeting()