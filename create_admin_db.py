# create_admin_db.py
import os
import sys
import argparse
from utils.auth import (
    ensure_admin_bootstrap, signup_user, update_password,
    update_role, create_users_table, get_db_path
)

def bootstrap_admin() -> int:
    created = ensure_admin_bootstrap()
    print(f"DB: {get_db_path()}")
    print("admin作成:", "OK（ADMIN_PASSWORD 使用）" if created else "スキップ（既存 or 未設定）")
    return 0

def set_user(username: str, password: str, role: str) -> int:
    if not username or not password:
        print("エラー: --username と --password は必須です")
        return 1
    create_users_table()
    # 既存なら更新、無ければ作成
    if not signup_user(username, password, role):
        ok_pw, _ = update_password(username, password)
        ok_role, _ = update_role(username, role)
        if not (ok_pw or ok_role):
            print("ユーザー作成/更新に失敗しました。")
            return 1
    print(f"ユーザー準備OK: {username} / role={role}")
    print(f"DB: {get_db_path()}")
    return 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="users.db 初期化/ユーザー作成")
    p.add_argument("--set", action="store_true", help="任意ユーザー作成/更新モード")
    p.add_argument("--username", type=str, default=None)
    p.add_argument("--password", type=str, default=None)
    p.add_argument("--role", type=str, default="user", choices=["user", "admin"])
    args = p.parse_args(argv)
    return set_user(args.username, args.password, args.role) if args.set else bootstrap_admin()

if __name__ == "__main__":
    sys.exit(main())
