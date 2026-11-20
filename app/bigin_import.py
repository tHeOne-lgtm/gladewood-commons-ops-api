"""One-time import from Bigin (item 3). Reads Bigin's own export (CSV with label headers) or the
API's JSON record arrays, for the Accounts (companies) and Contacts modules. Deals, tasks, and
the Grants and Donors layout are not imported: the account holds none (Source fact, account
read 2026-11-20), and Grants belongs to the WASH work, not Gladewood.

Rules:
- Match existing rows by legacy_ref `bigin:<module>:<id>`, then email, then phone, then exact
  name. A match is updated only where the local field is blank; nothing is overwritten.
- Every created row carries the ImportBatch id, so the run can be undone as a unit.
- Email_Opt_Out becomes a withdrawn email consent, so the campaign gate honours it.
- Description text goes to `notes` as written. Bigin Title goes to `extra.title`.
"""
import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.crm_common import set_tags, tags_for
from app.imports import norm_email, norm_phone, start_batch
from app.models import Company, Consent, Contact, ImportBatch, User, utcnow
from app.twilio import normalize_phone

HUB_NOTE = "Added from the Gladewood Prospect Hub"
KIND_HINTS: list[tuple[str, str]] = [
    (r"hospital|medical|clinic|health|behavioral|recovery|wellness|va\b|veteran", "hospital"),
    (r"housing authority|housing|homeless|shelter|mission|ministr|coalition|services|agency|county|city of|department|center|centre|program|outreach|school|college|university|church|charit|foundation|council|network|partnership|alliance|association", "agency"),
    (r"realty|real estate|properties|property management|rentals|brokerage|realtor", "brokerage"),
    (r"staffing|employ|workforce|labor|industries|manufactur|logistics", "employer"),
]
SKIP_EMAIL = re.compile(r"(noreply|no-reply|forwarding-noreply|donotreply|mailer-daemon)", re.I)


def _key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (k or "").lower())


def _get(row: dict, *names: str) -> str:
    """Field by API name or export label, ignoring case, spaces and underscores."""
    want = {_key(n) for n in names}
    for k, v in row.items():
        if _key(k) in want:
            if isinstance(v, dict):
                v = v.get("name") or v.get("id") or ""
            if isinstance(v, list):
                v = "|".join(str(x.get("name") if isinstance(x, dict) else x) for x in v)
            return str(v if v is not None else "").strip()
    return ""


def parse_rows(raw: bytes) -> list[dict]:
    """CSV (Bigin export) or JSON (`[...]` or `{"data": [...]}` from the API)."""
    text = raw.decode("utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict):
            data = data.get("data") or []
        return [r for r in data if isinstance(r, dict)]
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def guess_company_kind(name: str) -> str:
    low = name.lower()
    for pattern, kind in KIND_HINTS:
        if re.search(pattern, low):
            return kind
    return "other"


@dataclass
class Skip:
    module: str
    row: int
    reason: str
    label: str = ""


@dataclass
class Report:
    batch_id: int | None
    dry_run: bool
    companies: Counter = field(default_factory=Counter)
    contacts: Counter = field(default_factory=Counter)
    skipped: list[Skip] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"batch_id": self.batch_id, "dry_run": self.dry_run, "companies": dict(self.companies),
                "contacts": dict(self.contacts),
                "skipped": [{"module": s.module, "row": s.row, "reason": s.reason, "label": s.label} for s in self.skipped]}


def _fill(row, **values) -> int:
    """Set blank fields only. Returns how many fields changed."""
    n = 0
    for k, v in values.items():
        if v and not getattr(row, k):
            setattr(row, k, v)
            n += 1
    return n


def import_accounts(db: Session, rows: list[dict], batch: ImportBatch | None, report: Report) -> dict[str, int]:
    """Returns a map of Bigin account id and lower-cased name to local company id."""
    by_ref: dict[str, int] = {}
    for i, r in enumerate(rows, start=1):
        bid = _get(r, "id", "Account_Id", "Account Id", "Record Id")
        name = _get(r, "Account_Name", "Account Name", "Company Name")
        if not name:
            report.skipped.append(Skip("accounts", i, "no_name"))
            continue
        ref = f"bigin:account:{bid}" if bid else None
        row = db.scalar(select(Company).where(Company.legacy_ref == ref)) if ref else None
        if row is None:
            row = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
        desc = _get(r, "Description")
        address = ", ".join(x for x in (_get(r, "Billing_Street", "Billing Street"), _get(r, "Billing_City", "Billing City"),
                                       _get(r, "Billing_State", "Billing State"), _get(r, "Billing_Code", "Billing Code")) if x)
        values = dict(phone=_get(r, "Phone"), website=_get(r, "Website"), address=address,
                      notes="" if desc == HUB_NOTE else desc)
        tags = [t for t in _get(r, "Tag").split("|") if t.strip()]
        if row is None:
            report.companies["created"] += 1
            if batch is not None:
                row = Company(name=name, kind=guess_company_kind(name), legacy_ref=ref, import_batch_id=batch.id,
                              extra={"bigin_id": bid, "source": "bigin", "hub": desc == HUB_NOTE}, **values)
                db.add(row)
                db.flush()
        else:
            changed = _fill(row, **values)
            if ref and not row.legacy_ref:
                row.legacy_ref = ref
                changed += 1
            report.companies["matched"] += 1
            if changed:
                report.companies["updated"] += 1
        if row is not None:
            if tags:
                set_tags(db, "company", row.id, sorted(set(tags_for(db, "company", [row.id])[row.id]) | set(tags)))
            if bid:
                by_ref[bid] = row.id
            by_ref[name.lower()] = row.id
    return by_ref


