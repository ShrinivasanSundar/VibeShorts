import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { initializeTestEnvironment, assertFails, assertSucceeds } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc } from "firebase/firestore";
import { ref, uploadBytes, getBytes } from "firebase/storage";

let env;
before(async () => {
  env = await initializeTestEnvironment({ projectId: "demo-vibeshorts", firestore: {
    rules: readFileSync(new URL("../../infrastructure/firestore.rules", import.meta.url), "utf8"),
  }, storage: { rules: readFileSync(new URL("../../infrastructure/storage.rules", import.meta.url), "utf8") } });
  await env.withSecurityRulesDisabled(async (context) => {
    const db = context.firestore();
    await setDoc(doc(db, "users/alice"), { access_enabled: true });
    await setDoc(doc(db, "users/bob"), { access_enabled: true });
    await setDoc(doc(db, "users/disabled"), { access_enabled: false });
    await setDoc(doc(db, "projects/rules-project"), { members: { alice: "owner", disabled: "viewer" } });
    await setDoc(doc(db, "projects/rules-project/run_summaries/run"), { status: "queued" });
    await setDoc(doc(db, "projects/rules-project/conversations/chat"), { revision: 1 });
    await setDoc(doc(db, "projects/rules-project/conversations/chat/messages/message"), { text: "private" });
  });
});
after(async () => { await env?.cleanup(); });

test("only enabled project members read summaries", async () => {
  await assertSucceeds(getDoc(doc(env.authenticatedContext("alice").firestore(), "projects/rules-project/run_summaries/run")));
  for (const context of [env.authenticatedContext("bob"), env.authenticatedContext("disabled"), env.unauthenticatedContext()]) {
    await assertFails(getDoc(doc(context.firestore(), "projects/rules-project/run_summaries/run")));
  }
});
test("only enabled project members read a conversation, never its messages", async () => {
  const alice = env.authenticatedContext("alice").firestore();
  await assertSucceeds(getDoc(doc(alice, "projects/rules-project/conversations/chat")));
  await assertFails(getDoc(doc(alice, "projects/rules-project/conversations/chat/messages/message")));
  await assertFails(setDoc(doc(alice, "projects/rules-project/conversations/chat"), { revision: 2 }));
  for (const context of [env.authenticatedContext("bob"), env.authenticatedContext("disabled"), env.unauthenticatedContext()]) {
    await assertFails(getDoc(doc(context.firestore(), "projects/rules-project/conversations/chat")));
  }
});
test("browser cannot alter execution, budgets, grants or artifact records", async () => {
  const db = env.authenticatedContext("alice").firestore();
  for (const path of ["projects/rules-project", "projects/rules-project/jobs/job", "projects/rules-project/runs/run", "projects/rules-project/run_summaries/run", "projects/rules-project/artifacts/art", "budgets/rules-project", "oauth_grants/grant", "users/alice"]) {
    await assertFails(setDoc(doc(db, path), { access_enabled: true }));
  }
  await assertFails(getDoc(doc(db, "projects/rules-project/jobs/job")));
  await assertFails(getDoc(doc(db, "projects/rules-project/runs/run")));
});
test("storage is private even to project members", async () => {
  const file = ref(env.authenticatedContext("alice").storage(), "projects/rules-project/secret.png");
  await assertFails(uploadBytes(file, new Uint8Array([1, 2, 3])));
  await assertFails(getBytes(file));
});
