-- Exact-word mode: the whole comment must equal one of the keywords.
ALTER TABLE "Automation" ADD COLUMN "exactMatch" BOOLEAN NOT NULL DEFAULT false;
