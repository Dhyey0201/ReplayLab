open Domain
open Codec

type cached = {
  payload : Yojson.Safe.t;
  bytes : string;
  response : Yojson.Safe.t;
}

type t = {
  session_id : string;
  config : config;
  book : Book.t;
  orders : (key, order) Hashtbl.t;
  requests : (key, cached) Hashtbl.t;
  mutable next_seq : int64 option;
  mutable last_seq : int64;
  mutable event_count : int64;
  mutable event_digest : string;
}

let create ?(config = default_config) session_id =
  if not (valid_id session_id) then invalid_arg "invalid session ID";
  validate_config config;
  {
    session_id;
    config;
    book = Book.create ();
    orders = Hashtbl.create 128;
    requests = Hashtbl.create 128;
    next_seq = Some 1L;
    last_seq = 0L;
    event_count = 0L;
    event_digest = sha_raw "replaylab-events-v1";
  }

let envelope t ?(duplicate = false) ?(durable = false) ids semantic =
  let fields = match semantic with `Assoc xs -> xs | _ -> assert false in
  let id k = match List.assoc_opt k ids with Some v -> v | None -> `Null in
  obj
    ([
       ("schema_version", `Int 1);
       ("session_id", s t.session_id);
       ("client_id", id "client_id");
       ("request_id", id "request_id");
       ("duplicate", `Bool duplicate);
       ("durability", s (if durable then "synced" else "none"));
     ]
    @ fields)

let ids (c : command) =
  [ ("client_id", s c.client_id); ("request_id", s c.request_id) ]

