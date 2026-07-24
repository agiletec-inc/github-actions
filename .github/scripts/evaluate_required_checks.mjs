const required = JSON.parse(process.env.REQUIRED_CONTEXTS ?? '[]');
const checkRuns = JSON.parse(process.env.CHECK_RUNS ?? '[]');

const pending = [];
const failed = [];

for (const descriptor of required) {
  const candidates = checkRuns.filter(candidate =>
    candidate?.name === descriptor.context &&
    candidate?.workflow_path === descriptor.workflow_path
  );

  if (candidates.length > 1 && candidates.some(candidate => !Number.isSafeInteger(candidate?.id))) {
    failed.push(`${descriptor.context}=ambiguous correct-path candidates`);
    continue;
  }

  const run = candidates.toSorted((left, right) => (right.id ?? 0) - (left.id ?? 0))[0];
  if (!run || run.status !== 'completed') {
    pending.push(descriptor.context);
    continue;
  }

  if (run.conclusion !== 'success') {
    failed.push(`${descriptor.context}=${run.conclusion ?? 'unknown'}`);
  }
}

if (failed.length > 0) {
  console.error(`Required repository checks failed: ${failed.join(', ')}`);
  process.exit(1);
}

if (pending.length > 0) {
  console.error(`Required repository checks pending: ${pending.join(', ')}`);
  process.exit(75);
}

console.log('Required repository checks passed.');
