# syntax=docker/dockerfile:1.7
FROM parent_image

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /work

RUN git clone \
        --depth 1 \
        --branch v2.57b \
        https://github.com/google/AFL.git /afl && \
    cd /afl && \
    CFLAGS= CXXFLAGS= AFL_NO_X86=1 make

# Use afl_driver.cpp from LLVM as our fuzzing library.
RUN wget https://raw.githubusercontent.com/llvm/llvm-project/5feb80e748924606531ba28c97fe65145c65372e/compiler-rt/lib/fuzzer/afl/afl_driver.cpp -O /afl/afl_driver.cpp && \
    clang -Wno-pointer-sign -c /afl/llvm_mode/afl-llvm-rt.o.c -I/afl && \
    clang++ -std=c++11 -O2 -c /afl/afl_driver.cpp && \
    ar r /libAFL.a *.o
