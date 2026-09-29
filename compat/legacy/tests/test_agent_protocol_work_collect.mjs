import test from "node:test";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {collectSource, collectPreflight, collectWorkSession,
  createWorkConnector, connectorPayload, connectorFailure,
  createEvidenceCollector} from "../tools/agent_protocol_work_collect.mjs";

test("source observations survive interruption before the next read", async()=>{
  // Actual connector routing preserves branch separators; it rejects encoded '/'.
  const slash = host({"":{full_name:repo,default_branch:"release/protocol"},
    "/git/ref/heads/release/protocol":{...ref,ref:"refs/heads/release/protocol"}});
  await collectSource(slash);
  assert.ok(slash.calls.includes("/git/ref/heads/release/protocol"));
  assert.ok(!slash.calls.some(x=>x.includes("%2F")));
  const saved=[]; const h=host(); let calls=0;
  const get=h.fetchJson;
  h.fetchJson=async url=>{
    assert.equal(saved.length,calls);
    calls++;
    if(calls===3) throw Error("interrupted");
    return get(url);
  };
  h.persistObservation=async record=>saved.push(structuredClone(record));
  await assert.rejects(collectSource(h),/interrupted/);
  assert.equal(saved.length,3);
  assert.equal(saved[2].status,"UNKNOWN");
  assert.equal(saved[2].response,null);
});
test("persistence failure stops further connector reads", async()=>{
  const h=host();h.persistObservation=async()=>{throw Error("storage failure")};
  await assert.rejects(collectSource(h),/storage failure/);
  assert.equal(h.calls.length,1);
  const p=preflightHost();p.persistObservation=h.persistObservation;
  await assert.rejects(collectPreflight(p),/storage failure/);
  assert.equal(p.calls.length,1);
});
test("raw invalid typed response is durable before validation rejects it",async()=>{
  const h=toolHost();const saved=[];
  h.persistObservation=async r=>saved.push(structuredClone(r));
  h.fetchFile=async()=>({structuredContent:{sha:blob,encoding:"base64",content:""}});
  await assert.rejects(collectSource(h),/size mismatch/);
  assert.equal(saved.at(-1).tool,"github_fetch_file");
  assert.equal(saved.at(-1).response.structuredContent.content,"");
  assert.equal(h.saves.length,0);
});
test("progress follows verified transport saving and cannot qualify a push",async()=>{
  const h=host(),progress=[];
  h.progress=async p=>{assert.equal(h.saves.length,1);progress.push(p)};
  await collectSource(h);
  assert.equal(progress.length,1);
  assert.equal(progress[0].push_qualified,false);
});
test("resume retains old observation time and fetches a fresh policy",async()=>{
  const saved=[],first=preflightHost();
  first.persistObservation=async p=>saved.push(structuredClone(p));
  await collectPreflight(first);
  const before=structuredClone(saved);
  const second=preflightHost({"/rulesets?includes_parents=true&per_page=100&page=1":new Error("denied")});
  second.now=()=>"2026-09-07T00:00:00Z";
  second.persistObservation=async p=>saved.push(structuredClone(p));
  const resumed=await collectPreflight(second);
  assert.deepEqual(saved.slice(0,before.length),before);
  assert.equal(resumed.schema,"agent-work-preflight/v2");
  assert.equal(second.calls.some(p=>p.includes("/rulesets")),false);
  assert.equal(resumed.push_qualified,false);
});

