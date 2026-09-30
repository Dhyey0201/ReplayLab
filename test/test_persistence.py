import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from replaylab_ref.codec import canonical
from test_reference import new

ENGINE = str(Path("_build/default/bin/main.exe").resolve())


def run(*args, code=0):
    result = subprocess.run([ENGINE, *map(str, args)], capture_output=True, timeout=15)
    if result.returncode != code:
        raise AssertionError(
            (args, result.returncode, result.stderr.decode(errors="replace"))
        )
    return result


def encode_frame(payload):
    data = canonical(payload)
    header = b"RPLB" + struct.pack(">HI", 1, len(data))
    return header + data + hashlib.sha256(header + data).digest()


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="replaylab-storage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = self.root / "session"
        self.workload = self.root / "workload.jsonl"
        self.workload.write_bytes(
            Path("fixtures/golden/walkthrough.jsonl").read_bytes()
        )
        run(
            "run",
            "--mode",
            "durable",
            "--session-id",
            "golden",
            "--session-dir",
            self.session,
            "--input",
            self.workload,
            "--responses",
            self.root / "responses.jsonl",
            "--state-out",
            self.root / "state.json",
        )

    def test_durable_replay_snapshot_retries(self):
        state = json.loads((self.root / "state.json").read_bytes())
        run(
            "replay",
            "--session-dir",
            self.session,
            "--state-out",
            self.root / "replay.json",
        )
        self.assertEqual(state, json.loads((self.root / "replay.json").read_bytes()))
        responses = [
            json.loads(x)
            for x in (self.root / "responses.jsonl").read_bytes().splitlines()
        ]
        self.assertEqual(responses[0]["durability"], "synced")
        self.assertEqual(responses[-1]["durability"], "none")
        first = run("snapshot", "--session-dir", self.session).stdout
        self.assertEqual(first, run("snapshot", "--session-dir", self.session).stdout)
        before = (self.session / "commands.wal").read_bytes()
        run(
            "recover",
            "--session-dir",
            self.session,
            "--input",
            self.workload,
            "--responses",
            self.root / "retry.jsonl",
            "--state-out",
            self.root / "retry-state.json",
        )
        self.assertEqual(
            state, json.loads((self.root / "retry-state.json").read_bytes())
        )
        self.assertEqual(before, (self.session / "commands.wal").read_bytes())
        for line in (self.root / "retry.jsonl").read_bytes().splitlines()[:-1]:
            self.assertTrue(json.loads(line)["duplicate"])
        snap = next((self.session / "snapshots").glob("*.bin"))
        snap.write_bytes(b"damaged")
        result = run(
            "replay",
            "--session-dir",
            self.session,
            "--state-out",
            self.root / "fallback.json",
        )
        self.assertIn(b"snapshot rejected", result.stderr)
        self.assertEqual(state, json.loads((self.root / "fallback.json").read_bytes()))

    def test_empty_snapshot_and_suffix(self):
        empty = self.root / "empty"
        empty.write_bytes(b"")
        directory = self.root / "other"
        run(
            "run",
            "--mode",
            "durable",
            "--session-id",
            "golden",
            "--session-dir",
            directory,
            "--input",
            empty,
        )
        run("snapshot", "--session-dir", directory)
        run(
            "recover",
            "--session-dir",
            directory,
            "--input",
            self.workload,
            "--responses",
            self.root / "other.jsonl",
        )
        run(
            "replay",
            "--session-dir",
            directory,
            "--state-out",
            self.root / "other-state.json",
        )
        self.assertEqual(
            (self.root / "state.json").read_bytes(),
            (self.root / "other-state.json").read_bytes(),
        )

    def test_corruption_and_read_only(self):
        run("snapshot", "--session-dir", self.session)
        original = (self.session / "commands.wal").read_bytes()
        length = struct.unpack(">I", original[6:10])[0]
        end = 42 + length
        payload = json.loads(original[10 : 10 + length])
        cases = []
        for offset in [0, 4, 6, 10, end - 1, end + 12]:
            changed = bytearray(original)
            changed[offset] ^= 0x80
            cases.append(bytes(changed))
        for field, value in [
            ("seq", "2"),
            ("session_identity_hash", "0" * 64),
            ("schema_version", 2),
        ]:
            p = dict(payload)
            p[field] = value
            cases.append(encode_frame(p) + original[end:])
        p = json.loads(json.dumps(payload))
        p["command"]["quantity"] = "0"
        cases.append(encode_frame(p) + original[end:])
        p = json.loads(json.dumps(payload))
        p["seq"] = "2"
        cases.append(original[:end] + encode_frame(p))
        for data in cases:
            (self.session / "commands.wal").write_bytes(data)
            run("verify-log", "--session-dir", self.session, code=3)
            run(
                "recover",
                "--session-dir",
                self.session,
                "--repair-incomplete-tail",
                "--input",
                self.workload,
                code=3,
            )
            self.assertEqual((self.session / "commands.wal").read_bytes(), data)
        (self.session / "commands.wal").write_bytes(original)

    def test_all_byte_truncations_of_two_frames(self):
        raw = (self.session / "commands.wal").read_bytes()
        ends = []
        offset = 0
        for _ in range(2):
            offset += 42 + struct.unpack(">I", raw[offset + 6 : offset + 10])[0]
            ends.append(offset)
        raw = raw[: ends[-1]]
        empty = self.root / "empty"
        empty.write_bytes(b"")
        for cut in range(len(raw) + 1):
            data = raw[:cut]
            (self.session / "commands.wal").write_bytes(data)
            complete = cut in [0, *ends]
            result = run(
                "verify-log", "--session-dir", self.session, code=0 if complete else 3
            )
            self.assertEqual(json.loads(result.stdout)["incomplete_tail"], not complete)
            self.assertEqual((self.session / "commands.wal").read_bytes(), data)
            run(
                "recover",
                "--session-dir",
                self.session,
                "--repair-incomplete-tail",
                "--input",
                empty,
            )
            expected = max([0] + [x for x in ends if x <= cut])
            self.assertEqual((self.session / "commands.wal").stat().st_size, expected)

    def test_lock_and_fresh_path_refusal(self):
        run(
            "run",
            "--mode",
            "durable",
            "--session-id",
            "golden",
            "--session-dir",
            self.session,
            "--input",
            self.workload,
            code=3,
        )
        child = subprocess.Popen(
            [ENGINE, "recover", "--session-dir", str(self.session)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            child.stdin.write(canonical(new(99)) + b"\n")
            child.stdin.flush()
            from replaylab_tools.compare import Reader

            reader = Reader(child.stdout, 5)
            self.assertIsNotNone(reader.line())
            reader.close()
            run("inspect", "--session-dir", self.session, code=3)
            run(
                "recover",
                "--session-dir",
                self.session,
                "--input",
                self.workload,
                code=3,
            )
        finally:
            child.kill()
            child.communicate(timeout=5)
