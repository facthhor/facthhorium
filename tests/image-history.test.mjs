import assert from "node:assert/strict";
import test from "node:test";
import extension, { dropCount } from "../pi/facthhorium-images.ts";

let send;
extension({ on(name, handler) { assert.equal(name, "context"); send = handler; } });
const ctx = { model: { provider: "llamaswap", id: "inkling-2-facthhorium" } };
const image = {type:"image",data:"pixel",mimeType:"image/png"};
const observe = (n) => ({role:"toolResult",toolName:"look",toolCallId:String(n),content:[{type:"text",text:String(n)},image]});
const reply = {role:"assistant",content:[{type:"text",text:"next"}]};
const images = (messages) => messages.flatMap(m=>m.content).filter(b=>b.type==="image").length;

test("preserves user attachments, other tools and the current observation while aging old look results", () => {
  const user = {role:"user",content:[image]};
  const other = {...observe(-1),toolName:"read"};
  const turns = Array.from({length:20},(_,n)=>[reply,observe(n)]).flat();
  const messages=[user,other,...turns];
  const out=send({messages},ctx).messages;
  // 22 images: one batch of 8 dropped, 14 kept.
  assert.equal(images(out),14);
  assert.equal(out[0],user);
  assert.equal(out[1],other);
  assert.equal(out.at(-1),messages.at(-1));
  assert.equal(out[3].toolCallId,"0");
  assert.equal(out[3].content[0].text,"0");
  assert.match(out[3].content[1].text,/Earlier look screenshot omitted/);
  assert.equal(messages[3].content[1],image);
});

test("drops in batches so the kept count stays between 8 and 15", () => {
  for (let total = 0; total <= 16; total++) assert.equal(dropCount(total), 0);
  for (let total = 17; total <= 200; total++) {
    const kept = total - dropCount(total);
    assert.ok(kept >= 8 && kept <= 15, `total ${total} kept ${kept}`);
    assert.equal(dropCount(total) % 8, 0);
  }
});

test("keeps the request prefix byte-identical between trims", () => {
  // One screenshot per turn. Between batch boundaries, each request must
  // start with exactly the previous request, so Loom's prefix cache hits.
  let previous, changes = 0;
  for (let n = 1; n <= 40; n++) {
    const messages = [{role:"user",content:[{type:"text",text:"go"}]},
      ...Array.from({length:n},(_,i)=>[reply,observe(i)]).flat()];
    const out = (send({messages},ctx) ?? {messages}).messages;
    assert.ok(images(out) <= 16);
    if (previous) {
      const before = JSON.stringify(previous);
      const now = JSON.stringify(out.slice(0, previous.length));
      if (before !== now) changes++;
    }
    previous = out;
  }
  // Trims first apply at 17 images, then at 24, 32 and 40.
  assert.equal(changes, 4);
});

test("leaves other profiles, fitting requests, and oversized explicit inputs intact", () => {
  assert.equal(send({messages:[observe(0)]},ctx),undefined);
  const messages=[{role:"user",content:Array(17).fill(image)},observe(0)];
  assert.equal(send({messages},ctx),undefined);
  assert.equal(send({messages},{model:{provider:"llamaswap",id:"other"}}),undefined);
});
