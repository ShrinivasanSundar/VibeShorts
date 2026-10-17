import { firebaseAuth } from "./firebase";
import { track } from "./loading";

const api = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request(path: string, options: RequestInit = {}) {
  // Writes always show the loader; reads are polled in the background and stay silent.
  return (options.method || "GET").toUpperCase() === "GET" ? send(path, options) : track(() => send(path, options));
}

async function send(path: string, options: RequestInit) {
  const current = firebaseAuth().currentUser;
  if (!current) throw new Error("Sign in to continue.");
  const response = await fetch(api + path, {
    ...options, cache: "no-store", headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${await current.getIdToken()}`,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.message || body.detail?.[0]?.msg || "The request could not be completed.", response.status);
  }
  return response;
}

export async function call(path: string, options: RequestInit = {}) {
  return (await request(path, options)).json();
}
