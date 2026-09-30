open Replaylab
open Codec

let () =
  try
    let mode = ref "memory-session"
    and input = ref ""
    and directory = ref ""
    and snapshot = ref true in
    Arg.parse
      [
        ( "--mode",
          Arg.Set_string mode,
          "book-kernel|memory-session|json-batch|durable-session|recovery" );
        ("--input", Arg.Set_string input, "saved workload");
        ("--session-dir", Arg.Set_string directory, "durable directory");
        ("--no-snapshot", Arg.Clear snapshot, "full replay");
      ]
      (fun _ -> invalid_arg "unexpected argument")
      "Native benchmark boundaries";
    let samples = ref []
    and attempts = ref 0L
    and duplicates = ref 0L
    and rejections = ref 0L
    and protocols = ref 0L in
    let account response =
      if get "duplicate" response = `Bool true then
        duplicates := Domain.add !duplicates 1L;
      let status = get "status" (get "result" response) in
      if status = s "rejected" then rejections := Domain.add !rejections 1L;
      if status = s "error" then protocols := Domain.add !protocols 1L
    in
    let measure f =
      let start = Timing.now_ns () in
      let result = f () in
      samples := Int64.sub (Timing.now_ns ()) start :: !samples;
      result
    in
    let session = ref (Session.create "benchmark") in
    let kernel = Book.create () in
    let kernel_orders = ref 0L and kernel_trades = ref 0L in
    let overhead =
      List.init 1000 (fun _ ->
          let start = Timing.now_ns () in
          Int64.sub (Timing.now_ns ()) start)
      |> List.sort Int64.compare
    in
    let gc_before = Gc.quick_stat () in
    let start, finish =
      if !mode = "recovery" then (
        let start = Timing.now_ns () in
        let store = Storage.open_existing !directory in
        Fun.protect
          ~finally:(fun () -> Storage.close store)
          (fun () ->
            let scanned = Storage.scan store in
            if scanned.incomplete_tail then Storage.error "incomplete journal";
            session :=
              if !snapshot then fst (Snapshot.recover store scanned)
              else Storage.replay store scanned);
        let finish = Timing.now_ns () in
        samples := [ Int64.sub finish start ];
        (start, finish))
      else (
        if !input = "" then invalid_arg "--input required";
        let raws =
          Driver.with_in (Some !input) (fun channel ->
              let rec loop acc =
                match Driver.read_line_bounded channel 16384 with
                | None -> List.rev acc
                | Some raw -> loop (raw :: acc)
              in
              loop [])
        in
        let commands =
          if !mode = "json-batch" then []
          else
            List.map
              (fun raw -> try Some (parse raw) with Protocol _ -> None)
              raws
        in
        let store =
          if !mode = "durable-session" then
            Some (Storage.create !directory "benchmark" Domain.default_config)
          else None
        in
        let before_apply = Option.map Storage.append store in
        (if !mode = "book-kernel" then
           let seen_requests = Hashtbl.create 128
           and seen_orders = Hashtbl.create 128 in
           List.iter
             (function
               | None -> invalid_arg "kernel input must be schema-valid"
               | Some c -> (
                   if
                     c.Domain.instrument <> "SIM"
                     || Hashtbl.mem seen_requests (c.client_id, c.request_id)
                   then
                     invalid_arg
                       "kernel input must have unique requests for SIM";
                   Hashtbl.add seen_requests (c.client_id, c.request_id) ();
                   match c.action with
                   | Domain.Cancel -> ()
                   | Domain.New _ ->
                       if Hashtbl.mem seen_orders (c.client_id, c.order_id) then
                         invalid_arg "kernel order identity reused";
                       Hashtbl.add seen_orders (c.client_id, c.order_id) ()))
             commands);
        let start = Timing.now_ns () in
        Fun.protect
          ~finally:(fun () -> Option.iter Storage.close store)
          (fun () ->
            if !mode = "json-batch" then
              List.iter
                (fun raw ->
                  let response =
                    measure (fun () ->
                        let r = Session.handle !session raw in
                        ignore (canonical r);
                        r)
                  in
                  attempts := Domain.add !attempts 1L;
                  account response)
                raws
            else if !mode = "book-kernel" then
              List.iter
                (function
                  | None -> ()
                  | Some c ->
                      attempts := Domain.add !attempts 1L;
                      let accepted, trades, rejected =
                        measure (fun () ->
                            match c.Domain.action with
                            | Domain.Cancel ->
                                ( 0L,
                                  0L,
                                  Book.cancel kernel (c.client_id, c.order_id)
                                  = None )
                            | Domain.New x ->
                                let o : Domain.order =
                                  {
                                    key = (c.client_id, c.order_id);
                                    side = x.side;
                                    price = x.price;
                                    original = x.quantity;
                                    acceptance_seq = !attempts;
                                    remaining = x.quantity;
                                    filled = 0L;
                                    cancelled = 0L;
                                    status = Domain.Active;
                                  }
                                in
                                let fills = Book.match_order kernel o in
                                (1L, Int64.of_int (List.length fills), false))
                      in
                      kernel_orders := Domain.add !kernel_orders accepted;
                      kernel_trades := Domain.add !kernel_trades trades;
                      if rejected then rejections := Domain.add !rejections 1L)
                commands
            else if List.mem !mode [ "memory-session"; "durable-session" ] then
              List.iter
                (function
                  | None -> protocols := Domain.add !protocols 1L
                  | Some c ->
                      attempts := Domain.add !attempts 1L;
                      let response =
                        measure (fun () ->
                            Session.submit ?before_apply !session c)
                      in
                      account response)
                commands
            else invalid_arg "invalid benchmark mode");
        (start, Timing.now_ns ()))
    in
    let gc_after = Gc.quick_stat () in
    let state = !session in
    let trade_count =
      if !mode = "book-kernel" then !kernel_trades
      else
        Hashtbl.fold
          (fun _ c total ->
            List.fold_left
              (fun n e ->
                if get "type" e = s "trade" then Domain.add n 1L else n)
              total
              (list (get "events" c.Session.response)))
          state.requests 0L
    in
    let measured_book = if !mode = "book-kernel" then kernel else state.book in
    let samples = List.rev !samples in
    let percentile p =
      let sorted = List.sort Int64.compare samples in
      match sorted with
      | [] -> 0L
      | _ ->
          List.nth sorted (max 0 ((((List.length sorted * p) + 99) / 100) - 1))
    in
    Driver.output stdout
      (obj
         [
           ("schema_version", `Int 1);
           ("mode", s !mode);
           ("elapsed_ns", n (Int64.sub finish start));
           ("sample_count", s (string_of_int (List.length samples)));
           ("samples_ns", arr (List.map n samples));
           ("latency_median_ns", n (percentile 50));
           ("latency_p95_ns", n (percentile 95));
           ("latency_p99_ns", n (percentile 99));
           ("latency_max_ns", n (percentile 100));
           ("clock_pair_median_ns", n (List.nth overhead 500));
           ("attempts", n !attempts);
           ( "unique_commands",
             n (if !mode = "book-kernel" then !attempts else state.last_seq) );
           ( "accepted_orders",
             n
               (if !mode = "book-kernel" then !kernel_orders
                else Int64.of_int (Hashtbl.length state.orders)) );
           ("trades", n trade_count);
           ("duplicates", n !duplicates);
           ("business_rejections", n !rejections);
           ("unsequenced_or_invalid", n !protocols);
           ( "active_orders",
             s (string_of_int (Hashtbl.length measured_book.active)) );
           ( "active_levels",
             s
               (string_of_int
                  (Book.Prices.cardinal measured_book.bids
                  + Book.Prices.cardinal measured_book.asks)) );
           ("retained_orders", s (string_of_int (Hashtbl.length state.orders)));
           ("dedupe_entries", s (string_of_int (Hashtbl.length state.requests)));
           ("peak_rss_bytes", n (Timing.peak_rss_bytes ()));
           ( "allocated_words",
             s
               (Printf.sprintf "%.0f"
                  (gc_after.minor_words +. gc_after.major_words
                 -. gc_after.promoted_words
                  -. (gc_before.minor_words +. gc_before.major_words
                    -. gc_before.promoted_words))) );
           ( "minor_collections",
             s
               (string_of_int
                  (gc_after.minor_collections - gc_before.minor_collections)) );
           ( "session_hash",
             if !mode = "book-kernel" then `Null
             else s (hash (Session.export state)) );
         ])
  with exn ->
    prerr_endline (Printexc.to_string exn);
    exit 2
