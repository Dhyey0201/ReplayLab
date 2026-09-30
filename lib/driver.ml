open Codec

let with_in path f =
  match path with
  | None -> f stdin
  | Some p ->
      let c = open_in_bin p in
      Fun.protect ~finally:(fun () -> close_in c) (fun () -> f c)

let with_out path f =
  match path with
  | None -> f stdout
  | Some p ->
      let c = open_out_bin p in
      Fun.protect ~finally:(fun () -> close_out c) (fun () -> f c)

let output channel json =
  output_string channel (canonical json);
  output_char channel '\n';
  flush channel

let write_json path json = with_out (Some path) (fun c -> output c json)

let read_line_bounded input limit =
  let buffer = Buffer.create 256 in
  let seen = ref false and ended = ref false in
  (try
     while not !ended do
       let c = input_char input in
       seen := true;
       if c = '\n' then ended := true
       else if Buffer.length buffer <= limit then Buffer.add_char buffer c
     done
   with End_of_file -> ());
  if not !seen then None else Some (Buffer.contents buffer)

let stream ?(validate = false) ?before_apply ?(durable = false)
    ?(hook = fun _ _ -> ()) ?trace ?(trace_interval = 1) session input
    output_channel =
  let protocol_errors = ref 0 in
  let counters = Hashtbl.create 12 in
  List.iter
    (fun key -> Hashtbl.add counters key 0L)
    [
      "attempts";
      "duplicates";
      "conflicts";
      "business_rejections";
      "unique_commands";
      "accepted_orders";
      "unique_trades";
      "cancellations";
    ];
  let count key =
    Hashtbl.replace counters key (Domain.add (Hashtbl.find counters key) 1L)
  in
  let rec loop () =
    match read_line_bounded input session.Session.config.max_line_bytes with
    | None -> !protocol_errors
    | Some raw ->
        let seq = session.next_seq and before = session.last_seq in
        let after_fill () =
          Option.iter (hook "during_match_after_first_fill") seq
        in
        let response =
          Session.handle ~durable ?before_apply ~after_fill session raw
        in
        count "attempts";
        let result = get "result" response in
        if get "duplicate" response = `Bool true then count "duplicates"
        else if get "seq" response <> `Null then (
          count "unique_commands";
          if get "status" result = s "rejected" then count "business_rejections";
          if
            get "status" result = s "accepted"
            && get "command_type" result = s "new"
          then count "accepted_orders";
          List.iter
            (fun event ->
              count
                (if get "type" event = s "trade" then "unique_trades"
                 else "cancellations"))
            (list (get "events" response)));
        if get "code" result = s "IDEMPOTENCY_CONFLICT" then count "conflicts";
        if validate then Session.validate session;
        if get "code" (get "result" response) = s "PROTOCOL_ERROR" then
          incr protocol_errors;
        if before <> session.last_seq then
          hook "after_apply_before_response" session.last_seq;
        output output_channel response;
        if before <> session.last_seq then
          hook "after_response" session.last_seq;
        if
          Int64.rem
            (Hashtbl.find counters "attempts")
            (Int64.of_int trace_interval)
          = 0L
        then
          Option.iter
            (fun channel -> output channel (Session.export session))
            trace;
        loop ()
  in
  let errors = loop () in
  let fields =
    Hashtbl.fold (fun key value acc -> (key, n value) :: acc) counters []
  in
  output stderr
    (obj
       ([
          ("component", s "run_summary");
          ("protocol_errors", s (string_of_int errors));
          ("last_applied_seq", n session.last_seq);
          ("book_hash", s (hash (Book_view.export session.book)));
          ("session_hash", s (hash (Session.export session)));
        ]
       @ fields));
  errors

let usage =
  "ReplayLab: run|stream|recover|replay|verify-log|snapshot|inspect\n\
   Use COMMAND --help for arguments. Fresh durable runs require an empty \
   session directory; recover continues it."

let cli_int64 value =
  try Int64.of_string value
  with Failure _ -> invalid_arg "invalid integer option"

