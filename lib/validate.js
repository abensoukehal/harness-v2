import { existsSync, readFileSync } from "node:fs";
import { basename, dirname, extname, join } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import YAML from "yaml";

const schemaDir = new URL("../schemas/", import.meta.url);
const schemas = {
  config: JSON.parse(readFileSync(new URL("client.config.schema.json", schemaDir), "utf8")),
  state: JSON.parse(readFileSync(new URL("state.schema.json", schemaDir), "utf8")),
  result: JSON.parse(readFileSync(new URL("worker.result.schema.json", schemaDir), "utf8")),
};
const ajv = new Ajv2020({ allErrors: true, strictTypes: false, verbose: true });
ajv.addSchema(schemas.result);
const compiled = {
  config: ajv.compile(schemas.config),
  state: ajv.compile(schemas.state),
  result: ajv.getSchema("urn:harness:result"),
};

export function schemaFor(file) {
  const name = basename(file);
  if (name === "state.json") return "state";
  if (/\.config\.ya?ml$/.test(name)) return "config";
  return null;
}

export function load(file) {
  const text = readFileSync(file, "utf8");
  return extname(file) === ".json" ? JSON.parse(text) : YAML.parse(text);
}

export function validateFile(file, schema = schemaFor(file)) {
  // A config lives at <workspace>/product/client.config.yaml, so secrets/ sits two levels up. The checks that read
  // it run only for a file at that path; anywhere else, and for validate() on bare data, every other check still runs.
  const inWorkspace = schema === "config" && basename(dirname(file)) === "product";
  return validate(load(file), schema, inWorkspace ? { workspace: dirname(dirname(file)) } : undefined);
}

export function validate(data, schema, context) {
  const check = compiled[schema];
  if (!check) throw new Error(`unknown schema "${schema}"`);
  if (!check(data)) return { ok: false, pass: "schema", errors: format(check.errors) };
  const errors = { config: checkConfig, state: checkState, result: checkResult }[schema](data, context);
  return { ok: errors.length === 0, pass: "cross-field", errors };
}

const REMOVED = {
  git: 'no key "git": nothing reads it. Section 9.2 is enforced by the commit routine, not by a setting',
  max_parallel_features: 'no key "max_parallel_features": nothing reads it. One feature per workspace',
};
const RENAMED = { "/delivery/mode": { pr: 'mode "pr" is now "branch": push the branch and stop' } };

function format(ajvErrors) {
  const out = [];
  const seen = new Set();
  const push = (path, message) => {
    const key = `${path} ${message}`;
    if (!seen.has(key)) { seen.add(key); out.push({ path: path || "/", message }); }
  };
  const oneOfPaths = ajvErrors.filter((e) => e.keyword === "oneOf").map((e) => e.schemaPath);
  const branchOf = (e) => {
    const parent = oneOfPaths.find((p) => e.schemaPath.startsWith(`${p}/`));
    return parent ? { parent, index: Number(e.schemaPath.slice(parent.length + 1).split("/")[0]) } : null;
  };
  // Under a failed oneOf, keep only the branch that came closest.
  const byBranch = new Map();
  for (const e of ajvErrors) {
    const b = branchOf(e);
    if (!b) continue;
    const key = `${b.parent}#${b.index}`;
    byBranch.set(key, [...(byBranch.get(key) ?? []), e]);
  }
  const closest = new Set();
  for (const parent of oneOfPaths) {
    const groups = [...byBranch.entries()].filter(([k]) => k.startsWith(`${parent}#`));
    if (groups.length) closest.add(groups.sort((a, b) => a[1].length - b[1].length)[0][0]);
  }
  for (const e of ajvErrors) {
    const b = branchOf(e);
    if (b && !closest.has(`${b.parent}#${b.index}`)) continue;
    if (e.keyword === "if") continue;
    if (e.schemaPath.includes("/propertyNames/")) continue;
    const p = e.params;
    switch (e.keyword) {
      case "required": push(`${e.instancePath}/${p.missingProperty}`, `missing required key "${p.missingProperty}"`); break;
      case "additionalProperties": push(`${e.instancePath}/${p.additionalProperty}`, REMOVED[p.additionalProperty] ?? `unexpected key "${p.additionalProperty}"`); break;
      case "propertyNames": push(`${e.instancePath}/${p.propertyName}`, `invalid key "${p.propertyName}"`); break;
      case "enum": push(e.instancePath, RENAMED[e.instancePath]?.[e.data] ?? `must be one of: ${p.allowedValues.join(", ")}`); break;
      case "oneOf": {
        push(e.instancePath, `must match exactly one of: ${e.parentSchema.oneOf.map((b) => b.title).join(", ")}`);
        break;
      }
      default: push(e.instancePath, e.message);
    }
  }
  return out;
}

