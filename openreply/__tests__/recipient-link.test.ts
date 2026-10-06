import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockPrisma } = vi.hoisted(() => ({
  mockPrisma: {
    trackedLink: { findUnique: vi.fn() },
    linkClick: { create: vi.fn() },
    dmLog: { findFirst: vi.fn() },
  },
}));

vi.mock("@/lib/db/client", () => ({ prisma: mockPrisma }));

import { GET } from "../app/r/[slug]/route";
import { buildTrackedUrl } from "../lib/tracking/message";
import { personalizeDestination, signRecipient, verifyRecipient } from "../lib/tracking/recipient";

beforeEach(() => {
  vi.clearAllMocks();
  process.env.NEXTAUTH_SECRET = "test-secret-at-least-16";
});

describe("per-recipient tracked links", () => {
  it("signs and verifies the recipient, rejecting forged or foreign tokens", () => {
    const token = signRecipient("abc123", "1388507469800185");
    expect(verifyRecipient("abc123", token)).toBe("1388507469800185");
    expect(verifyRecipient("other", token)).toBeNull();
    const forged = `${Buffer.from("999999999").toString("base64url")}.${token.split(".")[1]}`;
    expect(verifyRecipient("abc123", forged)).toBeNull();
    expect(verifyRecipient("abc123", "garbage")).toBeNull();
    expect(verifyRecipient("abc123", null)).toBeNull();
  });

  it("adds the token to tracked urls only when the recipient is known", () => {
    expect(buildTrackedUrl("abc123", "https://or.example")).toBe("https://or.example/r/abc123");
    expect(buildTrackedUrl("abc123", "https://or.example", "1388507469800185")).toMatch(/^https:\/\/or\.example\/r\/abc123\?t=[\w-]+\.[\w-]{16}$/);
  });

  it("fills {username} in the destination, encoded, or drops it when unknown", () => {
    const dest = "https://wa.me/554825000259?text=Sou%20o%20%40%7Busername%7D%20e%20quero";
    expect(personalizeDestination(dest, "marina.escala")).toBe("https://wa.me/554825000259?text=Sou%20o%20%40marina.escala%20e%20quero");
    expect(personalizeDestination("https://x.test/?u=@{username}", "a_b")).toBe("https://x.test/?u=%40a_b");
    expect(personalizeDestination(dest, null)).toBe("https://wa.me/554825000259?text=Sou%20o%20%20e%20quero");
  });

  it("records who clicked and personalizes the redirect", async () => {
    mockPrisma.trackedLink.findUnique.mockResolvedValue({
      id: "link_1",
      workspaceId: "ws_1",
      automationId: "auto_1",
      destinationUrl: "https://wa.me/554825000259?text=Sou%20o%20%40%7Busername%7D",
      automation: { instagramAccountId: "ig_1" },
    });
    mockPrisma.dmLog.findFirst.mockResolvedValue({ commenterName: "marina.escala" });
    mockPrisma.linkClick.create.mockResolvedValue({});
    const token = signRecipient("abc123", "1388507469800185");

    const response = await GET(
      new Request(`https://or.example/r/abc123?t=${token}`) as Parameters<typeof GET>[0],
      { params: Promise.resolve({ slug: "abc123" }) }
    );

    expect(response.headers.get("location")).toBe("https://wa.me/554825000259?text=Sou%20o%20%40marina.escala");
    expect(mockPrisma.linkClick.create).toHaveBeenCalledWith({
      data: expect.objectContaining({ recipientId: "1388507469800185", recipientName: "marina.escala", trackedLinkId: "link_1" }),
    });
  });

  it("sends unknown links to the public home, not the internal origin", async () => {
    process.env.NEXTAUTH_URL = "https://openreply.example";
    mockPrisma.trackedLink.findUnique.mockResolvedValue(null);
    const response = await GET(new Request("http://localhost:3000/r/gone") as Parameters<typeof GET>[0], { params: Promise.resolve({ slug: "gone" }) });
    expect(response.headers.get("location")).toBe("https://openreply.example/");
    delete process.env.NEXTAUTH_URL;
  });

  it("keeps anonymous clicks working without a token", async () => {
    mockPrisma.trackedLink.findUnique.mockResolvedValue({
      id: "link_1", workspaceId: "ws_1", automationId: "auto_1",
      destinationUrl: "https://example.com/offer", automation: { instagramAccountId: "ig_1" },
    });
    mockPrisma.linkClick.create.mockResolvedValue({});
    const response = await GET(new Request("https://or.example/r/abc123") as Parameters<typeof GET>[0], { params: Promise.resolve({ slug: "abc123" }) });
    expect(response.headers.get("location")).toBe("https://example.com/offer");
    expect(mockPrisma.dmLog.findFirst).not.toHaveBeenCalled();
    expect(mockPrisma.linkClick.create).toHaveBeenCalledWith({ data: expect.objectContaining({ recipientId: null, recipientName: null }) });
  });
});
