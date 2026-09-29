/** Read-only Work collector. Dependencies are supplied by the authorized host.
 * fetchJson(url): decoded JSON from the real GitHub connector GET tool.
 * fetchFile(args): optional typed connector file tool; immutable ref + base64.
 * saveBlob(sha, response): stores base64 bytes for mandatory offline verification.
 * hasBlob(sha): optional verified content-addressed cache; never skips final hashing.
 * This module has no token, HTTP client, publication or process API.
 */
export async function collectSource({repository, fetchJson, saveBlob,
  fetchFile = null, hasBlob = async () => false, readTree = null,
  now = () => new Date().toISOString(), maxCalls = 2000,
  persistObservation = null, progress = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxCalls) || maxCalls < 1 || maxCalls > 10000) throw Error("invalid connector call budget");
  if (typeof fetchJson !== "function" || typeof saveBlob !== "function") throw Error("connector host capabilities required");
  if (fetchFile !== null && typeof fetchFile !== "function") throw Error("invalid file connector capability");
  if (persistObservation !== null && typeof persistObservation !== "function") throw Error("invalid persistence capability");
  if (progress !== null && typeof progress !== "function") throw Error("invalid progress capability");
  if (readTree !== null && typeof readTree !== "function") throw Error("invalid tree reader");
  const prefix = `https://api.github.com/repos/${repository}`;
  let calls = 0;
  const observations = [];
  async function get(suffix) {
    if (++calls > maxCalls) throw Error("bounded connector call budget exhausted");
    const url = prefix + suffix;
    let response;
    try { response = await fetchJson(url); }
    catch (error) {
      if (persistObservation) await persistObservation({url, observed_at:now(), status:"UNKNOWN",
        response:error.connectorResponse ?? null, failure:error.failure || connectorFailure(error)});
      throw error;
    }
    const observation = {url, observed_at: now(), response};
    if (persistObservation) await persistObservation(observation);
    if (!response || typeof response !== "object" || response.error || Number(response.status) >= 400) {
      throw Error("connector observation unavailable; no inferred success");
    }
    observations.push(observation);
    return observation;
  }
  async function getTree(sha, recursive = false) {
    if (!readTree) return get(`/git/trees/${sha}${recursive ? "?recursive=1" : ""}`);
    if (calls >= maxCalls) throw Error("bounded connector call budget exhausted");
    const {observation, reused} = await readTree(sha, recursive);
    if (observation.url !== `${prefix}/git/trees/${sha}${recursive ? "?recursive=1" : ""}` ||
        observation.response?.sha !== sha) throw Error("tree reader identity mismatch");
    if (!reused) calls++;
    observations.push(observation); // original timestamp, including on reuse
    return observation;
  }
  const metadata = await get("");
  if (metadata.response.full_name !== repository || !metadata.response.default_branch) throw Error("repository identity mismatch");
  const branch = metadata.response.default_branch;
  const ref = `/git/ref/heads/${branch.split("/").map(encodeURIComponent).join("/")}`;
  const before = await get(ref);
  const commit = before.response.object?.sha;
  if (!/^[0-9a-f]{40}$/.test(commit || "") || before.response.object.type !== "commit" ||
      before.response.ref !== "refs/heads/" + branch) throw Error("invalid commit identity");
  const commitObservation = await get(`/git/commits/${commit}`);
  const treeSha = commitObservation.response.tree?.sha;
  if (commitObservation.response.sha !== commit || !/^[0-9a-f]{40}$/.test(treeSha || "")) throw Error("commit/tree identity mismatch");
  let tree = (await getTree(treeSha, true)).response;
  if (tree.truncated === true) {
    const queue = [{sha: treeSha, path: "", ancestors: []}];
    const entries = [];
    for (let index = 0; index < queue.length; index++) {
      const node = queue[index];
      if (node.ancestors.includes(node.sha)) throw Error("recursive tree cycle");
      const part = (await getTree(node.sha)).response;
      if (part.sha !== node.sha || part.truncated !== false || !Array.isArray(part.tree)) throw Error("incomplete subtree");
      for (const entry of part.tree) {
        if (typeof entry.path !== "string" || entry.path.includes("/") || ["", ".", ".."].includes(entry.path)) throw Error("invalid subtree path");
        const path = node.path ? node.path + "/" + entry.path : entry.path;
        entries.push({...entry, path});
        if (entries.length > 100000) throw Error("tree entry budget exceeded");
        if (entry.type === "tree") queue.push({sha: entry.sha, path, ancestors: [...node.ancestors, node.sha]});
      }
    }
    tree = {sha: treeSha, truncated: false, tree: entries};
  }
  if (tree.sha !== treeSha || tree.truncated !== false || !Array.isArray(tree.tree)) throw Error("incomplete tree");
  if (tree.tree.length > 100000) throw Error("tree entry budget exceeded");
  const blobs = new Map();
  let total = 0;
  for (const entry of tree.tree) {
    if (typeof entry.path !== "string" || entry.path.includes("\\") || entry.path.includes("\0") ||
        entry.path.split("/").some(part => ["", ".", ".."].includes(part))) throw Error("invalid source path");
    if (!((entry.type === "blob" && ["100644", "100755"].includes(entry.mode)) ||
          (entry.type === "tree" && entry.mode === "040000"))) throw Error("symlink/submodule adapter unavailable");
    if (!/^[0-9a-f]{40}$/.test(entry.sha || "")) throw Error("invalid tree object identity");
    if (entry.type === "blob") {
      if (!Number.isInteger(entry.size) || entry.size < 0 || entry.size > 100 * 1024 * 1024) throw Error("blob size limit");
      total += entry.size;
      if (total > 512 * 1024 * 1024) throw Error("source size limit");
      blobs.set(entry.sha, entry);
    }
  }
  let downloaded = 0, cached = 0;
  for (const [sha, entry] of blobs) {
    if (await hasBlob(sha)) { cached++; continue; }
    let blob;
    if (fetchFile) {
      if (++calls > maxCalls) throw Error("bounded connector call budget exhausted");
      const args = {repository_full_name: repository, path: entry.path, ref: commit, encoding: "base64"};
      let response;
      try { response = await fetchFile(args); }
      catch (error) {
        if (persistObservation) await persistObservation({tool:"github_fetch_file", arguments:args,
          observed_at:now(), status:"UNKNOWN", response:error.connectorResponse ?? null,
          failure:error.failure || connectorFailure(error)});
        throw error;
      }
      const observation = {tool: "github_fetch_file", arguments: args, observed_at: now(), response};
      if (persistObservation) await persistObservation(observation);
      observations.push(observation);
      blob = connectorPayload(response);
    } else {
      blob = (await get(`/git/blobs/${sha}`)).response;
    }
    // A decoded-text tool result is not the raw GitHub blob API. Never guess an
    // encoding or manufacture original bytes from it. Typed file reads preserve
    // their actual envelope above; this size comes independently from the tree.
    blob = checkedBase64(blob, entry);
    await saveBlob(sha, blob);
    downloaded++;
    if (progress) await progress({phase:"SOURCE", calls, downloaded_blobs:downloaded,
      cached_blobs:cached, total_blobs:blobs.size, push_qualified:false});
  }
  const after = await get(ref);
  if (after.response.object?.sha !== commit || after.response.object?.type !== "commit") throw Error("default moved during acquisition");
  return {
    snapshot: {schema: "agent-work-source/v1", repository, commit_sha: commit, tree_sha: treeSha, tree},
    anchor: {default_branch: branch, repository: metadata, before, commit: commitObservation, after},
    acquisition: {calls, downloaded_blobs: downloaded, cached_blobs: cached,
      observations, authentication: "AUTHORIZED_HOST_RESPONSIBILITY", push_qualified: false},
  };
}

