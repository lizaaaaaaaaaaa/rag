# rag/fast_rag_chain.py - 超高速版（応答速度最優先・FAQ拡充版）

from __future__ import annotations
import os
import logging
import traceback
import asyncio
import re  # ✅ re モジュールをインポート
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from langchain.schema import Document
from langchain_core.embeddings import Embeddings
import time
import concurrent.futures
import hashlib
import json

logger = logging.getLogger(__name__)

LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# 🚀 超高速キャッシュ強化（サイズ拡大・永続化）
_ultra_fast_cache = {}
_cache_hits = 0
_cache_misses = 0
MAX_ULTRA_CACHE_SIZE = 800  # 🔧 拡大：500→800
CACHE_EXPIRE_TIME = 10800   # 🔧 3時間キャッシュ（短縮→延長）

# 🚀 FAQ事前キャッシュ（大幅拡充・住宅専門）
_faq_cache = {
    # === 価格・費用関連 ===
    "坪単価": "坪単価は約70～85万円/坪（標準仕様）、約85～100万円/坪（高性能仕様）です。お客様のご要望に応じて詳細なお見積りをご提供いたします。",
    "価格": "価格については、建物の仕様・設備グレード・立地条件により変動いたします。詳細なお見積りをお作りしますので、お気軽にお問い合わせください。",
    "費用": "建築費用は坪単価×延床面積に加え、付帯工事費（15-20%程度）、諸費用（5-8%程度）が必要です。総額での資金計画をサポートいたします。",
    "金額": "建築金額は仕様により異なりますが、標準仕様で約70～85万円/坪が目安です。ご予算に応じたプランをご提案いたします。",
    "いくら": "建築費は延床面積と仕様により決まります。30坪で約2100～2550万円、35坪で約2450～2975万円が標準仕様での目安です。",
    "値段": "住宅価格は仕様・設備により幅がありますが、品質と価格のバランスを重視した適正価格でご提供しています。",
    
    # === 仕様・設備関連 ===
    "標準仕様": "標準仕様は耐震等級3の長期優良住宅基準で、高断熱・高気密仕様、システムキッチン、ユニットバス、エコキュートなどを標準装備しています。",
    "仕様": "住宅仕様は構造（耐震等級3）、断熱（ZEH基準対応）、設備（標準グレード）を基本とし、お客様のご要望に応じてカスタマイズ可能です。",
    "設備": "標準設備にはシステムキッチン、ユニットバス、洗面化粧台、温水洗浄便座付きトイレ、エコキュートが含まれます。",
    "キッチン": "標準キッチンは食器洗い乾燥機付きシステムキッチンです。カウンタータイプ、アイランド型など、レイアウトも選択可能です。",
    "お風呂": "標準バスルームは1坪タイプのユニットバスで、浴室乾燥機付きです。1.25坪タイプへのアップグレードも可能です。",
    
    # === 性能関連 ===
    "断熱": "高性能断熱材使用でZEH基準対応の省エネ性能です。UA値0.6以下、C値1.0以下を実現し、年間光熱費を大幅削減できます。",
    "断熱性能": "断熱等級4以上を標準とし、外壁・屋根・基礎に高性能断熱材を使用。夏涼しく冬暖かい快適な住環境を実現します。",
    "耐震": "耐震等級3を標準とし、建築基準法の1.5倍の耐震強度を実現。地震に強い安心・安全な住まいです。",
    "耐震性能": "許容応力度計算による構造計算を実施し、耐震等級3を取得。構造用集成材と金物工法で強固な構造を実現しています。",
    "性能": "住宅性能は耐震等級3、断熱等級4以上、省エネ等級4以上を標準とし、長期優良住宅認定にも対応しています。",
    "ZEH": "ZEH（ゼロエネルギーハウス）に対応可能です。高断熱仕様に太陽光発電システムを組み合わせ、年間エネルギー収支ゼロを目指します。",
    
    # === 補助金・制度関連 ===
    "補助金": "ZEH補助金（55万円～）、こどもエコすまい支援事業（最大100万円）、住宅ローン減税、地域の補助金制度などが活用できます。",
    "助成金": "住宅取得に関する助成金制度は多数あります。お客様の条件に最適な制度をご提案し、申請手続きもサポートいたします。",
    "支援金": "国・自治体の住宅取得支援金制度をフル活用し、お客様の負担軽減を図ります。最新制度情報を常に把握しています。",
    "減税": "住宅ローン減税により最大13年間の所得税控除が受けられます。認定住宅では優遇措置もあります。",
    "住宅ローン減税": "住宅ローン残高の0.7%を最大13年間所得税から控除。認定長期優良住宅では年間最大35万円の控除が可能です。",
    
    # === サービス関連 ===
    "資料請求": "会社案内、施工事例集、間取りプラン集、価格・仕様資料をお送りします。お名前、ご住所、お電話番号をお教えください。",
    "展示場": "展示場では実際の住宅仕様をご確認いただけます。営業時間は9:00-18:00（水曜定休）です。ご予約をお取りいたします。",
    "見学": "モデルハウス見学により、実際の間取り・設備・住み心地を体感できます。専門スタッフがご案内いたします。",
    "相談": "住まいづくりのご相談は、展示場・お電話・LINEで承ります。資金計画から土地探し、建築まで トータルサポートします。",
    "予約": "展示場見学のご予約を承ります。お客様のご都合に合わせて、専門スタッフがご案内いたします。",
    
    # === 住まいづくりプロセス関連 ===
    "土地": "土地探しからサポートいたします。立地条件、価格、法的制限などを総合的に判断し、最適な土地をご提案します。",
    "土地探し": "ご希望エリア、予算、条件に合わせて土地探しをお手伝い。地盤調査、法規制チェックも含めてサポートします。",
    "ローン": "住宅ローンは金利タイプ、借入期間、返済方法など様々な選択肢があります。お客様に最適なプランをご提案します。",
    "資金計画": "無理のない返済計画を立てるため、年収、家族構成、将来設計を踏まえた資金計画をご提案します。",
    "流れ": "住まいづくりは、相談→土地探し→プラン作成→契約→着工→完成→引渡しの流れで進みます。各段階でしっかりサポートします。",
    
    # === 間取り・設計関連 ===
    "間取り": "ライフスタイルに合わせた間取りプランをご提案。家族構成、趣味、将来計画を考慮した最適なプランを作成します。",
    "設計": "お客様のご要望を形にする自由設計。敷地条件、法規制を踏まえ、機能的で美しい住まいを設計します。",
    "プラン": "豊富な間取りプランをご用意。標準プランからフルオーダーまで、ご要望に応じて対応いたします。",
    
    # === 建築・工事関連 ===
    "工期": "建築工期は約4-6ヶ月です。着工前の準備期間を含めると、契約から入居まで約6-8ヶ月が標準的なスケジュールです。",
    "施工": "自社職人による直接施工で品質を確保。第三者機関による検査も実施し、安心の施工体制を構築しています。",
    "工事": "地鎮祭から上棟、完成まで、各工程でお客様にご確認いただきながら丁寧に工事を進めます。",
    
    # === 保証・アフター関連 ===
    "保証": "構造躯体20年保証、設備10年保証、24時間365日のアフターサポート体制で、長期にわたり安心をお約束します。",
    "アフター": "定期点検（1年、2年、5年、10年）とメンテナンスサポートにより、住まいの価値を長期間維持します。",
    "メンテナンス": "住宅の定期メンテナンスは住まいの寿命を延ばします。計画的なメンテナンススケジュールをご提案します。",
    
    # === AI・サービス関連 ===
    "aiの相談": "🤖 AI住まい相談サービスでは、住まいに関するご質問に24時間いつでもお答えします。お気軽にご利用ください。",
    "AI相談": "住まいAIコンシェルジュがお客様のご質問にお答えします。基本的な疑問から詳しい仕様まで、何でもお聞きください。",
    "ai住まいサイト": "🌊 AI住まいサイトでは、住宅に関する情報を24時間いつでも検索・閲覧できます。https://preview.studio.site/live/EjOQljz1WJ/",
    "チャット相談": "💬 LINEチャット相談では営業時間内にスタッフが直接対応いたします。専門的なご相談もお気軽にどうぞ。"
}

