// Keep old observation pixels in the Pi session and fit the outbound request to Loom.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const imageLimit = 16; // program/control.loom, chat_image_limits
// Trim in batches so the request prefix stays byte-identical between trims and
// Loom's prefix cache keeps hitting. Dropping one image per new screenshot would
// change early history on every turn and force a full re-prefill.
const batch = 8;
const routes = new Set([
  "inkling-2-facthhorium", "inkling-preview", "inkling-2-mini-loom", "inkling-2-mini-256k-vision",
]);
const observationTools = new Set(["look", "computer_capture", "computer_wait", "computer_input"]);

// Images to drop for a request holding `total` images. Constant across each run
// of `batch` new images, and always leaves between 8 and 15 kept.
export function dropCount(total: number): number {
  if (total <= imageLimit) return 0;
  return Math.floor((total - (imageLimit - batch)) / batch) * batch;
}

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
    let excess = dropCount(total);
    if (!excess) return;
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
      const what = removed === 1 ? "screenshot" : `${removed} screenshots`;
      content.push({ type: "text", text: `[Earlier ${message.toolName} ${what} omitted to fit the image limit.]` });
      return { ...message, content };
    });
    if (limited.some((message, index) => message !== messages[index])) return { messages: limited };
  });
}
