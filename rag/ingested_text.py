# rag/ingested_text.py - 改善版（自然な回答生成）

import os
import logging
import sys
import traceback
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

# GCS関連の関数（既存のまま）
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

class MyEmbedding(Embeddings):
    """カスタム埋め込みクラス"""
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)
    
    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=False).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text).tolist()

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

def clean_and_format_response(raw_response: str) -> str:
    """回答をクリーンアップして自然な形式に変換（完全修正版）"""
    import re
    
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
    ]
    
    cleaned = raw_response
    for pattern in debug_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 2. 縦書き文字の完全修正
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
        
        # 1文字の行は縦書きとして蓄積
        if len(line) == 1:
            vertical_buffer.append(line)
        elif len(line) <= 3:
            # 2-3文字の短い行も蓄積対象
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
        # 重複する内容を除去
        unique_content = []
        seen_normalized = set()
        
        for content in horizontal_content:
            # 正規化（句読点と空白を除去）
            normalized = re.sub(r'[。、\s]', '', content.lower())
            
            # 短すぎる内容はスキップ
            if len(content) < 10:
                continue
            
            # 重複チェック
            is_duplicate = False
            for seen in seen_normalized:
                if normalized in seen or seen in normalized:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                seen_normalized.add(normalized)
                unique_content.append(content)
        
        # 最も情報量の多い内容を選択
        if unique_content:
            # 長さと内容の質を考慮して最適な回答を選択
            best_content = max(unique_content, key=lambda x: len(x))
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
        # 文末の調整
        result = result.strip()
        
        # 文末に句読点がない場合は追加
        if result and not result.endswith(('。', '！', '？', '.')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            else:
                result += '。'
    
    # 5. 品質チェック
    if not result or len(result) < 10:
        result = "申し訳ございません。お尋ねの内容について、詳しい情報をお答えできませんでした。"
    
    return result

def get_rag_chain(vectorstore, return_source: bool = True):
    """RAGチェーンを作成（完全修正版）"""
    logger.info("Creating RAG chain with improved response formatting...")
    
    try:
        # LLMをロード
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # 改良されたプロンプトテンプレート
        prompt_str = """あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の情報を参考に、ユーザーの質問に対して自然で分かりやすい回答を提供してください。

【重要な指示】
- 回答は自然な会話調で、親しみやすく答えてください
- 専門用語は分かりやすく説明してください
- 具体的で実用的な情報を含めてください
- 出典や参考文献については一切言及しないでください
- デバッグ情報や検索結果の詳細は含めないでください
- 【質問】【回答】などのラベルは使用しないでください
- 質問の内容に直接答えることから始めてください
- 縦書きではなく通常の横書き文章として回答してください

【参考情報】
{context}

【質問】
{question}

上記の参考情報を基に、質問に対して自然で分かりやすい回答をお願いします。
住宅に関する専門知識を活用して、お客様にとって有用な情報を提供してください。

回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=prompt_str
        )
        
        # Retrieverの作成
        retriever = vectorstore.as_retriever(
            search_kwargs={"k": 3}
        )
        
        # RAGチェーンを作成
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # カスタムラッパーで回答をクリーンアップ（完全修正版）
        class CleanResponseChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                # 元のチェーンを実行
                result = self.base_chain.invoke(inputs)
                
                # 回答をクリーンアップ（完全修正版適用）
                if "result" in result:
                    raw_result = result["result"]
                    logger.info(f"Raw RAG result: {raw_result[:200]}...")
                    
                    cleaned_result = clean_and_format_response(raw_result)
                    logger.info(f"Cleaned RAG result: {cleaned_result[:200]}...")
                    
                    result["result"] = cleaned_result
                
                return result
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ RAG chain created successfully with improved formatting")
        return CleanResponseChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating RAG chain: {e}")
        logger.error(traceback.format_exc())
        
        # フォールバック: 大幅改良されたシンプルチェーン
        class ImprovedSimpleChain:
            def __init__(self, vectorstore):
                self.vectorstore = vectorstore
                self.retriever = vectorstore.as_retriever()
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                docs = self.retriever.invoke(query)
                
                if docs:
                    # ドキュメントから自然な回答を生成
                    context_texts = [doc.page_content for doc in docs[:3]]
                    
                    # 各ドキュメントの内容をクリーンアップ
                    cleaned_contexts = []
                    for text in context_texts:
                        cleaned = clean_and_format_response(text)
                        if len(cleaned) > 10:
                            cleaned_contexts.append(cleaned)
                    
                    # 質問の種類に応じた回答生成
                    if "坪単価" in query or "価格" in query or "費用" in query:
                        # 価格関連の特別処理
                        price_info = []
                        for text in cleaned_contexts:
                            if any(keyword in text for keyword in ["価格", "坪単価", "万円", "費用", "コスト"]):
                                price_info.append(text)
                        
                        if price_info:
                            result = price_info[0]  # 最初の関連情報を使用
                        else:
                            result = "価格については、お客様のご要望や仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
                    
                    elif "仕様" in query or "標準" in query:
                        # 仕様関連
                        spec_info = []
                        for text in cleaned_contexts:
                            if any(keyword in text for keyword in ["仕様", "標準", "性能", "等級", "ZEH", "断熱"]):
                                spec_info.append(text)
                        
                        if spec_info:
                            result = spec_info[0]
                        else:
                            result = "標準仕様については、高品質な住宅をご提供するため、様々な設備や性能を標準装備としております。詳細については、ショールームでご確認いただけます。"
                    
                    else:
                        # その他の質問
                        if cleaned_contexts:
                            result = cleaned_contexts[0]  # 最も関連性の高い内容
                        else:
                            result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"
                    
                else:
                    result = "申し訳ございません。お尋ねの内容について、該当する情報が見つかりませんでした。詳細については、お気軽にお問い合わせください。"
                
                # 最終的なクリーンアップ
                final_result = clean_and_format_response(result)
                
                return {
                    "result": final_result,
                    "source_documents": docs[:3]
                }
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.warning("Using improved simple chain as fallback")
        return ImprovedSimpleChain(vectorstore)

# OpenAI APIキー取得（後方互換性のため残す）
def get_openai_api_key():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        logger.error("OPENAI_API_KEY not set!")
    return key