/** Unwrap only supported tool envelopes; error content is never source data. */
export function connectorFailure(result) {
  let value = result;
  for (let depth = 0; depth < 4 && value && typeof value === "object"; depth++) {
    if (value.structuredContent) { value = value.structuredContent; continue; }
    if (value.result && typeof value.result === "object") { value = value.result; continue; }
    break;
  }
  const response = value?.error_data || value?.response || value || {};
  const rawStatus = response.status ?? value?.status;
  const status = /^\d{3}$/.test(String(rawStatus)) ? Number(rawStatus) : null;
  const headers = Object.fromEntries(Object.entries(response.headers || value?.headers || {})
    .map(([name, content]) => [name.toLowerCase(), content]));
  const message = String(response.message || value?.error || value?.message || "");
  const rateEvidence = status === 429 || ((status === 403) &&
    (String(headers["x-ratelimit-remaining"]) === "0" ||
      /(?:API |secondary )?rate limit exceeded|secondary rate limit/i.test(message)));
  const kind = rateEvidence ? "RATE_LIMIT" : status === 403 || status === 401 ? "ACCESS_DENIED" :
    status !== null && status >= 500 && status <= 599 ? "TRANSIENT" :
    ["TOOL_UNAVAILABLE", "CAPABILITY_MISSING"].includes(value?.error_code) ? "CAPABILITY_MISSING" :
    status !== null && status >= 400 || value?.error_code === "INVALID_ARGUMENT" ? "DETERMINISTIC" :
    "UNKNOWN";
  return {kind, status, automatic_retry:false};
}

