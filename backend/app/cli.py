"""python -m app.cli seed [--market MM|KH|all] [--as-of YYYY-MM-DD]"""
import argparse
import json
import time
from datetime import date
from zoneinfo import ZoneInfo
from datetime import datetime

from app.db import session_scope
from app.seed.loader import seed_tenant


def main():
    parser = argparse.ArgumentParser(prog="tenpai")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="Reset and seed the demo tenants")
    s.add_argument("--market", default="all", choices=["MM", "KH", "all"])
    s.add_argument("--as-of", default=None, help="Export date (default: today in Asia/Yangon)")
    args = parser.parse_args()

    if args.cmd == "seed":
        as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(ZoneInfo("Asia/Yangon")).date()
        for market in (["MM", "KH"] if args.market == "all" else [args.market]):
            t0 = time.time()
            with session_scope() as session:
                out = seed_tenant(session, market, as_of)
            loans = out["import"]["batches"]["loans"]
            print(f"[{market}] tenant={out['tenant']} as_of={out['as_of']} in {time.time() - t0:.1f}s")
            print(f"  loans file: {loans['rows']} rows, {loans['accepted']} accepted, "
                  f"{loans['rejected']} rejected, issues={json.dumps(loans['counts'])}")
            for kind in ("schedule", "savings"):
                b = out["import"]["batches"].get(kind)
                if b:
                    print(f"  {kind} file: {b['rows']} rows, {b['accepted']} loaded")
            print(f"  cases: {json.dumps(out['import']['cases'])}")


if __name__ == "__main__":
    main()
