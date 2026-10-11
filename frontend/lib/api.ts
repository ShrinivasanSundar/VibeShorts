import { firebaseAuth } from "./firebase";

const api = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request(path: string, options: RequestInit = {}) {
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
