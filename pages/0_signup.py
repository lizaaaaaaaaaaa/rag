import streamlit as st
from utils.auth import signup_user, create_users_table

st.set_page_config(page_title="新規登録", layout="centered")

st.title("📝 新規ユーザー登録")

create_users_table()

username = st.text_input("ユーザー名を入力")
password = st.text_input("パスワードを入力", type="password")

if st.button("登録する"):
    if signup_user(username, password):
        st.success("✅ 登録成功！ログインページに進んでください。")
    else:
        st.error("❌ このユーザー名はすでに登録されています。")
