import streamlit as st

def login_user():
    st.session_state["user"] = "admin"

def get_user_role(username):
    return "admin"