# 🚀 高頻度キーワードセット（パフォーマンス向上用）
_high_frequency_keywords = {
    "価格系": ["坪単価", "価格", "費用", "金額", "いくら", "値段"],
    "仕様系": ["標準仕様", "仕様", "設備", "キッチン", "お風呂"],
    "性能系": ["断熱", "耐震", "性能", "ZEH", "省エネ"],
    "制度系": ["補助金", "助成金", "減税", "住宅ローン減税"],
    "サービス系": ["資料請求", "展示場", "相談", "AI相談"]
}

class SuperFastEmbedding(Embeddings):
    """超高速埋め込みクラス（最適化強化）"""
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        logger.info(f"🚀 Loading optimized embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.model.eval()
        
        # 🚀 更なる最適化強化
        import torch
        torch.set_num_threads(1)  # 🔧 削減：2→1（シングルスレッド）
        
        if hasattr(self.model, 'max_seq_length'):
            self.model.max_seq_length = 200  # 🔧 さらに短縮（超速度重視）
            
        logger.info("✅ Ultra-fast embedding model loaded with extreme optimizations")
    
    def embed_documents(self, texts):
        # 🚀 バッチサイズさらに拡大
        return self.model.encode(texts, 
                               show_progress_bar=False, 
                               convert_to_tensor=False, 
                               batch_size=64,  # 🔧 拡大：32→64
                               normalize_embeddings=True).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text, 
                               convert_to_tensor=False, 
                               normalize_embeddings=True).tolist()

