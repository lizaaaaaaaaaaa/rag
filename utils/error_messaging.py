"""
ユーザーフレンドリーエラーメッセージ管理モジュール
技術的エラーを分かりやすい言葉に変換し、次のアクション提案を含む
"""

import logging
import random
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

class ErrorLevel(Enum):
    """エラーレベル定義"""
    INFO = "info"
    WARNING = "warning" 
    ERROR = "error"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    """エラーカテゴリ定義"""
    NETWORK = "network"
    SYSTEM = "system"
    RAG = "rag"
    LLM = "llm"
    USER_INPUT = "user_input"
    TIMEOUT = "timeout"
    AUTHENTICATION = "auth"
    RESOURCE = "resource"

class ErrorMessaging:
    """ユーザーフレンドリーエラーメッセージ管理クラス"""
    
    def __init__(self):
        self.logger = logger
        
        # プラットフォーム別メッセージテンプレート
        self._platform_messages = {
            "line": {
                "max_length": 300,  # LINE文字制限
                "emoji_style": True,
                "casual_tone": True
            },
            "web": {
                "max_length": 500,
                "emoji_style": False,
                "casual_tone": False
            }
        }
        
        # エラーカテゴリ別メッセージマッピング
        self._error_messages = {
            ErrorCategory.NETWORK: {
                ErrorLevel.WARNING: {
                    "line": [
                        "📶 通信状況が不安定です。少し待ってからもう一度お試しください。",
                        "🌐 ネットワークの調子が良くないようです。しばらく時間をおいてからお試しください。",
                        "📡 接続が不安定になっています。少し待ってからもう一度お話しかけてください。"
                    ],
                    "web": [
                        "ネットワーク接続が不安定です。しばらく時間をおいてから再度お試しください。",
                        "通信エラーが発生しました。インターネット接続をご確認の上、再度お試しください。",
                        "接続に問題が発生しています。少し待ってからもう一度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "❌ 接続エラーが発生しました。お手数ですが、少し時間をおいてからもう一度お試しください。",
                        "⚠️ 通信に失敗しました。しばらく待ってから再度お話しかけてください。"
                    ],
                    "web": [
                        "ネットワークエラーが発生しました。接続状況をご確認の上、しばらく時間をおいてから再度お試しください。",
                        "通信エラーにより処理できませんでした。インターネット接続を確認して再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.SYSTEM: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚙️ システムが少し調子悪いようです。少し待ってからもう一度お試しください。",
                        "🔧 一時的な不具合が発生しています。しばらくお待ちください。",
                        "📱 システムメンテナンス中の可能性があります。少し時間をおいてお試しください。"
                    ],
                    "web": [
                        "システムに一時的な問題が発生しています。しばらく時間をおいてから再度お試しください。",
                        "サーバーが混雑している可能性があります。少し待ってから再度アクセスしてください。",
                        "システムメンテナンスにより一部機能が制限されている場合があります。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "❌ システムエラーが発生しました。復旧まで少しお時間をください。📞お急ぎの場合は直接お電話ください。",
                        "⚠️ システム障害が発生中です。お手数ですが、しばらく時間をおいてからお試しください。"
                    ],
                    "web": [
                        "システムエラーが発生しました。技術チームが対応中です。しばらく時間をおいてから再度お試しください。お急ぎの場合はお電話でお問い合わせください。",
                        "予期しないシステム障害が発生しています。復旧作業中のため、しばらくお待ちください。"
                    ]
                }
            },
            
            ErrorCategory.RAG: {
                ErrorLevel.WARNING: {
                    "line": [
                        "📚 データの読み込み中です。少しお待ちください。",
                        "🔍 情報を準備しています。もう少々お待ちください。",
                        "📖 資料を確認中です。少し時間をおいてからお試しください。"
                    ],
                    "web": [
                        "データベースの準備中です。少々お待ちください。",
                        "情報の読み込み中です。しばらくお待ちいただいてから再度お試しください。",
                        "システムが情報を整理中です。少し時間をおいてからお試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "📚 申し訳ございません。情報の取得に失敗しました。基本的な住まいづくりのご質問でしたら別の方法でお答えできます。",
                        "🔍 詳細情報の取得ができませんでした。一般的なご質問でしたらお答えできますので、お気軽にお聞きください。"
                    ],
                    "web": [
                        "申し訳ございません。データベースから情報を取得できませんでした。基本的な住まいづくりに関するご質問でしたら、一般的な知識でお答えできます。具体的にお聞かせください。",
                        "情報検索システムに問題が発生しています。住まいづくりの基本的なご相談でしたら対応可能ですので、お気軽にお聞きください。"
                    ]
                }
            },
            
            ErrorCategory.LLM: {
                ErrorLevel.WARNING: {
                    "line": [
                        "🤖 AI が考え中です...少しお待ちください。",
                        "💭 回答を生成中です。少々お時間をください。",
                        "🧠 質問を理解中です。もう少しお待ちください。"
                    ],
                    "web": [
                        "AI が回答を生成中です。少々お待ちください。",
                        "質問を解析中です。しばらくお待ちください。",
                        "回答の準備をしています。もう少しお時間をください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "🤖 申し訳ございません。AI に問題が発生しました。📞お急ぎでしたら直接お電話でご相談ください。",
                        "⚠️ AI システムが停止中です。復旧までお電話でのご相談をお願いいたします。"
                    ],
                    "web": [
                        "申し訳ございません。AI システムに問題が発生しています。お急ぎの場合はお電話でご相談ください。復旧まで少しお時間をいただきます。",
                        "AI システムが利用できない状態です。お電話での相談も承っていますので、お気軽にお問い合わせください。"
                    ]
                }
            },
            
            ErrorCategory.TIMEOUT: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⏰ 処理に時間がかかっています。少し待ってからもう一度お試しください。",
                        "🕐 混雑しているようです。少し時間をおいてからお話しかけてください。"
                    ],
                    "web": [
                        "処理に時間がかかっています。サーバーが混雑している可能性があります。少し時間をおいてから再度お試しください。",
                        "レスポンスタイムが長くなっています。しばらく待ってから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⏰ タイムアウトしました。システムが混雑しています。しばらく時間をおいてからお試しください。",
                        "🕐 処理が完了できませんでした。少し待ってからもう一度お話しかけてください。"
                    ],
                    "web": [
                        "処理がタイムアウトしました。システムが混雑している可能性があります。しばらく時間をおいてから再度お試しください。",
                        "応答時間が上限を超えました。サーバー負荷が高い状態です。少し待ってから再度アクセスしてください。"
                    ]
                }
            },
            
            ErrorCategory.USER_INPUT: {
                ErrorLevel.INFO: {
                    "line": [
                        "❓ どのようなことについて知りたいでしょうか？住まいづくりのことでしたら何でもお聞きください。",
                        "🏠 住まいづくりについて、どんなことでもお気軽にご質問ください。",
                        "💡 具体的にどのようなことについてお聞きしたいでしょうか？"
                    ],
                    "web": [
                        "どのようなことについてお知りになりたいでしょうか？住まいづくりに関することでしたら、どんなことでもお気軽にお聞きください。",
                        "具体的なご質問をお聞かせください。間取り、資金計画、土地探しなど、住まいづくりのあらゆることについてお答えいたします。",
                        "住まいづくりについてお答えいたします。具体的なご質問があればお聞かせください。"
                    ]
                }
            }
        }
        
        # 次のアクション提案
        self._action_suggestions = {
            "line": {
                ErrorCategory.NETWORK: [
                    "📞 お急ぎの場合は直接お電話ください: 0120-XXX-XXX",
                    "🔄 数分後にもう一度お試しください",
                    "📧 メールでのお問い合わせも承っています"
                ],
                ErrorCategory.SYSTEM: [
                    "📞 お急ぎの場合はお電話でご相談ください",
                    "⏰ しばらく時間をおいてから再度お試しください",
                    "📧 メールでも承っています: info@example.com"
                ],
                ErrorCategory.RAG: [
                    "💬 基本的なご質問でしたらお答えできます",
                    "📞 詳しいご相談はお電話でも承っています",
                    "📋 資料請求は可能です"
                ]
            },
            "web": {
                ErrorCategory.NETWORK: [
                    "しばらく時間をおいてから再度お試しください",
                    "お急ぎの場合はお電話でご相談ください: 0120-XXX-XXX", 
                    "メールでのお問い合わせ: info@example.com"
                ],
                ErrorCategory.SYSTEM: [
                    "システム復旧までしばらくお待ちください",
                    "お急ぎの場合は直接お問い合わせください",
                    "定期メンテナンス情報は公式サイトでご確認いただけます"
                ],
                ErrorCategory.RAG: [
                    "基本的な住まいづくりのご質問でしたらお答えできます",
                    "詳細な情報は資料請求でご提供できます",
                    "具体的なご相談はお電話でも承っています"
                ]
            }
        }

    def get_user_friendly_message(
        self,
        error_type: str,
        platform: str = "line",
        error_level: ErrorLevel = ErrorLevel.ERROR,
        user_context: Optional[Dict] = None,
        include_suggestions: bool = True
    ) -> Dict[str, any]:
        """
        ユーザーフレンドリーなエラーメッセージを生成
        
        Args:
            error_type: エラータイプ（技術的なエラー名）
            platform: プラットフォーム（line, web）
            error_level: エラーレベル
            user_context: ユーザーコンテキスト情報
            include_suggestions: アクション提案を含むかどうか
            
        Returns:
            エラーメッセージ情報辞書
        """
        try:
            # エラーカテゴリを判定
            category = self._categorize_error(error_type)
            
            # メッセージを取得
            message = self._get_message_for_category(category, platform, error_level)
            
            # アクション提案を取得
            suggestions = []
            if include_suggestions:
                suggestions = self._get_action_suggestions(category, platform)
            
            # コンテキストに応じてメッセージをカスタマイズ
            if user_context:
                message = self._customize_message_with_context(message, user_context, platform)
            
            # プラットフォーム制限に合わせて調整
            message = self._adjust_for_platform(message, platform)
            
            return {
                "message": message,
                "error_level": error_level.value,
                "error_category": category.value,
                "platform": platform,
                "suggestions": suggestions,
                "timestamp": datetime.utcnow().isoformat(),
                "user_friendly": True
            }
            
        except Exception as e:
            # エラーメッセージ生成でエラーが発生した場合のフォールバック
            self.logger.error(f"Error in generating user-friendly message: {str(e)}")
            return self._get_fallback_message(platform, error_level)

    def _categorize_error(self, error_type: str) -> ErrorCategory:
        """エラータイプからカテゴリを判定"""
        error_lower = error_type.lower()
        
        # ネットワーク関連
        if any(keyword in error_lower for keyword in ['network', 'connection', 'timeout', 'dns', 'socket']):
            if 'timeout' in error_lower:
                return ErrorCategory.TIMEOUT
            return ErrorCategory.NETWORK
        
        # システム関連
        if any(keyword in error_lower for keyword in ['system', 'server', 'service', 'internal', 'unavailable']):
            return ErrorCategory.SYSTEM
        
        # RAG関連
        if any(keyword in error_lower for keyword in ['rag', 'vectorstore', 'embeddings', 'retrieval', 'documents']):
            return ErrorCategory.RAG
        
        # LLM関連
        if any(keyword in error_lower for keyword in ['llm', 'model', 'generation', 'openai', 'gemini', 'api_key']):
            return ErrorCategory.LLM
        
        # 認証関連
        if any(keyword in error_lower for keyword in ['auth', 'api_key', 'permission', 'unauthorized']):
            return ErrorCategory.AUTHENTICATION
        
        # リソース関連
        if any(keyword in error_lower for keyword in ['memory', 'disk', 'resource', 'quota', 'limit']):
            return ErrorCategory.RESOURCE
        
        # デフォルトはシステムエラー
        return ErrorCategory.SYSTEM

    def _get_message_for_category(
        self,
        category: ErrorCategory,
        platform: str,
        error_level: ErrorLevel
    ) -> str:
        """カテゴリとレベルに応じたメッセージを取得"""
        try:
            messages = self._error_messages.get(category, {}).get(error_level, {}).get(platform, [])
            
            if messages:
                # ランダムに選択してバリエーションを持たせる
                return random.choice(messages)
            
            # フォールバック: デフォルトメッセージ
            return self._get_default_message(platform, error_level)
            
        except Exception:
            return self._get_default_message(platform, error_level)

    def _get_action_suggestions(self, category: ErrorCategory, platform: str) -> List[str]:
        """アクション提案を取得"""
        try:
            suggestions = self._action_suggestions.get(platform, {}).get(category, [])
            # 最大3つまでの提案に制限
            return suggestions[:3]
        except Exception:
            return []

    def _customize_message_with_context(
        self,
        message: str,
        context: Dict,
        platform: str
    ) -> str:
        """コンテキストに応じてメッセージをカスタマイズ"""
        try:
            # ユーザー名が分かっている場合
            if context.get("user_name"):
                if platform == "line":
                    message = f"{context['user_name']}さん、" + message
                else:
                    message = f"{context['user_name']}様、" + message
            
            # 繰り返しエラーの場合
            if context.get("retry_count", 0) > 2:
                if platform == "line":
                    message += "\n何度もご不便をおかけして申し訳ありません。"
                else:
                    message += " 繰り返しエラーが発生してご迷惑をおかけしております。"
            
            return message
            
        except Exception:
            return message

    def _adjust_for_platform(self, message: str, platform: str) -> str:
        """プラットフォーム制限に合わせて調整"""
        try:
            platform_config = self._platform_messages.get(platform, {})
            max_length = platform_config.get("max_length", 500)
            
            # 文字数制限
            if len(message) > max_length:
                # 重要な部分を保持して短縮
                truncated = message[:max_length - 10] + "..."
                return truncated
            
            return message
            
        except Exception:
            return message

    def _get_default_message(self, platform: str, error_level: ErrorLevel) -> str:
        """デフォルトメッセージを取得"""
        if platform == "line":
            if error_level == ErrorLevel.ERROR:
                return "❌ 申し訳ございません。一時的な問題が発生しました。少し時間をおいてからもう一度お試しください。"
            else:
                return "⚠️ 少し調子が悪いようです。しばらくお待ちください。"
        else:
            if error_level == ErrorLevel.ERROR:
                return "申し訳ございません。システムに問題が発生しています。しばらく時間をおいてから再度お試しください。"
            else:
                return "一時的な問題が発生しています。少々お待ちください。"

    def _get_fallback_message(self, platform: str, error_level: ErrorLevel) -> Dict[str, any]:
        """フォールバックメッセージを返す"""
        return {
            "message": self._get_default_message(platform, error_level),
            "error_level": error_level.value,
            "error_category": "unknown",
            "platform": platform,
            "suggestions": ["しばらく時間をおいてから再度お試しください"],
            "timestamp": datetime.utcnow().isoformat(),
            "user_friendly": True,
            "fallback": True
        }

# グローバルインスタンス
error_messaging = ErrorMessaging()

def get_user_friendly_error_message(
    error_type: str,
    platform: str = "line",
    error_level: str = "error",
    user_context: Optional[Dict] = None
) -> Dict[str, any]:
    """
    ユーザーフレンドリーエラーメッセージを取得する便利関数
    
    Args:
        error_type: エラータイプ
        platform: プラットフォーム
        error_level: エラーレベル（文字列）
        user_context: ユーザーコンテキスト
        
    Returns:
        エラーメッセージ情報辞書
    """
    try:
        level = ErrorLevel(error_level)
    except ValueError:
        level = ErrorLevel.ERROR
    
    return error_messaging.get_user_friendly_message(
        error_type, platform, level, user_context
    )