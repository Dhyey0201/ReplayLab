(* No environment activation. Only the separate test executable configures these. *)
type mutant = Correct | Lifo | Incoming_price | Middle_cancel | Missing_dedupe

let mutant = ref Correct
let hook_name = ref ""
let hook_seq = ref 0L
let notification_fd = ref (-1)
let control_fd = ref (-1)
let reached = ref false

let configure_mutant = function
  | "lifo" -> mutant := Lifo
  | "incoming-price" -> mutant := Incoming_price
  | "middle-cancel" -> mutant := Middle_cancel
  | "missing-dedupe" -> mutant := Missing_dedupe
  | _ -> invalid_arg "unknown test mutant"

external fd_of_int : int -> Unix.file_descr = "%identity"

let hook name seq =
  if (not !reached) && name = !hook_name && seq = !hook_seq then (
    reached := true;
    if !notification_fd < 0 || !control_fd < 0 then
      invalid_arg "hook requires control pipes";
    let message = Printf.sprintf "%s %Ld\n" name seq in
    let fd = fd_of_int !notification_fd in
    let rec write offset =
      if offset < String.length message then
        let n =
          Unix.write_substring fd message offset (String.length message - offset)
        in
        if n = 0 then failwith "hook notification failed" else write (offset + n)
    in
    write 0;
    let byte = Bytes.create 1 in
    ignore (Unix.read (fd_of_int !control_fd) byte 0 1);
    failwith "crash controller released a hook without killing child")
