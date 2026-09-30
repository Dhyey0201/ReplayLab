#include <time.h>
#include <sys/resource.h>
#include <caml/mlvalues.h>
#include <caml/alloc.h>
#include <caml/fail.h>

CAMLprim value replaylab_monotonic_ns(value unit) {
  struct timespec now;
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) caml_failwith("clock_gettime failed");
  return caml_copy_int64((int64_t)now.tv_sec * 1000000000LL + now.tv_nsec);
}
CAMLprim value replaylab_peak_rss(value unit) {
  struct rusage usage;
  if (getrusage(RUSAGE_SELF, &usage) != 0) caml_failwith("getrusage failed");
#ifdef __APPLE__
  return caml_copy_int64((int64_t)usage.ru_maxrss);
#else
  return caml_copy_int64((int64_t)usage.ru_maxrss * 1024);
#endif
}
