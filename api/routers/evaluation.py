# api/routers/evaluation.py (新規作成)
from fastapi import APIRouter
from evaluation.ragas_eval import RAGEvaluator

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

@router.post("/run-evaluation")
async def run_evaluation():
    """RAG品質の自動評価を実行"""
    evaluator = RAGEvaluator()
    test_data = evaluator.create_test_dataset()
    
    # テストケースで回答生成
    answers = []
    contexts = []
    
    for question in test_data["questions"]:
        # RAGチェーンで回答取得
        response = rag_chain_template.invoke({"query": question})
        answers.append(response["result"])
        contexts.append([doc.page_content for doc in response["source_documents"]])
    
    # 評価実行
    results = evaluator.evaluate_responses(
        test_data["questions"],
        answers,
        contexts,
        test_data["ground_truths"]
    )
    
    return {"evaluation_results": results}