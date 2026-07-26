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

# PR_LABELS carries labels from the pull_request event context (never from
# repository file content), so a head cannot self-authorize by editing
# tracked files. merge_group events have no labels, so this is empty there
# and the strict behavior below applies unchanged.
has_allow_label=0
for label in ${PR_LABELS:-}; do
  if [ "$label" = "allow-protected-workflow-change" ]; then
    has_allow_label=1
    break
  fi
done

for revision in "$base" "$head"; do
  if [ -z "$revision" ] || ! revision_exists "$revision"; then
    printf 'Cannot resolve required-gate revision: %s\n' "${revision:-<empty>}" >&2
    exit 1
  fi
done

# A gate already required by the protected base revision is itself protected.
# Allowing its workflow file to change in the same head would let that head
# manufacture a passing check with weaker behavior. The
# allow-protected-workflow-change PR label is a deliberate, auditable escape
# hatch for intentionally strengthening a protected workflow.
while IFS= read -r -d '' path; do
  if ! git -C "$repository" diff --quiet "$base" "$head" -- "$path"; then
    if [ "$has_allow_label" -eq 1 ]; then
      printf 'Protected workflow changed under allow-protected-workflow-change: %s\n' "$path"
    else
      printf 'Base-required workflow was modified or removed: %s\n' "$path" >&2
      exit 1
    fi
  fi
done < <(workflows_with_job "$base" repo-quality-gate)

if revision_has_supabase "$base"; then
  while IFS= read -r -d '' path; do
    if ! git -C "$repository" diff --quiet "$base" "$head" -- "$path"; then
      if [ "$has_allow_label" -eq 1 ]; then
        printf 'Protected workflow changed under allow-protected-workflow-change: %s\n' "$path"
      else
        printf 'Base-required workflow was modified or removed: %s\n' "$path" >&2
        exit 1
      fi
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
