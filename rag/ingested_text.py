# rag/ingested_text.py - 完全版（改良されたRAG回答生成システム）

import os
import logging
import sys
import traceback
import re
from pathlib import Path

from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from langchain.schema import Document

# 環境変数から GCS バケット名を取得
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
GCS_VEC_DIR = "vectorstore"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ローカルでの一時ベクトルストアフォルダ
LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# === GCS関連の関数 ===
def _get_gcs_client():
    try:
        from google.cloud import storage
        return storage.Client()
    except Exception as e:
        logger.warning(f"GCS client creation failed: {e}")
        return None

def upload_vectorstore_to_gcs(local_dir: str):
    """ベクトルストアをGCSにアップロード"""
    if not GCS_BUCKET:
        logger.info("GCS_BUCKET_NAME not set, skipping upload")
        return
    
    try:
        client = _get_gcs_client()
        if not client:
            return
            
        bucket = client.bucket(GCS_BUCKET)
        
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            local_path = os.path.join(local_dir, fname)
            if os.path.exists(local_path):
                blob_path = f"{GCS_VEC_DIR}/{fname}"
                blob = bucket.blob(blob_path)
                blob.upload_from_filename(local_path)
                logger.info(f"✅ Uploaded to GCS: gs://{GCS_BUCKET}/{blob_path}")
    except Exception as e:
        logger.error(f"GCS upload error: {e}")

def download_vectorstore_from_gcs(local_dir: str):
    """GCSからベクトルストアをダウンロード"""
    if not GCS_BUCKET:
        logger.info("GCS_BUCKET_NAME not set, skipping download")
        return False
    
    try:
        client = _get_gcs_client()
        if not client:
            return False
            
        bucket = client.bucket(GCS_BUCKET)
        os.makedirs(local_dir, exist_ok=True)
        
        downloaded = False
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            blob_path = f"{GCS_VEC_DIR}/{fname}"
            blob = bucket.blob(blob_path)
            local_path = os.path.join(local_dir, fname)
            
            if blob.exists():
                blob.download_to_filename(local_path)
                logger.info(f"✅ Downloaded from GCS: {blob_path}")
                downloaded = True
                
        return downloaded
    except Exception as e:
        logger.error(f"GCS download error: {e}")
        return False

# === カスタム埋め込みクラス ===
class MyEmbedding(Embeddings):
    """カスタム埋め込みクラス"""
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)
    
    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=False).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text).tolist()

# === 自然な回答生成システム ===
def create_natural_response(raw_response: str, query: str) -> str:
    """自然で完全な回答を生成"""
    
    if not raw_response or len(raw_response.strip()) < 3:
        return generate_fallback_response(query)
    
    # 1. 基本的なクリーンアップ
    cleaned = clean_and_format_response(raw_response)
    
    # 2. 質問の種類に応じた自然な回答生成
    if "坪単価" in query or "価格" in query or "費用" in query:
        if any(keyword in cleaned for keyword in ["坪単価", "万円", "価格", "円"]):
            # 価格情報がある場合はそのまま使用
            return format_price_response(cleaned)
        else:
            # 価格情報がない場合の自然な回答
            return "坪単価については、お客様のご希望される仕様や設備によって異なります。標準仕様では約70〜85万円/坪が目安となりますが、詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。"
    
    elif "仕様" in query or "標準" in query:
        if len(cleaned) > 20:
            return format_spec_response(cleaned)
        else:
            return "標準仕様については、耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。"
    
    elif "建ぺい率" in query or "容積率" in query:
        if len(cleaned) > 20:
            return cleaned
        else:
            return "建ぺい率は土地に対して建てられる建物の面積の割合、容積率は土地に対する建物の延床面積の割合を指します。地域によって制限が異なりますので、具体的な数値については土地の詳細をお聞かせください。"
    
    elif "ZEH" in query.upper() or "ゼッチ" in query:
        if len(cleaned) > 20:
            return cleaned
        else:
            return "ZEH（ゼッチ）とは、Net Zero Energy Houseの略で、年間の一次エネルギー消費量が正味ゼロとなる住宅です。太陽光発電システムと高断熱性能により、エネルギーを自給自足できる住宅として注目されています。"
    
    elif "断熱" in query or "性能" in query:
        if len(cleaned) > 20:
            return cleaned
        else:
            return "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。詳しい性能値や仕様については、展示場でご確認いただけます。"
    
    elif "設備" in query or "キッチン" in query or "お風呂" in query:
        if len(cleaned) > 20:
            return cleaned
        else:
            return "住宅設備については、お客様のライフスタイルに合わせて最適なものをご提案いたします。キッチンやバスルームなど、詳細な設備仕様は展示場でご確認いただけます。"
    
    else:
        # その他の質問
        if len(cleaned) > 15:
            return ensure_complete_sentence(cleaned)
        else:
            return generate_fallback_response(query)

