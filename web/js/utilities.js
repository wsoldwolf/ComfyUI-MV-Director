import { app } from "../../../scripts/app.js";

const MAX_TEXT_BYTES = 16 * 1024 * 1024;

function widget(node, name) {
  return node.widgets?.find((item) => item.name === name);
}

function hideSerializedWidget(item) {
  if (!item) return;
  item.type = "hidden";
  item.computeSize = () => [0, -4];
}

function parseStringList(value) {
  const result = [];
  let current = "";
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] !== "|") {
      current += value[index];
    } else if (value[index + 1] === "|") {
      current += "|";
      index += 1;
    } else {
      result.push(current.trim());
      current = "";
    }
  }
  result.push(current.trim());
  return result;
}

function setComboCandidates(item, values) {
  if (!item) return;
  item.type = "combo";
  item.options ??= {};
  item.options.values = values;
}

function linkedComboValues(node) {
  const links = node.outputs?.[0]?.links ?? [];
  const values = [];
  for (const linkId of links) {
    const link = app.graph?.links?.[linkId];
    const target = app.graph?.getNodeById?.(link?.target_id);
    const input = target?.inputs?.[link?.target_slot];
    const targetWidget = target?.widgets?.find(
      (item) => item.name === input?.widget?.name || item.name === input?.name
    );
    let candidates = targetWidget?.options?.values;
    if (typeof candidates === "function") candidates = candidates();
    if (!Array.isArray(candidates)) continue;
    for (const candidate of candidates) {
      if (typeof candidate === "string" && !values.includes(candidate)) {
        values.push(candidate);
      }
    }
  }
  return values;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

async function embedTextFile(node, file) {
  if (!file?.name?.toLowerCase().endsWith(".txt")) {
    throw new Error("MV Director Load Text File accepts .txt only.");
  }
  if (file.size > MAX_TEXT_BYTES) {
    throw new Error("The text file exceeds the 16 MiB limit.");
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  widget(node, "file_data_base64").value = bytesToBase64(bytes);
  widget(node, "basename").value = file.name;
  widget(node, "browser_metadata_json").value = JSON.stringify({
    lastModified: file.lastModified,
    size: file.size,
    type: file.type || "text/plain",
  });
  const display = widget(node, "selected_file");
  if (display) display.value = file.name;
  node.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "MVDirector.Utilities",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name === "MVDirectorSeed32") {
      const original = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = original?.apply(this, arguments);
        this.addWidget("button", "randomize once", null, () => {
          const data = new Uint32Array(1);
          crypto.getRandomValues(data);
          widget(this, "seed").value = (data[0] % 2147483647) + 1;
          widget(this, "mode").value = "fixed";
          this.setDirtyCanvas(true, true);
        });
        return result;
      };
    }

    if (nodeData.name === "MVDirectorStringCombo") {
      const original = nodeType.prototype.onNodeCreated;
      const originalConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onNodeCreated = function () {
        const result = original?.apply(this, arguments);
        const source = widget(this, "string_list");
        const selected = widget(this, "selected_value");
        const refresh = () => {
          const values = parseStringList(String(source?.value ?? ""));
          setComboCandidates(selected, values);
          this.setDirtyCanvas(true, true);
        };
        const callback = source?.callback;
        if (source) source.callback = (...args) => { callback?.apply(source, args); refresh(); };
        refresh();
        return result;
      };
      nodeType.prototype.onConfigure = function () {
        const result = originalConfigure?.apply(this, arguments);
        setComboCandidates(
          widget(this, "selected_value"),
          parseStringList(String(widget(this, "string_list")?.value ?? ""))
        );
        return result;
      };
    }

    if (nodeData.name === "MVDirectorConnectedCombo") {
      const original = nodeType.prototype.onNodeCreated;
      const originalConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onNodeCreated = function () {
        const result = original?.apply(this, arguments);
        hideSerializedWidget(widget(this, "enum_values_json"));
        return result;
      };
      nodeType.prototype.onConfigure = function () {
        const result = originalConfigure?.apply(this, arguments);
        let values = [];
        try { values = JSON.parse(widget(this, "enum_values_json")?.value ?? "[]"); }
        catch (_) { values = []; }
        setComboCandidates(widget(this, "selected_value"), Array.isArray(values) ? values : []);
        return result;
      };
      const originalConnections = nodeType.prototype.onConnectionsChange;
      nodeType.prototype.onConnectionsChange = function () {
        const result = originalConnections?.apply(this, arguments);
        queueMicrotask(() => {
          const values = linkedComboValues(this);
          const stored = widget(this, "enum_values_json");
          if (stored) stored.value = JSON.stringify(values);
          setComboCandidates(widget(this, "selected_value"), values);
          this.setDirtyCanvas(true, true);
        });
        return result;
      };
    }

    if (nodeData.name === "MVDirectorLoadTextFile") {
      const original = nodeType.prototype.onNodeCreated;
      const originalConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onNodeCreated = function () {
        const result = original?.apply(this, arguments);
        hideSerializedWidget(widget(this, "file_data_base64"));
        hideSerializedWidget(widget(this, "basename"));
        hideSerializedWidget(widget(this, "browser_metadata_json"));
        const display = this.addWidget("text", "selected_file", "No file selected", () => {}, { serialize: false });
        display.disabled = true;
        this.addWidget("button", "select .txt file", null, () => {
          const input = document.createElement("input");
          input.type = "file";
          input.accept = ".txt,text/plain";
          input.onchange = async () => {
            try { await embedTextFile(this, input.files?.[0]); }
            catch (error) { alert(error.message); }
          };
          input.click();
        });
        const originalDrop = this.onDragDrop;
        this.onDragDrop = async (event) => {
          const file = event?.dataTransfer?.files?.[0];
          if (!file) return originalDrop?.call(this, event) ?? false;
          try { await embedTextFile(this, file); }
          catch (error) { alert(error.message); }
          return true;
        };
        const originalOver = this.onDragOver;
        this.onDragOver = (event) => {
          if (event?.dataTransfer?.types?.includes("Files")) return true;
          return originalOver?.call(this, event) ?? false;
        };
        return result;
      };
      nodeType.prototype.onConfigure = function () {
        const result = originalConfigure?.apply(this, arguments);
        const display = widget(this, "selected_file");
        const basename = widget(this, "basename")?.value;
        if (display && basename) display.value = basename;
        return result;
      };
    }
  },
});
