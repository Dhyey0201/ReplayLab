open Codec

exception Error of string

let error message = raise (Error message)

type io = {
  write : Unix.file_descr -> bytes -> int -> int -> int;
  sync : Unix.file_descr -> unit;
}

let real_io = { write = Unix.write; sync = Unix.fsync }

let rec write_all ?(io = real_io) fd data offset length =
  if length > 0 then
    let count =
      try io.write fd data offset length
      with Unix.Unix_error (Unix.EINTR, _, _) -> -1
    in
    if count = -1 then write_all ~io fd data offset length
    else if count <= 0 || count > length then
      error "invalid or zero-length write"
    else write_all ~io fd data (offset + count) (length - count)

let rec sync ?(io = real_io) fd =
  try io.sync fd with Unix.Unix_error (Unix.EINTR, _, _) -> sync ~io fd

let with_fd path flags mode f =
  let fd = Unix.openfile path flags mode in
  Fun.protect ~finally:(fun () -> Unix.close fd) (fun () -> f fd)

let sync_dir path = with_fd path [ Unix.O_RDONLY ] 0 (fun fd -> sync fd)

let write_synced ?(exclusive = true) path data =
  let flags =
    [ Unix.O_WRONLY; Unix.O_CREAT ]
    @ if exclusive then [ Unix.O_EXCL ] else [ Unix.O_TRUNC ]
  in
  with_fd path flags 0o600 (fun fd ->
      let bytes = Bytes.of_string data in
      write_all fd bytes 0 (Bytes.length bytes);
      sync fd)

let read_bounded path limit =
  let stat = Unix.LargeFile.stat path in
  if stat.Unix.LargeFile.st_size > Int64.of_int limit then
    error "file exceeds format limit";
  let input = open_in_bin path in
  Fun.protect
    ~finally:(fun () -> close_in input)
    (fun () ->
      really_input_string input (Int64.to_int stat.Unix.LargeFile.st_size))

let metadata session_id config =
  obj
    [
      ("schema_version", `Int 1);
      ("semantics_version", s Version.semantics);
      ("journal_version", `Int 1);
      ("mode", s "durable");
      ("session_id", s session_id);
      ("configuration", Codec.config config);
      ("configuration_hash", s (hash (Codec.config config)));
    ]

type t = {
  dir : string;
  lock : Unix.file_descr;
  wal : Unix.file_descr;
  metadata : Yojson.Safe.t;
  identity : string;
}

let close t =
  Unix.close t.wal;
  Unix.close t.lock

let lock path =
  let fd = Unix.openfile path [ Unix.O_RDWR; Unix.O_CREAT ] 0o600 in
  try
    Unix.lockf fd Unix.F_TLOCK 0;
    fd
  with exn ->
    Unix.close fd;
    raise exn

let open_existing dir =
  (* Existing read operations never create a missing lock file. *)
  let fd =
    Unix.openfile (Filename.concat dir "writer.lock") [ Unix.O_RDWR ] 0
  in
  try
    Unix.lockf fd Unix.F_TLOCK 0;
    let meta =
      strict_json (read_bounded (Filename.concat dir "metadata.json") 65536)
    in
    let sid = str (get "session_id" meta) in
    if not (Domain.valid_id sid) then error "invalid session ID";
    let config = config_of_json (get "configuration" meta) in
    if canonical meta <> canonical (metadata sid config) then
      error "incompatible or invalid metadata";
    let wal =
      Unix.openfile (Filename.concat dir "commands.wal") [ Unix.O_RDWR ] 0
    in
    { dir; lock = fd; wal; metadata = meta; identity = hash meta }
  with exn ->
    Unix.close fd;
    raise exn

let create dir session_id config =
  ignore (Session.create ~config session_id);
  let parent = Filename.dirname dir in
  if not (Sys.file_exists parent) then
    error "session parent directory must exist";
  if Sys.file_exists dir then (
    if Array.length (Sys.readdir dir) <> 0 then
      error "new durable session refuses nonempty directory")
  else (
    Unix.mkdir dir 0o700;
    sync_dir parent);
  let fd = lock (Filename.concat dir "writer.lock") in
  try
    (* Recheck under the lock, preventing two empty-directory creators. *)
    if Array.exists (fun name -> name <> "writer.lock") (Sys.readdir dir) then
      error "session already initialized";
    let meta = metadata session_id config in
    write_synced (Filename.concat dir "metadata.json") (canonical meta);
    write_synced (Filename.concat dir "commands.wal") "";
    Unix.mkdir (Filename.concat dir "snapshots") 0o700;
    sync_dir dir;
    let wal =
      Unix.openfile (Filename.concat dir "commands.wal") [ Unix.O_RDWR ] 0
    in
    { dir; lock = fd; wal; metadata = meta; identity = hash meta }
  with exn ->
    Unix.close fd;
    raise exn

