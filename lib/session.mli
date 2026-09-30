open Domain

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

val create : ?config:config -> string -> t

val submit :
  ?durable:bool ->
  ?before_apply:(int64 -> command -> unit) ->
  ?after_fill:(unit -> unit) ->
  t ->
  command ->
  Yojson.Safe.t

val handle :
  ?durable:bool ->
  ?before_apply:(int64 -> command -> unit) ->
  ?after_fill:(unit -> unit) ->
  t ->
  string ->
  Yojson.Safe.t

val apply : ?after_fill:(unit -> unit) -> t -> int64 -> command -> Yojson.Safe.t
val sorted : ('a, 'b) Hashtbl.t -> ('a * 'b) list
val export : t -> Yojson.Safe.t
val restore : Yojson.Safe.t -> t
val validate : t -> unit
