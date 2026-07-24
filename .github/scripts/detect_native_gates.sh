#!/usr/bin/env bash
set -euo pipefail

repository=${1:-.}
base=${2:-}
head=${3:-HEAD}

revision_exists() {
  git -C "$repository" cat-file -e "$1^{commit}" 2>/dev/null
}

workflows_with_job() {
  local revision=$1
  local wanted=$2
  local path

  while IFS= read -r -d '' path; do
    if git -C "$repository" show "${revision}:${path}" 2>/dev/null |
      awk -v wanted="$wanted" '
        /^jobs:[[:space:]]*$/ { in_jobs=1; next }
        in_jobs && /^[^[:space:]#]/ { in_jobs=0 }
        in_jobs && $0 ~ "^  " wanted ":[[:space:]]*($|#)" { found=1 }
        END { exit(found ? 0 : 1) }
      '; then
      printf '%s\0' "$path"
    fi
  done < <(git -C "$repository" ls-tree -r -z --name-only "$revision" -- .github/workflows)
}

revision_has_supabase() {
  git -C "$repository" cat-file -e "$1:supabase/config.toml" 2>/dev/null
}

for revision in "$base" "$head"; do
  if [ -z "$revision" ] || ! revision_exists "$revision"; then
    printf 'Cannot resolve required-gate revision: %s\n' "${revision:-<empty>}" >&2
    exit 1
  fi
done

# A gate already required by the protected base revision is itself protected.
# Allowing its workflow file to change in the same head would let that head
# manufacture a passing check with weaker behavior.
while IFS= read -r -d '' path; do
  if ! git -C "$repository" diff --quiet "$base" "$head" -- "$path"; then
    printf 'Base-required workflow was modified or removed: %s\n' "$path" >&2
    exit 1
  fi
done < <(workflows_with_job "$base" repo-quality-gate)

if revision_has_supabase "$base"; then
  while IFS= read -r -d '' path; do
    if ! git -C "$repository" diff --quiet "$base" "$head" -- "$path"; then
      printf 'Base-required workflow was modified or removed: %s\n' "$path" >&2
      exit 1
    fi
  done < <(workflows_with_job "$base" db-tests)
fi

required_contexts="$({
  for revision in "$base" "$head"; do
    while IFS= read -r -d '' path; do
      printf '%s\0%s\0' repo-quality-gate "$path"
    done < <(workflows_with_job "$revision" repo-quality-gate)

    if revision_has_supabase "$revision"; then
      while IFS= read -r -d '' path; do
        printf '%s\0%s\0' db-tests "$path"
      done < <(workflows_with_job "$revision" db-tests)
    fi
  done
} | node -e '
  const chunks = [];
  process.stdin.on("data", chunk => chunks.push(chunk));
  process.stdin.on("end", () => {
    const fields = Buffer.concat(chunks).toString("utf8").split("\0");
    fields.pop();
    const descriptors = [];
    for (let index = 0; index < fields.length; index += 2) {
      descriptors.push({ context: fields[index], workflow_path: fields[index + 1] });
    }
    const unique = [...new Map(descriptors.map(item => [`${item.context}\0${item.workflow_path}`, item])).values()]
      .sort((left, right) => left.context.localeCompare(right.context) || left.workflow_path.localeCompare(right.workflow_path));
    process.stdout.write(JSON.stringify(unique));
  });
')"

printf 'required_contexts=%s\n' "$required_contexts"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'required_contexts=%s\n' "$required_contexts" >> "$GITHUB_OUTPUT"
fi
