import { readFileSync } from "node:fs";
import { basename, extname } from "node:path";
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
  return validate(load(file), schema);
}

export function validate(data, schema) {
  const check = compiled[schema];
  if (!check) throw new Error(`unknown schema "${schema}"`);
  if (!check(data)) return { ok: false, pass: "schema", errors: format(check.errors) };
  const errors = { config: checkConfig, state: checkState, result: checkResult }[schema](data);
  return { ok: errors.length === 0, pass: "cross-field", errors };
}

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
      case "additionalProperties": push(`${e.instancePath}/${p.additionalProperty}`, `unexpected key "${p.additionalProperty}"`); break;
      case "propertyNames": push(`${e.instancePath}/${p.propertyName}`, `invalid key "${p.propertyName}"`); break;
      case "enum": push(e.instancePath, `must be one of: ${p.allowedValues.join(", ")}`); break;
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

function checkConfig(cfg) {
  const errors = [];
  const names = Object.keys(cfg.stacks);
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
    const strings = [...Object.values(s.commands), s.dev_url, s.health.http, String(s.health.tcp || ""), s.seed].filter(Boolean);
    for (const str of strings) {
      for (const [ref, stack] of str.matchAll(portRef)) {
        if (!names.includes(stack.toLowerCase())) {
          errors.push({ path: base, message: `${ref} refers to a stack "${stack.toLowerCase()}" that does not exist` });
        }
      }
    }
  }
  const repos = new Set(Object.values(cfg.stacks).map((s) => s.repo).filter(Boolean));
  for (const repo of Object.keys(cfg.repos ?? {})) {
    if (!repos.has(repo)) errors.push({ path: `/repos/${repo}`, message: `no stack lives in repo "${repo}"` });
  }
  const cycle = findCycle(cfg.stacks);
  if (cycle) errors.push({ path: "/stacks", message: `depends_on cycle: ${cycle.join(" > ")}` });
  for (const key of ["client_tests", "test_runner", "browser_runner"]) {
    for (const stack of Object.keys(cfg[key] ?? {})) {
      if (!names.includes(stack)) errors.push({ path: `/${key}/${stack}`, message: `unknown stack "${stack}"` });
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
  st.subtasks.forEach((s, i) => {
    if (!s.worktree.startsWith(`.worktrees/${st.feature}/`)) {
      errors.push({ path: `/subtasks/${i}/worktree`, message: `must be under .worktrees/${st.feature}/` });
    }
  });
  return errors;
}
