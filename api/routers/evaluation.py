# api/routers/evaluation.py (新規作成)
from fastapi import APIRouter
from evaluation.ragas_eval import RAGEvaluator
import logging

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
logger = logging.getLogger(__name__)

@router.post("/run-evaluation")
async def run_evaluation():
    """RAG品質の自動評価を実行"""
    try:
        # mainモジュールから必要なものを取得
        import main
        vectorstore = getattr(main, 'vectorstore', None)
        rag_chain_template = getattr(main, 'rag_chain_template', None)
        
        if not vectorstore or not rag_chain_template:
            return {"error": "RAGシステムが初期化されていません"}
        
        evaluator = RAGEvaluator()
        test_data = evaluator.create_test_dataset()
        
        # テストケースで回答生成
        answers = []
        contexts = []
        
        for question in test_data["questions"]:
            try:
                # RAGチェーンで回答取得
                response = rag_chain_template.invoke({"query": question})
                answers.append(response.get("result", ""))
                
                # ソースドキュメントからコンテキストを抽出
                source_docs = response.get("source_documents", [])
                context_list = [doc.page_content for doc in source_docs]
                contexts.append(context_list)
            except Exception as e:
                logger.error(f"評価中のエラー: {e}")
                answers.append("")
                contexts.append([])
        
        # 評価実行
        results = evaluator.evaluate_responses(
            test_data["questions"],
            answers,
            contexts,
            test_data["ground_truths"]
        )
        
        return {"evaluation_results": results}
        
    except Exception as e:
        logger.error(f"評価エラー: {e}")
        return {"error": str(e)}