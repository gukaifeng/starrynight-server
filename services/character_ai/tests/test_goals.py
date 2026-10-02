import base64,json,uuid
import pytest
from services.character_ai import goals
from services.character_ai.schemas import Request,Plan
from services.character_ai.planner_wire import SpokenPlan
from services.character_ai.storage import Store
from services.character_ai.config import Settings
from services.character_ai.orchestrator import Orchestrator
from services.character_ai.reaction_pool import ReactionPool

def snapshot(mode='relationship',version=1):
 return dict(schema_version=1,version=version,progress_version=0,romance_allowed=True,
  config=dict(mode=mode,initial_relation='friends',long_term='romance',short_term='想被安慰',task='english',paused=False,confirmed_couple=False),branches={})

def test_goal_policy_language_and_prepared_context_invalidation(tmp_path):
 store=Store(tmp_path/'state.sqlite3');engine=Orchestrator(Settings(data_dir=tmp_path),store,None);pool=ReactionPool(engine)
 req=Request(request_id=uuid.uuid4(),character_id='anime-ichigo',text='hello')
 value=snapshot();raw=base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
 goals.attach(req,{'x-starry-goal-snapshot':raw,'x-starry-account':str(uuid.uuid4())},store,'u')
 ctx=engine.context('u',req,persist=False);assert ctx['goal_context']['weights']['relationship']==.85
 key=pool.context_key('u',req)
 value=snapshot('task',2);raw=base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
 changed=req.model_copy(deep=True);goals.attach(changed,{'x-starry-goal-snapshot':raw},store,'u')
 assert pool.context_key('u',req)!=key
 ctx=engine.context('u',changed,persist=False);assert 'English ONLY' in ctx['language_contract']
 assert ctx['goal_context']['weights']['task']==.8
 with pytest.raises(Exception):Request(request_id=uuid.uuid4(),character_id='anime-ichigo',goal_snapshot=snapshot())

def test_wire_keeps_evidence_and_feedback():
 p=SpokenPlan(focus='新邀请',beats=[],goal_feedback=dict(affection=.02,evidence='一起喝茶',milestone='date_agreed'))
 full=p.expand(Plan);assert full.goal_feedback.affection==.02 and full.goal_feedback.evidence=='一起喝茶'
 assert not Plan().goal_feedback.affection
