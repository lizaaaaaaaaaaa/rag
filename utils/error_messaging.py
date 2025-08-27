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
        
        # エラーカテゴリ別メッセージマッピング（簡潔な固定メッセージに統一）
        self._error_messages = {
            ErrorCategory.NETWORK: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ 通信エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "通信エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ 通信エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "通信エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.SYSTEM: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ システムエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "システムエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ システムエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "システムエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.RAG: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ データ取得エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "データ取得エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ データ取得エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "データ取得エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.LLM: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ AI処理エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "AI処理エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ AI処理エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "AI処理エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.TIMEOUT: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ タイムアウトエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "タイムアウトエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ タイムアウトエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "タイムアウトエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.USER_INPUT: {
                ErrorLevel.INFO: {
                    "line": [
                        "⚠️ 入力エラーが発生しました。もう一度お試しください。"
                    ],
                    "web": [
                        "入力エラーが発生しました。もう一度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.AUTHENTICATION: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ 認証エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "認証エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ 認証エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "認証エラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            },
            
            ErrorCategory.RESOURCE: {
                ErrorLevel.WARNING: {
                    "line": [
                        "⚠️ リソースエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "リソースエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                },
                ErrorLevel.ERROR: {
                    "line": [
                        "⚠️ リソースエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ],
                    "web": [
                        "リソースエラーが発生しました。少しお待ちいただいてから再度お試しください。"
                    ]
                }
            }
        }
        
        # 次のアクション提案（簡潔に統一）
        self._action_suggestions = {
            "line": {
                ErrorCategory.NETWORK: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.SYSTEM: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.RAG: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.LLM: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.TIMEOUT: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.AUTHENTICATION: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.RESOURCE: [
                    "少しお待ちいただいてから再度お試しください。"
                ]
            },
            "web": {
                ErrorCategory.NETWORK: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.SYSTEM: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.RAG: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.LLM: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.TIMEOUT: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.AUTHENTICATION: [
                    "少しお待ちいただいてから再度お試しください。"
                ],
                ErrorCategory.RESOURCE: [
                    "少しお待ちいただいてから再度お試しください。"
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
            
            # アクション提案を取得（簡潔な固定メッセージ）
            suggestions = []
            if include_suggestions:
                suggestions = self._get_action_suggestions(category, platform)
            
            # コンテキストカスタマイズは行わない（固定メッセージ維持）
            
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
                # 固定メッセージを返す（ランダム選択不要）
                return messages[0]
            
            # フォールバック: デフォルトメッセージ
            return self._get_default_message(platform, error_level)
            
        except Exception:
            return self._get_default_message(platform, error_level)

    def _get_action_suggestions(self, category: ErrorCategory, platform: str) -> List[str]:
        """アクション提案を取得"""
        try:
            suggestions = self._action_suggestions.get(platform, {}).get(category, [])
            # 簡潔な固定メッセージのみ
            return suggestions[:1]
        except Exception:
            return []

    def _customize_message_with_context(
        self,
        message: str,
        context: Dict,
        platform: str
    ) -> str:
        """コンテキストカスタマイズは行わない（固定メッセージ維持）"""
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
        """デフォルトメッセージを取得（簡潔な固定メッセージ）"""
        if platform == "line":
            return "⚠️ エラーが発生しました。少しお待ちいただいてから再度お試しください。"
        else:
            return "エラーが発生しました。少しお待ちいただいてから再度お試しください。"

    def _get_fallback_message(self, platform: str, error_level: ErrorLevel) -> Dict[str, any]:
        """フォールバックメッセージを返す"""
        return {
            "message": self._get_default_message(platform, error_level),
            "error_level": error_level.value,
            "error_category": "unknown",
            "platform": platform,
            "suggestions": ["少しお待ちいただいてから再度お試しください。"],
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
