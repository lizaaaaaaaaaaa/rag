# show_structure.py
import os

def print_tree(startpath, prefix=""):
    for i, item in enumerate(sorted(os.listdir(startpath))):
        path = os.path.join(startpath, item)
        connector = "└── " if i == len(os.listdir(startpath)) - 1 else "├── "
        print(prefix + connector + item)
        if os.path.isdir(path):
            extension = "    " if i == len(os.listdir(startpath)) - 1 else "│   "
            print_tree(path, prefix + extension)

# 実行したいルートを指定
root_path = "."  # カレントフォルダでOK（例: streamlit_rag_fullstack_ultimate）
print(f"\n📁 フォルダ構成 ({os.path.abspath(root_path)})\n")
print_tree(root_path)