const repo = "example/public", base = "a".repeat(40), root = "b".repeat(40), blob = "c".repeat(40);
const ref = {ref:"refs/heads/main", object:{type:"commit", sha:base}};
const entries = [{path:"readme", type:"blob", mode:"100644", sha:blob, size:1}];
function host(overrides = {}) {
  const calls = [], saves = [];
  const values = {
    "":{full_name:repo, default_branch:"main"},
    "/git/ref/heads/main":ref,
    [`/git/commits/${base}`]:{sha:base, tree:{sha:root}, message:"a normal commit message"},
    [`/git/trees/${root}?recursive=1`]:{sha:root, tree:entries, truncated:false},
    [`/git/blobs/${blob}`]:{sha:blob, size:1, encoding:"base64", content:"eA=="},
    ...overrides,
  };
  const prefix = `https://api.github.com/repos/${repo}`;
  return {calls, saves, repository:repo, now:()=>"2026-09-06T00:00:00Z",
    fetchJson:async url=>{assert.ok(url.startsWith(prefix));const key=url.slice(prefix.length);calls.push(key);
      const value=values[key]; if(value instanceof Error) throw value;
      assert.notEqual(value,undefined,`unexpected connector read: ${key}`);
      return typeof value === "function" ? value() : structuredClone(value);},
    saveBlob:async (sha,response)=>saves.push({sha,response})};
}
test("complete capture uses connector reads and preserves binary transport", async()=>{
  const h=host();const r=await collectSource(h);
  assert.equal(r.snapshot.commit_sha,base);assert.equal(h.saves.length,1);
  assert.equal(r.acquisition.push_qualified,false);assert.equal(h.calls.at(-1),"/git/ref/heads/main");
});
test("verified cache still requires final offline content verification", async()=>{
  const h=host();h.hasBlob=async()=>true;const r=await collectSource(h);
  assert.equal(r.acquisition.cached_blobs,1);assert.equal(h.saves.length,0);
});
test("moved default blocks", async()=>{
  let reads=0;const h=host({"/git/ref/heads/main":()=>++reads===1?ref:{...ref,object:{type:"commit",sha:"d".repeat(40)}}});
  await assert.rejects(collectSource(h),/default moved/);
});
test("truncated recursive tree is reconstructed through nonrecursive reads", async()=>{
  const sub="d".repeat(40);
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,tree:[],truncated:true},
    [`/git/trees/${root}`]:{sha:root,tree:[{path:"src",type:"tree",mode:"040000",sha:sub}],truncated:false},
    [`/git/trees/${sub}`]:{sha:sub,tree:entries,truncated:false}});
  const r=await collectSource(h);assert.deepEqual(r.snapshot.tree.tree.map(x=>x.path),["src","src/readme"]);
});
test("truncated nonrecursive response blocks", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:true},[`/git/trees/${root}`]:{sha:root,tree:entries,truncated:true}});
  await assert.rejects(collectSource(h),/incomplete subtree/);
});
test("no credential or network fallback on connector failure", async()=>{
  await assert.rejects(collectSource(host({[`/git/blobs/${blob}`]:new Error("denied")})),/denied/);
});
test("bounded request budget", async()=>{await assert.rejects(collectSource({...host(),maxCalls:1}),/budget/);});
test("non-finite and non-integer request budgets fail before access", async()=>{
  for (const maxCalls of [Infinity, NaN, 0, 1.5, 10001]) {
    const h=host();
    await assert.rejects(collectSource({...h,maxCalls}),/budget/);
    assert.equal(h.calls.length,0);
  }
});
test("source anchor retains authoritative default-branch metadata", async()=>{
  const r=await collectSource(host());
  assert.equal(r.anchor.repository.response.full_name,repo);
  assert.equal(r.anchor.repository.response.default_branch,"main");
});
test("object identity is validated before any blob URL is requested", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,
    tree:[{...entries[0],sha:"../not-an-object"}]}});
  await assert.rejects(collectSource(h),/object identity/);
  assert.equal(h.calls.some(x=>x.includes("/git/blobs/")),false);
});
test("symlink/submodule cannot silently disappear", async()=>{
  const h=host({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,tree:[{...entries[0],mode:"120000"}]}});
  await assert.rejects(collectSource(h),/adapter unavailable/);
});
function preflightHost(overrides={}) {
  return host({"/branches/main":{name:"main",commit:{sha:base},protected:false},
    "/rulesets?includes_parents=true&per_page=100&page=1":[],
    "/pulls?state=open&per_page=100&page=1":[],
    "/actions/runs?per_page=20&page=1":{workflow_runs:[]},...overrides});
}
test("non-finite pagination budgets fail before access",async()=>{
  const h=preflightHost();
  await assert.rejects(collectPreflight({...h,maxPages:Infinity}),/budget/);
  assert.equal(h.calls.length,0);
});
test("observational preflight does not become CI qualification",async()=>{
  const r=await collectPreflight(preflightHost());assert.equal(r.open_pull_requests.complete,true);
  assert.equal(r.push_qualified,false);assert.equal(r.environments,"UNKNOWN_NOT_ACCESSED");
});
test("ruleset unavailability is outside the ordinary preflight contract",async()=>{
  const h=preflightHost({"/rulesets?includes_parents=true&per_page=100&page=1":new Error("denied")});
  const r=await collectPreflight(h);
  assert.equal("rulesets" in r,false);
  assert.equal(h.calls.some(p=>p.includes("/rulesets")),false);
  assert.equal(r.policy_source,"TRUSTED_VERSIONED_REPOSITORY_POLICY");
  assert.equal(r.remote_enforcement,"GITHUB_DECIDES_AT_NORMAL_MERGE");
});
test("open PR pagination is bounded and never claimed complete at cap",async()=>{
  const h=preflightHost({"/pulls?state=open&per_page=100&page=1":Array.from({length:100},(_,i)=>({number:i+1}))});
  const r=await collectPreflight({...h,maxPages:1});assert.equal(r.open_pull_requests.complete,false);
});
test("only selected PR gets detail and missing threads remain UNKNOWN",async()=>{
  const h=preflightHost({"/pulls/1":{number:1,state:"open"},"/pulls/1/reviews?per_page=100&page=1":[]});
  const r=await collectPreflight({...h,activePr:1});assert.equal(r.active_pull_request.threads.status,"UNKNOWN");
});

