# pages/10_user_manage.py
import streamlit as st
import sqlite3
import pandas as pd
from unicodedata import normalize
from utils.auth import (
    get_users, signup_user, update_password, update_role, delete_user, get_db_path
)

st.set_page_config(page_title="ユーザー管理", page_icon="👤", layout="wide")
st.title("👤 ユーザー管理ページ（管理者専用）")

# 簡易アクセス制御（ここはあなたの既存ロジックに合わせてOK）
if st.session_state.get("user") != "admin":
    st.warning("管理者のみ利用できます。")
    st.stop()

# DBパスの確認（任意）
st.caption(f"DB_PATH = `{get_db_path()}`")

# 一覧
rows = get_users()
df = pd.DataFrame(rows, columns=["id", "username", "role"])
st.subheader("【ユーザー一覧】")
st.dataframe(df, use_container_width=True)

# 追加
st.subheader("【ユーザー追加】")
with st.form("add_user"):
    col1, col2, col3 = st.columns([3,3,2])
    with col1:
        new_username_raw = st.text_input("新規ユーザー名")
    with col2:
        new_password_raw = st.text_input("新規パスワード", type="password")
    with col3:
        new_role = st.selectbox("権限", ["user", "admin"])
    submit_add = st.form_submit_button("ユーザー追加")

    if submit_add:
        new_username = (new_username_raw or "").strip().lower()
        new_password = normalize("NFC", new_password_raw or "")
        ok, msg = signup_user(new_username, new_password, new_role)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

# PW変更
st.subheader("【パスワード変更】")
if len(df) > 0:
    target_user = st.selectbox("対象ユーザー", df["username"].tolist())
    new_pw_raw = st.text_input("新しいパスワード", type="password")
    if st.button("パスワード更新"):
        new_pw = normalize("NFC", new_pw_raw or "")
        ok, msg = update_password(target_user, new_pw)
        (st.success if ok else st.error)(msg)

# 権限変更
st.subheader("【権限変更】")
if len(df) > 0:
    col1, col2 = st.columns(2)
    with col1:
        role_user = st.selectbox("対象ユーザー", df["username"].tolist(), key="role_user")
    with col2:
        role_new = st.selectbox("新しい権限", ["user", "admin"], key="role_new")
    if st.button("権限を更新"):
        ok, msg = update_role(role_user, role_new)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

# 削除
st.subheader("【ユーザー削除】")
if len(df) > 0:
    del_user = st.selectbox("削除するユーザー", df["username"].tolist(), key="del_user")
    if st.button("ユーザー削除（注意！）"):
        ok, msg = delete_user(del_user)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()
