-- Add introductory offer flags for salons

ALTER TABLE salons
    ADD COLUMN IF NOT EXISTS introductory_offer_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS introductory_offer_type TEXT CHECK (introductory_offer_type IN ('first_month_free_direct'));

UPDATE salons
SET introductory_offer_enabled = FALSE
WHERE introductory_offer_enabled IS NULL;

UPDATE salons
SET introductory_offer_type = NULL
WHERE introductory_offer_enabled = FALSE;
