# check_directory_structure.py
import os
import sys

def check_project_structure():
    """プロジェクトのディレクトリ構造を確認"""
    
    print("現在のディレクトリ:", os.getcwd())
    print("\n=== ディレクトリ構造 ===")
    
    # streamlit_rag_fullstack_ultimateフォルダを探す
    if os.path.exists("streamlit_rag_fullstack_ultimate"):
        print("✅ streamlit_rag_fullstack_ultimate フォルダが見つかりました")
        
        # scriptsフォルダの確認
        scripts_path = os.path.join("streamlit_rag_fullstack_ultimate", "scripts")
        if os.path.exists(scripts_path):
            print("✅ scripts フォルダが見つかりました")
            print("\n📁 scripts フォルダ内のファイル:")
            for file in os.listdir(scripts_path):
                if file.endswith(".py"):
                    print(f"  - {file}")
        else:
            print("❌ scripts フォルダが見つかりません")
    else:
        print("❌ streamlit_rag_fullstack_ultimate フォルダが見つかりません")
        
        # 現在のディレクトリ内を確認
        print("\n現在のディレクトリ内容:")
        for item in os.listdir("."):
            if os.path.isdir(item):
                print(f"📁 {item}/")
            else:
                print(f"📄 {item}")

if __name__ == "__main__":
    check_project_structure()