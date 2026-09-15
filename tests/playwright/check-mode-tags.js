#!/usr/bin/env node
/**
 * Fail if any Playwright spec test lacks a CI mode tag.
 *
 * Required tags:
 *   @both         — safe under inplace and legacy reload modes
 *   @inplace-only — requires default inplace_timeline_transitions
 *   @legacy-only  — requires inplace_timeline_transitions=false
 */
const { spawnSync } = require("child_process");

const result = spawnSync(
  "npx",
  [
    "playwright",
    "test",
    "--list",
    "--grep-invert",
    "@both|@inplace-only|@legacy-only",
  ],
  { encoding: "utf8", shell: false }
);

const output = `${result.stdout || ""}${result.stderr || ""}`;
if (/Total:\s*0 tests/.test(output)) {
  process.exit(0);
}

process.stderr.write(
  "Untagged Playwright tests found. Tag each test with @both, " +
    "@inplace-only, or @legacy-only so CI can select without hardcoding " +
    "file paths.\n\n"
);
process.stderr.write(output);
process.exit(1);
