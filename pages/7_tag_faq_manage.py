import streamlit as st
st.set_page_config(page_title="FAQ・タグ管理", page_icon="🏷️", layout="wide")  # ←import直後！

import sqlite3
import pandas as pd

DB_FILE = "chat_logs.db"
FAQ_TABLE = "faqs"
TAG_TABLE = "tags"

# === ページタイトル・説明 ===
st.title("🏷️ FAQ・タグ管理ページ")
st.write("""
このページでは、FAQ（よくある質問）とタグの追加・管理ができます。
FAQやタグを登録するとチャットやダッシュボードで活用できます。
""")

# --- DB接続 ---
conn = sqlite3.connect(DB_FILE)

# FAQ表示・追加
st.subheader("❓ FAQ管理")
table_list = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist()
if FAQ_TABLE in table_list:
    faq_df = pd.read_sql_query(f"SELECT * FROM {FAQ_TABLE}", conn)
else:
    faq_df = pd.DataFrame(columns=["id", "question", "answer"])
st.dataframe(faq_df)

with st.form("add_faq"):
    new_q = st.text_input("新規FAQ: 質問")
    new_a = st.text_area("新規FAQ: 回答")
    submitted = st.form_submit_button("追加")
    if submitted and new_q and new_a:
        conn.execute(f"INSERT INTO {FAQ_TABLE} (question, answer) VALUES (?, ?)", (new_q, new_a))
        conn.commit()
        st.success("追加されました！")
        st.experimental_rerun()

# タグ表示・追加
st.subheader("🏷️ タグ管理")
if TAG_TABLE in table_list:
    tag_df = pd.read_sql_query(f"SELECT * FROM {TAG_TABLE}", conn)
else:
    tag_df = pd.DataFrame(columns=["id", "tag"])
st.dataframe(tag_df)

with st.form("add_tag"):
    new_tag = st.text_input("新規タグ名")
    submitted = st.form_submit_button("タグ追加")
    if submitted and new_tag:
        conn.execute(f"INSERT INTO {TAG_TABLE} (tag) VALUES (?)", (new_tag,))
        conn.commit()
        st.success("タグ追加！")
        st.experimental_rerun()
conn.close()