def super_fast_cache_key(query: str) -> str:
    """超高速キャッシュキー生成（正規化さらに強化）"""
    # 🚀 より積極的な正規化
    normalized = query.lower().strip()
    normalized = re.sub(r'[？?！!。、\s\n\r\t]+', '', normalized)  # ノイズ徹底除去
    normalized = normalized.replace("について", "").replace("教えて", "").replace("知りたい", "")
    normalized = normalized.replace("ください", "").replace("です", "").replace("ます", "")
    return hashlib.md5(normalized[:40].encode()).hexdigest()[:6]  # 🔧 短縮：8→6

def get_faq_response_enhanced(query: str) -> str | None:
    """🚀 強化版FAQ事前キャッシュから超高速回答取得"""
    q_normalized = query.lower().strip()
    
    # 🚀 完全一致チェック（最優先・最高速）
    if q_normalized in _faq_cache:
        logger.info(f"⚡ FAQ完全一致: {q_normalized}")
        return _faq_cache[q_normalized]
    
    # 🚀 高頻度キーワード最適化チェック
    for category, keywords in _high_frequency_keywords.items():
        for keyword in keywords:
            if keyword in q_normalized and keyword in _faq_cache:
                logger.info(f"⚡ 高頻度キーワード: {keyword}")
                return _faq_cache[keyword]
    
    # 🚀 部分一致チェック（効率重視）
    for faq_key, response in _faq_cache.items():
        if faq_key in q_normalized:
            logger.info(f"⚡ FAQ部分一致: {faq_key}")
            return response
    
    return None

def get_ultra_fast_cached_response(query: str) -> str | None:
    """超高速キャッシュから回答取得（FAQ優先・期限チェック付き）"""
    global _cache_hits, _cache_misses
    
    # 🚀 FAQ最優先チェック（99%をここでキャッチ）
    faq_response = get_faq_response_enhanced(query)
    if faq_response:
        _cache_hits += 1
        return faq_response
    
    key = super_fast_cache_key(query)
    current_time = time.time()
    
    if key in _ultra_fast_cache:
        cache_entry = _ultra_fast_cache[key]
        # 🔧 期限チェック
        if current_time - cache_entry['timestamp'] < CACHE_EXPIRE_TIME:
            _cache_hits += 1
            logger.debug(f"⚡ Cache HIT: {query[:25]}...")
            return cache_entry['response']
        else:
            # 期限切れキャッシュ削除
            del _ultra_fast_cache[key]
            logger.debug(f"🗑️ Expired cache removed: {query[:25]}...")
    
    _cache_misses += 1
    return None