let main ?(testing = false) () =
  let input = ref None
  and responses = ref None
  and state_out = ref None
  and events_out = ref None
  and trace = ref None in
  let session_id = ref ""
  and mode = ref "memory"
  and dir = ref ""
  and view = ref "session" in
  let validate = ref false
  and repair = ref false
  and fail_protocol = ref false
  and no_snapshot = ref false in
  let config = ref Domain.default_config in
  let trace_interval = ref 1 in
  let command = if Array.length Sys.argv > 1 then Sys.argv.(1) else "--help" in
  if command = "--version" then print_endline Version.version
  else if command = "--help" then print_endline usage
  else (
    if
      not
        (List.mem command
           [
             "run";
             "stream";
             "recover";
             "replay";
             "verify-log";
             "snapshot";
             "inspect";
           ])
    then invalid_arg "unknown command";
    let path r = Arg.String (fun p -> r := Some p) in
    let options =
      [
        ("--mode", Arg.Set_string mode, "memory|durable");
        ("--session-id", Arg.Set_string session_id, "explicit fresh session ID");
        ("--session-dir", Arg.Set_string dir, "session directory");
        ("--input", path input, "input JSONL");
        ("--responses", path responses, "response JSONL");
        ("--state-out", path state_out, "canonical session state");
        ( "--state-trace",
          path trace,
          "full state after every attempt (expensive)" );
        ("--events-out", path events_out, "unique event JSONL");
        ("--view", Arg.Set_string view, "book|session");
        ("--validate", Arg.Set validate, "invariants after every attempt");
        ( "--state-checkpoint",
          Arg.Set_int trace_interval,
          "state trace interval, positive" );
        ( "--repair-incomplete-tail",
          Arg.Set repair,
          "repair only an incomplete final frame during recover" );
        ( "--fail-on-protocol-error",
          Arg.Set fail_protocol,
          "exit 1 after processing malformed records" );
        ( "--no-snapshot",
          Arg.Set no_snapshot,
          "reconstruct by full journal replay" );
        ( "--max-orders",
          Arg.String
            (fun v ->
              config := { !config with max_accepted_orders = cli_int64 v }),
          "accepted order record limit" );
        ( "--max-requests",
          Arg.String
            (fun v ->
              config := { !config with max_unique_requests = cli_int64 v }),
          "unique request limit" );
      ]
      @
      if testing then
        [
          ("--mutant", Arg.String Testing.configure_mutant, "test-only mutant");
          ("--hook", Arg.Set_string Testing.hook_name, "test-only hook");
          ( "--hook-seq",
            Arg.String (fun x -> Testing.hook_seq := cli_int64 x),
            "hook sequence" );
          ( "--notify-fd",
            Arg.Set_int Testing.notification_fd,
            "notification pipe" );
          ( "--control-fd",
            Arg.Set_int Testing.control_fd,
            "blocking control pipe" );
        ]
      else []
    in
    let current = ref 1 in
    Arg.parse_argv ~current Sys.argv options
      (fun _ -> raise (Arg.Bad "unexpected positional argument"))
      usage;
    Domain.validate_config !config;
    if !trace_interval < 1 then
      invalid_arg "checkpoint interval must be positive";
    if !mode <> "memory" && !mode <> "durable" then invalid_arg "invalid mode";
    if !view <> "book" && !view <> "session" then invalid_arg "invalid view";
    if !repair && command <> "recover" then
      invalid_arg "repair is only valid for recover";
    let hook = if testing then Testing.hook else fun _ _ -> () in
    let execute ?store session =
      let before_apply = Option.map (fun t -> Storage.append ~hook t) store in
      let errors =
        with_in !input (fun i ->
            with_out !responses (fun o ->
                match !trace with
                | None ->
                    stream ~validate:!validate ?before_apply
                      ~durable:(store <> None) ~hook session i o
                | Some path ->
                    with_out (Some path) (fun tr ->
                        stream ~validate:!validate ?before_apply
                          ~durable:(store <> None) ~hook ~trace:tr
                          ~trace_interval:!trace_interval session i o)))
      in
      Option.iter
        (fun path -> write_json path (Session.export session))
        !state_out;
      if errors > 0 && !fail_protocol then 1 else 0
    in
    let exit_code =
      if (command = "run" || command = "stream") && !mode = "memory" then
        execute (Session.create ~config:!config !session_id)
      else (
        if !dir = "" then invalid_arg "--session-dir is required";
        let store =
          if command = "run" || command = "stream" then
            Storage.create !dir !session_id !config
          else Storage.open_existing !dir
        in
        Fun.protect
          ~finally:(fun () -> Storage.close store)
          (fun () ->
            if command = "run" || command = "stream" then
              execute ~store (Storage.fresh store)
            else
              let scanned = Storage.scan store in
              if command = "verify-log" then (
                output stdout
                  (obj
                     [
                       ( "valid_frames",
                         s (string_of_int (List.length scanned.records)) );
                       ("valid_bytes", n scanned.valid_bytes);
                       ("incomplete_tail", `Bool scanned.incomplete_tail);
                     ]);
                if scanned.incomplete_tail then 3 else 0)
              else (
                if
                  scanned.incomplete_tail && not (command = "recover" && !repair)
                then
                  Storage.error
                    "incomplete tail: recover requires --repair-incomplete-tail";
                if scanned.incomplete_tail then Storage.repair store scanned;
                let session, selected =
                  if !no_snapshot then (Storage.replay store scanned, None)
                  else Snapshot.recover store scanned
                in
                match command with
                | "recover" -> execute ~store session
                | "snapshot" ->
                    let path = Snapshot.publish ~hook store scanned session in
                    output stdout
                      (obj
                         [ ("snapshot", s path); ("seq", n session.last_seq) ]);
                    0
                | "inspect" ->
                    output stdout
                      (if !view = "book" then Book_view.export session.book
                       else Session.export session);
                    0
                | "replay" ->
                    Option.iter
                      (fun path -> write_json path (Session.export session))
                      !state_out;
                    Option.iter
                      (fun path ->
                        with_out (Some path) (fun channel ->
                            Session.sorted session.requests
                            |> List.map snd
                            |> List.sort (fun a b ->
                                   Int64.compare
                                     (num (get "seq" a.Session.response))
                                     (num (get "seq" b.Session.response)))
                            |> List.iter (fun c ->
                                   List.iter (output channel)
                                     (list (get "events" c.Session.response)))))
                      !events_out;
                    output stdout
                      (obj
                         [
                           ("session_hash", s (hash (Session.export session)));
                           ("last_applied_seq", n session.last_seq);
                           ( "snapshot",
                             match selected with None -> `Null | Some x -> s x
                           );
                         ]);
                    0
                | _ -> invalid_arg "invalid session command")))
    in
    if exit_code <> 0 then exit exit_code)

let entry ?testing () =
  Sys.catch_break true;
  try main ?testing () with
  | Sys.Break ->
      prerr_endline "ReplayLab: interrupted; session handles closed";
      exit 0
  | Arg.Bad message | Invalid_argument message ->
      prerr_endline message;
      exit 2
  | Arg.Help message -> print_string message
  | Storage.Error message | Sys_error message ->
      prerr_endline message;
      exit 3
  | Unix.Unix_error (error, op, path) ->
      prerr_endline (op ^ " " ^ path ^ ": " ^ Unix.error_message error);
      exit 3
  | exn ->
      prerr_endline (Printexc.to_string exn);
      exit 1
