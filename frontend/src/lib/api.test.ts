import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, ServiceUnavailableError } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch resilience (Req 21.4)", () => {
  it("throws ServiceUnavailableError on a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(apiFetch("/anything")).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
  });

  it("throws ServiceUnavailableError on a 5xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("", { status: 503, headers: { "content-type": "text/plain" } }),
      ),
    );
    await expect(apiFetch("/anything")).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
  });

  it("maps the backend error envelope to an ApiError with code and field", async () => {
    const body = JSON.stringify({
      error: { code: "email_already_registered", message: "Already registered", field: "email" },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 409,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    await expect(apiFetch("/auth/register", { method: "POST" })).rejects.toMatchObject(
      { name: "ApiError", code: "email_already_registered", field: "email" },
    );
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    await expect(apiFetch<{ ok: boolean }>("/health")).resolves.toEqual({ ok: true });
  });
});
