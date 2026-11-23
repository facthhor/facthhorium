import assert from "node:assert/strict";
import test from "node:test";
import extension from "../pi/facthhorium-images.ts";

let send;
extension({ on(name, handler) { assert.equal(name, "context"); send = handler; } });
const ctx = { model: { provider: "llamaswap", id: "inkling-2-facthhorium" } };
const image = {type:"image",data:"pixel",mimeType:"image/png"};
const observe = (n) => ({role:"toolResult",toolName:"look",toolCallId:String(n),content:[{type:"text",text:String(n)},image]});
const reply = {role:"assistant",content:[{type:"text",text:"next"}]};
test("preserves user attachments, other tools and the current observation while aging old look results", () => {
  const user = {role:"user",content:[image]};
  const other = {...observe(-1),toolName:"read"};
  const turns = Array.from({length:20},(_,n)=>[reply,observe(n)]).flat();
  const messages=[user,other,...turns];
  const out=send({messages},ctx).messages;
  assert.equal(out.flatMap(m=>m.content).filter(b=>b.type==="image").length,16);
  assert.equal(out[0],user);
  assert.equal(out[1],other);
  assert.equal(out.at(-1),messages.at(-1));
  assert.equal(out[3].toolCallId,"0");
  assert.equal(out[3].content[0].text,"0");
  assert.match(out[3].content[1].text,/omitted/);
  assert.equal(messages[3].content[1],image);
});
test("leaves other profiles, fitting requests, and oversized explicit inputs intact", () => {
  assert.equal(send({messages:[observe(0)]},ctx),undefined);
  const messages=[{role:"user",content:Array(17).fill(image)},observe(0)];
  assert.equal(send({messages},ctx),undefined);
  assert.equal(send({messages},{model:{provider:"llamaswap",id:"other"}}),undefined);
});
