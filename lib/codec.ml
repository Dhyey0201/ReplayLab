open Domain

let s x = `String x
let n x = s (Int64.to_string x)
let obj fields = `Assoc fields
let arr xs = `List xs

let get key = function
  | `Assoc xs -> ( try List.assoc key xs with Not_found -> `Null)
  | _ -> `Null

let str = function `String x -> x | _ -> invalid_arg "expected string"
let num j = Int64.of_string (str j)
let list = function `List xs -> xs | _ -> invalid_arg "expected array"
let key (client, order) = obj [ ("client_id", s client); ("order_id", s order) ]

let config c =
  obj
    [
      ("max_accepted_orders", n c.max_accepted_orders);
      ("max_unique_requests", n c.max_unique_requests);
      ("max_line_bytes", s (string_of_int c.max_line_bytes));
    ]

let config_of_json j =
  let c =
    {
      max_accepted_orders = num (get "max_accepted_orders" j);
      max_unique_requests = num (get "max_unique_requests" j);
      max_line_bytes = int_of_string (str (get "max_line_bytes" j));
    }
  in
  validate_config c;
  c

let canonical json =
  let b = Buffer.create 256 in
  let string x =
    Buffer.add_char b '"';
    String.iter
      (fun c ->
        match c with
        | '"' -> Buffer.add_string b "\\\""
        | '\\' -> Buffer.add_string b "\\\\"
        | c when Char.code c < 32 ->
            Buffer.add_string b (Printf.sprintf "\\u%04x" (Char.code c))
        | c when Char.code c > 127 -> invalid_arg "non-ASCII canonical string"
        | c -> Buffer.add_char b c)
      x;
    Buffer.add_char b '"'
  in
  let separated f xs =
    List.iteri
      (fun i x ->
        if i > 0 then Buffer.add_char b ',';
        f x)
      xs
  in
  let rec encode = function
    | `Null -> Buffer.add_string b "null"
    | `Bool x -> Buffer.add_string b (string_of_bool x)
    | `Int x -> Buffer.add_string b (string_of_int x)
    | `String x -> string x
    | `List xs ->
        Buffer.add_char b '[';
        separated encode xs;
        Buffer.add_char b ']'
    | `Assoc xs ->
        Buffer.add_char b '{';
        separated
          (fun (k, v) ->
            string k;
            Buffer.add_char b ':';
            encode v)
          (List.sort (fun (a, _) (b, _) -> String.compare a b) xs);
        Buffer.add_char b '}'
    | _ -> invalid_arg "outside canonical subset"
  in
  encode json;
  Buffer.contents b

let sha_raw text = Digestif.SHA256.(to_raw_string (digest_string text))
let sha text = Digestif.SHA256.(to_hex (digest_string text))
let hash j = sha (canonical j)

let hex raw =
  String.concat ""
    (List.init (String.length raw) (fun i ->
         Printf.sprintf "%02x" (Char.code raw.[i])))

let unhex hex =
  if String.length hex <> 64 then invalid_arg "invalid digest";
  String.init 32 (fun i ->
      Char.chr (int_of_string ("0x" ^ String.sub hex (i * 2) 2)))

let update_digest previous event =
  let bytes = canonical event in
  let len = Bytes.create 8 in
  Bytes.set_int64_be len 0 (Int64.of_int (String.length bytes));
  sha_raw (previous ^ Bytes.to_string len ^ bytes)

exception Protocol of string * (string * Yojson.Safe.t) list

let fail ?(ids = []) code = raise (Protocol (code, ids))

let valid_utf8 text =
  let rec loop i =
    if i = String.length text then true
    else
      let d = String.get_utf_8_uchar text i in
      Uchar.utf_decode_is_valid d && loop (i + Uchar.utf_decode_length d)
  in
  loop 0

(* Validate the RFC JSON grammar before Yojson, which accepts additional OCaml syntax. *)
let strict_json text =
  let i = ref 0 and length = String.length text in
  let bad () = fail "INVALID_JSON" in
  let peek () = if !i < length then text.[!i] else '\000' in
  let skip () =
    while !i < length && List.mem text.[!i] [ ' '; '\t'; '\r'; '\n' ] do
      incr i
    done
  in
  let take c = if peek () <> c then bad () else incr i in
  let string_token () =
    let start = !i in
    take '"';
    while !i < length && peek () <> '"' do
      if Char.code (peek ()) < 32 then bad ();
      if peek () = '\\' then (
        incr i;
        match peek () with
        | '"' | '\\' | '/' | 'b' | 'f' | 'n' | 'r' | 't' -> incr i
        | 'u' ->
            incr i;
            for _ = 1 to 4 do
              match peek () with
              | '0' .. '9' | 'a' .. 'f' | 'A' .. 'F' -> incr i
              | _ -> bad ()
            done
        | _ -> bad ())
      else incr i
    done;
    take '"';
    String.sub text start (!i - start)
  in
  let literal x = String.iter take x in
  let rec value depth =
    if depth > 256 then bad ();
    skip ();
    match peek () with
    | '"' -> ignore (string_token ())
    | '{' ->
        incr i;
        skip ();
        if peek () = '}' then incr i
        else
          let rec fields () =
            ignore (string_token ());
            skip ();
            take ':';
            value (depth + 1);
            skip ();
            if peek () = ',' then (
              incr i;
              skip ();
              fields ())
            else take '}'
          in
          fields ()
    | '[' ->
        incr i;
        skip ();
        if peek () = ']' then incr i
        else
          let rec entries () =
            value (depth + 1);
            skip ();
            if peek () = ',' then (
              incr i;
              entries ())
            else take ']'
          in
          entries ()
    | 't' -> literal "true"
    | 'f' -> literal "false"
    | 'n' -> literal "null"
    | '-' | '0' .. '9' ->
        if peek () = '-' then incr i;
        (match peek () with
        | '0' -> incr i
        | '1' .. '9' ->
            incr i;
            digits ()
        | _ -> bad ());
        if peek () = '.' then (
          incr i;
          required_digits ());
        if peek () = 'e' || peek () = 'E' then (
          incr i;
          if peek () = '+' || peek () = '-' then incr i;
          required_digits ())
    | _ -> bad ()
  and digits () =
    while !i < length && peek () >= '0' && peek () <= '9' do
      incr i
    done
  and required_digits () =
    let start = !i in
    digits ();
    if start = !i then bad ()
  in
  value 0;
  skip ();
  if !i <> length then bad ();
  let json = try Yojson.Safe.from_string text with _ -> bad () in
  let rec duplicates = function
    | `Assoc xs ->
        let keys = Hashtbl.create 16 in
        List.iter
          (fun (k, v) ->
            if Hashtbl.mem keys k then fail "DUPLICATE_OBJECT_KEY";
            Hashtbl.add keys k ();
            duplicates v)
          xs
    | `List xs -> List.iter duplicates xs
    | _ -> ()
  in
  duplicates json;
  json

let command_json c =
  obj
    ([
       ("schema_version", `Int 1);
       ("type", s (match c.action with New _ -> "new" | Cancel -> "cancel"));
       ("client_id", s c.client_id);
       ("request_id", s c.request_id);
       ("instrument", s c.instrument);
       ("order_id", s c.order_id);
     ]
    @
    match c.action with
    | Cancel -> []
    | New x ->
        [
          ("side", s (side_string x.side));
          ("price_ticks", n x.price);
          ("quantity", n x.quantity);
        ])

let payload c =
  match command_json c with
  | `Assoc xs ->
      obj
        (List.filter
           (fun (k, _) ->
             not (List.mem k [ "schema_version"; "client_id"; "request_id" ]))
           xs)
  | _ -> assert false

let parse ?(max_line_bytes = 16384) raw =
  let raw =
    if String.ends_with ~suffix:"\n" raw then
      String.sub raw 0 (String.length raw - 1)
    else raw
  in
  if String.length raw > max_line_bytes then fail "OVERSIZED_LINE";
  if not (valid_utf8 raw) then fail "INVALID_UTF8";
  let json = strict_json raw in
  let fields =
    match json with `Assoc xs -> xs | _ -> fail "WRONG_FIELD_TYPE"
  in
  let ids =
    List.filter
      (fun (k, v) ->
        List.mem k [ "client_id"; "request_id" ]
        && match v with `String x -> valid_id x | _ -> false)
      fields
  in
  let err = fail ~ids in
  let field k =
    match List.assoc_opt k fields with
    | Some v -> v
    | None -> err "MISSING_FIELD"
  in
  (match field "schema_version" with
  | `Int 1 -> ()
  | `Int _ | `Intlit _ -> err "UNSUPPORTED_SCHEMA_VERSION"
  | _ -> err "WRONG_FIELD_TYPE");
  let text k =
    match field k with `String v -> v | _ -> err "WRONG_FIELD_TYPE"
  in
  let kind = text "type" in
  if kind <> "new" && kind <> "cancel" then err "INVALID_COMMAND_TYPE";
  let names =
    [
      "schema_version";
      "type";
      "client_id";
      "request_id";
      "instrument";
      "order_id";
    ]
    @ if kind = "new" then [ "side"; "price_ticks"; "quantity" ] else []
  in
  if List.exists (fun (k, _) -> not (List.mem k names)) fields then
    err "UNKNOWN_FIELD";
  List.iter (fun k -> ignore (field k)) names;
  let id k =
    let v = text k in
    if not (valid_id v) then err "INVALID_ID";
    v
  in
  let client_id = id "client_id" in
  let request_id = id "request_id" in
  let instrument = id "instrument" in
  let order_id = id "order_id" in
  let positive k =
    let v = text k in
    if
      String.length v = 0
      || v.[0] < '1'
      || v.[0] > '9'
      || not (String.for_all (fun c -> c >= '0' && c <= '9') v)
    then err "INVALID_NUMERIC_ENCODING";
    if String.length v > 10 then err "NUMERIC_OUT_OF_RANGE";
    let x = Int64.of_string v in
    if x > 1000000000L then err "NUMERIC_OUT_OF_RANGE";
    x
  in
  let action =
    if kind = "cancel" then Cancel
    else
      let side =
        match text "side" with
        | "buy" -> Buy
        | "sell" -> Sell
        | _ -> err "INVALID_SIDE"
      in
      let price = positive "price_ticks" in
      let quantity = positive "quantity" in
      New { side; price; quantity }
  in
  { client_id; request_id; instrument; order_id; action }

let order (o : order) =
  obj
    [
      ("client_id", s (fst o.key));
      ("order_id", s (snd o.key));
      ("side", s (side_string o.side));
      ("price_ticks", n o.price);
      ("original_quantity", n o.original);
      ("acceptance_seq", n o.acceptance_seq);
      ("remaining_quantity", n o.remaining);
      ("filled_quantity", n o.filled);
      ("cancelled_quantity", n o.cancelled);
      ("status", s (status_string o.status));
    ]
