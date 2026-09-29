/** Current read-only host collector. No HTTP client, credentials or write APIs.
 * The authorized host supplies authenticated connector functions and persistence.
 * Preserved complete-run/attempt/job collection is reused without local forks.
 */
import {createEvidenceCollector, collectPreflight, connectorPayload, createWorkConnector}
  from '../compat/legacy/tools/agent_protocol_work_collect.mjs';

export {connectorPayload, createWorkConnector};

export async function collectLifecycle({repository, repositoryId, pr, fetchJson,
  fetchReviewThreads, persistObservation, now = () => new Date().toISOString(),
  maxPages = 20, cacheSnapshot = null, expectedCacheSha256 = null, sha256 = null}) {
  if (!Number.isSafeInteger(repositoryId) || repositoryId <= 0 ||
      !Number.isSafeInteger(pr) || pr <= 0 || typeof persistObservation !== 'function') {
    throw Error('Independent stable identity, owner PR and durable observation sink required');
  }
  const preflight = await collectPreflight({repository, fetchJson, activePr:pr,
    fetchReviewThreads, persistObservation, now, maxPages});
  const identity = preflight.repo.response;
  const active = preflight.active_pull_request;
  if (identity.id !== repositoryId || active.pr.status !== 'OBSERVED' ||
      active.pr.response.number !== pr || active.pr.response.base?.repo?.id !== repositoryId ||
      active.pr.response.base?.repo?.full_name !== repository) throw Error('Repository/PR identity mismatch');
  if (!active.reviews.complete || active.threads.status !== 'OBSERVED') {
    throw Error('Complete reviews and threads required; absence is not proof');
  }
  const head = active.pr.response.head?.sha;
  if (!/^[0-9a-f]{40}$/.test(head || '')) throw Error('Exact candidate required');
  const evidence = await createEvidenceCollector({repository, fetchJson, persistObservation,
    now, maxPages, cacheSnapshot, expectedCacheSha256, sha256});
  const ci = await evidence.collectRuns(head);
  const postMerge = active.pr.response.merged === true
    ? await evidence.collectRuns(active.pr.response.merge_commit_sha) : null;
  const prefix = `https://api.github.com/repos/${repository}`;
  const retained = [];
  async function pages(suffix, expected) {
    const values = [];
    for (let page = 1; page <= maxPages; page++) {
      const url = `${prefix}${suffix}?per_page=100&page=${page}`;
      const response = await fetchJson(url);
      const observation = {url, response, observed_at:now(), status:'OBSERVED'};
      await persistObservation(observation);
      retained.push(observation);
      if (!Array.isArray(response) || response.length > 100) throw Error('Incomplete object inventory');
      values.push(...response);
      if (response.length < 100) {
        if (values.length !== expected) throw Error('Inventory differs from observed PR');
        return values;
      }
    }
    throw Error('Pagination limit reached; no partial success');
  }
  const files = await pages(`/pulls/${pr}/files`, active.pr.response.changed_files);
  const commits = await pages(`/pulls/${pr}/commits`, active.pr.response.commits);
  const reviewComments = await pages(`/pulls/${pr}/comments`, active.pr.response.review_comments);
  const issueComments = await pages(`/issues/${pr}/comments`, active.pr.response.comments);
  const reviewReferences = [];
  const references = new Set();
  for (const comment of issueComments) {
    if (typeof comment.body !== 'string') continue;
    if (comment.body.includes('<!-- codex-pull-request-review-summary -->')) {
      for (const match of comment.body.matchAll(/\|[^\n]*\*\*(?:Code Review|Security Review)\*\*[^\n]*\|\s*`([0-9a-f]{7,40})`\s*\|/g)) {
        references.add(match[1]);
      }
    }
  }
  if (references.size > 100) throw Error('Review reference budget exceeded');
  for (const ref of references) {
    const url = `${prefix}/commits/${ref}`;
    const row = {url,response:await fetchJson(url),observed_at:now(),status:'OBSERVED'};
    await persistObservation(row); reviewReferences.push(row);
  }
  const baseCommit = await evidence.readImmutable('commits', active.pr.response.base.sha);
  const baseTree = await evidence.readTree(baseCommit.observation.response.tree.sha, true);
  if (baseTree.observation.response.truncated !== false) throw Error('Incomplete accepted base tree');
  const trees = [];
  for (const commit of commits) {
    const object = await evidence.readImmutable('commits', commit.sha);
    const tree = await evidence.readTree(object.observation.response.tree.sha, true);
    if (tree.observation.response.truncated !== false) throw Error('Incomplete candidate tree');
    trees.push({commit:object.observation, tree:tree.observation});
  }
  const before = preflight.default_branch.response.commit.sha;
  const observations = [];
  for (const suffix of [`/pulls/${pr}`, `/branches/${encodeURIComponent(identity.default_branch)}`]) {
    const url = prefix + suffix, response = await fetchJson(url);
    const row = {url, response, status:'OBSERVED', observed_at:now()};
    await persistObservation(row); observations.push(row);
  }
  if (observations[0].response.head?.sha !== head || observations[1].response.commit?.sha !== before ||
      observations[0].response.state !== active.pr.response.state ||
      observations[0].response.base?.sha !== active.pr.response.base.sha) {
    throw Error('PR or default changed during collection; reconcile before retry');
  }
  return {schema:'agent-lifecycle-collection/v2', repository, repository_id:repositoryId,
    pr, head, preflight, ci, postMerge, files, commits, trees, reviewComments, issueComments, reviewReferences,
    base:{commit:baseCommit.observation, tree:baseTree.observation}, retained, final:observations,
    metrics:evidence.metrics(), cache:evidence.snapshot(), result:'COLLECTED_NOT_QUALIFIED'};
}

