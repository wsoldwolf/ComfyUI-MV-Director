import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const SCHEMA = "mvd-execution-paths-v1";
const ACTIVE = 0;
const MUTED = 2;

// These helpers deliberately use native node modes, not rgthree widget classes.
// New frontends can adopt widgets and replace their prototypes (rgthree #770).
export function selectExecutionPath(graph, config, path) {
  if (config?.schema !== SCHEMA || !["generation", "reassembly"].includes(path)) {
    throw new Error("MV Director: unknown execution-path configuration.");
  }
  const ids = [...config.generation_node_ids, ...config.reassembly_node_ids];
  const nodes = ids.map((id) => graph.getNodeById(id));
  if (nodes.some((node) => !node)) {
    throw new Error("MV Director: execution nodes are missing; reload the original WF.");
  }
  const enabled = new Set(config[`${path}_node_ids`].map(String));
  graph.beforeChange?.();
  try {
    for (const node of nodes) node.mode = enabled.has(String(node.id)) ? ACTIVE : MUTED;
  } finally {
    graph.afterChange?.();
  }
  graph.setDirtyCanvas?.(true, true);
}

export function executionPathError(output, config) {
  if (config?.schema !== SCHEMA) return null;
  const contains = (ids) => ids.some((id) => Object.hasOwn(output ?? {}, String(id)));
  if (contains(config.generation_output_ids) && contains(config.reassembly_output_ids)) {
    return "MV Director: 通常生成と再連結の両方が有効なため送信を停止しました。" +
      "切替パネルの『通常生成に切替』または『再連結に切替』を押し、片方だけを有効にしてください。";
  }
  return null;
}

function notify(message) {
  if (app.extensionManager?.toast?.add) {
    app.extensionManager.toast.add({ severity: "error", summary: "MV Director", detail: message, life: 12000 });
  } else {
    app.ui?.dialog?.show(message);
  }
}

function addControls(node) {
  if (node.type === "Fast Groups Muter (rgthree)") return;
  const config = node.properties?.mv_director_execution_control;
  if (config?.schema !== SCHEMA) return;
  for (const [path, title] of [
    ["generation", "通常生成に切替 / GENERATE"],
    ["reassembly", "再連結に切替 / REASSEMBLE"],
  ]) {
    if (node.widgets?.some((widget) => widget.name === title)) continue;
    const widget = node.addWidget("button", title, null, () => {
      try {
        selectExecutionPath(node.graph, config, path);
      } catch (error) {
        notify(error.message);
      }
    }, { serialize: false });
    widget.serialize = false;
  }
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "MVDirector.ExecutionPaths",
  setup() {
    const original = api.queuePrompt;
    api.queuePrompt = async function (number, prompt, ...rest) {
      // Check the actual API payload, not visual group labels or cached state.
      // Applies only to workflows explicitly tagged by our migration.
      const config = prompt?.workflow?.extra?.mv_director?.execution_paths;
      const error = executionPathError(prompt?.output, config);
      if (error) {
        notify(error);
        throw new Error(error);
      }
      return original.call(this, number, prompt, ...rest);
    };
  },
  loadedGraphNode(node) {
    // Use a separate native Note: rgthree rebuilds its own widget list.
    queueMicrotask(() => addControls(node));
  },
  nodeCreated(node) {
    if (node.type !== "Fast Groups Muter (rgthree)") return;
    const original = node.getExtraMenuOptions;
    node.getExtraMenuOptions = function (_, options) {
      const result = original?.apply(this, arguments);
      if (this.properties?.mv_director_execution_control?.schema === SCHEMA) {
        options.push(null, ...[
          ["generation", "MV Director: 通常生成に切替"],
          ["reassembly", "MV Director: 再連結に切替"],
        ].map(([path, content]) => ({ content, callback: () => {
          try { selectExecutionPath(this.graph, this.properties.mv_director_execution_control, path); }
          catch (error) { notify(error.message); }
        } })));
      }
      return result;
    };
  },
});
