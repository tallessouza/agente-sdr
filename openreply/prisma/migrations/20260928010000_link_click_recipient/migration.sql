-- Per-recipient tracked links: a click names the Instagram user the DM went to.
-- Nullable and idempotent: old clicks and links without ?t= keep working.

-- AlterTable
ALTER TABLE "LinkClick" ADD COLUMN IF NOT EXISTS "recipientId" TEXT;
ALTER TABLE "LinkClick" ADD COLUMN IF NOT EXISTS "recipientName" TEXT;

-- CreateIndex
CREATE INDEX IF NOT EXISTS "LinkClick_recipientId_idx" ON "LinkClick"("recipientId");
