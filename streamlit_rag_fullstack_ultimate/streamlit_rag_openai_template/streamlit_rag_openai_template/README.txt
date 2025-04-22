【テンプレート使い方】

1. `.env` ファイルに OpenAI の APIキーを記述してください
   OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx

2. `check_openai_api.py` を実行してキーが有効か確認：
   python check_openai_api.py

3. 成功したら、/rag 配下にPDFを入れて、RAG初期化スクリプトへ進んでください

4. Streamlitアプリ側に統合してチャット画面やダッシュボードを使えます