export async function explainWithEngine({request, invokeAcceptedEngine}) {
  if (typeof invokeAcceptedEngine !== 'function') throw Error('Accepted host engine capability required');
  // The host binds this function to its verified package. Candidate data never
  // chooses a command, module, executable, policy source or credential provider.
  return invokeAcceptedEngine('explain', request);
}

export async function qualifyWithEngine({collection, acceptedProfile, acceptedProfileDigest,
  invokeAcceptedEngine}) {
  if (typeof invokeAcceptedEngine !== 'function') throw Error('Accepted host engine capability required');
  return invokeAcceptedEngine('qualify-pr', {collection, accepted_profile:acceptedProfile,
    expected_profile_digest:acceptedProfileDigest});
}

/** Concrete read-only native host. gh owns supported authentication; no token is read here. */
export async function createGitHubCliReader({repository, repositoryId, invoke = null}) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository) ||
      !Number.isSafeInteger(repositoryId) || repositoryId <= 0) throw Error('Exact repository required');
  if (!invoke) {
    const {execFile} = await import('node:child_process');
    const {promisify} = await import('node:util');
    const execute = promisify(execFile);
    invoke = async args => {
      // No shell, candidate cwd, user-selected command or automatic retry.
      try {
        const {stdout} = await execute('gh', ['api', '--hostname', 'github.com', ...args],
          {maxBuffer:64 * 1024 * 1024, timeout:120000});
        return JSON.parse(stdout);
      } catch { throw Error('Authenticated GitHub read failed; reconcile access, do not infer absence'); }
    };
  }
  const prefix = `https://api.github.com/repos/${repository}`;
  async function fetchJson(url) {
    if (url !== prefix && !url.startsWith(prefix + '/') && !url.startsWith(prefix + '?')) {
      throw Error('Read outside the selected repository refused');
    }
    const parsed = new URL(url);
    if (parsed.href !== url || parsed.origin !== 'https://api.github.com' || parsed.hash || parsed.username || parsed.password ||
        decodeURIComponent(parsed.pathname).split('/').some(p => p === '..' || p === '.')) {
      throw Error('Ambiguous API route refused');
    }
    return invoke(['--method', 'GET', parsed.pathname.slice(1) + parsed.search]);
  }
  async function query(query, variables) {
    const args = ['graphql', '-f', `query=${query}`];
    for (const [key,value] of Object.entries(variables)) {
      if (value !== null) args.push(typeof value === 'number' ? '-F' : '-f', `${key}=${value}`);
    }
    const result = await invoke(args);
    if (result.errors || !result.data) throw Error('Incomplete GraphQL observation');
    return result.data;
  }
  async function fetchReviewThreads(repository_full_name, pr_number) {
    if (repository_full_name !== repository || !Number.isSafeInteger(pr_number) || pr_number <= 0) {
      throw Error('Thread repository/PR identity mismatch');
    }
    const [owner,name] = repository.split('/');
    const threads = [], seenCursors = new Set(), seenIds = new Set();
    let cursor = null;
    for (let page = 0; page < 100; page++) {
      const data = await query(`query($owner:String!,$name:String!,$pr:Int!,$cursor:String){
        repository(owner:$owner,name:$name){databaseId nameWithOwner pullRequest(number:$pr){number
          reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{
            id isResolved comments(first:100){pageInfo{hasNextPage endCursor}
              nodes{id databaseId body author{login} createdAt updatedAt}}}}}}}`,
      {owner,name,pr:pr_number,cursor});
      const repo = data.repository, pull = repo?.pullRequest;
      if (repo?.databaseId !== repositoryId || repo?.nameWithOwner !== repository || pull?.number !== pr_number) {
        throw Error('Authenticated thread identity differs');
      }
      const connection = pull.reviewThreads;
      if (!Array.isArray(connection.nodes)) throw Error('Thread connection incomplete');
      for (const thread of connection.nodes) {
        if (!thread?.id || seenIds.has(thread.id)) throw Error('Duplicated thread');
        seenIds.add(thread.id);
        const comments = [...thread.comments.nodes], cursors = new Set();
        let next = thread.comments.pageInfo;
        for (let part = 0; next.hasNextPage; part++) {
          if (part >= 100 || !next.endCursor || cursors.has(next.endCursor)) throw Error('Comment pagination incomplete');
          cursors.add(next.endCursor);
          const extra = await query(`query($id:ID!,$cursor:String!){node(id:$id){
            ... on PullRequestReviewThread{id comments(first:100,after:$cursor){
              pageInfo{hasNextPage endCursor} nodes{id databaseId body author{login} createdAt updatedAt}}}}}`,
          {id:thread.id,cursor:next.endCursor});
          if (extra.node?.id !== thread.id) throw Error('Comment thread identity changed');
          comments.push(...extra.node.comments.nodes); next = extra.node.comments.pageInfo;
        }
        if (new Set(comments.map(c=>c.databaseId)).size !== comments.length ||
            comments.some(c=>!Number.isSafeInteger(c.databaseId))) throw Error('Incomplete comment identities');
        threads.push({id:thread.id,is_resolved:thread.isResolved,
          comments:comments.map(c=>({...c,database_id:c.databaseId}))});
      }
      if (!connection.pageInfo.hasNextPage) return {complete:true,threads};
      cursor = connection.pageInfo.endCursor;
      if (!cursor || seenCursors.has(cursor)) throw Error('Thread pagination incomplete');
      seenCursors.add(cursor);
    }
    throw Error('Thread pagination limit; no partial success');
  }
  return {fetchJson,fetchReviewThreads};
}

// CLI and Work adapters call the same collector; neither dispatches lifecycle writes.
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv.length !== 6 || process.argv[2] !== '--github') {
      throw Error('Usage: node collect.mjs --github owner/repository repository-id pr-number');
    }
    const repository = process.argv[3], repositoryId = Number(process.argv[4]), pr = Number(process.argv[5]);
    const reader = await createGitHubCliReader({repository,repositoryId});
    const observations = [];
    const collection = await collectLifecycle({repository,repositoryId,pr,...reader,
      persistObservation:async row=>observations.push(row)});
    process.stdout.write(JSON.stringify({collection,observations}) + '\n');
  } catch (error) {
    process.stderr.write(JSON.stringify({result:'REFUSED',reason:error.message}) + '\n');
    process.exitCode = 2;
  }
}
