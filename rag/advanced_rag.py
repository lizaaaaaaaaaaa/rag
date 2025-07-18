# rag/advanced_rag.py (新規作成)
from rag.hybrid_search import HybridRetriever
from rag.reranker import CrossEncoderReranker

def get_advanced_rag_chain(vectorstore, documents, return_source=True):
    """改善されたRAGチェーンを作成"""
    
    # Hybrid検索 + 再ランキング
    hybrid_retriever = HybridRetriever(vectorstore, documents)
    reranker = CrossEncoderReranker()
    
    class AdvancedRAGChain:
        def __init__(self, llm, hybrid_retriever, reranker, prompt):
            self.llm = llm
            self.hybrid_retriever = hybrid_retriever
            self.reranker = reranker
            self.prompt = prompt
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            # 1. Hybrid検索で候補を取得
            candidate_docs = self.hybrid_retriever.get_relevant_documents(query)
            
            # 2. 再ランキングで精度向上
            relevant_docs = self.reranker.rerank(query, candidate_docs, top_k=3)
            
            # 3. コンテキスト構築
            context = "\n\n".join([doc.page_content for doc in relevant_docs])
            
            # 4. LLMで回答生成
            formatted_prompt = self.prompt.format(context=context, question=query)
            response = self.llm.invoke(formatted_prompt)
            
            return {
                "result": response.content if hasattr(response, 'content') else str(response),
                "source_documents": relevant_docs
            }
    
    # LLMとプロンプトを取得
    from llm.llm_runner import load_llm
    llm, _, _ = load_llm()
    
    # 改善されたプロンプトテンプレート
    from langchain.prompts import PromptTemplate
    prompt = PromptTemplate(
        input_variables=["context", "question"],
        template="""以下のコンテキストを参考に、質問に正確に答えてください。

【重要な指示】
- コンテキストに含まれていない情報は推測しないでください
- 不明な点がある場合は「情報が不足しています」と答えてください
- 自然で親しみやすい日本語で回答してください

コンテキスト: {context}

質問: {question}

回答:"""
    )
    
    return AdvancedRAGChain(llm, hybrid_retriever, reranker, prompt)