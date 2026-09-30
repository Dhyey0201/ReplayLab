import argparse
import sys
from .codec import canonical, lines
from .engine import Session


def main():
    parser = argparse.ArgumentParser(
        description="Independent ReplayLab reference (memory mode)"
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--input")
    parser.add_argument("--state-out")
    args = parser.parse_args()
    session = Session(args.session_id)
    source = open(args.input, "rb") if args.input else sys.stdin.buffer
    try:
        for raw in lines(source):
            print(canonical(session.handle(raw)).decode(), flush=True)
            session.assert_invariants()
    finally:
        if args.input:
            source.close()
    if args.state_out:
        with open(args.state_out, "wb") as out:
            out.write(canonical(session.session_state()) + b"\n")


if __name__ == "__main__":
    main()
