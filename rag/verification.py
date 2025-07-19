# rag/verification.py (新規作成)

from rag.advanced_prompts import VERIFICATION_PROMPT
class ResponseVerifier:
    def __init__(self, llm):
        self.llm = llm
    
    def verify_response(self, context: str, question: str, answer: str) -> dict:
        """回答の正確性を検証"""
        
        verification_prompt = VERIFICATION_PROMPT.format(
            context=context,
            question=question,
            answer=answer
        )
        
        verification_result = self.llm.invoke(verification_prompt)
        verification_text = verification_result.content if hasattr(verification_result, 'content') else str(verification_result)
        
        is_accurate = "OK" in verification_text.upper()
        
        return {
            "is_accurate": is_accurate,
            "verification_details": verification_text,
            "original_answer": answer,
            "revised_answer": answer if is_accurate else "提供された情報では正確な回答ができません。"
        }