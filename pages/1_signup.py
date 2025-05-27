import streamlit as st
st.set_page_config(page_title="新規登録（管理者）", page_icon="📝", layout="wide")  # ←import直後！

from utils.auth import signup_user, create_users_table

# --- 管理者だけアクセス可 ---
role = st.session_state.get("role", "user")
if role != "admin":
    st.title("📝 新規ユーザー登録（管理者用）")
    st.error("このページは管理者のみアクセスできます。")
    st.stop()

st.title("📝 新規ユーザー登録（管理者用）")
create_users_table()

username = st.text_input("ユーザー名を入力")
password = st.text_input("パスワードを入力", type="password")
new_role = st.selectbox("権限", ["user", "admin"], index=0)  # ★ここで権限選択！

if st.button("登録する"):
    # signup_userがrole引数に対応している場合
    if signup_user(username, password, new_role):
        st.success("✅ 登録成功！ログインページでログインしてください。")
    else:
        st.error("❌ このユーザー名はすでに登録されています。")
