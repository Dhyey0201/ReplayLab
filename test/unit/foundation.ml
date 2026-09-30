let () =
  let value =
    `Assoc [ ("schema_version", `Int 1); ("quantity", `String "10") ]
  in
  assert (Yojson.Safe.from_string (Yojson.Safe.to_string value) = value);
  assert (
    Digestif.SHA256.(to_hex (digest_string "abc"))
    = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  let path = Filename.temp_file "replaylab" ".sync" in
  Fun.protect
    ~finally:(fun () -> Sys.remove path)
    (fun () ->
      let fd = Unix.openfile path [ Unix.O_WRONLY ] 0o600 in
      Fun.protect
        ~finally:(fun () -> Unix.close fd)
        (fun () ->
          assert (Unix.write_substring fd "sync" 0 4 = 4);
          Unix.fsync fd))

(* The adapter exercises the production write-all/sync loops with volatile storage. *)
let () =
  let open Replaylab in
  let volatile = Buffer.create 32
  and durable = ref ""
  and interrupted = ref true in
  let io : Storage.io =
    {
      write =
        (fun _ bytes offset length ->
          if !interrupted then (
            interrupted := false;
            raise (Unix.Unix_error (Unix.EINTR, "write", "")));
          let count = min 3 length in
          Buffer.add_subbytes volatile bytes offset count;
          count);
      sync = (fun _ -> durable := Buffer.contents volatile);
    }
  in
  let data = Bytes.of_string "first-synced" in
  Storage.write_all ~io Unix.stdout data 0 (Bytes.length data);
  Storage.sync ~io Unix.stdout;
  Storage.write_all ~io Unix.stdout (Bytes.of_string "-unsynced") 0 9;
  assert (!durable = "first-synced");
  Buffer.clear volatile;
  Buffer.add_string volatile !durable;
  assert (Buffer.contents volatile = "first-synced");
  let failing =
    {
      io with
      sync = (fun _ -> raise (Unix.Unix_error (Unix.EIO, "fsync", "")));
    }
  in
  assert (
    try
      Storage.sync ~io:failing Unix.stdout;
      false
    with Unix.Unix_error (Unix.EIO, _, _) -> true);
  let full =
    {
      io with
      write =
        (fun _ _ _ _ -> raise (Unix.Unix_error (Unix.ENOSPC, "write", "")));
    }
  in
  assert (
    try
      Storage.write_all ~io:full Unix.stdout data 0 1;
      false
    with Unix.Unix_error (Unix.ENOSPC, _, _) -> true);
  let zero = { io with write = (fun _ _ _ _ -> 0) } in
  assert (
    try
      Storage.write_all ~io:zero Unix.stdout data 0 1;
      false
    with Storage.Error _ -> true)

let () =
  let open Replaylab.Codec in
  let value =
    obj
      [
        ("z", arr []);
        ("a", s "\n\t\000\"\\");
        ("b", `Null);
        ("schema_version", `Int 1);
      ]
  in
  let expected =
    "{\"a\":\"\\u000a\\u0009\\u0000\\\"\\\\\",\"b\":null,\"schema_version\":1,\"z\":[]}"
  in
  assert (canonical value = expected);
  assert (
    sha expected
    = "a4f2faa587b161bfc240901dd47eac583d3d11e629c20e1da9adfd3eb7baf7d7");
  assert (sha expected = sha (canonical value))

let () =
  let open Replaylab in
  let session = Session.create "limits" in
  session.next_seq <- Some Int64.max_int;
  let command : Domain.command =
    {
      client_id = "a";
      request_id = "r";
      instrument = "SIM";
      order_id = "o";
      action =
        Domain.New { side = Domain.Buy; price = 1L; quantity = 1000000000L };
    }
  in
  let first = Session.submit session command in
  assert (Codec.get "seq" first = Codec.n Int64.max_int);
  assert (session.next_seq = None);
  let retry = Session.submit session command in
  assert (Codec.get "duplicate" retry = `Bool true);
  let exhausted =
    Session.submit session
      { command with request_id = "next"; order_id = "other" }
  in
  assert (
    Codec.get "code" (Codec.get "result" exhausted)
    = Codec.s "SEQUENCE_EXHAUSTED");
  assert (
    try
      ignore (Domain.add Int64.max_int 1L);
      false
    with Failure _ -> true)