function toolHost(overrides = {}) {
  const h = preflightHost(overrides), files = [];
  const connector = createWorkConnector({
    fetch: async ({url}) => ({isError:false, structuredContent:{content:JSON.stringify(await h.fetchJson(url))}}),
    fetchFile: async args => {
      files.push(args);
      return {isError:false, structuredContent:{sha:blob, encoding:"base64", content:"eA==\n"}};
    },
  });
  return {...h, ...connector, files};
}
test("real tool envelope uses pinned file base64 instead of decoded blob GET", async()=>{
  const h=toolHost({[`/git/blobs/${blob}`]:{content:"x"}});
  const result=await collectWorkSession(h);
  assert.deepEqual(h.files,[{repository_full_name:repo,path:"readme",ref:base,encoding:"base64"}]);
  assert.equal(h.calls.some(p=>p.startsWith("/git/blobs/")),false);
  assert.equal(h.saves[0].response.size,1);
  assert.equal(result.local_preflight,"NOT_RUN");
  assert.equal(result.push_qualified,false);
  const observation=result.acquisition.observations.find(o=>o.tool==="github_fetch_file");
  assert.equal(observation.response.structuredContent.content,"eA==\n");
  assert.equal(observation.arguments.ref,base);
});
test("decoded blob GET cannot masquerade as lossless data", async()=>{
  await assert.rejects(collectSource(host({[`/git/blobs/${blob}`]:{content:"x"}})),/github_fetch_file/);
});
test("typed binary transport preserves all byte values and empty files", async()=>{
  for (const bytes of [Buffer.from([]),Buffer.from(Array.from({length:256},(_,i)=>i))]) {
    const h=toolHost({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,tree:[{...entries[0],size:bytes.length}]}});
    h.fetchFile=async()=>({structuredContent:{result:{sha:blob,encoding:"base64",content:bytes.toString("base64")}}});
    await collectSource(h);
    assert.deepEqual(Buffer.from(h.saves[0].response.content,"base64"),bytes);
  }
});
test("wrong SHA, decoded text, missing or truncated bytes and malformed base64 never save",async()=>{
  const good={sha:blob,encoding:"base64",content:"eA=="};
  for (const payload of [ {...good,sha:base}, {...good,encoding:"utf-8",content:"x"},
    {...good,content:""}, {...good,content:"eA"}, {...good,content:"eA== "},
    {...good,content:"===="}, {...good,size:2}, {sha:blob,encoding:"base64"} ]) {
    const h=toolHost(); h.fetchFile=async()=>({structuredContent:payload});
    await assert.rejects(collectSource(h),/lossless|base64/);
    assert.equal(h.saves.length,0);
  }
});
test("error envelopes never unwrap successful-looking nested source",async()=>{
  for (const result of [
    {isError:true,structuredContent:{sha:blob,encoding:"base64",content:"eA=="}},
    {structuredContent:{error:"denied",result:{content:"{}"}}},
    {structuredContent:{result:{status:403,content:"{}"}}},
  ]) assert.throws(()=>connectorPayload(result),/failed/);
  const h=toolHost(); h.fetchFile=async()=>{throw Error("denied")};
  await assert.rejects(collectSource(h),/denied/);
  assert.equal(h.saves.length,0);
  assert.equal(h.calls.some(p=>p.startsWith("/git/blobs/")),false);
});
test("typed source reads obey the same call budget",async()=>{
  const h=toolHost(); await assert.rejects(collectSource({...h,maxCalls:4}),/budget/);
  assert.equal(h.files.length,0);
});
test("valid whitespace paths are retained literally in typed arguments",async()=>{
  const path="space #?\n.txt";
  const h=toolHost({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,tree:[{...entries[0],path}]}});
  await collectSource(h); assert.equal(h.files[0].path,path);
});
test("unsafe source paths fail before typed reads",async()=>{
  for (const path of ["../x","/x","a//x","a/./x","a\\x","a\0x"]) {
    const h=toolHost({[`/git/trees/${root}?recursive=1`]:{sha:root,truncated:false,tree:[{...entries[0],path}]}});
    await assert.rejects(collectSource(h),/source path/); assert.equal(h.files.length,0);
  }
});
test("restart reuses saved blobs but recollects default and policy observations",async()=>{
  const first=toolHost(); await collectWorkSession(first);
  const second=toolHost({"/rulesets?includes_parents=true&per_page=100&page=1":new Error("denied")});
  second.hasBlob=async sha=>sha===first.saves[0].sha;
  const result=await collectWorkSession(second);
  assert.equal(second.files.length,0);
  assert.equal(result.acquisition.cached_blobs,1);
  assert.equal("rulesets" in result.observations,false);
  assert.equal(second.calls.some(p=>p.includes("/rulesets")),false);
  assert.equal(result.local_preflight,"NOT_RUN");
});
test("move between acquisition and observations blocks session result",async()=>{
  const h=toolHost({"/branches/main":{name:"main",commit:{sha:blob}}});
  await assert.rejects(collectWorkSession(h),/default moved/);
});
test("host capabilities and JSON result are explicit",async()=>{
  assert.throws(()=>createWorkConnector({fetch:async()=>{}}),/requires/);
  const c=createWorkConnector({fetch:async()=>({structuredContent:{content:"plain text"}}),fetchFile:async()=>{}});
  await assert.rejects(c.fetchJson("unused"),SyntaxError);
});

