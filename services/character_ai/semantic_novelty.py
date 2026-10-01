"""Local Chinese BGE embeddings: retrieve related responses without a paid judge.

The model is provisioned separately, never downloaded on a conversation request.
SQLite caches vectors per message and model; only this account's recent replies
are compared. CPU inference is bounded and runs off the HTTP event loop.
Low-score retrieval is a suggestion, not proof of equivalent meaning; the
orchestrator permits one revision for it, never endless topic-based rejection.
"""
import asyncio
import json
from pathlib import Path

MODEL='BAAI/bge-small-zh-v1.5'
LOCK=json.loads(Path(__file__).with_name('novelty-model.lock.json').read_text())
MODEL_REVISION=LOCK['revision']+'/fastembed-0.8.1'
HISTORY_LIMIT=128
SIMILARITY_THRESHOLD=.74
SHAKE_SIMILARITY_THRESHOLD=.58

class SemanticNovelty:
    def __init__(self,settings,store):
        self.settings,self.store=settings,store
        self.lock=asyncio.Lock();self.model=None
    def embed(self,texts):
        if self.model is None:
            from fastembed import TextEmbedding
            cache=self.settings.data_dir/'models/reply-novelty'
            snapshot=cache/('models--'+LOCK['onnx_repository'].replace('/','--'))/'snapshots'/LOCK['revision']
            self.model=TextEmbedding(MODEL,specific_model_path=str(snapshot),local_files_only=True,threads=2)
        return list(self.model.embed(texts,batch_size=16))
    async def warmup(self):
        if not self.settings.semantic_novelty:return
        async with self.lock:
            if self.model is None:
                # Local weights only, no dialogue/paid request. Load ORT and
                # prime its kernels before a user's first generated answer.
                await asyncio.to_thread(self.embed,['预热'])
    async def match(self,owner,text,trigger='user_message'):
        if not self.settings.semantic_novelty or len(text.strip())<10:return None
        import numpy as np
        rows=self.store.db.execute('''SELECT n.message,n.text,n.character,e.vector,json_extract(m.data,'$.trigger') trigger FROM reply_novelty n
            JOIN messages m ON m.id=n.message
            LEFT JOIN reply_embeddings e ON e.message=n.message AND e.model=?
            WHERE n.owner=? ORDER BY n.created DESC LIMIT ?''',(MODEL_REVISION,owner,HISTORY_LIMIT)).fetchall()
        if not rows:return None
        missing=[r for r in rows if r['vector'] is None]
        async with self.lock:
            vectors=await asyncio.to_thread(self.embed,[text]+[r['text'] for r in missing])
        generated={r['message']:v for r,v in zip(missing,vectors[1:])}
        with self.store.db:
            for id,vector in generated.items():
                self.store.db.execute('INSERT OR REPLACE INTO reply_embeddings SELECT ?,?,? WHERE EXISTS (SELECT 1 FROM reply_novelty WHERE message=?)',
                    (id,MODEL_REVISION,vector.astype('<f4').tobytes(),id))
        query=vectors[0];best=None
        for row in rows:
            threshold=SHAKE_SIMILARITY_THRESHOLD if trigger in ('model_shaken','model_pinched') and row['trigger'] in ('model_shaken','model_pinched') else SIMILARITY_THRESHOLD
            vector=generated[row['message']] if row['vector'] is None else np.frombuffer(row['vector'],dtype='<f4')
            score=float(np.dot(query,vector)/(np.linalg.norm(query)*np.linalg.norm(vector)))
            if score>=threshold and (best is None or score>best['score']):
                best=dict(reason='meaning',score=round(score,4),text=row['text'],character=row['character'])
        return best