let error t ?subcode identities code =
  let result =
    obj
      ([ ("status", s "error"); ("code", s code) ]
      @ match subcode with None -> [] | Some x -> [ ("subcode", s x) ])
  in
  envelope t identities
    (obj [ ("seq", `Null); ("result", result); ("events", arr []) ])

let execute ?(after_fill = fun () -> ()) t seq c =
  let kind = match c.action with New _ -> "new" | Cancel -> "cancel" in
  let base = [ ("command_type", s kind); ("order_id", s c.order_id) ] in
  let rejected code =
    (obj (base @ [ ("status", s "rejected"); ("code", s code) ]), [])
  in
  let event index kind fields =
    obj
      ([
         ("session_id", s t.session_id);
         ("seq", n seq);
         ("event_index", n index);
         ("type", s kind);
         ("instrument", s "SIM");
       ]
      @ fields)
  in
  let order_key = (c.client_id, c.order_id) in
  if c.instrument <> "SIM" then rejected "UNKNOWN_INSTRUMENT"
  else
    match c.action with
    | Cancel -> (
        match Book.cancel t.book order_key with
        | None -> rejected "ORDER_NOT_ACTIVE"
        | Some (o, amount) ->
            ( obj
                (base
                @ [
                    ("status", s "accepted");
                    ("order_status", s "cancelled");
                    ("cancelled_quantity", n amount);
                  ]),
              [
                event 0L "cancelled"
                  [ ("order", key o.key); ("cancelled_quantity", n amount) ];
              ] ))
    | New x ->
        if Hashtbl.mem t.orders order_key then rejected "ORDER_ID_REUSED"
        else if
          Int64.of_int (Hashtbl.length t.orders) >= t.config.max_accepted_orders
        then rejected "SESSION_ORDER_LIMIT"
        else
          let incoming =
            {
              key = order_key;
              side = x.side;
              price = x.price;
              original = x.quantity;
              acceptance_seq = seq;
              remaining = x.quantity;
              filled = 0L;
              cancelled = 0L;
              status = Active;
            }
          in
          Hashtbl.add t.orders order_key incoming;
          let trades = Book.match_order ~after_fill t.book incoming in
          let events =
            List.mapi
              (fun index ((resting : order), quantity) ->
                let buyer, seller =
                  if incoming.side = Buy then (incoming, resting)
                  else (resting, incoming)
                in
                event (Int64.of_int index) "trade"
                  [
                    ("resting", key resting.key);
                    ("incoming", key incoming.key);
                    ("buyer", key buyer.key);
                    ("seller", key seller.key);
                    ( "price_ticks",
                      n
                        (if !Testing.mutant = Testing.Incoming_price then
                           incoming.price
                         else resting.price) );
                    ("quantity", n quantity);
                  ])
              trades
          in
          ( obj
              (base
              @ [
                  ("status", s "accepted");
                  ("order_status", s (status_string incoming.status));
                  ("original_quantity", n incoming.original);
                  ("filled_quantity", n incoming.filled);
                  ("remaining_quantity", n incoming.remaining);
                  ("cancelled_quantity", n incoming.cancelled);
                ]),
            events )

let apply ?after_fill t seq c =
  assert (t.next_seq = Some seq);
  assert (not (Hashtbl.mem t.requests (c.client_id, c.request_id)));
  assert (
    Int64.of_int (Hashtbl.length t.requests) < t.config.max_unique_requests);
  let result, events = execute ?after_fill t seq c in
  let response =
    obj [ ("seq", n seq); ("result", result); ("events", arr events) ]
  in
  let payload = payload c in
  Hashtbl.add t.requests
    (c.client_id, c.request_id)
    { payload; bytes = canonical payload; response };
  t.last_seq <- seq;
  t.next_seq <- successor seq;
  List.iter
    (fun event ->
      t.event_digest <- update_digest t.event_digest event;
      t.event_count <- add t.event_count 1L)
    events;
  response

let submit ?(durable = false) ?(before_apply = fun _ _ -> ()) ?after_fill t c =
  let identity = ids c in
  if !Testing.mutant = Testing.Missing_dedupe then
    Hashtbl.remove t.requests (c.client_id, c.request_id);
  match Hashtbl.find_opt t.requests (c.client_id, c.request_id) with
  | Some cached ->
      if cached.bytes <> canonical (payload c) then
        error t identity "IDEMPOTENCY_CONFLICT"
      else envelope t ~duplicate:true ~durable identity cached.response
  | None -> (
      if
        Int64.of_int (Hashtbl.length t.requests) >= t.config.max_unique_requests
      then error t identity "SESSION_REQUEST_LIMIT"
      else
        match t.next_seq with
        | None -> error t identity "SEQUENCE_EXHAUSTED"
        | Some seq ->
            before_apply seq c;
            let response = apply ?after_fill t seq c in
            envelope t ~durable identity response)

let handle ?durable ?before_apply ?after_fill t raw =
  match parse ~max_line_bytes:t.config.max_line_bytes raw with
  | c -> submit ?durable ?before_apply ?after_fill t c
  | exception Protocol (code, identities) ->
      error t ~subcode:code identities "PROTOCOL_ERROR"

let sorted table =
  Hashtbl.fold (fun key value acc -> (key, value) :: acc) table []
  |> List.sort (fun (a, _) (b, _) -> compare a b)

let export t =
  obj
    [
      ("schema_version", `Int 1);
      ("semantics_version", s Version.semantics);
      ("session_id", s t.session_id);
      ("configuration", config t.config);
      ("last_applied_seq", n t.last_seq);
      ("next_seq", match t.next_seq with None -> `Null | Some x -> n x);
      ("orders", arr (List.map (fun (_, o) -> order o) (sorted t.orders)));
      ( "requests",
        arr
          (List.map
             (fun ((client, request), v) ->
               obj
                 [
                   ("client_id", s client);
                   ("request_id", s request);
                   ("payload", v.payload);
                   ("response", v.response);
                 ])
             (sorted t.requests)) );
      ("event_count", n t.event_count);
      ("event_digest", s (hex t.event_digest));
    ]

let validate t =
  Book.validate t.book t.orders;
  let filled = Hashtbl.fold (fun _ o total -> add total o.filled) t.orders 0L in
  let quantity = ref 0L and count = ref 0L in
  Hashtbl.iter
    (fun _ cached ->
      List.iter
        (fun event ->
          count := add !count 1L;
          if get "type" event = s "trade" then
            quantity := add !quantity (num (get "quantity" event)))
        (list (get "events" cached.response)))
    t.requests;
  assert (filled = add !quantity !quantity && !count = t.event_count)

let restore json =
  let t =
    create
      ~config:(config_of_json (get "configuration" json))
      (str (get "session_id" json))
  in
  if
    get "schema_version" json <> `Int 1
    || get "semantics_version" json <> s Version.semantics
  then invalid_arg "snapshot versions";
  let orders = list (get "orders" json) in
  if Int64.of_int (List.length orders) > t.config.max_accepted_orders then
    invalid_arg "snapshot order limit";
  List.iter
    (fun j ->
      let client = str (get "client_id" j) and local = str (get "order_id" j) in
      if
        (not (valid_id client && valid_id local))
        || Hashtbl.mem t.orders (client, local)
      then invalid_arg "snapshot order key";
      let side =
        match str (get "side" j) with
        | "buy" -> Buy
        | "sell" -> Sell
        | _ -> invalid_arg "snapshot side"
      in
      let status =
        match str (get "status" j) with
        | "active" -> Active
        | "filled" -> Filled
        | "cancelled" -> Cancelled
        | _ -> invalid_arg "snapshot status"
      in
      let o =
        {
          key = (client, local);
          side;
          status;
          price = num (get "price_ticks" j);
          original = num (get "original_quantity" j);
          acceptance_seq = num (get "acceptance_seq" j);
          remaining = num (get "remaining_quantity" j);
          filled = num (get "filled_quantity" j);
          cancelled = num (get "cancelled_quantity" j);
        }
      in
      if
        o.price < 1L || o.price > 1000000000L || o.original < 1L
        || o.original > 1000000000L || o.acceptance_seq < 1L
      then invalid_arg "snapshot order numeric";
      Hashtbl.add t.orders o.key o)
    orders;
  let active =
    Hashtbl.fold
      (fun _ o acc -> if o.status = Active then o :: acc else acc)
      t.orders []
  in
  List.iter (Book.insert t.book)
    (List.sort
       (fun a b -> Int64.compare a.acceptance_seq b.acceptance_seq)
       active);
  let requests = list (get "requests" json) in
  if Int64.of_int (List.length requests) > t.config.max_unique_requests then
    invalid_arg "snapshot request limit";
  List.iter
    (fun j ->
      let client = str (get "client_id" j)
      and request = str (get "request_id" j) in
      if
        (not (valid_id client && valid_id request))
        || Hashtbl.mem t.requests (client, request)
      then invalid_arg "snapshot request key";
      let payload = get "payload" j and response = get "response" j in
      Hashtbl.add t.requests (client, request)
        { payload; response; bytes = canonical payload })
    requests;
  t.last_seq <- num (get "last_applied_seq" json);
  t.next_seq <-
    (match get "next_seq" json with `Null -> None | j -> Some (num j));
  if
    t.next_seq <> successor t.last_seq
    || t.last_seq <> Int64.of_int (List.length requests)
  then invalid_arg "snapshot sequence";
  t.event_count <- num (get "event_count" json);
  t.event_digest <- unhex (str (get "event_digest" json));
  let sorted_requests =
    Hashtbl.fold (fun _ c acc -> c :: acc) t.requests []
    |> List.sort (fun a b ->
           Int64.compare
             (num (get "seq" a.response))
             (num (get "seq" b.response)))
  in
  let history = ref (sha_raw "replaylab-events-v1") in
  List.iteri
    (fun i c ->
      if num (get "seq" c.response) <> Int64.of_int (i + 1) then
        invalid_arg "snapshot cached sequence";
      List.iter
        (fun e -> history := update_digest !history e)
        (list (get "events" c.response)))
    sorted_requests;
  if !history <> t.event_digest then invalid_arg "snapshot history digest";
  validate t;
  if canonical (export t) <> canonical json then
    invalid_arg "snapshot noncanonical state";
  t
