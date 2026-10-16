import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const wf = JSON.parse(readFileSync(new URL("../workflows/02_video_generator.json", import.meta.url)));
const config = wf.extra.mv_director.execution_paths;
const script = readFileSync(new URL("../web/js/execution_paths.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?\n/gm, "").replace(/export function /g, "function ") +
  "\nglobalThis.helpers = {selectExecutionPath, executionPathError};";

function environment() {
  const sent = [], notices = [];
  const app = { registerExtension: (e) => { app.extension = e; },
    ui: { dialog: { show: (text) => notices.push(text) } } };
  const api = { queuePrompt: async (...args) => { sent.push(args); return { prompt_id: "fake" }; } };
  const ctx = vm.createContext({ app, api, queueMicrotask, console });
  new vm.Script(script).runInContext(ctx);
  const graph = { nodes: structuredClone(wf.nodes), getNodeById(id) { return this.nodes.find(n => n.id === id); },
    setDirtyCanvas() {}, beforeChange() {}, afterChange() {} };
  return { ...ctx.helpers, app, api, sent, notices, graph };
}

test("explicit modes are mutually exclusive and leave every optional bypass intact", () => {
  const e = environment(), original = structuredClone(e.graph.nodes);
  for (const path of ["reassembly", "generation", "reassembly"]) {
    e.selectExecutionPath(e.graph, config, path);
    for (const role of ["generation", "reassembly"]) {
      for (const id of config[`${role}_node_ids`]) {
        assert.equal(e.graph.getNodeById(id).mode, role === path ? 0 : 2);
      }
    }
  }
  const managed = [...config.generation_node_ids, ...config.reassembly_node_ids];
  for (const before of original.filter(n => !managed.includes(n.id))) {
    assert.deepEqual(e.graph.getNodeById(before.id), before);
  }
});

test("missing nodes do not cause a half-applied mode switch", () => {
  const e = environment();
  e.graph.nodes = e.graph.nodes.filter(n => n.id !== config.reassembly_node_ids[0]);
  const before = structuredClone(e.graph.nodes);
  assert.throws(() => e.selectExecutionPath(e.graph, config, "reassembly"), /missing/);
  assert.deepEqual(e.graph.nodes, before);
});

test("native Note buttons survive widget prototype adoption and are not on rgthree", async () => {
  const e = environment();
  const control = e.graph.getNodeById(config.controller_id);
  control.graph = e.graph;
  control.widgets = [];
  control.addWidget = (type, name, value, callback, options) => {
    const w = { type, name, value, callback, options }; control.widgets.push(w); return w;
  };
  e.app.extension.loadedGraphNode(control);
  await new Promise(queueMicrotask);
  assert.equal(control.widgets.length, 2);
  for (const w of control.widgets) Object.setPrototypeOf(w, null);
  control.widgets[1].callback();
  assert.ok(config.generation_node_ids.every(id => e.graph.getNodeById(id).mode === 2));
  control.widgets[0].callback();
  assert.ok(config.reassembly_node_ids.every(id => e.graph.getNodeById(id).mode === 2));
  assert.ok(control.widgets.every(w => w.serialize === false));
  e.app.extension.loadedGraphNode(control);
  await new Promise(queueMicrotask);
  assert.equal(control.widgets.length, 2, "reload hooks must not duplicate buttons");
  const rg = e.graph.getNodeById(config.rgthree_controller_id);
  rg.addWidget = () => { throw new Error("must not attach removable widgets to rgthree"); };
  e.app.extension.loadedGraphNode(rg);
  await new Promise(queueMicrotask);
});

test("actual mixed API output is rejected without sending or changing it", async () => {
  const e = environment(); e.app.extension.setup();
  const output = { [config.generation_output_ids[0]]: {}, [config.reassembly_output_ids[0]]: {} };
  const prompt = { workflow: wf, output }, before = structuredClone(prompt);
  await assert.rejects(e.api.queuePrompt(0, prompt), /MV Director/);
  assert.equal(e.sent.length, 0);
  assert.equal(e.notices.length, 1);
  assert.deepEqual(prompt, before);
});

for (const role of ["generation", "reassembly"]) {
  test(`a ${role}-only payload is passed unchanged`, async () => {
    const e = environment(); e.app.extension.setup();
    const prompt = { workflow: wf, output: { [config[`${role}_output_ids`][0]]: {} } };
    await e.api.queuePrompt(3, prompt, "unchanged");
    assert.equal(e.sent.length, 1);
    assert.equal(e.sent[0][1], prompt);
    assert.equal(e.sent[0][2], "unchanged");
  });
}

test("untagged workflows are unaffected even with matching node IDs", async () => {
  const e = environment(); e.app.extension.setup();
  await e.api.queuePrompt(0, { workflow: { extra: {} }, output: {
    [config.generation_output_ids[0]]: {}, [config.reassembly_output_ids[0]]: {},
  } });
  assert.equal(e.sent.length, 1);
});
