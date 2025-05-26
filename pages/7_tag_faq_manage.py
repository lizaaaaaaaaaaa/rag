# pages/7_tag_faq_manage.py
import streamlit as st
import sqlite3
import pandas as pd

DB_FILE = "chat_logs.db"
FAQ_TABLE = "faqs"
TAG_TABLE = "tags"

st.set_page_config(page_title="FAQ・タグ管理", layout="wide")
st.title("🗂️ FAQ・タグ 管理画面")

# FAQ表示・追加
st.subheader("FAQ管理")
conn = sqlite3.connect(DB_FILE)
faq_df = pd.read_sql_query(f"SELECT * FROM {FAQ_TABLE}", conn) if FAQ_TABLE in pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist() else pd.DataFrame(columns=["id","question","answer"])
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
st.subheader("タグ管理")
tag_df = pd.read_sql_query(f"SELECT * FROM {TAG_TABLE}", conn) if TAG_TABLE in pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)['name'].tolist() else pd.DataFrame(columns=["id","tag"])
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
