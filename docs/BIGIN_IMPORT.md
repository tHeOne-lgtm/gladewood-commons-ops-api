# Bigin import and cutover (item 3)

**What is in Bigin (Source fact, account read through the Bigin connector, 2026-11-20).**

| Module | Count | What the records hold | Imported as |
|---|---|---|---|
| Accounts (Companies) | 130 | Referral organizations: housing authorities, agencies, clinics, schools, ministries. Name, phone, some websites, description (most read "Added from the Gladewood Prospect Hub", which is the Command Center push) | `companies` with `legacy_ref = bigin:account:<id>`, kind guessed from the name (hospital, agency, brokerage, employer, other), hub description dropped, any other description kept as notes |
| Contacts | 121 | Partner staff: case managers, homeless liaisons, housing coordinators. Full name, email, title, description ("Direct line: ..."), linked account. One system record (a Google forwarding address) | `contacts` kind `case_manager` linked to the company, title in `extra.title`, description as notes, tag `src-bigin`, `legacy_ref = bigin:contact:<id>`; the forwarding address is skipped and listed in the report |
| Pipelines (deals), Tasks, Events, Calls, Notes | 0 each | Nothing to import | |
| Tags | None on any record | The tag definitions on the Resident Pipeline layout have no records behind them | Source tags are already in use here (`src-web`, `src-whatsapp`, `src-bigin`) |
| Grants and Donors layout | 0 records | WASH work, not Gladewood | Not imported (domain isolation) |
| Email Opt Out flag | per contact | | Written as a withdrawn email consent, so campaigns skip the person |

**Matching.** A row matches an existing record by `legacy_ref`, then email, then phone, then exact name. A match is filled in where the local field is blank and never overwritten. Running the import twice creates nothing the second time.

**Undo.** Every run is an import batch; `POST /api/imports/{id}/undo` (admin) deletes the rows that run created and leaves matched records alone.

## Steps

1. **Export from Bigin.** Assumption on menu placement (Bigin's docs are blocked from the build environment): Bigin, Settings (gear icon), Data Administration, Export. Export Accounts, then Contacts, as CSV. Column headers are the field labels ("Account Name", "First Name", "Email Opt Out"); the importer reads those, the API names, and the JSON the Bigin API returns.
2. **Dry run.** Staff app, Imports page, choose both files, Preview. The report shows how many companies and contacts would be created, matched, or skipped, and why. Fix anything surprising in the files first.
3. **Apply.** Same page, Import. The batch appears in the list with an Undo button.
4. **Check.** Contacts filtered by tag `src-bigin` should number 120 (121 minus the forwarding address). Companies list should show 130 plus any that already existed.
5. **Cutover.** Done 2026-11-20 for the Make scenario (see `docs/COMMAND_CENTER_REPOINT.md`): the push and pull now hit `/api/integrations/bigin-accounts` with the `X-Api-Key` credential. Remaining: freeze Bigin to read-only, keep the export files for 30 days, then cancel the subscription.

Command line alternative, against the Render database:

```
python -m app.cli import-bigin --accounts accounts.csv --contacts contacts.csv            # dry run
python -m app.cli import-bigin --accounts accounts.csv --contacts contacts.csv --apply --actor <user id>
```