export function connectorPayload(result) {
  let value = result;
  for (let depth = 0; depth < 4; depth++) {
    if (!value || typeof value !== "object" || value.isError === true || value.error ||
        Number(value.status) >= 400) {
      const error = Error("connector tool failed; no fallback or inferred success");
      error.failure = connectorFailure(value);
      error.connectorResponse = result;
      throw error;
    }
    if (value.structuredContent) { value = value.structuredContent; continue; }
    if (value.result && typeof value.result === "object") { value = value.result; continue; }
    return value;
  }
  throw Error("unsupported connector envelope");
}

function checkedBase64(blob, entry) {
  if (blob.sha !== entry.sha || blob.encoding !== "base64" || typeof blob.content !== "string") {
    throw Error(`lossless blob unavailable: ${entry.path}; use github_fetch_file with encoding=base64 and the exact commit ref`);
  }
  // GitHub inserts CR/LF into base64; other whitespace and malformed padding fail.
  const encoded = blob.content.replace(/[\r\n]/g, "");
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
    throw Error(`invalid base64: ${entry.path}`);
  }
  const size = encoded.length / 4 * 3 - (encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0);
  if (size !== entry.size || (blob.size !== undefined && blob.size !== entry.size)) {
    throw Error(`lossless blob size mismatch: ${entry.path}; empty/truncated content cannot be repaired`);
  }
  // Final Git blob/subtree/root rehashing by agent_protocol_work_source.py remains
  // mandatory, including for cache hits. This normalization grants no authority.
  return {sha: entry.sha, encoding: "base64", size: entry.size, content: blob.content};
}

/** Bind the advertised Work tools once. No tokens, HTTP fallback or tool discovery. */
export function createWorkConnector({fetch, fetchFile}) {
  if (typeof fetch !== "function" || typeof fetchFile !== "function") {
    throw Error("Work requires github_fetch and github_fetch_file capabilities");
  }
  return {
    fetchJson: async url => {
      const value = connectorPayload(await fetch({url}));
      if (typeof value.content !== "string") throw Error("connector JSON content unavailable");
      const decoded = JSON.parse(value.content);
      if (!decoded || typeof decoded !== "object") throw Error("connector returned non-JSON resource");
      return decoded;
    },
    fetchFile,
  };
}

/** One observational startup/resume call, followed by the native local preflight.
 * Saved blobs survive interruption; hasBlob must verify bytes on every reuse.
 * Never reuses policy/CI observations or local check success from a former call.
 */
