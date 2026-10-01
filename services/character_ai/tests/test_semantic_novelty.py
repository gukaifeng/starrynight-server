"""Opt-in local model checks; no provider calls or downloads from a test run."""
import os
from pathlib import Path
import pytest
from services.character_ai.config import Settings
from services.character_ai.storage import Store
from services.character_ai.semantic_novelty import SemanticNovelty

@pytest.fixture
def semantic(tmp_path):
    cache=os.environ.get('STARRY_SEMANTIC_MODEL_CACHE')
    if not cache:pytest.skip('Set STARRY_SEMANTIC_MODEL_CACHE to the already-provisioned model for local CPU integration checks')
    (tmp_path/'models').mkdir()
    (tmp_path/'models/reply-novelty').symlink_to(Path(cache),target_is_directory=True)
    store=Store(tmp_path/'db')
    yield SemanticNovelty(Settings(data_dir=tmp_path,semantic_novelty=True,paid_enabled=False),store)
    store.db.close()

@pytest.mark.asyncio
async def test_meaning_copy_is_rejected_and_same_subject_with_new_question_survives(semantic):
    semantic.store.message('old','u','a','r','assistant',dict(text='我今天很开心，你能陪我说说话吗？'))
    result=await semantic.match('u','今天心情真好，可以多陪我聊一会儿吗？')
    assert result and result['reason']=='meaning'
    assert await semantic.match('other','今天心情真好，可以多陪我聊一会儿吗？') is None
    assert semantic.store.db.execute('SELECT count(*) FROM reply_embeddings').fetchone()[0]==1
    assert await semantic.match('u','你画画时通常先勾轮廓还是先挑颜色？我想听听你的习惯。') is None

@pytest.mark.asyncio
async def test_shake_does_not_rephrase_the_same_complaint(semantic):
    semantic.store.message('old','u','a','r','assistant',dict(text='呜，别再摇啦，我的头都晕了，轻一点好吗？',trigger='model_shaken'))
    assert await semantic.match('u','哎呀，我被晃得迷迷糊糊的，稍微温柔点嘛。','model_shaken')
    assert await semantic.match('u','哼，轮到我出题了，你能说出我的一个优点吗？','model_shaken') is None
    with semantic.store.db:semantic.store.clear_novelty('u','a')
    assert semantic.store.db.execute('SELECT count(*) FROM reply_embeddings').fetchone()[0]==0

@pytest.mark.asyncio
async def test_similar_idea_but_reworded_long_response_is_caught(semantic):
    semantic.store.message('old','u','a','r','assistant',dict(text='谢谢你愿意和我分享你的小花画作！虽然我没有眼睛能看到它，但我能感受到这份用心。你是在书屋里画的吗？那里的光线应该很适合画画呢。'))
    assert await semantic.match('u','谢谢你分享小花的创作心意～虽无法亲眼看见，但能想象到你一笔一划的专注。书屋窗边洒落的暖光最适合添上几笔温柔呢。')
