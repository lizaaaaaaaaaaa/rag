# create_admin_db.py
# 目的:
# - users.db に admin ユーザーを安全に作成（bcryptでハッシュ保存）
# - 既に存在する場合は何もしない（= idempotent）
# - 追加モードでは任意ユーザーの新規作成/更新も可能
#
# 使い方（ブートストラップ=環境変数で1回だけ作成）:
#   Windows: set ADMIN_PASSWORD=adminpass
#   mac/linux: export ADMIN_PASSWORD=adminpass
#   python create_admin_db.py
#
# 任意ユーザーを明示的に作成/更新したい場合（パス/ロール上書き可）:
#   python create_admin_db.py --set --username alice --password s3cret --role admin

import os
import sys
import argparse
from utils.auth import (
    ensure_admin_bootstrap,
    signup_user,
    update_password,
    update_role,
    create_users_table,
)

def bootstrap_admin() -> int:
    """
    ADMIN_PASSWORD が設定されていれば 'admin' を1度だけ作成。
    既に存在 / 未設定 の場合は作成しない。
    戻り値: 0=OK, 1=エラー
    """
    created = ensure_admin_bootstrap()
    if created:
        print("admin作成: OK (環境変数の ADMIN_PASSWORD を使用)")
        return 0
    else:
        print("admin作成: スキップ（既に存在 or ADMIN_PASSWORD未設定）")
        return 0

def set_user(username: str, password: str, role: str) -> int:
    """
    任意ユーザーを作成。既に存在していればパスワード/ロールを更新。
    戻り値: 0=OK, 1=エラー
    """
    if not username or not password:
        print("エラー: --username と --password は必須です")
        return 1

    # 念のためテーブルを確実に作る
    create_users_table()

    ok, msg = signup_user(username, password, role)
    if ok:
        print(f"ユーザー作成: {username} / role={role}")
        return 0

    # 既存なら更新に切り替え
    ok_pw, msg_pw = update_password(username, password)
    ok_role, msg_role = update_role(username, role)

    if ok_pw:
        print(f"パスワード更新: {username}")
    else:
        print(f"パスワード更新失敗: {username} -> {msg_pw}")

    if ok_role:
        print(f"ロール更新: {username} -> {role}")
    else:
        print(f"ロール更新失敗: {username} -> {msg_role}")

    return 0 if ok_pw or ok_role else 1

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="users.db 初期化/ユーザー作成スクリプト")
    parser.add_argument(
        "--set", action="store_true",
        help="任意ユーザーを作成/更新モードにする（未指定なら admin のブートストラップ）"
    )
    parser.add_argument("--username", type=str, default=None, help="作成/更新するユーザー名")
    parser.add_argument("--password", type=str, default=None, help="そのユーザーのパスワード")
    parser.add_argument("--role", type=str, default="user", choices=["user", "admin"], help="ロール")

    args = parser.parse_args(argv)

    if args.set:
        return set_user(args.username, args.password, args.role)
    else:
        # 環境変数 ADMIN_PASSWORD を使って admin を一度だけ作成
        return bootstrap_admin()

if __name__ == "__main__":
    sys.exit(main())
