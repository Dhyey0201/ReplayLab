type side = Buy | Sell

let side_string = function Buy -> "buy" | Sell -> "sell"

type key = string * string
type action = New of { side : side; price : int64; quantity : int64 } | Cancel

type command = {
  client_id : string;
  request_id : string;
  instrument : string;
  order_id : string;
  action : action;
}

type config = {
  max_accepted_orders : int64;
  max_unique_requests : int64;
  max_line_bytes : int;
}

let default_config =
  {
    max_accepted_orders = 100000L;
    max_unique_requests = 200000L;
    max_line_bytes = 16384;
  }

let validate_config c =
  if
    c.max_accepted_orders < 1L
    || c.max_accepted_orders > 1000000L
    || c.max_unique_requests < c.max_accepted_orders
    || c.max_unique_requests > 2000000L
    || c.max_line_bytes < 1 || c.max_line_bytes > 16384
  then invalid_arg "invalid semantic limits"

let valid_id s =
  let n = String.length s in
  n >= 1 && n <= 64
  && String.for_all
       (function
         | 'a' .. 'z' | 'A' .. 'Z' | '0' .. '9' | '_' | '-' -> true | _ -> false)
       s

let add a b =
  if a < 0L || b < 0L || a > Int64.sub Int64.max_int b then
    failwith "int64 overflow";
  Int64.add a b

let sub a b =
  if b < 0L || a < b then failwith "quantity underflow" else Int64.sub a b

let successor n = if n = Int64.max_int then None else Some (add n 1L)

type status = Active | Filled | Cancelled

let status_string = function
  | Active -> "active"
  | Filled -> "filled"
  | Cancelled -> "cancelled"

type order = {
  key : key;
  side : side;
  price : int64;
  original : int64;
  acceptance_seq : int64;
  mutable remaining : int64;
  mutable filled : int64;
  mutable cancelled : int64;
  mutable status : status;
}