export async function collectWorkSession(options) {
  const source = await collectSource(options);
  const observations = await collectPreflight(options);
  if (observations.default_branch.status !== "OBSERVED" ||
      observations.default_branch.response?.name !== source.anchor.default_branch ||
      observations.default_branch.response?.commit?.sha !== source.snapshot.commit_sha) {
    throw Error("default moved or unavailable before local preflight");
  }
  return {...source, observations, local_preflight: "NOT_RUN", push_qualified: false};
}

/** Bounded observational preflight. Unknown policy/Actions remain UNKNOWN.
 * The snapshot is not a merge, push or operational-receipt qualification.
 * Active PR review threads require the dedicated paginating connector tool.
 */
export async function collectPreflight({repository, fetchJson, activePr = null,
  fetchReviewThreads = null, now = () => new Date().toISOString(), maxPages = 20,
  persistObservation = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 100) throw Error("invalid pagination budget");
  if (!(activePr === null || (Number.isInteger(activePr) && activePr > 0))) throw Error("invalid owner PR");
  if (persistObservation !== null && typeof persistObservation !== "function") throw Error("invalid persistence capability");
  const prefix = `https://api.github.com/repos/${repository}`;
  async function get(suffix) {
    const url = prefix + suffix;
    let observation;
    try {
      const response = await fetchJson(url);
      const status = !response || response.error || Number(response.status) >= 400 ? "UNKNOWN" : "OBSERVED";
      observation = {url, observed_at: now(), status, response};
    } catch (error) {
      observation = {url, observed_at: now(), status: "UNKNOWN", response: error.connectorResponse ?? null,
        failure:error.failure || connectorFailure(error)};
    }
    // Persistence is outside the connector catch: a disk/host failure must stop
    // collection, not be converted into a successfully saved UNKNOWN record.
    if (persistObservation) await persistObservation(observation);
    return observation.status === "UNKNOWN" ? {...observation, response:null} : observation;
  }
  async function pages(suffix) {
    const observations = [];
    const items = [];
    for (let page = 1; page <= maxPages; page++) {
      const observation = await get(`${suffix}${suffix.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
      observations.push(observation);
      if (observation.status !== "OBSERVED" || !Array.isArray(observation.response)) return {status:"UNKNOWN", complete:false, observations};
      items.push(...observation.response);
      if (observation.response.length < 100) return {status:"OBSERVED", complete:true, items, observations};
    }
    return {status:"UNKNOWN", complete:false, observations};
  }
  const repo = await get("");
  if (repo.status !== "OBSERVED" || repo.response.full_name !== repository || !repo.response.default_branch) throw Error("repository observation unavailable");
  const branch = repo.response.default_branch;
  const defaultBranch = await get(`/branches/${branch.split("/").map(encodeURIComponent).join("/")}`);
  const openPullRequests = await pages("/pulls?state=open");
  const recentActions = await get("/actions/runs?per_page=20&page=1");
  let active = {status: "NOT_SELECTED", number: null};
  if (activePr !== null) {
    const pr = await get(`/pulls/${activePr}`);
    const reviews = await pages(`/pulls/${activePr}/reviews`);
    let threads = {status: "UNKNOWN", response: null};
    if (fetchReviewThreads) {
      try {
        // The host must preserve the connector's completeness metadata; a list
        // alone never establishes that all threads were observed.
        const response = await fetchReviewThreads(repository, activePr);
        threads = {status: response?.complete === true ? "OBSERVED" : "UNKNOWN", response, observed_at: now()};
      } catch { /* inaccessible thread details remain UNKNOWN */ }
    }
    if (persistObservation) await persistObservation({tool:"github_list_pull_request_review_threads",
      arguments:{repository_full_name:repository, pr_number:activePr}, observed_at:now(), ...threads});
    active = {number: activePr, pr, reviews, threads};
  }
  return {schema:"agent-work-preflight/v2", repository, generated_at:now(), repo,
    default_branch:defaultBranch, open_pull_requests:openPullRequests,
    policy_source:"TRUSTED_VERSIONED_REPOSITORY_POLICY",
    remote_enforcement:"GITHUB_DECIDES_AT_NORMAL_MERGE",
    active_pull_request:active, recent_actions:recentActions,
    recent_actions_scope:"BOUNDED_INVENTORY_NOT_CI_QUALIFICATION",
    environments:"UNKNOWN_NOT_ACCESSED", authentication:"AUTHORIZED_HOST_RESPONSIBILITY",
    critical_unknown_blocks_binding:true, push_qualified:false};
}

// 1.4.6: a read-only evidence cache. Live authority/gates are never cache keys.
// The host must establish provenance independently before restoring a snapshot.
export async function createEvidenceCollector({repository, fetchJson, persistObservation,
  now = () => new Date().toISOString(), maxPages = 20, maxCalls = 2000,
  cacheSnapshot = null, expectedCacheSha256 = null, sha256 = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("invalid repository");
  if (typeof fetchJson !== "function" || typeof persistObservation !== "function") throw Error("evidence host capabilities required");
  if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 100 ||
      !Number.isInteger(maxCalls) || maxCalls < 1 || maxCalls > 10000) throw Error("invalid evidence budget");
  const prefix = "https://api.github.com/repos/" + repository;
  const cache = new Map(); // immutable JSON strings; callers cannot alter entries
  const stats = {connector_reads:0, reused_reads:0};
  const clone = value => JSON.parse(JSON.stringify(value));
  const validSha = value => typeof value === "string" && /^[0-9a-f]{40}$/.test(value);
  const positive = value => Number.isSafeInteger(value) && value > 0;
  const terminal = row => row?.status === "completed" && typeof row.conclusion === "string" && row.conclusion.length > 0;
  function checkObservation(row, url) {
    if (row?.url !== url || !row.response || typeof row.response !== "object" ||
        !Number.isFinite(Date.parse(row.observed_at)) || Date.parse(row.observed_at) > Date.parse(now()) + 30000 ||
        row.status !== "OBSERVED") throw Error("invalid cached observation");
  }
  function checkImmutable(value, suffix) {
    checkObservation(value, prefix + suffix);
    const match = suffix.match(/^\/git\/(commits|trees)\/([0-9a-f]{40})(\?recursive=1)?$/);
    if (!match || (match[1] === "commits" && match[3]) || value.response.sha !== match[2]) throw Error("immutable identity mismatch");
    if (match[1] === "commits" && !validSha(value.response.tree?.sha)) throw Error("commit tree missing");
    if (match[1] === "trees" && (value.response.truncated !== false || !Array.isArray(value.response.tree))) throw Error("incomplete immutable tree");
  }
  function checkHistory(value, key) {
    const match = key.match(/^attempt\/([1-9][0-9]*)\/([1-9][0-9]*)\/([0-9a-f]{40})$/);
    if (!match) throw Error("invalid attempt key");
    const [, id, attempt, head] = match;
    const suffix = "/actions/runs/" + id + "/attempts/" + attempt;
    checkObservation(value?.attempt, prefix + suffix);
    const run = value.attempt.response;
    if (run.id !== Number(id) || run.run_attempt !== Number(attempt) || run.head_sha !== head || !terminal(run)) throw Error("attempt identity mismatch");
    if (!Array.isArray(value.jobs) || value.jobs.length < 1 || value.jobs.length > maxPages) throw Error("incomplete job history");
    const seen = new Set();
    let count = 0, total = null;
    for (const [index, page] of value.jobs.entries()) {
      checkObservation(page, prefix + suffix + "/jobs?per_page=100&page=" + (index + 1));
      const body = page.response;
      if (!Number.isSafeInteger(body.total_count) || body.total_count < 0 || !Array.isArray(body.jobs) ||
          body.jobs.length > 100 || (total !== null && total !== body.total_count)) throw Error("invalid job pagination");
      total = body.total_count;
      for (const job of body.jobs) {
        if (!positive(job.id) || seen.has(job.id) || job.run_id !== Number(id) ||
            job.head_sha !== head || (job.run_attempt !== undefined && job.run_attempt !== Number(attempt)) ||
            !terminal(job)) throw Error("incomplete or mismatched terminal job");
        seen.add(job.id);
      }
      count += body.jobs.length;
      if (index < value.jobs.length - 1 && count >= total) throw Error("extraneous job page");
    }
    if (count !== total) throw Error("incomplete job history");
  }
  function checkEntry(key, value) {
    if (key.startsWith("/git/")) checkImmutable(value, key);
    else checkHistory(value, key);
  }
  if (cacheSnapshot !== null) {
    if (typeof cacheSnapshot !== "string" || cacheSnapshot.length > 64 * 1024 * 1024 ||
        typeof sha256 !== "function" || !/^[0-9a-f]{64}$/.test(expectedCacheSha256 || "") ||
        await sha256(cacheSnapshot) !== expectedCacheSha256) throw Error("cache digest mismatch");
    const saved = JSON.parse(cacheSnapshot);
    if (saved.schema !== "agent-work-evidence-cache/v1" || saved.repository !== repository ||
        !Array.isArray(saved.entries) || saved.entries.length > 10000) throw Error("cache identity mismatch");
    for (const row of saved.entries) {
      if (!Array.isArray(row) || row.length !== 2 || typeof row[0] !== "string" || cache.has(row[0])) throw Error("duplicate or invalid cache entry");
      checkEntry(...row);
      cache.set(row[0], JSON.stringify(row[1]));
    }
  } else if (expectedCacheSha256 !== null) throw Error("cache snapshot missing");
  async function observe(suffix) {
    if (stats.connector_reads >= maxCalls) throw Error("bounded evidence call budget exhausted");
    stats.connector_reads++;
    const url = prefix + suffix;
    let response, error;
    try { response = await fetchJson(url); } catch (caught) { error = caught; }
    const ok = !error && response && typeof response === "object" && !response.error && !(Number(response.status) >= 400);
    const row = {url, observed_at:now(), status:ok ? "OBSERVED" : "UNKNOWN",
      response:response ?? error?.connectorResponse ?? null};
    if (!ok) row.failure = error?.failure || connectorFailure(response ?? error);
    await persistObservation(clone(row));
    if (!ok) throw error || Error("evidence unavailable");
    return clone(row);
  }
  async function reused(key) {
    const value = JSON.parse(cache.get(key));
    checkEntry(key, value);
    const reads = key.startsWith("/git/") ? 1 : 1 + value.jobs.length;
    await persistObservation({schema:"agent-work-evidence-reuse/v1", repository, key,
      reused_at:now(), original:value, push_qualified:false});
    stats.reused_reads += reads;
    return value;
  }
  function retain(key, value) {
    checkEntry(key, value);
    if (!cache.has(key) && cache.size >= 10000) throw Error("cache entry budget exhausted");
    cache.set(key, JSON.stringify(value));
  }
  async function readImmutable(kind, sha, recursive = false) {
    if (!["commits", "trees"].includes(kind) || !validSha(sha) || typeof recursive !== "boolean" ||
        (kind === "commits" && recursive)) throw Error("immutable request required");
    const key = "/git/" + kind + "/" + sha + (recursive ? "?recursive=1" : "");
    if (cache.has(key)) return {observation:await reused(key), reused:true};
    const observation = await observe(key);
    // Truncated recursive results are useful for fallback, but never reusable.
    if (kind !== "trees" || observation.response.truncated === false) retain(key, observation);
    return {observation, reused:false};
  }
  async function collectRuns(head) {
    if (!validSha(head)) throw Error("exact head required");
    const inventory = [], runs = [], seen = new Set();
    let total = null;
    for (let page = 1; page <= maxPages; page++) {
      const row = await observe("/actions/runs?head_sha=" + head + "&per_page=100&page=" + page);
      inventory.push(row);
      const body = row.response;
      if (!Number.isSafeInteger(body.total_count) || body.total_count < 0 || !Array.isArray(body.workflow_runs) ||
          body.workflow_runs.length > 100 || (total !== null && total !== body.total_count)) throw Error("invalid run pagination");
      total = body.total_count;
      for (const run of body.workflow_runs) {
        if (!positive(run.id) || !positive(run.run_attempt) || run.run_attempt > 100 ||
            run.head_sha !== head || run.repository?.full_name !== repository || seen.has(run.id)) throw Error("run identity mismatch");
        seen.add(run.id); runs.push(run);
      }
      if (runs.length === total) break;
      if (runs.length > total || page === maxPages || body.workflow_runs.length === 0) throw Error("incomplete run inventory");
    }
    const histories = [];
    for (const run of runs) {
      for (let attempt = 1; attempt <= run.run_attempt; attempt++) {
        const key = "attempt/" + run.id + "/" + attempt + "/" + head;
        // The current attempt must still be terminal with the same conclusion.
        if (cache.has(key)) {
          const old = JSON.parse(cache.get(key));
          if (attempt === run.run_attempt && (!terminal(run) || old.attempt.response.conclusion !== run.conclusion)) {
            cache.delete(key);
          }
        }
        if (cache.has(key)) { histories.push({...(await reused(key)), reused:true}); continue; }
        const suffix = "/actions/runs/" + run.id + "/attempts/" + attempt;
        const observed = await observe(suffix), current = observed.response;
        if (current.id !== run.id || current.run_attempt !== attempt || current.head_sha !== head) throw Error("attempt identity mismatch");
        const jobs = [], jobIds = new Set();
        let count = 0, expected = null;
        for (let page = 1; page <= maxPages; page++) {
          const row = await observe(suffix + "/jobs?per_page=100&page=" + page);
          jobs.push(row);
          if (!Array.isArray(row.response.jobs) || !Number.isSafeInteger(row.response.total_count) ||
              row.response.total_count < 0 || row.response.jobs.length > 100 ||
              (expected !== null && expected !== row.response.total_count)) throw Error("invalid job pagination");
          expected = row.response.total_count; count += row.response.jobs.length;
          for (const job of row.response.jobs) {
            if (!positive(job.id) || jobIds.has(job.id) || job.run_id !== run.id || job.head_sha !== head ||
                (job.run_attempt !== undefined && job.run_attempt !== attempt)) throw Error("job identity mismatch");
            jobIds.add(job.id);
          }
          if (count === expected) break;
          if (count > expected || page === maxPages || row.response.jobs.length === 0) throw Error("incomplete job history");
        }
        const value = {attempt:observed, jobs};
        if (terminal(current) && jobs.every(p=>p.response.jobs.every(terminal))) {
          checkHistory(value, key);
          if (attempt === run.run_attempt && (!terminal(run) || current.conclusion !== run.conclusion)) throw Error("run changed during collection");
          retain(key, value);
        }
        histories.push({...value, reused:false});
      }
    }
    return {schema:"agent-work-ci-history/v1", repository, head_sha:head, inventory, histories,
      complete:true, history_only:true, push_qualified:false};
  }
  return {readImmutable, readTree:(sha, recursive=false)=>readImmutable("trees", sha, recursive),
    collectRuns, metrics:()=>({...stats, read_reduction_percent:
      stats.connector_reads + stats.reused_reads ? 100 * stats.reused_reads / (stats.connector_reads + stats.reused_reads) : 0}),
    snapshot:()=>JSON.stringify({schema:"agent-work-evidence-cache/v1", repository,
      entries:[...cache].map(([key, value])=>[key, JSON.parse(value)])})};
}
