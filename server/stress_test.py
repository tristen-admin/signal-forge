#!/usr/bin/env python3
"""Repeatable server stress test — run before shipping. Exits non-zero on any failure.
Covers: card x condition resolve matrix, full best-of-7 sims, API robustness + malformed inputs."""
import random, sys, secrets
import engine, rules, app, store
random.seed(11)
names=list(engine.CATALOG.keys())
conds=engine.POWER_CONDS + ['none','veteranedge','freshblood','highroller','chaosrift','coinsedge','abilitylock']
fail=0
def rec(): return {'k':random.randint(0,40),'d':random.randint(0,10),'ok':random.randint(0,8),'od':0}

errs=[]; ran=0
for nm in names:
  for cond in conds:
    for _ in range(3):
      try:
        m=engine.new_match(random.sample(names,4)); m['playerScore']=[random.randint(0,3),random.randint(0,3)]
        m['matchCommits']=random.randint(0,6); m['lastResult']=random.choice(['win','lose','tie',None])
        m['winnersCircle']=[{'name':random.choice(names)} for _ in range(random.randint(0,3))]
        engine.resolve(m, engine.card(nm), engine.card(random.choice(names)), cond, pc_record=rec()); ran+=1
      except Exception as e: errs.append(nm+'|'+cond+'|'+str(e)[:80])
print("MATRIX: %d resolves, %d errors"%(ran,len(errs))); fail+=len(errs)
for e in errs[:10]: print("  !",e)

merr=[]; duels=0
for _ in range(120):
  try:
    deck=random.sample(names,8); m=engine.new_match(deck); g=0
    while not(m['playerScore'][0]>=4 or m['playerScore'][1]>=4) and g<40:
      engine.resolve(m, engine.card(random.choice(deck)), engine.card(random.choice(names)), random.choice(conds), pc_record=rec()); duels+=1; g+=1
  except Exception as e: merr.append(str(e)[:80])
print("MATCH SIM: 120 matches, %d duels, %d errors"%(duels,len(merr))); fail+=len(merr)
for e in merr[:6]: print("  !",e)

aerr=[]; store.conn(); app.seed()
for _ in range(40):
  try:
    h='st_'+secrets.token_hex(4); app.h_register(None,{'handle':h,'password':'pw12345'})
    uid=store.conn().execute('SELECT id FROM users WHERE handle=?',(h,)).fetchone()['id']
    ms=app.h_match_start(uid,{})[1]
    for _ in range(6):
      s=app.h_match_state(uid,{'matchId':ms['matchId']})[1]
      if s.get('done') or not s.get('hand'): break
      if app.h_match_commit(uid,{'matchId':ms['matchId'],'cardUid':s['hand'][0]['uid']})[0]!=200: aerr.append('commit!=200')
  except Exception as e: aerr.append('EXC '+str(e)[:70])
u=store.conn().execute('SELECT id FROM users LIMIT 1').fetchone()['id']
for nm,fn,b in [('buy',app.h_buy,{'listingId':9**9}),('sell',app.h_sell,{'cardUid':'x','price':5}),
                ('commit',app.h_match_commit,{'matchId':'x','cardUid':'x'}),('convert',app.h_convert,{'forge':-5}),
                ('ascpick',app.h_asc_pick,{'runId':'x'}),('spell',app.h_spell_cast,{'matchId':'x','spellId':'x'})]:
  try:
    if fn(u,b)[0]==500: aerr.append('500 on '+nm)
  except Exception as e: aerr.append('CRASH '+nm+': '+str(e)[:50])
print("API: 40 match-runs + malformed inputs, %d issues"%len(aerr)); fail+=len(aerr)
for e in aerr[:8]: print("  !",e)

print("=== "+("ALL CLEAN" if fail==0 else str(fail)+" FAILURES"))
sys.exit(1 if fail else 0)
