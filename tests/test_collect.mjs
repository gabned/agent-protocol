import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {collectLifecycle, explainWithEngine} from '../tools/collect.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const repository = 'example/synthetic', head = 'a'.repeat(40), base = 'b'.repeat(40);
function harness() {
  const repo = {full_name:repository, id:17, default_branch:'main'};
  const pr = {number:4, state:'open', head:{sha:head}, base:{sha:base,repo}, commits:1,
    changed_files:1,comments:0,review_comments:0};
  const observations = [];
  const responses = {
    '':repo, '/branches/main':{commit:{sha:base}}, '/pulls?state=open&per_page=100&page=1':[pr],
    '/actions/runs?per_page=20&page=1':{total_count:0,workflow_runs:[]},
    '/pulls/4':pr, '/pulls/4/reviews?per_page=100&page=1':[],
    [`/actions/runs?head_sha=${head}&per_page=100&page=1`]:{total_count:0,workflow_runs:[]},
    '/pulls/4/files?per_page=100&page=1':[{filename:'synthetic.py',status:'added'}],
    '/pulls/4/commits?per_page=100&page=1':[{sha:head}],
    '/pulls/4/comments?per_page=100&page=1':[], '/issues/4/comments?per_page=100&page=1':[],
    [`/git/commits/${base}`]:{sha:base,tree:{sha:'d'.repeat(40)},parents:[]},
    [`/git/trees/${'d'.repeat(40)}?recursive=1`]:{sha:'d'.repeat(40),truncated:false,tree:[]},
    [`/git/commits/${head}`]:{sha:head,tree:{sha:'c'.repeat(40)},parents:[{sha:base}]},
    [`/git/trees/${'c'.repeat(40)}?recursive=1`]:{sha:'c'.repeat(40),truncated:false,tree:[]},
  };
  const options = {repository,repositoryId:17,pr:4,
    fetchJson:async url=>{
      const prefix = `https://api.github.com/repos/${repository}`;
      assert.ok(url.startsWith(prefix));
      const suffix = url.slice(prefix.length);
      assert.ok(Object.hasOwn(responses,suffix),suffix);
      return structuredClone(responses[suffix]);
    }, fetchReviewThreads:async()=>({complete:true,threads:[]}),
    persistObservation:async row=>observations.push(row)};
  return {options,responses,observations};
}

test('complete bounded collection retains raw evidence and never claims qualification',async()=>{
  const {options,observations}=harness();
  const result=await collectLifecycle(options);
  assert.equal(result.result,'COLLECTED_NOT_QUALIFIED');
  assert.equal(result.head,head);
  assert.ok(observations.length>10);
  assert.equal(result.ci.complete,true);
});
test('identity, review completeness, pagination and changed head fail closed',async()=>{
  for(const attack of ['identity','threads','pagination','head']) {
    const {options,responses}=harness();
    if(attack==='identity') options.repositoryId=18;
    if(attack==='threads') options.fetchReviewThreads=async()=>({threads:[]});
    if(attack==='pagination') responses['/pulls/4'].changed_files=2;
    if(attack==='head') {
      const original=options.fetchJson; let calls=0;
      options.fetchJson=async url=>{
        const value=await original(url);
        if(url.endsWith('/pulls/4') && ++calls===2) value.head.sha='f'.repeat(40);
        return value;
      };
    }
    await assert.rejects(()=>collectLifecycle(options));
  }
});
test('Work adapter invokes the same accepted CLI and refuses the same invalid effects',async()=>{
  const fixture=JSON.parse(readFileSync(new URL('fixtures/lifecycle.json',import.meta.url)));
  fixture.observation.observed_at=new Date().toISOString().replace(/\.\d{3}Z$/,'Z');
  async function invokeAcceptedEngine(command,value) {
    assert.equal(command,'explain');
    const result=spawnSync(process.env.AP_PYTHON || 'python',['-m','agent_protocol',command],{
      input:JSON.stringify(value),encoding:'utf8',cwd:root,
      env:{...process.env,PYTHONPATH:fileURLToPath(new URL('../src',import.meta.url))}});
    if(result.error) throw result.error;
    if(result.status!==0) throw Error(result.stderr);
    return JSON.parse(result.stdout);
  }
  const accepted=await explainWithEngine({request:fixture,invokeAcceptedEngine});
  assert.equal(accepted.event.operation,'START');
  assert.equal(accepted.event.actor,'owner-a');
  for(const effects of ['UNKNOWN','PRODUCTION']) {
    fixture.observation.effects=effects;
    await assert.rejects(()=>explainWithEngine({request:fixture,invokeAcceptedEngine}));
  }
});
