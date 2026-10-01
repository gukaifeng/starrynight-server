"""Account-scoped exact and near-copy rejection, before persistence or speech.

SQLite FTS5 retrieves bigram candidates; difflib and Dice compare phrases.
This is lexical similarity, not a claim of perfect semantic equivalence.
No embedding downloads, extra classifier calls, or cross-account text exposure.
"""
import re
from difflib import SequenceMatcher
from .greetings import normalized

def grams(text):
    return set(text[i:i+2] for i in range(len(text)-1))

def tokens(text):
    return ' '.join(sorted(grams(normalized(text))))

def similar(left,right):
    a,b=normalized(left),normalized(right)
    if not a or not b:return None
    if a==b:return 'exact'
    small=min(len(a),len(b))
    if small<10:return None
    matcher=SequenceMatcher(None,a,b,autojunk=False)
    if matcher.ratio()>=.78:return 'wording'
    ga,gb=grams(a),grams(b)
    if 2*len(ga&gb)/max(1,len(ga)+len(gb))>=.70:return 'reordered'
    longest=matcher.find_longest_match().size
    if longest>=12 and longest/small>=.72:return 'copied_span'
    # Reusing a long sentence with a new greeting or tail remains a duplicate.
    for x in re.split(r'[。！？!?\n]',left):
        nx=normalized(x)
        if len(nx)<12:continue
        for y in re.split(r'[。！？!?\n]',right):
            ny=normalized(y)
            if len(ny)>=12 and SequenceMatcher(None,nx,ny,autojunk=False).ratio()>=.84:
                return 'copied_sentence'
    return None

def match(store,owner,text,extra=()):
    candidate=normalized(text)
    if not candidate:return None
    exact=store.db.execute('SELECT text,character FROM reply_novelty WHERE owner=? AND canonical=? LIMIT 1',(owner,candidate)).fetchone()
    if exact:return dict(reason='exact',text=exact['text'],character=exact['character'])
    grams_ = sorted(grams(candidate))
    # Bound FTS query size even for a multi-beat story; the most recent 64
    # replies are checked independently, including lexical retrieval misses.
    sampled=grams_[::max(1,len(grams_)//96)][:96]
    rows=[]
    if sampled:
        query=' OR '.join('"'+g.replace('"','""')+'"' for g in sampled)
        rows=store.db.execute('''SELECT n.text,n.character FROM reply_novelty_search f
            JOIN reply_novelty n ON n.rowid=f.rowid WHERE reply_novelty_search MATCH ? AND n.owner=?
            ORDER BY rank LIMIT 64''',(query,owner)).fetchall()
    rows+=store.db.execute('SELECT text,character FROM reply_novelty WHERE owner=? ORDER BY created DESC LIMIT 64',(owner,)).fetchall()
    for row in rows+list(extra):
        if reason:=similar(text,row['text']):return dict(reason=reason,text=row['text'],character=row.get('character') if isinstance(row,dict) else row['character'])
    return None

def context(store,owner,character):
    rows=store.db.execute('SELECT text FROM reply_novelty WHERE owner=? AND character=? ORDER BY created DESC LIMIT 24',(owner,character)).fetchall()
    return dict(previous_lines_to_avoid=[r['text'] for r in rows],
        instruction='每轮内容必须有新的实质回应。即使问题相同，也不要重放或近义改写旧台词；结合本轮情境换切入点，保留正确事实，不编造新事实来求不同。晃动反应也要承接当前相处状态，不反复说晃晕了、轻一点或同一种请求。不要仅更换语气词、昵称、标点或前后缀。')
