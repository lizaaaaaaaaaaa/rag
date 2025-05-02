import os
import uuid
import streamlit as st
import traceback
from rag.ingested_text import ingest_pdf_to_vectorstore, load_vectorstore, get_rag_chain

UPLOAD_DIR = "uploaded_docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(page_title="アップロード & RAG質問", layout="wide")
st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("アップロードしたPDFの内容から質問できます")

# ファイルアップロード
uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    # 📛 UUIDで保存（日本語ファイル名対応）
    unique_filename = f"{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(save_path, "wb") as f:
        f.write(uploaded_file.read())

    # 空ファイルチェック
    if os.path.getsize(save_path) == 0:
        st.error("❌ アップロードされたPDFが空です。別のファイルを選んでください。")
        st.stop()

    st.success(f"✅ アップロード成功: {unique_filename}")

    # 🧠 ベクトルストアに取り込み（エラーログ付き）
    try:
        ingest_pdf_to_vectorstore(save_path)
        st.success("✅ ベクトルストア取り込み完了！")
    except Exception as e:
        st.error("❌ ベクトル化に失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # 💬 質問UI
    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        try:
            vectorstore = load_vectorstore()
        except Exception as e:
            st.error("❌ ベクトルストアの読み込みに失敗しました")
            st.code(traceback.format_exc())
            st.stop()

        try:
            rag_chain = get_rag_chain(vectorstore, return_source=True, question=question)
        except Exception as e:
            st.error("❌ RAGチェーンの構築に失敗しました")
            st.code(traceback.format_exc())
            st.stop()

        try:
            result = rag_chain.invoke({"question": question})
            st.write(f"📘 回答: {result.get('result', '❌ 回答が見つかりませんでした')}")
            if result.get("source_documents"):
                st.write("📎 出典:")
                for doc in result["source_documents"]:
                    source = doc.metadata.get("source", "不明")
                    page = doc.metadata.get("page", "?")
                    st.write(f"- {source} (p{page})")
        except Exception as e:
            st.error("❌ 回答生成中にエラーが発生しました")
            st.code(traceback.format_exc())

