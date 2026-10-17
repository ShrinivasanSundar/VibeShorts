import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";

async function signIn(page: Page, request: APIRequestContext) {
  const email = `browser-${crypto.randomUUID()}@example.test`;
  const response = await request.post(
    "http://127.0.0.1:19099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-key",
    {
      data: {
        email,
        password: "fixture-password-123",
        returnSecureToken: true,
      },
    },
  );
  expect(response.ok()).toBeTruthy();
  const auth = await response.json();
  await page.goto("/");
  await page.evaluate(
    async ({ auth, email }) => {
      const value = {
        uid: auth.localId,
        email,
        emailVerified: false,
        isAnonymous: false,
        providerData: [{ providerId: "password", uid: email, email }],
        stsTokenManager: {
          refreshToken: auth.refreshToken,
          accessToken: auth.idToken,
          expirationTime: Date.now() + 3600000,
        },
        apiKey: "demo-key",
        appName: "[DEFAULT]",
      };
      const key = "firebase:authUser:demo-key:[DEFAULT]";
      localStorage.setItem(key, JSON.stringify(value));
      await new Promise<void>((resolve, reject) => {
        const open = indexedDB.open("firebaseLocalStorageDb", 1);
        open.onupgradeneeded = () =>
          open.result.createObjectStore("firebaseLocalStorage", {
            keyPath: "fbase_key",
          });
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const db = open.result;
          const transaction = db.transaction(
            "firebaseLocalStorage",
            "readwrite",
          );
          transaction
            .objectStore("firebaseLocalStorage")
            .put({ fbase_key: key, value });
          transaction.oncomplete = () => {
            db.close();
            resolve();
          };
          transaction.onerror = () => reject(transaction.error);
        };
      });
    },
    { auth, email },
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your projects" }),
  ).toBeVisible();
  return auth.idToken as string;
}

async function openProject(page: Page, request: APIRequestContext) {
  const token = await signIn(page, request);
  const title = `Browser video ${crypto.randomUUID().slice(0, 6)}`;
  await page.getByLabel("New project").fill(title);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await expect(
    page.getByRole("heading", { name: "What’s your story?" }),
  ).toBeVisible();
  return token;
}

