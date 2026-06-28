#!/usr/bin/env bash
set -euo pipefail

ARGS='is_asan = true
 is_component_build = false
 use_clang_modules = false
 symbol_level = 2
 forbid_non_component_debug_builds = false
 use_debug_fission = false
 use_dwarf5 = true
 target_cpu = "x64"
 target_os = "linux"
 use_reclient = false
 use_remoteexec = false
 use_siso = false
 treat_warnings_as_errors = false
 libcxx_is_shared = false
 v8_enable_backtrace = true
 v8_enable_slow_dchecks = true
 v8_enable_test_features = true
 v8_enable_fast_mksnapshot = true
 v8_enable_sandbox = true
 v8_enable_memory_corruption_api = true'

if [[ -n "${INDEXER_BUILD:-}" ]]; then
  ARGS="${ARGS} is_debug=true v8_optimized_debug=false v8_enable_slow_dchecks=true clang_base_path=\"/opt/toolchain\""
else
  ARGS="${ARGS} is_debug=true v8_optimized_debug=false v8_enable_slow_dchecks=true"
fi

gn gen out/fuzz --args="${ARGS}"

rm -f out/fuzz/d8
ninja -C out/fuzz d8 -j"$(nproc)"

cp ./out/fuzz/{d8,snapshot_blob.bin,*.so,icudtl.dat} "${OUT}"
