# utils/batch_processor.py (新規作成)
import asyncio
from typing import List, Dict

class BatchProcessor:
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        self.pending_requests = []
    
    async def process_batch(self, requests: List[Dict]) -> List[Dict]:
        """リクエストをバッチで処理"""
        results = []
        
        for i in range(0, len(requests), self.batch_size):
            batch = requests[i:i + self.batch_size]
            batch_results = await self._process_batch_chunk(batch)
            results.extend(batch_results)
        
        return results
    
    async def _process_batch_chunk(self, batch: List[Dict]) -> List[Dict]:
        """バッチチャンクを並列処理"""
        tasks = [self._process_single_request(req) for req in batch]
        return await asyncio.gather(*tasks)
    
    async def _process_single_request(self, request: Dict) -> Dict:
        """単一リクエストの処理"""
        # RAG処理の実装
        pass