async function send(page: Page, text: string) {
  await page.getByLabel("Message your video director").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

async function createVideo(page: Page) {
  await page
    .getByRole("button", { name: "Approve and create video", exact: true })
    .click();
  await expect(page.getByLabel("Keyframe 1")).toBeVisible();
  await page
    .getByRole("button", { name: "Approve and create videos", exact: true })
    .click();
  await expect(page.getByLabel("Combined video preview")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toHaveCount(0);
}

test("unified creation, automatic production, optional editing and exact export", async ({
  page,
  request,
}) => {
  await openProject(page, request);
  await expect(
    page.getByRole("button", { name: /Advanced mode|Chat mode/ }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Video timeline canvas")).toHaveCount(0);
  await page.screenshot({
    path: "../.cache/browser-results/unified-idea.png",
    fullPage: true,
  });
  await page
    .getByRole("group", { name: "Vibe", exact: true })
    .getByRole("button", { name: "Cinematic", exact: true })
    .click();
  await send(page, "A 6 second story about a tiny robot");
  await expect(
    page.getByRole("button", { name: "Approve and create video", exact: true }),
  ).toBeVisible();
  await send(page, "Change scene 2 to a sunny garden");
  await expect(
    page.getByText("Change scene 2 to a sunny garden", { exact: true }),
  ).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Approve and create video", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.cache/browser-results/unified-storyboard.png",
    fullPage: true,
  });
  await createVideo(page);
  await expect(page.getByLabel("Video timeline canvas")).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Video stages" })
    .getByRole("button", { name: "Scenes", exact: true })
    .click();
  await page
    .getByLabel("Preview scene-1")
    .evaluate((element) => (element as HTMLVideoElement).play());
  await expect
    .poll(() =>
      page
        .getByLabel("Preview scene-1")
        .evaluate((element) => (element as HTMLVideoElement).paused),
    )
    .toBe(false);
  await page
    .getByRole("navigation", { name: "Video stages" })
    .getByRole("button", { name: "Preview", exact: true })
    .click();
  await page
    .getByLabel("Combined video preview")
    .evaluate((element) => (element as HTMLVideoElement).play());
  await expect
    .poll(() =>
      page
        .getByLabel("Combined video preview")
        .evaluate((element) => (element as HTMLVideoElement).currentTime),
    )
    .toBeGreaterThan(0);
  await page
    .getByLabel("Combined video preview")
    .evaluate((element) => (element as HTMLVideoElement).pause());
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Select text clip Opening").click();
  await page.getByLabel("On-screen copy", { exact: true }).fill("Hello robot");
  await page
    .getByRole("button", { name: "Collapse agent", exact: true })
    .click();
  await expect(page.getByLabel("On-screen copy", { exact: true })).toHaveValue(
    "Hello robot",
  );
  await page.screenshot({
    path: "../.cache/browser-results/unified-editor.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Back to preview", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("button", { name: "New video", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Unsaved timeline changes" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel("On-screen copy", { exact: true })).toHaveValue(
    "Hello robot",
  );
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByText("All changes saved", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Back to preview", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Approve and export", exact: true })
    .click();
  await page.getByRole("button", { name: "Open agent", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Download video", exact: true }),
  ).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download video", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.mp4$/);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Download video", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.cache/browser-results/unified-preview.png",
    fullPage: true,
  });
});

test("storyboard only, independent videos, style review and mobile drawers", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openProject(page, request);
  await send(page, "Just write the storyboard for a 6 second forest story");
  await expect(
    page.getByRole("button", { name: "Approve and create video", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Preview scene-1")).toHaveCount(0);
  const first = page.url();
  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("button", { name: "New video", exact: true })
    .click();
  await send(page, "Just write the storyboard for a 6 second beach story");
  await expect(
    page.getByRole("button", { name: "Approve and create video", exact: true }),
  ).toBeVisible();
  expect(page.url()).not.toEqual(first);
  await page.goto(first);
  await expect(
    page
      .getByRole("region", { name: "Video agent", exact: true })
      .getByText("Just write the storyboard for a 6 second forest story", {
        exact: true,
      }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("button", { name: "Style", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Style & motion" });
  await dialog.getByRole("button", { name: "3D", exact: true }).click();
  await dialog
    .getByRole("button", { name: "Review changes with the agent", exact: true })
    .click();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Approve and create video", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Here’s the revised storyboard.", { exact: true }),
  ).toBeVisible();
  await createVideo(page);
  await expect(
    page.getByRole("button", { name: "Open agent", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel("Video timeline canvas")).toBeVisible();
  await page
    .getByRole("button", { name: "Back to preview", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await expect(page.getByLabel("Combined video preview")).toBeVisible();
  const exportBounds = await page
    .getByRole("button", { name: "Export", exact: true })
    .boundingBox();
  expect(exportBounds!.x + exportBounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "../.cache/browser-results/unified-mobile.png",
    fullPage: true,
  });
});

test("library and settings drawers preserve existing tools and restore focus", async ({
  page,
  request,
}) => {
  await openProject(page, request);
  const rail = page.getByRole("navigation", { name: "Workspace navigation" });
  await rail.getByRole("button", { name: "Library", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Workspace tools" });
  await expect(
    drawer.getByText("Bring your own assets", { exact: true }),
  ).toBeVisible();
  await drawer
    .getByRole("button", { name: "Create media", exact: true })
    .click();
  await drawer
    .getByLabel("Describe the image or music")
    .fill("A small blue robot on a dark background");
  await drawer
    .getByRole("button", { name: "Create image", exact: true })
    .click();
  await expect(
    drawer.getByText("Image queued. Find it in the library when ready.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    rail.getByRole("button", { name: "Library", exact: true }),
  ).toBeFocused();
  await rail.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    drawer.getByRole("button", { name: "Save brand version", exact: true }),
  ).toBeVisible();
  await drawer
    .getByRole("button", { name: "Save brand version", exact: true })
    .click();
  await expect(
    drawer.getByText("Brand version saved. Future runs will use this bundle.", {
      exact: true,
    }),
  ).toBeVisible();
  await drawer.getByRole("button", { name: "Team", exact: true }).click();
  await expect(drawer.getByLabel("Firebase user ID")).toBeVisible();
  await drawer.getByRole("button", { name: "Production", exact: true }).click();
  await expect(
    drawer.getByRole("heading", { name: "Jobs", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.cache/browser-results/unified-tools.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(
    rail.getByRole("button", { name: "Settings", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open projects", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Create multiple videos", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open projects", exact: true }),
  ).toBeFocused();
});

test("manual assembly keeps duration, layers and project heads isolated", async ({
  page,
  request,
}) => {
  const token = await openProject(page, request);
  await page
    .getByRole("navigation", { name: "Workspace navigation" })
    .getByRole("button", { name: "Library", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Start a blank video", exact: true })
    .click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Video duration (s)").fill("6");
  await page.getByRole("button", { name: "Add text", exact: true }).click();
  await page
    .getByLabel("On-screen copy", { exact: true })
    .fill("A manually assembled video");
  await page.getByLabel("Layer", { exact: true }).fill("3");
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByText("All changes saved", { exact: true }),
  ).toBeVisible();
  const url = new URL(page.url());
  const projectId = url.pathname.split("/").at(-1);
  const studio = await request.get(
    `http://127.0.0.1:8100/v1/projects/${projectId}/studio`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect((await studio.json()).data.project.composition_head).toBeNull();
  const scoped = await request.get(
    `http://127.0.0.1:8100/v1/projects/${projectId}/studio?conversation_id=${url.searchParams.get("chat")}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect((await scoped.json()).data.project.composition_head).toBeTruthy();
});
