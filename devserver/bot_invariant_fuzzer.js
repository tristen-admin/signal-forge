// Bot invariant fuzzer — paste into preview_eval (or the browser console on the live
// game) before claiming ANY bot/engine change is verified. Runs many full matches
// with randomized outcomes and checks invariants that should ALWAYS hold, rather
// than confirming one specific hypothesis for one reported symptom.
//
// Why this exists: three separate bot bugs shipped this session because each was
// verified with a narrow, hand-built scenario matching exactly the reported symptom
// -- not by testing the actual rule the code is supposed to guarantee. A card
// resurrecting after it won only shows up with the right combination of match
// length + timing; a fixed 15-turn test with one matchup never hit it. This fuzzer
// checks the INVARIANT ("a won card can never come back") across many randomized
// full matches instead, which is what actually catches this class of bug.
//
// Extend checkInvariants() with new rules as new invariants are discovered --
// don't just add another one-off reproduction script for the next bug.
//
// Usage: copy the IIFE body into preview_eval verbatim. Returns JSON.
// Tune MATCHES_PER_BOT / MAX_TURNS for a quick smoke check vs. a thorough sweep.

(function(){
  var MATCHES_PER_BOT = 15;
  var MAX_TURNS = 40;

  var violations = [];
  var stats = {matches:0, duels:0, errors:0};
  var pool = COLLECTION.filter(function(c){return c&&c.name&&c.pow!=null;});

  function checkInvariants(bot, matchNo, turn, phase){
    // A card already banked to the bot's Winners Circle must never simultaneously
    // exist in its deck, hand, or in-play slot (the exact bug found 2026-07-09).
    if(oppWonBot && oppWonBot.size){
      oppWonBot.forEach(function(nm){
        if(oppDeckBot.some(function(c){return c.name===nm;}))
          violations.push({bot:bot.id, matchNo:matchNo, turn:turn, phase:phase, issue:'won card in DECK', card:nm});
        if(oppHandBot.some(function(c){return c.name===nm;}))
          violations.push({bot:bot.id, matchNo:matchNo, turn:turn, phase:phase, issue:'won card in HAND', card:nm});
        if(_oppInPlay.some(function(c){return c&&c.name===nm;}))
          violations.push({bot:bot.id, matchNo:matchNo, turn:turn, phase:phase, issue:'won card IN PLAY', card:nm});
      });
    }
    // Hand/deck size sanity -- never negative, never runaway (catches unguarded
    // drain/duplication bugs like the pickOppRears and oppBanishN floor bugs).
    if(oppHandBot.length<0 || oppHandBot.length>20)
      violations.push({bot:bot.id, matchNo:matchNo, turn:turn, phase:phase, issue:'hand size out of bounds', size:oppHandBot.length});
    if(oppDeckBot.length<0 || oppDeckBot.length>60)
      violations.push({bot:bot.id, matchNo:matchNo, turn:turn, phase:phase, issue:'deck size out of bounds', size:oppDeckBot.length});
  }

  BOT_OPPONENTS.forEach(function(bot){
    for(var m=0; m<MATCHES_PER_BOT; m++){
      try{
        activeBot=bot; oppInitDeck(); oppLossStreak=0; matchCommits=0; playerScore=[0,0]; lastResult=null;
        winnersCircle=[]; banishPile=[]; if(typeof deathRemnants!=='undefined')deathRemnants=[]; oppWonBot=new Set();
        stats.matches++;
        checkInvariants(bot, m, 0, 'match-start');
        var turn=0;
        while(playerScore[0]<4 && playerScore[1]<4 && turn<MAX_TURNS){
          turn++; matchCommits++;
          if(typeof rearGuards!=='undefined') rearGuards=[];
          var pcTemplate = pool[Math.floor(Math.random()*pool.length)];
          var pc=Object.assign({}, pcTemplate, {kills:Math.floor(Math.random()*15), deaths:Math.floor(Math.random()*8)});
          var oc=pickOppCard();
          pendingOppRears=pickOppRears(oc);
          var conds=[{id:'none',tag:'',mech:'',name:'Open Ground',icon:'',rule:'',strat:''},
                     {id:'mirror',tag:'chaos',mech:'Mirror',name:'Yozai-no-Sato',icon:'',rule:'',strat:''}];
          var cond = conds[Math.random()<0.15?1:0];
          resolve(pc, oc, cond, pc.pow);
          oppEndDuelCycle();
          stats.duels++;
          checkInvariants(bot, m, turn, 'post-duel');
        }
      }catch(e){ stats.errors++; violations.push({bot:bot.id, matchNo:m, issue:'EXCEPTION', msg:e.message}); }
    }
  });

  return JSON.stringify({stats:stats, violationCount:violations.length, violations:violations.slice(0,25)}, null, 1);
})()
