# In-session Chronicle raw-chunk probe. Loaded and flattened to a single console
# line by chronicle_probe.py; the test sends it via rstudio_eval and reads back
# the sentinel token this function returns.
#
# Chronicle writes each metric's raw telemetry to
#   <base_path>/<store>/<server-id>/v2/<metric>/<Y>/<M>/<D>/<H>/<chunk>.csv
# where <store> is "private" or "hourly". Chunk filenames are unstable (mostly
# bare UUIDs, sometimes a "chronicle-data-*" stem), so we match any .csv/.parquet
# file under the metric's "/v2/<metric>/" directory rather than a filename prefix.
# The trailing slash stops a metric from matching a longer one that shares its
# prefix. We read the newest non-empty chunk to confirm the session user can
# actually read collected rows. We first require the chunk to be readable at all
# (file.access mode 4) so a chunk the session user cannot open -- e.g. permission
# denied -- reports VIP_NO_DATA rather than a false positive. n is then its line
# count (NA when the readable file is not text, e.g. a Parquet chunk), so a CSV
# with a header plus >= 1 row has n > 1.
#
# Returns exactly one sentinel token:
#   "VIP_DATA_OK"   a non-empty chunk exists and holds >= 1 data row
#   "VIP_NO_DATA"   no readable, non-empty chunk exists for the metric
#
# chronicle_probe.py flattens this file by dropping comment/blank lines and
# joining the rest with "; ", so every line below must be a complete R statement:
# no line-spanning calls, no bare "} else", and no inline "#" comments.
vip_chronicle_probe <- function(base_path, metric) {
  files <- list.files(base_path, pattern = "[.](csv|parquet)$", recursive = TRUE, full.names = TRUE)
  files <- files[grepl(paste0("/v2/", metric, "/"), files, fixed = TRUE)]
  files <- files[file.info(files)$size > 0]
  if (length(files) == 0) return("VIP_NO_DATA")
  newest <- files[order(file.info(files)$mtime, decreasing = TRUE)][[1]]
  if (file.access(newest, mode = 4) != 0) return("VIP_NO_DATA")
  n <- tryCatch(length(readLines(newest, warn = FALSE)), error = function(e) NA_integer_)
  if (is.na(n) || n > 1) "VIP_DATA_OK" else "VIP_NO_DATA"
}
