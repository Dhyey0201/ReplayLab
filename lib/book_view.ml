open Domain
open Book

let levels t = function Buy -> t.bids | Sell -> t.asks

let export t =
  let open Codec in
  let side which =
    let bindings = Prices.bindings (levels t which) in
    let bindings = if which = Buy then List.rev bindings else bindings in
    arr
      (List.map
         (fun (price, l) ->
           let rec walk acc = function
             | None -> List.rev acc
             | Some node ->
                 let o = node.order in
                 walk
                   (obj
                      [
                        ("client_id", s (fst o.key));
                        ("order_id", s (snd o.key));
                        ("acceptance_seq", n o.acceptance_seq);
                        ("remaining_quantity", n o.remaining);
                      ]
                   :: acc)
                   node.next
           in
           obj
             [
               ("price_ticks", n price);
               ("quantity", n l.quantity);
               ("orders", arr (walk [] l.head));
             ])
         bindings)
  in
  obj [ ("bids", side Buy); ("asks", side Sell) ]