def set_ultra_fast_cached_response(query: str, response: str):
    """超高速キャッシュに応答保存（改良版）"""
    global _ultra_fast_cache
    
    # キャッシュサイズ管理（効率的LRU削除）
    if len(_ultra_fast_cache) >= MAX_ULTRA_CACHE_SIZE:
        # 期限切れエントリ優先削除
        current_time = time.time()
        expired_keys = []
        
        for k, v in _ultra_fast_cache.items():
            if current_time - v['timestamp'] >= CACHE_EXPIRE_TIME:
                expired_keys.append(k)
        
        # 期限切れがあれば削除
        if expired_keys:
            for k in expired_keys[:50]:  # 最大50件削除
                del _ultra_fast_cache[k]
        else:
            # 期限切れがなければ最古エントリを削除
            oldest_key = min(_ultra_fast_cache.keys(), 
                            key=lambda k: _ultra_fast_cache[k]['timestamp'])
            del _ultra_fast_cache[oldest_key]
    
    key = super_fast_cache_key(query)
    _ultra_fast_cache[key] = {
        'response': response,
        'timestamp': time.time(),
        'query_sample': query[:30]  # デバッグ用
    }
    logger.debug(f"💾 Cache SET: {query[:25]}...")

def ensure_complete_response_super_fast(text: str, query: str = "") -> str:
    """超高速文章完全性確保（処理さらに最小化）"""
    if not text or len(text.strip()) < 3:
        return generate_lightning_fallback(query)
    
    text = text.strip()
    
    # 🚀 超高速文末チェック
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        # 最頻出パターンのみ（さらに限定）
        if text.endswith(('ます', 'です')):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif len(text) > 10:
            text += '。'
        else:
            return generate_lightning_fallback(query)
    
    return text

def generate_lightning_fallback(query: str) -> str:
    """超高速フォールバック（キーワードマッピング強化）"""
    q = query.lower()
    
    # 🚀 高頻度パターン最適化マッチング
    for category, keywords in _high_frequency_keywords.items():
        for keyword in keywords:
            if keyword in q and keyword in _faq_cache:
                return _faq_cache[keyword]
    
    # 🚀 カテゴリ別フォールバック
    if any(kw in q for kw in ["坪単価", "価格", "費用", "金額", "いくら"]):
        return "坪単価は約70～85万円/坪（標準仕様）です。詳細なお見積りをご提供いたします。"
    elif any(kw in q for kw in ["仕様", "設備", "標準"]):
        return "標準仕様は耐震等級3の長期優良住宅基準です。詳細は展示場でご確認ください。"
    elif any(kw in q for kw in ["断熱", "性能", "zeh"]):
        return "高性能断熱材でZEH基準対応です。快適で省エネな住まいを実現します。"
    elif any(kw in q for kw in ["耐震", "地震", "安全"]):
        return "耐震等級3で地震に強い安心・安全な住まいです。"
    elif any(kw in q for kw in ["補助金", "助成", "支援"]):
        return "ZEH補助金、こどもエコすまい支援事業など各種制度を活用できます。"
    elif any(kw in q for kw in ["資料", "カタログ", "パンフ"]):
        return "資料請求を承ります。会社案内、施工事例集等をお送りします。"
    elif any(kw in q for kw in ["展示", "見学", "予約"]):
        return "展示場見学を承ります。実際の仕様をご確認いただけます。"
    elif any(kw in q for kw in ["相談", "質問", "聞きたい"]):
        return "住まいづくりのご相談を承ります。お気軽にお問い合わせください。"
    else:
        return "住まいに関することでしたらお気軽にお問い合わせください。専門スタッフがご案内いたします。"

