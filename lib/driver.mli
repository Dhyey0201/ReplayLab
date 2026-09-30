val with_in : string option -> (in_channel -> 'a) -> 'a
val with_out : string option -> (out_channel -> 'a) -> 'a
val output : out_channel -> Yojson.Safe.t -> unit
val write_json : string -> Yojson.Safe.t -> unit
val read_line_bounded : in_channel -> int -> string option
val entry : ?testing:bool -> unit -> unit
