import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db/client";
import { getRequestIp, hashClickIp } from "@/lib/tracking/server";
import { personalizeDestination, verifyRecipient } from "@/lib/tracking/recipient";

type RedirectRouteProps = {
  params: Promise<{ slug: string }>;
};

export async function GET(request: NextRequest, { params }: RedirectRouteProps) {
  const { slug } = await params;
  const trackedLink = await prisma.trackedLink.findUnique({
    where: { slug },
    select: {
      id: true,
      workspaceId: true,
      automationId: true,
      destinationUrl: true,
      automation: {
        select: {
          instagramAccountId: true,
        },
      },
    },
  });

  if (!trackedLink) {
    // Behind a proxy request.url is the internal origin (localhost:3000); send
    // unknown links to the public home instead.
    return NextResponse.redirect(new URL("/", process.env.NEXTAUTH_URL ?? request.url), { status: 302 });
  }

  // A signed ?t= names the Instagram user the DM went to: the click is theirs,
  // and their @ can fill {username} in the destination (e.g. a wa.me text).
  const recipientId = verifyRecipient(slug, new URL(request.url).searchParams.get("t"));
  const recipientName = recipientId
    ? (
        await prisma.dmLog.findFirst({
          where: { automationId: trackedLink.automationId, commenterId: recipientId, commenterName: { not: null } },
          orderBy: { createdAt: "desc" },
          select: { commenterName: true },
        })
      )?.commenterName ?? null
    : null;

  await prisma.linkClick.create({
    data: {
      recipientId,
      recipientName,
      workspaceId: trackedLink.workspaceId,
      automationId: trackedLink.automationId,
      instagramAccountId: trackedLink.automation.instagramAccountId,
      trackedLinkId: trackedLink.id,
      ipHash: hashClickIp(getRequestIp(request)),
      userAgent: request.headers.get("user-agent"),
      referrer: request.headers.get("referer"),
    },
  });

  return NextResponse.redirect(personalizeDestination(trackedLink.destinationUrl, recipientName), { status: 302 });
}
