import streamlit as st
from datetime import datetime

st.set_page_config(page_title="住研RAGチャット（営業向け）", layout="wide")

# ユーザー名・営業名（仮ログイン情報）
user_name = st.sidebar.text_input("営業名（ログイン中）", value="田中 太郎")

# 顧客・案件・タグ
customer = st.sidebar.selectbox("顧客選択", ["A社", "B社", "C社"])
project = st.sidebar.text_input("案件名", value="新築提案")
tags = st.sidebar.multiselect("タグ", ["重要", "新規", "見積", "フォロー要", "その他"])

# PDFアップロード
uploaded_pdf = st.sidebar.file_uploader("📄 PDFアップロード", type=["pdf"])
if uploaded_pdf:
    st.sidebar.success("PDFアップロード完了！")

# チャット履歴（ダミーデータ）
chat_history = [
    {
        "role": "user",
        "msg": "A社の標準仕様の説明資料を教えて？",
        "time": "2024-05-24 10:11",
        "tags": ["新規", "見積"],
        "customer": "A社",
        "pdf": "標準仕様2024.pdf",
        "page": 12,
        "comment": "初回商談用"
    },
    {
        "role": "bot",
        "msg": "A社 標準仕様の概要は下記PDFの12ページをご覧ください。\n\n[標準仕様2024.pdf p.12]",
        "time": "2024-05-24 10:12",
        "tags": ["新規", "見積"],
        "customer": "A社",
        "pdf": "標準仕様2024.pdf",
        "page": 12,
        "comment": ""
    }
]

# メイン画面
st.title("🏠 住研RAG チャット（営業向け）")

# チャット履歴表示
for item in chat_history:
    align = "user" if item["role"] == "user" else "assistant"
    with st.chat_message(align):
        st.markdown(f"**{item['customer']} | {item['time']}**")
        st.markdown(item["msg"])
        if item.get("pdf"):
            st.caption(f"📄 出典: {item['pdf']} p.{item['page']}")
        if item.get("tags"):
            st.caption("🏷️ " + ", ".join(item["tags"]))
        if item.get("comment"):
            st.caption("📝 " + item["comment"])

# 質問送信欄
st.markdown("---")
question = st.text_area("質問内容を入力", height=50)
comment = st.text_input("コメント（任意）")
send = st.button("送信", type="primary")

if send and question:
    st.success("送信完了！（API未連携モック）")