def format_price_response(content: str) -> str:
    """価格関連の回答をフォーマット"""
    # 価格情報を自然な文章に整形
    if "坪単価" in content:
        return f"坪単価についてご案内いたします。{content}仕様や設備によって変動いたしますので、詳細なお見積りをご希望の場合は、お気軽にお問い合わせください。"
    elif "価格" in content or "費用" in content:
        return f"価格についてご説明いたします。{content}お客様のご要望に応じて詳細なお見積りをご提供いたします。"
    else:
        return content

def format_spec_response(content: str) -> str:
    """仕様関連の回答をフォーマット"""
    return f"住宅の仕様についてご説明いたします。{content}より詳しい仕様については、展示場でご確認いただけます。"

def ensure_complete_sentence(text: str) -> str:
    """文章の完全性を確保"""
    # 文末が途切れている場合の処理
    if not text.endswith(('。', '！', '？', '.')):
        if text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith('です') or text.endswith('ます'):
            text += '。'
        elif text.endswith('た') or text.endswith('る'):
            text += '。'
        else:
            text += '。'
    
    return text

def generate_fallback_response(query: str) -> str:
    """フォールバック回答の生成"""
    if "坪単価" in query or "価格" in query:
        return "坪単価については、お客様のご要望や仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
    elif "仕様" in query:
        return "住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
    elif "設備" in query:
        return "住宅設備について詳しくご案内いたします。お客様のご要望に合わせて最適な設備をご提案いたします。"
    else:
        return "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"

