# evaluation/ragas_eval.py (新規作成)
try:
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
    from datasets import Dataset
    HAS_RAGAS = True
except ImportError:
    HAS_RAGAS = False

class RAGEvaluator:
    def __init__(self):
        if not HAS_RAGAS:
            raise ImportError("ragasパッケージがインストールされていません")

class RAGEvaluator:
    def __init__(self):
        self.metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall
        ]
    
    def evaluate_responses(self, questions, answers, contexts, ground_truths):
        """RAG回答の品質を評価"""
        
        dataset = Dataset.from_dict({
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths
        })
        
        result = evaluate(dataset, metrics=self.metrics)
        return result
    
    def create_test_dataset(self):
        """テスト用データセットを作成"""
        return {
            "questions": [
                "RAGとは何ですか？",
                "ベクトル検索の仕組みは？",
                # 追加のテスト質問...
            ],
            "ground_truths": [
                "RAGは検索拡張生成技術です...",
                "ベクトル検索は類似度に基づく検索手法です...",
                # 対応する正解回答...
            ]
        }