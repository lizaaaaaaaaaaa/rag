import streamlit as st
import pandas as pd
from utils.auth import (
    get_users, signup_user, update_password, update_role,
    delete_user, get_db_path, get_user_role
)

st.set_page_config(page_title="ユーザー管理", page_icon="👤", layout="wide")
st.title("👤 ユーザー管理ページ（管理者専用）")

# アクセス制御（roleベース）
if get_user_role(st.session_state.get("user", "")) != "admin":
    st.warning("管理者のみ利用できます。")
    st.stop()

st.caption(f"DB_PATH = `{get_db_path()}`")  # 確認用（不要なら削除OK）

users = get_users()
df = pd.DataFrame(users) if users else pd.DataFrame(columns=["username","role","created_at","updated_at"])
st.dataframe(df, use_container_width=True)

st.divider()

# ユーザー追加
st.subheader("【ユーザー追加】")
new_u = st.text_input("ユーザー名", key="add_u")
new_p = st.text_input("パスワード", type="password", key="add_p")
new_r = st.selectbox("権限", ["user","admin"], index=0, key="add_r")
if st.button("追加"):
    ok, msg = signup_user(new_u, new_p, new_r)
    (st.success if ok else st.error)(msg)
    if ok: st.rerun()

# パスワード変更
st.subheader("【パスワード変更】")
if len(df) > 0:
    target_user = st.selectbox("ユーザー", df["username"].tolist(), key="pw_user")
    new_pw = st.text_input("新しいパスワード", type="password")
    if st.button("変更"):
        ok, msg = update_password(target_user, new_pw)
        (st.success if ok else st.error)(msg)
        if ok: st.rerun()

# 権限変更
st.subheader("【権限変更】")
if len(df) > 0:
    role_user = st.selectbox("ユーザー", df["username"].tolist(), key="role_user")
    role_new = st.selectbox("新しい権限", ["user","admin"], index=0, key="role_new")
    if st.button("権限を更新"):
        ok, msg = update_role(role_user, role_new)
        (st.success if ok else st.error)(msg)
        if ok: st.rerun()

# ユーザー削除
st.subheader("【ユーザー削除】")
if len(df) > 0:
    del_user = st.selectbox("削除するユーザー", df["username"].tolist(), key="del_user")
    if st.button("ユーザー削除（注意！）"):
        ok, msg = delete_user(del_user)
        (st.success if ok else st.error)(msg)
        if ok: st.rerun()
