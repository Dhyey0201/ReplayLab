exception Error of string

val error : string -> 'a

type io = {
  write : Unix.file_descr -> bytes -> int -> int -> int;
  sync : Unix.file_descr -> unit;
}

val write_all : ?io:io -> Unix.file_descr -> bytes -> int -> int -> unit
val sync : ?io:io -> Unix.file_descr -> unit
val sync_dir : string -> unit
val write_synced : ?exclusive:bool -> string -> string -> unit
val read_bounded : string -> int -> string

type t = private {
  dir : string;
  lock : Unix.file_descr;
  wal : Unix.file_descr;
  metadata : Yojson.Safe.t;
  identity : string;
}

val create : string -> string -> Domain.config -> t
val open_existing : string -> t
val close : t -> unit

val append :
  ?hook:(string -> int64 -> unit) -> t -> int64 -> Domain.command -> unit

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

val scan : t -> scan
val repair : t -> scan -> unit
val fresh : t -> Session.t
val replay : t -> scan -> Session.t
