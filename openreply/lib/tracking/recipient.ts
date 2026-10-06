import { createHmac, timingSafeEqual } from "crypto";

/**
 * Per-recipient tracked links.
 *
 * A DM button carries `/r/<slug>?t=<token>`, where the token names the
 * Instagram user (IGSID) the DM was sent to, signed with NEXTAUTH_SECRET so a
 * click can be attributed to that person without a database row per send and
 * without anything visible in the WhatsApp text the lead may edit.
 */

function secret(): string {
  return process.env.NEXTAUTH_SECRET ?? "";
}

function signature(slug: string, recipientId: string): string {
  return createHmac("sha256", secret())
    .update(`${slug}:${recipientId}`)
    .digest("base64url")
    .slice(0, 16);
}

export function signRecipient(slug: string, recipientId: string): string {
  return `${Buffer.from(recipientId).toString("base64url")}.${signature(slug, recipientId)}`;
}

/** The IGSID in a token, or null when the token is missing, malformed or forged. */
export function verifyRecipient(slug: string, token: string | null | undefined): string | null {
  if (!token || !secret()) return null;
  const [encoded, sig] = token.split(".");
  if (!encoded || !sig) return null;
  let recipientId: string;
  try {
    recipientId = Buffer.from(encoded, "base64url").toString("utf8");
  } catch {
    return null;
  }
  if (!/^[0-9]{5,32}$/.test(recipientId)) return null;
  const expected = Buffer.from(signature(slug, recipientId));
  const received = Buffer.from(sig);
  if (expected.length !== received.length || !timingSafeEqual(expected, received)) return null;
  return recipientId;
}

const USERNAME_PLACEHOLDER = /(%40|@)?(\{username\}|%7Busername%7D)/gi;

/**
 * Fill `{username}` in a destination URL at click time (URL-encoded), so a
 * WhatsApp prefilled text can carry the @ even behind a tracked button.
 * Unknown recipient: the placeholder (and a leading @) is dropped.
 */
export function personalizeDestination(url: string, username: string | null | undefined): string {
  const handle = (username ?? "").replace(/^@/, "").trim();
  return url.replace(USERNAME_PLACEHOLDER, (_match, at: string | undefined) =>
    handle ? `${at ? "%40" : ""}${encodeURIComponent(handle)}` : ""
  );
}