def clean_and_format_response(raw_response: str) -> str:
    """回答をクリーンアップして自然な形式に変換（完全修正版）"""
    
    if not raw_response or len(raw_response.strip()) < 3:
        return "申し訳ございません。お尋ねの内容について詳細な情報が見つかりませんでした。"
    
    # 1. デバッグ情報と構造化データの完全削除
    debug_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"【質問】\s*",
        r"出典[:：]\s*[^\n]*",
        r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
        r"\([pP]\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
        r"^質問[:：]\s*",
        r"^回答[:：]\s*",
        r"出典[:：][^\n]*",
        r"\.pdf\s*\([pP]\d+\)",
        r"\.pdf\s+\(p\d+\)",
        r"参考文献[:：][^\n]*",
        r"ソース[:：][^\n]*",
        r"情報源[:：][^\n]*",
    ]
    
    cleaned = raw_response
    for pattern in debug_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 2. 縦書き文字の完全修正（改良版）
    lines = cleaned.split('\n')
    horizontal_content = []
    vertical_buffer = []
    
    for line in lines:
        line = line.strip()
        
        # 空行で区切り
        if not line:
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:  # 意味のある長さのもののみ
                    horizontal_content.append(combined)
                vertical_buffer = []
            continue
        
        # 1文字または2文字の短い行は縦書きとして蓄積
        if len(line) <= 2:
            vertical_buffer.append(line)
        else:
            # 通常の文章
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:
                    horizontal_content.append(combined)
                vertical_buffer = []
            horizontal_content.append(line)
    
    # 最後のバッファを処理
    if vertical_buffer:
        combined = ''.join(vertical_buffer)
        if len(combined) > 5:
            horizontal_content.append(combined)
    
    # 3. 重複排除と内容の最適化
    if horizontal_content:
        unique_content = []
        seen_normalized = set()
        
        for content in horizontal_content:
            if len(content) < 10:  # 短すぎる内容はスキップ
                continue
                
            # 正規化（句読点と空白を除去）
            normalized = re.sub(r'[。、\s]', '', content.lower())
            
            # 重複チェック
            is_duplicate = False
            for seen in seen_normalized:
                similarity = len(set(normalized) & set(seen)) / max(len(set(normalized)), len(set(seen)), 1)
                if similarity > 0.8:  # 80%以上似ている場合は重複とみなす
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                seen_normalized.add(normalized)
                unique_content.append(content)
        
        # 最も情報量の多い内容を選択
        if unique_content:
            # 長さと質を考慮して最適な回答を選択
            best_content = max(unique_content, key=lambda x: len(x) + x.count('。') * 10)
            result = best_content
        else:
            result = horizontal_content[0] if horizontal_content else ""
    else:
        result = "申し訳ございません。関連する情報が見つかりませんでした。"
    
    # 4. 最終的な文章の整形
    if result:
        # 余分な空白の削除
        result = re.sub(r'\s+', ' ', result)
        # 句読点の後の空白を削除
        result = re.sub(r'([。！？])\s*', r'\1', result)
        result = result.strip()
        
        # 文末の調整
        if result and not result.endswith(('。', '！', '？', '.')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            elif not result.endswith('.'):
                result += '。'
    
    # 5. 品質チェック
    if not result or len(result) < 10:
        result = "申し訳ございません。お尋ねの内容について、詳しい情報をお答えできませんでした。"
    
    return result

# === ベクトルストア管理 ===
def create_initial_vectorstore():
    """初期ベクトルストアを作成"""
    logger.info("Creating initial vectorstore...")
    
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")
    
    # 初期ドキュメント
    initial_docs = [
        Document(
            page_content="このシステムはRAG（Retrieval-Augmented Generation）を使用しています。PDFをアップロードすることで、その内容について質問できます。",
            metadata={"source": "システム初期化", "page": 1}
        ),
        Document(
            page_content="RAGは検索と生成を組み合わせたAI技術です。アップロードされた文書から関連情報を検索し、AIが回答を生成します。",
            metadata={"source": "システム初期化", "page": 2}
        ),
        Document(
            page_content="PDFファイルは自動的にテキスト化され、ベクトルデータベースに保存されます。質問時には関連する部分が検索されます。",
            metadata={"source": "システム初期化", "page": 3}
        )
    ]
    
    vectorstore = FAISS.from_documents(initial_docs, embeddings)
    
    # ローカルに保存
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    
    # GCSにアップロード
    upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
    
    logger.info("✅ Initial vectorstore created")
    return vectorstore

def load_vectorstore():
    """ベクトルストアを読み込み"""
    try:
        # GCSからダウンロードを試みる
        downloaded = download_vectorstore_from_gcs(LOCAL_VECTOR_DIR)
        
        # ローカルファイルの存在確認
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        if not os.path.exists(index_path):
            logger.info("Vectorstore not found, creating initial one...")
            return create_initial_vectorstore()
        
        # 既存のベクトルストアを読み込み
        embeddings = MyEmbedding("intfloat/multilingual-e5-small")
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR,
            embeddings,
            index_name=INDEX_NAME,
            allow_dangerous_deserialization=True
        )
        
        logger.info("✅ Vectorstore loaded successfully")
        return vectorstore
        
    except Exception as e:
        logger.error(f"Error loading vectorstore: {e}")
        # エラー時は初期ベクトルストアを作成
        return create_initial_vectorstore()

def ingest_pdf_to_vectorstore(pdf_path: str):
    """PDFをベクトルストアに追加"""
    try:
        # PDF読み込み
        loader = PyPDFLoader(pdf_path)
        docs = loader.load()
        
        # テキスト分割
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=["\n\n", "\n", "。", "！", "？", "、", " ", ""]
        )
        documents = splitter.split_documents(docs)
        
        # 埋め込みモデル
        embeddings = MyEmbedding("intfloat/multilingual-e5-small")
        
        # 既存のベクトルストアを読み込み
        os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        if os.path.exists(index_path):
            vectorstore = FAISS.load_local(
                LOCAL_VECTOR_DIR,
                embeddings,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True
            )
            vectorstore.add_documents(documents)
        else:
            vectorstore = FAISS.from_documents(documents, embeddings)
        
        # 保存
        vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
        logger.info(f"✅ Added {len(documents)} documents from {os.path.basename(pdf_path)}")
        
        # GCSにアップロード
        upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
        
        return len(documents)
        
    except Exception as e:
        logger.error(f"Error ingesting PDF: {e}")
        raise

