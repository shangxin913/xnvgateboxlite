import assert from 'node:assert/strict';
import {setSession, getSession} from '../web/assets/api.js';
import {clearReceipts, storePrivateReceipt} from '../web/assets/subscriptions.js';

const result = {id:1,name:'Synthetic test',paths:{clash:'/sub/synthetic/clash'},node_count:0};
setSession({csrf_token:'synthetic-old-session',user:{id:1}});
assert.equal(storePrivateReceipt(result,'synthetic-old-session',true),true);
assert.equal(storePrivateReceipt(result,'synthetic-old-session',false),false);
assert.equal(storePrivateReceipt(result,undefined,true),false);

let release;
const delayed = new Promise(resolve => {release = resolve;});
const requestCSRF = getSession().csrf_token;
const late = delayed.then(data => storePrivateReceipt(data,requestCSRF,true));
// This is the real logout cleanup ordering while a response is still pending.
setSession(null);
clearReceipts();
release(result);
assert.equal(await late,false,'a late response after logout must not restore a private receipt');

setSession({csrf_token:'synthetic-new-session',user:{id:1}});
assert.equal(storePrivateReceipt(result,'synthetic-old-session',true),false,'same user with a new session is not the old authorization context');
assert.equal(storePrivateReceipt(result,'synthetic-new-session',false),false,'a closed route/dialog must discard the token');
assert.equal(storePrivateReceipt(result,'synthetic-new-session',true),true);
clearReceipts();
setSession(null);
console.log('Frontend private receipt lifecycle regression: passed');
