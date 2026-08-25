#!/bin/bash -eu
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################


ARCHITECTURE=$(uname -m)

cd $SRC/testdir

# The lunapark C API tests link libFuzzer through C targets, so they need an
# explicit C++ standard library after $ENV{LIB_FUZZING_ENGINE}. In our images
# libFuzzer is built against libstdc++, not libc++.
sed -i 's/[[:space:]]-lc++/ -lstdc++/g' tests/capi/CMakeLists.txt
# if [[ "${FUZZING_ENGINE:-}" == "centipede" ]]
# then
#     sed -i \
#         's/[[:space:]]-lstdc++/ -lc++/g' \
#         tests/capi/CMakeLists.txt
#     sed -i \
#         '/$ENV{LIB_FUZZING_ENGINE}/a \ \ \ \ \ \ \ \ -lc++' \
#         tests/capi/CMakeLists.txt
# fi

# # Clean up potentially persistent build directory.
[[ -e $SRC/testdir/build ]] && rm -rf $SRC/testdir/build

# case $SANITIZER in
#   address) SANITIZERS_ARGS="-DENABLE_ASAN=ON" ;;
#   undefined) SANITIZERS_ARGS="-DENABLE_UBSAN=ON" ;;
#   *) SANITIZERS_ARGS="" ;;
# esac

export LSAN_OPTIONS="verbosity=1:log_threads=1"

# Workaround for a LeakSanitizer crashes,
# see https://github.com/google/oss-fuzz/issues/11798.
# if [ "$ARCHITECTURE" = "aarch64" ]; then
#     export ASAN_OPTIONS=detect_leaks=0
# fi

: ${LD:="${CXX}"}
: ${LDFLAGS:="${CXXFLAGS}"}  # to make sure we link with sanitizer runtime

cmake_args=(
    -DUSE_LUA=ON
    -DOSS_FUZZ=ON
    -DENABLE_BUILD_PROTOBUF=FALSE
    $SANITIZERS_ARGS
    
    # C compiler
    -DCMAKE_C_COMPILER="${CC}"
    -DCMAKE_C_FLAGS="${CFLAGS}"

    # C++ compiler
    -DCMAKE_CXX_COMPILER="${CXX}"
    -DCMAKE_CXX_FLAGS="${CXXFLAGS}"

    # Linker
    -DCMAKE_LINKER="${LD}"
    -DCMAKE_EXE_LINKER_FLAGS="${LDFLAGS}"
    -DCMAKE_MODULE_LINKER_FLAGS="${LDFLAGS}"
    -DCMAKE_SHARED_LINKER_FLAGS="${LDFLAGS}"
)

# To deal with a host filesystem from inside of container.
git config --global --add safe.directory '*'

# Build the project and fuzzers.
[[ -e build ]] && rm -rf build
cmake "${cmake_args[@]}" -S . -B build -G Ninja
cmake --build build --parallel --verbose

LUALIB_PATH="$SRC/testdir/build/lua-master/source/"
AFL_RT=""
AFL_SAN_COV=""
if [[ "${CC}" == *afl-clang-fast* ]] || [[ "${CXX}" == *afl-clang-fast* ]]; then
  AFL_SAN_COV="-fsanitize-coverage=trace-pc-guard"
fi
for cand in /afl/afl-compiler-rt.o /afl/afl-compiler-rt-64.o; do
  if [[ -f "$cand" ]]; then
    AFL_RT="$cand"
    break
  fi
done
$CC $CFLAGS $AFL_SAN_COV -I$LUALIB_PATH -c $SRC/fuzz_lua.c -o fuzz_lua.o
$CXX $CXXFLAGS $AFL_SAN_COV $LIB_FUZZING_ENGINE fuzz_lua.o -o $OUT/fuzz_lua $LUALIB_PATH/liblua.a $AFL_RT

# If the dict filename is the same as your target binary name
# (i.e. `%fuzz_target%.dict`), it will be automatically used.
# If the name is different (e.g. because it is shared by several
# targets), specify this in .options file.
# cp corpus_dir/*.dict corpus_dir/*.options $OUT/

# Archive and copy to $OUT seed corpus if the build succeeded.
# for f in $(find build/tests/ -name '*_test' -type f);
# do
#   name=$(basename $f);
#   module=$(echo $name | sed 's/_test//')
#   corpus_dir="corpus_dir/$module"
#   echo "Copying for $module";
#   cp $f $OUT/
#   [[ -e $corpus_dir ]] && find "$corpus_dir" -mindepth 1 -maxdepth 1 | zip -@ -j $OUT/"$name"_seed_corpus.zip
# done

echo "Lua build.sh done"