# === 改良されたRAGチェーン ===
def get_rag_chain(vectorstore, return_source: bool = True):
    """改良されたRAGチェーンを作成"""
    logger.info("Creating improved RAG chain...")
    
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # より自然な日本語プロンプト
        prompt_str = """あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の参考情報を基に、ユーザーの質問に対して自然で完全な回答を提供してください。

【重要な指示】
- 自然で親しみやすい日本語で回答する
- 文章は必ず完結させる（途中で切れないようにする）
- 専門用語は分かりやすく説明する
- 具体的で実用的な情報を含める
- 出典情報や検索結果の詳細は含めない
- 回答は200-500文字程度でまとめる
- 「申し訳ございません」から始めない
- 質問に直接答える

【参考情報】
{context}

【質問】
{question}

上記の参考情報を基に、質問に対して完全で自然な回答をお願いします："""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=prompt_str
        )
        
        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # カスタムラッパーで自然な回答生成
        class NaturalResponseChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                
                try:
                    # 元のチェーンを実行
                    result = self.base_chain.invoke(inputs)
                    raw_result = result.get("result", "")
                    
                    logger.info(f"Raw RAG result: {raw_result[:150]}...")
                    
                    # 自然な回答に変換
                    natural_result = create_natural_response(raw_result, query)
                    
                    logger.info(f"Natural result: {natural_result[:150]}...")
                    
                    result["result"] = natural_result
                    return result
                    
                except Exception as e:
                    logger.error(f"Error in natural response generation: {e}")
                    logger.error(traceback.format_exc())
                    return {
                        "result": generate_fallback_response(query),
                        "source_documents": []
                    }
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ Improved RAG chain created successfully")
        return NaturalResponseChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating improved RAG chain: {e}")
        logger.error(traceback.format_exc())
        return create_fallback_chain(vectorstore)

def create_fallback_chain(vectorstore):
    """フォールバック用のシンプルチェーン"""
    logger.info("Creating fallback chain...")
    
    class FallbackChain:
        def __init__(self, vectorstore):
            self.vectorstore = vectorstore
            self.retriever = vectorstore.as_retriever() if vectorstore else None
            self.callbacks = []
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            try:
                if not self.retriever:
                    return {
                        "result": generate_fallback_response(query),
                        "source_documents": []
                    }
                
                docs = self.retriever.invoke(query)
                
                if docs:
                    # 最も関連性の高いドキュメントから情報を抽出
                    best_docs = docs[:2]  # 上位2件を使用
                    combined_content = " ".join([doc.page_content for doc in best_docs])
                    
                    # LLMが利用可能な場合は使用
                    try:
                        from llm.llm_runner import load_llm
                        llm, _, _ = load_llm()
                        
                        prompt = f"""以下の情報を参考に、質問に自然で分かりやすく答えてください。

参考情報: {combined_content[:800]}

質問: {query}

自然で完全な日本語で回答し、文章は必ず最後まで完結させてください："""
                        
                        response = llm.invoke(prompt)
                        llm_result = response.content if hasattr(response, 'content') else str(response)
                        
                        # LLM結果もクリーンアップ
                        natural_result = create_natural_response(llm_result, query)
                        
                    except Exception as llm_error:
                        logger.error(f"LLM fallback error: {llm_error}")
                        # LLMが失敗した場合は直接コンテンツを使用
                        natural_result = create_natural_response(combined_content, query)
                    
                    return {
                        "result": natural_result,
                        "source_documents": docs[:3]
                    }
                else:
                    return {
                        "result": generate_fallback_response(query),
                        "source_documents": []
                    }
                    
            except Exception as e:
                logger.error(f"Fallback chain error: {e}")
                return {
                    "result": "申し訳ございません。システムに一時的な問題が発生しています。しばらくしてから再度お試しください。",
                    "source_documents": []
                }
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return FallbackChain(vectorstore)