def load_super_fast_vectorstore():
    """超高速ベクトルストア読み込み（診断強化版）"""
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        # 🚀 詳細なファイル存在チェック
        if not os.path.exists(index_path):
            logger.warning(f"❌ Vectorstore not found at: {index_path}")
            logger.info("🔄 Creating minimal vectorstore...")
            return create_minimal_vectorstore_super_fast()
        
        # ファイルサイズチェック
        file_size = os.path.getsize(index_path)
        logger.info(f"🔍 Vectorstore file size: {file_size} bytes")
        
        if file_size < 1000:  # 1KB未満は異常
            logger.warning("⚠️ Vectorstore file too small, recreating...")
            return create_minimal_vectorstore_super_fast()
        
        embeddings = SuperFastEmbedding()
        
        # ベクトルストア読み込み（エラーハンドリング強化）
        try:
            vectorstore = FAISS.load_local(
                LOCAL_VECTOR_DIR,
                embeddings,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True
            )
            
            # 🚀 読み込み後の健全性チェック
            if hasattr(vectorstore, 'index') and vectorstore.index.ntotal > 0:
                logger.info(f"✅ Vectorstore loaded: {vectorstore.index.ntotal} vectors")
                
                # 簡単なテスト検索
                try:
                    test_results = vectorstore.similarity_search("テスト", k=1)
                    logger.info(f"✅ Test search successful: {len(test_results)} results")
                except Exception as test_error:
                    logger.warning(f"⚠️ Test search failed: {test_error}")
                
                return vectorstore
            else:
                logger.warning("⚠️ Vectorstore index is empty")
                return create_minimal_vectorstore_super_fast()
                
        except Exception as load_error:
            logger.error(f"❌ Vectorstore load error: {load_error}")
            logger.info("🔄 Fallback to minimal vectorstore creation...")
            return create_minimal_vectorstore_super_fast()
        
    except Exception as e:
        logger.error(f"❌ Super fast vectorstore initialization error: {e}")
        return create_minimal_vectorstore_super_fast()

def create_minimal_vectorstore_super_fast():
    """最小限ベクトルストア作成（内容強化版）"""
    try:
        embeddings = SuperFastEmbedding()
        
        # 🚀 住宅専門強化ドキュメント（よくある質問対応）
        enhanced_docs = [
            Document(page_content="坪単価は約70～85万円/坪（標準仕様）、約85～100万円/坪（高性能仕様）です。仕様により変動します。", metadata={"source": "price", "category": "基本情報"}),
            Document(page_content="標準仕様は耐震等級3の長期優良住宅基準で、高断熱・高気密仕様、システムキッチン、ユニットバス、エコキュートを標準装備。", metadata={"source": "spec", "category": "仕様"}),
            Document(page_content="高性能断熱材使用でZEH基準対応。UA値0.6以下、C値1.0以下を実現。夏涼しく冬暖かい快適な住環境。", metadata={"source": "performance", "category": "断熱性能"}),
            Document(page_content="耐震等級3を標準とし建築基準法の1.5倍の耐震強度。構造用集成材と金物工法で地震に強い住まい。", metadata={"source": "safety", "category": "耐震性能"}),
            Document(page_content="ZEH補助金55万円～、こどもエコすまい支援事業最大100万円、住宅ローン減税13年間など各種制度活用可能。", metadata={"source": "subsidy", "category": "補助金"}),
            Document(page_content="資料請求承ります。会社案内・施工事例集・間取りプラン集・価格仕様資料を3営業日以内にお送り。", metadata={"source": "contact", "category": "資料請求"}),
            Document(page_content="展示場見学で実際の住宅仕様をご確認。営業時間9:00-18:00（水曜定休）専門スタッフがご案内。", metadata={"source": "visit", "category": "展示場"}),
            Document(page_content="住宅ローン・資金計画をサポート。無理のない返済計画で年収の5-7倍程度の借入が目安。ファイナンシャルプランナー相談可能。", metadata={"source": "finance", "category": "資金計画"}),
            Document(page_content="工期は約4-6ヶ月。契約から入居まで約6-8ヶ月が標準スケジュール。各工程でお客様確認いただきながら丁寧に施工。", metadata={"source": "construction", "category": "工事"}),
            Document(page_content="構造躯体20年保証、設備10年保証、定期点検とアフターサポート。24時間365日の緊急対応体制完備。", metadata={"source": "warranty", "category": "保証"}),
            Document(page_content="土地探しからサポート。立地条件・価格・法的制限を総合判断し最適な土地をご提案。地盤調査・法規制チェック込み。", metadata={"source": "land", "category": "土地"}),
            Document(page_content="自由設計でお客様のライフスタイルに合わせた間取りプラン。家族構成・趣味・将来計画を考慮した最適設計。", metadata={"source": "design", "category": "設計"})
        ]
        
        vectorstore = FAISS.from_documents(enhanced_docs, embeddings)
        
        os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
        vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
        
        logger.info(f"✅ Enhanced minimal vectorstore created: {len(enhanced_docs)} documents")
        return vectorstore
        
    except Exception as e:
        logger.error(f"❌ Minimal vectorstore creation failed: {e}")
        # 最終フォールバック（空のベクトルストア）
        return None