let frame_payload t seq c =
  obj
    [
      ("schema_version", `Int 1);
      ("semantics_version", s Version.semantics);
      ("session_identity_hash", s t.identity);
      ("seq", n seq);
      ("client_id", s c.Domain.client_id);
      ("request_id", s c.request_id);
      ("command", command_json c);
    ]

let frame payload =
  let data = canonical payload in
  if String.length data > 65536 then error "frame payload too large";
  let header = Bytes.create 10 in
  Bytes.blit_string "RPLB" 0 header 0 4;
  Bytes.set_uint16_be header 4 1;
  Bytes.set_int32_be header 6 (Int32.of_int (String.length data));
  let content = Bytes.to_string header ^ data in
  Bytes.of_string (content ^ sha_raw content)

let append ?(hook = fun _ _ -> ()) t seq c =
  hook "before_append" seq;
  let data = frame (frame_payload t seq c) in
  ignore (Unix.LargeFile.lseek t.wal 0L Unix.SEEK_END);
  let prefix = Bytes.length data / 2 in
  write_all t.wal data 0 prefix;
  hook "after_partial_append" seq;
  write_all t.wal data prefix (Bytes.length data - prefix);
  hook "after_append_before_sync" seq;
  sync t.wal;
  hook "after_sync_before_apply" seq

type record = {
  seq : int64;
  command : Domain.command;
  end_offset : int64;
  checksum : string;
}

type scan = {
  records : record list;
  valid_bytes : int64;
  incomplete_tail : bool;
}

let scan t =
  ignore (Unix.LargeFile.lseek t.wal 0L Unix.SEEK_SET);
  let read count =
    let data = Bytes.create count in
    let rec loop offset =
      if offset = count then offset
      else
        let n =
          try Unix.read t.wal data offset (count - offset)
          with Unix.Unix_error (Unix.EINTR, _, _) -> -1
        in
        if n = -1 then loop offset
        else if n = 0 then offset
        else loop (offset + n)
    in
    let size = loop 0 in
    Bytes.sub_string data 0 size
  in
  let seen = Hashtbl.create 128 in
  let config = config_of_json (get "configuration" t.metadata) in
  let rec loop seq offset acc =
    let header = read 10 in
    if header = "" then
      { records = List.rev acc; valid_bytes = offset; incomplete_tail = false }
    else
      let size = String.length header in
      (* A partial header is repairable only if known fixed bytes are valid. *)
      for i = 0 to min 3 (size - 1) do
        if header.[i] <> "RPLB".[i] then error "bad frame magic"
      done;
      if size >= 5 && header.[4] <> '\000' then
        error "unsupported frame version";
      if size >= 6 && Char.code header.[5] <> 1 then
        error "unsupported frame version";
      if size < 10 then
        { records = List.rev acc; valid_bytes = offset; incomplete_tail = true }
      else
        let length =
          Int64.logand
            (Int64.of_int32 (String.get_int32_be header 6))
            0xffffffffL
        in
        if length > 65536L then error "frame length exceeds bound";
        let data = read (Int64.to_int length + 32) in
        if String.length data < Int64.to_int length + 32 then
          {
            records = List.rev acc;
            valid_bytes = offset;
            incomplete_tail = true;
          }
        else
          let payload = String.sub data 0 (Int64.to_int length) in
          let checksum = String.sub data (Int64.to_int length) 32 in
          if checksum <> sha_raw (header ^ payload) then
            error "frame checksum mismatch";
          let j =
            try strict_json payload with _ -> error "invalid frame JSON"
          in
          let command =
            try parse (canonical (get "command" j))
            with _ -> error "invalid normalized command"
          in
          if seq = None then error "sequence exhausted in journal";
          let sequence = Option.get seq in
          if
            canonical j <> canonical (frame_payload t sequence command)
            || payload <> canonical j
          then error "invalid sequence, identity, or payload schema";
          let key = (command.client_id, command.request_id) in
          if Hashtbl.mem seen key then error "duplicate journal request key";
          if Int64.of_int (Hashtbl.length seen) >= config.max_unique_requests
          then error "journal exceeds request capacity";
          Hashtbl.add seen key ();
          let finish = Int64.add offset (Int64.add 42L length) in
          loop
            (Domain.successor sequence)
            finish
            ({ seq = sequence; command; end_offset = finish; checksum } :: acc)
  in
  loop (Some 1L) 0L []

let repair t scanned =
  if scanned.incomplete_tail then (
    Unix.LargeFile.ftruncate t.wal scanned.valid_bytes;
    sync t.wal)

let fresh t =
  Session.create
    ~config:(config_of_json (get "configuration" t.metadata))
    (str (get "session_id" t.metadata))

let replay t scanned =
  let session = fresh t in
  List.iter
    (fun record -> ignore (Session.apply session record.seq record.command))
    scanned.records;
  Session.validate session;
  session

(* Invalid untrusted storage data always has the storage exit class. *)
let open_existing_unchecked = open_existing

let open_existing dir =
  try open_existing_unchecked dir
  with Protocol _ | Invalid_argument _ | Failure _ ->
    error "invalid session metadata"

let scan_unchecked = scan

let scan t =
  try scan_unchecked t
  with Protocol _ | Invalid_argument _ | Failure _ ->
    error "invalid journal payload"
