# services/response_enhancement.py - 応答品質向上サービス（リッチメニュー対応修正版）

import logging
import re
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import asyncio
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class QualityIssueType(Enum):
    """品質問題の種類"""
    INCOMPLETE_SENTENCE = "incomplete_sentence"
    TOO_SHORT = "too_short"  
    TOO_LONG = "too_long"
    UNCLEAR_CONTENT = "unclear_content"
    INAPPROPRIATE_TONE = "inappropriate_tone"
    MISSING_CONTEXT = "missing_context"
    FACTUAL_INCONSISTENCY = "factual_inconsistency"
    FORMATTING_ISSUES = "formatting_issues"

@dataclass
class QualityAssessment:
    """品質評価結果"""
    overall_score: float  # 0.0-1.0
    issues: List[QualityIssueType]
    suggestions: List[str]
    completeness_score: float
    clarity_score: float
    appropriateness_score: float
    platform_optimization_score: float
    confidence: float

class ResponseEnhancementService:
    """応答品質向上サービス"""
    
    def __init__(self):
        self.enhancement_rules = {}
        self.quality_patterns = {}
        self.platform_optimizers = {}
        
        # 統計
        self.stats = {
            "total_enhancements": 0,
            "completeness_fixes": 0,
            "clarity_improvements": 0,
            "platform_optimizations": 0,
            "quality_assessments": 0,
            "average_improvement_score": 0.0,
            "richmenu_responses_preserved": 0  # リッチメニュー応答保持数
        }
        
        # 設定
        self.min_response_length = 10
        self.max_response_length = 2000
        self.target_clarity_score = 0.8
        self.enable_auto_enhancement = True
        
        # 🔧 リッチメニュー関連設定
        self.preserve_richmenu_responses = True  # リッチメニュー応答保持
        self.richmenu_response_markers = [
            "🤖 AI住まい相談を開始します！",
            "🌐 AI住まいサイトのご案内",
            "📋ありがとうございます！こちらからご覧いただけます。",
            "📍 展示場のご来場予約につきましては",
            "💬 AI資金診断のご案内",
            "💬 スタッフとのご相談"
        ]
        
        self._initialize_enhancement_rules()
        self._initialize_quality_patterns()
        self._initialize_platform_optimizers()

    def _initialize_enhancement_rules(self):
        """品質向上ルールの初期化（リッチメニュー対応）"""
        self.enhancement_rules = {
            # 文章完全性ルール（リッチメニュー応答は除外）
            "sentence_completion": {
                "patterns": [
                    (r"(.+)や$", r"\1や関連する準備を進めることをお勧めします。"),
                    (r"(.+)重要$", r"\1重要です。詳しくはお気軽にご相談ください。"),
                    (r"(.+)必要$", r"\1必要です。"),
                    (r"(.+)について$", r"\1については、詳細をご案内いたします。"),
                    (r"(.+)から$", r"\1から始めることをお勧めします。"),
                    (r"(.+)ため$", r"\1ため、お気軽にご相談ください。"),
                    (r"(.+)、$", r"\1。"),
                    (r"(.+)(は|が)$", r"\1\2重要なポイントです。"),
                    (r"(.+)(ます|です)$", r"\1\2。")
                ],
                "priority": 10,
                "exclude_richmenu": True  # リッチメニュー応答は除外
            },
            
            # 明確性向上ルール（リッチメニュー応答は最小限）
            "clarity_improvement": {
                "replacements": [
                    ("こちら", "弊社"),
                    ("あちら", "お客様"),
                    ("それ", "その内容"),
                    ("これ", "この件"),
                    ("そちら", "そのこと")
                ],
                "enhancements": [
                    (r"約(\d+)万円", r"約\1万円（税込）"),
                    (r"(\d+)年", r"\1年間"),
                    (r"(\d+)%", r"\1パーセント")
                ],
                "priority": 7,
                "exclude_richmenu": True  # リッチメニュー応答は除外
            },
            
            # 情報補完ルール（リッチメニュー応答は除外）
            "information_enrichment": {
                "context_additions": {
                    "坪単価": "※坪単価は建物の仕様、立地条件、施工時期により変動する場合があります。",
                    "補助金": "※補助金制度は年度により変更される可能性があります。最新情報をご確認ください。",
                    "住宅ローン": "※金利や条件は金融機関により異なります。複数の機関で比較検討されることをお勧めします。",
                    "工期": "※工期は天候、地盤状況、仕様変更等により変動する場合があります。"
                },
                "priority": 5,
                "exclude_richmenu": True  # リッチメニュー応答は除外
            }
        }

    def _initialize_quality_patterns(self):
        """品質評価パターンの初期化（リッチメニュー対応）"""
        self.quality_patterns = {
            # 完全性チェックパターン（リッチメニュー応答は除外）
            "completeness": {
                "incomplete_endings": [
                    r".+[やがはで]$",
                    r".+、$",
                    r".+について$",
                    r".+から$",
                    r".+ため$",
                    r".+ので$",
                    r".+重要$",
                    r".+必要$"
                ],
                "good_endings": [
                    r".+[。！？]$",
                    r".+です。$",
                    r".+ます。$",
                    r".+ください。$"
                ],
                "richmenu_exceptions": True  # リッチメニュー応答は例外扱い
            },
            
            # 明確性チェックパターン
            "clarity": {
                "unclear_phrases": [
                    "あれ", "それ", "これ", "そのこと", "このこと",
                    "こちら", "そちら", "あちら",
                    "なんか", "的な", "みたいな",
                    "結構", "かなり", "ちょっと"
                ],
                "technical_terms": [
                    "UA値", "C値", "断熱等級", "耐震等級", 
                    "ZEH", "長期優良住宅", "瑕疵担保"
                ],
                "richmenu_exceptions": True  # リッチメニュー応答は例外扱い
            },
            
            # 適切性チェックパターン
            "appropriateness": {
                "platform_specific": {
                    "web": {
                        "good_patterns": [r"いたします", r"ございます", r"お客様"],
                        "avoid_patterns": [r"😊", r"✨", r"💰", r"🏠"]
                    },
                    "line": {
                        "good_patterns": [r"😊", r"✨", r"です♪", r"ですね"],
                        "avoid_patterns": []  # LINEでは絵文字使用OK
                    }
                }
            }
        }

    def _initialize_platform_optimizers(self):
        """プラットフォーム最適化の初期化（リッチメニュー対応）"""
        self.platform_optimizers = {
            "web": {
                "tone_adjustments": [
                    (r"です♪", "です。"),
                    (r"ですね〜", "です。"),
                    (r"だよ", "です"),
                    (r"だね", "です")
                ],
                "formality_enhancements": [
                    (r"すごく", "非常に"),
                    (r"とても", "大変"),
                    (r"ちゃんと", "適切に"),
                    (r"きちんと", "確実に")
                ],
                "structure_improvements": [
                    # 箇条書きの改善
                    (r"・(.+)\n・(.+)\n・(.+)", r"・\1\n・\2\n・\3\n"),
                    # 段落分けの改善
                    (r"([。！？])([A-Z])", r"\1\n\n\2")
                ],
                "exclude_richmenu": True  # リッチメニュー応答は除外
            },
            
            "line": {
                # 🔧 LINEでは最小限の調整のみ（リッチメニュー応答保持）
                "tone_adjustments": [],  # 調整なし
                "emoji_enhancements": [],  # 絵文字追加なし
                "length_optimization": [
                    # 極端に長い文のみ分割（400文字超える場合のみ）
                    (r"(.{400,}?)([、。])(.+)", r"\1\2\n\n\3")
                ],
                "exclude_richmenu": True  # リッチメニュー応答は完全除外
            }
        }

    def _is_richmenu_response(self, response: str) -> bool:
        """リッチメニュー応答かどうかを判定"""
        if not self.preserve_richmenu_responses:
            return False
        
        # マーカー文字列での判定
        for marker in self.richmenu_response_markers:
            if marker in response:
                return True
        
        # リッチメニューボタン名での判定
        richmenu_buttons = [
            "🤖 AI相談", "🌐 AI住まいサイト", "📋 資料請求",
            "📍 展示場来場　予約", "💰 資金計画", "💬 チャット相談"
        ]
        
        for button in richmenu_buttons:
            if response.strip().startswith(button):
                return True
        
        # 特徴的なフレーズでの判定
        richmenu_phrases = [
            "キノエデザインの住まいAIコンシェルジュです",
            "展示場のご来場予約につきましては",
            "AI資金診断のご案内",
            "スタッフとのご相談",
            "プライバシーポリシー：【",
            "利用規約：【",
            "Cookie：【"
        ]
        
        for phrase in richmenu_phrases:
            if phrase in response:
                return True
        
        return False

    async def enhance_response(self, response: str, query: str, platform: str = "web",
                             user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """応答品質向上のメイン処理（リッチメニュー対応）"""
        start_time = time.time()
        self.stats["total_enhancements"] += 1
        
        try:
            # 🔧 リッチメニュー応答の場合は最小限の処理で保持
            if self._is_richmenu_response(response):
                self.stats["richmenu_responses_preserved"] += 1
                logger.info(f"🎯 Richmenu response detected - preserving original content")
                
                # リッチメニュー応答は元のまま返す
                return {
                    "enhanced_response": response,  # そのまま保持
                    "original_response": response,
                    "quality_assessment": None,  # 評価スキップ
                    "enhancements_applied": ["richmenu_preservation"],
                    "processing_time": time.time() - start_time,
                    "improvement_score": 0.0,
                    "richmenu_response": True
                }
            
            # 通常の応答処理
            # 1. 品質評価
            quality_assessment = await self._assess_response_quality(
                response, query, platform, user_context
            )
            
            # 2. 改善が必要かチェック
            if not self._needs_enhancement(quality_assessment):
                return {
                    "enhanced_response": response,
                    "original_response": response,
                    "quality_assessment": quality_assessment,
                    "enhancements_applied": [],
                    "processing_time": time.time() - start_time,
                    "improvement_score": 0.0
                }
            
            # 3. 段階的品質向上
            enhanced_response = response
            applied_enhancements = []
            
            # 文章完全性の修正（リッチメニュー応答以外）
            if (QualityIssueType.INCOMPLETE_SENTENCE in quality_assessment.issues and
                not self._is_richmenu_response(enhanced_response)):
                enhanced_response = self._fix_sentence_completion(
                    enhanced_response, platform
                )
                applied_enhancements.append("sentence_completion")
                self.stats["completeness_fixes"] += 1
            
            # 明確性の向上（リッチメニュー応答以外）
            if (QualityIssueType.UNCLEAR_CONTENT in quality_assessment.issues and
                not self._is_richmenu_response(enhanced_response)):
                enhanced_response = self._improve_clarity(
                    enhanced_response, query, platform
                )
                applied_enhancements.append("clarity_improvement")
                self.stats["clarity_improvements"] += 1
            
            # プラットフォーム最適化（リッチメニュー応答は最小限）
            enhanced_response = self._optimize_for_platform(
                enhanced_response, platform, user_context
            )
            applied_enhancements.append("platform_optimization")
            self.stats["platform_optimizations"] += 1
            
            # 長さ調整（リッチメニュー応答は除外）
            if ((QualityIssueType.TOO_SHORT in quality_assessment.issues or 
                QualityIssueType.TOO_LONG in quality_assessment.issues) and
                not self._is_richmenu_response(enhanced_response)):
                enhanced_response = self._adjust_response_length(
                    enhanced_response, platform, quality_assessment
                )
                applied_enhancements.append("length_adjustment")
            
            # 4. 再評価
            final_assessment = await self._assess_response_quality(
                enhanced_response, query, platform, user_context
            )
            
            improvement_score = final_assessment.overall_score - quality_assessment.overall_score
            self.stats["average_improvement_score"] = (
                (self.stats["average_improvement_score"] * (self.stats["total_enhancements"] - 1) + improvement_score) /
                self.stats["total_enhancements"]
            )
            
            processing_time = time.time() - start_time
            
            logger.info(f"✨ Response enhanced: {improvement_score:+.3f} improvement, "
                       f"applied: {', '.join(applied_enhancements)}")
            
            return {
                "enhanced_response": enhanced_response,
                "original_response": response,
                "quality_assessment": quality_assessment,
                "final_assessment": final_assessment,
                "enhancements_applied": applied_enhancements,
                "improvement_score": improvement_score,
                "processing_time": processing_time
            }
            
        except Exception as e:
            logger.error(f"Response enhancement error: {e}")
            return {
                "enhanced_response": response,  # フォールバック
                "original_response": response,
                "error": str(e),
                "processing_time": time.time() - start_time
            }

    async def _assess_response_quality(self, response: str, query: str, 
                                     platform: str, user_context: Optional[Dict]) -> QualityAssessment:
        """応答品質の評価（リッチメニュー対応）"""
        self.stats["quality_assessments"] += 1
        
        # 🔧 リッチメニュー応答は高品質として扱う
        if self._is_richmenu_response(response):
            return QualityAssessment(
                overall_score=0.95,  # 高品質スコア
                issues=[],
                suggestions=[],
                completeness_score=1.0,
                clarity_score=1.0,
                appropriateness_score=1.0,
                platform_optimization_score=1.0,
                confidence=1.0
            )
        
        issues = []
        suggestions = []
        
        # 基本的な品質チェック
        response_length = len(response.strip())
        
        # 長さチェック
        if response_length < self.min_response_length:
            issues.append(QualityIssueType.TOO_SHORT)
            suggestions.append("応答をより詳しく記述してください")
        elif response_length > self.max_response_length:
            issues.append(QualityIssueType.TOO_LONG)
            suggestions.append("応答を簡潔にまとめてください")
        
        # 完全性チェック
        completeness_score = self._evaluate_completeness(response)
        if completeness_score < 0.8:
            issues.append(QualityIssueType.INCOMPLETE_SENTENCE)
            suggestions.append("文章の終わり方を改善してください")
        
        # 明確性チェック
        clarity_score = self._evaluate_clarity(response, query)
        if clarity_score < self.target_clarity_score:
            issues.append(QualityIssueType.UNCLEAR_CONTENT)
            suggestions.append("より具体的で分かりやすい表現にしてください")
        
        # プラットフォーム適合性チェック
        appropriateness_score = self._evaluate_platform_appropriateness(response, platform)
        if appropriateness_score < 0.7:
            issues.append(QualityIssueType.INAPPROPRIATE_TONE)
            suggestions.append(f"{platform}プラットフォームに適した表現に調整してください")
        
        # プラットフォーム最適化スコア
        platform_optimization_score = self._evaluate_platform_optimization(response, platform)
        
        # 総合スコア計算
        overall_score = (
            completeness_score * 0.3 +
            clarity_score * 0.3 +
            appropriateness_score * 0.2 +
            platform_optimization_score * 0.2
        )
        
        # 信頼度計算
        confidence = min(1.0, len(response) / 100)  # レスポンス長に基づく簡易信頼度
        
        return QualityAssessment(
            overall_score=overall_score,
            issues=issues,
            suggestions=suggestions,
            completeness_score=completeness_score,
            clarity_score=clarity_score,
            appropriateness_score=appropriateness_score,
            platform_optimization_score=platform_optimization_score,
            confidence=confidence
        )

    def _evaluate_completeness(self, response: str) -> float:
        """文章完全性の評価（リッチメニュー対応）"""
        # リッチメニュー応答は完全として扱う
        if self._is_richmenu_response(response):
            return 1.0
        
        patterns = self.quality_patterns["completeness"]
        
        # 不完全な終わり方をチェック
        for pattern in patterns["incomplete_endings"]:
            if re.search(pattern, response.strip()):
                return 0.3  # 低スコア
        
        # 適切な終わり方をチェック
        for pattern in patterns["good_endings"]:
            if re.search(pattern, response.strip()):
                return 1.0  # 高スコア
        
        # 文の終わり方が曖昧
        if response.strip() and not response.strip()[-1] in "。！？.!?":
            return 0.6
        
        return 0.8  # 標準スコア

    def _evaluate_clarity(self, response: str, query: str) -> float:
        """明確性の評価（リッチメニュー対応）"""
        # リッチメニュー応答は明確として扱う
        if self._is_richmenu_response(response):
            return 1.0
        
        patterns = self.quality_patterns["clarity"]
        score = 1.0
        
        # 不明確な表現のペナルティ
        unclear_count = 0
        for phrase in patterns["unclear_phrases"]:
            unclear_count += len(re.findall(phrase, response, re.IGNORECASE))
        
        if unclear_count > 0:
            score -= min(0.5, unclear_count * 0.1)
        
        # 専門用語の説明チェック（簡易版）
        technical_terms = [term for term in patterns["technical_terms"] if term in response]
        if technical_terms and len(response) < 200:
            score -= 0.2  # 専門用語があるのに説明が短い
        
        # 質問との関連性チェック（キーワードベース）
        query_keywords = set(re.findall(r'\w+', query.lower()))
        response_keywords = set(re.findall(r'\w+', response.lower()))
        
        if query_keywords:
            relevance = len(query_keywords & response_keywords) / len(query_keywords)
            score *= (0.7 + 0.3 * relevance)  # 関連性による重み付け
        
        return max(0.0, min(1.0, score))

    def _evaluate_platform_appropriateness(self, response: str, platform: str) -> float:
        """プラットフォーム適合性の評価（リッチメニュー対応）"""
        # リッチメニュー応答は適切として扱う
        if self._is_richmenu_response(response):
            return 1.0
        
        if platform not in self.quality_patterns["appropriateness"]["platform_specific"]:
            return 0.8  # デフォルトスコア
        
        platform_rules = self.quality_patterns["appropriateness"]["platform_specific"][platform]
        score = 0.8
        
        # 推奨パターンのボーナス
        good_patterns = platform_rules.get("good_patterns", [])
        good_matches = sum(len(re.findall(pattern, response)) for pattern in good_patterns)
        if good_matches > 0:
            score += min(0.2, good_matches * 0.05)
        
        # 避けるべきパターンのペナルティ
        avoid_patterns = platform_rules.get("avoid_patterns", [])
        avoid_matches = sum(len(re.findall(pattern, response)) for pattern in avoid_patterns)
        if avoid_matches > 0:
            score -= min(0.3, avoid_matches * 0.1)
        
        return max(0.0, min(1.0, score))

    def _evaluate_platform_optimization(self, response: str, platform: str) -> float:
        """プラットフォーム最適化の評価（リッチメニュー対応）"""
        # リッチメニュー応答は最適化済みとして扱う
        if self._is_richmenu_response(response):
            return 1.0
        
        if platform == "line":
            # LINE最適化評価
            emoji_count = len(re.findall(r'[😀-🿿]', response))
            length = len(response)
            
            # 適度な絵文字使用
            emoji_score = min(1.0, emoji_count / 5) if emoji_count <= 10 else 0.5
            
            # 適切な長さ
            length_score = 1.0 if 50 <= length <= 400 else 0.7
            
            # 親しみやすい表現
            friendly_patterns = ['です♪', 'ですね', '😊', '✨']
            friendly_count = sum(len(re.findall(pattern, response)) for pattern in friendly_patterns)
            friendly_score = min(1.0, friendly_count / 3)
            
            return (emoji_score + length_score + friendly_score) / 3
        
        else:  # web
            # Web最適化評価
            length = len(response)
            
            # 適切な長さと詳細度
            detail_score = 1.0 if 100 <= length <= 1000 else 0.8
            
            # フォーマルな表現
            formal_patterns = ['いたします', 'ございます', 'お客様']
            formal_count = sum(len(re.findall(pattern, response)) for pattern in formal_patterns)
            formal_score = min(1.0, formal_count / 2)
            
            # 構造化（箇条書きなど）
            structure_patterns = ['・', '1.', '2.', '**', '##']
            structure_count = sum(len(re.findall(pattern, response)) for pattern in structure_patterns)
            structure_score = min(1.0, structure_count / 3)
            
            return (detail_score + formal_score + structure_score) / 3

    def _needs_enhancement(self, assessment: QualityAssessment) -> bool:
        """改善が必要かの判定"""
        if not self.enable_auto_enhancement:
            return False
        
        # 重大な問題がある場合
        critical_issues = [
            QualityIssueType.INCOMPLETE_SENTENCE,
            QualityIssueType.TOO_SHORT
        ]
        
        if any(issue in assessment.issues for issue in critical_issues):
            return True
        
        # 総合スコアが低い場合
        if assessment.overall_score < 0.7:
            return True
        
        # 特定のスコアが低い場合
        if (assessment.completeness_score < 0.8 or 
            assessment.clarity_score < 0.7 or
            assessment.appropriateness_score < 0.7):
            return True
        
        return False

    def _fix_sentence_completion(self, response: str, platform: str) -> str:
        """文章完全性の修正（リッチメニュー応答は除外）"""
        # リッチメニュー応答は変更しない
        if self._is_richmenu_response(response):
            return response
        
        rules = self.enhancement_rules["sentence_completion"]
        
        enhanced = response.strip()
        
        for pattern, replacement in rules["patterns"]:
            if re.search(pattern, enhanced):
                enhanced = re.sub(pattern, replacement, enhanced)
                break
        
        # プラットフォーム別調整（リッチメニュー以外）
        if platform == "line" and not enhanced.endswith(('。', '！', '？')):
            if enhanced.endswith(('です', 'ます')):
                enhanced += '😊'
            else:
                enhanced += '。'
        
        return enhanced

    def _improve_clarity(self, response: str, query: str, platform: str) -> str:
        """明確性の向上（リッチメニュー応答は除外）"""
        # リッチメニュー応答は変更しない
        if self._is_richmenu_response(response):
            return response
        
        rules = self.enhancement_rules["clarity_improvement"]
        enhanced = response
        
        # 曖昧な表現の置換
        for old, new in rules["replacements"]:
            enhanced = enhanced.replace(old, new)
        
        # 情報の具体化
        for pattern, replacement in rules["enhancements"]:
            enhanced = re.sub(pattern, replacement, enhanced)
        
        # 文脈的補完（クエリに基づく）
        info_rules = self.enhancement_rules["information_enrichment"]
        for keyword, addition in info_rules["context_additions"].items():
            if keyword in query and keyword in enhanced and addition not in enhanced:
                enhanced += f"\n\n{addition}"
        
        return enhanced

    def _optimize_for_platform(self, response: str, platform: str, 
                             user_context: Optional[Dict]) -> str:
        """プラットフォーム最適化（リッチメニュー応答は最小限処理）"""
        # 🔧 リッチメニュー応答は最小限の処理のみ
        if self._is_richmenu_response(response):
            # 極端に長い場合のみ分割（1000文字超える場合）
            if len(response) > 1000 and platform == "line":
                # 改行で自然分割
                lines = response.split('\n')
                if len('\n'.join(lines[:len(lines)//2])) < 800:
                    return '\n'.join(lines[:len(lines)//2])
            return response  # 基本的にはそのまま返す
        
        if platform not in self.platform_optimizers:
            return response
        
        optimizer = self.platform_optimizers[platform]
        enhanced = response
        
        # トーン調整（リッチメニュー以外）
        for old, new in optimizer.get("tone_adjustments", []):
            enhanced = re.sub(old, new, enhanced)
        
        # プラットフォーム特有の改善
        if platform == "web":
            # フォーマル化（リッチメニュー以外）
            for old, new in optimizer.get("formality_enhancements", []):
                enhanced = enhanced.replace(old, new)
            
            # 構造改善（リッチメニュー以外）
            for pattern, replacement in optimizer.get("structure_improvements", []):
                enhanced = re.sub(pattern, replacement, enhanced)
        
        elif platform == "line":
            # LINEでは最小限の調整のみ（リッチメニュー応答は完全除外済み）
            
            # 長さ最適化（極端に長い場合のみ）
            for pattern, replacement in optimizer.get("length_optimization", []):
                enhanced = re.sub(pattern, replacement, enhanced)
        
        return enhanced

    def _adjust_response_length(self, response: str, platform: str, 
                              assessment: QualityAssessment) -> str:
        """応答長の調整（リッチメニュー応答は除外）"""
        # リッチメニュー応答は変更しない
        if self._is_richmenu_response(response):
            return response
        
        if QualityIssueType.TOO_SHORT in assessment.issues:
            return self._expand_response(response, platform)
        elif QualityIssueType.TOO_LONG in assessment.issues:
            return self._compress_response(response, platform)
        return response

    def _expand_response(self, response: str, platform: str) -> str:
        """応答の拡張（リッチメニュー応答は除外）"""
        # リッチメニュー応答は変更しない
        if self._is_richmenu_response(response):
            return response
        
        if platform == "line":
            # LINE用の短い追加情報
            additions = [
                "詳しくはお気軽にご相談ください😊",
                "他にもご質問がありましたらお聞かせください✨",
                "スタッフがサポートいたします📞"
            ]
        else:
            # Web用の詳細追加情報
            additions = [
                "詳細につきましては、お気軽にお問い合わせください。",
                "より具体的なご相談も承っております。",
                "専門スタッフが丁寧にご説明いたします。"
            ]
        
        # 既存の内容と重複しない追加文を選択
        for addition in additions:
            if addition not in response:
                return f"{response.rstrip()}。{addition}"
        
        return response

    def _compress_response(self, response: str, platform: str) -> str:
        """応答の圧縮（リッチメニュー応答は除外）"""
        # リッチメニュー応答は変更しない
        if self._is_richmenu_response(response):
            return response
        
        # 不要な繰り返しの除去
        sentences = response.split('。')
        unique_sentences = []
        seen_content = set()
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # 内容の類似性チェック（簡易版）
            content_key = ''.join(re.findall(r'\w', sentence.lower()))
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_sentences.append(sentence)
        
        compressed = '。'.join(unique_sentences)
        if compressed and not compressed.endswith('。'):
            compressed += '。'
        
        # まだ長すぎる場合は最重要文のみ保持
        if len(compressed) > self.max_response_length:
            # 最初の2文を保持
            first_sentences = '。'.join(unique_sentences[:2])
            if first_sentences:
                compressed = first_sentences + '。'
        
        return compressed

    def get_service_stats(self) -> Dict[str, Any]:
        """サービス統計取得（リッチメニュー対応）"""
        return {
            "performance": {
                "total_enhancements": self.stats["total_enhancements"],
                "completeness_fixes": self.stats["completeness_fixes"],
                "clarity_improvements": self.stats["clarity_improvements"],
                "platform_optimizations": self.stats["platform_optimizations"],
                "quality_assessments": self.stats["quality_assessments"],
                "average_improvement_score": self.stats["average_improvement_score"],
                "richmenu_responses_preserved": self.stats["richmenu_responses_preserved"]  # 追加
            },
            "enhancement_rates": {
                "completeness_fix_rate": (self.stats["completeness_fixes"] / max(1, self.stats["total_enhancements"]) * 100),
                "clarity_improvement_rate": (self.stats["clarity_improvements"] / max(1, self.stats["total_enhancements"]) * 100),
                "platform_optimization_rate": (self.stats["platform_optimizations"] / max(1, self.stats["total_enhancements"]) * 100),
                "richmenu_preservation_rate": (self.stats["richmenu_responses_preserved"] / max(1, self.stats["total_enhancements"]) * 100)  # 追加
            },
            "configuration": {
                "auto_enhancement_enabled": self.enable_auto_enhancement,
                "min_response_length": self.min_response_length,
                "max_response_length": self.max_response_length,
                "target_clarity_score": self.target_clarity_score,
                "preserve_richmenu_responses": self.preserve_richmenu_responses  # 追加
            },
            "enhancement_features": [
                "Sentence completion (excluding richmenu)",
                "Clarity improvement (excluding richmenu)", 
                "Platform optimization (minimal for richmenu)",
                "Length adjustment (excluding richmenu)",
                "Tone adjustment (excluding richmenu)",
                "Information enrichment (excluding richmenu)",
                "Richmenu response preservation"  # 追加
            ]
        }

    def configure(self, **kwargs) -> None:
        """サービス設定の更新（リッチメニュー対応）"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.info(f"Configuration updated: {key} = {value}")

# グローバルサービスインスタンス
_global_enhancement_service = None

def get_response_enhancement_service() -> ResponseEnhancementService:
    """グローバル応答品質向上サービス取得"""
    global _global_enhancement_service
    
    if _global_enhancement_service is None:
        _global_enhancement_service = ResponseEnhancementService()
    
    return _global_enhancement_service

def enhance_response_quality(response: str, query: str, platform: str = "web") -> str:
    """応答品質向上（簡易インターフェース）"""
    service = get_response_enhancement_service()
    
    # 同期実行版
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(
        service.enhance_response(response, query, platform)
    )
    
    return result.get("enhanced_response", response)

def reset_enhancement_service() -> ResponseEnhancementService:
    """サービスリセット"""
    global _global_enhancement_service
    _global_enhancement_service = None
    return get_response_enhancement_service()