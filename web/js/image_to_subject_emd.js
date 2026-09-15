import { app } from "../../../scripts/app.js";

app.registerExtension({
  name: "MVDirector.ImageToSubjectEMD",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "MVDirectorImageToSubjectEMD") return;
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = original?.apply(this, arguments);
      const widget = this.addWidget(
        "text",
        "resolved_picture_reference",
        "unbound",
        () => {},
        { serialize: false }
      );
      widget.disabled = true;
      return result;
    };
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const value = message?.resolved_picture_reference?.[0];
      const widget = this.widgets?.find(
        (item) => item.name === "resolved_picture_reference"
      );
      if (widget && typeof value === "string") widget.value = value;
      this.setDirtyCanvas(true, true);
    };
  },
});
