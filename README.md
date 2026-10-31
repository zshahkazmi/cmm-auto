# cmm-auto

Scheduled outreach runner. On weekday mornings (UK business hours) it
pulls newly scraped motor-trade businesses from a Google Sheet
directory, submits their website contact forms, and records every
outcome back in the sheet's outreach ledger so no business is ever
contacted twice.

No data lives in this repository — leads are pulled live at run time
and results are written back to the sheet, never committed here.
