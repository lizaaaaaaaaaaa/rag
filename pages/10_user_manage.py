# pages/10_user_manage.py
import streamlit as st
st.set_page_config(page_title="ユーザー管理", page_icon="👤", layout="wide")

import sqlite3
import pandas as pd

from utils.auth import (
    DB_PATH,
    create_users_table,
    get_users,
    signup_user,
    update_password,
    update_role,
    delete_user,
)

# ==== 権限チェック ====
st.title("👤 ユーザー管理ページ（管理者専用）")
user = st.session_state.get("user", "")
if user != "admin":
    st.warning("管理者のみ利用できます。")
    st.stop()

# ==== DB 初期化 & 一覧 ====
create_users_table()
conn = sqlite3.connect(DB_PATH)
user_df = pd.read_sql_query("SELECT id, username, role FROM users ORDER BY id ASC;", conn)
conn.close()

st.subheader("【ユーザー一覧】")
st.dataframe(user_df, use_container_width=True)

# ==== ユーザー追加 ====
st.subheader("【ユーザー追加】")
with st.form(key="add_user_form"):
    col1, col2, col3 = st.columns([3,3,2])
    with col1:
        new_username = st.text_input("新規ユーザー名")
    with col2:
        new_password = st.text_input("新規パスワード", type="password")
    with col3:
        new_role = st.selectbox("権限", ["user", "admin"])
    submitted = st.form_submit_button("ユーザー追加")
    if submitted:
        ok, msg = signup_user(new_username.strip(), new_password, new_role)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

# ==== パスワード変更 ====
st.subheader("【パスワード変更】")
if len(user_df) > 0:
    target_user = st.selectbox("対象ユーザー", user_df["username"].tolist(), key="pw_user")
    new_pw = st.text_input("新パスワード", type="password", key="pw_new")
    if st.button("パスワード更新"):
        ok, msg = update_password(target_user, new_pw)
        (st.success if ok else st.error)(msg)

# ==== 権限変更 ====
st.subheader("【権限変更】")
if len(user_df) > 0:
    col1, col2 = st.columns(2)
    with col1:
        role_user = st.selectbox("対象ユーザー", user_df["username"].tolist(), key="role_user")
    with col2:
        new_role = st.selectbox("新しい権限", ["user", "admin"], key="role_new")
    if st.button("権限を更新"):
        ok, msg = update_role(role_user, new_role)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

# ==== ユーザー削除 ====
st.subheader("【ユーザー削除】")
if len(user_df) > 0:
    del_user = st.selectbox("削除するユーザー", user_df["username"].tolist(), key="del_user")
    if st.button("ユーザー削除（注意！）"):
        ok, msg = delete_user(del_user)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()