def import_contacts(db: Session, rows: list[dict], batch: ImportBatch | None, report: Report, companies: dict[str, int]) -> None:
    for i, r in enumerate(rows, start=1):
        bid = _get(r, "id", "Contact_Id", "Contact Id", "Record Id")
        first, last = _get(r, "First_Name", "First Name"), _get(r, "Last_Name", "Last Name")
        full = _get(r, "Full_Name", "Full Name") or f"{first} {last}".strip()
        email = norm_email(_get(r, "Email"))
        if not full:
            report.skipped.append(Skip("contacts", i, "no_name", email))
            continue
        if SKIP_EMAIL.search(email) or SKIP_EMAIL.search(full):
            report.skipped.append(Skip("contacts", i, "system_address", full))
            continue
        phone = normalize_phone(_get(r, "Phone") or _get(r, "Mobile") or _get(r, "Home_Phone", "Home Phone"))
        ref = f"bigin:contact:{bid}" if bid else None
        acct_raw = r.get("Account_Name") if "Account_Name" in r else None
        acct_id = acct_raw.get("id") if isinstance(acct_raw, dict) else _get(r, "Account_Id", "Account Id")
        acct_name = _get(r, "Account_Name", "Account Name", "Company Name")
        company_id = companies.get(str(acct_id or "")) or companies.get(acct_name.lower()) if (acct_id or acct_name) else None
        if company_id is None and acct_name:
            co = db.scalar(select(Company).where(func.lower(Company.name) == acct_name.lower()))
            company_id = co.id if co else None
        row = db.scalar(select(Contact).where(Contact.legacy_ref == ref)) if ref else None
        if row is None and email:
            row = db.scalar(select(Contact).where(func.lower(Contact.email) == email))
        if row is None and phone:
            tail = norm_phone(phone)
            row = next((c for c in db.scalars(select(Contact).where(Contact.phone.like(f"%{tail[-4:]}"))).all()
                        if norm_phone(c.phone) == tail), None)
        if row is None:
            row = db.scalar(select(Contact).where(func.lower(Contact.display_name) == full.lower()))
        title = _get(r, "Title")
        desc = _get(r, "Description")
        kind = "case_manager" if (company_id or title) else "other"
        tags = [t for t in _get(r, "Tag").split("|") if t.strip()] + ["src-bigin"]
        if row is None:
            report.contacts["created"] += 1
            if batch is not None:
                row = Contact(display_name=full, first_name=first, last_name=last, email=email, phone=phone, kind=kind,
                              source="bigin", company_id=company_id, notes=desc, legacy_ref=ref, import_batch_id=batch.id,
                              extra={"bigin_id": bid, "title": title[:120]} if title else {"bigin_id": bid})
                db.add(row)
                db.flush()
        else:
            changed = _fill(row, email=email, phone=phone, first_name=first, last_name=last, notes=desc)
            if company_id and not row.company_id:
                row.company_id = company_id
                changed += 1
            if ref and not row.legacy_ref:
                row.legacy_ref = ref
                changed += 1
            if title and not (row.extra or {}).get("title"):
                row.extra = {**(row.extra or {}), "title": title[:120]}
                changed += 1
            report.contacts["matched"] += 1
            if changed:
                report.contacts["updated"] += 1
        opt_out = _get(r, "Email_Opt_Out", "Email Opt Out").lower() in ("true", "1", "yes")
        if row is None:  # dry run of a new contact: count what would happen
            report.contacts["opted_out"] += opt_out
            continue
        set_tags(db, "contact", row.id, sorted(set(tags_for(db, "contact", [row.id])[row.id]) | set(tags)))
        if opt_out and db.scalar(select(Consent).where(Consent.contact_id == row.id, Consent.consent_type == "email")) is None:
            db.add(Consent(contact_id=row.id, consent_type="email", source="import", given_at=utcnow(),
                           withdrawn_at=utcnow(), withdrawn_by="bigin:Email_Opt_Out"))
            report.contacts["opted_out"] += 1


def run_import(db: Session, *, accounts: list[dict], contacts: list[dict], actor: User | None,
               dry_run: bool, filename: str = "bigin") -> Report:
    batch = None if dry_run else start_batch(db, source="bigin", entity="bigin", filename=filename, actor=actor)
    report = Report(batch_id=batch.id if batch else None, dry_run=dry_run)
    companies = import_accounts(db, accounts, batch, report)
    import_contacts(db, contacts, batch, report, companies)
    if dry_run:
        db.rollback()
        return report
    batch.row_count = len(accounts) + len(contacts)
    batch.created_count = report.companies["created"] + report.contacts["created"]
    batch.error_count = len(report.skipped)
    write_audit(db, actor=actor, action="import.bigin", entity="import_batch", entity_id=batch.id, details=report.as_dict())
    db.commit()
    return report
