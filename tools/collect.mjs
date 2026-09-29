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
    pr, head, preflight, ci, files, commits, trees, retained, final:observations,
    metrics:evidence.metrics(), cache:evidence.snapshot(), result:'COLLECTED_NOT_QUALIFIED'};
}

export async function explainWithEngine({request, invokeAcceptedEngine}) {
  if (typeof invokeAcceptedEngine !== 'function') throw Error('Accepted host engine capability required');
  // The host binds this function to its verified package. Candidate data never
  // chooses a command, module, executable, policy source or credential provider.
  return invokeAcceptedEngine('explain', request);
}