const portRef = /\$\{PORT_([A-Z0-9_]+)\}/g;

const SECRET_FLOOR = 8;  // 9.3, and the same number lib/harness/secrets.py enforces at runtime

// Mirrors load_env_file in lib/harness/secrets.py: KEY=value, optional export, optional matching quotes.
function readEnvFile(path) {
  const values = {};
  for (const raw of readFileSync(path, "utf8").split("\n")) {
    let line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    if (line.startsWith("export ")) line = line.slice("export ".length);
    const at = line.indexOf("=");
    let value = line.slice(at + 1).trim();
    if (value.length >= 2 && value[0] === value.at(-1) && (value[0] === '"' || value[0] === "'")) value = value.slice(1, -1);
    values[line.slice(0, at).trim()] = value;
  }
  return values;
}

function checkConfig(cfg, context) {
  const errors = [];
  const names = Object.keys(cfg.stacks);
  const secretsDir = context?.workspace ? join(context.workspace, "secrets") : null;
  for (const [name, s] of Object.entries(cfg.stacks)) {
    const base = `/stacks/${name}`;
    if ((s.repo === null) !== (s.path === null)) {
      errors.push({ path: `${base}/path`, message: "repo and path are both null (a stack the run starts but never edits) or both set" });
    } else if (s.repo !== null && s.path !== `repos/${s.repo}` && !s.path.startsWith(`repos/${s.repo}/`)) {
      errors.push({ path: `${base}/path`, message: `must be inside repos/${s.repo} (the stack's repo)` });
    }
    (s.depends_on ?? []).forEach((dep, i) => {
      if (dep === name) errors.push({ path: `${base}/depends_on/${i}`, message: "stack depends on itself" });
      else if (!names.includes(dep)) errors.push({ path: `${base}/depends_on/${i}`, message: `unknown stack "${dep}"` });
    });
    s.health.forEach((check, i) => {
      if (check.http && !/^https?:\/\//.test(check.http)) {
        errors.push({ path: `${base}/health/${i}/http`, message: `must be a full URL; write "http://localhost:${check.http}"` });
      }
    });
    const health = s.health.flatMap((c) => [c.http, String(c.tcp ?? "")]);
    const strings = [...Object.values(s.commands), s.dev_url, ...health, s.seed].filter(Boolean);
    for (const str of strings) {
      for (const [ref, stack] of str.matchAll(portRef)) {
        if (!names.includes(stack.toLowerCase())) {
          errors.push({ path: base, message: `${ref} refers to a stack "${stack.toLowerCase()}" that does not exist` });
        }
      }
    }
    if (secretsDir && (s.env_files ?? []).length) {
      const values = {};
      for (const file of s.env_files) {
        const path = join(secretsDir, name, file);
        if (!existsSync(path)) {
          errors.push({ path: `${base}/env_files`, message: `secrets/${name}/${file} is missing` });
          continue;
        }
        Object.assign(values, readEnvFile(path));  // later files win
      }
      for (const key of s.secrets ?? []) {
        if (!(key in values)) {
          errors.push({ path: `${base}/secrets`, message: `"${key}" is in no file under secrets/${name}/` });
        } else if (values[key].length > 0 && values[key].length < SECRET_FLOOR) {
          errors.push({ path: `${base}/secrets`, message: `"${key}" is ${values[key].length} characters; under ${SECRET_FLOOR} the scrubber shreds ordinary output instead of redacting (9.3)` });
        }
      }
    }
  }
  // A declared event with nothing behind it is two frictions on every run that say nothing about the feature.
  if ((cfg.notify?.events ?? []).length) {
    const ref = cfg.notify.telegram?.chat_id_ref;
    if (!ref) {
      errors.push({ path: "/notify/telegram", message: `events ${cfg.notify.events.join(", ")} are declared with no telegram.chat_id_ref to send them with` });
    } else if (secretsDir) {
      for (const file of [ref, "telegram_bot_token"]) {
        if (!existsSync(join(secretsDir, file))) {
          errors.push({ path: "/notify/events", message: `secrets/${file} is missing, so ${cfg.notify.events.join(", ")} cannot be sent; add it or empty notify.events` });
        }
      }
    }
  }
  const repos = new Set(Object.values(cfg.stacks).map((s) => s.repo).filter(Boolean));
  for (const repo of Object.keys(cfg.repos ?? {})) {
    if (!repos.has(repo)) errors.push({ path: `/repos/${repo}`, message: `no stack lives in repo "${repo}"` });
  }
  // A branch map is the whole answer for every repo the stacks name. A repo missing from it has no branch to cut
  // from and no branch to merge into, and the run would only find that out at the worktree.
  for (const key of ["base_branch", "target_branch"]) {
    const value = cfg.delivery[key];
    if (typeof value === "string") continue;
    const missing = [...repos].filter((r) => !(r in value)).sort();
    const unknown = Object.keys(value).filter((r) => !repos.has(r)).sort();
    if (missing.length) errors.push({ path: `/delivery/${key}`, message: `no branch for ${missing.join(", ")}; a branch per repo names every repo a stack lives in` });
    for (const repo of unknown) errors.push({ path: `/delivery/${key}/${repo}`, message: `no stack lives in repo "${repo}"` });
  }
  const cycle = findCycle(cfg.stacks);
  if (cycle) errors.push({ path: "/stacks", message: `depends_on cycle: ${cycle.join(" > ")}` });
  for (const key of ["client_tests", "test_runner", "browser_runner"]) {
    for (const stack of Object.keys(cfg[key] ?? {})) {
      if (!names.includes(stack)) errors.push({ path: `/${key}/${stack}`, message: `unknown stack "${stack}"` });
    }
  }
  // The baseline runs client_tests, the briefing hands the worker commands.test. Two commands for one suite means the
  // phase that proves the client is green and the agents that must keep it green are running different things.
  for (const [stack, command] of Object.entries(cfg.client_tests ?? {})) {
    const declared = cfg.stacks[stack]?.commands?.test;
    if (declared && declared !== command) {
      errors.push({ path: `/client_tests/${stack}`, message: `is "${command}" but /stacks/${stack}/commands/test is "${declared}"; one client suite, one command` });
    }
  }
  return errors;
}

