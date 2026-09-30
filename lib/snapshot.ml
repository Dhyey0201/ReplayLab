open Codec

let boundary records seq =
  if seq = 0L then (0L, "empty")
  else
    match List.find_opt (fun (r : Storage.record) -> r.seq = seq) records with
    | Some r -> (r.end_offset, hex r.checksum)
    | None -> Storage.error "snapshot ahead of journal"

let body t scanned session =
  let offset, checksum =
    boundary scanned.Storage.records session.Session.last_seq
  in
  let state = Session.export session in
  obj
    [
      ("schema_version", `Int 1);
      ("semantics_version", s Version.semantics);
      ("session_id", s session.session_id);
      ("configuration_hash", get "configuration_hash" t.Storage.metadata);
      ("last_applied_seq", n session.last_seq);
      ("journal_offset", n offset);
      ("boundary_checksum", s checksum);
      ("state", state);
      ("state_digest", s (hash state));
    ]

let publish ?(hook = fun _ _ -> ()) t scanned session =
  Session.validate session;
  let content = body t scanned session in
  let bytes =
    canonical (obj [ ("body", content); ("checksum", s (hash content)) ])
  in
  let dir = Filename.concat t.Storage.dir "snapshots" in
  let final =
    Filename.concat dir
      (Printf.sprintf "snapshot-%020Ld.bin" session.Session.last_seq)
  in
  (if Sys.file_exists final then (
     if Storage.read_bounded final (512 * 1024 * 1024) <> bytes then
       Storage.error "different snapshot exists at same sequence")
   else
     let temp, channel =
       Filename.open_temp_file ~temp_dir:dir "pending-" ".tmp"
     in
     close_out channel;
     Fun.protect
       ~finally:(fun () -> if Sys.file_exists temp then Sys.remove temp)
       (fun () ->
         Storage.write_synced ~exclusive:false temp bytes;
         hook "snapshot_after_file_sync" session.last_seq;
         Unix.rename temp final;
         hook "snapshot_after_rename" session.last_seq;
         Storage.sync_dir dir));
  final

let recover t scanned =
  let dir = Filename.concat t.Storage.dir "snapshots" in
  let files =
    Sys.readdir dir |> Array.to_list
    |> List.filter (fun x ->
           String.starts_with ~prefix:"snapshot-" x
           && String.ends_with ~suffix:".bin" x)
    |> List.sort (fun a b -> String.compare b a)
  in
  let rec choose = function
    | [] -> (Storage.fresh t, None)
    | name :: rest -> (
        try
          let envelope =
            strict_json
              (Storage.read_bounded (Filename.concat dir name)
                 (512 * 1024 * 1024))
          in
          let b = get "body" envelope in
          if
            canonical envelope
            <> canonical
                 (obj [ ("body", b); ("checksum", get "checksum" envelope) ])
          then invalid_arg "snapshot envelope fields";
          if get "checksum" envelope <> s (hash b) then
            invalid_arg "snapshot checksum";
          let session = Session.restore (get "state" b) in
          if canonical b <> canonical (body t scanned session) then
            invalid_arg "snapshot metadata or boundary";
          if
            session.session_id <> str (get "session_id" t.Storage.metadata)
            || config session.config <> get "configuration" t.metadata
          then invalid_arg "snapshot session mismatch";
          (session, Some name)
        with exn ->
          prerr_endline
            ("snapshot rejected: " ^ name ^ ": " ^ Printexc.to_string exn);
          choose rest)
  in
  let session, selected = choose files in
  List.iter
    (fun (r : Storage.record) ->
      if r.seq > session.Session.last_seq then
        ignore (Session.apply session r.seq r.command))
    scanned.Storage.records;
  Session.validate session;
  (session, selected)
