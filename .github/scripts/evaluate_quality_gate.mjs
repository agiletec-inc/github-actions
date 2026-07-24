const detected = JSON.parse(process.env.DETECTED ?? '{}');
const needs = JSON.parse(process.env.NEEDS ?? '{}');

const required = new Set();
for (const [job, applicable] of Object.entries(detected)) {
  if (applicable === true) required.add(job);
}

const failures = [];
for (const [job, state] of Object.entries(needs)) {
  const result = state?.result ?? 'missing';
  if (result === 'failure' || result === 'cancelled') {
    failures.push(`${job}=${result}`);
  } else if (required.has(job) && result !== 'success') {
    failures.push(`${job}=${result}`);
  }
}

for (const job of required) {
  if (!(job in needs)) failures.push(`${job}=missing`);
}

if (failures.length > 0) {
  console.error(`Quality gate failed: ${[...new Set(failures)].join(', ')}`);
  process.exit(1);
}

console.log('Quality gate passed: all applicable jobs succeeded.');
