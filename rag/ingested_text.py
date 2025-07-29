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
    """回答をクリーンアップして自然な形式に変換（改善版）"""
    import re
    
    # より包括的な不要パターンの削除
    unwanted_patterns = [
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
    ]
    
    # パターンマッチングで不要部分を削除
    cleaned = raw_response
    for pattern in unwanted_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 縦書き文字の修正（より積極的な結合）
    lines = cleaned.split('\n')
    processed_lines = []
    combined_buffer = []
    
    for line in lines:
        line = line.strip()
        
        # 空行はスキップ
        if not line:
            if combined_buffer:
                # バッファに溜まったテキストを結合
                combined_text = ''.join(combined_buffer)
                if len(combined_text) > 3:
                    processed_lines.append(combined_text)
                combined_buffer = []
            continue
        
        # 短い行（1-3文字）は結合候補
        if len(line) <= 3:
            combined_buffer.append(line)
        else:
            # バッファに溜まったテキストを処理
            if combined_buffer:
                combined_text = ''.join(combined_buffer)
                if len(combined_text) > 3:
                    processed_lines.append(combined_text)
                combined_buffer = []
            
            # 現在の行を追加
            processed_lines.append(line)
    
    # 最後のバッファを処理
    if combined_buffer:
        combined_text = ''.join(combined_buffer)
        if len(combined_text) > 3:
            processed_lines.append(combined_text)
    
    # 文章を自然に結合
    result = ' '.join(processed_lines)
    
    # 追加のクリーンアップ
    result = re.sub(r'\s+', ' ', result)  # 複数スペースを1つに
    result = re.sub(r'([。！？])\s*', r'\1', result)  # 句読点後のスペースを削除
    result = re.sub(r'\.{3,}', '。', result)  # 3つ以上のドットを句点に
    result = result.strip()
    
    # 「、」で終わっている場合は「。」に変更
    if result.endswith('、'):
        result = result[:-1] + '。'
    
    # 最終チェック：意味のない短い回答は置き換え
    if not result or len(result) < 10:
        result = "申し訳ございません。お尋ねの内容について、現在のデータベースでは詳細な情報を見つけることができませんでした。"
    
    return result

