#!/usr/bin/env node
/**
 * Fail if the task vocabulary's wrapper/inner split has been violated.
 *
 * Node variant of check_task_layout.py — use this one in a repo whose tooling
 * scripts are already JS/TS, so the check doesn't drag in a second toolchain.
 * Requires the `yaml` package.
 *
 * Two rules, both structural — no per-stack configuration:
 *
 * 1. The root `Taskfile.yml` holds wrappers only. Every `cmds:` entry in it
 *    must be a `task:` call into a namespace file, never raw shell. Anything
 *    that shells out to a real tool belongs in the namespace file that owns it.
 * 2. Every task, in the root file and in every `tasks/*.yml`, carries a
 *    non-empty `desc:`. That is what keeps `task --list` self-documenting.
 *
 * Usage: node check_task_layout.mjs [repo-root]   (default: current directory)
 */

import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { parse } from "yaml";

/** The `tasks:` mapping of a Taskfile, or empty if there isn't one. */
function taskSpecs(document) {
  const tasks = document?.tasks;
  return tasks && typeof tasks === "object" && !Array.isArray(tasks) ? tasks : {};
}

function checkDesc(label, name, spec) {
  const desc = spec && typeof spec === "object" && !Array.isArray(spec) ? spec.desc : undefined;
  return String(desc ?? "").trim()
    ? []
    : [`${label}: task \`${name}\` has no non-empty \`desc:\``];
}

/** Every cmds entry in the root file must be a `task:` call. */
function checkWrapperOnly(label, name, spec) {
  // `name: echo hi` and `name: [a, b]` are go-task shorthand for raw shell.
  if (typeof spec === "string" || Array.isArray(spec)) {
    return [
      `${label}: task \`${name}\` is shorthand for a raw shell command — the root file holds wrappers only`,
    ];
  }
  if (!spec || typeof spec !== "object" || spec.cmds == null) return [];

  const cmds = Array.isArray(spec.cmds) ? spec.cmds : [spec.cmds];
  return cmds.flatMap((entry, index) => {
    if (entry && typeof entry === "object" && "task" in entry) return [];
    const shown = typeof entry === "string" ? JSON.stringify(entry) : typeof entry;
    return [
      `${label}: task \`${name}\` cmds[${index}] is not a \`task:\` call (${shown}) — ` +
        `move the command into the namespace file that owns it and call it from here`,
    ];
  });
}

function main() {
  const root = resolve(process.argv[2] ?? ".");
  const rootTaskfile = join(root, "Taskfile.yml");

  if (!existsSync(rootTaskfile)) {
    console.log(`${rootTaskfile}: not found`);
    return 1;
  }

  const errors = [];

  const document = parse(readFileSync(rootTaskfile, "utf8"));
  for (const [name, spec] of Object.entries(taskSpecs(document))) {
    errors.push(...checkDesc("Taskfile.yml", name, spec));
    errors.push(...checkWrapperOnly("Taskfile.yml", name, spec));
  }

  const tasksDir = join(root, "tasks");
  if (existsSync(tasksDir)) {
    for (const entry of readdirSync(tasksDir).filter((f) => f.endsWith(".yml")).sort()) {
      const parsed = parse(readFileSync(join(tasksDir, entry), "utf8"));
      for (const [name, spec] of Object.entries(taskSpecs(parsed))) {
        errors.push(...checkDesc(`tasks/${entry}`, name, spec));
      }
    }
  }

  if (errors.length) {
    errors.forEach((error) => console.log(error));
    return 1;
  }

  return 0;
}

process.exit(main());