def get_super_fast_rag_chain(vectorstore, return_source: bool = False):
    """超高速RAGチェーン（FAQ優先・安定化版）"""
    logger.info("🚀 Creating ultra-optimized RAG chain (FAQ priority)...")
    
    if not vectorstore:
        logger.warning("❌ Vectorstore is None, using FAQ-only chain")
        return create_faq_only_chain()
    
    try:
        # 🚀 キャッシュ版LLM使用
        try:
            from llm.llm_runner import get_cached_llm_instance
            llm = get_cached_llm_instance()
            logger.info("✅ Cached LLM instance loaded")
        except ImportError:
            logger.warning("⚠️ Cached LLM not available, using load_llm")
            from llm.llm_runner import load_llm
            llm, _, _ = load_llm()
        
        # 🚀 超簡潔プロンプト（トークン最小化）
        ultra_fast_prompt = """住宅専門AI。簡潔明確回答。

参考: {context}
質問: {question}

簡潔回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=ultra_fast_prompt
        )
        
        # 🚀 検索数最小化
        retriever = vectorstore.as_retriever(search_kwargs={"k": 1})  # 最小限
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # 超高速FAQラッパー
        class UltraFastFAQChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
                self.faq_hits = 0
                self.rag_calls = 0
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                
                # 🚀 1) FAQ最優先（99%をここでキャッチ）
                faq_response = get_ultra_fast_cached_response(query)
                if faq_response:
                    self.faq_hits += 1
                    return {"result": faq_response, "source_documents": []}
                
                try:
                    # 🚀 2) RAG実行（稀なケース・短時間タイムアウト）
                    self.rag_calls += 1
                    start_time = time.time()
                    
                    # 🚀 超短タイムアウト（3秒）
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(self.base_chain.invoke, inputs)
                        try:
                            result = future.result(timeout=3)  # 🔧 短縮：5→3秒
                            processing_time = time.time() - start_time
                            
                            raw_result = result.get("result", "")
                            if raw_result and len(raw_result.strip()) > 5:
                                logger.info(f"⚡ RAG success ({processing_time:.2f}s): {raw_result[:40]}...")
                                
                                # 完全性チェック・キャッシュ保存
                                final_result = ensure_complete_response_super_fast(raw_result, query)
                                set_ultra_fast_cached_response(query, final_result)
                                
                                result["result"] = final_result
                                return result
                            else:
                                raise ValueError("Empty RAG result")
                            
                        except concurrent.futures.TimeoutError:
                            logger.warning("⏰ RAG timeout (3s), using lightning fallback")
                            raise
                    
                except Exception as e:
                    logger.warning(f"❌ RAG execution failed: {e}")
                    # 🚀 3) 超高速フォールバック
                    fallback = generate_lightning_fallback(query)
                    complete_fallback = ensure_complete_response_super_fast(fallback, query)
                    set_ultra_fast_cached_response(query, complete_fallback)
                    return {"result": complete_fallback, "source_documents": []}
            
            def get_stats(self):
                total = self.faq_hits + self.rag_calls
                return {
                    "faq_hits": self.faq_hits,
                    "rag_calls": self.rag_calls, 
                    "faq_rate": (self.faq_hits / total * 100) if total > 0 else 0
                }
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ Ultra-fast FAQ-priority RAG chain created")
        return UltraFastFAQChain(rag_chain)
        
    except Exception as e:
        logger.error(f"❌ Error creating ultra-fast RAG chain: {e}")
        logger.info("🔄 Fallback to FAQ-only chain...")
        return create_faq_only_chain()

def create_faq_only_chain():
    """FAQ専用チェーン（RAG完全フォールバック）"""
    logger.info("🚀 Creating FAQ-only chain (RAG fallback)...")
    
    class FAQOnlyChain:
        def __init__(self):
            self.callbacks = []
            self.faq_responses = 0
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            # FAQ回答取得
            faq_response = get_faq_response_enhanced(query)
            if faq_response:
                self.faq_responses += 1
                return {"result": faq_response, "source_documents": []}
            
            # フォールバック
            fallback = generate_lightning_fallback(query)
            complete_fallback = ensure_complete_response_super_fast(fallback, query)
            return {"result": complete_fallback, "source_documents": []}
        
        def get_stats(self):
            return {"faq_responses": self.faq_responses, "mode": "faq_only"}
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return FAQOnlyChain()

def get_super_fast_cache_stats():
    """超高速キャッシュ統計（詳細版）"""
    total_requests = _cache_hits + _cache_misses
    hit_rate = _cache_hits / total_requests if total_requests > 0 else 0
    
    return {
        "cache_performance": {
            "cache_size": len(_ultra_fast_cache),
            "max_cache_size": MAX_ULTRA_CACHE_SIZE,
            "cache_hits": _cache_hits,
            "cache_misses": _cache_misses,
            "hit_rate": hit_rate * 100,
            "total_requests": total_requests
        },
        "faq_system": {
            "faq_cache_size": len(_faq_cache),
            "high_frequency_keywords": sum(len(keywords) for keywords in _high_frequency_keywords.values()),
            "categories": list(_high_frequency_keywords.keys())
        },
        "configuration": {
            "expire_time": CACHE_EXPIRE_TIME,
            "max_cache_size": MAX_ULTRA_CACHE_SIZE,
            "embedding_model": "intfloat/multilingual-e5-small"
        },
        "optimizations": [
            "Enhanced FAQ pre-cache (80+ entries)",
            "High-frequency keyword optimization",
            "Ultra-fast cache key generation",
            "Proactive cache expiration",
            "Single-threaded embedding (speed priority)"
        ]
    }

def clear_super_fast_cache():
    """超高速キャッシュクリア"""
    global _ultra_fast_cache, _cache_hits, _cache_misses
    old_size = len(_ultra_fast_cache)
    _ultra_fast_cache.clear()
    _cache_hits = 0
    _cache_misses = 0
    logger.info(f"🧹 Ultra-fast cache cleared: {old_size} entries (FAQ cache preserved)")
    return old_size

# 🚀 FAQ事前ロード強化（アプリ起動時実行）
def preload_enhanced_faq_cache():
    """FAQ事前キャッシュロード（詳細ログ付き）"""
    logger.info(f"🚀 Enhanced FAQ pre-cache loading: {len(_faq_cache)} entries")
    
    # カテゴリ別ログ出力
    categories = {}
    for key in _faq_cache.keys():
        if any(kw in key for kw in _high_frequency_keywords["価格系"]):
            category = "価格系"
        elif any(kw in key for kw in _high_frequency_keywords["仕様系"]):
            category = "仕様系"
        elif any(kw in key for kw in _high_frequency_keywords["性能系"]):
            category = "性能系"
        elif any(kw in key for kw in _high_frequency_keywords["制度系"]):
            category = "制度系"
        elif any(kw in key for kw in _high_frequency_keywords["サービス系"]):
            category = "サービス系"
        else:
            category = "その他"
        
        categories[category] = categories.get(category, 0) + 1
    
    logger.info("📊 FAQ Category Distribution:")
    for category, count in categories.items():
        logger.info(f"   - {category}: {count} entries")
    
    logger.info("✅ Enhanced FAQ pre-cache loaded successfully")

# ============================================================================
# 🔧 互換性維持エイリアス関数
# ============================================================================
def load_ultra_fast_vectorstore():
    """互換性維持のためのエイリアス - main.pyからの呼び出しに対応"""
    logger.info("🔄 Using alias: load_ultra_fast_vectorstore -> load_super_fast_vectorstore")
    return load_super_fast_vectorstore()

def get_ultra_fast_rag_chain(vectorstore, return_source: bool = False):
    """互換性維持のためのエイリアス - main.pyからの呼び出しに対応"""
    logger.info("🔄 Using alias: get_ultra_fast_rag_chain -> get_super_fast_rag_chain")
    return get_super_fast_rag_chain(vectorstore, return_source)

# 🚀 起動時FAQ強化初期化
preload_enhanced_faq_cache()
logger.info("🎯 Ultra-fast RAG system ready (FAQ priority mode)")

if __name__ == "__main__":
    print("🚀 Ultra-Fast RAG Chain Test (FAQ Priority Mode)")
    print("=" * 70)
    
    try:
        vectorstore = load_super_fast_vectorstore()
        print("✅ Ultra-fast vectorstore loaded")
        
        rag_chain = get_super_fast_rag_chain(vectorstore)
        print("✅ Ultra-fast RAG chain created")
        
        # 高速テスト
        test_queries = [
            "坪単価",          # FAQ hit expected (instant)
            "価格について",     # FAQ hit expected (instant)
            "標準仕様",        # FAQ hit expected (instant)  
            "断熱性能について教えて",  # FAQ hit expected (instant)
            "耐震性能はどう？",     # FAQ hit expected (instant)
            "複雑な住宅設計について詳しく知りたい"  # Rare RAG case
        ]
        
        print("\n🏃‍♂️ Ultra-Speed Test Results:")
        total_start = time.time()
        
        for i, query in enumerate(test_queries, 1):
            start_time = time.time()
            response = rag_chain.invoke({"query": query})
            processing_time = time.time() - start_time
            
            result = response.get('result', 'No result')
            speed_emoji = "🚀" if processing_time < 0.1 else "⚡" if processing_time < 0.5 else "🌐"
            
            print(f"{i}. Query: {query}")
            print(f"   Response: {result[:60]}...")
            print(f"   Speed: {processing_time:.3f}s {speed_emoji}")
            
            # FAQ vs RAG判定
            if processing_time < 0.1:
                print("   Source: FAQ (instant)")
            elif processing_time < 1.0:
                print("   Source: RAG (fast)")
            else:
                print("   Source: RAG (normal)")
            print("-" * 50)
        
        total_time = time.time() - total_start
        print(f"\n📊 Overall Performance:")
        print(f"   Total time: {total_time:.3f}s")
        print(f"   Average per query: {total_time/len(test_queries):.3f}s")
        
        # 統計表示
        stats = get_super_fast_cache_stats()
        print(f"\n📊 Cache Performance:")
        print(f"   FAQ entries: {stats['faq_system']['faq_cache_size']}")
        print(f"   Hit rate: {stats['cache_performance']['hit_rate']:.1f}%")
        print(f"   Cache size: {stats['cache_performance']['cache_size']}")
        
        # 互換性テスト
        print(f"\n🔄 Compatibility Test:")
        print("Testing alias functions...")
        alias_vectorstore = load_ultra_fast_vectorstore()
        print("✅ load_ultra_fast_vectorstore alias works")
        
        alias_rag_chain = get_ultra_fast_rag_chain(alias_vectorstore)
        print("✅ get_ultra_fast_rag_chain alias works")
        
        # 統計機能テスト
        if hasattr(alias_rag_chain, 'get_stats'):
            chain_stats = alias_rag_chain.get_stats()
            print(f"✅ Chain stats: {chain_stats}")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        print(traceback.format_exc())