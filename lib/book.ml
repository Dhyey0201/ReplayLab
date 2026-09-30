open Domain
module Prices = Map.Make (Int64)

type node = {
  order : order;
  level : level;
  mutable prev : node option;
  mutable next : node option;
}

and level = {
  side : side;
  price : int64;
  mutable head : node option;
  mutable tail : node option;
  mutable size : int64;
  mutable quantity : int64;
}

type t = {
  mutable bids : level Prices.t;
  mutable asks : level Prices.t;
  active : (key, node) Hashtbl.t;
}

let create () =
  { bids = Prices.empty; asks = Prices.empty; active = Hashtbl.create 128 }

let levels t = function Buy -> t.bids | Sell -> t.asks

let set_levels t side map =
  match side with Buy -> t.bids <- map | Sell -> t.asks <- map

let insert t (order : order) =
  let map = levels t order.side in
  let level =
    match Prices.find_opt order.price map with
    | Some x -> x
    | None ->
        let x =
          {
            side = order.side;
            price = order.price;
            head = None;
            tail = None;
            size = 0L;
            quantity = 0L;
          }
        in
        set_levels t order.side (Prices.add order.price x map);
        x
  in
  let node = { order; level; prev = level.tail; next = None } in
  (match level.tail with
  | None -> level.head <- Some node
  | Some tail -> tail.next <- Some node);
  level.tail <- Some node;
  level.size <- add level.size 1L;
  level.quantity <- add level.quantity order.remaining;
  Hashtbl.add t.active order.key node

(* Caller adjusts aggregate quantity exactly once, before unlink. *)
let unlink t node =
  let level = node.level in
  (match node.prev with
  | None -> level.head <- node.next
  | Some p -> p.next <- node.next);
  (match node.next with
  | None -> level.tail <- node.prev
  | Some n -> n.prev <- node.prev);
  level.size <- sub level.size 1L;
  Hashtbl.remove t.active node.order.key;
  node.prev <- None;
  node.next <- None;
  if level.size = 0L then (
    assert (level.quantity = 0L);
    set_levels t level.side (Prices.remove level.price (levels t level.side)))

let cancel t key =
  match Hashtbl.find_opt t.active key with
  | None -> None
  | Some node
    when !Testing.mutant = Testing.Middle_cancel
         && node.prev <> None && node.next <> None ->
      None
  | Some node ->
      let amount = node.order.remaining in
      node.level.quantity <- sub node.level.quantity amount;
      unlink t node;
      node.order.remaining <- 0L;
      node.order.cancelled <- amount;
      node.order.status <- Cancelled;
      Some (node.order, amount)

let best t = function
  | Buy -> Prices.min_binding_opt t.asks
  | Sell -> Prices.max_binding_opt t.bids

let match_order ?(after_fill = fun () -> ()) t (incoming : order) =
  let rec loop acc =
    if incoming.remaining = 0L then List.rev acc
    else
      match best t incoming.side with
      | None -> List.rev acc
      | Some (price, _)
        when if incoming.side = Buy then incoming.price < price
             else incoming.price > price ->
          List.rev acc
      | Some (_, level) ->
          let node =
            Option.get
              (if !Testing.mutant = Testing.Lifo then level.tail else level.head)
          in
          let resting = node.order in
          let quantity = Int64.min incoming.remaining resting.remaining in
          incoming.remaining <- sub incoming.remaining quantity;
          incoming.filled <- add incoming.filled quantity;
          resting.remaining <- sub resting.remaining quantity;
          resting.filled <- add resting.filled quantity;
          level.quantity <- sub level.quantity quantity;
          if resting.remaining = 0L then (
            resting.status <- Filled;
            unlink t node);
          after_fill ();
          loop ((resting, quantity) :: acc)
  in
  let trades = loop [] in
  if incoming.remaining = 0L then incoming.status <- Filled
  else insert t incoming;
  trades

let validate t ledger =
  let seen = Hashtbl.create 128 in
  List.iter
    (fun side ->
      Prices.iter
        (fun price level ->
          assert (level.size > 0L && level.side = side && level.price = price);
          let rec walk previous last_seq count quantity = function
            | None -> (
                assert (count = level.size && quantity = level.quantity);
                match (previous, level.tail) with
                | Some a, Some b -> assert (a == b)
                | _ -> assert false)
            | Some node ->
                assert (not (Hashtbl.mem seen node.order.key));
                Hashtbl.add seen node.order.key ();
                assert (
                  node.level == level && node.order.status = Active
                  && node.order.remaining > 0L);
                assert (
                  node.order.side = side && node.order.price = price
                  && node.order.acceptance_seq > last_seq);
                assert (
                  Hashtbl.find t.active node.order.key == node
                  && Hashtbl.find ledger node.order.key == node.order);
                (match (previous, node.prev) with
                | None, None -> ()
                | Some a, Some b -> assert (a == b)
                | _ -> assert false);
                walk (Some node) node.order.acceptance_seq (add count 1L)
                  (add quantity node.order.remaining)
                  node.next
          in
          walk None 0L 0L 0L level.head)
        (levels t side))
    [ Buy; Sell ];
  assert (Hashtbl.length seen = Hashtbl.length t.active);
  Hashtbl.iter
    (fun k o ->
      assert (o.status = Active = Hashtbl.mem seen k);
      assert (o.original = add o.filled (add o.cancelled o.remaining));
      assert (o.status = Cancelled = (o.cancelled > 0L)))
    ledger;
  match (Prices.max_binding_opt t.bids, Prices.min_binding_opt t.asks) with
  | Some (bid, _), Some (ask, _) -> assert (bid < ask)
  | _ -> ()
