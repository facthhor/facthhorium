// Keep old observation pixels in the Pi session and fit the outbound request to Loom.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const imageLimit = 16; // program/control.loom, chat_image_limits
const routes = new Set([
  "inkling-2-facthhorium", "inkling-preview", "inkling-2-mini-loom", "inkling-2-mini-256k-vision",
]);
const observationTools = new Set(["look", "computer_capture", "computer_wait", "computer_input"]);

export default function facthhoriumImages(pi: ExtensionAPI) {
  pi.on("context", (event, ctx) => {
    if (ctx.model?.provider !== "llamaswap" || !routes.has(ctx.model.id)) return;
    const messages = event.messages;
    let current = messages.length;
    while (current && messages[current - 1].role === "toolResult") current--;

    let total = 0;
    for (const message of messages) {
      if (!("content" in message) || !Array.isArray(message.content)) continue;
      total += message.content.filter(block => block.type === "image").length;
    }
    if (total <= imageLimit) return;
    let excess = total - imageLimit;
    const limited = messages.map((message, index) => {
      if (!excess || index >= current || message.role !== "toolResult" ||
          !observationTools.has(message.toolName)) return message;
      let removed = 0;
      const content = message.content.filter(block => {
        if (block.type !== "image" || !excess) return true;
        excess--;
        removed++;
        return false;
      });
      if (!removed) return message;
      content.push({ type: "text", text: "[Earlier observation image omitted from this request.]" });
      return { ...message, content };
    });
    if (excess < total - imageLimit) return { messages: limited };
  });
}