function findCycle(stacks) {
  const state = {};
  const trail = [];
  const visit = (n) => {
    if (state[n] === "open") return [...trail.slice(trail.indexOf(n)), n];
    if (state[n] === "closed" || !stacks[n]) return null;
    state[n] = "open";
    trail.push(n);
    for (const dep of stacks[n].depends_on ?? []) {
      const cycle = visit(dep);
      if (cycle) return cycle;
    }
    trail.pop();
    state[n] = "closed";
    return null;
  };
  for (const n of Object.keys(stacks)) {
    const cycle = visit(n);
    if (cycle) return cycle;
  }
  return null;
}

function checkResult(r) {
  const errors = [];
  if (r.ask) {
    const letters = r.ask.options.map((o) => o.letter).join("");
    if (letters !== "ABC".slice(0, letters.length)) errors.push({ path: "/ask/options", message: `letters must run A, B, C in order; got ${letters}` });
  }
  return errors;
}

function checkState(st) {
  const errors = [];
  const ids = st.subtasks.map((s) => s.id);
  st.subtasks.forEach((s, i) => {
    if (ids.indexOf(s.id) !== i) errors.push({ path: `/subtasks/${i}/id`, message: `duplicate sub-task id "${s.id}"` });
    (s.depends_on ?? []).forEach((dep, j) => {
      if (!ids.includes(dep)) errors.push({ path: `/subtasks/${i}/depends_on/${j}`, message: `unknown sub-task "${dep}"` });
    });
  });
  for (const [repo, path] of Object.entries(st.worktrees)) {
    const expected = `.worktrees/${st.feature}/${repo}`;
    if (path !== expected) errors.push({ path: `/worktrees/${repo}`, message: `must be ${expected}` });
  }
  const cycle = findCycle(Object.fromEntries(st.subtasks.map((s) => [s.id, { depends_on: s.depends_on ?? [] }])));
  if (cycle) errors.push({ path: "/subtasks", message: `depends_on cycle: ${cycle.join(" > ")}` });
  st.subtasks.forEach((s, i) => {
    if (!s.worktree.startsWith(`.worktrees/${st.feature}/`)) {
      errors.push({ path: `/subtasks/${i}/worktree`, message: `must be under .worktrees/${st.feature}/` });
    }
  });
  return errors;
}
