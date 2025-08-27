# utils/fallback.py - RAGフォールバックハンドラー（リッチメニュー対応修正版）
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class RAGFallbackHandler:
    """RAGフォールバックハンドラー（リッチメニュー対応版）"""
    
    def __init__(self):
        self.fallback_strategies = [
            self._try_web_search,
            self._try_general_llm,
            self._return_default_response
        ]
        
        # 🔧 リッチメニュー関連設定
        self.richmenu_buttons = [
            "🤖 AI相談", "🌐 AI住まいサイト", "📄 資料請求",
            "📍 展示場来場　予約", "💰 資金計画", "💬 チャット相談"
        ]
        self.disable_fallback_for_richmenu = True  # リッチメニュー押下時はフォールバック無効
        self.use_fixed_template_on_richmenu_error = True  # リッチメニューエラー時は固定テンプレート
        
        # 統計情報
        self.stats = {
            "total_fallback_attempts": 0,
            "web_search_attempts": 0,
            "general_llm_attempts": 0,
            "default_response_uses": 0,
            "richmenu_fallback_skips": 0,       # 🔧 リッチメニューフォールバックスキップ数
            "richmenu_fixed_template_uses": 0,  # 🔧 リッチメニュー固定テンプレート使用数
            "success_by_strategy": {
                "web_search": 0,
                "general_llm": 0,
                "default": 0,
                "richmenu_fixed": 0  # 🔧 リッチメニュー固定テンプレート成功数
            }
        }
    
    def _is_richmenu_request(self, query: str, user_context: Optional[Dict] = None) -> bool:
        """🔧 リッチメニューボタン押下かどうかを判定"""
        if not query:
            return False
        
        query_stripped = query.strip()
        
        # リッチメニューボタンとの完全一致チェック
        for button in self.richmenu_buttons:
            if query_stripped == button:
                return True
        
        # 部分一致チェック（絵文字なしでも判定）
        for button in self.richmenu_buttons:
            button_text = button.replace("🤖 ", "").replace("🌐 ", "").replace("📄 ", "").replace("📍 ", "").replace("💰 ", "").replace("💬 ", "")
            if query_stripped == button_text:
                return True
        
        # ユーザーコンテキストからの判定
        if user_context:
            if (user_context.get("source") == "richmenu" or 
                user_context.get("richmenu_button") or
                user_context.get("platform") == "line" and user_context.get("is_button_press")):
                return True
        
        return False

    async def handle_failure(self, query: str, error: Exception, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """エラー時のフォールバック処理（リッチメニュー対応版）"""
        logger.error(f"RAG処理エラー: {error}")
        self.stats["total_fallback_attempts"] += 1
        
        # 🔧 リッチメニューボタン押下時はフォールバック処理をスキップ
        if self._is_richmenu_request(query, user_context):
            if self.disable_fallback_for_richmenu:
                self.stats["richmenu_fallback_skips"] += 1
                logger.info(f"🎯 Skipping fallback for richmenu button: {query}")
                return await self._handle_richmenu_error(query, error, user_context)
        
        # 🔧 通常の質問に対する従来のフォールバック処理
        logger.info(f"💡 Starting fallback strategies for question: {query[:50]}...")
        
        for strategy in self.fallback_strategies:
            try:
                result = await strategy(query, user_context)
                if result:
                    strategy_name = strategy.__name__.replace("_try_", "").replace("_return_", "")
                    logger.info(f"✅ Fallback successful: {strategy_name}")
                    self.stats["success_by_strategy"][strategy_name] = self.stats["success_by_strategy"].get(strategy_name, 0) + 1
                    return result
            except Exception as e:
                strategy_name = strategy.__name__
                logger.error(f"❌ Fallback strategy failed {strategy_name}: {e}")
                continue
        
        # 全フォールバック戦略失敗時
        logger.warning("⚠️ All fallback strategies failed")
        return self._return_error_response(query, user_context)
    
    async def _handle_richmenu_error(self, query: str, error: Exception, 
                                   user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """🔧 リッチメニューエラー時の固定テンプレート応答"""
        self.stats["richmenu_fixed_template_uses"] += 1
        self.stats["success_by_strategy"]["richmenu_fixed"] += 1
        
        logger.info(f"🎯 Using fixed template for richmenu error: {query}")
        
        # プラットフォーム判定
        platform = "line"
        if user_context and user_context.get("platform"):
            platform = user_context["platform"]
        
        # ボタン別固定エラーテンプレート
        richmenu_error_templates = {
            "🤖 AI相談": {
                "line": "🤖 AI相談サービスに一時的な問題が発生しています。\nしばらく後に再度お試しください。\n\n💬 お急ぎの場合はスタッフまでご連絡ください。",
                "web": "AI相談サービスに一時的な問題が発生しています。しばらく時間をおいてから再度お試しください。"
            },
            "🌐 AI住まいサイト": {
                "line": "🌐 サイト情報の取得に問題が発生しています。\n\n直接サイトへアクセス:\nhttps://preview.studio.site/live/EjOQljz1WJ/",
                "web": "サイト情報の取得に問題が発生しています。直接サイトへアクセスしてください: https://preview.studio.site/live/EjOQljz1WJ/"
            },
            "📄 資料請求": {
                "line": "📄 資料請求システムに問題が発生しています。\nお手数ですが、お電話またはメールでご連絡ください。\n\n📞 営業時間: 9:00-18:00",
                "web": "資料請求システムに問題が発生しています。お電話またはメールでお問い合わせください。"
            },
            "📍 展示場来場　予約": {
                "line": "📍 予約システムに問題が発生しています。\n\n直接予約サイト:\nhttps://preview.studio.site/live/EjOQljz1WJ/reservation\n\nまたはお電話: 9:00-18:00",
                "web": "予約システムに問題が発生しています。直接予約サイト（https://preview.studio.site/live/EjOQljz1WJ/reservation）またはお電話でご連絡ください。"
            },
            "💰 資金計画": {
                "line": "💰 資金診断システムに問題が発生しています。\nスタッフが個別にご相談を承りますので、お気軽にお声かけください。\n\n💬 このLINEでもご相談いただけます。",
                "web": "資金診断システムに問題が発生しています。スタッフが個別にご相談を承りますので、お気軽にお問い合わせください。"
            },
            "💬 チャット相談": {
                "line": "💬 チャットシステムに問題が発生しています。\n\n📞 お電話でのご相談: 9:00-18:00\n📧 メールでのお問い合わせも承ります。",
                "web": "チャットシステムに問題が発生しています。お電話またはメールでご相談ください。営業時間: 9:00-18:00"
            }
        }
        
        # クエリに対応するテンプレートを取得
        for button, templates in richmenu_error_templates.items():
            if query.strip() == button or button.replace("🤖 ", "").replace("🌐 ", "").replace("📄 ", "").replace("📍 ", "").replace("💰 ", "").replace("💬 ", "") in query:
                error_message = templates.get(platform, templates.get("line", "システムエラーが発生しました。"))
                
                return {
                    "answer": error_message,
                    "fallback": "richmenu_fixed_template",
                    "richmenu_button": button,
                    "error_handled": True,
                    "original_error": str(error),
                    "platform": platform,
                    "processing_time": 0.05  # 高速応答
                }
        
        # デフォルトのリッチメニューエラーテンプレート
        default_message = "システムに一時的な問題が発生しています。しばらく後に再度お試しください。" if platform == "web" else "システムに問題が発生しています😔\nしばらく後に再度お試しください。\n\n💬 お急ぎの場合はスタッフまでご連絡を！"
        
        return {
            "answer": default_message,
            "fallback": "richmenu_default_error",
            "error_handled": True,
            "original_error": str(error),
            "platform": platform,
            "processing_time": 0.05
        }
    
    async def _try_web_search(self, query: str, user_context: Optional[Dict] = None) -> Optional[Dict]:
        """Web検索による回答生成（質問応答時のみ）"""
        # 🔧 リッチメニュー押下時は実行しない
        if self._is_richmenu_request(query, user_context):
            logger.debug("🚫 Skipping web search for richmenu request")
            return None
        
        self.stats["web_search_attempts"] += 1
        
        try:
            from utils.web_search import GoogleSearcher
            searcher = GoogleSearcher()
            
            if searcher.should_search_web(query):
                logger.info(f"🔍 Attempting web search fallback for: {query[:50]}...")
                answer = searcher.get_enhanced_answer(query, use_web_search=True)
                
                if answer and len(answer.strip()) > 20:  # 意味のある応答がある場合
                    return {
                        "answer": answer, 
                        "fallback": "web_search",
                        "search_performed": True,
                        "processing_time": 2.0
                    }
            else:
                logger.debug("Web search not appropriate for this query")
                
        except ImportError:
            logger.warning("Web search module not available for fallback")
        except Exception as e:
            logger.error(f"Web search fallback failed: {e}")
            
        return None
    
    async def _try_general_llm(self, query: str, user_context: Optional[Dict] = None) -> Optional[Dict]:
        """一般的なLLM回答（質問応答時のみ）"""
        # 🔧 リッチメニュー押下時は実行しない
        if self._is_richmenu_request(query, user_context):
            logger.debug("🚫 Skipping general LLM for richmenu request")
            return None
        
        self.stats["general_llm_attempts"] += 1
        
        try:
            from llm.llm_runner import load_llm
            llm, _, _ = load_llm()
            
            logger.info(f"🤖 Attempting general LLM fallback for: {query[:50]}...")
            
            # プラットフォーム別プロンプト調整
            platform = user_context.get("platform", "web") if user_context else "web"
            
            if platform == "line":
                prompt = f"""質問に対して、住まい・建築の一般的な知識に基づいて親しみやすく回答してください。
文字数は300文字以内で、絵文字も適度に使用してください。
不明な点がある場合は、推測ではなく「詳細は確認が必要です」と答えてください。

質問: {query}

回答:"""
            else:
                prompt = f"""質問に対して、住まい・建築の一般的な知識に基づいて丁寧に回答してください。
不明な点がある場合は、推測ではなく「詳細は確認が必要です」と答えてください。

質問: {query}

回答:"""
            
            response = llm.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            
            if answer and len(answer.strip()) > 15:  # 意味のある応答がある場合
                return {
                    "answer": answer.strip(), 
                    "fallback": "general_llm",
                    "llm_used": True,
                    "processing_time": 1.5
                }
            
        except ImportError:
            logger.warning("LLM module not available for fallback")
        except Exception as e:
            logger.error(f"General LLM fallback failed: {e}")
            
        return None
    
    def _return_default_response(self, query: str, user_context: Optional[Dict] = None) -> Dict:
        """デフォルト応答（質問応答時のみ）"""
        # 🔧 リッチメニュー押下時は実行しない（別途処理済み）
        if self._is_richmenu_request(query, user_context):
            logger.debug("🚫 Skipping default response for richmenu request (handled separately)")
            return None
        
        self.stats["default_response_uses"] += 1
        platform = user_context.get("platform", "web") if user_context else "web"
        
        if platform == "line":
            default_answer = """申し訳ございません😔
一時的にシステムに問題が発生しています。

💬 スタッフがお答えしますので、お気軽にご質問ください！
📞 お電話でのご相談も承ります（9:00-18:00）"""
        else:
            default_answer = """申し訳ございません。一時的にシステムに問題が発生しています。

お急ぎの場合は、お電話でお問い合わせください。
営業時間: 9:00-18:00

住まいづくりに関するご質問は、スタッフが丁寧にお答えいたします。"""
        
        return {
            "answer": default_answer,
            "fallback": "default",
            "system_default": True,
            "processing_time": 0.1
        }
    
    def _return_error_response(self, query: str, user_context: Optional[Dict] = None) -> Dict:
        """エラー応答（全フォールバック失敗時）"""
        platform = user_context.get("platform", "web") if user_context else "web"
        
        if platform == "line":
            error_answer = """システムエラーが発生しました😔

復旧作業中です。しばらくお待ちください。
💬 お急ぎの場合はスタッフまでご連絡を！"""
        else:
            error_answer = """システムエラーが発生しました。復旧作業中のため、しばらくお待ちください。

お急ぎの場合は、お電話でお問い合わせください。
ご不便をおかけして申し訳ございません。"""
        
        return {
            "answer": error_answer,
            "error": True,
            "all_fallbacks_failed": True,
            "processing_time": 0.1
        }
    
    def get_fallback_stats(self) -> Dict[str, Any]:
        """🔧 フォールバック統計取得（リッチメニュー対応）"""
        total_attempts = self.stats["total_fallback_attempts"]
        
        return {
            "total_fallback_attempts": total_attempts,
            "strategy_attempts": {
                "web_search": self.stats["web_search_attempts"],
                "general_llm": self.stats["general_llm_attempts"], 
                "default_response": self.stats["default_response_uses"]
            },
            "success_by_strategy": self.stats["success_by_strategy"],
            "richmenu_handling": {  # 🔧 リッチメニュー関連統計
                "fallback_skips": self.stats["richmenu_fallback_skips"],
                "fixed_template_uses": self.stats["richmenu_fixed_template_uses"],
                "skip_rate": (self.stats["richmenu_fallback_skips"] / max(1, total_attempts) * 100)
            },
            "configuration": {
                "disable_fallback_for_richmenu": self.disable_fallback_for_richmenu,
                "use_fixed_template_on_richmenu_error": self.use_fixed_template_on_richmenu_error,
                "supported_richmenu_buttons": len(self.richmenu_buttons)
            },
            "effectiveness": {
                "overall_success_rate": (sum(self.stats["success_by_strategy"].values()) / max(1, total_attempts) * 100),
                "web_search_success_rate": (self.stats["success_by_strategy"]["web_search"] / max(1, self.stats["web_search_attempts"]) * 100),
                "general_llm_success_rate": (self.stats["success_by_strategy"]["general_llm"] / max(1, self.stats["general_llm_attempts"]) * 100),
                "richmenu_fixed_success_rate": 100.0  # 固定テンプレートは常に成功
            }
        }
    
    def reset_stats(self):
        """統計リセット"""
        self.stats = {
            "total_fallback_attempts": 0,
            "web_search_attempts": 0,
            "general_llm_attempts": 0,
            "default_response_uses": 0,
            "richmenu_fallback_skips": 0,
            "richmenu_fixed_template_uses": 0,
            "success_by_strategy": {
                "web_search": 0,
                "general_llm": 0,
                "default": 0,
                "richmenu_fixed": 0
            }
        }
        logger.info("🔄 Fallback statistics reset")

# 🔧 便利関数（リッチメニュー対応）
async def handle_rag_failure(query: str, error: Exception, user_context: Optional[Dict] = None) -> Dict[str, Any]:
    """RAG失敗時のフォールバック処理（リッチメニュー対応版）"""
    handler = RAGFallbackHandler()
    return await handler.handle_failure(query, error, user_context)

def is_richmenu_request(query: str, user_context: Optional[Dict] = None) -> bool:
    """リッチメニューリクエスト判定（外部利用用）"""
    handler = RAGFallbackHandler()
    return handler._is_richmenu_request(query, user_context)

def get_fallback_statistics() -> Dict[str, Any]:
    """フォールバック統計取得（外部利用用）"""
    handler = RAGFallbackHandler()
    return handler.get_fallback_stats()

# グローバルハンドラーインスタンス（シングルトン風）
_global_fallback_handler = None

def get_global_fallback_handler() -> RAGFallbackHandler:
    """グローバルフォールバックハンドラー取得"""
    global _global_fallback_handler
    
    if _global_fallback_handler is None:
        _global_fallback_handler = RAGFallbackHandler()
    
    return _global_fallback_handler

# 🔧 テスト・デバッグ用
async def test_richmenu_fallback_behavior():
    """リッチメニューフォールバック動作テスト"""
    handler = RAGFallbackHandler()
    
    print("🧪 リッチメニューフォールバック動作テスト")
    print("=" * 50)
    
    # テストケース
    test_cases = [
        # リッチメニューボタン（フォールバックスキップ対象）
        ("🤖 AI相談", {"platform": "line"}, "richmenu_fixed_template"),
        ("💰 資金計画", {"platform": "line"}, "richmenu_fixed_template"), 
        ("📄 資料請求", {"platform": "web"}, "richmenu_fixed_template"),
        
        # 通常の質問（フォールバック実行対象）
        ("坪単価について教えて", {"platform": "line"}, "web_search_or_llm"),
        ("断熱性能はどのくらい？", {"platform": "web"}, "web_search_or_llm"),
        ("住宅ローンの金利は？", {"platform": "line"}, "web_search_or_llm")
    ]
    
    for query, context, expected_type in test_cases:
        print(f"\n🔍 テスト: {query}")
        print(f"   Context: {context}")
        
        is_richmenu = handler._is_richmenu_request(query, context)
        print(f"   リッチメニュー判定: {is_richmenu}")
        
        try:
            # 模擬エラーでフォールバック処理をテスト
            mock_error = Exception(f"Mock RAG error for: {query}")
            result = await handler.handle_failure(query, mock_error, context)
            
            fallback_type = result.get("fallback", "unknown")
            print(f"   フォールバック結果: {fallback_type}")
            print(f"   期待タイプ: {expected_type}")
            
            if is_richmenu:
                success = fallback_type.startswith("richmenu")
                print(f"   ✅ SUCCESS" if success else f"   ❌ FAILED")
            else:
                success = fallback_type in ["web_search", "general_llm", "default"]
                print(f"   ✅ SUCCESS" if success else f"   ❌ FAILED")
                
        except Exception as e:
            print(f"   💥 テストエラー: {e}")
    
    # 統計表示
    stats = handler.get_fallback_stats()
    print(f"\n📊 統計情報:")
    print(f"   総フォールバック試行: {stats['total_fallback_attempts']}")
    print(f"   リッチメニュースキップ: {stats['richmenu_handling']['fallback_skips']}")
    print(f"   リッチメニュー固定テンプレート: {stats['richmenu_handling']['fixed_template_uses']}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_richmenu_fallback_behavior())