# === 高度な回答生成機能 ===
def generate_contextual_response(query: str, context: str) -> str:
    """コンテキストを基にした高度な回答生成"""
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # コンテキストベースの詳細プロンプト
        prompt = f"""あなたは住宅・建築の専門アドバイザーです。
以下のコンテキスト情報を基に、ユーザーの質問に対して自然で完全な回答を生成してください。

【重要なルール】
1. 自然で親しみやすい日本語で回答する
2. 文章は必ず最後まで完結させる
3. 専門用語は分かりやすく説明する
4. 具体的で実用的な情報を提供する
5. 「申し訳ございません」から始めない
6. 200-400文字程度でまとめる

【コンテキスト情報】
{context[:1000]}

【ユーザーの質問】
{query}

【回答】"""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, 'content') else str(response)
        
        # 結果をクリーンアップ
        cleaned_result = clean_and_format_response(result)
        return ensure_complete_sentence(cleaned_result)
        
    except Exception as e:
        logger.error(f"Error in contextual response generation: {e}")
        return generate_fallback_response(query)

# === ユーティリティ関数 ===
def get_openai_api_key():
    """OpenAI APIキー取得（後方互換性のため残す）"""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        logger.error("OPENAI_API_KEY not set!")
    return key

def health_check_vectorstore() -> dict:
    """ベクトルストアの健康状態をチェック"""
    try:
        vectorstore = load_vectorstore()
        
        # テスト検索
        test_results = vectorstore.similarity_search("テスト", k=1)
        
        return {
            "status": "healthy",
            "vectorstore_loaded": True,
            "test_search_results": len(test_results),
            "local_vector_dir": LOCAL_VECTOR_DIR,
            "index_name": INDEX_NAME
        }
        
    except Exception as e:
        logger.error(f"Vectorstore health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "vectorstore_loaded": False
        }

def get_vectorstore_info() -> dict:
    """ベクトルストアの情報を取得"""
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        pkl_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.pkl")
        
        return {
            "local_vector_dir": LOCAL_VECTOR_DIR,
            "index_name": INDEX_NAME,
            "faiss_file_exists": os.path.exists(index_path),
            "pkl_file_exists": os.path.exists(pkl_path),
            "faiss_file_size": os.path.getsize(index_path) if os.path.exists(index_path) else 0,
            "gcs_bucket": GCS_BUCKET or "Not configured"
        }
        
    except Exception as e:
        logger.error(f"Error getting vectorstore info: {e}")
        return {"error": str(e)}

# === メイン実行部分（テスト用） ===
if __name__ == "__main__":
    print("🧪 RAG Ingested Text Test")
    print("=" * 50)
    
    # ベクトルストア情報を表示
    info = get_vectorstore_info()
    print("📋 Vectorstore Information:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    
    print("\n🔍 Health Check:")
    health = health_check_vectorstore()
    for key, value in health.items():
        print(f"  {key}: {value}")
    
    if health["status"] == "healthy":
        print("\n✅ Vectorstore is working correctly!")
        
        # サンプルRAGテスト
        print("\n💬 Sample RAG Test:")
        try:
            vectorstore = load_vectorstore()
            rag_chain = get_rag_chain(vectorstore)
            
            test_query = "住宅の標準仕様について教えてください"
            response = rag_chain.invoke({"query": test_query})
            result = response.get("result", "No result")
            
            print(f"Query: {test_query}")
            print(f"Response: {result[:300]}...")
            
        except Exception as e:
            print(f"RAG test error: {e}")
    else:
        print("\n❌ Vectorstore is not working properly!")
        
        # 初期化を試行
        print("\n🔄 Attempting to create initial vectorstore...")
        try:
            vectorstore = create_initial_vectorstore()
            print("✅ Initial vectorstore created successfully!")
        except Exception as e:
            print(f"❌ Failed to create initial vectorstore: {e}")