test("preflight retains unavailable original responses without promoting them", async()=>{
  const raw={status:403,error:"denied",detail:"original response"};
  const saved=[];
  const h=preflightHost({"/pulls?state=open&per_page=100&page=1":raw});
  const result=await collectPreflight({...h,persistObservation:async record=>saved.push(record)});
  assert.deepEqual(saved.find(r=>r.url.includes("/pulls?")).response,raw);
  assert.equal(result.open_pull_requests.status,"UNKNOWN");
  assert.equal(result.open_pull_requests.observations[0].response,null);
});

const sha256 = async value => createHash("sha256").update(value).digest("hex");
function evidenceHost() {
  const h = preflightHost(), records = [];
  let attempt = 1, status = "completed", conclusion = "failure";
  const original = h.fetchJson;
  h.fetchJson = async url => {
    if (!url.includes("/actions/runs")) return original(url);
    h.calls.push(url);
    const run = {id:42, head_sha:base, run_attempt:attempt, status, conclusion, repository:{full_name:repo}};
    if (url.includes("?head_sha=")) return {total_count:1, workflow_runs:[run]};
    const n = Number(url.match(/attempts\/(\d+)/)?.[1]);
    const detail = {...run, run_attempt:n, status:n < attempt ? "completed" : status,
      conclusion:n < attempt ? "failure" : conclusion};
    if (url.includes("/jobs?")) return {total_count:1, jobs:[
      {id:n, run_id:42, head_sha:base, run_attempt:n, status:detail.status, conclusion:detail.conclusion}]};
    return detail;
  };
  return {...h, records, persistObservation:async value=>records.push(structuredClone(value)),
    setRun:(a, s, c)=>{attempt=a;status=s;conclusion=c;}};
}
test("immutable reuse saves a read, retains original time and isolates returned mutation", async()=>{
  const h=evidenceHost(), c=await createEvidenceCollector(h);
  const first=await c.readImmutable("commits",base);
  first.observation.response.tree.sha=base;
  const second=await c.readImmutable("commits",base);
  assert.equal(second.observation.response.tree.sha,root);
  assert.equal(second.observation.observed_at,"2026-09-06T00:00:00Z");
  assert.equal(second.reused,true);
  assert.equal(h.records.at(-1).schema,"agent-work-evidence-reuse/v1");
  assert.deepEqual(c.metrics(),{connector_reads:1,reused_reads:1,read_reduction_percent:50});
  for(const [kind,sha] of [["refs","main"],["commits","main"],["pulls",base]]) {
    await assert.rejects(c.readImmutable(kind,sha),/immutable/);
  }
  assert.equal(c.metrics().connector_reads,1);
});
test("cache restore verifies independently retained digest and repository", async()=>{
  const h=evidenceHost(), c=await createEvidenceCollector(h);
  await c.readImmutable("commits",base);
  const cacheSnapshot=c.snapshot(), expectedCacheSha256=await sha256(cacheSnapshot);
  const resumed=await createEvidenceCollector({...h,cacheSnapshot,expectedCacheSha256,sha256,
    now:()=>"2026-09-07T00:00:00Z"});
  assert.equal((await resumed.readImmutable("commits",base)).reused,true);
  assert.equal(resumed.metrics().connector_reads,0);
  await assert.rejects(createEvidenceCollector({...h,cacheSnapshot:cacheSnapshot+" ",expectedCacheSha256,sha256}),/digest/);
  await assert.rejects(createEvidenceCollector({...h,repository:"example/other",cacheSnapshot,expectedCacheSha256,sha256}),/identity/);
  await assert.rejects(createEvidenceCollector({...h,cacheSnapshot,expectedCacheSha256}),/digest/);
  assert.equal((await resumed.readImmutable("commits",base)).observation.observed_at,"2026-09-06T00:00:00Z");
});
test("valid outer hash cannot import live gates, wrong identities or duplicate cache keys",async()=>{
  const h=evidenceHost(), c=await createEvidenceCollector(h);
  await c.readImmutable("commits",base);
  for(const mutate of [
    s=>s.entries[0][0]="/branches/main",
    s=>s.entries[0][1].response.sha=root,
    s=>s.entries[0][1].observed_at="2099-01-01T00:00:00Z",
    s=>s.entries.push(s.entries[0]),
  ]) {
    const state=JSON.parse(c.snapshot());mutate(state);const cacheSnapshot=JSON.stringify(state);
    await assert.rejects(createEvidenceCollector({...h,cacheSnapshot,expectedCacheSha256:await sha256(cacheSnapshot),sha256}));
  }
});
test("complete terminal histories reuse only beneath a freshly read exact head inventory",async()=>{
  const h=evidenceHost(),c=await createEvidenceCollector(h);
  const first=await c.collectRuns(base),second=await c.collectRuns(base);
  assert.equal(first.histories[0].attempt.response.conclusion,"failure");
  assert.equal(second.histories[0].reused,true);
  assert.equal(second.push_qualified,false);
  assert.equal(second.history_only,true);
  assert.deepEqual(c.metrics(),{connector_reads:4,reused_reads:2,read_reduction_percent:100/3});
});
test("a new attempt preserves failed history and fetches its own jobs",async()=>{
  const h=evidenceHost(),c=await createEvidenceCollector(h);
  await c.collectRuns(base);
  h.setRun(2,"completed","success");
  const result=await c.collectRuns(base);
  assert.equal(result.histories.length,2);
  assert.equal(result.histories[0].attempt.response.conclusion,"failure");
  assert.equal(result.histories[0].reused,true);
  assert.equal(result.histories[1].reused,false);
  assert.equal(result.histories[1].attempt.response.conclusion,"success");
});
test("live attempts never enter the cache and old green cannot hide current running state",async()=>{
  const h=evidenceHost(),c=await createEvidenceCollector(h);
  h.setRun(1,"completed","success");await c.collectRuns(base);
  h.setRun(1,"in_progress",null);
  const result=await c.collectRuns(base);
  assert.equal(result.histories[0].reused,false);
  assert.equal(result.histories[0].attempt.response.conclusion,null);
  assert.equal(JSON.parse(c.snapshot()).entries.length,0);
  await c.collectRuns(base);
  assert.equal(c.metrics().reused_reads,0);
});
test("policy, default and review observations remain fresh with tree reuse enabled",async()=>{
  const h=evidenceHost(),c=await createEvidenceCollector(h);
  const first=await collectWorkSession({...h,readTree:c.readTree,hasBlob:async()=>true});
  const next=await collectWorkSession({...h,readTree:c.readTree,hasBlob:async()=>true});
  assert.equal(first.snapshot.tree_sha,next.snapshot.tree_sha);
  assert.equal(c.metrics().reused_reads,1);
  assert.equal(h.calls.filter(p=>p.includes("/rulesets")).length,0);
  assert.equal(h.calls.filter(p=>p===("/git/commits/"+base)).length,2);
  assert.equal(h.calls.filter(p=>p==="/git/ref/heads/main").length,4);
});
test("moved source head blocks even with reusable trees",async()=>{
  let refs=0;
  const h=host({"/git/ref/heads/main":()=>++refs===1?ref:{...ref,object:{type:"commit",sha:root}}});
  h.persistObservation=async()=>{};
  const c=await createEvidenceCollector(h);
  await assert.rejects(collectSource({...h,readTree:c.readTree}),/default moved/);
});
test("truncated trees are refetched and never installed as complete cache entries",async()=>{
  const h=host({["/git/trees/"+root+"?recursive=1"]:{sha:root,truncated:true}});
  h.persistObservation=async()=>{};
  const c=await createEvidenceCollector(h);
  assert.equal((await c.readTree(root,true)).reused,false);
  assert.equal((await c.readTree(root,true)).reused,false);
  assert.equal(JSON.parse(c.snapshot()).entries.length,0);
});
test("failed observation or reuse persistence stops without advancing cache metrics",async()=>{
  const h=evidenceHost();let fail=true;
  const c=await createEvidenceCollector({...h,persistObservation:async()=>{if(fail)throw Error("disk failed")}});
  await assert.rejects(c.readImmutable("commits",base),/disk failed/);
  assert.equal(JSON.parse(c.snapshot()).entries.length,0);
  fail=false;await c.readImmutable("commits",base);
  fail=true;await assert.rejects(c.readImmutable("commits",base),/disk failed/);
  assert.equal(c.metrics().reused_reads,0);
});
test("missing or changing pagination never becomes a complete reusable history",async()=>{
  for(const mutate of [
    b=>{if(b.jobs)b.total_count=2},
    b=>{if(b.jobs)b.jobs[0].head_sha=root},
    b=>{if(b.jobs)b.jobs.push({...b.jobs[0]});if(b.jobs)b.total_count=2},
    b=>{if(b.workflow_runs)b.total_count=2},
    b=>{if(b.workflow_runs)b.workflow_runs[0].repository.full_name="other/repo"},
  ]) {
    const h=evidenceHost(),get=h.fetchJson;
    h.fetchJson=async u=>{const b=await get(u);mutate(b);return b};
    const c=await createEvidenceCollector({...h,maxPages:1});
    await assert.rejects(c.collectRuns(base));
    assert.equal(JSON.parse(c.snapshot()).entries.length,0);
  }
});
test("restored CI bytes must satisfy original run and complete job identity",async()=>{
  const h=evidenceHost(),c=await createEvidenceCollector(h);await c.collectRuns(base);
  for(const mutate of [
    s=>s.entries[0][1].attempt.response.status="in_progress",
    s=>s.entries[0][1].jobs[0].response.total_count=2,
    s=>s.entries[0][1].jobs[0].response.jobs[0].run_id=99,
    s=>s.entries[0][1].jobs[0].response.jobs[0].head_sha=root,
  ]) {
    const state=JSON.parse(c.snapshot());mutate(state);const cacheSnapshot=JSON.stringify(state);
    await assert.rejects(createEvidenceCollector({...h,cacheSnapshot,expectedCacheSha256:await sha256(cacheSnapshot),sha256}));
  }
});
test("real connector entrypoint preserves denied response and case-insensitive rate headers",async()=>{
  const response={isError:true,structuredContent:{error:"GitHub API error",
    error_data:{status:"403",message:"Request denied",headers:{"X-RateLimit-Remaining":"0"}}}};
  const h=evidenceHost(); let calls=0;
  const connector=createWorkConnector({fetch:async()=>{calls++;return response},fetchFile:async()=>{throw Error("unexpected")}});
  const collector=await createEvidenceCollector({...h,...connector});
  await assert.rejects(collector.collectRuns(base),error=>error.failure.kind==="RATE_LIMIT");
  assert.equal(calls,1);
  assert.deepEqual(h.records.at(-1).response,response);
  assert.equal(h.records.at(-1).failure.kind,"RATE_LIMIT");
  assert.equal(JSON.parse(collector.snapshot()).entries.length,0);
});
test("evidence budgets reject before extra connector access; UNKNOWN is never cached",async()=>{
  for (const [status,message,kind] of [
    [403,"Resource not accessible by integration","ACCESS_DENIED"],
    [403,"API rate limit exceeded","RATE_LIMIT"],
    [429,"Too many requests","RATE_LIMIT"],
    [503,"Service unavailable","TRANSIENT"],
    [422,"Invalid reference","DETERMINISTIC"],
  ]) {
    const response={isError:true,structuredContent:{error:"GitHub API error",error_data:{status:String(status),message}}};
    assert.deepEqual(connectorFailure(response),{kind,status,automatic_retry:false});
    assert.throws(()=>connectorPayload(response),error=>error.failure.kind===kind);
  }
  const h=evidenceHost(),c=await createEvidenceCollector({...h,maxCalls:1});
  await c.readImmutable("commits",base);
  await assert.rejects(c.readTree(root),/budget/);
  assert.equal(h.calls.length,1);
  const denied=await createEvidenceCollector({...h,fetchJson:async()=>{throw Error("denied")}});
  await assert.rejects(denied.collectRuns(base),/denied/);
  assert.equal(h.records.at(-1).status,"UNKNOWN");
  assert.equal(JSON.parse(denied.snapshot()).entries.length,0);
});
