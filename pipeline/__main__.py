import argparse
import json

from . import run


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("ticker")
    s.add_argument("date", nargs="?")
    s.add_argument("--fresh", action="store_true")
    q = sub.add_parser("accept")
    q.add_argument("ticker")
    q.add_argument("date")
    q.add_argument("artifact")
    for name in ("next", "done", "approve", "block"):
        q = sub.add_parser(name); q.add_argument("ticker"); q.add_argument("date")
        if name in ("done", "approve"): q.add_argument("step")
        if name == "approve":
            q.add_argument("--by", required=True)
            q.add_argument("--drop", default="")
        if name == "block": q.add_argument("reason")
    a = p.parse_args()
    if a.cmd == "start":
        print(run.start(a.ticker, a.date, a.fresh)); return
    d = run.run_dir(a.ticker, a.date)
    if a.cmd == "accept":
        run.accept(d, a.artifact); return
    if a.cmd == "next": print(json.dumps(run.next_step(d)))
    elif a.cmd == "done": run.mark_done(d, a.step)
    elif a.cmd == "approve": run.approve(d, a.step, a.by, [x for x in a.drop.split(",") if x])
    elif a.cmd == "block": run.block(d, a.reason)


main()
