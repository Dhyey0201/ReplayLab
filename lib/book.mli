open Domain
module Prices : Map.S with type key = int64

type node = private {
  order : order;
  level : level;
  mutable prev : node option;
  mutable next : node option;
}

and level = private {
  side : side;
  price : int64;
  mutable head : node option;
  mutable tail : node option;
  mutable size : int64;
  mutable quantity : int64;
}

type t = private {
  mutable bids : level Prices.t;
  mutable asks : level Prices.t;
  active : (key, node) Hashtbl.t;
}

val create : unit -> t
val insert : t -> order -> unit
val cancel : t -> key -> (order * int64) option

val match_order :
  ?after_fill:(unit -> unit) -> t -> order -> (order * int64) list

val validate : t -> (key, order) Hashtbl.t -> unit
