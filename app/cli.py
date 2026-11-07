"""Operational commands. Run with: python -m app.cli <command> [options]"""
import argparse
import json
import sys

from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import make_engine, normalize_database_url
from app.legacy_migration import run_legacy_migration
from app.seed import seed_default_pipelines


def _session():
    settings = get_settings()
    if not settings.database_url:
        sys.exit("DATABASE_URL is not set")
    engine = make_engine(normalize_database_url(settings.database_url), settings)
    return sessionmaker(bind=engine)()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate-legacy", help="Move prospects, residents, properties into the CRM")
    m.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    m.add_argument("--allow-partial", action="store_true", help="Apply even if some rows are rejected")
    m.add_argument("--actor", default=None, help="User id to record as deal owner and history actor")
    sub.add_parser("seed-pipelines", help="Create the default pipelines if missing")
    args = ap.parse_args(argv)

    db = _session()
    if args.cmd == "seed-pipelines":
        n = seed_default_pipelines(db)
        db.commit()
        print(f"pipelines created: {n}")
        return 0
    report = run_legacy_migration(db, apply=args.apply, allow_partial=args.allow_partial, actor_id=args.actor)
    print(json.dumps(report.model_dump(), indent=2, default=str))
    if report.rejections and not args.allow_partial:
        print(f"\n{len(report.rejections)} row(s) rejected; nothing written. Fix them or pass --allow-partial.",
              file=sys.stderr)
        return 1
    print("\nDRY RUN: nothing written. Re-run with --apply." if report.dry_run else "\nApplied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