def get_rag_chain(vectorstore, return_source: bool = True):
    """RAGチェーンを作成（自然な回答生成版）"""
    logger.info("Creating RAG chain with natural response formatting...")
    
    try:
        # LLMをロード
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # 改良されたプロンプトテンプレート（より明確な指示）
        prompt_str = """あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の情報を参考に、ユーザーの質問に対して自然で分かりやすい回答を提供してください。

【重要な指示】
- 回答は自然な会話調で、親しみやすく答えてください
- 専門用語は分かりやすく説明してください
- 具体的で実用的な情報を含めてください
- 出典や参考文献については一切言及しないでください
- デバッグ情報や検索結果の詳細は含めないでください
- 「関連文書が見つかりました」などの検索結果の説明は含めないでください
- 番号付きリストや出典情報は含めないでください
- 【質問】【回答】などのラベルは使用しないでください
- 質問の内容に直接答えることから始めてください

【参考情報】
{context}

【質問】
{question}

【回答指針】
- 質問に対して直接的で分かりやすい回答を提供する
- 住宅に関する専門知識を活用して具体的にアドバイスする
- 必要に応じて例を挙げて説明する
- 自然な日本語の文章として回答する

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
        
        # カスタムラッパーで回答をクリーンアップ（強化版）
        class CleanResponseChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                # 元のチェーンを実行
                result = self.base_chain.invoke(inputs)
                
                # 回答をクリーンアップ
                if "result" in result:
                    cleaned_result = clean_and_format_response(result["result"])
                    result["result"] = cleaned_result
                
                return result
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ RAG chain created successfully with natural formatting")
        return CleanResponseChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating RAG chain: {e}")
        logger.error(traceback.format_exc())
        
        # フォールバック: 改良されたシンプルチェーン
        class ImprovedSimpleChain:
            def __init__(self, vectorstore):
                self.vectorstore = vectorstore
                self.retriever = vectorstore.as_retriever()
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                docs = self.retriever.invoke(query)
                
                if docs:
                    # 関連する情報から自然な回答を生成
                    context_texts = [doc.page_content for doc in docs[:3]]
                    
                    # 縦書き文字の修正を各テキストに適用
                    fixed_texts = []
                    for text in context_texts:
                        # 縦書き修正処理
                        lines = text.split('\n')
                        fixed_lines = []
                        buffer = []
                        
                        for line in lines:
                            line = line.strip()
                            if len(line) <= 3:
                                buffer.append(line)
                            else:
                                if buffer:
                                    combined = ''.join(buffer)
                                    if len(combined) > 3:
                                        fixed_lines.append(combined)
                                    buffer = []
                                fixed_lines.append(line)
                        
                        if buffer:
                            combined = ''.join(buffer)
                            if len(combined) > 3:
                                fixed_lines.append(combined)
                        
                        fixed_text = ' '.join(fixed_lines)
                        fixed_texts.append(fixed_text)
                    
                    # 質問に応じた回答生成
                    if "坪単価" in query or "価格" in query or "費用" in query:
                        # 価格関連の質問
                        price_info = []
                        for text in fixed_texts:
                            if any(keyword in text for keyword in ["価格", "坪単価", "万円", "費用", "コスト"]):
                                # 価格情報を抽出
                                sentences = text.split("。")
                                for sentence in sentences:
                                    if any(keyword in sentence for keyword in ["価格", "坪単価", "万円"]):
                                        clean_sentence = sentence.strip()
                                        if len(clean_sentence) > 5:
                                            price_info.append(clean_sentence)
                        
                        if price_info:
                            result = "価格については、" + "。".join(price_info[:2]) + "。詳細については、お気軽にお問い合わせください。"
                        else:
                            result = "申し訳ございません。具体的な価格情報については、お客様のご要望や仕様によって異なるため、直接お問い合わせいただければ詳しくご案内いたします。"
                    
                    elif "仕様" in query or "標準" in query:
                        # 仕様関連の質問
                        spec_info = []
                        for text in fixed_texts:
                            if any(keyword in text for keyword in ["仕様", "標準", "性能", "等級", "ZEH", "断熱"]):
                                sentences = text.split("。")
                                for sentence in sentences[:3]:  # 最初の3文を使用
                                    clean_sentence = sentence.strip()
                                    if len(clean_sentence) > 10:
                                        spec_info.append(clean_sentence)
                        
                        if spec_info:
                            # 仕様情報を整理して回答
                            result = "標準仕様についてご説明します。" + "。".join(spec_info[:2]) + "。その他の詳細については、お気軽にお問い合わせください。"
                        else:
                            result = "標準仕様については、高品質な住宅をご提供するため、様々な設備や性能を標準装備としております。詳細については、ショールームでご確認いただけます。"
                    
                    elif "人気" in query or "おすすめ" in query:
                        # 人気・おすすめ関連の質問
                        popular_info = []
                        for text in fixed_texts:
                            if any(keyword in text for keyword in ["人気", "おすすめ", "好評", "評判"]):
                                sentences = text.split("。")
                                for sentence in sentences[:2]:
                                    clean_sentence = sentence.strip()
                                    if len(clean_sentence) > 10:
                                        popular_info.append(clean_sentence)
                        
                        if popular_info:
                            result = "最近人気の設備や間取りについてご紹介します。" + "。".join(popular_info) + "。"
                        else:
                            result = "最近は家事動線を重視した間取りや、省エネ設備、収納力の高い設計が人気です。お客様のライフスタイルに合わせてご提案いたします。"
                    
                    else:
                        # その他の質問
                        # 最も関連性の高い文章を使用
                        main_content = fixed_texts[0] if fixed_texts else ""
                        sentences = main_content.split("。")
                        relevant_sentences = []
                        
                        for sentence in sentences[:3]:
                            clean_sentence = sentence.strip()
                            if len(clean_sentence) > 10:
                                relevant_sentences.append(clean_sentence)
                        
                        if relevant_sentences:
                            result = "。".join(relevant_sentences) + "。ご不明な点がございましたら、お気軽にお尋ねください。"
                        else:
                            result = "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"
                    
                else:
                    result = "申し訳ございません。お尋ねの内容について、現在のデータベースでは該当する情報が見つかりませんでした。詳細については、お気軽にお問い合わせください。"
                
                # 最終的なクリーンアップ
                result = clean_and_format_response(result)
                
                return {
                    "result": result,
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